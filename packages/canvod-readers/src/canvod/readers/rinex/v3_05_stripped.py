"""RINEX v3.05 stripped (SNR-only) observation reader.

Reads RINEX v3 files that have been stripped down to contain only signal
strength (S*) observables. Inherits from :class:`Rnxv3Obs` for header parsing,
epoch iteration, and signal-ID mapping; overrides the dataset construction
path to allocate a single SNR array (no Pseudorange/Phase/Doppler/LLI/SSI),
which is significantly cheaper for the multi-hundred-MB daily files this
format typically produces.

Stripped files are recognised by their ``SYS / # / OBS TYPES`` records — every
observation code starts with ``S``. Files containing any non-SNR observable
are rejected with :class:`StrippedRinexError` at load time, since the full
:class:`Rnxv3Obs` reader is the right tool for those.
"""

from pathlib import Path
from typing import Self, cast

import numpy as np
import xarray as xr
from pydantic import model_validator

from canvod.readers.base import validate_dataset
from canvod.readers.gnss_specs.constants import UREG
from canvod.readers.gnss_specs.metadata import (
    CN0_METADATA,
    COORDS_METADATA,
    DTYPES,
    SNR_METADATA,
)
from canvod.readers.rinex.v3_04 import (
    _EPOCH_RE,
    Rnxv3Obs,
    _parse_obs_fast,
    _str_to_object,
)


class StrippedRinexError(ValueError):
    """Raised when a file is not a valid SNR-only stripped RINEX."""


class Rnxv3StrippedObs(Rnxv3Obs):
    """RINEX v3 reader for SNR-only stripped observation files.

    Stripped files contain only signal-strength (``S*``) observables — no
    pseudorange, carrier phase, or Doppler. This reader enforces that contract
    at load time and builds a Dataset with a single ``SNR`` data variable,
    skipping the auxiliary arrays that the full :class:`Rnxv3Obs` reader
    allocates.
    """

    @property
    def source_format(self) -> str:
        return "rinex3_stripped"

    @model_validator(mode="after")
    def _validate_snr_only(self) -> Self:
        bad: dict[str, list[str]] = {}
        for system, codes in self._header.obs_codes_per_system.items():
            non_snr = [c for c in codes if not c.startswith("S")]
            if non_snr:
                bad[system] = non_snr
        if bad:
            raise StrippedRinexError(
                f"File {self.fpath.name} is not a stripped RINEX — found "
                f"non-SNR observables {bad}. Use Rnxv3Obs for full files."
            )
        return self

    def _create_dataset_single_pass(self) -> xr.Dataset:
        lines = self._load_file()
        epoch_batches = self.get_epoch_record_batches()
        n_epochs = len(epoch_batches)

        sorted_sids, sid_properties = self._precompute_sids_from_header()
        n_sids = len(sorted_sids)
        sid_to_idx = {sid: i for i, sid in enumerate(sorted_sids)}

        timestamps = np.empty(n_epochs, dtype="datetime64[ns]")
        snr = np.full((n_epochs, n_sids), np.nan, dtype=DTYPES["SNR"])

        mapper = self._signal_mapper
        system_obs_lut: dict[str, list[str]] = {}
        for system, obs_codes in self._header.obs_codes_per_system.items():
            suffixes: list[str] = []
            for obs_code in obs_codes:
                if len(obs_code) < 3:
                    suffixes.append("")
                    continue
                band_num = obs_code[1]
                code_char = obs_code[2]
                band_name = mapper.SYSTEM_BANDS.get(system, {}).get(
                    band_num, f"UnknownBand{band_num}"
                )
                suffixes.append("|" + band_name + "|" + code_char)
            system_obs_lut[system] = suffixes

        valid_mask = np.ones(n_epochs, dtype=bool)
        for t_idx, (start, end) in enumerate(epoch_batches):
            epoch_line = lines[start]
            m = _EPOCH_RE.match(epoch_line)
            if m is None:
                valid_mask[t_idx] = False
                continue

            year, month, day = int(m[1]), int(m[2]), int(m[3])
            hour, minute = int(m[4]), int(m[5])
            seconds = float(m[6])
            sec_int = int(seconds)
            usec = int((seconds - sec_int) * 1_000_000)
            ts = np.datetime64(
                f"{year:04d}-{month:02d}-{day:02d}"
                f"T{hour:02d}:{minute:02d}:{sec_int:02d}",
                "ns",
            )
            ts += np.timedelta64(usec, "us")
            timestamps[t_idx] = ts

            for line_idx in range(start + 1, end):
                sat_line = lines[line_idx]
                if len(sat_line) < 3:
                    continue
                sv = sat_line[:3].strip()
                if not sv:
                    continue
                system = sv[0]
                lut_list = system_obs_lut.get(system)
                if lut_list is None:
                    continue

                data_part = sat_line[3:]
                data_part_len = len(data_part)
                for i, sid_suffix in enumerate(lut_list):
                    if not sid_suffix:
                        continue
                    col_start = i * 16
                    if col_start >= data_part_len:
                        break
                    sid_key = sv + sid_suffix
                    s_idx = sid_to_idx.get(sid_key)
                    if s_idx is None:
                        continue
                    col_end = col_start + 16
                    slice_text = data_part[col_start:col_end]
                    value, _lli, _ssi = _parse_obs_fast(slice_text)
                    if value is None or value == 0:
                        continue
                    snr[t_idx, s_idx] = value

        if not valid_mask.all():
            timestamps = timestamps[valid_mask]
            snr = snr[valid_mask]

        sv_list = np.array(
            [sid_properties[sid]["sv"] for sid in sorted_sids], dtype=object
        )
        constellation_list = np.array(
            [sid_properties[sid]["system"] for sid in sorted_sids], dtype=object
        )
        band_list = np.array(
            [sid_properties[sid]["band"] for sid in sorted_sids], dtype=object
        )
        code_list = np.array(
            [sid_properties[sid]["code"] for sid in sorted_sids], dtype=object
        )
        freq_center_list = [sid_properties[sid]["freq_center"] for sid in sorted_sids]
        freq_min_list = [sid_properties[sid]["freq_min"] for sid in sorted_sids]
        freq_max_list = [sid_properties[sid]["freq_max"] for sid in sorted_sids]

        signal_id_coord = xr.DataArray(
            np.array(sorted_sids, dtype=object),
            dims=["sid"],
            attrs=COORDS_METADATA["sid"],
        )
        coords = {
            "epoch": ("epoch", timestamps, COORDS_METADATA["epoch"]),
            "sid": signal_id_coord,
            "sv": ("sid", sv_list, COORDS_METADATA["sv"]),
            "system": ("sid", constellation_list, COORDS_METADATA["system"]),
            "band": ("sid", band_list, COORDS_METADATA["band"]),
            "code": ("sid", code_list, COORDS_METADATA["code"]),
            "freq_center": (
                "sid",
                np.asarray(freq_center_list, dtype=DTYPES["freq_center"]),
                COORDS_METADATA["freq_center"],
            ),
            "freq_min": (
                "sid",
                np.asarray(freq_min_list, dtype=DTYPES["freq_min"]),
                COORDS_METADATA["freq_min"],
            ),
            "freq_max": (
                "sid",
                np.asarray(freq_max_list, dtype=DTYPES["freq_max"]),
                COORDS_METADATA["freq_max"],
            ),
        }

        snr_meta = (
            CN0_METADATA
            if self._header.signal_strength_unit == UREG.dBHz
            else SNR_METADATA
        )

        ds = xr.Dataset(
            data_vars={"SNR": (["epoch", "sid"], snr, snr_meta)},
            coords=coords,
            attrs={**self._build_attrs()},
        )

        if self.apply_overlap_filter:
            ds = self.filter_by_overlapping_groups(ds, self.overlap_preferences)

        return ds

    def to_ds(
        self,
        keep_data_vars: list[str] | None = None,
        **kwargs: object,
    ) -> xr.Dataset:
        outname = cast(Path | str | None, kwargs.pop("outname", None))
        write_global_attrs = bool(kwargs.pop("write_global_attrs", False))
        pad_global_sid = bool(kwargs.pop("pad_global_sid", True))
        strip_fillval = bool(kwargs.pop("strip_fillval", True))
        keep_sids = cast(list[str] | None, kwargs.pop("keep_sids", None))

        if keep_data_vars is None:
            keep_data_vars = ["SNR"]

        ds = self._create_dataset_single_pass()

        for var in list(ds.data_vars):
            if var not in keep_data_vars:
                ds = ds.drop_vars([var])

        if pad_global_sid:
            from canvod.auxiliary.preprocessing import pad_to_global_sid

            ds = pad_to_global_sid(ds, keep_sids=keep_sids)

        if strip_fillval:
            from canvod.auxiliary.preprocessing import strip_fillvalue

            ds = strip_fillvalue(ds)

        if write_global_attrs:
            ds.attrs.update(self._create_comprehensive_attrs())

        ds.attrs.update(self._build_attrs())

        if outname:
            from canvod.utils.config import load_config as _load_config

            comp = _load_config().processing.compression
            encoding = {
                var: {"zlib": comp.zlib, "complevel": comp.complevel}
                for var in ds.data_vars
            }
            ds.to_netcdf(str(outname), encoding=encoding)

        ds = _str_to_object(ds)
        validate_dataset(ds, required_vars=keep_data_vars)
        return ds
