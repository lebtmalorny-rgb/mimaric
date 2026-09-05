# Automatic Planned PowerOps Return Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Реализовать пять согласованных плановых сценариев, автоматическую передачу manifest и ручной аварийный возврат без повторного использования старого выключения.

**Architecture:** Mistral создаёт и однократно использует постоянную запись планового цикла в общем etcd. Masakari до recovery публикует отдельный аварийный запрет; ручной возврат требует серверного подтверждения resume. Опасные действия сохраняют общий host lock, а Kolla включает новый протокол только явным opt-in после проверки всех реплик.

**Tech Stack:** Python 3.11, Mistral/Masakari stable/2025.1 с существующими PowerOps patches, tooz/etcd3gw, etcd v3 transactions, openstacksdk 4.10.0, oslo.config, Ansible/Jinja, testtools, requests-mock.

**Spec:** `../specs/2026-09-05-powerops-planned-return-design.md`.

## Global Constraints

- Пять сценариев из раздела 1 спецификации; аварийный возврат ручной.
- `power_ops.planned_power_on` принимает только `host` и `segment_uuid`.
- Исходные `SHUTOFF` не запускаются; мигрировавшие ВМ обратно не возвращаются.
- Ironic power-only: `manageable`, `network_interface=noop`.
- Общий lock `powerops/host/<canonical-host>` сохраняется на всю непрерывную операцию.
- Записи `powerops/return/v1/hosts/<canonical-host>` и `powerops/return/v1/emergencies/<canonical-host>` не прикрепляются к lease процесса.
- `powerops_planned_return_enabled: "no"`; `[powerops] planned_return_enabled=false` по умолчанию.
- Не гарантировать rollback/disabled при недоступных API или утраченном lock.
- Нет автоматического повтора после неоднозначного timeout/504.
- Не менять старые hotfix 0001–0005 и не публиковать секреты.
- Образы собирает и переносит пользователь; никакого deploy/reconfigure/restart/BMC в этой работе.
- Сначала RED, затем минимальный код, GREEN, review и отдельный commit.

## 0. Порядок, рабочие копии и baseline

Независимый compatibility-патч выполняется по
`2026-09-05-powerops-nova-compatibility.md`. Ниже — зависимые части одного
межсервисного протокола, а не независимые проекты.

| Обозначение | Абсолютная рабочая копия | Исходная точка |
| --- | --- | --- |
| M | `/Users/dmitry/Desktop/ironic:mistral:masakari/powerops-patches/worktrees/mistral-powerops` | `7be711a`, затем compatibility commit |
| H | `/Users/dmitry/Desktop/ironic:mistral:masakari/powerops-patches/worktrees/masakari-powerops` | `9f3cb14`, проверить фактический HEAD |
| K | `/Users/dmitry/Desktop/ironic:mistral:masakari/powerops-patches/work/kolla-ansible` | `88c70e6` и существующие изменения пользователя |
| D | `/Users/dmitry/Desktop/ironic:mistral:masakari/powerops-patches/worktrees/publish-mistral-powerops-hotfixes` | `codex/powerops-planned-return`, spec commit `5a00e68` |

В M/H использовать source feature-ветки в существующих worktrees. K содержит
изменения defaults/register/registration tests: не включать их молча в новые
commits. На этапе K создать изолированную копию с явно зафиксированным нужным
baseline; перенос перекрывающихся изменений согласовать, не делать reset/stash
без отдельной причины. D не равен parent main и не должен его подменять.

- [ ] Проверить `git status --short --branch`, HEAD и worktree каждого проекта.
- [ ] В M запустить baseline:

```bash
.venv/bin/stestr --test-path=./mistral/tests/unit/actions/powerops run --concurrency=1
.venv/bin/python -m testtools.run mistral.tests.unit.api.v2.test_executions_powerops mistral.tests.unit.services.test_powerops
```

- [ ] В H запустить:

```bash
.venv/bin/python -m testtools.run masakari.tests.unit.powerops.test_coordination masakari.tests.unit.powerops.test_ironic masakari.tests.unit.engine.drivers.taskflow.test_powerops masakari.tests.unit.engine.drivers.taskflow.test_taskflow_driver
```

- [ ] В D запустить `python3 -B -m unittest tests.test_delivery_artifacts -v`.
  Сохранить фактические результаты, не выдавать исторические числа за свежие.
  Cross-repository suite имеет три известные устаревшие проверки; они отдельно
  обновляются в Task 8, а не скрываются.

## Карта файлов и интерфейсов

| Зона | Новый модуль | Ответственность |
| --- | --- | --- |
| M | `mistral/actions/powerops/return_state.py` | Формат v1, строгое чтение, CAS, emergency guard и одноразовые claims |
| M | `mistral/services/powerops_execution.py` | Проверка source execution и серверная авторизация ручного resume |
| M | `mistral/actions/powerops/planned_return.py` | Только автоматическое включение по серверной записи |
| H | `masakari/powerops/return_state.py` | Совместимый v1 encoder/reader и публикация emergency guard |
| D | `tests/fixtures/powerops-return-v1.json` | Общие golden wire fixtures, используемые обоими репозиториями |

Общие значения v1 определяются один раз в fixtures; source modules не
импортируют друг друга и не требуют нового общего пакета. Небольшое дублирование
wire codec контролируется одинаковыми fixtures и межрепозиторным тестом.

### Task 1: Строгий протокол состояния и CAS

**Files:** M `mistral/actions/powerops/return_state.py` (create),
`mistral/actions/powerops/coordination.py`, `mistral/actions/powerops/exceptions.py`;
create M `mistral/tests/unit/actions/powerops/test_return_state.py`,
`mistral/tests/unit/actions/powerops/state_fakes.py`; create D golden fixture.

**Interfaces:**
- `ReturnStateError(PowerOpsError)` с непустым безопасным сообщением.
- `Snapshot(cycle: dict | None, cycle_revision: int, emergency: dict | None, emergency_revision: int)`.
- `ReturnStateStore(transaction, host, owner_compare)`; owner_compare —
  проверка текущего значения lock, полученная от `OperationCoordinator`.
- `read() -> Snapshot`, `begin(snapshot, record) -> Snapshot`,
  `advance(snapshot, expected_state, new_record) -> Snapshot`,
  `claim(snapshot, action_id) -> Snapshot`, `assert_current(snapshot) -> None`,
  `require_no_emergency(snapshot) -> None`,
  `invalidate(snapshot, reason_code) -> Snapshot`,
  `finish_manual(snapshot, observed_emergency_revision) -> Snapshot`.
- `OperationCoordinator.return_state(host) -> ReturnStateStore` только внутри
  активного lock; отсутствие lock — отказ, не пустой owner_compare.

- [ ] **Step 1: Написать schema/transaction tests и golden fixtures.**
  Зафиксировать canonical host, exact keys, JSON types, numeric revisions,
  неизвестную версию, повреждённый JSON, отсутствие записи, аварийный запрет,
  отсутствие lease и stale revision. Пример запуска теста без внешних сервисов:

```python
from unittest import TestCase, mock
from mistral.actions.powerops.return_state import ReturnStateStore, ReturnStateError

class ReturnStateProtocolTest(TestCase):
    def test_malformed_transaction_reply_is_not_an_empty_store(self):
        transaction = mock.Mock(return_value={'succeeded': True})
        store = ReturnStateStore(transaction, 'compute-01', {
            'key': 'bG9jaw==', 'target': 'VALUE',
            'result': 'EQUAL', 'value': 'b3duZXI=',
        })
        with self.assertRaises(ReturnStateError):
            store.read()
```

- [ ] **Step 2: Run RED.**
  `.venv/bin/python -m testtools.run mistral.tests.unit.actions.powerops.test_return_state`.
  Сначала отсутствует новый модуль; после введения codec требуется отдельный
  RED на stale-CAS, а не только import failure.
- [ ] **Step 3: Реализовать codec и транзакции.** Основные точные builders:

```python
import base64
import json

def wire_bytes(value):
    return base64.b64encode(value.encode('utf-8')).decode('ascii')

def encoded_record(record):
    return wire_bytes(json.dumps(record, sort_keys=True, separators=(',', ':')))

def revision_compare(key, revision):
    if revision == 0:
        return {'key': wire_bytes(key), 'target': 'VERSION',
                'result': 'EQUAL', 'version': '0'}
    return {'key': wire_bytes(key), 'target': 'MOD',
            'result': 'EQUAL', 'mod_revision': str(revision)}
```

`read` делает одну transaction с двумя linearizable ranges. Полный wire reply
обязателен: header revision, ровно два range responses, 0/1 kv на exact key;
не путать transport error/повреждённый reply с отсутствием ключа. `advance`
сравнивает owner, обе revisions и ожидаемый state, затем put без lease.
Claim разрешён только `OFF_READY -> RETURNING`; повторный claim всегда отказ.
После неопределённого ответа записи перечитать состояние для диагностики,
но не повторять put автоматически. Deadline каждой transaction конечный.

`state_fakes.FakeTxn` должен исполнять subset etcd `VALUE/MOD/VERSION`, ranges,
put/delete, общий revision и atomic compare/write под `threading.Lock`.
Это тестовый transport, не mock самого `ReturnStateStore`. Добавить injectable
ошибку до/после commit и барьеры двух конкурирующих вызовов.

- [ ] **Step 4: GREEN и конкурирующие claims.** Два store с одним FakeTxn и
  одним исходным Snapshot: ровно один claim успешен; второй не пишет и не
  получает право на power-on. Подмена emergency revision также запрещает claim.
- [ ] **Step 5: Review/commit.**
  `feat: add durable one-use PowerOps return state protocol`.

### Task 2: Проверка source execution через engine, без service-account обхода

**Files:** create M `mistral/services/powerops_execution.py`; modify
`mistral/rpc/clients.py`, `mistral/engine/engine_server.py`,
`mistral/engine/default_engine.py`, `mistral/engine/base.py`;
create tests `mistral/tests/unit/services/test_powerops_execution.py`.

**Interfaces:**
- `get_powerops_source(source_execution_id) -> dict`: RPC под исходным
  authenticated Mistral context, без передаваемых caller roles/project.
- `validate_source(wf_ex, subject) -> dict` в новом service module.
- Возвращаемая проекция: `id`, `project_id`, `name`, `state`, `host`,
  `segment_uuid`. Она не возвращает raw output, token, arbitrary env.

- [ ] **Step 1: RED на source другого проекта и не-SUCCESS.**

```python
from types import SimpleNamespace
from unittest import TestCase
from mistral import exceptions
from mistral.services import powerops_execution

class SourceScopeTest(TestCase):
    def test_admin_does_not_reuse_another_projects_cycle(self):
        subject = SimpleNamespace(roles=['admin'], project_id='project-a')
        source = SimpleNamespace(
            id='source-1', project_id='project-b', state='SUCCESS',
            name='power_ops.planned_power_off',
            input={'host': 'compute-01', 'segment_uuid': 'segment-1'},
        )
        with self.assertRaises(exceptions.NotAllowedException):
            powerops_execution.validate_source(source, subject)
```

- [ ] **Step 2: Реализовать проверку и thin RPC adapters.**

```python
powerops.authorize(subject)
if wf_ex.project_id != subject.project_id:
    raise exceptions.NotAllowedException('PowerOps source project mismatch')
if (wf_ex.name != 'power_ops.planned_power_off'
        or wf_ex.state != states.SUCCESS):
    raise exceptions.InputException('PowerOps source is not a successful off')
return {
    'id': wf_ex.id, 'project_id': wf_ex.project_id,
    'name': wf_ex.name, 'state': wf_ex.state,
    'host': wf_ex.input['host'],
    'segment_uuid': wf_ex.input['segment_uuid'],
}
```

Перед индексированием input проверить mapping и canonical identifiers.
`DefaultEngine` читает DB в read-only transaction, проверяет текущий
`mistral.context.ctx()`. `EngineServer` восстанавливает rpc context по
существующему шаблону; `EngineClient` использует `auth_ctx.ctx()`.
Не читать чужие execution через OpenStack SDK connection служебного пользователя:
видимость Mistral определяется проектом вызывающего.

- [ ] **Step 3: GREEN.** Проверить source missing/deleted, чужое имя,
  ERROR/PAUSED/RUNNING, malformed input, member и неверные роли. RPC transport
  failure не даёт разрешения на питание. Source SUCCESS без записи Task 1
  не даёт права на включение.
- [ ] **Step 4: Review/commit.**
  `feat: validate planned shutdown provenance in Mistral engine`.

### Task 3: Сохранять плановый цикл при off/reboot

**Files:** M `planned.py`, `base.py`, `clients.py`, `config.py`,
`fakes.py`; create `test_planned_cycle.py` в PowerOps tests.

**Interfaces:**
- `CloudClients.snapshot_instances(host) -> list[dict]` с sorted UUID,
  `compute_host`, status и task state; сначала допустимое состояние всего набора.
- `apply_instance_policy(host, policy, on_stopped=None)` сохраняет прежний
  результат; optional callback `(server_id: str) -> None` вызывается только
  после подтверждённого SHUTOFF.
- `power_off_result(host, allow_hard_off) -> (node, hard_off_used: bool)`;
  старый `power_off` сохраняет node return value для совместимости callers.
- `PowerOpsAction` открывает store только при opt-in и передаёт его операции
  через `self._return_store`, не отдавая raw backend action input.

- [ ] **Step 1: RED на два ACTIVE плюс исходную SHUTOFF.** В событиях требуется
  `record PREPARING` до первой maintenance mutation; callback UUID каждого
  подтверждённого stop до следующего stop; `OFF_READY` только после stable-off.
  Добавить отказ после первого stop: первая ВМ остановлена, вторая ещё ACTIVE,
  запись не выдаёт право на planned on, питание не менялось.

```python
def test_stop_reports_only_confirmed_new_stops(self):
    raw = fakes.cloud(instances=[
        fakes.server('vm-active-b', 'compute-01', 'ACTIVE'),
        fakes.server('vm-off', 'compute-01', 'SHUTOFF'),
        fakes.server('vm-active-a', 'compute-01', 'ACTIVE'),
    ])
    cloud = clients.CloudClients(raw.connection, ha_adapter=raw.ha_adapter,
                                 sleep=lambda seconds: None)
    observed = []
    manifest = cloud.apply_instance_policy(
        'compute-01', 'stop', on_stopped=observed.append
    )
    self.assertEqual(['vm-active-a', 'vm-active-b'], manifest)
    self.assertEqual(manifest, observed)
```

Этот метод добавляется в existing CloudClients test fixture с тремя ВМ;
fixture создаётся через `fakes.cloud` и `CloudClients`, а не mock policy.

- [ ] **Step 2: Добавить opt-in и callback.**

```python
cfg.BoolOpt('planned_return_enabled', default=False,
            help='Enable the coordinated planned return protocol.')
```

В существующей stop loop после подтверждения состояния:

```python
stopped.append(server.id)
if on_stopped is not None:
    on_stopped(server.id)
self._pace_instances()
```

Store PREPARING содержит initial snapshot и context project/workflow/action ID.
Initial preflight при opt-in требует stable-on, Nova enabled/up, maintenance
false, отсутствие незавершённого цикла/emergency. Off обновляет список через
callback CAS; перед питанием сохраняется прежняя `assert_host_safe_for_power_off`.
При hard-off — `MANUAL_REQUIRED`, при подтверждённом soft-off — `OFF_READY`.
Reboot использует `PREPARING -> RETURNED`, не публикуя промежуточный OFF_READY.

- [ ] **Step 3: Ошибки и совместимость.** Opt-in false не создаёт записи;
  existing actions tests остаются зелёными. Callback/storage failure запрещает
  дальнейшие stop/power. Ошибка после записи OFF_READY, но до SUCCESS engine,
  блокирует automatic on через Task 2. Сбой записи manual-required оставляет
  предыдущую незавершённую запись, которая тоже блокирует автоматический claim.
- [ ] **Step 4: Run GREEN.**
  `.venv/bin/stestr --test-path=./mistral/tests/unit/actions/powerops run --concurrency=1`.
- [ ] **Step 5: Review/commit.**
  `feat: record planned shutdown and reboot lifecycle`.

### Task 4: Согласованный аварийный запрет Masakari

**Files:** create H `masakari/powerops/return_state.py`,
`masakari/tests/unit/powerops/test_return_state.py`; modify
`masakari/conf/powerops.py`, `masakari/engine/manager.py`,
`masakari/engine/drivers/taskflow/driver.py`,
`masakari/tests/unit/engine/test_engine_mgr.py`,
`masakari/tests/unit/engine/drivers/taskflow/test_taskflow_driver.py`.

**Interfaces:**
- `mark_emergency(host, notification_uuid, transaction) -> int` возвращает
  подтверждённую mod_revision guard; не требует host lock, не снимает запрет.
- `require_emergency(host, notification_uuid, transaction) -> None` fail-closed
  перед dispatch driver; читает без stale read и проверяет ожидаемую notification.
- Codec использует те же golden fixtures, что Task 1.

- [ ] **Step 1: RED на порядок и отказ marker write.** Добавить к существующему
  valid STOPPED/NORMAL notification test attached mock parent с событиями
  `mark`, `host_save`, `execute_host_failure`; `mark` обязан быть первым.
  При исключении mark оба следующих вызова отсутствуют, notification ERROR.

```python
events = mock.Mock()
events.attach_mock(mark_emergency, 'mark')
events.attach_mock(host_obj.save, 'save')
events.attach_mock(self.engine.driver.execute_host_failure, 'recover')
self.engine._handle_notification_type_host(self.context, notification)
self.assertEqual('mark', events.mock_calls[0][0])
```

Вставить в existing fixture `EngineManagerUnitTestCase`; host_obj и notification
получены его `_get_fake_host`/`_get_compute_host_type_notification`.

- [ ] **Step 2: Реализовать marker до maintenance.** В valid STOPPED ветви,
  после разрешения host, до `host_obj.update/save`:

```python
if CONF.powerops.planned_return_enabled:
    return_state.mark_emergency(host_name, notification.notification_uuid,
                                transaction)
```

`transaction` здесь — bound etcd client transaction с конечным timeout,
созданный через существующую конфигурацию coordinator; открытие/закрытие
client окружить context manager. Ошибку включить в существующий путь ERROR
notification, не оставлять её до try-блока обработки recovery.
Driver проверяет marker внутри общего lock до `_dispatch_host_failure`.
Не переносить marker в IronicFenceTask: это слишком поздно.

- [ ] **Step 3: Проверить новые notification revisions и opt-in.** Новый marker
  заменяет предыдущий через CAS; повтор той же notification идемпотентен и не
  снимает блокировку. STARTED/invalid/ignored не пишут marker. При opt-in false
  legacy flow не обращается к новому namespace. Mixed replicas допустимы только
  с отключённой новой автоматикой.
- [ ] **Step 4: GREEN.**

```bash
.venv/bin/python -m testtools.run masakari.tests.unit.powerops.test_return_state masakari.tests.unit.engine.test_engine_mgr masakari.tests.unit.engine.drivers.taskflow.test_taskflow_driver masakari.tests.unit.engine.drivers.taskflow.test_powerops
```

- [ ] **Step 5: Review/commit.** `feat: invalidate planned return on host recovery`.

### Task 5: Автоматическое planned power-on

**Files:** create M `mistral/actions/powerops/planned_return.py`,
`mistral/tests/unit/actions/powerops/test_planned_return.py`; modify
`clients.py`, `base.py`, `setup.cfg`, `services/powerops.py`,
`etc/mistral/power_ops.yaml`, `test_workbook.py`, registration tests.

**Interfaces:**
- `PlannedPowerOnAction(host, segment_uuid).run(context)` — новая entry point
  `powerops.planned_power_on`.
- `CloudClients.validate_return_inventory(host, record, phase) -> None`;
  phase `before_power_on` или `before_start`, exact membership/placement/states.
- `wait_fresh_nova_service(host, started_at_utc) -> service` требует
  disabled/up и `updated_at > started_at_utc`; отсутствие/невалидное время — отказ.
- Existing `start_instances(host, ids)` сохраняется для callers. Новый путь
  до него требует отсутствие неожиданного ACTIVE в manifest.
- Успешный action result: `host`, `operation='planned_power_on'`,
  `source_execution_id`, `cycle_id`, `stopped_instance_ids` из записи,
  `power_state='power on'`, `nova_enabled=True`, `masakari_maintenance=False`.
  Эти итоговые значения возвращаются только после read-back и финального CAS.

- [ ] **Step 1: RED на opt-in false до I/O, missing record, replay claim,
  чужой проект/source/host/segment, emergency, changed VM inventory.**
  Добавить real-action тест с `fakes.cloud` и store Task 1; deny-path требует
  `set_node_power_state.assert_not_called()`, а не только текст ошибки.
- [ ] **Step 2: Реализовать порядок в одной host lock.**

```python
snapshot = store.read()
store.require_no_emergency(snapshot)
record = snapshot.cycle
source = rpc.get_engine_client().get_powerops_source(record['source_execution_id'])
cloud.validate_return_inventory(self.host, record, 'before_power_on')
claimed = store.claim(snapshot, context.execution.action_execution_id)
started_at = datetime.now(timezone.utc)
cloud.power_on(self.host)
cloud.wait_fresh_nova_service(self.host, started_at)
cloud.validate_return_inventory(self.host, record, 'before_start')
cloud.start_instances(self.host, record['stopped_instance_ids'])
cloud.enable_nova(self.host)
cloud.set_masakari_maintenance(self.segment_uuid, self.host, False)
```

До claim отдельно проверить, что record существует/OFF_READY; source projection
точно совпадает с record/input/project, Ironic UUID неизменен, питание stable-off,
Nova disabled и maintenance true. Перед каждой штатной mutation вызывать
`store.assert_current(claimed)` через CloudClients health hook. После claim
protected-error path включает fail-safe и запись MANUAL_REQUIRED. Protective
disable/maintenance используют lock health без требования отсутствия emergency.
После успешного read-back обеих сервисных записей CAS `RETURNING -> RETURNED`.

- [ ] **Step 3: Добавить публичный workflow без паузы.**

```yaml
  planned_power_on:
    input:
      - host
      - segment_uuid
    tasks:
      power_on:
        action: powerops.planned_power_on
        input:
          host: <% $.host %>
          segment_uuid: <% $.segment_uuid %>
        publish:
          result: <% task().result %>
    output:
      result: <% $.result %>
```

Добавить имя в общий RBAC allowlist, entry point, exact parser tests.
Не использовать `stale_domains_checked`, source ID или manifest из env.

- [ ] **Step 4: GREEN на все пять сценариев.** Использовать завершённый off
  из Task 3, тот же FakeTxn и snapshot реальных fake resources. ВМ ACTIVE/SHUTOFF
  проверяются после всей цепочки. Migration fixture после переноса возвращает
  только host-filtered resources; никакой обратной migration при on.
  Свежий heartbeat задавать контролируемыми UTC timestamps; stale up не проходит.
- [ ] **Step 5: Review/commit.** `feat: automatically return planned powered-off hosts`.

### Task 6: Trusted ручной resume и очистка аварийного запрета

**Files:** M `services/powerops_execution.py`, `api/controllers/v2/execution.py`,
`engine/default_engine.py`, `engine/actions.py`, `rpc/clients.py`,
`engine/engine_server.py`, `return_host.py`; create
`tests/unit/engine/test_powerops_resume.py`,
`tests/unit/api/v2/test_powerops_resume.py`; extend PowerOps action tests.

**Interfaces:**
- `authorize_resume(wf_ex, subject, env) -> dict`: typed grant с nonce,
  workflow ID, gate task ID, target host/segment/project и состоянием `issued`.
- `claim_powerops_resume(action_execution_id, nonce) -> dict`: RPC/DB атомарно
  связывает одноразовый grant с фактическим return task/action; возвращает
  approved host/segment. Роли/идентичность берутся из authenticated context.
- `ReturnToServiceAction` требует exact Boolean плюс успешный claim; env не
  создаёт grant. Не менять формат mistral-lib ExecutionContext повторно.

- [ ] **Step 1: RED через реальный engine pause.** В engine base test загрузить
  настоящий workbook; внешние OpenStack APIs заменить `fakes.cloud`. Дождаться
  PAUSED: gate IDLE, return task ещё не исполнялся. Без `stale_domains_checked`
  resume отклоняется. Прямой ReturnToServiceAction с `True`, но без grant,
  отклоняется до OpenStack I/O.
- [ ] **Step 2: Авторизовать в engine transaction, не только API.**

```python
with db_api.transaction():
    db_api.acquire_lock(db_models.WorkflowExecution, wf_ex_id)
    wf_ex = db_api.get_workflow_execution(wf_ex_id)
    if powerops.is_powerops_resume_workflow(wf_ex.name):
        grant = powerops_execution.authorize_resume(wf_ex, context.ctx(), env)
        runtime = dict(wf_ex.runtime_context or {})
        runtime[powerops.POWEROPS_RESUME_AUTH_KEY] = grant
        wf_ex.runtime_context = runtime
    wf_handler.resume_workflow(wf_ex, env=env)
```

`authorize_resume` допускает только текущий PAUSED workflow, единственный gate
`operator_inspection_gate` в IDLE, отсутствие уже начатого return и exact env
`{'stale_domains_checked': True}`. Повторно выдать использованный grant нельзя.
API делает ранний RBAC/reject_reserved_fields, engine повторяет окончательную
проверку. Description-only updates других workflow не затрагиваются.

- [ ] **Step 3: Атомарный claim и actual action связь.** Engine RPC читает
  action/task/workflow из DB, проверяет их принадлежность и nonce grant,
  обновляет grant `issued -> consumed` под workflow DB lock. Заявленный input
  host/segment сравнивается с grant до I/O. Повтор action delivery не получает
  новый grant. Generic workflow/rerun не может создать его из input/env.
- [ ] **Step 4: Связать с durable state.** Power-on-for-inspection инвалидирует
  старый off receipt до питания. Ручной return фиксирует emergency revision;
  при аварии допускается только пустой restart manifest. После успешной проверки,
  сервисных read-backs и trusted claim `finish_manual` одним CAS завершает цикл
  и удаляет именно наблюдённый emergency marker. Новая revision запрещает clear
  и вызывает protective fail-safe; переключение opt-in само marker не удаляет.
- [ ] **Step 5: GREEN engine/API/action.**

```bash
.venv/bin/python -m testtools.run mistral.tests.unit.engine.test_powerops_resume mistral.tests.unit.api.v2.test_powerops_resume mistral.tests.unit.engine.test_workflow_resume mistral.tests.unit.engine.test_task_pause_resume
.venv/bin/stestr --test-path=./mistral/tests/unit/actions/powerops run --concurrency=1
```

Дополнительно: wrong project, direct RPC, used grant, wrong gate, duplicate
resume, env-only injection, state SUCCESS без proof, task rerun, emergency
revision changed while returning. Тестировать настоящий action context
propagation, не подставлять grant непосредственно в конечный action во всех
положительных тестах.
- [ ] **Step 6: Review/commit.** `fix: require trusted one-use PowerOps manual resume`.

### Task 7: Opt-in и проверка всех реплик в Kolla-Ansible

**Files (K):** `ansible/group_vars/all.yml`,
`ansible/roles/mistral/templates/mistral.conf.j2`,
`ansible/roles/masakari/templates/masakari.conf.j2`,
`ansible/roles/mistral/tasks/precheck.yml`,
`ansible/roles/mistral/tasks/powerops.yml`,
`kolla_ansible/tests/unit/test_powerops_templates.py`,
`kolla_ansible/tests/unit/test_powerops_configuration_contract.py`,
`kolla_ansible/tests/unit/test_powerops_registration.py`.

**Interfaces:** единственный новый globals flag из спецификации; runtime
modules M/H экспортируют `RETURN_STATE_PROTOCOL_VERSION = 1` и marker/claim
callables. Reconcile добавляет новую action/workflow без удаления старых имён.

- [ ] **Step 1: RED рендера с opt-in false/true, trim_blocks false/true.**
  Через существующий Jinja test helper отрендерить оба ini и распарсить
  `configparser`. Проверить отдельные `[coordination]`/`[powerops]`, никакого
  склеивания URL и заголовка секции. Default false обязателен.
- [ ] **Step 2: Рендер и preflight.**

```yaml
powerops_planned_return_enabled: "no"
```

```jinja2
planned_return_enabled = {{ powerops_planned_return_enabled | bool | lower }}
```

При true require `enable_powerops`, etcd backend и согласованные images.
Проверку Python module версии/entry-point loading запускать для каждой
Mistral API/engine/executor и Masakari engine реплики, не `run_once` на одном
controller. Проверка не запускает workflow и не выдаёт успешный live power test.
Новая entry point:

```python
required = {'powerops.planned_power_on'}
found = {entry.name for entry in metadata.entry_points(group='mistral.actions')}
assert required <= found
assert return_state.RETURN_STATE_PROTOCOL_VERSION == 1
```

Фактические imports берутся из сервиса проверяемой реплики. Для Mistral
дополнительно проверять наличие новых EngineClient/EngineServer RPC methods;
для Masakari — marker callable. Сверка namespace/auth etcd и факт обновления
всех образов обязательны в runbook; module import не доказывает работающий quorum.
- [ ] **Step 3: GREEN локальных tests.** Использовать M `.venv/bin/python`
  как известный interpreter с Jinja из каталога K, не устанавливая весь Kolla:

```bash
/Users/dmitry/Desktop/ironic:mistral:masakari/powerops-patches/worktrees/mistral-powerops/.venv/bin/python -m unittest kolla_ansible.tests.unit.test_powerops_templates kolla_ansible.tests.unit.test_powerops_configuration_contract kolla_ansible.tests.unit.test_powerops_registration -v
```

- [ ] **Step 4: Review/commit scoped K changes.**
  `feat: opt in coordinated planned PowerOps return`.

### Task 8: Сквозные контракты, доставка и границы доказательств

**Files (D):** `tests/test_cross_repository_contract.py`,
`tests/test_delivery_artifacts.py`, `tests/fixtures/powerops-return-v1.json`,
create `tests/test_planned_return_delivery.py`,
create `hotfixes/planned-return/README.md`, `hotfixes/planned-return/ACCEPTANCE.md`,
`hotfixes/planned-return/SHA256SUMS`; новые format-patch artifacts по репозиториям.

- [ ] **Step 1: Обновить только устаревшие assertions.** Проверка RBAC должна
  подтверждать shared authorize + runtime authorization tests, а не inline if.
  Jinja проверять через rendered ini, а не единственное написание conditional.
  Manifest проверять как validate-all-before-first-start и serial mutation loop,
  а не считать количество всех циклов. Добавить новый workflow/entry point и
  одинаковую v1 schema, сохранив прежние safety-инварианты.
- [ ] **Step 2: Полная матрица fault injections.** Каждый сценарий проходит
  real actions, transport fakes и реальный parser/engine где применимо:

| Группа | Требуемые случаи |
| --- | --- |
| Пять штатных сценариев | empty; stop ACTIVE+SHUTOFF; migration; empty on; manifest on |
| Провенанс | старое выключение без receipt; source ERROR/deleted; wrong host/project; replay |
| Гонки | два claims; marker before/during on; новая авария при clear; duplicate delivery |
| Частичные мутации | stop/start/migration после первого успеха; timeout до/после etcd/API apply |
| Gate | PAUSED/IDLE; direct action; direct RPC; env injection; task rerun; grant reuse |
| Состояния | stale heartbeat; unexpected ACTIVE; unknown VM/task/power state; changed UUID |
| Rollout | default false; mixed modules; old templates; malformed receipt version |

- [ ] **Step 3: Выполнить все source suites, HTTP audit и cross-repo checks.**
  В D задать именно реальные checkout paths:

```bash
python3 -B -m unittest tests.test_delivery_artifacts tests.test_planned_return_delivery -v
POWEROPS_MISTRAL_TREE=/Users/dmitry/Desktop/ironic:mistral:masakari/powerops-patches/worktrees/mistral-powerops \
POWEROPS_MASAKARI_TREE=/Users/dmitry/Desktop/ironic:mistral:masakari/powerops-patches/worktrees/masakari-powerops \
POWEROPS_KOLLA_TREE=/Users/dmitry/Desktop/ironic:mistral:masakari/powerops-patches/work/kolla-ansible \
python3 -B -m unittest tests.test_cross_repository_contract -v
git diff --check
```

Если Task 7 выполнялся в отдельной новой K-копии, в команде явно заменить
только POWEROPS_KOLLA_TREE на зафиксированный путь этой копии и записать HEAD.
Отчитаться о всех failures, не только о зелёной подвыборке. В source M/H
сохранить raw stdout test runs отдельно от патчей.
- [ ] **Step 4: Упаковать через `git format-patch`, не переписывать patch
  файлы через текстовый редактор.** Отдельные серии M/H/K, отдельные README
  с base/HEAD, порядок включения opt-in и rollback. `SHA256SUMS` покрывает
  точный набор новых patch files. На чистых scratch trees выполнить apply,
  reverse-check каждого шага и сравнение итоговых source bytes.
- [ ] **Step 5: Документировать runtime acceptance без запуска.** Указать
  точные три `powerops_mistral_*_tag` и `powerops_masakari_engine_tag`, обязательную
  согласованность версий. Старые off без receipt возвращаются вручную. При etcd
  restore автоматика отключается до сверки. Локальная приёмка не доказывает
  BMC/TLS/RBAC/storage/network readiness. Результат status не разрешает mutation.
- [ ] **Step 6: Review и публикация отдельной ветки.** После явного требования
  публикации сверить remote, local commit и `git ls-remote`, не делать force push
  и не менять main. До публикации все source commits и artifacts перечислены
  в delivery README; исходные пять hotfix-патчей побайтно сохранены.

## Self-review плана (2026-09-05)

- [x] Разделы spec 1/4/7 покрываются Task 3/5 и матрицей Task 8.
- [x] Разделы 5/6: Task 1/4/6; marker публикуется до maintenance и ожидания lock.
- [x] Разделы 8/9: failure injection, legacy отдельным планом, opt-in Task 7.
- [x] Не добавлены автоматическая evacuation/очистка domains/обратная migration.
- [x] RPC source использует caller context, не credentials сервисного проекта.
- [x] Protective calls допускают emergency marker, но не потерю lock.
- [x] Новые публичные symbols объявлены в Interfaces задачи-производителя.
- [x] Никаких success claims по стенду; review после каждого source patch.

Проверен синтаксис 16 Python fragments двух планов; это не их исполнение и
не результат будущих runtime tests. Delivery baseline: 12 tests прошли.

## Execution handoff

Реализация ещё не выполнена. Возможны task-by-task исполнение с отдельным
implementer/reviewer или inline исполнение через `executing-plans` с теми же
review checkpoints. Способ исполнения согласуется с пользователем; данный
документ сам по себе не разрешает build/deploy или реальные power actions.
