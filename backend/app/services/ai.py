"""The Anthropic-backed panels: system coach, trade debate, learning panel.

Every one of these is optional and gated on ANTHROPIC_API_KEY. They read the
engine's own accumulated evidence and return written analysis; none of them can
create, modify or approve a signal - the strategy rules stay authoritative, and
an LLM verdict is presented as an opinion on candidates the scanner already
produced.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from app.core.errors import ApiError, NotConfigured
from app.engine import core
from app.services import jobs
from app.services.jobs import JobHandle
from app.services.serialization import clean_value, frame_to_records

COACH_KIND = "ai_coach"
DEBATE_KIND = "ai_debate"
PANEL_KIND = "ai_learning_panel"


def _require_anthropic() -> None:
    if not core._anthropic_configured():
        raise NotConfigured(
            "The AI panels need ANTHROPIC_API_KEY in the backend environment. "
            "Everything else in the application works without it."
        )


def coach() -> dict[str, Any]:
    _require_anthropic()

    def work(handle: JobHandle) -> dict[str, Any]:
        handle.progress(0.2, "Building the evidence payload")
        report, error = core.run_strategy_coach()
        if error:
            raise ApiError(error)
        handle.progress(0.9, "Saving the report")
        try:
            core.save_coach_report(report)
        except Exception:
            pass
        return {"report": report, "rows": [], "stats": {}}

    return jobs.registry.submit(COACH_KIND, "AI system coach", work).to_public()


def coach_history(limit: int = 10) -> dict[str, Any]:
    core.ensure_coach_table()
    con = core._db()
    try:
        df = pd.read_sql_query(
            "SELECT * FROM coach_reports ORDER BY id DESC LIMIT ?", con, params=(int(limit),))
    finally:
        con.close()
    return {"rows": frame_to_records(df)}


def debate(rows: list[dict[str, Any]], *, capital: float | None = None,
           max_slots: int | None = None, risk_pct: float | None = None,
           target_count: int = 5, max_candidates: int = 15) -> dict[str, Any]:
    _require_anthropic()
    if not rows:
        raise ApiError("Run a scan first — the debate panel argues over real candidates.")
    frame = pd.DataFrame(rows)

    def work(handle: JobHandle) -> dict[str, Any]:
        handle.progress(0.1, "Building the shortlist")
        result = core.run_trade_debate_panel(
            frame, capital=capital, max_slots=max_slots, risk_pct=risk_pct,
            target_count=target_count, max_candidates=max_candidates)
        if isinstance(result, dict) and result.get("error"):
            raise ApiError(result["error"])
        payload: dict[str, Any] = {}
        for key, value in (result or {}).items():
            payload[str(key)] = (frame_to_records(value) if isinstance(value, pd.DataFrame)
                                 else clean_value(value))
        return {"panel": payload, "rows": [], "stats": {}}

    return jobs.registry.submit(DEBATE_KIND, "AI trade debate panel", work,
                                request={"candidates": len(frame)}).to_public()


def learning_panel() -> dict[str, Any]:
    _require_anthropic()

    def work(handle: JobHandle) -> dict[str, Any]:
        handle.progress(0.15, "Assembling the learning payload")
        result = core.run_system_learning_panel()
        if isinstance(result, dict) and result.get("error"):
            raise ApiError(result["error"])
        handle.progress(0.9, "Saving the panel run")
        try:
            core.save_learning_panel_run(result)
        except Exception:
            pass
        payload: dict[str, Any] = {}
        for key, value in (result or {}).items():
            payload[str(key)] = (frame_to_records(value) if isinstance(value, pd.DataFrame)
                                 else clean_value(value))
        return {"panel": payload, "rows": [], "stats": {}}

    return jobs.registry.submit(PANEL_KIND, "System learning panel", work).to_public()


def panel_history(limit: int = 10) -> dict[str, Any]:
    core.ensure_learning_panel_table()
    con = core._db()
    try:
        df = pd.read_sql_query(
            "SELECT * FROM learning_panel_runs ORDER BY id DESC LIMIT ?",
            con, params=(int(limit),))
    finally:
        con.close()
    return {"rows": frame_to_records(df)}
