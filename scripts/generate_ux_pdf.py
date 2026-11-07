#!/usr/bin/env python3
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

REPO_ROOT = Path(__file__).resolve().parents[1]
out = REPO_ROOT / "docs" / "analysis" / "ux_roadmap_fact_check.pdf"
out.parent.mkdir(parents=True, exist_ok=True)
doc = SimpleDocTemplate(str(out), pagesize=letter, topMargin=0.5 * inch, bottomMargin=0.5 * inch)
styles = getSampleStyleSheet()
styles.add(ParagraphStyle(name="H1", parent=styles["Heading1"], fontSize=16, spaceAfter=12))
styles.add(ParagraphStyle(name="H2", parent=styles["Heading2"], fontSize=12, spaceAfter=8))
styles.add(ParagraphStyle(name="Body", parent=styles["BodyText"], fontSize=9, leading=11))
styles.add(ParagraphStyle(name="Small", parent=styles["BodyText"], fontSize=8, leading=10))


def table(data, widths, font_size=6.5, header_rows=1):
    t = Table(data, repeatRows=header_rows, colWidths=widths)
    t.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, header_rows - 1), colors.grey),
                ("TEXTCOLOR", (0, 0), (-1, header_rows - 1), colors.whitesmoke),
                ("FONTNAME", (0, 0), (-1, header_rows - 1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), font_size),
                ("GRID", (0, 0), (-1, -1), 0.25, colors.black),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    return t


story = []
story.append(Paragraph("UX Roadmap Fact-Check &amp; Plan", styles["H1"]))
story.append(
    Paragraph(
        "Updated 2026-11-07. Summary of docs/analysis/ux_roadmap_fact_check.md "
        "(source of truth). Streamlit console at ui/, HTTP-only, API-driven.",
        styles["Small"],
    )
)
story.append(Spacer(1, 6))
story.append(
    Paragraph(
        "<b>Status:</b> UX1-UX7 are delivered and closed (#130-#136), including the "
        "#145 dataset-runner follow-up. The next tranche, UX8-UX15, is opened as "
        "#151-#158 and mapped to Project #8 Workstream M.",
        styles["Body"],
    )
)
story.append(Spacer(1, 6))

story.append(Paragraph("Assessment: 'Don't make me think'", styles["H2"]))
story.append(
    Paragraph(
        "<b>What works well:</b> HTTP-only client; grouped, role-aware navigation; "
        "13-step tour and action-based Get started checklist; Query Studio templates, "
        "history, compare and result tabs; dataset evaluation with per-case isolation; "
        "trace waterfall; governance filters/export; admin safety; remediation hints.",
        styles["Body"],
    )
)
story.append(
    Paragraph(
        "<b>Remaining friction:</b> session-bound workspace; no persistent deep links; "
        "dataset runs are synchronous and capped at 20 cases; no dataset authoring; "
        "trace/audit/metrics/governance are not cross-linked; no formal WCAG 2.2 AA or "
        "keyboard-first flow; no command palette; one generic tour; no annotations or "
        "feedback capture; no saved executive/ops dashboards.",
        styles["Body"],
    )
)
story.append(Spacer(1, 6))

story.append(Paragraph("Delivered UX Workstreams (Closed)", styles["H2"]))
delivered = [
    ["ID", "Workstream", "Issue", "Status", "Evidence"],
    ["UX1", "Simplify IA and onboarding", "#130", "Shipped", "ui/navigation.py; tests/test_ux_navigation.py"],
    ["UX2", "Query Studio workflow polish", "#131", "Shipped", "ui/query_studio.py; tests/test_query_studio.py"],
    ["UX3", "Evaluation UX improvements", "#132", "Shipped", "ui/evaluation.py; tests/test_ui_evaluation_ux.py"],
    ["UX3b", "Dataset execution follow-up", "#145", "Shipped", "ui/evaluation.py; tests/test_ui_dataset_evaluation.py"],
    ["UX4", "Traces timeline/waterfall", "#133", "Shipped", "ui/traces.py; tests/test_ui_traces_timeline.py"],
    ["UX5", "Governance filters and export", "#134", "Shipped", "ui/governance.py; tests/test_ui_governance_filters.py"],
    ["UX6", "Admin/tenancy safety UX", "#135", "Shipped", "ui/admin.py; tests/test_ui_admin_safety.py"],
    ["UX7", "Polish, a11y, empty states", "#136", "Shipped", "ui/polish.py; tests/test_ui_polish.py"],
]
story.append(table(delivered, [0.45 * inch, 1.5 * inch, 0.45 * inch, 0.55 * inch, 2.9 * inch], 6.5))
story.append(Spacer(1, 8))

story.append(Paragraph("New UX/UI Proposals (UX8-UX15, Opened)", styles["H2"]))
story.append(
    Paragraph(
        "Opened as #151-#158. Tracking: label ux, link to umbrella #43, Project #8 Workstream M, "
        "milestone H4, HTTP-only rule plus AST/client tests for every change.",
        styles["Small"],
    )
)
story.append(Spacer(1, 4))
proposals = [
    ["ID", "Proposal", "Priority", "Problem", "Acceptance"],
    [
        "UX8",
        "Persistent workspace and shareable deep links",
        "P0",
        "Reload/share loses history, filters, runs, datasets and comparisons.",
        "Reload resumes screen/filters; links reproduce trace/governance views; no secrets in URLs.",
    ],
    [
        "UX9",
        "Background evaluation jobs: progress, cancel, resume",
        "P0",
        "Dataset runs block the UI, stop at 20 cases and cannot cancel/resume.",
        "100-case run stays responsive; cancel within one case; retry only failures; results survive refresh.",
    ],
    [
        "UX10",
        "Dataset Studio authoring",
        "P1",
        "Users hand-write JSON; no case/doc editor, validation, save or round-trip export.",
        "Author 20 cases/10 docs without JSON; inline validation; export round-trips.",
    ],
    [
        "UX11",
        "Cross-link and compare operational evidence",
        "P1",
        "Trace, audit, metrics and governance are disconnected; comparing requests is manual.",
        "Reach audit/metrics from a trace in <=2 clicks; two-trace diff shows stage/failure/document/guardrail deltas.",
    ],
    [
        "UX12",
        "Command palette and accessibility hardening",
        "P1",
        "Navigation is mouse-first; WCAG 2.2 AA and keyboard/screen-reader flows are unverified.",
        "Primary flows keyboard-only; no critical/serious a11y findings; usable at 200% zoom.",
    ],
    [
        "UX13",
        "Responsive, compact and theme system",
        "P2",
        "Wide layouts break on small screens; tables/colors are inconsistent.",
        "375/768/1280 px core flows have no horizontal scroll; contrast >=4.5:1; theme checks pass.",
    ],
    [
        "UX14",
        "Role-based guided journeys and demo mode",
        "P2",
        "One generic tour; no safe demo data or reset for personas.",
        "Each persona journey <10 min; reset is clean; tour covers new screens; no production data touched.",
    ],
    [
        "UX15",
        "Collaboration and feedback capture",
        "P2",
        "Bad answers cannot be annotated or promoted into evaluation data; sharing is copy/paste.",
        "Flag -> eval case in one click; annotations survive reload; exports are redacted.",
    ],
]
story.append(table(proposals, [0.4 * inch, 1.35 * inch, 0.55 * inch, 2.1 * inch, 2.1 * inch], 6))
story.append(Spacer(1, 8))

story.append(Paragraph("Recommended Execution Order", styles["H2"]))
story.append(
    Paragraph(
        "1. UX8 persistence/deep links unlocks the rest. 2. UX9 removes the biggest "
        "evaluation blocker. 3. UX12 is the enterprise accessibility gate. "
        "4. UX10 makes evaluation repeatable. 5. UX11 shortens debugging. "
        "6. UX13-UX15 add presentation, persona onboarding and collaboration polish.",
        styles["Body"],
    )
)
story.append(Spacer(1, 6))

story.append(Paragraph("Bottom Line", styles["H2"]))
story.append(
    Paragraph(
        "UX1-UX7 turned the console from a functional API demo into a role-aware, guided "
        "workflow surface. The next tranche (#151-#158) should make it persistent, "
        "asynchronous, accessible and collaborative. UX8 and UX9 are the highest-value "
        "changes; UX12 is the accessibility gate.",
        styles["Body"],
    )
)

doc.build(story)
print(out)
