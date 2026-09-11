# PowerOps: два реальных сценария, Python 3.11

`stand_test.py` — самостоятельный сценарный runner для Masakari, Mistral,
Ironic и Nova. Он выполняет реальные операции через API и Ansible, сохраняет
журнал и выдаёт JSON-отчёт. Rally устанавливать не требуется; совместимость
с его форматом заданий не заявляется.

Пошагово, начиная с получения ветки: **[установка и запуск](INSTALL_AND_RUN.md)**.

**Возврат хоста автоматический в обоих сценариях.** После фактического `PAUSED`
тест проверяет source и передаёт в тот же Mistral execution:

```json
{"state":"RUNNING","params":{"env":{"stale_domains_checked":true}}}
```

Это Boolean `true`. Ручного ввода подтверждения в середине теста нет.
Если остались старые libvirt-домены, тест не подтверждает возврат и не удаляет их.

## Что проверяется

| Этап | Аварийная эвакуация — `emergency` | Плановое выключение — `planned` |
|---|---|---|
| Подготовка | Source включён, Nova `enabled/up`, Masakari вне maintenance; только явно перечисленные ACTIVE ВМ и их libvirt-домены | То же |
| Воздействие | Ansible/systemd отключает указанный интерфейс на `duration`, по умолчанию 300 секунд | Mistral `power_ops.planned_power_off`, `instance_policy=live_migrate`, `allow_hard_off=false` |
| Перенос | Настоящее новое уведомление Masakari COMPUTE_HOST/STOPPED, recovery finished, успешный VMove каждой ВМ | Workflow SUCCESS, отдельная новая завершённая Nova live migration каждой ВМ |
| Питание | Ironic power off, Nova disabled/down; подтверждён порядок fencing → Nova down → начало эвакуации | Ironic power off, Nova disabled, Masakari maintenance; workflow не остановил ВМ вместо миграции |
| Возврат | Mistral `power_ops.power_on_and_return` | Тот же workflow |
| Автоподтверждение | Реальный PAUSED, power-on task SUCCESS; source disabled/up и maintenance; сеть восстановлена, старых доменов нет | То же |
| Финал | Source power on, новый boot ID, Nova enabled/up, maintenance снят; ВМ остались на проверенных destination | То же |

Перед подтверждением сверяются machine ID, имя/MAC интерфейса, административный
UP и наличие исходных адресов. Source пуст по Nova и `virsh list --all --uuid`.
Положение каждой ВМ сверяется с её VMove/migration и сохраняется до конца возврата.

Возврат compute **не мигрирует ВМ обратно**. Следующая итерация требует подходящего
исходного размещения. Например, второй сценарий можно отдельно настроить на
compute, куда ВМ переехали, указав его UUID и inventory alias. Тест не создаёт
и не удаляет ВМ, сети, сегменты или Ironic nodes.

## Вход и учётные данные

- **Task JSON:** сценарий, Nova host, UUID Ironic node/Masakari segment/host,
  UUID существующих тестовых ВМ, допустимые destination и libvirt backend.
- **Inventory обязателен:** файл Ansible INI/YAML; `inventory_host` выбирает ровно
  один inventory hostname. По умолчанию он совпадает с `host`.
- **Globals необязателен:** Ansible получает `-e @globals.yml` с обычным разрешением
  Jinja/Vault. Интерфейс задаётся явно либо через `interface_var`:
  `network_interface`, `tunnel_interface`, `storage_interface`.
- **OpenStack:** `clouds.yaml` (`cloud`/`region_name` в task) либо `OS_*` из RC.
  Нужны права чтения всех проектов, host-атрибутов и migrations Nova, recovery/VMove
  Masakari, состояния Ironic и запуска/продолжения Mistral.
- **SSH/become:** стандартные inventory variables, ключи, agent или Ansible Vault.
  `vault_password_file` — путь к файлу/скрипту для Ansible. Неизвестный SSH host key
  автоматически не принимается.
- **BMC-пароли тесту не передаются:** питание выполняют штатные PowerOps/Masakari
  через Ironic с уже настроенными BMC credentials.

Пароли/токены не помещаются в task JSON или аргументы CLI. В журнале нет дампа
inventory/globals, токенов или Ironic driver_info. Ansible работает с `no_log`;
временные входы и отчёты закрыты правами 0600/0700.

В [planned.json](examples/planned.json) и [emergency.json](examples/emergency.json)
замените все host/UUID/пути на значения стенда. Пути JSON разрешаются относительно
его каталога. Для `libvirt.backend` доступны `host`, `docker`, `podman`; контейнер
требует явного `container`, например `nova_libvirt`.

## Установка и запуск

Команды выполняются из корня репозитория на отдельной операторской машине,
которая останется доступна при отказе выбранного compute.

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install -r tools/stand-tests/requirements.txt 'ansible-core==2.18.2'
```

Нужен `ansible-playbook` в PATH (локально проверен ansible-core 2.18.2).
На compute нужны Linux, Python 3.11+, iproute2, systemd и доступ к libvirt.
`become` по умолчанию true; для входа под root можно задать false.

Сначала скопируйте и заполните пример task. Локальный план:

```bash
.venv/bin/python tools/stand-tests/stand_test.py plan --task /absolute/path/emergency.json --run-id ha-001 --host compute-01 --interface eno2 --duration 300
```

Проверка исходного стенда без запуска сценария:

```bash
.venv/bin/python tools/stand-tests/stand_test.py preflight --task /absolute/path/emergency.json --run-id ha-001 --host compute-01 --interface eno2 --duration 300
```

**Следующая команда выполняет реальный отказ, эвакуацию, питание и возврат
с автоматическим подтверждением оператора:**

```bash
.venv/bin/python tools/stand-tests/stand_test.py run --task /absolute/path/emergency.json --run-id ha-001 --host compute-01 --interface eno2 --duration 300 --execute
```

Для планового сценария используйте заполненный planned.json и другой run-id.
`--inventory` и `--globals` переопределяют пути из task; относительные CLI-пути
разрешаются от текущего каталога. `run` без `--execute` действует как локальный
plan, без Ansible/API. `duration`: 1–3600 секунд, по умолчанию 300. `timeout` в JSON:
30–14400 секунд на этап (1800); `poll_interval`: 1–30 секунд (5).

Сохранённый отчёт без обращения к стенду:

```bash
.venv/bin/python tools/stand-tests/stand_test.py report --run-id ha-001
```

`status` также читает сохранённый отчёт. Для продолжения INCOMPLETE повторите
исходный `run --execute` с теми же параметрами и `--state-dir`.

## Повторяемость и восстановление runner

Журнал `artifacts/stand-tests/<run-id>.json` привязывает запуск к task,
контрольным суммам inventory/globals, Keystone project/user и endpoint-адресам.
Он содержит исходные состояния, ID операций, наблюдения, проверку source
и итоговое размещение ВМ. Запись — atomic rename + fsync, права 0600/0700.
Нужна постоянная локальная файловая система с flock; NFS не поддерживается.

Намерение и UUID Mistral execution записываются **до POST**. При потере ответа
наблюдается только этот UUID с проверкой workflow/input/description. POST не
повторяется. Потерянный resume не вызывает повторный PUT. Если процесс остановился
между записью намерения и отправкой, возможен INCOMPLETE без фактического действия:
требуется разбор сохранённого ID.

Сетевой fault дополнительно связан с уникальным nonce, сохранённым в локальном
намерении и удалённом request. Старый run-id не даёт зачесть прежнее отключение,
даже при потерянном ответе. Для отдельного `link_fault.py status/restore` такого
fault передайте `--intent-nonce` из поля `operations.fault.nonce` отчёта.

Сроки ожидания сохраняются и повторным запуском не продлеваются. PASS/FAIL для того
же ID возвращают исторический результат без нового воздействия. INCOMPLETE можно
продолжить в пределах прежних сроков. Незавершённый прогон с mutation intent
удерживает source в общем state-dir. Распределённого lock между операторскими
машинами нет. Стенд на время опыта должен быть выделен для теста; параллельные
HA/DRS/manual операции нарушают однозначную атрибуцию событий.

При неудаче нет безусловного power-on, enable-service или удаления stale domains
в finally. Source может остаться выключенным либо на PAUSED в maintenance — это
видно в журнале. Разбор и восстановление выполняются по текущим API-состояниям
и ID. Удаление журнала не является способом повторить тест.

## Что означает «300 секунд» при настоящем HA

Worker регистрирует systemd ExecStopPost до DOWN, подтверждает административный
DOWN и отсчитывает duration по CLOCK_BOOTTIME. По окончании он пытается вернуть
UP. Отдельный CLI сетевого адаптера описан в [LINK_FAULT.md](LINK_FAULT.md).

Fencing может прервать worker отключением питания раньше окончания таймера.
Точные 300 секунд непрерывного Linux DOWN при этом гарантировать нельзя. Runner
консервативно выдерживает **ещё duration секунд после наблюдения завершённого
recovery и выключенного source**, затем запускает power-on. Часы compute и runner
не смешиваются. Общая длительность опыта может существенно превышать пять минут.

Это ожидание измеряется монотонными часами. После restart runner, если намерение
return ещё не было сохранено, полный интервал выдерживается заново; перевод
системных часов не сокращает его.

После загрузки проверяются записанный down_confirmed_at, новый boot, та же
машина/MAC/интерфейс и текущий UP. Старый fault-журнал закрывается без изменения
сети нового boot. В отчёте различаются штатный COMPLETED и прерванный fencing
INTERRUPTED_BY_REBOOT.

## Результат и границы доказательства

| Статус | Exit code | Смысл |
|---|---|---|
| PLAN / PREFLIGHT | 0 | План либо проверка исходного состояния; сценарий не выполнен |
| PASS | 0 | Все критерии выбранного сценария, включая возврат, подтверждены |
| FAIL | 2 | Наблюдалось нарушение критерия; автоматического повторного запуска нет |
| INCOMPLETE | 3 | Недостаточно данных, истёк срок или неопределён результат запроса |

Emergency требует Masakari API **1.3**, сохранённых TaskFlow recovery details
и post-fence Nova-down hotfix активного baseline 0809. Используются timestamped
сообщения IronicFenceTask и VMove.start_time, а не порядок элементов массива.
Global Nova migration history читается с API **2.59** через `/os-migrations`.

Один выключенный интерфейс не обязательно вызовет host failure: результат зависит
от bond/VLAN, роли сети, резервирования и матрицы мониторинга. Тест не подделывает
уведомление, если настоящее событие не случилось. BMC/control plane и ёмкость
назначений должны оставаться доступными для штатного recovery.

PASS подтверждает наблюдения API и локального source. Он не доказывает непрерывный
carrier/L3 outage, доступность гостевых приложений, отсутствие потери данных или
физическую временную отметку отключения BMC. Эти пробы не входят в первую версию.
Доступность ВМ оценивается как Nova ACTIVE с пустым task_state.

## Проверка реализации

```bash
python3.11 -m unittest discover -s tools/stand-tests/tests -v
python3.11 -m unittest discover -s tests -v
```

Локально проверены state machine, реальные файловые журналы, потеря ответов,
ошибка отдельной ВМ, порядок fencing, stale domains, дрейф source, таймауты,
пагинация и CLI. Два теста используют настоящий Ansible с локальными фиктивными
inventory/globals; Linux/systemd/OpenStack заменены тестовыми адаптерами.
SDK 4.20.0 проверен под Python 3.11.15. **На стенде сценарии пока не запускались.**
Итоговый локальный прогон: **75/75 тестов инструмента без пропусков и 7/7 тестов
репозитория**; независимое ревью не выявило оставшихся P1/P2 в проверенном scope.

Для проверки настоящего HTTP session-кода SDK без сетевых запросов:

```bash
.venv/bin/python -m unittest discover -s tools/stand-tests/tests -v
```

В окружении без SDK один такой тест пропускается. Ansible fixture-тесты также
пропускаются, если ansible-playbook отсутствует.
