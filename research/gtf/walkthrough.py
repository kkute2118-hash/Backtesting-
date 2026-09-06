"""One real 7/7 trade, start to finish, from the actual candles."""
import numpy as np, pandas as pd, sqlite3
import gtfcore as G
pd.set_option("display.width", 200)
DB = "/tmp/claude-0/-home-user-Backtesting-/52d73d1b-702d-51ce-a95b-beb9647ef04c/scratchpad/data/market_data.sqlite3"

d = pd.read_parquet("/tmp/gtf/events.parquet"); d["date"] = pd.to_datetime(d["date"])
x = pd.read_parquet("/tmp/gtf/exits.parquet")
d = pd.concat([d, x[["x_fix_2_8", "b_fix_2_8"]]], axis=1)
d = d[(d.gap_through == 0) & d.score.eq(7.0) & d.turnover_cr.ge(10)
      & (d.date >= "2024-09-04") & (d.date <= "2026-09-04")].copy()

def show(t, label):
    con = sqlite3.connect(DB)
    df = pd.read_sql_query("SELECT dt,open,high,low,close FROM candles WHERE symbol=? ORDER BY dt",
                           con, params=(t.symbol,)); con.close()
    df["dt"] = pd.to_datetime(df["dt"]); df = df.set_index("dt")
    O, H, L, C = (df[c].to_numpy() for c in ("open", "high", "low", "close"))
    A = G.atr(H, L, C, 14)
    exc, grn = G.classify(O, H, L, C)
    li, a, b, lo_i, j = int(t.legin_i), int(t.base_lo_i), int(t.base_hi_i), int(t.legout_i), int(t.bar)
    atr = A[j - 1]
    entry, stop, tgt = t.entry_plan, t.entry_plan - 2*atr, t.entry_plan + 8*atr
    held = int(t.b_fix_2_8)

    print("\n" + "#" * 96)
    print(f"# {label}: {t.symbol}   zone built {df.index[lo_i].date()}   "
          f"filled {df.index[j].date()}   result {t.x_fix_2_8:+.1f}%")
    print("#" * 96)
    print("\nSTEP 1-2  the zone is built, months before any trade")
    print(f"{'date':<12}{'open':>9}{'high':>9}{'low':>9}{'close':>9}{'body/rng':>9}  {'type':<11}role")
    for i in range(li, lo_i + int(t.legout_n)):
        rng = H[i]-L[i]; f = abs(C[i]-O[i])/rng if rng > 0 else 0
        kind = ("EXCITING "+("G" if grn[i] else "R")) if exc[i] else "base"
        role = ("LEG-IN" if i == li else f"BASE {i-a+1}/{b-a+1}" if a <= i <= b else "LEG-OUT")
        print(f"{df.index[i].date()!s:<12}{O[i]:>9.2f}{H[i]:>9.2f}{L[i]:>9.2f}{C[i]:>9.2f}"
              f"{f:>9.2f}  {kind:<11}<- {role}")
    print(f"\n  proximal = highest body of the base candles = {t.entry_plan:>9.2f}  <- the buy line")
    print(f"  distal   = lowest wick of the base candles  = {t.stop:>9.2f}  <- NOT the stop")
    print(f"\n  GTF trade score:  fresh 3  +  {int(t.legout_n)} leg-outs"
          f"{' (or gap)' if t.gap else ''} 2  +  {int(t.n_base)} base candle(s) 2  =  7/7")

    print(f"\nSTEP 3  {t.zone_age} bars pass. The zone stays alive (no close below the distal).")
    print("        A buy limit rests at the proximal every session.")

    print(f"\nSTEP 4  price returns and the limit fills")
    for i in range(j - 2, min(len(C), j + 1)):
        tag = "<== FILLED here, at the proximal" if i == j else ("decision bar" if i == j-1 else "")
        print(f"{df.index[i].date()!s:<12}{O[i]:>9.2f}{H[i]:>9.2f}{L[i]:>9.2f}{C[i]:>9.2f}"
              f"{'':>9}  {'':<11}{tag}")
    print(f"\n  ATR14 on the fill day = {atr:.2f}")
    print(f"  ENTRY  {entry:>9.2f}   (the proximal line)")
    print(f"  STOP   {stop:>9.2f}   = entry - 2 x ATR   ({100*(stop/entry-1):+.1f}%)")
    print(f"  TARGET {tgt:>9.2f}   = entry + 8 x ATR   ({100*(tgt/entry-1):+.1f}%)")
    print(f"  TIME STOP 60 trading days")

    print(f"\nSTEP 5  what happened over the next {held} bars")
    end = min(len(C)-1, j + held)
    for i in range(j+1, end+1):
        mark = ""
        if L[i] <= stop: mark = "  <== STOP hit"
        elif H[i] >= tgt: mark = "  <== TARGET hit"
        if i - j <= 3 or mark or i == end:
            print(f"{df.index[i].date()!s:<12}{O[i]:>9.2f}{H[i]:>9.2f}{L[i]:>9.2f}{C[i]:>9.2f}"
                  f"   bar {i-j:>2}{mark}")
        if mark: break
    print(f"\n  RESULT {t.x_fix_2_8:+.2f}% in {held} bars")

d = d.sort_values("x_fix_2_8")
show(d.iloc[-3], "A WINNER")
show(d[d.x_fix_2_8 < -5].iloc[len(d[d.x_fix_2_8 < -5])//2], "A LOSER")

print("\n" + "=" * 96)
print("THE ARITHMETIC OF THE WHOLE THING (7/7 + liquidity + high-vol, last 2 years)")
print("=" * 96)
s = pd.read_parquet("/tmp/gtf/events.parquet"); s["date"] = pd.to_datetime(s["date"])
xx = pd.read_parquet("/tmp/gtf/exits.parquet")
s = pd.concat([s, xx[["x_fix_2_8"]]], axis=1)
s = s[(s.gap_through == 0) & s.score.eq(7.0) & s.turnover_cr.ge(10)
      & (s.date >= "2024-09-04") & (s.date <= "2026-09-04")]
y = s.x_fix_2_8.dropna(); w = y[y > 0]; l = y[y <= 0]
print(f"  out of every 100 trades:  {100*len(w)/len(y):.0f} win, {100*len(l)/len(y):.0f} lose")
print(f"  the winners average       {w.mean():+.1f}%")
print(f"  the losers average        {l.mean():+.1f}%")
print(f"  so 100 trades produce     {len(w)/len(y)*100:.0f} x {w.mean():+.1f}  "
      f"{len(l)/len(y)*100:.0f} x {l.mean():+.1f}  =  {y.mean()*100:+.0f}% spread over 100 trades")
print(f"  i.e. {y.mean():+.2f}% per trade, profit factor {w.sum()/-l.sum():.2f}")
