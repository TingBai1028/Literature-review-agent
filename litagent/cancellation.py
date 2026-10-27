"""Cooperative cancellation for a disconnected search request and its worker threads."""
from contextlib import contextmanager
from contextvars import ContextVar
from threading import Event
import time


class SearchCancelled(RuntimeError):
    pass


_current: ContextVar[Event | None] = ContextVar("search_cancellation", default=None)


@contextmanager
def cancellation_scope(stop: Event):
    token = _current.set(stop)
    try:
        yield
    finally:
        _current.reset(token)


def check_cancelled() -> None:
    if (stop := _current.get()) is not None and stop.is_set():
        raise SearchCancelled("Search cancelled by the client")


def cancellation_enabled() -> bool:
    return _current.get() is not None


def cancellable_sleep(seconds: float) -> None:
    stop = _current.get()
    if stop is None:
        time.sleep(seconds)
    elif stop.wait(seconds):
        check_cancelled()
