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
        "Updated 2026-11-13. Summary of docs/analysis/ux_roadmap_fact_check.md "
        "(source of truth). Streamlit console at ui/, HTTP-only, API-driven.",
        styles["Small"],
    )
)
story.append(Spacer(1, 6))
story.append(
    Paragraph(
        "<b>Status:</b> UX1-UX12 are delivered and closed (#130-#136, #145, #151-#155). "
        "The remaining tranche, UX13-UX15, is opened as #156-#158 and mapped to "
        "Project #8 Workstream M.",
        styles["Body"],
    )
)
story.append(Spacer(1, 6))

story.append(Paragraph("Assessment: 'Don't make me think'", styles["H2"]))
story.append(
    Paragraph(
        "<b>What works well:</b> HTTP-only client; grouped, role-aware navigation; "
        "15-step tour and action-based Get started checklist; Query Studio templates, "
        "history, compare and result tabs; dataset evaluation with per-case isolation; "
        "trace waterfall; governance filters/export; admin safety; remediation hints; "
        "persistent workspace and shareable deep links; background evaluation jobs; "
        "Dataset Studio authoring; cross-object evidence and request diffs; keyboard-first "
        "command palette plus a WCAG 2.2 AA decision record.",
        styles["Body"],
    )
)
story.append(
    Paragraph(
        "<b>Remaining friction:</b> one generic tour for every persona; no demo mode or "
        "safe reset; no responsive/compact/high-contrast theme system; bad answers cannot "
        "be annotated or promoted into evaluation data; no saved executive/ops dashboards.",
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
    ["UX8", "Persistent workspace/deep links", "#151", "Shipped", "ui/workspace.py; tests/test_ui_workspace.py"],
    ["UX9", "Background evaluation jobs", "#152", "Shipped", "ui/eval_jobs.py; tests/test_ui_eval_jobs.py"],
    ["UX10", "Dataset Studio authoring", "#153", "Shipped", "ui/dataset_studio.py; tests/test_ui_dataset_studio.py"],
    ["UX11", "Cross-object evidence", "#154", "Shipped", "ui/evidence.py; tests/test_ui_evidence.py"],
    ["UX12", "Command palette + WCAG 2.2 AA", "#155", "Shipped", "ui/palette.py; ui/a11y.py; tests/test_ui_palette.py; docs/accessibility.md"],
]
story.append(table(delivered, [0.45 * inch, 1.5 * inch, 0.45 * inch, 0.55 * inch, 2.9 * inch], 6.5))
story.append(Spacer(1, 8))

story.append(Paragraph("Remaining UX/UI Proposals (UX13-UX15, Opened)", styles["H2"]))
story.append(
    Paragraph(
        "Opened as #156-#158. Tracking: label ux, link to umbrella #43, Project #8 Workstream M, "
        "milestone H4, HTTP-only rule plus AST/client tests for every change.",
        styles["Small"],
    )
)
story.append(Spacer(1, 4))
proposals = [
    ["ID", "Proposal", "Priority", "Problem", "Acceptance"],
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
        "1. UX8 persistence/deep links unlocked the rest. 2. UX9 removed the biggest "
        "evaluation blocker. 3. UX12 delivered the accessibility gate. "
        "4. UX10 made evaluation repeatable. 5. UX11 shortened debugging. "
        "6. UX13-UX15 add presentation, persona onboarding and collaboration polish.",
        styles["Body"],
    )
)
story.append(Spacer(1, 6))

story.append(Paragraph("Bottom Line", styles["H2"]))
story.append(
    Paragraph(
        "UX1-UX7 turned the console from a functional API demo into a role-aware, guided "
        "workflow surface. UX8-UX12 made it persistent, asynchronous, evidence-linked and "
        "keyboard-accessible. The remaining tranche (#156-#158) should make it responsive, "
        "persona-specific and collaborative.",
        styles["Body"],
    )
)

doc.build(story)
print(out)
