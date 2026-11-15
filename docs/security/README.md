# Security posture and qualification

> **This is evidence-based qualification, not a certification.** It records what was
> tested against this reference implementation, what was found, and what remains
> unvalidated. It is **not** a penetration test, an audit opinion, or a substitute for
> an adopter's own security review and independent assessment.

Assessed **2026-11-15** against `main` @ `ca95215` (capability surface unchanged by the
qualification PR itself except the dependency bump noted in F-06).

Companion documents: [threat model](threat-model.md) describes assets, trust boundaries
and abuse cases; [test plan](test-plan.md) maps every in-scope threat to automated
evidence or an explicitly tracked gap. The [production-readiness assessment](../production-readiness.md)
ranks operational risk; the [capability status matrix](../capability-status.md) records
what exists feature by feature.

## Scope

| In scope | Out of scope |
| --- | --- |
| Application-layer controls shipped in `app/` and `core/` (auth, RBAC, tenancy, ACL retrieval, guardrails, redaction, audit, admin operations) | Host/OS, kernel, container-runtime escape, network policy, TLS termination, WAF/DDoS |
| Configuration defaults and the effect of enabling each control | Identity-provider hardening, MFA policy, IdP misconfiguration |
| Cross-tenant and cross-identity isolation through the supported API and pipeline | Model training/weight provenance, foundation-model jailbreak research |
| Secret/PII handling in responses, traces, audit and introspection | Physical access, insider with host/root access, side channels |
| CI dependency/scanning posture as configured in this repository | Third-party services (GitHub, OpenAI, Hugging Face) after data leaves this process |

## How to reproduce

```bash
# Adversarial negative-case matrix (dummy providers, no network, seconds)
python -m pytest tests/test_security_qualification.py -q

# Structural guards: threat model <-> test plan <-> findings stay consistent
python -m pytest tests/test_security_docs.py -q

# Existing control suites cited by the test plan
python -m pytest tests/test_identity.py tests/test_acl_retrieval.py tests/test_tenancy.py \
  tests/test_injection_defense.py tests/test_pii_dlp.py tests/test_guardrail_framework.py \
  tests/test_audit_log.py tests/test_immutable_audit.py tests/test_pipeline_rebuild_api.py -q
```

A passing run proves the cited behaviour on the test configuration. It does **not** prove
resistance to an adaptive attacker, and the tests are not an accreditation artifact.

## Validated controls (summary)

| Control | Shipped default | Evidence | Residual limitation |
| --- | --- | --- | --- |
| API key + OIDC/JWT authentication | Off (`api.require_api_key: false`, `identity.enabled: false`) | `test_identity.py`, `test_security_qualification.py` | Open by default; must be enabled before shared exposure |
| RBAC capabilities per role | Off (`access_control.enabled: false`) | `test_identity.py`, `test_security_qualification.py` | Unknown key gets `admin` when enabled with shipped roles unless `default_role` is lowered |
| Tenant isolation (cache/history/audit/experiments) | Off (`tenants.enabled: false`) | `test_tenancy.py`, `test_security_qualification.py` | `X-Tenant-ID` is trusted from any caller - finding F-01 / #223 |
| Permission-aware retrieval (ACL filtering) | Off (`acl.enabled: false`) | `test_acl_retrieval.py` | Only documents carrying ACL metadata are constrained by it |
| Prompt-injection guardrail | Off; `profile: standard` is a one-line opt-in | `test_injection_defense.py`, `test_guardrail_profiles.py` | Heuristic detection; paraphrase/encoding can evade (F-03) |
| PII detection/redaction | Off (`observability.pii.enabled: false`) | `test_pii_dlp.py`, `test_national_id_redaction.py` | Regex classes plus optional NER; not a DLP product |
| Trace/audit/config redaction | Redaction on for traces; config secrets stripped | `test_redaction_config.py`, `test_api_introspection.py`, `test_security_qualification.py` | Custom configs can add unredacted free-text fields |
| Immutable audit trail | Off (`config/audit.yaml` enabled: false) | `test_immutable_audit.py`, `test_audit_log.py` | In-memory by default; purge requires `governance` capability |
| Admin/rebuild operations | Rebuild disabled; RBAC capability required | `test_pipeline_rebuild_api.py`, `test_security_qualification.py` | Governance override needs explicit per-request opt-in |
| Bounded input | `guardrails.max_query_chars: 8000`, batch caps | `test_query_length_guard.py`, `test_batch_query_api.py` | No rate limiting/quota - F-04 / #224 |

## Findings

Severity reflects impact **if the affected control is in the deployed configuration**;
most findings below require the adopter to expose a demo default or add a front door.

| ID | Finding | Severity | Exploitability | Status | Owner | Evidence / link |
| --- | --- | --- | --- | --- | --- | --- |
| F-01 | Tenant selection trusts `X-Tenant-ID` from any caller; it wins over the JWT tenant claim and API-key mapping, so an authenticated caller can select another configured tenant | High | Low-privilege authenticated caller in a multi-tenant deployment | **Tracked** (not fixed here) | bot-uni | #223; `core/services/tenancy.py`; workaround below |
| F-02 | Secure-by-default gap: auth, RBAC, tenancy, ACL and guardrails are all off in shipped configs (intentional for local demo) | High if exposed | Internet-facing demo deployment left as shipped | **Accepted** (documented, not hidden) | maintainer | [deployment playbook](../deployment.md), [adoption checklist](../adoption/checklist.md) |
| F-03 | Injection detection is weighted heuristics; a motivated attacker can paraphrase, encode or split a payload to stay under threshold | Medium | Caller who can send queries or poison retrieved documents | **Accepted** (defense in depth; classifier extension point) | bot-uni | `core/implementations/injection_guardrail.py`, `test_injection_defense.py` |
| F-04 | No application-layer rate limiting or per-caller quota; only per-request bounds and tenant budget caps | Medium | Any caller with `query` capability | **Tracked** | bot-uni | #224; T-DOS-1 |
| F-05 | CodeQL is advisory (not a required check); no dependency-audit or container-image scan gate in CI | Medium | Supply-chain regression merging with an open alert | **Tracked** | bot-uni | #225; scanning table below |
| F-06 | `pytest==9.0.2` is affected by GHSA-6w46-j5rx-g56g (dev/test dependency, vulnerable tmpdir handling) | Medium | Local/CI test execution with untrusted tmp content | **Mitigated** in this PR (9.0.3) | bot-uni | Dependabot alert 1-3; `requirements.txt`, `pyproject.toml` |
| F-07 | Run history, approvals and audit are in memory by default; restart loses evidence and a host compromise can rewrite it | Medium (integrity/availability) | Operator failure or host compromise | **Tracked** | bot-uni | #206; `docs/production-readiness.md` §1 |
| F-08 | API keys and SCIM tokens are static shared secrets compared as plain strings; no rotation, hashing or KMS integration | Medium | Credential leakage via environment or file read | **Accepted** (TLS + secret manager + rotation required) | adopter | `config/identity.yaml`, `docs/deployment.md` |
| F-09 | No independent penetration test, code audit or certification has been performed | Informational | — | **Not performed** | maintainer | This document, external assessment section |
| F-10 | Audit purge is a single-principal operation for the `governance` role; no dual control or immutable external anchor | Low | Privileged insider | **Accepted** (hash chain + export/verify available) | maintainer | `test_immutable_audit.py` |
| F-11 | `/metrics` is unauthenticated by design (scraper path) and may reveal tenant/denial/failure labels | Low | Network observer with reach to the port | **Accepted** (restrict at network layer) | adopter | `app/ops_api.py`, `docs/deployment.md` |
| F-12 | Redaction coverage depends on configuration; custom free-text fields added by an adopter are not automatically classified | Low | Misconfiguration | **Accepted** | adopter | [observability config](../architecture.md#9-observability-strategy) |

### F-01 workaround (until #223 lands)

If more than one tenant is served by a directly reachable API:

1. **Strip `X-Tenant-ID` at the ingress gateway** and map tenants to API keys
   (`tenants.api_keys`) or JWT tenant claims; or
2. run one tenant per deployment.

Do not rely on tenancy alone as an authorization boundary while F-01 is open. ACL
filtering (`acl.enabled`) still constrains document visibility per identity and is
independent of the tenant header, but it does not protect tenant-scoped operational
history.

## Dependency, container and secret scanning

State of the repository as configured on 2026-11-15 (not an endorsement of coverage):

| Scanner | Runs | Required gate? | Current state |
| --- | --- | --- | --- |
| CodeQL default setup (python, actions; weekly + on push/PR) | GitHub Actions (dynamic default setup) | **No** - advisory check | Configured; 0 open code-scanning alerts at assessment time |
| Dependabot alerts | GitHub repository setting | **No** | Enabled; 3 open alerts, all GHSA-6w46-j5rx-g56g (pytest), fixed by this PR |
| Dependabot security updates | GitHub repository setting | n/a | **Disabled**; no automatic fix PRs |
| Dependabot version updates | Repository `.github/dependabot.yml` | n/a | Added in this PR (pip + github-actions, weekly) |
| Secret scanning + push protection | GitHub repository setting | Push protection blocks new provider tokens | **Enabled**; non-provider patterns and validity checks disabled |
| Dependency audit (pip-audit / SCA) | — | — | **Not run** (#225) |
| Container image scan (Trivy/Grype/Snyk) | — | — | **Not run**; deploy-smoke builds an image without scanning (#225) |
| SBOM generation / image signing / provenance attestation | — | — | **Not run** |
| IaC scanning (Helm/Kustomize) | — | — | **Not run** |

CI jobs that do run: ruff, mypy, pytest on 3.11/3.13, deploy smoke (Helm/Kustomize
render + image health), eval regression gates, and CodeQL/secret scanning at the
platform level. See [`docs/engineering-lifecycle.md`](../engineering-lifecycle.md) for
required vs advisory checks.

## External assessment

**Not performed.** No third-party penetration test, red-team exercise, code audit or
certification has been commissioned or received. No date or scope exists to cite. The
evidence in this package is first-party automated testing only; treat it as input to an
adopter's review, not a replacement.

If an external assessment is performed later, record scope, tester, date and report
location here, and re-map findings to this table.

## Reporting a vulnerability

Follow [`SECURITY.md`](../../SECURITY.md): use GitHub private vulnerability reporting
on the repository Security tab. Do not open a public issue with exploit details.
Response is best-effort by the maintainer; no SLA or bug bounty is offered.

## Known limitations of this package

- Tests use dummy providers for speed and determinism; they exercise control flow and
  data exposure, not model behaviour or provider-side isolation.
- The package does not test network topology, TLS configuration, IdP policy, cloud IAM,
  Kubernetes admission control, or the security of the adopter's data connectors.
- Load and multi-replica correctness are covered separately (#197 harness, #206 open);
  they are not security evidence.
- Findings marked **Accepted** are deliberate trade-offs. They remain risks; they are not
  "passed".
