# Production-readiness gap assessment

> **This is an assessment, not a certification.** It states, with evidence, where the
> reference implementation stands against the operational expectations of an enterprise
> production deployment. It does **not** claim the project is production-certified, and it
> does **not** claim that the shipped Kubernetes manifests alone are sufficient for production.
> Assessed **2026-11-14** against `main` @ `df88aa2`.

Companion documents: [capability status](capability-status.md) answers *what exists*; the
[security qualification package](security/README.md) records the threat model, abuse-case
matrix and open findings;
this document answers *what it takes to run it for real*. The
[deployment playbook](deployment.md) covers *how to deploy it*; the
[DR runbook](dr-runbook.md) covers recovery procedures.

## Status vocabulary

| Status | Meaning |
| --- | --- |
| **Implemented** | Shipped and wired, with tests exercising the real path. |
| **Partial** | A meaningful subset works; a named capability is missing or only partly validated. |
| **Unvalidated** | Built but not proven under realistic conditions (load, failover, adversarial, multi-replica). |
| **Planned** | Not implemented; tracked by an open issue. |

An interface, manifest or runbook is not production readiness. A passing test suite proves
behaviour on a single reference node, not capacity, certification or regulatory fitness.

## Summary and operational risk ranking

| # | Area | Status | Risk | Primary next step |
| --- | --- | --- | --- | --- |
| 1 | Durable/shared persistence | Partial → qualified profile | Medium-High | Adopt a shared backend as the default for multi-replica deployments; declare the optional Postgres driver (#206). |
| 2 | Multi-replica consistency & coordination | Qualified (bounded) | Medium | Extend evidence to Postgres/multi-node; add PDB/NetworkPolicy and a rebuild broadcast story (#206). |
| 5 | Security testing & independent validation | Partial | **High** | Independent validation; CodeQL/SCA/image gates landed in #225. |
| 4 | Authn/authz & tenant isolation | Implemented | Medium | Adversarial multi-tenant validation; ship a hardening profile on by default. |
| 6 | Load/performance & SLOs | Partial | Medium | Define SLOs from real baselines; soak and autoscaling tests on target hardware. |
| 7 | Resilience, backup/restore & DR | Partial | Medium | Execute and automate failover/restore drills; wire cross-region replication (#71). |
| 3 | Deployment topology, secrets & environments | Implemented | Medium | Secret-manager integration + rotation; automate config promotion. |
| 8 | Monitoring, alerting & runbooks | Implemented | Low-Medium | Map every alert to a runbook; long-term metrics storage and SLO burn alerts. |

Risk reflects blast radius and the likelihood of silent failure in production, not effort.

---

## 1. Durable and shared persistence

**Current behaviour.** A backend-agnostic `BaseStore` (`core/services/base_store.py`) with
in-memory (default), SQLite and Postgres backends (`core/services/store_backends.py`) is
wired into run history and traces (`app/ops_api.py`), eval trends, experiments
(`app/evaluation_api.py`) and the audit logger (`core/services/audit_log.py`). The backend
is selected by `config/persistence.yaml`, whose shipped default is `backend: memory`.
Export/verify/restore helpers live in `core/services/backup_restore.py`.

**Evidence.** `config/persistence.yaml`, `core/services/base_store.py`,
`core/services/store_backends.py`, `tests/test_backup_restore.py`,
`tests/test_cross_region_persistence.py`, `tests/test_immutable_audit.py`,
`deployment/multi-replica/`, `docs/benchmarks/multi-replica.md`,
`benchmarks/multi_replica/run_qualification.py`.

**Gaps.**
- The default is still process-local memory: state is lost on restart and is not shared between
  replicas unless `persistence.yaml` is changed.
- The qualified profile uses one SQLite file on one host; it is not evidence for concurrent
  cross-replica writers or multi-node filesystems.
- The **approval queue is in-memory only** (`core/services/approval.py` keeps a plain dict);
  it is not backed by `BaseStore`, so pending approvals do not survive a restart.
- The Postgres backend imports `psycopg2` lazily but **`psycopg2` is not declared** in
  `pyproject.toml` or any `requirements*.txt`; enabling it requires installing the driver
  out of band.
- Prometheus metrics and the response cache are in-process (no remote write / shared cache).

**Impact.** The selected shared read paths are now qualified for a bounded two-replica profile,
but the shipped single-replica memory default, approvals and process-local utilities still require
operator action before scaling out.

**Recommended next step.** Adopt a shared backend as the default for multi-replica deployments,
declare the Postgres driver as an optional extra, back the approval queue with `BaseStore`, and
document the single-replica default explicitly. Tracked by **#206** (durable multi-replica
deployment profile); the bounded profile and evidence are in place.

**Status: Partial.**

## 2. Multi-process and multi-replica consistency and coordination

**Current behaviour.** The Helm chart can run multiple API replicas behind a Service and
scale with HPA and KEDA (`deployment/helm/genai-platform/templates/hpa.yaml`,
`keda-scaledobject.yaml`). Configuration is read once per process at startup.

**Evidence.** `deployment/helm/genai-platform/`, `tests/test_deployment_ha.py`,
`app/main.py` (per-process lifespan state), `deployment/multi-replica/`,
`benchmarks/multi_replica/run_qualification.py`, `docs/benchmarks/multi-replica.md`.

**Gaps.**
- No leader election, distributed lock or coordination primitive.
- Response cache, `config_revision`, approval queue, SCIM directory and Prometheus counters are
  per-process and not reconciled across replicas.
- `POST /v1/pipeline:rebuild` swaps the pipeline **in one process**; other replicas keep
  serving the old revision until restarted or rebuilt independently.
- No PodDisruptionBudget or NetworkPolicy in the chart (no disruption budget or default-deny
  network posture).

**Impact.** The gap is now qualified as a bounded two-process profile: shared traces, spend,
experiments, audit and eval trends are verified across two processes, but caches, rebuilds and
approvals still require an external coordination story.

**Recommended next step.** Extend the harness to Postgres and multi-node, add a documented
coordination story for rebuilds/caches/approvals, and add PDB/NetworkPolicy to the chart.
Tracked by **#206** and the broader HA roadmap.

**Status: Unvalidated.**

## 3. Deployment topology, secrets, configuration and environment separation

**Current behaviour.** A hardened multi-stage, non-root container with a healthcheck
(`deployment/Dockerfile`), a single-node Compose profile, a Helm chart, Kustomize base +
dev/staging/prod overlays, an Argo CD example and Terraform modules
(`deployment/terraform/modules/{aws,azure,gcp,storage,secrets,cluster-addons}`). Config is
fail-fast validated at startup (`core/config/validator.py`) and supports `${VAR}` / `env:VAR`
secret interpolation (`core/config/secrets.py`); Kubernetes deployments can mount a config
ConfigMap and an `existingSecret`.

**Evidence.** `deployment/`, `docs/deployment.md`, `core/config/`,
`tests/test_deployment_gitops.py`, `tests/test_config_validation.py`,
`tests/test_deployment_artifacts.py`.

**Gaps.**
- No Vault / cloud secret-manager integration and no automated secret rotation; secrets are
  injected as environment variables from a Kubernetes Secret or `.env`.
- Config promotion (dev → staging → prod) is documented but not automated end to end.
- Container image signing / SBOM / provenance attestation are not implemented.
- NetworkPolicy and PodDisruptionBudget are absent (see area 2).

**Impact.** Deployments are reproducible and config is validated, but secret lifecycle
(rotation, audit) and supply-chain provenance rely on external process.

**Recommended next step.** Add a secret-manager backend and rotation guidance; emit an SBOM
and sign images in CI. The base deployment path is sound and does not block a pilot.

**Status: Implemented.**

## 4. Authentication, authorization and tenant-isolation validation

**Current behaviour.** OIDC/JWKS verification with group→role mapping, SCIM user/group sync
and service-account keys (`core/services/identity.py`); capability-based RBAC
(`core/services/access_control.py`); a tenant resolver with per-tenant policy
(`core/services/tenancy.py`); per-request attribution (`core/services/attribution.py`); and
permission-aware retrieval with AND-semantics ACL filtering before reranking/prompting
(`core/services/acl.py`); and a config-driven API token bucket plus in-flight cap with a
standard `429 rate_limited` envelope (`core/services/rate_limit.py`, `app/main.py`).

**Evidence.** `tests/test_identity.py`, `tests/test_rbac_access_control.py`,
`tests/test_tenancy.py`, `tests/test_attribution.py`, `tests/test_acl_retrieval.py`,
`tests/test_rate_limits.py`,
`config/{identity,access_control,tenants,attribution,acl,api}.yaml`.

**Gaps.**
- **All five controls default to disabled** (`enabled: false`) to preserve legacy behaviour;
  a production deployment must turn them on and verify the combination.
- Isolation is covered by unit and API tests but not by adversarial, concurrent, multi-tenant
  testing; there is no independent review of the isolation model.
- Native SAML is not implemented (OIDC only); tenant isolation depends on correct header/JWT
  handling that is tested but not fuzz-tested.
- `api.rate_limit` is process-local and off by default; a gateway/WAF is still needed for
  distributed quotas and global edge protection.

**Impact.** The controls are real and tested individually, but their *combined* posture under
hostile input and concurrency is **not independently validated**.

**Recommended next step.** Publish a hardened profile that enables identity + RBAC + tenancy
+ ACL together, and add adversarial isolation tests; independent validation is tracked by
**#205**.

**Status: Implemented.**

## 5. Security testing, threat modelling and independent validation

**Current behaviour.** CodeQL (default setup), Dependabot alerts, Dependabot security
updates, secret scanning/push protection, `SCA (pip-audit)` and `Image scan (Trivy)` run on
the repository; CodeQL plus the two scanner jobs join `ruff`, `mypy` and the two pytest
matrix jobs as required checks (#225). Runtime defenses include prompt-injection/jailbreak
defense and PII/DLP guardrails (`core/implementations/injection_guardrail.py`,
`pii_guardrail.py`), input redaction before prompting (`app/pipeline.py`), immutable
hash-chained audit (`core/services/audit_store.py`) and secret redaction in logs/traces.

**Evidence.** `.github/workflows/ci.yml`, `.github/dependabot.yml`,
`security/waivers.yml`, `app/supply_chain.py`, `tests/test_supply_chain_gates.py`,
`tests/test_injection_defense.py`, `tests/test_pii_dlp.py`, `tests/test_input_redaction.py`,
`tests/test_immutable_audit.py`.

**Gaps.**
- **No independent penetration test**, code audit or certification (#205 F-09).
- No SBOM, image signing or provenance attestation; Trivy ignores unfixed CVEs.
- IaC scanning (Helm/Kustomize) and MEDIUM/LOW image advisories are reported but do not fail.
- The guardrail and identity defaults are off (area 4), so the shipped posture is permissive
  until configured.

**Impact.** High: the threat model, abuse-case matrix and supply-chain gates are first-party
evidence, but the posture has not been challenged by an independent assessment. Unit tests
and scanners are not a penetration test.

**Recommended next step.** Enable identity so the identity-bound tenant selection from
**#223** applies (identity-disabled tenancy remains gateway-trust), commission independent
validation, and add SBOM/signing/provenance when the delivery chain needs them. The threat
model and findings landed with **#205**; required CodeQL/SCA/image gates landed with **#225**;
no new duplicate issues are opened by this assessment.

**Status: Partial.**

## 6. Load, performance, capacity and SLOs

**Current behaviour.** A bounded, client-agnostic load harness
(`core/evaluation/load_harness.py`, CLI `benchmarks/load/run_load.py`) drives HTTP requests
and reports latency percentiles, throughput, error rate and per-stage latency. Committed
reference numbers and methodology live in `docs/benchmarks/load.md` /
`load-methodology.md`.

**Evidence.** `core/evaluation/load_harness.py`, `benchmarks/load/run_load.py`,
`tests/test_load_harness.py`, `docs/benchmarks/`.

**Gaps.**
- The published numbers are **single-node reference CPU baselines** and are explicitly not
  capacity or SLO claims.
- No SLOs are defined (no targets, error budgets or burn-rate alerts).
- No soak/long-duration test, no capacity model, and no load validation of autoscaling.
- Latency depends on the model backend; no per-backend capacity guidance is published.

**Impact.** The harness makes measurement reproducible, but there is no agreed target to
measure against, so "is it fast enough?" cannot yet be answered for a given deployment.

**Recommended next step.** Define SLOs and alert thresholds from measured baselines, run a
soak test and an autoscaling test on representative hardware, and publish per-backend
guidance.

**Status: Partial.**

## 7. Resilience, backup/restore and disaster recovery

**Current behaviour.** Retries, circuit breakers and an ordered provider failover chain
(`core/services/resilience.py`, default off). Backup export/verify/restore with SHA-256
checksums (`core/services/backup_restore.py`). Multi-region/residency and DR configuration
(`config/residency.yaml`, `config/dr.yaml`) with a runbook (`docs/dr-runbook.md`) and
Terraform environments (`deployment/terraform/environments/multi-region`).

**Evidence.** `core/services/resilience.py`, `core/services/backup_restore.py`,
`tests/test_resilience.py`, `tests/test_backup_restore.py`, `tests/test_dr_chaos.py`,
`tests/test_multi_region_dr.py`, `docs/dr-runbook.md`.

**Gaps.**
- Provider resilience is **off by default** and, when on, routing is an ordered fallback
  chain (no cost/latency-aware routing).
- Failover is **manual** by default; there is no automated, executed failover drill.
- Cross-region replication is a **config signal**, not an active replication mechanism;
  RPO/RTO values are declared, not measured.
- Chaos tests are in-process and do not exercise a real multi-region topology.

**Impact.** Recovery is documented and the data path supports verified restore, but the
end-to-end failover has not been drilled against real infrastructure.

**Recommended next step.** Run and record a failover + restore drill, automate restore
verification, and implement real cross-region replication. Tracked by **#71** (multi-region
DR) and **#206**.

**Status: Partial.**

## 8. Operational monitoring, alerting and runbooks

**Current behaviour.** In-process traces, failure taxonomy and `/v1/metrics`
(`app/ops_api.py`); Prometheus `/metrics` with a Grafana dashboard pack and alert rules
(`deployment/observability/`); OpenTelemetry OTLP export (optional extra). Operational
procedures live in `docs/deployment.md` (health/readiness, upgrade/rollback, backup/restore)
and `docs/dr-runbook.md`.

**Evidence.** `core/services/telemetry.py`, `deployment/observability/prometheus/alerts.yml`,
`deployment/observability/grafana/dashboards/genai-overview.json`,
`tests/test_prometheus_metrics.py`, `tests/test_otel_tracing.py`, `docs/deployment.md`.

**Gaps.**
- Alert thresholds in `alerts.yml` are **illustrative defaults**, not derived from SLOs
  (see area 6); there are no SLO burn-rate alerts.
- No alert-to-runbook mapping and no on-call/escalation definition.
- Metrics are in-process; there is no long-term storage or remote-write configuration in the
  reference pack (Grafana/Prometheus run as a Compose profile for local/demo use).

**Impact.** The observability surface is strong and tested; operationalizing it (targets,
runbooks, retention, on-call) is the remaining gap.

**Recommended next step.** Define SLOs and alert thresholds, map each alert to a runbook, and
document retention/remote-write for a real deployment.

**Status: Implemented.**

---

## Prioritized recommendations

Ordered by operational risk. None of these are new issues; each links to work already tracked.

1. **Before scaling beyond one replica** - move run/trace/experiment/approval state to a
   shared store and declare the Postgres driver as an optional extra; document the
   single-replica default. *(#206, #56)*
2. **Before any external exposure** - run with identity enabled so tenant-header binding
   applies, and commission independent security validation. *(#205 landed the threat model
   and evidence; #223 landed identity-bound tenant selection; #225 landed required
   CodeQL/SCA/image gates)*
3. **Before a pilot** - publish a hardened profile that enables identity + RBAC + tenancy +
   ACL + guardrails together, and add adversarial isolation tests. *(#204, #205)*
4. **Before capacity commitments** - define SLOs from measured baselines, run soak and
   autoscaling tests on target hardware, and publish per-backend guidance.
5. **Before relying on DR** - execute and record a failover + restore drill and implement
   real cross-region replication. *(#71)*
6. **Before hand-off to operations** - map every alert to a runbook, set retention/remote
   write, and define on-call. *(#157/#158 console, #163/#164 HITL)*

## Tracked work (no new issues)

This assessment creates **no duplicate implementation issues**. Every recommendation maps to
work already tracked:

- **[#204](https://github.com/sujeet-banerjee/enterprise-genai-platform-blueprint/issues/204)** - engineering-team adoption / pilot kit (golden paths, hardening profile).
- **[#205](https://github.com/sujeet-banerjee/enterprise-genai-platform-blueprint/issues/205)** - security qualification: threat model and adversarial validation (*landed*; independent assessment still not performed).
- **[#206](https://github.com/sujeet-banerjee/enterprise-genai-platform-blueprint/issues/206)** - durable multi-replica deployment profile.
- **[#71](https://github.com/sujeet-banerjee/enterprise-genai-platform-blueprint/issues/71)** - multi-region / disaster recovery execution.
- **[#43](https://github.com/sujeet-banerjee/enterprise-genai-platform-blueprint/issues/43)** - roadmap umbrella (semantic cache, streaming, real vector backends, behavioral metrics, prompt/model lifecycle, chargeback).
- **[#157](https://github.com/sujeet-banerjee/enterprise-genai-platform-blueprint/issues/157)** / **[#158](https://github.com/sujeet-banerjee/enterprise-genai-platform-blueprint/issues/158)** - remaining UX tranche (bot-win).
- **[#163](https://github.com/sujeet-banerjee/enterprise-genai-platform-blueprint/issues/163)** / **[#164](https://github.com/sujeet-banerjee/enterprise-genai-platform-blueprint/issues/164)** - HITL console on the approval contract.

## What this assessment is not

- It is **not** a certification, an audit opinion or a guarantee of fitness for a regulated
  workload.
- It does **not** assert that the Kubernetes manifests alone constitute production readiness.
- It does **not** introduce new implementation issues; every recommendation maps to existing
  tracked work (**#204**, **#205**, **#206**, **#43**, **#71**, **#157/#158**, **#163/#164**).

## Maintenance

- Re-assess when a high-risk area changes (persistence defaults, security gates, SLOs,
  failover automation) or before a release that claims a new maturity level.
- Keep the summary table's risk ranking and the area statuses consistent with
  [capability-status.md](capability-status.md); `tests/test_production_readiness.py` fails if a
  cited path disappears, an unknown status appears or the tracked issues go missing.
