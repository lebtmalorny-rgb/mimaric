# Установка OpenStack PowerOps

## Краткий вывод

Комплект содержит 36 Git-патчей: 10 для Masakari, 1 для mistral-lib, 16 для
Mistral, 1 для Kolla и 8 для Kolla-Ansible Epoxy 2025.1. Применяйте серии
именно в порядке Masakari → mistral-lib → Mistral → Kolla → Kolla-Ansible.
Чистый Horizon `stable/2025.1` не патчится: `powerops-dashboard` поставляется
как отдельный пакет.

Локальный Kolla recipe собирает Horizon, Mistral API, Mistral Engine и
Mistral Executor с тегом `2025.1-powerops`. Для полного backend deployment
дополнительно нужен отдельно собранный патченный Masakari Engine из этой же
поставки. Mistral Event Engine может остаться vanilla.

Установка исходников и образов сама по себе не разрешает live-операции.
`kolla-ansible prechecks` — обязательная проверка, а последующий `deploy` либо
`reconfigure` — отдельный явный gate изменения инфраструктуры. Эти команды
настраивают контейнеры, populate/reconcile/validate каталога Mistral, но путь
деплоя не запускает workflow и не выполняет power, Nova migration/evacuation
или VM start/stop. Первый workflow и тем более аварийный canary требуют
отдельного разрешения оператора.

После установки Kolla-серии архитектура и сценарии находятся в
`$KOLLA_SRC/docs/powerops/POWEROPS-ARCHITECTURE.md`; исходный документ входит
в [патч Kolla 0005](patches/kolla-ansible/0005-docs-add-Russian-PowerOps-operations-guide.patch).
Повседневный контроль, диагностика и runtime-приёмка описаны в
[`OPERATIONS.md`](OPERATIONS.md). Доказательства поставки — в
[`DELIVERY.md`](DELIVERY.md). Эксплуатация через Horizon описана отдельно в
[`POWEROPS_HORIZON_OPERATIONS.md`](POWEROPS_HORIZON_OPERATIONS.md).

## Проверка комплекта

Скопируйте каталог поставки на узел подготовки исходников и задайте только
локальные пути:

```bash
export POWEROPS_BUNDLE=/path/to/powerops-patches
export MASAKARI_SRC=/path/to/masakari
export MISTRAL_LIB_SRC=/path/to/mistral-lib
export MISTRAL_SRC=/path/to/mistral
export KOLLA_BUILD_SRC=/path/to/kolla
export KOLLA_SRC=/path/to/kolla-ansible-enroll-ironic-patch-3
cd "$POWEROPS_BUNDLE"
shasum -a 256 -c SHA256SUMS
POWEROPS_PATCH_COUNT="$(find patches -type f -name '*.patch' | wc -l | tr -d ' ')"
test "$POWEROPS_PATCH_COUNT" -eq 36
find patches -type f -name '*.patch' | sort
```

Ожидаются 36 строк `OK` и ровно 36 patch-файлов. До применения сохраните
вывод `git status --short`, `git branch --show-current`, `git rev-parse HEAD`
для каждого исходного репозитория. Рабочие деревья должны быть чистыми.
Не продолжайте при несовпадении SHA, baseline или количестве файлов.

Проверенные исходные точки и результаты серий:

| Проект | Baseline | Проверенный final tree |
|---|---|---|
| Horizon (для совместимости плагина) | `039850556d0516e52b94b28f95762f310d779f16` | `c50ffa875d2271700f8c2b24f8d7f71a6e01c395` |
| Masakari | `0fd34dd6a6d90525dbf806f35577c5ee1d7e9444` | `83bb2fd7a2d8c2f8d97e26c12fb66e8e06436bc5` |
| mistral-lib | `693174dd0aac1da22870b31e4a2481c4e749916a` | `cf20c15a39516272faf2ddfd69a74644fdc105c5` |
| Mistral | `3b2eab29e9dc71a5ba250d989155eb69a9bd8e48` | `9f9dee83d0e7146ce3d2011bc2169f0834e94ae4` |
| Kolla | `d14cef9bbafa0db561abfb0c0299d1d6bbbf8f0c` | `aba086df9f5a1e17f74eb5a67286fa00b805bb6b` |
| Kolla-Ansible | `703b06c9fa5771c758f703b424d63fb04192567a` | `0870059ba6ea82621002286e679bb93fbf719733` |

Для Kolla-Ansible авторитетен точный локальный imported baseline commit и
final tree. Commit, который создаётся повторным импортом стороннего архива,
может отличаться из-за Git metadata и не заменяет этот baseline.

## Подготовка исходных репозиториев

Используйте отдельные integration-ветки. Не применяйте серию поверх рабочей
ветки с локальными изменениями и не переписывайте существующие ветки.

Masakari:

```bash
cd "$MASAKARI_SRC"
test -z "$(git status --porcelain)"
test "$(git rev-parse HEAD)" = 0fd34dd6a6d90525dbf806f35577c5ee1d7e9444
git switch -c integration/powerops-masakari-2025.1
```

mistral-lib:

```bash
cd "$MISTRAL_LIB_SRC"
test -z "$(git status --porcelain)"
test "$(git rev-parse HEAD)" = 693174dd0aac1da22870b31e4a2481c4e749916a
git switch -c integration/powerops-mistral-lib-2025.1
```

Mistral:

```bash
cd "$MISTRAL_SRC"
test -z "$(git status --porcelain)"
test "$(git rev-parse HEAD)" = 3b2eab29e9dc71a5ba250d989155eb69a9bd8e48
git switch -c integration/powerops-mistral-2025.1
```

Kolla:

```bash
cd "$KOLLA_BUILD_SRC"
test -z "$(git status --porcelain)"
test "$(git rev-parse HEAD)" = d14cef9bbafa0db561abfb0c0299d1d6bbbf8f0c
git switch -c integration/powerops-kolla-build-2025.1
```

Для Kolla сначала проверьте ZIP и распакуйте его в новый каталог. Не
публикуйте временный baseline: он содержит исходный runtime log, который
удаляет первый патч.

```bash
cd /path/to/archive-directory
shasum -a 256 kolla-ansible-enroll-ironic-patch-3.zip
unzip -q kolla-ansible-enroll-ironic-patch-3.zip -d /path/to/new-kolla-import
export KOLLA_SRC=/path/to/new-kolla-import/kolla-ansible-enroll-ironic-patch-3
cd "$KOLLA_SRC"
git init
git add .
git add -f ansible.log
git commit -m "chore: import kolla-ansible-enroll-ironic-patch-3"
git switch -c integration/powerops-kolla-2025.1
```

Перед `git add` локально проверьте, что в `etc/kolla/passwords.yml`,
`ansible.log` и backup/reject-файлах нет ваших production-секретов. Если они
есть, остановитесь: такой архив не соответствует проверенному baseline и его
нельзя помещать в Git.

## Установка патчей Masakari

На чистой Masakari integration-ветке выполните одну mailbox-транзакцию:

```bash
cd "$MASAKARI_SRC"
git am \
  "$POWEROPS_BUNDLE/patches/masakari/0001-feat-add-PowerOps-coordination-primitives.patch" \
  "$POWEROPS_BUNDLE/patches/masakari/0002-feat-fence-failed-hosts-through-Ironic.patch" \
  "$POWEROPS_BUNDLE/patches/masakari/0003-fix-enforce-Ironic-fencing-deadlines.patch" \
  "$POWEROPS_BUNDLE/patches/masakari/0004-fix-honor-service-TLS-for-Ironic.patch" \
  "$POWEROPS_BUNDLE/patches/masakari/0005-feat-lock-complete-Masakari-host-recovery.patch" \
  "$POWEROPS_BUNDLE/patches/masakari/0006-test-harden-Masakari-host-lock-coverage.patch" \
  "$POWEROPS_BUNDLE/patches/masakari/0007-feat-serialize-Masakari-evacuations-through-etcd.patch" \
  "$POWEROPS_BUNDLE/patches/masakari/0008-docs-describe-Masakari-PowerOps-fencing.patch" \
  "$POWEROPS_BUNDLE/patches/masakari/0009-fix-satisfy-PowerOps-package-lint.patch" \
  "$POWEROPS_BUNDLE/patches/masakari/0010-fix-fail-closed-on-PowerOps-coordination-loss.patch"
git log --oneline --reverse 0fd34dd6a6d90525dbf806f35577c5ee1d7e9444..HEAD
git diff --check 0fd34dd6a6d90525dbf806f35577c5ee1d7e9444..HEAD
```

Если `git am` остановился, не разрешайте конфликт наугад. Сохраните диагностику
`git status` и `git am --show-current-patch=diff`, затем верните ветку в
доподготовленное состояние командой `git am --abort`. Устраните причину в
новой чистой ветке от точного baseline и повторите всю серию.

## Установка патча mistral-lib

Патч добавляет в доверенный action context `user_id`, защитную копию `roles`
и server-created resume authorization, сохраняя legacy positional contract.
Он должен быть установлен в Mistral API, Engine и Executor вместе с
патченным Mistral.

```bash
cd "$MISTRAL_LIB_SRC"
git am \
  "$POWEROPS_BUNDLE/patches/mistral-lib/0001-feat-carry-PowerOps-identity-in-action-context.patch"
git log --oneline --reverse 693174dd0aac1da22870b31e4a2481c4e749916a..HEAD
git diff --check 693174dd0aac1da22870b31e4a2481c4e749916a..HEAD
```

При конфликте сохраните диагностику и выполните `git am --abort`; не
переносите поля identity вручную в непроверенную версию библиотеки.

## Установка патчей Mistral

Mistral 0010 — обязательная security-зависимость reconcile. При PUT
он обновляет `Workbook`, а также его дочерние `ActionDefinition` и
`WorkflowDefinition` только по точному project/name/normalized namespace,
передавая детям `project_id=wb_db.project_id`, в one SQLAlchemy transaction.
Без него Kolla-Ansible 0004 применять для включённого reconcile нельзя:
межпроектная коллизия и TOCTOU должны закрываться и на уровне API.

```bash
cd "$MISTRAL_SRC"
git am \
  "$POWEROPS_BUNDLE/patches/mistral/0001-feat-add-PowerOps-action-coordination.patch" \
  "$POWEROPS_BUNDLE/patches/mistral/0002-fix-declare-PowerOps-etcd-backend.patch" \
  "$POWEROPS_BUNDLE/patches/mistral/0003-feat-add-PowerOps-OpenStack-primitives.patch" \
  "$POWEROPS_BUNDLE/patches/mistral/0004-fix-align-PowerOps-with-SDK-resources.patch" \
  "$POWEROPS_BUNDLE/patches/mistral/0005-feat-add-planned-PowerOps-actions.patch" \
  "$POWEROPS_BUNDLE/patches/mistral/0006-fix-harden-planned-action-boundaries.patch" \
  "$POWEROPS_BUNDLE/patches/mistral/0007-feat-add-guarded-host-return-actions.patch" \
  "$POWEROPS_BUNDLE/patches/mistral/0008-feat-register-the-PowerOps-workbook-API.patch" \
  "$POWEROPS_BUNDLE/patches/mistral/0009-test-generalize-action-plugin-coverage.patch" \
  "$POWEROPS_BUNDLE/patches/mistral/0010-fix-scope-workbook-updates-to-request-project.patch" \
  "$POWEROPS_BUNDLE/patches/mistral/0011-feat-propagate-trusted-PowerOps-action-identity.patch" \
  "$POWEROPS_BUNDLE/patches/mistral/0012-feat-define-PowerOps-role-authorization.patch" \
  "$POWEROPS_BUNDLE/patches/mistral/0013-feat-reject-unauthorized-PowerOps-starts.patch" \
  "$POWEROPS_BUNDLE/patches/mistral/0014-feat-reauthorize-PowerOps-workflow-resume.patch" \
  "$POWEROPS_BUNDLE/patches/mistral/0015-feat-enforce-PowerOps-roles-and-hard-off-policy.patch" \
  "$POWEROPS_BUNDLE/patches/mistral/0016-feat-expose-read-only-PowerOps-host-inventory.patch"
git log --oneline --reverse 3b2eab29e9dc71a5ba250d989155eb69a9bd8e48..HEAD
git diff --check 3b2eab29e9dc71a5ba250d989155eb69a9bd8e48..HEAD
```

При конфликте используйте тот же безопасный цикл: зафиксировать диагностику,
`git am --abort`, проверить baseline и повторить в новой integration-ветке.

## Установка патча Kolla

Патч добавляет opt-in local sources для standalone Horizon-плагина и
mistral-lib и активирует enabled-файл только при `ENABLE_POWEROPS=yes`.

```bash
cd "$KOLLA_BUILD_SRC"
git am \
  "$POWEROPS_BUNDLE/patches/kolla/0001-feat-package-PowerOps-Horizon-and-Mistral-components.patch"
git log --oneline --reverse d14cef9bbafa0db561abfb0c0299d1d6bbbf8f0c..HEAD
git diff --check d14cef9bbafa0db561abfb0c0299d1d6bbbf8f0c..HEAD
```

## Установка патчей Kolla-Ansible

Восемь патчей рассчитаны на точный imported baseline. Первый патч удаляет
runtime/backup/reject-артефакты и восстанавливает `no_log: true`. Четвёртый
патч зависит от уже включённого в Mistral патча 0010.

```bash
cd "$KOLLA_SRC"
git am \
  "$POWEROPS_BUNDLE/patches/kolla-ansible/0001-fix-sanitize-Ironic-enrollment-baseline.patch" \
  "$POWEROPS_BUNDLE/patches/kolla-ansible/0002-feat-define-Kolla-PowerOps-deployment-contract.patch" \
  "$POWEROPS_BUNDLE/patches/kolla-ansible/0003-feat-render-etcd-backed-PowerOps-configuration.patch" \
  "$POWEROPS_BUNDLE/patches/kolla-ansible/0004-feat-reconcile-PowerOps-actions-and-workbook.patch" \
  "$POWEROPS_BUNDLE/patches/kolla-ansible/0005-docs-add-Russian-PowerOps-operations-guide.patch" \
  "$POWEROPS_BUNDLE/patches/kolla-ansible/0006-fix-load-Masakari-through-idempotent-WSGI-wrapper.patch" \
  "$POWEROPS_BUNDLE/patches/kolla-ansible/0007-feat-configure-Horizon-PowerOps-RBAC-and-image.patch" \
  "$POWEROPS_BUNDLE/patches/kolla-ansible/0008-feat-validate-Horizon-PowerOps-runtime-contract.patch"
test ! -e ansible.log
git log --oneline -8
git diff --check HEAD~8..HEAD
```

Шестой патч доставляет в `masakari_api` файл
`/etc/masakari/masakari-api.wsgi` и направляет Apache на модульный WSGI entry
point `masakari.wsgi.api.application`. Он устраняет запуск legacy-скрипта,
который повторно разбирает уже обработанные аргументы и завершается с
`ArgsAlreadyParsedError`. Патч не поднимает Consul и не меняет
`masakari-hostmonitor`: это отдельный контур диагностики.

Если удаление `ansible.log` не применяется, это означает, что исходный архив
или импорт отличается от baseline. Не редактируйте patch: выполните
`git am --abort`, удалите только созданный integration-каталог после сохранения
нужной диагностики и повторите импорт из ZIP с проверенным SHA-256.

## Требования к сборке образов

Bundle содержит secret-free local recipe `build/kolla-build.conf`. После
применения Kolla patch он выбирает standalone plugin, local `mistral-base` и
local mistral-lib. Команда локальной сборки (отдельный change gate) должна
выполняться из `$KOLLA_BUILD_SRC` с `--locals-base`, указывающим на корень
bundle:

```bash
kolla-build \
  --config-file "$POWEROPS_BUNDLE/build/kolla-build.conf" \
  --locals-base "$POWEROPS_BUNDLE" \
  '^(horizon|mistral-api|mistral-engine|mistral-executor)$'
```

Она должна получить ровно четыре новых локальных образа:

1. `powerops-local/horizon:2025.1-powerops` с `powerops-dashboard`;
2. `powerops-local/mistral-api:2025.1-powerops`;
3. `powerops-local/mistral-engine:2025.1-powerops`;
4. `powerops-local/mistral-executor:2025.1-powerops`.

Для локального патченного fork Kolla читает точную строку
`mistral-lib===3.3.1` из активного upper-constraints 2025.1, исключает её из
обычной установки plugin requirements и устанавливает local source с
`PBR_VERSION=3.3.1+powerops.1`. Если точная constraint не найдена, сборка
останавливается fail-closed. После сборки обязательно выполните `pip check` и
загрузку всех шести `powerops.*` entry points отдельно в `mistral_api`,
`mistral_engine` и `mistral_executor`.

Отдельно для полного PowerOps deployment по-прежнему требуется патченный
Masakari Engine из финального Masakari-дерева; этот local recipe его не
собирает. Перенесите оба набора исходников в доверенный image pipeline вашей
организации с принятыми constraints, SBOM, scanning, подписью и immutable
tags.

Masakari API и Mistral Event Engine не исполняют добавленный код и могут
остаться vanilla. Pipeline должен подтвердить, что Masakari Engine содержит
entry point `ironic_fence` группы `masakari.task_flow.tasks`, Horizon — пакет
`powerops-dashboard`, а каждый из Mistral API/Engine/Executor содержит шесть
`powerops.*` entry points группы
`mistral.actions`. Проверка выполняется чтением `importlib.metadata` внутри
собранного артефакта; она не должна обращаться к OpenStack API, etcd или BMC.

После запуска контейнеров Kolla повторяет read-only acceptance check metadata
раздельно в `masakari_engine`, `mistral_api`, `mistral_engine` и
`mistral_executor`. Нельзя использовать один успешный Mistral-контейнер как
доказательство содержимого остальных двух.

## Настройка globals.yml

Ниже — пример без реальных адресов и секретов. Имена image repository и tag
демонстрационные; замените их immutable-ссылками из вашего registry. Не
копируйте credentials в `globals.yml`.

```yaml
enable_ironic: "yes"
enable_masakari: "yes"
enable_mistral: "yes"
enable_horizon: "yes"
enable_etcd: "yes"
enable_powerops: "yes"
openstack_region_name: RegionOne

powerops_coordination_url: >-
  etcd3+{{ internal_protocol }}://{{ kolla_internal_fqdn }}:{{ etcd_client_port }}?api_version=v3{% if openstack_cacert %}&ca_cert={{ openstack_cacert }}{% endif %}

powerops_masakari_engine_image: "registry.example.invalid/openstack/masakari-engine"
powerops_masakari_engine_tag: "epoxy-powerops-immutable"
powerops_mistral_api_image: "registry.example.invalid/openstack/mistral-api"
powerops_mistral_api_tag: "epoxy-powerops-immutable"
powerops_mistral_engine_image: "registry.example.invalid/openstack/mistral-engine"
powerops_mistral_engine_tag: "epoxy-powerops-immutable"
powerops_mistral_executor_image: "registry.example.invalid/openstack/mistral-executor"
powerops_mistral_executor_tag: "epoxy-powerops-immutable"
powerops_horizon_image: "powerops-local/horizon"
powerops_horizon_tag: "2025.1-powerops"

powerops_allowed_project_names:
  - powerops-operators
powerops_allowed_user_names:
  - svc-powerops

powerops_host_lock_timeout: 30
powerops_evacuation_lock_timeout: 3600
powerops_evacuation_interval: 5
powerops_power_timeout: 180
powerops_poll_interval: 5
powerops_stable_observations: 3
powerops_graceful_shutdown_timeout: 300
powerops_vm_action_timeout: 600
powerops_service_timeout: 300
powerops_instance_interval: 5
powerops_reconcile_workbook: "yes"
powerops_validate_registration: "yes"

kolla_admin_openrc_cacert: "/etc/kolla/controller-ca.pem"
```

### Включение компонентов

| Параметр | Назначение |
|---|---|
| `enable_ironic` | Включает Ironic, который PowerOps использует только как источник соответствия compute host → BMC и как backend физического питания. Узлы остаются `manageable` с `network_interface=noop`; этот сценарий не включает provisioning, cleaning или `nova-compute-ironic`. |
| `enable_masakari` | Включает Masakari. В PowerOps он обрабатывает аварийный отказ хоста: отключает `nova-compute`, выполняет fencing через Ironic и только после стабильного `power off` последовательно эвакуирует ВМ. |
| `enable_mistral` | Включает Mistral для плановых `status`, `power off`, `reboot` и двухфазного возврата хоста. Аварийный fencing Masakari от Mistral не зависит. |
| `enable_horizon` | Включает Horizon. PowerOps-плагин активируется только когда одновременно включены Horizon, Mistral и PowerOps. |
| `enable_etcd` | Включает etcd, используемый через tooz как общий backend распределённых блокировок Masakari и Mistral. |
| `enable_powerops` | Активирует PowerOps-конфигурацию, выбор четырёх патченных образов, изменённый Masakari recovery flow и Mistral reconcile/validation. Значение `yes` само по себе не запускает workflow, power action, migration или evacuation. По умолчанию PowerOps выключен. |
| `openstack_region_name` | Единственный регион этой инсталляции PowerOps. Horizon показывает его и блокирует вызов, если выбранный пользователем регион не совпадает. |

### Координация, fencing и последовательность операций

Все значения времени ниже задаются в секундах. Увеличение timeout не ускоряет
операцию, а только расширяет максимально допустимое ожидание. Слишком малые
значения дают ложные timeout на медленном BMC или Nova; слишком большие
удлиняют fail-closed остановку и реакцию оператора.

| Параметр | Назначение и область действия |
|---|---|
| `powerops_coordination_url` | Общий tooz URL для Masakari и Mistral. В активной конфигурации ожидается `etcd3+http[s]://...?...api_version=v3`; оба сервиса должны обращаться к одному логическому etcd-кластеру. Потеря coordination/ownership останавливает последующие мутации fail-closed. Redis может оставаться у других сервисов, но не является backend включённого PowerOps. |
| `powerops_host_lock_timeout` | Максимальное ожидание host lock `powerops/host/<host>`. Один namespace используется плановыми Mistral и аварийными Masakari операциями, поэтому они не могут одновременно изменять один хост. Значение по умолчанию — 30. |
| `powerops_evacuation_lock_timeout` | Максимальное ожидание Masakari global lock `powerops/evacuation/global` перед evacuation конкретной ВМ. Lock удерживается на время evacuation, подтверждения результата и pacing; значение по умолчанию — 3600. |
| `powerops_evacuation_interval` | Пауза между последовательными Masakari evacuation, уменьшающая нагрузку на Nova, scheduler, storage и network. Значение по умолчанию — 5; `0` убирает только паузу, но не глобальную сериализацию. |
| `powerops_power_timeout` | Общий deadline физического hard power transition и подтверждения стабильного состояния через Ironic. Используется аварийным fencing и плановыми hard-off/power-on проверками; значение по умолчанию — 180. |
| `powerops_poll_interval` | Интервал между чтениями состояния Ironic, Nova или Masakari во время ожидания перехода. Значение по умолчанию — 5. |
| `powerops_stable_observations` | Число последовательных допустимых наблюдений, необходимых для признания состояния стабильным. Mistral применяет его к питанию и длительным service/maintenance-переходам; в Masakari параметр рендерится как `stable_off_observations` для fencing. Минимум — 2, значение по умолчанию — 3. |
| `powerops_graceful_shutdown_timeout` | Deadline планового `soft power off` через Ironic. По умолчанию — 300. Переход к hard-off возможен только если workflow явно получил `allow_hard_off: true`; timeout самого API-вызова не запускает вторую мутацию автоматически. |
| `powerops_vm_action_timeout` | Deadline одной плановой операции Nova над ВМ и подтверждения её результата: stop, live migration или start. Это не timeout всего списка; каждая ВМ обрабатывается отдельно. Значение по умолчанию — 600. |
| `powerops_service_timeout` | Deadline поиска и изменения согласованного набора Ironic Node, `nova-compute` и Masakari host, включая подтверждение Nova enabled/disabled/up и maintenance. Значение по умолчанию — 300. |
| `powerops_instance_interval` | Пауза между последовательными плановыми операциями над ВМ в Mistral. Она предотвращает шторм stop/migration/start; значение по умолчанию — 5, `0` отключает паузу, но сохраняет последовательное выполнение. |

В шаблоне `powerops_coordination_url` используются обычные переменные Kolla:
`internal_protocol` выбирает `http` или `https`, `kolla_internal_fqdn`
указывает внутренний VIP/FQDN, `etcd_client_port` — клиентский порт etcd, а
непустой `openstack_cacert` добавляет container-visible CA через параметр
`ca_cert`. Не подменяйте их произвольным адресом одного etcd member: все
экземпляры Masakari и Mistral должны получать один отказоустойчивый endpoint.

### Патченные runtime-образы

| Параметр | Назначение |
|---|---|
| `powerops_masakari_engine_image` | Repository патченного Masakari Engine. Masakari API остаётся на обычном образе. |
| `powerops_masakari_engine_tag` | Immutable tag или digest-compatible tag патченного Masakari Engine. Пустое значение блокируется precheck. |
| `powerops_mistral_api_image` | Repository патченного Mistral API, содержащего owner-scoped workbook API и PowerOps metadata. |
| `powerops_mistral_api_tag` | Immutable tag патченного Mistral API. |
| `powerops_mistral_engine_image` | Repository патченного Mistral Engine, исполняющего workflow orchestration и PowerOps actions. |
| `powerops_mistral_engine_tag` | Immutable tag патченного Mistral Engine. |
| `powerops_mistral_executor_image` | Repository патченного Mistral Executor, в котором должны быть установлены те же `powerops.*` action entry points. |
| `powerops_mistral_executor_tag` | Immutable tag патченного Mistral Executor. Mistral Event Engine этим параметром намеренно не заменяется. |
| `powerops_horizon_image` | Repository Horizon image с установленным standalone `powerops-dashboard`. |
| `powerops_horizon_tag` | Immutable tag Horizon PowerOps image; локальный recipe использует `2025.1-powerops`. |

Пары repository/tag обязательны и выбираются только при
`enable_powerops: "yes"`. Предпочтительны digest либо immutable tag, чтобы
повторный deploy не получил другие байты под прежним именем.

### Кто может запускать PowerOps

| Параметр | Назначение |
|---|---|
| `powerops_allowed_project_names` | Allowlist точных `project_name` из Keystone-scoped контекста вызвавшего Mistral execution. `powerops-operators` в примере — имя проекта Keystone, а не роль или группа. |
| `powerops_allowed_user_names` | Allowlist точных `user_name` из того же контекста. `svc-powerops` в примере — имя пользователя Keystone. |

Для `powerops_operator` action разрешается, только если имя проекта входит в
первый список **и** имя пользователя входит во второй — оба условия
одновременно. Например, `svc-powerops` в проекте `powerops-operators`
допускается, а тот же пользователь в другом проекте либо другой пользователь
в разрешённом проекте отклоняется с `PowerOpsUnauthorized` до cloud-мутаций.

Точная роль `admin` проверяется первой: admin разрешён в любом проекте и
обходит оба allowlist. Следовательно, списки относятся только к
powerops_operator. Если у пользователя есть обе роли, применяется admin-ветка.

Эти параметры не создают Keystone-проект, пользователя или роли и не заменяют
Keystone RBAC/Mistral policy. Сущности и минимальные роли создаются отдельно.
Allowlist — дополнительный прикладной gate перед тем, как action воспользуется
сервисными credentials Mistral для обращения к Ironic, Nova и Masakari.
Самим service credentials Mistral не требуется человеческая роль
powerops_operator: человеческая авторизация доставляется отдельно в
доверенном action context.

Сопоставление выполняется по точному имени и регистрозависимо;
пустой список запрещает все вызовы. Kolla precheck не позволяет включить
PowerOps с пустым списком или элементами, содержащими запятые, пустую строку
либо пробелы по краям.
Если в каждом списке несколько элементов, разрешается любая комбинация
пользователя и проекта из этих двух списков: это два независимых множества,
а не список связанных пар.
Для наиболее узкого доступа используйте один выделенный project и одного
service user.

### Reconcile, validation и controller CA

| Параметр | Назначение |
|---|---|
| `powerops_reconcile_workbook` | При `yes` Kolla после запуска Mistral читает точный публичный workbook `power_ops`: создаёт его при отсутствии либо обновляет единственную принадлежащую token project запись при изменении. Чужая или неоднозначная запись блокирует reconcile. Workflow execution при этом не создаётся. |
| `powerops_validate_registration` | При `yes` Kolla после populate/reconcile read-only проверяет наличие точных шести actions и пяти workflows. Проверка валидирует каталог, но не проверяет реальный etcd lock, BMC или Nova operation. |
| `kolla_admin_openrc_cacert` | Путь к CA-файлу на Ansible control node для делегированных на `localhost` Keystone/Mistral API-вызовов reconcile и validation. Это не container path и не тот же контракт, что `openstack_cacert`. Файл должен быть обычным и читаемым. |

Если внутренние API используют TLS, `kolla_admin_openrc_cacert` проверяется
вручную до change gate и повторно внутри deploy/reconfigure. Не подставляйте
container-only путь. Если internal API действительно работает без TLS,
оставьте controller CA пустым согласно общему Kolla TLS-контракту; не
отключайте проверку сертификата для TLS.

## Prechecks и явный gate изменения

До мутации выполните обычные read-only/validation проверки вашей среды,
проверьте inventory limit и сохраните diff `globals.yml`. Затем отдельно
запустите prechecks принятой командой вашего Kolla checkout, например:

```bash
kolla-ansible prechecks -i /path/to/inventory
```

Prechecks должны подтвердить включённые Ironic, Masakari, Mistral и etcd,
непустые четыре image/tag пары и строгие allowlists. В текущем патче Kolla
prechecks не проверяет kolla_admin_openrc_cacert. Поэтому до operator gate
отдельно проверьте на Ansible control node точное непустое значение из
`globals.yml`; `test -f` следует по symlink и подтверждает обычный файл,
`test -r` — доступ на чтение:

```bash
POWEROPS_CONTROLLER_CA=/etc/kolla/controller-ca.pem
test -f "$POWEROPS_CONTROLLER_CA"
test -r "$POWEROPS_CONTROLLER_CA"
```

Если `kolla_admin_openrc_cacert` намеренно пуст для не-TLS internal API, этот
ручной блок пропускается. Для TLS путь в `POWEROPS_CONTROLLER_CA` должен точно
совпадать с `kolla_admin_openrc_cacert`; ошибка любой команды блокирует
продолжение.

Только после отдельного change approval выберите ровно один gate:
`kolla-ansible deploy` или `kolla-ansible reconfigure`; ниже команды включают
обязательный inventory конкретного облака.

```bash
kolla-ansible deploy -i /path/to/inventory
```

для нового развёртывания либо:

```bash
kolla-ansible reconfigure -i /path/to/inventory
```

для существующего облака. Не запускайте обе команды подряд автоматически.
Они перезапускают выбранные контейнеры и выполняют Mistral
populate/reconcile/validate, но не создают execution и не запускают операции
питания/Nova. Reconcile получает project-scoped Keystone token, перечисляет
точные `power_ops` workbook с пустым namespace и останавливается fail-closed
при нескольких либо чужих записях. POST выполняется только при отсутствии,
PUT — только для одной принадлежащей token project изменившейся записи.
Kolla также проверяет ровно один проектный workflow; Mistral
выполняет owner-scoped lookup/update `Workbook`, `ActionDefinition` и
`WorkflowDefinition` в одной SQLAlchemy-транзакции.

Kolla повторяет `stat`/`isreg`/`readable` проверку controller CA уже внутри
выбранного deploy/reconfigure, после meta: flush_handlers и Mistral action
population, но до Keystone token и Mistral reconcile. Поэтому эта встроенная
проверка не заменяет ручную проверку выше: при плохом пути контейнеры уже могли
быть перезапущены и actions populated до остановки playbook.

## Проверки после установки

Сначала проверьте только конфигурацию и каталог, не создавая workflow execution:

```bash
openstack action definition list
openstack workflow list
openstack baremetal node list --fields uuid name
openstack baremetal node show NODE_UUID --fields uuid name provision_state power_state target_power_state last_error network_interface
openstack compute service list --service nova-compute
openstack segment host list SEGMENT_UUID
```

Ожидаются шесть actions:
`powerops.host_inventory`, `powerops.host_power_status`,
`powerops.planned_power_off`,
`powerops.planned_reboot`, `powerops.power_on_for_inspection`,
`powerops.return_to_service`; и пять workflows:
`power_ops.host_inventory`, `power_ops.host_power_status`,
`power_ops.planned_power_off`,
`power_ops.planned_reboot`, `power_ops.power_on_and_return`.

Сначала по list проверьте единственность имени и возьмите точный `NODE_UUID`,
затем выполните show отдельно для каждого compute-host. По его выводу проверьте
точное равенство `Nova hostname = Masakari host.name = Ironic Node.name`,
`provision_state=manageable`, `network_interface=noop`, пустой `last_error` и
ожидаемый `power_state`/`target_power_state`. Эти команды дают point-in-time
снимок и не доказывают работу live etcd lease, BMC или Nova evacuation.

## Первый live canary

Первый canary — отдельное, явно авторизованное изменение с согласованным
maintenance window, наблюдением etcd, Nova, Masakari, Ironic/BMC и планом
возврата. Начните с выделенного непроизводственного compute host без ВМ и с
политики `require_empty`; не используйте аварийную notification как первый
тест. До запуска зафиксируйте точные host/segment UUID и фактическое состояние.

После каждого перехода перечитывайте Nova disabled/enabled, Masakari
maintenance, Ironic `power_state`/`target_power_state`/`last_error` и список
ВМ. Не повторяйте workflow автоматически при неопределённом результате. Live
canary, power action, evacuation и VM start/stop не разрешаются самим фактом
применения этих патчей.

Запись PowerOps audit — это только `structured LOG.info process log`.
Граница контракта: `no external durable audit store` и
`no delivery or persistence guarantee`. Оператор должен отдельно
настроить сбор, хранение и доставку process-логов, если это
требуется политикой аудита.

## Возобновление workflow возврата

`power_ops.power_on_and_return` после первой фазы стоит на
`operator_inspection_gate`. Оператор обязан проверить ОС, libvirt, storage,
network и отсутствие stale domains. Затем execution возобновляется запросом
`PUT /v2/executions/<execution_id>` с точным JSON:

```json
{
  "state": "RUNNING",
  "params": {
    "env": {
      "stale_domains_checked": true
    }
  }
}
```

`true` — JSON Boolean, не строка. Не используйте resume до фактической
проверки: вторая фаза последовательно запускает только UUID из переданного
`stopped_instance_ids`, затем включает Nova и снимает maintenance.

## Откат

Откат планируется до deploy и выполняется через прежние известные исправные
source branches, immutable image tags и сохранённый `globals.yml`, а не через
разрушительное переписывание рабочей ветки.

- До deploy: при незавершённом применении используйте `git am --abort`. Если
  серия уже применена, оставьте integration-ветку как доказательство и создайте
  новую ветку от baseline; не удаляйте общую исходную историю.
- После сборки, но до deploy: не публикуйте теги как production-approved;
  исправьте исходную ветку и повторите pipeline.
- После deploy: сначала запретите новые PowerOps executions организационным
  change gate, дождитесь завершения/разбора активных execution и аварийных
  notifications, зафиксируйте фактические состояния. Затем верните четыре
  image/tag пары и PowerOps-настройки к сохранённому варианту через отдельный
  одобренный `reconfigure`.
- `enable_powerops: "no"` прекращает рендеринг активного PowerOps-контракта при
  следующем одобренном reconfigure, но само изменение файла ничего не меняет.
- Kolla rollback не удаляет публичный workbook автоматически. Сначала
  исключите его использование политикой доступа. Удаление/изменение workbook
  — отдельная API-мутация с резервной копией definition и отдельным
  разрешением; этот runbook её автоматически не выполняет.
- Не включайте аварийно fenced-хост и не делайте повторный power cycle как
  способ отката. Восстановление выполняется из прочитанного состояния по
  процедуре `power_on_and_return` и operator gate.

## Граница статической и live-проверки

Поставка проверена локально: патчи применяются к заявленным baseline, тесты и
source/delivery checks проходят в указанной границе, контракты компонентов
согласованы, hashes зафиксированы. Собраны и read-only проинспектированы четыре
локальных образа; `pip check` прошёл в каждом, а шесть `powerops.*` entry points
загружены отдельно во всех трёх Mistral-репликах. Mock UI проверен на шести
маршрутах, пакет собран как wheel и sdist. Образы не публиковались.

`deploy`/`reconfigure` не выполнялись; реальные Keystone/Mistral API,
etcd lease/heartbeat, Ironic/Redfish/BMC, Nova migration/evacuation и
последовательный VM start/stop не проверялись. Эти проверки остаются отдельной
live-приёмкой под контролем оператора.
