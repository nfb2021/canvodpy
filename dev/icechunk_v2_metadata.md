# Icechunk v2 — Can It Replace the Custom Metadata Table?

**Date:** 2026-07-02
**Branch context:** `chore/icechunk-v2-upgrade`
**Question:** Does Icechunk v2 provide built-in facilities that could replace or
simplify canvodpy's custom `{group}/metadata/table` Zarr group, which implements
hash-based dedup and temporal-overlap detection?

---

## Background: what the custom table does

`{group}/metadata/table` is a Zarr group of parallel arrays (`rinex_hash`, `start`,
`end`, `fname`, `rel_path`, `exists`, `written_at`, `dataset_attrs`,
`canonical_name`, `physical_path`, `index`).  It serves three purposes:

1. **Hash dedup** — `batch_check_existing()` scans `rinex_hash` to detect whether
   a file (by content hash) was already ingested.
2. **Temporal overlap** — `check_existing_with_temporal_overlap()` / `check_temporal_overlaps()`
   filter on `[start, end]` columns to detect epoch-range collisions before writing.
3. **Intra-batch overlap** — the orchestrator compares epoch ranges across the batch
   in memory before submitting any writes to Icechunk.

---

## 1. Commit history and snapshot log

### What Icechunk v2 provides

`repo.ancestry(branch=None, snapshot_id=None, tag=None)` returns a lazy iterator of
`SnapshotInfo` objects.  Each carries:

| Field | Type | Notes |
|---|---|---|
| `id` | str | Opaque snapshot identifier |
| `parent_id` | str | Parent snapshot ID |
| `written_at` | `datetime` (UTC, µs precision) | Wall-clock timestamp of commit |
| `message` | str | Free-form commit message |
| `metadata` | `PySnapshotProperties` (dict) | Arbitrary key-value pairs |

Custom key-values can be attached at commit time:

```python
session.commit(
    "Append ROSA_2025_001",
    metadata={"rinex_hash": "abc123", "start": "2025-01-01", "end": "2025-01-02"},
)
```

v2 performance improvement: the full ancestry tree lives in **one file** in object
storage — `repo.ancestry()` costs a single network request regardless of history
depth, versus one request per commit in v1.

`repo.lookup_snapshot(snapshot_id)` returns `SnapshotInfo` for a known snapshot ID.

`repo.ancestry_graph()` renders a visual DAG (canvodpy already wraps this in
`_PatchedAncestryGraph`).

### Limitation: no server-side filter

There is **no** `repo.find_commits(metadata={"rinex_hash": "abc123"})` API.
Checking "has file with hash X been ingested?" requires iterating the entire
`ancestry()` sequence and comparing each entry's `metadata` dict in Python.
For a store with 500 committed files that is 500 objects iterated per ingest
check — O(n) — versus the Zarr table's Polars column filter which is O(1) on
any modern in-memory frame.

**Verdict for hash dedup:** Icechunk commit metadata could serve as a secondary,
human-readable audit annotation but cannot replace the Zarr table for dedup
because it has no indexed lookup.

---

## 2. Chunk-level provenance / lineage

Icechunk does **not** expose a "which commit wrote which chunks" query.  The
internal chunk manifest records which snapshot last modified each chunk, but
this is an opaque storage-layer detail with no public Python API.

There is no built-in "what epoch range is covered in this store?" introspection
beyond reading the actual `epoch` coordinate of the Zarr arrays.  That query
requires opening a Zarr session and loading coordinate metadata — not a
lightweight pre-write check.

**Verdict for temporal overlap:** Icechunk v2 provides nothing here.  Temporal
overlap detection requires domain knowledge (epoch axis semantics) that sits
entirely outside Icechunk's abstraction.

---

## 3. `flush()` and anonymous snapshots

`session.flush(message="Checkpoint after file X")` creates a detached snapshot
without advancing any branch pointer.  It returns a `snapshot_id` and makes
the session read-only.

The flush snapshot can later be promoted:

```python
repo.reset_branch("dev", snapshot_id=snapshot_id)
```

### Why flush cannot replace the metadata table

- Flushed snapshots are **anonymous** — they do not appear in `repo.ancestry(branch="main")`
  because no branch points to them.  Only explicitly promoted snapshots are
  visible in the ancestry of a branch.
- Even if the flush message encodes a file hash, there is no API to search
  anonymous snapshots by message or metadata.
- `flush()` does not accept a `metadata=` parameter in the current v2 API
  (only `message: str`).

**Verdict:** Flush snapshots are useful for pipeline checkpointing (save
intermediate state before deciding whether to commit), but provide no
queryable provenance trail.

---

## 4. Virtual datasets / chunk references

Icechunk supports "virtual chunks" — Zarr array cells that reference byte
ranges inside external files (HDF5, NetCDF, GRIB, TIFF):

```python
store.set_virtual_ref(
    "array/c/0",
    location="s3://bucket/file.nc",
    offset=1024, length=4096,
)
```

The chunk manifest stores the source URL and byte range per virtual chunk.

### Why virtual references do not apply here

canvodpy reads RINEX/SBF files, decodes them into `xarray.Dataset`, and writes
the resulting **native Zarr chunks** into Icechunk.  The original binary files
are not Zarr-compatible and cannot be referenced virtually.  Virtual references
are designed for archival formats (HDF5/NetCDF), not raw GNSS binary streams.

Even if the original files were NetCDF, virtual references track
chunk-to-file mapping, not file-to-epoch-range mapping — a different question.

**Verdict:** Not applicable to canvodpy's ingestion pattern.

---

## 5. Repository-level metadata

New in v2: arbitrary JSON-like dict stored at the repo root, independent of
snapshots:

```python
repo.set_metadata({"site": "ROSA", "station_type": "canopy"})
repo.update_metadata({"last_ingest": "2025-01-02T00:00:00Z"})
repo.get_metadata()
```

This is intended for repo-level provenance (site identity, contact, license) —
the same niche as `canvod_metadata` in the root attrs.

It is **not** a per-file index:

- No append semantics (update replaces or merges the whole dict).
- No column-oriented storage — cannot do epoch range filter without loading the
  entire dict.
- Not designed for O(n files) lookup tables.

**Verdict:** Already covered by `canvod_metadata` root attr written by
`canvod-store-metadata`.  Not a replacement for the file registry.

---

## 6. ops_log

`repo.ops_log()` yields entries with three fields:

| Field | Type | Content |
|---|---|---|
| `kind` | str | `NewCommit`, `BranchCreated`, `TagDeleted`, `GCRun`, etc. |
| `updated_at` | `datetime` | UTC timestamp |
| `backup_path` | str | Internal storage detail |

canvodpy already wraps this as `store.get_ops_log()` / `store.print_ops_log()`
(commit `6bfd3975`).

The ops log is a repo-wide audit trail of **structural mutations**.  It does
not carry commit-level metadata (no rinex_hash, no epoch range, no filename).
It is not queryable by content — only scannable in sequence.

**Verdict:** Useful for operational diagnostics and audit, already integrated.
Not a replacement for the file registry.

---

## Overall conclusion

**Keep the custom metadata table.  Partial annotation enhancement possible.**

| Guardrail | Icechunk v2 alternative | Decision |
|---|---|---|
| Hash dedup | Ancestry metadata (`metadata={"rinex_hash": ...}`) — O(n) scan | Keep table — O(1) Polars lookup |
| Temporal overlap detection | None — not a Zarr/Icechunk concept | Keep table — irreplaceable |
| Intra-batch overlap | None — in-memory orchestrator logic | Keep as-is |

### What Icechunk v2 genuinely adds (already used or easily added)

1. **Fast ancestry** — single-request history, already used via `get_history()`.
2. **ops_log** — repo-wide audit trail, already wrapped in `get_ops_log()`.
3. **Commit-level metadata annotation (optional enhancement)** — attaching
   `rinex_hash`, `canonical_name`, and epoch range to `session.commit(metadata={...})`
   costs nothing and makes the Icechunk history self-describing in `icechunk-io`
   tooling and Arraylake viewers.  This is complementary to the table, not a
   replacement.

### Recommended incremental change (low cost, high diagnostic value)

```python
# In _write_metadata_row(), after session.commit():
session.commit(
    f"Append {canonical_name}",
    metadata={
        "rinex_hash": rinex_hash,
        "canonical_name": canonical_name,
        "start": str(start),
        "end": str(end),
        "action": action,  # "appended" | "overwritten"
    },
)
```

This makes every Icechunk commit self-describing without changing the dedup or
overlap logic.  The metadata table remains the authoritative, O(1)-queryable
source of truth for all three guardrails.

---

## Sources

- [Transactions and Version Control — Icechunk stable](https://icechunk.io/en/latest/understanding/version-control/)
- [Repository Features — Icechunk stable](https://icechunk.io/en/stable/understanding/repository-features/)
- [Announcing Icechunk 2 — Earthmover blog](https://www.earthmover.io/blog/announcing-icechunk-2-better-consistency-performance-and-reliability-for-tensor-storage)
- [Evolving our Tensor Storage Engine: A Preview of Icechunk 2](https://www.earthmover.io/blog/evolving-our-tensor-storage-engine-a-preview-of-icechunk-2/)
- [Virtual Datasets — Icechunk latest](https://icechunk.io/en/latest/guides/virtual/)
- [Python API Reference — Icechunk stable](https://icechunk.io/en/stable/reference/)
- [Icechunk GitHub — earth-mover/icechunk](https://github.com/earth-mover/icechunk)
- [Icechunk — PyPI](https://pypi.org/project/icechunk/)
