# Streamlit → Web App Migration Plan

Adaptive Trading Intelligence Lab — from a single 2,700-line `app.py` Streamlit
script to a FastAPI backend + Next.js frontend.

---

## 1. What the current application does

The repository holds three Python files that matter:

| File | Lines | Role |
| --- | --- | --- |
| `core.py` | 8,724 | The whole engine: Dhan data, candle store, indicators, strategies S1–S4, scoring, safety, backtests, forward tests, learning, LLM panels, crypto/forex SMC. Contains **no UI** apart from one banner helper. |
| `app.py` | 2,682 | 15 Streamlit tabs on top of `core.py`. Pure UI + orchestration. |
| `daily_job.py` | 295 | Headless cron runner (GitHub Actions) that drives `core.py` after the NSE close. |

### Feature inventory (the 15 Streamlit tabs)

1. **Dashboard** — four static metrics and a prose explanation of the engine.
2. **Daily Scanner** — universe multiselect, strategy multiselect, min-score,
   result mode, data-freshness banner, "top up latest sessions" button, live
   intraday overlay toggle, then `scan_dataset()`; renders best setups, per-strategy
   condition audits (S2 and S4 SEPA), ML win probability, scanner diagnostics,
   strategy coverage, strategy board, multi-strategy confluence, all qualifying
   setups, forward-test queue, per-strategy tabs.
3. **AI Trade Debate Panel** — 5 Anthropic agents that argue over the shortlist.
4. **Backtest** — professional walk-forward backtest, learning dataset,
   strategy performance/ROI/risk, capital simulation, score learning,
   marking conditions, per-strategy results.
5. **Raw Strategy Learning** — ungated signal capture + fingerprints.
6. **Stop-Loss Calibration Study** — five SL schemes compared over history.
7. **Forward Testing** — persistent tracker, live P/L positions, strategy
   scorecard, persisted scanner signals.
8. **Market Learning** — forward leaderboard, historical evidence, marking
   component learning, adaptive score edge, learning DB stats.
9. **AI System Coach (LLM)** + **System Learning Panel (5 agents)**.
10. **Long-Term Fundamentals** — Screen A / Screen B universe scan, manual
    symbol lookup, Piotroski score, news snapshot.
11. **Small/Micro Safety Engine**.
12. **Live Monitor** — persistent Dhan WebSocket, live forward-test table.
13. **Dhan Data Manager** — sync missing data, top-up latest, sync diagnostics,
    history floor table, DB backup/restore to GitHub, backup diagnostic,
    connection diagnostic, historical smoke test.
14. **S4 SEPA Strategy** — SEPA watchlist scan, stock DNA, trailing stop,
    EMA20 extension calibration.
15. **Custom Strategy Lab** — a small DSL (`rsi14 >= 55`, `close > 1.02*ema20`)
    compiled against the feature frame, plus its own backtest.
16. **Research & Risk Control**, **Strategy Coach**, **Forex/Crypto SMC**,
    **Early Warning Radar**.

### Data sources

| Source | Used for | Auth | Notes |
| --- | --- | --- | --- |
| Dhan API v2 | instrument master, daily OHLCV, bulk quotes, live WebSocket | `DHAN_CLIENT_ID` + (`DHAN_PIN`+`DHAN_TOTP_SECRET` or `DHAN_ACCESS_TOKEN`) | 5 req/s throttle, 24h token, DH-907 = "no data" |
| niftyindices.com | Nifty 500 / Smallcap 100 / Smallcap 250 / Midcap 150 CSVs | none | cached 24h |
| Twelve Data | fundamentals, news, forex/crypto history | `TWELVEDATA_API_KEY` | optional |
| Anthropic | AI coach, debate panel, learning panel | `ANTHROPIC_API_KEY` | optional |
| GitHub Contents API | SQLite backup/restore | `GH_BACKUP_TOKEN` + `GH_REPO` | how state survives a container reboot |

### Storage

One SQLite file (`market_data.sqlite3`, path from `DATA_DB` or a writable dir
outside the git checkout). ~25 tables: `candles`, `forward_tests`,
`forward_observations`, `forward_results`, `scanner_signals`,
`learning_observations`, `feature_snapshots`, `engine_metrics`,
`raw_signal_fingerprints`, `sl_calibration_*`, `backtest_runs`,
`dhan_token_cache`, `dhan_history_floor`, `sync_diagnostics`, `research_events`,
`coach_reports`, `learning_panel_runs`, …

### Streamlit coupling in the engine

Small and surgical — this is what makes the migration low-risk:

* 8 × `@st.cache_data`, 2 × `@st.cache_resource`
* `st.secrets.get()` inside `_secret()` (already falls back to env vars)
* one UI function, `render_data_freshness_banner()`

Nothing else in `core.py` touches Streamlit.

---

## 2. What is preserved

**Everything in `core.py` is preserved byte-for-byte.** It moves to
`backend/app/engine/core.py` and the only edit is the import line:

```python
-import streamlit as st
+from app.engine import st_compat as st
```

`st_compat` supplies a real TTL cache (`cache_data` / `cache_resource`), a
`secrets` object backed by environment variables and an optional
`secrets.toml`, and no-op stubs for the handful of message calls.

That guarantees the scanner, indicators, scoring, safety and backtests produce
**identical** results to the Streamlit build — there is no reimplemented maths
to drift.

The `daily_job.py` cron runner and both GitHub Actions workflows keep working;
only the import path and the requirements file change.

---

## 3. What is redesigned

| Streamlit behaviour | Problem | New design |
| --- | --- | --- |
| Whole script re-runs on every widget change | a 2,000-stock scan re-triggers on a checkbox | scans are **jobs**: `POST /scanner/runs` → job id → poll progress → fetch results |
| Results held in `st.session_state` | lost on reload, invisible to other devices | results persisted in SQLite, addressable by run id |
| 15 flat tabs, one 2,700-line file | no hierarchy, impossible to maintain | sidebar IA with 10 sections, typed services, one router per domain |
| `st.dataframe` | no column control, no export, no row click | virtualised table: sort, filter, column visibility, selection, CSV export, row → detail page |
| No watchlists / no saved scanner configs | — | new `app_watchlists`, `app_watchlist_items`, `app_scanner_presets`, `app_preferences` tables |
| No stock detail view | — | dedicated page: candlestick chart, indicator panel, signal explanation, condition matrix |
| Blocking spinners | page freezes | skeletons, progress bars, non-blocking polling |
| Secrets in Streamlit Secrets only | tied to Streamlit Cloud | backend-only env vars, never sent to the browser |

---

## 4. Proposed architecture

```
                    ┌──────────────────────────────┐
  browser  ────────▶│  Next.js 15 (App Router, TS) │
                    │  Tailwind, TanStack Query    │
                    └──────────────┬───────────────┘
                                   │ REST /api/v1
                    ┌──────────────▼───────────────┐
                    │  FastAPI (Pydantic v2)       │
                    │  routers → services          │
                    └──────────────┬───────────────┘
                       ┌───────────┴───────────┐
                       │                       │
              ┌────────▼────────┐    ┌─────────▼─────────┐
              │ app/engine/core │    │ app/db/app_store  │
              │ (unchanged)     │    │ watchlists/presets│
              └────────┬────────┘    └─────────┬─────────┘
                       └───────────┬───────────┘
                          ┌────────▼────────┐
                          │ market_data.db  │
                          │ (SQLite)        │
                          └─────────────────┘
                                   ▲
                        Dhan · Twelve Data · Anthropic · GitHub
```

Long scans run in a background thread pool owned by `services/jobs.py`, with
progress written to an in-memory registry and the final result persisted.

## 5. Page structure

| Route | Purpose |
| --- | --- |
| `/` | Dashboard — market status, data freshness, forward-test book summary, latest scan, top opportunities, strategy scorecard |
| `/scanner` | Scanner controls, filter groups, presets, run history |
| `/scanner/runs/[id]` | Results table for one run |
| `/radar` | Early Warning Radar |
| `/stocks/[symbol]` | Stock detail — chart, indicators, signal explanation, condition matrix |
| `/watchlist` | Watchlist groups + live quotes |
| `/forward` | Forward-test book, live P/L, closed results, scorecard |
| `/learning` | Adaptive learning, leaderboards, score edge |
| `/backtest` | Walk-forward backtest runner + history |
| `/data` | Dhan data manager, sync, diagnostics, backup |
| `/settings` | Configuration status, theme, scan defaults |

## 6. Technology stack

**Backend** — Python 3.11, FastAPI, Pydantic v2, uvicorn, SQLite, the existing
pandas/numpy/scikit-learn/dhanhq/ccxt stack. No ORM: the engine already owns
its schema, and an ORM layered over it would be a second source of truth.

**Frontend** — Next.js (App Router), React 19, TypeScript, Tailwind CSS v4,
TanStack Query + TanStack Table, Recharts (analytics) and
lightweight-charts (candles), lucide-react, next-themes, sonner.

## 7. Migration risks

| Risk | Mitigation |
| --- | --- |
| Scanner results drift | engine is moved, not rewritten; parity tests pin indicators + strategy signals on fixed synthetic data |
| Streamlit cache semantics differ | `st_compat.cache_data` copies DataFrame/Series results and hashes pandas args, matching Streamlit |
| Long scans time out over HTTP | job queue + polling, never a synchronous scan request |
| Cron workflows break | `daily_job.py` keeps its path and CLI; only its import and requirements change |
| Secrets leaking to the browser | every provider call is server-side; the frontend only ever sees a boolean "configured" flag |
| SQLite write contention | engine already opens with `timeout=60`; jobs are serialised per kind |

## 8. Implementation order

1. Backend skeleton + engine shim (keeps `daily_job.py` runnable)
2. Services + REST API + app-store tables
3. Frontend foundation: design system, layout, navigation, API client
4. Dashboard → Scanner → Results → Stock detail → Watchlist → Radar → Forward → Learning → Backtest → Data → Settings
5. Polish: responsive, loading/error/empty states, a11y, dark/light
6. Tests: indicator + strategy parity, filter logic, API smoke
7. Cleanup: delete `app.py`, drop the Streamlit dependency, update workflows/README

---

## 9. Migration checklist

| Streamlit feature | New location | Status |
| --- | --- | --- |
| Dashboard metrics | `/` + `GET /api/v1/market/overview` | Complete |
| Data freshness banner | `/` and `/scanner` freshness card + `GET /api/v1/market/freshness` | Complete |
| Universe pickers | `GET /api/v1/universes` | Complete |
| Daily Scanner run | `POST /api/v1/scanner/runs` (job) | Complete |
| Live intraday overlay toggle | `use_live_prices` on the scan request | Complete |
| Top-up latest sessions | `POST /api/v1/data/sync/latest` (job) | Complete |
| Best setups / all setups / per-strategy | `/scanner/runs/[id]` table + strategy facets | Complete |
| Scanner diagnostics + coverage | run `stats` payload → Diagnostics panel | Complete |
| Multi-strategy confluence | Results table "Confluence" facet | Complete |
| Forward-test queue (score ≥ gate) | Results → "Send to forward test" action | Complete |
| Strategy condition audit (S2 / S4) | `/stocks/[symbol]` → Condition matrix | Complete |
| ML win probability | `Win Probability %` column | Complete |
| Early Warning Radar | `/radar` + `POST /api/v1/radar/runs` | Complete |
| Forward positions + live P/L | `/forward` + `GET /api/v1/forward/positions` | Complete |
| Forward scorecard | `/forward` scorecard + `GET /api/v1/forward/summary` | Complete |
| Persisted scanner signals | `GET /api/v1/scanner/signals` | Complete |
| Refresh/resolve forward positions | `POST /api/v1/forward/refresh` | Complete |
| Market learning tables | `/learning` + `GET /api/v1/learning/*` | Complete |
| Adaptive score edge | `GET /api/v1/learning/edge` | Complete |
| Walk-forward backtest | `/backtest` + `POST /api/v1/backtest/runs` (job) | Complete |
| Backtest history | `GET /api/v1/backtest/latest` | Complete |
| Raw strategy learning | `POST /api/v1/backtest/raw-signals` (job) | Complete |
| Stop-loss calibration study | `POST /api/v1/backtest/sl-calibration` (job) | Complete |
| S4 SEPA scan | `POST /api/v1/scanner/sepa` (job) | Complete |
| S4 EMA20 extension calibration | `POST /api/v1/backtest/s4-extension` (job) | Complete |
| Stock DNA | `GET /api/v1/stocks/{symbol}/dna` | Complete |
| Custom Strategy DSL + backtest | `/scanner` → Custom DSL panel, `POST /api/v1/scanner/custom` | Complete |
| Long-term fundamentals Screen A/B | `POST /api/v1/fundamentals/screens` (job) | Complete |
| Manual symbol fundamentals lookup | `GET /api/v1/stocks/{symbol}/fundamentals` | Complete |
| Small/micro safety engine | `GET /api/v1/stocks/{symbol}/safety` | Complete |
| Live monitor / WebSocket feed | `/forward` live panel + `POST /api/v1/live/start|stop`, `GET /api/v1/live/prices` | Complete |
| Dhan Data Manager | `/data` + `GET/POST /api/v1/data/*` | Complete |
| GitHub backup / restore / diagnostic | `/data` → Backup panel | Complete |
| Dhan connection + smoke test | `/data` → Diagnostics panel | Complete |
| Strategy Coach (statistical) | `GET /api/v1/learning/coach` | Complete |
| AI System Coach (LLM) | `POST /api/v1/ai/coach` | Complete |
| AI Trade Debate Panel | `POST /api/v1/ai/debate` | Complete |
| System Learning Panel (5 agents) | `POST /api/v1/ai/learning-panel` | Complete |
| Forex/Crypto SMC scan | `POST /api/v1/smc/scan` | Complete |
| Research & risk control | `/backtest` → Portfolio simulation panel | Complete |
| Watchlists | **new** `/watchlist` + `GET/POST/DELETE /api/v1/watchlists` | Complete |
| Scanner presets | **new** `GET/POST/PATCH/DELETE /api/v1/presets` | Complete |
| Dark / light theme | **new** persisted preference | Complete |
