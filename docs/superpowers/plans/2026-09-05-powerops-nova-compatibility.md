# PowerOps Nova Compatibility Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Исправить legacy Nova disable/enable без изменения современной ветви и глобальной microversion.

**Architecture:** Передавать проверенные host/binary в существующие методы SDK. Выбор legacy/modern endpoint остаётся ответственностью SDK. Проверки состояния, deadline и PowerOps lock не меняются.

**Tech Stack:** Python 3.11, Mistral stable/2025.1 с hotfix 0001–0005, openstacksdk 4.10.0, testtools, requests-mock.

**Spec:** `../specs/2026-09-05-powerops-planned-return-design.md`, раздел 9.

## Global Constraints

- Не менять глобальную microversion и версии библиотек.
- Не изменять Ironic, Masakari, TLS/RBAC и конфигурацию стенда.
- Не запускать реальные OpenStack/BMC запросы; `requests_mock.Mocker(real_http=False)`.
- Существующие hotfix 0001–0005 не переписываются.
- Сохранить read-back, deadline, исходную ошибку и владение host lock.

## Рабочие копии

Все относительные source-пути ниже относятся к
`/Users/dmitry/Desktop/ironic:mistral:masakari/powerops-patches/worktrees/mistral-powerops`.
Исходный HEAD: `7be711a`. Перед началом проверить `git status --short --branch`.
Создать source-ветку `feat/powerops-planned-return` в существующей изолированной
копии, не создавая дополнительный worktree и не изменяя базовую ветку hotfix.
Не переустанавливать рабочий `.venv` и editable mistral-lib.

Delivery-копия:
`/Users/dmitry/Desktop/ironic:mistral:masakari/powerops-patches/worktrees/publish-mistral-powerops-hotfixes`,
ветка `codex/powerops-planned-return`. Несмотря на имя каталога, это новая ветка.

### Task 1: Явные параметры Nova service

**Files:**
- Modify: `mistral/actions/powerops/clients.py`, `disable_nova` и `enable_nova`.
- Modify: `mistral/tests/unit/actions/powerops/fakes.py`, fake enable/disable.
- Test: `mistral/tests/unit/actions/powerops/test_clients.py`.
- Modify/Test (delivery): `hotfixes/mistral-masakari-v1-uuid/verify_sdk_contracts.py`.

**Interfaces:**
- Consumes: `CloudClients.nova_service(host)` возвращает точный `nova-compute` service.
- Produces: те же `disable_nova(host, reason)` и `enable_nova(host)`; новых API нет.

- [ ] **Step 1: Добавить regression test legacy HTTP в `SDKContractAudit`.**

В каждом тесте setup создаёт свежий proxy. До первого обращения к compute
заменить discovery fixture и ответ списка сервисов:

```python
def test_legacy_nova_disable_enable_has_host_and_binary(self):
    self.http.get('http://nova.example/v2.1', json={'version': {
        'id': 'v2.1', 'status': 'CURRENT',
        'min_version': '2.1', 'version': '2.52',
        'links': [{'rel': 'self', 'href': 'http://nova.example/v2.1/'}],
    }})
    self.service['id'] = 42
    calls = []

    def update(request, context):
        body = request.json()
        calls.append(body)
        self.assertEqual(self.host, body['host'])
        self.assertEqual('nova-compute', body['binary'])
        self.service['status'] = (
            'enabled' if request.path.endswith('/enable') else 'disabled'
        )
        return {'service': dict(self.service)}

    self.http.put('http://nova.example/v2.1/os-services/disable-log-reason',
                  json=update)
    self.http.put('http://nova.example/v2.1/os-services/enable', json=update)
    self.cloud.disable_nova(self.host, 'PowerOps planned operation')
    self.cloud.enable_nova(self.host)
    self.assertEqual([
        {'host': self.host, 'binary': 'nova-compute',
         'disabled_reason': 'PowerOps planned operation'},
        {'host': self.host, 'binary': 'nova-compute'},
    ], calls)
    self.assertEqual('enabled', self.service['status'])
```

Запускать именно изменённую delivery-копию, не одноимённый старый файл:

```bash
.venv/bin/python -B ../publish-mistral-powerops-hotfixes/hotfixes/mistral-masakari-v1-uuid/verify_sdk_contracts.py
```

- [ ] **Step 2: Подтвердить RED.** Ожидается несовпадение host/binary с `None`
  в legacy PUT, а не ошибка импорта/сети. Существующий modern test должен пройти.

- [ ] **Step 3: Изменить два существующих вызова внутри `_mutation`.**

```python
self.connection.compute.disable_service(
    service, host=host, binary='nova-compute', disabled_reason=reason
)
self.connection.compute.enable_service(
    service, host=host, binary='nova-compute'
)
```

Не добавлять свою развилку по номеру версии. В fakes сделать параметры
явными, сохранив существующие события и мутацию состояния:

```python
def disable_service(item, host=None, binary=None, disabled_reason=None):
    assert host == item.host
    assert binary == 'nova-compute'
    events.append(('disable', item.id, disabled_reason))
    item.status = 'disabled'

def enable_service(item, host=None, binary=None):
    assert host == item.host
    assert binary == 'nova-compute'
    events.append(('enable', item.id))
    item.status = 'enabled'
```

Обновить assertions `assert_called_once_with` существующих unit tests,
но не разрешать произвольные `**kwargs`, маскирующие ошибочные имена параметров.

- [ ] **Step 4: Добавить граничный modern discovery test.** Повторить modern
  `test_nova_disable_and_enable` с максимумом `2.53`, проверяя PUT по UUID,
  body `status/disabled_reason`, без `host/binary` в modern JSON. Для него
  проверять header `compute 2.53`; тест с максимумом `2.96` и прежним ожидаемым
  header оставить отдельным. Конкретный callback:

```python
def update_253(request, context):
    self.assertEqual('compute 2.53', request.headers['OpenStack-API-Version'])
    self.assertNotIn('host', request.json())
    self.assertNotIn('binary', request.json())
    self.service.update(request.json())
    return {'service': dict(self.service)}
```

- [ ] **Step 5: Проверить полный source-набор и HTTP audit.**

```bash
.venv/bin/stestr --test-path=./mistral/tests/unit/actions/powerops run --concurrency=1
.venv/bin/python -B ../publish-mistral-powerops-hotfixes/hotfixes/mistral-masakari-v1-uuid/verify_sdk_contracts.py
git diff --check
```

Ожидается: все исходные 130 PowerOps tests плюс добавленные tests проходят;
legacy и обе modern HTTP ветви проходят. Число отчитать из свежего результата.

- [ ] **Step 6: Review и отдельный source commit.** Проверить diff на отсутствие
  изменений discovery/auth/transport, получить review и устранить замечания.

```bash
git add mistral/actions/powerops/clients.py mistral/tests/unit/actions/powerops/fakes.py mistral/tests/unit/actions/powerops/test_clients.py
git commit -m "fix: pass Nova service identity for legacy API updates"
```

SDK audit сохранить отдельным delivery commit при упаковке серии; не смешивать
source и delivery Git repositories одним `git add`.

## Критерий завершения

Проходит реальный SDK с перехваченным HTTP для `2.52`, `2.53` и более нового
discovery. Read-back не удалён. Нет запросов к стенду. Патч независимо
накладывается после source `7be711a`. После этого переходить к основному плану
`2026-09-05-powerops-planned-return.md`.
