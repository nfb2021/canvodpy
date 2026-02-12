# Naming Refactor Plan

Audit date: 2026-02-07
Branch: to be created from `main` after current work is merged.

---

## Critical: Public API renames (require deprecation aliases)

| Current name | Package | Problem | Suggested name |
|---|---|---|---|
| `MyIcechunkStore` | canvod-store | `My` prefix (tutorial artifact) | `IcechunkStore` |
| `add_cell_ids_to_ds_fast` | canvod-grids | `_fast` with no slow counterpart | `assign_cell_ids` |
| `add_cell_ids_to_vod_fast` | canvod-grids | `_fast` suffix | `assign_cell_ids_to_vod` |
| `prep_aux_ds` | canvod-auxiliary | triple abbreviation | `prepare_auxiliary` |
| `preprocess_aux_for_interpolation` | canvod-auxiliary | overly long (borderline) | `preprocess_auxiliary` |

Each public rename needs a backward-compatible alias in `__init__.py` with a deprecation warning for at least one minor release.

---

## High: Internal but widely referenced

### Speed/algorithm qualifiers

| Current name | File | Problem | Suggested name |
|---|---|---|---|
| `astropy_hampel_vectorized_fast` | `canvod-grids/grids/analysis/sigma_clip_filter.py:212` | library name + `_fast` | `hampel_filter_vectorized` |
| `astropy_hampel_ultra_fast` | `canvod-grids/grids/analysis/sigma_clip_filter.py:399` | library + superlative speed | `sigma_clip_filter` |
| `_compute_spherical_coords_fast` | `canvodpy/orchestrator/processor.py:246` | no slow counterpart | `_compute_spherical_coords` |
| `_append_to_icechunk_slow` | `canvodpy/orchestrator/processor.py:914` | speed qualifier | `_append_to_icechunk_sequential` |
| `_append_to_icechunk_coord_distrbtd` | `canvodpy/orchestrator/processor.py:2625` | misspelling | `_append_to_icechunk_distributed` |
| `_append_to_icechunk_native_context_manager` | `canvodpy/orchestrator/processor.py:2502` | 6 words | `_append_to_icechunk_transactional` |

### Version/magic-number suffixes

| Current name | File | Problem | Suggested name |
|---|---|---|---|
| `parsed_rinex_data_gen_v2` | `canvod-store/store/reader.py:415` | version suffix | merge into `parsed_rinex_data_gen` |
| `parsed_rinex_data_gen_2_receivers` | `canvodpy/orchestrator/processor.py:1899` | magic number in name | `parsed_rinex_data_gen_multi` or consolidate |

### Overly long names

| Current name | File | Problem | Suggested name |
|---|---|---|---|
| `create_processed_data_fast_hampel_complete` | `canvod-grids/grids/workflows/adapted_workflow.py:233` | 6 words | `run_hampel_pipeline` |
| `create_processed_data_hampel_parallel_complete` | `canvod-grids/grids/workflows/adapted_workflow.py:290` | 6 words | `run_hampel_pipeline_parallel` |
| `_create_processed_data_fast_hampel` | `canvod-grids/grids/workflows/adapted_workflow.py:572` | 5 words + `_fast` | `_run_hampel_filter` |
| `generate_filename_based_on_type` | `canvod-auxiliary/auxiliary/core/base.py:216`, `ephemeris/reader.py:81`, `clock/reader.py:80` | wordy (3 locations) | `build_filename` |
| `normalize_datetime_for_comparison` | `canvod-grids/grids/workflows/adapted_workflow.py:55` | wordy | `normalize_datetime` |
| `check_temporal_coverage_compatibility` | `canvod-grids/grids/workflows/adapted_workflow.py:142` | borderline | `check_temporal_coverage` |
| `safe_temporal_aggregate_to_branch` | `canvod-store/store/store.py:2645` | `safe_` prefix is vague | `aggregate_to_branch` |
| `create_rinex_netcdf_with_signal_id` | `canvod-readers/readers/rinex/v3_04.py:1369` | leaks output format | `to_signal_id_dataset` |

### Cryptic abbreviations

| Current name | File | Problem | Suggested name |
|---|---|---|---|
| `epochrecordinfo_dt_to_numpy_dt` | `canvod-readers/readers/rinex/v3_04.py:1154` | no word separators, double `dt` | `epoch_record_to_datetime64` |
| `get_channel_used_by_SV` | `canvod-readers/readers/gnss_specs/constellations.py:811` | PEP 8 violation (noqa suppressed) | `get_channel_for_sv` |
| `freqs_G1_G2_lut` | `canvod-readers/readers/gnss_specs/constellations.py:865` | dense abbreviation + PEP 8 (noqa) | `build_glonass_frequency_lut` |

### Implementation-detail leaks

| Current name | File | Problem | Suggested name |
|---|---|---|---|
| `_convert_to_polars_freq` | `canvod-grids/grids/aggregation.py:487` | leaks "polars" | `_normalize_freq_string` |
| `_preprocess_aux_data_with_hermite` | `canvodpy/orchestrator/processor.py:551` | leaks algorithm name | `_preprocess_auxiliary_data` |
| `hemigrid_polars_storage_methods.py` | `canvod-store/store/grid_adapters/` | leaks "polars" in module name | deprecate module, move logic |

---

## Medium: Structural renames

### Directory rename

| Current | Problem | Suggested |
|---|---|---|
| `canvod-grids/grids/grids_impl/` | `_impl` suffix | `builders/` |

This requires updating all imports from `canvod.grids.grids_impl` to `canvod.grids.builders`. Leave a re-export shim in `grids_impl/__init__.py` for one release.

### File renames

| Current | Problem | Suggested |
|---|---|---|
| `constants_CLEANED.py` | process artifact in name | merge into `constants.py` or rename to `constants_v2.py` then consolidate |
| `timing_diagnostics_new_api.py` | `_new_api` temporal suffix | `timing_diagnostics.py` |

### Class rename

| Current | File | Problem | Suggested |
|---|---|---|---|
| `MyIcechunkStore` | `canvod-store/store/store.py:42` | `My` prefix | `IcechunkStore` |

This is the highest-impact rename. Used across notebooks, tests, and downstream code. Provide `MyIcechunkStore = IcechunkStore` alias with deprecation warning.

### Function that should be documentation

| Current | File | Problem |
|---|---|---|
| `adapt_existing_rnxv3obs_class` | `canvod-readers/readers/rinex/v3_04.py:1822` | Returns a string of integration instructions; not code |

Remove and move content to a doc page or docstring.

---

## Low: Naming conventions to establish

### Verb consistency for data retrieval

Establish project-wide convention:
- `get_*` = return metadata, config, lightweight (no I/O)
- `read_*` = read raw data from file/store (I/O bound)
- `load_*` = read + parse/construct (higher-level, may combine multiple reads)

Current violations are too numerous to list individually. Apply convention during refactor.

### Builder-pattern `compute()` methods

`WeightCalculator.compute()` and `SpatialMaskBuilder.compute()` are acceptable given the builder pattern (`builder.add_*().compute()`). No action needed.

---

## Execution order

1. `MyIcechunkStore` -> `IcechunkStore` (highest visibility)
2. `add_cell_ids_to_ds_fast` / `add_cell_ids_to_vod_fast` (public API)
3. `prep_aux_ds` (public API)
4. `grids_impl/` -> `builders/` (structural)
5. Internal speed qualifiers (`_fast`, `_slow`, `_ultra_fast`)
6. Overly long names
7. Abbreviations and PEP 8 violations
8. Verb consistency pass
