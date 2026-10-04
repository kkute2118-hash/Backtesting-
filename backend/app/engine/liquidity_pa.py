"""Liquidity + price action engine: the owner's framework
(.claude/skills/liquidity-price-action/SKILL.md) written as exact rules so it
can be backtested on stored 5-minute history.

Timeframes: HTF 1 hour (regime, dealing range), MTF 15 minutes (liquidity,
events, MSB, zones), LTF 5 minutes (retest, micro MSB, entry, management).
Nothing looks ahead: a swing exists only once the bars that confirm it have
closed, and the HTF read at any 15-minute bar uses completed hours only.

The analysis order is the framework's own:

  LIQUIDITY -> EVENT -> STRUCTURE/MSB -> DISPLACEMENT -> ZONE (OB/FVG)
  -> PREMIUM/DISCOUNT -> RETEST -> LTF CONFIRMATION -> TARGET LIQUIDITY
  -> STRUCTURAL STOP -> R:R -> SCORE -> DECISION

Each setup that reaches an entry is recorded with every field of section 28
(backtesting mode), including setups the score or R:R would reject, so the
research can measure whether each concept earns its weight (section 29).

Exact definitions (all distances in ATR(14) of the 15-minute chart):

  swing        fractal: high above the `swing_n` bars each side (MTF 2, HTF 3, LTF 2)
  BSL / SSL    untaken swing highs / lows; previous day and week high / low;
               "equal" when two swing highs (lows) sit within `equal_tol` ATR
  run          bar takes the level and closes beyond it by >= 0.1 ATR with a
               body >= 60% of its range and a wick beyond of <= 25%
  grab         bar takes the level and closes back inside in the same bar
  sweep        bar takes the level, then price closes back inside within
               `sweep_bars` bars (slower than a grab)
  MSB          reversal: close through the last confirmed opposite swing that
               formed before the liquidity event (the LH for longs, HL for shorts)
  strong MSB   break bar body >= 60% of range, close beyond >= 0.1 ATR, the
               leg from the sweep extreme took <= `fast_leg` bars, and it left
               displacement (a body >= 1 ATR, or two in a row >= 0.5 ATR) and an FVG
  FVG          three-bar gap: low[i] > high[i-2] (bullish), size >= 0.1 ATR
  OB           last opposite-coloured candle at or just before the sweep extreme
  discount     entry below the 50% of the HTF dealing range (last confirmed
               1-hour swing high and low); premium above it
  OTE          entry at 62-79% retracement of the MSB leg
  retest       price trades back into the zone (FVG if one exists, else OB)
               within `retest_bars` bars, first touch only
  LTF confirm  after the touch, a 5-minute close through the last confirmed
               5-minute swing in the trade direction (micro MSB)
  stop         beyond the sweep extreme plus `stop_buffer` ATR (structural)
  TP1 / TP2    nearest / next untaken opposing liquidity pool; no trade when
               TP1 gives less than `min_rr`
  management   half off at TP1 and stop to break-even; rest at TP2, stop, or
               after `max_hold` 5-minute bars
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

import numpy as np
import pandas as pd

CRYPTO_COST_PER_SIDE = 0.0005 + 0.0001        # taker fee + slippage
CRYPTO_FUNDING_PER_8H = 0.0001                # typical absolute funding rate


@dataclass
class Params:
    swing_n: int = 2
    htf_swing_n: int = 3
    ltf_swing_n: int = 2
    equal_tol: float = 0.10
    sweep_bars: int = 3
    msb_bars: int = 16          # 4 hours for the structure to break after the event
    fast_leg: int = 8
    retest_bars: int = 24       # 6 hours to come back to the zone
    ltf_confirm_bars: int = 36  # 3 hours of 5-minute bars after the touch
    stop_buffer: float = 0.10
    min_rr: float = 1.5
    max_hold: int = 144         # 12 hours of 5-minute bars
    entry: str = "ltf"          # "ltf" (method C) or "limit" (method A)
    pool_max_age: int = 96 * 5  # 15-minute bars a swing pool stays live (5 days)


def is_crypto(sym: str) -> bool:
    return sym.endswith("USDT")


def _atr(h, l, c, n=14):
    pc = np.r_[c[0], c[:-1]]
    tr = np.maximum(h - l, np.maximum(abs(h - pc), abs(l - pc)))
    return pd.Series(tr).rolling(n, min_periods=n).mean().to_numpy()


def _swings(h, l, n):
    """Boolean arrays: bar i is a swing high / low (known only at bar i+n)."""
    w = 2 * n + 1
    hm = pd.Series(h).rolling(w, center=True).max().to_numpy()
    lm = pd.Series(l).rolling(w, center=True).min().to_numpy()
    return h == hm, l == lm


def _resample(df, rule):
    return df.resample(rule, label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()


@dataclass
class Pool:
    price: float
    side: str            # "bsl" or "ssl"
    kind: str            # swing, equal, pdh/pdl, pwh/pwl
    born: int


KIND_RANK = {"pwh": 4, "pwl": 4, "pdh": 3, "pdl": 3, "equal": 2, "swing": 1}


@dataclass
class Setup:
    symbol: str
    family: str                 # reversal (sweep/grab) or continuation (run)
    direction: int
    event_time: str
    event: str                  # sweep / grab / run
    pool_kind: str
    htf_regime: str
    htf_aligned: bool
    msb: str                    # strong / weak / n/a
    displacement: bool
    fvg: bool
    zone: str                   # fvg / ob / level
    discount_ok: bool
    ote: bool
    entry_method: str
    entry_time: str = ""
    entry: float = 0.0
    stop: float = 0.0
    tp1: float = 0.0
    tp2: float = 0.0
    rr1: float = 0.0
    rr2: float = 0.0
    score: int = 0
    decision: str = ""
    reject_reason: str = ""
    exit_time: str = ""
    outcome: str = ""
    r: float = 0.0
    mae_r: float = 0.0
    mfe_r: float = 0.0
    hold_minutes: int = 0
    cost_r: float = 0.0
    extras: dict = field(default_factory=dict)


def score_setup(s: Setup) -> int:
    """Section 22: structure 20, liquidity 20, location 15, price action 15,
    entry confirmation 15, target/risk 15."""
    structure = 20 if s.htf_aligned else (10 if s.htf_regime == "range" else 0)
    liquidity = {"pwh": 20, "pwl": 20, "pdh": 18, "pdl": 18, "equal": 16, "swing": 10}.get(s.pool_kind, 8)
    location = (10 if s.discount_ok else 0) + (5 if s.ote else 0)
    if s.family == "continuation":
        location = 10 if s.discount_ok else 5
    pa = (8 if s.msb == "strong" else 3 if s.msb == "weak" else 5) + (4 if s.displacement else 0) + (3 if s.fvg else 0)
    confirm = 15 if s.entry_method == "ltf" else 7
    tr = 15 if s.rr1 >= 3 else 11 if s.rr1 >= 2 else 7 if s.rr1 >= 1.5 else 0
    return int(structure + liquidity + location + pa + confirm + tr)


def grade(score: int) -> str:
    return ("A+" if score >= 85 else "high" if score >= 75 else "watchlist" if score >= 65
            else "weak" if score >= 55 else "no trade")


class Engine:
    def __init__(self, df5: pd.DataFrame, symbol: str, p: Params | None = None):
        self.sym, self.p = symbol, p or Params()
        self.m5 = df5
        self.m15 = _resample(df5, "15min")
        self.h1 = _resample(df5, "1h")
        m, h = self.m15, self.h1
        self.h, self.l, self.o, self.c = (m[k].to_numpy() for k in ("high", "low", "open", "close"))
        self.t = m.index
        self.atr = _atr(self.h, self.l, self.c)
        self.sh, self.sl = _swings(self.h, self.l, self.p.swing_n)
        # HTF swings, usable from the close of the confirming hour
        hh, hl = h.high.to_numpy(), h.low.to_numpy()
        hsh, hsl = _swings(hh, hl, self.p.htf_swing_n)
        n = self.p.htf_swing_n
        conf_t = h.index + pd.Timedelta(hours=n + 1)
        self.htf_highs = pd.Series(np.where(hsh, hh, np.nan), index=conf_t).dropna()
        self.htf_lows = pd.Series(np.where(hsl, hl, np.nan), index=conf_t).dropna()
        # LTF
        self.l5h, self.l5l, self.l5c = (df5[k].to_numpy() for k in ("high", "low", "close"))
        self.l5t = df5.index
        self.l5sh, self.l5sl = _swings(self.l5h, self.l5l, self.p.ltf_swing_n)
        if is_crypto(symbol):
            self.cost5 = df5["close"].to_numpy() * 2 * CRYPTO_COST_PER_SIDE
        else:
            sp = df5["spread"].fillna(df5["spread"].median())
            self.cost5 = sp.to_numpy()
        self.day_key, self.week_key = self._sessions()

    def _sessions(self):
        if is_crypto(self.sym):
            day = self.t.floor("1D")
        else:
            ny = self.t.tz_convert("America/New_York")
            day = (ny + pd.Timedelta(hours=7)).floor("1D").tz_localize(None)
        day = pd.Index(day)
        week = pd.Index(pd.to_datetime(day).tz_localize(None).to_period("W-SUN").astype(str)) if getattr(pd.to_datetime(day), "tz", None) else pd.Index(pd.to_datetime(day).to_period("W-SUN").astype(str))
        return day, week

    # ------------------------------------------------------------------ HTF
    def htf_read(self, ts, price):
        hs = self.htf_highs.loc[:ts]
        ls = self.htf_lows.loc[:ts]
        if len(hs) < 2 or len(ls) < 2:
            return "unclear", None, None
        h1, h2 = hs.iloc[-2], hs.iloc[-1]
        l1, l2 = ls.iloc[-2], ls.iloc[-1]
        regime = "bull" if h2 > h1 and l2 > l1 else "bear" if h2 < h1 and l2 < l1 else "range"
        return regime, float(hs.iloc[-1]), float(ls.iloc[-1])

    # ---------------------------------------------------------------- run
    def run(self) -> list[Setup]:
        p = self.p
        h, l, o, c, atr = self.h, self.l, self.o, self.c, self.atr
        n = len(c)
        pools: list[Pool] = []
        setups: list[Setup] = []
        pending = []                # candidates waiting for MSB / retest
        last_sh_idx = last_sl_idx = None
        day_hi = day_lo = wk_hi = wk_lo = None
        busy_until = -1             # one position at a time per symbol
        for i in range(1, n):
            a = atr[i]
            if not np.isfinite(a) or a <= 0:
                continue
            # --- previous day / week pools at the session change
            if self.day_key[i] != self.day_key[i - 1]:
                if day_hi is not None:
                    pools = [q for q in pools if q.kind not in ("pdh", "pdl")]
                    pools += [Pool(day_hi, "bsl", "pdh", i), Pool(day_lo, "ssl", "pdl", i)]
                day_hi, day_lo = h[i], l[i]
            else:
                day_hi, day_lo = max(day_hi, h[i]) if day_hi is not None else h[i], min(day_lo, l[i]) if day_lo is not None else l[i]
            if self.week_key[i] != self.week_key[i - 1]:
                if wk_hi is not None:
                    pools = [q for q in pools if q.kind not in ("pwh", "pwl")]
                    pools += [Pool(wk_hi, "bsl", "pwh", i), Pool(wk_lo, "ssl", "pwl", i)]
                wk_hi, wk_lo = h[i], l[i]
            else:
                wk_hi = max(wk_hi, h[i]) if wk_hi is not None else h[i]
                wk_lo = min(wk_lo, l[i]) if wk_lo is not None else l[i]
            # --- swings confirmed now (bar i - swing_n)
            j = i - p.swing_n
            if j >= 0:
                if self.sh[j]:
                    last_sh_idx = j
                    self._add_pool(pools, Pool(h[j], "bsl", "swing", i), a)
                if self.sl[j]:
                    last_sl_idx = j
                    self._add_pool(pools, Pool(l[j], "ssl", "swing", i), a)
            pools = [q for q in pools if q.kind != "swing" and q.kind != "equal" or i - q.born <= p.pool_max_age]

            # --- liquidity events on this bar
            taken_b = [q for q in pools if q.side == "bsl" and h[i] > q.price]
            taken_s = [q for q in pools if q.side == "ssl" and l[i] < q.price]
            for side, taken in (("bsl", taken_b), ("ssl", taken_s)):
                if not taken:
                    continue
                pools = [q for q in pools if q not in taken]
                main = max(taken, key=lambda q: (KIND_RANK[q.kind], q.price if side == "bsl" else -q.price))
                lvl = main.price
                rng = max(h[i] - l[i], 1e-12)
                body = abs(c[i] - o[i])
                if side == "bsl":
                    beyond, back_inside, wick = c[i] - lvl, c[i] < lvl, h[i] - max(o[i], c[i])
                else:
                    beyond, back_inside, wick = lvl - c[i], c[i] > lvl, min(o[i], c[i]) - l[i]
                if back_inside:
                    ev = "grab"
                elif beyond >= 0.1 * a and body >= 0.6 * rng and wick <= 0.25 * rng:
                    ev = "run"
                else:
                    ev = "break"            # decided over the next sweep_bars bars
                pending.append({"stage": "event", "side": side, "level": lvl, "kind": main.kind,
                                "event": ev, "i": i, "extreme": h[i] if side == "bsl" else l[i],
                                "ref_sh": last_sh_idx, "ref_sl": last_sl_idx})

            # --- advance candidates
            still = []
            for cd in pending:
                res = self._advance(cd, i, pools)
                if res is None:
                    continue
                if isinstance(res, Setup):
                    if i > busy_until:
                        self._enter_and_manage(res, cd, i, pools)
                        setups.append(res)
                        if res.decision == "TRADE" and res.exit_time:
                            busy_until = cd.get("exit_i15", i)
                    continue
                still.append(cd)
            pending = still[-50:]
        return setups

    def _add_pool(self, pools, new, a):
        for q in pools:
            if q.side == new.side and q.kind in ("swing", "equal") and abs(q.price - new.price) <= self.p.equal_tol * a:
                q.kind, q.born = "equal", new.born
                q.price = max(q.price, new.price) if new.side == "bsl" else min(q.price, new.price)
                return
        pools.append(new)
        if len(pools) > 80:
            del pools[0]

    # ----------------------------------------------------------- state machine
    def _advance(self, cd, i, pools):
        """Returns cd to keep waiting, None to drop, or a Setup at its entry bar."""
        p = self.p
        h, l, o, c, atr = self.h, self.l, self.o, self.c, self.atr
        bull_rev = cd["side"] == "ssl"           # SSL taken -> look for longs
        d = 1 if bull_rev else -1
        age = i - cd["i"]
        if cd["stage"] == "event":
            if age == 0:
                if cd["event"] == "grab":
                    cd["stage"], cd["family"] = "msb", "reversal"
                elif cd["event"] == "run":
                    cd["stage"], cd["family"] = "retest_level", "continuation"
                    cd["run_i"] = i
                return cd
            # a break: track extreme, decide sweep vs run
            cd["extreme"] = min(cd["extreme"], l[i]) if bull_rev else max(cd["extreme"], h[i])
            back = c[i] > cd["level"] if bull_rev else c[i] < cd["level"]
            if back:
                cd["event"], cd["stage"], cd["family"] = "sweep", "msb", "reversal"
                return cd
            if age >= p.sweep_bars:
                return None                      # slow acceptance, neither clean run nor sweep
            return cd

        if cd["stage"] == "msb":
            # extreme extends while waiting
            if (bull_rev and l[i] < cd["extreme"]) or (not bull_rev and h[i] > cd["extreme"]):
                if age > p.sweep_bars:
                    return None                  # trap failed: price kept going
                cd["extreme"] = l[i] if bull_rev else h[i]
            ref = cd["ref_sh"] if bull_rev else cd["ref_sl"]
            if ref is None:
                return None
            ref_px = h[ref] if bull_rev else l[ref]
            broke = c[i] > ref_px if bull_rev else c[i] < ref_px
            if broke:
                return self._on_msb(cd, i, ref_px)
            if age > p.msb_bars:
                return None
            return cd

        if cd["stage"] in ("retest", "retest_level"):
            if cd["stage"] == "retest_level":
                return self._continuation(cd, i, pools)
            return self._retest(cd, i, pools)
        return None

    def _on_msb(self, cd, i, ref_px):
        p = self.p
        h, l, o, c, a = self.h, self.l, self.o, self.c, self.atr[i]
        bull = cd["side"] == "ssl"
        rng = max(h[i] - l[i], 1e-12)
        body = abs(c[i] - o[i])
        beyond = (c[i] - ref_px) if bull else (ref_px - c[i])
        # leg from the extreme bar to the break
        ext_i = cd["i"]
        for k in range(cd["i"], i + 1):
            if (bull and l[k] <= cd["extreme"]) or (not bull and h[k] >= cd["extreme"]):
                ext_i = k
        leg = range(ext_i, i + 1)
        bodies = [(c[k] - o[k]) * (1 if bull else -1) for k in leg]
        disp = any(b >= 1.0 * a for b in bodies) or any(
            bodies[k] >= 0.5 * a and bodies[k + 1] >= 0.5 * a for k in range(len(bodies) - 1))
        fvgs = []
        for k in range(max(ext_i + 2, 2), i + 1):
            if bull and l[k] - h[k - 2] >= 0.1 * a:
                fvgs.append((h[k - 2], l[k]))
            if not bull and l[k - 2] - h[k] >= 0.1 * a:
                fvgs.append((h[k], l[k - 2]))
        strong = body >= 0.6 * rng and beyond >= 0.1 * a and (i - ext_i) <= p.fast_leg and disp and bool(fvgs)
        # order block: last opposite candle at/just before the extreme
        ob = None
        for k in range(ext_i, max(ext_i - 6, 0), -1):
            if (bull and c[k] < o[k]) or (not bull and c[k] > o[k]):
                ob = (l[k], h[k])
                break
        if fvgs:
            zone, zlo, zhi = "fvg", fvgs[0][0], fvgs[0][1]
        elif ob:
            zone, (zlo, zhi) = "ob", ob
        else:
            return None
        leg_hi = max(h[k] for k in leg) if bull else cd["extreme"]
        leg_lo = cd["extreme"] if bull else min(l[k] for k in leg)
        cd.update(stage="retest", msb="strong" if strong else "weak", disp=disp, fvg=bool(fvgs),
                  zone=zone, zlo=zlo, zhi=zhi, msb_i=i, leg_hi=leg_hi, leg_lo=leg_lo)
        return cd

    def _retest(self, cd, i, pools):
        p = self.p
        h, l, c = self.h, self.l, self.c
        bull = cd["side"] == "ssl"
        if i == cd["msb_i"]:
            return cd
        if (bull and c[i] < cd["extreme"]) or (not bull and c[i] > cd["extreme"]):
            return None                          # invalidated before the retest
        if i - cd["msb_i"] > p.retest_bars:
            return None
        touched = l[i] <= cd["zhi"] if bull else h[i] >= cd["zlo"]
        if not touched:
            return cd
        return self._make_setup(cd, i, pools, "reversal")

    def _continuation(self, cd, i, pools):
        """Run -> continuation: first retest of the broken level (S/R flip)."""
        p = self.p
        h, l, c, a = self.h, self.l, self.c, self.atr[i]
        bull = cd["side"] == "bsl"               # BSL run -> longs
        lvl = cd["level"]
        if i == cd["run_i"]:
            return cd
        if i - cd["run_i"] > p.retest_bars:
            return None
        if (bull and c[i] < lvl - 0.3 * a) or (not bull and c[i] > lvl + 0.3 * a):
            return None                          # flip failed
        touched = l[i] <= lvl + 0.1 * a if bull else h[i] >= lvl - 0.1 * a
        if not touched:
            return cd
        run_i = cd["run_i"]
        # Invalidation from bars already closed: the pullback extreme before
        # this bar, but never closer than the broken level itself.
        prev_lo, prev_hi = min(l[run_i:i]), max(h[run_i:i])
        cd.update(msb="n/a", disp=True, fvg=False, zone="level",
                  zlo=lvl - 0.1 * a, zhi=lvl + 0.1 * a,
                  extreme=(min(prev_lo, lvl) if bull else max(prev_hi, lvl)),
                  leg_hi=prev_hi, leg_lo=prev_lo)
        return self._make_setup(cd, i, pools, "continuation")

    def _make_setup(self, cd, i, pools, family):
        d = (1 if cd["side"] == "ssl" else -1) if family == "reversal" else (1 if cd["side"] == "bsl" else -1)
        ts = self.t[i]
        regime, rh, rl = self.htf_read(ts, self.c[i])
        aligned = (regime == "bull" and d > 0) or (regime == "bear" and d < 0)
        cd["d"] = d
        cd["touch_i"] = i
        cd["regime"], cd["aligned"] = regime, aligned
        cd["range"] = (rh, rl)
        return Setup(symbol=self.sym, family=family, direction=d,
                     event_time=str(self.t[cd["i"]]), event=cd["event"], pool_kind=cd["kind"],
                     htf_regime=regime, htf_aligned=aligned, msb=cd["msb"], displacement=cd["disp"],
                     fvg=cd["fvg"], zone=cd["zone"], discount_ok=False, ote=False,
                     entry_method=self.p.entry)

    # ----------------------------------------------------- entry & management
    def _enter_and_manage(self, s: Setup, cd, i15, pools):
        p = self.p
        d = cd["d"]
        a = self.atr[i15]
        bar_start = self.t[i15]
        # 5-minute bars of the touching 15-minute bar onward
        k0 = self.l5t.searchsorted(bar_start)
        k_end = min(k0 + 3 + p.ltf_confirm_bars, len(self.l5c))
        entry_k = None
        if p.entry == "limit":
            px = cd["zhi"] if d > 0 else cd["zlo"]
            for k in range(k0, min(k0 + 3, len(self.l5c))):
                if (d > 0 and self.l5l[k] <= px) or (d < 0 and self.l5h[k] >= px):
                    entry_k, entry = k, px
                    break
        else:
            # micro MSB on 5 minutes after the touch
            last_sw = None
            touched = False
            for k in range(max(k0 - 12, 0), k_end):
                jn = k - p.ltf_swing_n
                if jn >= 0 and ((d > 0 and self.l5sh[jn]) or (d < 0 and self.l5sl[jn])):
                    last_sw = self.l5h[jn] if d > 0 else self.l5l[jn]
                if k < k0:
                    continue
                if not touched:
                    touched = (self.l5l[k] <= cd["zhi"]) if d > 0 else (self.l5h[k] >= cd["zlo"])
                    if not touched:
                        continue
                if (d > 0 and self.l5l[k] < cd["extreme"]) or (d < 0 and self.l5h[k] > cd["extreme"]):
                    break                               # invalidated
                if last_sw is not None and ((d > 0 and self.l5c[k] > last_sw) or (d < 0 and self.l5c[k] < last_sw)):
                    entry_k, entry = k, self.l5c[k]
                    break
        if entry_k is None:
            s.decision, s.reject_reason = "NO TRADE", "no LTF confirmation"
            return
        stop = cd["extreme"] - d * p.stop_buffer * a
        risk = (entry - stop) * d
        if risk <= 0:
            s.decision, s.reject_reason = "NO TRADE", "entry beyond invalidation"
            return
        # location
        rh, rl = cd["range"]
        if rh is not None and rl is not None and rh > rl:
            eq = (rh + rl) / 2
            s.discount_ok = entry < eq if d > 0 else entry > eq
        leg = cd["leg_hi"] - cd["leg_lo"]
        if leg > 0:
            retr = (cd["leg_hi"] - entry) / leg if d > 0 else (entry - cd["leg_lo"]) / leg
            s.ote = 0.62 <= retr <= 0.79
        # targets: untaken opposing pools beyond entry, nearest first
        side = "bsl" if d > 0 else "ssl"
        tgts = sorted((q for q in pools if q.side == side and (q.price - entry) * d > 0),
                      key=lambda q: (q.price - entry) * d)
        if not tgts:
            s.decision, s.reject_reason = "NO TRADE", "no target liquidity"
            s.entry, s.stop = float(entry), float(stop)
            return
        tp1 = tgts[0].price
        major = [q for q in tgts[1:] if KIND_RANK[q.kind] >= 2]
        tp2 = (major[0].price if major else tgts[1].price if len(tgts) > 1 else tp1)
        s.entry, s.stop, s.tp1, s.tp2 = float(entry), float(stop), float(tp1), float(tp2)
        s.rr1 = round((tp1 - entry) * d / risk, 2)
        s.rr2 = round((tp2 - entry) * d / risk, 2)
        s.entry_time = str(self.l5t[entry_k])
        s.score = score_setup(s)
        s.extras = {"grade": grade(s.score), "target_kind": tgts[0].kind}
        if s.rr1 < p.min_rr:
            s.decision, s.reject_reason = "NO TRADE", "TP1 below minimum R:R"
            return
        s.decision = "TRADE"
        self._manage(s, cd, entry_k, entry, stop, tp1, tp2, d, risk)

    def _manage(self, s, cd, k, entry, stop, tp1, tp2, d, risk):
        p = self.p
        H, L, C = self.l5h, self.l5l, self.l5c
        cost = self.cost5[k]
        half_done = False
        realized = 0.0
        mae = mfe = 0.0
        cur_stop = stop
        end = min(k + 1 + p.max_hold, len(C))
        exit_k = end - 1
        outcome = "time"
        # A limit fill can be stopped inside its own bar: count it as a loss.
        first = k if p.entry == "limit" else k + 1
        for j in range(first, end):
            if j == k:
                if (L[j] <= cur_stop) if d > 0 else (H[j] >= cur_stop):
                    realized, exit_k, outcome = (cur_stop - entry) * d / risk, j, "stop"
                    mae = -1.0
                    break
                continue
            mfe = max(mfe, (H[j] - entry if d > 0 else entry - L[j]) / risk)
            mae = min(mae, (L[j] - entry if d > 0 else entry - H[j]) / risk)
            hit_stop = L[j] <= cur_stop if d > 0 else H[j] >= cur_stop
            if hit_stop:                                   # stop first on a shared bar
                rem = 0.5 if half_done else 1.0
                realized += rem * (cur_stop - entry) * d / risk
                exit_k, outcome = j, ("breakeven" if half_done else "stop")
                break
            if not half_done and ((H[j] >= tp1) if d > 0 else (L[j] <= tp1)):
                if tp2 == tp1:
                    realized += (tp1 - entry) * d / risk
                    exit_k, outcome = j, "tp1"
                    break
                realized += 0.5 * (tp1 - entry) * d / risk
                half_done, cur_stop = True, entry
                continue
            if half_done and ((H[j] >= tp2) if d > 0 else (L[j] <= tp2)):
                realized += 0.5 * (tp2 - entry) * d / risk
                exit_k, outcome = j, "tp2"
                break
        else:
            rem = 0.5 if half_done else 1.0
            realized += rem * (C[exit_k] - entry) * d / risk
            outcome = "tp1+time" if half_done else "time"
        held_min = int((self.l5t[exit_k] - self.l5t[k]).total_seconds() // 60)
        cost_px = cost
        if is_crypto(self.sym):
            cost_px += entry * CRYPTO_FUNDING_PER_8H * (held_min / 480)
        s.cost_r = round(cost_px / risk, 3)
        s.r = round(realized - s.cost_r, 3)
        s.mae_r, s.mfe_r = round(mae, 2), round(mfe, 2)
        s.exit_time, s.outcome, s.hold_minutes = str(self.l5t[exit_k]), outcome, held_min
        cd["exit_i15"] = self.t.searchsorted(self.l5t[exit_k])


def backtest(df5: pd.DataFrame, symbol: str, p: Params | None = None) -> pd.DataFrame:
    rows = [asdict(s) for s in Engine(df5, symbol, p).run()]
    return pd.DataFrame(rows)


def metrics(r: pd.Series) -> dict:
    """Section 28: win rate, average R, expectancy, profit factor, drawdown, streaks."""
    r = pd.Series(r, dtype=float).dropna()
    if r.empty:
        return {"trades": 0}
    wins, losses = r[r > 0], r[r <= 0]
    eq = r.cumsum()
    streak = cur = 0
    for x in r:
        cur = cur + 1 if x <= 0 else 0
        streak = max(streak, cur)
    return {"trades": int(len(r)), "win_pct": round(len(wins) / len(r) * 100, 1),
            "avg_R": round(r.mean(), 3), "expectancy_R": round(r.mean(), 3),
            "profit_factor": round(wins.sum() / -losses.sum(), 2) if losses.sum() < 0 else None,
            "total_R": round(r.sum(), 1), "max_drawdown_R": round((eq - eq.cummax()).min(), 1),
            "max_consecutive_losses": int(streak)}
