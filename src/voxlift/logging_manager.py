# src/voxlift/logging_manager.py
"""
Structured JSON logging for Voxlift.

Design principles:
1. All logs are JSON for easy parsing and analysis
2. Logs go to both file (persistent) and stderr (real-time)
3. Each log entry has: timestamp, level, module, event, message, and optional data
4. Rotating file handler prevents disk fill
"""

import json
import logging
import os
import sys
import traceback
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from typing import Any, Dict, Optional


# Paths
DEFAULT_LOG_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "logs")
DEFAULT_LOG_FILE = os.path.join(DEFAULT_LOG_DIR, "voxlift.jsonl")  # JSON Lines format


class JSONFormatter(logging.Formatter):
    """Format log records as JSON."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "ts": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "level": record.levelname,
            "module": record.name,
            "event": getattr(record, "event", "log"),
            "msg": record.getMessage(),
        }

        # Add extra data if present
        if hasattr(record, "data") and record.data:
            log_entry["data"] = record.data

        # Add exception info if present
        if record.exc_info:
            log_entry["error"] = {
                "type": record.exc_info[0].__name__ if record.exc_info[0] else "Unknown",
                "message": str(record.exc_info[1]) if record.exc_info[1] else "",
                "traceback": traceback.format_exception(*record.exc_info),
            }

        return json.dumps(log_entry, ensure_ascii=False, default=str)


class ConsoleFormatter(logging.Formatter):
    """Human-readable format for console output."""

    COLORS = {
        "DEBUG": "\033[36m",     # Cyan
        "INFO": "\033[32m",      # Green
        "WARNING": "\033[33m",   # Yellow
        "ERROR": "\033[31m",     # Red
        "CRITICAL": "\033[35m",  # Magenta
    }
    RESET = "\033[0m"

    def format(self, record: logging.LogRecord) -> str:
        color = self.COLORS.get(record.levelname, "")
        event = getattr(record, "event", "")
        event_str = f"[{event}] " if event else ""

        timestamp = datetime.now().strftime("%H:%M:%S")
        data_str = ""
        if getattr(record, "data", None):
            try:
                data_str = " | " + json.dumps(record.data, ensure_ascii=False, default=str)
            except Exception:
                data_str = f" | data={record.data}"
        return f"{color}[{timestamp}] {record.levelname:7} [{record.name}]: {event_str}{record.getMessage()}{data_str}{self.RESET}"


_initialized = False


def init_logger(
    level: str = "INFO",
    log_file: Optional[str] = None,
    max_bytes: int = 10 * 1024 * 1024,  # 10MB
    backup_count: int = 5,
) -> None:
    """
    Initialize the logging system.

    Creates:
    - JSON file handler (for analysis/debugging)
    - Console handler (for real-time feedback)
    """
    global _initialized
    if _initialized:
        return

    log_file = log_file or DEFAULT_LOG_FILE
    log_dir = os.path.dirname(log_file)
    os.makedirs(log_dir, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Clear existing handlers
    root.handlers.clear()

    # JSON file handler (structured logs for analysis)
    file_handler = RotatingFileHandler(
        filename=log_file,
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8"
    )
    file_handler.setFormatter(JSONFormatter())
    file_handler.setLevel(logging.DEBUG)  # Log everything to file
    root.addHandler(file_handler)

    # Console handler (human-readable)
    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setFormatter(ConsoleFormatter())
    console_handler.setLevel(getattr(logging, level.upper(), logging.INFO))
    root.addHandler(console_handler)

    _initialized = True

    # Log initialization
    log_event("logging", "init", f"Logging initialized. File: {log_file}", level="INFO")


def log_event(
    module: str,
    event: str,
    message: str,
    level: str = "INFO",
    data: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Log a structured event.

    Args:
        module: Module name (e.g., 'downloader', 'transcriber', 'scheduler')
        event: Event type (e.g., 'download_start', 'transcribe_complete')
        message: Human-readable message
        level: Log level ('DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL')
        data: Optional structured data to include
    """
    logger = logging.getLogger(module)

    # Create a LogRecord with extra attributes
    payload = data or None
    record = logger.makeRecord(
        name=module,
        level=getattr(logging, level.upper(), logging.INFO),
        fn="",
        lno=0,
        msg=message,
        args=(),
        exc_info=None,
    )
    record.event = event
    record.data = payload

    logger.handle(record)


def log_error(
    module: str,
    event: str,
    message: str,
    exc: Optional[Exception] = None,
    data: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Log an error with optional exception info.

    Args:
        module: Module name
        event: Event type (e.g., 'download_error')
        message: Error message
        exc: Optional exception object
        data: Optional structured data
    """
    logger = logging.getLogger(module)

    extra_data = data or {}
    if exc:
        extra_data["error_type"] = type(exc).__name__
        extra_data["error_message"] = str(exc)
        extra_data["traceback"] = traceback.format_exc()

    record = logger.makeRecord(
        name=module,
        level=logging.ERROR,
        fn="",
        lno=0,
        msg=message,
        args=(),
        exc_info=(type(exc), exc, exc.__traceback__) if exc else None,
    )
    record.event = event
    record.data = extra_data

    logger.handle(record)


def get_log_file_path() -> str:
    """Get the current log file path."""
    return DEFAULT_LOG_FILE
