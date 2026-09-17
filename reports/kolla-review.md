# Independent Kolla security and integration review

Reviewed range: `54f4ee851cc2fc5db1068a8c5807f2b8e8e2c475..0f9aac2d479087808283ddb7fa382b6a8a1db00c`

Scope: Task 2 and the global constraints in `docs/superpowers/plans/2026-09-17-password-policy-exemption.md`, including the assumed patched Keystone create/update interface. This was a read-only source and evidence review. I did not rerun the test suite or modify the Kolla worktree.

## Findings

### Critical

None.

### Important

None.

### Minor

None open.

## Resolution of earlier findings

1. **Resolved: Magnum mTLS client identity forwarding.** All three direct Magnum Keystone calls now forward `client_cert` and `client_key`: domain creation at `ansible/roles/magnum/tasks/register.yml:20-21`, trustee-user registration at `:41-42`, and role assignment at `:58-59`. The predicate at `ansible/roles/magnum/defaults/main.yml:155-166` selects internal/admin versus public mTLS with the same logic as `service_ks_register_mtls`. Tests at `kolla_ansible/tests/unit/test_service_password_policy.py:247-278` assert every call and compare the normalized predicates. This closes the prior Important finding and satisfies the explicit Task 2 TLS-forwarding requirement.

2. **Resolved as an explicit operational limitation: first-enable and post-upgrade whole-Kolla `--check`.** The helper remains staged only by normal Ansible file/copy execution; no remote write or concealed preflight was added merely to make check mode appear successful. `password-policy-patches/README.md:162` and `password-policy-patches/reports/kolla-implementation.md:38` now state that an absent helper causes the first dry run to fail and an existing helper can be stale, require a normal staging/registration pass first, and distinguish that limitation from the current helper's read-only check-mode behavior. This is accurate and sufficient for the agreed deployment boundary.

## Specification compliance

- **Pass:** opt-in defaults to false; disabled mode keeps the stock `openstack.cloud.identity_user` path.
- **Pass:** create sends the password and all four Boolean options in one SDK `POST`; rotation sends the password and merged effective options in one `PATCH`.
- **Pass:** existing unrelated options are copied before the four service options are overlaid. `on_create` avoids password writes; `always` preserves the prior rotation behavior.
- **Pass:** exact name plus domain filtering is used for users, with mismatch and duplicate fail-closed checks. Project/domain consistency is checked. Project-less Magnum trustee creation and preservation of an existing default project are handled.
- **Pass:** service-password tasks use unconditional `no_log: true`; module results exclude the password; SDK failures are reduced to a generic message and status code.
- **Pass:** Vault references still traverse the unchanged recursive `kolla_toolbox` resolver. CA and endpoint-appropriate client certificate/key parameters are forwarded on the common service path and all direct Magnum Keystone calls.
- **Pass:** the module is copied beneath `/etc/kolla/kolla-toolbox`, which the existing toolbox volume mounts read-only at `/var/lib/kolla/config_files`; `module_path` is passed as a separate argv element. The role file source resolves from `service-ks-register/files` without a toolbox image change.
- **Pass:** the feature remains limited to explicitly managed Kolla service identities and the Magnum trustee; it does not infer exemptions from names or roles.

## Quality and evidence assessment

The helper is small, fail-closed, and uses real openstacksdk resources in request-serialization tests. The HTTP assertions directly prove atomic create/update payloads, option preservation, rotation semantics, exact lookup filters, check-mode suppression of writes, and refusal handling. The custom Ansible module was packed and loaded far enough to validate its argument spec, while `ansible-doc` confirms the inherited OpenStack auth/TLS interface.

The review-fix delta is bounded to the Magnum predicate, the three direct call sites, and two focused tests. The supplied implementation evidence reports 37 targeted feature-plus-Vault tests passing, clean syntax checks for the modified role imports, flake8 passing, and `git diff --check` passing. I did not rerun these commands because the re-review found no specific inconsistency requiring another execution. The two broader Vault/mTLS failures documented earlier reproduce in the unmodified baseline and touch files outside this patch, so they are not regressions from this change. The Kolla worktree remained clean at the reviewed head.

No container, remote Keystone, or cluster execution was performed. The evidence proves source integration and SDK wire serialization, not that the mounted module loads in the actual Kolla toolbox image or that the patched Keystone accepts the requests under the intended deployment policy. Those runtime boundaries are stated in the package documentation.

## Verdict

**Approved for packaging.** The earlier Important finding is fixed, the Minor check-mode limitation is accurately documented, and no new Critical, Important, or Minor issue was found in `0f9aac2d479087808283ddb7fa382b6a8a1db00c`.
