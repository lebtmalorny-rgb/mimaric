# OpenStack PowerOps patch delivery

This repository delivers 25 ordered Git patches plus source-level tests and
operator documentation for OpenStack Epoxy 2025.1. Detailed installation is
in [`INSTALL.md`](INSTALL.md). The Russian component/scenario runbook is
`docs/powerops/POWEROPS-ARCHITECTURE.md` after applying the Kolla-Ansible
series; its source is delivered by
[Kolla patch 0005](patches/kolla-ansible/0005-docs-add-Russian-PowerOps-operations-guide.patch).

## Baselines

| Series | Exact baseline | Verified source HEAD | Commits |
|---|---|---|---:|
| Masakari | `0fd34dd6a6d90525dbf806f35577c5ee1d7e9444` (`stable/2025.1`) | `9f3cb144958b8e60bba72adefb22edf51387c0ca` | 10 |
| Mistral | `3b2eab29e9dc71a5ba250d989155eb69a9bd8e48` (`stable/2025.1`) | `3e4fe82455de7473809b0e0bc677fa3df3a3d1e2` | 10 |
| Kolla-Ansible | `kolla-ansible-enroll-ironic-patch-3.zip`, SHA-256 `df27628ce641fefee30114ebeb3651490655aacb0930ad5bc30a298c88c3e08d`; internal force-tracked import `703b06c9fa5771c758f703b424d63fb04192567a` | `63a8d0f597f9034a42f2e1b0bd415f1746d33b8d` | 5 |

Clean `git am` reproduced the Masakari source tree
`83bb2fd7a2d8c2f8d97e26c12fb66e8e06436bc5`, the Mistral source tree
`8e3009eb1abf8033608d31d7e60cdb02ab8da1ed`, and the Kolla-Ansible source
tree `287bac4223f24393c32fbfd55c140601c8611a21`. Commit IDs created by
`git am` may differ because committer metadata changes; tree equality is the
content proof.

## Patch order

Apply the complete series in project order Masakari → Mistral → Kolla-Ansible.
Within each project, apply files exactly as listed.

Masakari:

1. `patches/masakari/0001-feat-add-PowerOps-coordination-primitives.patch`
2. `patches/masakari/0002-feat-fence-failed-hosts-through-Ironic.patch`
3. `patches/masakari/0003-fix-enforce-Ironic-fencing-deadlines.patch`
4. `patches/masakari/0004-fix-honor-service-TLS-for-Ironic.patch`
5. `patches/masakari/0005-feat-lock-complete-Masakari-host-recovery.patch`
6. `patches/masakari/0006-test-harden-Masakari-host-lock-coverage.patch`
7. `patches/masakari/0007-feat-serialize-Masakari-evacuations-through-etcd.patch`
8. `patches/masakari/0008-docs-describe-Masakari-PowerOps-fencing.patch`
9. `patches/masakari/0009-fix-satisfy-PowerOps-package-lint.patch`
10. `patches/masakari/0010-fix-fail-closed-on-PowerOps-coordination-loss.patch`

Mistral:

1. `patches/mistral/0001-feat-add-PowerOps-action-coordination.patch`
2. `patches/mistral/0002-fix-declare-PowerOps-etcd-backend.patch`
3. `patches/mistral/0003-feat-add-PowerOps-OpenStack-primitives.patch`
4. `patches/mistral/0004-fix-align-PowerOps-with-SDK-resources.patch`
5. `patches/mistral/0005-feat-add-planned-PowerOps-actions.patch`
6. `patches/mistral/0006-fix-harden-planned-action-boundaries.patch`
7. `patches/mistral/0007-feat-add-guarded-host-return-actions.patch`
8. `patches/mistral/0008-feat-register-the-PowerOps-workbook-API.patch`
9. `patches/mistral/0009-test-generalize-action-plugin-coverage.patch`
10. `patches/mistral/0010-fix-scope-workbook-updates-to-request-project.patch`

Kolla-Ansible:

1. `patches/kolla-ansible/0001-fix-sanitize-Ironic-enrollment-baseline.patch`
2. `patches/kolla-ansible/0002-feat-define-Kolla-PowerOps-deployment-contract.patch`
3. `patches/kolla-ansible/0003-feat-render-etcd-backed-PowerOps-configuration.patch`
4. `patches/kolla-ansible/0004-feat-reconcile-PowerOps-actions-and-workbook.patch`
5. `patches/kolla-ansible/0005-docs-add-Russian-PowerOps-operations-guide.patch`

Dependency boundary: Kolla-Ansible patch 0004 requires Mistral patch 0010.
The latter scopes the `Workbook` plus child `ActionDefinition` and
`WorkflowDefinition` lookup/update to exact project, name and normalized
namespace, passes `project_id=wb_db.project_id`, and performs all writes in
one SQLAlchemy transaction. Kolla additionally rejects ambiguous or foreign
public `power_ops` workbook matches before mutation and requires each
validated workflow to be an exact token-project-owned match.

## Implemented scenarios

- point-in-time physical and OpenStack host status;
- planned power-off using `require_empty`, deterministic `live_migrate` or
  deterministic `stop` (planned evacuation is forbidden);
- controlled planned off → proven stable-off → on reboot;
- two-phase power-on/return with a real operator pause,
  `stale_domains_checked=true` and sequential restart of only the explicit VM
  manifest;
- emergency Masakari fencing through exact Ironic node resolution before any
  instance preparation/evacuation;
- cluster-wide one-VM-at-a-time evacuation with completion confirmation and
  pacing under `powerops/evacuation/global`;
- shared per-host lock `powerops/host/<host>` across planned Mistral and
  emergency Masakari paths;
- etcd-backed tooz coordination with fail-closed ownership checks. Redis is
  not used by the enabled PowerOps path.

## Test commands and results

The following are the recorded local results from the final source trees and
fresh-apply verification:

- Masakari full unit suite: **895 passed, 3 skipped**, 0 failed (898 run).
- Masakari final PowerOps-focused selection: **85 passed**, 0 failed; full
  flake8 passed.
- Historic pre-expanded Mistral evidence, before the final child-ownership
  hardening: **1620 passed, 8 skipped**, 0 failed (1628 run). This is retained
  as historical evidence only, not as a final full-suite claim.
- Final expanded Mistral affected combined run: **332/332**. Additional
  selection evidence (some selections overlap) is: new owner-scope security
  regressions **6/6**, affected workbook boundary **120/120**,
  **PowerOps 106/106**, and **broader 106/106** action/workflow coverage;
  final flake8 and diff hygiene passed.
- The final Mistral full serial attempt **stopped after 829** tests following
  known sandbox WSGI socket `PermissionError` failures. It did not complete,
  so this delivery makes no final full-suite pass claim.
- Kolla-Ansible PowerOps plus Ironic enrollment suites: **64/64**; Ansible
  syntax and diff hygiene passed.
- Cross-repository source contract suite: **19/19**; artifact repository
  discovery: **29/29** (10 delivery plus 19 cross-repository); flake8,
  compileall and diff hygiene passed.

Representative verification commands:

```bash
python3 -m unittest tests.test_delivery_artifacts -v
POWEROPS_MASAKARI_TREE="$PWD/worktrees/masakari-powerops" \
POWEROPS_MISTRAL_TREE="$PWD/worktrees/mistral-powerops" \
POWEROPS_KOLLA_TREE="$PWD/work/kolla-ansible" \
  python3 -m unittest tests.test_cross_repository_contract -v
POWEROPS_MASAKARI_TREE="$PWD/worktrees/masakari-powerops" \
POWEROPS_MISTRAL_TREE="$PWD/worktrees/mistral-powerops" \
POWEROPS_KOLLA_TREE="$PWD/work/kolla-ansible" \
  python3 -m unittest discover -s tests -v
shasum -a 256 -c SHA256SUMS
git diff --check
```

The Mistral workbook bytes are identical in Mistral and Kolla-Ansible and have
SHA-256
`26c9f2a072827b5c342dcc1d51aacf5995110054a400efe3d68df0563f3e7921`.

PowerOps action audit output is a `structured LOG.info process log` only.
There is `no external durable audit store` in this patch set and there is
`no delivery or persistence guarantee`; durable collection and retention are
an operator logging-platform responsibility and were not verified here.

## Static verification boundary

The evidence proves patch checksums, exact source baselines, clean mailbox
application, final tree equality, unit/source contracts, syntax and lint in
the recorded local environments. It also proves that deploy/reconfigure source
contains only registration/reconciliation/validation operations and no
workflow execution or Nova/Ironic power mutation.

This bundle contains source patches and documentation: no images were built or
pushed, and the bundle does not define an image-build command or replace the
operator's existing image pipeline. Also, no deployment or reconfiguration was
run. No external API or production state was changed while producing it.

## Live verification still required

Runtime acceptance still must validate the four built images, actual Kolla
prechecks/deploy or reconfigure, controller-to-Keystone/Mistral TLS,
project-scoped workbook collision handling, Mistral action population, etcd
session/lease/heartbeat behavior, exact Nova/Masakari/Ironic name mapping,
Redfish/BMC stable power observations, live migration, emergency evacuation,
VM pacing and the return operator gate.

No physical power command, Masakari notification, workflow execution, Nova
migration/evacuation, VM stop/start or host return was performed. Those are
separately authorised operator changes, not implied by local PASS results.

## Safe apply and rollback notes

Verify `SHA256SUMS`, use a clean integration branch per repository, apply each
complete series with `git am`, and use `git am --abort` on any conflict. Do not
resolve a baseline mismatch by editing a published patch. Detailed commands,
globals example, image acceptance requirements and gates are in
[`INSTALL.md`](INSTALL.md).

Kolla prechecks do not prove `kolla_admin_openrc_cacert` readability. Before
approving deploy/reconfigure, perform the documented control-node `test -f`
and `test -r`. Kolla repeats followed-link regular/readable validation only
inside deploy/reconfigure, after handler flush and Mistral action population
but before Keystone/Mistral reconciliation.

Before live rollout, retain known-good branches, immutable image tags and the
previous Kolla configuration. Runtime rollback is a separately approved
reconfigure after active workflows/notifications are drained and actual host
state is recorded. Disabling PowerOps does not automatically delete the public
workbook or reverse an already completed physical/Nova operation; workbook
mutation and host return remain separate controlled operations.
