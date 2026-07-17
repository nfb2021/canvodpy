"""Shared zarr async-concurrency scoping (dev/todo_later.md §44).

Zarr v3's async codec pipeline issues chunk writes/reads for a single array
as a concurrent ``asyncio.gather`` burst, sized by ``zarr.config``'s
``async.concurrency`` (default 10). On network-mounted (CIFS/NFS) stores
that burst can trip connection-abort errors under load. Capping it costs
throughput, so every caller opts in explicitly via its own config knob
(``IcechunkConfig.zarr_async_concurrency``, ``AuxDataConfig.zarr_async_concurrency``)
rather than this helper choosing a default.

Extracted out of ``MyIcechunkStore`` so the aux (SP3/CLK Hermite) cache's
plain-Zarr write path -- a separate store, untouched by the Icechunk-only
fix that originally shipped this -- can use the exact same mechanism.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import zarr


@contextmanager
def scoped_zarr_concurrency(concurrency: int | None) -> Iterator[None]:
    """Scope zarr's async chunk write/read concurrency for the enclosed block.

    ``concurrency=None`` is a no-op (zarr's own default applies, unchanged).
    Otherwise reads the current ``async`` config subsection and merges the
    new concurrency value onto it before scoping -- ``zarr.config.set()``
    replaces the whole subsection rather than merging, so passing only
    ``{"concurrency": ...}`` would silently drop sibling keys (e.g.
    ``timeout``) for the scope of the block. This crashed a production run
    with ``KeyError: 'timeout'`` the first time this mistake was made; do
    not reintroduce it.
    """
    if concurrency is None:
        yield
        return
    scoped_async_cfg = dict(zarr.config.get("async"))
    scoped_async_cfg["concurrency"] = concurrency
    with zarr.config.set({"async": scoped_async_cfg}):
        yield
