# Kolla implementation evidence

Base: supplied `kolla-ansible-pvs_1.0.0_14.09.zip` unpacked tree snapshot `54f4ee851cc2fc5db1068a8c5807f2b8e8e2c475`. Original supplied tree untouched. Work is in `password-policy-work/kolla-ansible`.

Implemented:

- Opt-in `keystone_service_password_policy_exempt: false` default.
- Service registration module staged in existing toolbox config mount; `kolla_toolbox.module_path` passes a module search directory as one argv argument. No shell interpolation or toolbox image replacement.
- `kolla_service_user` uses SDK 4.4.0 and `openstack.cloud` 2.4.1 common authentication/TLS interface. First create has password and all four flags in the same request. Existing updates preserve MFA/options; `on_create` reruns do not rotate passwords; `always` retains rotation semantics.
- Exact domain/name lookup; mismatched results/duplicate identities fail before writes. Domain-only Magnum trustee is covered, including preservation of its existing default project.
- Explicit `no_log: true` on service-password tasks regardless Kolla debug. No secrets in result; sanitized SDK error status.

Tests and evidence:

- Python 3.11.15; ansible-core 2.17.14; openstacksdk 4.4.0 (2025.1 constraints); openstack.cloud 2.4.1.
- Initial RED: 17 tests, 16 failures, 1 pass (new module absent, module-path unsupported, flag/no_log absent), `kolla-red.log`.
- Additional Magnum RED: 20 tests, 1 failure and 2 errors from unsupported project-less creation. `kolla-magnum-red.log`.
- Feature GREEN: 20/20. Tests use real SDK identity resources and HTTP request mocks to check serialized requests; SDK methods are not mocked.
- Targeted command: `PYTHONPATH=/private/tmp/password-policy-collections .venv/bin/python -m unittest kolla_ansible.tests.unit.test_service_password_policy kolla_ansible.tests.unit.test_vault_file_sources -v` (`kolla-targeted-green.log`).
- `flake8` new module/test: PASS; `git diff --check`: PASS.
- `ansible-playbook --syntax-check` imports modified service registration and Magnum registration: PASS.
- Actual Ansible module packing/loading reached expected missing-required-arguments validation (`kolla-module-load.log`); no cloud request made. `ansible-doc` resolves inherited openstack.cloud interface (`kolla-ansible-doc.log`).

Existing unrelated failures: broad Vault file-source/mTLS tests produced two failures in unmodified Nova/DB TLS expectations. The same two failures reproduce in the original unpacked archive: `test_mtls_database_urls_verify_ca_and_identity`, `test_nova_bootstrap_copies_vault_internal_ca`. Original baseline: 33 tests, 2 failures (`kolla-existing-baseline.log`). These files are not changed by this patch.

Limits: no Docker daemon, Linux image build, real toolbox/container, remote Keystone or cluster rollout was run. Runtime-created identities in Heat/Magnum are outside Kolla registration and require their producer to send the protected options; they are not classified by a role/name heuristic.

## Independent review fixes

Commit `0f9aac2` addresses the Kolla review findings without changing the opt-in contract or performing cluster actions:

- All three direct Magnum Keystone calls (trustee domain creation, exempt trustee-user registration, and role assignment) now forward `client_cert` and `client_key` when the selected `openstack_interface` uses internal/admin or external mTLS. The new `magnum_ks_register_mtls` predicate is tested against the normalized `service_ks_register_mtls` predicate so their endpoint behavior cannot silently diverge.
- TDD RED: the two new unit tests failed before the implementation with missing cert/key assertions for all three tasks and a missing Magnum mTLS predicate (four assertion failures total). Focused GREEN: both new tests pass.
- Targeted regression command with Python 3.11: `PYTHONPATH=/private/tmp/password-policy-collections ANSIBLE_HOME=/private/tmp/password-policy-ansible-home ANSIBLE_LOCAL_TEMP=/private/tmp/password-policy-local ANSIBLE_REMOTE_TEMP=/private/tmp/password-policy-remote .venv/bin/python -m unittest kolla_ansible.tests.unit.test_service_password_policy kolla_ansible.tests.unit.test_vault_file_sources -v`; result: 37 tests passed.
- `ansible-playbook --syntax-check` passed for playbooks importing `service-ks-register` and `magnum` `register.yml`, using the repository role/library paths and `/private/tmp/password-policy-collections`. The initial syntax command omitted `ANSIBLE_LIBRARY` and stopped at module resolution; rerunning with `ansible/library` resolved it and produced two clean playbook checks.
- `.venv/bin/flake8 kolla_ansible/tests/unit/test_service_password_policy.py`: PASS. `git diff --check`: PASS.

Operational `--check` limitation: when `keystone_service_password_policy_exempt` is first enabled, Ansible check mode predicts the helper directory/copy changes but does not stage `kolla_service_user.py`. If the helper is absent, the later toolbox call fails before invoking Keystone; if an older staged helper exists, the dry run can execute that stale copy. Run one normal registration/deployment pass after first enablement and after helper upgrades before relying on a subsequent whole-Kolla `--check`. With the current helper staged, its Ansible check-mode path performs Keystone reads only and suppresses user create/update writes. This limitation is documented rather than hidden behind a remote preflight that would add deployment behavior outside the review fix.
