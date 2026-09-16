# Mistral PowerOps RBAC, Resume and Inventory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the existing Mistral PowerOps workflows enforce the approved `admin`/delegated-operator RBAC contract, protect workflow resume, and expose a safe all-project host inventory for Horizon.

**Architecture:** A shared Mistral authorization service evaluates only trusted request/action context and is called at the API, Engine and action boundaries. The Engine stores resume attribution in internal workflow runtime context in the same transaction that resumes the workflow. A new read-only composite action builds inventory from complete Masakari, Nova and Ironic service datasets while every mutating action retains the existing exact-host, etcd-lock and fail-safe state machine.

**Tech Stack:** Mistral stable/2025.1, patched `mistral-lib`, Pecan/WSME API, oslo.context/RPC, SQLAlchemy models, openstacksdk, YAQL/Mistral workbook v2, `stestr`, `unittest.mock`.

**Spec:** `docs/superpowers/specs/2026-09-02-horizon-powerops-integration-design.md`

## Global Constraints

- Start from completed Mistral PowerOps commit `3e4fe82455de7473809b0e0bc677fa3df3a3d1e2` in `worktrees/mistral-powerops`.
- Consume the `mistral-lib` interface defined in `docs/superpowers/plans/2026-09-02-mistral-lib-powerops-security-context.md`.
- Authorization is exactly `admin OR (powerops_operator AND exact project allowlist AND exact user allowlist)`.
- The `admin` branch bypasses both allowlists; empty allowlists disable only the delegated branch.
- `powerops_operator` is a human role and is not added to Mistral service credentials.
- `allow_hard_off` defaults to Boolean `false` and Boolean `true` is accepted only for the `admin` authorization branch.
- Request roles, user ID and project ID come only from validated Keystone/Mistral context, never workflow input or environment.
- PowerOps workflow resume must reauthorize the current RPC request context and atomically persist current actor IDs, branch and UTC timestamp in internal runtime context.
- `return_to_service` requires that internal resume record and the existing exact Boolean `stale_domains_checked=true` gate.
- One installation uses one configured `CONF.powerops.region_name`; region is never a workflow input.
- Inventory and mutations discover Nova instances with `details=True`, `all_projects=True`; caller project is not a blast-radius boundary.
- No task may run a live workflow, Nova mutation, Masakari mutation, Ironic power action or BMC command.
- Export six new Mistral patches numbered `0011` through `0016` without rewriting patches `0001` through `0010`.

---

### Task 1: Propagate trusted roles and resume metadata to actions

**Files:**
- Modify: `worktrees/mistral-powerops/mistral/context.py`
- Modify: `worktrees/mistral-powerops/mistral/engine/actions.py`
- Modify: `worktrees/mistral-powerops/mistral/tests/unit/engine/test_action_context.py`
- Modify: `worktrees/mistral-powerops/mistral/tests/unit/actions/powerops/fakes.py`

**Interfaces:**
- Consumes: `mistral_lib.actions.context.SecurityContext` fields `user_id` and
  `roles`.
- Consumes: `ExecutionContext.workflow_resume_authorization`.
- Produces: action security fields copied from current validated `MistralContext`.
- Produces: action execution field copied only from `WorkflowExecution.runtime_context['__powerops_resume_authorization']`.

- [ ] **Step 1: Write failing action-context tests**

Extend `ActionContextTest.test_context` by setting a context with exact identity
data before workflow start and asserting the action receives it:

```python
self.ctx.user_id = 'starter-user-id'
self.ctx.project_id = 'starter-project-id'
self.ctx.roles = ['powerops_operator']
auth_context.set_ctx(self.ctx)

# Existing workflow execution and action assertions run here.
self.assertEqual('starter-user-id', action_context.security.user_id)
self.assertEqual(
    ['powerops_operator'],
    action_context.security.roles,
)
```

Add a focused unit case for `_prepare_execution_context()` whose workflow
runtime context contains:

```python
RESUME_RECORD = {
    'user_id': 'resume-user-id',
    'project_id': 'resume-project-id',
    'authorization_branch': 'admin',
    'authorized_at': '2026-09-02T10:00:00+00:00',
}
```

Assert `workflow_resume_authorization == RESUME_RECORD`, and add a negative
case that the field is `None` when the internal key is absent.

- [ ] **Step 2: Run focused tests and verify RED**

```bash
cd worktrees/mistral-powerops
PYTHONPATH="$PWD/../../worktrees/mistral-lib-powerops:$PWD" \
  python -m stestr run mistral.tests.unit.engine.test_action_context
```

Expected: the new identity/resume assertions fail because Mistral does not yet
populate those fields.

- [ ] **Step 3: Populate the trusted security context**

Add only validated request-context values in `create_action_context()`:

```python
security_ctx = lib_ctx.SecurityContext(
    # Existing keyword arguments stay present.
    project_id=context.project_id,
    project_name=context.project_name,
    user_id=context.user_id,
    user_name=context.user_name,
    roles=list(context.roles or []),
    # Existing auth_token/trust/catalog keyword arguments stay present.
)
```

In `mistral/engine/actions.py`, define the internal key once and attach a
defensive copy only for workflow-backed actions:

```python
POWEROPS_RESUME_AUTH_KEY = '__powerops_resume_authorization'

def _prepare_execution_context(self):
    res = {}

    if self.task_ex:
        wf_ex = self.task_ex.workflow_execution
        res['workflow_execution_id'] = wf_ex.id
        res['task_execution_id'] = self.task_ex.id
        res['workflow_name'] = wf_ex.name
        record = (wf_ex.runtime_context or {}).get(
            POWEROPS_RESUME_AUTH_KEY
        )
        if record:
            res['workflow_resume_authorization'] = dict(record)

    # Preserve the existing action execution and callback fields.
    return res
```

Move the key to `mistral/services/powerops.py` in Task 2 and replace this local
constant with the shared import in the same commit as Task 2.

- [ ] **Step 4: Extend the PowerOps test context factory**

Change `fakes.action_context()` to accept exact trusted data:

```python
def action_context(execution_id, project_name='operations',
                   user_name='power-operator',
                   project_id='operations-project-id',
                   user_id='power-operator-id',
                   roles=None, resume_authorization=None):
    security = actions.SecurityContext(
        project_id=project_id,
        project_name=project_name,
        user_id=user_id,
        user_name=user_name,
        roles=list(roles or ['powerops_operator']),
    )
    execution = actions.ExecutionContext(
        workflow_execution_id=execution_id,
        action_execution_id=execution_id,
        workflow_resume_authorization=resume_authorization,
    )
    return actions.ActionContext(security, execution)
```

Existing tests keep delegated behavior because their existing allowlist fixture
matches the new factory defaults.

- [ ] **Step 5: Run focused tests and commit**

```bash
PYTHONPATH="$PWD/../../worktrees/mistral-lib-powerops:$PWD" \
  python -m stestr run \
  mistral.tests.unit.engine.test_action_context \
  mistral.tests.unit.actions.powerops
git add mistral/context.py mistral/engine/actions.py \
  mistral/tests/unit/engine/test_action_context.py \
  mistral/tests/unit/actions/powerops/fakes.py
git commit -m "feat: propagate trusted PowerOps action identity"
```

Expected: the focused suites pass and this becomes patch `0011`.

---

### Task 2: Implement the exact shared authorization contract

**Files:**
- Create: `worktrees/mistral-powerops/mistral/services/powerops.py`
- Create: `worktrees/mistral-powerops/mistral/tests/unit/services/test_powerops.py`
- Modify: `worktrees/mistral-powerops/mistral/engine/actions.py`

**Interfaces:**
- Produces: `authorize(subject, allow_hard_off=False, error_cls=exc.NotAllowedException) -> str`.
- Produces: branches `admin` and `powerops_operator`.
- Produces: `POWEROPS_WORKFLOW_NAMES: frozenset[str]`.
- Produces: `POWEROPS_RESUME_WORKFLOW = 'power_ops.power_on_and_return'`.
- Produces: `POWEROPS_RESUME_AUTH_KEY = '__powerops_resume_authorization'`.
- Produces: `reject_reserved_auth_fields(workflow_input, env) -> None`.

- [ ] **Step 1: Write the authorization matrix tests**

Create parameterized/subtest cases covering this exact matrix:

```python
cases = (
    ('admin outside lists', ['admin'], 'other-project', 'other-user',
     False, 'admin'),
    ('delegated exact', ['powerops_operator'], 'operations',
     'power-operator', False, 'powerops_operator'),
    ('delegated project mismatch', ['powerops_operator'], 'other-project',
     'power-operator', False, None),
    ('delegated user mismatch', ['powerops_operator'], 'operations',
     'other-user', False, None),
    ('unrelated role', ['member'], 'operations', 'power-operator',
     False, None),
    ('delegated hard off', ['powerops_operator'], 'operations',
     'power-operator', True, None),
    ('admin hard off', ['admin'], 'other-project', 'other-user',
     True, 'admin'),
)
```

Add separate cases proving role comparison is exact (`Admin` and
`PowerOps_Operator` are denied), both empty allowlists deny delegated access,
and malformed non-string role data is denied.

- [ ] **Step 2: Write reserved-field rejection tests**

Assert each of these top-level keys is rejected in workflow input or resume
environment: `roles`, `is_admin`, `authorization_branch`,
`workflow_resume_authorization`, `__powerops_resume_authorization`. Assert
ordinary inputs such as `host`, `segment_uuid`, `instance_policy`,
`allow_hard_off` and `stale_domains_checked` pass.

- [ ] **Step 3: Run the service tests and verify RED**

```bash
PYTHONPATH="$PWD/../../worktrees/mistral-lib-powerops:$PWD" \
  python -m stestr run mistral.tests.unit.services.test_powerops
```

Expected: import failure for `mistral.services.powerops`.

- [ ] **Step 4: Implement the shared service**

Use this exact public surface:

```python
ADMIN_ROLE = 'admin'
OPERATOR_ROLE = 'powerops_operator'
ADMIN_BRANCH = 'admin'
OPERATOR_BRANCH = 'powerops_operator'
POWEROPS_WORKFLOW_NAMES = frozenset({
    'power_ops.host_inventory',
    'power_ops.host_power_status',
    'power_ops.planned_power_off',
    'power_ops.planned_reboot',
    'power_ops.power_on_and_return',
})
POWEROPS_RESUME_WORKFLOW = 'power_ops.power_on_and_return'
POWEROPS_RESUME_AUTH_KEY = '__powerops_resume_authorization'
RESERVED_AUTH_FIELDS = frozenset({
    'roles',
    'is_admin',
    'authorization_branch',
    'workflow_resume_authorization',
    POWEROPS_RESUME_AUTH_KEY,
})


def authorize(subject, allow_hard_off=False,
              error_cls=exc.NotAllowedException):
    roles = getattr(subject, 'roles', None) or []

    if not all(isinstance(role, str) for role in roles):
        raise error_cls('caller is not authorized for PowerOps')

    if ADMIN_ROLE in roles:
        branch = ADMIN_BRANCH
    elif (
            OPERATOR_ROLE in roles
            and getattr(subject, 'project_name', None)
            in CONF.powerops.allowed_project_names
            and getattr(subject, 'user_name', None)
            in CONF.powerops.allowed_user_names):
        branch = OPERATOR_BRANCH
    else:
        raise error_cls('caller is not authorized for PowerOps')

    if allow_hard_off is True and branch != ADMIN_BRANCH:
        raise error_cls('hard-off escalation requires the admin role')

    return branch


def reject_reserved_auth_fields(workflow_input, env):
    for values in (workflow_input or {}, env or {}):
        if not isinstance(values, dict):
            raise exc.InputException('PowerOps input must be a mapping')
        if RESERVED_AUTH_FIELDS.intersection(values):
            raise exc.InputException(
                'PowerOps authorization fields are server controlled'
            )
```

Implement `is_powerops_workflow(name)` and
`is_powerops_resume_workflow(name)` as exact membership/equality checks. Import
`POWEROPS_RESUME_AUTH_KEY` from this module in `mistral/engine/actions.py`.

- [ ] **Step 5: Run, lint and commit**

```bash
PYTHONPATH="$PWD/../../worktrees/mistral-lib-powerops:$PWD" \
  python -m stestr run mistral.tests.unit.services.test_powerops
tox -e pep8 -- mistral/services/powerops.py \
  mistral/tests/unit/services/test_powerops.py
git add mistral/services/powerops.py \
  mistral/tests/unit/services/test_powerops.py mistral/engine/actions.py
git commit -m "feat: define PowerOps role authorization"
```

Expected: the matrix passes and this becomes patch `0012`.

---

### Task 3: Reject unauthorized PowerOps workflow starts at the API

**Files:**
- Modify: `worktrees/mistral-powerops/mistral/api/controllers/v2/execution.py`
- Create: `worktrees/mistral-powerops/mistral/tests/unit/api/v2/test_executions_powerops.py`

**Interfaces:**
- Consumes: `powerops.authorize()` and `POWEROPS_WORKFLOW_NAMES`.
- Produces: synchronous HTTP 403 for unauthorized exact PowerOps workflow starts.
- Preserves: action-side checks as the authoritative wrapper/direct-action boundary.

- [ ] **Step 1: Write API start tests**

Create API tests for workflow-name and workflow-ID start forms. Mock
`db_api.get_workflow_definition()` to return a definition with exact name
`power_ops.planned_power_off`. Assert:

```python
response = self.app.post_json(
    '/v2/executions',
    {
        'workflow_name': 'power_ops.planned_power_off',
        'input': json.dumps({
            'host': 'compute-01',
            'segment_uuid': 'segment-uuid',
            'allow_hard_off': False,
        }),
    },
    expect_errors=True,
)
self.assertEqual(403, response.status_int)
self.mock_start_workflow.assert_not_called()
```

Add positive `admin` and exact delegated cases, an unrelated workflow case
that remains governed only by normal Mistral policy, an admin hard-off case,
a delegated hard-off 403, and rejection of every reserved authorization field
before `EngineClient.start_workflow()`.

- [ ] **Step 2: Run and verify RED**

```bash
PYTHONPATH="$PWD/../../worktrees/mistral-lib-powerops:$PWD" \
  python -m stestr run \
  mistral.tests.unit.api.v2.test_executions_powerops
```

Expected: unauthorized PowerOps starts reach the mocked engine or return 201.

- [ ] **Step 3: Add exact workflow resolution and early enforcement**

After merging source-execution fields and before creating the Engine client,
resolve the canonical definition for either ID or name:

```python
workflow_identifier = result_exec_dict.get(
    'workflow_id',
    result_exec_dict.get('workflow_name'),
)
workflow_namespace = result_exec_dict.get('workflow_namespace', '')
workflow_definition = db_api.get_workflow_definition(
    workflow_identifier,
    namespace=workflow_namespace,
)

if powerops.is_powerops_workflow(workflow_definition.name):
    workflow_input = result_exec_dict.get('input') or {}
    params = result_exec_dict.get('params') or {}
    env = params.get('env') or {}
    allow_hard_off = workflow_input.get('allow_hard_off', False)
    powerops.reject_reserved_auth_fields(workflow_input, env)
    powerops.authorize(
        context.ctx(),
        allow_hard_off=allow_hard_off,
    )
```

The existing WSME resource conversion already turns JSON `input` and `params`
into mappings; tests must assert that malformed mappings retain the existing
400 behavior. Pass the already resolved identifier to the existing engine
call without adding role, region or authorization parameters.

- [ ] **Step 4: Run regression tests and commit**

```bash
PYTHONPATH="$PWD/../../worktrees/mistral-lib-powerops:$PWD" \
  python -m stestr run \
  mistral.tests.unit.api.v2.test_executions_powerops \
  mistral.tests.unit.api.v2.test_executions
git add mistral/api/controllers/v2/execution.py \
  mistral/tests/unit/api/v2/test_executions_powerops.py
git commit -m "feat: reject unauthorized PowerOps starts"
```

Expected: PowerOps cases return the declared status and ordinary execution API
tests remain green. This is patch `0013`.

---

### Task 4: Reauthorize and attribute protected workflow resume

**Files:**
- Modify: `worktrees/mistral-powerops/mistral/services/powerops.py`
- Modify: `worktrees/mistral-powerops/mistral/api/controllers/v2/execution.py`
- Modify: `worktrees/mistral-powerops/mistral/engine/default_engine.py`
- Modify: `worktrees/mistral-powerops/mistral/actions/powerops/return_host.py`
- Modify: `worktrees/mistral-powerops/mistral/tests/unit/api/v2/test_executions_powerops.py`
- Create: `worktrees/mistral-powerops/mistral/tests/unit/engine/test_powerops_resume.py`

**Interfaces:**
- Produces: `build_resume_authorization(subject, branch, now=None) -> dict[str, str]`.
- Produces: exact record keys `user_id`, `project_id`, `authorization_branch`, `authorized_at`.
- Produces: `require_resume_authorization(action_context) -> dict[str, str]`.
- Persists: `WorkflowExecution.runtime_context['__powerops_resume_authorization']`.

- [ ] **Step 1: Write failing API resume tests**

Use a paused `WorkflowExecution` named `power_ops.power_on_and_return`. Prove
that current unauthorized roles return 403 and never call the RPC client;
authorized admin and allowlisted operator requests pass only with this exact
environment:

```python
{'stale_domains_checked': True}
```

Assert missing env, string `'true'`, Boolean `False`, additional keys and every
reserved auth key return 400 before RPC. An unrelated paused workflow must
retain the existing generic resume behavior.

- [ ] **Step 2: Write failing Engine transaction tests**

In `test_powerops_resume.py`, run `DefaultEngine.resume_workflow()` under a
current context containing `user_id`, `project_id`, roles and names. Patch the
workflow handler so no task executes. Assert, inside a subsequent DB
transaction:

```python
self.assertEqual(
    {
        'user_id': 'resume-user-id',
        'project_id': 'resume-project-id',
        'authorization_branch': 'powerops_operator',
        'authorized_at': '2026-09-02T10:00:00+00:00',
    },
    wf_ex.runtime_context[powerops.POWEROPS_RESUME_AUTH_KEY],
)
```

Unit-test `build_resume_authorization()` with its `now` argument. In the Engine
test, patch that helper to return the fixed record above. Add rollback proof:
make `wf_handler.resume_workflow()` raise and assert a new DB session cannot
see the record. Add unauthorized Engine invocation proof and
ordinary-workflow proof.

- [ ] **Step 3: Write failing return-action record tests**

Add cases to `test_return_host.py` that invoke `ReturnToServiceAction` with an
authorized context but no record, a malformed record, and a valid record. The
first two must fail before `connection_from_conf()`; the valid case proceeds to
the existing host revalidation.

Add a wrapper-workflow case in which an unprotected parent invokes the
PowerOps return action without an Engine-created record. It must fail before
client creation. This proves a direct or nested action cannot bypass resume
authorization.

- [ ] **Step 4: Run and verify RED**

```bash
PYTHONPATH="$PWD/../../worktrees/mistral-lib-powerops:$PWD" \
  python -m stestr run \
  mistral.tests.unit.api.v2.test_executions_powerops \
  mistral.tests.unit.engine.test_powerops_resume \
  mistral.tests.unit.actions.powerops.test_return_host
```

Expected: resume is not reauthorized, no internal record is persisted and the
return action accepts a missing record.

- [ ] **Step 5: Implement strict resume helpers**

Add to `mistral/services/powerops.py`:

```python
def validate_resume_env(env):
    if env != {'stale_domains_checked': True}:
        raise exc.InputException(
            'PowerOps resume requires stale_domains_checked=true only'
        )


def build_resume_authorization(subject, branch, now=None):
    user_id = getattr(subject, 'user_id', None)
    project_id = getattr(subject, 'project_id', None)
    if not user_id or not project_id:
        raise exc.NotAllowedException(
            'PowerOps resume requires current actor identifiers'
        )
    timestamp = now or datetime.datetime.now(datetime.timezone.utc)
    return {
        'user_id': user_id,
        'project_id': project_id,
        'authorization_branch': branch,
        'authorized_at': timestamp.isoformat(),
    }


def require_resume_authorization(action_context):
    record = action_context.execution.workflow_resume_authorization
    required = {
        'user_id', 'project_id', 'authorization_branch', 'authorized_at'
    }
    if (
            not isinstance(record, dict)
            or set(record) != required
            or record['authorization_branch']
            not in {ADMIN_BRANCH, OPERATOR_BRANCH}
            or not all(isinstance(record[key], str) and record[key]
                       for key in required)):
        raise exc.NotAllowedException(
            'PowerOps return requires trusted resume authorization'
        )
    return dict(record)
```

- [ ] **Step 6: Enforce resume at API and Engine boundaries**

In API `put()`, load `workflow_name` with the existing ID/root fields. Before
the RPC call for `RUNNING`, call `authorize()`,
`reject_reserved_auth_fields({}, env)` and `validate_resume_env(env)` only for
`power_ops.power_on_and_return`.

In `DefaultEngine.resume_workflow()`, keep all work inside its existing
`db_api.transaction()`:

```python
wf_ex = db_api.get_workflow_execution(wf_ex_id)

if powerops.is_powerops_resume_workflow(wf_ex.workflow_name):
    powerops.validate_resume_env(env)
    branch = powerops.authorize(context.ctx())
    record = powerops.build_resume_authorization(
        context.ctx(), branch
    )
    runtime_context = dict(wf_ex.runtime_context or {})
    runtime_context[powerops.POWEROPS_RESUME_AUTH_KEY] = record
    wf_ex.runtime_context = runtime_context

wf_handler.resume_workflow(wf_ex, env=env)
```

This placement makes record persistence and the state transition one database
transaction; do not accept a record as an API, RPC, workflow or environment
argument.

- [ ] **Step 7: Require the record in `return_to_service`**

At the start of `ReturnToServiceAction.run()`, before creating clients, call:

```python
resume_authorization = powerops.require_resume_authorization(context)
```

Pass only its four safe fields into the process audit details. Keep the
existing `stale_domains_checked is True`, stable-power-on, Nova-disabled,
Masakari-maintenance and stopped-manifest checks unchanged.

- [ ] **Step 8: Run tests and commit**

```bash
PYTHONPATH="$PWD/../../worktrees/mistral-lib-powerops:$PWD" \
  python -m stestr run \
  mistral.tests.unit.api.v2.test_executions_powerops \
  mistral.tests.unit.engine.test_powerops_resume \
  mistral.tests.unit.actions.powerops.test_return_host
git add mistral/services/powerops.py \
  mistral/api/controllers/v2/execution.py \
  mistral/engine/default_engine.py \
  mistral/actions/powerops/return_host.py \
  mistral/tests/unit/api/v2/test_executions_powerops.py \
  mistral/tests/unit/engine/test_powerops_resume.py \
  mistral/tests/unit/actions/powerops/test_return_host.py
git commit -m "feat: reauthorize PowerOps workflow resume"
```

Expected: API, atomicity and action tests pass. This is patch `0014`.

---

### Task 5: Apply RBAC, hard-off and audit rules to every PowerOps action

**Files:**
- Modify: `worktrees/mistral-powerops/mistral/actions/powerops/base.py`
- Modify: `worktrees/mistral-powerops/mistral/actions/powerops/planned.py`
- Modify: `worktrees/mistral-powerops/mistral/actions/powerops/return_host.py`
- Modify: `worktrees/mistral-powerops/mistral/actions/powerops/exceptions.py`
- Modify: `worktrees/mistral-powerops/mistral/tests/unit/actions/powerops/test_planned.py`
- Modify: `worktrees/mistral-powerops/mistral/tests/unit/actions/powerops/test_return_host.py`

**Interfaces:**
- Consumes: `powerops.authorize(subject, allow_hard_off=False,
  error_cls=PowerOpsUnauthorized)`.
- Produces: `_authorize(context, allow_hard_off=False) -> str`.
- Produces audit fields: caller IDs, branch, region, host, segment, operation,
  policy, hard-off authorization, workflow/action execution IDs, outcome and
  fail-safe error types.

- [ ] **Step 1: Replace old allowlist tests with the complete matrix**

For both planned actions and both return actions, prove authorization runs
before `clients.connection_from_conf()`. Include admin outside allowlists,
exact delegated match, either delegated mismatch, unrelated role and exact
case mismatch. Add hard-off tests proving delegated Boolean `true` is rejected
before host resolution while admin Boolean `true` proceeds.

- [ ] **Step 2: Write safe audit tests**

Patch `LOG.info` and assert the structured message includes user/project IDs,
authorization branch, configured region, host, segment, operation,
`instance_policy`, `hard_off_authorized`, workflow/action execution IDs and
outcome. Assert serialized log arguments do not contain `auth_token`,
`password`, service catalog or BMC connection information.

- [ ] **Step 3: Run and verify RED**

```bash
PYTHONPATH="$PWD/../../worktrees/mistral-lib-powerops:$PWD" \
  python -m stestr run mistral.tests.unit.actions.powerops
```

Expected: admin bypass/hard-off/audit cases fail under the old allowlist-only
implementation.

- [ ] **Step 4: Route action authorization through the shared service**

Implement:

```python
def _authorize(self, context, allow_hard_off=False):
    return powerops.authorize(
        context.security,
        allow_hard_off=allow_hard_off,
        error_cls=exceptions.PowerOpsUnauthorized,
    )
```

Store the returned branch on the action only after success. Extend
`_run_locked()` with `allow_hard_off=False`, pass the planned action's exact
Boolean to it, and leave other actions at the default.

- [ ] **Step 5: Emit bounded process audit fields**

Use positional log arguments, not a dump of either context:

```python
LOG.info(
    'PowerOps audit operation=%s outcome=%s region=%s host=%s '
    'segment_uuid=%s user_id=%s project_id=%s auth_branch=%s '
    'instance_policy=%s hard_off_authorized=%s '
    'workflow_execution_id=%s action_execution_id=%s details=%s',
    operation,
    outcome,
    CONF.powerops.region_name,
    self.host,
    self.segment_uuid,
    context.security.user_id,
    context.security.project_id,
    self._authorization_branch,
    getattr(self, 'instance_policy', None),
    getattr(self, 'allow_hard_off', False) is True,
    context.execution.workflow_execution_id,
    context.execution.action_execution_id,
    details,
)
```

On denial, log only outcome, actor IDs and branch `denied`; do not log token,
catalog, password, raw exception string or configuration secrets. Describe
this as a non-durable process log.

- [ ] **Step 6: Run and commit**

```bash
PYTHONPATH="$PWD/../../worktrees/mistral-lib-powerops:$PWD" \
  python -m stestr run mistral.tests.unit.actions.powerops
tox -e pep8 -- mistral/actions/powerops \
  mistral/tests/unit/actions/powerops
git add mistral/actions/powerops \
  mistral/tests/unit/actions/powerops
git commit -m "feat: enforce PowerOps roles and hard-off policy"
```

Expected: all existing coordination/fail-safe tests plus the new RBAC cases
pass. This is patch `0015`.

---

### Task 6: Add fail-closed all-project host inventory

**Files:**
- Create: `worktrees/mistral-powerops/mistral/actions/powerops/inventory.py`
- Modify: `worktrees/mistral-powerops/mistral/actions/powerops/clients.py`
- Modify: `worktrees/mistral-powerops/mistral/actions/powerops/exceptions.py`
- Modify: `worktrees/mistral-powerops/setup.cfg`
- Modify: `worktrees/mistral-powerops/etc/mistral/power_ops.yaml`
- Create: `worktrees/mistral-powerops/mistral/tests/unit/actions/powerops/test_inventory.py`
- Modify: `worktrees/mistral-powerops/mistral/tests/unit/actions/powerops/test_registration.py`
- Modify: `worktrees/mistral-powerops/mistral/tests/unit/actions/powerops/test_workbook.py`

**Interfaces:**
- Produces action: `powerops.host_inventory` with no workflow input.
- Produces workflow: `power_ops.host_inventory` with output `result`.
- Produces: `CloudClients.host_inventory() -> list[dict]`.
- Produces row keys: `region_name`, `segment_uuid`, `host`,
  `ironic_node_uuid`, `power_state`, `target_power_state`,
  `ironic_last_error`, `nova_status`, `nova_state`,
  `masakari_maintenance`, `instance_count`, `instances`, `operable`,
  `blocking_reason`.
- Produces instance keys: `id`, `project_id`, `status`.

- [ ] **Step 1: Write global dataset and read-only tests**

Test one successful inventory with two projects on one host and assert Nova is
called exactly as:

```python
connection.compute.servers.assert_called_once_with(
    details=True,
    all_projects=True,
)
```

Assert the inventory path makes only list/read calls: bare-metal node listing,
Nova compute service listing, Nova server listing, Masakari segment/host GETs.
Explicitly assert no SDK `set_*`, `stop_server`, `start_server`,
`live_migrate_server`, `enable_service`, `disable_service` or adapter mutation
method is called.

- [ ] **Step 2: Write fail-closed and per-row degradation tests**

Cover these exact outcomes:

- failure to list any one required global dataset raises
  `InventoryUnavailable` and returns no partial list;
- duplicate canonical Masakari host across segments yields non-operable rows
  with `blocking_reason='ambiguous_masakari_host'`;
- zero/multiple Nova or Ironic matches yields a non-operable row with
  `missing_nova_service`, `ambiguous_nova_service`, `missing_ironic_node` or
  `ambiguous_ironic_node`;
- an incompatible Ironic node is visible but non-operable with
  `ironic_node_incompatible`;
- malformed instance identity/project/status marks its canonical host
  non-operable with `invalid_instance_data`;
- a server without a canonical `compute_host` raises `InventoryUnavailable`
  because its host-wide impact cannot be attributed safely;
- returned mappings contain only the declared keys and do not contain token,
  password, BMC address, `driver_info`, `instance_info` or service catalog.

- [ ] **Step 3: Run and verify RED**

```bash
PYTHONPATH="$PWD/../../worktrees/mistral-lib-powerops:$PWD" \
  python -m stestr run \
  mistral.tests.unit.actions.powerops.test_inventory \
  mistral.tests.unit.actions.powerops.test_registration \
  mistral.tests.unit.actions.powerops.test_workbook
```

Expected: inventory module, entry point and workflow are absent.

- [ ] **Step 4: Implement complete snapshot collection**

Use one shared service deadline and materialize every dataset before building
rows:

```python
def host_inventory(self):
    deadline = self._deadline(CONF.powerops.service_timeout)
    nodes = self._call_with_deadline(
        lambda: list(self.connection.baremetal.nodes(details=True)),
        deadline,
        'timed out listing Ironic nodes',
    )
    services = self._call_with_deadline(
        lambda: list(self.connection.compute.services(
            binary='nova-compute'
        )),
        deadline,
        'timed out listing Nova compute services',
    )
    servers = self._call_with_deadline(
        lambda: list(self.connection.compute.servers(
            details=True, all_projects=True
        )),
        deadline,
        'timed out listing Nova instances',
    )
    segments_and_hosts = self._list_masakari_inventory(deadline)

    return self._build_inventory_rows(
        segments_and_hosts, nodes, services, servers
    )
```

`_list_masakari_inventory()` performs `GET /segments` and exactly one
`GET /segments/<uuid>/hosts` per valid segment. Validate list response shapes
before row construction. `_build_inventory_rows()` treats Masakari hosts as
the canonical row source, compares exact host strings, sorts rows by
`(segment_uuid, host or '')`, and sorts instances by UUID. Blocking reasons
are fixed identifiers from the preceding test list, never raw exception text.

- [ ] **Step 5: Implement the authorized action and registration**

```python
class HostInventoryAction(base.PowerOpsAction):
    """Return a read-only all-project PowerOps host snapshot."""

    def run(self, context):
        if not CONF.powerops.enabled:
            raise exceptions.PowerOpsDisabled()

        self._authorization_branch = self._authorize(context)
        cloud = clients.CloudClients(clients.connection_from_conf())
        result = cloud.host_inventory()
        self._audit(
            context,
            'host_inventory',
            'success',
            {'host_count': len(result)},
        )
        return result
```

Because this action has no host/segment input and performs no mutation, it does
not use `_run_locked()` or the etcd host lock. Add the setup entry point:

```ini
powerops.host_inventory = mistral.actions.powerops.inventory:HostInventoryAction
```

- [ ] **Step 6: Add the workbook workflow**

Insert before `host_power_status`:

```yaml
  host_inventory:
    tasks:
      inventory:
        action: powerops.host_inventory
        publish:
          result: <% task().result %>
    output:
      result: <% $.result %>
```

Update registration/workbook expectations to exactly six actions and five
workflows. Assert the inventory definition has no input and no mutation action
name.

- [ ] **Step 7: Run all affected suites and commit**

```bash
PYTHONPATH="$PWD/../../worktrees/mistral-lib-powerops:$PWD" \
  python -m stestr run \
  mistral.tests.unit.actions.powerops \
  mistral.tests.unit.services.test_powerops \
  mistral.tests.unit.api.v2.test_executions_powerops \
  mistral.tests.unit.engine.test_powerops_resume \
  mistral.tests.unit.engine.test_action_context
tox -e pep8 -- mistral/actions/powerops \
  mistral/services/powerops.py \
  mistral/tests/unit/actions/powerops \
  mistral/tests/unit/services/test_powerops.py \
  mistral/tests/unit/api/v2/test_executions_powerops.py \
  mistral/tests/unit/engine/test_powerops_resume.py
git add mistral/actions/powerops mistral/tests/unit/actions/powerops \
  mistral/services/powerops.py setup.cfg etc/mistral/power_ops.yaml
git commit -m "feat: expose read-only PowerOps host inventory"
```

Expected: authorization, inventory, workflow, registration and legacy
PowerOps tests pass. This is patch `0016`.

---

### Task 7: Verify regression boundary and export patches

**Files:**
- Create: `patches/mistral/0011-feat-propagate-trusted-PowerOps-action-identity.patch`
- Create: `patches/mistral/0012-feat-define-PowerOps-role-authorization.patch`
- Create: `patches/mistral/0013-feat-reject-unauthorized-PowerOps-starts.patch`
- Create: `patches/mistral/0014-feat-reauthorize-PowerOps-workflow-resume.patch`
- Create: `patches/mistral/0015-feat-enforce-PowerOps-roles-and-hard-off-policy.patch`
- Create: `patches/mistral/0016-feat-expose-read-only-PowerOps-host-inventory.patch`

**Interfaces:**
- Produces: six ordered patches on top of the existing ten-patch series.
- Produces: clean-apply and source-test evidence for Kolla integration.

- [ ] **Step 1: Run the complete available Mistral verification**

```bash
cd worktrees/mistral-powerops
PYTHONPATH="$PWD/../../worktrees/mistral-lib-powerops:$PWD" \
  python -m stestr run
tox -e pep8
python -m compileall -q mistral
git diff --check 3e4fe82455de7473809b0e0bc677fa3df3a3d1e2..HEAD
```

Expected: record the exact pass/skip count. If known sandbox socket tests fail,
report those separately and do not claim a full-suite pass.

- [ ] **Step 2: Export only the six new commits**

```bash
git format-patch --numbered --start-number 11 \
  --output-directory "$PWD/../../patches/mistral" \
  3e4fe82455de7473809b0e0bc677fa3df3a3d1e2..HEAD
find "$PWD/../../patches/mistral" -maxdepth 1 -name '*.patch' | sort
```

Expected: existing files `0001` through `0010` remain byte-identical and new
files are exactly `0011` through `0016`.

- [ ] **Step 3: Clean-apply the complete Mistral chain**

```bash
git -C sources/mistral worktree add \
  /tmp/mistral-horizon-powerops-apply \
  3b2eab2
git -C /tmp/mistral-horizon-powerops-apply am \
  "$PWD"/patches/mistral/*.patch
git -C /tmp/mistral-horizon-powerops-apply diff 3b2eab2..HEAD --check
```

Expected: all sixteen patches apply in filename order and diff hygiene is
clean. Tests against the disposable tree use the patched `mistral-lib` tree on
`PYTHONPATH`.
