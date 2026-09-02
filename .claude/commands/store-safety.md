Review store operations for safety. Check the following before any store write:

## Pre-write checklist

1. **Branch safety:** Are we writing to `main`? If this is a production store, confirm with user first. Prefer creating a feature branch.

2. **Dedup guardrails active?** Verify the three-layer check is in place:
   - Layer 1: Hash match (`"File Hash"` attr comparison)
   - Layer 2: Temporal overlap vs metadata table
   - Layer 3: Intra-batch overlap detection

3. **Session lifecycle:** After `session.commit()`, the session is read-only. New writes need a new `repo.writable_session()`.

4. **Overwrite strategy:** Do NOT use `_prepare_store_for_overwrite()` — it's broken (Dask serialization bug). Use skip or manual branch reset instead.

5. **Consolidated metadata:** NEVER pass `consolidated=True` to `xr.open_zarr()` with Icechunk.

## Recovery patterns

| Problem | Solution |
|---|---|
| Accidentally wrote to main | `repo.reset_branch("main", snapshot_id=previous_tip)` |
| Bad data committed | Create branch from good snapshot, reset main |
| Concurrent write conflict | Retry with new session, or use separate branches |
| Store corruption suspected | Open read-only session from known-good tag/snapshot |

## Inspection commands

```python
# Check store state
viewer = IcechunkStoreViewer(store_path)
viewer.summary()

# Browse history
for snap in repo.ancestry(branch="main"):
    print(snap.id, snap.message, snap.written_at)

# Check metadata table
table = store.read_metadata_table(group)
```
