# canvod-store

Versioned Icechunk/Zarr storage layer for GNSS VOD datasets.

## Key modules

| Module | Purpose |
|---|---|
| `store.py` | `MyIcechunkStore` — main storage backend (read/write/append/metadata) |
| `viewer.py` | `IcechunkStoreViewer` — inspection, summary, format detection |
| `reader.py` | `IcechunkDataReader` — deprecated leftover ingestion path (RINEX v3 only, no augmentation); use `canvodpy run` / `Site.pipeline()` |
| `manager.py` | `GnssResearchSite` — high-level site management |
| `file_registry.py` | `FileRegistryManager` — tracks ingested files |
| `preprocessing.py` | `IcechunkPreprocessor` — data conditioning before write |

## Store layout

```
{store_root}/
├── {group}/                    # e.g. "canopy", "reference"
│   ├── obs, snr, ...          # Zarr arrays with (epoch, sid) dims
│   └── metadata/
│       ├── table/             # File registry (rinex_hash, start, end, fname, ...)
│       └── sbf_obs/           # SBF-specific metadata (PVT, DOP, SatVisibility)
├── source_format              # Root attr: "sbf" | "rinex3" | "rinex2"
└── canvod_metadata            # Root attr: rich metadata (see canvod-store-metadata)
```

## Critical guardrails

Three-layer dedup prevents data corruption:
1. **Hash match** — skip files already ingested (by `"File Hash"` attr)
2. **Temporal overlap vs metadata** — reject files overlapping existing time ranges
3. **Intra-batch overlap** — reject duplicate time ranges within a single batch

`append_to_group()` has an internal guardrail checking hash + temporal overlap.
The orchestrator's `_check_existing_with_temporal_overlap()` adds the metadata layer.

## Icechunk patterns

- Always use `consolidated=False` with `xr.open_zarr()`
- Sessions become read-only after `commit()` — create new writable session
- Branch safety: NEVER modify `main` on production stores without explicit intent
- Use `to_icechunk` (not `to_zarr`) for distributed writes

## Testing

```bash
uv run pytest packages/canvod-store/tests/
```

Key test files: `test_store_guardrails.py`, `test_metadata_overlap.py`
