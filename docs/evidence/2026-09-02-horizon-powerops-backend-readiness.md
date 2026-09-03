# Horizon PowerOps backend baseline readiness

Date: 2026-09-02

## Scope and safety boundary

This evidence establishes immutable local source baselines and proves that the
already published Masakari, Mistral, and Kolla-Ansible patch series apply
cleanly. It does not add component implementation.

No live OpenStack cloud was accessed. No workflow was started, no service was
deployed, reconfigured, or restarted, and no VM, power, fencing, or evacuation
operation was performed.

Source inspection and clean-apply evidence are not proof of a running
OpenStack deployment.

## Immutable component baselines

| Component | Source | Branch or origin | Commit |
| --- | --- | --- | --- |
| Horizon | OpenDev upstream | `stable/2025.1` | `039850556d0516e52b94b28f95762f310d779f16` |
| mistral-lib | OpenDev upstream | `stable/2025.1` | `693174dd0aac1da22870b31e4a2481c4e749916a` |
| Mistral | OpenDev upstream | `stable/2025.1` | `3b2eab29e9dc71a5ba250d989155eb69a9bd8e48` |
| Masakari | OpenDev upstream | `stable/2025.1` | `0fd34dd6a6d90525dbf806f35577c5ee1d7e9444` |
| Kolla | OpenDev upstream | `stable/2025.1` | `d14cef9bbafa0db561abfb0c0299d1d6bbbf8f0c` |
| Kolla-Ansible | imported local source | `powerops/kolla-ansible` | `703b06c9fa5771c758f703b424d63fb04192567a` |

The five upstream commits were resolved from fetched `stable/2025.1`
histories. Kolla-Ansible was cloned from
`/Users/dmitry/Desktop/ironic:mistral:masakari/powerops-patches/work/kolla-ansible`
and pinned to the imported commit shown above.

The immutable machine-readable copy is
`docs/evidence/horizon-powerops-baselines.json`.

## Fresh component worktrees

The following worktrees were created directly from the immutable commits:

| Worktree | Branch/state | Baseline |
| --- | --- | --- |
| `worktrees/horizon-powerops-clean` | `powerops/horizon-clean` | Horizon commit above |
| `worktrees/mistral-lib-horizon-clean` | `powerops/security-context-clean` | mistral-lib commit above |
| `worktrees/mistral-horizon-clean` | `powerops/mistral-horizon-clean` | Mistral commit above |
| `worktrees/masakari-horizon-verify` | `powerops/masakari-horizon-verify` | Masakari commit above |
| `worktrees/kolla-horizon-clean` | `powerops/kolla-horizon-clean` | Kolla commit above |
| `worktrees/kolla-ansible-horizon-verify` | detached verification worktree | Kolla-Ansible commit above |

All six worktrees had empty `git status --short` immediately after creation.

## Published series clean-apply proof

The existing patch files were applied without modification:

```console
git -C worktrees/masakari-horizon-verify am "$PWD"/patches/masakari/*.patch
git -C worktrees/mistral-horizon-clean am "$PWD"/patches/mistral/*.patch
git -C worktrees/kolla-ansible-horizon-verify am "$PWD"/patches/kolla-ansible/*.patch
```

All 10 Masakari patches, all 10 Mistral patches, and all 6 Kolla-Ansible
patches applied successfully. The resulting clean tree hashes are:

| Series | `git write-tree` result |
| --- | --- |
| Masakari | `83bb2fd7a2d8c2f8d97e26c12fb66e8e06436bc5` |
| Mistral | `8e3009eb1abf8033608d31d7e60cdb02ab8da1ed` |
| Kolla-Ansible | `c1488cb1a5db61d102bd55a9e9a2fafb5c25426c` |

Each hash exactly matches the published expected tree. This proves clean
application without changing any published patch byte.

## Masakari WSGI Kolla-Ansible dependency

Command:

```console
python3 worktrees/kolla-ansible-horizon-verify/kolla_ansible/tests/unit/test_masakari_wsgi_wrapper.py -v
```

Result: 3 tests ran and all 3 passed. Static inspection also confirms:

- the role copies `masakari-api.wsgi` into the Masakari API configuration;
- the container installs it at `/etc/masakari/masakari-api.wsgi`;
- the wrapper imports `api` from `masakari.wsgi` and exports its application;
- Apache uses `WSGIScriptAlias` for `/etc/masakari/masakari-api.wsgi`.

The test only reads and asserts repository files. It performs no power,
fencing, evacuation, deployment, or service operation.

## Baseline gate commands

The baseline contract was first run before the JSON manifest existed and
failed with `FileNotFoundError`, establishing RED:

```console
python3 -m unittest tests.test_horizon_backend_baselines -v
```

After recording the six immutable commits and published patch counts, the
same command ran 1 test successfully, establishing GREEN. The final root
evidence gate also includes:

```console
git diff --check
```

The final command completed without whitespace errors.
