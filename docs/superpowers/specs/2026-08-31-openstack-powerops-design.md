# OpenStack PowerOps Design

## Purpose

Implement safe physical power control and host fencing for OpenStack Epoxy
2025.1 using three independent patch series for Kolla-Ansible, Masakari and
Mistral.

The implementation covers planned power operations through Mistral and
emergency fencing and evacuation through Masakari. Ironic remains a
power-only registry and backend for the existing Nova compute hosts.

## Source Baselines and Deliverables

- Kolla-Ansible starts from
  `kolla-ansible-enroll-ironic-patch-3.zip`, SHA-256
  `df27628ce641fefee30114ebeb3651490655aacb0930ad5bc30a298c88c3e08d`.
- Masakari starts from the vanilla `stable/2025.1` branch.
- Mistral starts from the vanilla `stable/2025.1` branch.
- Each source tree has its own numbered Git commits and `git format-patch`
  output.
- `docs/powerops/POWEROPS-ARCHITECTURE.md` is the Russian operator-facing
  description of component interaction, workflows, failure states,
  configuration and verification.

The Kolla baseline first receives a hygiene commit that removes rejected and
backup artifacts from the deliverable and restores secret-safe Ansible
logging. This commit does not change the existing power-only enrollment
contract.

## Safety Invariants

1. `Nova hostname`, `Masakari host.name` and `Ironic Node.name` are exactly
   equal after canonical validation. Aliases and fuzzy matches are rejected.
2. One and only one Ironic Node must match a compute host.
3. Ironic Nodes remain in `manageable` state with `network_interface=noop`.
   PowerOps never provisions, cleans, inspects or moves them to `available`.
4. Emergency evacuation cannot begin until physical `power off` has been
   observed repeatedly and no conflicting target power state or `last_error`
   exists.
5. Failure to resolve a host, acquire required coordination, contact Ironic,
   or prove a stable power state is fail-closed.
6. TaskFlow revert logic never powers on a fenced host.
7. Planned-operation failure leaves the Nova compute service disabled and the
   Masakari host in maintenance.
8. Deployment and reconfiguration register code and workflows but never issue
   an Ironic power command, Nova migration, Nova evacuation or VM state change.
9. Secrets are not logged and are not embedded in generated patches or
   documentation.
10. Every PowerOps action rejects callers whose authenticated Mistral project
    name or user name is absent from the configured exact-match allowlists.
    Empty allowlists deny all action execution.

## Component Responsibilities

### Kolla-Ansible

Kolla-Ansible deploys patched Masakari and Mistral images, renders their
PowerOps configuration, validates prerequisites and reconciles the Mistral
action catalogue and workbook.

Deployment uses explicit image repository and tag variables for the patched
Masakari Engine and Mistral API, Engine and Executor images. Image building and
registry publication remain separate, operator-controlled steps.

The deploy/reconfigure path is idempotent:

1. validate that Ironic, Masakari, Mistral and the selected etcd coordination
   endpoint are configured;
2. render Masakari and Mistral PowerOps options;
3. start or reconfigure service containers using patched images;
4. verify the expected Python entry points inside the relevant containers;
5. run `mistral-db-manage populate` to reconcile custom actions;
6. on the Ansible controller, follow and `stat` a non-empty
   `kolla_admin_openrc_cacert`, requiring a readable regular file;
7. obtain the token project ID and list exact `power_ops`/empty-namespace
   workbook matches without a bounded page limit;
8. reject ambiguous matches and any public workbook owned by another project,
   then create an absent row or update one changed owned row;
9. verify every action by direct exact GET and every workflow by an exact
   name/default-namespace filtered GET, including token-project ownership.

All delegated controller API calls use `kolla_admin_openrc_cacert`, after a
local followed-link `stat` proves that a non-empty path is a readable regular
file. This is deliberately separate from `openstack_cacert`, whose path is
consumed inside service containers. The role-local prechecks do not perform
this controller CA check: the built-in `stat` runs inside deploy/reconfigure
after handler flush and Mistral action population. The operator installation
procedure therefore requires an explicit read-only controller `test -f` and
`test -r` before approving that mutation gate.

Workbook reconciliation has two complementary ownership defenses. Kolla
filters `/workbooks?name=power_ops&namespace=` results and fails closed with
`Refusing to reconcile an ambiguous or foreign public power_ops workbook`
before POST/PUT. The companion Mistral patch
`0010-fix-scope-workbook-updates-to-request-project.patch` makes
`update_workbook()` select within the same session-aware transaction by
`models.Workbook.project_id == security.get_project_id()`, exact name and
normalized namespace. Kolla's pre-mutation owner assertion gives clear
operator diagnostics; Mistral's atomic owner lookup closes the TOCTOU window
and prevents a public same-name row from another project being overwritten.

No custom Horizon code is added. When the vanilla Mistral dashboard is
enabled, operators can discover and start the registered workflows there; the
same workflows remain callable through the Mistral API and CLI.

### Masakari

Masakari owns the emergency path. A custom TaskFlow task performs Ironic
fencing directly, without calling Mistral. The recovery chain is:

```text
disable_compute_service_task
  -> ironic_fence
  -> prepare_HA_enabled_instances_task
  -> evacuate_instances_task
```

The reserved-host flow retains the upstream reserved-host preparation and
retry semantics; fencing is inserted before its existing prepare/evacuate
sequence rather than moving those tasks between phases.

The fence task:

1. runs only while the enclosing host-failure flow owns the per-host PowerOps
   coordination lock;
2. resolves exactly one Ironic Node by the canonical host name;
3. rejects a non-empty `last_error` or a target state that conflicts with
   `power off`;
4. requests hard `power off` when the node is not already stably off;
5. waits for a configurable number of consecutive `power off` observations;
6. raises a fatal TaskFlow error when any invariant is not met.

The enclosing emergency recovery obtains the per-host lock before disabling
Nova and retains it until the TaskFlow has terminated after evacuation or
failure. This prevents a concurrent planned workflow from powering on the
source host while evacuation is still running. Normal completion releases the
lock explicitly; coordinator loss relies on the backend session or lease
cleanup.

The evacuation implementation sorts instance move records deterministically
and serializes the complete recovery of each VM across the cluster. For every
VM it acquires the global evacuation lock, calls Nova evacuation, waits for
the upstream confirmation condition, holds a configurable pacing interval,
then releases the lock. A VM that was not running before failure is not
forcibly started merely to satisfy serialization.

If a VM evacuation fails, Masakari records the failure using its existing
recovery semantics and does not start the next VM in that host workflow.

### Mistral

Mistral owns planned operations only. It provides OpenStack actions and the
`power_ops` workbook with these workflows:

- `power_ops.host_power_status`;
- `power_ops.planned_power_off`;
- `power_ops.planned_reboot`;
- `power_ops.power_on_and_return`.

Before reading or mutating infrastructure, every action checks the caller's
`ActionContext.security.project_name` and `user_name` against exact configured
allowlists. This check is implemented in action code because the actions use
service credentials internally and therefore must not rely only on workbook
visibility. Kolla defaults the allowlists to its administrative OpenStack
identity, and operators may replace them with dedicated PowerOps identities.

Each uninterrupted state transition invokes one composite PowerOps action.
The action starts one `tooz` coordinator session, obtains the per-host
PowerOps lock before changing Nova, Masakari, VM or Ironic state, retains the
lock through its entire internal state machine, then releases it and stops the
coordinator. This is required because consecutive Mistral workflow tasks can
run on different Executor processes and a `tooz` lock cannot be transferred
safely between coordinator sessions. A workflow may use a second composite
action only after the first action has reached a documented safe state and
released its lock. `evacuate` is not a valid planned instance policy.

The workbook remains the stable operator-facing API and exposes workflow
inputs, outputs and task status. Detailed uninterrupted transitions are
recorded in structured action logs and audit events rather than represented as
separate lock-owning workflow tasks.

Supported instance policies are:

- `require_empty`: fail unless the host contains no instances;
- `live_migrate`: live-migrate instances in deterministic sequence and wait
  for each migration before continuing;
- `stop`: stop instances in deterministic sequence and remember their UUIDs
  for controlled restart.

The composite `planned_power_off` action returns the stopped-instance UUID list
as workflow output. The later `power_on_and_return` workflow requires that
list as explicit input when those instances must be restarted. It does not
infer or start every SHUTOFF instance on the host.

The composite `planned_reboot` action retains the stopped-instance list inside
the same action execution and restarts only those instances, sequentially,
after the compute services are healthy. It uses controlled `power off`,
verified stable off, then `power on`; a single opaque reboot operation is not
used.

Graceful power-off is the default for planned operations. Escalation to hard
power-off requires an explicit workflow input and occurs only after the
graceful timeout.

`power_on_and_return` has two safe phases. `power_on_for_inspection` powers on
the host and waits for compute-service visibility while deliberately retaining
Nova disabled and Masakari maintenance. The workflow then pauses before
`return_to_service`. After checking the host, the operator resumes the
workflow; `return_to_service` obtains a new per-host lock and requires the
explicit assertion `stale_domains_checked=true` before enabling the scheduler.
Mistral does not use SSH or `virsh` to make that physical-host safety decision
on behalf of the operator.

Planned reboot does not require a stale-domain assertion because no evacuated
copy is created on another compute host. It still validates power and compute
service health before restarting workflow-stopped instances and enabling Nova.

## Coordination Through etcd

Both Masakari and Mistral use `tooz` with an etcd-backed coordination URL.
Neither project contains a direct etcd client implementation.

Two lock namespaces are mandatory:

- `powerops/host/<host>` serializes all mutating operations for one physical
  compute host;
- `powerops/evacuation/global` serializes VM recovery across all Masakari
  Engine processes and simultaneous host-failure notifications.

Coordinator heartbeats run for the lifetime of an operation. Lock acquisition
has a bounded timeout. Coordinator startup, heartbeat or lock-acquisition
failure prevents the protected state transition. Driver-specific lease and
session cleanup prevents a dead process from owning a lock forever.

The global lock covers Nova's evacuation request, its completion check and the
configured pacing delay. Consequently two engines cannot overlap VM recovery,
even when different compute hosts fail at the same time.

## Planned Composite Action State Transitions

### Planned Power Off

```text
acquire host lock
  -> Masakari maintenance=true
  -> Nova service disable
  -> apply instance policy
  -> assert host safe for power-off
  -> Ironic graceful power-off
  -> optional explicit hard-off escalation after timeout
  -> prove stable power off
  -> audit
  -> release lock
```

Success leaves Nova disabled and Masakari maintenance enabled.

### Planned Reboot

```text
acquire host lock
  -> Masakari maintenance=true
  -> Nova service disable
  -> apply instance policy
  -> power off and prove stable off
  -> power on and prove stable on
  -> wait for OS-facing Nova service health
  -> restart only workflow-stopped VMs sequentially
  -> Nova service enable
  -> Masakari maintenance=false
  -> audit
  -> release lock
```

### Power On and Return

```text
acquire host lock for power_on_for_inspection
  -> Ironic power on
  -> prove stable on
  -> wait for Nova compute health
  -> retain Nova disabled and Masakari maintenance
  -> release lock
  -> pause workflow for operator inspection
  -> operator verifies stale domains and resumes workflow
  -> acquire host lock for return_to_service
  -> require stale_domains_checked=true
  -> restart explicitly supplied VM UUIDs sequentially
  -> Nova service enable
  -> Masakari maintenance=false
  -> audit
  -> release lock
```

## Failure Handling

- Errors before Nova disable leave the original scheduler state unchanged.
- Errors after Nova disable call a fail-safe action that reasserts Nova
  disabled and Masakari maintenance enabled.
- A lock is released only by the execution that owns it.
- Failure to write a success audit record is treated as workflow failure and
  retains the fail-safe host state.
- A coordinator release or stop error that occurs only after the final health
  proof and durable success audit is a terminal cleanup warning, not a failed
  power transition. The action records a separate
  `completed_with_coordination_cleanup_error` audit and returns its completed
  result so a retry cannot repeat an already completed power cycle. It never
  attempts fail-safe mutations after ownership is no longer proven.
- Conflicting Ironic `target_power_state`, a non-empty `last_error`, timeout,
  duplicate node match or unknown power state is a hard failure.
- Emergency fencing failures stop TaskFlow before instance preparation and
  evacuation.
- Emergency evacuation failures do not power on the source host.

## Configuration Contract

Kolla-Ansible exposes PowerOps variables for:

- enabling PowerOps integration;
- the `tooz` etcd coordination URL and TLS material paths;
- host-lock and global-lock acquisition timeouts;
- Ironic power timeout, polling interval and stable observation count;
- evacuation pacing interval;
- planned graceful-shutdown timeout and explicit hard-off policy;
- exact allowed Mistral caller project and user names;
- patched image repository and tag values;
- workbook reconciliation and validation toggles.

Secret-bearing values use Kolla passwords or protected configuration files and
are marked `no_log`. Defaults never contain deployment addresses, passwords or
certificates.

## Testing and Verification

### Masakari

Unit tests prove exact-node resolution, fencing order, conflicting-target
rejection, stable-off observation, fail-closed coordination, deterministic VM
ordering, cluster-wide lock coverage, pacing and no automatic power-on during
revert.

### Mistral

Unit tests prove action registration, host resolution, policy validation,
single-session lock ownership across every composite action, safe failure
state, graceful-to-hard escalation rules, explicit restart manifests and
sequential VM restart. Workbook contract tests prove that lock ownership is
never transferred between tasks and that the two return actions are separated
by an operator pause while Nova remains disabled and Masakari remains in
maintenance.

### Kolla-Ansible

Contract and Ansible tests prove baseline hygiene, secret-safe logging,
configuration rendering, correct image placement, entry-point verification,
action population, fail-closed workbook collision/owner handling, idempotent
owned workbook create/update and absence of power actions during
deploy/reconfigure. Controller API TLS is checked through
`kolla_admin_openrc_cacert`; action catalogue checks use `/actions/{{ item }}`
and workflow checks use `/workflows?name={{ item }}&namespace=` with exact
token-project assertions.

### Cross-Repository

Contract tests compare the configured TaskFlow names, Mistral entry-point
names, workbook action references and Kolla validation expectations. Every
generated patch series is checked by applying it to a clean copy of its
declared baseline and running the relevant test suite.

Static and unit verification is reported separately from live proof. Container
build, image push, cloud deployment, BMC commands and real evacuation require
separate operator authorization and are not implied by passing local tests.

## Documentation

`docs/powerops/POWEROPS-ARCHITECTURE.md` is written in Russian and contains:

- component roles and interaction diagrams in text;
- planned power-off, planned reboot, power-on/return and emergency fencing
  scenarios;
- etcd lock names, scope and failure behavior;
- VM policy and sequential-recovery rules;
- deploy/reconfigure behavior;
- safe operator checks and recovery states;
- explicit static-versus-live verification boundaries.

## Non-Goals

- automatic power-on or repair of an emergency-fenced host;
- planned evacuation as a Mistral policy;
- Ironic provisioning, cleaning, inspection or PXE services;
- a new custom Horizon plugin;
- automatic SSH or libvirt stale-domain inspection;
- image publication, live deployment or physical BMC testing without separate
  authorization.

## Acceptance Criteria

The implementation is accepted when all three patch series apply cleanly to
their declared baselines, all repository and cross-contract tests pass, the
Russian architecture document matches the implemented behavior, and no live
infrastructure action has been performed implicitly.
