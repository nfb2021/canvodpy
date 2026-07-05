➜  dev git:(explore/performance-review) ✗ rm -rf /Volumes/ExtremePro/Daily_data/aux_*.zarr && rm -rf /Volumes/ExtremePro/canvod_stores/rosalia && cd
  /Users/work/Developer/GNSS/canvodpy-perf && uv run python -m canvodpy.cli.run --site rosalia --start 2025001 --end 2025028
========================================================================
canvodpy  site=rosalia  2025001 .. 2025028
========================================================================
  started        2026-07-05 16:29:41
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
⠧   canopy_01              ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  0/28 0:00:14 eta -:--:--
⠧   reference_01_canopy_01 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  0/28 0:00:14 eta -:--:--/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/zarr/core/group.py:3559: ZarrUserWarning: Object at .DS_Store is not recognized as a component of a Zarr hierarchy.
⠏   canopy_01              ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  0/28 0:00:15 eta -:--:--
⠏   reference_01_canopy_01 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  0/28 0:00:15 eta -:--:--/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/xarray/coding/times.py:670: RuntimeWarning: invalid value encountered in cast
⠹   canopy_01              ━╺━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  1/28 0:00:16 eta -:--:--
⠹   reference_01_canopy_01 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  0/28 0:00:16 eta -:--:--/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/zarr/core/group.py:3559: ZarrUserWarning: Object at .DS_Store is not recognized as a component of a Zarr hierarchy.
⠼   canopy_01              ━╺━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  1/28 0:00:17 eta -:--:--
⠼   reference_01_canopy_01 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  0/28 0:00:17 eta -:--:--/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/xarray/coding/times.py:670: RuntimeWarning: invalid value encountered in cast

--- 2025001 ---
  canopy_01: 17280 epochs x 277 sids
  reference_01_canopy_01: 17280 epochs x 277 sids
  VOD canopy_01_vs_reference_01: 1050181/4786560 valid (22%)  0.1s
  pipeline=17.9s  vod=0.2s  vod_store=0.1s  day=18.2s
ℹ Using ESA FTP exclusively
  To enable NASA CDDIS fallback, set nasa_earthdata_acc_mail in config/processing.yaml
File /Volumes/ExtremePro/Daily_data/01_SP3/COD0MGXFIN_20250020000_01D_05M_ORB.SP3 exists.
ℹ Using ESA FTP exclusively
  To enable NASA CDDIS fallback, set nasa_earthdata_acc_mail in config/processing.yaml
File /Volumes/ExtremePro/Daily_data/02_CLK/COD0MGXFIN_20250020000_01D_30S_CLK.CLK exists.
⠹   canopy_01              ━╺━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  1/28 0:00:31 eta -:--:--
⠹   reference_01_canopy_01 ━╺━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  1/28 0:00:31 eta -:--:--/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/zarr/core/group.py:3559: ZarrUserWarning: Object at .DS_Store is not recognized as a component of a Zarr hierarchy.
⠋   canopy_01              ━━╸━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  2/28 0:00:35 eta 0:07:02
⠋   reference_01_canopy_01 ━╺━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  1/28 0:00:35 eta -:--:--/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/zarr/core/group.py:3559: ZarrUserWarning: Object at .DS_Store is not recognized as a component of a Zarr hierarchy.
⠙   canopy_01              ━━╸━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  2/28 0:00:35 eta 0:07:02
⠙   reference_01_canopy_01 ━╺━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  1/28 0:00:35 eta -:--:--/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/xarray/coding/times.py:670: RuntimeWarning: invalid value encountered in cast

--- 2025002 ---
  canopy_01: 17280 epochs x 277 sids
  reference_01_canopy_01: 17280 epochs x 277 sids
  VOD canopy_01_vs_reference_01: 1062680/4786560 valid (22%)  0.1s
  pipeline=17.9s  vod=0.1s  vod_store=0.1s  day=18.2s
ℹ Using ESA FTP exclusively
  To enable NASA CDDIS fallback, set nasa_earthdata_acc_mail in config/processing.yaml
File /Volumes/ExtremePro/Daily_data/01_SP3/COD0MGXFIN_20250030000_01D_05M_ORB.SP3 exists.
ℹ Using ESA FTP exclusively
  To enable NASA CDDIS fallback, set nasa_earthdata_acc_mail in config/processing.yaml
File /Volumes/ExtremePro/Daily_data/02_CLK/COD0MGXFIN_20250030000_01D_30S_CLK.CLK exists.
⠴   canopy_01              ━━╸━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  2/28 0:00:48 eta 0:07:02
⠴   reference_01_canopy_01 ━━╸━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  2/28 0:00:48 eta 0:07:56/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/zarr/core/group.py:3559: ZarrUserWarning: Object at .DS_Store is not recognized as a component of a Zarr hierarchy.
⠦   canopy_01              ━━━━╺━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  3/28 0:00:52 eta 0:07:05
⠦   reference_01_canopy_01 ━━╸━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  2/28 0:00:52 eta 0:07:56/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/zarr/core/group.py:3559: ZarrUserWarning: Object at .DS_Store is not recognized as a component of a Zarr hierarchy.
⠇   canopy_01              ━━━━╺━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  3/28 0:00:52 eta 0:07:05
⠇   reference_01_canopy_01 ━━╸━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  2/28 0:00:52 eta 0:07:56/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/xarray/coding/times.py:670: RuntimeWarning: invalid value encountered in cast

--- 2025003 ---
  canopy_01: 17280 epochs x 277 sids
  reference_01_canopy_01: 17280 epochs x 277 sids
  VOD canopy_01_vs_reference_01: 998503/4786560 valid (21%)  0.1s
  pipeline=16.9s  vod=0.1s  vod_store=0.1s  day=17.2s
ℹ Using ESA FTP exclusively
  To enable NASA CDDIS fallback, set nasa_earthdata_acc_mail in config/processing.yaml
File /Volumes/ExtremePro/Daily_data/01_SP3/COD0MGXFIN_20250040000_01D_05M_ORB.SP3 exists.
ℹ Using ESA FTP exclusively
  To enable NASA CDDIS fallback, set nasa_earthdata_acc_mail in config/processing.yaml
File /Volumes/ExtremePro/Daily_data/02_CLK/COD0MGXFIN_20250040000_01D_30S_CLK.CLK exists.
⠏   canopy_01              ━━━━╺━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  3/28 0:01:05 eta 0:07:05
⠏   reference_01_canopy_01 ━━━━╺━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  3/28 0:01:05 eta 0:07:11/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/zarr/core/group.py:3559: ZarrUserWarning: Object at .DS_Store is not recognized as a component of a Zarr hierarchy.
⠧   canopy_01              ━━━━━╸━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  4/28 0:01:09 eta 0:06:50
⠧   reference_01_canopy_01 ━━━━╺━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  3/28 0:01:09 eta 0:07:11/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/zarr/core/group.py:3559: ZarrUserWarning: Object at .DS_Store is not recognized as a component of a Zarr hierarchy.
⠋   canopy_01              ━━━━━╸━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  4/28 0:01:09 eta 0:06:50
⠋   reference_01_canopy_01 ━━━━╺━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  3/28 0:01:09 eta 0:07:11/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/xarray/coding/times.py:670: RuntimeWarning: invalid value encountered in cast

--- 2025004 ---
  canopy_01: 17280 epochs x 277 sids
  reference_01_canopy_01: 17280 epochs x 277 sids
  VOD canopy_01_vs_reference_01: 1029374/4786560 valid (22%)  0.1s
  pipeline=16.8s  vod=0.1s  vod_store=0.1s  day=17.0s
ℹ Using ESA FTP exclusively
  To enable NASA CDDIS fallback, set nasa_earthdata_acc_mail in config/processing.yaml
File /Volumes/ExtremePro/Daily_data/01_SP3/COD0MGXFIN_20250050000_01D_05M_ORB.SP3 exists.
ℹ Using ESA FTP exclusively
  To enable NASA CDDIS fallback, set nasa_earthdata_acc_mail in config/processing.yaml
File /Volumes/ExtremePro/Daily_data/02_CLK/COD0MGXFIN_20250050000_01D_30S_CLK.CLK exists.
⠦   canopy_01              ━━━━━╸━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  4/28 0:01:22 eta 0:06:50
⠦   reference_01_canopy_01 ━━━━━╸━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  4/28 0:01:22 eta 0:06:48/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/zarr/core/group.py:3559: ZarrUserWarning: Object at .DS_Store is not recognized as a component of a Zarr hierarchy.
⠴   canopy_01              ━━━━━━━╺━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  5/28 0:01:26 eta 0:06:42
⠴   reference_01_canopy_01 ━━━━━╸━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  4/28 0:01:26 eta 0:06:48/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/zarr/core/group.py:3559: ZarrUserWarning: Object at .DS_Store is not recognized as a component of a Zarr hierarchy.
⠇   canopy_01              ━━━━━━━╺━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  5/28 0:01:27 eta 0:06:42
⠇   reference_01_canopy_01 ━━━━━╸━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  4/28 0:01:27 eta 0:06:48/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/xarray/coding/times.py:670: RuntimeWarning: invalid value encountered in cast

--- 2025005 ---
  canopy_01: 17280 epochs x 277 sids
  reference_01_canopy_01: 17280 epochs x 277 sids
  VOD canopy_01_vs_reference_01: 1061584/4786560 valid (22%)  0.1s
  pipeline=17.1s  vod=0.1s  vod_store=0.1s  day=17.3s
ℹ Using ESA FTP exclusively
  To enable NASA CDDIS fallback, set nasa_earthdata_acc_mail in config/processing.yaml
File /Volumes/ExtremePro/Daily_data/01_SP3/COD0MGXFIN_20250060000_01D_05M_ORB.SP3 exists.
ℹ Using ESA FTP exclusively
  To enable NASA CDDIS fallback, set nasa_earthdata_acc_mail in config/processing.yaml
File /Volumes/ExtremePro/Daily_data/02_CLK/COD0MGXFIN_20250060000_01D_30S_CLK.CLK exists.
⠹   canopy_01              ━━━━━━━╺━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  5/28 0:01:40 eta 0:06:42
⠹   reference_01_canopy_01 ━━━━━━━╺━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  5/28 0:01:40 eta 0:06:39/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/zarr/core/group.py:3559: ZarrUserWarning: Object at .DS_Store is not recognized as a component of a Zarr hierarchy.
⠏   canopy_01              ━━━━━━━━╸━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  6/28 0:01:43 eta 0:06:21
⠏   reference_01_canopy_01 ━━━━━━━╺━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  5/28 0:01:43 eta 0:06:39/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/zarr/core/group.py:3559: ZarrUserWarning: Object at .DS_Store is not recognized as a component of a Zarr hierarchy.
⠙   canopy_01              ━━━━━━━━╸━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  6/28 0:01:44 eta 0:06:21
⠙   reference_01_canopy_01 ━━━━━━━╺━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  5/28 0:01:44 eta 0:06:39/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/xarray/coding/times.py:670: RuntimeWarning: invalid value encountered in cast

--- 2025006 ---
  canopy_01: 17280 epochs x 277 sids
  reference_01_canopy_01: 17280 epochs x 277 sids
  VOD canopy_01_vs_reference_01: 1043095/4786560 valid (22%)  0.1s
  pipeline=16.9s  vod=0.1s  vod_store=0.1s  day=17.2s
ℹ Using ESA FTP exclusively
  To enable NASA CDDIS fallback, set nasa_earthdata_acc_mail in config/processing.yaml
File /Volumes/ExtremePro/Daily_data/01_SP3/COD0MGXFIN_20250070000_01D_05M_ORB.SP3 exists.
ℹ Using ESA FTP exclusively
  To enable NASA CDDIS fallback, set nasa_earthdata_acc_mail in config/processing.yaml
File /Volumes/ExtremePro/Daily_data/02_CLK/COD0MGXFIN_20250070000_01D_30S_CLK.CLK exists.
⠸   canopy_01              ━━━━━━━━╸━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  6/28 0:01:57 eta 0:06:21
⠸   reference_01_canopy_01 ━━━━━━━━╸━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  6/28 0:01:57 eta 0:06:18/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/zarr/core/group.py:3559: ZarrUserWarning: Object at .DS_Store is not recognized as a component of a Zarr hierarchy.
⠹   canopy_01              ━━━━━━━━━━╺━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  7/28 0:02:00 eta 0:05:53
⠹   reference_01_canopy_01 ━━━━━━━━╸━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  6/28 0:02:00 eta 0:06:18/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/zarr/core/group.py:3559: ZarrUserWarning: Object at .DS_Store is not recognized as a component of a Zarr hierarchy.
⠼   canopy_01              ━━━━━━━━━━╺━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  7/28 0:02:01 eta 0:05:53
⠼   reference_01_canopy_01 ━━━━━━━━╸━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  6/28 0:02:01 eta 0:06:18/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/xarray/coding/times.py:670: RuntimeWarning: invalid value encountered in cast

--- 2025007 ---
  canopy_01: 17280 epochs x 277 sids
  reference_01_canopy_01: 17280 epochs x 277 sids
  VOD canopy_01_vs_reference_01: 1027281/4786560 valid (21%)  0.1s
  pipeline=16.8s  vod=0.1s  vod_store=0.1s  day=17.0s
ℹ Using ESA FTP exclusively
  To enable NASA CDDIS fallback, set nasa_earthdata_acc_mail in config/processing.yaml
File /Volumes/ExtremePro/Daily_data/01_SP3/COD0MGXFIN_20250080000_01D_05M_ORB.SP3 exists.
ℹ Using ESA FTP exclusively
  To enable NASA CDDIS fallback, set nasa_earthdata_acc_mail in config/processing.yaml
File /Volumes/ExtremePro/Daily_data/02_CLK/COD0MGXFIN_20250080000_01D_30S_CLK.CLK exists.
⠧   canopy_01              ━━━━━━━━━━╺━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  7/28 0:02:14 eta 0:05:53
⠧   reference_01_canopy_01 ━━━━━━━━━━╺━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  7/28 0:02:14 eta 0:05:58/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/zarr/core/group.py:3559: ZarrUserWarning: Object at .DS_Store is not recognized as a component of a Zarr hierarchy.
⠹   canopy_01              ━━━━━━━━━━━╺━━━━━━━━━━━━━━━━━━━━━━━━━━━━  8/28 0:02:17 eta 0:05:44
⠹   reference_01_canopy_01 ━━━━━━━━━━╺━━━━━━━━━━━━━━━━━━━━━━━━━━━━━  7/28 0:02:17 eta 0:05:58/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/zarr/core/group.py:3559: ZarrUserWarning: Object at .DS_Store is not recognized as a component of a Zarr hierarchy.

--- 2025008 ---
  canopy_01: 17280 epochs x 277 sids
  reference_01_canopy_01: 17280 epochs x 277 sids
  VOD canopy_01_vs_reference_01: 1034184/4786560 valid (22%)  0.1s
  pipeline=16.6s  vod=0.1s  vod_store=0.1s  day=16.9s
ℹ Using ESA FTP exclusively
  To enable NASA CDDIS fallback, set nasa_earthdata_acc_mail in config/processing.yaml
File /Volumes/ExtremePro/Daily_data/01_SP3/COD0MGXFIN_20250090000_01D_05M_ORB.SP3 exists.
ℹ Using ESA FTP exclusively
  To enable NASA CDDIS fallback, set nasa_earthdata_acc_mail in config/processing.yaml
File /Volumes/ExtremePro/Daily_data/02_CLK/COD0MGXFIN_20250090000_01D_30S_CLK.CLK exists.
⠦   canopy_01              ━━━━━━━━━━━╺━━━━━━━━━━━━━━━━━━━━━━━━━━━━  8/28 0:02:30 eta 0:05:44
⠦   reference_01_canopy_01 ━━━━━━━━━━━╺━━━━━━━━━━━━━━━━━━━━━━━━━━━━  8/28 0:02:30 eta 0:05:38/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/zarr/core/group.py:3559: ZarrUserWarning: Object at .DS_Store is not recognized as a component of a Zarr hierarchy.
⠹   canopy_01              ━━━━━━━━━━━━╸━━━━━━━━━━━━━━━━━━━━━━━━━━━  9/28 0:02:34 eta 0:05:18
⠹   reference_01_canopy_01 ━━━━━━━━━━━╺━━━━━━━━━━━━━━━━━━━━━━━━━━━━  8/28 0:02:34 eta 0:05:38/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/zarr/core/group.py:3559: ZarrUserWarning: Object at .DS_Store is not recognized as a component of a Zarr hierarchy.
⠸   canopy_01              ━━━━━━━━━━━━╸━━━━━━━━━━━━━━━━━━━━━━━━━━━  9/28 0:02:34 eta 0:05:18
⠸   reference_01_canopy_01 ━━━━━━━━━━━╺━━━━━━━━━━━━━━━━━━━━━━━━━━━━  8/28 0:02:34 eta 0:05:38/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/xarray/coding/times.py:670: RuntimeWarning: invalid value encountered in cast
  flat_num = flat_num.astype(np.int64)
/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/xarray/coding/times.py:670: RuntimeWarning: invalid value encountered in cast

--- 2025009 ---
  canopy_01: 17280 epochs x 277 sids
  reference_01_canopy_01: 17280 epochs x 277 sids
  VOD canopy_01_vs_reference_01: 1021338/4786560 valid (21%)  0.1s
  pipeline=16.5s  vod=0.1s  vod_store=0.1s  day=16.7s
ℹ Using ESA FTP exclusively
  To enable NASA CDDIS fallback, set nasa_earthdata_acc_mail in config/processing.yaml
File /Volumes/ExtremePro/Daily_data/01_SP3/COD0MGXFIN_20250100000_01D_05M_ORB.SP3 exists.
ℹ Using ESA FTP exclusively
  To enable NASA CDDIS fallback, set nasa_earthdata_acc_mail in config/processing.yaml
File /Volumes/ExtremePro/Daily_data/02_CLK/COD0MGXFIN_20250100000_01D_30S_CLK.CLK exists.
⠏   canopy_01              ━━━━━━━━━━━━╸━━━━━━━━━━━━━━━━━━━━━━━━━━━  9/28 0:02:47 eta 0:05:18
⠏   reference_01_canopy_01 ━━━━━━━━━━━━╸━━━━━━━━━━━━━━━━━━━━━━━━━━━  9/28 0:02:47 eta 0:05:18/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/zarr/core/group.py:3559: ZarrUserWarning: Object at .DS_Store is not recognized as a component of a Zarr hierarchy.
⠏   canopy_01              ━━━━━━━━━━━━━━╺━━━━━━━━━━━━━━━━━━━━━━━━━ 10/28 0:02:51 eta 0:04:54
⠏   reference_01_canopy_01 ━━━━━━━━━━━━╸━━━━━━━━━━━━━━━━━━━━━━━━━━━  9/28 0:02:51 eta 0:05:18/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/zarr/core/group.py:3559: ZarrUserWarning: Object at .DS_Store is not recognized as a component of a Zarr hierarchy.
⠹   canopy_01              ━━━━━━━━━━━━━━╺━━━━━━━━━━━━━━━━━━━━━━━━━ 10/28 0:02:51 eta 0:04:54
⠹   reference_01_canopy_01 ━━━━━━━━━━━━╸━━━━━━━━━━━━━━━━━━━━━━━━━━━  9/28 0:02:51 eta 0:05:18/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/xarray/coding/times.py:670: RuntimeWarning: invalid value encountered in cast

--- 2025010 ---
  canopy_01: 17280 epochs x 277 sids
  reference_01_canopy_01: 17280 epochs x 277 sids
  VOD canopy_01_vs_reference_01: 992766/4786560 valid (21%)  0.1s
  pipeline=16.3s  vod=0.1s  vod_store=0.1s  day=16.6s
ℹ Using ESA FTP exclusively
  To enable NASA CDDIS fallback, set nasa_earthdata_acc_mail in config/processing.yaml
File /Volumes/ExtremePro/Daily_data/01_SP3/COD0MGXFIN_20250110000_01D_05M_ORB.SP3 exists.
ℹ Using ESA FTP exclusively
  To enable NASA CDDIS fallback, set nasa_earthdata_acc_mail in config/processing.yaml
File /Volumes/ExtremePro/Daily_data/02_CLK/COD0MGXFIN_20250110000_01D_30S_CLK.CLK exists.
⠦   canopy_01              ━━━━━━━━━━━━━━╺━━━━━━━━━━━━━━━━━━━━━━━━━ 10/28 0:03:03 eta 0:04:54
⠦   reference_01_canopy_01 ━━━━━━━━━━━━━━╺━━━━━━━━━━━━━━━━━━━━━━━━━ 10/28 0:03:03 eta 0:04:59/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/zarr/core/group.py:3559: ZarrUserWarning: Object at .DS_Store is not recognized as a component of a Zarr hierarchy.
⠦   canopy_01              ━━━━━━━━━━━━━━━╸━━━━━━━━━━━━━━━━━━━━━━━━ 11/28 0:03:07 eta 0:04:41
⠦   reference_01_canopy_01 ━━━━━━━━━━━━━━╺━━━━━━━━━━━━━━━━━━━━━━━━━ 10/28 0:03:07 eta 0:04:59/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/zarr/core/group.py:3559: ZarrUserWarning: Object at .DS_Store is not recognized as a component of a Zarr hierarchy.

--- 2025011 ---
  canopy_01: 17280 epochs x 277 sids
  reference_01_canopy_01: 17280 epochs x 277 sids
  VOD canopy_01_vs_reference_01: 989893/4786560 valid (21%)  0.1s
  pipeline=16.4s  vod=0.1s  vod_store=0.1s  day=16.6s
ℹ Using ESA FTP exclusively
  To enable NASA CDDIS fallback, set nasa_earthdata_acc_mail in config/processing.yaml
File /Volumes/ExtremePro/Daily_data/01_SP3/COD0MGXFIN_20250120000_01D_05M_ORB.SP3 exists.
ℹ Using ESA FTP exclusively
  To enable NASA CDDIS fallback, set nasa_earthdata_acc_mail in config/processing.yaml
File /Volumes/ExtremePro/Daily_data/02_CLK/COD0MGXFIN_20250120000_01D_30S_CLK.CLK exists.
⠧   canopy_01              ━━━━━━━━━━━━━━━╸━━━━━━━━━━━━━━━━━━━━━━━━ 11/28 0:03:20 eta 0:04:41
⠧   reference_01_canopy_01 ━━━━━━━━━━━━━━━╸━━━━━━━━━━━━━━━━━━━━━━━━ 11/28 0:03:20 eta 0:04:43/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/zarr/core/group.py:3559: ZarrUserWarning: Object at .DS_Store is not recognized as a component of a Zarr hierarchy.
⠴   canopy_01              ━━━━━━━━━━━━━━━━━╺━━━━━━━━━━━━━━━━━━━━━━ 12/28 0:03:24 eta 0:04:31
⠴   reference_01_canopy_01 ━━━━━━━━━━━━━━━╸━━━━━━━━━━━━━━━━━━━━━━━━ 11/28 0:03:24 eta 0:04:43/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/zarr/core/group.py:3559: ZarrUserWarning: Object at .DS_Store is not recognized as a component of a Zarr hierarchy.
⠧   canopy_01              ━━━━━━━━━━━━━━━━━╺━━━━━━━━━━━━━━━━━━━━━━ 12/28 0:03:24 eta 0:04:31
⠧   reference_01_canopy_01 ━━━━━━━━━━━━━━━╸━━━━━━━━━━━━━━━━━━━━━━━━ 11/28 0:03:24 eta 0:04:43/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/xarray/coding/times.py:670: RuntimeWarning: invalid value encountered in cast
  flat_num = flat_num.astype(np.int64)
/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/xarray/coding/times.py:670: RuntimeWarning: invalid value encountered in cast

--- 2025012 ---
  canopy_01: 17280 epochs x 277 sids
  reference_01_canopy_01: 17280 epochs x 277 sids
  VOD canopy_01_vs_reference_01: 1010873/4786560 valid (21%)  0.1s
  pipeline=16.4s  vod=0.1s  vod_store=0.1s  day=16.7s
ℹ Using ESA FTP exclusively
  To enable NASA CDDIS fallback, set nasa_earthdata_acc_mail in config/processing.yaml
File /Volumes/ExtremePro/Daily_data/01_SP3/COD0MGXFIN_20250130000_01D_05M_ORB.SP3 exists.
ℹ Using ESA FTP exclusively
  To enable NASA CDDIS fallback, set nasa_earthdata_acc_mail in config/processing.yaml
File /Volumes/ExtremePro/Daily_data/02_CLK/COD0MGXFIN_20250130000_01D_30S_CLK.CLK exists.
⠦   canopy_01              ━━━━━━━━━━━━━━━━━╺━━━━━━━━━━━━━━━━━━━━━━ 12/28 0:03:38 eta 0:04:31
⠦   reference_01_canopy_01 ━━━━━━━━━━━━━━━━━╺━━━━━━━━━━━━━━━━━━━━━━ 12/28 0:03:38 eta 0:04:27/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/zarr/core/group.py:3559: ZarrUserWarning: Object at .DS_Store is not recognized as a component of a Zarr hierarchy.
⠋   canopy_01              ━━━━━━━━━━━━━━━━━━╸━━━━━━━━━━━━━━━━━━━━━ 13/28 0:03:41 eta 0:04:23
⠋   reference_01_canopy_01 ━━━━━━━━━━━━━━━━━╺━━━━━━━━━━━━━━━━━━━━━━ 12/28 0:03:41 eta 0:04:27/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/zarr/core/group.py:3559: ZarrUserWarning: Object at .DS_Store is not recognized as a component of a Zarr hierarchy.
⠸   canopy_01              ━━━━━━━━━━━━━━━━━━╸━━━━━━━━━━━━━━━━━━━━━ 13/28 0:03:41 eta 0:04:23
⠸   reference_01_canopy_01 ━━━━━━━━━━━━━━━━━╺━━━━━━━━━━━━━━━━━━━━━━ 12/28 0:03:41 eta 0:04:27/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/xarray/coding/times.py:670: RuntimeWarning: invalid value encountered in cast

--- 2025013 ---
  canopy_01: 17280 epochs x 277 sids
  reference_01_canopy_01: 17280 epochs x 277 sids
  VOD canopy_01_vs_reference_01: 1060962/4786560 valid (22%)  0.1s
  pipeline=17.0s  vod=0.1s  vod_store=0.1s  day=17.2s
ℹ Using ESA FTP exclusively
  To enable NASA CDDIS fallback, set nasa_earthdata_acc_mail in config/processing.yaml
File /Volumes/ExtremePro/Daily_data/01_SP3/COD0MGXFIN_20250140000_01D_05M_ORB.SP3 exists.
ℹ Using ESA FTP exclusively
  To enable NASA CDDIS fallback, set nasa_earthdata_acc_mail in config/processing.yaml
File /Volumes/ExtremePro/Daily_data/02_CLK/COD0MGXFIN_20250140000_01D_30S_CLK.CLK exists.
⠹   canopy_01              ━━━━━━━━━━━━━━━━━━╸━━━━━━━━━━━━━━━━━━━━━ 13/28 0:03:55 eta 0:04:23
⠹   reference_01_canopy_01 ━━━━━━━━━━━━━━━━━━╸━━━━━━━━━━━━━━━━━━━━━ 13/28 0:03:55 eta 0:04:19/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/zarr/core/group.py:3559: ZarrUserWarning: Object at .DS_Store is not recognized as a component of a Zarr hierarchy.
⠇   canopy_01              ━━━━━━━━━━━━━━━━━━━━╺━━━━━━━━━━━━━━━━━━━ 14/28 0:03:59 eta 0:04:03
⠇   reference_01_canopy_01 ━━━━━━━━━━━━━━━━━━╸━━━━━━━━━━━━━━━━━━━━━ 13/28 0:03:59 eta 0:04:19/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/zarr/core/group.py:3559: ZarrUserWarning: Object at .DS_Store is not recognized as a component of a Zarr hierarchy.
⠹   canopy_01              ━━━━━━━━━━━━━━━━━━━━╺━━━━━━━━━━━━━━━━━━━ 14/28 0:03:59 eta 0:04:03
⠹   reference_01_canopy_01 ━━━━━━━━━━━━━━━━━━╸━━━━━━━━━━━━━━━━━━━━━ 13/28 0:03:59 eta 0:04:19/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/xarray/coding/times.py:670: RuntimeWarning: invalid value encountered in cast

--- 2025014 ---
  canopy_01: 17280 epochs x 277 sids
  reference_01_canopy_01: 17266 epochs x 277 sids
  VOD canopy_01_vs_reference_01: 1077595/4782682 valid (23%)  0.1s
  pipeline=17.3s  vod=0.1s  vod_store=0.1s  day=17.5s
ℹ Using ESA FTP exclusively
  To enable NASA CDDIS fallback, set nasa_earthdata_acc_mail in config/processing.yaml
File /Volumes/ExtremePro/Daily_data/01_SP3/COD0MGXFIN_20250150000_01D_05M_ORB.SP3 exists.
ℹ Using ESA FTP exclusively
  To enable NASA CDDIS fallback, set nasa_earthdata_acc_mail in config/processing.yaml
File /Volumes/ExtremePro/Daily_data/02_CLK/COD0MGXFIN_20250150000_01D_30S_CLK.CLK exists.
⠴   canopy_01              ━━━━━━━━━━━━━━━━━━━━╺━━━━━━━━━━━━━━━━━━━ 14/28 0:04:12 eta 0:04:03
⠴   reference_01_canopy_01 ━━━━━━━━━━━━━━━━━━━━╺━━━━━━━━━━━━━━━━━━━ 14/28 0:04:12 eta 0:04:06/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/zarr/core/group.py:3559: ZarrUserWarning: Object at .DS_Store is not recognized as a component of a Zarr hierarchy.
⠹   canopy_01              ━━━━━━━━━━━━━━━━━━━━━╺━━━━━━━━━━━━━━━━━━ 15/28 0:04:16 eta 0:03:42
⠹   reference_01_canopy_01 ━━━━━━━━━━━━━━━━━━━━╺━━━━━━━━━━━━━━━━━━━ 14/28 0:04:16 eta 0:04:06/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/zarr/core/group.py:3559: ZarrUserWarning: Object at .DS_Store is not recognized as a component of a Zarr hierarchy.
⠦   canopy_01              ━━━━━━━━━━━━━━━━━━━━━╺━━━━━━━━━━━━━━━━━━ 15/28 0:04:16 eta 0:03:42
⠦   reference_01_canopy_01 ━━━━━━━━━━━━━━━━━━━━╺━━━━━━━━━━━━━━━━━━━ 14/28 0:04:16 eta 0:04:06/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/xarray/coding/times.py:670: RuntimeWarning: invalid value encountered in cast

--- 2025015 ---
  canopy_01: 17280 epochs x 277 sids
  reference_01_canopy_01: 17280 epochs x 277 sids
  VOD canopy_01_vs_reference_01: 1038132/4786560 valid (22%)  0.1s
  pipeline=16.9s  vod=0.1s  vod_store=0.2s  day=17.2s
ℹ Using ESA FTP exclusively
  To enable NASA CDDIS fallback, set nasa_earthdata_acc_mail in config/processing.yaml
File /Volumes/ExtremePro/Daily_data/01_SP3/COD0MGXFIN_20250160000_01D_05M_ORB.SP3 exists.
ℹ Using ESA FTP exclusively
  To enable NASA CDDIS fallback, set nasa_earthdata_acc_mail in config/processing.yaml
File /Volumes/ExtremePro/Daily_data/02_CLK/COD0MGXFIN_20250160000_01D_30S_CLK.CLK exists.
⠸   canopy_01              ━━━━━━━━━━━━━━━━━━━━━╺━━━━━━━━━━━━━━━━━━ 15/28 0:04:29 eta 0:03:42
⠸   reference_01_canopy_01 ━━━━━━━━━━━━━━━━━━━━━╺━━━━━━━━━━━━━━━━━━ 15/28 0:04:29 eta 0:03:43/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/zarr/core/group.py:3559: ZarrUserWarning: Object at .DS_Store is not recognized as a component of a Zarr hierarchy.
⠙   canopy_01              ━━━━━━━━━━━━━━━━━━━━━━╸━━━━━━━━━━━━━━━━━ 16/28 0:04:33 eta 0:03:31
⠙   reference_01_canopy_01 ━━━━━━━━━━━━━━━━━━━━━╺━━━━━━━━━━━━━━━━━━ 15/28 0:04:33 eta 0:03:43/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/zarr/core/group.py:3559: ZarrUserWarning: Object at .DS_Store is not recognized as a component of a Zarr hierarchy.
⠸   canopy_01              ━━━━━━━━━━━━━━━━━━━━━━╸━━━━━━━━━━━━━━━━━ 16/28 0:04:33 eta 0:03:31
⠸   reference_01_canopy_01 ━━━━━━━━━━━━━━━━━━━━━╺━━━━━━━━━━━━━━━━━━ 15/28 0:04:33 eta 0:03:43/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/xarray/coding/times.py:670: RuntimeWarning: invalid value encountered in cast
  flat_num = flat_num.astype(np.int64)
/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/xarray/coding/times.py:670: RuntimeWarning: invalid value encountered in cast
  flat_num = flat_num.astype(np.int64)
/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/xarray/coding/times.py:670: RuntimeWarning: invalid value encountered in cast
⠼   canopy_01              ━━━━━━━━━━━━━━━━━━━━━━╸━━━━━━━━━━━━━━━━━ 16/28 0:04:33 eta 0:03:31
⠼   reference_01_canopy_01 ━━━━━━━━━━━━━━━━━━━━━╺━━━━━━━━━━━━━━━━━━ 15/28 0:04:33 eta 0:03:43/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/xarray/coding/times.py:670: RuntimeWarning: invalid value encountered in cast

--- 2025016 ---
  canopy_01: 17280 epochs x 277 sids
  reference_01_canopy_01: 17280 epochs x 277 sids
  VOD canopy_01_vs_reference_01: 1068911/4786560 valid (22%)  0.1s
  pipeline=17.0s  vod=0.1s  vod_store=0.2s  day=17.4s
ℹ Using ESA FTP exclusively
  To enable NASA CDDIS fallback, set nasa_earthdata_acc_mail in config/processing.yaml
File /Volumes/ExtremePro/Daily_data/01_SP3/COD0MGXFIN_20250170000_01D_05M_ORB.SP3 exists.
ℹ Using ESA FTP exclusively
  To enable NASA CDDIS fallback, set nasa_earthdata_acc_mail in config/processing.yaml
File /Volumes/ExtremePro/Daily_data/02_CLK/COD0MGXFIN_20250170000_01D_30S_CLK.CLK exists.
⠴   canopy_01              ━━━━━━━━━━━━━━━━━━━━━━╸━━━━━━━━━━━━━━━━━ 16/28 0:04:47 eta 0:03:31
⠴   reference_01_canopy_01 ━━━━━━━━━━━━━━━━━━━━━━╸━━━━━━━━━━━━━━━━━ 16/28 0:04:47 eta 0:03:29/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/zarr/core/group.py:3559: ZarrUserWarning: Object at .DS_Store is not recognized as a component of a Zarr hierarchy.
⠦   canopy_01              ━━━━━━━━━━━━━━━━━━━━━━━━╺━━━━━━━━━━━━━━━ 17/28 0:04:51 eta 0:03:15
⠦   reference_01_canopy_01 ━━━━━━━━━━━━━━━━━━━━━━╸━━━━━━━━━━━━━━━━━ 16/28 0:04:51 eta 0:03:29/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/zarr/core/group.py:3559: ZarrUserWarning: Object at .DS_Store is not recognized as a component of a Zarr hierarchy.
⠧   canopy_01              ━━━━━━━━━━━━━━━━━━━━━━━━╺━━━━━━━━━━━━━━━ 17/28 0:04:51 eta 0:03:15
⠧   reference_01_canopy_01 ━━━━━━━━━━━━━━━━━━━━━━╸━━━━━━━━━━━━━━━━━ 16/28 0:04:51 eta 0:03:29/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/xarray/coding/times.py:670: RuntimeWarning: invalid value encountered in cast
⠏   canopy_01              ━━━━━━━━━━━━━━━━━━━━━━━━╺━━━━━━━━━━━━━━━ 17/28 0:04:51 eta 0:03:15
⠏   reference_01_canopy_01 ━━━━━━━━━━━━━━━━━━━━━━╸━━━━━━━━━━━━━━━━━ 16/28 0:04:51 eta 0:03:29/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/xarray/coding/times.py:670: RuntimeWarning: invalid value encountered in cast

--- 2025017 ---
  canopy_01: 17280 epochs x 277 sids
  reference_01_canopy_01: 17280 epochs x 277 sids
  VOD canopy_01_vs_reference_01: 1044326/4786560 valid (22%)  0.1s
  pipeline=17.7s  vod=0.1s  vod_store=0.2s  day=18.0s
ℹ Using ESA FTP exclusively
  To enable NASA CDDIS fallback, set nasa_earthdata_acc_mail in config/processing.yaml
File /Volumes/ExtremePro/Daily_data/01_SP3/COD0MGXFIN_20250180000_01D_05M_ORB.SP3 exists.
ℹ Using ESA FTP exclusively
  To enable NASA CDDIS fallback, set nasa_earthdata_acc_mail in config/processing.yaml
File /Volumes/ExtremePro/Daily_data/02_CLK/COD0MGXFIN_20250180000_01D_30S_CLK.CLK exists.
⠼   canopy_01              ━━━━━━━━━━━━━━━━━━━━━━━━╺━━━━━━━━━━━━━━━ 17/28 0:05:05 eta 0:03:15
⠼   reference_01_canopy_01 ━━━━━━━━━━━━━━━━━━━━━━━━╺━━━━━━━━━━━━━━━ 17/28 0:05:05 eta 0:03:19/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/zarr/core/group.py:3559: ZarrUserWarning: Object at .DS_Store is not recognized as a component of a Zarr hierarchy.
⠦   canopy_01              ━━━━━━━━━━━━━━━━━━━━━━━━━╸━━━━━━━━━━━━━━ 18/28 0:05:10 eta 0:03:05
⠦   reference_01_canopy_01 ━━━━━━━━━━━━━━━━━━━━━━━━╺━━━━━━━━━━━━━━━ 17/28 0:05:10 eta 0:03:19/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/zarr/core/group.py:3559: ZarrUserWarning: Object at .DS_Store is not recognized as a component of a Zarr hierarchy.
⠏   canopy_01              ━━━━━━━━━━━━━━━━━━━━━━━━━╸━━━━━━━━━━━━━━ 18/28 0:05:10 eta 0:03:05
⠏   reference_01_canopy_01 ━━━━━━━━━━━━━━━━━━━━━━━━╺━━━━━━━━━━━━━━━ 17/28 0:05:10 eta 0:03:19/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/xarray/coding/times.py:670: RuntimeWarning: invalid value encountered in cast

--- 2025018 ---
  canopy_01: 17280 epochs x 277 sids
  reference_01_canopy_01: 17280 epochs x 277 sids
  VOD canopy_01_vs_reference_01: 1056029/4786560 valid (22%)  0.1s
  pipeline=18.2s  vod=0.1s  vod_store=0.3s  day=18.6s
ℹ Using ESA FTP exclusively
  To enable NASA CDDIS fallback, set nasa_earthdata_acc_mail in config/processing.yaml
File /Volumes/ExtremePro/Daily_data/01_SP3/COD0MGXFIN_20250190000_01D_05M_ORB.SP3 exists.
ℹ Using ESA FTP exclusively
  To enable NASA CDDIS fallback, set nasa_earthdata_acc_mail in config/processing.yaml
File /Volumes/ExtremePro/Daily_data/02_CLK/COD0MGXFIN_20250190000_01D_30S_CLK.CLK exists.
⠼   canopy_01              ━━━━━━━━━━━━━━━━━━━━━━━━━╸━━━━━━━━━━━━━━ 18/28 0:05:30 eta 0:03:05
⠼   reference_01_canopy_01 ━━━━━━━━━━━━━━━━━━━━━━━━━╸━━━━━━━━━━━━━━ 18/28 0:05:30 eta 0:03:06/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/zarr/core/group.py:3559: ZarrUserWarning: Object at .DS_Store is not recognized as a component of a Zarr hierarchy.
⠏   canopy_01              ━━━━━━━━━━━━━━━━━━━━━━━━━━━╺━━━━━━━━━━━━ 19/28 0:05:32 eta 0:03:45
⠏   reference_01_canopy_01 ━━━━━━━━━━━━━━━━━━━━━━━━━╸━━━━━━━━━━━━━━ 18/28 0:05:32 eta 0:03:06/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/zarr/core/group.py:3559: ZarrUserWarning: Object at .DS_Store is not recognized as a component of a Zarr hierarchy.
⠹   canopy_01              ━━━━━━━━━━━━━━━━━━━━━━━━━━━╺━━━━━━━━━━━━ 19/28 0:05:33 eta 0:03:45
⠹   reference_01_canopy_01 ━━━━━━━━━━━━━━━━━━━━━━━━━╸━━━━━━━━━━━━━━ 18/28 0:05:33 eta 0:03:06/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/xarray/coding/times.py:670: RuntimeWarning: invalid value encountered in cast

--- 2025019 ---
  canopy_01: 17280 epochs x 277 sids
  reference_01_canopy_01: 17280 epochs x 277 sids
  VOD canopy_01_vs_reference_01: 1087111/4786560 valid (23%)  0.1s
  pipeline=22.2s  vod=0.1s  vod_store=0.2s  day=22.5s
ℹ Using ESA FTP exclusively
  To enable NASA CDDIS fallback, set nasa_earthdata_acc_mail in config/processing.yaml
File /Volumes/ExtremePro/Daily_data/01_SP3/COD0MGXFIN_20250200000_01D_05M_ORB.SP3 exists.
ℹ Using ESA FTP exclusively
  To enable NASA CDDIS fallback, set nasa_earthdata_acc_mail in config/processing.yaml
File /Volumes/ExtremePro/Daily_data/02_CLK/COD0MGXFIN_20250200000_01D_30S_CLK.CLK exists.
⠸   canopy_01              ━━━━━━━━━━━━━━━━━━━━━━━━━━━╺━━━━━━━━━━━━ 19/28 0:05:49 eta 0:03:45
⠸   reference_01_canopy_01 ━━━━━━━━━━━━━━━━━━━━━━━━━━━╺━━━━━━━━━━━━ 19/28 0:05:49 eta 0:03:24/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/zarr/core/group.py:3559: ZarrUserWarning: Object at .DS_Store is not recognized as a component of a Zarr hierarchy.
⠦   canopy_01              ━━━━━━━━━━━━━━━━━━━━━━━━━━━╺━━━━━━━━━━━━ 19/28 0:05:50 eta 0:03:45
⠦   reference_01_canopy_01 ━━━━━━━━━━━━━━━━━━━━━━━━━━━╺━━━━━━━━━━━━ 19/28 0:05:50 eta 0:03:24/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/xarray/coding/times.py:670: RuntimeWarning: invalid value encountered in cast
⠏   canopy_01              ━━━━━━━━━━━━━━━━━━━━━━━━━━━━╸━━━━━━━━━━━ 20/28 0:05:51 eta 0:02:32
⠏   reference_01_canopy_01 ━━━━━━━━━━━━━━━━━━━━━━━━━━━╺━━━━━━━━━━━━ 19/28 0:05:51 eta 0:03:24/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/zarr/core/group.py:3559: ZarrUserWarning: Object at .DS_Store is not recognized as a component of a Zarr hierarchy.
⠋   canopy_01              ━━━━━━━━━━━━━━━━━━━━━━━━━━━━╸━━━━━━━━━━━ 20/28 0:05:52 eta 0:02:32
⠋   reference_01_canopy_01 ━━━━━━━━━━━━━━━━━━━━━━━━━━━╺━━━━━━━━━━━━ 19/28 0:05:52 eta 0:03:24/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/xarray/coding/times.py:670: RuntimeWarning: invalid value encountered in cast

--- 2025020 ---
  canopy_01: 17280 epochs x 277 sids
  reference_01_canopy_01: 17280 epochs x 277 sids
  VOD canopy_01_vs_reference_01: 1064996/4786560 valid (22%)  0.1s
  pipeline=18.7s  vod=0.1s  vod_store=0.2s  day=19.1s
ℹ Using ESA FTP exclusively
  To enable NASA CDDIS fallback, set nasa_earthdata_acc_mail in config/processing.yaml
File /Volumes/ExtremePro/Daily_data/01_SP3/COD0MGXFIN_20250210000_01D_05M_ORB.SP3 exists.
ℹ Using ESA FTP exclusively
  To enable NASA CDDIS fallback, set nasa_earthdata_acc_mail in config/processing.yaml
File /Volumes/ExtremePro/Daily_data/02_CLK/COD0MGXFIN_20250210000_01D_30S_CLK.CLK exists.
⠧   canopy_01              ━━━━━━━━━━━━━━━━━━━━━━━━━━━━╸━━━━━━━━━━━ 20/28 0:06:10 eta 0:02:32
⠧   reference_01_canopy_01 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━╸━━━━━━━━━━━ 20/28 0:06:10 eta 0:02:33/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/zarr/core/group.py:3559: ZarrUserWarning: Object at .DS_Store is not recognized as a component of a Zarr hierarchy.
⠏   canopy_01              ━━━━━━━━━━━━━━━━━━━━━━━━━━━━╸━━━━━━━━━━━ 20/28 0:06:10 eta 0:02:32
⠏   reference_01_canopy_01 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━╸━━━━━━━━━━━ 20/28 0:06:10 eta 0:02:33/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/xarray/coding/times.py:670: RuntimeWarning: invalid value encountered in cast
  flat_num = flat_num.astype(np.int64)
/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/xarray/coding/times.py:670: RuntimeWarning: invalid value encountered in cast
⠙   canopy_01              ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╺━━━━━━━━━ 21/28 0:06:12 eta 0:02:23
⠙   reference_01_canopy_01 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━╸━━━━━━━━━━━ 20/28 0:06:12 eta 0:02:33/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/zarr/core/group.py:3559: ZarrUserWarning: Object at .DS_Store is not recognized as a component of a Zarr hierarchy.
⠸   canopy_01              ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╺━━━━━━━━━ 21/28 0:06:12 eta 0:02:23
⠸   reference_01_canopy_01 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━╸━━━━━━━━━━━ 20/28 0:06:12 eta 0:02:33/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/xarray/coding/times.py:670: RuntimeWarning: invalid value encountered in cast

--- 2025021 ---
  canopy_01: 17280 epochs x 277 sids
  reference_01_canopy_01: 17280 epochs x 277 sids
  VOD canopy_01_vs_reference_01: 1077833/4786560 valid (23%)  0.1s
  pipeline=19.9s  vod=0.1s  vod_store=0.2s  day=20.3s
ℹ Using ESA FTP exclusively
  To enable NASA CDDIS fallback, set nasa_earthdata_acc_mail in config/processing.yaml
File /Volumes/ExtremePro/Daily_data/01_SP3/COD0MGXFIN_20250220000_01D_05M_ORB.SP3 exists.
ℹ Using ESA FTP exclusively
  To enable NASA CDDIS fallback, set nasa_earthdata_acc_mail in config/processing.yaml
File /Volumes/ExtremePro/Daily_data/02_CLK/COD0MGXFIN_20250220000_01D_30S_CLK.CLK exists.
⠇   canopy_01              ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╺━━━━━━━━━ 21/28 0:06:29 eta 0:02:23
⠇   reference_01_canopy_01 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╺━━━━━━━━━ 21/28 0:06:29 eta 0:02:23/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/zarr/core/group.py:3559: ZarrUserWarning: Object at .DS_Store is not recognized as a component of a Zarr hierarchy.
⠋   canopy_01              ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╺━━━━━━━━ 22/28 0:06:31 eta 0:01:56
⠋   reference_01_canopy_01 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╺━━━━━━━━━ 21/28 0:06:31 eta 0:02:23/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/zarr/core/group.py:3559: ZarrUserWarning: Object at .DS_Store is not recognized as a component of a Zarr hierarchy.

--- 2025022 ---
  canopy_01: 17280 epochs x 277 sids
  reference_01_canopy_01: 17280 epochs x 277 sids
  VOD canopy_01_vs_reference_01: 1118509/4786560 valid (23%)  0.1s
  pipeline=18.7s  vod=0.1s  vod_store=0.2s  day=19.1s
ℹ Using ESA FTP exclusively
  To enable NASA CDDIS fallback, set nasa_earthdata_acc_mail in config/processing.yaml
File /Volumes/ExtremePro/Daily_data/01_SP3/COD0MGXFIN_20250230000_01D_05M_ORB.SP3 exists.
ℹ Using ESA FTP exclusively
  To enable NASA CDDIS fallback, set nasa_earthdata_acc_mail in config/processing.yaml
File /Volumes/ExtremePro/Daily_data/02_CLK/COD0MGXFIN_20250230000_01D_30S_CLK.CLK exists.
⠋   canopy_01              ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╺━━━━━━━━ 22/28 0:06:45 eta 0:01:56
⠋   reference_01_canopy_01 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╺━━━━━━━━ 22/28 0:06:45 eta 0:01:55/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/zarr/core/group.py:3559: ZarrUserWarning: Object at .DS_Store is not recognized as a component of a Zarr hierarchy.
⠦   canopy_01              ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╸━━━━━━━ 23/28 0:06:49 eta 0:01:21
⠦   reference_01_canopy_01 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╺━━━━━━━━ 22/28 0:06:49 eta 0:01:55/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/zarr/core/group.py:3559: ZarrUserWarning: Object at .DS_Store is not recognized as a component of a Zarr hierarchy.
⠧   canopy_01              ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╸━━━━━━━ 23/28 0:06:49 eta 0:01:21
⠧   reference_01_canopy_01 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╺━━━━━━━━ 22/28 0:06:49 eta 0:01:55/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/xarray/coding/times.py:670: RuntimeWarning: invalid value encountered in cast

--- 2025023 ---
  canopy_01: 17280 epochs x 277 sids
  reference_01_canopy_01: 17280 epochs x 277 sids
  VOD canopy_01_vs_reference_01: 1065374/4786560 valid (22%)  0.1s
  pipeline=17.7s  vod=0.1s  vod_store=0.2s  day=18.1s
ℹ Using ESA FTP exclusively
  To enable NASA CDDIS fallback, set nasa_earthdata_acc_mail in config/processing.yaml
File /Volumes/ExtremePro/Daily_data/01_SP3/COD0MGXFIN_20250240000_01D_05M_ORB.SP3 exists.
ℹ Using ESA FTP exclusively
  To enable NASA CDDIS fallback, set nasa_earthdata_acc_mail in config/processing.yaml
File /Volumes/ExtremePro/Daily_data/02_CLK/COD0MGXFIN_20250240000_01D_30S_CLK.CLK exists.
⠸   canopy_01              ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╸━━━━━━━ 23/28 0:07:03 eta 0:01:21
⠸   reference_01_canopy_01 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╸━━━━━━━ 23/28 0:07:03 eta 0:01:31/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/zarr/core/group.py:3559: ZarrUserWarning: Object at .DS_Store is not recognized as a component of a Zarr hierarchy.
⠼   canopy_01              ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╺━━━━━ 24/28 0:07:07 eta 0:01:12
⠼   reference_01_canopy_01 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╸━━━━━━━ 23/28 0:07:07 eta 0:01:31/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/zarr/core/group.py:3559: ZarrUserWarning: Object at .DS_Store is not recognized as a component of a Zarr hierarchy.
⠴   canopy_01              ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╺━━━━━ 24/28 0:07:07 eta 0:01:12
⠴   reference_01_canopy_01 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╸━━━━━━━ 23/28 0:07:07 eta 0:01:31/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/xarray/coding/times.py:670: RuntimeWarning: invalid value encountered in cast

--- 2025024 ---
  canopy_01: 17280 epochs x 277 sids
  reference_01_canopy_01: 17280 epochs x 277 sids
  VOD canopy_01_vs_reference_01: 1056198/4786560 valid (22%)  0.1s
  pipeline=17.9s  vod=0.1s  vod_store=0.2s  day=18.2s
ℹ Using ESA FTP exclusively
  To enable NASA CDDIS fallback, set nasa_earthdata_acc_mail in config/processing.yaml
File /Volumes/ExtremePro/Daily_data/01_SP3/COD0MGXFIN_20250250000_01D_05M_ORB.SP3 exists.
ℹ Using ESA FTP exclusively
  To enable NASA CDDIS fallback, set nasa_earthdata_acc_mail in config/processing.yaml
File /Volumes/ExtremePro/Daily_data/02_CLK/COD0MGXFIN_20250250000_01D_30S_CLK.CLK exists.
⠹   canopy_01              ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╺━━━━━ 24/28 0:07:21 eta 0:01:12
⠹   reference_01_canopy_01 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╺━━━━━ 24/28 0:07:21 eta 0:01:13/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/zarr/core/group.py:3559: ZarrUserWarning: Object at .DS_Store is not recognized as a component of a Zarr hierarchy.
⠴   canopy_01              ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╸━━━━ 25/28 0:07:26 eta 0:00:55
⠴   reference_01_canopy_01 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╺━━━━━ 24/28 0:07:26 eta 0:01:13/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/zarr/core/group.py:3559: ZarrUserWarning: Object at .DS_Store is not recognized as a component of a Zarr hierarchy.
⠇   canopy_01              ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╸━━━━ 25/28 0:07:26 eta 0:00:55
⠇   reference_01_canopy_01 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╺━━━━━ 24/28 0:07:26 eta 0:01:13/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/xarray/coding/times.py:670: RuntimeWarning: invalid value encountered in cast

--- 2025025 ---
  canopy_01: 17280 epochs x 277 sids
  reference_01_canopy_01: 17280 epochs x 277 sids
  VOD canopy_01_vs_reference_01: 1051482/4786560 valid (22%)  0.1s
  pipeline=18.2s  vod=0.1s  vod_store=0.2s  day=18.5s
ℹ Using ESA FTP exclusively
  To enable NASA CDDIS fallback, set nasa_earthdata_acc_mail in config/processing.yaml
File /Volumes/ExtremePro/Daily_data/01_SP3/COD0MGXFIN_20250260000_01D_05M_ORB.SP3 exists.
ℹ Using ESA FTP exclusively
  To enable NASA CDDIS fallback, set nasa_earthdata_acc_mail in config/processing.yaml
File /Volumes/ExtremePro/Daily_data/02_CLK/COD0MGXFIN_20250260000_01D_30S_CLK.CLK exists.
⠏   canopy_01              ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╸━━━━ 25/28 0:07:39 eta 0:00:55
⠏   reference_01_canopy_01 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╸━━━━ 25/28 0:07:39 eta 0:00:56/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/zarr/core/group.py:3559: ZarrUserWarning: Object at .DS_Store is not recognized as a component of a Zarr hierarchy.
⠙   canopy_01              ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╺━━ 26/28 0:07:44 eta 0:00:37
⠙   reference_01_canopy_01 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╸━━━━ 25/28 0:07:44 eta 0:00:56/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/zarr/core/group.py:3559: ZarrUserWarning: Object at .DS_Store is not recognized as a component of a Zarr hierarchy.

--- 2025026 ---
  canopy_01: 17280 epochs x 277 sids
  reference_01_canopy_01: 17280 epochs x 277 sids
  VOD canopy_01_vs_reference_01: 1044389/4786560 valid (22%)  0.1s
  pipeline=17.7s  vod=0.1s  vod_store=0.2s  day=18.0s
ℹ Using ESA FTP exclusively
  To enable NASA CDDIS fallback, set nasa_earthdata_acc_mail in config/processing.yaml
File /Volumes/ExtremePro/Daily_data/01_SP3/COD0MGXFIN_20250270000_01D_05M_ORB.SP3 exists.
ℹ Using ESA FTP exclusively
  To enable NASA CDDIS fallback, set nasa_earthdata_acc_mail in config/processing.yaml
File /Volumes/ExtremePro/Daily_data/02_CLK/COD0MGXFIN_20250270000_01D_30S_CLK.CLK exists.
⠸   canopy_01              ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╺━━ 26/28 0:07:57 eta 0:00:37
⠸   reference_01_canopy_01 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╺━━ 26/28 0:07:57 eta 0:00:37/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/zarr/core/group.py:3559: ZarrUserWarning: Object at .DS_Store is not recognized as a component of a Zarr hierarchy.
⠴   canopy_01              ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╸━ 27/28 0:08:02 eta 0:00:18
⠴   reference_01_canopy_01 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╺━━ 26/28 0:08:02 eta 0:00:37/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/zarr/core/group.py:3559: ZarrUserWarning: Object at .DS_Store is not recognized as a component of a Zarr hierarchy.
⠏   canopy_01              ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╸━ 27/28 0:08:02 eta 0:00:18
⠏   reference_01_canopy_01 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╺━━ 26/28 0:08:02 eta 0:00:37/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/xarray/coding/times.py:670: RuntimeWarning: invalid value encountered in cast

--- 2025027 ---
  canopy_01: 17280 epochs x 277 sids
  reference_01_canopy_01: 17280 epochs x 277 sids
  VOD canopy_01_vs_reference_01: 1028626/4786560 valid (21%)  0.1s
  pipeline=17.6s  vod=0.1s  vod_store=0.2s  day=18.0s
ℹ Using ESA FTP exclusively
  To enable NASA CDDIS fallback, set nasa_earthdata_acc_mail in config/processing.yaml
File /Volumes/ExtremePro/Daily_data/01_SP3/COD0MGXFIN_20250280000_01D_05M_ORB.SP3 exists.
ℹ Using ESA FTP exclusively
  To enable NASA CDDIS fallback, set nasa_earthdata_acc_mail in config/processing.yaml
File /Volumes/ExtremePro/Daily_data/02_CLK/COD0MGXFIN_20250280000_01D_30S_CLK.CLK exists.
⠴   canopy_01              ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╸━ 27/28 0:08:15 eta 0:00:18
⠴   reference_01_canopy_01 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╸━ 27/28 0:08:15 eta 0:00:18/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/zarr/core/group.py:3559: ZarrUserWarning: Object at .DS_Store is not recognized as a component of a Zarr hierarchy.
    canopy_01              ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 28/28 0:08:16 eta 0:00:00
⠏   reference_01_canopy_01 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╸━ 27/28 0:08:19 eta 0:00:18/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/zarr/core/group.py:3559: ZarrUserWarning: Object at .DS_Store is not recognized as a component of a Zarr hierarchy.
    canopy_01              ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 28/28 0:08:16 eta 0:00:00
⠹   reference_01_canopy_01 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╸━ 27/28 0:08:20 eta 0:00:18/Users/work/Developer/GNSS/canvodpy-perf/.venv/lib/python3.14/site-packages/xarray/coding/times.py:670: RuntimeWarning: invalid value encountered in cast

--- 2025028 ---
  canopy_01: 17280 epochs x 277 sids
  reference_01_canopy_01: 17280 epochs x 277 sids
  VOD canopy_01_vs_reference_01: 1044552/4786560 valid (22%)  0.1s
  pipeline=17.6s  vod=0.1s  vod_store=0.2s  day=17.9s
    canopy_01              ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 28/28 0:08:16 eta 0:00:00
    reference_01_canopy_01 ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━ 28/28 0:08:20 eta 0:00:00

========================================================================
Done  28 days  28 VOD analyses  501s total
========================================================================
➜  canvodpy-perf git:(explore/performance-review) ✗
