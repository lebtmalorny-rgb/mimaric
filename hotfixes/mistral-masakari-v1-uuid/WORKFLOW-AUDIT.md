# Проверка других workflow PowerOps

Дата: 2026-09-05. Итог: Mistral `7be711a1df54655fed9cfdaca66516023536558a`.
Проверка локальная; стенд и BMC не вызывались.

## Результат

Три ранее воспроизведённых дефекта исправлены отдельными патчами 0003–0005.
Первые два патча API v1/UUID и сообщений ошибок сохранены.
Это не утверждение о готовности всего стенда: runtime-условия и ограничения ниже.

## Исправленные риски

### 1. Разные права на workflow API и action — 0003

До исправления API использовал `mistral/services/powerops.py:authorize`,
а `mistral/actions/powerops/base.py:_authorize` проверял только имена.
Admin вне allowlists отклонялся action; allowlisted member мог пройти
проверку action, в том числе с hard-off, несмотря на отказ workflow API.

Теперь action вызывает общую policy до coordination/OpenStack.
Admin не зависит от allowlists; оператору нужны `powerops_operator` и
обе точные allowlists; hard-off разрешён только admin.
Отсутствующие/невалидные роли отклоняются. Прямой action также защищён.

Тесты: `test_authorization.py`, существующие API/service policy tests.
Проверены все пять классов PowerOps actions. Роли должны приходить в
доверенном SecurityContext, а не из workflow input.
Прямая политика `action_executions:create` не изменена: проверка действует
внутри самого action.

### 2. Чужая ВМ в restart manifest — 0004

До исправления `clients.py:start_instances(instance_ids)` искал UUID во всех
проектах, но не связывал их с заблокированным compute host.
В полном ReturnToServiceAction тесте запускалась SHUTOFF ВМ с compute-02,
после чего включался compute-01.

Теперь `start_instances(host, instance_ids)` проверяет весь список до
первого запуска. Перед обработкой каждой ВМ повторно читает UUID/compute_host
и допустимое состояние; при ожидании старта проверяет UUID/compute_host.
Оба вызывающих action — PlannedRebootAction и ReturnToServiceAction —
передают `self.host`. Неверный/отсутствующий host, смена UUID/host,
небезопасное состояние и malformed manifest дают отказ.

Сортировка, последовательный start → ожидание → pacing сохранены.
Полный тест отказа ReturnToServiceAction оставляет Nova disabled и
maintenance=true, не запускает чужую ВМ.
Проверен также реальный SDK с полностью перехваченным HTTP.

Ограничение: GET/check/start не является атомарной транзакцией Nova.
Внешний администратор или другая система могут менять ВМ вне PowerOps lock.
Патч не обещает устранить все такие гонки.

### 3. Ошибка первой записи maintenance пропускает fail-safe — 0005

До исправления `_nova_disabled=True` выставлялся только после
`set_masakari_maintenance(True)`. PUT мог примениться, а GET/read-back —
упасть; тогда Nova оставалась enabled без попытки защитного disable.

Флаг переименован в `_fail_safe_required` и включается после успешного
`resolve_host_set`, перед попыткой maintenance update.
Изменены PlannedPowerOffAction, PlannedRebootAction и
PowerOnForInspectionAction. В ReturnToServiceAction только переименован флаг.

`test_transition_safety.py` выполняет настоящие actions и CloudClients
с внешними test doubles:
PUT failed before/after apply; PUT applied/GET failed; исходная ошибка
сохраняется; protective disable выполняется внутри той же host lock.
Команд питания после этих сбоев нет.

Ошибка разрешения хоста до перехода не запускает мутации.
При потере coordination последующие записи запрещены, даже для fail-safe.
Поэтому при утрате блокировки либо недоступности Masakari/Nova восстановление
состояния не гарантируется: патч исправляет пропуск попытки, а не делает
распределённую операцию безусловно успешной.

## Проверки

- 130 тестов PowerOps: actions, clients, coordination, workbook,
  регистрация, исключения.
- 21 тест API/service policy.
- 6 тестов реального SDK с перехваченным HTTP: Nova disable/enable,
  stop/start, live migration/source empty, require_empty rejection,
  Ironic soft-off/on, отказ запуска ВМ с другого хоста.
- Четыре probes в `verify_workflow_safety.py` требуют безопасного поведения.
  Они заменили прежний `reproduce_workflow_risks.py`, который утверждал
  наличие багов и больше не подходит для итоговой версии.
- Новые regression tests сначала воспроизвели дефекты.
- Независимое ревью каждой из трёх новых правок: замечаний нет.
- Наложение всех пяти патчей на чистую базу `ce804184`, обратная проверка
  и побайтное совпадение 13 изменённых файлов с итоговым commit.
- `flake8` изменённых исходников/тестов и `git diff --check` пройдены.
- Пустой `msg=''` для собственных PowerOpsError исправлен патчем 0002;
  произвольные сторонние исключения не изменены глобально.

## Межрепозиторная проверка: 16/19

Общий файл `tests/test_cross_repository_contract.py` родительского delivery
repo содержит структурные assertions на прежнюю реализацию:

1. `test_enabled_powerops_coordination_is_etcd_and_not_redis`, строка 812:
   ожидает Jinja if-block, а шаблон Kolla уже использует conditional expression.
   Тот же сбой ранее воспроизведён с Mistral до всей hotfix-серии.
2. `test_privileged_actions_require_both_exact_allowlists`, строка 677:
   ожидает inline `if` внутри action и deny-all при пустых списках.
   Теперь вызван общий authorize с уже принятой policy admin/operator.
3. `test_planned_vm_operations_are_deterministic_serial_and_paced`,
   строка 1630: считает два цикла selected ошибкой; первый теперь валидирует
   весь manifest, только второй запускает ВМ. Далее тест также ожидает inline
   проверку ACTIVE, вынесенную в проверку наблюдения UUID/host.

Это не 19 зелёных тестов. Сам файл и Kolla не менялись в Mistral-патчах.
Поведение авторизации, отказов, сортировки/последовательности/pacing проверено
исполняемыми Mistral-тестами; структурный контракт delivery repo нужно
актуализировать отдельно при интеграции серии.

## Что остаётся за границами патчей

- Boolean `stale_domains_checked=True` — утверждение авторизованного
  оператора, а не серверное доказательство прохождения pause/resume.
  ReturnToServiceAction всё ещё не проверяет trusted resume context.
  Доказуемый operator gate требует отдельного согласованного контракта;
  полная engine pause/resume приёмка не выполнялась.
- Host status не проверяет etcd. Изменяющие actions требуют coordination URL,
  heartbeat и подтверждённого владения блокировкой.
- Возврат требует stable power-on, Nova disabled/up и maintenance=true.
  power_on_for_inspection и return_to_service — actions внутри
  power_on_and_return, не отдельные workflow поставляемого YAML.
- Для современных Nova проверен microversion discovery. При API <2.53
  SDK 4.10.0 выбирает legacy service update, где текущие вызовы не передают
  host/binary. Проверить реальные discovery/ограничения; не менять вслепую.
- Нужны реальные проверки TLS/RBAC служебного пользователя, видимости ресурсов
  всех проектов, состава библиотек, BMC/Redfish, таймаутов, migration ресурсов.
  Пустой список admin CLI не доказывает видимость из executor.
- При недоступном API/потере lock fail-safe не гарантирует конечный disabled.
  Нельзя автоматически повторять опасный workflow после 504 без выяснения,
  был ли создан execution и в каком он состоянии.

Сборка образов, reconfigure, рестарты и реальные power operations не выполнялись.
Публикация этой серии передаёт оператору патчи для самостоятельной сборки.
