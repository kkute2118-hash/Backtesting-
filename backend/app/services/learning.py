"""Adaptive learning: what kinds of valid setup historically worked better.

None of this changes strategy qualification. The learning layer only ranks
survivors, which is why every response here is presented as evidence with its
sample size attached rather than as a prediction.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from app.core.errors import ApiError
from app.engine import core
from app.services.serialization import clean_value, frame_to_records


def snapshot(market: str = "INDIA", limit: int = 500) -> dict[str, Any]:
    df = core.learning_snapshot(market)
    total = 0 if df is None else len(df)
    return {
        "market": market,
        "total": total,
        "rows": frame_to_records(df, limit=limit),
        "columns": [str(c) for c in (df.columns if df is not None else [])],
    }


def edge_table(market: str = "INDIA") -> dict[str, Any]:
    df = core.adaptive_edge_table(market)
    return {"market": market, "rows": frame_to_records(df)}


def component_weights(market: str = "INDIA", strategy: int | None = None) -> dict[str, Any]:
    df = core.adaptive_component_weights(market, strategy)
    return {"market": market, "strategy": strategy, "rows": frame_to_records(df)}


def leaderboard() -> dict[str, Any]:
    """Forward-test strategy ranking — the reality check on the backtests."""
    return {"rows": frame_to_records(core.forward_summary_table())}


def model_status(market: str = "INDIA") -> dict[str, Any]:
    """Whether the win-probability classifier has enough evidence to be used."""
    info = core.train_win_probability_model(market)
    if not isinstance(info, dict):
        return {"ready": False}
    return {
        "ready": bool(info.get("ready")),
        "samples": clean_value(info.get("n_samples")),
        "min_samples": clean_value(info.get("min_samples")),
        "reason": clean_value(info.get("reason")),
        "gbc_auc": clean_value(info.get("gbc_auc")),
        "gbc_brier": clean_value(info.get("gbc_brier")),
        "logit_auc": clean_value(info.get("logit_auc")),
        "logit_brier": clean_value(info.get("logit_brier")),
        "feature_columns": [str(c) for c in (info.get("feature_columns") or [])],
    }


def coach(market: str = "INDIA", strategy: str = "S1") -> dict[str, Any]:
    """The statistical (non-LLM) strategy coach: regime, components, tree rules."""
    report = core.strategy_coach_report(market, strategy)
    if not isinstance(report, dict):
        return {"available": False, "market": market, "strategy": strategy}
    out: dict[str, Any] = {"available": True, "market": market, "strategy": strategy}
    for key, value in report.items():
        out[str(key)] = frame_to_records(value) if isinstance(value, pd.DataFrame) else clean_value(value)
    return out


def database_stats() -> dict[str, Any]:
    """Row counts per table — how much evidence has actually accumulated."""
    con = core._db()
    try:
        tables = [r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' "
            "ORDER BY name")]
        counts = []
        for name in tables:
            try:
                n = int(con.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0])
            except Exception:
                n = -1
            counts.append({"table": name, "rows": n,
                           "rebuildable": name in core.REBUILDABLE_TABLES})
    finally:
        con.close()
    return {"database": core.DATA_DB, "tables": counts,
            "total_rows": sum(c["rows"] for c in counts if c["rows"] > 0)}


def raw_fingerprints(limit: int = 500) -> dict[str, Any]:
    """Ungated signal fingerprints from the raw-learning capture."""
    core.ensure_raw_fingerprint_table()
    con = core._db()
    try:
        df = pd.read_sql_query(
            "SELECT * FROM raw_signal_fingerprints ORDER BY id DESC LIMIT ?",
            con, params=(int(limit),))
    finally:
        con.close()
    return {"rows": frame_to_records(df),
            "columns": [str(c) for c in df.columns]}
