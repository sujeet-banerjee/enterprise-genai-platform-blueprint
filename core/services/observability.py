from contextlib import contextmanager
import json
import logging
from pathlib import Path
import re
import time
from typing import Any, Dict, List, Optional
import uuid
import yaml


class SensitiveDataRedactor:
    """
    Redacts secrets, API keys, passwords, bearer tokens, and credentials
    so sensitive document or query content is never exposed in logs.
    """

    _PATTERNS = [
        re.compile(
            r"(?i)\b(api[_-]?key|secret[_-]?key|access[_-]?token|auth[_-]?token|password|passwd|pwd|secret|client[_-]?secret)\b\s*([:=])\s*(['\"]?)([^\s,'\";]+)\3"
        ),
        re.compile(r"(?i)\b(authorization|bearer)\b\s*([:=\s])\s*(bearer\s+)?([A-Za-z0-9._\-]{8,})"),
        re.compile(r"\b(sk-[A-Za-z0-9]{8,}|ghp_[A-Za-z0-9]{8,}|AKIA[0-9A-Z]{12,})\b"),
    ]

    @classmethod
    def redact_text(cls, text: str) -> str:
        if not isinstance(text, str) or not text:
            return ""
        redacted = text
        redacted = cls._PATTERNS[0].sub(r"\1\2[REDACTED]", redacted)
        redacted = cls._PATTERNS[1].sub(r"\1\2[REDACTED]", redacted)
        redacted = cls._PATTERNS[2].sub("[REDACTED]", redacted)
        return redacted

    @classmethod
    def redact_obj(cls, obj: Any) -> Any:
        if isinstance(obj, str):
            return cls.redact_text(obj)
        if isinstance(obj, dict):
            result = {}
            for k, v in obj.items():
                key_str = str(k).lower()
                if any(s in key_str for s in ("password", "secret", "api_key", "apikey", "access_token", "private_key")):
                    result[k] = "[REDACTED]"
                else:
                    result[k] = cls.redact_obj(v)
            return result
        if isinstance(obj, list):
            return [cls.redact_obj(item) for item in obj]
        if isinstance(obj, tuple):
            return tuple(cls.redact_obj(item) for item in obj)
        return obj


class PipelineObservabilityTracker:
    """
    Measures stage-by-stage latency and captures structured execution traces
    with automatic secret redaction.
    """

    REQUIRED_STAGES = (
        "embedding",
        "retrieval",
        "reranking",
        "token_budget",
        "prompt_construction",
        "llm_generation",
        "evaluation",
    )

    def __init__(self, config_path: Optional[str] = None, logger: Optional[logging.Logger] = None):
        self.request_id = str(uuid.uuid4())
        self.start_perf = time.perf_counter()
        self.stage_latencies_ms: Dict[str, float] = {stage: 0.0 for stage in self.REQUIRED_STAGES}
        self.failure_tags: List[str] = []
        self.metadata: Dict[str, Any] = {}
        self.logger = logger or self._configure_logger(config_path)

    @staticmethod
    def _configure_logger(config_path: Optional[str] = None) -> logging.Logger:
        log_level = logging.INFO
        if config_path is None:
            default_path = Path(__file__).resolve().parent.parent.parent / "config" / "retrieval.yaml"
            config_path = str(default_path)
        try:
            with open(config_path, "r") as f:
                cfg = yaml.safe_load(f) or {}
                lvl_name = str((cfg.get("observability") or {}).get("log_level", "INFO")).upper()
                log_level = getattr(logging, lvl_name, logging.INFO)
        except Exception:
            pass

        logger = logging.getLogger("enterprise_genai.pipeline")
        logger.setLevel(log_level)
        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
            handler.setFormatter(formatter)
            logger.addHandler(handler)

            ### SUJEET
            # Create a file handler
            file_handler = logging.FileHandler("pipeline.log")
            file_handler.setLevel(logging.DEBUG)

            # Create a formatter so the logs are readable
            formatter = logging.Formatter('%(asctime)s | %(levelname)s | %(name)s | %(message)s')
            file_handler.setFormatter(formatter)

            # Attach the handler to the logger
            logger.addHandler(file_handler)
            ####
        return logger

    @contextmanager
    def measure_stage(self, stage_name: str):
        t0 = time.perf_counter()
        try:
            yield
        finally:
            elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 4)
            self.stage_latencies_ms[stage_name] = elapsed_ms

    def add_failure_tag(self, tag: str) -> None:
        if tag and tag not in self.failure_tags:
            self.failure_tags.append(tag)

    def get_latency_report(self) -> Dict[str, float]:
        total_ms = round((time.perf_counter() - self.start_perf) * 1000.0, 4)
        report: Dict[str, float] = {}
        for stage, ms in self.stage_latencies_ms.items():
            report[stage] = ms
            report[f"{stage}_ms"] = ms
        report["total_pipeline"] = total_ms
        report["total_pipeline_ms"] = total_ms
        report["total_ms"] = total_ms
        return report

    @staticmethod
    def summarize_documents(docs: list) -> List[Dict[str, Any]]:
        summaries = []
        for rank_idx, doc in enumerate(docs or []):
            content = getattr(doc, "content", str(doc))
            redacted_preview = SensitiveDataRedactor.redact_text(content)[:80]
            score = getattr(doc, "score", None)
            meta = getattr(doc, "metadata", {}) or {}
            if score is None and isinstance(meta, dict):
                score = meta.get("score")
            summaries.append(
                {
                    "rank": rank_idx,
                    "doc_id": meta.get("doc_id", rank_idx) if isinstance(meta, dict) else rank_idx,
                    "score": score,
                    "content_length": len(content),
                    "preview": redacted_preview,
                }
            )
        return summaries

    def log_trace(self, trace_payload: Dict[str, Any], is_error: bool = False) -> Dict[str, Any]:
        sanitized = SensitiveDataRedactor.redact_obj(trace_payload)
        serialized = json.dumps(sanitized, default=str)
        if is_error:
            self.logger.error("RAGPipeline execution failed: %s", serialized)
        elif self.failure_tags:
            self.logger.warning("RAGPipeline completed with failure tags %s: %s", self.failure_tags, serialized)
        else:
            self.logger.info("RAGPipeline execution trace: %s", serialized)
        return sanitized
