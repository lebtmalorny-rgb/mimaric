# Horizon PowerOps Integration Design

## Purpose

Add a dedicated Horizon interface for the existing OpenStack PowerOps patch
set. The interface lets an administrator or an explicitly delegated PowerOps
operator inspect compute hosts and start the existing planned power workflows
without granting Horizon direct mutation access to Nova, Masakari or Ironic.

This document extends
`2026-08-31-openstack-powerops-design.md`. It deliberately supersedes only
these decisions from that document:

- a custom Horizon plugin is now in scope;
- PowerOps authorization is no longer based only on caller project and user
  allowlists.

All existing host-resolution, fencing, coordination, VM sequencing,
fail-safe, secret-handling and no-implicit-live-action invariants remain in
force.

## Deployment Model

One OpenStack installation serves one OpenStack region. Horizon may retain its
standard region selector, but this deployment exposes one region in that
selector. The selected region is displayed by the PowerOps panel; it is not a
caller-controlled workflow input.

Mistral, Nova, Masakari and Ironic clients continue to use the server-side
`openstack_region_name`. This design does not add multi-region routing,
cross-region locks or cross-region HA.

Power operations are host-wide infrastructure operations. A caller's current
project is an authorization attribute and a Mistral execution-ownership
boundary; it does not limit the VMs affected on the selected compute host.
Inventory, stop, restart and migration checks cover instances from all
projects.

## Authorization Contract

### Roles and allowlists

The effective server-side authorization rule is:

```text
role:admin
OR
(
  role:powerops_operator
  AND project_name in powerops_allowed_project_names
  AND user_name in powerops_allowed_user_names
)
```

The exact role names are `admin` and `powerops_operator`. Role comparisons and
project/user allowlist comparisons are exact. The `admin` branch bypasses both
allowlists. The delegated `powerops_operator` branch requires both allowlist
matches. A user with neither role is denied.

`powerops_operator` is a human authorization role, not a service dependency of
Mistral. Mistral continues to call Nova, Masakari and Ironic with its configured
service credentials. When PowerOps is enabled, Kolla idempotently ensures that
the exact Keystone role exists. It does not assign the role or create an
implied-role relation; role assignments remain an operator-controlled Keystone
change.

Empty operator allowlists deny the delegated branch while leaving the `admin`
branch operational. Kolla defaults populate both lists from the configured
administrative OpenStack identity. Kolla prechecks validate
that both values are lists containing unique, non-empty, trimmed strings; an
empty list itself is valid.

### Trusted role propagation

The current Mistral `ActionContext.security` does not carry roles. The
implementation extends `mistral-lib`'s security context and Mistral's action
context construction so that roles received from the already validated
Keystone request context are persisted as trusted execution security data and
made available to actions.

Workflow inputs, workflow environment values, HTTP form fields and Horizon
session data cannot supply or override these trusted roles. Unknown
authorization-related workflow inputs are rejected. PowerOps actions enforce
the authorization contract before inventory reads or infrastructure
mutations, so a caller cannot bypass the rule by using the CLI, calling the
Mistral API directly or wrapping a `powerops.*` action in another workflow.

PowerOps workflow start requests also receive an early API-side role check so
ordinary unauthorized calls fail synchronously. Action-side enforcement
remains authoritative because an API name check alone cannot protect indirect
action invocation.

### Resume authorization

The `power_ops.power_on_and_return` workflow has an operator pause. A request
that resumes a PowerOps execution is checked against the same current-token
authorization rule in addition to normal Mistral execution policy. This
prevents a user from relying only on authorization captured when the workflow
was first started.

When resume is accepted, Mistral atomically records a server-generated trusted
resume authorization record containing the current actor IDs, authorization
branch and timestamp. Caller input and workflow environment cannot create or
replace this record. `return_to_service` requires the record and uses it for
audit correlation, so the second phase is attributable to the current resume
caller rather than only to the workflow starter.

The existing `stale_domains_checked=true` Boolean gate remains mandatory and
is independent of RBAC. An authorized caller who has not supplied the exact
Boolean assertion is denied. The stopped-instance manifest is taken from the
source planned-power-off result and is not editable in the Horizon resume
form.

### Hard-off authorization

`allow_hard_off` defaults to JSON Boolean `false`. Only the `admin` branch may
submit `allow_hard_off=true`, and Horizon requires a separate explicit
confirmation. A delegated `powerops_operator` may use the planned workflows
but cannot authorize hard-off escalation.

## Architecture

```text
Browser
  -> Horizon powerops-dashboard
       -> current Keystone token and selected service-catalog region
       -> Mistral API
            -> trusted request roles
            -> PowerOps API and action authorization
            -> power_ops workflow
            -> PowerOps composite action
                 -> Mistral service credentials
                 -> Nova + Masakari + Ironic
                 -> shared etcd powerops/host/<host> lock
```

### `powerops-dashboard`

`powerops-dashboard` is a separate Horizon plugin rather than a fork of the
vanilla Mistral dashboard. It provides a top-level
`PowerOps -> Compute Hosts` dashboard with typed forms, execution monitoring
and operator-facing diagnostics. It is not nested under Horizon's standard
`Admin` dashboard: that would prevent a delegated non-admin
`powerops_operator` from reaching the panel or would require broadening access
to unrelated administrative panels.

The plugin has no Nova, Masakari, Ironic or BMC mutation client. It forwards
the current user token to the regional Mistral endpoint obtained through
Horizon's normal service-catalog handling. It never stores service-account
credentials.

The plugin mirrors the server authorization rule only to control panel and
button visibility. Direct URL access performs the same UI-side check and
returns HTTP 403. A UI-side success is never treated as authorization proof;
Mistral is authoritative.

Kolla renders the same operator allowlists into Mistral and Horizon settings
from the same source variables to avoid presentation drift. A mismatch can at
most hide or show an unusable control because the server check remains final.

### Read-only host inventory

The existing workflow set has point-in-time host status but no safe discovery
source for a delegated operator. Add a read-only PowerOps inventory action and
workflow that use Mistral service credentials after the normal PowerOps
authorization check.

The inventory returns, for each canonical Masakari host:

- server-configured region name;
- Masakari segment UUID and host name;
- exact matching Nova compute service administrative and process state;
- exact matching compatible Ironic Node UUID and power fields;
- Masakari maintenance state;
- total instance count and affected instance identity/project/status data
  required for the confirmation view;
- an `operable` decision and a sanitized blocking reason.

A global failure to list a required service dataset fails the whole inventory
closed. A malformed or ambiguous individual host is returned as non-operable
so that other valid rows remain inspectable, but no mutation control is shown
for the blocked row. The action does not expose credentials, tokens, BMC
addresses or driver secrets.

Inventory is only a display snapshot. Every mutating composite action repeats
exact Nova/Ironic/Masakari resolution, instance discovery, authorization and
coordination after acquiring the authoritative host lock.

### Existing workflow boundary

The plugin starts these existing mutation workflows without reimplementing
their state machines:

- `power_ops.planned_power_off`;
- `power_ops.planned_reboot`;
- `power_ops.power_on_and_return`.

`power_ops.host_power_status` remains the authoritative point-in-time status
refresh for one selected host. The new inventory workflow is discovery and
preflight support, not an alternative mutation path.

### Kolla integration

Kolla integration:

- builds or installs the separate `powerops-dashboard` Python package in the
  Horizon image for OpenStack 2025.1;
- enables its Horizon plugin files only when Horizon, Mistral and PowerOps are
  enabled;
- continues to enable the standard Mistral dashboard independently;
- provides the one `openstack_region_name` and the two operator allowlists;
- idempotently ensures that the `powerops_operator` Keystone role exists but
  never assigns it automatically;
- installs compatible patched `mistral-lib` content in Mistral images;
- populates the added inventory action and reconciles the extended public
  `power_ops` workbook;
- validates role-context support, plugin import, action registration and exact
  workflow ownership without issuing a power or VM mutation.

Deploy and reconfigure remain registration/configuration operations. Building
an image or enabling the plugin does not authorize a live deployment, service
restart or infrastructure mutation.

## Horizon User Flow

### Host list

The main table displays:

- the single current region;
- Nova host and Masakari segment;
- Ironic `power_state`, `target_power_state` and `last_error`;
- Nova `enabled`/`disabled` and `up`/`down`;
- Masakari `on_maintenance`;
- VM count across all projects;
- visible active PowerOps execution, when one is discoverable.

The table clearly states that a physical-host action affects eligible VMs from
all projects. Detection of an active Mistral execution in Horizon is an
operator convenience and may be limited to executions visible to the current
token. The shared etcd host lock is the authoritative cross-project and
cross-process concurrency control.

### Planned power off and reboot

For a selected operable host, the confirmation flow:

1. refreshes read-only host status and all-project instance impact;
2. lets the caller select `require_empty`, `live_migrate` or `stop`, defaulting
   to `require_empty`;
3. displays affected VM UUID, project and current status information;
4. requires the caller to type the exact canonical host name;
5. exposes hard-off escalation only to `admin` and requires a separate
   confirmation;
6. submits typed JSON inputs once and immediately records the returned Mistral
   workflow execution UUID;
7. polls the execution and correlated host status without automatically
   resubmitting the mutation.

Client-side button disabling and a per-session submission guard reduce
accidental duplicate clicks. They are not substitutes for the Mistral/etcd
host lock.

### Two-phase return

An eligible successful planned-power-off execution exposes `Power on for
inspection`. Horizon obtains the stopped-instance manifest from that execution
output and starts `power_ops.power_on_and_return` without a caller-editable
manifest field.

After phase one, the page must show all of these states before offering resume:

- workflow execution `PAUSED` at `operator_inspection_gate`;
- physical power stably on;
- Nova compute process visible but administratively disabled;
- Masakari maintenance still true;
- no manifest restart has begun.

The resume form presents the operational inspection checklist and sends
`stale_domains_checked` as JSON Boolean `true` only after explicit
confirmation. Mistral reauthorizes the current resume caller and the second
composite action revalidates the host before starting only the recorded
manifest, enabling Nova and finally clearing Masakari maintenance.

## HA Interaction

Planned PowerOps and emergency Masakari recovery remain separate paths that
share `powerops/host/<host>` coordination.

Planned operations first set Masakari maintenance, then disable Nova, apply the
selected all-project instance policy and only then change Ironic power. An
error after Nova disable reasserts the safe state `Nova disabled` plus
`Masakari maintenance=true`.

An unplanned host failure is handled by the existing Masakari path: Nova
disable, Ironic fencing, stable-off proof and serialized evacuation. Horizon
does not start, replace or resume that emergency flow. It may show correlated
read-only state, but Masakari notification and VMove data remain the emergency
HA authority.

## Error Handling

The UI fails closed when authorization, region endpoint discovery, complete
inventory, exact host mapping, power-state validation or Mistral availability
cannot be established. A mutating button is not rendered for a non-operable
host.

Synchronous Horizon responses distinguish:

- `403` for UI authorization failure;
- `409` for a duplicate operation already known to the UI;
- `422` for invalid typed input or a failed read-only preflight;
- `503` for an unavailable required service endpoint.

Mistral workflow creation is asynchronous. Once an execution UUID exists,
backend lock conflicts, timeouts and action validation failures are reported
through the execution state and error details; Horizon must not pretend that
all such failures are synchronous HTTP status codes.

Neither HTTP timeout nor execution `ERROR` proves that no mutation happened.
Horizon never automatically retries a power, VM or resume request. It switches
to a `verification required` presentation, refreshes read-only facts and links
the execution UUID. Operators follow the runbook before deciding whether any
new mutation is safe.

If a mutating action fails after disabling Nova, the existing fail-safe retains
Nova disabled and Masakari maintenance. Horizon does not automatically enable
Nova, clear maintenance, restart VMs or power on the host.

Error messages exposed to the browser are sanitized. Tracebacks, tokens,
passwords, BMC connection data and service configuration are not returned.

## Audit

Extend PowerOps process audit records with:

- request user and project IDs;
- authorization outcome and the selected `admin` or delegated-operator
  branch;
- configured region, host and Masakari segment UUID;
- operation, instance policy and whether hard-off escalation was authorized;
- workflow and action execution UUIDs;
- outcome and fail-safe error types.

Tokens, passwords and secret configuration are never logged. The existing
`LOG.info` process audit remains non-durable unless an external logging system
collects and retains it. Horizon is a presentation layer; Mistral execution
data plus a consistent Nova/Masakari/Ironic observation are the operational
evidence.

## Testing

### Horizon unit and functional tests

Tests cover:

- panel visibility for `admin` and an allowlisted `powerops_operator`;
- direct URL HTTP 403 for unauthorized users;
- administrator allowlist bypass;
- operator failure on either allowlist mismatch;
- typed Boolean, UUID-list and instance-policy serialization;
- exact host-name confirmation;
- admin-only hard-off controls;
- manifest immutability in the return flow;
- duplicate-submit prevention and no implicit retry;
- sanitization of backend failures.

### Mistral and `mistral-lib` tests

Tests prove:

- roles originate from validated request context and survive the required
  execution/action context serialization;
- workflow input or environment cannot forge roles;
- `admin` bypasses both allowlists;
- `powerops_operator` requires both exact allowlist matches;
- other roles are denied before infrastructure access;
- direct action and nested-workflow invocation receive the same enforcement;
- PowerOps resume rechecks the current request role;
- hard-off is admin-only;
- inventory is read-only, secret-safe and fail-closed on incomplete global
  data;
- existing strict Boolean, stopped-manifest, coordination and fail-safe
  contracts remain unchanged.

### Kolla and cross-repository tests

Tests cover plugin packaging and enable conditions, compatible Mistral library
installation, shared settings rendering, prechecks, action/workbook
reconciliation and the absence of power/VM mutations during deploy or
reconfigure. Cross-repository contracts compare Horizon workflow names and
input schemas with the Mistral workbook and compare Kolla configuration with
both consumers.

### Local visual build

The first runnable artifact is a local Horizon 2025.1 build with realistic
mock inventory and execution fixtures. All PowerOps mutation POST paths are
disabled in this mode. The build is used to review navigation, one-region
presentation, RBAC states, confirmations, paused return flow, error states and
responsive layout.

### Runtime acceptance boundary

Connecting a real test OpenStack is a separate, explicitly approved stage. It
starts with read-only service-catalog, inventory, role and point-in-time status
checks. A real workflow start, VM change, Ironic power command, Masakari state
change, Kolla deployment or service restart requires a separate mutation
approval.

Passing local, static, unit, packaging or image-build checks is not evidence
that the integration works with real Nova, Masakari, Ironic, etcd or BMC.

## Operations Guide

Create a separate Russian operator document at
`POWEROPS_HORIZON_OPERATIONS.md`. It covers:

- the single-region installation and Horizon's one-item region selector;
- the exact RBAC matrix and the difference between human roles and Mistral
  service credentials;
- creation/assignment verification for `powerops_operator` without automatic
  assignment;
- the host-wide, all-project blast radius;
- read-only inventory and preflight interpretation;
- planned off, reboot and two-phase return procedures;
- admin-only hard-off handling;
- interaction with Masakari maintenance and emergency HA;
- execution monitoring, audit correlation and fail-safe states;
- troubleshooting and mandatory no-automatic-retry behavior;
- local/static versus real runtime acceptance boundaries.

The guide references the existing general `OPERATIONS.md` for CLI evidence
collection and emergency HA diagnostics instead of duplicating those sections.

## Non-Goals

- multi-region routing or cross-region HA/DR;
- direct Horizon mutation calls to Nova, Masakari, Ironic or BMC;
- replacement of the existing composite PowerOps state machines;
- automatic Keystone role assignment or admin-to-operator role implication;
- automatic retry, rollback, power-on, maintenance clearing or Nova enable
  after an uncertain result;
- automatic SSH/libvirt stale-domain inspection;
- changes to the emergency Masakari recovery workflow beyond compatibility
  and contract tests;
- live deployment or physical power testing without separate approval.

## Acceptance Criteria

The design is implemented when:

1. the separate Horizon plugin builds and loads against Horizon 2025.1;
2. the trusted Mistral action context carries validated roles and the
   server-side authorization matrix passes direct, nested and resume tests;
3. inventory and all mutation workflows preserve the existing exact-host,
   all-project, lock and fail-safe invariants;
4. `admin` operates without allowlist membership, delegated
   `powerops_operator` requires both allowlists, and only `admin` may enable
   hard-off escalation;
5. Kolla packages and configures the plugin and compatible Mistral components
   without issuing live mutations;
6. the local mock Horizon build is reviewable with mutation POST paths
   disabled;
7. `POWEROPS_HORIZON_OPERATIONS.md` matches the implemented UI and backend
   behavior;
8. static/local evidence and real runtime evidence are reported separately.
