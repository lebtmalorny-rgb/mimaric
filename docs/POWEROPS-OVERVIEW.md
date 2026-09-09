# PowerOps: устройство, сценарии и взаимодействие компонентов

Дата сверки: **9 сентября 2026 года**.

Это описание поставляемой реализации, а не проект будущей версии. База —
пользовательские архивы `0809` и дополнительный патч Masakari
`wait-for-Nova-down-after-confirmed-fencing`. `planned-return-v2` в документ
не включён. Значения на работающем стенде этим документом не подтверждаются.

Связанные документы:

- [Ручная диагностика всей цепочки](POWEROPS-DIAGNOSTICS.md).
- [Параметры, globals, Jinja-шаблоны и тайминги](POWEROPS-CONFIGURATION.md).

Дополнительный локальный отчёт — `AUDIT-2026-09-09-planned-off-live-migration.md`.
Он не входит в эту публикацию из трёх документов.

## 1. Назначение и границы

PowerOps связывает обслуживание существующих Nova compute-хостов с управлением
их физическим питанием через Ironic и BMC. Он обслуживает два независимых входа:

- плановая операция оператора → Mistral workflow;
- обнаруженный отказ хоста → Masakari notification → аварийное восстановление.

Ironic используется **только для питания**. Compute-хост не переводится в цикл
baremetal provisioning: ожидаются `provision_state=manageable`,
`network_interface=noop` и совместимые параметры enrollment. Cleaning,
переустановка ОС, PXE и перевод узла в `available` не являются частью PowerOps.

Главный принцип аварийной ветки: сначала подтвердить выключение исходного хоста
(fencing), затем дождаться Nova `disabled/down`, и только после этого эвакуировать
ВМ. Потеря LAN сама по себе не доказывает, что гипервизор и его ВМ остановлены.

## 2. Кто за что отвечает

| Компонент | Ответственность | Чего он здесь не делает |
|---|---|---|
| Kolla-Ansible | Генерация конфигурации, регистрация сервисов/ролей, запуск контейнеров, проверки загрузки расширений и сверка каталога Mistral/workbook | Не запускается при каждой операции питания |
| Keystone | Токены, роли, service catalog и доступ к API | Не принимает решение о миграции или fencing |
| Mistral API/engine/executor | Принимает плановый workflow, исполняет граф и PowerOps actions, хранит результат и ошибку | Не выполняет аварийную эвакуацию Masakari |
| Consul | Наблюдение сетевого членства; данные для решения hostmonitor | Не отключает BMC и не является распределённой блокировкой PowerOps |
| Masakari-hostmonitor | Оценивает Consul по настроенной политике и отправляет уведомление в Masakari API | Не является подтверждением физического выключения |
| Masakari API/engine | Приём уведомления, maintenance, TaskFlow fencing и восстановления ВМ | Не включает аварийный хост обратно автоматически |
| Nova | Административный статус compute, heartbeat, размещение/состояние ВМ, live migration и evacuation | `disabled` не означает остановку питания или ВМ |
| Ironic API/conductor и BMC | Запрос и наблюдение состояния питания точного физического узла | Не проверяют успешное восстановление гостевых приложений |
| etcd / tooz | Общая блокировка исходного хоста и отдельная глобальная блокировка аварийных перемещений ВМ | Не заменяют Nova/Ironic проверки состояния |
| RabbitMQ и БД сервисов | RPC, сохранение workflow/notification/task/action/VMove | Не являются доказательством физического состояния хоста |

Плановая и аварийная ветки сходятся на тех же Nova, Ironic и блокировке исходного
хоста. Для этого Mistral и Masakari должны использовать один совместимый backend
coordination и одинаковое каноническое имя хоста.

```text
Оператор → Mistral API → engine → executor / PowerOps action
                                    ├─ Masakari API: maintenance
                                    ├─ Nova: disable / stop / migrate / start
                                    └─ Ironic → conductor → BMC: питание

Consul → Masakari-hostmonitor → Masakari API → engine / TaskFlow
                                               ├─ Nova: disable
                                               ├─ Ironic → BMC: fencing
                                               ├─ Nova: дождаться down
                                               └─ Nova: evacuation → VMove

Mistral и Masakari → etcd/tooz: общий lock исходного хоста
Masakari           → etcd/tooz: глобальный lock одной эвакуируемой ВМ
```

### Имена и полномочия

Для одного compute должны однозначно совпадать Nova `service.host`, Masakari
`host.name` и Ironic `node.name`. В данном стенде это FQDN вида
`ultra1-3.ultra1.test.pvs.un.sbt`. IP для диагностического подключения к контроллеру
не подменяет это имя в workflow. У segment, Masakari host, Ironic node, Nova VM и
Nova compute service разные UUID: они не взаимозаменяемы.

Права вызывающего workflow пользователя проверяются отдельно от сервисных
учётных данных, которыми action обращается к облаку. В архиве Mistral `0809`
авторизация опирается на аутентифицированный RPC request context. Указание
пользователя/проекта в allowlists не создаёт роль `powerops_operator`, не назначает
её пользователю и не выдаёт доступ сервисной учётной записи.
Для hard-off действует отдельное ограничение полномочий.

## 3. Поставляемые workflow и пять плановых сценариев

В `etc/mistral/power_ops.yaml` находятся **четыре workflow**, а не пять отдельных
workflow по числу пользовательских сценариев.

| Сценарий | Workflow и вход | Что будет с ВМ | Конечное состояние при успехе |
|---|---|---|---|
| Плановое выключение без ВМ | `power_ops.planned_power_off`, `instance_policy=require_empty` | Наличие любой ВМ в Nova на source блокирует выключение | Source `power off`, Nova disabled, Masakari maintenance=true |
| Плановое выключение с ВМ на месте | Тот же workflow, `instance_policy=stop` | ACTIVE ВМ последовательно останавливаются; уже SHUTOFF не запускаются и не входят в список остановленных этой операцией | Source off; сохраняется `stopped_instance_ids` для возврата |
| Плановое выключение с миграцией | Тот же workflow, `instance_policy=live_migrate` | Только ACTIVE ВМ; последовательная live migration с подтверждением завершения | Source off и пуст по Nova; ВМ остаются на destination |
| Плановое включение без запуска ВМ | `power_ops.power_on_and_return`, `stopped_instance_ids=[]` | Workflow не запрашивает запуск ВМ | Сначала on + disabled/up + maintenance=true + PAUSED; после разрешённого возврата enabled/up и maintenance=false |
| Плановое включение с запуском ВМ | Тот же workflow, исходный `stopped_instance_ids` из успешного `stop` | Последовательный запуск только указанного списка, принадлежащего этому хосту | Та же ручная пауза; после возврата выбранные ВМ ACTIVE |

Пустой `stopped_instance_ids` означает «не запрашивать запуск ВМ», а не доказанную
пустоту гипервизора. Перемещённые или эвакуированные ВМ не возвращаются на старый
хост автоматически. Передача списка их UUID не является командой обратной
миграции: ВМ с другим текущим host будут отвергнуты.

Остальные workflow:

- `power_ops.host_power_status` — снимок состояния Ironic/Nova/Masakari. Он не
  берёт etcd lock и не доказывает готовность изменяющих actions.
- `power_ops.planned_reboot` — составная операция off → on с теми же тремя
  `instance_policy`; ждёт Nova disabled/up, запускает свой список остановленных
  ВМ и возвращает хост в сервис. **В этом workflow нет operator pause.** Это не
  способ обходить ручной возврат после аварийного fencing.

`powerops.power_on_for_inspection` и `powerops.return_to_service` — actions
внутри `power_on_and_return`, не отдельные workflow поставляемого YAML.

## 4. Плановое выключение: точный порядок

1. Проверить включение функции, авторизацию, входные параметры и взять общий
   lock канонического исходного хоста.
2. Однозначно разрешить соответствующий Ironic node, Nova service и Masakari host.
3. Установить Masakari `on_maintenance=true` и проверить результат чтением API.
4. Отключить планирование в Nova (`status=disabled`) и проверить readback.
   На этом шаге `disable_nova` само по себе не требует `state=up` или `down`.
5. Выполнить `require_empty`, `stop` либо `live_migrate`.
6. Повторить проверки безопасности соответствующей политики перед выключением.
7. Запросить через Ironic `soft power off` и дождаться нескольких совместимых
   наблюдений `power off` без ошибки и конфликтующего target state.
8. Сохранить результат workflow. Nova остаётся disabled, Masakari — на maintenance.

По умолчанию `allow_hard_off=false`. Жёсткое выключение допускается только при
явном Boolean `true`, разрешённых полномочиях и предусмотренном истечении
ожидания graceful shutdown. Неоднозначный timeout самого API-вызова не является
автоматическим разрешением повторить запрос как hard-off.

Плановый workflow **не ждёт Nova down после выключения**. Некоторое время после
`SUCCESS` ещё может наблюдаться `disabled/up`: heartbeat должен устареть.
Новый патч ожидания Nova down добавлен в Masakari, а не в этот Mistral action.

### Особенности `stop`

`stopped_instance_ids` содержит только ВМ, которые эта операция остановила из
ACTIVE. Исходные SHUTOFF ВМ не должны случайно запуститься при возврате.
Список следует сохранить вместе с execution UUID. При падении executor посередине
операции этот вариант не предоставляет доказанного долговечного журнала всех
уже остановленных ВМ: автоматическое восстановление списка не обещается.

### Особенности `live_migrate` после этапа 1

Mistral требует Nova microversion не ниже `2.59`, достаточные права на все
проекты/host/task поля и глобальную историю миграций, а также отключённый SDK
response cache. Один успешный POST или одна ACTIVE ВМ на destination недостаточны.

Для каждой ВМ снимается исходная история, отправляется один запрос миграции и
наблюдается новая migration UUID. Штатные промежуточные состояния, включая
`preparing`, `running`, `post-migrating`, допускаются. Для завершения требуются
`completed`, подходящий destination, ACTIVE ВМ на нём и **явный** `task_state=null`,
подтверждённые необходимым числом наблюдений. Затем выдерживается интервал между ВМ.

Перед power-off повторно проверяются история миграций source, подтверждения
перемещённых ВМ и полный список ВМ на source. Завершённая миграция первой ВМ не
даёт разрешения выключать хост, если вторая не завершилась.

Ограничения текущего этапа:

- SHUTOFF ВМ блокирует этот режим; cold migration и автоматический запуск перед
  миграцией в него не добавлены.
- Историческая evacuation со статусом `done` считается незавершённой для этих
  проверок и может блокировать дальнейшую плановую операцию. Нельзя вручную
  переписывать историю только ради обхода проверки.
- Нет общей транзакции между последним чтением Nova и Ironic power-off. Прямые
  параллельные Nova/BMC операции внешнего оператора не защищены lock PowerOps.
- Пустой список Nova и миграционные подтверждения не являются локальной
  инвентаризацией доменов libvirt. SSH-проверок исходного хоста здесь нет.

В указанном выше локальном отчёте проверки
описаны воспроизведённые состояния, включая этот случай `evacuation/done`.

## 5. Аварийная ветка: от Consul до эвакуации

### Обнаружение и приём уведомления

Hostmonitor принимает решение по фактическим контролируемым Consul-сетям и
сгенерированной matrix/policy. Потеря одного LAN не всегда равна отказу хоста:
значение имеют включённые сети, `all_down`/`majority_down`/`threshold`/`custom`,
число подтверждений и интервалы наблюдения. Формула «отключил кабель — через
строго N секунд выключится питание» не является контрактом.

Hostmonitor отправляет событие `COMPUTE_HOST` в Masakari API. Для хоста с
`on_maintenance=true` новое уведомление отклоняется. Поэтому перед тестом важен
снимок **до отказа**, а старое failed/error уведомление другого хоста или дня не
доказывает результат текущего теста.

В обработчике события `STOPPED` Masakari устанавливает maintenance; для
reserved-хоста также снимает reserved flag. Событие `STARTED` не выполняет
автоматическое включение BMC или возврат compute в сервис.

### Выполнение recovery с последним патчем

```text
Принятое уведомление STOPPED
  → maintenance=true
  → общий lock исходного хоста
  → disable_compute_service_task
      → Nova disabled
      → фиксированное wait_period_after_service_update
  → ironic_fence
      → Ironic/BMC power off
      → stable power-off подтверждён
      → НОВОЕ: дождаться единственного Nova service disabled/down
  → prepare_HA_enabled_instances_task
  → evacuate_instances_task
      → для каждой выбранной ВМ: global lock → evacuate → подтвердить → интервал
  → результат notification и отдельных VMove
```

Ожидание `wait_period_after_service_update` **перед fencing** и новый
`[powerops] nova_down_timeout` **после fencing** — разные этапы. В рассматриваемом
Masakari code default обоих равен 180 секундам, но только первое — фиксированная
задержка. Второе завершается раньше при наблюдении down; при up ждёт с polling.
Kolla `0809` не рендерит новый `nova_down_timeout`: без override действует default
кода. Все прочие таймеры и их владельцы — в [справочнике](POWEROPS-CONFIGURATION.md).

Новый gate не пишет `forced_down` и не подделывает heartbeat. Он требует ровно
один подходящий `nova-compute`, `status=disabled` и `state=down`. Missing/duplicate
service, enabled, неизвестное состояние, ошибка API или истечение срока не дают
начать evacuation. Отсутствие BMC-связи или невозможность доказать выключение
останавливают цепочку ещё раньше.

После fencing выбираются ВМ: либо все, либо только HA-enabled, в зависимости от
Masakari host-failure configuration. Выключение пустого хоста возможно: отсутствие
кандидатов обнаруживается **после fencing**, а `SkipHostRecoveryException` здесь
приводит notification к `finished`. Поэтому «хост off, VMove нет» само по себе не
означает неисправность.

При PowerOps аварийные ВМ обрабатываются последовательно в определённом порядке.
Глобальный lock `powerops/evacuation/global` удерживается на время одной evacuation,
её подтверждения и интервала после неё, в том числе между разными host-notification.
Это не глобальная блокировка всех плановых live migrations. Ошибка перемещения
не должна интерпретироваться как успех оставшихся pending ВМ.

Подтверждение VMove учитывает destination, отсутствие task и ожидаемое состояние
ВМ. **SHUTOFF на destination не обязательно ошибка**: исходно остановленная ВМ
может быть восстановлена остановленной. Сравнивать нужно состояние до отказа,
конкретный VMove и фактическую Nova VM, а не ожидать ACTIVE во всех случаях.

После аварийного fencing source остаётся выключенным, Nova disabled/down,
Masakari maintenance=true. Вставить LAN обратно недостаточно: это не команда
power-on. Если выключились два хоста, необходимо независимо восстановить цепочку
notification → fencing request → node UUID для каждого; один снимок `node list`
не доказывает единую причину или принадлежность одному тесту.

## 6. Включение и ручной возврат

Поставляемый `power_on_and_return` выполняет:

1. Под lock разрешает точный хост, подтверждает maintenance=true и Nova disabled.
2. Включает через Ironic, ждёт стабильный power-on и Nova disabled/up.
3. Останавливается перед `operator_inspection_gate` в `PAUSED`.
4. После разрешённого оператором продолжения action повторно берёт lock,
   проверяет stable power-on, Nova disabled/up и maintenance=true.
5. Проверяет manifest ВМ, последовательно запускает выбранные SHUTOFF ВМ,
   затем включает Nova scheduling и снимает maintenance.

`stale_domains_checked=true` — строго Boolean, но **это заявление оператора, а
не серверное доказательство обследования**. `ReturnToServiceAction` не проверяет
доверенный resume context, а перечисленные API-проверки не доказывают отсутствие
старых доменов на физическом гипервизоре. Пауза сама по себе эту проблему не решает.
Если источник выключен, отсутствие доступа к нему нельзя считать подтверждением
чистоты. Автоматическая очистка/доказуемый API-only возврат после аварии в эту базу
не добавлены; аварийный возврат остаётся ручным.

### 6.1. Что означает PAUSED и когда можно продолжать

В базовой линии `0809` этот workflow всегда делает ручную паузу перед
`operator_inspection_gate`: после планового выключения, после аварии и даже
если хост уже включён. `stopped_instance_ids: []` не отключает паузу; пустой
manifest означает, что action не должен запускать ВМ. После выключения с
`live_migrate` ВМ остаются на хостах назначения: возврат compute в обслуживание
не мигрирует их обратно. После режима `stop` передают точный manifest из результата
выключения; его не заменяют на `[]`, если требуется запуск остановленных ВМ.

Следующие команды выполняются на `ultra1-0` обычным пользователем с рабочим
OpenStack RC. Здесь нужен UUID уже созданного `power_ops.power_on_and_return`,
а не ID планового выключения или Masakari notification. Для другого хоста
измените имя и segment; UUID вводите без пробелов и переносов строки.

```bash
read -r -p 'UUID существующего power_on_and_return: ' POWEROPS_RETURN_EXEC
POWEROPS_RETURN_HOST=ultra1-2.ultra1.test.pvs.un.sbt
POWEROPS_RETURN_SEGMENT=b045da78-bc53-435a-937e-f12d41a217b1
timeout 30s openstack workflow execution show "$POWEROPS_RETURN_EXEC"
timeout 30s openstack workflow execution input show "$POWEROPS_RETURN_EXEC"
timeout 30s openstack task execution list "$POWEROPS_RETURN_EXEC"
timeout 30s openstack baremetal node show "$POWEROPS_RETURN_HOST" -f yaml -c uuid -c name -c power_state -c target_power_state -c last_error
timeout 30s openstack compute service list --host "$POWEROPS_RETURN_HOST" --service nova-compute --long
timeout 30s openstack segment host list "$POWEROPS_RETURN_SEGMENT"
timeout 30s openstack server list --all-projects --host "$POWEROPS_RETURN_HOST" --long
```

Перед продолжением должны быть согласованы все условия:

- execution относится к нужным host/segment и находится в `PAUSED`;
  `power_on_for_inspection = SUCCESS`, `operator_inspection_gate = IDLE`,
  `return_to_service` ещё не выполнялся;
- у точного Ironic node устойчивое `power on`, `target_power_state=null`,
  `last_error=null`; Nova compute — `disabled/up`, Masakari host —
  `on_maintenance=true`. Одного старого снимка недостаточно: перечитайте состояние;
- нет другой незавершённой операции для этого хоста; размещение и состояние
  ВМ согласованы с результатом предыдущего выключения/эвакуации и manifest;
- оператор действительно завершил проверку безопасности возврата, включая
  отсутствие старых копий эвакуированных ВМ и готовность storage/network.
  Пустой Nova server list, `power on` и `up` сами по себе этого не доказывают.

Здесь нет SSH-проверок. В `0809` перечисленные OpenStack API не дают полного
доказательства отсутствия stale domains после аварии. Если такое доказательство
не получено по принятому регламенту, оставьте workflow в `PAUSED` и не передавайте
подтверждение. Статус паузы — не повод обходить эту проверку.

### 6.2. После проверки: разрешить возврат и проверить результат

Это **изменяющая операция**, не диагностика. Выполняйте только после условий
раздела 6.1. Продолжите тот же execution один раз, передав Boolean `true`
в environment, а не строку `"true"` и не новый workflow input:

```bash
openstack workflow execution update "$POWEROPS_RETURN_EXEC" --state RUNNING --env '{"stale_domains_checked":true}'
```

Синтаксис `workflow execution update`, `--state` и `--env` сверён с
[регистрацией OSC-команд](https://github.com/openstack/python-mistralclient/blob/stable/2025.1/setup.cfg)
и [Update в python-mistralclient 2025.1](https://github.com/openstack/python-mistralclient/blob/stable/2025.1/mistralclient/commands/v2/executions.py).
В поставленном Mistral переход в `RUNNING` передаёт environment в
`resume_workflow`. Простой resume без подтверждения не заменяет проверку:
`ReturnToServiceAction` отклоняет отсутствующий или не-Boolean флаг.

Action заново получает блокировку и проверяет питание, Nova и maintenance;
при непустом manifest запускает только перечисленные ВМ, затем включает Nova
scheduling и снимает maintenance Masakari. С `[]` запуск ВМ пропускается.
Новый `workflow execution create`, прямой action, `task execution rerun`,
ручное выставление `SUCCESS` и ручные enable/maintenance-команды для штатного
продолжения не нужны.

После update перечитайте тот же execution и фактическое состояние:

```bash
timeout 30s openstack workflow execution show "$POWEROPS_RETURN_EXEC"
timeout 30s openstack task execution list "$POWEROPS_RETURN_EXEC"
timeout 30s openstack workflow execution output show "$POWEROPS_RETURN_EXEC"
timeout 30s openstack baremetal node show "$POWEROPS_RETURN_HOST" -f yaml -c uuid -c name -c power_state -c target_power_state -c last_error
timeout 30s openstack compute service list --host "$POWEROPS_RETURN_HOST" --service nova-compute --long
timeout 30s openstack segment host list "$POWEROPS_RETURN_SEGMENT"
```

Ожидаемый итог: execution и `return_to_service` — `SUCCESS`, Ironic — `power on`
без pending target/error, Nova — `enabled/up`, Masakari —
`on_maintenance=false`. В output — нужный `host`,
`operation=return_to_service`, `nova_enabled=true`,
`masakari_maintenance=false`; при пустом manifest — `stopped_instance_ids=[]`.
При непустом manifest дополнительно проверьте каждую ВМ по UUID: нужный host,
`ACTIVE`, `task_state=null`; состояние гостевых приложений проверяется отдельно.

Если update вернул `504`, timeout или связь оборвалась, результат запроса
неизвестен: сначала восстановите доступ к API и перечитайте этот UUID и tasks.
Не повторяйте update/create вслепую. При `ERROR` сохраните `state_info` и результаты
задач, проверьте фактические Nova/Masakari/Ironic состояния и устраните причину;
ошибка не разрешает вручную снять защитные статусы. При продолжающемся `RUNNING`
наблюдайте существующий execution, не запускайте второй возврат.

## 7. Ошибки, конкуренция и трактовка статусов

| Наблюдение | Правильная трактовка |
|---|---|
| Nova `disabled/up` | Scheduling выключен; compute ещё посылает heartbeat либо он пока не устарел |
| Nova `disabled/down` | Scheduling выключен и Nova считает service down; это не отдельное доказательство BMC power-off |
| Masakari `on_maintenance=true` | Новые уведомления для этого хоста не принимаются; это не выключение физического питания |
| Ironic `power off` | Наблюдение питания; для fencing нужны предусмотренные стабильные readback и совместимый target/last_error |
| Mistral `ERROR` | Операция не завершена по контракту; ранее принятые API-действия могли уже произойти |
| Mistral `SUCCESS` | Завершены проверки данного workflow, но не проверены гостевые приложения и все будущие состояния |
| Masakari notification `finished` | Завершён обработчик этого уведомления; нужно проверить VMove и число кандидатов |
| Timeout CLI | Клиент перестал ждать; серверная операция не обязательно отменена |

При ошибке планового action, уже начавшего обслуживание, предусмотрена попытка
оставить source в maintenance и Nova disabled. Потерянный lock не разрешает
обходить coordination для таких изменений. Нет гарантии rollback к исходным ВМ,
питанию и scheduling при любом обрыве процесса или сети.

Maintenance снижает вероятность конкуренции с новыми emergency notification, но
не создаёт автоматический переход planned → emergency. При настоящем отказе во
время `stop`/миграции workflow может завершиться ошибкой с частично выполненными
действиями; автоматическую эвакуацию оставшихся ВМ эта версия не гарантирует.
Общий lock также не отменяет уведомление, принятое до перехода в maintenance.

Не следует слепо повторять power/migration workflow после потери ответа, вручную
сбрасывать task/migration state или убирать maintenance ради «разблокировки».
Сначала восстановить временную линию и состояния по UUID, как описано в
[диагностике](POWEROPS-DIAGNOSTICS.md).

## 8. Что подтверждено и что ещё требует стенда

Алгоритмы выше сверены с локальными исходниками указанной базы. Отдельный
локальный аудит `AUDIT-2026-09-09-planned-off-live-migration.md` содержит результаты
локальных unit/SDK/engine сценариев с имитацией внешних API и отдельной тестовой
coordination. Они не являются приёмкой реальных BMC, сети, etcd, ролей, образов,
Nova scheduler/cells, libvirt/storage или гостевого приложения.

На стенде отдельно подтверждаются одинаковые образы/конфиги всех реплик,
загрузка action/task entry points, права фактических service accounts,
coordination, отсутствие SDK response cache, destination capacity и полный
чистый прогон с исходным снимком. Успешный redeploy или одиночный status-запрос
не заменяют эту проверку.

## 9. Исходники и точная версия

| Обозначение | База |
|---|---|
| M | `mistral-integration-powerops-mistral-2025.1 _0809.zip` — пробел перед `_0809` присутствует в имени |
| A | `masakari-integration-powerops-masakari-2025.1_0809.zip` + post-fence patch; проверенный commit `aabc8c0a9a874c798ff0c50139d15ed10472bd77` |
| K | `kolla-ansible-enroll-ironic-patch-3_0809.zip` |

SHA256 исходных артефактов:

```text
M: 3df7cd4afa9052251107335b0ec5771c2704ccf03894c7e6c1f34880a43daf0c
A archive: 0bbda50f9553b65a5757d7cc43ed47b4d2a8cf99641c4b9ce88a01d09f1bcde9
K: b5958f14a09b1bdad4edc9c6b3dd092f4376b55dee9d5814fd2ad78fdffb1be9
A post-fence patch: 319e1814cd4ab42be9df0bb7007e9c3cc36d9f7cbbc396a1a0b7558dc50ee43c
```

Навигация внутри соответствующих исходников:

- M: `etc/mistral/power_ops.yaml`, `mistral/actions/powerops/{base,clients,planned,return_host,live_migration,coordination}.py`, `mistral/services/powerops.py`.
- A: `masakari/api/`, `masakari/ha/api.py`, `masakari/engine/manager.py`,
  `masakari/engine/drivers/taskflow/{driver,host_failure,powerops}.py`,
  `masakari/powerops/{ironic,coordination}.py`, `masakari/conf/powerops.py`.
- K: `ansible/roles/{mistral,masakari,ironic,consul}/`,
  `ansible/group_vars/all.yml`, `kolla_ansible/masakari_consul.py`.

Дополнительный патч Masakari опубликован в репозитории `mimaric`, ветка
`codex/masakari-post-fence-nova-down`, каталог
`hotfixes/masakari-post-fence-nova-down/`. Проверенная публикация — commit
`3c350523bcf91ab598ce382e163dde10d2a249e5`; это ссылка на версию исходников,
не подтверждение её установки на стенд.
