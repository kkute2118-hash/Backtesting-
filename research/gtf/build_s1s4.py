"""Regenerate every ungated S1-S4 signal with the look-ahead-fixed engine.

The 273,688 fingerprints already in the store predate commit a30a00e, which
made the weekly and monthly features genuinely point-in-time. Three of the four
strategies read monthly fields, so those rows are not evidence. This rebuilds
them from the current engine.
"""
from __future__ import annotations
import argparse, os, sys, time
from multiprocessing import Pool
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "backend"))


def _work(chunk):
    from app.engine import core
    core._persist_raw_fingerprints = lambda *a, **k: None   # research run, no DB writes
    syms, start, end = chunk
    data = core.load_local_backtest_data(syms, "2021-04-01", end)
    if not data:
        return pd.DataFrame()
    try:
        return core.run_raw_signal_backtest(data, [1, 2, 3, 4], start, end)
    except Exception as exc:                                # noqa: BLE001
        print(f"  !! chunk failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return pd.DataFrame()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--start", default="2021-06-01")
    ap.add_argument("--end", default="2026-09-04")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()

    from app.engine import core
    con = core._db()
    syms = [r[0] for r in con.execute(
        "SELECT symbol FROM candles GROUP BY symbol HAVING COUNT(*)>=320 ORDER BY symbol")]
    con.close()
    if a.limit:
        syms = syms[:a.limit]
    k = max(1, len(syms) // (a.workers * 4))
    chunks = [(syms[i:i + k], a.start, a.end) for i in range(0, len(syms), k)]
    print(f"{len(syms)} symbols in {len(chunks)} chunks on {a.workers} workers", flush=True)

    t0 = time.time()
    out = []
    with Pool(a.workers) as p:
        for n, df in enumerate(p.imap_unordered(_work, chunks), 1):
            if len(df):
                out.append(df)
            done = sum(len(x) for x in out)
            print(f"  chunk {n}/{len(chunks)}  {done} signals  {time.time()-t0:.0f}s", flush=True)
    res = pd.concat(out, ignore_index=True) if out else pd.DataFrame()
    res.to_parquet(a.out, index=False)
    print(f"{len(res)} signals -> {a.out}  ({time.time()-t0:.0f}s)")
    if len(res):
        print(res.groupby("strategy").size().to_string())


if __name__ == "__main__":
    main()
