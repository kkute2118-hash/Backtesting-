"""Crypto trading routes - retest entry + dynamic leverage paper trading reports."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi import APIRouter, HTTPException

router = APIRouter()

REPORTS_DIR = Path("/data/reports")


@router.get("/crypto/trend-report")
async def get_trend_report():
    """Get the live 4h trend strategy paper trading report (HTML)."""
    report_file = REPORTS_DIR / "trend.html"
    if not report_file.exists():
        raise HTTPException(status_code=404, detail="Trend report not found. Job may not have run yet.")
    return {"html": report_file.read_text(), "path": str(report_file)}


@router.get("/crypto/trend-state")
async def get_trend_state():
    """Get the live trading state (JSON) - all positions and closed trades."""
    state_file = REPORTS_DIR / "trend-state.json"
    if not state_file.exists():
        raise HTTPException(status_code=404, detail="Trend state not found. Job may not have run yet.")
    try:
        return json.loads(state_file.read_text())
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read state: {str(e)}")


@router.get("/crypto/trend-latest")
async def get_trend_latest():
    """Get latest snapshot - equity, trades, recent events."""
    latest_file = REPORTS_DIR / "trend-latest.json"
    if not latest_file.exists():
        raise HTTPException(status_code=404, detail="Latest report not found. Job may not have run yet.")
    try:
        return json.loads(latest_file.read_text())
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read latest: {str(e)}")


@router.get("/crypto/trades")
async def get_closed_trades():
    """Get list of all closed trades with performance metrics."""
    state_file = REPORTS_DIR / "trend-state.json"
    if not state_file.exists():
        raise HTTPException(status_code=404, detail="No trades yet")
    try:
        state = json.loads(state_file.read_text())
        all_trades = []
        for market_state in state.get("markets", {}).values():
            all_trades.extend(market_state.get("closed", []))
        # Sort by exit time, newest first
        all_trades.sort(key=lambda t: t.get("exit_time", ""), reverse=True)
        return {"trades": all_trades, "count": len(all_trades)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get trades: {str(e)}")


@router.get("/crypto/equity")
async def get_equity_curve():
    """Get equity growth curve from closed trades."""
    state_file = REPORTS_DIR / "trend-state.json"
    if not state_file.exists():
        raise HTTPException(status_code=404, detail="No equity data yet")
    try:
        state = json.loads(state_file.read_text())
        all_trades = []
        for market_state in state.get("markets", {}).values():
            all_trades.extend(market_state.get("closed", []))

        # Calculate equity curve
        START_EQUITY = 10_000.0
        equity = START_EQUITY
        curve = [{"trade_num": 0, "equity": equity, "timestamp": state.get("start")}]

        all_trades_sorted = sorted(all_trades, key=lambda t: t.get("exit_time", ""))
        for i, trade in enumerate(all_trades_sorted, 1):
            if "ret" in trade:
                equity += equity * trade.get("size_x", 1.0) * trade.get("ret", 0)
            else:
                equity += equity * 0.01 * trade.get("r", 0)
            curve.append({"trade_num": i, "equity": round(equity, 2), "timestamp": trade.get("exit_time")})

        return {"curve": curve, "final_equity": round(equity, 2), "return_multiple": round(equity / START_EQUITY, 2)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to calculate equity: {str(e)}")


@router.get("/crypto/stats")
async def get_trading_stats():
    """Get summary statistics - win rate, avg R, drawdown, etc."""
    latest_file = REPORTS_DIR / "trend-latest.json"
    if not latest_file.exists():
        raise HTTPException(status_code=404, detail="No stats yet")
    try:
        latest = json.loads(latest_file.read_text())
        trades = latest.get("trades", 0)
        total_r = latest.get("total_r", 0)
        equity = latest.get("equity", 10_000)

        return {
            "equity": equity,
            "trades": trades,
            "total_r": total_r,
            "avg_r": round(total_r / trades, 2) if trades > 0 else 0,
            "return_multiple": round(equity / 10_000, 2),
            "paper_start": latest.get("paper_start"),
            "updated": latest.get("updated"),
            "markets": latest.get("markets", {}),
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get stats: {str(e)}")
