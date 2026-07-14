# GitHub Org Migration Plan — `nfb2021` → `tuw-geo`

Status: **planning only**. No step in this document has been executed. This is an
operations runbook to be followed manually (or semi-automated with `gh`/API calls)
by Nicolas Bader when he chooses to execute the migration.

Scope: two repositories move from the personal account `nfb2021` to the
organization `tuw-geo` (GitHub org login: `TUW-GEO`, https://github.com/TUW-GEO):

1. `nfb2021/canvodpy` → `tuw-geo/canvodpy`
2. `nfb2021/canvodpy-extensions` → `tuw-geo/canvodpy-extensions`

Nicolas remains sole maintainer with full permissions after the move. The org is
just the new home, not a change of stewardship.

---

## 1. Overview

### What's moving
- Two GitHub repositories: `canvodpy` (main monorepo) and `canvodpy-extensions`
  (optional slot-in packages: `canvod-filemap`, `canvod-airflow`, `canvod-adapters`).
- Their full git history, issues, PRs, wiki, stars/watchers, webhooks, secrets,
  deploy keys, and (for `canvodpy`) Git LFS objects if any.

### What stays the same
- Nicolas remains the maintainer with full (admin) permissions on both repos.
- All commit history, authorship, and existing DOIs/citations remain valid
  permanently — Zenodo's archival guarantee does not depend on where the GitHub
  repo currently lives (see §7 and §9).
- Branch-protection policy intent (topic-branch + PR + Nicolas merges) — this
  plan follows that same workflow for its own reference-cleanup changes (§5).

### Core mechanism: transfer, not re-creation
GitHub's built-in **repository transfer** (Settings → Danger Zone → Transfer, or
the equivalent API call) changes the repo's owner while preserving its internal
identity. A fresh `git clone` + new remote + `git push` would create a
brand-new, historyless repo under the org — it would NOT carry over issues,
PRs, stars, watchers, or the automatic old→new URL redirect, and every existing
clone, bookmark, PyPI link, DOI reference, and inbound link from the wider web
would break permanently with no recourse. Transfer is therefore the only
acceptable mechanism for this migration.

Per GitHub's docs (https://docs.github.com/en/repositories/creating-and-managing-repositories/transferring-a-repository):
- Preserved automatically: issues, pull requests, wiki, stars, watchers,
  webhooks, services, secrets, deploy keys, fork network association, Git LFS
  objects, and all git commit history.
- Automatic redirects: `git clone`/`fetch`/`push` against the old
  `owner/repo` URL, and web links to the old repo URL, redirect to the new
  location. This redirect can be lost if the old `owner/repo` namestring is
  ever reused for a different repo in the future (see §9) — so updating
  references explicitly (§5–§6) is still correct hygiene, not just relying on
  the redirect forever.
- Issue assignees: when transferring personal-account → org, issue assignees
  who are not members of the target org are cleared; assignees who are org
  members remain intact. (Not expected to matter here — verify open issue
  assignees before transfer if any exist.)

---

## 2. Pre-flight checklist (before initiating transfer)

Do all of these before touching the transfer button/API call.

### 2.1 Org access and permissions — VERIFIED, ACTION NEEDED
Checked via `gh api orgs/tuw-geo/memberships/nfb2021`:
```json
{"state": "active", "role": "member"}
```
Nicolas is an **active member** of `TUW-GEO` but **not an owner**. GitHub
requires the *initiating* user to have admin rights on the source repo (he has
this, he owns `canvodpy`) — but completing a transfer **into** an org where the
initiator only holds "member" (not "owner") role can require an existing org
owner to approve the incoming transfer, depending on the org's repository
creation/transfer policy.

**Action before transfer:**
1. Ask a current `TUW-GEO` org owner to either:
   - (a) temporarily/permanently promote Nicolas to **Owner** role in the org
     (Settings → People → change role), or
   - (b) be on standby to approve the incoming transfer request when GitHub
     prompts for it.
2. Confirm org policy doesn't block repo transfers in: org Settings →
   Member privileges → "Repository creation" / "Repository transfer" policy
   (only an owner can view/change this).
3. Confirm the target names `tuw-geo/canvodpy` and `tuw-geo/canvodpy-extensions`
   are not already taken (verify: `gh repo view tuw-geo/canvodpy`,
   `gh repo view tuw-geo/canvodpy-extensions` — both should 404 today).

### 2.2 Org security/CI baseline
1. Check org-wide Dependabot policy: Settings (org) → Code security → confirm
   Dependabot alerts/security updates are not disabled org-wide (orgs
   sometimes have stricter defaults than personal accounts).
2. Check org-wide Actions permissions: Settings (org) → Actions → General —
   confirm Actions are allowed to run, and that "Allow GitHub Actions to
   create and approve pull requests" is enabled if any workflow needs it
   (`test_coverage.yml`'s `python-coverage-comment-action` posts PR comments).
3. Check org-wide secret scanning / push protection defaults — shouldn't block
   anything here, but confirm no surprise org policy rejects the existing
   workflow files' pinned-SHA action references.

### 2.3 Submodule repos — decide scope
`canvodpy`'s `.gitmodules` declares two submodules, both pointing at other
personal `nfb2021` repos:
```
[submodule "demo"]
    path = demo
    url = https://github.com/nfb2021/canvodpy-demo.git
[submodule "packages/canvod-readers/tests/test_data"]
    path = packages/canvod-readers/tests/test_data
    url = https://github.com/nfb2021/canvodpy-test-data.git
```
Both `canvodpy-demo` and `canvodpy-test-data` are also cited with their own
Zenodo DOIs in `CITATION.cff`/`.zenodo.json` (test-data: `10.5281/zenodo.19708759`).

**Decision needed before transfer:** transfer these two alongside canvodpy, or
leave them under `nfb2021`?
- Recommendation: transfer them too, for consistency (all first-party repos
  live under one org) and so `.gitmodules` URLs can point at `tuw-geo` instead
  of a personal namespace that's otherwise being retired from active use.
  If left under `nfb2021`, GitHub's redirect still makes the old submodule URLs
  work indefinitely (until/unless that namespace gets reused), so this is not
  urgent — but resolve it explicitly rather than by default.
- If transferring: add `canvodpy-demo` and `canvodpy-test-data` as two more
  repos in this same runbook (repeat §3–§6 for each; they don't have PyPI/
  Zenodo-GitHub-integration/Coveralls complexity, so their post-transfer
  cleanup is much shorter — mainly `.gitmodules` URL update in the parent
  repo, and their own CITATION.cff/README self-references if any).

### 2.4 PyPI trusted publisher reconfiguration — prepare in advance
Confirmed which `canvodpy` packages are actually live on PyPI today
(`curl -s -o /dev/null -w "%{http_code}" https://pypi.org/pypi/<name>/json`):

| Package | On PyPI? |
|---|---|
| `canvodpy` | Yes (200) |
| `canvod-store` | Yes (200) |
| `canvod-vod` | Yes (200) |
| `canvod-readers` | Yes (200) |
| `canvod-grids` | Yes (200) |
| `canvod-auxiliary` | Yes (200) |
| `canvod-utils` | Yes (200) |
| `canvod-viz` | Yes (200) |
| `canvod-ops` | Yes (200) |
| `canvod-audit` | Yes (200) |
| `canvod-store-metadata` | Yes (200) |
| `canvod-config` | No (404) — not yet published, or TestPyPI-only; re-check before relying on this list |
| `canvod-preflight` | No (404) — same caveat |

`canvodpy-extensions` has **no PyPI publish workflow at all** — confirmed via
`ls .github/workflows/` (no `publish_pypi.yml`/`publish_testpypi.yml`) and via
`docs/guides/extensions.md`: "Extensions are not published to PyPI." Its
packages (`canvod-filemap`, `canvod-airflow`, `canvod-adapters`) are installed
by git URL only. **No PyPI trusted-publisher work is needed for
canvodpy-extensions.**

For each of the 11 `canvodpy` packages above that are live on PyPI (repeat
per-project — PyPI trusted publishers are per-*project*, not per-repo):
1. Log into pypi.org as the account that administers these projects.
2. Go to "Your projects" → select project → "Manage" → "Publishing" tab.
3. **You cannot edit an existing trusted publisher's owner field in place** —
   PyPI's docs do not describe an in-place edit for the GitHub owner value.
   The safe, documented pattern is: add a **new** trusted publisher entry with
   `repository_owner = tuw-geo`, same repo name, same workflow filename
   (`publish_pypi.yml` / `publish_testpypi.yml`), same environment name
   (`pypi` / `testpypi`), then remove the old `nfb2021`-owner entry once the
   new one is confirmed working. Do this for both `publish_pypi.yml` (env
   `pypi`) and `publish_testpypi.yml` (env `testpypi`) trusted publisher
   entries, for every one of the 11 live packages.
4. **Do this in the same release cycle as the transfer** — ideally
   immediately before or immediately after the `gh repo transfer` moment,
   and *before* the next tagged `vX.Y.Z` push triggers `publish_pypi.yml`.
   PyPI checks the immutable `repository_owner_id` (not just the name string)
   against its stored trusted-publisher config — a stale entry will cause the
   next publish to fail with an OIDC identity mismatch (`invalid-publisher`),
   not silently succeed under the old identity.
5. Not fully verified: whether PyPI's UI literally has a delete-then-recreate
   flow only, or whether it has grown an edit-in-place capability since the
   docs were last indexed. **Verify manually on the live PyPI UI at the time
   of migration** — check the "Publishing" tab for an edit affordance before
   assuming delete+recreate is required.

### 2.5 Zenodo — confirm current linkage state
1. Log into zenodo.org → Account → GitHub (https://zenodo.org/account/settings/github/).
2. Confirm `canvodpy` and `canvodpy-extensions` currently show as "enabled" /
   toggled on under the `nfb2021` namespace.
3. No action needed yet at this stage — actual re-toggle happens post-transfer
   (§4) because Zenodo's repo list needs to resync against GitHub after the
   ownership changes.

### 2.6 Coveralls — confirm current linkage state
1. Log into coveralls.io, confirm both repos currently appear under
   `nfb2021` in the repo list and coverage is currently reporting (green
   badge, recent build).
2. `test_coverage.yml` uses `coverallsapp/github-action@v2.3.7` with only
   `file: coverage.lcov` — **no explicit `COVERALLS_REPO_TOKEN` secret is
   referenced in the workflow**, meaning it appears to rely on
   Coveralls' GitHub-App/OIDC-based flow rather than a static repo token.
   **Verify manually**: check repo Settings → Secrets and variables → Actions
   on both repos for a `COVERALLS_REPO_TOKEN` (or similarly named) secret that
   isn't visible from reading the workflow file alone. If one exists, plan to
   regenerate it post-transfer per §4.

### 2.7 GitHub Pages custom domain check
1. Confirmed via `gh api repos/nfb2021/canvodpy/pages` and
   `.../canvodpy-extensions/pages`: both show `"cname": null` — **no custom
   domain configured** on either repo. This means the DNS-takeover risk GitHub
   warns about for custom-domain Pages sites during transfer does not apply
   here. Both currently resolve at the default
   `https://nfb2021.github.io/<repo>/` URL.

### 2.8 Branch protection — record current state for post-transfer diff
Confirmed via `gh api repos/nfb2021/canvodpy/branches/main/protection` on
`canvodpy`'s `main`:
- Required status checks (strict, must be up to date): `lock_file`,
  `linting`, `formatting`, `test_coverage`.
- PR reviews required: yes (dismiss stale reviews on push), 0 required
  approving reviewers configured (owner-merge model).
- Force pushes and deletions: blocked.
- `enforce_admins`: **disabled** (Nicolas as admin can bypass — consistent
  with him being sole maintainer).

Record the equivalent for `canvodpy-extensions` before transfer
(`gh api repos/nfb2021/canvodpy-extensions/branches/main/protection`) so
you have a known-good baseline to diff against in §4.4.

### 2.9 Reference-cleanup PR prepared in advance (see §5 for full detail)
Draft the search-and-replace PR(s) now, against the *old* `nfb2021` URLs, but
do not merge until the transfer has completed (§5.3 explains why and the exact
ordering).

---

## 3. The transfer itself

### 3.1 Method
No dedicated `gh repo transfer` subcommand exists in the GitHub CLI (confirmed
via search of `gh` docs/issues — this has been a standing feature request,
`cli/cli#5292`, not implemented as of this writing). Two equivalent options:

**Option A — Web UI (recommended, has the safety confirmation prompt):**
1. Go to `https://github.com/nfb2021/canvodpy/settings`.
2. Scroll to "Danger Zone" → click **Transfer**.
3. Enter `tuw-geo` as the new owner.
4. Optionally rename during transfer (not needed here — same name).
5. Type the repository name (`canvodpy`) to confirm.
6. Submit. If org policy requires it, an org owner will see a pending-transfer
   approval prompt (org Settings → or an email/notification) and must approve.

**Option B — API via `gh api` (scriptable, no interactive confirmation
screen — use carefully):**
```bash
gh api -X POST repos/nfb2021/canvodpy/transfer -f new_owner="tuw-geo"
```
This returns immediately with the original owner info; the transfer proceeds
asynchronously. Poll `gh api repos/tuw-geo/canvodpy` until it resolves
(200) to confirm completion.

Either method is real and usable; Option A is recommended for a one-time,
low-frequency operation like this because of the explicit confirmation step
and because org-approval prompts are more visible in the UI flow.

### 3.2 Order: sequential, canvodpy first
Do NOT transfer both repos in the same action/session. Recommended order:

1. **`canvodpy` first.** It's the core monorepo; `canvodpy-extensions`
   already depends on it conceptually (its packages install *alongside*
   canvodpy) but does not have a hard runtime git-URL dependency pointing at
   `canvodpy` itself (checked: no `pyproject.toml` entry in
   canvodpy-extensions references `canvodpy` by git URL). So transferring
   canvodpy first doesn't break extensions' installability.
2. **`canvodpy-extensions` second**, once canvodpy's transfer is confirmed
   complete and its PyPI/Pages/Zenodo immediate fixes (§4) are underway.
   canvodpy's own root `pyproject.toml` has git-URL dependencies pointing at
   `canvodpy-extensions.git` (`canvod-filemap`, `canvod-adapters`) — these
   continue to resolve fine against the *old* URL via GitHub's redirect during
   the gap between the two transfers, so there's no breakage window, but
   doing canvodpy-extensions promptly afterward minimizes how long you're
   relying on the redirect rather than a corrected URL.

Rationale for sequential (not simultaneous): each transfer needs its own
same-day follow-up (§4) — running them one at a time keeps the "what needs
fixing right now" list short and traceable, and avoids compounding two
sets of PyPI/Zenodo/Coveralls re-linking work into one confusing session.

### 3.3 Immediately after each transfer
1. Confirm new location resolves: `gh repo view tuw-geo/canvodpy` (or
   `-extensions`).
2. Confirm redirect works from old URL:
   `git ls-remote https://github.com/nfb2021/canvodpy.git` should still
   succeed (redirected) immediately after transfer.
3. Note the exact transfer timestamp (for correlating with PyPI/Zenodo/
   Coveralls follow-up in §4, all of which are time-sensitive).

---

## 4. Immediate post-transfer fixes (same-day)

Do these the same day as each repo's transfer, in this rough priority order
(most time-sensitive first):

### 4.1 PyPI trusted publisher reconfiguration (canvodpy only — highest urgency)
1. For each of the 11 live PyPI projects listed in §2.4, add the new
   `tuw-geo`-owner trusted publisher entry (if not already prepared per
   §2.4) and remove the stale `nfb2021`-owner entry.
2. Do this **before** the next tagged release (`vX.Y.Z` push) triggers
   `publish_pypi.yml` — a stale entry causes an OIDC `invalid-publisher`
   failure at publish time, not a silent fallback.
3. Do NOT wait for a release to discover this is broken — verify with a
   `workflow_dispatch` manual run of `publish_pypi.yml` against TestPyPI
   equivalents first if you want a dry run without cutting a real tag (both
   workflows support `workflow_dispatch`).

### 4.2 Zenodo GitHub-integration re-toggle
1. Go to https://zenodo.org/account/settings/github/, click "Sync now" (or
   equivalent) to refresh Zenodo's view of your GitHub repos so
   `tuw-geo/canvodpy` and `tuw-geo/canvodpy-extensions` appear in the list.
2. Toggle the integration **on** for both repos under their new org location.
   (The old `nfb2021/...` toggle state becomes irrelevant once the repo no
   longer exists under that owner from GitHub's API perspective, even though
   the URL redirects.)
3. Do this **before the next tagged release** on either repo — a release
   cut while the toggle is off (or stale) will NOT trigger a new Zenodo
   archive/DOI-version for that release.
4. Reassurance to carry into this step and beyond: **existing/already-
   published Zenodo DOIs and their archived zip snapshots remain valid
   permanently, independent of this transfer.** This is Zenodo's own
   guarantee — `10.5281/zenodo.18496233` (canvodpy concept DOI),
   `10.5281/zenodo.21359005`/`21359006` (canvodpy-extensions concept/version
   DOI), and `10.5281/zenodo.19708759` (canvodpy-test-data) are unaffected.
   Only *future* releases need the toggle re-flipped to keep archiving.
5. Not fully verified: whether Zenodo's re-sync always cleanly picks up an
   org-transferred repo on the first try — a real user-reported case
   (zenodo/zenodo GitHub issue history) describes the integration toggle not
   "staying on" after refresh for an org repo in at least one instance.
   **Verify manually**: if the toggle doesn't stick, Zenodo support
   (support@zenodo.org, or their GitHub issue tracker) is the fallback.

### 4.3 GitHub Pages re-verification
1. `gh api repos/tuw-geo/canvodpy/pages` — confirm still `"status":"built"`.
   If Pages did not carry over cleanly, re-enable with the same POST used
   earlier this session for canvodpy-extensions:
   ```bash
   gh api -X POST repos/tuw-geo/canvodpy/pages -f "source[branch]=gh-pages" -f "source[path]=/"
   ```
   (repeat for `canvodpy-extensions` with its own repo path).
2. Confirm the new URL resolves: `https://tuw-geo.github.io/canvodpy/` (and
   `/canvodpy-extensions/`). Expect this to take a few minutes after the
   `deploy_docs.yml` workflow next runs (it only runs on `release: published`
   or manual `workflow_dispatch` — trigger a manual dispatch if you want the
   new URL live immediately rather than waiting for the next release).
3. Note: the *old* `nfb2021.github.io/...` URL will likely keep serving the
   last-built content for a while via GitHub's redirect behavior for Pages
   sites tied to transferred repos — do not treat that as "nothing needs
   updating"; all first-party references should still move to the new URL
   (§5).

### 4.4 Branch protection re-verification
1. `gh api repos/tuw-geo/canvodpy/branches/main/protection` — diff against
   the baseline captured in §2.8. Confirm the same four required status
   checks (`lock_file`, `linting`, `formatting`, `test_coverage`) are still
   listed and still required, PR-review requirement intact, force-push/
   deletion still blocked.
2. GitHub's docs say branch protection rules are repo-level and generally
   preserved across a transfer — but do not assume; check names in
   particular, since these are matched by literal job-name string from the
   workflow files and could theoretically need to re-resolve after an owner
   change. Confirm by triggering one PR after transfer and watching that all
   four checks actually appear and gate merge as before.

### 4.5 Org Dependabot / security-settings verification
1. Confirm Dependabot alerts fire post-transfer: Settings (repo) → Code
   security → confirm "Dependabot alerts" and "Dependabot security updates"
   show enabled (not overridden off by an org-wide policy discovered in
   §2.2).
2. Confirm `.github/dependabot.yml` still runs on its schedule (next
   scheduled Dependabot run, or trigger manually if the UI allows).

### 4.6 OpenSSF Scorecard / badge verification
1. Scorecard results and any public badge/scorecard.dev page reference the
   literal `github.com/owner/repo` string — expect the badge URL and
   scorecard.dev lookup to need the new `tuw-geo/...` path (part of §5's
   grep-and-replace, but the *live* Scorecard run itself will re-key
   automatically the next time `scorecard.yml` runs against the new repo,
   since the workflow computes `github.repository` dynamically).
2. If either repo is later registered on
   openssf.bestpractices.dev (currently NOT done for canvodpy-extensions per
   project memory — listed open TODO, deferred), treat that as a "register
   once, under `tuw-geo`" task rather than a migration of prior state — there
   is no existing registration to move.

---

## 5. Reference cleanup PR(s)

### 5.1 Re-runnable verification greps
Run these exact commands against both repos' working trees at the time of
cleanup (not just once — re-run as the actual verification step, since new
`nfb2021` references can be added between now and execution time):

```bash
# 1. General nfb2021 string across doc/config/metadata file types
grep -rl "nfb2021" --include="*.md" --include="*.yml" --include="*.yaml" \
  --include="*.toml" --include="*.cff" --include="*.json" .

# 2. GitHub Pages URLs specifically (may be cased/formatted differently)
grep -rn "nfb2021.github.io" --include="*.md" --include="*.yml" \
  --include="*.yaml" --include="*.toml" --include="*.cff" --include="*.json" .

# 3. Literal github.com/nfb2021 substring (catches badge URLs, git+https
#    dependency URLs, and anything the first grep's extension filter missed)
grep -rn "github.com/nfb2021" .

# 4. Workflow files specifically — highest risk for silent CI breakage
grep -rn "nfb2021" .github/workflows/*.yml
```

At the time of this planning pass (2026-07-14), running these against the
local checkouts found:
- `canvodpy` (`/Users/work/Developer/GNSS/canvodpy-perf`): **65 files** match
  grep #1. Grep #4 (workflow files) returned **zero matches** — none of
  canvodpy's `.github/workflows/*.yml` hardcode `nfb2021` (they use
  `github.repository`/`github.token` context expressions instead, which
  re-key automatically post-transfer). This is good news: no CI workflow
  logic needs editing, only docs/config/metadata.
- `canvodpy-extensions` (`/Users/work/Developer/GNSS/canvodpy-extensions`):
  **21 files** match grep #1, same zero-match result for grep #4.
- Re-run all four greps again at actual execution time — this list will have
  drifted by then.

### 5.2 Categorized inventory (as found at planning time)

**canvodpy (65 files) — representative categories, not line-by-line:**
- Root metadata: `.zenodo.json` (2 `related_identifiers` URLs: canvodpy-demo,
  canvodpy-test-data), `CITATION.cff` (`repository-code`, `url`, 2 nested
  `references[].repository-code`/`url` for test-data/demo), `codemeta.json`,
  `.git-changelog.toml`, `REUSE.toml` (`SPDX-PackageDownloadLocation`).
- Docs config: `zensical.toml` (`site_url`, `repo_url`, `repo_name`, one
  in-page `link =`).
- Package metadata: every `packages/*/pyproject.toml` and root/`canvodpy/`
  `pyproject.toml` — `[project.urls]` blocks (`Homepage`, `Documentation`,
  `Repository`, `Issues`), plus root `pyproject.toml`'s
  `[tool.uv.sources]` git dependency URLs for `canvod-filemap`/
  `canvod-adapters` pointing at `canvodpy-extensions.git`.
- READMEs: root `README.md` + every `packages/*/README.md` +
  `canvodpy/README.md`.
- Docs prose: `docs/architecture.md`, `docs/build-system.md`,
  `docs/CONTRIBUTING.md`, `docs/FAIR_IMPLEMENTATION_SUMMARY.md`,
  `docs/guides/configuration.md`, `docs/guides/contributor-setup.md`,
  `docs/guides/DEVELOPMENT.md`, `docs/guides/extensions.md` (see below —
  cross-repo links), `docs/guides/getting-started.md`,
  `docs/guides/HOW_RELEASE_WORKS.md`, `docs/guides/OIDC_EXPLAINED.md`,
  `docs/guides/PYPI_SETUP.md`, `docs/guides/ZENODO_SETUP.md`,
  `docs/impressum.md`, `docs/index.md`, `docs/notebooks/index.md`,
  `docs/OPENSSF_BADGE_GUIDE.md`, `docs/packages/naming/overview.md`,
  `docs/principles.md`, `docs/RELEASING.md`, `docs/SECURITY.md`,
  `docs/tooling.md`, `docs/VERSIONING.md`.
- Project-level: `CHANGELOG.md`, `CLAUDE.md`, `CONTRIBUTING.md`,
  `SECURITY.md`.
- Test-data submodule's own files (only relevant if that submodule repo is
  also transferred per §2.3): `packages/canvod-readers/tests/test_data/.zenodo.json`,
  `.../CITATION.cff`, `.../README.md`.

**Concrete cross-repo doc links (`docs/guides/extensions.md`) — call out
specifically, found by direct read:**
```
Line 8:  **[github.com/nfb2021/canvodpy-extensions](https://github.com/nfb2021/canvodpy-extensions)**
Line 52: See [canvod-filemap's overview](https://nfb2021.github.io/canvodpy-extensions/packages/filemap/overview/)
Line 60: uv add "canvod-airflow[airflow] @ git+https://github.com/nfb2021/canvodpy-extensions.git#subdirectory=packages/canvod-airflow"
Line 63: See [canvod-airflow's overview](https://nfb2021.github.io/canvodpy-extensions/packages/airflow/overview/)
Line 70: uv add "canvod-adapters[store] @ git+https://github.com/nfb2021/canvodpy-extensions.git#subdirectory=packages/canvod-adapters"
Line 75: [canvod-adapters's overview](https://nfb2021.github.io/canvodpy-extensions/packages/adapters/overview/)
```
All six need `nfb2021` → `tuw-geo` in both the `github.com/...` git-URL form
and the `nfb2021.github.io/...` Pages-URL form.

**canvodpy-extensions (21 files) — representative categories:**
- Root metadata: `.zenodo.json` (`related_identifiers` → canvodpy URL),
  `CITATION.cff` (`repository-code`, `url`, nested `references[]` entry for
  canvodpy incl. its DOI which stays the same, only the URL changes),
  `.git-changelog.toml`, `REUSE.toml`.
- Docs config: `zensical.toml` (`site_url`, `repo_url`, `repo_name`, in-page
  `link =`).
- Package metadata: `packages/canvod-airflow/pyproject.toml`,
  `packages/canvod-filemap/pyproject.toml`,
  `packages/canvod-adapters/pyproject.toml`.
- READMEs: root `README.md`, `packages/canvod-airflow/README.md`,
  `packages/canvod-filemap/README.md`, `packages/canvod-adapters/README.md`.
- Docs prose: `docs/CONTRIBUTING.md`, `docs/index.md`,
  `docs/packages/adapters/overview.md`, `docs/packages/airflow/overview.md`,
  `docs/packages/filemap/overview.md`.
- Project-level: `CHANGELOG.md`, `CLAUDE.md`, `CONTRIBUTING.md`,
  `SECURITY.md`.

### 5.3 Workflow sequencing — when to open, when to merge
Follow the standing branch-protection rule for this work too: no direct
pushes to `main`, always a topic branch + PR, Nicolas merges.

1. **Before the transfer**: create a topic branch in each repo (e.g.
   `chore/org-migration-refs`) and open the PR against the *old* `nfb2021`
   URL/remote. It's fine to prepare and open this PR early — the PR itself,
   its branch, and its future merge commit are just more git history, which
   survives the transfer intact (PRs transfer with the repo per §1).
2. **Do NOT merge yet.** The PR's diff should replace `nfb2021` → `tuw-geo`
   everywhere per §5.1/§5.2 — merging it before the transfer would make the
   `main` branch's docs/config point at a `tuw-geo` URL that doesn't exist
   yet (Pages `site_url`, badge URLs, etc. would 404 temporarily).
3. **Execute the transfer** (§3).
4. **Merge the reference-cleanup PR immediately after transfer confirms.**
   Because the PR was opened against the repo before transfer, and PRs
   survive transfer, you do not need to reopen or recreate it — the existing
   PR, still open, now lives at `tuw-geo/canvodpy/pull/<n>` automatically.
   Just merge it there.
5. Note: `howfairis`/fair-software.eu always evaluates the **default branch**
   live via GitHub's API — the FAIR badge will keep showing old-URL-based
   results until this cleanup PR is actually merged to `main` post-transfer,
   not just opened.
6. Repeat this same sequencing independently for `canvodpy-extensions` (it
   is transferred second per §3.2, so its cleanup PR merges later than
   canvodpy's).

---

## 6. Local environment updates

### 6.1 Known local clones/worktrees to update
| Path | Current remote | Action |
|---|---|---|
| `/Users/work/Developer/GNSS/canvodpy-perf` | `https://github.com/nfb2021/canvodpy.git` | `git remote set-url origin https://github.com/tuw-geo/canvodpy.git` |
| `/Users/work/Developer/GNSS/canvodpy-extensions` | `git@github.com:nfb2021/canvodpy-extensions.git` | `git remote set-url origin git@github.com:tuw-geo/canvodpy-extensions.git` |
| `/Users/work/Developer/GNSS/canvodpy` (this session's primary checkout, branch `chore/icechunk-v2-upgrade`) | verify — likely also `nfb2021/canvodpy` | same as above |
| `/Users/work/Developer/GNSS/canvodpy-demo` | `nfb2021/canvodpy-demo` (submodule target) | update only if §2.3 decides to transfer this repo too |
| `/Users/work/Developer/GNSS/canvodpy-test-data` | `nfb2021/canvodpy-test-data` (submodule target) | update only if §2.3 decides to transfer this repo too |

Checked and **confirmed not affected** (no git remote or hardcoded repo URL
pointing at either migrating repo — only reference canvodpy via local
editable-install file paths in code comments, e.g.
`pip install -e /path/to/canvodpy/packages/canvod-ops`, which are
filesystem paths, not GitHub URLs, and need no change):
- `/Users/work/Developer/GNSS/canvod-streamviz` (own remote:
  `git@github.com:nfb2021/canvod-streamviz.git` — a separate personal repo,
  out of scope for this migration).
- `/Users/work/Developer/GNSS/canvod-streamstats` (own remote:
  `git@github.com:nfb2021/canvod-streamstats.git` — same, out of scope).

Any other local clone not listed above (other contributors' machines, CI
runners with cached checkouts, etc.) should run the same `git remote
set-url` pattern. GitHub's redirect makes old-URL `fetch`/`push` keep
working for a long time, but do not rely on that indefinitely (§9).

### 6.2 Submodule re-sync (only if §2.3 keeps demo/test-data under nfb2021,
or even if transferred — update `.gitmodules` either way once URLs change)
After updating `.gitmodules` in `canvodpy` (only needed if the submodule
target repos are transferred, or if you choose to point at `tuw-geo` for
consistency even without transferring them — not applicable if they stay
under `nfb2021` and you leave `.gitmodules` alone):
```bash
git submodule sync --recursive
git submodule update --init --recursive
```
Every contributor with an existing local clone must run `git submodule sync`
after `.gitmodules` URLs change — `git submodule update` alone does not pick
up a changed URL in an already-initialized submodule.

---

## 7. External service re-linking summary table

| Service | What breaks | Manual action needed | Who can do it | Urgency |
|---|---|---|---|---|
| **PyPI** (11 live `canvodpy` packages; N/A for extensions — no PyPI publish) | Next tagged release's `publish_pypi.yml`/`publish_testpypi.yml` run fails OIDC trusted-publisher check (`repository_owner_id` mismatch) | Add new trusted-publisher entry per project under `tuw-geo` owner, remove stale `nfb2021` entry (§2.4, §4.1) | Needs Nicolas's PyPI account credentials (project maintainer) — not doable via `gh`/API by an agent | **Highest** — must happen before next tag push |
| **Zenodo** (both repos + test-data submodule) | Next tagged GitHub release does NOT trigger a new Zenodo archive/DOI-version | Re-sync GitHub repo list on zenodo.org, re-toggle integration on for `tuw-geo/canvodpy` and `tuw-geo/canvodpy-extensions` (§4.2) | Needs Nicolas's Zenodo account (OAuth-linked to his GitHub identity) | **High** — before next tagged release |
| **Coveralls** (both repos) | Coverage badge stops updating; documented real-world cases of this failing silently after transfer (lemurheavy/coveralls-public#603) | Sync repos on coveralls.io, use "Change Source" button to point at the new `tuw-geo/...` location (§2.6, §4-adjacent) | Needs Nicolas's Coveralls account (GitHub OAuth) | **Medium-high** — coverage reporting on the next PR/push will otherwise silently stop |
| **GitHub Pages** (both repos) | URL changes from `nfb2021.github.io/...` to `tuw-geo.github.io/...`; Pages config *should* carry over automatically but must be verified | Verify via `gh api repos/tuw-geo/<repo>/pages`; re-enable via `gh api -X POST .../pages -f "source[branch]=gh-pages" -f "source[path]=/"` if needed (§4.3) | Doable via `gh api` by an agent/Nicolas — no special account needed beyond repo admin | **Medium** — same day, but not release-blocking |
| **OpenSSF Scorecard** | Badge/scorecard.dev URL references old `owner/repo` string; live workflow re-keys automatically since it uses `github.repository` context | Update any hardcoded badge URLs in docs (part of §5 cleanup PR); no service-side re-registration needed | Doable via PR by Nicolas or an agent | **Low** — cosmetic until next Scorecard run, which self-corrects |
| **FAIR-software.eu / howfairis** | Badge URL hardcodes `github.com/nfb2021/...`; badge won't reflect corrected URL until reference-cleanup PR is merged to the new default branch | Update badge URL in README/docs (§5 cleanup PR); no separate service action | Doable via PR by Nicolas or an agent | **Low** — cosmetic, self-corrects once PR merges |
| **REUSE/SPDX** | `REUSE.toml`'s `SPDX-PackageDownloadLocation` field is stale but not functionally load-bearing for REUSE compliance checks | Update the URL string in `REUSE.toml` (§5 cleanup PR) | Doable via PR by Nicolas or an agent | **Low** — no compliance-checker breakage, just metadata hygiene |
| **Dependabot** | Nothing repo-side breaks (config is repo-relative); only risk is an org-wide policy disabling it | Verify org allows Dependabot (§2.2, §4.5) — no repo-level edit needed | Needs an org owner if org policy needs changing; otherwise just verification | **Low-medium** — verify same day, act only if blocked |

---

## 8. Verification checklist (migration fully complete)

Run through all of these before considering the migration done:

1. [ ] `gh repo view tuw-geo/canvodpy` and `gh repo view tuw-geo/canvodpy-extensions`
       both resolve, show correct visibility/description.
2. [ ] Old-URL redirect still works:
       `git ls-remote https://github.com/nfb2021/canvodpy.git` succeeds
       (redirected) — expected to keep working long-term barring namespace
       reuse (§9).
3. [ ] A fresh clone from the new URL succeeds and passes the full check
       suite:
       ```bash
       git clone --recurse-submodules https://github.com/tuw-geo/canvodpy.git /tmp/canvodpy-verify
       cd /tmp/canvodpy-verify && uv sync && just check && just test
       ```
4. [ ] A test PR opened against `tuw-geo/canvodpy`'s `main` shows all four
       required status checks (`lock_file`, `linting`, `formatting`,
       `test_coverage`) running and passing/gating merge as before (§4.4).
5. [ ] `https://tuw-geo.github.io/canvodpy/` and
       `https://tuw-geo.github.io/canvodpy-extensions/` both resolve and
       show current docs content (post reference-cleanup-PR merge).
6. [ ] A manual `workflow_dispatch` run of `publish_pypi.yml` (or a real
       beta tag through `publish_testpypi.yml`) succeeds without an
       OIDC `invalid-publisher` error, for at least one representative
       package.
7. [ ] Coveralls badge on the new repo's README shows a recent, passing
       build (not stale from before the transfer).
8. [ ] A test release (or the next real tagged release) on `tuw-geo/canvodpy`
       produces a new Zenodo version DOI under the existing concept DOI
       `10.5281/zenodo.18496233` (confirms Zenodo integration re-toggle
       worked).
9. [ ] All items in the `grep -rl "nfb2021" ...` re-run (§5.1) return **zero
       results** in both repos' default branches (excluding intentionally
       historical references, e.g. old CHANGELOG entries describing past
       state, which are fine to leave as-is).
10. [ ] `just check` and `just test` (or each repo's equivalent) are green
        from the fresh clone in step 3, confirming no silent breakage from
        URL changes in config/tooling.
11. [ ] Submodule pointers resolve correctly if `canvodpy-demo`/
        `canvodpy-test-data` were also transferred and `.gitmodules` updated:
        `git submodule status` shows no errors after `git submodule sync &&
        git submodule update --init --recursive` on a fresh clone.

---

## 9. Known risks / things that can't be undone

1. **Namespace reuse risk (only real long-term risk):** if anyone (including
   Nicolas) ever creates a new repo at `nfb2021/canvodpy` or
   `nfb2021/canvodpy-extensions` in the future, GitHub's automatic redirect
   from the old namestring breaks immediately and permanently for the
   *original* transferred repo — old links, old `pip install git+https://...`
   pins in someone else's frozen requirements file, old DOI-linked
   `related_identifiers` URLs (if not cleaned up per §5), etc. would all
   point at the wrong (new, unrelated) repo instead of erroring cleanly.
   Mitigation: don't reuse the old namestring; complete the reference-cleanup
   PR (§5) so first-party docs/metadata don't depend on the redirect at all.
2. **Zenodo DOIs are permanent and unaffected — not a risk, included here
   only to close the loop on user-facing worry:** `10.5281/zenodo.18496233`,
   `10.5281/zenodo.21359005`/`21359006`, `10.5281/zenodo.19708759` and their
   archived zip snapshots remain valid and resolvable forever, regardless of
   what happens to the GitHub repos going forward. This is Zenodo's own
   guarantee, independent of GitHub-integration toggle state.
3. **Org-level policy differences are a real, not-fully-predictable risk**:
   `TUW-GEO` is a long-established, active org (91 public repos, 43 seats,
   created 2013) with its own security/Actions/Dependabot baseline that may
   differ from what a personal account allows by default. Anything the
   personal account currently permits silently (e.g., a permissive Actions
   setting, an unrestricted secret-scanning bypass) could start being blocked
   post-transfer with no advance warning — this is why §2.2's pre-flight org
   policy check and §4.5's post-transfer verification both exist as explicit
   steps rather than assumptions.
4. **PyPI trusted-publisher misconfiguration has a hard failure mode, not a
   silent one**: if §2.4/§4.1 isn't done before the next tag push, the
   publish workflow fails outright (it does not fall back to publishing
   under the old identity, and it does not silently no-op) — this blocks a
   release until fixed, but does not corrupt anything already published.
   Recoverable, just release-blocking until addressed.
5. **Coveralls has a documented history of not cleanly following transfers**
   (real GitHub issue: lemurheavy/coveralls-public#603, "Coveralls does no
   longer work after transferring a repository") — treat the "Change
   Source" button fix (§2.6) as the documented workaround, but budget time
   for it not working on the first try and needing Coveralls support
   involvement.
6. **Org-owner approval dependency**: because Nicolas currently holds
   "member" (not "owner") role in `TUW-GEO` (confirmed via API, §2.1), the
   transfer's completion depends on a *different person's* action (an
   existing org owner approving, or promoting Nicolas first). This is not
   something Nicolas can unilaterally push through with only his own
   credentials — plan the timing of the transfer around that person's
   availability, not just Nicolas's own schedule.
7. **Not genuinely irreversible, but worth flagging**: a repo can be
   transferred *back* to a personal account later if needed (same mechanism,
   reverse direction) — this migration is not a one-way door in the way a
   repo deletion or a fresh-recreation approach would be. The redirect and
   history-preservation properties described in §1 apply symmetrically to a
   hypothetical future reverse transfer.

---

## Sources consulted

- GitHub Docs — Transferring a repository:
  https://docs.github.com/en/repositories/creating-and-managing-repositories/transferring-a-repository
- `gh` CLI — no dedicated transfer subcommand (feature request, unimplemented):
  https://github.com/cli/cli/issues/5292
- GitHub REST API — repo transfer endpoint via `gh api`:
  `gh api -X POST repos/{owner}/{repo}/transfer -f new_owner="..."`
- PyPI Docs — Trusted publisher troubleshooting (repository_owner_id,
  rename/transfer mismatch behavior):
  https://docs.pypi.org/trusted-publishers/troubleshooting/
- PyPI Docs — Adding a trusted publisher (per-project "Publishing" tab flow):
  https://docs.pypi.org/trusted-publishers/adding-a-publisher/
- Zenodo Docs — GitHub integration, enabling a repository:
  https://help.zenodo.org/docs/github/enable-repository/,
  https://help.zenodo.org/docs/github/
- Coveralls — documented transfer breakage and "Change Source" fix:
  https://github.com/lemurheavy/coveralls-public/issues/603
- Local ground truth verified directly (this session): `.gitmodules`,
  `.zenodo.json`, `CITATION.cff`, `zensical.toml`, `REUSE.toml`,
  `docs/guides/extensions.md`, all `.github/workflows/*.yml`, all
  `packages/*/pyproject.toml` in both repos; `gh api` calls against
  `orgs/tuw-geo`, `orgs/tuw-geo/memberships/nfb2021`,
  `repos/nfb2021/canvodpy(-extensions)/pages`,
  `repos/nfb2021/canvodpy/branches/main/protection`; PyPI project existence
  via `pypi.org/pypi/<name>/json` HTTP status checks.

## Explicitly flagged as "verify manually" (not confirmed with full
confidence during this planning pass)

- Whether PyPI's "Publishing" tab has grown an in-place edit affordance for
  an existing trusted publisher's owner field, vs. requiring delete +
  recreate (§2.4 step 3, §2.4 step 5).
- Whether a `COVERALLS_REPO_TOKEN` (or similarly named) secret exists in
  either repo's Actions secrets beyond what's visible in the workflow file
  itself (§2.6).
- Whether Zenodo's GitHub-integration toggle reliably "sticks" for a
  freshly-transferred org repo on the first attempt, given at least one
  documented case of it not persisting after refresh (§4.2 step 5).
- Whether `TUW-GEO`'s org-level policy currently restricts incoming repo
  transfers or requires a specific approval flow beyond standard
  owner-approval (§2.1, §2.2) — only an existing org owner can see this
  setting; not visible via the API calls run during this planning pass.
