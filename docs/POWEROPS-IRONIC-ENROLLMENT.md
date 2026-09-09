# PowerOps: работа Ironic, Ansible-роли и операция enroll

Дата сверки: **9 сентября 2026 года**.

Документ описывает текущую поставку, прежде всего
`kolla-ansible-enroll-ironic-patch-3_0809.zip`, а не универсальную установку Ironic.
SHA-256 архива:
`b5958f14a09b1bdad4edc9c6b3dd092f4376b55dee9d5814fd2ad78fdffb1be9`.
Реальные overrides, образы и загруженные конфиги стенда могут отличаться.
`planned-return-v2` сюда не включён.

Связанные документы:

- [Общая архитектура и сценарии PowerOps](POWEROPS-OVERVIEW.md).
- [Ручная диагностика](POWEROPS-DIAGNOSTICS.md).
- [Конфигурации и тайминги](POWEROPS-CONFIGURATION.md).
- [Служебные пользователи, роли и авторизация](POWEROPS-AUTHENTICATION.md).

## 1. Для чего здесь нужен Ironic

Ironic используется как **сервис управления питанием уже установленных
compute-хостов через BMC**. Эти хосты уже работают как гипервизоры Nova.
Enrollment не устанавливает на них ОС и не превращает их в baremetal instances
Nova. Гостевые ВМ по-прежнему учитываются и перемещаются через обычную Nova.

| Компонент | Его работа в этой схеме |
| --- | --- |
| Kolla-Ansible, роль `ironic` | Доставка API/conductor, конфигов, регистрация Keystone, bootstrap БД и управление контейнерами |
| Kolla-Ansible, роль `ironic_enroll` | Создание/ограниченное обновление Ironic Node по BMC-описанию; доведение до `manageable` |
| Ironic API | Аутентификация, policy, приём запросов и предоставление состояния Node |
| Ironic conductor | Выбор и исполнение hardware interfaces, обращение к BMC, фоновые задачи и обновление состояния |
| BMC / Redfish / IPMI | Физическое управление питанием и получение его состояния независимо от ОС compute |
| Mistral PowerOps | Плановые операции, проверки Nova/Masakari, миграция/остановка ВМ, затем запрос питания |
| Masakari PowerOps | Аварийный fencing, подтверждение off, ожидание Nova down, затем эвакуация |

Ironic не принимает решение, безопасно ли выключать работающие ВМ. При прямом
обращении к его power API проверки и блокировки Mistral/Masakari не выполняются.
Поэтому прямой `baremetal power off` не является эквивалентом PowerOps workflow.

Управление идёт через Ironic API и BMC, **не через SSH на compute**. При этом
Ansible-доставка сама подключается к контроллерам; подготовка CA в enroll также
делегируется conductor-хостам с `become`. Это не проверка работоспособности ОС
аварийного compute и не зависимость аварийного fencing от SSH.

## 2. Что представляет собой Ironic Node

| Поле | Значение в PowerOps |
| --- | --- |
| `uuid` | Идентификатор Ironic Node; не UUID ВМ, Masakari host или segment |
| `name` | Каноническое имя исходного compute, полученное из `attached_host` |
| `driver` / `*_interface` | Реализации доступа к оборудованию и доступных операций |
| `driver_info` | Адрес BMC, credentials, Redfish System ID, настройки проверки BMC TLS |
| `extra.managed_by` | Метка `ansible`, по которой enroll допускает обновление существующей записи |
| `provision_state` | Состояние жизненного цикла Ironic; целевое для этой схемы — `manageable` |
| `power_state` | Известное Ironic состояние питания; не состояние ОС или Nova heartbeat |
| `target_power_state` | Целевое состояние текущей power-операции, если она выполняется |
| `maintenance`, `maintenance_reason`, `fault` | Собственный режим обслуживания/ошибки Ironic |
| `last_error` | Последняя ошибка операции Ironic; требует проверки вместе с остальными полями |
| `instance_uuid` | Связь с baremetal instance, если такая назначена; для power-only compute ожидается отсутствие связи |

Для одного физического compute должны совпадать **Nova `service.host`,
Masakari `host.name` и Ironic `node.name`**. Адрес BMC и IP управляющей сети —
другие сущности. Для стенда каноническое имя имеет вид
`ultra1-3.ultra1.test.pvs.un.sbt`.

Три независимых признака нельзя объединять в один:

- Masakari `on_maintenance=true` — состояние HA-обработки;
- Nova `disabled` — запрет планирования на compute;
- Ironic `maintenance=true` — состояние обслуживания самого baremetal Node.

`manageable` не означает «включён», «пуст», «Nova up» или «готов к эвакуации».
После планового выключения нормальна комбинация `manageable` + `power off`.

## 3. Как исполняется power-запрос

```text
Mistral / Masakari
        ↓ Keystone token, Ironic API request
Ironic API → RPC → conductor → hardware interface → BMC
        ↑              ↓
чтение Node ← сохранение состояния / ошибки
        ↓
повторные проверки PowerOps → следующий шаг workflow / recovery
```

Исполнение power-операции асинхронно: принятие API-запроса ещё не означает
физическое выключение. Conductor управляет оборудованием и обновляет запись.
В HA несколько conductors совместно обслуживают Nodes, используют распределение
по поддерживаемым драйверам и блокировки Ironic на время операций. Это не схема
«каждый из трёх conductors одновременно выключает каждый хост».
[Код Ironic stable/2025.1, ConductorManager](https://github.com/openstack/ironic/blob/stable/2025.1/ironic/conductor/manager.py).

Блокировка Node внутри Ironic не заменяет PowerOps lock всего процесса
обслуживания compute. Между Nova disable, миграцией, Ironic power-off и возвратом
есть несколько разных API-вызовов. Их согласование — ответственность PowerOps.

### Ironic работает и без нового PowerOps workflow

Conductor выполняет периодическую синхронизацию питания с BMC. При
`[conductor].force_power_state_during_sync=true` несовпадение состояний может
привести к приведению оборудования к состоянию из БД; при `false` обновляется
запись по фактическому состоянию оборудования. Доступность BMC проверяется
периодически; ошибки могут привести к Ironic maintenance с `fault=power failure`.
Для автоматической ошибки предусмотрена отдельная попытка восстановления;
ручной maintenance не снимается этим механизмом автоматически.
[Power synchronization, Ironic 2025.1](https://docs.openstack.org/ironic/2025.1/admin/power-sync.html).

В шаблоне 0809 опции power sync явно не заданы. Upstream defaults 2025.1:
`sync_power_state_interval=60` с, `force_power_state_during_sync=true`,
`power_state_sync_max_retries=3`, `sync_power_state_workers=8`.
Это **не подтверждение значений на стенде**: проверить установленную версию и
итоговую конфигурацию.
[Опции conductor 2025.1](https://docs.openstack.org/ironic/2025.1/configuration/config.html#conductor.force_power_state_during_sync).

В upstream 2025.1 `manageable` не входит в исключения power sync. Пропускаются,
в частности, Nodes с maintenance, выполняющейся power-операцией или reservation;
принудительное изменение дополнительно зависит от возможностей драйвера и
`disable_power_off`. Поэтому нельзя считать enrolled Node пассивной записью,
которая никогда не влияет на питание без workflow.
[Проверки power sync в исходниках](https://github.com/openstack/ironic/blob/stable/2025.1/ironic/conductor/manager.py).

Вывод для эксплуатации: включение узла вручную через BMC вне PowerOps требует
учёта power sync. Этот механизм не является автоматическим безопасным возвратом
аварийного compute в Nova/Masakari и не доказывает причину конкретного прошлого
выключения без соответствующих логов.

## 4. Что делает Ansible-роль `ironic`

Далее пути `ansible/...` и `kolla_ansible/...` указаны относительно Kolla0809.

### 4.1. Размещение и включение сервисов

`ansible/site.yml` запускает роль для групп Ironic при `enable_ironic=true`.
В поставляемом `ansible/inventory/multinode`:

- `ironic-api` и `ironic-conductor`: `ultra1-6`, `ultra1-7`, `ultra1-8`;
- `ironic-inspector`, `ironic-tftp`, `ironic-http`, `ironic-neutron-agent`,
  `nova-compute-ironic`: пустые группы.

Это конкретный inventory поставки, а не принудительное поведение роли.
В defaults роли TFTP и HTTP имеют `enabled=true`, но запускаются только на
сопоставленных inventory-хостах. `enable_ironic_inspector=no`; при этом
`enable_ironic_dnsmasq` по умолчанию следует `enable_ironic`, а dnsmasq привязан
к группе inspector. Отсутствие provisioning-сервисов обеспечивается сочетанием
флагов **и пустых групп**, а не одним переключателем `bmc-only`.

Наличие на стенде работающих `nova-compute` с именами `*-ironic` надо оценивать
отдельно. Оно не следует из показанного пустого `nova-compute-ironic` inventory
и не требуется для питания обычных compute через PowerOps.

### 4.2. Deploy/reconfigure: порядок и последствия

`ansible/roles/ironic/tasks/main.yml` выбирает файл по `kolla_action`.
`reconfigure.yml` импортирует **весь `deploy.yml`**, а не только рендеринг INI.

| Этап deploy | Файл / связанная роль | Что выполняется |
| --- | --- | --- |
| Регистрация | `register.yml` → `service-ks-register` | Service/endpoints, пользователи и назначения ролей при Keystone integration |
| Подготовка host | `config-host.yml` → `module-load` | Загрузка и сохранение `iscsi_tcp` на conductor-хостах; унаследованная часть общей роли |
| Конфигурация | `config.yml`, при необходимости `service-cert-copy` | Каталоги, `config.json`, INI, WSGI, policy overrides и сервисные сертификаты |
| Сравнение контейнеров | `check-containers.yml` → `service-check-containers` | Сравнение конфигурации контейнеров; уведомление restart handlers при изменениях |
| Dev mode | `clone.yml`, только при `ironic_dev_mode=true` | Подготовка исходников для dev-mode; не обычная пересборка образа |
| Bootstrap | `bootstrap.yml`, `bootstrap_service.yml` | Создание БД/пользователей при необходимости, одноразовый `bootstrap_ironic` с API image; дополнительные bootstrap по включённым сервисам |
| Применение | `handlers/main.yml` | `recreate_or_restart_container` для затронутых сервисов |
| Совместимость старого inspector | Конец `deploy.yml` | При соответствующем условии очистка старой цепочки iptables `ironic-inspector` |

Следовательно, `reconfigure` может менять регистрацию, выполнять bootstrap и
перезапускать контейнеры. Его нельзя считать безопасным read-only сбором.
Роль доставляет выбранные образы, но не устанавливает новую Sushy через pip
в ходе обычного enroll.

Другие действия роли:

- `precheck`: общие проверки сервисов, порты и условные требования inspector;
  не полная проверка BMC-парка.
- `pull`: `service-images-pull`, получение образов.
- `loadbalancer`: `loadbalancer-config`, конфигурация frontend/backend API.
- `config_validate`: `service-config-validate`, проверка конфигурации, не power test.
- `deploy-containers`: сравнение контейнеров и уведомление handlers, без полного
  deploy/bootstrap/enroll.
- `upgrade`: ожидание отсутствия provision states с `wait` (если не отключено),
  затем rolling/legacy ветка, bootstrap и перезапуски; rolling включает online
  data migration. Это не сценарий enroll и не гарантированный zero-downtime.
- `stop`: остановка сервисных контейнеров через `service-stop`, не штатное
  выключение физических compute.

### 4.3. Как получается итоговый `ironic.conf`

`config.yml` объединяет источники в таком порядке, от базового к более поздним:

```text
roles/ironic/templates/ironic.conf.j2
node_custom_config/global.conf
node_custom_config/ironic.conf
node_custom_config/ironic/<service-name>.conf
node_custom_config/ironic/<inventory_hostname>/ironic.conf
```

Результат сохраняется в `node_config_directory/<service-name>/ironic.conf`.
`config.json` задаёт доставку в `/etc/ironic/ironic.conf` внутри контейнера.
Поэтому исходный Jinja ещё не равен эффективной конфигурации.

Для conductor в Jinja0809 явно заданы:

- hardware types `ipmi,redfish`; power/management interfaces `ipmitool,redfish`;
- network/storage `noop`, inspect `no-inspect`, BIOS `no-bios`, RAID `no-raid`;
- console `no-console`, rescue `no-rescue`, firmware `no-firmware`, vendor `no-vendor`;
- boot `pxe`, deploy `direct` — необходимые реализации соответствующих families;
- `[conductor].automated_clean=false`.

Наличие `pxe` и `direct` здесь **не запускает PXE/deploy**. Текущая роль enroll
не вызывает `provide`, `deploy`, `clean`, `inspect` или `adopt`. Однако доступный
API и загруженные interfaces не являются аппаратным запретом этих операций:
граница power-only должна сохраняться в регламенте, policy и автоматизации.

## 5. Enroll — отдельная операция регистрации оборудования

`kolla-ansible enroll-ironic` зарегистрирована в `setup.cfg` через
`kolla_ansible.cli.commands:EnrollIronic` и запускает `ansible/enroll-ironic.yml`.
Обычный deploy роли `ironic` не импортирует этот playbook.

### 5.1. Входные данные

Основной источник BMC-описаний — `ironic_bmc_hosts` из globals. Схематический
пример с демонстрационным адресом, **не готовые данные стенда**:

```yaml
ironic_bmc_username: admin
ironic_bmc_hosts:
  bmc-compute-a:
    address: 192.0.2.20
    type: redfish
    attached_host: compute-a.example.invalid
    redfish_address: https://192.0.2.20
    redfish_system_id: /redfish/v1/Systems/1
```

| Поле | Как используется |
| --- | --- |
| Ключ `bmc-compute-a` | Логическое имя BMC в Ansible, не обязательно Ironic `node.name` |
| `address` | Непустой адрес BMC; для Redfish по умолчанию формируется `https://<address>` |
| `type` | Тип или комбинация типов через `+`; рекомендуется точное lowercase значение из mapping |
| `attached_host` | Имя Ironic Node; без явного значения используется имя BMC-записи |
| `redfish_address` | Необязательный URL с протоколом и портом; текущая проверка запрещает userinfo и путь после authority |
| `redfish_system_id` | Точный путь System; затем fallback к `ironic_bmc_default_redfish_system_id` / role default |
| `redfish_verify_ca` | Передаётся в `driver_info`; без override используется путь BMC CA внутри conductor |
| `ironic_bmc_username` | Общий пользователь BMC, default `admin`; для явно заданных BMC hostvars возможен локальный override |

`ironic-enroll-inventory.yml` добавляет в группу `bmc` только отсутствующие имена.
Если имя уже есть в `[bmc]`, поля из globals **не перезаписывают** существующую
запись. Необходимо устранить расхождения между inventory и globals заранее.
В автоматическом `add_host` из globals username берётся из общей переменной;
произвольное поле `username` внутри элемента не является поддержанным контрактом.

Есть и старый `contrib/inventory/ironic_bmc.py`, но штатная команда не требует
его вторым inventory: она уже строит runtime inventory. У старого скрипта другой
fallback System ID и другой способ переноса hostvars. Его `--host` возвращает
исходную запись, а `--list` фильтрует лишь часть полей. Не использовать его вывод
как гарантированно очищенный от секретов отчёт.

### 5.2. Два независимых вида аутентификации

1. **Ansible → Keystone/Ironic**: cloud `ironic_enroll_cloud`, default `kolla-admin`;
   interface `ironic_enroll_api_interface`, default `internal`;
   `OS_CLIENT_CONFIG_FILE={{ node_config }}/clouds.yaml`.
2. **Ironic conductor → BMC**: credentials, записанные enroll в `driver_info`.

Enrollment play задаёт `OS_SYSTEM_SCOPE=""`, чтобы унаследованный из shell
system scope не подменял project-scoped профиль. Это не очистка всех `OS_*`
переменных и не создание cloud-профиля. Кроме того, `interface=internal` выбирает
service endpoint, но не переписывает `auth_url` внутри cloud: в шаблоне
`kolla-admin` auth URL публичный, у `kolla-admin-internal` — внутренний.

При `enable_config_vault=false` BMC-пароли берутся из
`ironic_bmc_<type>_password`. При `true` playbook выбирает нужные имена
`vault_ironic_bmc_<type>_password`, запускает `vault-bootstrap-fetch.yml` и
использует transient mapping `vault_bootstrap_passwords`. Источник Vault должен
иметь AppRole-файлы; чтение делегируется `vault_bootstrap_host` либо выбранному
host из группы `baremetal`, требует соответствующего доступа и `become`.
Это не чтение пароля из отказавшего compute.

Пароли сейчас организованы **по типу BMC**, не как самостоятельный секрет для
каждого `attached_host`. Для комбинированного типа выбираются секреты всех
указанных поддерживаемых типов, а не только победившего драйвера.

### 5.3. Последовательность playbook

1. На localhost построить BMC runtime inventory и список нужных Vault secrets.
2. При Vault-режиме получить выбранные секреты во временные Ansible facts.
3. Отдельным несерийным play подготовить каталог и попытаться скопировать BMC CA
   на все хосты `ironic-conductor` из inventory.
4. Для BMC-группы выполнить локальный play с `gather_facts=false`,
   `connection=local`, `serial=25` по умолчанию.
5. `validate.yml`: собрать только нужные поля текущего BMC, проверить address,
   type и формат явного Redfish URL; не вычислять весь унаследованный `hostvars`.
6. `detect_driver.yml`: выбрать тип по mapping и приоритету, получить interfaces.
7. `resolve_passwords.yml`: выбрать BMC-пароли из нужного источника.
8. `enroll.yml`: сформировать native mapping `driver_info`, прочитать существующий
   Node, проверить границы, создать/обновить ресурс, выполнить `manage` при необходимости.
9. `verify.yml`: опрашивать `provision_state` до `manageable`, затем вывести summary.

Название `detect_driver` не означает сетевого autodiscovery: это выбор по
конфигурационной строке `type`. BMC не опрашивается для сравнения протоколов.

### 5.4. Драйвер и interfaces

| Тип в enroll | Hardware type | Power / management |
| --- | --- | --- |
| `redfish` | `redfish` | `redfish` / `redfish` |
| `ipmi` | `ipmi` | `ipmitool` / `ipmitool` |
| `ilo5` | `ilo` | `ilo` / `ilo` |
| `drac5` | `idrac` | `idrac` / `idrac` |
| `xclarity` | `xclarity` | `xclarity` / `xclarity` |
| `irmc` | `irmc` | `irmc` / `irmc` |

Приоритет default: `redfish → ilo5 → drac5 → xclarity → irmc → ipmi`.
Например, `ipmi+redfish` выбирает Redfish независимо от порядка в строке.
Если затем Redfish не работает, автоматического fallback на IPMI **нет**.
При составном `type` в `driver_info` могут попасть поля нескольких протоколов;
это также не механизм runtime fallback.

Mapping шире реально включённых `ipmi,redfish` в conductor Jinja0809.
Наличие типа в таблице не доказывает, что он загружен, совместим по всем families
и имеет нужные зависимости в образе.

При создании Node роль задаёт `provision_state=enroll`, `network_interface=noop`,
`storage_interface=noop`, `inspect_interface=no-inspect`, `bios_interface=no-bios`,
`raid_interface=no-raid`, `boot_interface=pxe`, `deploy_interface=direct`, выбранные
power/management interfaces и метки `extra` (`managed_by`, `enrollment_profile`,
`bmc_type`, `bmc_address`). Ports, portgroups и связь с Nova VM не создаются.

### 5.5. Состояния и повторный запуск

Для нового Node используется переход:

```text
создание Node → enroll → manage → verifying → manageable
                                             здесь enroll заканчивается
```

Во время `verifying` Ironic проверяет доступ через выбранные драйверы и credentials.
`manageable` — результат этого этапа, не `available` для выдачи baremetal workload.
[State machine 2025.1](https://docs.openstack.org/ironic/2025.1/user/states.html),
[enrollment 2025.1](https://docs.openstack.org/ironic/2025.1/install/enrollment.html).

| Найденное состояние | Поведение роли |
| --- | --- |
| Node не существует | Создать запись и продолжить state flow |
| Существующий `enroll`, `enroll failed`, `verifying`, `manageable` | Допустить только при `extra.managed_by=ansible` |
| Иное состояние, например `active` или `available` | Отказ до reconciliation; не переводить автоматически в power-only |
| `enroll` / `enroll failed` после чтения | Отправить `baremetal node manage --wait <timeout>` |
| `verifying` | Не отправлять новый manage; ждать `manageable` |
| `manageable` | Не отправлять manage; финальная проверка состояния |
| Manage вернул ошибку | Перечитать provision state и last_error; принять только текущий `verifying`/`manageable`, затем выполнить финальную проверку |

У существующего разрешённого Node `openstack.cloud.resource` имеет
`updateable_attributes: [driver_info]`. Поэтому повторный запуск может изменить
адрес/credentials BMC, но **не пересогласует `driver`, interfaces, name и `extra`**.
Смена `type` в globals не является миграцией уже созданного Node на другой драйвер.
Итоговый debug `driver` выводится из рассчитанной конфигурации, не из независимого
readback фактического Node: при таком расхождении summary может вводить в заблуждение.

Ошибка после создания не откатывает всё автоматически: Node может остаться
в Ironic, а часть BMC-парка — уже обработанной. Перед повторным запуском прочитать
состояние и last_error. `failed_when: false` у manage означает специальную проверку
гонки, а не безусловное игнорирование ошибки. Команды питания роль не отправляет.

## 6. Параметры enroll и реальные пределы ожиданий

Role defaults: `ansible/roles/ironic_enroll/defaults/main.yml`; часть значений
повторена в поставляемом `etc/kolla/globals.yml`.

| Параметр | Default | Что регулирует |
| --- | --- | --- |
| `ironic_enroll_cloud` | `kolla-admin` | Auth cloud для Ansible modules и CLI |
| `ironic_enroll_api_interface` | `internal` | Интерфейс Ironic API из каталога |
| `ironic_enroll_serial` | `25` | Размер BMC batch Ansible, не число одновременно работающих BMC-сессий |
| `ironic_enroll_throttle` | `10` | Ограничение параллелизма resource submission и manage tasks; фактически также ограничено forks/serial |
| `ironic_enroll_manage_timeout` | `300` с | Аргумент CLI `manage --wait`; не общий deadline playbook |
| `ironic_enroll_state_read_retries` / `ironic_enroll_state_read_delay` | `6` / `2` с | Повторы чтения provision state до успешного ответа CLI |
| `ironic_enroll_verify_retries` / `ironic_enroll_verify_delay` | `12` / `5` с | Финальные чтения до `manageable` |
| `ironic_enroll_bmc_ca_source` | Если не задан — `/etc/kolla/certificates/bmc-ca.pem` | Источник CA на Ansible runner, lookup/copy из `prepare.yml` |
| `ironic_enroll_bmc_ca_host_path` | `{{ node_config }}/certificates/bmc-ca.pem` | Назначение файла на conductor-хосте |
| `ironic_enroll_bmc_ca_container_path` | `/etc/ironic/bmc-ca.pem` | Строка пути в Redfish `driver_info`, не автоматический mount |
| `ironic_enroll_bmc_ca_owner` / `ironic_enroll_bmc_ca_group` | `root` / `root` | Владелец каталога/CA на host; CA mode `0644` |
| `ironic_bmc_default_redfish_system_id` / `ironic_enroll_default_system_id` | Пустая строка в globals / role defaults | Fallback System ID; непустой per-host `redfish_system_id` задаёт конкретную систему |
| `ironic_driver_priority` / `ironic_supported_bmc_types` | См. таблицу выше | Конфигурационный выбор драйвера, без проверки возможностей BMC |
| `ironic_enroll_mode` | `bmc-only` | Метка `extra.enrollment_profile`; не отдельный переключатель provisioning-сервисов |

Нет общего жёсткого deadline enroll: время включает Keystone, API/SDK, CLI,
очередь conductor и каждую попытку опроса. Вызовы чтения CLI не обёрнуты ролью
в shell `timeout`, а ресурс создаётся с `wait:false`. Нельзя считать верхнюю
границу равной `300 + 12 × 5` секунд или воспринимать throttle как rate limit.

Объявлены, но в проверенном исполняемом пути не используются как управляющие
условия: `ironic_enroll_overwrite_existing`, `ironic_enroll_allow_empty`,
`ironic_bmc_allow_empty`, `ironic_enroll_run_after_post_deploy`.
В частности, `overwrite_existing=false` не запрещает описанное обновление
`driver_info`, а `run_after_post_deploy=true` сам по себе не подключит enroll
к `post-deploy`. Пустая BMC-группа может закончиться без регистрации Nodes;
это не успешная проверка ожидаемого парка.

## 7. Текущие допущения и ограничения

Это ограничения текущей реализации, а не изменения, уже внесённые этим документом.

| Допущение | Что подтверждено исходниками / чего не хватает |
| --- | --- |
| Один BMC однозначно соответствует нужному compute | Роль доверяет `attached_host` и address; нет сверки с Nova/Masakari, hardware serial и физической коммутацией. Нет отдельной общей проверки уникальности BMC address / attached_host по всему batch |
| Inventory и globals согласованы | Уже существующий `[bmc]` не перезаписывается runtime inventory. Отсутствующий `attached_host` может дать неправильное имя Node |
| Все conductors готовы обслужить BMC | HA-размещение не проверяет сетевой маршрут, CA, версии драйвера и зависимости каждого conductor. Проверка одного API endpoint недостаточна |
| BMC CA доступен внутри контейнера | `prepare.yml` копирует файл только на host и подавляет ошибку copy (`failed_when:false`). В стандартных volumes и `ironic-conductor.json.j2` нет явной доставки этого BMC CA в `/etc/ironic/bmc-ca.pem`; нужен проверенный дополнительный mount/механизм доставки. Custom overrides могут уже решать это на стенде |
| Cloud для enroll уже существует | Play ожидает `node_config/clouds.yaml`. В Vault-режиме `post-deploy.yml` намеренно не создаёт cloud/openrc; получение BMC secrets не создаёт Keystone client profile. Полный transient auth-путь должен быть подготовлен отдельно |
| Секреты подходят конкретному оборудованию | Пароли выбираются по типу; отдельный per-node password override не реализован в основном пути. Direct-режим может передать пустой default; upstream/BMC затем отклонит доступ |
| `managed_by=ansible` означает разрешение на reconciliation | Это обычная метка `extra`, не криптографическое доказательство владения и не привязка к этой конкретной установке Ansible |
| Существующий Node уже соответствует power-only | Проверяются state и marker; роль не требует независимого readback всех interfaces, `instance_uuid`, allocation, maintenance и target power перед изменением `driver_info` |
| `manageable` подтверждает свежую валидность BMC credentials | Для уже manageable Node после обновления `driver_info` manage не повторяется; финал проверяет только state. Повторное полное подтверждение BMC-доступа этим не доказано |
| Enrollment не пересекается с обслуживанием хоста | Общей PowerOps coordination-блокировки и проверки активных workflow/notifications здесь нет. Не менять BMC mapping/credentials во время fencing, power-on/off, миграции и возврата |
| Ошибка не оставляет промежуточных изменений | Нет транзакционного rollback всего batch; часть Nodes/credentials/CA может быть уже изменена |
| Формально исправный Redfish endpoint совместим с SDK | Нужна совместимость payload с фактической Sushy в conductor. Отдельный удачный HTTP GET или значение `PowerState` не гарантирует корректного разбора всего ComputerSystem |
| Успех enroll достаточен для аварийной цепочки | Он не проверяет сервисные права Masakari/Mistral, Nova down, evacuation capacity, etcd lock, отсутствие stale domains или работоспособность ВМ |

С учётом этих допущений enroll — **изменяющая конфигурацию оборудования в Ironic
операция**, хотя сам playbook не содержит power-off/on. Ошибочный BMC mapping
опасен для последующих запросов питания и фоновых задач. Выполнять его как
безобидную диагностику живого парка нельзя.

`no_log` и redaction в resource rescue уменьшают риск утечки известных BMC-паролей,
но не гарантируют очистку любого CLI error или произвольного debug-дампа.
Не публиковать `driver_info`, полный inventory, токены или secrets из Vault.

## 8. Как выполнять и проверять enroll

### 8.1. До изменения

На управляющем хосте, где установлены нужная Kolla-Ansible, Ansible collection
`openstack.cloud`, OpenStack CLI с baremetal plugin и совместимый SDK:

1. Подтвердить установленную команду и путь поставки; явно выбрать свой inventory.
   Без `-i` команда использует packaged `multinode`, содержащий конкретные имена
   хостов поставки, а не автоматически актуальный inventory стенда.
2. Сверить BMC mapping, канонические имена и scope выбранного cloud-профиля.
3. Проверить доступ runner → Keystone/Ironic и всех conductors → нужные BMC,
   доставку CA и зависимости. Не выполнять пробное отключение.
4. Проверить отсутствие пересекающихся операций PowerOps и согласовать окно.
5. Для существующих Nodes заранее сверить driver/interfaces и ownership;
   не пытаться исправить неизвестную запись удалением и повторным созданием.

Проверка наличия команды без запуска playbook:

```bash
kolla-ansible enroll-ironic --help
```

После выполнения предварительных условий команда изменения выглядит так:

```bash
read -r -p 'Путь к проверенному inventory: ' POWEROPS_INVENTORY
kolla-ansible enroll-ironic -i "$POWEROPS_INVENTORY"
```

Она может обработать весь BMC inventory. Если используется `--limit`, проверить,
что он не исключил localhost/runtime inventory и необходимые bootstrap plays.
Подготовка CA всё равно делегируется conductor-группе из inventory. Не выдавать
`--check` за полноценную приёмку BMC/Keystone: отсутствие ошибок check mode не
заменяет выполнения реальных безопасных чтений.

### 8.2. После операции — read-only сверка конкретного Node

Команды на управляющем хосте с авторизованным OpenStack CLI. Указать UUID
проверяемого Ironic Node; никаких power/reset/manage-команд здесь нет:

```bash
read -r -p 'Ironic Node UUID: ' POWEROPS_IRONIC_NODE
timeout 30s openstack baremetal node show "$POWEROPS_IRONIC_NODE" -f yaml -c uuid -c name -c driver -c provision_state -c target_provision_state -c power_state -c target_power_state -c maintenance -c maintenance_reason -c last_error -c instance_uuid -c extra
timeout 30s openstack baremetal node show "$POWEROPS_IRONIC_NODE" -f yaml -c power_interface -c management_interface -c boot_interface -c deploy_interface -c inspect_interface -c network_interface -c storage_interface -c bios_interface -c raid_interface
timeout 30s openstack baremetal node validate "$POWEROPS_IRONIC_NODE"
```

Сверить `name`, `manageable`, нужные driver/interfaces, отсутствие нежелательной
instance association, перехода питания и ошибок. Отказ validate по неиспользуемой
deploy/boot-конфигурации нельзя автоматически трактовать как отказ power interface;
но и `power: True` не является физическим тестом выключения. Исследовать поля
power/management и сообщения отдельно, без добавления provisioning-данных «чтобы
все проверки стали зелёными».

При CA/Sushy-ошибке дополнительно проверить файл CA **внутри** каждой нужной
реплики conductor и версии установленных пакетов. При 401/403 установить,
на каком участке произошёл отказ: runner → Keystone/Ironic или conductor → BMC.
После успешного enroll отдельно проверить service-user доступ Mistral/Masakari
по документу авторизации.

Не продолжать общую upstream-инструкцию enrollment до `provide/available`,
cleaning, inspection или deploy: для существующих PowerOps compute эти шаги
находятся вне поддерживаемой операции.

## 9. Основания и граница проверки документа

Основные локальные исходники Kolla0809:

- `kolla_ansible/cli/commands.py:EnrollIronic`, `kolla_ansible/ansible.py`, `setup.cfg`;
- `ansible/enroll-ironic.yml`, `ansible/ironic-enroll-inventory.yml`,
  `ansible/vault-bootstrap-fetch.yml`, `ansible/post-deploy.yml`;
- все задачи и defaults `ansible/roles/ironic_enroll/`;
- задачи, defaults, handlers, `ironic.conf.j2` и `ironic-conductor.json.j2`
  роли `ansible/roles/ironic/`;
- `ansible/inventory/multinode`, `ansible/group_vars/all.yml`,
  `etc/kolla/globals.yml`, `contrib/inventory/ironic_bmc.py`;
- тесты `kolla_ansible/tests/unit/test_ironic_enroll_*.py`.

При подготовке документа 60 использованных файлов побайтно сверены с архивом
0809. Проверены Markdown-ссылки, Bash/YAML-примеры и разбор OpenStack CLI-команд
без доступа к сети. Прямым запуском прошли 8 локальных тестов environment,
validation, inventory и password resolution. Это не полный Kolla test suite:
пакетный запуск в локальном окружении ограничен отсутствующим `pbr`;
команда Kolla enroll сверена по исходникам, на стенде не выполнялась.

Сверка кода показывает, какие действия предусмотрены и какие проверки отсутствуют.
Она не подтверждает фактический mount CA, Keystone assignments, текущий Node,
совместимость BMC, безопасное изменение питания или завершение evacuation на стенде.
