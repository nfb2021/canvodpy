# Distribution & Packaging Plan: `brew install` / one-liner for canvodpy

Planning doc started 2026-07-09. Not yet executed — no code/formula/script written.
Goal: canvodpy is maturing into a terminal-first program; make it installable with
a single command on both macOS (Homebrew) and Linux, without asking users to think
about Python packaging at all.

## Prerequisite, found 2026-07-09: canvodpy cannot run outside a git checkout today

Before any distribution channel (uv tool install, Homebrew, AppImage, whatever)
matters, canvodpy needs to actually work when invoked from an arbitrary
directory with no monorepo checkout present. Checked the actual code — it
currently does not, confirmed via three call sites, not a hunch:

**1. `canvodpy config init` — the first command a new user runs — cannot work
at all outside a git checkout, confirmed by reading the code.** In
`canvodpy/src/canvodpy/cli/config.py::init`, the YAML templates it copies
(`canvod-settings.yaml.example`, `recipes/*.yaml`) are read from
`template_dir = monorepo_root / "config"` (or, if no monorepo root is found, a
`Path(__file__)`-relative fallback that lands inside site-packages and won't
contain a `config/` dir either). If neither resolves, the command prints
`"Template directory not found... Make sure you're running from the
repository root."` and exits 1. **The templates are not bundled as package
data in the wheel** — they only exist in the monorepo's `config/` directory on
disk. So `uv tool install canvodpy && canvodpy config init` from any directory
without a canvodpy git checkout fails outright today.

**2. Default config *directory* discovery is monorepo/CWD-based, not
XDG/user-based.** `canvod-utils/src/canvod/utils/config/loader.py::find_monorepo_root()`
walks up from `Path.cwd()` looking for a `.git` entry; `ConfigLoader.__init__`
falls back to `Path.cwd() / "config"` if that fails. `canvodpy/cli/config.py`
independently re-implements the same "find monorepo root, else cwd()/config"
logic at module-import time to compute `DEFAULT_CONFIG_DIR`, which every
`config` subcommand (`init`, `validate`, `show`, `edit`) and `stats` subcommand
default to. Three separate copies of the same fallback logic, none of which
default to a user-level location like `~/.config/canvodpy/` — meaning a
globally-installed CLI invoked from, say, a data directory, always ends up
looking for `./config/` right there unless the user explicitly passes
`--config-dir`/`-c` or sets `CANVOD_CONFIG_DIR` (both already exist as
overrides — the mechanism is there, just the *default* is wrong for a
standalone install).

**3. `dashboard.py`'s "TUI" is already just `rich.Live`-based progress
reporting** (`RichReporter`/`PlainReporter` classes) — not a separate
interactive TUI framework (no `textual`, no curses). Confirmed this is already
part of "the CLI," not a missing piece — no new TUI work needed, this finding
is just to close out that question.

**What's actually needed for "proper CLI, callable from anywhere":**
1. Bundle `canvod-settings.yaml.example` + `recipes/*.yaml` as real package
   data inside the wheel (e.g. under `canvodpy/data/config-templates/`, wired
   into the build backend's include rules) so `config init` works regardless
   of install method or invocation directory. This is the actual blocker —
   everything else is secondary until this is fixed.
2. Change the *default* config directory to an XDG-style user location
   (`$XDG_CONFIG_HOME/canvodpy` / `~/.config/canvodpy` fallback), keeping the
   existing `--config-dir`/`CANVOD_CONFIG_DIR` overrides as-is.
3. Consolidate the three duplicated "find monorepo root, else cwd"
   implementations into one shared helper; its role should shift from "the
   primary lookup" to "a dev-mode convenience when running from within a
   canvodpy checkout," with the XDG path as the real default otherwise.
4. Install with `uv tool install canvodpy` (not `uv add canvodpy`) — `uv add`
   only makes it available via `uv run canvodpy` from within that specific
   project's venv; `uv tool install` creates an isolated env with a `PATH`
   shim, which is the actual mechanism for "callable from any directory."
   Pair with `uv tool update-shell` to make sure the shim directory
   (`~/.local/bin` by default) is actually on `PATH`.
5. Minor polish, already free: Typer auto-provides
   `canvodpy --install-completion` for shell completion; no work needed there.

Not yet implemented — items 1–3 are real code changes in `canvodpy-perf`
(`canvod-utils/config`, `canvodpy/cli/config.py`), not documentation or
packaging config. Item 1 is the one that actually blocks first-run today.

## Current state (verified)

- `canvodpy` already has a real console-script entry point: `canvodpy = "canvodpy.cli.app:main"`
  (Typer-based, `canvodpy/pyproject.toml:65-66`). `canvod-preflight` has its own
  script too (`canvod-preflight = "canvod.preflight.cli:app"`).
- `canvodpy` is already published to PyPI (v0.3.0) — `pip install canvodpy` /
  `uv tool install canvodpy` work **today**, no new packaging work required for
  those.
- No existing Homebrew formula, tap, curl installer, or Linux distro packaging
  (checked for brew/homebrew, conda-forge, nix, snap, flatpak, deb, AUR —
  none found; only dev-tool install docs like `brew install uv`/`brew install just`).
- Dependency tree is heavy: canvodpy's umbrella package pulls in 11 internal
  workspace packages plus xarray/dask/zarr/icechunk/duckdb/pyarrow/altair/matplotlib
  etc. Relevant because Homebrew's resource-pinning approach builds dependencies
  from source (sdist), and icechunk (Rust/PyO3) + duckdb (C++) do not have a
  trivial from-source build path in a sandboxed formula install — **confirmed**,
  see "Confirmed: icechunk/duckdb break the Homebrew resource-pinning route" below.

## Reference example: `npikall/homebrew-tap`

Real, working example of a pure-Python Homebrew formula (`Formula/tiss-cli.rb`),
likely a TU Wien colleague's tap. Uses the classic pattern:

```ruby
resource "pydantic" do
  url "https://files.pythonhosted.org/packages/.../pydantic-2.13.4.tar.gz"
  sha256 "..."
end
# ...one resource block per transitive dependency

def install
  virtualenv_install_with_resources
end
```

Crucially, they automate the maintenance burden via `scripts/update-formulas.sh` +
a `workflow_dispatch` GitHub Action (`.github/workflows/update-formulas.yml`) that
queries the PyPI JSON API for the latest version/sha256 and calls out to
`brew update-python-resources` (official Homebrew maintainer tooling) to
regenerate every resource block, then auto-commits. This solves the "100+
resources to babysit by hand" problem — it's automatable with blessed tooling,
not bespoke/fragile.

A tap for canvodpy (e.g. `nfb2021/homebrew-canvodpy`) is a small, well-trodden
lift **for the macOS/Homebrew side** — but see "Confirmed: icechunk/duckdb break
the Homebrew resource-pinning route" below for the one real, now-verified risk.

## The Linux one-liner (this doc's primary ask)

Requirement: **one command, and afterwards `canvodpy` is installed and
invocable** — same UX as `brew install canvodpy` on macOS. Not a distro package,
not "add a repo then install" — one line, done.

### Recommended approach: hosted `install.sh`, piped from curl

This is the same pattern `uv`, `rustup`, `nvm`, and Homebrew's own installer use:

```bash
curl -fsSL https://nfb2021.github.io/canvodpy/install.sh | sh
```

Since canvodpy is pure Python (no compiled binary to fetch per-platform), the
script's job isn't "download a binary" — it's "ensure a suitable installer
exists, then delegate to it":

1. Check for `uv`; if missing, bootstrap it via uv's own official installer
   (`curl -LsSf https://astral.sh/uv/install.sh | sh`) — uv can also manage its
   own Python version, so no system Python dependency either.
2. Run `uv tool install canvodpy` — this is uv's built-in equivalent of `pipx`:
   isolated venv per tool, binary shim installed, no resource-pinning tax at all
   (resolves from PyPI/wheels directly, no sdist-build-from-scratch step like
   Homebrew's model — sidesteps the icechunk/duckdb risk entirely).
3. Handle PATH: `uv tool install` puts shims in `~/.local/bin` by default and
   will warn if that's not on `PATH`. The installer script should either call
   `uv tool update-shell` (adds the necessary line to the user's shell rc) or
   print an explicit one-line instruction to add it, mirroring how `uv`'s and
   `rustup`'s own installers end with "restart your terminal" / "run `source
   ...`".

End state: **one command**, works on any Linux distro (no distro-specific
packaging), and — since none of this is Linux-specific — **the exact same
script also works unmodified on macOS**, making the curl one-liner a
cross-platform baseline that the Homebrew tap sits *on top of* as a nicer
UX for people who already use `brew`, not a strict requirement.

### Where to host `install.sh`

Candidates: GitHub Pages via the existing Zensical docs site
(`nfb2021.github.io/canvodpy/install.sh`, just drop a static file into `docs/`),
or `raw.githubusercontent.com/nfb2021/canvodpy/main/install.sh` directly. Prefer
the docs-site path — shorter, brandable URL, no `raw.githubusercontent.com` in
user-facing instructions.

### Alternative considered: Homebrew-on-Linux (Linuxbrew)

If a canvodpy tap exists, `brew install nfb2021/canvodpy/canvodpy` (note: no
separate `brew tap` step needed — the `user/tap/formula` form is itself a
single line) works identically on Linux, since Homebrew runs on Linux too. Good
complementary option for users who already have brew, but not universal —
plenty of Linux users/servers/containers don't have brew installed and won't
want to bootstrap it just for one CLI. The curl `install.sh` route has no such
prerequisite and should be the primary documented method; the brew tap is an
equally-valid *alternative* for both platforms, not Linux-specific.

### Alternative considered: Nix one-liner

`nix profile install github:nfb2021/canvodpy` is also a genuine one-liner for
users with Nix installed, cross-platform, and popular in the same
reproducible-science/HPC circles canvodpy's users likely overlap with. Lower
priority than the curl script (smaller install base, and would need a
`flake.nix` authored and maintained), but worth revisiting once the curl/uv
route is live, as a "if you already have Nix" fast path.

## UX preference: package-manager verb+noun, not curl-pipe-to-shell

2026-07-09: user feedback — `curl -fsSL https://.../install.sh | sh` reads
ugly; wants a clean `<tool> install canvodpy` style command, name-checking
`flatpak install canvodpy` / `brew install canvodpy` as the desired shape.

**`pipx install canvodpy` already gives exactly this, today, with zero new
infrastructure** — canvodpy is already on PyPI, so this works right now. Same
for `uv tool install canvodpy`. Neither needs a hosted script, a tap, or any
work on our side. This should be the headline command in install docs, not the
curl one-liner — the curl script was only ever needed to handle the case where
the user has *neither* pipx/uv installed yet; if `pipx`/`uv` presence can be
assumed or trivially prompted for, the raw `pipx install canvodpy` is strictly
cleaner and matches the requested aesthetic exactly.

**Flatpak — evaluated, likely a poor fit, not just a syntax choice.** Flatpak
targets desktop/GUI apps distributed via Flathub with a sandboxed runtime
(bubblewrap). Concerns for a filesystem-heavy scientific CLI:
- Sandboxed filesystem access by default — a GNSS data-processing tool that
  needs to read arbitrary data directories would need `--filesystem=host`
  grants, undercutting the sandboxing model's point.
- Invocation is `flatpak run io.github.nfb2021.canvodpy`, not a bare `canvodpy`
  on `PATH` — Flatpak doesn't export a plain shell binary by default, which
  matters for scripting/piping and generally for "terminal-first" positioning.
- Flathub publishing needs a reverse-DNS app ID, AppStream metainfo XML, and a
  review process — real overhead for a niche research CLI with a small
  audience.
- Not independently verified whether `flatpak-pip-generator` (the Flatpak
  equivalent of `update-python-resources`) has the same sdist-only bias as
  Homebrew's tooling — worth checking if Flatpak is pursued regardless, but the
  sandboxing/PATH concerns above are reason enough to deprioritize it
  regardless of that answer.

**conda-forge — not yet in this doc, now worth elevating.** Given the
dependency stack (xarray/dask/zarr/duckdb/icechunk), conda-forge may be the
*technically best-suited* "clean install" channel, not just an aesthetic match:
- `conda install -c conda-forge canvodpy` / `mamba install canvodpy` is exactly
  the requested verb+noun shape.
- conda-forge feedstocks build actual prebuilt binary conda packages via their
  own CI (not on the user's machine) — icechunk and duckdb already have
  conda-forge feedstocks with proper per-platform binaries, so the whole
  sdist-vs-wheel compilation problem that blocks the Homebrew route doesn't
  apply here at all.
- The target audience (xarray/dask/zarr users) is disproportionately
  conda-native already, arguably more so than pip/uv-only users.
- Cost: authoring and maintaining a conda-forge feedstock (recipe/meta.yaml,
  going through conda-forge's staged-recipes review once, then bot-driven
  version bumps after that) — a real one-time setup cost, but conda-forge's
  bump automation is mature and low-maintenance long-term, arguably less
  ongoing toil than the Homebrew tap's resource-regeneration workflow.

**Revised verdict:** lead with `pipx install canvodpy` (zero-cost, exactly the
requested UX, works today) as the primary documented install method. Treat
conda-forge as the strongest *additional* "polished package manager" channel
given the dependency stack — better technical fit than Homebrew for the
compiled deps, and better audience fit than Flatpak. Keep the Homebrew tap as a
secondary option for brew users specifically (with the known icechunk/duckdb
workaround). Deprioritize Flatpak — poor fit for a filesystem-heavy terminal
CLI regardless of packaging mechanics. The curl `install.sh` idea is no longer
the recommended default; it only adds value as a fallback for users who refuse
to install pipx/uv themselves, which is a small and shrinking population.

## Pivot: reject Python-ecosystem tooling entirely — ship a real standalone binary

2026-07-09: user feedback — "no conda, no pip ideally. this is from the last
decade." Rejects `pipx`/`uv tool install`/`conda install` as the *user-facing*
verb, not just curl-pipe syntax. The ask is for canvodpy to feel like a
compiled, native tool (`brew install X`, `flatpak install X`), not "a Python
script installed by a Python installer with extra steps."

**Reframe: this doesn't have to be a Python-packaging problem at all.** Every
option discussed so far (pipx, uv, conda-forge, Homebrew resource-pinning,
Flatpak's pip generator) works at the *Python dependency* layer — resolving
and installing `.whl`/`.tar.gz` files. The alternative is to stop distributing
canvodpy as a Python package and instead build a genuine **standalone
executable** that bundles the interpreter and all dependencies into one
artifact, using a tool like:

- **PyInstaller** — most mature/widely used, produces a single-file or
  single-directory bundle per platform.
- **Nuitka** — compiles Python to C, arguably a better fit for "not from the
  last decade" positioning since it's an actual compiler, not just a bundler.
- **PyOxidizer** — Rust-based bundler, produces a single static-ish binary.

This is exactly how tools like `yt-dlp` ship a no-Python-required binary
alongside their PyPI package. Once built, the artifact is a real compiled-feeling
executable — this changes the packaging story completely:

- **Kills the Homebrew icechunk/duckdb sdist-build problem outright.** The
  formula would no longer resolve or build any Python dependency at all — it
  would just download the prebuilt binary and place it in `bin/` (`bin.install
  "canvodpy"`), the same as any Homebrew formula for a compiled Go/Rust tool
  (see `gotpm.rb`/`go-typstwatch.rb` in the `npikall/homebrew-tap` reference —
  binary-download formulas are trivial, no `resource` blocks, no build step).
  `brew install canvodpy` becomes genuinely simple.
- **Linux gets a real "modern, no package manager" answer: AppImage.** A
  single portable executable file — `chmod +x canvodpy.AppImage && ./canvodpy`
  or place it on `PATH` — no installation step, no sandboxing model fighting
  filesystem access (unlike Flatpak), no distro-specific packaging. This is
  the standalone-binary distribution format most associated with "current"
  Linux tooling, not legacy package managers.
- Also unlocks a genuinely trivial curl-based Linux one-liner *without*
  needing to bootstrap uv/pipx at all: `curl -L .../canvodpy-linux-x86_64 -o
  ~/.local/bin/canvodpy && chmod +x ~/.local/bin/canvodpy` — fetching a real
  binary, not bootstrapping a Python tool. (Still not as clean as `brew
  install`/AppImage, but notably simpler than the earlier uv-bootstrap script
  since there's nothing left to install *except* the binary itself.)

**Open questions / unknowns — not yet verified, need a feasibility spike
before committing:**
- Whether PyInstaller/Nuitka can successfully bundle the full scientific stack
  (xarray, dask, zarr, icechunk [Rust/PyO3], duckdb [C++], pyarrow, altair,
  matplotlib) without missing hidden imports or data files. Compiled-extension
  packages (icechunk, duckdb) should bundle cleanly since PyInstaller/Nuitka
  vendor the already-compiled `.so` files rather than rebuilding them from
  source — this is a materially different (and easier) problem than the
  Homebrew sdist issue. But packages like pyarrow/matplotlib have known
  PyInstaller quirks (hidden imports, hooks) that need testing, not assuming.
- Expected binary size — a full scientific Python stack bundled standalone is
  realistically several hundred MB. Fine for a one-time download, but worth
  setting expectations.
- Cannot cross-compile: needs a real CI build matrix (macOS arm64, macOS
  x86_64, Linux x86_64, Linux aarch64), each building on genuine runners for
  that platform/arch, since the bundle embeds a real interpreter and compiled
  extensions. More CI work than any of the previous options, but it's a
  one-time build pipeline, not per-user friction.
- Startup time — bundled Python executables (esp. PyInstaller one-file mode)
  can have a noticeable unpack/startup delay; worth benchmarking against a
  regular `python -m canvodpy` invocation before committing to one-file vs.
  one-directory bundling.

**Revised verdict:** this is a bigger one-time engineering investment than any
option previously discussed (real CI build matrix, per-platform binary
testing), but it is the only option that actually satisfies "feels like a
compiled tool, not Python tooling wearing a costume" *and* it independently
solves the Homebrew build-from-source problem as a side effect. Recommend a
small feasibility spike first — build one PyInstaller (or Nuitka) bundle
locally for the current platform, confirm the full dependency stack imports
and runs correctly from the frozen bundle, and measure size/startup time —
before committing to the CI matrix and rewriting the Homebrew formula and
Linux distribution story around it.

### Linux specifically: `python-appimage` is the easiest win of all the options above

2026-07-09, verified via `gh repo view`/`gh api` against
`niess/python-appimage` (real, actively used — other projects list it as a
dependency; base runtimes rebuilt weekly): this is **not** the same category of
tool as PyInstaller/Nuitka, and that's exactly why it's lower-risk for Linux
specifically:

- It does **not** freeze/analyze imports the way PyInstaller does (which is
  where PyInstaller's hidden-import/missing-data-file quirks come from).
  Instead it extracts a relocatable Python runtime from a **manylinux** Docker
  image, then does a completely normal `pip install` of the target package
  into that runtime, then wraps the whole relocatable environment as a single
  AppImage file. Since it's a real pip install (not an import-graph guess), it
  installs prebuilt manylinux **wheels** exactly the same way a plain `pip
  install canvodpy` would today.
- Checked a real example recipe (`applications/scipy/requirements.txt` in that
  repo): just `numpy`, `pandas`, `scipy`, `sympy`, `matplotlib`, `ipython` —
  i.e. a heavy, compiled-extension-laden scientific stack already works with
  this tool, published and maintained. A canvodpy recipe would likewise just
  be a `requirements.txt` containing `canvodpy` — no freezing, no hidden-import
  risk, no data-file guesswork.
- Since icechunk/duckdb already publish `manylinux_2_17`/`manylinux_2_28`
  wheels (confirmed earlier in this doc), they install into the AppImage's
  python-appimage runtime exactly as easily as they install via plain `pip`
  today — no compilation, no Homebrew-style sdist problem, no PyInstaller
  hidden-import risk.
- Only real unknown left: whether the specific python-appimage base-runtime's
  manylinux/glibc version is new enough to satisfy icechunk's `manylinux_2_28`
  aarch64 wheel tag (x86_64 only needs `manylinux_2_17`, an older/safer
  baseline). Worth a direct test, not a blocker in principle since runtimes
  are rebuilt weekly and manylinux tags are designed to be forward-compatible
  with newer base images.

**So: yes, AppImage-via-`python-appimage` is the easiest win of everything
discussed in this doc** — Linux has no macOS-style mandatory code-signing/
notarization gate, the tool sidesteps PyInstaller's fragile import-freezing
entirely by doing a real pip install of existing wheels, and a single x86_64
build already covers the large majority of Linux users. The macOS side (for
the Homebrew tap) still needs the PyInstaller/Nuitka feasibility spike, since
there's no equivalent "manylinux-style relocatable runtime + plain pip
install" tool for macOS used here — that remains the harder half of the pivot.

## Installation procedure, assuming `canvodpy-x86_64.AppImage` already exists

2026-07-09. Question asked directly: given a built and published AppImage
(e.g. attached to a GitHub Release), what does the user actually run? Three
tiers, from zero-dependency to nicest UX:

### Tier 0 — plain download, works today, no AppImage-specific tooling needed

```bash
curl -L -o ~/.local/bin/canvodpy \
  https://github.com/nfb2021/canvodpy/releases/latest/download/canvodpy-x86_64.AppImage \
  && chmod +x ~/.local/bin/canvodpy
```

One line, no `sudo`, no package manager, no submission/catalog process — just
fetching a file and marking it executable. `canvodpy --help` works immediately
afterward, assuming `~/.local/bin` is on `PATH` (true by default on most
current distros — Ubuntu/Fedora auto-add it if the directory exists at login;
worth a `PATH` check/fallback message in docs for distros that don't).

**Known AppImage gotcha to test for:** many AppImages need `libfuse2` to
self-mount at runtime, and several modern distros (Ubuntu 22.04+, current
Fedora) no longer ship it by default — the classic failure is
`dlopen(): error loading libfuse.so.2`. Newer `appimagetool` runtimes support
`--appimage-extract-and-run` as a FUSE-less fallback; worth confirming our
build uses a runtime that either auto-falls-back or documenting the flag /
`apt install libfuse2` explicitly so this doesn't surprise first-time users.

### Tier 1 — `am`/`AppMan` (AppImage Manager), zero-submission via the `-e` flag

Verified via `gh api` against `ivan-hc/AM` (real, actively maintained — "apt
for AppImages", curated database inspired by AUR). Its `-e`/`extra` command
installs **directly from a GitHub repo, bypassing the curated database
entirely** — no submission/review needed:

```bash
am -e nfb2021/canvodpy canvodpy       # root-managed system install
# or, no root needed:
appman -e nfb2021/canvodpy canvodpy   # AppMan = user-local variant of AM
```

This gives real `<tool> install <name>`-shaped UX (closer to `brew install`
than Tier 0's raw curl), with update/uninstall management (`am -u`, `am -r`,
etc.) for free — but requires the user to have `am`/`appman` installed first,
itself a one-time bootstrap:

```bash
curl -s -Lo ./AM-INSTALLER https://raw.githubusercontent.com/ivan-hc/AM/main/AM-INSTALLER \
  && chmod a+x ./AM-INSTALLER && ./AM-INSTALLER && rm ./AM-INSTALLER
```

(interactive; choose "1" for `am` (root) or "2" for `appman` (no root))

Net effect: two commands total for a user who doesn't have `am` yet (bootstrap
am, then `am -e nfb2021/canvodpy canvodpy`), one command for a user who already
does. Reasonable secondary path to document, not the day-one requirement.

### Tier 2 — submit to AM's curated catalog (later, optional polish)

Once canvodpy is listed in AM's community database
(`portable-linux-apps.github.io/apps`, PR-based submission, review process —
same shape as AUR/homebrew-core), plain `am -i canvodpy` works without the
`-e user/project` GitHub-pointer syntax, and canvodpy becomes discoverable via
`am` search/listing. Nice-to-have once the AppImage is stable and published;
not a blocker for Tier 0/1 to work today.

**Recommendation:** document Tier 0 as the primary install instruction (works
immediately, zero new dependency for the user), mention Tier 1 as the nicer
"package manager" alternative for users who want update/uninstall management,
and revisit Tier 2 once the AppImage has shipped a few releases and proven
stable.

## Proposed shape — SUPERSEDED by the pivot above; kept for history

The pipx/conda-forge/Homebrew ordering below was the plan before the
"no conda, no pip" feedback. It's superseded by the standalone-binary pivot:
if the feasibility spike (PyInstaller/Nuitka bundling the full stack) succeeds,
the plan becomes binary-first (spike → CI build matrix → simple binary-download
Homebrew formula → AppImage for Linux), and pipx/conda-forge become fallback
mentions in the docs rather than the headline install method. If the spike
fails or proves impractical (e.g. bundle size/startup time unacceptable, or a
dependency genuinely won't freeze), fall back to this ordering instead.

1. Document `pipx install canvodpy` as the primary, canonical install command
   in the README (top) and `docs/guides/getting-started.md` — works today, no
   new infra, exactly the requested verb+noun UX. Mention `uv tool install
   canvodpy` as the equivalent alternative for uv users.
2. Conda-forge feedstake for `canvodpy` (`conda install -c conda-forge
   canvodpy` / `mamba install canvodpy`) — go through conda-forge
   staged-recipes once; best technical fit for the compiled deps (icechunk/
   duckdb already have conda-forge feedstocks with prebuilt binaries) and best
   audience fit given xarray/dask/zarr users skew conda-native.
3. Homebrew tap (`nfb2021/homebrew-canvodpy`) as a secondary macOS/Linuxbrew
   path, using `npikall/homebrew-tap`'s `tiss-cli.rb` +
   `update-formulas.sh`/`update-formulas.yml` automation as the template for
   the pure-Python resources — with icechunk/duckdb requiring the
   hand-authored mitigation described above (confirmed necessary, not just
   possible).
4. Flatpak: deprioritized — sandboxing model and lack of a plain `PATH` binary
   are a poor fit for a filesystem-heavy terminal CLI, independent of the
   packaging mechanics.
5. `install.sh` / curl one-liner: demoted from primary to optional fallback
   for users without pipx/uv and unwilling to install either — no longer the
   headline recommendation.

## Next step

Feasibility spike: build a PyInstaller (or Nuitka) bundle of canvodpy locally,
confirm the full scientific dependency stack (xarray, dask, zarr, icechunk,
duckdb, pyarrow, altair, matplotlib) imports and runs from the frozen bundle,
and measure resulting binary size and startup time. Not yet started — awaiting
go-ahead.

## Confirmed: icechunk/duckdb break the Homebrew resource-pinning route

Researched 2026-07-09 — this was flagged as a risk to verify; it's now confirmed,
not hypothetical.

**Homebrew's own resolution logic always prefers sdist.** Checked
`Library/Homebrew/utils/pypi.rb` (source of `brew update-python-resources`)
directly on GitHub:

```ruby
dist = json["urls"].find { |url| url["packagetype"] == "sdist" }
# If there isn't an sdist, we use the first pure Python3 or universal wheel
if dist.nil?
  dist = json["urls"].find { |url| url["filename"].match?("[.-]py3[^-]*-none-any.whl$") }
end
```

It never falls back to a platform-specific wheel (`cp312-abi3-macosx_...whl` etc.)
— only sdist, or a universal `py3-none-any.whl` if no sdist exists at all. Makes
sense architecturally: a single Homebrew formula/resource has one URL+sha256 and
must work across every platform Homebrew supports, so a platform-pinned wheel
isn't a valid default; sdist is the only universally-applicable choice.

**Both icechunk and duckdb publish an sdist on PyPI**, so `brew
update-python-resources` / `homebrew-pypi-poet` will pin to it, forcing a
from-source native build at `brew install` time:

- **icechunk 2.1.1 sdist** (`icechunk-2.1.1.tar.gz`) — verified its
  `pyproject.toml`: `build-backend = "maturin"`, and the tarball contains a
  multi-crate Rust workspace (`Cargo.toml` at the root plus
  `icechunk/`, `icechunk-arrow-object-store/`, `icechunk-format/`,
  `icechunk-macros/`). Building requires a full Rust toolchain (rustc/cargo) —
  not something the tiss-cli-style formula needs, since none of its
  dependencies had compiled extensions.
- **duckdb 1.5.4 sdist** (`duckdb-1.5.4.tar.gz`, 18 MB compressed, 6134 files) —
  verified its `pyproject.toml`: `build-backend =
  "duckdb_packaging.build_backend"`, requires `scikit-build-core` (CMake) +
  `pybind11`. The tarball vendors the entire amalgamated DuckDB C++ engine
  source tree (`external/duckdb/`). Building from source is well known to take
  a long time (commonly cited at 10–30+ minutes) and needs meaningful RAM and a
  C++17 toolchain.

**Implication:** a canvodpy Homebrew formula built the standard
`virtualenv_install_with_resources` way would need `rust` and `cmake` added as
formula `depends_on :build` entries (neither needed by the tiss-cli template),
and `brew install canvodpy` would take substantially longer than a normal
Homebrew install while compiling Rust + C++ from scratch, with more failure
surface across architectures/Xcode CLT versions.

**Possible mitigations if the Homebrew tap is pursued anyway** (not evaluated
in depth, just noted):
- Hand-author the `icechunk`/`duckdb` resources to point at a specific wheel
  URL instead of the tool-generated sdist — works, but needs `on_macos`/
  `on_arm`/`on_intel`-conditional resource blocks per architecture (Homebrew
  formulas do support this), maintained by hand since `update-python-resources`
  won't generate it.
- Skip pinning those two as `resource` blocks and instead `pip install`
  them unpinned inside the formula's `install` step (plain pip/uv already
  prefers wheels) — breaks Homebrew-core's hermetic-pinning convention, but
  that convention doesn't apply to a personal tap anyway.

**This is exactly why `uv tool install canvodpy` (the curl one-liner route)
doesn't have this problem at all** — uv's resolver prefers wheels by default,
same as a normal `pip install icechunk`/`pip install duckdb`, no from-source
compilation involved. Reinforces treating the curl/uv route as primary and the
Homebrew tap as a secondary, more-involved nice-to-have.

## Resolved (short-term, no new packaging work): `uv tool install` for "callable from anywhere" today

2026-07-10/12. Separate from the AppImage/Homebrew pivot above (which is about
giving canvodpy a package-manager-native *distribution* channel) — this is the
immediate, zero-infrastructure answer for "I have canvodpy installed somewhere
in a project venv, I want to just type `canvodpy run ...` from any directory,
right now, with what already exists on PyPI."

**Two install paths, pick based on published-vs-local-dev-checkout:**

1. **Published version:**
   ```bash
   uv tool install canvodpy
   uv tool update-shell   # appends ~/.local/bin to PATH in ~/.zshrc, one-time
   ```
   `uv tool install` is uv's pipx-equivalent: builds a dedicated, isolated
   environment (not tied to any project directory) and drops a real executable
   shim in `~/.local/bin/canvodpy`. `uv tool update-shell` edits `~/.zshrc`
   directly (not just the current shell's env), so this is **fully persistent**
   — survives new terminal sessions and reboots, same as any normally-installed
   binary (`git`, `gfzrnx`, etc.). Only goes away via explicit `uv tool
   uninstall canvodpy`.

2. **Local dev checkout, live edits across the whole monorepo:** `uv tool
   install --editable <path>` only makes *one* target package editable — the
   other ~10 workspace packages (`canvod-readers`, `canvod-utils`, etc.) would
   still resolve from PyPI, not local edits, since a tool install doesn't
   participate in `[tool.uv.workspace]` resolution. Instead, reuse the
   environment `uv sync` already builds correctly at the workspace root (every
   sibling package properly linked as editable), and just expose its existing
   shim on `PATH`:
   ```bash
   cd /path/to/canvodpy-perf && uv sync   # if not already done
   ln -s /path/to/canvodpy-perf/.venv/bin/canvodpy ~/.local/bin/canvodpy
   ```
   Works from anywhere (the shim's shebang already has an absolute interpreter
   path baked in by `uv sync`, so it doesn't care about CWD) and always
   reflects current local code, no reinstall needed while iterating. Caveat:
   if the `canvodpy-perf` checkout is ever moved/renamed, `rm .venv && uv sync`
   again — same symlink target path keeps working. (This exact stale-shebang
   failure mode already bit `canvodpy-extensions`'s `.venv` once this week,
   from before it was renamed from `canvodpy-optional` — same root cause.)

**Confirmed the `run` subcommand syntax is real, pre-existing CLI, not
improvised for this conversation** — verified directly in source, not assumed:
- `canvodpy/src/canvodpy/cli/app.py` registers `@main_app.command("run", ...)`,
  delegating to `_run_main` in `canvodpy/src/canvodpy/cli/run.py`.
- `run.py` builds a real `argparse.ArgumentParser` with `--site` (required,
  `nargs="+"`), `--start`/`--end` (YYYYDOY), `--no-vod`, `--dry-run`,
  `--workers`, `--days-per-batch`, `--config` (overlay YAML — the "arbitrary
  config file" override already in use), `--ephemeris-source`,
  `--vod-calculator`. Module docstring already documents `uv run canvodpy run
  --site ExampleSite --start 2025001 --end 2025007` etc. Once installed via either
  path above, drop the `uv run` prefix — everything else is identical:
  ```bash
  canvodpy run --site ExampleSite --start 2025001 --end 2025007
  canvodpy run --site ExampleSite --config /path/to/overlay.yaml --dry-run
  ```

**Still open / not done:** the config-discovery prerequisite documented above
("canvodpy cannot run outside a git checkout today," specifically
`canvodpy config init`'s hard dependency on `monorepo_root/config` for its
templates) has **not** been fixed — this doesn't block `canvodpy run` itself
if a config overlay file is passed explicitly (confirmed working, per the
user's own testing), but `config init`/`validate`/`show`/`edit`'s *defaults*
still assume a monorepo checkout or `cwd()/config`. Fixing that (bundle
templates as package data, default to XDG `~/.config/canvodpy`) is
independent, still-unimplemented work — see the numbered list above.

## Open questions / risks

- **PATH handling in install.sh** — needs to gracefully handle zsh/bash/fish,
  and users who re-run the installer (idempotency).
- **Versioning/update story** — `uv tool install --force canvodpy` (or `uv tool
  upgrade canvodpy`) for updates; should the installer script also offer an
  update path, or is that out of scope for a first cut?
- **Windows** — out of scope for this doc (no one-liner requested), but note
  `uv tool install` also works on Windows if this ever comes up.
