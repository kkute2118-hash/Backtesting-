"""One candidate queue across every signal source, on identical terms.

You can take 2-3 trades a week. The system produces thousands. So the job is
no longer "does this strategy work" but "given everything that fired this
week, which two are the best". That is a ranking problem, and ranking is only
fair if every candidate is measured the same way.

So this file rebuilds every source - S1, S2, S3, S4, GTF zones, and the
liquidity setups - into one table where:

  * entry is the close of the signal day, for everyone
  * the stop is 2 ATR below entry, for everyone
  * the exit policy is identical (breakeven at +15%, 60-bar time stop)
  * the features are computed from price alone, identically, so no source
    gets ranked highly merely because its own scoring column is on a
    different scale

Source-specific scores are kept as features, but as ordinary numbers the
model may or may not use. Everything is read at the signal bar using bars up
to and including it, never later.
"""
from __future__ import annotations
import argparse, sqlite3, time
import numpy as np, pandas as pd
import gtfcore as G
import liq as Q
from build_events import load

HOLD, STOP_ATR, BE_AT = 60, 2.0, 15.0


def features(df):
    """Per-bar context. Row j uses bars <= j only."""
    O = df["open"].to_numpy(); H = df["high"].to_numpy()
    L = df["low"].to_numpy(); C = df["close"].to_numpy(); V = df["volume"].to_numpy()
    n = len(C)
    A = G.atr(H, L, C, 14)
    e10, e20, e50, e200 = (G.ema(C, k) for k in (10, 20, 50, 200))
    s50 = G.sma(C, 50)
    v20 = pd.Series(V).rolling(20, min_periods=20).mean().to_numpy()
    ret = pd.Series(C).pct_change()
    hi52 = pd.Series(H).rolling(250, min_periods=60).max().to_numpy()
    lo52 = pd.Series(L).rolling(250, min_periods=60).min().to_numpy()
    with np.errstate(invalid="ignore", divide="ignore"):
        f = {
            "atr_pct": 100 * A / C,
            "rsi14": G.rsi(C, 14),
            "relvol": V / v20,
            "turnover_cr": C * v20 / 1e7,
            "dist_ema20_atr": (C - e20) / A,
            "dist_ema50_atr": (C - e50) / A,
            "dist_ema200_atr": (C - e200) / A,
            "ema20_over_50": 100 * (e20 / e50 - 1),
            "ema50_over_200": 100 * (e50 / e200 - 1),
            "pct_from_52w_high": 100 * (C / hi52 - 1),
            "pct_above_52w_low": 100 * (C / lo52 - 1),
            "ret_5d": 100 * pd.Series(C).pct_change(5).to_numpy(),
            "ret_20d": 100 * pd.Series(C).pct_change(20).to_numpy(),
            "ret_60d": 100 * pd.Series(C).pct_change(60).to_numpy(),
            "ret_120d": 100 * pd.Series(C).pct_change(120).to_numpy(),
            "vol20d": ret.rolling(20).std().to_numpy() * np.sqrt(252) * 100,
            "slope50": 100 * (s50 / pd.Series(s50).shift(20).to_numpy() - 1),
            "body_pct": 100 * np.abs(C - O) / np.where(H - L > 0, H - L, np.nan),
            "up_wick_pct": 100 * (H - np.maximum(O, C)) / np.where(H - L > 0, H - L, np.nan),
            "dn_wick_pct": 100 * (np.minimum(O, C) - L) / np.where(H - L > 0, H - L, np.nan),
            "gap_pct": 100 * (O / np.roll(C, 1) - 1),
        }
    f["gap_pct"][0] = np.nan
    for freq, tag in (("W", "w"), ("M", "m")):
        b, _, last = G.aggregate(df, freq)
        bc = b["close"].to_numpy()
        sm = G.sma(bc, 20 if freq == "W" else 10)
        sl = np.full(len(bc), np.nan)
        k = 6 if freq == "W" else 3
        sl[k:] = 100 * (sm[k:] / sm[:-k] - 1)
        pos = np.searchsorted(last, np.arange(n), side="right") - 1
        ok = pos >= 0
        col = np.full(n, np.nan)
        col[ok] = sl[pos[ok]]
        f[f"{tag}_slope"] = col
    out = pd.DataFrame(f)
    out["atr"] = A
    return out


def walk_be(O, H, L, C, j, entry, atr, hold=HOLD, stop_atr=STOP_ATR, be=BE_AT):
    """Identical exit for every candidate. Bar 0 may stop us; it may not pay us."""
    n = len(C); end = min(j + hold, n - 1)
    stop = entry - stop_atr * atr
    trig = entry * (1 + be / 100.0)
    for k in range(j, end + 1):
        if L[k] <= stop:
            px = min(stop, O[k]) if k > j else stop
            return 100.0 * (px / entry - 1) - Q.COST, k - j
        if H[k] >= trig:
            stop = max(stop, entry)
    return 100.0 * (C[end] / entry - 1) - Q.COST, end - j


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True); ap.add_argument("--out", required=True)
    a = ap.parse_args()

    con = sqlite3.connect(a.db)
    cal = pd.read_sql_query("SELECT symbol, dt FROM candles ORDER BY symbol, dt", con)
    con.close()
    cal["dt"] = pd.to_datetime(cal["dt"])
    cal["bar"] = cal.groupby("symbol").cumcount()
    barkey = cal.set_index(["symbol", "dt"])["bar"]

    cand = []
    s4 = pd.read_parquet("/tmp/gtf/s1s4_exits.parquet")
    s4["date"] = pd.to_datetime(s4["entry_date"])
    s4["bar"] = barkey.reindex(pd.MultiIndex.from_arrays([s4.ticker, s4.date])).to_numpy()
    cand.append(pd.DataFrame({"symbol": s4.ticker, "bar": s4.bar,
                              "source": s4.strategy, "src_score": s4.score}))

    ev = pd.read_parquet("/tmp/gtf/events.parquet")
    ev = ev[ev.gap_through == 0]
    cand.append(pd.DataFrame({"symbol": ev.symbol, "bar": ev.bar,
                              "source": "GTF", "src_score": ev.score}))

    lq = pd.read_parquet("/tmp/gtf/liq.parquet")
    lq = lq[lq.side.eq("long")]
    cand.append(pd.DataFrame({"symbol": lq.symbol, "bar": lq.bar,
                              "source": "LIQ_" + lq.kind, "src_score": lq.level_touches}))

    c = pd.concat(cand, ignore_index=True).dropna(subset=["bar"])
    c["bar"] = c.bar.astype(int)
    print(f"{len(c)} raw candidates from {c.source.nunique()} sources")
    print(c.source.value_counts().to_string())

    rows = []
    t0 = time.time()
    for i, (sym, grp) in enumerate(c.groupby("symbol", sort=True)):
        df = load(a.db, sym)
        n = len(df)
        F = features(df)
        O = df["open"].to_numpy(); H = df["high"].to_numpy()
        L = df["low"].to_numpy(); C = df["close"].to_numpy()
        g = grp[(grp.bar >= 220) & (grp.bar < n)]
        if not len(g):
            continue
        agg = g.groupby(["bar", "source"])["src_score"].max().reset_index()
        fcols = [c_ for c_ in F.columns if c_ != "atr"]
        for r in agg.itertuples():
            j = int(r.bar)
            atr = F.atr.iloc[j]
            if not np.isfinite(atr) or atr <= 0:
                continue
            p, b = walk_be(O, H, L, C, j, float(C[j]), float(atr))
            row = {"symbol": sym, "bar": j, "date": df.index[j],
                   "source": r.source, "src_score": float(r.src_score),
                   "entry": float(C[j]), "stop_px": float(C[j] - STOP_ATR * atr),
                   "p": p, "b": b, "fwd_bars": n - 1 - j}
            row.update(F[fcols].iloc[j].to_dict())
            rows.append(row)
        if (i + 1) % 100 == 0:
            print(f"  {i+1} symbols  {len(rows)} rows  {time.time()-t0:.0f}s", flush=True)

    d = pd.DataFrame(rows)
    d = d[d.fwd_bars >= 20].reset_index(drop=True)
    d["n_sources"] = d.groupby(["symbol", "bar"])["source"].transform("size")
    d.to_parquet(a.out, index=False)
    print(f"\n{len(d)} scoreable candidates -> {a.out}  ({time.time()-t0:.0f}s)")
    print(d.groupby("source")["p"].agg(["size", "mean"]).round(2).to_string())


if __name__ == "__main__":
    main()
