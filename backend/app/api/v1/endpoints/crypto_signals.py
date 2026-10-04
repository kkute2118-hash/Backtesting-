"""Real-time crypto trading signals and WebSocket streaming."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

router = APIRouter()

REPORTS_DIR = Path("/data/reports")


class SignalManager:
    """Manages active WebSocket connections and broadcasts signals."""

    def __init__(self):
        self.active_connections: list[WebSocket] = []
        self.last_alert_time: dict[str, float] = {}

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, message: dict[str, Any]):
        """Broadcast message to all connected clients."""
        for connection in self.active_connections:
            try:
                await connection.send_json(message)
            except Exception:
                pass


signal_manager = SignalManager()


@router.websocket("/crypto/signals/ws")
async def websocket_signals(websocket: WebSocket):
    """WebSocket endpoint for real-time trading signals.

    Streams:
    - Live market updates every second
    - Entry/exit/retest signals
    - Price ticks for chart updates
    """
    await signal_manager.connect(websocket)
    try:
        while True:
            # Receive any client messages (heartbeat, etc)
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=30.0)
                # Client sent something, acknowledge
                await websocket.send_json({"type": "pong"})
            except asyncio.TimeoutError:
                # No message from client in 30s, send a ping
                await websocket.send_json({"type": "ping"})
                await asyncio.sleep(1)
                continue

            # Read latest market state
            state_file = REPORTS_DIR / "trend-latest.json"
            if state_file.exists():
                try:
                    state = json.loads(state_file.read_text())
                    await websocket.send_json(
                        {
                            "type": "market_update",
                            "timestamp": datetime.now().isoformat(),
                            "markets": state.get("markets", {}),
                            "equity": state.get("equity"),
                            "trades": state.get("trades"),
                        }
                    )
                except Exception as e:
                    await websocket.send_json({"type": "error", "message": str(e)})

            await asyncio.sleep(2)  # Send updates every 2 seconds

    except WebSocketDisconnect:
        signal_manager.disconnect(websocket)


@router.get("/crypto/signals")
async def get_trading_signals():
    """Get current trading signals for all 9 pairs.

    Returns market state, entry/exit levels, and recent signal history.
    """
    latest_file = REPORTS_DIR / "trend-latest.json"
    if not latest_file.exists():
        raise HTTPException(status_code=404, detail="No signals yet")

    try:
        latest = json.loads(latest_file.read_text())
        state_file = REPORTS_DIR / "trend-state.json"
        state = json.loads(state_file.read_text()) if state_file.exists() else {}

        return {
            "timestamp": latest.get("updated"),
            "markets": latest.get("markets", {}),
            "equity": latest.get("equity"),
            "trades": latest.get("trades"),
            "recent_trades": [
                trade
                for market in state.get("markets", {}).values()
                for trade in market.get("closed", [])
            ][-5:],  # Last 5 trades
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get signals: {str(e)}")


@router.get("/crypto/signals/{symbol}")
async def get_symbol_signals(symbol: str):
    """Get signals for a specific trading symbol.

    Includes entry/exit/stop-loss levels and position status.
    """
    latest_file = REPORTS_DIR / "trend-latest.json"
    if not latest_file.exists():
        raise HTTPException(status_code=404, detail="No data yet")

    try:
        latest = json.loads(latest_file.read_text())
        market = latest.get("markets", {}).get(symbol)

        if not market:
            raise HTTPException(status_code=404, detail=f"No data for {symbol}")

        state_file = REPORTS_DIR / "trend-state.json"
        trades = []
        if state_file.exists():
            state = json.loads(state_file.read_text())
            market_state = state.get("markets", {}).get(symbol, {})
            trades = market_state.get("closed", [])

        return {
            "symbol": symbol,
            "status": market.get("status"),
            "entry": market.get("entry"),
            "leverage": market.get("leverage"),
            "timestamp": latest.get("updated"),
            "recent_trades": trades[-3:],  # Last 3 trades
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get symbol signals: {str(e)}")
