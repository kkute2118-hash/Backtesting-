"""One portfolio simulator, used by every comparison.

Rules, and why each is there:

  fixed fractional risk   position size = equity * risk / stop distance, so a
                          wide stop takes a smaller position. This is what
                          makes R the thing that compounds.
  no leverage             gross notional across open positions never exceeds
                          equity. Without this cap a system taking 3 trades a
                          week with 12-week holds silently runs 5x geared and
                          the backtest measures leverage, not selection.
  one position per symbol never doubling up on the same name.
  random tie-break        when more candidates qualify than there is room for,
                          the order is randomised and the whole run repeated.
                          Reporting the median and the spread across orderings
                          stops the alphabet from deciding the answer.
"""
from __future__ import annotations
import numpy as np, pandas as pd

START, RISK, SLOTS = 1_000_000.0, 0.01, 40


def arrays(ev, cal_map, n_days):
    ev = ev.dropna(subset=["p", "b", "entry", "stop_px"]).copy()
    ev["di"] = ev.date.map(cal_map)
    ev = ev[ev.di.notna()]
    sd = (ev.entry - ev.stop_px).abs() / ev.entry
    ev = ev[np.isfinite(sd) & (sd > 0.001)]
    if not len(ev):
        return None
    ev = ev.sort_values("di")
    _, codes = np.unique(ev.symbol.to_numpy(), return_inverse=True)
    return (ev.di.to_numpy(np.int64),
            np.minimum((ev.di + ev.b).to_numpy(np.int64), n_days - 1),
            ((ev.entry - ev.stop_px).abs() / ev.entry).to_numpy(float),
            ev.p.to_numpy(float), codes, int(codes.max()) + 1)


def run(arr, seed=0, slots=SLOTS, risk=RISK, start=START, n_days=None,
        curve=False):
    if arr is None:
        return (np.nan, None) if curve else np.nan
    di, xi, sd, p, code, nsym = arr
    rng = np.random.default_rng(seed)
    order = np.lexsort((rng.random(len(di)), di))
    di, xi, sd, p, code = di[order], xi[order], sd[order], p[order], code[order]
    lo, hi = int(di[0]), int(xi.max())
    eq = start; gross = 0.0
    ex = np.empty(0, np.int64); pnl = np.empty(0, float)
    oc = np.empty(0, np.int64); nt = np.empty(0, float)
    held = np.zeros(nsym, bool)
    ptr = 0; taken = 0; pts = []
    for i in range(lo, hi + 1):
        done = ex <= i
        if done.any():
            eq += pnl[done].sum(); gross -= nt[done].sum()
            held[oc[done]] = False
            ex, pnl, oc, nt = ex[~done], pnl[~done], oc[~done], nt[~done]
        te, tp, tc, tn = [], [], [], []
        while ptr < len(di) and di[ptr] == i:
            k = ptr; ptr += 1
            if len(ex) + len(te) >= slots or held[code[k]]:
                continue
            size = min(eq * risk / sd[k], eq * 0.25, eq - gross)
            if size <= 0:
                continue
            gross += size; held[code[k]] = True
            te.append(xi[k]); tp.append(size * p[k] / 100.0)
            tc.append(code[k]); tn.append(size); taken += 1
        if te:
            ex = np.concatenate([ex, np.array(te, np.int64)])
            pnl = np.concatenate([pnl, np.array(tp, float)])
            oc = np.concatenate([oc, np.array(tc, np.int64)])
            nt = np.concatenate([nt, np.array(tn, float)])
        pts.append((i, eq + pnl.sum()))
    final = eq + pnl.sum()
    if curve:
        return 100 * (final / start - 1), pd.Series(dict(pts)), taken
    return 100 * (final / start - 1)


def summary(arr, cal, seeds=25, years=None, **kw):
    """Median and spread of ROI across selection orderings, plus CAGR."""
    r = np.array([run(arr, seed=s, **kw) for s in range(seeds)])
    r = r[np.isfinite(r)]
    if not len(r):
        return None
    med = float(np.median(r))
    out = {"ROI%": round(med, 1),
           "worst": round(float(r.min()), 1), "best": round(float(r.max()), 1)}
    if years:
        out["CAGR%"] = round(100 * ((1 + med / 100) ** (1 / years) - 1), 1)
    _, cv, taken = run(arr, seed=0, curve=True, **kw)
    if cv is not None and len(cv) > 2:
        eqs = cv.to_numpy()
        out["maxDD%"] = round(100 * float((eqs / np.maximum.accumulate(eqs) - 1).min()), 1)
        rets = pd.Series(eqs).pct_change().dropna()
        out["Sharpe"] = round(float(rets.mean() / rets.std() * np.sqrt(252)), 2) \
            if rets.std() > 0 else np.nan
        out["trades"] = taken
    return out
