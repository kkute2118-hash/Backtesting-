"""ROI and CAGR for the last 2 years: each strategy, with and without the
liquidity entry rules.

Per-trade averages answer a different question than the one asked. What a
portfolio actually earns depends on how many signals arrive at once, how long
each holds a slot, and whether the filtered signals are the ones that would
have been taken anyway. So every strategy below runs through the same
simulator: fixed fractional risk, a slot cap, one position per symbol, no
leverage, and ties broken by symbol name (which cannot know the outcome).

Three versions of each strategy:
  base    every signal
  liq     only signals in names that recently printed a qualifying liquidity
          setup (grab or sweep, long, weekly trend up > 5%)
  liq-e   the liquidity setups themselves as the entry, standalone
"""
import numpy as np, pandas as pd, sqlite3
pd.set_option("display.width", 250)
DB = ("/tmp/claude-0/-home-user-Backtesting-/52d73d1b-702d-51ce-a95b-beb9647ef04c"
      "/scratchpad/data/market_data.sqlite3")
START, RISK, SLOTS = 1_000_000.0, 0.01, 10
CUT = pd.Timestamp("2024-09-04")

con = sqlite3.connect(DB)
px = pd.read_sql_query("SELECT dt, symbol, close FROM candles", con)
cal_rows = pd.read_sql_query("SELECT symbol, dt FROM candles ORDER BY symbol, dt", con)
con.close()
px["dt"] = pd.to_datetime(px["dt"])
wide = px.pivot_table(index="dt", columns="symbol", values="close")
CAL = np.sort(wide.index.unique().values)
DMAP = {v: i for i, v in enumerate(CAL)}
cal_rows["dt"] = pd.to_datetime(cal_rows["dt"])
cal_rows["bar"] = cal_rows.groupby("symbol").cumcount()
BARKEY = cal_rows.set_index(["symbol", "dt"])["bar"]


def portfolio(ev, slots=SLOTS, risk=RISK, start=START):
    """ev needs: symbol, date, entry, stop_px, p (percent), b (bars held)."""
    ev = ev.dropna(subset=["p", "b", "entry", "stop_px"]).sort_values("date").copy()
    ev["di"] = ev.date.map(DMAP)
    ev = ev[ev.di.notna()]
    if not len(ev):
        return None
    ev["di"] = ev.di.astype(int)
    ev["exit_di"] = ev.di + ev.b.astype(int)
    lo, hi = ev.di.min(), min(int(ev.exit_di.max()), len(CAL) - 1)
    eq = start; open_pos = []; held = set(); curve = []; taken = 0
    by_day = {k: v for k, v in ev.groupby("di")}
    for i in range(lo, hi + 1):
        for pos in [p for p in open_pos if p[0] <= i]:
            eq += pos[1]; open_pos.remove(pos); held.discard(pos[2])
        todays = by_day.get(i)
        if todays is not None:
            for t in todays.sort_values("symbol").itertuples():
                if len(open_pos) >= slots or t.symbol in held:
                    continue
                stop_dist = abs(t.entry - t.stop_px) / t.entry
                if not np.isfinite(stop_dist) or stop_dist <= 0.001:
                    continue
                notional = min(eq * risk / stop_dist, eq * 0.25)
                open_pos.append((int(t.exit_di), notional * t.p / 100.0, t.symbol))
                held.add(t.symbol); taken += 1
        curve.append((CAL[i], eq + sum(p[1] for p in open_pos)))
    cv = pd.Series(dict(curve)).sort_index()
    yrs = (cv.index[-1] - cv.index[0]).days / 365.25
    rets = cv.pct_change().dropna()
    return {"signals": len(ev), "taken": taken,
            "ROI%": round(100 * (cv.iloc[-1] / start - 1), 1),
            "CAGR%": round(100 * ((cv.iloc[-1] / start) ** (1 / yrs) - 1), 1),
            "maxDD%": round(100 * (cv / cv.cummax() - 1).min(), 1),
            "Sharpe": round(rets.mean() / rets.std() * np.sqrt(252), 2)
            if rets.std() > 0 else np.nan,
            "years": round(yrs, 2)}


# ------------------------------------------------------------ the filter
liq = pd.read_parquet("/tmp/gtf/liq.parquet"); liq["date"] = pd.to_datetime(liq["date"])
sel = liq[liq.side.eq("long") & liq.kind.isin(["grab", "sweep"]) & (liq.weekly_slope_pct > 5)]
BY = {s: np.sort(g.bar.to_numpy()) for s, g in sel.groupby("symbol")}


def tagged(sym, bar, w=120):
    arr = BY.get(sym)
    if arr is None or not np.isfinite(bar): return False
    i = np.searchsorted(arr, bar, side="right") - 1
    return i >= 0 and 0 <= bar - arr[i] <= w


# ------------------------------------------------------------ the datasets
sets = {}

s4 = pd.read_parquet("/tmp/gtf/s1s4_exits.parquet")
s4["date"] = pd.to_datetime(s4["entry_date"])
s4["bar"] = BARKEY.reindex(pd.MultiIndex.from_arrays([s4.ticker, s4.date])).to_numpy()
s4 = s4.rename(columns={"ticker": "symbol", "stop": "stop_px",
                        "p_be15": "p", "b_be15": "b"})
for st in ["S1", "S2", "S3", "S4"]:
    sets[st] = s4[s4.strategy.eq(st)][["symbol", "date", "bar", "entry", "stop_px", "p", "b"]]

g7 = pd.read_parquet("/tmp/gtf/ratchet7.parquet"); g7["date"] = pd.to_datetime(g7["date"])
g7 = g7.rename(columns={"p_breakeven only at +15%": "p", "b_breakeven only at +15%": "b"})
g7["stop_px"] = g7.entry - 2.0 * g7.atr_at_entry
sets["GTF 7/7"] = g7[["symbol", "date", "bar", "entry", "stop_px", "p", "b"]]

lq = liq[liq.side.eq("long")].rename(columns={"entry_plan": "entry",
                                              "p_time": "p", "b_time": "b"})
sets["liquidity (standalone)"] = lq[["symbol", "date", "bar", "entry", "stop_px", "p", "b"]]
lqs = sel.rename(columns={"entry_plan": "entry", "p_time": "p", "b_time": "b"})
sets["liquidity + weekly>5%"] = lqs[["symbol", "date", "bar", "entry", "stop_px", "p", "b"]]

print(f"portfolio: Rs {START:,.0f}, {RISK:.0%} risk per trade, {SLOTS} slots, "
      f"one position per symbol, no leverage")
print(f"last 2 years = {CUT.date()} onwards\n")

print("=" * 122)
print("LAST 2 YEARS")
print("=" * 122)
rows = []
for name, df in sets.items():
    d2 = df[df.date >= CUT]
    r = portfolio(d2)
    if r: rows.append({"strategy": name, "version": "every signal", **r})
    if name.startswith("liquidity"):
        continue
    f = pd.Series([tagged(s, b) for s, b in zip(d2.symbol, d2.bar)], index=d2.index)
    r = portfolio(d2[f])
    if r: rows.append({"strategy": name, "version": "liquidity-filtered", **r})
t = pd.DataFrame(rows)
print(t.to_string(index=False))

print("\n" + "=" * 122)
print("SAME, FULL WINDOW (2021-04 to 2026-08) - for context on how much is regime")
print("=" * 122)
rows = []
for name, df in sets.items():
    r = portfolio(df)
    if r: rows.append({"strategy": name, "version": "every signal", **r})
    if name.startswith("liquidity"):
        continue
    f = pd.Series([tagged(s, b) for s, b in zip(df.symbol, df.bar)], index=df.index)
    r = portfolio(df[f])
    if r: rows.append({"strategy": name, "version": "liquidity-filtered", **r})
print(pd.DataFrame(rows).to_string(index=False))

print("\n" + "=" * 122)
print("BENCHMARK: equal-weight universe, same spans")
print("=" * 122)
idx = (wide / wide.shift(1)).mean(axis=1).fillna(1).cumprod()
for lab, sl in (("last 2 years", idx.loc[CUT:]), ("full window", idx)):
    yrs = (sl.index[-1] - sl.index[0]).days / 365.25
    print(f"  {lab:<14} ROI {100*(sl.iloc[-1]/sl.iloc[0]-1):+6.1f}%   "
          f"CAGR {100*((sl.iloc[-1]/sl.iloc[0])**(1/yrs)-1):+6.1f}%   "
          f"maxDD {100*(sl/sl.cummax()-1).min():+6.1f}%")


# --------------------------------------------------------------------------
# The numbers above are not yet trustworthy. S1 has 36,461 signals in the last
# two years and 10 slots take 180 of them. Which 180 is decided by the
# tie-break, and above that tie-break is alphabetical by symbol. So the
# comparison could be measuring the alphabet. Re-run with random selection
# order and look at the spread.
# --------------------------------------------------------------------------
def _arrays(ev):
    ev = ev.dropna(subset=["p", "b", "entry", "stop_px"]).copy()
    ev["di"] = ev.date.map(DMAP)
    ev = ev[ev.di.notna()]
    sd = (ev.entry - ev.stop_px).abs() / ev.entry
    ev = ev[np.isfinite(sd) & (sd > 0.001)]
    if not len(ev):
        return None
    ev = ev.sort_values("di")
    sym, codes = np.unique(ev.symbol.to_numpy(), return_inverse=True)
    return (ev.di.to_numpy(np.int64),
            (ev.di + ev.b).to_numpy(np.int64),
            ((ev.entry - ev.stop_px).abs() / ev.entry).to_numpy(float),
            ev.p.to_numpy(float), codes, len(sym))


def portfolio_rand(arr, seed, slots=SLOTS, risk=RISK, start=START):
    """Same simulator, driven by a random priority instead of the alphabet."""
    if arr is None:
        return np.nan
    di, xi, sd, p, code, nsym = arr
    rng = np.random.default_rng(seed)
    order = np.lexsort((rng.random(len(di)), di))       # random within each day
    di, xi, sd, p, code = di[order], xi[order], sd[order], p[order], code[order]
    lo, hi = di[0], min(int(xi.max()), len(CAL) - 1)
    eq = start
    exit_di = np.empty(0, np.int64); pnl = np.empty(0, float)
    open_code = np.empty(0, np.int64); notl = np.empty(0, float)
    gross = 0.0
    held = np.zeros(nsym, bool)
    ptr = 0
    for i in range(lo, hi + 1):
        done = exit_di <= i
        if done.any():
            eq += pnl[done].sum()
            gross -= notl[done].sum()
            held[open_code[done]] = False
            exit_di, pnl, open_code, notl = (exit_di[~done], pnl[~done],
                                             open_code[~done], notl[~done])
        take_e, take_p, take_c, take_n = [], [], [], []
        while ptr < len(di) and di[ptr] == i:
            k = ptr; ptr += 1
            if len(exit_di) + len(take_e) >= slots or held[code[k]]:
                continue
            # No leverage: gross notional across open positions never exceeds
            # equity. Without this a 50-slot run silently gears up 12x and the
            # slot sweep measures leverage rather than signal quality.
            size = min(eq * risk / sd[k], eq * 0.25, eq - gross)
            if size <= 0:
                continue
            gross += size
            held[code[k]] = True
            take_e.append(xi[k])
            take_p.append(size * p[k] / 100.0)
            take_c.append(code[k])
            take_n.append(size)
        if take_e:
            exit_di = np.concatenate([exit_di, np.array(take_e, np.int64)])
            pnl = np.concatenate([pnl, np.array(take_p, float)])
            open_code = np.concatenate([open_code, np.array(take_c, np.int64)])
            notl = np.concatenate([notl, np.array(take_n, float)])
    return 100 * ((eq + pnl.sum()) / start - 1)


print("\n" + "=" * 122)
print("HOW MUCH OF THAT IS THE SELECTION ORDER? 40 random orderings, last 2 years")
print("=" * 122)
rows = []
for name, df in sets.items():
    d2 = df[df.date >= CUT]
    variants = [("every signal", d2)]
    if not name.startswith("liquidity"):
        f = pd.Series([tagged(s, b) for s, b in zip(d2.symbol, d2.bar)], index=d2.index)
        variants.append(("liquidity-filtered", d2[f]))
    for vlab, dv in variants:
        A = _arrays(dv)
        r = np.array([portfolio_rand(A, s) for s in range(40)])
        r = r[np.isfinite(r)]
        if not len(r): continue
        rows.append({"strategy": name, "version": vlab, "signals": len(dv),
                     "median ROI%": round(float(np.median(r)), 1),
                     "10th pct": round(float(np.percentile(r, 10)), 1),
                     "90th pct": round(float(np.percentile(r, 90)), 1),
                     "spread": round(float(np.percentile(r, 90) - np.percentile(r, 10)), 1),
                     "P(beat +7.9% index)": f"{100*(r > 7.9).mean():.0f}%"})
res = pd.DataFrame(rows)
print(res.to_string(index=False))

print("\n" + "=" * 122)
print("THE ONLY COMPARISON THAT MEANS ANYTHING: same 40 orderings, paired")
print("=" * 122)
rows = []
for name, df in sets.items():
    if name.startswith("liquidity"): continue
    d2 = df[df.date >= CUT]
    f = pd.Series([tagged(s, b) for s, b in zip(d2.symbol, d2.bar)], index=d2.index)
    A, B = _arrays(d2), _arrays(d2[f])
    a = np.array([portfolio_rand(A, s) for s in range(40)])
    b = np.array([portfolio_rand(B, s) for s in range(40)])
    ok = np.isfinite(a) & np.isfinite(b)
    diff = b[ok] - a[ok]
    rows.append({"strategy": name,
                 "base median ROI%": round(float(np.median(a[ok])), 1),
                 "filtered median ROI%": round(float(np.median(b[ok])), 1),
                 "median change": round(float(np.median(diff)), 1),
                 "filter helped in": f"{100*(diff > 0).mean():.0f}% of orderings"})
print(pd.DataFrame(rows).to_string(index=False))


print("\n" + "=" * 122)
print("SLOT SWEEP - 10 slots against 36,000 signals is mostly a queue, not a strategy.")
print("Median of 25 random orderings, last 2 years. Index over the same span: +7.9%")
print("=" * 122)
rows = []
for name, df in sets.items():
    d2 = df[df.date >= CUT]
    variants = [("every signal", d2)]
    if not name.startswith("liquidity"):
        f = pd.Series([tagged(s, b) for s, b in zip(d2.symbol, d2.bar)], index=d2.index)
        variants.append(("liquidity-filtered", d2[f]))
    for vlab, dv in variants:
        A = _arrays(dv)
        row = {"strategy": name, "version": vlab}
        for slots in (5, 10, 20, 30, 50):
            r = np.array([portfolio_rand(A, s, slots=slots) for s in range(25)])
            row[f"{slots} slots"] = round(float(np.median(r[np.isfinite(r)])), 1)
        rows.append(row)
print(pd.DataFrame(rows).to_string(index=False))


print("\n" + "=" * 122)
print("ANSWER TABLE - last 2 years, 10 slots, no leverage, median of 40 random")
print("orderings. CAGR derived from the same median ROI over the same span.")
print("=" * 122)
rows = []
for name, df in sets.items():
    d2 = df[df.date >= CUT]
    yrs = (d2.date.max() - d2.date.min()).days / 365.25
    variants = [("every signal", d2)]
    if not name.startswith("liquidity"):
        f = pd.Series([tagged(s, b) for s, b in zip(d2.symbol, d2.bar)], index=d2.index)
        variants.append(("liquidity-filtered", d2[f]))
    for vlab, dv in variants:
        A = _arrays(dv)
        r = np.array([portfolio_rand(A, s) for s in range(40)])
        r = r[np.isfinite(r)]
        med = float(np.median(r))
        rows.append({"strategy": name, "version": vlab,
                     "ROI%": round(med, 1),
                     "CAGR%": round(100 * ((1 + med / 100) ** (1 / 2.0) - 1), 1),
                     "worst ordering": round(float(r.min()), 1),
                     "best ordering": round(float(r.max()), 1),
                     "beat index": f"{100*(r > 7.9).mean():.0f}%"})
print(pd.DataFrame(rows).to_string(index=False))
print("\nequal-weight index over the same 2 years: ROI +7.9%, CAGR +3.9%")
