"""Run independent model calls at the same time.

Almost all of a real run's time is spent waiting on the model, one request after another (26 Oct: 599 of 618 s
for a 50-paper map). Nightshift serves concurrent requests (8 at once finished in the time of the slowest), so
independent calls — relevance batches, label batches, connection groups, gap clusters — run in a thread pool.
Each task runs in a copy of the caller's context, so it logs to the run's trace and counts against its token
budget. Results keep the input order, so outputs do not depend on which request returns first.
"""

from __future__ import annotations

import contextvars
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, TypeVar

T = TypeVar("T")
R = TypeVar("R")


def run_parallel(fn: Callable[[T], R], items: list[T], workers: int) -> list[tuple[R | None, BaseException | None]]:
    """(result, error) per item, in input order; every item runs even when another fails."""
    items = list(items)
    if workers <= 1 or len(items) <= 1:
        out = []
        for item in items:
            try:
                out.append((fn(item), None))
            except Exception as error:  # noqa: BLE001 - reported to the caller with the item's position
                out.append((None, error))
        return out
    with ThreadPoolExecutor(max_workers=min(workers, len(items))) as pool:
        futures = [pool.submit(contextvars.copy_context().run, fn, item) for item in items]
        out = []
        for future in futures:
            error = future.exception()
            out.append((None, error) if error else (future.result(), None))
        return out


def parallel_map(fn: Callable[[T], R], items: list[T], workers: int) -> list[R]:
    """Like map(); the first error (in input order) is raised after every item has finished."""
    results = run_parallel(fn, items, workers)
    for _, error in results:
        if error is not None:
            raise error
    return [result for result, _ in results]
