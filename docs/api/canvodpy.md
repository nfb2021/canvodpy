# canvodpy API Reference

Umbrella package for the canVODpy framework. Two supported surfaces, plus the
CLI on top of one of them — see [API Levels](../guides/api-levels.md).

## Site and Pipeline (recommended — Python-native pipeline runs)

Stateful orchestrator with factory integration and structured logging. What
the CLI builds internally.

::: canvodpy.Site
::: canvodpy.Pipeline

## Functional API (recommended — component-level scripting/analysis)

Pure, stateless functions for composable pipelines, Airflow DAGs, and analysis.

::: canvodpy.read_rinex
::: canvodpy.create_grid
::: canvodpy.assign_grid_cells

## Deprecated: Convenience Functions

One-liner wrappers around `Site.pipeline()` — no longer taught. Use
`Site(site).pipeline()` directly instead.

::: canvodpy.process_date
::: canvodpy.calculate_vod
::: canvodpy.preview_processing

## Deprecated: Fluent Workflow

Chainable pipeline where steps are recorded and executed only when a
terminal method (`.result()`, `.to_store()`, `.plot()`) is called.

::: canvodpy.workflow
::: canvodpy.FluentWorkflow

## Deprecated: VODWorkflow

Factory-based alternative to `Site` + `Pipeline`. Its augmentation step is a
no-op stub — VOD computed through it uses un-augmented angles. Do not use.

::: canvodpy.VODWorkflow

## Factories

::: canvodpy.ReaderFactory
::: canvodpy.GridFactory
::: canvodpy.VODFactory

## Configuration

::: canvodpy.setup_logging
::: canvodpy.get_logger
