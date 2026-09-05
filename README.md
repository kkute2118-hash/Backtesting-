# 🧠 Adaptive Trading Intelligence Lab

A Dhan-first research and decision-support system for Indian equities, with
separate research engines for crypto and forex.

```text
Exact strategy rules → candidate detection → quality scoring → risk/safety
      → forward testing → learning → improved candidate ranking
```

It is a research platform. **It places no orders and holds no broker write
permissions.** A setup score ranks quality; it is not a probability of profit.

---

## 🏗️ Architecture

```text
                    ┌──────────────────────────────┐
  browser  ────────▶│  frontend/  Next.js + TS     │
                    │  Tailwind, TanStack Query    │
                    └──────────────┬───────────────┘
                                   │  REST /api/v1
                    ┌──────────────▼───────────────┐
                    │  backend/   FastAPI          │
                    │  routers → services → engine │
                    └──────────────┬───────────────┘
                       ┌───────────┴───────────┐
              ┌────────▼────────┐    ┌─────────▼─────────┐
              │ app/engine/core │    │ app/db/app_store  │
              │ strategies, MTF │    │ watchlists, presets│
              │ scoring, safety │    │ preferences, runs  │
              └────────┬────────┘    └─────────┬─────────┘
                       └───────────┬───────────┘
                          ┌────────▼────────┐
                          │ market_data     │
                          │ .sqlite3        │
                          └─────────────────┘
                                   ▲
                     Dhan · Twelve Data · Anthropic · GitHub
```

| Path | Role |
| --- | --- |
| `backend/app/engine/core.py` | the engine — data, features, strategies S1–S4, scoring, safety, backtests, forward tests, learning. No UI, no HTTP. |
| `backend/app/services/` | typed, JSON-safe wrappers around the engine, one module per domain |
| `backend/app/api/v1/` | the REST surface |
| `backend/app/db/app_store.py` | watchlists, scanner presets, preferences and run history |
| `frontend/src/features/` | one directory per product area, each owning its page |
| `daily_job.py` | headless runner for the scheduled GitHub Actions jobs |

**Business logic never lives in the frontend.** The browser renders what the API
returns; every calculation, every provider call and every credential stays on
the server.

`core.py` is deliberately kept as one module and was moved into the backend
unchanged during the web migration — the strategy, scoring and safety maths is
the product, and rewriting it while replacing the UI is how a scanner quietly
starts returning different stocks. See `docs/MIGRATION.md`.

---

## ▶️ Running it

Two processes. Python 3.11+ and Node 20+.

**Backend**

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # fill in your credentials
uvicorn app.main:app --reload --port 8000
```

The interactive API docs are then at <http://localhost:8000/docs>.

**Frontend**

```bash
cd frontend
npm install
cp .env.example .env.local    # NEXT_PUBLIC_API_URL, nothing secret
npm run dev
```

Open <http://localhost:3000>.

**First run:** the app opens on an empty candle store. Go to **Data Manager**,
pick a universe and use *Sync missing history* once to build it, then *Top up
latest sessions* daily thereafter.

---

## 🚀 Deploying it

Two processes, so two hosts — or one machine running both. Streamlit Cloud
cannot serve this; it only runs `streamlit run`.

The recommended path is **Render** for the backend (with a persistent disk for
the SQLite file) and **Vercel** for the frontend. `render.yaml` and
`frontend/vercel.json` are in the repository, so both are connect-and-deploy.
There is also a `docker-compose.yml` for putting both on a single VPS.

**Step-by-step, including the order the two URLs have to be wired together:
[`docs/DEPLOYMENT.md`](docs/DEPLOYMENT.md).**

---

## 🔑 Configuration

Every credential is read from the backend's environment (see
`backend/.env.example`). Nothing is ever sent to the browser — the frontend
receives only a boolean saying whether each provider is configured.

| Variable | Needed for |
| --- | --- |
| `DHAN_CLIENT_ID` + `DHAN_PIN` + `DHAN_TOTP_SECRET` | Indian equity data, with automatic 24-hour token renewal (**preferred**) |
| `DHAN_CLIENT_ID` + `DHAN_ACCESS_TOKEN` | the same, with a token you paste by hand each day |
| `TWELVEDATA_API_KEY` | fundamentals, news/event risk, forex & crypto SMC (optional) |
| `ANTHROPIC_API_KEY` | the AI coach, trade debate panel and learning panel (optional) |
| `GH_BACKUP_TOKEN` + `GH_REPO` + `DB_BACKUP_BRANCH` | database backup (optional, strongly recommended) |
| `DATA_DB` | where the SQLite file lives; defaults to a writable directory outside the checkout |
| `CORS_ORIGINS` | browser origins allowed to call the API |

`DHAN_TOTP_SECRET` is the base32 secret shown once when enabling TOTP-based API
login in Dhan's console — not a 6-digit code. If both PIN+TOTP and a manual
access token are present, PIN+TOTP renewal wins and the manual token remains a
fallback.

**Never commit credentials.** An existing `.streamlit/secrets.toml` is still
read if present, so a deployment moving off Streamlit keeps working before the
values are moved into the environment.

---

## 🧪 Tests

```bash
cd backend && python -m pytest        # 51 tests
cd frontend && npm run typecheck && npm run build
```

The suite pins the things a migration can silently break:

* indicator maths against hand-computed values, and `features_fast()` determinism
* that ANDing a strategy's condition matrix reproduces `strategy_signal()` bar
  for bar — the property the Early Warning Radar is built on
* a full scan end to end over a seeded fixture universe, with no network access
* that no NaN reaches the browser, a missing credential answers 503 naming the
  key, and an unknown symbol answers 404 with advice
* five script-shaped regression tests, each reproducing a specific past
  incident (lost learning data, DH-907 handling, database location, the S4 SEPA
  migration, universe coverage), run under pytest by
  `tests/test_regression_scripts.py`

### Two engine behaviours the tests document rather than fix

Both change which stocks the scanner returns, so correcting either is an
engine decision and not something a UI migration should do quietly:

1. **`rsi()` returns NaN when there is no average loss.** It divides by
   `dn.replace(0, NaN)`, so a window of unbroken up days yields NaN instead of
   100 — every "RSI ≥ 50" gate reads False for the strongest momentum there is.
2. **Monthly features use the whole calendar month.** `features_fast()`
   aggregates each month in one pass and maps the result onto every daily row in
   it. Correct for the current month, so the **live scanner is sound**; but a
   *historical* bar carries that month's eventual close and high, which it could
   not have known. Backtests and learning rows that lean on a monthly gate
   inherit that and read optimistically.

---

## 🤖 Running daily without the app open

The API server only runs the engine while it is up and something asks it to, so
the forward test is driven by GitHub Actions instead.

| File | Role |
| --- | --- |
| `daily_job.py` | headless runner |
| `.github/workflows/dhan-token-renewal.yml` | 02:30 UTC daily (08:00 IST) |
| `.github/workflows/daily-forward-test.yml` | 11:20 and 13:30 UTC on weekdays (16:50 / 19:00 IST) |

The daily run, in order: restore the database from GitHub → renew the Dhan token
→ top up the newest candles → resolve open positions that hit stop or target →
scan the just-closed session → record signals at/above the gate → back up the
database.

Two guards make it safe to leave running unattended:

- **Stale candles skip the scan.** If Dhan has not published the latest session
  yet, the job resolves positions and stops. It never records a candidate from
  out-of-date prices.
- **No backup config, no run.** If the backup token/repo are missing the job
  aborts immediately, so it can never push an empty database over your saved
  forward tests.

The scan runs **after the close**, on the finished daily candle, on purpose. An
intraday scan can show a setup at 11:00 that has vanished by 15:30; recording
that as a forward test would pollute the learning data with signals that never
really existed.

Setup — repository **Settings → Secrets and variables → Actions**:

```text
Secrets   DHAN_CLIENT_ID, DHAN_PIN, DHAN_TOTP_SECRET
          (or DHAN_ACCESS_TOKEN if you are not using PIN+TOTP)
          GH_BACKUP_TOKEN   optional; defaults to the built-in Actions token

Variables DB_BACKUP_BRANCH  strongly recommended, e.g. db-backup
          SCAN_UNIVERSE     default "Nifty 500"; join with | for several
          SCAN_STRATEGIES   default "1,2,3,4"
          SCAN_MIN_SCORE    default "85"
```

**GitHub refuses to create any secret or variable whose name starts with
`GITHUB_`** — the prefix is reserved. The backup settings therefore accept
non-reserved aliases, tried in this order:

| Setting | Names accepted |
| --- | --- |
| token | `GITHUB_TOKEN`, `GH_TOKEN`, `GH_BACKUP_TOKEN` |
| repository | `GITHUB_REPO`, `GH_REPO`, `DB_BACKUP_REPO` |
| backup branch | `GITHUB_BACKUP_BRANCH`, `GH_BACKUP_BRANCH`, `DB_BACKUP_BRANCH` |

Set a dedicated backup branch before enabling the schedule. Each backup commits
the entire SQLite file, so a daily job pointed at your code branch would add one
binary blob per day to its history forever. The branch is created automatically
on the first backup if it does not exist.

---

## 🩺 When the GitHub backup will not work

**Data Manager → Test the backup path** checks the whole path without writing a
commit: configuration present, repository name well-formed, token authenticates,
repository actually visible to that token, write permission held, backup branch
present, existing backup found. It names the exact failure.

The usual causes, in order of how often they bite:

1. **Two separate secret stores.** The API server reads its own environment; the
   scheduled jobs read GitHub Actions secrets. Configuring one does not
   configure the other.
2. **A reserved name.** See the table above; a variable called
   `GITHUB_BACKUP_BRANCH` cannot be created in Actions at all.
3. **Fine-grained token missing the repository.** A fine-grained PAT returns 404
   for a repository it was not explicitly granted, which looks identical to a
   typo. It needs *Repository access* → this repo, and *Repository permissions →
   Contents: Read and write*.
4. **`GH_REPO` set to a URL.** It must be `owner/repo`.

Failures are not swallowed: `backup_db_to_github()` returns the real reason, the
Data Manager prints it, and `daily_job.py` logs it. A restore that fails for any
reason other than "no backup exists yet" aborts the scheduled run rather than
backing an empty database up over your saved forward tests.

Two further operational notes: GitHub disables scheduled workflows in a
repository with no activity for 60 days, and cron runs can be delayed under load
— which is why the forward-test job has a second attempt each evening. Both
workflows also have a **Run workflow** button in the Actions tab.

---

## 🕒 Data freshness & live intraday prices

Stored daily candles can never be newer than the last completed NSE session, so
a scan run during market hours would otherwise be evaluating yesterday's close.
Two layers fix that.

**1. Fast top-up.** `sync_latest_sessions()` requests only the last
`LATEST_SYNC_TAIL_DAYS` (10) calendar days per symbol instead of walking the
full 1000-day window, and it re-requests the newest already-stored bars. Without
that re-request a candle first written while its session was still open could
never be corrected: `MAX(dt)` had already moved past it. It is a button in both
the Data Manager and the Scanner.

**2. Live intraday overlay.** While the cash session is open, the Scanner and
the Early Warning Radar can pull today's still-forming candle from Dhan's bulk
quote feed and merge it into the daily history **in memory only**:

```text
stored daily candles (closed sessions)
        + today's forming bar (open/high/low/LTP/volume)
        = frame the strategies actually evaluate
```

A partial bar is never written to the `candles` table, and features derived from
one are never persisted to the feature-snapshot store, so backtests and research
continue to see completed sessions only.

The feature cache is keyed on last date **plus** row count **plus** last close.
Keying on the date alone silently reused stale features whenever a candle was
revised, or whenever today's forming bar moved.

---

## 📈 Live forward-test P/L

The persistent forward-test tracker shows a real current price and what the
position is actually doing:

| Column | Meaning |
| --- | --- |
| Current Price | live WebSocket tick, else a REST quote, else the last stored close |
| Gain/Loss % and ₹ | move against the recorded entry |
| Unrealized R | that move divided by the position's own risk (entry − stop) |
| To Target % / To Stop % | how far price still has to travel |
| Progress to Target % | share of the planned entry→target distance covered |
| Price Source / Price As Of | provenance, so a stale price is never mistaken for a live one |

Target and stop **resolution** still happens only on completed daily candles. A
live price touching a level raises an alert in this table; it does not close the
record.

---

## 🚨 Early Warning Radar

The scanner is binary: a stock is invisible until the day it passes every rule
of a strategy, which is usually the day the move has already started. The radar
answers the other question — which stocks are *about* to trigger.

`strategy_condition_matrix()` decomposes each strategy into its individual
conditions; ANDing them reproduces `strategy_signal()` exactly (asserted bar by
bar in `backend/tests/test_strategies.py`). That decomposition is what lets the
radar report "7 of 9 rules pass, the blocker is Monthly RSI ≥ 50 and it is 3.6%
away".

Alongside proximity it measures volatility compression, because expansion moves
follow contraction: range percentile against the stock's own 120-day
distribution, NR7, consecutive inside bars, 5-day vs 60-day range ratio, volume
dry-up, and distance from the 52-week high.

```text
Readiness = 55% proximity-to-trigger + 35% compression + regime adjustment
```

The radar changes nothing about S1–S4 qualification. It builds a watchlist.
Setting "rules allowed to fail" to 0 reproduces the scanner's qualified list
exactly.

---

## ⚡ Persistent data & fast scanning

The application maintains a local historical-data cache.

```text
Existing data → reuse
Missing data  → download only missing range
New data      → append/update cache
```

No scan, backtest or page load downloads anything: acquisition is always an
explicit Data Manager action. That keeps a study's inputs fixed while it runs
and keeps the rate-limited Dhan budget under your control.

The architecture separates data acquisition, data storage, feature calculation,
strategy evaluation, scoring and learning, so expensive calculations are not
repeated unnecessarily.

---

📊 Strategies
The system currently evaluates four primary strategies:
Strategy 1
Strategy 2
Strategy 3
Strategy 4
The strategy rules are treated as the authoritative signal layer.
The learning engine does not silently modify the original strategy rules.
The hierarchy is:
```text
Strategy Rules
      ↓
Valid Signal
      ↓
Quality Score
      ↓
Risk / Safety
      ↓
Forward Test
      ↓
Learning
```
A stock does not qualify simply because it satisfies one attractive condition.
All mandatory conditions belonging to the selected strategy must be satisfied before the stock becomes a strategy candidate.
---
🎯 Multi-Timeframe Analysis
The equity engine uses:
Daily data
Weekly data
Monthly data
Indicators include:
EMA
SMA
RSI
ATR
Relative volume
Momentum
VWAP-derived measures
Higher-timeframe support/demand analysis
Price/volume footprint analysis
Historical calculations are designed to respect the information that would actually have been available at the historical date being tested.
This is important for avoiding look-ahead bias.
---
🏆 Setup Scoring
A qualifying setup receives a quality score.
The scoring framework considers components including:
Strategy quality
Higher-timeframe demand
Footprint
Trend
Entry quality
Relative strength
Market regime
Safety
The score is used for ranking and prioritisation.
A score is not a guaranteed probability of winning.
The dashboard should therefore present the strongest qualifying candidates first.
---
🛡️ Small / Micro Safety
Small and micro-cap safety is maintained as a separate risk layer.
It can evaluate characteristics such as:
traded value
liquidity
abnormal volatility
large gaps
circuit-like price behaviour
news/event risk
selected fundamental risk indicators
The safety engine can downgrade or reject a candidate.
It must not manufacture a strategy signal that does not otherwise exist.
---
🔬 Strategy 4 Recovery Study
Strategy 4 also contains a separate research-only Recovery Study.
The purpose is to study stocks that may exhibit:
```text
Large prior move
      ↓
Consolidation
      ↓
Controlled retracement
      ↓
Volatility / volume contraction
      ↓
EMA recovery / base reclaim
      ↓
Higher high / breakout confirmation
```
This study is intentionally kept separate from the exact Strategy 4 rules.
It is used to determine whether this additional market structure has a measurable historical edge.
The Recovery Study must prove itself through historical and forward testing before it is considered for integration into the primary Strategy 4 rules.
---
🔬 Backtesting
Backtesting is performed using downloaded/persisted market data wherever possible.
The research engine evaluates historical signals and then follows the subsequent price action to determine:
WIN
LOSS
TIMEOUT
Metrics include:
Number of trades
Win rate
Average return
Average R multiple
Profit factor
Maximum win
Maximum loss
Average holding period
Strategy breakdown
Score breakdown
The backtest should distinguish between:
```text
Signal generation
and
Trade outcome
```
so that the learning engine can analyse what characteristics were associated with successful and unsuccessful setups.
---
🧠 Market Learning
The learning engine is designed to learn from historical and forward-tested trades.
Learning dimensions include:
Strategy
Setup score
Strategy component scores
Higher-timeframe conditions
Footprint
Entry quality
Safety
Market regime
Outcome
R multiple
Holding period
The purpose is not to randomly change strategy rules.
Instead, the system should learn:
> Which types of valid setups historically produced better outcomes?
This information can then improve ranking and candidate selection.
---
🔭 Forward Testing
Forward testing is maintained separately from historical backtesting.
A forward-test candidate can be tracked through:
```text
Signal
↓
Entry
↓
Live price
↓
Maximum favourable excursion
↓
Maximum adverse excursion
↓
Exit
↓
R result
↓
Learning database
```
Forward testing is important because it provides a reality check against historical backtest results.
---
⚡ Live Monitoring
The live monitoring layer uses Dhan's live market feed where configured.
The objective is to monitor selected forward-test candidates without repeatedly downloading complete historical datasets.
The live layer should focus on:
Current price
Entry status
Stop status
Target status
MFE
MAE
Exit condition
Forward-test status
Real-money order execution remains disabled unless explicitly implemented and authorised.
---
💎 Fundamentals
Fundamental analysis is intentionally separated from the primary technical scan.
The preferred workflow is:
```text
Technical scan
      ↓
Shortlist
      ↓
Fundamental enrichment
      ↓
Risk review
      ↓
Final candidate ranking
```
This prevents expensive fundamental/API requests from slowing down the entire market scan.
---
📰 News / Event Risk
News and event information may be used as an additional risk layer.
News should not automatically create a trading signal.
Instead it can be used to:
identify event risk
identify unusual developments
downgrade risky candidates
provide additional context for forward testing
---
🪙 Crypto & Forex Research
Crypto and forex are maintained as separate research engines.
The current application includes Twelve Data connectivity for historical/current market data where configured.
Crypto research can also use CCXT-supported exchanges.
The objective is to build a separate learning dataset for crypto rather than assuming that Indian-equity strategy rules automatically work in crypto.
The research process is:
```text
Historical market data
        ↓
Pattern discovery
        ↓
Strategy hypothesis
        ↓
Backtest
        ↓
Walk-forward test
        ↓
Forward test
        ↓
Learning
```
No crypto strategy should be accepted merely because it produces a high historical return.
---
⚠️ Data Quality Principles
The system should prioritise:
No look-ahead bias
No repeated use of future information
Persistent historical data
Realistic transaction costs
Slippage assumptions
Liquidity awareness
Forward testing
Drawdown analysis
Out-of-sample validation
Avoiding overfitting
Historical results are research results, not guarantees of future performance.
---
📈 Portfolio & Risk
The research architecture can evaluate:
Position sizing
Capital allocation
Number of simultaneous positions
Compounding
Portfolio drawdown
Strategy diversification
Capital constraints
The system should optimise for risk-adjusted expectancy, not simply the highest historical return.
---
🧪 Research Philosophy
The application should behave as an independent research advocate rather than a trade-confirmation machine.
If the evidence is weak:
```text
NO TRADE
```
is a valid result.
The system should not search for reasons to justify a trade merely because a user wants to trade.
---
🔐 Safety
This application is for research and decision support.
Real-money trading is disabled by design unless separately implemented and explicitly enabled.
Users should independently verify:
data quality
broker conditions
transaction costs
liquidity
corporate actions
taxation
regulatory requirements
strategy performance
before making real investment decisions.
---
💾 Persistent Data
Do not unnecessarily delete the application's local market-data or forward-testing databases.
Historical data is valuable because it allows the system to:
reduce repeated API downloads
accelerate future scans
reproduce previous research
build larger learning datasets
compare strategy performance over time
---
🏗️ Long-Term Development Goal
The long-term objective is a continuously improving research platform:
```text
DATA
 ↓
FEATURES
 ↓
STRATEGIES
 ↓
SCORING
 ↓
BACKTEST
 ↓
FORWARD TEST
 ↓
OUTCOMES
 ↓
LEARNING
 ↓
BETTER RANKING
 ↓
NEW DATA
 ↓
REPEAT
```
The learning process should improve the system's evidence and ranking, while preserving the integrity of the original strategy definitions.
The goal is not to create a system that promises perfect predictions.
The goal is to create a system that becomes:
faster, more statistically disciplined, more transparent, and more useful as its dataset grows.
---
📌 Current Status
Indian Equities
Dhan historical data
Persistent market-data cache
Dhan live feed
Strategies 1–4
Multi-timeframe analysis
Setup scoring
Market regime
Small/micro safety
Forward testing
Market learning
Strategy 4 Recovery Study
Research Extensions
Crypto data
Forex data
Fundamental enrichment
News/event risk
Continuous research and learning
---
⚠️ Important
This software is for research and decision support.
Past performance does not guarantee future performance.
A high backtest return can result from:
overfitting
survivorship bias
unrealistic execution
insufficient sample size
market-regime dependence
data-quality problems
Always validate important findings with out-of-sample and forward testing.
