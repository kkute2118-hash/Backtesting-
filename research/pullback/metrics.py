"""Performance, risk, regime and robustness statistics for a backtest result."""

from __future__ import annotations

import numpy as np
import pandas as pd


def summarize(res: dict) -> dict:
    t, eq = res["trades"], res["equity"]
    cap = res["capital"]
    out = {
        "label": res["config"].label,
        "start": str(eq.index[0].date()) if len(eq) else None,
        "end": str(eq.index[-1].date()) if len(eq) else None,
        "starting_capital": cap,
        "ending_capital": float(eq["equity"].iloc[-1]) if len(eq) else cap,
        "trades": int(len(t)),
    }
    out["net_profit"] = out["ending_capital"] - cap
    out["total_return_pct"] = 100.0 * out["net_profit"] / cap
    if len(eq) > 1:
        years = (eq.index[-1] - eq.index[0]).days / 365.25
        out["years"] = round(years, 2)
        out["cagr_pct"] = 100.0 * ((out["ending_capital"] / cap) ** (1 / years) - 1) if years > 0 else np.nan
    if not len(t):
        out.update({k: np.nan for k in
                    ("win_rate_pct", "avg_win_r", "avg_loss_r", "profit_factor",
                     "expectancy_r", "total_r", "max_drawdown_pct")})
        return out

    r = t["r_multiple"]
    wins, losses = t[t["pnl"] > 0], t[t["pnl"] <= 0]
    out["winning_trades"], out["losing_trades"] = len(wins), len(losses)
    out["win_rate_pct"] = 100.0 * len(wins) / len(t)
    out["avg_win_r"] = float(wins["r_multiple"].mean()) if len(wins) else 0.0
    out["avg_loss_r"] = float(losses["r_multiple"].mean()) if len(losses) else 0.0
    out["avg_win_pct"] = float(wins["pnl_pct"].mean()) if len(wins) else 0.0
    out["avg_loss_pct"] = float(losses["pnl_pct"].mean()) if len(losses) else 0.0
    gp, gl = wins["pnl"].sum(), -losses["pnl"].sum()
    out["gross_profit"], out["gross_loss"] = float(gp), float(gl)
    out["profit_factor"] = float(gp / gl) if gl > 0 else np.inf
    out["expectancy_r"] = float(r.mean())
    out["expectancy_pct"] = float(t["pnl_pct"].mean())
    out["total_r"] = float(r.sum())
    out["r_std"] = float(r.std(ddof=1)) if len(r) > 1 else np.nan
    out["t_stat"] = float(r.mean() / (r.std(ddof=1) / np.sqrt(len(r)))) if len(r) > 1 and r.std(ddof=1) > 0 else np.nan
    out["largest_win_pnl"] = float(t["pnl"].max())
    out["largest_loss_pnl"] = float(t["pnl"].min())
    out["largest_win_r"] = float(r.max())
    out["largest_loss_r"] = float(r.min())
    out["avg_holding_bars"] = float(t["holding_bars"].mean())
    out["median_holding_bars"] = float(t["holding_bars"].median())
    out["avg_stop_pct"] = float(t["stop_pct"].mean())

    streak_w = streak_l = best_w = best_l = 0
    for pnl in t.sort_values("entry_date")["pnl"]:
        if pnl > 0:
            streak_w, streak_l = streak_w + 1, 0
        else:
            streak_l, streak_w = streak_l + 1, 0
        best_w, best_l = max(best_w, streak_w), max(best_l, streak_l)
    out["longest_win_streak"], out["longest_loss_streak"] = best_w, best_l

    curve = eq["equity"]
    peak = curve.cummax()
    dd = curve / peak - 1.0
    out["max_drawdown_pct"] = float(dd.min() * 100.0)
    out["max_drawdown_value"] = float((curve - peak).min())
    underwater = dd < -1e-9
    longest, cur = 0, 0
    for flag in underwater:
        cur = cur + 1 if flag else 0
        longest = max(longest, cur)
    out["max_drawdown_days"] = int(longest)
    out["return_over_maxdd"] = (out["total_return_pct"] / abs(out["max_drawdown_pct"])
                                if out["max_drawdown_pct"] else np.nan)
    daily = curve.pct_change().dropna()
    if len(daily) > 2 and daily.std() > 0:
        out["sharpe"] = float(daily.mean() / daily.std() * np.sqrt(252))
        down = daily[daily < 0]
        out["sortino"] = float(daily.mean() / down.std() * np.sqrt(252)) if len(down) > 1 and down.std() > 0 else np.nan
        out["ann_vol_pct"] = float(daily.std() * np.sqrt(252) * 100)
    out["exposure_avg_positions"] = float(eq["positions"].mean())
    out["pct_days_invested"] = float(100.0 * (eq["positions"] > 0).mean())
    out["exit_reasons"] = t["exit_reason"].value_counts().to_dict()
    return out


def by_period(res: dict, freq: str = "YE") -> pd.DataFrame:
    t, eq = res["trades"], res["equity"]
    if not len(t):
        return pd.DataFrame()
    grp = t.set_index("entry_date").groupby(pd.Grouper(freq=freq))
    rows = grp.agg(
        trades=("r_multiple", "size"),
        total_r=("r_multiple", "sum"),
        avg_r=("r_multiple", "mean"),
        win_rate=("pnl", lambda s: 100.0 * (s > 0).mean()),
        pnl=("pnl", "sum"),
    )
    eqp = eq["equity"].groupby(pd.Grouper(freq=freq)).agg(["first", "last"])
    rows["equity_return_pct"] = 100.0 * (eqp["last"] / eqp["first"] - 1.0)
    return rows.dropna(how="all")


def concentration(res: dict) -> dict:
    t = res["trades"]
    if not len(t):
        return {}
    r = t["r_multiple"].sort_values(ascending=False)
    total = r.sum()
    out = {"total_r": float(total)}
    for k in (1, 5, 10):
        if len(r) > k:
            out[f"total_r_ex_top{k}"] = float(total - r.head(k).sum())
            out[f"share_of_profit_top{k}_pct"] = float(100.0 * r.head(k).sum() / total) if total else np.nan
    pos = r[r > 0]
    out["winners_needed_for_half_profit"] = int(
        (pos.cumsum() <= pos.sum() / 2).sum() + 1
    ) if len(pos) else 0
    out["n_winners"] = int(len(pos))
    return out


def regime_table(res: dict, market: pd.DataFrame) -> pd.DataFrame:
    """Split trades by the market state on the *entry* date (known at entry)."""
    t = res["trades"]
    if not len(t):
        return pd.DataFrame()
    m = market.copy()
    trend = np.where(m["level"] > m["ema50"], "index_above_50ema", "index_below_50ema")
    vol = m["vol21"]
    vol_med = vol.median()
    volband = np.where(vol > vol_med, "high_vol", "low_vol")
    tags = pd.DataFrame({"trend": trend, "vol": volband}, index=m.index)
    j = t.join(tags, on="entry_date")
    rows = []
    for key, col in (("trend", "trend"), ("vol", "vol")):
        for val, g in j.groupby(col):
            rows.append(
                {
                    "dimension": key, "regime": val, "trades": len(g),
                    "avg_r": g["r_multiple"].mean(), "total_r": g["r_multiple"].sum(),
                    "win_rate": 100.0 * (g["pnl"] > 0).mean(),
                }
            )
    return pd.DataFrame(rows)
