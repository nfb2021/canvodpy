# Re-chunk benchmark (2026-07-20)

Follow-up to `dev/perf_fable_vetting_2026_07_20.md`'s finding that
`chunk_strategies.epoch=17280` (one physical Zarr chunk spans a full day)
causes a within-day write-cost ramp: each 15-min file append re-reads/
recompresses/rewrites the same growing chunk.

## Method

Throwaway Icechunk store (not the deployed rosalia store), real write path:
`MyIcechunkStore` + `to_icechunk()`, mirroring `processor.py`'s
`_append_to_icechunk()` call pattern exactly (one session, first file with
`encoding=chunk_encoding_for(ds)`, subsequent files with `append_dim="epoch"`,
one commit at the end). Synthetic data matches the live rosalia schema
(SNR float32, phi/theta float64, sid=277, 96 files/day x 180 epochs/file).
`store.chunk_strategy` set directly per run, bypassing config, to test
candidate `epoch` chunk sizes in isolation. Script:
`/Users/work/.claude/jobs/b17182ce/tmp/bench_rechunk.py` (job-scratch, not
committed).

## Results

| epoch_chunk | files/chunk | total_s/day | first_s | last_s | mean_s | ramp |
|---:|---:|---:|---:|---:|---:|---:|
| 180   | 1  | 1.92  | 0.086 | 0.020 | 0.020 | 0.2x (flat) |
| 2880  | 16 | 4.17  | 0.022 | 0.064 | 0.043 | 3.0x |
| 5760  | 8  | 6.60  | 0.026 | 0.109 | 0.069 | 4.2x |
| 17280 | 96 (current) | 16.74 | 0.042 | 0.308 | 0.174 | 7.4x |

The 17280 row's shape (0.04s -> 0.31s, 7.4x ramp) matches the production
`icechunk.file_append` numbers observed in the 2026-07-19 stress-test run
(0.05-0.3s) closely — confirms the benchmark reproduces the real bottleneck.

**epoch=180 (one physical chunk per file) is ~8.7x faster than the current
17280 config for this isolated write cost, and removes the ramp entirely.**

## Caveats (not measured here)

- Only isolates `to_icechunk()` cost — excludes dedup/batch-check, metadata
  writes, and commit-time manifest work.
- Read-side cost of many small chunks not measured. §35 (`todo_later.md`)
  already flags a *separate* read-side chunk-mismatch warning at the current
  config; smaller physical chunks change that trade further and need their
  own read-side benchmark before committing to an extreme (e.g. 180).
- More physical chunks/day = more chunk files on disk (96x more at epoch=180
  vs today) — inode/object count and long-term storage-listing cost not
  evaluated.
- Single run, one machine, no repeated trials.

## Recommendation

Don't jump straight to epoch=180. **2880 or 5760 is the more defensible
middle ground** (4-8x fewer chunk files than 180, still 2.5-4x faster writes
than today) pending a read-side re-benchmark. Applying this to an existing
store requires `MyIcechunkStore.rechunk_group()` (destructive `mode="w"`
rewrite on a temp branch, promoted after) — never edit `chunk_strategies` in
config alone for a store that already has data; that only affects *new*
groups going forward.
