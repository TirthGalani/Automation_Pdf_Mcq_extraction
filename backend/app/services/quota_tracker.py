import json
import time
import datetime
import threading
from pathlib import Path
from typing import Dict, Any, Optional
from app.logger import get_logger

logger = get_logger("quota_tracker")

QUOTA_CACHE_FILE = Path(__file__).resolve().parent.parent.parent / ".quota_cache.json"
FREE_TIER_DAILY_LIMIT_PER_KEY = 1500  # Google Gemini standard free tier requests per day (RPD)


class QuotaTracker:
    """Thread-safe persistent tracker for Gemini API daily requests, tokens, and model health."""

    def __init__(self):
        self._lock = threading.Lock()
        self._cache_file = QUOTA_CACHE_FILE
        self._data = self._load_data()

    def _get_today_str(self) -> str:
        return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")

    def _load_data(self) -> Dict[str, Any]:
        today = self._get_today_str()
        default_data = {
            "date": today,
            "requests_today": 0,
            "input_tokens_today": 0,
            "output_tokens_today": 0,
            "total_tokens_today": 0,
            "models_usage": {},
            "exhausted_models": {},
            "rate_limited_models": {},
            "recent_events": [],
        }

        if self._cache_file.exists():
            try:
                with open(self._cache_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if data.get("date") == today:
                        # Merge with defaults
                        for k, v in default_data.items():
                            if k not in data:
                                data[k] = v
                        return data
            except Exception:
                pass

        return default_data

    def _save_data(self):
        try:
            with open(self._cache_file, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2, ensure_ascii=False)
        except Exception:
            pass

    def record_request(
        self,
        model_name: str,
        input_tokens: int = 0,
        output_tokens: int = 0,
        is_error: bool = False,
        error_type: Optional[str] = None
    ):
        """Records a completed Gemini API request and token consumption."""
        today = self._get_today_str()
        with self._lock:
            if self._data.get("date") != today:
                self._data = {
                    "date": today,
                    "requests_today": 0,
                    "input_tokens_today": 0,
                    "output_tokens_today": 0,
                    "total_tokens_today": 0,
                    "models_usage": {},
                    "exhausted_models": {},
                    "rate_limited_models": {},
                    "recent_events": [],
                }

            if not is_error:
                self._data["requests_today"] += 1
                self._data["input_tokens_today"] += input_tokens
                self._data["output_tokens_today"] += output_tokens
                self._data["total_tokens_today"] += (input_tokens + output_tokens)

                if model_name not in self._data["models_usage"]:
                    self._data["models_usage"][model_name] = {"calls": 0, "tokens": 0, "last_used": 0}

                self._data["models_usage"][model_name]["calls"] += 1
                self._data["models_usage"][model_name]["tokens"] += (input_tokens + output_tokens)
                self._data["models_usage"][model_name]["last_used"] = time.time()

                # Clear exhausted/rate limited flags on success
                self._data["exhausted_models"].pop(model_name, None)
                self._data["rate_limited_models"].pop(model_name, None)

            elif error_type == "daily_quota":
                self._data["exhausted_models"][model_name] = time.time()
            elif error_type == "rate_limit":
                self._data["rate_limited_models"][model_name] = time.time()

            # Keep last 10 events for audit
            event = {
                "time": datetime.datetime.now(datetime.timezone.utc).strftime("%H:%M:%S"),
                "model": model_name,
                "type": "error" if is_error else "success",
                "detail": error_type if is_error else f"+{input_tokens + output_tokens} tokens"
            }
            self._data["recent_events"] = [event] + self._data["recent_events"][:9]
            self._save_data()

    def reset_quota(self):
        """Resets today's tracked usage and clears exhausted/rate-limited model flags."""
        today = self._get_today_str()
        with self._lock:
            self._data = {
                "date": today,
                "requests_today": 0,
                "input_tokens_today": 0,
                "output_tokens_today": 0,
                "total_tokens_today": 0,
                "models_usage": {},
                "exhausted_models": {},
                "rate_limited_models": {},
                "recent_events": [],
            }
            self._save_data()

    def get_quota_status(self, api_keys_count: int = 1, current_model: str = "gemini-3.5-flash") -> Dict[str, Any]:
        """Calculates current daily quota usage and limit remaining percentage."""
        today = self._get_today_str()
        with self._lock:
            if self._data.get("date") != today:
                self._data = self._load_data()

            keys_count = max(1, api_keys_count)
            total_limit = FREE_TIER_DAILY_LIMIT_PER_KEY * keys_count
            used = self._data.get("requests_today", 0)
            remaining = max(0, total_limit - used)
            percent_remaining = round((remaining / total_limit) * 100.0, 1)

            # Check models status and per-model quota metrics
            model_limits = {
                "gemini-3.6-flash": 1500 * keys_count,
                "gemini-3.5-flash": 1500 * keys_count,
                "gemini-3.5-flash-lite": 1500 * keys_count,
                "gemini-3.7-flash": 1500 * keys_count,
                "gemini-3.7-flash-lite": 1500 * keys_count,
                "gemini-3.1-pro": 300 * keys_count,
                "gemini-3.1-flash-lite": 1500 * keys_count,
                "gemini-2.5-flash": 1500 * keys_count,
                "gemini-2.5-pro": 300 * keys_count,
                "gemini-2.0-flash": 1500 * keys_count,
                "gemini-2.0-flash-lite": 1500 * keys_count,
                "gemini-1.5-flash": 1500 * keys_count,
                "gemini-1.5-pro": 50 * keys_count,
                "gemma-4-26b-a4b-it": 1500 * keys_count,
                "gemma-4-31b-it": 1500 * keys_count,
            }
            known_models = list(model_limits.keys())

            models_info = {}
            for m in known_models:
                m_limit = model_limits.get(m, 1500 * keys_count)
                usage = self._data.get("models_usage", {}).get(m, {})
                calls = usage.get("calls", 0)

                if m in self._data.get("exhausted_models", {}):
                    status = "Daily Quota Hit"
                    badge = "exhausted"
                    m_remaining = 0
                    m_percent = 0.0
                elif m in self._data.get("rate_limited_models", {}):
                    status = "Rate Limited"
                    badge = "rate_limited"
                    m_remaining = max(0, m_limit - calls)
                    m_percent = round((m_remaining / m_limit) * 100.0, 1)
                elif m == current_model:
                    status = "Active & Ready"
                    badge = "active"
                    m_remaining = max(0, m_limit - calls)
                    m_percent = round((m_remaining / m_limit) * 100.0, 1)
                else:
                    status = "Ready / Standby"
                    badge = "ready"
                    m_remaining = max(0, m_limit - calls)
                    m_percent = round((m_remaining / m_limit) * 100.0, 1)

                models_info[m] = {
                    "status": status,
                    "badge": badge,
                    "daily_limit": m_limit,
                    "calls_today": calls,
                    "requests_remaining": m_remaining,
                    "percent_remaining": m_percent,
                    "tokens_today": usage.get("tokens", 0)
                }

            now_utc = datetime.datetime.now(datetime.timezone.utc)
            next_midnight_utc = (now_utc + datetime.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            seconds_until_reset = max(0, int((next_midnight_utc - now_utc).total_seconds()))
            hours_left = seconds_until_reset // 3600
            mins_left = (seconds_until_reset % 3600) // 60
            reset_in_human = f"{hours_left}h {mins_left}m"

            return {
                "date": today,
                "daily_limit_per_key": FREE_TIER_DAILY_LIMIT_PER_KEY,
                "total_daily_limit": total_limit,
                "requests_used_today": used,
                "requests_remaining": remaining,
                "percent_remaining": percent_remaining,
                "reset_in_seconds": seconds_until_reset,
                "reset_in_human": reset_in_human,
                "reset_at_utc": next_midnight_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "reset_hours": hours_left,
                "reset_minutes": mins_left,
                "input_tokens_today": self._data.get("input_tokens_today", 0),
                "output_tokens_today": self._data.get("output_tokens_today", 0),
                "total_tokens_today": self._data.get("total_tokens_today", 0),
                "api_keys_count": keys_count,
                "current_model": current_model,
                "models": models_info,
                "recent_events": self._data.get("recent_events", [])
            }


# Singleton instance
quota_tracker = QuotaTracker()


def is_openrouter_key(api_key: Optional[str]) -> bool:
    if not api_key:
        return False
    k = api_key.strip()
    return k.startswith("sk-or-") or k.startswith("sk-")


def map_to_openrouter_model(model_name: str) -> str:
    m = (model_name or "").strip()
    if "/" in m:
        return m
    m_lower = m.lower()
    if "gemma-4-26b" in m_lower or "gemma-4" in m_lower or "26b" in m_lower:
        return "google/gemma-4-26b-a4b-it"
    if "pro" in m_lower:
        return "google/gemini-2.5-pro"
    if "1.5" in m_lower:
        return "google/gemini-flash-1.5"
    if "2.0" in m_lower:
        return "google/gemini-2.0-flash-001"
    return "google/gemini-2.5-flash"


def test_openrouter_api_key(api_key: str, model_name: str = "google/gemini-2.5-flash") -> Dict[str, Any]:
    """Tests OpenRouter API key connectivity and model availability with auto-fallback to free tier."""
    import urllib.request
    import urllib.error
    import json

    if not api_key or len(api_key.strip()) < 5:
        return {
            "success": False,
            "status": "missing_key",
            "message": "No API Key provided. Please enter a valid OpenRouter API Key."
        }

    t0 = time.time()
    initial_model = map_to_openrouter_model(model_name)
    models_to_test = [
        initial_model,
        "google/gemma-4-26b-a4b-it",
        "google/gemini-2.5-flash",
        "google/gemini-2.5-pro",
        "qwen/qwen-2.5-vl-72b-instruct:free",
        "meta-llama/llama-3.2-11b-vision-instruct:free",
        "google/gemma-4-31b-it:free",
        "openrouter/free"
    ]
    seen = set()
    test_queue = [m for m in models_to_test if not (m in seen or seen.add(m))]

    last_error_msg = ""
    for test_model in test_queue:
        payload = {
            "model": test_model,
            "messages": [{"role": "user", "content": "Say 'OK'"}],
            "max_tokens": 10,
            "temperature": 0.0
        }
        req = urllib.request.Request(
            "https://openrouter.ai/api/v1/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key.strip()}",
                "Content-Type": "application/json",
                "HTTP-Referer": "http://localhost:2211",
                "X-Title": "Question Extractor"
            }
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                latency_ms = int((time.time() - t0) * 1000)
                resp_text = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
                quota_tracker.record_request(test_model, input_tokens=5, output_tokens=2)
                return {
                    "success": True,
                    "status": "online",
                    "model": f"OpenRouter ({test_model})",
                    "latency_ms": latency_ms,
                    "response": resp_text,
                    "message": f"OpenRouter API Key is 100% active and healthy! Connected in {latency_ms}ms ({test_model})."
                }
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="ignore")
            if e.code == 401:
                return {
                    "success": False,
                    "status": "invalid_key",
                    "model": test_model,
                    "message": "Invalid OpenRouter API Key (HTTP 401). Please verify your OpenRouter key."
                }
            elif e.code == 402:
                last_error_msg = f"Model {test_model} requires credits. Trying free model..."
                continue
            elif e.code == 429:
                last_error_msg = f"Rate limited on {test_model} (HTTP 429)."
                continue
            else:
                last_error_msg = f"OpenRouter API Error ({e.code}): {err_body[:120]}"
        except Exception as e:
            last_error_msg = f"OpenRouter connection error: {str(e)[:120]}"

    return {
        "success": False,
        "status": "error",
        "model": initial_model,
        "message": last_error_msg or "OpenRouter connection failed on all test models."
    }


def test_gemini_api_key(api_key: str, model_name: str = "gemini-3.5-flash") -> Dict[str, Any]:
    """Lightweight test to verify API key connectivity and remaining quota status with Gemini or OpenRouter."""
    if not api_key or len(api_key.strip()) < 5:
        return {
            "success": False,
            "status": "missing_key",
            "message": "No API Key provided. Please enter a valid API Key."
        }

    if is_openrouter_key(api_key):
        return test_openrouter_api_key(api_key=api_key, model_name=model_name)

    try:
        from google import genai
        from google.genai import types

        t0 = time.time()
        alias_map = {
            "gemma-4-26b": "gemma-4-26b-a4b-it",
            "google/gemma-4-26b-a4b-it": "gemma-4-26b-a4b-it",
            "gemini-flash": "gemini-3.5-flash",
            "gemini-flash-lite": "gemini-3.1-flash-lite",
        }
        eff_model = alias_map.get(model_name, model_name)

        client = genai.Client(api_key=api_key.strip())
        response = client.models.generate_content(
            model=eff_model,
            contents="Say 'OK'",
            config=types.GenerateContentConfig(
                max_output_tokens=100,
                temperature=0.0
            )
        )
        latency_ms = int((time.time() - t0) * 1000)
        resp_text = (response.text or "").strip()

        quota_tracker.record_request(model_name, input_tokens=5, output_tokens=2)

        return {
            "success": True,
            "status": "online",
            "model": model_name,
            "latency_ms": latency_ms,
            "response": resp_text,
            "message": f"API Key is 100% active and healthy! Response received in {latency_ms}ms."
        }

    except Exception as e:
        err_str = str(e)
        if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
            quota_tracker.record_request(model_name, is_error=True, error_type="daily_quota")
            return {
                "success": False,
                "status": "quota_exhausted",
                "model": model_name,
                "message": "API Quota Limit reached (HTTP 429: Resource Exhausted). Please add another backup key."
            }
        elif "400" in err_str or "API_KEY_INVALID" in err_str or "invalid" in err_str.lower():
            return {
                "success": False,
                "status": "invalid_key",
                "model": model_name,
                "message": "Invalid API Key. Please check the key and try again."
            }
        else:
            return {
                "success": False,
                "status": "error",
                "model": model_name,
                "message": f"API Error: {err_str[:120]}"
            }
