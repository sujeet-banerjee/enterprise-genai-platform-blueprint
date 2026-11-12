"""Tests for UX10 (#153): Dataset Studio authoring.

The studio contract lives in ``ui/dataset_studio.py`` and is deliberately free
of Streamlit/backend imports, so these tests exercise real authoring, validation,
import/export round-trips and the UX8 workspace persistence contract. Structural
tests cover the Evaluation-screen wiring without importing Streamlit.
"""

import ast
import json
import random
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from ui.dataset_studio import (
    MAX_SAVED_DATASETS,
    MAX_STUDIO_CASES,
    MAX_STUDIO_DOCS,
    add_case,
    add_doc,
    apply_case_rows,
    apply_doc_rows,
    case_rows,
    delete_dataset,
    doc_rows,
    duplicate_dataset,
    export_dataset,
    find_dataset,
    import_guidance,
    move_case,
    new_dataset,
    normalize_dataset,
    normalize_saved_datasets,
    parse_import,
    remove_case,
    remove_doc,
    save_dataset,
    to_evaluation_cases,
    update_case,
    update_doc,
    validate_dataset,
)
from ui.evaluation import EvaluationCase, dataset_preview_rows
from ui.navigation import ALL_CAPABILITIES
from ui.workspace import (
    MAX_URL_CHARS,
    apply_workspace,
    build_share_url,
    export_workspace,
    import_workspace,
    normalize_workspace,
    reset_workspace_state,
    workspace_from_query_params,
    workspace_from_session,
)

REPO_BASE = Path(__file__).resolve().parents[1]
STUDIO_PATH = REPO_BASE / "ui" / "dataset_studio.py"
APP_PATH = REPO_BASE / "ui" / "app.py"
WORKSPACE_PATH = REPO_BASE / "ui" / "workspace.py"
TOUR_PATH = REPO_BASE / "ui" / "tour.py"


def _noise(length, seed=153):
    rng = random.Random(seed)
    return "".join(rng.choice("0123456789abcdef") for _ in range(length))


def _valid_dataset(name="QA"):
    dataset = new_dataset(name)
    dataset["cases"] = []
    add_case(dataset, query="What is RAG?", reference="Retrieval augmented generation.")
    add_doc(dataset, content="RAG grounds a model on retrieved documents.", title="RAG basics")
    return dataset


# -- editor: cases -----------------------------------------------------------


def test_new_dataset_starts_with_one_empty_case_and_no_docs():
    dataset = new_dataset("Support")
    assert dataset["name"] == "Support"
    assert dataset["cases"] == [{"query": "", "reference": "", "tags": []}]
    assert dataset["docs"] == []


def test_add_update_and_remove_case():
    dataset = new_dataset()
    dataset["cases"] = []
    add_case(dataset, query="q1", reference="r1", tags=["a", "b"])
    add_case(dataset)
    assert len(dataset["cases"]) == 2

    update_case(dataset, 1, query="q2", reference="r2", tags="x, y, x")
    assert dataset["cases"][1] == {"query": "q2", "reference": "r2", "tags": ["x", "y"]}

    remove_case(dataset, 0)
    assert [case["query"] for case in dataset["cases"]] == ["q2"]
    remove_case(dataset, 9)  # out of range is a no-op
    assert len(dataset["cases"]) == 1


def test_move_case_reorders_and_respects_bounds():
    dataset = new_dataset()
    dataset["cases"] = []
    for query in ("a", "b", "c"):
        add_case(dataset, query=query)

    assert move_case(dataset, 2, -1) is True
    assert [case["query"] for case in dataset["cases"]] == ["a", "c", "b"]
    assert move_case(dataset, 0, -1) is False
    assert move_case(dataset, 2, 1) is False
    assert [case["query"] for case in dataset["cases"]] == ["a", "c", "b"]


def test_case_rows_join_tags_and_apply_replaces_order():
    dataset = _valid_dataset()
    add_case(dataset, query="Second?", tags=["t1", "t2"])
    rows = case_rows(dataset)
    assert rows[1]["tags"] == "t1, t2"

    reversed_rows = list(reversed(rows))
    apply_case_rows(dataset, reversed_rows)
    assert [case["query"] for case in dataset["cases"]] == ["Second?", "What is RAG?"]
    assert dataset["cases"][0]["tags"] == ["t1", "t2"]


def test_apply_case_rows_never_leaves_the_editor_empty():
    dataset = _valid_dataset()
    apply_case_rows(dataset, [])
    assert len(dataset["cases"]) == 1
    assert dataset["cases"][0]["query"] == ""


# -- editor: documents -------------------------------------------------------


def test_document_editor_crud_and_rows():
    dataset = new_dataset()
    add_doc(dataset, content="First doc", title="One")
    add_doc(dataset, content="Second doc")
    rows = doc_rows(dataset)
    assert rows[1] == {"doc": 2, "title": "", "content": "Second doc", "chars": 10}

    update_doc(dataset, 1, content="Second edited", title="Two")
    assert dataset["docs"][1] == {"content": "Second edited", "title": "Two"}

    remove_doc(dataset, 0)
    assert [doc["content"] for doc in dataset["docs"]] == ["Second edited"]

    apply_doc_rows(dataset, rows)
    assert len(dataset["docs"]) == 2
    assert dataset["docs"][1]["content"] == "Second doc"


# -- validation --------------------------------------------------------------


def test_validate_flags_missing_query_with_case_number():
    dataset = new_dataset()
    dataset["cases"] = [{"query": "", "reference": "", "tags": []}]
    errors, _ = validate_dataset(dataset)
    assert any("Case 1 is missing a query" in message for message in errors)


def test_validate_rejects_empty_dataset_and_accepts_clean_one():
    dataset = new_dataset()
    dataset["cases"] = []
    errors, _ = validate_dataset(dataset)
    assert errors and "no cases" in errors[0]

    errors, warnings = validate_dataset(_valid_dataset())
    assert errors == []
    assert warnings == []


def test_validate_warns_on_duplicate_queries_and_empty_documents():
    dataset = _valid_dataset()
    add_case(dataset, query="What is RAG?")
    add_doc(dataset, content="")
    errors, warnings = validate_dataset(dataset)
    assert errors == []
    assert any("duplicates the query of case 1" in message for message in warnings)
    assert any("Document 2 has no content" in message for message in warnings)


def test_normalize_bounds_input_and_scrubs_secrets():
    payload = {
        "name": "sk-abcdefgh12345678 dataset",
        "cases": [
            {"query": f"q{i} sk-abcdefgh12345678", "reference": "", "tags": ["x"]}
            for i in range(MAX_STUDIO_CASES + 5)
        ],
        "docs": [{"content": "env:OPENAI_API_KEY"} for _ in range(MAX_STUDIO_DOCS + 5)],
    }
    dataset = normalize_dataset(payload)
    assert len(dataset["cases"]) == MAX_STUDIO_CASES
    assert len(dataset["docs"]) == MAX_STUDIO_DOCS
    assert "sk-abcdefgh12345678" not in json.dumps(dataset)
    assert "env:OPENAI_API_KEY" not in json.dumps(dataset)
    assert "[REDACTED]" in dataset["name"]

    fallback = normalize_dataset({"cases": ["not a dict"]})
    assert len(fallback["cases"]) == 1 and fallback["cases"][0]["query"] == ""


# -- import / export ---------------------------------------------------------


def test_parse_import_reads_benchmark_shaped_payload():
    payload = json.dumps(
        {
            "name": "Bench",
            "docs": [{"title": "D1", "content": "Doc one"}, "not-a-dict"],
            "cases": [
                {"query": "Q1", "reference": "R1", "tags": ["a"]},
                {"question": "Q2", "ground_truth": "R2"},
            ],
        }
    )
    dataset, errors = parse_import(payload)
    assert dataset["name"] == "Bench"
    assert [case["query"] for case in dataset["cases"]] == ["Q1", "Q2"]
    assert dataset["cases"][1]["reference"] == "R2"
    assert len(dataset["docs"]) == 1
    assert any("document entry" in message for message in errors)


def test_parse_import_reads_bare_case_list():
    dataset, errors = parse_import('[{"query": "Only question"}]')
    assert errors == []
    assert dataset["cases"][0]["query"] == "Only question"
    assert dataset["docs"] == []
    assert dataset["name"]  # default name assigned


def test_parse_import_invalid_json_reports_instead_of_wiping_work():
    dataset, errors = parse_import("{")
    assert errors and errors[0].startswith("Invalid JSON")
    assert dataset["cases"] == [{"query": "", "reference": "", "tags": []}]

    dataset, errors = parse_import(json.dumps({"docs": [], "nope": 1}))
    assert errors and "cases" in errors[0]


def test_parse_import_keeps_invalid_rows_with_errors():
    payload = json.dumps(
        {"cases": [{"query": "Good"}, {"reference": "no query"}, "junk row"]}
    )
    dataset, errors = parse_import(payload)
    assert len(dataset["cases"]) == 3  # nothing silently dropped
    assert dataset["cases"][0]["query"] == "Good"
    assert dataset["cases"][1]["query"] == ""
    assert dataset["cases"][2]["query"] == ""
    assert any("Case 2 is missing a `query`" in message for message in errors)
    assert any("Case 3 is not a JSON object" in message for message in errors)


def test_parse_import_caps_cases_at_studio_limit():
    payload = json.dumps({"cases": [{"query": f"q{i}"} for i in range(MAX_STUDIO_CASES + 10)]})
    dataset, errors = parse_import(payload)
    assert len(dataset["cases"]) == MAX_STUDIO_CASES
    assert any("only the first" in message for message in errors)


def test_export_import_round_trip_preserves_everything():
    dataset = _valid_dataset("Round trip")
    add_case(dataset, query="Second?", reference="Second ref.", tags=["t1", "t2"])
    add_doc(dataset, content="Second document.", title="D2")

    exported = export_dataset(dataset)
    restored, errors = parse_import(exported)

    assert errors == []
    assert restored["name"] == "Round trip"
    assert restored["cases"] == dataset["cases"]
    assert restored["docs"] == dataset["docs"]
    assert [case.reference for case in to_evaluation_cases(restored)] == [
        "Retrieval augmented generation.",
        "Second ref.",
    ]


def test_export_bare_shape_is_case_list_and_scrubs_secrets():
    dataset = _valid_dataset()
    add_case(dataset, query="leak sk-abcdefgh12345678", reference="r")

    bare = json.loads(export_dataset(dataset, benchmark_shaped=False))
    assert isinstance(bare, list)
    assert "docs" not in bare[0]
    assert "sk-abcdefgh12345678" not in export_dataset(dataset)

    restored, errors = parse_import(json.dumps(bare))
    assert errors == []
    assert restored["docs"] == []  # bare shape carries no documents
    assert "sk-abcdefgh12345678" not in json.dumps(restored)


def test_previews_do_not_expose_secrets():
    dataset = _valid_dataset()
    add_case(dataset, query="token sk-abcdefgh12345678", reference="Bearer abcdefgh12345678")
    preview = dataset_preview_rows(to_evaluation_cases(dataset))
    assert "sk-abcdefgh12345678" not in json.dumps(preview)
    assert "Bearer abcdefgh12345678" not in json.dumps(preview)
    assert "queries, references" in import_guidance()


# -- saved dataset store -----------------------------------------------------


def test_duplicate_dataset_names_are_unique_and_independent():
    dataset = _valid_dataset("Base")
    duplicate = duplicate_dataset(dataset, saved=["Base", "Base (copy)"])
    assert duplicate["name"] == "Base (copy 2)"

    duplicate["cases"][0]["query"] = "changed?"
    assert dataset["cases"][0]["query"] == "What is RAG?"


def test_save_dataset_upserts_and_evicts_oldest():
    saved = []
    for index in range(MAX_SAVED_DATASETS + 2):
        saved = save_dataset(saved, _valid_dataset(f"ds-{index}"))
    assert len(saved) == MAX_SAVED_DATASETS
    assert saved[0]["name"] == "ds-2"

    updated = _valid_dataset("ds-5")
    add_case(updated, query="added?")
    saved = save_dataset(saved, updated)
    matches = [item for item in saved if item["name"] == "ds-5"]
    assert len(matches) == 1
    assert len(matches[0]["cases"]) == 2


def test_delete_and_find_saved_dataset():
    saved = [save_dataset([], _valid_dataset("one"))][0]
    saved = save_dataset(saved, _valid_dataset("two"))
    assert find_dataset(saved, "two")["name"] == "two"
    assert find_dataset(saved, "missing") is None
    assert [item["name"] for item in delete_dataset(saved, "one")] == ["two"]


def test_normalize_saved_datasets_is_bounded_and_sanitized():
    raw = [_valid_dataset(f"ds-{index}") for index in range(MAX_SAVED_DATASETS + 3)]
    raw.append("junk")
    saved = normalize_saved_datasets(raw)
    assert len(saved) == MAX_SAVED_DATASETS
    assert all(isinstance(item, dict) and item["name"] for item in saved)
    assert normalize_saved_datasets("nope") == []


def test_to_evaluation_cases_maps_query_reference_and_tags():
    dataset = _valid_dataset()
    add_case(dataset, query="tagged?", tags=["a", "b"])
    cases = to_evaluation_cases(dataset)
    assert all(isinstance(case, EvaluationCase) for case in cases)
    assert cases[1].query == "tagged?"
    assert cases[1].tags == ("a", "b")


def test_authoring_twenty_cases_and_ten_docs_without_raw_json():
    dataset = new_dataset("Support QA")
    dataset["cases"] = []
    for index in range(20):
        add_case(
            dataset,
            query=f"Question {index}?",
            reference=f"Answer {index}.",
            tags=["support", f"group-{index % 2}"],
        )
    for index in range(10):
        add_doc(dataset, content=f"Document {index} body.", title=f"Doc {index}")

    errors, _ = validate_dataset(dataset)
    assert errors == []

    restored, import_errors = parse_import(export_dataset(dataset))
    assert import_errors == []
    assert len(restored["cases"]) == 20
    assert len(restored["docs"]) == 10
    assert restored["cases"][19]["tags"] == ["support", "group-1"]


# -- workspace persistence (UX8) ---------------------------------------------


def test_workspace_persists_saved_datasets_round_trip():
    dataset = _valid_dataset("Persisted")
    workspace = workspace_from_session({"saved_datasets": [dataset], "active_screen": "Evaluation"})
    assert workspace["evaluation"]["datasets"][0]["name"] == "Persisted"

    imported = import_workspace(export_workspace(workspace))
    state = {}
    reset_workspace_state(state)
    access = {"ok": True, "enabled": True, "role": "admin", "capabilities": ALL_CAPABILITIES}
    apply_workspace(imported, state, access, ["Evaluation"])
    assert state["saved_datasets"][0]["name"] == "Persisted"
    assert state["saved_datasets"][0]["cases"][0]["query"] == "What is RAG?"


def test_workspace_source_accepts_dataset_studio_and_rejects_garbage():
    accepted = normalize_workspace(
        {"evaluation": {"dataset_source": "Dataset Studio"}}
    )
    assert accepted["evaluation"]["dataset_source"] == "Dataset Studio"

    rejected = normalize_workspace({"evaluation": {"dataset_source": "hand-written"}})
    assert rejected["evaluation"]["dataset_source"] == "Built-in benchmark"

    from_params = workspace_from_query_params({"eval_dataset_source": "Dataset Studio"})
    assert from_params["evaluation"]["dataset_source"] == "Dataset Studio"


def test_workspace_url_share_strips_bulk_datasets():
    dataset = new_dataset("Huge")
    dataset["cases"] = [
        {"query": _noise(8000, seed=index), "reference": _noise(8000, seed=100 + index), "tags": []}
        for index in range(6)
    ]
    dataset["docs"] = [
        {"content": _noise(8000, seed=200 + index), "title": ""} for index in range(3)
    ]
    workspace = workspace_from_session({"saved_datasets": [dataset]})
    assert workspace["evaluation"]["datasets"]

    url = build_share_url("http://localhost:8501", workspace)
    assert len(url) <= MAX_URL_CHARS
    params = parse_qs(urlsplit(url).query)
    restored = workspace_from_query_params(
        {key: values[0] for key, values in params.items()}
    )
    assert restored["evaluation"]["datasets"] == []


# -- wiring ------------------------------------------------------------------


def test_studio_module_is_streamlit_and_backend_free():
    tree = ast.parse(STUDIO_PATH.read_text(encoding="utf-8"))
    forbidden = ("streamlit", "app", "core", "requests")
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] not in forbidden, alias.name
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            assert root not in forbidden, node.module


def test_app_wires_dataset_studio_into_evaluation_screen():
    source = APP_PATH.read_text(encoding="utf-8")
    assert '"Dataset Studio"' in source
    assert "def _render_dataset_studio()" in source
    assert "_render_dataset_studio()" in source
    assert "studio_dataset" in source
    assert "studio_cases_editor_" in source
    assert "studio_docs_editor_" in source
    assert "studio_export" in source
    for token in ("apply_case_rows(", "apply_doc_rows(", "validate_dataset(", "export_dataset(", "parse_import("):
        assert token in source
    assert "saved_datasets" in source

    workspace_source = WORKSPACE_PATH.read_text(encoding="utf-8")
    assert "normalize_saved_datasets" in workspace_source
    assert '"datasets": state.get("saved_datasets")' in workspace_source
    assert 'state["saved_datasets"] = copy.deepcopy(evaluation["datasets"])' in workspace_source


def test_tour_mentions_dataset_studio():
    source = TOUR_PATH.read_text(encoding="utf-8")
    assert "Dataset Studio" in source
