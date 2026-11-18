# Qualified multi-replica profile (#206)

This profile is a bounded qualification of **two API processes sharing one durable store on a single
host**. It verifies selected shared read paths and tenant isolation; it is not an HA, DR, performance
or global-consistency certification.

## Support matrix

| Capability | Status in this profile | Notes |
|---|---|---|
| Run history / spend window | Shared | `BaseStore` via `config/persistence.yaml` |
| Trace lookup `/v1/traces/{id}` | Shared | Cross-replica read plus tenant-scope denial |
| Experiment status `/v1/experiments/{id}` | Shared | Cross-replica read plus cross-tenant 404 |
| Audit events `/v1/audit` | Shared | Rebuild denial event written with tenant and read from peer |
| Evaluation trends | Shared | Shared store point reads; local fallback only when store has no points |
| Retrieval ACL | Tested | `acl.yaml` enabled; `X-Tenant-ID` scopes corpus |
| Response cache | Process-local | Tenant/app/user are part of the key; no cross-replica sharing |
| Rate limits | Process-local | External gateway/WAF remains responsible globally |
| Approvals | Not durable | In-memory queue; external workflow store required |
| SCIM directory | Not shared | External IdP required for multi-replica writes |
| Pipeline rebuild | Single-process | Swap is not broadcast to peers; deploy config to all replicas |
| Prometheus counters | Per-process | Scrape all replicas and aggregate at the edge |
| Immutable audit JSONL | Not covered | Multi-writer file sink requires separate qualification |
| Postgres backend | Supported but unqualified here | No Postgres runtime evidence generated locally |

## Files

- `config/` — dummy-provider config, ACL/tenancy/audit enabled, persistence from
  `${GENAI_QUALIFICATION_STORE}`.
- `config/documents.json` — two labelled documents for tenant-isolation checks.
- `docker-compose.yml` — two API services sharing a state volume and config mount.

## Run

```bash
python -m app.config_validate --config-dir deployment/multi-replica/config
python benchmarks/multi_replica/run_qualification.py
python benchmarks/multi_replica/run_qualification.py --check docs/benchmarks/multi-replica.json
```

The harness boots two uvicorn processes on free localhost ports, supplies the secret via env, runs the
checks, generates `docs/benchmarks/multi-replica.json` and `docs/benchmarks/multi-replica.md`, and
tears both processes down. It uses dummy providers and needs no model downloads or API keys.

## Compose topology

```bash
docker compose -f deployment/multi-replica/docker-compose.yml up --build
curl -fsS http://localhost:8000/ready
curl -fsS http://localhost:8001/ready
```

Both services mount the same `qualification-state` volume and read-only `config/`. `GENAI_API_KEY`,
JWT secrets and model-provider keys must be injected with `env:` / `${VAR}` references from the
platform secret store; this profile deliberately contains no secret values.

## Boundaries

- Identity is not enabled in the qualification config; `X-Tenant-ID` is gateway-trusted. Enable
  OIDC and restrict `tenants.header_override` for any real multi-tenant deployment.
- Sequential, low-concurrency requests only. SQLite shared-file locking under sustained write load
  is not qualified here.
- Single host only. Cross-node failover, backup/restore and regional replication are separate work.
