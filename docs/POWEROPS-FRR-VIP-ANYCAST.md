# FRR и VIP anycast: логика, конфигурация и действия Kolla-Ansible

Сверка исходников: 10 сентября 2026 года. Документ описывает **существующую
пользовательскую реализацию**, а не универсальную возможность любого Kolla-Ansible.

| Источник | Что из него проверено | SHA256 архива |
| --- | --- | --- |
| `kolla-ansible-enroll-ironic-patch-3_0809.zip` | Globals/defaults, inventory, роль `loadbalancer`, шаблоны, контейнерные модули | `b5958f14a09b1bdad4edc9c6b3dd092f4376b55dee9d5814fd2ad78fdffb1be9` |
| `kolla-pvs_1.0.0.zip` | Рецепты образов и runtime-скрипты `frr` / `anycast-vip` | `1c5c89977e9ec60079534bc82b03a132a6d790070ac4a1707275e75a396b2867` |

Второй архив — отдельный доступный снимок сборочных исходников, **не архив
`0809` и не доказательство содержимого работающего образа**. На стенде нужно
сверить image digest, скрипты, пакет FRR и доставленные конфиги. Живые BGP-сессии,
настройки маршрутизаторов и время переключения при подготовке документа
не проверялись. Код и настройки стенда этим документом не изменяются.

Связанные документы:

- [Общее устройство PowerOps](POWEROPS-OVERVIEW.md).
- [Consul и матрица отказов](POWEROPS-CONSUL.md).
- [Диагностика API и workflow](POWEROPS-DIAGNOSTICS.md).
- [Разбор отдельных проблем, включая Mistral](POWEROPS-TROUBLESHOOTING-COMMANDS.md).

## 1. Краткий вывод

В этой схеме VIP может одновременно находиться на нескольких исправных узлах
группы `loadbalancer`. Нет одного VRRP master, который единолично держит адрес.
Каждый узел принимает решение о **своём** VIP по локальным проверкам.

- `anycast_vip` — контейнер с Bash-watchdog. Проверяет локальные сервисы и
  добавляет/снимает IPv4 `/32` на dummy-интерфейсе хоста.
- `frr` — контейнер с `zebra` и `bgpd`. Обнаруживает connected-маршруты и
  распространяет разрешённые VIP-префиксы по BGP.
- HAProxy принимает API-трафик и выбирает backend; ProxySQL обслуживает
  соответствующий путь к БД. FRR не заменяет их прикладную балансировку.
- Kolla-Ansible создаёт конфигурацию и управляет контейнерами. Решение при
  отказе работающего сервиса принимает runtime-watchdog, без запуска playbook.

`anycast_watchdog` здесь — **не Linux hardware watchdog**: он не обслуживает
`/dev/watchdog`, не перезагружает сервер и не выполняет fencing.

## 2. Общая цепочка и маршрут клиентского запроса

```text
inventory + globals + passwords
    → Kolla-Ansible / роль loadbalancer
        ├─ HAProxy / ProxySQL и их локальные сокеты
        ├─ anycast_vip: checks.conf + ANYCAST_* → проверки → VIP на dummy
        └─ frr: frr.conf → zebra + bgpd → анонс разрешённых connected /32
                                            ├─ iBGP к другим loadbalancer
                                            └─ eBGP к заданным uplink routers

Клиент → маршрут к VIP → выбранный loadbalancer → HAProxy → backend API
```

### 2.1. Запрос с самого loadbalancer

Пока VIP назначен локальному dummy, для адреса есть маршрут в таблице `local`.
При стандартных Linux policy rules она проверяется раньше `main`, поэтому
локальный запрос к VIP остаётся на этой ноде, даже если известны BGP-маршруты
соседей. После удаления локального адреса может использоваться маршрут через
другой loadbalancer. Это требует реально установленного и достижимого маршрута;
само удаление адреса его не создаёт. Порядок стандартных правил описан в
[ip-rule(8)](https://man7.org/linux/man-pages/man8/ip-rule.8.html).

Проверять нужно и `ip rule`, и таблицы `local`/`main`: дополнительные VRF,
policy routing и статические маршруты могут менять фактический путь.

### 2.2. Запрос с compute, deployment host или внешнего клиента

Эти узлы не становятся BGP-соседями автоматически только потому, что используют
VIP. Маршрут к нему должен существовать в их сетевом тракте — например, через
uplink-маршрутизаторы. Mesh между loadbalancer сам по себе не доставляет маршрут
всем остальным хостам.

Anycast не означает автоматически равномерное распределение между всеми
нодами. Выбор пути и возможный ECMP зависят от маршрутизатора, атрибутов BGP и
настроек multipath. В поставляемом `frr.conf.j2` нет отдельной настройки
`maximum-paths`; внешний маршрутизатор роль не конфигурирует.

Если клиент считает VIP непосредственно подключённым адресом своей подсети,
он может использовать ARP вместо нужного маршрутизатора. `/32` на dummy не
отменяет это поведение других машин. В anycast-ветке роли нет настройки
`arp_ignore`/`arp_announce` или полной схемы устранения ARP flux. Размещение VIP
и маршруты к нему должны быть согласованы с сетевой схемой; механическая замена
Keepalived на FRR этого не гарантирует.

Существующие TCP-соединения при смене узла могут оборваться: синхронизация
состояния TCP/HAProxy между нодами этой реализацией не добавляется.

## 3. Как генерируется BGP-конфигурация

Источник: `ansible/roles/loadbalancer/templates/frr/frr.conf.j2`.
Это генерация Ansible, а не autodiscovery соседей самим FRR.

### 3.1. iBGP full-mesh внутри inventory

1. Шаблон получает `groups['loadbalancer']`.
2. Создаёт peer-group `MESH` с `remote-as = frr_bgp_asn`.
3. Для каждого хоста получает API-IP через `'api' | kolla_address(host)`.
4. Адрес, равный локальному `api_interface_address`, исключается.
5. Остальные адреса включаются в `MESH`; в IPv4 unicast задаются `activate`
   и `next-hop-self`.

В штатном `ansible/inventory/multinode` группа `loadbalancer` — children группы
`network`, **не автоматически всех compute или всех control**. Окончательный
состав задаёт ваш inventory. При трёх loadbalancer каждая нода получает двух
mesh-соседей; при одном — mesh отсутствует.

Для всех членов этого mesh предполагаются согласованный ASN и уникальные,
достижимые API-IP. Если отключить FRR только на одной ноде, но оставить её в
`loadbalancer`, соседи всё ещё будут сгенерированы по inventory. Фильтрации
списка по per-host `enable_frr` в BGP-шаблоне нет.

### 3.2. Uplink-соседи

Внешние соседи берутся только из `frr_bgp_uplink_peers`. Каждый элемент имеет
поля `address` и `asn`. При отличающемся ASN получается eBGP. Шаблон не содержит
параметров для `ebgp-multihop`, отдельного `update-source`, BFD или per-peer
таймеров. Такие схемы нельзя включить добавлением произвольного поля в словарь:
оно не будет использовано шаблоном.

Соседняя сторона должна отдельно настроить сессии, согласовать AS/MD5, разрешить
VIP-префиксы и обеспечить дальнейшую маршрутизацию. Эта Ansible-роль
не настраивает uplink-маршрутизатор и не проверяет весь этот тракт.

### 3.3. Какие маршруты принимаются и анонсируются

| Конструкция | Фактическое действие шаблона |
| --- | --- |
| `bgp router-id` | Равен локальному `api_interface_address` |
| `no bgp default ipv4-unicast` | Соседи активируются явно внутри address-family |
| `redistribute connected route-map ANYCAST-ONLY` | Источник локального BGP-анонса — connected-маршруты, прошедшие prefix-list |
| `ip prefix-list ANYCAST-VIP` | По записи на каждый элемент `anycast_vip_addresses`, последовательности 5, 10, 15…; без `le`/`ge` |
| `ANYCAST-ONLY permit 10` | Разрешает перераспределение только перечисленных VIP-префиксов |
| `UPLINK-OUT permit 10` | Разрешает наружу только префиксы из `ANYCAST-VIP` |
| `UPLINK-IN deny 10` | Не принимает маршруты от uplink, в том числе default route |
| `neighbor MESH next-hop-self` | Задаёт next-hop-self для mesh |
| `bgp graceful-restart-disable` | Настройка отключения graceful restart в поставляемом шаблоне |

Для eBGP указаны обе route-map. Это соответствует требованию явных политик
в профиле FRR `traditional`; Established без разрешающей политики ещё не
доказывает передачу маршрутов. См.
[FRR: Require policy on EBGP](https://docs.frrouting.org/en/stable-10.0/bgp.html#require-policy-on-ebgp).

Шаблон использует `redistribute connected`, а не `network`. Не следует
обобщать комментарий исходника до «`network` всегда анонсирует отсутствующий
адрес»: поведение `network` зависит от `bgp network import-check` и наличия
маршрута. См. [FRR: Networks](https://docs.frrouting.org/en/stable-10.0/bgp.html#networks).

Команда `bgp graceful-restart-disable` действительно присутствует в
[исходниках FRR tag frr-10.0](https://github.com/FRRouting/frr/blob/frr-10.0/bgpd/bgp_vty.c#L3071).
Но рецепт образа устанавливает пакет `frr` без фиксированной версии в этом
Dockerfile: допустимый синтаксис нужно сверять с **собранным** образом.

### 3.4. Важное различие: снять свой VIP и перестать объявлять префикс вообще

Удаление VIP снимает **локальный connected-источник** анонса. Однако тот же
префикс может оставаться в BGP как маршрут от исправного соседа.

Вывод из шаблона: `UPLINK-OUT` проверяет только префикс, не происхождение и не
здоровье локального proxy. Он не запрещает экспорт подходящего маршрута,
полученного через mesh. Поэтому обещание «после снятия VIP внешний маршрутизатор
никогда не пошлёт пакет на эту ноду» из данного конфига не следует.

Если такая нода остаётся транзитным next hop, нужны корректные forwarding,
firewall и маршрут до исправного владельца. Anycast-ветка `config-host.yml`
не устанавливает `net.ipv4.ip_forward` и не настраивает reverse-path filtering.
Проверять это нужно отдельно; наличие BGP-сессий не доказывает рабочий транзит.

## 4. Что именно проверяет anycast_vip

### 4.1. Генерация checks.conf

`roles/loadbalancer/tasks/config.yml` переиспользует два шаблона из каталога
`templates/keepalived/`. При включённых HAProxy и ProxySQL получается:

```text
exec|haproxy|/checks/check_alive_haproxy.sh
exec|proxysql|/checks/check_alive_proxysql.sh
```

Файл генерируется по `enable_haproxy` и `enable_proxysql`. Флаг
`keepalived_track_script_enabled` этими anycast-задачами не используется.

| Проверка | Реальная команда внутри скрипта | Чего она не доказывает |
| --- | --- | --- |
| HAProxy | `echo "show info" \| socat unix-connect:/var/lib/kolla/haproxy/haproxy.sock stdio` | Доступность каждого backend, отсутствие 504, корректную авторизацию API |
| ProxySQL | `echo "show info" \| socat unix-connect:/var/lib/kolla/proxysql/admin.sock stdio` | Успешный SQL-запрос, Galera quorum, доступность backend БД |

Вывод скриптов отбрасывается, результат определяется exit code. В частности,
ProxySQL-проба не использует MySQL-клиент с аутентификацией: несмотря на имя
`admin.sock`, её нельзя считать полноценным тестом SQL-протокола.

Поэтому возможна ситуация: watchdog считает узел здоровым, VIP остаётся,
HAProxy доступен, но Mistral отвечает 504 из-за проблем backend. Этот случай
нужно разбирать по [диагностике Mistral](../tools/diagnostics/README.md),
а не считать отсутствие переключения VIP само по себе ошибкой BGP.

### 4.2. Поддерживаемый формат ручных checks

Скрипт умеет три вида строк, разделённых `|`:

| Формат | Критерий успеха |
| --- | --- |
| `tcp|имя|host|port` | Открывается TCP-соединение через Bash `/dev/tcp` под `timeout` |
| `http|имя|url|код` | `curl` получает ровно ожидаемый HTTP-код; задан `--max-time` |
| `exec|имя|команда` | Команда `bash -c` под `timeout` завершается с кодом 0 |

Пробы выполняются **последовательно**, проверяются все строки; логика — AND.
Провал любой пробы делает весь цикл неуспешным. Неизвестный тип — провал.
Пустые строки и комментарии пропускаются.

Роль не предоставляет отдельный globals-список дополнительных проверок:
`checks.conf.j2` содержит только две условные `exec`-строки. Поддержка `http`
и `tcp` в скрипте не означает, что Ansible их уже генерирует. Правка доставленного
файла вручную не является устойчивой конфигурацией: его перезапишет роль.
`exec` — привилегированное выполнение кода, файл должен быть доступен для записи
только доверенному администратору.

### 4.3. Состояния и переходы

1. На старте обязательна непустая `ANYCAST_VIP_ADDRESS`; проверяется наличие
   `ip`, `curl`, `timeout`, `socat` и читаемость файла checks.
2. Скрипт создаёт dummy, если интерфейс с этим именем отсутствует, и поднимает
   link. Уже существующий интерфейс не проверяется на тип `dummy`.
3. Снимает заданные адреса, выставляет внутреннее состояние `DOWN` и обнуляет
   счётчики. Ошибка этого стартового удаления подавляется через `|| true`.
4. После `RISE` успешных циклов подряд добавляет **все** VIP и переходит в `UP`.
5. После `FALL` неуспешных циклов подряд удаляет **все** VIP и переходит в `DOWN`.
6. Противоположный результат обнуляет соответствующий счётчик серии.
7. При обработанном `TERM`/`INT` пытается удалить VIP и завершает работу.

Все адреса имеют общее здоровье. Отдельной политики для internal/external VIP
или отдельных API в этом варианте нет. Добавление/удаление нескольких адресов
выполняется последовательно, **не транзакционно**: частичный успех возможен.

## 5. Globals, приоритеты и действующие defaults

### 5.1. Где задавать значения

- `ansible/group_vars/all.yml` — общие значения поставки.
- `ansible/roles/loadbalancer/defaults/main.yml` — сервисы, образы, volumes,
  environment, параметры HAProxy и прочие defaults роли.
- `/etc/kolla/globals.yml` и `/etc/kolla/globals.d/` — операторские overrides
  при обычном config path; BGP-секреты — в защищённом `passwords.yml`.
- Inventory/group_vars/host_vars — состав и адреса узлов; нужно учитывать
  перекрывающие их extra vars из globals.

В этой версии `kolla_ansible/ansible.py:build_args()` передаёт файлы как `-e`:
сначала globals, затем passwords, затем файлы `globals.d` в сортированном
порядке, пользовательские `-e` и внутренние extra vars команды. Поэтому нельзя
предполагать, что host_vars перекроет значение из globals. Общие правила —
[Ansible variable precedence](https://docs.ansible.com/projects/ansible/latest/reference_appendices/general_precedence.html).

### 5.2. Дублирующий блок в архиве 0809

В `ansible/group_vars/all.yml` основной anycast-блок расположен около строк
1168–1205, но часть ключей **повторно задана** около строк 1324–1331.
При загрузке с семантикой «последний ключ побеждает» результат следующий;
Ansible также может предупредить о дубликатах либо отклонить файл при строгой
настройке загрузчика. Это не два независимых набора параметров.

| Параметр | Ранний блок | Последнее объявление в 0809 | Значение для runtime |
| --- | --- | --- | --- |
| `enable_frr` | `"no"` | `"False"` | FRR и anycast выключены, пока нет override |
| `anycast_vip_addresses` | Формула internal VIP + отличный от него external VIP, `/32` | `[]` | Пустой environment → watchdog не стартует |
| `anycast_vip_interface` | `"dummy0"` | `""` | Скрипты используют fallback `dummy0`, но лучше задать явно |
| `anycast_vip_interval` | `3` | `5` | Пауза между циклами, секунды |
| `anycast_vip_fall` | `2` | `3` | Число плохих циклов подряд до снятия VIP |
| `anycast_vip_rise` | `2` | `3` | Число хороших циклов подряд до возврата VIP |
| `anycast_vip_check_timeout` | `2` | `3` | Timeout одной пробы, секунды |
| `anycast_vip_debug` | `false` | `"False"` | После `bool` debug выключен |

Таким образом, **одного `enable_frr: "yes"` недостаточно**. Нужен явно заданный
непустой список VIP. Формула автоматического выбора internal/external VIP из
раннего блока в этом архиве перекрыта пустым списком.

Fallback самого Bash-скрипта — `interval=3`, `fall=2`, `rise=2`, `timeout=2`.
Он используется при отсутствии/пустом environment, а не поверх непустых значений,
переданных Ansible. Не путать его с действующими defaults `0809`.

### 5.3. Включение сервисов и BGP

| Параметр | Default / источник | Назначение |
| --- | --- | --- |
| `enable_frr` | См. дубли выше | Одновременно включает сервисы `frr` и `anycast-vip` на loadbalancer |
| `enable_haproxy` | `"yes"`, all.yml | Влияет на формирование HAProxy-пробы и других задач; в словаре `loadbalancer_services.haproxy.enabled` отдельно стоит `true` |
| `enable_proxysql` | `"yes"`, all.yml | Включает ProxySQL и его пробу |
| `enable_keepalived` | `enable_haproxy and not enable_frr` | Автоматически false при FRR, если оператор не перекрыл выражение |
| `enable_loadbalancer` | OR от HAProxy, Keepalived, ProxySQL, FRR | Разрешает соответствующий play в site.yml |
| `enable_bird` | `"no"`, all.yml | Отдельный сервис; включение FRR само по себе его не отключает |
| `kolla_internal_vip_address` | Из Kolla globals | Адрес API без маски; должен согласовываться с anycast-списком |
| `kolla_external_vip_address` | По умолчанию равен internal VIP | Второй адрес нужно явно включить в anycast-список, если он используется и отличается |
| `frr_bgp_asn` | `65000` | Локальный AS и remote-as для MESH |
| `frr_bgp_uplink_peers` | `[]` | Список `{address, asn}` для uplink-соседей |
| `frr_bgp_timers_keepalive` | `3` | Keepalive в секундах для MESH и uplink |
| `frr_bgp_timers_hold` | `9` | Предлагаемый hold time для тех же соседей |
| `frr_bgp_uplink_expected` | `false` | **Объявлен, но нигде не используется в задачах/шаблонах этой поставки**; не включает проверку Established |
| `frr_bgp_md5_mesh_password` | Ключ в passwords.yml | Необязательный общий TCP MD5 secret mesh; добавляется в neighbor при непустом значении |
| `frr_bgp_md5_uplink_password` | Ключ в passwords.yml | Отдельный общий secret для всех заданных uplink; per-peer password не предусмотрен |
| `api_interface_address` | `'api' \| kolla_address` | Локальный router-id; адреса mesh берутся тем же фильтром для соседей |

FRR и Keepalived не должны одновременно владеть одним VIP. Изменение флага
не является полной миграцией с VRRP: задачи работающие disabled-контейнеры
автоматически не удаляют. Проверить существующий Keepalived, старые адреса и
маршруты нужно до переключения схемы. Аналогично нельзя оставлять BIRD и FRR
конкурировать за TCP/179 и одинаковые маршруты без отдельного проекта.

### 5.4. Соответствие globals и environment контейнеров

| Ansible-переменная | Переменная внутри контейнера | Кто читает |
| --- | --- | --- |
| `anycast_vip_addresses`, соединённые пробелами | `ANYCAST_VIP_ADDRESS` | Оба контейнера; имя в единственном числе, значение — список CIDR |
| `anycast_vip_interface` | `ANYCAST_VIP_INTERFACE` | Оба контейнера |
| `anycast_vip_interval` | `ANYCAST_VIP_INTERVAL` | Watchdog |
| `anycast_vip_fall` | `ANYCAST_VIP_FALL` | Watchdog |
| `anycast_vip_rise` | `ANYCAST_VIP_RISE` | Watchdog |
| `anycast_vip_check_timeout` | `ANYCAST_CHECK_TIMEOUT` | Watchdog; в имени нет `VIP` |
| Фиксированный путь из defaults роли | `ANYCAST_CHECKS_FILE=/etc/anycast-vip/checks.conf` | Watchdog |
| `anycast_vip_debug` | `ANYCAST_DEBUG=1` или `0` | Watchdog; тот же globals также выбирает syslog level FRR |

`frr_environment` и `anycast_vip_environment` определены в defaults роли.
При полном переопределении этих словарей нельзя потерять нужные ключи или
передать контейнерам разные адреса/интерфейсы.

### 5.5. Образы, volumes и системные параметры

| Настройка | Смысл |
| --- | --- |
| `frr_image`, `anycast_vip_image` | Собираются из `docker_registry`, `docker_namespace`, `docker_image_name_prefix`; имена образов `frr` / `anycast-vip` |
| `frr_tag`, `anycast_vip_tag` | По умолчанию `openstack_tag`; это теги образов, не версия пакета FRR |
| `frr_image_full`, `anycast_vip_image_full` | Итоговое `image:tag` для контейнера |
| `frr_dimensions`, `anycast_vip_dimensions` | По умолчанию `default_container_dimensions` |
| `frr_extra_volumes`, `anycast_vip_extra_volumes` | По умолчанию `default_extra_volumes` |
| `node_config_directory` | Каталог конфигов на хосте, обычно `/etc/kolla` |
| `container_config_directory` | Mount конфигов в контейнере, обычно `/var/lib/kolla/config_files` |
| `config_strategy` | Default `COPY_ALWAYS`; передаётся как `KOLLA_CONFIG_STRATEGY` и влияет на применение конфигурации при старте |
| `set_sysctl` | Default `"yes"`; разрешает системные настройки из config-host.yml |
| `kolla_sysctl_conf_path` | Default `/etc/sysctl.conf`; куда общая sysctl-роль сохраняет настройки |
| `haproxy_host_ipv4_tcp_retries2` | Default `KOLLA_UNSET`: роль не назначает численное значение; не таймер BGP |
| `docker_restart_policy` | Общий default `unless-stopped`; используется FRR, watchdog переопределяет в `no` |
| `docker_graceful_timeout` | Default 60 с в all.yml; общий timeout остановки контейнера, может ограничить время на обработку сигнала |

Оба сервиса заданы как `privileged: true`; контейнерные backend-модули этой
поставки используют host network. Поэтому `ip addr` внутри watchdog меняет
сеть **хоста**, а не изолированного контейнера.

Для Podman restart policy реализуется systemd, а не полем restart самого
Podman: `kolla_systemd_worker.py` создаёт `kolla-<container>-container.service`.
Ожидаемые имена — `kolla-frr-container.service` и
`kolla-anycast_vip-container.service`. Итоговые units нужно проверить на узле.
`restart_policy: "no"` не означает отсутствие стартового unit или запрет
ручного/Ansible запуска.

## 6. Тайминги: почему это не просто interval × fall

Все значения ниже — из исходников, не измеренный SLA стенда.

| Этап | Настройка / значение | Особенность |
| --- | --- | --- |
| Пауза watchdog | `anycast_vip_interval`, эффективный default 5 с | Sleep **после** всех проб, не фиксированный период начала цикла |
| Одна проба | `anycast_vip_check_timeout`, эффективный default 3 с | Каждая последовательная проба может занять своё время |
| Снятие VIP | `anycast_vip_fall`, действующий default 3 | Требуется серия плохих циклов, а не 3 отдельных плохих проб в одном цикле |
| Возврат VIP | `anycast_vip_rise`, действующий default 3 | Требуется серия полностью успешных циклов |
| BGP keepalive / hold | `frr_bgp_timers_keepalive=3`, `frr_bgp_timers_hold=9` | Согласуются с соседом; применяются к обнаружению потери BGP-связи, не к timeout API |
| Проверка FRR после запуска | `sleep 3` в frr_run.sh | Фиксировано в образе, отдельного globals нет |
| Слежение FRR за исчезновением VIP | `sleep 2` | Фиксировано в образе; перед soft inbound refresh |
| Контроль работающих демонов FRR | `sleep 5` | Фиксировано в образе |
| Некоторые startup errors FRR | `sleep 30` перед exit 1 | Не hold time и не задержка снятия VIP |

Если проверки занимают `t1`, `t2`, …, то обычный цикл примерно равен
`sum(t_checks) + interval`. Пример: две пробы по 3 с, interval 5 с, fall 3.
От начала первого полностью неуспешного цикла до попытки снять VIP получится
примерно `6 + 5 + 6 + 5 + 6 = 28 с`, а не 15 с. К этому могут добавиться фаза
начала отказа, выполнение `ip`, обработка маршрута и сходимость сети.

Это иллюстрация расчёта, **не верхняя граница**: `timeout` для exec/tcp не имеет
`--kill-after`, `ip`-операции выполняются без deadline, возможны задержки ОС.
`hold=9` тоже не означает «любой клиентский отказ исправится за 9 секунд».
При явном withdraw по работающей BGP-сессии ждать hold time не требуется.

FRR-wrapper при обнаружении исчезнувшего VIP выполняет
`clear bgp ipv4 unicast * soft in`. Это дополнительное обновление входящих
маршрутов, не команда выключения хоста и не гарантия успешного failover.
Ошибки этого вызова подавляются; нужно смотреть фактические RIB/FIB.

## 7. Что делает Ansible и какой playbook запускать

Отдельного `frr.yml` или `vipanycast.yml` в этой базе нет. Основная точка входа —
`ansible/site.yml`, play **Apply role loadbalancer**. Hosts — пересечение
`loadbalancer` и `enable_loadbalancer_True`; роль выбирает файл задач по
`kolla_action`.

Теги play: `haproxy`, `keepalived`, `bird`, `loadbalancer`. Отдельных тегов
`frr` и `anycast-vip` здесь нет; для всего этого контура использовать
`--tags loadbalancer`. Название тега `keepalived` не означает, что будут
затронуты исключительно Keepalived-задачи: он назначен всему play.

### 7.1. Команды и реальный объём действий

Примеры выполняются на deployment host с установленным **этим** Kolla-Ansible.
`./multinode` — путь к вашему inventory. Команды приведены для эксплуатации,
при подготовке документа не выполнялись. `genconfig` пишет файлы на хостах,
а `deploy`/`reconfigure` могут прервать доступ к API.

| Команда | Цепочка задач | Что происходит |
| --- | --- | --- |
| `kolla-ansible prechecks -i ./multinode --tags loadbalancer` | `kolla_action=precheck` → `precheck.yml` | Предварительные проверки; не тест аварийного переключения |
| `kolla-ansible genconfig -i ./multinode --tags loadbalancer` | `kolla_action=config` → `config.yml` | Создаёт/перезаписывает host-конфиги, контейнерные handlers не выполняют restart |
| `kolla-ansible pull -i ./multinode --tags loadbalancer` | `pull.yml` → `service-images-pull` | Получает образы; не собирает их и не подтверждает здоровье приложения |
| `kolla-ansible deploy -i ./multinode --tags loadbalancer` | `deploy.yml` → config-host → config → check-containers | Настраивает хост, пишет конфиги, инициирует необходимые старты/restarts |
| `kolla-ansible reconfigure -i ./multinode --tags loadbalancer` | `reconfigure.yml` → `deploy.yml` | Повторяет deploy-цепочку; не только перечитывает globals |
| `kolla-ansible deploy-containers -i ./multinode --tags loadbalancer` | `deploy-containers.yml` → check-containers | Сравнивает/обновляет контейнеры с уже подготовленными конфигами; не заменяет genconfig/config-host |
| `kolla-ansible check -i ./multinode --tags loadbalancer` | `check.yml` → `service-check` | Проверяет наличие/работу контейнеров и unhealthy-статус, если он есть; не Established/маршруты/VIP |
| `kolla-ansible validate-config -i ./multinode --tags loadbalancer` | `config_validate.yml` | Проверяет HAProxy, **не FRR и не watchdog** |

`upgrade.yml` дополнительно удаляет старый HAProxy exporter/container config
перед `deploy.yml`. `stop.yml` вызывает общую роль `service-stop` для включённых
сервисов: это остановка данного контура, не read-only диагностика. Массовый
`stop` для поиска ошибки использовать не нужно.

По умолчанию `kolla_serial` в play — `0`; CLI reconfigure/upgrade также передаёт
значение `0` в этой базе. Следовательно, обещания автоматического rolling
restart по одному loadbalancer нет. Ограничение охвата и окно изменений нужно
планировать отдельно, сохраняя полный inventory для генерации mesh.

### 7.2. config-host.yml

- При `set_sysctl=true` задаёт `net.ipv4.ip_nonlocal_bind=1`, IPv6-аналог при
  доступном IPv6, `net.unix.max_dgram_qlen=128`; обрабатывает
  `haproxy_host_ipv4_tcp_retries2` через общую sysctl-роль.
- При `enable_frr=true` загружает модуль `dummy` и сохраняет автозагрузку через
  `/etc/modules-load.d/dummy.conf`.
- Не назначает VIP на интерфейс: это работа runtime-watchdog после проверок.
- Не настраивает внешние маршрутизаторы, ECMP, BGP ACL, ARP policy или полную
  транзитную маршрутизацию.

### 7.3. config.yml → контейнер → runtime-файл

Пути `/etc/kolla` и `/var/lib/kolla/config_files` ниже — обычные значения
`node_config_directory` и `container_config_directory`, не неизменяемые константы.

| Шаблон / источник относительно роли loadbalancer | Файл на хосте | Куда попадает в контейнере |
| --- | --- | --- |
| `templates/frr/frr.conf.j2` | `/etc/kolla/frr/frr.conf` | `/etc/frr/frr.conf` |
| `templates/frr/daemons.j2` | `/etc/kolla/frr/daemons` | `/etc/frr/daemons` |
| `templates/frr/vtysh.conf.j2` | `/etc/kolla/frr/vtysh.conf` | `/etc/frr/vtysh.conf` |
| `templates/frr/frr.json.j2` | `/etc/kolla/frr/config.json` | Mount как `/var/lib/kolla/config_files/config.json`; задаёт запуск `kolla_frr_run` |
| `templates/anycast-vip/checks.conf.j2` | `/etc/kolla/anycast-vip/checks.conf` | `/etc/anycast-vip/checks.conf` |
| `templates/keepalived/check_alive_*.sh.j2` | `/etc/kolla/anycast-vip/checks/check_alive_*.sh` | `/checks/check_alive_*.sh` |
| `templates/anycast-vip/anycast-vip.json.j2` | `/etc/kolla/anycast-vip/config.json` | Mount config.json; задаёт запуск `kolla_anycast_watchdog` |

Mount конфигурации — read-only. Kolla startup копирует файлы в целевые пути
по `config.json`; создание нового host-файла ещё не доказывает применение его
работающим процессом. `config_files` задаёт FRR owner `frr`, mode `0640`,
checks.conf owner `root`, mode `0640`, каталог checks mode `0770`.

Watchdog получает socket volumes `haproxy_socket` и `proxysql_socket` при
включённых соответствующих сервисах. У обоих контейнеров есть `kolla_logs`,
но это не означает, что весь stdout автоматически записывается туда.

Для FRR/anycast templates задача не использует `with_first_found` для
`node_custom_config`, в отличие от некоторых HAProxy-конфигов. Нельзя считать
произвольный файл `/etc/kolla/config/frr/frr.conf` автоматически поддержанным
override: в этой цепочке такого поиска нет.

### 7.4. Handlers и запуск образов

Общая роль `service-check-containers` сравнивает параметры/конфигурацию и
уведомляет `Restart <service> container`. В handlers FRR расположен раньше
anycast-vip. Это порядок вызова handlers, **не ожидание Established и не
гарантия нулевого перерыва**. При рестарте уже работающей системы VIP может
ещё присутствовать до выполнения следующего handler.

`kolla-pvs/docker/frr/Dockerfile.j2` устанавливает RPM/пакет `frr` через общий
package macro и копирует `frr_run.sh` в `/usr/local/bin/kolla_frr_run`.
Wrapper запускает `frrinit.sh`, ждёт 3 с, затем ищет в running-config две строки:

```text
redistribute connected route-map ANYCAST-ONLY
address-family ipv4 unicast
```

При их отсутствии останавливает демоны и завершается с ошибкой после паузы.
При наличии пишет сообщение о применении конфигурации, но проверяет **только
эти два маркера**, не всех соседей, пароли и route-map. Дальше наблюдает за
демонами и исчезновением адресов. Шаблон `daemons.j2` включает `zebra`/`bgpd`,
выключает `bfdd`, OSPF, VRRP и остальные перечисленные routing daemons.

`docker/anycast-vip/Dockerfile.j2` добавляет `socat`, `mariadb` и копирует
`anycast_watchdog.sh` в `/usr/local/bin/kolla_anycast_watchdog`.
`ip`, `curl`, `timeout`, Bash и утилиты FRR-wrapper должны присутствовать в
итоговом образе; одного просмотра списка пакетов дочернего Dockerfile мало.

Изменение globals, checks или BGP-шаблона доставляется через Ansible без
пересборки runtime-скрипта. Изменение `anycast_watchdog.sh`, `frr_run.sh` или
пакета FRR — изменение образа, требующее сборки и доставки нового образа.

## 8. Что prechecks проверяют, а что остаётся за оператором

Дополнительные anycast-проверки `precheck.yml`:

1. Свободен TCP/179 на API-IP при условии `container_facts.containers['frr']
   is not defined`. Важный дефект этой проверки описан ниже.
2. `modinfo dummy` завершается успешно.
3. Каждый элемент VIP-списка соответствует регулярному выражению
   `^[0-9.]+/32$`.
4. В `loadbalancer` больше одной ноды **или** задан хотя бы один uplink peer.

Проверки «VIP не отвечает» и «VIP находится в подсети интерфейса», рассчитанные
на обычный VRRP-сценарий, при `enable_frr` пропускаются.

**Нюанс повторного prechecks:** задача `Get container facts` в начале этого
файла запрашивает только `haproxy`, `proxysql`, `keepalived`, не `frr`, и
перезаписывает `container_facts`. Поэтому проверка отсутствия FRR не является
надёжной: даже при работающем FRR роль может требовать свободный TCP/179 и
падать на нормально занятом BGP-порту. Не останавливать FRR только ради
прохождения этого precheck; сначала сопоставить ошибку с кодом и `ss`.

Эти prechecks **не подтверждают**:

- Непустой VIP-список: цикл по `[]` ничего не проверяет.
- Валидность октетов IPv4, уникальность адреса или отсутствие конфликта с чужим VIP.
- Положительные корректные значения всех таймеров и счётчиков.
- Взаимное исключение уже работающих Keepalived/BIRD/FRR.
- Непустой checks.conf, тип существующего интерфейса, содержательность проб.
- Состояние BGP Established, TCP MD5 с другой стороны, получение prefix на router.
- Успешный client-to-API failover и сохранение существующих соединений.

У `frr` и `anycast-vip` в словаре сервисов нет собственного container healthcheck.
Поэтому зелёный `check` или статус running не заменяет проверки следующего раздела.

## 9. Пример явной конфигурации

Это **учебная адресация**, не текущие IP Ultra. Предполагаются три loadbalancer
с API-IP `192.0.2.16`, `192.0.2.17`, `192.0.2.18`, один маршрутизируемый VIP
`198.51.100.42` и два uplink-соседа. Физический интерфейс и схему маршрутизации
нужно определить отдельно. Не копировать эти значения в работающий стенд.

```yaml
# /etc/kolla/globals.yml
enable_haproxy: "yes"
enable_proxysql: "yes"
enable_frr: "yes"
enable_keepalived: "no"
enable_bird: "no"

kolla_internal_vip_address: "198.51.100.42"
kolla_external_vip_address: "198.51.100.42"
anycast_vip_addresses:
  - "198.51.100.42/32"
anycast_vip_interface: "dummy0"

anycast_vip_interval: 5
anycast_vip_fall: 3
anycast_vip_rise: 3
anycast_vip_check_timeout: 3
anycast_vip_debug: false

frr_bgp_asn: 65000
frr_bgp_timers_keepalive: 3
frr_bgp_timers_hold: 9
frr_bgp_uplink_peers:
  - address: "192.0.2.1"
    asn: 65001
  - address: "192.0.2.2"
    asn: 65001
```

При двух разных VIP перечислить оба `/32`. Эта настройка означает совместное
снятие обоих адресов, не независимое переключение двух сервисов.

Для ноды с API-IP `192.0.2.16` роль автоматически добавит mesh-соседей
`192.0.2.17` и `192.0.2.18`; `.1`/`.2` появятся только из явного списка uplink.
Реальное соответствие inventory hostname → API-IP должно быть проверено
по facts и результату фильтра `kolla_address`, а не только по `ansible_host`.

BGP-пароли задавать отдельными непустыми согласованными значениями в защищённом
источнике `frr_bgp_md5_mesh_password` / `frr_bgp_md5_uplink_password`.
Не помещать реальные секреты в этот Markdown или диагностические отчёты.
Смена пароля только с одной стороны нарушает сессию. TCP MD5 защищает BGP-сессию,
но не является Keystone-аутентификацией и не шифрует пользовательский API-трафик.

## 10. Ручная диагностика: от watchdog до маршрута

Команды ниже read-only. Выполнять на проверяемом **loadbalancer** с Podman и
sudo-доступом, повторить на остальных loadbalancer. Для Docker использовать
его CLI; systemd-часть ниже относится к Podman/Kolla. Адрес `10.101.25.42`
из прежних примеров Ultra — ориентир: сверить актуальный VIP перед проверкой.
Если выбран не `dummy0`, подставить настоящее имя. Переменные окружения
для подстановок в командах не используются.

### 10.1. Контейнеры, образ и журнал

```bash
sudo -n podman ps -a --filter name=frr --filter name=anycast_vip
sudo -n podman inspect frr anycast_vip --format '{{.Name}} image={{.Config.Image}} imageID={{.Image}}'
sudo -n podman exec frr vtysh -c 'show version'
sudo -n podman exec frr rpm -q frr
sudo -n podman logs --since 30m --tail 300 anycast_vip
sudo -n podman logs --since 30m --tail 300 frr
sudo -n systemctl show kolla-anycast_vip-container.service -p ActiveState -p SubState -p Restart -p NRestarts
sudo -n systemctl show kolla-frr-container.service -p ActiveState -p SubState -p Restart -p NRestarts
sudo -n journalctl -u kolla-anycast_vip-container.service -u kolla-frr-container.service --since '-30 min' --no-pager -n 300
```

`rpm -q` — для RPM-based образа, как на Ultra. Наличие номера версии ещё
не подтверждает, что все команды frr.conf применились. Watchdog пишет в stdout
с префиксом `[watchdog]`; FRR-wrapper — `[frr]`. Routing daemons в шаблоне
настроены на syslog, поэтому их сообщения могут находиться не в stdout wrapper.
Один mount `kolla_logs` не гарантирует конкретный файл `/var/log/kolla/frr/...`.

### 10.2. Доставленные параметры и проверки

```bash
sudo -n podman inspect anycast_vip --format '{{range .Config.Env}}{{println .}}{{end}}' | grep '^ANYCAST_'
sudo -n podman inspect frr --format '{{range .Config.Env}}{{println .}}{{end}}' | grep '^ANYCAST_'
sudo -n sed -n '1,120p' /etc/kolla/anycast-vip/checks.conf
sudo -n podman exec anycast_vip sed -n '1,120p' /etc/anycast-vip/checks.conf
sudo -n podman exec anycast_vip ls -l /checks /var/lib/kolla/haproxy/haproxy.sock /var/lib/kolla/proxysql/admin.sock
sudo -n podman exec anycast_vip timeout 5 /checks/check_alive_haproxy.sh
sudo -n podman exec anycast_vip timeout 5 /checks/check_alive_proxysql.sh
```

Запускать только пробы включённых сервисов. У этих скриптов успешный результат
обычно без вывода; важен код возврата. Здесь timeout 5 с — диагностический,
а не изменение рабочего `ANYCAST_CHECK_TIMEOUT`. При custom `exec` сначала
проверить его содержимое: произвольный скрипт не обязательно read-only.

### 10.3. Адреса, policy routing и Linux FIB

```bash
ip -d link show dummy0
ip -4 -brief addr show dev dummy0
ip -4 rule show
ip -4 route show table local
ip -4 route show table main
ip -4 route get 10.101.25.42
sysctl net.ipv4.ip_nonlocal_bind net.ipv4.ip_forward
sysctl net.ipv4.conf.all.rp_filter net.ipv4.conf.default.rp_filter
sudo -n ss -lntp 'sport = :179'
```

Когда VIP локален, `route get` обычно показывает `local`; после снятия адреса
нужен путь через достижимого соседа. Значения `rp_filter` проверять также на
конкретных входных интерфейсах. Если dummy есть, но адреса нет, это может быть
штатный `DOWN` watchdog. Если адрес есть, а контейнер мёртв — это не штатное
подтверждение здоровья, см. ограничения ниже.

### 10.4. BGP RIB, соседи и применённая конфигурация

```bash
sudo -n podman exec frr vtysh -c 'show bgp ipv4 unicast summary'
sudo -n podman exec frr vtysh -c 'show bgp ipv4 unicast'
sudo -n podman exec frr vtysh -c 'show bgp ipv4 unicast 10.101.25.42/32'
sudo -n podman exec frr vtysh -c 'show ip route 10.101.25.42/32'
sudo -n podman exec frr vtysh -c 'show bgp neighbors'
sudo -n podman exec frr vtysh -c 'show running-config' | sed -E 's/( password ).*/\1<redacted>/'
sudo -n sed -E 's/( password ).*/\1<redacted>/' /etc/kolla/frr/frr.conf
```

Проверить ожидаемое количество соседей, состояние Established, реальные
таймеры, next hop, prefix-list и route-map. Локальная BGP RIB и маршрут ядра —
разные уровни проверки; синтаксис show-команд см. в
[FRR BGP](https://docs.frrouting.org/en/stable-10.0/bgp.html#displaying-bgp-information)
и [FRR Zebra](https://docs.frrouting.org/en/stable-10.0/zebra.html).

Для проверки анонса конкретному uplink используется следующая форма.
`192.0.2.1` здесь **учебный адрес соседа**, заменить на фактический:

```bash
sudo -n podman exec frr vtysh -c 'show bgp ipv4 unicast neighbors 192.0.2.1 advertised-routes'
```

На самом маршрутизаторе отдельно проверить получение `/32`, выбранный next hop
и FIB. Локальное `advertised-routes` не подтверждает, что router принял маршрут
и установил его в forwarding table.

Не прикладывать исходный running-config с BGP-паролями. Приведённый `sed`
маскирует обычные строки `password`; это не универсальный фильтр любых секретов
и не замена просмотру отчёта перед передачей.

### 10.5. Проверка прикладного пути

На deployment host в обычном окружении OpenStack CLI, **без sudo**:

```bash
timeout 25s openstack workflow list
timeout 25s openstack compute service list
```

Сопоставить результат с проверкой маршрута к VIP и состоянием backend.
`ping VIP`, Established и успешный socket check по отдельности не доказывают
работоспособность API. Запрос с самого loadbalancer может идти локально;
для проверки внешнего failover нужен независимый клиентский путь.

## 11. Известные ограничения этой реализации

Это результаты чтения указанных исходников, а не утверждение, что все эти
ситуации уже произошли на Ultra.

| Ситуация | Что следует из кода / чего не следует обещать |
| --- | --- |
| Watchdog получил TERM/INT и смог выполнить `ip addr del` | Адреса снимаются; это штатный путь остановки |
| SIGKILL, OOM, crash или зависший watchdog при живом хосте | Trap может не выполниться. Host-network адрес останется, FRR может продолжить локальный анонс. `restart_policy: no` не обеспечивает cleanup |
| FRR упал, watchdog продолжает работать | Socket-пробы могут оставаться успешными, VIP — локальным; проверка здоровья FRR в checks.conf не включена |
| Контейнер watchdog стартует с пустым VIP-списком | Ошибка обязательной переменной, работа не начинается |
| checks.conf пустой/содержит только комментарии | `all_checks_pass()` не находит ошибок и возвращает успех; отдельного запрета пустого набора нет |
| Файл checks перестал читаться после старта | Проверка читаемости есть только на старте; функция не переводит ошибку открытия файла в обязательный неуспех. Нельзя полагаться на fail-closed |
| Адрес вручную удалили, когда внутреннее состояние UP | Постоянного сравнения state с фактическим адресом в основном цикле нет; успешные пробы сами по себе не вызывают повторный add в UP |
| Частично не удался add/delete нескольких VIP | Операция не атомарна; возможен неполный набор и расхождение с внутренним state |
| Все LB теряют доступность одного проверяемого proxy | Общая AND-политика может снять все VIP; кластерной координации/minimum-survivors в watchdog нет |
| API/backend завис, но локальный socket отвечает | VIP может не сниматься; это ограничение глубины проб |
| Локальный connected VIP снят, но есть маршрут от mesh | Префикс может остаться в BGP и экспортироваться на uplink; проверить транзит, как в разделе 3.4 |
| `enable_frr=false` или поменяли VIP/interface | Нет автоматической полной очистки предыдущих адресов/disabled-контейнеров. Новый процесс знает новый список, а старые остатки требуют проверки |

Порядок «сначала VIP удалить, потом перестать объявлять» связан с жизненным
циклом IP в ядре. Здесь нет независимого lease/TTL, автоматически снимающего
адрес при смерти watchdog. Не путать этот механизм с Consul TTL или гарантией
fencing в PowerOps.

## 12. Минимальные критерии приёмки на стенде

До отдельного согласованного fault-теста сохранить исходное состояние и
убедиться, что остаётся доступ к управлению вне проверяемого VIP.

1. Сверены фактические образы, runtime-скрипты, globals и inventory; список VIP
   непуст, все адреса ожидаемые `/32`, Keepalived/BIRD не конкурируют с FRR.
2. На исправных нодах socket-пробы успешны, нужные VIP присутствуют, конфиги
   в контейнерах соответствуют доставленным, mesh Established.
3. Для внешнего пути router получает нужные префиксы и имеет корректную FIB;
   проверен также сценарий транзита через ноду без локального VIP, если он возможен.
4. При согласованном отказе проверяемого сервиса отмечены отдельные моменты:
   первая неуспешная проба → снятие адреса → изменение BGP/FIB → результат
   запроса с независимого клиента. Считать отдельно обрывы старых TCP-сессий.
5. После восстановления возврат адреса происходит по rise-серии; нет
   непрерывного снятия/возврата и неожиданного второго владельца от VRRP.
6. Отдельно исследованы отказ самого watchdog, остановка FRR и reboot хоста:
   один успешный тест остановки HAProxy не покрывает эти три случая.

Этот документ не выполняет такие fault-тесты и не предлагает запускать их
без окна изменений. Для исправлений обнаруженных ограничений нужен отдельный
патч и отдельная приёмка, а не только обновление Markdown.

## 13. Что проверено при подготовке документа

- SHA256 двух исходных архивов; конечные YAML-значения и восемь дублируемых ключей.
- Четыре синтетических рендера шаблонов: три LB с uplink, один LB с uplink,
  mesh без uplink с двумя VIP, пустой набор service checks. Адресный фильтр
  использовал тестовое отображение hostname → IP; это не запуск полного Ansible.
- Разбор JSON-шаблонов, YAML-примера и `bash -n` для shell-примеров/скриптов.
- Семь штатных offline-проверок репозитория, включая Markdown-ссылки.

Эти проверки не запускают `bgpd`, не валидируют конфигурацию бинарным FRR,
не устанавливают BGP-сессию и не измеряют live failover. Для этого нужны
отдельные проверки собранного образа и согласованный стендовый прогон.
