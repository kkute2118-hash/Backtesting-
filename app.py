import streamlit as st
import pandas as pd
import numpy as np
import requests
import yfinance as yf
from datetime import date, timedelta

# ============================================================
# PAGE CONFIG
# ============================================================

st.set_page_config(
    page_title="Adaptive Trading Intelligence Lab",
    page_icon="🧠",
    layout="wide"
)

# ============================================================
# NSE INDEX DATA
# ============================================================

NSE_URLS = {
    "Nifty 500":
        "https://www.niftyindices.com/IndexConstituent/ind_nifty500list.csv",

    "Nifty Smallcap 100":
        "https://www.niftyindices.com/IndexConstituent/ind_niftysmallcap100list.csv",

    "Nifty Smallcap 250":
        "https://www.niftyindices.com/IndexConstituent/ind_niftysmallcap250list.csv",

    "Nifty Midcap 150":
        "https://www.niftyindices.com/IndexConstituent/ind_niftymidcap150list.csv",
}


@st.cache_data(ttl=86400, show_spinner=False)
def get_universe(index_name):

    response = requests.get(
        NSE_URLS[index_name],
        headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://www.niftyindices.com/"
        },
        timeout=30
    )

    response.raise_for_status()

    df = pd.read_csv(
        pd.io.common.BytesIO(response.content)
    )

    symbol_column = None

    for column in df.columns:
        if str(column).strip().upper() == "SYMBOL":
            symbol_column = column
            break

    if symbol_column is None:
        raise ValueError(
            "NSE constituent file does not contain SYMBOL column."
        )

    symbols = []

    for symbol in df[symbol_column].dropna():

        symbol = str(symbol).strip().upper()

        if symbol:
            if not symbol.endswith(".NS"):
                symbol += ".NS"

            symbols.append(symbol)

    return sorted(set(symbols))


# ============================================================
# YAHOO FINANCE PRICE DATA
# ============================================================

@st.cache_data(ttl=1800, show_spinner=False)
def download_prices(tickers, start_date, end_date):

    tickers = list(tickers)

    if not tickers:
        return {}

    raw = yf.download(
        tickers=tickers,
        start=start_date,
        end=end_date + timedelta(days=1),
        auto_adjust=False,
        progress=False,
        group_by="ticker",
        threads=True
    )

    result = {}

    if len(tickers) == 1:

        if not raw.empty:

            raw.columns = [
                str(c).lower()
                for c in raw.columns
            ]

            raw = raw.dropna(
                subset=["close"]
            )

            result[tickers[0]] = raw

        return result

    for ticker in tickers:

        try:

            df = raw[ticker].copy()

            df.columns = [
                str(c).lower()
                for c in df.columns
            ]

            df = df.dropna(
                subset=["close"]
            )

            if not df.empty:
                result[ticker] = df

        except Exception:
            continue

    return result


# ============================================================
# INDICATORS
# ============================================================

def ema(series, period):

    return series.ewm(
        span=period,
        adjust=False,
        min_periods=period
    ).mean()


def sma(series, period):

    return series.rolling(
        period,
        min_periods=period
    ).mean()


def rsi(series, period=14):

    change = series.diff()

    gain = change.clip(lower=0)
    loss = -change.clip(upper=0)

    average_gain = gain.ewm(
        alpha=1 / period,
        adjust=False,
        min_periods=period
    ).mean()

    average_loss = loss.ewm(
        alpha=1 / period,
        adjust=False,
        min_periods=period
    ).mean()

    rs = (
        average_gain /
        average_loss.replace(0, np.nan)
    )

    return 100 - (
        100 / (1 + rs)
    )


def add_features(df):

    x = df.copy()

    # Daily indicators

    for period in [
        10,
        15,
        20,
        50,
        200,
        250
    ]:

        x[f"ema{period}"] = ema(
            x["close"],
            period
        )

    x["volume20"] = sma(
        x["volume"],
        20
    )

    x["volume30"] = sma(
        x["volume"],
        30
    )

    x["rsi14"] = rsi(
        x["close"],
        14
    )

    x["momentum"] = (
        x["close"].pct_change() * 100
    )

    x["relative_volume"] = (
        x["volume"] /
        x["volume20"]
    )

    # ATR

    true_range = pd.concat(
        [
            x["high"] - x["low"],
            (
                x["high"] -
                x["close"].shift()
            ).abs(),
            (
                x["low"] -
                x["close"].shift()
            ).abs()
        ],
        axis=1
    ).max(axis=1)

    x["atr14"] = (
        true_range
        .rolling(14)
        .mean()
    )

    # Monthly indicators
    monthly = x.resample("ME").agg({
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
        "volume": "sum"
    })

    monthly["rsi14"] = rsi(
        monthly["close"],
        14
    )

    monthly["ema10"] = ema(
        monthly["close"],
        10
    )

    monthly["ema15"] = ema(
        monthly["close"],
        15
    )

    monthly["ema20"] = ema(
        monthly["close"],
        20
    )

    monthly["momentum"] = (
        monthly["close"].pct_change() * 100
    )

    # Only completed month
    monthly = monthly.shift(1)

    monthly = monthly.reindex(
        x.index,
        method="ffill"
    )

    x["monthly_close"] = monthly["close"]
    x["monthly_rsi"] = monthly["rsi14"]
    x["monthly_ema10"] = monthly["ema10"]
    x["monthly_ema15"] = monthly["ema15"]
    x["monthly_ema20"] = monthly["ema20"]
    x["monthly_momentum"] = monthly["momentum"]

    # Weekly RSI
    weekly = x.resample(
        "W-FRI"
    ).agg({
        "close": "last"
    })

    weekly["rsi14"] = rsi(
        weekly["close"],
        14
    )

    weekly = weekly.shift(1)

    weekly = weekly.reindex(
        x.index,
        method="ffill"
    )

    x["weekly_rsi"] = weekly["rsi14"]

    return x


# ============================================================
# STRATEGIES
# ============================================================

def strategy_signal(x, strategy):

    if strategy == 1:

        return (
            (x["weekly_rsi"] >= 50)
            &
            (x["monthly_rsi"] >= 50)
            &
            (
                x["monthly_close"]
                >=
                x["monthly_ema15"]
            )
            &
            (x["close"] >= 15)
            &
            (x["volume20"] >= 15000)
            &
            (
                (
                    x["monthly_close"]
                    -
                    x["monthly_ema10"]
                )
                /
                x["monthly_ema10"]
                <= 0.30
            )
            &
            (x["monthly_momentum"] >= 0)
        )

    if strategy == 2:

        ema_cross = (
            (x["ema20"] > x["ema50"])
            &
            (
                x["ema20"].shift(1)
                <=
                x["ema50"].shift(1)
            )
        )

        return (
            (x["close"] >= 15)
            &
            (x["volume20"] >= 10000)
            &
            (x["monthly_rsi"] >= 55)
            &
            (x["weekly_rsi"] >= 50)
            &
            (
                (
                    x["close"]
                    -
                    x["ema10"]
                )
                /
                x["ema10"]
                <= 0.04
            )
            &
            (x["ema50"] >= x["ema250"])
            &
            ema_cross
        )

    if strategy == 3:

        vwap20 = (
            (
                x["close"]
                *
                x["volume"]
            )
            .rolling(20)
            .sum()
            /
            x["volume"]
            .rolling(20)
            .sum()
        )

        return (
            (
                vwap20 *
                x["volume20"]
                >= 150000000
            )
            &
            (
                x["close"]
                >=
                x["ema200"]
            )
            &
            (x["weekly_rsi"] >= 40)
            &
            (
                x["close"]
                <=
                x["ema50"] * 1.04
            )
            &
            (
                x["close"]
                >=
                x["ema50"] * 0.96
            )
        )

    if strategy == 4:

        ema_cross = (
            (x["ema10"] > x["ema20"])
            &
            (
                x["ema10"].shift(1)
                <=
                x["ema20"].shift(1)
            )
        )

        reclaim = (
            (x["close"] > x["ema10"])
            &
            (
                x["close"].shift(1)
                <=
                x["ema10"].shift(1)
            )
        )

        return (
            (x["monthly_momentum"] >= 20)
            &
            (x["monthly_rsi"] >= 50)
            &
            (
                x["monthly_ema10"]
                >=
                x["monthly_ema20"]
            )
            &
            (x["volume30"] >= 50000)
            &
            (x["close"] >= 20)
            &
            (ema_cross | reclaim)
            &
            (
                x["close"]
                <=
                x["ema20"] * 1.03
            )
        )

    return pd.Series(
        False,
        index=x.index
    )


# ============================================================
# BACKTEST
# ============================================================

def run_backtest(
    df,
    signal,
    capital,
    risk_percent,
    stop_loss_percent,
    target_r,
    slippage
):

    x = add_features(
        df
    ).dropna()

    signal = signal.reindex(
        x.index
    ).fillna(False)

    equity = capital

    trades = []

    i = 0

    while i < len(x) - 1:

        if not bool(signal.iloc[i]):

            i += 1
            continue

        entry_index = i + 1

        entry = (
            float(
                x["close"].iloc[
                    entry_index
                ]
            )
            *
            (1 + slippage)
        )

        stop = (
            entry
            *
            (1 - stop_loss_percent)
        )

        risk_per_share = (
            entry - stop
        )

        if risk_per_share <= 0:

            i += 1
            continue

        quantity = int(
            (
                equity *
                risk_percent
            )
            /
            risk_per_share
        )

        if quantity < 1:

            i += 1
            continue

        target = (
            entry
            +
            target_r *
            risk_per_share
        )

        exit_index = None
        exit_price = None
        reason = ""

        for j in range(
            entry_index,
            len(x)
        ):

            low = float(
                x["low"].iloc[j]
            )

            high = float(
                x["high"].iloc[j]
            )

            # Stop first
            if low <= stop:

                exit_index = j

                exit_price = (
                    stop *
                    (1 - slippage)
                )

                reason = "Stop / Trail"

                break

            # Target
            if high >= target:

                exit_index = j

                exit_price = (
                    target *
                    (1 - slippage)
                )

                reason = (
                    f"{target_r:g}R Target"
                )

                break

            # Breakeven + EMA10 trail
            if high >= (
                entry +
                2 *
                risk_per_share
            ):

                stop = max(
                    stop,
                    entry
                )

                if not pd.isna(
                    x["ema10"].iloc[j]
                ):

                    stop = max(
                        stop,
                        float(
                            x["ema10"].iloc[j]
                        ) *
                        (1 - slippage)
                    )

        if exit_index is None:

            exit_index = len(x) - 1

            exit_price = (
                float(
                    x["close"].iloc[-1]
                )
                *
                (1 - slippage)
            )

            reason = "End of Test"

        pnl = (
            exit_price - entry
        ) * quantity

        equity += pnl

        r_multiple = (
            pnl /
            (
                risk_per_share *
                quantity
            )
        )

        trades.append({
            "Entry Date":
                x.index[
                    entry_index
                ].date(),

            "Exit Date":
                x.index[
                    exit_index
                ].date(),

            "Entry":
                entry,

            "Exit":
                exit_price,

            "Return %":
                (
                    exit_price /
                    entry -
                    1
                ) * 100,

            "R":
                r_multiple,

            "PnL ₹":
                pnl,

            "Holding Days":
                (
                    x.index[
                        exit_index
                    ]
                    -
                    x.index[
                        entry_index
                    ]
                ).days,

            "Reason":
                reason
        })

        i = exit_index + 1

    return (
        pd.DataFrame(trades),
        equity
    )


# ============================================================
# METRICS
# ============================================================

def calculate_metrics(trades):

    if trades.empty:
        return {}

    winners = trades[
        trades["R"] > 0
    ]

    losers = trades[
        trades["R"] < 0
    ]

    gross_profit = (
        winners["PnL ₹"].sum()
    )

    gross_loss = abs(
        losers["PnL ₹"].sum()
    )

    cumulative_r = (
        1 + trades["R"]
    ).cumprod()

    running_max = (
        cumulative_r.cummax()
    )

    drawdown = (
        cumulative_r /
        running_max -
        1
    )

    return {
        "Trades":
            len(trades),

        "Win %":
            len(winners) /
            len(trades) *
            100,

        "Average Win %":
            (
                winners["Return %"].mean()
                if len(winners)
                else 0
            ),

        "Average Loss %":
            (
                losers["Return %"].mean()
                if len(losers)
                else 0
            ),

        "Expectancy R":
            trades["R"].mean(),

        "Total R":
            trades["R"].sum(),

        "Profit Factor":
            (
                gross_profit /
                gross_loss
                if gross_loss
                else np.nan
            ),

        "Max Drawdown %":
            drawdown.min() * 100,

        "Winner Hold":
            (
                winners[
                    "Holding Days"
                ].mean()
                if len(winners)
                else 0
            ),

        "Loser Hold":
            (
                losers[
                    "Holding Days"
                ].mean()
                if len(losers)
                else 0
            )
    }


# ============================================================
# FUNDAMENTAL SCORE
# ============================================================

@st.cache_data(ttl=3600)
def get_company_data(ticker):

    company = yf.Ticker(
        ticker
    )

    try:
        info = company.info
    except Exception:
        info = {}

    try:
        news = company.news[:10]
    except Exception:
        news = []

    return info, news


def fundamental_score(info):

    score = 50

    flags = []

    fields = [
        "revenueGrowth",
        "earningsGrowth",
        "returnOnEquity",
        "returnOnAssets",
        "profitMargins",
        "operatingMargins"
    ]

    for field in fields:

        value = info.get(
            field
        )

        if (
            isinstance(
                value,
                (int, float)
            )
            and
            np.isfinite(value)
        ):

            if value > 0:
                score += 5
            else:
                score -= 5

    debt = info.get(
        "debtToEquity"
    )

    if (
        isinstance(
            debt,
            (int, float)
        )
        and
        np.isfinite(debt)
        and
        debt > 150
    ):

        score -= 15

        flags.append(
            "High debt/equity"
        )

    pe = info.get(
        "trailingPE"
    )

    if (
        isinstance(
            pe,
            (int, float)
        )
        and
        np.isfinite(pe)
        and
        pe > 80
    ):

        score -= 5

        flags.append(
            "High trailing P/E"
        )

    return (
        max(
            0,
            min(
                100,
                score
            )
        ),
        flags
    )


# ============================================================
# HEADER
# ============================================================

st.title(
    "🧠 Adaptive Trading Intelligence Lab"
)

st.caption(
    "Backtest • Walk-Forward • Forward Testing • "
    "Pattern Learning • Small/Micro-Cap Analysis • "
    "Custom Strategies"
)


# ============================================================
# TABS
# ============================================================

tabs = st.tabs([
    "🏠 Dashboard",
    "📊 Backtest",
    "🔬 Walk-Forward",
    "📡 Forward Test",
    "🧠 Pattern Learning",
    "🧪 Custom Strategy",
    "🏢 Small/Micro-Cap",
    "📒 Trade Journal"
])


# ============================================================
# DASHBOARD
# ============================================================

with tabs[0]:

    st.subheader(
        "System Overview"
    )

    c1, c2, c3, c4 = st.columns(4)

    c1.metric(
        "Default Risk",
        "1%"
    )

    c2.metric(
        "Default SL",
        "7%"
    )

    c3.metric(
        "Default Target",
        "3R"
    )

    c4.metric(
        "Learning",
        "Forward Validated"
    )

    st.info(
        "The objective is to improve robustness "
        "and decision quality, not guarantee profits."
    )

    st.markdown("""
### Research pipeline

**Market Data**
→ **Strategy**
→ **Technical Setup**
→ **Fundamentals / News**
→ **Risk Engine**
→ **Forward Test**
→ **Trade Journal**
→ **Learning**
→ **Walk-Forward Validation**
""")

    st.warning(
        "Never use future information to train a historical backtest."
    )


# ============================================================
# BACKTEST TAB
# ============================================================

with tabs[1]:

    st.subheader(
        "📊 Backtest Lab"
    )

    col1, col2, col3 = st.columns(3)

    universe_name = col1.selectbox(
        "Universe",
        [
            "Nifty 500",
            "Nifty Smallcap 100",
            "Nifty Smallcap 250",
            "Nifty Midcap 150",
            "Both Smallcap 100 + 250"
        ],
        key="bt_universe"
    )

    start_date = col2.date_input(
        "Start Date",
        date.today()
        -
        timedelta(days=730),
        key="bt_start"
    )

    end_date = col3.date_input(
        "End Date",
        date.today(),
        key
