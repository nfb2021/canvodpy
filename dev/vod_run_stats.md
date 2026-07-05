➜  canvodpy-perf git:(explore/performance-review) ✗   rm -rf /Volumes/ExtremePro/Daily_data/aux_*.zarr && rm -rf /Volumes/ExtremePro/canvod_stores/rosalia && cd
  /Users/work/Developer/GNSS/canvodpy-perf && uv run python -m canvodpy.cli.run --site rosalia --start 2025001 --end 2025028
========================================================================
canvodpy  site=rosalia  2025001 .. 2025028
========================================================================
  started        2026-07-05 13:46:23
  ephemeris      final
  keep_vars      ['SNR']
  batch_hours    24.0
  resource_mode  auto
  store_strategy skip
  rinex_store    rinex
  vod_store      vod
  vod            enabled

VOD analyses: ['canopy_01_vs_reference_01']

ℹ Using ESA FTP exclusively
  To enable NASA CDDIS fallback, set nasa_earthdata_acc_mail in config/processing.yaml
File /Volumes/ExtremePro/Daily_data/01_SP3/COD0MGXFIN_20250010000_01D_05M_ORB.SP3 exists.
ℹ Using ESA FTP exclusively
  To enable NASA CDDIS fallback, set nasa_earthdata_acc_mail in config/processing.yaml
File /Volumes/ExtremePro/Daily_data/02_CLK/COD0MGXFIN_20250010000_01D_30S_CLK.CLK exists.
⠼   canopy_01              ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  0/28 0:00:25 eta -:--:--
⠼   reference_01_canopy_01 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  0/28 0:00:25 eta -:--:--/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/xarray/coding/times.py:670: RuntimeWarning: invalid value encountered in cast
  flat_num = flat_num.astype(np.int64)
/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/xarray/coding/times.py:670: RuntimeWarning: invalid value encountered in cast
⠦   canopy_01              ━╺━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  1/28 0:00:29 eta -:--:--
⠦   reference_01_canopy_01 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  0/28 0:00:29 eta -:--:--/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/xarray/coding/times.py:670: RuntimeWarning: invalid value encountered in cast

--- 2025001 ---
  canopy_01: 17280 epochs x 277 sids
  reference_01_canopy_01: 17280 epochs x 277 sids
  VOD canopy_01_vs_reference_01: 1050181/4786560 valid (22%)  0.2s
  pipeline=30.3s  vod=0.4s  vod_store=0.2s  day=30.9s
ℹ Using ESA FTP exclusively
  To enable NASA CDDIS fallback, set nasa_earthdata_acc_mail in config/processing.yaml
File /Volumes/ExtremePro/Daily_data/01_SP3/COD0MGXFIN_20250020000_01D_05M_ORB.SP3 exists.
ℹ Using ESA FTP exclusively
  To enable NASA CDDIS fallback, set nasa_earthdata_acc_mail in config/processing.yaml
File /Volumes/ExtremePro/Daily_data/02_CLK/COD0MGXFIN_20250020000_01D_30S_CLK.CLK exists.
⠧   canopy_01              ━╺━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  1/28 0:00:55 eta -:--:--
⠧   reference_01_canopy_01 ━╺━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  1/28 0:00:55 eta -:--:--/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/zarr/core/group.py:3559: ZarrUserWarning: Object at .DS_Store is not recognized as a component of a Zarr hierarchy.
⠙   canopy_01              ━╺━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  1/28 0:00:56 eta -:--:--
⠙   reference_01_canopy_01 ━╺━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  1/28 0:00:56 eta -:--:--/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/xarray/coding/times.py:670: RuntimeWarning: invalid value encountered in cast
⠏   canopy_01              ━━╸━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  2/28 0:00:59 eta -:--:--
⠏   reference_01_canopy_01 ━╺━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  1/28 0:00:59 eta -:--:--/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/zarr/core/group.py:3559: ZarrUserWarning: Object at .DS_Store is not recognized as a component of a Zarr hierarchy.
⠸   canopy_01              ━━╸━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  2/28 0:00:59 eta -:--:--
⠸   reference_01_canopy_01 ━╺━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  1/28 0:00:59 eta -:--:--/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/xarray/coding/times.py:670: RuntimeWarning: invalid value encountered in cast

--- 2025002 ---
  canopy_01: 17280 epochs x 277 sids
  reference_01_canopy_01: 17280 epochs x 277 sids
  VOD canopy_01_vs_reference_01: 1062680/4786560 valid (22%)  0.2s
  pipeline=29.6s  vod=0.2s  vod_store=0.2s  day=30.0s
ℹ Using ESA FTP exclusively
  To enable NASA CDDIS fallback, set nasa_earthdata_acc_mail in config/processing.yaml
File /Volumes/ExtremePro/Daily_data/01_SP3/COD0MGXFIN_20250030000_01D_05M_ORB.SP3 exists.
ℹ Using ESA FTP exclusively
  To enable NASA CDDIS fallback, set nasa_earthdata_acc_mail in config/processing.yaml
File /Volumes/ExtremePro/Daily_data/02_CLK/COD0MGXFIN_20250030000_01D_30S_CLK.CLK exists.
⠹   canopy_01              ━━╸━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  2/28 0:01:24 eta -:--:--
⠹   reference_01_canopy_01 ━━╸━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  2/28 0:01:24 eta -:--:--/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/zarr/core/group.py:3559: ZarrUserWarning: Object at .DS_Store is not recognized as a component of a Zarr hierarchy.
⠦   canopy_01              ━━╸━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  2/28 0:01:24 eta -:--:--
⠦   reference_01_canopy_01 ━━╸━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  2/28 0:01:24 eta -:--:--/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/xarray/coding/times.py:670: RuntimeWarning: invalid value encountered in cast
⠙   canopy_01              ━━━━╺━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  3/28 0:01:28 eta 0:11:54
⠙   reference_01_canopy_01 ━━╸━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  2/28 0:01:28 eta -:--:--/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/zarr/core/group.py:3559: ZarrUserWarning: Object at .DS_Store is not recognized as a component of a Zarr hierarchy.
⠦   canopy_01              ━━━━╺━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  3/28 0:01:28 eta 0:11:54
⠦   reference_01_canopy_01 ━━╸━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  2/28 0:01:28 eta -:--:--/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/xarray/coding/times.py:670: RuntimeWarning: invalid value encountered in cast

--- 2025003 ---
  canopy_01: 17280 epochs x 277 sids
  reference_01_canopy_01: 17280 epochs x 277 sids
  VOD canopy_01_vs_reference_01: 998503/4786560 valid (21%)  0.2s
  pipeline=28.6s  vod=0.2s  vod_store=0.2s  day=29.1s
ℹ Using ESA FTP exclusively
  To enable NASA CDDIS fallback, set nasa_earthdata_acc_mail in config/processing.yaml
File /Volumes/ExtremePro/Daily_data/01_SP3/COD0MGXFIN_20250040000_01D_05M_ORB.SP3 exists.
ℹ Using ESA FTP exclusively
  To enable NASA CDDIS fallback, set nasa_earthdata_acc_mail in config/processing.yaml
File /Volumes/ExtremePro/Daily_data/02_CLK/COD0MGXFIN_20250040000_01D_30S_CLK.CLK exists.
⠋   canopy_01              ━━━━╺━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  3/28 0:01:54 eta 0:11:54
⠋   reference_01_canopy_01 ━━━━╺━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  3/28 0:01:54 eta 0:12:07/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/zarr/core/group.py:3559: ZarrUserWarning: Object at .DS_Store is not recognized as a component of a Zarr hierarchy.
⠧   canopy_01              ━━━━╺━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  3/28 0:01:54 eta 0:11:54
⠧   reference_01_canopy_01 ━━━━╺━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  3/28 0:01:54 eta 0:12:07/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/xarray/coding/times.py:670: RuntimeWarning: invalid value encountered in cast
⠏   canopy_01              ━━━━━╸━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  4/28 0:01:58 eta -:--:--
⠏   reference_01_canopy_01 ━━━━╺━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  3/28 0:01:58 eta 0:12:07/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/zarr/core/group.py:3559: ZarrUserWarning: Object at .DS_Store is not recognized as a component of a Zarr hierarchy.
⠼   canopy_01              ━━━━━╸━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  4/28 0:01:58 eta -:--:--
⠼   reference_01_canopy_01 ━━━━╺━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  3/28 0:01:58 eta 0:12:07/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/xarray/coding/times.py:670: RuntimeWarning: invalid value encountered in cast

--- 2025004 ---
  canopy_01: 17280 epochs x 277 sids
  reference_01_canopy_01: 17280 epochs x 277 sids
  VOD canopy_01_vs_reference_01: 1029374/4786560 valid (22%)  0.2s
  pipeline=29.8s  vod=0.2s  vod_store=0.2s  day=30.2s
ℹ Using ESA FTP exclusively
  To enable NASA CDDIS fallback, set nasa_earthdata_acc_mail in config/processing.yaml
File /Volumes/ExtremePro/Daily_data/01_SP3/COD0MGXFIN_20250050000_01D_05M_ORB.SP3 exists.
ℹ Using ESA FTP exclusively
  To enable NASA CDDIS fallback, set nasa_earthdata_acc_mail in config/processing.yaml
File /Volumes/ExtremePro/Daily_data/02_CLK/COD0MGXFIN_20250050000_01D_30S_CLK.CLK exists.
⠦   canopy_01              ━━━━━╸━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  4/28 0:02:25 eta -:--:--
⠦   reference_01_canopy_01 ━━━━━╸━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  4/28 0:02:25 eta -:--:--/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/zarr/core/group.py:3559: ZarrUserWarning: Object at .DS_Store is not recognized as a component of a Zarr hierarchy.
⠙   canopy_01              ━━━━━╸━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  4/28 0:02:25 eta -:--:--
⠙   reference_01_canopy_01 ━━━━━╸━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  4/28 0:02:25 eta -:--:--/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/xarray/coding/times.py:670: RuntimeWarning: invalid value encountered in cast
⠇   canopy_01              ━━━━━━━╺━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  5/28 0:02:28 eta -:--:--
⠇   reference_01_canopy_01 ━━━━━╸━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  4/28 0:02:28 eta -:--:--/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/zarr/core/group.py:3559: ZarrUserWarning: Object at .DS_Store is not recognized as a component of a Zarr hierarchy.

--- 2025005 ---
  canopy_01: 17280 epochs x 277 sids
  reference_01_canopy_01: 17280 epochs x 277 sids
  VOD canopy_01_vs_reference_01: 1061584/4786560 valid (22%)  0.2s
  pipeline=29.9s  vod=0.2s  vod_store=0.2s  day=30.3s
ℹ Using ESA FTP exclusively
  To enable NASA CDDIS fallback, set nasa_earthdata_acc_mail in config/processing.yaml
File /Volumes/ExtremePro/Daily_data/01_SP3/COD0MGXFIN_20250060000_01D_05M_ORB.SP3 exists.
ℹ Using ESA FTP exclusively
  To enable NASA CDDIS fallback, set nasa_earthdata_acc_mail in config/processing.yaml
File /Volumes/ExtremePro/Daily_data/02_CLK/COD0MGXFIN_20250060000_01D_30S_CLK.CLK exists.
⠋   canopy_01              ━━━━━━━╺━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  5/28 0:02:54 eta -:--:--
⠋   reference_01_canopy_01 ━━━━━━━╺━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  5/28 0:02:54 eta -:--:--/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/zarr/core/group.py:3559: ZarrUserWarning: Object at .DS_Store is not recognized as a component of a Zarr hierarchy.
⠸   canopy_01              ━━━━━━━╺━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  5/28 0:02:54 eta -:--:--
⠸   reference_01_canopy_01 ━━━━━━━╺━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  5/28 0:02:54 eta -:--:--/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/xarray/coding/times.py:670: RuntimeWarning: invalid value encountered in cast
⠹   canopy_01              ━━━━━━━━╸━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  6/28 0:02:57 eta 0:10:35
⠹   reference_01_canopy_01 ━━━━━━━╺━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  5/28 0:02:57 eta -:--:--/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/zarr/core/group.py:3559: ZarrUserWarning: Object at .DS_Store is not recognized as a component of a Zarr hierarchy.

--- 2025006 ---
  canopy_01: 17280 epochs x 277 sids
  reference_01_canopy_01: 17280 epochs x 277 sids
  VOD canopy_01_vs_reference_01: 1043095/4786560 valid (22%)  0.2s
  pipeline=28.7s  vod=0.2s  vod_store=0.2s  day=29.1s
ℹ Using ESA FTP exclusively
  To enable NASA CDDIS fallback, set nasa_earthdata_acc_mail in config/processing.yaml
File /Volumes/ExtremePro/Daily_data/01_SP3/COD0MGXFIN_20250070000_01D_05M_ORB.SP3 exists.
ℹ Using ESA FTP exclusively
  To enable NASA CDDIS fallback, set nasa_earthdata_acc_mail in config/processing.yaml
File /Volumes/ExtremePro/Daily_data/02_CLK/COD0MGXFIN_20250070000_01D_30S_CLK.CLK exists.
⠙   canopy_01              ━━━━━━━━╸━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  6/28 0:03:23 eta 0:10:35
⠙   reference_01_canopy_01 ━━━━━━━━╸━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  6/28 0:03:23 eta 0:10:40/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/zarr/core/group.py:3559: ZarrUserWarning: Object at .DS_Store is not recognized as a component of a Zarr hierarchy.
⠋   canopy_01              ━━━━━━━━━━╺━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  7/28 0:03:26 eta 0:10:06
⠋   reference_01_canopy_01 ━━━━━━━━╸━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  6/28 0:03:26 eta 0:10:40/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/zarr/core/group.py:3559: ZarrUserWarning: Object at .DS_Store is not recognized as a component of a Zarr hierarchy.

--- 2025007 ---
  canopy_01: 17280 epochs x 277 sids
  reference_01_canopy_01: 17280 epochs x 277 sids
  VOD canopy_01_vs_reference_01: 1027281/4786560 valid (21%)  0.2s
  pipeline=28.2s  vod=0.2s  vod_store=0.2s  day=28.6s
ℹ Using ESA FTP exclusively
  To enable NASA CDDIS fallback, set nasa_earthdata_acc_mail in config/processing.yaml
File /Volumes/ExtremePro/Daily_data/01_SP3/COD0MGXFIN_20250080000_01D_05M_ORB.SP3 exists.
ℹ Using ESA FTP exclusively
  To enable NASA CDDIS fallback, set nasa_earthdata_acc_mail in config/processing.yaml
File /Volumes/ExtremePro/Daily_data/02_CLK/COD0MGXFIN_20250080000_01D_30S_CLK.CLK exists.
⠧   canopy_01              ━━━━━━━━━━╺━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  7/28 0:03:51 eta 0:10:06
⠧   reference_01_canopy_01 ━━━━━━━━━━╺━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  7/28 0:03:51 eta 0:10:00/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/zarr/core/group.py:3559: ZarrUserWarning: Object at .DS_Store is not recognized as a component of a Zarr hierarchy.
⠸   canopy_01              ━━━━━━━━━━╺━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  7/28 0:03:52 eta 0:10:06
⠸   reference_01_canopy_01 ━━━━━━━━━━╺━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  7/28 0:03:52 eta 0:10:00/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/xarray/coding/times.py:670: RuntimeWarning: invalid value encountered in cast
  flat_num = flat_num.astype(np.int64)
/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/xarray/coding/times.py:670: RuntimeWarning: invalid value encountered in cast
⠋   canopy_01              ━━━━━━━━━━━╺━━━━━━━━━━━━━━━━━━━━━━━━━━━━  8/28 0:03:55 eta 0:09:34
⠋   reference_01_canopy_01 ━━━━━━━━━━╺━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  7/28 0:03:55 eta 0:10:00/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/zarr/core/group.py:3559: ZarrUserWarning: Object at .DS_Store is not recognized as a component of a Zarr hierarchy.

--- 2025008 ---
  canopy_01: 17280 epochs x 277 sids
  reference_01_canopy_01: 17280 epochs x 277 sids
  VOD canopy_01_vs_reference_01: 1034184/4786560 valid (22%)  0.2s
  pipeline=28.5s  vod=0.2s  vod_store=0.2s  day=28.8s
ℹ Using ESA FTP exclusively
  To enable NASA CDDIS fallback, set nasa_earthdata_acc_mail in config/processing.yaml
File /Volumes/ExtremePro/Daily_data/01_SP3/COD0MGXFIN_20250090000_01D_05M_ORB.SP3 exists.
ℹ Using ESA FTP exclusively
  To enable NASA CDDIS fallback, set nasa_earthdata_acc_mail in config/processing.yaml
File /Volumes/ExtremePro/Daily_data/02_CLK/COD0MGXFIN_20250090000_01D_30S_CLK.CLK exists.
⠧   canopy_01              ━━━━━━━━━━━╺━━━━━━━━━━━━━━━━━━━━━━━━━━━━  8/28 0:04:20 eta 0:09:34
⠧   reference_01_canopy_01 ━━━━━━━━━━━╺━━━━━━━━━━━━━━━━━━━━━━━━━━━━  8/28 0:04:20 eta 0:09:37/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/zarr/core/group.py:3559: ZarrUserWarning: Object at .DS_Store is not recognized as a component of a Zarr hierarchy.
⠙   canopy_01              ━━━━━━━━━━━╺━━━━━━━━━━━━━━━━━━━━━━━━━━━━  8/28 0:04:20 eta 0:09:34
⠙   reference_01_canopy_01 ━━━━━━━━━━━╺━━━━━━━━━━━━━━━━━━━━━━━━━━━━  8/28 0:04:20 eta 0:09:37/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/xarray/coding/times.py:670: RuntimeWarning: invalid value encountered in cast
⠹   canopy_01              ━━━━━━━━━━━━╸━━━━━━━━━━━━━━━━━━━━━━━━━━━  9/28 0:04:24 eta 0:09:08
⠹   reference_01_canopy_01 ━━━━━━━━━━━╺━━━━━━━━━━━━━━━━━━━━━━━━━━━━  8/28 0:04:24 eta 0:09:37/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/zarr/core/group.py:3559: ZarrUserWarning: Object at .DS_Store is not recognized as a component of a Zarr hierarchy.

--- 2025009 ---
  canopy_01: 17280 epochs x 277 sids
  reference_01_canopy_01: 17280 epochs x 277 sids
  VOD canopy_01_vs_reference_01: 1021338/4786560 valid (21%)  0.2s
  pipeline=28.7s  vod=0.2s  vod_store=0.2s  day=29.1s
ℹ Using ESA FTP exclusively
  To enable NASA CDDIS fallback, set nasa_earthdata_acc_mail in config/processing.yaml
File /Volumes/ExtremePro/Daily_data/01_SP3/COD0MGXFIN_20250100000_01D_05M_ORB.SP3 exists.
ℹ Using ESA FTP exclusively
  To enable NASA CDDIS fallback, set nasa_earthdata_acc_mail in config/processing.yaml
File /Volumes/ExtremePro/Daily_data/02_CLK/COD0MGXFIN_20250100000_01D_30S_CLK.CLK exists.
⠇   canopy_01              ━━━━━━━━━━━━╸━━━━━━━━━━━━━━━━━━━━━━━━━━━  9/28 0:04:49 eta 0:09:08
⠇   reference_01_canopy_01 ━━━━━━━━━━━━╸━━━━━━━━━━━━━━━━━━━━━━━━━━━  9/28 0:04:49 eta 0:09:13/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/zarr/core/group.py:3559: ZarrUserWarning: Object at .DS_Store is not recognized as a component of a Zarr hierarchy.
⠼   canopy_01              ━━━━━━━━━━━━╸━━━━━━━━━━━━━━━━━━━━━━━━━━━  9/28 0:04:49 eta 0:09:08
⠼   reference_01_canopy_01 ━━━━━━━━━━━━╸━━━━━━━━━━━━━━━━━━━━━━━━━━━  9/28 0:04:49 eta 0:09:13/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/xarray/coding/times.py:670: RuntimeWarning: invalid value encountered in cast
  flat_num = flat_num.astype(np.int64)
/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/xarray/coding/times.py:670: RuntimeWarning: invalid value encountered in cast
⠙   canopy_01              ━━━━━━━━━━━━━━╺━━━━━━━━━━━━━━━━━━━━━━━━━ 10/28 0:04:53 eta 0:08:46
⠙   reference_01_canopy_01 ━━━━━━━━━━━━╸━━━━━━━━━━━━━━━━━━━━━━━━━━━  9/28 0:04:53 eta 0:09:13/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/zarr/core/group.py:3559: ZarrUserWarning: Object at .DS_Store is not recognized as a component of a Zarr hierarchy.
⠦   canopy_01              ━━━━━━━━━━━━━━╺━━━━━━━━━━━━━━━━━━━━━━━━━ 10/28 0:04:54 eta 0:08:46
⠦   reference_01_canopy_01 ━━━━━━━━━━━━╸━━━━━━━━━━━━━━━━━━━━━━━━━━━  9/28 0:04:54 eta 0:09:13/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/xarray/coding/times.py:670: RuntimeWarning: invalid value encountered in cast
⠇   canopy_01              ━━━━━━━━━━━━━━╺━━━━━━━━━━━━━━━━━━━━━━━━━ 10/28 0:04:54 eta 0:08:46
⠇   reference_01_canopy_01 ━━━━━━━━━━━━╸━━━━━━━━━━━━━━━━━━━━━━━━━━━  9/28 0:04:54 eta 0:09:13/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/xarray/coding/times.py:670: RuntimeWarning: invalid value encountered in cast

--- 2025010 ---
  canopy_01: 17280 epochs x 277 sids
  reference_01_canopy_01: 17280 epochs x 277 sids
  VOD canopy_01_vs_reference_01: 992766/4786560 valid (21%)  0.2s
  pipeline=29.0s  vod=0.2s  vod_store=0.2s  day=29.4s
ℹ Using ESA FTP exclusively
  To enable NASA CDDIS fallback, set nasa_earthdata_acc_mail in config/processing.yaml
File /Volumes/ExtremePro/Daily_data/01_SP3/COD0MGXFIN_20250110000_01D_05M_ORB.SP3 exists.
ℹ Using ESA FTP exclusively
  To enable NASA CDDIS fallback, set nasa_earthdata_acc_mail in config/processing.yaml
File /Volumes/ExtremePro/Daily_data/02_CLK/COD0MGXFIN_20250110000_01D_30S_CLK.CLK exists.
⠏   canopy_01              ━━━━━━━━━━━━━━╺━━━━━━━━━━━━━━━━━━━━━━━━━ 10/28 0:05:19 eta 0:08:46
⠏   reference_01_canopy_01 ━━━━━━━━━━━━━━╺━━━━━━━━━━━━━━━━━━━━━━━━━ 10/28 0:05:19 eta 0:08:50/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/zarr/core/group.py:3559: ZarrUserWarning: Object at .DS_Store is not recognized as a component of a Zarr hierarchy.
⠧   canopy_01              ━━━━━━━━━━━━━━━╸━━━━━━━━━━━━━━━━━━━━━━━━ 11/28 0:05:23 eta 0:08:21
⠧   reference_01_canopy_01 ━━━━━━━━━━━━━━╺━━━━━━━━━━━━━━━━━━━━━━━━━ 10/28 0:05:23 eta 0:08:50/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/zarr/core/group.py:3559: ZarrUserWarning: Object at .DS_Store is not recognized as a component of a Zarr hierarchy.
⠸   canopy_01              ━━━━━━━━━━━━━━━╸━━━━━━━━━━━━━━━━━━━━━━━━ 11/28 0:05:23 eta 0:08:21
⠸   reference_01_canopy_01 ━━━━━━━━━━━━━━╺━━━━━━━━━━━━━━━━━━━━━━━━━ 10/28 0:05:23 eta 0:08:50/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/xarray/coding/times.py:670: RuntimeWarning: invalid value encountered in cast

--- 2025011 ---
  canopy_01: 17280 epochs x 277 sids
  reference_01_canopy_01: 17280 epochs x 277 sids
  VOD canopy_01_vs_reference_01: 989893/4786560 valid (21%)  0.2s
  pipeline=29.0s  vod=0.2s  vod_store=0.2s  day=29.4s
ℹ Using ESA FTP exclusively
  To enable NASA CDDIS fallback, set nasa_earthdata_acc_mail in config/processing.yaml
File /Volumes/ExtremePro/Daily_data/01_SP3/COD0MGXFIN_20250120000_01D_05M_ORB.SP3 exists.
ℹ Using ESA FTP exclusively
  To enable NASA CDDIS fallback, set nasa_earthdata_acc_mail in config/processing.yaml
File /Volumes/ExtremePro/Daily_data/02_CLK/COD0MGXFIN_20250120000_01D_30S_CLK.CLK exists.
⠴   canopy_01              ━━━━━━━━━━━━━━━╸━━━━━━━━━━━━━━━━━━━━━━━━ 11/28 0:05:49 eta 0:08:21
⠴   reference_01_canopy_01 ━━━━━━━━━━━━━━━╸━━━━━━━━━━━━━━━━━━━━━━━━ 11/28 0:05:49 eta 0:08:20/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/zarr/core/group.py:3559: ZarrUserWarning: Object at .DS_Store is not recognized as a component of a Zarr hierarchy.
⠦   canopy_01              ━━━━━━━━━━━━━━━━━╺━━━━━━━━━━━━━━━━━━━━━━ 12/28 0:05:52 eta 0:08:00
⠦   reference_01_canopy_01 ━━━━━━━━━━━━━━━╸━━━━━━━━━━━━━━━━━━━━━━━━ 11/28 0:05:52 eta 0:08:20/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/zarr/core/group.py:3559: ZarrUserWarning: Object at .DS_Store is not recognized as a component of a Zarr hierarchy.

--- 2025012 ---
  canopy_01: 17280 epochs x 277 sids
  reference_01_canopy_01: 17280 epochs x 277 sids
  VOD canopy_01_vs_reference_01: 1010873/4786560 valid (21%)  0.2s
  pipeline=29.1s  vod=0.2s  vod_store=0.2s  day=29.5s
ℹ Using ESA FTP exclusively
  To enable NASA CDDIS fallback, set nasa_earthdata_acc_mail in config/processing.yaml
File /Volumes/ExtremePro/Daily_data/01_SP3/COD0MGXFIN_20250130000_01D_05M_ORB.SP3 exists.
ℹ Using ESA FTP exclusively
  To enable NASA CDDIS fallback, set nasa_earthdata_acc_mail in config/processing.yaml
File /Volumes/ExtremePro/Daily_data/02_CLK/COD0MGXFIN_20250130000_01D_30S_CLK.CLK exists.
⠏   canopy_01              ━━━━━━━━━━━━━━━━━╺━━━━━━━━━━━━━━━━━━━━━━ 12/28 0:06:19 eta 0:08:00
⠏   reference_01_canopy_01 ━━━━━━━━━━━━━━━━━╺━━━━━━━━━━━━━━━━━━━━━━ 12/28 0:06:19 eta 0:07:53/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/zarr/core/group.py:3559: ZarrUserWarning: Object at .DS_Store is not recognized as a component of a Zarr hierarchy.
⠸   canopy_01              ━━━━━━━━━━━━━━━━━━╸━━━━━━━━━━━━━━━━━━━━━ 13/28 0:06:23 eta -:--:--
⠸   reference_01_canopy_01 ━━━━━━━━━━━━━━━━━╺━━━━━━━━━━━━━━━━━━━━━━ 12/28 0:06:23 eta 0:07:53/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/zarr/core/group.py:3559: ZarrUserWarning: Object at .DS_Store is not recognized as a component of a Zarr hierarchy.

--- 2025013 ---
  canopy_01: 17280 epochs x 277 sids
  reference_01_canopy_01: 17280 epochs x 277 sids
  VOD canopy_01_vs_reference_01: 1060962/4786560 valid (22%)  0.2s
  pipeline=30.4s  vod=0.2s  vod_store=0.2s  day=30.9s
ℹ Using ESA FTP exclusively
  To enable NASA CDDIS fallback, set nasa_earthdata_acc_mail in config/processing.yaml
File /Volumes/ExtremePro/Daily_data/01_SP3/COD0MGXFIN_20250140000_01D_05M_ORB.SP3 exists.
ℹ Using ESA FTP exclusively
  To enable NASA CDDIS fallback, set nasa_earthdata_acc_mail in config/processing.yaml
File /Volumes/ExtremePro/Daily_data/02_CLK/COD0MGXFIN_20250140000_01D_30S_CLK.CLK exists.
⠏   canopy_01              ━━━━━━━━━━━━━━━━━━╸━━━━━━━━━━━━━━━━━━━━━ 13/28 0:06:51 eta -:--:--
⠏   reference_01_canopy_01 ━━━━━━━━━━━━━━━━━━╸━━━━━━━━━━━━━━━━━━━━━ 13/28 0:06:51 eta -:--:--/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/zarr/core/group.py:3559: ZarrUserWarning: Object at .DS_Store is not recognized as a component of a Zarr hierarchy.
⠧   canopy_01              ━━━━━━━━━━━━━━━━━━━━╺━━━━━━━━━━━━━━━━━━━ 14/28 0:06:54 eta -:--:--
⠧   reference_01_canopy_01 ━━━━━━━━━━━━━━━━━━╸━━━━━━━━━━━━━━━━━━━━━ 13/28 0:06:54 eta -:--:--/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/zarr/core/group.py:3559: ZarrUserWarning: Object at .DS_Store is not recognized as a component of a Zarr hierarchy.

--- 2025014 ---
  canopy_01: 17280 epochs x 277 sids
  reference_01_canopy_01: 17266 epochs x 277 sids
  VOD canopy_01_vs_reference_01: 1077595/4782682 valid (23%)  0.2s
  pipeline=30.4s  vod=0.2s  vod_store=0.2s  day=30.8s
ℹ Using ESA FTP exclusively
  To enable NASA CDDIS fallback, set nasa_earthdata_acc_mail in config/processing.yaml
File /Volumes/ExtremePro/Daily_data/01_SP3/COD0MGXFIN_20250150000_01D_05M_ORB.SP3 exists.
ℹ Using ESA FTP exclusively
  To enable NASA CDDIS fallback, set nasa_earthdata_acc_mail in config/processing.yaml
File /Volumes/ExtremePro/Daily_data/02_CLK/COD0MGXFIN_20250150000_01D_30S_CLK.CLK exists.
⠙   canopy_01              ━━━━━━━━━━━━━━━━━━━━╺━━━━━━━━━━━━━━━━━━━ 14/28 0:07:20 eta -:--:--
⠙   reference_01_canopy_01 ━━━━━━━━━━━━━━━━━━━━╺━━━━━━━━━━━━━━━━━━━ 14/28 0:07:20 eta -:--:--/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/zarr/core/group.py:3559: ZarrUserWarning: Object at .DS_Store is not recognized as a component of a Zarr hierarchy.
⠦   canopy_01              ━━━━━━━━━━━━━━━━━━━━━╺━━━━━━━━━━━━━━━━━━ 15/28 0:07:24 eta 0:06:28
⠦   reference_01_canopy_01 ━━━━━━━━━━━━━━━━━━━━╺━━━━━━━━━━━━━━━━━━━ 14/28 0:07:24 eta -:--:--/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/zarr/core/group.py:3559: ZarrUserWarning: Object at .DS_Store is not recognized as a component of a Zarr hierarchy.

--- 2025015 ---
  canopy_01: 17280 epochs x 277 sids
  reference_01_canopy_01: 17280 epochs x 277 sids
  VOD canopy_01_vs_reference_01: 1038132/4786560 valid (22%)  0.2s
  pipeline=29.9s  vod=0.2s  vod_store=0.3s  day=30.5s
ℹ Using ESA FTP exclusively
  To enable NASA CDDIS fallback, set nasa_earthdata_acc_mail in config/processing.yaml
File /Volumes/ExtremePro/Daily_data/01_SP3/COD0MGXFIN_20250160000_01D_05M_ORB.SP3 exists.
ℹ Using ESA FTP exclusively
  To enable NASA CDDIS fallback, set nasa_earthdata_acc_mail in config/processing.yaml
File /Volumes/ExtremePro/Daily_data/02_CLK/COD0MGXFIN_20250160000_01D_30S_CLK.CLK exists.
⠦   canopy_01              ━━━━━━━━━━━━━━━━━━━━━╺━━━━━━━━━━━━━━━━━━ 15/28 0:07:51 eta 0:06:28
⠦   reference_01_canopy_01 ━━━━━━━━━━━━━━━━━━━━━╺━━━━━━━━━━━━━━━━━━ 15/28 0:07:51 eta -:--:--/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/zarr/core/group.py:3559: ZarrUserWarning: Object at .DS_Store is not recognized as a component of a Zarr hierarchy.
⠙   canopy_01              ━━━━━━━━━━━━━━━━━━━━━━╸━━━━━━━━━━━━━━━━━ 16/28 0:07:55 eta -:--:--
⠙   reference_01_canopy_01 ━━━━━━━━━━━━━━━━━━━━━╺━━━━━━━━━━━━━━━━━━ 15/28 0:07:55 eta -:--:--/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/zarr/core/group.py:3559: ZarrUserWarning: Object at .DS_Store is not recognized as a component of a Zarr hierarchy.

--- 2025016 ---
  canopy_01: 17280 epochs x 277 sids
  reference_01_canopy_01: 17280 epochs x 277 sids
  VOD canopy_01_vs_reference_01: 1068911/4786560 valid (22%)  0.2s
  pipeline=30.3s  vod=0.2s  vod_store=0.3s  day=30.9s
ℹ Using ESA FTP exclusively
  To enable NASA CDDIS fallback, set nasa_earthdata_acc_mail in config/processing.yaml
File /Volumes/ExtremePro/Daily_data/01_SP3/COD0MGXFIN_20250170000_01D_05M_ORB.SP3 exists.
ℹ Using ESA FTP exclusively
  To enable NASA CDDIS fallback, set nasa_earthdata_acc_mail in config/processing.yaml
File /Volumes/ExtremePro/Daily_data/02_CLK/COD0MGXFIN_20250170000_01D_30S_CLK.CLK exists.
⠇   canopy_01              ━━━━━━━━━━━━━━━━━━━━━━╸━━━━━━━━━━━━━━━━━ 16/28 0:08:22 eta -:--:--
⠇   reference_01_canopy_01 ━━━━━━━━━━━━━━━━━━━━━━╸━━━━━━━━━━━━━━━━━ 16/28 0:08:22 eta -:--:--/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/zarr/core/group.py:3559: ZarrUserWarning: Object at .DS_Store is not recognized as a component of a Zarr hierarchy.
⠴   canopy_01              ━━━━━━━━━━━━━━━━━━━━━━╸━━━━━━━━━━━━━━━━━ 16/28 0:08:22 eta -:--:--
⠴   reference_01_canopy_01 ━━━━━━━━━━━━━━━━━━━━━━╸━━━━━━━━━━━━━━━━━ 16/28 0:08:22 eta -:--:--/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/xarray/coding/times.py:670: RuntimeWarning: invalid value encountered in cast
⠦   canopy_01              ━━━━━━━━━━━━━━━━━━━━━━╸━━━━━━━━━━━━━━━━━ 16/28 0:08:22 eta -:--:--
⠦   reference_01_canopy_01 ━━━━━━━━━━━━━━━━━━━━━━╸━━━━━━━━━━━━━━━━━ 16/28 0:08:22 eta -:--:--/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/xarray/coding/times.py:670: RuntimeWarning: invalid value encountered in cast
⠙   canopy_01              ━━━━━━━━━━━━━━━━━━━━━━━━╺━━━━━━━━━━━━━━━ 17/28 0:08:25 eta -:--:--
⠙   reference_01_canopy_01 ━━━━━━━━━━━━━━━━━━━━━━╸━━━━━━━━━━━━━━━━━ 16/28 0:08:25 eta -:--:--/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/zarr/core/group.py:3559: ZarrUserWarning: Object at .DS_Store is not recognized as a component of a Zarr hierarchy.

--- 2025017 ---
  canopy_01: 17280 epochs x 277 sids
  reference_01_canopy_01: 17280 epochs x 277 sids
  VOD canopy_01_vs_reference_01: 1044326/4786560 valid (22%)  0.2s
  pipeline=29.7s  vod=0.2s  vod_store=0.3s  day=30.3s
ℹ Using ESA FTP exclusively
  To enable NASA CDDIS fallback, set nasa_earthdata_acc_mail in config/processing.yaml
File /Volumes/ExtremePro/Daily_data/01_SP3/COD0MGXFIN_20250180000_01D_05M_ORB.SP3 exists.
ℹ Using ESA FTP exclusively
  To enable NASA CDDIS fallback, set nasa_earthdata_acc_mail in config/processing.yaml
File /Volumes/ExtremePro/Daily_data/02_CLK/COD0MGXFIN_20250180000_01D_30S_CLK.CLK exists.
⠸   canopy_01              ━━━━━━━━━━━━━━━━━━━━━━━━╺━━━━━━━━━━━━━━━ 17/28 0:08:53 eta -:--:--
⠸   reference_01_canopy_01 ━━━━━━━━━━━━━━━━━━━━━━━━╺━━━━━━━━━━━━━━━ 17/28 0:08:53 eta -:--:--/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/zarr/core/group.py:3559: ZarrUserWarning: Object at .DS_Store is not recognized as a component of a Zarr hierarchy.
⠏   canopy_01              ━━━━━━━━━━━━━━━━━━━━━━━━╺━━━━━━━━━━━━━━━ 17/28 0:08:53 eta -:--:--
⠏   reference_01_canopy_01 ━━━━━━━━━━━━━━━━━━━━━━━━╺━━━━━━━━━━━━━━━ 17/28 0:08:53 eta -:--:--/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/xarray/coding/times.py:670: RuntimeWarning: invalid value encountered in cast
⠼   canopy_01              ━━━━━━━━━━━━━━━━━━━━━━━━━╸━━━━━━━━━━━━━━ 18/28 0:08:56 eta -:--:--
⠼   reference_01_canopy_01 ━━━━━━━━━━━━━━━━━━━━━━━━╺━━━━━━━━━━━━━━━ 17/28 0:08:56 eta -:--:--/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/zarr/core/group.py:3559: ZarrUserWarning: Object at .DS_Store is not recognized as a component of a Zarr hierarchy.
⠋   canopy_01              ━━━━━━━━━━━━━━━━━━━━━━━━━╸━━━━━━━━━━━━━━ 18/28 0:08:56 eta -:--:--
⠋   reference_01_canopy_01 ━━━━━━━━━━━━━━━━━━━━━━━━╺━━━━━━━━━━━━━━━ 17/28 0:08:56 eta -:--:--/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/xarray/coding/times.py:670: RuntimeWarning: invalid value encountered in cast

--- 2025018 ---
  canopy_01: 17280 epochs x 277 sids
  reference_01_canopy_01: 17280 epochs x 277 sids
  VOD canopy_01_vs_reference_01: 1056029/4786560 valid (22%)  0.2s
  pipeline=30.1s  vod=0.2s  vod_store=0.3s  day=30.6s
ℹ Using ESA FTP exclusively
  To enable NASA CDDIS fallback, set nasa_earthdata_acc_mail in config/processing.yaml
File /Volumes/ExtremePro/Daily_data/01_SP3/COD0MGXFIN_20250190000_01D_05M_ORB.SP3 exists.
ℹ Using ESA FTP exclusively
  To enable NASA CDDIS fallback, set nasa_earthdata_acc_mail in config/processing.yaml
File /Volumes/ExtremePro/Daily_data/02_CLK/COD0MGXFIN_20250190000_01D_30S_CLK.CLK exists.
⠦   canopy_01              ━━━━━━━━━━━━━━━━━━━━━━━━━╸━━━━━━━━━━━━━━ 18/28 0:09:23 eta -:--:--
⠦   reference_01_canopy_01 ━━━━━━━━━━━━━━━━━━━━━━━━━╸━━━━━━━━━━━━━━ 18/28 0:09:23 eta -:--:--/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/zarr/core/group.py:3559: ZarrUserWarning: Object at .DS_Store is not recognized as a component of a Zarr hierarchy.
⠙   canopy_01              ━━━━━━━━━━━━━━━━━━━━━━━━━╸━━━━━━━━━━━━━━ 18/28 0:09:24 eta -:--:--
⠙   reference_01_canopy_01 ━━━━━━━━━━━━━━━━━━━━━━━━━╸━━━━━━━━━━━━━━ 18/28 0:09:24 eta -:--:--/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/xarray/coding/times.py:670: RuntimeWarning: invalid value encountered in cast
⠏   canopy_01              ━━━━━━━━━━━━━━━━━━━━━━━━━━━╺━━━━━━━━━━━━ 19/28 0:09:27 eta -:--:--
⠏   reference_01_canopy_01 ━━━━━━━━━━━━━━━━━━━━━━━━━╸━━━━━━━━━━━━━━ 18/28 0:09:27 eta -:--:--/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/zarr/core/group.py:3559: ZarrUserWarning: Object at .DS_Store is not recognized as a component of a Zarr hierarchy.
⠸   canopy_01              ━━━━━━━━━━━━━━━━━━━━━━━━━━━╺━━━━━━━━━━━━ 19/28 0:09:27 eta -:--:--
⠸   reference_01_canopy_01 ━━━━━━━━━━━━━━━━━━━━━━━━━╸━━━━━━━━━━━━━━ 18/28 0:09:27 eta -:--:--/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/xarray/coding/times.py:670: RuntimeWarning: invalid value encountered in cast

--- 2025019 ---
  canopy_01: 17280 epochs x 277 sids
  reference_01_canopy_01: 17280 epochs x 277 sids
  VOD canopy_01_vs_reference_01: 1087111/4786560 valid (23%)  0.2s
  pipeline=30.2s  vod=0.2s  vod_store=0.3s  day=30.8s
ℹ Using ESA FTP exclusively
  To enable NASA CDDIS fallback, set nasa_earthdata_acc_mail in config/processing.yaml
File /Volumes/ExtremePro/Daily_data/01_SP3/COD0MGXFIN_20250200000_01D_05M_ORB.SP3 exists.
ℹ Using ESA FTP exclusively
  To enable NASA CDDIS fallback, set nasa_earthdata_acc_mail in config/processing.yaml
File /Volumes/ExtremePro/Daily_data/02_CLK/COD0MGXFIN_20250200000_01D_30S_CLK.CLK exists.
⠧   canopy_01              ━━━━━━━━━━━━━━━━━━━━━━━━━━━╺━━━━━━━━━━━━ 19/28 0:09:54 eta -:--:--
⠧   reference_01_canopy_01 ━━━━━━━━━━━━━━━━━━━━━━━━━━━╺━━━━━━━━━━━━ 19/28 0:09:54 eta -:--:--/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/zarr/core/group.py:3559: ZarrUserWarning: Object at .DS_Store is not recognized as a component of a Zarr hierarchy.
⠹   canopy_01              ━━━━━━━━━━━━━━━━━━━━━━━━━━━━╸━━━━━━━━━━━ 20/28 0:09:57 eta -:--:--
⠹   reference_01_canopy_01 ━━━━━━━━━━━━━━━━━━━━━━━━━━━╺━━━━━━━━━━━━ 19/28 0:09:57 eta -:--:--/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/zarr/core/group.py:3559: ZarrUserWarning: Object at .DS_Store is not recognized as a component of a Zarr hierarchy.
⠴   canopy_01              ━━━━━━━━━━━━━━━━━━━━━━━━━━━━╸━━━━━━━━━━━ 20/28 0:09:58 eta -:--:--
⠴   reference_01_canopy_01 ━━━━━━━━━━━━━━━━━━━━━━━━━━━╺━━━━━━━━━━━━ 19/28 0:09:58 eta -:--:--/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/xarray/coding/times.py:670: RuntimeWarning: invalid value encountered in cast

--- 2025020 ---
  canopy_01: 17280 epochs x 277 sids
  reference_01_canopy_01: 17280 epochs x 277 sids
  VOD canopy_01_vs_reference_01: 1064996/4786560 valid (22%)  0.2s
  pipeline=30.1s  vod=0.2s  vod_store=0.3s  day=30.7s
ℹ Using ESA FTP exclusively
  To enable NASA CDDIS fallback, set nasa_earthdata_acc_mail in config/processing.yaml
File /Volumes/ExtremePro/Daily_data/01_SP3/COD0MGXFIN_20250210000_01D_05M_ORB.SP3 exists.
ℹ Using ESA FTP exclusively
  To enable NASA CDDIS fallback, set nasa_earthdata_acc_mail in config/processing.yaml
File /Volumes/ExtremePro/Daily_data/02_CLK/COD0MGXFIN_20250210000_01D_30S_CLK.CLK exists.
⠙   canopy_01              ━━━━━━━━━━━━━━━━━━━━━━━━━━━━╸━━━━━━━━━━━ 20/28 0:10:25 eta -:--:--
⠙   reference_01_canopy_01 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━╸━━━━━━━━━━━ 20/28 0:10:25 eta -:--:--/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/zarr/core/group.py:3559: ZarrUserWarning: Object at .DS_Store is not recognized as a component of a Zarr hierarchy.
⠴   canopy_01              ━━━━━━━━━━━━━━━━━━━━━━━━━━━━╸━━━━━━━━━━━ 20/28 0:10:26 eta -:--:--
⠴   reference_01_canopy_01 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━╸━━━━━━━━━━━ 20/28 0:10:26 eta -:--:--/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/xarray/coding/times.py:670: RuntimeWarning: invalid value encountered in cast
⠴   canopy_01              ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╺━━━━━━━━━ 21/28 0:10:29 eta -:--:--
⠴   reference_01_canopy_01 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━╸━━━━━━━━━━━ 20/28 0:10:29 eta -:--:--/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/zarr/core/group.py:3559: ZarrUserWarning: Object at .DS_Store is not recognized as a component of a Zarr hierarchy.
⠸   canopy_01              ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╺━━━━━━━━━ 21/28 0:10:29 eta -:--:--
⠸   reference_01_canopy_01 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━╸━━━━━━━━━━━ 20/28 0:10:29 eta -:--:--/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/xarray/coding/times.py:670: RuntimeWarning: invalid value encountered in cast

--- 2025021 ---
  canopy_01: 17280 epochs x 277 sids
  reference_01_canopy_01: 17280 epochs x 277 sids
  VOD canopy_01_vs_reference_01: 1077833/4786560 valid (23%)  0.2s
  pipeline=30.9s  vod=0.2s  vod_store=0.3s  day=31.4s
ℹ Using ESA FTP exclusively
  To enable NASA CDDIS fallback, set nasa_earthdata_acc_mail in config/processing.yaml
File /Volumes/ExtremePro/Daily_data/01_SP3/COD0MGXFIN_20250220000_01D_05M_ORB.SP3 exists.
ℹ Using ESA FTP exclusively
  To enable NASA CDDIS fallback, set nasa_earthdata_acc_mail in config/processing.yaml
File /Volumes/ExtremePro/Daily_data/02_CLK/COD0MGXFIN_20250220000_01D_30S_CLK.CLK exists.
⠙   canopy_01              ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╺━━━━━━━━━ 21/28 0:10:57 eta -:--:--
⠙   reference_01_canopy_01 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╺━━━━━━━━━ 21/28 0:10:57 eta -:--:--/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/zarr/core/group.py:3559: ZarrUserWarning: Object at .DS_Store is not recognized as a component of a Zarr hierarchy.
⠇   canopy_01              ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╺━━━━━━━━ 22/28 0:11:00 eta -:--:--
⠇   reference_01_canopy_01 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╺━━━━━━━━━ 21/28 0:11:00 eta -:--:--/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/zarr/core/group.py:3559: ZarrUserWarning: Object at .DS_Store is not recognized as a component of a Zarr hierarchy.
⠼   canopy_01              ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╺━━━━━━━━ 22/28 0:11:01 eta -:--:--
⠼   reference_01_canopy_01 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╺━━━━━━━━━ 21/28 0:11:01 eta -:--:--/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/xarray/coding/times.py:670: RuntimeWarning: invalid value encountered in cast

--- 2025022 ---
  canopy_01: 17280 epochs x 277 sids
  reference_01_canopy_01: 17280 epochs x 277 sids
  VOD canopy_01_vs_reference_01: 1118509/4786560 valid (23%)  0.2s
  pipeline=30.9s  vod=0.2s  vod_store=0.3s  day=31.4s
ℹ Using ESA FTP exclusively
  To enable NASA CDDIS fallback, set nasa_earthdata_acc_mail in config/processing.yaml
File /Volumes/ExtremePro/Daily_data/01_SP3/COD0MGXFIN_20250230000_01D_05M_ORB.SP3 exists.
ℹ Using ESA FTP exclusively
  To enable NASA CDDIS fallback, set nasa_earthdata_acc_mail in config/processing.yaml
File /Volumes/ExtremePro/Daily_data/02_CLK/COD0MGXFIN_20250230000_01D_30S_CLK.CLK exists.
⠏   canopy_01              ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╺━━━━━━━━ 22/28 0:11:27 eta -:--:--
⠏   reference_01_canopy_01 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╺━━━━━━━━ 22/28 0:11:27 eta -:--:--/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/zarr/core/group.py:3559: ZarrUserWarning: Object at .DS_Store is not recognized as a component of a Zarr hierarchy.
⠹   canopy_01              ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╺━━━━━━━━ 22/28 0:11:28 eta -:--:--
⠹   reference_01_canopy_01 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╺━━━━━━━━ 22/28 0:11:28 eta -:--:--/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/xarray/coding/times.py:670: RuntimeWarning: invalid value encountered in cast
⠙   canopy_01              ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╸━━━━━━━ 23/28 0:11:31 eta -:--:--
⠙   reference_01_canopy_01 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╺━━━━━━━━ 22/28 0:11:31 eta -:--:--/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/zarr/core/group.py:3559: ZarrUserWarning: Object at .DS_Store is not recognized as a component of a Zarr hierarchy.
⠦   canopy_01              ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╸━━━━━━━ 23/28 0:11:31 eta -:--:--
⠦   reference_01_canopy_01 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╺━━━━━━━━ 22/28 0:11:31 eta -:--:--/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/xarray/coding/times.py:670: RuntimeWarning: invalid value encountered in cast
  flat_num = flat_num.astype(np.int64)
/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/xarray/coding/times.py:670: RuntimeWarning: invalid value encountered in cast

--- 2025023 ---
  canopy_01: 17280 epochs x 277 sids
  reference_01_canopy_01: 17280 epochs x 277 sids
  VOD canopy_01_vs_reference_01: 1065374/4786560 valid (22%)  0.2s
  pipeline=30.2s  vod=0.2s  vod_store=0.3s  day=30.7s
ℹ Using ESA FTP exclusively
  To enable NASA CDDIS fallback, set nasa_earthdata_acc_mail in config/processing.yaml
File /Volumes/ExtremePro/Daily_data/01_SP3/COD0MGXFIN_20250240000_01D_05M_ORB.SP3 exists.
ℹ Using ESA FTP exclusively
  To enable NASA CDDIS fallback, set nasa_earthdata_acc_mail in config/processing.yaml
File /Volumes/ExtremePro/Daily_data/02_CLK/COD0MGXFIN_20250240000_01D_30S_CLK.CLK exists.
⠼   canopy_01              ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╸━━━━━━━ 23/28 0:11:58 eta -:--:--
⠼   reference_01_canopy_01 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╸━━━━━━━ 23/28 0:11:58 eta -:--:--/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/zarr/core/group.py:3559: ZarrUserWarning: Object at .DS_Store is not recognized as a component of a Zarr hierarchy.
⠏   canopy_01              ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╸━━━━━━━ 23/28 0:11:59 eta -:--:--
⠏   reference_01_canopy_01 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╸━━━━━━━ 23/28 0:11:59 eta -:--:--/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/xarray/coding/times.py:670: RuntimeWarning: invalid value encountered in cast
  flat_num = flat_num.astype(np.int64)
/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/xarray/coding/times.py:670: RuntimeWarning: invalid value encountered in cast
⠦   canopy_01              ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╺━━━━━ 24/28 0:12:02 eta -:--:--
⠦   reference_01_canopy_01 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╸━━━━━━━ 23/28 0:12:02 eta -:--:--/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/zarr/core/group.py:3559: ZarrUserWarning: Object at .DS_Store is not recognized as a component of a Zarr hierarchy.

--- 2025024 ---
  canopy_01: 17280 epochs x 277 sids
  reference_01_canopy_01: 17280 epochs x 277 sids
  VOD canopy_01_vs_reference_01: 1056198/4786560 valid (22%)  0.2s
  pipeline=30.2s  vod=0.2s  vod_store=0.4s  day=30.8s
ℹ Using ESA FTP exclusively
  To enable NASA CDDIS fallback, set nasa_earthdata_acc_mail in config/processing.yaml
File /Volumes/ExtremePro/Daily_data/01_SP3/COD0MGXFIN_20250250000_01D_05M_ORB.SP3 exists.
ℹ Using ESA FTP exclusively
  To enable NASA CDDIS fallback, set nasa_earthdata_acc_mail in config/processing.yaml
File /Volumes/ExtremePro/Daily_data/02_CLK/COD0MGXFIN_20250250000_01D_30S_CLK.CLK exists.
⠧   canopy_01              ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╺━━━━━ 24/28 0:12:29 eta -:--:--
⠧   reference_01_canopy_01 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╺━━━━━ 24/28 0:12:29 eta -:--:--/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/zarr/core/group.py:3559: ZarrUserWarning: Object at .DS_Store is not recognized as a component of a Zarr hierarchy.
⠹   canopy_01              ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╺━━━━━ 24/28 0:12:29 eta -:--:--
⠹   reference_01_canopy_01 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╺━━━━━ 24/28 0:12:29 eta -:--:--/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/xarray/coding/times.py:670: RuntimeWarning: invalid value encountered in cast
⠦   canopy_01              ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╸━━━━ 25/28 0:12:33 eta -:--:--
⠦   reference_01_canopy_01 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╺━━━━━ 24/28 0:12:33 eta -:--:--/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/zarr/core/group.py:3559: ZarrUserWarning: Object at .DS_Store is not recognized as a component of a Zarr hierarchy.

--- 2025025 ---
  canopy_01: 17280 epochs x 277 sids
  reference_01_canopy_01: 17280 epochs x 277 sids
  VOD canopy_01_vs_reference_01: 1051482/4786560 valid (22%)  0.2s
  pipeline=30.6s  vod=0.2s  vod_store=0.3s  day=31.2s
ℹ Using ESA FTP exclusively
  To enable NASA CDDIS fallback, set nasa_earthdata_acc_mail in config/processing.yaml
File /Volumes/ExtremePro/Daily_data/01_SP3/COD0MGXFIN_20250260000_01D_05M_ORB.SP3 exists.
ℹ Using ESA FTP exclusively
  To enable NASA CDDIS fallback, set nasa_earthdata_acc_mail in config/processing.yaml
File /Volumes/ExtremePro/Daily_data/02_CLK/COD0MGXFIN_20250260000_01D_30S_CLK.CLK exists.
⠙   canopy_01              ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╸━━━━ 25/28 0:13:00 eta -:--:--
⠙   reference_01_canopy_01 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╸━━━━ 25/28 0:13:00 eta -:--:--/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/zarr/core/group.py:3559: ZarrUserWarning: Object at .DS_Store is not recognized as a component of a Zarr hierarchy.
⠦   canopy_01              ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╸━━━━ 25/28 0:13:00 eta -:--:--
⠦   reference_01_canopy_01 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╸━━━━ 25/28 0:13:00 eta -:--:--/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/xarray/coding/times.py:670: RuntimeWarning: invalid value encountered in cast
⠋   canopy_01              ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╺━━ 26/28 0:13:04 eta -:--:--
⠋   reference_01_canopy_01 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╸━━━━ 25/28 0:13:04 eta -:--:--/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/zarr/core/group.py:3559: ZarrUserWarning: Object at .DS_Store is not recognized as a component of a Zarr hierarchy.

--- 2025026 ---
  canopy_01: 17280 epochs x 277 sids
  reference_01_canopy_01: 17280 epochs x 277 sids
  VOD canopy_01_vs_reference_01: 1044389/4786560 valid (22%)  0.2s
  pipeline=30.1s  vod=0.2s  vod_store=0.3s  day=30.7s
ℹ Using ESA FTP exclusively
  To enable NASA CDDIS fallback, set nasa_earthdata_acc_mail in config/processing.yaml
File /Volumes/ExtremePro/Daily_data/01_SP3/COD0MGXFIN_20250270000_01D_05M_ORB.SP3 exists.
ℹ Using ESA FTP exclusively
  To enable NASA CDDIS fallback, set nasa_earthdata_acc_mail in config/processing.yaml
File /Volumes/ExtremePro/Daily_data/02_CLK/COD0MGXFIN_20250270000_01D_30S_CLK.CLK exists.
⠙   canopy_01              ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╺━━ 26/28 0:13:30 eta -:--:--
⠙   reference_01_canopy_01 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╺━━ 26/28 0:13:30 eta -:--:--/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/zarr/core/group.py:3559: ZarrUserWarning: Object at .DS_Store is not recognized as a component of a Zarr hierarchy.
⠦   canopy_01              ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╸━ 27/28 0:13:34 eta -:--:--
⠦   reference_01_canopy_01 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╺━━ 26/28 0:13:34 eta -:--:--/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/zarr/core/group.py:3559: ZarrUserWarning: Object at .DS_Store is not recognized as a component of a Zarr hierarchy.
⠏   canopy_01              ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╸━ 27/28 0:13:34 eta -:--:--
⠏   reference_01_canopy_01 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╺━━ 26/28 0:13:34 eta -:--:--/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/xarray/coding/times.py:670: RuntimeWarning: invalid value encountered in cast

--- 2025027 ---
  canopy_01: 17280 epochs x 277 sids
  reference_01_canopy_01: 17280 epochs x 277 sids
  VOD canopy_01_vs_reference_01: 1028626/4786560 valid (21%)  0.2s
  pipeline=29.6s  vod=0.2s  vod_store=0.3s  day=30.1s
ℹ Using ESA FTP exclusively
  To enable NASA CDDIS fallback, set nasa_earthdata_acc_mail in config/processing.yaml
File /Volumes/ExtremePro/Daily_data/01_SP3/COD0MGXFIN_20250280000_01D_05M_ORB.SP3 exists.
ℹ Using ESA FTP exclusively
  To enable NASA CDDIS fallback, set nasa_earthdata_acc_mail in config/processing.yaml
File /Volumes/ExtremePro/Daily_data/02_CLK/COD0MGXFIN_20250280000_01D_30S_CLK.CLK exists.
⠴   canopy_01              ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╸━ 27/28 0:14:01 eta -:--:--
⠴   reference_01_canopy_01 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╸━ 27/28 0:14:01 eta -:--:--/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/zarr/core/group.py:3559: ZarrUserWarning: Object at .DS_Store is not recognized as a component of a Zarr hierarchy.
⠧   canopy_01              ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╸━ 27/28 0:14:01 eta -:--:--
⠧   reference_01_canopy_01 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╸━ 27/28 0:14:01 eta -:--:--/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/xarray/coding/times.py:670: RuntimeWarning: invalid value encountered in cast
    canopy_01              ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 28/28 0:14:02 eta 0:00:00
⠴   reference_01_canopy_01 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╸━ 27/28 0:14:04 eta -:--:--/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/zarr/core/group.py:3559: ZarrUserWarning: Object at .DS_Store is not recognized as a component of a Zarr hierarchy.

--- 2025028 ---
  canopy_01: 17280 epochs x 277 sids
  reference_01_canopy_01: 17280 epochs x 277 sids
  VOD canopy_01_vs_reference_01: 1044552/4786560 valid (22%)  0.2s
  pipeline=29.7s  vod=0.2s  vod_store=0.3s  day=30.3s
    canopy_01              ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 28/28 0:14:02 eta 0:00:00
    reference_01_canopy_01 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 28/28 0:14:05 eta 0:00:00

========================================================================
Done  28 days  28 VOD analyses  847s total
========================================================================
➜  canvodpy-perf git:(explore/performance-review) ✗
