# PowerOps: практическая диагностика без изменения состояния

Документ помогает установить, на каком переходе остановилась цепочка
`Consul -> masakari-hostmonitor -> Masakari -> Nova/Ironic` или плановая операция
`Mistral -> Nova/Ironic`. Проверки читают состояние и журналы. Они не запускают
выключение, reboot, live migration, evacuation или возврат хоста.

Архитектура и границы операций: [POWEROPS-OVERVIEW.md](POWEROPS-OVERVIEW.md).
Размещение параметров и правила конфигурации:
[POWEROPS-CONFIGURATION.md](POWEROPS-CONFIGURATION.md).

## 1. Область применимости и безопасность

Базовая линия документа:

| Компонент | Проверенный источник |
|---|---|
| Kolla-Ansible | Переданный вариант 0809, каталог `kolla-ansible-enroll-ironic-patch-3` |
| Mistral | Переданный вариант 0809, каталог `mistral-integration-powerops-mistral-2025.1`, включая `mistral/actions/powerops/live_migration.py` |
| Masakari | `aabc8c0a9a874c798ff0c50139d15ed10472bd77`, ожидание Nova `disabled/down` после подтвержденного fencing |
| Диагностический сборщик | Публикация v2: `tools/diagnostics/collect-v2.yml`; локальные исходники: `tools/diagnostics/files/collect.py` и `collect.yml` |

Это привязка к исходникам, а не утверждение, что эти версии уже работают на всех
репликах стенда. Образ, загруженный конфиг и журнал конкретной реплики проверяют
отдельно, как показано ниже.

Не выполняйте во время диагностики команды изменения питания, `server migrate`,
`server evacuate`, reset-state, изменения Nova service enable/disable/forced-down,
Masakari maintenance, Ironic maintenance, resume/rerun workflow, restart,
reconfigure, удаления очередей или блокировок. Включение `--debug`, полный
`podman inspect`, вывод `Env`, `driver_info`, RC-файлов и конфигов с паролями тоже
не нужны. Не проверяйте безопасность выключенного compute через SSH.

CLI самостоятельно получает и передает токен. Не извлекайте его для вставки в
аргументы `curl`, не выводите заголовки Authorization и не включайте `set -x`.
Результаты задач и журналы могут содержать сведения об инфраструктуре; сохраняйте
их приватно и проверяйте перед передачей. Сборщик маскирует типовые секреты, но
не гарантирует очистку произвольного текста приложения.

## 2. Где выполнять команды и как выбрать инцидент

API-команды выполняются на операторском узле `ultra1-0`, обычным пользователем,
в уже работающем окружении OpenStack. Не запускайте их через `sudo`: это может
потерять авторизацию и подменить окружение. Примеры рассчитаны на Bash/Linux;
`timeout` ограничивает время диагностического процесса, `jq` фильтрует JSON.
Команды вводятся по одной строке. `read` запрашивает реальный UUID, без угловых
скобок и без использования UUID из старого инцидента.

```bash
command -v openstack
command -v jq
command -v timeout
openstack --version
date -u '+%Y-%m-%dT%H:%M:%SZ'
```

Проверяйте identity, регион и interface принятого окружения, не распечатывая
весь `env`. Начальные запросы:

```bash
timeout 30s openstack service list -f json
timeout 30s openstack endpoint list -c 'Service Type' -c Interface -c URL -f json
```

Ожидаются сервисы `compute`, `baremetal`, `instance-ha`, `workflowv2` и подходящие
endpoint. VIP данного inventory - `10.101.25.42`; endpoint надо брать из
действующего каталога, с его схемой HTTP/HTTPS и регионом. Успех identity не
подтверждает доступность каждого downstream API. При `401` проверяйте авторизацию,
при `403` - policy/роль/область токена, при неизвестной CLI-команде - plugin.
Код `124` от `timeout` означает, что проверка прервана по времени.

Выберите один исходный compute и окно события. Время вводится в UTC, например
`2026-09-09T06:00:00Z`; используйте фактические даты своего инцидента.

```bash
HOST=ultra1-2.ultra1.test.pvs.un.sbt
read -r -p 'Начало UTC, YYYY-MM-DDTHH:MM:SSZ: ' SINCE
read -r -p 'Конец UTC, YYYY-MM-DDTHH:MM:SSZ: ' UNTIL
printf 'host=%s since=%s until=%s\n' "$HOST" "$SINCE" "$UNTIL"
```

Для другого compute замените `HOST`. Полное имя здесь является API-идентификатором;
его использование не требует DNS-доступности самого compute.

| Узел | Management/LAN IP из inventory 0809 |
|---|---|
| `ultra1-2.ultra1.test.pvs.un.sbt` | `10.101.25.146` |
| `ultra1-3.ultra1.test.pvs.un.sbt` | `10.101.25.147` |
| `ultra1-6.ultra1.test.pvs.un.sbt` | `10.101.25.150` |
| `ultra1-7.ultra1.test.pvs.un.sbt` | `10.101.25.151` |
| `ultra1-8.ultra1.test.pvs.un.sbt` | `10.101.25.152` |

Эти адреса не являются BMC-адресами. SSH к контроллерам ниже используется только
для чтения локального состояния/журналов. Отсутствие SSH к failed compute не мешает
API-диагностике и не является доказательством fencing.

## 3. Приватный сбор журналов и двух API-снимков

На операторе используйте опубликованный одиночный
[collect-v2.yml](https://github.com/lebtmalorny-rgb/mimaric/blob/main/tools/diagnostics/collect-v2.yml).
В локальном каталоге разработки эквивалентный файл называется `collect.yml`;
имя публикации и имя исходного файла не надо смешивать. Плейбук содержит inventory
и сборщик; отдельные Python-файлы для его запуска не нужны.

Если файл уже получен, укажите его фактическое имя:

```bash
COLLECTOR=collect-v2.yml
ansible-playbook "$COLLECTOR" --syntax-check
```

По умолчанию сборщик пытается читать журналы пяти узлов из таблицы. Для отказа
compute выберите только контроллеры `.150/.151/.152` как источники SSH-журналов;
API продолжат опрашивать выбранный `HOST`. Следующие переменные содержат только
идентификаторы и время:

```bash
LOG_HOSTS='{"diag_hosts":["ultra1-6.ultra1.test.pvs.un.sbt","ultra1-7.ultra1.test.pvs.un.sbt","ultra1-8.ultra1.test.pvs.un.sbt"]}'
DIAG=$(jq -nc --arg h "$HOST" --arg s "$SINCE" --arg u "$UNTIL" '{diag:{compute_hosts:[$h],since:$s,until:$u}}')
ansible-playbook "$COLLECTOR" -e "$LOG_HOSTS" -e "$DIAG"
```

При необходимости добавьте `-u USERNAME`; если sudo требует пароль, добавьте
`-K`. Весь playbook через sudo не запускается. Host-key checking сохраняется.
Перед привилегированным чтением сборщик сверяет `hostname -f` с ожидаемым FQDN.
Это проверка источника журналов, не проверка безопасности ВМ.

Ожидается новый `artifacts/powerops-diag-XXXXXXXX.txt`: каталог `0700`, файл
`0600`. Скопируйте напечатанный путь:

```bash
read -r -p 'Путь к TXT отчета: ' REPORT
sed -n '1,100p' "$REPORT"
grep -n -F -C 5 -- "$HOST" "$REPORT"
```

`COLLECTED` означает полноту в пределах настроенных ограничений, `PARTIAL` -
ошибки/таймауты/усечения/недоступные поля. Ни один статус не подтверждает успешную
эвакуацию или отсутствие ошибок в облаке. Exit code `0` Ansible также не заменяет
чтение сводки. Сборщик создает временные файлы Ansible и приватный локальный
результат; конфигурацию и состояние сервисов он не меняет.

Сначала и в конце читаются API, а журналы ограничены фиксированным интервалом.
Это два неатомарных снимка. Если операция продолжалась после `UNTIL`, задайте новый
интервал и выполните отдельный сбор. Отсутствие строки в усеченном или ротированном
логе не доказывает отсутствие события.

После определения UUID можно повторить сбор точнее:

```bash
DIAG=$(jq -nc --arg h "$HOST" --arg s "$SINCE" --arg u "$UNTIL" --arg n "$NOTIF" '{diag:{compute_hosts:[$h],since:$s,until:$u,notification_id:$n}}')
ansible-playbook "$COLLECTOR" -e "$LOG_HOSTS" -e "$DIAG"
```

Этот пример применяется после раздела 5, когда `NOTIF` уже установлен. Для
планового сценария после раздела 8 используйте `workflow_ids`:

```bash
DIAG=$(jq -nc --arg h "$HOST" --arg s "$SINCE" --arg u "$UNTIL" --arg e "$EXEC" '{diag:{compute_hosts:[$h],since:$s,until:$u,workflow_ids:[$e]}}')
ansible-playbook "$COLLECTOR" -e "$LOG_HOSTS" -e "$DIAG"
```

## 4. Consul и masakari-hostmonitor: было ли обнаружено событие

Сначала исследуйте уже очищенный отчет на операторе:

```bash
grep -n -E -C 5 'consul|hostmonitor|HostOnMaintenance|duplicate|notification' "$REPORT"
```

Для локальных команд войдите на доступный контроллер по его IP. Например:

```bash
ssh -o BatchMode=yes -o ConnectTimeout=10 10.101.25.150
hostname -f
sudo podman ps -a --format '{{.Names}} {{.Image}} {{.Status}}'
```

Ожидаемый FQDN для этого IP - `ultra1-6.ultra1.test.pvs.un.sbt`. Если имя не
совпадает, эти журналы не относятся к ожидаемому источнику. Следующие команды
раздела выполняются в сессии контроллера. Сначала найдите реальные имена
контейнеров. В Kolla0809 определены `consul_management`, `consul_customer`,
`consul_storage`, но фактически включенный набор зависит от inventory/сетей.

Прочитайте только параметры драйвера и endpoint hostmonitor:

```bash
sudo podman exec masakari_hostmonitor python -c 'import configparser; c=configparser.ConfigParser(interpolation=None); c.read("/etc/masakari-monitors/masakari-monitors.conf"); ks=("monitoring_driver","monitoring_interval","monitoring_samples"); print({k:c.get("host",k,fallback="<not set>") for k in ks})'
sudo podman exec masakari_hostmonitor python -c 'import configparser; c=configparser.ConfigParser(interpolation=None); c.read("/etc/masakari-monitors/masakari-monitors.conf"); ks=("agent_manage","agent_tenant","agent_storage","matrix_config_file"); print({k:c.get("consul",k,fallback="<not set>") for k in ks})'
sudo podman exec masakari_hostmonitor sed -n '1,180p' /etc/masakari-monitors/matrix.yaml
```

Вывод ограничен именованными параметрами monitoring и адресами Consul.
Ожидаются `monitoring_driver=consul`,
корректные `monitoring_interval`/`monitoring_samples` и путь к фактической матрице.
Отсутствие секции или файла фиксируется как несовпадение с конфигурацией 0809.

Матрица описывает решение по нескольким сетям. При политике `all_down` отказ
только одной контролируемой сети не обязан запускать recovery. Значения
`manage`, `tenant`, `storage` - имена сетей hostmonitor; Kolla связывает их с
`management`, `customer`, `storage`. Оценивайте именно включенные сети и загруженную
матрицу, не число всех контейнеров с `consul` в имени.

Для каждой реально контролируемой сети выберите соответствующий Consul endpoint
из проверенной конфигурации. Не подменяйте три endpoint одним loopback-адресом,
если фактически они должны обозначать разные агенты/сети.

```bash
read -r -p 'Имя контейнера Consul: ' CONSUL_CONTAINER
read -r -p 'Consul HTTP URL без credentials: ' CONSUL_URL
sudo podman exec "$CONSUL_CONTAINER" consul members -http-addr="$CONSUL_URL"
```

Ожидается член с точным FQDN исходного compute. `alive`/`failed` - наблюдение
gossip конкретного агента. Представления разных агентов могут кратковременно
отличаться. Это не физическое состояние питания.
[Consul Agent API](https://developer.hashicorp.com/consul/api-docs/agent).

Задайте `HOST` также в сессии контроллера и прочитайте проверки нужного узла:

```bash
HOST=ultra1-2.ultra1.test.pvs.un.sbt
curl --fail --silent --show-error --connect-timeout 5 --max-time 20 "$CONSUL_URL/v1/health/node/$HOST" | jq 'map({Node,CheckID,ServiceName,Status})'
```

Этот GET показывает зарегистрированные health checks выбранного узла. Поле
`Output` намеренно не выводится. `passing`, `warning`, `critical` надо сопоставлять
с membership и матрицей; пустой массив может означать неверную сеть/имя/область
ACL. Если Consul требует ACL, используйте уже настроенный защищенный клиент или
curl config с токеном в файле. Не вставляйте токен в аргументы команды и не
отключайте ACL/TLS для проверки.
[Consul Health API](https://developer.hashicorp.com/consul/api-docs/health).

Следующее диагностическое разветвление:

| Наблюдение | Следующая проверка |
|---|---|
| Consul видит отказ, hostmonitor не сообщает HOST failure | Endpoint каждой сети, матрица, samples/interval, жив ли процесс hostmonitor |
| Hostmonitor отправляет событие, нового notification нет | Ответ Masakari API, имя/UUID segment host, maintenance, duplicate detection, права monitor |
| В логах `ignored ... already under maintenance` | Прочитать `on_maintenance` и предыдущее notification; это штатное отклонение нового события |
| Отказ только одной сети при `all_down` | Сверить остальные сети и матрицу; отсутствие recovery само по себе ожидаемо |

Выйдите из сессии контроллера перед следующими OpenStack-командами:

```bash
exit
```

## 5. Masakari: правильный segment, notification и VMove

На операторе получите segment и хосты:

```bash
timeout 30s openstack segment list -f json
read -r -p 'Segment UUID: ' SEGMENT
timeout 30s openstack segment show "$SEGMENT" -f json
timeout 30s openstack segment host list "$SEGMENT" -f json
```

Ожидается однозначный host с именем, равным `HOST`. Запишите UUID именно
Masakari host, не UUID segment, Ironic node или Nova service. Проверьте
`on_maintenance`, `reserved`, `recovery_method` segment. Если хост не найден или
есть неоднозначность, связь цепочки пока не установлена.

```bash
read -r -p 'Masakari host UUID: ' HA_HOST
timeout 30s openstack segment host show "$SEGMENT" "$HA_HOST" -f json
timeout 30s openstack notification list --filters "source_host_uuid=$HA_HOST" --sort created_at:desc --limit 20 -f json
read -r -p 'Notification UUID текущего события: ' NOTIF
timeout 30s openstack notification show "$NOTIF" -f json
```

Сопоставьте `source_host_uuid`, `type`, `generated_time`, `created_at`, `payload`,
`status` и подробности recovery, если они доступны в ответе. Для host recovery
нужно уведомление соответствующего типа `COMPUTE_HOST`, относящееся к заданному
окну. Последний исторический `ERROR` не становится новым инцидентом из-за того,
что он первый в списке. `--limit` у клиента может задавать размер страницы;
при большом объеме учитывайте общий таймаут и полноту вывода.

ВМ, которые Masakari пытался переместить:

```bash
timeout 30s openstack notification vmove list "$NOTIF" --limit 50 -f json
read -r -p 'VMove UUID из списка: ' VMOVE
timeout 30s openstack notification vmove show "$NOTIF" "$VMOVE" -f json
grep -n -F -C 8 -- "$NOTIF" "$REPORT"
```

Команды `read VMOVE` и `vmove show` нужны только при непустом списке. Сверяйте
UUID ВМ, исходный и целевой хосты, статус/время каждого VMove с Nova. Пустой VMove
нормален, если подходящих ВМ не было, либо recovery еще не дошел до эвакуации.
Одного `notification=finished` недостаточно для утверждения о размещении конкретной ВМ.
В этой версии отсутствие подходящих ВМ может приводить к
`SkipHostRecoveryException`, которую manager завершает статусом `finished`.
Поэтому подтвержденный off вместе с пустым VMove может быть штатным результатом.

Если уведомление осталось `new`/`running`, ищите прием UUID в `masakari-engine`,
ошибки RPC и координации. Если оно `error`, найдите первую ошибку шага перед
сообщениями rollback. Текущее `on_maintenance=true` не восстанавливает его
значение на момент старого события: для этого нужен журнал.

## 6. Nova: service, текущие ВМ и история, включая уже ушедшие ВМ

На операторе:

```bash
timeout 30s openstack compute service list --host "$HOST" --service nova-compute -f json
timeout 30s openstack server list --all-projects --host "$HOST" -c ID -c Name -c Status -f json
```

`Status=disabled` - административный запрет планирования; `State=down` - оценка
heartbeat сервисом Nova. `disabled/up` и `disabled/down` - разные состояния.
Сравнивайте время обновления service с временем fencing и локальной синхронизацией
часов. Принудительная установка down для ускорения проверки здесь не применяется.

Если ВМ уже мигрировала, ее не будет в текущем списке исходного хоста. Запросите
историю миграций по хосту; фильтр охватывает source/destination:

```bash
timeout 30s openstack --os-compute-api-version 2.66 server migration list --host "$HOST" --changes-since "$SINCE" --changes-before "$UNTIL" --limit 100 -f json
```

Нужны microversion Nova 2.66+ и разрешение policy для этой истории. Версия
передается только запросу; серверные настройки не меняются. `403` или отказ
microversion означает отсутствие данных, а не отсутствие миграций. При достижении
лимита повторите запрос по более узкому времени или используйте UUID известной ВМ.

Возьмите UUID из VMove, migration history, workflow или списка до операции:

```bash
read -r -p 'Server UUID: ' SERVER
timeout 30s openstack server show "$SERVER" -f json | jq '{id,name,status,host_field_present:has("OS-EXT-SRV-ATTR:host"),host:."OS-EXT-SRV-ATTR:host",task_field_present:has("OS-EXT-STS:task_state"),task_state:."OS-EXT-STS:task_state",vm_state:."OS-EXT-STS:vm_state",power_state:."OS-EXT-STS:power_state",fault}'
timeout 30s openstack server event list "$SERVER" -f json
timeout 30s openstack server migration list --server "$SERVER" -f json
```

Ожидаемый результат успешного переноса: Nova показывает нужный целевой host,
завершенную относящуюся к событию миграцию и отсутствие активного `task_state`.
Одно `ACTIVE` не доказывает перенос. `task_field_present=false` означает, что
показанное jq значение `null` получено из отсутствующего поля, а не является
явным подтверждением Nova. Аналогично проверяйте `host_field_present`.
Пустой `fault` не доказывает, что ошибки не
было раньше. Для детального события используйте request ID из event list:

```bash
read -r -p 'Request ID из server event list: ' REQUEST
timeout 30s openstack server event show "$SERVER" "$REQUEST" -f json
grep -n -F -C 8 -- "$SERVER" "$REPORT"
grep -n -F -C 8 -- "$REQUEST" "$REPORT"
```

Для плановой live migration различайте принятие запроса и завершение переноса.
Если API action живет, а миграция зависла/завершилась ошибкой, коррелируйте UUID
миграции и `req-...` с `nova-conductor`, `nova-scheduler` и доступными журналами
compute. Отсутствие доступа к исходному compute фиксируйте как ограничение.
Состояние libvirt/stale domains через эти API не доказано.

## 7. Ironic и аварийный fencing

На операторе запросите node по точному имени compute, с явным списком полей:

```bash
timeout 30s openstack baremetal node show "$HOST" --fields uuid name power_state target_power_state last_error provision_state network_interface maintenance -f json
```

Ожидается один node с совпадающим именем. В power-only схеме проверяйте
`network_interface=noop` и `provision_state=manageable`, а не готовность Ironic
развертывать ОС. `maintenance` Ironic и `on_maintenance` Masakari - отдельные
состояния. Не выводите `driver_info`: он содержит BMC credentials.

| Поле/состояние | Что означает и куда смотреть |
|---|---|
| `power_state=power off`, `target_power_state=null` | Текущее чтение состояния завершено; для stable-off нужна последовательность наблюдений операции |
| `target_power_state` не пуст | Есть незавершенный переход; сопоставить с таймаутом и conductor log |
| `last_error` не пуст | Сохранить сообщение приватно, проверить права Ironic, driver/conductor и время запроса |
| `last_error` скрыт политикой | Данных недостаточно; это не доказательство отсутствия ошибки |
| Node не найден | Проверить точное соответствие Nova hostname и Ironic name/UUID |
| Power off есть, эвакуации еще нет | Проверить stable-off, затем Nova `disabled/down` и постфенсинговый шаг Masakari |

Повторное чтение команды дает новый снимок. Несколько ручных снимков сами по себе
не удостоверяют, что операция сохраняла владение блокировкой между чтениями.

На операторе найдите переходы нового Masakari в отчете:

```bash
grep -n -E -C 8 'Ironic confirmed power off|Nova confirmed disabled/down|after fencing|evacuation is not permitted|Fencing for host' "$REPORT"
```

В `aabc8c0` порядок такой: Ironic подтверждает stable `power off`, Masakari
начинает ждать Nova, получает `status=disabled` вместе с `state=down`, затем
разрешает продолжение recovery. Основные сообщения:

| Сообщение | Интерпретация |
|---|---|
| `Ironic confirmed power off ... waiting ... for Nova disabled/down` | Физическое выключение подтверждено ранее; сейчас ожидается Nova |
| `Nova confirmed disabled/down ... host recovery may proceed` | Постфенсинговый барьер пройден; это еще не завершение эвакуации |
| `Timed out ... after fencing; evacuation is not permitted` | В рамках ожидания Nova не подтвердила требуемое состояние; запуск эвакуации запрещен |
| `Cannot verify Nova compute service ... after fencing` | Ошибка чтения/авторизации/API; отсутствие ответа не трактуется как down |
| `Unsafe Nova compute service ...` | Получен enabled либо неизвестное состояние; recovery остановлен |
| `previously confirmed power off ... current power state is not rechecked during rollback` | Историческое подтверждение off; rollback не подтверждает текущее питание и не включает узел |

`[powerops] nova_down_timeout` в новом Masakari по умолчанию равен 180 секундам.
Kolla0809 его отдельно не рендерит. Это значение относится только к новому коду,
а не доказывает версию или настройку запущенного контейнера. При таймауте проверьте
Nova service, RPC/часы, конфигурацию и образ Masakari; не обходите барьер вручную.
Отдельная пауза `wait_period_after_service_update` относится к
`disable_compute_service_task` до fencing. Ее сообщение `Sleeping ... before
starting recovery` не означает, что новый постфенсинговый барьер уже пройден.

## 8. Mistral: каталог, execution, task и action result

Эта часть нужна для плановых операций. Аварийная цепочка Masakari fencing/evacuation
не обязана создавать execution в Mistral.

На операторе сначала отделите доступность API от регистрации PowerOps:

```bash
timeout 30s openstack workbook list -f json
timeout 30s openstack action definition show std.noop -f json
timeout 30s openstack action definition show powerops.host_power_status -f json
timeout 30s openstack workflow list -f json
```

Это чтение каталога, без запуска action. При недоступности всех запросов исследуйте
auth/API/Keystone. Если workbook читается, а action-запросы зависают, проверяйте
action loader и API logs. Если не читается только PowerOps action, проверяйте
его регистрацию и установленный код. Успех `action definition show` не проверяет
конфиг executor и не выполняет безопасностные проверки операции. Имена команд
соответствуют OSC entry points клиента 2025.1.
[Регистрация команд Mistral CLI](https://github.com/openstack/python-mistralclient/blob/stable/2025.1/setup.cfg).

Найдите execution в окне инцидента:

```bash
timeout 30s openstack workflow execution list --sort_keys created_at --sort_dirs desc --limit 50 -f json
read -r -p 'Workflow execution UUID: ' EXEC
timeout 30s openstack workflow execution show "$EXEC" -f json
timeout 30s openstack workflow execution input show "$EXEC"
timeout 30s openstack workflow execution output show "$EXEC"
timeout 30s openstack task execution list "$EXEC" --limit 50 -f json
```

Сверьте `workflow_name`, host/segment входа, `instance_policy`, `allow_hard_off`,
created/updated time, `state` и `state_info`. В базовой линии имена workbook
начинаются с `power_ops.`, action - с `powerops.`. Старое `RUNNING` может относиться
к другому инциденту; большой поток других workflow может вытеснить нужный UUID из
ограниченного списка. Используйте известный точный UUID, если он сохранен.

Для подозрительного task:

```bash
read -r -p 'Task execution UUID: ' TASK
timeout 30s openstack task execution show "$TASK" -f json
timeout 30s openstack task execution result show "$TASK"
timeout 30s openstack action execution list "$TASK" --limit 50 -f json
```

Если action execution есть, прочитайте его результат отдельно:

```bash
read -r -p 'Action execution UUID: ' ACTION
timeout 30s openstack action execution show "$ACTION" -f json
timeout 30s openstack action execution output show "$ACTION"
grep -n -F -C 10 -- "$ACTION" "$REPORT"
grep -n -F -C 8 -- "$EXEC" "$REPORT"
```

Результат задач/действий читается только для нужного execution и остается
конфиденциальным. В error/result важна исходная ошибка и traceback executor;
короткое `msg=''` в engine не объясняет причину. Correlation по `action_ex_id`
позволяет найти реплику, которая действительно выполняла action.
UUID задачи у `action execution list` - позиционный аргумент.
[Исходник python-mistralclient 2025.1](https://github.com/openstack/python-mistralclient/blob/stable/2025.1/mistralclient/commands/v2/action_executions.py).

| Наблюдение | Следующий шаг |
|---|---|
| `PowerOpsDisabled` | Секция `[powerops]` в фактическом конфиге именно executor, image ID всех реплик, граница секции после `[coordination]` |
| `PowerOpsUnauthorized` / `403` | Роль вызывающего пользователя, разрешенные project/user, API policy; чтение API оператором не доказывает права service account |
| `HostResolutionError` | Точное совпадение имен/UUID Nova, segment host и Ironic node |
| `InstancePolicyError` | Политика ВМ, состояния и подтверждение завершения всех миграций перед power request |
| `PowerStateError` / `PowerOpsTimeout` | Ironic state/target/error, соответствующий task/result, проводилась ли вообще отправка power request |
| `RUNNING`, нет дальнейших задач | Состояние action, executor, RPC очередей, блокировки и deadline; снимок API не доказывает зависание процесса |
| `PAUSED` на `operator_inspection_gate` | Ожидаемая ручная пауза возврата; не ошибка и не повод выполнять resume во время диагностики |

Плановый return и аварийное восстановление не делают проверку stale domains
истинной автоматически. `stale_domains_checked=true` - не диагностическая команда
и не замена обследованию хоста. При пустом списке ВМ отсутствие migrate/evacuate
само по себе нормально; оценивайте переходы host/service/power.

Для штатной паузы возврата ожидаются `power_on_for_inspection = SUCCESS`,
`operator_inspection_gate = IDLE` и ещё не выполнявшийся `return_to_service`.
Хост уже включён, но сохраняет Nova `disabled/up` и Masakari maintenance.
В `0809` эта пауза есть и после планового выключения; `stopped_instance_ids: []`
не отменяет её и не возвращает мигрировавшие ВМ на исходный хост.

Когда диагностика закончена и проверка безопасности возврата действительно
пройдена, переходите к отдельной изменяющей процедуре:
[«После проверки: разрешить возврат и проверить результат»](POWEROPS-OVERVIEW.md#62-после-проверки-разрешить-возврат-и-проверить-результат).
Там приведены условия допуска, команда продолжения существующего execution,
контроль результата и действия при `504`/timeout. Не включайте её в автоматический
диагностический сбор: статус `PAUSED` сам по себе не является разрешением resume.

Плановый Mistral power-off не использует новый барьер Nova down из Masakari:
после успешного выключения некоторое время возможен `disabled/up`, пока не
устарел heartbeat. Не переносите критерий аварийной эвакуации на этот workflow.
Для `instance_policy=live_migrate` текущая реализация может считать историческую
`evacuation` со статусом `done` незавершенной и остановить проверку перед питанием.
Это проверяют по глобальной истории и action result; ручное редактирование
истории не является способом диагностики. SHUTOFF ВМ также блокирует этот
плановый режим, тогда как SHUTOFF на destination после аварийного recovery
не обязательно ошибка: учитывайте исходное состояние ВМ.

## 9. Координация etcd/Tooz и RabbitMQ

Сначала на операторе найдите ошибки в очищенном отчете:

```bash
grep -n -E -C 8 'coordination|lease|heartbeat|ownership|PowerOps lock|etcd|MessagingTimeout|AMQP|rabbit|quorum|osiris' "$REPORT"
```

Mistral использует логическое имя host lock `powerops/host/<canonical-hostname>`.
Фактическое представление ключа в etcd зависит от Tooz. Не делайте вывод
"блокировка свободна" по отсутствию угаданного KV path. Диагностика не берет
реальные PowerOps locks, не продлевает lease и ничего не удаляет. Доступный etcd
endpoint и наличие lock key не доказывают текущего владельца или линейризуемость
всех действий операции.

Для следующих команд войдите на контроллер с контейнерами etcd/RabbitMQ по IP,
как в разделе 4. Задайте endpoint etcd по проверенному конфигу, без credentials.
Пример адреса VIP применим только если фактическая схема HTTP и порт совпадают:

```bash
ETCD_ENDPOINT=http://10.101.25.42:2379
sudo podman exec etcd etcdctl --endpoints="$ETCD_ENDPOINT" --dial-timeout=5s --command-timeout=20s endpoint status --write-out=table
sudo podman exec etcd etcdctl --endpoints="$ETCD_ENDPOINT" --dial-timeout=5s --command-timeout=20s member list --write-out=table
sudo podman exec etcd etcdctl --endpoints="$ETCD_ENDPOINT" --dial-timeout=5s --command-timeout=20s alarm list
```

Эти команды читают status, membership и alarms. Повторите `endpoint status` для
прямых клиентских endpoint членов из `member list`: один VIP может показать только
одного backend. Сравните cluster/member IDs, leader, raft term/index и errors.
При TLS нужны реальные HTTPS endpoint и настроенные CA/client certificate;
не отключайте проверку сертификата и не выводите содержимое ключей. При отсутствии
`etcdctl` зафиксируйте ограничение и используйте журналы; установка/перезапуск
контейнера не являются диагностикой.
[etcdctl: endpoint status, member list, alarm list](https://github.com/etcd-io/etcd/blob/main/etcdctl/README.md).

RabbitMQ на каждом соответствующем контроллере:

```bash
sudo podman exec rabbitmq rabbitmq-diagnostics -q check_running
sudo podman exec rabbitmq rabbitmq-diagnostics -q check_local_alarms
sudo podman exec rabbitmq rabbitmqctl cluster_status
sudo podman exec rabbitmq rabbitmqctl list_vhosts name
```

Ожидаются работающий broker, отсутствие resource alarms и согласованный состав
кластера. Успех одной реплики не подтверждает состояние остальных.
[RabbitMQ diagnostics](https://www.rabbitmq.com/docs/man/rabbitmq-diagnostics.8).

Выберите фактический RPC vhost из конфигурации/списка. Не распечатывайте
`transport_url`, так как он содержит пароль.

```bash
read -r -p 'RPC vhost, обычно /: ' VHOST
sudo podman exec rabbitmq rabbitmqctl list_queues -p "$VHOST" name consumers messages_ready messages_unacknowledged state | grep -E 'masakari|mistral|nova|name'
```

Рост `messages_ready` вместе с отсутствием ожидаемых consumers указывает на
проблему доставки/получателя; высокий `unacknowledged` требует проверки занятых
или остановившихся обработчиков. Имена reply/fanout очередей зависят от версии и
`use_queue_manager`: отсутствие строки по этому фильтру не доказывает отсутствие
очереди. Для конкретного имени из service log прочитайте его строку в списке
нужного vhost. Нулевые счетчики не доказывают корректность action.
Не выполняйте purge, delete, reset или изменения policy очередей.
[RabbitMQ list_queues](https://www.rabbitmq.com/docs/man/rabbitmqctl.8).

## 10. Время, образ, процесс и фактический конфиг

Команды этого раздела выполняются локально на каждом доступном контроллере.

```bash
date -u '+%Y-%m-%dT%H:%M:%SZ'
timedatectl show --property=NTPSynchronized --property=Timezone --property=TimeUSec
chronyc tracking
chronyc -n sources
sudo podman ps -a --format '{{.Names}} {{.Image}} {{.Status}}'
```

Сравните UTC всех источников, синхронизацию и chrony offset. Логи без timezone
интерпретируются по их реальной зоне, а не по зоне ноутбука. У сборщика
`log_timezone=+00:00` по умолчанию; если сервис пишет иначе, это надо явно учесть
при выборе окна.

Выберите контейнер, который принимал нужный UUID. Сводное чтение разрешенных
полей исключает Env, секреты конфигурации и healthcheck output:

```bash
CONTAINER=masakari_engine
sudo podman inspect --format 'image_id={{.Image}} status={{.State.Status}} running={{.State.Running}} exit={{.State.ExitCode}} oom={{.State.OOMKilled}} started={{.State.StartedAt}} finished={{.State.FinishedAt}}' "$CONTAINER"
```

Повторите для `mistral_api`, `mistral_engine`, `mistral_executor`, `masakari_api`
и реальных Ironic containers. Одинаковый tag не доказывает одинаковое содержимое;
сравнивайте image ID/digest между репликами. `Running=true` не доказывает
готовность RPC/API. Для остановленного контейнера сопоставьте exit/OOM/start/finish
с kernel/conmon/Podman журналами из отчета.

Прочитайте только выбранные настройки из файла внутри контейнера. Короткий
Python ниже не загружает учетные данные в CLI и не подключается к сервисам:

```bash
CONTAINER=mistral_executor
CONF_FILE=/etc/mistral/mistral.conf
sudo podman exec "$CONTAINER" python -c 'import configparser,sys; c=configparser.ConfigParser(interpolation=None); c.read(sys.argv[1]); ks=("enabled","host_lock_timeout","power_timeout","poll_interval","stable_observations","vm_action_timeout","service_timeout"); print({k:c.get("powerops",k,fallback="<not set>") for k in ks})' "$CONF_FILE"
```

Ожидается самостоятельная `[powerops]`, `enabled=true`, параметры согласованы с
принятой конфигурацией. `<not set>` означает отсутствие явного значения в этом
файле, а не обязательно effective false: нужно учитывать default установленного
пакета и другие `--config-file`/`--config-dir`. Проверка файла не читает память
уже работающего процесса и не доказывает, что процесс перечитал изменения.

Для Masakari:

```bash
CONTAINER=masakari_engine
CONF_FILE=/etc/masakari/masakari.conf
sudo podman exec "$CONTAINER" python -c 'import configparser,sys; c=configparser.ConfigParser(interpolation=None); c.read(sys.argv[1]); ks=("enabled","power_timeout","nova_down_timeout","poll_interval","stable_off_observations","evacuation_interval"); print({k:c.get("powerops",k,fallback="<not set>") for k in ks})' "$CONF_FILE"
sudo podman exec masakari_engine python -c 'from masakari import conf; print("package default nova_down_timeout:", conf.CONF.powerops.nova_down_timeout)'
```

Последняя команда читает default установленного пакета в отдельном процессе.
Для `aabc8c0` ожидается `180`; отсутствие опции означает несовместимость с этой
базовой линией. Наличие одной опции еще не доказывает весь commit.

Проверка порядка задач recovery без полного config dump:

```bash
sudo podman exec masakari_engine python -c 'import configparser; c=configparser.ConfigParser(interpolation=None); c.read("/etc/masakari/masakari.conf"); s="taskflow_driver_recovery_flows"; ks=("host_auto_failure_recovery_tasks","host_rh_failure_recovery_tasks"); print({k:c.get(s,k,fallback="<not set>") for k in ks})'
```

Ожидается `disable_compute_service_task` перед `ironic_fence`, а эвакуация после
fencing. Для сверки coordination не выводите целиком URL с credentials/query.
Следующая команда печатает только scheme/host/port и имена query-параметров:

```bash
CONTAINER=mistral_executor
CONF_FILE=/etc/mistral/mistral.conf
sudo podman exec "$CONTAINER" python -c 'import configparser,sys,urllib.parse as u; c=configparser.ConfigParser(interpolation=None); c.read(sys.argv[1]); p=u.urlsplit(c.get("coordination","backend_url",fallback="")); print({"scheme":p.scheme,"host":p.hostname,"port":p.port,"query_keys":sorted(u.parse_qs(p.query))})' "$CONF_FILE"
```

Повторите для `masakari_engine`/его пути конфига. Для PowerOps ожидается
согласованный etcd3 HTTP(S) backend; его доступность и владение locks проверяются
по результатам операций и журналам, а не этой строкой. Mistral также имеет
`[powerops] coordination_url`; при проверке повторите команду, заменив пару
`"coordination","backend_url"` на `"powerops","coordination_url"`.

При ошибке bootstrap/импорта не запускайте заново bootstrap и не вызывайте
`db sync`. В Kolla это временный oneshot-контейнер; отсутствие `bootstrap_masakari`
или `bootstrap_mistral` после завершения/очистки само по себе не является ошибкой.
Используйте сохраненный вывод deployment, журналы в `/var/log/kolla`, состояние
постоянных контейнеров и метаданные образа.

```bash
read -r -p 'Image ID или точный image reference из podman ps: ' IMAGE
sudo podman image inspect --format 'id={{.Id}} digests={{json .RepoDigests}} created={{.Created}}' "$IMAGE"
```

Эта команда не запускает контейнер, не тянет образ и не выводит полный inspect.
Если контейнер не стартует из-за Python import/entry point, image metadata
устанавливает только идентичность образа. Проверка файлов/пакетов образа и
совместимости launcher нужна отдельно; здоровый tag или существующий endpoint
не доказывают исправление bootstrap.

### SDK response cache и зависимости в работающем контейнере

Следующие команды создают **отдельный диагностический Python-процесс** с тем же
основным config file. Они не выполняют power/migration/evacuation, не выводят
токен и не заменяют чтение памяти уже работающего процесса. Если service launcher
использует дополнительные файлы конфигурации, их надо учесть отдельно.
Каждая Python-команда дана одной строкой: это не интерактивная REPL и повторного
`parse_args` в одном интерпретаторе не происходит.

```bash
sudo podman exec mistral_executor python -B -c 'from mistral import config; from mistral.actions.powerops import clients; config.parse_args(args=[], default_config_files=["/etc/mistral/mistral.conf"]); c=clients.connection_from_conf(); print("SDK response cache enabled:", c.cache_enabled)'
sudo podman exec masakari_engine python -B -c 'from masakari import conf; from masakari.powerops import ironic; conf.CONF(args=[], project="masakari", default_config_files=["/etc/masakari/masakari.conf"]); c=ironic.connection_from_conf(); print("Ironic SDK response cache enabled:", c.cache_enabled)'
```

Для плановой live migration требуется `False`. `True` в Mistral объясняет отказ
guard; ошибка импорта или конфигурации означает, что значение не получено.
Команда Masakari проверяет Ironic SDK-клиент, а не новый Nova-down read через
python-novaclient. Отключение memcached Keystone или смена количества stable
observations не отключают этот response cache.

При проблеме импорта, включая ранее наблюдавшийся `No module named pkg_resources`,
в работающем соответствующем контейнере:

```bash
CONTAINER=mistral_executor
sudo podman exec "$CONTAINER" python -B -m pip show setuptools mistral-lib openstacksdk tooz etcd3gw python-novaclient
sudo podman exec "$CONTAINER" python -B -m pip check
sudo podman exec "$CONTAINER" python -B -c 'import pkg_resources; print("pkg_resources:", pkg_resources.__file__)'
sudo podman exec mistral_executor python -B -c 'from mistral_lib.actions import context; print("mistral_lib.actions.context import OK")'
sudo podman exec masakari_engine python -B -c 'import masakari.engine.drivers; print("masakari.engine.drivers import OK")'
```

`pip check` проверяет объявленные зависимости, но не все импорты приложения.
Сверяйте и версию, и `Location`: системные RPM и venv могут давать разные части
dependency tree. Здесь нет `pip install/upgrade`; совместимость исправляется
согласованной сборкой образа. Если контейнер не работает, `podman exec` неприменим:
это ограничение диагностики, а не причина запускать bootstrap заново.

### Роли: caller и service accounts проверяются отдельно

На операторском узле, не в контейнере, запросите назначения известного UUID
пользователя Keystone. Повторите отдельно для оператора, Mistral, Masakari и
Nova privileged account, фактически настроенных в конфигурации:

```bash
read -r -p 'Keystone user UUID для проверки назначений: ' AUTH_USER
timeout 30s openstack role assignment list --user "$AUTH_USER" --effective --names -f json
```

Результат показывает назначения с project/domain/system scope, но не содержимое
ранее выданного токена сервиса. Успех API из admin-shell не доказывает service-role
доступ Masakari к Ironic. По `req-...` в Ironic API log определяют фактический user,
project и запрещённое policy action. Маппинг разных service credentials приведён
в разделе 8 [справочника конфигурации](POWEROPS-CONFIGURATION.md).

### Ручное чтение журналов без сборщика

На доступном контроллере по его проверенному IP сначала найдите реальные файлы:

```bash
sudo ls -l /var/log/kolla/masakari /var/log/kolla/mistral /var/log/kolla/ironic /var/log/kolla/nova
read -r -p 'Полный путь к нужному файлу /var/log/kolla/...: ' LOG_FILE
read -r -p 'Notification/action/server UUID либо req-ID: ' CORRELATION
sudo timeout 30s grep -n -F -C 12 -- "$CORRELATION" "$LOG_FILE"
sudo tail -n 200 -- "$LOG_FILE"
```

Пропущенный каталог/ротированный файл фиксируйте явно. Не ищите только на одной
реплике: запрос API, executor и conductor могут обрабатываться на разных узлах.
Точные названия файлов зависят от logging config; типичные точки поиска:

| Переход | Журнал/процесс |
|---|---|
| Consul → notification | masakari-hostmonitor; Consul нужной сети |
| Приём/reject уведомления | masakari API/WSGI |
| Fencing → Nova down → evacuation/VMove | `masakari-engine.log` |
| Bootstrap Masakari | `masakari-manage.log` и сохранённый вывод Ansible |
| Workflow/task/action | Mistral API, `mistral-engine.log`, `mistral-executor.log` |
| Power request → BMC | Ironic API/WSGI и conductor |
| Запрос migration/evacuation → выбор destination | Nova API, scheduler, conductor; доступные журналы compute |

Это сырые журналы, без маскирования сборщиком. Просматривайте их приватно и
очищайте секреты перед передачей. Если service пишет только в stdout, можно
прочитать ограниченный контейнерный журнал. Задайте `SINCE`/`UNTIL` также в этой
сессии контроллера:

```bash
read -r -p 'Начало UTC: ' SINCE
read -r -p 'Конец UTC: ' UNTIL
CONTAINER=masakari_engine
sudo podman logs --since "$SINCE" --until "$UNTIL" --tail 200 "$CONTAINER"
sudo journalctl -k --since "$SINCE" --until "$UNTIL" --no-pager -n 200
```

Пустой stdout log не означает отсутствие прикладного лога в `/var/log/kolla`.
Kernel log помогает искать OOM/I/O/container-runtime причины, но не заменяет
Masakari/Mistral traceback.

## 11. Как сформулировать результат диагностики

Фиксируйте один проверяемый переход, а не общее "PowerOps не работает":

| Доказанный факт | Что еще не следует из него |
|---|---|
| Consul отметил failed в нужной сети | Физический power off или создание notification |
| Masakari принял точный notification | Успех fencing/evacuation |
| Ironic показал `power off` одним чтением | Stable-off и сохранение ownership на всем интервале |
| Новый Masakari подтвердил Nova `disabled/down` | Завершение переноса каждой ВМ |
| Nova показывает VM на другом host | Отсутствие stale libvirt domain на исходном узле |
| Mistral execution `SUCCESS` | Полная приемка инфраструктуры без проверки результата и API |
| CLI parser и shell syntax проходят локально | Доступность API, права, версии и работа этих команд на стенде |

Для передачи достаточно: UTC-интервал, HOST, segment/host/notification UUID,
execution/task/action UUID для плановой ветки, затронутые server UUID, последний
подтвержденный шаг и первая ошибка, container image IDs, статусы API-снимков и
приватный очищенный TXT. Не включайте токены, passwords.yml, driver_info и полный
конфиг.

В отчет о проверке явно заносите пропущенные источники: недоступный compute,
policy-hidden поле, отсутствующий plugin, несовместимую microversion, timeout,
усечение/ротацию журналов, другой image на реплике. Эти ограничения не надо
превращать в доказательство исправности или отсутствия события.

## 12. Источники и граница проверки документа

Порядок операций и диагностические состояния сверены с
`masakari/engine/drivers/taskflow/powerops.py`, `masakari/conf/powerops.py`,
`masakari/ha/api.py`, Mistral `mistral/actions/powerops/`,
`etc/mistral/power_ops.yaml`, Kolla `ansible/roles/masakari/`,
`ansible/roles/mistral/`, `ansible/roles/consul/` указанной базовой линии.
Локальные источники состава сборщика: `tools/diagnostics/README.md`,
`tools/diagnostics/files/collect.py`,
`tools/diagnostics/tests/test_real_cli.py`. Они не входят в эту публикацию из
трёх документов. Для запуска используется ранее опубликованный самостоятельный
[collect-v2.yml](../tools/diagnostics/collect-v2.yml), уже присутствующий в `main`.

Команды документа предназначены для ручного выполнения оператором. Локальная
проверка синтаксиса и регистрации команд не обращается к стенду и не подтверждает
его текущее состояние. Этот документ не является разрешением продолжить
застрявшую операцию или обойти ручную паузу возврата.

При подготовке проверены 43 Bash-блока и синтаксис 12 встроенных Python-команд.
19 API-команд проверены настоящими parsers `python-openstackclient 7.5.0`,
`python-masakariclient 8.9.0`, `python-ironicclient 6.3.0` при запрещенных сетевых
соединениях. 14 команд Mistral сверены с имеющимся сборщиком и официальным
исходником клиента 2025.1; в доступном проверочном окружении plugin Mistral
отсутствует, поэтому его runtime/parser-проверка здесь не заявляется.
