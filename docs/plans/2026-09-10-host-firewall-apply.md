# Host firewall apply/rollback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:executing-plans` for inline execution, or
> `superpowers:subagent-driven-development` if the user selects delegation.
> Execute tasks in order; steps use checkbox syntax for tracking.

**Goal:** Добавить в самостоятельный Kolla playbook проверяемое применение
host INPUT policy через firewalld, с SSH от любых источников и независимым откатом.

**Architecture:** Сначала расширяются отчёт и доказательная матрица потоков.
Чистая модель компилирует только разрешённые связи; отдельный адаптер управляет
одной policy, а локальный журнал и watchdog восстанавливают её без Ansible.
Оркестрация применяет правила последовательно, проверяет новые соединения
и сохраняет permanent только после проверок.

**Tech Stack:** ansible-core 2.18.x; Python 3.11 на целевом RPM/systemd-хосте;
firewalld 1.3.4/nftables для первого проверяемого профиля; системные `firewall`,
`dbus`, `gi` bindings; unittest и изолированные Linux-тесты.
Galaxy collections и pip-установка на целевые хосты не требуются.

**Spec:** [согласованный дизайн](2026-09-10-host-firewall-apply-design.md).

## Global Constraints

- «SSH-порт разрешается для `0.0.0.0/0` и `::/0`.»
- «Порт 22 не подставляется вместо неизвестного нестандартного порта.»
- «`report` остаётся режимом по умолчанию.»
- «Новых ограничений OUTPUT/FORWARD не вводим.»
- «Не меняем NAT, Neutron Security Groups, интерфейсы, маршруты, настройки SSH и HA.»
- «Не используется глобальный `--runtime-to-permanent`: сохраняется только свой объект.»
- «Не вводим `force`, разрешающий игнорировать эти ошибки.»
- «Отсутствующий или остановленный firewalld автоматически не устанавливается и не запускается.»
- «`--check` во всех режимах допускает только чтение и локальный отчёт».
- «Применение выполняется по одному хосту; ошибка запрещает переход к следующему.»
- Объект `kolla-host-input`: `ANY → HOST`, target `CONTINUE`.
- Не выполнять live SSH/OpenStack/firewall операции, deploy, restart или push
  в рамках реализации. Изолированный Linux-стенд — отдельный явно выбранный ресурс.
- Не менять базовые архивы, Horizon, существующие PowerOps-патчи и чужие правки.
- Каталог непокрытого включённого сервиса блокирует apply, даже если механизм
  транзакции уже написан. Универсальность отчёта не равна поддержке всех драйверов.

## Исходная точка и рабочая область

Ветка: `feature/host-firewall-report`, дизайн в коммите `07514a2`.
В worktree уже есть незакоммиченные изменения prereq-report: RPM firewalld и
python3-firewall, версия CLI, состояние unit и доступность read-only policy API.
Они не являются кодом применения. Task 0 проверяет и сохраняет их отдельно.

Все команды ниже, если не указано иначе, выполняются из корня git worktree.
Пути `ansible/...` и `tests/...` в блоках Files — относительно
`integrations/kolla-ansible/host-firewall/` (далее «добавка»).
Новые файлы добавки накладываются на Kolla `ansible/`, а не заменяют её роли.
Планы хранятся в существующем `docs/plans/`: `docs/superpowers/` запрещён
контрактом `tests/test_repository.py`.

Точная база — `baselines/0809.json`, архив
`kolla-ansible-enroll-ironic-patch-3_0809.zip`, SHA256
`b5958f14a09b1bdad4edc9c6b3dd092f4376b55dee9d5814fd2ad78fdffb1be9`.
Не использовать одноимённую распаковку без проверки хеша исходного архива.

## Контракты поставки

| Файл добавки | Ответственность |
| --- | --- |
| `ansible/module_utils/powerops_firewall_model.py` | Отчёт, blockers, обратная совместимость report |
| `ansible/module_utils/powerops_firewall_plan.py` (новый) | Схема планов, нормализация, digest, матрица, компиляция правил |
| `ansible/action_plugins/powerops_firewall_model.py` | Проекция только разрешённых ключей, без полного hostvars |
| `ansible/module_utils/powerops_firewall_probe.py` | Ограниченные read-only наблюдения и выбранные поля конфигов |
| `ansible/roles/host-firewall/vars/catalog.yml` | Классификация флагов и связи сервисов с доказательствами |
| `ansible/roles/host-firewall/vars/profiles.yml` (новый) | Проверенные сочетания драйверов и обязательные health checks |
| `ansible/module_utils/powerops_firewall_firewalld.py` (новый) | Снимки и изменения ровно одной policy, D-Bus adapter |
| `ansible/module_utils/powerops_firewall_transaction.py` (новый) | Lock, durable journal, deadlines, commit/rollback |
| `ansible/module_utils/powerops_firewall_checks.py` (новый) | Типизированные, ограниченные по времени проверки |
| `ansible/action_plugins/powerops_firewall_verify.py` (новый) | Новое SSH-соединение и сбор проверок controller-side |
| `ansible/library/powerops_firewall_transaction.py` (новый) | Тонкий Ansible facade локального helper |
| `ansible/roles/host-firewall/files/powerops_firewall_helper.py` (новый) | JSON CLI для Ansible, timer и boot recovery |
| `ansible/roles/host-firewall/tasks/{report,prepare,apply,rollback}.yml` (новые) | Разделённые операции; основной dispatcher остаётся в main.yml |
| `ansible/roles/host-firewall/templates/` | Отчёт, собственные systemd units и зависимость boot recovery |
| `tests/test_{plan,catalog,adapter,transaction,checks,apply}.py` (новые) | Чистые, контрактные и Ansible-тесты |
| `tests/transaction_fixtures.py` (новый) | Детерминированные fake clock/firewall/supervisor для unit-тестов |
| `tests/linux/{README.md,verify.yml}` (новые) | Отдельный opt-in Linux профиль, не production playbook |

### Настройки нового этапа

Добавить в defaults и README вместе с задачей, которая их использует:

```yaml
host_firewall_mode: report
host_firewall_initialize: false
host_firewall_allow_initial_reload: false
host_firewall_plan_file: ""
host_firewall_plan_id: ""
host_firewall_rollback_transaction_id: ""
host_firewall_extra_ssh_ports: []
host_firewall_service_sources: {}
host_firewall_verification_sources: {}
host_firewall_rollback_timeout: 300
host_firewall_verification_timeout: 90
host_firewall_api_timeout: 5
```

`plan_file` — приватный локальный JSON artifact; `plan_id` — его digest,
не пароль и не разрешение обойти проверки. `rollback_transaction_id` выбирает
конкретный локальный снимок. `service_sources` — CIDR по идентификатору
внешнего входящего потока. `verification_sources` — inventory-host по группе
проверок; исключённый `--limit` хост не опрашивается автоматически.

Ограничения: rollback timeout `60..900`, API timeout `1..10`, verification
timeout `10..600`, плюс `verification_timeout + 60 <= rollback_timeout`.
Commit резервирует не менее 30 секунд до deadline; исчерпание бюджета — rollback.
Параметры не должны менять deadline уже открытой транзакции.
Жёстко заданные имена/пути владельца не становятся произвольными shell/path vars.

`--check`: модуль проверяет свой check_mode до создания lock, директорий,
таймера или вызова изменения API. Отчёт явно содержит `simulation_only: true`.
Обычный report не получает скрытых удалённых изменений из новых imports/handlers.

### План и транзакция

План JSON schema 2 содержит `baseline_sha256`, `catalog_digest`, `profile_id`,
`selected_hosts`, `hosts`, `plan_id`. Для каждого хоста: подтверждённый порт SSH,
адреса, упорядоченные flows, policy rules, обязательные checks, blockers,
fingerprint runtime/permanent и чужой конфигурации, network/backend capabilities.
Digest исключает только timestamp и счётчики трафика; не исключает порты,
источники, правила, параметры проверки или capability profile.

`configuration_ready` означает полноту входов, не успешный apply.
В отчёте отдельно показывать ещё невыполненные проверки нового SSH и сервисов.
Окончательный успех — только результат операции `state: COMMITTED`.
До Task 9 сохранить `APPLY_NOT_IMPLEMENTED`/запрет публичного apply; тесты
внутренних модулей не должны включать production gate через extra-vars.

Локальное состояние: `/var/lib/kolla-host-firewall/` (root:root, 0700),
`owner.json`, `lock`, `transactions/<uuid>/journal.json`, отдельные снимки
runtime/permanent и точные байты собственного permanent XML для boot recovery.
Файлы 0600, без symlink; запись temporary → fsync → replace → fsync directory.
Helper и чистые модули: `/usr/local/libexec/kolla-host-firewall/`, root:root,
без импорта Python-кода из writable-директорий или рабочего каталога.

```text
SNAPSHOTTED → ARMED → RUNTIME_APPLIED → VERIFIED → PERSISTING → COMMITTED
                  \__________________________→ ROLLING_BACK → ROLLED_BACK
                                                       \→ RECOVERY_REQUIRED
```

Журнал: UUID, plan_id, boot_id, monotonic deadline, UTC deadline для отчёта,
state, owner-id, snapshot digests, pending API operation, ожидаемые до/после
fingerprints, результаты проверок с nonce и временем. Не хранить secrets,
SSH private keys, service tokens или полный вывод конфигурации.

## Task 0: сохранить проверенный prereq-report

**Files:** уже изменённые probe/model/tasks/template/README/tests добавки;
`docs/plans/2026-09-10-host-firewall-report.md`.

**Interfaces:** существующие `collect_snapshot()` и `build_report()` остаются
read-only. Не пересоздавать их заново и не удалять прежние tests.

- [ ] Проверить `git diff`, индекс и происхождение каждого изменённого файла;
  не включать чужие изменения или документы этого плана в prereq-коммит.
- [ ] Выполнить свежие тесты:

  ```bash
  python3 -m unittest discover -s integrations/kolla-ansible/host-firewall/tests -v
  python3 -m unittest discover -s tests -v
  git diff --check
  ```

  Ожидание исходного checkpoint: 54 addon tests, 7 repository tests, без SKIP
  теста наложения 0809. Иное количество сверить с diff, не подгонять тесты.
- [ ] Зафиксировать только перечисленные prereq-файлы коммитом
  `fix: report installed firewalld prerequisites without host mutations`.
  После commit проверить `git show --stat --oneline HEAD`.

## Task 1: схема плана, SSH и защита от дрейфа

**Files:** создать `ansible/module_utils/powerops_firewall_plan.py`,
`tests/test_plan.py`; изменить model и template report.

**Interfaces:** чистые функции, никаких Ansible/subprocess/import firewall:

```python
class PlanError(ValueError):
    pass

def canonical_digest(value: dict) -> str:
    import hashlib
    import json
    return hashlib.sha256(json.dumps(value, sort_keys=True,
                                    separators=(",", ":"),
                                    allow_nan=False).encode()).hexdigest()

def ssh_rules(port: int, extra_ports: list[int]) -> list[str]:
    ports = sorted(set([port, *extra_ports]))
    if any(type(p) is not int or not 1 <= p <= 65535 for p in ports):
        raise PlanError("SSH_PORT_UNRESOLVED")
    return [f'rule priority="-30000" port port="{p}" protocol="tcp" accept'
            for p in ports]
```

Также определить `compile_plan(projections: dict, catalog: dict,
observations: dict, profile: dict) -> dict` и
`validate_plan(plan: dict, current: dict) -> list[dict]`.
Ошибка возвращается только с code/subject, без сырого невалидного значения.

- [ ] Создать failing tests с импортом нового модуля через importlib по
  фиксированному пути, как в `tests/test_model.py`:

  ```python
  rules = module.ssh_rules(2222, [])
  self.assertEqual(['rule priority="-30000" port port="2222" protocol="tcp" accept'], rules)
  self.assertTrue(all('source ' not in rule and 'family=' not in rule for rule in rules))
  self.assertRaises(module.PlanError, module.ssh_rules, True, [])
  self.assertNotEqual(module.canonical_digest({'port': 22}),
                      module.canonical_digest({'port': 2222}))
  ```

  Добавить случаи IPv6 CIDR, null/строка вместо ports list, конфликт источников,
  смена selection/catalog/check timeout, сравнение runtime отдельно от permanent.
- [ ] Запустить `python3 -m unittest discover -s integrations/kolla-ansible/host-firewall/tests -p test_plan.py -v`;
  подтвердить RED из-за отсутствия контракта.
- [ ] Реализовать схему, валидацию strict types, детерминированное упорядочивание,
  fingerprint и SSH rules. Для значений inventory сначала вызвать существующий
  `valid_port()`, затем передавать int; boolean никогда не число порта.
- [ ] Повторить тесты до GREEN; проверить, что telemetry counter change не
  меняет configuration digest, а rule order при значимом порядке меняет.
- [ ] Commit файлов задачи: `feat: define firewall plan identity and mandatory SSH rules`.

## Task 2: проекция сетей, effective config и профиль покрытия

**Files:** изменить action/model/probe; создать `tests/test_catalog.py`,
`ansible/roles/host-firewall/vars/profiles.yml`; расширить playbook fixtures.

**Interfaces:** `project()` добавляет `network_addresses` для api/storage/
migration/tunnel/ironic_http/ironic_tftp, `drivers`, `effective_settings`,
`service_sources`, `verification_sources`. `effective_settings` — только
разрешённые несекретные ключи конфигурации, с origin/hash, не полные файлы.
`classify_flags(flags: dict, catalog: dict) -> list[dict]` в plan module
возвращает blockers для неизвестных/непокрытых включённых возможностей.

- [ ] Написать RED тесты: lookup в постороннем password var никогда не
  выполняется; override migration address принимается только если наблюдался;
  отсутствующий peer под `--limit` даёт blocker, не source any. Пример контракта:

  ```python
  catalog = {'flag_classes': {'enable_openstack_core': {
      'kind': 'selector', 'requires': ['enable_nova', 'enable_neutron']}}}
  blockers = module.classify_flags({'enable_unknown_service': True}, catalog)
  self.assertEqual([{'code': 'UNKNOWN_ENABLED_FLAG',
                     'subject': 'enable_unknown_service'}], blockers)
  ```

- [ ] Запустить test_catalog и test_playbook, зафиксировать конкретные RED.
- [ ] Проецировать поля individually через существующий resolver
  `disable_lookups=True`; не шаблонизировать service dict/consul_networks целиком.
  Каждое значение порта/адреса сохраняет `source_key` и результат проверки.
  Классы flags: `service`, `selector`, `feature`, `non_network`, `unsupported`;
  каждое non_network-исключение требует ссылки на 0809, не wildcard exemption.
- [ ] В read-only probe добавить allowlisted INI/HCL/network поля из реально
  смонтированной конфигурации (путь выводится из `node_config_directory` и
  проверенного имени контейнера). Не читать secrets/driver_info/transport_url;
  ограничить размер, запрещать symlink/выход из выбранного config root.
  Неопределённый override или неизвестный способ mount → CONFIG_UNRESOLVED.
- [ ] Проверить RED→GREEN и regression test secrets; создать пустой по
  runtime-квалификации profiles.yml, где нет автоматически разрешённого apply.
- [ ] Commit: `feat: project effective network settings with explicit coverage gates`.

## Task 3: каталог сервисов — четыре проверяемых приращения

**Files:** catalog.yml, profiles.yml, tests/test_catalog.py;
создать `docs/FIREWALL-CATALOG-0809.md` внутри добавки.

**Interfaces:** flow содержит `id`, `enable_condition`, `protocol`,
`port_key` или `protocol_number`, `destination_group`, `destination_network`,
`source_groups`/`external_source_key`, `evidence`, `checks`.
Порт — int или включительный диапазон `[first, last]`; одновременно порт
и protocol_number запрещены. `-1` выключает listener только там, где такое
значение документировано ролью (например, Consul DNS), а не для любых портов.
`resolve_flows(host: str, projection: dict, catalog: dict) -> dict` возвращает
`flows` и `blockers`; `compile_plan` использует именно этот контракт.
Каталог `requirements` — список полей `id`, `destination_group`,
`effective_key`, `error_code`: проверяются даже при пустом списке flows.
Функция `listener_port(value: object, *, disabled_value: int | None = None)
-> int | None` возвращает None только для явно разрешённого sentinel,
иначе валидирует порт или выбрасывает PlanError.

Для каждого из четырёх приращений провести отдельный RED→GREEN→commit цикл.
Не маркировать сервис `complete` из наличия одного API-порта.

### 3A. API, DB/RPC и координация

- [ ] Добавить тест на существующий Mistral backend + внутренний VIP frontend,
  а также независимые DB/RPC порты, без чтения URL с паролем:

  ```python
  projection = {'ports': {'mistral_api_listen_port': 18989},
                'network_addresses': {'node-a': {'api': '192.0.2.3'},
                                      'lb': {'api': '192.0.2.2'}},
                'groups': {'mistral-api': ['node-a'], 'loadbalancer': ['lb']},
                'enabled_flags': {'enable_mistral': True},
                'conditions': {}, 'service_sources': {}}
  catalog = {'flows': [{'id': 'mistral-backend', 'enable_condition': 'enable_mistral',
      'protocol': 'tcp', 'port_key': 'mistral_api_listen_port',
      'destination_group': 'mistral-api', 'destination_network': 'api',
      'source_groups': ['loadbalancer'], 'evidence': '0809:mistral/defaults',
      'checks': ['tcp-connect']}]}
  result = module.resolve_flows('node-a', projection, catalog)
  self.assertEqual(18989, result['flows'][0]['port'])
  self.assertEqual(['192.0.2.2/32'], result['flows'][0]['sources'])
  ```

- [ ] Запустить test_catalog до добавления resolver/entries, получить RED.
- [ ] Добавить связи Keystone, Placement, Glance, Nova, Neutron, Cinder,
  Horizon, Mistral, Masakari, Ironic; HAProxy frontend/backend отдельно.
  Добавить MariaDB/Galera/clustercheck, RabbitMQ client/inter-node/EPMD,
  Memcached, etcd, Redis/Sentinel при включении. Источник каждой связи —
  `0809 ansible/group_vars/all.yml` + defaults/templates соответствующей роли.
  TLS порты и single frontend определять по effective vars, не списком defaults.
- [ ] GREEN + negative missing external CIDRs; commit `feat: catalog API and control-plane firewall flows`.

### 3B. Nova, Neutron и storage

- [ ] RED cases: изменение migration network не открывает api network;
  libvirt TLS выбирает effective `nova_libvirt_port`; невыясненный диапазон
  QEMU migration блокирует compute, даже когда API каталог полон.

  ```python
  projection = {'groups': {'compute': ['node-a']},
                'enabled_flags': {'enable_nova': True},
                'drivers': {'nova_compute_virt_type': 'kvm'},
                'effective_settings': {'qemu_migration_ports': None},
                'ports': {}, 'network_addresses': {}, 'conditions': {},
                'service_sources': {}}
  catalog = {'flows': [], 'requirements': [{
      'id': 'qemu-migration-range', 'destination_group': 'compute',
      'effective_key': 'qemu_migration_ports',
      'error_code': 'MIGRATION_RANGE_UNRESOLVED'}]}
  self.assertIn('MIGRATION_RANGE_UNRESOLVED',
                {item['code'] for item in module.resolve_flows('node-a', projection, catalog)['blockers']})
  ```

- [ ] Запустить test_catalog; затем добавить libvirt control/migration data,
  nova-ssh/console proxy-to-compute, metadata path, OVS/OVN/VXLAN/Geneve/GRE
  только для выбранных драйверов, DHCP и разрешённые IP protocols.
  Источники: `roles/nova-cell/templates/libvirtd.conf.j2`,
  `nova.conf.d/libvirt.conf.j2`, neutron/openvswitch/ovn-* templates.
  Диапазон миграции читать из effective qemu/libvirt config или подтверждённой
  версии зависимости; при отсутствии доказательства не подставлять диапазон.
- [ ] Для storage отличать клиентские исходящие соединения от локальных
  listeners: NFSv4, NFSv3/RPC callbacks, iSCSI, Ceph и внешние drivers не
  превращаются в один общий allow. Неизвестный backend остаётся unsupported.
- [ ] GREEN с driver matrix и source restrictions; commit `feat: catalog compute network and storage dependencies`.

### 3C. PowerOps, Consul и FRR

- [ ] RED: Consul HTTP localhost не открывается удалённо, отключённый DNS
  `-1` не ошибка generic port; storage gossip не заменяется management адресами.
  Значение отключённого сервиса проверять до вызова `valid_port`:

  ```python
  self.assertIsNone(module.listener_port(-1, disabled_value=-1))
  self.assertEqual(8301, module.listener_port(8301, disabled_value=-1))
  self.assertRaises(module.PlanError, module.listener_port, -1)
  self.assertRaises(module.PlanError, module.listener_port, True)
  ```

- [ ] Запустить test_catalog; добавить per-network Consul server/client
  RPC и gossip TCP/UDP с server groups, client groups, extra groups и
  per-host enabled из фактической логики роли `consul/tasks/main.yml`.
  Сравнить также precheck, не считать комментарий про autodetection кодом.
  Токены ACL и gossip keys не проецировать.
- [ ] Добавить FRR BGP mesh/uplinks из `loadbalancer/templates/frr/frr.conf.j2`,
  VRRP только при keepalived. BFD не открывать из предположения, что любой FRR
  его использует. Ironic: provisioning HTTP/TFTP/DHCP только при включённых
  listeners; исходящий Redfish/BMC не требует входящего TCP/443 на conductor.
- [ ] GREEN и проверка HA-critical checks в профиле; commit `feat: catalog PowerOps Consul and routing dependencies`.

### 3D. Observability и полнота активного профиля

- [ ] RED: неизвестный exporter и enabled service без dependency coverage
  блокируют apply; присутствие всех известных sockets не доказывает полноту.

  ```python
  blockers = module.classify_flags({'enable_new_exporter': True},
                                   {'flag_classes': {}})
  self.assertEqual('UNKNOWN_ENABLED_FLAG', blockers[0]['code'])
  ```

- [ ] Добавить источники/порты Prometheus exporters, scrape endpoints,
  Alertmanager clustering, Grafana, Fluentd/syslog, OpenSearch и включённых
  monitoring services по их ролям. Сверить все `enable_*` базы с classification
  manifest; для иных OpenStack-сервисов явно указать unsupported, пока нет
  их полной матрицы. Не включать `complete` целиком всей базе Kolla.
- [ ] Проверить профили с раздельными/совмещёнными сетями, TLS, IPv6,
  external API и переопределёнными портами. В doc catalog записать для каждого
  семейства файлы evidence, покрытые режимы и сохраняющиеся blockers.
- [ ] GREEN; commit `feat: complete selected firewall profile coverage and expose unsupported modes`.

## Task 4: firewalld adapter и компиляция собственной policy

**Files:** новый firewalld module_utils, tests/test_adapter.py;
расширить plan compiler и profiles.yml.

**Interfaces:** `FirewalldAdapter` с методами `inspect() -> dict`,
`snapshot() -> dict`, `prepare_empty() -> dict`,
`replace_runtime(rules: list[str]) -> dict`,
`replace_permanent(rules: list[str]) -> dict`, `restore(snapshot: dict) -> dict`.
Constructor принимает bus и timeout; import bindings отложен до remote вызова.
Внутренний helper `_update_runtime_rules(policy_bus, rules: list[str],
timeout: int) -> None` выполняет один D-Bus вызов после guards адаптера.
`inspect` включает backend, version, capabilities, policy ownership evidence,
все значимые чужие правила и активность policy.

- [ ] Создать RED contract tests с autospec/fake D-Bus интерфейсом версии
  1.3.4, а не arbitrary Mock, принимающим любые методы/аргументы:

  ```python
  class PolicyBus134:
      def __init__(self):
          self.calls = []
      def setPolicySettings(self, policy, settings, *, timeout):
          self.calls.append((policy, settings, timeout))

  bus = PolicyBus134()
  module._update_runtime_rules(bus, [], timeout=5)
  self.assertEqual(('kolla-host-input', {'rich_rules': []}, 5), bus.calls[0])
  # Адаптер проверяется через этот узкий интерфейс; лишний positional
  # timeout из newer API должен вызывать TypeError в negative test.
  ```

- [ ] Запустить test_adapter и test_plan, увидеть RED на отсутствии адаптера.
- [ ] Реализовать direct D-Bus вызовы с typed dict/list и bounded timeout.
  В 1.3.4 `policy.setPolicySettings` получает имя и settings; keyword timeout
  транспорта не является третьим аргументом метода. Runtime меняет только
  `rich_rules`; immutable fields проверяются, не передаются для изменения.
  Permanent: `config.getPolicyByName` → `config.policy.getSettings/update`.
- [ ] Компилировать policy priority `-500`, SSH rich priority `-30000`,
  системные протоколы `-29000`, service allows `-20000`, final drop `30000`.
  Rule numbers — контракт этого профиля, не произвольные user overrides.
  Разрешить служебный ICMP/IPv6 ND; особенности DHCP/VRRP/GRE из каталога.
  Проверить реальный `Rich_Rule` parser и наличие baseline established/loopback
  правил перед разрешением ограничительного профиля.
- [ ] Проверить missing/foreign same-name policy, чужой early accept/drop,
  priority collision, reload drift, D-Bus restart и partial API success.
  По имени без owner.json не усыновлять объект; неизвестное поле не удалять.
  После любой записи перечитывать; не считать вызов атомарным.
- [ ] GREEN; commit `feat: add version-scoped firewalld policy adapter`.

## Task 5: durable transaction и независимый rollback

**Files:** transaction module_utils, helper CLI, tests/test_transaction.py,
tests/transaction_fixtures.py.

**Interfaces:** `TransactionManager(root, adapter, clock, supervisor)`;
`begin(plan: dict) -> dict`, `apply_runtime(txid: str) -> dict`,
`verify(txid: str, evidence: dict) -> dict`, `commit(txid: str) -> dict`,
`rollback(txid: str) -> dict`, `recover_boot() -> dict`, `status() -> dict`.
Clock: `monotonic()`, `utc()`, `boot_id()`; supervisor: `arm(txid, seconds)`,
`is_armed(txid)`, `disarm(txid)`. Fixture `make_transaction(root)` возвращает
manager, clock, adapter, supervisor; fake clock имеет `advance(seconds)`.
CLI actions: inspect, begin, apply-runtime, verify, commit, rollback,
recover-boot, recover-expired, status. Вход JSON stdin, не shell string.

- [ ] RED тест deadline и controller loss:

  ```python
  with tempfile.TemporaryDirectory() as root:
      manager, clock, adapter, supervisor = make_transaction(root)
      before = adapter.snapshot()
      txn = manager.begin({'plan_id': 'a' * 64, 'rollback_timeout': 300,
                           'rules': ['rule priority="30000" drop']})
      self.assertTrue(supervisor.is_armed(txn['id']))
      manager.apply_runtime(txn['id'])
      clock.advance(301)
      manager.rollback(txn['id'])
      self.assertEqual(before, adapter.snapshot())
      self.assertEqual('ROLLED_BACK', manager.status()['state'])
  ```

  Тестовая минимальная policy для transaction unit tests не проходит через
  production admission; production plan обязательно имеет SSH и полную матрицу.
- [ ] Запустить test_transaction RED; затем реализовать файловую машину
  состояний с flock, O_NOFOLLOW, root ownership, пределом JSON 4 MiB,
  UUID path validation и атомарной записью. Lock не удерживается во время
  ожидания controller, только при коротких переходах/ограниченных API calls.
- [ ] Перед каждым API изменением fsync write-ahead запись ожидаемых до/после
  состояний. Различать свой известный частичный результат и чужой drift.
  Для перезапуска после kill перечитать API и разрешить только записанные
  fingerprints/документированное промежуточное множество правил.
  Неизвестный результат → RECOVERY_REQUIRED, без перезаписи чужих правил.
- [ ] Проверить concurrency двумя процессами, kill после каждого durable
  шага, timeout во время permanent, stale txid, path traversal, symlink,
  disk full/fsync error, задвоенный rollback, новый boot_id и смену времени UTC.
  Commit: lock → deadline/evidence check → PERSISTING → permanent readback
  → durable COMMITTED → disarm. Timer после COMMITTED делает no-op.
- [ ] GREEN; commit `feat: add crash-aware local firewall transactions and rollback`.

## Task 6: первоначальная подготовка и systemd recovery

**Files:** tasks/prepare.yml; helper; templates
`kolla-host-firewall-recover.service.j2`,
`kolla-host-firewall-watchdog.service.j2`,
`kolla-host-firewall-watchdog.timer.j2`,
`firewalld-recovery-dependency.conf.j2`; tests/test_transaction.py и test_apply.py.

**Interfaces:** prepare создаёт только своё empty policy/owner record/helper/
служебные units; возвращает `prepared: true, restrictive_apply: false`.
Timer выполняет `recover-expired` каждые 2 секунды; `begin` требует подтверждения,
что timer активен и helper способен читать журнал. Timer не зависит от SSH.

- [ ] RED: без initialize подготовка ничего не создаёт; без allow_initial_reload
  не вызывает reload. При active transaction повторная подготовка запрещена.

  ```python
  result = self.run_play('host-firewall.yml', {
      'host_firewall_mode': 'apply', 'host_firewall_initialize': False})
  self.assertNotEqual(0, result.returncode)
  self.assertFalse((self.base / 'mutation-called').exists())
  ```

- [ ] Запустить test_apply RED; реализовать initial preflight с runtime/permanent
  drift и foreign owners. `initialize=true` завершает только подготовку, даже
  если передан plan_id. При необходимости reload требуются оба флага; после
  reload выполнить свежий SSH и проверить foreign rules/own empty runtime.
- [ ] Установить собственный boot recovery unit до firewalld:

  ```ini
  [Unit]
  Description=Recover unfinished Kolla host firewall transaction
  DefaultDependencies=no
  After=local-fs.target
  Before=firewalld.service network-pre.target
  RequiresMountsFor=/var/lib/kolla-host-firewall /usr/local/libexec/kolla-host-firewall
  [Service]
  Type=oneshot
  ExecStart=/usr/bin/python3 /usr/local/libexec/kolla-host-firewall/powerops_firewall_helper.py recover-boot
  ```

  Собственный drop-in firewalld содержит `Requires=` и `After=` этого unit;
  не заменяет vendor unit и не стартует/enable firewalld. `daemon-reload`
  относится только к подготовке своих units, не firewall reload.
  Проверить отсутствие циклов через `systemd-analyze verify` на Linux.
- [ ] При новом boot_id и unfinished journal восстановить **только свой**
  exact permanent XML до запуска firewalld: проверить owner, digest текущего
  известного candidate и сохранённого snapshot, replace/fsync, сохранить
  SELinux context. Это восстановление конфигурации firewalld, не nft rules.
  В этой фазе D-Bus autoactivation запрещена. После старта firewalld runtime
  выводится из восстановленного permanent; прежний runtime-only drift через
  reboot не обещается сохранить. Boot recovery при уже работающем daemon
  не пишет XML в обход него — используется online recovery.
- [ ] Проверить rollback подготовки: собственный permanent object удаляется
  только при подтверждённом owner; если потребуется reload, его допуск должен
  быть получен до начала. Не откатывать весь foreign ruleset.
- [ ] GREEN и отдельный Linux boot gate; commit `feat: prepare owned policy and install independent recovery units`.

## Task 7: новые соединения и доказательства проверки

**Files:** checks module_utils, action_plugins/powerops_firewall_verify.py,
tests/test_checks.py; profiles.yml.

**Interfaces:** `run_check(check: dict, timeout: int) -> dict` принимает
тип `tcp`, `http`, `consul`, `bgp`, `openstack-service` из фиксированного
реестра. `verify_evidence(required: list[dict], results: list[dict],
txid: str, plan_id: str, nonce: str) -> list[dict]` возвращает blockers.
Check имеет id, source_host, destination, protocol, expected_result и
read-only endpoint; нет поля произвольной shell command.

- [ ] RED: tcp connect success не удовлетворяет consul membership check;
  старый nonce, пропущенная IPv6 проверка или исключённый source блокируют commit.

  ```python
  required = [{'id': 'consul-membership', 'type': 'consul'}]
  results = [{'id': 'consul-membership', 'type': 'tcp', 'ok': True}]
  blockers = module.verify_evidence(required, results, 'txn', 'plan', 'nonce')
  self.assertTrue(blockers)
  ```

- [ ] Запустить test_checks RED; реализовать bounded runners, status-only
  результаты без token/body/password. Требовать positive до apply и после,
  negative only после apply, и предыдущее доказательство работоспособности
  тестового endpoint: timeout к несуществующему listener не доказывает deny.
- [ ] Для свежего SSH использовать новый OpenSSH процесс с argv (не shell),
  `ControlMaster=no`, `ControlPath=none`, `BatchMode=yes`,
  `StrictHostKeyChecking=yes`, фактическими user/port/identity из проверенного
  подключения. Не отключать host-key checking и не менять known_hosts.
  Команда — только helper status с одноразовым nonce; stderr не выводит ключи.
  Неподдерживаемый connection plugin, неизвестный ProxyCommand/Jump transport
  или несовпавший effective ssh port → SSH_TRANSPORT_UNSUPPORTED до изменения.
- [ ] Включить health checks нужного профиля: Consul memberships по сетям,
  Nova/Masakari states, FRR peer state если включён, API/DB/RPC доступность.
  Не запускать миграцию, fencing, power actions или рестарты как health check;
  миграция/UDP data plane проверяются в отдельной квалификации профиля.
- [ ] GREEN; commit `feat: verify fresh SSH and profile-specific service connectivity`.

## Task 8: Ansible orchestration, manual rollback и идемпотентность

**Files:** host-firewall.yml, role main/report/apply/rollback/defaults;
library/powerops_firewall_transaction.py; tests/test_apply.py/test_playbook.py;
README.md и report template.

**Interfaces:** playbook имеет общий read-only сбор с `strategy: linear`,
затем mutation play с `serial: 1`, `any_errors_fatal: true`, без run_once,
который незаметно выполняется заново в каждом batch. Все selected peers
проецируются до mutation play; ни один excluded host не становится delegate.
Module actions соответствуют helper CLI из Task 5, принимает типизированный
JSON и самостоятельно перепроверяет plan/owner/generation.

- [ ] RED Ansible tests: second host не изменён после failure первого;
  --check/--tags/--start-at-task не обходят helper admission;
  несуществующий plan и stale report не создают timer/journal;
  повторный подтверждённый apply — changed=false.

  ```python
  result = self.run_play('host-firewall.yml',
                         {'host_firewall_mode': 'apply'}, options=('--check',))
  self.assertFalse((self.base / 'mutation-called').exists())
  self.assertNotIn('SECRET_MUST_NOT_APPEAR', result.stdout)
  ```

- [ ] Запустить test_apply RED; перенести существующие report tasks без
  изменения их privacy/selection semantics. В mutation facade:

  ```python
  if module.check_mode:
      module.exit_json(changed=False, simulation_only=True)
  # Только после этой границы: schema/plan/owner checks и helper operation.
  ```

  Validation не доверяет extra-var `preflight_passed`; helper требует локальное
  состояние текущей транзакции. Прямой вызов commit без begin/verify отвергается.
- [ ] Подключить prepare → fresh report → apply workflow; отсутствие policy
  в ordinary apply — понятная ошибка, не скрытый reload. В apply: preflight и
  pre-SSH → begin/arm → runtime → post-SSH/service checks → verify → commit.
  Rescue пробует rollback, но не снимает timer при failed/unreachable.
- [ ] Добавить manual rollback по UUID с readback обеих областей; preflight
  rollback проверяет snapshot/owner/API, но **не требует полной текущей матрицы
  сервисов**, иначе он не сможет исправить ошибочный новый каталог.
  Старый rollback после более новой committed txn отвергается как stale.
- [ ] GREEN Ansible tests с test-only заменой OS/helper boundaries; никаких
  переменных bypass в production. До Task 9 публичный apply всё ещё закрыт.
- [ ] Commit `feat: orchestrate guarded serial firewall apply and rollback`.

## Task 9: Linux qualification, снятие delivery gate и handoff

**Files:** tests/linux/README.md, tests/linux/verify.yml, profiles.yml;
test_baseline.py/test_apply.py, README.md,
`docs/adr/0002-host-firewall.md` и этот план.

**Interfaces:** Linux suite получает отдельный disposable inventory и явный
`host_firewall_test_disposable: true`, не содержит адресов Ultra. Нельзя
запускать её на обычном baremetal inventory. Runtime qualification artifact
содержит OS/firewalld/RPM release, backend, package hashes, profile, результаты
и собственные изменения; не является переключателем игнорирования blockers.

- [ ] Создать failing acceptance assertions для empty prepare → apply →
  commit → no-op → manual rollback и отказов:

  ```yaml
  - name: Assert transaction completed and independent rules survived
    ansible.builtin.assert:
      that:
        - test_result.state == 'COMMITTED'
        - test_result.foreign_before == test_result.foreign_after
        - test_result.fresh_ssh_ipv4
        - test_result.fresh_ssh_ipv6
        - test_result.disallowed_probe_blocked
        - test_result.permanent_matches_runtime
  ```

- [ ] Выполнить Linux matrix: firewalld 1.3.4 upstream и отдельно целевой
  RPM release SberLinux; IPv4/IPv6, DHCP/ICMP/ND, реальные version-scoped
  D-Bus signatures, foreign policies, NAT/VM traffic, rebuild connections,
  controller kill, helper kill, reload, reboot при PERSISTING,
  commit-vs-watchdog race, negative probe и rollback после потери SSH.
  Проверить, что units/recovery доступны после выхода Ansible и перезагрузки.
- [ ] На изолированном OpenStack-профиле отдельно проверить migration,
  Consul membership и FRR; TCP probe не заменяет этот этап. Если такого
  ресурса нет, записать «не проверено», оставить соответствующий profile
  неподдерживаемым и не объявлять production readiness.
- [ ] Только после успешного Linux/profile gate разрешить публичный apply
  для проверенного сочетания. Не создавать переключатель `force`,
  `skip_verification` или user-controlled `profile_tested=true`.
  Неизвестная версия/RPM release/driver продолжает блокироваться.
- [ ] Запустить полный regression и exact overlay:

  ```bash
  python3 -m unittest discover -s integrations/kolla-ansible/host-firewall/tests -v
  python3 -m unittest discover -s tests -v
  git diff --check
  ```

  Тест exact archive не должен SKIP; свежие файлы 0809 после наложения
  должны остаться побайтно прежними. Обновить README: точные команды без
  environment variables, setup/reload отдельно, outputs и ограничения,
  диагностика owner/journal/timer, ручной rollback по UUID.
- [ ] Независимый code review перед допуском изменений; исправить Critical/
  Important findings, повторить затронутые проверки. Для review использовать
  `superpowers:requesting-code-review`, не запускать subagent без предусмотренного
  выбранным workflow основания.
- [ ] Commit `feat: qualify firewalld apply profile and document verified boundaries`.
  Push или стендовый apply — только по отдельному запросу пользователя.

## Покрытие требований дизайна

| Раздел дизайна | Задачи / проверяемый результат |
| --- | --- |
| 1: modes, check, границы INPUT и backend | 0, 4, 8, 9 |
| 2: SSH any, реальный порт и новый доступ | 1, 2, 7, 8 |
| 3: policy ownership и чужие правила | 4, 5, 6, 9 |
| 4: отдельная подготовка и явный reload | 6, 8 |
| 5: полнота матрицы и drift | 1, 2, 3A–3D, 9 |
| 6: serial runtime → verify → permanent | 5, 7, 8 |
| 7: deadline, concurrency, reboot, manual rollback | 5, 6, 8, 9 |
| 8: Linux/API/source proof отдельно от fixtures | 0, 4, 9 |

## Проверенные исходники и справка для реализации

- В 0809: `ansible/group_vars/all.yml`, defaults/templates ролей,
  `roles/consul/tasks/main.yml`, `roles/consul/tasks/precheck.yml`,
  `roles/loadbalancer/templates/frr/frr.conf.j2`,
  `roles/nova-cell/templates/libvirtd.conf.j2`.
- [Firewalld 1.3.4 client](https://github.com/firewalld/firewalld/blob/v1.3.4/src/firewall/client.py)
  и [D-Bus server](https://github.com/firewalld/firewalld/blob/v1.3.4/src/firewall/server/firewalld.py):
  контракты целевой версии, не mutable latest docs.
- [Runtime policy update в 1.3.4](https://github.com/firewalld/firewalld/blob/v1.3.4/src/firewall/core/fw_policy.py):
  обновление набора настроек включает последовательные операции; readback и
  журнал нужны даже при одном высокоуровневом вызове.
- [Rich language](https://firewalld.org/documentation/man-pages/firewalld.richlanguage.html):
  rule без family относится к IPv4/IPv6; source/destination требуют family;
  приоритеты rich rules не эквивалентны приоритетам policy.
- [Kolla 2025.1 firewalld](https://docs.openstack.org/kolla-ansible/2025.1/user/security.html#firewalld):
  существующее управление external API не считать полным host firewall.

## Статус этого документа

Это план, не свидетельство написанного apply или успешного стендового запуска.
Согласование дизайна позволяет выполнять задачи кода по порядку; не разрешает
сетевые изменения на Ultra. Каждый этап заканчивается тестами и checkpoint,
а не обещанием, что весь firewall уже готов.
