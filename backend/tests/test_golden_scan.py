"""The regression harness: has anything moved what a scan selects or scores?

Everything about strategy behaviour is frozen. These tests re-run a fixed scan
over a committed fixture database and compare against a committed snapshot. If
one of them fails, either a scan rule changed - which is not allowed - or the
snapshot needs regenerating deliberately, with the diff reviewed as evidence.

They deliberately do NOT resolve "Nifty 500" over the network: an index whose
membership changes on NSE's review schedule would make every failure ambiguous
about whether the code or the universe moved.
"""
from __future__ import annotations

import math
import os

import pytest

from tests.golden.conftest_helpers import (
    FROZEN_COLUMNS, install_fixture_db, load_golden, run_reference_scan,
    run_signal_census)

TOLERANCE = 1e-9


@pytest.fixture(scope="module")
def fixture_engine():
    """Point the engine at the fixture, and put it back afterwards.

    install_fixture_db mutates process-global state (os.environ and
    core.DATA_DB). Leaving it pointed at the fixture would silently hand the
    golden database to every test that runs after this module.
    """
    from app.engine import core
    before_env = os.environ.get("DATA_DB")
    before_attr = core.DATA_DB
    # Inside the try: install_fixture_db repoints DATA_DB before it can fail,
    # so a failure outside would leave every later test module reading the
    # golden fixture instead of its own database.
    try:
        install_fixture_db()
        yield core
    finally:
        core.DATA_DB = before_attr
        if before_env is None:
            os.environ.pop("DATA_DB", None)
        else:
            os.environ["DATA_DB"] = before_env


def _diff(got, want, path=""):
    """Every difference, not just the first: one call should say how far the
    behaviour moved, not send you round the loop once per row."""
    out = []
    if isinstance(want, dict):
        if not isinstance(got, dict):
            return [f"{path}: expected an object, got {type(got).__name__}"]
        for k in sorted(set(want) | set(got)):
            if k not in got:
                out.append(f"{path}.{k}: missing")
            elif k not in want:
                out.append(f"{path}.{k}: unexpected ({got[k]!r})")
            else:
                out += _diff(got[k], want[k], f"{path}.{k}")
        return out
    if isinstance(want, list):
        if not isinstance(got, list):
            return [f"{path}: expected a list, got {type(got).__name__}"]
        if len(got) != len(want):
            out.append(f"{path}: {len(got)} rows, expected {len(want)}")
        for i, (g, w) in enumerate(zip(got, want)):
            out += _diff(g, w, f"{path}[{i}]")
        return out
    if isinstance(want, (int, float)) and isinstance(got, (int, float)) \
            and not isinstance(want, bool) and not isinstance(got, bool):
        if math.isnan(float(want)) and math.isnan(float(got)):
            return []
        if abs(float(got) - float(want)) > TOLERANCE:
            out.append(f"{path}: {got!r} != {want!r}")
        return out
    if got != want:
        out.append(f"{path}: {got!r} != {want!r}")
    return out


def test_the_scan_selects_and_scores_exactly_what_it_did_before(fixture_engine):
    got = run_reference_scan(fixture_engine)
    want = load_golden("scan_nifty500_all.json")
    diffs = _diff(got, want, "scan")
    assert not diffs, (
        f"{len(diffs)} difference(s) against the golden scan - a scan rule moved.\n"
        + "\n".join(diffs[:40])
        + ("\n..." if len(diffs) > 40 else ""))


def test_the_golden_scan_is_not_accidentally_empty():
    """A harness that passes on zero rows protects nothing, and an empty result
    is exactly what a broken fixture path produces."""
    want = load_golden("scan_nifty500_all.json")
    assert len(want) >= 5, f"only {len(want)} golden rows - the fixture is not scanning"
    assert {r["Strategy"] for r in want}, "no strategies represented"
    for row in want:
        assert set(row) == set(FROZEN_COLUMNS), "golden columns drifted from FROZEN_COLUMNS"


def test_the_ungated_scan_is_unchanged(fixture_engine):
    """With the entry filter off, the same scan exposes the strategy rules for
    every name the filter would have removed."""
    diffs = _diff(run_reference_scan(fixture_engine, apply_filter=False),
                  load_golden("scan_nifty500_ungated.json"), "ungated")
    assert not diffs, (f"{len(diffs)} difference(s) in the ungated scan.\n"
                       + "\n".join(diffs[:40]))


def test_every_strategy_fires_somewhere_in_the_census():
    """The single-date scan covers only S1, S3 and S5 on this fixture. If the
    census ever stops covering all five, the rules of the missing one are
    unprotected and this harness is quietly weaker than it looks."""
    census = load_golden("strategy_signal_census.json")
    seen = {k.split("|")[1] for k in census}
    from app.engine import core
    from tests.golden.conftest_helpers import GOLDEN_STRATEGIES
    expected = {f"S{s}" for s in GOLDEN_STRATEGIES}
    assert seen == expected, f"missing from the census: {sorted(expected - seen)}"
    assert sum(v["count"] for v in census.values()) > 20000


def test_entry_rules_are_unchanged_across_the_whole_history(fixture_engine):
    """The strongest check here: every signal each strategy fires on every bar
    of the fixture, not just the latest one."""
    diffs = _diff(run_signal_census(fixture_engine),
                  load_golden("strategy_signal_census.json"), "census")
    assert not diffs, (
        f"{len(diffs)} difference(s) - an entry rule moved.\n"
        + "\n".join(diffs[:40]) + ("\n..." if len(diffs) > 40 else ""))


def test_the_scan_is_deterministic(fixture_engine):
    """Two runs over the same candles must agree, or the golden can never."""
    assert not _diff(run_reference_scan(fixture_engine),
                     run_reference_scan(fixture_engine), "rerun")


@pytest.mark.parametrize("name,call", [
    ("forward_summary", lambda f: f.summary()),
    ("forward_results", lambda f: f.results()),
    ("forward_positions", lambda f: f.positions(use_live=False)),
    ("scanner_signals", lambda f: f.signals(limit=5000)),
])
def test_forward_endpoints_return_what_they_did_before(fixture_engine, name, call):
    from tests.golden.generate import _clean
    from app.services import forward
    got = _clean(call(forward))
    diffs = _diff(got, load_golden(f"{name}.json"), name)
    assert not diffs, (f"{len(diffs)} difference(s) in {name}.\n"
                       + "\n".join(diffs[:30]))
