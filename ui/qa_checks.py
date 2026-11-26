from __future__ import annotations

import ast
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Sequence, Tuple

VIEWPORTS: Tuple[str, ...] = ("375", "768", "1280")
THEMES: Tuple[str, ...] = ("Light", "Dark", "High contrast")
MODES: Tuple[str, ...] = ("normal", "demo", "restricted role")

QA_RESULT = "documented"
QA_EVIDENCE = "structural checks only; external visual capture pending #232"
PENDING_CAPTURE_LINK = "_Pending - add external link (#232)_"

HTTP_FORBIDDEN_ROOTS = frozenset({"app", "core"})
PURE_FORBIDDEN_ROOTS = frozenset({"app", "core", "streamlit", "requests"})
FORBIDDEN_LITERALS = ("app" + ".pipeline", "import " + "core", "from " + "core")

QA_CSS_TOKENS: Tuple[str, ...] = (
    ".genai-kpi-strip",
    ".genai-alert",
    ".genai-trust-banner",
    ".genai-responsive-table",
    ".genai-score-fill",
    ".genai-waterfall-track",
    "@media (max-width: 640px)",
    "focus-visible",
    "prefers-reduced-motion",
)


@dataclass(frozen=True)
class QaArea:
    name: str
    checks: str
    captures: Tuple[str, ...]


@dataclass(frozen=True)
class CaptureTarget:
    slug: str
    title: str
    screen: str


QA_AREAS: Tuple[QaArea, ...] = (
    QaArea(
        "Shell & nav",
        "Branded header, active nav, sticky sidebar at >=1024, palette/help reachable, no clipped text",
        ("overview-health", "settings-readonly"),
    ),
    QaArea(
        "Status semantics",
        "Consistent ok/warn/error/blocked/disabled badges across screens",
        ("query-studio-result", "guardrails-decisions", "approvals-queue"),
    ),
    QaArea(
        "Raw-data discipline",
        "Primary view structured; raw JSON only in labeled redacted expanders",
        ("query-studio-result", "settings-readonly", "governance-cost", "audit-timeline"),
    ),
    QaArea(
        "Tables & cards",
        "Dense tables degrade to cards with all fields and actions; no page-level horizontal scroll",
        ("guardrails-decisions", "approvals-queue", "audit-timeline"),
    ),
    QaArea(
        "Charts/timelines",
        "Latency, cost and guardrail visuals render with readable legends and high-contrast safe colors",
        ("traces-waterfall-compare", "governance-cost"),
    ),
    QaArea(
        "States",
        "Empty, loading, error and taxonomy failures show structured remediation",
        ("overview-health", "query-studio-result", "audit-timeline", "approvals-queue"),
    ),
    QaArea(
        "Trust cues",
        "Demo, redaction, tenant scope and destructive confirmation cues are visible",
        ("approvals-queue", "settings-readonly"),
    ),
    QaArea(
        "Accessibility",
        "Skip link, focus-visible, keyboard palette/nav, 200% zoom reflow, reduced motion",
        ("query-studio-result", "traces-waterfall-compare", "approvals-queue"),
    ),
)

CAPTURE_TARGETS: Tuple[CaptureTarget, ...] = (
    CaptureTarget("overview-health", "Overview / Health", "Overview / Health"),
    CaptureTarget("query-studio-result", "Query Studio result", "Query Studio"),
    CaptureTarget("traces-waterfall-compare", "Traces waterfall + compare", "Traces"),
    CaptureTarget("governance-cost", "Governance & Cost", "Governance & Cost"),
    CaptureTarget("guardrails-decisions", "Guardrails decisions", "Guardrails"),
    CaptureTarget("approvals-queue", "Approvals queue", "Approvals"),
    CaptureTarget("audit-timeline", "Audit timeline", "Audit"),
    CaptureTarget("settings-readonly", "Settings (read-only)", "Settings (read-only)"),
)

CAPTURE_SLUGS: Tuple[str, ...] = tuple(target.slug for target in CAPTURE_TARGETS)
CAPTURE_VARIANTS: Tuple[Tuple[str, str], ...] = (
    ("light-1280", "Light @ 1280"),
    ("compact", "Compact/mobile @ 375"),
    ("high-contrast", "High contrast @ 1280"),
)


def _import_issues(source: str, roots: Iterable[str], label: str) -> List[str]:
    forbidden = frozenset(roots)
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return [f"{label}: invalid Python ({exc.msg} at line {exc.lineno})"]

    issues: List[str] = []
    for node in ast.walk(tree):
        node_roots: List[str] = []
        if isinstance(node, ast.Import):
            node_roots = [alias.name.split(".", 1)[0] for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            node_roots = [module.split(".", 1)[0]] if module else []
        for root in node_roots:
            if root in forbidden:
                issues.append(f"{label}: line {getattr(node, 'lineno', '?')} imports {root}")
    return issues


def check_http_only(source: str) -> List[str]:
    issues = _import_issues(source, HTTP_FORBIDDEN_ROOTS, "http_only")
    for literal in FORBIDDEN_LITERALS:
        if literal in source:
            issues.append(f"http_only: contains forbidden literal {literal}")
    return issues


def check_pure_helper(source: str) -> List[str]:
    return _import_issues(source, PURE_FORBIDDEN_ROOTS, "pure_helper")


def check_theme_tokens(css: str, tokens: Sequence[str] = QA_CSS_TOKENS) -> List[str]:
    return sorted(token for token in tokens if token not in css)


def check_capture_doc(doc: str, slugs: Sequence[str] = CAPTURE_SLUGS) -> List[str]:
    return [slug for slug in slugs if slug not in doc]


def qa_matrix(
    viewports: Sequence[str] = VIEWPORTS,
    themes: Sequence[str] = THEMES,
    modes: Sequence[str] = MODES,
) -> List[Dict[str, str]]:
    return [
        {
            "viewport": viewport,
            "theme": theme,
            "mode": mode,
            "result": QA_RESULT,
            "evidence": QA_EVIDENCE,
        }
        for viewport in viewports
        for theme in themes
        for mode in modes
    ]


def qa_summary(rows: Sequence[Dict[str, str]]) -> Dict[str, Any]:
    by_result: Dict[str, int] = {}
    by_viewport: Dict[str, int] = {}
    for row in rows:
        by_result[row["result"]] = by_result.get(row["result"], 0) + 1
        by_viewport[row["viewport"]] = by_viewport.get(row["viewport"], 0) + 1
    return {"total": len(rows), "by_result": by_result, "by_viewport": by_viewport}


def area_checklist() -> List[Dict[str, Any]]:
    return [
        {"area": area.name, "checks": area.checks, "captures": list(area.captures)}
        for area in QA_AREAS
    ]


def capture_manifest() -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for target in CAPTURE_TARGETS:
        variants = [
            {"slug": f"{target.slug}-{suffix}", "label": label, "link": PENDING_CAPTURE_LINK}
            for suffix, label in CAPTURE_VARIANTS
        ]
        rows.append(
            {
                "slug": target.slug,
                "title": target.title,
                "screen": target.screen,
                "primary": variants[0]["slug"],
                "variants": variants,
                "link": PENDING_CAPTURE_LINK,
            }
        )
    return rows


def _cell(value: Any) -> str:
    return str(value).replace("|", "\\|")


def qa_report_markdown() -> str:
    rows = qa_matrix()
    summary = qa_summary(rows)
    lines = [
        "# UI look & feel QA and target captures (#257)",
        "",
        "> **Status:** structural QA complete; external visual captures are maintained outside",
        "> the repository and linked by the maintainer (#232).",
        "",
        "## Scope",
        "",
        f"- Viewports: {', '.join(f'{viewport} px' for viewport in VIEWPORTS)}",
        f"- Themes: {', '.join(THEMES)}",
        f"- Modes: {', '.join(MODES)}",
        f"- Matrix rows: {summary['total']} ({summary['by_result']})",
        "",
        "## QA matrix",
        "",
        "| Viewport | Theme | Mode | Result | Evidence |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        lines.append(
            "| {viewport} | {theme} | {mode} | {result} | {evidence} |".format(
                **{key: _cell(value) for key, value in row.items()}
            )
        )

    lines.extend(["", "## Area checklist", "", "| Area | Checks | Targets |", "| --- | --- | --- |"])
    for row in area_checklist():
        lines.append(
            f"| {_cell(row['area'])} | {_cell(row['checks'])} | {_cell(', '.join(row['captures']))} |"
        )

    lines.extend(
        [
            "",
            "## Target capture manifest",
            "",
            "| Capture | Title | Screen | Variants | Link |",
            "| --- | --- | --- | --- | --- |",
        ]
    )
    for row in capture_manifest():
        variant_slugs = " / ".join(variant["slug"] for variant in row["variants"])
        lines.append(
            "| {slug} | {title} | {screen} | {variants} | {link} |".format(
                slug=_cell(row["slug"]),
                title=_cell(row["title"]),
                screen=_cell(row["screen"]),
                variants=_cell(variant_slugs),
                link=_cell(row["link"]),
            )
        )

    lines.extend(
        [
            "",
            "## How to refresh captures",
            "",
            "1. Run `streamlit run ui/app.py` and enter demo mode as described in",
            "   [demo-walkthrough.md](demo-walkthrough.md).",
            "2. Capture each manifest row in Light @1280, one compact/mobile sample, and one",
            "   High-contrast sample.",
            "3. Publish the captures outside this repository and replace the pending links in",
            "   [demo-walkthrough.md](demo-walkthrough.md) and this manifest.",
            "",
            "## Known exceptions",
            "",
            "- Screenshots and recordings are linked, not committed, per the #257 guardrail.",
            "- CI has no browser capture harness, so the executable evidence is structural:",
            "  HTTP-only AST guards, theme-token checks, capture-manifest checks, and QA matrix",
            "  tests in `tests/test_ui_qa_checks.py`.",
            "- External capture URLs are maintained by the maintainer under #232; this report",
            "  records the refreshed target names and expected variants until those links land.",
            "",
        ]
    )
    return "\n".join(lines)


def validate_qa_artifacts(
    app_source: str,
    helper_source: str,
    css: str,
    qa_doc: str,
    plan_doc: str,
    showcase_index: str,
) -> List[str]:
    issues: List[str] = []
    issues.extend(check_http_only(app_source))
    issues.extend(check_pure_helper(helper_source))
    issues.extend(check_theme_tokens(css))
    issues.extend(check_capture_doc(qa_doc))
    for viewport in VIEWPORTS:
        if f"{viewport} px" not in qa_doc:
            issues.append(f"qa_doc: missing viewport {viewport} px")
    for theme in THEMES:
        if theme not in qa_doc:
            issues.append(f"qa_doc: missing theme {theme}")
    for mode in MODES:
        if mode not in qa_doc:
            issues.append(f"qa_doc: missing mode {mode}")
    if "#257" not in qa_doc:
        issues.append("qa_doc: missing #257 reference")
    if "#232" not in qa_doc:
        issues.append("qa_doc: missing #232 capture-link reference")
    if "qa-and-captures.md" not in showcase_index:
        issues.append("showcase_index: missing qa-and-captures.md link")
    if "qa-and-captures.md" not in plan_doc:
        issues.append("plan_doc: missing qa-and-captures.md link")
    return issues
