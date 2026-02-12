# canvodpy API Reference

Umbrella package providing a unified, four-level API for the canVODpy framework.

## Level 1 — Convenience Functions

One-liner functions for quick exploration.

::: canvodpy.process_date
::: canvodpy.calculate_vod
::: canvodpy.preview_processing

## Level 2 — Fluent Workflow (Deferred Execution)

Chainable pipeline where steps are recorded and executed only when a
terminal method (`.result()`, `.to_store()`, `.plot()`) is called.

::: canvodpy.workflow
::: canvodpy.FluentWorkflow

## Level 3 — VODWorkflow (Eager Execution)

Stateful orchestrator with factory integration and structured logging.

::: canvodpy.Site
::: canvodpy.Pipeline
::: canvodpy.VODWorkflow

## Level 4 — Functional API

Pure, stateless functions for composable pipelines and Airflow DAGs.

::: canvodpy.read_rinex
::: canvodpy.create_grid
::: canvodpy.assign_grid_cells

## Factories

::: canvodpy.ReaderFactory
::: canvodpy.GridFactory
::: canvodpy.VODFactory

## Configuration

::: canvodpy.setup_logging
::: canvodpy.get_logger
