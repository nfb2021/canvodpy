---
title: Design Principles
description: The engineering and scientific principles that shape canVODpy — why the system works the way it does.
---

# Design Principles

This page explains the engineering and scientific choices behind canVODpy. It is
the "why" companion to [Architecture](architecture.md), which covers the "what"
and "how". Reading these principles will help you make changes that fit the grain
of the codebase — and understand why certain things that look configurable are, in
fact, hard constraints.

---

## 1. One data shape everywhere

**What:** Every GNSS reader — RINEX v2, RINEX v3, Septentrio SBF — produces an
`xarray.Dataset` with exactly two dimensions: `epoch` (observation timestamps) and
`sid` (signal identifier, format `SV|Band|Code`, e.g. `G01|L1|C`). No other shape
is accepted downstream.

**Why (scientific):** A GNSS observation is fundamentally a value indexed by *when*
it was measured (`epoch`) and *which satellite signal* it came from (`sid`). All
subsequent operations — aligning canopy and reference receivers, retrieving VOD,
writing to the store — only need those two coordinates. The data shape is the
minimal common language of the pipeline.

**Why (engineering):** Reader-agnostic code. Augmentation, VOD retrieval, and
storage never ask "is this RINEX or SBF?". They operate on datasets by dimension
name. Adding a new reader requires only that it produce the `(epoch, sid)` shape.

**How:** Enforced in `canvod-readers` at the reader base class. The attribute
`"File Hash"` (SHA-256 of the source file) is required on every dataset — a
missing hash causes a hard error, not a silent skip.

!!! note "What is a 'data contract'?"
    A data contract is an agreed shape for data passed between components. Here it
    means: `dataset.dims == {"epoch", "sid"}` and `"File Hash" in dataset.attrs`.
    Components are free to add extra coordinates (polar angle, azimuth, SNR per
    signal) but the two required dimensions are never optional.

---

## 2. Validation as a hard gate

**What:** Before any file is read or stored, `DataDirectoryValidator` checks every
receiver directory. If any file cannot be mapped to the naming convention, or if
any two files overlap in time, the pipeline stops and prints a diagnostic listing
the problem files. There is no "skip and continue" mode.

**Why (scientific):** An unrecognized file is probably data — ignoring it would
create a silent gap in the archive. Two files covering the same time window would
double-count epochs, biasing SNR statistics and corrupting VOD. The cost of a
false alarm (manual inspection) is far lower than the cost of silently wrong data.

**Why (engineering):** Fail-loud design. The validator returns a `ValidationReport`
with `is_valid`, `unmatched` (list of unrecognized paths), and `overlaps` (list of
conflicting pairs), so the error message always tells the operator exactly what to
fix.

**How:** `DataDirectoryValidator.validate_receiver()` in `canvod-filemap`.
Called by `validate_data_dirs()` in the orchestrator before any reading begins.

!!! warning "The naming convention is a hard gate, not an overridable default"
    `DataDirectoryValidator` has no "permissive" or "warn-only" mode. Files that
    do not match a recognized pattern or recipe are always rejected. Configuring a
    `NamingRecipe` for non-standard filenames is the correct response to a
    validation failure — not disabling the check.

---

## 3. Reproducibility via versioned storage

**What:** Every write to a canVODpy data store ends with an immutable commit. The
entire state of the store — every array, every coordinate, every attribute — is
captured as a numbered snapshot. Previous snapshots are never modified or deleted.

**Why (scientific):** A published VOD time series must be traceable to the exact
data that produced it. If a processing bug is discovered and a reanalysis is run,
the original run and the corrected run must be distinguishable. Icechunk stores work
like a version-controlled repository: every commit has an ID that can be cited in a
paper or included in a data-publication record.

**Why (engineering):** Processing mistakes are survivable. Committing bad data does
not destroy the previous good state — rolling back is a one-line operation. This
removes the pressure to get every run perfect before writing.

**How:** `canvod-store` wraps the Icechunk v2 API: `repo.writable_session()` opens
a transaction, writes proceed inside it, and `session.commit()` finalizes the
snapshot. The commit log is accessible via `store.get_ops_log()` or visualized as
a history graph via `store.plot_commit_graph()` (which delegates to Icechunk's
native `repo.ancestry_graph()`).

!!! note "What does 'immutable snapshot' mean?"
    Once a commit is finalized, its contents cannot be changed. Subsequent writes
    create a *new* commit that extends the history. Reading an old snapshot
    (`repo.readonly_session(snapshot_id=...)`) always returns the data as it was
    at that point in time — regardless of what has been written since.

---

## 4. Layered, upward-free dependencies

**What:** Packages are arranged in layers (Foundation → Data I/O → Computation →
Persistence → Orchestration). No package imports from a package above it in the
stack. `canvod-vod` does not know about `canvod-store`; `canvod-store` does not
know about `canvodpy`.

**Why (scientific):** Scientists often want to apply one algorithm in isolation —
run the VOD formula on data from a different source, or use the hemispheric grid
without the full pipeline. Upward-free dependencies make this possible: install
`canvod-vod` alone and it works.

**Why (engineering):** Independent testing. The VOD formula can be unit-tested
without a store, a reader, or an internet connection. The store can be tested
without running readers. Circular imports are structurally impossible.

**How:** Declared in each package's `pyproject.toml`. Four packages have no
inter-package dependencies at all: `canvod-utils`, `canvod-vod`,
`canvod-filemap`, and `canvod-preflight`. See
[Architecture → Dependency Graph](architecture.md#dependency-graph) for the full
declaration.

---

## 5. Self-describing filenames as provenance

**What:** The naming convention encodes every piece of identity information — site,
receiver type, date, period, sampling interval, data format — into the filename
itself. No external database is needed to know what a file contains or which
receiver produced it.

**Why (scientific):** Provenance should survive a file copy. A GNSS archive that
relies on a separate metadata database to interpret its filenames becomes opaque
the moment that database is unavailable. A self-describing filename is still
meaningful when found on a USB drive years later.

**Why (engineering):** The canonical name drives three operations automatically,
without additional configuration:

- **Deduplication** — two files with the same canonical name are the same data.
- **Receiver pairing** — reference (`T=R`) and canopy (`T=A`) files share all
  fields except receiver type; the pipeline pairs them by diffing on that one
  character.
- **Store keying** — each group in the Icechunk store is addressed by canonical
  name, so temporal range queries are computable from filenames alone.

**How:** `canvod-filemap`. Physical files are never renamed — a virtual
mapping layer (`FilenameMapper` + `VirtualFile`) attaches a canonical name to each
physical path. All downstream processing uses the canonical name; the physical path
is retained only for opening the file.

---

## 6. Three-layer deduplication — refuse, never silently skip

**What:** Before any dataset is appended to the store, three successive checks run:
(1) does a file with this exact hash already exist? (2) does the time window of
this file overlap with data already in the store? (3) does this file overlap with
another file in the current batch? If any check fails, the write is refused with a
diagnostic error.

**Why (scientific):** Duplicate epochs in the store corrupt canopy/reference
alignment. If the reference receiver's DOY 1 is written twice, every
canopy/reference SNR difference computed from that day will be wrong — and the
error will be silent unless the audit suite catches it. The deduplication guard
makes this class of mistake structurally impossible.

**Why (engineering):** Idempotent ingestion. Running the same processing job twice
(for example, after a crash and restart) produces the same store state, not a store
with doubled data. The hash check is the fast path: identical content is detected
before any write occurs.

**How:** `append_to_group()` in `canvod-store` contains the hash and temporal
overlap guard. `_check_existing_with_temporal_overlap()` in the orchestrator adds
the intra-batch check before batches are submitted. Together they form an outer and
inner defence that covers both inter-run and intra-run duplication.

!!! note "What does 'idempotent' mean?"
    An operation is idempotent if running it twice produces the same result as
    running it once. Here: ingest the same file twice → the store contains exactly
    one copy of the data. The first run writes it; the second run detects the hash
    match and skips without error.

---

## File Naming Convention

canVODpy uses a canonical naming convention for all GNSS observation files,
designed to be compatible with the
[RINEX v3.04 long-name convention](https://files.igs.org/pub/data/format/rinex304.pdf)
while extending it with GNSS-Transmissometry–specific fields.

### Why the naming convention matters

A self-describing filename enables automatic **deduplication** (same canonical name
= same data), **receiver pairing** (reference and canopy files share all fields
except the single receiver-type character), and **provenance tracking** (date, site,
and format are readable without opening the file). This is why the convention is a
hard validation gate rather than a default that can be bypassed — see
[Principle 2](#2-validation-as-a-hard-gate) above.

### Format

```
{SIT}{T}{NN}{AGC}_R_{YYYY}{DOY}{HHMM}_{PERIOD}_{SAMPLING}_{CONTENT}.{TYPE}[.{COMPRESSION}]
```

<iframe src="../diagrams/naming-convention-embed.html" style="width:100%;height:320px;border:none;display:block;margin:1.5rem 0;" loading="lazy"></iframe>

### Fields

| Field | Width | Description | Example |
|-------|-------|-------------|---------|
| `SIT` | 3 | Site ID, uppercase | `ROS`, `HAI`, `FON`, `LBS` |
| `T` | 1 | Receiver type: **R** = reference, **A** = active (below-canopy) | `R`, `A` |
| `NN` | 2 | Receiver number, zero-padded (01–99) | `01`, `35` |
| `AGC` | 3 | Data provider / agency ID, uppercase | `TUW`, `GFZ`, `MPI` |
| `_R` | 2 | RINEX data-source field — always `R` (receiver-generated) | `_R` |
| `YYYY` | 4 | Year | `2025` |
| `DOY` | 3 | Day of year (001–366) | `001`, `222` |
| `HHMM` | 4 | Start time (hours + minutes) | `0000`, `1530` |
| `PERIOD` | 3 | Batch size: 2-digit value + unit (S/M/H/D) | `01D`, `15M`, `01H` |
| `SAMPLING` | 3 | Data frequency: 2-digit value + unit (S/M/H/D) | `01S`, `05S`, `05M` |
| `CONTENT` | 2 | User-defined content code, default `AA` | `AA` |
| `TYPE` | 3–4 | File format, lowercase | `rnx`, `sbf`, `ubx`, `nmea` |
| `COMPRESSION` | — | Optional compression extension | `zip`, `gz`, `bz2`, `zst` |

!!! note "Receiver type: 'active' vs 'canopy'"
    In the filename, `T=A` denotes an **active** receiver — the below-canopy unit
    actively receiving attenuated signals. In the configuration API and validator,
    this role is called **canopy** (`ReceiverType.ACTIVE` in the code maps to
    `"canopy"` in configuration). Both terms refer to the same physical receiver;
    the difference reflects the code's adoption of the IGS convention (`A`) while
    the config API uses the more descriptive scientific term (`canopy`).

!!! note "The `_R` separator"
    `_R` is not simply "R for Receiver". It is the RINEX v3.04 **data-source
    field**, specifying how the data was produced: `R` means the file was generated
    directly by the receiver hardware (as opposed to `S` for a stream or `U` for
    unknown). canVODpy fixes this field to `R` because all ingested files originate
    from receiver hardware.

### Duration codes

The `PERIOD` and `SAMPLING` fields use a 2-digit value followed by a unit
character:

| Unit | Meaning | Example |
|------|---------|---------|
| `S` | Seconds | `05S` = 5 seconds |
| `M` | Minutes | `15M` = 15 minutes |
| `H` | Hours | `01H` = 1 hour |
| `D` | Days | `01D` = 1 day |

### Receiver types

| Code | Role | Description |
|------|------|-------------|
| `R` | Reference | Above canopy — unobstructed sky view |
| `A` | Active / canopy | Below canopy — signal attenuated by vegetation |

### Examples

**Daily merged, 5-second sampling (reference):**

```
ROSR01TUW_R_20250010000_01D_05S_AA.rnx
│  │ │ │     │       │    │   │   │  └── RINEX observation
│  │ │ │     │       │    │   │   └── content: default
│  │ │ │     │       │    │   └── sampling: 5 seconds
│  │ │ │     │       │    └── period: 1 day
│  │ │ │     │       └── start: 00:00
│  │ │ │     └── 2025, DOY 001
│  │ │ └── agency: TU Wien
│  │ └── receiver number 01
│  └── R = reference
└── site: Rosalia
```

**Daily merged, 5-second sampling (active / below-canopy):**

```
ROSA01TUW_R_20250010000_01D_05S_AA.rnx
   ^
   A = active (below-canopy)
```

**15-minute sub-daily file, SBF format:**

```
ROSR35TUW_R_20232221530_15M_05S_AA.sbf
    ^^                  ^^^        ^^^
    receiver #35        15-min     Septentrio Binary Format
```

**Compressed daily file, 1-second sampling:**

```
HAIA01GFZ_R_20250010000_01D_01S_AA.rnx.zip
^^^                                    ^^^^
Hainich                                zip compressed
```

### SP3 and CLK files

SP3 orbit and CLK clock product files already follow the IGS long-name convention
and **do not** need renaming under this scheme.

[Full naming convention reference](packages/naming/overview.md)

---

*Questions or suggestions? Open a discussion on
[GitHub](https://github.com/nfb2021/canvodpy/discussions).*

---

**Next in the trail:** [API Levels](guides/api-levels.md) · [Getting Started](guides/getting-started.md) · [Architecture](architecture.md) · [AI Development](guides/ai-development.md)
