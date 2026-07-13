# Storage Strategies

The write strategy controls how `MyIcechunkStore` handles the time range already in the store. Choose once per store type — set it in `canvod-settings.yaml` under `processing.storage:`.

<div class="grid cards" markdown>

-   :fontawesome-solid-forward-step: &nbsp; **Skip**

    ---

    No-op if any data already exists for the incoming time range.
    Safe for immutable raw observations — never overwrites.

    *Best for: initial ingestion, pipeline restarts*

-   :fontawesome-solid-arrows-rotate: &nbsp; **Overwrite**

    ---

    Deletes existing data for the time range, then writes fresh.
    Each run produces a new Icechunk snapshot for audit.

    *Best for: reprocessed results, algorithm updates*

-   :fontawesome-solid-layer-group: &nbsp; **Append**

    ---

    Merges new data with existing, extending the time series.
    Handles overlapping epochs by keeping existing values.

    *Best for: continuous monitoring, daily live ingestion*

</div>

---

## Behaviour Reference

| Strategy | Data exists | Data missing | Version snapshot | Speed |
|----------|:-----------:|:------------:|:----------------:|:-----:|
| `skip` | No write | Write | On write | Fast |
| `overwrite` | Delete + write | Write | Always | Medium |
| `append` | Merge | Write | Always | Slower |

---

## Usage

=== "Constructor"

    ```python
    from canvod.store import MyIcechunkStore

    # Raw observations — skip if already ingested
    rinex_store = MyIcechunkStore(
        "/data/stores/examplesite/rinex",
        strategy="skip",
    )

    # Processed VOD — rewrite on algorithm update
    vod_store = MyIcechunkStore(
        "/data/stores/examplesite/vod",
        strategy="overwrite",
    )

    # Monitoring — extend daily
    live_store = MyIcechunkStore(
        "/data/stores/live/rinex",
        strategy="append",
    )
    ```

=== "canvod-settings.yaml"

    ```yaml
    processing:
      storage:
      rinex_store_strategy: skip      # raw observations are immutable
      vod_store_strategy: overwrite   # recompute as algorithms improve
    ```

    The `Site` object reads these keys automatically:

    ```python
    from canvod.site import Site
    site = Site("ExampleSite")           # strategy from config
    site.rinex_store.strategy        # → "skip"
    site.vod_store.strategy          # → "overwrite"
    ```

---

## Recommended Defaults

!!! success "Raw RINEX observations → `skip`"
    Raw GNSS data never changes after collection.
    Skip prevents accidental re-ingestion and keeps ingest pipelines
    idempotent — safe to restart at any point.

!!! info "Processed VOD products → `overwrite`"
    As the tau-omega inversion improves or auxiliary data quality changes,
    re-running the pipeline should replace old values.
    Each overwrite creates a new Icechunk snapshot so you can compare
    before/after.

!!! warning "Continuous monitoring → `append`"
    Use `append` only when truly extending a live time series.
    It is slower and may produce unexpected results if a day is
    partially processed and re-submitted.

---

## Performance

| Strategy | Typical write throughput | Storage overhead | Re-ingest safety |
|----------|--------------------------|-----------------|------------------|
| `skip` | Fastest — hash check only | None | Safe |
| `overwrite` | Moderate — delete + write | Low (old chunks GC'd) | Safe |
| `append` | Slowest — read-merge-write | Higher (old + new chunks) | Risky |

!!! tip "Garbage collection"
    Overwritten chunks remain in the Icechunk object store until you run
    GC. The old versions are still accessible via snapshot IDs — useful for
    auditing before cleaning up.
