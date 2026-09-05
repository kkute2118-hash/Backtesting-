"""Test fixtures.

Every test runs against a throwaway SQLite file. ``DATA_DB`` is set before
``app.engine.core`` is imported anywhere, because the engine resolves its
database path at import time - importing first and pointing it somewhere else
afterwards would write into the developer's real candle store.
"""

from __future__ import annotations

import os
import tempfile
from datetime import date, timedelta

import numpy as np
import pytest

_TMP = tempfile.mkdtemp(prefix="ati-tests-")
os.environ["DATA_DB"] = os.path.join(_TMP, "test_market_data.sqlite3")
os.environ.setdefault("CORS_ORIGINS", "http://localhost:3000")
# Guarantee no test can reach a provider or a backup repository.
for _var in ("DHAN_CLIENT_ID", "DHAN_ACCESS_TOKEN", "DHAN_PIN", "DHAN_TOTP_SECRET",
             "TWELVEDATA_API_KEY", "ANTHROPIC_API_KEY",
             "GITHUB_TOKEN", "GH_TOKEN", "GH_BACKUP_TOKEN",
             "GITHUB_REPO", "GH_REPO", "DB_BACKUP_REPO"):
    os.environ.pop(_var, None)

import pandas as pd  # noqa: E402


def synthetic_ohlcv(seed: int, bars: int = 700, start: float = 100.0,
                    drift: float = 0.0008, volatility: float = 0.015,
                    base_volume: float = 500_000) -> pd.DataFrame:
    """A deterministic, plausible daily OHLCV series.

    Synthetic on purpose: these tests pin the *maths*, and a fixture that
    depended on live Dhan data would fail for reasons that have nothing to do
    with the code under test. It is never presented to a user as market data.
    """
    rng = np.random.default_rng(seed)
    returns = rng.normal(drift, volatility, bars)
    close = start * np.exp(np.cumsum(returns))
    spread = np.abs(rng.normal(0.008, 0.004, bars))
    high = close * (1 + spread)
    low = close * (1 - spread)
    open_ = np.concatenate([[start], close[:-1]]) * (1 + rng.normal(0, 0.003, bars))
    open_ = np.clip(open_, low, high)
    volume = base_volume * np.exp(rng.normal(0, 0.35, bars))

    index = pd.bdate_range(end=date.today() - timedelta(days=1), periods=bars)
    return pd.DataFrame(
        {"open": open_, "high": high, "low": low, "close": close, "volume": volume},
        index=index,
    )


@pytest.fixture(scope="session")
def frames() -> dict[str, pd.DataFrame]:
    """A small fixed universe with different characters (trend, chop, thin)."""
    return {
        "TRENDUP": synthetic_ohlcv(seed=1, drift=0.0016, volatility=0.014),
        "CHOPPY": synthetic_ohlcv(seed=2, drift=0.0000, volatility=0.022),
        "DOWNTREND": synthetic_ohlcv(seed=3, drift=-0.0012, volatility=0.016),
        "THIN": synthetic_ohlcv(seed=4, drift=0.0005, volatility=0.030,
                                base_volume=4_000),
    }


@pytest.fixture(scope="session")
def seeded_db(frames):
    """Load the fixture frames into the engine's candle store."""
    from app.engine import core

    con = core._db()
    try:
        for symbol, df in frames.items():
            core._save(con, symbol, df)
        con.commit()
    finally:
        con.close()
    return core.DATA_DB


@pytest.fixture()
def client(seeded_db):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as test_client:
        yield test_client
