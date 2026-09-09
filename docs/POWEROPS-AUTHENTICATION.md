# PowerOps: служебные пользователи, роли и межсервисная авторизация

Дата сверки: **9 сентября 2026 года**.

База — пользовательские архивы `0809`, включённое в Kolla исправление
service-role для Masakari и дополнительный патч ожидания Nova down после fencing.
`planned-return-v2` не рассматривается. Описание сверено с исходниками и
предоставленными результатами диагностики; это не проверка текущей конфигурации
всех контейнеров стенда.

Связанные документы:

- [Устройство и сценарии](POWEROPS-OVERVIEW.md).
- [Ручная диагностика всей цепочки](POWEROPS-DIAGNOSTICS.md).
- [Globals, шаблоны и тайминги](POWEROPS-CONFIGURATION.md).

## 1. Главное различие: оператор и сервис — разные пользователи

Успех `openstack baremetal node list` из admin-shell не доказывает, что такой же
запрос разрешён Masakari. В этой реализации существуют отдельные пути доступа:

| Кто обращается | Куда | Чья учётная запись используется по шаблонам 0809 |
| --- | --- | --- |
| Оператор / OpenStack CLI | Keystone, затем Mistral API | Пользователь из выбранного CLI auth-профиля |
| Mistral executor / PowerOps action | Nova, Ironic, Masakari | `mistral_keystone_user`, по умолчанию `mistral`, project `service` |
| Masakari-hostmonitor | Masakari API | `masakari_keystone_user`, по умолчанию `masakari`, project `service` |
| Masakari engine / fencing | Ironic API | `masakari_keystone_user`, project `service` |
| Masakari engine / операции с ВМ и compute service | Nova API | `os_privileged_user_name`, в шаблоне **`nova_keystone_user`**, project `service` |
| API middleware каждого сервиса | Keystone для проверки входящих токенов | Собственный auth-профиль `[keystone_authtoken]` соответствующего API |
| Kolla-Ansible при регистрации | Keystone | Deployment-профиль `openstack_auth` / сервисный override; по умолчанию административный |
| Ironic conductor | BMC физического узла | BMC credentials драйвера; это **не** Keystone-пользователь |

Имена пользователей настраиваются: литералы `mistral`, `masakari`, `nova`,
`ironic` — значения по умолчанию, а не обязательные имена во всех инсталляциях.

В Mistral сначала проверяются права инициатора PowerOps action. Затем action
создаёт отдельный SDK-клиент с сервисными credentials. Токен оператора не
подставляется вместо сервисного токена в этом клиенте. Поэтому возможны обе
ситуации: оператору разрешён запуск, но сервису запрещён Ironic API; либо сервис
имеет доступ к Ironic, но конкретному оператору запрещён action.

## 2. Что именно означает `service`

| Понятие | Значение | Что с ним нельзя смешивать |
| --- | --- | --- |
| User | Учётная запись Keystone с UUID и domain | Linux-пользователь контейнера или оператор, запустивший CLI |
| Project | Область project-scoped назначения; в шаблонах это project `service` | Роль с таким же именем |
| Role | Например, `admin`, `service`, `powerops_operator` | Имя пользователя или service type из каталога |
| Scope токена | Project, system или другая поддерживаемая область | Назначение роли в другом проекте не переносится автоматически |
| Authentication | Проверка личности и выдача/валидация токена | Разрешение конкретного API-действия |
| Authorization | Проверка policy действия с ролями, scope и целевым ресурсом | Простое наличие действительного токена |

`masakari` в project `service` **не получает роль `service` из имени проекта**.
Роль должна существовать, быть назначена нужному субъекту в нужной области и
присутствовать в токене, с которым выполняется запрос. Project-scoped `admin`
также не следует считать универсальным system-scoped администратором.

### Основной токен и дополнительный service token

`X-Auth-Token` несёт основную идентичность запроса. В межсервисном запросе ею
может быть служебный пользователь. `X-Service-Token` — отдельный дополнительный
токен; его наличие не следует из роли `service` у основного пользователя.
Middleware проверяет эти токены раздельно. Настройки `service_token_roles` и
`service_token_roles_required` регулируют проверку дополнительного токена,
а не создают роль и не назначают её пользователю.
[Документация keystonemiddleware 2025.1](https://docs.openstack.org/keystonemiddleware/2025.1/middlewarearchitecture.html).

В проверенных фабриках PowerOps SDK Mistral и Masakari нет настройки отдельного
`X-Service-Token`: они создают собственную password-auth session. Не надо
объяснять наш отказ Ironic отсутствием этого дополнительного заголовка.
Отдельно Nova-шаблон содержит `[service_user].send_service_user_token=true` для
клиентских путей Nova, использующих этот механизм; это не настройка SDK Mistral.

## 3. Роли в поставляемой конфигурации

Таблица описывает регистрацию Kolla0809, а не новую минимальную RBAC-модель.
Изменение этих полномочий требует отдельного анализа policy всех вызываемых API.

| Пользователь из переменной | Project | Роли, заданные регистрацией |
| --- | --- | --- |
| `mistral_keystone_user` | `service` | `admin`; дополнительно `service` при `enable_powerops=true` |
| `masakari_keystone_user` | `service` | `admin`; дополнительно `service` при `enable_powerops=true` |
| `nova_keystone_user` | `service` | `admin`, `service` |
| `ironic_keystone_user` | `service` | `admin`, `service` |

Регистрация находится в `ansible/roles/<service>/defaults/main.yml` и
`tasks/register.yml`; общие операции — в роли `service-ks-register`.

- Masakari при включённом PowerOps также запрашивает создание роли `service`.
  При выключенном PowerOps список дополнительных назначений пуст: это не
  явный отзыв ранее выданной роли.
- Mistral задаёт дополнительному назначению `state=present` при включении и
  `state=absent` при выключении PowerOps. Сам этот дополнительный assignment
  не доказывает, что роль была предварительно создана.
- Отдельное system-scope назначение `service` для Ironic Inspector не является
  образцом настройки Masakari: это другая учётная запись и другой путь.
- Defaults — желаемое состояние регистрации. После доставки надо проверить
  реальные назначения в Keystone, а не только наличие строк в YAML.

### Полномочия оператора Mistral

Дополнительная проверка `mistral/services/powerops.py:authorize` допускает:

1. Аутентифицированную роль `admin`; либо
2. Роль `powerops_operator` **одновременно** с точным совпадением project name
   и user name в обоих allowlists.

`allow_hard_off=true` требует `admin`; target-контекст (`is_target=true`)
отклоняется. Одного флага `is_admin` без подтверждённых ролей недостаточно.
Роли берутся из аутентифицированного request context, а не из workflow JSON.
Допуск API-запроса политикой Mistral — отдельная проверка до исполнения action.

`powerops_allowed_project_names` и `powerops_allowed_user_names` не создают
пользователей или роль `powerops_operator` и не назначают её. В проверенном
Mistral defaults/register пути такого создания нет. Эти allowlists также
не являются списком разрешённых compute-хостов и не содержат domain IDs.
Выдавать человеку роль `service` для обхода проверки оператора не следует.

## 4. Где задаются credentials и выбор API

Ниже `ansible/roles/...` — пути внутри Kolla-Ansible. Секреты указаны только
именами переменных. Их значения не нужно копировать в документацию или отчёт.

| Путь / секция | Основные поля и источник | Важная особенность |
| --- | --- | --- |
| `mistral/templates/mistral.conf.j2` → `/etc/mistral/mistral.conf`, `[keystone_authtoken]` | `auth_url=keystone_internal_url`, `username=mistral_keystone_user`, `password=mistral_keystone_password`, `project_name=service`, `user_domain_id=default_user_domain_id`, `project_domain_id=default_project_domain_id`, `cafile=openstack_cacert` | Этот же профиль использует фабрика PowerOps SDK Mistral, с явно созданным v3 Password auth |
| Mistral `[powerops]` | `region_name`, `interface` | Выбирает endpoints PowerOps SDK; `[openstack_actions].os_actions_endpoint_type` — другой клиентский путь |
| `masakari/templates/masakari.conf.j2` → `/etc/masakari/masakari.conf`, `[keystone_authtoken]` | `auth_type=password`, `auth_url=keystone_internal_url`, `username=masakari_keystone_user`, `password=masakari_keystone_password`, `project_name=service`, `default_user_domain_name` / `default_project_domain_name` → соответствующие domain name-поля, `cafile=openstack_cacert` | Этот профиль использует Masakari PowerOps Ironic SDK; session учитывает `insecure`, `cafile`, `certfile`, `keyfile` |
| Masakari `[powerops]` | `region_name`, `interface` | Выбор endpoint Ironic SDK; не переключает Nova-клиент ниже |
| Masakari `[DEFAULT]` | `os_privileged_user_name=nova_keystone_user`, `os_privileged_user_password=nova_keystone_password`, `os_privileged_user_tenant=service`, `os_privileged_user_auth_url=keystone_internal_url` | Отдельные credentials для Nova, не Masakari service user |
| Masakari `[DEFAULT]`, Nova scope/TLS/catalog | `os_user_domain_name`, `os_project_domain_name`, `os_system_scope`, `os_region_name`, `nova_catalog_admin_info`, `nova_ca_certificates_file`, `nova_api_insecure` | Не все опции отображены в Jinja; используются также defaults компонента |
| `masakari/templates/masakari-monitors.conf.j2` → `/etc/masakari-monitors/masakari-monitors.conf`, `[api]` | `username=masakari_keystone_user`, `password=masakari_keystone_password`, `project_name=service`, `user_domain_id`, `project_domain_id`, `auth_url`, `region`, `api_interface=internal`, `cafile`; при internal mTLS также `certfile`, `keyfile` | Проверяется отдельно от engine: другой контейнер и отдельный конфиг |
| `ironic/templates/ironic.conf.j2` → `/etc/ironic/ironic.conf`, `[DEFAULT]` | `rbac_service_role_elevated_access=true` | Настройка принимающего Ironic API, а не клиентская роль Masakari |
| Ironic `[keystone_authtoken]` | `username=ironic_keystone_user`, `password=ironic_keystone_password`, `project_name=service`, auth URL, domain IDs, CA | Собственный профиль middleware; не выдаёт полномочия входящему пользователю Masakari |
| `nova/templates/nova.conf.j2`, `[service_user]` и `[keystone_authtoken]` | `nova_keystone_user`, `nova_keystone_password`, project `service`, domain IDs, Keystone URL | Не заменяет настройки `os_privileged_user_*` в Masakari |

Переменные с паролями разрешаются механизмом секретов конкретной Kolla-инсталляции
при рендеринге. Для диагностики важен конфиг, действительно загруженный процессом
в контейнере. Совпадение `globals.yml` с ожиданиями ещё не доказывает, что новый
секрет попал на все реплики. Не публикуйте целиком `passwords.yml`, конфиги,
`podman inspect` с environment или дамп Keystone-токена.

### Домены, scope и endpoints: места для отдельной проверки

- В globals defaults `Default` — имя домена, `default` — его ID. Это разные поля.
  Mistral PowerOps требует полную пару domain IDs; при отсутствии IDs — полную
  пару domain names. Смешанная или неполная пара не является корректным fallback.
- В Masakari Jinja опции **`os_user_domain_name` / `os_project_domain_name`**
  получают **`default_*_domain_id`**. Проверить их соответствие реальным именам
  доменов нужно отдельно; не переносить эту подстановку как универсальный образец.
- Для Masakari Nova-клиента code default `nova_catalog_admin_info` равен
  `compute:nova:publicURL`. `[powerops].interface=internal` его не меняет.
  Project credentials шаблона не следует молча заменять system scope.
- Kolla регистрирует Mistral как `workflowv2`, Masakari как `instance-ha`, Ironic
  как `baremetal`. Mistral PowerOps создаёт HA adapter с `service_type='ha'`,
  `version='1'`: разрешение alias и версия endpoint зависят от установленного SDK
  и реального каталога. Неверный UUID/endpoint нельзя автоматически считать RBAC.
- Для Mistral PowerOps `cafile` либо системная CA используются с проверкой TLS.
  Эта фабрика не переносит автоматически все TLS-опции middleware. Для Masakari
  Ironic и Nova действуют разные session/TLS настройки, перечисленные выше.

## 5. Наш случай: Masakari не мог прочитать Ironic nodes

В диагностике от 7 сентября принимающий Ironic API зафиксировал:

```text
user_name=masakari project_name=service system_scope=-
baremetal:node:list_all is disallowed by policy
```

В показанном списке effective assignments были `admin`, `manager`, `member`,
`reader`, но отсутствовала `service`. Это был отказ авторизации конкретного
запроса Masakari, а не доказательство неверного пароля оператора. Effective roles
могут включать следствия иерархии ролей; их наличие не означает четыре отдельных
ручных назначения.

Для стандартной policy Ironic 2025.1 опция
`rbac_service_role_elevated_access` разрешает повышенный доступ пользователям
с ролью `service` из проекта `rbac_service_project_name` (по умолчанию `service`).
Upstream default первой опции — `false`; проверенный Kolla-шаблон устанавливает
`true`. Реальные policy overrides и настройки API всё равно надо учитывать.
[Опции Ironic 2025.1](https://docs.openstack.org/ironic/2025.1/configuration/config.html#DEFAULT.rbac_service_role_elevated_access).

После появления роли `service` свежий диагностический процесс показал
`AUTH: masakari service [...] service`, нашёл один нужный узел и прочитал его
состояние. Это подтверждало исправление показанного пути чтения на момент
проверки. Это не доказательство всех write-permissions или обновления токенов
во всех уже работающих engine-процессах.

Исправление назначения роли относится к **Kolla-Ansible**, файл пакета:

```text
hotfixes/masakari-service-role-and-revert/0001-fix-grant-Masakari-service-role-for-PowerOps.patch
```

Этот patch уже учтён в проверенных Kolla0809. Он создаёт/назначает `service`
для выбранного Masakari service user и сохраняет `admin`. Отдельный patch
компонента Masakari о корректном сообщении при неподтверждённом fencing не
назначает Keystone-роли и не заменяет это исправление.

Если перечисление узлов запрещено, fencing-код не доходит до подтверждения
выключения. Такой отказ должен остановить безопасную цепочку до эвакуации;
наличие Nova `down` или потеря LAN не дают права считать fencing успешным.

## 6. Безопасные ручные проверки

Команды ниже читают состояние и получают диагностические токены, но не меняют
роли, ВМ, питание, maintenance или конфигурацию. Их нельзя использовать как
полноценную приёмку изменяющих операций.

### 6.1. Назначения в Keystone — с управляющего хоста

Выполнять на `ultra1-0` или другом управляющем хосте с авторизованным CLI и
правом читать пользователей/назначения. Укажите UUID именно service user,
взятого из конфигурации проверяемого клиентского пути, и UUID его проекта:

```bash
set +x
read -r -p 'Keystone service user UUID: ' POWEROPS_AUTH_USER
read -r -p 'Keystone project UUID: ' POWEROPS_AUTH_PROJECT
timeout 30s openstack user show "$POWEROPS_AUTH_USER" -f yaml -c id -c name -c domain_id -c enabled
timeout 30s openstack project show "$POWEROPS_AUTH_PROJECT" -f yaml -c id -c name -c domain_id -c enabled
timeout 30s openstack role assignment list --user "$POWEROPS_AUTH_USER" --effective --names -f json
timeout 30s openstack role assignment list --user "$POWEROPS_AUTH_USER" --project "$POWEROPS_AUTH_PROJECT" --effective --names -f json
```

Проверить user/project/domain UUID, область назначения и `service` в нужном
проекте. Для пути Masakari → Nova отдельно повторить проверку пользователя
из `os_privileged_user_name`, а не ограничиваться пользователем `masakari`.
Назначения сейчас и содержимое ранее выданного токена — разные наблюдения.

### 6.2. Реальный клиентский профиль — на контроллере с контейнером

Следующие команды запускать **в shell контроллера**, не в Python REPL и не на
аварийном compute. Сначала определить фактическое имя контейнера:

```bash
sudo -n podman ps --format '{{.Names}}'
```

Примеры используют имена `masakari_engine` и `mistral_executor`; при отличии
заменить их. Каждый пример — одна физическая строка команды, даже если экран
визуально переносит её. Создаётся новый Python-процесс с конфигом существующего
контейнера; повторный `CONF` parse внутри прежнего REPL не нужен.
`timeout` работает внутри контейнера; проверить наличие этой утилиты в образе.

**Masakari → Keystone → Ironic**, основной профиль fencing. Печатаются только
метаданные токена и факт успешного ограниченного чтения списка:

```bash
sudo -n podman exec masakari_engine timeout -k 2s 30s /var/lib/kolla/venv/bin/python -B -c 'from masakari import conf; from masakari.powerops import ironic; conf.CONF(args=[], project="masakari", default_config_files=["/etc/masakari/masakari.conf"]); c=ironic.connection_from_conf(); c.session.timeout=15; a=c.session.auth.get_access(c.session); print("AUTH:", a.username, a.user_id, a.project_name, a.project_id, sorted(a.role_names)); n=next(c.baremetal.nodes(details=True, limit=1), None); print("IRONIC LIST OK; first node present:", n is not None)'
```

`first node present: False` означает пустой результат, а не обнаружение нужного
узла. Даже непустой результат ещё не подтверждает доступ к конкретному source.
Дальше проверить его точное имя/UUID по общему документу диагностики.

**Masakari → Nova**, отдельный privileged-профиль через штатную фабрику клиента.
Запрос только читает compute services; credentials не выводятся:

```bash
sudo -n podman exec masakari_engine timeout -k 2s 30s /var/lib/kolla/venv/bin/python -B -c 'from masakari import conf, context; from masakari.compute import nova; conf.CONF(args=[], project="masakari", default_config_files=["/etc/masakari/masakari.conf"]); n=nova.novaclient(context.get_admin_context(), timeout=15); print("NOVA USER CONFIG:", conf.CONF.os_privileged_user_name, conf.CONF.os_privileged_user_tenant); print("NOVA SERVICES GET OK; count:", len(n.services.list(binary="nova-compute")))'
```

Здесь `get_admin_context()` создаёт локальный контекст для фабрики, а не выдаёт
Keystone-полномочия. Удалённый запрос всё равно аутентифицируется через
`os_privileged_user_*`. Напечатанное имя — значение конфига, не расшифровка токена;
фактическую user/project идентичность сверять по принимающему Nova API и request ID.

**Mistral PowerOps → Keystone → Nova**, сервисный профиль executor:

```bash
sudo -n podman exec mistral_executor timeout -k 2s 30s /var/lib/kolla/venv/bin/python -B -c 'from mistral import config; from mistral.actions.powerops import clients; config.parse_args(args=[], default_config_files=["/etc/mistral/mistral.conf"]); c=clients.connection_from_conf(); c.session.timeout=15; a=c.session.auth.get_access(c.session); print("AUTH:", a.username, a.user_id, a.project_name, a.project_id, sorted(a.role_names)); s=next(c.compute.services(binary="nova-compute"), None); print("NOVA SERVICES GET OK; first service present:", s is not None)'
```

Это не проверяет Ironic и Masakari от имени Mistral. Отдельное ограниченное
чтение обоих API тем же способом создания сервисного клиента:

```bash
sudo -n podman exec mistral_executor timeout -k 2s 45s /var/lib/kolla/venv/bin/python -B -c 'from mistral import config; from mistral.actions.powerops import clients; config.parse_args(args=[], default_config_files=["/etc/mistral/mistral.conf"]); c=clients.connection_from_conf(); c.session.timeout=15; n=next(c.baremetal.nodes(details=True, limit=1), None); print("IRONIC LIST OK; first node present:", n is not None); h=clients.CloudClients(c); r=h.ha_adapter.get("/segments", params={"limit": 1}, timeout=15); print("MASAKARI SEGMENTS HTTP:", r.status_code)'
```

Проверки повторяются на каждой нужной реплике. Успех свежего процесса не
доказывает, что уже запущенный daemon использует свежий токен и тот же загруженный
конфиг. Для hostmonitor отдельно сверить `[api]` его конфигурации и исходящий
запрос в Masakari API: успех engine не покрывает monitor.

Для доказательства обращения к принимающему API сверять также его свежую запись
запроса. Новый Python-процесс сам по себе не исключает общий SDK response cache,
если он включён в инсталляции. Его состояние проверяется отдельно; приведённые
команды не меняют cache-настройки работающих сервисов.

### 6.3. Что нельзя выводить в общий отчёт

Не включать `set -x`, `openstack --debug`, HTTP debug/trace и полный `print(a)`
или `print(a.auth_token)`. Не выводить `driver_info`, connection objects,
полный environment и файлы с секретами. Даже сообщения об ошибках перед
передачей отчёта надо просмотреть на токены, пароли и URL с credentials.

## 7. Как интерпретировать ошибку и локализовать её

| Наблюдение | Что проверять сначала |
| --- | --- |
| Не получен токен / HTTP 401 | Какой клиентский профиль, auth URL, user/project/domain, секрет, срок токена; журнал Keystone и API |
| HTTP 403 / `PolicyNotAuthorized` | Точное policy action, user/project/scope/roles запроса на принимающей стороне; назначения сами по себе недостаточны |
| HTTP 404 | UUID, версия и путь API, регион/interface/catalog, видимость ресурса согласно policy; не считать автоматически ошибкой пароля |
| HTTP 504, timeout, HTTP 000 от curl | Доступность VIP/backend, зависимостей API и задержки; сам по себе такой код не доказывает RBAC-причину |
| Admin CLI работает, service SDK нет | Сравнить личности, scope, CA и выбранные endpoints; это разные запросы |
| Одна реплика работает, другая нет | Образ, загруженный конфиг, токен процесса, каталог и сеть конкретной реплики |

Для связи клиентской ошибки с серверным решением сохранить время, компонент,
request ID и имя API-действия. Искать прежде всего на **принимающей** стороне:
для отказа Masakari → Ironic — в `ironic-api-wsgi.log`, для Masakari → Nova —
в Nova API log, для hostmonitor → Masakari — в Masakari API log. Пути логов,
выбор интервала и сбор по репликам описаны в документе ручной диагностики.

Уведомление, workflow execution и API request имеют разные ID. Нельзя считать
старую notification другого хоста объяснением текущего auth-отказа.

## 8. Порядок исправления и границы приёмки

1. Определить конкретный клиентский путь и фактическую учётную запись.
2. Сверить assignments, project/domain IDs и policy принимающего API.
3. Исправить желаемую регистрацию/конфигурацию согласованным deployment-путём.
   Изменение Keystone-роли само по себе не требует пересборки образа. Но наличие
   patch в репозитории не применяет назначение: должен выполниться соответствующий
   registration task. Не считать любой `reconfigure` гарантией его выполнения.
4. Получить свежий диагностический токен и проверить безопасный GET нужного API.
5. Проверить остальные реплики и поведение работающего сервиса по свежему запросу.
   Обновление daemon/config/credentials выполняется отдельно в согласованном окне.
6. Изменяющие API-права и полную цепочку подтвердить отдельным согласованным
   стендовым сценарием. Не выполнять power-off или evacuation «для проверки роли».

Не отключать policy, scope-проверки или TLS; не выдавать всем system admin;
не очищать общий memcached и не перезапускать всё облако как диагностический шаг.
Ротация пароля, изменение assignments и обновление процесса — разные операции.
Keystone/token-validation cache также не равен SDK response cache:
отключение последнего не выдаёт роли и не исправляет отказ авторизации.

RabbitMQ, БД, etcd/tooz, Consul и BMC имеют собственные механизмы доступа
(учётные записи, ACL, сертификаты — в зависимости от backend и конфигурации).
Keystone-роль `service` их не заменяет. Успешная аутентификация к OpenStack API
не доказывает доступность coordination lock, RPC, БД или BMC.

### Проверенные исходные точки

- Mistral: `mistral/actions/powerops/clients.py:connection_from_conf`,
  `CloudClients`; `mistral/services/powerops.py:authorize`.
- Masakari: `masakari/powerops/ironic.py:connection_from_conf`,
  `IronicPowerClient.fence`; `masakari/compute/nova.py:novaclient`;
  `masakari/conf/nova.py`.
- Kolla: роли `mistral`, `masakari`, `nova`, `ironic` — `defaults/main.yml`,
  `tasks/register.yml`, соответствующие `templates/*.conf.j2`;
  роль `service-ks-register`; `ansible/group_vars/all.yml`.

Эти источники подтверждают wiring поставки. Установленные policy overrides,
секреты, выданные токены, загруженные конфиги и доступность всех endpoints
подтверждаются только отдельными runtime-наблюдениями.
