# OpenStack PowerOps patch delivery

This repository delivers **36 ordered Git patches**, a standalone Horizon
plugin, source-level contract tests, Kolla build inputs, Kolla-Ansible
configuration, and Russian operator documentation for OpenStack Epoxy 2025.1.

Installation is in [`INSTALL.md`](INSTALL.md). Routine backend checks remain
in [`OPERATIONS.md`](OPERATIONS.md). Horizon-specific operation and RBAC are
in [`POWEROPS_HORIZON_OPERATIONS.md`](POWEROPS_HORIZON_OPERATIONS.md). The
component/scenario runbook remains `docs/powerops/POWEROPS-ARCHITECTURE.md`
after applying Kolla-Ansible patch 0005.

## Baselines

| Component | Exact baseline | Reviewed final source tree | Patches |
|---|---|---|---:|
| Horizon | `039850556d0516e52b94b28f95762f310d779f16` | `c50ffa875d2271700f8c2b24f8d7f71a6e01c395` (clean upstream; standalone plugin is outside this tree) | 0 |
| Masakari | `0fd34dd6a6d90525dbf806f35577c5ee1d7e9444` | `83bb2fd7a2d8c2f8d97e26c12fb66e8e06436bc5` | 10 |
| mistral-lib | `693174dd0aac1da22870b31e4a2481c4e749916a` | `cf20c15a39516272faf2ddfd69a74644fdc105c5` | 1 |
| Mistral | `3b2eab29e9dc71a5ba250d989155eb69a9bd8e48` | `9f9dee83d0e7146ce3d2011bc2169f0834e94ae4` | 16 |
| Kolla | `d14cef9bbafa0db561abfb0c0299d1d6bbbf8f0c` | `aba086df9f5a1e17f74eb5a67286fa00b805bb6b` | 1 |
| Kolla-Ansible | `703b06c9fa5771c758f703b424d63fb04192567a` | `0870059ba6ea82621002286e679bb93fbf719733` | 8 |

The machine-readable baseline source is
`docs/evidence/horizon-powerops-baselines.json`. Git commit IDs created by
`git am` may vary with committer metadata; final `git write-tree` equality is
the content proof.

## Patch order

Apply complete series in this dependency order:

1. `patches/masakari/0001` through `0010`;
2. `patches/mistral-lib/0001`;
3. `patches/mistral/0001` through `0016` with patched mistral-lib available;
4. `patches/kolla/0001`;
5. `patches/kolla-ansible/0001` through `0008`.

The exact 36 file paths are listed in application order in `INSTALL.md`.
`SHA256SUMS` is the complete byte manifest. Kolla-Ansible patch 0006 is the
mandatory Masakari WSGI wrapper and must precede Horizon patches 0007/0008.

The standalone `powerops-dashboard` is installed into the Horizon image; no
patch is applied to the clean Horizon source tree. Kolla's local source
configuration attaches patched Mistral to `mistral-base`, patched mistral-lib
to `mistral-base-plugin-mistral-lib`, and the plugin to
`horizon-plugin-powerops-dashboard`.

## Implemented scenarios

- exact read-only all-project compute-host inventory;
- planned power-off and reboot with `require_empty`, `live_migrate`, or `stop`;
- guarded hard-off only for `admin` power-off, never reboot;
- two-phase power-on and return through `operator_inspection_gate`;
- emergency Masakari fencing/evacuation kept outside Horizon and Mistral's
  planned UI;
- shared fail-closed `powerops/host/<host>` coordination namespace;
- UI/server authorization `admin OR (powerops_operator AND project allowlist
  AND user allowlist)`.

`admin` is accepted in any project and bypasses both allowlists. The lists
constrain only `powerops_operator`. Mistral service credentials do not need the
human `powerops_operator` role; current human identity and roles arrive in the
trusted action context.

## Test commands and results

The final local gate completed on 2026-09-04 with these results:

- 14 delivery-artifact tests passed;
- 30 cross-repository and Horizon contract tests passed;
- 99 plugin tests passed under the isolated Horizon 2025.1 environment;
- Django system check reported no issues;
- plugin `tox -e pep8` passed;
- 57 focused Kolla tests passed for build and PowerOps behavior;
- 3 Kolla-Ansible Masakari WSGI tests passed;
- all 36 patch checksums passed and the patch manifest remained exact;
- Python test sources compiled and `git diff --check` passed.

The repeatable source gate is:

```bash
python3 -m unittest tests.test_delivery_artifacts -v
POWEROPS_MASAKARI_TREE="$MASAKARI_SRC" \
POWEROPS_MISTRAL_LIB_TREE="$MISTRAL_LIB_SRC" \
POWEROPS_MISTRAL_TREE="$MISTRAL_SRC" \
POWEROPS_DASHBOARD_TREE="$POWEROPS_BUNDLE/powerops-dashboard" \
POWEROPS_KOLLA_TREE="$KOLLA_BUILD_SRC" \
POWEROPS_KOLLA_ANSIBLE_TREE="$KOLLA_SRC" \
python3 -m unittest \
  tests.test_cross_repository_contract \
  tests.test_horizon_powerops_contract -v
shasum -a 256 -c SHA256SUMS
python3 -m compileall -q tests
git diff --check
```

The standalone package also built successfully without Git metadata. The
wheel and sdist are version `0.0.1`; both publish the required dependencies,
and the wheel contains all five templates plus its JavaScript and CSS assets.
Recorded SHA-256 values are:

- wheel: `810a80aac5d9a9538e72aae8245645afd26276e27169fc91bd7b3fb081c2f225`;
- sdist: `386874373079c9001dee20e36d68d7305451626bd6f894c2544f175cc4273997`.

The mock UI was started and inspected at all six routes: host inventory,
execution details for `RUNNING` and uncertain `ERROR`, planned operation,
return start, and return resume. Every route returned HTTP 200, the uncertain
result displayed `Verification required:`, and a single configured region hid
the region selector.

The four target images were built and inspected locally:

| Image | Local image ID |
|---|---|
| `powerops-local/horizon:2025.1-powerops` | `sha256:0c7b0faf396df276b42755995d32637aba094e4a3ccbcd241575c41e4a1af493` |
| `powerops-local/mistral-api:2025.1-powerops` | `sha256:5c4d2161a68132e10d568a28ce348ca4567572d502804d3f36a1cf4553e30f98` |
| `powerops-local/mistral-engine:2025.1-powerops` | `sha256:0f82a26ecf8ea0a04a691b53b724c3c263ec088c5313fc310849c0863694ef5e` |
| `powerops-local/mistral-executor:2025.1-powerops` | `sha256:07af76f4172c6bfffb55b7b5b36a49ff8f812cece5d19cd20c154b04f9e7471b` |

Read-only checks independently loaded the Horizon plugin and every one of the
six `powerops.*` action entry points in each Mistral replica. Each target image
passed `pip check`; all three Mistral images contained the patched
`mistral-lib` version `3.3.1+powerops.1`.

The image IDs above predate the follow-up mock stylesheet fix, which changes
only `poweropsdashboard.test.preview_settings` and its regression tests. The
deployed Horizon settings and production PowerOps request path are unchanged;
the production images were therefore not rebuilt for this preview-only fix.

The Kolla-Ansible workbook is byte-identical to the reviewed Mistral workbook.
The mandatory WSGI patch 0006 remains byte-identical at SHA-256
`b8e41f6ff7c8e54d0f14fdbe175b95d43d1d65ca542ec2d0f549fd0a98d0a27a`.

PowerOps action audit output is a `structured LOG.info process log` only.
There is `no external durable audit store` and `no delivery or persistence
guarantee`; durable collection remains an operator logging-platform duty.

## Static verification boundary

Proven locally are the exact component baselines, current patch count and
checksums, clean patch application and reviewed tree hashes, source contract
invariants, workbook equality, mandatory WSGI patch immutability, standalone
package contents, plugin tests, mock UI rendering, local image builds, and
read-only imports from every target image. No image was pushed.

No deployment or reconfiguration was run. No workflow was started or resumed,
no Nova service/VM state changed, no Ironic/BMC power request was made, and no
Masakari notification/fencing/evacuation was triggered.

## Live verification still required

Not proven by this source delivery:

- deployed Horizon/Mistral/Masakari behavior;
- real Keystone assignments and the effective scoped token roles;
- real service endpoints and TLS paths;
- live shared Memcached and etcd ownership/lease behavior;
- VM migration/stop/start;
- Ironic/BMC power and stable-state observation;
- Masakari evacuation;
- a real host mapping across Nova, Masakari, and Ironic.

The completed local package, Django, mock-preview, image-build, and image-import
gates do not prove the live items above. Those require a separately approved
deployment and controlled acceptance window.

## Safe apply and rollback notes

Verify `SHA256SUMS`, start every integration branch from its exact baseline,
and apply each complete series with `git am`. On conflict, preserve diagnostic
output and use `git am --abort`; do not edit a published patch to fit another
baseline.

Before any deploy/reconfigure, retain known-good images, configuration, and
branches, and obtain separate change approval. Disabling PowerOps does not
undo completed host or VM operations and does not automatically delete the
public Mistral workbook. Runtime rollback is a state-aware operation described
in `INSTALL.md` and `OPERATIONS.md`.
