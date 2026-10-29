import os
import sys
import logging
import datetime
from pathlib import Path
from collections import deque
from logging.handlers import RotatingFileHandler
from typing import List, Dict, Any, Optional

# Base directories
BACKEND_DIR = Path(__file__).resolve().parent.parent
LOGS_DIR = BACKEND_DIR / "logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)
LOG_FILE_PATH = LOGS_DIR / "app.log"

# Global in-memory log buffer (retains the latest 1,000 log events for API & Web Dashboard)
MAX_MEMORY_LOGS = 1000
_memory_logs: deque = deque(maxlen=MAX_MEMORY_LOGS)
_log_sequence_counter: int = 0


class InMemoryLogHandler(logging.Handler):
    """Custom logging handler that collects structured records in a bounded ring buffer."""

    def emit(self, record: logging.LogRecord):
        global _log_sequence_counter
        try:
            _log_sequence_counter += 1
            msg = self.format(record)
            entry = {
                "id": _log_sequence_counter,
                "timestamp": datetime.datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S"),
                "level": record.levelname,
                "logger": record.name,
                "message": msg,
            }
            _memory_logs.append(entry)
        except Exception:
            self.handleError(record)


# Create Root App Logger
_root_logger = logging.getLogger("mcq_app")
_root_logger.setLevel(logging.INFO)

# Prevent duplicate handlers on module reload
if not _root_logger.handlers:
    # 1. Standard Formatter
    log_format = logging.Formatter(
        fmt="[%(asctime)s] [%(levelname)s] [%(name)s]: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # 2. Console Handler (stdout)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(log_format)
    _root_logger.addHandler(console_handler)

    # 3. Rotating File Handler (10 MB, up to 5 backups)
    try:
        file_handler = RotatingFileHandler(
            filename=str(LOG_FILE_PATH),
            maxBytes=10 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8"
        )
        file_handler.setLevel(logging.INFO)
        file_handler.setFormatter(log_format)
        _root_logger.addHandler(file_handler)
    except Exception as err:
        sys.stderr.write(f"Warning: Could not initialize rotating file logger: {err}\n")

    # 4. In-Memory Ring Buffer Handler
    raw_formatter = logging.Formatter("%(message)s")
    mem_handler = InMemoryLogHandler()
    mem_handler.setLevel(logging.INFO)
    mem_handler.setFormatter(raw_formatter)
    _root_logger.addHandler(mem_handler)


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """Returns a namespaced logger child of mcq_app."""
    if not name or name == "mcq_app":
        return _root_logger
    # Strip redundant app prefixes if present
    clean_name = name.replace("app.", "")
    return _root_logger.getChild(clean_name)


def get_recent_logs(
    limit: int = 200,
    min_level: str = "ALL",
    search: str = ""
) -> List[Dict[str, Any]]:
    """Fetches recent log entries from the in-memory ring buffer with optional filtering."""
    level_hierarchy = {
        "DEBUG": 10,
        "INFO": 20,
        "WARNING": 30,
        "WARN": 30,
        "ERROR": 40,
        "CRITICAL": 50
    }

    min_val = level_hierarchy.get(min_level.upper(), 0) if min_level.upper() != "ALL" else 0
    search_lower = search.strip().lower()

    logs = list(_memory_logs)
    filtered = []

    for item in logs:
        item_level_val = level_hierarchy.get(item["level"].upper(), 20)
        if item_level_val < min_val:
            continue
        if search_lower and (search_lower not in item["message"].lower() and search_lower not in item["logger"].lower()):
            continue
        filtered.append(item)

    if limit > 0:
        return filtered[-limit:]
    return filtered


def clear_log_buffer() -> None:
    """Clears both the in-memory buffer and truncates the active log file."""
    _memory_logs.clear()
    try:
        if LOG_FILE_PATH.exists():
            with open(LOG_FILE_PATH, "w", encoding="utf-8") as f:
                f.truncate(0)
    except Exception:
        pass


def get_log_file_path() -> Path:
    """Returns the absolute Path to app.log."""
    return LOG_FILE_PATH
