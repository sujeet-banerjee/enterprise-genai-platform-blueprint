# Multi-replica qualification evidence

Status: **PASS**

Bounded single-host qualification for selected shared state only. This is not an HA, DR, performance or global-consistency claim.

## Provenance

| Field | Value |
| --- | --- |
| qualification_id | single-host-two-replica-shared-store-v1 |
| timestamp_utc | 2026-11-18T05:58:31.474904+00:00 |
| git_sha | fdc7c733ff062efbd4d14809d05cb783688ecf5a |
| platform | Linux-6.18.58.1-microsoft-standard-WSL2-x86_64-with-glibc2.43 |
| python | 3.13.15 |
| backend | sqlite |
| replica_count | 2 |
| config_sha256 | eb66ba6cbd33a951261d0a5c9cb1e13c5b7906ce83dcabb4aa6563412b890f8c |

## Profile

| Field | Value |
| --- | --- |
| backend | sqlite |
| identity_mode | trusted X-Tenant-ID header |
| replicas | 2 |
| request_pattern | sequential low-concurrency qualification |
| store_path | env:GENAI_QUALIFICATION_STORE |
| topology | two uvicorn processes, shared SQLite file on one host |

## Checks

| Check | Result | Detail |
| --- | --- | --- |
| persistence_secret_reference_resolved | PASS | backend=sqlite path=/tmp/genai-multi-replica-_ujrzuib/store.db |
| both_replicas_ready | PASS | A=True B=True |
| retrieval_acl_tenant_isolation | PASS | status=200 docs=['ACME internal runbook: rotate the acme service key every 30 days.'] |
| cross_tenant_retrieval_denied | PASS | status=200 docs=['Beta research note: quarterly retrieval quality experiment.'] |
| trace_visible_on_other_replica | PASS | status=200 request_id=qual-acme-query |
| cross_tenant_trace_denied | PASS | status=404 |
| spend_visible_on_other_replica | PASS | status=200 window={'window_size': 1000, 'requests': 1, 'total_cost_usd': 0.000199, 'mean_cost_usd': 0.000199, 'tenant': 'acme'} |
| experiment_status_visible_on_other_replica | PASS | launch=202 status=completed |
| cross_tenant_experiment_denied | PASS | status=404 |
| audit_event_visible_on_other_replica | PASS | status=200 events=1 |
| cache_tenant_key_isolation | PASS | hits=False,True,False |
| restart_recovery | PASS | restarted=True status=200 |

12/12 checks passed.

## Shared state in scope

- run_history
- trace_lookup
- spend_and_tenant_scoping
- audit_events
- experiment_status
- eval_trends

## Explicitly unsupported in this profile

| State | Limit |
| --- | --- |
| response_cache | Process-local; tenant-scoped keys only, no cross-replica sharing. |
| rate_limits | Process-local token buckets; external gateway/WAF required globally. |
| approvals | In-memory queue; not durable across restarts. |
| scim_directory | In-memory directory; external IdP required for multi-replica writes. |
| pipeline_rebuild | Swaps pipeline state in one process only; no cross-replica broadcast. |
| prometheus_counters | Per-process exposition; aggregate by scraping all replicas. |
| immutable_audit_jsonl | Multi-writer file sink requires separate single-writer qualification. |
