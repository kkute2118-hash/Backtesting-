# Step 7: sniper entries at higher-timeframe demand/supply zones (4 Oct 2026)

scripts/zone_sniper_study.py: the owner's master prompt (liquidity where
stop-losses sit, sections 1-2; rally/drop-base zones, section 14; sniper and
LTF entries, 17; structural stops and liquidity targets, 18-21) with the GTF
course's zone marking, freshness and "achievement" rules, on BTC, ETH, SOL,
BNB, XRP and gold, crypto-perpetual charges.

4h zones (1-3 boring candles, a leg-out body >= 1 ATR closing beyond the
base), fresh only, leg-out must reach 2 zone widths before the first return;
target = the extreme the market came back from, at least 2R.

| entry | 2021-24 | 2025-26 |
|---|---|---|
| limit at the proximal line, stop beyond the distal | −0.14R (1,358) | −0.23R (654) |
| sniper: 15m micro-MSB inside the zone, stop beyond the zone's low | −0.12R (549) | −0.01R (298) |

No tag fixes it in both periods: reversal vs continuation zones, stop-loss
sweep before the zone, daily trend on the trade's side, long vs short, gold
vs crypto (gold was worst, −0.3R to −1.0R).

## Why: the market prices risk-reward

Win rate by planned reward:risk (both entries) against the break-even rate
1/(1+RR):

| planned RR | win rate | break-even |
|---|---|---|
| 2-3 | 29% | 25-33% |
| 3-5 | 20-25% | 17-25% |
| 5-10 | 14-17% | 9-17% |
| above 10 | 9-12% | under 9% |

A tight stop at a zone does buy a large R:R, but it is hit in proportion: the
win rate falls almost exactly as the R:R rises, so the edge before costs is
about zero and charges make it negative. "Small risk, big reward" is only
an edge when something makes the win rate higher than 1/(1+RR); these zone
rules do not. Not adopted. The 4h trend breakout (step 6) remains the
strategy in use.
