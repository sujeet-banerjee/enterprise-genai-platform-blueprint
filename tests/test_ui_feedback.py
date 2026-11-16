"""Tests for UX15 (#158): collaboration and feedback annotations."""

import ast
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from ui.evidence import build_evidence_pack, evidence_pack_markdown
from ui.feedback import (
    EXPORT_SCHEMA,
    annotation_rows,
    export_annotations_csv,
    export_annotations_json,
    export_filename,
    filter_annotations,
    find_annotation,
    new_annotation,
    normalize_annotations,
    promote_to_dataset,
    promoted_dataset_name,
    reason_summary,
    remove_annotation,
    set_promoted,
    upsert_annotation,
)
from ui.workspace import (
    build_share_url,
    empty_workspace,
    export_workspace,
    import_workspace,
    normalize_workspace,
    workspace_from_query_params,
)

REPO_BASE = Path(__file__).resolve().parents[1]


def test_new_and_upsert_annotation_preserves_created_at_and_redacts_secret():
    first = new_annotation(
        "req-1",
        query="What is RAG?",
        reason="incorrect",
        note="api_key=sk-secretvalue12345",
        created_at="2026-01-01T00:00:00+00:00",
    )
    assert first["request_id"] == "req-1"
    assert first["flag"] is True
    assert "sk-secretvalue12345" not in first["note"]
    assert "[REDACTED]" in first["note"]

    updated = new_annotation(
        "req-1",
        query="What is RAG?",
        reason="unsafe",
        note="needs review",
        created_at="2026-01-01T00:00:00+00:00",
    )
    merged = upsert_annotation([first], updated)
    assert len(merged) == 1
    assert merged[0]["reason"] == "unsafe"
    assert merged[0]["created_at"] == "2026-01-01T00:00:00+00:00"


def test_filter_annotations_and_reason_summary():
    items = normalize_annotations(
        [
            {"request_id": "a", "reason": "incorrect", "note": "bad answer", "flag": True},
            {
                "request_id": "b",
                "reason": "unsafe",
                "note": "unsafe",
                "flag": True,
                "promoted": True,
            },
        ]
    )
    assert [item["request_id"] for item in filter_annotations(items, reason="unsafe")] == ["b"]
    assert [item["request_id"] for item in filter_annotations(items, promoted="no")] == ["a"]
    assert [item["request_id"] for item in filter_annotations(items, search="bad")] == ["a"]

    summary = reason_summary(items)
    assert summary["total"] == 2
    assert summary["flagged"] == 2
    assert summary["promoted"] == 1
    assert summary["by_reason"]["incorrect"] == 1


def test_promote_to_dataset_creates_and_appends_review_dataset():
    annotation = new_annotation("req-9", query="Explain retrieval", reason="incorrect")
    saved, dataset = promote_to_dataset([], annotation)
    assert len(saved) == 1
    assert dataset["name"] == promoted_dataset_name()
    assert dataset["cases"][0]["query"] == "Explain retrieval"
    assert "request:req-9" in dataset["cases"][0]["tags"]

    saved, dataset = promote_to_dataset(
        saved, new_annotation("req-10", query="Explain reranking", reason="incorrect")
    )
    assert len(saved) == 1
    assert len(dataset["cases"]) == 2
    assert find_annotation(set_promoted([annotation], "req-9"), "req-9")["promoted"] is True


def test_feedback_exports_are_redacted_and_remove_annotation():
    annotations = [
        new_annotation("req-2", query="q", reason="unsafe", note="token sk-abc123SECRET")
    ]
    js = export_annotations_json(annotations)
    csv = export_annotations_csv(annotations)
    assert "sk-abc123SECRET" not in js
    assert "sk-abc123SECRET" not in csv
    assert "[REDACTED]" in js
    assert EXPORT_SCHEMA in js
    assert export_filename("json").endswith(".json")
    assert export_filename("csv").endswith(".csv")

    rows = annotation_rows(annotations)
    assert rows[0]["request_id"] == "req-2"
    assert remove_annotation(annotations, "req-2") == []


def test_workspace_round_trip_and_share_link_privacy_for_feedback():
    workspace = empty_workspace()
    workspace["feedback"] = {
        "reason": "incorrect",
        "promoted": "no",
        "search": "needle",
        "annotations": [
            {
                "request_id": "req-7",
                "query": "Why did this fail?",
                "reason": "incorrect",
                "flag": True,
                "promoted": False,
                "note": "reviewer note with sk-private-token-value",
            }
        ],
    }
    normalized = normalize_workspace(workspace)
    assert normalized["feedback"]["annotations"][0]["request_id"] == "req-7"
    assert "sk-private-token-value" not in normalized["feedback"]["annotations"][0]["note"]

    exported = export_workspace(normalized)
    imported = import_workspace(exported)
    assert imported["feedback"]["annotations"][0]["note"] == normalized["feedback"]["annotations"][0]["note"]
    assert imported["feedback"]["annotations"][0]["request_id"] == "req-7"

    url = build_share_url("http://localhost:8501", normalized)
    assert "sk-private-token-value" not in url
    assert "reviewer note" not in url
    params = {k: v[0] for k, v in parse_qs(urlsplit(url).query).items()}
    restored = workspace_from_query_params(params)
    if restored["feedback"]["annotations"]:
        assert restored["feedback"]["annotations"][0]["request_id"] == "req-7"
        assert restored["feedback"]["annotations"][0]["note"] == ""


def test_evidence_pack_includes_redacted_review_feedback():
    annotation = new_annotation(
        "req-3",
        query="secret question sk-verysecretvalue123",
        reason="incorrect",
        note="contains sk-verysecretvalue123",
    )
    pack = build_evidence_pack(
        request_id="req-3",
        trace={"request_id": "req-3", "status": "success"},
        annotation=annotation,
    )
    md = evidence_pack_markdown(pack)
    assert "Review / feedback" in md
    assert pack["review"]["request_id"] == "req-3"
    assert "sk-verysecretvalue123" not in md
    assert "sk-verysecretvalue123" not in export_annotations_json([annotation])


def test_app_and_tour_wire_feedback_screen():
    app_src = (REPO_BASE / "ui" / "app.py").read_text(encoding="utf-8")
    tour_src = (REPO_BASE / "ui" / "tour.py").read_text(encoding="utf-8")
    nav_src = (REPO_BASE / "ui" / "navigation.py").read_text(encoding="utf-8")
    assert "screen_feedback" in app_src
    assert '"Feedback": screen_feedback' in app_src
    assert "_render_feedback_controls" in app_src
    assert "Feedback" in tour_src
    assert "Feedback" in nav_src
    tree = ast.parse(app_src)
    funcs = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    assert "screen_feedback" in funcs
