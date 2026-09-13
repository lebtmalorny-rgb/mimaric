# Per-target Masakari Evacuation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Execute tasks in order, each with TDD and independent task review. User approved the specification and execution; no further execution-choice question is required.

**Goal:** Allow evacuation to different automatically selected Nova computes concurrently, while enforcing one evacuation per target, a shared configurable budget of three and a five-second per-target cooldown.

**Architecture:** Masakari records a durable submission intent and uses a process-wide bounded submission pool. Receiving nova-compute binds the actual migration and target, then atomically acquires both a target claim and a global slot in etcd before local recovery. Only a verified Nova completion followed by a full monotonic cooldown releases those claims; unknown outcomes retain them.

**Tech Stack:** Python 3.11+, requests, oslo.config, etcd v3 transactions; Nova stable/2025.1; Masakari and Kolla 0809 plus already delivered prerequisites; unittest/pytest, real local etcd, Ansible/Jinja behavioral tests.

**Spec:** `docs/superpowers/specs/2026-09-13-masakari-per-target-evacuation-design.md`.

## Global Constraints

- Назначение по-прежнему выбирает Nova. Одна активная эвакуация на целевой compute; до трёх активных эвакуаций во всём контуре; пауза 5 секунд после успешного завершения на том же compute. Общий предел и пауза настраиваются.
- Множество ВМ одного задания может быть распределено по разным назначениям. No single-VM job cap and no per-notification unbounded worker pools.
- Gate applies to `rebuild_instance(recreate=True)` on enabled computes. Ordinary build/start, live migration, scheduler/Placement policies, Ironic fencing and existing source-host protection retain their scope.
- Nova API 2.53 semantics for Masakari evacuation remain; do not switch to 2.95 as a boot-storm workaround.
- Потеря процесса, неоднозначный ответ etcd или ошибка после допуска не освобождают запись по TTL. No lease on authoritative intent/operation/claim/tombstone records.
- Claims use globally unique compute/provider UUIDs. Every ownership transition is conditional on owner/revision. An existing migration UUID never authorizes a second executor.
- A Masakari observation timeout is not a Nova cancellation. Preserve intent even when the request has not reached compute. No automatic request retry after an ambiguous result.
- Queued admission timeouts in Nova must terminate that admission attempt durably before it can later execute. Do not reset another executor's Nova task/migration state when rejecting a duplicate.
- Completion proof must include Nova migration `done`, matching destination/VM, `task_state is None`, consistent final VM state and normal completion of the whole rebuild path. Host change or VMove success alone is insufficient.
- After proven completion and process restart, wait a fresh full cooldown; wall-clock changes cannot shorten it. Unknown active work needs operator proof of Nova terminal state and old executor/delivery quiescence before exact-revision resolution.
- Preserve original disabled behavior. Mixed old/new active workers while enabled are unsupported. No deployment, restarts, SSH/BMC, live cloud requests, merge or change to `main`.
- Separate namespace `/powerops/evacuation/v1`; published Watcher gate/package/patches and emergency epoch are immutable prerequisites. No Mistral patch in this scope.
- Python test caches, venvs, etcd data and ephemeral proof copies stay under `/tmp`. Never print/read/index Kolla `etc/kolla/passwords.yml` or its digest. Replay excludes it in the initial Git add with literal pathspecs.
- No assertions of production or 1000-host readiness from local tests. Real-etcd tests complement, not replace, component execution-boundary tests.

## Workspaces and ownership

Kit worktree: `/Users/dmitry/Desktop/ironic:mistral:masakari/powerops-patches/worktrees/masakari-per-target-evacuation`, branch `feature/masakari-per-target-evacuation`, parent published Watcher `c866d56fbf382afa4612c07039c34fbb5032aef5`; approved design commit `4aa7f32`.

Component root: `/Users/dmitry/Desktop/ironic:mistral:masakari/analysis/masakari-per-target-evacuation-work/`:
- `nova`: base `ce37978276744e92d91251210a1d9c2784eea375`, full official stable/2025.1 checkout.
- `masakari`: base `0c2fa56a36e71612e32bf50e174c465138d0c8fb`, includes 0809, post-fence and Watcher hold.
- `kolla`: base `3c8d0b9b04053855541fc33f5be91ab0541a6a77`, includes 0809 and Watcher hold/config fixes.

Each task owns only its stated paths; controller owns plan, ledger, source baselines and environment. One implementation agent at a time. Package/report interfaces freeze before consumer tasks. If a signature needs refinement, report it to controller before the next task; controller records it and updates consumer briefs.

## File map

- `packages/powerops-evacuation-guard/powerops_evacuation_guard/etcd.py`: strict JSON/base64 transaction transport and validation, TLS verified, no redirects or secret echo.
- `.../guard.py`: durable intent/operation/claim protocol; bounded compare transactions, no process-local authority.
- `.../config.py`, `.../cli.py`, `.../__init__.py`: common service config, operator commands and public API.
- Nova `nova/compute/powerops_evacuation.py`: admission wrapper, real Nova completion proof and exception/duplicate isolation. Small hook in `manager.py` only.
- Masakari `masakari/powerops/evacuation.py`: process-wide bounded coordinator and intent lifecycle; existing `host_failure.py` and `compute/nova.py` keep recovery semantics.
- Kolla shared `powerops-evacuation-guard` precheck role plus existing Nova-cell/Masakari config templates; no cloud workflow in Ansible.
- `hotfixes/masakari-per-target-evacuation/`: wheel, ordered component patches, manifest, evidence and Russian runbook; reusable replay tooling.

### Task 1: Durable evacuation guard package and operator lifecycle

**Files:** Create package `packages/powerops-evacuation-guard/` with pyproject, README, the five modules above and `tests/{test_guard,test_etcd,test_cli,test_config}.py`, test-only fake etcd helpers. Do not modify Watcher package.

**Public interfaces:** Distribution `powerops-evacuation-guard==0.1.0`, Python>=3.11, Apache-2.0 SPDX, requests>=2.25.1 and oslo.config>=9.0.0, setuptools>=77. Export `Guard`, `GuardError`, `GuardBusy`, `GuardDuplicate`, `GuardConflict`, `GuardDenied`, `GuardUnavailable`. UUIDs are canonical strings; snapshots are JSON-compatible dicts including integer `revision`.

```python
Guard(endpoint, prefix='/powerops/evacuation/v1', timeout=5.0,
      ca_file=None, cert_file=None, key_file=None,
      max_parallel=3, cooldown=5.0)
guard.initialize(actor, reason)                         # absent state only
guard.configure(expected_revision, max_parallel, cooldown, actor, reason)
guard.configuration()                                  # actual shared config
guard.create_intent(attempt_uuid, vm_uuid, source_host, request_id, actor)
guard.get_intent(attempt_uuid)
guard.note_intent_unknown(attempt_uuid, reason)          # observer only
guard.register(migration_uuid, vm_uuid, source_host, target_uuid,
               target_host, owner_uuid, request_id=None) # WAITING
guard.get_operation(migration_uuid)
guard.try_admit(migration_uuid, owner_uuid)              # RUNNING or GuardBusy
guard.deny_waiting(migration_uuid, owner_uuid, reason)   # durable DENIED
guard.mark_unknown(migration_uuid, owner_uuid, reason)   # retains claims
guard.complete(migration_uuid, owner_uuid, result)       # COOLDOWN
guard.finish_cooldown(migration_uuid, owner_uuid)        # full wait -> DONE
guard.recover_cooldown(migration_uuid, expected_revision, actor, reason)
guard.resolve(migration_uuid, expected_revision, actor, reason,
              nova_terminal, executors_quiesced)         # proof -> cooldown
guard.resolve_intent(attempt_uuid, expected_revision, actor, reason,
                     nova_terminal, executors_quiesced)
guard.status(limit=100, cursor=None)                     # bounded pagination
```

`config.register_opts(conf)` and `config.from_conf(conf)` produce the above Guard. Common group `[powerops_evacuation_guard]`: enabled=false, endpoint=http://127.0.0.1:2379, prefix as above, timeout=5.0, max_parallel=3, cooldown=5.0, admission_timeout=3600.0, poll_interval=1.0, submission_workers=3 and optional TLS paths. max_parallel/submission_workers positive bounded integers; timeouts finite positive; cooldown finite >=0. Runtime actions reject a shared max_parallel/cooldown mismatch. Status can report it for diagnosis.

**Durable protocol requirements:**
- Separate metadata, per-attempt intent, immutable request-ID index, per-migration operation tombstone, VM claim, per-target claim and numbered global-slot keys. No ever-growing JSON map of every host/VM. Normal admission touches one operation/VM/target plus bounded configured slots.
- `create_intent` atomically reserves VM + attempt + request ID before Nova submission. A duplicate never returns a fresh right to submit. A random request ID alone is not authorization: bind existing intent only when VM/source/attempt index all match. Native Nova evacuations without an existing intent still use the gate; they cannot bypass an existing VM claim.
- `register` atomically binds actual migration/target to an intent (if present) and its VM claim. Retain immutable identity/tombstones after completion. Reject reuse of a resolved request-ID intent so a delayed old RPC cannot become new native work.
- `note_intent_unknown` changes client observation only; it must not overwrite Nova-owned RUNNING/COOLDOWN/DONE, relinquish claims, or prevent an already accepted delayed request from being accounted for.
- Admission compares metadata revision, operation owner/state/revision, VM claim and empty target+global slot in ONE transaction. On contention raise GuardBusy; no partial acquisition. Treat missing/inconsistent keys, malformed payload, network ambiguity and unexpected transaction responses as fail-closed.
- Never let a second process resume the same RUNNING UUID. Duplicate/terminal records deny a second execute. Concurrent deny/admit must have exactly one winner. Waiting denial retains tombstones and releases only its own VM claim.
- `complete` accepts proof containing migration_status=done, vm_uuid, target_uuid, target_host, final vm_state in active/stopped and task_state=None, all consistent with the operation. Nova supplies this proof; Masakari does not call complete/release.
- Completion retains all claims through COOLDOWN. A normal finisher uses monotonic elapsed time; a new recovery owner CASes the exact COOLDOWN revision and waits the FULL configured cooldown. Then atomically marks DONE and releases only matching target/global/VM claims. Stale finishers cannot release a new owner. Inject/patch time primitives only for tests, not a bypass flag in production.
- Unknown resolution requires both explicit Boolean acknowledgements, actor/reason, exact revision and an atomic race check against binding/admission. It goes through full cooldown for any admitted operation. Resolving an unbound intent preserves its request/attempt tombstone; it cannot strand or release a concurrently bound operation.
- `configure` changes limits only with exact metadata revision and no active/waiting/submitting claims, using an atomic range-absence condition (compare actual etcd range semantics in a real-etcd test) to exclude phantom claims. Every creating transition compares that metadata revision. No automatic metadata reset or force option.

- [ ] **RED:** write real behavior tests, including same-target contention, different-target overlap, cluster capacity, duplicate/old owner, ambiguous successful write response lost, intent-bind-vs-resolve, deny-vs-admit, persistent claims, cooldown restart/clock jump, config-vs-new-claim and sanitized CLI errors. Each assertion must be invalidated by removing the production safety check, not by a fake's own counters.

```python
# Concrete acceptance shape; fixture uses isolated real/fake etcd transport.
a = guard.register(M1, VM1, 'src-a', HOST1, 'dst-a', OWNER1)
guard.try_admit(M1, OWNER1)
guard.register(M2, VM2, 'src-b', HOST1, 'dst-a', OWNER2)
with self.assertRaises(GuardBusy):
    guard.try_admit(M2, OWNER2)
self.assertEqual('WAITING', guard.get_operation(M2)['state'])
guard.register(M3, VM3, 'src-c', HOST2, 'dst-b', OWNER3)
self.assertEqual('RUNNING', guard.try_admit(M3, OWNER3)['state'])
```

- [ ] **GREEN:** implement strict transport and transactional protocol. Endpoint has HTTP(S), no userinfo/query/fragment, valid port and verified TLS; bound and sanitize error text. Separate state transitions from transport. CLI `powerops-evacuation-guard --config-file FILE` implements initialize/configure/status, inspect-operation/inspect-intent, recover-cooldown, resolve-operation/resolve-intent; mutation commands require actor/reason/revision where applicable and explicit quiescence/terminal flags.
- [ ] Run package tests offline and with `POWEROPS_EVACUATION_TEST_ENDPOINT=http://127.0.0.1:33379`; root supplies endpoint/process and handles sandbox execution. Confirm an actual etcd restart retains claims and blocks admission. CLI init/status from distinct processes; no daemon.
- [ ] Commit package only. Write report with exact API/config final forms, RED/GREEN commands/output, real-etcd proof pointers and concerns.

### Task 2: Nova receiving-compute admission and completion proof

**Files:** Create `nova/compute/powerops_evacuation.py`, unit tests `nova/tests/unit/compute/test_powerops_evacuation.py`; modify `nova/compute/manager.py`, `nova/conf/__init__.py`, `nova/conf/opts.py` or existing common registration hook, `requirements.txt`. Work only in component Nova tree.

**Consumes:** Task1 Guard/config methods and snapshots. Baseline actual `ResourceTracker.finish_evacuation` sets migration status `done`; normal manager return alone is not sufficient because some exception branches are swallowed. Produces opt-in guarded `rebuild_instance(recreate=True)` without changing public RPC signature or original disabled behavior.

- [ ] **RED:** use real ComputeManager path and fake external virt/service boundaries to prove denied/duplicate calls do not execute recovery/spawn, same-target mutual exclusion across helpers, different targets may execute together, host auto-selection is honored, and slot remains occupied through finish_evacuation and cooldown. Test thrown and swallowed rebuild failures, missing migration UUID/compute UUID, stale result, duplicate native and Masakari-correlated RPC, waiting timeout and backend failure.

```python
# Test must call ComputeManager.rebuild_instance, not just an admission mock.
# Simulated first virt driver spawn installs a barrier; invoke a second call
# with a distinct migration on the same target and assert no second spawn.
self.assertEqual([VM1], recorded_driver_spawn_uuids)
self.assertEqual('RUNNING', guard.get_operation(M1)['state'])
# A different target runs while VM1 remains blocked in its fake external driver.
self.assertIn(VM3, other_target_recorded_spawn_uuids)
```

- [ ] **GREEN:** keep the manager change a small wrapper/hook and put policy in the helper. Resolve the local ComputeNode/provider UUID from actual scheduled node/compute info; validate migration VM/source/target bindings before admission. Use context.global_request_id for correlation, never as standalone privilege. Claim ownership uses a fresh executor UUID.
- [ ] Register before local recovery; retry only GuardBusy using monotonic deadline/polling. Poll/wait must not hold Nova's resource semaphore or process-wide lifecycle locks. A pending timeout durably denies that owner; do not allow the same queued call to execute later.
- [ ] Duplicate/denial must not enter state-changing error decorators that reset another executor's task_state or mark its migration failed. Handle a duplicate as an explicit no-op without invoking the protected body. Preserve visible failed/unknown outcome for genuine new work; never present a denied call as proof of successful evacuation. Review wrapper placement against existing Nova decorators and test active-other-owner state preservation.
- [ ] On callback normal return, reread real Nova migration and instance objects; require done, correct VM/destination and final state/task_state before complete. On any exception/unknown outcome retain/mark UNKNOWN before propagation; never release in finally. Loss of completion/release response must preserve safe state and prevent re-execute.
- [ ] Recover a proven COOLDOWN safely when needed for the same target, using Task1 exact-revision recovery/full wait. Never automatically resolve RUNNING/UNKNOWN. Disabled guard and `recreate=False` call the original code unchanged.
- [ ] Run new boundary tests plus existing rebuild/evacuate ComputeManager and resource-tracker cases that touch the hook. Root installs constrained Nova test dependencies; use `/tmp/masakari-evac-venv/bin/python`. No real libvirt/cloud calls. Commit component only and report final SHA, tests, exact completion observations and limits.

### Task 3: Masakari durable intents and bounded parallel submissions

**Files:** Create `masakari/powerops/evacuation.py` and unit tests under `masakari/tests/unit/powerops/`; modify `masakari/engine/drivers/taskflow/host_failure.py`, `masakari/compute/nova.py`, common conf registration/opts, `requirements.txt`, relevant host-failure/Nova client tests.

**Consumes:** Task1 intent/read/observer protocol and Nova operation state from Task2. Preserve API2.53 and existing guest-state handling. Use old disabled path with GLOBAL_EVACUATION_LOCK exactly as before.

Enabled guard requires `powerops.enabled=True` and a healthy source coordinator at runtime, matching Kolla prerequisites. Reject inconsistent enabled configuration before inventory/VM effects. Recheck a recovery's stop/failure condition after waiting for shared worker capacity so a previously blocked feeder cannot submit fresh work after that recovery failed.

**Full inventory refinement (source-verified):** Existing `API.get_servers` calls `servers.list` without pagination; constrained python-novaclient18.9.0 returns only the first API page, and baseline Nova defaults `api.max_limit=1000`. For enabled new guard mode, retrieve every source-host page before building VMove inventory, using an optional backwards-compatible `all_pages=False` client argument and SDK `limit=-1` when true. Preserve the disabled invocation/behavior. Add a behavioral test through the real SDK pagination path with only HTTP transport faked, proving second-page VMs enter the recovery inventory. Do not claim a complete batch solely from an already truncated injected VMove list.

- [ ] **RED:** multi-VM lists from several simultaneous notifications exercise a SINGLE process-wide bounded pool/semaphore, not independent limits per recovery. At least 12 VMs must all be processed; different target Nova fakes overlap while shared admission keeps same-target spawn serial. Failure stops new submission only for the affected recovery and waits for already-submitted workers. Test unrelated recovery progress and full source-coordinator lifetime.

```python
# Real TaskFlow EvacuateInstancesTask, fake OpenStack boundary only.
task.execute('failed-a', notification_a)
self.assertEqual(set(twelve_vm_uuids), set(recorded_submitted_vm_uuids))
self.assertLessEqual(observed_peak_process_submissions, 3)
# Another notification shares the same limiter, including when concurrently run.
```

- [ ] **GREEN:** before the evacuation POST, reserve intent with unique attempt UUID and unique req-UUID in a per-call copied Masakari context; never mutate shared task context/global client. Extend the client method with an optional explicit global_request_id or copied-context path while retaining legacy signature behavior when disabled. Actual Nova invocation remains `host=reserved_host` (normally None), API2.53, one attempt, no retries after ambiguous response.
- [ ] Bounded dispatch must avoid materializing one waiting greenlet per VM; feed at most configured worker count from the sorted input iterator, and enforce one process-wide limit across tasks. Preserve original state reset/lock/unlock checks, source fencing and coordinator.assert_healthy boundaries.
- [ ] Persist unknown intent on API timeout/connection uncertainty before returning failure; observer updates cannot overwrite Nova-owned state. A known client-side pre-submit denial is distinct from an ambiguous external result. No automatic resubmission for existing VM intent.
- [ ] When Nova's new host/state observation appears successful, also verify the correlated operation has reached DONE and correct migration/target. DENIED or UNKNOWN is not success. Do not free Nova claims or call complete from Masakari; its failure/cleanup does not reverse or cancel evacuation.
- [ ] Preserve VMove result reporting: mark SUCCEEDED only after both existing VM final-state checks and shared operation proof; otherwise keep a clear failure/unknown reason including attempt ID, without a new misleading success state. No need to add a VMove schema field when the durable shared record supplies the state.
- [ ] Run selected existing API/powerops/host-failure/post-fence tests plus new concurrency/client-intent cases using `/tmp/watcher-hold-venv/bin/python` (Masakari's test hacking pin differs from Nova). All Nova/Ironic calls mocked at external boundary. Commit component only; report peak concurrency, complete multi-VM coverage, unknown behavior and exact SHA.

### Task 4: Kolla configuration and coordinated image prerequisites

**Files:** Modify `ansible/group_vars/all.yml`, Nova-cell defaults/config/prechecks, Masakari config/prechecks; create `ansible/roles/powerops-evacuation-guard/tasks/main.yml`; add covering cases in `kolla_ansible/tests/unit/test_powerops_{templates,configuration_contract}.py`.

**Consumes:** exact Task1 `[powerops_evacuation_guard]` options. Nova-cell template is `ansible/roles/nova-cell/templates/nova.conf.j2`; source roles `nova` and `nova-cell` have distinct precheck/config responsibilities. Existing patched Masakari image override remains.

- [ ] **RED:** render both actual service templates with enabled/disabled and optional TLS cases; execute real Ansible shared precheck conditions. Cover managed-etcd/PowerOps prerequisites, config limits, valid endpoint syntax/port/no-userinfo, TLS pair/path rules, absent image and unchanged disabled Nova image selection.

```python
self.assertEqual(nova_guard_options, masakari_guard_options)
self.assertEqual('false', default_guard_options['enabled'])
self.assertEqual(legacy_nova_compute_image, disabled_rendered_image)
```

- [ ] **GREEN:** add `powerops_evacuation_guard_enabled: "no"` and shared endpoint/prefix/timeout/max_parallel/cooldown/admission_timeout/poll_interval/submission_workers/TLS variables. Endpoint may reuse the existing etcd VIP computation; namespace remains independent of Watcher.
- [ ] Guard-only Nova image override `powerops_nova_compute_image`/`powerops_nova_compute_tag` defaults empty; require both non-empty while enabled, leave existing `nova_compute_image_full` exactly unchanged while disabled. Masakari continues using its patched engine image. Shared role imported from effective Nova-cell and Masakari prechecks, requiring Nova/Masakari/PowerOps/managed etcd.
- [ ] TLS follows preprovisioned container roots `/etc/pki/`, `/etc/ssl/`, `/var/lib/kolla/share/ca-certificates/`, no traversal and cert/key pair. Do not add arbitrary host mounts or infer actual file/image presence from syntax tests. Render group identically; no state initialize/resume in deploy/reconfigure.
- [ ] Run covering config/template tests and existing powerops config tests; classify unchanged baseline warnings. Commit only component code/tests. Record exact optional/default paths and image rollout requirements for Task5.

### Task 5: Deliver separate patches, wheel, operator guide and cross-process proof

**Files:** Create `hotfixes/masakari-per-target-evacuation/` with three ordered component patch series, `manifest.json`, `EVIDENCE.md`, `package/*.whl`; create `docs/MASAKARI-PER-TARGET-EVACUATION.md`; extend kit README/SHA256SUMS and tests. Reuse the existing verifier/replay `--manifest` option (verified at `tools/watcher_automation_hold_delivery.py:214`); change general manifest handling only if the new delivery tests reveal a necessary gap, preserving existing Watcher invocation/results. Add `tests/test_masakari_per_target_evacuation_{delivery,crossprocess}.py`.

**Consumes:** frozen Task1 package + Task2/3/4 component SHAs and base trees. Published Watcher payloads are unchanged prerequisites. New branch remains stacked on published c866d56; do not include original unrelated firewall design or private scratch.

- [ ] **RED:** exact package/component artifact checks, wrong-base/no-overwrite replay, dependent patch ordering, no excluded-secret object blob, unchanged Watcher artifact hashes, wheel import outside editable sources; ensure expected content inventory is updated rather than hardcoding obsolete SHA256SUMS counts.
- [ ] **GREEN:** export feature-only `git format-patch BASE..HEAD` per component; manifest exact base/final commits/trees and dependency order. Preserve Kolla symlinks and initially exclude all recorded private/untracked files literally before Git indexing. No secrets/digests in report. Do not reintroduce fixed Watcher replay bug.
- [ ] Build reproducible wheel using fixed SOURCE_DATE_EPOCH and recorded Python/build/setuptools versions; install it separately with --no-deps and verify actual module path/metadata/CLI. Verify every artifact digest, replay exact clean bases, compare final trees and compile changed Python.
- [ ] Run a real-etcd cross-process smoke with the actual Nova and Masakari helpers in SEPARATE processes (oslo config registries conflict in one process): correlated intent -> actual Nova helper admission -> same-target denied/queued -> different-target admitted -> Nova completion/cooldown -> Masakari proof; duplicate and restart/unknown keep claims. External Nova DB/virt calls may be faked, but production helper/gate transitions must run. Test must clean only its own unique namespace.
- [ ] Russian guide: exact prerequisite checkout/patch order, actual local-wheel pip command for Masakari engine and every Nova compute Python>=3.11 environment, shared etcd initialize/configure/status/inspect/exact-revision resolution commands, default-disabled and no mixed workers, all-replica offline image/import/TLS checks, handling queued vs unknown vs cooldown, no blind retry after API timeout. Config change requires no active/pending intents and coordinated configs; failed quiescence remains blocked. Explain ordinary start/build/live/planned Mistral are outside this queue.
- [ ] Document safety/performance tradeoffs, source proof vs live proof, existing Nova2.53 state semantics and libvirt2.95 spawn-before-stop finding, global=3 not a load-tested capacity recommendation, no 1000-host claim. No new cloud actions in example verification commands.
- [ ] Final local tests, exact replay/manifests, independent whole-branch review, one consolidated final fix wave if needed and scoped re-review. Push the finished separate branch to existing origin under the user's publication request, verify remote SHA and unchanged main; no PR/merge/deploy unless separately requested. Keep worktrees and evidence.

## Plan self-review and interface gates

Each implementation task report carries RED/GREEN commands, frozen commit(s), exact public interfaces/config values and concerns. Root records any refinement before dependent dispatch. Task1 is the load-bearing protocol gate; Task2 demonstrates that completion/denial respects real Nova lifecycle; Task3 demonstrates batch behavior and intent correlation; Task4 proves delivery configuration; Task5 ties frozen trees together.

Verification of source baselines, setup, limits/clock behavior, repeated messages and malformed responses is not production/scale verification. Do not broaden/repeat passing suites without a changed area, failure or concrete doubt. Root runs only necessary socket/network commands outside sandbox and relays evidence; workers do not wait on hidden approval prompts.
