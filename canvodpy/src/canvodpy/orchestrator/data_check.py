"""Check a site's receiver data before processing it.

Used by ``canvodpy config validate``. It applies the same file discovery as
``canvodpy run`` (:mod:`canvodpy.orchestrator.discovery`), so a site that
passes the check is processed with exactly the files reported here, and
every error reported here would also stop a run. In addition it reports
what a run passes over without a message: files that are not recognized,
and files whose named sampling interval differs from that of their data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from canvodpy.orchestrator.discovery import (
    DiscoveredFile,
    DiscoveryError,
    check_receivers,
    clear_discovery_cache,
    detect_reader_format,
    discover_files,
    receiver_days,
    scan_directory,
)


@dataclass
class ReceiverReport:
    """What a run would process for one receiver, and what is wrong.

    Attributes
    ----------
    name : str
        Receiver name in the site configuration.
    directory : Path
        The receiver's data directory.
    reader_format : str
        Configured reader format (``"auto"`` resolved from the files).
    recipe : str | None
        Naming recipe, if configured.
    days : list[str]
        Days (``YYYYDOY``) with files to process, sorted.
    files : int
        Number of files a run would process.
    unrecognized : list[Path]
        Files that are never processed: neither the recipe nor the naming
        convention recognizes them, or they are of another reader format.
    errors : list[str]
        Problems that stop a run or make its results wrong.
    warnings : list[str]
        Problems worth a look that do not stop a run.
    """

    name: str
    directory: Path
    reader_format: str
    recipe: str | None
    days: list[str] = field(default_factory=list)
    files: int = 0
    unrecognized: list[Path] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


@dataclass
class SiteReport:
    """Result of :func:`check_site_data` for one site.

    Attributes
    ----------
    site : str
        Site name.
    receivers : dict[str, ReceiverReport]
        One report per configured receiver.
    errors : list[str]
        Problems concerning several receivers (e.g. two receivers with the
        same identity).
    """

    site: str
    receivers: dict[str, ReceiverReport] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """``True`` if nothing would stop a run or make its results wrong."""
        return not self.errors and not any(r.errors for r in self.receivers.values())


def data_sampling_seconds(
    path: Path, reader_format: str, **reader_options: Any
) -> float:
    """Median interval between the epochs of a GNSS data file, in seconds.

    ``reader_options`` are passed to the reader, as a run passes them.
    """
    from canvodpy.factories import ReaderFactory

    reader = ReaderFactory.create(reader_format, fpath=path, **reader_options)
    epochs = reader.to_ds(keep_data_vars=[]).epoch.values
    if len(epochs) < 2:
        msg = f"{path.name} has fewer than two epochs"
        raise ValueError(msg)
    return float(np.median(np.diff(epochs)) / np.timedelta64(1, "s"))


def _check_sampling(
    report: ReceiverReport,
    file: DiscoveredFile,
    reader_options: dict[str, Any],
) -> None:
    from canvod.preflight.convention import CanVODFilename

    named = CanVODFilename.from_filename(file.canonical_name)
    named_s = named.sampling_interval.total_seconds()
    try:
        data_s = data_sampling_seconds(
            file.path, report.reader_format, **reader_options
        )
    except Exception as exc:
        report.warnings.append(
            f"Could not read {file.path} to check its sampling: {exc}"
        )
        return
    if not np.isclose(data_s, named_s):
        source = f"recipe '{report.recipe}'" if report.recipe else "file name"
        report.errors.append(
            f"{file.path} is named with sampling {named.sampling} by its "
            f"{source}, but its data are sampled every {data_s:g} s."
        )


def check_receiver_data(
    name: str,
    cfg: dict[str, Any],
    base_path: Path,
    check_sampling: bool = True,
    reader_options: dict[str, Any] | None = None,
) -> ReceiverReport:
    """Check one receiver's directory as a run would read it.

    Parameters
    ----------
    name : str
        Receiver name in the site configuration.
    cfg : dict
        Receiver configuration (``directory``, ``reader_format``, ``recipe``).
    base_path : Path
        The site's data root, which receiver directories are relative to.
    check_sampling : bool
        Read the first file of the first and of the last day and compare
        the sampling interval of the data with the one in the file's
        canonical name.
    reader_options : dict | None
        Options passed to the reader for the sampling check.
    """
    directory = base_path / cfg["directory"]
    configured_format = cfg.get("reader_format") or "auto"
    recipe = cfg.get("recipe")
    report = ReceiverReport(name, directory, configured_format, recipe)

    if not directory.is_dir():
        report.errors.append(f"Directory not found: {directory}")
        return report
    try:
        scan = scan_directory(directory, recipe)
        reader_format = None if configured_format == "auto" else configured_format
        days = receiver_days(name, directory, reader_format, recipe)
    except DiscoveryError as exc:
        report.errors.append(str(exc))
        return report

    files_of_day = {day.yyyydoy: discover_files(day, reader_format) for day in days}
    report.days = sorted(files_of_day)
    report.files = sum(len(files) for files in files_of_day.values())
    read = {f.path for files in files_of_day.values() for f in files}
    other_format = sorted(
        f.path for files in scan.days.values() for f in files if f.path not in read
    )
    report.unrecognized = list(scan.unrecognized) + other_format

    if configured_format == "auto" and files_of_day:
        report.reader_format = detect_reader_format(
            [f for files in files_of_day.values() for f in files]
        )

    if not report.files:
        if report.unrecognized:
            what = (
                f"its recipe '{recipe}'"
                if recipe
                else f"the canVOD naming convention for reader format "
                f"'{configured_format}'"
            )
            report.errors.append(
                f"{directory} holds {len(report.unrecognized)} file(s), but none "
                f"of them is recognized by {what}, so nothing would be processed."
            )
        else:
            report.warnings.append(f"{directory} holds no files.")
        return report

    if report.unrecognized:
        report.warnings.append(
            f"{len(report.unrecognized)} file(s) in {directory} are not processed."
        )
    if check_sampling:
        for day in dict.fromkeys((report.days[0], report.days[-1])):
            _check_sampling(report, files_of_day[day][0], reader_options or {})
    return report


def check_site_data(
    site: str, config: Any = None, check_sampling: bool = True
) -> SiteReport:
    """Check the data of every receiver of a site as a run would read them.

    Parameters
    ----------
    site : str
        Site name in the configuration.
    config : CanvodConfig | None
        Loaded configuration; ``None`` loads the active one.
    check_sampling : bool
        See :func:`check_receiver_data`.

    Returns
    -------
    SiteReport
        ``report.ok`` is ``False`` if a run would stop or produce wrong
        results.
    """
    if config is None:
        from canvod.config import load_config

        config = load_config()
    site_config = config.sites.sites[site]
    reader_options = {
        "aggregate_glonass_fdma": config.processing.params.aggregate_glonass_fdma
    }
    base_path = site_config.get_base_path()
    receivers = {name: cfg.model_dump() for name, cfg in site_config.receivers.items()}
    clear_discovery_cache()
    report = SiteReport(site)
    try:
        check_receivers(receivers, base_path)
    except DiscoveryError as exc:
        report.errors.append(str(exc))
    for name, cfg in receivers.items():
        report.receivers[name] = check_receiver_data(
            name, cfg, base_path, check_sampling, reader_options
        )
    return report
