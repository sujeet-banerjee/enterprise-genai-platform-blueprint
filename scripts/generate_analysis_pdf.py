#!/usr/bin/env python3
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

out = Path("/home/sujeet/enterprise-genai-platform-blueprint/docs/analysis/fact_check_usability_value_for_enterprise_architects.pdf")
out.parent.mkdir(parents=True, exist_ok=True)
doc = SimpleDocTemplate(str(out), pagesize=letter, topMargin=0.5*inch, bottomMargin=0.5*inch)
styles = getSampleStyleSheet()
styles.add(ParagraphStyle(name='H1', parent=styles['Heading1'], fontSize=16, spaceAfter=12))
styles.add(ParagraphStyle(name='H2', parent=styles['Heading2'], fontSize=12, spaceAfter=8))
styles.add(ParagraphStyle(name='Body', parent=styles['BodyText'], fontSize=9, leading=11))
styles.add(ParagraphStyle(name='Small', parent=styles['BodyText'], fontSize=8, leading=10))

story = []
story.append(Paragraph("Fact Analysis: Usability & Value for Enterprise Architects", styles['H1']))
story.append(Paragraph("Generated 2026-11-02. Grounded in repository state.", styles['Small']))
story.append(Spacer(1, 6))

story.append(Paragraph("1) Market Pain Points vs. What This Project Addresses", styles['H2']))
data = [
["Pain Point", "Industry Reality", "How This Project Addresses It", "Maturity"],
["Lack of proper evaluation", "Most orgs can't answer 'is this RAG actually good?' beyond 'it looks okay'. Hallucination rates unmeasured.", "SemanticEvaluator, LLMJudgeEvaluator, EvaluationEngine, ground-truth scoring, benchmark runner, experiment runner, /v1/evaluate + /v1/experiments.", "Strong"],
["Governance & compliance", "PII leakage, prompt injection, unauthorized access, lack of audit trails block production adoption.", "Guardrail framework, InjectionGuardrail, PiiGuardrail, tenancy/workspaces, ACL, RBAC/identity, immutable audit hash-chain/export/verify/purge, attribution.", "Strong"],
["Observability & debugging", "Black box RAG makes failures un-debuggable. Need traces, costs, failure taxonomy.", "PipelineObservabilityTracker, failure classification, RunHistory, /v1/traces/{id}, /v1/metrics, /metrics, OTel OTLP, Grafana dashboards/alerts.", "Strong"],
["RAG workflow complexity", "Chunking, retrieval, reranking, query expansion ad-hoc and hard to compare.", "Config-driven registries, retrievers (FAISS/Simple/Dummy/KG/Hybrid), rerankers, query expanders, response cache, batching/parallel, /v1/pipeline:rebuild.", "Strong"],
["Knowledge Graph adoption friction", "KGs powerful but hard to integrate with vector search and evaluate.", "KGRetriever (triples + expansion), hybrid BM25+vector, benchmark runner.", "Good"],
["Vendor lock-in & cost control", "Want to swap models/providers without rewriting code, need cost governance.", "Vendor-neutral interfaces/registries, OpenAI+local/HF, per-model pricing, budget caps, tenant budgets, attribution, what-if.", "Strong"],
["Deployment & operations", "Need HA, rollbacks, secrets, validation to go from notebook to prod.", "Helm/Kustomize/GitOps, HPA/KEDA, Argo Rollouts, config validation+secrets, Codespaces, health/ready, BaseStore, immutable audit.", "Good"],
]
t = Table(data, repeatRows=1, colWidths=[0.9*inch, 1.3*inch, 2.7*inch, 0.6*inch])
t.setStyle(TableStyle([
('BACKGROUND',(0,0),(-1,0),colors.grey),
('TEXTCOLOR',(0,0),(-1,0),colors.whitesmoke),
('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'),
('FONTSIZE',(0,0),(-1,0),6),
('FONTSIZE',(0,1),(-1,-1),6),
('GRID',(0,0),(-1,-1),0.25,colors.black),
('VALIGN',(0,0),(-1,-1),'TOP'),
]))
story.append(t)
story.append(Spacer(1, 8))

story.append(Paragraph("2) Usability for Enterprise Architects", styles['H2']))
story.append(Paragraph("<b>What works well:</b> Config-first design; single source of truth via registries/bootstrap; introspection-first APIs; evaluation as first-class; defense-in-depth security.", styles['Body']))
story.append(Paragraph("<b>Friction points:</b> Complexity/learning curve; slow local dev with model downloads; limited connector ecosystem; Streamlit UI great for demos but API integration needed for most architect workflows.", styles['Body']))
story.append(Spacer(1, 6))

story.append(Paragraph("3) Value Assessment (Assuming Near Completion)", styles['H2']))
data2 = [
["Audience Need", "Value", "Notes"],
["Platform/AI Architects", "Very High", "Treats eval/governance/observability as non-negotiable; config-driven architecture reference-quality."],
["Security/Compliance Architects", "Very High", "Guardrails, PII, ACL, tenancy, immutable audit, attribution address enterprise requirements."],
["Data/ML Architects (RAG/KG)", "High", "Hybrid+KG, experiments, benchmarks strong; needs connectors and larger eval datasets."],
["SRE/Platform Engineers", "High", "OTel/Prometheus/Helm/Kustomize/HPA/rollouts/health/config validation aligned; multi-region/DR planned."],
["Product/Business Stakeholders", "Medium-High", "Cost attribution/governance help; more architectural than user-facing; UI functional not polished."],
]
t2 = Table(data2, repeatRows=1, colWidths=[1.5*inch, 0.8*inch, 3.2*inch])
t2.setStyle(TableStyle([
('BACKGROUND',(0,0),(-1,0),colors.grey),
('TEXTCOLOR',(0,0),(-1,0),colors.whitesmoke),
('FONTNAME',(0,0),(-1,0),'Helvetica-Bold'),
('FONTSIZE',(0,0),(-1,0),6),
('FONTSIZE',(0,1),(-1,-1),6),
('GRID',(0,0),(-1,-1),0.25,colors.black),
('VALIGN',(0,0),(-1,-1),'TOP'),
]))
story.append(t2)
story.append(Spacer(1, 8))

story.append(Paragraph("4) Verdict & Remaining Gaps", styles['H2']))
story.append(Paragraph("<b>Verdict:</b> Highly valuable and usable for enterprise architects moving RAG/agentic workflows from POC to production. Fills evaluation/governance/observability gaps better than most open-source alternatives.", styles['Body']))
story.append(Paragraph("<b>Key differentiators:</b> Evaluation-first; config-driven swappability/vendor neutrality; defense-in-depth; production operations (Helm/GitOps/rollouts/observability).", styles['Body']))
story.append(Paragraph("<b>Remaining gaps:</b> Data connectors (SharePoint/Confluence/S3/etc.); scalability hardening (multi-region/DR G5/G6 + robust persistence); policy-as-code engine; larger/domain-specific eval datasets; simplified onboarding/golden-path templates.", styles['Body']))
story.append(Paragraph("<b>Bottom line:</b> With near-completion of remaining roadmap items (especially G5/G6), this is an excellent reference architecture and viable foundation for an internal platform - solving the productionization problem.", styles['Body']))

doc.build(story)
print(out)
