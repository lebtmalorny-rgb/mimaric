# OpenStack PowerOps Integration and Delivery Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Execute and verify the three independent source patch plans as one contract-consistent, reproducible delivery.

**Architecture:** Masakari is implemented first because it owns emergency fencing, Mistral second because it owns planned operations, and Kolla-Ansible last because its templates and registration checks consume both source contracts. A repository-neutral contract suite compares action names, TaskFlow names, workbook bytes, lock namespaces and deployment safety invariants before patch export is accepted.

**Tech Stack:** Git worktrees, Python standard library/unittest, git format-patch/am, SHA-256.

**Spec:** `docs/superpowers/specs/2026-08-31-openstack-powerops-design.md`

## Global Constraints

- Execute the subsystem plans in this order: Masakari, Mistral, Kolla-Ansible, integration verification.
- Use isolated Git worktrees created through `superpowers:using-git-worktrees`.
- Use test-first implementation through `superpowers:test-driven-development`.
- Review each task before starting the next task.
- Never run live deploy, reconfigure, image pull, Nova mutation, Ironic power operation, BMC command or Masakari notification.
- Report static/source verification separately from live/runtime proof.

---

### Task 1: Execute subsystem plans at pinned baselines

**Files:**
- Consume: `docs/superpowers/plans/2026-08-31-masakari-powerops.md`
- Consume: `docs/superpowers/plans/2026-08-31-mistral-powerops.md`
- Consume: `docs/superpowers/plans/2026-08-31-kolla-ansible-powerops.md`
- Create during execution: `worktrees/masakari-powerops/`
- Create during execution: `worktrees/mistral-powerops/`
- Create during execution: `work/kolla-ansible/`

**Interfaces:**
- Produces: reviewed Masakari, Mistral and Kolla-Ansible commit series.
- Produces: `patches/masakari/*.patch`, `patches/mistral/*.patch`, and `patches/kolla-ansible/*.patch`.
- Preserves: ignored planning clones under `sources/` as read-only baseline references.

- [ ] **Step 1: Verify baseline identities before creating worktrees**

```bash
git -C sources/masakari rev-parse HEAD
git -C sources/mistral rev-parse HEAD
shasum -a 256 \
  ../kolla-ansible-enroll-ironic-patch-3.zip
```

Expected values:

```text
0fd34dd
3b2eab2
df27628ce641fefee30114ebeb3651490655aacb0930ad5bc30a298c88c3e08d
```

Accept full commit IDs whose prefixes match the first two values.

- [ ] **Step 2: Execute the Masakari plan with all review gates**

Follow every checkbox in
`docs/superpowers/plans/2026-08-31-masakari-powerops.md`. Do not start Mistral
until Masakari focused tests, full tests, lint, patch export and clean-apply
verification pass.

- [ ] **Step 3: Execute the Mistral plan with all review gates**

Follow every checkbox in
`docs/superpowers/plans/2026-08-31-mistral-powerops.md`. Do not start Kolla
until the action tests, workbook parser tests, full tests, lint, patch export
and clean-apply verification pass.

- [ ] **Step 4: Execute the Kolla-Ansible plan with all review gates**

Follow every checkbox in
`docs/superpowers/plans/2026-08-31-kolla-ansible-powerops.md`. Its workbook
copy must come from the completed Mistral worktree and compare byte-for-byte.

---

### Task 2: Add a cross-repository executable contract check

**Files:**
- Create: `tests/test_cross_repository_contract.py`
- Create: `tests/__init__.py`

**Interfaces:**
- Consumes environment variables: `POWEROPS_MASAKARI_TREE`, `POWEROPS_MISTRAL_TREE`, `POWEROPS_KOLLA_TREE`.
- Produces: source-only contract evidence without importing service packages or contacting APIs.
- Verifies: entry points, workflow bytes, lock scopes, fencing order, exact
  allowlists, etcd selection, patched image placement, workbook ownership,
  deterministic VM pacing and deploy non-mutation.

- [ ] **Step 1: Write the failing contract suite**

Implement the assertions in `tests/test_cross_repository_contract.py` with
only the Python standard library. Parse Python sources with `ast`, entry-point
groups with `configparser`, and the controlled workbook/Ansible structures
without importing Masakari, Mistral, Kolla-Ansible or their dependencies.

The suite must cover the actual completed source contracts, including the
companion Mistral owner-scoped workbook update and Kolla's fail-closed handling
of ambiguous or foreign public workbook rows. Missing environment variables
or required source files must produce explicit assertion messages.

Lock and pacing checks must assert AST parent/child scope at the real mutation
call sites, not only the presence or textual order of tokens. Kolla checks must
allowlist the permitted command tasks and URI endpoint/method pairs and reject
all workflow-execution CLI/API forms during deploy or reconfigure.

- [ ] **Step 2: Run before all repositories are complete and verify RED**

```bash
POWEROPS_MASAKARI_TREE="$PWD/sources/masakari" \
POWEROPS_MISTRAL_TREE="$PWD/sources/mistral" \
POWEROPS_KOLLA_TREE="$PWD/../kolla-ansible-enroll-ironic-patch-3" \
python3 -m unittest tests.test_cross_repository_contract -v
```

Expected: the pinned, unpatched trees fail because the PowerOps contracts are
absent; the old Mistral workbook update also fails the exact owner-scope
assertion.

- [ ] **Step 3: Run after all repositories are complete and verify GREEN**

```bash
POWEROPS_MASAKARI_TREE="$PWD/worktrees/masakari-powerops" \
POWEROPS_MISTRAL_TREE="$PWD/worktrees/mistral-powerops" \
POWEROPS_KOLLA_TREE="$PWD/work/kolla-ansible" \
python3 -m unittest tests.test_cross_repository_contract -v
```

Expected: PASS with no network or service access.

- [ ] **Step 4: Commit the contract suite in the artifact repository**

```bash
git add tests
git commit -m "test: verify cross-repository PowerOps contracts"
```

---

### Task 3: Produce a verified delivery manifest

**Files:**
- Create: `DELIVERY.md`
- Create: `SHA256SUMS`
- Modify: `.gitignore`

**Interfaces:**
- Consumes: all exported patch files and repository verification outputs.
- Produces: exact patch ordering, baselines, checksums and verification boundary.
- Excludes: source worktrees and any credentials from the artifact commit.

- [ ] **Step 1: Extend ignores for execution worktrees**

Add:

```gitignore
/work/
/worktrees/
```

Keep the existing `/sources/` ignore.

- [ ] **Step 2: Create checksums for immutable patch outputs**

```bash
find patches -type f -name '*.patch' -print0 \
  | sort -z \
  | xargs -0 shasum -a 256 > SHA256SUMS
shasum -a 256 -c SHA256SUMS
```

Expected: every patch reports `OK`.

- [ ] **Step 3: Write `DELIVERY.md` with exact evidence**

Use these sections:

```markdown
# OpenStack PowerOps patch delivery

## Baselines
## Patch order
## Implemented scenarios
## Test commands and results
## Static verification boundary
## Live verification still required
## Safe apply and rollback notes
```

List patch filenames in application order, full baseline commit IDs/archive
hash, test commands with actual pass/fail counts, and the direct path to the
Russian Kolla runbook. State explicitly that no images were built or pushed,
no deployment/reconfiguration was run, and no physical power or VM operation
was performed.

- [ ] **Step 4: Re-run clean-apply and contract verification**

Apply each patch series to a fresh declared baseline exactly as specified in
its subsystem plan, then run:

```bash
POWEROPS_MASAKARI_TREE=/tmp/masakari-powerops-apply \
POWEROPS_MISTRAL_TREE=/tmp/mistral-powerops-apply \
POWEROPS_KOLLA_TREE=/tmp/kolla-powerops-apply \
python -m unittest tests.test_cross_repository_contract -v
git diff --check
shasum -a 256 -c SHA256SUMS
```

Expected: PASS, clean diff hygiene, and all checksums `OK`.

- [ ] **Step 5: Commit the delivery manifest**

```bash
git add .gitignore DELIVERY.md SHA256SUMS patches
git commit -m "docs: publish verified PowerOps patch delivery"
```
