"""Run the script-shaped regression tests under pytest.

Each script in ``tests/regression/`` reproduces a specific incident — a lost
database, a mishandled Dhan error code, a universe picker that silently topped
out at 500 names. They are kept script-shaped because the exact conditions are
the point, and rewriting them into pytest idiom risks losing the detail that
caught the bug. Running them as subprocesses also gives each one a clean
interpreter, which several of them need: they set ``DATA_DB`` and
``GTF_DATA_DIR`` before importing the engine, which resolves its database path
at import time.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REGRESSION_DIR = Path(__file__).parent / "regression"
SCRIPTS = sorted(path.name for path in REGRESSION_DIR.glob("test_*.py"))


@pytest.mark.parametrize("script", SCRIPTS)
def test_regression_script(script: str) -> None:
    env = dict(os.environ)
    # Each script picks its own database location; make sure this suite's
    # DATA_DB (set by conftest) does not override the one under test.
    env.pop("DATA_DB", None)
    env["GTF_DATA_DIR"] = tempfile.mkdtemp(prefix="ati-regression-")

    result = subprocess.run(
        [sys.executable, str(REGRESSION_DIR / script)],
        capture_output=True, text=True, env=env, timeout=600,
    )
    if result.returncode != 0:
        pytest.fail(f"{script} failed:\n{result.stdout[-4000:]}\n{result.stderr[-2000:]}")
