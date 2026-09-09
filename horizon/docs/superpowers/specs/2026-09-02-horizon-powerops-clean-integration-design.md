# Проект интеграции PowerOps с Horizon 2025.1

## Статус документа

Документ фиксирует согласованный новый дизайн интеграции PowerOps с Horizon.
Он заменяет в качестве актуальной спецификации документ
`2026-09-02-horizon-powerops-integration-design.md`, который сохраняется как
исторический материал. Старые незавершённые Horizon-ветки не являются
основанием для новой реализации.

Целевая версия интерфейса — чистый Horizon `stable/2025.1`. Существующие серии
патчей Masakari, Mistral и Kolla-Ansible используются только после повторного
применения к чистым upstream-деревьям и проверки контрактов.

## Цель

Добавить отдельный Horizon-плагин для безопасного планового управления
питанием compute-хостов:

- просмотр согласованного состояния хоста;
- плановое выключение;
- плановая перезагрузка;
- включение и контролируемый возврат хоста в эксплуатацию;
- наблюдение за выполнением операций;
- отображение состояния Masakari без ручного запуска аварийного recovery.

Плагин не реализует собственную state machine управления питанием. Все
изменяющие операции выполняются существующими PowerOps workflow и actions в
Mistral.

## Зафиксированные ограничения

- Одна OpenStack-инсталляция соответствует одному региону.
- Horizon может сохранять штатный селектор регионов, но в целевом развёртывании
  доступен один регион.
- Операция над compute-хостом инфраструктурная и затрагивает ВМ всех проектов.
- Текущий проект пользователя участвует в авторизации и владении Mistral
  execution, но не ограничивает множество ВМ на хосте.
- Masakari самостоятельно запускает аварийный fencing и evacuation по событиям.
- Horizon не предоставляет кнопку ручного запуска аварийного recovery.
- Horizon не обращается напрямую к BMC и не выполняет изменяющие вызовы Nova,
  Masakari или Ironic.
- Реальное развёртывание, изменение состояния ВМ и power-команды не входят в
  локальный этап реализации и требуют отдельного разрешения.

## Архитектура

```text
Browser
  -> powerops-dashboard (отдельный Horizon plugin)
       -> текущий Keystone token пользователя
       -> Mistral endpoint из service catalog для текущего региона
            -> проверка PowerOps RBAC
            -> PowerOps inventory/workflow/action
                 -> service credentials Mistral
                 -> Nova + Masakari + Ironic
                 -> etcd powerops/host/<host>
```

`powerops-dashboard` устанавливается отдельным Python-пакетом поверх чистого
Horizon `stable/2025.1`. Плагин создаёт верхнеуровневый раздел
`PowerOps -> Compute Hosts`. Он не размещается внутри штатного `Admin`
dashboard, потому что это закрыло бы доступ делегированному пользователю
`powerops_operator` либо потребовало бы открыть ему посторонние панели.

Стандартный `mistral-dashboard` может оставаться включённым независимо. Он не
считается интерфейсом PowerOps и не заменяет специализированные формы,
подтверждения и диагностику.

## Модель авторизации

### Итоговое правило

Mistral разрешает PowerOps-вызов, если выполняется одно из условий:

```text
role:admin
OR
(
  role:powerops_operator
  AND project_name in powerops_allowed_project_names
  AND user_name in powerops_allowed_user_names
)
```

Правила трактуются следующим образом:

- наличие `admin` в текущем Keystone-токене разрешает операцию независимо от
  проекта токена и обоих allowlist;
- `powerops_operator` требует точного совпадения и имени проекта, и имени
  пользователя;
- пользователь с обеими ролями проходит по ветке `admin`;
- все остальные пользователи получают отказ;
- `allow_hard_off=true` дополнительно требует ветку `admin`;
- роль `powerops_operator` предназначена для людей и не нужна сервисному
  пользователю Mistral.

Проверяются роли текущего project-scoped токена. Допустимо, что пользователь с
проектной ролью `admin` в любом проекте получает доступ к PowerOps.

### Значения Kolla по умолчанию

```yaml
powerops_allowed_project_names:
  - "{{ openstack_auth.project_name }}"

powerops_allowed_user_names:
  - "{{ openstack_auth.username }}"
```

В штатной конфигурации Kolla `openstack_auth.project_name` ссылается на
`keystone_admin_project`, а `openstack_auth.username` — на
`keystone_admin_user`. Обычно оба значения равны `admin`. Эти allowlist
ограничивают только ветку `powerops_operator` и не ограничивают `admin`.

Kolla идемпотентно обеспечивает существование точной роли
`powerops_operator`, но не назначает её пользователям и не создаёт Keystone
implied-role relation. Назначение роли остаётся явной операцией администратора.

### Две точки проверки

Horizon повторяет правило только для видимости панели и кнопок. Прямой URL к
панели проверяет тот же UI-предикат и возвращает `403`, но эта проверка не
является границей безопасности.

Mistral является источником окончательного решения:

1. Mistral API проверяет текущий авторизованный Keystone context при старте и
   возобновлении PowerOps workflow.
2. Каждая PowerOps action повторно проверяет trusted security context до чтения
   инфраструктурного inventory и до мутаций.

Роли, user/project identity и данные авторизации берутся только из
валидированного request context. Workflow input, environment, HTTP form и
Horizon session не могут добавить или заменить роли. Зарезервированные поля
авторизации в пользовательском input/environment отклоняются.

Поддержка trusted roles в `mistral-lib` и Mistral является обязательным
backend-контрактом. Имеющиеся незавершённые реализации этого контракта не
принимаются автоматически: они повторно проверяются и при необходимости
пересобираются отдельными патчами от чистых upstream-деревьев.

## Инвентаризация

Horizon получает сведения через read-only PowerOps inventory в Mistral.
Mistral использует свои сервисные credentials для чтения Nova, Masakari и
Ironic. Для каждого канонического Masakari host возвращаются:

- настроенный сервером регион;
- имя хоста и Masakari segment UUID;
- состояние `nova-compute`: `enabled/disabled` и `up/down`;
- Masakari `on_maintenance`;
- UUID сопоставленного Ironic Node и нормализованное состояние питания;
- количество ВМ на хосте;
- минимальные сведения о каждой ВМ: UUID, имя, project ID и состояние;
- активное PowerOps execution, если оно найдено;
- решение `operable` и очищенная причина блокировки.

Не возвращаются токены, пароли, BMC-адреса, driver info, metadata ВМ и иные
данные, не нужные для оценки воздействия операции.

Невозможность получить обязательный набор данных от Nova, Masakari или Ironic
завершает общую инвентаризацию ошибкой. Неоднозначный или повреждённый отдельный
host возвращается как `operable=false`, чтобы остальные строки оставались
доступны для диагностики.

Inventory — только снимок для UI. Перед каждой мутацией Mistral после получения
host-lock заново выполняет авторизацию, точное сопоставление ресурсов,
перечитывает ВМ и проверяет состояние инфраструктуры.

## Панель Horizon

Таблица `PowerOps -> Compute Hosts` показывает:

- регион и хост;
- Masakari segment;
- состояния Nova, Masakari и Ironic;
- количество и минимальный список ВМ;
- текущую PowerOps-операцию;
- доступные действия;
- диагностическую причину недоступности действия.

Регион отображается из серверной конфигурации и текущего service catalog. Он не
является редактируемым workflow input.

Кнопки изменения состояния доступны только для `operable=true` и разрешённой
роли. Наличие кнопки не отменяет повторные серверные проверки Mistral.

## Контракт workflow

Плагин использует только заранее определённые workflow:

- `power_ops.host_inventory` — discovery и общий preflight;
- `power_ops.host_power_status` — свежий статус одного хоста;
- `power_ops.planned_power_off` — плановое выключение;
- `power_ops.planned_reboot` — плановая перезагрузка;
- `power_ops.power_on_and_return` — двухфазное включение и возврат.

Horizon не принимает произвольное имя workflow, action или YAML/JSON-описание
выполнения.

Для `planned_power_off` и `planned_reboot` передаются типизированные значения:

```text
host: string
segment_uuid: UUID/string из inventory
instance_policy: require_empty | live_migrate | stop
allow_hard_off: JSON Boolean
```

Horizon показывает hard-off control только для `planned_power_off` и только
пользователю, прошедшему по ветке `admin`. Для `planned_reboot` Horizon всегда
передаёт `allow_hard_off=false`.

`require_empty` является значением по умолчанию:

- `require_empty` запрещает операцию, если на хосте остаётся хотя бы одна ВМ;
- `live_migrate` последовательно мигрирует ВМ и требует пустого source host
  перед power action;
- `stop` последовательно останавливает ВМ и сохраняет точный manifest для
  последующего возврата.

Политики относятся ко всем ВМ хоста независимо от их проекта.

## Подтверждение выключения и перезагрузки

Перед запуском Horizon:

1. обновляет inventory;
2. показывает минимальный список всех затрагиваемых ВМ;
3. показывает выбранную политику и её последствия;
4. требует ввести точное имя хоста;
5. передаёт `allow_hard_off=false` по умолчанию;
6. только для `planned_power_off` и только для `admin` предоставляет отдельный
   явно подтверждаемый флаг hard-off;
7. отправляет один запрос и сразу сохраняет возвращённый execution UUID.

Для `powerops_operator` hard-off control не отображается, а
`allow_hard_off=true`, переданный напрямую, отклоняется Mistral.

После получения execution UUID повторное нажатие блокируется. Lock и повторные
проверки Mistral остаются авторитетной защитой от параллельных операций.

## Включение и возврат в эксплуатацию

Возврат является продолжением контролируемого планового цикла:

1. Horizon выбирает совместимое успешное `planned_power_off` и берёт из него
   неизменяемый `stopped_instance_ids` manifest.
2. `power_ops.power_on_and_return` включает питание для проверки.
3. Nova остаётся disabled, а Masakari maintenance остаётся включённым.
4. Workflow переходит в `PAUSED`.
5. Оператор проверяет консоль, состояние ОС/гипервизора и отсутствие stale
   domains.
6. Оператор устанавливает точный Boolean `stale_domains_checked=true` и
   возобновляет то же execution.
7. Mistral повторно авторизует текущего пользователя, использует исходный
   manifest, запускает ранее остановленные ВМ, включает Nova и снимает Masakari
   maintenance.

Новый workflow вместо resume не создаётся. Manifest нельзя редактировать в
Horizon. Дополнительно действуют штатные Mistral policy владения execution:
`admin` может работать как администратор, а `powerops_operator` — в разрешённом
проектном контексте.

## Masakari и аварийное восстановление

Плановые и аварийные пути разделены:

- Mistral владеет плановым выключением, перезагрузкой и возвратом;
- Masakari владеет обнаружением аварии, fencing и evacuation;
- Ironic выполняет только операции питания;
- Horizon отображает состояние Masakari, но не создаёт аварийные notifications
  и не запускает fencing/evacuation.

Mistral и Masakari используют общий lock `powerops/host/<host>` в одном
логическом etcd-кластере. Операции не вытесняют друг друга. Если lock занят,
истёк срок ожидания либо потеряна coordination/ownership, новый путь
останавливается fail-closed без последующих мутаций.

## Новый WSGI-патч Masakari

`patches/kolla-ansible/0006-fix-load-Masakari-through-idempotent-WSGI-wrapper.patch`
является обязательной deployment-зависимостью целевого комплекта. Он:

- добавляет управляемый Kolla-файл `/etc/masakari/masakari-api.wsgi`;
- экспортирует `masakari.wsgi.api.application`;
- направляет Apache `WSGIScriptAlias` на этот wrapper;
- устраняет зависимость от legacy `masakari-wsgi` entry point и повторную
  инициализацию конфигурации.

Это патч Kolla-Ansible, а не новый патч исходников Masakari. Он обеспечивает
стабильный запуск Masakari API, но не меняет PowerOps RBAC, workflow или
аварийную state machine. Его проверка входит в backend readiness до проверки
Horizon.

## Ошибки и безопасное поведение

Синхронные ответы Horizon различают:

- `403` — пользователь не прошёл RBAC;
- `409` — конфликт состояния, активная операция или занятый host-lock;
- `422` — неверный параметр, тип, политика либо подтверждение;
- `503` — недоступен Mistral или обязательный backend.

После создания execution дальнейший результат асинхронный. Horizon показывает
execution, task и action states и очищенный текст ошибки. UI не объявляет
операцию успешной только потому, что Mistral принял запрос.

При timeout или обрыве соединения с неопределённым результатом Horizon не
повторяет power/workflow запрос автоматически. Пользователь сначала проверяет
Mistral executions и фактические состояния Nova, Masakari и Ironic.

Horizon также не выполняет автоматический rollback. Безопасный fail-closed
результат может намеренно оставить Nova disabled и Masakari maintenance=true
для ручной диагностики.

## Аудит

Для каждой операции сохраняются:

- user ID/name, project ID/name и trusted roles;
- использованная ветка `admin` или `powerops_operator`;
- регион, host и segment UUID;
- операция, instance policy и факт разрешения hard-off;
- Mistral workflow и execution UUID;
- временные метки, этапы и итоговое состояние.

Токены, пароли, BMC-адреса, BMC credentials и driver secrets не сохраняются в
данных UI и не выводятся в операторский аудит.

## Kolla-интеграция

Kolla-Ansible должен:

- установить отдельный `powerops-dashboard` в Horizon image;
- включить plugin только при включённых Horizon, Mistral и PowerOps;
- независимо сохранять возможность включения штатного `mistral-dashboard`;
- передать в Horizon один `openstack_region_name` и те же два allowlist, что и
  в Mistral;
- обеспечить существование роли `powerops_operator` без автоматического
  назначения;
- установить проверенную поддержку trusted roles в Mistral API/engine/executor;
- зарегистрировать проверенные PowerOps actions и публичный workbook;
- применить WSGI-wrapper Masakari API;
- выполнить только read-only registration/readiness проверки, не запуская
  power action, migration, stop/start ВМ или evacuation.

## Стратегия повторной проверки backend

Проверка выполняется независимо для каждого upstream-проекта:

1. Зафиксировать точный commit чистого `stable/2025.1`.
2. Применить соответствующую полную patch series одной mailbox-транзакцией.
3. Проверить `git diff --check`, patch ordering и отсутствие неожиданных файлов.
4. Сравнить итоговое дерево с проверяемым source worktree.
5. Запустить профильные и полные доступные unit/linters suites.
6. Проверить межрепозиторные имена actions, workflow, inputs, config options и
   lock namespace.
7. Не переносить незавершённый код только на основании наличия старого commit.
8. Если обязательного контракта нет в опубликованной серии либо проверка не
   проходит, оформить исправление отдельным воспроизводимым backend-патчем;
   Horizon не должен компенсировать отсутствующую серверную защиту.

Проверяются как минимум:

- Masakari fencing до evacuation, stable-off и fail-closed coordination;
- Mistral host resolution, политики ВМ, service credentials и host-lock;
- trusted roles, обе ветки RBAC, admin из любого проекта, прямой API,
  косвенный вызов action и resume;
- admin-only hard-off для выключения и отсутствие hard-off control для reboot;
- Kolla image selection, конфигурация, reconciliation и prechecks;
- Masakari WSGI wrapper и доступность API `/` и `/v1` без power-команд.

## Проверка Horizon

### Unit и functional tests

Проверяются:

- видимость панели для `admin` и разрешённого `powerops_operator`;
- доступ `admin` из любого проекта;
- необходимость обоих allowlist для `powerops_operator`;
- запрет для обычного пользователя и direct URL;
- admin-only hard-off;
- точные типы полей и JSON Boolean;
- все три instance policy и `require_empty` по умолчанию;
- повторное подтверждение точного имени хоста;
- минимальный список ВМ всех проектов;
- блокировка неоперабельных строк;
- отсутствие автоматического retry;
- двухфазный resume того же execution;
- очистка ошибок и отсутствие секретов.

### Контрактные tests

Контрактные проверки сравнивают:

- имена workflow и их input с Mistral workbook;
- имена actions и параметры с Mistral registration;
- allowlist и регион между Kolla, Horizon и Mistral;
- условия включения plugin с Kolla;
- общий host-lock namespace Mistral и Masakari;
- отсутствие прямого изменяющего клиента Ironic/Masakari/Nova в plugin.

### Сборка и просмотр

Первый запускаемый результат — локально собранный Horizon 2025.1 с
`powerops-dashboard` и mock backend. В этом режиме все изменяющие операции
эмулируются. Проверяются навигация, одна строка региона, таблица, роли, формы,
подтверждения, execution states и ошибки.

После этого собирается отдельный Horizon image с plugin и выполняется smoke-test
импорта/загрузки. Успешные локальные tests и сборка доказывают структурную
совместимость, но не доказывают работу с реальными Nova, Masakari, Ironic,
etcd, BMC или production policy.

## Руководство эксплуатации

Отдельный русскоязычный документ должен описывать:

- назначение `admin` и `powerops_operator`;
- создание роли и явное назначение пользователям;
- значение project/user allowlist и Kolla defaults;
- установку plugin и backend patch series;
- проверку Masakari WSGI/API;
- плановое выключение, reboot и двухэтапный возврат;
- поведение трёх политик ВМ;
- admin-only hard-off;
- чтение execution states и аудит;
- действия при `403`, `409`, `422`, `503`, timeout и `ERROR`;
- проверку Nova disabled, Masakari maintenance, Ironic power state и etcd lock;
- явное разделение планового Mistral и аварийного Masakari путей.

## Не входит в объём

- multi-region routing и cross-region HA/DR;
- отдельный backend API, дублирующий Mistral;
- прямые power-вызовы из Horizon в Ironic/BMC;
- ручной запуск Masakari fencing или evacuation из Horizon;
- произвольный запуск workflow/action через PowerOps forms;
- автоматическое назначение Keystone-ролей;
- автоматический retry или rollback после неопределённого результата;
- автоматическое подтверждение stale domains;
- реальное выключение хоста без отдельного разрешения.

## Критерии приёмки

Работа считается готовой к этапу эксплуатационной проверки, когда:

1. чистый Horizon `stable/2025.1` собирается с отдельным plugin;
2. все варианты RBAC и admin-only hard-off проверены тестами;
3. UI вызывает только разрешённые Mistral workflow с точными типами input;
4. inventory показывает согласованное состояние Nova/Masakari/Ironic и
   минимальный состав ВМ;
5. mutation повторно валидируется Mistral под host-lock;
6. PowerOps и аварийный Masakari не могут одновременно изменить один хост;
7. двухфазный возврат возобновляет то же execution и исходный VM manifest;
8. WSGI-патч Masakari повторно применён и его tests проходят;
9. backend patch series воспроизводимы от зафиксированных upstream commits;
10. локальная mock-сборка Horizon доступна для визуальной проверки;
11. создано отдельное руководство эксплуатации;
12. ни один test/build этап не выполняет реальную power-команду или изменение
    состояния ВМ.
