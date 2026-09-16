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
  child-definition ownership, deterministic VM pacing and deploy
  non-mutation.

- [ ] **Step 1: Write the failing contract suite**

Implement the assertions in `tests/test_cross_repository_contract.py` with
only the Python standard library. Parse Python sources with `ast`, entry-point
groups with `configparser`, and the controlled workbook/Ansible structures
without importing Masakari, Mistral, Kolla-Ansible or their dependencies.

The suite must cover the actual completed source contracts, including the
companion Mistral owner-scoped workbook update and Kolla's fail-closed handling
of ambiguous or foreign public workbook rows. Missing environment variables
or required source files must produce explicit assertion messages.

Workbook child ownership must be checked end-to-end with AST assertions. The
workbook service must pass `project_id=wb_db.project_id` for both action and
workflow definitions, the DB facade must preserve that argument, and both SQL
backend operations must validate it against the request project before an
exact `project_id + name + namespace` lookup using the same transaction
session. Require the direct AST chain
`model_query(..., session=session).filter(sa.and_(project, name,
namespace)).first()` with exactly those three comparison predicates. The
common lookup must reject every `sa.or_`, extra predicate, alternate filter and
public-aware fallback. Do not require or reject secure-model assignment of
`project_id` in the values mapping: that is owned by Mistral's existing
secure-model hook.

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
absent. Against the otherwise patched Mistral commit
`665cde880127f56c8335e6f8b210362f87ae19d9`, the child owner-scope test must
also fail because ownership is not propagated to generated action and workflow
definitions.

- [ ] **Step 3: Run after all repositories are complete and verify GREEN**

```bash
POWEROPS_MASAKARI_TREE="$PWD/worktrees/masakari-powerops" \
POWEROPS_MISTRAL_TREE="$PWD/worktrees/mistral-powerops" \
POWEROPS_KOLLA_TREE="$PWD/work/kolla-ansible" \
python3 -m unittest tests.test_cross_repository_contract -v
```

Expected: PASS with no network or service access.

The completed Mistral source for this check is
`3e4fe82455de7473809b0e0bc677fa3df3a3d1e2`. Mutation checks must independently
remove the project argument from either child-definition call and replace the
exact direct filter with an outer public-aware `sa.or_`; removing
`session=session` from the model query must also fail. Each mutation must fail
the child owner-scope test.

- [ ] **Step 4: Commit the contract suite in the artifact repository**

```bash
git add tests docs/superpowers/plans/2026-08-31-powerops-integration.md
git commit -m "test: cover workbook child ownership contract"
```

---

### Task 3: Produce a verified installation guide and delivery manifest

**Files:**
- Create: `INSTALL.md`
- Create: `DELIVERY.md`
- Create: `SHA256SUMS`
- Create: `tests/test_delivery_artifacts.py`
- Modify: `docs/superpowers/plans/2026-08-31-kolla-ansible-powerops.md`
- Modify: `docs/superpowers/plans/2026-08-31-mistral-powerops.md`
- Modify: `docs/superpowers/plans/2026-08-31-powerops-integration.md`
- Modify: `docs/superpowers/specs/2026-08-31-openstack-powerops-design.md`

**Interfaces:**
- Consumes: all exported patch files and repository verification outputs.
- Produces: exact patch ordering, baselines, checksums, safe apply/recovery,
  image/configuration gates and verification boundary.
- Excludes: source worktrees and any credentials from the artifact commit.

- [ ] **Step 1: Write the failing delivery-artifact contract**

Use only the standard library. Require:

- all installation/delivery headings and exact baseline/final identities;
- 10 Masakari, 10 Mistral and 5 Kolla patch paths in exact application order;
- the actual patch filesystem set is exactly the expected 25 paths, with no
  unmanifested 26th patch, and sorted checksum hashes match those bytes;
- exactly four patched runtime image repository/tag pairs and no invented
  image-build command;
- non-empty exact caller allowlists, etcd coordination, controller CA
  distinction/manual pre-gate check and deploy/reconfigure mutation gate;
- valid Mistral/Ironic read-only CLI commands that expose every claimed field;
- subcommand-first Kolla CLI forms
  `kolla-ansible prechecks -i /path/to/inventory`,
  `kolla-ansible deploy -i /path/to/inventory` and
  `kolla-ansible reconfigure -i /path/to/inventory`, while rejecting the
  obsolete inventory-first order;
- exact resume JSON, safe `git am --abort` recovery and rollback boundaries;
- final `Workbook` plus child `ActionDefinition`/`WorkflowDefinition`
  collision/owner-scope contract in plans and design;
- the bounded audit terminology: a `structured LOG.info process log` with no
  external durable audit store and no delivery or persistence guarantee.

Run `python3 -m unittest tests.test_delivery_artifacts -v` before creating the
three root artifacts. Expected RED: missing `INSTALL.md`, `DELIVERY.md` and
`SHA256SUMS`, plus stale plan/design assertions.

- [ ] **Step 2: Create checksums for immutable patch outputs**

```bash
find patches -type f -name '*.patch' -print0 \
  | sort -z \
  | xargs -0 shasum -a 256 > SHA256SUMS
shasum -a 256 -c SHA256SUMS
POWEROPS_PATCH_COUNT="$(find patches -type f -name '*.patch' | wc -l | tr -d ' ')"
test "$POWEROPS_PATCH_COUNT" -eq 25
```

Expected: every patch reports `OK`.

- [ ] **Step 3: Write detailed Russian `INSTALL.md`**

Pin full Masakari/Mistral baseline and final SHAs plus the Kolla archive hash,
internal import and final SHA/tree. Final Mistral is
`3e4fe82455de7473809b0e0bc677fa3df3a3d1e2` / tree
`8e3009eb1abf8033608d31d7e60cdb02ab8da1ed`; final Kolla is
`63a8d0f597f9034a42f2e1b0bd415f1746d33b8d` / tree
`287bac4223f24393c32fbfd55c140601c8611a21`. Give exact `git am` commands on
separate clean integration branches and abort/recovery handling. Document the
dependency `Kolla 0004 -> Mistral 0010`.

Do not invent an image build recipe: the bundle does not contain one. State
requirements for the operator's existing image pipeline and entry-point
acceptance for exactly Masakari Engine plus Mistral API/Engine/Executor;
Mistral Event Engine may remain vanilla.

Provide a secret-free `globals.yml` example with required services, image/tag
pairs, strict allowlists, etcd/timing/reconcile/validate options and the
controller-only `kolla_admin_openrc_cacert` distinction. Make prechecks and one
of deploy/reconfigure explicit mutation gates. State accurately that prechecks
do not validate the controller CA: require `test -f`/`test -r` before approval,
and explain that Kolla repeats `stat` only inside deploy/reconfigure after
handler flush and action population. State that deployment never executes
workflows or Nova/Ironic mutations, then document valid `openstack action
definition list` and exact per-node Ironic field reads, separately authorised
canary, exact return resume JSON and non-destructive source/image/config/
workbook rollback.

- [ ] **Step 4: Write `DELIVERY.md` with exact evidence**

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

- [ ] **Step 5: Align final plans and design**

Replace Kolla Task 4's obsolete direct-workbook GET contract with exact
unbounded list/filter/ownership validation, controller CA `stat`, direct action
GETs, exact per-workflow filtered GETs and token-project assertions. Record
that the companion Mistral owner-scoped update closes the remaining TOCTOU
window atomically for the workbook and both child-definition model types in
one SQLAlchemy transaction. Add the final Mistral security task/commit and this
delivery task to their executable plans. Describe action audit output only as
a structured process log, never as a durable delivered event.

- [ ] **Step 6: Re-run clean-apply and contract verification**

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

- [ ] **Step 7: Verify delivery contracts and commit**

```bash
python3 -m unittest tests.test_delivery_artifacts -v
POWEROPS_MASAKARI_TREE="$PWD/worktrees/masakari-powerops" \
POWEROPS_MISTRAL_TREE="$PWD/worktrees/mistral-powerops" \
POWEROPS_KOLLA_TREE="$PWD/work/kolla-ansible" \
  python3 -m unittest tests.test_cross_repository_contract -v
shasum -a 256 -c SHA256SUMS
python3 -m compileall -q tests
git diff --check
```

Expected: delivery suite 10/10, cross-repository 19/19, artifact discovery
29/29, Kolla 64/64, final affected Mistral combined 332/332, all 25 checksums
OK, compileall and diff hygiene clean. The final Mistral full serial run
stopped after 829 following known sandbox socket failures, so there is no
final full-suite PASS claim; the earlier 1620 passed, 8 skipped result is
historic pre-expanded evidence only.

```bash
git add INSTALL.md DELIVERY.md SHA256SUMS tests/test_delivery_artifacts.py \
  docs/superpowers/plans/2026-08-31-kolla-ansible-powerops.md \
  docs/superpowers/plans/2026-08-31-mistral-powerops.md \
  docs/superpowers/plans/2026-08-31-powerops-integration.md \
  docs/superpowers/specs/2026-08-31-openstack-powerops-design.md
git commit -m "docs: refresh delivery after ownership hardening"
```
