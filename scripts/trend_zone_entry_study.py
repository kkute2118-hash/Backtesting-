#!/usr/bin/env python3
"""4h trend breakout (step 6) with the entry moved to the first pullback into
a fresh 4h demand zone (step 7's zone rules) instead of the broken high.

Signal (unchanged): 4h close above the previous 55 4h highs, daily close above
its 200-day average, long only. Exit (unchanged): a 4h close below the
previous 20 4h lows, at the next 15m open, or the stop.

Zone: the nearest fresh demand zone (scripts/zone_sniper_study.find_zones,
any of DBR/RBR) made in the 10 days before the signal, whose proximal line is
below the signal close and which price has not touched since it was made.
Entries (15m bars), valid for `hours` after the signal:
  zone_limit   limit at the zone's proximal line
  zone_sniper  after the touch, the first 15m close above the last 15m swing
               high while the distal line holds; entry at the next open
Stops: "zone" = 0.1 ATR(4h) below the distal line (sniper: below the low made
in the zone); "atr" = 2 ATR(4h) below the entry, as in step 6.
Baseline: step 6's limit at the broken high for 24 hours.
Charges as in step 6.

Usage: python scripts/trend_zone_entry_study.py DATA_DIR OUT_PREFIX
"""

from __future__ import annotations

import itertools
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import trend_4h_study as t4s  # noqa: E402
import zone_sniper_study as zs  # noqa: E402

SPLIT = pd.Timestamp("2025-01-01", tz="UTC")


def run(sym, m15, h4, zones, entry, stop_kind, hours):
    H4c = h4.close.to_numpy()
    hh = h4.high.rolling(55).max().shift().to_numpy()
    ll = h4.low.rolling(20).min().shift().to_numpy()
    atr, trend = h4.atr.to_numpy(), h4.trend.to_numpy()
    t4 = h4.index
    o, h, l, c, fund = (m15[k].to_numpy() for k in ("open", "high", "low", "close", "funding"))
    t15 = m15.index
    sh15 = t4s.swings_high(h)
    nxt = t15 + pd.Timedelta(minutes=15)
    last4 = np.asarray((nxt.hour % 4 == 0) & (nxt.minute == 0))
    idx4 = t4.searchsorted(t15, side="right") - 1
    demand = [z for z in zones if z["d"] == 1]
    made = pd.DatetimeIndex([z["made"] for z in demand])
    out = []
    j = 220
    while j < len(H4c) - 1:
        if not (trend[j] and np.isfinite(hh[j]) and np.isfinite(atr[j]) and H4c[j] > hh[j]):
            j += 1
            continue
        a = atr[j]
        sig_end = t4[j] + pd.Timedelta(hours=4)
        k0 = t15.searchsorted(sig_end)
        k_end = min(k0 + hours * 4, len(c) - 1)
        if entry == "retest":
            zone = None
            prox, dist = hh[j], None
        else:
            lo, hi = made.searchsorted(sig_end - pd.Timedelta(days=10)), made.searchsorted(sig_end, side="right")
            zone = None
            for z in sorted(demand[lo:hi], key=lambda z: -z["prox"]):
                if z["prox"] >= H4c[j]:
                    continue
                kz = t15.searchsorted(z["made"])
                if kz < k0 and l[kz:k0].min() <= z["prox"]:
                    continue                                  # not fresh
                zone = z
                break
            if zone is None:
                j += 1
                continue
            prox, dist = zone["prox"], zone["dist"]
        k_in = px = stop = None
        fee_in = t4s.MAKER
        if entry in ("retest", "zone_limit"):
            for k in range(k0, k_end):
                if l[k] <= prox:
                    k_in, px = k, min(o[k], prox)
                    break
            if k_in is not None:
                stop = (dist - 0.1 * a) if (stop_kind == "zone" and dist is not None) else px - 2 * a
        else:   # zone_sniper
            last_sw, ext, touched = None, None, False
            for k in range(k0 - 8, k_end):
                if k - 2 >= 0 and sh15[k - 2]:
                    last_sw = h[k - 2]
                if k < k0:
                    continue
                touched = touched or l[k] <= prox
                if not touched:
                    continue
                ext = l[k] if ext is None else min(ext, l[k])
                if c[k] < dist:
                    break
                if last_sw is not None and c[k] > last_sw:
                    k_in, px, fee_in = k + 1, o[k + 1], t4s.TAKER
                    stop = (ext - 0.1 * a) if stop_kind == "zone" else px - 2 * a
                    break
        if k_in is None:
            j += 1
            continue
        risk = px - stop
        if risk <= 0:
            j += 1
            continue
        funding, k, exit_px = 0.0, k_in, None
        while k < len(c) - 1:
            if l[k] <= stop:
                exit_px = min(o[k], stop)
                break
            funding += fund[k]
            if last4[k]:
                j4 = idx4[k]
                if np.isfinite(ll[j4]) and H4c[j4] < ll[j4]:
                    k += 1
                    exit_px = o[k]
                    break
            k += 1
        if exit_px is None:
            break
        cost = fee_in * px + t4s.TAKER * exit_px + funding * px
        out.append({"symbol": sym, "entry_mode": entry, "stop_kind": stop_kind, "hours": hours,
                    "entry_time": t15[k_in], "entry": px, "stop": stop, "exit": exit_px,
                    "risk_pct": risk / px * 100, "r": (exit_px - px - cost) / risk,
                    "pnl_pct": (exit_px - px - cost) / px * 100})
        j = t4.searchsorted(t15[min(k, len(t15) - 1)])
    return out


def main():
    data, prefix = Path(sys.argv[1]), sys.argv[2]
    rows = []
    for sym in t4s.SYMBOLS:
        m15, h4 = t4s.load(data, sym)
        _, h4z, d1 = zs.load(data, sym)
        zones = zs.find_zones(h4z, d1)
        rows += run(sym, m15, h4, zones, "retest", "atr", 24)
        for entry, stop_kind, hours in itertools.product(("zone_limit", "zone_sniper"), ("zone", "atr"), (24, 72)):
            rows += run(sym, m15, h4, zones, entry, stop_kind, hours)
        print(sym, len(rows), file=sys.stderr, flush=True)
    t = pd.DataFrame(rows)
    t["test"] = t.entry_time >= SPLIT
    t.to_csv(f"{prefix}_trades.csv", index=False)
    for key, g in t.groupby(["entry_mode", "stop_kind", "hours"]):
        a, b = g[~g.test], g[g.test]
        print(f"{str(key):34s} 2021-24 n={len(a):3d} {a.r.mean():+.2f}R win {(a.r > 0).mean():.0%} stop {a.risk_pct.median():.1f}% "
              f"| 2025-26 n={len(b):3d} {b.r.mean():+.2f}R win {(b.r > 0).mean():.0%} | sum R {a.r.sum():+.0f} / {b.r.sum():+.0f}")


if __name__ == "__main__":
    main()
