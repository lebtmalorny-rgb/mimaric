# Исправление Ironic enrollment и отдельная команда запуска

## Краткий вывод

В форк добавлена отдельная команда:

```bash
kolla-ansible enroll-ironic
```

Она запускает `ansible/enroll-ironic.yml`, получает стандартные для
Kolla-Ansible `globals.yml`, `passwords.yml` и inventory, а BMC-хосты при
необходимости строит из `ironic_bmc_hosts`. Существующий параметризованный
вызов через `kolla-ansible` и прямой вызов `ansible-playbook` сохраняются.

Каждый BMC inventory host обрабатывает только соответствующий ему Ironic
Node. `serial` и `throttle` ограничивают реальную параллельность, а не
повторную обработку всей группы. Повторный запуск не вызывает `manage` для
уже `manageable` Nodes и завершается ошибкой, если хотя бы один ожидаемый
Node не достиг `manageable`.

`kolla-ansible post-deploy` не вызывает enrollment автоматически и после этой
правки продолжает работать как раньше.

Текущее исправление распространяется четырьмя последовательными patch-файлами:

1. `kolla-ansible-ironic-enroll-command.patch` — отдельная команда,
   inventory/Vault/validator/scale/state changes и основной runbook;
2. `kolla-ansible-ironic-enroll-diagnostic.patch` — безопасный вывод ошибки
   `openstack.cloud.resource` без раскрытия BMC-паролей;
3. `kolla-ansible-ironic-enroll-driver-info-type.patch` — передача
   `driver_info` как native mapping и регрессионная проверка типа;
4. `kolla-ansible-ironic-enroll-scope-isolation.patch` — нейтрализация
   унаследованного `OS_SYSTEM_SCOPE` внутри enrollment play.

Второй, третий и четвёртый patch применяются только после первого и не требуют
переустановки Python-пакета или redeploy/reconfigure кластера. Переустановка
пакета относится только к первоначальному добавлению CLI entry point из
первого patch, если рабочий `kolla-ansible` не использует editable checkout.

## Причина исходной ошибки

Ошибка возникала в
`ansible/roles/ironic_enroll/tasks/validate.yml`. Валидатор включал в
`ironic_bmc_resolved` весь объект `hostvars[item]`:

```yaml
combine({item: hostvars[item] | combine({...})})
```

Ansible при таком обращении пытался материализовать не только BMC-поля, но и
все унаследованные переменные хоста. В форке среди них есть контекстные
выражения, например вычисление адреса через `kolla_address`. При выполнении
локального BMC-play нужный контекст отсутствовал, поэтому появлялась ошибка
вида:

```text
'hostvars' variable is unavailable
```

Это не означало, что в BMC-записи отсутствуют `address` или `type`: падение
происходило раньше проверки этих полей, при раскрытии посторонних переменных.

## Что изменено в валидаторе

Вместо копирования всего `hostvars[item]` валидатор теперь формирует
минимальный словарь только из полей, необходимых роли:

- `address`;
- `type`;
- `ironic_bmc_resolved_attached_host`, вычисленный из `attached_host` или
  имени BMC-хоста;
- необязательный `redfish_system_id`;
- необязательный `ironic_bmc_default_redfish_system_id`;
- `ironic_bmc_username_global`: явное host-specific значение сохраняется, а
  при его отсутствии используется глобальный `ironic_bmc_username`.

Сами правила проверки `address`, `type` и поддерживаемых BMC-типов не
ослаблялись. Пароли в `ironic_bmc_resolved` не копируются. В обычном режиме
роль получает их из переменных `passwords.yml`, а в pull-only Vault mode — из
transient `no_log` facts текущего процесса `ansible-playbook`.

Регрессионный тест
`kolla_ansible/tests/unit/test_ironic_enroll_validation.py` создаёт
унаследованную обязательную, но намеренно неразрешимую переменную и проверяет,
что валидатор её не вычисляет и не переносит в результат.

## Как реализована отдельная команда

Последовательность вызова:

```text
kolla-ansible enroll-ironic
  -> setup.cfg: entry point EnrollIronic
  -> kolla_ansible/cli/commands.py: EnrollIronic.take_action()
  -> ansible/enroll-ironic.yml
  -> ansible/ironic-enroll-inventory.yml
  -> ansible/vault-bootstrap-fetch.yml (только при Vault mode)
  -> role ironic_enroll
```

`ansible/ironic-enroll-inventory.yml` добавляет в runtime inventory только те
BMC-хосты из `ironic_bmc_hosts`, которых ещё нет в группе `bmc`. Поэтому
приоритет остаётся у явного статического или dynamic inventory. Существующие
host vars не перезаписываются.

При добавлении хоста из `globals.yml` передаются только безопасные поля,
необходимые роли. Вложенные поля наподобие `password_override` не копируются.
После построения группы определяется минимальный набор BMC-паролей по реально
настроенным типам. Например, для `ipmi+redfish` запрашиваются только IPMI и
Redfish secrets, но не пароли iLO, iDRAC, XClarity или iRMC.

Подготовка CA на conductor hosts выполняется отдельным localhost-play до
serial enrollment. Поэтому `run_once` не повторяется для каждого batch.
Внутри BMC-play файлы `validate.yml`, `detect_driver.yml`, `enroll.yml` и
`verify.yml` работают только с `inventory_hostname`.

## Какие файлы меняются

| Файл | Назначение изменения |
|---|---|
| `IRONIC_ENROLL_FIX_AND_RUNBOOK.md` | Полный технический runbook и границы runtime-проверки |
| `setup.cfg` | Регистрация команды `enroll-ironic` |
| `kolla_ansible/cli/commands.py` | Новый класс `EnrollIronic` и isolated default `multinode` |
| `ansible/enroll-ironic.yml` | Импорт bootstrap-playbook и изоляция Keystone system scope |
| `ansible/ironic-enroll-inventory.yml` | BMC runtime inventory, включая полный Redfish URL |
| `ansible/vault-bootstrap-fetch.yml` | Строго ограниченное разрешение empty scope только для enrollment |
| `ansible/group_vars/all.yml` | Разрешённые controller-side имена BMC secrets для pull-only Vault |
| `etc/kolla/globals.yml` | BMC inventory, batch/throttle и bounded polling defaults |
| `etc/kolla/vault-bootstrap-secrets.yml` | Добавление BMC secrets в необязательный bootstrap manifest |
| `ansible/roles/ironic_enroll/tasks/validate.yml` | Выборочное копирование BMC-полей вместо всего `hostvars` |
| `ansible/roles/ironic_enroll/tasks/main.yml` | Подключение выбора безопасного источника BMC-паролей |
| `ansible/roles/ironic_enroll/defaults/main.yml` | Batch, throttle и bounded polling состояния |
| `ansible/roles/ironic_enroll/tasks/prepare.yml` | Однократная CA-подготовка с `become: true` |
| `ansible/roles/ironic_enroll/tasks/detect_driver.yml` | Выбор драйвера только для текущего BMC host |
| `ansible/roles/ironic_enroll/tasks/resolve_passwords.yml` | Выбор transient Vault values или обычных значений |
| `ansible/roles/ironic_enroll/tasks/enroll.yml` | Native `driver_info`, safe error reporting, reconciliation, state-aware `manage` и `last_error` |
| `ansible/roles/ironic_enroll/tasks/verify.yml` | Проверка `manageable` каждого ожидаемого Node |
| `kolla_ansible/tests/unit/test_ironic_enroll_command.py` | Контракт CLI и entry point |
| `kolla_ansible/tests/unit/test_ironic_enroll_environment.py` | Регрессия унаследованного `OS_SYSTEM_SCOPE=all` |
| `kolla_ansible/tests/unit/test_ironic_enroll_inventory.py` | Приоритет явного inventory и безопасный bootstrap |
| `kolla_ansible/tests/unit/test_ironic_enroll_passwords.py` | Контракты Vault/non-Vault без раскрытия секретов |
| `kolla_ansible/tests/unit/test_ironic_enroll_validation.py` | Регрессия исходной ошибки валидатора |
| `kolla_ansible/tests/unit/test_ironic_enroll_scaling.py` | Контракты `N`, а не `N×N`, native `driver_info`, redaction, idempotency и final state |

## Полный перечень технических изменений

### 1. Новая отдельная CLI-команда

В `setup.cfg` зарегистрирован entry point `enroll-ironic`. Класс
`EnrollIronic` в `kolla_ansible/cli/commands.py` выбирает только
`ansible/enroll-ironic.yml` и передаёт его штатному `run_playbooks()`.
Благодаря этому сохраняются общие аргументы Kolla-Ansible: inventory,
`globals.yml`, `passwords.yml`, `CONFIG_DIR`, Vault options, tags, limit,
check/diff и become.

Вызов без аргументов использует packaged `ansible/inventory/multinode` и
стандартный config directory `/etc/kolla`. Явный `-i` имеет приоритет;
параметризованный CLI-вызов и прямой `ansible-playbook` не удалены. Изменение
default ограничено классом `EnrollIronic` и не меняет inventory для deploy,
reconfigure и других команд Kolla-Ansible.

### 2. Построение BMC runtime inventory

Новый `ansible/ironic-enroll-inventory.yml` выполняется на `localhost` до
enrollment. Он преобразует `ironic_bmc_hosts` из `globals.yml` в группу `bmc`
через `add_host`, но добавляет только отсутствующие имена. Поэтому явный
статический или dynamic inventory имеет приоритет и его host vars не
перезаписываются.

Из вложенной записи переносятся только `address`, `type`, `attached_host`,
`redfish_address`, `redfish_system_id`, `redfish_verify_ca` и безопасные
defaults. `redfish_address` сохраняется как полный URL со схемой и портом;
если он отсутствует, совместимый fallback равен `https://<address>`.
`redfish_system_id` необязателен: при отсутствии поле не добавляется в
`driver_info`, и Ironic может выбрать единственный ComputerSystem. Встроенный
Dell-specific fallback `System.Embedded.1` удалён. Поля наподобие
`password_override` не копируются. Пустой `ironic_bmc_hosts` остаётся
разрешённым no-op.

### 3. Исправление исходной ошибки валидатора

`validate.yml` больше не объединяет весь `hostvars[item]`. Для текущего
`inventory_hostname` создаётся новый минимальный словарь с разрешёнными BMC
полями. Это исключает вычисление посторонних унаследованных выражений вроде
`kolla_address`, но сохраняет проверки обязательных `address`, `type` и
поддерживаемого BMC driver type.

Пароли и произвольные host vars в `ironic_bmc_resolved` не попадают. Ошибка
`'hostvars' variable is unavailable` воспроизводится на старом коде и
закрывается регрессионным тестом production tasks.

### 4. Vault и BMC-пароли

Inventory bootstrap вычисляет минимальный набор Vault keys по фактически
используемым BMC types. Разрешённые имена добавлены в
`ansible/group_vars/all.yml` и `etc/kolla/vault-bootstrap-secrets.yml`.

`resolve_passwords.yml` выбирает источник отдельно для Vault и non-Vault:
transient `vault_bootstrap_passwords` либо штатные
`ironic_bmc_*_password`. Plaintext существует только как `no_log` facts
текущего процесса и не записывается в generated inventory или persistent
YAML. Empty Vault scope разрешён только для `enroll-ironic`; остальные
операции сохраняют fail-closed проверку.

Текущая модель оставляет один username/password на BMC type. Per-host
credentials этим patch не добавляются.

### 5. Масштабирование без `N×N`

Раньше play выполнялся на каждом BMC host, но задачи внутри снова обходили
`groups['bmc']`. Для `N` серверов это давало до `N×N` create/manage attempts.

Теперь `validate.yml`, `detect_driver.yml`, `enroll.yml` и `verify.yml`
обрабатывают только `inventory_hostname`. Один BMC host выполняет одну
resource reconciliation своего Ironic Node, начальное чтение state,
необязательный `manage` и bounded verification. `serial` ограничивает размер
play batch, а `throttle` — число одновременных create/manage tasks.

При defaults `serial: 25` и 1000 BMC Ansible выполняет 40 последовательных
batches. Другой play host больше не повторяет операции для всей группы.

### 6. Подготовка Ironic conductors

`prepare.yml` вынесен из serial BMC-play в отдельный localhost-play. Поэтому
`run_once` не повторяется в каждом batch. `include_role.apply.tags` передаёт
`always`, `ironic` и `ironic-enroll` во вложенные tasks, поэтому подготовка
работает и при tagged-запуске.

Owner/group CA-файла задаются defaults с production-значением `root`. Если
локальный CA bundle отсутствует, `first_found` безопасно возвращает пустое
значение и optional copy пропускается без templating error. Обе delegated
операции с `/etc/kolla` явно используют `become: true`, поэтому не зависят от
CLI-флага `--become` при штатном passwordless sudo на conductor hosts.

### 7. Безопасный переход в `manageable`

До resource reconciliation роль читает существующий Node по имени. Для уже
созданного объекта `driver_info` обновляется только при выполнении двух
условий: `extra.managed_by=ansible` и state входит в enrollment boundary.
`available`, `active` и другие рабочие состояния отклоняются до обновления.
Новый Node создаётся как прежде. Разрешённый список обновляемых полей содержит
только `driver_info`; driver, interfaces, extra и прочие атрибуты существующего
Node не перезаписываются.

После reconciliation роль читает фактический `provision_state`:

- `manageable` — повторный `manage` пропускается;
- `enroll` и `enroll failed` — выполняется `baremetal node manage`;
- `verifying` — новый `manage` не отправляется, роль ждёт результат;
- `available`, `active` и остальные состояния — выполнение останавливается,
  чтобы не нарушить power-only границу.

Если между первым чтением и `manage` другой процесс уже начал переход, ошибка
повторного `manage` сама по себе не игнорируется. Роль повторно читает state и
продолжает только при подтверждённом `verifying` или `manageable`. Сетевые,
authentication и прочие ошибки остаются фатальными.

После отклонённого `manage` роль отдельно читает безопасное API-поле
`last_error` и добавляет его в итоговый assert. Секретный `manage_result`
остаётся под `no_log`, но оператор получает первичную причину Ironic вместо
одного сообщения о неизменившемся state.

`verify.yml` больше не читает все Nodes на каждом play host. Он выполняет
bounded polling только своего Node и требует итоговый
`provision_state=manageable`. Недостигший состояния Node делает Ansible host
failed и влияет на общий exit code.

### 8. Диагностика resource error и тип `driver_info`

Вызов `openstack.cloud.resource` остаётся под `no_log: true`, поэтому полный
result, invocation, exception, HTTP body и BMC credentials не выводятся.
Задача обёрнута в `block/rescue`: из зарегистрированного результата берётся
только поле `msg`, после чего все непустые BMC-пароли из текущего password map
заменяются на `[REDACTED]`. Итоговая ошибка содержит имя Ironic Node, имя BMC
inventory host и очищенное сообщение OpenStack SDK.

Маскирование относится именно к известным BMC-паролям. Сообщение SDK может
содержать endpoint, username, UUID Node и другие несекретные диагностические
поля, поэтому полный лог всё равно следует передавать только по разрешённому
каналу.

Диагностический запуск на целевом окружении показал следующую отдельную
ошибку:

```text
Schema error for patch: "{...}" is not of type 'object', 'null'
```

Причина состояла в том, что составленный Jinja block возвращал `_driver_info`
как строковое представление словаря. Тестовая заглушка скрывала дефект,
выполняя `ast.literal_eval()` перед проверками. В исправленном коде значение
нормализуется через `from_yaml`, если оно является строкой, и затем явно
проверяется условием `_driver_info is mapping` до обращения к OpenStack API.
Тестовая заглушка больше не преобразует строку и отклоняет любой
`driver_info`, который не является native dictionary.

Это исправляет подтверждённый HTTP 400 schema mismatch. Успешное прохождение
следующих Redfish и provision-state этапов подтверждается только новым
runtime-запуском в целевом кластере.

### 9. Изоляция Keystone scope

Enrollment использует project-scoped cloud `kolla-admin` из
`<node_config>/clouds.yaml`. Если вызывающая оболочка ранее загрузила
system-scoped openrc, она передаёт `OS_SYSTEM_SCOPE=all` в `ansible-playbook`,
а локальные OpenStack CLI-задачи наследуют его. Одновременный project и system
scope приводит к ошибке аутентификации ещё до обращения к Ironic.

BMC-play теперь задаёт собственное окружение:

```yaml
environment:
  OS_CLIENT_CONFIG_FILE: "{{ node_config }}/clouds.yaml"
  OS_SYSTEM_SCOPE: ""
```

Пустое значение не выбирает system scope и оставляет источником project scope
именованный cloud. Изменение действует только на задачи enrollment play: оно
не меняет вызывающую оболочку, остальные команды Kolla-Ansible или содержимое
`clouds.yaml`. Остальные `OS_*` намеренно не очищаются этим patch, поскольку
подтверждённый конфликт относится к `OS_SYSTEM_SCOPE`.

Регрессионный тест запускает настоящую локальную Ansible-задачу при
`OS_SYSTEM_SCOPE=all` в родительском процессе и проверяет её эффективное
окружение: `OS_SYSTEM_SCOPE=` и ожидаемый `OS_CLIENT_CONFIG_FILE`.

### 10. Тесты и доказанная граница

Добавлены unit/contract tests для CLI, inventory bootstrap, Vault/non-Vault
password source, минимального validator map и scale/state поведения. Scale
suite реально запускает production Ansible tasks с несколькими BMC hosts;
локальными substitutes заменены только внешние OpenStack module/CLI calls.

Проверяются `N`, а не `N×N`, serial batches, tagged conductor preparation,
`become`, полный Redfish URL с нестандартным портом, отсутствие vendor System
ID, native mapping для `driver_info`, redaction BMC-паролей, безопасная
reconciliation существующего Node, запрет чужих provision states, вывод
`last_error`, обязательный final state и race конкурентного `manage`.

Локальные проверки не обращаются к реальным OpenStack, Vault или BMC. Поэтому
они доказывают структуру и control flow patch, но не фактический enrollment и
управление питанием в целевом кластере.

## Что делает `post-deploy`

В этом форке `Postdeploy.take_action()` выбирает только
`ansible/post-deploy.yml`. Playbook выполняет на deploy node следующие
действия:

1. Проверяет доступность каталога `node_config` и определяет необходимость
   `become`.
2. При `enable_config_vault: false` создаёт `clouds.yaml`, admin/public openrc
   и их system-варианты.
3. При включённой Octavia дополнительно вызывает `octavia/openrc.yml`.
4. При `enable_config_vault: true` не создаёт файлы с открытыми учётными
   данными и выводит пояснение.

После этого внутри Kolla-Ansible больше ничего не вызывается: enrollment,
другой playbook или post-hook отсутствуют.

Переменная:

```yaml
ironic_enroll_run_after_post_deploy: false
```

в репозитории объявлена, но код её не читает. Значение `true` ничего не
изменяет. Для отдельной команды она не нужна; оставленное значение `false`
совместимо с новым поведением и явно исключает ожидание автоматического
запуска.

## Предварительные условия

Для запуска без параметров должны существовать стандартные пути:

- `/etc/kolla/globals.yml`;
- `/etc/kolla/passwords.yml`;
- packaged `ansible/inventory/multinode` из установленного fork;
- `/etc/kolla/clouds.yaml` с cloud `kolla-admin`;
- установленные Ansible collections, включая `openstack.cloud`;
- доступ deploy node к OpenStack API и BMC endpoints.

`/etc/kolla/globals.yml` должен содержать BMC-описания без секретов, например:

```yaml
ironic_bmc_username: "admin"
ironic_bmc_default_redfish_system_id: ""

ironic_bmc_hosts:
  bmc_compute_01:
    attached_host: compute-01
    address: "192.0.2.10"
    type: "ipmi+redfish"
    redfish_address: "http://192.0.2.10:8000"
    redfish_system_id: "/redfish/v1/Systems/1"
    redfish_verify_ca: false
```

`redfish_address` — полный Redfish endpoint без `/redfish/v1/`; схема и порт
не вычисляются из management IP. Для production используйте HTTPS и CA bundle.
HTTP и `redfish_verify_ca: false` допустимы только в изолированном test/lab:
BMC credentials передаются без TLS. Не помещайте username/password в URL.

`redfish_system_id` берётся из `Members[]."@odata.id"` коллекции
`<redfish_address>/redfish/v1/Systems/`. Если поле отсутствует и BMC управляет
ровно одним ComputerSystem, Ironic выбирает его автоматически. При нескольких
Systems задайте значение явно для детерминированного enrollment.

Значения `vault_ironic_bmc_*_password`, из которых в обычном режиме строятся
`ironic_bmc_*_password`, должны поступать из защищённого `passwords.yml` или
Ansible Vault, а не храниться в inventory, документации или командной строке.

В pull-only Vault mode соответствующие ключи должны существовать по shared KV
пути deployment/region. Команда получает только secrets, нужные типам из
текущей группы `bmc`, держит plaintext как `no_log` facts в одном процессе и
не записывает его в persistent YAML.

Если группа `bmc` и `ironic_bmc_hosts` пусты, enrollment остаётся разрешённым
no-op даже в Vault mode. Ослабление empty scope действует только на import из
`enroll-ironic.yml`; остальные команды сохраняют строгую проверку непустого
Vault bootstrap request.

Важно: при `enable_config_vault: true` штатный `post-deploy` намеренно не
создаёт `/etc/kolla/clouds.yaml`. До enrollment необходимо предоставить
разрешённый в данном окружении временный OpenStack client config; сама новая
команда это ограничение не обходит.

## Другие хосты и масштаб до 1000 BMC

Для новых серверов исходный код менять не нужно. В рабочем
`/etc/kolla/globals.yml` меняется `ironic_bmc_hosts`:

```yaml
ironic_bmc_hosts:
  bmc_compute_0001:
    attached_host: compute-0001
    address: "10.101.25.101"
    type: "redfish"
    redfish_address: "https://10.101.25.101"
  bmc_compute_0002:
    attached_host: compute-0002
    address: "10.101.25.102"
    type: "ipmi+redfish"
    redfish_address: "https://10.101.25.102:8443"
    redfish_system_id: "/redfish/v1/Systems/1"
```

- ключ `bmc_compute_0001` — уникальное имя Ansible inventory host;
- `attached_host` — имя Ironic Node и связанного Nova compute-host;
- `address` — management IP/FQDN без схемы; используется IPMI и как fallback
  для Redfish;
- `redfish_address` — необязательный полный URL Redfish со схемой и портом;
- `type` содержит один или несколько поддерживаемых типов:
  `redfish`, `ipmi`, `ilo5`, `drac5`, `xclarity`, `irmc`;
- `redfish_system_id` необязателен при единственном System и задаётся явно,
  если BMC управляет несколькими Systems либо нужен deterministic mapping;
- `redfish_verify_ca` может быть boolean или путём к доверенному CA внутри
  conductor container; не включайте credentials в `redfish_address`.

Удаление записи из `ironic_bmc_hosts` не удаляет Ironic Node. Изменение
`attached_host` означает другое имя Node, поэтому прежний объект останется.
Существующий Node получает обновлённый `driver_info` только если он помечен
`extra.managed_by=ansible` и находится в `enroll`, `enroll failed`,
`verifying` или `manageable`. Для `available`, `active`, другого state или
чужого Node reconciliation останавливается до изменения. Удаление записи из
config по-прежнему не удаляет Node.

Текущая password-модель использует один username и один password на BMC type.
Она подходит, если все Redfish/IPMI устройства соответствующего типа имеют
общую service account. Разные credentials для каждого из 1000 BMC пока не
поддерживаются; пароли нельзя добавлять во вложенные host records. Для этого
нужна отдельная схема per-host secret references с разрешённым Vault scope.

После scale-исправления один BMC inventory host выполняет одну resource
reconciliation соответствующего Ironic Node, одно начальное чтение состояния,
необязательный `manage` и bounded final polling. Другой inventory host больше
не повторяет эти действия для всей группы. Стандартные ограничения:

```yaml
ironic_enroll_serial: 25
ironic_enroll_throttle: 10
ironic_enroll_manage_timeout: 300
ironic_enroll_state_read_retries: 6
ironic_enroll_state_read_delay: 2
ironic_enroll_verify_retries: 12
ironic_enroll_verify_delay: 5
```

При 1000 Nodes значение `serial: 25` создаёт 40 последовательных play batches,
а `throttle: 10` разрешает не более десяти одновременных create/manage tasks.
Начинать рекомендуется с этих значений и увеличивать их только после проверки
нагрузки на Ironic API, conductor и BMC. Увеличение `serial` не требует
редеплоя контейнеров: переменная читается при следующем запуске команды.

Для 1000 записей предпочтителен генерируемый из CMDB статический/dynamic
inventory. Явные host vars имеют приоритет над `ironic_bmc_hosts`. Обычный
полный запуск уже делится на batches автоматически:

```bash
kolla-ansible enroll-ironic
```

Для контролируемого повторного запуска части узлов заранее создайте в
статическом/dynamic inventory подгруппы `bmc_batch_001`, `bmc_batch_002` и
так далее. `--limit` должен сохранять `localhost`, иначе inventory bootstrap
и Vault secret scope не выполнятся:

```bash
kolla-ansible enroll-ironic \
  --limit 'localhost,bmc_batch_001'
```

В Vault mode дополнительно проверьте доступность настроенного
`vault_bootstrap_host`. Не используйте `--limit` как единственный способ
описания ещё не существующих dynamic hosts: имена и batch groups должны быть
известны inventory до BMC-play.

## Установка четырёх patch-файлов

Patch применяются к одному checkout строго в указанном порядке:

```bash
cd /path/to/kolla-ansible

git apply --check ../kolla-ansible-ironic-enroll-command.patch
git apply ../kolla-ansible-ironic-enroll-command.patch

git apply --check ../kolla-ansible-ironic-enroll-diagnostic.patch
git apply ../kolla-ansible-ironic-enroll-diagnostic.patch

git apply --check ../kolla-ansible-ironic-enroll-driver-info-type.patch
git apply ../kolla-ansible-ironic-enroll-driver-info-type.patch

git apply --check ../kolla-ansible-ironic-enroll-scope-isolation.patch
git apply ../kolla-ansible-ironic-enroll-scope-isolation.patch
```

Если один или несколько patch уже применены, не применяйте их повторно:
начните со следующего отсутствующего patch после отдельного
`git apply --check`.

Первый patch меняет `setup.cfg` и добавляет CLI entry point. Если команда
`kolla-ansible help` ещё не показывает `enroll-ironic`, активируйте рабочее
Python-окружение и переустановите fork тем же способом, которым он был
установлен:

```bash
python -m pip install -e .
kolla-ansible help | grep -F enroll-ironic
```

Для production-установки вместо editable mode соберите и установите wheel по
принятой процедуре. Если `enroll-ironic` уже существует и запускает playbook
из текущего checkout, после diagnostic и driver-info-type patch повторная
установка не нужна. Scope-isolation patch также меняет только Ansible play,
тесты и документацию. Эти три инкрементальных patch не требуют redeploy или
`reconfigure` OpenStack-кластера.

Короткая инструкция для копирования и установки находится в companion-файле
`PATCH_INSTALL.md`, который распространяется рядом с четырьмя patch-файлами.

## Проверки исходного кода

В окружении с зависимостями из `requirements.txt` и
`test-requirements.txt`:

```bash
python -m unittest \
  kolla_ansible.tests.unit.test_approle_bootstrap_order \
  kolla_ansible.tests.unit.test_ironic_enroll_command \
  kolla_ansible.tests.unit.test_ironic_enroll_environment \
  kolla_ansible.tests.unit.test_ironic_enroll_inventory \
  kolla_ansible.tests.unit.test_ironic_enroll_passwords \
  kolla_ansible.tests.unit.test_ironic_enroll_scaling \
  kolla_ansible.tests.unit.test_ironic_enroll_validation \
  kolla_ansible.tests.unit.test_vault_bootstrap_scoping
```

Тесты запускают настоящие production tasks через локальный
`ansible-playbook`, но не обращаются к OpenStack, Vault или BMC.
Полный указанный набор содержит 40 тестов; отдельный шаблон
`test_ironic_enroll_*.py` содержит 26 тестов.

## Preflight

Следующие проверки не выполняют enrollment:

```bash
kolla-ansible enroll-ironic --help

ansible-playbook \
  -i /path/to/kolla-ansible/ansible/inventory/multinode \
  ansible/enroll-ironic.yml \
  -e @/etc/kolla/globals.yml \
  -e @/etc/kolla/passwords.yml \
  -e node_config=/etc/kolla \
  --syntax-check

kolla-ansible enroll-ironic --list-tasks
```

Не выводите `ansible-inventory --list` или extra vars в общий лог без
предварительной проверки: в объединённых переменных могут присутствовать
секреты.

## Запуск

Scope-isolation patch нейтрализует унаследованный `OS_SYSTEM_SCOPE=all`
внутри BMC-play. Для этого подтверждённого конфликта больше не требуется
запускать `kolla-ansible enroll-ironic` из отдельного subshell с ручным
`unset OS_*`. Вызывающая оболочка при этом остаётся без изменений.

### Без параметров

При стандартной структуре `/etc/kolla` и установленном packaged inventory:

```bash
kolla-ansible enroll-ironic
```

Команда автоматически передаёт packaged `ansible/inventory/multinode`,
`globals.yml`, `passwords.yml` и `CONFIG_DIR=/etc/kolla`. Runtime play создаёт
группу `bmc` из `ironic_bmc_hosts`. Если реальный cluster inventory находится
в другом месте, передайте его через `-i`; явное значение всегда имеет
приоритет.

### С параметрами Kolla-Ansible

Способ вызова с параметрами остаётся доступным:

```bash
kolla-ansible enroll-ironic \
  -i /home/VVaPrisyazhnyuk/kolla-ansible/ansible/inventory/multinode \
  --configdir /etc/kolla \
  --passwords /etc/kolla/passwords.yml
```

Можно передать только статический inventory: отсутствующие в его группе
`bmc` записи будут дополнены из `ironic_bmc_hosts`.

Если одновременно используется `--limit`, нужно учитывать стандартную
семантику Ansible: ограничение, исключающее `localhost`, не позволит
bootstrap-play добавить отсутствующие BMC и вычислить Vault secret scope.
Поэтому для enrollment из `ironic_bmc_hosts` и для pull-only Vault mode нельзя
исключать `localhost`. При обычном non-Vault запуске с уже существующей
группой `bmc` статический/dynamic inventory продолжает работать.

### Прямой вызов Ansible

Старый способ остаётся рабочим и использует те же playbook и роль:

```bash
cd /path/to/kolla-ansible
ansible-playbook \
  -i /home/VVaPrisyazhnyuk/kolla-ansible/ansible/inventory/multinode \
  ansible/enroll-ironic.yml \
  -e @/etc/kolla/globals.yml \
  -e @/etc/kolla/passwords.yml \
  -e node_config=/etc/kolla
```

Bootstrap видит, что dynamic inventory уже создал хосты группы `bmc`, и не
перезаписывает их.

## Проверка результата

Enrollment изменяет состояние OpenStack: создаёт Ironic Nodes при их
отсутствии и вызывает переход `enroll -> manageable`. После запуска нужна
runtime-проверка:

```bash
openstack --os-cloud kolla-admin \
  --os-interface internal \
  baremetal node list --long

openstack --os-cloud kolla-admin \
  --os-interface internal \
  baremetal node show compute-01 -f yaml
```

Проверьте как минимум `name`, `driver`, `provision_state`, интерфейсы и
ожидаемый BMC endpoint без публикации `driver_info` в общий лог.

Роль сначала читает фактический `provision_state`. Повторный `manage`
выполняется только для `enroll` или `enroll failed`; `verifying` ожидается, а
`available`, `active` и другие состояния отклоняются как выход за границу
power-only enrollment. Если конкурентный запуск успел начать переход после
первого чтения, отклонённый `manage` принимается только после повторного
подтверждения `verifying` или `manageable`. Финальный `verify.yml` отдельно
опрашивает каждый Node и завершает соответствующий inventory host ошибкой,
если тот не достиг `manageable` за заданное время.

Нулевой exit code теперь подтверждает этот программный state gate для всех
узлов текущего запуска. Он всё равно не доказывает исправность реального
управления питанием: её нужно проверять отдельными командами ниже.

`--check` нельзя считать полноценным безопасным доказательством: используемые
OpenStack-модули и команда `openstack baremetal node manage` не гарантируют
полную эмуляцию всех изменений.

## Проверка Ironic и управление питанием

Ниже приведены ручные команды для power-only Ironic Nodes. Они не входят в
`enroll-ironic` и должны выполняться только оператором в целевом окружении.
Пример использует разные переменные для имени Ironic Node и Nova compute-host:

```bash
export OS_CLOUD=kolla-admin
export OS_INTERFACE=internal

test_node=compute-01
test_host=compute-01
```

Если имя Ironic Node не совпадает с полем `Host` сервиса `nova-compute`,
задайте в `test_node` и `test_host` соответствующие разные значения.

### Read-only проверка Ironic

```bash
openstack baremetal conductor list --long
openstack baremetal node list --long

openstack baremetal node show "$test_node" \
  -f yaml \
  -c uuid \
  -c name \
  -c provision_state \
  -c power_state \
  -c target_power_state \
  -c last_error \
  -c driver \
  -c power_interface \
  -c management_interface \
  -c network_interface \
  -c maintenance

openstack baremetal node validate "$test_node"
```

`node validate` не меняет power/provision state, но проверка power- и
management-интерфейсов может обращаться к BMC. У power-only узла ожидаются
`provision_state=manageable` и `network_interface=noop`. Не выводите
`driver_info` в общий лог: там могут присутствовать BMC credentials.

### Обязательный safety gate перед power action

Сначала запретите новые размещения на compute-host и убедитесь, что на нём нет
инстансов:

```bash
openstack compute service list \
  --host "$test_host" \
  --service nova-compute \
  --long

openstack compute service set \
  --disable \
  --disable-reason "manual-ironic-power-test" \
  "$test_host" nova-compute

openstack server list \
  --all-projects \
  --host "$test_host" \
  --long

test "$(
  openstack server list \
    --all-projects \
    --host "$test_host" \
    -f value \
    -c ID | wc -l | tr -d ' '
)" = "0"
```

Если последняя команда завершилась с ненулевым кодом, остановитесь: сначала
нужен согласованный drain/migration workflow. Прямые Ironic power actions не
заменяют fencing через Masakari и не должны выполняться на хосте с workload.

### Ожидание подтверждённого power state

Для проверки результата задайте ограниченную по времени shell-функцию:

```bash
wait_power_state() {
    desired_state="$1"
    for power_attempt in $(seq 1 60); do
        actual_state="$(
            openstack baremetal node show "$test_node" \
              -f value -c power_state
        )"
        last_error="$(
            openstack baremetal node show "$test_node" \
              -f value -c last_error
        )"
        printf 'attempt=%s power_state=%s last_error=%s\n' \
          "$power_attempt" "$actual_state" "$last_error"

        if [ "$actual_state" = "$desired_state" ]; then
            return 0
        fi
        if [ -n "$last_error" ] && [ "$last_error" != "None" ]; then
            return 1
        fi
        sleep 5
    done
    return 1
}
```

Функция ждёт не более пяти минут и возвращает ненулевой код при timeout или
`last_error`. Автоматически выполнять следующую power action после такой
ошибки нельзя.

### Выключение, включение и перезагрузка

Предпочтительный способ выключения — soft power off:

```bash
openstack baremetal node power off \
  --soft \
  --power-timeout 300 \
  "$test_node"

wait_power_state "power off"
```

Hard power off допустим только после явного решения оператора, например если
graceful shutdown завершился timeout и потеря несохранённого состояния
приемлема:

```bash
openstack baremetal node power off \
  --power-timeout 120 \
  "$test_node"

wait_power_state "power off"
```

Включение узла:

```bash
openstack baremetal node power on \
  --power-timeout 300 \
  "$test_node"

wait_power_state "power on"
```

Soft reboot и аварийный hard reboot:

```bash
openstack baremetal node reboot \
  --soft \
  --power-timeout 300 \
  "$test_node"

# Только после отдельного решения об аварийном hard reboot:
openstack baremetal node reboot \
  --power-timeout 300 \
  "$test_node"
```

Для контролируемого теста предпочтительнее явный цикл `power off` → ожидание
`power off` → `power on` → ожидание `power on`. После `reboot` простая проверка
`power_state=power on` может дать ложноположительный результат, если опрос
успел выполниться до начала перезагрузки; дополнительно контролируйте BMC,
доступность ОС и время обновления состояния узла.

### Проверка после power action и возврат Nova

```bash
openstack baremetal node show "$test_node" \
  -f yaml \
  -c name \
  -c provision_state \
  -c power_state \
  -c target_power_state \
  -c last_error

openstack baremetal node validate "$test_node"

openstack compute service list \
  --host "$test_host" \
  --service nova-compute \
  --long
```

До включения `nova-compute` отдельно подтвердите загрузку ОС, состояние
libvirt, отсутствие stale domains и исправность используемых сетью агентов.
Если на хосте активен Masakari maintenance/recovery workflow, дождитесь его
штатного завершения. Только после этих проверок:

```bash
openstack compute service set --enable "$test_host" nova-compute

openstack compute service list \
  --host "$test_host" \
  --service nova-compute \
  --long
```

При ошибке оставьте `nova-compute` выключенным, не выполняйте автоматический
power on после emergency fencing и соберите диагностику:

```bash
openstack baremetal node show "$test_node" \
  -f yaml \
  -c uuid \
  -c name \
  -c provision_state \
  -c power_state \
  -c target_power_state \
  -c last_error

openstack baremetal node validate "$test_node"
openstack baremetal conductor list --long

# На узле с Kolla containers; выберите фактически используемый engine.
docker ps --filter name=ironic_conductor
docker logs --since 10m ironic_conductor
# podman ps --filter name=ironic_conductor
# podman logs --since 10m ironic_conductor
```

Если узел был выключен ошибочно и нет запрета со стороны fencing/recovery,
ручной откат — `power on` с обязательным ожиданием `power on`. Возврат
`nova-compute` выполняется отдельным решением после host health checks.

Этот power-only сценарий не переводит узел в `available`, не запускает
cleaning, inspection или provisioning и не меняет `network_interface=noop`.
Синтаксис команд соответствует официальной документации
[Ironic CLI 2025.1](https://docs.openstack.org/python-openstackclient/2025.1/cli/plugin-commands/ironic.html),
[OpenStackClient compute v2](https://docs.openstack.org/python-openstackclient/latest/cli/command-objects/compute/v2/index.html)
и [Bare Metal API](https://docs.openstack.org/api-ref/baremetal/index.html).

## Откат

### Откат кода через patch

Откатывайте код в порядке, обратном установке:

```bash
cd /path/to/kolla-ansible

git apply -R --check ../kolla-ansible-ironic-enroll-scope-isolation.patch
git apply -R ../kolla-ansible-ironic-enroll-scope-isolation.patch

git apply -R --check ../kolla-ansible-ironic-enroll-driver-info-type.patch
git apply -R ../kolla-ansible-ironic-enroll-driver-info-type.patch

git apply -R --check ../kolla-ansible-ironic-enroll-diagnostic.patch
git apply -R ../kolla-ansible-ironic-enroll-diagnostic.patch

git apply -R --check ../kolla-ansible-ironic-enroll-command.patch
git apply -R ../kolla-ansible-ironic-enroll-command.patch
```

Если нужно убрать только изоляцию scope, выполните только первую пару команд.
Driver-info-type patch нельзя откатывать раньше scope-isolation patch,
diagnostic patch — раньше driver-info-type patch, а основной patch — раньше
всех трёх инкрементальных patch.

Переустановка пакета/entry points требуется только после прямого или обратного
изменения первого patch, содержащего `setup.cfg`. Откат трёх инкрементальных
patch не требует переустановки, redeploy или `reconfigure`.

### Откат runtime-состояния

Откат кода не удаляет созданные Ironic Nodes и не возвращает их прежнее
состояние. До первого запуска сохраните read-only снимок:

```bash
openstack --os-cloud kolla-admin \
  --os-interface internal \
  baremetal node list --long -f yaml
```

Удалять можно только UUID узлов, про которые достоверно известно, что они были
созданы этим запуском. Для ранее существовавших узлов сначала зафиксируйте их
атрибуты и восстанавливайте их отдельно. Удаление Ironic Node — деструктивная
операция и не должно выполняться автоматически этим runbook.

## Граница подтверждения

Статически и локальными тестами проверяются выбор playbook, регистрация CLI,
стандартные аргументы без параметров, построение runtime inventory в том числе
без исходной группы `bmc`, приоритет явных host vars, исправление валидатора,
Vault/non-Vault выбор BMC-паролей, native тип `driver_info`, маскирование
BMC-паролей, нейтрализация унаследованного `OS_SYSTEM_SCOPE=all` и
YAML/syntax-контракт.

Runtime-запуск диагностического patch подтвердил на целевом OpenStack API
строковый `driver_info` и HTTP 400 schema mismatch. Последнее исправление типа
проверено локальными contract tests. Последующая read-only проверка
`driver_info` узла `ultra1-2` подтвердила ожидаемые
`http://10.101.25.237:8000`, `/redfish/v1/Systems/1` и
`redfish_verify_ca=false`. Scope-isolation patch также проверен только
локально. Его фактический проход через OpenStack API, подключение к BMC и
переход Nodes в `manageable` требуют нового запуска в целевом окружении.
Управление питанием остаётся отдельной операторской проверкой.
