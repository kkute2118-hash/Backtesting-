"""Generate every GTF demand-zone arrival across the Nifty 500 daily store.

An "event" is one arrival of price at the proximal line of a daily demand
zone: the moment a GTF trader's resting limit order would fill. Each event
carries the zone's own properties, the multi-timeframe context as it stood
on that date, and the forward path summary needed to evaluate any exit
policy later. Nothing in a row uses information after its own date except
the deliberately-named fwd_* columns, which exist to be the outcome.
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
import time

import numpy as np
import pandas as pd

import gtfcore as G

R_GRID = [0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0]
PCT_GRID = [3, 5, 7, 10, 12, 15, 18, 21]
HORIZONS = [5, 10, 20, 40, 60, 120]
# stop placements, as ATR below the distal line (K) and below the entry (M),
# so a stop wider than the zone can be tested against the video's own
STOP_K = [0.0, 0.25, 0.5, 1.0]
STOP_M = [1.0, 1.5, 2.0, 3.0]
# targets in ATR above the planned entry: stop-independent, so any
# (stop, target) pair can be scored in R afterwards
TGT_ATR = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 8.0, 10.0]
MAX_HOLD = 120


def load(db, symbol):
    con = sqlite3.connect(db)
    df = pd.read_sql_query(
        "SELECT dt, open, high, low, close, volume FROM candles "
        "WHERE symbol=? ORDER BY dt", con, params=(symbol,))
    con.close()
    df["dt"] = pd.to_datetime(df["dt"])
    return df.set_index("dt")


def _first_break(L, fl, j, level):
    """First bar (0 = entry bar) whose low trades at or below `level`."""
    if not np.isfinite(level):
        return -1
    if L[j] <= level:
        return 0
    hits = np.nonzero(fl <= level)[0]
    return int(hits[0]) + 1 if len(hits) else -1


def _tr(state, k, src):
    """Trend state, or -9 when the average is not yet defined (which is not
    the same thing as sideways)."""
    if k < 0 or k >= len(state) or not np.isfinite(src[k]):
        return -9
    return int(state[k])


def _curve_state(px, cv):
    """A9 - which of the five curve sections price sits in.

    The video takes the trade when no opposing zone exists at all ("कोई सप्लाई
    जोन तो है नहीं ... सिर्फ डिमांड जोन का लोकेशन मार्क किया"), so that case is
    named rather than dropped.
    """
    d, s_ = cv["dem_prox"], cv["sup_prox"]
    if not np.isfinite(d):
        return "no_demand"
    if px <= d:
        return "very_low"
    if not np.isfinite(s_):
        return "no_supply"
    span = s_ - d
    if span <= 0:
        return "inverted"
    f = (px - d) / span
    if f >= 1.0:
        return "very_high"
    return ("low", "equilibrium", "high")[min(2, int(f * 3))]


def htf_context(bars, last_idx, zones_d, zones_s, upto_daily, px):
    """A9 - nearest fresh demand below and fresh supply above on a higher
    timeframe, and where price sits on the curve between them."""
    nil = {"curve": np.nan, "dem_prox": np.nan, "sup_prox": np.nan}
    k = int(np.searchsorted(last_idx, upto_daily, side="right")) - 1
    if k < 1:
        return nil
    H = bars["high"].to_numpy()[:k + 1]
    L = bars["low"].to_numpy()[:k + 1]
    C = bars["close"].to_numpy()[:k + 1]

    def nearest(zs, below):
        # "below" means the zone floor is under price, which includes the case
        # of price sitting inside the zone - that is the video's "very low on
        # the curve", not an absent zone.
        best = None
        for z in zs:
            if z.legout_start + z.legout_n - 1 > k:
                continue
            if below and not (z.distal < px):
                continue
            if not below and not (z.distal > px):
                continue
            # still alive?
            tail = C[z.legout_start + z.legout_n:k + 1]
            if len(tail):
                if below and (tail < z.distal).any():
                    continue
                if not below and (tail > z.distal).any():
                    continue
            n, _ = G.zone_tests(z, H, L, C, k)
            if n > 0:
                continue
            if best is None or (below and z.proximal > best.proximal) or \
               (not below and z.proximal < best.proximal):
                best = z
        return best

    d = nearest(zones_d, True)
    s = nearest(zones_s, False)
    if d is None or s is None:
        return {"curve": np.nan, "dem_prox": d.proximal if d else np.nan,
                "sup_prox": s.proximal if s else np.nan}
    span = s.proximal - d.proximal
    if span <= 0:
        return {"curve": np.nan, "dem_prox": d.proximal, "sup_prox": s.proximal}
    return {"curve": (px - d.proximal) / span,
            "dem_prox": d.proximal, "sup_prox": s.proximal}


def weekly_supply_target(bars, last_idx, zones_s, upto_daily, px):
    """A11 - proximal of the nearest fresh supply zone on the trending
    timeframe, read at the moment of arrival."""
    k = int(np.searchsorted(last_idx, upto_daily, side="right")) - 1
    if k < 1:
        return np.nan
    H = bars["high"].to_numpy()[:k + 1]
    L = bars["low"].to_numpy()[:k + 1]
    C = bars["close"].to_numpy()[:k + 1]
    best = np.nan
    for z in zones_s:
        if z.legout_start + z.legout_n - 1 > k or z.distal <= px:
            continue
        tail = C[z.legout_start + z.legout_n:k + 1]
        if len(tail) and (tail > z.distal).any():
            continue
        n, _ = G.zone_tests(z, H, L, C, k)
        if n > 0:
            continue
        if not np.isfinite(best) or z.proximal < best:
            best = z.proximal
    return best


def events_for_symbol(df, symbol, max_arrivals=3, min_bars=320):
    n = len(df)
    if n < min_bars:
        return []
    O = df["open"].to_numpy(); H = df["high"].to_numpy()
    L = df["low"].to_numpy(); C = df["close"].to_numpy(); V = df["volume"].to_numpy()
    dates = df.index

    A = G.atr(H, L, C, 14)
    e200 = G.ema(C, 200); e50 = G.ema(C, 50); e20 = G.ema(C, 20)
    s50 = G.sma(C, 50)
    r14 = G.rsi(C, 14)
    vol20 = pd.Series(V).rolling(20, min_periods=20).mean().to_numpy()
    d_trend = G.trend_state(s50, 6)

    wb, _, wlast = G.aggregate(df, "W")
    mb, _, mlast = G.aggregate(df, "M")
    w_s50 = G.sma(wb["close"].to_numpy(), 50)
    m_s50 = G.sma(mb["close"].to_numpy(), 50)
    # weekly SMA50 needs 50 weeks; with ~5.5y of data that leaves ~4y usable.
    # A 10-period weekly average is also carried so the trend gate can be
    # tested without throwing away the first year.
    w_s10 = G.sma(wb["close"].to_numpy(), 10)
    m_s10 = G.sma(mb["close"].to_numpy(), 10)
    w_tr50 = G.trend_state(w_s50, 6); w_tr10 = G.trend_state(w_s10, 6)
    m_tr50 = G.trend_state(m_s50, 6); m_tr10 = G.trend_state(m_s10, 6)

    wo = wb["open"].to_numpy(); wh = wb["high"].to_numpy()
    wl = wb["low"].to_numpy(); wc = wb["close"].to_numpy()
    mo = mb["open"].to_numpy(); mh = mb["high"].to_numpy()
    ml = mb["low"].to_numpy(); mc = mb["close"].to_numpy()

    wz_d = G.find_zones(wo, wh, wl, wc, kind="demand")
    wz_s = G.find_zones(wo, wh, wl, wc, kind="supply")
    mz_d = G.find_zones(mo, mh, ml, mc, kind="demand")
    mz_s = G.find_zones(mo, mh, ml, mc, kind="supply")
    dz = G.find_zones(O, H, L, C, A, kind="demand")

    out = []
    for z in dz:
        start = z.legout_start + z.legout_n
        if start >= n:
            continue
        prox, dist = z.proximal, z.distal
        if dist <= 0 or prox <= dist:
            continue
        if (prox - dist) / prox < 0.001:      # degenerate: no risk to speak of
            continue
        inside = False
        arrivals = 0
        for j in range(start, n):
            if C[j] < dist:          # zone broken, stop tracking it
                break
            if not inside and L[j] <= prox:
                inside = True
                if arrivals < max_arrivals and j > 0 and j + 20 < n and np.isfinite(A[j - 1]):
                    _r = _row(symbol, dates, O, H, L, C, V, A, e200, e50,
                                    e20, r14, vol20, d_trend, z, j, arrivals,
                                    wb, wlast, wz_d, wz_s, mb, mlast, mz_d, mz_s,
                                    w_tr50, w_tr10, m_tr50, m_tr10,
                              w_s50, w_s10, m_s50, m_s10, s50, n)
                    if _r is not None:
                        out.append(_r)
                arrivals += 1
            if inside and C[j] > prox:
                inside = False
    return out


def _row(symbol, dates, O, H, L, C, V, A, e200, e50, e20, r14, vol20, d_trend,
         z, j, arrivals, wb, wlast, wz_d, wz_s, mb, mlast, mz_d, mz_s,
         w_tr50, w_tr10, m_tr50, m_tr10, w_s50, w_s10, m_s50, m_s10, s50, n):
    prox, dist = z.proximal, z.distal
    # A GTF entry is a resting limit order placed before the session opens, so
    # every input to the decision has to be readable on the previous close.
    # Only the fill itself belongs to bar j.
    ctx = j - 1
    entry = min(prox, O[j])          # gapped opens fill below the line
    risk = prox - dist               # planned risk, so R is comparable across fills
    a = A[ctx]
    px = C[ctx]

    wk = int(np.searchsorted(wlast, ctx, side="right")) - 1
    mk = int(np.searchsorted(mlast, ctx, side="right")) - 1

    mcurve = htf_context(mb, mlast, mz_d, mz_s, ctx, px)
    wcurve = htf_context(wb, wlast, wz_d, wz_s, ctx, px)
    wtgt = weekly_supply_target(wb, wlast, wz_s, ctx, px)

    # Forward path. Bar 0 is the entry bar; within it, whether the low that
    # filled us printed before or after the high that might have paid us is
    # unknowable. So the stop may trigger on bar 0 and the target may not -
    # targets are measured from bar 1 onward. The matched control uses the
    # same convention, so the two remain comparable.
    end = min(j + MAX_HOLD, n - 1)
    fh = H[j + 1:end + 1]; fl = L[j + 1:end + 1]
    fo = O[j + 1:end + 1]; fc = C[j + 1:end + 1]
    if len(fc) == 0:
        return None
    run_max = np.maximum.accumulate(fh)
    run_min = np.minimum.accumulate(fl)

    row = {
        "symbol": symbol, "date": dates[j], "bar": j, "arrival": arrivals,
        # --- zone (A2/A3/A5/A6/A12)
        "n_base": z.n_base, "legout_n": z.legout_n, "gap": int(z.gap),
        "closing_ok": int(z.closing_ok), "legout_atr": z.legout_atr,
        "pattern": "RBR" if C[z.legin_idx] >= O[z.legin_idx] else "DBR",
        "score": z.score(arrivals),
        "zone_age": j - (z.legout_start + z.legout_n - 1),
        "zone_h_pct": 100.0 * (prox - dist) / prox,
        # --- trade geometry
        "entry": entry, "entry_plan": prox, "stop": dist,
        "risk_pct": 100.0 * risk / prox,
        "risk_atr": risk / a if a > 0 else np.nan,
        # the open gapped below the stop: the limit and the stop trigger on the
        # same tick, so this is not a trade the system can actually take
        "gap_through": int(entry <= dist),
        "fill_slip_r": (entry - prox) / risk if risk > 0 else np.nan,
        # --- context (A7/A9/A11)
        "w_trend50": _tr(w_tr50, wk, w_s50), "w_trend10": _tr(w_tr10, wk, w_s10),
        "m_trend50": _tr(m_tr50, mk, m_s50), "m_trend10": _tr(m_tr10, mk, m_s10),
        "d_trend": _tr(d_trend, ctx, s50),
        "m_curve": mcurve["curve"], "w_curve": wcurve["curve"],
        "m_curve_state": _curve_state(px, mcurve),
        "w_curve_state": _curve_state(px, wcurve),
        # A13 / "fully coinciding": does the daily zone sit on the monthly one?
        "coincide": int(np.isfinite(mcurve["dem_prox"]) and dist <= mcurve["dem_prox"]),
        "w_sup_target": wtgt,
        "target_r_available": (wtgt - entry) / risk if np.isfinite(wtgt) and risk > 0 else np.nan,
        # --- generic features for the discovery phase
        "dist_ema200_atr": (px - e200[ctx]) / a if a > 0 else np.nan,
        "dist_ema50_atr": (px - e50[ctx]) / a if a > 0 else np.nan,
        "dist_ema20_atr": (px - e20[ctx]) / a if a > 0 else np.nan,
        "above_ema200": int(px > e200[ctx]) if np.isfinite(e200[ctx]) else -1,
        "rsi14": r14[ctx], "atr_pct": 100.0 * a / px,
        "relvol": V[ctx] / vol20[ctx] if np.isfinite(vol20[ctx]) and vol20[ctx] > 0 else np.nan,
        "prev_close_pct": 100.0 * (px / prox - 1.0),
        "gap_in": 100.0 * (O[j] / C[ctx] - 1.0),
        "turnover_cr": px * vol20[ctx] / 1e7 if np.isfinite(vol20[ctx]) else np.nan,
    }

    # stop: bar 0 counts - we were filled, and then the low broke the level
    if L[j] <= dist:
        row["stop_bar"] = 0
        row["stop_fill"] = float(dist)
    else:
        hits = np.nonzero(fl <= dist)[0]
        if len(hits):
            k = int(hits[0])
            row["stop_bar"] = k + 1
            row["stop_fill"] = float(min(dist, fo[k]))
        else:
            row["stop_bar"] = -1
            row["stop_fill"] = np.nan

    # alternative stops (A27): first bar whose low breaks each level
    for K in STOP_K:
        lv = dist - K * a if a > 0 else dist
        row[f"sK{K}_bar"] = _first_break(L, fl, j, lv)
        row[f"sK{K}_px"] = lv
    for M in STOP_M:
        lv = prox - M * a if a > 0 else np.nan
        row[f"sM{M}_bar"] = _first_break(L, fl, j, lv) if np.isfinite(lv) else -1
        row[f"sM{M}_px"] = lv
    # alternative targets (A28), in ATR above the planned entry
    for M in TGT_ATR:
        lv = prox + M * a if a > 0 else np.nan
        hh = np.nonzero(run_max >= lv)[0] if np.isfinite(lv) else []
        row[f"gA{M}_bar"] = int(hh[0]) + 1 if len(hh) else -1
        row[f"gA{M}_px"] = lv
    row["atr_at_entry"] = a

    # targets are measured off the planned entry, so R is comparable across fills
    for rm in R_GRID:
        hits = np.nonzero(run_max >= prox + rm * risk)[0]
        row[f"t{rm}R_bar"] = int(hits[0]) + 1 if len(hits) else -1
    for p in PCT_GRID:
        hits = np.nonzero(run_max >= prox * (1 + p / 100.0))[0]
        row[f"t{p}pct_bar"] = int(hits[0]) + 1 if len(hits) else -1

    for hzn in HORIZONS:
        k = min(hzn - 1, len(fc) - 1)
        row[f"mfe{hzn}"] = 100.0 * (run_max[k] / entry - 1.0)
        row[f"mae{hzn}"] = 100.0 * (run_min[k] / entry - 1.0)
        row[f"ret{hzn}"] = 100.0 * (fc[k] / entry - 1.0)
    row["n_fwd"] = len(fc) - 1
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()

    con = sqlite3.connect(a.db)
    syms = [r[0] for r in con.execute(
        "SELECT symbol FROM candles GROUP BY symbol HAVING COUNT(*) >= 320 ORDER BY symbol")]
    con.close()
    if a.limit:
        syms = syms[:a.limit]
    print(f"{len(syms)} symbols", flush=True)

    rows = []
    t0 = time.time()
    for i, s in enumerate(syms):
        try:
            rows.extend(events_for_symbol(load(a.db, s), s))
        except Exception as e:                       # noqa: BLE001
            print(f"  !! {s}: {type(e).__name__}: {e}", file=sys.stderr)
        if (i + 1) % 50 == 0:
            print(f"  {i+1}/{len(syms)}  {len(rows)} events  {time.time()-t0:.0f}s", flush=True)
    df = pd.DataFrame(rows)
    df.to_parquet(a.out, index=False)
    print(f"{len(df)} events -> {a.out}  ({time.time()-t0:.0f}s)")
    print(df["date"].min(), "..", df["date"].max())


if __name__ == "__main__":
    main()
