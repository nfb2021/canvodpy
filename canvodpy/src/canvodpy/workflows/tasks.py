"""Airflow-compatible task functions for GNSS daily processing pipeline.

Each function accepts only primitives (str, dict, list, None) and returns
JSON-serializable dicts suitable for XCom.  They delegate to existing
canvodpy machinery — no pipeline rewrite.

Two DAG topologies (SBF and RINEX)::

    SBF:   validate_dirs → check_sbf → process_sbf
             → validate_ingest → calculate_vod → cleanup

    RINEX: validate_dirs → wait_for_rinex → wait_for_sp3 → fetch_aux_data
             → process_rinex → validate_ingest → calculate_vod → cleanup
"""

from __future__ import annotations

import datetime
import shutil
from pathlib import Path
from typing import Any, cast

import numpy as np
import structlog
import xarray as xr

from canvod.auxiliary.pipeline import AuxDataPipeline
from canvod.auxiliary.position import ECEFPosition
from canvod.readers import MatchedDirs
from canvod.utils.config import load_config
from canvod.utils.tools import YYYYDOY
from canvodpy.orchestrator.interpolator import (
    ClockConfig,
    ClockInterpolationStrategy,
    Sp3Config,
    Sp3InterpolationStrategy,
)

logger = structlog.get_logger(__name__)


def _cap_blas_threads(n: int = 1) -> None:
    """Set BLAS/OpenMP thread-cap env vars if not already set by the caller.

    Called at the start of CPU-heavy tasks so that numpy/scipy don't spawn
    os.cpu_count() threads per process.  Only sets vars that are absent,
    so an operator-level override (e.g. Airflow env) always wins.
    """
    import os

    s = str(n)
    for var in (
        "OMP_NUM_THREADS",
        "MKL_NUM_THREADS",
        "OPENBLAS_NUM_THREADS",
        "NUMEXPR_NUM_THREADS",
        "VECLIB_MAXIMUM_THREADS",
    ):
        if var not in os.environ:
            os.environ[var] = s


# GNSS file glob patterns — sourced from canvod-virtualiconvname BUILTIN_PATTERNS
def _get_gnss_globs() -> list[str]:
    from canvod.virtualiconvname.patterns import BUILTIN_PATTERNS, auto_match_order

    globs: set[str] = set()
    for name in auto_match_order():
        globs.update(BUILTIN_PATTERNS[name].file_globs)
    return sorted(globs)


# ---------------------------------------------------------------------------
# Utility extracted from RinexDataProcessor._parse_sampling_interval_from_filename
# ---------------------------------------------------------------------------


def parse_sampling_interval_from_filename(filename: str) -> float | None:
    """Extract sampling interval from a RINEX v3 long filename.

    RINEX v3.04 long filenames encode the data frequency at a fixed
    position, e.g. ``ROSA01TUW_R_20250020000_01D_05S_AA.rnx`` where
    ``05S`` means 5-second sampling.

    Parameters
    ----------
    filename : str
        RINEX filename (stem or full name).

    Returns
    -------
    float or None
        Sampling interval in seconds, or ``None`` if parsing fails.
    """
    import re

    parts = Path(filename).stem.split("_")
    if len(parts) >= 5:
        freq = parts[4]  # e.g. "05S", "30S", "01Z" (1 Hz)
        m = re.match(r"^(\d+)([SMHDZC])$", freq)
        if m:
            value, unit = int(m.group(1)), m.group(2)
            multipliers = {"S": 1, "M": 60, "H": 3600, "D": 86400}
            if unit == "Z":  # Hz -> seconds
                return 1.0 / value if value else None
            if unit in multipliers:
                return float(value * multipliers[unit])
    return None


def _resolve_date(yyyydoy: str) -> YYYYDOY:
    """Accept ``YYYYDDD`` *or* Airflow ``ds`` (``YYYY-MM-DD``)."""
    if "-" in yyyydoy:
        return YYYYDOY.from_date(datetime.date.fromisoformat(yyyydoy))
    return YYYYDOY.from_str(yyyydoy)


def _get_rinex_files(directory: Path) -> list[Path]:
    """Glob GNSS data files from *directory* using BUILTIN_PATTERNS globs."""
    from natsort import natsorted

    if not directory.exists():
        return []

    files: list[Path] = []
    seen: set[Path] = set()
    for pattern in _get_gnss_globs():
        for path in directory.glob(pattern):
            if path.is_file() and path not in seen:
                seen.add(path)
                files.append(path)
    return natsorted(files)


# ---------------------------------------------------------------------------
# Task 1 — check_rinex
# ---------------------------------------------------------------------------


def _discover_files_for_date(
    site_cfg,
    rcfg,
    receiver_name: str,
    date_obj: YYYYDOY,
    base: Path,
) -> tuple[list[Path], list[str]]:
    """Discover files for a receiver+date using FilenameMapper or glob fallback.

    Returns (file_paths, warnings).
    """
    warnings: list[str] = []

    # Prefer FilenameMapper when naming config is available
    if site_cfg.naming and rcfg.naming:
        try:
            from canvod.virtualiconvname import (
                FilenameMapper,
                ReceiverNamingConfig,
                SiteNamingConfig,
            )

            mapper = FilenameMapper(
                site_naming=SiteNamingConfig(**site_cfg.naming),
                receiver_naming=ReceiverNamingConfig(**rcfg.naming),
                receiver_type=rcfg.type,
                receiver_base_dir=base / rcfg.directory,
            )
            vfs = mapper.discover_for_date(date_obj.year, date_obj.doy)
            overlaps = FilenameMapper.detect_overlaps(vfs)
            if overlaps:
                warnings.append(
                    f"{receiver_name}: {len(overlaps)} temporal overlaps detected"
                )
                overlap_paths = {vf.physical_path for pair in overlaps for vf in pair}
                vfs = [vf for vf in vfs if vf.physical_path not in overlap_paths]
            return [vf.physical_path for vf in vfs], warnings
        except Exception:
            # Fall back to glob if naming config is invalid
            pass

    # Fallback: raw glob
    recv_dir = base / rcfg.directory / date_obj.yydoy
    files = _get_rinex_files(recv_dir)
    return files, warnings


def check_rinex(site: str, yyyydoy: str) -> dict:
    """Check whether RINEX files exist for all receivers on the given date.

    Uses ``FilenameMapper`` when naming config is available (prevents
    duplicate ingest from daily+sub-daily files). Falls back to raw
    glob when naming config is absent.

    Parameters
    ----------
    site : str
        Research site name (must exist in config).
    yyyydoy : str
        Date in ``YYYYDDD`` format **or** Airflow ``ds`` (``YYYY-MM-DD``).

    Returns
    -------
    dict
        ``{"site", "yyyydoy", "ready": bool, "receivers": {...}}``

    Raises
    ------
    RuntimeError
        If RINEX files are missing for any receiver (stops the DAG run
        so Airflow can retry later).
    """
    config = load_config()
    site_cfg = config.sites.sites[site]
    date_obj = _resolve_date(yyyydoy)
    base = site_cfg.get_base_path()

    receivers: dict[str, dict] = {}
    all_ready = True

    for name, rcfg in site_cfg.receivers.items():
        files, file_warnings = _discover_files_for_date(
            site_cfg, rcfg, name, date_obj, base
        )
        has_files = len(files) > 0
        receivers[name] = {
            "directory": str(base / rcfg.directory),
            "has_files": has_files,
            "files": [str(f) for f in files],
            "count": len(files),
            "warnings": file_warnings,
        }
        if not has_files:
            all_ready = False

    result = {
        "site": site,
        "yyyydoy": date_obj.to_str(),
        "ready": all_ready,
        "receivers": receivers,
    }

    if not all_ready:
        missing = [n for n, r in receivers.items() if not r["has_files"]]
        msg = (
            f"RINEX files not yet available for {site} {date_obj.to_str()}: "
            f"missing receivers {missing}"
        )
        logger.warning(msg)
        raise RuntimeError(msg)

    logger.info("check_rinex: %s %s — all receivers ready", site, date_obj.to_str())
    return result


# ---------------------------------------------------------------------------
# Task 1a-sbf — check_sbf
# ---------------------------------------------------------------------------


def check_sbf(site: str, yyyydoy: str) -> dict:
    """Check whether SBF files exist for all receivers on the given date.

    Same logic as :func:`check_rinex` but for SBF binary data. SBF files
    are available immediately after receiver transfer (no sensor wait needed).

    Parameters
    ----------
    site : str
        Research site name (must exist in config).
    yyyydoy : str
        Date in ``YYYYDDD`` format **or** Airflow ``ds`` (``YYYY-MM-DD``).

    Returns
    -------
    dict
        ``{"site", "yyyydoy", "ready": bool, "receivers": {...}}``

    Raises
    ------
    RuntimeError
        If SBF files are missing for any receiver.
    """
    config = load_config()
    site_cfg = config.sites.sites[site]
    date_obj = _resolve_date(yyyydoy)
    base = site_cfg.get_base_path()

    receivers: dict[str, dict] = {}
    all_ready = True

    for name, rcfg in site_cfg.receivers.items():
        files, file_warnings = _discover_files_for_date(
            site_cfg, rcfg, name, date_obj, base
        )
        # Filter to SBF files only
        sbf_files = [f for f in files if f.suffix.lower() == ".sbf"]
        has_files = len(sbf_files) > 0
        receivers[name] = {
            "directory": str(base / rcfg.directory),
            "has_files": has_files,
            "files": [str(f) for f in sbf_files],
            "count": len(sbf_files),
            "warnings": file_warnings,
        }
        if not has_files:
            all_ready = False

    result = {
        "site": site,
        "yyyydoy": date_obj.to_str(),
        "ready": all_ready,
        "receivers": receivers,
    }

    if not all_ready:
        missing = [n for n, r in receivers.items() if not r["has_files"]]
        msg = (
            f"SBF files not yet available for {site} {date_obj.to_str()}: "
            f"missing receivers {missing}"
        )
        logger.warning(msg)
        raise RuntimeError(msg)

    logger.info("check_sbf: %s %s — all receivers ready", site, date_obj.to_str())
    return result


# ---------------------------------------------------------------------------
# Task 1b — validate_data_dirs
# ---------------------------------------------------------------------------


def _resolve_recipe(recipe_name: str) -> Path:
    """Resolve a recipe name to its YAML file path.

    Searches ``config/recipes/`` relative to the monorepo root.
    """
    from canvod.utils.config.loader import find_monorepo_root

    recipe_path = find_monorepo_root() / "config" / "recipes" / f"{recipe_name}.yaml"
    if not recipe_path.exists():
        msg = (
            f"Recipe file not found: {recipe_path}\n"
            f"Create it with: just naming-init {recipe_name}"
        )
        raise FileNotFoundError(msg)
    return recipe_path


def _validate_receiver_with_recipe(
    recipe_name: str,
    receiver_base_dir: Path,
    reader_format: str | None,
) -> dict:
    """Validate a receiver's data directory using a NamingRecipe.

    Returns a result dict with status, counts, and sample canonical names.
    Raises ValueError on validation failure.
    """
    from natsort import natsorted

    from canvod.virtualiconvname.recipe import NamingRecipe

    recipe_path = _resolve_recipe(recipe_name)
    recipe = NamingRecipe.load(recipe_path)

    # Discover files using the recipe's glob pattern
    if not receiver_base_dir.exists():
        return {
            "status": "valid",
            "matched": 0,
            "skipped_format": 0,
            "unmatched": 0,
            "overlaps": 0,
            "warnings": [f"Directory does not exist: {receiver_base_dir}"],
            "sample_canonical_names": [],
        }

    # Walk subdirectories or flat depending on layout
    all_files: list[Path] = []
    for f in receiver_base_dir.rglob(recipe.glob):
        if f.is_file():
            all_files.append(f)
    all_files = natsorted(all_files)

    matched = []
    skipped = []
    unmatched = []
    errors = []

    for f in all_files:
        if not recipe.matches(f.name):
            skipped.append(f)
            continue
        try:
            vf = recipe.to_virtual_file(f)
            matched.append(vf)
        except ValueError as exc:
            unmatched.append(f)
            errors.append(f"  {f.name}: {exc}")

    # Check for temporal overlaps (same canonical name = duplicate)
    canonical_counts: dict[str, list[Path]] = {}
    for vf in matched:
        key = vf.canonical_str
        canonical_counts.setdefault(key, []).append(vf.physical_path)
    duplicates = {k: v for k, v in canonical_counts.items() if len(v) > 1}

    warnings: list[str] = []
    if duplicates:
        for cn, paths in duplicates.items():
            warnings.append(
                f"Duplicate canonical name {cn}: " + ", ".join(p.name for p in paths)
            )

    if unmatched:
        detail = "\n".join(errors[:20])
        if len(errors) > 20:
            detail += f"\n  ... and {len(errors) - 20} more"
        raise ValueError(
            f"{len(unmatched)} files could not be parsed by recipe "
            f"'{recipe_name}':\n{detail}"
        )

    return {
        "status": "valid",
        "matched": len(matched),
        "skipped": len(skipped),
        "unmatched": 0,
        "overlaps": len(duplicates),
        "warnings": warnings,
        "sample_canonical_names": [vf.canonical_str for vf in matched[:5]],
    }


def validate_data_dirs(site: str) -> dict:
    """Pre-flight validation of all receiver data directories for a site.

    Checks every receiver's data directory against the naming convention:
    - All files must map to a canonical ``CanVODFilename``
    - No temporal overlaps (e.g. daily + sub-daily files for the same day)
    - Duplicate canonical names are flagged

    Supports two validation modes per receiver:
    - **Recipe mode**: when ``recipe`` is set in the receiver config,
      loads a ``NamingRecipe`` from ``config/recipes/{recipe}.yaml``
    - **Legacy mode**: when ``naming`` dict is set, uses
      ``SiteNamingConfig`` + ``ReceiverNamingConfig`` + ``DataDirectoryValidator``

    Run this **before** starting a processing campaign to catch data
    quality issues early.

    Parameters
    ----------
    site : str
        Research site name (must exist in config).

    Returns
    -------
    dict
        ``{"site": str, "valid": bool, "receivers": {name: {status, ...}}}``

    Raises
    ------
    ValueError
        If any receiver directory has validation errors.
    """
    config = load_config()
    available = list(config.sites.sites.keys())
    if site not in config.sites.sites:
        msg = f"Unknown site '{site}'. Available sites: {', '.join(available) or '(none)'}"
        raise KeyError(msg)
    site_cfg = config.sites.sites[site]
    base = site_cfg.get_base_path()

    receivers_result: dict[str, dict] = {}
    all_valid = True
    errors: list[str] = []

    for name, rcfg in site_cfg.receivers.items():
        receiver_base_dir = base / rcfg.directory
        reader_format = rcfg.reader_format

        # Recipe-based validation (preferred)
        if rcfg.recipe:
            try:
                receivers_result[name] = _validate_receiver_with_recipe(
                    recipe_name=rcfg.recipe,
                    receiver_base_dir=receiver_base_dir,
                    reader_format=reader_format,
                )
                logger.info(
                    "validate_data_dirs: %s/%s — %d files via recipe '%s'",
                    site,
                    name,
                    receivers_result[name]["matched"],
                    rcfg.recipe,
                )
            except (ValueError, FileNotFoundError) as exc:
                all_valid = False
                errors.append(f"[{name}] {exc}")
                receivers_result[name] = {"status": "invalid", "error": str(exc)}
                logger.error("validate_data_dirs: %s/%s — FAILED: %s", site, name, exc)
            continue

        # Legacy naming-dict validation
        if rcfg.naming:
            from canvod.virtualiconvname import (
                DataDirectoryValidator,
                ReceiverNamingConfig,
                SiteNamingConfig,
            )

            if not site_cfg.naming:
                msg = (
                    f"Receiver '{name}' uses naming dict but site '{site}' "
                    "has no site-level naming config."
                )
                raise ValueError(msg)

            site_naming = SiteNamingConfig(**site_cfg.naming)
            receiver_naming = ReceiverNamingConfig(**rcfg.naming)
            validator = DataDirectoryValidator()

            try:
                report = validator.validate_receiver(
                    site_naming=site_naming,
                    receiver_naming=receiver_naming,
                    receiver_type=rcfg.type,
                    receiver_base_dir=receiver_base_dir,
                    reader_format=reader_format,
                )
                receivers_result[name] = {
                    "status": "valid",
                    "matched": len(report.matched),
                    "skipped_format": len(report.skipped_format),
                    "unmatched": 0,
                    "overlaps": 0,
                    "warnings": report.warnings,
                    "sample_canonical_names": [
                        vf.canonical_str for vf in report.matched[:5]
                    ],
                }
                logger.info(
                    "validate_data_dirs: %s/%s — %d files, all valid",
                    site,
                    name,
                    len(report.matched),
                )
            except ValueError as exc:
                all_valid = False
                errors.append(f"[{name}] {exc}")
                receivers_result[name] = {"status": "invalid", "error": str(exc)}
                logger.error("validate_data_dirs: %s/%s — FAILED: %s", site, name, exc)
            continue

        # No recipe and no naming — skip
        receivers_result[name] = {
            "status": "skipped",
            "reason": "no recipe or naming config",
        }
        logger.warning("Receiver '%s' has no recipe or naming config, skipping", name)

    result = {
        "site": site,
        "valid": all_valid,
        "receivers": receivers_result,
    }

    if not all_valid:
        full_report = "\n\n".join(errors)
        raise ValueError(
            f"Data directory validation failed for site '{site}':\n\n{full_report}"
        )

    logger.info("validate_data_dirs: %s — all receivers valid", site)
    return result


# ---------------------------------------------------------------------------
# SP3/CLK sensor helper — shared by all DAGs that wait for agency products
# ---------------------------------------------------------------------------


def check_sp3_availability(ds: str) -> object:
    """Return a ``PokeReturnValue`` for the SP3/CLK date-age sensor.

    Uses a date-age heuristic keyed to ``processing.aux_data.product_type``:

    * ``ultra-rapid`` — gate at 0 days (always available)
    * ``rapid``       — gate at 2 days
    * ``final``       — gate at 14 days (default)

    Raises ``AirflowSkipException`` when age > 30 days to prevent zombie runs.
    Falls back to ``"final"`` if config cannot be loaded.

    Intended for use inside ``@task.sensor`` bodies so that the four identical
    sensor copies (2 DAGs × 2 repos) share a single implementation.

    Parameters
    ----------
    ds : str
        Airflow ``ds`` macro value (``YYYY-MM-DD`` ISO date string).
    """
    import datetime as dt

    from airflow.exceptions import (
        AirflowSkipException,  # type: ignore[unresolved-import]
    )
    from airflow.sensors.base import PokeReturnValue  # type: ignore[unresolved-import]

    target = dt.date.fromisoformat(ds)
    age = (dt.date.today() - target).days

    if age > 30:
        raise AirflowSkipException(
            f"SP3 not available for {ds} after {age} days — abandoning"
        )

    try:
        product_type = load_config().processing.aux_data.product_type
    except Exception:
        product_type = "final"

    _MIN_AGE: dict[str, int] = {"ultra-rapid": 0, "rapid": 2, "final": 14}
    min_age = _MIN_AGE.get(product_type, 14)
    available = age >= min_age

    return PokeReturnValue(
        is_done=available,
        xcom_value={
            "sp3_ready": available,
            "product_type": product_type,
            "age_days": age,
            "min_age_days": min_age,
        },
    )


# ---------------------------------------------------------------------------
# Task 2 — fetch_aux_data
# ---------------------------------------------------------------------------


def fetch_aux_data(
    site: str,
    yyyydoy: str,
    agency: str | None = None,
    product_type: str | None = None,
    sampling_interval_s: float | None = None,
) -> dict:
    """Download SP3+CLK, Hermite-interpolate, and write to a temp Zarr store.

    SP3/CLK products are published with a delay (rapid ~1 day,
    final ~12-14 days).  When products are not yet available the FTP
    download raises ``RuntimeError("Failed to download …")``.  This
    exception is **not** caught here — it propagates to Airflow so the
    task is marked as failed and retried on the next scheduled run.

    Parameters
    ----------
    site : str
        Research site name.
    yyyydoy : str
        Date in ``YYYYDDD`` format **or** Airflow ``ds`` (``YYYY-MM-DD``).
    agency : str, optional
        Analysis centre code (e.g. ``"COD"``).  Defaults to config value.
    product_type : str, optional
        ``"final"`` or ``"rapid"``.  Defaults to config value.
    sampling_interval_s : float, optional
        Observation sampling interval in seconds.  Auto-detected from
        filename if ``None``.

    Returns
    -------
    dict
        ``{"site", "yyyydoy", "aux_zarr_path", "sampling_interval_s",
        "n_epochs", "n_sids"}``
    """
    config = load_config()
    site_cfg = config.sites.sites[site]
    date_obj = _resolve_date(yyyydoy)
    keep_sids = config.sids.get_sids()

    # Resolve aux_file_path
    configured_aux_dir = config.processing.storage.aux_data_dir
    if configured_aux_dir is not None:
        aux_file_path = configured_aux_dir
    else:
        aux_file_path = site_cfg.get_base_path()

    user_email = config.nasa_earthdata_acc_mail
    base = site_cfg.get_base_path()

    # Build a MatchedDirs for the date (pipeline reads .yyyydoy from it)
    canopy_dir = reference_dir = base
    for _name, rcfg in site_cfg.receivers.items():
        if rcfg.type == "canopy" and canopy_dir == base:
            canopy_dir = base / rcfg.directory
        elif rcfg.type == "reference" and reference_dir == base:
            reference_dir = base / rcfg.directory
    matched_dirs = MatchedDirs(
        canopy_data_dir=canopy_dir,
        reference_data_dir=reference_dir,
        yyyydoy=date_obj,
    )

    # 1. Create and load pipeline (downloads SP3 + CLK via FTP)
    #    RuntimeError propagates to Airflow if products not yet available
    pipeline = AuxDataPipeline.create_standard(
        matched_dirs=matched_dirs,
        aux_file_path=aux_file_path,
        agency=agency,
        product_type=product_type,
        user_email=user_email,
        keep_sids=keep_sids,
    )
    pipeline.load_all()

    ephem_ds = pipeline.get("ephemerides")
    clock_ds = pipeline.get("clock")

    # 2. Detect sampling interval from RINEX filename
    if sampling_interval_s is None:
        yydoy = date_obj.yydoy
        if yydoy is None:
            msg = f"Missing YYDOY for date {date_obj.to_str()}"
            raise ValueError(msg)
        for _name, rcfg in site_cfg.receivers.items():
            recv_dir = base / rcfg.directory / yydoy
            rnx_files = _get_rinex_files(recv_dir)
            if rnx_files:
                sampling_interval_s = parse_sampling_interval_from_filename(
                    rnx_files[0].name,
                )
                if sampling_interval_s is not None:
                    break
    if sampling_interval_s is None:
        sampling_interval_s = 30.0  # safe default

    # 3. Generate full-day target epoch grid
    day_start = np.datetime64(date_obj.date, "D")
    n_epochs = int(24 * 3600 / sampling_interval_s)
    target_epochs = day_start + np.arange(n_epochs) * np.timedelta64(
        int(sampling_interval_s),
        "s",
    )

    # 4. Hermite interpolation for ephemerides
    sp3_interp = Sp3InterpolationStrategy(
        config=Sp3Config(use_velocities=True, fallback_method="linear"),
    )
    ephem_interp = sp3_interp.interpolate(ephem_ds, target_epochs)
    ephem_interp.attrs["interpolator_config"] = sp3_interp.to_attrs()

    # 5. Piecewise-linear interpolation for clocks
    clock_interp = ClockInterpolationStrategy(
        config=ClockConfig(window_size=9, jump_threshold=1e-6),
    )
    clock_interp_ds = clock_interp.interpolate(clock_ds, target_epochs)
    clock_interp_ds.attrs["interpolator_config"] = clock_interp.to_attrs()

    # 6. Merge and write to Zarr
    aux_processed = xr.merge([ephem_interp, clock_interp_ds])
    aux_dir = config.processing.storage.get_aux_data_dir()
    aux_zarr_path = aux_dir / f"aux_{date_obj.to_str()}.zarr"

    if aux_zarr_path.exists():
        shutil.rmtree(aux_zarr_path)
    aux_processed.to_zarr(aux_zarr_path, mode="w")

    logger.info(
        "fetch_aux_data: wrote %s  dims=%s",
        aux_zarr_path,
        dict(aux_processed.sizes),
    )

    return {
        "site": site,
        "yyyydoy": date_obj.to_str(),
        "aux_zarr_path": str(aux_zarr_path),
        "sampling_interval_s": sampling_interval_s,
        "n_epochs": int(aux_processed.sizes["epoch"]),
        "n_sids": int(aux_processed.sizes["sid"]),
    }


# ---------------------------------------------------------------------------
# Task 3 — process_rinex
# ---------------------------------------------------------------------------


def process_rinex(
    site: str,
    yyyydoy: str,
    aux_zarr_path: str,
    receiver_files: dict | None = None,
) -> dict:
    """Read RINEX, augment with aux data, and write to Icechunk RINEX store.

    Parameters
    ----------
    site : str
        Research site name.
    yyyydoy : str
        Date in ``YYYYDDD`` format **or** Airflow ``ds`` (``YYYY-MM-DD``).
    aux_zarr_path : str
        Path to the pre-processed auxiliary Zarr store (from ``fetch_aux_data``).
    receiver_files : dict, optional
        ``{receiver_name: {"files": [str, ...], "count": N}}`` from
        ``check_rinex``.  When ``None``, files are discovered from disk.

    Returns
    -------
    dict
        ``{"site", "yyyydoy", "receivers_processed": [...], "files_written": N}``
    """
    from pydantic import ValidationError

    from canvod.readers.rinex.v3_04 import Rnxv3Header
    from canvod.store import GnssResearchSite
    from canvodpy.orchestrator.processor import preprocess_with_hermite_aux

    config = load_config()
    _cap_blas_threads(config.processing.processing.threads_per_worker or 1)
    site_cfg = config.sites.sites[site]
    date_obj = _resolve_date(yyyydoy)
    keep_vars = config.processing.processing.keep_rnx_vars
    keep_sids = config.sids.get_sids()
    base = site_cfg.get_base_path()
    aux_path = Path(aux_zarr_path)

    research_site = GnssResearchSite(site)
    receivers_processed: list[str] = []
    total_files_written = 0

    # Iterate over configured receivers
    for recv_name, rcfg in site_cfg.receivers.items():
        recv_type = rcfg.type
        yydoy = date_obj.yydoy
        if yydoy is None:
            msg = f"Missing YYDOY for date {date_obj.to_str()}"
            raise ValueError(msg)
        recv_dir = base / rcfg.directory / yydoy

        # Determine store groups for this receiver
        if recv_type == "canopy":
            store_groups = [recv_name]
        else:
            # Reference receivers write to {ref}_{canopy} store groups
            canopy_names = site_cfg.resolve_scs_from(recv_name)
            store_groups = [f"{recv_name}_{cn}" for cn in canopy_names]

        # Resolve RINEX files
        if receiver_files and recv_name in receiver_files:
            rnx_files = [Path(f) for f in receiver_files[recv_name]["files"]]
        else:
            rnx_files = _get_rinex_files(recv_dir)

        if not rnx_files:
            logger.warning("process_rinex: no files for %s, skipping", recv_name)
            continue

        # Compute receiver position from first RINEX header
        position: ECEFPosition | None = None
        for ff in rnx_files:
            try:
                header = Rnxv3Header.from_file(ff)
                position = ECEFPosition(
                    x=header.approx_position[0].magnitude,
                    y=header.approx_position[1].magnitude,
                    z=header.approx_position[2].magnitude,
                )
                break
            except (ValidationError, OSError, RuntimeError, ValueError) as exc:
                logger.warning("Header parse failed for %s: %s", ff.name, exc)

        if position is None:
            logger.error("No valid RINEX header for %s — skipping", recv_name)
            continue

        # Process each file sequentially (Airflow handles parallelism across sites)
        for rnx_file in rnx_files:
            try:
                _path, augmented_ds, _aux_ds, _sid_issues = preprocess_with_hermite_aux(
                    rnx_file=rnx_file,
                    keep_vars=keep_vars,
                    aux_zarr_path=aux_path,
                    receiver_position=position,
                    receiver_type=recv_name,
                    keep_sids=keep_sids,
                )
            except Exception:
                logger.exception("Failed to process %s", rnx_file.name)
                continue

            file_hash = augmented_ds.attrs.get("File Hash")
            time_start = augmented_ds.epoch.min().values
            time_end = augmented_ds.epoch.max().values

            # Write to each store group for this receiver
            for group in store_groups:
                # Early-exit pre-check (hash match + temporal overlap).
                # write_or_append_group(dedup=True) repeats this check as the
                # authoritative store-level gate, covering races and future
                # refactors that might bypass this pre-check.
                skip, reason = research_site.rinex_store.should_skip_file(
                    group_name=group,
                    file_hash=file_hash,
                    time_start=time_start,
                    time_end=time_end,
                )
                if skip:
                    logger.info(
                        "Skipping %s in group %s (reason=%s)",
                        rnx_file.name,
                        group,
                        reason,
                    )
                    continue

                research_site.rinex_store.write_or_append_group(
                    dataset=augmented_ds,
                    group_name=group,
                    commit_message=f"Airflow ingest {rnx_file.name}",
                    dedup=True,
                )
                total_files_written += 1

        receivers_processed.append(recv_name)
        logger.info(
            "process_rinex: %s processed %d files -> groups %s",
            recv_name,
            len(rnx_files),
            store_groups,
        )

    return {
        "site": site,
        "yyyydoy": date_obj.to_str(),
        "receivers_processed": receivers_processed,
        "files_written": total_files_written,
        "store_radial_distance": config.processing.processing.store_radial_distance,
    }


# ---------------------------------------------------------------------------
# Task 3b — process_sbf (broadcast or agency ephemeris)
# ---------------------------------------------------------------------------


def process_sbf(
    site: str,
    yyyydoy: str,
    receiver_files: dict | None = None,
    aux_zarr_path: str | None = None,
) -> dict:
    """Read SBF, augment with ephemeris, and write to Icechunk store.

    Supports two ephemeris modes controlled by ``aux_zarr_path``:

    * ``aux_zarr_path=None`` *(default)* — **broadcast geometry**: theta/phi
      come from SBF ``SatVisibility`` blocks embedded in the binary.  No
      external products needed; results are available same-day.
    * ``aux_zarr_path=<path>`` — **agency geometry**: theta/phi are computed
      from Hermite-interpolated SP3/CLK products (same path produced by
      ``fetch_aux_data``).  Geometry quality matches the RINEX pipeline at
      the cost of a 12-18 day product lag.

    In both modes SBF observables (SNR, Phase, Pseudorange, Doppler) and
    metadata (PVT, DOP, SatVisibility as ``sbf_obs``) are written.

    Parameters
    ----------
    site : str
        Research site name.
    yyyydoy : str
        Date in ``YYYYDDD`` format **or** Airflow ``ds`` (``YYYY-MM-DD``).
    receiver_files : dict, optional
        ``{receiver_name: {"files": [str, ...], "count": N}}`` from
        ``check_sbf``.  When ``None``, files are discovered from disk.
    aux_zarr_path : str or None, optional
        Path to the Hermite-interpolated auxiliary Zarr store produced by
        ``fetch_aux_data``.  When ``None``, broadcast geometry is used.

    Returns
    -------
    dict
        ``{"site", "yyyydoy", "receivers_processed", "files_written",
        "sbf_obs_written", "ephemeris_source"}``
    """
    from canvod.store import GnssResearchSite
    from canvodpy.orchestrator.processor import preprocess_with_hermite_aux

    config = load_config()
    _cap_blas_threads(config.processing.processing.threads_per_worker or 1)
    site_cfg = config.sites.sites[site]
    date_obj = _resolve_date(yyyydoy)
    keep_vars = config.processing.processing.keep_rnx_vars
    keep_sids = config.sids.get_sids()
    base = site_cfg.get_base_path()

    use_broadcast = aux_zarr_path is None
    # preprocess_with_hermite_aux always requires an aux path argument;
    # when using broadcast geometry the path is unused internally.
    effective_aux_path = Path("/dev/null") if use_broadcast else Path(aux_zarr_path)

    research_site = GnssResearchSite(site)
    receivers_processed: list[str] = []
    total_files_written = 0
    sbf_obs_written = False

    for recv_name, rcfg in site_cfg.receivers.items():
        recv_type = rcfg.type

        # Determine store groups
        if recv_type == "canopy":
            store_groups = [recv_name]
        else:
            canopy_names = site_cfg.resolve_scs_from(recv_name)
            store_groups = [f"{recv_name}_{cn}" for cn in canopy_names]

        # Resolve SBF files
        if receiver_files and recv_name in receiver_files:
            sbf_files = [Path(f) for f in receiver_files[recv_name]["files"]]
        else:
            files, _ = _discover_files_for_date(
                site_cfg, rcfg, recv_name, date_obj, base
            )
            sbf_files = [f for f in files if f.suffix.lower() == ".sbf"]

        if not sbf_files:
            logger.warning("process_sbf: no SBF files for %s, skipping", recv_name)
            continue

        # Receiver position from first SBF file's metadata
        position: ECEFPosition | None = None
        for ff in sbf_files:
            try:
                from canvodpy.factories import ReaderFactory

                reader = ReaderFactory.create("sbf", fpath=ff)
                ds_tmp = reader.to_ds(keep_data_vars=None, write_global_attrs=True)
                position = ECEFPosition.from_ds_metadata(ds_tmp)
                break
            except Exception as exc:
                logger.warning("SBF position extract failed for %s: %s", ff.name, exc)

        if position is None:
            logger.error("No valid position for %s — skipping", recv_name)
            continue

        # Process each SBF file
        sbf_obs_parts: list[xr.Dataset] = []
        for sbf_file in sbf_files:
            try:
                _path, augmented_ds, aux_datasets, _sid_issues = (
                    preprocess_with_hermite_aux(
                        rnx_file=sbf_file,
                        keep_vars=keep_vars,
                        aux_zarr_path=effective_aux_path,
                        receiver_position=position,
                        receiver_type=recv_name,
                        keep_sids=keep_sids,
                        reader_name="sbf",
                        use_sbf_geometry=use_broadcast,
                    )
                )
            except Exception:
                logger.exception("Failed to process SBF %s", sbf_file.name)
                continue

            # Collect sbf_obs metadata for later writing
            if "sbf_obs" in aux_datasets:
                sbf_obs_parts.append(aux_datasets["sbf_obs"])

            file_hash = augmented_ds.attrs.get("File Hash")
            time_start = augmented_ds.epoch.min().values
            time_end = augmented_ds.epoch.max().values

            # Write to each store group
            for group in store_groups:
                # Early-exit pre-check (hash match + temporal overlap).
                # write_or_append_group(dedup=True) repeats this check as the
                # authoritative store-level gate, covering races and future
                # refactors that might bypass this pre-check.
                skip, reason = research_site.rinex_store.should_skip_file(
                    group_name=group,
                    file_hash=file_hash,
                    time_start=time_start,
                    time_end=time_end,
                )
                if skip:
                    logger.info(
                        "Skipping %s in group %s (reason=%s)",
                        sbf_file.name,
                        group,
                        reason,
                    )
                    continue

                research_site.rinex_store.write_or_append_group(
                    dataset=augmented_ds,
                    group_name=group,
                    commit_message=f"Airflow SBF ingest {sbf_file.name}",
                    dedup=True,
                )
                total_files_written += 1

        # Write sbf_obs metadata per receiver — no in-memory concat
        if sbf_obs_parts:
            try:
                rinex_store_any = cast(Any, research_site.rinex_store)
                rinex_store_any.append_metadata_datasets(
                    sbf_obs_parts, recv_name, "sbf_obs"
                )
                sbf_obs_written = True
                logger.info(
                    "process_sbf: wrote sbf_obs for %s (%d parts)",
                    recv_name,
                    len(sbf_obs_parts),
                )
            except Exception:
                logger.exception("Failed to write sbf_obs for %s", recv_name)

        receivers_processed.append(recv_name)
        logger.info(
            "process_sbf: %s processed %d files -> groups %s",
            recv_name,
            len(sbf_files),
            store_groups,
        )

    return {
        "site": site,
        "yyyydoy": date_obj.to_str(),
        "receivers_processed": receivers_processed,
        "files_written": total_files_written,
        "sbf_obs_written": sbf_obs_written,
        "ephemeris_source": "broadcast" if use_broadcast else "agency",
        "store_radial_distance": config.processing.processing.store_radial_distance,
        "store_sbf_raw_observables": config.processing.processing.store_sbf_raw_observables,
    }


# ---------------------------------------------------------------------------
# Task 3c — validate_ingest (quality gate between ingest and VOD)
# ---------------------------------------------------------------------------


def validate_ingest(site: str, yyyydoy: str) -> dict:
    """Spot-check stored data before VOD computation.

    Reads back ingested data from the Icechunk store and verifies basic
    physical plausibility. Catches corrupt writes, coordinate transform
    bugs, or SID mismatches before they propagate into VOD.

    Parameters
    ----------
    site : str
        Research site name.
    yyyydoy : str
        Date in ``YYYYDDD`` format **or** Airflow ``ds`` (``YYYY-MM-DD``).

    Returns
    -------
    dict
        ``{"site", "yyyydoy", "valid": bool, "checks": {...}}``

    Raises
    ------
    RuntimeError
        If any check fails (blocks VOD computation).
    """
    from canvod.store import GnssResearchSite

    config = load_config()
    site_cfg = config.sites.sites[site]
    date_obj = _resolve_date(yyyydoy)

    research_site = GnssResearchSite(site)
    checks: dict[str, dict] = {}
    all_valid = True

    import datetime as _dt

    assert date_obj.date is not None
    day_start = _dt.datetime.combine(date_obj.date, _dt.time.min)
    day_end = day_start + _dt.timedelta(days=1)
    time_range = (day_start, day_end)

    for recv_name, rcfg in site_cfg.receivers.items():
        recv_checks: dict[str, str] = {}

        try:
            ds = research_site.read_receiver_data(
                receiver_name=recv_name,
                time_range=time_range,
            )
        except Exception:
            recv_checks["data_loaded"] = "SKIP: no data for this date"
            checks[recv_name] = recv_checks
            continue

        n_epochs = ds.sizes.get("epoch", 0)
        n_sids = ds.sizes.get("sid", 0)

        # Check 1: non-empty
        if n_epochs == 0 or n_sids == 0:
            recv_checks["non_empty"] = f"FAIL: {n_epochs} epochs, {n_sids} sids"
            all_valid = False
        else:
            recv_checks["non_empty"] = f"OK: {n_epochs} epochs, {n_sids} sids"

        # Check 2: SNR in plausible range (0-70 dB-Hz)
        for snr_var in ["cn0", "SNR", "S1C", "S1W", "S2C", "S2W"]:
            if snr_var in ds.data_vars:
                snr_vals = ds[snr_var].values[np.isfinite(ds[snr_var].values)]
                if len(snr_vals) > 0:
                    snr_min, snr_max = float(snr_vals.min()), float(snr_vals.max())
                    if snr_min < 0 or snr_max > 70:
                        recv_checks["snr_range"] = (
                            f"FAIL: {snr_var} range [{snr_min:.1f}, {snr_max:.1f}]"
                        )
                        all_valid = False
                    else:
                        recv_checks["snr_range"] = (
                            f"OK: {snr_var} [{snr_min:.1f}, {snr_max:.1f}]"
                        )
                break

        # Check 3: theta (polar angle) in valid range [0, π/2]
        if "theta" in ds.coords:
            theta = ds.coords["theta"].values[np.isfinite(ds.coords["theta"].values)]
            if len(theta) > 0:
                t_min, t_max = float(theta.min()), float(theta.max())
                if t_min < -0.01 or t_max > np.pi / 2 + 0.01:
                    recv_checks["theta_range"] = (
                        f"FAIL: theta [{t_min:.4f}, {t_max:.4f}] rad"
                    )
                    all_valid = False
                else:
                    recv_checks["theta_range"] = (
                        f"OK: theta [{t_min:.4f}, {t_max:.4f}] rad"
                    )

        # Check 4: phi (azimuth) in valid range [0, 2π]
        if "phi" in ds.coords:
            phi = ds.coords["phi"].values[np.isfinite(ds.coords["phi"].values)]
            if len(phi) > 0:
                p_min, p_max = float(phi.min()), float(phi.max())
                if p_min < -0.01 or p_max > 2 * np.pi + 0.01:
                    recv_checks["phi_range"] = (
                        f"FAIL: phi [{p_min:.4f}, {p_max:.4f}] rad"
                    )
                    all_valid = False
                else:
                    recv_checks["phi_range"] = f"OK: phi [{p_min:.4f}, {p_max:.4f}] rad"

        checks[recv_name] = recv_checks

    result = {
        "site": site,
        "yyyydoy": date_obj.to_str(),
        "valid": all_valid,
        "checks": checks,
    }

    if not all_valid:
        failed = {
            r: {k: v for k, v in c.items() if v.startswith("FAIL")}
            for r, c in checks.items()
            if any(v.startswith("FAIL") for v in c.values())
        }
        msg = f"Ingest validation failed for {site} {date_obj.to_str()}: {failed}"
        logger.error(msg)
        raise RuntimeError(msg)

    logger.info("validate_ingest: %s %s — all checks passed", site, date_obj.to_str())
    return result


# ---------------------------------------------------------------------------
# Task 4 — calculate_vod
# ---------------------------------------------------------------------------


def calculate_vod(site: str, yyyydoy: str) -> dict:
    """Compute VOD for all active analysis pairs and write to the VOD store.

    Parameters
    ----------
    site : str
        Research site name.
    yyyydoy : str
        Date in ``YYYYDDD`` format **or** Airflow ``ds`` (``YYYY-MM-DD``).

    Returns
    -------
    dict
        ``{"site", "yyyydoy", "analyses": {name: {"mean_vod", "std_vod",
        "n_epochs"}}}``
    """
    from canvod.store import GnssResearchSite

    date_obj = _resolve_date(yyyydoy)

    research_site = GnssResearchSite(site)

    # Build time range for this day
    day_date = date_obj.date
    if day_date is None:
        msg = f"Missing calendar date for {date_obj.to_str()}"
        raise ValueError(msg)
    start_time = datetime.datetime.combine(day_date, datetime.time.min)
    end_time = datetime.datetime.combine(day_date, datetime.time.max)
    time_range = (start_time, end_time)

    analyses_result: dict[str, dict] = {}
    for analysis_name in research_site.active_vod_analyses:
        logger.info("calculate_vod: running %s for %s", analysis_name, site)

        vod_ds = research_site.calculate_vod(
            analysis_name=analysis_name,
            time_range=time_range,
        )

        research_site.store_vod_analysis(
            vod_dataset=vod_ds,
            analysis_name=analysis_name,
            commit_message=f"Airflow VOD {analysis_name} {date_obj.to_str()}",
        )

        # Collect stats — TauOmegaZerothOrder returns variable "VOD"
        tau_values = vod_ds["VOD"].values if "VOD" in vod_ds else None
        analyses_result[analysis_name] = {
            "mean_vod": float(np.nanmean(tau_values))
            if tau_values is not None
            else None,
            "std_vod": float(np.nanstd(tau_values)) if tau_values is not None else None,
            "n_epochs": int(vod_ds.sizes.get("epoch", 0)),
        }

    return {
        "site": site,
        "yyyydoy": date_obj.to_str(),
        "analyses": analyses_result,
    }


# ---------------------------------------------------------------------------
# Task 5 — cleanup (runs regardless of upstream outcome)
# ---------------------------------------------------------------------------


def cleanup(site: str, yyyydoy: str) -> dict:
    """Remove temporary files created during pipeline execution.

    Cleans up the aux Zarr store from ``fetch_aux_data`` and any other
    temporary artifacts. Designed to run with ``TriggerRule.ALL_DONE``
    so it executes even if upstream tasks fail.

    Parameters
    ----------
    site : str
        Research site name.
    yyyydoy : str
        Date in ``YYYYDDD`` format **or** Airflow ``ds`` (``YYYY-MM-DD``).

    Returns
    -------
    dict
        ``{"site", "yyyydoy", "cleaned": [...]}``
    """
    date_obj = _resolve_date(yyyydoy)
    cleaned: list[str] = []

    # Clean up aux Zarr temp files
    try:
        config = load_config()
        aux_dir = config.processing.storage.get_aux_data_dir()
        aux_zarr_path = aux_dir / f"aux_{date_obj.to_str()}.zarr"
        if aux_zarr_path.exists():
            shutil.rmtree(aux_zarr_path)
            cleaned.append(str(aux_zarr_path))
            logger.info("cleanup: removed %s", aux_zarr_path)
    except Exception:
        logger.exception("cleanup: failed to remove aux Zarr")

    return {
        "site": site,
        "yyyydoy": date_obj.to_str(),
        "cleaned": cleaned,
    }
