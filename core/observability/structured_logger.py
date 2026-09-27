import logging
import json
import re
from typing import Any, Dict, Optional

# Regex patterns to sanitize sensitive credentials/keys
SENSITIVE_PATTERNS = [
    re.compile(r"(?i)(api[_-]?key|password|secret|token|auth)\s*[:=]\s*['\"]?([^\s'\"]+)['\"]?"),
    re.compile(r"(?i)(sk-[a-zA-Z0-9_-]{20,})"),
    re.compile(r"(?i)(bearer\s+[a-zA-Z0-9_\-\.]+)"),
]


def sanitize_text(text: str) -> str:
    """Masks secrets, api keys, and passwords from logs."""
    if not isinstance(text, str):
        return text
    sanitized = text
    for pattern in SENSITIVE_PATTERNS:
        sanitized = pattern.sub(r"[REDACTED_SECRET]", sanitized)
    return sanitized


class StructuredLogger:
    """
    Structured logger for Gen-AI / RAG pipeline stages and events.
    """

    def __init__(self, name: str = "rag_pipeline"):
        self.logger = logging.getLogger(name)
        if not self.logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                fmt="%(asctime)s [%(levelname)s] [%(name)s] %(message)s",
                datefmt="%Y-%m-%d %H:%M:%S"
            )
            handler.setFormatter(formatter)
            self.logger.addHandler(handler)
            self.logger.setLevel(logging.INFO)

    def log_stage(self, stage: str, data: Dict[str, Any], level: str = "info"):
        sanitized_data = {
            k: (sanitize_text(v) if isinstance(v, str) else v)
            for k, v in data.items()
        }
        log_entry = json.dumps({"stage": stage, **sanitized_data}, default=str)
        log_func = getattr(self.logger, level.lower(), self.logger.info)
        log_func(log_entry)

    def info(self, msg: str, **kwargs):
        self.logger.info(sanitize_text(msg), **kwargs)

    def warning(self, msg: str, **kwargs):
        self.logger.warning(sanitize_text(msg), **kwargs)

    def error(self, msg: str, **kwargs):
        self.logger.error(sanitize_text(msg), **kwargs)
