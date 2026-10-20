"""Streamlit console entrypoint for the Enterprise GenAI RAG platform (#40).

Run it against a live backend::

    streamlit run ui/app.py -- --api-base http://localhost:8000

The console is an HTTP-only client of the public API and demonstrates that the
API surface is sufficient for a real front-end. See ``docs/ux-and-api.md`` §6.
"""

import argparse
import sys
from typing import Any, Dict

import streamlit as st

from ui.client import ApiClient
from ui.common import api_base_url, latency_rows, metric_rows, require_ok
from ui.tour import render_help_expander, render_tour, start_tour

st.set_page_config(page_title="Enterprise GenAI RAG Console", layout="wide")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--api-base", default=None)
    args, _ = parser.parse_known_args(sys.argv[1:])
    return args


def client() -> ApiClient:
    return ApiClient(
        base_url=api_base_url(),
        api_key=st.session_state.get("api_key", ""),
    )


def _bootstrap() -> None:
    args = _parse_args()
    if "api_base_url" not in st.session_state:
        st.session_state.api_base_url = args.api_base or "http://localhost:8000"
    if "api_key" not in st.session_state:
        st.session_state.api_key = ""
    if "last_request_id" not in st.session_state:
        st.session_state.last_request_id = ""
    if "tour_state" not in st.session_state:
        st.session_state.tour_state = "idle"
    if "tour_step" not in st.session_state:
        st.session_state.tour_step = 0


def _failure_taxonomy(result) -> None:
    if result.failure_type:
        st.warning(
            f"Failure taxonomy: `{result.failure_type}` | tags: "
            f"{', '.join(result.failure_tags) or '-'}"
        )


# --------------------------------------------------------------------------- #
# Screens
# --------------------------------------------------------------------------- #


def screen_overview() -> None:
    st.header("Overview / Health")
    api = client()

    health = api.health()
    ready = api.ready()
    left, right = st.columns(2)
    with left:
        if require_ok(health):
            st.success(f"Health: {health.data.get('status')}")
    with right:
        if ready.ok:
            st.success(f"Ready: {ready.data.get('status')} (revision {ready.data.get('config_revision')})")
            st.json(ready.data.get("components", {}))
        else:
            st.info("Service is not ready yet.")

    col1, col2, col3, col4 = st.columns(4)
    for col, (label, call) in zip(
        (col1, col2, col3, col4),
        (
            ("Active model", api.models),
            ("Retriever", api.retrievers),
            ("Reranker", api.rerankers),
            ("Evaluator", api.evaluators),
        ),
    ):
        with col:
            result = call()
            if result.ok:
                st.metric(label, _active_label(label, result.data))
            else:
                st.metric(label, "unavailable")


def _active_label(label: str, data: Dict[str, Any]) -> str:
    if label == "Active model":
        return str(data.get("active", "-"))
    if label == "Retriever":
        return str(data.get("default_retriever", "-"))
    if label == "Reranker":
        return str(data.get("active_reranker") or ("disabled" if not data.get("enabled", True) else "-"))
    return str(data.get("active_evaluator") or ("disabled" if not data.get("enabled", True) else "-"))


def screen_query_studio() -> None:
    st.header("Query Studio")
    api = client()

    query = st.text_area("Query", value="What is retrieval augmented generation?")
    top_k = st.slider("top_k", min_value=1, max_value=10, value=3)
    include_trace = st.checkbox("Include redacted trace", value=True)
    use_batch = st.checkbox("Batch mode (one query per line)", value=False)

    if st.button("Run query", type="primary"):
        if use_batch:
            queries = [line.strip() for line in query.splitlines() if line.strip()]
            with st.spinner("Running batch..."):
                result = api.batch_query(queries, top_k=top_k, include_trace=include_trace)
            if require_ok(result):
                st.json(result.data.get("summary", {}))
                for item in result.data.get("results", []):
                    _render_query_result(item)
        else:
            with st.spinner("Running..."):
                result = api.query(query, top_k=top_k, include_trace=include_trace)
            if require_ok(result):
                st.session_state.last_request_id = result.data.get("request_id") or result.request_id or ""
                _render_query_result(result.data)
            else:
                _failure_taxonomy(result)


def _render_query_result(item: Dict[str, Any]) -> None:
    if item.get("error"):
        st.error(f"{item.get('failure_type')}: {item.get('error')}")
        return
    st.subheader("Answer")
    st.write(item.get("response"))
    st.caption(f"request_id: {item.get('request_id')}")

    cost = item.get("cost") or {}
    latency = item.get("latency") or {}
    c1, c2, c3 = st.columns(3)
    c1.metric("Cost (USD)", cost.get("estimated_cost_usd", 0.0))
    c2.metric("Latency (ms)", latency.get("total_ms", 0.0))
    c3.metric("Failure tags", len(item.get("failure_tags") or []))

    docs = item.get("retrieved_docs_with_scores") or []
    if docs:
        st.subheader("Retrieved documents")
        st.dataframe(
            [
                {"score": d.get("score"), "content": (d.get("content") or "")[:200]}
                for d in docs
            ],
            use_container_width=True,
        )

    stages = latency_rows(latency)
    if stages:
        st.subheader("Per-stage latency")
        st.dataframe(stages, use_container_width=True)

    if item.get("observability"):
        st.subheader("Raw redacted trace")
        st.json(item["observability"])


def screen_compare() -> None:
    st.header("Compare (what-if)")
    api = client()

    st.caption("Rebuild the live pipeline with config overrides, then run A/B queries.")
    metric = st.selectbox("similarity_metric", ["(keep)", "cosine", "l2"])
    retriever = st.selectbox("default_retriever", ["(keep)", "faiss", "simple", "dummy"])
    query = st.text_input("Query", value="What is retrieval augmented generation?")

    if st.button("Apply what-if & run"):
        overrides = {}
        if metric != "(keep)":
            overrides["similarity_metric"] = metric
        if retriever != "(keep)":
            overrides["default_retriever"] = retriever
        with st.spinner("Rebuilding pipeline..."):
            rebuild = api.rebuild(overrides)
        if not require_ok(rebuild):
            return
        st.success(f"Rebuilt at revision {rebuild.data.get('config_revision')}")
        st.json(rebuild.data.get("components", {}))
        after = api.query(query, include_trace=False)
        if require_ok(after):
            _render_query_result(after.data)


def _evaluator_options(api: ApiClient) -> list:
    """Return the configured evaluator keys (blank = active) for the dropdown."""
    options = ["(active)"]
    result = api.evaluators()
    if result.ok:
        options.extend(evaluator.get("key") for evaluator in result.data.get("evaluators", []))
    return options


def screen_evaluation() -> None:
    st.header("Evaluation")
    api = client()

    st.caption(
        "Score a query/response pair with an evaluator. `retrieved_docs` is auto-retrieved "
        "from the live pipeline, so the evaluator judges your response against real context."
    )
    query = st.text_input("Query", value="What is retrieval augmented generation?")
    response = st.text_area("Response", value="RAG grounds an LLM on retrieved documents.")
    options = _evaluator_options(api)
    button_col, gt_col = st.columns([1, 1])
    with button_col:
        evaluator = st.selectbox("Evaluator", options)
    with gt_col:
        ground_truth = st.text_input("Ground truth (optional)", value="")

    if st.button("Evaluate"):
        result = api.evaluate(
            query,
            response,
            evaluator=None if evaluator == "(active)" else evaluator,
            ground_truth=ground_truth or None,
        )
        if require_ok(result):
            st.write(f"Evaluator: `{result.data.get('evaluator')}`")
            st.caption(
                f"docs_source: {result.data.get('docs_source')} | "
                f"num_retrieved_docs: {result.data.get('num_retrieved_docs')} | "
                f"ground_truth_used: {result.data.get('ground_truth_used')}"
            )
            metrics = result.data.get("metrics", {})
            if metrics:
                st.dataframe(metric_rows(metrics), use_container_width=True)
            else:
                st.info("The selected evaluator returned no metrics.")
            if ground_truth and not result.data.get("ground_truth_used"):
                st.info(
                    "Ground truth was echoed but not used: the selected evaluator has no "
                    "`evaluate_with_ground_truth` method."
                )

    st.divider()
    st.subheader("Launch experiment")
    kind = st.selectbox(
        "kind", ["single", "compare_embedding_models", "compare_chunking_strategies"]
    )
    if st.button("Launch"):
        launch = api.launch_experiment(kind=kind, query=query)
        if require_ok(launch):
            st.session_state.last_experiment_id = launch.data.get("id")
            st.json(launch.data)

    exp_id = st.text_input("Experiment id", value=st.session_state.get("last_experiment_id", ""))
    if exp_id and st.button("Poll experiment"):
        poll = api.get_experiment(exp_id)
        if require_ok(poll):
            st.json(poll.data)


def screen_governance() -> None:
    st.header("Governance & Cost")
    api = client()

    status = api.governance_status()
    if require_ok(status):
        c1, c2, c3 = st.columns(3)
        c1.metric("Governance", "enabled" if status.data.get("enabled") else "disabled")
        c2.metric("Max cost / request", status.data.get("max_cost_per_request_usd"))
        c3.metric("Safety margin (tokens)", status.data.get("safety_margin_tokens"))
        window = status.data.get("window", {})
        st.subheader("Spend window")
        st.json(window)

    metrics = api.metrics()
    if require_ok(metrics):
        st.subheader("Metrics")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total runs", metrics.data.get("total_runs"))
        c2.metric("Successes", metrics.data.get("success_count"))
        c3.metric("Failures", metrics.data.get("failure_count"))
        c4.metric("Failure rate", metrics.data.get("failure_rate"))
        st.subheader("Failures by type")
        st.json(metrics.data.get("failures_by_type", {}))


def screen_traces() -> None:
    st.header("Traces")
    api = client()

    request_id = st.text_input("request_id", value=st.session_state.get("last_request_id", ""))
    if request_id and st.button("Look up trace"):
        result = api.trace(request_id)
        if require_ok(result):
            st.json(result.data)
            latency = result.data.get("latency", {})
            rows = latency_rows(latency)
            if rows:
                st.dataframe(rows, use_container_width=True)
            _failure_taxonomy(result)
        else:
            _failure_taxonomy(result)


def screen_settings() -> None:
    st.header("Settings (read-only)")
    api = client()

    st.caption("Read-only view of the redacted effective configuration. YAML files are the source of truth.")
    config = api.effective_config()
    if require_ok(config):
        st.json(config.data.get("config", {}))
    st.subheader("Providers")
    for label, call in (
        ("Models", api.models),
        ("Embedding models", api.embedding_models),
        ("Retrievers", api.retrievers),
        ("Rerankers", api.rerankers),
        ("Evaluators", api.evaluators),
    ):
        result = call()
        if result.ok:
            with st.expander(label):
                st.json(result.data)


SCREENS = {
    "Overview / Health": screen_overview,
    "Query Studio": screen_query_studio,
    "Compare (what-if)": screen_compare,
    "Evaluation": screen_evaluation,
    "Governance & Cost": screen_governance,
    "Traces": screen_traces,
    "Settings (read-only)": screen_settings,
}


def main() -> None:
    _bootstrap()
    st.sidebar.title("GenAI RAG Console")
    st.session_state.api_base_url = st.sidebar.text_input(
        "API base URL", value=st.session_state.api_base_url
    )
    st.session_state.api_key = st.sidebar.text_input(
        "API key (optional)", value=st.session_state.api_key, type="password"
    )
    if st.sidebar.button("Take the tour"):
        start_tour()
    render_help_expander()
    render_tour()
    choice = st.sidebar.radio("Screen", list(SCREENS.keys()))
    SCREENS[choice]()


if __name__ == "__main__":
    main()
