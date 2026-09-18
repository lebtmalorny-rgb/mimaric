# Администрирование OpenStack через CLI

Практическое руководство для администраторов PVS

Версионная основа OpenStack 2025.1 Epoxy

Редакция 1 от 18 сентября 2026 года

[Версия для Word](OPENSTACK_CLI_ADMIN_GUIDE_2025.1.docx)

Руководство описывает работу через API OpenStack: проверку состояния облака, управление ресурсами и доступом, обслуживание вычислительных узлов и разбор ошибок. Основной набор — Keystone, Nova, Neutron, Glance, Cinder, Placement, Mistral, Masakari и Watcher. Ironic включён отдельным разделом для управления физическими узлами.

Для каждой изменяющей операции сначала проверяют объект и область доступа, затем выполняют команду и подтверждают итоговое состояние. Успешное принятие запроса API ещё не означает завершение фоновой операции. При обрыве связи состояние проверяют по UUID, прежде чем повторять запрос.

## Границы применимости

Синтаксис основных примеров сверен с исходниками клиентов указанной ниже версии и официальной документацией. Команды в действующем облаке не выполнялись. Установленные версии серверов, их API microversion, политики, endpoint и включённые расширения требуют проверки на площадке.

| Клиент | Основа проверки |
| --- | --- |
| python-openstackclient | 7.4.0 |
| python-mistralclient | 5.4.0 |
| python-masakariclient | 8.6.0 |
| python-watcherclient | 4.8.0 |
| python-ironicclient | 5.10.0 |
| osc-placement | Документация ветки 2025.1 |

Эти версии задают основу примеров, а не требование устанавливать старые пакеты в новое окружение. Для эксплуатации нужен согласованный набор клиентов и зависимостей вашей поставки. В локальном архиве PVS значение openstack_release задано как latest; оно само по себе не подтверждает версию развёрнутого облака.

## Содержание

- [1 Подготовка рабочего места](#1-подготовка-рабочего-места)
- [2 Аутентификация и обращение с секретами](#2-аутентификация-и-обращение-с-секретами)
- [3 Первичная проверка облака](#3-первичная-проверка-облака)
- [4 Keystone и управление доступом](#4-keystone-и-управление-доступом)
- [5 Nova и жизненный цикл виртуальных машин](#5-nova-и-жизненный-цикл-виртуальных-машин)
- [6 Nova и обслуживание вычислительных ресурсов](#6-nova-и-обслуживание-вычислительных-ресурсов)
- [7 Neutron и сетевые ресурсы](#7-neutron-и-сетевые-ресурсы)
- [8 Neutron и правила доступа](#8-neutron-и-правила-доступа)
- [9 Glance и образы](#9-glance-и-образы)
- [10 Cinder и блочное хранилище](#10-cinder-и-блочное-хранилище)
- [11 Placement и диагностика размещения](#11-placement-и-диагностика-размещения)
- [12 Mistral и запуск workflow](#12-mistral-и-запуск-workflow)
- [13 Mistral и разбор выполнения](#13-mistral-и-разбор-выполнения)
- [14 Masakari и объекты HA](#14-masakari-и-объекты-ha)
- [15 Masakari и обслуживание хоста](#15-masakari-и-обслуживание-хоста)
- [16 Watcher и подготовка аудита](#16-watcher-и-подготовка-аудита)
- [17 Watcher и выполнение плана](#17-watcher-и-выполнение-плана)
- [18 Ironic и физические узлы](#18-ironic-и-физические-узлы)
- [19 Типовые ошибки и сбор доказательств](#19-типовые-ошибки-и-сбор-доказательств)
- [20 Источники и правила актуализации](#20-источники-и-правила-актуализации)
- [21 Локальная основа и проверка перед применением](#21-локальная-основа-и-проверка-перед-применением)

## 1 Подготовка рабочего места

### Клиент и плагины

Команду openstack предоставляет python-openstackclient. Mistral, Masakari и Watcher добавляют собственные команды через плагины. Наличие плагина на рабочем месте не означает наличие сервиса в облаке. [1–4]

Устанавливайте клиенты в отдельное виртуальное окружение на административной машине. Файл requirements-openstack-cli.txt должен содержать согласованные версии пакетов; constraints.txt — проверенные ограничения зависимостей поставки. Следующий пример предполагает, что оба файла уже подготовлены.

```sh
python3 -m venv .venv-openstack
. .venv-openstack/bin/activate
python -m pip install -c constraints.txt \
  -r requirements-openstack-cli.txt
python -m pip check
openstack --version
python -m pip list
```

Состав requirements: python-openstackclient, python-mistralclient, python-masakariclient, python-watcherclient, python-ironicclient и osc-placement.

### Проверка регистрации команд

```sh
openstack help server list
openstack help workflow execution create
openstack help segment host update
openstack help optimize audit create
openstack help resource provider list
```

Результат — справка по команде, без обращения к управляемому ресурсу. Сообщение «is not an openstack command» означает проблему имени команды, установки или загрузки плагина; смена ролей Keystone такую ошибку не исправляет.

### Условные обозначения

Примеры рассчитаны на bash или zsh. Переменные PROJECT_ID, SERVER_ID, VOLUME_ID и другие обозначают UUID заранее выбранных объектов; HOST — точное имя службы Nova, а не произвольный DNS-псевдоним. До запуска задайте нужные переменные и проверьте их командой show. Используйте UUID при совпадающих именах. Значения в угловых скобках заменяют своими, вместе со скобками.

Коды возврата, таблицы и названия колонок зависят от версии. Для автоматизации предпочтителен JSON и явная проверка обязательных полей. Команды из разных блоков не предназначены для запуска одним общим скриптом.

## 2 Аутентификация и обращение с секретами

### Профиль clouds yaml

Храните несекретные параметры в ~/.config/openstack/clouds.yaml. Ниже — шаблон project scope; endpoint, домены, проект и регион замените данными площадки. Путь cacert должен указывать на доверенную цепочку CA. [1]

```yaml
clouds:
  pvs-admin:
    auth_type: password
    auth:
      auth_url: https://keystone.example.org:5000/v3
      username: operator
      user_domain_name: PVS
      project_name: admin-project
      project_domain_name: PVS
    region_name: RegionOne
    interface: internal
    identity_api_version: 3
    cacert: /etc/ssl/certs/pvs-ca.pem
```

Пароль вводите через интерактивный запрос клиента либо утверждённый механизм выдачи секретов. Если допустим secure.yaml, используйте ~/.config/openstack/secure.yaml с тем же именем профиля и auth.password, правами 0600 и каталогом 0700. Этот файл хранит пароль открытым текстом.

```sh
export OS_CLOUD=pvs-admin
openstack token issue -c expires -c project_id -c user_id
openstack catalog list
```

Пример token issue не выводит сам токен. Перед сменой профиля проверьте конфликты с ранее загруженным openrc и переменными OS_*. Полный environment и отладочные трассы могут раскрыть секреты.

### Область полномочий

Project, domain и system scope не взаимозаменяемы. Project admin не подтверждает право на все операции. Для system scope используйте отдельный профиль с auth.system_scope: all без полей проекта; проверьте поддержку scope сервисом и выданную роль.

В PVS virtualization_admin сопоставляется с admin, vm_developer — с member. Запрет удаления, остановки или snapshot определяется policy, а не именем роли. Учётные записи и членство read-only AD/LDAP меняют в каталоге, проектные назначения — в Keystone. Роли LCMP, гостевой ОС, Grafana и OpenSearch относятся к другим системам. [8]

### Vault и технические учётные записи

OpenStack CLI получает Keystone credentials или токен; установленный клиент сам по себе не умеет автоматически разрешать ссылки Vault из конфигурации PVS. Используйте утверждённую интеграцию выдачи учётных данных. Не копируйте серверные service credentials, root token Vault или AppRole SecretID в clouds.yaml оператора.

Application credentials подходят для разрешённых проектных сценариев, но не заменяют system scope. Ограничьте роли и срок, проверьте поддержку нужных API. Пароли, токены и payload секретов не передавайте в аргументах команд, тикетах и shell history. После завершения сессии удалите временные секретные файлы по регламенту и завершите административную оболочку.

## 3 Первичная проверка облака

Сначала убедитесь, что выбран правильный проект, регион и интерфейс endpoint. Затем проверьте регистрацию сервисов и их рабочие состояния. Каталог показывает адреса API; доступность каталога не доказывает здоровье compute, storage или сети.

```sh
openstack catalog list
openstack service list
openstack endpoint list
openstack compute service list
openstack hypervisor list
openstack network agent list
openstack volume service list
openstack availability zone list
openstack quota show "$PROJECT_ID"
```

Для service list, endpoint list и межпроектных выборок могут требоваться административные права. В Nova различайте административный Status enabled/disabled и наблюдаемый State up/down. В Cinder проверяйте отдельно scheduler и volume backend. Набор Neutron agents зависит от механизма сети; в OVN он отличается от классического OVS с L3/DHCP agents.

### Проверка дополнительных подсистем

```sh
openstack workflow engine service list
openstack segment list
openstack notification list
openstack optimize service list
openstack optimize audit list
openstack optimize actionplan list
```

Сравните найденные службы с ожидаемым составом площадки. Пустой список может означать отсутствие объектов, неподходящий scope, фильтр или недоступные оператору ресурсы. Ответ API 200 и пустая таблица не являются полной проверкой сервиса.

### Снимок перед изменением

Сохраните сведения только об объектах изменения в защищённом рабочем каталоге. JSON может содержать адреса, metadata и чувствительные поля; ограничьте доступ и срок хранения. Пример ниже не является резервной копией ВМ.

```sh
umask 077
mkdir -p change-evidence
openstack server show "$SERVER_ID" -f json \
  > change-evidence/server-before.json
openstack port list --server "$SERVER_ID" -f json \
  > change-evidence/ports-before.json
openstack volume show "$VOLUME_ID" -f json \
  > change-evidence/volume-before.json
```

В записи изменения укажите время UTC, оператора, облако и регион, UUID ресурсов, исходное состояние, ожидаемый результат и условия прекращения. Не собирайте все проекты и секреты для диагностики одного объекта.

## 4 Keystone и управление доступом

### Поиск объектов и эффективных назначений

```sh
openstack domain list
openstack project list --domain "$DOMAIN_ID"
openstack project show "$PROJECT_ID"
openstack user list --domain "$DOMAIN_ID"
openstack group list --domain "$DOMAIN_ID"
openstack role list
openstack role assignment list --project "$PROJECT_ID" \
  --user "$USER_ID" --effective --names
```

Проверяйте домен пользователя отдельно от домена проекта. Эффективные назначения помогают учитывать группы и наследование; доступ к конкретному API дополнительно определяется policy сервиса. После отзыва доступа учитывайте ранее выданные токены, механизм отзыва и кэширование; проверяйте новую и действующую сессию.

### Выдача и отзыв роли на проект

Условие: UUID пользователя, проекта и роли проверены; выдаваемое право согласовано. Для пользователя из AD не создавайте одноимённого локального пользователя вместо поиска существующего.

```sh
openstack role add --user "$USER_ID" \
  --project "$PROJECT_ID" "$ROLE_ID"
openstack role assignment list --user "$USER_ID" \
  --project "$PROJECT_ID" --effective --names
```

Для группового назначения используйте --group вместо --user. Проверку фактического доступа выполните с новой сессией получателя прав; административная сессия не воспроизводит его полномочия. Отзыв прямого назначения:

```sh
openstack role remove --user "$USER_ID" \
  --project "$PROJECT_ID" "$ROLE_ID"
```

Если доступ сохранился, проверьте групповые и унаследованные назначения, role implication и ранее выданные токены. Не удаляйте роль целиком для отзыва одного назначения.

### Проект и квоты

Следующий пример создаёт новый проект в выбранном домене. Создание проекта само по себе не добавляет пользователей, сеть, образы или ресурсы.

```sh
openstack project create --domain "$DOMAIN_ID" \
  --description "Administrative test project" cli-lab
```

Сохраните UUID созданного проекта как PROJECT_ID, затем проверьте и установите его квоты.

```sh
openstack quota show "$PROJECT_ID"
openstack quota set --instances 10 --cores 40 \
  --ram 81920 "$PROJECT_ID"
openstack quota show "$PROJECT_ID"
```

Перед quota set сохраните прежние значения и оцените уже занятый объём. RAM задаётся в MiB. Квоты Nova, Neutron и Cinder относятся к разным сервисам; принятые квоты не гарантируют физическую ёмкость. Для возврата установите записанные значения. Удаление проекта не является штатным способом очистки его ВМ, томов и сетей.

## 5 Nova и жизненный цикл виртуальных машин

### Инвентаризация и диагностика

```sh
openstack server list --all-projects --long
openstack server list --all-projects --host "$HOST"
openstack server show "$SERVER_ID"
openstack server event list "$SERVER_ID"
openstack server migration list --server "$SERVER_ID"
openstack console log show --lines 100 "$SERVER_ID"
```

Проверьте status, fault, task_state, проект, flavor, порты, подключённые тома и текущий хост, если эти поля доступны роли. Для события возьмите request ID из списка и выполните server event show. Консоль гостевой ОС может содержать секреты; перед передачей её вывод нужно проверить.

```sh
openstack server event show "$SERVER_ID" "$REQUEST_ID"
```

### Создание тестовой ВМ

Условие: существует согласованный тестовый проект, доступный образ, flavor и сеть; заданы IMAGE_ID, FLAVOR_ID, NETWORK_ID, SECURITY_GROUP_ID и KEYPAIR_NAME. Проектный профиль должен указывать на этот проект. В примере используется ephemeral root из образа.

```sh
openstack image show "$IMAGE_ID"
openstack flavor show "$FLAVOR_ID"
openstack network show "$NETWORK_ID"
openstack server create --image "$IMAGE_ID" \
  --flavor "$FLAVOR_ID" --network "$NETWORK_ID" \
  --security-group "$SECURITY_GROUP_ID" \
  --key-name "$KEYPAIR_NAME" --wait cli-test-vm
```

Запишите выданный UUID как SERVER_ID. Проверьте ACTIVE, отсутствие task_state и доступность приложения по разрешённой сети. При ERROR исследуйте fault, event и состояние ресурсов; повторное create может породить вторую ВМ.

### Остановка и запуск

Остановка прерывает работу гостевой ОС и приложений. Сначала согласуйте остановку и сохранность данных. Команды возвращаются до завершения перехода; проверяйте состояние отдельным show.

```sh
openstack server stop "$SERVER_ID"
openstack server show "$SERVER_ID"
openstack server start "$SERVER_ID"
openstack server show "$SERVER_ID"
```

Ожидаемые состояния: SHUTOFF после остановки и ACTIVE после запуска. Reboot не является лечением неизвестного состояния Nova. Для удаления используйте server delete только после проверки UUID, резервного копирования и политики удаления подключённых томов; этот шаг необратим для данных без сохранённой копии.

## 6 Nova и обслуживание вычислительных ресурсов

### Запрет нового размещения

```sh
openstack compute service list --host "$HOST"
openstack compute service set --disable \
  --disable-reason "CHG maintenance" "$HOST" nova-compute
openstack compute service list --host "$HOST"
```

Ожидается Status disabled. Команда не останавливает уже работающие ВМ, не выключает узел и не включает maintenance в Masakari. Она также не является общей блокировкой любых внешних операций над хостом. Перед работами согласуйте Watcher, HA и плановые workflow.

### Живая миграция одной ВМ

Условие: ВМ ACTIVE без текущей задачи; источник и назначение исправны; сеть, storage и CPU совместимы, ёмкости достаточно. Сначала проверьте ограничения flavor, passthrough, pinned CPU, NUMA и локальных дисков. Для явного --host нужна compute microversion не ниже 2.30. [5]

```sh
openstack server show "$SERVER_ID"
openstack --os-compute-api-version 2.30 server migrate \
  --live-migration --host "$DEST_HOST" --wait "$SERVER_ID"
openstack server migration list --server "$SERVER_ID"
openstack server show "$SERVER_ID"
```

Пример применим только если сервер поддерживает 2.30; в другом случае выберите согласованную поддерживаемую microversion. Начиная с 2.25 Nova может определить режим block/shared автоматически. Не подставляйте --block-migration без проверки storage. Результат: migration завершена, хост назначения изменился, ВМ ACTIVE, task_state отсутствует и приложение доступно. Потеря ответа --wait требует проверки, а не немедленной повторной миграции.

### Изменение размера

Resize может прервать работу ВМ. Проверьте доступность нового flavor и его свойства. После перехода в VERIFY_RESIZE протестируйте гостевую ОС и приложение; затем выберите ровно одно действие — confirm или revert.

```sh
openstack server resize --flavor "$NEW_FLAVOR_ID" \
  --wait "$SERVER_ID"
openstack server show "$SERVER_ID"
openstack server resize confirm "$SERVER_ID"
```

Альтернатива последней команде до подтверждения — openstack server resize revert "$SERVER_ID". Проверьте политику автоматического подтверждения на площадке.

### Возврат узла и аварийное восстановление

После проверки оборудования, Nova, storage, сети и HA разрешите размещение командой compute service set --enable "$HOST" nova-compute. Порядок снятия maintenance описан в разделе 15.

Evacuate предназначена для восстановления ВМ с отказавшего узла. До неё требуется подтверждённое fencing источника и исключение конкурирующего восстановления Masakari. Heartbeat down сам по себе не доказывает выключение узла. Для планового исправного хоста используйте согласованную миграцию; подробный аварийный runbook зависит от storage и реализации fencing площадки.

## 7 Neutron и сетевые ресурсы

### Проверка пути подключения ВМ

```sh
openstack network list
openstack subnet list --network "$NETWORK_ID"
openstack port list --server "$SERVER_ID"
openstack port show "$PORT_ID"
openstack router list
openstack floating ip list
openstack network agent list
```

Для порта сопоставьте network_id, fixed_ips, device_id, MAC, status, binding_host_id и security_group_ids. Значение ACTIVE не доказывает прохождение трафика внутри гостя. Диагностику продолжайте по цепочке: интерфейс гостя → порт → subnet → router → внешняя сеть → обратный маршрут. Отсутствие ICMP-ответа отдельно от TCP-проверки не доказывает недоступность приложения.

### Создание проектной сети

Условие: выбран правильный проект; CIDR не пересекается с его маршрутами; проверены правила IPAM. Пример использует документационный диапазон, который нужно заменить выделенным диапазоном площадки.

```sh
openstack network create cli-lab-net
```

Сохраните UUID созданной сети как NETWORK_ID и создайте subnet.

```sh
openstack subnet create --network "$NETWORK_ID" \
  --subnet-range 192.0.2.0/24 --gateway 192.0.2.1 \
  --dhcp cli-lab-subnet
openstack subnet list --network "$NETWORK_ID"
```

DNS-серверы задавайте только значениями площадки. Provider network требует согласования physical network, VLAN и ML2 mapping; произвольное создание такой сети в административном проекте не гарантирует связность.

### Маршрутизатор и внешняя сеть

Создайте router, сохраните ROUTER_ID и SUBNET_ID. EXT_NETWORK_ID должен указывать на разрешённую external network.

```sh
openstack router create cli-lab-router
openstack router add subnet "$ROUTER_ID" "$SUBNET_ID"
openstack router set --external-gateway "$EXT_NETWORK_ID" \
  "$ROUTER_ID"
openstack router show "$ROUTER_ID"
```

Проверяйте router interfaces, gateway и фактический маршрут. Для очистки сначала удалите floating IP и зависимые подключения, затем снимите gateway, удалите интерфейс subnet, router, subnet и сеть. Перед каждым удалением убедитесь, что ресурс принадлежит созданному тестовому набору и не используется другими ВМ.

## 8 Neutron и правила доступа

### Security groups

Security group применяется к портам. Сначала выясните, к какому порту привязано правило и включена ли port security. Пример разрешает SSH только из согласованной административной подсети ADMIN_CIDR.

```sh
openstack security group list
openstack security group show "$SECURITY_GROUP_ID"
openstack security group rule list "$SECURITY_GROUP_ID"
openstack security group rule create \
  --protocol tcp --dst-port 22 --remote-ip "$ADMIN_CIDR" \
  "$SECURITY_GROUP_ID"
openstack port set --security-group "$SECURITY_GROUP_ID" \
  "$PORT_ID"
openstack port show "$PORT_ID"
```

В клиенте 7.4.0 port set --security-group добавляет группу к существующим; без --no-security-group прежние назначения сохраняются. Перед изменением запишите исходный набор, после — проверьте итоговый. Для IPv6 создайте отдельное правило с --ethertype IPv6 и IPv6 CIDR. Remote group означает адреса членов указанной группы, а не рекурсивное наследование её правил.

Для отзыва конкретного правила используйте его UUID:

```sh
openstack security group rule delete "$RULE_ID"
openstack security group rule list "$SECURITY_GROUP_ID"
```

### Floating IP

Условие: у ВМ есть порт во внутренней сети и путь через router к external network. Создание выделяет адрес; связывание публикует разрешённые security group входящие подключения.

```sh
openstack floating ip create "$EXT_NETWORK_ID"
openstack floating ip set --port "$PORT_ID" "$FIP_ID"
openstack floating ip show "$FIP_ID"
```

После проверки назначенного адреса протестируйте разрешённый TCP-порт с нужной внешней точки. Для отмены публикации выполните floating ip unset --port "$FIP_ID" и проверьте отвязку; delete дополнительно освобождает адрес из пула.

### Разбор отсутствия связности

Если порт DOWN, проверьте состояние ВМ, привязку к хосту и механизм сети. Если порт ACTIVE, но DHCP не работает, проверьте subnet, DHCP-настройки, агенты или OVN и интерфейс гостя. Если внутренний трафик работает, а внешний нет, исследуйте gateway, floating IP, external network и обратную маршрутизацию. Не отключайте port security или все security groups как постоянное исправление.

Изменения MTU, provider mapping, bridge и маршрутов на узлах выходят за рамки API CLI. Они требуют отдельной процедуры с проверкой влияния на остальные проекты.

## 9 Glance и образы

### Инвентаризация и проверка образа

```sh
openstack image list --long
openstack image show "$IMAGE_ID"
```

Проверяйте owner, visibility, status, disk_format, container_format, min_disk, min_ram, size и checksum или os_hash_value/os_hash_algo при наличии. Образ в состоянии active доступен для использования согласно policy, но не обязательно загружается с любым flavor и типом firmware.

### Загрузка приватного образа

Условие: файл получен из доверенного источника, его контрольная сумма проверена, формат соответствует содержимому и достаточно квоты. Имя образа не является уникальным идентификатором.

```sh
openstack image create --file ./approved-image.qcow2 \
  --disk-format qcow2 --container-format bare \
  --private --min-disk 10 --min-ram 1024 cli-approved-image
```

Сохраните UUID и дождитесь active через image show. Затем создайте тестовую ВМ, проверьте загрузку и драйверы. До успешной проверки не публикуйте образ для всех проектов.

### Защита и публикация

```sh
openstack image set --protected "$IMAGE_ID"
openstack image show "$IMAGE_ID"
```

Protected защищает от обычного удаления через API, но не заменяет резервное копирование backend. Для выдачи образа определённому проекту используйте shared visibility и membership, если это разрешено поставкой:

```sh
openstack image set --shared "$IMAGE_ID"
openstack image add project "$IMAGE_ID" "$TARGET_PROJECT_ID"
```

Затем оператор целевого проекта принимает членство своим проектным профилем:

```sh
openstack image set --accept "$IMAGE_ID"
```

Проверьте видимость в новой сессии целевого проекта. Public visibility открывает образ всем проектам и требует отдельного согласования. Удаление образа не равно удалению всех уже созданных из него ВМ; перед очисткой проверьте зависимости, требования к rebuild и правила хранения.

## 10 Cinder и блочное хранилище

### Состояние сервиса и томов

```sh
openstack volume service list
openstack volume backend pool list --long
openstack volume type list --long
openstack volume list --all-projects --long
openstack volume show "$VOLUME_ID"
openstack volume snapshot list --all-projects
```

Проверяйте status, attachments, тип тома, availability zone, backend и размер. Состояние сервиса up не доказывает исправность каждого пула. Тип тома связан с backend через extra specs; имя типа само по себе не подтверждает шифрование или репликацию.

### Создание и подключение

Условие: выбран проект ВМ, доступный VOLUME_TYPE и нужная зона. Размер задаётся в GiB.

```sh
openstack volume create --size 20 --type "$VOLUME_TYPE" \
  cli-data-volume
```

Сохраните VOLUME_ID и дождитесь available. Затем подключите том:

```sh
openstack server add volume "$SERVER_ID" "$VOLUME_ID"
openstack volume show "$VOLUME_ID"
openstack server volume list "$SERVER_ID"
```

Ожидается in-use и attachment к нужной ВМ. Разметку, файловую систему и mount выполняют внутри гостя отдельной процедурой. Перед отключением остановите ввод-вывод и размонтируйте устройство внутри гостя; затем используйте server remove volume "$SERVER_ID" "$VOLUME_ID" и дождитесь available.

### Snapshot и backup

Snapshot не является независимой резервной копией backend. Для согласованности данных остановите запись или используйте согласованный механизм quiesce. Пример ниже предназначен для тома available.

```sh
openstack volume snapshot create --volume "$VOLUME_ID" \
  cli-data-snapshot
openstack volume snapshot show "$SNAPSHOT_ID"
openstack volume backup create --name cli-data-backup \
  "$VOLUME_ID"
openstack volume backup show "$BACKUP_ID"
```

BACKUP_ID и SNAPSHOT_ID берут из результатов create. Backup требует настроенного cinder-backup и целевого хранилища. Подтверждайте available и периодически проверяйте восстановление в отдельный том. Расширение тома не расширяет автоматически файловую систему гостя. Reset-state меняет запись API, а не исправляет storage; не используйте его для снятия неизвестного attachment или обхода ошибки без расследования.

## 11 Placement и диагностика размещения

Placement учитывает resource providers, inventory, traits и allocations. Это источник данных для планирования ресурсов, а не отдельный гипервизор. Административные запросы требуют osc-placement и разрешённого policy scope. [6]

```sh
openstack resource provider list
openstack resource provider show "$RP_UUID"
openstack resource provider inventory list "$RP_UUID"
openstack resource provider usage show "$RP_UUID"
openstack --os-placement-api-version 1.6 \
  resource provider trait list "$RP_UUID"
openstack resource provider allocation show "$SERVER_ID"
```

Trait list требует Placement microversion не ниже 1.6; подтвердите поддержку сервером. В allocation show аргумент — UUID consumer; для обычной ВМ это UUID сервера. Во время миграции возможны allocations migration consumer. Не считайте любой неизвестный consumer утечкой.

### Что сравнивать при NoValidHost

| Проверка | Что она объясняет |
| --- | --- |
| Nova service и hypervisor | Узел жив, разрешено размещение, корректно имя |
| Inventory и usage | Доступные классы ресурсов, reserved и allocation ratio |
| Flavor extra specs и свойства образа | CPU, NUMA, traits, PCI, aggregate и zone ограничения |
| Сеть и storage | Доступность требуемых сегментов, томов и зон |
| Журнал scheduler и request ID | Причина исключения кандидатов |

Начните с server show и server event list, зафиксируйте request ID, время и flavor. Сопоставьте кандидатов с inventory и требованиями ВМ. Сумма свободной RAM по облаку не доказывает, что один узел удовлетворяет NUMA, CPU pinning, PCI и disk требованиям.

### Изменения inventory и allocations

Не редактируйте allocations и inventory вручную как первый шаг исправления NoValidHost. Их жизненным циклом управляют Nova и другие владельцы ресурсов; запись через Placement может разойтись с фактическим состоянием. Восстановление учета требует отдельного плана и проверки источника данных, поколения ресурса и незавершённых миграций.

Resource provider UUID и имя compute service — разные идентификаторы. При вложенных providers один физический хост представлен деревом ресурсов. Проверяйте связь по данным Nova и Placement, а не по совпадению строк имени.

## 12 Mistral и запуск workflow

Mistral хранит определения workflow и исполняет их задачи. В OSC используются workflow, workbook, task execution и action execution; отдельной штатной группы openstack mistral или openstack powerops нет. Требуется python-mistralclient. [2]

### Инвентаризация

```sh
openstack workflow engine service list
openstack workbook list
openstack workflow list
openstack workflow show "$WORKFLOW_ID"
openstack workflow definition show "$WORKFLOW_ID"
openstack action definition list
openstack workflow execution list
```

Проверьте owner/scope, namespace, входные параметры и action definitions. Одинаковое имя в другом namespace может означать другое определение. Не делайте административный workflow public без проверки передаваемых полномочий и доступности действий.

### Проверочный workflow без управления инфраструктурой

Сохраните следующий YAML как cli-smoke.yaml. Он возвращает входную строку через std.echo и не вызывает Nova, Ironic или другие инфраструктурные действия. Создание и запуск всё равно записывают объекты в Mistral.

```yaml
version: '2.0'
cli_smoke:
  type: direct
  input:
    - message: 'cli check'
  output:
    result: <% task(echo).result %>
  tasks:
    echo:
      action: std.echo output=<% $.message %>
```

```sh
openstack workflow validate cli-smoke.yaml
openstack workflow create cli-smoke.yaml
openstack workflow execution create cli_smoke \
  '{"message":"operator check"}'
```

Запишите ID выполнения как EXECUTION_ID, затем проверьте его состояние и output. Validate проверяет определение, но не доказывает доступность внешних API и секретов, если они понадобятся другому workflow. При повторной загрузке существующего определения используйте согласованное обновление, а не создавайте неоднозначные копии.

Input можно передать JSON-файлом как позиционный аргумент: workflow execution create "$WORKFLOW_ID" input.json. JSON сохраняет типы boolean, array и number. Строка "false" не равна логическому false. Не помещайте пароли и BMC credentials в input: они могут попасть в БД исполнения, output и журналы.

## 13 Mistral и разбор выполнения

### Последовательность проверки

```sh
openstack workflow execution show "$EXECUTION_ID"
openstack task execution list "$EXECUTION_ID"
openstack workflow execution report show --errors-only \
  "$EXECUTION_ID"
openstack workflow execution output show "$EXECUTION_ID"
openstack task execution show "$TASK_ID"
openstack action execution list "$TASK_ID"
openstack action execution show "$ACTION_EXECUTION_ID"
```

Результат проверочного workflow — SUCCESS и ожидаемая строка в output. Для рабочего сценария дополнительно проверьте изменённые ресурсы: SUCCESS означает завершение логики workflow, а критерии приемки определяет сам сценарий.

Состояния RUNNING, PAUSED, SUCCESS, ERROR и CANCELLED относятся к исполнению. Ошибку ищите от root execution к task и action execution. При подworkflow просмотрите дочерние выполнения и state_info. Полные input/output и published variables могут содержать секреты; ограничьте сбор нужным исполнением.

### Пауза и продолжение

```sh
openstack workflow execution update --state PAUSED \
  "$EXECUTION_ID"
openstack workflow execution show "$EXECUTION_ID"
```

Пауза не гарантирует остановку уже начатого внешнего действия. Перед продолжением проверьте фактическое состояние объектов и условия workflow. Продолжение без изменения env:

```sh
openstack workflow execution update --state RUNNING \
  "$EXECUTION_ID"
```

Если workflow использует ручной gate через env, передавайте только документированные им параметры и подтверждайте соответствующее условие фактически. Нельзя выставлять SUCCESS или обходить gate ради удаления ошибки. CANCELLED также не откатывает уже выполненные операции в Nova, storage или BMC.

### Повтор и обрыв связи

После timeout найдите созданное исполнение, сравните workflow, время, description и input, затем исследуйте состояние его задач. Не создавайте второе выполнение для хоста, пока неизвестен исход первого. Rerun задачи может повторить внешнее действие; до него нужна оценка идемпотентности и уже выполненных эффектов.

### Расширения PVS

В локальной исследованной доработке PowerOps используются workflow power_ops.host_power_status, power_ops.planned_power_off, power_ops.planned_reboot и power_ops.power_on_and_return. Это локальный контракт, а не upstream API. Перед запуском найдите определения в установленном Mistral и сверьте их input, политику ВМ и return gate с runbook именно этой поставки. Наличие workflow в списке не доказывает настройку Ironic mapping, fencing и права исполнителя. [9]

## 14 Masakari и объекты HA

Masakari управляет сегментами HA и обработкой уведомлений об отказах. Требуется python-masakariclient. Команды — openstack segment и openstack notification; внутреннее имя плагина ha не добавляется в командную строку. [3]

### Инвентаризация

```sh
openstack segment list
openstack segment show "$SEGMENT_ID"
openstack segment host list "$SEGMENT_ID"
openstack segment host show "$SEGMENT_ID" "$HA_HOST_ID"
openstack notification list
openstack notification show "$NOTIFICATION_ID"
```

Сопоставьте имя HA-хоста с host поля nova-compute, сегмент, recovery_method, reserved и on_maintenance. UUID HA-хоста отличается от UUID compute service и Ironic node. Ошибка такого сопоставления может направить операцию на другой объект.

### Создание сегмента и регистрация хоста

Условие: согласованы границы отказа, recovery method, резерв ёмкости и источники мониторинга. Ниже — пример сегмента с методом auto. Он не настраивает monitor и fencing автоматически.

```sh
openstack segment create cli-ha-segment auto compute
```

Сохраните SEGMENT_ID. Для хоста с согласованными значениями type=COMPUTE и control_attributes=SSH используйте:

```sh
openstack segment host create "$HOST" COMPUTE SSH \
  "$SEGMENT_ID" --reserved False --on_maintenance False
openstack segment host list "$SEGMENT_ID"
```

Тип и control_attributes выбираются по интеграции площадки; строка SSH не выполняет настройку SSH-доступа. В методах reserved_host, auto_priority и rh_priority проверьте смысл резервных хостов, настройки Nova и достаточность резервов до включения восстановления.

### Maintenance и резерв

```sh
openstack segment host update "$SEGMENT_ID" "$HA_HOST_ID" \
  --on_maintenance True
openstack segment host show "$SEGMENT_ID" "$HA_HOST_ID"
```

У этого клиента параметр называется --on_maintenance с подчёркиванием, значения — True или False. Позиционные аргументы update: сначала segment, затем host. Maintenance в Masakari не отключает scheduling Nova и не останавливает ВМ. Поле reserved описывает роль резервного хоста, а не общую блокировку ресурса.

## 15 Masakari и обслуживание хоста

### Плановый вывод из работы

Сначала остановите новые конкурирующие изменения для целевого хоста по регламенту площадки: задания Watcher, другие PowerOps workflow и ручные операции. Проверьте активные notification и уже начатое восстановление. Maintenance не отменяет автоматически выполняющийся recovery workflow.

```sh
openstack notification list
openstack workflow execution list
openstack optimize actionplan list
openstack server list --all-projects --host "$HOST"
```

Далее включите on_maintenance в Masakari и запретите новое размещение Nova, если это не делает утверждённый workflow. Сохраните прежние значения: уже disabled хост после работ не нужно автоматически включать.

```sh
openstack segment host update "$SEGMENT_ID" "$HA_HOST_ID" \
  --on_maintenance True
openstack compute service set --disable \
  --disable-reason "CHG maintenance" "$HOST" nova-compute
```

Перенесите ВМ утверждённым способом и проверьте завершение каждой операции. Отдельно учтите SHUTOFF, ERROR и специальные ВМ, локальные диски и attachments. Для выключения узла нужен критерий отсутствия работающих гостевых доменов и незавершённых миграций, а не только пустая таблица ACTIVE. Если поставка требует PowerOps, используйте полный workflow вместо ручного обхода его шагов.

### Возврат в работу

Проверьте питание, сеть, storage, время, nova-compute up и отсутствие конфликтующих или устаревших гостевых доменов после аварий. Подтвердите готовность monitor/fencing. Затем снимите maintenance; разрешение Nova выполняйте последним, только если до работ сервис был enabled.

```sh
openstack segment host update "$SEGMENT_ID" "$HA_HOST_ID" \
  --on_maintenance False
openstack compute service set --enable "$HOST" nova-compute
openstack compute service list --host "$HOST"
openstack segment host show "$SEGMENT_ID" "$HA_HOST_ID"
```

При ошибке возврата оставьте хост вне размещения и выясните причину. Не поднимайте старые копии ВМ, которые уже восстановлены на другом хосте.

### Диагностика recovery

```sh
openstack --os-ha-api-version 1.3 notification show \
  "$NOTIFICATION_ID"
openstack --os-ha-api-version 1.3 notification vmove list \
  "$NOTIFICATION_ID"
```

VMoves требуют API 1.3; сначала подтвердите его поддержку сервером. Детали recovery workflow доступны начиная с 1.1. Сопоставьте notification, VMoves, Nova events и журналы engine по времени и UUID. Создание notification может запустить реальное восстановление; это не проверка здоровья API. Штатных команд notification retry/cancel в проверенном клиенте нет. [3]

## 16 Watcher и подготовка аудита

Watcher строит рекомендации по оптимизации, а action plan применяет изменения. Требуется python-watcherclient; OSC-команды начинаются с optimize. Разделение audit и start позволяет проверить рекомендации до их выполнения. [4]

### Обнаружение возможностей

```sh
openstack optimize service list
openstack optimize goal list
openstack optimize strategy list
openstack optimize strategy show "$STRATEGY_ID"
openstack optimize strategy state "$STRATEGY_NAME"
openstack optimize scoringengine list
openstack optimize datamodel list
```

Выберите goal и совместимую strategy из реального списка. Для strategy state укажите имя STRATEGY_NAME. Доступные стратегии, data sources и параметры зависят от конфигурации. Проверяйте свежесть телеметрии и модель ресурсов; пустые или устаревшие метрики могут привести к неподходящим рекомендациям.

### Ограничение области аудита

Создайте scope.yaml с фактическим числовым ID разрешённого host aggregate. В примере 42 — заменяемое значение. Проверьте состав aggregate через Nova; ошибки scope влияют на область возможных изменений.

```yaml
- compute:
  - host_aggregates:
    - id: 42
```

```sh
openstack aggregate show "$AGGREGATE_ID"
openstack optimize audittemplate create cli-review-template \
  "$GOAL_ID" --strategy "$STRATEGY_ID" --scope scope.yaml
openstack optimize audittemplate show "$TEMPLATE_ID"
```

TEMPLATE_ID берут из результата create. Перед запуском добавьте только параметры, поддерживаемые выбранной strategy; их значения и единицы должны быть проверены по её описанию. Scope должен поддерживаться этой стратегией и соответствовать требуемой области обслуживания.

### Однократный аудит

```sh
openstack optimize audit create --audit-template "$TEMPLATE_ID" \
  --audit_type ONESHOT --name cli-review-audit
openstack optimize audit show "$AUDIT_ID"
openstack optimize actionplan list --audit "$AUDIT_ID"
```

Для клиента 4.8.0 auto_trigger по умолчанию False. В примере --auto-trigger не задаётся; после создания проверьте фактическое значение в audit. Дождитесь завершения аудита и появления плана либо понятной причины отсутствия рекомендаций. Не задавайте --force для обхода уже выполняющегося плана без разбора конфликта.

## 17 Watcher и выполнение плана

### Проверка рекомендаций

```sh
openstack optimize actionplan show "$PLAN_ID"
openstack optimize action list --action-plan "$PLAN_ID"
openstack optimize action show "$ACTION_ID"
```

Перед start проверьте все действия и их зависимости, UUID ВМ, source/destination, свободную ёмкость, миграционные ограничения и отсутствие обслуживания хостов. Оцените эффект на приложения и допустимое окно работ. RECOMMENDED означает готовую рекомендацию, а не доказанную безопасность применения.

В исходниках клиента 4.8.0 нет зарегистрированной команды optimize actionplan create: план формируется в результате аудита. Создавать его по устаревшему примеру из документации не нужно.

### Запуск и наблюдение

```sh
openstack optimize actionplan start "$PLAN_ID"
openstack optimize actionplan show "$PLAN_ID"
openstack optimize action list --action-plan "$PLAN_ID"
```

Дождитесь конечного состояния плана, проверьте каждое действие и соответствующие объекты Nova/Cinder. При успешной миграции дополнительно проверяются новый хост, task_state и доступность приложения. План может завершиться с частично выполненными действиями; общий FAILED не означает, что инфраструктура осталась неизменной.

### Запрос отмены

```sh
openstack optimize actionplan cancel "$PLAN_ID"
openstack optimize actionplan show "$PLAN_ID"
openstack optimize action list --action-plan "$PLAN_ID"
```

Отмена не является транзакционным откатом и не обязательно прерывает уже отправленный запрос Nova. До повторного start, нового аудита или ручного исправления установите фактический результат каждой начатой операции. Для CONTINUOUS audit отдельно остановите или измените генерацию новых планов по поддерживаемой сервером процедуре; отмена одного плана не выключает весь аудит.

### Согласование с HA и PowerOps

Штатный OSC не предоставляет универсальную блокировку, общую для Watcher, Mistral и ручных команд Nova. В PVS могут присутствовать серверные guard/hold-механизмы; их команды и гарантии зависят от локальной доработки. Проверяйте их по runbook установленной версии. CONTINUOUS audit может создать новый план после завершения текущей проверки. [9]

Основные причины ошибки: нет актуальной модели или метрик, недоступен datasource, стратегия не применима, нет ресурсов для миграции, сработала политика доступа или локальная защита. Проверяйте service, strategy state, audit, action plan и action последовательно.

## 18 Ironic и физические узлы

Раздел применяется при наличии Ironic и python-ironicclient. Ironic node UUID, BMC-адрес, Nova host и Masakari host UUID — разные сущности. Перед power operation их соответствие должно быть проверено по инвентарю площадки. [7]

### Инвентаризация

```sh
openstack baremetal node list
openstack baremetal node show "$NODE_UUID"
openstack baremetal node validate "$NODE_UUID"
openstack baremetal driver list
```

Node show показывает power_state, target_power_state, provision_state, maintenance и last_error. Полные сведения driver_info могут быть чувствительными; не передавайте их в открытые тикеты. Validate проверяет интерфейсы драйвера и может обращаться к BMC; это не тест HA и не доказательство успешного fencing.

### Профиль PVS для управления питанием

В исследованной локальной доработке предусмотрен BMC/power-only профиль: финальное provision_state — manageable, сетевой и storage интерфейсы noop, без обычного provisioning и cleaning. Не переводите такой узел в available по инструкции для baremetal-провижининга и не запускайте чистку дисков без отдельного задания. Наличие Ironic в каталоге не доказывает использование этого профиля на конкретном узле. [9]

### Команды питания

Следующие команды воздействуют на физический узел. Используйте их только в процедуре, которая уже обеспечила вывод ВМ, запрет размещения, согласование HA и отсутствие конкурирующих действий. Для PVS с PowerOps рабочей точкой входа является утверждённый workflow; прямые команды ниже — справка для отдельно разрешённых операций.

```sh
openstack baremetal node power off "$NODE_UUID"
openstack baremetal node show "$NODE_UUID"
```

Подтвердите фактическое выключение через независимый канал BMC согласно runbook. Принятый API-запрос и target_power_state сами по себе не равны физическому выключению. Включение:

```sh
openstack baremetal node power on "$NODE_UUID"
openstack baremetal node show "$NODE_UUID"
```

Power on не подтверждает готовность Nova, storage или отсутствие старых гостевых доменов. До возврата в scheduling выполните проверки раздела 15. Ironic maintenance также не включает автоматически Masakari maintenance и не отключает nova-compute.

При timeout после команды питания сначала выясните фактическое состояние BMC. Не выполняйте последовательно off/on/reboot в попытке получить успешный код возврата: это может прервать уже начатый recovery.

## 19 Типовые ошибки и сбор доказательств

| Симптом | Первый шаг | Что проверить дальше |
| --- | --- | --- |
| Команда не найдена | openstack help и список пакетов | Плагин, его версия, правильное имя |
| 401 | Новая аутентификация | Срок credentials, домен, время, auth URL |
| 403 | Scope и назначения ролей | Policy конкретного сервиса, ownership и ACL |
| Endpoint not found | catalog list | Тип сервиса, регион, interface |
| Ошибка TLS | Цепочка CA и имя endpoint | Срок сертификата, trust store, proxy |
| 404 | show по UUID в нужном проекте | Неверный объект, скрытие по policy, удаление |
| 409 | show и текущая задача | Конфликт состояния или параллельная операция |
| 406 или unsupported version | Поддержка API microversion | Клиентские defaults и диапазон сервера |
| 5xx | Время и request ID | API, backend, очередь и БД по журналам |
| Timeout или разрыв связи | Состояние объекта и execution | Запрос мог быть принят; исключить дублирование |

### Минимальный набор для обращения к сопровождению

Укажите время UTC, cloud/region/interface, версии клиентов, точную команду с заменёнными секретами, UUID объекта, scope, код ошибки и request ID. Приложите исходное и текущее состояние ресурса. Для Mistral нужны execution/task/action IDs; для Masakari — notification, segment и host IDs; для Watcher — audit/actionplan/action IDs.

Не прикладывайте пароль, token ID, Application Credential Secret, SecretID Vault, BMC credentials, значения секретов или полный environment. Ограничьте доступ к сведениям о topology, адресах, metadata и tenant resources.

### Когда нужен debug

Если обычной ошибки и request ID недостаточно, повторите только безопасный запрос чтения с --debug в защищённом окружении. Debug может раскрыть URL, заголовки, тела запросов и ответов. Перед передачей проверьте и очистите весь файл; не полагайтесь на автоматическую маскировку клиента. Повторять изменяющий запрос ради debug без проверки его первого результата нельзя.

### Завершение изменения

Изменение завершено, когда достигнуто ожидаемое состояние API, подтверждена работа приложения, сняты только временные ограничения данного изменения и сохранены доказательства. Если часть операции прошла, опишите фактическое состояние и следующий шаг; не называйте это полным откатом без проверки всех затронутых ресурсов.

## 20 Источники и правила актуализации

### Официальные источники

[1] OpenStackClient 2025.1 — конфигурация и реестр команд. Точный синтаксис основных примеров дополнительно проверен по python-openstackclient 7.4.0.

https://docs.openstack.org/python-openstackclient/2025.1/configuration/index.html

https://docs.openstack.org/python-openstackclient/2025.1/cli/command-list.html

https://github.com/openstack/python-openstackclient/tree/7.4.0/openstackclient

[2] Mistral — регистрация OSC-команд и обработчики версии 5.4.0; справочник OSC ветки 2025.1.

https://github.com/openstack/python-mistralclient/tree/5.4.0/mistralclient/commands/v2

https://docs.openstack.org/python-openstackclient/2025.1/cli/plugin-commands/mistral.html

[3] Masakari — клиент 8.6.0, регистрация команд, параметры сегментов, хостов, notification и API version.

https://github.com/openstack/python-masakariclient/tree/8.6.0/masakariclient

[4] Watcher — клиент 4.8.0, обработчики audit, template, action plan и action. При расхождении с текстовой справкой использована фактическая регистрация в setup.cfg и get_parser.

https://github.com/openstack/python-watcherclient/tree/4.8.0/watcherclient/v1

https://github.com/openstack/python-watcherclient/blob/4.8.0/setup.cfg

[5] Nova — OSC обработчик миграции и эвакуации в версии 7.4.0.

https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server.py

[6] Placement — CLI reference ветки 2025.1.

https://docs.openstack.org/osc-placement/2025.1/cli/index.html

[7] Ironic — клиент 5.10.0, обработчики OSC.

https://github.com/openstack/python-ironicclient/tree/5.10.0/ironicclient/osc/v1

## 21 Локальная основа и проверка перед применением

### Материалы PVS

[8] Рабочие документы отдельного набора RBAC: README.md, POSTDEPLOY.md, AD-INTEGRATION.md и архив kolla-ansible-pvs_1.0.0_14.09.zip. Эти исходные материалы предоставляются отдельно; упомянутый README.md не является оглавлением этой ветки. Использованы для границ ролей, проектных назначений, read-only AD/LDAP и отделения credentials CLI от серверных секретов. Руководство не утверждает, что все параметры архива применены на площадке.

[9] Локальное исследование OpenStack_Epoxy_2025.1_CLI_Horizon.md и материалы analysis/openstack-cli-horizon-2025.1: исходники релизных клиентов, command-inventory.tsv, masakari-watcher.md, mistral-heat.md и local-customizations.md. В репозитории доступны [опубликованный отчёт](docs/openstack-cli-horizon-2025.1/README.md) и [реестр исходных материалов](docs/openstack-cli-horizon-2025.1/evidence/README.md). Описание PowerOps, BMC-only Ironic и Watcher guards относится к исследованным локальным доработкам; установленная версия должна быть подтверждена отдельно.

### Проверка применимости на площадке

Перед первой рабочей операцией зафиксируйте версии клиента и плагинов, версии сервисов по инвентарю поставки, доступные API microversion и endpoint. Убедитесь, что административный профиль относится к нужному региону и scope. Проверьте доступ чтения для каждого используемого сервиса и соответствие имени хоста UUID в Nova, Masakari и Ironic.

После обновления клиента или облака повторно сверяйте help изменяющих команд и параметры workflow. Политики RBAC, defaults API, поведение provider driver и локальные защиты могут меняться независимо от наличия команды в OSC.

### Граница проверки этого документа

Выполнена статическая сверка команд и параметров по указанным источникам. Не выполнены аутентификация на площадке, создание ресурсов, миграции, recovery, запуск оптимизации и операции питания. Примеры с условными UUID, доменами, CIDR и файлами становятся исполнимыми только после подстановки и проверки данных конкретного окружения.

Руководство предназначено для управления сервисами через их API. Ремонт базы данных, RabbitMQ, Ceph, OVN/OVS, libvirt, BMC и конфигурации Kolla требует отдельных процедур. Изменение статуса ресурса в API не заменяет устранение причины на этом уровне.

### Запись выполненной операции

| Поле | Что записать |
| --- | --- |
| Контекст | Номер изменения, время UTC, оператор, cloud и регион |
| Объекты | Проект, UUID ресурсов, проверенное имя хоста |
| Основание | Исходное состояние и цель изменения |
| Выполнение | Команды без секретов, request и execution IDs |
| Приёмка | Итоговое состояние API и проверка приложения |
| Остаточные действия | Временные блокировки, очистка тестов, нерешённые ошибки |
