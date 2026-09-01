# Kolla-Ansible PowerOps Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the selected Kolla-Ansible fork so deploy and reconfigure safely configure patched Masakari/Mistral PowerOps code, reconcile Mistral actions and workflows, and document operations in Russian.

**Architecture:** Kolla-Ansible renders one etcd3gw/tooz endpoint into both services, explicitly selects patched images, inserts Ironic fencing in Masakari TaskFlow, then performs post-restart registration checks. Workbook reconciliation uses authenticated Mistral API calls from the Ansible control node and never executes a workflow.

**Tech Stack:** Ansible 2.17, Kolla container modules, Jinja2, OpenStack REST APIs, Python unittest/stestr, YAML.

**Spec:** `docs/superpowers/specs/2026-08-31-openstack-powerops-design.md`

## Global Constraints

- Baseline archive is `kolla-ansible-enroll-ironic-patch-3.zip` with SHA-256 `df27628ce641fefee30114ebeb3651490655aacb0930ad5bc30a298c88c3e08d`.
- The imported baseline commit is tagged `powerops-kolla-baseline`; it is not part of the exported patch series.
- `enable_powerops` defaults to `no`.
- Enabling PowerOps requires Ironic, Masakari, Mistral and etcd; Redis is not a PowerOps dependency.
- Patched image repository/tag inputs are mandatory when PowerOps is enabled.
- Deploy and reconfigure may render config, restart configured containers, populate action metadata and reconcile workbook definitions; they may not invoke a workflow or any Nova/Ironic mutation.
- Existing power-only Ironic enrollment remains `manageable` with `network_interface=noop`.
- Authentication task results are always `no_log: true`.
- Live deploy, reconfigure, image pull, BMC operation and evacuation are outside local implementation verification.

---

### Task 1: Import the archive baseline and remove unsafe artifacts

**Files:**
- Delete: `IRONIC_ENROLL_FIX_AND_RUNBOOK.md.rej`
- Delete: `ansible.log`
- Delete: `ansible/group_vars/all.yml.bak.1787905143`
- Delete: `ansible/roles/masakari/defaults/main.yml.bak.1787914076`
- Delete: `ansible/roles/masakari/templates/masakari-monitors.conf.j2.bak.1787914072`
- Modify: `ansible/ironic-enroll-inventory.yml`
- Create: `kolla_ansible/tests/unit/test_powerops_baseline_hygiene.py`

**Interfaces:**
- Consumes: pristine extracted archive with the exact SHA-256 above.
- Produces: Git tag `powerops-kolla-baseline` and first exportable hygiene commit.
- Preserves: all existing Ironic enrollment tasks and inventory schema.

- [ ] **Step 1: Create a Git import without modifying the selected source**

Run from the artifact repository:

```bash
mkdir -p work
rsync -a --exclude .git \
  ../kolla-ansible-enroll-ironic-patch-3/ work/kolla-ansible/
cd work/kolla-ansible
git init
git add .
git add -f ansible.log
git commit -m "chore: import kolla-ansible-enroll-ironic-patch-3"
git tag powerops-kolla-baseline
```

Before `git add`, run `git grep` equivalents against `etc/kolla/passwords.yml`
and generated logs; stop if any non-placeholder credential is present. Do not
copy `.git`, shell history or Ansible fact caches. The explicit force-add is
limited to the exact ignored archive log so the exportable hygiene commit can
represent its deletion. Keep `ansible.log binary` in local-only
`.git/info/attributes`; never add that attributes file to the repository.

- [ ] **Step 2: Write the failing hygiene test**

```python
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[3]


class PowerOpsBaselineHygieneTest(unittest.TestCase):
    def test_no_reject_backup_or_runtime_log_artifacts(self):
        forbidden = [
            path for path in ROOT.rglob("*")
            if path.is_file() and (
                path.name.endswith(".rej")
                or ".bak." in path.name
                or path.name == "ansible.log"
            )
        ]
        self.assertEqual([], forbidden)

    def test_ironic_inventory_never_logs_credentials(self):
        text = (ROOT / "ansible/ironic-enroll-inventory.yml").read_text()
        self.assertNotIn("no_log: false", text.lower())
        self.assertGreaterEqual(text.lower().count("no_log: true"), 2)
```

- [ ] **Step 3: Run the hygiene test and verify RED**

```bash
python -m unittest \
  kolla_ansible.tests.unit.test_powerops_baseline_hygiene -v
```

Expected: forbidden artifacts and `no_log: false` are reported.

- [ ] **Step 4: Remove artifacts and restore secret-safe logging**

Delete only the five files listed in this task. Change both credential-bearing
tasks in `ansible/ironic-enroll-inventory.yml` from:

```yaml
no_log: false
```

to:

```yaml
no_log: true
```

- [ ] **Step 5: Run the baseline and existing enrollment tests**

```bash
python -m unittest \
  kolla_ansible.tests.unit.test_powerops_baseline_hygiene \
  kolla_ansible.tests.unit.test_ironic_enroll_inventory \
  kolla_ansible.tests.unit.test_ironic_enroll_validation -v
```

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add -A
git commit -m "fix: sanitize Ironic enrollment baseline"
```

---

### Task 2: Add PowerOps variables, explicit images and prechecks

**Files:**
- Modify: `ansible/group_vars/all.yml`
- Modify: `etc/kolla/globals.yml`
- Modify: `ansible/roles/masakari/defaults/main.yml`
- Modify: `ansible/roles/mistral/defaults/main.yml`
- Modify: `ansible/roles/masakari/tasks/precheck.yml`
- Modify: `ansible/roles/mistral/tasks/precheck.yml`
- Test: `kolla_ansible/tests/unit/test_powerops_configuration_contract.py`

**Interfaces:**
- Produces: `powerops_coordination_url` using etcd3gw API v3.
- Produces: eight required image variables for Masakari Engine and Mistral API/Engine/Executor repository/tag pairs.
- Produces: timing variables shared by Jinja templates.
- Consumes: existing `enable_ironic`, `enable_masakari`, `enable_mistral`, `enable_etcd`, `internal_protocol`, `kolla_internal_fqdn`, `etcd_client_port`, and `openstack_cacert`.

- [ ] **Step 1: Write failing default and precheck contract tests**

```python
class PowerOpsConfigurationContractTest(unittest.TestCase):
    def test_powerops_is_disabled_by_default(self):
        variables = yaml.safe_load((ROOT / "ansible/group_vars/all.yml").read_text())
        self.assertEqual("no", variables["enable_powerops"])

    def test_etcd3gw_url_uses_one_query_separator(self):
        text = (ROOT / "ansible/group_vars/all.yml").read_text()
        self.assertIn("?api_version=v3", text)
        self.assertIn("&ca_cert=", text)
        self.assertNotIn("?ca_cert=", text)

    def test_prechecks_require_etcd_and_patched_images(self):
        combined = "\n".join([
            (ROOT / "ansible/roles/masakari/tasks/precheck.yml").read_text(),
            (ROOT / "ansible/roles/mistral/tasks/precheck.yml").read_text(),
        ])
        for name in (
            "enable_etcd",
            "powerops_masakari_engine_image",
            "powerops_masakari_engine_tag",
            "powerops_mistral_api_image",
            "powerops_mistral_api_tag",
            "powerops_mistral_engine_image",
            "powerops_mistral_engine_tag",
            "powerops_mistral_executor_image",
            "powerops_mistral_executor_tag",
            "powerops_allowed_project_names",
            "powerops_allowed_user_names",
        ):
            self.assertIn(name, combined)
```

- [ ] **Step 2: Run and verify RED**

```bash
python -m unittest \
  kolla_ansible.tests.unit.test_powerops_configuration_contract -v
```

Expected: `enable_powerops` and image variables are absent.

- [ ] **Step 3: Add the exact global defaults**

Add to `ansible/group_vars/all.yml`:

```yaml
enable_powerops: "no"

powerops_coordination_url: >-
  etcd3+{{ internal_protocol }}://{{ kolla_internal_fqdn }}:{{ etcd_client_port }}?api_version=v3{% if openstack_cacert %}&ca_cert={{ openstack_cacert }}{% endif %}
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
powerops_allowed_project_names:
  - "{{ openstack_auth.project_name }}"
powerops_allowed_user_names:
  - "{{ openstack_auth.username }}"

powerops_masakari_engine_image: ""
powerops_masakari_engine_tag: ""
powerops_mistral_api_image: ""
powerops_mistral_api_tag: ""
powerops_mistral_engine_image: ""
powerops_mistral_engine_tag: ""
powerops_mistral_executor_image: ""
powerops_mistral_executor_tag: ""
```

Add commented operator examples for the same names to `etc/kolla/globals.yml`.
Do not include a registry hostname or tag value in defaults.

- [ ] **Step 4: Select patched images only when PowerOps is enabled**

In Masakari defaults set the engine service image to:

```yaml
image: >-
  {{ powerops_masakari_engine_image ~ ':' ~ powerops_masakari_engine_tag
     if enable_powerops | bool else masakari_engine_image_full }}
```

Apply the equivalent expression to Mistral API, Engine and Executor. Leave
Mistral Event Engine on `mistral_event_engine_image_full`; it does not execute
or populate the custom action plugin.

- [ ] **Step 5: Add fail-fast prechecks**

Add an assertion guarded by `enable_powerops | bool`:

```yaml
- name: Validate PowerOps service and coordination dependencies
  ansible.builtin.assert:
    that:
      - enable_ironic | bool
      - enable_masakari | bool
      - enable_mistral | bool
      - enable_etcd | bool
      - powerops_coordination_url | length > 0
      - powerops_allowed_project_names | length > 0
      - powerops_allowed_user_names | length > 0
      - powerops_allowed_project_names | reject('equalto', '') | list | length == powerops_allowed_project_names | length
      - powerops_allowed_user_names | reject('equalto', '') | list | length == powerops_allowed_user_names | length
    fail_msg: >-
      PowerOps requires Ironic, Masakari, Mistral and etcd coordination.
  when: enable_powerops | bool
```

Masakari additionally asserts its Engine image and tag are non-empty. Mistral
asserts all six Mistral image values are non-empty. Do not assert that Redis is
disabled; Redis may remain enabled for unrelated services.

- [ ] **Step 6: Run focused tests and Ansible syntax parsing**

```bash
python -m unittest \
  kolla_ansible.tests.unit.test_powerops_configuration_contract -v
ansible-playbook -i ansible/inventory/all-in-one \
  ansible/site.yml --syntax-check
```

Expected: PASS without inventory changes.

- [ ] **Step 7: Commit**

```bash
git add ansible/group_vars/all.yml etc/kolla/globals.yml \
  ansible/roles/masakari/defaults/main.yml \
  ansible/roles/mistral/defaults/main.yml \
  ansible/roles/masakari/tasks/precheck.yml \
  ansible/roles/mistral/tasks/precheck.yml \
  kolla_ansible/tests/unit/test_powerops_configuration_contract.py
git commit -m "feat: define Kolla PowerOps deployment contract"
```

---

### Task 3: Render Masakari and Mistral PowerOps configuration

**Files:**
- Modify: `ansible/roles/masakari/templates/masakari.conf.j2`
- Modify: `ansible/roles/mistral/templates/mistral.conf.j2`
- Test: `kolla_ansible/tests/unit/test_powerops_templates.py`

**Interfaces:**
- Consumes: variables from Task 2.
- Produces: Masakari `[coordination]`, `[powerops]` and `[taskflow_driver_recovery_flows]` sections.
- Produces: Mistral `[powerops]` and etcd-backed `[coordination]` sections.
- Preserves: original templates exactly when `enable_powerops` is false, except the existing invalid Masakari `?ca_cert` delimiter is corrected to `&ca_cert`.

- [ ] **Step 1: Write failing render-contract tests**

```python
class PowerOpsTemplateTest(unittest.TestCase):
    def test_masakari_flow_fences_before_prepare(self):
        text = (ROOT / "ansible/roles/masakari/templates/masakari.conf.j2").read_text()
        normalized = text.replace(" ", "").replace("\n", "")
        auto = (
            "pre:['disable_compute_service_task', 'ironic_fence'],"
            "main:['prepare_HA_enabled_instances_task'],"
            "post:['evacuate_instances_task']"
        ).replace(" ", "")
        reserved = (
            "pre:['disable_compute_service_task', 'ironic_fence'],"
            "main:['prepare_HA_enabled_instances_task', "
            "'evacuate_instances_task'],post:[]"
        ).replace(" ", "")
        self.assertIn(auto, normalized)
        self.assertIn(reserved, normalized)

    def test_both_services_use_powerops_etcd_url(self):
        for relative in (
            "ansible/roles/masakari/templates/masakari.conf.j2",
            "ansible/roles/mistral/templates/mistral.conf.j2",
        ):
            text = (ROOT / relative).read_text()
            self.assertIn("powerops_coordination_url", text)
            self.assertIn("[powerops]", text)
```

The source assertions above are supplemental. The test module must also render
the complete templates and parse the resulting INI for this matrix:

- Masakari API and Engine with PowerOps enabled and disabled;
- the disabled Masakari Redis and etcd branches, including etcd with and
  without a CA path;
- Mistral API, Engine, Event Engine and Executor with PowerOps enabled and
  disabled.

Assert exact section/option scope in rendered output. In particular, Event
Engine gets etcd-backed `[coordination]` but never `[powerops]`, and disabled
renders preserve their original sections. Assert that every rendered TLS etcd
URL has exactly one `?`, uses `&ca_cert=`, and never contains `?ca_cert=`.

Use these assertions for every timeout variable and for the absence of
`backend_url = {{ redis_connection_string }}` in Mistral's PowerOps branch:

```python
def test_templates_reference_every_powerops_timeout(self):
    combined = "\n".join([
        (ROOT / "ansible/roles/masakari/templates/masakari.conf.j2").read_text(),
        (ROOT / "ansible/roles/mistral/templates/mistral.conf.j2").read_text(),
    ])
    for variable in (
        "powerops_host_lock_timeout",
        "powerops_evacuation_lock_timeout",
        "powerops_evacuation_interval",
        "powerops_power_timeout",
        "powerops_poll_interval",
        "powerops_stable_observations",
        "powerops_graceful_shutdown_timeout",
        "powerops_vm_action_timeout",
        "powerops_service_timeout",
        "powerops_instance_interval",
    ):
        self.assertIn(variable, combined)


def test_mistral_powerops_branch_is_not_redis_backed(self):
    text = (ROOT / "ansible/roles/mistral/templates/mistral.conf.j2").read_text()
    powerops_branch = text.split("{% if enable_powerops | bool %}", 1)[1]
    powerops_branch = powerops_branch.split("{% else %}", 1)[0]
    self.assertNotIn("redis_connection_string", powerops_branch)
```

- [ ] **Step 2: Run and verify RED**

```bash
python -m unittest kolla_ansible.tests.unit.test_powerops_templates -v
```

Expected: PowerOps sections are missing.

- [ ] **Step 3: Render Masakari coordination and emergency options**

Render `[coordination]` for `masakari-api` and `masakari-engine`. When
PowerOps is enabled it uses `powerops_coordination_url` in both containers.
Render the new `[powerops]` section only when
`service_name == 'masakari-engine'`, because only that image is required to
contain the Masakari patch:

```ini
[coordination]
backend_url = {{ powerops_coordination_url }}

[powerops]
enabled = true
host_lock_timeout = {{ powerops_host_lock_timeout }}
evacuation_lock_timeout = {{ powerops_evacuation_lock_timeout }}
evacuation_interval = {{ powerops_evacuation_interval }}
power_timeout = {{ powerops_power_timeout }}
poll_interval = {{ powerops_poll_interval }}
stable_off_observations = {{ powerops_stable_observations }}
region_name = {{ openstack_region_name }}
interface = internal
```

Keep the original selected Redis/etcd coordination block when PowerOps is
disabled and change its TLS suffix to `&ca_cert={{ openstack_cacert }}`.

- [ ] **Step 4: Insert fencing into both host recovery flow shapes**

Render only when PowerOps is enabled and
`service_name == 'masakari-engine'`:

```ini
[taskflow_driver_recovery_flows]
host_auto_failure_recovery_tasks = pre:['disable_compute_service_task', 'ironic_fence'],main:['prepare_HA_enabled_instances_task'],post:['evacuate_instances_task']
host_rh_failure_recovery_tasks = pre:['disable_compute_service_task', 'ironic_fence'],main:['prepare_HA_enabled_instances_task', 'evacuate_instances_task'],post:[]
```

This preserves reserved-host preparation/retry placement while inserting the
fence after Nova disable and before instance preparation.

- [ ] **Step 5: Render Mistral action-local options**

When PowerOps is enabled, render:

```ini
[coordination]
backend_url = {{ powerops_coordination_url }}

[powerops]
enabled = true
coordination_url = {{ powerops_coordination_url }}
host_lock_timeout = {{ powerops_host_lock_timeout }}
power_timeout = {{ powerops_power_timeout }}
poll_interval = {{ powerops_poll_interval }}
stable_observations = {{ powerops_stable_observations }}
graceful_shutdown_timeout = {{ powerops_graceful_shutdown_timeout }}
vm_action_timeout = {{ powerops_vm_action_timeout }}
service_timeout = {{ powerops_service_timeout }}
instance_interval = {{ powerops_instance_interval }}
region_name = {{ openstack_region_name }}
interface = internal
allowed_project_names = {{ powerops_allowed_project_names | join(',') }}
allowed_user_names = {{ powerops_allowed_user_names | join(',') }}
```

Keep the existing non-PowerOps coordination behavior under the false branch.
Render `[powerops]` only to Mistral API, Engine and Executor; do not render it
to Event Engine because no patched Event Engine image is required. Only the
Executor invokes mutating action code.

- [ ] **Step 6: Run tests and template hygiene checks**

```bash
python -m unittest kolla_ansible.tests.unit.test_powerops_templates -v
rg -n "\?ca_cert=" ansible/roles/masakari ansible/roles/mistral
```

Expected: tests pass and the search returns no matches.

- [ ] **Step 7: Commit**

```bash
git add ansible/roles/masakari/templates/masakari.conf.j2 \
  ansible/roles/mistral/templates/mistral.conf.j2 \
  kolla_ansible/tests/unit/test_powerops_templates.py
git commit -m "feat: render etcd-backed PowerOps configuration"
```

---

### Task 4: Reconcile Mistral actions and workbook after container restart

**Files:**
- Create: `ansible/roles/mistral/files/power_ops.yaml`
- Create: `ansible/roles/mistral/tasks/powerops.yml`
- Modify: `ansible/roles/mistral/tasks/deploy.yml`
- Create: `ansible/roles/masakari/tasks/powerops.yml`
- Modify: `ansible/roles/masakari/tasks/deploy.yml`
- Test: `kolla_ansible/tests/unit/test_powerops_registration.py`

**Interfaces:**
- Consumes: five Mistral action entry points from the Mistral patch.
- Produces: idempotently created or updated public workbook `power_ops`.
- Produces: deploy ordering `flush_handlers -> populate -> workbook reconcile -> verify`.
- Uses: Keystone v3 token and internal Mistral `/v2` API; credential-bearing results are hidden.

- [ ] **Step 1: Write failing task-order and no-execution tests**

```python
class PowerOpsRegistrationTest(unittest.TestCase):
    def test_registration_runs_after_handler_flush(self):
        text = (ROOT / "ansible/roles/mistral/tasks/deploy.yml").read_text()
        self.assertLess(text.index("meta: flush_handlers"),
                        text.index("import_tasks: powerops.yml"))

        masakari = (
            ROOT / "ansible/roles/masakari/tasks/deploy.yml"
        ).read_text()
        self.assertLess(masakari.index("meta: flush_handlers"),
                        masakari.index("import_tasks: powerops.yml"))

    def test_deploy_never_starts_a_workflow_or_power_action(self):
        text = "\n".join([
            path.read_text()
            for role in ("mistral", "masakari")
            for path in (ROOT / "ansible/roles" / role / "tasks").glob("*.yml")
        ]).lower()
        for forbidden in (
            "/executions",
            "workflow create execution",
            "baremetal node power",
            "server evacuate",
            "server migrate",
        ):
            self.assertNotIn(forbidden, text)

    def test_workbook_names_match_public_contract(self):
        workbook = yaml.safe_load(
            (ROOT / "ansible/roles/mistral/files/power_ops.yaml").read_text()
        )
        self.assertEqual(
            {"host_power_status", "planned_power_off", "planned_reboot",
             "power_on_and_return"},
            set(workbook["workflows"]),
        )
```

- [ ] **Step 2: Run and verify RED**

```bash
python -m unittest \
  kolla_ansible.tests.unit.test_powerops_registration -v
```

Expected: workbook and post-deploy task file are absent.

- [ ] **Step 3: Copy the exact tested workbook contract**

Copy `etc/mistral/power_ops.yaml` from the completed Mistral worktree without
alteration to `ansible/roles/mistral/files/power_ops.yaml`. Verify byte
identity:

```bash
cmp ../../worktrees/mistral-powerops/etc/mistral/power_ops.yaml \
  ansible/roles/mistral/files/power_ops.yaml
```

- [ ] **Step 4: Populate actions and verify entry points inside containers**

Start `powerops.yml` with guarded, run-once tasks. Verify the Mistral entry
points separately in API, Engine and Executor; success in one image does not
prove the other two patched images. Execute the checks with
`changed_when: false`:

```yaml
- name: Verify PowerOps Mistral action entry points
  ansible.builtin.command: >-
    {{ kolla_container_engine }} exec {{ item.container }} python -c
    "import importlib.metadata as m; required={'powerops.host_power_status','powerops.planned_power_off','powerops.planned_reboot','powerops.power_on_for_inspection','powerops.return_to_service'}; found={e.name for e in m.entry_points(group='mistral.actions')}; assert required <= found, required - found"
  changed_when: false
  loop:
    - container: mistral_api
      group: mistral-api
    - container: mistral_engine
      group: mistral-engine
    - container: mistral_executor
      group: mistral-executor
  run_once: true
  delegate_to: "{{ groups[item.group][0] }}"

- name: Populate Mistral action definitions
  ansible.builtin.command: >-
    {{ kolla_container_engine }} exec mistral_api
    mistral-db-manage --config-file /etc/mistral/mistral.conf populate
  changed_when: false
  run_once: true
  delegate_to: "{{ groups['mistral-api'][0] }}"
```

Create `ansible/roles/masakari/tasks/powerops.yml` with this run-once check,
delegated to `groups['masakari-engine'][0]`:

```yaml
- name: Verify PowerOps Masakari fencing entry point
  ansible.builtin.command: >-
    {{ kolla_container_engine }} exec masakari_engine python -c
    "import importlib.metadata as m; found={e.name for e in m.entry_points(group='masakari.task_flow.tasks')}; assert 'ironic_fence' in found"
  changed_when: false
  run_once: true
  delegate_to: "{{ groups['masakari-engine'][0] }}"
```

Import that file after `meta: flush_handlers` in Masakari `deploy.yml`, guarded
by `enable_powerops | bool`. This keeps container locality correct.

- [ ] **Step 5: Obtain a protected Keystone token**

Before API access, `stat` `kolla_admin_openrc_cacert` on `localhost` with
`follow: true` and assert that a non-empty path exists, is a regular file and
is readable. This controller-side path is distinct from `openstack_cacert`
inside service containers. Use it as `ca_path` for every delegated
Keystone/Mistral URI task; omit `ca_path` only when the controller value is
empty.

This is not a role-local precheck. In the implemented ordering it runs inside
deploy/reconfigure after `meta: flush_handlers` and the Mistral action
population command, but before Keystone authentication and workbook
reconciliation. The operator guide must require an explicit read-only
`test -f`/`test -r` on the controller before approving deploy/reconfigure;
otherwise a bad CA path is detected only after containers may have restarted.

```yaml
- name: Check PowerOps controller CA certificate
  ansible.builtin.stat:
    path: "{{ kolla_admin_openrc_cacert }}"
    get_checksum: false
    follow: true
  register: powerops_controller_ca
  run_once: true
  delegate_to: localhost
  when:
    - >-
      powerops_reconcile_workbook | bool or
      powerops_validate_registration | bool
    - kolla_admin_openrc_cacert | length > 0

- name: Validate PowerOps controller CA certificate
  ansible.builtin.assert:
    that:
      - powerops_controller_ca.stat.exists | default(false)
      - powerops_controller_ca.stat.isreg | default(false)
      - powerops_controller_ca.stat.readable | default(false)
  run_once: true
  delegate_to: localhost
  when:
    - >-
      powerops_reconcile_workbook | bool or
      powerops_validate_registration | bool
    - kolla_admin_openrc_cacert | length > 0
```

Use this project-scoped Keystone request and protect its result:

```yaml
- name: Authenticate PowerOps workbook reconciliation
  ansible.builtin.uri:
    url: >-
      {{ openstack_mistral_auth.auth_url |
         regex_replace('/v3/?$', '') |
         regex_replace('/+$', '') }}/v3/auth/tokens
    method: POST
    body_format: json
    body:
      auth:
        identity:
          methods: [password]
          password:
            user:
              name: "{{ openstack_mistral_auth.username }}"
              password: "{{ openstack_mistral_auth.password }}"
              domain:
                name: "{{ openstack_mistral_auth.user_domain_name }}"
        scope:
          project:
            name: "{{ openstack_mistral_auth.project_name }}"
            domain:
              name: "{{ openstack_mistral_auth.domain_name }}"
    status_code: 201
    return_content: true
    validate_certs: true
    ca_path: >-
      {{ kolla_admin_openrc_cacert
         if kolla_admin_openrc_cacert else omit }}
  register: powerops_keystone_auth
  no_log: true
  run_once: true
  delegate_to: localhost
  when: >-
    powerops_reconcile_workbook | bool or
    powerops_validate_registration | bool

- name: Store protected PowerOps token
  ansible.builtin.set_fact:
    powerops_keystone_token: >-
      {{ powerops_keystone_auth.x_subject_token }}
    powerops_keystone_project_id: >-
      {{ powerops_keystone_auth.json.token.project.id }}
  no_log: true
  run_once: true
  delegate_to: localhost
  when: >-
    powerops_reconcile_workbook | bool or
    powerops_validate_registration | bool
```

Set all later tasks that consume the token to:

```yaml
no_log: true
run_once: true
delegate_to: localhost
```

This preserves the deployment's existing service-registration identity and
role policy. Run token acquisition only when
`powerops_reconcile_workbook | bool or powerops_validate_registration | bool`.

- [ ] **Step 6: Reconcile the workbook without running it**

Read the file on the control node with:

```yaml
powerops_workbook_definition: >-
  {{ lookup('ansible.builtin.file', role_path ~ '/files/power_ops.yaml',
            rstrip=False) }}
```

List all exact-name/default-namespace candidates without a bounded page limit,
then defensively repeat the exact name/namespace filter. Fail closed before
POST/PUT if more than one row exists or the sole row's `project_id` differs
from `powerops_keystone_project_id`:

```yaml
- name: List matching PowerOps workbooks
  ansible.builtin.uri:
    url: >-
      {{ mistral_internal_endpoint }}/workbooks?name=power_ops&namespace=
    method: GET
    headers:
      X-Auth-Token: "{{ powerops_keystone_token }}"
    status_code: 200
    return_content: true
    validate_certs: true
    ca_path: >-
      {{ kolla_admin_openrc_cacert
         if kolla_admin_openrc_cacert else omit }}
  register: powerops_workbook_list
  until: powerops_workbook_list is success
  retries: 12
  delay: 5
  no_log: true
  run_once: true
  delegate_to: localhost
  when: powerops_reconcile_workbook | bool

- name: Store matching PowerOps workbooks
  ansible.builtin.set_fact:
    powerops_matching_workbooks: >-
      {{ powerops_workbook_list.json.workbooks | default([]) |
         selectattr('name', 'equalto', 'power_ops') |
         selectattr('namespace', 'equalto', '') | list }}
  no_log: true
  run_once: true
  delegate_to: localhost
  when: powerops_reconcile_workbook | bool

- name: Validate PowerOps workbook ownership
  ansible.builtin.assert:
    that:
      - powerops_matching_workbooks | length <= 1
      - >-
        powerops_matching_workbooks | length == 0 or
        powerops_matching_workbooks[0].project_id ==
        powerops_keystone_project_id
    fail_msg: >-
      Refusing to reconcile an ambiguous or foreign public power_ops workbook
  no_log: true
  run_once: true
  delegate_to: localhost
  when: powerops_reconcile_workbook | bool

- name: Create PowerOps workbook
  ansible.builtin.uri:
    url: "{{ mistral_internal_endpoint }}/workbooks?scope=public"
    method: POST
    headers:
      X-Auth-Token: "{{ powerops_keystone_token }}"
      Content-Type: text/plain
    body: "{{ powerops_workbook_definition }}"
    body_format: raw
    status_code: 201
    validate_certs: true
    ca_path: >-
      {{ kolla_admin_openrc_cacert
         if kolla_admin_openrc_cacert else omit }}
  when:
    - powerops_reconcile_workbook | bool
    - powerops_matching_workbooks | length == 0
  no_log: true
  run_once: true
  delegate_to: localhost

- name: Update changed PowerOps workbook
  ansible.builtin.uri:
    url: "{{ mistral_internal_endpoint }}/workbooks?scope=public"
    method: PUT
    headers:
      X-Auth-Token: "{{ powerops_keystone_token }}"
      Content-Type: text/plain
    body: "{{ powerops_workbook_definition }}"
    body_format: raw
    status_code: 200
    validate_certs: true
    ca_path: >-
      {{ kolla_admin_openrc_cacert
         if kolla_admin_openrc_cacert else omit }}
  when:
    - powerops_reconcile_workbook | bool
    - powerops_matching_workbooks | length == 1
    - >-
      powerops_matching_workbooks[0].project_id ==
      powerops_keystone_project_id
    - >-
      powerops_matching_workbooks[0].definition |
      default('') != powerops_workbook_definition or
      powerops_matching_workbooks[0].scope | default('') != 'public'
  no_log: true
  run_once: true
  delegate_to: localhost
```

Do not add automatic retries to POST or PUT. When the definition is identical
and the existing scope is already public, neither mutation task runs and
Ansible reports the reconciliation unchanged.

The PUT is safe only with the companion Mistral commit/patch
`0010-fix-scope-workbook-updates-to-request-project.patch`. Its
`update_workbook()` performs an atomic, session-aware lookup/update scoped by
`models.Workbook.project_id == security.get_project_id()`, exact name and
normalized namespace. The preceding Kolla ownership assertion is necessary
operator feedback but alone cannot close the TOCTOU window.

- [ ] **Step 7: Verify action and workflow names through read-only API calls**

Use a direct read-only GET for every exact action. For workflows, the API does
not provide the same direct exact read contract, so issue one unbounded
name/default-namespace filtered list GET per expected workflow and assert one
exact, token-project-owned row. Safe GETs retry 12 times with a five-second
delay; mutation requests never retry blindly.

```yaml
- name: Read exact populated Mistral actions
  ansible.builtin.uri:
    url: "{{ mistral_internal_endpoint }}/actions/{{ item }}"
    method: GET
    headers:
      X-Auth-Token: "{{ powerops_keystone_token }}"
    status_code: 200
    return_content: true
    validate_certs: true
    ca_path: >-
      {{ kolla_admin_openrc_cacert
         if kolla_admin_openrc_cacert else omit }}
  register: powerops_action_reads
  until: powerops_action_reads is success
  retries: 12
  delay: 5
  loop:
    - powerops.host_power_status
    - powerops.planned_power_off
    - powerops.planned_reboot
    - powerops.power_on_for_inspection
    - powerops.return_to_service
  when: powerops_validate_registration | bool
  no_log: true
  run_once: true
  delegate_to: localhost

- name: Read exact registered PowerOps workflows
  ansible.builtin.uri:
    url: >-
      {{ mistral_internal_endpoint }}/workflows?name={{ item }}&namespace=
    method: GET
    headers:
      X-Auth-Token: "{{ powerops_keystone_token }}"
    status_code: 200
    return_content: true
    validate_certs: true
    ca_path: >-
      {{ kolla_admin_openrc_cacert
         if kolla_admin_openrc_cacert else omit }}
  register: powerops_workflow_reads
  until: powerops_workflow_reads is success
  retries: 12
  delay: 5
  loop:
    - power_ops.host_power_status
    - power_ops.planned_power_off
    - power_ops.planned_reboot
    - power_ops.power_on_and_return
  when: powerops_validate_registration | bool
  no_log: true
  run_once: true
  delegate_to: localhost
```

Then apply these assertions:

```yaml
- name: Validate registered PowerOps actions
  ansible.builtin.assert:
    that:
      - >-
        (powerops_action_reads.results | default([]) |
         map(attribute='json.name') | list | unique | sort) ==
        ['powerops.host_power_status', 'powerops.planned_power_off',
         'powerops.planned_reboot', 'powerops.power_on_for_inspection',
         'powerops.return_to_service']
  no_log: true
  run_once: true
  when: powerops_validate_registration | bool

- name: Validate each registered PowerOps workflow
  ansible.builtin.assert:
    that:
      - item.json.workflows | default([]) | length == 1
      - >-
        (item.json.workflows | default([]) |
         map(attribute='name') | list) == [item.item]
      - >-
        (item.json.workflows | default([]) |
         map(attribute='project_id') | list) ==
        [powerops_keystone_project_id]
  loop: "{{ powerops_workflow_reads.results | default([]) }}"
  no_log: true
  run_once: true
  delegate_to: localhost
  when: powerops_validate_registration | bool
```

The GET loops and assertions remain `no_log: true` because their registered
data or evaluation context carries the token.

- [ ] **Step 8: Wire post-restart ordering**

Append to `deploy.yml` after the existing handler flush:

```yaml
- import_tasks: powerops.yml
  when: enable_powerops | bool
```

Inside `powerops.yml`, entry-point verification and action population are
always mandatory. Guard the workbook GET/create/update tasks with
`powerops_reconcile_workbook | bool` and the final catalogue GET/assertion
tasks with `powerops_validate_registration | bool`.

- [ ] **Step 9: Run registration tests and Ansible syntax check**

```bash
python -m unittest \
  kolla_ansible.tests.unit.test_powerops_registration -v
ansible-playbook -i ansible/inventory/all-in-one \
  ansible/site.yml --syntax-check
```

Expected: PASS. Do not run `kolla-ansible deploy` or `reconfigure`.

- [ ] **Step 10: Commit**

```bash
git add ansible/roles/mistral/files/power_ops.yaml \
  ansible/roles/mistral/tasks/powerops.yml \
  ansible/roles/mistral/tasks/deploy.yml \
  ansible/roles/masakari/tasks/powerops.yml \
  ansible/roles/masakari/tasks/deploy.yml \
  kolla_ansible/tests/unit/test_powerops_registration.py
git commit -m "feat: reconcile PowerOps actions and workbook"
```

---

### Task 5: Russian architecture runbook, repository checks and export

**Files:**
- Create: `docs/powerops/POWEROPS-ARCHITECTURE.md`
- Create: `kolla_ansible/tests/unit/test_powerops_documentation.py`

**Interfaces:**
- Produces: operator-facing Russian description requested by the user.
- Produces: five numbered Kolla-Ansible patches after the import baseline.
- References: exact action/workflow names, lock names, config variables and fail-safe states implemented in all repositories.

- [ ] **Step 1: Write the failing documentation contract test**

```python
class PowerOpsDocumentationTest(unittest.TestCase):
    def test_runbook_covers_required_scenarios_and_boundaries(self):
        text = (ROOT / "docs/powerops/POWEROPS-ARCHITECTURE.md").read_text()
        required = {
            "power_ops.planned_power_off",
            "power_ops.planned_reboot",
            "power_ops.power_on_and_return",
            "ironic_fence",
            "powerops/host/<host>",
            "powerops/evacuation/global",
            "stale_domains_checked=true",
            "powerops_allowed_project_names",
            "powerops_allowed_user_names",
            "Статическая проверка",
            "Проверка в реальной инфраструктуре",
        }
        self.assertEqual(set(), required - set(filter(lambda item: item in text, required)))
```

- [ ] **Step 2: Run and verify RED**

```bash
python -m unittest \
  kolla_ansible.tests.unit.test_powerops_documentation -v
```

Expected: documentation file is absent.

- [ ] **Step 3: Write the Russian operator document**

Use these exact top-level sections:

```markdown
# PowerOps: управление питанием и fencing вычислительных узлов

## Краткий вывод
## Границы решения
## Компоненты и их ответственность
## Координация через etcd
## Сценарий: плановое выключение
## Сценарий: плановая перезагрузка
## Сценарий: включение и возврат в эксплуатацию
## Сценарий: аварийный fencing и эвакуация
## Последовательный запуск и эвакуация ВМ
## Развёртывание и повторная конфигурация
## Состояния отказа и безопасное восстановление
## Проверки оператора
## Статическая проверка
## Проверка в реальной инфраструктуре
```

Include text diagrams for component calls and each state transition. State
that status is point-in-time, planned `evacuate` is forbidden, emergency-fenced
hosts are never powered on automatically, the return workflow resumes with an
updated Mistral environment, action callers must match both exact configured
allowlists, and local passing tests do not prove real BMC, etcd lease, Nova
migration or evacuation behavior.

- [ ] **Step 4: Run all local Kolla tests**

```bash
python -m unittest discover -s kolla_ansible/tests/unit -v
tox -e py3
tox -e linters
git diff --check powerops-kolla-baseline...HEAD
```

Expected: PASS with no warnings introduced by PowerOps.

- [ ] **Step 5: Verify no deploy-time mutation or leaked secrets**

```bash
rg -n "/executions|baremetal node power|server evacuate|server migrate" \
  ansible/roles/masakari ansible/roles/mistral
rg -n "no_log: false|\?ca_cert=" ansible/ironic-enroll-inventory.yml \
  ansible/roles/masakari ansible/roles/mistral
```

Expected: both searches return no matches.

- [ ] **Step 6: Commit documentation and export**

```bash
git add docs/powerops/POWEROPS-ARCHITECTURE.md \
  kolla_ansible/tests/unit/test_powerops_documentation.py
git commit -m "docs: add Russian PowerOps operations guide"
POWEROPS_ARTIFACT_ROOT=/Users/dmitry/Desktop/ironic:mistral:masakari/powerops-patches
git format-patch --full-index --no-binary --output-directory \
  "$POWEROPS_ARTIFACT_ROOT/patches/kolla-ansible" \
  powerops-kolla-baseline..HEAD
```

The local-only `ansible.log binary` attribute plus `--full-index --no-binary`
must produce a hash-only deletion record. Before publishing, assert that the
Task 1 patch contains `Binary files a/ansible.log and /dev/null differ`, does
not contain `GIT binary patch`, and contains no log payload or credential
material.

- [ ] **Step 7: Apply the exported series to a clean archive copy**

```bash
mkdir -p /tmp/kolla-powerops-apply
rsync -a --exclude .git \
  /Users/dmitry/Desktop/ironic:mistral:masakari/kolla-ansible-enroll-ironic-patch-3/ \
  /tmp/kolla-powerops-apply/
git -C /tmp/kolla-powerops-apply init
git -C /tmp/kolla-powerops-apply add .
git -C /tmp/kolla-powerops-apply add -f ansible.log
git -C /tmp/kolla-powerops-apply commit -m "baseline"
git -C /tmp/kolla-powerops-apply am \
  "$POWEROPS_ARTIFACT_ROOT"/patches/kolla-ansible/*.patch
git -C /tmp/kolla-powerops-apply diff --check HEAD~5..HEAD
```

Expected: the fresh baseline tree equals `powerops-kolla-baseline`, all five
patches apply in order without fuzz or rejects, `ansible.log` is absent, and
the hygiene plus enrollment tests pass in the applied tree.
