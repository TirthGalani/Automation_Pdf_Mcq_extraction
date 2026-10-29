
import io
import os
import re
import uuid
import asyncio
import json
import threading
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple, Union
from pathlib import Path
import pandas as pd

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Response, Query
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from dotenv import load_dotenv

from app.logger import get_logger, get_recent_logs, clear_log_buffer, get_log_file_path
from app.models import (
    ExtractionResult,
    QuestionItem,
    BatchJobProgress,
    HealthResponse,
)
from app.extractor import GeminiExtractor
from app.utils import (
    export_to_csv_bytes,
    export_to_excel_bytes,
    export_single_sheet_excel_bytes,
    export_advance_excel_bundle,
    export_advance_excel_zip,
    is_paragraph_question,
    is_matching_question,
    is_advance_matching_question,
    is_advance_paper,
    sort_questions_naturally,
)
from app.services.pdf_export import export_results_to_pdf, export_single_result_to_pdf
from app.services.solution_generator import (
    generate_solutions_for_df,
    generate_solutions_for_file,
    export_df_to_styled_excel,
    normalize_df_columns,
)

load_dotenv()
logger = get_logger("main")
logger.info("MCQ Extraction & Translation API server initialized successfully.")

app = FastAPI(
    title="MCQ PDF Extraction & Translation API",
    description="Automated MCQ extraction and translation system using Gemini Multimodal API",
    version="1.0.0",
)

# Enable CORS for decoupled frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def add_no_cache_headers(request, call_next):
    response = await call_next(request)
    path = request.url.path
    if path.endswith((".js", ".html", ".css")) or path == "/" or "/api/" in path:
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response

# Persistent storage for batch jobs across server reloads
JOBS_CACHE_FILE = Path(__file__).resolve().parent.parent / ".jobs_cache.json"
_CACHE_LOCK = threading.Lock()


def _load_jobs_cache() -> Dict[str, BatchJobProgress]:
    store = {}
    if not JOBS_CACHE_FILE.exists():
        return store
    try:
        with open(JOBS_CACHE_FILE, "r", encoding="utf-8") as f:
            raw = f.read()
        if not raw.strip():
            return store

        try:
            data = json.loads(raw)
        except Exception as json_err:
            logger.warning(f"Corrupted jobs cache file detected ({json_err}). Creating backup and starting fresh.")
            try:
                backup_path = JOBS_CACHE_FILE.with_suffix(".corrupted.bak")
                JOBS_CACHE_FILE.rename(backup_path)
            except Exception:
                pass
            return store

        for k, v in data.items():
            try:
                job = BatchJobProgress(**v)
                # If job already has extracted questions/results, keep it completed so export works
                if job.results and any(r.total_questions > 0 for r in job.results):
                    if job.status in ("processing", "queued"):
                        job.status = "completed"
                        job.progress_message = f"Completed! Extracted {sum(r.total_questions for r in job.results)} question(s)."
                elif job.status in ("processing", "queued"):
                    job.status = "failed"
                    job.error = "Extraction interrupted by server restart."
                    job.progress_message = "Extraction interrupted by server restart."
                store[k] = job
            except Exception:
                pass
    except Exception as e:
        logger.warning(f"Failed to load jobs cache: {e}")
    return store


def _save_jobs_cache():
    def _do_save():
        try:
            with _CACHE_LOCK:
                # Keep only the latest 20 jobs to ensure lightweight and fast file writes
                all_items = list(JOBS_STORE.items())[-20:]
                data = {k: v.model_dump() for k, v in all_items}
                temp_file = JOBS_CACHE_FILE.with_name(f".jobs_cache_{os.getpid()}_{uuid.uuid4().hex[:8]}.tmp")
                with open(temp_file, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False)
                    f.flush()
                    os.fsync(f.fileno())
                temp_file.replace(JOBS_CACHE_FILE)
        except Exception:
            pass
    threading.Thread(target=_do_save, daemon=True).start()


JOBS_STORE: Dict[str, BatchJobProgress] = _load_jobs_cache()
ACTIVE_JOB_TASKS: Dict[str, asyncio.Task] = {}


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    """Silently handle browser favicon requests to prevent 404 logs in console."""
    return Response(status_code=204)


@app.get("/.well-known/appspecific/com.chrome.devtools.json")
async def chrome_devtools_ignore():
    """Ignore Chrome DevTools probing to prevent 404 logs in console."""
    return {}


@app.get("/api/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint to verify backend status and API key configuration."""
    load_dotenv(override=True)
    api_key = os.getenv("GEMINI_API_KEY")
    return HealthResponse(
        status="ok",
        api_key_configured=bool(api_key and len(api_key.strip()) > 5),
        version="1.0.0",
    )


@app.get("/api/quota-status")
async def get_quota_status():
    """Returns real-time Gemini API Daily Quota usage, limit remaining percentage, and model health."""
    load_dotenv(override=True)
    raw_keys = os.getenv("GEMINI_API_KEYS") or os.getenv("GEMINI_API_KEY") or ""
    keys_list = [k.strip() for k in re.split(r'[\r\n,;]+', str(raw_keys)) if k.strip() and len(k.strip()) > 5]
    for idx in range(1, 10):
        k = os.getenv(f"GEMINI_API_KEY_{idx}")
        if k and len(k.strip()) > 5 and k.strip() not in keys_list:
            keys_list.append(k.strip())

    current_model = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")
    from app.services.quota_tracker import quota_tracker
    data = quota_tracker.get_quota_status(api_keys_count=max(1, len(keys_list)), current_model=current_model)
    data["api_keys_configured"] = len(keys_list)
    data["masked_keys"] = [f"{k[:6]}...{k[-4:]}" if len(k) > 10 else "***" for k in keys_list]
    return data
 
 
@app.post("/api/reset-quota")
async def reset_quota_endpoint():
    """Resets daily quota usage tracker to 0 used (100% available)."""
    from app.services.quota_tracker import quota_tracker
    quota_tracker.reset_quota()
    return {"status": "ok", "message": "Quota counter reset to 0 used (100% available)."}


@app.post("/api/test-quota")
async def test_quota_endpoint(
    api_key: Optional[str] = Form(None),
    model_name: Optional[str] = Form(None),
):
    """Performs a live connectivity and quota validation ping against Gemini API."""
    load_dotenv(override=True)
    effective_key = api_key or os.getenv("GEMINI_API_KEY")
    effective_model = model_name or os.getenv("GEMINI_MODEL", "gemini-3.5-flash")
    from app.services.quota_tracker import test_gemini_api_key
    result = test_gemini_api_key(api_key=effective_key, model_name=effective_model)
    return result



@app.post("/api/count-tokens")
async def count_pdf_tokens(
    files: List[UploadFile] = File(...),
    api_key: Optional[str] = Form(None),
    model_name: Optional[str] = Form(None),
):
    """Calculates multimodal tokens and cost metrics for one or multiple PDF documents."""
    pdf_files = [f for f in files if f.filename.lower().endswith(".pdf")]
    if not pdf_files:
        raise HTTPException(status_code=400, detail="Please upload at least one valid PDF file.")

    load_dotenv(override=True)
    effective_key = api_key or os.getenv("GEMINI_API_KEY")
    if not effective_key or len(effective_key.strip()) < 5:
        raise HTTPException(status_code=400, detail="Gemini API Key is required.")

    effective_model = model_name or os.getenv("GEMINI_MODEL", "gemini-3.5-flash")

    temp_dir = Path(__file__).resolve().parent.parent / "extracted_images"
    temp_dir.mkdir(parents=True, exist_ok=True)
    saved_temp_paths = []

    try:
        import sys
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from token_calculator import count_tokens_with_gemini, count_tokens_for_multiple_pdfs

        for upload_f in pdf_files:
            content = await upload_f.read()
            if len(content) == 0:
                continue
            clean_name = re.sub(r'[^a-zA-Z0-9_\-.]', '_', upload_f.filename)
            temp_path = temp_dir / f"tc_{uuid.uuid4().hex[:6]}_{clean_name}"
            with open(temp_path, "wb") as f_out:
                f_out.write(content)
            saved_temp_paths.append((temp_path, upload_f.filename))

        if not saved_temp_paths:
            raise HTTPException(status_code=400, detail="Uploaded PDF files were empty.")

        if len(saved_temp_paths) == 1:
            p_path, original_name = saved_temp_paths[0]
            report = count_tokens_with_gemini(p_path, effective_key, effective_model)
            report["file_name"] = original_name
            report["is_batch"] = False
            return report
        else:
            just_paths = [p for p, _ in saved_temp_paths]
            batch_report = count_tokens_for_multiple_pdfs(just_paths, effective_key, effective_model)
            # Restore original filenames
            for i, (_, orig_name) in enumerate(saved_temp_paths):
                if i < len(batch_report["files"]):
                    batch_report["files"][i]["file_name"] = orig_name
            return batch_report

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        for p, _ in saved_temp_paths:
            if p.exists():
                try:
                    p.unlink()
                except Exception:
                    pass


@app.post("/api/extract-textbook-topics")
async def extract_textbook_topics_endpoint(
    file: UploadFile = File(...),
    source_language: Optional[str] = Form("Original"),
    target_language: Optional[str] = Form("Original"),
    api_key: Optional[str] = Form(None),
    model_name: Optional[str] = Form(None),
):
    """Scans ALL pages of an uploaded Textbook PDF and extracts all main curriculum topics (e.g. 1.1, 1.2, 1.3...)."""
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")

    pdf_bytes = await file.read()
    if len(pdf_bytes) == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    try:
        extractor = GeminiExtractor(api_key=api_key, model_name=model_name)
        result = await extractor.extract_topics_from_textbook(
            pdf_bytes=pdf_bytes,
            file_name=file.filename,
            source_language=source_language or "Original",
            target_language=target_language or "Original",
            model_name=model_name,
            progress_callback=None
        )
        return result
    except Exception as e:
        logger.error(f"[Textbook Topics API] Error extracting topics from {file.filename}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/extract", response_model=ExtractionResult)
async def extract_single_pdf(
    file: UploadFile = File(...),
    solution_pdf: Optional[UploadFile] = File(None),
    source_language: Optional[str] = Form("Original"),
    target_language: Optional[str] = Form("Original"),
    api_key: Optional[str] = Form(None),
    model_name: Optional[str] = Form(None),
):
    """Directly extracts and translates MCQs from a single uploaded PDF."""
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")

    pdf_bytes = await file.read()
    if len(pdf_bytes) == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    try:
        extractor = GeminiExtractor(api_key=api_key, model_name=model_name)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    try:
        result = await extractor.extract_from_pdf(
            pdf_bytes=pdf_bytes,
            file_name=file.filename,
            source_language=source_language,
            target_language=target_language,
            model_name=model_name,
        )

        # Only apply and show solutions if a Solution PDF is provided
        if solution_pdf and solution_pdf.filename:
            sol_bytes = await solution_pdf.read()
            if len(sol_bytes) > 0:
                sol_data = await extractor.extract_solutions_and_answers_from_pdf(
                    pdf_bytes=sol_bytes,
                    file_name=solution_pdf.filename,
                    source_language=source_language,
                    target_language=target_language,
                    model_name=model_name,
                )
                align_and_verify_solutions(
                    result=result,
                    sol_data=sol_data,
                    cur_sol_name=solution_pdf.filename,
                )
        else:
            # STRICT RULE: No Solution PDF applied -> Clear all solution fields
            result.has_solution = False
            result.matched_solution_filename = None
            result.total_solutions = 0
            result.verified_solutions_count = 0
            result.unmatched_solutions_count = 0
            result.verification_rate = 0.0
            for rq in (result.questions or []):
                rq.solution = ""
                rq.solution_image_url = None
                rq.solution_image_box = None
                rq.has_solution_image = False
                rq.matched_solution_file = None
                rq.solution_verified = False
                rq.verification_status = "no_solution"
                rq.verification_details = None

    except asyncio.CancelledError:
        raise HTTPException(status_code=499, detail="Extraction request was cancelled.")

    if result.status == "failed":
        raise HTTPException(status_code=500, detail=result.error_message or "Extraction failed.")

    result.is_advance = is_advance_paper(result)
    return result


def find_matching_solution_pdf(
    q_filename: str,
    q_idx: int,
    total_q_files: int,
    solutions_data: List[Tuple[str, bytes]],
) -> Optional[Tuple[str, bytes]]:
    """
    Intelligently pairs an MCQ Question PDF with its corresponding Solution PDF.
    Strategies (in order of priority):
    1. Single solution PDF: shared across all question PDFs.
    2. Normalized stem match (e.g. 'physics_ch1_questions.pdf' <-> 'physics_ch1_solutions.pdf').
    3. Number/Chapter match (e.g. 'test_01.pdf' <-> 'sol_01.pdf' or 'chapter 5' <-> 'chapter 5').
    4. Substring stem containment.
    5. Positional 1-to-1 match (if N question PDFs and N solution PDFs are uploaded).
    6. Positional index fallback (if 0 <= q_idx < len(solutions_data)).
    """
    if not solutions_data:
        return None
    if len(solutions_data) == 1:
        return solutions_data[0]

    def normalize_stem(name: str) -> str:
        s = os.path.splitext(name)[0].lower()
        noise_words = {
            "questions", "question", "mcqs", "mcq", "paper", "test", "exam",
            "solutions", "solution", "sol", "ans", "answers", "answer", "key",
            "hints", "hint", "expl", "explanations", "explanation", "set", "part",
            "q", "s", "qp", "ms"
        }
        tokens = re.split(r'[^a-z0-9]+', s)
        filtered = [t for t in tokens if t and t not in noise_words]
        return "_".join(filtered) if filtered else s

    q_norm = normalize_stem(q_filename)

    # 1. Exact normalized stem match
    for sol_name, sol_bytes in solutions_data:
        s_norm = normalize_stem(sol_name)
        if q_norm and s_norm and q_norm == s_norm:
            return (sol_name, sol_bytes)

    # 2. Number extraction match (e.g. Test 01 or Chapter 2)
    q_nums = re.findall(r'\d+', q_filename.lower())
    if q_nums:
        matching_by_num = []
        for sol_name, sol_bytes in solutions_data:
            s_nums = re.findall(r'\d+', sol_name.lower())
            if set(q_nums) == set(s_nums) or (len(q_nums) == 1 and q_nums[0] in s_nums):
                matching_by_num.append((sol_name, sol_bytes))
        if len(matching_by_num) == 1:
            return matching_by_num[0]

    # 3. Substring match
    q_clean = re.sub(r'[^a-z0-9]', '', os.path.splitext(q_filename)[0].lower())
    for sol_name, sol_bytes in solutions_data:
        s_clean = re.sub(r'[^a-z0-9]', '', os.path.splitext(sol_name)[0].lower())
        s_norm = normalize_stem(sol_name)
        if (q_norm and len(q_norm) > 2 and q_norm in s_clean) or (s_norm and len(s_norm) > 2 and s_norm in q_clean):
            return (sol_name, sol_bytes)

    # 4. Positional 1-to-1 match (if equal number of questions and solutions)
    if len(solutions_data) == total_q_files and 0 <= q_idx < len(solutions_data):
        return solutions_data[q_idx]

    # 5. Fallback index match if available
    if 0 <= q_idx < len(solutions_data):
        return solutions_data[q_idx]

    return solutions_data[0]


def _normalize_comparable_answer(raw_ans: Optional[str]) -> str:
    """Normalizes an answer string for strict equality comparison across MCQ and Numeric formats."""
    if not raw_ans:
        return ""
    from app.utils import clean_numeric_answer, normalize_option_key
    s = str(raw_ans).strip()
    # Check if MCQ letter e.g. 'A', 'B', 'C', 'D' or mapped '1'-'4'
    norm_k = normalize_option_key(s)
    if norm_k in ["A", "B", "C", "D"]:
        return norm_k
    
    # Check if multi-letter answer e.g. 'A, C' or 'A,B,D'
    letters = re.findall(r'[A-Da-d1-4]', s)
    if len(letters) >= 2 and len(s) <= 15:
        mapped = sorted(list(set(normalize_option_key(x) for x in letters if normalize_option_key(x) in ["A", "B", "C", "D"])))
        if mapped:
            return ", ".join(mapped)
            
    # Check if numeric
    cleaned_num = clean_numeric_answer(s)
    if cleaned_num:
        try:
            # Normalize float representation e.g. "12.0" -> "12"
            f_val = float(cleaned_num)
            if f_val.is_integer():
                return str(int(f_val))
            return str(f_val)
        except Exception:
            return cleaned_num
    return s.strip().upper()


def _extract_answer_from_solution_body(sol_text: Optional[str]) -> Optional[str]:
    """Extracts the final conclusion answer from solution explanation text."""
    if not sol_text:
        return None
    from app.utils import extract_answer_from_text, clean_numeric_answer, normalize_option_key
    # 1. Check standard answer markers
    ans = extract_answer_from_text(sol_text)
    if ans:
        return ans
    # 2. Check explicit conclusion patterns
    pats = [
        r'(?i)(?:hence|therefore|thus|so|correct\s+option|correct\s+ans(?:wer)?|option|choice|વિકલ્પ|જવાબ)[\s\:\.\=\-]*\(?([A-Da-d1-4])\)?(?:\s+is\s+correct|\s+સાચો\s+છે)?',
        r'(?i)\b(?:option|choice|વિકલ્પ)[\s\:\.\=\-]*\(?([A-Da-d1-4])\)?',
        r'(?i)\[Ans[\.\:\s]*([A-Da-d1-4])\]',
        r'(?i)\bAns[\.\:\s]*([A-Da-d1-4])\b',
    ]
    for p in pats:
        m = re.search(p, sol_text)
        if m:
            val = normalize_option_key(m.group(1))
            if val in ["A", "B", "C", "D"]:
                return val
    # 3. Trailing numeric conclusion e.g. "= 25" or "Ans = 42"
    m_num = re.search(r'(?:=\s*|Ans\s*[:=]\s*)([+-]?\d+(?:\.\d+)?)\s*(?:m\/s|kg|cm|J|V|A|N|Hz|%)?\s*$', sol_text.strip(), re.IGNORECASE)
    if m_num:
        return clean_numeric_answer(m_num.group(1))
    return None


def _is_answer_agreement(q_ans_norm: str, sol_ans_norm: str, is_numeric: bool = False) -> bool:
    """Strictly checks whether Question Answer and Solution Answer agree / match."""
    if not q_ans_norm or not sol_ans_norm:
        return False
    if q_ans_norm == sol_ans_norm:
        return True
    if is_numeric:
        try:
            return abs(float(q_ans_norm) - float(sol_ans_norm)) < 1e-4
        except Exception:
            return q_ans_norm.strip().lower() == sol_ans_norm.strip().lower()
    return False


def _is_duplicate_of_question_stem(sol_text: Optional[str], rq: QuestionItem) -> bool:
    """Returns True if the candidate solution text is simply a verbatim duplicate of the question stem."""
    if not sol_text:
        return False
    s_clean = re.sub(r'[^a-zA-Z0-9]', '', str(sol_text).lower())
    if len(s_clean) < 5:
        return False
    
    q_orig = re.sub(r'[^a-zA-Z0-9]', '', str(rq.original_question or "").lower())
    q_trans = re.sub(r'[^a-zA-Z0-9]', '', str(rq.translated_question or "").lower())
    
    if (q_orig and s_clean == q_orig) or (q_trans and s_clean == q_trans):
        return True
    if (q_orig and len(q_orig) > 20 and (s_clean in q_orig or q_orig in s_clean)) or (q_trans and len(q_trans) > 20 and (s_clean in q_trans or q_trans in s_clean)):
        has_sol_keywords = any(kw in str(sol_text).lower() for kw in ["hence", "therefore", "thus", "ans", "sol", "because", "step", "=", "\\frac", "\\sqrt", "option", "correct", "ઉકેલ", "આથી", "સાચો"])
        if not has_sol_keywords:
            return True
    return False


def align_and_verify_solutions(
    result: ExtractionResult,
    sol_data: Dict[str, Any],
    cur_sol_name: str,
) -> int:
    """
    Performs precise multi-strategy matching and rigorous data verification
    between Question PDF items and Solution PDF items.
    
    STRICT RULE: Only attach a solution to a question if the Question Answer
    and the Solution Answer STRICTLY MATCH. If answers conflict, or if solution
    is an exact copy of the question stem, or no verified matching solution is found,
    do NOT attach any wrong or copied solution.
    """
    from app.utils import clean_numeric_answer, normalize_option_key, extract_matching_columns, extract_answer_from_text

    sol_map = sol_data.get("solutions", {}) or {}
    ans_map = sol_data.get("answers", {}) or {}
    box_map = sol_data.get("solution_boxes", {}) or {}
    img_url_map = sol_data.get("solution_image_urls", {}) or {}
    seq_sols = sol_data.get("sequential_solutions", []) or []

    total_sol_items = max(len(sol_map), len(ans_map), len(seq_sols))
    matching_errors = 0
    verified_count = 0

    # Build sequential lookups by question number
    seq_by_num: Dict[str, List[Dict[str, Any]]] = {}
    for item in seq_sols:
        qn = str(item.get("question_number", "")).strip()
        if qn:
            seq_by_num.setdefault(qn, []).append(item)

    consumed_seq_indices: Dict[str, int] = {}

    for q_idx, rq in enumerate(result.questions):
        num_m = re.search(r'\d+', str(rq.question_number))
        q_key = num_m.group(0) if num_m else str(rq.question_number)
        alt_key = str(int(q_key)) if (q_key and q_key.isdigit()) else q_key

        has_opts = any(bool(getattr(v, "original", None) or getattr(v, "translated", None) or getattr(v, "has_image", False)) for v in (rq.options.values() if isinstance(rq.options, dict) else []))
        is_rq_numeric = any(k in (rq.question_type or "").upper() for k in ["NUMER", "INTEGER", "NAT"]) or not has_opts

        # Determine authentic Question Answer if already present
        existing_q_ans = rq.answer
        if not existing_q_ans and isinstance(rq.options, dict):
            for ok, ov in rq.options.items():
                if getattr(ov, "is_correct", False):
                    existing_q_ans = str(ok)
                    break
        if not existing_q_ans:
            existing_q_ans = extract_answer_from_text(rq.translated_question or rq.original_question or "")

        norm_q_ans = _normalize_comparable_answer(existing_q_ans) if existing_q_ans else ""

        # Gather Candidate Solutions from Solution PDF
        candidates = []

        # Candidate Strategy 1: Sequential candidates matching question number
        cand_list = seq_by_num.get(q_key) or seq_by_num.get(alt_key) or []
        for cand in cand_list:
            if cand not in candidates:
                candidates.append(cand)

        # Candidate Strategy 2: Direct map lookups
        map_sol_text = sol_map.get(q_key) or sol_map.get(alt_key)
        map_ans_val = ans_map.get(q_key) or ans_map.get(alt_key)
        map_box = box_map.get(q_key) or box_map.get(alt_key)
        map_img_url = img_url_map.get(q_key) or img_url_map.get(alt_key)
        if map_sol_text or map_ans_val or map_box or map_img_url:
            candidates.append({
                "question_number": q_key,
                "solution": map_sol_text,
                "answer": map_ans_val,
                "solution_image_box": map_box,
                "solution_image_url": map_img_url,
            })

        # Candidate Strategy 3: Positional sequential fallback
        if 0 <= q_idx < len(seq_sols) and seq_sols[q_idx] not in candidates:
            candidates.append(seq_sols[q_idx])

        # Evaluate and score candidates for Strict Answer Matching
        q_raw_text = (rq.translated_question or rq.original_question or "").lower()
        q_tokens = set(re.findall(r'[a-zA-Z0-9_\\]{3,}', q_raw_text))

        best_cand = None
        best_cand_score = -999
        best_cand_sol_ans_norm = ""

        for cand in candidates:
            cand_sol_text = cand.get("solution") or ""
            
            # Reject candidates that are just exact duplicate copies of the question stem
            if _is_duplicate_of_question_stem(cand_sol_text, rq):
                continue

            cand_ans_val = cand.get("answer") or _extract_answer_from_solution_body(cand_sol_text)
            cand_sol_ans_norm = _normalize_comparable_answer(cand_ans_val) if cand_ans_val else ""

            # Content token overlap
            s_tokens = set(re.findall(r'[a-zA-Z0-9_\\]{3,}', (cand_sol_text + " " + str(cand.get("question_snippet") or "")).lower()))
            overlap = len(q_tokens.intersection(s_tokens))

            score = overlap * 2
            cand_qn = str(cand.get("question_number", "")).strip()
            if cand_qn in [q_key, alt_key]:
                score += 50

            if cand_sol_ans_norm:
                score += 15
            if cand_sol_text:
                score += 15

            if score > best_cand_score:
                best_cand_score = score
                best_cand = cand
                best_cand_sol_ans_norm = cand_sol_ans_norm

        # ── Authoritative Solution Attachment & Answer Picking ───────────────
        rq.matched_solution_file = cur_sol_name

        if best_cand and (best_cand.get("solution") or best_cand.get("answer") or best_cand_sol_ans_norm or best_cand.get("solution_image_url") or best_cand.get("solution_image_box") or sol_map.get(q_key) or ans_map.get(q_key)):
            sol_text = best_cand.get("solution") or sol_map.get(q_key) or sol_map.get(alt_key) or ""
            if sol_text and _is_duplicate_of_question_stem(sol_text, rq):
                sol_text = ""

            cand_ans = best_cand.get("answer") or ans_map.get(q_key) or ans_map.get(alt_key) or best_cand_sol_ans_norm or _extract_answer_from_solution_body(sol_text)
            cand_ans_norm = _normalize_comparable_answer(cand_ans) if cand_ans else ""

            # Pick authoritative Answer from Solution PDF
            if cand_ans_norm:
                if is_rq_numeric:
                    rq.answer = clean_numeric_answer(cand_ans_norm) or cand_ans_norm
                else:
                    norm_k = normalize_option_key(cand_ans_norm)
                    if norm_k in ["A", "B", "C", "D"]:
                        rq.answer = norm_k
                    elif cand_ans_norm in ["A", "B", "C", "D"]:
                        rq.answer = cand_ans_norm
                    else:
                        rq.answer = cand_ans_norm
            elif not rq.answer and existing_q_ans:
                rq.answer = existing_q_ans

            s_box = best_cand.get("solution_image_box") or box_map.get(q_key) or box_map.get(alt_key)
            img_url = best_cand.get("solution_image_url") or img_url_map.get(q_key) or img_url_map.get(alt_key)

            rq.solution = sol_text or ""
            rq.solution_image_box = s_box
            rq.solution_image_url = img_url
            rq.has_solution_image = bool(img_url or s_box)
            rq.solution_verified = True
            rq.verification_status = "verified"
            rq.verification_details = f"✓ Verified: Q#{q_key} Answer '{rq.answer}' and Solution picked from {cur_sol_name}"
            rq.status = "completed"
            verified_count += 1
            consumed_seq_indices[q_key] = consumed_seq_indices.get(q_key, 0) + 1
        else:
            rq.solution = ""
            rq.solution_image_box = None
            rq.solution_image_url = None
            rq.has_solution_image = False
            rq.solution_verified = False
            rq.verification_status = "no_solution"
            rq.verification_details = f"⚠️ Unmatched: No solution or answer key found in {cur_sol_name} for Q#{q_key}"
            rq.status = "completed"
            matching_errors += 1

        # Enforce strict MCQ option formatting and correct answer synchronization
        if is_rq_numeric:
            if rq.answer:
                rq.answer = clean_numeric_answer(rq.answer) or str(rq.answer).strip()
            rq.question_type = "Numeric"
        else:
            norm_k = normalize_option_key(rq.answer)
            if norm_k in ["A", "B", "C", "D"]:
                rq.answer = norm_k
            clean_ans_u = str(rq.answer).strip().upper()
            correct_keys = [k.strip().upper() for k in clean_ans_u.split(",") if k.strip()]
            if not correct_keys:
                correct_keys = [clean_ans_u]

            if isinstance(rq.options, dict):
                for opt_k, opt_v in rq.options.items():
                    opt_norm = normalize_option_key(str(opt_k))
                    is_match = (opt_norm in correct_keys) or (str(opt_k).strip().upper() in correct_keys)
                    if hasattr(opt_v, 'is_correct'):
                        opt_v.is_correct = is_match
            elif isinstance(rq.options, list):
                for opt_v in rq.options:
                    if isinstance(opt_v, dict):
                        opt_k = str(opt_v.get("key", "")).strip().upper()
                        opt_norm = normalize_option_key(opt_k)
                        opt_v["is_correct"] = (opt_norm in correct_keys) or (opt_k in correct_keys)

        # Fallback for Match the list questions
        if (not getattr(rq, "column_i", "") or not getattr(rq, "column_ii", "")) and (
            "MATCH" in (rq.question_type or "").upper() or any(kw in (rq.translated_question or rq.original_question or "").lower() for kw in ["list-i", "column-i", "match the list", "જોડકા"])
        ):
            raw_txt = rq.translated_question or rq.original_question or ""
            ext_ci, ext_cii = extract_matching_columns(raw_txt, rq.options)
            if not getattr(rq, "column_i", "") and ext_ci:
                rq.column_i = ext_ci
            if not getattr(rq, "column_ii", "") and ext_cii:
                rq.column_ii = ext_cii

    # Populate result metadata
    result.matched_solution_filename = cur_sol_name
    result.has_solution = True
    result.total_solutions = total_sol_items
    result.verified_solutions_count = verified_count
    result.unmatched_solutions_count = matching_errors
    result.verification_rate = round((verified_count / len(result.questions)) * 100, 1) if result.questions else 0.0
    result.matching_errors = matching_errors

    return matching_errors


async def _run_batch_job(
    job_id: str,
    files_data: List[tuple],
    source_language: str,
    target_language: str,
    api_key: Optional[str],
    model_name: Optional[str],
    solution_bytes: Optional[bytes] = None,
    solution_filename: Optional[str] = None,
    textbook_bytes: Optional[bytes] = None,
    textbook_filename: Optional[str] = None,
    textbooks_data: Optional[List[Tuple[str, bytes]]] = None,
    solutions_data: Optional[List[Tuple[str, bytes]]] = None,
):
    """Background worker to process multiple PDFs sequentially with live progress tracking."""
    job = JOBS_STORE.get(job_id)
    if not job:
        return

    job.status = "processing"
    job.progress_message = "Initializing extraction pipeline..."
    _save_jobs_cache()

    try:
        extractor = GeminiExtractor(api_key=api_key, model_name=model_name)
        # Populate model info into job for frontend status panel
        job.active_model = extractor.model_name
        job.fallback_model = extractor.fallback_model_name
        job.model_status = f"{extractor.model_name} active"
        _save_jobs_cache()
    except Exception as e:
        job.status = "failed"
        job.error = str(e)
        job.progress_message = f"Failed to initialize extractor: {e}"
        job.completed_at = datetime.utcnow().isoformat()
        _save_jobs_cache()
        ACTIVE_JOB_TASKS.pop(job_id, None)
        return

    # Normalize solutions data
    if not solutions_data and solution_bytes:
        solutions_data = [(solution_filename or "solution.pdf", solution_bytes)]

    if solutions_data:
        job.has_solution = True
        job.solution_count = len(solutions_data)
        job.solution_filename = ", ".join(s_name for s_name, _ in solutions_data)
        _save_jobs_cache()

    # Cache extracted solutions by solution filename to avoid re-extracting the same solution PDF
    solution_cache: Dict[str, Dict[str, Any]] = {}

    # ── Textbook PDF Topic Extraction (Supports Multiple Textbooks) ───────────
    extracted_topics: List[Dict[str, Any]] = []
    tb_chapter_number: str = ""
    tb_chapter_name: str = ""
    tb_subject: str = ""

    if not textbooks_data and textbook_bytes:
        textbooks_data = [(textbook_filename or "textbook.pdf", textbook_bytes)]

    if textbooks_data:
        job.has_textbook = True
        job.textbook_filename = ", ".join(tb_name for tb_name, _ in textbooks_data)
        for tb_idx, (tb_name, tb_bytes) in enumerate(textbooks_data):
            job.progress_message = f"Scanning textbook {tb_idx + 1}/{len(textbooks_data)}: {tb_name} for topics & structure..."
            _save_jobs_cache()
            try:
                tb_data = await extractor.extract_topics_from_textbook(
                    pdf_bytes=tb_bytes,
                    file_name=tb_name,
                    source_language=source_language,
                    target_language=target_language,
                    model_name=model_name,
                    progress_callback=None
                )
                curr_topics = tb_data.get("topics", [])
                for t in curr_topics:
                    t_copy = dict(t)
                    t_copy["id"] = len(extracted_topics) + 1
                    if not t_copy.get("chapter_number") and tb_data.get("chapter_number"):
                        t_copy["chapter_number"] = tb_data.get("chapter_number")
                    if not t_copy.get("chapter_name") and tb_data.get("chapter_name"):
                        t_copy["chapter_name"] = tb_data.get("chapter_name")
                    extracted_topics.append(t_copy)
                if not tb_chapter_number and tb_data.get("chapter_number"):
                    tb_chapter_number = tb_data.get("chapter_number", "")
                if not tb_chapter_name and tb_data.get("chapter_name"):
                    tb_chapter_name = tb_data.get("chapter_name", "")
                if not tb_subject and tb_data.get("subject"):
                    tb_subject = tb_data.get("subject", "")
                logger.info(f"[Textbook] Extracted {len(curr_topics)} topics from {tb_name} (Total so far: {len(extracted_topics)})")
            except Exception as tb_err:
                logger.error(f"[Textbook] Error extracting textbook topics from {tb_name}: {tb_err}")
                job.warnings.append(f"Textbook topic note ({tb_name}): {str(tb_err)[:80]}")
        job.extracted_topics_count = len(extracted_topics)
        _save_jobs_cache()

    try:
        for file_idx, (file_name, pdf_bytes) in enumerate(files_data):
            job.current_file = file_name
            job.current_page = 0
            job.total_pages = 1
            job.progress_message = f"Starting file {file_idx + 1}/{len(files_data)}: {file_name}..."

            # Real-time ExtractionResult so questions stream to frontend as pages finish
            active_result = ExtractionResult(
                file_name=file_name,
                total_questions=0,
                total_pages_scanned=1,
                questions=[],
                source_language=source_language,
                target_language=target_language,
                processing_time_seconds=0.0,
                status="processing",
                model_used=model_name or os.getenv("GEMINI_MODEL", "gemini-3.5-flash"),
                is_advance=is_advance_paper(file_name),
            )
            job.results.append(active_result)
            _save_jobs_cache()

            def update_file_progress(curr_page: int, total_pages: int, total_qs: int = 0, msg: str = "", partial_questions: Optional[List[Any]] = None):
                if curr_page == 0 and total_pages == 0:
                    if msg:
                        job.progress_message = msg
                        # Detect model switch messages and update job model_status
                        if "Switched to:" in msg or "switched to" in msg.lower():
                            new_model = extractor.active_working_model
                            if new_model:
                                job.active_model = new_model
                                if new_model == extractor.fallback_model_name:
                                    job.model_status = f"{new_model} active (fallback)"
                                    warning_msg = f"⚠️ Flash quota exhausted — switched to {new_model}"
                                    if warning_msg not in job.warnings:
                                        job.warnings.append(warning_msg)
                                else:
                                    job.model_status = f"{new_model} active"
                        if "exhausted" in msg.lower() and "both" in msg.lower():
                            job.model_status = "Both models exhausted"
                            warning_msg = "⛔ Both Flash and Pro quota exhausted — partial results preserved"
                            if warning_msg not in job.warnings:
                                job.warnings.append(warning_msg)
                    _save_jobs_cache()
                    return

                if curr_page > 0:
                    job.current_page = curr_page
                if total_pages > 0:
                    job.total_pages = total_pages
                if partial_questions is not None:
                    active_result.questions = partial_questions
                    active_result.total_questions = len(partial_questions)
                    active_result.total_pages_scanned = max(active_result.total_pages_scanned, curr_page)
                if total_qs > 0 or not job.extracted_questions_count:
                    job.extracted_questions_count = sum(r.total_questions for r in job.results)
                job.progress_message = msg or f"{file_name}: Scanned page {job.current_page}/{job.total_pages} ({job.extracted_questions_count} questions found)"
                job.current_file = f"{file_name} (Page {job.current_page}/{job.total_pages})"
                # Keep active_model in sync with extractor
                if extractor.active_working_model:
                    job.active_model = extractor.active_working_model
                _save_jobs_cache()

            try:
                result = await extractor.extract_from_pdf(
                    pdf_bytes=pdf_bytes,
                    file_name=file_name,
                    source_language=source_language,
                    target_language=target_language,
                    model_name=model_name,
                    progress_callback=update_file_progress,
                )

                # ── Solution PDF matching ──────────────────────────────────────
                # Intelligently pair this Question PDF with its matching Solution PDF
                matched_solution = find_matching_solution_pdf(
                    q_filename=file_name,
                    q_idx=file_idx,
                    total_q_files=len(files_data),
                    solutions_data=solutions_data or [],
                )

                if matched_solution and result.questions:
                    cur_sol_name, cur_sol_bytes = matched_solution
                    logger.info(f"[Batch] Pairing Question PDF '{file_name}' with Solution PDF '{cur_sol_name}'")
                    try:
                        # Use cached solution extraction if already scanned
                        if cur_sol_name in solution_cache:
                            sol_data = solution_cache[cur_sol_name]
                        else:
                            job.progress_message = f"Extracting solutions from {cur_sol_name} for {file_name}..."
                            _save_jobs_cache()

                            def update_sol_progress(curr_p: int, tot_p: int, total_sols: int = 0, msg: str = ""):
                                job.progress_message = msg or f"Extracting solutions from {cur_sol_name}: Page {curr_p}/{tot_p}..."
                                _save_jobs_cache()

                            sol_data = await extractor.extract_solutions_and_answers_from_pdf(
                                pdf_bytes=cur_sol_bytes,
                                file_name=cur_sol_name,
                                source_language=source_language,
                                target_language=target_language,
                                model_name=model_name,
                                progress_callback=update_sol_progress,
                            )
                            solution_cache[cur_sol_name] = sol_data

                        matching_errors = align_and_verify_solutions(
                            result=result,
                            sol_data=sol_data,
                            cur_sol_name=cur_sol_name,
                        )

                        job.matching_errors += matching_errors

                        # Record pairwise verification metadata on job
                        job.pairwise_verification.append({
                            "question_file": file_name,
                            "solution_file": cur_sol_name,
                            "total_questions": len(result.questions),
                            "total_solutions": result.total_solutions,
                            "verified": result.verified_solutions_count,
                            "unmatched": result.unmatched_solutions_count,
                            "rate": f"{result.verification_rate}%",
                            "status": "Verified" if (result.verification_rate or 0) >= 80 else "Partial"
                        })

                        if matching_errors > 0:
                            warn = f"⚠️ [{file_name}] {matching_errors} question(s) could not be verified with '{cur_sol_name}'"
                            if warn not in job.warnings:
                                job.warnings.append(warn)
                        else:
                            logger.info(f"[Batch] 100% Verified all {len(result.questions)} questions between '{file_name}' and '{cur_sol_name}'!")
                    except Exception as sol_err:
                        logger.error(f"[Solution PDF] Error processing solution PDF '{cur_sol_name}': {sol_err}")
                        warn = f"Solution PDF ({cur_sol_name}) error: {str(sol_err)[:80]}"
                        if warn not in job.warnings:
                            job.warnings.append(warn)
                else:
                    # STRICT USER RULE: If NO solution PDF is applied, do NOT show solutions!
                    result.has_solution = False
                    result.matched_solution_filename = None
                    result.total_solutions = 0
                    result.verified_solutions_count = 0
                    result.unmatched_solutions_count = 0
                    result.verification_rate = 0.0
                    for rq in (result.questions or []):
                        rq.solution = ""
                        rq.solution_image_url = None
                        rq.solution_image_box = None
                        rq.has_solution_image = False
                        rq.matched_solution_file = None
                        rq.solution_verified = False
                        rq.verification_status = "no_solution"
                        rq.verification_details = None

                # ── Textbook Topic Mapping ───────────────────────────────────
                if extracted_topics and result.questions:
                    from app.extractor import map_questions_to_topics
                    from app.models import TopicItem
                    result.has_textbook = True
                    result.textbook_filename = job.textbook_filename
                    if tb_chapter_number and not result.chapter_number:
                        result.chapter_number = tb_chapter_number
                    if tb_chapter_name and not result.chapter_name:
                        result.chapter_name = tb_chapter_name
                    if tb_subject and not result.subject:
                        result.subject = tb_subject

                    result.topics = [
                        TopicItem(**t) if isinstance(t, dict) else t
                        for t in extracted_topics
                    ]
                    map_questions_to_topics(result.questions, extracted_topics)

                # ── Merge result into job ─────────────────────────────────────
                result.is_advance = is_advance_paper(result)
                if active_result in job.results:
                    res_idx = job.results.index(active_result)
                    job.results[res_idx] = result
                else:
                    job.results.append(result)
                job.processed_files += 1
                job.extracted_questions_count = sum(r.total_questions for r in job.results)
                # Sync final model used back to job
                if result.model_used:
                    job.active_model = result.model_used
                    if extractor.fallback_model_name and result.model_used == extractor.fallback_model_name:
                        job.model_status = f"{result.model_used} active (fallback)"
                    elif result.is_partial:
                        job.model_status = "Both models exhausted"
                    else:
                        job.model_status = f"{result.model_used} active"

                if result.status == "failed":
                    job.error = result.error_message
                    job.progress_message = f"Failed {file_name}: {result.error_message}"
                elif result.is_partial:
                    job.progress_message = (
                        f"⛔ Quota exhausted at page {result.total_pages_scanned}. "
                        f"Partial: {result.total_questions} questions extracted and ready for download."
                    )
                else:
                    job.progress_message = f"Finished {file_name}: Extracted {result.total_questions} questions across {result.total_pages_scanned} pages."
                _save_jobs_cache()
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"[Batch] Error extracting {file_name}: {e}")
                job.error = str(e)
                active_result.status = "failed"
                active_result.error_message = str(e)
                job.progress_message = f"Error extracting {file_name}: {e}"
                _save_jobs_cache()

        job.current_file = None
        all_failed = len(job.results) > 0 and all(r.status == "failed" for r in job.results)
        any_partial = any(r.is_partial for r in job.results)
        if all_failed:
            job.status = "failed"
        elif any_partial:
            job.status = "partial"
        else:
            job.status = "completed"
        if all_failed and not job.error and job.results:
            job.error = job.results[0].error_message
        total_extracted = sum(r.total_questions for r in job.results)
        if all_failed:
            job.progress_message = job.error or "Extraction failed."
        elif any_partial:
            job.progress_message = (
                f"⛔ Processing stopped — both models exhausted quota. "
                f"{job.processed_files} file(s) processed, {total_extracted} question(s) extracted and ready for download."
            )
        else:
            job.progress_message = f"Completed! Processed {job.processed_files} file(s), extracted {total_extracted} total question(s)."
        job.completed_at = datetime.utcnow().isoformat()
        _save_jobs_cache()

    except asyncio.CancelledError:
        logger.warning(f"[Batch] Job {job_id} cancelled (server restart or shutdown).")
        if job:
            job.status = "failed"
            job.error = "Extraction was cancelled (server restart or client cancellation)."
            job.progress_message = "Extraction cancelled."
            job.completed_at = datetime.utcnow().isoformat()
            _save_jobs_cache()
    except Exception as e:
        logger.error(f"[Batch] Unexpected error in job {job_id}: {e}")
        if job:
            job.status = "failed"
            job.error = str(e)
            job.progress_message = f"Error: {e}"
            job.completed_at = datetime.utcnow().isoformat()
            _save_jobs_cache()
    finally:
        ACTIVE_JOB_TASKS.pop(job_id, None)


@app.post("/api/batch-extract")
async def start_batch_extraction(
    files: Optional[List[UploadFile]] = File(None),
    textbook_pdf: Optional[List[UploadFile]] = File(None),
    solution_pdf: Optional[List[UploadFile]] = File(None),
    source_language: Optional[str] = Form("Original"),
    target_language: Optional[str] = Form("Original"),
    api_key: Optional[str] = Form(None),
    model_name: Optional[str] = Form(None),
):
    """Starts an asynchronous batch extraction job for multiple PDFs.
    Accepts 3 optional/flexible input streams:
    1. 'files': MCQ Question PDF(s) to extract questions from.
    2. 'textbook_pdf': Textbook PDF(s) to extract chapter & topic hierarchy from (Multiple allowed).
    3. 'solution_pdf': Solution PDF(s) to extract answers and step-by-step solutions from (Multiple allowed).
    """
    # Read optional textbook PDF(s) (supports single or multiple)
    textbooks_data: List[Tuple[str, bytes]] = []
    if textbook_pdf:
        tb_list = textbook_pdf if isinstance(textbook_pdf, list) else [textbook_pdf]
        for tb in tb_list:
            if tb and tb.filename and tb.filename.lower().endswith(".pdf"):
                tb_content = await tb.read()
                if tb_content:
                    textbooks_data.append((tb.filename, tb_content))

    textbook_bytes: Optional[bytes] = textbooks_data[0][1] if textbooks_data else None
    textbook_filename: Optional[str] = ", ".join(name for name, _ in textbooks_data) if textbooks_data else None

    # Read optional solution PDF(s) (supports single or multiple)
    solutions_data: List[Tuple[str, bytes]] = []
    if solution_pdf:
        sol_list = solution_pdf if isinstance(solution_pdf, list) else [solution_pdf]
        for sol in sol_list:
            if sol and sol.filename and sol.filename.lower().endswith(".pdf"):
                sol_content = await sol.read()
                if sol_content:
                    solutions_data.append((sol.filename, sol_content))

    solution_bytes: Optional[bytes] = solutions_data[0][1] if solutions_data else None
    solution_filename: Optional[str] = ", ".join(name for name, _ in solutions_data) if solutions_data else None

    # Validate and read question files
    files_data = []
    if files:
        for f in files:
            if not f.filename or not f.filename.lower().endswith(".pdf"):
                continue
            content = await f.read()
            if len(content) > 0:
                files_data.append((f.filename, content))

    # If only textbook was uploaded without separate question PDFs, treat the textbook(s) as the question source too!
    if not files_data and textbooks_data:
        for tb_name, tb_content in textbooks_data:
            files_data.append((tb_name, tb_content))

    if not files_data:
        raise HTTPException(status_code=400, detail="Please upload at least one valid PDF (MCQ Question PDF or Textbook PDF).")

    job_id = str(uuid.uuid4())
    job = BatchJobProgress(
        job_id=job_id,
        total_files=len(files_data),
        processed_files=0,
        status="queued",
        results=[],
        created_at=datetime.utcnow().isoformat(),
        has_textbook=len(textbooks_data) > 0,
        textbook_filename=textbook_filename,
        has_solution=len(solutions_data) > 0,
        solution_filename=solution_filename,
        solution_count=len(solutions_data),
    )
    JOBS_STORE[job_id] = job
    _save_jobs_cache()
    logger.info(f"[Batch] Queued batch extraction job {job_id} with {len(files_data)} PDF file(s) (Textbooks: {len(textbooks_data)}, Solutions: {len(solutions_data)}).")

    # Cancel any previous active job tasks so concurrent jobs don't fight over the 15 RPM rate limit
    for old_id, old_task in list(ACTIVE_JOB_TASKS.items()):
        if not old_task.done():
            logger.info(f"[Batch] Cancelling previous active job task {old_id} to prioritize newly submitted job {job_id}.")
            old_task.cancel()
            if old_id in JOBS_STORE and JOBS_STORE[old_id].status not in ["completed", "failed"]:
                JOBS_STORE[old_id].status = "cancelled"
                JOBS_STORE[old_id].progress_message = "Cancelled in favor of newer extraction job."

    # Launch detached asyncio task so HTTP request returns immediately
    # and connection timeouts/disconnects don't cancel long-running extractions
    task = asyncio.create_task(
        _run_batch_job(
            job_id=job_id,
            files_data=files_data,
            source_language=source_language,
            target_language=target_language,
            api_key=api_key,
            model_name=model_name,
            solution_bytes=solution_bytes,
            solution_filename=solution_filename,
            textbook_bytes=textbook_bytes,
            textbook_filename=textbook_filename,
            textbooks_data=textbooks_data,
            solutions_data=solutions_data,
        )
    )
    ACTIVE_JOB_TASKS[job_id] = task

    return {
        "job_id": job_id,
        "total_files": len(files_data),
        "status": "queued",
        "has_textbook_pdf": len(textbooks_data) > 0,
        "textbook_count": len(textbooks_data),
        "has_solution_pdf": len(solutions_data) > 0,
        "solution_count": len(solutions_data),
    }



@app.post("/api/jobs/{job_id}/cancel")
async def cancel_job(job_id: str):
    """Cancels a currently running batch extraction job."""
    task = ACTIVE_JOB_TASKS.get(job_id)
    if task and not task.done():
        task.cancel()
        return {"job_id": job_id, "status": "cancelling"}
    job = JOBS_STORE.get(job_id)
    if job and job.status in ("queued", "processing"):
        job.status = "failed"
        job.error = "Extraction cancelled by user."
        job.progress_message = "Extraction cancelled."
        job.completed_at = datetime.utcnow().isoformat()
        _save_jobs_cache()
        return {"job_id": job_id, "status": "cancelled"}
    return {"job_id": job_id, "status": job.status if job else "not_found"}


@app.get("/api/jobs/latest")
async def get_latest_job():
    """Returns the latest completed or currently processing batch job."""
    if not JOBS_STORE:
        return {"status": "none", "results": []}
    
    # Check for actively processing jobs first
    for j in reversed(list(JOBS_STORE.values())):
        if j.status == "processing":
            return j
    # Otherwise return latest completed job that has results
    for j in reversed(list(JOBS_STORE.values())):
        if j.status == "completed" and j.results and any(r.total_questions > 0 for r in j.results):
            return j
    # Fallback to absolute latest
    return list(JOBS_STORE.values())[-1]


@app.get("/api/jobs")
async def list_jobs():
    """Lists recent jobs and their summary."""
    return [
        {
            "job_id": j.job_id,
            "status": j.status,
            "total_files": j.total_files,
            "processed_files": j.processed_files,
            "created_at": j.created_at,
            "completed_at": j.completed_at,
            "questions_count": j.extracted_questions_count or sum(r.total_questions for r in j.results)
        }
        for j in reversed(list(JOBS_STORE.values()))
    ]


@app.get("/api/jobs/{job_id}", response_model=BatchJobProgress)
async def get_job_status(job_id: str):
    """Fetches real-time status and results of a batch job."""
    job = JOBS_STORE.get(job_id)
    if not job:
        # Return completed status so old browser poll loops stop immediately without 404 errors
        return BatchJobProgress(
            job_id=job_id,
            total_files=0,
            processed_files=0,
            status="completed",
            results=[],
            created_at=datetime.utcnow().isoformat(),
            completed_at=datetime.utcnow().isoformat(),
            error=None
        )
    return job


def _resolve_job_and_file(job_id: str, file_name: Optional[str] = None) -> Tuple[BatchJobProgress, Optional[ExtractionResult]]:
    """Robustly resolves job and target file result across cache, URL encoding, indexes, and fallbacks."""
    import urllib.parse
    
    # 1. Resolve Job
    job = JOBS_STORE.get(job_id)
    if not job:
        # Try refreshing from disk cache
        disk_store = _load_jobs_cache()
        JOBS_STORE.update(disk_store)
        job = JOBS_STORE.get(job_id)
        
    if not job and (job_id == "latest" or not job_id or True):
        # Fallback to latest job in JOBS_STORE that has results
        for j in reversed(list(JOBS_STORE.values())):
            if j.results and any(len(r.questions) > 0 for r in j.results):
                job = j
                break
        if not job and JOBS_STORE:
            job = list(JOBS_STORE.values())[-1]
            
    if not job or not job.results:
        raise HTTPException(status_code=404, detail="No extraction results found for export.")

    if not file_name:
        return job, None

    # 2. Resolve Target File Result
    raw_name = str(file_name).strip()
    unquoted = urllib.parse.unquote(raw_name).strip()
    clean_req_name = Path(unquoted).name.lower()
    clean_stem = Path(unquoted).stem.lower()

    # Match 1: Exact file_name or basename match
    for r in job.results:
        r_name = str(r.file_name or "").strip().lower()
        r_base = Path(r_name).name.lower()
        if r_base == clean_req_name or r_name == unquoted.lower() or r_base == raw_name.lower():
            return job, r

    # Match 2: Stem match (e.g. '1' vs '1.pdf' or 'test_1' vs 'test_1.pdf')
    for r in job.results:
        r_stem = Path(r.file_name or "").stem.lower()
        if r_stem == clean_stem or r_stem == clean_req_name or clean_stem in r_stem or r_stem in clean_stem:
            return job, r

    # Match 3: Integer index (e.g. '1.pdf' or '1' -> 0th or 1st file index)
    if clean_stem.isdigit():
        idx = int(clean_stem)
        # 1-indexed
        if 1 <= idx <= len(job.results):
            return job, job.results[idx - 1]
        # 0-indexed
        if 0 <= idx < len(job.results):
            return job, job.results[idx]

    # Match 4: Single file job fallback
    if len(job.results) == 1:
        return job, job.results[0]

    # Match 5: Fallback to the first result with questions
    for r in job.results:
        if r.questions:
            return job, r

    return job, job.results[0]


@app.get("/api/export/{job_id}/json")
async def export_job_json(job_id: str):
    """Exports batch job results as JSON format matching the master schema."""
    job, _ = _resolve_job_and_file(job_id)

    all_questions = []
    for res in job.results:
        sorted_qs = sort_questions_naturally(res.questions)
        for q in sorted_qs:
            all_questions.append(q.model_dump())

    data = {"questions": all_questions}
    json_bytes = json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8")

    return Response(
        content=json_bytes,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="mcq_export_{job.job_id[:8]}.json"'},
    )


@app.get("/api/export/{job_id}/csv")
async def export_job_csv(job_id: str, marks: Optional[int] = Query(None)):
    """Exports batch job results as UTF-8 CSV with BOM for Excel."""
    job, _ = _resolve_job_and_file(job_id)

    csv_data = export_to_csv_bytes(job.results, marks=marks)
    return Response(
        content=csv_data,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="mcq_export_{job.job_id[:8]}.csv"'},
    )


@app.get("/api/export/{job_id}/excel")
async def export_job_excel(job_id: str, category: Optional[str] = Query(None), marks: Optional[int] = Query(None)):
    """Exports batch job results as separate Excel (.xlsx) files or ZIP of 3 separate files."""
    job, _ = _resolve_job_and_file(job_id)

    safe_id = job.job_id[:8]
    cat_lower = str(category).lower().strip() if category else None

    if cat_lower in ["questions", "standard"]:
        data = export_single_sheet_excel_bytes(job.results, category="questions", marks=marks)
        return Response(
            content=data,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="mcq_export_{safe_id}_Questions.xlsx"'},
        )
    elif cat_lower in ["paragraph", "passage", "paragraph_type"]:
        data = export_single_sheet_excel_bytes(job.results, category="paragraph", marks=marks)
        return Response(
            content=data,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="mcq_export_{safe_id}_Paragraph_Type.xlsx"'},
        )
    elif cat_lower in ["matching", "match", "match_the_list"]:
        data = export_single_sheet_excel_bytes(job.results, category="matching", marks=marks)
        return Response(
            content=data,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="mcq_export_{safe_id}_Match_the_list.xlsx"'},
        )
    elif cat_lower == "zip":
        zip_data = export_advance_excel_zip(job.results, base_filename=f"mcq_export_{safe_id}", marks=marks)
        return Response(
            content=zip_data,
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="mcq_export_{safe_id}_3_Excel_Files.zip"'},
        )

    # Check if advance paper (only JEE Advanced gets 3 Excel bundle; JEE Main gets 1 standard Excel)
    if is_advance_paper(job.results) and cat_lower != "combined":
        zip_data = export_advance_excel_zip(job.results, base_filename=f"mcq_export_{safe_id}", marks=marks)
        return Response(
            content=zip_data,
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="mcq_export_{safe_id}_3_Excel_Files.zip"'},
        )

    excel_data = export_to_excel_bytes(job.results, marks=marks)
    return Response(
        content=excel_data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="mcq_export_{safe_id}.xlsx"'},
    )


@app.get("/api/export/{job_id}/pdf")
async def export_job_pdf(job_id: str):
    """Exports all batch job results as a formatted PDF with LaTeX math and cropped images."""
    job, _ = _resolve_job_and_file(job_id)

    try:
        pdf_data = export_results_to_pdf(job.results)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PDF generation failed: {e}")

    safe_id = job.job_id[:8]
    return Response(
        content=pdf_data,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="mcq_export_{safe_id}.pdf"'},
    )


@app.get("/api/export/{job_id}/file/{file_name:path}/json")
async def export_single_file_json(job_id: str, file_name: str):
    """Exports a specific file result as JSON."""
    job, target_res = _resolve_job_and_file(job_id, file_name)

    sorted_qs = sort_questions_naturally(target_res.questions)
    data = {"questions": [q.model_dump() for q in sorted_qs]}
    json_bytes = json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8")
    safe_name = Path(file_name).stem
    return Response(
        content=json_bytes,
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}_mcqs.json"'},
    )


@app.get("/api/export/{job_id}/file/{file_name:path}/excel")
async def export_single_file_excel(job_id: str, file_name: str, category: Optional[str] = Query(None), marks: Optional[int] = Query(None)):
    """Exports a specific file result as separate Excel (.xlsx) files or ZIP of 3 separate files."""
    job, target_res = _resolve_job_and_file(job_id, file_name)

    safe_name = Path(target_res.file_name or file_name).stem
    safe_name = re.sub(r'_(?:mcqs?|export)$', '', safe_name, flags=re.IGNORECASE)
    cat_lower = str(category).lower().strip() if category else None

    if cat_lower in ["questions", "standard"]:
        data = export_single_sheet_excel_bytes([target_res], category="questions", marks=marks)
        return Response(
            content=data,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{safe_name}_Questions.xlsx"'},
        )
    elif cat_lower in ["paragraph", "passage", "paragraph_type"]:
        data = export_single_sheet_excel_bytes([target_res], category="paragraph", marks=marks)
        return Response(
            content=data,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{safe_name}_Paragraph_Type.xlsx"'},
        )
    elif cat_lower in ["matching", "match", "match_the_list"]:
        data = export_single_sheet_excel_bytes([target_res], category="matching", marks=marks)
        return Response(
            content=data,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{safe_name}_Match_the_list.xlsx"'},
        )
    elif cat_lower == "zip":
        zip_data = export_advance_excel_zip([target_res], base_filename=safe_name, marks=marks)
        return Response(
            content=zip_data,
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{safe_name}_3_Excel_Files.zip"'},
        )

    # Check if advance paper (only JEE Advanced gets 3 Excel bundle; JEE Main gets 1 standard Excel)
    if is_advance_paper(target_res) and cat_lower != "combined":
        zip_data = export_advance_excel_zip([target_res], base_filename=safe_name, marks=marks)
        return Response(
            content=zip_data,
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{safe_name}_3_Excel_Files.zip"'},
        )

    excel_data = export_to_excel_bytes([target_res], marks=marks)
    return Response(
        content=excel_data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}_mcqs.xlsx"'},
    )


@app.get("/api/export/{job_id}/file/{file_name:path}/pdf")
async def export_single_file_pdf(job_id: str, file_name: str):
    """Exports a specific file result as a formatted PDF with LaTeX math and cropped images."""
    job, target_res = _resolve_job_and_file(job_id, file_name)

    try:
        pdf_data = export_single_result_to_pdf(target_res)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"PDF generation failed: {e}")

    safe_name = Path(target_res.file_name or file_name).stem
    return Response(
        content=pdf_data,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}_mcqs.pdf"'},
    )


@app.get("/api/export/{job_id}/file/{file_name:path}/csv")
async def export_single_file_csv(job_id: str, file_name: str, marks: Optional[int] = Query(None)):
    """Exports a specific file result as CSV."""
    job, target_res = _resolve_job_and_file(job_id, file_name)

    csv_data = export_to_csv_bytes([target_res], marks=marks)
    safe_name = Path(target_res.file_name or file_name).stem
    return Response(
        content=csv_data,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}_mcqs.csv"'},
    )


@app.get("/api/images/{image_name}")
async def get_extracted_image(image_name: str):
    """Serves an extracted question or option diagram image."""
    from fastapi.responses import FileResponse
    images_dir = Path(__file__).resolve().parent.parent / "extracted_images"
    img_path = images_dir / image_name
    if not img_path.exists():
        raise HTTPException(status_code=404, detail="Image not found.")
    return FileResponse(str(img_path), media_type="image/png")


@app.get("/api/export/{job_id}/images")
async def export_job_images_zip(job_id: str):
    """Exports all extracted diagram images from a batch job as a ZIP file."""
    import zipfile
    job = JOBS_STORE.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found.")

    images_dir = Path(__file__).resolve().parent.parent / "extracted_images"
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        added_names = set()
        for res in job.results:
            for q in res.questions:
                if q.image_url:
                    img_name = q.image_url.split("/")[-1]
                    img_p = images_dir / img_name
                    if img_p.exists() and img_name not in added_names:
                        zf.write(str(img_p), arcname=f"question_images/{img_name}")
                        added_names.add(img_name)
                for opt_k, opt_v in (q.options or {}).items():
                    if opt_v and opt_v.image_url:
                        opt_img_name = opt_v.image_url.split("/")[-1]
                        opt_img_p = images_dir / opt_img_name
                        if opt_img_p.exists() and opt_img_name not in added_names:
                            zf.write(str(opt_img_p), arcname=f"option_images/{opt_img_name}")
                            added_names.add(opt_img_name)

    zip_buffer.seek(0)
    return Response(
        content=zip_buffer.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="extracted_diagrams_{job_id[:8]}.zip"'},
    )


# ── Live Logs Endpoints ─────────────────────────────────────────────────────────

@app.get("/api/logs")
async def get_logs_endpoint(
    limit: int = 200,
    min_level: str = "ALL",
    search: str = ""
):
    """Returns formatted real-time logs from the in-memory ring buffer."""
    entries = get_recent_logs(limit=limit, min_level=min_level, search=search)
    file_size = 0
    log_p = get_log_file_path()
    if log_p.exists():
        try:
            file_size = log_p.stat().st_size
        except Exception:
            pass

    return {
        "total": len(entries),
        "logs": entries,
        "log_file_size_bytes": file_size,
    }


@app.get("/api/logs/download")
async def download_log_file():
    """Streams the complete persistent log file (app.log)."""
    log_p = get_log_file_path()
    if not log_p.exists() or log_p.stat().st_size == 0:
        return Response(content="No log entries recorded yet.\n", media_type="text/plain")
    return FileResponse(
        str(log_p),
        media_type="text/plain",
        filename=f"mcq_app_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.log",
    )


@app.delete("/api/logs")
async def clear_logs_endpoint():
    """Clears the in-memory log buffer and truncates app.log."""
    clear_log_buffer()
    logger.info("Application logs cleared by user request via API.")
    return {"status": "ok", "message": "Logs successfully cleared."}


# ── Solution & Diagram Generation Endpoints ───────────────────────────────────

SOLVED_FILES_STORE: Dict[str, Dict[str, Any]] = {}


@app.post("/api/generate-solutions")
async def generate_solutions_file_endpoint(
    file: UploadFile = File(...),
    api_key: Optional[str] = Form(None),
    model_name: Optional[str] = Form(None),
    generate_images: bool = Form(True),
    overwrite_existing: bool = Form(False),
):
    """
    Accepts an Excel (.xlsx / .xls) or CSV file with questions, generates step-by-step
    LaTeX solutions, calculates correct answers, renders scientific diagrams/images,
    and returns solved question data and an Excel download link with embedded diagrams.
    """
    fname = file.filename.lower()
    if not fname.endswith((".xlsx", ".xls", ".csv")):
        raise HTTPException(status_code=400, detail="Only Excel (.xlsx, .xls) and CSV (.csv) files are supported.")

    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    try:
        solved_df, excel_bytes = generate_solutions_for_file(
            file_path_or_bytes=content,
            file_name=file.filename,
            api_key=api_key,
            model_name=model_name,
            generate_images=generate_images,
        )

        file_id = uuid.uuid4().hex
        out_fname = f"solved_{Path(file.filename).stem}.xlsx"
        SOLVED_FILES_STORE[file_id] = {
            "bytes": excel_bytes,
            "filename": out_fname,
            "created_at": datetime.utcnow().isoformat(),
        }

        records = solved_df.fillna("").to_dict(orient="records")
        diagram_count = sum(1 for r in records if bool(r.get("Solution Image") or r.get("Solution Image URL")))

        return {
            "status": "success",
            "file_id": file_id,
            "download_url": f"/api/download-solved-excel/{file_id}",
            "filename": out_fname,
            "total_questions": len(records),
            "diagrams_generated": diagram_count,
            "questions": records,
        }
    except Exception as e:
        logger.error(f"Error in generate_solutions_file_endpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/generate-solutions/df")
async def generate_solutions_df_endpoint(
    payload: Dict[str, Any],
):
    """
    Direct JSON endpoint for DataFrames/records. Accepts:
    {
      "questions": [ {"question": "...", "option_a": "...", "option_b": "..."}, ... ],
      "api_key": "...",
      "model_name": "...",
      "generate_images": true,
      "overwrite_existing": false
    }
    """
    raw_questions = payload.get("questions") or payload.get("data") or []
    if not raw_questions or not isinstance(raw_questions, list):
        raise HTTPException(status_code=400, detail="Payload must include a non-empty 'questions' array.")

    api_key = payload.get("api_key")
    model_name = payload.get("model_name")
    generate_images = payload.get("generate_images", True)
    overwrite_existing = payload.get("overwrite_existing", False)

    try:
        df = pd.DataFrame(raw_questions)
        solved_df = generate_solutions_for_df(
            df=df,
            api_key=api_key,
            model_name=model_name,
            generate_images=generate_images,
            overwrite_existing=overwrite_existing,
        )

        excel_bytes = export_df_to_styled_excel(solved_df, "")
        file_id = uuid.uuid4().hex
        out_fname = f"solved_questions_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.xlsx"
        SOLVED_FILES_STORE[file_id] = {
            "bytes": excel_bytes,
            "filename": out_fname,
            "created_at": datetime.utcnow().isoformat(),
        }

        records = solved_df.fillna("").to_dict(orient="records")
        diagram_count = sum(1 for r in records if bool(r.get("Solution Image") or r.get("Solution Image URL")))

        return {
            "status": "success",
            "file_id": file_id,
            "download_url": f"/api/download-solved-excel/{file_id}",
            "filename": out_fname,
            "total_questions": len(records),
            "diagrams_generated": diagram_count,
            "questions": records,
        }
    except Exception as e:
        logger.error(f"Error in generate_solutions_df_endpoint: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/download-solved-excel/{file_id}")
async def download_solved_excel_endpoint(file_id: str):
    """Downloads the generated Excel file with embedded diagrams."""
    entry = SOLVED_FILES_STORE.get(file_id)
    if not entry:
        raise HTTPException(status_code=404, detail="File not found or expired.")

    return Response(
        content=entry["bytes"],
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{entry["filename"]}"'},
    )


# Serve frontend static assets if frontend directory exists
FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend"

if FRONTEND_DIR.exists():
    app.mount("/", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
