import functools
import json
import logging
import re
import time
import uuid
from contextlib import contextmanager, nullcontext
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

import yaml

from core.interfaces.pii import PiiDetector, apply_pii_masks
from core.services.telemetry import build_otel_tracer


def _build_otel_from_config(obs_cfg: Optional[dict]) -> Optional[Any]:
    """Build an OTel tracer from the ``observability.otel`` block (issue #47).

    Returns ``None`` when tracing is disabled or the OTel SDK is not installed,
    so the disabled path never constructs a provider (zero overhead).
    """
    if not isinstance(obs_cfg, dict):
        return None
    otel_cfg = obs_cfg.get("otel")
    if not isinstance(otel_cfg, dict):
        return None
    return build_otel_tracer(otel_cfg)



class _HybridMethod:
    """
    Descriptor so redaction methods can be called both on an instance
    (config-driven behaviour, issue #16) and on the class itself
    (backwards-compatible default behaviour, e.g.
    ``SensitiveDataRedactor.redact_text(...)`` in existing callers).
    """

    def __init__(self, func: Callable[..., str]):
        self._func = func
        self.__doc__ = func.__doc__

    def __get__(self, instance: Any, owner: Any) -> Any:
        target = instance
        if target is None:
            target = getattr(owner, "_default_instance", None)
            if target is None:
                target = owner()
                owner._default_instance = target
        return functools.partial(self._func, target)


class SensitiveDataRedactor:
    """
    Redacts secrets, API keys, passwords, bearer tokens, and credentials
    so sensitive document or query content is never exposed in logs.

    Configurable per instance (issue #16):
    - ``enabled=False`` disables redaction entirely (text patterns and the
      dict-key heuristic alike).
    - ``patterns`` (regex strings) replace the built-in defaults when provided;
      each pattern redacts the value in ``name: value`` / ``name=value``
      assignments (the label is kept for debuggability) and the bare match
      otherwise, so value-style patterns such as ``sk-...`` are also covered.

    Class-level calls keep the historical default behaviour (three built-in
    rules), so existing callers and tests are unaffected.
    """

    REDACTION_PLACEHOLDER = "[REDACTED]"

    _KEY_HINTS = (
        "password",
        "secret",
        "api_key",
        "apikey",
        "access_token",
        "private_key",
    )

    # Historical default rules: label-preserving assignments, bearer-style
    # tokens, and standalone secret literals (sk-/ghp_/AKIA).
    _DEFAULT_RULES: List[Tuple[Any, Any]] = [
        (
            re.compile(
                r"(?i)\b(api[_-]?key|secret[_-]?key|access[_-]?token|auth[_-]?token|"
                r"password|passwd|pwd|secret|client[_-]?secret)\b\s*([:=])\s*(['\"]?)"
                r"([^\s,'\";]+)\3"
            ),
            r"\1\2[REDACTED]",
        ),
        (
            re.compile(
                r"(?i)\b(authorization|bearer)\b\s*([:=\s])\s*(bearer\s+)?"
                r"([A-Za-z0-9._\-]{8,})"
            ),
            r"\1\2[REDACTED]",
        ),
        (re.compile(r"\b(sk-[A-Za-z0-9]{8,}|ghp_[A-Za-z0-9]{8,}|AKIA[0-9A-Z]{12,})\b"), "[REDACTED]"),
    ]

    _default_instance: Optional["SensitiveDataRedactor"] = None

    def __init__(
        self,
        enabled: bool = True,
        patterns: Optional[Sequence[str]] = None,
        pii_detector: Optional["PiiDetector"] = None,
        pii_classes: Optional[Sequence[str]] = None,
    ):
        self.enabled = bool(enabled)
        if patterns is None:
            self._rules: List[Tuple[Any, Any]] = list(self._DEFAULT_RULES)
        elif isinstance(patterns, (list, tuple)):
            self._rules = [
                self._compile_config_rule(str(p)) for p in patterns if str(p).strip()
            ]
        else:
            self._rules = list(self._DEFAULT_RULES)

        # PII / DLP scrubbing (issue #54). Off unless a detector is injected;
        # the detector is supplied by the composition root from the
        # observability config's ``pii:`` block.
        self.pii_detector = pii_detector
        self.pii_classes: List[str] = [
            str(c).strip().lower() for c in (pii_classes or []) if str(c).strip()
        ]

    def _redact_pii(self, text: str) -> str:
        """Strip PII spans from ``text`` (classes + counts only are reported)."""
        if self.pii_detector is None or not text:
            return text
        try:
            matches = self.pii_detector.detect(text)
        except Exception:
            # A detector failure must never break the trace/log path.
            return text
        if not matches:
            return text
        selected = [
            match
            for match in matches
            if not self.pii_classes or match.pii_class in self.pii_classes
        ]
        if not selected:
            return text
        return apply_pii_masks(text, selected)

    @staticmethod
    def _compile_config_rule(pattern: str) -> Tuple[Any, Any]:
        """
        Compile one configured pattern (regex fragment, issue AC) into a single
        pass: the assignment form ``label sep value`` keeps the label and
        separator and redacts the value (including a following bearer-style
        token); otherwise the bare match is replaced entirely.
        Invalid regex falls back to a literal (escaped) match.
        """
        try:
            combined = re.compile(
                rf"(?P<label>\b(?:{pattern})\b)(?P<sep>['\"]?\s*[:=]\s*)"
                rf"(?P<val>['\"]?[^\s,'\";]+(?:\s+[A-Za-z0-9._\-]{{8,}})?)"
                rf"|(?P<bare>\b(?:{pattern})\b)",
                re.IGNORECASE,
            )
        except re.error:
            return re.compile(re.escape(pattern), re.IGNORECASE), "[REDACTED]"

        def _sub(match: "re.Match[str]") -> str:
            if match.group("label") is not None:
                return (
                    match.group("label") + match.group("sep") + SensitiveDataRedactor.REDACTION_PLACEHOLDER
                )
            return SensitiveDataRedactor.REDACTION_PLACEHOLDER

        return combined, _sub

    @_HybridMethod
    def redact_text(self, text: Any) -> str:
        if not isinstance(text, str) or not text:
            return ""
        if not self.enabled:
            return text
        redacted = text
        for regex, repl in self._rules:
            redacted = regex.sub(repl, redacted)
        return self._redact_pii(redacted)

    @_HybridMethod
    def redact_obj(self, obj: Any) -> Any:
        if not self.enabled:
            return obj
        if isinstance(obj, str):
            return self.redact_text(obj)
        if isinstance(obj, dict):
            result = {}
            for k, v in obj.items():
                key_str = str(k).lower()
                if any(s in key_str for s in self._KEY_HINTS):
                    result[k] = self.REDACTION_PLACEHOLDER
                else:
                    result[k] = self.redact_obj(v)
            return result
        if isinstance(obj, list):
            return [self.redact_obj(item) for item in obj]
        if isinstance(obj, tuple):
            return tuple(self.redact_obj(item) for item in obj)
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

    def __init__(
        self,
        config_path: Optional[str] = None,
        logger: Optional[logging.Logger] = None,
        observability_config_path: Optional[str] = None,
        otel: Optional[Any] = None,
        redactor: Optional[SensitiveDataRedactor] = None,
    ):
        self.request_id = str(uuid.uuid4())
        self.start_perf = time.perf_counter()
        self.stage_latencies_ms: Dict[str, float] = {stage: 0.0 for stage in self.REQUIRED_STAGES}
        self.failure_tags: List[str] = []
        self.metadata: Dict[str, Any] = {}
        # Tenant attribution (issue #48): set by the pipeline before any stage.
        self.tenant: Optional[str] = None
        self.workspace: Optional[str] = None
        self.app: Optional[str] = None
        # Full attribution dimensions (issue #50): tenant/workspace/app/user/
        # cost_center, resolved once at ingress and set by the pipeline.
        self.attribution: Dict[str, str] = {}
        self.config_path = config_path
        self.observability_config_path = observability_config_path

        if observability_config_path:
            obs_cfg = self._load_obs_config(observability_config_path, dedicated=True)
            if not obs_cfg:
                obs_cfg = self._load_obs_config(config_path, dedicated=False)
        else:
            obs_cfg = self._load_obs_config(config_path, dedicated=False)

        # Reuse the pipeline's redactor when supplied so traces and logs share
        # its policy (secrets *and* PII), instead of rebuilding a narrower one.
        self._redactor = redactor or SensitiveDataRedactor(
            enabled=bool(obs_cfg.get("redact_sensitive_data", True)),
            patterns=obs_cfg.get("sensitive_patterns") if isinstance(obs_cfg, dict) else None,
        )
        self.logger = logger or self._configure_logger(obs_cfg)

        # OTel-native tracing (issue #47): explicit injection wins, else built
        # from the observability ``otel:`` block. ``None`` == tracing disabled.
        self.otel = otel if otel is not None else _build_otel_from_config(obs_cfg)
        self._root_span_cm: Optional[Any] = None
        self._root_span: Optional[Any] = None
        self._pending_attrs: Dict[str, Any] = {}

    @staticmethod
    def _load_obs_config(config_path: Optional[str], dedicated: bool = False) -> dict:
        """
        Load observability settings.

        ``dedicated=True`` reads a standalone ``observability.yaml`` whose body is
        the section itself (issue #34); otherwise the legacy ``observability``
        section nested inside the retrieval config is used.
        """
        if config_path is None:
            default_path = Path(__file__).resolve().parent.parent.parent / "config" / "retrieval.yaml"
            config_path = str(default_path)
        try:
            with open(config_path, "r") as f:
                cfg = yaml.safe_load(f) or {}
            if not isinstance(cfg, dict):
                return {}
            if dedicated:
                return cfg
            obs = cfg.get("observability") or {}
            if isinstance(obs, dict):
                return obs
        except Exception:
            pass
        return {}

    @staticmethod
    def _configure_logger(obs_cfg: Optional[dict] = None) -> logging.Logger:
        log_level = logging.INFO
        if isinstance(obs_cfg, dict):
            lvl_name = str(obs_cfg.get("log_level", "INFO")).upper()
            log_level = getattr(logging, lvl_name, logging.INFO)

        logger = logging.getLogger("enterprise_genai.pipeline")
        logger.setLevel(log_level)
        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
            handler.setFormatter(formatter)
            logger.addHandler(handler)
        return logger

    @contextmanager
    def measure_stage(self, stage_name: str):
        t0 = time.perf_counter()
        span_cm = self._stage_span(stage_name)
        try:
            with span_cm as span:
                yield span
        finally:
            elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 4)
            self.stage_latencies_ms[stage_name] = elapsed_ms

    def _stage_span(self, stage_name: str):
        """Open an OTel child span for a stage (no-op when tracing is off)."""
        if self.otel is not None and self.otel.is_available():
            self._ensure_root_span()
            return self.otel.span(f"pipeline.{stage_name}")
        return nullcontext(None)

    def _ensure_root_span(self) -> None:
        """Lazily open the root ``pipeline.run`` span so stages nest under it."""
        if self._root_span_cm is not None or self.otel is None:
            return
        if not self.otel.is_available():
            return
        self._root_span_cm = self.otel.span(
            "pipeline.run", {"request_id": self.request_id, **self._pending_attrs}
        )
        self._root_span = self._root_span_cm.__enter__()

    def set_trace_attribute(self, key: str, value: Any) -> None:
        """Attach an attribute to the root span (no-op when tracing is off).

        Attributes set before the root span exists are buffered and applied when
        it is lazily opened, so ordering within :meth:`RAGPipeline.run` is safe.
        """
        if value is None or self.otel is None or not self.otel.is_available():
            return
        if self._root_span is None:
            self._pending_attrs[key] = value
            return
        try:
            self._root_span.set_attribute(key, value)
        except Exception:  # pragma: no cover - defensive
            pass

    def end_trace(self) -> None:
        """Close the root span if one was opened (idempotent)."""
        if self._root_span_cm is not None:
            try:
                self._root_span_cm.__exit__(None, None, None)
            except Exception:  # pragma: no cover - defensive
                pass
            self._root_span_cm = None
            self._root_span = None

    def start_trace_span(self, attributes: Optional[Dict[str, Any]] = None):
        """Open the root ``pipeline.run`` span as a context (or no-op)."""
        if self.otel is not None and self.otel.is_available():
            return self.otel.span("pipeline.run", attributes)
        return nullcontext(None)

    def trace_context(self) -> Dict[str, Optional[str]]:
        """Trace/span ids for log correlation (empty when tracing is off)."""
        if self.otel is not None and self.otel.is_available():
            return self.otel.current_ids()
        return {"trace_id": None, "span_id": None}

    def add_failure_tag(self, tag: str) -> None:
        if tag and tag not in self.failure_tags:
            self.failure_tags.append(tag)
        self.set_trace_attribute("failure_tags", ",".join(self.failure_tags))

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

    def summarize_documents(self, docs: list) -> List[Dict[str, Any]]:
        summaries = []
        for rank_idx, doc in enumerate(docs or []):
            content = getattr(doc, "content", str(doc))
            redacted_preview = self._redactor.redact_text(content)[:80]
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
        sanitized = self._redactor.redact_obj(trace_payload)
        # Trace/span ids for log correlation (issue #47); captured before the
        # root span is closed so the exported trace and the log ids agree.
        ids = self.trace_context()
        if isinstance(sanitized, dict) and ids.get("trace_id"):
            sanitized.setdefault("otel", ids)
        self.end_trace()
        # ``sanitized`` already passed through the redactor, but we re-apply the
        # redactor to the serialized string immediately before logging so the
        # value handed to the logger is provably redacted at the sink itself
        # (defense in depth; also makes the sanitization explicit to static
        # analysis instead of relying on recognizing the redactor as a barrier).
        serialized = self._redactor.redact_text(json.dumps(sanitized, default=str))
        prefix = (
            f"[trace_id={ids['trace_id']} span_id={ids['span_id']}] "
            if ids.get("trace_id")
            else ""
        )
        if is_error:
            self.logger.error("%sRAGPipeline execution failed: %s", prefix, serialized)
        elif self.failure_tags:
            self.logger.warning(
                "%sRAGPipeline completed with failure tags %s: %s",
                prefix,
                self.failure_tags,
                serialized,
            )
        else:
            self.logger.info("%sRAGPipeline execution trace: %s", prefix, serialized)
        return sanitized