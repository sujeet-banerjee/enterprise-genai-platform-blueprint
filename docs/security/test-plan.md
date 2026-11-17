# Security test plan

> Maps every abuse case in [threat-model.md](threat-model.md) to automated evidence, a
> documented control, or an explicitly tracked gap. Passing this plan demonstrates the
> cited behaviour on the test configuration; it is **not** a certification and does not
> replace independent assessment.

Baseline: `main` @ `ca95215` (2026-11-15). Each row names the threat ID, the negative
test(s) that exercise the control, and the residual risk or finding. Tests are cited as
`tests/<file>.py::<function>`; `tests/test_security_docs.py` fails if a cited function
disappears or a threat has no mapping.

## 1. How the evidence is produced

```bash
# New adversarial matrix in this package
python -m pytest tests/test_security_qualification.py -q

# Existing control suites
python -m pytest tests/test_identity.py tests/test_tenancy.py tests/test_acl_retrieval.py \
  tests/test_injection_defense.py tests/test_pii_dlp.py tests/test_guardrail_profiles.py \
  tests/test_audit_log.py tests/test_immutable_audit.py tests/test_pipeline_rebuild_api.py \
  tests/test_query_length_guard.py tests/test_api_introspection.py -q

# Structural consistency between model, plan and findings
python -m pytest tests/test_security_docs.py -q
```

All of the above run on every push/PR through the existing CI test jobs (no new
provider credentials, no network). The new module uses dummy providers so it stays
fast and deterministic; cross-tenant cache/ACL cases use the real embedder fixtures.

## 2. Threat-to-test mapping

| Threat | Automated evidence | Control exercised | Residual / linked finding |
| --- | --- | --- | --- |
| T-AUTH-1 | `tests/test_security_qualification.py::test_alg_none_token_rejected` | Algorithm allowlist, required `exp`/`sub` | PyJWT dependency |
| T-AUTH-2 | `tests/test_security_qualification.py::test_forged_signature_rejected_and_token_not_echoed`, `tests/test_identity.py::test_expired_jwt_is_rejected`, `tests/test_identity.py::test_invalid_signature_is_rejected` | Signature/issuer/audience/expiry validation; error does not echo the token | Key custody is adopter-owned (F-08) |
| T-AUTH-3 | `tests/test_security_qualification.py::test_missing_exp_claim_rejected`, `tests/test_security_qualification.py::test_missing_credentials_rejected`, `tests/test_identity.py::test_missing_credentials_and_anonymous_gate` | Required claims; no anonymous by default | Controls disabled by default (F-02) |
| T-AUTH-4 | `tests/test_security_qualification.py::test_scim_requires_dedicated_token`, `tests/test_identity.py::test_scim_disabled_endpoint_is_404`, `tests/test_identity.py::test_scim_group_change_changes_effective_capabilities` | Dedicated SCIM token; disabled → 404, bad token → 401 | Static shared secret (F-08) |
| T-RBAC-1 | `tests/test_security_qualification.py::test_viewer_cannot_reach_admin_operations` | Path→capability enforcement (rebuild, evaluate, audit, metrics, purge) | Role config adopter-owned |
| T-RBAC-2 | `tests/test_security_qualification.py::test_role_without_query_capability_is_denied` | `query` capability required before retrieval | — |
| T-RBAC-3 | `tests/test_security_qualification.py::test_public_probe_paths_remain_public_but_traces_require_auth` | Public-path allowlist; tenant-scoped routes stay protected | Aggregate `/metrics` labels (F-11) |
| T-TENANT-1 | `tests/test_tenant_header_binding.py::test_api_rejects_cross_tenant_header_for_normal_caller`, `tests/test_tenant_header_binding.py::test_api_override_role_can_select_another_tenant`, `tests/test_tenant_header_binding.py::test_api_service_account_mapping_blocks_header_spoofing`, `tests/test_tenant_header_binding.py::test_denied_override_is_audited_and_scoped_to_bound_tenant`, `tests/test_security_qualification.py::test_unknown_tenant_header_is_rejected_without_pipeline_call`, `tests/test_tenancy.py::test_unknown_tenant_header_is_400` | Claim/key binding, 403 on mismatch, allowlisted role/key, audited denial, unknown tenant rejected | Identity-disabled legacy mode still trusts the header (F-01 residual) |
| T-TENANT-2 | `tests/test_security_qualification.py::test_cache_is_isolated_between_tenants` | Tenant/workspace/app/user in cache key | Only when tenancy active |
| T-TENANT-3 | `tests/test_tenancy.py::test_ops_reads_are_scoped_to_caller_tenant`, `tests/test_tenancy.py::test_experiments_are_tenant_scoped` | Ops/trace/experiment scoping; cross-tenant mismatch denied | Header spoofing closed by #223 when identity is enabled |
| T-ACL-1 | `tests/test_acl_retrieval.py::test_group_restricted_chunk_is_hidden_from_other_callers`, `tests/test_acl_retrieval.py::test_reranker_never_receives_denied_documents`, `tests/test_acl_retrieval.py::test_query_expansion_cannot_leak_denied_documents`, `tests/test_acl_retrieval.py::test_kg_expansion_cannot_leak_denied_triples`, `tests/test_acl_retrieval.py::test_acl_filter_applies_to_all_retriever_backends` | Filter after retrieval, before rerank/prompt; expansion and backend coverage | Documents without ACL metadata follow `default_policy` |
| T-ACL-2 | `tests/test_security_qualification.py::test_acl_cache_is_isolated_between_groups`, `tests/test_acl_retrieval.py::test_cache_is_scoped_per_identity` | ACL scope in cache key | Only when ACL active |
| T-GUARD-1 | `tests/test_security_qualification.py::test_injection_payload_is_blocked_without_echo`, `tests/test_injection_defense.py::test_direct_injection_payloads_blocked`, `tests/test_injection_defense.py::test_adversarial_corpus_block_rate_and_false_positives` | Threshold-based block; failure envelope omits payload | Heuristic limits (F-03) |
| T-GUARD-2 | `tests/test_injection_defense.py::test_indirect_injection_neutralized_by_default`, `tests/test_injection_defense.py::test_pipeline_neutralizes_indirect_injection_in_docs` | Untrusted-document masking + delimiting | Trusted mode disables neutralization |
| T-GUARD-3 | `tests/test_security_qualification.py::test_guardrails_disabled_is_fail_open`, `tests/test_injection_defense.py::test_low_sensitivity_is_more_permissive_than_high` | Documents fail-open default; sensitivity trade-off | **Accepted** risk (F-03) |
| T-LEAK-1 | `tests/test_security_qualification.py::test_config_view_never_returns_configured_secrets`, `tests/test_api_introspection.py::test_config_endpoint_redacts_secrets`, `tests/test_api_introspection.py::test_config_endpoint_never_leaks_env_resolved_secret` | Secret stripping/redaction in introspection | Custom free-text fields (F-12) |
| T-LEAK-2 | `tests/test_security_qualification.py::test_bearer_token_absent_from_trace_and_audit`, `tests/test_security_qualification.py::test_deny_list_does_not_echo_matched_secret`, `tests/test_audit_log.py::test_logger_redacts_secrets` | Trace/audit redaction; guardrail labels omit values | In-memory stores (F-07) |
| T-LEAK-3 | `tests/test_pii_dlp.py::test_detects_email`, `tests/test_pii_dlp.py::test_guardrail_never_leaks_matched_value`, `tests/test_national_id_redaction.py::test_api_masks_pan_when_pii_enabled` | PII classes, masking, class-only reporting | Off by default; regex/NER limits |
| T-DOS-1 | `tests/test_security_qualification.py::test_oversized_query_is_rejected`, `tests/test_query_length_guard.py::test_api_returns_400_query_too_long`, `tests/test_batch_query_api.py::test_batch_beyond_cap_returns_400_envelope` | Query/batch bounds | **No rate limiting** (F-04 / #224) |
| T-ADMIN-1 | `tests/test_security_qualification.py::test_viewer_cannot_reach_admin_operations`, `tests/test_pipeline_rebuild_api.py::test_rebuild_disabled_returns_403_and_keeps_old_pipeline`, `tests/test_pipeline_rebuild_api.py::test_governance_override_without_opt_in_is_rejected` | Capability + operator opt-ins; failed rebuild keeps old pipeline | Admin role is intentionally powerful |
| T-AUDIT-1 | `tests/test_immutable_audit.py::test_mutated_record_is_detected`, `tests/test_immutable_audit.py::test_tampered_file_is_detected_on_reload`, `tests/test_immutable_audit.py::test_retention_purge_exports_before_deleting`, `tests/test_security_qualification.py::test_viewer_cannot_reach_admin_operations` | Hash chain, export-before-purge, purge capability | Single-principal purge (F-10); memory default (F-07) |
| T-SUPPLY-1 | `tests/test_security_docs.py::test_scanning_status_matches_repository_configuration`, `.github/dependabot.yml` (guarded) | Advisory CodeQL, Dependabot alerts/updates, secret push protection, pinned deps | **No required SCA/image gate** (F-05 / #225) |

## 3. Negative-case emphasis

The new matrix deliberately asserts the *denial* or *absence* of data, not just a
status code:

- forged/unsigned/missing-credential requests must not echo the token or claims;
- a role without a capability receives a `forbidden` envelope with `forbidden_<capability>`
  and no handler side effect;
- cross-tenant cache reuse must not return `cache_hit` for the second tenant;
- restricted documents must be absent from `retrieved_docs`, the generation prompt and
  the trace for a non-matching identity;
- guardrail block envelopes must not repeat the payload or matched secret;
- introspection must not contain configured secret values;
- audit/traces must not contain the bearer token;
- oversized queries fail before retrieval.

## 4. What is explicitly not covered

- Adaptive/obfuscated prompt-injection research, model-level jailbreaks and classifier
  evasion beyond the shipped heuristics.
- Network/TLS, ingress, WAF, Kubernetes admission, cloud IAM, IdP configuration.
- Load, soak and multi-replica consistency (see #197 harness, #206 open).
- Third-party provider isolation and data-retention behaviour.
- Container escape, host compromise, side channels, physical access.
- Independent assessment: **not performed** (see [README.md](README.md)).

## 5. Maintenance

When a control changes, update the mapped test and this table in the same PR. When a
threat's residual changes, update [README.md](README.md) findings and the risk row in
[production-readiness.md](../production-readiness.md). `tests/test_security_docs.py`
guards threat/test/finding consistency, not correctness of the underlying control.
