"""Runner for the whole study.

  python -m research.pullback.run_study --db <sqlite> --out <dir> --cache <pkl> \
      --phase all

Phases
  original    the strategy exactly as derived, on the last two years
  robustness  concentration, year split, out-of-sample, regime, sensitivity
  ablation    one rule removed at a time, measured on unconstrained signals
"""

from __future__ import annotations

import argparse
import json
import os
import pickle
import sys
import time
from dataclasses import asdict

import numpy as np
import pandas as pd

from . import features as ft
from . import metrics as mt
from . import edge_analysis as ea
from .backtest import run, signal_study
from .strategy import Config, all_setups, variant

WINDOW_2Y = ("2024-09-05", "2026-09-04")
WINDOW_OOS = ("2021-10-01", "2024-09-04")
CAPITAL = 1_000_000.0


# --------------------------------------------------------------------------- #

def build_cache(db: str, cache: str, avwap_lookback: int = ft.AVWAP_LOOKBACK) -> dict:
    if os.path.exists(cache):
        with open(cache, "rb") as fh:
            return pickle.load(fh)
    t0 = time.time()
    candles = ft.load_candles(db)
    print(f"loaded {len(candles)} symbols in {time.time()-t0:.1f}s", flush=True)
    ft.AVWAP_LOOKBACK = avwap_lookback
    feats = {sym: ft.build_features(df) for sym, df in candles.items()}
    blob = {
        "feats": feats,
        "market": ft.build_market(feats),
        "rs": ft.cross_sectional_rs(feats),
        "avwap_lookback": avwap_lookback,
    }
    with open(cache, "wb") as fh:
        pickle.dump(blob, fh, protocol=4)
    print(f"cache built in {time.time()-t0:.1f}s", flush=True)
    return blob


def portfolio(blob: dict, cfg: Config, window=WINDOW_2Y) -> dict:
    s = all_setups(blob["feats"], blob["rs"], blob["market"], cfg)
    res = run(blob["feats"], s, cfg, window[0], window[1], capital=CAPITAL)
    res["setups"] = s
    in_win = s[(s["setup_date"] >= window[0]) & (s["setup_date"] <= window[1])] if len(s) else s
    res["n_setups_in_window"] = int(len(in_win))
    return res


def signals(blob: dict, cfg: Config, window=WINDOW_2Y) -> pd.DataFrame:
    s = all_setups(blob["feats"], blob["rs"], blob["market"], cfg)
    return signal_study(blob["feats"], s, cfg, window[0], window[1])


def signal_stats(sig: pd.DataFrame, label: str) -> dict:
    if not len(sig):
        return {"label": label, "signals": 0}
    traded = sig[sig["r_multiple"].notna()]
    out = {
        "label": label,
        "signals": int(len(sig)),
        "triggered_and_taken": int(len(traded)),
        "rejected_stop_too_wide": int((sig["outcome"] == "stop_too_wide").sum()),
        "no_trigger": int((sig["outcome"] == "no_trigger").sum()),
    }
    if not len(traded):
        return out
    r = traded["r_multiple"]
    wins = traded[r > 0]
    out.update(
        {
            "avg_r": float(r.mean()),
            "median_r": float(r.median()),
            "total_r": float(r.sum()),
            "win_rate_pct": float(100.0 * len(wins) / len(traded)),
            "profit_factor": float(wins["r_multiple"].sum() / -traded[r <= 0]["r_multiple"].sum())
            if (r <= 0).any() and traded[r <= 0]["r_multiple"].sum() != 0 else np.inf,
            "avg_win_r": float(wins["r_multiple"].mean()) if len(wins) else 0.0,
            "avg_loss_r": float(traded[r <= 0]["r_multiple"].mean()) if (r <= 0).any() else 0.0,
            "t_stat": float(r.mean() / (r.std(ddof=1) / np.sqrt(len(r)))) if len(r) > 1 and r.std(ddof=1) > 0 else np.nan,
            "avg_holding_bars": float(traded["holding_bars"].mean()),
            "avg_stop_pct": float(traded["stop_pct"].mean()),
            "avg_mfe_pct": float(traded["mfe_pct"].mean()),
            "avg_mae_pct": float(traded["mae_pct"].mean()),
        }
    )
    return out


# --------------------------------------------------------------------------- #

def phase_original(blob: dict, out: str) -> dict:
    payload = {}
    runs = {
        "A_literal": Config(label="A_literal"),
        "B_ceiling_only": variant(Config(), "B_ceiling_only", use_adr_stop_cap=False),
    }
    for name, cfg in runs.items():
        res = portfolio(blob, cfg)
        s = mt.summarize(res)
        s["setups_in_window"] = res["n_setups_in_window"]
        s["rejected_no_capital"] = res["rejected_no_capital"]
        res["trades"].to_csv(os.path.join(out, f"trades_{name}.csv"), index=False)
        res["equity"].to_csv(os.path.join(out, f"equity_{name}.csv"))
        sig = signals(blob, cfg)
        sig.to_csv(os.path.join(out, f"signals_{name}.csv"), index=False)
        payload[name] = {
            "portfolio": s,
            "signal_level": signal_stats(sig, name),
            "concentration": mt.concentration(res),
            "by_year": json.loads(mt.by_period(res, "YE").to_json(orient="index", date_format="iso")),
            "by_quarter": json.loads(mt.by_period(res, "QE").to_json(orient="index", date_format="iso")),
            "by_month": json.loads(mt.by_period(res, "ME").to_json(orient="index", date_format="iso")),
            "regime": json.loads(mt.regime_table(res, blob["market"].index).to_json(orient="records")),
            "config": {k: (list(v) if isinstance(v, tuple) else v) for k, v in asdict(cfg).items()},
        }
        print(f"[{name}] trades={s['trades']} return={s['total_return_pct']:.1f}% "
              f"PF={s.get('profit_factor', float('nan')):.2f} maxDD={s.get('max_drawdown_pct', float('nan')):.1f}%",
              flush=True)
    with open(os.path.join(out, "original.json"), "w") as fh:
        json.dump(payload, fh, indent=2, default=str)
    return payload


def phase_robustness(blob: dict, out: str) -> dict:
    payload = {}
    base = variant(Config(), "B_ceiling_only", use_adr_stop_cap=False)

    # out-of-sample: the three years before the two-year window
    for name, cfg, window in (
        ("oos_2021_2024", base, WINDOW_OOS),
        ("oos_2021_2024_literal", Config(label="A_literal"), WINDOW_OOS),
    ):
        res = portfolio(blob, cfg, window)
        sig = signals(blob, cfg, window)
        payload[name] = {"portfolio": mt.summarize(res), "signal_level": signal_stats(sig, name)}
        print(f"[{name}] {payload[name]['portfolio']['total_return_pct']:.1f}%", flush=True)

    # intrabar path assumption
    for name, cfg in (
        ("intrabar_adverse", base),
        ("intrabar_benign", variant(base, "intrabar_benign", intrabar="benign")),
    ):
        res = portfolio(blob, cfg)
        payload[name] = {"portfolio": mt.summarize(res),
                         "signal_level": signal_stats(signals(blob, cfg), name)}

    # costs off, to size the cost drag
    zero = variant(base, "zero_cost", cost_round_trip_pct=0.0, slippage_pct=0.0)
    payload["zero_cost"] = {"portfolio": mt.summarize(portfolio(blob, zero)),
                            "signal_level": signal_stats(signals(blob, zero), "zero_cost")}

    # parameter sensitivity, measured on unconstrained signals
    grid = {
        "min_rs_rank": [0.0, 50.0, 60.0, 70.0, 80.0, 90.0],
        "min_adr20": [0.0, 1.5, 2.0, 3.0, 4.0],
        "breadth_min": [0.0, 0.30, 0.40, 0.50],
        "max_stop_pct": [2.5, 3.0, 4.0, 5.0, 8.0],
        "touch_tol": [0.0025, 0.005, 0.01, 0.02],
        "dip_atr": [0.5, 1.0, 2.0, 3.0],
        "min_confluence": [0, 1, 2, 3],
        "entry_window": [1, 2, 3],
        "partial_fraction": [0.0, 0.15, 0.33, 0.50],
        "min_close_pos": [0.0, 0.35, 0.50, 0.65],
    }
    sens = []
    for param, values in grid.items():
        for v in values:
            cfg = variant(base, f"{param}={v}", **{param: v})
            st = signal_stats(signals(blob, cfg), f"{param}={v}")
            st["param"], st["value"] = param, v
            sens.append(st)
            print(f"  sens {param}={v}: n={st.get('triggered_and_taken')} "
                  f"avgR={st.get('avg_r', float('nan')):.3f}", flush=True)
    payload["sensitivity"] = sens

    # partial-target geometry
    geo = []
    for levels in [(), (2.0,), (3.0,), (2.0, 4.0), (3.0, 5.0), (4.0, 8.0), (1.0, 2.0)]:
        cfg = variant(base, f"partials={levels}", partial_r_levels=levels)
        st = signal_stats(signals(blob, cfg), f"partials={levels}")
        st["levels"] = str(levels)
        geo.append(st)
    payload["partial_geometry"] = geo

    # exit-rule readings (AMBIG-3): when does the 9 EMA close rule start to bind?
    exits = []
    for name, kw in (
        ("trail_from_entry", {}),
        ("trail_after_1R", {"trail_activate_r": 1.0}),
        ("trail_after_2R", {"trail_activate_r": 2.0}),
        ("no_trail_stop_only_10d", {"use_ema9_exit": False, "max_holding_bars": 10}),
        ("no_trail_stop_only_20d", {"use_ema9_exit": False, "max_holding_bars": 20}),
        ("no_trail_stop_only_60d", {"use_ema9_exit": False, "max_holding_bars": 60}),
        ("trail_after_1R_no_partials", {"trail_activate_r": 1.0, "partial_r_levels": ()}),
    ):
        cfg = variant(base, name, **kw)
        st = signal_stats(signals(blob, cfg), name)
        res = portfolio(blob, cfg)
        st["portfolio_return_pct"] = mt.summarize(res)["total_return_pct"]
        st["portfolio_max_dd_pct"] = mt.summarize(res).get("max_drawdown_pct")
        exits.append(st)
        print(f"  exit {name}: avgR={st.get('avg_r', float('nan')):.3f} "
              f"port={st['portfolio_return_pct']:.1f}%", flush=True)
    payload["exit_readings"] = exits

    # is there any edge in the signal at all, exits removed?
    setups_base = all_setups(blob["feats"], blob["rs"], blob["market"], base)
    mkt = blob["market"].index
    sig = ea.triggered_edge(blob["feats"], setups_base, mkt, *WINDOW_2Y)
    null = ea.null_sample(blob["feats"], mkt, *WINDOW_2Y, stride=3)
    payload["edge_vs_null"] = json.loads(ea.compare(sig, null).to_json(orient="records"))
    payload["edge_by_confluence"] = json.loads(
        sig.groupby("confluence")[["exc5", "exc10", "exc20"]].agg(["count", "mean"])
        .round(4).to_json(orient="index"))
    sig.to_csv(os.path.join(out, "edge_signal.csv"), index=False)

    # benchmark: what the universe itself did over the window
    lvl = mkt["level"]
    w = lvl[(lvl.index >= WINDOW_2Y[0]) & (lvl.index <= WINDOW_2Y[1])]
    payload["benchmark"] = {
        "equal_weight_index_return_pct": float(100.0 * (w.iloc[-1] / w.iloc[0] - 1.0)),
        "equal_weight_index_max_dd_pct": float(100.0 * (w / w.cummax() - 1.0).min()),
        "median_stock_return_pct": float(np.median([
            100.0 * (f["close"][(f.index >= WINDOW_2Y[0]) & (f.index <= WINDOW_2Y[1])].iloc[-1] /
                     f["close"][(f.index >= WINDOW_2Y[0]) & (f.index <= WINDOW_2Y[1])].iloc[0] - 1.0)
            for f in blob["feats"].values()
            if len(f["close"][(f.index >= WINDOW_2Y[0]) & (f.index <= WINDOW_2Y[1])]) > 100])),
    }
    print("  benchmark:", payload["benchmark"], flush=True)

    with open(os.path.join(out, "robustness.json"), "w") as fh:
        json.dump(payload, fh, indent=2, default=str)
    return payload


ABLATIONS = [
    ("full_strategy", {}),
    ("no_market_trend", {"use_market_trend": False}),
    ("no_market_slope", {"use_market_slope": False}),
    ("no_breadth", {"use_breadth": False}),
    ("no_market_gate_at_all", {"use_market_trend": False, "use_market_slope": False, "use_breadth": False}),
    ("no_liquidity", {"use_liquidity": False}),
    ("no_adr", {"use_adr": False}),
    ("no_daily_trend", {"use_daily_trend": False}),
    ("no_ema150", {"use_ema150": False}),
    ("no_weekly", {"use_weekly": False}),
    ("no_relative_strength", {"use_rs": False}),
    ("no_fresh_leg", {"use_fresh_leg": False}),
    ("no_higher_low", {"use_higher_low": False}),
    ("no_reversal_close", {"use_reversal_close": False}),
    ("no_real_dip", {"use_real_dip": False}),
    ("no_pullback_touch", {"min_confluence": 0}),
    ("no_partials", {"partial_r_levels": ()}),
    ("no_ema9_trail", {"use_ema9_exit": False, "max_holding_bars": 20}),
    ("stock_gate_only", {"use_market_trend": False, "use_market_slope": False,
                         "use_breadth": False, "use_reversal_close": False,
                         "use_real_dip": False}),
]


def phase_ablation(blob: dict, out: str) -> dict:
    base = variant(Config(), "B_ceiling_only", use_adr_stop_cap=False)
    rows, per_year = [], []
    for name, kw in ABLATIONS:
        cfg = variant(base, name, **kw)
        sig = signals(blob, cfg)
        st = signal_stats(sig, name)
        rows.append(st)
        traded = sig[sig["r_multiple"].notna()] if len(sig) else sig
        if len(traded):
            traded = traded.copy()
            traded["year"] = pd.to_datetime(traded["entry_date"]).dt.year
            for y, g in traded.groupby("year"):
                per_year.append({"label": name, "year": int(y), "n": len(g),
                                 "avg_r": float(g["r_multiple"].mean()),
                                 "total_r": float(g["r_multiple"].sum()),
                                 "win_rate": float(100.0 * (g["r_multiple"] > 0).mean())})
        print(f"[ablation {name}] n={st.get('triggered_and_taken')} "
              f"avgR={st.get('avg_r', float('nan')):.3f} PF={st.get('profit_factor', float('nan')):.2f}",
              flush=True)
        # portfolio-level too, for the headline rules
        if name in {"full_strategy", "no_market_gate_at_all", "no_relative_strength",
                    "no_pullback_touch", "no_weekly", "no_partials", "no_ema9_trail"}:
            res = portfolio(blob, cfg)
            rows[-1]["portfolio_return_pct"] = mt.summarize(res)["total_return_pct"]
            rows[-1]["portfolio_trades"] = mt.summarize(res)["trades"]
    payload = {"ablation": rows, "ablation_by_year": per_year}
    with open(os.path.join(out, "ablation.json"), "w") as fh:
        json.dump(payload, fh, indent=2, default=str)
    return payload


def phase_shorts(blob: dict, out: str) -> dict:
    """The mirror-image pullback short (rulebook section D-SHORT), reported apart.

    Kept out of the headline result for two stated reasons: the speaker's own
    conclusion that his shorts carried worse reward-for-risk and should be fewer,
    and the fact that Indian cash equities cannot be held short overnight at all.
    """
    payload = {}
    cfgs = {
        "short_literal": variant(Config(), "short_literal", direction="short",
                                 max_holding_bars=3),
        "short_ceiling_only": variant(Config(), "short_ceiling_only", direction="short",
                                      use_adr_stop_cap=False, max_holding_bars=3),
    }
    for name, cfg in cfgs.items():
        res = portfolio(blob, cfg)
        sig = signals(blob, cfg)
        payload[name] = {"portfolio": mt.summarize(res), "signal_level": signal_stats(sig, name)}
        print(f"[{name}] trades={payload[name]['portfolio']['trades']} "
              f"return={payload[name]['portfolio']['total_return_pct']:.1f}%", flush=True)
    with open(os.path.join(out, "shorts.json"), "w") as fh:
        json.dump(payload, fh, indent=2, default=str)
    return payload


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--cache", required=True)
    ap.add_argument("--phase", default="all")
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    blob = build_cache(args.db, args.cache)
    todo = ["original", "shorts", "robustness", "ablation"] if args.phase == "all" else [args.phase]
    for ph in todo:
        t0 = time.time()
        print(f"\n===== phase: {ph} =====", flush=True)
        {"original": phase_original, "robustness": phase_robustness,
         "ablation": phase_ablation, "shorts": phase_shorts}[ph](blob, args.out)
        print(f"----- {ph} done in {time.time()-t0:.1f}s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
