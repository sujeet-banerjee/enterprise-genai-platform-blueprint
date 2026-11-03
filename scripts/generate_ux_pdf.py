#!/usr/bin/env python3
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

out = Path("/home/sujeet/enterprise-genai-platform-blueprint/docs/analysis/ux_roadmap_fact_check.pdf")
out.parent.mkdir(parents=True, exist_ok=True)
doc = SimpleDocTemplate(str(out), pagesize=letter, topMargin=0.5 * inch, bottomMargin=0.5 * inch)
styles = getSampleStyleSheet()
styles.add(ParagraphStyle(name="H1", parent=styles["Heading1"], fontSize=16, spaceAfter=12))
styles.add(ParagraphStyle(name="H2", parent=styles["Heading2"], fontSize=12, spaceAfter=8))
styles.add(ParagraphStyle(name="Body", parent=styles["BodyText"], fontSize=9, leading=11))
styles.add(ParagraphStyle(name="Small", parent=styles["BodyText"], fontSize=8, leading=10))

story = []
story.append(Paragraph("UX Roadmap Fact-Check & Plan", styles["H1"]))
story.append(Paragraph("Generated 2026-11-03. Streamlit console at ui/, HTTP-only, API-driven.", styles["Small"]))
story.append(Spacer(1, 6))

story.append(Paragraph("Assessment: 'Don't make me think'", styles["H2"]))
story.append(Paragraph("<b>What works well:</b> HTTP-only client; IA covers key flows; guided tour/help; API-first introspection; failure taxonomy; feature parity with backend.", styles["Body"]))
story.append(Paragraph("<b>Friction/gaps:</b> 11 screens/cognitive load; no guided workflows; Query Studio lacks templates/history/compare; Evaluation needs GT/dataset/comparison; Traces dense JSON; Governance needs filters/export; Admin/tenancy needs safety; errors need remediation; a11y/empty states missing.", styles["Body"]))
story.append(Spacer(1, 6))

story.append(Paragraph("Proposed UX Workstreams", styles["H2"]))
data = [
    ["ID", "Workstream", "Priority", "Goal"],
    ["UX1", "Simplify IA & onboarding", "P0", "Reduce load, role-based defaults"],
    ["UX2", "Query Studio workflow polish", "P0", "Templates/history/compare/result tabs"],
    ["UX3", "Evaluation UX improvements", "P0", "Dataset/GT/comparison/charts/explain"],
    ["UX4", "Traces timeline/waterfall", "P1", "Timeline/span filter/redaction-safe"],
    ["UX5", "Governance/metrics filters & export", "P1", "Time range/filters/CSV/alerts"],
    ["UX6", "Admin/tenancy safety UX", "P1", "Switch warnings/confirmations/export"],
    ["UX7", "Polish, a11y, empty states", "P2", "Remediation/tooltips/keyboard/empty states"],
]
t = Table(data, repeatRows=1, colWidths=[0.5*inch, 1.8*inch, 0.6*inch, 3.6*inch])
t.setStyle(TableStyle([
    ('BACKGROUND',(0,0),(-1,0),colors.grey),
    ('TEXTCOLOR',(0,0),(-1,0),colors.whitesmoke),
    ('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'),
    ('FONTSIZE',(0,0),(-1,0),7),
    ('FONTSIZE',(0,1),(-1,-1),7),
    ('GRID',(0,0),(-1,-1),0.25,colors.black),
    ('VALIGN',(0,0),(-1,-1),'TOP'),
]))
story.append(t)
story.append(Spacer(1, 8))

story.append(Paragraph("Suggested Issues & Tracking", styles["H2"]))
story.append(Paragraph("#129 UX1 IA simplification, #130 UX2 Query Studio, #131 UX3 Evaluation, #132 UX4 Traces timeline/waterfall, #133 UX5 Governance/metrics export, #134 UX6 Admin/tenancy safety, #135 UX7 Polish/a11y. Labels ux, link to #43, Project #8 Workstream F, H2/H3. Keep HTTP-only; add AST/client tests.", styles["Body"]))
story.append(Spacer(1, 6))

story.append(Paragraph("Bottom Line", styles["H2"]))
story.append(Paragraph("Console is functional and API-aligned. Focused polish will make it significantly more intuitive for enterprise architects and speed adoption of evaluation/governance/observability.", styles["Body"]))

doc.build(story)
print(out)
