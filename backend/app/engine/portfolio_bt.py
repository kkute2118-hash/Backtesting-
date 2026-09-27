"""Portfolio-level backtest for the scanner's strategies, with Indian costs.

Per-trade statistics answer "is this setup any good"; they do not answer "what
would my account have done". Strategies compete for the same money, slots fill
up during a breadth surge, whole shares round positions down, and costs are
charged on every fill. This module replays that.

    trades = collect_trades(data, start, end)          # S4, S5, S6 on their own exits
    result = run_portfolio(trades, closes, capital=100_000,
                           buckets={"S4_SEPA": .34, "S5_POCKETPIVOT": .33, "S6_BREAKOUT": .33})

Trade generation reuses the engine's own replays, so the entries and exits are
the scanner's: S6 via run_s6_backtest(), S5 via run_s5_pocket_pivot_backtest(),
S4 via run_raw_signal_backtest() (fixed -7% stop, 3R target). S4 and S5 are
passed through the live entry filter as it stood on each signal day
(historical_entry_verdict()).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, asdict

import numpy as np
import pandas as pd

from app.engine import core


# ------------------------------------------------------------------ costs ---
@dataclass(frozen=True)
class IndianDeliveryCosts:
    """Charges on a delivery (CNC) equity trade on NSE.

    Rates as published for FY2025-26; they change, so every one is a field.
    `slippage_pct` is the price you lose to the spread and impact on each fill;
    the stop is already filled at the open when a stock gaps through it, so
    slippage is on top of that, not instead of it.
    """
    brokerage_per_order: float = 0.0        # Dhan: zero brokerage on delivery
    stt_pct: float = 0.1                    # both buy and sell, on turnover
    exchange_txn_pct: float = 0.00297       # NSE transaction charge, both sides
    sebi_per_crore: float = 10.0            # Rs 10 per crore, both sides
    stamp_buy_pct: float = 0.015            # buy side only
    gst_pct: float = 18.0                   # on brokerage + exchange + SEBI
    dp_charge_per_sell: float = 12.5        # depository charge per scrip per sell day (+GST)
    slippage_pct: float = 0.10              # each fill

    def buy(self, value: float) -> float:
        return self._common(value) + value * self.stamp_buy_pct / 100

    def sell(self, value: float) -> float:
        return self._common(value) + self.dp_charge_per_sell * (1 + self.gst_pct / 100)

    def _common(self, value: float) -> float:
        exch = value * self.exchange_txn_pct / 100
        sebi = value * self.sebi_per_crore / 1e7
        gst = (self.brokerage_per_order + exch + sebi) * self.gst_pct / 100
        return self.brokerage_per_order + value * self.stt_pct / 100 + exch + sebi + gst

    def round_trip_pct(self, value: float) -> float:
        """Total cost of buying and selling `value` rupees, as % of it, slippage included."""
        return (self.buy(value) + self.sell(value)) / value * 100 + 2 * self.slippage_pct


NO_COSTS = IndianDeliveryCosts(0, 0, 0, 0, 0, 0, 0, 0)


# ----------------------------------------------------------------- trades ---
TRADE_COLUMNS = ["strategy", "symbol", "signal_date", "entry_date", "entry", "stop",
                 "exit_date", "exit", "exit_reason", "rank_key"]


def _norm(sym):
    return str(sym).upper().replace(".NS", "")


def collect_trades(data, start, end, strategies=("S4_SEPA", "S5_POCKETPIVOT", "S6_BREAKOUT"),
                   eligible=None, apply_entry_filter=True):
    """Every trade the scanner's strategies would have taken, one row each.

    `data` is {ticker: daily frame}. `eligible` is an optional point-in-time
    universe (core.point_in_time_universe()). Returns TRADE_COLUMNS.
    """
    long_data = {k: v for k, v in data.items() if v is not None and len(v) >= 260}
    frames = []

    def is_eligible(sym, d):
        if eligible is None:
            return True
        try:
            return bool(eligible.at[pd.Timestamp(d), _norm(sym)])
        except KeyError:
            return False

    if "S6_BREAKOUT" in strategies:
        t = core.run_s6_backtest(long_data, start, end, eligible=eligible)
        if len(t):
            frames.append(pd.DataFrame({
                "strategy": "S6_BREAKOUT", "symbol": t["Ticker"], "signal_date": t["Signal Date"],
                "entry_date": t["Entry Date"], "entry": t["Entry"], "stop": t["Initial SL"],
                "exit_date": t["Exit Date"], "exit": t["Exit"], "exit_reason": t["Exit Reason"],
                "rank_key": t["ATR %"]}))

    if "S5_POCKETPIVOT" in strategies:
        t = core.run_s5_pocket_pivot_backtest(long_data, start, end)["trades"]
        if len(t):
            keep = [is_eligible(s, d) and (not apply_entry_filter or
                                          core.historical_entry_verdict(5, long_data[s], d)[0])
                    for s, d in zip(t["Ticker"], t["Date"])]
            t = t[keep]
            frames.append(pd.DataFrame({
                "strategy": "S5_POCKETPIVOT", "symbol": t["Ticker"].map(_norm), "signal_date": t["Date"],
                "entry_date": t["Entry Date"], "entry": t["Entry"], "stop": t["Initial SL"],
                "exit_date": t["Exit Date"], "exit": t["Exit"], "exit_reason": t["Exit Reason"],
                "rank_key": t["atr_pct"]}))

    if "S4_SEPA" in strategies:
        t = core.run_raw_signal_backtest(long_data, [4], start, end)
        if len(t):
            ranks = core.sector_rank_history() if apply_entry_filter else None
            lookup = core.sector_map(source="index") if apply_entry_filter else None
            keep = [is_eligible(s, d) and (not apply_entry_filter or core.historical_entry_verdict(
                        4, long_data[s], d, sector_ranks=ranks, sector_lookup=lookup, ticker=s)[0])
                    for s, d in zip(t["ticker"], t["signal_date"])]
            t = t[keep]
            frames.append(pd.DataFrame({
                "strategy": "S4_SEPA", "symbol": t["ticker"].map(_norm), "signal_date": t["signal_date"],
                "entry_date": t["entry_date"], "entry": t["entry"], "stop": t["stop"],
                "exit_date": t["exit_date"], "exit": t["exit_price"], "exit_reason": t["outcome"],
                "rank_key": t["atr_pct"]}))

    if not frames:
        return pd.DataFrame(columns=TRADE_COLUMNS)
    out = pd.concat(frames, ignore_index=True)
    for c in ("signal_date", "entry_date", "exit_date"):
        out[c] = pd.to_datetime(out[c])
    out = out.dropna(subset=["entry", "stop", "exit", "entry_date", "exit_date"])
    out = out[(out.entry > 0) & (out.stop < out.entry)]
    return out[TRADE_COLUMNS].sort_values(["entry_date", "strategy"]).reset_index(drop=True)


# -------------------------------------------------------------- portfolio ---
@dataclass
class PortfolioResult:
    equity: pd.Series                       # total account value per day
    bucket_equity: pd.DataFrame             # per strategy bucket (shared pool: one column)
    fills: pd.DataFrame                     # every trade taken, with rupee P&L and costs
    skipped: dict = field(default_factory=dict)
    stats: dict = field(default_factory=dict)


def _stats(equity, fills, capital):
    if equity.empty:
        return {}
    days = max(1, (equity.index[-1] - equity.index[0]).days)
    final = float(equity.iloc[-1])
    cagr = (final / capital) ** (365.25 / days) - 1 if final > 0 else -1.0
    dd = float((equity / equity.cummax() - 1).min())
    ye = equity.resample("YE").last()
    starts = ye.shift(1)
    starts.iloc[0] = capital
    yearly = ye / starts - 1
    closed = fills[fills.status == "closed"] if len(fills) else fills
    return {
        "start": str(equity.index[0].date()), "end": str(equity.index[-1].date()),
        "capital": capital, "final": round(final, 2), "profit": round(final - capital, 2),
        "cagr_pct": round(cagr * 100, 2), "max_drawdown_pct": round(dd * 100, 2),
        "trades": int(len(fills)), "closed": int(len(closed)),
        "win_pct": round(float((closed.net_pnl > 0).mean() * 100), 1) if len(closed) else None,
        "avg_net_return_pct": round(float(closed.net_return_pct.mean()), 2) if len(closed) else None,
        "costs": round(float(fills.costs.sum()), 2) if len(fills) else 0.0,
        "yearly_return_pct": {int(k.year): round(float(v) * 100, 2) for k, v in yearly.items()},
        "by_strategy": ({s: {"trades": int(len(g)), "win_pct": round(float((g.net_pnl > 0).mean() * 100), 1),
                             "net_pnl": round(float(g.net_pnl.sum()), 2)}
                         for s, g in closed.groupby("strategy")} if len(closed) else {}),
    }


def run_portfolio(trades, closes, capital=100_000.0, buckets=None, risk_pct=1.0,
                  max_positions=10, position_cap_pct=25.0, costs=IndianDeliveryCosts(),
                  start=None, end=None, priority=("S4_SEPA", "S5_POCKETPIVOT", "S6_BREAKOUT")):
    """Replay `trades` through an account.

    buckets:  {strategy: fraction of capital} for separate money per strategy,
              each with its own `max_positions` slots; None = one shared pool
              with `max_positions` slots in total.
    Sizing:   risk `risk_pct` of the bucket's current value to the initial stop,
              capped at `position_cap_pct` of it and at the cash on hand; whole
              shares only. A stock already held is not bought again.
    Order:    same-day signals by strategy `priority`, then highest rank_key.
    Fills:    at the trade's own entry and exit prices, worsened by slippage,
              plus the charges in `costs`.
    `closes`: DataFrame dates x symbols of daily closes, for marking to market.
    """
    closes = closes.sort_index()
    dates = closes.index
    if start is not None:
        dates = dates[dates >= pd.Timestamp(start)]
    if end is not None:
        dates = dates[dates <= pd.Timestamp(end)]
    names = list(buckets) if buckets else ["ALL"]
    total_w = sum(buckets.values()) if buckets else 1.0
    cash = {b: capital * (buckets[b] / total_w if buckets else 1.0) for b in names}
    open_pos = {b: {} for b in names}
    held = set()
    fills, skipped = [], {"no_slot": 0, "held": 0, "too_small": 0, "no_bucket": 0}
    rank = {s: i for i, s in enumerate(priority)}
    t = trades.copy()
    t["_pri"] = t.strategy.map(rank).fillna(len(rank))
    by_day = {d: g.sort_values(["_pri", "rank_key"], ascending=[True, False])
              for d, g in t.groupby("entry_date")}
    slip = costs.slippage_pct / 100
    eq_rows = []

    def mark(b, d):
        v = cash[b]
        for sym, p in open_pos[b].items():
            px = closes.at[d, sym] if sym in closes.columns and pd.notna(closes.at[d, sym]) else p["last"]
            p["last"] = float(px)
            v += p["qty"] * p["last"]
        return v

    for d in dates:
        # exits first: a slot freed today can be reused by today's signal
        for b in names:
            for sym in list(open_pos[b]):
                p = open_pos[b][sym]
                if d >= p["exit_date"]:
                    px = p["exit"] * (1 - slip)
                    value = p["qty"] * px
                    fee = costs.sell(value)
                    cash[b] += value - fee
                    pnl = value - fee - p["cost_basis"]
                    fills.append({**p["row"], "qty": p["qty"], "fill_entry": p["fill_entry"], "fill_exit": px,
                                  "costs": p["buy_fee"] + fee, "net_pnl": pnl,
                                  "net_return_pct": pnl / p["cost_basis"] * 100, "status": "closed",
                                  "bucket": b})
                    del open_pos[b][sym]
                    held.discard(sym)
        values = {b: mark(b, d) for b in names}
        for r in (by_day[d].itertuples() if d in by_day else []):
            b = r.strategy if buckets else "ALL"
            if b not in open_pos:
                skipped["no_bucket"] += 1; continue
            if r.symbol in held:
                skipped["held"] += 1; continue
            if len(open_pos[b]) >= max_positions:
                skipped["no_slot"] += 1; continue
            px = float(r.entry) * (1 + slip)
            risk_per_share = px - float(r.stop)
            if risk_per_share <= 0:
                continue
            budget = min(values[b] * risk_pct / 100 / risk_per_share * px,
                         values[b] * position_cap_pct / 100, cash[b])
            qty = int(budget // px)
            # whole shares, and the buy charges must fit in the cash on hand too
            while qty >= 1 and qty * px + costs.buy(qty * px) > cash[b]:
                qty -= 1
            if qty < 1:
                skipped["too_small"] += 1; continue
            value = qty * px
            fee = costs.buy(value)
            cash[b] -= value + fee
            open_pos[b][r.symbol] = {"qty": qty, "fill_entry": px, "exit": float(r.exit),
                                     "exit_date": pd.Timestamp(r.exit_date), "last": px,
                                     "cost_basis": value + fee, "buy_fee": fee,
                                     "row": {k: getattr(r, k) for k in TRADE_COLUMNS}}
            held.add(r.symbol)
            values[b] = mark(b, d)
        eq_rows.append((d, {b: mark(b, d) for b in names}))

    # value anything still open at the last mark, as an unrealised line
    for b in names:
        for sym, p in open_pos[b].items():
            value = p["qty"] * p["last"]
            fills.append({**p["row"], "qty": p["qty"], "fill_entry": p["fill_entry"], "fill_exit": p["last"],
                          "costs": p["buy_fee"], "net_pnl": value - p["cost_basis"],
                          "net_return_pct": (value - p["cost_basis"]) / p["cost_basis"] * 100,
                          "status": "open", "bucket": b})
    bucket_eq = pd.DataFrame({d: v for d, v in eq_rows}).T.sort_index() if eq_rows else pd.DataFrame()
    equity = bucket_eq.sum(axis=1) if len(bucket_eq) else pd.Series(dtype=float)
    fills_df = pd.DataFrame(fills)
    res = PortfolioResult(equity=equity, bucket_equity=bucket_eq, fills=fills_df, skipped=skipped)
    res.stats = _stats(equity, fills_df, capital)
    res.stats["skipped"] = skipped
    res.stats["settings"] = {"buckets": buckets, "risk_pct": risk_pct, "max_positions": max_positions,
                             "position_cap_pct": position_cap_pct, "costs": asdict(costs)}
    return res


def close_matrix(data):
    """dates x symbols of closes from a {ticker: frame} dataset."""
    return pd.DataFrame({_norm(k): v["close"] for k, v in data.items() if v is not None and len(v)}).sort_index()
