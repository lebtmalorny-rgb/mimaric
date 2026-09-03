# Плановое выключение compute-хоста через PowerOps

## Краткий вывод

Выключение запускается workflow `power_ops.planned_power_off`. Для пустого
хоста используйте `require_empty`, для хоста с ВМ — `live_migrate` или `stop`.
Во всех примерах ниже `allow_hard_off=false`: если мягкое выключение не
завершится вовремя, workflow остановится с ошибкой и не выполнит жёсткое
выключение.

Запускайте команды только в согласованное окно работ и из shell с загруженными
OpenStack credentials.

PowerOps использует etcd для общих блокировок Masakari и Mistral. Consul можно
сохранить для обнаружения отказов через `masakari-hostmonitor`, но он не нужен
самому плановому workflow и не заменяет etcd.

## 1. Получить UUID сегмента и имя хоста

Проверьте доступ к облаку и выведите сегменты Masakari:

```bash
openstack token issue
openstack segment list
```

Выберите нужный сегмент вручную и сохраните его UUID. Здесь и далее значения
примерные:

```bash
export SEGMENT_UUID='7f3c2e10-6a4b-4d83-9a21-123456789abc'
openstack segment host list "$SEGMENT_UUID"
```

Выберите точное имя compute-хоста из этого сегмента и сверьте его с Nova:

```bash
export HOST='compute-01'
openstack segment host show "$SEGMENT_UUID" "$HOST"
openstack compute service list --host "$HOST" --service nova-compute --long
```

Не подставляйте автоматически первую строку списка: перед выключением нужно
осознанно выбрать точный сегмент и хост. Имя `HOST` должно полностью совпадать
в Masakari, Nova и Ironic.

## 2. Проверить состояние до выключения

Посмотрите ВМ на хосте и найдите соответствующий Ironic Node:

```bash
openstack server list --all-projects --host "$HOST" --long
openstack baremetal node list --fields uuid name provision_state power_state target_power_state last_error network_interface
```

Сохраните UUID найденного Node и проверьте его подробно:

```bash
export NODE_UUID='11111111-2222-3333-4444-555555555555'
openstack baremetal node show "$NODE_UUID" --fields uuid name provision_state power_state target_power_state last_error network_interface
openstack workflow execution list --rootsonly --limit 20
```

Не запускайте выключение, если:

- имя хоста не совпадает между Masakari, Nova и Ironic;
- Ironic Node не находится в `manageable` или использует не `noop` network
  interface;
- задан `last_error` либо конфликтуют `power_state` и `target_power_state`;
- список ВМ неизвестен или неожиданен;
- для этого хоста уже выполняется PowerOps execution.

## 3. Выбрать политику ВМ и выключить хост

### Пустой хост

`require_empty` завершит операцию ошибкой, если на хосте обнаружится хотя бы
одна ВМ:

```bash
export EXECUTION_ID="$(openstack workflow execution create -f value -c ID power_ops.planned_power_off '{"host":"compute-01","segment_uuid":"7f3c2e10-6a4b-4d83-9a21-123456789abc","instance_policy":"require_empty","allow_hard_off":false}')"
```

### Хост с ВМ: live migration

`live_migrate` последовательно мигрирует все `ACTIVE` ВМ на другие
compute-хосты. До запуска проверьте доступную capacity, совместимость CPU и
доступность storage/network на целевых хостах:

```bash
export EXECUTION_ID="$(openstack workflow execution create -f value -c ID power_ops.planned_power_off '{"host":"compute-01","segment_uuid":"7f3c2e10-6a4b-4d83-9a21-123456789abc","instance_policy":"live_migrate","allow_hard_off":false}')"
```

### Хост с ВМ: остановка ВМ

`stop` последовательно остановит ВМ, оставит их на исходном хосте и вернёт
UUID фактически остановленных ВМ в `stopped_instance_ids`. Сохраните этот
список для отдельной процедуры возврата хоста:

```bash
export EXECUTION_ID="$(openstack workflow execution create -f value -c ID power_ops.planned_power_off '{"host":"compute-01","segment_uuid":"7f3c2e10-6a4b-4d83-9a21-123456789abc","instance_policy":"stop","allow_hard_off":false}')"
```

Если ВМ много, команда не меняется. Workflow сам получает полный список ВМ,
сортирует его по UUID и обрабатывает ВМ по одной, подтверждая результат и
выдерживая настроенный интервал между операциями. UUID ВМ вручную в команду
выключения не передаются.

Проверьте, что идентификатор execution получен:

```bash
test -n "$EXECUTION_ID"
printf 'EXECUTION_ID=%s\n' "$EXECUTION_ID"
```

Если команда потеряла соединение или завершилась по timeout до вывода ID, не
запускайте её повторно. Сначала найдите уже созданный execution:

```bash
openstack workflow execution list --rootsonly --limit 50
```

## 4. Наблюдать выполнение

```bash
openstack workflow execution show "$EXECUTION_ID"
openstack workflow execution input show "$EXECUTION_ID"
openstack task execution list "$EXECUTION_ID"
openstack workflow execution report show --errors-only "$EXECUTION_ID"
```

Дождитесь терминального состояния `SUCCESS`, `ERROR` или `CANCELLED`.
Длительный `RUNNING` не является основанием запускать второй execution.

## 5. Проверить фактический результат

```bash
openstack workflow execution output show "$EXECUTION_ID"
openstack compute service list --host "$HOST" --service nova-compute --long
openstack server list --all-projects --host "$HOST" --long
openstack segment host show "$SEGMENT_UUID" "$HOST"
openstack baremetal node show "$NODE_UUID" --fields uuid name provision_state power_state target_power_state last_error network_interface
```

Успешное плановое выключение подтверждено только когда одновременно:

- execution имеет состояние `SUCCESS`;
- output содержит `operation=planned_power_off` и `power_state=power off`;
- Nova service имеет `Status=disabled`;
- Masakari host находится в maintenance;
- Ironic подтверждает устойчивое `power off`, пустой `target_power_state` и
  пустой `last_error`;
- при `live_migrate` на исходном хосте не осталось ВМ;
- при `stop` output содержит сохранённый `stopped_instance_ids`.

## Если возникла ошибка

Не повторяйте workflow вслепую. После ошибки безопасное состояние может быть
частичным: Nova уже `disabled`, Masakari уже в maintenance, но физический хост
ещё включён. Сохраните execution input/output/report и повторно прочитайте
фактические состояния Nova, Masakari и Ironic перед любым следующим действием.

Полная процедура диагностики и возврата хоста приведена в
[`OPERATIONS.md`](OPERATIONS.md).
