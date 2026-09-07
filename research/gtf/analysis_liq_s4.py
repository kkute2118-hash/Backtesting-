"""S4 is the only strategy the filter improved. Is it better selection, or
just less exposure? Per trade the kept S4 signals were WORSE in the last two
years (+0.15% vs +1.19%), yet the portfolio improved. Those two facts can
only be reconciled by exposure, so measure exposure directly.
"""
import numpy as np, pandas as pd, sqlite3
pd.set_option("display.width", 200)

src = open("analysis_liq_roi.py").read()
exec(src[:src.index('print(f"portfolio:')] + src[src.index("def _arrays("):src.index("print(\"\\n\" + \"=\" * 122)\nprint(\"HOW MUCH OF THAT")])

def taken_stats(dv, slots=10, seeds=25):
    A = _arrays(dv)
    if A is None: return None
    di, xi, sd, p, code, nsym = A
    n_taken, bars_held, pnl_taken = [], [], []
    for seed in range(seeds):
        rng = np.random.default_rng(seed)
        order = np.lexsort((rng.random(len(di)), di))
        d2, x2, s2, p2, c2 = di[order], xi[order], sd[order], p[order], code[order]
        open_x = []; open_c = []; took = []
        ptr = 0
        for i in range(d2[0], min(int(x2.max()), len(CAL) - 1) + 1):
            keep = [k for k in range(len(open_x)) if open_x[k] > i]
            open_x = [open_x[k] for k in keep]; open_c = [open_c[k] for k in keep]
            while ptr < len(d2) and d2[ptr] == i:
                k = ptr; ptr += 1
                if len(open_x) >= slots or c2[k] in open_c: continue
                open_x.append(x2[k]); open_c.append(c2[k])
                took.append((p2[k], x2[k] - d2[k]))
        n_taken.append(len(took))
        pnl_taken.append(np.mean([t[0] for t in took]) if took else np.nan)
        bars_held.append(np.mean([t[1] for t in took]) if took else np.nan)
    return (int(np.median(n_taken)), round(float(np.nanmedian(pnl_taken)), 2),
            round(float(np.nanmedian(bars_held)), 1))

print("Last 2 years, 10 slots, median over 25 random orderings\n")
rows = []
for name, df in sets.items():
    if name.startswith("liquidity"): continue
    d2 = df[df.date >= CUT]
    f = pd.Series([tagged(s, b) for s, b in zip(d2.symbol, d2.bar)], index=d2.index)
    for lab, dv in (("every signal", d2), ("liquidity-filtered", d2[f])):
        r = taken_stats(dv)
        if r is None: continue
        rows.append({"strategy": name, "version": lab, "signals available": len(dv),
                     "trades taken": r[0], "avg % per taken trade": r[1],
                     "avg bars held": r[2],
                     "capital-days used": int(r[0] * r[2])})
print(pd.DataFrame(rows).to_string(index=False))
print("\nIf a filter improves the portfolio while its trades are individually")
print("worse, the gain came from being out of the market, not from picking better.")
