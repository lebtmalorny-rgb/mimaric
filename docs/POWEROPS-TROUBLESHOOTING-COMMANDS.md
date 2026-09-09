# PowerOps: ручные команды по разобранным проблемам

Сверка: 9 сентября 2026 года. Это практический справочник **по симптомам**,
собранный из разборов Mistral, Masakari, Ironic, Nova и Kolla/Podman.
Общая последовательность расследования остаётся в
[POWEROPS-DIAGNOSTICS.md](POWEROPS-DIAGNOSTICS.md).

Основа — архивы `0809` и отдельно добавленное ожидание Nova down после fencing
в Masakari. Старые скриншоты используются как примеры наблюдений, а не как
снимок текущего состояния. `planned-return-v2` не включён.

## 1. Правила запуска и переменные инцидента

- Команды ниже — для Linux/Bash, не для Python REPL и не для macOS shell.
  Копируйте одну команду целиком. Длинные Python-команды специально записаны
  одной физической строкой: перенос после `-c` ломает команду.
- OpenStack CLI запускайте на операторском узле с уже настроенной авторизацией
  (на стенде — `ultra1-0`). `podman`, `journalctl`, `ss` — локально на доступном
  контроллере нужного сервиса. Проверка не требует SSH на аварийный compute.
- Здесь нет `power off/on`, `evacuate`, `migrate`, `resume`, `db sync`,
  назначения ролей, удаления контейнеров и перезапуска сервисов.
- Исключение по локальным действиям: раздел 6 создаёт временный изолированный
  контейнер **только для проверки импортов**, раздел 7 — локальный файл журнала.
  Рабочие контейнеры, конфиги и база не изменяются.
- Не используйте `--debug`, `set -x`, полный `podman inspect`, вывод env,
  `clouds.yaml`, `passwords.yml` или полного service config в общий отчёт.
  Сырые логи/traceback и результаты executions могут содержать секреты.
- Timeout чтения безопасно повторить. Timeout **изменяющего** запроса не означает,
  что операция не была принята: сначала найдите её UUID и состояние.

На операторе задайте параметры нового инцидента, без привязки к старым датам:

```bash
set +x
umask 077
date -u '+%Y-%m-%dT%H:%M:%SZ'
read -r -p 'Исходный compute FQDN: ' HOST
read -r -p 'Начало окна UTC, YYYY-MM-DDTHH:MM:SSZ: ' SINCE
read -r -p 'Конец окна UTC, YYYY-MM-DDTHH:MM:SSZ: ' UNTIL
```

Например, `HOST=ultra1-2.ultra1.test.pvs.un.sbt`; для другого теста укажите другой
хост. UUID execution, notification, VM, segment и Ironic node — разные сущности.
Не подставляйте UUID одной сущности в команду для другой.

## 2. Mistral: 504, долгие ответы, execution list «не обновляется»

### Сначала сравнить чтение разных ресурсов

На операторе:

```bash
timeout 30s openstack action definition show std.noop -f json
timeout 30s openstack action definition show powerops.host_power_status -f json
timeout 30s openstack workbook list -f json
timeout 30s openstack workflow list -f json
timeout 30s openstack workflow execution list --sort_keys created_at --sort_dirs desc --limit 50 -f json
```

`std.noop` здесь **читается как definition**, не запускается. Отдельный успешный
GET не доказывает исправность всех API workers, engine, executor, RPC или DB.

### Сравнить VIP и конкретные API backends

В старой диагностике стенда использовались следующие адреса. Это **пример
инвентаризации того стенда**, не discovery и не универсальные defaults:

| Назначение | Адрес |
| --- | --- |
| Mistral VIP | `10.101.25.42:8989` |
| API backend на ultra1-6 | `10.101.25.150:8989` |
| API backend на ultra1-7 | `10.101.25.151:8989` |
| API backend на ultra1-8 | `10.101.25.152:8989` |

Для каждого **проверенного** URL выполните один блок. URL задаётся с `/v2` без
завершающего `/`. Используйте реальную схему/CA; не заменяйте HTTPS на HTTP и не
добавляйте `-k`. Пример из старого стенда — `http://10.101.25.42:8989/v2`.

```bash
read -r -p 'Mistral API URL с /v2: ' POWEROPS_API
(
set +x
powerops_diag_token=$(timeout 20s openstack token issue -f value -c id) || exit 1
[ -n "$powerops_diag_token" ] || exit 1
for resource in 'actions/std.noop' 'workbooks?limit=1' 'actions/powerops.host_power_status'
do
printf '\n%s\n' "$resource"
printf 'X-Auth-Token: %s\n' "$powerops_diag_token" | curl -q -sS --connect-timeout 5 --max-time 20 -H @- -o /dev/null -w 'HTTP=%{http_code} connect=%{time_connect} start=%{time_starttransfer} total=%{time_total}\n' "$POWEROPS_API/$resource"
done
)
```

Токен передаётся через stdin curl, не печатается и не помещается в аргументы
процесса. Подоболочка ограничивает срок жизни shell-переменной. `-q` отключает
автоподхват `.curlrc`; proxy environment остаётся действующим. Если прямой backend
должен обходить proxy, сначала проверьте утверждённые proxy/NO_PROXY настройки.
Не делайте вывод о backend, если запрос фактически ушёл через иной proxy.

Интерпретация:

| Результат | Что установлено / следующий шаг |
| --- | --- |
| `HTTP=000`, curl timeout | HTTP-ответ не получен; это не `403` Keystone |
| `504` | Gateway не дождался upstream; причину надо искать дальше |
| Только один backend зависает | Проверить его API process, image/config, DB/auth и логи; VIP может чередовать исправную и проблемную реплики |
| `std.noop` и workbook читаются, PowerOps definition `404` | Проверить регистрацию action и версию кода; не запускать populate/db sync автоматически |
| `401/403` | Проверить auth/scope/policy по Request-ID и фактическому пользователю |
| Везде быстрые ответы, execution не меняется | Читать точный execution/task/action; искать очередь/RPC/executor, а не считать API виновным |

Ранее `.150` и `.152` отвечали на часть GET, а `.151` не отвечал за 20 секунд.
Это было основанием разделить расследование по backend, но не доказательством
текущей неисправности `.151` или единственной причины всех ошибок.

## 3. Как получить настоящую ошибку workflow, а не короткий ERROR

На операторе, по **полному** UUID execution:

```bash
read -r -p 'Workflow execution UUID: ' EXEC
timeout 30s openstack workflow execution show "$EXEC" -f json
timeout 30s openstack workflow execution input show "$EXEC"
timeout 30s openstack workflow execution output show "$EXEC"
timeout 30s openstack task execution list "$EXEC" --limit 50 -f json
read -r -p 'Task execution UUID: ' TASK
timeout 30s openstack task execution show "$TASK" -f json
timeout 30s openstack task execution result show "$TASK"
timeout 30s openstack action execution list "$TASK" --limit 50 -f json
read -r -p 'Action execution UUID: ' ACTION
timeout 30s openstack action execution show "$ACTION" -f json
timeout 30s openstack action execution output show "$ACTION"
```

`TASK` и `ACTION` вводите из полученных списков, а не из UUID workflow definition.
Если execution `RUNNING`, пустой output `{}` ещё не является финальным результатом.
При `WorkflowExecution not found` сначала исключите обрезанный UUID, другой
проект/namespace и другой endpoint. В одном из прошлых случаев при копировании
UUID потерялся последний символ.

Нужны первая ошибка action, `action_ex_id`, `task_ex_id`, `req-...` и реплика
executor. `Failure caused by error in tasks` описывает следствие. Журнал
`mistral-executor.log` обычно даёт точный клиентский вызов/исключение; команда
для чтения scoped журнала приведена в разделе 7.

## 4. Masakari segment GET вернул 404 внутри Mistral

Прошлый traceback доходил до `CloudClients.masakari_host()` и
`ha_adapter.get(segment_url)`. Значит, PowerOps action уже исполнялся; это не
тот же случай, что `404` чтения action definition в Mistral API.

На операторе сравните UUID из **входа упавшего execution**, а не из нового запуска:

```bash
timeout 30s openstack workflow execution input show "$EXEC"
timeout 30s openstack segment list -f json
read -r -p 'Segment UUID из входа execution: ' SEGMENT
timeout 30s openstack segment show "$SEGMENT" -f json
timeout 30s openstack segment host list "$SEGMENT" -f json
```

Чтобы проверить тот же сервисный клиент, на контроллере с `mistral_executor`
введите `SEGMENT` заново и выполните **отдельный** Python-процесс:

```bash
read -r -p 'Segment UUID для проверки сервисным клиентом: ' SEGMENT
timeout 30s sudo -n podman exec mistral_executor python -B -u -c 'import sys,uuid; from mistral import config; from mistral.actions.powerops import clients; segment=str(uuid.UUID(sys.argv[1])); config.parse_args(args=[],default_config_files=["/etc/mistral/mistral.conf"]); c=clients.connection_from_conf(); c.session.timeout=15; cloud=clients.CloudClients(c); r=cloud.ha_adapter.get("/segments/"+segment,raise_exc=False,timeout=15); print("URL:",r.url); print("HTTP:",r.status_code); print("Request-ID:",r.headers.get("X-Openstack-Request-ID"))' "$SEGMENT"
```

Тело ответа и токен намеренно не выводятся. URL остаётся служебной информацией.
Сравните URL/region/interface, точный segment UUID и Request-ID с API log.
Свежий `200` доказывает доступность этого чтения **сейчас**, но не объясняет
старый `404` без сравнения старого входа, endpoint и логов.

Не повторяйте `config.parse_args()` в уже использованной Python REPL:
`ArgsAlreadyParsedError` — ошибка диагностической сессии, не новая ошибка
workflow. Однострочная команда выше каждый раз создаёт свежий интерпретатор.

## 5. Ironic 403: оператор может читать nodes, Masakari — нет

По `req-...` найдите в Ironic API log фактические `user_name`, `project_name`,
scope и запрещённое policy action. В нашем разборе это были `masakari`, project
`service` и `baremetal:node:list_all`; у сервисного токена не хватало роли
`service`. Не подменяйте эту проверку успехом команды из admin-shell.

На операторе:

```bash
read -r -p 'Keystone user UUID из API log: ' AUTH_USER
timeout 30s openstack role assignment list --user "$AUTH_USER" --effective --names -f json
```

На контроллере с `masakari_engine` — свежий токен и **только чтение** Ironic:

```bash
read -r -p 'Compute FQDN для чтения Ironic: ' HOST
timeout 35s sudo -n podman exec masakari_engine python -B -u -c 'import sys; from masakari import conf; from masakari.powerops import ironic; conf.CONF(args=[],project="masakari",default_config_files=["/etc/masakari/masakari.conf"]); c=ironic.connection_from_conf(); c.session.timeout=15; a=c.session.auth.get_access(c.session); print("AUTH:",a.username,a.project_name,sorted(a.role_names)); nodes=[n for n in c.baremetal.nodes(details=True) if n.name==sys.argv[1]]; print("MATCHES:",len(nodes)); print([(n.id,n.name,n.power_state,n.provision_state,n.network_interface,bool(n.last_error)) for n in nodes])' "$HOST"
```

Ожидайте ровно один узел нужного имени. Эта команда не печатает `driver_info`
с BMC credentials, не изменяет питание и не доказывает write-permissions.
Переиспользуемый токен работающего процесса может отличаться от свежего.

Mistral PowerOps имеет собственный сервисный профиль. Его проверка:

```bash
timeout 30s sudo -n podman exec mistral_executor python -B -u -c 'from mistral import config; from mistral.actions.powerops import clients; config.parse_args(args=[],default_config_files=["/etc/mistral/mistral.conf"]); c=clients.connection_from_conf(); c.session.timeout=15; a=c.session.auth.get_access(c.session); print("AUTH:",a.username,a.project_name,sorted(a.role_names))'
```

Вызовы Masakari → Nova используют ещё один профиль: в шаблоне это privileged
Nova user, не Ironic-клиент Masakari. Нужные конфиги и источник исправления роли
даны в [POWEROPS-AUTHENTICATION.md](POWEROPS-AUTHENTICATION.md).
Команд выдачи ролей в диагностическом блоке нет.

## 6. Bootstrap: нет контейнера или `No module named pkg_resources`

`bootstrap_mistral`/`bootstrap_masakari` — временные контейнеры. После их
завершения/очистки `podman exec` может вернуть `no such container`.
Сначала используйте вывод deployment, постоянные service logs и локальный образ.
Не повторяйте `db sync` как тест Python-зависимостей.

На узле неудачного bootstrap:

```bash
sudo -n podman ps -a --format '{{.Names}} {{.Image}} {{.Status}}'
sudo -n podman images --no-trunc --filter 'reference=*mistral*'
sudo -n podman images --no-trunc --filter 'reference=*masakari*'
read -r -p 'Точный локальный image ID/reference проблемной сборки: ' POWEROPS_IMAGE
sudo -n podman image inspect --format 'id={{.Id}} digests={{json .RepoDigests}} created={{.Created}}' "$POWEROPS_IMAGE"
```

Следующие команды создают и удаляют только временный диагностический контейнер:
сеть выключена, rootfs read-only, image pull запрещён, entrypoint bootstrap
переопределён на Python. Не добавляйте `--privileged`, host volumes или сетевой доступ.

Для образа Mistral:

```bash
timeout 30s sudo -n podman run --rm --pull=never --network=none --read-only --entrypoint=/var/lib/kolla/venv/bin/python "$POWEROPS_IMAGE" -B -m pip show setuptools mistral-lib
timeout 30s sudo -n podman run --rm --pull=never --network=none --read-only --entrypoint=/var/lib/kolla/venv/bin/python "$POWEROPS_IMAGE" -B -m pip check
timeout 30s sudo -n podman run --rm --pull=never --network=none --read-only --entrypoint=/var/lib/kolla/venv/bin/python "$POWEROPS_IMAGE" -B -u -c 'import importlib.util as u; print("pkg_resources:",u.find_spec("pkg_resources")); from mistral_lib.actions import context; print("MISTRAL LIB IMPORT OK")'
```

Для образа Masakari **сначала выберите его image**, не оставляйте Mistral image:

```bash
read -r -p 'Точный локальный Masakari image ID/reference: ' POWEROPS_IMAGE
timeout 30s sudo -n podman run --rm --pull=never --network=none --read-only --entrypoint=/var/lib/kolla/venv/bin/python "$POWEROPS_IMAGE" -B -m pip show setuptools masakari
timeout 30s sudo -n podman run --rm --pull=never --network=none --read-only --entrypoint=/var/lib/kolla/venv/bin/python "$POWEROPS_IMAGE" -B -u -c 'import importlib.util as u; print("pkg_resources:",u.find_spec("pkg_resources")); import masakari.engine.drivers; print("MASAKARI DRIVERS IMPORT OK")'
```

Для сравнения с прежней рабочей сборкой повторите команды с её точным локальным
image ID. Если Python в конкретном образе расположен иначе, используйте
подтверждённый путь launcher; не меняйте system Python наугад.

В показанном инциденте Mistral image содержал `setuptools 83.0.0` в venv и
`mistral-lib 3.3.1` в system site-packages; импорт `pkg_resources` падал.
Masakari также падал на namespace import через `pkg_resources`.
После возврата пользователем setuptools к ветке 80 bootstrap прошёл.
Это историческая проверенная связка, а не универсальный совет ставить любую
80.x и не доказательство, что зависимость принёс именно PowerOps patch.

При исправлении образа сравнивают рецепт сборки, constraints и финальную версию
пакетов после всех pip/RPM шагов. `pip check` не заменяет import smoke test:
необъявленный runtime import может ломаться при формально совместимых зависимостях.
В работающие контейнеры пакеты вручную не устанавливаются.

## 7. Podman: `given PID did not die`, `died without exit code`, пустой log

На доступном контроллере выберите реальное имя контейнера:

```bash
read -r -p 'Контейнер с ошибкой restart: ' CONTAINER
sudo -n podman ps -a --format '{{.Names}} {{.Image}} {{.Status}}'
sudo -n podman inspect --format 'image={{.Image}} status={{.State.Status}} running={{.State.Running}} pid={{.State.Pid}} exit={{.State.ExitCode}} oom={{.State.OOMKilled}} started={{.State.StartedAt}} finished={{.State.FinishedAt}}' "$CONTAINER"
read -r -p 'Начало окна UTC: ' SINCE
read -r -p 'Конец окна UTC: ' UNTIL
timeout 25s sudo -n podman logs --timestamps --since "$SINCE" --until "$UNTIL" --tail 300 "$CONTAINER"
sudo -n journalctl -u podman.service --since "$SINCE" --until "$UNTIL" --no-pager -n 300
sudo -n journalctl -k --since "$SINCE" --until "$UNTIL" --no-pager -n 300
```

Проверяйте OOM, I/O errors, blocked tasks и время переходов. Отсутствие stdout
не доказывает отсутствие ошибки: OpenStack-сервис может писать в `/var/log/kolla`.
`died without exit code` — сообщение runtime, не диагноз ошибки приложения.
После timeout остановки не выполняйте автоматически `rm -f`, `kill -9`, restart
или reboot: сначала установите причину и сохраните данные.

В отдельной shell-переменной можно исследовать только полученный числовой PID:

```bash
POWEROPS_PID=$(sudo -n podman inspect --format '{{.State.Pid}}' "$CONTAINER")
if [[ "$POWEROPS_PID" =~ ^[1-9][0-9]*$ ]]; then ps -p "$POWEROPS_PID" -o pid,ppid,stat,etime,wchan,comm; fi
```

Не выводится полная command line, которая иногда содержит credentials.
PID может завершиться/быть переиспользован между чтениями: сопоставляйте время
и container state, не посылайте сигнал только по сохранённому номеру.

### Корреляция с OpenStack service log

Локально на контроллере, пример для Mistral executor:

```bash
read -r -p 'UUID action/execution или req-...: ' CORRELATION
umask 077
POWEROPS_RAWLOG=$(mktemp /tmp/powerops-log.XXXXXX)
sudo -n grep -F -C 12 -- "$CORRELATION" /var/log/kolla/mistral/mistral-executor.log > "$POWEROPS_RAWLOG"
printf 'Локальный сырой фрагмент: %s\n' "$POWEROPS_RAWLOG"
```

Другие обычные источники: `/var/log/kolla/masakari/masakari-engine.log`,
`masakari-hostmonitor.log`, `masakari-manage.log`,
`/var/log/kolla/ironic/ironic-api-wsgi.log` и журналы conductor.
Имена зависят от образа/logging; сначала найдите реальный файл. Ограничение:
пример не читает rotated/compressed logs. Сырой фрагмент остаётся локальным
файлом с правами от `umask 077`; перед передачей очистите секреты или используйте
редактирующий чувствительные поля диагностический сборщик.

Если Kolla после ошибки одного узла сообщает
`PowerOps verification must not accept a partial deploy`, это защитная итоговая
проверка. Исправлять надо первую ошибку узла, а не отключать этот assert.

## 8. Плановая миграция: workflow ERROR, а ВМ уже на другом хосте

При прежнем `instance entered an unsafe migration state` ВМ затем оказалась
`ACTIVE` на destination с `task_state=null`, исходный хост оставался включённым.
Это не противоречие: action мог остановиться на промежуточном состоянии, а Nova
позже завершила перенос. Поздний успех Nova не делает упавший workflow SUCCESS.

На операторе, с параметрами инцидента из раздела 1:

```bash
read -r -p 'Workflow execution UUID: ' EXEC
timeout 30s openstack workflow execution input show "$EXEC"
timeout 30s openstack workflow execution output show "$EXEC"
timeout 30s openstack compute service list --host "$HOST" --service nova-compute -f json
timeout 30s openstack server list --all-projects --host "$HOST" -c ID -c Name -c Status -f json
read -r -p 'UUID перенесённой ВМ: ' SERVER
timeout 30s openstack server show "$SERVER" -f yaml -c status -c OS-EXT-SRV-ATTR:host -c OS-EXT-STS:task_state
timeout 30s openstack server migration list --server "$SERVER" -f json
timeout 30s openstack server event list "$SERVER" -f json
timeout 30s openstack --os-compute-api-version 2.66 server migration list --host "$HOST" --changes-since "$SINCE" --changes-before "$UNTIL" --limit 100 -f json
timeout 30s openstack baremetal node show "$HOST" -f yaml -c uuid -c name -c power_state -c target_power_state -c last_error
```

Убедитесь, что поля host/task_state действительно присутствуют; отсутствие поля
по policy — не подтверждённый `null`. История по host нужна и для ВМ, которых уже
нет на source. `403` или неподдерживаемая microversion — недоступность данных,
не отсутствие миграций. `baremetal node show "$HOST"` применим, когда имя Ironic
node точно совпадает с FQDN; иначе используйте проверенный UUID node.

До повторного запуска выясните: был ли power request, какие ВМ успели уйти,
есть ли активные/ошибочные migration records, что осталось в maintenance/disabled.
Не удаляйте историю и не запускайте вторую миграцию «для завершения» первой.
`stopped_instance_ids=[]` при последующем return не возвращает мигрировавшие ВМ.

### Проверка response cache того клиента, который использует PowerOps

На контроллере:

```bash
sudo -n podman exec mistral_executor python -B -c 'from mistral import config; from mistral.actions.powerops import clients; config.parse_args(args=[],default_config_files=["/etc/mistral/mistral.conf"]); c=clients.connection_from_conf(); print("SDK response cache:",c.cache_enabled)'
sudo -n podman exec masakari_engine python -B -c 'from masakari import conf; from masakari.powerops import ironic; conf.CONF(args=[],project="masakari",default_config_files=["/etc/masakari/masakari.conf"]); c=ironic.connection_from_conf(); print("Ironic SDK response cache:",c.cache_enabled)'
```

Для planned live migration нужен `False`. Это не Keystone token cache и не
memcached. Проба создаёт отдельное соединение по основному config file и не
читает память старого процесса; дополнительные launcher config files надо
учесть отдельно. Masakari-проба проверяет Ironic SDK, не Nova novaclient.

## 9. Аварийный тест: нет эвакуации, compute down или выключены два хоста

Начинайте с нового notification нужного host, а не первого старого `error` в списке:

```bash
read -r -p 'Segment UUID: ' SEGMENT
timeout 30s openstack segment host list "$SEGMENT" -f json
read -r -p 'Masakari host UUID исходного compute: ' HA_HOST
timeout 30s openstack segment host show "$SEGMENT" "$HA_HOST" -f json
timeout 30s openstack notification list --filters "source_host_uuid=$HA_HOST" --sort created_at:desc --limit 20 -f json
read -r -p 'Notification UUID именно этого теста: ' NOTIF
timeout 30s openstack notification show "$NOTIF" -f json
timeout 30s openstack notification vmove list "$NOTIF" --limit 50 -f json
timeout 30s openstack compute service list --host "$HOST" --service nova-compute -f json
timeout 30s openstack baremetal node show "$HOST" -f yaml -c power_state -c target_power_state -c last_error
timeout 30s openstack server list --all-projects --host "$HOST" -c ID -c Name -c Status -f json
```

Сравнивайте `source_host_uuid`, generated/created times, статус, VMove и состояние
каждой ВМ по UUID. Последний список ВМ на исходном хосте недостаточен: после
успешного переноса он пуст. При `SHUTOFF` на destination проверяйте состояние до
аварии и результат VMove: это не универсальный признак неуспеха.

| Симптом | Что проверять |
| --- | --- |
| LAN отключили, нового notification нет | Consul endpoints/матрицу/samples, hostmonitor logs, правильное имя, API rejection/maintenance |
| До теста ВМ не было | Эвакуировать нечего; отдельно оценить detection, notification и fencing |
| `on_maintenance=true` | Было ли это до события? Возможен отказ приёма нового уведомления; текущее значение не восстанавливает историю |
| После возврата LAN Nova всё ещё down | Ironic power state: выключенный BMC хост от кабеля не включается |
| Nova `disabled/up` после off | Различайте административный status и heartbeat state; проверяйте время обновления |
| Аварийный fencing подтверждён, эвакуация ещё не началась | Новый патч Masakari ждёт Nova down; читайте engine log и `nova_down_timeout` |
| Выключены два compute | Отдельные host/notification/execution UUID и временные линии для каждого; один список `power off` не объясняет причину второго выключения |

При расследовании двух хостов повторите команды для каждого, включая поиск
плановых Mistral executions. Проверьте Ironic conductor logs: существует также
периодическая синхронизация питания Ironic. Не приписывайте ей конкретное
выключение без соответствующей записи. Сам Consul не вызывает BMC.

Для чистого следующего прогона заранее зафиксируйте power, Nova status/state,
Masakari maintenance, размещение/состояния ВМ, текущую матрицу и UTC. Подготовка
исходного состояния и имитация аварии — отдельные согласованные операции,
не часть диагностических команд. Подробнее —
[Consul и матрица](POWEROPS-CONSUL.md),
[Ironic и его допущения](POWEROPS-IRONIC-ENROLLMENT.md).

## 10. `power_on_and_return` остановился на PAUSED

На операторе, используя UUID уже созданного execution:

```bash
read -r -p 'UUID power_on_and_return execution: ' EXEC
timeout 30s openstack workflow execution show "$EXEC" -f json
timeout 30s openstack workflow execution input show "$EXEC"
timeout 30s openstack task execution list "$EXEC" --limit 50 -f json
timeout 30s openstack baremetal node show "$HOST" -f yaml -c power_state -c target_power_state -c last_error
timeout 30s openstack compute service list --host "$HOST" --service nova-compute -f json
timeout 30s openstack segment host list "$SEGMENT" -f json
```

Если `power_on_for_inspection=SUCCESS`, `operator_inspection_gate=IDLE`,
`return_to_service` ещё не выполнялся, это ожидаемая ручная пауза `0809`.
Хост должен сохранять Nova disabled и Masakari maintenance до допуска оператора.
Пустой `stopped_instance_ids` паузу не отменяет.

API-состояние `power on`, Nova up и пустой список ВМ не доказывают отсутствие
stale domains на исходном гипервизоре. Флаг `stale_domains_checked=true` нельзя
выставлять автоматически по этому диагностическому выводу. После реального
выполнения согласованной проверки используйте отдельную изменяющую процедуру
[продолжения существующего execution](POWEROPS-OVERVIEW.md#62-после-проверки-разрешить-возврат-и-проверить-результат).
Повторный `execution create` вместо resume не является продолжением старой операции.

## 11. Ошибки CLI, вставки текста и SSH сборщика

| Ошибка | Причина/проверка |
| --- | --- |
| curl пытается разрешить `xn--connect-timeout...` или host `5` | Типографское тире вместо `--`, «умные» кавычки; запрос к API мог вообще не уйти |
| `IndentationError: unexpected indent` | Лишние пробелы в Python REPL/heredoc; используйте целую однострочную `python -c '...'` |
| `Argument expected for the -c option` | Перенос строки между `-c` и Python-текстом |
| Python `can't open file '//registry/...:tag'` | Image reference продублирован после первого image и стал аргументом Python |
| `ArgsAlreadyParsedError` | Повторный parse в старой REPL; нужен новый процесс |
| YAML `mapping values are not allowed`, line 2 | Повреждённое начало/отступы плейбука, например потерянное `- name:`; не ошибка доступности hosts |
| SSH `Could not resolve hostname ultra1-8` | Не разрешается короткое имя; не доказательство отказа физического хоста |
| `Host key verification failed` | Проблема проверки ключа сервера; не «нет прав OpenStack» |

Локально на операторе, **без запуска сбора**, проверьте конкретный файл:

```bash
read -r -p 'Путь к плейбуку: ' PLAYBOOK
sed -n '1,24p' "$PLAYBOOK"
ansible-playbook --syntax-check "$PLAYBOOK"
getent ahostsv4 ultra1-8.ultra1.test.pvs.un.sbt
```

Перед сетевой проверкой выберите IP доступного контроллера по inventory/CMDB,
а не угадывайте его по имени. Для нашей прежней схемы `.150/.151/.152` относятся
к ultra1-6/7/8, но это надо подтвердить:

```bash
read -r -p 'Проверенный IP доступного контроллера: ' DIAG_CONTROLLER_IP
ssh -o BatchMode=yes -o ConnectTimeout=10 "$DIAG_CONTROLLER_IP" 'hostname -f'
```

Не отключайте `StrictHostKeyChecking` и не удаляйте known_hosts вслепую.
При несовпадении ключа сверьте fingerprint доверенным способом.
`ansible_host` может переопределить адрес подключения независимо от красивого
FQDN в отчёте. API-only проверки PowerOps не должны зависеть от SSH к аварийному
compute; SSH в этом разделе нужен только для доступа оператора к контроллеру.

## 12. Что приложить к результату диагностики

Один инцидент — host/segment, UTC-окно, execution либо notification UUID,
VM UUID и source/destination, фактические image IDs затронутых реплик,
HTTP-коды/Request-ID, первая ошибка и очищенные связанные логи.
Отдельно отметьте недоступные API/узлы и срез «до»/«после».

Команды сверены по синтаксису и доступным исходникам/CLI parsers локально;
они не выполнялись против живого облака при подготовке документа. Наличие
пакета и успешный parser/import test не доказывают API permissions, отсутствие
кеша в работающем процессе или готовность всех реплик.
Для Mistral выполнена сверка с исходниками клиента и проверка shell-синтаксиса,
но не прогон через установленный Mistral CLI plugin. Python-пробы проверены
на синтаксис; импорты из реальных контейнерных образов здесь не запускались.
