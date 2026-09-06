"""Produce tomorrow's ranked signals.

Run after the close. Everything it reads is from completed candles, and the
model is trained only on trades that had already resolved, so a run dated T
could have been made on the evening of T.

    python scan.py --db market_data.sqlite3                 # today
    python scan.py --db market_data.sqlite3 --asof 2026-08-07
"""
from __future__ import annotations
import argparse, sqlite3, sys
import numpy as np, pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor

import gtfcore as G
from build_events import events_for_symbol, load

FEATS = ["risk_pct", "zone_h_pct", "n_base", "legout_n", "gap", "closing_ok",
         "legout_atr", "zone_age", "arrival", "score", "atr_pct", "relvol",
         "rsi14", "dist_ema200_atr", "dist_ema50_atr", "dist_ema20_atr",
         "prev_close_pct", "gap_in", "target_r_available", "w_trend50",
         "w_trend10", "m_trend50", "d_trend", "m_curve", "w_curve", "coincide",
         "risk_atr"]                    # turnover deliberately excluded
STOP_ATR, TGT_ATR, HOLD = 2.0, 8.0, 60
MIN_TURNOVER_CR = 10.0
RESOLVE_DAYS = 95                       # a trade needs 60 bars to finish
# The model was fitted on actual arrivals, where price sat a median 1.2% above
# the zone and 99% of the time under 9.7%. A zone 50% below price is not a
# setup, it is extrapolation, and the model happily prints +24% for it. Only
# zones price could plausibly reach in the next few sessions are scored.
MAX_APPROACH_PCT = 9.66                 # 99th percentile of training arrivals


def live_zones(df, asof_i):
    """Alive demand zones close enough beneath price to be reachable.

    "Alive" is not enough on its own: a zone 50% below the market is still
    technically untested, but the model has never seen an arrival like that
    and will extrapolate wildly. MAX_APPROACH_PCT keeps scoring inside the
    range the model was actually fitted on.
    """
    O, H, L, C = (df[c].to_numpy()[:asof_i + 1] for c in ("open", "high", "low", "close"))
    A = G.atr(H, L, C, 14)
    out = []
    for z in G.find_zones(O, H, L, C, A, kind="demand"):
        start = z.legout_start + z.legout_n
        if start > asof_i or z.proximal >= C[asof_i] or z.proximal <= z.distal:
            continue
        approach = 100.0 * (C[asof_i] / z.proximal - 1.0)
        if approach > MAX_APPROACH_PCT:
            continue
        if (C[start:asof_i + 1] < z.distal).any():        # broken
            continue
        n_tests, inside = G.zone_tests(z, H, L, C, asof_i)
        if inside:                                        # already in the zone
            continue
        out.append((z, n_tests))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--asof", default=None)
    ap.add_argument("--events", default="/tmp/gtf/events.parquet")
    ap.add_argument("--exits", default="/tmp/gtf/exits.parquet")
    ap.add_argument("--top", type=int, default=25)
    a = ap.parse_args()

    hist = pd.read_parquet(a.events)
    ex = pd.read_parquet(a.exits)
    hist = pd.concat([hist, ex[["x_fix_2_8"]]], axis=1)
    hist["date"] = pd.to_datetime(hist["date"])
    hist = hist[(hist.gap_through == 0) & hist["x_fix_2_8"].notna()]

    con = sqlite3.connect(a.db)
    last = pd.to_datetime(pd.read_sql_query("SELECT MAX(dt) m FROM candles", con).m[0])
    con.close()
    asof = pd.Timestamp(a.asof) if a.asof else last
    if asof > last:
        sys.exit(f"no candles after {last.date()}")

    # train only on trades that had already resolved by `asof`
    tr = hist[hist.date < asof - pd.Timedelta(days=RESOLVE_DAYS)]
    if len(tr) < 6000:
        sys.exit(f"only {len(tr)} resolved trades before {asof.date()}; need 6000")
    use = [f for f in FEATS if tr[f].notna().sum() > 50 and tr[f].nunique() > 1]
    model = HistGradientBoostingRegressor(
        max_depth=3, max_iter=250, learning_rate=0.05, min_samples_leaf=80,
        l2_regularization=1.0, random_state=0).fit(tr[use].to_numpy(),
                                                   tr["x_fix_2_8"].to_numpy())
    thr = float(np.percentile(model.predict(tr[use].to_numpy()), 90))
    print(f"as of {asof.date()}   trained on {len(tr)} resolved trades   "
          f"score threshold {thr:.2f}")

    # market volatility regime, point in time
    con = sqlite3.connect(a.db)
    px = pd.read_sql_query("SELECT dt,symbol,close FROM candles WHERE dt<=?",
                           con, params=(str(asof.date()),))
    syms = [r[0] for r in con.execute(
        "SELECT symbol FROM candles GROUP BY symbol HAVING COUNT(*)>=320")]
    con.close()
    px["dt"] = pd.to_datetime(px["dt"])
    wide = px.pivot_table(index="dt", columns="symbol", values="close")
    idx = (wide / wide.shift(1)).mean(axis=1).fillna(1).cumprod()
    v20 = idx.pct_change().rolling(20).std() * np.sqrt(252) * 100
    high_vol = bool(v20.iloc[-1] > v20.rolling(500, min_periods=120).median().iloc[-1])
    print(f"market 20d vol {v20.iloc[-1]:.1f}%  -> regime "
          f"{'HIGH (trade)' if high_vol else 'LOW (stand down)'}")

    rows = []
    for s in syms:
        df = load(a.db, s)
        df = df[df.index <= asof]
        if len(df) < 320:
            continue
        i = len(df) - 1
        cand = live_zones(df, i)
        if not cand:
            continue
        ev = events_for_symbol(df, s)          # reuse the exact feature code
        if not ev:
            continue
        e = pd.DataFrame(ev)
        # the newest arrival row carries this symbol's current context
        ctx = e.iloc[-1]
        C = df["close"].to_numpy(); A = G.atr(df["high"].to_numpy(),
                                              df["low"].to_numpy(), C, 14)
        vol20 = df["volume"].rolling(20).mean().iloc[-1]
        for z, n_tests in cand:
            r = {"symbol": s, "proximal": z.proximal, "distal": z.distal,
                 "n_base": z.n_base, "legout_n": z.legout_n, "gap": int(z.gap),
                 "closing_ok": int(z.closing_ok), "legout_atr": z.legout_atr,
                 "arrival": n_tests, "score": z.score(n_tests),
                 "zone_age": i - (z.legout_start + z.legout_n - 1),
                 "zone_h_pct": 100 * (z.proximal - z.distal) / z.proximal,
                 "risk_pct": 100 * (z.proximal - z.distal) / z.proximal,
                 "risk_atr": (z.proximal - z.distal) / A[i],
                 "atr_pct": 100 * A[i] / C[i], "rsi14": ctx.rsi14,
                 "relvol": ctx.relvol, "dist_ema200_atr": ctx.dist_ema200_atr,
                 "dist_ema50_atr": ctx.dist_ema50_atr,
                 "dist_ema20_atr": ctx.dist_ema20_atr,
                 "prev_close_pct": 100 * (C[i] / z.proximal - 1),
                 "gap_in": 0.0, "target_r_available": ctx.target_r_available,
                 "w_trend50": ctx.w_trend50, "w_trend10": ctx.w_trend10,
                 "m_trend50": ctx.m_trend50, "d_trend": ctx.d_trend,
                 "m_curve": ctx.m_curve, "w_curve": ctx.w_curve,
                 "coincide": ctx.coincide,
                 "turnover_cr": C[i] * vol20 / 1e7,
                 "entry": z.proximal, "atr_now": A[i],
                 # indicative only: the real levels are set from the ATR on the
                 # day the limit fills, which is not knowable yet
                 "stop_indic": z.proximal - STOP_ATR * A[i],
                 "target_indic": z.proximal + TGT_ATR * A[i]}
            rows.append(r)
    if not rows:
        print("no live zones"); return
    cand = pd.DataFrame(rows)
    # one row per symbol: the nearest qualifying zone, so the list is not
    # eight variations of the same name
    cand = (cand.sort_values(["symbol", "prev_close_pct"])
                .groupby("symbol", as_index=False).first())
    cand["pred"] = model.predict(cand[use].to_numpy())
    cand["signal"] = (cand.pred >= thr) & cand.turnover_cr.ge(MIN_TURNOVER_CR) & high_vol
    cols = ["symbol", "pred", "signal", "entry", "stop_indic", "target_indic",
            "prev_close_pct", "zone_h_pct", "atr_pct", "legout_atr", "zone_age",
            "arrival", "turnover_cr"]
    out = cand.sort_values("pred", ascending=False)
    print(f"\n{int(cand.signal.sum())} signals of {len(cand)} live zones. Top {a.top} by score:")
    print(out[cols].head(a.top).round(2).to_string(index=False))
    out.to_csv(f"signals_{asof.date()}.csv", index=False)
    print(f"\nwritten signals_{asof.date()}.csv")
    print("\nOrders are resting BUY LIMITs at `entry`, good for the next session.")
    print(f"On the day it fills: stop = entry - {STOP_ATR} x ATR14, "
          f"target = entry + {TGT_ATR} x ATR14, both using that day's ATR.")
    print(f"Time stop {HOLD} trading days. Reject the fill if the open is below the stop.")
    print("stop_indic / target_indic use today's ATR and are indicative only.")


if __name__ == "__main__":
    main()
