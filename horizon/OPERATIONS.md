# PowerOps: контроль и диагностика

## Краткий вывод

Эта инструкция предназначена для оператора OpenStack и администратора HA. Она
помогает без изменения инфраструктуры определить, где находится плановая
операция Mistral или аварийное восстановление Masakari, проверить фактическое
состояние Nova, Masakari, Ironic и etcd и собрать доказательства корректной
последовательности.

Авторитетен не один статус и не одна строка лога, а согласованный снимок:

```text
Mistral execution или Masakari notification
        + Nova service и размещение каждой ВМ
        + Masakari host/VMove
        + Ironic power_state/target_power_state/last_error
        + здоровье etcd и коррелированные логи
```

Для аварии обязательный порядок: Nova disable → Ironic fencing → несколько
совпадающих наблюдений stable-off → подготовка ВМ → последовательная
evacuation. Если fencing или stable-off не доказан, evacuation не должна
начаться. Для планового пути evacuation не используется.

Установка описана в [`INSTALL.md`](INSTALL.md), архитектура — в
`docs/powerops/POWEROPS-ARCHITECTURE.md` после применения Kolla-серии. Эта
инструкция не заменяет регламент конкретного облака, change ticket и
согласованное окно работ.

## Правила безопасности

Все команды до раздела «Контролируемая runtime-приёмка» являются read-only.
Они не должны менять питание, состояние ВМ, Nova service, Masakari host,
notification или Mistral execution.

- Работайте по UUID и каноническому Nova hostname. До диагностики докажите
  равенство `Nova hostname = Masakari host.name = Ironic Node.name`.
- Не считайте недоступность SSH/ОС доказательством выключения физического
  хоста. Требуются совместимые наблюдения Ironic/BMC.
- Не включайте fenced-хост, Nova service и не снимайте Masakari maintenance,
  пока не проверены libvirt domains, storage/network и отсутствие stale
  domains.
- Не повторяйте workflow, notification, power action или evacuation вслепую
  после timeout, `ERROR`, `FAILED` либо потери coordinator. Сначала перечитайте
  фактические состояния всех компонентов.
- Не выводите в терминал и пакет доказательств пароли BMC, Keystone token,
  содержимое `passwords.yml`, приватные ключи и client-key etcd.
- `PowerOps audit` — только structured process `LOG.info`. В комплекте нет
  внешнего долговечного audit store и гарантии доставки логов.
- `etcdctl endpoint health` подтверждает возможность commit к etcd, но не
  доказывает, кто владеет конкретной tooz-блокировкой. Владение проверяется по
  результату operation и коррелированным логам процесса; сырое чтение ключей
  etcd не является стабильным API PowerOps.

Перед началом зафиксируйте UTC-время, change/incident ID и источник OpenStack
credentials. Используйте отдельную shell-сессию и заполните переменные:

```bash
export HOST=compute-example
export SEGMENT_UUID=00000000-0000-0000-0000-000000000000
export NODE_UUID=11111111-1111-1111-1111-111111111111
export SINCE=2026-09-01T00:00:00Z
export ETCD_ENDPOINTS=https://etcd-1.example:2379,https://etcd-2.example:2379,https://etcd-3.example:2379
test -n "$HOST" && test -n "$SEGMENT_UUID" && test -n "$NODE_UUID"
date -u +%Y-%m-%dT%H:%M:%SZ
```

UUID выше фиктивные. Для etcd применяйте те же CA/client credentials и
endpoint, что разрешены эксплуатационным регламентом; не копируйте секреты в
командную строку или документацию.

## Базовый read-only снимок

Снимок снимайте до операции, при каждом подозрительном переходе и после её
окончания. Сохраняйте полный вывод вместе с UTC-временем.

```bash
openstack catalog list
openstack compute service list --host "$HOST" --service nova-compute --long
openstack server list --all-projects --host "$HOST" --long
openstack baremetal node show "$NODE_UUID" --fields uuid name provision_state power_state target_power_state last_error network_interface
openstack segment host show "$SEGMENT_UUID" "$HOST"
openstack workflow execution list --rootsonly --limit 20
openstack notification list --limit 20
```

Проверьте:

- Ironic Node имеет точное имя хоста, `provision_state=manageable`,
  `network_interface=noop`, пустой `last_error`; `power_state` и
  `target_power_state` не конфликтуют;
- в Nova существует ровно один `nova-compute` для хоста, отдельно видны
  административный `Status` (`enabled`/`disabled`) и процессный `State`
  (`up`/`down`);
- Masakari host относится к ожидаемому segment, а `on_maintenance` соответствует
  текущей фазе;
- список Nova ВМ на исходном хосте согласуется с manifest плановой операции или
  VMove аварийной notification;
- нет другого незавершённого PowerOps execution/notification для того же хоста.

Если имя хоста неоднозначно, Node не `manageable`, interface не `noop`, задан
`last_error` или фактический список ВМ неизвестен, итог снимка — `FAIL`; к
изменяющей операции переходить нельзя.

## Как читать Mistral execution

Выберите точный PowerOps execution из списка и задайте его ID:

```bash
export EXECUTION_ID=22222222-2222-2222-2222-222222222222
openstack workflow execution show "$EXECUTION_ID"
openstack workflow execution input show "$EXECUTION_ID"
openstack workflow execution output show "$EXECUTION_ID"
openstack workflow execution report show --errors-only "$EXECUTION_ID"
openstack task execution list "$EXECUTION_ID"
```

Для каждой относящейся к операции task и action:

```bash
export TASK_EXECUTION_ID=33333333-3333-3333-3333-333333333333
export ACTION_EXECUTION_ID=44444444-4444-4444-4444-444444444444
openstack task execution show "$TASK_EXECUTION_ID"
openstack task execution result show "$TASK_EXECUTION_ID"
openstack action execution list "$TASK_EXECUTION_ID"
openstack action execution show "$ACTION_EXECUTION_ID"
openstack action execution input show "$ACTION_EXECUTION_ID"
openstack action execution output show "$ACTION_EXECUTION_ID"
```

Обычные состояния Mistral: `RUNNING`, `PAUSED`, `SUCCESS`, `ERROR`,
`CANCELLED`. Для успешной плановой операции нужен не только `SUCCESS`, но и
совпадение execution input/output с фактическими Nova/Masakari/Ironic
состояниями. При `ERROR` сохраните `state_info`, report, task/action result и
перейдите к матрице неисправностей. `SUCCESS` с ошибкой cleanup coordination в
аудите не разрешает повторять уже завершённый power cycle.

## Плановое выключение

Workflow: `power_ops.planned_power_off`. Допустимые `instance_policy`:
`require_empty`, `live_migrate`, `stop`. Плановая evacuation запрещена.
Готовые команды запуска находятся в разделе
[«Плановое выключение: готовая процедура»](#плановое-выключение-готовая-процедура)
после обязательного runtime/change gate.

Ожидаемая последовательность:

```text
powerops/host/<host>
  → exact Ironic/Nova/Masakari mapping
  → Masakari on_maintenance=true
  → Nova disabled
  → require_empty | sequential live_migrate | sequential stop
  → source safe for power-off
  → soft off, а разрешённый hard off только после timeout
  → stable-off
```

После завершения снимите базовый снимок и раскройте execution. Итог `PASS`,
если одновременно выполнены условия:

- execution `SUCCESS`, output содержит `operation=planned_power_off`,
  `nova_enabled=false`, `masakari_maintenance=true` и фактический manifest
  `stopped_instance_ids`;
- Nova service `disabled`; Masakari host `on_maintenance=True`;
- Ironic показывает устойчивое выключение, пустой `target_power_state` и пустой
  `last_error`;
- при `require_empty` на хосте не было ВМ; при `live_migrate` ни одна ВМ из
  исходного списка не осталась на source; при `stop` только UUID из output
  manifest имеют ожидаемое остановленное состояние;
- порядок UUID и интервалы видны в Mistral action/logs: следующая VM mutation
  начинается только после подтверждения предыдущей и pacing.

Если action завершился после Nova disable с ошибкой, безопасный ожидаемый
результат — Nova disabled и Masakari maintenance=true. Это не `PASS` операции,
а fail-safe состояние для ручной диагностики.

## Плановая перезагрузка

Workflow: `power_ops.planned_reboot`; политики ВМ те же, что у планового
выключения.

```text
maintenance=true → Nova disabled → VM policy
→ stable-off → stable-on → nova-compute up/disabled
→ последовательный старт stopped manifest
→ Nova enabled → maintenance=false
```

Итог `PASS`, если execution `SUCCESS`, output сообщает
`operation=planned_reboot`, `power_state=power on`, `nova_enabled=true`,
`masakari_maintenance=false`, а фактический снимок это подтверждает. Для каждой
ВМ из `stopped_instance_ids` проверьте полный `server show`: ожидаемый статус,
отсутствие незавершённого task state и ожидаемое размещение. Проверка только
`nova-compute up` недостаточна: сервис может оставаться административно
disabled.

При ошибке старта части manifest не включайте Nova вручную. Часть ВМ уже может
быть `ACTIVE`; повторное чтение каждой ВМ обязательно до решения о новой
операции.

## Двухфазный возврат хоста

Workflow: `power_ops.power_on_and_return`. В input передаётся точный
`stopped_instance_ids` из ранее сохранённого output планового выключения.

Фаза 1 должна завершиться реальной паузой перед task
`operator_inspection_gate`. Ожидается:

- физическое питание устойчиво включено;
- `nova-compute` имеет `State=up`, но `Status=disabled`;
- Masakari host остаётся `on_maintenance=True`;
- execution `PAUSED`, а `return_to_service` ещё не выполнен;
- VM manifest не стартовал.

До resume администратор хоста проверяет ОС, время, multipath/storage, bridge/OVS
или OVN, MTU, libvirt и отсутствие stale domains. Минимальный локальный набор
команд зависит от дистрибутива, но результат проверки должен явно содержать
хост, UTC-время и список всех libvirt domains. Сравните его с Nova placement и
manifest; чужой или дублирующий domain означает `FAIL`.

Resume разрешён только с JSON Boolean `stale_domains_checked=true`, не строкой
`"true"`. После resume Mistral повторно получает host lock, проверяет stable-on,
`nova-compute up/disabled` и maintenance=true, последовательно стартует только
manifest, затем включает Nova и последним снимает maintenance.

Фаза 2 имеет `PASS`, когда execution `SUCCESS`, все manifest UUID проверены,
Nova `up/enabled`, Masakari maintenance=false, Ironic stable-on и нет
незавершённых task states. Если execution не стоит на ожидаемом gate, не
пытайтесь принудительно менять его состояние.

## Аварийное отключение, fencing и evacuation

Аварийный путь запускается host-failure notification Masakari, а не Mistral
planned workflow. На весь flow удерживается общий с Mistral lock
`powerops/host/<host>`.

Обязательная последовательность:

```text
host lock
  → disable_compute_service_task
  → ironic_fence: exact manageable/noop Node, hard off
  → несколько stable-off наблюдений
  → prepare_HA_enabled_instances_task
  → VMove UUID-1: evacuation → confirm → pacing
  → VMove UUID-2: evacuation → confirm → pacing
  → ... под powerops/evacuation/global
```

Найдите точную notification и все её VMove:

```bash
export NOTIFICATION_ID=55555555-5555-5555-5555-555555555555
openstack notification show "$NOTIFICATION_ID"
openstack notification vmove list "$NOTIFICATION_ID"
```

Для каждой VMove:

```bash
export VMOVE_ID=66666666-6666-6666-6666-666666666666
openstack notification vmove show "$NOTIFICATION_ID" "$VMOVE_ID"
```

Сверьте `instance_uuid`, `source_host`, `dest_host`, `status`, `start_time`,
`end_time` и `message`. Состояния VMove: `pending`, `ongoing`, `succeeded`,
`failed`, `ignored`; состояние notification проходит через `new`/`running` и
обычно заканчивается `finished`, `error`, `failed` либо `ignored`.

Проверяйте каждую ВМ независимо:

```bash
export SERVER_ID=77777777-7777-7777-7777-777777777777
openstack server show "$SERVER_ID" -f yaml
openstack server event list "$SERVER_ID"
openstack server migration list --server "$SERVER_ID"
```

Аварийный сценарий имеет `PASS`, если:

- в логах Nova disable предшествует fencing, stable-off доказан раньше первой
  Nova evacuation;
- Ironic остаётся stable-off, `target_power_state` и `last_error` пусты;
- Nova service исходного хоста disabled, Masakari host в maintenance;
- все ожидаемые VMove имеют `succeeded`, `dest_host` не равен source, а Nova
  подтверждает то же размещение и допустимое состояние;
- интервалы между VMove согласуются с последовательной обработкой: нет двух
  одновременных evacuation внутри глобальной блокировки;
- notification закончилась `finished`; аварийно fenced-хост автоматически не
  включался.

Если fencing или stable-off не подтверждён, наличие любой начавшейся VMove —
критический `FAIL`. При `failed` текущая попытка прекращает обработку следующих
UUID; priority recovery method может начать альтернативный flow только при
здоровом coordinator. Поэтому после первой ошибки нельзя считать последующие
ВМ ни эвакуированными, ни нетронутыми — прочитайте все VMove и Nova server.

## Диагностика по компонентам

### Mistral

Проверьте наличие ровно одного проектного workflow каждого имени и пяти action
definitions:

```bash
openstack action definition list
openstack workflow list
openstack workflow show power_ops.host_power_status
openstack workflow show power_ops.planned_power_off
openstack workflow show power_ops.planned_reboot
openstack workflow show power_ops.power_on_and_return
```

Для зависшего execution смотрите сверху вниз: execution `state/state_info` →
task → action input/output. `RUNNING` дольше настроенного timeout требует
сверки с фактическим Ironic/Nova состоянием и логами executor; это не повод
менять state. `ERROR` авторитетнее красивой последней INFO-строки, но также не
отменяет уже совершённую внешнюю mutation.

### Masakari

```bash
openstack segment show "$SEGMENT_UUID"
openstack segment host list "$SEGMENT_UUID"
openstack segment host show "$SEGMENT_UUID" "$HOST"
openstack notification list --limit 50
```

Для planned off/первой фазы возврата ожидается maintenance=true; для полностью
успешного reboot/возврата — false. В аварийном flow оценивайте notification
вместе с VMove: `finished` без сверки полного списка ВМ ещё не доказывает
корректное размещение, а `error` требует чтения recovery details и каждой
VMove.

### Nova

```bash
openstack compute service list --host "$HOST" --service nova-compute --long
openstack hypervisor list --matching "$HOST" --long
openstack server list --all-projects --host "$HOST" --long
```

Различайте administrative `Status` и heartbeat `State`. Для каждой ВМ из
manifest/VMove используйте UUID и полный `server show`; имена ВМ могут
повторяться между проектами. После evacuation исходный placement недопустим.
После planned `live_migrate` source также должен быть пуст для исходного
manifest, но это миграция, не Masakari VMove.

### Ironic и BMC

```bash
openstack baremetal node list --fields uuid name provision_state power_state maintenance
openstack baremetal node show "$NODE_UUID" --fields uuid name provision_state power_state target_power_state last_error network_interface maintenance maintenance_reason
```

`power_state` — фактическое наблюдение Ironic, `target_power_state` — ещё
выполняемый или застрявший переход, `last_error` — причина последней ошибки.
Stable-off/stable-on означает несколько последовательных одинаковых
наблюдений с интервалом `powerops_poll_interval` в количестве не меньше
`powerops_stable_observations`. Один ответ не является stable-state.
Независимый read-only BMC status полезен для сверки, но используйте штатный
клиент/CA конкретного BMC и не выполняйте Reset/Power action.

### etcd и блокировки

С узла/контейнера, где установлен `etcdctl` и доступны утверждённые TLS
credentials:

```bash
ETCDCTL_API=3 etcdctl --endpoints="$ETCD_ENDPOINTS" endpoint health
ETCDCTL_API=3 etcdctl --write-out=table --endpoints="$ETCD_ENDPOINTS" endpoint status
```

Все endpoint должны отвечать без ошибок, у кластера должен быть один leader, а
Raft applied index не должен надолго расходиться. Проверку выполняйте из
сетевого контекста `masakari_engine`, `mistral_engine` и `mistral_executor`:
здоровье с bastion не доказывает доступность из контейнера.

Host lock `powerops/host/<host>` взаимно исключает planned и emergency flow
одного хоста. `powerops/evacuation/global` сериализует одну VMove во всём
облаке. Потеря heartbeat/ownership должна останавливать новые mutations в
режиме fail-closed. Не удаляйте lock/key вручную: lease может принадлежать
живому процессу, а формат tooz backend не является операторским контрактом.

### Контейнеры и логи Kolla

На соответствующих controller/compute узлах:

```bash
docker ps --format '{{.Names}}\t{{.Status}}' | grep -E 'masakari_engine|mistral_(api|engine|executor)|ironic_conductor|nova_compute|etcd'
docker inspect --format '{{.Name}} {{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{else}}no-healthcheck{{end}}' masakari_engine
docker inspect --format '{{.Name}} {{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{else}}no-healthcheck{{end}}' mistral_engine
docker inspect --format '{{.Name}} {{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{else}}no-healthcheck{{end}}' mistral_executor
docker inspect --format '{{.Name}} {{.State.Status}} {{if .State.Health}}{{.State.Health.Status}}{{else}}no-healthcheck{{end}}' ironic_conductor
docker logs --since "$SINCE" mistral_executor 2>&1 | grep -E 'PowerOps audit|coordination|ERROR|Traceback'
docker logs --since "$SINCE" masakari_engine 2>&1 | grep -E 'ironic_fence|evacuat|coordination|ERROR|Traceback'
```

`no-healthcheck` означает, что Docker healthcheck у контейнера не определён;
это само по себе не ошибка. `docker logs` показывает только container stdout;
если сервис пишет в файл, пустой вывод не доказывает отсутствие события.
Найдите фактические service log-файлы и ищите по точному ID:

```bash
sudo find /var/log/kolla/masakari /var/log/kolla/mistral /var/log/kolla/ironic /var/log/kolla/nova -maxdepth 1 -type f -print
sudo grep -R -E "$EXECUTION_ID|$NOTIFICATION_ID|$NODE_UUID|$SERVER_ID|PowerOps audit|ironic_fence|coordination|Traceback" /var/log/kolla/masakari /var/log/kolla/mistral /var/log/kolla/ironic /var/log/kolla/nova
```

Ключевые источники: `mistral_engine` — переходы workflow/task,
`mistral_executor` — PowerOps actions и audit; `masakari_engine` — notification,
fencing и очередь VMove; `ironic_conductor` — BMC power transition;
`nova_compute` и Nova controller services — heartbeat, migration/evacuation и
spawn. Коррелируйте по UTC и UUID. Лог показывает порядок вызовов, но итоговое
состояние всегда перечитывается через API.

## Матрица неисправностей

| Наблюдение | Вероятная граница отказа | Безопасное действие |
|---|---|---|
| Mistral `ERROR` до Nova disable | authorization, mapping, allowlist или lock | Сохранить action error; проверить exact names, project/user allowlists и etcd. Power/BMC не трогать. |
| Nova disabled, execution `ERROR` | отказ после начала fail-safe границы | Оставить disabled и maintenance=true; перечитать ВМ, Ironic и action output. Не повторять execution вслепую. |
| `target_power_state` долго не пуст | Ironic conductor/BMC transition | Проверить conductor log, Redfish TLS/CA и read-only BMC state; не запускать встречную power operation. |
| Ironic `last_error` не пуст | BMC/driver/inventory | Устранить причину и снова собрать снимок; не считать питание доказанным. |
| Masakari notification `running` без VMove | lock, Nova disable, fencing или stable-off | По recovery details/logs определить последний успешный шаг. Отсутствие VMove может быть правильным fail-closed результатом. |
| VMove `ongoing` дольше timeout | Nova evacuation/confirm или coordinator | Проверить Nova server/event/migration и destination; не создавать вторую evacuation. |
| Одна VMove `failed`, следующие `pending` | ожидаемая остановка текущей очереди | Проверить все VMove и возможный priority fallback. Не переводить pending вручную. |
| Две evacuation одновременно | нарушение global serialization либо неверная корреляция | Объявить `FAIL`, прекратить новые canary, сохранить логи всех engine и проверить единый etcd backend. |
| etcd endpoint unhealthy | quorum/network/TLS | Новые PowerOps mutations запретить; восстановить coordinator, затем перечитать внешнее состояние. |
| Host включён, Nova up/disabled, maintenance=true | нормальная фаза inspection | Проверить stale domains и инфраструктуру; resume только по утверждённому gate. |
| Nova enabled до конца VM manifest или maintenance снят раньше | нарушение порядка возврата | `FAIL`; остановить новые операции и расследовать точные task/action и фактические ВМ. |
| Audit содержит `completed_with_coordination_cleanup_error` | внешняя операция завершилась, cleanup coordinator ошибся | Не повторять power cycle; проверить факт, logging pipeline и состояние etcd. |

Если API разных компонентов противоречат друг другу, результат всегда `FAIL`
или `INCONCLUSIVE`, но не `PASS`. Сначала остановите новые операции на этом
хосте организационным gate; ручное изменение состояния требует отдельного
решения и плана восстановления.

## Контролируемая runtime-приёмка

Команды этого раздела создают execution и могут выключать хост, мигрировать,
останавливать или запускать ВМ. Они допустимы только после явного разрешения,
на выделенном canary-host, с BMC-консолью, capacity check, backup/rollback plan
и согласованным окном. Простое применение патчей такого разрешения не даёт.

### Плановое выключение: готовая процедура

Эта процедура выполняет реальное выключение compute host. Запускайте её только
в утверждённое окно. Identity в mutation-сессии должна одновременно попадать
в `powerops_allowed_project_names` и `powerops_allowed_user_names`; отдельная
read-only сессия наблюдения может использовать административную учётную запись
по регламенту облака. Держите доступ к BMC-консоли. Команды ниже ничего не
возвращают автоматически при ошибке: безопасный fail-safe может оставить Nova
disabled и Masakari host в maintenance.

1. Загрузите обычный OpenStack RC либо выберите запись `clouds.yaml`. Не
   указывайте пароль или token непосредственно в командах. Подготовьте
   инструменты и точные идентификаторы:

   ```bash
   command -v openstack
   command -v jq
   openstack help workflow execution create

   export HOST=compute-example
   export SEGMENT_UUID=00000000-0000-0000-0000-000000000000
   export NODE_UUID=11111111-1111-1111-1111-111111111111
   export INSTANCE_POLICY=require_empty
   export ALLOW_HARD_OFF=false

   test -n "$HOST"
   test -n "$SEGMENT_UUID"
   test -n "$NODE_UUID"
   ```

   Замените фиктивные значения реальными. Для первого запуска оставьте
   `INSTANCE_POLICY=require_empty` и `ALLOW_HARD_OFF=false`. Для последующих
   операций выберите ровно одну политику:

   | Значение | Что произойдёт до выключения хоста |
   |---|---|
   | `require_empty` | Workflow требует, чтобы на source не было ВМ. Это рекомендуемый первый canary. |
   | `live_migrate` | ВМ по очереди live-migrate с подтверждением и pacing; capacity/storage должны быть проверены заранее. |
   | `stop` | ВМ по очереди останавливаются; их UUID возвращаются в `stopped_instance_ids` для последующего возврата. |

2. Валидируйте значения и снимите состояние до mutation:

   ```bash
   case "$INSTANCE_POLICY" in
     require_empty|live_migrate|stop) ;;
     *) echo "Unsupported INSTANCE_POLICY" >&2; exit 1 ;;
   esac

   case "$ALLOW_HARD_OFF" in
     true|false) ;;
     *) echo "ALLOW_HARD_OFF must be true or false" >&2; exit 1 ;;
   esac

   date -u +%Y-%m-%dT%H:%M:%SZ
   openstack workflow show power_ops.planned_power_off
   openstack compute service list --host "$HOST" --service nova-compute --long
   openstack server list --all-projects --host "$HOST" --long
   openstack baremetal node show "$NODE_UUID" --fields uuid name provision_state power_state target_power_state last_error network_interface
   openstack segment host show "$SEGMENT_UUID" "$HOST"
   openstack workflow execution list --rootsonly --limit 50
   ```

   Остановитесь, если три имени не совпадают, Node не `manageable/noop`,
   `last_error` не пуст, существует другой незавершённый PowerOps execution или
   список ВМ неожиданен. Для `require_empty` отдельно докажите нулевое число
   ВМ:

   ```bash
   SOURCE_VM_COUNT="$(openstack server list --all-projects --host "$HOST" -f value -c ID | awk 'NF {count++} END {print count+0}')"
   echo "SOURCE_VM_COUNT=$SOURCE_VM_COUNT"
   if [ "$INSTANCE_POLICY" = require_empty ]; then
     test "$SOURCE_VM_COUNT" -eq 0
   fi
   ```

   `ALLOW_HARD_OFF=false` разрешает только graceful shutdown и завершает
   workflow ошибкой при истечении его timeout. `allow_hard_off=true` разрешает
   последующий hard off и должен включаться только отдельным решением после
   оценки приложений и риска потери данных. При таком решении подтвердите
   опасную настройку отдельно:

   ```bash
   if [ "$ALLOW_HARD_OFF" = true ]; then
     printf 'Type allow-hard-off:%s to approve hard off: ' "$HOST"
     read -r CONFIRM_HARD_OFF
     test "$CONFIRM_HARD_OFF" = "allow-hard-off:$HOST"
   fi
   ```

3. Безопасно сформируйте JSON. `--argjson` сохраняет `allow_hard_off` логическим
   JSON Boolean, а не строкой:

   ```bash
   WORKFLOW_INPUT="$(
     jq -nc \
       --arg host "$HOST" \
       --arg segment_uuid "$SEGMENT_UUID" \
       --arg instance_policy "$INSTANCE_POLICY" \
       --argjson allow_hard_off "$ALLOW_HARD_OFF" \
       '{host: $host, segment_uuid: $segment_uuid,
         instance_policy: $instance_policy,
         allow_hard_off: $allow_hard_off}'
   )"
   printf '%s\n' "$WORKFLOW_INPUT" | jq .
   ```

   Проверьте напечатанный JSON и введите точное имя хоста как последний
   локальный gate:

   ```bash
   printf 'Type the exact host name to approve planned power off: '
   read -r CONFIRM_HOST
   test "$CONFIRM_HOST" = "$HOST"
   ```

4. Запустите ровно один execution. Команда возвращает его ID и сохраняет его в
   текущей shell-сессии:

   ```bash
   export STARTED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
   EXECUTION_ID="$(openstack workflow execution create -f value -c ID power_ops.planned_power_off "$WORKFLOW_INPUT")"
   test -n "$EXECUTION_ID"
   export EXECUTION_ID
   printf 'EXECUTION_ID=%s\n' "$EXECUTION_ID"
   ```

   Если команда create вернула timeout или потеряла соединение до печати ID,
   не запускайте её повторно. Сначала найдите execution чтением списка и
   сопоставьте workflow, input, время и hostname:

   ```bash
   openstack workflow execution list --rootsonly --limit 50
   ```

5. Наблюдайте execution только read-only командами. Повторяйте снимок вручную
   до терминального `SUCCESS`, `ERROR` либо `CANCELLED`:

   ```bash
   date -u +%Y-%m-%dT%H:%M:%SZ
   openstack workflow execution show "$EXECUTION_ID"
   openstack workflow execution input show "$EXECUTION_ID"
   openstack task execution list "$EXECUTION_ID"
   openstack compute service list --host "$HOST" --service nova-compute --long
   openstack server list --all-projects --host "$HOST" --long
   openstack baremetal node show "$NODE_UUID" --fields uuid name provision_state power_state target_power_state last_error network_interface
   openstack segment host show "$SEGMENT_UUID" "$HOST"
   ```

   В отдельной сессии можно следить за action/audit, не принимая лог за
   итоговый источник состояния:

   ```bash
   docker logs --since "$STARTED_AT" -f mistral_executor 2>&1 | grep -E "$EXECUTION_ID|PowerOps audit|ERROR|Traceback"
   ```

6. После терминального состояния сохраните результат и полный путь ошибок:

   ```bash
   openstack workflow execution show "$EXECUTION_ID"
   openstack workflow execution output show "$EXECUTION_ID"
   openstack workflow execution report show --errors-only "$EXECUTION_ID"
   openstack task execution list "$EXECUTION_ID"
   ```

   `SUCCESS` принимается только вместе с фактическими состояниями: Ironic
   stable-off, пустые `target_power_state`/`last_error`, Nova disabled,
   Masakari maintenance=true и корректный результат выбранной VM policy. Для
   `stop` обязательно сохраните точный `stopped_instance_ids`: этот manifest
   нужен workflow `power_ops.power_on_and_return`. Для `live_migrate` убедитесь,
   что все исходные UUID покинули source; для `require_empty` manifest должен
   оставаться пустым.

   При `ERROR` выполните диагностику из раздела «Матрица неисправностей» и не
   включайте Nova, не снимайте maintenance и не повторяйте execution вслепую.
   Последующий возврат выполняется отдельным workflow и отдельным operator gate,
   описанным в разделе «Двухфазный возврат хоста».

Рекомендуемый порядок приёмки:

1. Проверить только status workflow и совпадение трёх имён:

   ```bash
   openstack workflow execution create power_ops.host_power_status "{\"host\":\"$HOST\",\"segment_uuid\":\"$SEGMENT_UUID\"}"
   ```

2. На пустом canary-host выполнить planned off с `require_empty`, наблюдая
   базовый снимок в отдельной сессии:

   ```bash
   openstack workflow execution create power_ops.planned_power_off "{\"host\":\"$HOST\",\"segment_uuid\":\"$SEGMENT_UUID\",\"instance_policy\":\"require_empty\",\"allow_hard_off\":false}"
   ```

3. Выполнить двухфазный return. Передайте только сохранённый manifest; для
   первого пустого canary он равен `[]`:

   ```bash
   openstack workflow execution create power_ops.power_on_and_return "{\"host\":\"$HOST\",\"segment_uuid\":\"$SEGMENT_UUID\",\"stopped_instance_ids\":[]}"
   ```

4. Дождаться `PAUSED`, выполнить host inspection и только затем возобновить
   точный execution:

   ```bash
   openstack workflow execution update --state RUNNING --env '{"stale_domains_checked": true}' "$EXECUTION_ID"
   ```

5. После успешного пустого canary отдельно испытать `stop`, `live_migrate` и
   planned reboot на специально созданных тестовых ВМ, измерив configured
   timeout и pacing. Не совмещайте сценарии в одной первой проверке.
6. Аварийный canary проводить последним. Используйте утверждённый HA
   monitor/test harness и валидированный Masakari host-failure payload; не
   генерируйте production notification вручную из этой инструкции. Наблюдайте
   fencing и VMove из независимой read-only сессии.

Немедленно прекратите запуск новых canary при потере etcd, неоднозначном host
mapping, неожиданной ВМ, ошибке BMC, недоказанном stable-state, любой
параллельной evacuation или расхождении Nova/Masakari/Ironic. Уже начатые
мутации не откатывайте вслепую.

Критерий общей приёмки `PASS`: каждый сценарий имеет полный до/во время/после
снимок, ожидаемые переходы и fail-safe; последовательность подтверждена по API
и временным меткам; VM pacing измерен; возврат прошёл реальный operator gate.
Иначе фиксируйте `FAIL`/`INCONCLUSIVE` с последним доказанным шагом.

## Пакет доказательств

Для каждого случая создайте каталог с ограниченными правами и не сохраняйте
секреты:

```bash
export CASE_ID=CHG-000000
umask 077
mkdir -p "$CASE_ID"
date -u +%Y-%m-%dT%H:%M:%SZ | tee "$CASE_ID/timeline.txt"
```

Минимальное содержимое:

- change/incident ID, оператор, UTC start/end, cloud/region, hostname,
  segment/Node UUID;
- исходный и конечный базовый снимок;
- Mistral execution/task/action IDs, input/output/state_info либо Masakari
  notification/VMove IDs и полный status/message;
- список UUID ВМ до/после, source/destination, server event/migration;
- Ironic stable observations с UTC, число наблюдений и интервал;
- Nova administrative/process state и Masakari maintenance;
- etcd endpoint health/status из сетевого контекста сервисов;
- коррелированные отрывки логов без credentials;
- применённые значения timeout/poll/stable observations/pacing;
- итог `PASS`, `FAIL` или `INCONCLUSIVE`, последний доказанный шаг и явно
  непройденные проверки.

Не называйте локальные unit/syntax tests доказательством работы реального BMC,
lease etcd или Nova evacuation. И наоборот, успешный единичный canary не
доказывает capacity и поведение при конкурентных host failures; эти проверки
должны быть частью отдельного нагрузочного плана.

Официальная справка по использованным командам:

- OpenStack Mistral CLI: <https://docs.openstack.org/python-openstackclient/latest/cli/plugin-commands/mistral.html>
- Masakari CLI: <https://docs.openstack.org/python-masakariclient/latest/cli/masakari_commands.html>
- OpenStack server CLI 2025.1: <https://docs.openstack.org/python-openstackclient/2025.1/cli/command-objects/server.html>
- Ironic API: <https://docs.openstack.org/api-ref/baremetal/>
- etcd endpoint health/status: <https://etcd.io/docs/v3.5/tutorials/how-to-check-cluster-status/>
