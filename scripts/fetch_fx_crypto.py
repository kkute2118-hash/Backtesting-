#!/usr/bin/env python3
"""Download free intraday history for forex and crypto and publish it as
assets of the GitHub Release `fx-crypto-data`.

No API key is needed for either source:

- Crypto: Binance USD-M perpetual futures 5-minute candles and funding rates
  from data.binance.vision (Binance's public bulk archive; monthly files,
  daily files for the current month).
- Forex and gold: Dukascopy's public datafeed, 1-minute BID and ASK candles,
  one file per day, resampled here to 5 minutes with the average and maximum
  BID/ASK spread of each bar (spreads widen at the daily rollover and around
  news, which an intraday study has to pay for).

Runs on a GitHub runner (.github/workflows/fx-crypto-data.yml) because Claude
sessions cannot reach these hosts. Output, one file per symbol:

    <SYMBOL>_5m.csv.gz       time (UTC), open, high, low, close, volume[, spread, max_spread]
    <SYMBOL>_funding.csv.gz  time (UTC), funding_rate          (crypto only)

Usage: python scripts/fetch_fx_crypto.py OUT_DIR [--start 2021-01-01] [--upload]
Upload needs GITHUB_REPOSITORY and GH_PUSH_TOKEN (contents: write).
"""

from __future__ import annotations

import argparse
import io
import lzma
import os
import struct
import sys
import time
import urllib.parse
import zipfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
from release_backup import API, call  # noqa: E402

CRYPTO = ("BTCUSDT", "ETHUSDT", "SOLUSDT", "BNBUSDT", "XRPUSDT")
# Dukascopy symbol -> price scale (prices are stored as integers).
FOREX = {"EURUSD": 1e5, "GBPUSD": 1e5, "USDJPY": 1e3, "AUDUSD": 1e5, "XAUUSD": 1e3}
RELEASE_TAG = "fx-crypto-data"
BINANCE = "https://data.binance.vision/data/futures/um"
DUKA = "https://datafeed.dukascopy.com/datafeed"
KLINE_COLS = ["open_time", "open", "high", "low", "close", "volume", "close_time",
              "quote_volume", "trades", "taker_buy_volume", "taker_buy_quote", "ignore"]

session = requests.Session()
session.headers["User-Agent"] = "Mozilla/5.0 (research data download)"


def _get(url, tries=5):
    last = None
    for i in range(tries):
        try:
            r = session.get(url, timeout=60)
            if r.status_code == 404:
                return None
            if r.ok:
                return r.content
            last = f"HTTP {r.status_code} {r.text[:120]!r}"
        except requests.RequestException as exc:
            last = f"{type(exc).__name__}: {exc}"[:200]
        time.sleep(2 ** i)
    raise RuntimeError(f"download failed: {url} ({last})")


def _months(start: date, end: date):
    y, m = start.year, start.month
    while (y, m) < (end.year, end.month):
        yield y, m
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)


def _zip_csv(blob, names=None):
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        raw = z.read(z.namelist()[0])
    head = raw[:64].decode("ascii", "replace")
    has_header = not head[:1].isdigit()
    return pd.read_csv(io.BytesIO(raw), header=0 if has_header else None,
                       names=None if has_header else names)


def _epoch(series):
    s = pd.to_numeric(series)
    unit = "us" if s.iloc[0] > 1e14 else "ms"           # Binance moved some files to microseconds
    return pd.to_datetime(s, unit=unit, utc=True)


def crypto_klines(sym, start, end):
    urls = [f"{BINANCE}/monthly/klines/{sym}/5m/{sym}-5m-{y}-{m:02d}.zip" for y, m in _months(start, end)]
    d = date(end.year, end.month, 1)
    while d < end:
        urls.append(f"{BINANCE}/daily/klines/{sym}/5m/{sym}-5m-{d}.zip")
        d += timedelta(days=1)
    with ThreadPoolExecutor(8) as ex:
        blobs = list(ex.map(_get, urls))
    frames = []
    for blob in blobs:
        if blob:
            df = _zip_csv(blob, KLINE_COLS)
            df.columns = KLINE_COLS[:len(df.columns)]
            frames.append(df)
    df = pd.concat(frames, ignore_index=True)
    out = pd.DataFrame({"time": _epoch(df["open_time"])})
    for c in ("open", "high", "low", "close", "volume", "taker_buy_volume"):
        out[c] = pd.to_numeric(df[c])
    out["trades"] = pd.to_numeric(df["trades"]).astype("int64")
    return out.drop_duplicates("time").sort_values("time").reset_index(drop=True)


def crypto_funding(sym, start, end):
    urls = [f"{BINANCE}/monthly/fundingRate/{sym}/{sym}-fundingRate-{y}-{m:02d}.zip"
            for y, m in _months(start, end)]
    with ThreadPoolExecutor(8) as ex:
        blobs = list(ex.map(_get, urls))
    frames = [_zip_csv(b, ["calc_time", "funding_interval_hours", "last_funding_rate"]) for b in blobs if b]
    if not frames:
        return pd.DataFrame(columns=["time", "funding_rate"])
    df = pd.concat(frames, ignore_index=True)
    out = pd.DataFrame({"time": _epoch(df["calc_time"]), "funding_rate": pd.to_numeric(df["last_funding_rate"])})
    return out.drop_duplicates("time").sort_values("time").reset_index(drop=True)


def _duka_day(sym, side, d):
    # Months are zero-based in Dukascopy URLs.
    blob = _get(f"{DUKA}/{sym}/{d.year}/{d.month - 1:02d}/{d.day:02d}/{side}_candles_min_1.bi5")
    if not blob:
        return None
    raw = lzma.decompress(blob)
    n = len(raw) // 24
    if not n:
        return None
    rows = struct.iter_unpack(">5if", raw[:n * 24])   # seconds, open, close, low, high, volume
    df = pd.DataFrame(rows, columns=["sec", "open", "close", "low", "high", "volume"])
    df = df[df.volume > 0]                             # Dukascopy pads closed minutes with zero volume
    df["time"] = pd.Timestamp(d, tz="UTC") + pd.to_timedelta(df.pop("sec"), unit="s")
    return df


def forex_5m(sym, start, end):
    scale = FOREX[sym]
    days = [start + timedelta(days=i) for i in range((end - start).days)]
    days = [d for d in days if d.weekday() != 5]        # nothing trades on Saturday
    out = {}
    for side in ("BID", "ASK"):
        failed = []

        def day(d):
            try:
                return _duka_day(sym, side, d)
            except RuntimeError as exc:
                failed.append(str(exc))
                return None
        # Dukascopy throttles parallel clients; two at a time stays under it.
        with ThreadPoolExecutor(2) as ex:
            parts = [p for p in ex.map(day, days) if p is not None]
        if failed:
            print(f"{sym} {side}: {len(failed)} of {len(days)} days failed, first: {failed[0]}", flush=True)
        if len(failed) > 0.05 * len(days) or not parts:
            raise RuntimeError(f"{sym} {side}: too many failed days")
        df = pd.concat(parts, ignore_index=True).set_index("time").sort_index()
        df[["open", "close", "low", "high"]] /= scale
        bad = (df.low > df[["open", "close"]].min(axis=1) + 1e-9) | (df.high < df[["open", "close"]].max(axis=1) - 1e-9)
        if bad.mean() > 0.01:
            raise RuntimeError(f"{sym} {side}: {bad.mean():.1%} of candles fail low<=open,close<=high")
        out[side] = df
    bid, ask = out["BID"], out["ASK"]
    spread = (ask["close"] - bid["close"]).reindex(bid.index)
    agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    bars = bid.resample("5min", label="left", closed="left").agg(agg).dropna(subset=["open"])
    bars["spread"] = spread.resample("5min", label="left", closed="left").mean().reindex(bars.index)
    bars["max_spread"] = spread.resample("5min", label="left", closed="left").max().reindex(bars.index)
    return bars.reset_index()


def upload(files, repo, token):
    status, rel = call("GET", f"{API}/repos/{repo}/releases/tags/{RELEASE_TAG}", token)
    if status == 404:
        import json
        status, rel = call("POST", f"{API}/repos/{repo}/releases", token, json.dumps({
            "tag_name": RELEASE_TAG, "target_commitish": "main", "name": "Forex and crypto data",
            "prerelease": True,
            "body": "5-minute forex (Dukascopy) and crypto perpetual (Binance) history for "
                    "research, written by .github/workflows/fx-crypto-data.yml. Not a software release.",
        }).encode())
    if status not in (200, 201):
        raise RuntimeError(f"could not open release: {status} {rel}")
    assets = {a["name"]: a["id"] for a in rel.get("assets", [])}
    upload_url = rel["upload_url"].split("{")[0]
    for path in files:
        if path.name in assets:
            call("DELETE", f"{API}/repos/{repo}/releases/assets/{assets[path.name]}", token)
        payload = path.read_bytes()
        status, out = call("POST", f"{upload_url}?name={urllib.parse.quote(path.name)}", token,
                           payload, "application/gzip")
        if status != 201:
            raise RuntimeError(f"upload {path.name}: {status} {str(out)[:200]}")
        print(f"uploaded {path.name} ({len(payload) / 1048576:.1f} MB)", flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("out")
    ap.add_argument("--start", default="2021-01-01")
    ap.add_argument("--only", default="", help="comma-separated symbols")
    ap.add_argument("--upload", action="store_true")
    a = ap.parse_args()
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    start = date.fromisoformat(a.start)
    end = datetime.now(timezone.utc).date()
    only = {s for s in a.only.split(",") if s}
    written = []
    for sym in CRYPTO:
        if only and sym not in only:
            continue
        t = time.time()
        k = crypto_klines(sym, start, end)
        k.to_csv(out / f"{sym}_5m.csv.gz", index=False)
        crypto_funding(sym, start, end).to_csv(out / f"{sym}_funding.csv.gz", index=False)
        written += [out / f"{sym}_5m.csv.gz", out / f"{sym}_funding.csv.gz"]
        print(f"{sym}: {len(k):,} bars {k.time.iloc[0]} to {k.time.iloc[-1]} ({time.time() - t:.0f}s)", flush=True)
    for sym in FOREX:
        if only and sym not in only:
            continue
        t = time.time()
        b = forex_5m(sym, start, end)
        b.to_csv(out / f"{sym}_5m.csv.gz", index=False)
        written.append(out / f"{sym}_5m.csv.gz")
        print(f"{sym}: {len(b):,} bars {b.time.iloc[0]} to {b.time.iloc[-1]}, "
              f"median spread {b.spread.median():.5g} ({time.time() - t:.0f}s)", flush=True)
    if a.upload:
        upload(written, os.environ["GITHUB_REPOSITORY"], os.environ["GH_PUSH_TOKEN"])


if __name__ == "__main__":
    main()
