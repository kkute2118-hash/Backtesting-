"""The scan universe: real shares only, and no more than the label promises.

"NSE All Cash (~2000)" used to resolve to 9,922 names. 4,325 of them were
Sovereign Gold Bonds and only 2,688 were shares, because Dhan labels every one
of those SEM_INSTRUMENT_NAME = EQUITY and the distinction lives in a series
column the engine never read (research/trader_methodology/UNIVERSE_AUDIT.md).

Four things have to keep holding, and each has already been wrong once:

  * the series filter runs at all, so gold bonds and debt stay out;
  * it also removes the SME board, which the old suffix check missed 464 times
    out of 466 because SME is marked in the series, not the symbol;
  * the cap ranks by liquidity and not by alphabet;
  * a symbol with three stored bars cannot be the most liquid stock on the
    exchange. It was: one bar from 2024 on a huge volume put IRBIT above
    HDFCBANK the first time this ran.
"""
from __future__ import annotations

import pandas as pd
import pytest

from app.engine import core


@pytest.fixture
def master(monkeypatch):
    """A stub instrument master: 30 EQ, 40 SG, 10 SM, 5 N0."""
    rows = {}
    series = {}
    for i in range(30):
        rows[f"EQ{i:03d}"] = str(i); series[f"EQ{i:03d}"] = "EQ"
    for i in range(40):
        rows[f"SGB{i:03d}"] = str(100 + i); series[f"SGB{i:03d}"] = "SG"
    for i in range(10):
        rows[f"SME{i:03d}"] = str(200 + i); series[f"SME{i:03d}"] = "SM"
    for i in range(5):
        rows[f"NCD{i:03d}"] = str(300 + i); series[f"NCD{i:03d}"] = "N0"
    monkeypatch.setattr(core, "dhan_map", lambda: rows)
    monkeypatch.setattr(core, "dhan_series_map", lambda: series)
    return rows, series


def test_only_real_equity_series_survives(master, monkeypatch):
    monkeypatch.setattr(core, "stored_turnover_cr", lambda symbols=None, **k: {})
    u = core.nse_liquid_universe()
    assert len(u) == 30
    assert all(t.startswith("EQ") for t in u)
    assert not any("SGB" in t or "SME" in t or "NCD" in t for t in u)


def test_the_sme_board_goes_even_though_no_symbol_ends_in_sm(master, monkeypatch):
    # The old check was `not t.endswith("SM.NS")`. None of these would trip it.
    _, series = master
    assert not any(s.endswith("SM") for s in series if series[s] == "SM")
    monkeypatch.setattr(core, "stored_turnover_cr", lambda symbols=None, **k: {})
    assert not any("SME" in t for t in core.nse_liquid_universe())


def test_the_cap_keeps_the_liquid_names_not_the_alphabetical_ones(master, monkeypatch):
    # EQ029 is the most liquid and last alphabetically; it must survive a cap
    # of 3, and EQ000 - first alphabetically, least liquid - must not.
    monkeypatch.setattr(core, "stored_turnover_cr",
                        lambda symbols=None, **k: {f"EQ{i:03d}": float(i) for i in range(30)})
    u = core.nse_liquid_universe(cap=3)
    assert set(u) == {"EQ029.NS", "EQ028.NS", "EQ027.NS"}


def test_an_unranked_name_sorts_below_every_ranked_one(master, monkeypatch):
    # Only two names have stored turnover. With a cap of 4 they must both be
    # in, and the other two slots filled by whatever is left - never the other
    # way round.
    monkeypatch.setattr(core, "stored_turnover_cr",
                        lambda symbols=None, **k: {"EQ020": 5.0, "EQ021": 9.0})
    u = core.nse_liquid_universe(cap=4)
    assert "EQ020.NS" in u and "EQ021.NS" in u
    assert len(u) == 4


def test_an_empty_store_does_not_truncate_to_an_arbitrary_two_thousand(master, monkeypatch):
    # Nothing to rank on means no cap. Truncating here would hide names from
    # the build job that is supposed to download them.
    monkeypatch.setattr(core, "stored_turnover_cr", lambda symbols=None, **k: {})
    assert len(core.nse_liquid_universe(cap=5)) == 30


def test_a_master_without_a_series_column_falls_back_and_does_not_empty(monkeypatch):
    monkeypatch.setattr(core, "dhan_map", lambda: {"AAA": "1", "BBBSM": "2"})
    monkeypatch.setattr(core, "dhan_series_map", lambda: {})
    monkeypatch.setattr(core, "stored_turnover_cr", lambda symbols=None, **k: {})
    u = core.nse_liquid_universe()
    assert u == ["AAA.NS"]          # old suffix check still applies when blind


def _store(tmp_path, rows):
    import sqlite3
    p = tmp_path / "market_data.sqlite3"
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE candles(symbol TEXT, dt TEXT, open REAL, high REAL, "
                "low REAL, close REAL, volume REAL)")
    con.executemany("INSERT INTO candles VALUES(?,?,?,?,?,?,?)", rows)
    con.commit(); con.close()
    return p


def test_a_symbol_with_three_bars_is_not_the_most_liquid_stock(tmp_path, monkeypatch):
    # The IRBIT case, exactly: one enormous day against a name with a real
    # history at a tenth the turnover.
    days = pd.bdate_range("2026-01-01", periods=40).strftime("%Y-%m-%d")
    rows = [("REAL", d, 1, 1, 1, 100.0, 1_000_000.0) for d in days]
    rows += [("SPARSE", d, 1, 1, 1, 200.0, 500_000_000.0) for d in days[-3:]]
    p = _store(tmp_path, rows)

    import sqlite3
    monkeypatch.setattr(core, "_db", lambda: sqlite3.connect(p))
    got = core.stored_turnover_cr()
    assert "REAL" in got
    assert "SPARSE" not in got, "3 bars is not a 20-day turnover measurement"


def test_a_delisted_name_does_not_hold_a_slot(tmp_path, monkeypatch):
    old = pd.bdate_range("2024-01-01", periods=30).strftime("%Y-%m-%d")
    new = pd.bdate_range("2026-01-01", periods=30).strftime("%Y-%m-%d")
    rows = [("GONE", d, 1, 1, 1, 100.0, 9_000_000.0) for d in old]
    rows += [("LIVE", d, 1, 1, 1, 100.0, 1_000_000.0) for d in new]
    p = _store(tmp_path, rows)

    import sqlite3
    monkeypatch.setattr(core, "_db", lambda: sqlite3.connect(p))
    got = core.stored_turnover_cr()
    assert "LIVE" in got
    assert "GONE" not in got, "its newest bar is two years behind the store"


def test_turnover_is_a_median_so_one_block_trade_cannot_carry_a_name(tmp_path, monkeypatch):
    days = pd.bdate_range("2026-01-01", periods=25).strftime("%Y-%m-%d")
    rows = [("QUIET", d, 1, 1, 1, 100.0, 100_000.0) for d in days[:-1]]
    rows += [("QUIET", days[-1], 1, 1, 1, 100.0, 900_000_000.0)]
    p = _store(tmp_path, rows)

    import sqlite3
    monkeypatch.setattr(core, "_db", lambda: sqlite3.connect(p))
    got = core.stored_turnover_cr()
    assert got["QUIET"] == pytest.approx(100.0 * 100_000 / 1e7)
