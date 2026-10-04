#!/usr/bin/env python3
"""Analyze patterns in 4h trend strategy trades to find when it works best.

Identifies: winning vs losing periods, best symbols, time-of-day effects,
volatility regimes, and other conditions that correlate with better performance.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
import trend_4h_study as t4s

SYMBOLS = t4s.SYMBOLS
SPLIT = pd.Timestamp("2025-01-01", tz="UTC")


def analyze_pattern_space(trades: pd.DataFrame) -> dict:
    """Find all patterns in the trade space."""
    if trades.empty:
        return {}

    patterns = {}

    # 1. Performance by symbol
    patterns["by_symbol"] = {}
    for sym in SYMBOLS:
        sym_trades = trades[trades.symbol == sym]
        if not sym_trades.empty:
            patterns["by_symbol"][sym] = {
                "count": len(sym_trades),
                "win_rate": (sym_trades.r > 0).mean(),
                "avg_r": sym_trades.r.mean(),
                "avg_r_win": sym_trades[sym_trades.r > 0].r.mean() if (sym_trades.r > 0).any() else 0,
                "avg_r_loss": sym_trades[sym_trades.r <= 0].r.mean() if (sym_trades.r <= 0).any() else 0,
                "total_r": sym_trades.r.sum(),
                "median_r": sym_trades.r.median(),
            }

    # 2. Performance by year
    trades["year"] = trades.entry_time.dt.year
    patterns["by_year"] = {}
    for year in sorted(trades.year.unique()):
        year_trades = trades[trades.year == year]
        patterns["by_year"][year] = {
            "count": len(year_trades),
            "win_rate": (year_trades.r > 0).mean(),
            "avg_r": year_trades.r.mean(),
            "total_r": year_trades.r.sum(),
            "best_trade": year_trades.r.max(),
            "worst_trade": year_trades.r.min(),
        }

    # 3. Performance by month
    trades["month"] = trades.entry_time.dt.month
    patterns["by_month"] = {}
    month_names = {1: "Jan", 2: "Feb", 3: "Mar", 4: "Apr", 5: "May", 6: "Jun",
                   7: "Jul", 8: "Aug", 9: "Sep", 10: "Oct", 11: "Nov", 12: "Dec"}
    for month in range(1, 13):
        month_trades = trades[trades.month == month]
        if not month_trades.empty:
            patterns["by_month"][f"{month:02d}_{month_names[month]}"] = {
                "count": len(month_trades),
                "win_rate": (month_trades.r > 0).mean(),
                "avg_r": month_trades.r.mean(),
                "total_r": month_trades.r.sum(),
            }

    # 4. Performance by entry mode (if available)
    if "mode" in trades.columns:
        patterns["by_entry_mode"] = {}
        for mode in trades.mode.unique():
            mode_trades = trades[trades.mode == mode]
            patterns["by_entry_mode"][mode] = {
                "count": len(mode_trades),
                "win_rate": (mode_trades.r > 0).mean(),
                "avg_r": mode_trades.r.mean(),
                "total_r": mode_trades.r.sum(),
            }

    # 5. Performance by hour of entry
    trades["hour"] = trades.entry_time.dt.hour
    patterns["by_hour"] = {}
    for hour in range(24):
        hour_trades = trades[trades.hour == hour]
        if not hour_trades.empty:
            patterns["by_hour"][f"{hour:02d}:00"] = {
                "count": len(hour_trades),
                "win_rate": (hour_trades.r > 0).mean(),
                "avg_r": hour_trades.r.mean(),
                "total_r": hour_trades.r.sum(),
            }

    # 6. Streak analysis - winning and losing streaks
    trades_sorted = trades.sort_values("entry_time").reset_index(drop=True)
    r_values = trades_sorted.r.values

    # Find streaks
    streaks = []
    current_streak = {"type": "win" if r_values[0] > 0 else "loss", "count": 1, "r_sum": r_values[0]}

    for i in range(1, len(r_values)):
        is_win = r_values[i] > 0
        if (is_win and current_streak["type"] == "win") or (not is_win and current_streak["type"] == "loss"):
            current_streak["count"] += 1
            current_streak["r_sum"] += r_values[i]
        else:
            streaks.append(current_streak.copy())
            current_streak = {"type": "win" if is_win else "loss", "count": 1, "r_sum": r_values[i]}
    streaks.append(current_streak)

    win_streaks = [s for s in streaks if s["type"] == "win"]
    loss_streaks = [s for s in streaks if s["type"] == "loss"]

    patterns["streaks"] = {
        "max_win_streak": max([s["count"] for s in win_streaks]) if win_streaks else 0,
        "max_loss_streak": max([s["count"] for s in loss_streaks]) if loss_streaks else 0,
        "avg_win_streak": sum(s["count"] for s in win_streaks) / len(win_streaks) if win_streaks else 0,
        "avg_loss_streak": sum(s["count"] for s in loss_streaks) / len(loss_streaks) if loss_streaks else 0,
        "total_win_streaks": len(win_streaks),
        "total_loss_streaks": len(loss_streaks),
        "worst_streak_r": min(s["r_sum"] for s in loss_streaks) if loss_streaks else 0,
    }

    # 7. Risk/reward by entry mode
    if "n_in" in trades.columns and "cost_r" in trades.columns:
        patterns["by_n_in"] = {}
        for n_in in sorted(trades.n_in.unique()):
            n_trades = trades[trades.n_in == n_in]
            patterns["by_n_in"][n_in] = {
                "count": len(n_trades),
                "win_rate": (n_trades.r > 0).mean(),
                "avg_r": n_trades.r.mean(),
                "avg_cost_r": n_trades.cost_r.mean(),
                "total_r": n_trades.r.sum(),
            }

    # 8. Trade duration analysis (if exit_time available)
    if "exit_time" in trades.columns:
        trades["duration_hours"] = (trades.exit_time - trades.entry_time).dt.total_seconds() / 3600
        patterns["duration"] = {
            "avg_hours": trades.duration_hours.mean(),
            "min_hours": trades.duration_hours.min(),
            "max_hours": trades.duration_hours.max(),
            "median_hours": trades.duration_hours.median(),
        }

        # Win/loss by duration quintiles
        trades["duration_quintile"] = pd.qcut(trades.duration_hours, q=5, labels=False, duplicates="drop")
        patterns["by_duration_quintile"] = {}
        for q in sorted(trades.duration_quintile.unique()):
            q_trades = trades[trades.duration_quintile == q]
            avg_dur = q_trades.duration_hours.mean()
            patterns["by_duration_quintile"][f"q{int(q)}_~{avg_dur:.1f}h"] = {
                "count": len(q_trades),
                "win_rate": (q_trades.r > 0).mean(),
                "avg_r": q_trades.r.mean(),
                "total_r": q_trades.r.sum(),
            }

    # 9. Risk % analysis
    if "risk_pct" in trades.columns:
        trades["risk_quintile"] = pd.qcut(trades.risk_pct, q=5, labels=False, duplicates="drop")
        patterns["by_risk_quintile"] = {}
        for q in sorted(trades.risk_quintile.unique()):
            q_trades = trades[trades.risk_quintile == q]
            avg_risk = q_trades.risk_pct.mean()
            patterns["by_risk_quintile"][f"risk_~{avg_risk:.1f}%"] = {
                "count": len(q_trades),
                "win_rate": (q_trades.r > 0).mean(),
                "avg_r": q_trades.r.mean(),
                "total_r": q_trades.r.sum(),
            }

    return patterns


def print_patterns(patterns: dict) -> None:
    """Pretty-print pattern analysis."""
    if not patterns:
        print("No trades to analyze")
        return

    print("\n" + "=" * 80)
    print("PATTERN ANALYSIS: When does the 4H trend strategy work best?")
    print("=" * 80)

    # By symbol
    if "by_symbol" in patterns:
        print("\n--- PERFORMANCE BY SYMBOL ---")
        for sym in SYMBOLS:
            if sym in patterns["by_symbol"]:
                p = patterns["by_symbol"][sym]
                print(f"{sym:10s} | {p['count']:3d} trades | win {p['win_rate']:5.1%} | "
                      f"avg {p['avg_r']:+.2f}R | total {p['total_r']:+.0f}R")

    # By year
    if "by_year" in patterns:
        print("\n--- PERFORMANCE BY YEAR ---")
        for year in sorted(patterns["by_year"].keys()):
            p = patterns["by_year"][year]
            print(f"{year} | {p['count']:3d} trades | win {p['win_rate']:5.1%} | "
                  f"avg {p['avg_r']:+.2f}R | total {p['total_r']:+.0f}R | "
                  f"range {p['worst_trade']:+.2f}R to {p['best_trade']:+.2f}R")

    # By month
    if "by_month" in patterns:
        print("\n--- PERFORMANCE BY MONTH (across all years) ---")
        months_sorted = sorted(patterns["by_month"].items(),
                              key=lambda x: float(x[0].split("_")[0]))
        for month_key, p in months_sorted:
            month_name = month_key.split("_")[1]
            print(f"{month_name:3s} | {p['count']:3d} trades | win {p['win_rate']:5.1%} | "
                  f"avg {p['avg_r']:+.2f}R | total {p['total_r']:+.0f}R")

    # By hour
    if "by_hour" in patterns:
        print("\n--- PERFORMANCE BY HOUR OF ENTRY (UTC) ---")
        hours_sorted = sorted(patterns["by_hour"].items())
        for hour_key, p in hours_sorted:
            if p["count"] >= 2:  # Only show hours with at least 2 trades
                print(f"{hour_key} | {p['count']:3d} trades | win {p['win_rate']:5.1%} | "
                      f"avg {p['avg_r']:+.2f}R | total {p['total_r']:+.0f}R")

    # Streaks
    if "streaks" in patterns:
        print("\n--- STREAK ANALYSIS ---")
        s = patterns["streaks"]
        print(f"Max winning streak:     {int(s['max_win_streak'])} trades")
        print(f"Max losing streak:      {int(s['max_loss_streak'])} trades")
        print(f"Avg winning streak:     {s['avg_win_streak']:.1f} trades")
        print(f"Avg losing streak:      {s['avg_loss_streak']:.1f} trades")
        print(f"Total winning streaks:  {int(s['total_win_streaks'])}")
        print(f"Total losing streaks:   {int(s['total_loss_streaks'])}")
        print(f"Worst streak drawdown:  {s['worst_streak_r']:+.1f}R")

    # By risk quintile
    if "by_risk_quintile" in patterns:
        print("\n--- PERFORMANCE BY TRADE RISK SIZE ---")
        for risk_key, p in sorted(patterns["by_risk_quintile"].items()):
            print(f"{risk_key:15s} | {p['count']:3d} trades | win {p['win_rate']:5.1%} | "
                  f"avg {p['avg_r']:+.2f}R | total {p['total_r']:+.0f}R")

    # By duration
    if "by_duration_quintile" in patterns:
        print("\n--- PERFORMANCE BY TRADE DURATION ---")
        for dur_key, p in sorted(patterns["by_duration_quintile"].items()):
            print(f"{dur_key:15s} | {p['count']:3d} trades | win {p['win_rate']:5.1%} | "
                  f"avg {p['avg_r']:+.2f}R | total {p['total_r']:+.0f}R")

    # By entry mode
    if "by_entry_mode" in patterns:
        print("\n--- PERFORMANCE BY ENTRY MODE ---")
        for mode, p in sorted(patterns["by_entry_mode"].items()):
            print(f"{mode:10s} | {p['count']:3d} trades | win {p['win_rate']:5.1%} | "
                  f"avg {p['avg_r']:+.2f}R | total {p['total_r']:+.0f}R")

    # By N_in parameter
    if "by_n_in" in patterns:
        print("\n--- PERFORMANCE BY N_IN PARAMETER ---")
        for n_in, p in sorted(patterns["by_n_in"].items()):
            print(f"N_in={n_in:2d} | {p['count']:3d} trades | win {p['win_rate']:5.1%} | "
                  f"avg {p['avg_r']:+.2f}R | total {p['total_r']:+.0f}R")

    print("\n" + "=" * 80)


def identify_best_conditions(patterns: dict) -> str:
    """Identify the best conditions for trading based on patterns."""
    recommendations = []

    if "by_symbol" in patterns:
        # Best symbol
        symbols_by_avg_r = sorted(patterns["by_symbol"].items(),
                                  key=lambda x: x[1]["avg_r"], reverse=True)
        best_sym = symbols_by_avg_r[0][0]
        best_sym_r = symbols_by_avg_r[0][1]["avg_r"]
        recommendations.append(f"Best symbol: {best_sym} (avg {best_sym_r:+.2f}R)")

    if "by_year" in patterns:
        years_by_total_r = sorted(patterns["by_year"].items(),
                                  key=lambda x: x[1]["total_r"], reverse=True)
        best_year = years_by_total_r[0][0]
        best_year_r = years_by_total_r[0][1]["total_r"]
        recommendations.append(f"Best year: {best_year} (total {best_year_r:+.0f}R)")

    if "by_month" in patterns:
        months_by_avg_r = sorted(patterns["by_month"].items(),
                                 key=lambda x: x[1]["avg_r"], reverse=True)
        best_month = months_by_avg_r[0][0].split("_")[1]
        best_month_r = months_by_avg_r[0][1]["avg_r"]
        recommendations.append(f"Best month: {best_month} (avg {best_month_r:+.2f}R)")

    if "by_hour" in patterns:
        hours_with_trades = {k: v for k, v in patterns["by_hour"].items() if v["count"] >= 2}
        if hours_with_trades:
            hours_by_avg_r = sorted(hours_with_trades.items(),
                                   key=lambda x: x[1]["avg_r"], reverse=True)
            best_hour = hours_by_avg_r[0][0]
            best_hour_r = hours_by_avg_r[0][1]["avg_r"]
            recommendations.append(f"Best trading hour (UTC): {best_hour} (avg {best_hour_r:+.2f}R)")

    if "streaks" in patterns:
        max_loss = patterns["streaks"]["max_loss_streak"]
        recommendations.append(f"Max drawdown risk: {int(max_loss)}-trade losing streak")

    return "\n".join(recommendations)


def main():
    if len(sys.argv) < 2:
        print("Usage: python trade_pattern_analysis.py DATA_DIR [OUT_PREFIX]")
        sys.exit(1)

    data = Path(sys.argv[1])
    prefix = sys.argv[2] if len(sys.argv) > 2 else "analysis"

    # Run backtest
    rows = []
    for sym in SYMBOLS:
        try:
            m15, h4 = t4s.load(data, sym)
            for n_in, n_out in ((55, 20), (20, 10)):
                for mode in ("next", "retest", "confirm"):
                    rows += t4s.run(sym, m15, h4, n_in, n_out, mode)
            print(f"{sym}: {len([r for r in rows if r['symbol'] == sym])} trades", file=__import__("sys").stderr)
        except Exception as e:
            print(f"{sym}: ERROR - {e}", file=__import__("sys").stderr)

    if not rows:
        print("No trade data generated. Check if data files exist in:", data)
        sys.exit(1)

    trades = pd.DataFrame(rows)
    trades["test"] = trades.entry_time >= SPLIT

    # Analyze patterns
    patterns = analyze_pattern_space(trades)
    print_patterns(patterns)

    # Get recommendations
    print("\n" + "=" * 80)
    print("RECOMMENDATIONS FOR BETTER ENTRY TIMING")
    print("=" * 80)
    print(identify_best_conditions(patterns))
    print("=" * 80)

    # Save to CSV for further analysis
    trades.to_csv(f"{prefix}_trades.csv", index=False)
    print(f"\nTrade data saved to: {prefix}_trades.csv")

    # Save patterns as JSON for visualization
    import json
    with open(f"{prefix}_patterns.json", "w") as f:
        # Convert numpy types to native Python types for JSON serialization
        def convert(obj):
            if isinstance(obj, (np.integer, np.floating)):
                return float(obj)
            raise TypeError
        json.dump(patterns, f, indent=2, default=convert)
    print(f"Pattern analysis saved to: {prefix}_patterns.json")


if __name__ == "__main__":
    main()
