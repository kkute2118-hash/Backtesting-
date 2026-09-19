"""Rebuild the golden fixture database from a full market_data.sqlite3.

Run only when the fixture must genuinely change (new strategy, new table).
Regenerating it invalidates every golden snapshot, so the goldens have to be
rebuilt in the same commit and the diff reviewed - that diff IS the evidence
about whether scan behaviour moved.

    python backend/tests/golden/build_fixture.py /path/to/market_data.sqlite3
"""
from __future__ import annotations

import gzip, os, shutil, sqlite3, sys, tempfile

OUT = os.path.dirname(os.path.abspath(__file__))
BARS = 750          # SEPA needs 52-week structure with room before it; at 400
                    # bars S4 fired zero times and its rules went unpinned.
EVERY = 3           # every Nth symbol: representative, and a 2 MB fixture

COPY_TABLES = ("sector_membership", "forward_tests", "forward_observations",
               "scanner_signals")


def build(source: str) -> str:
    src = sqlite3.connect(source)
    syms = [r[0] for r in src.execute(
        "SELECT symbol FROM candles WHERE symbol NOT LIKE '^%' "
        "GROUP BY symbol HAVING COUNT(*)>=300 ORDER BY symbol")][::EVERY]
    idx = [r[0] for r in src.execute(
        "SELECT DISTINCT symbol FROM candles WHERE symbol LIKE '^%' ORDER BY symbol")]
    tmp = os.path.join(tempfile.gettempdir(), "golden_fixture.sqlite3")
    if os.path.exists(tmp):
        os.remove(tmp)
    dst = sqlite3.connect(tmp)
    dst.execute("""CREATE TABLE candles(symbol TEXT NOT NULL, dt TEXT NOT NULL,
        open REAL, high REAL, low REAL, close REAL, volume REAL,
        PRIMARY KEY(symbol,dt))""")
    rows = 0
    for s in syms + idx:
        got = src.execute("""SELECT symbol,dt,open,high,low,close,volume FROM candles
                             WHERE symbol=? ORDER BY dt DESC LIMIT ?""", (s, BARS)).fetchall()
        dst.executemany("INSERT INTO candles VALUES(?,?,?,?,?,?,?)", got)
        rows += len(got)
    # Copy the DDL of EVERY table, not just the ones with data. The engine
    # creates its own tables once at import time against whatever DATA_DB was
    # set then, so a fixture pointed to afterwards never gets them - and the
    # first read of learning_observations or feature_snapshots dies on a
    # missing table, but only when another test module has already run.
    for (name, ddl) in src.execute(
            "SELECT name, sql FROM sqlite_master WHERE type='table' "
            "AND name NOT LIKE 'sqlite_%' AND name<>'candles'").fetchall():
        if not ddl:
            continue
        try:
            dst.execute(ddl)
        except sqlite3.Error as exc:
            print(f"  skipped schema for {name}: {exc}")
            continue
        if name not in COPY_TABLES:
            continue
        got = src.execute(f"SELECT * FROM {name}").fetchall()
        if got:
            dst.executemany(
                f"INSERT INTO {name} VALUES({','.join('?' * len(got[0]))})", got)
    for (name, ddl) in src.execute(
            "SELECT name, sql FROM sqlite_master WHERE type='index' "
            "AND name NOT LIKE 'sqlite_%'").fetchall():
        if ddl:
            try:
                dst.execute(ddl)
            except sqlite3.Error:
                pass
    dst.commit()
    dst.execute("VACUUM")
    dst.close()
    src.close()
    out = os.path.join(OUT, "fixture_market_data.sqlite3.gz")
    with open(tmp, "rb") as f, gzip.open(out, "wb", compresslevel=9) as g:
        shutil.copyfileobj(f, g)
    print(f"{len(syms)} stocks + {len(idx)} indices, {rows:,} candles")
    print(f"{os.path.getsize(tmp)/1e6:.1f} MB -> {os.path.getsize(out)/1e6:.2f} MB gz")
    return out


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    build(sys.argv[1])
