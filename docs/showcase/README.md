# Showcase package

> Draft, review-ready material for presenting this repository publicly. Nothing here is
> published automatically. The user reviews, approves and publishes every surface.

This directory owns the *presentation* copy that must stay consistent with the
[repository identity](../positioning.md), the [capability status matrix](../capability-status.md)
and the [production-readiness assessment](../production-readiness.md). It is not a second
source of truth: when a claim and the evidence disagree, the evidence wins and the copy is
corrected.

| File | Purpose | Status |
| --- | --- | --- |
| [demo-walkthrough.md](demo-walkthrough.md) | End-to-end 3-5 minute console demo script (RAG/eval/governance/trace-audit) with external captures (#189) | Maintainer-maintained; external capture links may be pending |
| [qa-and-captures.md](qa-and-captures.md) | UI look/feel QA matrix, target capture manifest and known exceptions (#257) | Structural QA complete; external visual links pending #232 |
| [linkedin.md](linkedin.md) | LinkedIn profile project entry, announcement post and approval checklist (#193) | Awaiting user approval |

## Approval workflow

1. Read [linkedin.md](linkedin.md) and confirm the title, dates, Experience association and
   skills.
2. Add the profile project entry manually in the LinkedIn UI.
3. Publish the announcement post only after the profile entry exists, so the post can link
   to it.
4. If any claim changes, update
   [positioning.md](../positioning.md) first, then this package, or `tests/test_showcase_linkedin.py`
   will fail.

## Rules

- Reuse the canonical name and one-liner from [positioning.md](../positioning.md).
- Use the status vocabulary from [capability-status.md](../capability-status.md):
  **Tested**, **Implemented**, **Partial**, **Planned**, **External**.
- Keep every claim traceable to a path, issue or document in this repository.
- Never describe the project as a customer deployment, employer-sponsored work, a
  production-certified platform or a commercial product.
- Do not publish on the user's behalf or automate LinkedIn login, profile edits or posting.
