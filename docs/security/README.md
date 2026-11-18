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
| Tenant isolation (cache/history/audit/experiments) | Off (`tenants.enabled: false`) | `test_tenancy.py`, `test_tenant_header_binding.py`, `test_security_qualification.py` | Binding requires `identity.enabled`; identity-disabled tenancy remains gateway-trust (see F-01) |
| Permission-aware retrieval (ACL filtering) | Off (`acl.enabled: false`) | `test_acl_retrieval.py` | Only documents carrying ACL metadata are constrained by it |
| Prompt-injection guardrail | Off; `profile: standard` is a one-line opt-in | `test_injection_defense.py`, `test_guardrail_profiles.py` | Heuristic detection; paraphrase/encoding can evade (F-03) |
| PII detection/redaction | Off (`observability.pii.enabled: false`) | `test_pii_dlp.py`, `test_national_id_redaction.py` | Regex classes plus optional NER; not a DLP product |
| Trace/audit/config redaction | Redaction on for traces; config secrets stripped | `test_redaction_config.py`, `test_api_introspection.py`, `test_security_qualification.py` | Custom configs can add unredacted free-text fields |
| Immutable audit trail | Off (`config/audit.yaml` enabled: false) | `test_immutable_audit.py`, `test_audit_log.py` | In-memory by default; purge requires `governance` capability |
| Admin/rebuild operations | Rebuild disabled; RBAC capability required | `test_pipeline_rebuild_api.py`, `test_security_qualification.py` | Governance override needs explicit per-request opt-in |
| Bounded input | `guardrails.max_query_chars: 8000`, batch caps, `api.rate_limit` token bucket + in-flight cap | `test_query_length_guard.py`, `test_batch_query_api.py`, `test_rate_limits.py` | Rate limits are process-local and off by default - #224 |

## Findings

Severity reflects impact **if the affected control is in the deployed configuration**;
most findings below require the adopter to expose a demo default or add a front door.

| ID | Finding | Severity | Exploitability | Status | Owner | Evidence / link |
| --- | --- | --- | --- | --- | --- | --- |
| F-01 | Tenant selection trusted `X-Tenant-ID` from any caller, so an authenticated caller could select another configured tenant | High | Low-privilege authenticated caller in a multi-tenant deployment | **Fixed** (#223): claim/key binds; contradiction → 403 unless allowlisted | bot-uni | #223; `core/services/tenancy.py`; `tests/test_tenant_header_binding.py`; residual below |
| F-02 | Secure-by-default gap: auth, RBAC, tenancy, ACL and guardrails are all off in shipped configs (intentional for local demo) | High if exposed | Internet-facing demo deployment left as shipped | **Accepted** (documented, not hidden) | maintainer | [deployment playbook](../deployment.md), [adoption checklist](../adoption/checklist.md) |
| F-03 | Injection detection is weighted heuristics; a motivated attacker can paraphrase, encode or split a payload to stay under threshold | Medium | Caller who can send queries or poison retrieved documents | **Accepted** (defense in depth; classifier extension point) | bot-uni | `core/implementations/injection_guardrail.py`, `test_injection_defense.py` |
| F-04 | No application-layer rate limiting or per-caller quota; only per-request bounds and tenant budget caps | Medium | Any caller with `query` capability | **Tested** | bot-uni | #224; T-DOS-1; `api.rate_limit` off by default, process-local |
| F-05 | CodeQL was advisory (not a required check); no dependency-audit or container-image scan gate in CI | Medium | Supply-chain regression merging with an open alert | **Fixed** (#225): CodeQL, pip-audit and Trivy are required; waivers are explicit and expiring | bot-uni | #225; scanning table and waiver policy below |
| F-06 | `pytest==9.0.2` is affected by GHSA-6w46-j5rx-g56g (dev/test dependency, vulnerable tmpdir handling) | Medium | Local/CI test execution with untrusted tmp content | **Mitigated** in this PR (9.0.3) | bot-uni | Dependabot alert 1-3; `requirements.txt`, `pyproject.toml` |
| F-07 | Run history, approvals and audit are in memory by default; restart loses evidence and a host compromise can rewrite it | Medium (integrity/availability) | Operator failure or host compromise | **Tracked** | bot-uni | #206; `docs/production-readiness.md` §1 |
| F-08 | API keys and SCIM tokens are static shared secrets compared as plain strings; no rotation, hashing or KMS integration | Medium | Credential leakage via environment or file read | **Accepted** (TLS + secret manager + rotation required) | adopter | `config/identity.yaml`, `docs/deployment.md` |
| F-09 | No independent penetration test, code audit or certification has been performed | Informational | — | **Not performed** | maintainer | This document, external assessment section |
| F-10 | Audit purge is a single-principal operation for the `governance` role; no dual control or immutable external anchor | Low | Privileged insider | **Accepted** (hash chain + export/verify available) | maintainer | `test_immutable_audit.py` |
| F-11 | `/metrics` is unauthenticated by design (scraper path) and may reveal tenant/denial/failure labels | Low | Network observer with reach to the port | **Accepted** (restrict at network layer) | adopter | `app/ops_api.py`, `docs/deployment.md` |
| F-12 | Redaction coverage depends on configuration; custom free-text fields added by an adopter are not automatically classified | Low | Misconfiguration | **Accepted** | adopter | [observability config](../architecture.md#9-observability-strategy) |

### F-01 remediation and residual risk (fixed in #223)

With `identity.enabled: true`, the JWT `tenant` claim (or `tenants.api_keys`
mapping for a service account) binds the request. `X-Tenant-ID` may only differ
when the caller's RBAC role or key is allowlisted in
`tenants.header_override`; otherwise the API returns `403
forbidden_tenant_scope` and records a `tenant/tenant_override` audit event.
Unknown tenants remain `400 unknown_tenant`.

Residual risk: `identity.enabled: false` keeps the legacy trusted-gateway
ordering (header wins). In that mode, only expose the API behind an ingress that
strips or authoritatively sets `X-Tenant-ID`, or run one tenant per deployment.
ACL filtering (`acl.enabled`) constrains document visibility independently but
does not protect tenant-scoped operational history.

### F-04 remediation and residual risk (fixed in #224)

`api.rate_limit` adds a process-local token bucket plus in-flight cap at the API
edge. It returns a standard `429 rate_limited` envelope with `Retry-After` and
increments `genai_rate_limit_events_total{scope,reason,tenant}`. Buckets can be
isolated by API key, tenant, role, subject or client IP; identity/API-key values
are hashed before use. It ships disabled so local/demo behaviour is unchanged.
A batch query consumes one token, while `max_batch_size` and `batch_max_workers`
still bound work inside that request; tenant `budget_cap_usd` remains a separate
post-hoc spend guard. Each replica enforces its own limit, so a gateway/WAF is
still responsible for global edge protection and distributed quotas.
`tests/test_rate_limits.py` exercises within-limit requests, per-key/tenant
isolation, 429/Retry-After, the in-flight cap, disabled mode and the metric.

## Dependency, container and secret scanning

State of the repository as configured on 2026-11-17 after #225 (not an endorsement of
coverage; the 2026-11-15 assessment is preserved in the git history):

| Scanner | Runs | Required gate? | Current state |
| --- | --- | --- | --- |
| CodeQL default setup (python, actions; weekly + on push/PR) | GitHub Actions (dynamic default setup) | **Yes** - `CodeQL` context | Configured; `Analyze (python)` / `Analyze (actions)` are sub-checks, not separate required contexts |
| Dependabot alerts | GitHub repository setting | n/a | Enabled by the repository setting; advisory alerts do not carry a CI check name |
| Dependabot security updates | GitHub repository setting | n/a | **Enabled** (#225); fix PRs are automated for supported ecosystems |
| Dependabot version updates | `.github/dependabot.yml` | n/a | Weekly Monday, grouped pip + github-actions, `open-pull-requests-limit: 5` |
| Secret scanning + push protection | GitHub repository setting | Push protection blocks new provider tokens | Provider-pattern scanning + push protection enabled; non-provider patterns and validity checks remain disabled (requested via API in #225, readback stayed disabled - repository-plan limitation) |
| Dependency audit (pip-audit / SCA) | `SCA (pip-audit)` CI job | **Yes** | Audits all four `requirements*.txt`; JSON report uploaded; advisories must be waived in `security/waivers.yml` |
| Container image scan (Trivy) | `Image scan (Trivy)` CI job | **Yes** | Builds `deployment/Dockerfile`, fails on fixable HIGH/CRITICAL OS/library CVEs; JSON report uploaded |
| SBOM generation / image signing / provenance attestation | — | n/a | **Not performed** |
| IaC scanning (Helm/Kustomize) | — | n/a | **Not performed** |

CI jobs that do run: ruff, mypy, pytest on 3.11/3.13, deploy smoke (Helm/Kustomize
render + image health), eval regression gates, SCA, image scan, and CodeQL/secret scanning
at the platform level. Only the seven checks listed in
[`docs/engineering-lifecycle.md`](../engineering-lifecycle.md) block a merge; Deploy smoke
and Eval gates remain explicitly advisory with the maintainer as owner.

### Scanner waiver policy

`security/waivers.yml` is versioned with `version: 1`; it currently contains three expiring
image-scan waivers from #225 and starts empty for new deployments. Each entry must provide
`id` (GHSA/CVE/PYSEC), `package`, `reason` (at least 20 characters),
`expires` (future ISO date), `owner` and `approved_by`. Unknown fields, duplicate IDs,
malformed IDs and expired waivers fail the gate before either scanner runs.

`python -m app.supply_chain ignores --format pip-audit` emits IDs for `pip-audit
--ignore-vuln`; `--format trivy` emits the same IDs into `.trivyignore`. A waiver suppresses
only the CI gate for the named scanner - it does not close the GitHub advisory/alert, erase
the report artifact, or change the finding status in this document. Trivy ignores unfixed
CVEs (`ignore-unfixed: true`) and scans HIGH/CRITICAL by design; MEDIUM/LOW and unfixed
findings are visible in the uploaded JSON report but do not fail the gate. Scanner configs
contain no tokens or secrets: pip-audit uses the public OSV API and Trivy uses its public
database and the default GitHub token supplied by the action runner.

The first #225 image-scan run found HIGH CVEs in the Debian base packages (`zlib1g`) and
build-tool dependencies (`setuptools`, `wheel`, `jaraco.context`). Base packages are now
refreshed and corrected standalone tool versions are pinned in
`deployment/Dockerfile`. Three remaining HIGH results come from stale SBOM entries and
vendored metadata inside setuptools, not standalone runtime dependencies; they are explicitly
waived until `2027-02-15` in `security/waivers.yml` (owner/approver `bot-uni`, with maintainer
review requested on #225). The expiry forces re-evaluation. A future finding must be fixed or
explicitly waived; a green gate without either is not acceptable evidence.

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
