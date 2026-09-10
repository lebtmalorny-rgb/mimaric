# Ultra: выключение и перезагрузка через PowerOps

Короткая памятка для текущей базы **0809**. Выполнять на **ultra1-0**
в обычном терминале с загруженными OpenStack credentials, без `sudo`,
не внутри контейнера. Команды ниже изменяют состояние реального хоста.
Выбрать **одну операцию для одного хоста**, не запускать все примеры подряд.
Все команды приведены без shell-переменных: имена хостов, UUID сегмента и
параметры указаны непосредственно в строках команд.

## 1. Выбрать хост и проверить исходное состояние

Проверить питание, Nova и ВМ всех проектов на **ultra1-2**:

```bash
timeout 25s openstack baremetal node show ultra1-2.ultra1.test.pvs.un.sbt -f yaml -c power_state -c target_power_state -c last_error
timeout 25s openstack compute service list --host ultra1-2.ultra1.test.pvs.un.sbt --service nova-compute
timeout 25s openstack server list --all-projects --host ultra1-2.ultra1.test.pvs.un.sbt --long
```

Те же проверки для **ultra1-3**:

```bash
timeout 25s openstack baremetal node show ultra1-3.ultra1.test.pvs.un.sbt -f yaml -c power_state -c target_power_state -c last_error
timeout 25s openstack compute service list --host ultra1-3.ultra1.test.pvs.un.sbt --service nova-compute
timeout 25s openstack server list --all-projects --host ultra1-3.ultra1.test.pvs.un.sbt --long
```

Maintenance обоих хостов в общем сегменте:

```bash
timeout 25s openstack segment host list b045da78-bc53-435a-937e-f12d41a217b1
```

Для чистого планового прогона: `power on`, `target_power_state: null`,
`last_error: null`, Nova `enabled/up`, Masakari `on_maintenance=False`.
После аварии или незавершённого workflow сначала разобраться с состоянием;
перезагрузка не заменяет процедуру возврата после fencing.

## 2. Выбрать, что делать с ВМ

В примерах ниже выбран режим **с миграцией**, как в предыдущих прогонах.
Для другого режима заменить **только значение `instance_policy` внутри JSON**:

| Поле в команде | Поведение |
|---|---|
| `"instance_policy":"live_migrate"` | Перенести ACTIVE ВМ на другой compute перед выключением. |
| `"instance_policy":"require_empty"` | Только пустой хост. Любая ВМ, включая SHUTOFF, блокирует выключение. |
| `"instance_policy":"stop"` | Остановить ACTIVE ВМ на месте. Уже SHUTOFF не входят в список остановленных этой операцией. |

`live_migrate` допускает только ACTIVE ВМ: они мигрируют последовательно.
Нужен другой доступный compute с подходящими ресурсами. Например, для
ultra1-2 это ultra1-3, если он `enabled/up` и пригоден для размещения ВМ.
API-список ВМ не доказывает отсутствие stale domains на гипервизоре.

## 3. Плановое выключение

**ultra1-2, с миграцией ВМ:**

```bash
openstack workflow execution create power_ops.planned_power_off '{"host":"ultra1-2.ultra1.test.pvs.un.sbt","segment_uuid":"b045da78-bc53-435a-937e-f12d41a217b1","instance_policy":"live_migrate","allow_hard_off":false}'
```

**ultra1-3, с миграцией ВМ:**

```bash
openstack workflow execution create power_ops.planned_power_off '{"host":"ultra1-3.ultra1.test.pvs.un.sbt","segment_uuid":"b045da78-bc53-435a-937e-f12d41a217b1","instance_policy":"live_migrate","allow_hard_off":false}'
```

`host` — выключаемый исходный хост, **не назначение миграции**;
`segment_uuid` — UUID его сегмента Masakari. Хост назначения выбирает Nova.

При успехе: хост **power off**, Nova **disabled**, Masakari **maintenance=true**.
Nova может ещё некоторое время показывать `up`: workflow не ждёт её `down`.
При `live_migrate` ВМ остаются на другом хосте; при `stop` сохранить
`stopped_instance_ids` из результата для последующего запуска ВМ.

## 4. Плановая перезагрузка — вместо выключения

**ultra1-2, с миграцией ВМ:**

```bash
openstack workflow execution create power_ops.planned_reboot '{"host":"ultra1-2.ultra1.test.pvs.un.sbt","segment_uuid":"b045da78-bc53-435a-937e-f12d41a217b1","instance_policy":"live_migrate","allow_hard_off":false}'
```

**ultra1-3, с миграцией ВМ:**

```bash
openstack workflow execution create power_ops.planned_reboot '{"host":"ultra1-3.ultra1.test.pvs.un.sbt","segment_uuid":"b045da78-bc53-435a-937e-f12d41a217b1","instance_policy":"live_migrate","allow_hard_off":false}'
```

Workflow выполняет **off → on**, ждёт Nova `disabled/up`, затем возвращает
хост в сервис: **power on**, Nova **enabled/up**, Masakari **maintenance=false**.
Ручной паузы здесь нет. При `live_migrate` ВМ **не возвращаются** обратно;
при `stop` запускаются только ВМ, остановленные этим workflow.
Во всех примерах `allow_hard_off=false`: жёсткий fallback не разрешён.

## 5. Проверить результат выбранной операции

После `create` скопировать UUID из поля **`ID`**, не из `Workflow ID`.
В трёх командах ниже заменить текст **`EXECUTION_UUID`** этим UUID;
это место подстановки, а не переменная. Следующие команды можно повторять:

```bash
timeout 25s openstack workflow execution show EXECUTION_UUID
timeout 25s openstack workflow execution output show EXECUTION_UUID
timeout 25s openstack task execution list EXECUTION_UUID
```

Дождаться `SUCCESS`, затем повторить API-проверки из раздела 1. Пустой output
при `RUNNING` ещё не означает ошибку. При `ERROR` не запускать новую операцию,
пока не разобраны `State info`, task и фактическое состояние хоста/ВМ.

Если `create` вернул timeout/504 или не выдал ID, **не повторять его вслепую**:
workflow мог уже запуститься. Найти execution и проверить его входные параметры:

```bash
timeout 25s openstack workflow execution list
```

Для включения после отдельного выключения используется другой workflow —
`power_ops.power_on_and_return` с ручной проверкой на `PAUSED`.
Порядок продолжения: [возврат хоста](POWEROPS-OVERVIEW.md#6-включение-и-ручной-возврат).
Разбор ошибок: [команды диагностики](POWEROPS-TROUBLESHOOTING-COMMANDS.md).

Команды и поведение сверены с `etc/mistral/power_ops.yaml` и
`mistral/actions/powerops/planned.py` из архива Mistral `0809`.
Это проверка по исходникам; новый прогон на стенде при подготовке памятки не выполнялся.
