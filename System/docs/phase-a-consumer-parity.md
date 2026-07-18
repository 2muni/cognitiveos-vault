# Phase A consumer and worktree parity evidence

This record completes the remaining independently reviewable Phase A slice
after PR #16 (`8dc1b1dfc3c5be0dd65604021d402611f79f0fed`). It is evidence for
the consumer checks and the two-independent-clean-worktree exit condition; it
does not claim that the v0.6 release itself is published.

## Executable consumer gate

`scripts/verify_release.py` now includes
`fresh-clone-public-wheel-consumer`. The gate:

1. creates a source snapshot with `git archive`;
2. rejects any non-placeholder file under the private vault roots;
3. installs the built wheel into a new, dependency-free consumer venv; and
4. runs `--help` for all seven public CLI entry points from the fresh clone.

The existing isolated wheel consumer remains a separate gate. The report is
JSON with schema `cognitiveos-release-gates-v0.1`, sorted keys, no absolute
paths, and exactly the wheel, sdist, and report in its artifact directory.

Verified locally with Python 3.14.6:

- 99 warning-strict tests passed;
- two byte-identical wheel/sdist builds passed;
- wheel and sdist contained no private vault or derived artifacts;
- the nine-tool read-only MCP surface, semantic runtime off, and writeback
  disabled contracts passed;
- both isolated wheel consumers passed, including the fresh-clone consumer;
- wheel SHA-256: `b64a1281afd76a5feab1d1102669ece83b029c817d9aa90c63cd675952cc5a8a`;
- sdist SHA-256: `3e50a830cf5839639b162378b6bcff5e250e38e483b7e7aa415efefceea43f32`.

## Two-worktree exit evidence

Orca created two independent worktrees from `origin/main`, with setup hooks
skipped and no shared `.venv`, index, model cache, or build directory:

| Worktree | HEAD | baseRef | warning-strict test output SHA-256 |
| --- | --- | --- | --- |
| `phase-a-parity-a` | `8dc1b1dfc3c5be0dd65604021d402611f79f0fed` | `origin/main` | `7f301b92a4d5e44a51603d80487f352eeae4a45e57289ad1947d6c05d2ca33de` |
| `phase-a-parity-b` | `8dc1b1dfc3c5be0dd65604021d402611f79f0fed` | `origin/main` | `7f301b92a4d5e44a51603d80487f352eeae4a45e57289ad1947d6c05d2ca33de` |

Each worktree passed 98 tests with `-W error`, `git diff --check`, and a
clean status. Their four-gate release reports were also byte-identical with
SHA-256 `de3652347728872e8f4b01819c5c8168fe49976427ebfde3201dba0da56db135`.
The two worktrees were independently created by Orca, each received its own
temporary venv containing only the build dependency, and used distinct
temporary artifact/report directories. The source Markdown checksums were not
modified. The additional fresh-clone gate in this change is exercised by the
current worktree's five-gate report above; the merged-baseline parity evidence
necessarily predates this change because the exit-gate base is `origin/main`.

## Limitations

This evidence intentionally excludes actual-vault indexing, private Markdown,
model acquisition, semantic evaluation, writeback, version changes, and
publication/tagging. The public-wheel wording refers to the validated public
wheel artifact produced by the release gate; no network download or published
v0.6 asset is required or performed.
