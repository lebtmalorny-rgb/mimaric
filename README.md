# Keystone Epoxy 2025.1: исключение сервисных записей из парольной политики

Пакет добавляет защищённый признак `user.options.password_policy_exempt`. Для помеченной записи Keystone пропускает проверку сложности/длины через `password_regex`, историю и минимальный возраст пароля. Для остальных записей действуют обычные настройки Keystone. Исключения из первой смены, срока действия и блокировки задаются тремя штатными options одновременно с новым признаком.

Роли `admin`, `member`, `service`, имя пользователя и вызывающий сервис не определяют исключение. Человеческий администратор остаётся под политикой. API по-прежнему проверяет тип/техническую максимальную длину, старый пароль при самосмене, `lock_password`, состояние пользователя и домена.

Подготовлены исходники и патчи. Образ в registry и изменения на кластере этим пакетом **не создавались**. Отчёты локальных проверок находятся в [reports](reports/).

Проверки: **Keystone — 1037 passed, 3 skipped, 0 failed** в выбранном regression suite; после финальной правки imports — 31/31 feature tests. **Kolla — 37/37** целевых проверок. Оба патча применены к чистым базам и сравнены с финальными исходниками: 0 расхождений; исходный sdist также совпадает со всеми изменёнными файлами. Независимое [ревью](reports/final-review.md) одобрило упаковку. Отдельно воспроизведены существующие ошибки вне патча: 29 setup errors дополнительного Keystone protection suite и 2 падения Vault/mTLS тестов исходной Kolla; детали в отчётах, а не скрыты в итоговом счётчике.

## Получение пакета

```bash
git clone --single-branch --branch feature/keystone-password-policy-2025.1 \
  https://github.com/lebtmalorny-rgb/mimaric.git password-policy-patches
cd password-policy-patches
sha256sum -c SHA256SUMS
```

На macOS использовать `shasum -a 256 -c SHA256SUMS`. Далее пути `/path/to/password-policy-patches` в примерах заменить на абсолютный путь этой папки.

## 1. Состав и точная база

| Файл | Назначение |
|---|---|
| `keystone-password-policy-exempt.patch` | Патч Keystone, включая API/SQL-тесты и upstream-документацию |
| `kolla-service-password-policy.patch` | Регистрация сервисных identities с исключениями с первого запроса |
| `keystone-password-policy-source.tar.gz` | Исходный sdist для сборки образов Kolla |
| `SHA256SUMS` | Контрольные суммы поставки |
| `examples/` | Примеры настроек, которые требуется адаптировать к окружению |
| `reports/` | RED/GREEN, границы проверки и результаты ревью |

Keystone: официальный `stable/2025.1`, **`537e65b2b1d4b8e0fe1faa09c8f882a6b2899b21`**. Это зафиксированная ревизия Epoxy, а не плавающий `latest` и не первоначальный 27.0.0. Устанавливать поверх другой ревизии без проверки diff нельзя.

Kolla: предоставленное дерево `kolla-ansible-pvs_1.0.0` из архива `kolla-ansible-pvs_1.0.0_14.09.zip`. Локальный исходный snapshot: `54f4ee851cc2fc5db1068a8c5807f2b8e8e2c475`. Этот SHA создан для сравнения распакованного дерева; это не upstream commit Kolla. Исходный архив Kolla предоставляется отдельно; в эту ветку входят патчи и sdist Keystone. Пути рабочих копий в отчётах описывают среду локальной проверки и не нужны для установки.

Финальные commits: Keystone `323e6fadc43b342afb9315c0efef837c8dd10320`, Kolla `0f9aac2d479087808283ddb7fa382b6a8a1db00c`. SHA-256 исходного ZIP Kolla: `bbb7bfb1398cbe07a12e374cae56f03e9e5c192798cf3ff7842aa75d8c2d7e44`. Контроль поставки: из этой папки выполнить `sha256sum -c SHA256SUMS` (на macOS: `shasum -a 256 -c SHA256SUMS`).

Новая resource option имеет ID `PPEX`, помещается в существующую таблицу options. Миграция схемы БД не нужна. Все Keystone workers должны понимать новую опцию.

## 2. Применение патчей к исходникам

В отдельной сборочной папке:

```bash
git clone --branch stable/2025.1 https://opendev.org/openstack/keystone.git
cd keystone
git checkout --detach 537e65b2b1d4b8e0fe1faa09c8f882a6b2899b21
git apply --check /path/to/password-policy-patches/keystone-password-policy-exempt.patch
git apply /path/to/password-policy-patches/keystone-password-policy-exempt.patch
```

В копии вашей поставки Kolla:

```bash
cd /path/to/kolla-ansible-pvs_1.0.0
git apply --check /path/to/password-policy-patches/kolla-service-password-policy.patch
git apply /path/to/password-policy-patches/kolla-service-password-policy.patch
```

Для `git apply` распакованная папка может не быть Git-репозиторием. Патч не устанавливает обновлённую Kolla в Python environment автоматически: при установке Kolla через pip переустановить именно изменённую копию обычным для вашего deploy-узла способом. Проверить, что запускаемый `kolla-ansible` использует её `ansible/library` и роли.

## 3. Сборка Keystone-образов

В вашем сборщике Kolla **ветки 2025.1**, сохраняя текущие distro, namespace, registry, сертификаты и другие применяемые патчи, добавить в `kolla-build.conf`:

```ini
[keystone-base]
type = local
location = /absolute/path/password-policy-patches/keystone-password-policy-source.tar.gz
```

Далее выполнить обычную сборку семейства Keystone, например:

```bash
kolla-build --config-file /etc/kolla/kolla-build.conf \
  --tag 2025.1-password-policy-1 '^keystone'
```

Проверить созданные `keystone`, `keystone-fernet`, `keystone-ssh`, затем опубликовать их в вашем registry штатным процессом. Пример не задаёт новый registry и не выполняет push. Исходник Keystone используется в общем `keystone-base`, поэтому выбранный тег должен существовать для всех образов семейства.

`keystone-password-policy-source.tar.gz` содержит локальную версию `27.1.1.dev1+passwordpolicy.1` и metadata для PBR; runtime-зависимости не обновлялись патчем. В конечном образе проверить импорт:

```bash
docker run --rm --entrypoint /var/lib/kolla/venv/bin/python \
  registry.example.org/openstack/keystone:2025.1-password-policy-1 \
  -c 'from keystone.identity.backends.resource_options import PASSWORD_POLICY_EXEMPT_OPT; print(PASSWORD_POLICY_EXEMPT_OPT.option_id)'
```

Ожидается `PPEX`. Адрес образа в примере заменить на реальный. Зафиксировать digest образа; один только тег не доказывает одинаковые исходники на всех узлах. Linux container build в этой работе не запускался.

Механизм локального source подтверждён [Kolla 2025.1 image building](https://docs.openstack.org/kolla/2025.1/admin/image-building.html#build-openstack-from-source) и [шаблоном keystone-base](https://opendev.org/openstack/kolla/src/branch/stable/2025.1/docker/keystone/keystone-base/Dockerfile.j2).

## 4. Кто вправе назначать исключения

Новое дополнительное правило:

```yaml
"identity:manage_password_policy_exemption": "role:admin and system_scope:all"
```

Это default патча. Проверяются также штатные `identity:create_user` / `identity:update_user`. Передача поля со значением `false` или `null` тоже требует нового права. `null` удаляет сохранённую опцию; разрешены Boolean и штатное удаление, строка `"true"` недопустима. Изменение классификации попадает в CADF reason и журнал Keystone без пароля.

Kolla обычно получает project-scoped токен. Для отдельного оператора автоматизации можно добавить `/etc/kolla/config/keystone/policy.yaml`:

```yaml
"identity:manage_password_policy_exemption": "(role:admin and system_scope:all) or (role:admin and user_id:DEPLOYMENT_USER_UUID and project_id:ADMIN_PROJECT_UUID)"
```

Заменить оба UUID после проверки `openstack user show` и `openstack project show`. Это точечное разрешение конкретной deployment identity. Не заменять его общим `role:admin`: тогда любой администратор с обычным управлением пользователями получит право отключать политику.

Использовать реальный поддерживаемый путь override вашей поставки: задачи Kolla (`kolla-ansible-pvs_1.0.0/ansible/roles/keystone/tasks/config.yml` в исходном архиве) копируют `policy.yaml` в контейнер. Если уже есть файл, добавить правило, сохранив остальные. Проверить `[oslo_policy] policy_file` и фактический файл во всех workers.

## 5. Bootstrap / deployment admin и персональный admin

Разделить техническую запись Kolla и персональные учётные записи. `admin` — также название роли: персональный пользователь с этой ролью не должен получать исключение.

Стандартный `kolla_keystone_bootstrap` создаёт bootstrap identity отдельно от `service-ks-register`. Патч **не объявляет её сервисной автоматически**. Для новой установки выполнять bootstrap при ещё выключенных человеческих настройках; затем явно классифицировать техническую deployment identity и только после этого включать политику. Для действующей установки проверить её назначение и options до включения политики. Нельзя использовать одну запись одновременно как персональный вход и постоянный credential Kolla.

Штатный `keystone_admin_user` можно выбрать отдельным техническим именем при проектировании новой установки. Для действующей установки смена deployment identity требует согласованного переноса прав, auth и секретов; этот патч его не выполняет. Если выбранная запись является человеческой, сначала создать отдельную техническую identity обычным управляемым процессом.

## 6. Options сервисной записи

Разрешённый оператор передаёт через `PATCH /v3/users/USER_UUID`:

```json
{
  "user": {
    "options": {
      "password_policy_exempt": true,
      "ignore_change_password_upon_first_use": true,
      "ignore_lockout_failure_attempts": true,
      "ignore_password_expiry": true
    }
  }
}
```

Не требуется сбрасывать сервисный пароль для назначения options. Штатный API обновляет переданные options, сохраняя остальные. Проверить ответ и последующее `GET /v3/users/USER_UUID`. Новый признак отключает regex, историю и минимальный возраст; три native flags отключают отдельные механизмы первой смены, lockout и expiry. Установка только `password_policy_exempt` не отключает остальные механизмы.

CLI `--password-policy-exempt` не добавлялся. Для автоматизации через SDK:

```python
from openstack import connection

conn = connection.from_config(cloud='operator')
user = conn.identity.get_user('SERVICE_USER_UUID')
options = dict(user.options or {})
options.update(
    password_policy_exempt=True,
    ignore_change_password_upon_first_use=True,
    ignore_lockout_failure_attempts=True,
    ignore_password_expiry=True,
)
conn.identity.update_user(user, options=options)
```

Cloud `operator` должен использовать разрешённую identity из раздела 4; UUID берётся из утверждённого списка сервисов. Код не должен определять сервисную принадлежность по роли или имени.

## 7. Автоматизация Kolla

После установки образа и policy override добавить в `/etc/kolla/globals.yml`:

```yaml
keystone_tag: "2025.1-password-policy-1"
keystone_service_password_policy_exempt: true
```

Сохранить ваш `keystone_image`/registry; убедиться, что `keystone_service_tag` и `keystone_image_full` не переопределены другим значением. По умолчанию новый флаг `false`, используется штатный `openstack.cloud.identity_user`.

При `true` общая роль использует `kolla_service_user`, а также покрывает отдельный Magnum trustee. Модуль копируется в `/etc/kolla/kolla-toolbox/ansible/library/` на выбранном контроллере и доступен внутри уже существующего config mount toolbox. Пересборка toolbox не требуется. Требуются `openstack.cloud` и openstacksdk внутри toolbox; проверенная пара: **2.4.1 / 4.4.0**, Ansible core **2.17.14**.

Создание отправляет пароль и все четыре options одним запросом. Обновление объединяет options с существующими; когда включена ротация, новый пароль отправляется вместе с ними, а Keystone проверяет итоговую классификацию. `update_keystone_service_user_passwords: false` сохраняет существующий пароль; `true` сохраняет штатную семантику ротации Kolla. На этапе назначения исключений существующим сервисам использовать `false`, если ротация не нужна.

Парольные задачи принудительно используют `no_log: true`. Vault references разрешаются существующим `kolla_toolbox`; CA и client certificate/key передаются штатным интерфейсом коллекции. Новая автоматизация не получает или не сохраняет plaintext-секреты на deploy-узле сверх существующего процесса.

При первом включении и после обновления helper не использовать целый Kolla `--check` как доказательство работоспособности: check mode не копирует новый модуль в toolbox. Отсутствующий модуль вызовет отказ, а ранее размещённый может быть устаревшим. Сначала выполнить обычное размещение/регистрацию в согласованном окне, затем проверять dry run. Сам актуальный helper в check mode выполняет только чтение Keystone, без создания/изменения пользователей.

Граница охвата: регистрационные записи Kolla и Magnum trustee. Учётные записи, которые приложения создают **во время работы** (например, Heat stack users или Magnum trust users), bootstrap и внешние скрипты не становятся exempt автоматически. Для них producer должен передавать те же защищённые options в исходном запросе и иметь явно разрешённую policy. Уже существующие записи включить в инвентаризацию. Если такие producers используются и не доработаны, считать требование полного исключения для них выполненным нельзя.

## 8. Включение человеческой политики

Порядок для действующего кластера:

1. Сделать резервную копию конфигурации, policy и options; составить список всех технических identities, включая deployment/backup/monitoring и динамические producer paths.
2. Собрать/проверить образ, установить патчи Kolla. Человеческая политика пока выключена.
3. Обновить **все** Keystone workers новым образом и правилом policy. Подтвердить одинаковые digest, option registry и ответы API. Смешанная группа vanilla/patched workers не является поддержанным рабочим состоянием.
4. Явно назначить четыре options deployment identity и техническим пользователям вне регистрации Kolla.
5. Включить новый флаг Kolla. Выполнить регистрации реально используемых сервисов штатным `deploy`/`reconfigure`, проверить сохранённые options и успешную аутентификацию. Это операторское действие с возможным перезапуском контейнеров; в этой работе оно не запускалось.
6. Убедиться, что все сервисные пути покрыты. Только затем добавить следующий override и настройку Horizon.

`/etc/kolla/config/keystone.conf`:

```ini
[security_compliance]
password_regex = ^[!-~]{8,}\Z
password_regex_description = Use at least 8 printable ASCII characters without spaces.
change_password_upon_first_use = true
unique_last_password_count = 1
minimum_password_age = 0
lockout_failure_attempts = 4
lockout_duration = 900
```

Алфавит regex — 94 печатных ASCII-символа без пробела; пароль минимум 8 символов. Это не требование использовать все классы в каждом пароле. `900` секунд администратор меняет на нужный интервал. История `1` не позволяет завершить первую смену тем же временным паролем. Новая политика не заставляет уже существующих людей сменить пароль, пока администратор не установит им временный пароль.

`/etc/kolla/config/horizon/_9999-custom-settings.py`:

```python
ALLOW_USERS_CHANGE_EXPIRED_PASSWORD = True
HORIZON_CONFIG['password_validator'] = {
    'regex': '.*',
    'help_text': 'Требования к паролю проверяются сервером Keystone.',
}
```

Backend проверяет человеческую политику также при обходе Horizon и прямом обращении к API. Общий строгий regex Horizon мешал бы административной установке сервисных паролей.

В согласованное окно применить overrides штатным Kolla `reconfigure --tags keystone,horizon` с вашим inventory. Предварительно выполнить `prechecks`; учитывать регистрацию пользователей и bootstrap при reconfigure.

## 9. Приёмка и откат

На тестовом контуре проверить человека: запрет короткого/недопустимого пароля при создании, сбросе и самосмене; обязательную первую смену через Horizon; отказ повторить временный пароль; блокировку после четвёртого неверного пароля; вход после таймера и после административного `openstack user set --enable USER_UUID`.

Для тестовой сервисной записи проверить непустой пароль вне regex во всех трёх путях, повтор пароля, отсутствие first-use/expiry/lockout, сохранение options после повторной регистрации и ротации. У обычного и доменного администратора без нового права попытки включить/снять исключение должны завершаться отказом. Отзыв исключения с одновременным коротким паролем должен отклоняться.

Проверить несколько Keystone workers и конкурентные входы отдельно. Наличие значения `4` в конфигурации не доказывает строгий порог при гонках. Этот патч не переделывает алгоритм счётчика неудачных аутентификаций. Существующие токены/сессии также не заменяются блокировкой новых парольных входов.

Для отката сначала отключить человеческую политику на всех workers, затем вернуть штатную регистрацию Kolla и прежние образы. Возврат vanilla с включённым глобальным regex опять распространит его на сервисы. Сохранить options/export до отката. Уже записанное истечение временного пароля не отменяется одним удалением строки конфигурации — использовать штатную смену/сброс после корректировки политики.

Подробные варианты: [SQL](https://github.com/lebtmalorny-rgb/mimaric/blob/docs/all-markdown/OPENSTACK_PASSWORD_POLICY_LOCAL_SQL.md), [LDAP AD/FreeIPA](https://github.com/lebtmalorny-rgb/mimaric/blob/docs/all-markdown/OPENSTACK_PASSWORD_POLICY_LDAP_AD_FREEIPA.md). В вашей схеме «люди в LDAP, сервисы в SQL» патч нужен только при включении человеческой политики также для локальных SQL identities.
