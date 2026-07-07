"""
Safe store rechunk — preserves metadata/table/ and metadata/sbf_obs/.

Run AFTER the pipeline finishes, not during an active ingest.
Usage:
    uv run python dev/rechunk_store.py /path/to/store canopy_01 reference_01

The script:
  1. Creates a safety tag "before_rechunk" on the current main tip.
  2. For each receiver group, reads science data only (not metadata subgroups).
  3. Rechunks to epoch=34560, sid=-1.
  4. Writes science arrays back (mode="r+" via a writable session, preserving
     sibling subgroups like metadata/table/ and metadata/sbf_obs/).
  5. Runs expire_old_snapshots() + garbage_collect() once at the end.

Recovery: if anything goes wrong, the safety tag lets you reset:
    repo.reset_branch("main", repo.lookup_tag("before_rechunk"))
"""

import logging
import sys
import time
from datetime import UTC
from pathlib import Path

import xarray as xr
from icechunk import Repository, local_filesystem_storage
from icechunk.xarray import to_icechunk

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

TARGET_CHUNKS = {"epoch": 34560, "sid": -1}


def rechunk_group_safe(repo: Repository, group_name: str) -> str:
    """
    Rechunk science arrays in *group_name* without touching metadata subgroups.

    Returns the snapshot ID of the rechunked commit.
    """
    log.info("Reading group '%s' from main...", group_name)
    t0 = time.time()

    # Read the science dataset (epoch × sid arrays only).
    # open_zarr with group=group_name reads arrays directly inside the group,
    # NOT the metadata/ subgroup (which has different dims and won't be in the
    # consolidated metadata, because we use consolidated=False).
    store = repo.as_store()
    # Read from the zarr group — xarray only picks up arrays with recognised dims.
    ds = xr.open_zarr(store, group=group_name, consolidated=False, chunks=None)
    log.info("Read in %.1fs, original chunks: %s", time.time() - t0, dict(ds.chunks))

    # Rechunk
    ds_rechunked = ds.chunk(TARGET_CHUNKS)
    for var in ds_rechunked.data_vars:
        ds_rechunked[var].encoding = {}
    log.info("Target chunks: %s", dict(ds_rechunked.chunks))

    # Write back using mode="r+" so only the arrays we write are changed;
    # sibling subgroups (metadata/table/, metadata/sbf_obs/) are untouched.
    log.info("Writing rechunked data for '%s'...", group_name)
    t1 = time.time()
    session = repo.writable_session("main")
    to_icechunk(ds_rechunked, session, group=group_name, mode="r+")
    snapshot_id = session.commit(f"rechunk {group_name}: epoch=34560, sid=-1")
    log.info("Committed in %.1fs, snapshot=%s", time.time() - t1, snapshot_id[:8])
    return snapshot_id


def main(store_path: str, *group_names: str) -> None:
    path = Path(store_path).expanduser().resolve()
    if not path.exists():
        log.error("Store path does not exist: %s", path)
        sys.exit(1)

    log.info("Opening store: %s", path)
    storage = local_filesystem_storage(str(path))
    repo = Repository.open(storage)

    # Safety tag — lets you roll back if anything goes wrong.
    current_tip = repo.lookup_branch("main")
    tag_name = "before_rechunk"
    try:
        repo.create_tag(tag_name, current_tip)
        log.info("Safety tag '%s' created at %s", tag_name, current_tip[:8])
    except Exception as e:
        log.warning("Could not create safety tag (already exists?): %s", e)

    if not group_names:
        log.error("Provide at least one group name, e.g. canopy_01 reference_01")
        sys.exit(1)

    for group in group_names:
        log.info("=== Rechunking group: %s ===", group)
        t = time.time()
        rechunk_group_safe(repo, group)
        log.info("Group '%s' done in %.1fs", group, time.time() - t)

    # Single GC pass now that all rechunking is done.
    log.info("Running expire + garbage_collect (one-time)...")
    from datetime import datetime, timedelta

    cutoff = datetime.now(UTC) - timedelta(days=0)  # expire nothing — just collect
    summary = repo.garbage_collect(delete_object_older_than=cutoff)
    log.info(
        "GC done: deleted_chunks=%s, deleted_manifests=%s, deleted_bytes=%s",
        summary.chunks_deleted,
        summary.manifests_deleted,
        summary.bytes_deleted,
    )
    log.info(
        "Rechunk complete. Roll back with: repo.reset_branch('main', repo.lookup_tag('before_rechunk'))"
    )


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(
            "Usage: uv run python dev/rechunk_store.py <store_path> <group1> [group2 ...]"
        )
        sys.exit(1)
    main(sys.argv[1], *sys.argv[2:])
