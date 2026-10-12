"""Rulebook v1 (RB1) constants: the owner's rulebook (12 Oct 2026).

Tags: SOURCE_STATED (the rulebook says so), DERIVED (chosen to implement a
stated rule), NEEDS_TUNING (a guess the owner decides after the first test).
Per-group overrides go in GROUP_OVERRIDES.
"""

# --- Capital & risk ---
STARTING_CAPITAL_USD = 10_000          # NEEDS_TUNING (owner to confirm)
RISK_PER_TRADE = 0.01                  # DERIVED
RISK_PER_TRADE_HIGH = 0.02             # SOURCE_STATED ("double risk" on five-star trades): confluence >= 4 or delta absorption
RISK_PER_DAY_MAX = 0.025               # DERIVED (tighter than the source's 5%)
MAX_TRADES_PER_DAY = 2                 # SOURCE_STATED
STOP_AFTER_LOSSES_PER_DAY = 2          # SOURCE_STATED
DAILY_PROFIT_STOP = 0.05               # SOURCE_STATED: stop trading that day once reached
MIN_RR = 2.0                           # SOURCE_STATED
LEVERAGE = {"crypto": 10, "gold": 10, "forex": 10}   # SOURCE_STATED for crypto; margin only, never sizing
MAINTENANCE_MARGIN = 0.005             # DERIVED: liquidation sits at about 1/leverage - this from entry

# --- Timeframes ---
BIAS_TF = "1h"                         # SOURCE_STATED
EXEC_TF = "15min"                      # SOURCE_STATED
OB_TFS = ("15min", "1h")               # SOURCE_STATED: never order blocks below 15m

# --- Day boundary & window ---
DAY_BOUNDARY_UTC_HOURS = {"crypto": 0, "gold": 22, "forex": 22}   # DERIVED (forex/gold = New York close)
TRADING_WINDOW_UTC = (7, 16)           # DERIVED (12:30-21:30 IST); SOURCE_STATED that a fixed window exists
SKIP_WEEKENDS = {"crypto": False, "gold": True, "forex": True}

# --- Indicators ---
ATR_LEN = 14
SWING_PIVOT_BARS = 3                   # DERIVED: fractal pivot, bars each side
ZONE_MERGE_ATR = 0.25                  # DERIVED, x ATR(14, 15m)
STOP_BUFFER_ATR = 0.20                 # DERIVED, x ATR(14, 15m)
CDH_CDL_ATR_GATE = 0.70                # SOURCE_STATED ("ATR minus 30%"), x ATR(14, daily)

# --- Candle classifier ---
POWER_BODY_PCT = 0.60                  # NEEDS_TUNING
POWER_CLOSE_ZONE = 0.25                # NEEDS_TUNING (close in the top/bottom 25% of the range)
POWER_MIN_RANGE_ATR = 1.0              # NEEDS_TUNING
REJ_WICK_TO_BODY = 2.0                 # NEEDS_TUNING
REJ_WICK_PCT = 0.50                    # NEEDS_TUNING

# --- Delta ---
DELTA_NEUTRAL_PCT = 0.10               # NEEDS_TUNING: |delta|/volume below this = neutral

# --- Levels / scoring ---
LEVEL_SCORES = {"PDH_PDL": 3, "VAH_VAL": 2, "HTF_OB": 2, "TRIPLE_TOUCH": 2, "CDH_CDL": 1}
MIN_CONFLUENCE = 2                     # DERIVED
HIGH_CONFLUENCE = 4                    # DERIVED
VALUE_AREA_PCT = 0.70                  # standard value-area definition
VALUE_AREA_BINS = 50                   # DERIVED: price bins of the previous day's volume profile
SWEEP_MAX_DEPTH_ATR = 0.5              # NEEDS_TUNING: deeper is a breakout, not a sweep
MIN_ZONE_TOUCHES = 3                   # SOURCE_STATED: trade the 4th touch
TRIPLE_LOOKBACK_BARS = 480             # NEEDS_TUNING: turning points from the last 5 days of 15m bars
OB_MAX_AGE_DAYS = 10                   # NEEDS_TUNING: unmitigated order blocks older than this are dropped
TARGET_MODE = "nearest"                # NEEDS_TUNING: "nearest" opposing level (the rulebook) | "first_ok" (first level giving MIN_RR)
D_TARGET_R = 2.0                       # NEEDS_TUNING: the rulebook only says ">= MIN_RR" for N-breakouts
RANGE_ALLOWS_BOTH = False              # NEEDS_TUNING: in a RANGE, trade only A_SWEEP at PDH/PDL (the rulebook)

# --- Management ---
BREAKEVEN_AT = 0.50                    # SOURCE_STATED (fraction of the distance to TP)
TRAIL_FROM = 0.80                      # SOURCE_STATED
TRAIL_METHOD = "swing"                 # SOURCE_STATED ("swing" | "ema20")

# --- Setups on/off ---
SETUPS_ENABLED = {"A_SWEEP": True, "B_TRIPLE": True, "C_PULLBACK": True, "D_NBREAKOUT": True}
SETUP_PRIORITY = ("A_SWEEP", "B_TRIPLE", "C_PULLBACK", "D_NBREAKOUT")
DELTA_FILTER_MODE = "upgrade"          # "off" | "upgrade" (raises the risk tier) | "required"

# --- Costs (the repository's existing models) ---
CRYPTO_TAKER = 0.0005 * 1.18           # Binance futures taker 0.05% + 18% GST
CRYPTO_SLIPPAGE = 0.0001
FX_SLIPPAGE = 0.00002                  # plus half the recorded Dukascopy spread per side

GROUPS = {
    "crypto": ("BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT"),
    "gold": ("XAUUSD",),
    "forex": ("EURUSD", "GBPUSD"),
}
GROUP_OVERRIDES: dict[str, dict] = {"crypto": {}, "gold": {}, "forex": {}}


def group_of(symbol: str) -> str:
    for g, syms in GROUPS.items():
        if symbol in syms:
            return g
    raise KeyError(symbol)


def tagged() -> list[tuple[str, object, str]]:
    """(name, value, tag) for every constant, read from this file's comments."""
    import inspect
    import re
    out = []
    for line in inspect.getsource(inspect.getmodule(tagged)).splitlines():
        m = re.match(r"^([A-Z][A-Z0-9_]+)\s*=.*?#\s*(SOURCE_STATED|DERIVED|NEEDS_TUNING)", line)
        if m:
            out.append((m.group(1), globals()[m.group(1)], m.group(2)))
    return out
