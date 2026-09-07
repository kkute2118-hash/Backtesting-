"""Rule engine: market gate, stock gate, pullback setup, entry trigger.

Rule IDs match research/PULLBACK_STRATEGY_RULEBOOK.md.  Every rule that can be
switched off for the ablation study is a field on `Config`, so the ablation
never edits the rule code — it edits one flag.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

import pandas as pd

LEVEL_NAMES = ("ema9", "ema21", "ema50", "ema150", "avwap", "swing_high", "gap_base")


@dataclass
class Config:
    # --- market gate (video: general market / QQQ-IWM situational awareness) --
    use_market_trend: bool = True        # M1  index above its 50 EMA
    use_market_slope: bool = True        # M2  index 21 EMA rising
    use_breadth: bool = True             # M3  breadth floor
    breadth_min: float = 0.40            # M3  threshold — ENGINEERING CHOICE
    use_index_not_extended: bool = False # M4  optional "don't press when extended"
    index_extension_max: float = 0.04

    # --- stock gate ----------------------------------------------------------
    use_liquidity: bool = True           # S1  dollar volume
    min_dv20: float = 5.0e7              # S1  INR 5 crore median turnover
    use_adr: bool = True                 # S2  "only fast moving stocks"
    min_adr20: float = 2.0               # S2  percent — ENGINEERING CHOICE
    use_daily_trend: bool = True         # S3  9>21>50, close>150, 21 rising
    use_ema150: bool = True              # S3b close above the 150 EMA
    use_weekly: bool = True              # S4  weekly 9>21 and close>weekly 9
    use_rs: bool = True                  # S5  relative strength / leadership
    min_rs_rank: float = 70.0            # S5  percentile — ENGINEERING CHOICE
    use_fresh_leg: bool = True           # S6  recent 20-day high
    max_bars_since_high20: int = 15      # S6
    use_higher_low: bool = True          # S7  base makes higher lows

    # --- setup ---------------------------------------------------------------
    touch_tol: float = 0.005             # P1  low must reach within 0.5% of level
    close_tol: float = 0.005             # P1  close must hold within 0.5% of level
    use_reversal_close: bool = True      # P2  close in upper half of the range
    min_close_pos: float = 0.50          # P2
    use_real_dip: bool = True            # P3  the pullback must be a real dip
    dip_atr: float = 1.0                 # P3
    min_confluence: int = 1              # P4  levels lining up at the touch

    # --- entry / risk --------------------------------------------------------
    entry_window: int = 1                # E1  bars the trigger stays live
    max_stop_pct: float = 5.0            # R1  hard ceiling from the video
    stop_adr_fraction: float = 0.50      # R1  "stop < 50% of the stock's ADR"
    use_adr_stop_cap: bool = True        # R1  apply the ADR half-range cap at all
    intrabar: str = "adverse"            # path assumption when a bar both triggers
                                         # and breaches the stop: adverse | benign
    use_stop: bool = True                # R1  set False only for the harness
                                         # control run (buy-and-hold benchmark)
    equal_weight_sizing: bool = False    # control only: size by max_position_pct
                                         # instead of by risk, so a stopless run
                                         # is not sized to nothing
    risk_pct: float = 0.005              # R2  0.5% of equity per trade
    max_position_pct: float = 0.30       # R3  25-30% typical, 35% ceiling
    max_gross_exposure: float = 1.00     # R4  no margin in the base run
    max_positions: int = 8               # R5
    max_new_per_day: int = 4             # R5

    # --- exits ---------------------------------------------------------------
    partial_r_levels: tuple = (3.0, 5.0)  # X1  sell into strength at +3R, +5R
    partial_fraction: float = 0.15        # X1  ~15% of the position each time
    use_ema9_exit: bool = True            # X2  close the rest on first close < 9EMA
    trail_activate_r: float = 0.0         # X2b R of open profit before the 9 EMA
                                          # rule arms (0 = from entry — see AMBIG-3)
    max_holding_bars: int = 0             # X3  0 = no time stop (longs)

    # --- costs ---------------------------------------------------------------
    cost_round_trip_pct: float = 0.23     # repo's cost model
    slippage_pct: float = 0.05            # each side, on top of costs

    direction: str = "long"
    label: str = "original"


def _level_frame(f: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    """The support levels the video names, one column each, NaN when absent."""
    lv = pd.DataFrame(index=f.index)
    lv["ema9"] = f["ema9"]
    lv["ema21"] = f["ema21"]
    lv["ema50"] = f["ema50"]
    lv["ema150"] = f["ema150"]
    lv["avwap"] = f["avwap"]
    # a prior swing high only acts as support once price is above it (break/retest)
    sh = f["swing_high"]
    lv["swing_high"] = sh.where(f["close"] > sh)
    lv["gap_base"] = f["gap_base"]
    return lv


def setups(sym: str, f: pd.DataFrame, rs: pd.Series, mkt: pd.DataFrame, cfg: Config) -> pd.DataFrame:
    """Rows are dates on which a valid setup closed.  Entry is the *next* bar.

    The short branch is the mirror image the video describes explicitly: a rally
    into declining EMAs / anchored VWAP instead of a dip into rising ones, with
    the weekly veto ("don't short it while the weekly is still above its 9 EMA")
    applied the same way round.
    """
    long_side = cfg.direction == "long"
    ok = pd.Series(True, index=f.index)

    # --- stock gate ----------------------------------------------------------
    if cfg.use_liquidity:
        ok &= f["dv20"] >= cfg.min_dv20
    if cfg.use_adr:
        ok &= f["adr20"] >= cfg.min_adr20
    if cfg.use_daily_trend:
        if long_side:
            ok &= (f["ema9"] > f["ema21"]) & (f["ema21"] > f["ema50"]) & (f["ema21_slope"] > 0)
        else:
            ok &= (f["ema9"] < f["ema21"]) & (f["ema21"] < f["ema50"]) & (f["ema21_slope"] < 0)
    if cfg.use_ema150:
        ok &= (f["close"] > f["ema150"]) if long_side else (f["close"] < f["ema150"])
    if cfg.use_weekly:
        if long_side:
            ok &= (f["w_ema9"] > f["w_ema21"]) & (f["w_close"] > f["w_ema9"])
        else:
            ok &= (f["w_ema9"] < f["w_ema21"]) & (f["w_close"] < f["w_ema9"])
    if cfg.use_rs:
        rr = rs.reindex(f.index)
        ok &= (rr >= cfg.min_rs_rank) if long_side else (rr <= 100.0 - cfg.min_rs_rank)
    if cfg.use_fresh_leg:
        col = "bars_since_high20" if long_side else "bars_since_low20"
        ok &= f[col] <= cfg.max_bars_since_high20
    if cfg.use_higher_low:
        ok &= (f["swing_low"] > f["swing_low_prev"]) if long_side else (f["swing_high"] < f["swing_high_prev"])

    # --- market gate ---------------------------------------------------------
    m = mkt.reindex(f.index)
    if cfg.use_market_trend:
        ok &= (m["level"] > m["ema50"]) if long_side else (m["level"] < m["ema50"])
    if cfg.use_market_slope:
        ok &= (m["ema21_slope"] > 0) if long_side else (m["ema21_slope"] < 0)
    if cfg.use_breadth:
        ok &= (m["breadth50"] >= cfg.breadth_min) if long_side else (m["breadth50"] <= 1.0 - cfg.breadth_min)
    if cfg.use_index_not_extended:
        ext = m["level"] / m["ema21"] - 1.0
        ok &= (ext <= cfg.index_extension_max) if long_side else (ext >= -cfg.index_extension_max)

    # --- pullback (long) / rally (short) into the level ----------------------
    lv = _level_frame(f, cfg)
    touched = pd.DataFrame(index=f.index)
    for name in LEVEL_NAMES:
        level = lv[name]
        if long_side:
            touched[name] = (f["low"] <= level * (1 + cfg.touch_tol)) & (f["close"] >= level * (1 - cfg.close_tol))
        else:
            touched[name] = (f["high"] >= level * (1 - cfg.touch_tol)) & (f["close"] <= level * (1 + cfg.close_tol))
    confluence = touched.fillna(False).sum(axis=1)
    ok &= confluence >= cfg.min_confluence

    if cfg.use_reversal_close:
        ok &= (f["close_pos"] >= cfg.min_close_pos) if long_side else (f["close_pos"] <= 1.0 - cfg.min_close_pos)
    if cfg.use_real_dip:
        if long_side:
            ok &= f["low"] <= (f["high20"] - cfg.dip_atr * f["atr14"])
        else:
            ok &= f["high"] >= (f["low20"] + cfg.dip_atr * f["atr14"])

    ok = ok.fillna(False)
    if not ok.any():
        return pd.DataFrame()

    idx = f.index[ok.to_numpy()]
    touched_bool = touched.fillna(False)
    out = pd.DataFrame(
        {
            "symbol": sym,
            "setup_date": idx,
            "trigger": f.loc[idx, "high" if long_side else "low"].to_numpy(),
            "stop": f.loc[idx, "low" if long_side else "high"].to_numpy(),
            "confluence": confluence.loc[idx].to_numpy(),
            "rs_rank": rs.reindex(f.index).loc[idx].to_numpy(),
            "dv20": f.loc[idx, "dv20"].to_numpy(),
            "adr20": f.loc[idx, "adr20"].to_numpy(),
            "atr14": f.loc[idx, "atr14"].to_numpy(),
            "close": f.loc[idx, "close"].to_numpy(),
            "levels": [",".join(n for n in LEVEL_NAMES if bool(touched_bool[n].loc[d])) for d in idx],
        }
    )
    return out


def all_setups(feats, rs_frame, market, cfg: Config) -> pd.DataFrame:
    frames = []
    for sym, f in feats.items():
        s = setups(sym, f, rs_frame[sym], market.index, cfg)
        if len(s):
            frames.append(s)
    if not frames:
        return pd.DataFrame(
            columns=["symbol", "setup_date", "trigger", "stop", "confluence", "rs_rank", "dv20"]
        )
    out = pd.concat(frames, ignore_index=True)
    return out.sort_values(["setup_date", "symbol"]).reset_index(drop=True)


def variant(base: Config, label: str, **kw) -> Config:
    return replace(base, label=label, **kw)
