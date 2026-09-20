# Universe audit — "NSE All Cash (~2000)" is 73% not equity

Read-only investigation, run 2026-09-20 on a GitHub runner against the live
Dhan instrument master. **Nothing was changed.** Universe definitions are
frozen under the ABSOLUTE RULE, so this reports what a change would do without
making one.

---

## What the filters actually do

```
rows in the Dhan instrument master          207,159
after exchange filter (NSE / NSE_EQ)        126,305
after segment filter (E / EQUITY / NSE_EQ)    9,924
after the engine's SME exclusion              9,922   <- the scanned universe
```

The label says ~2000. The docstring on `nse_liquid_universe()` says
"~1900-2100 names". The real number is **9,922**.

## Where the other ~7,000 come from

Breaking the survivors down by `SEM_SERIES`:

| series | n | what it is |
|---|---|---|
| **SG** | **4,325** | **Sovereign Gold Bonds** |
| **EQ** | **2,688** | **ordinary rolling-settlement equity** |
| N0 | 1,010 | non-convertible debentures |
| SM | 466 | SME board |
| BE | 242 | trade-to-trade equity (delivery only) |
| GS | 132 | government securities |
| ST | 105 | — |
| MF | 103 | mutual funds / ETFs |
| N1 | 101 | debt |
| TB | 84 | treasury bills |
| SF | 50 | — |
| GB | 45 | government bonds |
| BZ | 36 | surveillance series equity |
| N2–N9, NC, ND, NE, IV… | ~250 | further debt series |

**The single largest group in our "equity" universe is Sovereign Gold Bonds**,
at 4,325 — more than the 2,688 actual equities. Add the debt series, treasury
bills, government securities and ETFs and roughly **73% of the universe is not
a share.**

### Why the existing filters miss all of it

Dhan labels every one of these `SEM_INSTRUMENT_NAME = EQUITY`:

```
-- breakdown by INSTRUMENT --
  EQUITY   9922
```

So the segment filter has nothing to bite on. The distinction lives in
`SEM_SERIES`, which the engine never reads.

### And the SME exclusion is broken

`nse_liquid_universe()` excludes names ending `SM.NS` or containing `-SM`:

```python
tickers = [t for t in tickers if not t.endswith("SM.NS") and "-SM" not in t]
```

It removed **2** rows. There are **466** SME names, and they are marked in the
`SEM_SERIES` column, not in the trading symbol. The exclusion is looking in the
wrong place.

---

## What a series filter would give

| filter | count | note |
|---|---|---|
| `EQ` only | **2,688** | matches the label and the docstring |
| `EQ` + `BE` | 2,930 | adds trade-to-trade (delivery only) |
| `EQ` + `BE` + `BZ` | 2,966 | adds the surveillance series |

Any of these lands in the "~1900–2100" range the docstring claims, and squarely
on the "~2000" in the universe's own name.

One more tell in the data: **5,010 rows carry a lot size greater than 1**,
which is a derivative characteristic rather than cash equity.

---

## What this explains

1. **The failed build.** 9,917 symbols pulled 3,521 with history and compressed
   to 116.5 MB, past GitHub's 100 MB push limit. Filtered to EQ, the same three
   years would be roughly a quarter of that and would never have hit the ceiling.

2. **The Dhan rate limiting.** Nearly 7,000 unnecessary requests, which is what
   pushed the tail of the run into repeated `DH-904` throttling errors.

3. **Why only 3,521 of 9,917 returned data.** Gold bonds and treasury bills do
   not have the daily OHLCV history the scanners need.

4. **Wasted scan time on every run**, not just this one.

---

## What it does *not* appear to affect

The non-equity instruments almost certainly produce no signals: they lack the
history the strategies require, and anything that survived would still have to
clear the existing ₹40 crore/day turnover filter. So this is very likely a
**cost and correctness problem rather than a silent-bad-trades problem**.

That is a reasoned expectation, not a measurement. Confirming it means checking
whether any non-EQ symbol has ever appeared in `scanner_signals` — worth doing
before anyone relies on the reassurance.

---

## Recommendation, not applied

Add a series filter to `nse_liquid_universe()`, keeping `EQ` and `BE`:

```python
# SEM_SERIES, not the trading symbol: Dhan marks every instrument in this
# segment as EQUITY, so the series column is the only thing that separates
# a share from a sovereign gold bond.
```

**This is a change to a frozen universe definition and has not been made.** It
needs an explicit decision, because even as a bug fix it changes what the
scanners see — which is exactly what the ABSOLUTE RULE exists to prevent. The
golden signal census would have to be re-baselined deliberately rather than
silently.

Tooling: `scripts/universe_audit.py`, run as a step in `build-history.yml`.
Read-only, ~5 seconds, no credentials.
