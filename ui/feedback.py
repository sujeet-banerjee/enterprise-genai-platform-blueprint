"""Collaboration and feedback capture for the console (issue #158).

The console lets a reviewer annotate a request, flag a bad answer with a reason,
leave a short note, and promote the run into a studio evaluation dataset. This
module owns the bounded, redacted state contract so it can be unit-tested
without Streamlit or a live API.

Annotations are per-user console state (UX8 workspace). Share links intentionally
carry the request id, flag and reason but never the note text; full notes only
travel through a local workspace export/import or the redacted evidence pack.
"""

from __future__ import annotations

import csv
import io
import json
import re
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from ui.dataset_studio import (
    MAX_STUDIO_CASES,
    add_case,
    find_dataset,
    new_dataset,
    normalize_dataset,
    save_dataset,
)

FLAG_REASONS: Tuple[str, ...] = (
    "incorrect",
    "unsupported",
    "outdated",
    "unsafe",
    "off_topic",
    "other",
)

REASON_LABELS: Dict[str, str] = {
    "incorrect": "incorrect",
    "unsupported": "unsupported",
    "outdated": "outdated",
    "unsafe": "unsafe",
    "off_topic": "off-topic",
    "other": "other",
}

ANY_REASON = "any"
ANY_PROMOTED = "any"
DEFAULT_DATASET_NAME = "Feedback review"
FEEDBACK_TAG = "feedback"
EXPORT_SCHEMA = "genai-feedback/v1"

MAX_ANNOTATIONS = 50
MAX_NOTE_CHARS = 1_000
MAX_QUERY_CHARS = 2_000
MAX_ID_CHARS = 200
MAX_TAGS = 5
MAX_TAG_CHARS = 40
MAX_TENANT_CHARS = 120
MAX_USER_CHARS = 120

_SECRET_VALUE_RE = re.compile(
    r"(sk-[A-Za-z0-9_-]{4,}|Bearer\s+[A-Za-z0-9._~+/=-]{8,}"
    r"|\$\{[A-Za-z_][A-Za-z0-9_]*\}|env:[A-Za-z_][A-Za-z0-9_]*)"
)
_CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")
_ID_RE = re.compile(r"[^A-Za-z0-9._:@/+=-]+")


def clean_request_id(value: Any) -> str:
    """Bound and sanitise a request id; returns ``""`` when absent."""
    if value is None:
        return ""
    return _ID_RE.sub("", str(value).strip())[:MAX_ID_CHARS]


def _clean_text(value: Any, limit: int) -> str:
    text = _CONTROL_RE.sub("", str(value or ""))
    text = _SECRET_VALUE_RE.sub("[REDACTED]", text)
    return text.strip()[:limit]


def redact_note(value: Any, limit: int = MAX_NOTE_CHARS) -> str:
    """Redact obvious secrets from reviewer notes before storing or exporting."""
    return _clean_text(value, limit)


def normalize_reason(value: Any) -> str:
    """Map a selector value (``off-topic``) to a canonical reason key."""
    text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    return text if text in FLAG_REASONS else "other"


def reason_label(value: Any) -> str:
    return REASON_LABELS.get(normalize_reason(value), "other")


def _clean_tags(value: Any) -> List[str]:
    if isinstance(value, str):
        value = value.split(",")
    if not isinstance(value, (list, tuple)):
        return []
    tags: List[str] = []
    for tag in value:
        clean = _clean_text(tag, MAX_TAG_CHARS)
        if clean and clean not in tags:
            tags.append(clean)
        if len(tags) >= MAX_TAGS:
            break
    return tags


def _as_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in ("1", "true", "yes", "on"):
        return True
    if text in ("0", "false", "no", "off"):
        return False
    return default


def normalize_annotation(value: Any) -> Optional[Dict[str, Any]]:
    """Return a bounded annotation or ``None`` when there is no request id."""
    if not isinstance(value, Mapping):
        return None
    request_id = clean_request_id(value.get("request_id"))
    if not request_id:
        return None
    return {
        "request_id": request_id,
        "query": _clean_text(value.get("query"), MAX_QUERY_CHARS),
        "flag": _as_bool(value.get("flag"), True),
        "reason": normalize_reason(value.get("reason")),
        "note": redact_note(value.get("note")),
        "tags": _clean_tags(value.get("tags")),
        "failure_type": _clean_text(value.get("failure_type"), 80),
        "tenant": _clean_text(value.get("tenant"), MAX_TENANT_CHARS),
        "user": _clean_text(value.get("user"), MAX_USER_CHARS),
        "promoted": _as_bool(value.get("promoted"), False),
        "created_at": _clean_text(value.get("created_at"), 40),
    }


def normalize_annotations(value: Any) -> List[Dict[str, Any]]:
    """Bounded, deduplicated annotation list for the workspace layer."""
    if not isinstance(value, (list, tuple)):
        return []
    annotations: List[Dict[str, Any]] = []
    seen: set = set()
    for item in value:
        annotation = normalize_annotation(item)
        if annotation is None or annotation["request_id"] in seen:
            continue
        seen.add(annotation["request_id"])
        annotations.append(annotation)
        if len(annotations) >= MAX_ANNOTATIONS:
            break
    return annotations


def new_annotation(
    request_id: Any,
    *,
    query: Any = "",
    reason: Any = "other",
    note: Any = "",
    flag: bool = True,
    tags: Sequence[str] = (),
    failure_type: Any = "",
    tenant: Any = "",
    user: Any = "",
    promoted: bool = False,
    created_at: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a normalized annotation; raises when the request id is invalid."""
    annotation = normalize_annotation(
        {
            "request_id": request_id,
            "query": query,
            "reason": reason,
            "note": note,
            "flag": flag,
            "tags": list(tags),
            "failure_type": failure_type,
            "tenant": tenant,
            "user": user,
            "promoted": promoted,
            "created_at": created_at
            or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
    )
    if annotation is None:
        raise ValueError("A request id is required to annotate a run")
    return annotation


def upsert_annotation(
    annotations: Iterable[Mapping[str, Any]], annotation: Mapping[str, Any]
) -> List[Dict[str, Any]]:
    """Insert or replace one annotation (newest first, bounded)."""
    clean = normalize_annotation(annotation)
    if clean is None:
        raise ValueError("A request id is required to annotate a run")
    rest = [
        dict(item)
        for item in normalize_annotations(list(annotations))
        if item["request_id"] != clean["request_id"]
    ]
    return [clean, *rest][:MAX_ANNOTATIONS]


def remove_annotation(
    annotations: Iterable[Mapping[str, Any]], request_id: Any
) -> List[Dict[str, Any]]:
    target = clean_request_id(request_id)
    return [
        dict(item)
        for item in normalize_annotations(list(annotations))
        if item["request_id"] != target
    ]


def find_annotation(
    annotations: Iterable[Mapping[str, Any]], request_id: Any
) -> Optional[Dict[str, Any]]:
    target = clean_request_id(request_id)
    if not target:
        return None
    for item in normalize_annotations(list(annotations)):
        if item["request_id"] == target:
            return item
    return None


def set_promoted(
    annotations: Iterable[Mapping[str, Any]], request_id: Any, promoted: bool = True
) -> List[Dict[str, Any]]:
    target = clean_request_id(request_id)
    out: List[Dict[str, Any]] = []
    for item in normalize_annotations(list(annotations)):
        entry = dict(item)
        if entry["request_id"] == target:
            entry["promoted"] = bool(promoted)
        out.append(entry)
    return out


def annotation_rows(annotations: Iterable[Mapping[str, Any]]) -> List[Dict[str, Any]]:
    """Flat, redacted rows for tables and exports."""
    rows: List[Dict[str, Any]] = []
    for item in normalize_annotations(list(annotations)):
        rows.append(
            {
                "request_id": item["request_id"],
                "flagged": "yes" if item["flag"] else "no",
                "reason": reason_label(item["reason"]),
                "note": item["note"],
                "promoted": "yes" if item["promoted"] else "no",
                "failure_type": item["failure_type"],
                "query": item["query"],
                "tenant": item["tenant"],
                "user": item["user"],
                "created_at": item["created_at"],
            }
        )
    return rows


def reason_summary(annotations: Iterable[Mapping[str, Any]]) -> Dict[str, Any]:
    """Counts for header tiles and the reason breakdown."""
    items = normalize_annotations(list(annotations))
    by_reason = {reason: 0 for reason in FLAG_REASONS}
    flagged = 0
    promoted = 0
    for item in items:
        if item["flag"]:
            flagged += 1
            by_reason[item["reason"]] = by_reason.get(item["reason"], 0) + 1
        if item["promoted"]:
            promoted += 1
    return {
        "total": len(items),
        "flagged": flagged,
        "promoted": promoted,
        "by_reason": by_reason,
    }


def filter_annotations(
    annotations: Iterable[Mapping[str, Any]],
    *,
    reason: Any = ANY_REASON,
    promoted: Any = ANY_PROMOTED,
    search: Any = "",
) -> List[Dict[str, Any]]:
    """Filter by reason, promotion state and a free-text search."""
    items = normalize_annotations(list(annotations))
    reason_choice = str(reason or ANY_REASON).strip().lower()
    promoted_choice = str(promoted or ANY_PROMOTED).strip().lower()
    needle = str(search or "").strip().lower()
    out: List[Dict[str, Any]] = []
    for item in items:
        if reason_choice not in (ANY_REASON, "", "all") and item["reason"] != normalize_reason(
            reason_choice
        ):
            continue
        if promoted_choice in ("yes", "true", "promoted") and not item["promoted"]:
            continue
        if promoted_choice in ("no", "false", "unpromoted") and item["promoted"]:
            continue
        if needle:
            haystack = " ".join(
                [
                    item["request_id"],
                    item["query"],
                    item["note"],
                    reason_label(item["reason"]),
                    item["failure_type"],
                    item["tenant"],
                    item["user"],
                ]
            ).lower()
            if needle not in haystack:
                continue
        out.append(item)
    return out


def build_eval_case(annotation: Mapping[str, Any]) -> Dict[str, Any]:
    """Turn an annotation into a studio evaluation case."""
    clean = normalize_annotation(annotation)
    if clean is None:
        raise ValueError("A request id is required to promote a run")
    tags = [FEEDBACK_TAG, f"feedback:{clean['reason']}", f"request:{clean['request_id']}"]
    return {
        "query": clean["query"],
        "reference": clean["note"],
        "tags": _clean_tags(tags),
    }


def promote_to_dataset(
    saved: Sequence[Mapping[str, Any]],
    annotation: Mapping[str, Any],
    dataset_name: str = DEFAULT_DATASET_NAME,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Create or append the dataset case for an annotation (idempotent)."""
    clean = normalize_annotation(annotation)
    if clean is None:
        raise ValueError("A request id is required to promote a run")
    case = build_eval_case(clean)
    name = _clean_text(dataset_name, 80) or DEFAULT_DATASET_NAME
    dataset = find_dataset(saved, name)
    marker = f"request:{clean['request_id']}"
    if dataset is None:
        dataset = normalize_dataset({"name": name, "cases": [case], "docs": []})
        return save_dataset(saved, dataset), dataset
    if any(marker in (entry.get("tags") or []) for entry in dataset["cases"]):
        return save_dataset(saved, dataset), dataset
    if len(dataset["cases"]) >= MAX_STUDIO_CASES:
        raise ValueError(
            f"Dataset {name!r} already has {MAX_STUDIO_CASES} cases; remove one first"
        )
    dataset = add_case(
        dataset,
        query=case["query"],
        reference=case["reference"],
        tags=case["tags"],
    )
    dataset = normalize_dataset(dataset)
    return save_dataset(saved, dataset), dataset


def export_annotations_json(
    annotations: Iterable[Mapping[str, Any]], generated_at: Optional[str] = None
) -> str:
    """Redacted, deterministic JSON export of the feedback log."""
    rows = annotation_rows(annotations)
    payload = {
        "schema": EXPORT_SCHEMA,
        "generated_at": generated_at
        or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "count": len(rows),
        "redacted": True,
        "annotations": rows,
    }
    return json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=True)


def _csv_safe(value: Any) -> str:
    text = "" if value is None else str(value)
    if text and text[0] in ("=", "+", "-", "@", "\t", "\r", "\n"):
        return "'" + text
    return text


def export_annotations_csv(annotations: Iterable[Mapping[str, Any]]) -> str:
    """Redacted CSV export (formula-injection safe)."""
    rows = annotation_rows(annotations)
    fields = [
        "request_id",
        "flagged",
        "reason",
        "note",
        "promoted",
        "failure_type",
        "query",
        "tenant",
        "user",
        "created_at",
    ]
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({field: _csv_safe(row.get(field)) for field in fields})
    return buffer.getvalue()


def export_filename(extension: str = "json") -> str:
    suffix = "md" if str(extension).lower() in ("md", "markdown") else "json"
    if str(extension).lower() == "csv":
        suffix = "csv"
    return f"genai-feedback.{suffix}"


def promoted_dataset_name() -> str:
    """Default dataset target shown in the console and docs."""
    return DEFAULT_DATASET_NAME


def new_feedback_dataset() -> Dict[str, Any]:
    """A blank dataset shell used by tests and the console fallback."""
    return new_dataset(DEFAULT_DATASET_NAME)
