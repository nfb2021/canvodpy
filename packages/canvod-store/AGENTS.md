# canvod-store

Versioned Icechunk stores for observations and VOD: writing with dedup,
reading, history, maintenance. Built on icechunk 2 (see the `icechunk`
guide).

## Where things live

| Path (under `src/canvod/store/`) | What |
|---|---|
| `store.py` | `MyIcechunkStore`: sessions, group writes and appends, the metadata table, dedup checks, VOD writes, maintenance (`maintenance_due`, `compact_manifests`, expiry, GC), branches and tags |
| `manager.py` | `GnssResearchSite`: a site's observation and VOD stores |
| `viewer.py` | `IcechunkStoreViewer`: inspection and summaries |
| `reader.py` | `IcechunkDataReader`: deprecated second ingestion path, not used by any run |
| `zarr_concurrency.py` | Zarr async concurrency cap (shared or network mounts) |

Background: `docs/packages/store/overview.md`,
`docs/packages/store/icechunk.md` (concurrency, settings),
`docs/packages/store/storage-strategies.md`.

## Invariants

- **Dedup before writing**, in three layers: file hash already in the
  metadata table; time range overlapping stored files; overlap inside the
  batch. A rejected file is reported, never written silently.
- **Write strategies** (`processing.storage.gnss_store_strategy`,
  `vod_store_strategy`): `skip`, `overwrite`, `unsafe_append`. Their
  meaning is documented on the settings model in
  `packages/canvod-config/src/canvod/config/models/storage.py`; keep code
  and that description in step.
- **VOD writes** check `validate_vod_dataset` (canvod-readers) first.
- **Preprocessing**: a group refuses data whose `processing.preprocessing`
  differs from what it already holds (`check_preprocessing_matches`).
- **One committer per branch.** On local or network file systems icechunk
  cannot detect concurrent commits; the second silently wins. Parallel
  writes go through fork/merge into one session and one `commit()`.
- canvod-store does not import `canvodpy`.

## Store layout

One Icechunk repository per store; one group per receiver (observation
store) or per analysis (VOD store), each with a log of the
ingested files (`{group}/metadata/table`). Root attributes hold the source format and the rich
metadata (`canvod_metadata`, see canvod-store-metadata).

## Tests

```bash
just test-package canvod-store
```
