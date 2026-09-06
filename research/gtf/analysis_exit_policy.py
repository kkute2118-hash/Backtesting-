"""Which exit policy? Chosen on TRAIN, then read once on val and test."""
import numpy as np, pandas as pd
import candidates as K
pd.set_option("display.width", 250)

d = pd.read_parquet("/tmp/gtf/events.parquet"); d["date"] = pd.to_datetime(d["date"])
x = pd.read_parquet("/tmp/gtf/exits.parquet")
d = pd.concat([d, x[[c for c in x.columns if c.startswith("x_")]]], axis=1)
d = d[d.gap_through == 0].copy()
c = pd.read_parquet("/tmp/gtf/control.parquet"); c["date"] = pd.to_datetime(c["date"])

TR = d[d.date < "2024-04-01"]
q = lambda f, pp: float(np.nanpercentile(TR[f], pp))
TH = dict(atr=q("atr_pct", 50), legout=q("legout_atr", 50),
          risk=q("risk_pct", 40), speed=q("prev_close_pct", 50))
def C12(z):
    return (z.risk_pct.ge(TH["risk"]) & z.legout_atr.ge(TH["legout"])
            & z.atr_pct.ge(TH["atr"]) & z.prev_close_pct.ge(TH["speed"])
            & z.dist_ema200_atr.le(0.96))

POL = [c_ for c_ in d.columns if c_.startswith("x_")]
SPL = {"train": d.date < "2024-04-01",
       "val": (d.date >= "2024-04-01") & (d.date < "2025-07-01"),
       "test": d.date >= "2025-07-01"}

def stats(s):
    s = s[np.isfinite(s)]
    if len(s) < 50: return dict(n=len(s))
    w = s[s > 0]; l = s[s <= 0]; eq = np.cumsum(s)
    return dict(n=len(s), win=100 * len(w) / len(s), avg=s.mean(),
                PF=w.sum() / -l.sum() if l.sum() < 0 else np.inf,
                maxDD=float((eq - np.maximum.accumulate(eq)).min()))

print("=" * 122)
print("EXIT POLICY on the C12 signal set. Selection is on TRAIN; val and test are read once.")
print("=" * 122)
W = {k: d[m & C12(d)] for k, m in SPL.items()}
rows = []
for p in POL:
    r = {"policy": p[2:]}
    for k in ("train", "val", "test"):
        st = stats(W[k][p].to_numpy())
        r[f"avg%_{k}"] = st.get("avg"); r[f"PF_{k}"] = st.get("PF")
    r["win%_tr"] = stats(W["train"][p].to_numpy()).get("win")
    r["maxDD_tr"] = stats(W["train"][p].to_numpy()).get("maxDD")
    rows.append(r)
t = pd.DataFrame(rows).sort_values("avg%_train", ascending=False)
print(t.round(3).to_string(index=False))

best = t.iloc[0]["policy"]
print(f"\nbest on train: {best}")

print("\n" + "=" * 122)
print("Does it beat the placebo, or is it just holding longer in a rising market?")
print("=" * 122)
# the control has no path simulation, so compare on the shared static policy and
# on buy-and-hold-for-60-bars, which is what a loose trail degenerates towards
print("static fix_2_4, real vs placebo (train):")
print("  real   ", {k: round(v, 3) for k, v in stats(W["train"]["x_fix_2_4"].to_numpy()).items()})
cm = c[c.date < "2024-04-01"]
cp = K.pct_pnl(cm)
print("  placebo", {k: round(v, 3) for k, v in stats(cp).items()})
print("\nhold-60-bars-no-stop equivalent (ret60 minus cost), train:")
print("  real   ", {k: round(v, 3) for k, v in stats(W["train"].ret60.to_numpy() - 0.23).items()})
print("  placebo", {k: round(v, 3) for k, v in stats(cm.ret60.to_numpy() - 0.23).items()})

print("\n" + "=" * 122)
print("Top policies, full detail across splits")
print("=" * 122)
for p in list(t.policy.head(4)) + ["fix_2_4"]:
    col = "x_" + p
    line = f"{p:<14}"
    for k in ("train", "val", "test"):
        st = stats(W[k][col].to_numpy())
        line += (f" | {k}: n={st['n']:>4} win={st.get('win', 0):.1f}% "
                 f"avg={st.get('avg', 0):+.2f}% PF={st.get('PF', 0):.2f}")
    print(line)
