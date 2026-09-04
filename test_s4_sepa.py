"""Synthetic-data unit tests for the S4 SEPA replacement patch.

Covers:
  (a) strategy4_sepa_watchlist()/strategy4_sepa_signal() fire on a hand-
      constructed positive case (genuine monthly EMA10/20 "reclaim" pattern +
      daily VCP-style contraction + demand candle) and do NOT fire on a
      flat/random series.
  (b) clean_liquid_universe() excludes a synthetic heavy-wick/gap ticker and
      keeps a clean one.
  (c) stock_dna()'s size-multiplier tiers on synthetic monthly-return data.
  (d) The forward_tests 'S4' -> 'S4_RECOVERY_LEGACY' migration in _db() is
      idempotent and only touches rows tagged exactly 'S4'.

Run from a scratch copy of app.py + core.py (never against the real repo's
market_data.sqlite3).
"""
import os
import sys
import sqlite3
import numpy as np
import pandas as pd

import core

FAILURES = []


def check(name, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    print(f"[{status}] {name}" + (f" - {detail}" if detail and not cond else ""))
    if not cond:
        FAILURES.append(name)


# ======================================================================
# (a) SEPA signal logic
# ======================================================================

def _month_dates(start, days_per_month):
    return pd.bdate_range(start, periods=days_per_month + 5, freq="B")[:days_per_month]


def build_sepa_positive_case(plateau_months=16, plateau_start=20.5, plateau_end=28.0,
                              pullback_close=21.0, event_mult=1.25,
                              days_per_month=20, dip_tail=4, rally_tail=5,
                              base_tail=9, seed=5):
    """A stock that: has been in a genuine multi-month uptrend (daily EMA50 >
    EMA200, EMA200 sloping up); had a sharp one-month dip (visible only at
    that month's close, so it doesn't wreck the daily EMAs); then this month
    rallies back >=20% to a demand candle that closes within SEPA's proximity
    bands of both the monthly EMA10 and the daily EMA200 - Scenario A.
    """
    event_close = round(pullback_close * event_mult, 3)
    rng = np.random.default_rng(seed)
    cur = pd.Timestamp("2019-01-07")
    dates, closes = [], []
    prev_level = plateau_start * 0.94

    d0 = _month_dates(cur, days_per_month)
    path0 = np.linspace(prev_level, plateau_start, len(d0)) * (1 + rng.normal(0, 0.003, len(d0)))
    path0[-1] = plateau_start
    dates += list(d0); closes += list(path0)
    cur = d0[-1] + pd.offsets.MonthBegin(1)
    level = plateau_start

    for i in range(plateau_months):
        target = plateau_start + (plateau_end - plateau_start) * (i + 1) / plateau_months
        dd = _month_dates(cur, days_per_month)
        path = np.linspace(level, target, len(dd)) * (1 + rng.normal(0, 0.003, len(dd)))
        path[-1] = target
        dates += list(dd); closes += list(path)
        level = target
        cur = dd[-1] + pd.offsets.MonthBegin(1)

    dd = _month_dates(cur, days_per_month)
    n = len(dd)
    path = level * (1 + rng.normal(0, 0.003, n - dip_tail))
    tail = np.linspace(level, pullback_close, dip_tail + 1)[1:]
    path = np.concatenate([path, tail]); path[-1] = pullback_close
    dates += list(dd); closes += list(path)
    cur = dd[-1] + pd.offsets.MonthBegin(1)

    dd = _month_dates(cur, days_per_month)
    n = len(dd)
    lead = n - base_tail - rally_tail
    path_lead = level * (1 + rng.normal(0, 0.003, lead))
    base_level = level * 0.985
    path_base = base_level * (1 + rng.normal(0, 0.0012, base_tail))
    path_rally = np.linspace(base_level, event_close, rally_tail + 1)[1:]
    path_rally[-1] = event_close
    path = np.concatenate([path_lead, path_base, path_rally])
    dates += list(dd); closes += list(path)

    closes = np.array(closes)
    dates = pd.DatetimeIndex(dates)

    open_ = np.empty_like(closes); open_[0] = closes[0]; open_[1:] = closes[:-1]
    rng2 = np.abs(rng.normal(0.006, 0.002, size=len(closes))) * closes
    high = np.maximum(open_, closes) + rng2 * 0.4
    low = np.minimum(open_, closes) - rng2 * 0.4
    volume = rng.uniform(80_000, 120_000, size=len(closes))

    total = len(closes)
    base_start_idx = total - rally_tail - base_tail
    for i in range(base_start_idx, total - 1):
        mid = (open_[i] + closes[i]) / 2
        high[i] = mid + abs(rng2[i]) * 0.10
        low[i] = mid - abs(rng2[i]) * 0.10
        volume[i] = rng.uniform(28_000, 42_000)
    i = total - 1
    open_[i] = closes[i] * 0.975
    low[i] = open_[i] * 0.995
    high[i] = closes[i] * 1.004
    volume[i] = 230_000

    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": closes, "volume": volume},
        index=dates,
    )


def build_flat_random_series(seed=3, n=480):
    rng = np.random.default_rng(seed)
    dates = pd.bdate_range("2019-01-01", periods=n)
    price = 50 + np.cumsum(rng.normal(0, 0.15, size=n))
    price = np.clip(price, 30, None)
    open_ = np.empty_like(price); open_[0] = price[0]; open_[1:] = price[:-1]
    r = np.abs(rng.normal(0.3, 0.1, size=n))
    high = np.maximum(open_, price) + r
    low = np.minimum(open_, price) - r
    volume = rng.uniform(60_000, 90_000, size=n)
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": price, "volume": volume},
        index=pd.DatetimeIndex(dates, name="date"),
    )


def test_sepa_signal_logic():
    print("\n--- (a) SEPA signal logic ---")
    d_pos = build_sepa_positive_case()
    x_pos = core.strategy4_sepa_features(d_pos)
    watch_pos = core.strategy4_sepa_watchlist(x_pos)
    sig_pos = core.strategy4_sepa_signal(d_pos)

    check("watchlist is a boolean Series matching index length (positive case)",
          isinstance(watch_pos, pd.Series) and len(watch_pos) == len(d_pos))
    check("signal is a boolean Series matching index length (positive case)",
          isinstance(sig_pos, pd.Series) and len(sig_pos) == len(d_pos))
    check("watchlist fires on the constructed positive case (last bar)",
          bool(watch_pos.iloc[-1]))
    check("full entry signal fires on the constructed positive case (last bar)",
          bool(sig_pos.iloc[-1]))
    check("signal is a strict subset of watchlist over the whole series",
          bool((sig_pos & ~watch_pos).sum() == 0))

    d_flat = build_flat_random_series()
    x_flat = core.strategy4_sepa_features(d_flat)
    watch_flat = core.strategy4_sepa_watchlist(x_flat)
    sig_flat = core.strategy4_sepa_signal(d_flat)
    check("watchlist does NOT fire on a flat/random series (last bar)",
          not bool(watch_flat.iloc[-1]))
    check("full entry signal does NOT fire on a flat/random series (last bar)",
          not bool(sig_flat.iloc[-1]))
    check("no exception raised on either series (non-crashing)", True)

    # Live-wiring regression guard: strategy_signal(x, 4) must call
    # strategy4_sepa_watchlist(x) exactly (this is the actual swap the patch
    # makes - a prior draft of this change edited the wrong function and left
    # the live branch on the old formula, caught only by this comparison).
    a = core.strategy_signal(x_pos, 4)
    check("live strategy_signal(x, 4) == strategy4_sepa_watchlist(x) (positive case)",
          a.equals(watch_pos))
    a2 = core.strategy_signal(x_flat, 4)
    check("live strategy_signal(x, 4) == strategy4_sepa_watchlist(x) (flat case)",
          a2.equals(watch_flat))


# ======================================================================
# (b) clean_liquid_universe()
# ======================================================================

def build_clean_ticker(n=260, seed=1):
    rng = np.random.default_rng(seed)
    price = 50 + np.cumsum(rng.normal(0.05, 0.4, size=n))
    price = np.clip(price, 30, None)
    dates = pd.bdate_range("2023-01-02", periods=n)
    open_ = np.empty_like(price); open_[0] = price[0]; open_[1:] = price[:-1]
    # Small, well-behaved ranges; closes mostly in the upper half of the bar.
    rng_amt = np.abs(rng.normal(0.4, 0.1, size=n))
    high = np.maximum(open_, price) + rng_amt * 0.3
    low = np.minimum(open_, price) - rng_amt * 0.15
    volume = rng.uniform(150_000, 220_000, size=n)  # traded value well above 2M at price ~50-80
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": price, "volume": volume},
        index=pd.DatetimeIndex(dates, name="date"),
    )


def build_manipulated_ticker(n=260, seed=2):
    rng = np.random.default_rng(seed)
    price = [40.0]
    for _ in range(1, n):
        # Frequent >=15% one-day moves (safety() "Abnormal volatility") plus
        # thin liquidity, on top of the wick/gap structure below.
        shock = rng.choice([1.0, 1.0, 1.0, 1.18, 0.83], p=[0.7, 0.1, 0.1, 0.05, 0.05])
        price.append(max(5.0, price[-1] * shock * (1 + rng.normal(0, 0.02))))
    price = np.array(price)
    dates = pd.bdate_range("2023-01-02", periods=n)
    open_ = np.empty_like(price); open_[0] = price[0]
    # Large overnight gaps most days (open far from prior close).
    open_[1:] = price[:-1] * (1 + rng.normal(0, 0.09, size=n - 1))
    # Huge wicks: close near the LOW of a wide range most days (weak closes).
    rng_amt = np.abs(rng.normal(2.2, 0.6, size=n)) + 0.5
    high = np.maximum(open_, price) + rng_amt * 1.3
    low = np.minimum(open_, price) - rng_amt * 1.3
    low = np.clip(low, 1.0, None)
    volume = rng.uniform(2_000, 12_000, size=n)  # thin - low traded value
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": price, "volume": volume},
        index=pd.DatetimeIndex(dates, name="date"),
    )


def test_clean_liquid_universe():
    print("\n--- (b) clean_liquid_universe() ---")
    good = build_clean_ticker()
    bad = build_manipulated_ticker()
    data = {"GOODCO.NS": good, "BADCO.NS": bad}
    clean, audit = core.clean_liquid_universe(data)

    check("clean_liquid_universe returns a (dict, DataFrame) pair",
          isinstance(clean, dict) and isinstance(audit, pd.DataFrame))
    check("audit covers every input ticker", len(audit) == len(data),
          f"audit has {len(audit)} rows for {len(data)} inputs")
    check("GOODCO.NS is kept in the clean universe", "GOODCO.NS" in clean)
    check("BADCO.NS is excluded from the clean universe", "BADCO.NS" not in clean)

    bad_row = audit[audit.Ticker == "BADCO"]
    good_row = audit[audit.Ticker == "GOODCO"]
    check("BADCO audit row is marked not-passed", bool((~bad_row.Passed).all()))
    check("GOODCO audit row is marked passed", bool(good_row.Passed.all()))
    check("BADCO's audit row carries at least one explanatory flag",
          bool(bad_row.Flags.iloc[0]))


# ======================================================================
# (c) stock_dna()
# ======================================================================

def _monthly_frame_from_returns(returns_pct, start="2019-01-31"):
    n = len(returns_pct) + 1
    idx = pd.date_range(start, periods=n, freq="ME")
    price = [100.0]
    for r in returns_pct:
        price.append(price[-1] * (1 + r / 100))
    df = pd.DataFrame({
        "open": price, "high": [p * 1.01 for p in price],
        "low": [p * 0.99 for p in price], "close": price,
        "volume": [100_000] * n,
    }, index=idx)
    return df


def test_stock_dna():
    print("\n--- (c) stock_dna() size-multiplier tiers ---")
    # Big-mover stock: median up-leg ~70% -> multiplier should be 1.0.
    big = _monthly_frame_from_returns([70, -10, 65, -5, 75, -8, 68, -12, 72, -6])
    dna_big = core.stock_dna(big)
    check("big-mover (median leg >=60%) gets size_multiplier 1.0",
          dna_big["size_multiplier"] == 1.0, str(dna_big))

    # Mid-mover: median up-leg ~40% -> multiplier should be 0.75.
    mid = _monthly_frame_from_returns([40, -10, 38, -5, 42, -8, 39, -12, 41, -6])
    dna_mid = core.stock_dna(mid)
    check("mid-mover (30<=median leg<60%) gets size_multiplier 0.75",
          dna_mid["size_multiplier"] == 0.75, str(dna_mid))

    # Small-mover: median up-leg ~20% -> multiplier should be 0.5.
    small = _monthly_frame_from_returns([20, -5, 18, -4, 22, -6, 19, -5, 21, -4])
    dna_small = core.stock_dna(small)
    check("small-mover (15<=median leg<30%) gets size_multiplier 0.5",
          dna_small["size_multiplier"] == 0.5, str(dna_small))

    # Sluggish mover: median up-leg ~8% -> multiplier should be 0.25.
    sluggish = _monthly_frame_from_returns([8, -5, 7, -4, 9, -6, 8, -5, 7, -4])
    dna_sluggish = core.stock_dna(sluggish)
    check("sluggish mover (median leg<15%) gets size_multiplier 0.25",
          dna_sluggish["size_multiplier"] == 0.25, str(dna_sluggish))

    # Degenerate/too-little history -> neutral fallback.
    tiny = _monthly_frame_from_returns([5])
    dna_tiny = core.stock_dna(tiny)
    check("insufficient monthly history gets the 0.5 neutral fallback",
          dna_tiny["size_multiplier"] == 0.5, str(dna_tiny))


# ======================================================================
# (d) forward_tests 'S4' -> 'S4_RECOVERY_LEGACY' migration idempotency
# ======================================================================

def test_forward_tests_migration(tmp_db_path):
    print("\n--- (d) forward_tests migration idempotency ---")
    if os.path.exists(tmp_db_path):
        os.remove(tmp_db_path)

    old_data_db = core.DATA_DB
    core.DATA_DB = tmp_db_path
    try:
        # First _db() call runs every CREATE TABLE / migration statement,
        # including the UPDATE under test - but forward_tests is still empty
        # at this point, so nothing can be migrated yet.
        con = core._db()
        con.execute(
            "INSERT INTO forward_tests(created_at,symbol,strategy,score,status) "
            "VALUES('t','TICKA','S4',80,'ACTIVE')"
        )
        con.execute(
            "INSERT INTO forward_tests(created_at,symbol,strategy,score,status) "
            "VALUES('t','TICKB','S1',75,'ACTIVE')"
        )
        con.execute(
            "INSERT INTO forward_tests(created_at,symbol,strategy,score,status) "
            "VALUES('t','TICKC','S4_SEPA',90,'ACTIVE')"
        )
        con.commit()
        con.close()

        # Second _db() call: this is when the migration actually has 'S4' rows
        # to act on (every _db() call re-runs the idempotent migration SQL).
        con = core._db()
        rows = con.execute("SELECT symbol,strategy FROM forward_tests ORDER BY symbol").fetchall()
        con.close()
        by_symbol = dict(rows)

        check("pre-existing 'S4' row was renamed to 'S4_RECOVERY_LEGACY'",
              by_symbol.get("TICKA") == "S4_RECOVERY_LEGACY", str(by_symbol))
        check("an 'S1' row is untouched by the migration",
              by_symbol.get("TICKB") == "S1", str(by_symbol))
        check("a new 'S4_SEPA' row is untouched by the migration",
              by_symbol.get("TICKC") == "S4_SEPA", str(by_symbol))

        # Run _db() (and therefore the migration UPDATE) two more times and
        # confirm it is a true no-op: no error, and the row set is identical.
        core._db().close()
        core._db().close()
        con = core._db()
        rows_after = con.execute("SELECT symbol,strategy FROM forward_tests ORDER BY symbol").fetchall()
        con.close()
        check("running the migration repeatedly is idempotent (no further change)",
              rows_after == rows, f"{rows} vs {rows_after}")

        # No row anywhere is left tagged plain 'S4' after repeated migrations.
        con = core._db()
        remaining_s4 = con.execute(
            "SELECT COUNT(*) FROM forward_tests WHERE strategy='S4'"
        ).fetchone()[0]
        con.close()
        check("zero rows remain tagged exactly 'S4' after migration", remaining_s4 == 0)
    finally:
        core.DATA_DB = old_data_db
        if os.path.exists(tmp_db_path):
            os.remove(tmp_db_path)


if __name__ == "__main__":
    test_sepa_signal_logic()
    test_clean_liquid_universe()
    test_stock_dna()
    test_forward_tests_migration(os.path.join(os.path.dirname(__file__), "_migration_test.sqlite3"))

    print("\n==============================")
    if FAILURES:
        print(f"{len(FAILURES)} CHECK(S) FAILED:")
        for f in FAILURES:
            print(" -", f)
        sys.exit(1)
    print("ALL CHECKS PASSED")
