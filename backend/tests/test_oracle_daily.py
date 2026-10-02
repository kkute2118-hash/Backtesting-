"""The Oracle server's daily work writes readable reports and nothing else."""

import json

from app.engine import core
from app.tasks import oracle_daily


def test_scan_and_research_write_reports(seeded_db, tmp_path, monkeypatch):
    monkeypatch.setattr(oracle_daily, "REPORT_DIR", tmp_path)
    persist = core._persist_raw_fingerprints

    oracle_daily.scan()
    scan = json.loads((tmp_path / "scan-latest.json").read_text())
    assert scan["kind"] == "scan"
    assert scan["stocks_scanned"] > 0
    assert set(scan["per_strategy"]) == {core.strategy_label_for(s) for s in core.DEFAULT_STRATEGIES}

    oracle_daily.research()
    research = json.loads((tmp_path / "research-latest.json").read_text())
    assert research["kind"] == "research"
    assert set(research["strategies"]) <= set(oracle_daily.ALL)
    assert core._persist_raw_fingerprints is persist        # restored after the run

    assert len(list(tmp_path.glob("scan-20*.json"))) == 1
    assert len(list(tmp_path.glob("research-20*.json"))) == 1
