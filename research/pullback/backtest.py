"""Portfolio simulation.

Timing contract, so the no-look-ahead claim is checkable:

  * a setup is evaluated on the close of day t using bars <= t;
  * the entry trigger (prior bar high) can only fire on day t+1;
  * the fill is max(open[t+1], trigger) — a gap through the trigger fills at the
    open, never at the trigger;
  * position size and exposure use marks from the close of day t, never day t+1;
  * within a bar, the stop is assumed to be hit before any profit target;
  * a gap below the stop fills at the open, not at the stop.

Cash convention: cash -= sign * shares * price on entry, cash += sign * shares *
price on exit, fees always subtracted, and equity = cash + sign * Σ shares·mark.
That is correct for both directions (a short adds its proceeds to cash and
carries a negative mark).
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .strategy import Config


@dataclass
class Trade:
    symbol: str
    setup_date: pd.Timestamp
    entry_date: pd.Timestamp
    entry: float
    stop: float
    shares: int
    risk_amount: float
    confluence: int
    levels: str
    rs_rank: float
    adr20: float
    stop_pct: float
    exit_date: object = None
    exit_reason: str = ""
    realized: float = 0.0
    exit_value: float = 0.0
    exit_shares: int = 0
    mfe_pct: float = 0.0
    mae_pct: float = 0.0
    holding_bars: int = 0
    partials: int = 0

    @property
    def r_multiple(self) -> float:
        return self.realized / self.risk_amount if self.risk_amount else 0.0

    @property
    def pnl_pct(self) -> float:
        cost = self.entry * self.shares
        return 100.0 * self.realized / cost if cost else 0.0


@dataclass
class Position:
    trade: Trade
    open_shares: int
    risk_per_share: float
    last_px: float
    hit_levels: set = field(default_factory=set)
    bars: int = 0


def _fee(cfg: Config, notional: float) -> float:
    """Half the round-trip cost model, charged on each side."""
    return abs(notional) * (cfg.cost_round_trip_pct / 100.0) / 2.0


def _close(cash: float, p: Position, px: float, qty: int, cfg: Config, sign: float,
           d, reason: str, partial: bool = False) -> float:
    qty = min(qty, p.open_shares)
    if qty <= 0:
        return cash
    proceeds = qty * px
    entry_cost = qty * p.trade.entry
    fees = _fee(cfg, proceeds) + _fee(cfg, entry_cost)
    p.trade.realized += sign * (proceeds - entry_cost) - fees
    p.trade.exit_value += proceeds
    p.trade.exit_shares += qty
    p.open_shares -= qty
    cash += sign * proceeds - _fee(cfg, proceeds)
    p.trade.holding_bars = p.bars
    if (not partial) or p.open_shares <= 0:
        p.trade.exit_date = d
        p.trade.exit_reason = reason
    return cash


def run(
    feats: dict[str, pd.DataFrame],
    setups: pd.DataFrame,
    cfg: Config,
    start: str,
    end: str,
    capital: float = 1_000_000.0,
) -> dict:
    all_dates = sorted({d for f in feats.values() for d in f.index})
    dates = [d for d in all_dates if pd.Timestamp(start) <= d <= pd.Timestamp(end)]
    pos_of = {d: i for i, d in enumerate(all_dates)}

    live: dict[pd.Timestamp, list] = {}
    if len(setups):
        for row in setups.itertuples(index=False):
            i = pos_of.get(row.setup_date)
            if i is None:
                continue
            for k in range(1, cfg.entry_window + 1):
                if i + k < len(all_dates):
                    live.setdefault(all_dates[i + k], []).append(row)

    cash = capital
    equity_prev = capital
    positions: dict[str, Position] = {}
    trades: list[Trade] = []
    curve: list[tuple] = []
    slip = cfg.slippage_pct / 100.0
    sign = 1.0 if cfg.direction == "long" else -1.0
    rejected_no_capital = 0

    for d in dates:
        # ---------------- manage open positions ------------------------------
        for sym in list(positions):
            p = positions[sym]
            f = feats[sym]
            if d not in f.index or d <= p.trade.entry_date:
                continue
            bar = f.loc[d]
            p.bars += 1
            t = p.trade
            hi, lo, op, cl = bar["high"], bar["low"], bar["open"], bar["close"]
            t.mfe_pct = max(t.mfe_pct, 100.0 * sign * (hi if sign > 0 else lo) / t.entry - 100.0 * sign)
            t.mae_pct = min(t.mae_pct, 100.0 * sign * (lo if sign > 0 else hi) / t.entry - 100.0 * sign)

            stopped = cfg.use_stop and ((lo <= t.stop) if sign > 0 else (hi >= t.stop))
            if stopped:
                gapped = (op <= t.stop) if sign > 0 else (op >= t.stop)
                px = op if gapped else t.stop
                px *= (1 - slip) if sign > 0 else (1 + slip)
                cash = _close(cash, p, px, p.open_shares, cfg, sign, d,
                              "stop_gap" if gapped else "stop")
                trades.append(t)
                del positions[sym]
                continue

            for r_level in cfg.partial_r_levels:
                if r_level in p.hit_levels or p.open_shares <= 0:
                    continue
                target = t.entry + sign * r_level * p.risk_per_share
                reached = (hi >= target) if sign > 0 else (lo <= target)
                if not reached:
                    continue
                px = max(op, target) if sign > 0 else min(op, target)
                px *= (1 - slip) if sign > 0 else (1 + slip)
                qty = min(max(1, int(round(t.shares * cfg.partial_fraction))), p.open_shares)
                cash = _close(cash, p, px, qty, cfg, sign, d, "partial", partial=True)
                p.hit_levels.add(r_level)
                t.partials += 1

            if p.open_shares <= 0:
                t.exit_date, t.exit_reason = d, "partials_exhausted"
                trades.append(t)
                del positions[sym]
                continue

            armed = cfg.trail_activate_r <= 0.0 or (
                sign * (cl - t.entry) >= cfg.trail_activate_r * p.risk_per_share)
            trail_hit = armed and ((cl < bar["ema9"]) if sign > 0 else (cl > bar["ema9"]))
            timed_out = bool(cfg.max_holding_bars) and p.bars >= cfg.max_holding_bars
            if (cfg.use_ema9_exit and trail_hit) or timed_out:
                px = cl * ((1 - slip) if sign > 0 else (1 + slip))
                reason = "ema9_close" if (cfg.use_ema9_exit and trail_hit) else "time"
                cash = _close(cash, p, px, p.open_shares, cfg, sign, d, reason)
                trades.append(t)
                del positions[sym]
            else:
                p.last_px = cl

        # ---------------- new entries ----------------------------------------
        gross_prev = sum(abs(p.open_shares * p.last_px) for p in positions.values())
        cands = []
        for row in live.get(d, []):
            if row.symbol in positions:
                continue
            f = feats[row.symbol]
            if d not in f.index:
                continue
            bar = f.loc[d]
            triggered = (bar["high"] >= row.trigger) if sign > 0 else (bar["low"] <= row.trigger)
            if not triggered:
                continue
            fill = max(bar["open"], row.trigger) if sign > 0 else min(bar["open"], row.trigger)
            fill *= (1 + slip) if sign > 0 else (1 - slip)
            risk_ps = (fill - row.stop) if sign > 0 else (row.stop - fill)
            if risk_ps <= 0:
                continue
            stop_pct = 100.0 * risk_ps / fill
            if cfg.use_stop:
                cap = cfg.max_stop_pct
                if cfg.use_adr_stop_cap:
                    cap = min(cap, cfg.stop_adr_fraction * row.adr20)
                if stop_pct > cap:
                    continue
            cands.append((row, bar, fill, risk_ps, stop_pct))

        cands.sort(key=lambda c: (-c[0].confluence, -c[0].rs_rank, -c[0].dv20))
        taken = 0
        for row, bar, fill, risk_ps, stop_pct in cands:
            if taken >= cfg.max_new_per_day or len(positions) >= cfg.max_positions:
                break
            budget = min(
                cfg.max_gross_exposure * equity_prev - gross_prev,
                cfg.max_position_pct * equity_prev,
            )
            if sign > 0:
                budget = min(budget, cash)
            by_risk = (max(budget, 0) / fill if cfg.equal_weight_sizing
                       else cfg.risk_pct * equity_prev / risk_ps)
            shares = int(min(by_risk, max(budget, 0) / fill))
            if shares <= 0:
                rejected_no_capital += 1
                continue
            notional = shares * fill
            cash -= sign * notional + _fee(cfg, notional)
            gross_prev += notional
            t = Trade(
                symbol=row.symbol, setup_date=row.setup_date, entry_date=d, entry=fill,
                stop=row.stop, shares=shares, risk_amount=shares * risk_ps,
                confluence=int(row.confluence), levels=row.levels,
                rs_rank=float(row.rs_rank), adr20=float(row.adr20), stop_pct=stop_pct,
            )
            p = Position(trade=t, open_shares=shares, risk_per_share=risk_ps, last_px=fill)
            t.mfe_pct = max(0.0, 100.0 * sign * (bar["high"] - fill) / fill)
            t.mae_pct = min(0.0, 100.0 * sign * (bar["low"] - fill) / fill)
            breached = cfg.use_stop and (
                (bar["low"] <= row.stop) if sign > 0 else (bar["high"] >= row.stop))
            gap_entry = (bar["open"] >= row.trigger) if sign > 0 else (bar["open"] <= row.trigger)
            # "benign" assumes the adverse excursion happened before the trigger
            # fired, so the position was not yet open; only a gap entry is then
            # exposed to the whole bar.
            same_day_stop = breached and (cfg.intrabar == "adverse" or gap_entry)
            if same_day_stop:
                px = row.stop * ((1 - slip) if sign > 0 else (1 + slip))
                cash = _close(cash, p, px, p.open_shares, cfg, sign, d, "stop_same_day")
                trades.append(t)
            else:
                positions[row.symbol] = p
            taken += 1

        # ---------------- mark to market -------------------------------------
        mtm = 0.0
        for sym, p in positions.items():
            f = feats[sym]
            if d in f.index:
                p.last_px = f.loc[d, "close"]
            mtm += sign * p.open_shares * p.last_px
        equity_prev = cash + mtm
        curve.append((d, equity_prev, len(positions), cash))

    last = dates[-1]
    for sym, p in list(positions.items()):
        cash = _close(cash, p, p.last_px, p.open_shares, cfg, sign, last, "open_at_end")
        trades.append(p.trade)
        del positions[sym]

    eq = pd.DataFrame(curve, columns=["date", "equity", "positions", "cash"]).set_index("date")
    return {
        "trades": _trades_frame(trades),
        "equity": eq,
        "config": cfg,
        "final_equity": float(eq["equity"].iloc[-1]) if len(eq) else capital,
        "capital": capital,
        "rejected_no_capital": rejected_no_capital,
    }


def _trades_frame(trades: list[Trade]) -> pd.DataFrame:
    if not trades:
        return pd.DataFrame(
            columns=["symbol", "setup_date", "entry_date", "exit_date", "entry", "stop",
                     "avg_exit", "shares", "stop_pct", "risk_amount", "pnl", "r_multiple",
                     "pnl_pct", "holding_bars", "exit_reason", "mfe_pct", "mae_pct",
                     "confluence", "levels", "rs_rank", "adr20", "partials"]
        )
    rows = [
        {
            "symbol": t.symbol, "setup_date": t.setup_date, "entry_date": t.entry_date,
            "exit_date": t.exit_date, "entry": t.entry, "stop": t.stop,
            "avg_exit": t.exit_value / t.exit_shares if t.exit_shares else np.nan,
            "shares": t.shares, "stop_pct": t.stop_pct, "risk_amount": t.risk_amount,
            "pnl": t.realized, "r_multiple": t.r_multiple, "pnl_pct": t.pnl_pct,
            "holding_bars": t.holding_bars, "exit_reason": t.exit_reason,
            "mfe_pct": t.mfe_pct, "mae_pct": t.mae_pct, "confluence": t.confluence,
            "levels": t.levels, "rs_rank": t.rs_rank, "adr20": t.adr20,
            "partials": t.partials,
        }
        for t in trades
    ]
    return pd.DataFrame(rows).sort_values("entry_date").reset_index(drop=True)


# --------------------------------------------------------------------------- #
# unconstrained signal study
# --------------------------------------------------------------------------- #

def signal_study(
    feats: dict[str, pd.DataFrame],
    setups: pd.DataFrame,
    cfg: Config,
    start: str,
    end: str,
    max_bars: int = 250,
) -> pd.DataFrame:
    """Every setup traded independently, one unit of risk, no portfolio limits.

    The portfolio run answers "what would my account have done"; this answers
    "does the signal itself carry an edge", with every signal counted instead of
    only those that fitted inside the book.  Same entry, stop, partial and trail
    rules; no capital, ranking or position caps, so no selection is imposed by
    the simulator.
    """
    if not len(setups):
        return pd.DataFrame()
    all_dates = sorted({d for f in feats.values() for d in f.index})
    pos_of = {d: i for i, d in enumerate(all_dates)}
    slip = cfg.slippage_pct / 100.0
    half_cost = cfg.cost_round_trip_pct / 200.0
    sign = 1.0 if cfg.direction == "long" else -1.0
    lo_d, hi_d = pd.Timestamp(start), pd.Timestamp(end)
    rows = []

    for row in setups.itertuples(index=False):
        if not (lo_d <= row.setup_date <= hi_d):
            continue
        f = feats[row.symbol]
        i = pos_of.get(row.setup_date)
        if i is None or i + 1 >= len(all_dates):
            continue
        entry_date, bar = None, None
        for k in range(1, cfg.entry_window + 1):     # the trigger stays live for
            if i + k >= len(all_dates):              # entry_window bars
                break
            cand = all_dates[i + k]
            if cand not in f.index:
                continue
            b = f.loc[cand]
            if (b["high"] >= row.trigger) if sign > 0 else (b["low"] <= row.trigger):
                entry_date, bar = cand, b
                break
        if entry_date is None:
            reason = "no_trigger" if i + 1 < len(all_dates) else "no_bar"
            rows.append(_sig_row(row, reason, np.nan, 0, 0.0, 0.0, np.nan))
            continue
        fill = max(bar["open"], row.trigger) if sign > 0 else min(bar["open"], row.trigger)
        fill *= (1 + slip) if sign > 0 else (1 - slip)
        risk_ps = (fill - row.stop) if sign > 0 else (row.stop - fill)
        if risk_ps <= 0:
            rows.append(_sig_row(row, "bad_geometry", np.nan, 0, 0.0, 0.0, np.nan))
            continue
        stop_pct = 100.0 * risk_ps / fill
        if cfg.use_stop:
            cap = cfg.max_stop_pct
            if cfg.use_adr_stop_cap:
                cap = min(cap, cfg.stop_adr_fraction * row.adr20)
            if stop_pct > cap:
                rows.append(_sig_row(row, "stop_too_wide", np.nan, 0, 0.0, 0.0, stop_pct))
                continue

        pnl = -half_cost * fill          # entry cost, per unit of position
        remaining = 1.0
        hit = set()
        mfe = mae = 0.0
        reason, bars = "", 0
        idx = f.index
        j = idx.get_loc(entry_date)

        for k in range(0, max_bars + 1):
            if j + k >= len(idx):
                reason = "data_end"
                break
            b = f.iloc[j + k]
            first_bar = k == 0
            hi, lo, op, cl = b["high"], b["low"], b["open"], b["close"]
            mfe = max(mfe, 100.0 * sign * (hi if sign > 0 else lo) / fill - 100.0 * sign)
            mae = min(mae, 100.0 * sign * (lo if sign > 0 else hi) / fill - 100.0 * sign)
            bars = k

            breached = cfg.use_stop and ((lo <= row.stop) if sign > 0 else (hi >= row.stop))
            if first_bar:
                gap_entry = (op >= row.trigger) if sign > 0 else (op <= row.trigger)
                breached = breached and (cfg.intrabar == "adverse" or gap_entry)
            if breached:
                gapped = (op <= row.stop) if sign > 0 else (op >= row.stop)
                px = (op if (gapped and not first_bar) else row.stop)
                px *= (1 - slip) if sign > 0 else (1 + slip)
                pnl += remaining * (sign * (px - fill) - half_cost * px)
                remaining, reason = 0.0, "stop_gap" if gapped else "stop"
                break

            for r_level in cfg.partial_r_levels:
                if r_level in hit or remaining <= 0:
                    continue
                target = fill + sign * r_level * risk_ps
                if (hi >= target) if sign > 0 else (lo <= target):
                    px = (max(op, target) if sign > 0 else min(op, target))
                    px *= (1 - slip) if sign > 0 else (1 + slip)
                    qty = min(cfg.partial_fraction, remaining)
                    pnl += qty * (sign * (px - fill) - half_cost * px)
                    remaining -= qty
                    hit.add(r_level)
            if remaining <= 1e-9:
                reason = "partials_exhausted"
                break

            armed = cfg.trail_activate_r <= 0.0 or (
                sign * (cl - fill) >= cfg.trail_activate_r * risk_ps)
            trail_hit = armed and ((cl < b["ema9"]) if sign > 0 else (cl > b["ema9"]))
            timed = bool(cfg.max_holding_bars) and k >= cfg.max_holding_bars
            if (cfg.use_ema9_exit and trail_hit and not first_bar) or timed:
                px = cl * ((1 - slip) if sign > 0 else (1 + slip))
                pnl += remaining * (sign * (px - fill) - half_cost * px)
                remaining, reason = 0.0, "ema9_close" if trail_hit else "time"
                break

        if remaining > 0:
            px = f.iloc[min(j + bars, len(idx) - 1)]["close"]
            pnl += remaining * (sign * (px - fill) - half_cost * px)
            reason = reason or "open_at_end"

        rows.append(_sig_row(row, reason, pnl / risk_ps, bars, mfe, mae, stop_pct,
                             entry=fill, entry_date=entry_date))

    return pd.DataFrame(rows)


def _sig_row(row, reason, r, bars, mfe, mae, stop_pct, entry=np.nan, entry_date=None):
    return {
        "symbol": row.symbol, "setup_date": row.setup_date, "entry_date": entry_date,
        "entry": entry, "stop": row.stop, "stop_pct": stop_pct, "outcome": reason,
        "r_multiple": r, "holding_bars": bars, "mfe_pct": mfe, "mae_pct": mae,
        "confluence": row.confluence, "levels": row.levels, "rs_rank": row.rs_rank,
        "adr20": row.adr20, "dv20": row.dv20, "traded": not np.isnan(r) if r is not None else False,
    }


def edge_probe(
    feats: dict[str, pd.DataFrame],
    setups: pd.DataFrame,
    market: pd.DataFrame,
    start: str,
    end: str,
    horizons=(1, 3, 5, 10, 20),
) -> pd.DataFrame:
    """Raw forward returns of the setup, with the exit rules switched off.

    Separates two questions the portfolio run conflates: does the *setup* select
    stocks that go up, and does the *exit* keep any of it.  Entry is still the
    next bar's open (no trigger condition, so nothing is selected by hindsight),
    and each horizon return is quoted against the equal-weighted market over the
    identical dates, so a rising tide is netted out.
    """
    if not len(setups):
        return pd.DataFrame()
    all_dates = sorted({d for f in feats.values() for d in f.index})
    pos_of = {d: i for i, d in enumerate(all_dates)}
    lo_d, hi_d = pd.Timestamp(start), pd.Timestamp(end)
    rows = []
    for row in setups.itertuples(index=False):
        if not (lo_d <= row.setup_date <= hi_d):
            continue
        f = feats[row.symbol]
        i = pos_of.get(row.setup_date)
        if i is None or i + 1 >= len(all_dates):
            continue
        entry_date = all_dates[i + 1]
        if entry_date not in f.index:
            continue
        j = f.index.get_loc(entry_date)
        base = f.iloc[j]["open"]
        rec = {"symbol": row.symbol, "setup_date": row.setup_date, "entry_date": entry_date,
               "confluence": row.confluence, "rs_rank": row.rs_rank, "adr20": row.adr20}
        for h in horizons:
            k = j + h
            if k < len(f):
                rec[f"fwd{h}"] = 100.0 * (f.iloc[k]["close"] / base - 1.0)
                if entry_date in market.index:
                    m0 = market.index.get_loc(entry_date)
                    m1 = min(m0 + h, len(market) - 1)
                    mret = 100.0 * (market["level"].iloc[m1] / market["level"].iloc[m0] - 1.0)
                    rec[f"exc{h}"] = rec[f"fwd{h}"] - mret
            else:
                rec[f"fwd{h}"] = np.nan
                rec[f"exc{h}"] = np.nan
        rows.append(rec)
    return pd.DataFrame(rows)


def baseline_probe(
    feats: dict[str, pd.DataFrame],
    market: pd.DataFrame,
    start: str,
    end: str,
    horizons=(1, 3, 5, 10, 20),
    stride: int = 5,
) -> pd.DataFrame:
    """The same forward-return measurement on every stock/day in the window.

    This is the null the setup has to beat: buying anything, any day.
    """
    lo_d, hi_d = pd.Timestamp(start), pd.Timestamp(end)
    rows = []
    for sym, f in feats.items():
        idx = f.index
        sel = np.where((idx >= lo_d) & (idx <= hi_d))[0][::stride]
        for j in sel:
            if j + 1 >= len(f):
                continue
            base = f.iloc[j + 1]["open"]
            rec = {"symbol": sym, "entry_date": idx[j + 1]}
            for h in horizons:
                k = j + 1 + h
                if k < len(f):
                    rec[f"fwd{h}"] = 100.0 * (f.iloc[k]["close"] / base - 1.0)
                    if idx[j + 1] in market.index:
                        m0 = market.index.get_loc(idx[j + 1])
                        m1 = min(m0 + h, len(market) - 1)
                        mret = 100.0 * (market["level"].iloc[m1] / market["level"].iloc[m0] - 1.0)
                        rec[f"exc{h}"] = rec[f"fwd{h}"] - mret
            rows.append(rec)
    return pd.DataFrame(rows)
