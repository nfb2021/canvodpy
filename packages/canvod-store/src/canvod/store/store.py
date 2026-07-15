import contextlib
import io
import json
import os
import sys
import time
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

import icechunk
import numpy as np
import polars as pl
import xarray as xr
import zarr
from canvod.utils.tools import get_version_from_pyproject
from canvodpy.logging import get_logger, stage_timer
from canvodpy.logging.run_context import get_run_id
from icechunk.xarray import to_icechunk
from zarr.dtype import VariableLengthUTF8

from canvod.store.viewer import add_rich_display_to_store

# Suppress the "local filesystem not safe for concurrent commits" Rust/tracing
# warning — we are aware and it is noise for single-writer local workflows.
icechunk.set_logs_filter("icechunk=error")

if TYPE_CHECKING:
    from icechunk import AncestryGraph


def _with_run_id(commit_message: str) -> str:
    """Append the current run_id (if any) to a commit message.

    Lets a human or an agent correlate an Icechunk commit with the run
    that produced it, by grepping the same run_id across the commit log
    and the agent-diagnostic log (see ``canvodpy.logging.run_context``).
    Append-only: does not change caller-provided commit message content.
    """
    run_id = get_run_id()
    if run_id is None:
        return commit_message
    return f"{commit_message} (run={run_id})"


@add_rich_display_to_store
class MyIcechunkStore:
    """
    Core Icechunk store manager for GNSS data.

    This class encapsulates all operations on a single Icechunk repository,
    providing a clean interface for GNSS data storage and retrieval with
    integrated logging and proper resource management.

    Features:
    - Automatic repository creation/connection
    - Group management with validation
    - Session management with context managers
    - Integrated logging with file contexts
    - Configurable compression and chunking

    Note on "metadata"
    ------------------
    This class manages two distinct things both historically called "metadata":

    - **File registry** (``{group}/metadata/table``): per-file ingest ledger
      tracking hashes, temporal ranges, filenames, and paths. Managed by
      ``append_metadata()``, ``load_metadata()``, ``backup_metadata_table()``, etc.

    - **Store metadata** (``canvod.store_metadata`` package): store-level
      provenance (identity, creator, environment, compliance). Written to
      Zarr root attrs by the orchestrator. See ``canvod-store-metadata``.

    Parameters
    ----------
    store_path : Path
        Path to the Icechunk store directory.
    store_type : str, default "rinex_store"
        Type of store ("rinex_store" or "vod_store").
    compression_level : int | None, optional
        Override default compression level.
    compression_algorithm : str | None, optional
        Override default compression algorithm.

    Attributes
    ----------
    store_path : Path
        Path to the Icechunk store directory.
    store_type : str
        Type of store ("rinex_store" or "vod_store").
    compression_level : int
        Compression level (1-9).
    compression_algorithm : icechunk.CompressionAlgorithm
        Compression algorithm enum.
    repo : icechunk.Repository
        The Icechunk repository instance.
    """

    def __init__(
        self,
        store_path: Path,
        store_type: str = "rinex_store",
        compression_level: int | None = None,
        compression_algorithm: str | None = None,
    ) -> None:
        """Initialize the Icechunk store manager.

        Parameters
        ----------
        store_path : Path
            Path to the Icechunk store directory.
        store_type : str, default "rinex_store"
            Type of store ("rinex_store" or "vod_store").
        compression_level : int | None, optional
            Override default compression level.
        compression_algorithm : str | None, optional
            Override default compression algorithm.
        """
        self._logger = get_logger(__name__)

        try:
            from canvod.config import load_config

            cfg = load_config()
            ic_cfg = cfg.processing.icechunk
            _rinex_store_strategy = cfg.processing.storage.gnss_store_strategy
            _vod_store_strategy = cfg.processing.storage.vod_store_strategy
            _log_path_depth = cfg.processing.logging.log_path_depth
        except Exception:
            from canvod.config.models import IcechunkConfig

            ic_cfg = IcechunkConfig()
            _rinex_store_strategy = "append"
            _vod_store_strategy = "overwrite"
            _log_path_depth = 3

        self.store_path = Path(store_path)
        self.store_type = store_type
        # Site name is parent directory name
        self.site_name = self.store_path.parent.name

        # Compression — icechunk v2 only supports zstd
        self.compression_level = compression_level or ic_cfg.compression_level
        self.compression_algorithm = icechunk.CompressionAlgorithm.Zstd

        # Chunk strategy
        chunk_strategies = {
            k: {"epoch": v.epoch, "sid": v.sid}
            for k, v in ic_cfg.chunk_strategies.items()
        }
        self.chunk_strategy = chunk_strategies.get(store_type, {})

        # Storage config cached for metadata rows
        self._rinex_store_strategy = _rinex_store_strategy
        self._vod_store_strategy = _vod_store_strategy
        self._log_path_depth = _log_path_depth

        # Configure repository
        self.config = icechunk.RepositoryConfig.default()
        self.config.compression = icechunk.CompressionConfig(
            level=self.compression_level, algorithm=self.compression_algorithm
        )
        self.config.inline_chunk_threshold_bytes = ic_cfg.inline_chunk_threshold_bytes
        self.config.get_partial_values_concurrency = (
            ic_cfg.get_partial_values_concurrency
        )

        if ic_cfg.max_concurrent_requests is not None:
            self.config.max_concurrent_requests = ic_cfg.max_concurrent_requests

        if (
            ic_cfg.cache_num_chunk_refs is not None
            or ic_cfg.cache_num_bytes_chunks is not None
        ):  # noqa: E501
            caching = icechunk.CachingConfig.default()
            if ic_cfg.cache_num_chunk_refs is not None:
                caching.num_chunk_refs = ic_cfg.cache_num_chunk_refs
            if ic_cfg.cache_num_bytes_chunks is not None:
                caching.num_bytes_chunks = ic_cfg.cache_num_bytes_chunks
            self.config.caching = caching

        preload_cfg = None
        if ic_cfg.manifest_preload_enabled:
            preload_cfg = icechunk.ManifestPreloadConfig(
                max_total_refs=ic_cfg.manifest_preload_max_refs,
                max_arrays_to_scan=ic_cfg.manifest_preload_max_arrays_to_scan,
                preload_if=icechunk.ManifestPreloadCondition.name_matches(
                    ic_cfg.manifest_preload_pattern
                ),
            )
            self._logger.info(
                "Manifest preload enabled: "
                f"pattern={ic_cfg.manifest_preload_pattern!r}, "
                f"max_refs={ic_cfg.manifest_preload_max_refs}"
            )

        splitting_cfg = None
        if ic_cfg.manifest_splitting_enabled:
            from icechunk import (
                ManifestSplitCondition,
                ManifestSplitDimCondition,
                ManifestSplittingConfig,
            )

            _n_ep = ic_cfg.manifest_splitting_epoch_range
            # Split all arrays that have an "epoch" dimension every _n_ep indices.
            # Arrays without that dimension (e.g. coordinate arrays) are unaffected.
            splitting_cfg = ManifestSplittingConfig.from_dict(
                {
                    ManifestSplitCondition.name_matches(".*"): {
                        ManifestSplitDimCondition.DimensionName("epoch"): _n_ep,
                    },
                }
            )
            self._logger.info(f"Manifest splitting enabled: epoch_range={_n_ep}")

        if preload_cfg is not None or splitting_cfg is not None:
            self.config.manifest = icechunk.ManifestConfig(
                preload=preload_cfg,
                splitting=splitting_cfg,
            )

        self._repo = None

        # Remove .DS_Store files that corrupt icechunk ref listing on macOS
        self._clean_ds_store()
        self._ensure_store_exists()

    def _clean_ds_store(self) -> None:
        """Remove .DS_Store files from the store directory tree.

        macOS creates these files automatically and they corrupt icechunk's
        ref listing, causing 'invalid ref type `.DS_Store`' errors.
        """
        if not self.store_path.exists():
            return
        for ds_store in self.store_path.rglob(".DS_Store"):
            ds_store.unlink()
            self._logger.debug(f"Removed {ds_store}")

    def _normalize_encodings(self, ds: xr.Dataset) -> xr.Dataset:
        """Normalize dataset encodings for Icechunk.

        Parameters
        ----------
        ds : xr.Dataset
            Dataset to normalize.

        Returns
        -------
        xr.Dataset
            Dataset with normalized encodings.
        """
        for v in ds.data_vars:
            if "dtype" in ds[v].encoding:
                ds[v].encoding["dtype"] = np.dtype(ds[v].dtype)
        # Cast string-like / non-numeric coords to numpy object for Zarr V3.
        #
        # Why np.array(raw, dtype=object) instead of raw.astype(object):
        # In numpy 2.x, StringDType.astype(object) can silently return StringDType
        # when the array is a Dask lazy computation. np.array() box-constructs a
        # new object array from scratch, guaranteeing object dtype regardless of
        # input type or lazy-evaluation state.
        #
        # Batching strategy: collect all Dask-backed coords first, compute them in
        # one dask.compute() call (one scheduler pass), then handle numpy-backed
        # coords. Reduces ~7 separate graph walks to 1 on a lazy VOD dataset.
        _numeric_kinds = frozenset("fiucbmMV")
        str_coords: dict = {}
        dask_coords: dict = {}
        numpy_coords: dict = {}

        for name in list(ds.coords):
            da = ds[name]
            if da.dtype.kind in _numeric_kinds:
                continue
            if da.chunks is None and da.dtype == object:
                continue  # already correct numpy object
            if da.chunks is not None:
                dask_coords[name] = da
            else:
                numpy_coords[name] = da

        # Batch-compute all dask-backed string coords in ONE scheduler pass
        if dask_coords:
            try:
                import dask

                computed = dask.compute(*dask_coords.values())
                for name, computed_da in zip(dask_coords.keys(), computed):
                    raw = (
                        computed_da.values
                        if hasattr(computed_da, "values")
                        else np.asarray(computed_da)
                    )
                    if raw.dtype != object:
                        raw = np.array(raw, dtype=object)
                    str_coords[name] = (
                        dask_coords[name].dims,
                        raw,
                        dask_coords[name].attrs,
                    )
            except Exception:
                for name, da in dask_coords.items():
                    try:
                        raw = da.compute().values
                        if raw.dtype != object:
                            raw = np.array(raw, dtype=object)
                        str_coords[name] = (da.dims, raw, da.attrs)
                    except Exception:
                        continue

        # Numpy-backed non-object coords (StringDType, unicode kind 'U')
        for name, da in numpy_coords.items():
            try:
                raw = da.values
                if raw.dtype != object:
                    raw = np.array(raw, dtype=object)
                str_coords[name] = (da.dims, raw, da.attrs)
            except Exception:
                continue

        if str_coords:
            ds = ds.assign_coords(str_coords)
        for name in list(ds.data_vars):
            if ds[name].dtype.kind in ("U", "T"):
                ds[name] = ds[name].astype(object)
        # Eagerly compute any remaining Dask-backed object data variables
        try:
            import dask.array as da_mod

            for name in list(ds.data_vars):
                if ds[name].dtype == object and isinstance(ds[name].data, da_mod.Array):
                    ds[name] = ds[name].compute()
        except ImportError:
            pass
        return ds

    def _ensure_store_exists(self) -> None:
        """Ensure the store exists, creating if necessary."""
        storage = icechunk.local_filesystem_storage(str(self.store_path))

        if self.store_path.exists() and any(self.store_path.iterdir()):
            self._logger.info(f"Opening existing Icechunk store at {self.store_path}")
            self._repo = icechunk.Repository.open(storage=storage, config=self.config)
        else:
            self._logger.info(f"Creating new Icechunk store at {self.store_path}")
            self.store_path.mkdir(parents=True, exist_ok=True)
            self._repo = icechunk.Repository.create(storage=storage, config=self.config)

    @property
    def repo(self) -> icechunk.Repository:
        """Get the repository instance."""
        if self._repo is None:
            self._ensure_store_exists()
        return self._repo

    @contextlib.contextmanager
    def readonly_session(
        self,
        branch: str = "main",
    ) -> Generator[icechunk.ReadonlySession]:
        """Thin wrapper over ``repo.readonly_session()`` for this CM."""
        yield self.repo.readonly_session(branch)

    @contextlib.contextmanager
    def writable_session(
        self,
        branch: str = "main",
    ) -> Generator[icechunk.WritableSession]:
        """Thin wrapper over ``repo.writable_session()`` for this CM."""
        yield self.repo.writable_session(branch)

    # ── Root-level store attributes ────────────────────────────────────────────

    def set_root_attrs(self, attrs: dict[str, Any], branch: str = "main") -> str:
        """Set root-level Zarr attributes on the store.

        Parameters
        ----------
        attrs : dict[str, Any]
            Key-value pairs to merge into root attrs.
        branch : str, default "main"
            Branch to write to.

        Returns
        -------
        str
            Snapshot ID from the commit.
        """
        message = f"Set root attrs: {list(attrs.keys())}"
        with self.repo.transaction(branch, message=message) as store:
            try:
                root = zarr.open_group(store, mode="r+")
            except zarr.errors.GroupNotFoundError:
                root = zarr.open_group(store, mode="w")
            root.attrs.update(attrs)
        return self.repo.lookup_branch(branch)

    def get_root_attrs(self, branch: str = "main") -> dict[str, Any]:
        """Read root-level Zarr attributes from the store.

        Returns
        -------
        dict[str, Any]
            Root attributes (empty dict if none set).
        """
        try:
            with self.readonly_session(branch) as session:
                root = zarr.open_group(session.store, mode="r")
                return dict(root.attrs)
        except Exception:
            return {}

    @property
    def source_format(self) -> str | None:
        """Return the ``source_format`` root attribute, or None."""
        return self.get_root_attrs().get("source_format")

    def get_branch_names(self) -> list[str]:
        """
        List all branches in the store.

        Returns
        -------
        list[str]
            List of branch names.
        """
        return list(self.repo.list_branches())

    def get_group_names(self, branch: str | None = None) -> dict[str, list[str]]:
        """
        List all groups in the store.

        Parameters
        ----------
        branch: Optional[str]
            Repository branch to examine. Defaults to listing groups from all branches.

        Returns
        -------
        dict[str, list[str]]
            Dictionary mapping branch names to lists of group names.

        """
        branches = [branch] if branch else self.get_branch_names()
        group_dict = {}
        for br in branches:
            with self.readonly_session(br) as session:
                try:
                    root = zarr.open(session.store, mode="r")
                    group_dict[br] = list(root.group_keys())
                except zarr.errors.GroupNotFoundError:
                    group_dict[br] = []
        return group_dict

    def list_groups(self, branch: str = "main") -> list[str]:
        """
        List all groups in a branch.

        Parameters
        ----------
        branch : str
            Branch name (default: "main")

        Returns
        -------
        list[str]
            List of group names in the branch
        """
        group_dict = self.get_group_names(branch=branch)
        if branch in group_dict:
            return group_dict[branch]
        return []

    @property
    def tree(self) -> None:
        """Print hierarchical tree of all branches and groups. See ``print_tree``."""
        self.print_tree(max_depth=None)

    def print_tree(self, max_depth: int | None = None) -> None:
        """
        Display hierarchical tree of all branches, groups, and subgroups.

        Parameters
        ----------
        max_depth : int | None
            Maximum depth to display. None for unlimited depth.
            - 0: Only show branches
            - 1: Show branches and top-level groups
            - 2: Show branches, groups, and first level of subgroups/arrays
            - etc.
        """
        try:
            branches = self.get_branch_names()

            for i, branch in enumerate(branches):
                is_last_branch = i == len(branches) - 1
                branch_prefix = "└── " if is_last_branch else "├── "

                if max_depth is not None and max_depth < 1:
                    continue

                session = self.repo.readonly_session(branch)
                root = zarr.open(session.store, mode="r")

                if i == 0:
                    sys.stdout.write(f"{self.store_path}\n")

                sys.stdout.write(f"{branch_prefix}{branch}\n")
                # Build tree recursively
                branch_indent = "    " if is_last_branch else "│   "
                self._build_tree(root, branch_indent, max_depth, current_depth=1)

        except Exception as e:
            self._logger.warning(f"Failed to generate tree for {self!r}: {e}")
            sys.stdout.write(f"Error generating tree: {e}\n")

    def _build_tree(
        self,
        group: zarr.Group,
        prefix: str,
        max_depth: int | None,
        current_depth: int = 0,
    ) -> None:
        """Recursively build a tree structure.

        Parameters
        ----------
        group : zarr.Group
            Root group to traverse.
        prefix : str
            Prefix string for tree formatting.
        max_depth : int | None
            Maximum depth to display. None for unlimited.
        current_depth : int, default 0
            Current recursion depth.

        Returns
        -------
        None
        """
        if max_depth is not None and current_depth >= max_depth:
            return

        # Get all groups and arrays
        groups = list(group.group_keys())
        arrays = list(group.array_keys())
        items = groups + arrays

        for i, item_name in enumerate(items):
            is_last = i == len(items) - 1
            connector = "└── " if is_last else "├── "

            if item_name in groups:
                # It's a group
                sys.stdout.write(f"{prefix}{connector}{item_name}\n")

                # Recurse into subgroup
                subgroup = group[item_name]
                new_prefix = prefix + ("    " if is_last else "│   ")
                self._build_tree(subgroup, new_prefix, max_depth, current_depth + 1)
            else:
                # It's an array
                arr = group[item_name]
                shape_str = str(arr.shape)
                dtype_str = str(arr.dtype)
                sys.stdout.write(
                    f"{prefix}{connector}{item_name} {shape_str} {dtype_str}\n"
                )

    def group_exists(self, group_name: str, branch: str = "main") -> bool:
        """
        Check if a group exists.

        Parameters
        ----------
        group_name : str
            Name of the group to check.
        branch : str, default "main"
            Repository branch to examine.

        Returns
        -------
        bool
            True if the group exists, False otherwise.
        """
        group_dict = self.get_group_names(branch)

        # get_group_names returns dict like {'main': ['canopy_01', ...]}
        if branch in group_dict:
            exists = group_name in group_dict[branch]
        else:
            exists = False

        self._logger.debug(
            f"Group '{group_name}' exists on branch '{branch}': {exists}"
        )
        return exists

    def read_group(
        self,
        group_name: str,
        branch: str = "main",
        time_slice: slice | None = None,
        date: str | None = None,
        chunks: dict[str, Any] | None = None,
    ) -> xr.Dataset:
        """
        Read data from a group.

        Parameters
        ----------
        group_name : str
            Name of the group to read.
        branch : str, default "main"
            Repository branch.
        time_slice : slice | None, optional
            Optional label-based time slice for filtering (passed to ``ds.sel``).
        date : str | None, optional
            YYYYDOY string (e.g. ``"2025001"``) selecting a single calendar day.
            Converted to a ``time_slice``; mutually exclusive with ``time_slice``.
        chunks : dict[str, Any] | None, optional
            Chunking specification (uses config defaults if None).

        Returns
        -------
        xr.Dataset
            Dataset from the group.
        """
        self._logger.info(f"Reading group '{group_name}' from branch '{branch}'")

        if date is not None:
            from canvod.utils.tools.date_utils import YYYYDOY

            _d = YYYYDOY.from_str(date).date
            time_slice = slice(str(_d), str(_d + timedelta(days=1)))

        with self.readonly_session(branch) as session:
            # Use default chunking strategy if none provided
            if chunks is None:
                chunks = self.chunk_strategy or {"epoch": 17280, "sid": -1}

            ds = xr.open_zarr(
                session.store,
                group=group_name,
                chunks=chunks,
                consolidated=False,
            )

            if time_slice is not None:
                ds = ds.sel(epoch=time_slice)
                self._logger.debug(f"Applied time slice: {time_slice}")

            self._logger.info(
                f"Successfully read group '{group_name}' - shape: {dict(ds.sizes)}"
            )
            return ds

    def read_group_deduplicated(
        self,
        group_name: str,
        branch: str = "main",
        keep: str = "last",
        time_slice: slice | None = None,
        chunks: dict[str, Any] | None = None,
    ) -> xr.Dataset:
        """
        Read data from a group with automatic deduplication.

        This method calls read_group() then removes duplicates using metadata table
        intelligence when available, falling back to simple epoch deduplication.

        Parameters
        ----------
        group_name : str
            Name of the group to read.
        branch : str, default "main"
            Repository branch.
        keep : str, default "last"
            Deduplication strategy for duplicate epochs.
        time_slice : slice | None, optional
            Optional time slice for filtering.
        chunks : dict[str, Any] | None, optional
            Chunking specification (uses config defaults if None).

        Returns
        -------
        xr.Dataset
            Dataset with duplicates removed (latest data only).
        """

        if keep not in ["last"]:
            raise ValueError("Currently only 'last' is supported for keep parameter.")

        self._logger.info(f"Reading group '{group_name}' with deduplication")

        # First, read the raw data
        ds = self.read_group(
            group_name, branch=branch, time_slice=time_slice, chunks=chunks
        )

        # Then deduplicate using metadata table intelligence
        with self.readonly_session(branch) as session:
            try:
                zmeta = zarr.open_group(session.store, mode="r")[
                    f"{group_name}/metadata/table"
                ]

                # Load metadata and get latest entries for each time range
                data = {col: zmeta[col][:] for col in zmeta.array_keys()}
                df = pl.DataFrame(data)

                # Ensure datetime dtypes
                df = df.with_columns(
                    [
                        pl.col("start").cast(pl.Datetime("ns")),
                        pl.col("end").cast(pl.Datetime("ns")),
                    ]
                )

                # Get latest entry for each unique (start, end) combination
                latest_entries = df.sort("written_at").unique(
                    subset=["start", "end"], keep=keep
                )

                if latest_entries.height > 0:
                    # Create time masks for latest data only
                    time_masks = []
                    for row in latest_entries.iter_rows(named=True):
                        start_time = np.datetime64(row["start"], "ns")
                        end_time = np.datetime64(row["end"], "ns")
                        mask = (ds.epoch >= start_time) & (ds.epoch <= end_time)
                        time_masks.append(mask)

                    # Combine all masks with OR logic
                    if time_masks:
                        combined_mask = time_masks[0]
                        for mask in time_masks[1:]:
                            combined_mask = combined_mask | mask
                        ds = ds.isel(epoch=combined_mask)

                        self._logger.info(
                            "Deduplicated using metadata table: kept "
                            f"{len(latest_entries)} time ranges"
                        )

            except Exception as e:
                # Fall back to simple deduplication
                self._logger.warning(
                    f"Metadata-based deduplication failed, using simple approach: {e}"
                )
                ds = ds.drop_duplicates("epoch", keep="last")
                self._logger.info("Applied simple epoch deduplication (keep='last')")

        return ds

    def _cleanse_dataset_attrs(self, dataset: xr.Dataset) -> xr.Dataset:
        """Remove any attributes that might interfere with Icechunk storage."""

        attrs_to_remove = [
            "Created",
            "File Path",
            "File Type",
            "Date",
            "institution",
            "Time of First Observation",
            "GLONASS COD",
            "GLONASS PHS",
            "GLONASS BIS",
            "Leap Seconds",
        ]
        for attr in attrs_to_remove:
            if attr in dataset.attrs:
                del dataset.attrs[attr]
        return dataset

    def write_dataset(
        self,
        dataset: xr.Dataset,
        group_name: str,
        session: Any,
        mode: str = "a",
        chunks: dict[str, int] | None = None,
    ) -> None:
        """
        Write a dataset to Icechunk with proper chunking.

        Parameters
        ----------
        dataset : xr.Dataset
            Dataset to write
        group_name : str
            Group path in store
        session : Any
            Active writable session or store handle.
        mode : str
            Write mode: 'w' (overwrite) or 'a' (append)
        chunks : dict[str, int] | None
            Chunking spec. If None, uses store's chunk_strategy.
            Example: {'epoch': 17280, 'sid': -1}
        """
        # Use explicit chunks, or fall back to store's chunk strategy
        if chunks is None:
            chunks = self.chunk_strategy

        # Apply chunking if strategy defined
        if chunks:
            dataset = dataset.chunk(chunks)
            self._logger.info(f"Rechunked to {dict(dataset.chunks)} before write")

        # Normalize encodings
        dataset = self._normalize_encodings(dataset)

        # Calculate dataset metrics for tracing
        dataset_size_mb = dataset.nbytes / 1024 / 1024
        num_variables = len(dataset.data_vars)

        # Write to Icechunk, timed via the lightweight stage_timer (see
        # canvodpy/logging/stage_timer.py) -- replaces the removed
        # OpenTelemetry-based telemetry.py, which required an optional
        # dependency that was never actually installed.
        with stage_timer(
            "icechunk.write",
            group=group_name,
            size_mb=round(dataset_size_mb, 2),
            num_variables=num_variables,
        ):
            to_icechunk(dataset, session, group=group_name, mode=mode)

        self._logger.info(f"Wrote dataset to group '{group_name}' (mode={mode})")

    def write_initial_group(
        self,
        dataset: xr.Dataset,
        group_name: str,
        branch: str = "main",
        commit_message: str | None = None,
    ) -> None:
        """Write initial data to a new group."""
        if self.group_exists(group_name, branch):
            raise ValueError(
                f"Group '{group_name}' already exists. Use append_to_group() instead."
            )

        dataset = self._normalize_encodings(dataset)

        rinex_hash = dataset.attrs.get("File Hash")
        if rinex_hash is None:
            raise ValueError("Dataset missing 'File Hash' attribute")
        start = dataset.epoch.min().values
        end = dataset.epoch.max().values

        if commit_message is None:
            version = get_version_from_pyproject()
            commit_message = f"[v{version}] Initial commit to group '{group_name}'"

        with self.writable_session(branch) as session:
            to_icechunk(dataset, session, group=group_name, mode="w")
            zroot = zarr.open_group(session.store, mode="a")
            self._append_metadata_row(
                zroot=zroot,
                group_name=group_name,
                rinex_hash=rinex_hash,
                start=start,
                end=end,
                snapshot_id="",
                action="write",
                commit_msg=commit_message,
                dataset_attrs=dataset.attrs,
            )
            session.commit(_with_run_id(commit_message))

        self._logger.info(
            f"Created group '{group_name}' with {len(dataset.epoch)} epochs, "
            f"hash={rinex_hash}"
        )

    def backup_metadata_table(
        self,
        group_name: str,
        session: Any,
    ) -> pl.DataFrame | None:
        """Backup the metadata table to a Polars DataFrame.

        Parameters
        ----------
        group_name : str
            Group name.
        session : Any
            Active session for reading.

        Returns
        -------
        pl.DataFrame | None
            DataFrame with metadata rows, or None if missing.
        """
        try:
            zroot = zarr.open_group(session.store, mode="r")
            meta_group_path = f"{group_name}/metadata/table"

            if (
                "metadata" not in zroot[group_name]
                or "table" not in zroot[group_name]["metadata"]
            ):
                self._logger.info(
                    "No metadata table found for group "
                    f"'{group_name}' - nothing to backup"
                )
                return None

            zmeta = zroot[meta_group_path]

            # Load all columns into a dictionary
            data = {}
            for col_name in zmeta.array_keys():
                data[col_name] = zmeta[col_name][:]

            # Convert to Polars DataFrame
            df = pl.DataFrame(data)

            self._logger.info(
                "Backed up metadata table with "
                f"{df.height} rows for group '{group_name}'"
            )
            return df

        except Exception as e:
            self._logger.warning(
                f"Failed to backup metadata table for group '{group_name}': {e}"
            )
            return None

    def restore_metadata_table(
        self,
        group_name: str,
        df: pl.DataFrame,
        session: Any,
    ) -> None:
        """Restore the metadata table from a Polars DataFrame.

        This recreates the full Zarr structure for the metadata table.

        Parameters
        ----------
        group_name : str
            Group name.
        df : pl.DataFrame
            Metadata table to restore.
        session : Any
            Active session for writing.

        Returns
        -------
        None
        """
        if df is None or df.height == 0:
            self._logger.info(f"No metadata to restore for group '{group_name}'")
            return

        try:
            zroot = zarr.open_group(session.store, mode="a")
            meta_group_path = f"{group_name}/metadata/table"

            # Create the metadata subgroup
            zmeta = zroot.require_group(meta_group_path)

            # Create all arrays from the DataFrame
            for col_name in df.columns:
                col_data = df[col_name]

                if col_name == "index":
                    # Index column as int64
                    arr = col_data.to_numpy().astype("i8")
                    dtype = "i8"
                elif col_name in ("start", "end"):
                    # Datetime columns
                    arr = col_data.to_numpy().astype("datetime64[ns]")
                    dtype = "M8[ns]"
                else:
                    # String columns - use VariableLengthUTF8
                    arr = col_data.to_list()  # Convert to list for VariableLengthUTF8
                    dtype = VariableLengthUTF8()

                # Create the array
                zmeta.create_array(
                    name=col_name,
                    shape=(len(arr),),
                    dtype=dtype,
                    chunks=(1024,),
                    overwrite=True,
                )

                # Write the data
                zmeta[col_name][:] = arr

            self._logger.info(
                "Restored metadata table with "
                f"{df.height} rows for group '{group_name}'"
            )

        except Exception as e:
            self._logger.error(
                f"Failed to restore metadata table for group '{group_name}': {e}"
            )
            raise RuntimeError(
                f"Critical error: could not restore metadata table: {e}"
            ) from e

    def overwrite_file_in_group(
        self,
        dataset: xr.Dataset,
        group_name: str,
        rinex_hash: str,
        start: np.datetime64,
        end: np.datetime64,
        branch: str = "main",
        commit_message: str | None = None,
    ) -> None:
        """Overwrite a file's contribution to the group (same hash, new epoch range)."""

        dataset = self._normalize_encodings(dataset)

        # --- Step 3: rewrite store ---
        with self.writable_session(branch) as session:
            ds_from_store = xr.open_zarr(
                session.store, group=group_name, consolidated=False
            ).compute(
                scheduler="synchronous"
            )  # synchronous avoids Dask serialization error

            # Backup the existing metadata table
            metadata_backup = self.backup_metadata_table(group_name, session)

            mask = (ds_from_store.epoch.values < start) | (
                ds_from_store.epoch.values > end
            )
            ds_from_store_cleansed = ds_from_store.isel(epoch=mask)
            ds_from_store_cleansed = self._normalize_encodings(ds_from_store_cleansed)

            # Check if any epochs remain after cleansing, then write leftovers.
            if ds_from_store_cleansed.sizes.get("epoch", 0) > 0:
                to_icechunk(ds_from_store_cleansed, session, group=group_name, mode="w")
            # no epochs left, reset group to empty
            else:
                to_icechunk(dataset.isel(epoch=[]), session, group=group_name, mode="w")

            # write back the backed up metadata table
            self.restore_metadata_table(group_name, metadata_backup, session)

            # Append the new dataset
            to_icechunk(dataset, session, group=group_name, append_dim="epoch")

            if commit_message is None:
                version = get_version_from_pyproject()
                commit_message = (
                    f"[v{version}] Overwrote file {rinex_hash} in group '{group_name}'"
                )

            zroot = zarr.open_group(session.store, mode="a")
            self._append_metadata_row(
                zroot=zroot,
                group_name=group_name,
                rinex_hash=rinex_hash,
                start=start,
                end=end,
                snapshot_id="",
                action="overwrite",
                commit_msg=commit_message,
                dataset_attrs=dataset.attrs,
            )
            session.commit(_with_run_id(commit_message))

    def get_group_info(self, group_name: str, branch: str = "main") -> dict[str, Any]:
        """
        Get metadata about a group.

        Parameters
        ----------
        group_name : str
            Name of the group.
        branch : str, default "main"
            Repository branch to examine.

        Returns
        -------
        dict[str, Any]
            Group metadata.

        Raises
        ------
        ValueError
            If the group does not exist.
        """
        if not self.group_exists(group_name, branch):
            raise ValueError(f"Group '{group_name}' does not exist")

        ds = self.read_group(group_name, branch)

        info = {
            "group_name": group_name,
            "store_type": self.store_type,
            "dimensions": dict(ds.sizes),
            "variables": list(ds.data_vars.keys()),
            "coordinates": list(ds.coords.keys()),
            "attributes": dict(ds.attrs),
        }

        # Add temporal information if epoch dimension exists
        if "epoch" in ds.sizes:
            info["temporal_info"] = {
                "start": str(ds.epoch.min().values),
                "end": str(ds.epoch.max().values),
                "count": ds.sizes["epoch"],
                "resolution": str(ds.epoch.diff("epoch").median().values),
            }

        return info

    # ── Generic metadata datasets ─────────────────────────────────────────────

    def metadata_dataset_exists(
        self, group_name: str, name: str, branch: str = "main"
    ) -> bool:
        """Return True if a metadata dataset *name* exists for *group_name*."""
        try:
            session = self.repo.readonly_session(branch)
            root = zarr.open_group(session.store, mode="r")
            meta = root.get(f"{group_name}/metadata", None)
            return meta is not None and name in meta
        except Exception:
            return False

    def write_metadata_dataset(
        self,
        meta_ds: xr.Dataset,
        group_name: str,
        name: str,
        branch: str = "main",
    ) -> str:
        """Write a pre-concatenated metadata dataset to *{group_name}/metadata/{name}*.

        Always writes with ``mode="w"`` (full overwrite for the day).

        Parameters
        ----------
        meta_ds : xr.Dataset
            Pre-concatenated ``(epoch, sid)`` metadata dataset.
        group_name : str
            Target group (receiver name).
        name : str
            Dataset name under ``metadata/`` (e.g. ``"sbf_obs"``).
        branch : str, default "main"
            Repository branch to write to.

        Returns
        -------
        str
            Icechunk snapshot ID.
        """
        version = get_version_from_pyproject()
        path = f"{group_name}/metadata/{name}"
        ds = self._normalize_encodings(meta_ds)
        ds = self._cleanse_dataset_attrs(ds)
        with self.writable_session(branch) as session:
            to_icechunk(ds, session, group=path, mode="w")
            return session.commit(
                _with_run_id(f"[v{version}] metadata/{name} for {group_name}")
            )

    def append_metadata_datasets(
        self,
        parts: list[xr.Dataset],
        group_name: str,
        name: str,
        branch: str = "main",
    ) -> str:
        """Write metadata datasets incrementally — no in-memory concat.

        The first dataset initialises the group (``mode="w"``), subsequent
        datasets are appended along ``epoch``.  All writes happen inside a
        single session/commit so the operation is atomic.

        Parameters
        ----------
        parts : list[xr.Dataset]
            Individual per-file metadata datasets with an ``epoch`` dim.
        group_name : str
            Target group (receiver name).
        name : str
            Dataset name under ``metadata/`` (e.g. ``"sbf_obs"``).
        branch : str, default "main"
            Repository branch to write to.

        Returns
        -------
        str
            Icechunk snapshot ID.
        """
        if not parts:
            msg = "parts list is empty"
            raise ValueError(msg)

        version = get_version_from_pyproject()
        path = f"{group_name}/metadata/{name}"
        total_epochs = 0

        with self.writable_session(branch) as session:
            for i, part in enumerate(parts):
                ds = self._normalize_encodings(part)
                ds = self._cleanse_dataset_attrs(ds)
                if i == 0:
                    to_icechunk(ds, session, group=path, mode="w")
                else:
                    to_icechunk(ds, session, group=path, append_dim="epoch")
                total_epochs += ds.sizes.get("epoch", 0)

            return session.commit(
                _with_run_id(
                    f"[v{version}] metadata/{name} for {group_name} "
                    f"({total_epochs} epochs)"
                )
            )

    def read_metadata_dataset(
        self,
        group_name: str,
        name: str,
        branch: str = "main",
        chunks: dict | None = None,
    ) -> xr.Dataset:
        """Read a metadata dataset *name* for *group_name*.

        Parameters
        ----------
        group_name : str
            Group (receiver) name.
        name : str
            Dataset name under ``metadata/`` (e.g. ``"sbf_obs"``).
        branch : str, default "main"
            Repository branch.
        chunks : dict | None, optional
            Dask chunk specification.  Defaults to
            ``{"epoch": 17280, "sid": -1}``.

        Returns
        -------
        xr.Dataset
            Lazy ``(epoch, sid)`` metadata dataset.
        """
        path = f"{group_name}/metadata/{name}"
        with self.readonly_session(branch) as session:
            return xr.open_zarr(
                session.store,
                group=path,
                chunks=chunks or self.chunk_strategy or {"epoch": 17280, "sid": -1},
                consolidated=False,
            )

    def get_metadata_dataset_info(
        self,
        group_name: str,
        name: str,
        branch: str = "main",
    ) -> dict[str, Any]:
        """Get info about metadata dataset *name* for *group_name*.

        Parameters
        ----------
        group_name : str
            Group (receiver) name.
        name : str
            Dataset name under ``metadata/`` (e.g. ``"sbf_obs"``).
        branch : str, default "main"
            Repository branch.

        Returns
        -------
        dict[str, Any]
            Info dict with the same structure as ``get_group_info()``.

        Raises
        ------
        ValueError
            If the metadata dataset does not exist.
        """
        if not self.metadata_dataset_exists(group_name, name, branch):
            raise ValueError(f"No metadata dataset '{name}' for group '{group_name}'")
        ds = self.read_metadata_dataset(group_name, name, branch, chunks={})
        info: dict[str, Any] = {
            "group_name": group_name,
            "store_path": f"{group_name}/metadata/{name}",
            "store_type": f"metadata/{name}",
            "dimensions": dict(ds.sizes),
            "variables": list(ds.data_vars.keys()),
            "coordinates": list(ds.coords.keys()),
            "attributes": dict(ds.attrs),
        }
        if "epoch" in ds.sizes:
            info["temporal_info"] = {
                "start": str(ds.epoch.min().values),
                "end": str(ds.epoch.max().values),
                "count": ds.sizes["epoch"],
                "resolution": str(ds.epoch.diff("epoch").median().values),
            }
        return info

    # Convenience aliases (SBF)
    def sbf_metadata_exists(self, group_name: str, branch: str = "main") -> bool:
        """Return True if an SBF metadata dataset exists for *group_name*."""
        return self.metadata_dataset_exists(group_name, "sbf_obs", branch)

    def write_sbf_metadata(
        self, meta_ds: xr.Dataset, group_name: str, branch: str = "main"
    ) -> str:
        """Write SBF metadata dataset."""
        return self.write_metadata_dataset(meta_ds, group_name, "sbf_obs", branch)

    def read_sbf_metadata(
        self, group_name: str, branch: str = "main", chunks: dict | None = None
    ) -> xr.Dataset:
        """Read SBF metadata dataset."""
        return self.read_metadata_dataset(group_name, "sbf_obs", branch, chunks)

    def get_sbf_metadata_info(
        self, group_name: str, branch: str = "main"
    ) -> dict[str, Any]:
        """Get SBF metadata info."""
        return self.get_metadata_dataset_info(group_name, "sbf_obs", branch)

    def rel_path_for_commit(self, file_path: Path) -> str:
        """
        Generate relative path for commit messages.

        Parameters
        ----------
        file_path : Path
            Full file path.

        Returns
        -------
        str
            Relative path string with log_path_depth parts.
        """
        return str(Path(*file_path.parts[-self._log_path_depth :]))

    def get_store_stats(self) -> dict[str, Any]:
        """
        Get statistics about the store.

        Returns
        -------
        dict[str, Any]
            Store statistics.
        """
        groups = self.get_group_names()
        # groups maps branch name -> list of group names (e.g. {"main": ["canopy_01"]});
        # flatten + dedup to count distinct groups rather than branches.
        all_group_names = {name for names in groups.values() for name in names}
        stats = {
            "store_path": str(self.store_path),
            "store_type": self.store_type,
            "compression_level": self.compression_level,
            # icechunk v2's CompressionAlgorithm has no .name attribute
            # (PyO3 enum wrapper, unlike Python's enum.Enum) — str() gives
            # "CompressionAlgorithm.Zstd"; take the part after the dot.
            "compression_algorithm": str(self.compression_algorithm).rsplit(".", 1)[-1],
            "total_groups": len(all_group_names),
            "groups": groups,
        }

        # Add group-specific stats (from "main" — get_group_info()'s default branch)
        for group_name in groups.get("main", []):
            try:
                info = self.get_group_info(group_name)
                stats[f"group_{group_name}"] = {
                    "dimensions": info["dimensions"],
                    "variables_count": len(info["variables"]),
                    "has_temporal_data": "temporal_info" in info,
                }
            except Exception as e:
                self._logger.warning(
                    f"Failed to get stats for group '{group_name}': {e}"
                )

        return stats

    def append_to_group(
        self,
        dataset: xr.Dataset,
        group_name: str,
        append_dim: str = "epoch",
        branch: str = "main",
        action: str = "write",
        commit_message: str | None = None,
    ) -> None:
        """Append data to an existing group."""
        if not self.group_exists(group_name, branch):
            raise ValueError(
                f"Group '{group_name}' does not exist. Use write_initial_group() first."
            )

        dataset = self._normalize_encodings(dataset)

        rinex_hash = dataset.attrs.get("File Hash")
        if rinex_hash is None:
            raise ValueError("Dataset missing 'File Hash' attribute")
        start = dataset.epoch.min().values
        end = dataset.epoch.max().values

        # Guard: check hash + temporal overlap before appending
        exists, matches = self.metadata_row_exists(
            group_name, rinex_hash, start, end, branch
        )
        if exists and action != "overwrite":
            self._logger.warning(
                "append_blocked_by_guardrail",
                group=group_name,
                hash=rinex_hash[:16],
                range=f"{start} → {end}",
                reason="hash_or_temporal_overlap",
                matching_files=matches.height if not matches.is_empty() else 0,
            )
            return

        if commit_message is None and action == "write":
            version = get_version_from_pyproject()
            commit_message = f"[v{version}] Wrote to group '{group_name}'"
        elif commit_message is None and action == "append":
            version = get_version_from_pyproject()
            commit_message = f"[v{version}] Appended to group '{group_name}'"
        elif commit_message is None:
            version = get_version_from_pyproject()
            commit_message = f"[v{version}] {action} to group '{group_name}'"

        with self.writable_session(branch) as session:
            to_icechunk(dataset, session, group=group_name, append_dim=append_dim)
            zroot = zarr.open_group(session.store, mode="a")
            self._append_metadata_row(
                zroot=zroot,
                group_name=group_name,
                rinex_hash=rinex_hash,
                start=start,
                end=end,
                snapshot_id="",
                action=action,
                commit_msg=commit_message,
                dataset_attrs=dataset.attrs,
            )
            session.commit(_with_run_id(commit_message))

        if action == "append":
            self._logger.info(
                f"Appended {len(dataset.epoch)} epochs to group '{group_name}', "
                f"hash={rinex_hash}"
            )
        elif action == "write":
            self._logger.info(
                f"Wrote {len(dataset.epoch)} epochs to group '{group_name}', "
                f"hash={rinex_hash}"
            )
        else:
            self._logger.info(
                f"Action '{action}' completed for group '{group_name}', "
                f"hash={rinex_hash}"
            )

    def write_or_append_group(
        self,
        dataset: xr.Dataset,
        group_name: str,
        append_dim: str = "epoch",
        branch: str = "main",
        commit_message: str | None = None,
        dedup: bool = False,
    ) -> bool:
        """Write or append a dataset to a group.

        By default (``dedup=False``) no guardrails are applied — suitable for
        VOD stores and other derived-data stores where rinex-style dedup does
        not apply.

        When ``dedup=True`` the method runs a full hash-match + temporal-overlap
        check (via :meth:`should_skip_file`) **before** opening a write session.
        This makes the store the authoritative final gate for RINEX/SBF ingest
        paths, backstopping any pre-checks in the caller.

        If the group does not exist, creates it (``mode='w'``).
        If it exists, appends along ``append_dim``.

        Parameters
        ----------
        dataset : xr.Dataset
            Dataset to write or append.
        group_name : str
            Target Icechunk group.
        append_dim : str, default "epoch"
            Dimension along which to append when the group already exists.
        branch : str, default "main"
            Icechunk branch to write to.
        commit_message : str or None
            Commit message.  Auto-generated if ``None``.
        dedup : bool, default False
            When ``True``, check for duplicate hash or temporal overlap before
            writing.  If the dataset would be a duplicate, the write is skipped,
            a warning is logged, and ``False`` is returned.  Set to ``True`` for
            RINEX/SBF ingest; leave ``False`` for VOD and derived-data stores.

        Returns
        -------
        bool
            ``True`` if the dataset was written, ``False`` if skipped
            (only possible when ``dedup=True``).
        """
        if dedup:
            file_hash = dataset.attrs.get("File Hash")
            time_start = dataset.epoch.min().values
            time_end = dataset.epoch.max().values
            skip, reason = self.should_skip_file(
                group_name=group_name,
                file_hash=file_hash,
                time_start=time_start,
                time_end=time_end,
                branch=branch,
            )
            if skip:
                self._logger.warning(
                    "write_or_append_group skipped duplicate",
                    group=group_name,
                    reason=reason,
                    file_hash=file_hash,
                )
                return False

        dataset = self._normalize_encodings(dataset)

        if self.group_exists(group_name, branch):
            with self.writable_session(branch) as session:
                to_icechunk(dataset, session, group=group_name, append_dim=append_dim)
                if commit_message is None:
                    commit_message = f"Appended to group '{group_name}'"
                session.commit(_with_run_id(commit_message))
            self._logger.info(
                f"Appended {len(dataset.epoch)} epochs to group '{group_name}'"
            )
        else:
            with self.writable_session(branch) as session:
                to_icechunk(dataset, session, group=group_name, mode="w")
                if commit_message is None:
                    commit_message = f"Created group '{group_name}'"
                session.commit(_with_run_id(commit_message))
            self._logger.info(
                f"Created group '{group_name}' with {len(dataset.epoch)} epochs"
            )
        return True

    def _append_metadata_row(
        self,
        zroot: zarr.Group,
        group_name: str,
        rinex_hash: str,
        start: np.datetime64,
        end: np.datetime64,
        snapshot_id: str,
        action: str,
        commit_msg: str,
        dataset_attrs: dict,
        canonical_name: str | None = None,
        physical_path: str | None = None,
    ) -> None:
        """Write one metadata row into an already-open zarr group (no session/commit).

        Must be called inside an active writable session or transaction so the
        caller controls the commit boundary. This is the canonical implementation;
        ``append_metadata`` is a thin standalone wrapper around it.

        Schema:
            index           int64 (continuous row id)
            rinex_hash      str   (UTF-8, VariableLengthUTF8)
            start           datetime64[ns]
            end             datetime64[ns]
            snapshot_id     str   (UTF-8; empty string when written inside a
                                  combined data+metadata commit — the commit ID
                                  is recoverable via repo.ancestry())
            action          str   (UTF-8, e.g. "write"|"append"|"overwrite")
            commit_msg      str   (UTF-8)
            written_at      str   (UTF-8, ISO8601 with timezone)
            write_strategy  str   (UTF-8)
            attrs           str   (UTF-8, JSON dump of dataset attrs)
            canonical_name  str   (UTF-8)
            physical_path   str   (UTF-8)
        """
        written_at = datetime.now().astimezone().isoformat()
        row = {
            "rinex_hash": str(rinex_hash),
            "start": np.datetime64(start, "ns"),
            "end": np.datetime64(end, "ns"),
            "snapshot_id": str(snapshot_id),
            "action": str(action),
            "commit_msg": str(commit_msg),
            "written_at": written_at,
            "write_strategy": str(self._rinex_store_strategy)
            if self.store_type == "rinex_store"
            else str(self._vod_store_strategy),
            "attrs": json.dumps(dataset_attrs, default=str),
            "canonical_name": str(canonical_name) if canonical_name else "",
            "physical_path": str(physical_path) if physical_path else "",
        }
        df_row = pl.DataFrame([row])
        meta_group_path = f"{group_name}/metadata/table"

        if (
            "metadata" not in zroot[group_name]
            or "table" not in zroot[group_name]["metadata"]
        ):
            zmeta = zroot.require_group(meta_group_path)
            zmeta.create_array(
                name="index", shape=(0,), dtype="i8", chunks=(1024,), overwrite=True
            )
            zmeta["index"].append([0])
            for col in df_row.columns:
                if col in ("start", "end"):
                    dtype = "M8[ns]"
                    arr = np.array(df_row[col].to_numpy(), dtype=dtype)
                else:
                    dtype = VariableLengthUTF8()
                    arr = df_row[col].to_list()
                zmeta.create_array(
                    name=col, shape=(0,), dtype=dtype, chunks=(1024,), overwrite=True
                )
                zmeta[col].append(arr)
        else:
            zmeta = zroot[meta_group_path]
            current_len = zmeta["index"].shape[0]
            zmeta["index"].append([current_len])
            for col in df_row.columns:
                if col in ("start", "end"):
                    arr = np.array(df_row[col].to_numpy(), dtype="M8[ns]")
                else:
                    arr = df_row[col].to_list()
                zmeta[col].append(arr)

    def append_metadata(
        self,
        group_name: str,
        rinex_hash: str,
        start: np.datetime64,
        end: np.datetime64,
        snapshot_id: str,
        action: str,
        commit_msg: str,
        dataset_attrs: dict,
        branch: str = "main",
        canonical_name: str | None = None,
        physical_path: str | None = None,
    ) -> None:
        """Standalone metadata-row append — opens its own transaction.

        For ingest paths (write_initial_group, append_to_group) use
        _append_metadata_row directly inside the data-write session to avoid
        an extra commit per file.
        """
        message = f"Appended metadata row for {group_name}, hash={rinex_hash}"
        with self.repo.transaction(branch, message=message) as store:
            zroot = zarr.open_group(store, mode="a")
            self._append_metadata_row(
                zroot=zroot,
                group_name=group_name,
                rinex_hash=rinex_hash,
                start=start,
                end=end,
                snapshot_id=snapshot_id,
                action=action,
                commit_msg=commit_msg,
                dataset_attrs=dataset_attrs,
                canonical_name=canonical_name,
                physical_path=physical_path,
            )

        self._logger.info(
            f"Metadata appended for group '{group_name}': "
            f"hash={rinex_hash}, snapshot={snapshot_id}, action={action}"
        )

    def append_metadata_bulk(
        self,
        group_name: str,
        rows: list[dict[str, Any]],
        session: icechunk.WritableSession | None = None,
    ) -> None:
        """
        Append multiple metadata rows in one commit.

        Parameters
        ----------
        group_name : str
            Group name (e.g. "canopy", "reference")
        rows : list[dict[str, Any]]
            List of metadata records matching the schema used in
            append_metadata().
        session : icechunk.WritableSession, optional
            If provided, rows are written into this session (caller commits later).
            If None, this method opens its own writable session and commits once.
        """
        if not rows:
            self._logger.info(f"No metadata rows to append for group '{group_name}'")
            return

        # Ensure datetime conversions for consistency
        for row in rows:
            if isinstance(row.get("start"), str):
                row["start"] = np.datetime64(row["start"])
            if isinstance(row.get("end"), str):
                row["end"] = np.datetime64(row["end"])
            if "written_at" not in row:
                row["written_at"] = datetime.now(UTC).isoformat()

        # Prepare the Polars DataFrame
        df = pl.DataFrame(rows)

        def _do_append(session_obj: icechunk.WritableSession) -> None:
            """Append metadata rows to a writable session.

            Parameters
            ----------
            session_obj : icechunk.WritableSession
                Writable session to update.

            Returns
            -------
            None
            """
            zroot = zarr.open_group(session_obj.store, mode="a")
            meta_group_path = f"{group_name}/metadata/table"
            zmeta = zroot.require_group(meta_group_path)

            start_index = 0
            if "index" in zmeta:
                existing_len = zmeta["index"].shape[0]
                start_index = (
                    int(zmeta["index"][-1].item()) + 1 if existing_len > 0 else 0
                )

            # Assign sequential indices
            df_with_index = df.with_columns(
                (pl.arange(start_index, start_index + df.height)).alias("index")
            )

            # Write each column
            for col_name in df_with_index.columns:
                col_data = df_with_index[col_name]

                if col_name == "index":
                    dtype = "i8"
                    arr = col_data.to_numpy().astype(dtype)
                elif col_name in ("start", "end"):
                    dtype = "M8[ns]"
                    arr = col_data.to_numpy().astype(dtype)
                else:
                    # strings / jsons / ids
                    dtype = VariableLengthUTF8()
                    arr = col_data.to_list()

                if col_name not in zmeta:
                    # Create array if it doesn't exist
                    zmeta.create_array(
                        name=col_name,
                        shape=(0,),
                        dtype=dtype,
                        chunks=(1024,),
                        overwrite=True,
                    )

                # Resize and append
                old_len = zmeta[col_name].shape[0]
                new_len = old_len + len(arr)
                zmeta[col_name].resize(new_len)
                zmeta[col_name][old_len:new_len] = arr

            self._logger.info(
                f"Appended {df_with_index.height} metadata rows to group '{group_name}'"
            )

        if session is not None:
            _do_append(session)
        else:
            with self.writable_session() as sess:
                _do_append(sess)
                sess.commit(_with_run_id(f"Bulk metadata append for {group_name}"))

    # ------------------------------------------------------------------
    # VOD store: {model}/{analysis_name} group hierarchy + dedicated ledger
    # ------------------------------------------------------------------
    #
    # A VOD computation reads from *two* receivers, so there is no single
    # "File Hash" to dedup on (unlike RINEX ingest). The methods below are
    # a parallel, VOD-shaped equivalent of should_skip_file()/
    # metadata_row_exists()/append_to_group() — same hash+temporal-overlap
    # guardrail pattern, but keyed on a combined per-receiver hash dict
    # instead of one flat rinex_hash column, and with a ledger schema that
    # also records calculator_name and per-receiver provenance
    # (source_gnss_stores). See dev/todo_later.md §29.

    def _append_vod_metadata_row(
        self,
        zroot: zarr.Group,
        group_name: str,
        source_file_hashes: dict[str, str],
        source_gnss_stores: dict[str, str],
        start: np.datetime64,
        end: np.datetime64,
        snapshot_id: str,
        action: str,
        commit_msg: str,
        calculator_name: str,
        dataset_attrs: dict,
    ) -> None:
        """Write one VOD metadata row into an already-open zarr group.

        Must be called inside an active writable session so the caller
        controls the commit boundary (mirrors ``_append_metadata_row``).

        Schema:
            index               int64
            source_file_hashes  str (UTF-8, JSON dict {receiver_name: hash},
                                 sorted keys — doubles as the dedup key)
            source_gnss_stores  str (UTF-8, JSON dict {receiver_name: store_path})
            start               datetime64[ns]
            end                 datetime64[ns]
            snapshot_id         str (UTF-8)
            action              str (UTF-8, "write"|"append"|"overwrite")
            commit_msg          str (UTF-8)
            written_at          str (UTF-8, ISO8601 with timezone)
            write_strategy      str (UTF-8)
            calculator_name     str (UTF-8)
            attrs               str (UTF-8, JSON dump of dataset attrs)
        """
        written_at = datetime.now().astimezone().isoformat()
        row = {
            "source_file_hashes": json.dumps(source_file_hashes, sort_keys=True),
            "source_gnss_stores": json.dumps(source_gnss_stores, sort_keys=True),
            "start": np.datetime64(start, "ns"),
            "end": np.datetime64(end, "ns"),
            "snapshot_id": str(snapshot_id),
            "action": str(action),
            "commit_msg": str(commit_msg),
            "written_at": written_at,
            "write_strategy": str(self._vod_store_strategy),
            "calculator_name": str(calculator_name),
            "attrs": json.dumps(dataset_attrs, default=str),
        }
        df_row = pl.DataFrame([row])
        meta_group_path = f"{group_name}/metadata/table"

        if (
            "metadata" not in zroot[group_name]
            or "table" not in zroot[group_name]["metadata"]
        ):
            zmeta = zroot.require_group(meta_group_path)
            zmeta.create_array(
                name="index", shape=(0,), dtype="i8", chunks=(1024,), overwrite=True
            )
            zmeta["index"].append([0])
            for col in df_row.columns:
                if col in ("start", "end"):
                    dtype = "M8[ns]"
                    arr = np.array(df_row[col].to_numpy(), dtype=dtype)
                else:
                    dtype = VariableLengthUTF8()
                    arr = df_row[col].to_list()
                zmeta.create_array(
                    name=col, shape=(0,), dtype=dtype, chunks=(1024,), overwrite=True
                )
                zmeta[col].append(arr)
        else:
            zmeta = zroot[meta_group_path]
            current_len = zmeta["index"].shape[0]
            zmeta["index"].append([current_len])
            for col in df_row.columns:
                if col in ("start", "end"):
                    arr = np.array(df_row[col].to_numpy(), dtype="M8[ns]")
                else:
                    arr = df_row[col].to_list()
                zmeta[col].append(arr)

    def _vod_metadata_row_exists(
        self,
        group_name: str,
        source_hash_key: str,
        start: np.datetime64,
        end: np.datetime64,
        branch: str = "main",
    ) -> tuple[bool, pl.DataFrame]:
        """Check whether a VOD computation already exists or overlaps temporally.

        Analogous to :meth:`metadata_row_exists`, but compares against the
        ``source_file_hashes`` column (a canonical, sorted-keys JSON string)
        instead of a single flat hash column.

        Parameters
        ----------
        group_name : str
            ``{model}/{analysis_name}`` group path.
        source_hash_key : str
            ``json.dumps(source_file_hashes, sort_keys=True)`` for the
            incoming computation.
        start, end : np.datetime64
            Epoch range of the incoming VOD dataset.
        branch : str, default "main"

        Returns
        -------
        tuple[bool, pl.DataFrame]
            ``(True, matching_rows)`` when this should be skipped,
            ``(False, empty_df)`` when it is safe to write.
        """
        with self.readonly_session(branch) as session:
            try:
                zmeta = zarr.open_group(session.store, mode="r")[
                    f"{group_name}/metadata/table"
                ]
            except Exception:
                return False, pl.DataFrame()

            data = {col: zmeta[col][:] for col in zmeta.array_keys()}
            df = pl.DataFrame(data)
            df = df.with_columns(
                [
                    pl.col("start").cast(pl.Datetime("ns")),
                    pl.col("end").cast(pl.Datetime("ns")),
                ]
            )

            hash_matches = df.filter(pl.col("source_file_hashes") == source_hash_key)
            if not hash_matches.is_empty():
                return True, hash_matches

            start_ns = np.datetime64(start, "ns")
            end_ns = np.datetime64(end, "ns")
            overlaps = df.filter(
                (pl.col("start") <= end_ns) & (pl.col("end") >= start_ns)
            )
            if not overlaps.is_empty():
                self._logger.warning(
                    "vod_temporal_overlap_detected",
                    group=group_name,
                    incoming_range=f"{start} → {end}",
                    existing_range=(
                        f"{overlaps['start'].min()} → {overlaps['end'].max()}"
                    ),
                    overlapping_rows=overlaps.height,
                )
                return True, overlaps

            return False, pl.DataFrame()

    def should_skip_vod_write(
        self,
        group_name: str,
        source_file_hashes: dict[str, str],
        time_start: np.datetime64,
        time_end: np.datetime64,
        branch: str = "main",
    ) -> tuple[bool, str]:
        """Check whether a VOD write should be skipped as a duplicate.

        Parameters
        ----------
        group_name : str
            ``{model}/{analysis_name}`` group path.
        source_file_hashes : dict[str, str]
            ``{receiver_name: "File Hash"}`` for every receiver the
            computation read from.
        time_start, time_end : np.datetime64
            Epoch range of the incoming VOD dataset.
        branch : str, default "main"

        Returns
        -------
        tuple[bool, str]
            ``(True, "hash_match")``, ``(True, "temporal_overlap")``, or
            ``(False, "")``.
        """
        source_hash_key = json.dumps(source_file_hashes, sort_keys=True)
        exists, matches = self._vod_metadata_row_exists(
            group_name, source_hash_key, time_start, time_end, branch
        )
        if not exists:
            return False, ""
        if (
            not matches.is_empty()
            and (matches["source_file_hashes"] == source_hash_key).any()
        ):
            return True, "hash_match"
        return True, "temporal_overlap"

    def write_or_append_vod_group(
        self,
        dataset: xr.Dataset,
        group_name: str,
        source_file_hashes: dict[str, str],
        source_gnss_stores: dict[str, str],
        calculator_name: str,
        append_dim: str = "epoch",
        branch: str = "main",
        commit_message: str | None = None,
        dedup: bool = True,
    ) -> bool:
        """Write or append a VOD analysis dataset, with its own metadata ledger.

        ``group_name`` is expected to be ``{model}/{analysis_name}`` (e.g.
        ``"tau_omega_zeroth_order/canopy_01_vs_reference_01"``) — the model
        layer disambiguates results from different VOD calculators sharing
        the same analysis pair. Data write and metadata-row write happen in
        one Icechunk commit, mirroring :meth:`append_to_group`.

        Parameters
        ----------
        dataset : xr.Dataset
            Computed VOD dataset to write or append.
        group_name : str
            Target ``{model}/{analysis_name}`` group.
        source_file_hashes : dict[str, str]
            ``{receiver_name: "File Hash"}`` for every receiver the
            computation read from — the dedup key (no single hash exists
            for a two-receiver computation).
        source_gnss_stores : dict[str, str]
            ``{receiver_name: rinex_store_path}`` — provenance back to the
            GNSS store(s) the inputs came from.
        calculator_name : str
            Registered ``VODFactory`` name (e.g. ``"tau_omega"``).
        append_dim : str, default "epoch"
        branch : str, default "main"
        commit_message : str or None
            Auto-generated if ``None``.
        dedup : bool, default True
            When ``True``, skip the write if this exact source-hash
            combination was already written, or if the incoming epoch
            range temporally overlaps an existing row. Set ``False`` to
            force a write regardless (e.g. explicit overwrite/reprocessing).

        Returns
        -------
        bool
            ``True`` if written, ``False`` if skipped as a duplicate.
        """
        start = dataset.epoch.min().values
        end = dataset.epoch.max().values

        if dedup:
            skip, reason = self.should_skip_vod_write(
                group_name=group_name,
                source_file_hashes=source_file_hashes,
                time_start=start,
                time_end=end,
                branch=branch,
            )
            if skip:
                self._logger.warning(
                    "write_or_append_vod_group_skipped_duplicate",
                    group=group_name,
                    reason=reason,
                    calculator=calculator_name,
                )
                return False

        dataset = self._normalize_encodings(dataset)
        action = "append" if self.group_exists(group_name, branch) else "write"
        if commit_message is None:
            version = get_version_from_pyproject()
            commit_message = (
                f"[v{version}] {action.capitalize()}d VOD group '{group_name}' "
                f"(calculator={calculator_name})"
            )

        with self.writable_session(branch) as session:
            if action == "append":
                to_icechunk(dataset, session, group=group_name, append_dim=append_dim)
            else:
                to_icechunk(dataset, session, group=group_name, mode="w")
            zroot = zarr.open_group(session.store, mode="a")
            self._append_vod_metadata_row(
                zroot=zroot,
                group_name=group_name,
                source_file_hashes=source_file_hashes,
                source_gnss_stores=source_gnss_stores,
                start=start,
                end=end,
                snapshot_id="",
                action=action,
                commit_msg=commit_message,
                calculator_name=calculator_name,
                dataset_attrs=dict(dataset.attrs),
            )
            session.commit(_with_run_id(commit_message))

        self._logger.info(
            f"{action.capitalize()}d VOD group '{group_name}' "
            f"({len(dataset.epoch)} epochs, calculator={calculator_name})"
        )
        return True

    def load_metadata(self, store: Any, group_name: str) -> pl.DataFrame:
        """Load metadata directly from Zarr into a Polars DataFrame.

        Parameters
        ----------
        store : Any
            Zarr store or session store handle.
        group_name : str
            Group name.

        Returns
        -------
        pl.DataFrame
            Metadata table.
        """
        zroot = zarr.open_group(store, mode="r")
        zmeta = zroot[f"{group_name}/metadata/table"]

        # Read all columns into a dict of numpy arrays
        data = {col: zmeta[col][...] for col in zmeta.array_keys()}

        # Build Polars DataFrame
        df = pl.DataFrame(data)

        # Convert numeric datetime64 columns back to proper Polars datetimes
        if "start" in df.columns and df["start"].dtype in (pl.Int64, pl.Float64):
            df = df.with_columns(pl.col("start").cast(pl.Datetime("ns")))
        if "end" in df.columns and df["end"].dtype in (pl.Int64, pl.Float64):
            df = df.with_columns(pl.col("end").cast(pl.Datetime("ns")))
        if "written_at" in df.columns and df["written_at"].dtype == pl.Utf8:
            df = df.with_columns(pl.col("written_at").str.to_datetime("%+"))
        return df

    def read_metadata_table(self, session: Any, group_name: str) -> pl.DataFrame:
        """Read the metadata table from a session.

        Parameters
        ----------
        session : Any
            Active session for reading.
        group_name : str
            Group name.

        Returns
        -------
        pl.DataFrame
            Metadata table.
        """
        zmeta = zarr.open_group(
            session.store,
            mode="r",
        )[f"{group_name}/metadata/table"]

        data = {col: zmeta[col][:] for col in zmeta.array_keys()}
        df = pl.DataFrame(data)

        # Ensure start/end are proper datetime
        df = df.with_columns(
            [
                pl.col("start").cast(pl.Datetime("ns")),
                pl.col("end").cast(pl.Datetime("ns")),
            ]
        )
        return df

    def metadata_row_exists(
        self,
        group_name: str,
        rinex_hash: str,
        start: np.datetime64,
        end: np.datetime64,
        branch: str = "main",
    ) -> tuple[bool, pl.DataFrame]:
        """
        Check whether a file already exists or temporally overlaps existing data.

        Performs two checks in order:

        1. **Hash match** — if ``rinex_hash`` already appears in the metadata
           table, the file was previously ingested (exact duplicate).
        2. **Temporal overlap** — if the incoming ``[start, end]`` interval
           overlaps any existing metadata interval, the file covers a time
           range that is already (partially) present in the store.  This
           catches cases like a daily concatenation file coexisting with the
           sub-daily files it was built from.

        Parameters
        ----------
        group_name : str
            Icechunk group name.
        rinex_hash : str
            Hash of the current GNSS dataset.
        start : np.datetime64
            Start epoch of the incoming file.
        end : np.datetime64
            End epoch of the incoming file.
        branch : str, default "main"
            Branch name in the Icechunk repository.

        Returns
        -------
        tuple[bool, pl.DataFrame]
            ``(True, overlapping_rows)`` when the file should be skipped,
            ``(False, empty_df)`` when it is safe to ingest.
        """
        with self.readonly_session(branch) as session:
            try:
                zmeta = zarr.open_group(session.store, mode="r")[
                    f"{group_name}/metadata/table"
                ]
            except Exception:
                return False, pl.DataFrame()

            data = {col: zmeta[col][:] for col in zmeta.array_keys()}
            df = pl.DataFrame(data)

            df = df.with_columns(
                [
                    pl.col("start").cast(pl.Datetime("ns")),
                    pl.col("end").cast(pl.Datetime("ns")),
                ]
            )

            # --- Check 1: exact hash match (file already ingested) ---
            hash_matches = df.filter(pl.col("rinex_hash") == rinex_hash)
            if not hash_matches.is_empty():
                return True, hash_matches

            # --- Check 2: temporal overlap ---
            # Two intervals [A.start, A.end] and [B.start, B.end] overlap
            # iff A.start <= B.end AND A.end >= B.start
            start_ns = np.datetime64(start, "ns")
            end_ns = np.datetime64(end, "ns")

            overlaps = df.filter(
                (pl.col("start") <= end_ns) & (pl.col("end") >= start_ns)
            )

            if not overlaps.is_empty():
                n = overlaps.height
                existing_range = f"{overlaps['start'].min()} → {overlaps['end'].max()}"
                self._logger.warning(
                    "temporal_overlap_detected",
                    group=group_name,
                    incoming_hash=rinex_hash,
                    incoming_range=f"{start} → {end}",
                    existing_range=existing_range,
                    overlapping_files=n,
                )
                return True, overlaps

            return False, pl.DataFrame()

    def should_skip_file(
        self,
        group_name: str,
        file_hash: str | None,
        time_start: np.datetime64,
        time_end: np.datetime64,
        branch: str = "main",
    ) -> tuple[bool, str]:
        """Check whether a file should be skipped before processing and writing.

        Thin public wrapper around :meth:`metadata_row_exists` that returns a
        simple ``(skip, reason)`` pair instead of a DataFrame, suitable for use
        in Airflow task functions as an early-exit optimisation.

        This method is an early-exit optimisation: it avoids opening a write
        session for files that are already present.  Pass ``dedup=True`` to
        :meth:`write_or_append_group` to make the store the authoritative
        final gate (runs the same check again before writing).

        Checks performed (in order):

        1. **Hash match** — file was previously ingested (exact duplicate).
        2. **Temporal overlap** — incoming time range overlaps existing epochs.

        Layer 3 (intra-batch overlap) is not applicable here because task
        functions process files one at a time.

        Parameters
        ----------
        group_name : str
            Icechunk group name.
        file_hash : str or None
            Hash from ``dataset.attrs["File Hash"]``.  When ``None`` the check
            is skipped and ``(False, "")`` is returned.
        time_start : np.datetime64
            First epoch of the incoming dataset.
        time_end : np.datetime64
            Last epoch of the incoming dataset.
        branch : str, default "main"
            Branch name in the Icechunk repository.

        Returns
        -------
        tuple[bool, str]
            ``(True, "hash_match")`` — exact duplicate, skip.
            ``(True, "temporal_overlap")`` — overlapping time range, skip.
            ``(False, "")`` — safe to ingest.
        """
        if file_hash is None:
            return False, ""

        exists, matches = self.metadata_row_exists(
            group_name, file_hash, time_start, time_end, branch
        )
        if not exists:
            return False, ""

        if not matches.is_empty() and (matches["rinex_hash"] == file_hash).any():
            return True, "hash_match"
        return True, "temporal_overlap"

    def dir_entry_counts(self) -> dict[str, int]:
        """Cheap on-disk entry counts for ``manifests``/``snapshots``/``transactions``.

        A directional proxy for Icechunk-internal growth (manifest count,
        snapshot count) without walking the full store. Deliberately
        excludes ``chunks/`` (can reach millions of entries -- not cheap)
        and only applies to local-filesystem-backed stores; returns ``{}``
        for anything else (e.g. S3/GCS) since ``os.scandir`` doesn't apply.
        """
        counts: dict[str, int] = {}
        for name in ("manifests", "snapshots", "transactions"):
            d = self.store_path / name
            try:
                with os.scandir(d) as it:
                    counts[name] = sum(1 for _ in it)
            except OSError:
                continue
        return counts

    def metadata_row_count(self, group_name: str, branch: str = "main") -> int:
        """Row count of ``{group_name}/metadata/table``, or 0 if absent.

        Reads only the ``index`` array's shape (no full table load) -- cheap
        enough to log alongside every dedup check, so growth in
        ``batch_check``/``check_temporal_overlaps`` duration can be directly
        correlated against store size instead of assumed.
        """
        try:
            with self.readonly_session(branch) as session:
                zmeta = zarr.open_group(session.store, mode="r")[
                    f"{group_name}/metadata/table"
                ]
                return int(zmeta["index"].shape[0])
        except Exception:
            return 0

    def load_metadata_for_dedup(
        self, group_name: str, branch: str = "main"
    ) -> pl.DataFrame | None:
        """Load ``{group_name}``'s metadata table once, for reuse across dedup checks.

        ``batch_check_existing``/``check_temporal_overlaps`` each used to call
        ``load_metadata()`` independently -- two full-table reads per batch,
        growing with store size (dev/todo_later.md §34; confirmed 2026-07-15
        against a real backfill: ``batch_check`` duration tracked
        ``metadata_rows`` almost exactly, ~5x over 41,597 rows). Callers
        needing both checks should load once here and pass the result to
        both via their ``metadata_df`` parameter. Returns ``None`` (not an
        empty DataFrame) when the group/metadata doesn't exist yet, so
        callers can distinguish "nothing to check against" from "failed to
        load" without re-attempting the load.
        """
        try:
            with self.readonly_session(branch) as session:
                t0 = time.perf_counter()
                df = self.load_metadata(session.store, group_name)
                self._logger.info(
                    "metadata_table_loaded",
                    duration_seconds=round(time.perf_counter() - t0, 4),
                    group=group_name,
                    rows=df.height,
                    caller="load_metadata_for_dedup",
                )
                return df
        except Exception:
            return None

    def batch_check_existing(
        self,
        group_name: str,
        file_hashes: list[str],
        metadata_df: pl.DataFrame | None = None,
    ) -> set[str]:
        """Check which file hashes already exist in metadata.

        Parameters
        ----------
        metadata_df : pl.DataFrame, optional
            Pre-loaded metadata table (see ``load_metadata_for_dedup``) to
            skip this call's own full-table read. Loads internally (original
            behavior) when not provided.
        """
        try:
            if metadata_df is None:
                with self.readonly_session("main") as session:
                    t0 = time.perf_counter()
                    df = self.load_metadata(session.store, group_name)
                    self._logger.info(
                        "metadata_table_loaded",
                        duration_seconds=round(time.perf_counter() - t0, 4),
                        group=group_name,
                        rows=df.height,
                        caller="batch_check_existing",
                    )
            else:
                df = metadata_df

            existing = df.filter(pl.col("rinex_hash").is_in(file_hashes))
            return set(existing["rinex_hash"].to_list())

        except Exception:
            # Branch/group/metadata doesn't exist yet (fresh store)
            return set()

    def check_temporal_overlaps(
        self,
        group_name: str,
        file_intervals: list[tuple[str, np.datetime64, np.datetime64]],
        branch: str = "main",
        metadata_df: pl.DataFrame | None = None,
    ) -> set[str]:
        """Check which files temporally overlap existing metadata intervals.

        Parameters
        ----------
        group_name : str
            Icechunk group name.
        file_intervals : list[tuple[str, np.datetime64, np.datetime64]]
            List of ``(rinex_hash, start, end)`` tuples for incoming files.
        branch : str, default "main"
            Branch name in the Icechunk repository.
        metadata_df : pl.DataFrame, optional
            Pre-loaded metadata table (see ``load_metadata_for_dedup``) to
            skip this call's own full-table read. Loads internally (original
            behavior) when not provided.

        Returns
        -------
        set[str]
            Hashes of files whose ``[start, end]`` overlaps any existing
            metadata interval.  Files whose hash already exists in the store
            are NOT included (use ``batch_check_existing`` for those).
        """
        if not file_intervals:
            return set()

        if metadata_df is None:
            try:
                with self.readonly_session(branch) as session:
                    t0 = time.perf_counter()
                    df = self.load_metadata(session.store, group_name)
                    self._logger.info(
                        "metadata_table_loaded",
                        duration_seconds=round(time.perf_counter() - t0, 4),
                        group=group_name,
                        rows=df.height,
                        caller="check_temporal_overlaps",
                    )
            except Exception:
                return set()
        else:
            df = metadata_df

        if df.is_empty():
            return set()

        df = df.with_columns(
            [
                pl.col("start").cast(pl.Datetime("ns")),
                pl.col("end").cast(pl.Datetime("ns")),
            ]
        )

        # Build from proper numpy datetime64[ns] *arrays*, not boxed scalars:
        # polars' dict-of-scalars inference silently reinterprets the
        # underlying int64 as microseconds regardless of the numpy dtype's
        # declared unit (produces garbage timestamps), where array dtype
        # metadata is read correctly.
        incoming = pl.DataFrame(
            {
                "incoming_hash": [h for h, _, _ in file_intervals],
                "incoming_start": np.array(
                    [s for _, s, _ in file_intervals], dtype="datetime64[ns]"
                ),
                "incoming_end": np.array(
                    [e for _, _, e in file_intervals], dtype="datetime64[ns]"
                ),
            }
        )

        t_loop = time.perf_counter()
        # Vectorized interval-overlap join replaces one .filter() scan per
        # incoming interval (O(intervals x rows) Python loop) with a single
        # sort-merge join (dev/todo_later.md §34).
        hits = incoming.join_where(
            df.select(["rinex_hash", "start", "end"]),
            pl.col("incoming_start") <= pl.col("end"),
            pl.col("incoming_end") >= pl.col("start"),
        )

        overlapping: set[str] = set()
        if not hits.is_empty():
            summary = hits.group_by(
                ["incoming_hash", "incoming_start", "incoming_end"]
            ).agg(pl.len().alias("existing_files"))
            for row in summary.iter_rows(named=True):
                overlapping.add(row["incoming_hash"])
                self._logger.warning(
                    "temporal_overlap_detected",
                    group=group_name,
                    incoming_hash=row["incoming_hash"][:16],
                    incoming_range=f"{row['incoming_start']} → {row['incoming_end']}",
                    existing_files=row["existing_files"],
                )

        self._logger.info(
            "temporal_overlap_scan_complete",
            duration_seconds=round(time.perf_counter() - t_loop, 4),
            group=group_name,
            intervals=len(file_intervals),
            rows=df.height,
        )
        return overlapping

    def expire_old_snapshots(
        self,
        days: int | None = None,
        branch: str = "main",
        delete_expired_branches: bool = False,
        delete_expired_tags: bool = False,
    ) -> set[str]:
        """
        Expire snapshots older than the given retention period.

        Metadata-only "soft delete": rewrites ancestry so expired snapshots
        become unreachable from any surviving branch/tag. No objects
        (manifests, chunks, snapshot files) are deleted at this stage —
        call ``garbage_collect()`` separately to reclaim storage
        (dev/perf_degradation_findings_2026_07_15.md, Problem B). Keeping
        this expire-only (previously it also ran GC internally) is what
        lets a caller run GC exactly once via ``maintenance()`` instead of
        twice per call.

        Never invoke this automatically inside the pipeline's write path —
        it's an administrative operation, not safe to run casually
        alongside active writes. Use a generous ``days`` margin (weeks to
        months, not hours) so it can never touch anything from an
        in-flight write session.

        Parameters
        ----------
        days : int | None, optional
            Number of days to retain snapshots. Defaults to 90 (weeks-to-
            months cadence; see dev/perf_degradation_findings_2026_07_15.md
            for the operational guidance behind this default).
        branch : str, default "main"
            Branch to apply expiration on.
        delete_expired_branches : bool, default False
            Whether to delete branches pointing to expired snapshots.
            Matches Icechunk's own safe default — flip only deliberately.
        delete_expired_tags : bool, default False
            Whether to delete tags pointing to expired snapshots.
            **Do not set True** if using keeper tags (``create_keeper_tag``)
            — it would delete them along with any other expired-tip tag.

        Returns
        -------
        set[str]
            Expired snapshot IDs.
        """
        if days is None:
            days = 90
        cutoff = datetime.now(UTC) - timedelta(days=days)

        self._logger.info(
            f"Running expiration on store '{self.store_type}' "
            f"(branch '{branch}') with cutoff {cutoff.isoformat()}"
        )

        # Expire snapshots older than cutoff
        expired_ids = self.repo.expire_snapshots(
            older_than=cutoff,
            delete_expired_branches=delete_expired_branches,
            delete_expired_tags=delete_expired_tags,
        )

        if expired_ids:
            self._logger.info(
                f"Expired {len(expired_ids)} snapshots: {sorted(expired_ids)}"
            )
        else:
            self._logger.info("No snapshots to expire.")

        return expired_ids

    def garbage_collect(self, days: int = 90, *, dry_run: bool = False) -> dict:
        """
        Physically delete objects no longer reachable from any branch/tag.

        Only removes what a prior ``expire_old_snapshots()`` (or manual ref
        deletion) already made unreachable — this does not itself expire
        anything. Always run with ``dry_run=True`` first on a store that
        hasn't been GC'd before, especially one with a large accumulated
        backlog: there's no documented cost model for GC time/memory at
        scale, so a first-ever run's duration is unknown until measured
        (dev/perf_degradation_findings_2026_07_15.md, open question 4).

        **Not safe to run casually alongside active writes** — the cutoff
        must predate the start of any concurrently-running write session,
        and only one expire/GC operation should run at a time. Icechunk
        does have self-protection against races with *new* commits arriving
        mid-run (it restarts, bounded retries, rather than deleting
        something a concurrent writer needs), but that's not a substitute
        for a generous cutoff margin.

        Parameters
        ----------
        days : int, default 90
            Objects older than this (by the same write-time semantics as
            ``expire_old_snapshots``) are eligible for deletion.
        dry_run : bool, default False
            Report what would be deleted without deleting anything.

        Returns
        -------
        dict
            Summary of (would-be-)deleted objects.
        """
        cutoff = datetime.now(UTC) - timedelta(days=days)
        summary = self.repo.garbage_collect(
            delete_object_older_than=cutoff, dry_run=dry_run
        )
        self._logger.info(
            "garbage_collect_complete",
            dry_run=dry_run,
            cutoff=cutoff.isoformat(),
            bytes_deleted=summary.bytes_deleted,
            chunks_deleted=summary.chunks_deleted,
            manifests_deleted=summary.manifests_deleted,
            snapshots_deleted=summary.snapshots_deleted,
            attributes_deleted=summary.attributes_deleted,
            transaction_logs_deleted=summary.transaction_logs_deleted,
        )
        return {
            "dry_run": dry_run,
            "cutoff": cutoff.isoformat(),
            "bytes_deleted": summary.bytes_deleted,
            "chunks_deleted": summary.chunks_deleted,
            "manifests_deleted": summary.manifests_deleted,
            "snapshots_deleted": summary.snapshots_deleted,
            "attributes_deleted": summary.attributes_deleted,
            "transaction_logs_deleted": summary.transaction_logs_deleted,
        }

    def get_history(self, branch: str = "main", limit: int | None = None) -> list[dict]:
        """
        Return commit ancestry (history) for a branch.

        Parameters
        ----------
        branch : str, default "main"
            Branch name.
        limit : int | None, optional
            Maximum number of commits to return.

        Returns
        -------
        list[dict]
            Commit info dictionaries (id, message, written_at, parent_ids).
        """
        self._logger.info(f"Fetching ancestry for branch '{branch}'")

        history = []
        for i, ancestor in enumerate(self.repo.ancestry(branch=branch)):
            history.append(
                {
                    "snapshot_id": ancestor.id,
                    "commit_msg": ancestor.message,
                    "written_at": ancestor.written_at,
                    "parent_ids": ancestor.parent_id,
                }
            )
            if limit is not None and i + 1 >= limit:
                break

        return history

    def print_history(self, branch: str = "main", limit: int | None = 100) -> None:
        """
        Pretty-print the ancestry for quick inspection.
        """
        for entry in self.get_history(branch=branch, limit=limit):
            ts = entry["written_at"].strftime("%Y-%m-%d %H:%M:%S")
            print(f"{ts} {entry['snapshot_id'][:8]} {entry['commit_msg']}")

    def get_ops_log(self, limit: int | None = None) -> list[dict]:
        """
        Return the repository operations log (newest first).

        The ops log is an immutable audit trail of every structural mutation:
        commits, branch and tag operations, GC runs, config changes, etc.
        Unlike :meth:`get_history`, this is repo-wide (not per-branch) and
        covers all event types, not only commits.

        Parameters
        ----------
        limit : int | None, optional
            Maximum number of entries to return. ``None`` returns all.

        Returns
        -------
        list[dict]
            Each entry contains ``kind`` (str), ``updated_at`` (datetime),
            and ``backup_path`` (str).
        """
        entries = []
        for i, update in enumerate(self._repo.ops_log()):
            entries.append(
                {
                    "kind": str(update.kind),
                    "updated_at": update.updated_at,
                    "backup_path": update.backup_path,
                }
            )
            if limit is not None and i + 1 >= limit:
                break
        return entries

    def print_ops_log(self, limit: int | None = 50) -> None:
        """
        Pretty-print the repository operations log for quick inspection.

        Parameters
        ----------
        limit : int | None, optional
            Maximum number of entries to display (default: 50).
        """
        for entry in self.get_ops_log(limit=limit):
            ts = entry["updated_at"].strftime("%Y-%m-%d %H:%M:%S")
            print(f"{ts}  {entry['kind']}")

    def __repr__(self) -> str:
        """Return the developer-facing representation.

        Returns
        -------
        str
            Representation string.
        """
        display_names = {"rinex_store": "GNSS Store", "vod_store": "VOD Store"}
        display = display_names.get(self.store_type, self.store_type)
        return f"MyIcechunkStore(store_path={self.store_path}, store_type={display})"

    def __str__(self) -> str:
        """Return a human-readable summary.

        Returns
        -------
        str
            Summary string.
        """

        # Capture tree output
        old_stdout = sys.stdout
        sys.stdout = buffer = io.StringIO()

        try:
            self.print_tree()
            tree_output = buffer.getvalue()
        finally:
            sys.stdout = old_stdout

        branches = self.get_branch_names()
        group_dict = self.get_group_names()
        total_groups = sum(len(groups) for groups in group_dict.values())

        return (
            f"MyIcechunkStore: {self.store_path}\n"
            f"Branches: {len(branches)} | Total Groups: {total_groups}\n\n"
            f"{tree_output}"
        )

    @staticmethod
    def _copy_zarr_subtree(source_group: Any, target_group: Any) -> int:
        """Recursively copy all arrays, subgroups, and attrs (byte-for-byte).

        Used to restore ``group_name``'s nested ``metadata/`` subtree after
        a destructive ``mode="w"`` rewrite of the group's data arrays wipes
        it. Copies raw Zarr arrays directly (no xarray/Polars round-trip),
        so there is no dtype/schema-reconstruction risk — the arrays here
        (file registry rows, SBF metadata, etc.) end up byte-identical to
        the source. Handles arbitrary nesting depth (e.g. ``metadata/table``
        and ``metadata/sbf_obs`` are both subgroups of ``metadata``, not
        direct arrays of it).

        Parameters
        ----------
        source_group : zarr.Group
            Group to copy from (e.g. the original ``group_name`` node).
        target_group : zarr.Group
            Group to copy into (must already exist).

        Returns
        -------
        int
            Total number of subgroups copied (recursively).
        """
        target_group.attrs.update(source_group.attrs)

        count = 0
        for array_name in source_group.array_keys():
            source_array = source_group[array_name]
            target_array = target_group.create_array(
                array_name,
                shape=source_array.shape,
                dtype=source_array.dtype,
                chunks=source_array.chunks,
                overwrite=True,
            )
            target_array[:] = source_array[:]
            target_array.attrs.update(source_array.attrs)

        for subgroup_name in source_group.group_keys():
            source_subgroup = source_group[subgroup_name]
            target_subgroup = target_group.create_group(subgroup_name, overwrite=True)
            count += 1
            count += MyIcechunkStore._copy_zarr_subtree(
                source_subgroup, target_subgroup
            )

        return count

    def rechunk_group(
        self,
        group_name: str,
        chunks: dict[str, int],
        source_branch: str = "main",
        temp_branch: str | None = None,
        promote_to_main: bool = True,
        delete_temp_branch: bool = True,
    ) -> str:
        """
        Rechunk a group with optimal chunk sizes.

        Zarr arrays have a fixed chunk shape once created — writing with
        ``mode="r+"`` onto an existing array cannot change chunk boundaries,
        it can only update values within the existing grid (verified
        2026-07-08: a previous version of this method used ``mode="r+"``,
        which silently failed to change on-disk chunking whenever the
        request didn't align with the current chunks). Actually changing
        chunk size requires a destructive ``mode="w"`` rewrite of the
        group, which also wipes the group's nested subgroups (``metadata/
        table``, ``metadata/sbf_obs``) — so this method copies that
        subtree back afterward via a raw recursive Zarr copy (see
        ``_copy_zarr_subtree``), all on a temporary branch, before ``main``
        is ever touched. This mirrors a fix already applied once before in
        gnssvodpy (``rechunk_group_verbose``), generalized here to handle
        canvod-store's two-level-deep ``metadata/{table,sbf_obs}`` nesting
        rather than gnssvodpy's one-level copy.

        Both the data read and the subtree copy are pinned to the exact
        snapshot captured at the start of this call (not just "whatever
        ``source_branch`` currently points to"), so this is safe to run
        even if ``source_branch`` keeps advancing concurrently — anything
        committed after this call started is simply not part of the
        rechunk and stays untouched on ``source_branch``.

        Parameters
        ----------
        group_name : str
            Name of the group to rechunk
        chunks : dict[str, int]
            Chunking specification, e.g. {'epoch': 17280, 'sid': -1}
        source_branch : str
            Branch to read original data from (default: "main")
        temp_branch : str | None
            Temporary branch name for rechunked data. If None, uses
            "{group_name}_rechunked".
        promote_to_main : bool
            If True, reset main branch to rechunked snapshot after writing
        delete_temp_branch : bool
            If True, delete temporary branch after promotion (only if
            promote_to_main=True).

        Returns
        -------
        str
            Snapshot ID of the rechunked data
        """
        if temp_branch is None:
            temp_branch = f"{group_name}_rechunked_temp"

        self._logger.info(
            f"Starting rechunk of group '{group_name}' with chunks={chunks}"
        )

        # Snapshot everything up front so the whole operation is pinned to
        # one consistent point in time, regardless of concurrent writers.
        current_snapshot = self.repo.lookup_branch(source_branch)

        # Create temp branch from that snapshot (preserves all existing groups)
        try:
            self.repo.create_branch(temp_branch, current_snapshot)
            self._logger.info(
                f"Created temporary branch '{temp_branch}' from current {source_branch}"
            )
        except Exception as e:
            self._logger.warning(f"Branch '{temp_branch}' may already exist: {e}")

        # Read original data, pinned to current_snapshot
        session = self.repo.readonly_session(snapshot_id=current_snapshot)
        ds_original = xr.open_zarr(session.store, group=group_name, consolidated=False)
        self._logger.info(f"Original chunks: {ds_original.chunks}")

        # Rechunk
        ds_rechunked = ds_original.chunk(chunks)
        self._logger.info(f"New chunks: {ds_rechunked.chunks}")

        # Clear encoding in-place on all variables and coords.
        # Assignment (= {}) creates a new dict on the returned copy and
        # is a no-op; .clear() mutates the shared dict the Dataset holds.
        for key in list(ds_rechunked.data_vars) + list(ds_rechunked.coords):
            ds_rechunked[key].encoding.clear()

        source_zroot = zarr.open_group(session.store, mode="r")
        source_group = source_zroot[group_name]
        subgroup_names = list(source_group.group_keys())

        # Force-write with mode="w": the only way to actually change chunk
        # boundaries on an existing array. This wipes group_name's entire
        # subtree, including all subgroups -- restored below, same
        # session, same commit, so the temp branch never has a subgroup-less
        # state that could be read by anything else.
        with self.writable_session(temp_branch) as session:
            to_icechunk(ds_rechunked, session, group=group_name, mode="w")

            subgroup_count = 0
            if subgroup_names:
                ro_session = self.repo.readonly_session(snapshot_id=current_snapshot)
                ro_zroot = zarr.open_group(ro_session.store, mode="r")
                source_group = ro_zroot[group_name]

                target_zroot = zarr.open_group(session.store, mode="a")
                target_group = target_zroot[group_name]

                for subgroup_name in subgroup_names:
                    source_subgroup = source_group[subgroup_name]
                    target_subgroup = target_group.create_group(
                        subgroup_name, overwrite=True
                    )
                    subgroup_count += 1
                    subgroup_count += self._copy_zarr_subtree(
                        source_subgroup, target_subgroup
                    )

            snapshot_id = session.commit(
                _with_run_id(
                    f"Rechunked {group_name} with chunks={chunks} "
                    f"({subgroup_count} subgroups restored)"
                )
            )

        self._logger.info(
            f"Rechunked data written to branch '{temp_branch}', snapshot={snapshot_id}"
        )

        # Promote to main if requested
        if promote_to_main:
            rechunked_snapshot = self.repo.lookup_branch(temp_branch)
            self.repo.reset_branch(source_branch, rechunked_snapshot)
            self._logger.info(
                f"Reset branch '{source_branch}' to rechunked snapshot "
                f"{rechunked_snapshot}"
            )

            # Delete temp branch if requested
            if delete_temp_branch:
                self.repo.delete_branch(temp_branch)
                self._logger.info(f"Deleted temporary branch '{temp_branch}'")

        return snapshot_id

    def create_release_tag(self, tag_name: str, snapshot_id: str | None = None) -> None:
        """
        Create an immutable tag for an important version.

        Parameters
        ----------
        tag_name : str
            Name for the tag (e.g., "v2024_complete", "before_reprocess")
        snapshot_id : str | None
            Snapshot to tag. If None, uses current tip of main branch.
        """
        if snapshot_id is None:
            # Tag current main branch tip
            snapshot_id = self.repo.lookup_branch("main")

        self.repo.create_tag(tag_name, snapshot_id)
        self._logger.info(f"Created tag '{tag_name}' at snapshot {snapshot_id[:8]}")

    def list_tags(self) -> list[str]:
        """List all tags in the repository."""
        return list(self.repo.list_tags())

    def delete_tag(self, tag_name: str) -> None:
        """Delete a tag (use with caution - tags are meant to be permanent)."""
        self.repo.delete_tag(tag_name)
        self._logger.warning(f"Deleted tag '{tag_name}'")

    def create_keeper_tag(self, receiver: str, yyyydoy: str, snapshot_id: str) -> bool:
        """
        Tag a per-(receiver, date) commit as a permanent retention keeper.

        Part of the tag-based retention scheme in
        dev/perf_degradation_findings_2026_07_15.md (Problem B): tagging
        ``keep/{receiver}/{yyyydoy}`` after each commit means a later
        ``expire_old_snapshots(delete_expired_tags=False)`` run can safely
        prune everything else while these specific snapshots stay
        time-travelable forever. Additive and inert on its own — creating a
        tag doesn't expire or delete anything.

        Never raises: a tag name collision (already exists, or was
        previously deleted — Icechunk tag names are never reusable) is
        logged and skipped rather than failing the pipeline write that
        called this.

        Parameters
        ----------
        receiver : str
            Receiver/group name (e.g. ``"canopy_01"``).
        yyyydoy : str
            Date key (e.g. ``"2025001"``).
        snapshot_id : str
            Snapshot to tag — typically the just-committed snapshot.

        Returns
        -------
        bool
            True if the tag was created, False if skipped.
        """
        tag_name = f"keep/{receiver}/{yyyydoy}"
        try:
            self.repo.create_tag(tag_name, snapshot_id)
        except icechunk.IcechunkError as exc:
            self._logger.warning("keeper_tag_skipped", tag=tag_name, error=str(exc))
            return False
        self._logger.info("keeper_tag_created", tag=tag_name, snapshot=snapshot_id[:8])
        return True

    def plot_commit_graph(
        self,
        branch: str | None = None,
        *,
        plain: bool = False,
    ) -> AncestryGraph:
        """
        Visualize commit history as a graph.

        Delegates to icechunk's native ``repo.ancestry_graph()``. Renders as
        an SVG diagram in Jupyter/marimo notebooks, or as colored text in a
        terminal (``print(store.plot_commit_graph())``).

        Parameters
        ----------
        branch : str, optional
            Restrict the graph to this branch's linear history.
            When omitted, all branches are shown as a tree.
        plain : bool, optional
            Render without ANSI colours or SVG fill colours (useful for CI
            logs or piping to a file).

        Returns
        -------
        AncestryGraph
            Displayable object with ``_repr_svg_()`` for notebooks.
        """
        return self._repo.ancestry_graph(branch=branch, plain=plain)

    def cleanup_stale_branches(
        self, keep_patterns: list[str] | None = None
    ) -> list[str]:
        """
        Delete stale temporary branches (e.g., from failed rechunking).

        Parameters
        ----------
        keep_patterns : list[str] | None
            Patterns to preserve. Default: ["main", "dev"]

        Returns
        -------
        list[str]
            Names of deleted branches
        """
        if keep_patterns is None:
            keep_patterns = ["main", "dev"]

        deleted = []

        for branch in self.repo.list_branches():
            # Keep if matches any pattern
            should_keep = any(pattern in branch for pattern in keep_patterns)

            if not should_keep:
                # Check if it's a temp branch from rechunking
                if "_rechunked_temp" in branch or "_temp" in branch:
                    try:
                        self.repo.delete_branch(branch)
                        deleted.append(branch)
                        self._logger.info(f"Deleted stale branch: {branch}")
                    except Exception as e:
                        self._logger.warning(f"Failed to delete branch {branch}: {e}")

        return deleted

    def delete_branch(self, branch_name: str) -> None:
        """Delete a branch."""
        if branch_name == "main":
            raise ValueError("Cannot delete 'main' branch")

        self.repo.delete_branch(branch_name)
        self._logger.info(f"Deleted branch '{branch_name}'")

    def get_snapshot_info(self, snapshot_id: str) -> dict:
        """
        Get detailed information about a specific snapshot.

        Parameters
        ----------
        snapshot_id : str
            Snapshot ID to inspect

        Returns
        -------
        dict
            Snapshot metadata and statistics
        """
        try:
            snap = self.repo.lookup_snapshot(snapshot_id)
        except Exception as e:
            raise ValueError(f"Snapshot {snapshot_id} not found") from e

        info = {
            "snapshot_id": snap.id,
            "message": snap.message,
            "written_at": snap.written_at,
            "parent_id": snap.parent_id,
        }

        try:
            session = self.repo.readonly_session(snapshot_id=snap.id)
            root = zarr.open(session.store, mode="r")
            info["groups"] = list(root.group_keys())
            info["arrays"] = list(root.array_keys())
        except Exception as e:
            self._logger.warning(f"Could not inspect snapshot contents: {e}")

        return info

    def compare_snapshots(self, snapshot_id_1: str, snapshot_id_2: str) -> dict:
        """
        Compare two snapshots to see what changed.

        Parameters
        ----------
        snapshot_id_1 : str
            First snapshot (older)
        snapshot_id_2 : str
            Second snapshot (newer)

        Returns
        -------
        dict
            Comparison results showing added/removed/modified groups
        """
        info_1 = self.get_snapshot_info(snapshot_id_1)
        info_2 = self.get_snapshot_info(snapshot_id_2)

        groups_1 = set(info_1.get("groups", []))
        groups_2 = set(info_2.get("groups", []))

        return {
            "snapshot_1": snapshot_id_1[:8],
            "snapshot_2": snapshot_id_2[:8],
            "added_groups": list(groups_2 - groups_1),
            "removed_groups": list(groups_1 - groups_2),
            "common_groups": list(groups_1 & groups_2),
            "time_diff": (info_2["written_at"] - info_1["written_at"]).total_seconds(),
        }

    def maintenance(
        self,
        expire_days: int = 90,
        cleanup_branches: bool = True,
        run_gc: bool = True,
        *,
        dry_run_gc: bool = False,
        delete_expired_branches: bool = False,
        delete_expired_tags: bool = False,
    ) -> dict:
        """
        Run full maintenance on the store: expire, then (optionally) GC.

        Must be invoked manually or from a separately scheduled maintenance
        job — never from the pipeline's own run path, and never on an
        automatic schedule until ``garbage_collect(dry_run=True)`` has been
        checked against the real store and, if using keeper tags,
        ``create_tag()`` cost at scale has been confirmed
        (dev/perf_degradation_findings_2026_07_15.md, open questions 4, 8).
        Not safe during active writes — see ``expire_old_snapshots``/
        ``garbage_collect`` docstrings for the concurrency caveats.

        Parameters
        ----------
        expire_days : int
            Days of snapshot history to keep. Default 90 (weeks-to-months
            cadence, not the previous 7-day default — 7 days is far too
            aggressive for a store under sustained daily writes).
        cleanup_branches : bool
            Remove stale temporary branches.
        run_gc : bool
            Run garbage collection after expiration.
        dry_run_gc : bool, default False
            Pass through to ``garbage_collect`` — report without deleting.
        delete_expired_branches : bool, default False
            Pass through to ``expire_old_snapshots``.
        delete_expired_tags : bool, default False
            Pass through to ``expire_old_snapshots``. **Do not set True**
            if using keeper tags — see ``create_keeper_tag``.

        Returns
        -------
        dict
            Summary of maintenance actions.
        """
        self._logger.info(f"Starting maintenance on {self.store_type}")

        results = {"expired_snapshots": 0, "deleted_branches": [], "gc_summary": None}

        # Expire old snapshots (metadata-only; no objects deleted here)
        expired_ids = self.expire_old_snapshots(
            days=expire_days,
            delete_expired_branches=delete_expired_branches,
            delete_expired_tags=delete_expired_tags,
        )
        results["expired_snapshots"] = len(expired_ids)

        # Cleanup stale branches
        if cleanup_branches:
            deleted_branches = self.cleanup_stale_branches()
            results["deleted_branches"] = deleted_branches

        # Garbage collection — runs exactly once here (previously ran once
        # inside expire_old_snapshots() too, a double-GC-per-call bug; see
        # dev/perf_degradation_findings_2026_07_15.md, Problem B).
        if run_gc:
            results["gc_summary"] = self.garbage_collect(
                days=expire_days, dry_run=dry_run_gc
            )

        self._logger.info(f"Maintenance complete: {results}")
        return results


# Factory functions for common use cases
def create_rinex_store(store_path: Path) -> MyIcechunkStore:
    """
    Create a RINEX Icechunk store with appropriate configuration.

    Parameters
    ----------
    store_path : Path
        Path to the store directory.

    Returns
    -------
    MyIcechunkStore
        Configured store for RINEX data.
    """
    return MyIcechunkStore(store_path=store_path, store_type="rinex_store")


def create_vod_store(store_path: Path) -> MyIcechunkStore:
    """
    Create a VOD Icechunk store with appropriate configuration.

    Parameters
    ----------
    store_path : Path
        Path to the store directory.

    Returns
    -------
    MyIcechunkStore
        Configured store for VOD analysis data.
    """
    return MyIcechunkStore(store_path=store_path, store_type="vod_store")
