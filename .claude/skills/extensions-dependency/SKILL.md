---
name: extensions-dependency
description: Change how canvodpy takes canvod-filemap or canvod-adapters from canvodpy-extensions (git rev or tag, dependency groups, relock), or change canvodpy API the extensions use. Use when touching those sources or public API they import.
---

# canvodpy and canvodpy-extensions

The two repositories depend on each other, in both directions:

- canvodpy installs **canvod-filemap** (and canvod-adapters) from the
  extensions repository on GitHub, as workspace dependency groups:
  `uv sync --group filemap`. They are not extras and not on PyPI.
- The extensions import canvodpy: canvod-preflight's convention, the
  readers' contracts, `canvodpy.workflows.tasks` (canvod-airflow). Until
  canvodpy 1.0.0 is on PyPI they take canvodpy from a canvodpy git branch.

## Where it is set

Root `pyproject.toml`:

- `[tool.uv.sources]`: canvod-filemap and canvod-adapters, each as
  `git` + `subdirectory` + a pinned `rev` (a commit) or `tag`. Never a
  branch: a branch makes the lock move without a change here.
- `[dependency-groups]`: `filemap = ["canvod-filemap"]`.
- `override-dependencies`: makes canvod-filemap use this workspace's
  canvod-preflight, so the lock holds one canvod-preflight. Drop it once
  both sides take canvod-preflight from PyPI.

## Move the pin

1. Pick the extensions commit (merged `main`) or release tag.
2. Change `rev`/`tag` in `[tool.uv.sources]`, then
   `uv lock --upgrade-package canvod-filemap` and `uv sync --group filemap`.
3. Check: `just test-package canvodpy` (discovery uses canvod-filemap)
   and `just check-agent-docs` (paths written `extensions:<path>` are
   checked at the new commit).

## Changing canvodpy API the extensions use

Search the extensions first (`git -C <extensions checkout> grep -n <name>`).
A rename here breaks them once they relock. Keep the old name working
with the `deprecate` guide, and note the change for the extensions. Their
side of this is their `canvodpy-dependency` guide and `just lock-canvodpy`
(in their repository).
