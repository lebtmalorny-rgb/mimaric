# Horizon PowerOps Clean Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Собрать от чистого Horizon `stable/2025.1` отдельный безопасный `powerops-dashboard`, повторно доказать backend-контракты Masakari/Mistral/Kolla и подготовить воспроизводимый комплект установки без выполнения реальных power-команд.

**Architecture:** Horizon-плагин использует текущий Keystone-токен только для обращения к региональному Mistral API; изменяющий путь остаётся единственным: `Horizon -> Mistral -> PowerOps -> Nova/Masakari/Ironic`. Mistral выполняет авторизацию и повторный preflight под общим с Masakari etcd host-lock, а Masakari остаётся владельцем только аварийного fencing/evacuation. Работа разбита на независимые review gates, но оставлена одним последовательным планом, потому что имена workflow, схемы inventory, RBAC и Kolla packaging образуют один межрепозиторный контракт.

**Tech Stack:** OpenStack Horizon/Masakari/Mistral/mistral-lib/Kolla/Kolla-Ansible `stable/2025.1`, Python, Django, Horizon tables/forms, python-mistralclient, oslo.policy, oslo.config, openstacksdk, tooz/etcd, PBR, Jinja2/Ansible, Docker, `stestr`, `pytest`, `unittest`, `tox`, Git format-patch.

**Spec:** `docs/superpowers/specs/2026-09-02-horizon-powerops-clean-integration-design.md`

## Global Constraints

- Начать выполнение из нового изолированного root worktree от commit, который содержит этот план; commit спецификации `8d6c78d87ec0dfed186b653ff2ec4903f89ff13b` должен быть его предком. Не продолжать ветку `powerops/horizon-implementation` и старые компонентные worktree.
- Целевой Horizon берётся из чистого upstream `stable/2025.1`; фактический 40-символьный commit фиксируется до изменений в baseline manifest.
- Базовые commits: Masakari `0fd34dd6a6d90525dbf806f35577c5ee1d7e9444`, Mistral `3b2eab29e9dc71a5ba250d989155eb69a9bd8e48`, mistral-lib `693174dd0aac1da22870b31e4a2481c4e749916a`, imported Kolla-Ansible `703b06c9fa5771c758f703b424d63fb04192567a`, Kolla `d14cef9bbafa0db561abfb0c0299d1d6bbbf8f0c`.
- Existing published patch bytes under `patches/masakari/`, `patches/mistral/` and `patches/kolla-ansible/0001` through `0006` remain unchanged unless a clean-apply or contract test proves a defect and the defect receives its own reviewed fix patch.
- Kolla-Ansible patch `0006-fix-load-Masakari-through-idempotent-WSGI-wrapper.patch` is mandatory and precedes all new Horizon-related Kolla-Ansible patches.
- One installation serves one region. Horizon displays `openstack_region_name` and never accepts a caller-supplied region workflow input.
- UI/server RBAC is exactly `admin OR (powerops_operator AND exact project allowlist AND exact user allowlist)`; `admin` is allowed in any project.
- `powerops_operator` affects the whole compute host and all projects after authorization; project scope does not filter the host's VMs.
- `allow_hard_off=true` is accepted only for `admin`. Horizon exposes hard-off only for `planned_power_off`; Horizon always sends `false` for `planned_reboot`.
- Horizon calls only `power_ops.host_inventory`, `power_ops.host_power_status`, `power_ops.planned_power_off`, `power_ops.planned_reboot` and `power_ops.power_on_and_return`.
- Horizon never performs direct mutation calls to Nova, Masakari, Ironic, etcd or BMC and never exposes service/BMC credentials.
- Masakari state is display/diagnostic data. Horizon never creates a Masakari notification and never starts fencing or evacuation.
- All mutable workflows repeat server-side authorization, exact host mapping, VM discovery and state checks after acquiring `powerops/host/<host>`.
- No automatic retry or rollback follows a timeout or ambiguous response.
- First visual result is local mock mode. Any test-cloud access is read-only until separately approved; deployment, restart, workflow start, VM operation and physical power action each require explicit approval.
- Every task follows RED -> GREEN -> focused regression -> commit. Do not combine commits across review gates.

## Target File Map

- `patches/mistral-lib/`: one additive trusted-context patch.
- `patches/mistral/0011` onward: trusted identity, RBAC/start/resume/action enforcement and inventory patches.
- `powerops-dashboard/`: standalone Horizon plugin; no Horizon fork.
- `patches/kolla/`: opt-in image-source and Horizon activation patch.
- `patches/kolla-ansible/0007` onward: shared settings, role creation, workbook reconciliation and read-only runtime checks.
- `tests/test_horizon_powerops_contract.py`: cross-repository executable contract.
- `docs/evidence/2026-09-02-horizon-powerops-backend-readiness.md`: exact baseline, clean-apply and test evidence.
- `POWEROPS_HORIZON_OPERATIONS.md`: separate Russian operations guide.

---

### Task 1: Create fresh worktrees and prove the existing backend baseline

**Files:**
- Create: `docs/evidence/2026-09-02-horizon-powerops-backend-readiness.md`
- Create: `docs/evidence/horizon-powerops-baselines.json`
- Create: `tests/test_horizon_backend_baselines.py`
- Create during execution: `sources/horizon/`
- Create during execution: `sources/mistral-lib/`
- Create during execution: `sources/mistral/`
- Create during execution: `sources/masakari/`
- Create during execution: `sources/kolla/`
- Create during execution: `sources/kolla-ansible/`
- Create during execution: `worktrees/horizon-powerops-clean/`
- Create during execution: `worktrees/mistral-lib-horizon-clean/`
- Create during execution: `worktrees/mistral-horizon-clean/`
- Create during execution: `worktrees/masakari-horizon-verify/`
- Create during execution: `worktrees/kolla-ansible-horizon-verify/`
- Create during execution: `worktrees/kolla-horizon-clean/`

**Interfaces:**
- Produces exact baseline commits for all six component sources; Kolla-Ansible
  is recreated from the imported local source, while the other five are
  resolved from their upstream `stable/2025.1` histories.
- Proves existing tree hashes: Masakari `83bb2fd7a2d8c2f8d97e26c12fb66e8e06436bc5`, Mistral `8e3009eb1abf8033608d31d7e60cdb02ab8da1ed`, Kolla-Ansible `c1488cb1a5db61d102bd55a9e9a2fafb5c25426c`.
- Produces clean component branches with no dependency on old unfinished worktrees.

- [ ] **Step 1: Create the isolated root worktree**

Invoke `superpowers:using-git-worktrees`, then run from the clean branch that
contains this plan:

```bash
POWEROPS_PLAN_BASE=$(git rev-parse HEAD)
git merge-base --is-ancestor \
  8d6c78d87ec0dfed186b653ff2ec4903f89ff13b \
  "$POWEROPS_PLAN_BASE"
git worktree add -b powerops/horizon-clean-v2 \
  /tmp/powerops-horizon-clean-v2 \
  "$POWEROPS_PLAN_BASE"
git -C /tmp/powerops-horizon-clean-v2 status --short --branch
test -f /tmp/powerops-horizon-clean-v2/docs/superpowers/plans/2026-09-02-horizon-powerops-clean-integration.md
```

Expected: branch `powerops/horizon-clean-v2`, empty status.

- [ ] **Step 2: Write a failing baseline manifest test**

Create `tests/test_horizon_backend_baselines.py` with exact published invariants:

```python
import json
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / 'docs/evidence/horizon-powerops-baselines.json'


class HorizonBackendBaselinesTest(unittest.TestCase):
    def test_exact_existing_baselines_and_patch_counts(self):
        data = json.loads(MANIFEST.read_text(encoding='utf-8'))
        self.assertEqual(
            '0fd34dd6a6d90525dbf806f35577c5ee1d7e9444',
            data['masakari']['commit'],
        )
        self.assertEqual(10, data['masakari']['published_patches'])
        self.assertEqual(
            '3b2eab29e9dc71a5ba250d989155eb69a9bd8e48',
            data['mistral']['commit'],
        )
        self.assertEqual(10, data['mistral']['published_patches'])
        self.assertEqual(
            '693174dd0aac1da22870b31e4a2481c4e749916a',
            data['mistral_lib']['commit'],
        )
        self.assertEqual(
            '703b06c9fa5771c758f703b424d63fb04192567a',
            data['kolla_ansible']['commit'],
        )
        self.assertEqual(6, data['kolla_ansible']['published_patches'])
        self.assertEqual(
            'd14cef9bbafa0db561abfb0c0299d1d6bbbf8f0c',
            data['kolla']['commit'],
        )
        self.assertEqual('stable/2025.1', data['horizon']['branch'])
        self.assertRegex(data['horizon']['commit'], r'^[0-9a-f]{40}$')


if __name__ == '__main__':
    unittest.main()
```

Run:

```bash
cd /tmp/powerops-horizon-clean-v2
python3 -m unittest tests.test_horizon_backend_baselines -v
```

Expected: FAIL because `docs/evidence/horizon-powerops-baselines.json` does not exist.

- [ ] **Step 3: Materialize upstream sources and resolve exact refs**

```bash
cd /tmp/powerops-horizon-clean-v2
git clone https://opendev.org/openstack/horizon.git sources/horizon
git clone https://opendev.org/openstack/mistral-lib.git sources/mistral-lib
git clone https://opendev.org/openstack/mistral.git sources/mistral
git clone https://opendev.org/openstack/masakari.git sources/masakari
git clone https://opendev.org/openstack/kolla.git sources/kolla
POWEROPS_SOURCE_ROOT=/Users/dmitry/Desktop/ironic:mistral:masakari/powerops-patches
git clone "$POWEROPS_SOURCE_ROOT/work/kolla-ansible" sources/kolla-ansible
git -C sources/horizon fetch origin stable/2025.1
git -C sources/mistral-lib fetch origin stable/2025.1
git -C sources/mistral fetch origin stable/2025.1
git -C sources/masakari fetch origin stable/2025.1
git -C sources/kolla fetch origin stable/2025.1
git -C sources/horizon rev-parse origin/stable/2025.1
git -C sources/mistral-lib rev-parse 693174dd0aac1da22870b31e4a2481c4e749916a^{commit}
git -C sources/mistral rev-parse 3b2eab29e9dc71a5ba250d989155eb69a9bd8e48^{commit}
git -C sources/masakari rev-parse 0fd34dd6a6d90525dbf806f35577c5ee1d7e9444^{commit}
git -C sources/kolla rev-parse d14cef9bbafa0db561abfb0c0299d1d6bbbf8f0c^{commit}
git -C sources/kolla-ansible rev-parse 703b06c9fa5771c758f703b424d63fb04192567a^{commit}
```

Record the exact printed Horizon hash and verified fixed hashes in
`docs/evidence/horizon-powerops-baselines.json` using `apply_patch`. The JSON
must also contain the four fixed commits and published patch counts asserted
above; do not store a branch name in place of a commit hash.

- [ ] **Step 4: Create fresh component worktrees**

Use the exact hashes recorded in the manifest. Resolve the already fetched
Horizon ref once and pass that immutable value to the worktree command:

```bash
cd /tmp/powerops-horizon-clean-v2
HORIZON_BASE_COMMIT=$(git -C sources/horizon rev-parse origin/stable/2025.1)
git -C sources/horizon worktree add \
  -b powerops/horizon-clean \
  ../../worktrees/horizon-powerops-clean \
  "$HORIZON_BASE_COMMIT"
git -C sources/mistral-lib worktree add \
  -b powerops/security-context-clean \
  ../../worktrees/mistral-lib-horizon-clean \
  693174dd0aac1da22870b31e4a2481c4e749916a
git -C sources/mistral worktree add \
  -b powerops/mistral-horizon-clean \
  ../../worktrees/mistral-horizon-clean \
  3b2eab29e9dc71a5ba250d989155eb69a9bd8e48
git -C sources/masakari worktree add \
  -b powerops/masakari-horizon-verify \
  ../../worktrees/masakari-horizon-verify \
  0fd34dd6a6d90525dbf806f35577c5ee1d7e9444
git -C sources/kolla worktree add \
  -b powerops/kolla-horizon-clean \
  ../../worktrees/kolla-horizon-clean \
  d14cef9bbafa0db561abfb0c0299d1d6bbbf8f0c
```

Create the Kolla-Ansible verification worktree from the imported baseline:

```bash
cd /tmp/powerops-horizon-clean-v2
git -C sources/kolla-ansible worktree add \
  ../../worktrees/kolla-ansible-horizon-verify \
  703b06c9fa5771c758f703b424d63fb04192567a
```

Expected: all six worktrees have empty `git status --short`.

- [ ] **Step 5: Clean-apply the three published series**

From root `/tmp/powerops-horizon-clean-v2`:

```bash
cd /tmp/powerops-horizon-clean-v2
git -C worktrees/masakari-horizon-verify am \
  "$PWD"/patches/masakari/*.patch
git -C worktrees/mistral-horizon-clean am \
  "$PWD"/patches/mistral/*.patch
git -C worktrees/kolla-ansible-horizon-verify am \
  "$PWD"/patches/kolla-ansible/*.patch
git -C worktrees/masakari-horizon-verify write-tree
git -C worktrees/mistral-horizon-clean write-tree
git -C worktrees/kolla-ansible-horizon-verify write-tree
```

Expected hashes, in order:

```text
83bb2fd7a2d8c2f8d97e26c12fb66e8e06436bc5
8e3009eb1abf8033608d31d7e60cdb02ab8da1ed
c1488cb1a5db61d102bd55a9e9a2fafb5c25426c
```

- [ ] **Step 6: Prove the new Masakari WSGI deployment dependency**

```bash
cd /tmp/powerops-horizon-clean-v2
python3 worktrees/kolla-ansible-horizon-verify/kolla_ansible/tests/unit/test_masakari_wsgi_wrapper.py -v
rg -n "masakari-api\.wsgi|masakari\.wsgi import api|WSGIScriptAlias" \
  worktrees/kolla-ansible-horizon-verify/ansible/roles/masakari
```

Expected: 3/3 tests pass; Apache points to
`/etc/masakari/masakari-api.wsgi`, and no test performs a power or evacuation
operation.

- [ ] **Step 7: Make the baseline test GREEN and record evidence**

Run:

```bash
cd /tmp/powerops-horizon-clean-v2
python3 -m unittest tests.test_horizon_backend_baselines -v
git diff --check
```

In `docs/evidence/2026-09-02-horizon-powerops-backend-readiness.md`, record
commands, exact commits, the three tree hashes, WSGI result, and this boundary:
source/clean-apply evidence is not proof of a running OpenStack deployment.

- [ ] **Step 8: Commit the baseline gate**

```bash
cd /tmp/powerops-horizon-clean-v2
git add tests/test_horizon_backend_baselines.py \
  docs/evidence/horizon-powerops-baselines.json \
  docs/evidence/2026-09-02-horizon-powerops-backend-readiness.md
git commit -m "test: establish Horizon PowerOps backend baselines"
```

Expected: one root commit; no component implementation yet.

---

### Task 2: Recreate the mistral-lib trusted security context

**Files:**
- Modify: `worktrees/mistral-lib-horizon-clean/mistral_lib/actions/context.py`
- Modify: `worktrees/mistral-lib-horizon-clean/mistral_lib/tests/actions/test_context.py`
- Create: `patches/mistral-lib/0001-feat-carry-PowerOps-identity-in-action-context.patch`

**Interfaces:**
- Produces additive `SecurityContext.user_id: Optional[str]`.
- Produces additive `SecurityContext.roles: list[str]` with a defensive copy.
- Produces additive `ExecutionContext.workflow_resume_authorization: dict | None` with a defensive copy.
- Preserves all legacy positional `SecurityContext` arguments through `auth_token` and legacy serialized payloads.

- [ ] **Step 1: Write failing constructor and serializer tests**

Add these cases to `mistral_lib/tests/actions/test_context.py`:

```python
def test_security_context_carries_exact_roles_defensively(self):
    roles = ['admin', 'powerops_operator']
    security = context.SecurityContext(user_id='user-id', roles=roles)
    roles.append('forged')
    self.assertEqual('user-id', security.user_id)
    self.assertEqual(['admin', 'powerops_operator'], security.roles)

def test_execution_context_copies_resume_authorization(self):
    record = {
        'user_id': 'u',
        'project_id': 'p',
        'authorization_branch': 'admin',
        'authorized_at': '2026-09-02T10:00:00+00:00',
    }
    execution = context.ExecutionContext(
        workflow_resume_authorization=record,
    )
    record['authorization_branch'] = 'forged'
    self.assertEqual('admin', execution.workflow_resume_authorization[
        'authorization_branch'
    ])

def test_deserializes_legacy_payload_without_powerops_fields(self):
    restored = context.ActionContextSerializer().deserialize_from_dict({
        'security': {'project_id': 'legacy-project'},
        'execution': {'workflow_execution_id': 'legacy-execution'},
    })
    self.assertIsNone(restored.security.user_id)
    self.assertEqual([], restored.security.roles)
    self.assertIsNone(restored.execution.workflow_resume_authorization)
```

Retain a separate test that calls `SecurityContext` with all legacy positional
arguments through `auth_token` and asserts they retain their original slots.

- [ ] **Step 2: Run RED**

```bash
cd worktrees/mistral-lib-horizon-clean
python -m stestr run mistral_lib.tests.actions.test_context
```

Expected: new keyword arguments/attributes are absent.

- [ ] **Step 3: Implement additive fields without changing wire format**

Append parameters after existing positional parameters:

```python
class SecurityContext(object):
    def __init__(self, auth_uri=None, auth_cacert=None, insecure=None,
                 service_catalog=None, region_name=None, is_trust_scoped=None,
                 redelivered=None, expires_at=None, trust_id=None,
                 is_target=None, project_id=None, project_name=None,
                 user_name=None, auth_token=None, user_id=None, roles=None):
        self.user_id = user_id
        self.roles = list(roles) if roles else []
```

Append the execution parameter and copy it:

```python
def __init__(self, workflow_execution_id=None, task_execution_id=None,
             action_execution_id=None, workflow_name=None,
             callback_url=None, task_id=None, with_items_index=0,
             task_rerun_no=0, task_rerun_id=None,
             workflow_propagated_headers=None,
             workflow_resume_authorization=None):
    self.workflow_resume_authorization = (
        dict(workflow_resume_authorization)
        if workflow_resume_authorization else None
    )
```

Do not change `ActionContextSerializer`: its existing `vars()` encoding carries
new fields, while constructor defaults accept legacy payloads.

- [ ] **Step 4: Run focused and full verification**

```bash
cd worktrees/mistral-lib-horizon-clean
python -m stestr run mistral_lib.tests.actions.test_context
python -m stestr run
tox -e pep8
git diff --check
```

Expected: focused, full and pep8 suites pass.

- [ ] **Step 5: Commit, export and clean-apply**

```bash
cd worktrees/mistral-lib-horizon-clean
git add mistral_lib/actions/context.py \
  mistral_lib/tests/actions/test_context.py
git commit -m "feat: carry PowerOps identity in action context"
mkdir -p ../../patches/mistral-lib
git format-patch --output-directory ../../patches/mistral-lib \
  693174dd0aac1da22870b31e4a2481c4e749916a..HEAD
```

Apply the exported patch to another detached worktree at the exact baseline,
run the focused test there and compare tree hashes:

```bash
cd /tmp/powerops-horizon-clean-v2
git -C sources/mistral-lib worktree add \
  /tmp/mistral-lib-horizon-apply \
  693174dd0aac1da22870b31e4a2481c4e749916a
git -C /tmp/mistral-lib-horizon-apply am \
  "$PWD/patches/mistral-lib/0001-feat-carry-PowerOps-identity-in-action-context.patch"
git -C /tmp/mistral-lib-horizon-apply write-tree
git -C worktrees/mistral-lib-horizon-clean write-tree
cd /tmp/mistral-lib-horizon-apply
python -m stestr run mistral_lib.tests.actions.test_context
git status --short
```

Expected: exactly one patch, equal printed tree hashes, focused tests pass and
the applied worktree is clean.

---

### Task 3: Recreate Mistral trusted identity and the shared RBAC helper

**Files:**
- Modify: `worktrees/mistral-horizon-clean/mistral/context.py`
- Modify: `worktrees/mistral-horizon-clean/mistral/engine/actions.py`
- Create: `worktrees/mistral-horizon-clean/mistral/services/powerops.py`
- Modify: `worktrees/mistral-horizon-clean/mistral/tests/unit/actions/powerops/fakes.py`
- Modify: `worktrees/mistral-horizon-clean/mistral/tests/unit/engine/test_action_context.py`
- Create: `worktrees/mistral-horizon-clean/mistral/tests/unit/services/test_powerops.py`

**Interfaces:**
- Consumes mistral-lib `SecurityContext(user_id, roles)` and `ExecutionContext(workflow_resume_authorization)`.
- Produces `authorize(subject, allow_hard_off=False, error_cls=...) -> 'admin' | 'powerops_operator'`.
- Produces `reject_reserved_auth_fields(workflow_input, env) -> None`.
- Produces exact workflow allowlist `POWEROPS_WORKFLOW_NAMES`.

- [ ] **Step 1: Write failing trusted-context tests**

Assert `create_action_context()` transports exact request values and copies
roles:

```python
self.assertEqual('user-id', action_ctx.security.user_id)
self.assertEqual(
    ['admin', 'powerops_operator'],
    action_ctx.security.roles,
)
self.assertEqual(
    expected_resume_record,
    action_ctx.execution.workflow_resume_authorization,
)
```

Mutate original role/record containers after construction and assert the action
context does not change. Add a legacy no-runtime-record case.

- [ ] **Step 2: Write failing authorization matrix tests**

Use these exact cases in `test_powerops.py`:

```python
cases = (
    (['admin'], 'any-project', 'any-user', False, 'admin'),
    (['powerops_operator'], 'ops-project', 'ops-user', False,
     'powerops_operator'),
    (['powerops_operator'], 'wrong-project', 'ops-user', False, None),
    (['powerops_operator'], 'ops-project', 'wrong-user', False, None),
    (['member'], 'ops-project', 'ops-user', False, None),
    (['Admin'], 'ops-project', 'ops-user', False, None),
    (['powerops_operator'], 'ops-project', 'ops-user', True, None),
    (['admin'], 'any-project', 'any-user', True, 'admin'),
)
```

Also reject `roles=None` as unauthorized and malformed role containers such as
`'admin'`, tuples, dictionaries and lists containing non-strings.

- [ ] **Step 3: Run RED**

```bash
cd worktrees/mistral-horizon-clean
PYTHONPATH="$PWD/../mistral-lib-horizon-clean:$PWD" \
  python -m stestr run \
  mistral.tests.unit.engine.test_action_context \
  mistral.tests.unit.services.test_powerops
```

Expected: trusted fields/helper are absent.

- [ ] **Step 4: Populate the trusted action context**

In `mistral/context.py`, pass only validated request-context fields:

```python
security_ctx = actions_ctx.SecurityContext(
    project_id=context.project_id,
    project_name=context.project_name,
    user_id=context.user_id,
    user_name=context.user_name,
    roles=list(context.roles or []),
    auth_token=context.auth_token,
    service_catalog=context.service_catalog,
    region_name=context.region_name,
)
```

In `mistral/engine/actions.py`, copy only the server-created record from
`wf_ex.runtime_context['__powerops_resume_authorization']` into execution
context. Do not read it from workflow input or environment.

- [ ] **Step 5: Implement the exact shared helper**

Create constants and the authorization body in `mistral/services/powerops.py`:

```python
ADMIN_ROLE = 'admin'
OPERATOR_ROLE = 'powerops_operator'
ADMIN_BRANCH = 'admin'
OPERATOR_BRANCH = 'powerops_operator'
POWEROPS_RESUME_AUTH_KEY = '__powerops_resume_authorization'
POWEROPS_WORKFLOW_NAMES = frozenset({
    'power_ops.host_inventory',
    'power_ops.host_power_status',
    'power_ops.planned_power_off',
    'power_ops.planned_reboot',
    'power_ops.power_on_and_return',
})

def authorize(subject, allow_hard_off=False,
              error_cls=exc.NotAllowedException):
    roles = getattr(subject, 'roles', None)
    if (not isinstance(roles, list)
            or not all(isinstance(role, str) for role in roles)):
        raise error_cls('caller is not authorized for PowerOps')
    if ADMIN_ROLE in roles:
        branch = ADMIN_BRANCH
    elif (OPERATOR_ROLE in roles
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
```

Reserve exactly `roles`, `is_admin`, `authorization_branch`,
`workflow_resume_authorization` and `__powerops_resume_authorization`; reject a
non-mapping input/environment before any infrastructure access.

- [ ] **Step 6: Run regression and commit two reviewable changes**

First commit trusted propagation, then the helper:

```bash
cd worktrees/mistral-horizon-clean
PYTHONPATH="$PWD/../mistral-lib-horizon-clean:$PWD" \
  python -m stestr run mistral.tests.unit.engine.test_action_context
git add mistral/context.py mistral/engine/actions.py \
  mistral/tests/unit/engine/test_action_context.py \
  mistral/tests/unit/actions/powerops/fakes.py
git commit -m "feat: propagate trusted PowerOps action identity"

PYTHONPATH="$PWD/../mistral-lib-horizon-clean:$PWD" \
  python -m stestr run mistral.tests.unit.services.test_powerops
git add mistral/services/powerops.py \
  mistral/tests/unit/services/test_powerops.py \
  mistral/engine/actions.py
git commit -m "feat: define PowerOps role authorization"
```

Expected: both focused suites pass; no API/start behavior changes yet.

---

### Task 4: Enforce Mistral start, resume, action and audit boundaries

**Files:**
- Modify: `worktrees/mistral-horizon-clean/mistral/api/controllers/v2/execution.py`
- Modify: `worktrees/mistral-horizon-clean/mistral/engine/default_engine.py`
- Modify: `worktrees/mistral-horizon-clean/mistral/services/powerops.py`
- Modify: `worktrees/mistral-horizon-clean/mistral/actions/powerops/base.py`
- Modify: `worktrees/mistral-horizon-clean/mistral/actions/powerops/planned.py`
- Modify: `worktrees/mistral-horizon-clean/mistral/actions/powerops/return_host.py`
- Modify: `worktrees/mistral-horizon-clean/mistral/actions/powerops/exceptions.py`
- Create: `worktrees/mistral-horizon-clean/mistral/tests/unit/api/v2/test_executions_powerops.py`
- Create: `worktrees/mistral-horizon-clean/mistral/tests/unit/engine/test_powerops_resume.py`
- Modify: `worktrees/mistral-horizon-clean/mistral/tests/unit/actions/powerops/test_planned.py`
- Modify: `worktrees/mistral-horizon-clean/mistral/tests/unit/actions/powerops/test_return_host.py`

**Interfaces:**
- Start rejects unauthorized exact PowerOps workflow definitions before RPC.
- Resume accepts only `{'stale_domains_checked': True}` and stores an atomic server record.
- Actions call `_authorize()` before clients/coordination; hard-off uses the exact Boolean.
- Audit contains actor IDs/branch/operation but no token, catalog, password or BMC data.

- [ ] **Step 1: Write failing API-start tests**

Cover lookup by both workflow name and UUID, public `power_ops` definitions,
unknown workflow names, and exact role matrix. For a PowerOps start, assert this
order before `engine.start_workflow()`:

```python
powerops.reject_reserved_auth_fields(workflow_input, env)
powerops.authorize(
    context.ctx(),
    allow_hard_off=workflow_input.get('allow_hard_off', False),
)
```

Unauthorized calls return 403; malformed/reserved input returns 400; ordinary
workflow tests retain existing behavior.

- [ ] **Step 2: Write failing resume and transaction tests**

For paused `power_ops.power_on_and_return`, accept only:

```python
{'stale_domains_checked': True}
```

Reject missing env, string `'true'`, Boolean `False`, extra keys and reserved
keys before RPC. Engine tests assert exact record keys:

```python
{
    'user_id': 'resume-user-id',
    'project_id': 'resume-project-id',
    'authorization_branch': 'powerops_operator',
    'authorized_at': '2026-09-02T10:00:00+00:00',
}
```

If `wf_handler.resume_workflow()` raises, a new DB session must not see the
record. An ordinary workflow retains generic resume behavior.

- [ ] **Step 3: Write failing action and audit tests**

For every PowerOps action, assert authorization runs before
`connection_from_conf()`. Include admin outside allowlists, delegated exact
match/mismatch, unrelated role and case mismatch. Assert delegated hard-off is
denied before host resolution and admin hard-off proceeds.

Patch `LOG.info` and assert bounded fields include user/project IDs,
authorization branch, configured region, host, segment, operation, policy,
hard-off authorization and execution IDs. Assert log arguments omit
`auth_token`, `password`, service catalog, `driver_info` and BMC addresses.

- [ ] **Step 4: Run RED**

```bash
cd worktrees/mistral-horizon-clean
PYTHONPATH="$PWD/../mistral-lib-horizon-clean:$PWD" \
  python -m stestr run \
  mistral.tests.unit.api.v2.test_executions_powerops \
  mistral.tests.unit.engine.test_powerops_resume \
  mistral.tests.unit.actions.powerops.test_planned \
  mistral.tests.unit.actions.powerops.test_return_host
```

Expected: API enforcement, atomic record and action RBAC are absent.

- [ ] **Step 5: Implement strict resume helpers**

In `mistral/services/powerops.py` add:

```python
def validate_resume_env(env):
    if env != {'stale_domains_checked': True}:
        raise exc.InputException(
            'PowerOps resume requires stale_domains_checked=true only'
        )

def build_resume_authorization(subject, branch, now=None):
    if not subject.user_id or not subject.project_id:
        raise exc.NotAllowedException(
            'PowerOps resume requires current actor identifiers'
        )
    timestamp = now or datetime.datetime.now(datetime.timezone.utc)
    return {
        'user_id': subject.user_id,
        'project_id': subject.project_id,
        'authorization_branch': branch,
        'authorized_at': timestamp.isoformat(),
    }
```

Add `require_resume_authorization(action_context)` that accepts only those four
non-empty string keys and one of the two known authorization branches.

- [ ] **Step 6: Implement API and atomic Engine enforcement**

At workflow start, resolve the actual workflow definition before deciding that
it is PowerOps; do not trust the caller's display name. At resume, load the
actual execution and apply PowerOps checks only to
`power_ops.power_on_and_return`.

Inside the existing Engine DB transaction:

```python
if powerops.is_powerops_resume_workflow(wf_ex.workflow_name):
    powerops.validate_resume_env(env)
    branch = powerops.authorize(context.ctx())
    record = powerops.build_resume_authorization(context.ctx(), branch)
    runtime_context = dict(wf_ex.runtime_context or {})
    runtime_context[powerops.POWEROPS_RESUME_AUTH_KEY] = record
    wf_ex.runtime_context = runtime_context
wf_handler.resume_workflow(wf_ex, env=env)
```

- [ ] **Step 7: Route every action through the helper**

In the base action:

```python
def _authorize(self, context, allow_hard_off=False):
    return powerops.authorize(
        context.security,
        allow_hard_off=allow_hard_off,
        error_cls=exceptions.PowerOpsUnauthorized,
    )
```

Call it before clients/locks. `planned_power_off` and `planned_reboot` pass
their exact Boolean; return actions use the default. `return_to_service`
additionally requires the trusted resume record before creating clients.

- [ ] **Step 8: Run tests and commit separate review gates**

```bash
cd worktrees/mistral-horizon-clean
PYTHONPATH="$PWD/../mistral-lib-horizon-clean:$PWD" \
  python -m stestr run \
  mistral.tests.unit.api.v2.test_executions_powerops \
  mistral.tests.unit.api.v2.test_executions
git add mistral/api/controllers/v2/execution.py \
  mistral/tests/unit/api/v2/test_executions_powerops.py
git commit -m "feat: reject unauthorized PowerOps starts"

PYTHONPATH="$PWD/../mistral-lib-horizon-clean:$PWD" \
  python -m stestr run \
  mistral.tests.unit.engine.test_powerops_resume \
  mistral.tests.unit.actions.powerops.test_return_host
git add mistral/services/powerops.py mistral/api/controllers/v2/execution.py \
  mistral/engine/default_engine.py mistral/actions/powerops/return_host.py \
  mistral/tests/unit/api/v2/test_executions_powerops.py \
  mistral/tests/unit/engine/test_powerops_resume.py \
  mistral/tests/unit/actions/powerops/test_return_host.py
git commit -m "feat: reauthorize PowerOps workflow resume"

PYTHONPATH="$PWD/../mistral-lib-horizon-clean:$PWD" \
  python -m stestr run mistral.tests.unit.actions.powerops
git add mistral/actions/powerops mistral/tests/unit/actions/powerops
git commit -m "feat: enforce PowerOps roles and hard-off policy"
```

Expected: three independently reviewable commits and all affected legacy tests
pass.

---

### Task 5: Add fail-closed all-project inventory and export Mistral patches

**Files:**
- Create: `worktrees/mistral-horizon-clean/mistral/actions/powerops/inventory.py`
- Modify: `worktrees/mistral-horizon-clean/mistral/actions/powerops/clients.py`
- Modify: `worktrees/mistral-horizon-clean/mistral/actions/powerops/exceptions.py`
- Modify: `worktrees/mistral-horizon-clean/setup.cfg`
- Modify: `worktrees/mistral-horizon-clean/etc/mistral/power_ops.yaml`
- Create: `worktrees/mistral-horizon-clean/mistral/tests/unit/actions/powerops/test_inventory.py`
- Modify: `worktrees/mistral-horizon-clean/mistral/tests/unit/actions/powerops/test_registration.py`
- Modify: `worktrees/mistral-horizon-clean/mistral/tests/unit/actions/powerops/test_workbook.py`
- Create: `patches/mistral/0011-feat-propagate-trusted-PowerOps-action-identity.patch`
- Create: `patches/mistral/0012-feat-define-PowerOps-role-authorization.patch`
- Create: `patches/mistral/0013-feat-reject-unauthorized-PowerOps-starts.patch`
- Create: `patches/mistral/0014-feat-reauthorize-PowerOps-workflow-resume.patch`
- Create: `patches/mistral/0015-feat-enforce-PowerOps-roles-and-hard-off-policy.patch`
- Create: `patches/mistral/0016-feat-expose-read-only-PowerOps-host-inventory.patch`

**Interfaces:**
- Produces action `powerops.host_inventory` with no caller input.
- Produces workflow `power_ops.host_inventory` with output key `result`.
- Produces `CloudClients.host_inventory() -> list[dict]` across all projects.
- Produces exact row keys: `region_name`, `segment_uuid`, `host`,
  `ironic_node_uuid`, `power_state`, `target_power_state`, `nova_status`,
  `nova_state`, `masakari_maintenance`, `instance_count`, `instances`,
  `operable`, `blocking_reason`.
- Produces exact instance keys: `id`, `name`, `project_id`, `status`.

- [ ] **Step 1: Write failing inventory tests**

Create tests proving one successful row has this exact shape:

```python
{
    'region_name': 'RegionOne',
    'segment_uuid': '11111111-1111-1111-1111-111111111111',
    'host': 'compute-01',
    'ironic_node_uuid': '22222222-2222-2222-2222-222222222222',
    'power_state': 'power on',
    'target_power_state': None,
    'nova_status': 'enabled',
    'nova_state': 'up',
    'masakari_maintenance': False,
    'instance_count': 2,
    'instances': [
        {'id': '33333333-3333-3333-3333-333333333333',
         'name': 'vm-a', 'project_id': 'project-a', 'status': 'ACTIVE'},
        {'id': '44444444-4444-4444-4444-444444444444',
         'name': 'vm-b', 'project_id': 'project-b', 'status': 'SHUTOFF'},
    ],
    'operable': True,
    'blocking_reason': None,
}
```

Assert Nova is called with `details=True, all_projects=True`. Assert the path
uses only list/GET calls and never invokes power, Nova service mutation,
migration, stop/start, Masakari notification or etcd mutation.

- [ ] **Step 2: Write failing global/per-row degradation tests**

Required global dataset failure raises `InventoryUnavailable` and returns no
partial result. Per-row failures use only these fixed reasons:

```python
{
    'ambiguous_masakari_host',
    'missing_nova_service',
    'ambiguous_nova_service',
    'missing_ironic_node',
    'ambiguous_ironic_node',
    'ironic_node_incompatible',
    'invalid_instance_data',
}
```

A Nova server without canonical `compute_host` fails the complete snapshot,
because its impact cannot be attributed safely. Returned mappings must not
contain token, password, endpoint credentials, BMC address, `driver_info`,
`instance_info`, service catalog or raw backend exception strings.

- [ ] **Step 3: Run RED**

```bash
cd worktrees/mistral-horizon-clean
PYTHONPATH="$PWD/../mistral-lib-horizon-clean:$PWD" \
  python -m stestr run \
  mistral.tests.unit.actions.powerops.test_inventory \
  mistral.tests.unit.actions.powerops.test_registration \
  mistral.tests.unit.actions.powerops.test_workbook
```

Expected: inventory action, entry point and workflow do not exist.

- [ ] **Step 4: Implement complete read-only collection**

Materialize every global dataset under one service deadline before building
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

Masakari hosts are the canonical row source. Match host strings exactly, sort
rows by `(segment_uuid, host)` and instances by UUID. Convert failures only to
the fixed reason identifiers asserted above.

- [ ] **Step 5: Register the authorized action and workflow**

```python
class HostInventoryAction(base.PowerOpsAction):
    def run(self, context):
        if not CONF.powerops.enabled:
            raise exceptions.PowerOpsDisabled()
        self._authorization_branch = self._authorize(context)
        cloud = clients.CloudClients(clients.connection_from_conf())
        result = cloud.host_inventory()
        self._audit(
            context, 'host_inventory', 'success',
            {'host_count': len(result)},
        )
        return result
```

Add the entry point:

```ini
powerops.host_inventory = mistral.actions.powerops.inventory:HostInventoryAction
```

Add the workbook definition:

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

Inventory does not acquire a host lock because it is read-only; every later
mutation performs a fresh authoritative check under the lock.

- [ ] **Step 6: Run affected suites and commit**

```bash
cd worktrees/mistral-horizon-clean
PYTHONPATH="$PWD/../mistral-lib-horizon-clean:$PWD" \
  python -m stestr run \
  mistral.tests.unit.actions.powerops \
  mistral.tests.unit.services.test_powerops \
  mistral.tests.unit.api.v2.test_executions_powerops \
  mistral.tests.unit.engine.test_powerops_resume \
  mistral.tests.unit.engine.test_action_context
tox -e pep8 -- mistral/actions/powerops mistral/services/powerops.py
git add mistral/actions/powerops mistral/tests/unit/actions/powerops \
  setup.cfg etc/mistral/power_ops.yaml
git commit -m "feat: expose read-only PowerOps host inventory"
```

Expected: six new Mistral commits exist after the published ten-patch tree.

- [ ] **Step 7: Export exactly six patches and clean-apply them**

```bash
cd worktrees/mistral-horizon-clean
git format-patch --numbered --start-number 11 -6 \
  --output-directory ../../patches/mistral
ls ../../patches/mistral/00*.patch
```

Expected: existing `0001` through `0010` plus exact new `0011` through `0016`.
Apply all sixteen patches to a second clean worktree:


```bash
cd /tmp/powerops-horizon-clean-v2
git -C sources/mistral worktree add \
  /tmp/mistral-horizon-apply \
  3b2eab29e9dc71a5ba250d989155eb69a9bd8e48
git -C /tmp/mistral-horizon-apply am "$PWD"/patches/mistral/*.patch
git -C /tmp/mistral-horizon-apply write-tree
git -C worktrees/mistral-horizon-clean write-tree
cd /tmp/mistral-horizon-apply
PYTHONPATH="/tmp/mistral-lib-horizon-apply:$PWD" \
  python -m stestr run \
  mistral.tests.unit.actions.powerops \
  mistral.tests.unit.services.test_powerops \
  mistral.tests.unit.api.v2.test_executions_powerops \
  mistral.tests.unit.engine.test_powerops_resume
git status --short
```

Expected: equal printed tree hashes, focused tests pass and the applied tree is
clean.

- [ ] **Step 8: Commit exported Mistral/mistral-lib artifacts in root**

```bash
cd /tmp/powerops-horizon-clean-v2
git add patches/mistral-lib patches/mistral
git commit -m "build: add Horizon PowerOps backend security patches"
```

Expected: patch bytes are tracked and all older published patch hashes remain
unchanged.

---

### Task 6: Scaffold the standalone Horizon plugin and exact UI RBAC

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
- Create: `powerops-dashboard/poweropsdashboard/test/settings.py`
- Create: `powerops-dashboard/poweropsdashboard/test/urls.py`
- Create: `powerops-dashboard/poweropsdashboard/tests/__init__.py`
- Create: `powerops-dashboard/poweropsdashboard/tests/test_auth.py`
- Create: `powerops-dashboard/poweropsdashboard/tests/test_dashboard.py`

**Interfaces:**
- Produces `Authorization(branch: str, is_admin: bool)`.
- Produces `authorize_user(user) -> Authorization` or raises `PermissionDenied`.
- Consumes settings `POWEROPS_ALLOWED_PROJECT_NAMES`, `POWEROPS_ALLOWED_USER_NAMES`, `POWEROPS_REGION_NAME`, `POWEROPS_MOCK_MODE`.
- Produces top-level dashboard URL namespace `horizon:powerops:compute_hosts`.

- [ ] **Step 1: Add package and test metadata**

Use this package metadata:

```ini
[metadata]
name = powerops-dashboard
summary = Safe Horizon interface for OpenStack PowerOps workflows
license = Apache License, Version 2.0

[files]
packages =
    poweropsdashboard
```

`requirements.txt` contains `pbr`, `horizon` and `python-mistralclient`, all
resolved with OpenStack 2025.1 upper constraints. `tox.ini` provides `py3` and
`pep8`; `py3` runs:

```ini
commands =
    stestr run {posargs}
```

`MANIFEST.in` contains the exact package-data rule:

```text
recursive-include poweropsdashboard *.html *.js *.css
```

Test settings import Horizon test settings, append `poweropsdashboard`, and set:

```python
POWEROPS_REGION_NAME = 'RegionOne'
POWEROPS_ALLOWED_PROJECT_NAMES = ['ops-project']
POWEROPS_ALLOWED_USER_NAMES = ['ops-user']
POWEROPS_MOCK_MODE = False
```

- [ ] **Step 2: Write failing RBAC and direct-URL tests**

Use exact test cases:

```python
cases = (
    (['admin'], 'any-project', 'any-user', 'admin'),
    (['powerops_operator'], 'ops-project', 'ops-user',
     'powerops_operator'),
    (['powerops_operator'], 'wrong-project', 'ops-user', None),
    (['powerops_operator'], 'ops-project', 'wrong-user', None),
    (['member'], 'ops-project', 'ops-user', None),
    (['Admin'], 'ops-project', 'ops-user', None),
)
```

Assert users with both roles take the `admin` branch. Assert an unauthorized
GET to the panel returns HTTP 403 and never constructs a Mistral client.

- [ ] **Step 3: Run RED**

```bash
cd powerops-dashboard
python -m stestr run \
  poweropsdashboard.tests.test_auth \
  poweropsdashboard.tests.test_dashboard
```

Expected: package/dashboard/auth modules are absent.

- [ ] **Step 4: Implement exact UI authorization**

```python
Authorization = collections.namedtuple(
    'Authorization', ['branch', 'is_admin']
)

def authorize_user(user):
    raw_roles = getattr(user, 'roles', None)
    if not isinstance(raw_roles, (list, tuple)):
        raise PermissionDenied

    roles = []
    for role in raw_roles:
        if not isinstance(role, dict):
            raise PermissionDenied
        name = role.get('name')
        if not isinstance(name, str):
            raise PermissionDenied
        roles.append(name)

    if 'admin' in roles:
        return Authorization('admin', True)
    if ('powerops_operator' in roles
            and user.project_name
            in settings.POWEROPS_ALLOWED_PROJECT_NAMES
            and user.username in settings.POWEROPS_ALLOWED_USER_NAMES):
        return Authorization('powerops_operator', False)
    raise PermissionDenied
```

Do not lowercase roles, project names or user names. Treat malformed role
containers as denial. Call `authorize_user()` from both panel visibility and
every class-based view dispatch path.

- [ ] **Step 5: Register one top-level dashboard and panel**

`dashboard.py` declares `PowerOps` with slug `powerops`; `panel.py` declares
`Compute Hosts` with slug `compute_hosts`. Register them explicitly with
`horizon.register(PowerOps)` and `PowerOps.register(ComputeHosts)`.
`_50_powerops.py` contains only the standard enabled-file settings:

```python
DASHBOARD = 'powerops'
ADD_INSTALLED_APPS = ['poweropsdashboard']
AUTO_DISCOVER_STATIC_FILES = True
```

Do not add the panel to Horizon `Admin` and do not modify upstream Horizon
source files.

- [ ] **Step 6: Run focused tests and commit the protected shell**

```bash
cd powerops-dashboard
python -m stestr run \
  poweropsdashboard.tests.test_auth \
  poweropsdashboard.tests.test_dashboard
tox -e pep8
git add .
git commit -m "feat: scaffold protected PowerOps dashboard"
```

Expected: RBAC matrix and direct-URL denial pass, and the dashboard imports
against the clean target Horizon constraints.

---

### Task 7: Add the Mistral adapter, strict inventory and execution views

**Files:**
- Create: `powerops-dashboard/poweropsdashboard/constants.py`
- Create: `powerops-dashboard/poweropsdashboard/api.py`
- Create: `powerops-dashboard/poweropsdashboard/mock_data.py`
- Create: `powerops-dashboard/poweropsdashboard/presentation.py`
- Create: `powerops-dashboard/poweropsdashboard/hosts/tables.py`
- Modify: `powerops-dashboard/poweropsdashboard/hosts/views.py`
- Modify: `powerops-dashboard/poweropsdashboard/hosts/urls.py`
- Create: `powerops-dashboard/poweropsdashboard/hosts/templates/powerops/compute_hosts/index.html`
- Create: `powerops-dashboard/poweropsdashboard/hosts/templates/powerops/compute_hosts/execution.html`
- Create: `powerops-dashboard/poweropsdashboard/tests/test_api.py`
- Create: `powerops-dashboard/poweropsdashboard/tests/test_mock_api.py`
- Create: `powerops-dashboard/poweropsdashboard/tests/test_inventory_views.py`
- Create: `powerops-dashboard/poweropsdashboard/tests/test_execution_views.py`

**Interfaces:**
- Produces `get_client(request) -> MistralPowerOpsClient | MockPowerOpsClient`.
- Produces read methods `start_inventory()`, `start_host_status(host, segment_uuid)`, `get_execution(id)`, `list_executions(all_projects=False)`, `list_tasks(id)`.
- Produces immutable `InstanceRow`, `HostRow` and `ExecutionState` presentation objects.
- Produces GET routes `index`, `refresh_inventory`, `execution`.

- [ ] **Step 1: Write failing client/region tests**

Patch `mistralclient.api.client.client` and Horizon `base.url_for`. Assert exact
client construction:

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

If `request.user.services_region != settings.POWEROPS_REGION_NAME`, raise
`RegionMismatch` before endpoint discovery. Assert no Nova, Masakari, Ironic or
bare-metal client is imported or constructed by the plugin.

- [ ] **Step 2: Write failing strict inventory/parser tests**

Feed the exact Task 5 row shape to `parse_inventory_execution()`. Assert it
returns a `HostRow` whose instances contain UUID, name, project ID and status.
Reject missing required keys, extra keys, non-list instances, mismatched
`instance_count`, malformed UUIDs, non-Boolean `operable`, unknown blocking
reasons and any key matching `token`, `password`, `bmc`, `driver_info`,
`instance_info` or `service_catalog`.

Assert the displayed region comes from `POWEROPS_REGION_NAME` and equals every
row's `region_name`; mismatch blocks the whole inventory.

- [ ] **Step 3: Write failing execution/inventory view tests**

Assert:

- index authorizes before creating the adapter;
- inventory is rendered only from a successful `power_ops.host_inventory`;
- non-operable rows show fixed diagnostic text and no mutation links;
- active executions are determined only from the five exact workflow names,
  non-terminal state and exact `input.host`/`input.segment_uuid`;
- `admin` lists executions with `all_projects=True`;
- `powerops_operator` lists only its Mistral project scope;
- polling an execution uses GET/read methods only.

- [ ] **Step 4: Write failing mock adapter tests and run RED**

With `POWEROPS_MOCK_MODE=True`, inventory/status/execution reads return deep
copies of secret-free fixtures. Every mutation method named `start_planned`,
`start_return` and `resume_return` raises:

```python
MockMutationDisabled(
    'PowerOps mutations are disabled in mock mode'
)
```

Run:

```bash
cd powerops-dashboard
python -m stestr run \
  poweropsdashboard.tests.test_api \
  poweropsdashboard.tests.test_mock_api \
  poweropsdashboard.tests.test_inventory_views \
  poweropsdashboard.tests.test_execution_views
```

Expected: adapter/presentation/table modules are absent.

- [ ] **Step 5: Define the closed workflow and policy sets**

```python
HOST_INVENTORY = 'power_ops.host_inventory'
HOST_POWER_STATUS = 'power_ops.host_power_status'
PLANNED_POWER_OFF = 'power_ops.planned_power_off'
PLANNED_REBOOT = 'power_ops.planned_reboot'
POWER_ON_AND_RETURN = 'power_ops.power_on_and_return'
POWEROPS_WORKFLOWS = frozenset({
    HOST_INVENTORY,
    HOST_POWER_STATUS,
    PLANNED_POWER_OFF,
    PLANNED_REBOOT,
    POWER_ON_AND_RETURN,
})
INSTANCE_POLICIES = ('require_empty', 'live_migrate', 'stop')
TERMINAL_STATES = frozenset({'SUCCESS', 'ERROR', 'CANCELLED'})
```

No view accepts a workflow name or action name from the browser.

- [ ] **Step 6: Implement the narrow live adapter**

```python
def start_inventory(self):
    return self.client.executions.create(HOST_INVENTORY)

def start_host_status(self, host, segment_uuid):
    return self.client.executions.create(
        HOST_POWER_STATUS,
        workflow_input={
            'host': host,
            'segment_uuid': segment_uuid,
        },
    )

def get_execution(self, execution_id):
    return self.client.executions.get(execution_id)

def list_tasks(self, execution_id):
    return self.client.tasks.list(
        workflow_execution_id=execution_id,
    )
```

`list_executions(all_projects)` passes the Boolean only for admin and sorts
presentation results by `created_at` descending. Do not expose the raw client
outside `api.py`.

- [ ] **Step 7: Implement strict immutable presentation objects**

Use frozen dataclasses:

```python
@dataclasses.dataclass(frozen=True)
class InstanceRow:
    id: str
    name: str
    project_id: str
    status: str

@dataclasses.dataclass(frozen=True)
class HostRow:
    region_name: str
    segment_uuid: str
    host: str
    ironic_node_uuid: typing.Optional[str]
    power_state: typing.Optional[str]
    target_power_state: typing.Optional[str]
    nova_status: typing.Optional[str]
    nova_state: typing.Optional[str]
    masakari_maintenance: typing.Optional[bool]
    instance_count: int
    instances: typing.Tuple[InstanceRow, ...]
    operable: bool
    blocking_reason: typing.Optional[str]

@dataclasses.dataclass(frozen=True)
class ExecutionState:
    id: str
    workflow_name: str
    state: str
    state_info: typing.Optional[str]
    verification_required: bool
    output: typing.Mapping[str, object]
```

Parser copies primitive fields, converts instances to tuples and never
attaches raw backend objects.

- [ ] **Step 8: Render the read-only UI and commit**

The host table displays one configured region, infrastructure states, minimal
VM list, active execution and safe blocking reason. Status colors are derived
only from fixed state sets. Execution page renders workflow/task/action state
and sanitized output fields; it never renders raw exception objects.

```bash
cd powerops-dashboard
python -m stestr run \
  poweropsdashboard.tests.test_api \
  poweropsdashboard.tests.test_mock_api \
  poweropsdashboard.tests.test_inventory_views \
  poweropsdashboard.tests.test_execution_views
git add .
git commit -m "feat: show PowerOps inventory and execution state"
```

Expected: inventory is read-only, non-operable rows have no mutation links,
and the browser receives no raw backend object or secret field.

---

### Task 8: Add guarded planned power-off and reboot forms

**Files:**
- Create: `powerops-dashboard/poweropsdashboard/submission.py`
- Create: `powerops-dashboard/poweropsdashboard/hosts/forms.py`
- Modify: `powerops-dashboard/poweropsdashboard/api.py`
- Modify: `powerops-dashboard/poweropsdashboard/hosts/views.py`
- Modify: `powerops-dashboard/poweropsdashboard/hosts/urls.py`
- Modify: `powerops-dashboard/poweropsdashboard/hosts/tables.py`
- Create: `powerops-dashboard/poweropsdashboard/hosts/templates/powerops/compute_hosts/confirm_planned.html`
- Create: `powerops-dashboard/poweropsdashboard/tests/test_planned_forms.py`
- Create: `powerops-dashboard/poweropsdashboard/tests/test_planned_views.py`

**Interfaces:**
- Produces `PlannedOperationForm(authorization, host_row, operation, *args, **kwargs)`.
- Produces `workflow_input() -> dict` with exact typed values.
- Produces `issue_submission_token(request, operation, host) -> str`.
- Produces `consume_submission_token(request, token, operation, host) -> None`.
- Produces route `planned/<operation>/<segment_uuid>/<host>` where operation is closed to `power_off|reboot`.

- [ ] **Step 1: Write failing form tests for all policies**

Assert `require_empty`, `live_migrate` and `stop` are the only choices and
`require_empty` is default. Require byte-for-byte `typed_host == host_row.host`.
The valid base payload is:

```python
{
    'host': 'compute-01',
    'segment_uuid': '11111111-1111-1111-1111-111111111111',
    'instance_policy': 'require_empty',
    'allow_hard_off': False,
}
```

Assert `type(payload['allow_hard_off']) is bool`.

- [ ] **Step 2: Write failing hard-off scope tests**

For `power_off`, admin sees `allow_hard_off` and must also check
`confirm_hard_off` when it is true. A delegated operator sees neither field and
a forged POST is rejected.

For `reboot`, neither admin nor operator sees hard-off controls. A forged
`allow_hard_off` or `confirm_hard_off` POST is rejected and every valid reboot
payload contains:

```python
{'allow_hard_off': False}
```

- [ ] **Step 3: Write failing preflight and impact tests**

The confirmation view runs a fresh authorized inventory and exact host-status
workflow before rendering. It derives host and segment from the returned
`HostRow`, not from hidden form values. Assert the template shows for every VM:

```text
UUID, name, project_id, status, selected policy
```

If either read workflow fails, the row is non-operable, state changed, host
mapping is ambiguous or an active mutation exists, return HTTP 409/422 and do
not call `start_planned()`.

- [ ] **Step 4: Write failing duplicate/ambiguous-response tests**

Issue a 32-byte random single-use token and store only its SHA-256 digest in
the Horizon session. Two POSTs with the same token must produce one adapter
call; the second returns 409. Consume the digest before calling Mistral. A
timeout after submission renders `verification_required=True`; a following GET
must only list/read executions and never call `start_planned()`.

- [ ] **Step 5: Run RED**

```bash
cd powerops-dashboard
python -m stestr run \
  poweropsdashboard.tests.test_planned_forms \
  poweropsdashboard.tests.test_planned_views
```

Expected: form, submission guard and mutation adapter method are absent.

- [ ] **Step 6: Implement typed form validation**

Use `ChoiceField`, `CharField` and `BooleanField`. Build the backend payload
explicitly:

```python
def workflow_input(self):
    return {
        'host': self.host_row.host,
        'segment_uuid': self.host_row.segment_uuid,
        'instance_policy': self.cleaned_data['instance_policy'],
        'allow_hard_off': (
            self.operation == 'power_off'
            and self.authorization.is_admin
            and self.cleaned_data.get('allow_hard_off') is True
        ),
    }
```

Reject any browser key not declared for the exact role/operation instead of
forwarding `cleaned_data` wholesale.

- [ ] **Step 7: Implement the single-use guard and closed adapter call**

```python
def start_planned(self, operation, payload):
    workflow = {
        'power_off': constants.PLANNED_POWER_OFF,
        'reboot': constants.PLANNED_REBOOT,
    }[operation]
    return self.client.executions.create(
        workflow,
        workflow_input=dict(payload),
    )
```

Use `secrets.token_urlsafe(32)`, `hashlib.sha256` and
`hmac.compare_digest`. Delete the digest before the adapter call. On success,
store only the returned execution UUID and redirect to the GET execution page.
Do not store workflow input, user token or credentials in the session.

- [ ] **Step 8: Render explicit impact confirmation and commit**

The template states that the operation affects all projects, lists every VM,
shows the selected policy, requires exact host typing and renders the separate
hard-off warning only for admin power-off.

```bash
cd powerops-dashboard
python -m stestr run \
  poweropsdashboard.tests.test_planned_forms \
  poweropsdashboard.tests.test_planned_views \
  poweropsdashboard.tests.test_mock_api
git add .
git commit -m "feat: guard planned PowerOps submissions"
```

Expected: all policies, exact-host confirmation, hard-off scope and one-call
maximum per session token are proven.

---

### Task 9: Add immutable return, sanitized errors, polling and mock preview

**Files:**
- Modify: `powerops-dashboard/poweropsdashboard/api.py`
- Modify: `powerops-dashboard/poweropsdashboard/hosts/forms.py`
- Modify: `powerops-dashboard/poweropsdashboard/hosts/views.py`
- Modify: `powerops-dashboard/poweropsdashboard/hosts/urls.py`
- Create: `powerops-dashboard/poweropsdashboard/error_handling.py`
- Create: `powerops-dashboard/poweropsdashboard/hosts/templates/powerops/compute_hosts/start_return.html`
- Create: `powerops-dashboard/poweropsdashboard/hosts/templates/powerops/compute_hosts/resume_return.html`
- Create: `powerops-dashboard/poweropsdashboard/static/poweropsdashboard/js/powerops.js`
- Create: `powerops-dashboard/poweropsdashboard/static/poweropsdashboard/css/powerops.css`
- Create: `powerops-dashboard/poweropsdashboard/test/preview_settings.py`
- Create: `powerops-dashboard/poweropsdashboard/test/preview_middleware.py`
- Create: `powerops-dashboard/poweropsdashboard/tests/test_return_views.py`
- Create: `powerops-dashboard/poweropsdashboard/tests/test_error_handling.py`
- Create: `powerops-dashboard/poweropsdashboard/tests/test_preview.py`
- Create: `powerops-dashboard/README.rst`
- Modify: `powerops-dashboard/MANIFEST.in`

**Interfaces:**
- Produces routes `return/start/<source_execution_id>` and `return/resume/<execution_id>`.
- Consumes stopped VM manifest only from successful `power_ops.planned_power_off` output.
- Produces fixed resume env `{'stale_domains_checked': True}`.
- Produces `classify_error(exc) -> (status_code, public_message, verification_required)`.
- Produces local mock preview bound only to `127.0.0.1`.

- [ ] **Step 1: Write failing immutable-manifest tests**

Enable start-return only for a successful exact
`power_ops.planned_power_off`. Validate source input host/segment and output:

```python
{'stopped_instance_ids': [
    '33333333-3333-3333-3333-333333333333',
]}
```

Reject missing, duplicate, non-string or malformed UUIDs. The browser form has
no manifest field. A forged `stopped_instance_ids` POST is rejected and the
adapter receives only a fresh copy of the server-read source manifest.

- [ ] **Step 2: Write failing pause/resume predicate tests**

Before displaying resume, require all of:

```python
execution.workflow_name == constants.POWER_ON_AND_RETURN
execution.state == 'PAUSED'
paused_task.name == 'operator_inspection_gate'
status.power_state == 'power on'
status.nova_status == 'disabled'
status.nova_state == 'up'
status.masakari_maintenance is True
manifest_restart_started is False
```

The form contains only required Boolean `stale_domains_checked`. Current UI
authorization is reevaluated on both start and resume requests. Removed
allowlist membership returns 403 even if the original start was authorized.

- [ ] **Step 3: Write failing error and polling tests**

Assert fixed mappings:

```python
EXPECTED = {
    'forbidden': (403, 'Недостаточно прав для операции PowerOps.'),
    'conflict': (409, 'Хост занят или его состояние изменилось.'),
    'invalid': (422, 'Параметры операции не прошли проверку.'),
    'unavailable': (503, 'Обязательный сервис временно недоступен.'),
}
```

Unknown exceptions map to 503 with a fixed message and server-side exception
logging. Public messages and templates must not contain traceback, raw
exception text, token, password, service catalog, BMC address or driver data.
JavaScript polls only the execution GET URL and stops on
`SUCCESS|ERROR|CANCELLED`; it never submits POST/PUT or retries an operation.

- [ ] **Step 4: Write failing mock preview tests and run RED**

Mock fixtures contain:

- an operable powered-on host with two VMs from different project IDs;
- a non-operable ambiguous host;
- a running planned power-off;
- a paused return at `operator_inspection_gate`;
- an error marked `verification_required`.

Assert all pages render without network access and all mutation POSTs return
409 `MockMutationDisabled`.

```bash
cd powerops-dashboard
python -m stestr run \
  poweropsdashboard.tests.test_return_views \
  poweropsdashboard.tests.test_error_handling \
  poweropsdashboard.tests.test_preview
```

Expected: return/error/preview components are absent.

- [ ] **Step 5: Implement immutable start-return**

Build payload exclusively from the source execution:

```python
payload = {
    'host': source_input['host'],
    'segment_uuid': source_input['segment_uuid'],
    'stopped_instance_ids': list(
        source_output['stopped_instance_ids']
    ),
}
```

Use the Task 8 single-use token. The live adapter maps the closed method:

```python
def start_return(self, payload):
    return self.client.executions.create(
        constants.POWER_ON_AND_RETURN,
        workflow_input=dict(payload),
    )
```

- [ ] **Step 6: Implement strict resume of the same execution**

Re-read execution, tasks and `host_power_status` server-side. After all eight
predicates pass and the checkbox is exact Boolean true, consume the token and
call only:

```python
def resume_return(self, execution_id):
    return self.client.executions.update(
        execution_id,
        'RUNNING',
        env={'stale_domains_checked': True},
    )
```

Do not accept env, manifest, role, region, host or segment values from the
resume POST.

- [ ] **Step 7: Implement safe errors and GET-only polling**

Classify known python-mistralclient/HTTP and local validation exceptions into
the four declared response classes. Log correlation data server-side, but
render only fixed messages. A request with an uncertain submission outcome
sets `verification_required=True` and links to execution listing; it never
calls the mutation adapter again.

`powerops.js` performs `fetch()` with `method: 'GET'`, validates same-origin
JSON, replaces only state fields and stops polling on a terminal state or any
HTTP error.

- [ ] **Step 8: Create local mock preview and commit**

Preview settings set:

```python
DEBUG = True
ALLOWED_HOSTS = ['127.0.0.1', 'localhost']
POWEROPS_MOCK_MODE = True
POWEROPS_REGION_NAME = 'RegionOne'
POWEROPS_ALLOWED_PROJECT_NAMES = ['ops-project']
POWEROPS_ALLOWED_USER_NAMES = ['ops-user']
```

Middleware creates only a local fake authorized user and never reads
credentials. README command:

```bash
python manage.py runserver \
  --settings=poweropsdashboard.test.preview_settings \
  127.0.0.1:8000
```

Run and commit:

```bash
cd powerops-dashboard
python -m stestr run
tox -e pep8
git add .
git commit -m "feat: finish safe PowerOps Horizon workflows"
```

Expected: full plugin suite passes; mock UI is inspectable without OpenStack
or any mutation path.

---

### Task 10: Teach Kolla to package and activate the local components

**Files:**
- Modify: `worktrees/kolla-horizon-clean/kolla/common/sources.py`
- Modify: `worktrees/kolla-horizon-clean/docker/horizon/extend_start.sh`
- Create: `worktrees/kolla-horizon-clean/kolla/tests/test_powerops_plugins.py`
- Create: `build/kolla-build.conf`
- Create: `patches/kolla/0001-feat-package-PowerOps-Horizon-and-Mistral-components.patch`

**Interfaces:**
- Produces Kolla source `horizon-plugin-powerops-dashboard`.
- Produces Kolla source `mistral-base-plugin-mistral-lib`.
- Consumes local patched Mistral through the standard `mistral` source override.
- Produces Horizon runtime gate `ENABLE_POWEROPS=yes|no`.

- [ ] **Step 1: Write failing source-parent tests**

Assert `SOURCES` contains disabled-by-default local entries:

```python
{
    'horizon-plugin-powerops-dashboard': {
        'type': 'local',
        'location': '$locals_base/powerops-dashboard',
        'enabled': False,
    },
    'mistral-base-plugin-mistral-lib': {
        'type': 'local',
        'location': '$locals_base/worktrees/mistral-lib-horizon-clean',
        'enabled': False,
    },
}
```

Use Kolla's source-parent parser to prove the first attaches only to `horizon`
and the second only to `mistral-base`.

- [ ] **Step 2: Write failing Horizon activation tests**

Inspect `docker/horizon/extend_start.sh` and assert it copies:

```text
${SITE_PACKAGES}/poweropsdashboard/enabled/_50_powerops.py
```

to:

```text
${SITE_PACKAGES}/openstack_dashboard/local/enabled/_50_powerops.py
```

only when `${ENABLE_POWEROPS:-no}` is enabled, using the existing
`config_dashboard` helper before static collection.

- [ ] **Step 3: Run RED**

```bash
cd worktrees/kolla-horizon-clean
python -m pytest -q kolla/tests/test_powerops_plugins.py
```

Expected: both source entries and activation function are absent.

- [ ] **Step 4: Add opt-in sources and activation**

Add the two exact `SOURCES` entries from Step 1. Add:

```bash
function config_powerops_dashboard {
    config_dashboard "${ENABLE_POWEROPS:-no}" \
        "${SITE_PACKAGES}/poweropsdashboard/enabled/_50_powerops.py" \
        "${SITE_PACKAGES}/openstack_dashboard/local/enabled/_50_powerops.py"
}
```

Call `config_powerops_dashboard` next to existing dashboard activation before
the settings/static check. Do not run `pip` from container startup.

- [ ] **Step 5: Add a secret-free local build configuration**

Create `build/kolla-build.conf`:

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
location = $locals_base/worktrees/mistral-horizon-clean

[mistral-base-plugin-mistral-lib]
type = local
location = $locals_base/worktrees/mistral-lib-horizon-clean
enabled = true
```

Do not add registry credentials or a production registry hostname.

- [ ] **Step 6: Run Kolla tests and commit**

```bash
cd worktrees/kolla-horizon-clean
python -m pytest -q \
  kolla/tests/test_powerops_plugins.py \
  kolla/tests/test_build.py
tox -e pep8 -- kolla/common/sources.py \
  kolla/tests/test_powerops_plugins.py
git add kolla/common/sources.py docker/horizon/extend_start.sh \
  kolla/tests/test_powerops_plugins.py
git commit -m "feat: package PowerOps Horizon and Mistral components"
```

- [ ] **Step 7: Export and clean-apply the Kolla patch**

```bash
cd worktrees/kolla-horizon-clean
mkdir -p ../../patches/kolla
git format-patch --output-directory ../../patches/kolla \
  d14cef9bbafa0db561abfb0c0299d1d6bbbf8f0c..HEAD
```

Expected: exactly
`patches/kolla/0001-feat-package-PowerOps-Horizon-and-Mistral-components.patch`.
Apply it in another detached worktree at the exact Kolla baseline, rerun
`test_powerops_plugins.py` and compare tree hashes:

```bash
cd /tmp/powerops-horizon-clean-v2
git -C sources/kolla worktree add \
  /tmp/kolla-horizon-apply \
  d14cef9bbafa0db561abfb0c0299d1d6bbbf8f0c
git -C /tmp/kolla-horizon-apply am \
  "$PWD/patches/kolla/0001-feat-package-PowerOps-Horizon-and-Mistral-components.patch"
git -C /tmp/kolla-horizon-apply write-tree
git -C worktrees/kolla-horizon-clean write-tree
cd /tmp/kolla-horizon-apply
python -m pytest -q kolla/tests/test_powerops_plugins.py
git status --short
```

Expected: equal printed tree hashes, test passes and the applied worktree is
clean. Commit the patch plus `build/kolla-build.conf` in the root repository:

```bash
cd /tmp/powerops-horizon-clean-v2
git add patches/kolla build/kolla-build.conf
git commit -m "build: add PowerOps image packaging patch"
```

---

### Task 11: Configure and validate Horizon PowerOps through Kolla-Ansible

**Files:**
- Modify: `worktrees/kolla-ansible-horizon-verify/ansible/group_vars/all.yml`
- Modify: `worktrees/kolla-ansible-horizon-verify/ansible/roles/horizon/defaults/main.yml`
- Modify: `worktrees/kolla-ansible-horizon-verify/ansible/roles/horizon/templates/_9998-kolla-settings.py.j2`
- Modify: `worktrees/kolla-ansible-horizon-verify/ansible/roles/horizon/tasks/precheck.yml`
- Modify: `worktrees/kolla-ansible-horizon-verify/ansible/roles/horizon/tasks/deploy.yml`
- Create: `worktrees/kolla-ansible-horizon-verify/ansible/roles/horizon/tasks/powerops.yml`
- Modify: `worktrees/kolla-ansible-horizon-verify/ansible/roles/mistral/defaults/main.yml`
- Modify: `worktrees/kolla-ansible-horizon-verify/ansible/roles/mistral/tasks/register.yml`
- Modify: `worktrees/kolla-ansible-horizon-verify/ansible/roles/mistral/tasks/precheck.yml`
- Modify: `worktrees/kolla-ansible-horizon-verify/ansible/roles/mistral/tasks/powerops.yml`
- Modify: `worktrees/kolla-ansible-horizon-verify/ansible/roles/mistral/files/power_ops.yaml`
- Create: `worktrees/kolla-ansible-horizon-verify/kolla_ansible/tests/unit/test_powerops_horizon.py`
- Modify: `worktrees/kolla-ansible-horizon-verify/kolla_ansible/tests/unit/test_powerops_configuration_contract.py`
- Modify: `worktrees/kolla-ansible-horizon-verify/kolla_ansible/tests/unit/test_powerops_templates.py`
- Modify: `worktrees/kolla-ansible-horizon-verify/kolla_ansible/tests/unit/test_powerops_registration.py`
- Create: `patches/kolla-ansible/0007-feat-configure-Horizon-PowerOps-RBAC-and-image.patch`
- Create: `patches/kolla-ansible/0008-feat-validate-Horizon-PowerOps-runtime-contract.patch`

**Interfaces:**
- Produces derived `enable_horizon_powerops` only when Horizon, Mistral and PowerOps are enabled.
- Produces selected `powerops_horizon_image:powerops_horizon_tag`.
- Produces exact Horizon settings from the same allowlist/region variables as Mistral.
- Ensures the Keystone role object `powerops_operator` exists without assigning it.
- Reconciles exactly six PowerOps actions and five workflows.
- Runs only read-only container import/definition checks after deployment.

- [ ] **Step 1: Create a branch after the verified six-patch patch treeline**

```bash
git -C worktrees/kolla-ansible-horizon-verify switch \
  -c powerops/kolla-ansible-horizon-clean
git -C worktrees/kolla-ansible-horizon-verify status --short --branch
```

Expected: clean branch whose parent tree is
`c1488cb1a5db61d102bd55a9e9a2fafb5c25426c` and already includes WSGI patch
`0006`.

- [ ] **Step 2: Write failing shared-setting and image tests**

Assert these defaults:

```yaml
enable_horizon_powerops: >-
  {{ enable_horizon | bool and enable_mistral | bool and enable_powerops | bool }}
powerops_horizon_image: ""
powerops_horizon_tag: ""
powerops_allowed_project_names:
  - "{{ openstack_auth.project_name }}"
powerops_allowed_user_names:
  - "{{ openstack_auth.username }}"
```

When the derived flag is true, Horizon selects the PowerOps image and sets
`ENABLE_POWEROPS=yes`; otherwise it uses `horizon_image_full` and
`ENABLE_POWEROPS=no`. Keep existing `ENABLE_MISTRAL` independent.

Render both service configurations from:

```yaml
openstack_region_name: RegionOne
powerops_allowed_project_names: [admin, ops-project]
powerops_allowed_user_names: [admin, ops-user]
```

Assert Horizon receives Python lists and Mistral receives equivalent `ListOpt`
values. Existing validation for list type, non-empty trimmed unique strings and
comma rejection remains active.

- [ ] **Step 3: Write failing Keystone role object tests**

With PowerOps enabled, `mistral_ks_roles` resolves to exactly:

```yaml
- powerops_operator
```

With PowerOps disabled, it resolves to `[]`. Assert
`service_ks_register_roles` receives the list, while
`service_ks_register_user_roles` is not added and no role-assignment or implied
role task exists.

- [ ] **Step 4: Write failing registration/runtime tests**

Update expected names to exactly:

```python
ACTIONS = {
    'powerops.host_inventory',
    'powerops.host_power_status',
    'powerops.planned_power_off',
    'powerops.planned_reboot',
    'powerops.power_on_for_inspection',
    'powerops.return_to_service',
}
WORKFLOWS = {
    'power_ops.host_inventory',
    'power_ops.host_power_status',
    'power_ops.planned_power_off',
    'power_ops.planned_reboot',
    'power_ops.power_on_and_return',
}
```

Assert post-start checks import patched Mistral/mistral-lib in API, Engine and
Executor, and import `poweropsdashboard` in Horizon. Explicitly reject commands
containing execution POST/PUT, workflow start/resume, Nova/Ironic mutation,
Masakari notification or etcd writes.

- [ ] **Step 5: Run RED**

```bash
cd worktrees/kolla-ansible-horizon-verify
python3 -m unittest \
  kolla_ansible.tests.unit.test_powerops_configuration_contract \
  kolla_ansible.tests.unit.test_powerops_templates \
  kolla_ansible.tests.unit.test_powerops_registration \
  kolla_ansible.tests.unit.test_powerops_horizon -v
```

Expected: Horizon settings/image/role/inventory checks are absent.

- [ ] **Step 6: Implement shared settings and role creation**

Select the image in Horizon defaults:

```yaml
image: >-
  {{ powerops_horizon_image ~ ':' ~ powerops_horizon_tag
     if enable_horizon_powerops | bool else horizon_image_full }}
environment:
  ENABLE_POWEROPS: "{{ 'yes' if enable_horizon_powerops | bool else 'no' }}"
```

Render only:

```jinja
POWEROPS_REGION_NAME = {{ openstack_region_name | to_json }}
POWEROPS_ALLOWED_PROJECT_NAMES = {{ powerops_allowed_project_names | to_json }}
POWEROPS_ALLOWED_USER_NAMES = {{ powerops_allowed_user_names | to_json }}
POWEROPS_MOCK_MODE = False
```

Add `mistral_ks_roles` and pass it through `service_ks_register_roles`. Do not
render passwords credentials into Horizon.

- [ ] **Step 7: Reconcile the extended workbook and read-only runtime checks**

Copy `worktrees/mistral-horizon-clean/etc/mistral/power_ops.yaml` byte-for-byte
into the Kolla-Ansible role and prove equality with `cmp`. Extend existing
reconciliation validation to six actions/five workflows.

`horizon/tasks/powerops.yml` runs one read-only container command that imports
the package/enabled module, loads Django settings and compares the configured
region and allowlists. It performs no HTTP request and no Mistral execution.

- [ ] **Step 8: Run suites and commit two review gates**

```bash
cd worktrees/kolla-ansible-horizon-verify
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

python3 -m unittest \
  kolla_ansible.tests.unit.test_powerops_registration \
  kolla_ansible.tests.unit.test_powerops_horizon -v
python3 kolla_ansible/tests/unit/test_masakari_wsgi_wrapper.py -v
git add ansible/roles/mistral/files/power_ops.yaml \
  ansible/roles/mistral/tasks/powerops.yml \
  ansible/roles/horizon/tasks/deploy.yml \
  ansible/roles/horizon/tasks/powerops.yml \
  kolla_ansible/tests/unit/test_powerops_registration.py \
  kolla_ansible/tests/unit/test_powerops_horizon.py
git commit -m "feat: validate Horizon PowerOps runtime contract"
```

Expected: WSGI 3/3 remains green and two new component commits exist after the
six published commits.

- [ ] **Step 9: Export exact patches 0007 and 0008**

```bash
cd worktrees/kolla-ansible-horizon-verify
git format-patch --numbered --start-number 7 -2 \
  --output-directory ../../patches/kolla-ansible
```

Apply all eight Kolla-Ansible patches to another clean worktree at
`703b06c9fa5771c758f703b424d63fb04192567a`, run the four focused suites plus
the WSGI suite, and compare tree hashes:

```bash
cd /tmp/powerops-horizon-clean-v2
git -C sources/kolla-ansible worktree add \
  /tmp/kolla-ansible-horizon-apply \
  703b06c9fa5771c758f703b424d63fb04192567a
git -C /tmp/kolla-ansible-horizon-apply am \
  "$PWD"/patches/kolla-ansible/*.patch
git -C /tmp/kolla-ansible-horizon-apply write-tree
git -C worktrees/kolla-ansible-horizon-verify write-tree
cd /tmp/kolla-ansible-horizon-apply
python3 -m unittest \
  kolla_ansible.tests.unit.test_powerops_configuration_contract \
  kolla_ansible.tests.unit.test_powerops_templates \
  kolla_ansible.tests.unit.test_powerops_registration \
  kolla_ansible.tests.unit.test_powerops_horizon -v
python3 kolla_ansible/tests/unit/test_masakari_wsgi_wrapper.py -v
git status --short
```

Expected: equal tree hashes and all five suites pass.

```bash
cd /tmp/powerops-horizon-clean-v2
git add patches/kolla-ansible
git commit -m "build: add Horizon PowerOps deployment patches"
```

---

### Task 12: Close cross-repository contracts, build images and publish the operations guide

**Files:**
- Create: `tests/test_horizon_powerops_contract.py`
- Modify: `tests/test_cross_repository_contract.py`
- Modify: `tests/test_delivery_artifacts.py`
- Create: `POWEROPS_HORIZON_OPERATIONS.md`
- Modify: `INSTALL.md`
- Modify: `DELIVERY.md`
- Modify: `SHA256SUMS`
- Modify: `docs/evidence/2026-09-02-horizon-powerops-backend-readiness.md`

**Interfaces:**
- Proves five exact workflow names, six action names, shared settings and lock namespace across repositories.
- Produces local Horizon, Mistral API, Engine and Executor images tagged `powerops-local/*:2025.1-powerops`.
- Produces a separate Russian operations guide and explicit static-versus-runtime evidence boundary.
- Produces final ordered patch manifest of 36 patches.

- [ ] **Step 1: Write failing cross-repository contract tests**

`tests/test_horizon_powerops_contract.py` must parse source, workbook and Kolla
templates and assert:

```python
WORKFLOWS = {
    'power_ops.host_inventory',
    'power_ops.host_power_status',
    'power_ops.planned_power_off',
    'power_ops.planned_reboot',
    'power_ops.power_on_and_return',
}
INSTANCE_POLICIES = {'require_empty', 'live_migrate', 'stop'}
ROLE_NAMES = {'admin', 'powerops_operator'}
```

Also prove:

- Horizon calls no other workflow;
- `planned_reboot` UI always emits `allow_hard_off=False`;
- hard-off controls occur only in admin power-off form code;
- Horizon and Mistral consume the same allowlist variable names;
- Mistral and Masakari contain exact `powerops/host/<host>` lock prefix;
- the Kolla-Ansible workbook is byte-identical to the Mistral workbook;
- WSGI patch `0006` remains present and unchanged;
- plugin imports no Nova, Masakari, Ironic or Redfish mutation client;
- no UI route contains emergency fencing/evacuation operations.

Run and expect RED until all component artifacts are present:

```bash
python3 -m unittest tests.test_horizon_powerops_contract -v
```

- [ ] **Step 2: Extend delivery artifact tests and document contract**

Update expected counts to:

```python
EXPECTED_PATCH_COUNTS = {
    'masakari': 10,
    'mistral-lib': 1,
    'mistral': 16,
    'kolla': 1,
    'kolla-ansible': 8,
}
```

Assert the new spec, plan, evidence, standalone plugin and operations guide are
tracked. Update `INSTALL.md` and `DELIVERY.md` with exact baselines, ordered
patch paths, component/image dependencies and current test counts only after
commands have run.

- [ ] **Step 3: Write the separate Russian operations guide**

`POWEROPS_HORIZON_OPERATIONS.md` contains these independently searchable
sections:

```text
Назначение и границы
Роли admin и powerops_operator
Настройка project/user allowlist
Установка и включение Horizon-плагина
Проверка Masakari WSGI и API
Плановое выключение
Плановая перезагрузка
Включение и возврат в эксплуатацию
Политики require_empty, live_migrate и stop
Hard-off только для admin
Состояния Mistral execution
Ошибки 403, 409, 422, 503 и неопределённый timeout
Диагностика Nova, Masakari, Ironic и etcd lock
Разделение планового Mistral и аварийного Masakari
```

Use concrete role commands with operator-selected shell variables:

```bash
POWEROPS_PROJECT_NAME=powerops-operators
POWEROPS_USER_NAME=svc-powerops
openstack role create --or-show powerops_operator
openstack role add \
  --project "$POWEROPS_PROJECT_NAME" \
  --user "$POWEROPS_USER_NAME" \
  powerops_operator
openstack role assignment list \
  --project "$POWEROPS_PROJECT_NAME" \
  --user "$POWEROPS_USER_NAME" \
  --names
```

State that `admin` works in any project and bypasses both allowlists; the two
lists apply only to `powerops_operator`. State that Mistral service credentials
do not require the human `powerops_operator` role.

- [ ] **Step 4: Run standalone package and mock preview gates**

```bash
cd /tmp/powerops-horizon-clean-v2
python3 -m venv /tmp/powerops-horizon-2025.1-venv
/tmp/powerops-horizon-2025.1-venv/bin/python -m pip install \
  -c https://releases.openstack.org/constraints/upper/2025.1 \
  -e worktrees/horizon-powerops-clean \
  -e powerops-dashboard
/tmp/powerops-horizon-2025.1-venv/bin/python -m pip install \
  -c https://releases.openstack.org/constraints/upper/2025.1 \
  -r powerops-dashboard/test-requirements.txt build
cd powerops-dashboard
/tmp/powerops-horizon-2025.1-venv/bin/python -m stestr run
/tmp/powerops-horizon-2025.1-venv/bin/python manage.py check \
  --settings=poweropsdashboard.test.preview_settings
tox -e pep8
/tmp/powerops-horizon-2025.1-venv/bin/python -m build
/tmp/powerops-horizon-2025.1-venv/bin/python manage.py runserver \
  --settings=poweropsdashboard.test.preview_settings \
  127.0.0.1:8000
```

Open only `http://127.0.0.1:8000/` and verify one-region navigation, both host
states, all three policies, admin/operator visibility, power-off-only hard-off,
VM impact list, running/error/paused execution views and resume checklist. Stop
the local preview after inspection. Record screenshots only if the user asks;
do not treat mock rendering as OpenStack runtime proof.

- [ ] **Step 5: Build four local Kolla images without deployment**

From `worktrees/kolla-horizon-clean`:

```bash
cd worktrees/kolla-horizon-clean
kolla-build \
  --config-file "$PWD/../../build/kolla-build.conf" \
  --locals-base "$PWD/../.." \
  '^(horizon|mistral-api|mistral-engine|mistral-executor)$'
```

The build may download dependencies/base images but does not authorize push,
deploy, reconfigure, container replacement or restart.

- [ ] **Step 6: Inspect image contents without service entrypoints**

```bash
docker run --rm --entrypoint python \
  powerops-local/horizon:2025.1-powerops -c \
  "import importlib.metadata as m; import poweropsdashboard; assert m.version('powerops-dashboard')"
docker run --rm --entrypoint python \
  powerops-local/mistral-api:2025.1-powerops -c \
  "from mistral_lib.actions.context import SecurityContext, ExecutionContext; assert hasattr(SecurityContext(), 'roles'); assert hasattr(SecurityContext(), 'user_id'); assert hasattr(ExecutionContext(), 'workflow_resume_authorization')"
docker run --rm --entrypoint python \
  powerops-local/mistral-engine:2025.1-powerops -c \
  "from mistral.services import powerops; assert powerops.ADMIN_ROLE == 'admin'"
docker run --rm --entrypoint python \
  powerops-local/mistral-executor:2025.1-powerops -c \
  "from mistral.actions.powerops.inventory import HostInventoryAction; assert HostInventoryAction"
```

Record image IDs and exact results. Do not start normal Horizon/Mistral
entrypoints and do not connect to a real service catalog.

- [ ] **Step 7: Regenerate checksums and clean-apply all chains**

```bash
cd /tmp/powerops-horizon-clean-v2
find patches -type f -name '*.patch' -print0 \
  | sort -z \
  | xargs -0 shasum -a 256 > SHA256SUMS
shasum -a 256 -c SHA256SUMS
test "$(find patches -type f -name '*.patch' | wc -l | tr -d ' ')" -eq 36
```

Clean-apply in this dependency order:

1. 10 Masakari patches;
2. 1 mistral-lib patch;
3. 16 Mistral patches with the patched mistral-lib on `PYTHONPATH`;
4. 1 Kolla patch;
5. 8 Kolla-Ansible patches, including WSGI patch `0006` before Horizon patches.

For every applied tree run its focused suite and compare `git write-tree` with
the implementation tree. Preserve a failed tree for diagnosis until the cause
is recorded; use `git am --abort` only in that disposable tree.

- [ ] **Step 8: Run the complete source/delivery verification**

```bash
cd /tmp/powerops-horizon-clean-v2
python3 -m unittest tests.test_delivery_artifacts -v
POWEROPS_MASAKARI_TREE="$PWD/worktrees/masakari-horizon-verify" \
POWEROPS_MISTRAL_LIB_TREE="$PWD/worktrees/mistral-lib-horizon-clean" \
POWEROPS_MISTRAL_TREE="$PWD/worktrees/mistral-horizon-clean" \
POWEROPS_DASHBOARD_TREE="$PWD/powerops-dashboard" \
POWEROPS_KOLLA_TREE="$PWD/worktrees/kolla-horizon-clean" \
POWEROPS_KOLLA_ANSIBLE_TREE="$PWD/worktrees/kolla-ansible-horizon-verify" \
python3 -m unittest \
  tests.test_cross_repository_contract \
  tests.test_horizon_powerops_contract -v
shasum -a 256 -c SHA256SUMS
python3 -m compileall -q tests
git diff --check
```

Expected: every command passes. Record exact observed counts, not historical
counts from the old Horizon attempt.

- [ ] **Step 9: Record the evidence boundary and commit delivery**

`DELIVERY.md` and the readiness evidence must distinguish:

```text
Proven: clean patch application, source tests, plugin tests, mock UI,
        image build and read-only image import.
Not proven: deployed Horizon/Mistral/Masakari behavior, Keystone assignments,
            real service endpoints, etcd ownership, VM migration/stop/start,
            Ironic/BMC power and Masakari evacuation.
```

Commit only after all recorded claims match current command output:

```bash
cd /tmp/powerops-horizon-clean-v2
git add powerops-dashboard patches build \
  POWEROPS_HORIZON_OPERATIONS.md INSTALL.md DELIVERY.md SHA256SUMS \
  tests docs/evidence
git commit -m "feat: deliver Horizon PowerOps integration"
git status --short --branch
```

Expected: clean root worktree. Do not push, deploy or start any real operation
without a separate user request.
