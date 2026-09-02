# Horizon PowerOps Image, Kolla and Delivery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Package the PowerOps dashboard and compatible Mistral components into OpenStack 2025.1 images, configure them through Kolla-Ansible, verify cross-repository contracts, and publish a separate Russian operations guide.

**Architecture:** Kolla learns two opt-in local plugin sources: the Horizon package and patched `mistral-lib`; Kolla-Ansible selects the resulting images only when PowerOps is enabled. The deployment layer renders one region and the same two allowlists into Horizon and Mistral, creates only the Keystone role object, and performs read-only registration/import checks after container start. Root contract tests tie all component names, schemas and safety gates together before delivery hashes are updated.

**Tech Stack:** Kolla stable/2025.1, Kolla-Ansible stable/2025.1 fork, Jinja2/Ansible, Docker-compatible image builds, Keystone `openstack.cloud.identity_role`, Python `unittest`, Git format-patch, SHA-256, Russian Markdown runbook.

**Spec:** `docs/superpowers/specs/2026-09-02-horizon-powerops-integration-design.md`

## Global Constraints

- Execute plans in this order: `mistral-lib`, Mistral, `powerops-dashboard`, then this integration plan.
- Pin Kolla baseline `d14cef9bbafa0db561abfb0c0299d1d6bbbf8f0c` from `stable/2025.1`.
- Continue Kolla-Ansible from completed commit `63a8d0f597f9034a42f2e1b0bd415f1746d33b8d` in `work/kolla-ansible`.
- Enable the PowerOps dashboard only when Horizon, Mistral and PowerOps are all enabled; keep the standard Mistral dashboard independent.
- Use one `openstack_region_name` for Mistral backend and Horizon display; do not add region workflow input or cross-region logic.
- Render the same `powerops_allowed_project_names` and `powerops_allowed_user_names` variables to Mistral and Horizon.
- Defaults remain `['{{ openstack_auth.project_name }}']` and `['{{ openstack_auth.username }}']`; empty lists are valid and disable only delegated access.
- Validate lists as unique non-empty trimmed strings when elements exist; commas remain forbidden because Mistral `ListOpt` uses comma serialization.
- Idempotently create the exact Keystone role `powerops_operator`; never assign it automatically and never create an implied-role relation.
- Patched Mistral API, Engine and Executor images must contain patched Mistral and patched `mistral-lib`; Event Engine may remain vanilla.
- The Horizon image must contain `powerops-dashboard`; activation is controlled by `ENABLE_POWEROPS`.
- Deploy/reconfigure may populate actions, reconcile workbook and inspect imports/definitions but may not start/resume a workflow or mutate Nova, Masakari, Ironic, etcd host locks, VMs or physical power.
- Local mock preview remains the first visual gate. A test-cloud connection begins read-only and requires separate approval; any deployment, restart or workflow/power/VM mutation requires another explicit approval.
- Export one Kolla patch and two new Kolla-Ansible patches; preserve all existing patch bytes.
- Publish `POWEROPS_HORIZON_OPERATIONS.md` as a separate Russian document referencing `OPERATIONS.md`.

---

### Task 1: Teach Kolla to package and activate the two local sources

**Files:**
- Create during execution: `sources/kolla/`
- Create during execution: `worktrees/kolla-powerops/`
- Modify: `worktrees/kolla-powerops/kolla/common/sources.py`
- Modify: `worktrees/kolla-powerops/docker/horizon/extend_start.sh`
- Create: `worktrees/kolla-powerops/kolla/tests/test_powerops_plugins.py`
- Create: `build/kolla-build.conf`
- Create: `patches/kolla/0001-feat-package-PowerOps-Horizon-and-Mistral-components.patch`

**Interfaces:**
- Produces source section: `horizon-plugin-powerops-dashboard`.
- Produces source section: `mistral-base-plugin-mistral-lib`.
- Produces environment gate: `ENABLE_POWEROPS=yes|no`.
- Consumes local sources relative to Kolla `--locals-base`.

- [ ] **Step 1: Create and verify the pinned Kolla worktree**

```bash
git clone https://opendev.org/openstack/kolla.git sources/kolla
git -C sources/kolla rev-parse d14cef9bbafa0db561abfb0c0299d1d6bbbf8f0c^{commit}
git -C sources/kolla worktree add \
  -b powerops/horizon-image \
  ../../worktrees/kolla-powerops \
  d14cef9bbafa0db561abfb0c0299d1d6bbbf8f0c
```

Expected: the exact baseline resolves and the worktree is clean.

- [ ] **Step 2: Write failing Kolla source/activation tests**

Assert `SOURCES` contains both exact keys with `enabled=False`, `type` set
to `local`, and locations:

```text
$locals_base/powerops-dashboard
$locals_base/worktrees/mistral-lib-powerops
```

Use Kolla's plugin-parent parser to prove the first source attaches to the
`horizon` image and the second to `mistral-base`. Inspect
`docker/horizon/extend_start.sh` and assert it passes
`${ENABLE_POWEROPS:-no}` through `config_dashboard` from
`${SITE_PACKAGES}/poweropsdashboard/enabled/_50_powerops.py` to
`${SITE_PACKAGES}/openstack_dashboard/local/enabled/_50_powerops.py`, then
calls the function before static collection.

- [ ] **Step 3: Run and verify RED**

```bash
cd worktrees/kolla-powerops
python -m pytest -q kolla/tests/test_powerops_plugins.py
```

Expected: both source entries and activation function are absent.

- [ ] **Step 4: Add opt-in local source records**

Add to `SOURCES`:

```python
'horizon-plugin-powerops-dashboard': {
    'type': 'local',
    'location': '$locals_base/powerops-dashboard',
    'enabled': False,
},
'mistral-base-plugin-mistral-lib': {
    'type': 'local',
    'location': '$locals_base/worktrees/mistral-lib-powerops',
    'enabled': False,
},
```

The existing Horizon and Mistral-base Dockerfiles already install every item
from `plugins-archive`; do not add a network `pip install` or modify upper
constraints in container startup.

- [ ] **Step 5: Add Horizon runtime activation**

Add:

```bash
function config_powerops_dashboard {
    config_dashboard "${ENABLE_POWEROPS:-no}" \
        "${SITE_PACKAGES}/poweropsdashboard/enabled/_50_powerops.py" \
        "${SITE_PACKAGES}/openstack_dashboard/local/enabled/_50_powerops.py"
}
```

Call `config_powerops_dashboard` beside the existing Mistral dashboard call,
before `settings_changed`. Missing package behavior remains the existing
warning plus later Kolla-Ansible fail-closed import check.

- [ ] **Step 6: Add the local build configuration**

`build/kolla-build.conf` contains:

```ini
[DEFAULT]
namespace = powerops-local
tag = 2025.1-powerops

[horizon-plugin-powerops-dashboard]
type = local
location = $locals_base/powerops-dashboard
enabled = true

[mistral]
type = local
location = $locals_base/worktrees/mistral-powerops

[mistral-base-plugin-mistral-lib]
type = local
location = $locals_base/worktrees/mistral-lib-powerops
enabled = true
```

No credential, registry password or production registry hostname belongs in
this tracked file.

- [ ] **Step 7: Run Kolla checks and commit**

```bash
python -m pytest -q kolla/tests/test_powerops_plugins.py \
  kolla/tests/test_build.py
tox -e pep8 -- kolla/common/sources.py \
  kolla/tests/test_powerops_plugins.py
git add kolla/common/sources.py docker/horizon/extend_start.sh \
  kolla/tests/test_powerops_plugins.py
git commit -m "feat: package PowerOps Horizon and Mistral components"
```

Expected: plugin-parent and activation tests pass.

- [ ] **Step 8: Export and clean-apply the Kolla patch**

```bash
mkdir -p patches/kolla
git -C worktrees/kolla-powerops format-patch \
  --output-directory "$PWD/patches/kolla" \
  d14cef9bbafa0db561abfb0c0299d1d6bbbf8f0c..HEAD
git -C sources/kolla worktree add \
  /tmp/kolla-powerops-apply \
  d14cef9bbafa0db561abfb0c0299d1d6bbbf8f0c
git -C /tmp/kolla-powerops-apply am \
  "$PWD/patches/kolla/0001-feat-package-PowerOps-Horizon-and-Mistral-components.patch"
```

Expected: exactly one patch and clean application.

---

### Task 2: Render shared RBAC and image settings through Kolla-Ansible

**Files:**
- Modify: `work/kolla-ansible/ansible/group_vars/all.yml`
- Modify: `work/kolla-ansible/ansible/roles/horizon/defaults/main.yml`
- Modify: `work/kolla-ansible/ansible/roles/horizon/templates/_9998-kolla-settings.py.j2`
- Modify: `work/kolla-ansible/ansible/roles/horizon/tasks/precheck.yml`
- Modify: `work/kolla-ansible/ansible/roles/mistral/defaults/main.yml`
- Modify: `work/kolla-ansible/ansible/roles/mistral/tasks/register.yml`
- Modify: `work/kolla-ansible/ansible/roles/mistral/tasks/precheck.yml`
- Modify: `work/kolla-ansible/kolla_ansible/tests/unit/test_powerops_configuration_contract.py`
- Modify: `work/kolla-ansible/kolla_ansible/tests/unit/test_powerops_templates.py`

**Interfaces:**
- Produces: `enable_horizon_powerops` derived Boolean.
- Produces: `powerops_horizon_image`, `powerops_horizon_tag` and selected Horizon image.
- Produces Horizon settings: `POWEROPS_REGION_NAME`, `POWEROPS_ALLOWED_PROJECT_NAMES`, `POWEROPS_ALLOWED_USER_NAMES`, `POWEROPS_MOCK_MODE=False`.
- Produces: `mistral_ks_roles=['powerops_operator']` only when PowerOps is enabled.

- [ ] **Step 1: Write failing default/precheck tests**

Assert defaults retain the existing administrative identity lists and add:

```yaml
enable_horizon_powerops: >-
  {{ enable_horizon | bool and enable_mistral | bool and enable_powerops | bool }}
powerops_horizon_image: ""
powerops_horizon_tag: ""
```

Change malformed-value cases so empty allowlists pass, but these fail: scalar,
mapping, non-string element, whitespace-only element, leading/trailing
whitespace, comma-containing element and duplicate element. Assert the Horizon
image repository/tag are required only when `enable_horizon_powerops` is true.

- [ ] **Step 2: Write failing shared-template tests**

Render Mistral and Horizon templates from the same values and assert:

```python
self.assertEqual('RegionTwo', horizon['POWEROPS_REGION_NAME'])
self.assertEqual(
    ['ops-project', 'ha-project'],
    horizon['POWEROPS_ALLOWED_PROJECT_NAMES'],
)
self.assertEqual(
    ['ops-user', 'ha-user'],
    horizon['POWEROPS_ALLOWED_USER_NAMES'],
)
self.assertIs(False, horizon['POWEROPS_MOCK_MODE'])
self.assertEqual(
    'ops-project,ha-project',
    mistral['powerops']['allowed_project_names'],
)
```

Add empty-list rendering assertions: Horizon gets `[]` and Mistral gets an
empty `ListOpt` value without a synthetic admin entry.

- [ ] **Step 3: Write failing Keystone-role tests**

Parse `mistral/tasks/register.yml`. With PowerOps enabled, assert
`service_ks_register_roles` resolves to exactly `['powerops_operator']`; when
disabled, it resolves to `[]`. Assert `service_ks_register_user_roles` is not
set and no role-assignment module or implied-role operation was added.

- [ ] **Step 4: Run and verify RED**

```bash
cd work/kolla-ansible
python3 -m unittest \
  kolla_ansible.tests.unit.test_powerops_configuration_contract \
  kolla_ansible.tests.unit.test_powerops_templates -v
```

Expected: empty allowlists fail and Horizon/role settings are absent.

- [ ] **Step 5: Implement defaults and selected image**

Add the group variables above. In Horizon service defaults, use:

```yaml
image: >-
  {{ powerops_horizon_image ~ ':' ~ powerops_horizon_tag
     if enable_horizon_powerops | bool else horizon_image_full }}
environment:
  ENABLE_POWEROPS: "{{ 'yes' if enable_horizon_powerops | bool else 'no' }}"
```

Keep `ENABLE_MISTRAL` unchanged so generic Mistral dashboard activation remains
independent.

- [ ] **Step 6: Render exact Horizon settings**

Under `enable_horizon_powerops` in `_9998-kolla-settings.py.j2` render:

```jinja
POWEROPS_REGION_NAME = {{ openstack_region_name | to_json }}
POWEROPS_ALLOWED_PROJECT_NAMES = {{ powerops_allowed_project_names | to_json }}
POWEROPS_ALLOWED_USER_NAMES = {{ powerops_allowed_user_names | to_json }}
POWEROPS_MOCK_MODE = False
```

Do not render any password, BMC field, service token or Mistral service-account
credential.

- [ ] **Step 7: Create only the Keystone role object**

Add in Mistral defaults:

```yaml
mistral_ks_roles: >-
  {{ ['powerops_operator'] if enable_powerops | bool else [] }}
```

Pass it from `mistral/tasks/register.yml` as
`service_ks_register_roles: "{{ mistral_ks_roles }}"`. The existing generic
role service is idempotent and does not assign a standalone role list.

- [ ] **Step 8: Update prechecks and commit**

Remove only the two `length > 0` assertions for allowlist collections and add
for each:

```jinja
powerops_allowed_project_names | unique | list | length
== powerops_allowed_project_names | length
```

Add equivalent uniqueness for users and validate the Horizon image pair when
the derived enable flag is true.

```bash
python3 -m unittest \
  kolla_ansible.tests.unit.test_powerops_configuration_contract \
  kolla_ansible.tests.unit.test_powerops_templates -v
git add ansible/group_vars/all.yml ansible/roles/horizon \
  ansible/roles/mistral/defaults/main.yml \
  ansible/roles/mistral/tasks/register.yml \
  ansible/roles/mistral/tasks/precheck.yml \
  kolla_ansible/tests/unit/test_powerops_configuration_contract.py \
  kolla_ansible/tests/unit/test_powerops_templates.py
git commit -m "feat: configure Horizon PowerOps RBAC and image"
```

Expected: defaults, empty-list semantics, shared rendering and no-assignment
role creation pass. This becomes Kolla-Ansible patch `0006`.

---

### Task 3: Reconcile and validate the extended runtime contract

**Files:**
- Modify: `work/kolla-ansible/ansible/roles/mistral/files/power_ops.yaml`
- Modify: `work/kolla-ansible/ansible/roles/mistral/tasks/powerops.yml`
- Modify: `work/kolla-ansible/ansible/roles/horizon/tasks/deploy.yml`
- Create: `work/kolla-ansible/ansible/roles/horizon/tasks/powerops.yml`
- Modify: `work/kolla-ansible/kolla_ansible/tests/unit/test_powerops_registration.py`
- Create: `work/kolla-ansible/kolla_ansible/tests/unit/test_powerops_horizon.py`

**Interfaces:**
- Consumes exact Mistral action set of six and workflow set of five.
- Verifies patched `SecurityContext.user_id`, `SecurityContext.roles` and `ExecutionContext.workflow_resume_authorization` in API/Engine/Executor images.
- Verifies dashboard import/activation in the Horizon image.
- Preserves deploy/reconfigure non-mutation contract.

- [ ] **Step 1: Copy and prove the workbook is byte-identical**

```bash
cmp worktrees/mistral-powerops/etc/mistral/power_ops.yaml \
  work/kolla-ansible/ansible/roles/mistral/files/power_ops.yaml
```

Expected before copy: mismatch because `host_inventory` is absent from the
Kolla copy.

Copy the completed source workbook during implementation and rerun `cmp`.
Expected after copy: no output and exit zero.

- [ ] **Step 2: Write failing Mistral runtime-contract tests**

Update expected names to include `powerops.host_inventory` and
`power_ops.host_inventory`. Assert the entry-point import check runs in API,
Engine and Executor containers and a second read-only Python check imports
`mistral_lib.actions.context`, constructs both context classes, and asserts all
three new attributes exist.

Assert reconciliation still uses only action population plus workbook
GET/POST/PUT and exact action/workflow GETs. Explicitly reject execution
`POST`, execution `PUT`, `openstack workflow execution create`, Nova/Ironic
commands, Masakari notification calls and etcd mutation commands.

- [ ] **Step 3: Write failing Horizon post-start tests**

Assert `horizon/tasks/deploy.yml` imports `powerops.yml` after handler flush
under `enable_horizon_powerops | bool`. The task file must run exactly one
read-only container command that:

- imports `poweropsdashboard`, its enabled file and `dashboard.py`;
- checks installed distribution name `powerops-dashboard`;
- loads Django settings and compares one region plus both allowlists;
- confirms `_50_powerops.py` exists under Horizon local enabled files;
- performs no HTTP request and no workflow/action execution.

- [ ] **Step 4: Run and verify RED**

```bash
python3 -m unittest \
  kolla_ansible.tests.unit.test_powerops_registration \
  kolla_ansible.tests.unit.test_powerops_horizon -v
```

Expected: inventory names, context attributes and Horizon check are absent.

- [ ] **Step 5: Extend Mistral validation without mutations**

Change the required action set to:

```python
{
    'powerops.host_inventory',
    'powerops.host_power_status',
    'powerops.planned_power_off',
    'powerops.planned_reboot',
    'powerops.power_on_for_inspection',
    'powerops.return_to_service',
}
```

Add the five workflows to the existing exact per-name GET/owner validation.
Add a separate context import command in all three patched containers. It may
construct objects but may not create an action or workflow execution.

- [ ] **Step 6: Add Horizon post-start validation**

Import `powerops.yml` after handler flush. Run once on the first Horizon host
and use `changed_when: false`. The container Python command validates package,
enabled file, configured region and exact JSON-decoded allowlists; it must not
print tokens or settings wholesale.

- [ ] **Step 7: Run tests and commit**

```bash
python3 -m unittest \
  kolla_ansible.tests.unit.test_powerops_registration \
  kolla_ansible.tests.unit.test_powerops_horizon \
  kolla_ansible.tests.unit.test_powerops_configuration_contract \
  kolla_ansible.tests.unit.test_powerops_templates -v
git add ansible/roles/mistral/files/power_ops.yaml \
  ansible/roles/mistral/tasks/powerops.yml \
  ansible/roles/horizon/tasks/deploy.yml \
  ansible/roles/horizon/tasks/powerops.yml \
  kolla_ansible/tests/unit/test_powerops_registration.py \
  kolla_ansible/tests/unit/test_powerops_horizon.py
git commit -m "feat: validate Horizon PowerOps runtime contracts"
```

Expected: registration checks pass and this becomes Kolla-Ansible patch
`0007`.

- [ ] **Step 8: Export only the two new Kolla-Ansible patches**

```bash
git format-patch --numbered --start-number 6 \
  --output-directory "$PWD/../../patches/kolla-ansible" \
  63a8d0f597f9034a42f2e1b0bd415f1746d33b8d..HEAD
```

Expected: existing files `0001` through `0005` remain byte-identical and the
new files are `0006` and `0007`.

---

### Task 4: Extend executable cross-repository contracts

**Files:**
- Modify: `tests/test_cross_repository_contract.py`
- Modify: `tests/test_delivery_artifacts.py`
- Create: `tests/test_horizon_powerops_contract.py`

**Interfaces:**
- Consumes environment paths: `POWEROPS_MISTRAL_LIB_TREE`, `POWEROPS_MISTRAL_TREE`, `POWEROPS_DASHBOARD_TREE`, `POWEROPS_KOLLA_TREE`, `POWEROPS_KOLLA_ANSIBLE_TREE`, `POWEROPS_MASAKARI_TREE`.
- Produces source-only proof for names, input types, RBAC, package activation,
  one-region settings, role creation and deploy non-mutation.
- Expects 35 patch files: 10 Masakari, 16 Mistral, 7 Kolla-Ansible, 1
  `mistral-lib`, 1 Kolla.

- [ ] **Step 1: Write the failing cross-contract additions**

Using the standard library AST/config/YAML helpers already present, assert:

- `mistral-lib` declares and serializes `user_id`, defensive `roles` and
  `workflow_resume_authorization`;
- Mistral copies roles only from request context, stores resume record only in
  internal runtime context, and does not consume auth fields from inputs/env;
- Mistral/Horizon/Kolla-Ansible names are exactly six actions/five workflows;
- Horizon form payload keys match workbook inputs and keep Boolean/list types;
- Horizon has no Nova, Masakari, Ironic, Redfish or BMC client import;
- Kolla attaches the two plugin sources to the intended parent images and
  activates the dashboard through `ENABLE_POWEROPS`;
- Kolla-Ansible renders one region and byte-equivalent allowlists to both
  consumers;
- only the Keystone role object is created;
- deploy/reconfigure contains no workflow execution, resume, power, VM or HA
  mutation call.

- [ ] **Step 2: Run against old completed trees and verify RED**

```bash
POWEROPS_MASAKARI_TREE="$PWD/worktrees/masakari-powerops" \
POWEROPS_MISTRAL_LIB_TREE=/tmp/mistral-lib.mln14a/repo \
POWEROPS_MISTRAL_TREE="$PWD/worktrees/mistral-powerops" \
POWEROPS_DASHBOARD_TREE="$PWD/powerops-dashboard" \
POWEROPS_KOLLA_TREE=/tmp/powerops-kolla-plan \
POWEROPS_KOLLA_ANSIBLE_TREE="$PWD/work/kolla-ansible" \
python3 -m unittest tests.test_horizon_powerops_contract -v
```

Expected: failures for the unpatched library/Kolla and missing dashboard or
new contracts.

- [ ] **Step 3: Run against completed trees and verify GREEN**

```bash
POWEROPS_MASAKARI_TREE="$PWD/worktrees/masakari-powerops" \
POWEROPS_MISTRAL_LIB_TREE="$PWD/worktrees/mistral-lib-powerops" \
POWEROPS_MISTRAL_TREE="$PWD/worktrees/mistral-powerops" \
POWEROPS_DASHBOARD_TREE="$PWD/powerops-dashboard" \
POWEROPS_KOLLA_TREE="$PWD/worktrees/kolla-powerops" \
POWEROPS_KOLLA_ANSIBLE_TREE="$PWD/work/kolla-ansible" \
python3 -m unittest \
  tests.test_cross_repository_contract \
  tests.test_horizon_powerops_contract -v
```

Expected: all source-only contracts pass without network or OpenStack access.

- [ ] **Step 4: Update delivery artifact expectations**

Require the exact 35-patch set, the standalone dashboard source files,
`build/kolla-build.conf`, the separate operations guide and the four new plan
documents. Keep checksum verification exact: no unmanifested patch is allowed.

- [ ] **Step 5: Commit the contract suite**

```bash
git add tests/test_cross_repository_contract.py \
  tests/test_horizon_powerops_contract.py tests/test_delivery_artifacts.py
git commit -m "test: cover Horizon PowerOps integration contracts"
```

Expected: contract checks are independently runnable before image build.

---

### Task 5: Write the separate Russian operations guide

**Files:**
- Create: `POWEROPS_HORIZON_OPERATIONS.md`
- Modify: `tests/test_delivery_artifacts.py`

**Interfaces:**
- Produces: operator guidance for one region, RBAC, all-project impact,
  planned operations, two-phase return, HA interaction and uncertain results.
- References: `OPERATIONS.md` for CLI evidence collection and emergency HA diagnostics.

- [ ] **Step 1: Write failing documentation contract tests**

Require these exact section headings:

```markdown
# Эксплуатация PowerOps в Horizon
## Область действия и один регион
## Роли и списки доступа
## Подготовка роли powerops_operator
## Чтение состояния узлов
## Плановое выключение
## Плановая перезагрузка
## Включение для проверки и возврат в работу
## Hard-off только для администратора
## Взаимодействие с Masakari HA
## Мониторинг и аудит
## Неопределенный результат и запрет автоматического повтора
## Поиск неисправностей
## Границы проверки
```

Assert the document includes the exact Boolean JSON examples, exact RBAC
formula, both allowlist variable names, `powerops/host/<host>`, all-project
warning, role create/assignment/list verification commands, and a relative
link to `OPERATIONS.md`.

- [ ] **Step 2: Run and verify RED**

```bash
python3 -m unittest tests.test_delivery_artifacts -v
```

Expected: missing operations guide assertions fail.

- [ ] **Step 3: Write the operational procedures**

Document in Russian:

- the single displayed `openstack_region_name`, Horizon's standard one-item
  region selector, absence of a PowerOps-specific selector and absence of
  cross-region HA;
- `admin` allowlist bypass and delegated role's two exact matches;
- human role versus Mistral service credentials;
- `openstack role create powerops_operator`, explicit project user role add,
  role assignment list verification and removal, with no automatic assignment;
- inventory blocking reasons and non-operable row behavior;
- affected VM UUID/project/status review for all projects;
- typed exact-host confirmation and one-submit rule;
- separate admin hard-off confirmation;
- the six paused-return predicates and exact
  `{"stale_domains_checked": true}` resume environment;
- fail-safe `Nova disabled + Masakari maintenance=true` state;
- planned-versus-emergency ownership and shared host lock;
- execution/action IDs plus Mistral process logs as non-durable audit;
- no automatic retry after HTTP timeout or execution `ERROR`;
- local/static, read-only test-cloud and separately authorized mutation stages.

Link to `OPERATIONS.md` instead of repeating its CLI evidence and emergency
diagnostic procedures.

- [ ] **Step 4: Verify and commit**

```bash
python3 -m unittest tests.test_delivery_artifacts -v
git diff --check
git add POWEROPS_HORIZON_OPERATIONS.md tests/test_delivery_artifacts.py
git commit -m "docs: add Horizon PowerOps operations guide"
```

Expected: documentation contract and Markdown hygiene pass.

---

### Task 6: Build and inspect images without deployment

**Files:**
- Consume: `build/kolla-build.conf`
- Consume: `powerops-dashboard/`
- Consume: `worktrees/mistral-lib-powerops/`
- Consume: `worktrees/mistral-powerops/`
- Consume: `worktrees/kolla-powerops/`
- Modify after evidence exists: `DELIVERY.md`

**Interfaces:**
- Produces local images tagged `2025.1-powerops` for Horizon, Mistral API,
  Engine and Executor.
- Produces import/build evidence without starting OpenStack workflows or services.

- [ ] **Step 1: Build and inspect the standalone dashboard first**

Run its full tests, wheel build and loopback mock preview from the dashboard
plan. Complete visual review before building Kolla images.

- [ ] **Step 2: Build the four local Kolla images**

From the patched Kolla worktree, use the artifact repository as locals base:

```bash
kolla-build \
  --config-file "$PWD/../../build/kolla-build.conf" \
  --locals-base "$PWD/../.." \
  '^(horizon|mistral-api|mistral-engine|mistral-executor)$'
```

This local image build may download base images/dependencies. It does not
authorize a registry push, Kolla deploy/reconfigure, container replacement or
service restart.

- [ ] **Step 3: Inspect image contents read-only**

Use the exact local image references fixed by `namespace` and `tag` in the
tracked build configuration:

```bash
docker run --rm --entrypoint python powerops-local/horizon:2025.1-powerops -c \
  "import importlib.metadata as m; import poweropsdashboard; assert m.version('powerops-dashboard')"
docker run --rm --entrypoint python powerops-local/mistral-api:2025.1-powerops -c \
  "from mistral_lib.actions.context import SecurityContext, ExecutionContext; assert hasattr(SecurityContext(), 'roles'); assert hasattr(SecurityContext(), 'user_id'); assert hasattr(ExecutionContext(), 'workflow_resume_authorization')"
```

Record the inspected image IDs and commands in `DELIVERY.md`. Do not start the
normal Horizon or Mistral entrypoints.

- [ ] **Step 4: Record the evidence boundary**

State whether package tests, mock preview, Kolla image build and import checks
passed. State explicitly that no real service catalog, Keystone role, Mistral
execution, Nova/Masakari/Ironic state, etcd lock or BMC was exercised and no
deployment/restart occurred.

---

### Task 7: Final patch, checksum and clean-apply verification

**Files:**
- Modify: `INSTALL.md`
- Modify: `DELIVERY.md`
- Modify: `SHA256SUMS`
- Modify: `docs/superpowers/plans/2026-08-31-powerops-integration.md`
- Modify: `docs/superpowers/specs/2026-08-31-openstack-powerops-design.md`
- Consume: all 35 patches and the standalone dashboard source tree.

**Interfaces:**
- Produces exact apply order: `mistral-lib` before Mistral and image build;
  Mistral before Kolla-Ansible workbook reconciliation; Kolla before images;
  Kolla-Ansible last.
- Produces static/local verification report and separate runtime-not-tested list.

- [ ] **Step 1: Align installation and delivery documentation**

Document full baselines/final SHAs, exact 35-patch paths, local source paths,
image build command, image variable examples, role creation without assignment,
empty delegated-list behavior, one region, mock preview and separate mutation
approval. Preserve the earlier no-blind-retry and clean `git am --abort`
recovery procedures.

- [ ] **Step 2: Regenerate exact patch hashes**

```bash
find patches -type f -name '*.patch' -print0 \
  | sort -z \
  | xargs -0 shasum -a 256 > SHA256SUMS
shasum -a 256 -c SHA256SUMS
test "$(find patches -type f -name '*.patch' | wc -l | tr -d ' ')" -eq 35
```

Expected: 35 `OK` lines and exact count 35.

- [ ] **Step 3: Clean-apply every upstream patch chain**

Apply:

1. 10 Masakari patches to its pinned baseline;
2. 1 `mistral-lib` patch to `693174dd0aac1da22870b31e4a2481c4e749916a`;
3. 16 Mistral patches to `3b2eab2`;
4. 1 Kolla patch to `d14cef9bbafa0db561abfb0c0299d1d6bbbf8f0c`;
5. 7 Kolla-Ansible patches to its documented imported baseline.

Run each component's focused tests against the disposable applied tree. The
Mistral applied tree must import the disposable patched `mistral-lib`, not a
system package.

- [ ] **Step 4: Run all source-only delivery verification**

```bash
python3 -m unittest tests.test_delivery_artifacts -v
POWEROPS_MASAKARI_TREE="$PWD/worktrees/masakari-powerops" \
POWEROPS_MISTRAL_LIB_TREE="$PWD/worktrees/mistral-lib-powerops" \
POWEROPS_MISTRAL_TREE="$PWD/worktrees/mistral-powerops" \
POWEROPS_DASHBOARD_TREE="$PWD/powerops-dashboard" \
POWEROPS_KOLLA_TREE="$PWD/worktrees/kolla-powerops" \
POWEROPS_KOLLA_ANSIBLE_TREE="$PWD/work/kolla-ansible" \
python3 -m unittest \
  tests.test_cross_repository_contract \
  tests.test_horizon_powerops_contract -v
shasum -a 256 -c SHA256SUMS
python3 -m compileall -q tests
git diff --check
```

Expected: every command passes. Record exact test counts rather than copying
historic counts.

- [ ] **Step 5: Commit the integrated delivery**

```bash
git add patches build powerops-dashboard \
  POWEROPS_HORIZON_OPERATIONS.md INSTALL.md DELIVERY.md SHA256SUMS \
  tests docs/superpowers
git commit -m "feat: deliver Horizon PowerOps integration"
```

Expected: one artifact-repository delivery commit after all upstream component
commits and exported patches have passed their review gates.

- [ ] **Step 6: Stop at the runtime approval gate**

Do not connect the plugin to a test cloud in this plan. Present the completed
local/static evidence and request separate approval for read-only
service-catalog, role, inventory and status checks. A workflow start, Kolla
deploy/reconfigure, container restart, VM operation or physical power action
requires a further explicit mutation approval.
