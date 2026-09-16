# Horizon PowerOps Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a separate Horizon 2025.1 `powerops-dashboard` plugin for safe host inventory, planned power operations, execution monitoring and two-phase return.

**Architecture:** The plugin is a top-level Horizon dashboard and talks only to the regional Mistral v2 endpoint with the current user token. UI authorization mirrors the server contract for visibility and direct-URL protection, while Mistral remains authoritative. Live and mock clients share one narrow adapter; mock mode serves realistic read-only fixtures and rejects every mutation method.

**Tech Stack:** Horizon stable/2025.1, Django, Horizon tables/forms, python-mistralclient stable/2025.1, PBR/setuptools, JavaScript GET polling, `stestr`, `unittest.mock`.

**Spec:** `docs/superpowers/specs/2026-09-02-horizon-powerops-integration-design.md`

## Global Constraints

- Create a standalone package under `powerops-dashboard/`; do not fork Horizon or `mistral-dashboard`.
- Register a top-level `PowerOps` dashboard with one `Compute Hosts` panel; do not nest it under Horizon `Admin`.
- UI authorization is exactly `admin OR (powerops_operator AND exact project allowlist AND exact user allowlist)`.
- Compare role, project and user names exactly; `admin` bypasses allowlists.
- Use `request.user.roles[*]['name']`, `request.user.project_name`, `request.user.username`, `request.user.id` and `request.user.project_id` as presentation attributes only.
- Forward the current user token to `base.url_for(request, 'workflowv2')`; never store or use Mistral service-account or BMC credentials.
- Require `request.user.services_region == settings.POWEROPS_REGION_NAME`; region is displayed but never sent as workflow input.
- Preserve Horizon's standard region selector; do not add a PowerOps selector.
  In the supported deployment it contains the one configured region.
- Call only `power_ops.host_inventory`, `power_ops.host_power_status`, `power_ops.planned_power_off`, `power_ops.planned_reboot` and `power_ops.power_on_and_return`.
- Serialize booleans as JSON booleans and stopped manifests as JSON UUID lists, never strings.
- State prominently that a host action affects eligible instances from all projects.
- Default hard-off to Boolean `false`; expose and accept Boolean `true` only
  for the exact `admin` branch with a separate confirmation.
- Never automatically retry a workflow start, power request or resume request.
- In `POWEROPS_MOCK_MODE=True`, all destructive adapter methods raise
  `MockMutationDisabled`; inventory refresh and host-status fixtures remain
  usable without a Mistral write.
- Sanitize browser errors to fixed operator messages; never render traceback, token, password, service catalog or BMC details.
- Local preview binds to `127.0.0.1` and is not runtime proof against OpenStack services.

---

### Task 1: Scaffold the package and protect dashboard access

**Files:**
- Create: `powerops-dashboard/setup.py`
- Create: `powerops-dashboard/setup.cfg`
- Create: `powerops-dashboard/MANIFEST.in`
- Create: `powerops-dashboard/requirements.txt`
- Create: `powerops-dashboard/test-requirements.txt`
- Create: `powerops-dashboard/tox.ini`
- Create: `powerops-dashboard/manage.py`
- Create: `powerops-dashboard/poweropsdashboard/__init__.py`
- Create: `powerops-dashboard/poweropsdashboard/dashboard.py`
- Create: `powerops-dashboard/poweropsdashboard/auth.py`
- Create: `powerops-dashboard/poweropsdashboard/exceptions.py`
- Create: `powerops-dashboard/poweropsdashboard/enabled/__init__.py`
- Create: `powerops-dashboard/poweropsdashboard/enabled/_50_powerops.py`
- Create: `powerops-dashboard/poweropsdashboard/hosts/__init__.py`
- Create: `powerops-dashboard/poweropsdashboard/hosts/panel.py`
- Create: `powerops-dashboard/poweropsdashboard/hosts/urls.py`
- Create: `powerops-dashboard/poweropsdashboard/hosts/views.py`
- Create: `powerops-dashboard/poweropsdashboard/test/__init__.py`
- Create: `powerops-dashboard/poweropsdashboard/test/helpers.py`
- Create: `powerops-dashboard/poweropsdashboard/test/settings.py`
- Create: `powerops-dashboard/poweropsdashboard/test/urls.py`
- Create: `powerops-dashboard/poweropsdashboard/tests/test_auth.py`
- Create: `powerops-dashboard/poweropsdashboard/tests/test_dashboard.py`

**Interfaces:**
- Produces: `Authorization(branch: str, is_admin: bool)`.
- Produces: `authorize_user(user) -> Authorization`, raising `django.core.exceptions.PermissionDenied`.
- Consumes settings: `POWEROPS_ALLOWED_PROJECT_NAMES: list[str]`, `POWEROPS_ALLOWED_USER_NAMES: list[str]`.
- Produces URL namespace: `horizon:powerops:compute_hosts`.

- [ ] **Step 1: Create packaging metadata and the test harness**

Use package metadata:

```ini
[metadata]
name = powerops-dashboard
summary = Safe Horizon interface for OpenStack PowerOps workflows
license = Apache License, Version 2.0
python_requires = >=3.8

[files]
packages =
    poweropsdashboard
```

`requirements.txt` contains PBR, `python-mistralclient>=4.3.0` and
`horizon>=24.0.0` under the OpenStack 2025.1 upper constraints. `tox.ini`
mirrors the stable/2025.1 `mistral-dashboard` `py3` and `pep8` environments and
runs:

```ini
commands =
    stestr run {posargs}
```

`poweropsdashboard.test.settings` imports Horizon test settings, appends
`poweropsdashboard`, and defines:

```python
POWEROPS_REGION_NAME = 'RegionOne'
POWEROPS_ALLOWED_PROJECT_NAMES = ['operations']
POWEROPS_ALLOWED_USER_NAMES = ['power-operator']
POWEROPS_MOCK_MODE = False
```

- [ ] **Step 2: Write the failing authorization matrix**

Use `openstack_auth.user.User` with role dictionaries and assert:

```python
cases = (
    (['admin'], 'other-project', 'other-user', 'admin'),
    (['powerops_operator'], 'operations', 'power-operator',
     'powerops_operator'),
    (['powerops_operator'], 'other-project', 'power-operator', None),
    (['powerops_operator'], 'operations', 'other-user', None),
    (['member'], 'operations', 'power-operator', None),
    (['Admin'], 'operations', 'power-operator', None),
)
```

Add empty-allowlist tests: admin remains allowed and delegated operator is
denied. Add malformed role dictionary tests that fail closed.

- [ ] **Step 3: Write failing dashboard and direct-URL tests**

Assert `PowerOpsDashboard.allowed()` and `ComputeHosts.allowed()` are true for
admin and exact delegated access. Use the Horizon test client to assert an
unauthorized GET of `horizon:powerops:compute_hosts:index` returns HTTP 403,
not only a hidden navigation item.

- [ ] **Step 4: Run and verify RED**

```bash
cd powerops-dashboard
python -m stestr run \
  poweropsdashboard.tests.test_auth \
  poweropsdashboard.tests.test_dashboard
```

Expected: package modules and dashboard registration do not exist.

- [ ] **Step 5: Implement exact UI authorization**

In `auth.py`:

```python
@dataclasses.dataclass(frozen=True)
class Authorization:
    branch: str
    is_admin: bool


def _role_names(user):
    roles = getattr(user, 'roles', None) or []
    if not all(
            isinstance(role, dict)
            and isinstance(role.get('name'), str)
            for role in roles):
        raise PermissionDenied
    return {role['name'] for role in roles}


def authorize_user(user):
    roles = _role_names(user)
    if 'admin' in roles:
        return Authorization('admin', True)
    if (
            'powerops_operator' in roles
            and user.project_name
            in settings.POWEROPS_ALLOWED_PROJECT_NAMES
            and user.username in settings.POWEROPS_ALLOWED_USER_NAMES):
        return Authorization('powerops_operator', False)
    raise PermissionDenied
```

Do not use `user.is_superuser`, because Horizon admin-role configuration is
case-insensitive and broader than this exact PowerOps contract.

- [ ] **Step 6: Register a top-level dashboard and panel**

`dashboard.py`:

```python
class PowerOpsDashboard(horizon.Dashboard):
    name = _('PowerOps')
    slug = 'powerops'
    panels = ('compute_hosts',)
    default_panel = 'compute_hosts'

    def allowed(self, context):
        auth.authorize_user(context['request'].user)
        return super().allowed(context)


horizon.register(PowerOpsDashboard)
PowerOpsDashboard.register(panel.ComputeHosts)
```

`hosts/panel.py` implements the same `allowed()` call. `_50_powerops.py`
defines exactly:

```python
DASHBOARD = 'powerops'
ADD_INSTALLED_APPS = ['poweropsdashboard']
DEFAULT = False
```

The initial index view returns a simple registered template response; every
URL remains covered by Horizon's component-access decorator.

- [ ] **Step 7: Run and commit**

```bash
python -m stestr run \
  poweropsdashboard.tests.test_auth \
  poweropsdashboard.tests.test_dashboard
tox -e pep8
git add powerops-dashboard
git commit -m "feat: scaffold protected PowerOps dashboard"
```

Expected: exact RBAC and direct-URL 403 tests pass.

---

### Task 2: Implement the live Mistral adapter and locked-down mock adapter

**Files:**
- Create: `powerops-dashboard/poweropsdashboard/constants.py`
- Create: `powerops-dashboard/poweropsdashboard/api.py`
- Create: `powerops-dashboard/poweropsdashboard/mock_data.py`
- Create: `powerops-dashboard/poweropsdashboard/tests/test_api.py`
- Create: `powerops-dashboard/poweropsdashboard/tests/test_mock_api.py`

**Interfaces:**
- Produces: `get_client(request) -> MistralPowerOpsClient | MockPowerOpsClient`.
- Produces live methods: `start_inventory()`,
  `start_host_status(host, segment_uuid)`, `get_execution(id)`,
  `list_executions(**filters)`, `list_tasks(id)`,
  `start_planned(operation, payload)`, `start_return(payload)` and
  `resume_return(id)`.
- Produces workflow constants for the five exact public workflow names.
- Produces: `MockMutationDisabled`, `RegionMismatch`, `BackendUnavailable`, `InvalidBackendData`.

- [ ] **Step 1: Write failing client-construction and serialization tests**

Patch `mistralclient.api.client.client` and `base.url_for`. Assert live client
construction matches Horizon stable/2025.1:

```python
mistral_client.client.assert_called_once_with(
    username=request.user.username,
    auth_token=request.user.token.id,
    project_id=request.user.project_id,
    mistral_url='https://mistral.example/v2',
    endpoint_type=settings.OPENSTACK_ENDPOINT_TYPE,
    service_type='workflowv2',
    enforce_raw_definition=False,
)
```

Assert a selected service region different from `POWEROPS_REGION_NAME` raises
`RegionMismatch` before endpoint discovery. Assert workflow creation receives
typed mappings such as:

```python
{
    'host': 'compute-01',
    'segment_uuid': '11111111-1111-1111-1111-111111111111',
    'instance_policy': 'stop',
    'allow_hard_off': False,
}
```

and resume calls:

```python
client.executions.update(
    execution_id,
    'RUNNING',
    env={'stale_domains_checked': True},
)
```

- [ ] **Step 2: Write failing mock mutation-gate tests**

With `POWEROPS_MOCK_MODE=True`, assert `start_inventory()`,
`start_host_status()`, and the execution read methods return defensive fixture
copies without touching python-mistralclient. Assert all destructive methods
raise `MockMutationDisabled` without touching python-mistralclient:
`start_planned`, `start_return` and `resume_return`.

- [ ] **Step 3: Run and verify RED**

```bash
python -m stestr run \
  poweropsdashboard.tests.test_api \
  poweropsdashboard.tests.test_mock_api
```

Expected: adapter modules are absent.

- [ ] **Step 4: Define exact workflow constants**

```python
HOST_INVENTORY = 'power_ops.host_inventory'
HOST_POWER_STATUS = 'power_ops.host_power_status'
PLANNED_POWER_OFF = 'power_ops.planned_power_off'
PLANNED_REBOOT = 'power_ops.planned_reboot'
POWER_ON_AND_RETURN = 'power_ops.power_on_and_return'
MUTATION_WORKFLOWS = frozenset({
    PLANNED_POWER_OFF,
    PLANNED_REBOOT,
    POWER_ON_AND_RETURN,
})
INSTANCE_POLICIES = ('require_empty', 'live_migrate', 'stop')
```

- [ ] **Step 5: Implement the live adapter**

Construct the client as asserted in Step 1. Map methods directly:

```python
def start_inventory(self):
    return self.client.executions.create(HOST_INVENTORY)

def start_host_status(self, host, segment_uuid):
    return self.client.executions.create(
        HOST_POWER_STATUS,
        workflow_input={'host': host, 'segment_uuid': segment_uuid},
    )

def start_planned(self, operation, payload):
    workflow = {
        'power_off': PLANNED_POWER_OFF,
        'reboot': PLANNED_REBOOT,
    }[operation]
    return self.client.executions.create(
        workflow,
        workflow_input=dict(payload),
    )

def start_return(self, payload):
    return self.client.executions.create(
        POWER_ON_AND_RETURN,
        workflow_input=dict(payload),
    )

def resume_return(self, execution_id):
    return self.client.executions.update(
        execution_id,
        'RUNNING',
        env={'stale_domains_checked': True},
    )
```

`list_executions()` passes exact Mistral filters including `workflow_name` and
sorts returned resources by `created_at` descending in presentation code;
`get_execution()` and `list_tasks()` are GET-only wrappers.

- [ ] **Step 6: Add realistic secret-free fixtures**

`mock_data.py` contains:

- `compute-01`, operable, powered on, Nova enabled/up, maintenance false,
  with two instances from different project UUIDs;
- `compute-02`, non-operable, with a sanitized
  `blocking_reason='ironic_node_incompatible'` and non-empty displayed
  `ironic_last_error` fixture containing no connection data;
- one successful inventory execution;
- one running planned-power-off execution;
- one paused `power_on_and_return` execution at
  `operator_inspection_gate` with power on, Nova disabled and maintenance true;
- one error execution marked for manual verification.

The mock client returns deep copies for inventory, host status and execution
reads. Its three destructive methods unconditionally raise
`MockMutationDisabled('PowerOps mutations are disabled in mock mode')`.

- [ ] **Step 7: Run and commit**

```bash
python -m stestr run \
  poweropsdashboard.tests.test_api \
  poweropsdashboard.tests.test_mock_api
git add powerops-dashboard/poweropsdashboard/constants.py \
  powerops-dashboard/poweropsdashboard/api.py \
  powerops-dashboard/poweropsdashboard/mock_data.py \
  powerops-dashboard/poweropsdashboard/exceptions.py \
  powerops-dashboard/poweropsdashboard/tests/test_api.py \
  powerops-dashboard/poweropsdashboard/tests/test_mock_api.py
git commit -m "feat: add PowerOps Mistral and mock adapters"
```

Expected: live call shapes and mock mutation denial are proven.

---

### Task 3: Render inventory and authoritative execution state

**Files:**
- Create: `powerops-dashboard/poweropsdashboard/presentation.py`
- Create: `powerops-dashboard/poweropsdashboard/hosts/tables.py`
- Modify: `powerops-dashboard/poweropsdashboard/hosts/views.py`
- Modify: `powerops-dashboard/poweropsdashboard/hosts/urls.py`
- Create: `powerops-dashboard/poweropsdashboard/hosts/templates/powerops/compute_hosts/index.html`
- Create: `powerops-dashboard/poweropsdashboard/hosts/templates/powerops/compute_hosts/execution.html`
- Create: `powerops-dashboard/poweropsdashboard/tests/test_inventory_views.py`
- Create: `powerops-dashboard/poweropsdashboard/tests/test_execution_views.py`

**Interfaces:**
- Produces: `parse_inventory_execution(execution) -> list[HostRow]`.
- Produces: `ExecutionState(id, workflow_name, state, state_info, verification_required, output)`.
- Produces routes: `index`, `refresh_inventory`, `execution`.
- Consumes only declared Mistral inventory/output fields.

- [ ] **Step 1: Write failing parser tests**

Test string and already-decoded Mistral `output` values. Accept only a mapping
with top-level `result` list and the exact inventory row/instance keys declared
in the Mistral plan. Reject missing keys, unexpected field types, an unexpected
region, duplicate host/segment pairs, and any key matching
`token|password|secret|driver_info|instance_info|bmc`.

For execution state, set `verification_required=True` when state is `ERROR` or
when the adapter reports an uncertain timeout after an execution UUID was
known. Preserve only sanitized `state_info` categories; do not pass raw backend
text to templates.

- [ ] **Step 2: Write failing inventory view tests**

Assert the table displays region, segment, host, Ironic power/target/error,
Nova status/state, Masakari maintenance, VM count and active visible execution.
Assert a non-operable row has no mutation actions. Assert the all-project
warning is present in Russian and includes the two fixture project UUIDs in the
impact detail.

POST `refresh_inventory` may start only `power_ops.host_inventory`; it stores
the returned execution UUID in the session and redirects to the GET-only
execution page. GET index never starts a workflow.

- [ ] **Step 3: Write failing no-retry execution tests**

Patch the adapter and use repeated GET polls. Assert every poll calls only
`get_execution()`/`list_tasks()` and never any start/resume method. An `ERROR`
or adapter timeout renders `verification required`, the execution UUID and a
runbook link without a retry button.

- [ ] **Step 4: Run and verify RED**

```bash
python -m stestr run \
  poweropsdashboard.tests.test_inventory_views \
  poweropsdashboard.tests.test_execution_views
```

Expected: parsers, table and routes are absent.

- [ ] **Step 5: Implement strict presentation models**

Use frozen dataclasses and explicit key/type validation. `HostRow` includes
the exact backend fields plus `active_execution_id: str | None`. Never attach
the raw Mistral resource. `blocking_reason` is mapped through a fixed Russian
message dictionary; unknown reasons become `Состояние узла не подтверждено`.

Build active-operation hints from executions visible to the current token by
matching exact workflow names and the decoded input's exact `host`. Treat this
as convenience only and display that the etcd host lock remains authoritative.

- [ ] **Step 6: Implement the table and views**

Define read-only columns and row actions whose `allowed(request, datum)` returns
`datum.operable`. Index data comes from the latest successful inventory
execution visible to the caller or the mock fixture. The refresh view accepts
POST only, invokes `start_inventory()`, saves
`request.session['powerops_inventory_execution_id']`, and redirects.

The execution view returns JSON when requested by polling JavaScript and HTML
otherwise. Both forms include only safe fields:

```json
{
  "id": "execution-uuid",
  "workflow_name": "power_ops.planned_power_off",
  "state": "RUNNING",
  "verification_required": false
}
```

- [ ] **Step 7: Run and commit**

```bash
python -m stestr run \
  poweropsdashboard.tests.test_inventory_views \
  poweropsdashboard.tests.test_execution_views
git add powerops-dashboard/poweropsdashboard/presentation.py \
  powerops-dashboard/poweropsdashboard/hosts \
  powerops-dashboard/poweropsdashboard/tests/test_inventory_views.py \
  powerops-dashboard/poweropsdashboard/tests/test_execution_views.py
git commit -m "feat: show PowerOps inventory and execution state"
```

Expected: inventory is read-only, non-operable rows cannot launch actions and
polling never submits mutations.

---

### Task 4: Add guarded planned power-off and reboot forms

**Files:**
- Create: `powerops-dashboard/poweropsdashboard/submission.py`
- Create: `powerops-dashboard/poweropsdashboard/hosts/forms.py`
- Modify: `powerops-dashboard/poweropsdashboard/hosts/views.py`
- Modify: `powerops-dashboard/poweropsdashboard/hosts/urls.py`
- Modify: `powerops-dashboard/poweropsdashboard/hosts/tables.py`
- Create: `powerops-dashboard/poweropsdashboard/hosts/templates/powerops/compute_hosts/confirm_planned.html`
- Create: `powerops-dashboard/poweropsdashboard/tests/test_planned_forms.py`
- Create: `powerops-dashboard/poweropsdashboard/tests/test_planned_views.py`

**Interfaces:**
- Produces: `PlannedOperationForm(request, host_row, operation, *args, **kwargs)`.
- Produces: `workflow_input() -> dict[str, object]` with typed Boolean.
- Produces: `issue_submission_token(request, operation, host) -> str` and
  `consume_submission_token(request, token, operation, host) -> None`.
- Produces route: `planned/<operation>/<segment_uuid>/<host>`.

- [ ] **Step 1: Write failing form tests**

Cover `require_empty`, `live_migrate` and `stop`, with `require_empty` as the
default. Require `typed_host` to equal the canonical host byte-for-byte. Assert
`allow_hard_off` is absent for delegated users, visible for admin, and requires
a separate `confirm_hard_off` checkbox when true. A forged delegated POST with
either hard-off field must be invalid.

Assert `workflow_input()` returns:

```python
{
    'host': 'compute-01',
    'segment_uuid': '11111111-1111-1111-1111-111111111111',
    'instance_policy': 'require_empty',
    'allow_hard_off': False,
}
```

with `type(value) is bool` for the final value.

- [ ] **Step 2: Write failing preflight and duplicate-submit tests**

The initial POST from the host table starts a new read-only inventory refresh
and `power_ops.host_power_status`; the confirmation view is rendered only from
their successful outputs and displays every affected instance UUID, project
UUID and status. A failed/partial preflight returns 422 and no mutation method
call.

Issue a random single-use token into the session on confirmation GET. Two POSTs
with the same token yield one adapter call and HTTP 409 on the second. Consume
the token before calling Mistral so an uncertain timeout cannot be blindly
retried.

- [ ] **Step 3: Run and verify RED**

```bash
python -m stestr run \
  poweropsdashboard.tests.test_planned_forms \
  poweropsdashboard.tests.test_planned_views
```

Expected: forms and submission guard do not exist.

- [ ] **Step 4: Implement server-side typed validation**

Use Django `ChoiceField`, `CharField` and `BooleanField`; derive host and
segment from the trusted `HostRow`, not hidden POST values. `clean()` performs
the exact host confirmation and hard-off branch checks. `workflow_input()`
constructs a new mapping and never forwards `cleaned_data` wholesale.

- [ ] **Step 5: Implement the single-use session guard**

Store SHA-256 of a 32-byte random URL-safe token under a key derived from
operation and canonical host. Compare with `hmac.compare_digest`, delete the
stored digest before the backend call, and reject missing/reused tokens with
`DuplicateSubmission` mapped to HTTP 409. Do not store a workflow payload,
token or credential in the session.

- [ ] **Step 6: Submit one workflow and retain its UUID**

Map only `power_off` and `reboot`. On success, immediately save the returned
execution UUID in the session and redirect to its GET-only execution page. On
an exception before any UUID exists, return a sanitized 503/422 as classified.
On an uncertain response containing an execution UUID, render verification
required and never call `start_planned()` again.

In mock mode, catch `MockMutationDisabled` and render a clear preview-only
banner with HTTP 409; the adapter remains the enforcement point.

- [ ] **Step 7: Run and commit**

```bash
python -m stestr run \
  poweropsdashboard.tests.test_planned_forms \
  poweropsdashboard.tests.test_planned_views \
  poweropsdashboard.tests.test_mock_api
git add powerops-dashboard/poweropsdashboard/submission.py \
  powerops-dashboard/poweropsdashboard/hosts \
  powerops-dashboard/poweropsdashboard/tests/test_planned_forms.py \
  powerops-dashboard/poweropsdashboard/tests/test_planned_views.py
git commit -m "feat: guard planned PowerOps submissions"
```

Expected: preflight, hard-off and duplicate controls pass with one backend
submission maximum per UI token.

---

### Task 5: Add immutable two-phase return and protected resume

**Files:**
- Modify: `powerops-dashboard/poweropsdashboard/hosts/forms.py`
- Modify: `powerops-dashboard/poweropsdashboard/hosts/views.py`
- Modify: `powerops-dashboard/poweropsdashboard/hosts/urls.py`
- Create: `powerops-dashboard/poweropsdashboard/hosts/templates/powerops/compute_hosts/start_return.html`
- Create: `powerops-dashboard/poweropsdashboard/hosts/templates/powerops/compute_hosts/resume_return.html`
- Create: `powerops-dashboard/poweropsdashboard/tests/test_return_views.py`

**Interfaces:**
- Produces route: `return/start/<source_execution_id>`.
- Produces route: `return/resume/<execution_id>`.
- Consumes stopped manifest only from successful `power_ops.planned_power_off` output.
- Produces resume environment only through `MistralPowerOpsClient.resume_return()`.

- [ ] **Step 1: Write failing manifest-origin tests**

Assert `Power on for inspection` appears only for a successful exact
`power_ops.planned_power_off` execution whose output has a valid
`stopped_instance_ids: list[str]`. The start-return form has no manifest field.
A forged POST key `stopped_instance_ids` is ignored and the adapter receives
the source execution's server-read list.

Reject missing, duplicate, non-string or malformed UUID items with HTTP 422 and
no mutation call.

- [ ] **Step 2: Write failing paused-state/resume tests**

Before showing resume, require all of:

```python
execution.state == 'PAUSED'
paused_task.name == 'operator_inspection_gate'
status.power_state == 'power on'
status.nova_enabled is False
status.nova_state == 'up'
status.masakari_maintenance is True
manifest_restart_started is False
```

The form exposes one required Boolean confirmation named
`stale_domains_checked`. A checked form makes one `resume_return(execution_id)`
call; it does not accept an env, manifest, role, region, host or segment value
from the browser.

- [ ] **Step 3: Write failing current-user and no-retry tests**

Assert both start-return and resume routes rerun `authorize_user()` for the
current request. An operator whose allowlist membership was removed gets HTTP
403 even if the source execution was started while authorized. A timeout after
resume switches to verification required and subsequent GET polling never
calls resume again.

- [ ] **Step 4: Run and verify RED**

```bash
python -m stestr run poweropsdashboard.tests.test_return_views
```

Expected: return routes and forms are absent.

- [ ] **Step 5: Implement immutable start-return flow**

Read the source execution by URL UUID and validate its workflow and terminal
state. Decode its stored input and output server-side; validate the canonical
host and segment from the input and the stopped-instance manifest from the
output. Create a fresh payload containing only:

```python
{
    'host': source_input['host'],
    'segment_uuid': source_input['segment_uuid'],
    'stopped_instance_ids': list(source_output['stopped_instance_ids']),
}
```

Use the same single-use session-token guard as planned actions. The template
may display the manifest but contains no editable input for it.

- [ ] **Step 6: Implement strict resume flow**

Read execution, task list and fresh `host_power_status` output server-side.
Render the inspection checklist only after the six state predicates pass. On
POST, validate the checkbox, consume the session token and call only
`resume_return(execution_id)`, whose fixed environment is
`{'stale_domains_checked': True}`.

- [ ] **Step 7: Run and commit**

```bash
python -m stestr run \
  poweropsdashboard.tests.test_return_views \
  poweropsdashboard.tests.test_execution_views \
  poweropsdashboard.tests.test_auth
git add powerops-dashboard/poweropsdashboard/hosts \
  powerops-dashboard/poweropsdashboard/tests/test_return_views.py
git commit -m "feat: add guarded two-phase host return"
```

Expected: manifest immutability, current-user resume authorization and
no-retry presentation pass.

---

### Task 6: Finish sanitized errors, polling UI and local mock preview

**Files:**
- Create: `powerops-dashboard/poweropsdashboard/error_handling.py`
- Create: `powerops-dashboard/poweropsdashboard/static/poweropsdashboard/js/powerops.js`
- Create: `powerops-dashboard/poweropsdashboard/static/poweropsdashboard/css/powerops.css`
- Create: `powerops-dashboard/poweropsdashboard/test/preview_settings.py`
- Create: `powerops-dashboard/poweropsdashboard/test/preview_middleware.py`
- Create: `powerops-dashboard/README.rst`
- Create: `powerops-dashboard/poweropsdashboard/tests/test_error_handling.py`
- Create: `powerops-dashboard/poweropsdashboard/tests/test_preview.py`
- Modify: `powerops-dashboard/MANIFEST.in`

**Interfaces:**
- Produces: `classify_error(error, execution_id=None) -> SafeError`.
- Produces status codes: 403 authorization, 409 duplicate/mock mutation, 422 invalid preflight/input, 503 endpoint unavailable.
- Produces GET-only execution polling at a fixed five-second interval.
- Produces preview command bound to `127.0.0.1:8000`.

- [ ] **Step 1: Write failing error-sanitization tests**

Pass exceptions whose raw text contains `X-Auth-Token`, password, traceback,
BMC address and driver info. Assert the returned/operator-rendered message is
one fixed Russian message and contains none of the raw values. Assert the
status mapping above and `verification_required=True` when an execution UUID
exists after an uncertain error.

- [ ] **Step 2: Write failing polling and preview tests**

Inspect `powerops.js` and assert its timer issues only
`fetch(statusUrl, {method: 'GET'})`; reject `POST`, `PUT`, form submission and
recursive retry calls.

Load `preview_settings` and assert:

```python
POWEROPS_MOCK_MODE is True
POWEROPS_REGION_NAME == 'RegionOne'
POWEROPS_ALLOWED_PROJECT_NAMES == ['operations']
POWEROPS_ALLOWED_USER_NAMES == ['power-operator']
```

Use the Django client with preview middleware and prove inventory pages render,
while planned/start-return/resume POSTs cannot reach a live adapter.

- [ ] **Step 3: Run and verify RED**

```bash
python -m stestr run \
  poweropsdashboard.tests.test_error_handling \
  poweropsdashboard.tests.test_preview
```

Expected: error classifier and preview settings are absent.

- [ ] **Step 4: Implement fixed safe errors and GET polling**

Define `SafeError(status_code, message, verification_required)` and map known
exception classes without including `str(error)`. JavaScript updates state,
task and status elements from the execution JSON route every five seconds and
stops on `SUCCESS`, `ERROR`, `CANCELLED` or `verification_required=true`.

- [ ] **Step 5: Implement preview-only authentication fixture**

The middleware activates only when `POWEROPS_MOCK_MODE is True`, installs one
in-memory `openstack_auth.user.User` equivalent with exact admin or delegated
fixture roles, and supplies the one fake workflow service endpoint. It rejects
non-loopback `REMOTE_ADDR`. Production test settings do not install this
middleware.

The README command is:

```bash
tox -e venv -- python manage.py runserver 127.0.0.1:8000 \
  --settings=poweropsdashboard.test.preview_settings
```

State immediately below it that preview POST mutations are deliberately
blocked and the server must never bind to a non-loopback address.

- [ ] **Step 6: Run the full plugin suite and build the wheel**

```bash
tox -e py3
tox -e pep8
python setup.py bdist_wheel
python -m compileall -q poweropsdashboard
git diff --check
```

Expected: all plugin tests and lint pass; `dist/` contains exactly one
`powerops_dashboard-*.whl`. Record its filename and SHA-256 in the integration
plan execution evidence.

- [ ] **Step 7: Start the local preview for visual review**

Starting the loopback preview is non-mutating and may be done in this stage:

```bash
tox -e venv -- python manage.py runserver 127.0.0.1:8000 \
  --settings=poweropsdashboard.test.preview_settings
```

Verify navigation, the one-region label, admin/delegated visibility, blocked
row, all-project impact, hard-off confirmation, paused inspection gate,
verification-required error and responsive layout. Save screenshots as test
evidence only if they contain no credentials or real infrastructure data.

- [ ] **Step 8: Commit the finished package**

```bash
git add powerops-dashboard
git commit -m "feat: deliver mockable Horizon PowerOps dashboard"
```

Expected: the standalone source package is tracked; generated `.tox`, build
and wheel directories remain ignored until the delivery task explicitly hashes
the selected wheel.
