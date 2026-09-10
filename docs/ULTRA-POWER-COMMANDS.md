# Ultra: выключение и перезагрузка через PowerOps

Короткая памятка для текущей базы **0809**. Выполнять на **ultra1-0**
в обычном терминале с загруженными OpenStack credentials, без `sudo`,
не внутри контейнера. Команды ниже изменяют состояние реального хоста.
Выбрать **одну операцию для одного хоста**, не запускать все примеры подряд.

## 1. Выбрать хост и проверить исходное состояние

Пример для **ultra1-2**:

```bash
POWEROPS_HOST=ultra1-2.ultra1.test.pvs.un.sbt
POWEROPS_SEGMENT=b045da78-bc53-435a-937e-f12d41a217b1
```

Для **ultra1-3** заменить только выбор хоста:

```bash
POWEROPS_HOST=ultra1-3.ultra1.test.pvs.un.sbt
```

Проверить питание, Nova, ВМ всех проектов и maintenance выбранного хоста:

```bash
timeout 25s openstack baremetal node show "$POWEROPS_HOST" -f yaml -c power_state -c target_power_state -c last_error
timeout 25s openstack compute service list --host "$POWEROPS_HOST" --service nova-compute
timeout 25s openstack server list --all-projects --host "$POWEROPS_HOST" --long
timeout 25s openstack segment host list "$POWEROPS_SEGMENT"
```

Для чистого планового прогона: `power on`, `target_power_state: null`,
`last_error: null`, Nova `enabled/up`, Masakari `on_maintenance=False`.
После аварии или незавершённого workflow сначала разобраться с состоянием;
перезагрузка не заменяет процедуру возврата после fencing.

## 2. Выбрать, что делать с ВМ

Для выключения или перезагрузки **с миграцией**, как в предыдущих прогонах:

```bash
POWEROPS_POLICY=live_migrate
```

| Вместо этого можно выбрать | Поведение |
|---|---|
| `POWEROPS_POLICY=require_empty` | Только пустой хост. Любая ВМ, включая SHUTOFF, блокирует выключение. |
| `POWEROPS_POLICY=stop` | Остановить ACTIVE ВМ на месте. Уже SHUTOFF не входят в список остановленных этой операцией. |

`live_migrate` допускает только ACTIVE ВМ: они мигрируют последовательно.
Нужен другой доступный compute с подходящими ресурсами. Например, для
ultra1-2 это ultra1-3, если он `enabled/up` и пригоден для размещения ВМ.
API-список ВМ не доказывает отсутствие stale domains на гипервизоре.

## 3. Плановое выключение

```bash
POWEROPS_EXEC=$(openstack workflow execution create -f value -c ID power_ops.planned_power_off "{\"host\":\"$POWEROPS_HOST\",\"segment_uuid\":\"$POWEROPS_SEGMENT\",\"instance_policy\":\"$POWEROPS_POLICY\",\"allow_hard_off\":false}")
printf 'Execution: %s\n' "$POWEROPS_EXEC"
```

При успехе: хост **power off**, Nova **disabled**, Masakari **maintenance=true**.
Nova может ещё некоторое время показывать `up`: workflow не ждёт её `down`.
При `live_migrate` ВМ остаются на другом хосте; при `stop` сохранить
`stopped_instance_ids` из результата для последующего запуска ВМ.

## 4. Плановая перезагрузка — вместо выключения

```bash
POWEROPS_EXEC=$(openstack workflow execution create -f value -c ID power_ops.planned_reboot "{\"host\":\"$POWEROPS_HOST\",\"segment_uuid\":\"$POWEROPS_SEGMENT\",\"instance_policy\":\"$POWEROPS_POLICY\",\"allow_hard_off\":false}")
printf 'Execution: %s\n' "$POWEROPS_EXEC"
```

Workflow выполняет **off → on**, ждёт Nova `disabled/up`, затем возвращает
хост в сервис: **power on**, Nova **enabled/up**, Masakari **maintenance=false**.
Ручной паузы здесь нет. При `live_migrate` ВМ **не возвращаются** обратно;
при `stop` запускаются только ВМ, остановленные этим workflow.
В обоих примерах `allow_hard_off=false`: жёсткий fallback не разрешён.

## 5. Проверить результат выбранной операции

Сохранить напечатанный Execution ID. Следующие команды можно повторять:

```bash
timeout 25s openstack workflow execution show "$POWEROPS_EXEC"
timeout 25s openstack workflow execution output show "$POWEROPS_EXEC"
timeout 25s openstack task execution list "$POWEROPS_EXEC"
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
