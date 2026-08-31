"""Per-run identifier propagation for logging.

A run_id identifies a single pipeline invocation for one site (see
``cli/run.py``'s per-site loop). It is threaded automatically into every
log record via a structlog processor (``logging_config.py``) and, where
possible, into Icechunk commit messages, so a human or an agent can
correlate "this run" across the human log, the agent-diagnostic log, and
the data it wrote -- without any call site needing to pass it explicitly.
"""

import contextvars

RUN_ID: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "RUN_ID", default=None
)


def get_run_id() -> str | None:
    """Return the run_id bound to the current context, if any."""
    return RUN_ID.get()


def set_run_id(run_id: str) -> contextvars.Token:
    """Bind ``run_id`` to the current context.

    Parameters
    ----------
    run_id : str
        Identifier for the current pipeline run (see ``cli/run.py``'s
        ``{site}-{YYYYMMDD-HHMMSS}`` format).

    Returns
    -------
    contextvars.Token
        Token used to restore the previous value via ``reset_run_id``.
    """
    return RUN_ID.set(run_id)


def reset_run_id(token: contextvars.Token) -> None:
    """Reset RUN_ID to its previous value."""
    RUN_ID.reset(token)
