# RESEARCH_GAPS

Everything the transcripts leave unresolved, ranked by impact on implementation.

---

## RG-01 — The blue-candle overlay — **RESOLVED**

**Resolved by the user, 2026-09-20:** blue candles are **CB candles** — a day on
which the stock performed *extremely well compared with its own other good days*.

This fits everything the transcripts show and nothing contradicts it:

- CB is listed beside DNA and relativity, not beside volume: *"you do not have to
  sit and see the DNA of ETF, **CB of ETF**, relativity of ETF"* (line 4437). All
  three are per-stock, per-timeframe character judgements.
- His sequence is literally *"we are going sequence wise for **CB**, contraction,
  and then what happened"* (line 1045) — CB is the expansion candle.
- *"Event, amazing **CB candle**, contraction starts within the high of expansion"*
  (line 5076) — the full setup in one line.
- It explains why he counts them (*"how many dark blue candles you are having, 1 2
  3 4"*) and why white candles interleaved are a defect: a white up-candle is an up
  day that was *not* exceptional for that stock.
- It explains why the same percentage is a CB in one stock and unremarkable in
  another — the benchmark is the stock's own distribution, which is exactly how he
  treats DNA.

**Implemented** as `cb_flags()` in `backend/app/engine/trader_layer.py`: a trailing
percentile of the stock's own *positive* daily returns, two bands for blue vs
dark/navy. Causal, adapts as a stock's character changes, and needs only the
percentile as a fitted parameter.

**First measurement (fixture, 22,530 signals):** CB purity carries real signal.
Sorting all signals into quartiles by the CB purity of their expansion gives mean
forward returns of −1.06% / −0.74% / +1.63% / +0.40%. The bottom half is clearly
worse than the top half. This is the strongest single soft signal found so far and
it came directly from this definition.

**Still open:** whether the shades (blue / dark blue / navy) are percentile bands,
as implemented, or encode something else. Low impact — the bands are a parameter.

## RG-02 — Almost no numeric thresholds — **HIGH**

The author states relationships, not numbers, and explicitly refuses to state numbers
("Do not make it a formula"). Missing values:

| Parameter | Evidence available |
|---|---|
| Turnover floor | Band only: ₹2.5 cr rejected, ₹80 cr "pretty healthy" |
| Volume elevation multiple | One mention of "twice the average", lookback unstated |
| Minimum EMA10/EMA20 separation | "clearly visible distance" — qualitative |
| Contraction time proportionality | "60% in 6 days, contracted 8 days — not enough" |
| Relativity → which MA | Direction only, no boundaries |
| Event lookback window | "recent" |
| Extension threshold | "been going up for a long period of time" |
| Top-N per day | Implied 2–3 by position sizing |

**Impact.** Every gate needs a fitted parameter, and every fitted parameter is an
overfitting opportunity. Mitigation: sweep rather than tune, count every sweep toward
the best-of-N adjustment, and hold out a test split touched once.

---

## RG-03 — "Candle quality" is never quantified — **MEDIUM**

The corpus contains dozens of quality judgements — "amazing", "brilliant", "not the
best", "horrible" — and no definition beyond "open near low, full body, minimal wick".

`body / (high - low)` is the obvious proxy but is certainly incomplete: the author also
weighs where the candle sits relative to the MA, what precedes it, and what the higher
timeframe is doing.

**Test available.** Lecture 10 provides roughly twenty charts with explicit accept /
reject verdicts and stated reasons. That is a labelled validation set. If the proxy
cannot separate his accepts from his rejects on his own examples, it is not usable —
and that is a result worth reporting rather than a problem to tune around.

---

## RG-04 — Momentum-day contradiction — **LOW (resolved)**

Lecture 11, consecutive sentences:

> "I don't like to add on these days. These are momentum days. Usually it happens in
> the first 15 30 minutes. I just don't get the liquidity. **So, for me these are the
> perfect day to add on to a stock.**"

**Resolution:** almost certainly a transcription error for "*not* the perfect day". The
surrounding argument and every other lecture reject chasing momentum. Treat momentum
days as **not** add points.

---

## RG-05 — The methodology resists formalisation by design — **STRUCTURAL**

The author's most-repeated meta-rule is that his observations must not become formulas
(G-01, G-02). The master prompt requires a deterministic engine. These are in genuine
tension.

**This cannot be resolved, only managed:**
- Hard gates only for EXPLICIT computable rules.
- Everything else is an approximation, labelled as ours.
- The approximation layer must be validated against his own labelled examples before
  use, not merely fitted for return.

If the validated approximation layer adds nothing over the hard gates, the honest
deliverable is the hard gates alone.

---

## RG-06 — EMA vs SMA never stated — **LOW**

"10 EMA", "20 EMA", "50 EMA" dominate, but "moving average", "200 day moving average"
and "10 moving average" are used interchangeably throughout. The colour legend
(line 1297) says "moving average" for all four.

**Resolution:** test both. The difference on a 10-period is small; on a 200-period it
is material.

---

## RG-07 — Scan definition is external — **MEDIUM**

The author references his own scans by name — "rich road pivot points weekly scan"
(lecture 14) — and says the definition is shared elsewhere (Telegram, website PDFs).
The transcripts never state it.

What we can infer about his scan:
- Runs **weekly**, after Friday's close (lecture 14).
- Produced **57 stocks** that week; he calls that "not a very big number to manage".
- Also runs a daily list (lecture 12: "you run your scan and this is the day you see
  the stock come in your scan").
- Triggers include a large up day with high volume (+20% day, lecture 8; +8% day,
  lecture 11), and a candle on roughly twice average volume (lecture 4).

**Impact is limited** for our purpose: we already have S1–S5 as the candidate
generator, and the master prompt explicitly frames this work as the *second stage*. The
gap matters only if we wanted to reproduce his first stage, which we do not.

---

## RG-08 — Position sizing is stated in notional, not risk — **LOW**

He quotes notional sizes (35–40% starting, 60–80% for the best) and stop widths
(2–8%), but never a risk-per-trade percentage.

The reconciliation in `RISK_ENGINE.md` §5 — that his numbers are consistent with a
~1.5–2% risk budget — is **arithmetic inference, not a quotation**, and is flagged as
DERIVED there. It should be validated, not cited as his rule.

---

## RG-09 — No losing-trade anatomy — **MEDIUM**

The corpus is heavily weighted toward trades that worked. Losses appear (the Olectra
trade in lecture 13, which he calls "one of the worst trades to be there in your trade
book") but are not dissected with anything like the rigour applied to winners.

**Impact.** We can reconstruct what he looks *for* far better than what actually goes
wrong after a setup passes every filter. The false-positive rate of his own criteria is
unobservable from this material.

**Only our own backtest can supply it.** This is the strongest single argument for
running `BACKTEST_SPEC.md` before believing any of this.

---

## RG-10 — Sample provenance — **STRUCTURAL**

Roughly 40 charts, chosen by the author, after the fact, to teach specific points.

He is scrupulous about separating real-time from hindsight *within* each chart —
"it's the hindsight analysis that can say oh you could have bought it here; the point
is at this point what are the guarantees? None" (lecture 7) — which is a genuine mark
of quality in the material.

But the **selection of which charts to teach from** is unavoidably retrospective. The
transcripts are a source of hypotheses. They are not evidence. Our 5-year candle store
is the only evidence available, and Section 37 of the master prompt is the right
standard: **no data, no claim.**
