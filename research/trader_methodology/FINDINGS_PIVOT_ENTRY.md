# His entry is worth something. His selection still is not.

500 stocks, 145,366 signals, 2022-2026. **Our 7% stop and 3R target on every
arm**, so only the selection and the entry vary. This is the run that
separates the two halves that had always moved together.

---

## 1. The gates fail again, harder

| | E_CLOSE | E_PIVOT 5 | E_PIVOT 10 |
|---|---|---|---|
| no gates | +0.992% | +1.443% | +1.396% |
| DNA only | +0.682% | +1.183% | +1.139% |
| DNA + turnover | **+0.186%** | +0.632% | +0.479% |

Against a random draw of the same size: **−8.7 sd** on E_CLOSE, −6.3 and −6.7
sd on the pivot arms. DNA ≥ 8% on ≥ 5 legs, then turnover ≥ ₹40 cr and
rising, selects worse trades than picking at random. That is now consistent
across every construction tried.

## 2. The pivot entry looked good for the wrong reason

The table above reads as though waiting for the pivot pays: +1.443% against
+0.992%. **It does not say that**, and the error is the same survivorship
trap the CB gate produced. E_PIVOT's average is computed over the 35% of
signals where price came back to the demand candle. The other 65% are not
missing data — they are the trades that ran away and never looked back.

Decomposed on the **same** signals:

| | n | E_PIVOT | E_CLOSE | paired diff |
|---|---|---|---|---|
| filled (5 bars) | 50,522 | +1.443% | −1.327% | **+2.770%** (t = +77) |
| never filled | 62,773 | — | **+2.853%** | the ones it skipped |

So the paired gain on filled trades is large and real — you buy a median
1.82% cheaper, and the stop-out rate falls from 76.8% to 66.4% on the very
same signals. And the trades the limit never caught were the best ones in the
book.

Per signal over the same pool of 113,295, with an unfilled order earning
nothing:

```
E_CLOSE  +0.989%       E_PIVOT 5  +0.643%       E_PIVOT 10  +0.810%
```

**Per signal, the pivot entry is worse.** Had I reported the first table, I
would have reported an artefact.

## 3. On an account, it wins anyway — because signals are not the constraint

The per-signal view assumes you could take every signal. A three-slot ₹1 lakh
book takes 29 to 49 a year out of 113,295 offered. When slots are the
binding constraint, skipping a runaway costs far less than it appears,
because another signal fills the slot within days — and the trades you do
take are cheaper and stop out less.

₹1 lakh, 3 slots, **median of 25 runs with the within-day order reshuffled**:

| strategy | E_CLOSE | orderings >₹1L | E_PIVOT 5 | orderings >₹1L |
|---|---|---|---|---|
| **ALL** | ₹134,666 | 72% | **₹143,285** | **92%** |
| S1 | ₹125,332 | 76% | ₹134,894 | 84% |
| S2 | ₹112,567 | 68% | ₹125,384 | 80% |
| S3 | **₹154,506** | 96% | ₹131,743 | 80% |
| **S4** | ₹124,787 | 80% | **₹218,978** | **100%** (p10 ₹192,866) |
| S5 | ₹59,338 | 0% | ₹82,283 | 20% |

The gain is modest in the median and large in the robustness: 92% of
orderings profitable against 72%, and a 10th percentile of ₹104,360 against
₹79,002.

**A resting limit holds its slot.** An unfilled buy order blocks margin with
an Indian broker, so the arm above keeps the slot occupied for the wait and
then releases it with no P&L. Treating an unfilled order as free gives
₹252,603 and 100% of orderings profitable — that is the optimistic bound, not
the answer, and it is in the output file labelled as such.

S3 is the exception: it is better bought at the close.

## 4. S4 again

Second independent construction in which S4 plus his pivot logic wins
decisively — first as a **stop** (median ₹178,694, 92% of orderings), now as
an **entry** (median ₹218,978, 100% of orderings, 10th percentile ₹192,866).
S4 on our close-entry, 7%-stop treatment is the worst of the five to
mediocre depending on the arm.

Whatever is different about S4, the demand candle is informative for it and
is not for S1 or S3. That is the one thread from his methodology worth
pulling further.

---

## Standing summary after this run

| his rule | verdict |
|---|---|
| CB purity gate | no edge over 5 years; off |
| DNA + turnover selection | −8.7 sd against random; do not use |
| DNA target instead of 3R | trades expectancy for win rate; worse |
| pivot as STOP | worse on S1/S2/S3, **better on S4/S5** |
| pivot as ENTRY | worse per signal, **better per account**; best on S4 |
| turnover floor | carries S4 (+3.0%/trade); mixed elsewhere |
| turnover ceiling, tower rule, marking gates | harmful |

Nothing in the engine has been changed by any of this. Stop and entry
calculation are frozen; these are reports.
