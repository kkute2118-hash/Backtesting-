"""The background S1-S3 pass must never cost the daily job its main result."""

from __future__ import annotations

import pytest

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def test_the_shadow_pass_scans_s1_s3_only_and_never_raises(monkeypatch):
    import daily_job
    seen = {}

    def fake_scan(tickers, strategies, min_score, session_date=None, data=None):
        seen["strategies"] = strategies
        raise RuntimeError("scan blew up")

    monkeypatch.setattr(daily_job, "step_scan", fake_scan)
    monkeypatch.setattr(daily_job.core, "SHADOW_STRATEGIES", (1, 2, 3))
    assert daily_job.step_shadow(["A"], 71, session_date="2026-09-25") == 0
    assert seen["strategies"] == [1, 2, 3]


def test_with_nothing_retired_the_shadow_pass_does_nothing(monkeypatch):
    import daily_job
    monkeypatch.setattr(daily_job.core, "SHADOW_STRATEGIES", ())
    monkeypatch.setattr(daily_job, "step_scan", lambda *a, **k: pytest.fail("scanned"))
    assert daily_job.step_shadow(["A"], 71) == 0
