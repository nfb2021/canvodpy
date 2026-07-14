"""Utility modules for canvodpy.

Pipeline timing/tracing lives in ``canvodpy.logging.stage_timer`` (see
``stage_timer``, ``emit_run_summary``) -- a lightweight, always-on
replacement for the removed OpenTelemetry-based ``telemetry.py``, which
required an optional dependency that was never actually installed.
"""
