"""Do the transcript's liquidity patterns work, on our data, as defined?"""
import numpy as np, pandas as pd
pd.set_option("display.width", 250)

d = pd.read_parquet("/tmp/gtf/liq.parquet"); d["date"] = pd.to_datetime(d["date"])
CUT = "2024-09-04"
print(f"{len(d)} setups, {d.symbol.nunique()} symbols, "
      f"{d.date.min().date()} .. {d.date.max().date()}")
print(f"last 2 years: {(d.date >= CUT).sum()} setups\n")


def st(x, label=""):
    x = np.asarray(x, float); x = x[np.isfinite(x)]
    if len(x) < 25:
        return {"set": label, "n": len(x)}
    w = x[x > 0]; l = x[x <= 0]
    return {"set": label, "n": len(x), "win%": round(100 * len(w) / len(x), 1),
            "avg%": round(float(x.mean()), 2),
            "med%": round(float(np.median(x)), 2),
            "PF": round(w.sum() / -l.sum(), 2) if l.sum() < 0 else np.inf,
            "avg win": round(float(w.mean()), 1) if len(w) else np.nan,
            "avg loss": round(float(l.mean()), 1) if len(l) else np.nan}


print("=" * 118)
print("1. EACH PATTERN, AS THE TRANSCRIPT DEFINES IT")
print("   grab/sweep = reversal trade.  run = breakout trade, WITH the break.")
print("=" * 118)
for col, lab in (("p_liq", "target = nearest opposing liquidity pool"),
                 ("p_8atr", "target = 8 ATR"),
                 ("p_time", "no target, 60-bar time exit")):
    rows = []
    for (k, s), g in d.groupby(["kind", "side"]):
        rows.append(st(g[col], f"{k} {s}"))
        rows[-1]["last2y"] = st(g.loc[g.date >= CUT, col]).get("avg%", np.nan)
    print(f"\n{lab}")
    print(pd.DataFrame(rows).to_string(index=False))

print("\n" + "=" * 118)
print("2. THE CENTRAL CLAIM: does the classifier separate reversal from continuation?")
print("   Same bar, same stop distance - only the direction differs.")
print("=" * 118)
rows = []
for k, g in d.groupby("kind"):
    for s in ("long", "short"):
        gg = g[g.side.eq(s)]
        if len(gg) < 25: continue
        a = st(gg["p_time"])
        rows.append({"pattern": k, "traded": s, "n": a.get("n"),
                     "win%": a.get("win%"), "avg%": a.get("avg%")})
print(pd.DataFrame(rows).to_string(index=False))
print("\nIf the classifier is real, 'run' held in its break direction should beat")
print("'grab'/'sweep' held in the same direction as their break (which they fade).")

print("\n" + "=" * 118)
print("3. WHICH OF THE SPEAKER'S DISCRIMINATORS ACTUALLY DISCRIMINATE?")
print("=" * 118)
for kind in ("grab", "sweep", "run"):
    g = d[d.kind.eq(kind)]
    print(f"\n-- {kind} (n={len(g)}) --")
    for f, bins in (("level_touches", [0, 1, 2, 3, 99]),
                    ("conf_body_mult", [0, 1, 2, 3, 5, 1e9]),
                    ("conf_relvol", [0, 1, 1.5, 2, 3, 99]),
                    ("take_relvol", [0, 1, 1.5, 2, 3, 99]),
                    ("poke_atr", [0, 0.25, 0.5, 1, 2, 99]),
                    ("level_age", [0, 40, 80, 150, 250, 9999]),
                    ("weekly_slope_pct", [-999, -5, 0, 5, 15, 999]),
                    ("dist_ema200_atr", [-999, -3, 0, 3, 999])):
        b = pd.cut(g[f], bins)
        t = g.groupby(b, observed=True)["p_time"].agg(["size", "mean"])
        t = t[t["size"] >= 60]
        if len(t) >= 2:
            print(f"  {f:<18} " + "  ".join(
                f"{str(i):>13}:{r['mean']:+6.2f}% (n={int(r['size'])})" for i, r in t.iterrows()))
    for f in ("level_res", "target_res"):
        t = g.groupby(f, observed=True)["p_time"].agg(["size", "mean"])
        t = t[t["size"] >= 60]
        if len(t) >= 2:
            print(f"  {f:<18} " + "  ".join(
                f"{str(i):>13}:{r['mean']:+6.2f}% (n={int(r['size'])})" for i, r in t.iterrows()))

print("\n" + "=" * 118)
print("4. BY YEAR (no target, time exit) - is any of it stable?")
print("=" * 118)
for k, g in d.groupby("kind"):
    t = g.set_index("date").groupby([pd.Grouper(freq="YE"), "side"])["p_time"].agg(["size", "mean"])
    t = t.unstack("side")
    print(f"\n{k}:")
    print(t.round(2).to_string())

print("\n" + "=" * 118)
print("5. THE TRANSCRIPT'S TARGET RULE vs A FIXED TARGET")
print("=" * 118)
m = d.p_liq.notna()
print(f"{m.sum()} setups have an untapped opposing pool to aim at")
print(pd.DataFrame([
    st(d.loc[m, "p_liq"], "liquidity target"),
    st(d.loc[m, "p_8atr"], "8 ATR target, same rows"),
    st(d.loc[m, "p_time"], "no target, same rows")]).to_string(index=False))
print("\nreward:risk offered by the liquidity target:")
print(d.loc[m, "rr_liq"].describe(percentiles=[.25, .5, .75]).round(2).to_string())
print("\nhow the liquidity-target trades ended:")
print(d.loc[m].groupby(["kind", "exit_liq"]).size().unstack(fill_value=0).to_string())
