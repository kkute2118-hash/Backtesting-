"""Shared setup for the golden regression harness.

The harness answers exactly one question: did a change move what a scan
selects or scores? So it has to be hermetic - same candles, same universe,
same code path - every run. It reads a committed fixture database rather than
whatever the machine happens to hold, and it pins the symbol list rather than
resolving "Nifty 500" over the network, because a list that changes when NSE
reviews the index would make every failure ambiguous.
"""
from __future__ import annotations

import gzip, json, os, shutil, tempfile

GOLDEN_DIR = os.path.dirname(os.path.abspath(__file__))
FIXTURE_GZ = os.path.join(GOLDEN_DIR, "fixture_market_data.sqlite3.gz")

# The columns that define WHAT a scan selects and scores. Deliberately not the
# whole row: Adaptive Score, Learned Rank, Historical Edge R and Win
# Probability are functions of accumulated learning data, so they move as the
# forward record grows even when no scan rule changed. Freezing them would
# make the harness cry wolf; leaving them out keeps every failure meaningful.
FROZEN_COLUMNS = [
    "Ticker", "Strategy", "Score", "Entry", "SL 7%", "Target 3R", "R:R",
    "Signal", "Regime", "Safety", "Safety Score", "Safety Flags",
    "HTF Score", "Footprint Score", "Strategy Score", "Entry Quality",
    "Trend Score", "RSI", "RelVol",
    "ATR %", "Turnover Cr", "Sector Rank", "Entry Filter",
]


def install_fixture_db() -> str:
    """Unpack the fixture and point the engine at it. Returns the path."""
    path = os.path.join(tempfile.mkdtemp(prefix="golden-"), "market_data.sqlite3")
    with gzip.open(FIXTURE_GZ, "rb") as src, open(path, "wb") as dst:
        shutil.copyfileobj(src, dst)
    os.environ["DATA_DB"] = path
    # The engine reads DATA_DB at import time, so anything that imported it
    # earlier in the session is still pointing at the real database.
    from app.engine import core
    core.DATA_DB = path
    # ensure_engine_tables() also ran at import, against the OLD path, so the
    # fixture has candles but none of the engine's own tables. Standalone this
    # is invisible - nothing has read them yet - but after another test module
    # has run, the first feature-snapshot lookup fails on a missing table.
    core.ensure_engine_tables()
    return path


def fixture_symbols(core) -> list[str]:
    """The pinned universe: every stock in the fixture with enough history."""
    con = core._db()
    try:
        return [r[0] for r in con.execute(
            "SELECT symbol FROM candles WHERE symbol NOT LIKE '^%' "
            "GROUP BY symbol HAVING COUNT(*)>=260 ORDER BY symbol")]
    finally:
        con.close()


def run_reference_scan(core, apply_filter: bool = True) -> list[dict]:
    """The scan the golden pins: every fixture stock, all five strategies.

    apply_filter=False runs the same scan with the entry evidence filter off.
    That second snapshot is what actually protects the STRATEGY rules: with the
    filter on, only 13 rows survive and S2 and S4 produce none at all, so a
    change to their entry conditions would sail straight through. Ungated the
    same fixture yields hundreds of rows across all five.
    """
    symbols = fixture_symbols(core)
    data = core.load_scan_dataset(symbols)
    proxy, _src = core.market_regime_frame(data)
    regime, _score = core.regime_from_index(proxy)
    previous = core.APPLY_ENTRY_EVIDENCE_FILTER
    core.APPLY_ENTRY_EVIDENCE_FILTER = bool(apply_filter)
    try:
        result = core.scan_dataset(data, list(core.IMPLEMENTED_STRATEGIES), regime)
    finally:
        core.APPLY_ENTRY_EVIDENCE_FILTER = previous
    if result is None or result.empty:
        return []
    rows = []
    for _, r in result.iterrows():
        rows.append({c: _plain(r.get(c)) for c in FROZEN_COLUMNS})
    rows.sort(key=lambda d: (str(d["Ticker"]), str(d["Strategy"])))
    return rows


def _plain(v):
    """JSON-safe, and NaN as None so a reload compares equal to itself."""
    import math
    import numpy as np
    if v is None:
        return None
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating, float)):
        f = float(v)
        return None if math.isnan(f) else f
    if isinstance(v, (np.bool_, bool)):
        return bool(v)
    return str(v)


def load_golden(name: str):
    with open(os.path.join(GOLDEN_DIR, name), encoding="utf-8") as f:
        return json.load(f)


def save_golden(name: str, payload) -> None:
    with open(os.path.join(GOLDEN_DIR, name), "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=1, sort_keys=True, ensure_ascii=False)
        f.write("\n")


def run_signal_census(core) -> dict:
    """Every signal every strategy fires over the whole fixture history.

    This is the real pin on the ENTRY RULES. A scan only evaluates the latest
    bar, so a single-date snapshot covers whichever strategies happen to fire
    that day - on this fixture that was S1, S3 and S5, leaving S2's and S4's
    conditions completely unprotected. Walking the history instead exercises
    all five, 25,603 signals, and names the symbol and date of any that move.

    Stored as first/last/count plus a digest per (symbol, strategy): the full
    date list would be a megabyte of JSON, while the digest still fails on a
    single added or dropped bar and the counts say how far it moved.
    """
    import hashlib
    import numpy as np

    data = core.load_scan_dataset(fixture_symbols(core))
    out = {}
    for ticker in sorted(data):
        frame = data[ticker]
        if frame is None or len(frame) < 260:
            continue
        feats = core.features_fast(str(ticker), frame).replace([np.inf, -np.inf], np.nan)
        for s in core.IMPLEMENTED_STRATEGIES:
            hits = feats.index[core.strategy_signal(feats, s).fillna(False).to_numpy()]
            if not len(hits):
                continue
            dates = [d.strftime("%Y-%m-%d") for d in hits]
            out[f"{ticker}|S{s}"] = {
                "count": len(dates),
                "first": dates[0],
                "last": dates[-1],
                "digest": hashlib.sha256("|".join(dates).encode()).hexdigest()[:16],
            }
    return out
