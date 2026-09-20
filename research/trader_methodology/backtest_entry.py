"""Does waiting for his entry beat entering on the scan bar?

Same candidates, same exits, one difference: WHEN you buy.

  IMMEDIATE  buy the close after the scanner fires        (what we do today)
  WAITED     hold the candidate and buy only when one of his triggers
             appears within the wait window; if none appears, no trade

Scanner logic is untouched - this reads core.strategy_signal() and changes
nothing about what a signal is.

Both arms are priced two ways, because his stop and ours are different sizes
and comparing raw percentages would quietly credit the wider stop for size it
could never have carried:

  flat   7% stop, 3R target - the platform's current model
  pivot  stop under the DC low, exit on a decisive close below the 10 EMA

Usage:
    python research/trader_methodology/backtest_entry.py --fixture
"""

from __future__ import annotations

import argparse, os, sys, warnings
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "backend"))

FLAT_STOP = 0.07
R_TARGET = 3.0
MAX_HOLD = 120


def exit_flat(df, e, stop, tgt):
    for j in range(e, min(len(df), e + MAX_HOLD)):
        if float(df.low.iloc[j]) <= stop:
            return stop, j - e, "stop"
        if float(df.high.iloc[j]) >= tgt:
            return tgt, j - e, "target"
    j = min(len(df) - 1, e + MAX_HOLD - 1)
    return float(df.close.iloc[j]), j - e, "timeout"


def exit_pivot(df, ema10, e, stop):
    for j in range(e, min(len(df), e + MAX_HOLD)):
        if float(df.low.iloc[j]) <= stop:
            return stop, j - e, "stop"
        if j > e and float(df.close.iloc[j]) < float(ema10.iloc[j]) * 0.995:
            return float(df.close.iloc[j]), j - e, "ema10"
    j = min(len(df) - 1, e + MAX_HOLD - 1)
    return float(df.close.iloc[j]), j - e, "timeout"


def run(symbols, core, te):
    rows = []
    for k, sym in enumerate(symbols):
        if k % 25 == 0:
            print(f"  {k}/{len(symbols)}", file=sys.stderr, flush=True)
        d = core.load_scan_dataset([sym]).get(sym)
        if d is None or len(d) < 300:
            continue
        d = d.sort_index()
        try:
            f = core.features_fast(str(sym), d).replace([np.inf, -np.inf], np.nan)
        except Exception:
            continue
        if f.empty:
            continue

        e = te.emas(d.close)
        pre = {"emas": e, "vmed": d.volume.rolling(20, min_periods=10).median()}
        ema10 = e["ema10"]

        for s in core.IMPLEMENTED_STRATEGIES:
            try:
                sig = core.strategy_signal(f, s).fillna(False).to_numpy()
            except Exception:
                continue
            for i in np.flatnonzero(sig):
                i = int(i)
                if i < 260 or i >= len(d) - 3:
                    continue
                row = {"symbol": sym, "strategy": f"S{s}",
                       "date": pd.Timestamp(d.index[i]).date().isoformat(),
                       "year": pd.Timestamp(d.index[i]).year}

                # --- IMMEDIATE: buy the close after the signal --------------
                ei = i + 1
                en = float(d.close.iloc[ei])
                if en <= 0:
                    continue
                st = en * (1 - FLAT_STOP)
                x, b, r = exit_flat(d, ei, st, en + R_TARGET * (en - st))
                row.update(imm_ret=(x - en) / en * 100, imm_r=(x - en) / (en - st),
                           imm_bars=b, imm_exit=r, imm_risk=FLAT_STOP * 100)

                # --- WAITED: buy only on one of his triggers ----------------
                ent = te.find_entry(d, i, pre=pre)
                if ent and ent["stop"] and ent["entry_i"] < len(d) - 1:
                    ei2, en2, st2 = ent["entry_i"], ent["entry"], ent["stop"]
                    x2, b2, r2 = exit_pivot(d, ema10, ei2, st2)

                    # His explicit defence against a tight stop being taken
                    # out by noise: "whether it looks like this, dips a little
                    # bit below, takes your SL, goes up and does it again -
                    # well, then you enter it again. Because if you don't,
                    # then you will not make that system work for you."
                    # Modelled as up to two re-entries, each on the next
                    # trigger after the stop-out, cost carried forward.
                    chain, cur_i, tries = (x2 - en2) / en2 * 100, ei2 + b2, 0
                    chain_r = (x2 - en2) / (en2 - st2) if en2 > st2 else np.nan
                    last_reason = r2
                    while last_reason == "stop" and tries < 2 and cur_i < len(d) - 3:
                        nxt = te.find_entry(d, cur_i, pre=pre)
                        if not (nxt and nxt["stop"] and nxt["entry_i"] < len(d) - 1):
                            break
                        ni, nen, nst = nxt["entry_i"], nxt["entry"], nxt["stop"]
                        if nen <= nst:
                            break
                        nx, nb, last_reason = exit_pivot(d, ema10, ni, nst)
                        chain += (nx - nen) / nen * 100
                        chain_r += (nx - nen) / (nen - nst)
                        cur_i, tries = ni + nb, tries + 1
                    row.update(chain_ret=chain, chain_r=chain_r, reentries=tries)
                    xf, bf, rf = exit_flat(d, ei2, en2 * (1 - FLAT_STOP),
                                           en2 * (1 + R_TARGET * FLAT_STOP))
                    row.update(
                        waited=True, trigger=ent["trigger"], zone=str(ent["zone"]),
                        wait_bars=ent["bars_waited"], w_risk=ent["risk_pct"],
                        w_ret=(x2 - en2) / en2 * 100,
                        w_r=(x2 - en2) / (en2 - st2) if en2 > st2 else np.nan,
                        w_bars=b2, w_exit=r2,
                        wflat_ret=(xf - en2) / en2 * 100,
                        wflat_r=(xf - en2) / (en2 * FLAT_STOP),
                    )
                else:
                    row.update(waited=False, trigger=None, zone=None)
                rows.append(row)
    return pd.DataFrame(rows)


def summarise(df):
    o = []
    w = df[df.waited]

    def line(lbl, d, col):
        if d.empty or d[col].isna().all():
            o.append(f"{lbl:38s} (none)"); return
        x = d[col].dropna()
        o.append(f"{lbl:38s} n={len(x):6d}  win={100*(x>0).mean():5.1f}%  "
                 f"mean={x.mean():+7.3f}  med={x.median():+7.3f}")

    o.append("=" * 100)
    o.append("Same candidates, same exit (flat 7% / 3R). Only the entry bar differs.")
    o.append("=" * 100)
    line("IMMEDIATE  all signals  (%)", df, "imm_ret")
    line("IMMEDIATE  those that later triggered", w, "imm_ret")
    line("WAITED     his entry    (%)", w, "wflat_ret")
    o.append("")
    o.append("  The middle row is the fair control: the same trades, bought early")
    o.append("  instead of on the trigger. Comparing row 3 to row 1 would confuse")
    o.append("  better timing with a smaller, easier subset.")

    o.append("")
    o.append("=" * 100)
    o.append("His stop and exit (DC-low stop, decisive close below 10 EMA)")
    o.append("=" * 100)
    line("WAITED     pivot stop   (%)", w, "w_ret")
    line("WAITED     pivot stop   (R)", w, "w_r")
    line("WAITED     + re-entry   (%)", w, "chain_ret")
    line("WAITED     + re-entry   (R)", w, "chain_r")
    line("IMMEDIATE  flat stop    (R)", df, "imm_r")
    if "reentries" in w and w.reentries.notna().any():
        o.append(f"  re-entries used: {int(w.reentries.sum()):d} across "
                 f"{int((w.reentries>0).sum()):d} of {len(w):d} trades")

    o.append("")
    o.append("=" * 100)
    o.append("Stop width - the whole point of waiting")
    o.append("=" * 100)
    if not w.empty and w.w_risk.notna().any():
        o.append(f"  his entry     median {w.w_risk.median():5.2f}%   "
                 f"mean {w.w_risk.mean():5.2f}%   p90 {w.w_risk.quantile(.9):5.2f}%")
        o.append(f"  scan bar      flat   {FLAT_STOP*100:5.2f}%")
        o.append(f"  case studies  daily STF 3%, weekly 6%, monthly 10%")

    o.append("")
    o.append("=" * 100)
    o.append("How often his entry appears at all")
    o.append("=" * 100)
    o.append(f"  signals              {len(df):6d}")
    o.append(f"  produced an entry    {len(w):6d}  ({100*len(w)/max(len(df),1):4.1f}%)")
    if not w.empty:
        o.append(f"  median wait          {int(w.wait_bars.median()):6d} bars")
        o.append("")
        o.append("  by trigger:")
        for t, g in w.groupby("trigger"):
            o.append(f"    {t:22s} n={len(g):5d}  flat-exit mean {g.wflat_ret.mean():+6.2f}%  "
                     f"median stop {g.w_risk.median():5.2f}%")
        o.append("")
        o.append("  by zone:")
        for z, g in w.groupby("zone"):
            o.append(f"    {z:22s} n={len(g):5d}  flat-exit mean {g.wflat_ret.mean():+6.2f}%  "
                     f"median stop {g.w_risk.median():5.2f}%")

    o.append("")
    o.append("=" * 100)
    o.append("Per strategy (flat exit, immediate vs waited)")
    o.append("=" * 100)
    for s in sorted(df.strategy.unique()):
        a = df[df.strategy == s]; b = a[a.waited]
        o.append(f"  {s}  immediate n={len(a):6d} {a.imm_ret.mean():+6.2f}%   "
                 f"waited n={len(b):5d} "
                 + (f"{b.wflat_ret.mean():+6.2f}%" if len(b) else "   --   "))

    o.append("")
    o.append("=" * 100)
    o.append("Per year (flat exit)")
    o.append("=" * 100)
    for y in sorted(df.year.unique()):
        a = df[df.year == y]; b = a[a.waited]
        o.append(f"  {y}  immediate n={len(a):6d} {a.imm_ret.mean():+6.2f}%   "
                 f"waited n={len(b):5d} "
                 + (f"{b.wflat_ret.mean():+6.2f}%" if len(b) else "   --   "))
    return "\n".join(o)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fixture", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--out", default=os.path.join(HERE, "entry_results.csv"))
    a = ap.parse_args()

    if a.fixture:
        sys.path.insert(0, os.path.join(ROOT, "backend", "tests", "golden"))
        import conftest_helpers as H
        H.install_fixture_db()
        from app.engine import core
        symbols = H.fixture_symbols(core)
    else:
        from app.engine import core
        con = core._db()
        try:
            symbols = [r[0] for r in con.execute(
                "SELECT symbol FROM candles WHERE symbol NOT LIKE '^%' "
                "GROUP BY symbol HAVING COUNT(*)>=300 ORDER BY symbol")]
        finally:
            con.close()

    import importlib.util as u
    spec = u.spec_from_file_location(
        "trader_entry", os.path.join(ROOT, "backend", "app", "engine", "trader_entry.py"))
    te = u.module_from_spec(spec); spec.loader.exec_module(te)

    if a.limit:
        symbols = symbols[: a.limit]
    print(f"symbols: {len(symbols)}", file=sys.stderr)
    df = run(symbols, core, te)
    if df.empty:
        print("no signals"); return
    df.to_csv(a.out, index=False)
    print(summarise(df))
    print(f"\nrows -> {a.out}")


if __name__ == "__main__":
    main()
