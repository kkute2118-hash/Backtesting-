"""The system, end to end. Run it, get this week's trades with sizes.

    python system.py                    # today
    python system.py 2026-08-07         # any past date, as it would have looked
    python system.py 2026-08-07 500000  # with your own capital

Every rule below earned its place by surviving a test that could have killed
it. Rules that did not survive are absent, however good they sound: the
liquidity sweep, the run breakout, the source score gates, the trend filters,
and the expected-return model are all in the findings as failures.

WHAT THIS IS
  A ranking system on top of signal sources you already have. It does not
  find new setups. It decides which two of the ~300 weekly candidates to
  take, which is the decision that was actually costing you money.

WHAT IT IS NOT
  A high win-rate system. It wins about a third of the time. The money comes
  from the winners running to the 60-bar limit while the losers are cut at
  2 ATR. If a run of six losses would make you abandon it, do not start:
  six straight losses is an ordinary event at a 33% win rate (9% likely).
"""
from __future__ import annotations
import sys
import numpy as np, pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
import rank as RK, regime as RG

DB = ("/tmp/claude-0/-home-user-Backtesting-/52d73d1b-702d-51ce-a95b-beb9647ef04c"
      "/scratchpad/data/market_data.sqlite3")

FLOOR_CR = 25.0      # turnover floor. Below this the backtest is fiction.
RISK_PCT = 1.0       # of equity, per trade
STOP_ATR = 2.0
BREAKEVEN_AT = 15.0  # percent
MAX_HOLD = 60        # trading days
MAX_POSITION_PCT = 25.0
RESOLVE_DAYS = RK.RESOLVE_DAYS


def budget(breadth):
    """Trades per week. More when the market is frightened.

    THIN EVIDENCE - the only rule here measured on fewer than ten episodes.
    Buying into low breadth returned +0.386 and +1.482 R in the two scored
    episodes, and index-below-200 returned +2.303, +0.106, +0.202 in three.
    All positive, but each is one drawdown that happened to bounce, and this
    sample contains no sustained bear market. Set TILT=False to drop it; the
    system loses about 1.5 points of CAGR and gains nothing back.
    """
    if not np.isfinite(breadth):
        return 2
    if breadth < 30: return 4
    if breadth < 40: return 3
    return 2


def fit_mark(pool, asof):
    """Train on candidates that had RESOLVED before `asof`. Never on the future."""
    train = pool[pool.date < asof - pd.Timedelta(days=RESOLVE_DAYS)]
    if len(train) < RK.MIN_TRAIN:
        raise ValueError(f"only {len(train)} resolved candidates before {asof.date()}")
    feats = [f for f in RK.FEATS + [c for c in pool.columns if c.startswith("is_")]
             if f in train.columns and train[f].notna().sum() > 100
             and train[f].nunique() > 1]
    m = HistGradientBoostingClassifier(
        max_depth=3, max_iter=300, learning_rate=0.05, min_samples_leaf=100,
        l2_regularization=1.0, random_state=0).fit(
            train[feats].to_numpy(), (train.p > 0).astype(int).to_numpy())
    return m, feats, m.predict_proba(train[feats].to_numpy())[:, 1]


def run(asof=None, equity=1_000_000.0, tilt=True):
    pool = RK.prepare()
    pool = pool[pool.turnover_cr >= FLOOR_CR]
    asof = pd.Timestamp(asof) if asof is not None else pool.date.max()
    reg = RG.build(DB)
    reg = reg[reg.index <= asof]
    breadth = float(reg.breadth_ma20.iloc[-1]) if len(reg) else np.nan
    n = budget(breadth) if tilt else 2

    m, feats, ref = fit_mark(pool, asof)
    live = pool[pool.date == asof].copy()
    if not len(live):
        return None, breadth, n, asof
    live["pwin"] = m.predict_proba(live[feats].to_numpy())[:, 1]
    live["mark"] = [100 * (ref < v).mean() for v in live.pwin]
    live = live.sort_values("mark", ascending=False).drop_duplicates("symbol")

    out = live.head(n).copy()
    out["stop"] = out.entry - STOP_ATR * out.entry * out.atr_pct / 100
    out["stop_pct"] = 100 * (out.entry - out.stop) / out.entry
    risk_amt = equity * RISK_PCT / 100
    out["shares"] = np.minimum(risk_amt / (out.entry - out.stop),
                               equity * MAX_POSITION_PCT / 100 / out.entry).astype(int)
    out["capital"] = (out.shares * out.entry).round(0)
    out["risk_rs"] = (out.shares * (out.entry - out.stop)).round(0)
    out["breakeven_at"] = (out.entry * (1 + BREAKEVEN_AT / 100)).round(1)
    return out, breadth, n, asof


if __name__ == "__main__":
    asof = sys.argv[1] if len(sys.argv) > 1 else None
    eq = float(sys.argv[2]) if len(sys.argv) > 2 else 1_000_000.0
    out, breadth, n, asof = run(asof, eq)
    print(f"\nas of {asof.date()}   capital Rs {eq:,.0f}   "
          f"market breadth {breadth:.0f}% above 200 DMA   -> budget {n} trades this week\n")
    if out is None or not len(out):
        print("no candidates fired on this date."); raise SystemExit
    cols = ["symbol", "source", "mark", "entry", "stop", "stop_pct",
            "shares", "capital", "risk_rs", "breakeven_at"]
    print(out[cols].round(2).to_string(index=False))
    print(f"\n  stop      {STOP_ATR:.0f} ATR below entry, never widened")
    print(f"  breakeven move the stop to entry once price reaches +{BREAKEVEN_AT:.0f}%")
    print(f"  time exit close the trade after {MAX_HOLD} trading days regardless")
    print(f"  total risk if every stop hits: Rs {out.risk_rs.sum():,.0f} "
          f"({100*out.risk_rs.sum()/eq:.1f}% of capital)")
