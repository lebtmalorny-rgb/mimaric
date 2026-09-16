# Watcher automation hold after host failure

Approved scope: after a valid Masakari COMPUTE_HOST STOPPED/NORMAL failure is accepted, globally pause scheduled Watcher balancing. No audits are enabled currently. No deployment or live cloud operations authorized by this implementation task.

## Invariants

1. Persist a hold before the accepted failure is queued for recovery. Replicas share etcd v3 state. Missing/malformed/unreachable coordination denies automatic work. No TTL and no automatic release after recovery.
2. Operator resumes explicitly using compare-and-swap against the observed state revision; a new concurrent failure defeats stale resume. Each transition creates a fresh UUID epoch. Incident UUID deduplication is persistent; duplicate delivery after resume must not reapply an old hold.
3. Gate before every CONTINUOUS audit calculation, before plan launch, and before every new action in its plan. Old epochs remain invalid after resume. Recompute with a refreshed model; skip blocked ticks without catchup or terminal audit failure.
4. An admission transaction and a hold have a linearizable order. A successful admission preceding hold is already admitted: it may still reach Nova later. This version neither drains nor cancels admitted/running operations, and does not claim full migration exclusion.
5. Hold must not invoke automatic abort or reverse migration. On guarded plan admission failure, no action/rollback side effect is submitted. Healthy action parallelism stays unchanged.
6. New ONESHOT/EVENT plans retain manual behavior. Immutable per-plan provenance prevents an audit-type edit from making an old scheduled plan manual. Pre-upgrade/unclassified plans must be recomputed before applying with guard enabled (currently no audits exist).
7. Mistral/Nova/Ironic runtime code, migration destination selection, throttling, metric rules and existing PowerOps evacuation locks are outside this change.

## Architecture

A small shared Python package `powerops-watcher-guard` implements etcd v3 JSON transactions and oslo.config registration. It introduces no new daemon. Watcher stores a private nullable `automation_epoch` string on ActionPlan: UUID for scheduled plans; `manual` for newly calculated ONESHOT/EVENT plans; NULL for unclassified historical plans. No REST field permits changing it. Built-in planners stamp it before ActionPlan.create. Schema/object migration is delivered explicitly; mixed old/new writers are unsupported while guard is enabled.

Shared config group `[watcher_automation_guard]`: enabled=false, endpoint=http://127.0.0.1:2379, prefix=/powerops/watcher-automation/v1, timeout=5.0, ca_file/cert_file/key_file optional. Endpoint is a single etcd gateway or HA endpoint; HTTPS verifies certificates, no insecure option, no embedded URL credentials. Both services use identical config. Missing state is initially denied, operator `initialize` creates BLOCKED; no deployment task initializes or resumes implicitly.

etcd state holds schema=1, epoch, blocked, incident_id, host, actor, reason. State and incident marker writes in one txn. `admit(expected_epoch=None)` reads state, checks unblocked/epoch, then a txn compares its mod_revision and reads state; failed comparison denies (no late silent admission into a different generation). `hold` retries bounded CAS collisions, preserving incident idempotency. Resume compares exact revision, writes unblocked with a NEW UUID epoch. State reads are linearizable (serializable=false). Every network/parse ambiguity raises GuardUnavailable/GuardDenied. No client cache of allowed state.

Fresh model: once per epoch per collector process, synchronize collectors needed by the selected strategy under a local per-collector semaphore; no epoch state on singleton AuditHandler. Retest gate after refresh/calculation. A refresh failure prevents plan creation and permits a later periodic retry.

## Verification

Behavioral unit tests and actual local etcd concurrent/restart tests; Watcher real handler/taskflow boundary tests with external Nova calls mocked; Masakari API/engine tests; Kolla Jinja render and patch replay. No test calls cloud APIs, SSH, BMC or production etcd. Report local evidence separately from unperformed live acceptance.

etcd protocol sources: https://etcd.io/docs/v3.5/learning/api/ and https://etcd.io/docs/v3.5/dev-guide/api_grpc_gateway/ .
