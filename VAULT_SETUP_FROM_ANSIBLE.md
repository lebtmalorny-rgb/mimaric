# Настройка HashiCorp Vault для Kolla-Ansible PVS 1.0.0

Инструкция восстановлена по исходникам архива `kolla-ansible-pvs_1.0.0_14.09.zip`.

В этой ветке опубликована только инструкция. Архив, распакованные исходники и локальные протоколы проверок в репозиторий не включены. Ссылки на исходники ниже указаны как пути относительно корня распакованного архива `kolla-ansible-pvs_1.0.0/`.

- Дата анализа: **15 сентября 2026 года**.
- SHA-256 архива: `bbb7bfb1398cbe07a12e374cae56f03e9e5c192798cf3ff7842aa75d8c2d7e44`.
- Распакованные исходники: `kolla-ansible-pvs_1.0.0/`.
- Проверка выполнена по коду и локальным тестам. Подключений к действующему Vault и запусков Ansible на узлах не было.

## 1. Краткий вывод

Архив содержит **форк Kolla-Ansible с собственными ролями, модулями и Python CLI**. Коллекция `openstack.kolla` указана как внешняя зависимость. Готовой роли установки сервера Vault, создания KV engine, ACL-политик и AppRole в архиве не найдено.

Для работы интеграции администратор отдельно готовит **существующий и распечатанный (unsealed) Vault**, KV v2, две AppRole и прикладные секреты. Затем Kolla устанавливает на управляемые узлы сервис `kolla-vault-agent`, который получает и обновляет runtime SecretID. Контейнеры используют эти учётные данные для получения секретов.

**Это собственный Python-сервис, а не бинарник HashiCorp Vault Agent.** Установка стандартного `vault agent` не заменяет роль из архива.

Основной сценарий: пароли находятся в Vault KV v2; источник сертификатов выбирается независимо — `local`, `kv` или `pki`. Прикладные KV-секреты штатный deploy только читает. Хостовый агент создаёт SecretID и wrapped token; PKI-режим дополнительно выпускает сертификаты.

Ниже приведён пример для `prod-cloud / RegionOne`. Адреса, имена узлов и сроки жизни — **параметры примера**, а не обнаруженная конфигурация стенда. Установка, HA, storage, seal/unseal и резервное копирование самого Vault требуют отдельного регламента: восстановить его из этого архива нельзя.

### 1.1. Общий поток движения секретов

**Администратор загружает значения в Vault → Ansible размещает ссылки → контейнер получает значения по runtime AppRole → сервис использует готовую конфигурацию.** Для ограниченного набора bootstrap-паролей есть дополнительный путь через память процесса Ansible. Ниже показано движение данных при включённой интеграции; установка самого Vault выполняется заранее.

```mermaid
flowchart TD
    operator["Администратор: подготовить пароли, ключи и сертификаты"]
    kv["Vault KV v2: прикладные значения"]
    refs["Deploy-хост: passwords.yml со ссылками"]
    pointers["Ansible: конфиги и pointer-файлы на узлах"]
    runtime["Контейнер: доработанный Kolla runtime"]
    auth["Runtime RoleID и SecretID: tmpfs узла"]
    ram["Приватный tmpfs контейнера: разрешённые значения"]
    service["OpenStack и инфраструктурные сервисы"]
    fetch["Управляемый узел: kolla_vault_get"]
    facts["Deploy-хост: bootstrap-пароли в памяти Ansible"]
    setup["Подготовка и регистрация сервисов"]
    adminfiles["При post-deploy: клиентские файлы 0600 на deploy-хосте"]
    pki["Vault PKI: выпуск сертификатов в режиме pki"]
    operator -->|"заполнить KV"| kv
    refs --> pointers
    pointers -->|"передать ссылки"| runtime
    auth -->|"аутентификация"| runtime
    kv -->|"получить по ссылке"| runtime
    pki -.->|"сертификат, ключ, цепочка"| runtime
    runtime --> ram
    ram --> service
    auth -->|"аутентификация"| fetch
    kv -->|"только запрошенный bootstrap-набор"| fetch
    fetch -->|"no_log facts по SSH"| facts
    facts --> setup
    facts -.-> adminfiles
```

1. **Подготовка значений.** Для нового облака значения генерируют или выпускают заранее; для существующего переносят действующие. Скалярные пароли и SSH-ключи размещаются в KV по каталогу раздела 4. В режиме `kv` туда же загружают готовые сертификаты и private keys; в режиме `pki` настраивают выпуск в отдельном PKI engine.
2. **Подготовка ссылок.** `kolla-readpwd --pull-only` заменяет значения `passwords.yml` на ссылки и проверяет только свой bootstrap-манифест. Ansible использует эти ссылки при подготовке конфигов. Для сертификатов `kv`/`pki` роли создают отдельные pointer-файлы.
3. **Получение в контейнере.** Runtime читает RoleID/SecretID из read-only mount, выполняет AppRole login, получает Vault token и читает KV или вызывает PKI issue. Приложение получает уже разрешённые значения через свой конфиг/файл. Поддержка этой обработки должна быть в поставляемых образах.
4. **Bootstrap-путь Ansible.** Выбранный узел читает только список ключей конкретной CLI-команды. Значения возвращаются в `no_log` facts текущего процесса Ansible для действий, которым пароль нужен до обычного запуска сервиса. Файлы RoleID/SecretID узла при этом не переносятся на deploy-хост.
5. **Эксплуатация.** Изменение значения в KV не меняет автоматически пароль в БД/сервисе и не доказывает reload приложения. Хостовый агент обновляет credentials доступа к Vault; применение новых прикладных значений требует согласованной процедуры обновления.

Локальные сертификаты при `kolla_secret_certificates_source=local` проходят штатный файловый workflow и не проходят через KV/PKI. CA для первого HTTPS-соединения с Vault заранее доверен узлу и образу. Итоговая проверка приложения и реального хранения в tmpfs остаётся стендовой проверкой, поскольку исходники контейнерного resolver не входят в ZIP.

### 1.2. Отдельный поток wrapped bootstrap token

**Wrapped token — одноразовый ключ к ответу Vault, внутри которого находится bootstrap SecretID.** Это не прикладной пароль и не runtime Vault token. На каждом узле хранится собственный wrapper; после успешного запуска агент заменяет его новым wrapper для следующего восстановления.

```mermaid
sequenceDiagram
    participant O as Администратор
    participant V as Vault
    participant D as Диск узла: bootstrap.wrap
    participant A as kolla-vault-agent
    participant R as RAM узла: AppRole-файлы
    O->>V: Выпустить bootstrap SecretID с response wrapping
    V-->>O: W0 — wrapping token
    O->>D: Доставить отдельный W0 на узел, root:root 0400
    A->>D: Прочитать W0 при старте
    A->>V: Lookup W0 — проверить origin и TTL
    A->>V: Unwrap W0 — одноразовое использование
    V-->>A: B0 — bootstrap SecretID в память процесса
    A->>V: Bootstrap login с RoleID и B0
    V-->>A: Tboot — bootstrap Vault token в память
    A->>V: Создать новый recovery SecretID и выполнить wrap
    V-->>A: W1 — новый recovery wrapper
    A->>D: Атомарно заменить W0 на W1
    A->>V: Создать Bnext для следующего bootstrap login
    V-->>A: Bnext — только в память процесса
    A->>V: Создать runtime SecretID
    V-->>A: R1 — runtime SecretID
    A->>R: Записать runtime RoleID и R1, tmpfs 0400
    Note over A,R: Контейнеры читают runtime-файлы и выполняют собственный login
    loop По отдельным срокам обновления
        Note over A,V: Bootstrap login, runtime SecretID и recovery wrapper обновляются независимо
        A->>V: Выполнить наступившее обновление
        V-->>A: Новый credential или wrapper
        A->>D: При обновлении wrapper заменить текущий файл
        A->>R: При обновлении runtime SecretID заменить secret_id
    end
    Note over D,A: При следующем старте расходуется последний сохранённый wrapper
```

Обозначения `W0/W1`, `B0/Bnext`, `Tboot`, `R1` используются только для объяснения последовательности; таких имён файлов и KV-путей в реализации нет.

| Этап | Каким credential выполняется | Что остаётся после этапа |
|---|---|---|
| Первоначальный выпуск wrapper | Административная identity с правом выдачи bootstrap SecretID | Wrapper отдельно для каждого узла |
| `sys/wrapping/lookup`, затем `unwrap` | Сам wrapping token | После успешного unwrap он израсходован; bootstrap SecretID доступен агенту в памяти |
| `auth/kolla-role/login` bootstrap-роли | Bootstrap RoleID + полученный SecretID | Bootstrap Vault token в памяти агента |
| Подготовить credential для следующего старта | Bootstrap token: создать **новый** bootstrap SecretID, затем `sys/wrapping/wrap` | Новый wrapper в `bootstrap.wrap`; это происходит до выдачи runtime credentials |
| Подготовить следующий bootstrap login | Bootstrap token: ещё один собственный SecretID | Отдельный `Bnext` в памяти; recovery wrapper остаётся неиспользованным |
| Подготовить runtime-доступ | Bootstrap token: SecretID runtime-роли | Runtime RoleID/SecretID в `/run/kolla-vault/approle`, доступные контейнерам через read-only mount |
| Обновление и повторный старт | Текущий token/следующий bootstrap SecretID либо последний wrapper | Раздельное обновление credentials; wrapper нужен для восстановления процесса |

Три разных срока: TTL wrapping token, TTL вложенного bootstrap SecretID и TTL Vault token. У runtime SecretID есть свой TTL. Для автоматического расписания агент использует примерно 2/3 соответствующего эффективного TTL; для recovery — минимум TTL wrapper и вложенного SecretID. Обновление recovery создаёт новый SecretID и новый wrapper; `sys/wrapping/rewrap` в этом алгоритме не используется.

Между unwrap и сохранением нового wrapper есть обозначенное в коде окно аварии. Если после такой аварии или длительного простоя при следующем старте wrapper уже использован, просрочен либо истёк вложенный SecretID, для восстановления нужен новый wrapper от администратора. При обычном цикле контейнеры не читают `bootstrap.wrap` и не получают bootstrap token.

Основание для обоих потоков: `ansible/roles/vault-agent/templates/kolla-vault-agent.py.j2` (методы `generate_wrapped_secret_id`, `run`), `ansible/vault-bootstrap-fetch.yml`, `kolla_ansible/cmd/readpwd.py`, `kolla_ansible/secret_backends.py`, `ansible/post-deploy.yml`.

### 1.3. Порядок настройки

1. Проверить пакет Kolla, образы, inventory и доверие к HTTPS Vault.
2. Создать или проверить KV v2 и AppRole auth mount.
3. Загрузить прикладные секреты по схеме этого форка.
4. Создать runtime-политику, bootstrap-политику и две AppRole.
5. Записать настройки и RoleID в `globals.yml`.
6. Выпустить **отдельный wrapped bootstrap SecretID для каждого узла** и доставить его на узел.
7. Выполнить `approle init`, затем `approle status`.
8. Подготовить `passwords.yml` со ссылками через `kolla-readpwd --pull-only`.
9. Выполнить `prechecks`; после проверки результата — штатное развёртывание.

## 2. Компоненты интеграции

| Компонент | Что получает и делает |
|---|---|
| Администратор Vault | Настраивает engine/auth/policies, заполняет KV, выдаёт первоначальные wrappers |
| Bootstrap AppRole | Создаёт SecretID runtime-роли и собственной bootstrap-роли; выполняет `sys/wrapping/wrap` |
| Runtime AppRole | Читает нужные KV-объекты; в PKI-режиме получает право выпуска через конкретные PKI-роли |
| `kolla-vault-agent` | Хранит bootstrap token и bootstrap SecretID в памяти процесса; обновляет runtime SecretID и recovery wrapper |
| Контейнеры | Получают только runtime RoleID/SecretID; преобразуют ссылки в реальные конфигурации с помощью доработанного Kolla runtime |
| Ansible controller | Получает ограниченный набор прикладных паролей через делегированный модуль; обычные CLI-команды не копируют к нему AppRole-файлы узла |
| `kolla-readpwd` | Самостоятельная CLI-утилита: напрямую обращается к Vault со своими credentials, проверяет bootstrap-секреты и переписывает локальный YAML в ссылки |

Термин **bootstrap** используется в двух разных смыслах: bootstrap **AppRole** запускает хостовый агент; bootstrap **пароли** нужны Ansible для подготовки сервисов. Эти пароли читает runtime AppRole, а не bootstrap AppRole.

Основание: `ansible/roles/vault-agent/tasks/init.yml`, `ansible/roles/vault-agent/templates/kolla-vault-agent.py.j2`, `ansible/vault-bootstrap-fetch.yml`, `kolla_ansible/cmd/readpwd.py`.

## 3. Предварительные условия

### 3.1. Пакет и контейнеры

Использовать CLI и playbooks **этого форка**. Наличие стандартного upstream Kolla-Ansible не доказывает поддержку команды `approle` и ссылок на секреты.

Проверить в окружении оператора Kolla:

```bash
kolla-ansible approle --help
kolla-readpwd --help
ansible --version
ansible-galaxy collection list
```

| Требование из архива | Значение |
|---|---|
| Python, метаданные пакета | `>=3.10`; для проверок этой инструкции использован Python 3.11 |
| `ansible-core` | `>=2.17,<2.19` |
| `openstack.kolla` | Git-зависимость `stable/2025.1` в `requirements.yml` |
| Остальные коллекции | `ansible.netcommon <8`, `ansible.posix <2`, `ansible.utils <6`, `community.crypto <3`, `community.general <11`, `community.docker <5`, `containers.podman <2` |
| Python Vault-зависимость | `hvac>=0.10.1`; новый pull-only reader и хостовый агент также содержат собственные HTTP-клиенты |
| Engine контейнеров по умолчанию | `podman` |
| Registry/namespace/tag по умолчанию | `sberlinux.sbertech.ru / pvs / latest` |
| Закрепление образов | `kolla_image_lock_required: "no"`, пустой `kolla_image_lock` |

Исходники `kolla_set_configs` из соответствующего проекта сборки образов в ZIP не входят. Архив задаёт ссылки, `config.json`, mounts и параметры tmpfs, но **не подтверждает**, что фактически скачанный образ умеет их обрабатывать. Перед deploy нужны согласованные образы с поддержкой `vault://`, а для PKI — `secret://pki`, безопасной материализации и повторного чтения credentials. При наличии манифеста поставки следует закрепить его digest через предусмотренный image lock.

Точная версия сервера Vault не закреплена. Нужны API KV v2, AppRole и response wrapping; для `pki` также PKI issue API. Версии и совместимость runtime следует подтвердить на целевой поставке.

Основание: `requirements.txt`, `requirements.yml`, `requirements-core.yml`, `setup.cfg`, `ansible/group_vars/all.yml`, `kolla_ansible/secret_backends.py`.

### 3.2. Узлы и сеть

- На управляемых Linux-узлах нужны `/usr/bin/python3`, systemd, `systemd-tmpfiles`, `findmnt`; `/run` должен находиться на `tmpfs`.
- Ansible должен иметь SSH-доступ и `become` для установки root-сервиса и чтения закрытых файлов.
- HTTPS Vault должен быть доступен с каждого узла и из контейнеров. Отдельная проверка `kolla-readpwd` требует доступ с машины, где она запускается.
- Сертификат HTTPS Vault должен соответствовать имени в `vault_addr`. Его CA заранее доступен хостовому агенту и контейнерному runtime.
- Установленный и unsealed Vault должен быть доступен до первого `approle init` и до запуска контейнеров, которым нужны секреты.

**CA для HTTPS Vault нельзя впервые получать через тот же Vault:** для чтения секретов уже нужно проверить его TLS. Практичный вариант — заранее включить CA в системное доверие всех согласованных образов и установить CA-файл на узлы. `vault_cacert` задаёт хостовый путь; `vault_container_cacert` — путь внутри контейнера. Пустой контейнерный путь означает использование системного доверия, а не отключение проверки. Роль `vault-agent` сама CA не распространяет.

## 4. Схема KV v2

Параметры примера:

| Параметр | Значение |
|---|---|
| KV mount | `kv` |
| Deployment | `prod-cloud` |
| Region | `RegionOne` |
| Логический префикс `P` | `kolla/prod-cloud/RegionOne` |
| AppRole mount | `kolla-role` |
| Runtime AppRole | `kolla-prod-cloud-RegionOne` |
| Bootstrap AppRole | `kolla-agent-bootstrap-prod-cloud-RegionOne` |

### 4.1. Пароли и SSH-ключи

Каждый ключ верхнего уровня `passwords.yml` — **отдельный KV-документ**:

```text
kv/                                       # mount KV v2
└── kolla/prod-cloud/RegionOne/
    ├── passwords/
    │   ├── shared/
    │   │   ├── database_password          # {"password": "..."}
    │   │   ├── keystone_admin_password    # {"password": "..."}
    │   │   └── nova_ssh_key               # {"private_key": "...", "public_key": "..."}
    │   └── hosts/
    │       └── compute01/
    │           └── <имя_секрета>          # только явно выбранные host-scoped secrets
    └── certificates/                     # используется в режиме kv
        ├── hosts/<inventory_hostname>/...
        ├── shared/...
        └── trust/...
```

Не размещать весь YAML внутри одного `passwords_yml` и не создавать единый документ `passwords/shared` со всеми паролями: этот форк читает другие пути.

Для `database_password`:

| Контекст | Путь |
|---|---|
| Vault CLI | `vault kv get -mount=kv kolla/prod-cloud/RegionOne/passwords/shared/database_password` |
| HTTP API | `/v1/kv/data/kolla/prod-cloud/RegionOne/passwords/shared/database_password` |
| ACL policy | `kv/data/kolla/prod-cloud/RegionOne/passwords/shared/database_password` |
| Значение в `passwords.yml` | `$(vault://kv/data/kolla/prod-cloud/RegionOne/passwords/shared/database_password#password)` |

`/data/` присутствует в API, ACL и ссылке; при `vault kv ... -mount=kv` его вручную не добавляют. Это соответствует [схеме KV v2 HashiCorp](https://developer.hashicorp.com/vault/docs/secrets/kv).

Скаляр хранить как строковое поле `password`. Словари SSH-ключей сохранять с полями `private_key` и `public_key`. Типы и ограничения конкретных значений сохраняются: например, `rbd_secret_uuid` и `cinder_rbd_secret_uuid` должны оставаться UUID, а bcrypt salts — корректными salts. Полный перечень входных ключей находится в `etc/kolla/passwords.yml`; это перечень возможностей поставки, а не доказательство необходимости всех сервисов в конкретном inventory.

### 4.2. Host-scoped secrets

По умолчанию `vault_host_scoped_passwords: []`, все пароли общие для deployment/region. Если ключ добавлен в этот список, путь становится:

```text
P/passwords/hosts/<inventory_hostname>/<имя_секрета>
```

Используется **имя из inventory**, не обязательно DNS-имя или IP. Автоматического fallback из `hosts` в `shared` нет. Bootstrap-пароли нельзя переводить в host-scoped: CLI `kolla-readpwd` и prechecks это ограничивают.

Разные пути по узлам сами по себе не дают изоляцию доступа: с одной общей runtime AppRole и политикой `hosts/*` узлы получают доступ ко всему разрешённому набору. Если требуется изоляция каждого узла, нужны согласованные индивидуальные роли, ACL и host vars; это отдельный вариант от показанного здесь общего профиля.

### 4.3. Полный контракт данных и граница каталога

Ниже перечислены **все 128 ключей** из `etc/kolla/passwords.yml` этого ZIP: **121 скалярный объект и 7 объектов SSH-ключей, всего 135 полей**. Включены не только пароли, но также UUID, salts, shared secrets и идентификаторы, которые этот форк преобразует в Vault references тем же способом.

Каталог построен по шаблону, а форматы генерации — по `kolla_ansible/cmd/genpwd.py`. Это полный перечень штатной структуры `passwords.yml`, не утверждение, что каждый ключ читается в любой конфигурации. Runtime-only ключи требуются при использовании соответствующего сервиса; bootstrap-требования определяются конкретной командой и разделом 9. Пользовательские дополнительные ключи/словарные поля reader также может преобразовать, но их невозможно перечислить без пользовательской конфигурации.

Для таблиц:

- `P = kolla/prod-cloud/RegionOne` — логический префикс примера, без mount и без `/data/`.
- Все перечисленные пути расположены **внутри mount `kv`**, который должен быть KV v2.
- Для любой строки `P/passwords/shared/K` полный API-путь равен `/v1/kv/data/kolla/prod-cloud/RegionOne/passwords/shared/K`.
- Поле `password` сохраняется даже для UUID, Fernet key, salt или идентификатора. Имя KV-документа — имя ключа `K`, имя поля не повторяет `K`.
- Все строки имеют scope `shared` по умолчанию. Правило замены на `hosts/<inventory_hostname>` приведено после каталога.
- Заголовки групп ниже служат для чтения и **не создают дополнительных каталогов в KV**.

#### Форматы значений

| Профиль в каталоге | Поля KV-документа и формат | Основание |
|---|---|---|
| `G40` | `password`: строка; default генератор использует 40 символов `[A-Za-z0-9]` | Обычная ветка `generate_password(length=40)` |
| `UUID` | `password`: строка UUID; не число | Список `uuid_keys` в `genpwd.py` |
| `HMAC32` | `password`: 32-символьная hex-строка результата HMAC-MD5 в генераторе архива | `hmac_md5_keys`; это описание именно этого генератора |
| `FERNET` | `password`: строка ключа формата Fernet | `fernet.Fernet.generate_key()` |
| `SALT22` | `password`: 22-символьная строка bcrypt salt; не готовый bcrypt password hash | `random_salt(22)` |
| `SSH` | `private_key`: PEM PKCS#8 private key без шифрования; `public_key`: OpenSSH public key; по умолчанию RSA 4096 | `generate_RSA()` |
| `EXTERNAL` | `password`: действующий пароль внешнего registry | `docker_registry_password` входит в `blank_keys`, генератор оставляет `null` незаполненным |

`G40` показывает поведение генератора нового YAML. Он не требует заменять уже действующие внешние credentials случайной строкой. Ограничения конкретного потребителя сохраняются. Не загружать `null`, шаблонную заглушку или `$(vault://...)` вместо реального значения; необязательный неиспользуемый объект можно не создавать.

#### Обозначения bootstrap

| Метка | Значение |
|---|---|
| `C + R` | Ключ разрешён CLI-fetch, присутствует в reader-манифесте и обязателен для стандартного `kolla-readpwd` |
| `C + M` | Ключ разрешён CLI-fetch и проверяется reader; reader только предупреждает при отсутствии, но нуждающаяся CLI-команда требует значение |
| `M` | Ключ есть только в reader-манифесте из этих двух механизмов, но отсутствует в allow-list CLI-fetch |
| `—` | Не входит ни в reader-манифест, ни в allow-list CLI-fetch; может требоваться своему runtime-потребителю |

`C` не означает, что все команды читают ключ: точный набор задаёт CLI. `R` не отменяет остальных требований deploy. Проверка множеств по архиву: 7 строк `C + R`, 13 строк `C + M`, 2 строки `M`, 106 строк `—`.

### 4.4. Каталог всех password/SSH KV-объектов

#### Ceph, MariaDB, registry и внешние интеграции

| № | Логический путь в mount `kv` | Поля документа | Профиль | Bootstrap |
|---|---|---|---|---|
| 001 | `P/passwords/shared/rbd_secret_uuid` | `password` | `UUID` | C + M |
| 002 | `P/passwords/shared/cinder_rbd_secret_uuid` | `password` | `UUID` | C + M |
| 003 | `P/passwords/shared/database_password` | `password` | `G40` | C + R |
| 004 | `P/passwords/shared/mariadb_backup_database_password` | `password` | `G40` | — |
| 005 | `P/passwords/shared/mariadb_monitor_password` | `password` | `G40` | C + R |
| 006 | `P/passwords/shared/docker_registry_password` | `password` | `EXTERNAL` | C + M |
| 007 | `P/passwords/shared/vmware_dvs_host_password` | `password` | `G40` | — |
| 008 | `P/passwords/shared/vmware_nsxv_password` | `password` | `G40` | — |
| 009 | `P/passwords/shared/vmware_vcenter_host_password` | `password` | `G40` | — |
| 010 | `P/passwords/shared/nsxv3_api_password` | `password` | `G40` | — |
| 011 | `P/passwords/shared/vmware_nsxp_api_password` | `password` | `G40` | — |
| 012 | `P/passwords/shared/vmware_nsxp_metadata_proxy_shared_secret` | `password` | `G40` | — |
| 013 | `P/passwords/shared/hnas_nfs_password` | `password` | `G40` | — |
| 014 | `P/passwords/shared/infoblox_admin_password` | `password` | `G40` | — |

#### OpenStack: сервисные пароли, ключи и идентификаторы

| № | Логический путь в mount `kv` | Поля документа | Профиль | Bootstrap |
|---|---|---|---|---|
| 015 | `P/passwords/shared/aodh_database_password` | `password` | `G40` | — |
| 016 | `P/passwords/shared/aodh_keystone_password` | `password` | `G40` | — |
| 017 | `P/passwords/shared/barbican_database_password` | `password` | `G40` | — |
| 018 | `P/passwords/shared/barbican_keystone_password` | `password` | `G40` | — |
| 019 | `P/passwords/shared/barbican_p11_password` | `password` | `G40` | — |
| 020 | `P/passwords/shared/barbican_crypto_key` | `password` | `FERNET` | — |
| 021 | `P/passwords/shared/blazar_database_password` | `password` | `G40` | — |
| 022 | `P/passwords/shared/blazar_keystone_password` | `password` | `G40` | — |
| 023 | `P/passwords/shared/keystone_admin_password` | `password` | `G40` | C + R |
| 024 | `P/passwords/shared/keystone_database_password` | `password` | `G40` | — |
| 025 | `P/passwords/shared/grafana_database_password` | `password` | `G40` | — |
| 026 | `P/passwords/shared/grafana_admin_password` | `password` | `G40` | — |
| 027 | `P/passwords/shared/glance_database_password` | `password` | `G40` | — |
| 028 | `P/passwords/shared/glance_keystone_password` | `password` | `G40` | — |
| 029 | `P/passwords/shared/gnocchi_database_password` | `password` | `G40` | — |
| 030 | `P/passwords/shared/gnocchi_keystone_password` | `password` | `G40` | — |
| 031 | `P/passwords/shared/kuryr_keystone_password` | `password` | `G40` | — |
| 032 | `P/passwords/shared/nova_database_password` | `password` | `G40` | C + R |
| 033 | `P/passwords/shared/nova_api_database_password` | `password` | `G40` | — |
| 034 | `P/passwords/shared/nova_keystone_password` | `password` | `G40` | — |
| 035 | `P/passwords/shared/placement_keystone_password` | `password` | `G40` | — |
| 036 | `P/passwords/shared/placement_database_password` | `password` | `G40` | — |
| 037 | `P/passwords/shared/neutron_database_password` | `password` | `G40` | — |
| 038 | `P/passwords/shared/neutron_keystone_password` | `password` | `G40` | — |
| 039 | `P/passwords/shared/metadata_secret` | `password` | `G40` | — |
| 040 | `P/passwords/shared/cinder_database_password` | `password` | `G40` | — |
| 041 | `P/passwords/shared/cinder_keystone_password` | `password` | `G40` | — |
| 042 | `P/passwords/shared/cloudkitty_database_password` | `password` | `G40` | — |
| 043 | `P/passwords/shared/cloudkitty_keystone_password` | `password` | `G40` | — |
| 044 | `P/passwords/shared/cyborg_database_password` | `password` | `G40` | — |
| 045 | `P/passwords/shared/cyborg_keystone_password` | `password` | `G40` | — |
| 046 | `P/passwords/shared/designate_database_password` | `password` | `G40` | — |
| 047 | `P/passwords/shared/designate_keystone_password` | `password` | `G40` | — |
| 048 | `P/passwords/shared/designate_pool_id` | `password` | `UUID` | — |
| 049 | `P/passwords/shared/designate_rndc_key` | `password` | `HMAC32` | — |
| 050 | `P/passwords/shared/heat_database_password` | `password` | `G40` | — |
| 051 | `P/passwords/shared/heat_keystone_password` | `password` | `G40` | — |
| 052 | `P/passwords/shared/heat_domain_admin_password` | `password` | `G40` | C + R |
| 053 | `P/passwords/shared/ironic_database_password` | `password` | `G40` | — |
| 054 | `P/passwords/shared/ironic_keystone_password` | `password` | `G40` | — |
| 055 | `P/passwords/shared/ironic_inspector_database_password` | `password` | `G40` | — |
| 056 | `P/passwords/shared/ironic_inspector_keystone_password` | `password` | `G40` | — |
| 057 | `P/passwords/shared/magnum_database_password` | `password` | `G40` | — |
| 058 | `P/passwords/shared/magnum_keystone_password` | `password` | `G40` | — |
| 059 | `P/passwords/shared/mistral_database_password` | `password` | `G40` | — |
| 060 | `P/passwords/shared/mistral_keystone_password` | `password` | `G40` | — |
| 061 | `P/passwords/shared/trove_database_password` | `password` | `G40` | — |
| 062 | `P/passwords/shared/trove_keystone_password` | `password` | `G40` | — |
| 063 | `P/passwords/shared/ceilometer_database_password` | `password` | `G40` | — |
| 064 | `P/passwords/shared/ceilometer_keystone_password` | `password` | `G40` | — |
| 065 | `P/passwords/shared/watcher_database_password` | `password` | `G40` | — |
| 066 | `P/passwords/shared/watcher_keystone_password` | `password` | `G40` | — |
| 067 | `P/passwords/shared/horizon_secret_key` | `password` | `G40` | — |
| 068 | `P/passwords/shared/horizon_database_password` | `password` | `G40` | — |
| 069 | `P/passwords/shared/telemetry_secret_key` | `password` | `G40` | — |
| 070 | `P/passwords/shared/manila_database_password` | `password` | `G40` | — |
| 071 | `P/passwords/shared/manila_keystone_password` | `password` | `G40` | — |
| 072 | `P/passwords/shared/octavia_database_password` | `password` | `G40` | — |
| 073 | `P/passwords/shared/octavia_persistence_database_password` | `password` | `G40` | — |
| 074 | `P/passwords/shared/octavia_keystone_password` | `password` | `G40` | C + M |
| 075 | `P/passwords/shared/octavia_ca_password` | `password` | `G40` | C + M |
| 076 | `P/passwords/shared/octavia_client_ca_password` | `password` | `G40` | C + M |
| 077 | `P/passwords/shared/tacker_database_password` | `password` | `G40` | — |
| 078 | `P/passwords/shared/tacker_keystone_password` | `password` | `G40` | — |
| 079 | `P/passwords/shared/zun_database_password` | `password` | `G40` | — |
| 080 | `P/passwords/shared/zun_keystone_password` | `password` | `G40` | — |
| 081 | `P/passwords/shared/venus_database_password` | `password` | `G40` | — |
| 082 | `P/passwords/shared/venus_keystone_password` | `password` | `G40` | — |
| 083 | `P/passwords/shared/masakari_database_password` | `password` | `G40` | — |
| 084 | `P/passwords/shared/masakari_keystone_password` | `password` | `G40` | — |
| 085 | `P/passwords/shared/memcache_secret_key` | `password` | `G40` | — |
| 086 | `P/passwords/shared/skyline_secret_key` | `password` | `G40` | — |
| 087 | `P/passwords/shared/skyline_database_password` | `password` | `G40` | — |
| 088 | `P/passwords/shared/skyline_keystone_password` | `password` | `G40` | — |
| 089 | `P/passwords/shared/osprofiler_secret` | `password` | `HMAC32` | — |

#### SSH-ключи: семь документов по два поля

| № | Логический путь в mount `kv` | Поля документа | Профиль | Bootstrap |
|---|---|---|---|---|
| 090 | `P/passwords/shared/nova_ssh_key` | `private_key`, `public_key` | `SSH` | — |
| 091 | `P/passwords/shared/kolla_ssh_key` | `private_key`, `public_key` | `SSH` | — |
| 092 | `P/passwords/shared/keystone_ssh_key` | `private_key`, `public_key` | `SSH` | — |
| 093 | `P/passwords/shared/bifrost_ssh_key` | `private_key`, `public_key` | `SSH` | — |
| 094 | `P/passwords/shared/octavia_amp_ssh_key` | `private_key`, `public_key` | `SSH` | — |
| 095 | `P/passwords/shared/neutron_ssh_key` | `private_key`, `public_key` | `SSH` | — |
| 096 | `P/passwords/shared/haproxy_ssh_key` | `private_key`, `public_key` | `SSH` | — |

#### Gnocchi: идентификаторы

| № | Логический путь в mount `kv` | Поля документа | Профиль | Bootstrap |
|---|---|---|---|---|
| 097 | `P/passwords/shared/gnocchi_project_id` | `password` | `UUID` | — |
| 098 | `P/passwords/shared/gnocchi_resource_id` | `password` | `UUID` | — |
| 099 | `P/passwords/shared/gnocchi_user_id` | `password` | `UUID` | — |

#### RabbitMQ, HAProxy, Keepalived и FRR

| № | Логический путь в mount `kv` | Поля документа | Профиль | Bootstrap |
|---|---|---|---|---|
| 100 | `P/passwords/shared/rabbitmq_password` | `password` | `G40` | — |
| 101 | `P/passwords/shared/rabbitmq_monitoring_password` | `password` | `G40` | — |
| 102 | `P/passwords/shared/rabbitmq_cluster_cookie` | `password` | `G40` | C + R |
| 103 | `P/passwords/shared/haproxy_password` | `password` | `G40` | C + M |
| 104 | `P/passwords/shared/keepalived_password` | `password` | `G40` | — |
| 105 | `P/passwords/shared/frr_bgp_md5_mesh_password` | `password` | `G40` | — |
| 106 | `P/passwords/shared/frr_bgp_md5_uplink_password` | `password` | `G40` | — |

#### etcd и Redis

| № | Логический путь в mount `kv` | Поля документа | Профиль | Bootstrap |
|---|---|---|---|---|
| 107 | `P/passwords/shared/etcd_cluster_token` | `password` | `G40` | M |
| 108 | `P/passwords/shared/redis_master_password` | `password` | `G40` | C + M |

#### Prometheus

| № | Логический путь в mount `kv` | Поля документа | Профиль | Bootstrap |
|---|---|---|---|---|
| 109 | `P/passwords/shared/prometheus_mysql_exporter_database_password` | `password` | `G40` | — |
| 110 | `P/passwords/shared/prometheus_alertmanager_password` | `password` | `G40` | — |
| 111 | `P/passwords/shared/prometheus_password` | `password` | `G40` | C + M |
| 112 | `P/passwords/shared/prometheus_grafana_password` | `password` | `G40` | C + M |
| 113 | `P/passwords/shared/prometheus_haproxy_password` | `password` | `G40` | C + M |
| 114 | `P/passwords/shared/prometheus_skyline_password` | `password` | `G40` | C + M |
| 115 | `P/passwords/shared/prometheus_bcrypt_salt` | `password` | `SALT22` | C + M |

#### Федерация Keystone, RadosGW, libvirt и ProxySQL

| № | Логический путь в mount `kv` | Поля документа | Профиль | Bootstrap |
|---|---|---|---|---|
| 116 | `P/passwords/shared/keystone_federation_openid_crypto_password` | `password` | `G40` | — |
| 117 | `P/passwords/shared/ceph_rgw_keystone_password` | `password` | `G40` | — |
| 118 | `P/passwords/shared/libvirt_sasl_password` | `password` | `G40` | C + R |
| 119 | `P/passwords/shared/proxysql_admin_password` | `password` | `G40` | — |
| 120 | `P/passwords/shared/proxysql_stats_password` | `password` | `G40` | — |

#### OpenSearch и аудит безопасности

| № | Логический путь в mount `kv` | Поля документа | Профиль | Bootstrap |
|---|---|---|---|---|
| 121 | `P/passwords/shared/opensearch_dashboards_password` | `password` | `G40` | M |
| 122 | `P/passwords/shared/opensearch_dashboards_backend_password` | `password` | `G40` | — |
| 123 | `P/passwords/shared/prometheus_elasticsearch_exporter_password` | `password` | `G40` | — |
| 124 | `P/passwords/shared/security_audit_ingest_password` | `password` | `G40` | — |
| 125 | `P/passwords/shared/security_audit_readonly_password` | `password` | `G40` | — |
| 126 | `P/passwords/shared/security_audit_flog_ingest_password` | `password` | `G40` | — |
| 127 | `P/passwords/shared/security_audit_admin_password` | `password` | `G40` | — |
| 128 | `P/passwords/shared/security_audit_bcrypt_salt` | `password` | `SALT22` | — |

Контроль полноты: 128 строк соответствуют 128 уникальным ключам исходного YAML; семь SSH-документов содержат по два поля, остальные — по одному. Поля каждого документа проверены через функцию `_runtime_placeholder` reader. Источники: `etc/kolla/passwords.yml`, `kolla_ansible/cmd/readpwd.py`, `kolla_ansible/cmd/genpwd.py`, `etc/kolla/vault-bootstrap-secrets.yml`, `ansible/group_vars/all.yml`.

### 4.5. Как выглядит содержимое KV-документа

**Скаляр** — например, `P/passwords/shared/database_password`. Для `vault kv put ... @payload.json` JSON содержит только пользовательские поля:

```json
{
  "password": "REPLACE_WITH_ACTUAL_VALUE"
}
```

Точно такое же имя поля `password` используется для `rbd_secret_uuid`, `prometheus_bcrypt_salt`, `barbican_crypto_key` и других скалярных строк каталога; меняется формат значения и имя документа.

**SSH-пара** — например, `P/passwords/shared/nova_ssh_key`:

```json
{
  "private_key": "REPLACE_WITH_PEM_PRIVATE_KEY",
  "public_key": "REPLACE_WITH_OPENSSH_PUBLIC_KEY"
}
```

Это один документ с двумя полями. Не создавать два объекта `.../nova_ssh_key/private_key` и `.../nova_ssh_key/public_key`. Reader формирует две ссылки к одному документу с разными фрагментами `#private_key` и `#public_key`.

**Различие CLI и HTTP API:** при прямой записи KV v2 через `POST /v1/kv/data/<logical-path>` пользовательские поля помещаются внутрь `data`. Пример тела первого создания:

```json
{
  "options": {"cas": 0},
  "data": {
    "password": "REPLACE_WITH_ACTUAL_VALUE"
  }
}
```

При чтении KV v2 пользовательские поля находятся в `response.data.data`. В файл для `vault kv put` внешние поля `data/options` из HTTP-примера переносить не нужно: это разные уровни API. `version`, `created_time`, `deletion_time` — служебные метаданные KV v2, не поля пароля.

### 4.6. Развёртывание каталога по узлам

Если выбранный ключ `K` включён в `vault_host_scoped_passwords`, его строка каталога заменяется для **каждого нужного узла**:

```text
По умолчанию: P/passwords/shared/K
Host-scoped:  P/passwords/hosts/<inventory_hostname>/K
```

Поля и формат документа остаются прежними. Для SSH-пары в каждом таком документе по-прежнему два поля. При переименовании `inventory_hostname` меняется ожидаемый Vault-путь; значения сами не перемещаются. Для ключей с метками `C + R`, `C + M` и `M` host-scoped режим стандартный reader запрещает: все 22 имени входят в его bootstrap-манифест. Для остальных ключей допустимость отдельного значения на каждом узле определяется устройством сервиса — общий пароль к общей БД нельзя произвольно разнести по узлам.

Пример структуры для выбранного runtime-ключа `K` на двух узлах:

```text
P/passwords/hosts/controller01/K   -> те же поля, значение для controller01
P/passwords/hosts/controller02/K   -> те же поля, значение для controller02
```

В режиме host-scoped reader создаёт путь с `{{ inventory_hostname }}`. Он не проверяет наличие всех этих документов; полноту по inventory требуется проверять отдельно. Приведённая в разделе 5 общая региональная ACL не изолирует один узел от другого.

### 4.7. Полная схема сертификатов и CA в режиме kv

Эти документы существуют **дополнительно** к 128 password/SSH-объектам. Число фактических документов зависит от inventory и включённых TLS-сервисов. В архиве определены семь стандартных шаблонов путей и расширяемая карта дополнительных CA:

```text
kv                                      # engine KV v2
└── kolla/prod-cloud/RegionOne
    └── certificates
        ├── hosts
        │   └── <inventory_hostname>
        │       ├── backend             -> cert, key, pem
        │       ├── libvirt-client      -> cert, key
        │       └── libvirt-server      -> cert, key
        ├── shared
        │   ├── haproxy-external        -> pem
        │   ├── haproxy-internal        -> pem
        │   └── database                -> cert, key
        └── trust
            ├── internal-ca             -> ca
            └── <additional-ca-name>    -> ca или поле из vault_extra_ca_files
```

Последняя строка — соглашение для дополнительных CA, не жёстко заданный путь: `vault_extra_ca_files[*].path` может указывать на другой KV-путь. Нельзя добавить поле/путь в эту карту и считать, что оно уже создано в Vault.

| Шаблон логического пути | Поля и значения | Когда/как читается |
|---|---|---|
| `P/certificates/hosts/<inventory_hostname>/backend` | `cert`: PEM сертификат и нужная цепочка; `key`: соответствующий PEM private key; `pem`: объединённый комплект для HAProxy | Backend TLS/mTLS; `pem` нужен узлам, где используется HAProxy backend client identity |
| `P/certificates/hosts/<inventory_hostname>/libvirt-client` | `cert`, `key`: клиентский TLS-комплект в PEM | libvirt TLS client на соответствующем узле |
| `P/certificates/hosts/<inventory_hostname>/libvirt-server` | `cert`, `key`: серверный TLS-комплект в PEM | libvirt TLS server на соответствующем узле |
| `P/certificates/shared/haproxy-external` | `pem`: private key + сертификат/цепочка, пригодные для HAProxy | Включён внешний TLS frontend |
| `P/certificates/shared/haproxy-internal` | `pem`: private key + сертификат/цепочка, пригодные для HAProxy | Включён внутренний TLS frontend |
| `P/certificates/shared/database` | `cert`, `key`: общий PEM TLS-комплект БД | ProxySQL; MariaDB без ProxySQL использует этот путь, с ProxySQL — host `backend` |
| `P/certificates/trust/internal-ca` | `ca`: PEM доверенного CA/bundle | Внутреннее доверие и libvirt CA; разные целевые файлы могут ссылаться на один объект |
| Путь из `vault_extra_ca_files[<filename>].path` | Поле из `.field`, default `ca`: дополнительный PEM CA/bundle | Дополнительные trust anchors при включённом копировании CA; карта пуста по умолчанию |

В default-схеме нет отдельного KV-документа `proxysql` и нет отдельного CA-документа на каждый сервис: `vault_proxysql_tls_path` ссылается на общий `database`, `vault_libvirt_ca_path` — на `trust/internal-ca`. `ca-certificates/internal-ca.crt` и `ca-certificates/root.crt` могут быть двумя pointer-файлами к одному `internal-ca#ca`.

Пример payload для host `backend`:

```json
{
  "cert": "REPLACE_WITH_PEM_CERTIFICATE_CHAIN",
  "key": "REPLACE_WITH_MATCHING_PEM_PRIVATE_KEY",
  "pem": "REPLACE_WITH_HAPROXY_PEM_BUNDLE"
}
```

Reader `kolla-readpwd` не формирует эти объекты и не переносит их из `passwords.yml`. Certificate pointers создают соответствующие Ansible-роли. В режиме `pki` стандартные leaf certificates и внутренний trust chain приходят из PKI issue response вместо перечисленных KV-документов; произвольные дополнительные CA из `vault_extra_ca_files` остаются KV-backed. В `local` стандартные сертификаты остаются в файловом workflow.

Все 12 полей семи стандартных шаблонов выше — имена полей, которые используются ролями; не каждый узел читает все 12. При замене путей через `vault_*_tls_path`/`vault_libvirt_ca_path` учесть соответствующие ссылки и ACL. Подробности выбора сертификатов и PKI-role приведены в разделе 10.

Источники: `ansible/group_vars/all.yml:1754`, `ansible/roles/service-cert-copy/tasks/main.yml`, `ansible/roles/loadbalancer/tasks/copy-certs.yml`, `ansible/roles/nova-cell/tasks/config-libvirt-tls.yml`.

### 4.8. Что не является объектом этого KV-каталога

| Материал | Где он находится/какой механизм используется | Причина отдельного описания |
|---|---|---|
| Wrapping token | `bootstrap.wrap` на диске узла; `sys/wrapping/*` в Vault | Одноразовый доступ к обёрнутому ответу, не `kv/data/...` |
| Bootstrap SecretID и Vault token | AppRole auth API и память `kolla-vault-agent` | Выдают credentials и обновляют recovery; не загружаются как password KV-объекты |
| Runtime RoleID/SecretID | AppRole auth API; файлы в `/run/kolla-vault/approle` | Используются для login; runtime token клиент получает отдельно |
| Временный token для `kolla-readpwd` | Token auth API; защищённый файл оператора | Отдельный доступ reader, описанный в разделе 5.6 |
| Выпущенные PKI private keys и сертификаты | PKI issue response → runtime материализация | Не становятся автоматически документами `certificates/...` в KV |
| Внутренний CA/private key issuer | Настроенный Vault PKI engine/регламент PKI | CA private key не должен подменяться полем `trust/internal-ca#ca`, где ожидается публичный trust bundle |
| CA для HTTPS самого Vault | Предварительно установленное доверие хоста и образов | Нужен до первого чтения KV/PKI |
| Keystone Fernet keys | Штатный `keystone_fernet` bootstrap/volume/rotation workflow | В каталоге нет автоматического KV-мэппинга этих ключей; `keystone_ssh_key` — другой объект |
| Материалы Octavia Amphora CA | Локальные задачи `octavia-certificates` и копирование файлов | `vault_octavia_kv_path` объявлен, но потребитель этого KV-пути не найден; имена его предполагаемых KV-полей не определены |
| Произвольные BMC/SSH credentials inventory и внешних плагинов | Определяется конкретной конфигурацией/плагином | Этот шаблон и reader не задают для них полный автоматический Vault-каталог |

Источники для границ: `ansible/roles/keystone/tasks/bootstrap_service.yml`, `ansible/roles/keystone/tasks/distribute_fernet.yml`, `ansible/roles/octavia/tasks/config.yml`, `ansible/roles/octavia-certificates/tasks/main.yml`, `ansible/roles/vault-agent/templates/kolla-vault-agent.py.j2`.

## 5. Настроить Vault: действия администратора

### 5.1. Проверить endpoint и mounts

Команды выполнять на административной машине с Vault CLI и уже настроенной административной аутентификацией. Не переносить административный token в `globals.yml`, AppRole-файлы или контейнеры.

```bash
export VAULT_ADDR='https://vault.example:8200'
export VAULT_CACERT='/etc/pki/ca-trust/source/anchors/vault-ca.crt'
# Для Enterprise namespace дополнительно задайте VAULT_NAMESPACE.

vault status
vault secrets list -detailed
vault auth list -detailed
```

Для новой конфигурации, **если соответствующие mounts отсутствуют**:

```bash
vault secrets enable -path=kv kv-v2
vault auth enable -path=kolla-role approle
```

Если mount уже существует, проверить его тип и версию. Команды выше не являются процедурой миграции существующего KV v1. Синтаксис создания подтверждён [документацией KV v2](https://docs.hashicorp.com/vault/docs/secrets/kv/kv-v2/setup) и [AppRole](https://docs.hashicorp.com/vault/docs/auth/approle).

### 5.2. Заполнить секреты

Для действующего облака перенести текущие согласованные значения; смена пароля только в Vault не обновляет автоматически пароль в MariaDB, RabbitMQ или Keystone. Для нового облака подготовить значения через штатный процесс генерации Kolla на административной машине. `kolla-genpwd` заполняет YAML, но не создаёт KV engine, policies или AppRole и не загружает данные в Vault.

Пример: JSON payload на защищённом RAM-диске административной Linux-машины `/run/kolla-seed/database_password.json` содержит:

```json
{"password": "REPLACE_WITH_ACTUAL_DATABASE_PASSWORD"}
```

После замены значения выполнить:

```bash
vault kv put -cas=0 -mount=kv \
  kolla/prod-cloud/RegionOne/passwords/shared/database_password \
  @/run/kolla-seed/database_password.json
```

Аналогично загрузить остальные нужные скаляры. Для SSH-ключей payload — объект с `private_key` и `public_key`, путь — имя ключа, например `.../shared/nova_ssh_key`.

`-cas=0` подходит для первоначального создания: запись существующего ключа завершится ошибкой. Обновления выполнять отдельной операцией с проверкой текущей версии. Передавать данные через файл/стандартный ввод, не подставлять реальные пароли в аргументы команды. Возможность JSON-файла и семантика CAS описаны в [Vault kv put](https://developer.hashicorp.com/vault/docs/commands/kv/put).

**Особенность архива:** `kolla-writepwd` есть, но запись требует `--allow-vault-write`, явно обозначенного как break-glass. Утилита пишет только `passwords/shared`, пропускает пустые значения и может обновлять существующие. В штатный deploy её включать не следует. Нельзя подавать ей уже преобразованный файл со ссылками: в коде нет запрета на сохранение этих строк как паролей. Основание: `kolla_ansible/cmd/writepwd.py`.

Какие bootstrap-ключи обязательно подготовить, см. раздел 9. Одного `database_password` достаточно лишь для штатного probe `approle status`, не для deploy.

### 5.3. Runtime policy

Создать `kolla-runtime.hcl` для основного сценария, где все пароли общие:

```hcl
path "kv/data/kolla/prod-cloud/RegionOne/passwords/shared/*" {
  capabilities = ["read"]
}
```

При использовании host-scoped паролей добавить разрешение на фактически нужные пути. Для общей региональной роли это, например:

```hcl
path "kv/data/kolla/prod-cloud/RegionOne/passwords/hosts/*" {
  capabilities = ["read"]
}
```

Расширения для сертификатов приведены в разделе 10. Runtime reader обращается к конкретным `data`-путям; права `list`, запись KV и управление AppRole для этого не нужны. Права просмотра дерева в UI, если нужны оператору, выдаются отдельно.

Загрузить политику:

```bash
vault policy write kolla-runtime-prod-cloud-RegionOne kolla-runtime.hcl
```

### 5.4. Bootstrap policy

Создать `kolla-bootstrap.hcl`:

```hcl
path "auth/kolla-role/role/kolla-prod-cloud-RegionOne/secret-id" {
  capabilities = ["update"]
}

path "auth/kolla-role/role/kolla-agent-bootstrap-prod-cloud-RegionOne/secret-id" {
  capabilities = ["update"]
}

path "sys/wrapping/wrap" {
  capabilities = ["update"]
}
```

```bash
vault policy write kolla-bootstrap-prod-cloud-RegionOne kolla-bootstrap.hcl
```

Эти права восстановлены по вызовам агента: он создаёт runtime SecretID, создаёт собственный следующий SecretID и отдельно оборачивает recovery SecretID через `sys/wrapping/wrap`. Политики только на runtime `secret-id` недостаточно. `lookup` и `unwrap` агент выполняет с wrapping token.

Bootstrap token не имеет прямого права читать KV, но может выдать runtime SecretID и тем самым получить runtime-доступ. Это привилегированный credential хостового сервиса. Не монтировать bootstrap wrapper и bootstrap token в контейнеры.

Основание: `ansible/roles/vault-agent/templates/kolla-vault-agent.py.j2`, [wrapping API](https://developer.hashicorp.com/vault/api-docs/system/wrapping-wrap).

### 5.5. Создать две AppRole

Следующие TTL — пример для проверки интеграции: runtime SecretID 24 часа, bootstrap SecretID 72 часа, tokens 1 час. Выбрать их с учётом допустимого простоя и регламента площадки; агент требует конечные TTL SecretID.

```bash
vault write auth/kolla-role/role/kolla-prod-cloud-RegionOne \
  bind_secret_id=true \
  secret_id_ttl=24h \
  secret_id_num_uses=0 \
  token_type=service \
  token_ttl=1h \
  token_max_ttl=1h \
  token_num_uses=0 \
  token_policies=kolla-runtime-prod-cloud-RegionOne

vault write auth/kolla-role/role/kolla-agent-bootstrap-prod-cloud-RegionOne \
  bind_secret_id=true \
  secret_id_ttl=72h \
  secret_id_num_uses=1 \
  token_type=service \
  token_ttl=1h \
  token_max_ttl=1h \
  token_num_uses=0 \
  token_policies=kolla-bootstrap-prod-cloud-RegionOne
```

Обязательная особенность: **runtime `secret_id_num_uses=0`**. Несколько контейнеров и bootstrap-модуль используют один актуальный SecretID узла; лимит `1` сломает параллельную аутентификацию. Для bootstrap SecretID одноразовое использование допустимо: агент заранее создаёт следующий. `token_num_uses` — отдельный параметр, его не путать с количеством логинов по SecretID. Семантика описана в [AppRole API](https://developer.hashicorp.com/vault/api-docs/auth/approle).

Пример оставляет стандартную `default` policy Vault. Её фактическое содержимое также учитывать при проверке эффективных прав. Если namespace использует изменённую default policy или дополнительные ограничения, проверить работу клиента отдельно.

Получить два RoleID и внести их в `globals.yml`:

```bash
vault read -field=role_id auth/kolla-role/role/kolla-prod-cloud-RegionOne/role-id
vault read -field=role_id auth/kolla-role/role/kolla-agent-bootstrap-prod-cloud-RegionOne/role-id
```

RoleID — идентификатор роли. SecretID, wrapping token и Vault token в `globals.yml` не записываются.

### 5.6. Отдельный временный token для kolla-readpwd

Этот шаг нужен, если reader запускается на отдельном deploy-хосте без локальных runtime AppRole-файлов. Создать отдельную политику только на чтение паролей; она останется read-only и при добавлении PKI-прав к runtime policy:

```bash
vault policy write kolla-readpwd-prod-cloud-RegionOne - <<'EOF'
path "kv/data/kolla/prod-cloud/RegionOne/passwords/shared/*" {
  capabilities = ["read"]
}
EOF

umask 077
vault token create \
  -policy=kolla-readpwd-prod-cloud-RegionOne \
  -ttl=15m -field=token > readpwd.token
```

Административная identity должна иметь право создать token с этой policy. Проверить фактический TTL и default policy площадки. Защищённым каналом передать token оператору reader в `/run/kolla-readpwd/token`, выставить `0400` и владельца пользователя запуска. Выполнить reader до истечения TTL. Это отдельный краткоживущий credential; файл не нужен штатным `kolla-ansible deploy/prechecks`, которые делегируют чтение на узел. Синтаксис выпуска: [Vault token create](https://developer.hashicorp.com/vault/docs/commands/token/create).

## 6. Настроить Kolla globals.yml

Добавить в **существующий** `/etc/kolla/globals.yml`, заменив пример адреса и два RoleID. Настройки региона должны совпадать с путями и именами ролей выше.

```yaml
enable_config_vault: "yes"
kolla_secret_backend: "hashicorp"

openstack_region_name: "RegionOne"
vault_deployment: "prod-cloud"
vault_region: "RegionOne"
vault_mount_point: "kv"

vault_addr: "https://vault.example:8200"
vault_namespace: ""
vault_cacert: "/etc/pki/ca-trust/source/anchors/vault-ca.crt"
vault_container_cacert: ""  # CA уже установлен в системное доверие образов

vault_approle_auth_mount: "kolla-role"
vault_approle_role_name: "kolla-prod-cloud-RegionOne"
vault_approle_role_id: "REPLACE_WITH_RUNTIME_ROLE_ID"

vault_bootstrap_approle_auth_mount: "kolla-role"
vault_bootstrap_approle_role_name: "kolla-agent-bootstrap-prod-cloud-RegionOne"
vault_bootstrap_approle_role_id: "REPLACE_WITH_BOOTSTRAP_ROLE_ID"

vault_wrapped_token_file: "/var/lib/kolla-vault/bootstrap.wrap"
vault_approle_ram_dir: "/run/kolla-vault/approle"
vault_host_scoped_passwords: []

kolla_secret_certificates_source: "local"
config_strategy: "COPY_ALWAYS"

# Опционально: реальное имя доступного узла из inventory.
# По умолчанию используется первый узел группы baremetal.
# vault_bootstrap_host: "controller01"
```

`config_strategy=COPY_ALWAYS` требуется для повторной материализации: после остановки контейнера его приватный tmpfs пуст. `COPY_ONCE` отклоняется prechecks при включённом Vault.

Для standalone `kolla-readpwd` использовать буквальное `vault_region: "RegionOne"` либо передавать `--vault-region`: эта CLI не вычисляет Jinja и не подставляет автоматически `openstack_region_name`. Она также не собирает `globals.d` как Ansible. При переопределении `vault_kv_path` передать соответствующий `--vault-kv-path` явно — reader вычисляет свой default из deployment/region.

`vault_ott_file` существует только как совместимый псевдоним пути. **Содержимое этого файла всё равно должно быть wrapping token**, а не старый долгоживущий token.

Основание: `etc/kolla/globals.yml`, `ansible/group_vars/all.yml`, `ansible/roles/prechecks/tasks/service_checks.yml`, `kolla_ansible/cmd/readpwd.py`.

## 7. Доставить wrapper на каждый узел

На административной машине создать **новый** wrapper для конкретного узла. В примере файл — полный JSON-ответ с `wrap_info.token`, такой формат агент поддерживает:

```bash
umask 077
vault write -format=json -wrap-ttl=24h -f \
  auth/kolla-role/role/kolla-agent-bootstrap-prod-cloud-RegionOne/secret-id \
  > controller01.bootstrap.wrap.json
```

Защищённым каналом доставить его на `controller01` в `/var/lib/kolla-vault/bootstrap.wrap`. На целевом узле права должны быть:

```bash
sudo install -d -o root -g root -m 0700 /var/lib/kolla-vault
# SOURCE — путь уже доставленного файла именно для этого узла.
sudo install -o root -g root -m 0400 SOURCE /var/lib/kolla-vault/bootstrap.wrap
sudo stat -c '%U:%G %a %n' /var/lib/kolla-vault/bootstrap.wrap
```

Повторить выпуск и доставку для **каждого хоста, на который запускается `approle init`**. Playbook `approle.yml` нацелен на `hosts: all`; учитывать состав inventory и используемый `--limit`. Для обычного кластера агент нужен на всех узлах с контейнерами, использующими Vault.

Не размножать один wrapper на несколько узлов: успешный `unwrap` расходует его. Не проверять доставку командой `vault unwrap`. После приёма удалить промежуточные копии по регламенту работы с credentials; рабочая копия на узле нужна для восстановления агента. Одноразовость подтверждена [response wrapping](https://developer.hashicorp.com/vault/docs/concepts/response-wrapping).

Срок `-wrap-ttl` имеет эксплуатационное значение: агент узнаёт его через lookup и использует при выпуске следующих recovery wrappers. В `globals.yml` отдельной настройки wrapper TTL нет. Простой ограничен оставшимся временем жизни **и wrapper, и вложенного bootstrap SecretID**. Изменение только TTL роли не меняет унаследованный wrapper TTL.

## 8. Запустить интеграцию

Команды ниже предназначены для оператора на deploy-хосте с установленным форком, существующим inventory и заполненным `globals.yml`.

### 8.1. Инициализация и проверка агента

```bash
kolla-ansible approle init -i /etc/kolla/multinode
kolla-ansible approle status -i /etc/kolla/multinode
```

`approle init` устанавливает файлы и **всегда перезапускает** `kolla-vault-agent`. Это операция изменения состояния; она запускается до prechecks. `passwords.yml` для неё не требуется. При повторном запуске используется текущий recovery wrapper, который агент успел сохранить на диске.

Ожидаемые файлы:

| Файл | Расположение/режим | Назначение |
|---|---|---|
| `/var/lib/kolla-vault/bootstrap.wrap` | Диск; `root:root 0400` | Текущий recovery wrapper; агент заменяет его атомарно |
| `/etc/kolla/vault-agent.json` | Диск; `0600` | Настройки, пути и RoleID |
| `/usr/local/libexec/kolla-vault-agent` | Диск; `0755` | Python-сервис |
| `/run/kolla-vault/approle/role_id` | tmpfs; `0400` | Runtime RoleID |
| `/run/kolla-vault/approle/secret_id` | tmpfs; `0400` | Runtime SecretID |
| `/run/kolla-vault/status.json` | tmpfs; `0600` | Времена обновления, TTL, счётчики, `last_error` |

`approle init` ждёт появления файлов; **`approle status` дополнительно проверяет runtime login и чтение `database_password#password`**. Успех probe не проверяет весь набор секретов и все контейнеры. AppRole status не изменяет KV, но создаёт login token и читает секрет с `no_log`.

### 8.2. Подготовить passwords.yml со ссылками

На deploy-хосте должен существовать YAML с полной структурой ключей текущей поставки. Для нового окружения взять `etc/kolla/passwords.yml`. Для действующего облака сначала сохранить предусмотренную регламентом резервную копию: `kolla-readpwd` **перезаписывает входной файл**.

У `kolla-readpwd` отдельная аутентификация. Для удалённого deploy-хоста используйте временный read-only token в защищённом файле, которому разрешено чтение bootstrap-путей из манифеста. Если CLI выполняется прямо на узле агента, можно передать локальные runtime RoleID/SecretID-файлы; копировать их между узлами не требуется.

Вариант для deploy-хоста с заранее полученным read-only token в `/run/kolla-readpwd/token` (файл `0400`, владелец — пользователь запуска):

```bash
env -u VAULT_TOKEN -u VAULT_ROLE_ID_FILE -u VAULT_SECRET_ID_FILE \
  kolla-readpwd --pull-only \
  --globals-file /etc/kolla/globals.yml \
  --passwords /etc/kolla/passwords.yml \
  --bootstrap-keys-file /etc/kolla/vault-bootstrap-secrets.yml \
  --vault-deployment prod-cloud \
  --vault-region RegionOne \
  --vault-kv-path kolla/prod-cloud/RegionOne/passwords \
  --vault-token-file /run/kolla-readpwd/token
```

Файл `/etc/kolla/vault-bootstrap-secrets.yml` предварительно взять из `etc/kolla/vault-bootstrap-secrets.yml`. Не путать token-файл reader с `bootstrap.wrap`: wrapper не является token для чтения KV.

Для запуска на узле агента заменить token-file аутентификацию следующими параметрами и обеспечить право чтения root-файлов:

```text
--vault-role-id-file /run/kolla-vault/approle/role_id
--vault-secret-id-file /run/kolla-vault/approle/secret_id
--vault-approle-mount-point kolla-role
```

Результат содержит ссылки, включая поля SSH-ключей, и получает режим `0640`. Пример:

```yaml
database_password: $(vault://kv/data/kolla/prod-cloud/RegionOne/passwords/shared/database_password#password)
nova_ssh_key:
  private_key: $(vault://kv/data/kolla/prod-cloud/RegionOne/passwords/shared/nova_ssh_key#private_key)
  public_key: $(vault://kv/data/kolla/prod-cloud/RegionOne/passwords/shared/nova_ssh_key#public_key)
```

Reader проверяет bootstrap-манифест; остальные runtime-секреты не читает. Поэтому успешный `kolla-readpwd` **не является проверкой полноты Vault**. `--allow-missing-bootstrap` ослабляет только эту проверку, а не требования последующего deploy. `--bootstrap-output` больше не создаёт plaintext-файл; `--legacy-materialize-all` запрещён.

### 8.3. Prechecks и развёртывание

```bash
kolla-ansible prechecks -i /etc/kolla/multinode
```

Устранить замечания по Vault, TLS, образам и остальным компонентам. Затем выполнять штатный сценарий площадки. Для нового облака команды в этой CLI имеют вид:

```bash
kolla-ansible pull -i /etc/kolla/multinode
kolla-ansible deploy -i /etc/kolla/multinode
```

Для существующего облака миграцию на Vault планировать отдельно: запись KV, формат файлов и готовность образов должны быть согласованы до `reconfigure`. Эта инструкция не подтверждает бесшовную миграцию работающего облака.

CLI добавляет `vault-bootstrap-fetch.yml` перед основной операцией в **тот же процесс ansible-playbook**. Прямой запуск `ansible-playbook site.yml` обходит этот механизм. `--check` и `--list-tasks` пропускают добавление fetch и не доказывают работоспособность login/read.

`post-deploy` опционален для выдачи клиентских файлов:

```bash
kolla-ansible post-deploy -i /etc/kolla/multinode
```

Он создаёт на deploy-хосте `clouds.yaml` и `*-openrc*.sh` с реальными credentials, `0600`; при включённой Octavia также её openrc. Это явно реализованное исключение из схемы хранения только ссылок, а не RAM-only результат. Основание: `kolla_ansible/cli/commands.py`, `ansible/post-deploy.yml`.

## 9. Bootstrap-секреты: что проверяется фактически

Есть **три отдельных перечня**:

1. `etc/kolla/vault-bootstrap-secrets.yml` — проверка standalone `kolla-readpwd`.
2. `vault_bootstrap_allowed_secrets` в group vars — допустимые ключи для CLI-fetch.
3. `VAULT_BOOTSTRAP_*_SECRETS` в CLI — фактически запрашиваемые ключи каждой команды.

### 9.1. Минимум required для kolla-readpwd

Стандартный манифест требует семь ключей:

```text
database_password
heat_domain_admin_password
keystone_admin_password
libvirt_sasl_password
mariadb_monitor_password
nova_database_password
rabbitmq_cluster_cookie
```

Остальные ключи манифеста при отсутствии дают предупреждения reader. Их отсутствие всё ещё может остановить соответствующую Kolla-команду.

### 9.2. Полный набор для deploy/reconfigure/upgrade

CLI запрашивает следующий набор, а fetch требует непустое поле `password` для каждого оставшегося ключа:

```text
database_password
docker_registry_password
haproxy_password
heat_domain_admin_password
mariadb_monitor_password
keystone_admin_password
libvirt_sasl_password
nova_database_password
octavia_keystone_password
prometheus_bcrypt_salt
prometheus_password
prometheus_grafana_password
prometheus_haproxy_password
prometheus_skyline_password
rabbitmq_cluster_cookie
rbd_secret_uuid
cinder_rbd_secret_uuid
```

Fetch исключает `docker_registry_password`, если не задан `docker_registry_username`, и `octavia_keystone_password`, если выключена Octavia. Остальные ключи этого списка автоматически по feature flags не отфильтровываются. Например, выключение Prometheus само по себе не убирает его пароли из запроса CLI.

### 9.3. Другие команды

| Команда | Запрашиваемые ключи до основной операции |
|---|---|
| `approle init/status/stop` | Общего bootstrap-fetch нет |
| `prechecks` | `prometheus_bcrypt_salt`, `prometheus_password`, `prometheus_grafana_password`, `prometheus_skyline_password` |
| `genconfig` | `haproxy_password`, пять ключей `prometheus_*` из deploy-списка, `rabbitmq_cluster_cookie`, оба `rbd_secret_uuid` |
| `deploy-containers` | `docker_registry_password`, `haproxy_password`, `mariadb_monitor_password`, `rabbitmq_cluster_cookie` |
| `pull` | `docker_registry_password`, если нужна registry-аутентификация |
| `check` | `redis_master_password` |
| `post-deploy` | `keystone_admin_password`, `octavia_keystone_password` при включённой Octavia |
| `octavia-certificates` | `octavia_ca_password`, `octavia_client_ca_password` |

Манифест reader содержит `opensearch_dashboards_password` и `etcd_cluster_token`, которых нет в глобальном allow-list CLI-fetch. Соответствующие plaintext aliases в group vars присутствуют, но одних aliases недостаточно для получения значений. Нельзя просто добавить эти имена в запрос fetch, не согласовав allow-list и потребителей.

Источники: `etc/kolla/vault-bootstrap-secrets.yml`, `kolla_ansible/cli/commands.py`, `ansible/vault-bootstrap-fetch.yml`.

## 10. Сертификаты: три режима

| `kolla_secret_certificates_source` | Что подготовить | Что делает Kolla |
|---|---|---|
| `local` | Сертификаты штатного файлового workflow | Обычное копирование файлов; пароли могут оставаться в Vault |
| `kv` | Готовые сертификаты, ключи и CA в KV | Создаёт pointer-файлы на узлах; ожидает материализацию в контейнерах |
| `pki` | Настроенный PKI issuer, шесть профилей ролей, ACL на выпуск | Формирует PKI-ссылки с CN/SAN; runtime должен выпускать и материализовать сертификаты |

Флаг источника сертификатов сам по себе не включает TLS/mTLS у сервисов. Соответствующие `kolla_enable_tls_*`, `kolla_enable_mtls_*`, параметры RabbitMQ/БД/libvirt выбираются отдельно. Для `kv` и `pki` нужен `enable_config_vault=yes` и `COPY_ALWAYS`; внутренний `enable_vault_file_sources` вручную не задавать.

### 10.1. Готовые сертификаты в KV

Установить:

```yaml
kolla_secret_certificates_source: "kv"
```

Здесь `P = kolla/prod-cloud/RegionOne`, mount `kv`:

| Логический KV-путь | Поля, используемые ролями | Назначение |
|---|---|---|
| `P/certificates/hosts/<inventory_hostname>/backend` | `cert`, `key`; также `pem` для HAProxy backend client | Backend-сервер и общий client identity узла |
| `P/certificates/shared/haproxy-external` | `pem` | Внешний frontend/VIP |
| `P/certificates/shared/haproxy-internal` | `pem` | Внутренний frontend/VIP |
| `P/certificates/shared/database` | `cert`, `key` | Общая идентичность БД; ProxySQL либо MariaDB без ProxySQL |
| `P/certificates/hosts/<inventory_hostname>/libvirt-client` | `cert`, `key` | Клиент libvirt |
| `P/certificates/hosts/<inventory_hostname>/libvirt-server` | `cert`, `key` | Сервер libvirt |
| `P/certificates/trust/internal-ca` | `ca` | PEM trust bundle внутреннего контура |

Загружать объекты, которые реально нужны включённым сервисам. `cert` содержит PEM сертификата с нужной цепочкой, `key` — соответствующий PEM private key, `pem` — объединённый комплект для HAProxy. SAN должны покрывать реальные имена/IP, используемые клиентами. Для mTLS сертификат должен иметь подходящие server/client EKU. При включённом ProxySQL MariaDB использует host backend identity, а ProxySQL — общий database identity.

Пример первоначальной записи host backend (файлы заранее подготовлены на административной машине):

```bash
vault kv put -cas=0 -mount=kv \
  kolla/prod-cloud/RegionOne/certificates/hosts/controller01/backend \
  cert=@/run/kolla-seed/controller01.crt \
  key=@/run/kolla-seed/controller01.key \
  pem=@/run/kolla-seed/controller01.pem
```

Добавить в runtime policy:

```hcl
path "kv/data/kolla/prod-cloud/RegionOne/certificates/*" {
  capabilities = ["read"]
}
```

Это общий региональный доступ. Для более узких прав перечислить нужные host/shared/trust пути.

В `kv`/`pki` команда `kolla-ansible certificates` намеренно завершается ошибкой: host-side генерация отключена. `vault_extra_ca_files` позволяет описать дополнительные CA из KV; это не механизм первого доверия к HTTPS Vault.

Основание: `ansible/roles/service-cert-copy/tasks/main.yml`, `ansible/roles/loadbalancer/tasks/copy-certs.yml`, `ansible/roles/nova-cell/tasks/config-libvirt-tls.yml`, `ansible/roles/certificates/tasks/main.yml`.

### 10.2. Выпуск через Vault PKI

В Vault заранее подготовить PKI mount с пригодным issuing CA и цепочкой доверия. Подписание промежуточного CA выполняется по принятому регламенту PKI; архив не создаёт issuer и не содержит параметров корпоративного CA.

Настройки Kolla:

```yaml
kolla_secret_certificates_source: "pki"
kolla_secret_pki_mount: "pki"
kolla_secret_pki_roles:
  backend: "kolla-backend"
  haproxy_external: "kolla-haproxy-external"
  haproxy_internal: "kolla-haproxy-internal"
  database: "kolla-database"
  libvirt_client: "kolla-libvirt-client"
  libvirt_server: "kolla-libvirt-server"
```

**AppRole и PKI role — разные объекты.** Runtime AppRole разрешает API-доступ; PKI role определяет допустимые имена, TTL, ключ и EKU сертификата.

| PKI role | CN / DNS SAN из Kolla | IP SAN из Kolla | Назначение EKU |
|---|---|---|---|
| `kolla-backend` | `inventory_hostname` | `api_interface_address` | serverAuth; также clientAuth при использовании общего mTLS identity |
| `kolla-haproxy-external` | `kolla_external_fqdn` | `kolla_external_vip_address` | serverAuth |
| `kolla-haproxy-internal` | `kolla_internal_fqdn` | `kolla_internal_vip_address` | serverAuth |
| `kolla-database` | CN `database_address`; DNS SAN `database_address`, `kolla_internal_fqdn` | `kolla_internal_vip_address` | serverAuth; clientAuth, если topology использует комплект для исходящих mTLS-соединений |
| `kolla-libvirt-client` | `inventory_hostname` | `migration_interface_address` | clientAuth |
| `kolla-libvirt-server` | `inventory_hostname` | `migration_interface_address` | serverAuth |

Поля CN/SAN восстановлены из group vars; назначение EKU — требование потребителей сертификатов. TTL, алгоритм и размер ключа задать на PKI-ролях. В ссылках форк передаёт только CN, DNS SAN и IP SAN. Роли должны разрешать реальные значения inventory, включая короткие имена, если они используются, и IP SAN. При `database_address` в виде IP отдельно проверить принятие сформированного профиля Vault и hostname verification драйвером БД.

Минимальный образец **одной** PKI-роли для двух конкретных узлов при уже настроенном issuer:

```bash
vault write pki/roles/kolla-backend \
  allowed_domains='controller01,compute01' \
  allow_bare_domains=true \
  allow_subdomains=false \
  allow_any_name=false \
  allow_ip_sans=true \
  server_flag=true \
  client_flag=true \
  key_type=rsa \
  key_bits=2048 \
  ttl=24h \
  max_ttl=24h
```

Заменить список имён на действительный; остальные пять ролей создать по таблице с собственными разрешёнными именами и EKU. `24h` и RSA 2048 — пример, не параметры из архива. `allow_ip_sans=true` само по себе не ограничивает разрешённые IP конкретным хостом; при общей runtime-роли учитывать эту границу авторизации. Параметры role/issue подтверждены [PKI API](https://developer.hashicorp.com/vault/api-docs/secret/pki).

Добавить к runtime policy точные endpoints выпуска:

```hcl
path "pki/issue/kolla-backend" { capabilities = ["update"] }
path "pki/issue/kolla-haproxy-external" { capabilities = ["update"] }
path "pki/issue/kolla-haproxy-internal" { capabilities = ["update"] }
path "pki/issue/kolla-database" { capabilities = ["update"] }
path "pki/issue/kolla-libvirt-client" { capabilities = ["update"] }
path "pki/issue/kolla-libvirt-server" { capabilities = ["update"] }
```

Повторно загрузить объединённый `kolla-runtime.hcl`, сохранив правила чтения паролей. По коду ожидается ответ с `certificate`, `private_key`, `issuing_ca` и `ca_chain`. Внутренний trust anchor в PKI-режиме берётся через `#chain` из PKI-профиля, а не из KV `certificates/trust/internal-ca`. Дополнительные внешние CA из `vault_extra_ca_files` остаются KV-backed.

**Автоматическое обновление сертификатов и reload сервисов этим ZIP не доказаны.** Агент обновляет AppRole credentials, а не сертификаты приложений. Перед применением коротких TTL проверить механизм обновления внутри конкретных образов и реакцию сервисов на смену файла.

### 10.3. Ограничения по отдельным сервисам

- `vault_octavia_kv_path` объявлен, но в просмотренном дереве не найден потребитель этого пути. Материалы Amphora CA продолжают обрабатываться локальными задачами `octavia-certificates` и копироваться из файлов в `octavia/tasks/config.yml`. Не считать общую настройку `pki` доказательством переноса всего контура Octavia в Vault.
- Prechecks запрещают внутренний frontend mTLS вместе с `enable_glance_image_cache`, а RabbitMQ mTLS — вместе с `enable_trove`.
- Для backend mTLS требуется `kolla_verify_tls_backend=yes`; mTLS-флаги требуют соответствующих TLS-флагов.

Основание: `ansible/roles/octavia/tasks/config.yml`, `ansible/roles/octavia-certificates/tasks/main.yml`, `ansible/roles/prechecks/tasks/service_checks.yml`.

## 11. Проверка и эксплуатация

### 11.1. На управляемом узле

Следующие команды не печатают SecretID и прикладные значения:

```bash
sudo systemctl is-active kolla-vault-agent
sudo systemctl is-enabled kolla-vault-agent
sudo findmnt -n -o FSTYPE -T /run/kolla-vault/approle
sudo stat -c '%U:%G %a %n' \
  /var/lib/kolla-vault/bootstrap.wrap \
  /run/kolla-vault/approle/role_id \
  /run/kolla-vault/approle/secret_id
sudo cat /run/kolla-vault/status.json
sudo journalctl -u kolla-vault-agent --since '-15 min' --no-pager
```

Проверить `active`, `enabled`, `tmpfs`, владельца `root:root`, режим `400`, `last_error: null`. Счётчики должны увеличиваться **после наступления соответствующего срока**, а не сразу при каждом просмотре. По умолчанию обновление запланировано приблизительно на 2/3 TTL; для wrapper берётся минимум TTL wrapper и вложенного SecretID, для повторного bootstrap login — минимум token TTL и SecretID TTL. Отзыв старых runtime SecretID код не выполняет; они доживают до своего TTL.

### 11.2. В контейнере

Для фактического engine и существующего контейнера проверить mount-ы. Пример для default Podman:

```bash
sudo podman inspect --format '{{json .Mounts}}' keystone
sudo podman inspect --format '{{json .HostConfig.Tmpfs}}' keystone
sudo podman exec keystone sh -c \
  'stat -f -c %T /run/kolla-vault-secrets; test -r /run/kolla-vault/approle/secret_id'
```

Проверить read-only mount `/run/kolla-vault/approle` и отдельный tmpfs `/run/kolla-vault-secrets`. Не выводить конечные конфиги или credential-файлы в терминал/логи. Наличие mount-ов — только проверка доставки; дополнительно нужны фактический успешный старт сервиса, login/read по Vault audit и отсутствие неразрешённых ссылок в используемой конфигурации.

Имя `keystone` — пример; уточнить через `podman ps`. Для Docker выбрать Docker CLI. `noexec` включён в default tmpfs только для Docker; в Podman default требуются `nosuid,nodev`, поэтому нельзя выдавать `noexec` за общий инвариант архива.

### 11.3. Восстановление агента

| Ситуация | Действие |
|---|---|
| Wrapper ещё действителен, Vault доступен | При старте агент unwrap-ит его и немедленно сохраняет новый recovery wrapper |
| Wrapper просрочен или уже использован | Администратор выпускает новый wrapper для этого узла, доставляет с `0400`; оператор выполняет `approle init --limit <узел>`, затем `approle status --limit <узел>` |
| Отозвана/изменена AppRole | Проверить обе роли, policies и RoleID; после исправления при необходимости перевыпустить wrapper |
| Сеть недоступна во время refresh | Агент записывает `last_error` и повторяет попытки; если bootstrap credential истёк, одна лишь доступность сети может уже не восстановить работающий процесс — проверить recovery wrapper и перезапуск по регламенту |
| Нужна остановка интеграции | `approle stop` отключает unit и удаляет RAM-файлы; выполнять как отдельное изменение, поскольку контейнерам могут понадобиться credentials для следующего login |

Пример адресного восстановления:

```bash
kolla-ansible approle init -i /etc/kolla/multinode --limit controller01
kolla-ansible approle status -i /etc/kolla/multinode --limit controller01
```

В коде явно обозначено окно сбоя: между успешным одноразовым unwrap и сохранением нового wrapper авария может лишить узел рабочего recovery credential. Резервная копия старого wrapper не гарантирует восстановление после его использования.

После reboot отдельно проверить порядок старта контейнеров и агента. Unit агента зависит от сети и tmpfiles; зависимость всех контейнерных сервисов от готовности AppRole-файлов этим unit не задаётся. Устойчивость запуска при пустом `/run` проверить на целевой системе.

## 12. Типовые ошибки

| Симптом | Что проверить |
|---|---|
| `HTTP 403` на `...runtime-role/secret-id` | Bootstrap policy разрешает `update` на точное имя runtime-роли |
| `HTTP 403` на `...bootstrap-role/secret-id` | Разрешено создание следующего собственного bootstrap SecretID |
| `HTTP 403` на `sys/wrapping/wrap` | Есть отдельное право wrap; проверены namespace и эффективные policies |
| Ошибка lookup/unwrap | Wrapper не истёк, не использован другим узлом, создан от bootstrap-роли; в файле не обычный token |
| `creation_path ... expected ...` | Wrapper создан от указанной bootstrap AppRole или через `sys/wrapping/wrap` |
| `runtime AppRole SecretID num_uses must be 0` | У runtime-роли выставить `secret_id_num_uses=0` |
| `SecretID TTL must be finite` | Проверить `secret_id_ttl` обеих ролей; нулевой TTL отклоняется |
| `not RAM-backed tmpfs` | `/run/kolla-vault/approle` действительно находится на tmpfs |
| `Requested bootstrap secret ... unavailable` | Нужный путь, поле `password`, ACL, namespace, TLS; сверить список именно запускаемой команды |
| `kolla-readpwd` успешен, deploy падает на секрете | Reader проверял другой перечень; проверить раздел 9 и runtime-секреты включённых сервисов |
| В приложении остался `$(vault://...)` | Образ поддерживает resolver, его config.json содержит секцию `vault`, credentials и CA доступны |
| TLS Vault не проходит | CA установлен до обращения к Vault; различать путь на хосте и путь в контейнере |
| Сертификат PKI не выпускается | Runtime ACL на точную issue-role, разрешённые CN/SAN, issuer, ограничения TTL/EKU |
| `certificates` отказывается работать | В `kv`/`pki` это ожидаемое поведение; материал готовится вне host-side генератора |

## 13. Границы реализации и результаты проверки

### 13.1. Что подтверждено исходниками

- Канонические пути KV v2, формат ссылок и разделение shared/hosts.
- Две AppRole, потребность bootstrap policy в выдаче обоих видов SecretID и отдельном wrapping API.
- Обновление runtime SecretID, recovery wrapper и повторная bootstrap-аутентификация; credentials в `/run`.
- Порядок `approle` → bootstrap-fetch → штатная операция CLI.
- Отдельные режимы сертификатов; профили CN/SAN и контракт PKI API.
- Определённые в Ansible требования к mounts/tmpfs и ограничения prechecks.

### 13.2. Что нельзя утверждать по этому архиву

- Работоспособность конкретного Vault endpoint, политики на сервере и наличие всех значений.
- Поддержка resolver и автоматической ротации сертификатов фактическими образами `latest`.
- Полная изоляция секретов каждого узла/сервиса при общей региональной роли.
- Отсутствие всех persistent secrets: `post-deploy` прямо создаёт plaintext-клиентские файлы; локальные сертификаты и Octavia имеют собственный workflow.
- Корректная работа всех вариантов mTLS и восстановление при reboot/outage без стендовых испытаний.

**Дополнительное расхождение:** при `enable_security_audit` функция `security_audit.ensure_passwords()` добавляет отсутствующие audit-ключи в `passwords.yml` как сгенерированные значения, без проверки `enable_config_vault`. Поэтому старый неполный YAML может снова получить plaintext даже после перевода на ссылки. Использовать полный шаблон поставки, обеспечить наличие и Vault-ссылки всех audit-ключей; отдельная проверка нужна перед объявлением файла reference-only. Основание: `kolla_ansible/security_audit.py`.

### 13.3. Локальные тесты

Выполнены **83 существующих теста** восьми профильных модулей на macOS / Python 3.11.15. Результат: **79 passed, 3 failures, 1 error**. Это не успешный полный прогон поставки.

| Проверка | Результат и объяснение |
|---|---|
| `test_site_scope_contains_only_current_controller_consumers` | Тест не ожидает `mariadb_monitor_password`, фактический CLI его включает |
| `test_nova_bootstrap_copies_vault_internal_ca` | Тест ищет буквальный `vault_file_reference`; текущая задача использует `trust_ca_reference` с переключением KV/PKI |
| `test_mtls_database_urls_verify_ca_and_identity` | Тест ищет `openstack_cacert`, `ssl_verify_cert`, `ssl_verify_identity`; текущие шаблоны используют `database_cacert` и `ssl_check_hostname`. Нужна отдельная проверка с драйвером/образом, а не вывод об отсутствии TLS по одному строковому тесту |
| `test_wrapped_token_reader_accepts_raw_and_wrap_info_json` | Ошибка окружения: тестовый файл принадлежит текущему пользователю macOS, а агент требует `root:root` |

При предварительной попытке `test_vault_tmpfs` не импортировался из-за отсутствия Linux-зависимости `dbus`; этот модуль не входит в итоговые 83 теста. Его классы также рассчитаны на pytest, поэтому проверять его следует в штатном Linux test environment.

Повторить этот набор существующих тестов можно из корня распакованного архива:

```bash
uv run --offline --no-project --python 3.11 \
  --with pyyaml --with cliff --with jinja2 \
  python -B -m unittest \
  kolla_ansible.tests.unit.test_readpwd_vault \
  kolla_ansible.tests.unit.test_secret_backends \
  kolla_ansible.tests.unit.test_vault_file_sources \
  kolla_ansible.tests.unit.test_vault_bootstrap_scoping \
  kolla_ansible.tests.unit.test_vault_mtls_merge \
  kolla_ansible.tests.unit.test_secret_architecture \
  kolla_ansible.tests.unit.test_approle_bootstrap_order \
  kolla_ansible.tests.unit.test_wrapped_secret_agent
```

`--offline` предполагает уже доступные зависимости. Команда запускает существующие тесты и возвращает ненулевой код при ошибках. Исходники архива не исправлялись. Полный протокол и машиночитаемый результат сохранены локально при подготовке инструкции; в эту ветку они не включены.

## 14. Карта исходников для сопровождения инструкции

Номера строк относятся только к разобранному ZIP; при другой поставке сверять заново.

| Вопрос | Файл и ориентир |
|---|---|
| CLI entrypoints и внешние коллекции | `setup.cfg:55`, `requirements.yml:1`, `requirements-core.yml:1` |
| Общие настройки интеграции | `ansible/group_vars/all.yml:1617` |
| KV-пути и host scopes | `ansible/group_vars/all.yml:1715` |
| Источник сертификатов и PKI identities | `ansible/group_vars/all.yml:1738` |
| AppRole/wrapper и tmpfs | `ansible/group_vars/all.yml:1862` |
| Значения host agent по умолчанию | `ansible/roles/vault-agent/defaults/main.yml:1` |
| Установка и запуск агента | `ansible/roles/vault-agent/tasks/init.yml:1` |
| Wrap/login/SecretID lifecycle | `ansible/roles/vault-agent/templates/kolla-vault-agent.py.j2:156`, `:292` |
| systemd unit | `ansible/roles/vault-agent/templates/kolla-vault-agent.service.j2:1` |
| Функциональная проверка AppRole | `ansible/roles/vault-agent/tasks/status.yml:1` |
| Формирование password references | `kolla_ansible/cmd/readpwd.py:151`, `:299` |
| Списки fetch по командам | `kolla_ansible/cli/commands.py:25`, `:148`, `:308` |
| Делегирование чтения на узел | `ansible/vault-bootstrap-fetch.yml:1` |
| KV/PKI HTTP-контракт | `kolla_ansible/secret_backends.py:116` |
| Формат certificate references | `kolla_ansible/vault_file_sources.py:18` |
| Проверки режима и mTLS | `ansible/roles/prechecks/tasks/service_checks.yml:34` |
| Persistent admin-файлы | `ansible/post-deploy.yml:11` |

**Критерий готовности к применению:** реальные параметры заменены, Vault-объекты созданы, probe проходит на каждом целевом узле, bootstrap-списки обеспечены, образы проверены, prechecks выполнены, выбранный TLS/PKI-сценарий подтверждён на стенде. Подготовка этой инструкции подтверждает восстановленный контракт из исходников; она не заменяет перечисленные live-проверки.
