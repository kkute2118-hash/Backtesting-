#!/usr/bin/env python3
"""Higher-timeframe demand/supply zones with a liquidity sweep and a sniper
entry (the owner's master prompt, sections 1-2, 14, 17-21; the GTF course's
zone marking, freshness and achievement rules).

4h zone (known only once the leg-out candle closes):
  base     1-3 consecutive candles with body <= 50% of range
  leg-out  the next candle, body >= 1 ATR(14, 4h), closing beyond the base
  leg-in   the candle before the base: opposite colour = reversal (DBR / RBD),
           same colour = continuation (RBR / DBD)
  zone     demand: proximal = highest body top of the base, distal = lowest low
           of the base and leg-out; supply mirrored
  achieve  price must move >= 2 zone widths beyond the proximal line before
           it first comes back (room for reward)
  fresh    one trade per zone: the first return only; zones expire after 30 days
Tags: swept = the move into the zone took out a confirmed 4h swing beyond the
proximal line (stop-losses taken); trend = last completed daily close on the
trade's side of its 200-day average.
Entries on 15-minute bars:
  limit    limit at the proximal line, stop 0.1 ATR beyond the distal line
  sniper   inside the zone, the first 15m close through the last 15m swing
           (micro MSB) while the distal line holds; stop 0.1 ATR(4h) beyond the
           extreme made inside the zone
Target: the extreme between the leg-out and the return (the liquidity the
market came from); skip if it is less than 2R. Time limit 10 days.
Charges as on a crypto-exchange perpetual: maker 0.02% + 18% GST for limit
fills (entry and target), taker 0.05% + GST + 0.01% slippage for market
fills (sniper entry, stop, time exit), funding 0.01% per 8 hours.

Usage: python scripts/zone_sniper_study.py DATA_DIR OUT_PREFIX
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

SYMBOLS = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT", "XAUUSD")
MAKER = 0.0002 * 1.18
TAKER = 0.0005 * 1.18 + 0.0001
FUND_15M = 0.0001 / 32
SPLIT = pd.Timestamp("2025-01-01", tz="UTC")
AGG = {"open": "first", "high": "max", "low": "min", "close": "last"}


def load(data, sym):
    df = pd.read_csv(data / f"{sym}_5m.csv.gz")
    df["time"] = pd.to_datetime(df["time"], utc=True)
    df = df.set_index("time").sort_index()
    return df.resample("15min").agg(AGG).dropna(), df.resample("4h").agg(AGG).dropna(), \
        df.resample("1D").agg(AGG).dropna()


def atr(df, n):
    tr = np.maximum(df.high - df.low, np.maximum(abs(df.high - df.close.shift()), abs(df.low - df.close.shift())))
    return tr.rolling(n).mean()


def find_zones(h4, d1):
    o, h, l, c = (h4[k].to_numpy() for k in ("open", "high", "low", "close"))
    a = atr(h4, 14).to_numpy()
    rng = h - l
    body = np.abs(c - o)
    boring = body <= 0.5 * np.where(rng > 0, rng, np.inf)
    trend_up = (d1.close > d1.close.rolling(200).mean()).shift(1)
    tr_up = trend_up.astype(float).reindex(h4.index.floor("1D")).to_numpy()
    zones = []
    for j in range(20, len(c)):
        if not np.isfinite(a[j]) or body[j] < 1.0 * a[j]:
            continue
        for nb in (1, 2, 3):                      # base = bars j-nb .. j-1
            b0 = j - nb
            if b0 < 1 or not boring[b0:j].all():
                continue
            if b0 - 1 >= 0 and boring[b0 - 1]:
                continue                          # want the longest clean base only once
            bt, bb = max(np.maximum(o[b0:j], c[b0:j])), min(np.minimum(o[b0:j], c[b0:j]))
            up = c[j] > o[j] and c[j] > max(h[b0:j])
            dn = c[j] < o[j] and c[j] < min(l[b0:j])
            if not (up or dn):
                continue
            leg_in_up = c[b0 - 1] > o[b0 - 1]
            if up:
                prox, dist = bt, min(l[b0:j + 1].min(), l[b0:j].min())
                kind = "DBR" if not leg_in_up else "RBR"
            else:
                prox, dist = bb, max(h[b0:j + 1].max(), h[b0:j].max())
                kind = "RBD" if leg_in_up else "DBD"
            if abs(prox - dist) <= 0:
                continue
            zones.append({"d": 1 if up else -1, "prox": prox, "dist": dist, "kind": kind,
                          "made": h4.index[j] + pd.Timedelta(hours=4), "atr": a[j],
                          "trend": tr_up[j]})
            break
    return zones


def swings(h, l, n=2):
    w = 2 * n + 1
    return (h == pd.Series(h).rolling(w, center=True).max().to_numpy(),
            l == pd.Series(l).rolling(w, center=True).min().to_numpy())


def simulate(sym, m15, h4, d1):
    o, h, l, c = (m15[k].to_numpy() for k in ("open", "high", "low", "close"))
    t = m15.index
    sh15, sl15 = swings(h, l, 2)
    H4h, H4l = h4.high.to_numpy(), h4.low.to_numpy()
    sh4, sl4 = swings(H4h, H4l, 2)
    t4 = h4.index
    out = []
    for z in find_zones(h4, d1):
        d, prox, dist, a = z["d"], z["prox"], z["dist"], z["atr"]
        width = abs(prox - dist)
        k = t.searchsorted(z["made"])
        k_exp = min(k + 30 * 96, len(c) - 1)
        achieved, far = False, prox
        touch = None
        while k < k_exp:
            far = max(far, h[k]) if d > 0 else min(far, l[k])
            if not achieved and (far - prox) * d >= 2 * width:
                achieved = True
            if (d > 0 and l[k] <= prox) or (d < 0 and h[k] >= prox):
                touch = k
                break
            k += 1
        if touch is None or not achieved:
            continue
        target = far
        # swept: a confirmed 4h swing beyond the proximal line, made after the zone, taken on the way back
        j0, j1 = t4.searchsorted(z["made"]), t4.searchsorted(t[touch])
        swept = False
        for jj in range(j0, max(j0, j1 - 2)):
            if d > 0 and sl4[jj] and H4l[jj] > prox and l[touch - 96:touch + 1].min() < H4l[jj]:
                swept = True
            if d < 0 and sh4[jj] and H4h[jj] < prox and h[touch - 96:touch + 1].max() > H4h[jj]:
                swept = True
        trend_ok = (z["trend"] == 1.0) if d > 0 else (z["trend"] == 0.0)
        for mode in ("limit", "sniper"):
            entry_k = entry = stop = None
            fee_in = MAKER
            if mode == "limit":
                entry_k, entry = touch, (min(o[touch], prox) if d > 0 else max(o[touch], prox))
                stop = dist - d * 0.1 * a
            else:
                last_sw, ext = None, None
                for kk in range(touch - 8, min(touch + 4 * 96, len(c) - 1)):   # up to 4 days in the zone
                    if kk - 2 >= 0 and ((d > 0 and sh15[kk - 2]) or (d < 0 and sl15[kk - 2])):
                        last_sw = h[kk - 2] if d > 0 else l[kk - 2]
                    if kk < touch:
                        continue
                    ext = (l[kk] if ext is None else min(ext, l[kk])) if d > 0 else \
                          (h[kk] if ext is None else max(ext, h[kk]))
                    if (d > 0 and c[kk] < dist) or (d < 0 and c[kk] > dist):
                        break                                         # zone failed
                    if last_sw is not None and ((d > 0 and c[kk] > last_sw) or (d < 0 and c[kk] < last_sw)):
                        entry_k, entry, fee_in = kk + 1, o[kk + 1], TAKER
                        stop = ext - d * 0.1 * a
                        break
                if entry_k is None:
                    continue
            risk = (entry - stop) * d
            if risk <= 0 or (target - entry) * d < 2 * risk:
                continue
            # manage: stop first on a shared bar, the limit fill bar included
            px, why, kk = None, "time", entry_k
            end = min(entry_k + 10 * 96, len(c) - 1)
            while kk < end:
                if (d > 0 and l[kk] <= stop) or (d < 0 and h[kk] >= stop):
                    px, why = (min(o[kk], stop) if d > 0 else max(o[kk], stop)), "stop"
                    break
                if kk > entry_k and ((d > 0 and h[kk] >= target) or (d < 0 and l[kk] <= target)):
                    px, why = target, "target"
                    break
                kk += 1
            if px is None:
                px = c[kk]
            fee_out = MAKER if why == "target" else TAKER
            cost = fee_in * entry + fee_out * px + FUND_15M * (kk - entry_k) * entry
            r = ((px - entry) * d - cost) / risk
            out.append({"symbol": sym, "mode": mode, "d": d, "kind": z["kind"], "swept": swept,
                        "trend": bool(trend_ok), "entry_time": t[entry_k], "entry": entry, "stop": stop,
                        "target": target, "rr": (target - entry) * d / risk, "risk_pct": risk / entry * 100,
                        "why": why, "r": r, "cost_r": cost / risk, "days": (kk - entry_k) / 96})
    return out


def main():
    data, prefix = Path(sys.argv[1]), sys.argv[2]
    rows = []
    for sym in SYMBOLS:
        m15, h4, d1 = load(data, sym)
        rows += simulate(sym, m15, h4, d1)
        print(sym, len(rows), file=sys.stderr, flush=True)
    t = pd.DataFrame(rows)
    t["test"] = t.entry_time >= SPLIT
    t.to_csv(f"{prefix}_trades.csv", index=False)
    print(t.groupby(["mode", "test"]).r.agg(["size", "mean"]).round(3))


if __name__ == "__main__":
    main()
