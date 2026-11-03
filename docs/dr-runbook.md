# Disaster Recovery Runbook (G6)

## Objectives
- **RPO**: 60 minutes (configurable in `config/dr.yaml`)
- **RTO**: 120 minutes (configurable in `config/dr.yaml`)

## Topology
Multi-region with primary/secondary. Residency routing controlled by `config/residency.yaml`. 
Failover mode defaults to **manual** for safety.

## Backup
1. Back up persistent store (BaseStore) - SQLite/Postgres snapshots
2. Back up audit JSONL and immutable audit store
3. Back up `config/**` (git is source of truth; tag releases)
4. Back up artifacts if enabled

Run via documented procedures; automate in future per schedule.

## Restore
1. Provision secondary region infrastructure (Terraform modules)
2. Restore data to secondary (verify integrity)
3. Update DNS/routing or apply residency failover
4. Validate with `/health`, `/ready`, smoke tests
5. Update DR status and document in audit

## Failover
- Health checks on `/ready` 
- Promote secondary (manual approval required by default)
- Update residency routing (`config/residency.yaml`)
- Monitor via Prometheus/Grafana/OTel

## Verification
Run restore tests per schedule. Track in runbook checklist.

## References
- `config/residency.yaml`, `config/dr.yaml`
- `core/services/base_store.py`, `core/services/store_backends.py`
- `docs/deployment.md`, G5 GitOps
