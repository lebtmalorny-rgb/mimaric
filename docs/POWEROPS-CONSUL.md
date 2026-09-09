# PowerOps: Consul, матрица отказов и настройки Kolla-Ansible

Сверка: 9 сентября 2026 года. Основа — пользовательский архив
`kolla-ansible-enroll-ironic-patch-3_0809.zip`, не произвольная версия upstream
Kolla-Ansible. SHA256 архива:
`b5958f14a09b1bdad4edc9c6b3dd092f4376b55dee9d5814fd2ad78fdffb1be9`.

Документ описывает код и шаблоны этой поставки. Фактические globals, inventory,
образы, итоговые конфиги и состояние каждого агента нужно проверять на стенде.
Исходники установленного `masakari-monitors` в этой базе отдельно не зафиксированы:
семантика samples ниже приведена по документации OpenStack, а не как проверка
бинарного образа. `planned-return-v2` не рассматривается.

Связанные документы:

- [Общая цепочка PowerOps](POWEROPS-OVERVIEW.md).
- [Диагностика всей цепочки](POWEROPS-DIAGNOSTICS.md).
- [Служебные пользователи и авторизация](POWEROPS-AUTHENTICATION.md).
- [Параметры Mistral, Masakari и Ironic](POWEROPS-CONFIGURATION.md).

## 1. Что делает Consul, а что делают другие компоненты

```text
Consul agents в контролируемых сетях
    → наблюдение доступности узлов через gossip
    → masakari-hostmonitor: опрос агентов, samples, health/action matrix
    → уведомление COMPUTE_HOST в Masakari API
    → Masakari engine: проверки, координация, запрет планирования
    → Ironic fencing: запрос питания через BMC и подтверждение off
    → ожидание Nova down в дополнительном патче Masakari
    → эвакуация подходящих ВМ через Nova
```

Consul не выключает сервер через BMC, не эвакуирует ВМ и не запускает плановый
workflow Mistral. Уведомление в Masakari отправляет **hostmonitor**, использующий
Consul как источник наблюдений. Такая модель описана в
[документации masakari-hostmonitor](https://docs.openstack.org/masakari-monitors/latest/hostmonitor.html).

Потеря LAN не доказывает физическое выключение. Изолированный compute может
продолжать исполнять ВМ; до эвакуации нужен подтверждённый fencing. Если сеть
позже вернулась, это не включает уже выключенный через BMC сервер автоматически.

Consul и etcd здесь выполняют разные задачи: Consul — обнаружение отказа;
etcd/Tooz — координация операций PowerOps. Raft quorum Consul, решение матрицы
по сетям и host lock PowerOps — три разных механизма. Нельзя заменять один другим.

## 2. Три логические сети и их имена

Определение находится в `ansible/group_vars/all.yml`, словарь `consul_networks`.
Роль `ansible/roles/consul/defaults/main.yml` содержит три соответствующих сервиса.

| Ключ сети | Datacenter | Kolla address network | Проверяемая interface-переменная | Address override на хосте | Имя в Masakari / порядок | Контейнер |
| --- | --- | --- | --- | --- | --- | --- |
| `management` | `management` | `api` | `network_interface` | `consul_management_address` | `manage` / 10 | `consul_management` |
| `customer` | `customer` | `tunnel` | `tunnel_interface` | `consul_customer_address` | `tenant` / 20 | `consul_customer` |
| `storage` | `storage` | `storage` | `storage_interface` | `consul_storage_address` | `storage` / 30 | `consul_storage` |

Это отдельные логические Consul-кластеры. Не путайте LAN gossip каждого кластера
с сетью tenant как таковой или с WAN federation между datacenter: наличие
параметра WAN port само по себе не настраивает federation этих трёх кластеров.

### Как выбираются server и client

- В поставляемом `ansible/inventory/multinode` все три `consul-*-server`
  объявлены children группы `control`.
- Дополнительно `ansible/site.yml` динамически добавляет servers:
  `api → control`, `tunnel → network`, `storage → storage`.
  Это добавление к уже существующим inventory groups, а не их замена.
- В `consul-client` попадают compute и узлы `masakari-hostmonitor`.
  Родительская группа `consul` объединяет server/client группы.
- Если узел входит и в server, и в client group, активный HCL-шаблон задаёт
  `server=true`: проверяется принадлежность к server group конкретной сети.
- `retry_join` строится из адресов всех hosts этой server group и LAN gossip
  порта. `bootstrap_expect` равен длине группы, а не отдельному globals-флагу.

Важное ограничение: комментарий к `server_group_extra` обещает список групп,
но `site.yml` использует значение как один ключ `groups.get(...)`, без обхода
списка. Непустой список не следует считать поддержанным способом расширения
топологии; надёжнее описать реальные `consul-*-server` группы в inventory и
проверить результат. Исправление кода группировки не входит в этот документ.

### Что реально делает автоматическое отключение сетей

`roles/consul/tasks/main.yml` пересчитывает `enabled` **на каждом хосте** перед
выбранным действием роли:

1. Сеть должна быть включена исходным `enabled`.
2. Interface-переменная должна быть непустой.
3. Для `customer`/`storage` имя интерфейса должно отличаться от
   `network_interface`; для `management` это сравнение не требуется.

Вопреки комментариям в globals, код сравнивает **строки имён интерфейсов**,
а не IP, VLAN, физические NIC или независимость L2. Два VLAN на одном кабеле
не становятся независимыми отказоустойчивыми путями. Два разных имени с общим
физическим трактом также могут пройти эту проверку.

Пересчёт локальный: разные hosts могут получить разный набор сетей. Матрица
Masakari должна быть одинаково осмысленной на всех hostmonitor; это проверяется
по доставленным файлам. При запуске только роли Masakari пересчёт роли Consul
может не выполняться. Уже работающий контейнер отключённой сети не удаляется
задачами `config.yml`/`deploy.yml`: они просто пропускают disabled service.

## 3. Матрица: когда появляется решение recovery

Цепочка генерации:

```text
consul_networks + masakari_consul_* в Ansible
    → filter masakari_consul_matrix
    → kolla_ansible/masakari_consul.py:build_matrix
    → roles/masakari/templates/matrix.yaml.j2
    → /etc/kolla/masakari-hostmonitor/matrix.yaml на хосте (обычный путь)
    → /etc/masakari-monitors/matrix.yaml в контейнере
```

В `sequence` входят только сети с `enabled=true` и `masakari_monitor=true`;
порядок определяется `masakari_order`. Допустимы уникальные имена `manage`,
`tenant`, `storage`. Пустой набор и повтор имён отклоняются. Генератор создаёт
все `2^N` сочетания `up/down`. Максимум в коде — 8 сетей, но разрешённые уникальные
имена в этой реализации фактически ограничивают набор тремя.

| Политика | Правило recovery | При трёх сетях |
| --- | --- | --- |
| `all_down` | Все участвующие сети `down` | Только 3 из 3 |
| `majority_down` | Число `down` строго больше `N/2` | 2 или 3 из 3 |
| `threshold` | Число `down >= masakari_consul_down_threshold` | Зависит от порога 1–3 |
| `custom` | Точное совпадение со строкой `masakari_consul_custom_recovery_states` | Явно заданные состояния |

Для одной сети `all_down` срабатывает при отказе этой одной сети. Для двух
сетей `majority_down` требует обе. Это голосование **сетевых состояний одного
узла**, а не большинство Consul servers или hostmonitor-процессов.

Полная таблица для `sequence: [manage, tenant, storage]`:

| manage | tenant | storage | all_down | majority_down / threshold=2 |
| --- | --- | --- | --- | --- |
| up | up | up | Нет | Нет |
| up | up | down | Нет | Нет |
| up | down | up | Нет | Нет |
| up | down | down | Нет | recovery |
| down | up | up | Нет | Нет |
| down | up | down | Нет | recovery |
| down | down | up | Нет | recovery |
| down | down | down | recovery | recovery |

В YAML `Нет` соответствует `action: []`, recovery — `action: [recovery]`.
Это решение монитора, ещё не доказательство принятого уведомления или эвакуации.

У `custom` ключи каждой строки должны точно совпадать с текущим `sequence`,
значения — только `up/down`. После исключения сети старый custom-набор может
перестать проходить генерацию. Пустой custom-набор не создаёт recovery ни для
одной строки. Генератор также **не запрещает recovery для all-up**; это обязанность
оператора при проектировании политики, а не существующая защита фильтра.

## 4. Где задаются параметры

Пути ниже относительно Kolla-Ansible. Пользовательские значения обычно задают
в `/etc/kolla/globals.yml`, адреса/интерфейсы отдельных узлов — в inventory,
`host_vars`/`group_vars`, секреты — в защищённом `/etc/kolla/passwords.yml`.
Действуют обычные правила приоритета Ansible; проверяйте итоговые значения,
особенно `-e`, словарные overrides и host-local `set_fact` роли Consul.

### 4.1. Топология и выбор сетей

| Переменная | База 0809 | Где используется / смысл |
| --- | --- | --- |
| `enable_consul` | `yes` в `group_vars/all.yml` | Включение роли/сервисов; не доказательство готовности |
| `enable_masakari`, `enable_masakari_hostmonitor` | `yes`; hostmonitor следует `enable_masakari` | Включение Masakari и нужного монитора; одного Consul недостаточно |
| `consul_management_enabled`, `consul_customer_enabled`, `consul_storage_enabled` | `true` через `default(true)` | Исходный `consul_networks.<net>.enabled`, затем per-host пересчёт |
| `consul_networks.<net>.datacenter` | По таблице сетей | `consul.hcl.j2:datacenter` |
| `.kolla_network`, `.address_override_var` | По таблице сетей | `bind_addr`, `advertise_addr`, адреса `retry_join` и agent endpoints |
| `.interface_var` | По таблице сетей | Только логика выбора сети; не прямая подстановка bind IP |
| `.server_group`, `.client_group` | `consul-<net>-server`, `consul-client` | Размещение и режим агента |
| `.server_group_extra` | `[]` | Ограничение реализации описано в разделе 2 |
| `.masakari_monitor`, `.masakari_name`, `.masakari_order` | `true`, имя и порядок из таблицы | Состав/порядок матрицы; `agent_<name>` в INI |
| `consul_min_server_count` | 3 | Precheck непустой server group |
| `consul_require_odd_server_count` | `true` | Precheck требует нечётное число servers |

Precheck пропускает size-check пустой server group, проверяет непустой адрес,
наличие gossip key и совпадение ключей `consul_services`/`consul_networks`.
Он не доказывает наличие leader, доступность BMC, готовность Nova или корректность
матрицы на всех мониторах. Gossip key проверяется на непустоту, не на валидность
base64/длину после декодирования. Не считайте комментарий «32-byte key» проверкой.

### 4.2. Тайминги и порты

| Переменная / поле | База 0809 | Результат и граница |
| --- | --- | --- |
| `masakari_hostmonitor_monitoring_interval` | 60 секунд | `[host] monitoring_interval` в `masakari-monitors.conf.j2` |
| `masakari_hostmonitor_monitoring_samples` | 1 | `[host] monitoring_samples` |
| `gossip_lan.probe_interval` | Литерал `1s` | Прямо в `consul.hcl.j2`, globals-переменной нет |
| `gossip_lan.probe_timeout` | Литерал `1s` | Там же; это ожидание ACK пробы, не всего recovery |
| `gossip_lan.suspicion_mult` | Литерал `6` | Там же; множитель, **не 6 секунд** |
| `consul_acl_token_ttl` | `30s` | ACL token cache; не детектор отказа compute |
| `consul_server_port` | 8300 | Server RPC, HCL `ports.server` |
| `consul_serf_lan_port` | 8301 | LAN gossip, также порт `retry_join` |
| `consul_serf_wan_port` | 8302 | WAN gossip server-агентов |
| `consul_http_port` | 8500 | HTTP API и endpoints hostmonitor |
| `consul_https_port`, `consul_dns_port`, `consul_grpc_port`, `consul_grpc_tls_port` | Все `-1` | Соответствующие listeners выключены в шаблоне |

По [документации OpenStack](https://docs.openstack.org/masakari-monitors/latest/configuration/sample-config.html),
`monitoring_samples` — последовательные наблюдения с одинаковым статусом перед
решением отправить уведомление. В образе надо проверить версию и реализацию
драйвера: эти настройки не означают несколько независимых голосующих узлов.

Полезная оценка задержки:

```text
T до начала эвакуации ≈ T gossip detection
                      + ожидание опроса и нужного числа samples
                      + доставка/приём уведомления и очередь engine
                      + получение lock и подтверждённый fencing
                      + ожидание Nova down
```

При периоде `I` и `S` последовательных опросах дополнительное ожидание обычно
оценивают как `[0, I] + (S-1)×I`, если статус стабилен, опросы успешны и драйвер
работает именно так. Это не SLA и не верхняя граница при timeout/retry/нагрузке.
`60 × 1` нельзя объявлять гарантированными 60 секундами до эвакуации.

Время suspicion зависит от размера кластера и probe interval; уменьшение
параметров повышает риск ложных отказов. HashiCorp рекомендует осторожность с
ручной настройкой gossip. [Описание параметров gossip](https://developer.hashicorp.com/consul/docs/reference/agent/configuration-file/gossip).

Параметры `power_timeout`, `stable_off_observations`, `nova_down_timeout`,
`evacuation_interval` относятся уже к Masakari PowerOps, не к Consul.
Их источники приведены в [общем справочнике](POWEROPS-CONFIGURATION.md).

### 4.3. Матрица и подключение hostmonitor

| Переменная | База 0809 | Результат |
| --- | --- | --- |
| `masakari_hostmonitor_driver` | `consul` в `group_vars/all.yml`; role default — `default` | `[host] monitoring_driver`; у активных globals приоритет над role default |
| `masakari_consul_matrix_policy` | `all_down` | Выбор политики генератора |
| `masakari_consul_down_threshold` | `null` | Обязателен для `threshold`, диапазон 1…N |
| `masakari_consul_custom_recovery_states` | `[]` | Точные состояния для `custom` |
| `masakari_hostmonitor_consul_use_loopback` | `true`, role default | Все активные `agent_*` получают `127.0.0.1:<http_port>` |
| `[consul] matrix_config_file` | `/etc/masakari-monitors/matrix.yaml` | Литерал в INI-шаблоне; отдельной globals-переменной нет |

Пример именуемых overrides, а **не рекомендация менять тайминги стенда**:

```yaml
masakari_hostmonitor_driver: "consul"
masakari_hostmonitor_monitoring_interval: 60
masakari_hostmonitor_monitoring_samples: 1
masakari_consul_matrix_policy: "all_down"
```

Для INI применяется `merge_configs` в таком порядке: Jinja-шаблон →
`{{ node_custom_config }}/global.conf` → `masakari/masakari-hostmonitor.conf` →
`masakari/masakari-monitors.conf` →
`masakari/{{ inventory_hostname }}/masakari-monitors.conf`.
Поздний override может изменить тайминги, endpoints или путь к матрице.
Сама матрица генерируется отдельной `template`-задачей, без этой цепочки merge.

### 4.4. Защита и образ

| Переменная | База 0809 | Назначение / ограничение |
| --- | --- | --- |
| `consul_client_addr` | `127.0.0.1` | Client listeners; не равен gossip bind/advertise |
| `consul_management_gossip_key`, `consul_customer_gossip_key`, `consul_storage_gossip_key` | Пустые значения в исходных defaults | Секреты сетей, HCL `encrypt`; при `consul_require_gossip_key=true` пустые отклоняются |
| `consul_require_gossip_key` | `true` | Precheck наличия ключа, не настройка ACL |
| `consul_acl_enabled` | `false` | Включает ACL-блок, но не создаёт токены |
| `consul_acl_default_policy` | `deny` | Политика ACL по умолчанию при включённых ACL |
| `consul_acl_down_policy` | `extend-cache` | Поведение ACL при недоступности ACL-источника |
| `consul_tls_enabled` | `false` | Вывод TLS-полей в HCL, не доставка сертификатов |
| `consul_tls_ca_file`, `consul_tls_cert_file`, `consul_tls_key_file` | `/etc/consul.d/ca.pem`, `consul.pem`, `consul-key.pem` | Пути внутри контейнера |
| `consul_tls_verify_incoming`, `consul_tls_verify_outgoing`, `consul_tls_verify_server_hostname` | Все `true` | Печатаются при включении TLS |
| `consul_log_level` | `INFO` | HCL `log_level` |
| `consul_tag` | `openstack_tag` | Tag образа; реальную версию проверять `consul version` |
| `consul_image`, `consul_image_full` | Registry/namespace/prefix + `consul` + tag | Источник контейнерного образа |
| `consul_dimensions` | `default_container_dimensions` | Ограничения ресурсов контейнера |
| `consul_config_owner` | `consul` | Владение скопированным конфигом и data directory |
| `masakari_monitors_image`, `masakari_monitors_tag`, `masakari_monitors_image_full` | Образ `masakari-monitors`, tag через `masakari_tag` | Отдельный образ hostmonitor; замена PowerOps engine image не доказывает обновление monitor |

## 5. Доставка конфигурации и ограничения текущей роли

Активны `consul.hcl.j2` и `consul.json.j2`. `config.yml` пишет конфиги в
`{{ node_config_directory }}/consul-<network>/`, обычно `/etc/kolla/...`.
Контейнер получает их через `{{ container_config_directory }}` и копирует HCL
в `/etc/consul.d/consul.hcl`; команда запуска —
`consul agent -config-dir=/etc/consul.d`.
Данные хранятся в отдельных volumes `kolla_consul_management`,
`kolla_consul_customer`, `kolla_consul_storage` → `/var/lib/consul`.

`deploy.yml` выполняет config, сравнение контейнеров, handlers.
`reconfigure.yml` включает `deploy.yml`: изменение конфига может вызвать
`recreate_or_restart_container`. Это не безобидное чтение настроек.
В `site.yml` роль использует `kolla_serial` (fallback `"0"`) и
`consul_max_fail_percentage` → `kolla_max_fail_percentage` → 100.
Это параметры раскатки, не задержки детектора отказа; данный fallback не задаёт
обязательный restart по одному server с проверкой quorum между перезапусками.
В этом пути нет полноценного доказательства работоспособности кластера после
перезапуска; отдельные файлы `check.yml` и `config_validate.yml` не становятся
автоматическими post-deploy проверками только из-за своего наличия.

Следующие ограничения подтверждены исходниками, но **не являются установленной
причиной какого-либо прежнего инцидента**:

1. **Одинаковый loopback для разных агентов.** Podman worker использует host
   network. При нескольких агентах на одном узле общий `127.0.0.1:8500`
   не разделяет три HTTP API; возможен конфликт bind. Три `agent_*` с таким
   адресом не доказывают наблюдение трёх независимых сетей. Нужны фактические
   listeners, адреса и datacenter каждого endpoint. Одного переключения
   `masakari_hostmonitor_consul_use_loopback=false` недостаточно, если Consul
   по-прежнему слушает только loopback. Проектирование раздельных listeners —
   отдельная доработка, не предлагается открывать все API на `0.0.0.0`.
2. **Идентичность узла.** Активный HCL использует `node_name=ansible_fqdn`.
   Переменная `consul_node_name` из defaults не используется этим шаблоном.
   Надо сопоставлять фактический FQDN с именами Nova и Masakari segment host.
3. **ACL не заканчиваются флагом.** В проверенных задачах нет bootstrap ACL,
   выдачи/доставки agent tokens и токена hostmonitor. Имена
   `consul_*_acl_token` упомянуты в комментарии, но не подключены к шаблону.
   Включение `consul_acl_enabled=true` само по себе не даёт готовую защищённую
   интеграцию. Keystone service-role это не исправляет: другой механизм.
4. **TLS-пути не равны файлам.** `consul.json.j2` копирует только HCL, а volumes
   роли не содержат отдельной доставки CA/cert/key в целевые пути. HTTP endpoints
   hostmonitor не переключаются автоматически на HTTPS. Требуется отдельно
   проверить доставку и поддержку TLS/ACL конкретным monitor-клиентом.
5. **HTTP check расходится с loopback default.** `tasks/check.yml` запрашивает
   `http://<network-address>:8500/v1/agent/self`, а `client_addr` по умолчанию
   loopback. Ошибка такого check может быть несовпадением адреса проверки,
   а не отсутствием работающего локального агента.
6. **Устаревшие параметры/шаблоны.** `masakari_consul_monitoring_interval=30`
   и `masakari_consul_monitoring_samples=3` определены, но активный INI-шаблон
   их не использует. `consul_server_bootstrap_expect` и `consul_datacenter`
   относятся к старым `consul-server.hcl.j2`/`consul-agent.hcl.j2`, которые
   `config.yml` не выбирает. Значение 3 в globals не меняет формулу активного
   `bootstrap_expect`. Gossip literals также не меняются придуманными globals.

## 6. Ручные проверки без изменения состояния

Команды выполняются на **доступном узле с hostmonitor/Consul**, не требуют SSH
на аварийный compute. Примеры для Linux/Bash и Podman; сначала найдите реальные
имена контейнеров. Не выводите полный HCL: в нём может быть gossip key.

```bash
sudo -n podman ps -a --format '{{.Names}} {{.Image}} {{.Status}}'
read -r -p 'Контейнер Consul: ' CONSUL_CONTAINER
timeout 20s sudo -n podman exec "$CONSUL_CONTAINER" consul version
timeout 20s sudo -n podman exec "$CONSUL_CONTAINER" consul validate /etc/consul.d
sudo -n ss -lntup
```

`validate` проверяет файл, не leader/quorum и не совпадение файла с памятью
агента. Его диагностический вывод при повреждённом HCL может включить фрагменты
конфига: храните локально, очищайте перед передачей.

Доставленный файл конфигурации hostmonitor и его матрица:

```bash
sudo -n podman exec masakari_hostmonitor python -B -m pip show masakari-monitors
sudo -n podman exec masakari_hostmonitor python -B -c 'import configparser; c=configparser.ConfigParser(interpolation=None); c.read("/etc/masakari-monitors/masakari-monitors.conf"); print({k:c.get("host",k,fallback="<not set>") for k in ("monitoring_driver","monitoring_interval","monitoring_samples")}); print({k:c.get("consul",k,fallback="<not set>") for k in ("agent_manage","agent_tenant","agent_storage","matrix_config_file")})'
sudo -n podman exec masakari_hostmonitor sed -n '1,160p' /etc/masakari-monitors/matrix.yaml
```

Если `matrix_config_file` переопределён, читайте тот путь. Файл внутри контейнера
ещё не доказывает, что процесс перечитал его; сопоставьте время старта процесса
и применения конфигурации. Повторите на каждом hostmonitor.

Выберите **один реальный** endpoint из конфигурации, задайте URL без credentials.
Ниже HTTP/без ACL допустим только для уже существующего такого локального
endpoint. При ACL/TLS используйте настроенный защищённый клиент/curl config,
не передавайте токены в аргументах и не отключайте проверки ради диагностики.

```bash
read -r -p 'Consul URL, например http://127.0.0.1:8500: ' CONSUL_URL
read -r -p 'Точное имя compute: ' HOST
curl -q --fail --silent --show-error --connect-timeout 5 --max-time 20 "$CONSUL_URL/v1/agent/self" | jq '{Config:(.Config | {NodeName,Datacenter,Server,Version}),Member:(.Member | {Name,Addr,Port,Status})}'
timeout 20s sudo -n podman exec "$CONSUL_CONTAINER" consul members -http-addr="$CONSUL_URL"
curl -q --fail --silent --show-error --connect-timeout 5 --max-time 20 "$CONSUL_URL/v1/status/leader"
curl -q --fail --silent --show-error --connect-timeout 5 --max-time 20 "$CONSUL_URL/v1/health/node/$HOST" | jq 'map({Node,CheckID,ServiceName,Status})'
```

Повторите для каждой сети и сравните `Datacenter`, `NodeName`, members и leader.
Пустой leader — повод проверить servers/quorum. `alive/failed` — наблюдение
конкретного агента, не power state. Пустой health-массив не доказывает исправность:
возможны неверное имя, сеть или ограничения доступа.
[Agent API](https://developer.hashicorp.com/consul/api-docs/agent),
[Status API](https://developer.hashicorp.com/consul/api-docs/status),
[Health API](https://developer.hashicorp.com/consul/api-docs/health).

Дальше на операторском узле с OpenStack CLI:

```bash
read -r -p 'Segment UUID: ' SEGMENT
timeout 30s openstack segment host list "$SEGMENT" -f json
read -r -p 'Masakari host UUID нужного compute: ' HA_HOST
timeout 30s openstack notification list --filters "source_host_uuid=$HA_HOST" --sort created_at:desc --limit 20 -f json
```

Сверьте время и host нового уведомления. `on_maintenance=true` может препятствовать
приёму нового host failure. Текущее maintenance не доказывает его значение до
отказа. Пустой список ВМ означает, что эвакуировать нечего, но не исключает
обнаружение отказа и fencing. Разбор notification, VMove, Ironic и Nova —
в [диагностике цепочки](POWEROPS-DIAGNOSTICS.md).

## 7. Что проверить перед изменением политики или таймингов

1. Сохранить текущие итоговые матрицы и безопасные поля конфигов всех мониторов.
2. Установить реальный состав сетей, server groups, listeners и независимость
   физических путей. Не принимать три одинаковых endpoint за три измерения.
3. Проверить роли monitor → Masakari и engine → Ironic/Nova, готовность etcd,
   доступность BMC и пригодность destination для эвакуации.
4. Согласовать допустимый отказ: одна сеть, большинство или полный разрыв.
   Более агрессивная матрица может вызвать fencing исправного compute при
   частичной сетевой аварии; `all_down` может оставить отказ одной сети без recovery.
5. Проверить шаблоны и полный вывод матрицы локально. Не считать синтаксический
   PASS доказательством правильного поведения установленного hostmonitor.
6. Reconfigure/restart выполнять отдельной согласованной операцией: они влияют
   на наблюдение отказов. Затем проверить каждый агент и монитор и провести
   контролируемый тест с зафиксированным состоянием **до** отключения сети.

В этом документе конфигурации не менялись, агенты не перезапускались и аварии
не моделировались. Подтверждённые по коду ограничения перечислены для дальнейших
решений, а не замаскированы под уже реализованную защиту.

## 8. Карта исходников

| Вопрос | Файл в Kolla0809 |
| --- | --- |
| Сети, базовые тайминги, ACL/TLS, порты | `ansible/group_vars/all.yml`, `etc/kolla/globals.yml` |
| Inventory и динамические группы | `ansible/inventory/multinode`, `ansible/site.yml` |
| Контейнеры, volumes, image | `ansible/roles/consul/defaults/main.yml` |
| Реальное определение enabled | `ansible/roles/consul/tasks/main.yml` |
| Precheck, доставка и restart | `ansible/roles/consul/tasks/{precheck,config,deploy,reconfigure,check-containers}.yml`, `handlers/main.yml` |
| HCL и container config | `ansible/roles/consul/templates/{consul.hcl,consul.json}.j2` |
| Проверки файла и HTTP | `ansible/roles/consul/tasks/{config_validate,check}.yml` |
| Генератор матрицы и tests | `kolla_ansible/masakari_consul.py`, `kolla_ansible/tests/unit/test_masakari_consul.py`, `ansible/filter_plugins/masakari_consul.py` |
| INI/матрица hostmonitor | `ansible/roles/masakari/templates/{masakari-monitors.conf,matrix.yaml,masakari-hostmonitor.json}.j2`, `tasks/config.yml` |
| Host networking Podman | `ansible/module_utils/kolla_podman_worker.py:prepare_container_args` |

При подготовке пройдены 11 unit tests генератора; отдельно таблица документа
сверена с `build_matrix`, отрендерены настоящие Jinja-шаблоны и проверено покрытие
28 верхнеуровневых Consul globals. 32 использованных файла Consul/Masakari
побайтно совпадают с архивом `0809`. Это локальные проверки исходников,
не запуск Consul, не тест quorum и не приёмка аварийного сценария.
