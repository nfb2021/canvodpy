# Icechunk Configuration Guide

Config lives in `canvod-settings.yaml` under `processing.icechunk:`, backed by
`IcechunkConfig` in `packages/canvod-utils/src/canvod/utils/config/models.py`.
Wired into `MyIcechunkStore.__init__` in `packages/canvod-store/src/canvod/store/store.py`.

---

## Compression

```yaml
icechunk:
  compression_algorithm: zstd   # only valid value in icechunk v2
  compression_level: 3          # 0 = off, 1-22; 3 is fast + good ratio
```

Icechunk v2 dropped lz4 and gzip — only zstd is available. Level 3 is the
icechunk-team recommendation for write-heavy workloads (GNSS ingestion fits
this). Level 1 is ~20% faster with ~5% worse ratio. Level 6 is
Parquet-comparable compression but halves write throughput.

**S3:** no change needed. zstd is also the right call over the wire.

---

## Inline chunk threshold

```yaml
  inline_chunk_threshold_bytes: 512
```

Chunks smaller than this are stored directly inside the manifest (no separate
object). Coordinate arrays (epoch, sid strings) are typically small enough to
be inlined. At 512 bytes, all coordinate chunks go inline; SNR/obs data chunks
are too large and always stored as separate objects.

Raising this puts more data in the manifest, which makes it larger and slower
to fetch — keep at 512.

**S3:** keep at 512. A larger value would bloat the manifest and increase
every cold-start latency with no read benefit.

---

## Concurrency and requests

```yaml
  get_partial_values_concurrency: 1   # concurrent range-request parallelism
  max_concurrent_requests: null       # null = icechunk picks a platform default
```

`get_partial_values_concurrency` controls how many chunk GET requests icechunk
issues in parallel when reading partial arrays (e.g. `ds.sel(epoch=...)`).
At 1, reads are sequential — fine for a local NVMe where syscall overhead
dominates anyway.

`max_concurrent_requests` is a global cap on concurrent object-store
connections per store instance.

**S3:** both of these matter a lot.

```yaml
  get_partial_values_concurrency: 10   # or higher — measure
  max_concurrent_requests: 50          # ~16-32 for standard S3, up to 100 for high-throughput
```

S3 GET latency is ~5-20 ms; parallelism hides it. Start at 10/50 and profile
with `canvod bench read`. Do not exceed ~100 concurrent requests on standard
S3 without checking account-level rate limits.

---

## Chunk cache

```yaml
  cache_num_chunk_refs: null     # null = icechunk default (unlimited)
  cache_num_bytes_chunks: null   # null = icechunk default (unlimited)
```

In-memory LRU caches. `cache_num_chunk_refs` caps the chunk reference index;
`cache_num_bytes_chunks` caps raw decompressed data cached in RAM.

On local FS these are irrelevant — OS page cache does a better job.

**S3:** set both to avoid re-fetching the same chunks in a hot loop.

```yaml
  cache_num_chunk_refs: 500_000    # ~40 MB at 80 bytes/ref
  cache_num_bytes_chunks: 2_000_000_000   # 2 GB; adjust to available RAM
```

For a VOD compute pass that re-reads the same epoch range per site, a warm
chunk cache eliminates redundant S3 GETs. Size `cache_num_bytes_chunks` to
fit the hot working set (one day of SNR for all SIDs at float32 ≈ 321 × 17280
× 4 bytes ≈ 22 MB per receiver group).

---

## Chunk strategies

```yaml
  chunk_strategies:
    gnss_store:
      epoch: 34560   # epochs per chunk along epoch dim
      sid: -1        # -1 = no chunking (entire sid axis in one chunk)
    vod_store:
      epoch: 34560
      sid: -1
```

`epoch: 34560` was chosen as a "one-day-ish" chunk. At 2.5 s cadence this is
exactly 24 h; at 5 s it is 48 h. The point is to keep chunk sizes in the
100 MB–1 GB range per variable so icechunk does not create millions of tiny
objects.

**sid: -1** (no chunking) is deliberate: the SID axis is 321 elements ×
4 bytes × epoch chunk size ≈ fits in one chunk. Splitting the SID axis would
fragment reads when you need all satellites for a time window (the dominant
access pattern).

**S3:** keep `sid: -1`. Consider *lowering* `epoch` if you have many parallel
readers each accessing a short time window — smaller chunks reduce read
amplification. A good rule: `epoch` ≈ 2 × expected query window in epochs.

To change `epoch` for an existing store you must rewrite the store from
scratch (rechunk + new write). Plan this during any migration.

---

## Manifest splitting

```yaml
  manifest_splitting_enabled: true
  manifest_splitting_epoch_range: 34560   # split every N epoch indices
```

Manifests are icechunk's chunk-location index. Without splitting, every
variable's manifest grows proportionally to the number of chunks — for a
year of SNR data at `epoch: 34560` that is ~365 chunks, which is still
manageable. But for long deployments (5+ years) or small chunk sizes, a
single manifest becomes slow to load.

Splitting creates sub-manifests every `manifest_splitting_epoch_range` epoch
indices. The rule applied is: split **any array that has an `epoch`
dimension** at that stride. Arrays without an epoch dim (sid coordinate,
metadata arrays) are unaffected.

`manifest_splitting_epoch_range` should match `chunk_strategies.gnss_store.epoch`
so each sub-manifest covers exactly one chunk. Diverging the two wastes space
or creates over-fragmented sub-manifests.

**S3:** manifest splitting is *more* important on S3 because each manifest
is a separate GET. A split manifest means icechunk only fetches the
sub-manifest covering your query time window instead of the entire history.
Keep enabled; set `manifest_splitting_epoch_range` to match chunk size.

---

## Manifest preloading

```yaml
  manifest_preload_enabled: false      # off by default
  manifest_preload_max_refs: 10_000    # stop preloading after this many refs
  manifest_preload_max_arrays_to_scan: 500
  manifest_preload_pattern: "^(epoch|sid)$"
```

When enabled, icechunk eagerly fetches manifests for arrays whose names match
`manifest_preload_pattern` at store-open time, up to `manifest_preload_max_refs`
total chunk references. This turns random-access reads into one upfront latency
hit instead of many small ones.

`max_arrays_to_scan` limits how many arrays are considered, avoiding pathological
performance on stores with many small variables.

Currently off because local-FS stores don't benefit — the manifest is already
in the OS page cache after first access.

**S3:** consider enabling for read-heavy workflows (VOD compute, viewer).

```yaml
  manifest_preload_enabled: true
  manifest_preload_max_refs: 50_000       # increase for larger stores
  manifest_preload_max_arrays_to_scan: 500
  manifest_preload_pattern: "^(obs|snr|epoch|sid)$"
```

The pattern `^(obs|snr|epoch|sid)$` preloads the four arrays accessed on
every VOD pass. Do not preload everything — that defeats the purpose and
bloats the startup time.

---

## What to touch when migrating to S3

The storage backend (endpoint, bucket, credentials) lives **outside**
`IcechunkConfig` — it is passed to `icechunk.s3_store(...)` or
`icechunk.Repository.open(storage=...)` when constructing the repository.
That wiring is currently not in `IcechunkConfig`; add a `StorageBackendConfig`
section when you get there.

Config knobs to revisit in order of impact:

| Knob | Local default | Recommended S3 starting point |
|---|---|---|
| `max_concurrent_requests` | `null` | `50` |
| `get_partial_values_concurrency` | `1` | `10` |
| `cache_num_bytes_chunks` | `null` | `2_000_000_000` |
| `cache_num_chunk_refs` | `null` | `500_000` |
| `manifest_preload_enabled` | `false` | `true` |
| `manifest_preload_pattern` | `^(epoch|sid)$` | `^(obs|snr|epoch|sid)$` |
| `manifest_preload_max_refs` | `10_000` | `50_000` |
| `chunk_strategies.gnss_store.epoch` | `34560` | profile before changing |
| `compression_level` | `3` | `3` (no change) |
| `inline_chunk_threshold_bytes` | `512` | `512` (no change) |
| `manifest_splitting_enabled` | `true` | `true` (no change) |
| `manifest_splitting_epoch_range` | `34560` | match chunk size (no change) |
