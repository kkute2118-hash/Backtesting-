"""Regenerate every golden snapshot from the committed fixture database.

    python backend/tests/golden/generate.py

Run this ONLY when a change is intended to move the output, and review the
resulting diff - that diff is the record of what the change did to scan
behaviour. A green golden test after an accidental regeneration proves nothing.
"""
from __future__ import annotations

import os, sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))

from tests.golden.conftest_helpers import (  # noqa: E402
    install_fixture_db, run_reference_scan, run_signal_census, save_golden, _plain)


def main() -> None:
    install_fixture_db()
    from app.engine import core
    from app.services import forward

    scan = run_reference_scan(core)
    save_golden("scan_nifty500_all.json", scan)
    print(f"scan_nifty500_all.json           {len(scan):>5} rows")

    ungated = run_reference_scan(core, apply_filter=False)
    save_golden("scan_nifty500_ungated.json", ungated)
    print(f"scan_nifty500_ungated.json       {len(ungated):>5} rows")

    census = run_signal_census(core)
    save_golden("strategy_signal_census.json", census)
    total = sum(v["count"] for v in census.values())
    per = {}
    for key, v in census.items():
        per[key.split("|")[1]] = per.get(key.split("|")[1], 0) + v["count"]
    print(f"strategy_signal_census.json      {total:>5} signals  {per}")

    for name, fn in (("forward_summary", forward.summary),
                     ("forward_results", forward.results),
                     ("forward_positions", lambda: forward.positions(use_live=False)),
                     ("scanner_signals", lambda: forward.signals(limit=5000))):
        payload = _clean(fn())
        save_golden(f"{name}.json", payload)
        n = len(payload.get("rows", [])) if isinstance(payload, dict) else len(payload)
        print(f"{name + '.json':<33}{n:>5} rows")


def _clean(obj):
    """Drop wall-clock fields; they change every run and mean nothing here."""
    volatile = {"created_at", "updated_at", "observed_at", "generated_at", "as_of"}
    if isinstance(obj, dict):
        return {k: _clean(v) for k, v in obj.items() if k not in volatile}
    if isinstance(obj, list):
        return [_clean(v) for v in obj]
    return _plain(obj)


if __name__ == "__main__":
    main()
