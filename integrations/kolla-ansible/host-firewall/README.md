# Host firewall: обследование, применение и откат через firewalld

Отдельная добавка к Kolla-Ansible `0809` по
[ADR-0002](../../../docs/adr/0002-host-firewall.md).

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
Не удалять blockers вручную: перед изменениями отчёт собирается заново
и его идентификатор сверяется. Полный каталог сервисов — отдельная оставшаяся работа.

## Что получается

На controller сохраняется новый приватный каталог
`artifacts/host-firewall-<случайный суффикс>/` в корне Kolla-Ansible:

- `report.md` — читаемый итог по выбранным хостам.
- `report.json` — структурированный отчёт и вывод read-only команд.

Каталог имеет права `0700`, файлы — `0600`. Существующие отчёты не
перезаписываются. Уже существующий родительский каталог не получает новый chmod.
В вывод Ansible передаётся путь отчёта, а не его содержимое.
Правила могут содержать внутренние адреса и комментарии: обращаться с JSON
как с чувствительной диагностикой, не публиковать без проверки.

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

Подкаталог `ansible/` содержит только новые файлы. Его нужно скопировать
в `ansible/` исходников Kolla-Ansible; один YAML без соседних plugins и role
не является автономным playbook.

Ниже пример для двух локальных checkout: `~/work/mimaric-firewall` и
`~/work/kolla-ansible`. Подставить свои пути. Использовать чистую отдельную
ветку Kolla-Ansible на базе `0809`; существующие одноимённые файлы означают,
что добавка уже установлена — обновление тогда требует сравнения версий.

```bash
cd ~/work/kolla-ansible
git switch -c feature/host-firewall-apply
rsync -a --ignore-existing --exclude='__pycache__' --exclude='*.pyc' \
  ~/work/mimaric-firewall/integrations/kolla-ansible/host-firewall/ansible/ \
  ./ansible/
git status --short
```

`--ignore-existing` защищает существующие файлы, но не обновляет старую версию
добавки. Не считать такую команду универсальной процедурой upgrade.
Изменение `site.yml`, deploy/reconfigure handlers, globals и образов не требуется.

## Запуск

Требования: рабочий controller Kolla-Ansible с **ansible-core 2.18.x**, его
обычный inventory и Linux-хосты с Python. Локальная проверка выполнена с
ansible-core 2.18.2; другие ветки Ansible этим этапом не заявлены и gate их
отклоняет. Новые collections или Python-пакеты добавка не устанавливает.

Запускать из обычного окружения пользователя на controller, не оборачивать
весь playbook в `sudo`. Для удалённых read-only команд используется Ansible
`become`; ключи, пользователь и адреса берутся из существующего inventory.
`passwords.yml` и OpenStack credentials этому playbook не нужны.

```bash
cd ~/work/kolla-ansible
ansible-playbook -i ./ansible/inventory/multinode \
  ./ansible/host-firewall.yml \
  -e @/etc/kolla/globals.yml \
  --syntax-check
```

После проверки путей и состава inventory, для сбора:

```bash
ansible-playbook -i ./ansible/inventory/multinode \
  ./ansible/host-firewall.yml \
  -e @/etc/kolla/globals.yml
```

По умолчанию выбирается группа `baremetal`. Для ограниченного сбора:

```bash
ansible-playbook -i ./ansible/inventory/multinode \
  ./ansible/host-firewall.yml \
  -e @/etc/kolla/globals.yml \
  --limit 'control'
```

`--limit` не вызывает дополнительных подключений к исключённым хостам.
Адреса исключённых источников не угадываются и не берутся из старого fact cache;
поэтому предварительная матрица такого запуска может оказаться неполной.
Если ни один хост не выбран, Ansible может завершиться без отчёта: отсутствие
нового пути `report.md` не является успешным обследованием.

Произвольная группа вместо `baremetal` задаётся
`-e host_firewall_hosts=control`. Не указывать случайно инфраструктуру за
пределами выбранного развёртывания. `--check` также выполняет read-only сбор
и сохраняет новый локальный отчёт; это явно предусмотренное поведение.

## Параметры обследования

| Параметр | По умолчанию | Значение |
| --- | --- | --- |
| `host_firewall_mode` | `report` | `report`, `apply`, `rollback` |
| `host_firewall_hosts` | `baremetal` | Ansible host pattern; дополнительно действует `--limit` |
| `host_firewall_become` | `true` | Повышение прав для удалённого сбора |
| `host_firewall_probe_timeout` | `10` | Секунды на одну команду, целое `1..120` |
| `host_firewall_probe_max_bytes` | `262144` | Лимит байт отдельно для stdout/stderr, целое `1..4194304` |
| `host_firewall_output_dir` | `artifacts` в корне Kolla-Ansible | Абсолютный путь родительского каталога отчётов на controller |

Это параметры добавки, а не существующие опции upstream Kolla.
Их можно передать через `-e` или свой globals. Команды внутри сборщика
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
В `report.md` появляется раздел «Проверка firewalld», в JSON каждого хоста —
объект `firewalld` с полями `packages`, `cli_version`, `service`, `api`.

1. Через `rpm -q --queryformat ...` проверяется **установленная база пакетов**,
   без DNF, доступа к репозиториям или установки. Этот способ предназначен для
   RPM-хостов, включая текущий SberLinux. Если RPM недоступен (например, на
   Debian/Ubuntu) или база не читается, статус будет `неизвестно`, не «не установлен».
   В JSON это `installed: null`; `false` — только явный ответ об отсутствии пакета.
2. Через `systemctl show firewalld.service` собираются `LoadState`, `ActiveState`,
   `SubState`, `UnitFileState`. Отдельно отмечаются остановленная/упавшая служба,
   отсутствие постоянного автозапуска и `masked`. `enabled-runtime` не считается
   постоянным автозапуском. Запрос этой службы отделён от общей проверки units,
   чтобы отсутствие `nftables.service` не мешало оценке firewalld.
3. `firewall-cmd --version`, `--state` и чтение runtime/permanent policies
   показывают версию клиента и доступность API-чтения. Пустой успешный список
   policies допустим. Ошибка API не объявляется автоматически «версия не
   поддерживается»: причиной могут быть права, D-Bus или остановленная служба.

API-поля JSON имеют значения `true` (запрос успешен), `false` (получен код
ошибки), `null` (нет полной достоверной проверки). Исходные ответы остаются
в `observations.commands`. Наличие `python3-firewall` в RPM не доказывает
импорт bindings конкретным Ansible-интерпретатором; успешное чтение policies
не доказывает права на их изменение. Backend и совместимость всей конфигурации
по одной версии не утверждаются.

Отсутствие prerequisites **не прерывает report**, остальные сведения продолжают
собираться. Никакой автоустановки, `start`, `enable`, `unmask`, `reload` или
изменения правил нет. `apply` по-прежнему целиком заблокирован: успешные
предварительные проверки не включают применение.

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

Все доступные `enable_*` отражаются как bool либо неопределённое значение.
Неизвестные feature flags намеренно не скрываются. При таком начальном каталоге
блокировки ожидаемы: отчёт не должен объявить всё развёртывание покрытым.

Открытый socket — наблюдение, а не автоматическое разрешение доступа.
Apply проверяет маркер владельца своей policy, её неизменяемые поля, ранние
HOST policies и изменение снимка чужих объектов firewalld. Это не полный
аудит правил ядра или Security Groups. Для ограничения реального OpenStack
остаётся дополнить и проверить весь каталог необходимых потоков.

## Как выполняется применение

1. Controller проверяет сохранённый JSON, `plan_id`, точный список выбранных
   хостов и blockers, ещё до подключения к хостам.
2. Заново выполняется read-only сбор. Изменившиеся порты, адреса, флаги,
   каталог или состав inventory запрещают использование старого отчёта.
3. Хосты обрабатываются с `serial: 1`, `any_errors_fatal: true`. До изменения
   проверяются новое SSH-подключение и заданные service checks.
4. Локально сохраняются разные исходные runtime/permanent снимки, исходный
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

### Однократная инициализация

Нужны уже установленные RPM `firewalld`, `python3-firewall`, доступный D-Bus
из Python Ansible, работающий и enabled firewalld **1.3.4 / nftables**.
Свежая SSH-проверка требует явного `ansible_user`, известного host key и ключа
или ssh-agent. Произвольные SSH options/ProxyJump/password в этом профиле
не поддержаны: проверка останавливается, а не отключает защиту host key.

Пример команды для одного хоста; путь inventory и имя выбрать свои:

```bash
ansible-playbook -i ./ansible/inventory/multinode ./ansible/host-firewall.yml \
  -e @/etc/kolla/globals.yml --limit ultra1-2 \
  -e '{"host_firewall_mode":"apply","host_firewall_initialize":true,"host_firewall_allow_initial_reload":true}'
```

Это **изменяющая операция**, не dry run. Создаёт только пустую policy и
устанавливает helper, timer, boot-recovery unit и свой drop-in для firewalld.
Первое создание policy вызывает reload, отдельно разрешённый указанным флагом.
Он запрещён при runtime/permanent drift, direct rules, IP sets,
чужих nftables tables или непустых iptables rulesets. При уже подготовленной
policy reload не выполняется. Чужая одноимённая policy не присваивается себе.

`--check` проверяет входные параметры без установки файлов, запуска units
или изменения правил. Это не подтверждение live-совместимости хоста.

### Apply по проверенному отчёту

Для реального OpenStack текущий partial catalog остановит эту команду.
Ниже интерфейс уже реализованного apply, **не рекомендация обходить blockers**.
Состав выбранных хостов и `--limit` должен совпадать с отчётом.

В отдельном YAML параметров, например `/etc/kolla/host-firewall-apply.yml`:

```yaml
host_firewall_mode: apply
host_firewall_plan_file: /home/operator/work/kolla-ansible/artifacts/host-firewall-EXAMPLE/report.json
host_firewall_plan_id: 'ВСТАВИТЬ_64_HEX_СИМВОЛА_ИЗ_ПОЛЯ_plan_id_ОТЧЁТА'
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

```bash
ansible-playbook -i ./ansible/inventory/multinode ./ansible/host-firewall.yml \
  -e @/etc/kolla/globals.yml -e @/etc/kolla/host-firewall-apply.yml
```

`host_firewall_rollback_timeout`: целое `60..900`, секунд с начала транзакции,
не со старта playbook. Проверки до начала: SSH до 20 с; TCP/HTTP socket timeout
5 с на check; 1–16 checks. DNS может занимать дополнительное время.
Watchdog проверяет срок примерно каждые 2 с; rollback занимает дополнительное
время и зависит от доступности D-Bus/firewalld и диска. Срок — не обещание
восстановления сети ровно на указанной секунде.

### Ручной откат и локальная диагностика

UUID показан задачей `Show transaction identifier...`. У каждого хоста свой UUID.
Использовать только текущую транзакцию конкретного хоста; старая отклоняется:

```bash
ansible-playbook -i ./ansible/inventory/multinode ./ansible/host-firewall.yml \
  -e @/etc/kolla/globals.yml --limit ultra1-2 \
  -e host_firewall_mode=rollback \
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

Из корня `mimaric`:

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
Он проверяет сохранность исходных файлов. Без архива этот тест помечается SKIP;
остальные тесты не требуют исходников Kolla.

Ни эти проверки, ни успешный локальный отчёт не подтверждают, что firewall
можно безопасно включать на Ultra. Реального стендового запуска не выполнялось.
