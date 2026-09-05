"""A drop-in stand-in for the parts of Streamlit that ``core.py`` uses.

``core.py`` is the engine this whole product is built on: strategies S1-S4,
scoring, safety, the backtests and the learning store.  It is moved into the
FastAPI backend **verbatim** so the new application cannot silently produce
different scanner results from the Streamlit build it replaces.  The single
edit is its import line, which now points here.

Only four things were ever borrowed from Streamlit:

* ``cache_data``    - memoise a pure function, keyed on its arguments
* ``cache_resource``- memoise a live object (a model, a websocket manager)
* ``secrets``       - read configuration
* ``info``/``warning``/``error``/``success`` - one banner helper

so that is all this module provides.  Anything else raises ``AttributeError``
rather than silently doing nothing, which is how a missed dependency on the UI
framework gets found at import time instead of in production.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any, Callable, TypeVar

F = TypeVar("F", bound=Callable[..., Any])

_LOCK = threading.RLock()
_CACHES: dict[int, dict[Any, tuple[float, Any]]] = {}


# --------------------------------------------------------------------------- #
# argument hashing
# --------------------------------------------------------------------------- #
class _Unhashable:
    """Sentinel meaning "this call cannot be cached"; the wrapper falls through."""


def _hash_arg(value: Any) -> Any:
    """Stable key for one argument, including pandas objects.

    Streamlit hashes DataFrames by content.  ``features_fast(symbol, df)`` and
    ``features_cached(symbol, df)`` rely on that: the same symbol with a longer
    frame must miss the cache.  Content hashing is what makes those two calls
    correct, so it is reproduced here rather than approximated by ``id()``.
    """
    if value is None or isinstance(value, (bool, int, float, str, bytes)):
        return value
    if isinstance(value, (list, tuple)):
        parts = tuple(_hash_arg(v) for v in value)
        return _Unhashable if any(p is _Unhashable for p in parts) else parts
    if isinstance(value, (set, frozenset)):
        try:
            return ("set", tuple(sorted(value)))
        except TypeError:
            return _Unhashable
    if isinstance(value, dict):
        try:
            items = tuple(sorted((k, _hash_arg(v)) for k, v in value.items()))
        except TypeError:
            return _Unhashable
        return _Unhashable if any(v is _Unhashable for _, v in items) else ("dict", items)

    module = type(value).__module__.split(".")[0]
    if module in {"pandas", "numpy"}:
        try:
            import numpy as np
            import pandas as pd

            if isinstance(value, (pd.DataFrame, pd.Series, pd.Index)):
                digest = int(pd.util.hash_pandas_object(value, index=True).sum())
                shape = getattr(value, "shape", None)
                cols = tuple(map(str, value.columns)) if isinstance(value, pd.DataFrame) else ()
                return ("pandas", type(value).__name__, shape, cols, digest)
            if isinstance(value, np.ndarray):
                return ("numpy", value.shape, str(value.dtype), value.tobytes())
            if isinstance(value, np.generic):
                return ("numpy-scalar", value.item())
        except Exception:
            return _Unhashable

    try:
        hash(value)
    except TypeError:
        return _Unhashable
    return value


def _make_key(args: tuple, kwargs: dict) -> Any:
    key_args = tuple(_hash_arg(a) for a in args)
    key_kwargs = tuple(sorted((k, _hash_arg(v)) for k, v in kwargs.items()))
    if any(a is _Unhashable for a in key_args):
        return _Unhashable
    if any(v is _Unhashable for _, v in key_kwargs):
        return _Unhashable
    return (key_args, key_kwargs)


def _copy_result(value: Any) -> Any:
    """Match ``st.cache_data``, which hands every caller its own copy.

    Without this a caller that mutates a returned frame would corrupt the cache
    for everyone else - and several engine call sites do exactly that kind of
    in-place work on the feature frame.
    """
    try:
        import pandas as pd

        if isinstance(value, (pd.DataFrame, pd.Series)):
            return value.copy()
    except Exception:
        pass
    return value


# --------------------------------------------------------------------------- #
# caches
# --------------------------------------------------------------------------- #
def _cached(func: F, ttl: float | None, copy: bool, max_entries: int | None) -> F:
    import functools

    store: dict[Any, tuple[float, Any]] = {}
    _CACHES[id(func)] = store

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        key = _make_key(args, kwargs)
        if key is _Unhashable:
            return func(*args, **kwargs)
        now = time.time()
        with _LOCK:
            hit = store.get(key)
            if hit is not None:
                stamped, value = hit
                if ttl is None or (now - stamped) < ttl:
                    return _copy_result(value) if copy else value
                store.pop(key, None)
        value = func(*args, **kwargs)
        with _LOCK:
            if max_entries is not None and len(store) >= max_entries:
                oldest = min(store, key=lambda k: store[k][0])
                store.pop(oldest, None)
            store[key] = (time.time(), value)
        return _copy_result(value) if copy else value

    def clear() -> None:
        with _LOCK:
            store.clear()

    wrapper.clear = clear  # type: ignore[attr-defined]
    return wrapper  # type: ignore[return-value]


def _decorator(copy: bool):
    def outer(func: F | None = None, *, ttl: float | None = None,
              show_spinner: bool = True, max_entries: int | None = None,
              **_ignored: Any):
        def wrap(f: F) -> F:
            return _cached(f, ttl, copy, max_entries)

        return wrap(func) if callable(func) else wrap

    return outer


cache_data = _decorator(copy=True)
cache_resource = _decorator(copy=False)


def clear_all_caches() -> None:
    """Drop every memoised value. Used by the Data Manager's refresh action."""
    with _LOCK:
        for store in _CACHES.values():
            store.clear()


# --------------------------------------------------------------------------- #
# secrets
# --------------------------------------------------------------------------- #
class _Secrets:
    """Configuration lookup with the same surface ``st.secrets`` exposed.

    The engine's ``_secret()`` already falls back to the environment, which is
    how the GitHub Actions cron jobs work.  Environment variables are therefore
    the primary store here.  A ``secrets.toml`` is still read when present so an
    existing Streamlit deployment's file keeps working unchanged.
    """

    def __init__(self) -> None:
        self._file: dict[str, Any] | None = None

    def _load_file(self) -> dict[str, Any]:
        if self._file is not None:
            return self._file
        self._file = {}
        path = os.environ.get("SECRETS_TOML") or os.path.join(".streamlit", "secrets.toml")
        try:
            if os.path.exists(path):
                import tomllib

                with open(path, "rb") as fh:
                    loaded = tomllib.load(fh)
                self._file = {k: v for k, v in loaded.items()}
        except Exception:
            self._file = {}
        return self._file

    def get(self, name: str, default: Any = None) -> Any:
        value = os.environ.get(name)
        if value not in (None, ""):
            return value
        value = self._load_file().get(name)
        return value if value not in (None, "") else default

    def __contains__(self, name: str) -> bool:
        return self.get(name) is not None

    def __getitem__(self, name: str) -> Any:
        value = self.get(name)
        if value is None:
            raise KeyError(name)
        return value


secrets = _Secrets()


# --------------------------------------------------------------------------- #
# message stubs
# --------------------------------------------------------------------------- #
def _noop(*_args: Any, **_kwargs: Any) -> None:
    """Rendering is the frontend's job; the engine only ever reported state."""
    return None


info = warning = error = success = caption = write = _noop
