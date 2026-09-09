# 2026-09-07: плановое выключение с live migration завершается ошибкой

Статус: **дефект старого пути ожидания миграции установлен по исходникам;
исправление на стенде ещё не подтверждено**. Это отдельный инцидент от
аварийного Consul → Masakari recovery с notification `failed` около 12:33 UTC.

## Наблюдаемое поведение

Workflow `power_ops.planned_power_off` отправил live migration ВМ, но завершился
`ERROR` до окончания миграции:

```text
instance entered an unsafe migration state
```

Nova позднее успешно завершила миграцию. Исходный физический хост остался
включённым, Nova service — disabled, Masakari host — on_maintenance=true.
Это не успешное плановое выключение: выполнена только часть операции.

## Идентификаторы

| Объект | Значение |
|---|---|
| Workflow execution | `be44830e-598f-4581-bae4-6f8d235f64ce` |
| Task execution | `404e9786-e354-44df-9ad3-ef7e2d90bfc7` |
| Action execution | `8202119e-bd72-46ad-aea4-08451c02be65` |
| ВМ | `85387b2a-32fe-48b2-be94-df20701d2659` (`vm-on-ultra1-2`) |
| Исходный хост | `ultra1-2.ultra1.test.pvs.un.sbt` |
| Целевой хост | `ultra1-3.ultra1.test.pvs.un.sbt` |
| Segment | `b045da78-bc53-435a-937e-f12d41a217b1` |
| Ironic node исходного хоста | `edebd181-6865-4134-8657-0e318efd4336` |

## Хронология (UTC, 7 сентября 2026)

| Время | Событие |
|---|---|
| 11:42:49 | Mistral execution создан, RUNNING |
| 11:43:11 | Nova создала live migration ultra1-2 → ultra1-3 |
| 11:43:40 | Mistral ERROR: `instance entered an unsafe migration state` |
| 11:45:01 | Nova migration `completed` |
| После миграции | Пользователь подтвердил ВМ ACTIVE на ultra1-3, task_state=null; исходный хост power on |

В более поздних снимках есть обратная live migration ultra1-3 → ultra1-2,
завершившаяся в 12:18:49 UTC. Поэтому состояние ВМ на ultra1-2 после 12:33 UTC
не опровергает успешную первую миграцию и относится уже к следующему тесту.

## Причина и граница доказательства

В старом коде
`worktrees/mistral-powerops/mistral/actions/powerops/clients.py`, метод
`_validate_migration_observation`, имеется проверка:

```python
if server.status != 'ACTIVE':
    raise exceptions.InstancePolicyError(
        'instance entered an unsafe migration state'
    )
```

Она отвергает любой статус, отличный от ACTIVE, включая нормальное
промежуточное состояние MIGRATING. Исключение останавливает ожидание в Mistral,
но не отменяет уже принятую Nova операцию. Поэтому workflow может быть ERROR,
а миграция спустя некоторое время — completed.

По снимкам установлены ошибка, порядок событий и успешное конечное размещение.
Точное значение `server.status` в момент исключения не было сохранено в тексте
ошибки: MIGRATING — объяснение, подтверждённое дефектом валидатора и локальным
воспроизведением, а не прочитанное из стендового traceback поле.

## Исправление и текущий статус

Этап 1 ожидания live migration уже включён в пользовательский Mistral `0809`.
Отдельный planned-return-v2 / planned-return-kit выведен из текущей поставки;
его не нужно включать через `planned_return_enabled` для проверки этого дефекта.
Прежнее обсуждение экспериментального пути сохранено только в backup.

Актуальное воспроизведение, результаты локальных проверок и ограничения описаны
в [аудите 9 сентября](AUDIT-2026-09-09-planned-off-live-migration.md).
Пользователь также сообщил об успешном стендовом прогоне планового выключения
с миграцией; это отдельное наблюдение, не новая проверка при объединении Git.

## Что проверить при приёмке

1. Все executor используют требуемый образ Mistral на базе 0809; необходимые
   API-права, coordination и отключённый SDK response cache проверены.
2. Запустить один согласованный сценарий с live migration тестовой ACTIVE ВМ.
3. Mistral остаётся RUNNING во время нормальной незавершённой миграции.
4. Подтверждены новая completed migration UUID, правильный destination,
   ACTIVE и task_state=null; перед power-off повторно проверена пустота source
   по Nova. Это API-наблюдение, не доказательство отсутствия локальных доменов.
5. Только затем Ironic подтверждает стабильный power off. Итог: SUCCESS,
   Nova disabled, Masakari maintenance=true.
6. Отдельно проверить error/timeout миграции, потерю lock и неоднозначную историю:
   они не должны разрешать выключение исходного хоста.

## Данные для повторного разбора (только чтение)

```bash
openstack workflow execution show be44830e-598f-4581-bae4-6f8d235f64ce
openstack workflow execution output show be44830e-598f-4581-bae4-6f8d235f64ce
openstack server show 85387b2a-32fe-48b2-be94-df20701d2659 -f yaml
openstack server migration list --server 85387b2a-32fe-48b2-be94-df20701d2659
openstack baremetal node show edebd181-6865-4134-8657-0e318efd4336 \
  -f yaml -c power_state -c target_power_state -c last_error
```

В `mistral-executor.log` искать точный action execution ID на всех контроллерах.
Не повторять выключение вслепую: ERROR не отменяет уже отправленную миграцию.
Не делать принудительный reset-state, не снимать maintenance и не включать
scheduling до проверки фактического состояния ВМ и отсутствия stale domains.
