# CLK Usage & Aux/Augmentation Caching

Two related findings from investigating why a batch run over several days
still re-downloads/re-augments aux data even when SP3/CLK files and the
augmented store already exist locally.

---

## Finding 1: CLK is downloaded, parsed, interpolated — and never used

**Confirmed: the CLK product has zero effect on VOD output.** It's fetched
and processed on every run for no benefit.

Trace of the CLK data path:

1. `fetch_aux_data` (`canvodpy/src/canvodpy/workflows/tasks.py:709-761`) and
   `AgencyEphemerisProvider.preprocess_day()`
   (`packages/canvod-auxiliary/src/canvod/auxiliary/ephemeris/provider.py:122-217`)
   download SP3 **and** CLK via FTP (CDDIS primary, ESA fallback), then
   Hermite-interpolate SP3 and piecewise-linear-interpolate CLK, merging
   both into the per-day aux Zarr store.
2. `augment_dataset()` (`provider.py:274-290`) computes `theta`/`phi` from
   SP3 `X, Y, Z` only. The clock series is merely assigned onto the output
   dataset as an unused `clock` data var if present.
3. `ClockCorrectionAugmentation.augment()`
   (`packages/canvod-auxiliary/src/canvod/auxiliary/augmentation.py:254-275`)
   is an explicit placeholder — logs a message and returns the dataset
   **unchanged**.
4. Grepped `canvod-vod/calculator.py`, `canvodpy/vod_computer.py`,
   `canvodpy/functional.py` — zero references to `clock`. The VOD formula
   (`VOD = -ln(T)·cos(θ)`) only needs `θ`, which comes from SP3 positions.

### Recommendation

Make CLK fetch/interpolation opt-in rather than always-on:

- `AuxDataConfig` (`packages/canvod-utils/src/canvod/utils/config/models.py:91-103`)
  gains `fetch_clock: bool = False` (or similar).
- `pipeline.register("clock", clk_file, required=True)` in
  `packages/canvod-auxiliary/src/canvod/auxiliary/pipeline.py:436-445` becomes
  conditional on the flag.
- Skip the clock-interpolation block in `tasks.py:756-761` when disabled.
- Keep the parser/interpolator code in place (don't delete) — a future
  pseudorange-based clock correction could reuse it.

---

## Finding 2: no skip-if-already-augmented check anywhere

Batch runs over N days currently redo full ephemeris download +
interpolation + augmentation every time, even when nothing changed since
the last run.

- `fetch_aux_data` (`tasks.py:645-785`) always calls `pipeline.load_all()`
  (line 718, no existence check first) and always deletes + rewrites the
  aux Zarr (`tasks.py:768-770`: `shutil.rmtree` then `to_zarr(mode="w")`).
- `AgencyEphemerisProvider.preprocess_day()` has the same pattern
  (`provider.py:164-166`), with the comment *"Always reprocess (cheap;
  avoids stale caches)"* — true for a single day, not true for a
  multi-day batch re-run.
- The three-layer dedup in `processor.py`
  (`_check_existing_with_temporal_overlap`, ~L1665-1743) only guards the
  **final Icechunk write**. It does nothing to prevent the expensive
  augmentation compute from re-running.

### The fingerprint mechanism already exists — just isn't wired to a skip check

`canvod-store-metadata` already computes exactly the kind of settings
fingerprint needed to answer "was this store produced with the ephemeris
settings I need for this run?":

- `collect_config_snapshot()`
  (`packages/canvod-store-metadata/src/canvod/store_metadata/collectors.py:166-205`)
  hashes the `processing`, `preprocessing`, `aux_data`, `compression`,
  `icechunk`, `sids` config sections (SHA256) into `ConfigSnapshot.config_hash`
  (`schema.py:160`).
- The `aux_data` section is `AuxDataConfig` — just `agency` + `product_type`
  (models.py:91-103) — exactly the ephemeris-source settings that matter
  here.
- This snapshot is written into the store's root Zarr attr `canvod_metadata`
  on ingest (STEP 5b in `processor.py`), and is readable cheaply via
  `metadata_exists()` / `read_metadata()` without opening the full dataset.

### Recommendation

1. Before running `fetch_aux_data` / augmentation for a given site+date,
   check if the target store already covers that date (temporal check
   already exists in `processor.py`).
2. If it does, `read_metadata(store)` and pull `config_snapshot.aux_data`.
3. Compute the current run's `aux_data` config the same way and compare.
   Match → skip download, interpolation, and augmentation entirely for
   that day; read straight from the store.
4. Mismatch (e.g. `agency: COD` → `ESA` changed) → fall through and
   re-augment. This keeps the skip graceful — no silent staleness when
   settings actually change.
5. Consider hashing just the `aux_data` sub-section for this check (finer
   grained than the full `config_hash`, which would also invalidate on
   unrelated `compression`/`icechunk` changes that don't affect
   augmentation).

### Open question

Should the per-day aux Zarr cache (`aux_{date}.zarr`, separate from the
final Icechunk store) also carry a config-hash attr, so a batch re-run can
skip the SP3/CLK download + interpolation step even before checking the
final store? This would help when the final store write is skipped for
unrelated reasons (e.g. temporal overlap) but aux data was already fetched
in a prior attempt.

---

## Status

Design only — not implemented. Depends on user confirming whether both
fixes (CLK opt-out, augmentation skip check) should be scoped together or
separately.
