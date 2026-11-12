"""Dataset Studio authoring helpers (issue #153, UX10).

Pure, Streamlit-free helpers for authoring evaluation datasets without raw
JSON: a structured case editor (query / reference / tags), a document editor,
inline validation, JSON import/export with round-trip fidelity, and a bounded
saved-dataset store that survives reloads through the UX8 workspace layer
(``ui.workspace``). HTTP-only and backend-free for testability.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from ui.evaluation import EvaluationCase

MAX_STUDIO_CASES = 100
MAX_STUDIO_DOCS = 100
MAX_SAVED_DATASETS = 10
MAX_NAME_CHARS = 80
MAX_TEXT_CHARS = 8000
MAX_TAG_CHARS = 40
MAX_TAGS_PER_CASE = 10
DEFAULT_DATASET_NAME = "Untitled dataset"
DUPLICATE_SUFFIX = "copy"

# Same policy as ui.workspace / ui.approvals: never persist or echo
# secret-looking values in names, cases, documents or exports.
_SECRET_VALUE_RE = re.compile(
    r"(sk-[A-Za-z0-9_\-]{8,}|Bearer\s+[A-Za-z0-9._\-]{8,}|env:[A-Z0-9_]+|\$\{[A-Z0-9_]+\})",
    re.IGNORECASE,
)


def _clean_text(value: Any, limit: int) -> str:
    if not isinstance(value, str):
        if value is None:
            return ""
        value = str(value)
    text = value.strip()
    text = _SECRET_VALUE_RE.sub("[REDACTED]", text)
    if len(text) > limit:
        text = text[:limit]
    return text


def _clean_tags(value: Any) -> List[str]:
    if isinstance(value, str):
        value = [part for part in value.split(",")]
    if not isinstance(value, (list, tuple)):
        return []
    tags: List[str] = []
    for tag in value:
        clean = _clean_text(tag, MAX_TAG_CHARS)
        if clean and clean not in tags:
            tags.append(clean)
        if len(tags) >= MAX_TAGS_PER_CASE:
            break
    return tags


def new_dataset(name: str = DEFAULT_DATASET_NAME) -> Dict[str, Any]:
    """A fresh studio dataset with one empty case so the editor is never blank."""
    return {
        "name": _clean_text(name, MAX_NAME_CHARS) or DEFAULT_DATASET_NAME,
        "cases": [{"query": "", "reference": "", "tags": []}],
        "docs": [],
    }


def normalize_dataset(value: Any) -> Dict[str, Any]:
    """Sanitize and bound an untrusted dataset mapping (or return a new one)."""
    data = value if isinstance(value, Mapping) else {}
    raw_cases = data.get("cases")
    if not isinstance(raw_cases, list):
        raw_cases = []
    cases = [
        {
            "query": _clean_text(case.get("query"), MAX_TEXT_CHARS),
            "reference": _clean_text(case.get("reference"), MAX_TEXT_CHARS),
            "tags": _clean_tags(case.get("tags")),
        }
        for case in raw_cases[:MAX_STUDIO_CASES]
        if isinstance(case, Mapping)
    ]
    if not cases:
        cases = new_dataset()["cases"]
    raw_docs = data.get("docs")
    if not isinstance(raw_docs, list):
        raw_docs = []
    docs = [
        {
            "content": _clean_text(doc.get("content"), MAX_TEXT_CHARS),
            "title": _clean_text(doc.get("title"), MAX_NAME_CHARS),
        }
        for doc in raw_docs[:MAX_STUDIO_DOCS]
        if isinstance(doc, Mapping)
    ]
    return {
        "name": _clean_text(data.get("name"), MAX_NAME_CHARS) or DEFAULT_DATASET_NAME,
        "cases": cases,
        "docs": docs,
    }


def validate_dataset(dataset: Mapping[str, Any]) -> Tuple[List[str], List[str]]:
    """Return (errors, warnings) with actionable, case-numbered messages.

    Errors block starting a background job; warnings do not. Invalid cases are
    never dropped from the editor — they stay visible with their errors.
    """
    errors: List[str] = []
    warnings: List[str] = []
    cases = dataset.get("cases") or []
    if not cases:
        errors.append("Dataset has no cases. Add at least one case with a query.")
    seen: Dict[str, int] = {}
    for index, case in enumerate(cases, start=1):
        query = str(case.get("query") or "").strip()
        if not query:
            errors.append(
                f"Case {index} is missing a query — fill in the query or remove the row."
            )
        elif len(query) > MAX_TEXT_CHARS:
            errors.append(f"Case {index} query exceeds {MAX_TEXT_CHARS} characters.")
        reference = str(case.get("reference") or "").strip()
        if reference and len(reference) > MAX_TEXT_CHARS:
            errors.append(f"Case {index} reference exceeds {MAX_TEXT_CHARS} characters.")
        if query and query in seen:
            warnings.append(
                f"Case {index} duplicates the query of case {seen[query]} — "
                "intentional repeats are allowed but inflate averages."
            )
        elif query:
            seen[query] = index
    docs = dataset.get("docs") or []
    for index, doc in enumerate(docs, start=1):
        content = str(doc.get("content") or "").strip()
        if not content:
            warnings.append(
                f"Document {index} has no content — empty documents never rank."
            )
    if len(cases) > MAX_STUDIO_CASES:
        errors.append(
            f"Dataset has {len(cases)} cases; only {MAX_STUDIO_CASES} are kept."
        )
    if len(docs) > MAX_STUDIO_DOCS:
        errors.append(
            f"Dataset has {len(docs)} documents; only {MAX_STUDIO_DOCS} are kept."
        )
    return errors, warnings


# -- case editor -------------------------------------------------------------


def add_case(dataset: Dict[str, Any], query: str = "", reference: str = "", tags: Sequence[str] = ()) -> Dict[str, Any]:
    cases = dataset.get("cases")
    if not isinstance(cases, list):
        cases = []
        dataset["cases"] = cases
    cases.append(
        {
            "query": _clean_text(query, MAX_TEXT_CHARS),
            "reference": _clean_text(reference, MAX_TEXT_CHARS),
            "tags": _clean_tags(list(tags)),
        }
    )
    return dataset


def update_case(dataset: Dict[str, Any], index: int, **fields: Any) -> Dict[str, Any]:
    cases = dataset.get("cases") or []
    if not 0 <= index < len(cases):
        return dataset
    case = cases[index]
    if "query" in fields:
        case["query"] = _clean_text(fields["query"], MAX_TEXT_CHARS)
    if "reference" in fields:
        case["reference"] = _clean_text(fields["reference"], MAX_TEXT_CHARS)
    if "tags" in fields:
        case["tags"] = _clean_tags(fields["tags"])
    return dataset


def remove_case(dataset: Dict[str, Any], index: int) -> Dict[str, Any]:
    cases = dataset.get("cases") or []
    if 0 <= index < len(cases):
        cases.pop(index)
    return dataset


def move_case(dataset: Dict[str, Any], index: int, delta: int) -> bool:
    """Move a case up (-1) or down (+1); returns True when the move happened."""
    cases = dataset.get("cases") or []
    target = index + delta
    if not 0 <= index < len(cases) or not 0 <= target < len(cases):
        return False
    cases[index], cases[target] = cases[target], cases[index]
    return True


def case_rows(dataset: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """Rows for ``st.data_editor``; tags are joined for single-cell editing."""
    rows = []
    for case in dataset.get("cases") or []:
        rows.append(
            {
                "query": str(case.get("query") or ""),
                "reference": str(case.get("reference") or ""),
                "tags": ", ".join(str(tag) for tag in case.get("tags") or []),
            }
        )
    return rows


def apply_case_rows(dataset: Dict[str, Any], rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """Replace all cases from edited table rows (add/remove/reorder in one)."""
    cases: List[Dict[str, Any]] = []
    for row in rows[:MAX_STUDIO_CASES]:
        mapping = row if isinstance(row, Mapping) else {}
        cases.append(
            {
                "query": _clean_text(mapping.get("query"), MAX_TEXT_CHARS),
                "reference": _clean_text(mapping.get("reference"), MAX_TEXT_CHARS),
                "tags": _clean_tags(mapping.get("tags")),
            }
        )
    if not cases:
        cases = new_dataset()["cases"]
    dataset["cases"] = cases
    return dataset


# -- document editor ---------------------------------------------------------


def add_doc(dataset: Dict[str, Any], content: str = "", title: str = "") -> Dict[str, Any]:
    docs = dataset.get("docs")
    if not isinstance(docs, list):
        docs = []
        dataset["docs"] = docs
    docs.append(
        {
            "content": _clean_text(content, MAX_TEXT_CHARS),
            "title": _clean_text(title, MAX_NAME_CHARS),
        }
    )
    return dataset


def update_doc(dataset: Dict[str, Any], index: int, **fields: Any) -> Dict[str, Any]:
    docs = dataset.get("docs") or []
    if not 0 <= index < len(docs):
        return dataset
    doc = docs[index]
    if "content" in fields:
        doc["content"] = _clean_text(fields["content"], MAX_TEXT_CHARS)
    if "title" in fields:
        doc["title"] = _clean_text(fields["title"], MAX_NAME_CHARS)
    return dataset


def remove_doc(dataset: Dict[str, Any], index: int) -> Dict[str, Any]:
    docs = dataset.get("docs") or []
    if 0 <= index < len(docs):
        docs.pop(index)
    return dataset


def doc_rows(dataset: Mapping[str, Any]) -> List[Dict[str, Any]]:
    rows = []
    for index, doc in enumerate(dataset.get("docs") or [], start=1):
        content = str(doc.get("content") or "")
        rows.append(
            {
                "doc": index,
                "title": str(doc.get("title") or ""),
                "content": content,
                "chars": len(content),
            }
        )
    return rows


def apply_doc_rows(dataset: Dict[str, Any], rows: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    docs: List[Dict[str, Any]] = []
    for row in rows[:MAX_STUDIO_DOCS]:
        mapping = row if isinstance(row, Mapping) else {}
        docs.append(
            {
                "content": _clean_text(mapping.get("content"), MAX_TEXT_CHARS),
                "title": _clean_text(mapping.get("title"), MAX_NAME_CHARS),
            }
        )
    dataset["docs"] = docs
    return dataset


# -- import / export ---------------------------------------------------------


def import_guidance() -> str:
    return (
        "Paste either a **bare case list** (`[{\"query\": ..., \"reference\": ...}]`) "
        "or a **benchmark-shaped** payload (`{\"docs\": [{\"content\": ...}], "
        "\"cases\": [{\"query\": ..., \"reference\": ..., \"tags\": [...]}]}`). "
        "The studio export uses the benchmark shape so queries, references, tags "
        "and documents round-trip exactly. Invalid rows are kept with inline "
        "errors — nothing is dropped silently."
    )


def parse_import(text: str) -> Tuple[Dict[str, Any], List[str]]:
    """Parse pasted JSON into a studio dataset.

    Returns ``(dataset, errors)``. Invalid rows are preserved as empty cases so
    the user can fix them in the editor; the errors list explains each one.
    A JSON syntax error returns an empty dataset plus the error.
    """
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        return new_dataset(), [f"Invalid JSON: {exc.msg} (line {exc.lineno})"]

    errors: List[str] = []
    if isinstance(payload, Mapping):
        docs_payload = payload.get("docs")
        raw_cases = payload.get("cases")
        name = payload.get("name")
    elif isinstance(payload, list):
        docs_payload = None
        raw_cases = payload
        name = None
    else:
        return new_dataset(), [
            "Dataset must be a JSON list of cases or an object with `docs` and `cases`."
        ]

    dataset = new_dataset(_clean_text(name, MAX_NAME_CHARS) if name else DEFAULT_DATASET_NAME)
    dataset["cases"] = []
    dataset["docs"] = []

    if isinstance(docs_payload, list):
        for raw in docs_payload[:MAX_STUDIO_DOCS]:
            if not isinstance(raw, Mapping):
                errors.append("A document entry was not a JSON object and was skipped.")
                continue
            add_doc(dataset, content=str(raw.get("content") or ""), title=str(raw.get("title") or ""))
    elif docs_payload is not None:
        errors.append("`docs` must be a JSON list; documents were not imported.")

    if not isinstance(raw_cases, list):
        errors.append("Dataset must contain a `cases` list.")
    else:
        for index, raw in enumerate(raw_cases[:MAX_STUDIO_CASES], start=1):
            if not isinstance(raw, Mapping):
                errors.append(
                    f"Case {index} is not a JSON object — kept as an empty case; "
                    "fill the query or remove the row."
                )
                add_case(dataset)
                continue
            query = raw.get("query") or raw.get("question") or ""
            if not str(query).strip():
                errors.append(
                    f"Case {index} is missing a `query` — kept as an empty case so "
                    "nothing is dropped; fix it in the editor."
                )
            add_case(
                dataset,
                query=str(query),
                reference=str(raw.get("reference") or raw.get("ground_truth") or raw.get("expected_answer") or ""),
                tags=list(raw.get("tags") or []),
            )
    if len(raw_cases or []) > MAX_STUDIO_CASES:
        errors.append(
            f"Dataset has {len(raw_cases)} cases; only the first {MAX_STUDIO_CASES} were imported."
        )
    if not dataset["cases"]:
        add_case(dataset)
    return dataset, errors


def export_dataset(dataset: Mapping[str, Any], benchmark_shaped: bool = True) -> str:
    """Serialize a dataset as JSON with round-trip fidelity.

    Benchmark shape keeps docs and case metadata; the bare shape is a plain
    case list (no documents). Both are re-importable via :func:`parse_import`.
    """
    clean = normalize_dataset(dataset)
    cases = [
        {
            "query": case["query"],
            "reference": case["reference"],
            "tags": list(case["tags"]),
        }
        for case in clean["cases"]
    ]
    if not benchmark_shaped:
        return json.dumps(cases, indent=2)
    return json.dumps(
        {
            "name": clean["name"],
            "docs": [{"title": doc["title"], "content": doc["content"]} for doc in clean["docs"]],
            "cases": cases,
        },
        indent=2,
    )


def to_evaluation_cases(dataset: Mapping[str, Any]) -> List[EvaluationCase]:
    """Convert studio cases into the EvaluationCase objects jobs consume."""
    cases: List[EvaluationCase] = []
    for case in normalize_dataset(dataset)["cases"]:
        cases.append(
            EvaluationCase(
                query=case["query"],
                reference=case["reference"],
                tags=tuple(case["tags"]),
            )
        )
    return cases


# -- saved dataset store -----------------------------------------------------


def normalize_saved_datasets(value: Any) -> List[Dict[str, Any]]:
    """Bounded, sanitized saved-dataset list for the UX8 workspace layer."""
    if not isinstance(value, list):
        return []
    saved: List[Dict[str, Any]] = []
    for item in value[:MAX_SAVED_DATASETS]:
        if isinstance(item, Mapping):
            saved.append(normalize_dataset(item))
    return saved


def find_dataset(saved: Sequence[Mapping[str, Any]], name: str) -> Optional[Dict[str, Any]]:
    target = _clean_text(name, MAX_NAME_CHARS)
    for dataset in saved:
        if dataset.get("name") == target:
            return normalize_dataset(dataset)
    return None


def save_dataset(
    saved: Sequence[Mapping[str, Any]], dataset: Mapping[str, Any]
) -> List[Dict[str, Any]]:
    """Upsert a dataset by name, keeping at most MAX_SAVED_DATASETS entries."""
    clean = normalize_dataset(dataset)
    out = [dict(item) for item in saved]
    for index, item in enumerate(out):
        if item.get("name") == clean["name"]:
            out[index] = clean
            return out
    out.append(clean)
    if len(out) > MAX_SAVED_DATASETS:
        out = out[-MAX_SAVED_DATASETS:]
    return out


def delete_dataset(saved: Sequence[Mapping[str, Any]], name: str) -> List[Dict[str, Any]]:
    target = _clean_text(name, MAX_NAME_CHARS)
    return [dict(item) for item in saved if item.get("name") != target]


def duplicate_dataset(
    dataset: Mapping[str, Any], suffix: str = DUPLICATE_SUFFIX, saved: Sequence[str] = ()
) -> Dict[str, Any]:
    """A deep copy with a unique, non-colliding name."""
    clean = normalize_dataset(dataset)
    names = {str(item) for item in saved}
    names.add(clean["name"])
    candidate = f"{clean['name']} ({suffix})"
    counter = 2
    while candidate in names:
        candidate = f"{clean['name']} ({suffix} {counter})"
        counter += 1
    clean["name"] = candidate
    return clean
