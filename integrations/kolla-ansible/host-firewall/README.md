# Host firewall: обследование, применение и откат через firewalld

Отдельная добавка к Kolla-Ansible `0809` по
[ADR-0002](../../../docs/adr/0002-host-firewall.md).

Точка запуска — **`kolla-ansible host-firewall`**. Kolla-Ansible загружает
inventory, `/etc/kolla/globals.yml`, файлы `globals.d` и переданные `-e`, затем
вызывает `ansible/host-firewall.yml`. Роль `host-firewall` собирает отчёт либо
применяет правила через firewalld. Обычные `deploy` и `reconfigure` эту
операцию автоматически не запускают.

По умолчанию `report` ничего не меняет на хостах. Реализованы также
`apply` и `rollback`: работа с собственной policy `kolla-host-input` через
D-Bus firewalld **1.3.4 / nftables**, последовательное применение и локальное
восстановление. Пакеты и сам firewalld автоматически не устанавливаются,
не запускаются и не перезапускаются. Инициализация устанавливает и запускает
только собственные recovery units; создание пустой policy требует отдельно
разрешённого reload firewalld.

**Ограничение текущей поставки:** каталог потоков OpenStack пока частичный.
`PARTIAL_SERVICE_COVERAGE`, неизвестные включённые сервисы и неполный сбор
по-прежнему запрещают restrictive apply. Реализованный механизм применения
не означает, что уже можно безопасно закрыть весь кластер Ultra.
Перед изменениями Kolla заново проверяет блокировки и сверяет идентификатор
плана. Полный каталог сервисов — отдельная оставшаяся работа.

Порядок работы после установки:
[инициализация → новый отчёт → применение правил → проверка → откат при необходимости](#apply).
**Установка патча и успешный `report` не применяют правила.** Для этого нужен
отдельный запуск `kolla-ansible host-firewall --mode apply` с проверенным `plan_id`.

## Что получается

Режим `report` выводит сводку непосредственно в консоль Ansible:

- `plan_id` — идентификатор рассчитанного плана для следующего apply.
- `selected_hosts`, `not_selected_hosts`, `collection_complete` — состав и полнота сбора.
- `reports` — SSH-порт, предварительные разрешения, состояние firewalld и блокировки по хостам.

**Файлы `report.json`, `report.md` и каталог отчётов на controller не создаются.**
Полные результаты команд используются в памяти текущего запуска; в консоль
выводятся только перечисленные поля модели. Существующие отчёты прежних версий
автоматически не удаляются. Журнал транзакции на управляемом хосте сохраняется:
он нужен локальному откату и не является отчётом controller.

## Получение отдельной ветки

Код и эта инструкция находятся в ветке `feature/host-firewall-apply`
репозитория `lebtmalorny-rgb/mimaric`. Ветка не требует слияния в `main`.
Чтобы не переключать существующий рабочий checkout, получить отдельную копию
в свободный каталог (родительский `~/work` должен существовать):

```bash
git clone --branch feature/host-firewall-apply --single-branch \
  https://github.com/lebtmalorny-rgb/mimaric.git ~/work/mimaric-firewall
git -C ~/work/mimaric-firewall log -1 --oneline
```

Инструкция в этой копии: `integrations/kolla-ansible/host-firewall/README.md`.
Сначала выполнить установку добавки и read-only `report`. До полноты каталога
не переходить к restrictive apply на рабочем кластере.

## Установка добавки

Поставка состоит из двух частей:

- [CLI-патч](patches/0001-add-host-firewall-command.patch) добавляет команду
  `host-firewall` в `kolla_ansible/cli/commands.py` и регистрацию в `setup.cfg`.
- Подкаталог `ansible/` содержит playbook, plugins, модули и роль. Его нужно
  скопировать в `ansible/` исходников Kolla-Ansible.

Обе части обязательны. После установки требуется переустановить Python-пакет
Kolla-Ansible в используемом окружении controller: это регистрирует команду
и устанавливает её Ansible-файлы. Сборка контейнерных образов не требуется.

Ниже пример для двух локальных checkout: `~/work/mimaric-firewall` и
`~/work/kolla-ansible`. Подставить свои пути. Использовать чистую отдельную
ветку Kolla-Ansible на базе `0809`; существующие одноимённые файлы означают,
что добавка уже установлена — обновление тогда требует сравнения версий.

```bash
cd ~/work/kolla-ansible
git switch -c feature/host-firewall-apply
git apply --check ~/work/mimaric-firewall/integrations/kolla-ansible/host-firewall/patches/0001-add-host-firewall-command.patch
git apply ~/work/mimaric-firewall/integrations/kolla-ansible/host-firewall/patches/0001-add-host-firewall-command.patch
rsync -a --exclude='__pycache__' --exclude='*.pyc' \
  ~/work/mimaric-firewall/integrations/kolla-ansible/host-firewall/ansible/ \
  ./ansible/
git status --short
python -m pip install --no-deps .
kolla-ansible host-firewall --help
```

Копирование обновляет файлы добавки, поэтому выполнять его в отдельной рабочей
ветке с сохранёнными прежними изменениями. При обновлении уже установленной
добавки повторить копирование `ansible/` и установку Python-пакета; старый
`--ignore-existing` оставит прежний код сохранения отчётов и для обновления не подходит.
Повторно применять уже установленный CLI-патч не нужно. При конфликте
`git apply --check` сравнить версию исходников; патч проверен на базе `0809`.
Убрать старый `host_firewall_plan_file` из параметров: он больше не принимается.
`host_firewall_output_dir` больше не используется. Для apply нужен `plan_id`
из консольной сводки, а не путь к файлу.
Изменение `site.yml`, deploy/reconfigure handlers, globals и образов не требуется.

## Запуск

Требования: рабочий controller Kolla-Ansible с **ansible-core 2.18.x**, его
обычный inventory и Linux-хосты с Python. Локальная проверка выполнена с
ansible-core 2.18.2; другие ветки Ansible этим этапом не заявлены и gate их
отклоняет. Новые collections или runtime-зависимости добавка не добавляет.

Запускать из обычного окружения пользователя на controller, не оборачивать
весь playbook в `sudo`. Для удалённых read-only команд используется Ansible
`become`; ключи, пользователь и адреса берутся из существующего inventory.
`passwords.yml` и OpenStack credentials этому playbook не нужны.
Команда не загружает `passwords.yml` и не запускает получение секретов из Vault.
`--configdir` задаёт каталог Kolla-конфигурации; по умолчанию это `/etc/kolla`
(либо существующая настройка `KOLLA_CONFIG_PATH`). Файлы `globals.d` загружаются
в алфавитном порядке после `globals.yml`, затем действуют переданные `-e`.

Посмотреть состав задач без их выполнения:

```bash
cd ~/work/kolla-ansible
kolla-ansible host-firewall -i ./ansible/inventory/multinode \
  --configdir /etc/kolla --list-tasks
```

После проверки путей и состава inventory, для сбора:

```bash
kolla-ansible host-firewall -i ./ansible/inventory/multinode \
  --configdir /etc/kolla
```

По умолчанию выбирается группа `baremetal`. Для ограниченного сбора:

```bash
kolla-ansible host-firewall -i ./ansible/inventory/multinode \
  --configdir /etc/kolla --limit 'control'
```

`--limit` не вызывает дополнительных подключений к исключённым хостам.
Адреса исключённых источников не угадываются и не берутся из старого fact cache;
поэтому предварительная матрица такого запуска может оказаться неполной.
Если ни один хост не выбран, Ansible может завершиться без отчёта: отсутствие
сводки с `plan_id` не является успешным обследованием.

Произвольная группа вместо `baremetal` задаётся
`-e host_firewall_hosts=control`. Не указывать случайно инфраструктуру за
пределами выбранного развёртывания. `--check` также выполняет read-only сбор
и выводит сводку без сохранения файлов.
Подмена playbook через `--playbook` и частичный запуск через `--tags`/
`--skip-tags` для этой команды запрещены: допуск, применение и проверки
должны выполняться вместе.

Режим задаётся **только аргументом `--mode report|apply|rollback`**.
Без `--mode` всегда выбирается `report`, даже если в globals или `-e` указано
`host_firewall_mode: apply`. Kolla передаёт выбранный режим в playbook с высшим
приоритетом. Остальные `host_firewall_*` передаются обычным способом.

## Параметры обследования

| Параметр | По умолчанию | Значение |
| --- | --- | --- |
| `--mode` | `report` | Аргумент CLI: `report`, `apply`, `rollback` |
| `host_firewall_hosts` | `baremetal` | Ansible host pattern; дополнительно действует `--limit` |
| `host_firewall_become` | `true` | Повышение прав для удалённого сбора |
| `host_firewall_probe_timeout` | `10` | Секунды на одну команду, целое `1..120` |
| `host_firewall_probe_max_bytes` | `262144` | Лимит байт отдельно для stdout/stderr, целое `1..4194304` |

Это параметры добавки, а не существующие опции upstream Kolla.
Кроме `--mode`, их можно передать через `-e` или свой globals. Команды внутри сборщика
фиксированы: произвольный shell или список команд через переменные не принимаются.
19 команд выполняются последовательно на каждом выбранном хосте; таймаут
относится к каждой отдельно, плюс время Ansible/SSH и завершения процесса.

## Какие сведения собираются

- Установленные RPM-пакеты `firewalld` и `python3-firewall`: версия, release,
  архитектура; отдельно версия `firewall-cmd` и состояние `firewalld.service`.
- Адреса интерфейсов, IPv4/IPv6 маршруты всех таблиц.
- Слушающие TCP/UDP порты без аргументов процессов.
- Состояние firewalld, активные зоны, runtime/permanent зоны и policies.
- Ruleset nftables, `iptables-save` и `ip6tables-save`.
- Состояние systemd units firewalld/nftables, bridge-netfilter sysctl.

Использованы read-only операции
[firewall-cmd](https://firewalld.org/documentation/man-pages/firewall-cmd.html).
Если команды нет, версия не поддерживает запрос, недостаточно прав, истёк
таймаут или вывод обрезан, это отдельная отметка о неполноте. Это не
доказательство отсутствия правил. Сборщик не устанавливает отсутствующие утилиты.

### Автоматические проверки firewalld в задачах

Задача роли `Collect bounded network and firewall observations` запускает
проверки с теми же таймаутами и ограничениями вывода. Ручные команды не нужны.
В консольной сводке каждого хоста есть объект `firewalld` с полями
`packages`, `cli_version`, `service`, `api`.

1. Через `rpm -q --queryformat ...` проверяется **установленная база пакетов**,
   без DNF, доступа к репозиториям или установки. Этот способ предназначен для
   RPM-хостов, включая текущий SberLinux. Если RPM недоступен (например, на
   Debian/Ubuntu) или база не читается, статус будет `неизвестно`, не «не установлен».
   В сводке это `installed: null`; `false` — только явный ответ об отсутствии пакета.
2. Через `systemctl show firewalld.service` собираются `LoadState`, `ActiveState`,
   `SubState`, `UnitFileState`. Отдельно отмечаются остановленная/упавшая служба,
   отсутствие постоянного автозапуска и `masked`. `enabled-runtime` не считается
   постоянным автозапуском. Запрос этой службы отделён от общей проверки units,
   чтобы отсутствие `nftables.service` не мешало оценке firewalld.
3. `firewall-cmd --version`, `--state` и чтение runtime/permanent policies
   показывают версию клиента и доступность API-чтения. Пустой успешный список
   policies допустим. Ошибка API не объявляется автоматически «версия не
   поддерживается»: причиной могут быть права, D-Bus или остановленная служба.

API-поля имеют значения `true` (запрос успешен), `false` (получен код
ошибки), `null` (нет полной достоверной проверки). Исходные ответы используются
только в памяти, в консоль они не выводятся. Наличие `python3-firewall` в RPM не доказывает
импорт bindings конкретным Ansible-интерпретатором; успешное чтение policies
не доказывает права на их изменение. Backend и совместимость всей конфигурации
по одной версии не утверждаются.

Отсутствие prerequisites **не прерывает report**, остальные сведения продолжают
собираться. В режиме `report` нет автоустановки, `start`, `enable`, `unmask`,
`reload` или изменения правил. Успешные предварительные проверки сами по себе
не разрешают применение: для ограничительного `apply` нужны полный каталог,
проверенный отчёт и остальные условия допуска, описанные ниже.

Семантика запросов: [RPM query](https://rpm.org/docs/4.20.x/man/rpm.8),
[firewall-cmd](https://firewalld.org/documentation/man-pages/firewall-cmd.html).

## Как читать матрицу

Каталог `ansible/roles/host-firewall/vars/catalog.yml` содержит только
предварительные HAProxy → backend API связи Keystone, Mistral, Masakari
и Ironic, сверенные с ролями `0809`. Внешний VIP-порт не подставляется вместо
backend listen-порта. Выключенный сервис или HAProxy не создаёт такой поток.
Public backend Keystone дополнительно требует вычисленного
`haproxy_enable_external_vip=true`; неизвестное или выключенное значение
не создаёт этот поток.

Адрес должен наблюдаться в текущем выводе `ip` на выбранном `api_interface`
и соответствовать `api_address_family`. При нескольких адресах требуется
однозначный `api_interface_address`; адреса VIP исключаются. Выражения
с ошибкой и явный `null` не заменяются автоматическим выбором адреса.
Динамические и нестандартные override-выражения могут остаться непокрытыми — это показывается
как неопределённая переменная. Сбор не импортирует deploy-роли ради их defaults.

| Код | Что означает |
| --- | --- |
| `APPLY_REQUIRES_VERIFICATION` | Сам отчёт не подтверждает безопасность; нужны отдельная транзакция и live-проверки |
| `PARTIAL_SERVICE_COVERAGE` | Описана только часть связей сервиса, не БД/RPC и все зависимости |
| `UNKNOWN_ENABLED_FLAG` | Включённый сервис либо feature flag ещё не покрыт каталогом |
| `INVALID_ENABLE_FLAG`, `MISSING_ENABLE_FLAG` | Значение флага неоднозначно или отсутствует |
| `UNRESOLVED_VARIABLE`, `INVALID_PORT` | Не удалось получить пригодное значение без догадок |
| `UNRESOLVED_FLOW_CONDITION` | Не вычислено обязательное условие конкретного потока |
| `MISSING_GROUP`, `MISSING_ADDRESS`, `INVALID_ADDRESS` | Недостаточно сведений о размещении или адресах |
| `ADDRESS_FAMILY_MISMATCH` | Источник и назначение относятся к разным IP-семействам |
| `SSH_ACCESS_NOT_VERIFIED`, `SSH_PORT_UNRESOLVED` | Новое SSH-подключение не проверено; порт нельзя подтвердить из inventory |
| `PROBE_*`, `OBSERVATION_MISSING` | Неполное или неуспешное наблюдение |
| `PROJECTION_INCOMPLETE` | Не получена полноценная проекция переменных хоста |
| `FIREWALLD_PACKAGE_MISSING`, `FIREWALLD_PACKAGE_UNKNOWN` | Пакет явно отсутствует либо его наличие не удалось установить |
| `FIREWALLD_VERSION_UNKNOWN`, `FIREWALLD_SERVICE_UNKNOWN` | Версия клиента или свойства службы не подтверждены |
| `FIREWALLD_NOT_LOADED`, `FIREWALLD_NOT_RUNNING` | Unit не загружен нормально либо служба не работает |
| `FIREWALLD_NOT_ENABLED`, `FIREWALLD_MASKED` | Нет постоянного автозапуска либо запуск заблокирован |
| `FIREWALLD_API_UNAVAILABLE`, `FIREWALLD_API_UNKNOWN` | Запрос API завершился ошибкой либо достоверного результата нет |

`collection_complete` требует результатов всех 19 измерений на каждом выбранном
хосте без ошибок/обрезания/таймаутов. Отсутствующее измерение — `PROBE_MISSING`,
а не успешный пустой результат. Эта полнота относится только к сбору;
готовности firewall и полноты каталога она не подтверждает.

Модель учитывает все доступные `enable_*` как bool либо неопределённое значение.
Неизвестные feature flags перечисляются в блокировках консольной сводки. При таком начальном каталоге
блокировки ожидаемы: отчёт не должен объявить всё развёртывание покрытым.

Открытый socket — наблюдение, а не автоматическое разрешение доступа.
Apply проверяет маркер владельца своей policy, её неизменяемые поля, ранние
HOST policies и изменение снимка чужих объектов firewalld. Это не полный
аудит правил ядра или Security Groups. Для ограничения реального OpenStack
остаётся дополнить и проверить весь каталог необходимых потоков.

<a id="apply"></a>

## Применение правил через Kolla-Ansible

| Этап | Действие оператора | Результат |
| --- | --- | --- |
| 1 | Один раз вызвать `--mode apply` с флагами инициализации | Подготовлена пустая policy и локальный механизм отката; ограничения ещё не включены |
| 2 | После инициализации вызвать `--mode report` | Консольная сводка с `plan_id` для выбранных хостов |
| 3 | Подготовить YAML с `plan_id` и проверками сервисов | Входные параметры применения |
| 4 | Вызвать `--mode apply` с этим YAML, без флага инициализации | Kolla применяет runtime-правила и после проверок сохраняет permanent |
| 5 | Проверить завершение Ansible и состояние транзакции | Подтверждено сохранение правил либо обнаружен отказ/откат |
| 6 | При необходимости вызвать `--mode rollback` с UUID | Восстановлены прежние правила собственной policy |

Ниже один последовательный пример для хоста `ultra1-2`. Заменить имя хоста,
inventory и адреса проверок своими. **Одинаковый набор хостов
должен использоваться при формировании отчёта и при apply.** Для другого набора
нужен другой отчёт. Текущий неполный каталог OpenStack блокирует этап 4;
инициализация и успешный сбор отчёта эту блокировку не снимают.

### Что Kolla-Ansible делает во время применения

1. Controller проверяет формат `plan_id`, параметры проверок и отката ещё до
   подключения к хостам. Файлы отчётов не читаются.
2. Заново выполняется read-only сбор и расчёт плана в памяти. До первой записи
   правил проверяются полнота сбора и blockers всего выбранного набора хостов.
   Изменившиеся порты, адреса, флаги, каталог или состав хостов приводят к
   несовпадению `plan_id` и запрещают применение.
3. Хосты обрабатываются с `serial: 1`, `any_errors_fatal: true`. До изменения
   проверяются новое SSH-подключение и заданные service checks.
4. На управляемом хосте сохраняются разные исходные runtime/permanent снимки, исходный
   XML, UUID транзакции и deadline. Без работающего собственного watchdog
   применение не начинается. Каждая отдельная запись заранее заносится в журнал.
5. Меняются только rich rules собственной policy. SSH-порт из inventory
   разрешён с любых IPv4/IPv6 адресов; ICMP/ICMPv6 разрешены; сервисные правила
   содержат точные адреса источника и назначения. Последнее правило — drop.
6. Controller открывает новое SSH-соединение без reuse, со строгой проверкой
   host key, и повторяет service checks. Лишь затем сохраняется permanent.
7. Ошибка вызывает rollback и остановку дальнейшего rollout. При недоступном
   SSH или пропавшем controller локальный timer восстанавливает правила после
   deadline. Watchdog не отключается после успешной транзакции — он остаётся
   наблюдать журнал, но не откатывает `COMMITTED`.

Собственная policy: `ANY → HOST`, priority `-500`, target `CONTINUE`.
Зоны, default zone, OUTPUT/FORWARD, NAT и чужие объекты не переписываются.
Команды `runtime-to-permanent`, flush ruleset и прямые записи nft/iptables
не используются. Совместимость с произвольным существующим firewall не заявлена.

### Этап 1. Подготовить policy и механизм отката

Нужны уже установленные RPM `firewalld`, `python3-firewall`, доступный D-Bus
из Python Ansible, работающий и enabled firewalld **1.3.4 / nftables**.
Свежая SSH-проверка требует явного `ansible_user`, известного host key и ключа
или ssh-agent. Произвольные SSH options/ProxyJump/password в этом профиле
не поддержаны: проверка останавливается, а не отключает защиту host key.

Пример команды для одного хоста; путь inventory и имя выбрать свои:

```bash
kolla-ansible host-firewall --mode apply -i ./ansible/inventory/multinode \
  --configdir /etc/kolla --limit ultra1-2 \
  -e '{"host_firewall_initialize":true,"host_firewall_allow_initial_reload":true}'
```

Это **изменяющая операция**, не dry run. Создаёт только пустую policy и
устанавливает helper, timer, boot-recovery unit и свой drop-in для firewalld.
Первое создание policy вызывает reload, отдельно разрешённый указанным флагом.
Он запрещён при runtime/permanent drift, direct rules, IP sets,
чужих nftables tables или непустых iptables rulesets. При уже подготовленной
policy reload не выполняется. Чужая одноимённая policy не присваивается себе.

`--check` проверяет входные параметры без установки файлов, запуска units
или изменения правил. Это не подтверждение live-совместимости хоста.

### Этап 2. Сформировать новый отчёт после подготовки

После инициализации выполнить отдельный сбор. Если policy и recovery units
уже подготовлены ранее, начать с этого этапа.

```bash
kolla-ansible host-firewall --mode report -i ./ansible/inventory/multinode \
  --configdir /etc/kolla --limit ultra1-2
```

В выводе задачи `Show firewall plan summary without saving report files`
взять значение `plan_id` — строку из 64 шестнадцатеричных символов. Его нужно
указать на этапе 3. Проверить `selected_hosts`, `collection_complete` и блокировки
каждого хоста. Отдельный файл отчёта не создаётся и не требуется.

`PARTIAL_SERVICE_COVERAGE`, неизвестные включённые сервисы, неполные наблюдения
и остальные ошибки модели запрещают применение. Только
`SSH_ACCESS_NOT_VERIFIED` и `APPLY_REQUIRES_VERIFICATION` допускаются на этом
этапе: соответствующие проверки выполняются самим apply. Поле
`apply_ready: false` в read-only отчёте не заменяет эту проверку допуска.
Apply самостоятельно повторит расчёт: менять поля сводки для обхода допуска бессмысленно.

### Этап 3. Подготовить параметры применения

Для реального OpenStack текущий partial catalog остановит эту команду.
Ниже интерфейс уже реализованного apply, **не рекомендация обходить blockers**.
Состав выбранных хостов и `--limit` должен совпадать с отчётом.

В отдельном YAML параметров, например `/etc/kolla/host-firewall-apply.yml`:

```yaml
host_firewall_initialize: false
host_firewall_allow_initial_reload: false
host_firewall_plan_id: 'ВСТАВИТЬ_64_HEX_СИМВОЛА_ИЗ_ПОЛЯ_plan_id_В_КОНСОЛИ'
host_firewall_rollback_timeout: 300
host_firewall_verification_checks:
  - id: api
    type: tcp
    host: 192.0.2.10
    port: 443
  - id: health
    type: http
    url: https://api.example.test/health
    status: 200
```

Адреса — примеры, заменить реальными проверяемыми endpoints. TCP проверяет
только установление соединения; HTTP — заданный успешный код без redirect,
HTTPS — с проверкой сертификата. Credentials/query в URL не принимаются.
Это не доказательство исправности RPC, HA, миграции или всех связей между хостами;
для них необходимы отдельные квалификационные проверки профиля.

Флаги инициализации оставлены `false`, чтобы следующий вызов выполнял именно
применение правил. `host_firewall_initialize: true` выбирает только подготовку
пустой policy. Не переносить флаги первоначальной подготовки в постоянные globals.

### Этап 4. Применить правила

Именно эта команда записывает разрешения SSH/ICMP/сервисов и завершающий запрет
в собственную policy. Перед записью Kolla повторно собирает сведения и сверяет
идентификатор свежего плана с указанным `plan_id`. Изменённые входные данные
требуют нового запуска `report` и проверки нового идентификатора.

```bash
kolla-ansible host-firewall --mode apply -i ./ansible/inventory/multinode \
  --configdir /etc/kolla --limit ultra1-2 \
  -e @/etc/kolla/host-firewall-apply.yml
```

Правила сначала меняются в runtime. Kolla проверяет новое SSH-соединение и
указанные сервисы, затем сохраняет только проверенные правила в permanent.
Ошибка останавливает переход к следующему хосту и вызывает откат; при потере
связи восстановлением занимается локальный watchdog.

`host_firewall_rollback_timeout`: целое `60..900`, секунд с начала транзакции,
не со старта playbook. Проверки до начала: SSH до 20 с; TCP/HTTP socket timeout
5 с на check; 1–16 checks. DNS может занимать дополнительное время.
Watchdog проверяет срок примерно каждые 2 с; rollback занимает дополнительное
время и зависит от доступности D-Bus/firewalld и диска. Срок — не обещание
восстановления сети ровно на указанной секунде.

### Этап 5. Проверить результат применения

В Ansible должны успешно завершиться задачи
`Verify a new SSH connection and required service endpoints after apply` и
`Persist only the verified owned rich rules`, а в итоговой сводке выбранного
хоста — `failed=0`, `unreachable=0`. Успех одних задач сбора или инициализации
не означает применение правил. При повторном применении того же плана уже
сохранённая транзакция может завершиться без изменений.

UUID выводится задачей `Show transaction identifier for recovery without
revealing its nonce`. Финальное состояние хранится на хосте в
`/var/lib/kolla-host-firewall/transactions/<UUID>.json`, поле `state`:
`COMMITTED` — правила сохранены, `ROLLED_BACK` — выполнено восстановление.
Промежуточное состояние не считать успешным завершением. Начальный `state`,
напечатанный вместе с UUID до записи правил, не является финальным результатом.

На выбранном хосте посмотреть собственную policy в runtime и permanent:

```bash
sudo firewall-cmd --info-policy=kolla-host-input
sudo firewall-cmd --permanent --info-policy=kolla-host-input
```

Эти команды только читают правила. Проверка их наличия дополняет выполненные
Kolla проверки связности, но не заменяет проверку миграций, сети ВМ и HA на стенде.

### Этап 6. Выполнить откат при необходимости

UUID показан задачей `Show transaction identifier...`. У каждого хоста свой UUID.
Использовать только текущую транзакцию конкретного хоста; старая отклоняется:

```bash
kolla-ansible host-firewall --mode rollback -i ./ansible/inventory/multinode \
  --configdir /etc/kolla --limit ultra1-2 \
  -e host_firewall_rollback_transaction_id=ВСТАВИТЬ_UUID_ТРАНЗАКЦИИ
```

На самом хосте (при необходимости через локальную/BMC-консоль):

```bash
sudo systemctl status kolla-host-firewall-watchdog.timer
sudo journalctl -u kolla-host-firewall-watchdog.service -u kolla-host-firewall-boot-recovery.service -n 100 --no-pager
sudo firewall-cmd --info-policy=kolla-host-input
sudo firewall-cmd --permanent --info-policy=kolla-host-input
```

Журнал и снимки: `/var/lib/kolla-host-firewall/`, каталог `0700`, JSON `0600`.
Они содержат внутренние правила и nonce; не публиковать целиком.
Не удалять их и не отключать watchdog во время незавершённой транзакции.
На новом boot исходный owned XML восстанавливается **до запуска firewalld**;
после запуска timer завершает восстановление прежнего runtime. При конфликте
владельца/неподтверждённом повреждении журнал сохраняется, boot recovery завершится
ошибкой и запуск firewalld будет заблокирован зависимостью `Requires`.
Тогда нужна диагностика с консоли; автоматический запуск firewalld в обход
этой ошибки небезопасен. Это программный recovery, не гарантия при отказе диска/ОС.

## Локальные проверки

Из корня `mimaric`, в Python-окружении Kolla-Ansible (нужны `cliff`, `pbr`,
`PyYAML`) и с `ansible-playbook` версии 2.18.x в PATH:

```bash
python3 -m unittest discover \
  -s integrations/kolla-ansible/host-firewall/tests -v
python3 -m unittest discover -s tests -v
git diff --check
```

Integration tests запускают настоящий Ansible в одноразовом дереве, заменяя
только OS/connection boundary тестовыми fixtures. Они не вызывают настоящий
firewall и не подключаются к стенду. Чистые тесты runner запускают только свои
короткие дочерние процессы и проверяют timeout/лимиты вывода.

Дополнительный тест автоматически ищет объявленный архив `0809` в родительских
каталогах workspace, сверяет SHA256 с `baselines/0809.json`, проверяет отсутствие
коллизий добавки, syntax-check и report run на временной копии исходников.
Он проверяет сохранность исходных файлов Ansible-части. Без архива этот тест
помечается SKIP. CLI-патч отдельно меняет только `commands.py` и `setup.cfg`.

CLI-тесты также используют проверенный архив `0809`: применяют CLI-патч,
читают его регистрацию команды и запускают настоящий Kolla CLI и Ansible.
Проверяются режим по умолчанию, порядок globals/overrides, применение и откат,
сохранение кода ошибки Ansible и остановка перед следующим хостом.
Без архива или Python-зависимостей Kolla эти тесты помечаются SKIP; такой
запуск не подтверждает CLI-интеграцию.

Для CLI-поставки дополнительно проверены сборка wheel из базы `0809`, наличие
в нём всех Ansible-файлов добавки, установка через pip во временный каталог,
справка установленной команды, `--list-tasks` и формирование отчёта с переменными
`0809`. В проверке отчёта удалённое обследование заменено локальной fixture.

Ни эти проверки, ни успешный локальный отчёт не подтверждают, что firewall
можно безопасно включать на Ultra. Реального стендового запуска не выполнялось.
