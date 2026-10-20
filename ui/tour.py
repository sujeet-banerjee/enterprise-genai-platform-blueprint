"""First-time-user guided tour for the Streamlit console.

A lightweight, dependency-free tour: an ordered list of steps (one per sidebar
screen, plus the sidebar controls) rendered with Back / Next / Skip buttons and a
persistent Help expander. No third-party tour library is required.
"""

from dataclasses import dataclass
from typing import List

import streamlit as st


@dataclass(frozen=True)
class TourStep:
    title: str
    screen: str
    body: str
    try_it: str


TOUR_STEPS: List[TourStep] = [
    TourStep(
        title="1. Connect to the backend",
        screen="Sidebar",
        body=(
            "Use the **API base URL** box in the sidebar to point the console at your "
            "backend (default `http://localhost:8000`). If the backend has API-key auth "
            "enabled, paste the key into **API key (optional)**."
        ),
        try_it="Confirm the URL matches where `uvicorn app.main:app` is serving.",
    ),
    TourStep(
        title="2. Overview / Health",
        screen="Overview / Health",
        body=(
            "Shows service **health** and **readiness** (with a config revision), plus "
            "the currently active model, retriever, reranker and evaluator as metric tiles."
        ),
        try_it="Check that Active model = `local-qwen` and Evaluator = `semantic`.",
    ),
    TourStep(
        title="3. Query Studio",
        screen="Query Studio",
        body=(
            "Type a question, set **top_k**, and optionally keep the redacted **trace**. "
            "Click **Run query** to see the answer, retrieved documents + scores, "
            "per-stage latency, cost, failure tags and the raw trace. Tick **Batch mode** "
            "to run one query per line."
        ),
        try_it="Run `What is retrieval augmented generation?` with top_k = 3.",
    ),
    TourStep(
        title="4. Compare (what-if)",
        screen="Compare (what-if)",
        body=(
            "Pick config overrides (similarity metric, retriever) and click **Apply "
            "what-if & run** to rebuild the live pipeline via `POST /v1/pipeline:rebuild`, "
            "then immediately run a query against the new configuration."
        ),
        try_it="Requires `api.allow_rebuild: true` in `config/api.yaml`.",
    ),
    TourStep(
        title="5. Evaluation",
        screen="Evaluation",
        body=(
            "Score a query/response pair with the **Evaluator** dropdown (e.g. `llm_judge`). "
            "Retrieved docs are auto-fetched from the live pipeline. Optionally add "
            "**Launch experiment** below to compare embedding models or chunking strategies."
        ),
        try_it="Select `llm_judge`, then click **Evaluate** and read the metric tiles.",
    ),
    TourStep(
        title="6. Governance & Cost",
        screen="Governance & Cost",
        body=(
            "Shows whether governance is enabled, the per-request cost cap and safety "
            "margin, the rolling **spend window**, and aggregate **metrics** "
            "(runs, successes, failures, failure rate, failures by type)."
        ),
        try_it="After a few queries, watch Total runs increase.",
    ),
    TourStep(
        title="7. Traces",
        screen="Traces",
        body=(
            "Paste a `request_id` (from a Query Studio result) and click **Look up trace** "
            "to see the exact redacted trace the server logged, plus a per-stage latency table."
        ),
        try_it="Look up the request_id shown after your Query Studio run.",
    ),
    TourStep(
        title="8. Settings (read-only)",
        screen="Settings (read-only)",
        body=(
            "View the redacted **effective configuration** and expand the provider lists "
            "(models, embedding models, retrievers, rerankers, evaluators). YAML files in "
            "`config/` remain the source of truth."
        ),
        try_it="Confirm no secrets are shown (values are `[REDACTED]`).",
    ),
]


def _state() -> str:
    return st.session_state.get("tour_state", "idle")


def _set_state(value: str) -> None:
    st.session_state.tour_state = value


def _step_index() -> int:
    return int(st.session_state.get("tour_step", 0))


def _set_step(index: int) -> None:
    st.session_state.tour_step = max(0, min(index, len(TOUR_STEPS) - 1))


def render_help_expander() -> None:
    """A persistent, always-available reference for every screen."""
    with st.expander("Help & tour guide", expanded=False):
        st.markdown(
            "New here? Click **Take the tour** in the sidebar for a step-by-step walkthrough, "
            "or read the summary below."
        )
        for step in TOUR_STEPS:
            st.markdown(f"**{step.title}** - _screen: {step.screen}_")
            st.markdown(step.body)
            st.caption(f"Try it: {step.try_it}")


def render_tour() -> None:
    """Render the guided-tour control panel and the current step."""
    state = _state()

    if state == "idle":
        return

    if state == "done":
        st.success("Tour complete. Use the sidebar **Screen** list to explore, or reopen Help & tour guide.")
        if st.button("Restart tour"):
            _set_step(0)
            _set_state("running")
        return

    index = _step_index()
    step = TOUR_STEPS[index]
    st.info(
        f"**Guided tour - {step.title}**  \n"
        f"_Go to sidebar screen:_ `{step.screen}`  \n\n"
        f"{step.body}  \n\n"
        f"**Try it:** {step.try_it}"
    )

    back, nxt, skip = st.columns([1, 1, 1])
    with back:
        if st.button("Back", disabled=index == 0):
            _set_step(index - 1)
    with nxt:
        label = "Finish" if index == len(TOUR_STEPS) - 1 else "Next"
        if st.button(label, type="primary"):
            if index == len(TOUR_STEPS) - 1:
                _set_state("done")
            else:
                _set_step(index + 1)
    with skip:
        if st.button("Skip tour"):
            _set_state("done")

    st.progress((index + 1) / len(TOUR_STEPS), text=f"Step {index + 1} of {len(TOUR_STEPS)}")


def start_tour() -> None:
    _set_step(0)
    _set_state("running")
