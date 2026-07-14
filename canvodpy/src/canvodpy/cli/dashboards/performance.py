import marimo

__generated_with = "0.23.13"
app = marimo.App(
    width="medium",
    app_title="canvodpy — Performance Dashboard",
    css_file="canvod_nordic.css",
)


@app.cell
def _():
    import marimo as mo

    return (mo,)


@app.cell
def _(mo):
    mo.md(
        """
# canvodpy — Performance Dashboard

Reads `stage_timing` events from `machine/performance*.json` (see
`canvodpy.logging.stage_timer` / `docs/guides/diagnostics.md`).
Not full telemetry — this is a lightweight, always-on, file-based
view of how a pipeline run spent its time. Works while a run is
still in progress (partial data) or after it's finished.
"""
    )
    return


@app.cell
def _(mo):
    import os
    from pathlib import Path

    def _default_log_dir() -> Path:
        env_dir = os.environ.get("CANVODPY_PERF_LOG_DIR")
        if env_dir:
            return Path(env_dir).expanduser()
        try:
            from canvod.config import load_config

            return load_config().processing.logging.get_log_dir()
        except Exception:
            return Path.cwd() / ".logs"

    log_dir = _default_log_dir()
    machine_dir = log_dir / "machine"

    mo.md(f"**Log directory:** `{machine_dir}`")
    return (machine_dir,)


@app.cell
def _(mo):
    refresh = mo.ui.button(label="🔄 Refresh")
    refresh
    return (refresh,)


@app.cell
def _(machine_dir, mo, refresh):
    import json

    import polars as pl

    _ = refresh  # re-run this cell when the button is clicked

    _STAGE_SCHEMA = {
        "run_id": pl.Utf8,
        "stage": pl.Utf8,
        "receiver": pl.Utf8,
        "date_key": pl.Utf8,
        "duration_seconds": pl.Float64,
        "status": pl.Utf8,
        "timestamp": pl.Utf8,
    }

    def _read_stage_events(paths: list) -> pl.DataFrame:
        """Read stage_timing events from one or more performance*.json files.

        Line-by-line json.loads rather than pl.read_ndjson: a file being
        actively appended to by a live run may have an incomplete trailing
        line at read time, which would otherwise fail the whole read.
        """
        rows = []
        for path in paths:
            try:
                text = path.read_text()
            except OSError:
                continue
            for line in text.splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue  # partial trailing line from a live writer
                if event.get("event") != "stage_timing":
                    continue
                rows.append({key: event.get(key) for key in _STAGE_SCHEMA})

        if not rows:
            return pl.DataFrame(schema=_STAGE_SCHEMA)
        return pl.DataFrame(rows, schema=_STAGE_SCHEMA)

    perf_files = sorted(machine_dir.glob("performance*.json"))
    events = _read_stage_events(perf_files)

    if events.is_empty():
        summary = mo.callout(
            mo.md(
                f"No `stage_timing` events found yet under `{machine_dir}`. "
                "Run `canvodpy run ...` first, or click Refresh once one "
                "has started writing."
            ),
            kind="warn",
        )
    else:
        summary = mo.md(
            f"**{len(events)}** stage_timing events across "
            f"**{events['run_id'].n_unique()}** run(s), "
            f"**{events['stage'].n_unique()}** distinct stages."
        )
    summary
    return events, pl


@app.cell
def _(events, mo, pl):
    mo.md("## Current iteration — stage breakdown")

    if events.is_empty():
        latest_chart = mo.md("_No data yet._")
    else:
        # "Current iteration" = the most recently completed (receiver, date_key)
        # unit of work: every stage_timing row sharing its max timestamp group.
        latest = events.filter(pl.col("date_key").is_not_null()).sort(
            "timestamp", descending=True
        )
        if latest.is_empty():
            latest_chart = mo.md(
                "_No stage_timing events carry receiver/date_key context yet "
                "(only reading/validating/augmenting/writing stages do)._"
            )
        else:
            latest_key = (latest[0, "receiver"], latest[0, "date_key"])
            current = events.filter(
                (pl.col("receiver") == latest_key[0])
                & (pl.col("date_key") == latest_key[1])
            )
            import altair as _alt

            _chart = (
                _alt.Chart(current.to_pandas())
                .mark_bar()
                .encode(
                    x=_alt.X("stage:N", sort="-y", title="Stage"),
                    y=_alt.Y("duration_seconds:Q", title="Duration (s)"),
                    color=_alt.Color("status:N"),
                    tooltip=["stage", "duration_seconds", "status"],
                )
                .properties(
                    title=f"receiver={latest_key[0]}  date={latest_key[1]}",
                    width=500,
                    height=300,
                )
            )
            latest_chart = mo.ui.altair_chart(_chart)

    latest_chart
    return


@app.cell
def _(events, mo, pl):
    mo.md("## Elapsed time per receiver × day")

    if events.is_empty():
        agg_chart = mo.md("_No data yet._")
    else:
        by_unit = (
            events.filter(
                pl.col("date_key").is_not_null() & pl.col("receiver").is_not_null()
            )
            .group_by(["receiver", "date_key"])
            .agg(pl.col("duration_seconds").sum().alias("total_seconds"))
            .sort(["date_key", "receiver"])
        )
        if by_unit.is_empty():
            agg_chart = mo.md("_No receiver/date_key-tagged events yet._")
        else:
            import altair as _alt

            _chart = (
                _alt.Chart(by_unit.to_pandas())
                .mark_bar()
                .encode(
                    x=_alt.X("date_key:N", title="Day (YYYYDOY)"),
                    y=_alt.Y("total_seconds:Q", title="Total time (s)"),
                    color=_alt.Color("receiver:N"),
                    tooltip=["receiver", "date_key", "total_seconds"],
                )
                .properties(width=650, height=350)
            )
            agg_chart = mo.ui.altair_chart(_chart)

    agg_chart
    return


if __name__ == "__main__":
    app.run()
