# Step 8: 4h trend breakout with a demand-zone entry (4 Oct 2026)

scripts/trend_zone_entry_study.py. Same signals and exits as step 6 (4h 55/20,
daily 200-day filter, long only, crypto + gold perps, full charges); only the
entry changes: the first pullback into the nearest fresh 4h demand zone (step
7's rules) made in the 10 days before the breakout.

Total R (= % of equity at 1% risk a trade) and average per trade:

| entry | stop | window | 2021-24 | 2025-26 |
|---|---|---|---|---|
| **baseline: limit at the broken high** | 2 ATR | 24h | **+191R** (199, +0.96R) | **+35R** (93, +0.38R) |
| zone limit | 2 ATR | 24h / 72h | +57R / +72R | +21R / +25R |
| zone limit | below the zone | 24h / 72h | +190R / +222R | +18R / +14R |
| zone sniper (15m MSB) | 2 ATR | 24h / 72h | +56R / +82R | +3R / −5R |
| zone sniper | below the zone's low | 24h / 72h | +137R / +208R | +12R / +2R |

The tight zone stop (1.3-2.0% of price against 3.2%) raises the R:R and
drops the win rate to 8-17%. The best 2021-24 variant (zone limit, zone stop,
72h: +222R) earned +14R in 2025-26, less than half the baseline's +35R.

Dependence on a few trades, 2021-24: without its five best trades the
baseline still made +31R; every zone variant made −39R to −92R. The zone
entries' 2021-24 totals come from a handful of 2023-24 rally trades where a
tight stop multiplied the R.

Not adopted. The Oracle paper book keeps the limit at the broken high.
