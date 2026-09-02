# Mistral-lib PowerOps Security Context Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the OpenStack 2025.1 `mistral-lib` action context with trusted user identity, role and workflow-resume authorization fields required by PowerOps.

**Architecture:** Keep the public change additive and backward compatible. `SecurityContext` carries a defensive copy of Keystone role names plus `user_id`; `ExecutionContext` carries an optional server-generated resume authorization mapping. The existing dictionary serializer transports both fields without a new wire format and accepts legacy payloads that omit them.

**Tech Stack:** Python 3.8+, `mistral-lib` stable/2025.1, `stestr`, `testtools`, PBR, Git format-patch.

**Spec:** `docs/superpowers/specs/2026-09-02-horizon-powerops-integration-design.md`

## Global Constraints

- Baseline `mistral-lib` commit is `693174dd0aac1da22870b31e4a2481c4e749916a` from `stable/2025.1`.
- The change is additive: existing constructor calls and serialized action contexts without the new keys must continue to work.
- Role values originate from validated Mistral request context; this library only transports them and must not infer authorization.
- Use exact role strings; do not lowercase, expand implied roles or synthesize `admin`.
- Copy caller-provided role lists so later caller mutation cannot alter the context.
- Never place tokens, passwords or service credentials in the resume authorization mapping.
- Produce one independently applicable patch under `patches/mistral-lib/`.
- Report source/unit verification separately from a built or running Mistral image.

---

### Task 1: Create the pinned component worktree

**Files:**
- Create during execution: `sources/mistral-lib/`
- Create during execution: `worktrees/mistral-lib-powerops/`

**Interfaces:**
- Produces source baseline: `693174dd0aac1da22870b31e4a2481c4e749916a`.
- Produces implementation branch: `powerops/security-context`.

- [ ] **Step 1: Materialize and verify the source baseline**

```bash
git clone https://opendev.org/openstack/mistral-lib.git sources/mistral-lib
git -C sources/mistral-lib fetch origin stable/2025.1
git -C sources/mistral-lib rev-parse 693174dd0aac1da22870b31e4a2481c4e749916a^{commit}
```

Expected: the last command prints exactly
`693174dd0aac1da22870b31e4a2481c4e749916a`.

- [ ] **Step 2: Create the isolated worktree**

Invoke `superpowers:using-git-worktrees`, then create the branch from the pinned
commit:

```bash
git -C sources/mistral-lib worktree add \
  -b powerops/security-context \
  ../../worktrees/mistral-lib-powerops \
  693174dd0aac1da22870b31e4a2481c4e749916a
git -C worktrees/mistral-lib-powerops status --short
```

Expected: the worktree is on `powerops/security-context` and status is empty.

---

### Task 2: Add backward-compatible trusted fields

**Files:**
- Modify: `worktrees/mistral-lib-powerops/mistral_lib/actions/context.py`
- Modify: `worktrees/mistral-lib-powerops/mistral_lib/tests/actions/test_context.py`

**Interfaces:**
- Produces: additive `SecurityContext` keyword arguments `user_id=None`,
  `user_name=None`, `roles=None` and `auth_token=None`.
- Produces: `SecurityContext.user_id: str | None`.
- Produces: `SecurityContext.roles: list[str]`.
- Produces: additive `ExecutionContext` keyword argument
  `workflow_resume_authorization=None`.
- Produces: `ExecutionContext.workflow_resume_authorization: dict | None`.
- Preserves: `ActionContextSerializer.serialize_to_dict()` and `deserialize_from_dict()` dictionary format.

- [ ] **Step 1: Write failing constructor and defensive-copy tests**

Add these cases to `TestActionsBase`:

```python
def test_security_context_carries_user_and_exact_roles(self):
    roles = ['admin', 'powerops_operator']
    security = context.SecurityContext(
        user_id='user-id',
        roles=roles,
    )

    roles.append('forged-after-construction')

    self.assertEqual('user-id', security.user_id)
    self.assertEqual(
        ['admin', 'powerops_operator'],
        security.roles,
    )

def test_security_context_defaults_roles_to_new_empty_list(self):
    first = context.SecurityContext()
    second = context.SecurityContext()

    first.roles.append('admin')

    self.assertEqual([], second.roles)

def test_execution_context_carries_resume_authorization(self):
    record = {
        'user_id': 'resume-user',
        'project_id': 'resume-project',
        'authorization_branch': 'admin',
        'authorized_at': '2026-09-02T10:00:00+00:00',
    }
    execution = context.ExecutionContext(
        workflow_resume_authorization=record,
    )

    self.assertEqual(record, execution.workflow_resume_authorization)
```

- [ ] **Step 2: Write failing serializer compatibility tests**

Add to `TestActionContextSerializer`:

```python
def test_round_trip_preserves_powerops_security_fields(self):
    action_ctx = context.ActionContext(
        context.SecurityContext(
            user_id='user-id',
            project_id='project-id',
            roles=['powerops_operator'],
        ),
        context.ExecutionContext(
            workflow_execution_id='workflow-id',
            workflow_resume_authorization={
                'user_id': 'resume-user',
                'project_id': 'resume-project',
                'authorization_branch': 'powerops_operator',
                'authorized_at': '2026-09-02T10:00:00+00:00',
            },
        ),
    )
    serializer = context.ActionContextSerializer()

    restored = serializer.deserialize_from_dict(
        serializer.serialize_to_dict(action_ctx)
    )

    self.assertEqual('user-id', restored.security.user_id)
    self.assertEqual(['powerops_operator'], restored.security.roles)
    self.assertEqual(
        action_ctx.execution.workflow_resume_authorization,
        restored.execution.workflow_resume_authorization,
    )

def test_deserializes_legacy_payload_without_powerops_fields(self):
    restored = context.ActionContextSerializer().deserialize_from_dict({
        'security': {'project_id': 'legacy-project'},
        'execution': {'workflow_execution_id': 'legacy-workflow'},
    })

    self.assertIsNone(restored.security.user_id)
    self.assertEqual([], restored.security.roles)
    self.assertIsNone(
        restored.execution.workflow_resume_authorization
    )
```

- [ ] **Step 3: Run the focused tests and verify RED**

```bash
cd worktrees/mistral-lib-powerops
python -m stestr run \
  mistral_lib.tests.actions.test_context.TestActionsBase \
  mistral_lib.tests.actions.test_context.TestActionContextSerializer
```

Expected: failures report unexpected `user_id`, `roles` and
`workflow_resume_authorization` constructor arguments.

- [ ] **Step 4: Implement the minimal additive fields**

Change the two constructors to this contract while preserving the order of all
existing arguments:

```python
class SecurityContext(object):
    def __init__(self, auth_uri=None, auth_cacert=None, insecure=None,
                 service_catalog=None, region_name=None,
                 is_trust_scoped=None, redelivered=None, expires_at=None,
                 trust_id=None, is_target=None, project_id=None,
                 project_name=None, user_id=None, user_name=None, roles=None,
                 auth_token=None):
        # Existing assignments remain unchanged.
        self.user_id = user_id
        self.user_name = user_name
        self.roles = list(roles) if roles else []
        self.auth_token = auth_token


class ExecutionContext(object):
    def __init__(self, workflow_execution_id=None, task_execution_id=None,
                 action_execution_id=None, workflow_name=None,
                 callback_url=None, task_id=None, with_items_index=0,
                 task_rerun_no=0, task_rerun_id=None,
                 workflow_propagated_headers=None,
                 workflow_resume_authorization=None):
        # Existing assignments remain unchanged.
        self.workflow_resume_authorization = (
            dict(workflow_resume_authorization)
            if workflow_resume_authorization else None
        )
```

Do not add convenience aliases such as `context.roles`; PowerOps consumes the
new values only through `context.security` and `context.execution`.

- [ ] **Step 5: Run focused tests and verify GREEN**

```bash
python -m stestr run \
  mistral_lib.tests.actions.test_context.TestActionsBase \
  mistral_lib.tests.actions.test_context.TestActionContextSerializer
```

Expected: all selected tests pass.

- [ ] **Step 6: Run the component checks**

```bash
python -m stestr run
tox -e pep8
git diff --check
```

Expected: the full `mistral-lib` suite and PEP8 pass and diff hygiene is clean.

- [ ] **Step 7: Commit the library change**

```bash
git add mistral_lib/actions/context.py \
  mistral_lib/tests/actions/test_context.py
git commit -m "feat: carry PowerOps identity in action context"
```

Expected: one focused commit on `powerops/security-context`.

---

### Task 3: Export and clean-apply the patch

**Files:**
- Create: `patches/mistral-lib/0001-feat-carry-PowerOps-identity-in-action-context.patch`

**Interfaces:**
- Produces: one patch consumed by the Mistral and image-integration plans.
- Produces: clean-apply evidence against the pinned stable/2025.1 baseline.

- [ ] **Step 1: Export the single patch**

```bash
mkdir -p patches/mistral-lib
git -C worktrees/mistral-lib-powerops format-patch \
  --output-directory "$PWD/patches/mistral-lib" \
  693174dd0aac1da22870b31e4a2481c4e749916a..HEAD
```

Expected: exactly one patch with the declared filename.

- [ ] **Step 2: Verify clean application in a disposable worktree**

```bash
git -C sources/mistral-lib worktree add \
  /tmp/mistral-lib-powerops-apply \
  693174dd0aac1da22870b31e4a2481c4e749916a
git -C /tmp/mistral-lib-powerops-apply am \
  "$PWD/patches/mistral-lib/0001-feat-carry-PowerOps-identity-in-action-context.patch"
git -C /tmp/mistral-lib-powerops-apply diff \
  693174dd0aac1da22870b31e4a2481c4e749916a..HEAD --check
```

Expected: `git am` succeeds and the diff check prints nothing.

- [ ] **Step 3: Commit the exported artifact in the delivery repository**

```bash
git add patches/mistral-lib \
  docs/superpowers/plans/2026-09-02-mistral-lib-powerops-security-context.md
git commit -m "build: add Mistral-lib PowerOps context patch"
```

Expected: the delivery repository records the plan and immutable patch bytes.
