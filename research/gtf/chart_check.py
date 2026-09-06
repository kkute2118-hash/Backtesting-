"""Print the raw candles of a recorded trade so the zone marking can be
checked by eye on any chart. The zone's bar coordinates come from the trade
row itself, so what is printed is exactly what the backtest traded."""
import sqlite3
import numpy as np, pandas as pd
import gtfcore as G
DB = "/tmp/claude-0/-home-user-Backtesting-/52d73d1b-702d-51ce-a95b-beb9647ef04c/scratchpad/data/market_data.sqlite3"


def show(t, back=3, fwd=3):
    con = sqlite3.connect(DB)
    df = pd.read_sql_query("SELECT dt,open,high,low,close FROM candles "
                           "WHERE symbol=? ORDER BY dt", con, params=(t.symbol,))
    con.close()
    df["dt"] = pd.to_datetime(df["dt"]); df = df.set_index("dt")
    O, H, L, C = (df[c].to_numpy() for c in ("open", "high", "low", "close"))
    A = G.atr(H, L, C, 14); E2 = G.ema(C, 200)
    exciting, green = G.classify(O, H, L, C)
    li, a, b, lo_i = int(t.legin_i), int(t.base_lo_i), int(t.base_hi_i), int(t.legout_i)
    j = int(t.bar); ctx = j - 1

    print("=" * 100)
    print(f"{t.symbol}   zone formed {df.index[lo_i].date()}   "
          f"entry {df.index[j].date()}   waited {t.zone_age} bars   "
          f"result {t.outcome} {t['pnl%']:+.2f}%")
    print("=" * 100)
    hdr = f"{'date':<12}{'open':>9}{'high':>9}{'low':>9}{'close':>9}{'body/rng':>10}  {'kind':<11}role"
    def rows(i0, i1):
        for i in range(max(0, i0), min(len(C), i1 + 1)):
            rng = H[i] - L[i]
            frac = abs(C[i] - O[i]) / rng if rng > 0 else 0.0
            kind = ("EXCITING " + ("G" if green[i] else "R")) if exciting[i] else "base"
            role = ("<- LEG-IN" if i == li else
                    f"<- BASE {i-a+1}/{b-a+1}" if a <= i <= b else
                    "<- LEG-OUT" if lo_i <= i < lo_i + int(t.legout_n) else
                    "<- decision bar" if i == ctx else
                    "<== ENTRY, limit filled at the proximal line" if i == j else "")
            print(f"{df.index[i].date()!s:<12}{O[i]:>9.2f}{H[i]:>9.2f}{L[i]:>9.2f}"
                  f"{C[i]:>9.2f}{frac:>10.2f}  {kind:<11}{role}")
    print(hdr)
    rows(li - back, lo_i + int(t.legout_n) - 1 + back)
    if j - ctx_gap(ctx, lo_i, t) > 0:
        print(f"{'   ...':<12}{'':>9}{'':>9}{'':>9}{'':>9}{'':>10}  "
              f"{'':<11}({t.zone_age} bars pass, zone stays alive - no close below the distal)")
    rows(ctx - back, j + fwd)
    print(f"\n  proximal  (highest body of the {b-a+1} base candle(s))  = {t.proximal:>9.2f}")
    print(f"  distal    (lowest wick of the base candles)      = {t.distal:>9.2f}")
    print(f"  zone height {100*(t.proximal-t.distal)/t.proximal:>5.2f}%  (F1 >= 2.21)"
          f"   leg-out/ATR {t.legout_atr:>4.2f}  (F2 >= 0.837)")
    print(f"  ATR/close   {100*A[ctx]/C[ctx]:>5.2f}%  (F3 >= 3.24)"
          f"   approach {100*(C[ctx]/t.proximal-1):>5.2f}%  (F4 >= 1.19)"
          f"   EMA200 dist {(C[ctx]-E2[ctx])/A[ctx]:>5.2f}  (F5 <= 0.96)")
    print(f"\n  ORDER:  buy limit {t.proximal:.2f}   stop {t.stop_px:.2f}   "
          f"target {t.target_px:.2f}   time stop 60 bars")


def ctx_gap(ctx, lo_i, t):
    return ctx - (lo_i + int(t.legout_n) - 1)


tr = pd.read_csv("trades_audit_window.csv", parse_dates=["date"])
print(f"{len(tr)} trades in the audit window\n")
picks = pd.concat([tr.head(2), tr[tr.outcome == "stop"].tail(1)])
for _, t in picks.iterrows():
    show(t); print()
