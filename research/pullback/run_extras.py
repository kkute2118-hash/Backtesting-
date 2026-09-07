"""Follow-up checks that need their own feature build or a corrected sweep.

  * entry_window sweep, after the signal study was taught to honour it;
  * anchored-VWAP anchor lookback (AMBIG-1) — needs the feature cache rebuilt;
  * relative-strength lookback (AMBIG-5) — likewise;
  * profit concentration and the drop-the-best-N test;
  * trade examples for the report.
"""

from __future__ import annotations

import argparse
import json
import os
import pickle

from . import features as ft
from .run_study import portfolio, signal_stats, signals
from .strategy import Config, variant


def rebuild(db: str, avwap_lookback: int, rs_days: int, cache_dir: str) -> dict:
    key = os.path.join(cache_dir, f"cache_av{avwap_lookback}_rs{rs_days}.pkl")
    if os.path.exists(key):
        with open(key, "rb") as fh:
            return pickle.load(fh)
    candles = ft.load_candles(db)
    feats = {}
    for sym, df in candles.items():
        f = ft.build_features(df, avwap_lookback=avwap_lookback)
        if rs_days != 63:
            f["ret63"] = f["close"] / f["close"].shift(rs_days) - 1.0
        feats[sym] = f
    blob = {"feats": feats, "market": ft.build_market(feats), "rs": ft.cross_sectional_rs(feats)}
    with open(key, "wb") as fh:
        pickle.dump(blob, fh, protocol=4)
    return blob


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--cache", required=True)
    ap.add_argument("--cache-dir", required=True)
    args = ap.parse_args()
    with open(args.cache, "rb") as fh:
        blob = pickle.load(fh)
    base = variant(Config(), "B_ceiling_only", use_adr_stop_cap=False)
    payload = {}

    # --- entry window, now honoured by the signal study ----------------------
    rows = []
    for w in (1, 2, 3, 5):
        st = signal_stats(signals(blob, variant(base, f"entry_window={w}", entry_window=w)),
                          f"entry_window={w}")
        st["param"], st["value"] = "entry_window", w
        rows.append(st)
        print(f"entry_window={w}: n={st.get('triggered_and_taken')} avgR={st.get('avg_r'):.3f}", flush=True)
    payload["entry_window"] = rows

    # --- anchored VWAP anchor lookback (AMBIG-1) -----------------------------
    rows = []
    for lb in (30, 60, 90, 120):
        b2 = rebuild(args.db, lb, 63, args.cache_dir)
        st = signal_stats(signals(b2, variant(base, f"avwap_lookback={lb}")), f"avwap_lookback={lb}")
        st["param"], st["value"] = "avwap_lookback", lb
        rows.append(st)
        print(f"avwap_lookback={lb}: n={st.get('triggered_and_taken')} avgR={st.get('avg_r'):.3f}", flush=True)
    payload["avwap_lookback"] = rows

    # --- relative-strength lookback (AMBIG-5) --------------------------------
    rows = []
    for d in (21, 63, 126):
        b2 = rebuild(args.db, 60, d, args.cache_dir)
        st = signal_stats(signals(b2, variant(base, f"rs_days={d}")), f"rs_days={d}")
        st["param"], st["value"] = "rs_days", d
        rows.append(st)
        print(f"rs_days={d}: n={st.get('triggered_and_taken')} avgR={st.get('avg_r'):.3f}", flush=True)
    payload["rs_lookback"] = rows

    # --- concentration / drop-the-best-N -------------------------------------
    conc = {}
    for name, cfg in (("A_literal", Config(label="A_literal")), ("B_ceiling_only", base)):
        res = portfolio(blob, cfg)
        t = res["trades"]
        r = t["r_multiple"].sort_values(ascending=False)
        c = {"trades": len(t), "total_r": float(r.sum())}
        for k in (1, 5, 10):
            if len(r) > k:
                c[f"total_r_ex_top{k}"] = float(r.sum() - r.head(k).sum())
        # equity result with the best N trades removed (P&L, not R)
        p = t["pnl"].sort_values(ascending=False)
        for k in (1, 5, 10):
            if len(p) > k:
                c[f"net_pnl_ex_top{k}"] = float(p.sum() - p.head(k).sum())
        c["net_pnl"] = float(t["pnl"].sum())
        c["exit_reasons"] = t["exit_reason"].value_counts().to_dict()
        conc[name] = c
        print(name, json.dumps(c, default=str)[:220], flush=True)
    payload["concentration"] = conc

    # --- trade examples -------------------------------------------------------
    res = portfolio(blob, base)
    t = res["trades"].copy()
    t["entry_date"] = t["entry_date"].astype(str)
    t["exit_date"] = t["exit_date"].astype(str)
    t["setup_date"] = t["setup_date"].astype(str)
    cols = ["symbol", "setup_date", "entry_date", "exit_date", "entry", "stop", "avg_exit",
            "stop_pct", "r_multiple", "pnl_pct", "holding_bars", "exit_reason", "mfe_pct",
            "mae_pct", "confluence", "levels", "rs_rank", "adr20"]
    payload["examples"] = {
        "best": json.loads(t.nlargest(5, "r_multiple")[cols].to_json(orient="records")),
        "worst": json.loads(t.nsmallest(5, "r_multiple")[cols].to_json(orient="records")),
        "typical_winner": json.loads(
            t[t.r_multiple > 0].iloc[(t[t.r_multiple > 0]["r_multiple"] -
                                      t[t.r_multiple > 0]["r_multiple"].median()).abs()
                                     .argsort()[:3]][cols].to_json(orient="records")),
        "typical_loser": json.loads(
            t[t.r_multiple <= 0].iloc[(t[t.r_multiple <= 0]["r_multiple"] -
                                       t[t.r_multiple <= 0]["r_multiple"].median()).abs()
                                      .argsort()[:3]][cols].to_json(orient="records")),
    }

    # --- monthly equity path --------------------------------------------------
    eq = res["equity"]["equity"]
    monthly = eq.resample("ME").last()
    payload["monthly_equity"] = {str(k.date()): float(v) for k, v in monthly.items()}

    with open(os.path.join(args.out, "extras.json"), "w") as fh:
        json.dump(payload, fh, indent=2, default=str)
    print("written", os.path.join(args.out, "extras.json"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
