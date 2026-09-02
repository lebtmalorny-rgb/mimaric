# Task 3 — Mistral-lib PowerOps patch export

## Status

PASS.  The delivery repository contains exactly one independently applicable
Mistral-lib patch:

`patches/mistral-lib/0001-feat-carry-PowerOps-identity-in-action-context.patch`

The patch SHA-256 is
`98c0e39c0cb9732a157538295c9d688890fa4118d0d59708026e544ef5206144`.

## Synthetic export method

The reviewed implementation worktree was left unchanged at
`a37d9265850fd661b526578c702d6891df4a3363`.  Its two commits
(`8419730` and `a37d926`) were deliberately not exported separately.

A disposable detached worktree was created from the pinned stable/2025.1
baseline `693174dd0aac1da22870b31e4a2481c4e749916a`:

```bash
git -C sources/mistral-lib worktree add --detach \
  /tmp/mistral-lib-powerops-export \
  693174dd0aac1da22870b31e4a2481c4e749916a
git -C /tmp/mistral-lib-powerops-export diff --binary \
  693174dd0aac1da22870b31e4a2481c4e749916a \
  a37d9265850fd661b526578c702d6891df4a3363 | \
  git -C /tmp/mistral-lib-powerops-export apply --index
git -C /tmp/mistral-lib-powerops-export commit --no-verify \
  -m 'feat: carry PowerOps identity in action context'
git -C /tmp/mistral-lib-powerops-export format-patch \
  --output-directory "$PWD/patches/mistral-lib" \
  693174dd0aac1da22870b31e4a2481c4e749916a..HEAD
```

This produced synthetic export commit
`599094312e148b879a68e4c539232892e4b06bba`, with parent equal to the pinned
baseline and tree `72148cf6531037f0ea0e6e7c38bac5a24598e7b6`.  The output
directory was checked with `find ... -name '*.patch'`; count: **1**.

## Clean-apply verification

In a second disposable worktree at the same pinned baseline, the following
completed successfully:

```bash
git -C sources/mistral-lib worktree add --detach \
  /tmp/mistral-lib-powerops-apply \
  693174dd0aac1da22870b31e4a2481c4e749916a
git -C /tmp/mistral-lib-powerops-apply am \
  "$PWD/patches/mistral-lib/0001-feat-carry-PowerOps-identity-in-action-context.patch"
git -C /tmp/mistral-lib-powerops-apply diff \
  693174dd0aac1da22870b31e4a2481c4e749916a..HEAD --check
```

`git am` reported `Applying: feat: carry PowerOps identity in action context`.
The whitespace/diff check printed nothing and exited zero.  It created
`a16d5bc75783cec2d5aa30daa1d1cff9a23889de` (a different commit object, as
expected after `git am`).

## Final-tree equality

The clean-applied worktree and the reviewed final implementation have the same
Git tree object:

```text
clean-applied tree: 72148cf6531037f0ea0e6e7c38bac5a24598e7b6
final reviewed tree: 72148cf6531037f0ea0e6e7c38bac5a24598e7b6
```

Equality of the complete Git tree object proves identical tracked paths,
modes, and blob bytes.  A direct `git diff --exit-code` of the clean-applied
worktree against `a37d9265850fd661b526578c702d6891df4a3363` also printed
nothing and exited zero.

## Delivery commit

The patch and this evidence report are committed in the delivery repository
with subject:

```text
build: add Mistral-lib PowerOps context patch
```

## Self-review

- Confirmed that the reviewed implementation branch remains at `a37d926` and
  was not rewritten.
- Confirmed only one `.patch` file exists in `patches/mistral-lib` and that its
  name is the declared filename.
- Confirmed the patch is based on exactly `693174dd0...`, applies with
  `git am`, passes `git diff --check`, and reproduces the reviewed tree.
- No OpenStack service or live infrastructure action was performed.

## Concerns

The export and apply worktrees are disposable temporary state.  They are
removed after the delivery commit; all durable verification evidence is kept
in this report and the immutable patch bytes in the delivery repository.
