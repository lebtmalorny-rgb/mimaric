# PowerOps two-scenario implementation plan

Goal: Python 3.11 acceptance runner for real emergency evacuation and planned live-migrate/power-off/power-on/return. Host/interface and inventory/globals are inputs; no live operations during development.

The user explicitly authorized automatic operator confirmation. The runner must
observe the actual PAUSED gate, inspect the source through Ansible, and resume
the same execution with Boolean stale_domains_checked=true. Failed inspection
prevents resume. Both scenarios finish by checking the returned source and all
test VMs on destination hosts; returning the source does not reverse-migrate VMs.

Scope: existing explicitly listed ACTIVE test VMs only; one selected scenario
and one runner at a time. No automatic creation/deletion of VMs, deploy or service
configuration. Existing link_fault/remote_fault become the fault injection adapter.

Files and implementation steps:

- [x] `scenario_runner.py`: durable state machine and explicit assertions. Tests
  cover successful scenarios, per-VM failures, stale notification, missing fencing
  evidence, non-empty source inspection, true Boolean resume, and lost responses.
- [x] `openstack_probe.py`: SDK-authenticated REST JSON reads, full pagination,
  fresh workflow/notification binding, correct VMove and migration fields.
- [x] `ansible_target.py`: inventory + globals via Ansible, protected/no_log
  execution, target inspection and the existing fault worker. No secret dumping.
- [x] `stand_test.py`: JSON task config, plan/preflight/run/status/report, persistent journal,
  stable run ID, bounded polling and JSON result report.
- [x] Extend `remote_fault.py` with read-and-reconcile after reboot: no network
  changes, require same interface MAC/name and current UP before closing old fault.
- [x] Deliver two task examples and Russian instructions. Run Python 3.11 local
  scenario/adapter tests, actual Ansible fixtures and SDK session checks, repository checks
  and independent review. Report live verification as not performed.

Mutation intents are persisted before requests. A lost workflow create response
is reconciled by its preassigned UUID plus exact description/name/input; it is never blindly retried.
A lost resume response is observed on the same execution and never replayed.
Fault requests use the existing remote run ID journal. Failures preserve state
for diagnosis; no unconditional power-on or service enable in cleanup.

Emergency order evidence is taken from timestamped IronicFenceTask progress and
VMove.start_time in Masakari API 1.3. Missing evidence is INCOMPLETE, not PASS.
Planned validation uses the real workflow/action result plus new global Nova
live-migration records and fresh VM/node/service state. It does not infer physical
BMC timestamps from API polling.

Validation completed locally: 75/75 stand-runner/adapter tests with SDK 4.20.0
under Python 3.11.15, no skips; 7/7 repository tests; syntax, example plans,
documentation links and git diff --check passed. Two tests used real Ansible
against local fixture inventories; the SDK session test replaced HTTP transport.
No SSH, OpenStack API, systemd, NIC or power actions were performed on a stand.

Independent review found no remaining P1/P2 after fixes and re-review. Addressed
stale preflight after restart, workflow ERROR wire shape, pagination/HTTP retry
behavior, final network drift, notification binding, API/auth timeouts, local
source ownership, and old fault evidence under a lost response. Fault intents
now contain a durable nonce shared with the target; the post-fencing hold uses
monotonic time and repeats fully after restart before a new return intent.
