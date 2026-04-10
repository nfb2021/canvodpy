import contextlib
import io
import json
import sys
import warnings
from collections.abc import Generator, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Any

import icechunk
import numpy as np
import polars as pl
import xarray as xr
import zarr
from canvod.utils.config import load_config
from canvod.utils.tools import get_version_from_pyproject
from canvodpy.logging import get_logger
from icechunk.xarray import to_icechunk
from zarr.dtype import VariableLengthUTF8

from canvod.store.viewer import add_rich_display_to_store

# Suppress the "local filesystem not safe for concurrent commits" Rust/tracing
# warning — we are aware and it is noise for single-writer local workflows.
icechunk.set_logs_filter("icechunk=error")

if TYPE_CHECKING:
    from plotly.graph_objects import Figure


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
        try:
            from canvod.utils.config import load_config

            cfg = load_config()
            ic_cfg = cfg.processing.icechunk
            _rinex_store_strategy = cfg.processing.storage.rinex_store_strategy
            _rinex_store_expire_days = cfg.processing.storage.rinex_store_expire_days
            _vod_store_strategy = cfg.processing.storage.vod_store_strategy
        except Exception:
            from canvod.utils.config.models import IcechunkConfig

            ic_cfg = IcechunkConfig()
            _rinex_store_strategy = "append"
            _rinex_store_expire_days = 2
            _vod_store_strategy = "overwrite"

        self.store_path = Path(store_path)
        self.store_type = store_type
        # Site name is parent directory name
        self.site_name = self.store_path.parent.name

        # Compression
        self.compression_level = compression_level or ic_cfg.compression_level
        compression_alg = compression_algorithm or ic_cfg.compression_algorithm
        self.compression_algorithm = getattr(
            icechunk.CompressionAlgorithm, compression_alg.capitalize()
        )

        # Chunk strategy
        chunk_strategies = {
            k: {"epoch": v.epoch, "sid": v.sid}
            for k, v in ic_cfg.chunk_strategies.items()
        }
        self.chunk_strategy = chunk_strategies.get(store_type, {})

        # Storage config cached for metadata rows
        self._rinex_store_strategy = _rinex_store_strategy
        self._rinex_store_expire_days = _rinex_store_expire_days
        self._vod_store_strategy = _vod_store_strategy

        # Configure repository
        self.config = icechunk.RepositoryConfig.default()
        self.config.compression = icechunk.CompressionConfig(
            level=self.compression_level, algorithm=self.compression_algorithm
        )
        self.config.inline_chunk_threshold_bytes = ic_cfg.inline_threshold
        self.config.get_partial_values_concurrency = ic_cfg.get_concurrency

        if ic_cfg.manifest_preload_enabled:
            self.config.manifest = icechunk.ManifestConfig(
                preload=icechunk.ManifestPreloadConfig(
                    max_total_refs=ic_cfg.manifest_preload_max_refs,
                    preload_if=icechunk.ManifestPreloadCondition.name_matches(
                        ic_cfg.manifest_preload_pattern
                    ),
                )
            )
            self._logger.info(
                f"Manifest preload enabled: {ic_cfg.manifest_preload_pattern}"
            )

        self._repo = None
        self._logger = get_logger(__name__)

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
        # Cast StringDType / fixed-width unicode to object for Zarr V3
        for name in list(ds.coords) + list(ds.data_vars):
            if ds[name].dtype.kind in ("U", "T"):
                ds[name] = ds[name].astype(object)
        # Eagerly compute Dask-backed object arrays to avoid SerializationWarning
        # (rechunking after write can leave string coords as dask object arrays)
        try:
            import dask.array as da

            for name in list(ds.coords) + list(ds.data_vars):
                if ds[name].dtype == object and isinstance(ds[name].data, da.Array):
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
        """Context manager for readonly sessions.

        Parameters
        ----------
        branch : str, default "main"
            Branch name.

        Returns
        -------
        Generator[icechunk.ReadonlySession, None, None]
            Readonly session context manager.
        """
        session = self.repo.readonly_session(branch)
        try:
            self._logger.debug(f"Opened readonly session for branch '{branch}'")
            yield session
        finally:
            self._logger.debug(f"Closed readonly session for branch '{branch}'")

    @contextlib.contextmanager
    def writable_session(
        self,
        branch: str = "main",
    ) -> Generator[icechunk.WritableSession]:
        """Context manager for writable sessions.

        Parameters
        ----------
        branch : str, default "main"
            Branch name.

        Returns
        -------
        Generator[icechunk.WritableSession, None, None]
            Writable session context manager.
        """
        session = self.repo.writable_session(branch)
        try:
            self._logger.debug(f"Opened writable session for branch '{branch}'")
            yield session
        finally:
            self._logger.debug(f"Closed writable session for branch '{branch}'")

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
        with self.writable_session(branch) as session:
            try:
                root = zarr.open_group(session.store, mode="r+")
            except zarr.errors.GroupNotFoundError:
                root = zarr.open_group(session.store, mode="w")
            root.attrs.update(attrs)
            return session.commit(f"Set root attrs: {list(attrs.keys())}")

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
        try:
            if self._repo is None:
                self._ensure_store_exists()
            return list(self._repo.list_branches())  # type: ignore[union-attr]
        except Exception as e:
            self._logger.warning(f"Failed to list branches in {self!r}: {e}")
            warnings.warn(f"Failed to list branches in {self!r}: {e}", stacklevel=2)
            return []

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
        try:
            if not branch:
                branches = self.get_branch_names()
            else:
                branches = [branch]

            if self._repo is None:
                self._ensure_store_exists()

            group_dict = {}
            for br in branches:
                with self.readonly_session(br) as session:
                    root = zarr.open(session.store, mode="r")
                    group_dict[br] = list(root.group_keys())

            return group_dict

        except Exception as e:
            self._logger.warning(f"Failed to list groups in {self!r}: {e}")
            return {}

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
        """
        Display hierarchical tree of all branches, groups, and subgroups.
        """
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
                chunks = self.chunk_strategy or {"epoch": 34560, "sid": -1}

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
            Example: {'epoch': 34560, 'sid': -1}
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

        # Write to Icechunk with OpenTelemetry tracing
        try:
            from canvodpy.utils.telemetry import trace_icechunk_write

            with trace_icechunk_write(
                group_name=group_name,
                dataset_size_mb=dataset_size_mb,
                num_variables=num_variables,
            ):
                to_icechunk(dataset, session, group=group_name, mode=mode)
        except ImportError:
            # Fallback if telemetry not available
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

        with self.writable_session(branch) as session:
            dataset = self._normalize_encodings(dataset)

            rinex_hash = dataset.attrs.get("File Hash")
            if rinex_hash is None:
                raise ValueError("Dataset missing 'File Hash' attribute")
            start = dataset.epoch.min().values
            end = dataset.epoch.max().values

            to_icechunk(dataset, session, group=group_name, mode="w")

            if commit_message is None:
                version = get_version_from_pyproject()
                commit_message = f"[v{version}] Initial commit to group '{group_name}'"

            snapshot_id = session.commit(commit_message)

            self.append_metadata(
                group_name=group_name,
                rinex_hash=rinex_hash,
                start=start,
                end=end,
                snapshot_id=snapshot_id,
                action="write",  # Correct action for initial data
                commit_msg=commit_message,
                dataset_attrs=dataset.attrs,
            )

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

            snapshot_id = session.commit(commit_message)

            self.append_metadata(
                group_name=group_name,
                rinex_hash=rinex_hash,
                start=start,
                end=end,
                snapshot_id=snapshot_id,
                action="overwrite",
                commit_msg=commit_message,
                dataset_attrs=dataset.attrs,
            )

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
        path = f"{group_name}/metadata/{name}"
        try:
            with self.readonly_session(branch) as session:
                zarr.open_group(session.store, mode="r", path=path)
                return True
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
            return session.commit(f"[v{version}] metadata/{name} for {group_name}")

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
                f"[v{version}] metadata/{name} for {group_name} ({total_epochs} epochs)"
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
            ``{"epoch": 34560, "sid": -1}``.

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
                chunks=chunks or self.chunk_strategy or {"epoch": 34560, "sid": -1},
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
        depth = load_config().processing.logging.log_path_depth
        return str(Path(*file_path.parts[-depth:]))

    def get_store_stats(self) -> dict[str, Any]:
        """
        Get statistics about the store.

        Returns
        -------
        dict[str, Any]
            Store statistics.
        """
        groups = self.get_group_names()
        stats = {
            "store_path": str(self.store_path),
            "store_type": self.store_type,
            "compression_level": self.compression_level,
            "compression_algorithm": self.compression_algorithm.name,
            "total_groups": len(groups),
            "groups": groups,
        }

        # Add group-specific stats
        for group_name in groups:
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

        with self.writable_session(branch) as session:
            to_icechunk(dataset, session, group=group_name, append_dim=append_dim)

            if commit_message is None and action == "write":
                version = get_version_from_pyproject()
                commit_message = f"[v{version}] Wrote to group '{group_name}'"
            elif commit_message is None and action != "append":
                version = get_version_from_pyproject()
                commit_message = f"[v{version}] Appended to group '{group_name}'"

            snapshot_id = session.commit(commit_message)

            self.append_metadata(
                group_name=group_name,
                rinex_hash=rinex_hash,
                start=start,
                end=end,
                snapshot_id=snapshot_id,
                action=action,
                commit_msg=commit_message,
                dataset_attrs=dataset.attrs,
            )

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
                session.commit(commit_message)
            self._logger.info(
                f"Appended {len(dataset.epoch)} epochs to group '{group_name}'"
            )
        else:
            with self.writable_session(branch) as session:
                to_icechunk(dataset, session, group=group_name, mode="w")
                if commit_message is None:
                    commit_message = f"Created group '{group_name}'"
                session.commit(commit_message)
            self._logger.info(
                f"Created group '{group_name}' with {len(dataset.epoch)} epochs"
            )
        return True

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
        """
        Append a metadata row into the group_name/metadata/table.

        Schema:
            index           int64 (continuous row id)
            rinex_hash      str   (UTF-8, VariableLengthUTF8)
            start           datetime64[ns]
            end             datetime64[ns]
            snapshot_id     str   (UTF-8)
            action          str   (UTF-8, e.g. "insert"|"append"|"overwrite"|"skip")
            commit_msg      str   (UTF-8)
            written_at      str   (UTF-8, ISO8601 with timezone)
            write_strategy  str   (UTF-8, RINEX_STORE_STRATEGY or VOD_STORE_STRATEGY)
            attrs           str   (UTF-8, JSON dump of dataset attrs)
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

        with self.writable_session(branch) as session:
            zroot = zarr.open_group(session.store, mode="a")
            meta_group_path = f"{group_name}/metadata/table"

            if (
                "metadata" not in zroot[group_name]
                or "table" not in zroot[group_name]["metadata"]
            ):
                # --- First time: create arrays with correct dtypes ---
                zmeta = zroot.require_group(meta_group_path)

                # index counter
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
                        name=col,
                        shape=(0,),
                        dtype=dtype,
                        chunks=(1024,),
                        overwrite=True,
                    )
                    zmeta[col].append(arr)

            else:
                # --- Append to existing ---
                zmeta = zroot[meta_group_path]

                # index increment
                current_len = zmeta["index"].shape[0]
                next_idx = current_len
                zmeta["index"].append([next_idx])

                for col in df_row.columns:
                    if col in ("start", "end"):
                        arr = np.array(df_row[col].to_numpy(), dtype="M8[ns]")
                    else:
                        arr = df_row[col].to_list()
                    zmeta[col].append(arr)

            session.commit(f"Appended metadata row for {group_name}, hash={rinex_hash}")

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
                sess.commit(f"Bulk metadata append for {group_name}")

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
        if df["start"].dtype in (pl.Int64, pl.Float64):
            df = df.with_columns(pl.col("start").cast(pl.Datetime("ns")))
        if df["end"].dtype in (pl.Int64, pl.Float64):
            df = df.with_columns(pl.col("end").cast(pl.Datetime("ns")))
        if df["written_at"].dtype == pl.Utf8:
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

    def batch_check_existing(self, group_name: str, file_hashes: list[str]) -> set[str]:
        """Check which file hashes already exist in metadata."""

        try:
            with self.readonly_session("main") as session:
                df = self.load_metadata(session.store, group_name)

                # Filter to matching hashes
                existing = df.filter(pl.col("rinex_hash").is_in(file_hashes))
                return set(existing["rinex_hash"].to_list())

        except KeyError, zarr.errors.GroupNotFoundError, Exception:
            # Branch/group/metadata doesn't exist yet (fresh store)
            return set()

    def check_temporal_overlaps(
        self,
        group_name: str,
        file_intervals: list[tuple[str, np.datetime64, np.datetime64]],
        branch: str = "main",
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

        Returns
        -------
        set[str]
            Hashes of files whose ``[start, end]`` overlaps any existing
            metadata interval.  Files whose hash already exists in the store
            are NOT included (use ``batch_check_existing`` for those).
        """
        if not file_intervals:
            return set()

        try:
            with self.readonly_session(branch) as session:
                df = self.load_metadata(session.store, group_name)
        except KeyError, zarr.errors.GroupNotFoundError, Exception:
            return set()

        if df.is_empty():
            return set()

        df = df.with_columns(
            [
                pl.col("start").cast(pl.Datetime("ns")),
                pl.col("end").cast(pl.Datetime("ns")),
            ]
        )

        overlapping: set[str] = set()
        for rinex_hash, start, end in file_intervals:
            start_ns = np.datetime64(start, "ns")
            end_ns = np.datetime64(end, "ns")

            hits = df.filter((pl.col("start") <= end_ns) & (pl.col("end") >= start_ns))
            if not hits.is_empty():
                self._logger.warning(
                    "temporal_overlap_detected",
                    group=group_name,
                    incoming_hash=rinex_hash[:16],
                    incoming_range=f"{start} → {end}",
                    existing_files=hits.height,
                )
                overlapping.add(rinex_hash)

        return overlapping

    def append_metadata_bulk_store(
        self,
        group_name: str,
        rows: list[dict[str, Any]],
        store: Any,
    ) -> None:
        """
        Append metadata rows into an open transaction store.

        Parameters
        ----------
        group_name : str
            Group name (e.g. "canopy", "reference").
        rows : list[dict[str, Any]]
            Metadata rows to append.
        store : Any
            Open Icechunk transaction store.
        """
        if not rows:
            return

        zroot = zarr.open_group(store, mode="a")
        zmeta = zroot.require_group(f"{group_name}/metadata/table")

        # Find next index
        start_index = 0
        if "index" in zmeta:
            start_index = (
                int(zmeta["index"][-1]) + 1 if zmeta["index"].shape[0] > 0 else 0
            )

        for i, row in enumerate(rows, start=start_index):
            row["index"] = i

        import polars as pl

        df = pl.DataFrame(rows)

        for col in df.columns:
            list_only_cols = {
                "attrs",
                "commit_msg",
                "action",
                "write_strategy",
                "rinex_hash",
                "snapshot_id",
            }
            if col in list_only_cols:
                values = df[col].to_list()
            else:
                values = df[col].to_numpy()

            if col == "index":
                dtype = "i8"
            elif col in ("start", "end"):
                dtype = "M8[ns]"
            else:
                dtype = VariableLengthUTF8()

            if col not in zmeta:
                zmeta.create_array(
                    name=col, shape=(0,), dtype=dtype, chunks=(1024,), overwrite=True
                )

            arr = zmeta[col]
            old_len = arr.shape[0]
            new_len = old_len + len(values)
            arr.resize(new_len)
            arr[old_len:new_len] = values

        self._logger.info(f"Appended {df.height} metadata rows to group '{group_name}'")

    def expire_old_snapshots(
        self,
        days: int | None = None,
        branch: str = "main",
        delete_expired_branches: bool = True,
        delete_expired_tags: bool = True,
    ) -> set[str]:
        """
        Expire and garbage-collect snapshots older than the given retention period.

        Parameters
        ----------
        days : int | None, optional
            Number of days to retain snapshots. Defaults to config value.
        branch : str, default "main"
            Branch to apply expiration on.
        delete_expired_branches : bool, default True
            Whether to delete branches pointing to expired snapshots.
        delete_expired_tags : bool, default True
            Whether to delete tags pointing to expired snapshots.

        Returns
        -------
        set[str]
            Expired snapshot IDs.
        """
        if days is None:
            days = self._rinex_store_expire_days
        cutoff = datetime.now(UTC) - timedelta(days=days)

        # cutoff = datetime(2025, 10, 3, 16, 44, 1, tzinfo=timezone.utc)
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

        # Garbage-collect expired objects to reclaim storage
        summary = self.repo.garbage_collect(delete_object_older_than=cutoff)
        self._logger.info(
            f"Garbage collection summary: "
            f"deleted_bytes={summary.bytes_deleted}, "
            f"deleted_chunks={summary.chunks_deleted}, "
            f"deleted_manifests={summary.manifests_deleted}, "
            f"deleted_snapshots={summary.snapshots_deleted}, "
            f"deleted_attributes={summary.attributes_deleted}, "
            f"deleted_transaction_logs={summary.transaction_logs_deleted}"
        )

        return expired_ids

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

        Parameters
        ----------
        group_name : str
            Name of the group to rechunk
        chunks : dict[str, int]
            Chunking specification, e.g. {'epoch': 34560, 'sid': -1}
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

        # Get CURRENT snapshot from source branch to preserve all other groups
        current_snapshot = next(self.repo.ancestry(branch=source_branch)).id

        # Create temp branch from current snapshot (preserves all existing groups)
        try:
            self.repo.create_branch(temp_branch, current_snapshot)
            self._logger.info(
                f"Created temporary branch '{temp_branch}' from current {source_branch}"
            )
        except Exception as e:
            self._logger.warning(f"Branch '{temp_branch}' may already exist: {e}")

        # Read original data
        ds_original = self.read_group(group_name, branch=source_branch)
        self._logger.info(f"Original chunks: {ds_original.chunks}")

        # Rechunk
        ds_rechunked = ds_original.chunk(chunks)
        self._logger.info(f"New chunks: {ds_rechunked.chunks}")

        # Clear encoding to avoid conflicts
        for var in ds_rechunked.data_vars:
            ds_rechunked[var].encoding = {}

        # Write rechunked data (overwrites only this group)
        with self.writable_session(temp_branch) as session:
            to_icechunk(ds_rechunked, session, group=group_name, mode="w")
            snapshot_id = session.commit(f"Rechunked {group_name} with chunks={chunks}")

        self._logger.info(
            f"Rechunked data written to branch '{temp_branch}', snapshot={snapshot_id}"
        )

        # Promote to main if requested
        if promote_to_main:
            rechunked_snapshot = next(self.repo.ancestry(branch=temp_branch)).id
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

    def rechunk_group_verbose(
        self,
        group_name: str,
        chunks: dict[str, int] | None = None,
        source_branch: str = "main",
        temp_branch: str | None = None,
        promote_to_main: bool = True,
        delete_temp_branch: bool = True,
    ) -> str:
        """
        Rechunk a group with optimal chunk sizes.

        Parameters
        ----------
        group_name : str
            Name of the group to rechunk
        chunks : dict[str, int] | None
            Chunking specification, e.g. {'epoch': 34560, 'sid': -1}. Defaults
            to `gnnsvodpy.globals.ICECHUNK_CHUNK_STRATEGIES`.
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

        if chunks is None:
            chunks = self.chunk_strategy or {"epoch": 34560, "sid": -1}

        print(f"\n{'=' * 60}")
        print(f"Starting rechunk of group '{group_name}'")
        print(f"Target chunks: {chunks}")
        print(f"{'=' * 60}\n")

        self._logger.info(
            f"Starting rechunk of group '{group_name}' with chunks={chunks}"
        )

        # Get CURRENT snapshot from source branch to preserve all other groups
        print(f"[1/7] Getting current snapshot from branch '{source_branch}'...")
        current_snapshot = next(self.repo.ancestry(branch=source_branch)).id
        print(f"      ✓ Current snapshot: {current_snapshot[:12]}")

        # Create temp branch from current snapshot (preserves all existing groups)
        print(f"\n[2/7] Creating temporary branch '{temp_branch}'...")
        try:
            self.repo.create_branch(temp_branch, current_snapshot)
            print(f"      ✓ Branch '{temp_branch}' created")
            self._logger.info(
                f"Created temporary branch '{temp_branch}' from current {source_branch}"
            )
        except Exception as e:
            print(
                f"      ⚠ Branch '{temp_branch}' already exists, using existing branch"
            )
            self._logger.warning(f"Branch '{temp_branch}' may already exist: {e}")

        # Read original data
        print(f"\n[3/7] Reading original data from '{group_name}'...")
        ds_original = self.read_group(group_name, branch=source_branch)

        # Unify chunks if inconsistent
        try:
            ds_original = ds_original.unify_chunks()
            print("      ✓ Unified inconsistent chunks")
        except TypeError, ValueError:
            pass  # Chunks are already consistent

        print(f"      ✓ Data shape: {dict(ds_original.sizes)}")
        print(f"      ✓ Original chunks: {ds_original.chunks}")
        self._logger.info(f"Original chunks: {ds_original.chunks}")

        # Rechunk
        print("\n[4/7] Rechunking data...")
        ds_rechunked = ds_original.chunk(chunks)
        ds_rechunked = ds_rechunked.unify_chunks()
        print(f"      ✓ New chunks: {ds_rechunked.chunks}")
        self._logger.info(f"New chunks: {ds_rechunked.chunks}")

        # Clear encoding to avoid conflicts
        for var in ds_rechunked.data_vars:
            ds_rechunked[var].encoding = {}
        for coord in ds_rechunked.coords:
            if "chunks" in ds_rechunked[coord].encoding:
                del ds_rechunked[coord].encoding["chunks"]

        # Write rechunked data first (overwrites entire group)
        print(f"\n[5/7] Writing rechunked data to branch '{temp_branch}'...")
        print("      This may take several minutes for large datasets...")
        with self.writable_session(temp_branch) as session:
            to_icechunk(ds_rechunked, session, group=group_name, mode="w")
            session.commit(f"Wrote rechunked data for {group_name}")
        print("      ✓ Data written successfully")

        # Copy subgroups after writing rechunked data
        print(f"\n[6/7] Copying subgroups from '{group_name}'...")
        with self.writable_session(temp_branch) as session:
            with self.readonly_session(source_branch) as icsession:
                source_group = zarr.open_group(icsession.store, mode="r")[group_name]
            target_group = zarr.open_group(session.store, mode="a")[group_name]

            subgroup_count = 0
            for subgroup_name in source_group.group_keys():
                print(f"      ✓ Copying subgroup '{subgroup_name}'...")
                source_subgroup = source_group[subgroup_name]
                target_subgroup = target_group.create_group(
                    subgroup_name, overwrite=True
                )

                # Copy arrays from subgroup
                for array_name in source_subgroup.array_keys():
                    source_array = source_subgroup[array_name]
                    target_array = target_subgroup.create_array(
                        array_name,
                        shape=source_array.shape,
                        dtype=source_array.dtype,
                        chunks=source_array.chunks,
                        overwrite=True,
                    )
                    target_array[:] = source_array[:]

                # Copy subgroup attributes
                target_subgroup.attrs.update(source_subgroup.attrs)
                subgroup_count += 1

            if subgroup_count > 0:
                snapshot_id = session.commit(
                    f"Rechunked {group_name} with chunks={chunks}"
                )
                print(f"      ✓ {subgroup_count} subgroups copied")
            else:
                snapshot_id = next(self.repo.ancestry(branch=temp_branch)).id
                print("      ✓ No subgroups to copy")

        print(f"      ✓ Snapshot ID: {snapshot_id[:12]}")
        self._logger.info(
            f"Rechunked data written to branch '{temp_branch}', snapshot={snapshot_id}"
        )

        # Promote to main if requested
        if promote_to_main:
            print(f"\n[7/7] Promoting to '{source_branch}' branch...")
            rechunked_snapshot = next(self.repo.ancestry(branch=temp_branch)).id
            self.repo.reset_branch(source_branch, rechunked_snapshot)
            print(
                f"      ✓ Branch '{source_branch}' reset to {rechunked_snapshot[:12]}"
            )
            self._logger.info(
                f"Reset branch '{source_branch}' to rechunked snapshot "
                f"{rechunked_snapshot}"
            )

            # Delete temp branch if requested
            if delete_temp_branch:
                print(f"      ✓ Deleting temporary branch '{temp_branch}'...")
                self.delete_branch(temp_branch)
                print("      ✓ Temporary branch deleted")
                self._logger.info(f"Deleted temporary branch '{temp_branch}'")
        else:
            print("\n[7/7] Skipping promotion (promote_to_main=False)")
            print(f"      Rechunked data available on branch '{temp_branch}'")

        print(f"\n{'=' * 60}")
        print(f"✓ Rechunking complete for '{group_name}'")
        print(f"{'=' * 60}\n")

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
            snapshot_id = next(self.repo.ancestry(branch="main")).id

        self.repo.create_tag(tag_name, snapshot_id)
        self._logger.info(f"Created tag '{tag_name}' at snapshot {snapshot_id[:8]}")

    def list_tags(self) -> list[str]:
        """List all tags in the repository."""
        return list(self.repo.list_tags())

    def delete_tag(self, tag_name: str) -> None:
        """Delete a tag (use with caution - tags are meant to be permanent)."""
        self.repo.delete_tag(tag_name)
        self._logger.warning(f"Deleted tag '{tag_name}'")

    def plot_commit_graph(self, max_commits: int = 100) -> Figure:
        """
        Visualize commit history as an interactive git-like graph.

        Creates an interactive visualization showing:
        - Branches with different colors
        - Chronological commit ordering
        - Branch divergence points
        - Commit messages on hover
        - Click to see commit details

        Parameters
        ----------
        max_commits : int
            Maximum number of commits to display (default: 100).

        Returns
        -------
        Figure
            Interactive plotly figure (works in marimo and Jupyter).
        """
        from collections import defaultdict
        from datetime import datetime

        import plotly.graph_objects as go

        # Collect all commits with full metadata
        commit_map = {}  # id -> commit data
        branch_tips = {}  # branch -> latest commit id

        for branch in self.repo.list_branches():
            ancestors = list(self.repo.ancestry(branch=branch))
            if ancestors:
                branch_tips[branch] = ancestors[0].id

            for ancestor in ancestors:
                if ancestor.id not in commit_map:
                    commit_map[ancestor.id] = {
                        "id": ancestor.id,
                        "parent_id": ancestor.parent_id,
                        "message": ancestor.message,
                        "written_at": ancestor.written_at,
                        "branches": [branch],
                    }
                else:
                    # Multiple branches point to same commit
                    commit_map[ancestor.id]["branches"].append(branch)

                if len(commit_map) >= max_commits:
                    break
            if len(commit_map) >= max_commits:
                break

        # Build parent-child relationships
        commits_list = list(commit_map.values())
        commits_list.sort(key=lambda c: c["written_at"])  # Oldest first

        # Assign horizontal positions (chronological)
        commit_x_positions = {}
        for idx, commit in enumerate(commits_list):
            commit["x"] = idx
            commit_x_positions[commit["id"]] = idx

        # Assign vertical positions: commits shared by branches stay on same Y
        # Only diverge when branches have different commits
        branch_names = sorted(
            self.repo.list_branches(), key=lambda b: (b != "main", b)
        )  # main first

        # Build a set of all commit IDs for each branch
        branch_commits = {}
        for branch in branch_names:
            history = list(self.repo.ancestry(branch=branch))
            branch_commits[branch] = {h.id for h in history if h.id in commit_map}

        # Find where branches diverge
        def branches_share_commit(
            commit_id: str,
            branches: list[str],
        ) -> list[str]:
            """Return branches that contain a commit.

            Parameters
            ----------
            commit_id : str
                Commit identifier to check.
            branches : list[str]
                Branch names to search.

            Returns
            -------
            list[str]
                Branches that contain the commit.
            """
            return [b for b in branches if commit_id in branch_commits[b]]

        # Assign Y position: all commits on a single horizontal line initially
        # We'll use vertical offset for parallel branch indicators
        for commit in commits_list:
            commit["y"] = 0  # All on same timeline
            commit["branch_set"] = frozenset(commit["branches"])

        # Color palette for branches
        colors = [
            "#4a9a4a",  # green (main)
            "#5580c8",  # blue
            "#d97643",  # orange
            "#9b59b6",  # purple
            "#e74c3c",  # red
            "#1abc9c",  # turquoise
            "#f39c12",  # yellow
            "#34495e",  # dark gray
        ]
        branch_colors = {b: colors[i % len(colors)] for i, b in enumerate(branch_names)}

        # Build edges: draw parallel lines for shared commits (metro-style)
        edges_by_branch = defaultdict(list)  # branch -> list of edge dicts

        for commit in commits_list:
            if commit["parent_id"] and commit["parent_id"] in commit_map:
                parent = commit_map[commit["parent_id"]]

                # Find which branches share both this commit and its parent
                shared_branches = [
                    b for b in commit["branches"] if b in parent["branches"]
                ]

                for branch in shared_branches:
                    edges_by_branch[branch].append(
                        {
                            "x0": parent["x"],
                            "y0": parent["y"],
                            "x1": commit["x"],
                            "y1": commit["y"],
                        }
                    )

        # Create plotly figure
        fig = go.Figure()

        # Draw edges grouped by branch (parallel lines for shared paths)
        for branch_idx, branch in enumerate(branch_names):
            if branch not in edges_by_branch:
                continue

            color = branch_colors[branch]

            # Draw each edge as a separate line
            for edge in edges_by_branch[branch]:
                # Vertical offset for parallel lines (metro-style)
                offset = (branch_idx - (len(branch_names) - 1) / 2) * 0.15

                fig.add_trace(
                    go.Scatter(
                        x=[edge["x0"], edge["x1"]],
                        y=[edge["y0"] + offset, edge["y1"] + offset],
                        mode="lines",
                        line=dict(color=color, width=3),
                        hoverinfo="skip",
                        showlegend=False,
                        opacity=0.7,
                    )
                )

        # Draw commits (nodes) - one trace per unique commit
        # Color by which branches include it
        x_vals = [c["x"] for c in commits_list]
        y_vals = [c["y"] for c in commits_list]

        # Format hover text
        hover_texts = []
        marker_colors = []
        marker_symbols = []

        for c in commits_list:
            # Handle both string and datetime objects
            if isinstance(c["written_at"], str):
                time_str = datetime.fromisoformat(c["written_at"]).strftime(
                    "%Y-%m-%d %H:%M"
                )
            else:
                time_str = c["written_at"].strftime("%Y-%m-%d %H:%M")

            branches_str = ", ".join(c["branches"])
            hover_texts.append(
                f"<b>{c['message'] or 'No message'}</b><br>"
                f"Commit: {c['id'][:12]}<br>"
                f"Branches: {branches_str}<br>"
                f"Time: {time_str}"
            )

            # Color by first branch (priority: main)
            if "main" in c["branches"]:
                marker_colors.append(branch_colors["main"])
            else:
                marker_colors.append(branch_colors[c["branches"][0]])

            # Star for branch tips
            if c["id"] in branch_tips.values():
                marker_symbols.append("star")
            else:
                marker_symbols.append("circle")

        fig.add_trace(
            go.Scatter(
                x=x_vals,
                y=y_vals,
                mode="markers",
                name="Commits",
                marker=dict(
                    size=14,
                    color=marker_colors,
                    symbol=marker_symbols,
                    line=dict(color="white", width=2),
                ),
                hovertext=hover_texts,
                hoverinfo="text",
                showlegend=False,
            )
        )

        # Add legend traces (invisible points just for legend)
        for branch_idx, branch in enumerate(branch_names):
            fig.add_trace(
                go.Scatter(
                    x=[None],
                    y=[None],
                    mode="markers",
                    name=branch,
                    marker=dict(
                        size=10,
                        color=branch_colors[branch],
                        line=dict(color="white", width=2),
                    ),
                    showlegend=True,
                )
            )

        # Layout styling
        title_text = (
            f"Commit Graph: {self.site_name} ({len(commits_list)} commits, "
            f"{len(branch_names)} branches)"
        )
        fig.update_layout(
            title=dict(
                text=title_text,
                font=dict(size=16, color="#e5e5e5"),
            ),
            xaxis=dict(
                title="Time (oldest ← → newest)",
                showticklabels=False,
                showgrid=True,
                gridcolor="rgba(255,255,255,0.1)",
                zeroline=False,
            ),
            yaxis=dict(
                title="",
                showticklabels=False,
                showgrid=False,
                zeroline=False,
                range=[-1, 1],  # Fixed range for single timeline
            ),
            plot_bgcolor="#1a1a1a",
            paper_bgcolor="#1a1a1a",
            font=dict(color="#e5e5e5"),
            hovermode="closest",
            height=400,
            width=max(800, len(commits_list) * 50),
            legend=dict(
                title="Branches",
                orientation="h",
                x=0,
                y=-0.15,
                bgcolor="rgba(30,30,30,0.8)",
                bordercolor="rgba(255,255,255,0.2)",
                borderwidth=1,
            ),
        )

        return fig

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
        # Find the snapshot in ancestry
        for ancestor in self.repo.ancestry(branch="main"):
            if ancestor.id == snapshot_id or ancestor.id.startswith(snapshot_id):
                info = {
                    "snapshot_id": ancestor.id,
                    "message": ancestor.message,
                    "written_at": ancestor.written_at,
                    "parent_id": ancestor.parent_id,
                }

                # Try to get groups at this snapshot
                try:
                    session = self.repo.readonly_session(snapshot_id=ancestor.id)
                    root = zarr.open(session.store, mode="r")
                    info["groups"] = list(root.group_keys())
                    info["arrays"] = list(root.array_keys())
                except Exception as e:
                    self._logger.warning(f"Could not inspect snapshot contents: {e}")

                return info

        raise ValueError(f"Snapshot {snapshot_id} not found in history")

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
        self, expire_days: int = 7, cleanup_branches: bool = True, run_gc: bool = True
    ) -> dict:
        """
        Run full maintenance on the store.

        Parameters
        ----------
        expire_days : int
            Days of snapshot history to keep
        cleanup_branches : bool
            Remove stale temporary branches
        run_gc : bool
            Run garbage collection after expiration

        Returns
        -------
        dict
            Summary of maintenance actions
        """
        self._logger.info(f"Starting maintenance on {self.store_type}")

        results = {"expired_snapshots": 0, "deleted_branches": [], "gc_summary": None}

        # Expire old snapshots
        expired_ids = self.expire_old_snapshots(days=expire_days)
        results["expired_snapshots"] = len(expired_ids)

        # Cleanup stale branches
        if cleanup_branches:
            deleted_branches = self.cleanup_stale_branches()
            results["deleted_branches"] = deleted_branches

        # Garbage collection
        if run_gc:
            from datetime import datetime, timedelta

            cutoff = datetime.now(UTC) - timedelta(days=expire_days)
            gc_summary = self.repo.garbage_collect(delete_object_older_than=cutoff)
            results["gc_summary"] = {
                "bytes_deleted": gc_summary.bytes_deleted,
                "chunks_deleted": gc_summary.chunks_deleted,
                "manifests_deleted": gc_summary.manifests_deleted,
            }

        self._logger.info(f"Maintenance complete: {results}")
        return results

    def sanitize_store(
        self,
        source_branch: str = "main",
        temp_branch: str = "sanitize_temp",
        promote_to_main: bool = True,
        delete_temp_branch: bool = True,
    ) -> str:
        """
        Sanitize all groups by removing NaN-only SIDs and cleaning coordinates.

        Creates a temporary branch, applies sanitization to all groups, then
        optionally promotes to main and cleans up.

        Parameters
        ----------
        source_branch : str, default "main"
            Branch to read original data from.
        temp_branch : str, default "sanitize_temp"
            Temporary branch name for sanitized data.
        promote_to_main : bool, default True
            If True, reset main branch to sanitized snapshot after writing.
        delete_temp_branch : bool, default True
            If True, delete temporary branch after promotion.

        Returns
        -------
        str
            Snapshot ID of the sanitized data.
        """
        import time

        from icechunk.xarray import to_icechunk

        print(f"\n{'=' * 60}")
        print("Starting store sanitization")
        print(f"{'=' * 60}\n")

        # Step 1: Get current snapshot
        print(f"[1/6] Getting current snapshot from '{source_branch}'...")
        current_snapshot = next(self.repo.ancestry(branch=source_branch)).id
        print(f"      ✓ Current snapshot: {current_snapshot[:12]}")

        # Step 2: Create temp branch
        print(f"\n[2/6] Creating temporary branch '{temp_branch}'...")
        try:
            self.repo.create_branch(temp_branch, current_snapshot)
            print(f"      ✓ Branch '{temp_branch}' created")
        except Exception:
            print("      ⚠ Branch exists, deleting and recreating...")
            self.delete_branch(temp_branch)
            self.repo.create_branch(temp_branch, current_snapshot)
            print(f"      ✓ Branch '{temp_branch}' created")

        # Step 3: Get all groups
        print("\n[3/6] Discovering groups...")
        groups = self.list_groups()
        print(f"      ✓ Found {len(groups)} groups: {groups}")

        # Step 4: Sanitize each group
        print("\n[4/6] Sanitizing groups...")
        sanitized_count = 0

        for group_name in groups:
            print(f"\n      Processing '{group_name}'...")
            t_start = time.time()

            try:
                # Read original data
                ds_original = self.read_group(group_name, branch=source_branch)
                original_sids = len(ds_original.sid)
                print(f"        • Original: {original_sids} SIDs")

                # Sanitize: remove SIDs with all-NaN data
                ds_sanitized = self._sanitize_dataset(ds_original)
                sanitized_sids = len(ds_sanitized.sid)
                removed_sids = original_sids - sanitized_sids

                print(
                    f"        • Sanitized: {sanitized_sids} SIDs "
                    f"(removed {removed_sids})"
                )

                # Write sanitized data
                with self.writable_session(temp_branch) as session:
                    to_icechunk(ds_sanitized, session, group=group_name, mode="w")

                    # Copy metadata subgroups if they exist
                    try:
                        with self.readonly_session(source_branch) as read_session:
                            source_group = zarr.open_group(
                                read_session.store, mode="r"
                            )[group_name]
                            if "metadata" in source_group.group_keys():
                                # Copy entire metadata subgroup
                                dest_group = zarr.open_group(session.store)[group_name]
                                zarr.copy(
                                    source_group["metadata"],
                                    dest_group,
                                    name="metadata",
                                )
                                print("        • Copied metadata subgroup")
                    except Exception as e:
                        print(f"        ⚠ Could not copy metadata: {e}")

                    session.commit(
                        f"Sanitized {group_name}: removed {removed_sids} empty SIDs"
                    )

                t_elapsed = time.time() - t_start
                print(f"        ✓ Completed in {t_elapsed:.2f}s")
                sanitized_count += 1

            except Exception as e:
                print(f"        ✗ Failed: {e}")
                continue

        print(f"\n      ✓ Sanitized {sanitized_count}/{len(groups)} groups")

        # Step 5: Get final snapshot
        print("\n[5/6] Getting sanitized snapshot...")
        sanitized_snapshot = next(self.repo.ancestry(branch=temp_branch)).id
        print(f"      ✓ Snapshot: {sanitized_snapshot[:12]}")

        # Step 6: Promote to main
        if promote_to_main:
            print(f"\n[6/6] Promoting to '{source_branch}' branch...")
            self.repo.reset_branch(source_branch, sanitized_snapshot)
            print(
                f"      ✓ Branch '{source_branch}' reset to {sanitized_snapshot[:12]}"
            )

            if delete_temp_branch:
                print(f"      ✓ Deleting temporary branch '{temp_branch}'...")
                self.delete_branch(temp_branch)
                print("      ✓ Temporary branch deleted")
        else:
            print("\n[6/6] Skipping promotion (promote_to_main=False)")
            print(f"      Sanitized data available on branch '{temp_branch}'")

        print(f"\n{'=' * 60}")
        print("✓ Sanitization complete")
        print(f"{'=' * 60}\n")

        return sanitized_snapshot

    def _sanitize_dataset(self, ds: xr.Dataset) -> xr.Dataset:
        """
        Remove SIDs that have all-NaN data and clean coordinate metadata.

        Parameters
        ----------
        ds : xr.Dataset
            Dataset to sanitize

        Returns
        -------
        xr.Dataset
            Sanitized dataset with NaN-only SIDs removed
        """
        # Find SIDs that have at least some non-NaN data across all variables
        has_data = ds.to_array().notnull().any(dim=["variable", "epoch"])

        # Keep only SIDs with data
        sids_with_data = ds.sid.values[has_data.values]
        ds_clean = ds.sel(sid=sids_with_data)

        # Clean coordinate metadata - remove NaN values from string coordinates
        for coord in ["band", "system", "code", "sv"]:
            if coord in ds_clean.coords:
                coord_values = ds_clean[coord].values
                # Convert object arrays, handling NaN
                if coord_values.dtype == object:
                    clean_values = []
                    for val in coord_values:
                        if isinstance(val, float) and np.isnan(val):
                            clean_values.append("")
                        elif val is None or (isinstance(val, str) and val == "nan"):
                            clean_values.append("")
                        else:
                            clean_values.append(str(val))
                    ds_clean = ds_clean.assign_coords({coord: ("sid", clean_values)})

        # Numeric coordinates can keep NaN if needed
        for coord in ["freq_center", "freq_min", "freq_max"]:
            if coord in ds_clean.coords:
                # These are fine as-is since they're numeric
                pass

        return ds_clean

    def safe_temporal_aggregate(
        self,
        group: str,
        freq: str = "1D",
        vars_to_aggregate: Sequence[str] = ("VOD",),
        geometry_vars: Sequence[str] = ("phi", "theta"),
        drop_empty: bool = True,
        branch: str = "main",
    ) -> xr.Dataset:
        """Aggregate temporally irregular VOD data per SID.

        Each satellite (SID) is aggregated independently within each
        time bin.  Mixing observations across satellites is physically
        meaningless because each observes a different part of the canopy
        from a different sky position.

        .. note::

           For production use, prefer ``canvod.ops.TemporalAggregate``
           which uses Polars groupby and handles all coordinate types
           explicitly.  This method is a convenience wrapper for quick
           interactive exploration.

        Parameters
        ----------
        group : str
            Group name to aggregate.
        freq : str, default "1D"
            Resample frequency string.
        vars_to_aggregate : Sequence[str], optional
            Variables to aggregate using mean.
        geometry_vars : Sequence[str], optional
            Geometry variables to aggregate using mean (centroid of
            contributing sky positions).
        drop_empty : bool, default True
            Drop empty epochs after aggregation.
        branch : str, default "main"
            Branch name to read from.

        Returns
        -------
        xr.Dataset
            Aggregated dataset with independent per-SID aggregation.
        """
        log = get_logger(__name__)

        with self.readonly_session(branch=branch) as session:
            ds = xr.open_zarr(session.store, group=group, consolidated=False)

            log.info(
                "Aggregating group",
                group=group,
                branch=branch,
                freq=freq,
            )

            # Aggregate data and geometry vars with mean (per SID
            # independently — resample preserves the sid dimension).
            all_vars = list(vars_to_aggregate) + list(geometry_vars)
            merged_vars = []
            for var in all_vars:
                if var in ds:
                    merged_vars.append(ds[var].resample(epoch=freq).mean())
                else:
                    log.warning("Skipping missing variable", var=var)
            ds_agg = xr.merge(merged_vars)

            # Preserve sid-only coordinates (sv, band, code, etc.)
            for coord in ds.coords:
                if coord in ds_agg.coords or coord == "epoch":
                    continue
                coord_dims = ds.coords[coord].dims
                # Only copy coords whose dims all survive in ds_agg
                if all(d in ds_agg.dims for d in coord_dims):
                    ds_agg[coord] = ds[coord]

            # Drop all-NaN epochs if requested
            if drop_empty and "VOD" in ds_agg:
                valid_mask = ds_agg["VOD"].notnull().any(dim="sid").compute()
                ds_agg = ds_agg.isel(epoch=valid_mask)

            log.info("Aggregation done", sizes=dict(ds_agg.sizes))
            return ds_agg

    def safe_temporal_aggregate_to_branch(
        self,
        source_group: str,
        target_group: str,
        target_branch: str,
        freq: str = "1D",
        overwrite: bool = False,
        **kwargs: Any,
    ) -> xr.Dataset:
        """Aggregate a group and save to a new Icechunk branch/group.

        Parameters
        ----------
        source_group : str
            Source group name.
        target_group : str
            Target group name.
        target_branch : str
            Target branch name.
        freq : str, default "1D"
            Resample frequency string.
        overwrite : bool, default False
            Whether to overwrite an existing branch.
        **kwargs : Any
            Additional keyword args passed to safe_temporal_aggregate().

        Returns
        -------
        xr.Dataset
            Aggregated dataset written to the target branch.
        """

        print(
            f"🚀 Creating new aggregated branch '{target_branch}' at '{target_group}'"
        )

        # Compute safe aggregation
        ds_agg = self.safe_temporal_aggregate(
            group=source_group,
            freq=freq,
            **kwargs,
        )

        # Write to new branch
        current_snapshot = next(self.repo.ancestry(branch="main")).id
        self.delete_branch(target_branch)
        self.repo.create_branch(target_branch, current_snapshot)
        with self.writable_session(target_branch) as session:
            to_icechunk(
                obj=ds_agg,
                session=session,
                group=target_group,
                mode="w",
            )
            session.commit(f"Saved aggregated data to {target_group} at freq={freq}")

        print(
            f"✅ Saved aggregated dataset to branch '{target_branch}' "
            f"(group '{target_group}')"
        )
        return ds_agg


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


def write_vod_to_store(
    vod_store: MyIcechunkStore,
    group_name: str,
    vod_ds: xr.Dataset,
    canopy_hash: str,
    sky_hash: str,
    commit_msg: str = "VOD calculation",
) -> str:
    """Write VOD data to store with metadata tracking."""

    with vod_store.writable_session() as session:
        vod_store.write_dataset(dataset=vod_ds, group_name=group_name, session=session)

        start = vod_ds["epoch"].values[0]
        end = vod_ds["epoch"].values[-1]

        vod_store.append_metadata(
            group_name=group_name,
            rinex_hash=f"{canopy_hash}_{sky_hash}",
            start=start,
            end=end,
            snapshot_id=session.snapshot_id,
            action="insert",
            commit_msg=commit_msg,
            dataset_attrs=dict(vod_ds.attrs),
        )

        snapshot_id = session.commit(commit_msg)

    return snapshot_id


# Example usage
if __name__ == "__main__":
    import tempfile

    from gnssvodpy.research_sites_config import RESEARCH_SITES

    # Create a temporary directory for testing
    with tempfile.TemporaryDirectory() as temp_dir:
        print(f"Temporary directory created at: {temp_dir}")

    # Example: Create stores for Rosalia site
    rosalia_config = RESEARCH_SITES["Rosalia"]

    # Create RINEX store
    rinex_store = create_rinex_store(Path(temp_dir) / "rinex_store")
    print(f"RINEX store: {rinex_store}")

    # Create VOD store
    vod_store = create_vod_store(Path(temp_dir) / "vod_store")
    print(f"VOD store: {vod_store}")

    # List existing groups
    print(f"RINEX groups: {rinex_store.list_groups()}")
    print(f"VOD groups: {vod_store.list_groups()}")
