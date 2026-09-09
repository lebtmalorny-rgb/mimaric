# Horizon PowerOps: руководство эксплуатации

## Назначение и границы

Плагин `powerops-dashboard` даёт оператору Horizon безопасный интерфейс к
плановым операциям над compute host. Единственный изменяющий путь:

```text
Horizon -> Mistral -> PowerOps actions -> Nova/Masakari/Ironic
```

Horizon использует Keystone token текущего пользователя только для обращения
к региональному Mistral API. Плагин не содержит Nova, Masakari, Ironic,
Redfish/BMC или etcd mutation client и не принимает имя workflow от браузера.
Одна инсталляция PowerOps обслуживает один `openstack_region_name`; Horizon
может показывать выбор региона, но PowerOps принимает только настроенный
регион и блокирует несовпадение.

Показанные в UI состояние и список ВМ — снимок. Перед любой мутацией backend
повторяет авторизацию, сопоставление host, список ВМ и состояние уже под общим
lock `powerops/host/<host>`. Timeout или неопределённый ответ нельзя считать
успехом либо основанием для автоматического повтора.

## Роли admin и powerops_operator

Доступ разрешён по формуле:

```text
admin OR
(powerops_operator AND project_name в allowlist AND user_name в allowlist)
```

Роль `admin` проверяется первой: **admin работает в любом проекте** и
**обходит оба allowlist**. Поэтому проектная роль `admin`, назначенная
пользователю в любом Keystone project, даёт этому scoped token доступ к
PowerOps и управлению всем compute host, включая ВМ других проектов. Это
осознанный административный контракт; ограничивать его allowlist нельзя.

Для роли `powerops_operator` оба точных, регистрозависимых совпадения
обязательны: списки применяются только к powerops_operator. Пользователь с
обеими ролями всегда идёт по ветке `admin`.

Служебный проект не является особым типом Keystone project. Это обычный
выделенный проект, созданный для изоляции операторских назначений и токенов;
он не является «дочерним» основного проекта и не ограничивает набор ВМ,
затрагиваемых host-wide операцией. При принятом режиме, где питанием управляет
администратор, отдельный служебный проект и назначение `powerops_operator`
человеку не обязательны.

Mistral service credentials используются самим backend для Nova, Masakari и
Ironic и **не требуют человеческой роли powerops_operator**. Нельзя назначать
сервисному пользователю эту роль только ради выполнения action: право человека
передаётся в доверенном action context отдельно от service credentials.

## Настройка project/user allowlist

В `globals.yml` задаются два независимых множества точных имён:

```yaml
powerops_allowed_project_names:
  - powerops-operators
powerops_allowed_user_names:
  - svc-powerops
```

Разрешена любая комбинация имени из первого и имени из второго списка. Для
узкой делегации используйте по одному значению. Эти параметры ограничивают
только `powerops_operator`; они не создают Keystone objects и не влияют на
ветку `admin`.

Kolla-Ansible создаёт объект роли `powerops_operator`, когда PowerOps включён,
но намеренно не назначает её пользователям. Если делегированный оператор
нужен, выберите значения сами и выполните под отдельным change approval:

```bash
POWEROPS_PROJECT_NAME=powerops-operators
POWEROPS_USER_NAME=svc-powerops
openstack role create --or-show powerops_operator
openstack role add \
  --project "$POWEROPS_PROJECT_NAME" \
  --user "$POWEROPS_USER_NAME" \
  powerops_operator
openstack role assignment list \
  --project "$POWEROPS_PROJECT_NAME" \
  --user "$POWEROPS_USER_NAME" \
  --names
```

Последняя команда — read-only проверка. Первые две изменяют Keystone и требуют
обычного согласования вашей организации.

## Установка и включение Horizon-плагина

Примените 36 патчей в порядке из `INSTALL.md`: Masakari, mistral-lib,
Mistral, Kolla, Kolla-Ansible. `powerops-dashboard` остаётся отдельным Python
пакетом; чистое дерево Horizon `stable/2025.1` не патчится.

Локальный Kolla recipe находится в `build/kolla-build.conf` и выбирает
`powerops-dashboard`, патченный `mistral-base` и патченный `mistral-lib`.
Целевые теги:

```text
powerops-local/horizon:2025.1-powerops
powerops-local/mistral-api:2025.1-powerops
powerops-local/mistral-engine:2025.1-powerops
powerops-local/mistral-executor:2025.1-powerops
```

Для Kolla-Ansible задайте `enable_horizon`, `enable_mistral` и
`enable_powerops` в `yes`, точные `powerops_horizon_image`/tag и остальные
патченные image/tag пары. `enable_horizon_powerops` вычисляется автоматически
как пересечение этих трёх флагов. В контейнер передаётся `ENABLE_POWEROPS=yes`,
и `extend_start.sh` активирует `_50_powerops.py` до collectstatic.

Для атомарной защиты от двойного POST Horizon обязан использовать общий
Memcached: cache-backed `SESSION_ENGINE`, backend
`django.core.cache.backends.memcached.PyMemcacheCache` и полный список
развёрнутых endpoints. Precheck и read-only post-deploy check отклоняют
database/LocMem/Dummy cache и поздние неверные custom overrides.

Сборка образов, `deploy` и `reconfigure` — разные change gates. Наличие
исходников или успешных unit tests не разрешает запуск любой из этих операций.

## Проверка Masakari WSGI и API

Kolla-Ansible patch `0006` устанавливает
`/etc/masakari/masakari-api.wsgi`, импортирующий
`masakari.wsgi.api.application`, и направляет Apache `WSGIScriptAlias` на
этот файл. После отдельно одобренного deployment проверьте конфигурацию и API
только чтением:

```bash
docker exec masakari_api test -r /etc/masakari/masakari-api.wsgi
docker exec masakari_api grep -F \
  /etc/masakari/masakari-api.wsgi \
  /etc/apache2/conf-enabled/masakari-api.conf
openstack segment list
```

Дополнительно проверьте ответы корня Masakari API и `/v1` вашим штатным
healthcheck. В логах не должно быть `ArgsAlreadyParsedError`. Эти проверки не
создают notification, не запускают fencing и не доказывают BMC power path.

## Плановое выключение

В Horizon откройте `PowerOps -> Compute Hosts`, выберите operable host и
`Плановое выключение`. UI заново читает inventory, точный host status и
активные executions. Проверьте регион, `segment_uuid`, Nova/Masakari/Ironic
состояния и полный список затрагиваемых ВМ всех проектов.

Выберите policy, введите hostname байт-в-байт и подтвердите форму. Один
одноразовый token допускает максимум один вызов Mistral. Не нажимайте повторно
после timeout: сначала найдите execution и перечитайте его состояние.

## Плановая перезагрузка

Плановая перезагрузка использует только
`power_ops.planned_reboot`. Для неё Horizon всегда отправляет
`allow_hard_off=false`, в том числе для `admin`; hard-off controls на этой
форме отсутствуют. Policy и impact list проверяются так же, как при
выключении.

## Включение и возврат в эксплуатацию

Возврат запускается только из успешного точного
`power_ops.planned_power_off`. Манифест `stopped_instance_ids` повторно
читается из результата source execution и не принимается из POST браузера.

Workflow `power_ops.power_on_and_return` сначала включает питание, ждёт
подтверждённое состояние и останавливается на `operator_inspection_gate`.
Перед resume оператор проверяет ОС, libvirt, storage, network и отсутствие
stale domains. Horizon допускает resume только для `PAUSED` execution с
единственной задачей `operator_inspection_gate` в `IDLE` и отправляет ровно:

```json
{"stale_domains_checked": true}
```

После resume backend последовательно запускает только ВМ из неизменённого
манифеста, включает Nova service и снимает Masakari maintenance.

## Политики require_empty, live_migrate и stop

- `require_empty` — разрешает операцию только при отсутствии ВМ на host;
- `live_migrate` — последовательно live-migrate всех обнаруженных ВМ и ждёт
  подтверждения каждой миграции;
- `stop` — последовательно останавливает ВМ и сохраняет точный UUID-манифест
  для контролируемого возврата.

Плановая evacuation отсутствует. Выбранная policy показывается рядом с каждой
ВМ до разблокировки submit; операция влияет на все проекты, а не только на
проект текущего Horizon token.

## Hard-off только для admin

Hard-off доступен только пользователю с точной ролью `admin` и только в форме
планового выключения. Требуются отдельные флаги разрешения и подтверждения.
`powerops_operator` не видит полей, а подделанный POST отклоняется. Mistral
повторно проверяет admin-ветку до разрешения `allow_hard_off=true`.

Hard-off не является автоматическим retry после неопределённого soft-off.
Сначала установите фактическое состояние Ironic/BMC; повторный power request
без этого запрещён операционной процедурой.

## Состояния Mistral execution

UI показывает `RUNNING`, `PAUSED`, `SUCCESS`, `ERROR` и `CANCELLED` вместе с
санитизированными task/action данными. `SUCCESS`, `ERROR` и `CANCELLED` —
terminal states, polling после них прекращается. Polling выполняет только GET.

`PAUSED` не означает автоматическую готовность к resume: применяются все
предикаты раздела возврата. Состояние, workflow name, host и `segment_uuid`
должны совпадать с ожидаемыми точно.

## Ошибки 403, 409, 422, 503 и неопределённый timeout

- `403` — текущий scoped пользователь не прошёл роль/allowlist;
- `409` — host занят, состояние изменилось, token уже использован или есть
  активная мутация;
- `422` — форма, mapping, inventory либо execution не прошли строгую
  проверку;
- `503` — обязательный backend недоступен либо ответ не удалось безопасно
  классифицировать.

При неопределённом timeout Horizon показывает `verification_required` и не
повторяет POST. Найдите execution через read-only list/show, сопоставьте actor,
workflow, host, segment и время. Только доказанное отсутствие принятой
мутации позволяет создать новый запрос с новым одноразовым token.

## Диагностика Nova, Masakari, Ironic и etcd lock

Сначала снимите состояние без мутаций:

```bash
HOST=compute-01
SEGMENT_UUID=11111111-1111-1111-1111-111111111111
openstack compute service list --host "$HOST"
openstack server list --all-projects --host "$HOST" --long
openstack segment host show "$SEGMENT_UUID" "$HOST"
openstack baremetal node list --fields uuid name
openstack workflow execution list
```

Требуется точное единственное сопоставление
`Nova hostname = Masakari host.name = Ironic Node.name`. Для Ironic проверьте
`provision_state`, `power_state`, `target_power_state`, `last_error` и
`network_interface`. Для coordination проверьте здоровье всех etcd endpoints,
lease/session и владельца `powerops/host/<host>` штатными read-only средствами.
Истечение lock timeout не доказывает, что внешняя операция не была принята.

## Разделение планового Mistral и аварийного Masakari

Mistral владеет только плановыми status/off/reboot/return workflow и общим
per-host lock. Masakari владеет аварийной notification, fencing через Ironic,
evacuation и глобальным `powerops/evacuation/global` lock.

Horizon не создаёт Masakari notification и не предлагает кнопок emergency
fencing/evacuation. Аварийно fenced host нельзя возвращать нажатием плановой
кнопки без отдельной диагностики и процедуры восстановления. Совпадающий
`powerops/host/<host>` сериализует плановую и аварийную ветви; потеря
coordination приводит к fail-closed, а не к продолжению мутации.

Локальные source tests, package build, mock UI и read-only image imports не
доказывают поведение развёрнутых сервисов, реальные Keystone assignments,
владение etcd lock, Nova VM transitions, Ironic/BMC power или Masakari
evacuation. Это отдельные этапы runtime-приёмки с явным разрешением.
