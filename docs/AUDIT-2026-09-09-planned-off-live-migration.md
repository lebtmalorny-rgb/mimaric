# Проверка планового выключения с live migration — 2026-09-09

## Вывод

На исходниках Mistral из пользовательского архива `0809` штатный сценарий
`power_ops.planned_power_off`, `instance_policy=live_migrate` прошёл локально,
включая настоящий engine, поставляемый YAML, executor, action и openstacksdk.
Ответы внешних OpenStack API имитировались, coordination backend заменён fixture.
Это не запуск на стенде, не проверка собранного образа и не реальная миграция ВМ.

Последний патч Masakari добавляет ожидание Nova disabled/down после аварийного
fencing. Он не включается в плановый Mistral workflow и не меняет его алгоритм.
Maintenance по-прежнему препятствует приёму нового уведомления Masakari.

Безусловное «всё сработает на стенде» не подтверждено: требуются корректные
образы, права API, отключённый SDK response cache, работоспособная coordination
и готовое назначение. Сохранились ограничения после evacuation и для SHUTOFF-ВМ.

## Точная база

- Архив: `mistral-integration-powerops-mistral-2025.1 _0809.zip`.
- SHA256: `3df7cd4afa9052251107335b0ec5771c2704ccf03894c7e6c1f34880a43daf0c`.
- В нём уже присутствует `live_migration.py` из этапа 1. Повторное наложение
  того же патча для этой проверки не требовалось.
- В отличие от локальной ветки Mistral `fix/planned-live-migration-wait`
  (`f9e57d7`), архив дополнительно содержит авторизацию через RPC request context
  и передачу host/binary при disable/enable Nova service. Проверялся архив,
  а не только эта более старая локальная ветка.
- Masakari: `fix/powerops-post-fence-nova-down`,
  `aabc8c0a9a874c798ff0c50139d15ed10472bd77`.
- `planned-return-v2` не исследовался, не включался и не требуется этому пути.

Локальное окружение Mistral: Python 3.11, openstacksdk 4.10.0,
keystoneauth1 5.17.0, setuptools 80.10.2, eventlet 0.41.2.
Metadata установленного локального mistral-lib: `0.0.1.dev1` (editable source).
Это не идентичный стендовому образу набор зависимостей; проверка образа с его
реальными RPM/venv остаётся отдельной обязательной стадией.

## Фактические прогоны

| Проверка | Результат |
|---|---|
| PowerOps на неизменённом архиве 0809 | 180 тестов: 178 успешно, 2 ошибки fixtures |
| Тот же набор после актуализации только HTTP fixture во временной копии | 180/180 успешно |
| Дополнительные сценарии через DefaultExecutor и SDK | 8/8 успешно |
| Поставляемый YAML через настоящий локальный engine и SQLite | 2/2 успешно |
| Masakari HA API и post-fence Nova-down проверки на последнем коммите | 70/70 успешно |

Два исходных сбоя: `test_sdk_http.SDKContractAudit.test_live_migration_and_source_empty_guard`
и `test_planned_live_migration_off_on_http`. Старый fixture не регистрировал
`GET /os-migrations`, не возвращал явный `task_state` и ожидал POST microversion
2.30 вместо нового 2.59. Ошибка `NoMockAddress` возникала до отправки миграции.

Во временной копии исправлены только эти имитации: история с новой UUID,
переходы accepted → preparing → running → post-migrating → completed,
явный task_state и ожидание 2.59. Производственный код для получения PASS
не изменялся. Эти тестовые изменения не внесены в Git и не опубликованы;
их стоит перенести отдельным небольшим тестовым изменением.

В новом engine-harness исправлены собственные ошибки аргумента `wf_input`
и порядка импорта eventlet; итоговые два workflow прошли без прежних фоновых
ошибок operation queue. Первоначальный запуск Masakari в sandbox остановлен
из-за ограничений локальных сокетов; повторный stestr с разрешённым loopback
завершился успешно. OpenStack HTTP во всех прогонах перехватывался mocks.

## Подтверждённый порядок

1. Авторизация и блокировка точного исходного хоста.
2. Masakari maintenance=true с readback.
3. Nova disabled/up с readback.
4. Для каждой ACTIVE ВМ последовательно: исходная история, один POST миграции,
   ожидание новой completed migration UUID и стабильных ACTIVE/destination/null.
5. Повторная проверка миграций хоста и перемещённых ВМ, затем пустоты source.
6. Только затем Ironic soft power off и подтверждение стабильного power off.
7. Workflow SUCCESS, Nova disabled, Masakari maintenance=true,
   stopped_instance_ids=[]. ВМ остаются на назначении.

Плановый путь не ждёт Nova down после выключения: распространение этого состояния
может запаздывать за SUCCESS. Новый post-fence gate относится к аварийной эвакуации.

Проверки error/timeout миграции, потери ответа POST, потери lock, неоднозначной
истории, HTTP 403, занятого task_state и новой ВМ на source не разрешают power-off.
Проверен и частичный успех двух ВМ: успех первой не даёт выключить source,
если вторая не завершила миграцию. При обычном отказе source остаётся включённым,
Nova disabled и maintenance=true; потеря lock не разрешает обходить блокировку
для fail-safe мутаций. ERROR не отменяет уже принятый Nova запрос миграции.

## Существенные ограничения для следующего стендового теста

- **После evacuation:** запись `migration_type=evacuation, status=done` блокирует
  новую плановую миграцию либо финальную проверку хоста. Это воспроизведено через
  реальный executor/SDK. Просто ACTIVE ВМ на назначении недостаточно. В Nova 2025.1
  такие записи участвуют в cleanup прежнего source; не следует принудительно
  переписывать их статус или считать все done безопасными.
  [Исходник Nova cleanup](https://raw.githubusercontent.com/openstack/nova/stable/2025.1/nova/compute/manager.py).
- **SHUTOFF ВМ:** live_migrate требует ACTIVE для всех исходных ВМ. ВМ после
  аварийной эвакуации в SHUTOFF будет отвергнута до POST. Cold migration и запуск
  выключенных ВМ не добавлены этим этапом.
- **Права и кеш:** нужны Nova >=2.59, доступ ко всем проектам и расширенным
  host/task полям, глобальной истории и live migration; cache_enabled должен
  быть False. Патч Masakari эти настройки Mistral не меняет.
- **Авария во время планового обслуживания:** maintenance не обеспечивает
  автоматический planned → emergency handoff. Отказ source во время миграции
  требует разбора; этот сценарий не превращён в автоматическую эвакуацию.
- **Пустота Nova не равна инвентаризации гипервизора:** SSH/libvirt-проверок нет.
  Последнее чтение Nova и выключение Ironic не являются общей транзакцией;
  параллельные прямые действия операторов через Nova должны быть исключены.
- Реальные etcd, роли, RabbitMQ, multi-cell, сеть миграции, Ceph/libvirt,
  доступность BMC, нагрузка и жёсткие пределы блокирующих системных вызовов
  этим прогоном не доказаны.

Для подтверждения завершённых live migrations требуется глобальная история,
а не только `/servers/{id}/migrations`: последний API показывает текущие миграции.
[Nova API](https://docs.openstack.org/api-ref/compute/#server-migrations-servers-migrations).

## Воспроизведение локальной проверки

Временная распаковка и диагностические тесты сохранены в:

```text
/private/tmp/planned-migration-audit.JE2F5m/mistral-integration-powerops-mistral-2025.1
```

В ней, с `.venv/bin/python` исходного worktree Mistral:

```bash
python -m unittest discover -s mistral/tests/unit/actions/powerops -p 'test_*.py' -q
python -m unittest test_planned_engine_audit test_planned_scenario_audit -q
```

Для Masakari в его worktree, с разрешёнными локальными тестовыми сокетами:

```bash
.venv/bin/stestr run --concurrency 2 'masakari.tests.unit.ha.test_api|masakari.tests.unit.engine.drivers.taskflow.test_nova_down'
```

Рабочие исходники Mistral/Masakari, опубликованные патчи и стенд не изменены.
Сборка, deploy/reconfigure, SSH, реальные power/migration/evacuation не запускались.
