"""API behaviour: the envelope, the job lifecycle and the product endpoints."""

from __future__ import annotations

import time

import pytest

from app.engine import core


def _wait(client, job_id: str, timeout: float = 120.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        payload = client.get(f"/api/v1/jobs/{job_id}").json()
        if payload["status"] in {"succeeded", "failed", "cancelled"}:
            return payload
        time.sleep(0.15)
    raise AssertionError(f"Job {job_id} did not finish within {timeout}s")


def test_health_reports_the_engine_and_its_database(client):
    body = client.get("/api/v1/health").json()
    assert body["status"] == "ok"
    assert body["database"]["ok"] is True
    assert body["engine_version"]


def test_config_never_returns_a_credential(client):
    body = client.get("/api/v1/config").json()
    serialised = str(body)
    for secret in ("DHAN_ACCESS_TOKEN", "DHAN_PIN", "ANTHROPIC_API_KEY", "sk-"):
        assert secret not in serialised
    assert body["providers"]["dhan"]["configured"] is False


def test_missing_credentials_answer_503_not_500(client):
    """A missing key is the user's configuration problem, and the message has
    to say which key and where to put it."""
    response = client.post("/api/v1/ai/coach")
    assert response.status_code == 503
    body = response.json()["error"]
    assert body["code"] == "not_configured"
    assert "ANTHROPIC_API_KEY" in body["message"]


def test_unknown_universe_is_rejected_with_its_name(client):
    response = client.post("/api/v1/scanner/runs",
                           json={"universes": ["Nifty 9000"], "strategies": [1]})
    assert response.status_code == 400
    assert "Nifty 9000" in response.json()["error"]["message"]


def test_unknown_strategy_is_rejected(client):
    response = client.post("/api/v1/scanner/runs",
                           json={"universes": ["Nifty 500"], "strategies": [7]})
    assert response.status_code == 422


def test_unknown_job_is_a_404(client):
    assert client.get("/api/v1/jobs/does-not-exist").status_code == 404


# --------------------------------------------------------------------------- #
# scan lifecycle, end to end, over the seeded fixture universe
# --------------------------------------------------------------------------- #
@pytest.fixture()
def scan_run(client, monkeypatch, frames):
    """Run a real scan against the fixture stocks, with no network access."""
    from app.services import scanner, universe

    monkeypatch.setattr(universe, "resolve", lambda names: sorted(frames))
    monkeypatch.setattr(scanner, "resolve", lambda names: sorted(frames))

    started = client.post("/api/v1/scanner/runs",
                          json={"universes": ["Nifty 500"], "strategies": [1, 2, 3, 4],
                                "min_score": 0})
    assert started.status_code == 202
    job = _wait(client, started.json()["id"])
    assert job["status"] == "succeeded", job["error"]
    return started.json()["id"]


def test_scan_produces_a_readable_run(client, scan_run):
    run = client.get(f"/api/v1/scanner/runs/{scan_run}").json()
    assert run["status"] == "succeeded"
    stats = run["stats"]
    assert stats["loaded"] >= 1
    assert stats["regime"]
    assert {"strategy", "signals", "qualified"} <= set(stats["per_strategy"][0])
    for row in run["rows"]:
        assert row["Ticker"]
        assert row["Score"] is not None


def test_scan_results_are_json_safe(client, scan_run):
    """NaN would serialise as a bare NaN token and break JSON.parse."""
    raw = client.get(f"/api/v1/scanner/runs/{scan_run}").text
    assert "NaN" not in raw and "Infinity" not in raw


def test_result_filters_never_re_run_the_engine(client, scan_run):
    body = client.post(f"/api/v1/scanner/runs/{scan_run}/results",
                       json={"min_score": 101, "limit": 50}).json()
    assert body["filtered"] == 0
    assert body["total"] == len(client.get(f"/api/v1/scanner/runs/{scan_run}").json()["rows"])

    everything = client.post(f"/api/v1/scanner/runs/{scan_run}/results",
                             json={"limit": 500}).json()
    assert everything["filtered"] == everything["total"]


def test_run_appears_in_history(client, scan_run):
    runs = client.get("/api/v1/scanner/runs").json()
    assert any(r["id"] == scan_run for r in runs)


# --------------------------------------------------------------------------- #
# stock detail
# --------------------------------------------------------------------------- #
def test_stock_detail_and_chart(client):
    quote = client.get("/api/v1/stocks/TRENDUP").json()
    assert quote["symbol"] == "TRENDUP"
    assert quote["price"] > 0
    assert quote["price_source"] == "STORED CLOSE"

    history = client.get("/api/v1/stocks/TRENDUP/history?timeframe=6M").json()
    assert 100 < len(history["candles"]) <= 140
    assert {"time", "open", "high", "low", "close"} <= set(history["candles"][0])
    assert "ema20" in history["overlays"]


def test_condition_matrix_explains_the_verdict(client):
    body = client.get("/api/v1/stocks/TRENDUP/conditions").json()
    assert len(body["strategies"]) == len(core.DEFAULT_STRATEGIES)
    for entry in body["strategies"]:
        assert entry["total"] == len(entry["conditions"])
        assert entry["passed"] == sum(1 for c in entry["conditions"] if c["passed"])
        # The signal is exactly "every condition passed".
        assert entry["signal"] is (entry["passed"] == entry["total"])


def test_unknown_symbol_is_a_404_with_advice(client):
    response = client.get("/api/v1/stocks/NOSUCHSTOCK")
    assert response.status_code == 404
    assert "NOSUCHSTOCK" in response.json()["error"]["message"]


def test_safety_report_flags_a_thin_stock(client):
    thin = client.get("/api/v1/stocks/THIN/safety").json()
    liquid = client.get("/api/v1/stocks/TRENDUP/safety").json()
    assert thin["score"] < liquid["score"]
    assert any("liquidity" in f.lower() or "traded value" in f.lower()
               for f in thin["flags"])


# --------------------------------------------------------------------------- #
# watchlists and presets
# --------------------------------------------------------------------------- #
def test_watchlist_round_trip(client):
    created = client.post("/api/v1/watchlists", json={"name": "Round trip"}).json()
    list_id = created["id"]

    added = client.post(f"/api/v1/watchlists/{list_id}/symbols",
                        json={"symbols": ["TRENDUP", "trendup", "CHOPPY.NS"]}).json()
    # Case and the .NS suffix are normalised, so a symbol cannot be added twice.
    assert sorted(i["symbol"] for i in added["items"]) == ["CHOPPY", "TRENDUP"]
    assert added["items"][0]["price"] is not None

    client.delete(f"/api/v1/watchlists/{list_id}/symbols/TRENDUP")
    assert client.get(f"/api/v1/watchlists/{list_id}").json()["count"] == 1

    assert client.delete(f"/api/v1/watchlists/{list_id}").status_code == 204
    assert client.get(f"/api/v1/watchlists/{list_id}").status_code == 404


def test_duplicate_watchlist_name_is_rejected(client):
    client.post("/api/v1/watchlists", json={"name": "Unique"})
    response = client.post("/api/v1/watchlists", json={"name": "Unique"})
    assert response.status_code == 400
    assert "already exists" in response.json()["error"]["message"]


def test_builtin_presets_are_shipped_and_protected(client):
    presets = client.get("/api/v1/presets").json()["presets"]
    builtin = [p for p in presets if p["builtin"]]
    assert len(builtin) >= 3
    for preset in builtin:
        # Every shipped preset must be runnable as-is.
        assert preset["config"]["universes"]
        assert preset["config"]["strategies"]
    response = client.delete(f"/api/v1/presets/{builtin[0]['id']}")
    assert response.status_code == 400


def test_preset_validation_rejects_options_the_engine_has_no_screen_for(client):
    response = client.post("/api/v1/presets", json={
        "name": "Bad", "config": {"universes": ["Nifty 500"], "strategies": [9]}})
    assert response.status_code == 400
    assert "strategies 1-5" in response.json()["error"]["message"]

    response = client.post("/api/v1/presets", json={
        "name": "Bad", "config": {"universes": ["Made Up Index"], "strategies": [1]}})
    assert response.status_code == 400
    assert "Made Up Index" in response.json()["error"]["message"]


def test_custom_dsl_validation_is_a_plain_request(client):
    body = client.post("/api/v1/scanner/custom/validate",
                       json={"rules": "rsi14 > 55\nnope < 3"}).json()
    assert body["valid"] is False
    assert any("nope" in e for e in body["errors"])
    assert "rsi14" in body["columns"]


def test_sector_strength_says_it_is_not_ready_rather_than_returning_nothing(client):
    """Before any sync there is no membership. The endpoint has to say so — an
    empty list would read as 'no sector is strong', which is a different claim."""
    body = client.get("/api/v1/market/sector-strength").json()
    assert body["ready"] is False
    assert body["reason"]
    assert body["sectors"] == []
    assert body["benchmark"] == core.REGIME_INDEX


def test_index_sync_refuses_clearly_without_dhan(client):
    """Index prices come from Dhan. With no credentials this must be a stated
    refusal, not a silent empty result."""
    response = client.post("/api/v1/market/index-sync")
    assert response.status_code == 400
    assert "dhan" in response.json()["error"]["message"].lower()


# ---------------------------------------------------------------------------
# P7: the guard on state-changing endpoints.
# ---------------------------------------------------------------------------

def test_config_does_not_name_the_environment_variables_it_reads(client):
    """/config is unauthenticated. Naming the exact variables a server reads,
    and which are unset, tells an attacker what to look for; token_issued_at
    tells them when it was last rotated."""
    body = client.get("/api/v1/config").json()
    assert "variables" not in body["providers"]["dhan"]
    assert "token_issued_at" not in body["providers"]["dhan"]
    assert set(body["providers"]["dhan"]) == {"configured", "auto_renew"}


def test_a_mutation_without_the_key_is_refused(client, monkeypatch):
    from app.core import guard
    monkeypatch.setenv("API_ACCESS_KEY", "s3cret-for-tests")
    guard.reset_rate_limit()
    refused = client.post("/api/v1/forward/refresh")
    assert refused.status_code == 401
    assert refused.json()["code"] == "unauthorized"
    assert "s3cret-for-tests" not in refused.text, "the reply must not echo the key"

    wrong = client.post("/api/v1/forward/refresh", headers={"X-API-Key": "nope"})
    assert wrong.status_code == 401

    ok = client.post("/api/v1/forward/refresh", headers={"X-API-Key": "s3cret-for-tests"})
    assert ok.status_code == 200


def test_reads_stay_open_with_the_key_set(client, monkeypatch):
    """Locking reads would break the app for its own frontend, and the health
    check has to answer before anything is configured."""
    monkeypatch.setenv("API_ACCESS_KEY", "s3cret-for-tests")
    assert client.get("/api/v1/config").status_code == 200
    assert client.get("/health").status_code == 200


def test_an_unset_key_does_not_lock_the_owner_out(client, monkeypatch):
    """Deploying the guard must not break a running install before its owner
    has set the key."""
    monkeypatch.delenv("API_ACCESS_KEY", raising=False)
    from app.core import guard
    guard.reset_rate_limit()
    assert client.post("/api/v1/forward/refresh").status_code == 200


def test_expensive_endpoints_are_rate_limited(client, monkeypatch):
    from app.core import guard
    monkeypatch.delenv("API_ACCESS_KEY", raising=False)
    monkeypatch.setattr(guard, "RATE_LIMIT", 3)
    guard.reset_rate_limit()
    codes = [client.post("/api/v1/data/sync", json={"universes": ["Nifty 500"]}).status_code
             for _ in range(5)]
    assert 429 in codes, codes
    assert codes.count(429) == 2, f"expected the last two to be limited, got {codes}"
    # A read is never rate limited: the dashboard polls.
    assert client.get("/api/v1/config").status_code == 200
    guard.reset_rate_limit()


def test_cors_is_not_a_wildcard():
    """Reads the class DEFAULT, not an instance: conftest sets CORS_ORIGINS for
    the test run, so an instance would only tell us what the tests configured."""
    from app.core.config import Settings
    default = Settings.model_fields["cors_origins"].default
    assert "*" not in default
    assert "ati-lab.onrender.com" in default
    assert "localhost:3000" in default, "dev must still work"
