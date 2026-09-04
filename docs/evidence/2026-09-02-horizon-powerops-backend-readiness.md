# Horizon PowerOps backend and delivery readiness

Date: 2026-09-02; final local verification: 2026-09-04

## Scope and safety boundary

This evidence records immutable source baselines, clean application of every
published patch series, the standalone Horizon plugin gate, local package and
image builds, and read-only inspection of every target image.

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

The existing patch files were applied without modification to their exact
baselines:

```console
git -C worktrees/masakari-horizon-verify am "$PWD"/patches/masakari/*.patch
git -C worktrees/mistral-lib-horizon-clean am "$PWD"/patches/mistral-lib/*.patch
git -C worktrees/mistral-horizon-clean am "$PWD"/patches/mistral/*.patch
git -C worktrees/kolla-horizon-clean am "$PWD"/patches/kolla/*.patch
git -C worktrees/kolla-ansible-horizon-verify am "$PWD"/patches/kolla-ansible/*.patch
```

All 36 patches applied successfully: 10 Masakari, 1 mistral-lib, 16 Mistral,
1 Kolla, and 8 Kolla-Ansible. The standalone plugin does not modify the clean
Horizon tree. The resulting reviewed tree hashes are:

| Series | `git write-tree` result |
| --- | --- |
| Horizon upstream | `c50ffa875d2271700f8c2b24f8d7f71a6e01c395` |
| Masakari | `83bb2fd7a2d8c2f8d97e26c12fb66e8e06436bc5` |
| mistral-lib | `cf20c15a39516272faf2ddfd69a74644fdc105c5` |
| Mistral | `9f9dee83d0e7146ce3d2011bc2169f0834e94ae4` |
| Kolla | `aba086df9f5a1e17f74eb5a67286fa00b805bb6b` |
| Kolla-Ansible | `0870059ba6ea82621002286e679bb93fbf719733` |

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

The immutable baseline contract was first run before the JSON manifest existed
and failed with `FileNotFoundError`, establishing RED:

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

## Final Task 12 verification

The fresh local verification completed with:

| Gate | Result |
| --- | --- |
| Delivery artifact suite | 14 passed |
| Cross-repository and Horizon contracts | 30 passed |
| Standalone plugin suite | 99 passed |
| Django system check | 0 issues |
| Plugin `tox -e pep8` | passed |
| Focused Kolla PowerOps/build suite | 57 passed |
| Kolla-Ansible Masakari WSGI suite | 3 passed |
| Patch checksum manifest | 36 of 36 passed |
| Python compile and whitespace gates | passed |

The standalone plugin built from a source copy without `.git`, proving the PBR
fallback. Its wheel metadata records version `0.0.1` and dependencies on
`pbr`, `horizon`, and `python-mistralclient`; the sdist includes
`requirements.txt`. The wheel contains all five templates and its JavaScript
and CSS assets.

| Artifact | SHA-256 |
| --- | --- |
| `powerops_dashboard-0.0.1-py3-none-any.whl` | `810a80aac5d9a9538e72aae8245645afd26276e27169fc91bd7b3fb081c2f225` |
| `powerops_dashboard-0.0.1.tar.gz` | `386874373079c9001dee20e36d68d7305451626bd6f894c2544f175cc4273997` |

The isolated mock server returned HTTP 200 for host inventory, RUNNING
execution details, uncertain ERROR details, planned power-off, return start,
and return resume. The uncertain outcome included `Verification required:`;
the single-region configuration hid the region selector.

A follow-up visual check found that the original preview inherited Horizon's
unit-test settings without its SCSS precompiler and theme static directories.
Two regression tests were added, the preview-only settings were corrected, and
a fresh 1440x900 headless render confirmed normal Horizon navigation, logo,
typography, and table styling.

## Local image evidence

Kolla built the four target Linux/arm64 images locally:

| Image | Image ID |
| --- | --- |
| `powerops-local/horizon:2025.1-powerops` | `sha256:0c7b0faf396df276b42755995d32637aba094e4a3ccbcd241575c41e4a1af493` |
| `powerops-local/mistral-api:2025.1-powerops` | `sha256:5c4d2161a68132e10d568a28ce348ca4567572d502804d3f36a1cf4553e30f98` |
| `powerops-local/mistral-engine:2025.1-powerops` | `sha256:0f82a26ecf8ea0a04a691b53b724c3c263ec088c5313fc310849c0863694ef5e` |
| `powerops-local/mistral-executor:2025.1-powerops` | `sha256:07af76f4172c6bfffb55b7b5b36a49ff8f812cece5d19cd20c154b04f9e7471b` |

Read-only inspection imported the Horizon plugin and independently loaded all
six `powerops.*` action entry points in `mistral-api`, `mistral-engine`, and
`mistral-executor`. Every image passed `pip check`; each Mistral image reported
the patched fork as `mistral-lib=3.3.1+powerops.1`. No image was pushed.

These image IDs predate the follow-up change limited to mock preview settings
and their regression tests. No deployed setting or production request path was
changed, so the production images were not rebuilt for that preview-only fix.

## Proof boundary

This evidence proves source structure, clean patch application, unit and
contract behavior, mock rendering, Python package contents, local container
assembly, dependency consistency, and imports from every target image. It does
not prove deployed Horizon/Mistral/Masakari behavior, Keystone assignments,
real service endpoints, shared etcd ownership, VM migration/stop/start,
Ironic/BMC power, Masakari evacuation, or a real cross-service host mapping.

No deployment or reconfiguration was run. No workflow was started or resumed,
no service was restarted, and no Nova, Ironic, BMC, Masakari, fencing, or
evacuation mutation was performed.
