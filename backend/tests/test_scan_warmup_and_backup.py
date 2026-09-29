"""Scan-feature warm-up and keeping the feature cache out of backups.

The warm-up exists so a scan straight after a sync takes the fast path; it is
only worth anything if the snapshots it writes are the ones the scan reuses.
The backup half guards the NSE Top 2000: ~2,000 pickled feature frames are
~380 MB, and if they ride along the learning backup - the web host's only copy
of the forward tests - becomes too big to store.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy as np
import pandas as pd

from app.engine import core


def _frame(n=320, seed=0):
    rng = np.random.default_rng(seed)
    close = 100 + np.cumsum(rng.normal(0, 1, n))
    idx = pd.bdate_range(end=pd.Timestamp(core.market_today()) - pd.Timedelta(days=1), periods=n)
    return pd.DataFrame({"open": close, "high": close + 1, "low": close - 1,
                         "close": close, "volume": rng.integers(1e5, 1e6, n)}, index=idx)


def test_feature_snapshots_are_rebuildable():
    assert "feature_snapshots" in core.REBUILDABLE_TABLES


def test_derived_cache_is_stripped_from_a_backup_copy(tmp_path):
    path = tmp_path / "copy.sqlite3"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE feature_snapshots(symbol TEXT, payload BLOB)")
    con.execute("CREATE TABLE forward_tests(id INTEGER)")
    con.executemany("INSERT INTO feature_snapshots VALUES (?,?)",
                    [(f"S{i}", b"x" * 50_000) for i in range(40)])
    con.execute("INSERT INTO forward_tests VALUES (1)")
    con.commit()
    con.close()
    before = path.stat().st_size

    core._drop_derived_cache(str(path))

    con = sqlite3.connect(path)
    assert con.execute("SELECT COUNT(*) FROM feature_snapshots").fetchone()[0] == 0
    assert con.execute("SELECT COUNT(*) FROM forward_tests").fetchone()[0] == 1
    con.close()
    assert path.stat().st_size < before


def test_the_dhan_token_never_leaves_in_a_backup(tmp_path, monkeypatch):
    """The backup branch is readable by anyone who can read the repository,
    and a Dhan access token can place orders. Both backup paths must drop it."""
    import daily_job
    path = tmp_path / "db.sqlite3"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE dhan_token_cache(id INTEGER, access_token TEXT, issued_at TEXT)")
    con.execute("INSERT INTO dhan_token_cache VALUES (1, 'eyJsecret', '2026-09-28')")
    con.execute("CREATE TABLE forward_tests(id INTEGER)")
    con.execute("INSERT INTO forward_tests VALUES (1)")
    con.commit()
    con.close()

    copy = tmp_path / "copy.sqlite3"
    copy.write_bytes(path.read_bytes())
    core._drop_derived_cache(str(copy))                       # the API's backup path
    assert b"eyJsecret" not in copy.read_bytes()

    monkeypatch.setattr(core, "DATA_DB", str(path))           # the scheduled job's path
    stage = tmp_path / "stage.gz"
    daily_job._stage_backup(str(stage))
    import gzip
    raw = gzip.open(stage).read()
    assert b"eyJsecret" not in raw and b"forward_tests" in raw


def test_warm_up_writes_the_snapshots_a_scan_reuses(monkeypatch):
    frames = {"AAA.NS": _frame(seed=1), "BBB.NS": _frame(seed=2)}
    monkeypatch.setattr(core, "load_scan_dataset",
                        lambda tickers, **_: {t: frames[t] for t in tickers if t in frames})
    saved = {}
    monkeypatch.setattr(core, "_save_feature_snapshot",
                        lambda symbol, x: saved.__setitem__(symbol, x))
    monkeypatch.setattr(core, "_load_feature_snapshot", lambda symbol: saved.get(symbol))
    if hasattr(core.features_fast, "clear"):
        core.features_fast.clear()

    progress = []
    warmed = core.warm_feature_snapshots(["AAA.NS", "BBB.NS", "MISSING.NS"],
                                         progress_cb=progress.append, chunk=2)
    assert warmed == 2
    assert set(saved) == {"AAA.NS", "BBB.NS"}
    assert progress and progress[-1] == 1.0
    # The scan passes the same frame; the stored snapshot must count as a match.
    assert core._snapshot_matches(saved["AAA.NS"], frames["AAA.NS"])


def test_a_backup_keeps_only_the_newest_capture_run(tmp_path, monkeypatch):
    """Old research capture runs are dropped from both backup paths, which is
    what keeps the backup under GitHub's 100 MB file limit. The live database
    keeps them."""
    import daily_job
    path = tmp_path / "db.sqlite3"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE raw_signal_fingerprints(id INTEGER, run_id INTEGER, ticker TEXT)")
    con.executemany("INSERT INTO raw_signal_fingerprints VALUES (?,?,?)",
                    [(i, 1 + i % 3, f"OLDRUN{i}" if i % 3 != 2 else f"NEWRUN{i}") for i in range(30)])
    con.execute("CREATE TABLE forward_tests(id INTEGER)")
    con.execute("INSERT INTO forward_tests VALUES (1)")
    con.commit()
    con.close()

    copy = tmp_path / "copy.sqlite3"
    copy.write_bytes(path.read_bytes())
    core._drop_derived_cache(str(copy))
    con = sqlite3.connect(copy)
    assert {r[0] for r in con.execute("SELECT DISTINCT run_id FROM raw_signal_fingerprints")} == {3}
    assert con.execute("SELECT COUNT(*) FROM forward_tests").fetchone()[0] == 1
    con.close()

    monkeypatch.setattr(core, "DATA_DB", str(path))
    stage = tmp_path / "stage.gz"
    daily_job._stage_backup(str(stage))
    import gzip
    raw = gzip.open(stage).read()
    assert b"NEWRUN" in raw and b"OLDRUN" not in raw
    live = sqlite3.connect(path)
    assert live.execute("SELECT COUNT(*) FROM raw_signal_fingerprints").fetchone()[0] == 30
    live.close()
