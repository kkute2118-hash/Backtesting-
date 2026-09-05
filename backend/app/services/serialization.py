"""Turn engine output (pandas, numpy, dates) into JSON the browser can hold.

The engine speaks DataFrames. FastAPI speaks JSON. Everything crossing that
boundary goes through here so a NaN never reaches the browser as the literal
``NaN`` token (which is not valid JSON and breaks ``JSON.parse``), and so a
``numpy.float64`` never escapes as an unserialisable object.
"""

from __future__ import annotations

import math
from datetime import date, datetime
from typing import Any

import numpy as np
import pandas as pd


def clean_value(value: Any) -> Any:
    """One scalar, JSON-safe. NaN/Inf become ``None`` rather than a bad token."""
    if value is None:
        return None
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating, float)):
        f = float(value)
        return None if (math.isnan(f) or math.isinf(f)) else f
    if isinstance(value, (pd.Timestamp, datetime)):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (np.str_,)):
        return str(value)
    if isinstance(value, pd.Period):
        return str(value)
    if value is pd.NaT:
        return None
    if isinstance(value, (list, tuple, np.ndarray)):
        return [clean_value(v) for v in value]
    if isinstance(value, dict):
        return {str(k): clean_value(v) for k, v in value.items()}
    if isinstance(value, (pd.Series,)):
        return [clean_value(v) for v in value.tolist()]
    if isinstance(value, pd.DataFrame):
        return frame_to_records(value)
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(value, (str, int)):
        return value
    return str(value)


def frame_to_records(df: pd.DataFrame | None, *, index_name: str | None = None,
                     limit: int | None = None) -> list[dict[str, Any]]:
    """DataFrame -> list of JSON-safe row objects, preserving column order."""
    if df is None or len(df) == 0:
        return []
    frame = df if limit is None else df.head(limit)
    if index_name:
        frame = frame.reset_index().rename(columns={frame.index.name or "index": index_name})
    records: list[dict[str, Any]] = []
    columns = [str(c) for c in frame.columns]
    for row in frame.itertuples(index=False, name=None):
        records.append({col: clean_value(val) for col, val in zip(columns, row)})
    return records


def frame_columns(df: pd.DataFrame | None) -> list[str]:
    return [] if df is None else [str(c) for c in df.columns]


def clean_mapping(payload: dict[str, Any] | None) -> dict[str, Any]:
    return {} if not payload else {str(k): clean_value(v) for k, v in payload.items()}
