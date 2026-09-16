# OpenStack Epoxy 2025.1: возможности CLI и Horizon с учётом наших доработок


## Как читать документ

Всё содержимое анализа и таблицы находятся в этом MD. Для навигации используйте оглавление Markdown-просмотрщика или поиск точного имени команды. Таблицы разделены по компонентам, чтобы не создавать одну широкую таблицу на 953 строки. Внешние ссылки ведут к исходникам зафиксированных версий и коммитов. Относительные ссылки открывают данные и выбранные исходники из этого каталога; пояснения и все таблицы находятся в данном MD.

- [Краткий вывод и границы](#summary).
- [Все основные команды: 817 строк](#matrix).
- [Полные контракты наших доработок](#custom).
- [Старые API базового клиента: 136 регистраций](#legacy).
- [Отдельные сервисные клиенты и проверка полноты](#completeness).

Статусы в столбце Horizon:

| Статус | Значение |
|---|---|
| Есть | Основное пользовательское действие или результат представлены в штатном UI. Это не обещание наличия каждого аргумента CLI. |
| Частично | Есть связанное действие, но конкретные поля, scope, типы входа или режимы ограничены; различие указано в строке. |
| Условно | Реализация есть при дополнительном условии: extension, настройка, feature flag или поддержка backend. |
| Нет | Не найдено самостоятельного пользовательского действия/представления. Внутренний API helper и вызов сервиса другим workflow не считаются готовой UI-функцией. |
| Не применимо | Возможность относится к окружению самого CLI, а не к облачному UI. |

Для всех строк необходимы соответствующий сервис, права, поддерживаемая версия API и допустимое состояние ресурса. Полнота гарантируется на уровне **регистраций команд**, а не всех комбинаций аргументов, API-полей или поддерживаемых сервером расширений. Команды без слова `openstack` в специальных таблицах ниже — отдельные программы.

Столбец «Наш слой» ссылается на проверенный backend-контекст компонента. Он не означает изменения каждого указанного CLI-обработчика. «—» означает, что отдельной связанной доработки в исследованном комплекте не установлено.

| Код | Доработка и её влияние |
|---|---|
| P1 | Mistral PowerOps: четыре workflow и пять серверных actions через существующие generic команды; типизированные JSON inputs и gate возврата. |
| M1 | Masakari: fencing, общий source lock и ожидание свежего Nova disabled/down до эвакуации. |
| M2 | Masakari/Nova: admission, intents/operations, очередь и ограничения принимающего compute; отдельная evacuation guard CLI. |
| W1 | Watcher: hold автоматического пути CONTINUOUS, revision/epoch, отдельная guard CLI. |
| N1 | Nova: участие в per-target evacuation; обычные migrate/service команды не заменяют полный PowerOps workflow. |
| I1 | Ironic: BMC-only профиль регистрации Kolla; прямые power-команды не выполняют Mistral drain/return. |


<a id="summary"></a>



Дата анализа: **16 сентября 2026 года**.

## Краткий вывод

**OpenStackClient с пятью сервисными плагинами предоставляет более широкий операторский интерфейс, чем штатный Horizon с соответствующими dashboard-плагинами.** Horizon покрывает основные операции с облачными ресурсами и часть административных сценариев. Разница особенно заметна в типизированных входах Mistral, управлении Watcher, расширенных операциях Ironic и служебных операциях Heat.

Для нашей реализации полного равенства нет и на уровне сценариев: PowerOps использует типы JSON и ручной gate возврата, которые штатные формы Mistral не выражают полностью. Блокировка автоматизации Watcher и очередь эвакуации имеют собственные служебные CLI; команды `openstack` и штатные панели Horizon ими не управляют. Вместе с тем серверные защитные проверки продолжают действовать независимо от интерфейса, через который пришёл запрос.

Исследован **весь базовый `python-openstackclient 7.4.0` — 683 регистрации — и все 270 регистраций пяти согласованных OSC-плагинов**. В основном сравнении 817 строк: 547 базовых и 270 плагинных. Ещё 136 регистраций старых API приведены отдельно. Каждая регистрация сохранена в таблицах этого документа; одинаковые имена разных API и aliases не считаются независимыми бизнес-функциями.

## 1. Объём и метод

Сравниваются:

- **CLI:** `python-openstackclient` и плагины `python-masakariclient`, `python-watcherclient`, `python-mistralclient`, `python-heatclient`, `python-ironicclient`.
- **UI:** upstream Horizon и `masakari-dashboard`, `watcher-dashboard`, `mistral-dashboard`, `heat-dashboard`, `ironic-ui`. Собственные изменения Horizon исключены по условию задачи.
- **Наш backend:** PowerOps `0809`, post-fence Nova-down, Watcher automation hold, per-target evacuation Nova/Masakari и связанная конфигурация/enrollment Kolla-Ansible. Серверные патчи раннего отдельного комплекта рассмотрены с явной отметкой несовместимой/непроверенной базы.

Наличие CLI-команды установлено по entry points `setup.cfg` и реализации обработчика. Наличие UI-операции — по регистрации панели, URL, форме и действиям таблицы; один вспомогательный API-метод не считается готовой UI-возможностью. Существенные аргументы и ограничения проверены по исходникам конкретных версий.

**Это статический анализ.** Не проверялись установленные в облаке версии, фактические роли пользователя, enabled-панели, API microversions сервера, реальные миграции, fencing и поведение браузера. Команды из примеров не запускались. Анализ не изменял код сервисов, конфигурацию и стенд. Документ опубликован отдельно в `docs/openstack-cli-horizon-2025.1/README.md`; каталог `data/` содержит реестры, а `evidence/` — выбранные проверенные исходники, необходимые для ссылок.

## 2. Версии: финальная база цикла 2025.1

У OpenStack нет одной версии «openstackcli 2025.1»: клиент, плагины и Horizon выпускаются отдельными пакетами. Для воспроизводимого сравнения взяты релизы, соответствующие финальной базе/ответвлению `stable/2025.1`, а не первая промежуточная версия цикла и не текущий `latest`.

| Назначение | CLI-пакет / версия | UI-пакет / версия | Команды OSC плагина |
|---|---|---|---:|
| Базовое облако | `python-openstackclient 7.4.0` | `horizon 25.3.0` | 683: 547 основных + 136 legacy |
| Masakari | `python-masakariclient 8.6.0` | `masakari-dashboard 12.0.0` | 15 |
| Watcher | `python-watcherclient 4.8.0` | `watcher-dashboard 13.0.0` | 28 |
| Mistral | `python-mistralclient 5.4.0` | `mistral-dashboard 20.0.0` | 71 |
| Heat | `python-heatclient 4.1.0` | `heat-dashboard 13.0.0` | 49 |
| Ironic | `python-ironicclient 5.10.0` | `ironic-ui 6.5.0` | 107 |
| **Итого пяти плагинов** | | | **270** |

Версии и происхождение подтверждены [официальным составом Epoxy](https://releases.openstack.org/epoxy/index.html) и release YAML/тегами, указанными в компонентных приложениях. Это исследовательская база сравнения, а не рекомендация заменить установленные пакеты или откатить maintenance-обновления. Документация `/2025.1/` обновляется вместе со stable-веткой; поэтому точные команды сверялись с тегами.

Пять dashboard-плагинов устанавливаются отдельно от Horizon. Пять CLI-плагинов также должны присутствовать в том Python-окружении, из которого запускается `openstack`. Установка сервера Masakari/Watcher/Mistral/Heat/Ironic сама по себе не добавляет команд на операторский компьютер.

## 3. Базовый OpenStackClient и Horizon

| Область | Основные возможности CLI | Что есть в Horizon | Существенная разница |
|---|---|---|---|
| Nova | Servers, flavors, keypairs, groups, console, images/volumes/networks при создании ВМ; lifecycle, resize, migrate/live migrate, evacuate, migrations, aggregates, hypervisors, compute services, quotas | Создание/изменение ВМ, консоль, lifecycle, resize; административные live/cold migration, evacuation host, compute maintenance, flavors/aggregates | UI предоставляет формы для выбранных параметров. Просмотр/управление отдельными migration records и расширенные параметры CLI шире. Нельзя утверждать, что миграции или эвакуация в штатном Horizon вообще отсутствуют |
| Neutron | Network/subnet/port/router/floating IP/security group; agents, network RBAC, QoS, trunks, address groups/scopes, subnet pools и другие группы | Основные сетевые ресурсы, topology, security groups, floating IP; часть административных функций и расширений | Полный набор API extension-параметров и служебных объектов не покрывается одинаково всеми формами. Доступность зависит от Neutron extensions и настроек Horizon |
| Cinder | Volumes, snapshots, backups, types, QoS, transfers, groups, services, quotas; расширенное управление backend/volume operations | Основной lifecycle volumes/snapshots/backups, подключения, transfers; admin manage/unmanage, migration, reset status | Для `block storage log level` и `block storage cleanup` UI нет; manage/unmanage, миграцию и reset status нельзя целиком записывать в пробелы UI |
| Glance | Image create/list/show/set/unset/delete/save/stage/import, members, tasks, metadata definitions | Каталог, загрузка/создание/изменение образов, visibility и metadata в предусмотренных формах | CLI явно предоставляет tasks и разные этапы import/stage; UI не является универсальной формой всех Glance API |
| Keystone | Projects/domains/users/groups/roles, role assignments, application credentials, service catalog/endpoints, federation, mappings, trusts, limits | Основное identity, credentials/application credentials, federation IdP/mappings, в зависимости от роли | Service catalog показан без CRUD service/endpoint; нет самостоятельных endpoint-group/registered-limit форм |
| Swift | Containers/objects: list/create/upload/show/save/delete и metadata/ACL | Контейнеры, просмотр/загрузка/скачивание/копирование/редактирование объектов, базовые операции доступа | UI имеет собственный Copy Object workflow; CLI — account set/show/unset и возможности автоматизации. Нельзя считать UI строгим подмножеством названий OSC-команд |

Эта таблица даёт обзор. Ниже в этом же документе приведено покомандное сопоставление всего базового CLI и пяти плагинов. Общие первичные справочники: [OSC command list 2025.1](https://docs.openstack.org/python-openstackclient/2025.1/cli/command-list.html), [Horizon user documentation 2025.1](https://docs.openstack.org/horizon/2025.1/user/).

В core-реестре оставлены разные пространства API версий; одинаковое имя команды может встречаться несколько раз. Сумма всех таких строк не означает столько одновременно доступных уникальных команд. CLI также не равен всему REST API: отсутствие конкретного entry point может требовать сервисного клиента, SDK или API. Собственная ценность UI — интерактивная консоль, topology, переходы между связанными ресурсами и графический Heat Template Generator; это не дополнительные одинаково названные CLI-команды.

## 4. Masakari: HA-сегменты, хосты и восстановление

| Функция | CLI | Штатный Masakari Dashboard |
|---|---|---|
| HA segments | `segment list/show/create/update/delete` | Базовый CRUD; некоторые поля ограничены формой, например service type |
| Hosts в сегментах | `segment host list/show/create/update/delete`, reserved и maintenance | Добавление Nova compute в сегмент, изменение reserved/maintenance, просмотр/удаление; имя при обновлении readonly |
| Notifications | `notification list/show/create` | Список, детали и recovery progress; **создания notification нет** |
| VMoves | `notification vmove list/show` | Список и подробности перемещений |
| Retry/cancel recovery, управление внутренними lock | Специализированных команд в этом плагине нет | Специализированных действий нет |

Пользовательский namespace — `openstack segment …` и `openstack notification …`; `ha` является внутренним именем расширения, а не обязательным словом команды. Штатный UI Masakari умеет управлять сегментами и хостами, его нельзя считать только мониторингом.

Наши fencing, ожидание Nova down, source lock и ограничения эвакуации — серверное поведение. Оно применяется к соответствующему recovery без нового аргумента `notification create`. Штатные клиенты показывают обычные notification/VMoves, а состояние новых guard-записей требует собственной утилиты. Источники и детали: [Masakari/Watcher](#masakari), [наши доработки](#custom).

## 5. Watcher: оптимизация и action plans

| Функция | CLI `openstack optimize …` | Штатный Watcher Dashboard |
|---|---|---|
| Goals и strategies | `goal list/show`, `strategy list/show/state` | Списки/детали; нет strategy state, вывод параметров стратегии ограничен |
| Audit templates | `audittemplate list/show/create/update/delete` | Create, details, archive/delete, launch audit; **update отсутствует** |
| Audits | `audit list/show/create/update/delete` | Create из template, list/details, cancel, archive; нет полного update, EVENT, прямого goal/strategy и всех параметров CLI |
| Action plans | `actionplan list/show/update/start/cancel/delete` | List/details, start, archive; **cancel и общий update отсутствуют** |
| Actions | `action list/show` | List/details |
| Диагностика | `scoringengine list/show`, `service list/show`, `datamodel list` | Соответствующих панелей нет |

Standalone `watcher …` предоставляет те же 28 обработчиков с соответствующими именами. Это дополнительные способы вызова, не ещё 28 новых возможностей. В теге не зарегистрирована `actionplan create`, хотя устаревший раздел документации её упоминает; план формирует сервер в ходе audit.

Наш automation hold добавляет долговечный запрет новых периодических расчётов и допуска новых действий при принятой аварии Masakari. Он не является общей блокировкой ручных Mistral/Nova операций и не отменяет уже допущенные действия. Команда возобновления находится в `powerops-watcher-guard`, а не в `openstack optimize`. Источники: [компонентный анализ](#masakari), [точная граница guard](#custom).

## 6. Mistral: workflow и исполнение PowerOps

| Функция | CLI | Штатный Mistral Dashboard |
|---|---|---|
| Workbooks/workflows/actions | Управление definitions, list/show, создание/изменение/удаление в предусмотренных группах | Формы загрузки/редактирования definitions, списки/детали и основные действия |
| Workflow executions | Create с JSON input/params, list/show, update state/env/description, input/output/report/published, delete | Execute, list/details, input/output, pause/resume, описание и удаление; не все CLI-возможности |
| Action executions | Run с JSON, list/show/input/output/update/delete | Run Action с JSON, list/detail/delete, update state/output; это не task rerun и не workflow env-update |
| Tasks | List/show, result/published, rerun | Просмотр tasks/results; нет полного набора CLI управления |
| Environments, cron/event triggers, services, members, code sources, dynamic actions | Отдельные группы CLI | Cron Trigger CRUD есть; самостоятельных панелей остальных перечисленных групп нет |

**Ключевой разрыв для PowerOps:** Execute Workflow в dashboard 20.0.0 создаёт `CharField` для каждого параметра и передаёт строку либо `None`. Наш backend требует boolean для `allow_hard_off`, массив для `stopped_instance_ids` и boolean true в `env.stale_domains_checked`. Кнопка Resume меняет state на RUNNING без передачи `env`. Поэтому штатная форма не воспроизводит полный сценарий планового питания и возврата.

CLI умеет выразить необходимое возобновление через **`workflow execution update`**, а не через несуществующую отдельную команду `workflow execution resume`:

```bash
# Пример изменения execution после фактической ручной проверки; здесь не выполнялся.
openstack workflow execution update EXECUTION_UUID \
  --state RUNNING --env '{"stale_domains_checked": true}'
```

Run Action в UI действительно поддерживает JSON, но запускает отдельный action и не заменяет граф workflow с паузой. Create Cron Trigger также принимает JSON input/params, однако создаёт триггер и не решает передачу env при возврате. `powerops.host_power_status` имеет строковые аргументы и может использоваться из generic workflow UI для просмотра output. Ни workflow видимость, ни кнопка Run Action не означают наличия специализированной PowerOps панели. Ещё одна особенность: кнопка Cancel execution отправляет состояние ERROR, а не CANCELLED.

Standalone `mistral` имеет три дополнительные предметные команды относительно OSC 5.4.0: `action-validate`, `execution-get-sub-executions`, `task-get-sub-executions`. Источники, полная матрица и реестр: [mistral-heat.md](#mistral), [71+49 OSC entries](https://github.com/lebtmalorny-rgb/mimaric/blob/89be5492cba1a1c44d187a7f1df4a4b2243e1ab1/docs/openstack-cli-horizon-2025.1/data/mistral-heat-osc-inventory.tsv), [standalone Mistral](https://github.com/lebtmalorny-rgb/mimaric/blob/89be5492cba1a1c44d187a7f1df4a4b2243e1ab1/docs/openstack-cli-horizon-2025.1/data/mistral-standalone-inventory.tsv).

## 7. Heat: управление инфраструктурными шаблонами

| Функция | CLI | Штатный Heat Dashboard |
|---|---|---|
| Основной lifecycle stack | Create/list/show/update/delete, check/suspend/resume | Launch, preview, список/детали, change template, delete, check/suspend/resume |
| Resources/events/outputs | Отдельные команды подробного просмотра, фильтрации и специализированных операций | Вкладки ресурсов/событий/outputs, схема topology |
| Templates/environment | Validate, template/environment show, параметры и файлы при create/update | Выбор/загрузка шаблона и environment, ввод параметров, preview |
| Advanced stack operations | Adopt/abandon, export, snapshot lifecycle, cancel и другие команды реестра | Соответствующих стандартных действий в stack table нет |
| Software config/deployment | Отдельные группы управления | Отдельного CRUD этих ресурсов нет |
| Resource types, services, template versions/functions | Справочные/служебные группы CLI | Часть справочной информации UI; не полный набор CLI |
| Графическое создание шаблона | Работа с текстовым HOT и его валидацией | Template Generator: ресурсы/связи, Download HOT, передача в Launch Stack; Import/Export Draft помечены Not Implemented |

Heat Dashboard достаточно функционален для обычного обслуживания stack. Он не заменяет CLI для переноса/снимков/служебных объектов и всех вариантов resource management. Новая функция Heat в наших исследованных компонентных патчах не обнаружена; произвольный шаблон с вызовом другого сервиса не считается доказанной готовой PowerOps интеграцией. Источник: [подробный Heat-анализ](#mistral).

## 8. Ironic: широкий CLI и ограниченный API-профиль UI

| Функция | CLI `openstack baremetal …` | Штатный Ironic UI |
|---|---|---|
| Nodes, properties, interfaces, driver info | Создание/изменение/просмотр/удаление, validate, rich node set/unset | Enroll/edit/delete node, details, driver interfaces/properties и ограничения форм |
| Power, maintenance, console | Power on/off/reboot, maintenance, console enable/disable/show | Power on/off, soft power off, reboot/soft reboot, maintenance, просмотр/переключение console; это BMC-операции |
| Provisioning state | Manage/provide/adopt/deploy/undeploy/rebuild/inspect/clean/abort/rescue/unrescue и другие зарегистрированные переходы | Только переходы из UI state graph и предусмотренных состояний; rescue/unrescue отсутствуют |
| Ports/port groups | Полный зарегистрированный набор lifecycle | Основные CRUD и привязки ports/portgroups |
| BIOS, RAID, traits, allocations | BIOS list/show, конфигурационные/cleaning операции, target RAID config, traits, allocations | RAID Configuration и JSON clean steps есть; самостоятельного BIOS, traits и allocations UI нет |
| Conductors, deploy templates, storage/network inventory и другие новые ресурсы | Соответствующие команды клиента | Отдельных полноценных панелей нет |

В `ironic-ui 6.5.0` API adapter **жёстко задаёт Ironic microversion 1.34**. Это существенная техническая граница: актуальность серверного Ironic 2025.1 не делает все его новые API-функции доступными через этот UI. Возможности клиента тоже требуют совместимой microversion сервера и hardware interface, а не только наличия команды.

В нашей поставке Ironic обслуживает питание существующих compute: manageable, network/storage noop, no-inspect/no-bios/no-raid. Универсальные upstream deploy/clean/provide возможности не являются поддерживаемым сценарием для этих зарегистрированных хостов. Прямой power-off из Ironic UI/CLI не выполняет Mistral PowerOps drain, maintenance и координацию. Источники: [Ironic и core](#ironic), [локальные доработки](#custom).

## 9. Покрытие наших доработок

| Доработка | Как пользоваться | Штатный Horizon |
|---|---|---|
| Четыре PowerOps workflow / пять actions базы `0809` | Generic Mistral OSC с типизированным JSON | Частичное наблюдение/запуск; полного workflow-контракта формы не выражают |
| Masakari fencing и Nova-down gate | Автоматический backend recovery | Видны стандартные уведомления/прогресс; отдельных органов управления нет |
| Watcher automation hold | Автоматический backend + `powerops-watcher-guard` | Нет status/revision/resume формы guard |
| Per-target evacuation Nova/Masakari | Автоматический backend + `powerops-evacuation-guard` | Нет очереди claims/intents/operations и разрешения UNKNOWN |
| Ironic BMC-only enrollment | `kolla-ansible enroll-ironic` | Generic Enroll Node не повторяет Ansible-профиль |
| Service config / metrics / etcd / policy wiring | Kolla-Ansible и конфигурация сервисов | Не универсальные REST-настройки, штатных форм нет |
| Backend inventory/RBAC раннего комплекта | Только при наличии exact согласованного backend | Не учитывается как действующая возможность `0809`; собственный UI исключён |

Подробная матрица, восемь команд evacuation guard, три команды Watcher guard и проверенные базы: [local-customizations.md](#custom). Происхождение локальных источников: [local-source-manifest.json](https://github.com/lebtmalorny-rgb/mimaric/blob/89be5492cba1a1c44d187a7f1df4a4b2243e1ab1/docs/openstack-cli-horizon-2025.1/data/local-source-manifest.json).

## 10. Что проверить в установленном окружении

Ниже только примеры чтения/проверки интерфейса. Они нужны, чтобы сопоставить этот статический отчёт с фактической поставкой; в рамках анализа не выполнялись.

```bash
openstack --version
openstack command list
openstack help segment list
openstack help optimize audit create
openstack help workflow execution update
openstack help stack create
openstack help baremetal node show

openstack segment list
openstack notification list
openstack optimize service list
openstack optimize audit list
openstack workflow list
openstack workflow execution list
openstack stack list
openstack baremetal node list
```

Для guard-состояний используются их собственные конфиги и программы:

```bash
powerops-watcher-guard --config-file /etc/watcher/watcher.conf status
powerops-evacuation-guard --config-file /etc/powerops/evacuation.conf status --limit 100
```

Это отдельный сервисный доступ к etcd, не замена аутентификации через Keystone. Наличие этих утилит и фактическое расположение конфигов требуется проверить в целевом операторском окружении. Для Horizon отдельно сверяются версии пяти плагинов, их enabled-файлы, service catalog, доступ пользователя и отрисовка предусмотренных действий. Локально найденное Kolla wiring не доказывает результат такого runtime-чтения.

## 11. Вывод для выбора интерфейса

Для повседневного обслуживания стандартных ресурсов Horizon подходит как рабочий интерфейс. Для полного набора функций рассматриваемых компонентов нужен CLI; для нашего PowerOps операторский контур состоит из **OpenStackClient с плагинами + двух guard-утилит + Kolla-Ansible для конфигурации/enrollment**.

Если требуется обеспечить те же сценарии через UI, незакрытые потребности уже определены: типизированные PowerOps формы и resume env; наблюдение/управление Watcher hold; состояние и разбор очереди эвакуации; перечисленные upstream-пробелы Watcher/Ironic/Heat. Для guard-операций дополнительно нужен подходящий серверный API с авторизацией, если управлять ими через Horizon: штатные проекты сейчас не предоставляют его. Прямой доступ браузера к etcd не является существующим UI-контрактом. Этот отчёт фиксирует потребности; реализация UI не входила в задачу.


<a id="matrix"></a>
## 12. Полная покомандная матрица


| Компонент | Регистраций | Есть | Частично | Нет | Условно | Не применимо |
| --- | --- | --- | --- | --- | --- | --- |
| [Общие команды](#common) | 13 | 0 | 5 | 5 | 0 | 3 |
| [Nova — вычислительные ресурсы](#nova) | 95 | 40 | 35 | 20 | 0 | 0 |
| [Neutron — сети](#neutron) | 160 | 57 | 20 | 83 | 0 | 0 |
| [Cinder — блочное хранилище](#cinder) | 93 | 42 | 10 | 36 | 5 | 0 |
| [Glance — образы](#glance) | 41 | 11 | 11 | 19 | 0 | 0 |
| [Keystone — идентификация и доступ](#keystone) | 128 | 32 | 39 | 57 | 0 | 0 |
| [Swift — объектное хранилище](#swift) | 17 | 5 | 4 | 8 | 0 | 0 |
| [Masakari — высокая доступность](#masakari) | 15 | 10 | 4 | 1 | 0 | 0 |
| [Watcher — оптимизация](#watcher) | 28 | 16 | 3 | 9 | 0 | 0 |
| [Mistral — автоматизация](#mistral) | 71 | 36 | 6 | 29 | 0 | 0 |
| [Heat — оркестрация](#heat) | 49 | 17 | 4 | 28 | 0 | 0 |
| [Ironic — bare metal](#ironic) | 107 | 11 | 32 | 64 | 0 | 0 |


Счётчики описывают строки реестра, включая aliases. Они не являются процентом функционального покрытия или оценкой трудоёмкости реализации UI.


<a id="common"></a>
### 12.1. Общие команды


**13 регистраций.** CLI: `python-openstackclient 7.4.0`. Namespace: `openstack.common`, `openstack.cli`.


#### Общие свойства CLI, не сводимые к числу entry points

| Возможность | Что это даёт | Отличие UI |
|---|---|---|
| Keystone authentication plugins | Password, token, application credentials и поддерживаемые federation-механизмы | Horizon использует собственный login/session/WebSSO поток; поддержка одного auth plugin CLI не означает идентичную форму входа Horizon |
| `clouds.yaml`, `OS_*`, глобальные аргументы | Выбор облака, project/domain/system scope, region/interface, CA/сертификатов и таймаутов | UI использует серверную конфигурацию и контекст пользователя; API Access может скачать OpenRC/clouds.yaml |
| `--os-…-api-version` | Выбор API version/microversion, согласование поддержки клиентом/сервером | Dashboard API adapter может использовать иной фиксированный профиль, как Ironic1.34 |
| `help`, `complete`, `--help` | Справка фактически зарегистрированных команд и shell completion | Наследуемые возможности framework, не новые сервисные операции. Не включены повторно в 683 записи setup.cfg |
| Interactive mode | `openstack` без команды открывает сессию, сохраняющую клиентские контексты | UI — навигация в браузерной сессии; это другая форма взаимодействия |
| Структурированный вывод | Table/JSON/YAML/value/CSV и выбор колонок в поддерживающих форматирование командах | UI даёт таблицы/фильтры/визуализацию, а не единый машинный протокол вывода |
| Диагностика | `--debug`, `--timing`, exit codes, журналирование | UI сообщения об ошибках и серверные логи не равны подробному CLI HTTP/SDK tracing |
| `--wait`, повторяемые аргументы, файлы/JSON | Автоматизация и точные структурированные входы там, где они реализованы конкретной командой | Поддержка полей проверяется по конкретной форме; Mistral Workflow Execute показывает важное различие типов |

Поддержка форматов/`--wait` и аргументов зависит от конкретного обработчика; это не обещание одинаковых опций у всех команд. Вывод CLI о завершении запроса не доказывает готовность приложения в ВМ и не заменяет серверную проверку конечного состояния.

Первичные руководства находятся и в сохранённом теге: [man/openstack](https://github.com/openstack/python-openstackclient/blob/7.4.0/doc/source/cli/man/openstack.rst), [authentication](https://github.com/openstack/python-openstackclient/blob/7.4.0/doc/source/cli/authentication.rst), [configuration](https://github.com/openstack/python-openstackclient/blob/7.4.0/doc/source/configuration/index.rst), [interactive](https://github.com/openstack/python-openstackclient/blob/7.4.0/doc/source/cli/interactive.rst).


| Команда | Возможность | Horizon | Пояснение / ограничение | Наш слой | Источники |
| --- | --- | --- | --- | --- | --- |
| `openstack availability zone list` | Availability zones сервисов | Частично | Зоны видны в формах запуска и System Information; нет единого агрегированного списка всех сервисов как CLI. | — | [CLI][S0001]; [UI][S0002] |
| `openstack command list` | Операторское окружение CLI: command list | Не применимо | Инвентаризация установленного клиента, его конфигурации или версий API; нет прямого экрана Horizon. | — | [CLI][S0001]; [UI][S0003] |
| `openstack configuration show` | Операторское окружение CLI: configuration show | Не применимо | Инвентаризация установленного клиента, его конфигурации или версий API; нет прямого экрана Horizon. | — | [CLI][S0001]; [UI][S0003] |
| `openstack extension list` | API extensions поддерживаемых сервисов | Нет | UI использует проверки extensions внутри; общего списка/details extensions для оператора нет. | — | [CLI][S0001]; [UI][S0004] |
| `openstack extension show` | API extensions поддерживаемых сервисов | Нет | UI использует проверки extensions внутри; общего списка/details extensions для оператора нет. | — | [CLI][S0001]; [UI][S0004] |
| `openstack limits show` | Текущие лимиты/использование compute и volume | Частично | Overview/quotas дают часть данных; rate/absolute CLI-вывод не полностью представлен. | — | [CLI][S0001]; [UI][S0005] |
| `openstack module list` | Операторское окружение CLI: module list | Не применимо | Инвентаризация установленного клиента, его конфигурации или версий API; нет прямого экрана Horizon. | — | [CLI][S0001]; [UI][S0003] |
| `openstack project cleanup` | Очистка ресурсов проекта с планом SDK cleanup | Нет | Delete Project не воспроизводит dependency-aware cleanup ресурсов разных сервисов. | — | [CLI][S0001]; [UI][S0006] |
| `openstack quota delete` | Квоты проектов: quota delete | Нет | Modify Quotas и Defaults показывают/меняют заданные поля compute/network/volume; отдельного сброса через quota delete и полного многопроектного CLI-вывода нет. | — | [CLI][S0001]; [UI][S0007] |
| `openstack quota list` | Квоты проектов: quota list | Частично | Modify Quotas и Defaults показывают/меняют заданные поля compute/network/volume; отдельного сброса через quota delete и полного многопроектного CLI-вывода нет. | — | [CLI][S0001]; [UI][S0007] |
| `openstack quota set` | Квоты проектов: quota set | Частично | Modify Quotas и Defaults показывают/меняют заданные поля compute/network/volume; отдельного сброса через quota delete и полного многопроектного CLI-вывода нет. | — | [CLI][S0001]; [UI][S0007] |
| `openstack quota show` | Квоты проектов: quota show | Частично | Modify Quotas и Defaults показывают/меняют заданные поля compute/network/volume; отдельного сброса через quota delete и полного многопроектного CLI-вывода нет. | — | [CLI][S0001]; [UI][S0007] |
| `openstack versions show` | Обнаружение облачных API: Version/Min/Max Microversion | Нет | Команда выполняет запросы к сервисам через get_all_version_data; это не инвентаризация локальных Python-пакетов. Общего UI эквивалента нет. | — | [CLI][S0001]; [UI][S0003] |


<a id="nova"></a>
### 12.2. Nova — вычислительные ресурсы


**95 регистраций.** CLI: `python-openstackclient 7.4.0`. Namespace: `openstack.compute.v2`.


#### Compute agents

| Команда | Доступ | UI | Возможность и граница | Источники |
|---|---|---|---|---|
| `openstack compute agent create` | mutation | no | Нет панели управления Nova guest-agent build records. Это compute agents; Neutron agents и nova-compute services — другие ресурсы. | [CLI](https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/agent.py#L31) [UI1](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/info/tables.py#L104) [UI2](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/hypervisors/compute/tables.py#L97) |
| `openstack compute agent delete` | mutation | no | Нет панели управления Nova guest-agent build records. Это compute agents; Neutron agents и nova-compute services — другие ресурсы. | [CLI](https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/agent.py#L82) [UI1](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/info/tables.py#L104) [UI2](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/hypervisors/compute/tables.py#L97) |
| `openstack compute agent list` | read | no | Нет панели управления Nova guest-agent build records. Это compute agents; Neutron agents и nova-compute services — другие ресурсы. | [CLI](https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/agent.py#L124) [UI1](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/info/tables.py#L104) [UI2](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/hypervisors/compute/tables.py#L97) |
| `openstack compute agent set` | mutation | no | Нет панели управления Nova guest-agent build records. Это compute agents; Neutron agents и nova-compute services — другие ресурсы. | [CLI](https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/agent.py#L166) [UI1](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/info/tables.py#L104) [UI2](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/hypervisors/compute/tables.py#L97) |

#### Aggregates

| Команда | Доступ | UI | Возможность и граница | Источники |
|---|---|---|---|---|
| `openstack aggregate add host` | mutation | yes | Manage Hosts добавляет выбранный compute-host в aggregate. | [CLI](https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/aggregate.py#L54) [UI1](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/aggregates/workflows.py#L202) [UI2](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/aggregates/tables.py#L165) |
| `openstack aggregate create` | mutation | partial | Create Host Aggregate: имя, AZ, выбор hosts. --property задаётся отдельным Update Metadata после создания. | [CLI](https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/aggregate.py#L87) [UI1](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/aggregates/workflows.py#L165) [UI2](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/aggregates/tables.py#L68) |
| `openstack aggregate delete` | mutation | yes | Удаление aggregate. | [CLI](https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/aggregate.py#L135) [UI1](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/aggregates/tables.py#L23) [UI2](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/aggregates/tables.py#L162) |
| `openstack aggregate list` | read | yes | Таблица name, AZ, hosts и metadata. | [CLI](https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/aggregate.py#L177) [UI1](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/aggregates/tables.py#L145) |
| `openstack aggregate remove host` | mutation | yes | Manage Hosts удаляет membership хоста. | [CLI](https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/aggregate.py#L237) [UI1](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/aggregates/workflows.py#L211) [UI2](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/aggregates/tables.py#L165) |
| `openstack aggregate set` | mutation | yes | Edit Aggregate меняет имя/AZ; Update Metadata добавляет/меняет/удаляет свойства. Выполняется через отдельные формы; удаление всех свойств — выбор всех в редакторе. | [CLI](https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/aggregate.py#L270) [UI1](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/aggregates/forms.py#L25) [UI2](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/aggregates/tables.py#L68) [UI3](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/api/rest/nova.py#L684) |
| `openstack aggregate show` | read | yes | Данные конкретного aggregate доступны в строке таблицы: имя, AZ, hosts, metadata. Отдельная detail-страница не требуется для этого отображения. | [CLI](https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/aggregate.py#L342) [UI1](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/aggregates/tables.py#L145) |
| `openstack aggregate unset` | mutation | yes | Update Metadata удаляет выбранные свойства aggregate. | [CLI](https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/aggregate.py#L371) [UI1](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/aggregates/tables.py#L68) [UI2](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/api/rest/nova.py#L684) |
| `openstack aggregate cache image` | mutation | no | Нет действия предзагрузки image cache на hosts aggregate. Update Metadata не выполняет cache image. | [CLI](https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/aggregate.py#L406) [UI1](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/aggregates/tables.py#L162) |

#### Compute services

| Команда | Доступ | UI | Возможность и граница | Источники |
|---|---|---|---|---|
| `openstack compute service delete` | mutation | no | Нет удаления service record. В Compute Host Table есть только enable/disable, evacuation и migration. | [CLI](https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/service.py#L31) [UI1](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/hypervisors/compute/tables.py#L139) [UI2](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/info/tables.py#L121) |
| `openstack compute service list` | read | yes | System Information показывает Nova services; Hypervisors показывает compute hosts. | [CLI](https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/service.py#L78) [UI1](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/info/tables.py#L104) [UI2](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/hypervisors/compute/tables.py#L97) |
| `openstack compute service set` | mutation | partial | Enable/Disable nova-compute; при disable можно указать reason. Нет forced --up/--down; UI actions ограничены nova-compute, а не произвольным binary. | [CLI](https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/service.py#L146) [UI1](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/hypervisors/compute/tables.py#L40) [UI2](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/hypervisors/compute/tables.py#L51) [UI3](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/hypervisors/compute/forms.py#L79) |

#### Console

| Команда | Доступ | UI | Возможность и граница | Источники |
|---|---|---|---|---|
| `openstack console log show` | read | yes | Вкладка Log получает console output; задаётся длина хвоста. | [CLI](https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/console.py#L35) [UI1](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/tabs.py#L87) |
| `openstack console url show` | read | partial | Console открывает VNC, SPICE, RDP, SERIAL или MKS по настройке/AUTO. Тип выбирается конфигурацией Horizon; нет соответствующего CLI выборщика каждого protocol; отдельный xvpvnc не представлен. | [CLI](https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/console.py#L77) [UI1](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/console.py#L27) [UI2](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/tabs.py#L109) [UI3](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/api/nova.py#L197) |

#### Flavors

| Команда | Доступ | UI | Возможность и граница | Источники |
|---|---|---|---|---|
| `openstack flavor create` | mutation | partial | Create Flavor задаёт ID/name, vCPU, RAM, disk/ephemeral/swap, rxtx и project access. В штатной Django-форме нет description; extra specs добавляются после создания; отсутствие выбранных projects означает public. | [CLI](https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/flavor.py#L57) [UI1](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/flavors/workflows.py#L29) [UI2](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/flavors/workflows.py#L192) [UI3](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/flavors/tables.py#L63) |
| `openstack flavor delete` | mutation | yes | Delete Flavor. | [CLI](https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/flavor.py#L213) [UI1](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/flavors/tables.py#L31) [UI2](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/flavors/tables.py#L167) |
| `openstack flavor list` | read | yes | Список flavors с ресурсами, ID, public и extra specs. | [CLI](https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/flavor.py#L252) [UI1](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/flavors/tables.py#L138) |
| `openstack flavor show` | read | partial | Ресурсы/ID/public в таблице; extra specs и project access в соответствующих формах. Нет полной detail-формы, в частности description не выводится. | [CLI](https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/flavor.py#L490) [UI1](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/flavors/tables.py#L138) [UI2](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/flavors/tables.py#L89) |
| `openstack flavor set` | mutation | partial | Update Metadata управляет extra specs; Modify Access добавляет projects. Нет обновления description из CLI --description. | [CLI](https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/flavor.py#L374) [UI1](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/flavors/tables.py#L167) [UI2](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/flavors/workflows.py#L242) [UI3](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/api/rest/nova.py#L641) |
| `openstack flavor unset` | mutation | yes | Удаление extra specs и project access. | [CLI](https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/flavor.py#L539) [UI1](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/flavors/tables.py#L167) [UI2](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/flavors/workflows.py#L269) [UI3](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/api/rest/nova.py#L655) |

#### Legacy os-hosts

| Команда | Доступ | UI | Возможность и граница | Источники |
|---|---|---|---|---|
| `openstack host list` | read | partial | System Information отображает host/service/zone; compute hosts видны в Hypervisors. Это современные service/hypervisor представления; legacy /os-hosts напрямую не вызывается. Команда CLI помечена DEPRECATED. | [CLI](https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/host.py#L25) [UI1](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/info/tables.py#L104) [UI2](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/hypervisors/compute/tables.py#L97) |
| `openstack host set` | mutation | no | Нет управления legacy /os-hosts status/maintenance_mode. Compute service disable/enable — отдельная операция; её нельзя приравнивать к legacy host maintenance. CLI DEPRECATED. | [CLI](https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/host.py#L57) [UI1](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/hypervisors/compute/tables.py#L139) [UI2](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/hypervisors/compute/forms.py#L79) |
| `openstack host show` | read | no | Нет legacy /os-hosts/{host} отчёта о ресурсах по projects. Таблицы Hypervisors/Compute Hosts не эквивалентны legacy per-project host resource report. CLI DEPRECATED. | [CLI](https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/host.py#L115) [UI1](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/hypervisors/tables.py#L21) [UI2](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/hypervisors/views.py#L48) |

#### Hypervisors

| Команда | Доступ | UI | Возможность и граница | Источники |
|---|---|---|---|---|
| `openstack hypervisor list` | read | yes | Таблица Hypervisors показывает hosts, тип, RAM, local storage, число instances. | [CLI](https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/hypervisor.py#L70) [UI1](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/hypervisors/tables.py#L21) |
| `openstack hypervisor show` | read | partial | Строка с ресурсами hypervisor и переход к списку его instances. DetailView получает hypervisor_search(..., servers=True); не полный hypervisor show с CPU info, uptime и всеми атрибутами. | [CLI](https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/hypervisor.py#L154) [UI1](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/hypervisors/tables.py#L21) [UI2](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/hypervisors/views.py#L48) |
| `openstack hypervisor stats show` | read | yes | На странице Hypervisors выводится сводная статистика ресурсов. | [CLI](https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/hypervisor_stats.py#L39) [UI1](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/hypervisors/views.py#L28) [UI2](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/api/nova.py#L817) |

#### Keypairs

| Команда | Доступ | UI | Возможность и граница | Источники |
|---|---|---|---|---|
| `openstack keypair create` | mutation | partial | Create Key Pair генерирует ключ выбранного типа; Import Key Pair принимает public key. Операции для текущего пользователя; нет CLI --user для другого пользователя. | [CLI](https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/keypair.py#L75) [UI1](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/key_pairs/tables.py#L71) [UI2](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/key_pairs/tables.py#L85) [UI3](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/static/dashboard/project/workflow/launch-instance/keypair/create-keypair.controller.js#L71) [UI4](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/key_pairs/forms.py#L39) |
| `openstack keypair delete` | mutation | partial | Delete Key Pair для ключей текущего пользователя. Нет --user для другого пользователя. | [CLI](https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/keypair.py#L210) [UI1](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/key_pairs/tables.py#L28) [UI2](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/key_pairs/tables.py#L133) |
| `openstack keypair list` | read | partial | Список ключей текущего пользователя. Нет --user/--project для административного выбора владельца. | [CLI](https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/keypair.py#L274) [UI1](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/key_pairs/views.py#L37) [UI2](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/key_pairs/tables.py#L120) |
| `openstack keypair show` | read | partial | DetailView показывает ключ, fingerprint/public key. Нет --user для другого пользователя. | [CLI](https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/keypair.py#L386) [UI1](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/key_pairs/views.py#L75) |

#### Server network

| Команда | Доступ | UI | Возможность и граница | Источники |
|---|---|---|---|---|
| `openstack server add fixed ip` | mutation | partial | Attach Interface: network и необязательный fixed IP; создаётся интерфейс. Нет --tag интерфейса. В 7.4.0 CLI тоже использует create_server_interface, а не legacy addFixedIp. | [CLI](https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server.py#L369) [UI1](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/forms.py#L291) [UI2](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/forms.py#L352) [UI3](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/tables.py#L966) |
| `openstack server add floating ip` | mutation | yes | Associate Floating IP связывает адрес с портом/fixed IP instance. При Neutron операция проходит через networking API. | [CLI](https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server.py#L467) [UI1](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/tables.py#L680) |
| `openstack server add port` | mutation | partial | Attach Interface по существующему порту. Нет --tag интерфейса. | [CLI](https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server.py#L563) [UI1](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/forms.py#L291) [UI2](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/forms.py#L352) |
| `openstack server add network` | mutation | partial | Attach Interface по network; порт создаётся при attach. Нет --tag интерфейса. | [CLI](https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server.py#L617) [UI1](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/forms.py#L291) [UI2](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/forms.py#L352) |
| `openstack server add security group` | mutation | yes | Edit Security Groups добавляет SG; при Neutron обновляются security groups портов instance. | [CLI](https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server.py#L672) [UI1](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/tables.py#L500) [UI2](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/workflows/update_instance.py#L26) |
| `openstack server remove fixed ip` | mutation | no | Нет Nova removeFixedIp action по адресу. Detach Interface удаляет интерфейс целиком; редактирование Neutron fixed_ips — другой путь. Не считать автоматической парой к add fixed ip. | [CLI](https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server.py#L3916) [UI1](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/forms.py#L376) [UI2](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/tables.py#L1295) |
| `openstack server remove floating ip` | mutation | yes | Disassociate Floating IP. | [CLI](https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server.py#L3944) [UI1](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/tables.py#L713) [UI2](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/forms.py#L417) |
| `openstack server remove port` | mutation | yes | Detach Interface по выбранному port. | [CLI](https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server.py#L3977) [UI1](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/forms.py#L376) [UI2](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/forms.py#L402) |
| `openstack server remove network` | mutation | partial | Можно отсоединить порты выбранной сети через Detach Interface. CLI удаляет все interfaces этой network одним вызовом команды; UI выбирает конкретный port, для нескольких нужно повторить. | [CLI](https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server.py#L4016) [UI1](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/forms.py#L376) |
| `openstack server remove security group` | mutation | yes | Edit Security Groups снимает SG с instance/портов. | [CLI](https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server.py#L4056) [UI1](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/tables.py#L500) [UI2](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/workflows/update_instance.py#L26) |

#### Server volumes

| Команда | Доступ | UI | Возможность и граница | Источники |
|---|---|---|---|---|
| `openstack server add volume` | mutation | partial | Attach Volume подключает выбранный том. Нет tag/delete-on-termination для attachment; device поле скрыто. | [CLI](https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server.py#L741) [UI1](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/forms.py#L173) [UI2](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/forms.py#L208) [UI3](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/tables.py#L933) |
| `openstack server remove volume` | mutation | yes | Detach Volume. | [CLI](https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server.py#L4125) [UI1](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/forms.py#L235) [UI2](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/forms.py#L267) |
| `openstack server volume list` | read | partial | Overview перечисляет attached volumes и device; Detach Volume загружает attachments. Не полный вывод attachment metadata/tag/delete_on_termination из современных API. | [CLI](https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server_volume.py#L25) [UI1](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/templates/instances/_detail_overview.html#L158) [UI2](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/forms.py#L235) |
| `openstack server volume set` | mutation | no | Нет изменения delete_on_termination существующего attachment. Флаг при boot-volume создании не является редактированием существующего attachment. | [CLI](https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server_volume.py#L81) [UI1](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/tables.py#L933) [UI2](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/forms.py#L173) |
| `openstack server volume update` | mutation | no | Нет изменения delete_on_termination существующего attachment. volume update — deprecated alias server volume set. | [CLI](https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server_volume.py#L146) [UI1](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/tables.py#L933) [UI2](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/forms.py#L173) |

#### Server lifecycle

| Команда | Доступ | UI | Возможность и граница | Источники |
|---|---|---|---|---|
| `openstack server create` | mutation | partial | Launch Instance: источники image/snapshot/volume, flavor, AZ, networks/ports, SG, keypair, user data, config drive, metadata, hints/group и число instances. REST whitelist не принимает CLI hostname, tags, trusted-image-cert, host/hypervisor-hostname как отдельные параметры; нет полного произвольного block-device CLI. | [CLI](https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server.py#L1107) [UI1](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/static/dashboard/project/workflow/launch-instance/launch-instance-model.service.js#L176) [UI2](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/api/rest/nova.py#L315) [UI3](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/tables.py#L418) |
| `openstack server delete` | mutation | partial | Delete Instance; в admin доступны экземпляры разных projects. Нет явного force-delete режима (--force). | [CLI](https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server.py#L2204) [UI1](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/tables.py#L86) [UI2](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/instances/tables.py#L193) |
| `openstack server lock` | mutation | partial | Lock Instance. Нет reason из CLI --reason. | [CLI](https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server.py#L3100) [UI1](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/tables.py#L869) |
| `openstack server pause` | mutation | yes | Pause Instance. | [CLI](https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server.py#L3340) [UI1](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/tables.py#L224) [UI2](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/tables.py#L279) |
| `openstack server reboot` | mutation | yes | Soft Reboot и Hard Reboot. --wait CLI не сопоставляется отдельной кнопке; UI обновляет состояние асинхронно. | [CLI](https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server.py#L3363) [UI1](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/tables.py#L117) [UI2](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/tables.py#L152) |
| `openstack server rebuild` | mutation | partial | Rebuild: image, password, disk partition и description. Нет preserve-ephemeral, key replacement, user-data replacement, trusted cert, hostname и reimage-boot-volume опций. | [CLI](https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server.py#L3423) [UI1](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/forms.py#L39) [UI2](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/forms.py#L104) |
| `openstack server rescue` | mutation | yes | Rescue Instance с image/password. | [CLI](https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server.py#L4167) [UI1](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/forms.py#L468) [UI2](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/tables.py#L180) |
| `openstack server resize` | mutation | yes | Resize Instance выбирает новый flavor; confirm/revert доступны отдельно. | [CLI](https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server.py#L4218) [UI1](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/tables.py#L578) [UI2](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/workflows/resize_instance.py#L104) |
| `openstack server restore` | mutation | no | Нет восстановления soft-deleted VM. Rebuild/Unshelve не являются server restore. | [CLI](https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server.py#L4413) [UI1](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/tables.py#L1295) [UI2](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/instances/tables.py#L196) |
| `openstack server resume` | mutation | yes | Resume через Toggle Suspend для SUSPENDED instance. | [CLI](https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server.py#L4436) [UI1](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/tables.py#L288) [UI2](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/tables.py#L343) |
| `openstack server shelve` | mutation | partial | Shelve Instance. Нет самостоятельного --offload режима (shelveOffload). | [CLI](https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server.py#L4620) [UI1](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/tables.py#L352) [UI2](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/tables.py#L409) [UI3](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/api/nova.py#L570) |
| `openstack server start` | mutation | yes | Start Instance. | [CLI](https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server.py#L4957) [UI1](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/tables.py#L807) |
| `openstack server stop` | mutation | yes | Shut Off/Stop Instance. | [CLI](https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server.py#L4992) [UI1](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/tables.py#L836) [UI2](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/instances/tables.py#L196) |
| `openstack server suspend` | mutation | yes | Suspend Instance. | [CLI](https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server.py#L5026) [UI1](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/tables.py#L288) [UI2](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/tables.py#L343) |
| `openstack server unlock` | mutation | yes | Unlock Instance. | [CLI](https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server.py#L5049) [UI1](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/tables.py#L901) |
| `openstack server unpause` | mutation | yes | Unpause через Toggle Pause для PAUSED instance. | [CLI](https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server.py#L5072) [UI1](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/tables.py#L224) [UI2](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/tables.py#L279) |
| `openstack server unrescue` | mutation | yes | Unrescue Instance. | [CLI](https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server.py#L5095) [UI1](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/tables.py#L195) |
| `openstack server unshelve` | mutation | partial | Unshelve доступен для SHELVED_OFFLOADED. Нет host/AZ/no-AZ параметров; состояние SHELVED не выбирается UI как unshelve. | [CLI](https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server.py#L5211) [UI1](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/tables.py#L386) [UI2](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/api/nova.py#L575) |

#### Server diagnostics

| Команда | Доступ | UI | Возможность и граница | Источники |
|---|---|---|---|---|
| `openstack server dump create` | mutation | no | Нет Trigger Crash Dump действия. Snapshot и console log не заменяют guest crash dump. | [CLI](https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server.py#L2175) [UI1](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/tables.py#L1295) [UI2](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/instances/tables.py#L196) |

#### Server migration

| Команда | Доступ | UI | Возможность и граница | Источники |
|---|---|---|---|---|
| `openstack server evacuate` | mutation | partial | Evacuate Host вызывает evacuate для экземпляров выбранного хоста; target/shared-storage доступны. UI действует на host, не на выбранную отдельную VM; нет CLI --password. | [CLI](https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server.py#L3798) [UI1](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/hypervisors/compute/tables.py#L25) [UI2](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/hypervisors/compute/forms.py#L23) [UI3](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/api/nova.py#L827) |
| `openstack server migrate` | mutation | partial | Admin: cold Migrate и Live Migrate; live выбирает host, block-migration/disk-over-commit. Cold migrate не принимает target host; в API adapter вызов без host. | [CLI](https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server.py#L3158) [UI1](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/instances/tables.py#L49) [UI2](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/instances/forms.py#L28) [UI3](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/api/nova.py#L605) |

#### Server inventory

| Команда | Доступ | UI | Возможность и граница | Источники |
|---|---|---|---|---|
| `openstack server list` | read | partial | Списки instances в Project и Admin. Нет режима CLI --deleted для инвентаризации удалённых серверов; остальные CLI фильтры шире UI. | [CLI](https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server.py#L2306) [UI1](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/tables.py#L1232) [UI2](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/instances/tables.py#L129) |
| `openstack server show` | read | partial | Overview instance: основные свойства, IP, security groups, metadata, attached volumes. Нет CLI --diagnostics и --topology (CPU/NUMA topology); network topology является другим экраном. | [CLI](https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server.py#L4729) [UI1](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/templates/instances/_detail_overview.html#L1) [UI2](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/tabs.py#L32) |

#### Resize/migrate aliases

| Команда | Доступ | UI | Возможность и граница | Источники |
|---|---|---|---|---|
| `openstack server migrate confirm` | mutation | yes | Confirm Resize/Migrate подтверждает операцию в VERIFY_RESIZE. migrate confirm — deprecated alias; все варианты наследуют тот же CLI ResizeConfirm. | [CLI](https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server.py#L4343) [UI1](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/tables.py#L603) [UI2](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/instances/tables.py#L196) |
| `openstack server migrate revert` | mutation | yes | Revert Resize/Migrate откатывает операцию в VERIFY_RESIZE. migrate revert — deprecated alias; все варианты наследуют тот же CLI ResizeRevert. | [CLI](https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server.py#L4391) [UI1](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/tables.py#L623) [UI2](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/instances/tables.py#L196) |
| `openstack server migration confirm` | mutation | yes | Confirm Resize/Migrate подтверждает операцию в VERIFY_RESIZE. | [CLI](https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server.py#L4356) [UI1](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/tables.py#L603) [UI2](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/instances/tables.py#L196) |
| `openstack server migration revert` | mutation | yes | Revert Resize/Migrate откатывает операцию в VERIFY_RESIZE. | [CLI](https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server.py#L4404) [UI1](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/tables.py#L623) [UI2](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/instances/tables.py#L196) |
| `openstack server resize confirm` | mutation | yes | Confirm Resize/Migrate подтверждает операцию в VERIFY_RESIZE. | [CLI](https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server.py#L4318) [UI1](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/tables.py#L603) [UI2](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/instances/tables.py#L196) |
| `openstack server resize revert` | mutation | yes | Revert Resize/Migrate откатывает операцию в VERIFY_RESIZE. | [CLI](https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server.py#L4365) [UI1](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/tables.py#L623) [UI2](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/instances/tables.py#L196) |

#### Server attributes

| Команда | Доступ | UI | Возможность и граница | Источники |
|---|---|---|---|---|
| `openstack server set` | mutation | partial | Edit Instance меняет name/description; Update Metadata меняет properties. Нет reset-state, root-password/password clear, server tags и hostname. | [CLI](https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server.py#L4459) [UI1](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/workflows/update_instance.py#L70) [UI2](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/tables.py#L733) [UI3](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/api/rest/nova.py#L475) |
| `openstack server unset` | mutation | partial | Удаление properties через Update Metadata; очистка description через Edit. Нет удаления server tags/all-tags. | [CLI](https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server.py#L5115) [UI1](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/api/rest/nova.py#L491) [UI2](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/workflows/update_instance.py#L70) [UI3](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/api/nova.py#L599) |

#### Client session

| Команда | Доступ | UI | Возможность и граница | Источники |
|---|---|---|---|---|
| `openstack server ssh` | client | no | Нет открытия локального SSH-клиента к instance с CLI аргументами. Browser console использует console API и не заменяет SSH. | [CLI](https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server.py#L4796) [UI1](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/tables.py#L540) [UI2](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/console.py#L27) |

#### Server snapshots/backups

| Команда | Доступ | UI | Возможность и граница | Источники |
|---|---|---|---|---|
| `openstack server backup create` | mutation | no | Нет Nova server backup с type/rotation. Create Snapshot и Cinder volume backup — другие операции. | [CLI](https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server_backup.py#L27) [UI1](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/tables.py#L1295) [UI2](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/images/snapshots/forms.py#L30) |
| `openstack server image create` | mutation | partial | Create Snapshot создаёт image из server с именем. Форма не принимает --property при snapshot; metadata образа можно редактировать отдельно. | [CLI](https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server_image.py#L32) [UI1](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/tables.py#L527) [UI2](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/images/snapshots/forms.py#L30) |

#### Server events

| Команда | Доступ | UI | Возможность и граница | Источники |
|---|---|---|---|---|
| `openstack server event list` | read | partial | Вкладка Action Log показывает request ID, action, time, user, message. Экран открывается для существующего instance; нет CLI обращения к deleted-server UUID и date/pagination режимов. | [CLI](https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server_event.py#L105) [UI1](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/tabs.py#L140) [UI2](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/audit_tables.py#L22) |
| `openstack server event show` | read | no | Нет detail-view отдельного instance action по request ID с вложенными events. Action Log — только плоская таблица; request_id не является ссылкой. | [CLI](https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server_event.py#L254) [UI1](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/audit_tables.py#L48) [UI2](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/tabs.py#L140) [UI3](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/api/nova.py#L1029) |

#### Server groups

| Команда | Доступ | UI | Возможность и граница | Источники |
|---|---|---|---|---|
| `openstack server group create` | mutation | partial | Create Server Group с name/policy, включая soft policies при поддержке. Нет CLI --rule max_server_per_host и иных rule полей. | [CLI](https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server_group.py#L55) [UI1](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/static/app/core/server_groups/actions/workflow/workflow.service.js#L40) [UI2](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/static/app/core/server_groups/actions/actions.module.js#L67) |
| `openstack server group delete` | mutation | yes | Delete Server Group. | [CLI](https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server_group.py#L142) [UI1](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/static/app/core/server_groups/actions/actions.module.js#L47) [UI2](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/api/rest/nova.py#L454) |
| `openstack server group list` | read | partial | Панель Server Groups показывает группы текущего проекта. Нет --all-projects: adapter вызывает server_groups.list() без all_projects. | [CLI](https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server_group.py#L177) [UI1](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/static/app/core/server_groups/server-groups.module.js#L44) [UI2](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/api/rest/nova.py#L424) [UI3](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/api/nova.py#L924) |
| `openstack server group show` | read | partial | Details: id/name/policy, project/user при поддержке; members со ссылками. Не показывает rules вроде max_server_per_host. | [CLI](https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server_group.py#L254) [UI1](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/static/app/core/server_groups/details/overview.controller.js#L40) |

#### Server migration records

| Команда | Доступ | UI | Возможность и граница | Источники |
|---|---|---|---|---|
| `openstack server migration abort` | mutation | no | Нет abort активной migration. Confirm/Revert Resize/Migrate относится к другой фазе и не заменяет это действие. | [CLI](https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server_migration.py#L386) [UI1](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/instances/tables.py#L196) [UI2](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/tables.py#L603) [UI3](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/tabs.py#L160) |
| `openstack server migration force complete` | mutation | no | Нет force-complete активной migration. Confirm/Revert Resize/Migrate относится к другой фазе и не заменяет это действие. | [CLI](https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server_migration.py#L453) [UI1](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/instances/tables.py#L196) [UI2](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/tables.py#L603) [UI3](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/tabs.py#L160) |
| `openstack server migration list` | read | no | Нет списка migration records с IDs/status/source/destination. Confirm/Revert Resize/Migrate относится к другой фазе и не заменяет это действие. | [CLI](https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server_migration.py#L27) [UI1](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/instances/tables.py#L196) [UI2](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/tables.py#L603) [UI3](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/tabs.py#L160) |
| `openstack server migration show` | read | no | Нет detail-view migration record по ID. Confirm/Revert Resize/Migrate относится к другой фазе и не заменяет это действие. | [CLI](https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server_migration.py#L269) [UI1](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/instances/tables.py#L196) [UI2](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/tables.py#L603) [UI3](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/tabs.py#L160) |

#### Usage

| Команда | Доступ | UI | Возможность и граница | Источники |
|---|---|---|---|---|
| `openstack usage list` | read | yes | Admin Overview: usage всех projects за выбранный период, CSV. | [CLI](https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/usage.py#L108) [UI1](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/overview/views.py#L46) [UI2](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/usage/base.py#L154) |
| `openstack usage show` | read | yes | Project Overview и Identity Project Usage: usage проекта за период, CSV. | [CLI](https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/usage.py#L209) [UI1](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/overview/views.py#L56) [UI2](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/identity/projects/views.py#L141) [UI3](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/usage/base.py#L161) |


| Команда | Возможность | Horizon | Пояснение / ограничение | Наш слой | Источники |
| --- | --- | --- | --- | --- | --- |
| `openstack aggregate add host` | Manage Hosts добавляет выбранный compute-host в aggregate. | Есть | Основная операция представлена; действуют права и допустимое состояние ресурса. | — | [CLI][S0008]; [UI1][S0009], [UI2][S0010] |
| `openstack aggregate cache image` | Нет действия предзагрузки image cache на hosts aggregate. | Нет | Update Metadata не выполняет cache image. | — | [CLI][S0011]; [UI][S0012] |
| `openstack aggregate create` | Create Host Aggregate: имя, AZ, выбор hosts. | Частично | --property задаётся отдельным Update Metadata после создания. | — | [CLI][S0013]; [UI1][S0014], [UI2][S0015] |
| `openstack aggregate delete` | Удаление aggregate. | Есть | Основная операция представлена; действуют права и допустимое состояние ресурса. | — | [CLI][S0016]; [UI1][S0017], [UI2][S0012] |
| `openstack aggregate list` | Таблица name, AZ, hosts и metadata. | Есть | Основная операция представлена; действуют права и допустимое состояние ресурса. | — | [CLI][S0018]; [UI][S0019] |
| `openstack aggregate remove host` | Manage Hosts удаляет membership хоста. | Есть | Основная операция представлена; действуют права и допустимое состояние ресурса. | — | [CLI][S0020]; [UI1][S0021], [UI2][S0010] |
| `openstack aggregate set` | Edit Aggregate меняет имя/AZ; Update Metadata добавляет/меняет/удаляет свойства. | Есть | Выполняется через отдельные формы; удаление всех свойств — выбор всех в редакторе. | — | [CLI][S0022]; [UI1][S0023], [UI2][S0015], [UI3][S0024] |
| `openstack aggregate show` | Данные конкретного aggregate доступны в строке таблицы: имя, AZ, hosts, metadata. | Есть | Отдельная detail-страница не требуется для этого отображения. | — | [CLI][S0025]; [UI][S0019] |
| `openstack aggregate unset` | Update Metadata удаляет выбранные свойства aggregate. | Есть | Основная операция представлена; действуют права и допустимое состояние ресурса. | — | [CLI][S0026]; [UI1][S0015], [UI2][S0024] |
| `openstack compute agent create` | Нет панели управления Nova guest-agent build records. | Нет | Это compute agents; Neutron agents и nova-compute services — другие ресурсы. | — | [CLI][S0027]; [UI1][S0002], [UI2][S0028] |
| `openstack compute agent delete` | Нет панели управления Nova guest-agent build records. | Нет | Это compute agents; Neutron agents и nova-compute services — другие ресурсы. | — | [CLI][S0029]; [UI1][S0002], [UI2][S0028] |
| `openstack compute agent list` | Нет панели управления Nova guest-agent build records. | Нет | Это compute agents; Neutron agents и nova-compute services — другие ресурсы. | — | [CLI][S0030]; [UI1][S0002], [UI2][S0028] |
| `openstack compute agent set` | Нет панели управления Nova guest-agent build records. | Нет | Это compute agents; Neutron agents и nova-compute services — другие ресурсы. | — | [CLI][S0031]; [UI1][S0002], [UI2][S0028] |
| `openstack compute service delete` | Нет удаления service record. | Нет | В Compute Host Table есть только enable/disable, evacuation и migration. | N1 | [CLI][S0032]; [UI1][S0033], [UI2][S0034] |
| `openstack compute service list` | System Information показывает Nova services; Hypervisors показывает compute hosts. | Есть | Основная операция представлена; действуют права и допустимое состояние ресурса. | N1 | [CLI][S0035]; [UI1][S0002], [UI2][S0028] |
| `openstack compute service set` | Enable/Disable nova-compute; при disable можно указать reason. | Частично | Нет forced --up/--down; UI actions ограничены nova-compute, а не произвольным binary. | N1 | [CLI][S0036]; [UI1][S0037], [UI2][S0038], [UI3][S0039] |
| `openstack console log show` | Вкладка Log получает console output; задаётся длина хвоста. | Есть | Основная операция представлена; действуют права и допустимое состояние ресурса. | — | [CLI][S0040]; [UI][S0041] |
| `openstack console url show` | Console открывает VNC, SPICE, RDP, SERIAL или MKS по настройке/AUTO. | Частично | Тип выбирается конфигурацией Horizon; нет соответствующего CLI выборщика каждого protocol; отдельный xvpvnc не представлен. | — | [CLI][S0042]; [UI1][S0043], [UI2][S0044], [UI3][S0045] |
| `openstack flavor create` | Create Flavor задаёт ID/name, vCPU, RAM, disk/ephemeral/swap, rxtx и project access. | Частично | В штатной Django-форме нет description; extra specs добавляются после создания; отсутствие выбранных projects означает public. | — | [CLI][S0046]; [UI1][S0047], [UI2][S0048], [UI3][S0049] |
| `openstack flavor delete` | Delete Flavor. | Есть | Основная операция представлена; действуют права и допустимое состояние ресурса. | — | [CLI][S0050]; [UI1][S0051], [UI2][S0052] |
| `openstack flavor list` | Список flavors с ресурсами, ID, public и extra specs. | Есть | Основная операция представлена; действуют права и допустимое состояние ресурса. | — | [CLI][S0053]; [UI][S0054] |
| `openstack flavor set` | Update Metadata управляет extra specs; Modify Access добавляет projects. | Частично | Нет обновления description из CLI --description. | — | [CLI][S0055]; [UI1][S0052], [UI2][S0056], [UI3][S0057] |
| `openstack flavor show` | Ресурсы/ID/public в таблице; extra specs и project access в соответствующих формах. | Частично | Нет полной detail-формы, в частности description не выводится. | — | [CLI][S0058]; [UI1][S0054], [UI2][S0059] |
| `openstack flavor unset` | Удаление extra specs и project access. | Есть | Основная операция представлена; действуют права и допустимое состояние ресурса. | — | [CLI][S0060]; [UI1][S0052], [UI2][S0061], [UI3][S0062] |
| `openstack host list` | System Information отображает host/service/zone; compute hosts видны в Hypervisors. | Частично | Это современные service/hypervisor представления; legacy /os-hosts напрямую не вызывается. Команда CLI помечена DEPRECATED. | — | [CLI][S0063]; [UI1][S0002], [UI2][S0028] |
| `openstack host set` | Нет управления legacy /os-hosts status/maintenance_mode. | Нет | Compute service disable/enable — отдельная операция; её нельзя приравнивать к legacy host maintenance. CLI DEPRECATED. | — | [CLI][S0064]; [UI1][S0033], [UI2][S0039] |
| `openstack host show` | Нет legacy /os-hosts/{host} отчёта о ресурсах по projects. | Нет | Таблицы Hypervisors/Compute Hosts не эквивалентны legacy per-project host resource report. CLI DEPRECATED. | — | [CLI][S0065]; [UI1][S0066], [UI2][S0067] |
| `openstack hypervisor list` | Таблица Hypervisors показывает hosts, тип, RAM, local storage, число instances. | Есть | Основная операция представлена; действуют права и допустимое состояние ресурса. | — | [CLI][S0068]; [UI][S0066] |
| `openstack hypervisor show` | Строка с ресурсами hypervisor и переход к списку его instances. | Частично | DetailView получает hypervisor_search(..., servers=True); не полный hypervisor show с CPU info, uptime и всеми атрибутами. | — | [CLI][S0069]; [UI1][S0066], [UI2][S0067] |
| `openstack hypervisor stats show` | На странице Hypervisors выводится сводная статистика ресурсов. | Есть | Основная операция представлена; действуют права и допустимое состояние ресурса. | — | [CLI][S0070]; [UI1][S0071], [UI2][S0072] |
| `openstack keypair create` | Create Key Pair генерирует ключ выбранного типа; Import Key Pair принимает public key. | Частично | Операции для текущего пользователя; нет CLI --user для другого пользователя. | — | [CLI][S0073]; [UI1][S0074], [UI2][S0075], [UI3][S0076], [UI4][S0077] |
| `openstack keypair delete` | Delete Key Pair для ключей текущего пользователя. | Частично | Нет --user для другого пользователя. | — | [CLI][S0078]; [UI1][S0079], [UI2][S0080] |
| `openstack keypair list` | Список ключей текущего пользователя. | Частично | Нет --user/--project для административного выбора владельца. | — | [CLI][S0081]; [UI1][S0082], [UI2][S0083] |
| `openstack keypair show` | DetailView показывает ключ, fingerprint/public key. | Частично | Нет --user для другого пользователя. | — | [CLI][S0084]; [UI][S0085] |
| `openstack server add fixed ip` | Attach Interface: network и необязательный fixed IP; создаётся интерфейс. | Частично | Нет --tag интерфейса. В 7.4.0 CLI тоже использует create_server_interface, а не legacy addFixedIp. | — | [CLI][S0086]; [UI1][S0087], [UI2][S0088], [UI3][S0089] |
| `openstack server add floating ip` | Associate Floating IP связывает адрес с портом/fixed IP instance. | Есть | При Neutron операция проходит через networking API. | — | [CLI][S0090]; [UI][S0091] |
| `openstack server add network` | Attach Interface по network; порт создаётся при attach. | Частично | Нет --tag интерфейса. | — | [CLI][S0092]; [UI1][S0087], [UI2][S0088] |
| `openstack server add port` | Attach Interface по существующему порту. | Частично | Нет --tag интерфейса. | — | [CLI][S0093]; [UI1][S0087], [UI2][S0088] |
| `openstack server add security group` | Edit Security Groups добавляет SG; при Neutron обновляются security groups портов instance. | Есть | Основная операция представлена; действуют права и допустимое состояние ресурса. | — | [CLI][S0094]; [UI1][S0095], [UI2][S0096] |
| `openstack server add volume` | Attach Volume подключает выбранный том. | Частично | Нет tag/delete-on-termination для attachment; device поле скрыто. | — | [CLI][S0097]; [UI1][S0098], [UI2][S0099], [UI3][S0100] |
| `openstack server backup create` | Нет Nova server backup с type/rotation. | Нет | Create Snapshot и Cinder volume backup — другие операции. | — | [CLI][S0101]; [UI1][S0102], [UI2][S0103] |
| `openstack server create` | Launch Instance: источники image/snapshot/volume, flavor, AZ, networks/ports, SG, keypair, user data, config drive, metadata, hints/group и число instances. | Частично | REST whitelist не принимает CLI hostname, tags, trusted-image-cert, host/hypervisor-hostname как отдельные параметры; нет полного произвольного block-device CLI. | — | [CLI][S0104]; [UI1][S0105], [UI2][S0106], [UI3][S0107] |
| `openstack server delete` | Delete Instance; в admin доступны экземпляры разных projects. | Частично | Нет явного force-delete режима (--force). | — | [CLI][S0108]; [UI1][S0109], [UI2][S0110] |
| `openstack server dump create` | Нет Trigger Crash Dump действия. | Нет | Snapshot и console log не заменяют guest crash dump. | — | [CLI][S0111]; [UI1][S0102], [UI2][S0112] |
| `openstack server evacuate` | Evacuate Host вызывает evacuate для экземпляров выбранного хоста; target/shared-storage доступны. | Частично | UI действует на host, не на выбранную отдельную VM; нет CLI --password. | N1 | [CLI][S0113]; [UI1][S0114], [UI2][S0115], [UI3][S0116] |
| `openstack server event list` | Вкладка Action Log показывает request ID, action, time, user, message. | Частично | Экран открывается для существующего instance; нет CLI обращения к deleted-server UUID и date/pagination режимов. | — | [CLI][S0117]; [UI1][S0118], [UI2][S0119] |
| `openstack server event show` | Нет detail-view отдельного instance action по request ID с вложенными events. | Нет | Action Log — только плоская таблица; request_id не является ссылкой. | — | [CLI][S0120]; [UI1][S0121], [UI2][S0118], [UI3][S0122] |
| `openstack server group create` | Create Server Group с name/policy, включая soft policies при поддержке. | Частично | Нет CLI --rule max_server_per_host и иных rule полей. | — | [CLI][S0123]; [UI1][S0124], [UI2][S0125] |
| `openstack server group delete` | Delete Server Group. | Есть | Основная операция представлена; действуют права и допустимое состояние ресурса. | — | [CLI][S0126]; [UI1][S0127], [UI2][S0128] |
| `openstack server group list` | Панель Server Groups показывает группы текущего проекта. | Частично | Нет --all-projects: adapter вызывает server_groups.list() без all_projects. | — | [CLI][S0129]; [UI1][S0130], [UI2][S0131], [UI3][S0132] |
| `openstack server group show` | Details: id/name/policy, project/user при поддержке; members со ссылками. | Частично | Не показывает rules вроде max_server_per_host. | — | [CLI][S0133]; [UI][S0134] |
| `openstack server image create` | Create Snapshot создаёт image из server с именем. | Частично | Форма не принимает --property при snapshot; metadata образа можно редактировать отдельно. | — | [CLI][S0135]; [UI1][S0136], [UI2][S0103] |
| `openstack server list` | Списки instances в Project и Admin. | Частично | Нет режима CLI --deleted для инвентаризации удалённых серверов; остальные CLI фильтры шире UI. | — | [CLI][S0137]; [UI1][S0138], [UI2][S0139] |
| `openstack server lock` | Lock Instance. | Частично | Нет reason из CLI --reason. | — | [CLI][S0140]; [UI][S0141] |
| `openstack server migrate` | Admin: cold Migrate и Live Migrate; live выбирает host, block-migration/disk-over-commit. | Частично | Cold migrate не принимает target host; в API adapter вызов без host. | N1 | [CLI][S0142]; [UI1][S0143], [UI2][S0144], [UI3][S0145] |
| `openstack server migrate confirm` | Confirm Resize/Migrate подтверждает операцию в VERIFY_RESIZE. | Есть | migrate confirm — deprecated alias; все варианты наследуют тот же CLI ResizeConfirm. | N1 | [CLI][S0146]; [UI1][S0147], [UI2][S0112] |
| `openstack server migrate revert` | Revert Resize/Migrate откатывает операцию в VERIFY_RESIZE. | Есть | migrate revert — deprecated alias; все варианты наследуют тот же CLI ResizeRevert. | N1 | [CLI][S0148]; [UI1][S0149], [UI2][S0112] |
| `openstack server migration abort` | Нет abort активной migration. | Нет | Confirm/Revert Resize/Migrate относится к другой фазе и не заменяет это действие. | N1 | [CLI][S0150]; [UI1][S0112], [UI2][S0147], [UI3][S0151] |
| `openstack server migration confirm` | Confirm Resize/Migrate подтверждает операцию в VERIFY_RESIZE. | Есть | Основная операция представлена; действуют права и допустимое состояние ресурса. | N1 | [CLI][S0152]; [UI1][S0147], [UI2][S0112] |
| `openstack server migration force complete` | Нет force-complete активной migration. | Нет | Confirm/Revert Resize/Migrate относится к другой фазе и не заменяет это действие. | N1 | [CLI][S0153]; [UI1][S0112], [UI2][S0147], [UI3][S0151] |
| `openstack server migration list` | Нет списка migration records с IDs/status/source/destination. | Нет | Confirm/Revert Resize/Migrate относится к другой фазе и не заменяет это действие. | N1 | [CLI][S0154]; [UI1][S0112], [UI2][S0147], [UI3][S0151] |
| `openstack server migration revert` | Revert Resize/Migrate откатывает операцию в VERIFY_RESIZE. | Есть | Основная операция представлена; действуют права и допустимое состояние ресурса. | N1 | [CLI][S0155]; [UI1][S0149], [UI2][S0112] |
| `openstack server migration show` | Нет detail-view migration record по ID. | Нет | Confirm/Revert Resize/Migrate относится к другой фазе и не заменяет это действие. | N1 | [CLI][S0156]; [UI1][S0112], [UI2][S0147], [UI3][S0151] |
| `openstack server pause` | Pause Instance. | Есть | Основная операция представлена; действуют права и допустимое состояние ресурса. | — | [CLI][S0157]; [UI1][S0158], [UI2][S0159] |
| `openstack server reboot` | Soft Reboot и Hard Reboot. | Есть | --wait CLI не сопоставляется отдельной кнопке; UI обновляет состояние асинхронно. | — | [CLI][S0160]; [UI1][S0161], [UI2][S0162] |
| `openstack server rebuild` | Rebuild: image, password, disk partition и description. | Частично | Нет preserve-ephemeral, key replacement, user-data replacement, trusted cert, hostname и reimage-boot-volume опций. | — | [CLI][S0163]; [UI1][S0164], [UI2][S0165] |
| `openstack server remove fixed ip` | Нет Nova removeFixedIp action по адресу. | Нет | Detach Interface удаляет интерфейс целиком; редактирование Neutron fixed_ips — другой путь. Не считать автоматической парой к add fixed ip. | — | [CLI][S0166]; [UI1][S0167], [UI2][S0102] |
| `openstack server remove floating ip` | Disassociate Floating IP. | Есть | Основная операция представлена; действуют права и допустимое состояние ресурса. | — | [CLI][S0168]; [UI1][S0169], [UI2][S0170] |
| `openstack server remove network` | Можно отсоединить порты выбранной сети через Detach Interface. | Частично | CLI удаляет все interfaces этой network одним вызовом команды; UI выбирает конкретный port, для нескольких нужно повторить. | — | [CLI][S0171]; [UI][S0167] |
| `openstack server remove port` | Detach Interface по выбранному port. | Есть | Основная операция представлена; действуют права и допустимое состояние ресурса. | — | [CLI][S0172]; [UI1][S0167], [UI2][S0173] |
| `openstack server remove security group` | Edit Security Groups снимает SG с instance/портов. | Есть | Основная операция представлена; действуют права и допустимое состояние ресурса. | — | [CLI][S0174]; [UI1][S0095], [UI2][S0096] |
| `openstack server remove volume` | Detach Volume. | Есть | Основная операция представлена; действуют права и допустимое состояние ресурса. | — | [CLI][S0175]; [UI1][S0176], [UI2][S0177] |
| `openstack server rescue` | Rescue Instance с image/password. | Есть | Основная операция представлена; действуют права и допустимое состояние ресурса. | — | [CLI][S0178]; [UI1][S0179], [UI2][S0180] |
| `openstack server resize` | Resize Instance выбирает новый flavor; confirm/revert доступны отдельно. | Есть | Основная операция представлена; действуют права и допустимое состояние ресурса. | — | [CLI][S0181]; [UI1][S0182], [UI2][S0183] |
| `openstack server resize confirm` | Confirm Resize/Migrate подтверждает операцию в VERIFY_RESIZE. | Есть | Основная операция представлена; действуют права и допустимое состояние ресурса. | — | [CLI][S0184]; [UI1][S0147], [UI2][S0112] |
| `openstack server resize revert` | Revert Resize/Migrate откатывает операцию в VERIFY_RESIZE. | Есть | Основная операция представлена; действуют права и допустимое состояние ресурса. | — | [CLI][S0185]; [UI1][S0149], [UI2][S0112] |
| `openstack server restore` | Нет восстановления soft-deleted VM. | Нет | Rebuild/Unshelve не являются server restore. | — | [CLI][S0186]; [UI1][S0102], [UI2][S0112] |
| `openstack server resume` | Resume через Toggle Suspend для SUSPENDED instance. | Есть | Основная операция представлена; действуют права и допустимое состояние ресурса. | — | [CLI][S0187]; [UI1][S0188], [UI2][S0189] |
| `openstack server set` | Edit Instance меняет name/description; Update Metadata меняет properties. | Частично | Нет reset-state, root-password/password clear, server tags и hostname. | — | [CLI][S0190]; [UI1][S0191], [UI2][S0192], [UI3][S0193] |
| `openstack server shelve` | Shelve Instance. | Частично | Нет самостоятельного --offload режима (shelveOffload). | — | [CLI][S0194]; [UI1][S0195], [UI2][S0196], [UI3][S0197] |
| `openstack server show` | Overview instance: основные свойства, IP, security groups, metadata, attached volumes. | Частично | Нет CLI --diagnostics и --topology (CPU/NUMA topology); network topology является другим экраном. | — | [CLI][S0198]; [UI1][S0199], [UI2][S0200] |
| `openstack server ssh` | Нет открытия локального SSH-клиента к instance с CLI аргументами. | Нет | Browser console использует console API и не заменяет SSH. | — | [CLI][S0201]; [UI1][S0202], [UI2][S0043] |
| `openstack server start` | Start Instance. | Есть | Основная операция представлена; действуют права и допустимое состояние ресурса. | — | [CLI][S0203]; [UI][S0204] |
| `openstack server stop` | Shut Off/Stop Instance. | Есть | Основная операция представлена; действуют права и допустимое состояние ресурса. | — | [CLI][S0205]; [UI1][S0206], [UI2][S0112] |
| `openstack server suspend` | Suspend Instance. | Есть | Основная операция представлена; действуют права и допустимое состояние ресурса. | — | [CLI][S0207]; [UI1][S0188], [UI2][S0189] |
| `openstack server unlock` | Unlock Instance. | Есть | Основная операция представлена; действуют права и допустимое состояние ресурса. | — | [CLI][S0208]; [UI][S0209] |
| `openstack server unpause` | Unpause через Toggle Pause для PAUSED instance. | Есть | Основная операция представлена; действуют права и допустимое состояние ресурса. | — | [CLI][S0210]; [UI1][S0158], [UI2][S0159] |
| `openstack server unrescue` | Unrescue Instance. | Есть | Основная операция представлена; действуют права и допустимое состояние ресурса. | — | [CLI][S0211]; [UI][S0212] |
| `openstack server unset` | Удаление properties через Update Metadata; очистка description через Edit. | Частично | Нет удаления server tags/all-tags. | — | [CLI][S0213]; [UI1][S0214], [UI2][S0191], [UI3][S0215] |
| `openstack server unshelve` | Unshelve доступен для SHELVED_OFFLOADED. | Частично | Нет host/AZ/no-AZ параметров; состояние SHELVED не выбирается UI как unshelve. | — | [CLI][S0216]; [UI1][S0217], [UI2][S0218] |
| `openstack server volume list` | Overview перечисляет attached volumes и device; Detach Volume загружает attachments. | Частично | Не полный вывод attachment metadata/tag/delete_on_termination из современных API. | — | [CLI][S0219]; [UI1][S0220], [UI2][S0176] |
| `openstack server volume set` | Нет изменения delete_on_termination существующего attachment. | Нет | Флаг при boot-volume создании не является редактированием существующего attachment. | — | [CLI][S0221]; [UI1][S0100], [UI2][S0098] |
| `openstack server volume update` | Нет изменения delete_on_termination существующего attachment. | Нет | volume update — deprecated alias server volume set. | — | [CLI][S0222]; [UI1][S0100], [UI2][S0098] |
| `openstack usage list` | Admin Overview: usage всех projects за выбранный период, CSV. | Есть | Основная операция представлена; действуют права и допустимое состояние ресурса. | — | [CLI][S0223]; [UI1][S0224], [UI2][S0225] |
| `openstack usage show` | Project Overview и Identity Project Usage: usage проекта за период, CSV. | Есть | Основная операция представлена; действуют права и допустимое состояние ресурса. | — | [CLI][S0226]; [UI1][S0227], [UI2][S0228], [UI3][S0229] |


<a id="neutron"></a>
### 12.3. Neutron — сети


**160 регистраций.** CLI: `python-openstackclient 7.4.0`. Namespace: `openstack.network.v2`.


#### Результат

Все **160** зарегистрированных entry points перечислены в [core-network-ui.tsv](https://github.com/lebtmalorny-rgb/mimaric/blob/89be5492cba1a1c44d187a7f1df4a4b2243e1ab1/docs/openstack-cli-horizon-2025.1/data/core-network-ui.tsv). Для каждой команды указаны тип доступа, назначение, статус покрытия, ограничение и ссылки на точный класс CLI и исходники UI. Проверено полное совпадение множества строк TSV с [tagged setup.cfg](https://github.com/openstack/python-openstackclient/blob/7.4.0/setup.cfg), без пропусков и повторов.

| Статус | Команд | Значение |
|---|---:|---|
| `yes` | 57 | Основное пользовательское действие или результат представлены в UI. Это не обещание равенства всех флагов, фильтров и полей CLI. |
| `partial` | 20 | Есть только часть операций/параметров одной команды, либо ограниченный вложенный просмотр. Ограничение приведено в каждой строке. |
| `no` | 83 | Соответствующее действие или ресурс не представлены в штатном UI. |
| **Всего** | **160** | Счет относится к entry points, а не к числу независимых функций/API endpoints. |

Общие условия — доступный Neutron endpoint, права, настройки Horizon и поддержка extensions сервером — применяются ко всем строкам. Если действие явно реализовано, один лишь `policy_rules` или extension gate не переводит его в статус отсутствующего. Статусы `conditional` и `uncertain` разрешены схемой TSV, но не понадобились: условия известных реализаций записаны в ограничениях.

#### Сети, подсети и порты

| Группа и число команд | Что дает CLI | Что есть в Horizon | Граница покрытия |
|---|---|---|---|
| `network` — 6 | `create/delete/list/set/show/unset` | Project/Admin Networks, создание обычных и provider/external/shared сетей, детали, удаление, базовый Edit | `create/delete/list/show` — yes; `set` — partial; `unset` — no. Edit меняет name/admin state/shared и в Admin external. Нет полного редактора QoS, DNS, tags, provider attributes и прочих CLI-полей. **`network unset` в этом теге снимает tags**, а не gateway. |
| `subnet` — 6 | `create/delete/list/set/show/unset` | Вкладка Subnets сети; создание с CIDR или существующим pool, DHCP, gateway, DNS, allocation pools, host routes, IPv6 при создании; детали и удаление | `create/delete/list/show` — yes; `set/unset` — partial. IPv6 modes при обновлении скрыты; service types/network segment/tags не редактируются. Пустой allocation_pools не отправляется, поэтому удалить последний pool очисткой поля нельзя; DNS/routes можно очистить. |
| `port` — 6 | `create/delete/list/set/show/unset` | Ports в сети: создание, детали, удаление, базовое изменение, security groups и Allowed Address Pairs | `create/delete/list/show` — yes; `set/unset` — partial. Нет полного редактора fixed IP при update, QoS, binding profile/host, DNS, extra DHCP, NUMA, hints и offload-настроек. |
| `subnet pool` — 6 | `create/delete/list/set/show/unset` | Только выбор существующего pool при создании subnet | `list` — partial; остальные — no. Чтение имени pool в карточке subnet не является просмотром его prefixes/address scope/quotas и не дает CRUD pool. |
| `ip availability` — 2 | `list/show` | Admin Network → Subnets показывает Used IPs / Free IPs | Оба partial: информация по подсетям одной сети, без общего resource list по всем сетям. Требуется `network-ip-availability`. |

Основания: [Admin network Create](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/networks/forms.py#L92), [Admin network Update](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/networks/forms.py#L337), [Subnet create/select pool](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/networks/workflows.py#L105), [Subnet update](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/networks/subnets/workflows.py#L94), [сборка изменяемых subnet-параметров](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/networks/workflows.py#L507), [Port workflows](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/networks/ports/workflows.py#L57), [Allowed Address Pairs](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/networks/ports/extensions/allowed_address_pairs/tables.py#L31), [IP availability](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/networks/subnets/tables.py#L63).

#### Floating IP и перенаправление портов

| Группа и число команд | CLI | Horizon и ограничение |
|---|---|---|
| `floating ip` — 6 | `create/delete/list/set/show/unset` | Allocate/Release, список и Admin Details — yes. `set/unset` — partial: Associate/Disassociate реализуют связь с портом, но нет общего Edit для description, QoS policy и tags. |
| `floating ip pool` — 1 | `list` | Partial: список pools присутствует как выбор в Allocate IP; отдельного списка ресурсов нет. |
| `floating ip port forwarding` — 5 | `create/delete/list/set/show` | `create/delete/list/set` — yes. В Floating IPs доступны Configure и List All Rules; формы задают TCP/UDP, external/internal port ranges, внутренний адрес и description. `show` — partial: параметры видны в таблице/Edit-форме, отдельного DetailView нет. |

Панель forwarding имеет `nav=False` и открывается из Floating IPs; это существующий интерфейс, а не отсутствие панели. Проверка доступности использует `floating-ip-port-forwarding`. Основания: [Floating IP actions](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/floating_ips/tables.py#L147), [Allocate form](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/floating_ips/forms.py#L30), [Association workflow](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/floating_ips/workflows.py#L153), [Port Forwarding actions](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/floating_ip_portforwardings/tables.py#L131), [Port Forwarding fields](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/floating_ip_portforwardings/workflows.py#L60), [panel gate](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/floating_ip_portforwardings/panel.py#L24).

#### Routers и network agents

| Команды | Покрытие | Обоснование |
|---|---|---|
| `router create/delete/list/show` | yes | Обычные Routers формы/таблицы; Create умеет external network/SNAT и доступные DVR/HA/AZ. |
| `router set/unset` | partial | Базовый Edit, Set/Clear Gateway и Static Routes. HA update в форме намеренно выключен; нет всех расширенных параметров QoS/NDP/ECMP/BFD и multihoming. |
| `router add/remove route` | yes | Add/Delete Static Routes. Наличие этой операции не доказывает одинаковую атомарность реализации UI и всех CLI-вариантов. |
| `router add subnet`, `router remove port` | yes | Add Interface по subnet; Remove Interface по port_id. |
| `router remove subnet` | partial | UI снимает интерфейс целиком по port_id; выбор одной subnet из общего IPv6-интерфейса не представлен. |
| `router add port` | no | UI не предлагает выбрать существующий port. Его `_add_interface_by_port` создает **новый** port для указанного IP и затем подключает его. |
| `router add/remove gateway` | no | В CLI это **external-gateway-multihoming**, отдельные методы add/remove_external_gateways. Обычные Set/Clear Gateway в UI не являются этими командами. |
| `network agent add/remove network` | yes | DHCP Agents у сети, назначение/снятие сети с DHCP agent; требуется `dhcp_agent_scheduler`. |
| `network agent list` | yes | Admin → System Information → Network Agents. |
| `network agent show` | partial | Основные свойства видны в строке, без отдельной карточки с полным configurations/API-ответом. |
| `network agent add/remove router`, `network agent delete/set` | no | View Routers только показывает размещение; нет действий назначения L3 agent, удаления агента или enable/disable. |

Суммарно это **14 router-команд** и **8 network agent-команд**. Не следует путать кнопку **Delete DHCP Agent** с `network agent delete`: [ее обработчик](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/networks/agents/tables.py#L31) вызывает `remove_network_from_dhcp_agent`, оставляя сам agent.

Основания: [router actions](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/routers/tables.py#L257), [router Update с отключенным HA update](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/routers/forms.py#L159), [Add Interface и создание нового port](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/routers/ports/forms.py#L92), [Remove Interface](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/routers/ports/tables.py#L78), [CLI multihoming gateway-команды](https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/router.py#L1248), [Network Agents actions](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/info/tables.py#L185).

#### QoS, RBAC, trunks и security groups

| Группа и число команд | Реальный UI | Граница |
|---|---|---|
| `network qos policy` — 5 | Create Policy, Delete Policy/Policies, список, Policy Details | 4 yes; **set — no**. Edit Rule изменяет правило, а не свойства policy. В Create есть name/description/shared, полного набора CLI-полей нет. |
| `network qos rule` — 5 | Add/Edit/Delete Rule; правила в Policy Details | Все yes для основных операций. Код CLI и UI поддерживает `bandwidth_limit`, `dscp_marking`, `minimum_bandwidth`, `minimum_packet_rate`. |
| `network qos rule type` — 2 | Отдельного справочника нет | Оба no. Фиксированный список четырех типов в Create Rule не является запросом API rule types и возможностями драйверов. |
| `network rbac` — 5 | Admin RBAC Policies: Create/Update/Delete/List/Details | Create — partial: только shared network, external network и shared qos_policy; CLI умеет также address_group/address_scope/subnetpool/security_group. Остальные основные операции yes; Update меняет target project, включая `*`. |
| `network trunk` и `network subport list` — 7 | Trunks: Create/Edit/Delete/List/Details; parent/subports; name/description/admin state | Все yes. Edit вычисляет разницу subports и вызывает remove/add; это покрывает `trunk set/unset` и вложенный subport list. |
| `security group` — 6 | Create/Edit name/description, список, Manage Rules, Delete | create/set — partial из-за stateful/stateless и tags; delete/list/show — yes; unset — no, поскольку эта команда снимает tags. |
| `security group rule` — 4 | Add Rule, параметры в таблице, Delete Rule | Create — partial: CIDR или remote security group есть, remote address group нет. delete/list/show — yes для просмотра основных параметров. |

QoS и Trunks включаются по соответствующим extensions. RBAC требует `enable_rbac_policy` и `rbac-policies`; [значение по умолчанию — True](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/defaults.py#L413), поэтому считать эту панель выключенной в штатном коде неправильно.

Основания: [регистрация QoS actions без Edit Policy](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/static/app/core/network_qos/actions/actions.module.js#L32), [четыре типа при Add Rule](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/static/app/core/network_qos/actions/add-rule.action.service.js#L129), [Edit Rule](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/static/app/core/network_qos/actions/edit-rule.action.service.js#L135), [Delete Rule](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/static/app/core/network_qos/actions/delete-rule.action.service.js#L85), [Rule tables с параметрами](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/static/app/core/network_qos/details/overview.controller.js#L36), [RBAC object types формы](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/rbac_policies/forms.py#L30), [Trunk actions](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/static/app/core/trunks/actions/actions.module.js#L45), [Trunk subports update](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/api/neutron.py#L1126), [Security Group fields](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/security_groups/forms.py#L36), [Remote выбора Security Group Rule](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/security_groups/forms.py#L208).

#### Семейства без самостоятельного штатного UI

| Семейство | Число команд | Что осталось CLI/API-функцией |
|---|---:|---|
| `address group` | 6 | CRUD, добавление/снятие IP/CIDR-адресов группы. |
| `address scope` | 5 | CRUD address scopes IPv4/IPv6, shared и прочие свойства. |
| `local ip` + `local ip association` | 8 | CRUD Local IP и связь с портами; это не Floating IP. |
| `network auto allocated topology` | 2 | Создание/удаление автоматически выделяемой топологии проекта; рисунок Network Topology не выполняет эти API-операции. |
| `network flavor` + `network flavor profile` | 12 | CRUD сетевых flavors/service profiles и их привязки; Nova Compute Flavor — другой ресурс. |
| `network l3 conntrack helper` | 5 | CRUD conntrack helper у router. |
| `network meter` + `network meter rule` | 8 | Metering labels и их правила. |
| `network segment` + `network segment range` | 10 | CRUD отдельных сегментов и диапазонов сегментации; поле provider segmentation ID сети не заменяет эти ресурсы. |
| `network service provider` | 1 | Перечень Neutron service providers; значения provider network type — другой справочник. |
| `router ndp proxy` | 5 | CRUD NDP proxies. |
| `default security group rule` | 4 | CRUD шаблонов правил, используемых при создании групп; редактирование группы `default` не является этим API. |

Для отрицательных выводов проверены все frontend-каталоги [enabled](https://github.com/openstack/horizon/tree/25.3.0/openstack_dashboard/enabled), [dashboards](https://github.com/openstack/horizon/tree/25.3.0/openstack_dashboard/dashboards), [static/app/core](https://github.com/openstack/horizon/tree/25.3.0/openstack_dashboard/static/app/core): регистрации панелей, URL, формы/workflows, Django table actions и Angular resource actions. Поиск перечисленных имен ресурсов не обнаружил соответствующих реализаций; найденные сходные понятия (например provider attributes, обычная default SG и subnetpool dropdown) проверены отдельно и не повышены до CRUD без формы.

#### Воспроизводимость и граница доказательства

Локальные источники находятся в `analysis/openstack-cli-horizon-2025.1/sources/python_openstackclient-7.4.0/`, `horizon-25.3.0/`; entry points прочитаны из `python-openstackclient-7.4.0-tagged-setup.cfg`. Для каждой TSV-строки файл и строка CLI-класса определены разбором AST; все пути указанных UI-файлов проверены на существование. Доступ `read` назначен list/show, остальные команды помечены mutation. Команды не выполнялись против облака; браузерные сценарии и policies в развернутом Horizon не тестировались.

Схема TSV: `command`, `namespace`, `access`, `ui_status`, `capability`, `limitation`, `cli_source`, `ui_source`. Это полное перечисление сетевого namespace основного клиента, а не расширений `python-neutronclient`, сторонних UI и не перечень всех REST API Neutron.


| Команда | Возможность | Horizon | Пояснение / ограничение | Наш слой | Источники |
| --- | --- | --- | --- | --- | --- |
| `openstack address group create` | Создать — Создать: группа IP/CIDR. | Нет | Нет панели address groups и выбора remote_address_group в Security Groups. | — | [CLI][S0230]; [UI1][S0231], [UI2][S0232], [UI3][S0233] |
| `openstack address group delete` | Удалить — Удалить: группа IP/CIDR. | Нет | Нет панели address groups и выбора remote_address_group в Security Groups. | — | [CLI][S0234]; [UI1][S0231], [UI2][S0232], [UI3][S0233] |
| `openstack address group list` | Перечислить — Перечислить: группа IP/CIDR. | Нет | Нет панели address groups и выбора remote_address_group в Security Groups. | — | [CLI][S0235]; [UI1][S0231], [UI2][S0232], [UI3][S0233] |
| `openstack address group set` | Изменить — Изменить: группа IP/CIDR. | Нет | Нет панели address groups и выбора remote_address_group в Security Groups. | — | [CLI][S0236]; [UI1][S0231], [UI2][S0232], [UI3][S0233] |
| `openstack address group show` | Показать — Показать: группа IP/CIDR. | Нет | Нет панели address groups и выбора remote_address_group в Security Groups. | — | [CLI][S0237]; [UI1][S0231], [UI2][S0232], [UI3][S0233] |
| `openstack address group unset` | Снять параметры — Снять параметры: группа IP/CIDR. | Нет | Нет панели address groups и выбора remote_address_group в Security Groups. | — | [CLI][S0238]; [UI1][S0231], [UI2][S0232], [UI3][S0233] |
| `openstack address scope create` | Создать — Создать: область адресного пространства. | Нет | Нет отдельного интерфейса address scopes; это не подсеть и не security group. | — | [CLI][S0239]; [UI1][S0231], [UI2][S0232], [UI3][S0233] |
| `openstack address scope delete` | Удалить — Удалить: область адресного пространства. | Нет | Нет отдельного интерфейса address scopes; это не подсеть и не security group. | — | [CLI][S0240]; [UI1][S0231], [UI2][S0232], [UI3][S0233] |
| `openstack address scope list` | Перечислить — Перечислить: область адресного пространства. | Нет | Нет отдельного интерфейса address scopes; это не подсеть и не security group. | — | [CLI][S0241]; [UI1][S0231], [UI2][S0232], [UI3][S0233] |
| `openstack address scope set` | Изменить — Изменить: область адресного пространства. | Нет | Нет отдельного интерфейса address scopes; это не подсеть и не security group. | — | [CLI][S0242]; [UI1][S0231], [UI2][S0232], [UI3][S0233] |
| `openstack address scope show` | Показать — Показать: область адресного пространства. | Нет | Нет отдельного интерфейса address scopes; это не подсеть и не security group. | — | [CLI][S0243]; [UI1][S0231], [UI2][S0232], [UI3][S0233] |
| `openstack default security group rule create` | Создать — Создать: шаблон default security group rule. | Нет | Редактирование обычной security group с именем default не управляет этим API-ресурсом. | — | [CLI][S0244]; [UI1][S0231], [UI2][S0232], [UI3][S0233] |
| `openstack default security group rule delete` | Удалить — Удалить: шаблон default security group rule. | Нет | Редактирование обычной security group с именем default не управляет этим API-ресурсом. | — | [CLI][S0245]; [UI1][S0231], [UI2][S0232], [UI3][S0233] |
| `openstack default security group rule list` | Перечислить — Перечислить: шаблон default security group rule. | Нет | Редактирование обычной security group с именем default не управляет этим API-ресурсом. | — | [CLI][S0246]; [UI1][S0231], [UI2][S0232], [UI3][S0233] |
| `openstack default security group rule show` | Показать — Показать: шаблон default security group rule. | Нет | Редактирование обычной security group с именем default не управляет этим API-ресурсом. | — | [CLI][S0247]; [UI1][S0231], [UI2][S0232], [UI3][S0233] |
| `openstack floating ip create` | Создать — Выделить floating IP из внешней сети; Allocate IP в Project/Admin. | Есть | UI предлагает адрес, описание и DNS-поля; произвольные CLI-параметры, включая QoS policy, представлены не все. | — | [CLI][S0248]; [UI][S0249] |
| `openstack floating ip delete` | Удалить — Release IPs / таблица Floating IPs. | Есть | Операции и список доступны в Project/Admin; действуют права и квота. | — | [CLI][S0250]; [UI][S0251] |
| `openstack floating ip list` | Перечислить — Release IPs / таблица Floating IPs. | Есть | Операции и список доступны в Project/Admin; действуют права и квота. | — | [CLI][S0252]; [UI][S0251] |
| `openstack floating ip pool list` | Перечислить — Список pools показан при Allocate IP. | Частично | Это список выбора в форме, а не самостоятельная таблица всех external network pool attributes. | — | [CLI][S0253]; [UI][S0249] |
| `openstack floating ip port forwarding create` | Создать — Configure/List All Floating IP Port Forwarding Rules: создать, удалить, перечислить, изменить правило. | Есть | Доступ через Floating IPs, скрытая навигационная панель; нужны соответствующие Neutron extensions. UI поддерживает TCP/UDP, диапазоны портов, internal IP и description. | — | [CLI][S0254]; [UI1][S0255], [UI2][S0256] |
| `openstack floating ip port forwarding delete` | Удалить — Configure/List All Floating IP Port Forwarding Rules: создать, удалить, перечислить, изменить правило. | Есть | Доступ через Floating IPs, скрытая навигационная панель; нужны соответствующие Neutron extensions. UI поддерживает TCP/UDP, диапазоны портов, internal IP и description. | — | [CLI][S0257]; [UI1][S0255], [UI2][S0256] |
| `openstack floating ip port forwarding list` | Перечислить — Configure/List All Floating IP Port Forwarding Rules: создать, удалить, перечислить, изменить правило. | Есть | Доступ через Floating IPs, скрытая навигационная панель; нужны соответствующие Neutron extensions. UI поддерживает TCP/UDP, диапазоны портов, internal IP и description. | — | [CLI][S0258]; [UI1][S0255], [UI2][S0256] |
| `openstack floating ip port forwarding set` | Изменить — Configure/List All Floating IP Port Forwarding Rules: создать, удалить, перечислить, изменить правило. | Есть | Доступ через Floating IPs, скрытая навигационная панель; нужны соответствующие Neutron extensions. UI поддерживает TCP/UDP, диапазоны портов, internal IP и description. | — | [CLI][S0259]; [UI1][S0255], [UI2][S0256] |
| `openstack floating ip port forwarding show` | Показать — Правило видно в таблице и предзаполненной Edit-форме. | Частично | Отдельного DetailView по UUID нет; таблица показывает основные параметры перенаправления. | — | [CLI][S0260]; [UI1][S0255], [UI2][S0261] |
| `openstack floating ip set` | Изменить — Associate IP связывает адрес с портом/фиксированным IP. | Частично | Нет общего Edit Floating IP для изменения description, QoS policy и тегов. | — | [CLI][S0262]; [UI1][S0263], [UI2][S0251] |
| `openstack floating ip show` | Показать — Посмотреть floating IP и связанную сеть/порт в деталях Admin. | Есть | Не заявляется равенство всех дополнительных колонок API. | — | [CLI][S0264]; [UI][S0265] |
| `openstack floating ip unset` | Снять параметры — Disassociate IP снимает связь с портом. | Частично | Снятие QoS policy/тегов этим UI не представлено. | — | [CLI][S0266]; [UI][S0267] |
| `openstack ip availability list` | Перечислить — Used IPs / Free IPs подсетей в Admin → Networks → конкретная сеть. | Частично | Нет общей таблицы availability по всем сетям; вывод Free IPs ограничен представлением, нужен network-ip-availability. | — | [CLI][S0268]; [UI][S0269] |
| `openstack ip availability show` | Показать — Used IPs / Free IPs подсетей в Admin → Networks → конкретная сеть. | Частично | Нет общей таблицы availability по всем сетям; вывод Free IPs ограничен представлением, нужен network-ip-availability. | — | [CLI][S0270]; [UI][S0269] |
| `openstack local ip association create` | Создать — Создать: ассоциация Local IP с портом. | Нет | Нет действий управления Local IP associations. | — | [CLI][S0271]; [UI1][S0231], [UI2][S0232], [UI3][S0233] |
| `openstack local ip association delete` | Удалить — Удалить: ассоциация Local IP с портом. | Нет | Нет действий управления Local IP associations. | — | [CLI][S0272]; [UI1][S0231], [UI2][S0232], [UI3][S0233] |
| `openstack local ip association list` | Перечислить — Перечислить: ассоциация Local IP с портом. | Нет | Нет действий управления Local IP associations. | — | [CLI][S0273]; [UI1][S0231], [UI2][S0232], [UI3][S0233] |
| `openstack local ip create` | Создать — Создать: Local IP Neutron. | Нет | Нет панели Local IP; Floating IP — другой ресурс. | — | [CLI][S0274]; [UI1][S0231], [UI2][S0232], [UI3][S0233] |
| `openstack local ip delete` | Удалить — Удалить: Local IP Neutron. | Нет | Нет панели Local IP; Floating IP — другой ресурс. | — | [CLI][S0275]; [UI1][S0231], [UI2][S0232], [UI3][S0233] |
| `openstack local ip list` | Перечислить — Перечислить: Local IP Neutron. | Нет | Нет панели Local IP; Floating IP — другой ресурс. | — | [CLI][S0276]; [UI1][S0231], [UI2][S0232], [UI3][S0233] |
| `openstack local ip set` | Изменить — Изменить: Local IP Neutron. | Нет | Нет панели Local IP; Floating IP — другой ресурс. | — | [CLI][S0277]; [UI1][S0231], [UI2][S0232], [UI3][S0233] |
| `openstack local ip show` | Показать — Показать: Local IP Neutron. | Нет | Нет панели Local IP; Floating IP — другой ресурс. | — | [CLI][S0278]; [UI1][S0231], [UI2][S0232], [UI3][S0233] |
| `openstack network agent add network` | Add DHCP Agent у сети связывает сеть с DHCP agent. | Есть | Нужен dhcp_agent_scheduler; это назначение DHCP, не произвольного типа agent. | — | [CLI][S0279]; [UI1][S0280], [UI2][S0281] |
| `openstack network agent add router` | Нет соответствующего действия над network agent. | Нет | View Routers показывает размещенные routers, но не добавляет/удаляет L3 bindings; в NetworkAgentsTable нет enable/disable/delete. Delete DHCP Agent отвязывает сеть. | — | [CLI][S0282]; [UI1][S0283], [UI2][S0280] |
| `openstack network agent delete` | Удалить — Нет соответствующего действия над network agent. | Нет | View Routers показывает размещенные routers, но не добавляет/удаляет L3 bindings; в NetworkAgentsTable нет enable/disable/delete. Delete DHCP Agent отвязывает сеть. | — | [CLI][S0284]; [UI1][S0283], [UI2][S0280] |
| `openstack network agent list` | Перечислить — Admin → System Information → Network Agents. | Есть | Показаны тип, binary, host, AZ, enabled/alive, heartbeat; нужен extension agent. | — | [CLI][S0285]; [UI][S0286] |
| `openstack network agent remove network` | Delete DHCP Agent у сети удаляет назначение сети этому DHCP agent. | Есть | Несмотря на текст Delete DHCP Agent, сам agent не удаляется: вызывается remove_network_from_dhcp_agent. | — | [CLI][S0287]; [UI][S0280] |
| `openstack network agent remove router` | Нет соответствующего действия над network agent. | Нет | View Routers показывает размещенные routers, но не добавляет/удаляет L3 bindings; в NetworkAgentsTable нет enable/disable/delete. Delete DHCP Agent отвязывает сеть. | — | [CLI][S0288]; [UI1][S0283], [UI2][S0280] |
| `openstack network agent set` | Изменить — Нет соответствующего действия над network agent. | Нет | View Routers показывает размещенные routers, но не добавляет/удаляет L3 bindings; в NetworkAgentsTable нет enable/disable/delete. Delete DHCP Agent отвязывает сеть. | — | [CLI][S0289]; [UI1][S0283], [UI2][S0280] |
| `openstack network agent show` | Показать — Основные свойства agent видны в строке Network Agents. | Частично | Отдельной страницы agent с configurations/полным ответом API нет. | — | [CLI][S0290]; [UI][S0286] |
| `openstack network auto allocated topology create` | Создать — Создать: автоматически выделяемая топология проекта. | Нет | Network Topology визуализирует имеющуюся сеть; действий auto-allocated-topology create/delete нет. | — | [CLI][S0291]; [UI1][S0231], [UI2][S0232], [UI3][S0233] |
| `openstack network auto allocated topology delete` | Удалить — Удалить: автоматически выделяемая топология проекта. | Нет | Network Topology визуализирует имеющуюся сеть; действий auto-allocated-topology create/delete нет. | — | [CLI][S0292]; [UI1][S0231], [UI2][S0232], [UI3][S0233] |
| `openstack network create` | Создать — Create Network: обычная сеть проекта или provider/external/shared сеть через Admin. | Есть | Admin поддерживает тип, physnet и segmentation ID; UI не предоставляет все продвинутые CLI-поля, например QoS/DNS/tags. | — | [CLI][S0293]; [UI1][S0294], [UI2][S0295] |
| `openstack network delete` | Удалить — Список Networks, Network Details и Delete Networks. | Есть | Есть Project/Admin views; provider fields отображаются как атрибуты сети, а не отдельный segment CRUD. | — | [CLI][S0296]; [UI1][S0297], [UI2][S0298] |
| `openstack network flavor add profile` | add profile: сетевой flavor и его service profiles. | Нет | Compute Flavors относятся к Nova и не заменяют Neutron network flavors. | — | [CLI][S0299]; [UI1][S0231], [UI2][S0232], [UI3][S0233] |
| `openstack network flavor create` | Создать — Создать: сетевой flavor и его service profiles. | Нет | Compute Flavors относятся к Nova и не заменяют Neutron network flavors. | — | [CLI][S0300]; [UI1][S0231], [UI2][S0232], [UI3][S0233] |
| `openstack network flavor delete` | Удалить — Удалить: сетевой flavor и его service profiles. | Нет | Compute Flavors относятся к Nova и не заменяют Neutron network flavors. | — | [CLI][S0301]; [UI1][S0231], [UI2][S0232], [UI3][S0233] |
| `openstack network flavor list` | Перечислить — Перечислить: сетевой flavor и его service profiles. | Нет | Compute Flavors относятся к Nova и не заменяют Neutron network flavors. | — | [CLI][S0302]; [UI1][S0231], [UI2][S0232], [UI3][S0233] |
| `openstack network flavor profile create` | Создать — Создать: профиль сервисного драйвера network flavor. | Нет | Нет панели Neutron flavor profiles. | — | [CLI][S0303]; [UI1][S0231], [UI2][S0232], [UI3][S0233] |
| `openstack network flavor profile delete` | Удалить — Удалить: профиль сервисного драйвера network flavor. | Нет | Нет панели Neutron flavor profiles. | — | [CLI][S0304]; [UI1][S0231], [UI2][S0232], [UI3][S0233] |
| `openstack network flavor profile list` | Перечислить — Перечислить: профиль сервисного драйвера network flavor. | Нет | Нет панели Neutron flavor profiles. | — | [CLI][S0305]; [UI1][S0231], [UI2][S0232], [UI3][S0233] |
| `openstack network flavor profile set` | Изменить — Изменить: профиль сервисного драйвера network flavor. | Нет | Нет панели Neutron flavor profiles. | — | [CLI][S0306]; [UI1][S0231], [UI2][S0232], [UI3][S0233] |
| `openstack network flavor profile show` | Показать — Показать: профиль сервисного драйвера network flavor. | Нет | Нет панели Neutron flavor profiles. | — | [CLI][S0307]; [UI1][S0231], [UI2][S0232], [UI3][S0233] |
| `openstack network flavor remove profile` | remove profile: сетевой flavor и его service profiles. | Нет | Compute Flavors относятся к Nova и не заменяют Neutron network flavors. | — | [CLI][S0308]; [UI1][S0231], [UI2][S0232], [UI3][S0233] |
| `openstack network flavor set` | Изменить — Изменить: сетевой flavor и его service profiles. | Нет | Compute Flavors относятся к Nova и не заменяют Neutron network flavors. | — | [CLI][S0309]; [UI1][S0231], [UI2][S0232], [UI3][S0233] |
| `openstack network flavor show` | Показать — Показать: сетевой flavor и его service profiles. | Нет | Compute Flavors относятся к Nova и не заменяют Neutron network flavors. | — | [CLI][S0310]; [UI1][S0231], [UI2][S0232], [UI3][S0233] |
| `openstack network l3 conntrack helper create` | Создать — Создать: L3 conntrack helper маршрутизатора. | Нет | Нет формы управления conntrack helpers. | — | [CLI][S0311]; [UI1][S0231], [UI2][S0232], [UI3][S0233] |
| `openstack network l3 conntrack helper delete` | Удалить — Удалить: L3 conntrack helper маршрутизатора. | Нет | Нет формы управления conntrack helpers. | — | [CLI][S0312]; [UI1][S0231], [UI2][S0232], [UI3][S0233] |
| `openstack network l3 conntrack helper list` | Перечислить — Перечислить: L3 conntrack helper маршрутизатора. | Нет | Нет формы управления conntrack helpers. | — | [CLI][S0313]; [UI1][S0231], [UI2][S0232], [UI3][S0233] |
| `openstack network l3 conntrack helper set` | Изменить — Изменить: L3 conntrack helper маршрутизатора. | Нет | Нет формы управления conntrack helpers. | — | [CLI][S0314]; [UI1][S0231], [UI2][S0232], [UI3][S0233] |
| `openstack network l3 conntrack helper show` | Показать — Показать: L3 conntrack helper маршрутизатора. | Нет | Нет формы управления conntrack helpers. | — | [CLI][S0315]; [UI1][S0231], [UI2][S0232], [UI3][S0233] |
| `openstack network list` | Перечислить — Список Networks, Network Details и Delete Networks. | Есть | Есть Project/Admin views; provider fields отображаются как атрибуты сети, а не отдельный segment CRUD. | — | [CLI][S0316]; [UI1][S0297], [UI2][S0298] |
| `openstack network meter create` | Создать — Создать: metering label сети. | Нет | Нет панели Neutron metering labels. | — | [CLI][S0317]; [UI1][S0231], [UI2][S0232], [UI3][S0233] |
| `openstack network meter delete` | Удалить — Удалить: metering label сети. | Нет | Нет панели Neutron metering labels. | — | [CLI][S0318]; [UI1][S0231], [UI2][S0232], [UI3][S0233] |
| `openstack network meter list` | Перечислить — Перечислить: metering label сети. | Нет | Нет панели Neutron metering labels. | — | [CLI][S0319]; [UI1][S0231], [UI2][S0232], [UI3][S0233] |
| `openstack network meter rule create` | Создать — Создать: правило metering label. | Нет | Нет интерфейса metering label rules. | — | [CLI][S0320]; [UI1][S0231], [UI2][S0232], [UI3][S0233] |
| `openstack network meter rule delete` | Удалить — Удалить: правило metering label. | Нет | Нет интерфейса metering label rules. | — | [CLI][S0321]; [UI1][S0231], [UI2][S0232], [UI3][S0233] |
| `openstack network meter rule list` | Перечислить — Перечислить: правило metering label. | Нет | Нет интерфейса metering label rules. | — | [CLI][S0322]; [UI1][S0231], [UI2][S0232], [UI3][S0233] |
| `openstack network meter rule show` | Показать — Показать: правило metering label. | Нет | Нет интерфейса metering label rules. | — | [CLI][S0323]; [UI1][S0231], [UI2][S0232], [UI3][S0233] |
| `openstack network meter show` | Показать — Показать: metering label сети. | Нет | Нет панели Neutron metering labels. | — | [CLI][S0324]; [UI1][S0231], [UI2][S0232], [UI3][S0233] |
| `openstack network qos policy create` | Создать — Network QoS → Create Policy: name, description, shared. | Есть | Нужен extension qos; default/project и прочие CLI-поля представлены не все. | — | [CLI][S0325]; [UI1][S0326], [UI2][S0327] |
| `openstack network qos policy delete` | Удалить — Network QoS: список, Policy Details, Delete Policy/Policies. | Есть | Нужен extension qos. | — | [CLI][S0328]; [UI1][S0326], [UI2][S0329] |
| `openstack network qos policy list` | Перечислить — Network QoS: список, Policy Details, Delete Policy/Policies. | Есть | Нужен extension qos. | — | [CLI][S0330]; [UI1][S0326], [UI2][S0329] |
| `openstack network qos policy set` | Изменить — Нет Edit Policy. | Нет | Edit Rule изменяет правило политики, а не name/description/shared/default самой policy. | — | [CLI][S0331]; [UI][S0326] |
| `openstack network qos policy show` | Показать — Network QoS: список, Policy Details, Delete Policy/Policies. | Есть | Нужен extension qos. | — | [CLI][S0332]; [UI1][S0326], [UI2][S0329] |
| `openstack network qos rule create` | Создать — Add/Edit/Delete Rule поддерживает bandwidth_limit, dscp_marking, minimum_bandwidth, minimum_packet_rate. | Есть | Нужны qos и соответствующие серверные policy/driver capabilities; статический UI-код не подтверждает runtime поддержку драйвером. | — | [CLI][S0333]; [UI1][S0326], [UI2][S0334] |
| `openstack network qos rule delete` | Удалить — Add/Edit/Delete Rule поддерживает bandwidth_limit, dscp_marking, minimum_bandwidth, minimum_packet_rate. | Есть | Нужны qos и соответствующие серверные policy/driver capabilities; статический UI-код не подтверждает runtime поддержку драйвером. | — | [CLI][S0335]; [UI1][S0326], [UI2][S0336] |
| `openstack network qos rule list` | Перечислить — Правила и их параметры отображаются в Policy Details, по типам. | Есть | Просмотр встроен в карточку политики, отдельная навигационная панель правил не требуется. | — | [CLI][S0337]; [UI][S0338] |
| `openstack network qos rule set` | Изменить — Add/Edit/Delete Rule поддерживает bandwidth_limit, dscp_marking, minimum_bandwidth, minimum_packet_rate. | Есть | Нужны qos и соответствующие серверные policy/driver capabilities; статический UI-код не подтверждает runtime поддержку драйвером. | — | [CLI][S0339]; [UI1][S0326], [UI2][S0340] |
| `openstack network qos rule show` | Показать — Правила и их параметры отображаются в Policy Details, по типам. | Есть | Просмотр встроен в карточку политики, отдельная навигационная панель правил не требуется. | — | [CLI][S0341]; [UI][S0338] |
| `openstack network qos rule type list` | Перечислить — Перечислить: тип правил QoS и возможности драйверов. | Нет | UI содержит фиксированный список четырех типов для создания правил; не вызывает справочник API rule_types и не показывает driver capabilities. | — | [CLI][S0342]; [UI1][S0231], [UI2][S0232], [UI3][S0233] |
| `openstack network qos rule type show` | Показать — Показать: тип правил QoS и возможности драйверов. | Нет | UI содержит фиксированный список четырех типов для создания правил; не вызывает справочник API rule_types и не показывает driver capabilities. | — | [CLI][S0343]; [UI1][S0231], [UI2][S0232], [UI3][S0233] |
| `openstack network rbac create` | Создать — Admin → RBAC Policies → Create: share/external network либо shared qos_policy целевому проекту или *. | Частично | CLI также поддерживает address_group, address_scope, subnetpool, security_group; их нет среди трех вариантов формы. Нужны enable_rbac_policy и rbac-policies. | — | [CLI][S0344]; [UI1][S0345], [UI2][S0346] |
| `openstack network rbac delete` | Удалить — RBAC Policies: список, Details, Delete. | Есть | Нужны enable_rbac_policy (по умолчанию True), rbac-policies и админский доступ. | — | [CLI][S0347]; [UI1][S0346], [UI2][S0348] |
| `openstack network rbac list` | Перечислить — RBAC Policies: список, Details, Delete. | Есть | Нужны enable_rbac_policy (по умолчанию True), rbac-policies и админский доступ. | — | [CLI][S0349]; [UI1][S0346], [UI2][S0348] |
| `openstack network rbac set` | Изменить — Update RBAC Policy меняет target project, включая *. | Есть | Основной параметр CLI set представлен; отсутствует создание иных object types через форму. | — | [CLI][S0350]; [UI1][S0351], [UI2][S0346] |
| `openstack network rbac show` | Показать — RBAC Policies: список, Details, Delete. | Есть | Нужны enable_rbac_policy (по умолчанию True), rbac-policies и админский доступ. | — | [CLI][S0352]; [UI1][S0346], [UI2][S0348] |
| `openstack network segment create` | Создать — Создать: отдельный сегмент сети Neutron. | Нет | Provider network type/segmentation ID в Network не являются CRUD отдельного ресурса segment. | — | [CLI][S0353]; [UI1][S0231], [UI2][S0232], [UI3][S0233] |
| `openstack network segment delete` | Удалить — Удалить: отдельный сегмент сети Neutron. | Нет | Provider network type/segmentation ID в Network не являются CRUD отдельного ресурса segment. | — | [CLI][S0354]; [UI1][S0231], [UI2][S0232], [UI3][S0233] |
| `openstack network segment list` | Перечислить — Перечислить: отдельный сегмент сети Neutron. | Нет | Provider network type/segmentation ID в Network не являются CRUD отдельного ресурса segment. | — | [CLI][S0355]; [UI1][S0231], [UI2][S0232], [UI3][S0233] |
| `openstack network segment range create` | Создать — Создать: диапазон выделения сегментов сети. | Нет | Нет панели network segment ranges; поле segmentation ID сети не заменяет range. | — | [CLI][S0356]; [UI1][S0231], [UI2][S0232], [UI3][S0233] |
| `openstack network segment range delete` | Удалить — Удалить: диапазон выделения сегментов сети. | Нет | Нет панели network segment ranges; поле segmentation ID сети не заменяет range. | — | [CLI][S0357]; [UI1][S0231], [UI2][S0232], [UI3][S0233] |
| `openstack network segment range list` | Перечислить — Перечислить: диапазон выделения сегментов сети. | Нет | Нет панели network segment ranges; поле segmentation ID сети не заменяет range. | — | [CLI][S0358]; [UI1][S0231], [UI2][S0232], [UI3][S0233] |
| `openstack network segment range set` | Изменить — Изменить: диапазон выделения сегментов сети. | Нет | Нет панели network segment ranges; поле segmentation ID сети не заменяет range. | — | [CLI][S0359]; [UI1][S0231], [UI2][S0232], [UI3][S0233] |
| `openstack network segment range show` | Показать — Показать: диапазон выделения сегментов сети. | Нет | Нет панели network segment ranges; поле segmentation ID сети не заменяет range. | — | [CLI][S0360]; [UI1][S0231], [UI2][S0232], [UI3][S0233] |
| `openstack network segment set` | Изменить — Изменить: отдельный сегмент сети Neutron. | Нет | Provider network type/segmentation ID в Network не являются CRUD отдельного ресурса segment. | — | [CLI][S0361]; [UI1][S0231], [UI2][S0232], [UI3][S0233] |
| `openstack network segment show` | Показать — Показать: отдельный сегмент сети Neutron. | Нет | Provider network type/segmentation ID в Network не являются CRUD отдельного ресурса segment. | — | [CLI][S0362]; [UI1][S0231], [UI2][S0232], [UI3][S0233] |
| `openstack network service provider list` | Перечислить — Перечислить: провайдер сетевого сервиса. | Нет | Нет таблицы Neutron service providers; список provider network types в форме создания сети — другой объект. | — | [CLI][S0363]; [UI1][S0231], [UI2][S0232], [UI3][S0233] |
| `openstack network set` | Изменить — Edit Network меняет name/admin_state/shared; Admin также external. | Частично | Нет общей формы для остальных CLI-настроек: QoS, MTU при update, DNS, provider attributes, tags и др. | — | [CLI][S0364]; [UI1][S0365], [UI2][S0366] |
| `openstack network show` | Показать — Список Networks, Network Details и Delete Networks. | Есть | Есть Project/Admin views; provider fields отображаются как атрибуты сети, а не отдельный segment CRUD. | — | [CLI][S0367]; [UI1][S0297], [UI2][S0298] |
| `openstack network subport list` | Перечислить — Subports перечислены в деталях trunk. | Есть | Список вложен в trunk; нужен extension trunk. | — | [CLI][S0368]; [UI][S0369] |
| `openstack network trunk create` | Создать — Trunks: Create/Delete, список, Details, parent port и subports. | Есть | Нужен extension trunk; project/admin scope и права остаются ограничением. | — | [CLI][S0370]; [UI1][S0371], [UI2][S0369] |
| `openstack network trunk delete` | Удалить — Trunks: Create/Delete, список, Details, parent port и subports. | Есть | Нужен extension trunk; project/admin scope и права остаются ограничением. | — | [CLI][S0372]; [UI1][S0371], [UI2][S0369] |
| `openstack network trunk list` | Перечислить — Trunks: Create/Delete, список, Details, parent port и subports. | Есть | Нужен extension trunk; project/admin scope и права остаются ограничением. | — | [CLI][S0373]; [UI1][S0371], [UI2][S0369] |
| `openstack network trunk set` | Изменить — Edit Trunk: name, description, admin state, добавление/изменение subports. | Есть | Parent port существующего trunk не заменяется этой формой; UI diff отправляет update + remove/add subports. | — | [CLI][S0374]; [UI1][S0371], [UI2][S0375] |
| `openstack network trunk show` | Показать — Trunks: Create/Delete, список, Details, parent port и subports. | Есть | Нужен extension trunk; project/admin scope и права остаются ограничением. | — | [CLI][S0376]; [UI1][S0371], [UI2][S0369] |
| `openstack network trunk unset` | Снять параметры — Edit Trunk снимает выбранные subports. | Есть | Именно удаление subports является назначением CLI unset в этом теге. | — | [CLI][S0377]; [UI1][S0371], [UI2][S0378] |
| `openstack network unset` | Снять параметры — CLI снимает сетевые теги. | Нет | В network unset тега 7.4.0 нет снятия gateway/QoS; зарегистрирована именно очистка tags. UI управления тегами сети нет. | — | [CLI][S0379]; [UI][S0365] |
| `openstack port create` | Создать — Create Port у сети: fixed IP/subnet, MAC, device, vNIC, port security и security groups. | Есть | CLI содержит дополнительные поля (QoS, binding profile/host, extra DHCP, NUMA, hardware offload); полной эквивалентности флагов нет. | — | [CLI][S0380]; [UI1][S0381], [UI2][S0382] |
| `openstack port delete` | Удалить — Ports в деталях сети; Port Details, Delete Port. | Есть | Список вложен в Network; административный вариант может видеть порты других проектов. | — | [CLI][S0383]; [UI1][S0382], [UI2][S0384] |
| `openstack port list` | Перечислить — Ports в деталях сети; Port Details, Delete Port. | Есть | Список вложен в Network; административный вариант может видеть порты других проектов. | — | [CLI][S0385]; [UI1][S0382], [UI2][S0384] |
| `openstack port set` | Изменить — Edit Port меняет name/admin state/vNIC/port security/security groups; Allowed Address Pairs добавляются в деталях. | Частично | Нет общего редактора CLI-свойств порта: fixed IP при update, QoS, binding profile/host, DNS, extra DHCP, NUMA и др. | — | [CLI][S0386]; [UI1][S0387], [UI2][S0388] |
| `openstack port show` | Показать — Ports в деталях сети; Port Details, Delete Port. | Есть | Список вложен в Network; административный вариант может видеть порты других проектов. | — | [CLI][S0389]; [UI1][S0382], [UI2][S0384] |
| `openstack port unset` | Снять параметры — Можно снять security groups и удалить allowed address pairs. | Частично | Снятие binding profile, QoS, fixed IP, NUMA, host и hints не представлено. | — | [CLI][S0390]; [UI1][S0391], [UI2][S0392] |
| `openstack router add gateway` | Нет UI управления несколькими external gateways. | Нет | CLI add/remove gateway требует external-gateway-multihoming. Обычные Set/Clear Gateway в UI соответствуют части router set/unset и не заменяют эти команды. | — | [CLI][S0393]; [UI1][S0394], [UI2][S0395] |
| `openstack router add port` | Нет выбора существующего port для подключения к router. | Нет | Add Interface выбирает subnet и optional IP; вариант _add_interface_by_port создает новый порт, а не выбирает уже существующий CLI port. | — | [CLI][S0396]; [UI1][S0397], [UI2][S0398] |
| `openstack router add route` | Static Routes в деталях router: Add Static Route / Delete Static Routes. | Есть | Нужен extraroute; UI работает через таблицу маршрутов, а не обещает одинаковую атомарность всех CLI-вариантов. | — | [CLI][S0399]; [UI][S0400] |
| `openstack router add subnet` | Router → Interfaces → Add Interface по subnet, optional IP. | Есть | При явном IP UI создает новый port и подключает его. | — | [CLI][S0401]; [UI1][S0397], [UI2][S0402] |
| `openstack router create` | Создать — Create Router: name, admin state, external network/SNAT, DVR/HA/AZ при доступности. | Есть | Flavor, NDP, QoS и другие расширенные CLI-поля не все представлены. | — | [CLI][S0403]; [UI1][S0404], [UI2][S0405] |
| `openstack router delete` | Удалить — Routers: список, Router Details, Delete Router. | Есть | Удаление UI предварительно снимает интерфейсы; это отличается от прямого запроса delete API. | — | [CLI][S0406]; [UI1][S0405], [UI2][S0407] |
| `openstack router list` | Перечислить — Routers: список, Router Details, Delete Router. | Есть | Удаление UI предварительно снимает интерфейсы; это отличается от прямого запроса delete API. | — | [CLI][S0408]; [UI1][S0405], [UI2][S0407] |
| `openstack router ndp proxy create` | Создать — Создать: NDP proxy маршрутизатора. | Нет | Нет панели и формы NDP proxies. | — | [CLI][S0409]; [UI1][S0231], [UI2][S0232], [UI3][S0233] |
| `openstack router ndp proxy delete` | Удалить — Удалить: NDP proxy маршрутизатора. | Нет | Нет панели и формы NDP proxies. | — | [CLI][S0410]; [UI1][S0231], [UI2][S0232], [UI3][S0233] |
| `openstack router ndp proxy list` | Перечислить — Перечислить: NDP proxy маршрутизатора. | Нет | Нет панели и формы NDP proxies. | — | [CLI][S0411]; [UI1][S0231], [UI2][S0232], [UI3][S0233] |
| `openstack router ndp proxy set` | Изменить — Изменить: NDP proxy маршрутизатора. | Нет | Нет панели и формы NDP proxies. | — | [CLI][S0412]; [UI1][S0231], [UI2][S0232], [UI3][S0233] |
| `openstack router ndp proxy show` | Показать — Показать: NDP proxy маршрутизатора. | Нет | Нет панели и формы NDP proxies. | — | [CLI][S0413]; [UI1][S0231], [UI2][S0232], [UI3][S0233] |
| `openstack router remove gateway` | Нет UI управления несколькими external gateways. | Нет | CLI add/remove gateway требует external-gateway-multihoming. Обычные Set/Clear Gateway в UI соответствуют части router set/unset и не заменяют эти команды. | — | [CLI][S0414]; [UI1][S0394], [UI2][S0395] |
| `openstack router remove port` | Remove Interface у выбранного router port. | Есть | Для gateway-порта UI вызывает удаление gateway; обычный интерфейс удаляется по port_id. | — | [CLI][S0415]; [UI][S0416] |
| `openstack router remove route` | Static Routes в деталях router: Add Static Route / Delete Static Routes. | Есть | Нужен extraroute; UI работает через таблицу маршрутов, а не обещает одинаковую атомарность всех CLI-вариантов. | — | [CLI][S0417]; [UI][S0400] |
| `openstack router remove subnet` | Remove Interface удаляет интерфейс, соответствующий подсети. | Частично | UI удаляет по port_id; выбор одной subnet из общего интерфейса нескольких IPv6 subnet не представлен. | — | [CLI][S0418]; [UI][S0419] |
| `openstack router set` | Изменить — Edit Router: name/admin state/DVR; Set Gateway задает внешнюю сеть/SNAT; отдельные действия меняют routes. | Частично | HA update намеренно скрыт; нет общей формы multihoming, QoS, NDP, ECMP/BFD и остальных расширенных параметров. | — | [CLI][S0420]; [UI1][S0421], [UI2][S0394] |
| `openstack router show` | Показать — Routers: список, Router Details, Delete Router. | Есть | Удаление UI предварительно снимает интерфейсы; это отличается от прямого запроса delete API. | — | [CLI][S0422]; [UI1][S0405], [UI2][S0407] |
| `openstack router unset` | Снять параметры — Clear Gateway и удаление Static Routes. | Частично | Нет снятия QoS policy/тегов и управления выборочными multihomed gateways. | — | [CLI][S0423]; [UI1][S0424], [UI2][S0425] |
| `openstack security group create` | Создать — Create/Edit Security Group: name и description. | Частично | Нет выбора stateful/stateless и управления tags; создание для произвольного проекта не представлено формой проекта. | — | [CLI][S0426]; [UI1][S0427], [UI2][S0428] |
| `openstack security group delete` | Удалить — Security Groups: список, Manage Rules/детали, Delete. | Есть | Детали ориентированы на правила; полный JSON API не воспроизводится. | — | [CLI][S0429]; [UI1][S0428], [UI2][S0430] |
| `openstack security group list` | Перечислить — Security Groups: список, Manage Rules/детали, Delete. | Есть | Детали ориентированы на правила; полный JSON API не воспроизводится. | — | [CLI][S0431]; [UI1][S0428], [UI2][S0430] |
| `openstack security group rule create` | Создать — Add Rule: protocol/ports/ICMP, direction, ethertype, CIDR или remote security group. | Частично | Нет remote address group, которая доступна CLI; это существенный отдельный вид remote. | — | [CLI][S0432]; [UI][S0433] |
| `openstack security group rule delete` | Удалить — Manage Rules: список и параметры правил; Delete Rule. | Есть | Просмотр конкретного правила обеспечивается строкой таблицы; remote address group не создается UI. | — | [CLI][S0434]; [UI1][S0435], [UI2][S0436] |
| `openstack security group rule list` | Перечислить — Manage Rules: список и параметры правил; Delete Rule. | Есть | Просмотр конкретного правила обеспечивается строкой таблицы; remote address group не создается UI. | — | [CLI][S0437]; [UI1][S0435], [UI2][S0436] |
| `openstack security group rule show` | Показать — Manage Rules: список и параметры правил; Delete Rule. | Есть | Просмотр конкретного правила обеспечивается строкой таблицы; remote address group не создается UI. | — | [CLI][S0438]; [UI1][S0435], [UI2][S0436] |
| `openstack security group set` | Изменить — Create/Edit Security Group: name и description. | Частично | Нет выбора stateful/stateless и управления tags; создание для произвольного проекта не представлено формой проекта. | — | [CLI][S0439]; [UI1][S0427], [UI2][S0428] |
| `openstack security group show` | Показать — Security Groups: список, Manage Rules/детали, Delete. | Есть | Детали ориентированы на правила; полный JSON API не воспроизводится. | — | [CLI][S0440]; [UI1][S0428], [UI2][S0430] |
| `openstack security group unset` | Снять параметры — CLI снимает tags security group. | Нет | UI name/description не является редактором tags; действия снятия тегов нет. | — | [CLI][S0441]; [UI][S0427] |
| `openstack subnet create` | Создать — Create Subnet: CIDR либо существующий subnet pool, IPv4/IPv6, gateway, DHCP, DNS, routes, allocation pools. | Есть | Нет полного набора CLI-полей, например service types, network segment и tags. | — | [CLI][S0442]; [UI1][S0443], [UI2][S0444] |
| `openstack subnet delete` | Удалить — Subnets в Network Details: список, детали, Delete Subnet. | Есть | Список вложен в сеть; IPv6 и другие поля зависят от настроек/расширений. | — | [CLI][S0445]; [UI1][S0446], [UI2][S0447] |
| `openstack subnet list` | Перечислить — Subnets в Network Details: список, детали, Delete Subnet. | Есть | Список вложен в сеть; IPv6 и другие поля зависят от настроек/расширений. | — | [CLI][S0448]; [UI1][S0446], [UI2][S0447] |
| `openstack subnet pool create` | Создать — Нет отдельной панели subnet pools. | Нет | При просмотре subnet читается только имя/id ее pool; это не просмотр pool prefixes, address scope, quotas и allocation attributes и не CRUD pool. | — | [CLI][S0449]; [UI1][S0450], [UI2][S0451] |
| `openstack subnet pool delete` | Удалить — Нет отдельной панели subnet pools. | Нет | При просмотре subnet читается только имя/id ее pool; это не просмотр pool prefixes, address scope, quotas и allocation attributes и не CRUD pool. | — | [CLI][S0452]; [UI1][S0450], [UI2][S0451] |
| `openstack subnet pool list` | Перечислить — Существующие subnet pools перечислены в Create Subnet. | Частично | Dropdown для allocation, без самостоятельной таблицы pool ресурсов. | — | [CLI][S0453]; [UI][S0451] |
| `openstack subnet pool set` | Изменить — Нет отдельной панели subnet pools. | Нет | При просмотре subnet читается только имя/id ее pool; это не просмотр pool prefixes, address scope, quotas и allocation attributes и не CRUD pool. | — | [CLI][S0454]; [UI1][S0450], [UI2][S0451] |
| `openstack subnet pool show` | Показать — Нет отдельной панели subnet pools. | Нет | При просмотре subnet читается только имя/id ее pool; это не просмотр pool prefixes, address scope, quotas и allocation attributes и не CRUD pool. | — | [CLI][S0455]; [UI1][S0450], [UI2][S0451] |
| `openstack subnet pool unset` | Снять параметры — Нет отдельной панели subnet pools. | Нет | При просмотре subnet читается только имя/id ее pool; это не просмотр pool prefixes, address scope, quotas и allocation attributes и не CRUD pool. | — | [CLI][S0456]; [UI1][S0450], [UI2][S0451] |
| `openstack subnet set` | Изменить — Edit Subnet: name, gateway, DHCP, allocation pools, DNS nameservers, host routes. | Частично | IPv6 modes при update скрыты; нет service types, segment, description/tags и ряда расширений. | — | [CLI][S0457]; [UI1][S0458], [UI2][S0459] |
| `openstack subnet show` | Показать — Subnets в Network Details: список, детали, Delete Subnet. | Есть | Список вложен в сеть; IPv6 и другие поля зависят от настроек/расширений. | — | [CLI][S0460]; [UI1][S0446], [UI2][S0447] |
| `openstack subnet unset` | Снять параметры — Edit Subnet может убрать gateway, DNS/host routes и записи allocation pools. | Частично | Нет снятия service types и tags; полностью пустой allocation_pools не отправляется, поэтому удаление последнего pool не покрыто. DNS/routes можно очистить. | — | [CLI][S0461]; [UI1][S0459], [UI2][S0462] |


<a id="cinder"></a>
### 12.4. Cinder — блочное хранилище


**93 регистраций.** CLI: `python-openstackclient 7.4.0`. Namespace: `openstack.volume.v3`.


#### Cinder: тома, snapshots, backups и transfer

##### Основной lifecycle тома — 9 команд

`volume create/delete/list/show/migrate` имеют прямые рабочие сценарии в Project/Admin Volumes. Create Volume поддерживает пустой том, image, snapshot и clone; восстановление backup и принятие существующего backend volume реализованы отдельными формами Restore Backup и Admin Manage Volume. `volume delete --remote` соответствует Admin Unmanage. Horizon также предоставляет Upload to Image, Extend Volume, Change Volume Type, Edit Volume и Update Metadata. [Project forms.py:78](https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/project/volumes/forms.py#L78), [Admin forms.py:46](https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/admin/volumes/forms.py#L46), [реестр действий Volumes:575](https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/project/volumes/tables.py#L575).

`volume set` оценен `partial`: UI покрывает name/description/bootable, extend, retype, обычные metadata и административный reset volume status. CLI дополнительно управляет image properties на томе, read-only/read-write и ручным attachment status; полного UI для этих функций нет. `volume unset` покрыт только для обычных metadata, без отдельного удаления volume image properties. [CLI SetVolume:604](https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/volume/v3/volume.py#L604), [UI Edit/Extend/Retype:660](https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/project/volumes/forms.py#L660), [Admin UpdateStatus:216](https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/admin/volumes/forms.py#L216).

`volume summary` и `volume revert` — `no`: quota/usage виджеты не представляют специальный summary API; Create Volume from Snapshot создает другой том и не откатывает существующий том к последнему snapshot. [CLI summary/revert:1002](https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/volume/v3/volume.py#L1002), [CreateVolumeFromSnapshot:127](https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/project/snapshots/tables.py#L127).

Удаление через UI имеет собственные ограничения состояния: например Delete Volume не доступно, если том состоит в volume group или имеет snapshot. Поэтому `yes` для delete не означает наличие аналога всех вариантов `--force` и `--purge`. [DeleteVolume.allowed:125](https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/project/volumes/tables.py#L125).

##### Attachment API — 6 команд

`volume attachment create/delete/complete/set/show` — `no`. UI Manage Attachments вызывает **Nova** `instance_volume_attach/detach`; CLI здесь управляет отдельными записями **Cinder Attachment API**, включая создание reservation/connector state и complete. Кнопка прикрепления диска к ВМ не является интерфейсом управления этим lifecycle. [CLI volume_attachment.py](https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/volume/v3/volume_attachment.py), [AttachForm:469](https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/project/volumes/forms.py#L469), [DetachVolume:592](https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/project/volumes/tables.py#L592).

`volume attachment list` — `partial`: UI показывает `volume.attachments` выбранного тома, но не глобальный список ресурсов Attachment API и их полный набор полей. [AttachView.get_data:550](https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/project/volumes/views.py#L550).

##### Volume snapshots — 6 команд

Все `volume snapshot create/delete/list/set/show/unset` имеют основные UI-соответствия: Create Snapshot из тома; Project/Admin Snapshots; Edit Snapshot, Update Metadata, Admin Update Status; Overview/Messages. Create Volume from Snapshot — дополнительный сценарий UI. [Snapshot actions:227](https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/project/snapshots/tables.py#L227), [CreateSnapshotForm:544](https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/project/volumes/forms.py#L544), [Admin snapshot actions:69](https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/admin/snapshots/tables.py#L69).

##### Backups и backup records — 9 команд

`volume backup create/delete/list/restore/show` реализованы, но оценены `conditional`: **upstream `OPENSTACK_CINDER_FEATURES['enable_backup'] = False`**. Наличие Cinder само по себе не включает эти панели/кнопки. [defaults.py:367](https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/defaults.py#L367), [backup gate api/cinder.py:571](https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/api/cinder.py#L571).

Create Backup предлагает name, description, container, snapshot и incremental. Incremental показывается при наличии предыдущего доступного backup; для тома in-use форма передает force. Restore Backup умеет новый или существующий том. Admin Backups содержит Force Delete и Update Status. `volume backup set` — `partial`, поскольку name/description/metadata CLI не имеют соответствующего editor; `volume backup unset` — `no`. [Project backup forms.py:32](https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/project/backups/forms.py#L32), [RestoreBackupForm:130](https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/project/backups/forms.py#L130), [Admin Backups actions:122](https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/admin/backups/tables.py#L122).

`volume backup record export/import` — `no`: перенос backend record между инсталляциями не представлен в UI. Это отдельная операция, не восстановление backup и не скачивание образа. [CLI backup_record.py](https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/volume/v2/backup_record.py).

##### Transfer requests — 5 команд

`volume transfer request create/accept/delete/show` имеют соответствия Create Transfer, Accept Transfer, Cancel Transfer и ShowTransferView. После создания UI показывает и позволяет скачать ID/name/auth key; повторное чтение auth key из API не подразумевается. `list` — `partial`: transfers связываются с томами для действий, отдельной таблицы всех transfer requests нет. Опция CLI включить/исключить snapshots при передаче не является полем формы. [Transfer forms.py:588](https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/project/volumes/forms.py#L588), [CancelTransfer:338](https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/project/volumes/tables.py#L338), [ShowTransferView:438](https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/project/volumes/views.py#L438).

#### Cinder: groups, типы и QoS

##### Legacy consistency groups — 11 команд

Все 7 `consistency group` и 4 `consistency group snapshot` entry points сохранены в namespace volume.v3, но используют legacy client classes `volume/v2/consistency_group*.py`. Штатные панели **Volume Groups/Group Snapshots** в Horizon 25.3.0 вызывают `client.groups`/`client.group_snapshots`, то есть generic groups. Это разные API-ресурсы, поэтому для 11 legacy-команд поставлено `no`, а не ложное соответствие по слову group. [CLI registration](https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/setup.cfg), [Horizon generic group API:1137](https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/api/cinder.py#L1137).

##### Generic groups, group snapshots и group types — 15 команд

- Из 6 `volume group` команд create/delete/list имеют основные UI-соответствия; create включает обычное создание, clone и создание из group snapshot. `set` — `partial`: имя/описание доступны, enable/disable replication отсутствует. `show` — `partial`: group/volumes видны, специализированного показа replication targets нет. `failover` — `no`.
- Все 4 `volume group snapshot create/delete/list/show` имеют соответствия в UI.
- Все 5 зарегистрированных `volume group type create/delete/list/set/show` имеют соответствия Admin Group Types и View Specs; specs доступны для создания/редактирования/удаления.

Источники: [Group actions:175](https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/project/volume_groups/tables.py#L175), [group forms:24](https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/project/volume_groups/forms.py#L24), [Group Snapshot actions:130](https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/project/vg_snapshots/tables.py#L130), [Group Types actions:121](https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/admin/group_types/tables.py#L121), [CLI replication functions:314](https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/volume/v3/volume_group.py#L314).

Отдельная особенность полного сравнения: UI **Manage Volumes** умеет добавлять/удалять тома из generic group, но `volume group set` именно в OSC 7.4.0 принимает name/description и replication toggle, без add/remove volumes. Нельзя автоматически считать, что любую возможность Horizon покрывает одноименная группа команд базового OSC. [UI workflows.py](https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/project/volume_groups/workflows.py), [CLI SetVolumeGroup](https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/volume/v3/volume_group.py#L314).

##### Volume types — 6 команд; QoS — 8 команд

Все зарегистрированные `volume type create/delete/list/set/show/unset` имеют основные UI-соответствия. Admin Volume Types объединяет типы, extra specs/metadata, private-project access, encryption settings. Encryption не потеряна из-за отсутствия отдельной `volume type encryption` группы в этом CLI: соответствующие параметры входят в `volume type create/set/unset`, а в Horizon вынесены в Create/Update/Delete Encryption. [VolumeTypesTable:249](https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/admin/volume_types/tables.py#L249), [type forms:95](https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/admin/volume_types/forms.py#L95), [CLI SetVolumeType:564](https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/volume/v3/volume_type.py#L564).

Все 8 `volume qos associate/create/delete/disassociate/list/set/show/unset` имеют основные соответствия: QoS Specs, Manage Specs, Edit Consumer и Manage QoS Spec Association. CLI объединяет часть последовательных UI-действий; глобальные bulk-варианты association не подразумеваются. [QoS actions:268](https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/admin/volume_types/tables.py#L268), [association form:167](https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/admin/volume_types/forms.py#L167), [key/value editor:78](https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/admin/volume_types/qos_specs/tables.py#L78).

#### Cinder: административные и диагностические семейства — 18 команд

| Семейство | Число | Соответствие Horizon |
|---|---:|---|
| `volume backend capability show`, `volume backend pool list` | 2 | Capability — `no`; pools — `partial`: список имен для destination Migrate, без полноценной pool/capabilities панели |
| `volume host set` | 1 | `no`: freeze/thaw host отсутствует |
| `volume message delete/list/show` | 3 | Delete — `no`; list/show — `partial`: Messages tabs выбранных volume/backup/snapshot, без общего message browser |
| `block storage cluster list/set/show` | 3 | `no`: Cinder service clusters не представлены |
| `block storage resource filter list/show` | 2 | `no`: discovery поддерживаемых API resource filters не является обычным фильтром таблицы |
| `volume service list/set` | 2 | List — `yes`, Admin System Information / Block Storage Services; set — `no`, таблица read-only |
| `block storage log level list/set` | 2 | `no`: runtime log levels не представлены |
| `block storage cleanup` | 1 | `no` |
| `block storage volume manageable list`, `block storage snapshot manageable list` | 2 | `no`: Admin Manage принимает reference вручную, не показывает discovery unmanaged backend objects |

Источники: [Migrate pool selector:246](https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/admin/volumes/views.py#L246), [VolumeMessagesTab:82](https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/project/volumes/tabs.py#L82), [message table:664](https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/project/volumes/tables.py#L664), [CinderServicesTable:128](https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/admin/info/tables.py#L128), [Admin ManageVolume:46](https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/admin/volumes/forms.py#L46). Для каждой строки TSV дополнительно указан точный класс CLI.


| Команда | Возможность | Horizon | Пояснение / ограничение | Наш слой | Источники |
| --- | --- | --- | --- | --- | --- |
| `openstack block storage cleanup` | Очистка Cinder service ресурсов после отказов | Нет | Нет UI cleanup. | — | [CLI][S0463]; [UI][S0464] |
| `openstack block storage cluster list` | Список Cinder service cluster | Нет | Нет UI Cinder clusters и управления clustered-service состоянием. | — | [CLI][S0465]; [UI][S0464] |
| `openstack block storage cluster set` | Изменение Cinder service cluster | Нет | Нет UI Cinder clusters и управления clustered-service состоянием. | — | [CLI][S0466]; [UI][S0464] |
| `openstack block storage cluster show` | Просмотр Cinder service cluster | Нет | Нет UI Cinder clusters и управления clustered-service состоянием. | — | [CLI][S0467]; [UI][S0464] |
| `openstack block storage log level list` | Список runtime log levels Cinder services | Нет | Нет штатной панели log-level управления Cinder. | — | [CLI][S0468]; [UI][S0464] |
| `openstack block storage log level set` | Изменение runtime log levels Cinder services | Нет | Нет штатной панели log-level управления Cinder. | — | [CLI][S0469]; [UI][S0464] |
| `openstack block storage resource filter list` | Список поддерживаемых Cinder API resource filters | Нет | Фильтры таблицы Volumes не являются discovery API supported resource filters. | — | [CLI][S0470]; [UI][S0471] |
| `openstack block storage resource filter show` | Просмотр поддерживаемых Cinder API resource filters | Нет | Фильтры таблицы Volumes не являются discovery API supported resource filters. | — | [CLI][S0472]; [UI][S0471] |
| `openstack block storage snapshot manageable list` | Список backend snapshots, доступных для принятия под управление | Нет | Нет discovery manageable snapshots UI. | — | [CLI][S0473]; [UI][S0474] |
| `openstack block storage volume manageable list` | Список backend volumes, доступных для принятия под управление | Нет | Admin Manage Volume принимает reference вручную; не содержит discovery списка manageable volumes. | — | [CLI][S0475]; [UI][S0476] |
| `openstack consistency group add volume` | Добавление тома в legacy consistency group | Нет | Панель Volume Groups использует client.groups generic API; это иной ресурс, не legacy consistencygroups. | — | [CLI][S0477]; [UI1][S0478], [UI2][S0479] |
| `openstack consistency group create` | Создание legacy consistency group | Нет | Панель Volume Groups использует client.groups generic API; это иной ресурс, не legacy consistencygroups. | — | [CLI][S0480]; [UI1][S0478], [UI2][S0479] |
| `openstack consistency group delete` | Удаление legacy consistency group | Нет | Панель Volume Groups использует client.groups generic API; это иной ресурс, не legacy consistencygroups. | — | [CLI][S0481]; [UI1][S0478], [UI2][S0479] |
| `openstack consistency group list` | Список legacy consistency group | Нет | Панель Volume Groups использует client.groups generic API; это иной ресурс, не legacy consistencygroups. | — | [CLI][S0482]; [UI1][S0478], [UI2][S0479] |
| `openstack consistency group remove volume` | Удаление тома из legacy consistency group | Нет | Панель Volume Groups использует client.groups generic API; это иной ресурс, не legacy consistencygroups. | — | [CLI][S0483]; [UI1][S0478], [UI2][S0479] |
| `openstack consistency group set` | Изменение legacy consistency group | Нет | Панель Volume Groups использует client.groups generic API; это иной ресурс, не legacy consistencygroups. | — | [CLI][S0484]; [UI1][S0478], [UI2][S0479] |
| `openstack consistency group show` | Просмотр legacy consistency group | Нет | Панель Volume Groups использует client.groups generic API; это иной ресурс, не legacy consistencygroups. | — | [CLI][S0485]; [UI1][S0478], [UI2][S0479] |
| `openstack consistency group snapshot create` | Создание legacy consistency-group snapshot | Нет | Панель Group Snapshots вызывает generic group_snapshots; отдельного legacy cgsnapshots UI нет. | — | [CLI][S0486]; [UI1][S0487], [UI2][S0488] |
| `openstack consistency group snapshot delete` | Удаление legacy consistency-group snapshot | Нет | Панель Group Snapshots вызывает generic group_snapshots; отдельного legacy cgsnapshots UI нет. | — | [CLI][S0489]; [UI1][S0487], [UI2][S0488] |
| `openstack consistency group snapshot list` | Список legacy consistency-group snapshot | Нет | Панель Group Snapshots вызывает generic group_snapshots; отдельного legacy cgsnapshots UI нет. | — | [CLI][S0490]; [UI1][S0487], [UI2][S0488] |
| `openstack consistency group snapshot show` | Просмотр legacy consistency-group snapshot | Нет | Панель Group Snapshots вызывает generic group_snapshots; отдельного legacy cgsnapshots UI нет. | — | [CLI][S0491]; [UI1][S0487], [UI2][S0488] |
| `openstack volume attachment complete` | Завершение объекта Cinder Attachment API | Нет | Manage Attachments подключает/отключает volume через Nova; UI не управляет отдельным reserve/connect/complete lifecycle Cinder attachments. | — | [CLI][S0492]; [UI1][S0493], [UI2][S0494] |
| `openstack volume attachment create` | Создание объекта Cinder Attachment API | Нет | Manage Attachments подключает/отключает volume через Nova; UI не управляет отдельным reserve/connect/complete lifecycle Cinder attachments. | — | [CLI][S0495]; [UI1][S0493], [UI2][S0494] |
| `openstack volume attachment delete` | Удаление объекта Cinder Attachment API | Нет | Manage Attachments подключает/отключает volume через Nova; UI не управляет отдельным reserve/connect/complete lifecycle Cinder attachments. | — | [CLI][S0496]; [UI1][S0493], [UI2][S0494] |
| `openstack volume attachment list` | Список объектов Cinder Attachment API | Частично | В Manage Attachments виден volume.attachments выбранного тома; нет отдельного глобального списка и полного набора полей Attachment API. | — | [CLI][S0497]; [UI1][S0498], [UI2][S0499] |
| `openstack volume attachment set` | Изменение объекта Cinder Attachment API | Нет | Manage Attachments подключает/отключает volume через Nova; UI не управляет отдельным reserve/connect/complete lifecycle Cinder attachments. | — | [CLI][S0500]; [UI1][S0493], [UI2][S0494] |
| `openstack volume attachment show` | Просмотр объекта Cinder Attachment API | Нет | Manage Attachments подключает/отключает volume через Nova; UI не управляет отдельным reserve/connect/complete lifecycle Cinder attachments. | — | [CLI][S0501]; [UI1][S0493], [UI2][S0494] |
| `openstack volume backend capability show` | Возможности драйвера storage backend | Нет | Нет самостоятельного UI backend capabilities. | — | [CLI][S0502]; [UI][S0503] |
| `openstack volume backend pool list` | Список storage pools и их возможностей | Частично | Имена pools используются в выборе destination Migrate; отдельной подробной таблицы pool capabilities нет. | — | [CLI][S0504]; [UI][S0505] |
| `openstack volume backup create` | Создание полного/incremental backup тома или snapshot | Условно | Панель/действия требуют OPENSTACK_CINDER_FEATURES['enable_backup']=True (upstream default False), backup service и policy. Есть name/description/container/snapshot/incremental; для in-use force выставляется автоматически; нет metadata/AZ CLI. | — | [CLI][S0506]; [UI1][S0507], [UI2][S0508] |
| `openstack volume backup delete` | Удаление backup | Условно | Панель/действия требуют OPENSTACK_CINDER_FEATURES['enable_backup']=True (upstream default False), backup service и policy. Обычное удаление; Admin имеет Force Delete. | — | [CLI][S0509]; [UI1][S0510], [UI2][S0511] |
| `openstack volume backup list` | Список backup | Условно | Панель/действия требуют OPENSTACK_CINDER_FEATURES['enable_backup']=True (upstream default False), backup service и policy. Project/Admin Backups. | — | [CLI][S0512]; [UI1][S0513], [UI2][S0514] |
| `openstack volume backup record export` | Экспорт backup record для переноса между инсталляциями | Нет | Экспорт записи backend не представлен кнопкой UI; это не скачивание содержимого тома. | — | [CLI][S0515]; [UI1][S0516], [UI2][S0517] |
| `openstack volume backup record import` | Импорт backup record | Нет | Нет UI импорта backup record. | — | [CLI][S0518]; [UI1][S0516], [UI2][S0517] |
| `openstack volume backup restore` | Восстановление backup в новый или существующий том | Условно | Панель/действия требуют OPENSTACK_CINDER_FEATURES['enable_backup']=True (upstream default False), backup service и policy. Restore Backup выбирает destination volume или новый том. | — | [CLI][S0519]; [UI][S0520] |
| `openstack volume backup set` | Изменение имени/описания/status/metadata backup | Частично | Панель/действия требуют OPENSTACK_CINDER_FEATURES['enable_backup']=True (upstream default False), backup service и policy. Admin Update Status реализован; редактирования name/description/metadata backup нет. | — | [CLI][S0521]; [UI1][S0522], [UI2][S0523] |
| `openstack volume backup show` | Просмотр деталей backup | Условно | Панель/действия требуют OPENSTACK_CINDER_FEATURES['enable_backup']=True (upstream default False), backup service и policy. Overview и Messages. | — | [CLI][S0524]; [UI][S0525] |
| `openstack volume backup unset` | Удаление metadata backup | Нет | Нет отдельного UI удаления свойств backup. | — | [CLI][S0526]; [UI1][S0516], [UI2][S0517] |
| `openstack volume create` | Создание тома, clone, том из image/snapshot/backup; прием существующего backend volume | Есть | Основной Create Volume; backup restore и Admin Manage реализованы отдельными формами. Не все scheduler/remote-source/cluster параметры CLI доступны. | — | [CLI][S0527]; [UI1][S0528], [UI2][S0520], [UI3][S0476] |
| `openstack volume delete` | Удаление тома; освобождение от управления с соответствующей опцией CLI | Есть | Delete Volume; Admin Unmanage отдельно. UI не обещает parity --force/--purge и ограничивает допустимые состояния. | — | [CLI][S0529]; [UI1][S0530], [UI2][S0531] |
| `openstack volume group create` | Создание generic volume group, clone или создание из group snapshot | Есть | Create Group workflow, Clone Group и Create Group from Snapshot. Требуется generic-groups API/backend. | — | [CLI][S0532]; [UI1][S0533], [UI2][S0534], [UI3][S0535] |
| `openstack volume group delete` | Удаление generic volume group, при необходимости вместе с volumes | Есть | Delete Group и флаг удаления томов. | — | [CLI][S0536]; [UI][S0537] |
| `openstack volume group failover` | Failover репликации generic volume group | Нет | Нет UI group replication failover. | — | [CLI][S0538]; [UI][S0479] |
| `openstack volume group list` | Список generic volume groups | Есть | Project/Admin Volume Groups. | — | [CLI][S0539]; [UI1][S0540], [UI2][S0541] |
| `openstack volume group set` | Изменение group name/description; enable/disable replication | Частично | Edit Group меняет name/description; enable/disable replication отсутствует. Manage Volumes — дополнительное действие UI, не флаг этой команды. | — | [CLI][S0542]; [UI1][S0543], [UI2][S0544] |
| `openstack volume group show` | Детали volume group, входящие volumes и replication targets | Частично | Overview/Volumes доступны; нет специального представления replication targets. | — | [CLI][S0545]; [UI][S0546] |
| `openstack volume group snapshot create` | Создание generic group snapshot | Есть | Create Snapshot из группы; Project/Admin Group Snapshots, detail/delete; создание новой группы из snapshot отдельной кнопкой. | — | [CLI][S0547]; [UI1][S0548], [UI2][S0549], [UI3][S0550] |
| `openstack volume group snapshot delete` | Удаление generic group snapshot | Есть | Create Snapshot из группы; Project/Admin Group Snapshots, detail/delete; создание новой группы из snapshot отдельной кнопкой. | — | [CLI][S0551]; [UI1][S0548], [UI2][S0549], [UI3][S0550] |
| `openstack volume group snapshot list` | Список generic group snapshot | Есть | Create Snapshot из группы; Project/Admin Group Snapshots, detail/delete; создание новой группы из snapshot отдельной кнопкой. | — | [CLI][S0552]; [UI1][S0548], [UI2][S0549], [UI3][S0550] |
| `openstack volume group snapshot show` | Просмотр generic group snapshot | Есть | Create Snapshot из группы; Project/Admin Group Snapshots, detail/delete; создание новой группы из snapshot отдельной кнопкой. | — | [CLI][S0553]; [UI1][S0548], [UI2][S0549], [UI3][S0550] |
| `openstack volume group type create` | Создание group type и его specs | Есть | Admin Group Types: Create/Edit/Delete/View Specs; specs можно добавлять, изменять и удалять. | — | [CLI][S0554]; [UI1][S0555], [UI2][S0556], [UI3][S0557] |
| `openstack volume group type delete` | Удаление group type и его specs | Есть | Admin Group Types: Create/Edit/Delete/View Specs; specs можно добавлять, изменять и удалять. | — | [CLI][S0558]; [UI1][S0555], [UI2][S0556], [UI3][S0557] |
| `openstack volume group type list` | Список group type и его specs | Есть | Admin Group Types: Create/Edit/Delete/View Specs; specs можно добавлять, изменять и удалять. | — | [CLI][S0559]; [UI1][S0555], [UI2][S0556], [UI3][S0557] |
| `openstack volume group type set` | Изменение group type и его specs | Есть | Admin Group Types: Create/Edit/Delete/View Specs; specs можно добавлять, изменять и удалять. | — | [CLI][S0560]; [UI1][S0555], [UI2][S0556], [UI3][S0557] |
| `openstack volume group type show` | Просмотр group type и его specs | Есть | Admin Group Types: Create/Edit/Delete/View Specs; specs можно добавлять, изменять и удалять. | — | [CLI][S0561]; [UI1][S0555], [UI2][S0556], [UI3][S0557] |
| `openstack volume host set` | Freeze/thaw Cinder volume host | Нет | Нет UI управления freeze/thaw backend host. | — | [CLI][S0562]; [UI][S0464] |
| `openstack volume list` | Список томов проекта или всех проектов | Есть | Project/Admin Volumes; состав фильтров и формат выгрузки отличаются от CLI. | — | [CLI][S0563]; [UI1][S0564], [UI2][S0565] |
| `openstack volume message delete` | Удаление Cinder user message | Нет | Messages tabs доступны для просмотра; действий delete нет. | — | [CLI][S0566]; [UI][S0567] |
| `openstack volume message list` | Список Cinder user messages | Частично | Messages для выбранных volume/backup/snapshot; отдельного общего списка messages и всех CLI-фильтров нет. | — | [CLI][S0568]; [UI1][S0569], [UI2][S0570], [UI3][S0571] |
| `openstack volume message show` | Подробности конкретного Cinder user message | Частично | Таблицы messages показывают ID, event ID, user message, created time; отдельной карточки message нет. | — | [CLI][S0572]; [UI][S0567] |
| `openstack volume migrate` | Перенос тома на другой backend/host | Есть | Admin Migrate Volume с выбором host, force host copy и lock volume; нужны policy и поддержка backend. | — | [CLI][S0573]; [UI][S0574] |
| `openstack volume qos associate` | Привязка QoS spec к volume type | Есть | Manage QoS Spec Association у volume type. | — | [CLI][S0575]; [UI][S0576] |
| `openstack volume qos create` | Создание QoS spec и его key/value параметров | Есть | Admin Volume Types / QoS Specs: Create/Delete, Manage Specs и Edit Consumer; ключи Create/Edit/Delete. | — | [CLI][S0577]; [UI1][S0578], [UI2][S0579], [UI3][S0580] |
| `openstack volume qos delete` | Удаление QoS spec и его key/value параметров | Есть | Admin Volume Types / QoS Specs: Create/Delete, Manage Specs и Edit Consumer; ключи Create/Edit/Delete. | — | [CLI][S0581]; [UI1][S0578], [UI2][S0579], [UI3][S0580] |
| `openstack volume qos disassociate` | Отвязка QoS spec от volume type | Есть | Manage QoS Spec Association; UI меняет association выбранного type, без глобального bulk сценария CLI. | — | [CLI][S0582]; [UI][S0576] |
| `openstack volume qos list` | Список QoS spec и его key/value параметров | Есть | Admin Volume Types / QoS Specs: Create/Delete, Manage Specs и Edit Consumer; ключи Create/Edit/Delete. | — | [CLI][S0583]; [UI1][S0578], [UI2][S0579], [UI3][S0580] |
| `openstack volume qos set` | Изменение QoS spec и его key/value параметров | Есть | Admin Volume Types / QoS Specs: Create/Delete, Manage Specs и Edit Consumer; ключи Create/Edit/Delete. | — | [CLI][S0584]; [UI1][S0578], [UI2][S0579], [UI3][S0580] |
| `openstack volume qos show` | Просмотр QoS spec и его key/value параметров | Есть | Admin Volume Types / QoS Specs: Create/Delete, Manage Specs и Edit Consumer; ключи Create/Edit/Delete. | — | [CLI][S0585]; [UI1][S0578], [UI2][S0579], [UI3][S0580] |
| `openstack volume qos unset` | Удаление свойств QoS spec и его key/value параметров | Есть | Admin Volume Types / QoS Specs: Create/Delete, Manage Specs и Edit Consumer; ключи Create/Edit/Delete. | — | [CLI][S0586]; [UI1][S0578], [UI2][S0579], [UI3][S0580] |
| `openstack volume revert` | Откат существующего тома к последнему snapshot | Нет | Create Volume from Snapshot создает другой том и не эквивалент revert. | — | [CLI][S0587]; [UI][S0588] |
| `openstack volume service list` | Список Cinder services и состояния | Есть | Admin System Information / Block Storage Services показывает binary/host/zone/status/state/update time. | — | [CLI][S0589]; [UI1][S0590], [UI2][S0464] |
| `openstack volume service set` | Enable/disable или сброс service state | Нет | Cinder Services table read-only: есть только FilterAction. | — | [CLI][S0591]; [UI][S0592] |
| `openstack volume set` | Имя, описание, размер, metadata, image metadata, status/attachment state, type, bootable, read-only | Частично | UI имеет Edit/Extend/Retype/Update Metadata/Admin Update Status; не предоставляет весь набор image-property, read-only и ручного attachment-state CLI. | — | [CLI][S0593]; [UI1][S0594], [UI2][S0595], [UI3][S0596], [UI4][S0597], [UI5][S0598] |
| `openstack volume show` | Детали тома | Есть | Overview, attachments, snapshots, messages; raw output CLI может содержать больше полей. | — | [CLI][S0599]; [UI1][S0600], [UI2][S0498] |
| `openstack volume snapshot create` | Создание snapshot тома | Есть | Create Snapshot в Volumes; in-use обрабатывается force в форме. | — | [CLI][S0601]; [UI][S0602] |
| `openstack volume snapshot delete` | Удаление volume snapshot | Есть | Delete Volume Snapshot в Project/Admin; UI ограничивает допустимые состояния. | — | [CLI][S0603]; [UI1][S0604], [UI2][S0474] |
| `openstack volume snapshot list` | Список volume snapshots | Есть | Project/Admin Snapshots и вкладка snapshots тома. | — | [CLI][S0605]; [UI1][S0606], [UI2][S0607] |
| `openstack volume snapshot set` | Имя/описание/metadata/status snapshot | Есть | Edit Snapshot, Update Metadata и Admin Update Snapshot Status. | — | [CLI][S0608]; [UI1][S0609], [UI2][S0610], [UI3][S0611] |
| `openstack volume snapshot show` | Детали volume snapshot | Есть | Snapshot Overview, metadata и Messages. | — | [CLI][S0612]; [UI][S0613] |
| `openstack volume snapshot unset` | Удаление metadata snapshot | Есть | Update Metadata позволяет удалить пользовательские ключи. | — | [CLI][S0614]; [UI][S0610] |
| `openstack volume summary` | Агрегированная статистика volumes API | Нет | Quota/usage панели не реализуют отдельный volume summary API и его сводку. | — | [CLI][S0615]; [UI][S0616] |
| `openstack volume transfer request accept` | Принятие transfer по ID и auth key | Есть | Accept Transfer в Volumes; quota/policy checks. | — | [CLI][S0617]; [UI1][S0618], [UI2][S0619] |
| `openstack volume transfer request create` | Создание transfer тома другому проекту | Есть | Create Transfer; показ и скачивание transfer credentials. CLI опция переноса/исключения snapshots отдельно не выставляется. | — | [CLI][S0620]; [UI1][S0621], [UI2][S0622] |
| `openstack volume transfer request delete` | Отмена transfer request | Есть | Cancel Transfer у volume в awaiting-transfer. | — | [CLI][S0623]; [UI][S0624] |
| `openstack volume transfer request list` | Список transfer requests | Частично | UI связывает transfers с volumes для Cancel Transfer; отдельной таблицы всех transfer requests нет. | — | [CLI][S0625]; [UI1][S0626], [UI2][S0624] |
| `openstack volume transfer request show` | Детали transfer request | Есть | ShowTransferView получает transfer_get и показывает credentials после создания; повторное получение auth key сервером не гарантируется. | — | [CLI][S0627]; [UI1][S0622], [UI2][S0628] |
| `openstack volume type create` | Создание volume type, extra specs, encryption и project access | Есть | Admin Volume Types: Create/Edit/Delete, Extra Specs/Metadata, Edit Access, Create/Update/Delete Encryption. CLI может объединять эти действия. | — | [CLI][S0629]; [UI1][S0630], [UI2][S0631], [UI3][S0632], [UI4][S0633] |
| `openstack volume type delete` | Удаление volume type, extra specs, encryption и project access | Есть | Admin Volume Types: Create/Edit/Delete, Extra Specs/Metadata, Edit Access, Create/Update/Delete Encryption. CLI может объединять эти действия. | — | [CLI][S0634]; [UI1][S0630], [UI2][S0631], [UI3][S0632], [UI4][S0633] |
| `openstack volume type list` | Список volume type, extra specs, encryption и project access | Есть | Admin Volume Types: Create/Edit/Delete, Extra Specs/Metadata, Edit Access, Create/Update/Delete Encryption. CLI может объединять эти действия. | — | [CLI][S0635]; [UI1][S0630], [UI2][S0631], [UI3][S0632], [UI4][S0633] |
| `openstack volume type set` | Изменение volume type, extra specs, encryption и project access | Есть | Admin Volume Types: Create/Edit/Delete, Extra Specs/Metadata, Edit Access, Create/Update/Delete Encryption. CLI может объединять эти действия. | — | [CLI][S0636]; [UI1][S0630], [UI2][S0631], [UI3][S0632], [UI4][S0633] |
| `openstack volume type show` | Просмотр volume type, extra specs, encryption и project access | Есть | Admin Volume Types: Create/Edit/Delete, Extra Specs/Metadata, Edit Access, Create/Update/Delete Encryption. CLI может объединять эти действия. | — | [CLI][S0637]; [UI1][S0630], [UI2][S0631], [UI3][S0632], [UI4][S0633] |
| `openstack volume type unset` | Удаление свойств volume type, extra specs, encryption и project access | Есть | Admin Volume Types: Create/Edit/Delete, Extra Specs/Metadata, Edit Access, Create/Update/Delete Encryption. CLI может объединять эти действия. | — | [CLI][S0638]; [UI1][S0630], [UI2][S0631], [UI3][S0632], [UI4][S0633] |
| `openstack volume unset` | Удаление volume metadata или volume image metadata | Частично | Update Metadata покрывает обычные свойства; отдельного удаления image-property не обнаружено. | — | [CLI][S0639]; [UI][S0597] |


<a id="glance"></a>
### 12.5. Glance — образы


**41 регистраций.** CLI: `python-openstackclient 7.4.0`. Namespace: `openstack.image.v2`.


#### Glance: images, sharing, import и cache — 21 команда

##### Основные image-команды — 7

`image create/delete/list/show` имеют основные UI-соответствия. Create включает загрузку файла, основные свойства и metadata; image из тома создается через Cinder Upload to Image. `image save` — `no`: штатный action registry не предоставляет Download Image. `image set/unset` — `partial`: Edit Image/Update Metadata покрывают многие свойства, но не image membership status, весь набор tags и низкоуровневых параметров CLI. [Angular action registry:60](https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/static/app/core/images/actions/actions.module.js#L60), [Create Image service](https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/static/app/core/images/actions/create.action.service.js), [metadata action](https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/static/app/core/images/actions/update-metadata.action.service.js).

В Horizon 25.3.0 **`ANGULAR_FEATURES['images_panel'] = True`**. Angular registry содержит **Deactivate Image/Reactivate Image**, которые соответствуют возможностям `image set --deactivate/--activate`; эти действия нельзя потерять, проверяя только старые Django `tables.py`. Если локальная конфигурация выбирает legacy-панель, состав видимых действий меняется. [defaults.py:521](https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/defaults.py#L521), [Deactivate/Reactivate registration:90](https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/static/app/core/images/actions/actions.module.js#L90).

Режим загрузки отдельно задается `HORIZON_IMAGES_UPLOAD_MODE` (`legacy` по умолчанию; возможны direct/off), а `IMAGES_ALLOW_LOCATION=False` по умолчанию. Поэтому возможность файла/URL зависит от конкретной конфигурации, и наличие source-field в коде не гарантирует его видимость. [defaults.py:213](https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/defaults.py#L213).

##### Image membership — 4 команды

`image add project`, `image remove project`, `image member list`, `image member get` — `no`. Shared visibility сама по себе не предоставляет UI управления membership. Также `image set --accept/--reject/--pending` не покрывается обычным Edit Image. [CLI image.py:227](https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/image/v2/image.py#L227), [CLI membership state options:1223](https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/image/v2/image.py#L1223), [штатный полный registry](https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/static/app/core/images/actions/actions.module.js#L60).

##### Stage/import/tasks/stores — 6 команд

`image stage`, `image import`, `image import info`, `image task list/show`, `image stores list` — `no`. CLI предоставляет stage и запуск interoperable import методами `glance-direct`, `web-download`, `glance-download`, `copy-image`, discovery методов/stores и просмотр asynchronous tasks. Возможности метода и multistore зависят от сервера. [CLI ImportImage:1604](https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/image/v2/image.py#L1604), [CLI task.py](https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/image/v2/task.py), [CLI info.py](https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/image/v2/info.py).

У Horizon есть исторические поля `import_data`/`copy_from` в create flow, но исследованная цепочка вызывает `images.create`, `images.add_location` или `images.upload`, а не `image_import`/stage API. Совпадение слова import недостаточно для функционального эквивалента современной CLI-команде. Status image также не является Task API browser. [REST create:238](https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/api/rest/glance.py#L238), [backend image_create:455](https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/api/glance.py#L455).

##### Glance cache — 4 команды

`cached image list/queue/delete/clear` — `no`: штатной панели управления Glance image cache нет. Настройки web/session cache Horizon относятся к другому механизму. [CLI cache.py](https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/image/v2/cache.py), [image action registry](https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/static/app/core/images/actions/actions.module.js#L60).

#### Glance metadata definitions — 20 команд

Эти команды управляют **определениями** метаданных, а не значениями custom properties конкретного image. Их UI — **Admin → Metadata Definitions**; Update Metadata у image является другим интерфейсом.

| Семейство | Число | Соответствие Horizon |
|---|---:|---|
| `image metadef namespace create/delete/list/show` | 4 | `yes`: Import Namespace из JSON файла/direct input, Delete, таблица, Overview/Contents |
| `image metadef namespace set` | 1 | `partial`: только public/private и protected; не редактор display name/description |
| `image metadef object create/show/list/delete/update` + `object property show` | 6 | Create — `partial`, можно включить объект в JSON нового namespace; show/list/property show — `partial`, видны в Contents JSON; delete/update — `no` для existing namespace |
| `image metadef property create/delete/list/set/show` | 5 | Create — `partial` через новый namespace JSON; list/show — `partial` через Contents; delete/set — `no` для existing namespace |
| `image metadef resource type list` | 1 | `partial`: список выбора внутри Manage Resource Type Associations |
| `image metadef resource type association create/delete/list` | 3 | `yes`: Manage Resource Type Associations читает и записывает выбранный набор связей |

Import Namespace декодирует полный JSON и передает его созданию namespace. Это позволяет определить вложенные objects/properties при создании, но не является отдельной операцией добавления/изменения объекта уже существующего namespace. Edit Namespace меняет только visibility/protected. Contents показывает JSON определения и позволяет увидеть nested properties без специальных списков/карточек. [CreateNamespaceForm:34](https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/admin/metadata_defs/forms.py#L34), [UpdateNamespaceForm:147](https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/admin/metadata_defs/forms.py#L147), [ContentsTab:45](https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/admin/metadata_defs/tabs.py#L45).

Manage Resource Type Associations читает JSON выбора, удаляет прежние associations и создает выбранные с параметрами, включая prefix/properties target. Это полноценное основное UI-соответствие association create/delete/list, хотя workflow обновляет весь набор. [ManageResourceTypesForm:116](https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/admin/metadata_defs/forms.py#L116), [ManageResourceTypes view:157](https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/admin/metadata_defs/views.py#L157).


| Команда | Возможность | Horizon | Пояснение / ограничение | Наш слой | Источники |
| --- | --- | --- | --- | --- | --- |
| `openstack cached image clear` | Очистка Glance image cache | Нет | Нет панели cache list/queue/delete/clear. Кэш Horizon и Glance image cache — разные объекты. | — | [CLI][S0640]; [UI][S0641] |
| `openstack cached image delete` | Удаление Glance image cache | Нет | Нет панели cache list/queue/delete/clear. Кэш Horizon и Glance image cache — разные объекты. | — | [CLI][S0642]; [UI][S0641] |
| `openstack cached image list` | Список Glance image cache | Нет | Нет панели cache list/queue/delete/clear. Кэш Horizon и Glance image cache — разные объекты. | — | [CLI][S0643]; [UI][S0641] |
| `openstack cached image queue` | Постановка в очередь Glance image cache | Нет | Нет панели cache list/queue/delete/clear. Кэш Horizon и Glance image cache — разные объекты. | — | [CLI][S0644]; [UI][S0641] |
| `openstack image add project` | Добавление проекта в image membership | Нет | Visibility shared в Edit/Create Image не является интерфейсом управления members; таких действий в registry нет. | — | [CLI][S0645]; [UI][S0641] |
| `openstack image create` | Создание image с загрузкой данных/метаданных; image из volume | Есть | Create Image, metadata шаг; Upload to Image из Cinder volume. Режим загрузки/URL зависит от настроек; полный Glance import/stores workflow отсутствует. | — | [CLI][S0646]; [UI1][S0647], [UI2][S0648], [UI3][S0649], [UI4][S0650] |
| `openstack image delete` | Удаление image | Есть | Delete Image одиночно или bulk; удаление только из конкретного multistore не представлено отдельно. | — | [CLI][S0651]; [UI1][S0652], [UI2][S0653] |
| `openstack image import` | Запуск interoperable image import: glance-direct/web-download/copy-image/glance-download | Нет | Create Image import_data/copy_from исторического upload flow не вызывает современный image_import и не дает выбора методов/stores. | — | [CLI][S0654]; [UI1][S0647], [UI2][S0655], [UI3][S0650] |
| `openstack image import info` | Discovery поддерживаемых image import methods | Нет | Нет UI import methods discovery. | — | [CLI][S0656]; [UI][S0641] |
| `openstack image list` | Список images и фильтрация | Есть | Project/Admin Images; backend filters и output formats CLI отличаются. | — | [CLI][S0657]; [UI1][S0658], [UI2][S0659] |
| `openstack image member get` | Детали image member | Нет | Visibility shared в Edit/Create Image не является интерфейсом управления members; таких действий в registry нет. | — | [CLI][S0660]; [UI][S0641] |
| `openstack image member list` | Список image members | Нет | Visibility shared в Edit/Create Image не является интерфейсом управления members; таких действий в registry нет. | — | [CLI][S0661]; [UI][S0641] |
| `openstack image metadef namespace create` | Создание namespace определений метаданных | Есть | Admin Metadata Definitions / Import Namespace принимает JSON файл или direct JSON целиком. | — | [CLI][S0662]; [UI1][S0663], [UI2][S0664] |
| `openstack image metadef namespace delete` | Удаление namespace метаданных | Есть | Delete Namespace. | — | [CLI][S0665]; [UI][S0666] |
| `openstack image metadef namespace list` | Список namespace метаданных | Есть | Admin Metadata Definitions с фильтрами и pagination. | — | [CLI][S0667]; [UI][S0668] |
| `openstack image metadef namespace set` | Изменение атрибутов namespace | Частично | Edit Namespace позволяет public/private и protected; не отдельные display_name/description поля CLI. | — | [CLI][S0669]; [UI][S0670] |
| `openstack image metadef namespace show` | Детали namespace метаданных | Есть | Namespace Overview и Contents с полным JSON. | — | [CLI][S0671]; [UI][S0672] |
| `openstack image metadef object create` | Создание объекта определения метаданных | Частично | Можно включить в импорт нового namespace JSON; отдельного добавления в существующий namespace UI нет. | — | [CLI][S0673]; [UI][S0663] |
| `openstack image metadef object delete` | Удаление объекта определения метаданных | Нет | Нет отдельного CRUD объектов/свойств в существующем namespace; Edit Namespace меняет только visibility/protected. | — | [CLI][S0674]; [UI1][S0675], [UI2][S0670] |
| `openstack image metadef object list` | Список объекта определения метаданных | Частично | Содержимое доступно через namespace Contents JSON; отдельного списка/карточки объектов или свойств нет. | — | [CLI][S0676]; [UI][S0677] |
| `openstack image metadef object property show` | Просмотр свойства внутри metadef object | Частично | Видно внутри namespace Contents JSON, отдельной карточки property нет. | — | [CLI][S0678]; [UI][S0677] |
| `openstack image metadef object show` | Просмотр объекта определения метаданных | Частично | Содержимое доступно через namespace Contents JSON; отдельного списка/карточки объектов или свойств нет. | — | [CLI][S0679]; [UI][S0677] |
| `openstack image metadef object update` | Изменение объекта определения метаданных | Нет | Нет отдельного CRUD объектов/свойств в существующем namespace; Edit Namespace меняет только visibility/protected. | — | [CLI][S0680]; [UI1][S0675], [UI2][S0670] |
| `openstack image metadef property create` | Создание свойства определения метаданных | Частично | Можно включить в импорт нового namespace JSON; отдельного добавления в существующий namespace UI нет. | — | [CLI][S0681]; [UI][S0663] |
| `openstack image metadef property delete` | Удаление свойства определения метаданных | Нет | Нет отдельного CRUD объектов/свойств в существующем namespace; Edit Namespace меняет только visibility/protected. | — | [CLI][S0682]; [UI1][S0675], [UI2][S0670] |
| `openstack image metadef property list` | Список свойства определения метаданных | Частично | Содержимое доступно через namespace Contents JSON; отдельного списка/карточки объектов или свойств нет. | — | [CLI][S0683]; [UI][S0677] |
| `openstack image metadef property set` | Изменение свойства определения метаданных | Нет | Нет отдельного CRUD объектов/свойств в существующем namespace; Edit Namespace меняет только visibility/protected. | — | [CLI][S0684]; [UI1][S0675], [UI2][S0670] |
| `openstack image metadef property show` | Просмотр свойства определения метаданных | Частично | Содержимое доступно через namespace Contents JSON; отдельного списка/карточки объектов или свойств нет. | — | [CLI][S0685]; [UI][S0677] |
| `openstack image metadef resource type association create` | Создание связей namespace с resource type | Есть | Manage Resource Type Associations читает и записывает набор associations, включая prefix/properties target; изменение списка одним workflow. | — | [CLI][S0686]; [UI1][S0687], [UI2][S0688] |
| `openstack image metadef resource type association delete` | Удаление связей namespace с resource type | Есть | Manage Resource Type Associations читает и записывает набор associations, включая prefix/properties target; изменение списка одним workflow. | — | [CLI][S0689]; [UI1][S0687], [UI2][S0688] |
| `openstack image metadef resource type association list` | Список связей namespace с resource type | Есть | Manage Resource Type Associations читает и записывает набор associations, включая prefix/properties target; изменение списка одним workflow. | — | [CLI][S0690]; [UI1][S0687], [UI2][S0688] |
| `openstack image metadef resource type list` | Список известных resource types для metadata definitions | Частично | Список используется в Manage Resource Type Associations, отдельной самостоятельной таблицы нет. | — | [CLI][S0691]; [UI][S0688] |
| `openstack image remove project` | Удаление проекта из image membership | Нет | Visibility shared в Edit/Create Image не является интерфейсом управления members; таких действий в registry нет. | — | [CLI][S0692]; [UI][S0641] |
| `openstack image save` | Скачивание binary image в локальный файл/stdout | Нет | В штатном image action registry нет Download/Save Image; Upload и Create Volume — другие операции. | — | [CLI][S0693]; [UI][S0641] |
| `openstack image set` | Изменение image attributes/properties/tags, activate/deactivate, membership status | Частично | Edit Image/Update Metadata и Angular Deactivate/Reactivate доступны; членство accept/reject/pending и прочие низкоуровневые параметры не представлены. | — | [CLI][S0694]; [UI1][S0695], [UI2][S0696], [UI3][S0697] |
| `openstack image show` | Подробности image и свойства | Есть | Image details/overview/metadata; нет гарантии отображения каждого raw API поля. | — | [CLI][S0698]; [UI][S0699] |
| `openstack image stage` | Загрузка image data в staging area Glance import API | Нет | Create Image upload вызывает images.upload; отдельного stage действия нет. | — | [CLI][S0700]; [UI1][S0647], [UI2][S0650] |
| `openstack image stores list` | Discovery Glance multistore backends | Нет | Нет панели/выбора Glance stores в штатном Images UI. | — | [CLI][S0701]; [UI][S0641] |
| `openstack image task list` | Список Glance asynchronous tasks | Нет | Нет панели task API; статус самого image не является списком задач. | — | [CLI][S0702]; [UI][S0641] |
| `openstack image task show` | Детали Glance asynchronous task | Нет | Нет карточки task API. | — | [CLI][S0703]; [UI][S0641] |
| `openstack image unset` | Удаление image custom properties/tags | Частично | Update Metadata позволяет удалять custom properties; отдельного интерфейса управления image tags не найдено. | — | [CLI][S0704]; [UI][S0697] |


<a id="keystone"></a>
### 12.6. Keystone — идентификация и доступ


**128 регистраций.** CLI: `python-openstackclient 7.4.0`. Namespace: `openstack.identity.v3`.


#### Identity v3: все семейства команд

| Семейство | Функциональность CLI | Horizon 25.3.0 |
|---|---|---|
| `access rule` | List/show/delete правил доступа application credential как отдельных объектов | Create и Details показывают service/method/path rules одного credential; нет отдельного owner-wide списка, rule ID lookup и удаления rules |
| `application credential` | Create/delete/list/show; secret, роли, срок, access rules и unrestricted | Create/list/detail/delete есть. Access rules зависят от Keystone API/настроек; UI действует в контексте пользователя |
| `catalog` | Каталог endpoint сервисов доступного scope | Данные в API Access/System Information; это не администрирование всех endpoint |
| `consumer` | OAuth1 consumer create/delete/list/show/set | Самостоятельного UI нет |
| `credential` | Произвольные Keystone credentials: user, type, blob, project; CRUD | Credentials panel имеет create/edit/delete/list; перечень типов/полей формы ограничен, отдельной полноценной show-страницы нет |
| `domain` | Create/delete/list/show/set, enabled и свойства | Domains CRUD и membership есть; данные show представлены таблицей/Edit; не все произвольные свойства CLI доступны |
| `ec2 credentials` | Create/delete/list/show специализированных EC2 access/secret | При ec2 endpoint API Access даёт View/Download и Recreate ключа текущего пользователя/проекта. Не полный CLI scope. Получение credentials может создать ключ, если его ещё нет |
| `endpoint` | CRUD endpoint, enabled, region/interface/service; привязка к проекту | Только данные каталога в API Access/System Information; CRUD и endpoint-filter назначения нет |
| `endpoint group` | CRUD и групповой доступ проектов к endpoint | Нет |
| `federation domain/project` | Доступные unscoped SAML domains/projects | Есть пользовательские login/scope-сценарии, но не отдельный операторский вывод этих запросов |
| `federation protocol` | Create/delete/list/show/set связи protocol ↔ mapping у IdP | Add/Remove и таблица связей есть; Update Protocol нет |
| `group` | CRUD групп, add/remove/contains user | Groups CRUD и Manage Members есть; contains представлен просмотром членов, некоторые свойства CLI отсутствуют |
| `identity provider` | CRUD IdP, remote identifiers и enabled | Register/Edit/Delete/list/details и Manage Protocols есть |
| `implied role` | Create/delete/list наследования ролей | Нет отдельного UI |
| `limit` | Unified project limits CRUD | Нет отдельного UI; старые Nova/Cinder/Neutron quota формы не заменяют Keystone unified limits |
| `mapping` | CRUD federation mapping rules | Create/Edit/Delete/list есть, JSON rules редактируются; show представлен данными/Edit |
| `policy` | CRUD объектов Keystone policy | Нет. Это не редактирование `policy.yaml` каждого OpenStack-сервиса |
| `project` | CRUD проектов, domain/parent/tags/properties и другие режимы | Основной CRUD, membership и quotas; формы не покрывают все CLI поля/режимы |
| `region` | CRUD service catalog regions | Region используется в контексте/каталоге; отдельного CRUD нет |
| `registered limit` | CRUD зарегистрированных лимитов Keystone | Нет |
| `role` | CRUD ролей и add/remove назначений | Roles CRUD с ограниченными полями. Project/domain membership задаёт назначения; полного system/inherited scope интерфейса нет |
| `role assignment` | List назначений с user/group/project/domain/system/effective/inherited режимами | Пользовательские role assignments и membership показывают часть, но не единый полный административный запрос |
| `service` | CRUD записей сервисов Keystone | System Information читает пользовательский service catalog; CRUD отсутствует |
| `service provider` | CRUD Keystone-to-Keystone federation SP | Нет. Не следует смешивать с реализованными Identity Providers |
| `trust` | Create/delete/list/show делегирования trust | Нет отдельной операторской панели; внутреннее применение trust сервисами — другая функция |
| `user` | Create/delete/list/show/set и password set | Users CRUD, enable/disable и смена пароля есть; не все дополнительные CLI поля доступны |
| `access token`, `request token`, `token` | OAuth1 request/access token flow, issue/revoke Keystone token | Login/logout используют токены внутри; нет универсальной формы произвольного issue/revoke/OAuth1 flow |

Первичный CLI inventory: [setup.cfg, Identity v3](https://github.com/openstack/python-openstackclient/blob/7.4.0/setup.cfg#L212). Реальные UI регистрации: [Identity panels](https://github.com/openstack/horizon/tree/25.3.0/openstack_dashboard/dashboards/identity), [enabled](https://github.com/openstack/horizon/tree/25.3.0/openstack_dashboard/enabled).

Важные проверенные места: [Application credential forms](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/identity/application_credentials/forms.py), [Credentials forms](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/identity/credentials/forms.py), [Protocol actions](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/identity/identity_providers/protocols/tables.py), [EC2 actions](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/api_access/tables.py), [EC2 get-or-create](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/api_access/views.py#L42), [role form только name](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/identity/roles/forms.py), [service table](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/info/tables.py#L73).


| Команда | Возможность | Horizon | Пояснение / ограничение | Наш слой | Источники |
| --- | --- | --- | --- | --- | --- |
| `openstack access rule delete` | Просмотр/удаление application credential access rule как отдельного ресурса | Нет | Create и Details application credential содержат service/method/path rules. Нет rule ID, отдельного owner-wide списка/lookup и удаления rules. | — | [CLI][S0001]; [UI][S0705] |
| `openstack access rule list` | Просмотр/удаление application credential access rule как отдельного ресурса | Частично | Create и Details application credential содержат service/method/path rules. Нет rule ID, отдельного owner-wide списка/lookup и удаления rules. | — | [CLI][S0001]; [UI][S0705] |
| `openstack access rule show` | Просмотр/удаление application credential access rule как отдельного ресурса | Частично | Create и Details application credential содержат service/method/path rules. Нет rule ID, отдельного owner-wide списка/lookup и удаления rules. | — | [CLI][S0001]; [UI][S0705] |
| `openstack access token create` | Токены Keystone/OAuth1: access token create | Нет | Login/logout используют токены внутри; нет эквивалентного инструмента выдачи/отзыва произвольного токена или OAuth1 request/access-token. | — | [CLI][S0001]; [UI][S0706] |
| `openstack application credential create` | Identity: application credential create | Частично | Create задаёт secret, срок, roles, unrestricted и access_rules при поддержке API; действует в контексте текущего пользователя/проекта. | — | [CLI][S0001]; [UI][S0707] |
| `openstack application credential delete` | Identity: application credential delete | Есть | Реализовано основное действие/просмотр; видимость и доступ определяются policy и scope. | — | [CLI][S0001]; [UI][S0707] |
| `openstack application credential list` | Identity: application credential list | Есть | Реализовано основное действие/просмотр; видимость и доступ определяются policy и scope. | — | [CLI][S0001]; [UI][S0707] |
| `openstack application credential show` | Identity: application credential show | Есть | Реализовано основное действие/просмотр; видимость и доступ определяются policy и scope. | — | [CLI][S0001]; [UI][S0707] |
| `openstack catalog list` | Каталог сервисов/endpoint/region: catalog list | Частично | System Information показывает пользовательский service catalog с endpoint; это не полный административный список всех объектов/полей. CRUD отсутствует. | — | [CLI][S0001]; [UI][S0003] |
| `openstack catalog show` | Каталог сервисов/endpoint/region: catalog show | Частично | System Information показывает пользовательский service catalog с endpoint; это не полный административный список всех объектов/полей. CRUD отсутствует. | — | [CLI][S0001]; [UI][S0003] |
| `openstack consumer create` | Управление: OAuth1 consumers | Нет | Нет самостоятельной панели или пользовательского действия этой группы. | — | [CLI][S0001]; [UI][S0706] |
| `openstack consumer delete` | Управление: OAuth1 consumers | Нет | Нет самостоятельной панели или пользовательского действия этой группы. | — | [CLI][S0001]; [UI][S0706] |
| `openstack consumer list` | Управление: OAuth1 consumers | Нет | Нет самостоятельной панели или пользовательского действия этой группы. | — | [CLI][S0001]; [UI][S0706] |
| `openstack consumer set` | Управление: OAuth1 consumers | Нет | Нет самостоятельной панели или пользовательского действия этой группы. | — | [CLI][S0001]; [UI][S0706] |
| `openstack consumer show` | Управление: OAuth1 consumers | Нет | Нет самостоятельной панели или пользовательского действия этой группы. | — | [CLI][S0001]; [UI][S0706] |
| `openstack credential create` | Identity: credential create | Частично | Create/Edit форма покрывает предусмотренные поля; произвольные дополнительные свойства/все режимы CLI не представлены. | — | [CLI][S0001]; [UI][S0708] |
| `openstack credential delete` | Identity: credential delete | Есть | Реализовано основное действие/просмотр; видимость и доступ определяются policy и scope. | — | [CLI][S0001]; [UI][S0708] |
| `openstack credential list` | Identity: credential list | Есть | Реализовано основное действие/просмотр; видимость и доступ определяются policy и scope. | — | [CLI][S0001]; [UI][S0708] |
| `openstack credential set` | Identity: credential set | Частично | Create/Edit форма покрывает предусмотренные поля; произвольные дополнительные свойства/все режимы CLI не представлены. | — | [CLI][S0001]; [UI][S0708] |
| `openstack credential show` | Identity: credential show | Частично | Данные доступны в таблице/Edit или membership; нет полноценной отдельной страницы всех полей show. | — | [CLI][S0001]; [UI][S0708] |
| `openstack domain create` | Identity: domain create | Частично | Create/Edit форма покрывает предусмотренные поля; произвольные дополнительные свойства/все режимы CLI не представлены. | — | [CLI][S0001]; [UI][S0709] |
| `openstack domain delete` | Identity: domain delete | Есть | Реализовано основное действие/просмотр; видимость и доступ определяются policy и scope. | — | [CLI][S0001]; [UI][S0709] |
| `openstack domain list` | Identity: domain list | Есть | Реализовано основное действие/просмотр; видимость и доступ определяются policy и scope. | — | [CLI][S0001]; [UI][S0709] |
| `openstack domain set` | Identity: domain set | Частично | Create/Edit форма покрывает предусмотренные поля; произвольные дополнительные свойства/все режимы CLI не представлены. | — | [CLI][S0001]; [UI][S0709] |
| `openstack domain show` | Identity: domain show | Частично | Данные доступны в таблице/Edit или membership; нет полноценной отдельной страницы всех полей show. | — | [CLI][S0001]; [UI][S0709] |
| `openstack ec2 credentials create` | Специализированные EC2 credentials пользователя | Частично | API Access при ec2 endpoint умеет View/Download и Recreate credentials текущего пользователя/проекта; ключ создаётся при отсутствии. Нет произвольного полного list/delete scope CLI. | — | [CLI][S0001]; [UI][S0710] |
| `openstack ec2 credentials delete` | Специализированные EC2 credentials пользователя | Частично | API Access при ec2 endpoint умеет View/Download и Recreate credentials текущего пользователя/проекта; ключ создаётся при отсутствии. Нет произвольного полного list/delete scope CLI. | — | [CLI][S0001]; [UI][S0710] |
| `openstack ec2 credentials list` | Специализированные EC2 credentials пользователя | Частично | API Access при ec2 endpoint умеет View/Download и Recreate credentials текущего пользователя/проекта; ключ создаётся при отсутствии. Нет произвольного полного list/delete scope CLI. | — | [CLI][S0001]; [UI][S0710] |
| `openstack ec2 credentials show` | Специализированные EC2 credentials пользователя | Частично | API Access при ec2 endpoint умеет View/Download и Recreate credentials текущего пользователя/проекта; ключ создаётся при отсутствии. Нет произвольного полного list/delete scope CLI. | — | [CLI][S0001]; [UI][S0710] |
| `openstack endpoint add project` | Каталог сервисов/endpoint/region: endpoint add project | Нет | System Information показывает пользовательский service catalog с endpoint; это не полный административный список всех объектов/полей. CRUD отсутствует. | — | [CLI][S0001]; [UI][S0003] |
| `openstack endpoint create` | Каталог сервисов/endpoint/region: endpoint create | Нет | System Information показывает пользовательский service catalog с endpoint; это не полный административный список всех объектов/полей. CRUD отсутствует. | — | [CLI][S0001]; [UI][S0003] |
| `openstack endpoint delete` | Каталог сервисов/endpoint/region: endpoint delete | Нет | System Information показывает пользовательский service catalog с endpoint; это не полный административный список всех объектов/полей. CRUD отсутствует. | — | [CLI][S0001]; [UI][S0003] |
| `openstack endpoint group add project` | Управление: группы endpoint и доступ проектов | Нет | Нет самостоятельной панели или пользовательского действия этой группы. | — | [CLI][S0001]; [UI][S0706] |
| `openstack endpoint group create` | Управление: группы endpoint и доступ проектов | Нет | Нет самостоятельной панели или пользовательского действия этой группы. | — | [CLI][S0001]; [UI][S0706] |
| `openstack endpoint group delete` | Управление: группы endpoint и доступ проектов | Нет | Нет самостоятельной панели или пользовательского действия этой группы. | — | [CLI][S0001]; [UI][S0706] |
| `openstack endpoint group list` | Управление: группы endpoint и доступ проектов | Нет | Нет самостоятельной панели или пользовательского действия этой группы. | — | [CLI][S0001]; [UI][S0706] |
| `openstack endpoint group remove project` | Управление: группы endpoint и доступ проектов | Нет | Нет самостоятельной панели или пользовательского действия этой группы. | — | [CLI][S0001]; [UI][S0706] |
| `openstack endpoint group set` | Управление: группы endpoint и доступ проектов | Нет | Нет самостоятельной панели или пользовательского действия этой группы. | — | [CLI][S0001]; [UI][S0706] |
| `openstack endpoint group show` | Управление: группы endpoint и доступ проектов | Нет | Нет самостоятельной панели или пользовательского действия этой группы. | — | [CLI][S0001]; [UI][S0706] |
| `openstack endpoint list` | Каталог сервисов/endpoint/region: endpoint list | Частично | System Information показывает пользовательский service catalog с endpoint; это не полный административный список всех объектов/полей. CRUD отсутствует. | — | [CLI][S0001]; [UI][S0003] |
| `openstack endpoint remove project` | Каталог сервисов/endpoint/region: endpoint remove project | Нет | System Information показывает пользовательский service catalog с endpoint; это не полный административный список всех объектов/полей. CRUD отсутствует. | — | [CLI][S0001]; [UI][S0003] |
| `openstack endpoint set` | Каталог сервисов/endpoint/region: endpoint set | Нет | System Information показывает пользовательский service catalog с endpoint; это не полный административный список всех объектов/полей. CRUD отсутствует. | — | [CLI][S0001]; [UI][S0003] |
| `openstack endpoint show` | Каталог сервисов/endpoint/region: endpoint show | Частично | System Information показывает пользовательский service catalog с endpoint; это не полный административный список всех объектов/полей. CRUD отсутствует. | — | [CLI][S0001]; [UI][S0003] |
| `openstack federation domain list` | Перечень доступных federation domains/projects для unscoped SAML | Частично | Federated login и выбор доступного scope дают пользовательский сценарий; отдельного экрана результата этих CLI-команд нет. | — | [CLI][S0001]; [UI][S0706] |
| `openstack federation project list` | Перечень доступных federation domains/projects для unscoped SAML | Частично | Federated login и выбор доступного scope дают пользовательский сценарий; отдельного экрана результата этих CLI-команд нет. | — | [CLI][S0001]; [UI][S0706] |
| `openstack federation protocol create` | Protocol ↔ mapping у identity provider | Есть | Есть Add/Remove Protocol и таблица Protocol ID/Mapping ID; Update Protocol отсутствует. | — | [CLI][S0001]; [UI][S0711] |
| `openstack federation protocol delete` | Protocol ↔ mapping у identity provider | Есть | Есть Add/Remove Protocol и таблица Protocol ID/Mapping ID; Update Protocol отсутствует. | — | [CLI][S0001]; [UI][S0711] |
| `openstack federation protocol list` | Protocol ↔ mapping у identity provider | Есть | Есть Add/Remove Protocol и таблица Protocol ID/Mapping ID; Update Protocol отсутствует. | — | [CLI][S0001]; [UI][S0711] |
| `openstack federation protocol set` | Protocol ↔ mapping у identity provider | Нет | Есть Add/Remove Protocol и таблица Protocol ID/Mapping ID; Update Protocol отсутствует. | — | [CLI][S0001]; [UI][S0711] |
| `openstack federation protocol show` | Protocol ↔ mapping у identity provider | Есть | Есть Add/Remove Protocol и таблица Protocol ID/Mapping ID; Update Protocol отсутствует. | — | [CLI][S0001]; [UI][S0711] |
| `openstack group add user` | Identity: group add user | Есть | Реализовано основное действие/просмотр; видимость и доступ определяются policy и scope. | — | [CLI][S0001]; [UI][S0712] |
| `openstack group contains user` | Identity: group contains user | Частично | Членство видно через Manage Members; отдельного булева contains-запроса UI нет. | — | [CLI][S0001]; [UI][S0712] |
| `openstack group create` | Identity: group create | Частично | Create/Edit форма покрывает предусмотренные поля; произвольные дополнительные свойства/все режимы CLI не представлены. | — | [CLI][S0001]; [UI][S0712] |
| `openstack group delete` | Identity: group delete | Есть | Реализовано основное действие/просмотр; видимость и доступ определяются policy и scope. | — | [CLI][S0001]; [UI][S0712] |
| `openstack group list` | Identity: group list | Есть | Реализовано основное действие/просмотр; видимость и доступ определяются policy и scope. | — | [CLI][S0001]; [UI][S0712] |
| `openstack group remove user` | Identity: group remove user | Есть | Реализовано основное действие/просмотр; видимость и доступ определяются policy и scope. | — | [CLI][S0001]; [UI][S0712] |
| `openstack group set` | Identity: group set | Частично | Create/Edit форма покрывает предусмотренные поля; произвольные дополнительные свойства/все режимы CLI не представлены. | — | [CLI][S0001]; [UI][S0712] |
| `openstack group show` | Identity: group show | Частично | Данные доступны в таблице/Edit или membership; нет полноценной отдельной страницы всех полей show. | — | [CLI][S0001]; [UI][S0712] |
| `openstack identity provider create` | Identity: identity provider create | Есть | Реализовано основное действие/просмотр; видимость и доступ определяются policy и scope. | — | [CLI][S0001]; [UI][S0713] |
| `openstack identity provider delete` | Identity: identity provider delete | Есть | Реализовано основное действие/просмотр; видимость и доступ определяются policy и scope. | — | [CLI][S0001]; [UI][S0713] |
| `openstack identity provider list` | Identity: identity provider list | Есть | Реализовано основное действие/просмотр; видимость и доступ определяются policy и scope. | — | [CLI][S0001]; [UI][S0713] |
| `openstack identity provider set` | Identity: identity provider set | Есть | Реализовано основное действие/просмотр; видимость и доступ определяются policy и scope. | — | [CLI][S0001]; [UI][S0713] |
| `openstack identity provider show` | Identity: identity provider show | Есть | Реализовано основное действие/просмотр; видимость и доступ определяются policy и scope. | — | [CLI][S0001]; [UI][S0713] |
| `openstack implied role create` | Управление: наследование ролей | Нет | Нет самостоятельной панели или пользовательского действия этой группы. | — | [CLI][S0001]; [UI][S0706] |
| `openstack implied role delete` | Управление: наследование ролей | Нет | Нет самостоятельной панели или пользовательского действия этой группы. | — | [CLI][S0001]; [UI][S0706] |
| `openstack implied role list` | Управление: наследование ролей | Нет | Нет самостоятельной панели или пользовательского действия этой группы. | — | [CLI][S0001]; [UI][S0706] |
| `openstack limit create` | Управление: Keystone unified limits | Нет | Нет самостоятельной панели или пользовательского действия этой группы. | — | [CLI][S0001]; [UI][S0706] |
| `openstack limit delete` | Управление: Keystone unified limits | Нет | Нет самостоятельной панели или пользовательского действия этой группы. | — | [CLI][S0001]; [UI][S0706] |
| `openstack limit list` | Управление: Keystone unified limits | Нет | Нет самостоятельной панели или пользовательского действия этой группы. | — | [CLI][S0001]; [UI][S0706] |
| `openstack limit set` | Управление: Keystone unified limits | Нет | Нет самостоятельной панели или пользовательского действия этой группы. | — | [CLI][S0001]; [UI][S0706] |
| `openstack limit show` | Управление: Keystone unified limits | Нет | Нет самостоятельной панели или пользовательского действия этой группы. | — | [CLI][S0001]; [UI][S0706] |
| `openstack mapping create` | Identity: mapping create | Есть | Реализовано основное действие/просмотр; видимость и доступ определяются policy и scope. | — | [CLI][S0001]; [UI][S0714] |
| `openstack mapping delete` | Identity: mapping delete | Есть | Реализовано основное действие/просмотр; видимость и доступ определяются policy и scope. | — | [CLI][S0001]; [UI][S0714] |
| `openstack mapping list` | Identity: mapping list | Есть | Реализовано основное действие/просмотр; видимость и доступ определяются policy и scope. | — | [CLI][S0001]; [UI][S0714] |
| `openstack mapping set` | Identity: mapping set | Есть | Реализовано основное действие/просмотр; видимость и доступ определяются policy и scope. | — | [CLI][S0001]; [UI][S0714] |
| `openstack mapping show` | Identity: mapping show | Частично | Данные доступны в таблице/Edit или membership; нет полноценной отдельной страницы всех полей show. | — | [CLI][S0001]; [UI][S0714] |
| `openstack policy create` | Управление: объекты Keystone policy | Нет | Нет самостоятельной панели или пользовательского действия этой группы. | — | [CLI][S0001]; [UI][S0706] |
| `openstack policy delete` | Управление: объекты Keystone policy | Нет | Нет самостоятельной панели или пользовательского действия этой группы. | — | [CLI][S0001]; [UI][S0706] |
| `openstack policy list` | Управление: объекты Keystone policy | Нет | Нет самостоятельной панели или пользовательского действия этой группы. | — | [CLI][S0001]; [UI][S0706] |
| `openstack policy set` | Управление: объекты Keystone policy | Нет | Нет самостоятельной панели или пользовательского действия этой группы. | — | [CLI][S0001]; [UI][S0706] |
| `openstack policy show` | Управление: объекты Keystone policy | Нет | Нет самостоятельной панели или пользовательского действия этой группы. | — | [CLI][S0001]; [UI][S0706] |
| `openstack project create` | Identity: project create | Частично | Create/Edit форма покрывает предусмотренные поля; произвольные дополнительные свойства/все режимы CLI не представлены. | — | [CLI][S0001]; [UI][S0006] |
| `openstack project delete` | Identity: project delete | Есть | Реализовано основное действие/просмотр; видимость и доступ определяются policy и scope. | — | [CLI][S0001]; [UI][S0006] |
| `openstack project list` | Identity: project list | Есть | Реализовано основное действие/просмотр; видимость и доступ определяются policy и scope. | — | [CLI][S0001]; [UI][S0006] |
| `openstack project set` | Identity: project set | Частично | Create/Edit форма покрывает предусмотренные поля; произвольные дополнительные свойства/все режимы CLI не представлены. | — | [CLI][S0001]; [UI][S0006] |
| `openstack project show` | Identity: project show | Есть | Реализовано основное действие/просмотр; видимость и доступ определяются policy и scope. | — | [CLI][S0001]; [UI][S0006] |
| `openstack region create` | Каталог сервисов/endpoint/region: region create | Нет | System Information показывает пользовательский service catalog с endpoint; это не полный административный список всех объектов/полей. CRUD отсутствует. | — | [CLI][S0001]; [UI][S0003] |
| `openstack region delete` | Каталог сервисов/endpoint/region: region delete | Нет | System Information показывает пользовательский service catalog с endpoint; это не полный административный список всех объектов/полей. CRUD отсутствует. | — | [CLI][S0001]; [UI][S0003] |
| `openstack region list` | Каталог сервисов/endpoint/region: region list | Частично | System Information показывает пользовательский service catalog с endpoint; это не полный административный список всех объектов/полей. CRUD отсутствует. | — | [CLI][S0001]; [UI][S0003] |
| `openstack region set` | Каталог сервисов/endpoint/region: region set | Нет | System Information показывает пользовательский service catalog с endpoint; это не полный административный список всех объектов/полей. CRUD отсутствует. | — | [CLI][S0001]; [UI][S0003] |
| `openstack region show` | Каталог сервисов/endpoint/region: region show | Частично | System Information показывает пользовательский service catalog с endpoint; это не полный административный список всех объектов/полей. CRUD отсутствует. | — | [CLI][S0001]; [UI][S0003] |
| `openstack registered limit create` | Управление: Keystone registered limits | Нет | Нет самостоятельной панели или пользовательского действия этой группы. | — | [CLI][S0001]; [UI][S0706] |
| `openstack registered limit delete` | Управление: Keystone registered limits | Нет | Нет самостоятельной панели или пользовательского действия этой группы. | — | [CLI][S0001]; [UI][S0706] |
| `openstack registered limit list` | Управление: Keystone registered limits | Нет | Нет самостоятельной панели или пользовательского действия этой группы. | — | [CLI][S0001]; [UI][S0706] |
| `openstack registered limit set` | Управление: Keystone registered limits | Нет | Нет самостоятельной панели или пользовательского действия этой группы. | — | [CLI][S0001]; [UI][S0706] |
| `openstack registered limit show` | Управление: Keystone registered limits | Нет | Нет самостоятельной панели или пользовательского действия этой группы. | — | [CLI][S0001]; [UI][S0706] |
| `openstack request token authorize` | Токены Keystone/OAuth1: request token authorize | Нет | Login/logout используют токены внутри; нет эквивалентного инструмента выдачи/отзыва произвольного токена или OAuth1 request/access-token. | — | [CLI][S0001]; [UI][S0706] |
| `openstack request token create` | Токены Keystone/OAuth1: request token create | Нет | Login/logout используют токены внутри; нет эквивалентного инструмента выдачи/отзыва произвольного токена или OAuth1 request/access-token. | — | [CLI][S0001]; [UI][S0706] |
| `openstack role add` | Identity: role add | Частично | Назначение/снятие ролей через membership проектов/доменов; CLI дополнительно выражает system/inherited и другие scope. | — | [CLI][S0001]; [UI][S0715] |
| `openstack role assignment list` | Просмотр назначения ролей | Частично | Есть роли пользователя и membership проектов/доменов; нет одного полного UI эквивалента всех system/inherited/effective/filter режимов CLI. | — | [CLI][S0001]; [UI][S0716] |
| `openstack role create` | Identity: role create | Частично | Create/Edit форма покрывает предусмотренные поля; произвольные дополнительные свойства/все режимы CLI не представлены. | — | [CLI][S0001]; [UI][S0715] |
| `openstack role delete` | Identity: role delete | Есть | Реализовано основное действие/просмотр; видимость и доступ определяются policy и scope. | — | [CLI][S0001]; [UI][S0715] |
| `openstack role list` | Identity: role list | Есть | Реализовано основное действие/просмотр; видимость и доступ определяются policy и scope. | — | [CLI][S0001]; [UI][S0715] |
| `openstack role remove` | Identity: role remove | Частично | Назначение/снятие ролей через membership проектов/доменов; CLI дополнительно выражает system/inherited и другие scope. | — | [CLI][S0001]; [UI][S0715] |
| `openstack role set` | Identity: role set | Частично | Create/Edit форма покрывает предусмотренные поля; произвольные дополнительные свойства/все режимы CLI не представлены. | — | [CLI][S0001]; [UI][S0715] |
| `openstack role show` | Identity: role show | Частично | Данные доступны в таблице/Edit или membership; нет полноценной отдельной страницы всех полей show. | — | [CLI][S0001]; [UI][S0715] |
| `openstack service create` | Каталог сервисов/endpoint/region: service create | Нет | System Information показывает пользовательский service catalog с endpoint; это не полный административный список всех объектов/полей. CRUD отсутствует. | — | [CLI][S0001]; [UI][S0003] |
| `openstack service delete` | Каталог сервисов/endpoint/region: service delete | Нет | System Information показывает пользовательский service catalog с endpoint; это не полный административный список всех объектов/полей. CRUD отсутствует. | — | [CLI][S0001]; [UI][S0003] |
| `openstack service list` | Каталог сервисов/endpoint/region: service list | Частично | System Information показывает пользовательский service catalog с endpoint; это не полный административный список всех объектов/полей. CRUD отсутствует. | — | [CLI][S0001]; [UI][S0003] |
| `openstack service provider create` | Управление: federation service providers | Нет | Нет самостоятельной панели или пользовательского действия этой группы. | — | [CLI][S0001]; [UI][S0706] |
| `openstack service provider delete` | Управление: federation service providers | Нет | Нет самостоятельной панели или пользовательского действия этой группы. | — | [CLI][S0001]; [UI][S0706] |
| `openstack service provider list` | Управление: federation service providers | Нет | Нет самостоятельной панели или пользовательского действия этой группы. | — | [CLI][S0001]; [UI][S0706] |
| `openstack service provider set` | Управление: federation service providers | Нет | Нет самостоятельной панели или пользовательского действия этой группы. | — | [CLI][S0001]; [UI][S0706] |
| `openstack service provider show` | Управление: federation service providers | Нет | Нет самостоятельной панели или пользовательского действия этой группы. | — | [CLI][S0001]; [UI][S0706] |
| `openstack service set` | Каталог сервисов/endpoint/region: service set | Нет | System Information показывает пользовательский service catalog с endpoint; это не полный административный список всех объектов/полей. CRUD отсутствует. | — | [CLI][S0001]; [UI][S0003] |
| `openstack service show` | Каталог сервисов/endpoint/region: service show | Частично | System Information показывает пользовательский service catalog с endpoint; это не полный административный список всех объектов/полей. CRUD отсутствует. | — | [CLI][S0001]; [UI][S0003] |
| `openstack token issue` | Токены Keystone/OAuth1: token issue | Нет | Login/logout используют токены внутри; нет эквивалентного инструмента выдачи/отзыва произвольного токена или OAuth1 request/access-token. | — | [CLI][S0001]; [UI][S0706] |
| `openstack token revoke` | Токены Keystone/OAuth1: token revoke | Нет | Login/logout используют токены внутри; нет эквивалентного инструмента выдачи/отзыва произвольного токена или OAuth1 request/access-token. | — | [CLI][S0001]; [UI][S0706] |
| `openstack trust create` | Управление: делегирование Keystone trusts | Нет | Нет самостоятельной панели или пользовательского действия этой группы. | — | [CLI][S0001]; [UI][S0706] |
| `openstack trust delete` | Управление: делегирование Keystone trusts | Нет | Нет самостоятельной панели или пользовательского действия этой группы. | — | [CLI][S0001]; [UI][S0706] |
| `openstack trust list` | Управление: делегирование Keystone trusts | Нет | Нет самостоятельной панели или пользовательского действия этой группы. | — | [CLI][S0001]; [UI][S0706] |
| `openstack trust show` | Управление: делегирование Keystone trusts | Нет | Нет самостоятельной панели или пользовательского действия этой группы. | — | [CLI][S0001]; [UI][S0706] |
| `openstack user create` | Identity: user create | Частично | Create/Edit форма покрывает предусмотренные поля; произвольные дополнительные свойства/все режимы CLI не представлены. | — | [CLI][S0001]; [UI][S0717] |
| `openstack user delete` | Identity: user delete | Есть | Реализовано основное действие/просмотр; видимость и доступ определяются policy и scope. | — | [CLI][S0001]; [UI][S0717] |
| `openstack user list` | Identity: user list | Есть | Реализовано основное действие/просмотр; видимость и доступ определяются policy и scope. | — | [CLI][S0001]; [UI][S0717] |
| `openstack user password set` | Identity: user password set | Частично | Create/Edit форма покрывает предусмотренные поля; произвольные дополнительные свойства/все режимы CLI не представлены. | — | [CLI][S0001]; [UI][S0717] |
| `openstack user set` | Identity: user set | Частично | Create/Edit форма покрывает предусмотренные поля; произвольные дополнительные свойства/все режимы CLI не представлены. | — | [CLI][S0001]; [UI][S0717] |
| `openstack user show` | Identity: user show | Есть | Реализовано основное действие/просмотр; видимость и доступ определяются policy и scope. | — | [CLI][S0001]; [UI][S0717] |


<a id="swift"></a>
### 12.7. Swift — объектное хранилище


**17 регистраций.** CLI: `python-openstackclient 7.4.0`. Namespace: `openstack.object_store.v1`.


#### Swift: все 17 команд

| Команды | CLI | Horizon |
|---|---|---|
| `container create/delete/list/show` | Контейнеры и их свойства/metadata | Создание/перечень/сведения есть. UI удаляет только пустые контейнеры, CLI имеет --recursive; create не принимает metadata, различается массовый режим |
| `container save` | Выгрузка содержимого контейнера в локальную файловую систему | Общего Save Container действия нет |
| `container set/unset` | Добавление/удаление metadata properties | Generic metadata editor отсутствует. Public/private toggle меняет доступ, а не эти properties |
| `object create/delete/list/show/save` | Загрузка, удаление, перечень, свойства и скачивание объектов | Upload/Delete/List/View Details/Download есть; набор параметров загрузки ограничен |
| `object set/unset` | Изменение/удаление metadata properties | Нет. Edit Object повторно загружает содержимое, что не равно metadata set/unset |
| `object store account set/show/unset` | Metadata Swift account | Отдельного account-management экрана нет |

У UI дополнительно есть Copy Object, Edit Object и представление каталогов/prefix. Поэтому «Horizon — строгое подмножество списка OSC-команд» было бы неверной моделью сравнения. Источники: [OSC object store registrations](https://github.com/openstack/python-openstackclient/blob/7.4.0/setup.cfg#L618), [Containers controller](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/static/dashboard/project/containers/containers.controller.js), [Object actions](https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/static/dashboard/project/containers/objects-row-actions.service.js).


| Команда | Возможность | Horizon | Пояснение / ограничение | Наш слой | Источники |
| --- | --- | --- | --- | --- | --- |
| `openstack container create` | Swift: container create | Частично | Создание/Upload есть; CLI допускает несколько имён контейнеров или файлов за вызов и файловые режимы. Metadata этими create-командами не задаются. | — | [CLI][S0001]; [UI][S0718] |
| `openstack container delete` | Swift: container delete | Частично | UI удаляет пустой контейнер; CLI дополнительно поддерживает --recursive. В UI сначала нужно удалить объекты. | — | [CLI][S0001]; [UI][S0718] |
| `openstack container list` | Swift: container list | Есть | Основной lifecycle/просмотр представлен в Containers; UI также имеет собственное Copy Object действие. | — | [CLI][S0001]; [UI][S0718] |
| `openstack container save` | Swift: container save | Нет | Нет штатной команды/кнопки выгрузки целого контейнера в локальный каталог; Download работает для объекта. | — | [CLI][S0001]; [UI][S0718] |
| `openstack container set` | Swift: container set | Нет | CLI меняет/удаляет metadata properties. Edit Object меняет содержимое, а public/private контейнера меняет доступ; это другие действия. | — | [CLI][S0001]; [UI][S0718] |
| `openstack container show` | Swift: container show | Частично | Есть список/сводные свойства контейнера; полный набор произвольных заголовков/metadata не выводится отдельной формой. | — | [CLI][S0001]; [UI][S0718] |
| `openstack container unset` | Swift: container unset | Нет | CLI меняет/удаляет metadata properties. Edit Object меняет содержимое, а public/private контейнера меняет доступ; это другие действия. | — | [CLI][S0001]; [UI][S0718] |
| `openstack object create` | Swift: object create | Частично | Создание/Upload есть; CLI допускает несколько имён контейнеров или файлов за вызов и файловые режимы. Metadata этими create-командами не задаются. | — | [CLI][S0001]; [UI][S0719] |
| `openstack object delete` | Swift: object delete | Есть | Основной lifecycle/просмотр представлен в Containers; UI также имеет собственное Copy Object действие. | — | [CLI][S0001]; [UI][S0719] |
| `openstack object list` | Swift: object list | Есть | Основной lifecycle/просмотр представлен в Containers; UI также имеет собственное Copy Object действие. | — | [CLI][S0001]; [UI][S0719] |
| `openstack object save` | Swift: object save | Есть | Основной lifecycle/просмотр представлен в Containers; UI также имеет собственное Copy Object действие. | — | [CLI][S0001]; [UI][S0719] |
| `openstack object set` | Swift: object set | Нет | CLI меняет/удаляет metadata properties. Edit Object меняет содержимое, а public/private контейнера меняет доступ; это другие действия. | — | [CLI][S0001]; [UI][S0719] |
| `openstack object show` | Swift: object show | Есть | Основной lifecycle/просмотр представлен в Containers; UI также имеет собственное Copy Object действие. | — | [CLI][S0001]; [UI][S0719] |
| `openstack object store account set` | Чтение/изменение metadata Swift account | Нет | Нет самостоятельного account-management экрана. | — | [CLI][S0001]; [UI][S0718] |
| `openstack object store account show` | Чтение/изменение metadata Swift account | Нет | Нет самостоятельного account-management экрана. | — | [CLI][S0001]; [UI][S0718] |
| `openstack object store account unset` | Чтение/изменение metadata Swift account | Нет | Нет самостоятельного account-management экрана. | — | [CLI][S0001]; [UI][S0718] |
| `openstack object unset` | Swift: object unset | Нет | CLI меняет/удаляет metadata properties. Edit Object меняет содержимое, а public/private контейнера меняет доступ; это другие действия. | — | [CLI][S0001]; [UI][S0719] |


<a id="masakari"></a>
### 12.8. Masakari — высокая доступность


**15 регистраций.** CLI: `python-masakariclient 8.6.0`. Namespace: `openstack.ha.v1`.


| Команда | Возможность | Horizon | Пояснение / ограничение | Наш слой | Источники |
| --- | --- | --- | --- | --- | --- |
| `openstack notification create` | Создание: уведомление Masakari | Нет | Панель Notifications только читает события/прогресс; Create отсутствует. | M1, M2 | [CLI][S0720]; [UI][S0721] |
| `openstack notification list` | Список: уведомление Masakari | Есть | Основная операция/результат представлены; нужны сервис, права и допустимое состояние. | M1, M2 | [CLI][S0722]; [UI][S0721] |
| `openstack notification show` | Просмотр: уведомление Masakari | Есть | Основная операция/результат представлены; нужны сервис, права и допустимое состояние. | M1, M2 | [CLI][S0723]; [UI][S0721] |
| `openstack notification vmove list` | Список: перемещения ВМ при восстановлении | Есть | Основная операция/результат представлены; нужны сервис, права и допустимое состояние. | M1, M2 | [CLI][S0724]; [UI][S0725] |
| `openstack notification vmove show` | Просмотр: перемещения ВМ при восстановлении | Есть | Основная операция/результат представлены; нужны сервис, права и допустимое состояние. | M1, M2 | [CLI][S0726]; [UI][S0725] |
| `openstack segment create` | Создание: HA-сегмент | Частично | UI ограничивает service_type/имя хоста и выбор Nova compute; CLI содержит дополнительные редактируемые поля. | M1, M2 | [CLI][S0727]; [UI][S0728] |
| `openstack segment delete` | Удаление: HA-сегмент | Есть | Основная операция/результат представлены; нужны сервис, права и допустимое состояние. | M1, M2 | [CLI][S0729]; [UI][S0728] |
| `openstack segment host create` | Создание: хост HA-сегмента | Частично | UI ограничивает service_type/имя хоста и выбор Nova compute; CLI содержит дополнительные редактируемые поля. | M1, M2 | [CLI][S0730]; [UI][S0731] |
| `openstack segment host delete` | Удаление: хост HA-сегмента | Есть | Основная операция/результат представлены; нужны сервис, права и допустимое состояние. | M1, M2 | [CLI][S0732]; [UI][S0731] |
| `openstack segment host list` | Список: хост HA-сегмента | Есть | Основная операция/результат представлены; нужны сервис, права и допустимое состояние. | M1, M2 | [CLI][S0733]; [UI][S0731] |
| `openstack segment host show` | Просмотр: хост HA-сегмента | Есть | Основная операция/результат представлены; нужны сервис, права и допустимое состояние. | M1, M2 | [CLI][S0734]; [UI][S0731] |
| `openstack segment host update` | Изменение: хост HA-сегмента | Частично | UI ограничивает service_type/имя хоста и выбор Nova compute; CLI содержит дополнительные редактируемые поля. | M1, M2 | [CLI][S0735]; [UI][S0731] |
| `openstack segment list` | Список: HA-сегмент | Есть | Основная операция/результат представлены; нужны сервис, права и допустимое состояние. | M1, M2 | [CLI][S0736]; [UI][S0728] |
| `openstack segment show` | Просмотр: HA-сегмент | Есть | Основная операция/результат представлены; нужны сервис, права и допустимое состояние. | M1, M2 | [CLI][S0737]; [UI][S0728] |
| `openstack segment update` | Изменение: HA-сегмент | Частично | UI ограничивает service_type/имя хоста и выбор Nova compute; CLI содержит дополнительные редактируемые поля. | M1, M2 | [CLI][S0738]; [UI][S0728] |


<a id="watcher"></a>
### 12.9. Watcher — оптимизация


**28 регистраций.** CLI: `python-watcherclient 4.8.0`. Namespace: `openstack.infra_optim.v1`.


| Команда | Возможность | Horizon | Пояснение / ограничение | Наш слой | Источники |
| --- | --- | --- | --- | --- | --- |
| `openstack optimize action list` | Список: действия Watcher | Есть | Основная операция/результат представлены; нужны сервис, права и допустимое состояние. | W1 | [CLI][S0739]; [UI][S0740] |
| `openstack optimize action show` | Просмотр: действия Watcher | Есть | Основная операция/результат представлены; нужны сервис, права и допустимое состояние. | W1 | [CLI][S0741]; [UI][S0740] |
| `openstack optimize actionplan cancel` | Отмена: план действий Watcher | Нет | Соответствующее пользовательское действие не зарегистрировано; ActionPlan Cancel закомментирован. | W1 | [CLI][S0742]; [UI][S0743] |
| `openstack optimize actionplan delete` | Удаление: план действий Watcher | Есть | Основная операция/результат представлены; нужны сервис, права и допустимое состояние. | W1 | [CLI][S0744]; [UI][S0743] |
| `openstack optimize actionplan list` | Список: план действий Watcher | Есть | Основная операция/результат представлены; нужны сервис, права и допустимое состояние. | W1 | [CLI][S0745]; [UI][S0743] |
| `openstack optimize actionplan show` | Просмотр: план действий Watcher | Есть | Основная операция/результат представлены; нужны сервис, права и допустимое состояние. | W1 | [CLI][S0746]; [UI][S0743] |
| `openstack optimize actionplan start` | Запуск: план действий Watcher | Есть | Основная операция/результат представлены; нужны сервис, права и допустимое состояние. | W1 | [CLI][S0747]; [UI][S0743] |
| `openstack optimize actionplan update` | Изменение: план действий Watcher | Нет | Соответствующее пользовательское действие не зарегистрировано; ActionPlan Cancel закомментирован. | W1 | [CLI][S0748]; [UI][S0743] |
| `openstack optimize audit create` | Создание: audit Watcher | Частично | Create из template, ONESHOT/CONTINUOUS/interval/auto-trigger; без EVENT, goal/strategy напрямую, parameters, force, start/end. | W1 | [CLI][S0749]; [UI][S0750] |
| `openstack optimize audit delete` | Удаление: audit Watcher | Есть | Основная операция/результат представлены; нужны сервис, права и допустимое состояние. | W1 | [CLI][S0751]; [UI][S0750] |
| `openstack optimize audit list` | Список: audit Watcher | Есть | Основная операция/результат представлены; нужны сервис, права и допустимое состояние. | W1 | [CLI][S0752]; [UI][S0750] |
| `openstack optimize audit show` | Просмотр: audit Watcher | Есть | Основная операция/результат представлены; нужны сервис, права и допустимое состояние. | W1 | [CLI][S0753]; [UI][S0750] |
| `openstack optimize audit update` | Изменение: audit Watcher | Частично | Есть только Cancel Audit через PATCH state=CANCELLED; общего update нет. | W1 | [CLI][S0754]; [UI][S0750] |
| `openstack optimize audittemplate create` | Создание: шаблон audit | Есть | Основная операция/результат представлены; нужны сервис, права и допустимое состояние. | W1 | [CLI][S0755]; [UI][S0756] |
| `openstack optimize audittemplate delete` | Удаление: шаблон audit | Есть | Основная операция/результат представлены; нужны сервис, права и допустимое состояние. | W1 | [CLI][S0757]; [UI][S0756] |
| `openstack optimize audittemplate list` | Список: шаблон audit | Есть | Основная операция/результат представлены; нужны сервис, права и допустимое состояние. | W1 | [CLI][S0758]; [UI][S0756] |
| `openstack optimize audittemplate show` | Просмотр: шаблон audit | Есть | Основная операция/результат представлены; нужны сервис, права и допустимое состояние. | W1 | [CLI][S0759]; [UI][S0756] |
| `openstack optimize audittemplate update` | Изменение: шаблон audit | Нет | Соответствующее пользовательское действие не зарегистрировано; ActionPlan Cancel закомментирован. | W1 | [CLI][S0760]; [UI][S0756] |
| `openstack optimize datamodel list` | Список: модель инфраструктуры Watcher | Нет | Нет панели scoring engines, services или data model. | W1 | [CLI][S0761]; [UI][S0762] |
| `openstack optimize goal list` | Список: цели оптимизации | Есть | Основная операция/результат представлены; нужны сервис, права и допустимое состояние. | W1 | [CLI][S0763]; [UI][S0764] |
| `openstack optimize goal show` | Просмотр: цели оптимизации | Есть | Основная операция/результат представлены; нужны сервис, права и допустимое состояние. | W1 | [CLI][S0765]; [UI][S0764] |
| `openstack optimize scoringengine list` | Список: механизмы оценки | Нет | Нет панели scoring engines, services или data model. | W1 | [CLI][S0766]; [UI][S0762] |
| `openstack optimize scoringengine show` | Просмотр: механизмы оценки | Нет | Нет панели scoring engines, services или data model. | W1 | [CLI][S0767]; [UI][S0762] |
| `openstack optimize service list` | Список: сервисы Watcher | Нет | Нет панели scoring engines, services или data model. | W1 | [CLI][S0768]; [UI][S0762] |
| `openstack optimize service show` | Просмотр: сервисы Watcher | Нет | Нет панели scoring engines, services или data model. | W1 | [CLI][S0769]; [UI][S0762] |
| `openstack optimize strategy list` | Список: стратегии оптимизации | Есть | Основная операция/результат представлены; нужны сервис, права и допустимое состояние. | W1 | [CLI][S0770]; [UI][S0771] |
| `openstack optimize strategy show` | Просмотр: стратегии оптимизации | Частично | Детали strategy есть, parameters_spec не выводится. | W1 | [CLI][S0772]; [UI][S0771] |
| `openstack optimize strategy state` | Просмотр состояния: стратегии оптимизации | Нет | Соответствующее пользовательское действие не зарегистрировано; ActionPlan Cancel закомментирован. | W1 | [CLI][S0773]; [UI][S0771] |


<a id="mistral"></a>
### 12.10. Mistral — автоматизация


**71 регистраций.** CLI: `python-mistralclient 5.4.0`. Namespace: `openstack.workflow_engine.v2`.


| Команда | Возможность | Horizon | Пояснение / ограничение | Наш слой | Источники |
| --- | --- | --- | --- | --- | --- |
| `openstack action definition create` | Создание: определения Mistral actions | Есть | Основная операция/результат представлены; нужны сервис, права и допустимое состояние. | P1 | [CLI][S0774]; [UI][S0775] |
| `openstack action definition definition show` | Просмотр: текст определения action | Есть | Основная операция/результат представлены; нужны сервис, права и допустимое состояние. | P1 | [CLI][S0776]; [UI][S0775] |
| `openstack action definition delete` | Удаление: определения Mistral actions | Есть | Основная операция/результат представлены; нужны сервис, права и допустимое состояние. | P1 | [CLI][S0777]; [UI][S0775] |
| `openstack action definition list` | Список: определения Mistral actions | Есть | Основная операция/результат представлены; нужны сервис, права и допустимое состояние. | P1 | [CLI][S0778]; [UI][S0775] |
| `openstack action definition show` | Просмотр: определения Mistral actions | Есть | Основная операция/результат представлены; нужны сервис, права и допустимое состояние. | P1 | [CLI][S0779]; [UI][S0775] |
| `openstack action definition update` | Изменение: определения Mistral actions | Есть | Основная операция/результат представлены; нужны сервис, права и допустимое состояние. | P1 | [CLI][S0780]; [UI][S0775] |
| `openstack action execution delete` | Удаление: исполнение action | Есть | Основная операция/результат представлены; нужны сервис, права и допустимое состояние. | P1 | [CLI][S0781]; [UI][S0782] |
| `openstack action execution input show` | Просмотр: входные данные action | Есть | Основная операция/результат представлены; нужны сервис, права и допустимое состояние. | P1 | [CLI][S0783]; [UI][S0782] |
| `openstack action execution list` | Список: исполнение action | Есть | Основная операция/результат представлены; нужны сервис, права и допустимое состояние. | P1 | [CLI][S0784]; [UI][S0782] |
| `openstack action execution output show` | Просмотр: результат action | Есть | Основная операция/результат представлены; нужны сервис, права и допустимое состояние. | P1 | [CLI][S0785]; [UI][S0782] |
| `openstack action execution run` | Запуск: исполнение action | Частично | Run Action принимает JSON input; params ограничены Save result to DB. | P1 | [CLI][S0786]; [UI][S0782] |
| `openstack action execution show` | Просмотр: исполнение action | Есть | Основная операция/результат представлены; нужны сервис, права и допустимое состояние. | P1 | [CLI][S0787]; [UI][S0782] |
| `openstack action execution update` | Изменение: исполнение action | Частично | Update action state SUCCESS/ERROR и output; это отдельное действие, не повтор task. | P1 | [CLI][S0788]; [UI][S0782] |
| `openstack code source content show` | Просмотр: содержимое источника кода | Нет | Нет панели environments/event triggers/services/members/code sources/dynamic actions. | P1 | [CLI][S0789]; [UI][S0790] |
| `openstack code source create` | Создание: источник кода | Нет | Нет панели environments/event triggers/services/members/code sources/dynamic actions. | P1 | [CLI][S0791]; [UI][S0790] |
| `openstack code source delete` | Удаление: источник кода | Нет | Нет панели environments/event triggers/services/members/code sources/dynamic actions. | P1 | [CLI][S0792]; [UI][S0790] |
| `openstack code source list` | Список: источник кода | Нет | Нет панели environments/event triggers/services/members/code sources/dynamic actions. | P1 | [CLI][S0793]; [UI][S0790] |
| `openstack code source show` | Просмотр: источник кода | Нет | Нет панели environments/event triggers/services/members/code sources/dynamic actions. | P1 | [CLI][S0794]; [UI][S0790] |
| `openstack code source update` | Изменение: источник кода | Нет | Нет панели environments/event triggers/services/members/code sources/dynamic actions. | P1 | [CLI][S0795]; [UI][S0790] |
| `openstack cron trigger create` | Создание: периодический триггер | Есть | Основная операция/результат представлены; нужны сервис, права и допустимое состояние. | P1 | [CLI][S0796]; [UI][S0797] |
| `openstack cron trigger delete` | Удаление: периодический триггер | Есть | Основная операция/результат представлены; нужны сервис, права и допустимое состояние. | P1 | [CLI][S0798]; [UI][S0797] |
| `openstack cron trigger list` | Список: периодический триггер | Есть | Основная операция/результат представлены; нужны сервис, права и допустимое состояние. | P1 | [CLI][S0799]; [UI][S0797] |
| `openstack cron trigger show` | Просмотр: периодический триггер | Есть | Основная операция/результат представлены; нужны сервис, права и допустимое состояние. | P1 | [CLI][S0800]; [UI][S0797] |
| `openstack dynamic action create` | Создание: динамический action | Нет | Нет панели environments/event triggers/services/members/code sources/dynamic actions. | P1 | [CLI][S0801]; [UI][S0790] |
| `openstack dynamic action delete` | Удаление: динамический action | Нет | Нет панели environments/event triggers/services/members/code sources/dynamic actions. | P1 | [CLI][S0802]; [UI][S0790] |
| `openstack dynamic action list` | Список: динамический action | Нет | Нет панели environments/event triggers/services/members/code sources/dynamic actions. | P1 | [CLI][S0803]; [UI][S0790] |
| `openstack dynamic action show` | Просмотр: динамический action | Нет | Нет панели environments/event triggers/services/members/code sources/dynamic actions. | P1 | [CLI][S0804]; [UI][S0790] |
| `openstack dynamic action update` | Изменение: динамический action | Нет | Нет панели environments/event triggers/services/members/code sources/dynamic actions. | P1 | [CLI][S0805]; [UI][S0790] |
| `openstack event trigger create` | Создание: событийный триггер | Нет | Нет панели environments/event triggers/services/members/code sources/dynamic actions. | P1 | [CLI][S0806]; [UI][S0790] |
| `openstack event trigger delete` | Удаление: событийный триггер | Нет | Нет панели environments/event triggers/services/members/code sources/dynamic actions. | P1 | [CLI][S0807]; [UI][S0790] |
| `openstack event trigger list` | Список: событийный триггер | Нет | Нет панели environments/event triggers/services/members/code sources/dynamic actions. | P1 | [CLI][S0808]; [UI][S0790] |
| `openstack event trigger show` | Просмотр: событийный триггер | Нет | Нет панели environments/event triggers/services/members/code sources/dynamic actions. | P1 | [CLI][S0809]; [UI][S0790] |
| `openstack resource member create` | Создание: доступ участника к ресурсу Mistral | Нет | Нет панели environments/event triggers/services/members/code sources/dynamic actions. | P1 | [CLI][S0810]; [UI][S0790] |
| `openstack resource member delete` | Удаление: доступ участника к ресурсу Mistral | Нет | Нет панели environments/event triggers/services/members/code sources/dynamic actions. | P1 | [CLI][S0811]; [UI][S0790] |
| `openstack resource member list` | Список: доступ участника к ресурсу Mistral | Нет | Нет панели environments/event triggers/services/members/code sources/dynamic actions. | P1 | [CLI][S0812]; [UI][S0790] |
| `openstack resource member show` | Просмотр: доступ участника к ресурсу Mistral | Нет | Нет панели environments/event triggers/services/members/code sources/dynamic actions. | P1 | [CLI][S0813]; [UI][S0790] |
| `openstack resource member update` | Изменение: доступ участника к ресурсу Mistral | Нет | Нет панели environments/event triggers/services/members/code sources/dynamic actions. | P1 | [CLI][S0814]; [UI][S0790] |
| `openstack task execution list` | Список: исполнение task | Есть | Основная операция/результат представлены; нужны сервис, права и допустимое состояние. | P1 | [CLI][S0815]; [UI][S0816] |
| `openstack task execution published show` | Просмотр: опубликованные переменные task | Есть | Основная операция/результат представлены; нужны сервис, права и допустимое состояние. | P1 | [CLI][S0817]; [UI][S0816] |
| `openstack task execution rerun` | Повторный запуск: исполнение task | Нет | Соответствующее самостоятельное действие/представление отсутствует. | P1 | [CLI][S0818]; [UI][S0816] |
| `openstack task execution result show` | Просмотр: результат task | Есть | Основная операция/результат представлены; нужны сервис, права и допустимое состояние. | P1 | [CLI][S0819]; [UI][S0816] |
| `openstack task execution show` | Просмотр: исполнение task | Есть | Основная операция/результат представлены; нужны сервис, права и допустимое состояние. | P1 | [CLI][S0820]; [UI][S0816] |
| `openstack workbook create` | Создание: workbook Mistral | Есть | Основная операция/результат представлены; нужны сервис, права и допустимое состояние. | P1 | [CLI][S0821]; [UI][S0822] |
| `openstack workbook definition show` | Просмотр: текст workbook | Есть | Основная операция/результат представлены; нужны сервис, права и допустимое состояние. | P1 | [CLI][S0823]; [UI][S0822] |
| `openstack workbook delete` | Удаление: workbook Mistral | Есть | Основная операция/результат представлены; нужны сервис, права и допустимое состояние. | P1 | [CLI][S0824]; [UI][S0822] |
| `openstack workbook list` | Список: workbook Mistral | Есть | Основная операция/результат представлены; нужны сервис, права и допустимое состояние. | P1 | [CLI][S0825]; [UI][S0822] |
| `openstack workbook show` | Просмотр: workbook Mistral | Есть | Основная операция/результат представлены; нужны сервис, права и допустимое состояние. | P1 | [CLI][S0826]; [UI][S0822] |
| `openstack workbook update` | Изменение: workbook Mistral | Есть | Основная операция/результат представлены; нужны сервис, права и допустимое состояние. | P1 | [CLI][S0827]; [UI][S0822] |
| `openstack workbook validate` | Проверка: workbook Mistral | Частично | Серверная validation вызывается внутри формы загрузки определения; отдельного самостоятельного Validate действия нет. | P1 | [CLI][S0828]; [UI][S0829] |
| `openstack workflow create` | Создание: workflow Mistral | Есть | Основная операция/результат представлены; нужны сервис, права и допустимое состояние. | P1 | [CLI][S0830]; [UI][S0831] |
| `openstack workflow definition show` | Просмотр: текст workflow | Есть | Основная операция/результат представлены; нужны сервис, права и допустимое состояние. | P1 | [CLI][S0832]; [UI][S0831] |
| `openstack workflow delete` | Удаление: workflow Mistral | Есть | Основная операция/результат представлены; нужны сервис, права и допустимое состояние. | P1 | [CLI][S0833]; [UI][S0831] |
| `openstack workflow engine service list` | Список: сервисы Mistral | Нет | Нет панели environments/event triggers/services/members/code sources/dynamic actions. | P1 | [CLI][S0834]; [UI][S0790] |
| `openstack workflow env create` | Создание: сохранённое environment Mistral | Нет | Нет панели environments/event triggers/services/members/code sources/dynamic actions. | P1 | [CLI][S0835]; [UI][S0790] |
| `openstack workflow env delete` | Удаление: сохранённое environment Mistral | Нет | Нет панели environments/event triggers/services/members/code sources/dynamic actions. | P1 | [CLI][S0836]; [UI][S0790] |
| `openstack workflow env list` | Список: сохранённое environment Mistral | Нет | Нет панели environments/event triggers/services/members/code sources/dynamic actions. | P1 | [CLI][S0837]; [UI][S0790] |
| `openstack workflow env show` | Просмотр: сохранённое environment Mistral | Нет | Нет панели environments/event triggers/services/members/code sources/dynamic actions. | P1 | [CLI][S0838]; [UI][S0790] |
| `openstack workflow env update` | Изменение: сохранённое environment Mistral | Нет | Нет панели environments/event triggers/services/members/code sources/dynamic actions. | P1 | [CLI][S0839]; [UI][S0790] |
| `openstack workflow execution create` | Создание: исполнение workflow | Частично | Execute workflow передаёт строки/None; отсутствуют JSON workflow input/params, namespace и env. | P1 | [CLI][S0840]; [UI][S0841] |
| `openstack workflow execution delete` | Удаление: исполнение workflow | Есть | Основная операция/результат представлены; нужны сервис, права и допустимое состояние. | P1 | [CLI][S0842]; [UI][S0841] |
| `openstack workflow execution input show` | Просмотр: входные данные workflow | Есть | Основная операция/результат представлены; нужны сервис, права и допустимое состояние. | P1 | [CLI][S0843]; [UI][S0841] |
| `openstack workflow execution list` | Список: исполнение workflow | Есть | Основная операция/результат представлены; нужны сервис, права и допустимое состояние. | P1 | [CLI][S0844]; [UI][S0841] |
| `openstack workflow execution output show` | Просмотр: выходные данные workflow | Есть | Основная операция/результат представлены; нужны сервис, права и допустимое состояние. | P1 | [CLI][S0845]; [UI][S0841] |
| `openstack workflow execution published show` | Просмотр: опубликованные переменные workflow | Нет | Соответствующее самостоятельное действие/представление отсутствует. | P1 | [CLI][S0846]; [UI][S0841] |
| `openstack workflow execution report show` | Просмотр: отчёт исполнения workflow | Нет | Соответствующее самостоятельное действие/представление отсутствует. | P1 | [CLI][S0847]; [UI][S0841] |
| `openstack workflow execution show` | Просмотр: исполнение workflow | Есть | Основная операция/результат представлены; нужны сервис, права и допустимое состояние. | P1 | [CLI][S0848]; [UI][S0841] |
| `openstack workflow execution update` | Изменение: исполнение workflow | Частично | UI Pause/Resume/Description и Cancel->ERROR; env-update и произвольный допустимый state отсутствуют. | P1 | [CLI][S0849]; [UI][S0841] |
| `openstack workflow list` | Список: workflow Mistral | Есть | Основная операция/результат представлены; нужны сервис, права и допустимое состояние. | P1 | [CLI][S0850]; [UI][S0831] |
| `openstack workflow show` | Просмотр: workflow Mistral | Есть | Основная операция/результат представлены; нужны сервис, права и допустимое состояние. | P1 | [CLI][S0851]; [UI][S0831] |
| `openstack workflow update` | Изменение: workflow Mistral | Есть | Основная операция/результат представлены; нужны сервис, права и допустимое состояние. | P1 | [CLI][S0852]; [UI][S0831] |
| `openstack workflow validate` | Проверка: workflow Mistral | Частично | Серверная validation вызывается внутри формы загрузки определения; отдельного самостоятельного Validate действия нет. | P1 | [CLI][S0853]; [UI][S0854] |


<a id="heat"></a>
### 12.11. Heat — оркестрация


**49 регистраций.** CLI: `python-heatclient 4.1.0`. Namespace: `openstack.orchestration.v1`.


| Команда | Возможность | Horizon | Пояснение / ограничение | Наш слой | Источники |
| --- | --- | --- | --- | --- | --- |
| `openstack orchestration build info` | Просмотр: информация о сборке Heat | Нет | Нет специализированного UI действия/панели; общие шаблоны и API helper не заменяют эту функцию. | — | [CLI][S0855]; [UI][S0856] |
| `openstack orchestration resource type list` | Список: типы ресурсов Heat | Есть | Основная операция/результат представлены; нужны сервис, права и допустимое состояние. | — | [CLI][S0857]; [UI][S0858] |
| `openstack orchestration resource type show` | Просмотр: типы ресурсов Heat | Есть | Основная операция/результат представлены; нужны сервис, права и допустимое состояние. | — | [CLI][S0859]; [UI][S0858] |
| `openstack orchestration service list` | Список: сервисы Heat | Нет | Нет специализированного UI действия/панели; общие шаблоны и API helper не заменяют эту функцию. | — | [CLI][S0860]; [UI][S0856] |
| `openstack orchestration template function list` | Список: функции HOT | Есть | Основная операция/результат представлены; нужны сервис, права и допустимое состояние. | — | [CLI][S0861]; [UI][S0862] |
| `openstack orchestration template validate` | Проверка: шаблон Heat | Частично | Validation выполняется внутри Launch/Preview; не отдельный CLI-style validator всех режимов. | — | [CLI][S0863]; [UI][S0864] |
| `openstack orchestration template version list` | Список: версии HOT | Есть | Основная операция/результат представлены; нужны сервис, права и допустимое состояние. | — | [CLI][S0865]; [UI][S0862] |
| `openstack software config create` | Создание: конфигурация ПО | Нет | Нет специализированного UI действия/панели; общие шаблоны и API helper не заменяют эту функцию. | — | [CLI][S0866]; [UI][S0856] |
| `openstack software config delete` | Удаление: конфигурация ПО | Нет | Нет специализированного UI действия/панели; общие шаблоны и API helper не заменяют эту функцию. | — | [CLI][S0867]; [UI][S0856] |
| `openstack software config list` | Список: конфигурация ПО | Нет | Нет специализированного UI действия/панели; общие шаблоны и API helper не заменяют эту функцию. | — | [CLI][S0868]; [UI][S0856] |
| `openstack software config show` | Просмотр: конфигурация ПО | Нет | Нет специализированного UI действия/панели; общие шаблоны и API helper не заменяют эту функцию. | — | [CLI][S0869]; [UI][S0856] |
| `openstack software deployment create` | Создание: развёртывание ПО | Нет | Нет специализированного UI действия/панели; общие шаблоны и API helper не заменяют эту функцию. | — | [CLI][S0870]; [UI][S0856] |
| `openstack software deployment delete` | Удаление: развёртывание ПО | Нет | Нет специализированного UI действия/панели; общие шаблоны и API helper не заменяют эту функцию. | — | [CLI][S0871]; [UI][S0856] |
| `openstack software deployment list` | Список: развёртывание ПО | Нет | Нет специализированного UI действия/панели; общие шаблоны и API helper не заменяют эту функцию. | — | [CLI][S0872]; [UI][S0856] |
| `openstack software deployment metadata show` | Просмотр: metadata развёртывания ПО | Нет | Нет специализированного UI действия/панели; общие шаблоны и API helper не заменяют эту функцию. | — | [CLI][S0873]; [UI][S0856] |
| `openstack software deployment output show` | Просмотр: выходы развёртывания ПО | Нет | Нет специализированного UI действия/панели; общие шаблоны и API helper не заменяют эту функцию. | — | [CLI][S0874]; [UI][S0856] |
| `openstack software deployment show` | Просмотр: развёртывание ПО | Нет | Нет специализированного UI действия/панели; общие шаблоны и API helper не заменяют эту функцию. | — | [CLI][S0875]; [UI][S0856] |
| `openstack stack abandon` | Снятие с управления с выдачей описания: стек Heat | Нет | Нет специализированного UI действия/панели; общие шаблоны и API helper не заменяют эту функцию. | — | [CLI][S0876]; [UI][S0856] |
| `openstack stack adopt` | Принятие существующих ресурсов под управление: стек Heat | Нет | Нет специализированного UI действия/панели; общие шаблоны и API helper не заменяют эту функцию. | — | [CLI][S0877]; [UI][S0856] |
| `openstack stack cancel` | Отмена: стек Heat | Нет | Нет специализированного UI действия/панели; общие шаблоны и API helper не заменяют эту функцию. | — | [CLI][S0878]; [UI][S0856] |
| `openstack stack check` | Проверка состояния: стек Heat | Есть | Основная операция/результат представлены; нужны сервис, права и допустимое состояние. | — | [CLI][S0879]; [UI][S0856] |
| `openstack stack create` | Создание: стек Heat | Частично | Launch/Change Template есть; не представлены все CLI environment/parameter-file/tags/hooks/dry-run/nested preview режимы. | — | [CLI][S0880]; [UI][S0856] |
| `openstack stack delete` | Удаление: стек Heat | Есть | Основная операция/результат представлены; нужны сервис, права и допустимое состояние. | — | [CLI][S0881]; [UI][S0856] |
| `openstack stack environment show` | Просмотр: environment стека | Нет | Нет специализированного UI действия/панели; общие шаблоны и API helper не заменяют эту функцию. | — | [CLI][S0882]; [UI][S0856] |
| `openstack stack event list` | Список: события стека | Есть | Основная операция/результат представлены; нужны сервис, права и допустимое состояние. | — | [CLI][S0883]; [UI][S0856] |
| `openstack stack event show` | Просмотр: события стека | Частично | Events table содержит status/reason/ссылки, но нет отдельного полного event-detail action. | — | [CLI][S0884]; [UI][S0856] |
| `openstack stack export` | Экспорт: стек Heat | Нет | Нет специализированного UI действия/панели; общие шаблоны и API helper не заменяют эту функцию. | — | [CLI][S0885]; [UI][S0856] |
| `openstack stack failures list` | Список: ошибки стека | Нет | Нет специализированного UI действия/панели; общие шаблоны и API helper не заменяют эту функцию. | — | [CLI][S0886]; [UI][S0856] |
| `openstack stack file list` | Список: файлы стека | Нет | Нет специализированного UI действия/панели; общие шаблоны и API helper не заменяют эту функцию. | — | [CLI][S0887]; [UI][S0856] |
| `openstack stack hook clear` | Снятие hook: hook стека | Нет | Нет специализированного UI действия/панели; общие шаблоны и API helper не заменяют эту функцию. | — | [CLI][S0888]; [UI][S0856] |
| `openstack stack hook poll` | Ожидание hook: hook стека | Нет | Нет специализированного UI действия/панели; общие шаблоны и API helper не заменяют эту функцию. | — | [CLI][S0889]; [UI][S0856] |
| `openstack stack list` | Список: стек Heat | Есть | Основная операция/результат представлены; нужны сервис, права и допустимое состояние. | — | [CLI][S0890]; [UI][S0856] |
| `openstack stack output list` | Список: выходы стека | Есть | Основная операция/результат представлены; нужны сервис, права и допустимое состояние. | — | [CLI][S0891]; [UI][S0856] |
| `openstack stack output show` | Просмотр: выходы стека | Есть | Основная операция/результат представлены; нужны сервис, права и допустимое состояние. | — | [CLI][S0892]; [UI][S0856] |
| `openstack stack resource list` | Список: ресурсы стека | Есть | Основная операция/результат представлены; нужны сервис, права и допустимое состояние. | — | [CLI][S0893]; [UI][S0856] |
| `openstack stack resource mark unhealthy` | Пометка ресурса нездоровым | Нет | Нет специализированного UI действия/панели; общие шаблоны и API helper не заменяют эту функцию. | — | [CLI][S0894]; [UI][S0856] |
| `openstack stack resource metadata` | Чтение metadata: ресурсы стека | Есть | Основная операция/результат представлены; нужны сервис, права и допустимое состояние. | — | [CLI][S0895]; [UI][S0856] |
| `openstack stack resource show` | Просмотр: ресурсы стека | Есть | Основная операция/результат представлены; нужны сервис, права и допустимое состояние. | — | [CLI][S0896]; [UI][S0856] |
| `openstack stack resource signal` | Отправка сигнала ресурсу: ресурсы стека | Нет | Нет специализированного UI действия/панели; общие шаблоны и API helper не заменяют эту функцию. | — | [CLI][S0897]; [UI][S0856] |
| `openstack stack resume` | Возобновление: стек Heat | Есть | Основная операция/результат представлены; нужны сервис, права и допустимое состояние. | — | [CLI][S0898]; [UI][S0856] |
| `openstack stack show` | Просмотр: стек Heat | Есть | Основная операция/результат представлены; нужны сервис, права и допустимое состояние. | — | [CLI][S0899]; [UI][S0856] |
| `openstack stack snapshot create` | Создание: снимки стека | Нет | Нет специализированного UI действия/панели; общие шаблоны и API helper не заменяют эту функцию. | — | [CLI][S0900]; [UI][S0856] |
| `openstack stack snapshot delete` | Удаление: снимки стека | Нет | Нет специализированного UI действия/панели; общие шаблоны и API helper не заменяют эту функцию. | — | [CLI][S0901]; [UI][S0856] |
| `openstack stack snapshot list` | Список: снимки стека | Нет | Нет специализированного UI действия/панели; общие шаблоны и API helper не заменяют эту функцию. | — | [CLI][S0902]; [UI][S0856] |
| `openstack stack snapshot restore` | Восстановление снимка: снимки стека | Нет | Нет специализированного UI действия/панели; общие шаблоны и API helper не заменяют эту функцию. | — | [CLI][S0903]; [UI][S0856] |
| `openstack stack snapshot show` | Просмотр: снимки стека | Нет | Нет специализированного UI действия/панели; общие шаблоны и API helper не заменяют эту функцию. | — | [CLI][S0904]; [UI][S0856] |
| `openstack stack suspend` | Приостановка: стек Heat | Есть | Основная операция/результат представлены; нужны сервис, права и допустимое состояние. | — | [CLI][S0905]; [UI][S0856] |
| `openstack stack template show` | Просмотр: шаблон стека | Есть | Основная операция/результат представлены; нужны сервис, права и допустимое состояние. | — | [CLI][S0906]; [UI][S0856] |
| `openstack stack update` | Изменение: стек Heat | Частично | Launch/Change Template есть; не представлены все CLI environment/parameter-file/tags/hooks/dry-run/nested preview режимы. | — | [CLI][S0907]; [UI][S0856] |


<a id="ironic"></a>
### 12.12. Ironic — bare metal


**107 регистраций.** CLI: `python-ironicclient 5.10.0`. Namespace: `openstack.baremetal.v1`.


| Команда | Возможность | Horizon | Пояснение / ограничение | Наш слой | Источники |
| --- | --- | --- | --- | --- | --- |
| `openstack baremetal allocation create` | Создание: заявки на выделение bare metal | Нет | Нет соответствующей панели/REST adapter: allocations/chassis/conductors/deploy templates/runbooks/shards/storage attachments. | I1 | [CLI][S0908]; [UI][S0909] |
| `openstack baremetal allocation delete` | Удаление: заявки на выделение bare metal | Нет | Нет соответствующей панели/REST adapter: allocations/chassis/conductors/deploy templates/runbooks/shards/storage attachments. | I1 | [CLI][S0908]; [UI][S0909] |
| `openstack baremetal allocation list` | Список: заявки на выделение bare metal | Нет | Нет соответствующей панели/REST adapter: allocations/chassis/conductors/deploy templates/runbooks/shards/storage attachments. | I1 | [CLI][S0908]; [UI][S0909] |
| `openstack baremetal allocation set` | Установка параметров: заявки на выделение bare metal | Нет | Нет соответствующей панели/REST adapter: allocations/chassis/conductors/deploy templates/runbooks/shards/storage attachments. | I1 | [CLI][S0908]; [UI][S0909] |
| `openstack baremetal allocation show` | Просмотр: заявки на выделение bare metal | Нет | Нет соответствующей панели/REST adapter: allocations/chassis/conductors/deploy templates/runbooks/shards/storage attachments. | I1 | [CLI][S0908]; [UI][S0909] |
| `openstack baremetal allocation unset` | Снятие параметров: заявки на выделение bare metal | Нет | Нет соответствующей панели/REST adapter: allocations/chassis/conductors/deploy templates/runbooks/shards/storage attachments. | I1 | [CLI][S0908]; [UI][S0909] |
| `openstack baremetal chassis create` | Создание: шасси | Нет | Нет соответствующей панели/REST adapter: allocations/chassis/conductors/deploy templates/runbooks/shards/storage attachments. | I1 | [CLI][S0908]; [UI][S0909] |
| `openstack baremetal chassis delete` | Удаление: шасси | Нет | Нет соответствующей панели/REST adapter: allocations/chassis/conductors/deploy templates/runbooks/shards/storage attachments. | I1 | [CLI][S0908]; [UI][S0909] |
| `openstack baremetal chassis list` | Список: шасси | Нет | Нет соответствующей панели/REST adapter: allocations/chassis/conductors/deploy templates/runbooks/shards/storage attachments. | I1 | [CLI][S0908]; [UI][S0909] |
| `openstack baremetal chassis set` | Установка параметров: шасси | Нет | Нет соответствующей панели/REST adapter: allocations/chassis/conductors/deploy templates/runbooks/shards/storage attachments. | I1 | [CLI][S0908]; [UI][S0909] |
| `openstack baremetal chassis show` | Просмотр: шасси | Нет | Нет соответствующей панели/REST adapter: allocations/chassis/conductors/deploy templates/runbooks/shards/storage attachments. | I1 | [CLI][S0908]; [UI][S0909] |
| `openstack baremetal chassis unset` | Снятие параметров: шасси | Нет | Нет соответствующей панели/REST adapter: allocations/chassis/conductors/deploy templates/runbooks/shards/storage attachments. | I1 | [CLI][S0908]; [UI][S0909] |
| `openstack baremetal conductor list` | Список: службы conductor | Нет | Нет соответствующей панели/REST adapter: allocations/chassis/conductors/deploy templates/runbooks/shards/storage attachments. | I1 | [CLI][S0908]; [UI][S0909] |
| `openstack baremetal conductor show` | Просмотр: службы conductor | Нет | Нет соответствующей панели/REST adapter: allocations/chassis/conductors/deploy templates/runbooks/shards/storage attachments. | I1 | [CLI][S0908]; [UI][S0909] |
| `openstack baremetal create` | Создание: bare metal ресурсы из файла | Частично | Enroll Node создаёт узел; нет bulk YAML/JSON create всего набора nodes/ports/portgroups. | I1 | [CLI][S0908]; [UI][S0909] |
| `openstack baremetal deploy template create` | Создание: шаблоны развёртывания | Нет | Нет соответствующей панели/REST adapter: allocations/chassis/conductors/deploy templates/runbooks/shards/storage attachments. | I1 | [CLI][S0908]; [UI][S0909] |
| `openstack baremetal deploy template delete` | Удаление: шаблоны развёртывания | Нет | Нет соответствующей панели/REST adapter: allocations/chassis/conductors/deploy templates/runbooks/shards/storage attachments. | I1 | [CLI][S0908]; [UI][S0909] |
| `openstack baremetal deploy template list` | Список: шаблоны развёртывания | Нет | Нет соответствующей панели/REST adapter: allocations/chassis/conductors/deploy templates/runbooks/shards/storage attachments. | I1 | [CLI][S0908]; [UI][S0909] |
| `openstack baremetal deploy template set` | Установка параметров: шаблоны развёртывания | Нет | Нет соответствующей панели/REST adapter: allocations/chassis/conductors/deploy templates/runbooks/shards/storage attachments. | I1 | [CLI][S0908]; [UI][S0909] |
| `openstack baremetal deploy template show` | Просмотр: шаблоны развёртывания | Нет | Нет соответствующей панели/REST adapter: allocations/chassis/conductors/deploy templates/runbooks/shards/storage attachments. | I1 | [CLI][S0908]; [UI][S0909] |
| `openstack baremetal deploy template unset` | Снятие параметров: шаблоны развёртывания | Нет | Нет соответствующей панели/REST adapter: allocations/chassis/conductors/deploy templates/runbooks/shards/storage attachments. | I1 | [CLI][S0908]; [UI][S0909] |
| `openstack baremetal driver list` | Список: драйверы оборудования | Частично | Driver list/properties/details используются формами; самостоятельного полного driver-management экрана нет. | I1 | [CLI][S0908]; [UI][S0909] |
| `openstack baremetal driver passthru call` | Вызов: vendor passthru драйвера | Нет | Vendor passthru action отсутствует. | I1 | [CLI][S0908]; [UI][S0909] |
| `openstack baremetal driver passthru list` | Список: vendor passthru драйвера | Нет | Vendor passthru action отсутствует. | I1 | [CLI][S0908]; [UI][S0909] |
| `openstack baremetal driver property list` | Список: свойства драйвера | Частично | Driver list/properties/details используются формами; самостоятельного полного driver-management экрана нет. | I1 | [CLI][S0908]; [UI][S0909] |
| `openstack baremetal driver raid property list` | Список: свойства RAID драйвера | Нет | Нет чтения RAID logical disk properties драйвера. Форма RAID имеет собственные поля; обычный DriverProperties не заменяет RAID properties API. | I1 | [CLI][S0908]; [UI][S0909] |
| `openstack baremetal driver show` | Просмотр: драйверы оборудования | Частично | Driver list/properties/details используются формами; самостоятельного полного driver-management экрана нет. | I1 | [CLI][S0908]; [UI][S0909] |
| `openstack baremetal node abort` | Прерывание текущей операции: bare metal узел | Частично | Операция есть только в предусмотренных UI state transitions; config-drive/deploy-steps/runbook/disable-ramdisk не представлены. | I1 | [CLI][S0908]; [UI][S0910] |
| `openstack baremetal node add trait` | Добавление trait узлу | Нет | Нет специализированного UI действия/adapter; generic properties/cleaning не равны отдельной функции. | I1 | [CLI][S0908]; [UI][S0909] |
| `openstack baremetal node adopt` | Принятие существующих ресурсов под управление: bare metal узел | Частично | Операция есть только в предусмотренных UI state transitions; config-drive/deploy-steps/runbook/disable-ramdisk не представлены. | I1 | [CLI][S0908]; [UI][S0910] |
| `openstack baremetal node bios setting list` | Список: настройки BIOS узла | Нет | Нет специализированного UI действия/adapter; generic properties/cleaning не равны отдельной функции. | I1 | [CLI][S0908]; [UI][S0909] |
| `openstack baremetal node bios setting show` | Просмотр: настройки BIOS узла | Нет | Нет специализированного UI действия/adapter; generic properties/cleaning не равны отдельной функции. | I1 | [CLI][S0908]; [UI][S0909] |
| `openstack baremetal node boot device set` | Установка параметров: загрузочное устройство | Есть | Основная операция/результат представлены; нужны сервис, права и допустимое состояние. | I1 | [CLI][S0908]; [UI][S0909] |
| `openstack baremetal node boot device show` | Просмотр: загрузочное устройство | Есть | Основная операция/результат представлены; нужны сервис, права и допустимое состояние. | I1 | [CLI][S0908]; [UI][S0909] |
| `openstack baremetal node boot mode set` | Установка параметров: режим загрузки | Нет | Нет специализированного UI действия/adapter; generic properties/cleaning не равны отдельной функции. | I1 | [CLI][S0908]; [UI][S0909] |
| `openstack baremetal node children list` | Список: дочерние узлы | Нет | Нет специализированного UI действия/adapter; generic properties/cleaning не равны отдельной функции. | I1 | [CLI][S0908]; [UI][S0909] |
| `openstack baremetal node clean` | Запуск cleaning: bare metal узел | Частично | Операция есть только в предусмотренных UI state transitions; config-drive/deploy-steps/runbook/disable-ramdisk не представлены. | I1 | [CLI][S0908]; [UI][S0910] |
| `openstack baremetal node console disable` | Отключение: консоль узла | Есть | Основная операция/результат представлены; нужны сервис, права и допустимое состояние. | I1 | [CLI][S0908]; [UI][S0909] |
| `openstack baremetal node console enable` | Включение: консоль узла | Есть | Основная операция/результат представлены; нужны сервис, права и допустимое состояние. | I1 | [CLI][S0908]; [UI][S0909] |
| `openstack baremetal node console show` | Просмотр: консоль узла | Есть | Основная операция/результат представлены; нужны сервис, права и допустимое состояние. | I1 | [CLI][S0908]; [UI][S0909] |
| `openstack baremetal node create` | Создание: bare metal узел | Частично | Enroll/Edit и RAID Configuration; ограничены поля, интерфейсы и microversion1.34. | I1 | [CLI][S0908]; [UI][S0909] |
| `openstack baremetal node delete` | Удаление: bare metal узел | Есть | Основная операция/результат представлены; нужны сервис, права и допустимое состояние. | I1 | [CLI][S0908]; [UI][S0909] |
| `openstack baremetal node deploy` | Развёртывание: bare metal узел | Частично | Операция есть только в предусмотренных UI state transitions; config-drive/deploy-steps/runbook/disable-ramdisk не представлены. | I1 | [CLI][S0908]; [UI][S0910] |
| `openstack baremetal node firmware list` | Список: прошивки узла | Нет | Нет специализированного UI действия/adapter; generic properties/cleaning не равны отдельной функции. | I1 | [CLI][S0908]; [UI][S0909] |
| `openstack baremetal node history get` | Получение записи: история событий узла | Нет | Нет специализированного UI действия/adapter; generic properties/cleaning не равны отдельной функции. | I1 | [CLI][S0908]; [UI][S0909] |
| `openstack baremetal node history list` | Список: история событий узла | Нет | Нет специализированного UI действия/adapter; generic properties/cleaning не равны отдельной функции. | I1 | [CLI][S0908]; [UI][S0909] |
| `openstack baremetal node inject nmi` | Отправка немаскируемого прерывания NMI | Есть | Основная операция/результат представлены; нужны сервис, права и допустимое состояние. | I1 | [CLI][S0908]; [UI][S0909] |
| `openstack baremetal node inspect` | Инспекция оборудования: bare metal узел | Частично | Операция есть только в предусмотренных UI state transitions; config-drive/deploy-steps/runbook/disable-ramdisk не представлены. | I1 | [CLI][S0908]; [UI][S0910] |
| `openstack baremetal node inventory save` | Сохранение в файл: инвентаризация узла | Нет | Нет специализированного UI действия/adapter; generic properties/cleaning не равны отдельной функции. | I1 | [CLI][S0908]; [UI][S0909] |
| `openstack baremetal node list` | Список: bare metal узел | Есть | Основная операция/результат представлены; нужны сервис, права и допустимое состояние. | I1 | [CLI][S0908]; [UI][S0909] |
| `openstack baremetal node maintenance set` | Установка параметров: режим обслуживания узла | Есть | Основная операция/результат представлены; нужны сервис, права и допустимое состояние. | I1 | [CLI][S0908]; [UI][S0909] |
| `openstack baremetal node maintenance unset` | Снятие параметров: режим обслуживания узла | Есть | Основная операция/результат представлены; нужны сервис, права и допустимое состояние. | I1 | [CLI][S0908]; [UI][S0909] |
| `openstack baremetal node manage` | Переход в manageable: bare metal узел | Частично | Операция есть только в предусмотренных UI state transitions; config-drive/deploy-steps/runbook/disable-ramdisk не представлены. | I1 | [CLI][S0908]; [UI][S0910] |
| `openstack baremetal node passthru call` | Вызов: vendor passthru узла | Нет | Нет специализированного UI действия/adapter; generic properties/cleaning не равны отдельной функции. | I1 | [CLI][S0908]; [UI][S0909] |
| `openstack baremetal node passthru list` | Список: vendor passthru узла | Нет | Нет специализированного UI действия/adapter; generic properties/cleaning не равны отдельной функции. | I1 | [CLI][S0908]; [UI][S0909] |
| `openstack baremetal node power off` | Выключение: питание узла | Частично | Power/soft power/reboot UI есть; не все timeout и CLI варианты представлены. | I1 | [CLI][S0908]; [UI][S0909] |
| `openstack baremetal node power on` | Включение: питание узла | Частично | Power/soft power/reboot UI есть; не все timeout и CLI варианты представлены. | I1 | [CLI][S0908]; [UI][S0909] |
| `openstack baremetal node provide` | Переход в available: bare metal узел | Частично | Операция есть только в предусмотренных UI state transitions; config-drive/deploy-steps/runbook/disable-ramdisk не представлены. | I1 | [CLI][S0908]; [UI][S0910] |
| `openstack baremetal node reboot` | Перезагрузка: bare metal узел | Частично | Power/soft power/reboot UI есть; не все timeout и CLI варианты представлены. | I1 | [CLI][S0908]; [UI][S0909] |
| `openstack baremetal node rebuild` | Повторное развёртывание: bare metal узел | Частично | Операция есть только в предусмотренных UI state transitions; config-drive/deploy-steps/runbook/disable-ramdisk не представлены. | I1 | [CLI][S0908]; [UI][S0910] |
| `openstack baremetal node remove trait` | Удаление trait узла | Нет | Нет специализированного UI действия/adapter; generic properties/cleaning не равны отдельной функции. | I1 | [CLI][S0908]; [UI][S0909] |
| `openstack baremetal node rescue` | Переход в rescue: bare metal узел | Нет | Нет специализированного UI действия/adapter; generic properties/cleaning не равны отдельной функции. | I1 | [CLI][S0908]; [UI][S0909] |
| `openstack baremetal node secure boot off` | Выключение: Secure Boot узла | Нет | Нет специализированного UI действия/adapter; generic properties/cleaning не равны отдельной функции. | I1 | [CLI][S0908]; [UI][S0909] |
| `openstack baremetal node secure boot on` | Включение: Secure Boot узла | Нет | Нет специализированного UI действия/adapter; generic properties/cleaning не равны отдельной функции. | I1 | [CLI][S0908]; [UI][S0909] |
| `openstack baremetal node service` | Запуск servicing: bare metal узел | Нет | Нет специализированного UI действия/adapter; generic properties/cleaning не равны отдельной функции. | I1 | [CLI][S0908]; [UI][S0909] |
| `openstack baremetal node set` | Установка параметров: bare metal узел | Частично | Enroll/Edit и RAID Configuration; ограничены поля, интерфейсы и microversion1.34. | I1 | [CLI][S0908]; [UI][S0909] |
| `openstack baremetal node show` | Просмотр: bare metal узел | Частично | Details и validate есть; новые API поля ограничены жёсткой microversion1.34. | I1 | [CLI][S0908]; [UI][S0909] |
| `openstack baremetal node trait list` | Список: traits узла | Нет | Нет специализированного UI действия/adapter; generic properties/cleaning не равны отдельной функции. | I1 | [CLI][S0908]; [UI][S0909] |
| `openstack baremetal node undeploy` | Снятие развёртывания: bare metal узел | Частично | Операция есть только в предусмотренных UI state transitions; config-drive/deploy-steps/runbook/disable-ramdisk не представлены. | I1 | [CLI][S0908]; [UI][S0910] |
| `openstack baremetal node unhold` | Снятие hold: bare metal узел | Нет | Нет специализированного UI действия/adapter; generic properties/cleaning не равны отдельной функции. | I1 | [CLI][S0908]; [UI][S0909] |
| `openstack baremetal node unrescue` | Выход из rescue: bare metal узел | Нет | Нет специализированного UI действия/adapter; generic properties/cleaning не равны отдельной функции. | I1 | [CLI][S0908]; [UI][S0909] |
| `openstack baremetal node unset` | Снятие параметров: bare metal узел | Частично | Enroll/Edit и RAID Configuration; ограничены поля, интерфейсы и microversion1.34. | I1 | [CLI][S0908]; [UI][S0909] |
| `openstack baremetal node validate` | Проверка: bare metal узел | Есть | Основная операция/результат представлены; нужны сервис, права и допустимое состояние. | I1 | [CLI][S0908]; [UI][S0909] |
| `openstack baremetal node vif attach` | Подключение: VIF узла | Нет | Нет специализированного UI действия/adapter; generic properties/cleaning не равны отдельной функции. | I1 | [CLI][S0908]; [UI][S0909] |
| `openstack baremetal node vif detach` | Отключение: VIF узла | Нет | Нет специализированного UI действия/adapter; generic properties/cleaning не равны отдельной функции. | I1 | [CLI][S0908]; [UI][S0909] |
| `openstack baremetal node vif list` | Список: VIF узла | Нет | Нет специализированного UI действия/adapter; generic properties/cleaning не равны отдельной функции. | I1 | [CLI][S0908]; [UI][S0909] |
| `openstack baremetal port create` | Создание: физические порты | Частично | Основной CRUD внутри деталей node есть; scope/поля ограничены интерфейсом и microversion1.34. | I1 | [CLI][S0908]; [UI][S0909] |
| `openstack baremetal port delete` | Удаление: физические порты | Частично | Основной CRUD внутри деталей node есть; scope/поля ограничены интерфейсом и microversion1.34. | I1 | [CLI][S0908]; [UI][S0909] |
| `openstack baremetal port group create` | Создание: группы физических портов | Частично | Основной CRUD внутри деталей node есть; scope/поля ограничены интерфейсом и microversion1.34. | I1 | [CLI][S0908]; [UI][S0909] |
| `openstack baremetal port group delete` | Удаление: группы физических портов | Частично | Основной CRUD внутри деталей node есть; scope/поля ограничены интерфейсом и microversion1.34. | I1 | [CLI][S0908]; [UI][S0909] |
| `openstack baremetal port group list` | Список: группы физических портов | Частично | Основной CRUD внутри деталей node есть; scope/поля ограничены интерфейсом и microversion1.34. | I1 | [CLI][S0908]; [UI][S0909] |
| `openstack baremetal port group set` | Установка параметров: группы физических портов | Частично | Основной CRUD внутри деталей node есть; scope/поля ограничены интерфейсом и microversion1.34. | I1 | [CLI][S0908]; [UI][S0909] |
| `openstack baremetal port group show` | Просмотр: группы физических портов | Частично | Основной CRUD внутри деталей node есть; scope/поля ограничены интерфейсом и microversion1.34. | I1 | [CLI][S0908]; [UI][S0909] |
| `openstack baremetal port group unset` | Снятие параметров: группы физических портов | Частично | Основной CRUD внутри деталей node есть; scope/поля ограничены интерфейсом и microversion1.34. | I1 | [CLI][S0908]; [UI][S0909] |
| `openstack baremetal port list` | Список: физические порты | Частично | Основной CRUD внутри деталей node есть; scope/поля ограничены интерфейсом и microversion1.34. | I1 | [CLI][S0908]; [UI][S0909] |
| `openstack baremetal port set` | Установка параметров: физические порты | Частично | Основной CRUD внутри деталей node есть; scope/поля ограничены интерфейсом и microversion1.34. | I1 | [CLI][S0908]; [UI][S0909] |
| `openstack baremetal port show` | Просмотр: физические порты | Частично | Основной CRUD внутри деталей node есть; scope/поля ограничены интерфейсом и microversion1.34. | I1 | [CLI][S0908]; [UI][S0909] |
| `openstack baremetal port unset` | Снятие параметров: физические порты | Частично | Основной CRUD внутри деталей node есть; scope/поля ограничены интерфейсом и microversion1.34. | I1 | [CLI][S0908]; [UI][S0909] |
| `openstack baremetal runbook create` | Создание: runbooks Ironic | Нет | Нет соответствующей панели/REST adapter: allocations/chassis/conductors/deploy templates/runbooks/shards/storage attachments. | I1 | [CLI][S0908]; [UI][S0909] |
| `openstack baremetal runbook delete` | Удаление: runbooks Ironic | Нет | Нет соответствующей панели/REST adapter: allocations/chassis/conductors/deploy templates/runbooks/shards/storage attachments. | I1 | [CLI][S0908]; [UI][S0909] |
| `openstack baremetal runbook list` | Список: runbooks Ironic | Нет | Нет соответствующей панели/REST adapter: allocations/chassis/conductors/deploy templates/runbooks/shards/storage attachments. | I1 | [CLI][S0908]; [UI][S0909] |
| `openstack baremetal runbook set` | Установка параметров: runbooks Ironic | Нет | Нет соответствующей панели/REST adapter: allocations/chassis/conductors/deploy templates/runbooks/shards/storage attachments. | I1 | [CLI][S0908]; [UI][S0909] |
| `openstack baremetal runbook show` | Просмотр: runbooks Ironic | Нет | Нет соответствующей панели/REST adapter: allocations/chassis/conductors/deploy templates/runbooks/shards/storage attachments. | I1 | [CLI][S0908]; [UI][S0909] |
| `openstack baremetal runbook unset` | Снятие параметров: runbooks Ironic | Нет | Нет соответствующей панели/REST adapter: allocations/chassis/conductors/deploy templates/runbooks/shards/storage attachments. | I1 | [CLI][S0908]; [UI][S0909] |
| `openstack baremetal shard list` | Список: shards Ironic | Нет | Нет соответствующей панели/REST adapter: allocations/chassis/conductors/deploy templates/runbooks/shards/storage attachments. | I1 | [CLI][S0908]; [UI][S0909] |
| `openstack baremetal volume connector create` | Создание: коннекторы внешнего хранилища | Нет | Нет соответствующей панели/REST adapter: allocations/chassis/conductors/deploy templates/runbooks/shards/storage attachments. | I1 | [CLI][S0908]; [UI][S0909] |
| `openstack baremetal volume connector delete` | Удаление: коннекторы внешнего хранилища | Нет | Нет соответствующей панели/REST adapter: allocations/chassis/conductors/deploy templates/runbooks/shards/storage attachments. | I1 | [CLI][S0908]; [UI][S0909] |
| `openstack baremetal volume connector list` | Список: коннекторы внешнего хранилища | Нет | Нет соответствующей панели/REST adapter: allocations/chassis/conductors/deploy templates/runbooks/shards/storage attachments. | I1 | [CLI][S0908]; [UI][S0909] |
| `openstack baremetal volume connector set` | Установка параметров: коннекторы внешнего хранилища | Нет | Нет соответствующей панели/REST adapter: allocations/chassis/conductors/deploy templates/runbooks/shards/storage attachments. | I1 | [CLI][S0908]; [UI][S0909] |
| `openstack baremetal volume connector show` | Просмотр: коннекторы внешнего хранилища | Нет | Нет соответствующей панели/REST adapter: allocations/chassis/conductors/deploy templates/runbooks/shards/storage attachments. | I1 | [CLI][S0908]; [UI][S0909] |
| `openstack baremetal volume connector unset` | Снятие параметров: коннекторы внешнего хранилища | Нет | Нет соответствующей панели/REST adapter: allocations/chassis/conductors/deploy templates/runbooks/shards/storage attachments. | I1 | [CLI][S0908]; [UI][S0909] |
| `openstack baremetal volume target create` | Создание: цели внешнего хранилища | Нет | Нет соответствующей панели/REST adapter: allocations/chassis/conductors/deploy templates/runbooks/shards/storage attachments. | I1 | [CLI][S0908]; [UI][S0909] |
| `openstack baremetal volume target delete` | Удаление: цели внешнего хранилища | Нет | Нет соответствующей панели/REST adapter: allocations/chassis/conductors/deploy templates/runbooks/shards/storage attachments. | I1 | [CLI][S0908]; [UI][S0909] |
| `openstack baremetal volume target list` | Список: цели внешнего хранилища | Нет | Нет соответствующей панели/REST adapter: allocations/chassis/conductors/deploy templates/runbooks/shards/storage attachments. | I1 | [CLI][S0908]; [UI][S0909] |
| `openstack baremetal volume target set` | Установка параметров: цели внешнего хранилища | Нет | Нет соответствующей панели/REST adapter: allocations/chassis/conductors/deploy templates/runbooks/shards/storage attachments. | I1 | [CLI][S0908]; [UI][S0909] |
| `openstack baremetal volume target show` | Просмотр: цели внешнего хранилища | Нет | Нет соответствующей панели/REST adapter: allocations/chassis/conductors/deploy templates/runbooks/shards/storage attachments. | I1 | [CLI][S0908]; [UI][S0909] |
| `openstack baremetal volume target unset` | Снятие параметров: цели внешнего хранилища | Нет | Нет соответствующей панели/REST adapter: allocations/chassis/conductors/deploy templates/runbooks/shards/storage attachments. | I1 | [CLI][S0908]; [UI][S0909] |


<a id="custom"></a>
## 13. Полные контракты наших доработок


### 13.1. Какие источники считаются доработками

Основная база — три архива `0809`, перечисленные в [baselines/0809.json](https://github.com/lebtmalorny-rgb/mimaric/blob/3b665acfae723c33bd01bc7ef22181cfe707bbc1/baselines/0809.json). Их SHA256 повторно вычислены и совпали с manifest. Mistral PowerOps исследован непосредственно в архиве, его значимые исходники сохранены в [local-sources/mistral-0809](https://github.com/lebtmalorny-rgb/mimaric/tree/89be5492cba1a1c44d187a7f1df4a4b2243e1ab1/docs/openstack-cli-horizon-2025.1/evidence/mistral-0809). Masakari и Kolla исследованы также в актуальных компонентных деревьях с последующими патчами.

| Слой | Проверенный локальный источник | Статус включения в анализ |
|---|---|---|
| База PowerOps | Mistral, Masakari, Kolla-Ansible `0809` | Основная реализация |
| Post-fence Nova down | `powerops-patches/hotfixes/masakari-post-fence-nova-down` | Дополнение базы Masakari |
| Watcher automation hold | `feature/watcher-automation-hold-2025.1`, `c866d56fbf382afa4612c07039c34fbb5032aef5` | Отдельная поставка; код подтверждён, включение на стенде не проверено |
| Per-target evacuation | `feature/masakari-per-target-evacuation`, `71b0123f390bfeaab4dc4ca2dffaa6fab32a6cdf` | Последующее дополнение с зависимостью от Watcher kit; включение не проверено |
| Старый интеграционный backend | Патчи Mistral/Mistral-lib/Masakari в `powerops-patches/horizon/patches` | Отдельная ранняя база, не объединяется с `0809` в одну реализацию |
| Собственный Horizon PowerOps | `powerops-dashboard` | Исключён по условию задачи |
| `planned-return-v2`, planned-return kit, disk-monitor ADR | Выведенные из актуального набора или проектные материалы | Не считаются действующими возможностями |

Точные HEAD, состояние рабочих деревьев, SHA256 и комментарии архивов сохранены в [local-source-manifest.json](https://github.com/lebtmalorny-rgb/mimaric/blob/89be5492cba1a1c44d187a7f1df4a4b2243e1ab1/docs/openstack-cli-horizon-2025.1/data/local-source-manifest.json). Наличие файлов в рабочем каталоге и история публикации не доказывают их установку в облаке. Текущий `main` имеет пользовательские изменения; они не редактировались.

### 13.2. Матрица операторских возможностей

Здесь «CLI» разделён на штатный `openstack` и отдельные утилиты. Действие, выполняемое автоматически внутри сервера, не считается новой CLI-командой.

| Возможность | Через штатный OpenStack CLI | Через штатный Horizon с upstream-плагинами | Фактическая граница |
|---|---|---|---|
| Состояние одного PowerOps host | `openstack workflow execution create power_ops.host_power_status` с JSON `host`, `segment_uuid`; затем execution/task/action output | Workflow можно запустить и посмотреть output в Mistral dashboard | Результат содержит Ironic power/target/error, Nova enabled/state, Masakari maintenance; это наблюдение нескольких API, не атомарный снимок и не отдельная страница хоста |
| Выключение пустого хоста | `power_ops.planned_power_off`, `instance_policy=require_empty`, boolean `allow_hard_off` | Workflow виден, но типизированный boolean штатная форма не передаёт корректно | Права, общая блокировка source, maintenance и Nova disable проверяются сервером |
| Выключение с остановкой ВМ | Тот же workflow, `instance_policy=stop` | Та же проблема типов | Сохраняется `stopped_instance_ids`; уже выключенные ВМ не входят в список остановленных операцией |
| Выключение после live migration | Тот же workflow, `instance_policy=live_migrate` | Та же проблема типов; отдельной формы с выбором политики и проверками PowerOps нет | Последовательная миграция ACTIVE ВМ с ожиданием её завершения; это плановая миграция, не Masakari evacuation |
| Плановая перезагрузка | `power_ops.planned_reboot` с теми же policy/boolean | Та же проблема типов | Серверная операция PowerOps; обычный Ironic reboot не реализует её контракт |
| Включение и возврат | `power_ops.power_on_and_return`, JSON-массив `stopped_instance_ids` | Строковое поле не передаёт массив; Resume не передаёт `env` | После включения хост остаётся Nova disabled и Masakari maintenance, workflow делает PAUSED перед возвратом |
| Подтверждение ручной проверки при возврате | `openstack workflow execution update … --state RUNNING --env …`, где `stale_domains_checked` — boolean true | Кнопка Resume меняет state, но не задаёт env | При отсутствии настоящего boolean true серверный gate отвергает возврат. Текст `"true"` не подходит |
| Запуск отдельного PowerOps action | `openstack action execution run powerops.…` с JSON | Mistral Run Action поддерживает JSON | Это отдельное выполнение action: оно не воспроизводит автоматически граф workflow и паузу оператора |
| Общая блокировка source Mistral/Masakari | Действует при вызове существующих операций | Действует и при вызове через dashboard | Внутренняя серверная координация etcd/tooz; штатного списка блокировок в OSC/UI нет |
| Ironic fencing перед evacuation | Через стандартный Masakari notification запускается серверный recovery | Видны обычные notification/host состояния | Новые TaskFlow проверки и fencing не представлены отдельной кнопкой или командой OSC |
| Ожидание Nova disabled/down после power off | Автоматический этап patched Masakari | Косвенное наблюдение по notification и сервисам | Только подтверждённое отключение Ironic плюс свежий Nova disabled/down разрешают дальнейшее восстановление |
| Глобальная последовательная эвакуация в PowerOps `0809` | Внутренний lock и интервал в Masakari | Настройка через UI отсутствует | При включённом новом evacuation guard используется его отдельный путь, а не сложение двух лимитеров |
| Остановка новых периодических действий Watcher при аварии | Автоматически в Watcher/Masakari; чтение отдельной утилитой | Обычные audit/action-plan состояния; причины и состояние guard отдельной панелью не представлены | Штатные `optimize` команды не содержат управления этим общим guard |
| Просмотр/снятие Watcher hold | Отдельная `powerops-watcher-guard status/initialize/resume` | Нет | Утилита обращается к общему etcd по сервисной конфигурации; это не Keystone REST API и не OSC plugin |
| Ограничение эвакуации на принимающий compute | Автоматически в patched Nova + Masakari | Нет отдельной очереди/claims в dashboard | По умолчанию 3 одновременно занятых глобальных слота, 1 операция на target, cooldown 5 секунд; значения конфигурируемы |
| Разбор UNKNOWN, intent и operation эвакуации | Отдельная `powerops-evacuation-guard` | Нет | Штатные Nova/Masakari status полезны, но не заменяют долговечное состояние guard |
| Массовая регистрация Ironic BMC-only | Отдельная `kolla-ansible enroll-ironic` | Generic Enroll Node не воспроизводит Ansible-процедуру | Создание/обновление BMC metadata, профиль и переход до manageable; это команда Kolla-Ansible |
| Настройки guards, задержек, источников метрик, backend/RBAC | Конфигурация сервисов и Kolla-Ansible | Штатных форм нет | Не управляются произвольными командами OSC; наличие API объекта не делает весь конфиг сервиса доступным через API |

### 13.3. Точные контракты PowerOps

В [power_ops.yaml](https://github.com/lebtmalorny-rgb/mimaric/blob/89be5492cba1a1c44d187a7f1df4a4b2243e1ab1/docs/openstack-cli-horizon-2025.1/evidence/mistral-0809/etc/mistral/power_ops.yaml) определены четыре workflow: `host_power_status` (строка 6), `planned_power_off` (21), `planned_reboot` (41), `power_on_and_return` (60). В [setup.cfg](https://github.com/lebtmalorny-rgb/mimaric/blob/89be5492cba1a1c44d187a7f1df4a4b2243e1ab1/docs/openstack-cli-horizon-2025.1/evidence/mistral-0809/setup.cfg), строки 60–65, зарегистрированы пять серверных actions:

```text
powerops.host_power_status
powerops.planned_power_off
powerops.planned_reboot
powerops.power_on_for_inspection
powerops.return_to_service
```

Это entry points группы `mistral.actions`, а не `openstack.cli.extension`. Поэтому эти доработки доступны существующими командами `workflow execution …` и `action execution …`; отдельная команда `openstack powerops …` в исследованном комплекте отсутствует.

Для штатной формы Mistral dashboard критичны три проверки в сервере:

1. [planned.py](https://github.com/lebtmalorny-rgb/mimaric/blob/89be5492cba1a1c44d187a7f1df4a4b2243e1ab1/docs/openstack-cli-horizon-2025.1/evidence/mistral-0809/mistral/actions/powerops/planned.py), строка 38: `type(self.allow_hard_off) is not bool` отвергает строку `"false"`/`"true"`.
2. [clients.py](https://github.com/lebtmalorny-rgb/mimaric/blob/89be5492cba1a1c44d187a7f1df4a4b2243e1ab1/docs/openstack-cli-horizon-2025.1/evidence/mistral-0809/mistral/actions/powerops/clients.py), строка 815: manifest остановленных ВМ должен быть списком, со строковыми идентификаторами и без повторов.
3. [return_host.py](https://github.com/lebtmalorny-rgb/mimaric/blob/89be5492cba1a1c44d187a7f1df4a4b2243e1ab1/docs/openstack-cli-horizon-2025.1/evidence/mistral-0809/mistral/actions/powerops/return_host.py), строка 122: `stale_domains_checked is not True` блокирует возврат. Workbook берёт это значение из `env()`, строка 84.

Следовательно, совпадение названия workflow в списке Horizon с доступной CLI-операцией не означает равенства пользовательского сценария. Подробная проверка Execute/Resume/Run Action приведена в [mistral-heat.md](#mistral).

Возврат не выполняет автоматическую проверку stale domains по SSH. `stale_domains_checked=true` — подтверждение оператора после проверки, а не вычисленный сервером факт. После аварийной эвакуации нет автоматического power-on или обратного размещения эвакуированных ВМ. Это следует из текущего [описания PowerOps](https://github.com/lebtmalorny-rgb/mimaric/blob/3b665acfae723c33bd01bc7ef22181cfe707bbc1/docs/POWEROPS-OVERVIEW.md) и кода возврата.

### 13.4. Watcher hold: чего именно нет в OSC/Horizon

Пакет [powerops-watcher-guard](https://github.com/lebtmalorny-rgb/mimaric/blob/c866d56fbf382afa4612c07039c34fbb5032aef5/packages/powerops-watcher-guard/pyproject.toml), строки 14–15, регистрирует самостоятельный console script. В [cli.py](https://github.com/lebtmalorny-rgb/mimaric/blob/c866d56fbf382afa4612c07039c34fbb5032aef5/packages/powerops-watcher-guard/powerops_watcher_guard/cli.py), строки 18–29, доступны только:

```text
status
initialize --actor … --reason …
resume --expected-revision … --actor … --reason … --acknowledge-recovery
```

`initialize` создаёт исходное BLOCKED. `resume` требует актуальную revision и явное подтверждение восстановления; старые планы с прежним epoch не становятся допустимыми. Сброс по таймауту или после SUCCESS notification не выполняется. Внутреннее `automation_epoch` не является доступным для редактирования REST-полем ActionPlan.

По коду [automation_guard.py](https://github.com/lebtmalorny-rgb/mimaric/blob/89be5492cba1a1c44d187a7f1df4a4b2243e1ab1/docs/openstack-cli-horizon-2025.1/evidence/watcher/watcher/common/automation_guard.py), строки 46–62, новые `ONESHOT`/`EVENT` планы обходят этот запрет; защищён автоматический путь `CONTINUOUS`. Уже допущенное действие может обратиться к Nova после hold. Это не drain, не отмена миграций и не общая блокировка всех ручных Mistral/Nova операций. Полная граница — [WATCHER-AUTOMATION-HOLD.md](../WATCHER-AUTOMATION-HOLD.md).

Серверный guard действует независимо от того, был ли автоматический audit создан из CLI или Horizon. Но оба штатных клиента не показывают revision/epoch и не выполняют предусмотренное операторское разрешение.

### 13.5. Per-target evacuation: новая служебная CLI

[pyproject.toml](https://github.com/lebtmalorny-rgb/mimaric/blob/71b0123f390bfeaab4dc4ca2dffaa6fab32a6cdf/packages/powerops-evacuation-guard/pyproject.toml), строки 14–15, и [cli.py](https://github.com/lebtmalorny-rgb/mimaric/blob/71b0123f390bfeaab4dc4ca2dffaa6fab32a6cdf/packages/powerops-evacuation-guard/powerops_evacuation_guard/cli.py), строки 18–42, дают восемь подкоманд:

```text
initialize
configure
status
inspect-operation MIGRATION_UUID
inspect-intent ATTEMPT_UUID
recover-cooldown MIGRATION_UUID
resolve-operation MIGRATION_UUID
resolve-intent ATTEMPT_UUID
```

У модифицирующих операторских команд есть actor/reason, у соответствующих операций — expected revision. Разрешение неопределённых исходов требует `--nova-terminal` и `--executors-quiesced`. Это подтверждения оператора, а не самостоятельная проверка Nova утилитой.

Патч добавляет долговечные admission/claims и наблюдение завершения Nova; cooldown удерживает и target, и глобальный слот. UNKNOWN/ошибка/падение процесса не освобождают их автоматически. Штатные `server migration …` и `notification …` не умеют разрешать эти записи. Ограничитель по умолчанию выключен, `powerops_evacuation_guard_enabled: "no"`; установка кода не равна его включению.

Источники: [MASAKARI-PER-TARGET-EVACUATION.md](../MASAKARI-PER-TARGET-EVACUATION.md), [manifest](https://github.com/lebtmalorny-rgb/mimaric/blob/71b0123f390bfeaab4dc4ca2dffaa6fab32a6cdf/hotfixes/masakari-per-target-evacuation/manifest.json), [интеграция Masakari](https://github.com/lebtmalorny-rgb/mimaric/blob/89be5492cba1a1c44d187a7f1df4a4b2243e1ab1/docs/openstack-cli-horizon-2025.1/evidence/masakari/masakari/engine/drivers/taskflow/host_failure.py), строки 486–507.

### 13.6. Ironic, Heat и интеграция Kolla

В исследованной поставке не найден самостоятельный компонентный patch Ironic API/conductor или Heat, добавляющий новую CLI/API-функцию. Для Ironic обнаружены доработки Kolla enrollment и использование стандартного Ironic API из PowerOps. Это вывод о проверенном локальном комплекте, а не об отсутствии любых иных корпоративных веток.

`kolla-ansible enroll-ironic` зарегистрирован в [setup.cfg](https://github.com/lebtmalorny-rgb/mimaric/blob/89be5492cba1a1c44d187a7f1df4a4b2243e1ab1/docs/openstack-cli-horizon-2025.1/evidence/kolla/setup.cfg), строка 65. В [enroll.yml](https://github.com/lebtmalorny-rgb/mimaric/blob/89be5492cba1a1c44d187a7f1df4a4b2243e1ab1/docs/openstack-cli-horizon-2025.1/evidence/kolla/ansible/roles/ironic_enroll/tasks/enroll.yml), строки 161–176, заданы enroll, `network_interface=noop`, `storage_interface=noop`, `inspect_interface=no-inspect`, `bios_interface=no-bios`, `raid_interface=no-raid`. Завершающая цель — manageable.

Поэтому наличие в upstream Ironic CLI/UI кнопок deploy, clean, inspect, provide, RAID или BIOS не означает их применимость к вашим существующим compute в профиле BMC-only. Штатный Power On/Off в Ironic также не выполняет PowerOps maintenance, drain ВМ и проверки Nova. Подробности профиля — [POWEROPS-IRONIC-ENROLLMENT.md](https://github.com/lebtmalorny-rgb/mimaric/blob/3b665acfae723c33bd01bc7ef22181cfe707bbc1/docs/POWEROPS-IRONIC-ENROLLMENT.md).

Роль Horizon в Kolla передаёт пять отдельных флагов `ENABLE_HEAT`, `ENABLE_IRONIC`, `ENABLE_MASAKARI`, `ENABLE_MISTRAL`, `ENABLE_WATCHER` в [defaults/main.yml](https://github.com/lebtmalorny-rgb/mimaric/blob/89be5492cba1a1c44d187a7f1df4a4b2243e1ab1/docs/openstack-cli-horizon-2025.1/evidence/kolla/ansible/roles/horizon/defaults/main.yml), строки 13–24. Это wiring установки/включения штатных плагинов; оно не доказывает фактическую доступность панели для пользователя. Нужны пакет в образе, enabled-файлы, endpoint, policy и соответствующие роли.

Отдельная ветка host-firewall содержит команду `kolla-ansible host-firewall`; это управление инфраструктурой Kolla, не функция OpenStackClient и не Horizon. Аналогично конфигурация Consul/FRR/NTP и диагностические Ansible playbook не расширяют автоматически `openstack`. Их подробная функциональная инвентаризация выходит за перечень сервисных клиентов в этой задаче.

### 13.7. Серверные патчи раннего комплекта с Horizon

Условие «кроме Horizon» исключает собственную UI-реализацию, но не скрывает серверный код, лежащий в одноимённом каталоге. Поэтому его отличия фиксируются отдельно:

| Серверная доработка | Канал использования | Статус относительно базы `0809` |
|---|---|---|
| `powerops.host_inventory` и workflow инвентаризации | Generic Mistral action/workflow CLI после установки соответствующего backend | Отдельный patch `0016`; в пяти actions базы `0809` отсутствует |
| Типизированный доверенный контекст вызова в mistral-lib | Внутренний транспорт идентичности/полномочий для actions | Входит в ранний согласованный комплект |
| Проверка прав на старт и повторная авторизация resume | Серверные Mistral API/RBAC проверки | Проверять exact backend; не приписывать автоматически `0809` |
| Allowlist/roles/hard-off policy и inventory с all-project данными | Серверные ограничения и read-only aggregation | Не являются новой группой OSC-команд |

Источники: [README сохранённого комплекта](https://github.com/lebtmalorny-rgb/mimaric/blob/3b665acfae723c33bd01bc7ef22181cfe707bbc1/horizon/README.md), [DELIVERY](https://github.com/lebtmalorny-rgb/mimaric/blob/3b665acfae723c33bd01bc7ef22181cfe707bbc1/horizon/DELIVERY.md), [патч inventory](https://github.com/lebtmalorny-rgb/mimaric/blob/3b665acfae723c33bd01bc7ef22181cfe707bbc1/horizon/patches/mistral/0016-feat-expose-read-only-PowerOps-host-inventory.patch), [baseline manifest](https://github.com/lebtmalorny-rgb/mimaric/blob/3b665acfae723c33bd01bc7ef22181cfe707bbc1/horizon/docs/evidence/horizon-powerops-baselines.json). Совместимость этого набора с `0809` помечена `not_verified`; сама папка не означает установленную возможность.

### 13.8. Практический вывод

Для вашей реализации `openstack` покрывает стандартные сервисные объекты и служит подходящим типизированным входом в Mistral PowerOps. Для полного операторского контура дополнительно требуются две поставляемые guard-утилиты и Kolla-Ansible для конфигурации/enrollment. Штатный Horizon обеспечивает часть операций и наблюдение стандартных объектов, но не полное управление PowerOps, типизированным возвратом, Watcher hold и очередью эвакуации.


### 13.9. Команды собственных операторских утилит

Эти 11 подкоманд не входят в 953 регистрации `openstack`. Их источник — собственные `console_scripts` и argparse CLI из проверенных Watcher/evacuation kits. У штатного Horizon соответствующих действий нет.


| Команда | Назначение | Тип |
| --- | --- | --- |
| `powerops-watcher-guard status` | Чтение состояния hold, revision/epoch | Чтение |
| `powerops-watcher-guard initialize` | Создание исходного BLOCKED; actor/reason | Изменение |
| `powerops-watcher-guard resume` | Ручное разрешение с expected revision и подтверждением восстановления | Изменение |
| `powerops-evacuation-guard initialize` | Инициализация состояния ограничителя | Изменение |
| `powerops-evacuation-guard configure` | Настройка лимитов guard | Изменение |
| `powerops-evacuation-guard status` | Чтение сводного состояния | Чтение |
| `powerops-evacuation-guard inspect-operation` | Чтение операции по migration UUID | Чтение |
| `powerops-evacuation-guard inspect-intent` | Чтение intent по attempt UUID | Чтение |
| `powerops-evacuation-guard recover-cooldown` | Операторское восстановление cooldown | Изменение |
| `powerops-evacuation-guard resolve-operation` | Разрешение состояния операции с установленными подтверждениями | Изменение |
| `powerops-evacuation-guard resolve-intent` | Разрешение состояния intent с установленными подтверждениями | Изменение |



<a id="legacy"></a>
## 14. Полный остаток базового клиента: старые API

В `python-openstackclient 7.4.0` сохранено 136 регистраций для Identity v2, Image v1 и Volume v1/v2. Они приведены для полноты **пакета клиента**. Это не ещё 136 одновременно доступных функций Epoxy: поддержка устаревшего API требует соответствующего endpoint и выбора версии, а основной анализ использует Identity v3, Image v2 и Volume v3. Совпадающие имена разных namespace намеренно не удалены.

Отдельный статус Horizon для этих регистраций не назначается: современный UI выполняет операции через свой API adapter, а не через legacy-команду. Для совпадающих функций сравнение находится в таблице основной версии API. API/аргументный контракт legacy может отличаться.


### `openstack.identity.v2` — 34 регистраций


| Команда | Обработчик в python-openstackclient 7.4.0 | Источник |
| --- | --- | --- |
| `openstack catalog list` | `openstackclient.identity.v2_0.catalog:ListCatalog` | [CLI][S0001] |
| `openstack catalog show` | `openstackclient.identity.v2_0.catalog:ShowCatalog` | [CLI][S0001] |
| `openstack ec2 credentials create` | `openstackclient.identity.v2_0.ec2creds:CreateEC2Creds` | [CLI][S0001] |
| `openstack ec2 credentials delete` | `openstackclient.identity.v2_0.ec2creds:DeleteEC2Creds` | [CLI][S0001] |
| `openstack ec2 credentials list` | `openstackclient.identity.v2_0.ec2creds:ListEC2Creds` | [CLI][S0001] |
| `openstack ec2 credentials show` | `openstackclient.identity.v2_0.ec2creds:ShowEC2Creds` | [CLI][S0001] |
| `openstack endpoint create` | `openstackclient.identity.v2_0.endpoint:CreateEndpoint` | [CLI][S0001] |
| `openstack endpoint delete` | `openstackclient.identity.v2_0.endpoint:DeleteEndpoint` | [CLI][S0001] |
| `openstack endpoint list` | `openstackclient.identity.v2_0.endpoint:ListEndpoint` | [CLI][S0001] |
| `openstack endpoint show` | `openstackclient.identity.v2_0.endpoint:ShowEndpoint` | [CLI][S0001] |
| `openstack project create` | `openstackclient.identity.v2_0.project:CreateProject` | [CLI][S0001] |
| `openstack project delete` | `openstackclient.identity.v2_0.project:DeleteProject` | [CLI][S0001] |
| `openstack project list` | `openstackclient.identity.v2_0.project:ListProject` | [CLI][S0001] |
| `openstack project set` | `openstackclient.identity.v2_0.project:SetProject` | [CLI][S0001] |
| `openstack project show` | `openstackclient.identity.v2_0.project:ShowProject` | [CLI][S0001] |
| `openstack project unset` | `openstackclient.identity.v2_0.project:UnsetProject` | [CLI][S0001] |
| `openstack role add` | `openstackclient.identity.v2_0.role:AddRole` | [CLI][S0001] |
| `openstack role assignment list` | `openstackclient.identity.v2_0.role_assignment:ListRoleAssignment` | [CLI][S0001] |
| `openstack role create` | `openstackclient.identity.v2_0.role:CreateRole` | [CLI][S0001] |
| `openstack role delete` | `openstackclient.identity.v2_0.role:DeleteRole` | [CLI][S0001] |
| `openstack role list` | `openstackclient.identity.v2_0.role:ListRole` | [CLI][S0001] |
| `openstack role remove` | `openstackclient.identity.v2_0.role:RemoveRole` | [CLI][S0001] |
| `openstack role show` | `openstackclient.identity.v2_0.role:ShowRole` | [CLI][S0001] |
| `openstack service create` | `openstackclient.identity.v2_0.service:CreateService` | [CLI][S0001] |
| `openstack service delete` | `openstackclient.identity.v2_0.service:DeleteService` | [CLI][S0001] |
| `openstack service list` | `openstackclient.identity.v2_0.service:ListService` | [CLI][S0001] |
| `openstack service show` | `openstackclient.identity.v2_0.service:ShowService` | [CLI][S0001] |
| `openstack token issue` | `openstackclient.identity.v2_0.token:IssueToken` | [CLI][S0001] |
| `openstack token revoke` | `openstackclient.identity.v2_0.token:RevokeToken` | [CLI][S0001] |
| `openstack user create` | `openstackclient.identity.v2_0.user:CreateUser` | [CLI][S0001] |
| `openstack user delete` | `openstackclient.identity.v2_0.user:DeleteUser` | [CLI][S0001] |
| `openstack user list` | `openstackclient.identity.v2_0.user:ListUser` | [CLI][S0001] |
| `openstack user set` | `openstackclient.identity.v2_0.user:SetUser` | [CLI][S0001] |
| `openstack user show` | `openstackclient.identity.v2_0.user:ShowUser` | [CLI][S0001] |


### `openstack.image.v1` — 6 регистраций


| Команда | Обработчик в python-openstackclient 7.4.0 | Источник |
| --- | --- | --- |
| `openstack image create` | `openstackclient.image.v1.image:CreateImage` | [CLI][S0001] |
| `openstack image delete` | `openstackclient.image.v1.image:DeleteImage` | [CLI][S0001] |
| `openstack image list` | `openstackclient.image.v1.image:ListImage` | [CLI][S0001] |
| `openstack image save` | `openstackclient.image.v1.image:SaveImage` | [CLI][S0001] |
| `openstack image set` | `openstackclient.image.v1.image:SetImage` | [CLI][S0001] |
| `openstack image show` | `openstackclient.image.v1.image:ShowImage` | [CLI][S0001] |


### `openstack.volume.v1` — 39 регистраций


| Команда | Обработчик в python-openstackclient 7.4.0 | Источник |
| --- | --- | --- |
| `openstack volume backup create` | `openstackclient.volume.v1.volume_backup:CreateVolumeBackup` | [CLI][S0001] |
| `openstack volume backup delete` | `openstackclient.volume.v1.volume_backup:DeleteVolumeBackup` | [CLI][S0001] |
| `openstack volume backup list` | `openstackclient.volume.v1.volume_backup:ListVolumeBackup` | [CLI][S0001] |
| `openstack volume backup restore` | `openstackclient.volume.v1.volume_backup:RestoreVolumeBackup` | [CLI][S0001] |
| `openstack volume backup show` | `openstackclient.volume.v1.volume_backup:ShowVolumeBackup` | [CLI][S0001] |
| `openstack volume create` | `openstackclient.volume.v1.volume:CreateVolume` | [CLI][S0001] |
| `openstack volume delete` | `openstackclient.volume.v1.volume:DeleteVolume` | [CLI][S0001] |
| `openstack volume list` | `openstackclient.volume.v1.volume:ListVolume` | [CLI][S0001] |
| `openstack volume migrate` | `openstackclient.volume.v1.volume:MigrateVolume` | [CLI][S0001] |
| `openstack volume qos associate` | `openstackclient.volume.v1.qos_specs:AssociateQos` | [CLI][S0001] |
| `openstack volume qos create` | `openstackclient.volume.v1.qos_specs:CreateQos` | [CLI][S0001] |
| `openstack volume qos delete` | `openstackclient.volume.v1.qos_specs:DeleteQos` | [CLI][S0001] |
| `openstack volume qos disassociate` | `openstackclient.volume.v1.qos_specs:DisassociateQos` | [CLI][S0001] |
| `openstack volume qos list` | `openstackclient.volume.v1.qos_specs:ListQos` | [CLI][S0001] |
| `openstack volume qos set` | `openstackclient.volume.v1.qos_specs:SetQos` | [CLI][S0001] |
| `openstack volume qos show` | `openstackclient.volume.v1.qos_specs:ShowQos` | [CLI][S0001] |
| `openstack volume qos unset` | `openstackclient.volume.v1.qos_specs:UnsetQos` | [CLI][S0001] |
| `openstack volume service list` | `openstackclient.volume.v1.service:ListService` | [CLI][S0001] |
| `openstack volume service set` | `openstackclient.volume.v1.service:SetService` | [CLI][S0001] |
| `openstack volume set` | `openstackclient.volume.v1.volume:SetVolume` | [CLI][S0001] |
| `openstack volume show` | `openstackclient.volume.v1.volume:ShowVolume` | [CLI][S0001] |
| `openstack volume snapshot create` | `openstackclient.volume.v1.volume_snapshot:CreateVolumeSnapshot` | [CLI][S0001] |
| `openstack volume snapshot delete` | `openstackclient.volume.v1.volume_snapshot:DeleteVolumeSnapshot` | [CLI][S0001] |
| `openstack volume snapshot list` | `openstackclient.volume.v1.volume_snapshot:ListVolumeSnapshot` | [CLI][S0001] |
| `openstack volume snapshot set` | `openstackclient.volume.v1.volume_snapshot:SetVolumeSnapshot` | [CLI][S0001] |
| `openstack volume snapshot show` | `openstackclient.volume.v1.volume_snapshot:ShowVolumeSnapshot` | [CLI][S0001] |
| `openstack volume snapshot unset` | `openstackclient.volume.v1.volume_snapshot:UnsetVolumeSnapshot` | [CLI][S0001] |
| `openstack volume transfer request accept` | `openstackclient.volume.v1.volume_transfer_request:AcceptTransferRequest` | [CLI][S0001] |
| `openstack volume transfer request create` | `openstackclient.volume.v1.volume_transfer_request:CreateTransferRequest` | [CLI][S0001] |
| `openstack volume transfer request delete` | `openstackclient.volume.v1.volume_transfer_request:DeleteTransferRequest` | [CLI][S0001] |
| `openstack volume transfer request list` | `openstackclient.volume.v1.volume_transfer_request:ListTransferRequest` | [CLI][S0001] |
| `openstack volume transfer request show` | `openstackclient.volume.v1.volume_transfer_request:ShowTransferRequest` | [CLI][S0001] |
| `openstack volume type create` | `openstackclient.volume.v1.volume_type:CreateVolumeType` | [CLI][S0001] |
| `openstack volume type delete` | `openstackclient.volume.v1.volume_type:DeleteVolumeType` | [CLI][S0001] |
| `openstack volume type list` | `openstackclient.volume.v1.volume_type:ListVolumeType` | [CLI][S0001] |
| `openstack volume type set` | `openstackclient.volume.v1.volume_type:SetVolumeType` | [CLI][S0001] |
| `openstack volume type show` | `openstackclient.volume.v1.volume_type:ShowVolumeType` | [CLI][S0001] |
| `openstack volume type unset` | `openstackclient.volume.v1.volume_type:UnsetVolumeType` | [CLI][S0001] |
| `openstack volume unset` | `openstackclient.volume.v1.volume:UnsetVolume` | [CLI][S0001] |


### `openstack.volume.v2` — 57 регистраций


| Команда | Обработчик в python-openstackclient 7.4.0 | Источник |
| --- | --- | --- |
| `openstack consistency group add volume` | `openstackclient.volume.v2.consistency_group:AddVolumeToConsistencyGroup` | [CLI][S0001] |
| `openstack consistency group create` | `openstackclient.volume.v2.consistency_group:CreateConsistencyGroup` | [CLI][S0001] |
| `openstack consistency group delete` | `openstackclient.volume.v2.consistency_group:DeleteConsistencyGroup` | [CLI][S0001] |
| `openstack consistency group list` | `openstackclient.volume.v2.consistency_group:ListConsistencyGroup` | [CLI][S0001] |
| `openstack consistency group remove volume` | `openstackclient.volume.v2.consistency_group:RemoveVolumeFromConsistencyGroup` | [CLI][S0001] |
| `openstack consistency group set` | `openstackclient.volume.v2.consistency_group:SetConsistencyGroup` | [CLI][S0001] |
| `openstack consistency group show` | `openstackclient.volume.v2.consistency_group:ShowConsistencyGroup` | [CLI][S0001] |
| `openstack consistency group snapshot create` | `openstackclient.volume.v2.consistency_group_snapshot:CreateConsistencyGroupSnapshot` | [CLI][S0001] |
| `openstack consistency group snapshot delete` | `openstackclient.volume.v2.consistency_group_snapshot:DeleteConsistencyGroupSnapshot` | [CLI][S0001] |
| `openstack consistency group snapshot list` | `openstackclient.volume.v2.consistency_group_snapshot:ListConsistencyGroupSnapshot` | [CLI][S0001] |
| `openstack consistency group snapshot show` | `openstackclient.volume.v2.consistency_group_snapshot:ShowConsistencyGroupSnapshot` | [CLI][S0001] |
| `openstack volume backend capability show` | `openstackclient.volume.v2.volume_backend:ShowCapability` | [CLI][S0001] |
| `openstack volume backend pool list` | `openstackclient.volume.v2.volume_backend:ListPool` | [CLI][S0001] |
| `openstack volume backup create` | `openstackclient.volume.v2.volume_backup:CreateVolumeBackup` | [CLI][S0001] |
| `openstack volume backup delete` | `openstackclient.volume.v2.volume_backup:DeleteVolumeBackup` | [CLI][S0001] |
| `openstack volume backup list` | `openstackclient.volume.v2.volume_backup:ListVolumeBackup` | [CLI][S0001] |
| `openstack volume backup record export` | `openstackclient.volume.v2.backup_record:ExportBackupRecord` | [CLI][S0001] |
| `openstack volume backup record import` | `openstackclient.volume.v2.backup_record:ImportBackupRecord` | [CLI][S0001] |
| `openstack volume backup restore` | `openstackclient.volume.v2.volume_backup:RestoreVolumeBackup` | [CLI][S0001] |
| `openstack volume backup set` | `openstackclient.volume.v2.volume_backup:SetVolumeBackup` | [CLI][S0001] |
| `openstack volume backup show` | `openstackclient.volume.v2.volume_backup:ShowVolumeBackup` | [CLI][S0001] |
| `openstack volume create` | `openstackclient.volume.v2.volume:CreateVolume` | [CLI][S0001] |
| `openstack volume delete` | `openstackclient.volume.v2.volume:DeleteVolume` | [CLI][S0001] |
| `openstack volume host failover` | `openstackclient.volume.v2.volume_host:FailoverVolumeHost` | [CLI][S0001] |
| `openstack volume host set` | `openstackclient.volume.v2.volume_host:SetVolumeHost` | [CLI][S0001] |
| `openstack volume list` | `openstackclient.volume.v2.volume:ListVolume` | [CLI][S0001] |
| `openstack volume migrate` | `openstackclient.volume.v2.volume:MigrateVolume` | [CLI][S0001] |
| `openstack volume qos associate` | `openstackclient.volume.v2.qos_specs:AssociateQos` | [CLI][S0001] |
| `openstack volume qos create` | `openstackclient.volume.v2.qos_specs:CreateQos` | [CLI][S0001] |
| `openstack volume qos delete` | `openstackclient.volume.v2.qos_specs:DeleteQos` | [CLI][S0001] |
| `openstack volume qos disassociate` | `openstackclient.volume.v2.qos_specs:DisassociateQos` | [CLI][S0001] |
| `openstack volume qos list` | `openstackclient.volume.v2.qos_specs:ListQos` | [CLI][S0001] |
| `openstack volume qos set` | `openstackclient.volume.v2.qos_specs:SetQos` | [CLI][S0001] |
| `openstack volume qos show` | `openstackclient.volume.v2.qos_specs:ShowQos` | [CLI][S0001] |
| `openstack volume qos unset` | `openstackclient.volume.v2.qos_specs:UnsetQos` | [CLI][S0001] |
| `openstack volume service list` | `openstackclient.volume.v2.service:ListService` | [CLI][S0001] |
| `openstack volume service set` | `openstackclient.volume.v2.service:SetService` | [CLI][S0001] |
| `openstack volume set` | `openstackclient.volume.v2.volume:SetVolume` | [CLI][S0001] |
| `openstack volume show` | `openstackclient.volume.v2.volume:ShowVolume` | [CLI][S0001] |
| `openstack volume snapshot create` | `openstackclient.volume.v2.volume_snapshot:CreateVolumeSnapshot` | [CLI][S0001] |
| `openstack volume snapshot delete` | `openstackclient.volume.v2.volume_snapshot:DeleteVolumeSnapshot` | [CLI][S0001] |
| `openstack volume snapshot list` | `openstackclient.volume.v2.volume_snapshot:ListVolumeSnapshot` | [CLI][S0001] |
| `openstack volume snapshot set` | `openstackclient.volume.v2.volume_snapshot:SetVolumeSnapshot` | [CLI][S0001] |
| `openstack volume snapshot show` | `openstackclient.volume.v2.volume_snapshot:ShowVolumeSnapshot` | [CLI][S0001] |
| `openstack volume snapshot unset` | `openstackclient.volume.v2.volume_snapshot:UnsetVolumeSnapshot` | [CLI][S0001] |
| `openstack volume transfer request accept` | `openstackclient.volume.v2.volume_transfer_request:AcceptTransferRequest` | [CLI][S0001] |
| `openstack volume transfer request create` | `openstackclient.volume.v2.volume_transfer_request:CreateTransferRequest` | [CLI][S0001] |
| `openstack volume transfer request delete` | `openstackclient.volume.v2.volume_transfer_request:DeleteTransferRequest` | [CLI][S0001] |
| `openstack volume transfer request list` | `openstackclient.volume.v2.volume_transfer_request:ListTransferRequest` | [CLI][S0001] |
| `openstack volume transfer request show` | `openstackclient.volume.v2.volume_transfer_request:ShowTransferRequest` | [CLI][S0001] |
| `openstack volume type create` | `openstackclient.volume.v2.volume_type:CreateVolumeType` | [CLI][S0001] |
| `openstack volume type delete` | `openstackclient.volume.v2.volume_type:DeleteVolumeType` | [CLI][S0001] |
| `openstack volume type list` | `openstackclient.volume.v2.volume_type:ListVolumeType` | [CLI][S0001] |
| `openstack volume type set` | `openstackclient.volume.v2.volume_type:SetVolumeType` | [CLI][S0001] |
| `openstack volume type show` | `openstackclient.volume.v2.volume_type:ShowVolumeType` | [CLI][S0001] |
| `openstack volume type unset` | `openstackclient.volume.v2.volume_type:UnsetVolumeType` | [CLI][S0001] |
| `openstack volume unset` | `openstackclient.volume.v2.volume:UnsetVolume` | [CLI][S0001] |



<a id="completeness"></a>
## 15. Отдельные сервисные клиенты и проверка полноты

Граница основного реестра — `openstack` плюс пять согласованных OSC-плагинов. Остальные официальные OSC-плагины (Octavia, Manila, Barbican, Designate, Placement, Telemetry и другие) не включены. Отдельные `nova`, `neutron`, `cinder`, `glance`, `swift`, `heat`, `ironic` и остальные исторические сервисные CLI не добавляются к базовому OSC.

В исследованных пяти пакетах отдельно проверено важное различие способов вызова:

| Интерфейс | Что установлено |
|---|---|
| `watcher` | 28 standalone-команд ведут к тем же 28 обработчикам, что и `openstack optimize …`; функциональность не удваивается. |
| `mistral` | 75 регистраций, включая 74 предметные команды и completion. Три предметные команды не представлены в OSC 5.4.0: `action-validate`, `execution-get-sub-executions`, `task-get-sub-executions`. Остальные 71 сопоставлены с OSC. |
| `powerops-watcher-guard`, `powerops-evacuation-guard` | Собственные 3 и 8 подкоманд описаны выше; доступ к etcd через сервисную конфигурацию. |
| `kolla-ansible enroll-ironic` | Отдельная процедура регистрации BMC-only, не OSC-плагин. |

Проверка полноты выполнена сравнением ключей `(namespace, command)` с entry points зафиксированных версий:

- Базовый OSC: 683 регистрации = 547 основных + 136 legacy.
- Пять плагинов: 270 = Masakari 15 + Watcher 28 + Mistral 71 + Heat 49 + Ironic 107.
- Основная матрица: 817 = 547 + 270; у каждой строки есть статус UI, объяснение и первичные источники.
- Весь реестр `openstack`: 953 = 817 + 136; пропусков и дублей ключей между основным и legacy-разделами нет.
- Общие механизмы CLI, наследуемые `help`/completion, способы аутентификации и вывода разобраны отдельно; они не добавляются повторно к числу entry points.

Выводы о наличии интерфейса основаны на исходниках. Этот отчёт не удостоверяет runtime-доступность функций в установленном облаке и не подтверждает прохождение стендовых сценариев.

## 16. Воспроизводимость и источники

Ссылки `CLI` указывают на регистрацию/реализацию команды зафиксированной версии. Ссылки `UI` указывают на проверенные формы, таблицы, actions или registry; для отсутствующей операции это граница проверенного интерфейса, а не единственная строка, доказывающая отсутствие во всём проекте. Полные upstream-деревья оставлены в локальном исследовании; публикация ссылается на их теги. В `evidence/` сохранены только исходники собственных компонентов, на которые ссылается этот MD, с проверенными SHA256. Эти фрагменты не являются установочным пакетом сервисов.

- [Объединённый первичный реестр](https://github.com/lebtmalorny-rgb/mimaric/blob/89be5492cba1a1c44d187a7f1df4a4b2243e1ab1/docs/openstack-cli-horizon-2025.1/data/command-inventory.tsv).
- [Покомандная нормализованная матрица](https://github.com/lebtmalorny-rgb/mimaric/blob/89be5492cba1a1c44d187a7f1df4a4b2243e1ab1/docs/openstack-cli-horizon-2025.1/data/full-cli-horizon-matrix.tsv).
- [Зафиксированные upstream-источники](https://github.com/lebtmalorny-rgb/mimaric/blob/89be5492cba1a1c44d187a7f1df4a4b2243e1ab1/docs/openstack-cli-horizon-2025.1/data/upstream-source-manifest.json).
- [Архивы, SHA256 и HEAD собственных доработок](https://github.com/lebtmalorny-rgb/mimaric/blob/89be5492cba1a1c44d187a7f1df4a4b2243e1ab1/docs/openstack-cli-horizon-2025.1/data/local-source-manifest.json).
- [Результат проверки полноты документа](https://github.com/lebtmalorny-rgb/mimaric/blob/89be5492cba1a1c44d187a7f1df4a4b2243e1ab1/docs/openstack-cli-horizon-2025.1/data/verification.json).



[S0001]: https://github.com/openstack/python-openstackclient/blob/7.4.0/setup.cfg

[S0002]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/info/tables.py#L104

[S0003]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/info/tables.py#L73

[S0004]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/info/tabs.py#L1

[S0005]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/overview/views.py#L1

[S0006]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/identity/projects/tables.py#L1

[S0007]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/identity/projects/workflows.py#L200

[S0008]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/aggregate.py#L54

[S0009]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/aggregates/workflows.py#L202

[S0010]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/aggregates/tables.py#L165

[S0011]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/aggregate.py#L406

[S0012]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/aggregates/tables.py#L162

[S0013]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/aggregate.py#L87

[S0014]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/aggregates/workflows.py#L165

[S0015]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/aggregates/tables.py#L68

[S0016]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/aggregate.py#L135

[S0017]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/aggregates/tables.py#L23

[S0018]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/aggregate.py#L177

[S0019]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/aggregates/tables.py#L145

[S0020]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/aggregate.py#L237

[S0021]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/aggregates/workflows.py#L211

[S0022]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/aggregate.py#L270

[S0023]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/aggregates/forms.py#L25

[S0024]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/api/rest/nova.py#L684

[S0025]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/aggregate.py#L342

[S0026]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/aggregate.py#L371

[S0027]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/agent.py#L31

[S0028]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/hypervisors/compute/tables.py#L97

[S0029]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/agent.py#L82

[S0030]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/agent.py#L124

[S0031]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/agent.py#L166

[S0032]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/service.py#L31

[S0033]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/hypervisors/compute/tables.py#L139

[S0034]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/info/tables.py#L121

[S0035]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/service.py#L78

[S0036]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/service.py#L146

[S0037]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/hypervisors/compute/tables.py#L40

[S0038]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/hypervisors/compute/tables.py#L51

[S0039]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/hypervisors/compute/forms.py#L79

[S0040]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/console.py#L35

[S0041]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/tabs.py#L87

[S0042]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/console.py#L77

[S0043]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/console.py#L27

[S0044]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/tabs.py#L109

[S0045]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/api/nova.py#L197

[S0046]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/flavor.py#L57

[S0047]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/flavors/workflows.py#L29

[S0048]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/flavors/workflows.py#L192

[S0049]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/flavors/tables.py#L63

[S0050]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/flavor.py#L213

[S0051]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/flavors/tables.py#L31

[S0052]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/flavors/tables.py#L167

[S0053]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/flavor.py#L252

[S0054]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/flavors/tables.py#L138

[S0055]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/flavor.py#L374

[S0056]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/flavors/workflows.py#L242

[S0057]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/api/rest/nova.py#L641

[S0058]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/flavor.py#L490

[S0059]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/flavors/tables.py#L89

[S0060]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/flavor.py#L539

[S0061]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/flavors/workflows.py#L269

[S0062]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/api/rest/nova.py#L655

[S0063]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/host.py#L25

[S0064]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/host.py#L57

[S0065]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/host.py#L115

[S0066]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/hypervisors/tables.py#L21

[S0067]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/hypervisors/views.py#L48

[S0068]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/hypervisor.py#L70

[S0069]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/hypervisor.py#L154

[S0070]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/hypervisor_stats.py#L39

[S0071]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/hypervisors/views.py#L28

[S0072]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/api/nova.py#L817

[S0073]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/keypair.py#L75

[S0074]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/key_pairs/tables.py#L71

[S0075]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/key_pairs/tables.py#L85

[S0076]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/static/dashboard/project/workflow/launch-instance/keypair/create-keypair.controller.js#L71

[S0077]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/key_pairs/forms.py#L39

[S0078]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/keypair.py#L210

[S0079]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/key_pairs/tables.py#L28

[S0080]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/key_pairs/tables.py#L133

[S0081]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/keypair.py#L274

[S0082]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/key_pairs/views.py#L37

[S0083]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/key_pairs/tables.py#L120

[S0084]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/keypair.py#L386

[S0085]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/key_pairs/views.py#L75

[S0086]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server.py#L369

[S0087]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/forms.py#L291

[S0088]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/forms.py#L352

[S0089]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/tables.py#L966

[S0090]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server.py#L467

[S0091]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/tables.py#L680

[S0092]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server.py#L617

[S0093]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server.py#L563

[S0094]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server.py#L672

[S0095]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/tables.py#L500

[S0096]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/workflows/update_instance.py#L26

[S0097]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server.py#L741

[S0098]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/forms.py#L173

[S0099]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/forms.py#L208

[S0100]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/tables.py#L933

[S0101]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server_backup.py#L27

[S0102]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/tables.py#L1295

[S0103]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/images/snapshots/forms.py#L30

[S0104]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server.py#L1107

[S0105]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/static/dashboard/project/workflow/launch-instance/launch-instance-model.service.js#L176

[S0106]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/api/rest/nova.py#L315

[S0107]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/tables.py#L418

[S0108]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server.py#L2204

[S0109]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/tables.py#L86

[S0110]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/instances/tables.py#L193

[S0111]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server.py#L2175

[S0112]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/instances/tables.py#L196

[S0113]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server.py#L3798

[S0114]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/hypervisors/compute/tables.py#L25

[S0115]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/hypervisors/compute/forms.py#L23

[S0116]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/api/nova.py#L827

[S0117]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server_event.py#L105

[S0118]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/tabs.py#L140

[S0119]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/audit_tables.py#L22

[S0120]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server_event.py#L254

[S0121]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/audit_tables.py#L48

[S0122]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/api/nova.py#L1029

[S0123]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server_group.py#L55

[S0124]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/static/app/core/server_groups/actions/workflow/workflow.service.js#L40

[S0125]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/static/app/core/server_groups/actions/actions.module.js#L67

[S0126]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server_group.py#L142

[S0127]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/static/app/core/server_groups/actions/actions.module.js#L47

[S0128]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/api/rest/nova.py#L454

[S0129]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server_group.py#L177

[S0130]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/static/app/core/server_groups/server-groups.module.js#L44

[S0131]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/api/rest/nova.py#L424

[S0132]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/api/nova.py#L924

[S0133]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server_group.py#L254

[S0134]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/static/app/core/server_groups/details/overview.controller.js#L40

[S0135]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server_image.py#L32

[S0136]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/tables.py#L527

[S0137]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server.py#L2306

[S0138]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/tables.py#L1232

[S0139]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/instances/tables.py#L129

[S0140]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server.py#L3100

[S0141]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/tables.py#L869

[S0142]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server.py#L3158

[S0143]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/instances/tables.py#L49

[S0144]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/instances/forms.py#L28

[S0145]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/api/nova.py#L605

[S0146]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server.py#L4343

[S0147]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/tables.py#L603

[S0148]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server.py#L4391

[S0149]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/tables.py#L623

[S0150]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server_migration.py#L386

[S0151]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/tabs.py#L160

[S0152]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server.py#L4356

[S0153]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server_migration.py#L453

[S0154]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server_migration.py#L27

[S0155]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server.py#L4404

[S0156]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server_migration.py#L269

[S0157]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server.py#L3340

[S0158]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/tables.py#L224

[S0159]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/tables.py#L279

[S0160]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server.py#L3363

[S0161]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/tables.py#L117

[S0162]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/tables.py#L152

[S0163]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server.py#L3423

[S0164]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/forms.py#L39

[S0165]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/forms.py#L104

[S0166]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server.py#L3916

[S0167]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/forms.py#L376

[S0168]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server.py#L3944

[S0169]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/tables.py#L713

[S0170]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/forms.py#L417

[S0171]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server.py#L4016

[S0172]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server.py#L3977

[S0173]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/forms.py#L402

[S0174]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server.py#L4056

[S0175]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server.py#L4125

[S0176]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/forms.py#L235

[S0177]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/forms.py#L267

[S0178]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server.py#L4167

[S0179]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/forms.py#L468

[S0180]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/tables.py#L180

[S0181]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server.py#L4218

[S0182]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/tables.py#L578

[S0183]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/workflows/resize_instance.py#L104

[S0184]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server.py#L4318

[S0185]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server.py#L4365

[S0186]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server.py#L4413

[S0187]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server.py#L4436

[S0188]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/tables.py#L288

[S0189]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/tables.py#L343

[S0190]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server.py#L4459

[S0191]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/workflows/update_instance.py#L70

[S0192]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/tables.py#L733

[S0193]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/api/rest/nova.py#L475

[S0194]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server.py#L4620

[S0195]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/tables.py#L352

[S0196]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/tables.py#L409

[S0197]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/api/nova.py#L570

[S0198]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server.py#L4729

[S0199]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/templates/instances/_detail_overview.html#L1

[S0200]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/tabs.py#L32

[S0201]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server.py#L4796

[S0202]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/tables.py#L540

[S0203]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server.py#L4957

[S0204]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/tables.py#L807

[S0205]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server.py#L4992

[S0206]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/tables.py#L836

[S0207]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server.py#L5026

[S0208]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server.py#L5049

[S0209]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/tables.py#L901

[S0210]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server.py#L5072

[S0211]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server.py#L5095

[S0212]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/tables.py#L195

[S0213]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server.py#L5115

[S0214]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/api/rest/nova.py#L491

[S0215]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/api/nova.py#L599

[S0216]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server.py#L5211

[S0217]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/tables.py#L386

[S0218]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/api/nova.py#L575

[S0219]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server_volume.py#L25

[S0220]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/instances/templates/instances/_detail_overview.html#L158

[S0221]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server_volume.py#L81

[S0222]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/server_volume.py#L146

[S0223]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/usage.py#L108

[S0224]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/overview/views.py#L46

[S0225]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/usage/base.py#L154

[S0226]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/compute/v2/usage.py#L209

[S0227]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/overview/views.py#L56

[S0228]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/identity/projects/views.py#L141

[S0229]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/usage/base.py#L161

[S0230]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/address_group.py#L60

[S0231]: https://github.com/openstack/horizon/tree/25.3.0/openstack_dashboard/enabled

[S0232]: https://github.com/openstack/horizon/tree/25.3.0/openstack_dashboard/dashboards

[S0233]: https://github.com/openstack/horizon/tree/25.3.0/openstack_dashboard/static/app/core

[S0234]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/address_group.py#L107

[S0235]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/address_group.py#L147

[S0236]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/address_group.py#L212

[S0237]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/address_group.py#L264

[S0238]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/address_group.py#L288

[S0239]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/address_scope.py#L61

[S0240]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/address_scope.py#L112

[S0241]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/address_scope.py#L154

[S0242]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/address_scope.py#L248

[S0243]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/address_scope.py#L293

[S0244]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/default_security_group_rule.py#L38

[S0245]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/default_security_group_rule.py#L232

[S0246]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/default_security_group_rule.py#L277

[S0247]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/default_security_group_rule.py#L390

[S0248]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/floating_ip.py#L95

[S0249]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/floating_ips/forms.py#L30

[S0250]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/floating_ip.py#L209

[S0251]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/floating_ips/tables.py#L324

[S0252]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/floating_ip.py#L236

[S0253]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/floating_ip_pool.py#L22

[S0254]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/floating_ip_port_forwarding.py#L95

[S0255]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/floating_ip_portforwardings/tables.py#L131

[S0256]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/floating_ip_portforwardings/workflows.py#L60

[S0257]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/floating_ip_port_forwarding.py#L198

[S0258]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/floating_ip_port_forwarding.py#L251

[S0259]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/floating_ip_port_forwarding.py#L351

[S0260]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/floating_ip_port_forwarding.py#L451

[S0261]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/floating_ip_portforwardings/views.py#L35

[S0262]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/floating_ip.py#L441

[S0263]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/floating_ips/workflows.py#L153

[S0264]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/floating_ip.py#L522

[S0265]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/floating_ips/templates/floating_ips/detail.html#L1

[S0266]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/floating_ip.py#L549

[S0267]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/floating_ips/tables.py#L219

[S0268]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/ip_availability.py#L38

[S0269]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/networks/subnets/tables.py#L63

[S0270]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/ip_availability.py#L104

[S0271]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/local_ip_association.py#L38

[S0272]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/local_ip_association.py#L84

[S0273]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/local_ip_association.py#L139

[S0274]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/local_ip.py#L71

[S0275]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/local_ip.py#L118

[S0276]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/local_ip.py#L190

[S0277]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/local_ip.py#L158

[S0278]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/local_ip.py#L297

[S0279]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/network_agent.py#L59

[S0280]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/networks/agents/tables.py#L31

[S0281]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/networks/agents/forms.py#L25

[S0282]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/network_agent.py#L96

[S0283]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/info/tables.py#L185

[S0284]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/network_agent.py#L125

[S0285]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/network_agent.py#L165

[S0286]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/info/tables.py#L202

[S0287]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/network_agent.py#L290

[S0288]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/network_agent.py#L326

[S0289]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/network_agent.py#L359

[S0290]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/network_agent.py#L398

[S0291]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/network_auto_allocated_topology.py#L64

[S0292]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/network_auto_allocated_topology.py#L125

[S0293]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/network.py#L203

[S0294]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/networks/forms.py#L92

[S0295]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/networks/workflows.py#L37

[S0296]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/network.py#L430

[S0297]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/networks/tables.py#L190

[S0298]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/networks/templates/networks/_detail_overview.html#L1

[S0299]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/network_flavor.py#L62

[S0300]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/network_flavor.py#L92

[S0301]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/network_flavor.py#L145

[S0302]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/network_flavor.py#L185

[S0303]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/network_flavor_profile.py#L55

[S0304]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/network_flavor_profile.py#L113

[S0305]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/network_flavor_profile.py#L154

[S0306]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/network_flavor_profile.py#L190

[S0307]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/network_flavor_profile.py#L246

[S0308]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/network_flavor.py#L213

[S0309]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/network_flavor.py#L243

[S0310]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/network_flavor.py#L287

[S0311]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/l3_conntrack_helper.py#L48

[S0312]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/l3_conntrack_helper.py#L94

[S0313]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/l3_conntrack_helper.py#L142

[S0314]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/l3_conntrack_helper.py#L205

[S0315]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/l3_conntrack_helper.py#L252

[S0316]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/network.py#L458

[S0317]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/network_meter.py#L64

[S0318]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/network_meter.py#L117

[S0319]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/network_meter.py#L154

[S0320]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/network_meter_rule.py#L68

[S0321]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/network_meter_rule.py#L145

[S0322]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/network_meter_rule.py#L186

[S0323]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/network_meter_rule.py#L221

[S0324]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/network_meter.py#L186

[S0325]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/network_qos_policy.py#L82

[S0326]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/static/app/core/network_qos/actions/actions.module.js#L32

[S0327]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/static/app/core/network_qos/actions/workflow/workflow.service.js#L37

[S0328]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/network_qos_policy.py#L143

[S0329]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/static/app/core/network_qos/details/overview.html#L1

[S0330]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/network_qos_policy.py#L184

[S0331]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/network_qos_policy.py#L243

[S0332]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/network_qos_policy.py#L295

[S0333]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/network_qos_rule.py#L237

[S0334]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/static/app/core/network_qos/actions/add-rule.action.service.js#L129

[S0335]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/network_qos_rule.py#L285

[S0336]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/static/app/core/network_qos/actions/delete-rule.action.service.js#L85

[S0337]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/network_qos_rule.py#L322

[S0338]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/static/app/core/network_qos/details/overview.html#L24

[S0339]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/network_qos_rule.py#L368

[S0340]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/static/app/core/network_qos/actions/edit-rule.action.service.js#L135

[S0341]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/network_qos_rule.py#L414

[S0342]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/network_qos_rule_type.py#L33

[S0343]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/network_qos_rule_type.py#L82

[S0344]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/network_rbac.py#L95

[S0345]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/rbac_policies/forms.py#L30

[S0346]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/rbac_policies/tables.py#L24

[S0347]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/network_rbac.py#L181

[S0348]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/rbac_policies/tabs.py#L25

[S0349]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/network_rbac.py#L220

[S0350]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/network_rbac.py#L314

[S0351]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/rbac_policies/forms.py#L159

[S0352]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/network_rbac.py#L363

[S0353]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/network_segment.py#L36

[S0354]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/network_segment.py#L108

[S0355]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/network_segment.py#L149

[S0356]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/network_segment_range.py#L95

[S0357]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/network_segment_range.py#L253

[S0358]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/network_segment_range.py#L306

[S0359]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/network_segment_range.py#L422

[S0360]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/network_segment_range.py#L487

[S0361]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/network_segment.py#L212

[S0362]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/network_segment.py#L250

[S0363]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/network_service_provider.py#L22

[S0364]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/network.py#L727

[S0365]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/networks/forms.py#L35

[S0366]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/admin/networks/forms.py#L337

[S0367]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/network.py#L847

[S0368]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/network_trunk.py#L263

[S0369]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/static/app/core/trunks/details/overview.html#L1

[S0370]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/network_trunk.py#L43

[S0371]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/static/app/core/trunks/actions/actions.module.js#L45

[S0372]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/network_trunk.py#L100

[S0373]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/network_trunk.py#L138

[S0374]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/network_trunk.py#L177

[S0375]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/api/neutron.py#L1126

[S0376]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/network_trunk.py#L242

[S0377]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/network_trunk.py#L294

[S0378]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/api/neutron.py#L1153

[S0379]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/network.py#L871

[S0380]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/port.py#L487

[S0381]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/networks/ports/workflows.py#L57

[S0382]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/networks/ports/tables.py#L137

[S0383]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/port.py#L723

[S0384]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/networks/ports/views.py#L70

[S0385]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/port.py#L765

[S0386]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/port.py#L965

[S0387]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/networks/ports/workflows.py#L303

[S0388]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/networks/ports/extensions/allowed_address_pairs/tables.py#L31

[S0389]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/port.py#L1221

[S0390]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/port.py#L1241

[S0391]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/networks/ports/workflows.py#L373

[S0392]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/networks/ports/extensions/allowed_address_pairs/tables.py#L55

[S0393]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/router.py#L1248

[S0394]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/routers/ports/forms.py#L147

[S0395]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/routers/tables.py#L110

[S0396]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/router.py#L310

[S0397]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/routers/ports/forms.py#L28

[S0398]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/routers/ports/forms.py#L107

[S0399]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/router.py#L360

[S0400]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/routers/extensions/extraroutes/tables.py#L26

[S0401]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/router.py#L334

[S0402]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/routers/ports/tables.py#L39

[S0403]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/router.py#L462

[S0404]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/routers/forms.py#L34

[S0405]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/routers/tables.py#L257

[S0406]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/router.py#L641

[S0407]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/routers/tables.py#L36

[S0408]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/router.py#L683

[S0409]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/ndp_proxy.py#L39

[S0410]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/ndp_proxy.py#L103

[S0411]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/ndp_proxy.py#L138

[S0412]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/ndp_proxy.py#L233

[S0413]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/ndp_proxy.py#L270

[S0414]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/router.py#L1316

[S0415]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/router.py#L827

[S0416]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/routers/ports/tables.py#L52

[S0417]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/router.py#L409

[S0418]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/router.py#L853

[S0419]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/routers/ports/tables.py#L81

[S0420]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/router.py#L883

[S0421]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/routers/forms.py#L159

[S0422]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/router.py#L1117

[S0423]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/router.py#L1153

[S0424]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/routers/tables.py#L124

[S0425]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/routers/extensions/extraroutes/tables.py#L39

[S0426]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/security_group.py#L102

[S0427]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/security_groups/forms.py#L36

[S0428]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/security_groups/tables.py#L113

[S0429]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/security_group.py#L196

[S0430]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/security_groups/views.py#L40

[S0431]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/security_group.py#L223

[S0432]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/security_group_rule.py#L42

[S0433]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/security_groups/forms.py#L97

[S0434]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/security_group_rule.py#L327

[S0435]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/security_groups/tables.py#L143

[S0436]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/security_groups/tables.py#L247

[S0437]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/security_group_rule.py#L351

[S0438]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/security_group_rule.py#L571

[S0439]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/security_group.py#L324

[S0440]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/security_group.py#L407

[S0441]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/security_group.py#L437

[S0442]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/subnet.py#L291

[S0443]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/networks/subnets/workflows.py#L32

[S0444]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/networks/workflows.py#L105

[S0445]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/subnet.py#L435

[S0446]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/networks/subnets/tables.py#L110

[S0447]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/networks/subnets/views.py#L105

[S0448]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/subnet.py#L477

[S0449]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/subnet_pool.py#L154

[S0450]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/networks/subnets/views.py#L122

[S0451]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/networks/workflows.py#L247

[S0452]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/subnet_pool.py#L225

[S0453]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/subnet_pool.py#L266

[S0454]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/subnet_pool.py#L392

[S0455]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/subnet_pool.py#L463

[S0456]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/subnet_pool.py#L485

[S0457]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/subnet.py#L650

[S0458]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/networks/subnets/workflows.py#L94

[S0459]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/networks/subnets/workflows.py#L199

[S0460]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/subnet.py#L743

[S0461]: https://github.com/openstack/python-openstackclient/blob/7.4.0/openstackclient/network/v2/subnet.py#L764

[S0462]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/networks/workflows.py#L340

[S0463]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/volume/v3/block_storage_cleanup.py#L46

[S0464]: https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/admin/info/tables.py#L128

[S0465]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/volume/v3/block_storage_cluster.py#L70

[S0466]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/volume/v3/block_storage_cluster.py#L177

[S0467]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/volume/v3/block_storage_cluster.py#L248

[S0468]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/volume/v3/block_storage_log_level.py#L25

[S0469]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/volume/v3/block_storage_log_level.py#L101

[S0470]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/volume/v3/block_storage_resource_filter.py#L24

[S0471]: https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/project/volumes/tables.py#L527

[S0472]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/volume/v3/block_storage_resource_filter.py#L58

[S0473]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/volume/v3/block_storage_manage.py#L193

[S0474]: https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/admin/snapshots/tables.py#L69

[S0475]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/volume/v3/block_storage_manage.py#L29

[S0476]: https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/admin/volumes/forms.py#L46

[S0477]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/volume/v2/consistency_group.py#L51

[S0478]: https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/api/cinder.py#L1137

[S0479]: https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/project/volume_groups/tables.py#L175

[S0480]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/volume/v2/consistency_group.py#L93

[S0481]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/volume/v2/consistency_group.py#L195

[S0482]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/volume/v2/consistency_group.py#L245

[S0483]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/volume/v2/consistency_group.py#L296

[S0484]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/volume/v2/consistency_group.py#L338

[S0485]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/volume/v2/consistency_group.py#L376

[S0486]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/volume/v2/consistency_group_snapshot.py#L29

[S0487]: https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/api/cinder.py#L1226

[S0488]: https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/project/vg_snapshots/tables.py#L130

[S0489]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/volume/v2/consistency_group_snapshot.py#L74

[S0490]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/volume/v2/consistency_group_snapshot.py#L117

[S0491]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/volume/v2/consistency_group_snapshot.py#L195

[S0492]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/volume/v3/volume_attachment.py#L361

[S0493]: https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/project/volumes/forms.py#L469

[S0494]: https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/project/volumes/tables.py#L592

[S0495]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/volume/v3/volume_attachment.py#L78

[S0496]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/volume/v3/volume_attachment.py#L238

[S0497]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/volume/v3/volume_attachment.py#L386

[S0498]: https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/project/volumes/views.py#L550

[S0499]: https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/project/volumes/tables.py#L636

[S0500]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/volume/v3/volume_attachment.py#L272

[S0501]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/volume/v3/volume_attachment.py#L488

[S0502]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/volume/v2/volume_backend.py#L24

[S0503]: https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/admin/volumes/tables.py#L114

[S0504]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/volume/v2/volume_backend.py#L71

[S0505]: https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/admin/volumes/views.py#L246

[S0506]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/volume/v3/volume_backup.py#L62

[S0507]: https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/project/backups/forms.py#L32

[S0508]: https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/defaults.py#L369

[S0509]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/volume/v3/volume_backup.py#L183

[S0510]: https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/project/backups/tables.py#L67

[S0511]: https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/admin/backups/tables.py#L36

[S0512]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/volume/v3/volume_backup.py#L235

[S0513]: https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/project/backups/tables.py#L149

[S0514]: https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/admin/backups/tables.py#L109

[S0515]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/volume/v2/backup_record.py#L28

[S0516]: https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/project/backups/tables.py#L203

[S0517]: https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/admin/backups/tables.py#L122

[S0518]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/volume/v2/backup_record.py#L59

[S0519]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/volume/v3/volume_backup.py#L382

[S0520]: https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/project/backups/forms.py#L130

[S0521]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/volume/v3/volume_backup.py#L455

[S0522]: https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/admin/backups/forms.py#L24

[S0523]: https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/admin/backups/tables.py#L87

[S0524]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/volume/v3/volume_backup.py#L643

[S0525]: https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/project/backups/tabs.py#L30

[S0526]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/volume/v3/volume_backup.py#L586

[S0527]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/volume/v3/volume.py#L94

[S0528]: https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/project/volumes/forms.py#L78

[S0529]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/volume/v3/volume.py#L358

[S0530]: https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/project/volumes/tables.py#L98

[S0531]: https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/admin/volumes/forms.py#L138

[S0532]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/volume/v3/volume_group.py#L62

[S0533]: https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/project/volume_groups/workflows.py#L31

[S0534]: https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/project/volume_groups/forms.py#L140

[S0535]: https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/project/vg_snapshots/forms.py#L24

[S0536]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/volume/v3/volume_group.py#L272

[S0537]: https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/project/volume_groups/forms.py#L80

[S0538]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/volume/v3/volume_group.py#L567

[S0539]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/volume/v3/volume_group.py#L401

[S0540]: https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/project/volume_groups/tables.py#L133

[S0541]: https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/admin/volume_groups/tables.py#L53

[S0542]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/volume/v3/volume_group.py#L314

[S0543]: https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/project/volume_groups/forms.py#L24

[S0544]: https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/project/volume_groups/workflows.py#L260

[S0545]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/volume/v3/volume_group.py#L465

[S0546]: https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/project/volume_groups/tabs.py#L25

[S0547]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/volume/v3/volume_group_snapshot.py#L52

[S0548]: https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/project/volume_groups/forms.py#L103

[S0549]: https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/project/vg_snapshots/tables.py#L92

[S0550]: https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/project/vg_snapshots/tabs.py#L24

[S0551]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/volume/v3/volume_group_snapshot.py#L102

[S0552]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/volume/v3/volume_group_snapshot.py#L136

[S0553]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/volume/v3/volume_group_snapshot.py#L198

[S0554]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/volume/v3/volume_group_type.py#L57

[S0555]: https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/admin/group_types/tables.py#L101

[S0556]: https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/admin/group_types/forms.py#L24

[S0557]: https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/admin/group_types/specs/tables.py#L74

[S0558]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/volume/v3/volume_group_type.py#L110

[S0559]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/volume/v3/volume_group_type.py#L310

[S0560]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/volume/v3/volume_group_type.py#L143

[S0561]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/volume/v3/volume_group_type.py#L375

[S0562]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/volume/v2/volume_host.py#L48

[S0563]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/volume/v3/volume.py#L412

[S0564]: https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/project/volumes/tables.py#L554

[S0565]: https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/admin/volumes/tables.py#L99

[S0566]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/volume/v3/volume_message.py#L29

[S0567]: https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/project/volumes/tables.py#L664

[S0568]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/volume/v3/volume_message.py#L70

[S0569]: https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/project/volumes/tabs.py#L82

[S0570]: https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/project/backups/tabs.py#L58

[S0571]: https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/project/snapshots/tabs.py#L48

[S0572]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/volume/v3/volume_message.py#L132

[S0573]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/volume/v3/volume.py#L556

[S0574]: https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/admin/volumes/forms.py#L166

[S0575]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/volume/v2/qos_specs.py#L32

[S0576]: https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/admin/volume_types/forms.py#L167

[S0577]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/volume/v2/qos_specs.py#L61

[S0578]: https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/admin/volume_types/tables.py#L268

[S0579]: https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/admin/volume_types/tables.py#L323

[S0580]: https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/admin/volume_types/qos_specs/tables.py#L78

[S0581]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/volume/v2/qos_specs.py#L116

[S0582]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/volume/v2/qos_specs.py#L162

[S0583]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/volume/v2/qos_specs.py#L202

[S0584]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/volume/v2/qos_specs.py#L250

[S0585]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/volume/v2/qos_specs.py#L312

[S0586]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/volume/v2/qos_specs.py#L349

[S0587]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/volume/v3/volume.py#L1052

[S0588]: https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/project/snapshots/tables.py#L127

[S0589]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/volume/v3/service.py#L23

[S0590]: https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/admin/info/tabs.py#L74

[S0591]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/volume/v2/service.py#L85

[S0592]: https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/admin/info/tables.py#L145

[S0593]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/volume/v3/volume.py#L604

[S0594]: https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/project/volumes/forms.py#L660

[S0595]: https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/project/volumes/forms.py#L759

[S0596]: https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/project/volumes/forms.py#L810

[S0597]: https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/project/volumes/tables.py#L536

[S0598]: https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/admin/volumes/forms.py#L216

[S0599]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/volume/v3/volume.py#L910

[S0600]: https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/project/volumes/tabs.py#L31

[S0601]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/volume/v2/volume_snapshot.py#L63

[S0602]: https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/project/volumes/forms.py#L544

[S0603]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/volume/v3/volume_snapshot.py#L28

[S0604]: https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/project/snapshots/tables.py#L72

[S0605]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/volume/v2/volume_snapshot.py#L209

[S0606]: https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/project/snapshots/tables.py#L227

[S0607]: https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/admin/snapshots/tables.py#L56

[S0608]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/volume/v2/volume_snapshot.py#L345

[S0609]: https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/project/snapshots/forms.py#L24

[S0610]: https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/project/snapshots/tables.py#L163

[S0611]: https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/admin/snapshots/forms.py#L24

[S0612]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/volume/v2/volume_snapshot.py#L460

[S0613]: https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/project/snapshots/tabs.py#L28

[S0614]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/volume/v2/volume_snapshot.py#L487

[S0615]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/volume/v3/volume.py#L1002

[S0616]: https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/project/volumes/tables.py#L575

[S0617]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/volume/v3/volume_transfer_request.py#L30

[S0618]: https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/project/volumes/forms.py#L621

[S0619]: https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/project/volumes/tables.py#L307

[S0620]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/volume/v3/volume_transfer_request.py#L69

[S0621]: https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/project/volumes/forms.py#L588

[S0622]: https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/project/volumes/views.py#L438

[S0623]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/volume/v3/volume_transfer_request.py#L136

[S0624]: https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/project/volumes/tables.py#L338

[S0625]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/volume/v3/volume_transfer_request.py#L179

[S0626]: https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/project/volumes/views.py#L62

[S0627]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/volume/v3/volume_transfer_request.py#L213

[S0628]: https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/project/volumes/forms.py#L642

[S0629]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/volume/v3/volume_type.py#L109

[S0630]: https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/admin/volume_types/tables.py#L223

[S0631]: https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/admin/volume_types/forms.py#L95

[S0632]: https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/admin/volume_types/forms.py#L313

[S0633]: https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/admin/volume_types/extras/tables.py#L68

[S0634]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/volume/v3/volume_type.py#L330

[S0635]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/volume/v3/volume_type.py#L372

[S0636]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/volume/v3/volume_type.py#L564

[S0637]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/volume/v3/volume_type.py#L803

[S0638]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/volume/v3/volume_type.py#L874

[S0639]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/volume/v3/volume.py#L943

[S0640]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/image/v2/cache.py#L188

[S0641]: https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/static/app/core/images/actions/actions.module.js#L60

[S0642]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/image/v2/cache.py#L148

[S0643]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/image/v2/cache.py#L66

[S0644]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/image/v2/cache.py#L107

[S0645]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/image/v2/image.py#L227

[S0646]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/image/v2/image.py#L271

[S0647]: https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/static/app/core/images/actions/actions.module.js#L113

[S0648]: https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/static/app/core/images/actions/create.action.service.js#L46

[S0649]: https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/project/volumes/forms.py#L701

[S0650]: https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/api/glance.py#L455

[S0651]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/image/v2/image.py#L668

[S0652]: https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/static/app/core/images/actions/actions.module.js#L104

[S0653]: https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/static/app/core/images/actions/delete-image.service.js#L43

[S0654]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/image/v2/image.py#L1604

[S0655]: https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/api/rest/glance.py#L238

[S0656]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/image/v2/info.py#L20

[S0657]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/image/v2/image.py#L722

[S0658]: https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/static/app/core/images/images.module.js#L70

[S0659]: https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/project/images/urls.py#L31

[S0660]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/image/v2/image.py#L1019

[S0661]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/image/v2/image.py#L947

[S0662]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/image/v2/metadef_namespaces.py#L65

[S0663]: https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/admin/metadata_defs/forms.py#L34

[S0664]: https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/admin/metadata_defs/views.py#L84

[S0665]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/image/v2/metadef_namespaces.py#L139

[S0666]: https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/admin/metadata_defs/tables.py#L43

[S0667]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/image/v2/metadef_namespaces.py#L178

[S0668]: https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/admin/metadata_defs/views.py#L38

[S0669]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/image/v2/metadef_namespaces.py#L220

[S0670]: https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/admin/metadata_defs/forms.py#L147

[S0671]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/image/v2/metadef_namespaces.py#L296

[S0672]: https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/admin/metadata_defs/tabs.py#L26

[S0673]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/image/v2/metadef_objects.py#L50

[S0674]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/image/v2/metadef_objects.py#L113

[S0675]: https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/admin/metadata_defs/tables.py#L141

[S0676]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/image/v2/metadef_objects.py#L160

[S0677]: https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/admin/metadata_defs/tabs.py#L45

[S0678]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/image/v2/metadef_objects.py#L228

[S0679]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/image/v2/metadef_objects.py#L83

[S0680]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/image/v2/metadef_objects.py#L192

[S0681]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/image/v2/metadef_properties.py#L57

[S0682]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/image/v2/metadef_properties.py#L114

[S0683]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/image/v2/metadef_properties.py#L166

[S0684]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/image/v2/metadef_properties.py#L194

[S0685]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/image/v2/metadef_properties.py#L259

[S0686]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/image/v2/metadef_resource_type_association.py#L32

[S0687]: https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/admin/metadata_defs/forms.py#L116

[S0688]: https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/dashboards/admin/metadata_defs/views.py#L157

[S0689]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/image/v2/metadef_resource_type_association.py#L80

[S0690]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/image/v2/metadef_resource_type_association.py#L161

[S0691]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/image/v2/metadef_resource_types.py#L21

[S0692]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/image/v2/image.py#L983

[S0693]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/image/v2/image.py#L1056

[S0694]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/image/v2/image.py#L1088

[S0695]: https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/static/app/core/images/actions/actions.module.js#L76

[S0696]: https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/static/app/core/images/actions/edit.action.service.js#L40

[S0697]: https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/static/app/core/images/actions/update-metadata.action.service.js#L40

[S0698]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/image/v2/image.py#L1389

[S0699]: https://opendev.org/openstack/horizon/src/tag/25.3.0/openstack_dashboard/static/app/core/images/details/details.module.js#L20

[S0700]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/image/v2/image.py#L1527

[S0701]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/image/v2/image.py#L1848

[S0702]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/image/v2/task.py#L86

[S0703]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/image/v2/task.py#L63

[S0704]: https://opendev.org/openstack/python-openstackclient/src/tag/7.4.0/openstackclient/image/v2/image.py#L1419

[S0705]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/identity/application_credentials/forms.py#L53

[S0706]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/enabled/_3000_identity.py#L1

[S0707]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/identity/application_credentials/tables.py#L1

[S0708]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/identity/credentials/tables.py#L1

[S0709]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/identity/domains/tables.py#L1

[S0710]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/api_access/tables.py#L34

[S0711]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/identity/identity_providers/protocols/tables.py#L1

[S0712]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/identity/groups/tables.py#L1

[S0713]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/identity/identity_providers/tables.py#L1

[S0714]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/identity/mappings/tables.py#L1

[S0715]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/identity/roles/tables.py#L1

[S0716]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/identity/users/role_assignments/tables.py#L1

[S0717]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/identity/users/tables.py#L1

[S0718]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/static/dashboard/project/containers/containers.controller.js#L85

[S0719]: https://github.com/openstack/horizon/blob/25.3.0/openstack_dashboard/dashboards/project/static/dashboard/project/containers/objects-row-actions.service.js#L54

[S0720]: https://github.com/openstack/python-masakariclient/blob/8.6.0/setup.cfg#L34

[S0721]: https://github.com/openstack/masakari-dashboard/blob/12.0.0/masakaridashboard/notifications/tables.py#L1

[S0722]: https://github.com/openstack/python-masakariclient/blob/8.6.0/setup.cfg#L36

[S0723]: https://github.com/openstack/python-masakariclient/blob/8.6.0/setup.cfg#L35

[S0724]: https://github.com/openstack/python-masakariclient/blob/8.6.0/setup.cfg#L38

[S0725]: https://github.com/openstack/masakari-dashboard/blob/12.0.0/masakaridashboard/vmoves/tables.py#L1

[S0726]: https://github.com/openstack/python-masakariclient/blob/8.6.0/setup.cfg#L37

[S0727]: https://github.com/openstack/python-masakariclient/blob/8.6.0/setup.cfg#L39

[S0728]: https://github.com/openstack/masakari-dashboard/blob/12.0.0/masakaridashboard/segments/tables.py#L1

[S0729]: https://github.com/openstack/python-masakariclient/blob/8.6.0/setup.cfg#L41

[S0730]: https://github.com/openstack/python-masakariclient/blob/8.6.0/setup.cfg#L44

[S0731]: https://github.com/openstack/masakari-dashboard/blob/12.0.0/masakaridashboard/hosts/tables.py#L1

[S0732]: https://github.com/openstack/python-masakariclient/blob/8.6.0/setup.cfg#L47

[S0733]: https://github.com/openstack/python-masakariclient/blob/8.6.0/setup.cfg#L46

[S0734]: https://github.com/openstack/python-masakariclient/blob/8.6.0/setup.cfg#L45

[S0735]: https://github.com/openstack/python-masakariclient/blob/8.6.0/setup.cfg#L48

[S0736]: https://github.com/openstack/python-masakariclient/blob/8.6.0/setup.cfg#L43

[S0737]: https://github.com/openstack/python-masakariclient/blob/8.6.0/setup.cfg#L42

[S0738]: https://github.com/openstack/python-masakariclient/blob/8.6.0/setup.cfg#L40

[S0739]: https://github.com/openstack/python-watcherclient/blob/4.8.0/setup.cfg#L63

[S0740]: https://github.com/openstack/watcher-dashboard/blob/13.0.0/watcher_dashboard/content/actions/tables.py#L1

[S0741]: https://github.com/openstack/python-watcherclient/blob/4.8.0/setup.cfg#L62

[S0742]: https://github.com/openstack/python-watcherclient/blob/4.8.0/setup.cfg#L60

[S0743]: https://github.com/openstack/watcher-dashboard/blob/13.0.0/watcher_dashboard/content/action_plans/tables.py#L1

[S0744]: https://github.com/openstack/python-watcherclient/blob/4.8.0/setup.cfg#L56

[S0745]: https://github.com/openstack/python-watcherclient/blob/4.8.0/setup.cfg#L57

[S0746]: https://github.com/openstack/python-watcherclient/blob/4.8.0/setup.cfg#L55

[S0747]: https://github.com/openstack/python-watcherclient/blob/4.8.0/setup.cfg#L59

[S0748]: https://github.com/openstack/python-watcherclient/blob/4.8.0/setup.cfg#L58

[S0749]: https://github.com/openstack/python-watcherclient/blob/4.8.0/setup.cfg#L51

[S0750]: https://github.com/openstack/watcher-dashboard/blob/13.0.0/watcher_dashboard/content/audits/tables.py#L1

[S0751]: https://github.com/openstack/python-watcherclient/blob/4.8.0/setup.cfg#L53

[S0752]: https://github.com/openstack/python-watcherclient/blob/4.8.0/setup.cfg#L50

[S0753]: https://github.com/openstack/python-watcherclient/blob/4.8.0/setup.cfg#L49

[S0754]: https://github.com/openstack/python-watcherclient/blob/4.8.0/setup.cfg#L52

[S0755]: https://github.com/openstack/python-watcherclient/blob/4.8.0/setup.cfg#L45

[S0756]: https://github.com/openstack/watcher-dashboard/blob/13.0.0/watcher_dashboard/content/audit_templates/tables.py#L1

[S0757]: https://github.com/openstack/python-watcherclient/blob/4.8.0/setup.cfg#L47

[S0758]: https://github.com/openstack/python-watcherclient/blob/4.8.0/setup.cfg#L44

[S0759]: https://github.com/openstack/python-watcherclient/blob/4.8.0/setup.cfg#L43

[S0760]: https://github.com/openstack/python-watcherclient/blob/4.8.0/setup.cfg#L46

[S0761]: https://github.com/openstack/python-watcherclient/blob/4.8.0/setup.cfg#L71

[S0762]: https://github.com/openstack/watcher-dashboard/blob/13.0.0/watcher_dashboard/local/enabled/_31020_watcher_panelgroup.py#L1

[S0763]: https://github.com/openstack/python-watcherclient/blob/4.8.0/setup.cfg#L37

[S0764]: https://github.com/openstack/watcher-dashboard/blob/13.0.0/watcher_dashboard/content/goals/tables.py#L1

[S0765]: https://github.com/openstack/python-watcherclient/blob/4.8.0/setup.cfg#L36

[S0766]: https://github.com/openstack/python-watcherclient/blob/4.8.0/setup.cfg#L66

[S0767]: https://github.com/openstack/python-watcherclient/blob/4.8.0/setup.cfg#L65

[S0768]: https://github.com/openstack/python-watcherclient/blob/4.8.0/setup.cfg#L69

[S0769]: https://github.com/openstack/python-watcherclient/blob/4.8.0/setup.cfg#L68

[S0770]: https://github.com/openstack/python-watcherclient/blob/4.8.0/setup.cfg#L40

[S0771]: https://github.com/openstack/watcher-dashboard/blob/13.0.0/watcher_dashboard/content/strategies/tables.py#L1

[S0772]: https://github.com/openstack/python-watcherclient/blob/4.8.0/setup.cfg#L39

[S0773]: https://github.com/openstack/python-watcherclient/blob/4.8.0/setup.cfg#L41

[S0774]: https://opendev.org/openstack/python-mistralclient/src/tag/5.4.0/setup.cfg#L84

[S0775]: https://github.com/openstack/mistral-dashboard/blob/20.0.0/mistraldashboard/actions/tables.py#L1

[S0776]: https://opendev.org/openstack/python-mistralclient/src/tag/5.4.0/setup.cfg#L87

[S0777]: https://opendev.org/openstack/python-mistralclient/src/tag/5.4.0/setup.cfg#L85

[S0778]: https://opendev.org/openstack/python-mistralclient/src/tag/5.4.0/setup.cfg#L82

[S0779]: https://opendev.org/openstack/python-mistralclient/src/tag/5.4.0/setup.cfg#L83

[S0780]: https://opendev.org/openstack/python-mistralclient/src/tag/5.4.0/setup.cfg#L86

[S0781]: https://opendev.org/openstack/python-mistralclient/src/tag/5.4.0/setup.cfg#L64

[S0782]: https://github.com/openstack/mistral-dashboard/blob/20.0.0/mistraldashboard/action_executions/tables.py#L1

[S0783]: https://opendev.org/openstack/python-mistralclient/src/tag/5.4.0/setup.cfg#L61

[S0784]: https://opendev.org/openstack/python-mistralclient/src/tag/5.4.0/setup.cfg#L59

[S0785]: https://opendev.org/openstack/python-mistralclient/src/tag/5.4.0/setup.cfg#L62

[S0786]: https://opendev.org/openstack/python-mistralclient/src/tag/5.4.0/setup.cfg#L58

[S0787]: https://opendev.org/openstack/python-mistralclient/src/tag/5.4.0/setup.cfg#L60

[S0788]: https://opendev.org/openstack/python-mistralclient/src/tag/5.4.0/setup.cfg#L63

[S0789]: https://opendev.org/openstack/python-mistralclient/src/tag/5.4.0/setup.cfg#L112

[S0790]: https://github.com/openstack/mistral-dashboard/blob/20.0.0/mistraldashboard/dashboard.py#L1

[S0791]: https://opendev.org/openstack/python-mistralclient/src/tag/5.4.0/setup.cfg#L109

[S0792]: https://opendev.org/openstack/python-mistralclient/src/tag/5.4.0/setup.cfg#L110

[S0793]: https://opendev.org/openstack/python-mistralclient/src/tag/5.4.0/setup.cfg#L107

[S0794]: https://opendev.org/openstack/python-mistralclient/src/tag/5.4.0/setup.cfg#L108

[S0795]: https://opendev.org/openstack/python-mistralclient/src/tag/5.4.0/setup.cfg#L111

[S0796]: https://opendev.org/openstack/python-mistralclient/src/tag/5.4.0/setup.cfg#L91

[S0797]: https://github.com/openstack/mistral-dashboard/blob/20.0.0/mistraldashboard/cron_triggers/tables.py#L1

[S0798]: https://opendev.org/openstack/python-mistralclient/src/tag/5.4.0/setup.cfg#L92

[S0799]: https://opendev.org/openstack/python-mistralclient/src/tag/5.4.0/setup.cfg#L89

[S0800]: https://opendev.org/openstack/python-mistralclient/src/tag/5.4.0/setup.cfg#L90

[S0801]: https://opendev.org/openstack/python-mistralclient/src/tag/5.4.0/setup.cfg#L116

[S0802]: https://opendev.org/openstack/python-mistralclient/src/tag/5.4.0/setup.cfg#L117

[S0803]: https://opendev.org/openstack/python-mistralclient/src/tag/5.4.0/setup.cfg#L114

[S0804]: https://opendev.org/openstack/python-mistralclient/src/tag/5.4.0/setup.cfg#L115

[S0805]: https://opendev.org/openstack/python-mistralclient/src/tag/5.4.0/setup.cfg#L118

[S0806]: https://opendev.org/openstack/python-mistralclient/src/tag/5.4.0/setup.cfg#L96

[S0807]: https://opendev.org/openstack/python-mistralclient/src/tag/5.4.0/setup.cfg#L97

[S0808]: https://opendev.org/openstack/python-mistralclient/src/tag/5.4.0/setup.cfg#L94

[S0809]: https://opendev.org/openstack/python-mistralclient/src/tag/5.4.0/setup.cfg#L95

[S0810]: https://opendev.org/openstack/python-mistralclient/src/tag/5.4.0/setup.cfg#L103

[S0811]: https://opendev.org/openstack/python-mistralclient/src/tag/5.4.0/setup.cfg#L104

[S0812]: https://opendev.org/openstack/python-mistralclient/src/tag/5.4.0/setup.cfg#L101

[S0813]: https://opendev.org/openstack/python-mistralclient/src/tag/5.4.0/setup.cfg#L102

[S0814]: https://opendev.org/openstack/python-mistralclient/src/tag/5.4.0/setup.cfg#L105

[S0815]: https://opendev.org/openstack/python-mistralclient/src/tag/5.4.0/setup.cfg#L76

[S0816]: https://github.com/openstack/mistral-dashboard/blob/20.0.0/mistraldashboard/tasks/tables.py#L1

[S0817]: https://opendev.org/openstack/python-mistralclient/src/tag/5.4.0/setup.cfg#L78

[S0818]: https://opendev.org/openstack/python-mistralclient/src/tag/5.4.0/setup.cfg#L80

[S0819]: https://opendev.org/openstack/python-mistralclient/src/tag/5.4.0/setup.cfg#L79

[S0820]: https://opendev.org/openstack/python-mistralclient/src/tag/5.4.0/setup.cfg#L77

[S0821]: https://opendev.org/openstack/python-mistralclient/src/tag/5.4.0/setup.cfg#L38

[S0822]: https://github.com/openstack/mistral-dashboard/blob/20.0.0/mistraldashboard/workbooks/tables.py#L1

[S0823]: https://opendev.org/openstack/python-mistralclient/src/tag/5.4.0/setup.cfg#L41

[S0824]: https://opendev.org/openstack/python-mistralclient/src/tag/5.4.0/setup.cfg#L39

[S0825]: https://opendev.org/openstack/python-mistralclient/src/tag/5.4.0/setup.cfg#L36

[S0826]: https://opendev.org/openstack/python-mistralclient/src/tag/5.4.0/setup.cfg#L37

[S0827]: https://opendev.org/openstack/python-mistralclient/src/tag/5.4.0/setup.cfg#L40

[S0828]: https://opendev.org/openstack/python-mistralclient/src/tag/5.4.0/setup.cfg#L42

[S0829]: https://github.com/openstack/mistral-dashboard/blob/20.0.0/mistraldashboard/workbooks/forms.py#L1

[S0830]: https://opendev.org/openstack/python-mistralclient/src/tag/5.4.0/setup.cfg#L46

[S0831]: https://github.com/openstack/mistral-dashboard/blob/20.0.0/mistraldashboard/workflows/tables.py#L1

[S0832]: https://opendev.org/openstack/python-mistralclient/src/tag/5.4.0/setup.cfg#L49

[S0833]: https://opendev.org/openstack/python-mistralclient/src/tag/5.4.0/setup.cfg#L47

[S0834]: https://opendev.org/openstack/python-mistralclient/src/tag/5.4.0/setup.cfg#L99

[S0835]: https://opendev.org/openstack/python-mistralclient/src/tag/5.4.0/setup.cfg#L52

[S0836]: https://opendev.org/openstack/python-mistralclient/src/tag/5.4.0/setup.cfg#L53

[S0837]: https://opendev.org/openstack/python-mistralclient/src/tag/5.4.0/setup.cfg#L55

[S0838]: https://opendev.org/openstack/python-mistralclient/src/tag/5.4.0/setup.cfg#L56

[S0839]: https://opendev.org/openstack/python-mistralclient/src/tag/5.4.0/setup.cfg#L54

[S0840]: https://opendev.org/openstack/python-mistralclient/src/tag/5.4.0/setup.cfg#L66

[S0841]: https://github.com/openstack/mistral-dashboard/blob/20.0.0/mistraldashboard/executions/tables.py#L1

[S0842]: https://opendev.org/openstack/python-mistralclient/src/tag/5.4.0/setup.cfg#L67

[S0843]: https://opendev.org/openstack/python-mistralclient/src/tag/5.4.0/setup.cfg#L71

[S0844]: https://opendev.org/openstack/python-mistralclient/src/tag/5.4.0/setup.cfg#L69

[S0845]: https://opendev.org/openstack/python-mistralclient/src/tag/5.4.0/setup.cfg#L72

[S0846]: https://opendev.org/openstack/python-mistralclient/src/tag/5.4.0/setup.cfg#L74

[S0847]: https://opendev.org/openstack/python-mistralclient/src/tag/5.4.0/setup.cfg#L73

[S0848]: https://opendev.org/openstack/python-mistralclient/src/tag/5.4.0/setup.cfg#L70

[S0849]: https://opendev.org/openstack/python-mistralclient/src/tag/5.4.0/setup.cfg#L68

[S0850]: https://opendev.org/openstack/python-mistralclient/src/tag/5.4.0/setup.cfg#L44

[S0851]: https://opendev.org/openstack/python-mistralclient/src/tag/5.4.0/setup.cfg#L45

[S0852]: https://opendev.org/openstack/python-mistralclient/src/tag/5.4.0/setup.cfg#L48

[S0853]: https://opendev.org/openstack/python-mistralclient/src/tag/5.4.0/setup.cfg#L50

[S0854]: https://github.com/openstack/mistral-dashboard/blob/20.0.0/mistraldashboard/workflows/forms.py#L1

[S0855]: https://opendev.org/openstack/python-heatclient/src/tag/4.1.0/setup.cfg#L40

[S0856]: https://github.com/openstack/heat-dashboard/blob/13.0.0/heat_dashboard/content/stacks/tables.py#L1

[S0857]: https://opendev.org/openstack/python-heatclient/src/tag/4.1.0/setup.cfg#L45

[S0858]: https://github.com/openstack/heat-dashboard/blob/13.0.0/heat_dashboard/content/resource_types/views.py#L1

[S0859]: https://opendev.org/openstack/python-heatclient/src/tag/4.1.0/setup.cfg#L46

[S0860]: https://opendev.org/openstack/python-heatclient/src/tag/4.1.0/setup.cfg#L41

[S0861]: https://opendev.org/openstack/python-heatclient/src/tag/4.1.0/setup.cfg#L42

[S0862]: https://github.com/openstack/heat-dashboard/blob/13.0.0/heat_dashboard/content/template_versions/views.py#L1

[S0863]: https://opendev.org/openstack/python-heatclient/src/tag/4.1.0/setup.cfg#L43

[S0864]: https://github.com/openstack/heat-dashboard/blob/13.0.0/heat_dashboard/content/stacks/forms.py#L1

[S0865]: https://opendev.org/openstack/python-heatclient/src/tag/4.1.0/setup.cfg#L44

[S0866]: https://opendev.org/openstack/python-heatclient/src/tag/4.1.0/setup.cfg#L47

[S0867]: https://opendev.org/openstack/python-heatclient/src/tag/4.1.0/setup.cfg#L48

[S0868]: https://opendev.org/openstack/python-heatclient/src/tag/4.1.0/setup.cfg#L49

[S0869]: https://opendev.org/openstack/python-heatclient/src/tag/4.1.0/setup.cfg#L50

[S0870]: https://opendev.org/openstack/python-heatclient/src/tag/4.1.0/setup.cfg#L51

[S0871]: https://opendev.org/openstack/python-heatclient/src/tag/4.1.0/setup.cfg#L52

[S0872]: https://opendev.org/openstack/python-heatclient/src/tag/4.1.0/setup.cfg#L53

[S0873]: https://opendev.org/openstack/python-heatclient/src/tag/4.1.0/setup.cfg#L54

[S0874]: https://opendev.org/openstack/python-heatclient/src/tag/4.1.0/setup.cfg#L55

[S0875]: https://opendev.org/openstack/python-heatclient/src/tag/4.1.0/setup.cfg#L56

[S0876]: https://opendev.org/openstack/python-heatclient/src/tag/4.1.0/setup.cfg#L57

[S0877]: https://opendev.org/openstack/python-heatclient/src/tag/4.1.0/setup.cfg#L59

[S0878]: https://opendev.org/openstack/python-heatclient/src/tag/4.1.0/setup.cfg#L60

[S0879]: https://opendev.org/openstack/python-heatclient/src/tag/4.1.0/setup.cfg#L61

[S0880]: https://opendev.org/openstack/python-heatclient/src/tag/4.1.0/setup.cfg#L62

[S0881]: https://opendev.org/openstack/python-heatclient/src/tag/4.1.0/setup.cfg#L63

[S0882]: https://opendev.org/openstack/python-heatclient/src/tag/4.1.0/setup.cfg#L66

[S0883]: https://opendev.org/openstack/python-heatclient/src/tag/4.1.0/setup.cfg#L64

[S0884]: https://opendev.org/openstack/python-heatclient/src/tag/4.1.0/setup.cfg#L65

[S0885]: https://opendev.org/openstack/python-heatclient/src/tag/4.1.0/setup.cfg#L58

[S0886]: https://opendev.org/openstack/python-heatclient/src/tag/4.1.0/setup.cfg#L67

[S0887]: https://opendev.org/openstack/python-heatclient/src/tag/4.1.0/setup.cfg#L68

[S0888]: https://opendev.org/openstack/python-heatclient/src/tag/4.1.0/setup.cfg#L69

[S0889]: https://opendev.org/openstack/python-heatclient/src/tag/4.1.0/setup.cfg#L70

[S0890]: https://opendev.org/openstack/python-heatclient/src/tag/4.1.0/setup.cfg#L71

[S0891]: https://opendev.org/openstack/python-heatclient/src/tag/4.1.0/setup.cfg#L72

[S0892]: https://opendev.org/openstack/python-heatclient/src/tag/4.1.0/setup.cfg#L73

[S0893]: https://opendev.org/openstack/python-heatclient/src/tag/4.1.0/setup.cfg#L74

[S0894]: https://opendev.org/openstack/python-heatclient/src/tag/4.1.0/setup.cfg#L75

[S0895]: https://opendev.org/openstack/python-heatclient/src/tag/4.1.0/setup.cfg#L76

[S0896]: https://opendev.org/openstack/python-heatclient/src/tag/4.1.0/setup.cfg#L77

[S0897]: https://opendev.org/openstack/python-heatclient/src/tag/4.1.0/setup.cfg#L78

[S0898]: https://opendev.org/openstack/python-heatclient/src/tag/4.1.0/setup.cfg#L79

[S0899]: https://opendev.org/openstack/python-heatclient/src/tag/4.1.0/setup.cfg#L80

[S0900]: https://opendev.org/openstack/python-heatclient/src/tag/4.1.0/setup.cfg#L81

[S0901]: https://opendev.org/openstack/python-heatclient/src/tag/4.1.0/setup.cfg#L82

[S0902]: https://opendev.org/openstack/python-heatclient/src/tag/4.1.0/setup.cfg#L83

[S0903]: https://opendev.org/openstack/python-heatclient/src/tag/4.1.0/setup.cfg#L84

[S0904]: https://opendev.org/openstack/python-heatclient/src/tag/4.1.0/setup.cfg#L85

[S0905]: https://opendev.org/openstack/python-heatclient/src/tag/4.1.0/setup.cfg#L86

[S0906]: https://opendev.org/openstack/python-heatclient/src/tag/4.1.0/setup.cfg#L87

[S0907]: https://opendev.org/openstack/python-heatclient/src/tag/4.1.0/setup.cfg#L88

[S0908]: https://github.com/openstack/python-ironicclient/blob/5.10.0/setup.cfg

[S0909]: https://github.com/openstack/ironic-ui/blob/6.5.0/ironic_ui/api/ironic_rest_api.py#L1

[S0910]: https://github.com/openstack/ironic-ui/blob/6.5.0/ironic_ui/static/dashboard/admin/ironic/node-state-transition.service.js#L1
