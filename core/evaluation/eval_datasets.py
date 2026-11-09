"""Eval dataset schema + loaders (issue #124, Workstream K).

Provides a canonical, versioned schema for domain-specific evaluation datasets
and config-driven loaders. Supports the legacy IR benchmark shape
(``{docs, cases:[{query,relevant_doc_ids}]}``) and a general RAG eval-case
shape (``{cases:[{query, reference|ground_truth, tags, metadata, ...}]}`` or a
bare case list). Loaders accept JSON and JSONL; paths are resolved relative to
the repository root unless absolute.

The module is deliberately dependency-light (stdlib + pydantic for schema
validation where useful) and does not import ``ui.*`` or ``app.*``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple, Union

SUPPORTED_FORMATS = ("json", "jsonl")
REPO_ROOT = Path(__file__).resolve().parents[2]


def _repo_path(path: Union[str, Path]) -> Path:
    target = Path(path)
    if not target.is_absolute():
        target = REPO_ROOT / target
    return target


@dataclass(frozen=True)
class EvalCase:
    """A single evaluation case (RAG/ground-truth style)."""

    query: str
    reference: str = ""
    relevant_doc_ids: Tuple[int, ...] = ()
    tags: Tuple[str, ...] = ()
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class EvalDataset:
    """Loaded evaluation dataset."""

    name: str
    path: Optional[str]
    format: str
    cases: List[EvalCase]
    docs: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def kind(self) -> str:
        if self.docs or any(case.relevant_doc_ids for case in self.cases):
            return "ir_benchmark"
        return "rag_eval"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "path": self.path,
            "format": self.format,
            "kind": self.kind,
            "num_cases": len(self.cases),
            "num_docs": len(self.docs),
            "metadata": dict(self.metadata),
        }


class EvalDatasetValidationError(ValueError):
    """Raised when a dataset payload fails schema validation."""


def _as_str_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()] if str(value).strip() else []


def _as_int_list(value: Any) -> List[int]:
    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        return []
    out: List[int] = []
    for item in value:
        if isinstance(item, bool):
            continue
        if isinstance(item, int):
            out.append(item)
        elif isinstance(item, str) and item.strip().lstrip("-").isdigit():
            out.append(int(item))
    return out


def _reference_from_docs(case: Mapping[str, Any], docs: Sequence[Any]) -> str:
    ids = _as_int_list(case.get("relevant_doc_ids") or case.get("relevant_docs"))
    parts: List[str] = []
    for doc_id in ids:
        if doc_id < 0 or doc_id >= len(docs):
            continue
        doc = docs[doc_id]
        if isinstance(doc, Mapping):
            content = str(doc.get("content") or doc.get("text") or "").strip()
        else:
            content = str(doc).strip()
        if content:
            parts.append(content)
    return " ".join(parts)


def normalize_case(raw: Mapping[str, Any], *, docs: Sequence[Any] = (), index: int = 1) -> EvalCase:
    if not isinstance(raw, Mapping):
        raise EvalDatasetValidationError(f"Case {index} must be an object")
    query = str(raw.get("query") or raw.get("question") or raw.get("input") or "").strip()
    if not query:
        raise EvalDatasetValidationError(f"Case {index} is missing a non-empty query")

    reference: Any = (
        raw.get("reference")
        or raw.get("ground_truth")
        or raw.get("expected_answer")
        or raw.get("expected")
        or raw.get("answer")
        or ""
    )
    if isinstance(reference, (list, tuple)):
        reference = " ".join(str(item).strip() for item in reference if str(item).strip())
    reference_text = str(reference).strip() or _reference_from_docs(raw, docs)

    relevant = tuple(_as_int_list(raw.get("relevant_doc_ids") or raw.get("relevant_docs")))
    tags = tuple(_as_str_list(raw.get("tags") or raw.get("labels")))
    known = {
        "query",
        "question",
        "input",
        "reference",
        "ground_truth",
        "expected_answer",
        "expected",
        "answer",
        "relevant_doc_ids",
        "relevant_docs",
        "tags",
        "labels",
        "metadata",
    }
    metadata = dict(raw.get("metadata") or {})
    if not isinstance(metadata, dict):
        metadata = {}
    for key, value in raw.items():
        if key not in known:
            metadata.setdefault(str(key), value)
    return EvalCase(
        query=query,
        reference=reference_text,
        relevant_doc_ids=relevant,
        tags=tags,
        metadata=metadata,
    )


def parse_dataset_payload(
    payload: Any,
    *,
    name: str = "dataset",
    path: Optional[str] = None,
    fmt: str = "json",
) -> EvalDataset:
    """Normalize a decoded JSON/JSONL payload into an :class:`EvalDataset`."""
    docs: List[Dict[str, Any]] = []
    metadata: Dict[str, Any] = {}
    if isinstance(payload, Mapping):
        raw_docs = payload.get("docs") or []
        if isinstance(raw_docs, list):
            docs = [dict(d) if isinstance(d, Mapping) else {"content": str(d)} for d in raw_docs]
        raw_cases = payload.get("cases")
        for key in ("name", "description", "domain", "version", "task"):
            if key in payload and payload[key] not in (None, ""):
                metadata[key] = payload[key]
    elif isinstance(payload, list):
        raw_cases = payload
    else:
        raise EvalDatasetValidationError("Dataset must be an object with `cases` or a case list")

    if not isinstance(raw_cases, list) or not raw_cases:
        raise EvalDatasetValidationError(f"{name}: dataset must contain at least one case")

    cases = [normalize_case(raw, docs=docs, index=i) for i, raw in enumerate(raw_cases, start=1)]
    return EvalDataset(
        name=str(metadata.get("name") or name),
        path=path,
        format=fmt,
        cases=cases,
        docs=docs,
        metadata=metadata,
    )


def load_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as handle:
        for lineno, line in enumerate(handle, start=1):
            text = line.strip()
            if not text:
                continue
            try:
                value = json.loads(text)
            except json.JSONDecodeError as exc:
                raise EvalDatasetValidationError(
                    f"{path}: invalid JSONL at line {lineno}: {exc.msg}"
                ) from exc
            if not isinstance(value, Mapping):
                raise EvalDatasetValidationError(f"{path}: line {lineno} must be an object")
            rows.append(dict(value))
    return rows


def load_eval_dataset(path: Union[str, Path], *, name: Optional[str] = None) -> EvalDataset:
    target = _repo_path(path)
    if not target.exists():
        raise EvalDatasetValidationError(f"Eval dataset not found: {target}")
    suffix = target.suffix.lower().lstrip(".")
    if suffix not in SUPPORTED_FORMATS:
        raise EvalDatasetValidationError(
            f"Unsupported eval dataset format '.{suffix}' for {target.name}; "
            f"supported: {', '.join(SUPPORTED_FORMATS)}"
        )
    dataset_name = name or target.stem
    if suffix == "jsonl":
        payload: Any = load_jsonl(target)
        # A JSONL file may be docs+cases? treat as case list unless wrapped upstream.
        return parse_dataset_payload(payload, name=dataset_name, path=str(target), fmt="jsonl")
    with open(target, "r", encoding="utf-8") as handle:
        try:
            payload = json.load(handle)
        except json.JSONDecodeError as exc:
            raise EvalDatasetValidationError(
                f"{target}: invalid JSON: {exc.msg} (line {exc.lineno})"
            ) from exc
    return parse_dataset_payload(payload, name=dataset_name, path=str(target), fmt="json")


def discover_eval_datasets(
    config: Optional[Mapping[str, Any]] = None,
    *,
    paths: Optional[Sequence[Union[str, Path]]] = None,
) -> List[EvalDataset]:
    """Load datasets declared in config and/or explicit paths.

    Config shape (``config/eval_datasets.yaml``)::

        enabled: true
        datasets:
          qa: {path: data/my_qa.jsonl, format: jsonl, domain: qa}
          benchmark: data/benchmark.json

    Disabled/missing config returns ``[]`` unless explicit ``paths`` are given.
    """
    datasets: List[EvalDataset] = []
    cfg = config or {}
    if isinstance(cfg, Mapping) and "eval_datasets" in cfg and isinstance(cfg["eval_datasets"], Mapping):
        cfg = cfg["eval_datasets"]
    enabled = bool(cfg.get("enabled", False)) if isinstance(cfg, Mapping) else False
    if enabled and isinstance(cfg, Mapping):
        declared = cfg.get("datasets") or {}
        if isinstance(declared, Mapping):
            for ds_name, spec in declared.items():
                if isinstance(spec, str):
                    spec = {"path": spec}
                if not isinstance(spec, Mapping):
                    raise EvalDatasetValidationError(f"Dataset '{ds_name}' spec must be a mapping or path")
                ds_path = spec.get("path")
                if not ds_path:
                    raise EvalDatasetValidationError(f"Dataset '{ds_name}' requires a `path`")
                dataset = load_eval_dataset(ds_path, name=str(ds_name))
                extra_meta = {k: v for k, v in spec.items() if k not in {"path", "format"}}
                dataset.metadata.update(extra_meta)
                datasets.append(dataset)
    for path in paths or []:
        datasets.append(load_eval_dataset(path))
    return datasets


def validate_eval_dataset_file(path: Union[str, Path]) -> Dict[str, Any]:
    """Validate a dataset file and return a small summary (CLI/config helper)."""
    dataset = load_eval_dataset(path)
    return {
        "ok": True,
        "dataset": dataset.to_dict(),
    }
