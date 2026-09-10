# Host firewall: implementation plan первого этапа

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:executing-plans` for inline execution, or
> `superpowers:subagent-driven-development` if that execution mode is selected.
> Execute tasks in order; steps use checkbox syntax for tracking.

**Goal:** Поставить запускаемый в Kolla-Ansible `0809` отдельный playbook,
который собирает сетевое состояние и формирует предварительную матрицу
и отчёт о непокрытых зависимостях, не меняя firewall.

**Architecture:** Поставка — добавочные файлы в дерево `ansible/` Kolla-Ansible.
Controller-side action plugin выбирает только необходимые переменные и строит
модель, remote module выполняет фиксированные read-only проверки. Отдельный
playbook сохраняет приватный отчёт на controller; режим применения запрещён.

**Tech Stack:** ansible-core 2.18, Python 3.11 на целевой базе, стандартная
библиотека Python, YAML/Jinja, unittest. На первом этапе новые Galaxy collections
и Python runtime-зависимости не добавляются.

**Spec:** [ADR-0002](../adr/0002-host-firewall.md).

## Global Constraints

- «SSH сохраняется обязательно.»
- «Применение разрешается только отдельным явным действием.»
- «Playbook не выполняет общий сброс правил и не переписывает принадлежащие
  Neutron, OVS/OVN и контейнерному движку цепочки, NAT или Security Groups.»
- «Неизвестный сервис нельзя молча пропустить или автоматически открыть для
  него произвольный доступ.»
- «Конкретные IP, порты, backend firewall и названия новых globals здесь
  намеренно не задаются.» Это граница ADR: первый этап не выбирает backend
  применения; его собственные параметры ниже относятся только к отчёту.
- «В текущей работе проверяется только документ.» Это статус исходного ADR;
  обновлять его лишь с указанием реально проверенного этапа реализации.
- На стенде ничего не запускать. Не менять исходные архивы, FRR-документ,
  существующие payload-файлы, сетевые настройки и bootstrap.
- Не начинать разработку на `main`; согласовать отдельную рабочую ветку/копию.

## Граница поставки и последующие этапы

Этот план реализует только обследование и предварительную матрицу. В отчёте
всегда `apply_ready: false` и блокировка `APPLY_NOT_IMPLEMENTED`. Наличие
API-потоков не обозначается как полное покрытие сервиса.

После него отдельными планами выполняются:

1. Полный каталог потоков для выбранных драйверов и режимов, включая Consul,
   Nova/Neutron, хранилища, внешние зависимости и административную политику.
2. Согласованный backend, управляемая область правил, независимый откат,
   явный apply и проверка новых соединений; тесты в изолированной среде.
3. Допуск к стендовому прогону только по отдельному разрешению оператора.

Это не пропущенные части первого этапа и не разрешение включить default-deny
после получения первого отчёта.

## Размещение файлов

Корень добавки: `integrations/kolla-ansible/host-firewall/`.
Его подкаталог `ansible/` накладывается на одноимённый каталог Kolla-Ansible;
существующие файлы исходной базы не заменяются.

| Файл относительно корня добавки | Назначение |
| --- | --- |
| `ansible/host-firewall.yml` | Отдельная точка запуска; report-only gate до удалённых проверок |
| `ansible/action_plugins/powerops_firewall_model.py` | Безопасная проекция переменных controller |
| `ansible/module_utils/powerops_firewall_model.py` | Чистые функции валидации, матрицы и отчёта |
| `ansible/module_utils/powerops_firewall_probe.py` | Ограниченный запуск фиксированных read-only команд |
| `ansible/library/powerops_firewall_probe.py` | Тонкий Ansible module с `changed=false` |
| `ansible/roles/host-firewall/defaults/main.yml` | Только параметры обследования |
| `ansible/roles/host-firewall/tasks/main.yml` | Сбор и передача результатов, в том числе ошибок |
| `ansible/roles/host-firewall/templates/report.md.j2` | Читаемый итог с явными ограничениями |
| `ansible/roles/host-firewall/vars/catalog.yml` | Версионированный начальный каталог предварительных потоков |
| `tests/test_model.py` | Входные данные, полнота и fail-closed семантика |
| `tests/test_probe.py` | Ограничения процессов, ошибки, размеры вывода |
| `tests/test_playbook.py` | Реальный локальный запуск Ansible и изолированные fixtures |
| `README.md` | Размещение, запуск, формат отчёта, ограничения |

## Task 1: модель отчёта и запрет ложной готовности

**Files:** `ansible/module_utils/powerops_firewall_model.py`,
`tests/test_model.py`.

**Interfaces:**

```python
def build_report(host: str, model: dict, catalog: dict, observation: dict) -> dict:
    """Pure function; no filesystem, subprocess, network or Ansible calls."""
```

Вход `model`: `enabled_flags`, `groups`, `network_addresses`, `ports`,
`ssh_port`, `unresolved_names`. Значения уже вычислены Ansible; модель не
интерпретирует Jinja или Python. `groups` содержит имена групп и хостов,
`network_addresses` — только нормализованные IP по сетям.

Выход: `schema_version`, `host`, `enabled_flags`, `candidate_flows`,
`blockers`, `observations`, `apply_ready`. Блокировка — словарь с `code` и
несекретным контекстом: именем флага, группы или проверки.

- [ ] **Step 1: написать отрицательные тесты.** Удаление постоянного запрета
  apply, пропуск неизвестного сервиса или подмена invalid port на default
  должны ломать тесты. Использовать литеральные ожидания:

  ```python
  model = {
      'enabled_flags': {'enable_unknown_service': True},
      'groups': {}, 'network_addresses': {}, 'ports': {},
      'ssh_port': 2222, 'unresolved_names': [],
  }
  report = build_report('node-a', model, {'services': {}}, {})
  assert report['apply_ready'] is False
  assert 'UNKNOWN_ENABLED_FLAG' in {b['code'] for b in report['blockers']}
  assert 'APPLY_NOT_IMPLEMENTED' in {b['code'] for b in report['blockers']}
  ```

  Отдельные случаи: строка `false` не принимается как true; неизвестная
  булева строка остаётся ошибкой; порт вне `1..65535`; нет IP нужной сети;
  нет группы; IPv6; partial/truncated observation; выключенный сервис.
- [ ] **Step 2: запустить `python3 -m unittest discover -s tests -p test_model.py -v`.**
  Подтвердить, что отсутствие реализации проявляется в проверяемом контракте.
- [ ] **Step 3: реализовать функцию.** Нормализовать только документированные
  поля, отвергать неоднозначность, сортировать результат детерминированно.
  Не создавать разрешения с source `any` при нехватке данных.
- [ ] **Step 4: повторить тесты.** Добавить тест, что пароль или полный словарь
  hostvars, переданный в лишнем поле, не попадает в результат.
- [ ] **Step 5: сохранить только файлы задачи отдельным коммитом.**

## Task 2: read-only обследование с ограничениями

**Files:** `ansible/module_utils/powerops_firewall_probe.py`,
`ansible/library/powerops_firewall_probe.py`, `tests/test_probe.py`.

**Interfaces:**

```python
def collect_snapshot(timeout: int = 10, max_bytes: int = 262144) -> dict:
    """Return timestamp and named command results; never change firewall."""
```

Каждый результат: `argv`, `rc`, `stdout`, `stderr`, `timed_out`,
`truncated`, `available`. Отсутствие команды отличается от пустого ruleset.
Linux-only module: `supports_check_mode=True`, итог `changed=False`.

Фиксированные проверки: адреса и маршруты IPv4/IPv6 через `ip -j`,
слушающие TCP/UDP через `ss`, активные и постоянные zones/policies firewalld,
`nft -j list ruleset`, `iptables-save`, `ip6tables-save`, состояние служб
firewall и bridge-netfilter sysctl. Никаких аргументов-команд от пользователя,
`shell=True`, reload, flush, смены policy или запуска сервиса.

- [ ] **Step 1: написать тесты с маленькими исполняемыми fixtures во временном
  каталоге.** Проверить успешный вывод, ненулевой rc, отсутствие бинарника,
  зависший процесс и вывод сверх лимита. Пример ожидаемого результата:

  ```python
  result = collect_snapshot(timeout=1, max_bytes=128)
  assert result['commands']['nft']['truncated'] is True
  assert len(result['commands']['nft']['stdout'].encode()) <= 128
  ```

  Fixtures используют перехват поиска бинарников только в тестовой среде;
  реальные firewall-команды тестами не вызываются.
- [ ] **Step 2: выполнить `python3 -m unittest discover -s tests -p test_probe.py -v`.**
  Проверить падения до реализации.
- [ ] **Step 3: реализовать bounded subprocess runner и module adapter.**
  Ограничивать и время, и удерживаемый объём данных; не применять `capture_output`
  без ограничения памяти. Завершать только созданную runner группу процессов.
  Недостаток прав сохранять как результат проверки, не как «firewall выключен».
- [ ] **Step 4: повторить тесты с общим timeout тестового запуска.**
  Проверить отсутствие оставленных дочерних процессов после timeout.
- [ ] **Step 5: отдельный коммит файлов задачи.**

## Task 3: проекция Kolla и предварительный каталог

**Files:** `ansible/action_plugins/powerops_firewall_model.py`,
`ansible/roles/host-firewall/vars/catalog.yml`, `tests/test_model.py`,
`tests/test_playbook.py`.

**Interfaces:** action `powerops_firewall_model` возвращает `model` для
`build_report`. Каталог имеет `schema_version`, `services`; каждая запись
содержит `enable_flag`, `coverage: partial`, `source_evidence` и `flows`.
Поток содержит `id`, `protocol`, `port_var`, `destination_group`, `network`,
`source_groups` либо `requires_operator_sources: true`.

- [ ] **Step 1: написать реальные Ansible fixtures.** Проверить приоритет
  inventory/globals/extra-vars, Jinja-значения, неопределённую переменную,
  выключенный сервис, неизвестный `enable_*`, секрет в несвязанной переменной.
  Например, extra-vars с `mistral_api_listen_port=18989` должны дать в отчёте
  `18989`, а не default `8989`; секрет не должен появиться в stdout и артефакте.
- [ ] **Step 2: выполнить профиль тестов Task 3 и увидеть падение.**
- [ ] **Step 3: реализовать action projection.** Вычислять значения только
  отдельных ключей; не сериализовать `vars`, `hostvars` или service dictionaries
  целиком. Ошибка шаблонизации выводит имя ключа, а не потенциально секретный
  текст выражения. Не подменять переменные inventory поздним `include_vars`
  базового `all.yml`.
- [ ] **Step 4: добавить исходно подтверждённые backend API-потоки Keystone,
  Mistral, Masakari и Ironic от группы loadbalancer.** Порт брать из соответствующей
  listen-переменной, а не из внешнего frontend порта. Это partial coverage:
  БД, RPC, внешние клиенты и иные связи остаются отдельными блокировками.
  Все остальные включённые флаги учитывать в отчёте как непокрытые.
- [ ] **Step 5: тестами подтвердить различие socket observation и policy.**
  Неизвестный слушающий порт не должен автоматически превращаться в allow.
  Consul с динамическими группами остаётся явно непокрытым, а не угадывается.
- [ ] **Step 6: отдельный коммит файлов задачи.**

## Task 4: playbook, приватный отчёт и сквозная проверка

**Files:** `ansible/host-firewall.yml`,
`ansible/roles/host-firewall/defaults/main.yml`,
`ansible/roles/host-firewall/tasks/main.yml`,
`ansible/roles/host-firewall/templates/report.md.j2`,
`tests/test_playbook.py`, `README.md`; ссылка из корневого `README.md`.

**Interfaces:** параметры первого этапа:

```yaml
host_firewall_mode: report
host_firewall_hosts: baremetal
host_firewall_probe_timeout: 10
host_firewall_probe_max_bytes: 262144
```

Выход на controller: уникальный приватный каталог внутри `artifacts/` корня
Kolla-Ansible, `report.json` и `report.md`. Каталог `0700`, файлы `0600`.
Существующий отчёт не перезаписывать. Каталог отчёта допускает отдельный override.

- [ ] **Step 1: написать локальные integration tests.** Временное дерево Kolla,
  localhost inventory, fixtures команд Task 2. Проверить результат JSON,
  права файлов, повторный запуск, сохранность предыдущего отчёта и fixture
  чужого firewall ruleset. Вызов с `host_firewall_mode=apply` обязан завершиться
  ошибкой до выполнения даже read-only remote probe; fixture фиксирует вызовы.
- [ ] **Step 2: выполнить `python3 -m unittest discover -s tests -p test_playbook.py -v`.**
  Подтвердить падения до добавления playbook.
- [ ] **Step 3: реализовать preflight gate и сбор.** Не импортировать
  `site.yml`, deploy/reconfigure handlers или штатный `gather-facts.yml`, который
  при `--limit` может обследовать хосты за пределами выбранного набора.
  Отмечать недоступные, пропущенные и неуспешно обследованные хосты, не превращая
  частичный запуск в полный. Не печатать probe output и hostvars в Ansible log.
- [ ] **Step 4: добавить controller aggregation и Markdown render.**
  Отчёт перечисляет выбранные хосты, время наблюдений, источники сведений,
  candidate flows, неизвестные флаги, ошибки команд и постоянный запрет apply.
- [ ] **Step 5: выполнить syntax-check на временно наложенной добавке к `0809`.**
  Архив не изменять; использовать распаковку во временном каталоге. Проверить,
  что все исходные файлы сохраняют SHA256 и ни один новый путь с ними не совпал.
- [ ] **Step 6: документировать запуск без environment variables.**
  Указывать явные inventory, globals и путь playbook; не добавлять несуществующую
  подкоманду в `kolla-ansible`. Пароли для обследования сервисных API не нужны:
  этот этап не аутентифицируется в OpenStack и не читает `passwords.yml`.
- [ ] **Step 7: запустить полную проверку добавки и текущие repository tests.**

  ```bash
  python3 -m unittest discover -s integrations/kolla-ansible/host-firewall/tests -v
  python3 -m unittest discover -s tests -v
  git diff --check
  ```

- [ ] **Step 8: обновить статус ADR ровно до report-only implementation.**
  Сохранить отдельным коммитом, не публиковать без запроса. В handoff перечислить
  выполненные проверки и непроверенное на стенде; не называть весь firewall готовым.

## Самопроверка плана

- Этап имеет самостоятельный результат: запускаемый report-only playbook.
- Связность стенда и backend apply не нужны для локальной разработки этапа.
- SSH, default-deny, откат и чужие rulesets не меняются этим этапом.
- Полное покрытие сервисов и реальное применение не скрыты за первыми API-записями.
- Сбор и отчёт не требуют выноса паролей в артефакты или журнал Ansible.
- До кода остаётся выбор рабочей копии; backend применяется только в следующем плане.
