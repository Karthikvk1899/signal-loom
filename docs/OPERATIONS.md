# Operations

## Lifecycle and health

`python scripts/init_env.py` creates a mode-0600 `.env` using OS randomness and refuses overwrites. Back it up separately from data, restrict access, and keep it out of source control. Compose uses an explicit migration service and PostgreSQL readiness before starting the API; migrations are serialized by advisory transaction lock. API replicas do not run DDL. Schema v1 is initial installation, not a general-purpose future migration engine.

`/health/live` checks only process execution. `/health/ready` queries schema state through the bounded connection pool (10 connections/process, 5-second checkout, 5-second statement timeout, 3-second lock timeout). External ingress should enforce request rate, connection count and timeout limits. All app requests have a 64 KiB actual-byte body cap, including chunked bodies. The console reverse-proxies only `/v1`; admin endpoints require the separate API port locally.

## Operator signals

Monitor HTTP 401/403 changes, 409 conflict rate, 5xx/503 rate, response latency, DB connections/lock waits, database disk growth, SDK refresh failures and stale decision counts in the embedding application. No built-in Prometheus exporter or alert manager is shipped. Readiness is not an SLO. Poll the audit API for releases; store the last sequence per environment. Do not use raw tenant IDs/subject IDs as metric labels.

SQL diagnostics (trusted DB operator only):

```sql
SELECT tenant,name,generation,active_revision FROM environments ORDER BY tenant,name;
SELECT tenant,environment,count(*) FROM revisions GROUP BY tenant,environment;
SELECT tenant,environment,count(*) FROM audit GROUP BY tenant,environment;
SELECT pid,wait_event_type,wait_event FROM pg_stat_activity WHERE datname=current_database();
```

## Failure runbooks

* **409 activation:** refresh revisions and generation; determine whether the intended release already committed after an ambiguous response. Never automatically overwrite another operator's release. Re-propose stale drafts. A duplicate activation retry with the original expected generation correctly conflicts.
* **DB outage:** new changes and snapshots fail closed with 503. SDK continues only until max_age then returns its explicit default. Restore PostgreSQL and check readiness before resuming. CI verifies stop/start recovery, not primary failover or zero data loss.
* **Bad release:** identify a previously activated, approved revision, fetch current generation, activate it with rollback=true. This creates a new generation; do not manually decrement the pointer. Check audit and observe SDK refreshes. Already-running requests may use previous configuration.
* **Bad credential:** use DELETE /admin/credentials/{id}. Requests already past authentication can finish. Cached SDK bundles remain usable until configured expiry. Issue a replacement with least privilege; do not reuse actor names for unrelated people.
* **Signing-key compromise:** stop release writes, revoke credentials as needed, distribute a new trusted public key to every client through an authenticated channel, deploy a new signing key, re-activate a vetted prior release as a new generation, and refresh clients. Existing envelopes remain signed with the old key; a key change without a new activation makes refresh validation fail. Multi-key overlap and automated rotation are not implemented.
* **Stale SDK:** inspect credential revocation, TLS, scope, pinned key and API reachability. Failed refresh must not extend max_age. In-process monotonic timer avoids wall-clock jumps; restart clears cache/high-water mark and defaults until refresh.

## Backup, restore and capacity

Keep database backups and signing key recovery material in separately controlled stores. Suggested rehearsal in a disposable environment: pg_dump with custom format; restore into an empty DB with pg_restore; preserve the signing key; compare environment generations and verify snapshots with the pinned public key before serving traffic. This rehearsal and point-in-time recovery are **not yet verified**. Restoring an older generation can make existing SDKs reject it; recovery needs a generation strategy above the highest externally observed generation, not blind service restart.

No automatic retention is implemented. Revisions, activations and audit grow without bound; measure growth and establish retention policy before real use. Do not delete revisions referenced by activations. Actor and tenant lifecycle management is limited to credential revocation. List APIs cap results; audit supports a cursor but revisions/environments do not yet paginate beyond 100.

Compose is a single-host, single-DB development topology. For deployment, use a private managed PostgreSQL network, distinct migration/application database roles, TLS termination, service credentials from a secret manager, controlled identity provisioning, database backup policy, per-tenant quotas, ingress rate limits, container-image scanning, and load/failure testing. No Terraform/AWS deployment or sizing claims are supplied without verification.
