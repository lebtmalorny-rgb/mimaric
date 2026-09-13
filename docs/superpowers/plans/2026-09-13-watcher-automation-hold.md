# Watcher automation hold implementation plan

Spec: `docs/superpowers/specs/2026-09-13-watcher-automation-hold.md`

## Global Constraints

- No deployment, live cloud calls, production etcd writes, push, or merge. Preserve dirty main trees. Work only in isolated component/kit branches.
- Scope is CONTINUOUS scheduled balancing after valid Masakari host failure. No global migration serialization; already admitted actions may finish. Never auto-abort or auto-rollback because of hold. Missing/malformed/unavailable guard denies automatic work.
- Persistent hold, explicit CAS manual resume, new epoch at every transition, permanent invalidation of old plans, no TTL/no automatic release/no catchup. New ONESHOT/EVENT plans retain manual behavior; historical NULL provenance denied when enabled.
- Python 3.11. Use behavioral TDD; tests must exercise actual entry points and boundaries, not duplicate implementation. Each implementer owns only its task, no subagents. Commit in isolated branches and report commands/results.

## Task 1: Shared durable gate and operator CLI

Workdir: `/Users/dmitry/Desktop/ironic:mistral:masakari/powerops-patches/worktrees/watcher-automation-hold`.
Create `packages/powerops-watcher-guard/pyproject.toml`, `powerops_watcher_guard/{__init__,gate,config,cli}.py`, focused tests and README. Distribution name `powerops-watcher-guard`, version 0.1.0, Apache-2.0, dependencies requests and oslo.config. Avoid extra framework.

Interface binding downstream:
`Gate(endpoint, prefix='/powerops/watcher-automation/v1', timeout=5.0, ca_file=None, cert_file=None, key_file=None)`.
`Gate.status()` returns dict state including integer `revision`; missing state raises GuardDenied.
`Gate.initialize(actor, reason)` creates blocked state only if absent, returns status.
`Gate.hold(incident_id, host, reason='Masakari host failure')` returns state, works if state absent, writes persistent incident marker in same txn; duplicate is no-op even after resume; bounded CAS retries.
`Gate.resume(expected_revision, actor, reason)` writes unblocked NEW epoch only by exact CAS; reject missing/invalid state. All text IDs/reasons validate nonempty bounded values; incident id UUID, epoch UUID.
`Gate.admit(expected_epoch=None)` returns current epoch after linearizable txn proving exact observed revision and allowed state. A mismatch denies, no retry which could silently change generation.
`GuardDenied(Exception)` base; `GuardUnavailable(GuardDenied)` for backend/parse/protocol error; `GuardConflict(GuardDenied)` for stale CAS.
`config.register_opts(conf)` registers `[watcher_automation_guard]` config per spec; `config.list_opts()` sample generator; `config.from_conf(conf)` creates Gate (callers check conf.enabled). No permissive fallback, TLS verification enforced.
Console `powerops-watcher-guard --config-file FILE status|initialize|resume`; initialize requires --actor --reason; resume requires --expected-revision INT --actor --reason --acknowledge-recovery. Output JSON, errors nonzero without endpoint secret leakage. No hold CLI required.

- [ ] RED tests for missing state deny, persistent initialize blocked, resume new epoch, blocked/stale admit deny, hold idempotent across resume, two incident/resume races, malformed responses and failed network deny, prefix isolation and input validation, TLS request params, CLI acknowledgement/revision requirements.
- [ ] Implement using etcd v3 `/v3/kv/range` and `/v3/kv/txn` requests, base64 bytes, revision compare and incident version compare. No leases. State mutation can safely retry only CAS conflicts; network ambiguity remains denied, never reset allowed by default.
- [ ] Provide real-etcd tests opt-in via `POWEROPS_GUARD_TEST_ENDPOINT`, unique disposable namespace; no production endpoint default. Test concurrent admissions vs holds using transaction revisions, concurrent resume vs new hold and client reconstruction. Root will supply local etcd endpoint and environment while you work.
- [ ] GREEN focused/full package tests, self-review, commit. Report protocol/race limitations honestly.

## Task 2: Watcher scheduled audit and action boundaries

Workdir: `/Users/dmitry/Desktop/ironic:mistral:masakari/analysis/watcher-automation-hold-work/watcher`, base 5cf30fbbfd6b94be098d3f1f8c21c1efd331badc. Shared package in kit worktree above. Test env root provides under /tmp.
Read spec and Task 1 interface from package README (do not read whole plan). Add dependency `powerops-watcher-guard>=0.1.0,<0.2.0`, config registration/sample discovery.
Create `watcher/common/automation_guard.py`: configuration checks, audit epoch admission, plan/action validation, fresh collector handling. Add private nullable `automation_epoch` string length36 to SQL model and ActionPlan object with version bump/backport handling, one Alembic revision on current head, DB/object fixture compatibility. Values are UUID scheduled, `manual` newly ONESHOT/EVENT, NULL historical/unclassified. Field not user-writable via REST. Unknown non-null strings deny. NULL plans denied while enabled. Disabled behavior stays upstream.
Pass epoch explicitly through audit calculation/planning, not mutable singleton handler fields. Built-in planners base/weight/node_resource_consolidation/workload_stabilization accept optional `automation_epoch=None` and set before create. Extend post_execute overrides compatibly. Custom planners without new signature fail closed when enabled and document requirement; preserve existing call signature when disabled.
CONTINUOUS execute: admit before pre_execute/strategy; on GuardDenied skip without FAILED/inactive state; next_run_time still advances using existing finally. Ensure refresh exceptions treated retryable skip. Capture epoch before model refresh and calculation; revalidate after both before launch. Refresh only selected strategy-required models using collector synchronization, once per epoch/process with local synchronization; enable only guarded scheduled calculation. Keep strategy context explicit per-call. Do not reuse cached pre-incident CDM after resume.
Plan handler checks before marking ONGOING/executing and fails stale/blocked plans safely. Per action enforce immediately before `self.action.execute()` inside TaskFlowActionContainer.do_execute (pre_execute swallows generic errors upstream). Guard do_revert too; stale/blocked/unknown guard suppresses rollback side effects and never routes through CANCEL_STATE or abort. Existing admitted running actions can complete.

- [ ] RED behavioral tests through actual continuous handler, plan handler, and TaskFlowActionContainer, gate mock only at external boundary: block audit preserves periodic state and advances tick; failure during computation prevents launch; old epoch after resume denied; manual newly stamped plan allowed; NULL legacy denied; audit-type edit cannot bypass stamped scheduled provenance; singleton concurrent audits keep independent epoch; model refresh failure retries, epoch refreshed once; next action blocked without cancelling current or reverting completed migration even with rollback option true.
- [ ] Implement minimal source changes, migration/object roundtrip tests.
- [ ] GREEN new tests and relevant upstream audit/applier/planner/object/db tests using root-supplied /tmp env; fix regressions, self-review, commit. Do not export patch yet.

## Task 3: Masakari trigger and Kolla configuration

Workdirs `/Users/dmitry/Desktop/ironic:mistral:masakari/analysis/watcher-automation-hold-work/{masakari,kolla}`. Masakari base e7943dbce5f693bf67b22fa33ce137c937313346 includes verified0809 + existing post-fence Nova-down patch; Kolla base 305da1ef8f816c58d13b2d14a78cf03c9c734aae. Shared package in kit.
Add package requirement/config options/sample registration to Masakari. Add focused `masakari/powerops/watcher_automation.py` helper using shared Gate: only enabled and notification COMPUTE_HOST, payload event STOPPED and host_status NORMAL (matching engine case handling) holds. API `_create_notification` after host/maintenance/duplicate checks assign UUID, then durable hold before notification.create and before RPC. Preserve notification UUID; no silent continue if backend denied. Engine `_handle_notification_type_host` also holds for eligible STOPPED before maintenance/recovery for queued notifications; duplicate UUID makes this idempotent and must not reblock after manual resume. Do not release on any terminal status. Source conflicts/other events remain upstream.
Kolla roles watcher+masakari templates emit identical `[watcher_automation_guard]` values sourced from shared group_vars. Default enabled false in deployment config (operator explicitly enables after coordinated package/schema update and initialization); assert prerequisites when true: enable_watcher, enable_masakari, enable_powerops, compatible etcd backend/explicit endpoint. Endpoint can be dedicated HA etcd endpoint; default derive existing etcd internal endpoint with safe scheme mapping. Configure ca/cert/key only if provided, use container paths plus matching volume/cert handling or explicitly validate operator-preprovisioned paths; no dangling host paths. Do not create/init/resume gate through Ansible, do not turn on balancing.

- [ ] RED API order tests (hold before create/RPC), invalid/duplicate/maintenance bypass tests, failclosed no accepted notification on backend failure; engine legacy queue/idempotent replay tests and no hold for STARTED/process events.
- [ ] Implement minimal hooks. Preserve post-fence behavior and existing global/host locks unchanged.
- [ ] RED/GREEN Kolla real Jinja template render tests ensure both configs identical, enabled=false default, prerequisites/endpoint validation; no source/text-substring-only tests.
- [ ] Relevant upstream/current PowerOps tests, self-review and commit each component.

## Task 4: Reproducible delivery and runbook

Workdir kit `/Users/dmitry/Desktop/ironic:mistral:masakari/powerops-patches/worktrees/watcher-automation-hold`.
Create `hotfixes/watcher-automation-hold/{watcher,masakari,kolla-ansible}` patches from exact component bases and final source commits; manifest JSON with baseline refs/archive hashes/additional Masakari prerequisite, patch/package SHA256, component final commits. Add scoped apply/replay verification tool (no network/live cloud by default), shared wheel build or reproducible wheel build command; do not claim requirement pip-index availability: install local wheel in all Watcher/Masakari service images including API before source patches activate.
Russian `docs/WATCHER-AUTOMATION-HOLD.md` covers purpose, limitations, exact sources, coordinated upgrade with guard disabled then migration/package rollout and initialize BLOCKED then enable same config everywhere; all healthy old/unclassified plans must recompute; no mixed old workers with enabled guard. Explicit operator status/initialize/resume commands and recovery verification before resume. Guard config/namespace failures deny automatic work; Masakari can't accept eligible failure if hold backend unavailable (existing coordination dependency, document operational effect). No automatic release or plan restart; periodic audits calculate next new plan.
Report local checks vs missing production/scale evidence, residual admitted-window/manual-operation races and lack of Nova drain. Keep README changes small appended feature link; don't copy dirty main edits. Evidence records test commands/results including actual etcd run/restart if available, no inflated pass claims.
- [ ] Export patches; replay against clean baselines using `git apply --check` then application, compare resulting source tree to implementation (except git metadata).
- [ ] Verify shared wheel imports, CLI help/status missing state behavior, patch/package hashes, config render contract, source compile and previously untested cross-component boundaries.
- [ ] Write runbook/evidence, commit kit; final whole-branch review and address concrete findings. Keep local branches ready for user review, no merge/push/deploy.
