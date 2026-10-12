"""Rulebook v1 backtest: one bar-by-bar loop on closed 15-minute bars.

Sections: data preparation, setups (A_SWEEP > B_TRIPLE > C_PULLBACK >
D_NBREAKOUT), risk (per-trade and per-day limits) and management (hard stop
and target, break-even at 50% of the way, swing trail from 80%). Each
instrument is its own account. A signal on bar i fills at bar i+1's open.

Usage (from backend/):
  python -m app.engine.rb1.backtest DATA_DIR --group all --months 12 --capital 10000 --out OUT_DIR
  DATA_DIR holds SYMBOL_5m.csv.gz files (time, open, high, low, close, volume,
  taker_buy_volume for crypto, spread for Dukascopy). --months 0 = all history.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from . import candles as K
from . import config as C
from . import delta as D
from . import structure as S
from .levels import Level, confluence, distance, triple_zones, value_area

DAY = np.int64(86_400_000_000_000)
NS15 = np.int64(15 * 60 * 1_000_000_000)


# ------------------------------------------------------------------ data
def load_5m(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path)
    df["time"] = pd.to_datetime(df["time"], utc=True)
    df = df.set_index("time").sort_index()
    if "taker_buy_volume" not in df:
        df["taker_buy_volume"] = np.nan
    if "spread" not in df:
        df["spread"] = 0.0
    return df


def resample(df5: pd.DataFrame, rule: str) -> pd.DataFrame:
    return df5.resample(rule, label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum",
         "taker_buy_volume": lambda s: s.sum(min_count=1), "spread": "mean"}).dropna(subset=["close"])


@dataclass
class Prepared:
    symbol: str
    group: str
    t: np.ndarray            # 15m open times, int64 ns
    o: np.ndarray; h: np.ndarray; l: np.ndarray; c: np.ndarray
    v: np.ndarray; tb: np.ndarray; sp: np.ndarray
    atr: np.ndarray; cls: np.ndarray; ema20: np.ndarray
    day: np.ndarray          # day id per bar (group boundary)
    pdh: np.ndarray; pdl: np.ndarray; vah: np.ndarray; val: np.ndarray
    cdh: np.ndarray; cdl: np.ndarray; datr: np.ndarray
    trend: np.ndarray; h1_sh: np.ndarray; h1_sl: np.ndarray
    piv_h: np.ndarray; piv_l: np.ndarray       # 15m pivot indices
    obs: np.ndarray          # rows: created_ns, lo, hi, side, mitig_idx


def prepare(symbol: str, df5: pd.DataFrame) -> Prepared:
    group = C.group_of(symbol)
    m15 = resample(df5, C.EXEC_TF)
    t = m15.index.asi8.copy()
    o, h, l, c = (m15[k].to_numpy(float) for k in ("open", "high", "low", "close"))
    v, tb, sp = (m15[k].to_numpy(float) for k in ("volume", "taker_buy_volume", "spread"))
    prev_c = np.r_[c[0], c[:-1]]
    tr = np.maximum(h - l, np.maximum(abs(h - prev_c), abs(l - prev_c)))
    atr = pd.Series(tr).rolling(C.ATR_LEN).mean().to_numpy()
    cls = K.classify_all(o, h, l, c, atr)
    ema20 = pd.Series(c).ewm(span=20, adjust=False).mean().to_numpy()

    # days at the group's boundary
    off = np.int64(C.DAY_BOUNDARY_UTC_HOURS[group]) * np.int64(3_600_000_000_000)
    day = (t - off) // DAY
    days = pd.DataFrame({"day": day, "h": h, "l": l, "c": c}).groupby("day").agg(
        h=("h", "max"), l=("l", "min"), c=("c", "last"))
    dprev_c = days.c.shift()
    dtr = np.maximum(days.h - days.l, np.maximum(abs(days.h - dprev_c), abs(days.l - dprev_c)))
    days["atr"] = dtr.rolling(C.ATR_LEN).mean()
    # value area of each day from its 5m bars (typical price x volume)
    d5 = (df5.index.asi8 - off) // DAY
    tp = ((df5.high + df5.low + df5.close) / 3).to_numpy()
    vol5 = df5.volume.to_numpy(float)
    va = {}
    order = np.argsort(d5, kind="stable")
    d5s, tps, vs = d5[order], tp[order], vol5[order]
    bounds = np.flatnonzero(np.diff(d5s)) + 1
    for a, b in zip(np.r_[0, bounds], np.r_[bounds, len(d5s)]):
        va[d5s[a]] = value_area(tps[a:b], vs[a:b])
    days["val"] = [va.get(d, None)[0] if va.get(d) else np.nan for d in days.index]
    days["vah"] = [va.get(d, None)[1] if va.get(d) else np.nan for d in days.index]
    prev = days.shift()                       # the previous day with data
    pdh = prev.h.reindex(day).to_numpy(); pdl = prev.l.reindex(day).to_numpy()
    vah = prev.vah.reindex(day).to_numpy(); val = prev.val.reindex(day).to_numpy()
    datr = prev.atr.reindex(day).to_numpy()
    s = pd.Series(h).groupby(day).cummax().shift()
    cdh = np.where(pd.Series(day).diff().fillna(1).to_numpy() != 0, np.nan, s.to_numpy())
    s = pd.Series(l).groupby(day).cummin().shift()
    cdl = np.where(pd.Series(day).diff().fillna(1).to_numpy() != 0, np.nan, s.to_numpy())

    # bias: completed 1h bars only
    h1 = resample(df5, C.BIAS_TF)
    st, sh1, sl1 = S.trend_states(h1.high.to_numpy(float), h1.low.to_numpy(float), h1.close.to_numpy(float))
    h1_close = h1.index.asi8 + np.int64(3_600_000_000_000)
    j = np.searchsorted(h1_close, t + NS15, side="right") - 1
    ok = j >= 0
    trend = np.where(ok, st[np.clip(j, 0, None)], S.UNCLEAR).astype(np.int8)
    h1_sh = np.where(ok, sh1[np.clip(j, 0, None)], np.nan)
    h1_sl = np.where(ok, sl1[np.clip(j, 0, None)], np.nan)

    sh15, sl15 = S.pivots(h, l)
    # order blocks on 15m and 1h, mitigation measured on 15m bars
    obs = []
    for tf_df, dur in ((m15, NS15), (h1, np.int64(3_600_000_000_000))):
        tc = tf_df.index.asi8 + dur
        obs += S.order_blocks(tf_df.open.to_numpy(float), tf_df.high.to_numpy(float),
                              tf_df.low.to_numpy(float), tf_df.close.to_numpy(float), tc)
    rows = []
    span = int(C.OB_MAX_AGE_DAYS * 96)
    for created, lo, hi, side in obs:
        i0 = int(np.searchsorted(t, created, side="left"))
        seg = slice(i0, min(i0 + span, len(t)))
        touch = (l[seg] <= hi) & (h[seg] >= lo)
        mit = i0 + int(np.argmax(touch)) if touch.any() else len(t) + span
        rows.append((created, lo, hi, side, mit))
    obs_arr = np.array(sorted(rows), dtype=float) if rows else np.zeros((0, 5))
    return Prepared(symbol, group, t, o, h, l, c, v, tb, sp, atr, cls, ema20, day,
                    pdh, pdl, vah, val, cdh, cdl, datr, trend, h1_sh, h1_sl,
                    np.flatnonzero(sh15), np.flatnonzero(sl15), obs_arr)


# ------------------------------------------------------------------ levels at bar i
def levels_at(P: Prepared, i: int) -> list[Level]:
    sc = C.LEVEL_SCORES
    out: list[Level] = []
    if np.isfinite(P.pdh[i]):
        out += [Level("PDH", P.pdh[i], P.pdh[i], -1, sc["PDH_PDL"]), Level("PDL", P.pdl[i], P.pdl[i], 1, sc["PDH_PDL"])]
    if np.isfinite(P.vah[i]):
        out += [Level("VAH", P.vah[i], P.vah[i], -1, sc["VAH_VAL"]), Level("VAL", P.val[i], P.val[i], 1, sc["VAH_VAL"])]
    if len(P.obs):
        a = np.searchsorted(P.obs[:, 0], P.t[i] - C.OB_MAX_AGE_DAYS * DAY, side="left")
        b = np.searchsorted(P.obs[:, 0], P.t[i], side="right")
        for created, lo, hi, side, mit in P.obs[a:b]:
            if mit >= i:
                out.append(Level("HTF_OB", lo, hi, int(side), sc["HTF_OB"]))
    merge = C.ZONE_MERGE_ATR * P.atr[i]
    for piv, side in ((P.piv_h, -1), (P.piv_l, 1)):
        a = np.searchsorted(piv, i - C.TRIPLE_LOOKBACK_BARS, side="left")
        b = np.searchsorted(piv, i - C.SWING_PIVOT_BARS, side="right")
        k = piv[a:b]
        if len(k) >= C.MIN_ZONE_TOUCHES:
            if side < 0:
                out += triple_zones(k, P.h[k], np.maximum(P.o[k], P.c[k]), merge, -1)
            else:
                out += triple_zones(k, P.l[k], np.minimum(P.o[k], P.c[k]), merge, 1)
    if np.isfinite(P.cdh[i]) and np.isfinite(P.datr[i]) and P.cdh[i] - P.cdl[i] >= C.CDH_CDL_ATR_GATE * P.datr[i]:
        out += [Level("CDH", P.cdh[i], P.cdh[i], -1, sc["CDH_CDL"]), Level("CDL", P.cdl[i], P.cdl[i], 1, sc["CDH_CDL"])]
    return out


def last_pivot(piv: np.ndarray, i: int) -> int | None:
    j = np.searchsorted(piv, i - C.SWING_PIVOT_BARS, side="right") - 1
    return int(piv[j]) if j >= 0 else None


def recent_pivots(piv: np.ndarray, i: int) -> np.ndarray:
    a = np.searchsorted(piv, i - C.TRIPLE_LOOKBACK_BARS, side="left")
    b = np.searchsorted(piv, i - C.SWING_PIVOT_BARS, side="right")
    return piv[a:b]


# ------------------------------------------------------------------ setups
def _direction_ok(trend: int, d: int, level_kind: str | None, setup: str) -> bool:
    if trend == S.UNCLEAR:
        return False
    if setup == "A_SWEEP" and level_kind in ("PDH", "PDL"):
        return True
    if trend == S.RANGE:
        return C.RANGE_ALLOWS_BOTH
    return (trend == S.UP and d > 0) or (trend == S.DOWN and d < 0)


def _target(entry: float, stop: float, d: int, prices: list[float]) -> float | None:
    risk = abs(entry - stop)
    beyond = sorted([p for p in prices if (p - entry) * d > 1e-12], key=lambda p: (p - entry) * d)
    if not beyond:
        return None
    if C.TARGET_MODE == "first_ok":
        for p in beyond:
            if abs(p - entry) >= C.MIN_RR * risk:
                return p
        return None
    p = beyond[0]
    return p if abs(p - entry) >= C.MIN_RR * risk else None


def find_setup(P: Prepared, i: int, levels: list[Level]) -> dict | None:
    """The highest-priority valid setup on closed bar i (entry at bar i+1's open)."""
    cls, trend, atr = int(P.cls[i]), int(P.trend[i]), P.atr[i]
    if cls == K.NONE or trend == S.UNCLEAR or not np.isfinite(atr) or i + 1 >= len(P.t):
        return None
    o, h, l, c = P.o, P.h, P.l, P.c
    entry = o[i + 1]
    merge, buf = C.ZONE_MERGE_ATR * atr, C.STOP_BUFFER_ATR * atr
    piv_lo, piv_hi = recent_pivots(P.piv_l, i), recent_pivots(P.piv_h, i)
    turning_lo, turning_hi = list(l[piv_lo]), list(h[piv_hi])

    def build(setup, d, lvl, stop, target, conf):
        return {"setup": setup, "dir": d, "level": lvl.kind if lvl else None, "conf": conf,
                "stop": stop, "target": target, "entry": entry}

    # A_SWEEP: wick through a level by <= SWEEP_MAX_DEPTH_ATR, close back inside, rejection candle
    if C.SETUPS_ENABLED["A_SWEEP"] and cls in (K.HPR, K.LPR):
        best = None
        for L in levels:
            if cls == K.HPR:
                d, edge = -1, L.hi
                swept = h[i] > edge and h[i] - edge <= C.SWEEP_MAX_DEPTH_ATR * atr and c[i] < edge and c[i - 1] < edge
            else:
                d, edge = 1, L.lo
                swept = l[i] < edge and edge - l[i] <= C.SWEEP_MAX_DEPTH_ATR * atr and c[i] > edge and c[i - 1] > edge
            if not swept or not _direction_ok(trend, d, L.kind, "A_SWEEP"):
                continue
            conf = confluence(L, levels, merge)
            if conf >= C.MIN_CONFLUENCE and (best is None or conf > best[1]):
                best = (L, conf, d)
        if best:
            L, conf, d = best
            stop = h[i] + buf if d < 0 else l[i] - buf
            if (entry - stop) * d > 0:
                opp = [x.hi if d < 0 else x.lo for x in levels] + (turning_lo if d < 0 else turning_hi)
                tgt = _target(entry, stop, d, opp)
                if tgt is not None:
                    return build("A_SWEEP", d, L, stop, tgt, conf)

    # B_TRIPLE: the 4th touch of a triple-touch zone with a rejection candle
    if C.SETUPS_ENABLED["B_TRIPLE"] and cls in (K.HPR, K.LPR):
        for L in levels:
            if L.kind != "TRIPLE_TOUCH":
                continue
            if cls == K.HPR and L.side < 0 and h[i] >= L.lo and c[i] < L.hi and c[i - 1] < L.lo:
                d, stop = -1, max(L.hi, h[i]) + buf
            elif cls == K.LPR and L.side > 0 and l[i] <= L.hi and c[i] > L.lo and c[i - 1] > L.hi:
                d, stop = 1, min(L.lo, l[i]) - buf
            else:
                continue
            if not _direction_ok(trend, d, L.kind, "B_TRIPLE"):
                continue
            conf = confluence(L, levels, merge)
            if conf < C.MIN_CONFLUENCE or (entry - stop) * d <= 0:
                continue
            tgt = _target(entry, stop, d, turning_lo if d < 0 else turning_hi)
            if tgt is not None:
                return build("B_TRIPLE", d, L, stop, tgt, conf)

    # C_PULLBACK: trend leg, rejection at a level forming the next HL / LH
    if C.SETUPS_ENABLED["C_PULLBACK"] and cls in (K.HPR, K.LPR) and trend in (S.UP, S.DOWN):
        d = 1 if (trend == S.UP and cls == K.LPR) else -1 if (trend == S.DOWN and cls == K.HPR) else 0
        if d:
            swing_ref = P.h1_sl[i] if d > 0 else P.h1_sh[i]
            target = P.h1_sh[i] if d > 0 else P.h1_sl[i]
            forms = np.isfinite(swing_ref) and ((l[i] > swing_ref) if d > 0 else (h[i] < swing_ref))
            if forms and np.isfinite(target):
                x = l[i] if d > 0 else h[i]
                touch = [L for L in levels if L.lo - merge <= x <= L.hi + merge]
                best = max(((L, confluence(L, levels, merge)) for L in touch), key=lambda x: x[1], default=None)
                if best and best[1] >= C.MIN_CONFLUENCE:
                    k = last_pivot(P.piv_h if d > 0 else P.piv_l, i)
                    k = k if k is not None else i
                    stop = (l[k:i + 1].min() - buf) if d > 0 else (h[k:i + 1].max() + buf)
                    if (entry - stop) * d > 0 and (target - entry) * d >= C.MIN_RR * abs(entry - stop):
                        return build("C_PULLBACK", d, best[0], stop, float(target), best[1])

    # D_NBREAKOUT: push, pullback, push - a power candle closing through a level
    if C.SETUPS_ENABLED["D_NBREAKOUT"] and cls in (K.BULL_POWER, K.BEAR_POWER):
        d = 1 if cls == K.BULL_POWER else -1
        if _direction_ok(trend, d, None, "D_NBREAKOUT"):
            # last three confirmed alternating swings (L1, H1, L2) for longs, (H1, L1, H2) for shorts
            pl, ph = recent_pivots(P.piv_l, i), recent_pivots(P.piv_h, i)
            ok = False
            if d > 0 and len(pl) >= 2 and len(ph) >= 1:
                l2, hh = pl[-1], ph[ph < pl[-1]]
                if len(hh):
                    h1 = hh[-1]; l1s = pl[pl < h1]
                    if len(l1s):
                        l1 = l1s[-1]
                        ok = l[l1] < l[l2] < h[h1] and c[i] > h[h1]
                        ext = l[l2]
            elif d < 0 and len(ph) >= 2 and len(pl) >= 1:
                h2, ll = ph[-1], pl[pl < ph[-1]]
                if len(ll):
                    l1 = ll[-1]; h1s = ph[ph < l1]
                    if len(h1s):
                        h1 = h1s[-1]
                        ok = h[h1] > h[h2] > l[l1] and c[i] < l[l1]
                        ext = h[h2]
            if ok:
                if d > 0:
                    broken = [L for L in levels if o[i] <= L.hi < c[i]]
                else:
                    broken = [L for L in levels if c[i] < L.lo <= o[i]]
                best = max(((L, confluence(L, levels, merge)) for L in broken), key=lambda x: x[1], default=None)
                if best and best[1] >= C.MIN_CONFLUENCE:
                    stop = ext - buf if d > 0 else ext + buf
                    if (entry - stop) * d > 0:
                        tgt = entry + d * C.D_TARGET_R * abs(entry - stop)
                        return build("D_NBREAKOUT", d, best[0], stop, tgt, best[1])
    return None


# ------------------------------------------------------------------ risk + management
def fee_per_unit(P: Prepared, price: float, k: int) -> float:
    if P.group == "crypto":
        return (C.CRYPTO_TAKER + C.CRYPTO_SLIPPAGE) * price
    s = P.sp[k] if np.isfinite(P.sp[k]) else 0.0
    return s / 2 + C.FX_SLIPPAGE * price


def run(P: Prepared, capital: float = C.STARTING_CAPITAL_USD, start_ns: int | None = None) -> list[dict]:
    trades: list[dict] = []
    equity = capital
    pos = None
    cur_day = None
    lo_h, hi_h = C.TRADING_WINDOW_UTC
    n = len(P.t)
    warm = max(200, C.ATR_LEN + 5)
    for i in range(warm, n):
        # ---- day reset
        if P.day[i] != cur_day:
            cur_day = P.day[i]
            day_trades = day_losses = 0
            day_risk = day_pnl = 0.0
            day_start_eq = equity
        # ---- manage an open position through bar i
        if pos is not None and i >= pos["e"]:
            d, sl, tp = pos["dir"], pos["sl"], pos["tp"]
            px = why = None
            if (P.l[i] <= sl) if d > 0 else (P.h[i] >= sl):
                px = sl if i == pos["e"] else (min(P.o[i], sl) if d > 0 else max(P.o[i], sl))
                why = "stop" if sl == pos["sl0"] else ("breakeven" if sl == pos["entry"] else "trail")
            elif (P.h[i] >= tp) if d > 0 else (P.l[i] <= tp):
                px, why = tp, "target"
            if px is not None:
                fee = pos["fee_in"] + fee_per_unit(P, px, i)
                pnl = pos["qty"] * ((px - pos["entry"]) * d - fee)
                equity += pnl
                day_pnl += pnl
                day_losses += pnl < 0
                trades.append({**pos["rec"], "exit_time": pd.Timestamp(P.t[i], tz="UTC").isoformat(), "exit": px,
                               "reason": why, "r": pnl / pos["risk_amt"], "fees_r": pos["qty"] * fee / pos["risk_amt"],
                               "equity": equity})
                pos = None
            else:
                reach = ((P.h[i] - pos["entry"]) if d > 0 else (pos["entry"] - P.l[i])) / abs(tp - pos["entry"])
                if reach >= C.BREAKEVEN_AT:
                    pos["sl"] = max(pos["sl"], pos["entry"]) if d > 0 else min(pos["sl"], pos["entry"])
                if reach >= C.TRAIL_FROM:
                    pos["trail"] = True
                if pos.get("trail"):
                    if C.TRAIL_METHOD == "ema20":
                        cand = P.ema20[i]
                    else:
                        k = last_pivot(P.piv_l if d > 0 else P.piv_h, i)
                        cand = (P.l[k] if d > 0 else P.h[k]) if k is not None and k > pos["e"] else None
                    if cand is not None and ((cand < P.c[i]) if d > 0 else (cand > P.c[i])):
                        pos["sl"] = max(pos["sl"], cand) if d > 0 else min(pos["sl"], cand)
        # ---- look for a new setup at bar i's close
        if pos is not None or i + 1 >= n or (start_ns is not None and P.t[i] < start_ns):
            continue
        ts = pd.Timestamp(P.t[i], tz="UTC")
        if not (lo_h <= ts.hour < hi_h):
            continue
        if C.SKIP_WEEKENDS[P.group] and ts.weekday() >= 5:
            continue
        if (day_trades >= C.MAX_TRADES_PER_DAY or day_losses >= C.STOP_AFTER_LOSSES_PER_DAY
                or day_pnl >= C.DAILY_PROFIT_STOP * day_start_eq or day_risk >= C.RISK_PER_DAY_MAX - 1e-12):
            continue
        if P.cls[i] == K.NONE or P.trend[i] == S.UNCLEAR:
            continue
        levels = levels_at(P, i)
        sig = find_setup(P, i, levels)
        if sig is None:
            continue
        d = sig["dir"]
        merge = C.ZONE_MERGE_ATR * P.atr[i]
        near = lambda x: any(distance(Level("", x, x, 0, 0), L) <= merge for L in levels)  # noqa: E731
        absn = D.absorption(i, P.o, P.h, P.l, P.c, P.v, P.tb, P.cls, near(P.h[i - 1]), near(P.l[i - 1]))
        delta_ok = absn is not None and absn == d
        if C.DELTA_FILTER_MODE == "required" and absn is not None and not delta_ok:
            continue
        risk_pct = C.RISK_PER_TRADE_HIGH if (sig["conf"] >= C.HIGH_CONFLUENCE or
                                             (C.DELTA_FILTER_MODE != "off" and delta_ok)) else C.RISK_PER_TRADE
        risk_pct = min(risk_pct, C.RISK_PER_DAY_MAX - day_risk)
        if risk_pct < 0.0025:
            continue
        entry, stop = sig["entry"], sig["stop"]
        dist = abs(entry - stop)
        if dist / entry >= 1 / C.LEVERAGE[P.group] - C.MAINTENANCE_MARGIN:
            continue                                # liquidation would come before the stop
        fee_in = fee_per_unit(P, entry, i + 1)
        risk_amt = equity * risk_pct
        qty = risk_amt / (dist + 2 * fee_in)
        day_trades += 1
        day_risk += risk_pct
        rec = {"symbol": P.symbol, "group": P.group, "setup": sig["setup"], "side": "long" if d > 0 else "short",
               "signal_time": ts.isoformat(), "entry_time": pd.Timestamp(P.t[i + 1], tz="UTC").isoformat(),
               "level": sig["level"], "confluence": sig["conf"], "candle": K.NAMES[int(P.cls[i])],
               "trend": S.TREND_NAMES[int(P.trend[i])],
               "delta": "n/a" if absn is None else ("confirmed" if delta_ok else "no"),
               "risk_pct": risk_pct, "entry": entry, "stop": stop, "target": sig["target"],
               "rr": abs(sig["target"] - entry) / dist, "hour": ts.hour}
        pos = {"e": i + 1, "dir": d, "entry": entry, "sl": stop, "sl0": stop, "tp": sig["target"],
               "qty": qty, "risk_amt": risk_amt, "fee_in": fee_in, "rec": rec}
    return trades


# ------------------------------------------------------------------ report
def stats(r: pd.Series) -> dict:
    if not len(r):
        return {"trades": 0}
    eq = (1 + r * 0.01).cumprod()
    wins, losses = r[r > 0].sum(), -r[r < 0].sum()
    return {"trades": int(len(r)), "win_rate": round(float((r > 0).mean()), 3), "avg_r": round(float(r.mean()), 3),
            "total_r": round(float(r.sum()), 1), "profit_factor": round(float(wins / losses), 2) if losses else None,
            "max_dd_pct_at_1pct": round(float((1 - eq / eq.cummax()).max() * 100), 1)}


def report(trades: pd.DataFrame) -> dict:
    if trades.empty:
        return {"overall": {"trades": 0}}
    out = {"overall": stats(trades.r)}
    for col in ("symbol", "setup", "level", "confluence", "side", "delta", "hour", "reason"):
        out[f"by_{col}"] = {str(k): stats(g.r) for k, g in trades.groupby(col)}
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("data", type=Path)
    ap.add_argument("--group", default="all", choices=["all", *C.GROUPS])
    ap.add_argument("--months", type=int, default=12, help="0 = all history")
    ap.add_argument("--capital", type=float, default=C.STARTING_CAPITAL_USD)
    ap.add_argument("--out", type=Path, default=Path("rb1_out"))
    a = ap.parse_args()
    a.out.mkdir(parents=True, exist_ok=True)
    groups = list(C.GROUPS) if a.group == "all" else [a.group]
    all_trades = []
    for g in groups:
        for sym in C.GROUPS[g]:
            f = a.data / f"{sym}_5m.csv.gz"
            if not f.exists():
                print("missing", f); continue
            df5 = load_5m(f)
            start = None
            if a.months:
                start = (df5.index[-1] - pd.DateOffset(months=a.months)).value
                df5 = df5[df5.index >= df5.index[-1] - pd.DateOffset(months=a.months + 1)]   # one month of warm-up
            P = prepare(sym, df5)
            tr = run(P, a.capital, start)
            print(sym, len(tr), "trades", flush=True)
            all_trades += tr
    t = pd.DataFrame(all_trades)
    t.to_csv(a.out / "rb1_trades.csv", index=False)
    rep = report(t)
    (a.out / "rb1_report.json").write_text(json.dumps(rep, indent=1, default=str))
    print(json.dumps(rep["overall"], indent=1))


if __name__ == "__main__":
    main()
