# Решения и издержки

Ниже все Ruling root из progress.md на момент поставки, в исходном
хронологическом порядке; формулировки и цена решения сохранены дословно.

1. Ruling: execute with SDD without another execution-choice question — user already approved implementation and prior skill workflow; cost is only agent/task organization, not expanded functional scope.

2. Ruling: keep Nova and Masakari test environments separate — Nova hacking6.1.0 conflicts with Masakari hacking<6.1; no production dependency change. Nova /tmp/masakari-evac-venv, Masakari/Kolla prior /tmp/watcher-hold-venv; cost is two dependency environments and subprocess separation.

3. Ruling: use complete Nova manager result plus fresh migration/instance validation — original manager can swallow some failures, so a normal callback return alone cannot release the slot; cost is two bounded per-VM DB reads.

4. Ruling: use native unittest plus fail-loud external syscall import shim locally — Nova native Linux symbol lookup prevents collection on macOS and pytest conflicts with Nova TestCase attribute cleanup; cost is explicitly limited Linux host proof, no production modification.

5. Ruling: automatic Nova COOLDOWN recovery is limited to a known duplicate migration at exact revision; unrelated orphaned cooldown uses existing operator CLI — frozen Guard API has no per-target blocker lookup and history scans in each poll are unsuitable for growing VM history; cost is operator intervention if a proven cooldown loses its finalizer and receives no duplicate RPC. Spec permits full-cooldown recovery without requiring automatic global scanning.

6. Ruling: enabled per-target mode must enumerate all Nova server pages before VMove creation — existing Masakari API.get_servers omits limit and python-novaclient18.9.0 returns one page; Nova default api.max_limit1000; cost is additional bounded-per-page API reads and the full source-host inventory in memory. Preserve disabled calls with optionalall_pages=False, enabledlimit=-1. This closes the approved all-VM requirement rather than expanding operation scope. Task3 plan/brief amended before dispatch.

7. Ruling: reuse existing delivery verifier --manifest rather than add/refactor an already implemented interface — source tools/watcher_automation_hold_delivery.py:214 provides the requested selector; cost is retaining the historical Watcher tool filename in the new guide, with explicit new manifest argument. Task5 plan/brief clarified; new artifact/replay tests still required.

8. Ruling: runtime Masakari guard requires enabled PowerOps and healthy source coordinator before inventory/VM effects — same prerequisite as approved Kolla/source-fencing contract; cost is explicit fail-closed refusal for inconsistent enabled configuration instead of independent unfenced dispatch. Task3 implementer informed; pool feeder must recheck own-recovery failure after capacity wait.

9. Ruling: enabled-mode notification preflight refuses dispatch/reserved-host activation if any existing VMove is FAILED — existing ParameterizedForEach can re-enter with still-PENDING VMs after failure, violating recovery stop; cost is deliberate operator recovery decision before remaining VMs of that failed notification continue. Pending records retained, disabled behavior unchanged, no new schema/retry redesign. Task3 brief amended and implementer approved this bounded change.

10. Ruling: enabled notification preflight also refuses existing ONGOING VMove — after engine crash the PENDING filter could skip an unresolved accepted request and report overall completion; cost is operator reconciliation before that notification can continue. No blind retry or record deletion. Task3 plan/brief refined.

11. Ruling: preserve existing Nova client HTTP timeout behavior in this kit — request cancellation is not established and the approved change concerns durable admission/concurrency; cost is a potentially blocked API/auth request retaining a bounded submission worker and source lock. Document this availability limit; no safety release on timeout.

12. Ruling: represent the already-applied Watcher/post-fence prerequisite as manifest dependency metadata and exact base trees, with separate old-manifest verification — existing verifier correctly confines artifact paths to its delivery directory; cost is two explicit manifest verification steps, without duplicated predecessor artifacts or relaxed path validation. Task5 interface context updated.

Уточнение пользователя во время Task4: обычные настроенные образы считаются
содержащими патчи и wheel. Отдельный image/tag override и обязательная проверка
содержимого образов не добавляются. Цена: фактическая готовность пользовательских
образов предполагается, а не доказывается локальным комплектом. Ранее
записанная строка preflight об offline проверках каждого образа заменена этим
уточнением. Текущие правила изложены в [инструкции](../../docs/MASAKARI-PER-TARGET-EVACUATION.md).
