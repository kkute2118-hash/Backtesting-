"""What is actually in 'NSE All Cash (~2000)'?

The label says ~2000. A build on 2026-09-20 resolved it to 9,917 symbols, of
which only 3,521 returned any price history, and the resulting backup blew
past GitHub's file size limit. nse_liquid_universe()'s own docstring claims
"~1900-2100 names", so either the docstring was never true or Dhan's scrip
master changed under it.

This answers that with data instead of a guess. It reads the same public
instrument master the engine reads, applies the same filters, and reports what
survives and why - it changes nothing and writes nothing.

Universe definitions are frozen, so this is deliberately read-only: it tells
you what a change WOULD do without making one.
"""
from __future__ import annotations

import io
import os
import sys
from collections import Counter

import pandas as pd
import requests

URLS = ["https://images.dhan.co/api-data/api-scrip-master.csv",
        "https://images.dhan.co/api-data/api-scrip-master-detailed.csv"]


def load():
    last = ""
    for u in URLS:
        try:
            r = requests.get(u, timeout=60)
            r.raise_for_status()
            if len(r.content) > 1000:
                print(f"source: {u}  ({len(r.content)/1048576:.1f} MB)")
                return pd.read_csv(io.BytesIO(r.content), low_memory=False)
        except Exception as e:
            last = str(e)
    raise SystemExit(f"could not fetch the instrument master: {last}")


def pick(cols, *names):
    for n in names:
        if n in cols:
            return cols[n]
    return None


def main():
    m = load()
    cols = {str(c).strip().lower(): c for c in m.columns}
    print(f"rows in master: {len(m):,}")
    print(f"columns: {', '.join(sorted(cols))}\n")

    sym = pick(cols, "sem_trading_symbol", "trading_symbol", "sem_custom_symbol", "custom_symbol")
    ex = pick(cols, "sem_exm_exch_id", "exchange")
    seg = pick(cols, "sem_segment", "segment")
    series = pick(cols, "sem_series", "series")
    inst = pick(cols, "sem_instrument_name", "instrument_name", "sem_exch_instrument_type")
    lot = pick(cols, "sem_lot_units", "lot_size")

    if ex:
        m = m[m[ex].astype(str).str.upper().isin(["NSE", "NSE_EQ"])]
        print(f"after exchange filter (NSE / NSE_EQ): {len(m):,}")
    if seg:
        sv = m[seg].astype(str).str.upper().str.strip()
        q = sv.isin(["E", "EQUITY", "NSE_EQ"])
        if q.any():
            m = m[q]
        print(f"after segment filter (E / EQUITY / NSE_EQ): {len(m):,}")

    s = m[sym].astype(str).str.upper().str.strip()
    keep = ~(s.str.endswith("SM") | s.str.contains("-SM"))
    print(f"after the SME exclusion the engine applies: {int(keep.sum()):,}")
    print(f"  (the engine appends .NS, so it excludes names ending 'SM.NS' or containing '-SM')\n")
    m = m[keep]

    for label, col in (("SERIES", series), ("INSTRUMENT", inst)):
        if not col:
            print(f"-- no {label} column in this master --\n")
            continue
        c = Counter(m[col].astype(str).str.upper().str.strip())
        print(f"-- breakdown by {label} ({col}) --")
        for k, n in c.most_common(25):
            print(f"  {k:24s} {n:6d}")
        print()

    # The series codes that are ordinary tradeable equity on NSE. Everything
    # else in the cash segment is an ETF, a debt instrument, a rights entitle-
    # ment, a suspended or trade-to-trade name, or an SME board listing.
    if series:
        sv = m[series].astype(str).str.upper().str.strip()
        for combo, why in (
            (["EQ"], "EQ only - the normal rolling-settlement equity series"),
            (["EQ", "BE"], "EQ + BE - adds trade-to-trade (delivery only)"),
            (["EQ", "BE", "BZ"], "EQ + BE + BZ - adds the surveillance series"),
        ):
            n = int(sv.isin(combo).sum())
            print(f"  {n:6d}  {why}")
        print()

    if lot:
        print(f"note: lot-size column present ({lot}); "
              f"{int((pd.to_numeric(m[lot], errors='coerce') > 1).sum()):,} rows have lot size > 1, "
              f"which is a derivative tell rather than cash equity")

    print("\nNothing was changed. Universe definitions are frozen; this is a report.")


if __name__ == "__main__":
    main()
