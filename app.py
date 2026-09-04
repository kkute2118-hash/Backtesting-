"""Adaptive Trading Intelligence Lab — Streamlit interface.

All engine logic lives in core.py; this file is the UI on top of it. Run with:
    streamlit run app.py
"""

import streamlit as st

st.set_page_config(page_title="Adaptive Trading Intelligence Lab — Professional Final",
                   page_icon="🧠", layout="wide")

# The engine defines several deliberately private helpers (_db, _read_cache,
# _metric_get ...) that the UI below uses. `from core import *` skips
# underscore names, so bind the whole module namespace instead of maintaining
# a hand-written import list that would silently rot as the engine changes.
import core as _core
globals().update({k: v for k, v in vars(_core).items() if not k.startswith("__")})

# ========================= UI =========================

st.title("🧠 Adaptive Trading Intelligence Lab — Professional Final")
st.caption("Dhan-first • persistent local data • S1–S3 exact • S4 SEPA (Minervini) • no-lookahead walk-forward • adaptive learning • fundamentals/news enrichment")

tabs=st.tabs([
    "🏠 Dashboard",
    "📡 Daily Scanner",
    "📊 Backtest",
    "🔬 Forward Testing",
    "🧠 Market Learning",
    "💎 Long-Term Fundamentals",
    "🏢 Small/Micro Safety",
    "⚡ Live Monitor",
    "💾 Dhan Data Manager",
    "🎯 S4 SEPA Strategy",
    "🧪 Custom Strategy",
    "🧬 Research & Risk Control",
    "🎓 Strategy Coach",
    "💱 Forex/Crypto SMC",
    "🚨 Early Warning Radar"
])

with tabs[0]:
    a,b,c,d=st.columns(4)
    a.metric("Forward-test gate","≥85")
    b.metric("Strategies","4")
    c.metric("MTF","Monthly / Weekly / Daily")
    d.metric("Real orders","OFF")
    st.info("The score ranks setup quality. It is not a guaranteed probability of winning.")
    st.markdown("""
**Trading engine:** Strategies 1–4 → MTF → market regime → setup score → forward test.

**Investment engine:** Fundamental Model A / B scans the broader cash market separately.

**Safety engine:** Small/micro-cap liquidity and abnormal-volatility checks reduce risk but do not change the four strategies.
""")

with tabs[1]:
    st.subheader("📡 Daily Live Scanner")
    st.caption("First audit the raw strategy signals. Then turn on the score gate. Each strategy is scanned independently.")

    a,b,c = st.columns(3)
    universes = a.multiselect(
        "Trading universes",
        ["Nifty 500","Nifty Smallcap 100","Nifty Smallcap 250","Nifty Midcap 150"],
        ["Nifty 500","Nifty Smallcap 100","Nifty Smallcap 250","Nifty Midcap 150"],
        key="scan_universes"
    )
    scan_mode = b.selectbox(
        "Scan mode",
        ["All qualifying setups + scores", "Exact raw signals (audit)"],
        key="scan_mode_v4"
    )
    min_score = c.number_input(
        "Minimum score",
        value=85,
        min_value=0,
        max_value=100,
        key="scan_score_v4"
    )

    d,e = st.columns(2)
    selected_strategies = d.multiselect(
        "Strategies to scan independently",
        [1,2,3,4],
        [1,2,3,4],
        key="scan_strategies_v4"
    )
    result_mode = e.selectbox(
        "Results",
        ["ALL qualifying setups","Top 10","Top 25","Top 50"],
        key="scan_result_mode_v4"
    )

    st.markdown("### 📅 Data Freshness")
    try:
        _freshness_universe=set()
        for u in universes:
            _freshness_universe.update(index_universe(u))
        scan_freshness_tickers=sorted(_freshness_universe)
    except Exception as ex:
        scan_freshness_tickers=[]
        st.caption(f"Could not verify data freshness (index universe fetch failed): {ex}")
    render_data_freshness_banner(scan_freshness_tickers)

    fcol1, fcol2 = st.columns([1, 1])
    with fcol1:
        if st.button("⬇️ TOP-UP LATEST SESSIONS NOW", type="primary", key="scan_topup_latest",
                     disabled=not scan_freshness_tickers):
            if not dhan_configured():
                st.error("Dhan is not configured. Add DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN to Streamlit Secrets.")
            else:
                topbar = st.progress(0.0)
                try:
                    with st.spinner(f"Requesting only the last {LATEST_SYNC_TAIL_DAYS} days for "
                                    f"{len(scan_freshness_tickers):,} stocks..."):
                        summary = sync_latest_sessions(
                            scan_freshness_tickers,
                            progress_cb=lambda frac: topbar.progress(min(1.0, frac))
                        )
                    topbar.empty()
                    st.success(
                        f"✅ Top-up complete — {summary['advanced']:,} of {summary['symbols']:,} stocks "
                        f"advanced. Newest stored session: {summary['latest'] or '—'}."
                    )
                    if summary["errors"]:
                        st.warning("Dhan errors during top-up: " + " | ".join(summary["errors"][:6]))
                    st.rerun()
                except Exception as ex:
                    topbar.empty()
                    st.error(f"Top-up failed: {ex}")
        st.caption(
            f"Fetches only the last {LATEST_SYNC_TAIL_DAYS} days per stock and re-requests the newest "
            "stored bars, so a candle saved mid-session is corrected once it really closes. Much faster "
            "than the full Data Manager sync."
        )
    with fcol2:
        use_live_prices = st.checkbox(
            "Use live intraday price (scan against the current price)",
            value=nse_market_is_open(),
            key="scan_use_live_price"
        )
        st.caption(
            "While the session is open this overlays today's still-forming candle "
            "(open/high/low/LTP/volume from Dhan's bulk quote feed) on top of the stored daily "
            "history, in memory only. Stored candles are never overwritten with a partial bar."
        )

    st.info(
        "Every selected stock is tested independently against every selected strategy. "
        "A stock appears under a strategy only when ALL rules of that strategy pass. "
        "Scores rank qualifying setups; the ≥85 gate is used only for forward testing."
    )

    best_top_placeholder = st.empty()

    st.subheader("⚡ Continuous Scan Mode")
    cc1, cc2, cc3 = st.columns(3)
    cc1.metric("Historical cache", "ON")
    cc2.metric("Feature cache", "ON")
    cc3.metric("Live layer", "Dhan WebSocket")
    st.caption(
        "Daily/weekly/monthly strategy state is cached. The live layer tracks only candidates and "
        "re-ranks them from the Dhan feed instead of rebuilding the entire market every minute."
    )


    if st.button("🔄 Scan Market Now", type="primary", key="scan_button_v4"):
        try:
            if not dhan_configured():
                st.error("Dhan is not configured. Add DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN to Streamlit Secrets.")
                st.stop()
            if not selected_strategies:
                st.warning("Select at least one strategy.")
                st.stop()
            if not universes:
                st.warning("Select at least one universe.")
                st.stop()

            universe = set()
            for u in universes:
                universe.update(index_universe(u))
            tickers = sorted(universe)

            # Scanner is LOCAL-ONLY. Data acquisition belongs exclusively to the
            # Data Manager / explicit sync action. This prevents every scan from
            # becoming another Dhan historical download.
            t0 = time.perf_counter()
            with st.spinner(f"Loading local price cache for {len(tickers):,} stocks..."):
                data = load_scan_dataset(tickers)
            scan_load_seconds = time.perf_counter() - t0

            if not data:
                st.error("Local dataset is empty/incomplete. Use Data Manager → SYNC ONLY MISSING DATA once, then scan again. Scanner itself never downloads historical data.")
                st.stop()

            # ---- Live intraday overlay -------------------------------------
            # Stored daily candles can never be newer than the last completed
            # session, so an in-session scan against them is always a day late.
            # When enabled, today's forming candle is merged in memory so the
            # strategies evaluate the price that exists right now.
            scan_live_bars = {}
            scan_price_asof = None
            if st.session_state.get("scan_use_live_price"):
                if not nse_market_is_open():
                    st.info("Live price overlay skipped — the NSE cash session is closed, so the last stored close already is the current price.")
                else:
                    with st.spinner("Fetching live intraday prices from Dhan..."):
                        data, scan_live_bars = attach_live_bars(data)
                    if scan_live_bars:
                        scan_price_asof = max(b["ts"] for b in scan_live_bars.values())
                        st.success(
                            f"🟢 Live overlay applied to {len(scan_live_bars):,} of {len(data):,} stocks "
                            f"(as of {scan_price_asof})."
                        )
                    else:
                        st.warning(
                            "Live price overlay requested but Dhan returned no quotes — this scan is "
                            "running on the last stored close. Check the Dhan Connection Test."
                        )

            scan_data_last_date = max(
                (pd.Timestamp(df.index[-1]).date() for df in data.values()), default=None
            )
            st.caption(
                f"Scanning against price data as of "
                f"{scan_data_last_date.strftime('%d-%b-%Y') if scan_data_last_date else '—'}"
                + (f" · live tick {scan_price_asof}" if scan_price_asof else " · last completed close")
            )

            proxy = max(data.values(), key=len)
            regime, regime_score = regime_from_index(proxy)

            if not data:
                st.error(
                    "Dhan returned no price data for the selected universe. "
                    "The scanner cannot generate signals until price data is available."
                )
                st.stop()

            bar = st.progress(0)
            stats = {}
            ml_model = {}
            # The scan itself lives in core.scan_dataset() so the Streamlit
            # scanner and the scheduled daily job run identical logic.
            result = scan_dataset(
                data, selected_strategies, regime,
                progress_cb=lambda frac: bar.progress(min(1.0, frac)),
                stats=stats
            )
            ml_model = stats.get("ml_model", {})

            # Persist every scanner-qualified signal; mark only the configured
            # forward-test gate as selected. This survives Streamlit reruns.
            if not result.empty:
                persist_scanner_signals(result, min_score)

                # Convert selected signals into durable forward-test records.
                added=add_forward_candidates(
                    result[result["Score"]>=min_score].copy()
                )
                st.session_state["forward_last_added"]=int(added)

            with best_top_placeholder.container():
                st.subheader("🏆 BEST SETUPS — Score Highest First")
                if result.empty:
                    st.warning("No complete-rule setups found in this scan.")
                else:
                    _top=result.sort_values(["Score","Strategy","Ticker"],ascending=[False,True,True])
                    _best=_top[_top["Score"]>=min_score]
                    if _best.empty:
                        st.info(f"No complete-rule setup currently meets the ≥{min_score} forward-test gate.")
                    else:
                        st.dataframe(_best,width='stretch',hide_index=True)
                    st.caption("Every displayed setup has already passed ALL rules of its own strategy. Score only ranks valid setups.")


            gate_audit = stats.get("safety_gate_audit", pd.DataFrame())
            gate_excluded = stats.get("safety_gate_excluded", 0)
            with st.expander(
                f"🛡️ Universe safety/liquidity gate — {gate_excluded:,} stock(s) excluded before any strategy ran",
                expanded=False,
            ):
                st.caption(
                    "Applied to every selected strategy (S1-S4) before strategy_signal() runs: "
                    "manipulation/liquidity checks (advanced_small_micro_safety) plus a choppy "
                    "price-action filter. A stock excluded here cannot appear under ANY strategy "
                    "this scan, regardless of which one would otherwise have found it."
                )
                if gate_audit is None or gate_audit.empty:
                    st.info("No gate audit available for this scan.")
                else:
                    st.dataframe(gate_audit, width='stretch', hide_index=True)

            with st.expander("🔧 Advanced Diagnostics — S2/S4 audits", expanded=False):
                # Strategy 4 condition audit — shown only when S4 is selected.
                if 4 in selected_strategies and stats["usable"] > 0:
                    s4_audit_rows = []
                    for ticker, df in data.items():
                        if len(df) < 260:
                            continue
                        f = features_fast(str(ticker), df)
                        if f.empty:
                            continue
                        z = f.iloc[-1]
                        monthly_cross = (
                            (f.mema10 > f.mema20) &
                            (f.mema10.shift(1) <= f.mema20.shift(1))
                        )
                        monthly_cross_count = (
                            monthly_cross.shift(1).rolling(20, min_periods=20).sum().iloc[-1]
                        )
                        reclaim = bool(
                            pd.notna(z.mprevclose) and pd.notna(z.mema10) and
                            z.mclose > z.mema10 and z.mprevclose <= z.mema10
                        )
                        conditions = {
                            "Monthly return >=20%": bool(pd.notna(z.mmom) and z.mmom >= 20),
                            "Monthly RSI >=50": bool(pd.notna(z.mrsi14) and z.mrsi14 >= 50),
                            "Monthly EMA10 >= EMA20": bool(pd.notna(z.mema10) and pd.notna(z.mema20) and z.mema10 >= z.mema20),
                            "Daily EMA volume30 >=50000": bool(pd.notna(z.vol30) and z.vol30 >= 50000),
                            "Daily close >=20": bool(z.close >= 20),
                            "Monthly cross count >=1 OR reclaim": bool((pd.notna(monthly_cross_count) and monthly_cross_count >= 1) or reclaim),
                        }
                        s4_audit_rows.append({
                            "Ticker": ticker.replace(".NS",""),
                            **conditions,
                            "S4 SEPA WATCHLIST": all(conditions.values())
                        })

                    if s4_audit_rows:
                        s4df = pd.DataFrame(s4_audit_rows)
                        st.subheader("🧪 Strategy 4 (SEPA Watchlist) Condition Audit")
                        st.caption(
                            "Live S4 now uses the SEPA watchlist gate below, not the old fixed "
                            "'close <= 1.03x EMA20' proximity rule. The tighter VCP/VCC entry-timing "
                            "layer (strategy4_sepa_signal) is separate and shown on the S4 SEPA "
                            "Strategy tab, not here."
                        )
                        s4counts = pd.DataFrame({
                            "Condition": list(s4df.columns[1:-1]),
                            "Passing stocks": [int(s4df[c].sum()) for c in s4df.columns[1:-1]]
                        })
                        st.dataframe(s4counts, width='stretch', hide_index=True)
                        with st.expander("View S4 stock-by-stock audit"):
                            st.dataframe(s4df, width='stretch', hide_index=True)

                # Strategy 2 condition audit — shown only when S2 is selected.
                if 2 in selected_strategies and stats["usable"] > 0:
                    audit_rows = []
                    for ticker, df in data.items():
                        if len(df) < 260:
                            continue
                        f = features_fast(str(ticker), df)
                        if f.empty:
                            continue
                        z = f.iloc[-1]
                        dr = f.close.pct_change() * 100

                        c_30max = bool(dr.rolling(30, min_periods=30).max().iloc[-1] >= 5) if len(f) >= 30 else False
                        c_ema50_250 = bool(z.ema50 >= z.ema250)
                        c_vol = bool(z.vol20 >= 10000)
                        c_price = bool(z.close >= 15)
                        c_mrsi = bool(z.mrsi14 >= 55)
                        c_wrsi = bool(z.wrsi14 >= 50)

                        c_inside = bool(
                            (z.open <= f.high.shift(1).iloc[-1]) and
                            (z.open >= f.low.shift(1).iloc[-1]) and
                            (z.close >= f.low.shift(1).iloc[-1]) and
                            (z.close <= f.high.shift(1).iloc[-1])
                        )

                        r1 = dr.shift(1).iloc[-1]
                        r2 = dr.shift(2).iloc[-1]
                        c_r1 = bool(pd.notna(r1) and -4 <= r1 <= 5)
                        c_r2 = bool(pd.notna(r2) and -4 <= r2 <= 5)

                        c_ema10 = bool(pd.notna(z.ema10) and ((z.close-z.ema10)/z.ema10 <= .04))

                        cross20 = (
                            ((f.ema20 > f.ema50) & (f.ema20.shift(1) <= f.ema50.shift(1)))
                            .shift(1).rolling(20, min_periods=20).sum().iloc[-1]
                        )
                        cross50 = (
                            ((f.ema50 > f.ema200) & (f.ema50.shift(1) <= f.ema200.shift(1)))
                            .shift(1).rolling(20, min_periods=20).sum().iloc[-1]
                        )
                        c_bull = bool((cross20 == 1) or (cross50 == 1))

                        bear20 = (
                            ((f.ema20 < f.ema50) & (f.ema20.shift(1) >= f.ema50.shift(1)))
                            .shift(1).rolling(20, min_periods=20).sum().iloc[-1]
                        )
                        bear10 = (
                            ((f.ema10 < f.ema20) & (f.ema10.shift(1) >= f.ema20.shift(1)))
                            .shift(1).rolling(10, min_periods=10).sum().iloc[-1]
                        )
                        c_bear20 = bool(bear20 < 1)
                        c_bear10 = bool(bear10 < 1)

                        audit_rows.append({
                            "Ticker": ticker.replace(".NS",""),
                            "30D Max ≥5": c_30max,
                            "Bearish EMA20/50 count <1": c_bear20,
                            "Bearish EMA10/20 count <1": c_bear10,
                            "EMA50 ≥ EMA250": c_ema50_250,
                            "Vol20 ≥10000": c_vol,
                            "Price ≥15": c_price,
                            "Monthly RSI ≥55": c_mrsi,
                            "Weekly RSI ≥50": c_wrsi,
                            "Inside previous day": c_inside,
                            "Prev day return -4..5": c_r1,
                            "2D ago return -4..5": c_r2,
                            "Close ≤4% above EMA10": c_ema10,
                            "Bullish cross count =1": c_bull,
                            "S2 EXACT": all([c_30max,c_bear20,c_bear10,c_ema50_250,c_vol,c_price,c_mrsi,c_wrsi,c_inside,c_r1,c_r2,c_ema10,c_bull])
                        })

                    if audit_rows:
                        audit_df = pd.DataFrame(audit_rows)
                        st.subheader("🧪 Strategy 2 Condition Audit")
                        counts = pd.DataFrame({
                            "Condition": list(audit_df.columns[1:]),
                            "Passing stocks": [int(audit_df[c].sum()) for c in audit_df.columns[1:]]
                        })
                        st.dataframe(counts, width='stretch', hide_index=True)
                        with st.expander("View S2 stock-by-stock audit"):
                            st.dataframe(audit_df, width='stretch', hide_index=True)


            st.subheader("🧠 ML Win Probability")
            if ml_model.get("ready"):
                m1,m2,m3,m4 = st.columns(4)
                m1.metric("Training samples", ml_model["n_samples"])
                m2.metric("GBC AUC", f"{ml_model['gbc_auc']:.2f}" if np.isfinite(ml_model['gbc_auc']) else "—")
                m3.metric("GBC Brier", f"{ml_model['gbc_brier']:.3f}")
                m4.metric("Logistic AUC (baseline)", f"{ml_model['logit_auc']:.2f}" if np.isfinite(ml_model['logit_auc']) else "—")
                st.caption(
                    "AUC 0.5 = no better than chance, 1.0 = perfect separation. Brier score is mean "
                    "squared error of the probability (lower is better, 0 is perfect). With this few "
                    "samples these numbers can swing a lot run to run — treat them as directional, not final."
                )
            else:
                st.info(
                    f"ML model not trained yet: {ml_model.get('n_samples',0)} completed learning "
                    f"observations, needs ≥{ml_model['min_samples']}"
                    + (f" ({ml_model['reason']})" if ml_model.get('reason') else "")
                    + ". 'Win Probability %' falls back to the score-band historical edge table below "
                      "(Historical Edge R / Learning Confidence) until then."
                )

            st.subheader("🔎 Scanner Diagnostics")
            c1,c2,c3,c4,c5,c6 = st.columns(6)
            c1.metric("Universe stocks", len(tickers))
            c2.metric("Price datasets", stats["downloaded"])
            c3.metric("Usable datasets", stats["usable"])
            c4.metric("S1/S2 signals", stats["signals"][1]+stats["signals"][2])
            c5.metric("S3/S4 signals", stats["signals"][3]+stats["signals"][4])
            c6.metric("Safety rejects", stats["safety_reject"])
            st.caption(
                "Warm-up history: 1000 calendar days. This is required for EMA250 and monthly EMA20; "
                "the previous 450-day window could leave the feature table with zero valid rows."
            )

            diag = pd.DataFrame({
                "Strategy":["S1","S2","S3","S4"],
                "Raw signals":[stats["signals"][1],stats["signals"][2],stats["signals"][3],stats["signals"][4]],
                "Displayed/qualified":[stats["qualified"][1],stats["qualified"][2],stats["qualified"][3],stats["qualified"][4]]
            })
            st.dataframe(diag,width='stretch',hide_index=True)

            if result.empty:
                st.error(
                    "ZERO RESULTS. If RAW mode also shows zero signals, the problem is in the "
                    "strategy/data layer—not the scoring filters."
                )
                st.stop()

            result = result.sort_values(
                ["Score","Strategy","Ticker"],
                ascending=[False,True,True]
            )
            full_result = result.copy()

            st.subheader("📊 Strategy Coverage")
            cov=[]
            for s in selected_strategies:
                sr=full_result[full_result["Strategy"]==f"S{s}"] if not full_result.empty else pd.DataFrame()
                cov.append({
                    "Strategy":f"S{s}",
                    "ALL rules pass":len(sr),
                    f"≥{min_score}":int((sr["Score"]>=min_score).sum()) if not sr.empty else 0,
                    "Best":int(sr["Score"].max()) if not sr.empty else 0,
                    "Average":round(float(sr["Score"].mean()),1) if not sr.empty else 0
                })
            st.dataframe(pd.DataFrame(cov),width='stretch',hide_index=True)

            if full_result.empty:
                st.warning("No stock passed ALL rules of the selected strategies.")
            else:
                # Four-column board: one independent column per strategy.
                st.subheader("🏆 Strategy Board — Best to Average")
                cols=st.columns(4)
                for idx,s in enumerate([1,2,3,4]):
                    with cols[idx]:
                        sr=full_result[full_result["Strategy"]==f"S{s}"].copy()
                        sr=sr.sort_values("Score",ascending=False)
                        st.markdown(f"### S{s}")
                        if sr.empty:
                            st.caption("No complete-rule setups")
                        else:
                            for rank,(_,r) in enumerate(sr.iterrows(),1):
                                score=float(r["Score"])
                                if score>=85:
                                    st.success(f"**{rank}. {r['Ticker']} — {score:.0f}**")
                                elif score>=75:
                                    st.warning(f"**{rank}. {r['Ticker']} — {score:.0f}**")
                                else:
                                    st.info(f"**{rank}. {r['Ticker']} — {score:.0f}**")
                                st.caption(
                                    f"HTF {r.get('HTF Score','-')} | "
                                    f"Footprint {r.get('Footprint Score','-')} | "
                                    f"Safety {r.get('Safety','-')} | {r.get('Regime','-')}"
                                )

                # Same stock in 2+ strategies = confluence, but only from
                # complete independent strategy passes.
                st.subheader("⭐ Multi-Strategy Confluence")
                pivot=full_result.pivot_table(
                    index="Ticker",columns="Strategy",values="Score",aggfunc="max"
                )
                for sname in ["S1","S2","S3","S4"]:
                    if sname not in pivot.columns:
                        pivot[sname]=np.nan
                pivot=pivot[["S1","S2","S3","S4"]]
                pivot["Strategies Passed"]=pivot.notna().sum(axis=1)
                pivot["Best Score"]=pivot[["S1","S2","S3","S4"]].max(axis=1)
                conf=pivot[pivot["Strategies Passed"]>=2].sort_values(
                    ["Strategies Passed","Best Score"],ascending=[False,False]
                ).reset_index()
                if conf.empty:
                    st.info("No stock currently passes the complete rules of 2 or more strategies.")
                else:
                    st.dataframe(conf,width='stretch',hide_index=True)

                st.subheader("📋 All Qualifying Setups")
                st.dataframe(full_result,width='stretch',hide_index=True)

                forward=full_result[
                    (full_result["Score"]>=min_score) &
                    (full_result["Safety"]!="REJECT")
                ].copy()
                st.subheader(f"🚀 Forward-Test Queue — Score ≥ {min_score}")
                if forward.empty:
                    st.info("No complete-rule setup currently meets the forward-test gate.")
                else:
                    st.dataframe(forward,width='stretch',hide_index=True)
                    st.session_state["forward_queue"]=forward
                    added=add_forward_candidates(forward)
                    st.success(
                        f"{len(forward)} setups qualify for forward testing; "
                        f"{added} added to active monitoring."
                    )

                st.subheader("🔎 Individual Strategy Results")
                stabs=st.tabs(["S1","S2","S3","S4"])
                for tab,s in zip(stabs,[1,2,3,4]):
                    with tab:
                        sr=full_result[full_result["Strategy"]==f"S{s}"]
                        if sr.empty:
                            st.warning(f"S{s}: no stock passed ALL S{s} rules.")
                        else:
                            st.dataframe(
                                sr.sort_values("Score",ascending=False),
                                width='stretch',
                                hide_index=True
                            )

        except Exception as e:
            st.error(f"Scanner error: {e}")

    st.divider()
    st.subheader("🧑‍⚖️ AI Trade Debate Panel")
    st.caption("5 agents (Technical, Statistical Skeptic, Risk/Capital, Devil's Advocate, Judge) analyze the scanner's forward-test queue. 5 API calls total per run, regardless of shortlist size.")

    # "forward_queue" is the actual session_state key the scanner populates with
    # its forward-test-qualifying shortlist (Score >= min_score, Safety != REJECT)
    # right before calling add_forward_candidates() above - there is no session_state
    # key holding the full unfiltered scan result (full_result is a local variable,
    # not persisted across reruns), so this is the closest and most fitting analog:
    # it's exactly the "before you commit capital" shortlist this panel is meant to
    # analyze, not the raw universe of every strategy-qualified setup.
    panel_result = st.session_state.get('forward_queue', pd.DataFrame())
    if panel_result.empty:
        st.info("Run a scan first — the panel analyzes the scanner's forward-test queue (Score above the gate).")
    elif not _anthropic_configured():
        st.info("ANTHROPIC_API_KEY not set in Streamlit secrets — add it to enable this section.")
    else:
        pc1, pc2, pc3 = st.columns(3)
        panel_capital = pc1.number_input("Capital ₹", 10000, 100000000, 100000, 10000, key="panel_capital")
        panel_slots = pc2.number_input("Max concurrent positions", 1, 20, 5, 1, key="panel_slots")
        panel_target = pc3.slider("Final shortlist size", 2, 6, 5, 1, key="panel_target")

        if st.button("🔬 RUN 5-AGENT DEBATE PANEL", type="primary", key="panel_run"):
            with st.spinner("Running 5-agent analysis (5 API calls)..."):
                panel = run_trade_debate_panel(
                    panel_result, capital=panel_capital, max_slots=panel_slots,
                    risk_pct=1.0, target_count=panel_target
                )
            st.session_state["latest_panel"] = panel

        panel = st.session_state.get("latest_panel")
        if panel:
            if panel.get("error"):
                st.warning(panel["error"])
            else:
                if panel["errors"]:
                    st.warning("Some agents had issues: " + " | ".join(panel["errors"]))

                if panel["final"]:
                    st.subheader("🏆 Judge's Final Ranking")
                    st.dataframe(pd.DataFrame(panel["final"]), width='stretch', hide_index=True)

                with st.expander("🔍 View individual agent verdicts"):
                    vt1, vt2, vt3, vt4 = st.tabs(["Technical", "Statistical Skeptic", "Risk/Capital", "Devil's Advocate"])
                    with vt1:
                        st.dataframe(pd.DataFrame(panel["tech"]), width='stretch', hide_index=True) if panel["tech"] else st.info("No data.")
                    with vt2:
                        st.dataframe(pd.DataFrame(panel["skeptic"]), width='stretch', hide_index=True) if panel["skeptic"] else st.info("No data.")
                    with vt3:
                        st.dataframe(pd.DataFrame(panel["risk"]), width='stretch', hide_index=True) if panel["risk"] else st.info("No data.")
                    with vt4:
                        st.dataframe(pd.DataFrame(panel["bear"]), width='stretch', hide_index=True) if panel["bear"] else st.info("No data.")


with tabs[2]:
    st.subheader("📊 Professional Walk-Forward Backtest")
    st.caption("Dhan is used ONLY by the explicit Data Manager sync. Backtest reads the same SQLite candle store and makes ZERO Dhan/API calls.")
    c1,c2,c3=st.columns(3)
    period=c1.selectbox("Time Span",["6 Months","1 Year","2 Years","3 Years"],index=0,key="bt_period_final")
    threshold=c2.number_input("Score threshold",0,100,85,1,key="bt_threshold_final")
    universes=c3.multiselect("Universe",["Nifty 500","Nifty Smallcap 100","Nifty Smallcap 250","Nifty Midcap 150"],default=["Nifty 500"],key="bt_universes_final")
    start_date,end_date=_bt_period(period);data_start=_bt_required_data_start(start_date)
    tickers=[]
    if universes:
        try:
            tickers=sorted(set(sum([index_universe(u) for u in universes],[])))
        except Exception as e:
            st.error(f"Could not load index universe constituents (network/data issue): {e}")
    st.info(f"{period} | Signal window {start_date} → {end_date} | Warm-up {data_start} → {start_date} | {len(tickers):,} stocks | S1–S4 | local SQLite only | forward gate ≥{threshold}")

    st.markdown("### 📅 Data Freshness")
    render_data_freshness_banner(tickers)

    st.markdown("### 1️⃣ Local Dataset")
    status=local_backtest_status(tickers,start_date,end_date) if tickers else pd.DataFrame()
    ready=int(status.Ready.sum()) if not status.empty else 0
    total=len(status)
    a,b,c,d=st.columns(4)
    a.metric("Stocks ready",f"{ready:,}")
    b.metric("Missing",f"{total-ready:,}")
    a.caption("Only locally cached candles are counted.")
    c.metric("Local bars",f"{int(status.Bars.sum()):,}" if not status.empty else "0")
    d.metric("Warm-up",f"{BT_WARMUP_DAYS} days")

    if total and ready==total:
        st.success("✅ Local SQLite dataset ready. Backtest will make ZERO Dhan/API calls.")
    elif total:
        st.warning(
            f"⚠️ {total-ready:,} stocks are missing required local history. "
            f"The backtest button remains available and will run ONLY on the {ready:,} stocks already cached."
        )
    else:
        st.error("No local universe data is available.")

    st.markdown("### 2️⃣ Run Backtest")
    st.caption(
        "🔒 HARD RULE: this button never synchronizes data and never calls Dhan. "
        "Use Data Manager → SYNC ONLY MISSING DATA when you deliberately want to acquire history."
    )

    # ALWAYS visible. Missing stocks must never hide the backtest.
    if st.button("⚡ RUN LOCAL S1–S4 BACKTEST",type="primary",key="run_local_bt"):
        t0=time.perf_counter()
        try:
            with st.spinner(f"Replaying local data for {ready:,}/{total:,} available stocks..."):
                bt=run_local_backtest(tickers,start_date,end_date,int(threshold))
            elapsed=time.perf_counter()-t0
            _persist_backtest(bt,period,start_date,end_date,int(threshold),len(tickers),elapsed)
            learned=_learn_from_backtest(bt)
            st.session_state["backtest_final"]=bt
            st.session_state["backtest_learning_added"]=learned
            st.success(
                f"Completed locally in {elapsed:.2f}s — {len(bt):,} qualifying trades; "
                f"{learned:,} learning observations saved. Dhan/API calls: 0."
            )
        except Exception as ex:
            st.error(f"Local backtest error: {ex}")

    bt=st.session_state.get("backtest_final",pd.DataFrame())
    if bt.empty:
        bt,_run=_load_latest_backtest()
        if not bt.empty:st.session_state["backtest_final"]=bt
    if bt.empty:
        st.info("No completed backtest is stored yet. Build the dataset and run the backtest once.")
    else:
        st.subheader("🏆 Historical Learning Dataset")
        a,b,c,d,e=st.columns(5)
        a.metric("Trades",len(bt));b.metric("S1",int((bt.Strategy=='S1').sum()));c.metric("S2",int((bt.Strategy=='S2').sum()));d.metric("S3",int((bt.Strategy=='S3').sum()));e.metric("S4",int((bt.Strategy=='S4').sum()))
        st.dataframe(bt.sort_values(["Score","Date"],ascending=[False,False]),width='stretch',hide_index=True)

        st.subheader("📈 Strategy Performance / ROI / Risk")
        perf=[]
        for strat,g in bt.groupby('Strategy'):
            wins=g[g['R']>0];loss=g[g['R']<=0];grossw=float(wins['R'].sum());grossl=abs(float(loss['R'].sum()))
            pf=grossw/grossl if grossl>0 else (99.99 if grossw>0 else 0)
            perf.append({'Strategy':strat,'Trades':len(g),'Win %':round((g.R>0).mean()*100,1),'Avg R':round(g.R.mean(),3),'Total R':round(g.R.sum(),2),'Profit Factor':round(pf,2),'Avg Return %':round(g['Return %'].mean(),2),'Avg MFE %':round(g['MFE %'].mean(),2),'Avg MAE %':round(g['MAE %'].mean(),2),'Best Score':int(g.Score.max())})
        st.dataframe(pd.DataFrame(perf).sort_values('Avg R',ascending=False),width='stretch',hide_index=True)

        st.subheader("💰 Capital / ROI Simulation")
        pc1,pc2,pc3=st.columns(3);capital=pc1.number_input("Starting capital ₹",10000,100000000,100000,10000,key='bt_capital');risk_pct=pc2.number_input("Risk per trade %",0.1,5.0,1.0,0.1,key='bt_risk');slots=pc3.number_input("Capital slots",1,50,5,1,key='bt_slots')
        roi=portfolio_from_backtest(bt,float(capital),float(risk_pct),int(slots));st.dataframe(pd.DataFrame([roi]),width='stretch',hide_index=True)

        st.subheader("🎯 Score Learning")
        bands=pd.cut(bt.Score,[84,89,94,100],labels=["85–89","90–94","95–100"],include_lowest=True);bx=bt.assign(Band=bands,Win=(bt.Outcome.str.upper()=='WIN').astype(int))
        learn=bx.groupby('Band',observed=True).agg(Signals=('Ticker','count'),Wins=('Win','sum'),WinRate=('Win','mean'),AvgR=('R','mean'),TotalR=('R','sum'),AvgReturn=('Return %','mean'),AvgMFE=('MFE %','mean'),AvgMAE=('MAE %','mean')).reset_index();learn['WinRate']=(learn.WinRate*100).round(1);learn[['AvgR','TotalR','AvgReturn','AvgMFE','AvgMAE']]=learn[['AvgR','TotalR','AvgReturn','AvgMFE','AvgMAE']].round(2);st.dataframe(learn,width='stretch',hide_index=True)

        st.subheader("🧠 Marking Conditions Used")
        st.info("A row exists only when ALL mandatory rules of its strategy passed. The columns below preserve the score components used to rank the historical setup; the strategy itself is independently re-evaluated from the full rule set.")
        st.dataframe(bt[['Ticker','Date','Strategy','Score','Strategy Score','HTF','Footprint','Trend','Entry Quality','Relative Strength','Safety','Regime','Outcome','R','Return %','MFE %','MAE %','Holding Bars']].sort_values('Score',ascending=False),width='stretch',hide_index=True)

        st.subheader("🔎 Individual Strategy Results")
        stabs=st.tabs(['S1','S2','S3','S4'])
        for tab,ss in zip(stabs,[1,2,3,4]):
            with tab:
                sr=bt[bt.Strategy==f'S{ss}'].sort_values(['Score','Date'],ascending=[False,False])
                if not sr.empty:
                    st.dataframe(sr,width='stretch',hide_index=True)
                else:
                    st.info(f'S{ss}: no qualifying historical setups in this window.')

    st.divider()
    st.subheader("🔬 Raw Strategy Learning — Ungated Signal Capture")
    st.caption("Records EVERY S1-S4 signal regardless of score, with a full feature fingerprint at signal time. This does not affect the existing ≥85 backtest or scanner above — it's a separate research dataset for discovering what actually separates winners from losers.")
    st.caption("🔒 Same hard rule as the backtest above: this reads the same local SQLite dataset (period/universe selected above) and makes ZERO Dhan/API calls — it does not independently sync data.")

    raw_strategies = st.multiselect("Strategies", [1,2,3,4], default=[1,2,3,4], key="raw_strategies")

    if st.button("🔬 RUN RAW SIGNAL CAPTURE", type="primary", key="raw_capture_run"):
        if not tickers:
            st.warning("Select at least one universe above first.")
        elif not raw_strategies:
            st.warning("Select at least one strategy.")
        else:
            with st.spinner(f"Loading local data for {len(tickers):,} tickers..."):
                raw_data = load_local_backtest_data(tickers, start_date, end_date)
            if not raw_data:
                st.error("No local data available for this universe/date range. Sync it in Data Manager first.")
            else:
                raw_prog = st.progress(0.0)
                def _raw_cb(done, total, sym):
                    raw_prog.progress(done/max(total,1), text=f"{sym} ({done}/{total})")
                t0 = time.perf_counter()
                with st.spinner(f"Running ungated backtest on {len(raw_data):,} locally-available tickers..."):
                    raw_result = run_raw_signal_backtest(raw_data, raw_strategies, pd.Timestamp(start_date), pd.Timestamp(end_date), progress_cb=_raw_cb)
                raw_prog.empty()
                st.session_state["raw_signal_result"] = raw_result
                st.success(f"Captured {len(raw_result):,} raw signals (no score gate applied) in {time.perf_counter()-t0:.1f}s.")

    raw_result = st.session_state.get("raw_signal_result", pd.DataFrame())
    if not raw_result.empty:
        st.markdown("#### Quick sanity check: does score correlate with outcome AT ALL?")
        band_check = raw_result.copy()
        band_check["score_band"] = pd.cut(band_check["score"], bins=[0,50,60,70,80,85,90,100])
        raw_summary = band_check.groupby("score_band", observed=True).agg(
            trades=("outcome","count"), win_pct=("r_multiple", lambda x: round((x>0).mean()*100,1)),
            avg_r=("r_multiple","mean")
        ).reset_index()
        st.dataframe(raw_summary, width='stretch', hide_index=True)
        st.caption("If low-score bands show similar or better win%/avg R than 85+, that's direct evidence the current gate may be miscalibrated. Treat any band with a handful of trades as noise, not a conclusion.")

        st.divider()
        st.markdown("#### 🏆 Winners vs Losers — What actually separates them?")
        st.caption("Compares the feature fingerprint (captured AT SIGNAL TIME, before the outcome was known) between WIN and LOSS trades only — TIMEOUT excluded since it's not a clean win/loss. Sorted by how far apart the two groups are, biggest gap first.")

        outc = raw_result["outcome"].value_counts()
        oc1, oc2, oc3, oc4 = st.columns(4)
        oc1.metric("Wins", int(outc.get("WIN", 0)))
        oc2.metric("Losses", int(outc.get("LOSS", 0)))
        oc3.metric("Timeouts", int(outc.get("TIMEOUT", 0)))
        overall_win_pct = (raw_result["r_multiple"] > 0).mean() * 100
        oc4.metric("Win % (all trades)", f"{overall_win_pct:.1f}%")

        wl = raw_result[raw_result["outcome"].isin(["WIN", "LOSS"])]
        wins_df = wl[wl["outcome"] == "WIN"]
        losses_df = wl[wl["outcome"] == "LOSS"]

        if len(wins_df) < 10 or len(losses_df) < 10:
            st.info(f"Only {len(wins_df)} win(s) / {len(losses_df)} loss(es) captured so far — need at least ~10 of each before a winners-vs-losers comparison means anything. Run a wider universe/date range to accumulate more.")
        else:
            feature_gap_df = _feature_gap_table(wins_df, losses_df, RAW_SIGNAL_NUMERIC_FEATURES)
            st.dataframe(feature_gap_df, width='stretch', hide_index=True)
            st.caption("\"Gap (in std devs)\" is just |win avg − loss avg| divided by the pooled standard deviation — a plain descriptive size-of-difference, not a significance test. A large gap on a small N is still noise; check the N column. This is deliberately a simple sanity check, not the pattern-discovery/similarity engine the research doc defers to a later phase once more data has accumulated.")

            cat_features = [c for c in ("trend_direction", "market_regime") if c in wl.columns]
            if cat_features:
                st.markdown("##### Win % by category")
                cat_cols = st.columns(len(cat_features))
                for col, cat_col in zip(cat_cols, cat_features):
                    with col:
                        cat_summary = wl.groupby(cat_col, observed=True).agg(
                            trades=("outcome", "count"),
                            win_pct=("r_multiple", lambda x: round((x > 0).mean() * 100, 1)),
                        ).reset_index().sort_values("trades", ascending=False)
                        st.markdown(f"**{col}**")
                        st.dataframe(cat_summary, width='stretch', hide_index=True)

            st.divider()
            st.markdown("#### 🎯 Suggested marking read — strategy by strategy")
            st.caption("Same win-vs-loss comparison as above, but scoped to each strategy separately and limited to the deterministic score's own components (HTF, Footprint, Entry Quality, Relative Strength, Safety) — since a component can matter for one strategy and not another. **Informational only — this does not change S1-S4 scoring**; it's evidence for you to decide whether a component's weight deserves a second look.")
            for strat in sorted(wl["strategy"].dropna().unique()):
                s_wins = wins_df[wins_df["strategy"] == strat]
                s_losses = losses_df[losses_df["strategy"] == strat]
                with st.expander(f"{strat} — {len(s_wins)} win(s) / {len(s_losses)} loss(es)", expanded=False):
                    if len(s_wins) < 10 or len(s_losses) < 10:
                        st.info(f"Need at least ~10 wins and ~10 losses for {strat} specifically before this is meaningful — currently {len(s_wins)}/{len(s_losses)}.")
                        continue
                    comp_df = _feature_gap_table(s_wins, s_losses, RAW_SIGNAL_SCORE_COMPONENTS, min_n=5)
                    if comp_df.empty:
                        st.info("Not enough per-component data for this strategy yet.")
                        continue
                    comp_df["Suggested Read"] = comp_df["Gap (in std devs)"].apply(_component_read_label)
                    st.dataframe(comp_df, width='stretch', hide_index=True)

        with st.expander("View raw captured signals"):
            st.dataframe(raw_result, width='stretch', hide_index=True)

    st.divider()
    st.subheader("🎯 Stop-Loss Calibration Study")
    st.caption(
        "Backtests candidate stop-loss schemes (the current fixed 7% baseline, three ATR-multiple "
        "widths, and a structure/swing-low based stop) against the SAME real historical S1-S4 "
        "signals, broken out by strategy AND market regime. **Purely additive research — this does "
        "NOT change the live scanner's stop-loss, the existing ≥85 gated backtest, or forward-test "
        "tracking**, all of which keep using the fixed entry×0.93 (7%) stop untouched. Every scheme "
        "is compared using the same 3R target convention so the comparison isolates stop PLACEMENT, "
        "not a different reward:risk ratio."
    )
    st.caption("🔒 Same hard rule as above: reads the same local SQLite dataset (period/universe selected above), makes ZERO Dhan/API calls.")

    sl_cal_strategies = st.multiselect("Strategies", [1, 2, 3, 4], default=[1, 2, 3, 4], key="sl_cal_strategies")

    if st.button("🎯 RUN STOP-LOSS CALIBRATION STUDY", type="primary", key="sl_cal_run"):
        if not tickers:
            st.warning("Select at least one universe above first.")
        elif not sl_cal_strategies:
            st.warning("Select at least one strategy.")
        else:
            with st.spinner(f"Loading local data for {len(tickers):,} tickers..."):
                sl_cal_data = load_local_backtest_data(tickers, start_date, end_date)
            if not sl_cal_data:
                st.error("No local data available for this universe/date range. Sync it in Data Manager first.")
            else:
                sl_cal_prog = st.progress(0.0)
                def _sl_cal_cb(done, total, sym):
                    sl_cal_prog.progress(done / max(total, 1), text=f"{sym} ({done}/{total})")
                t0 = time.perf_counter()
                with st.spinner(f"Running SL calibration study on {len(sl_cal_data):,} locally-available tickers × {len(SL_CALIBRATION_SCHEMES)} schemes..."):
                    sl_cal_result = run_sl_calibration_study(
                        sl_cal_data, sl_cal_strategies, pd.Timestamp(start_date), pd.Timestamp(end_date), progress_cb=_sl_cal_cb
                    )
                sl_cal_prog.empty()
                st.session_state["sl_calibration_result"] = sl_cal_result
                st.success(f"Captured {len(sl_cal_result):,} scheme-trade rows in {time.perf_counter() - t0:.1f}s.")

    sl_cal_result = st.session_state.get("sl_calibration_result", pd.DataFrame())
    if not sl_cal_result.empty:
        sl_cal_report = sl_calibration_report(sl_cal_result)
        st.markdown("#### Strategy × Regime × Scheme — Win% / Avg R")

        rep_cols = st.columns(3)
        strat_filter = rep_cols[0].multiselect("Filter: Strategy", sorted(sl_cal_report["Strategy"].unique()), key="sl_cal_filter_strat")
        regime_filter = rep_cols[1].multiselect("Filter: Regime", sorted(sl_cal_report["Regime"].unique()), key="sl_cal_filter_regime")
        reliable_only = rep_cols[2].checkbox("Reliable buckets only", value=False, key="sl_cal_reliable_only")

        view = sl_cal_report.copy()
        if strat_filter:
            view = view[view["Strategy"].isin(strat_filter)]
        if regime_filter:
            view = view[view["Regime"].isin(regime_filter)]
        reliable_col = f"Reliable (>={SL_CALIBRATION_MIN_BUCKET_SAMPLES} samples)"
        if reliable_only:
            view = view[view[reliable_col]]
        st.dataframe(view, width='stretch', hide_index=True)
        st.caption(
            f"Buckets below {SL_CALIBRATION_MIN_BUCKET_SAMPLES} samples are marked unreliable — treat "
            "them as noise, not evidence. A scheme missing for a given strategy/regime means it was "
            "unavailable for every signal there (e.g. no nearby support for structure_swing_low), not zero trades."
        )

        with st.expander("View raw scheme-trade rows"):
            st.dataframe(sl_cal_result, width='stretch', hide_index=True)

with tabs[3]:
    st.subheader('🔬 Forward Testing — Persistent Strategy Outcome Tracker')
    st.caption("Every scanner-selected ≥gate signal is stored in SQLite with its original conditions. Refreshing the page does not clear it.")

    # Resolution is explicit, not automatic. Opening this tab used to run
    # refresh_forward_positions() immediately, so simply looking at the book
    # could close positions against newly-synced candles with no warning.
    # Nothing is ever deleted either way — a resolved record moves to
    # TARGET/STOP with its result — but you decide when that happens.
    rf1, rf2 = st.columns([1, 2])
    with rf1:
        _do_refresh = st.button("🔄 REFRESH / RESOLVE POSITIONS", key="fwd_resolve_now")
    with rf2:
        _last_resolve = _metric_get("forward_last_resolved_at")
        st.caption(
            f"Checks every open position against the stored daily candles and closes any that hit "
            f"their stop or target. Last run: **{_last_resolve or 'never in this database'}**."
        )
    if _do_refresh:
        with st.spinner("Resolving open forward tests against stored candles..."):
            changed, newly_closed_count = refresh_forward_positions()
            _metric_set("forward_last_resolved_at", datetime.now().isoformat(timespec="seconds"))
        st.success(
            f"✅ {changed} position(s) checked; {newly_closed_count} resolved and recorded to the "
            "learning database."
        )
    con=_db()
    try:
        ft=pd.read_sql_query("""SELECT id,signal_date AS Signal_Date,symbol AS Ticker,strategy AS Strategy,
            score AS Score,regime AS Regime,entry AS Entry,sl AS Stop,target AS Target,status AS Status,
            ltp AS Current_Price,mfe AS MFE_pct,mae AS MAE_pct,exit_price AS Exit,result_r AS R,
            updated_at AS Updated FROM forward_tests ORDER BY signal_date DESC,score DESC""",con)
        signals=pd.read_sql_query("""SELECT signal_date AS Date,symbol AS Ticker,strategy AS Strategy,
            score AS Score,entry AS Entry,stop AS Stop,target AS Target,rr AS RR,regime AS Regime,
            safety_status AS Safety,historical_edge_r AS Historical_Edge_R
            FROM scanner_signals WHERE selected_for_forward=1
            ORDER BY signal_date DESC,score DESC""",con)
    finally:con.close()

    if ft.empty:
        st.info("No persistent forward-test records yet. Run Daily Scanner and let the ≥85 gate create them.")
    else:
        closed=ft[ft.Status!="ACTIVE"]; wins=int((closed.R>0).sum()); losses=int((closed.R<=0).sum())
        avg_r=float(closed.R.mean()) if not closed.empty else np.nan
        a,b,c,d,e=st.columns(5)
        a.metric("Persistent signals",len(ft)); b.metric("Open",int((ft.Status=="ACTIVE").sum()))
        c.metric("Wins",wins); d.metric("Losses",losses); e.metric("Avg R",f"{avg_r:.2f}" if np.isfinite(avg_r) else "—")

        st.subheader("📋 Forward Positions — Live P/L")
        pc1, pc2 = st.columns([1, 2])
        with pc1:
            fwd_use_live = st.checkbox(
                "Use live price", value=True, key="fwd_use_live_price",
                help="Prices open positions from the Dhan feed. Uncheck to see the last stored daily close instead."
            )
            if st.button("🔄 Refresh prices", key="fwd_refresh_prices"):
                st.rerun()

        try:
            positions, pos_meta = forward_positions_view(use_live=fwd_use_live)
        except Exception as ex:
            positions, pos_meta = pd.DataFrame(), {}
            st.error(f"Could not build the live position view: {ex}")

        if not positions.empty:
            open_pos = positions[positions["Status"] == "ACTIVE"]
            with pc2:
                if pos_meta.get("live_symbols"):
                    st.success(
                        f"🟢 Live prices for {pos_meta['live_symbols']:,} open position(s) "
                        f"via {pos_meta['source']} · as of {pos_meta['as_of']}"
                    )
                elif not fwd_use_live:
                    st.info("Live pricing is off — showing the last stored daily close.")
                elif pos_meta.get("market_open"):
                    st.warning(
                        "No live quote returned — showing the last stored close. "
                        "Run the Dhan Connection Test in the Data Manager."
                    )
                else:
                    st.info("NSE cash session is closed — the last completed close is the current price.")

            if not open_pos.empty:
                gl = pd.to_numeric(open_pos["Gain/Loss %"], errors="coerce")
                ur = pd.to_numeric(open_pos["Unrealized R"], errors="coerce")
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("Open positions", len(open_pos))
                m2.metric("Avg unrealized", f"{gl.mean():+.2f}%" if gl.notna().any() else "—")
                m3.metric("Open in profit", int((gl > 0).sum()))
                m4.metric("Open unrealized R", f"{ur.sum():+.2f}" if ur.notna().any() else "—")

            show_only_open = st.checkbox("Show open positions only", value=True, key="fwd_open_only")
            table = open_pos if show_only_open else positions
            st.dataframe(
                table.drop(columns=["id"], errors="ignore"),
                width='stretch', hide_index=True,
                column_config={
                    "Gain/Loss %": st.column_config.NumberColumn("Gain/Loss %", format="%+.2f%%"),
                    "Gain/Loss ₹": st.column_config.NumberColumn("Gain/Loss ₹", format="%+.2f"),
                    "Unrealized R": st.column_config.NumberColumn("Unrealized R", format="%+.2f"),
                    "To Target %": st.column_config.NumberColumn("To Target %", format="%+.2f%%"),
                    "To Stop %": st.column_config.NumberColumn("To Stop %", format="%+.2f%%"),
                    "Progress to Target %": st.column_config.ProgressColumn(
                        "Progress to Target", min_value=-100, max_value=100, format="%.0f%%"
                    ),
                }
            )
            st.caption(
                "Gain/Loss is measured against the recorded entry. Unrealized R divides that by the "
                "position's own risk (entry − stop), so it is comparable across stocks of any price. "
                "Target/stop resolution still happens only on completed daily candles — a live price "
                "touching the level raises an alert here, it does not close the record."
            )
            st.download_button(
                "⬇️ Download live position book",
                table.to_csv(index=False).encode(), "forward_positions_live.csv", "text/csv",
                key="download_forward_positions"
            )

        st.subheader("🏆 Strategy Performance Scorecard")
        try:
            fs=forward_summary_table()
        except Exception as e:
            fs=pd.DataFrame(); st.error(f"Strategy scorecard error: {e}")
        if not fs.empty: st.dataframe(fs,width='stretch',hide_index=True)
        else: st.info("Waiting for completed forward-test outcomes.")
        st.subheader("🧠 What is being learned")
        st.write("The system tracks strategy, score, regime, entry/stop/target, MFE/MAE, R and final outcome. This is the permanent evidence base for future strategy ranking.")

    st.subheader("🗃️ Persisted Scanner Signals")
    if signals.empty: st.info("No scanner signals saved for the forward-test gate yet.")
    else:
        st.dataframe(signals.head(500),width='stretch',hide_index=True)
        st.download_button("⬇️ Download forward signal history",signals.to_csv(index=False).encode(),"forward_signal_history.csv","text/csv",key="download_forward_history")

with tabs[4]:
    st.subheader("🧠 Adaptive Market Learning")
    try:
        fwd=forward_summary_table()
    except Exception as e:
        fwd=pd.DataFrame(); st.error(f"Forward strategy leaderboard error: {e}")
    if not fwd.empty:
        st.subheader("🏆 Forward Strategy Leaderboard")
        st.dataframe(fwd,width='stretch',hide_index=True)

    bt=st.session_state.get('backtest_final',pd.DataFrame())
    if bt.empty:
        bt,_run=_load_latest_backtest()
        if not bt.empty:st.session_state['backtest_final']=bt
    learn_db=learning_snapshot('INDIA')
    if bt.empty and learn_db.empty:
        st.info('No learning observations yet. Run a backtest or complete forward-test trades first.')
    else:
        if not bt.empty:
            st.subheader('📊 Historical Evidence')
            st.dataframe(_learning_summary(bt),width='stretch',hide_index=True)
            rows=[]
            for c in ['HTF','Footprint','Strategy Score','Safety','Entry Quality','Relative Strength']:
                if c in bt.columns:
                    med=bt[c].median();hi=bt[bt[c]>=med];lo=bt[bt[c]<med]
                    rows.append({'Component':c,'High Samples':len(hi),'High Avg R':round(float(hi.R.mean()),3) if len(hi) else 0,'Low Samples':len(lo),'Low Avg R':round(float(lo.R.mean()),3) if len(lo) else 0,'High Win %':round(float((hi.Outcome.str.upper()=='WIN').mean()*100),1) if len(hi) else 0})
            st.subheader('🔬 Marking Component Learning');st.dataframe(pd.DataFrame(rows),width='stretch',hide_index=True)
        st.subheader('🎯 Adaptive Score Edge')
        edge=adaptive_edge_table('INDIA')
        if not edge.empty:
            st.dataframe(edge,width='stretch',hide_index=True)
        else:
            st.info('Not enough completed observations for adaptive edge estimates.')
        st.subheader('🗄️ Persistent Learning Database')
        st.metric('Completed observations',len(learn_db))
        if not learn_db.empty:
            st.dataframe(adaptive_component_weights('INDIA'),width='stretch',hide_index=True)
            st.dataframe(learn_db.head(500),width='stretch',hide_index=True)
        st.caption('Learning ranks candidates using evidence; it never changes the deterministic S1–S4 qualification rules.')

    st.divider()
    st.subheader("🧑‍🏫 AI System Coach (LLM)")
    st.caption(
        "Different from the 🎓 Strategy Coach tab, which uses deterministic decision-tree rules — "
        "this one is an on-demand LLM analysis of the same underlying data."
    )
    st.caption("On-demand AI analysis of the marking system's accuracy across backtest + forward-test history. One API call per run — you control when it runs.")

    if not _anthropic_configured():
        st.info("ANTHROPIC_API_KEY not set in Streamlit secrets — add it to enable this section.")
    elif st.button("🔬 RUN AI SYSTEM COACH ANALYSIS", type="primary", key="coach_run"):
        with st.spinner("Analyzing backtest performance, forward-test outcomes, and component correlations..."):
            coach_report, coach_err = run_strategy_coach()
        if coach_err:
            st.warning(coach_err)
        else:
            save_coach_report(coach_report)
            st.session_state["latest_coach_report"] = coach_report
            st.success("Analysis complete and saved.")

    latest_coach = st.session_state.get("latest_coach_report")
    if latest_coach:
        st.markdown(latest_coach)

    with st.expander("📜 Report History"):
        con = _db()
        try:
            coach_hist = pd.read_sql_query("SELECT id, created_at, total_backtest_trades, total_forward_closed, verdict FROM coach_reports ORDER BY id DESC", con)
        finally:
            con.close()
        if coach_hist.empty:
            st.info("No reports yet — run your first analysis above.")
        else:
            st.dataframe(coach_hist, width='stretch', hide_index=True)
            coach_pick = st.selectbox("View full report", coach_hist["id"].tolist(), key="coach_history_pick")
            if coach_pick:
                con = _db()
                try:
                    coach_full = con.execute("SELECT report_text FROM coach_reports WHERE id=?", (coach_pick,)).fetchone()
                finally:
                    con.close()
                if coach_full:
                    st.markdown(coach_full[0])

    st.divider()
    st.subheader("🧑‍🤝‍🧑 System Learning Panel (5 Agents)")
    st.caption(
        "Same underlying data as AI System Coach above, but analyzed by 5 specialized agents "
        "with different priorities, then synthesized by a Judge — useful when you want the "
        "disagreements surfaced, not just one summary."
    )
    st.caption(
        "5 API calls per run (4 analysts + 1 Judge) — you control when it runs. Reads the AI "
        "System Coach payload, the Raw Strategy Learning winners-vs-losers data (Backtest tab — "
        "skipped gracefully if that section hasn't been run yet), and the Stop-Loss Calibration "
        "Study results (Backtest tab — same graceful skip if empty)."
    )

    if not _anthropic_configured():
        st.info("ANTHROPIC_API_KEY not set in Streamlit secrets — add it to enable this section.")
    elif st.button("🧑‍🤝‍🧑 RUN SYSTEM LEARNING PANEL", type="primary", key="learning_panel_run"):
        raw_for_panel = st.session_state.get("raw_signal_result", pd.DataFrame())
        with st.spinner("Running 4 analysts + Judge (5 API calls)..."):
            panel_result = run_system_learning_panel(raw_for_panel)
        if panel_result.get("error"):
            st.warning(panel_result["error"])
        else:
            save_learning_panel_run(panel_result)
            st.session_state["latest_learning_panel"] = panel_result
            if panel_result["errors"]:
                st.warning("Panel completed with some agent errors: " + "; ".join(panel_result["errors"]))
            else:
                st.success("Panel analysis complete and saved.")

    latest_panel = st.session_state.get("latest_learning_panel")
    if latest_panel:
        judge = latest_panel.get("judge")
        st.markdown("#### 🏁 Judge's Prioritized Recommendations")
        if judge and judge.get("recommendations"):
            for rec in sorted(judge["recommendations"], key=lambda r: r.get("priority", 999)):
                st.markdown(f"**{rec.get('priority', '?')}. {rec.get('recommendation', '')}**")
                st.caption(rec.get("reasoning", ""))
        else:
            st.info("Judge did not return recommendations this run (see any errors above).")

        st.markdown("#### Individual Agent Findings")
        panel_tabs = st.tabs(["📈 Strategy Performance", "🎯 Marking/Component", "🛡️ Risk & Stop-Loss", "🕵️ Devil's Advocate"])
        panel_specs = [
            ("strategy", "Strategy Performance Analyst"),
            ("marking", "Marking/Component Analyst"),
            ("risk", "Risk & Stop-Loss Analyst"),
            ("skeptic", "Devil's Advocate / Overfitting Skeptic"),
        ]
        for tab, (key, label) in zip(panel_tabs, panel_specs):
            with tab:
                finding = latest_panel.get(key)
                if finding:
                    st.markdown(f"**Confidence: {finding.get('confidence', '?')}**")
                    st.write(finding.get("finding", ""))
                    st.caption(finding.get("evidence_summary", ""))
                else:
                    st.info(f"{label} did not return a result this run.")

    with st.expander("📜 Panel Run History"):
        con = _db()
        try:
            panel_hist = pd.read_sql_query(
                "SELECT id, created_at, total_backtest_trades, total_forward_closed, "
                "marking_read_available, sl_calibration_available FROM system_learning_panel_runs ORDER BY id DESC",
                con,
            )
        finally:
            con.close()
        if panel_hist.empty:
            st.info("No panel runs yet — run your first analysis above.")
        else:
            st.dataframe(panel_hist, width='stretch', hide_index=True)

with tabs[5]:
    st.subheader("💎 Long-Term Fundamentals + News")
    st.caption("Dhan remains the primary Indian market-price source. Twelve Data provides fundamentals; Screen A / Screen B run against the full index universe, not just typed symbols.")

    fscreen_tab1, fscreen_tab2 = st.tabs(["📋 Screen A / B — Universe Scan", "🔎 Manual Symbol Lookup"])

    with fscreen_tab1:
        st.info(
            "⚠️ Twelve Data field-name mappings for income_statement/balance_sheet/cash_flow "
            "(and therefore the Piotroski score, ROCE fallback, and every Screen A/B pass/fail below) "
            "are UNVERIFIED assumptions — this deployment has not been checked against a live Twelve "
            "Data key or a real company filing. Spot-check any PASS result against the company's actual "
            "financial statements before acting on it."
        )
        fc1, fc2, fc3 = st.columns([2, 1, 1])
        fund_universes = fc1.multiselect(
            "Universe", ["Nifty 500", "Nifty Smallcap 100", "Nifty Smallcap 250", "Nifty Midcap 150"],
            default=["Nifty 500"], key="fund_screen_universe"
        )
        fund_run_a = fc2.checkbox("Screen A", value=True, key="fund_run_a")
        fund_run_b = fc3.checkbox("Screen B", value=True, key="fund_run_b")

        fund_auto_track = st.checkbox(
            "Auto-track PASS results into Forward Testing", value=True, key="fund_auto_track",
            help="Passing stocks are inserted into the same forward_tests table used by the technical "
                 "scanner (tagged FUNDA/FUNDB) so they can be watched forward, using a local Dhan close "
                 "as entry with a wide 15%/3R stop-target (see add_fundamental_forward_candidates)."
        )

        if st.button("🔬 RUN FUNDAMENTAL SCREENS", type="primary", key="fund_screen_run"):
            if not fund_universes:
                st.warning("Select at least one universe.")
            elif not (fund_run_a or fund_run_b):
                st.warning("Select at least one screen (A and/or B).")
            elif not twelvedata_configured():
                st.error("TWELVEDATA_API_KEY not configured in Streamlit secrets — Screen A/B need Twelve Data fundamentals.")
            else:
                fund_prog = st.progress(0.0, text="Starting scan...")

                def _fund_cb(done, total, sym):
                    fund_prog.progress(done / max(total, 1), text=f"Scanning {sym} ({done}/{total})")

                with st.spinner("Fetching fundamentals — this can take a while for large universes..."):
                    fund_result = run_fundamental_screens(fund_universes, run_a=fund_run_a, run_b=fund_run_b, progress_cb=_fund_cb)

                fund_prog.empty()
                st.session_state["fund_screen_results"] = fund_result

                if fund_auto_track and not fund_result.empty:
                    n_added = add_fundamental_forward_candidates(fund_result)
                    st.success(f"Scan complete. {n_added} new candidate(s) added to Forward Testing.")
                else:
                    st.success("Scan complete.")

        fund_result = st.session_state.get("fund_screen_results", pd.DataFrame())
        if fund_result.empty:
            st.info("Run a screen to see universe-wide fundamental results here.")
        else:
            fund_passed = fund_result[fund_result["Pass"] == True]
            fund_failed = fund_result[fund_result["Pass"] == False]
            fm1, fm2, fm3 = st.columns(3)
            fm1.metric("Scanned", len(fund_result))
            fm2.metric("Passed", len(fund_passed))
            fm3.metric("Failed", len(fund_failed))

            fund_display_cols = [c for c in fund_result.columns if c not in ("Checks",)]
            st.dataframe(
                fund_result[fund_display_cols].sort_values(["Pass", "Screen"], ascending=[False, True]),
                width='stretch', hide_index=True
            )

            if "Unverifiable" in fund_result.columns and fund_result["Unverifiable"].astype(str).str.len().gt(0).any():
                st.warning("Some checks could not be verified (e.g. Promoter Holding — not available via Twelve Data) and were excluded from the Pass/Fail decision rather than assumed true.")

            with st.expander("🔍 View individual stock check breakdown"):
                fund_pick = st.selectbox("Stock", fund_result["Ticker"].unique(), key="fund_screen_detail_pick")
                fund_sub = fund_result[fund_result["Ticker"] == fund_pick]
                for _, frow in fund_sub.iterrows():
                    st.markdown(f"**Screen {frow.get('Screen')}** — {'✅ PASS' if frow.get('Pass') else '❌ FAIL'}")
                    fchecks = frow.get("Checks", {})
                    if isinstance(fchecks, dict):
                        for k, v in fchecks.items():
                            ficon = "✅" if v is True else "❌" if v is False else "⚪ N/A"
                            st.write(f"{ficon} {k}")

    with fscreen_tab2:
        st.caption("Dhan remains the primary Indian market-price source. Fundamental/news enrichment is deliberately fetched only for candidates, cached locally, and never used to weaken S1–S4 rules.")
        st.info("Twelve Data provides India fundamentals/press releases; Dhan's current API documentation exposes market data, instruments, quotes, positions and related trading/data APIs rather than a fundamental-financial-statement endpoint.")
        sym_text=st.text_input("Candidate symbols (comma separated)","RELIANCE,TCS,HDFCBANK",key="fund_symbols_final")
        if st.button("🔎 Enrich Fundamentals + News",key="fund_enrich_final"):
            symbols=[x.strip().upper() for x in sym_text.split(',') if x.strip()]
            rows=[]
            with st.spinner(f"Enriching {len(symbols)} candidate(s)..."):
                for sym in symbols:
                    try:
                        info,ff=company_info(sym)
                        items,sent,risk=news_snapshot(sym)
                        score,status,flags=_fundamental_score(info)
                        rows.append({"Ticker":sym,"Fundamental Score":score,"Status":status,"News Sentiment":round(sent,1),"News Risk":round(risk,1),"Flags":"; ".join(ff+flags),"News Items":len(items)})
                    except Exception as e:
                        rows.append({"Ticker":sym,"Fundamental Score":np.nan,"Status":f"ERROR: {e}","News Sentiment":np.nan,"News Risk":np.nan,"Flags":"","News Items":0})
            st.session_state["fundamental_results_final"]=pd.DataFrame(rows)
        fr=st.session_state.get("fundamental_results_final",pd.DataFrame())
        if fr.empty: st.info("Enter candidates or feed the tab from the scanner's ≥85 queue.")
        else: st.dataframe(fr.sort_values(["Fundamental Score","News Sentiment"],ascending=[False,False]),width='stretch',hide_index=True)

with tabs[6]:
    st.subheader("🏢 Small/Micro Safety Engine")
    st.caption("Independent risk gate. It cannot create an S1–S4 signal; it can only downgrade/reject a qualifying candidate.")
    con=_db()
    try: syms=pd.read_sql_query("SELECT DISTINCT symbol FROM forward_tests WHERE status='ACTIVE'",con)
    finally: con.close()
    if syms.empty: st.info("No active forward-test stocks yet.")
    else:
        rows=[]
        for sym in syms.symbol:

            con2=_db()
            try:
                d=_read_cache(con2,str(sym).upper().replace('.NS',''),date.today()-timedelta(days=180),date.today())
            finally:
                con2.close()
            # LOCAL-ONLY. Safety must never trigger a live Dhan download on a bare rerun.
            if d is None or d.empty:
                rows.append({
                    "Stock":sym,"Safety Score":np.nan,
                    "Status":"NO LOCAL DATA — sync this symbol in Data Manager first",
                    "News Risk":np.nan,"Flags":""
                })
                continue
            try:
                info,_=company_info(sym); _,_,newsrisk=news_snapshot(sym)
                sc,status,flags=advanced_small_micro_safety(info,d,newsrisk)
                rows.append({"Stock":sym,"Safety Score":sc,"Status":status,"News Risk":round(newsrisk,1),"Flags":", ".join(flags)})
            except Exception as e:
                rows.append({"Stock":sym,"Safety Score":np.nan,"Status":f"ERROR: {e}","News Risk":np.nan,"Flags":""})
        st.dataframe(pd.DataFrame(rows).sort_values("Safety Score",ascending=False),width='stretch',hide_index=True)


with tabs[7]:
    st.subheader("⚡ Live Forward-Test Monitor — Persistent Dhan WebSocket")
    st.caption(
        "The WebSocket stays connected in the Streamlit process, automatically reconnects "
        "after disconnects, and monitors only active ≥85 forward-test candidates."
    )

    con=_db()
    try:
        active=pd.read_sql_query(
            "SELECT symbol,strategy,score,entry,sl,target,status "
            "FROM forward_tests WHERE status='ACTIVE' ORDER BY score DESC",con
        )
    finally:
        con.close()

    if active.empty:
        st.info("No active ≥85 forward-test candidates yet.")
        mgr=get_dhan_live_manager()
        mgr.stop()
    else:
        mgr=start_persistent_live_feed(active.symbol.tolist())
        status,error,last_tick,subscribed=mgr.snapshot()

        a,b,c,d=st.columns(4)
        a.metric("WebSocket",status)
        b.metric("Active setups",len(active))
        c.metric("Subscribed",len(subscribed))
        d.metric("Last tick",last_tick or "—")

        if error:
            st.warning(f"Last WebSocket error: {error}")

        try:
            q=live_forward_test_table()
        except Exception as e:
            q=pd.DataFrame(); st.error(f"Live forward-test table error: {e}")
        if q.empty:
            st.info("Waiting for the first Dhan WebSocket ticks...")
        else:
            st.dataframe(q,width='stretch',hide_index=True)

        st.caption(
            "The feed is persistent only while this Streamlit application process is running. "
            "If the app sleeps/restarts, the manager reconnects automatically when the app resumes."
        )

with tabs[8]:
    st.subheader("💾 Dhan Data Manager")
    st.caption("Dhan is the primary Indian-equity market-data source. Historical candles are cached locally; backtests use the local dataset after it is built.")

    # ---- Access token status (Dhan tokens expire every 24h) -------------------
    st.markdown("### 🔑 Access Token Status")
    if _dhan_pin_totp_configured():
        _tok, _issued = _read_cached_dhan_token()
        if _tok and _issued:
            try:
                _age_h = (datetime.now() - datetime.fromisoformat(_issued)).total_seconds() / 3600
                st.success(f"🟢 Auto-renewal active (PIN+TOTP). Cached token is {_age_h:.1f}h old (renews automatically past {DHAN_TOKEN_MAX_AGE_HOURS}h).")
            except Exception:
                st.info("Auto-renewal active (PIN+TOTP). Token cached, age unknown.")
        else:
            st.info("Auto-renewal active (PIN+TOTP). No token generated yet — one will be minted on first Dhan call.")
        if st.button("🔄 Force-renew token now", key="dhan_force_renew"):
            with st.spinner("Generating a fresh Dhan access token via PIN+TOTP..."):
                try:
                    _dhan_generate_fresh_token()
                    st.success("✅ New access token generated and cached.")
                except Exception as e:
                    st.error(f"Token renewal failed: {e}")

        # "Invalid TOTP" has exactly two plausible causes and they need
        # opposite fixes: a wrong/stale DHAN_TOTP_SECRET, or clock skew on this
        # server (TOTP is time-based, so a server clock more than ~30s off
        # produces codes Dhan rejects even when the secret is perfect).
        # Showing the code this server generates right now, next to its clock,
        # tells the two apart in one glance instead of guessing.
        with st.expander("🩺 TOTP diagnostic — 'Invalid TOTP' troubleshooting"):
            try:
                import pyotp
                from datetime import timezone as _tz
                _secret_val = str(_secret("DHAN_TOTP_SECRET") or "").strip()
                if not _secret_val:
                    st.warning("DHAN_TOTP_SECRET is not set.")
                else:
                    _totp = pyotp.TOTP(_secret_val)
                    _now_utc = datetime.now(_tz.utc)
                    _seconds_left = 30 - (int(_now_utc.timestamp()) % 30)
                    d1, d2 = st.columns(2)
                    d1.metric("Code this server generates now", _totp.now())
                    d2.metric("Valid for", f"{_seconds_left}s")
                    st.caption(
                        f"Server UTC time: **{_now_utc.strftime('%Y-%m-%d %H:%M:%S')}** · "
                        f"secret length: **{len(_secret_val)}** chars · "
                        f"characters outside base32 (A-Z, 2-7): "
                        f"**{sorted(set(_secret_val.upper()) - set('ABCDEFGHIJKLMNOPQRSTUVWXYZ234567='))}**"
                    )
                    st.markdown(
                        "**Compare the code above with your authenticator app right now:**\n\n"
                        "- **They match, but Dhan still says Invalid TOTP** → the secret is right; the problem is "
                        "on Dhan's side (TOTP not fully activated for API login, or reset in their console). "
                        "Re-run the TOTP setup in Dhan's console and paste the new secret.\n"
                        "- **They differ** → this server's `DHAN_TOTP_SECRET` is not the secret your authenticator "
                        "was seeded with (wrong value, a stale one from a previous setup, or stray characters — "
                        "check the 'characters outside base32' list above; it should be empty).\n"
                        "- **Server UTC time is visibly wrong** → clock skew; codes will be rejected regardless of "
                        "the secret."
                    )
            except Exception as e:
                st.error(f"Could not generate a diagnostic code: {e}")
    elif _dhan_manual_token_configured():
        st.warning("Using a manually-pasted DHAN_ACCESS_TOKEN. Dhan tokens expire every 24h — you'll need to regenerate it in Dhan's console and update Streamlit Secrets daily. Add DHAN_PIN and DHAN_TOTP_SECRET to Secrets to switch to automatic renewal.")
    else:
        st.error("No Dhan credentials configured. Add DHAN_CLIENT_ID plus either (DHAN_PIN + DHAN_TOTP_SECRET) for auto-renewal, or DHAN_ACCESS_TOKEN for manual daily renewal, to Streamlit Secrets.")

    # ---- GitHub DB backup status (Streamlit Cloud's filesystem is ephemeral) --
    st.markdown("### 🗄️ Database Backup (GitHub)")
    if _github_configured():
        st.success("🟢 GitHub backup configured — learning data is protected against Streamlit Cloud reboots. Auto-backs up after every closed forward test, learned backtest batch, and added candidate (rate-limited to once per 15 minutes).")
    else:
        st.error(
            "🔴 GitHub backup NOT configured — accumulated learning data will be LOST on the next "
            "Streamlit Cloud reboot/redeploy. Add GITHUB_TOKEN and GITHUB_REPO to **Streamlit "
            "Secrets**. Note that Streamlit Secrets and GitHub Actions secrets are separate stores: "
            "configuring the scheduled jobs does not configure this app, and vice versa."
        )

    bk1, bk2 = st.columns(2)
    if bk1.button("🔎 TEST GITHUB BACKUP", key="db_backup_test"):
        with st.spinner("Checking credentials, repository access and write permission..."):
            gdiag = github_backup_diagnostic()
        checks = [
            ("Configured", gdiag["configured"]),
            ("Repo format", gdiag["repo_format"]),
            ("Token valid", gdiag["token_valid"]),
            ("Repo visible", gdiag["repo_visible"]),
            ("Write access", gdiag["can_write"]),
        ]
        cols = st.columns(len(checks))
        for col, (label, ok) in zip(cols, checks):
            col.metric(label, "PASS" if ok else "FAIL")
        if all(ok for _, ok in checks) and gdiag["branch_ok"]:
            st.success("🟢 GitHub backup is working — credentials, repository access and write permission all verified.")
        else:
            st.error("🔴 GitHub backup is not usable yet. The reason is below.")
        for msg in gdiag["details"]:
            st.write("•", msg)
        st.caption(
            "This test never writes a commit. If every check passes but a backup still fails, "
            "press Backup DB Now — the error message now names the exact cause."
        )

    if bk2.button("💾 Backup DB Now", type="primary", key="db_backup_now"):
        with st.spinner("Uploading market_data.sqlite3 to GitHub..."):
            ok, reason = backup_db_to_github(return_reason=True)
        if ok:
            st.success(f"✅ {reason}")
        else:
            st.error(f"❌ Backup failed — {reason}")
            st.caption("Run TEST GITHUB BACKUP for a step-by-step breakdown.")

    # ---- Explicit, read-only Dhan health check --------------------------------
    st.markdown("### 🔌 Dhan Connection Test")
    st.caption("These tests never place an order. First prove the Dhan historical API, then prove Dhan → parser → SQLite with one stock before starting a large sync.")

    if st.button("🧪 TEST DHAN CONNECTION",type="primary",key="dhan_connection_test"):
        with st.spinner("Testing Dhan connection..."):
            diag=dhan_connection_diagnostic()

        checks=[
            ("Credentials",diag["credentials"]),
            ("Instrument master",diag["instrument_master"]),
            ("RELIANCE NSE mapping",diag["reliance_mapping"]),
            ("Authenticated LTP API",diag["ltp_api"]),
            ("Authenticated historical API",diag["historical_api"]),
        ]
        cols=st.columns(5)
        for col,(label,ok) in zip(cols,checks):
            col.metric(label,"PASS" if ok else "FAIL")

        if all(ok for _,ok in checks):
            st.success("🟢 DHAN CONNECTED — authentication, NSE mapping, LTP and historical data are working.")
        else:
            st.error("🔴 Dhan connection is not fully verified. Read the diagnostics below.")
        for msg in diag["details"]:
            st.write("•",msg)

    st.markdown("### 🧪 One-Stock Data Smoke Test")
    st.caption("This downloads only RELIANCE for a small diagnostic range and immediately verifies that candles were written to SQLite. It does NOT start the 500-stock sync.")
    smoke_days=st.selectbox("Smoke-test range",[7,30,90],index=1,key="dhan_smoke_days")
    if st.button("🔎 TEST DHAN → SQLITE (RELIANCE)",type="secondary",key="dhan_smoke_test"):
        try:
            with st.spinner("Testing Dhan historical data and SQLite write..."):
                smoke=dhan_historical_smoke_test("RELIANCE",int(smoke_days))
            st.success(f"✅ End-to-end data test passed: {smoke['http/parser_candles']:,} candles received and {smoke['saved_rows']:,} rows written/updated in SQLite.")
            q1,q2,q3,q4=st.columns(4)
            q1.metric("Security ID",smoke["security_id"])
            q2.metric("Candles received",smoke["http/parser_candles"])
            q3.metric("DB rows after",smoke["db_rows_after"])
            q4.metric("Request time",f"{smoke['request_seconds']:.2f}s")
            st.write(f"**Requested:** {smoke['requested_start']} → {smoke['requested_end']}  |  **Returned:** {smoke['sample_first']} → {smoke['sample_last']}  |  **DB:** {smoke['db_min']} → {smoke['db_max']}")
            st.write(f"**Latest RELIANCE close:** ₹{smoke['sample_close']:,.2f}")
        except Exception as ex:
            st.error(f"❌ End-to-end data test failed: {ex}")
            st.warning("Do not start the 500-stock sync until this one-stock test passes.")

    st.markdown("### 📦 Local Dataset")
    st.caption(
        "Historical acquisition is controlled ONLY from this section. "
        "Backtest and scanner never synchronize historical data. "
        f"Latest expected NSE cash-session: {last_expected_nse_session().strftime('%d-%b-%Y')}. "
        "No candle is expected on Saturday/Sunday."
    )
    sync_universe=st.selectbox(
        "Sync universe",
        ["Nifty 500","Nifty Smallcap 100","Nifty Smallcap 250","Nifty Midcap 150"],
        key="dm_sync_universe"
    )
    sync_days=st.selectbox(
        "Historical range to maintain",
        [730,1000,1500,2000],
        index=1,
        format_func=lambda x: f"{x} calendar days",
        key="dm_sync_days"
    )
    if st.button(f"⚡ FAST TOP-UP (last {LATEST_SYNC_TAIL_DAYS} days only)",key="dm_sync_tail"):
        try:
            tail_tickers=index_universe(sync_universe)
            tailbar=st.progress(0.0)
            with st.spinner(f"Topping up the latest sessions for {len(tail_tickers):,} stocks..."):
                tail_summary=sync_latest_sessions(
                    tail_tickers,
                    progress_cb=lambda frac: tailbar.progress(min(1.0,frac))
                )
            tailbar.empty()
            st.success(
                f"✅ {tail_summary['advanced']:,} of {tail_summary['symbols']:,} stocks advanced. "
                f"Newest stored session: {tail_summary['latest'] or '—'}."
            )
            if tail_summary["errors"]:
                st.warning("Dhan errors: "+" | ".join(tail_summary["errors"][:6]))
            st.rerun()
        except Exception as ex:
            st.error(f"Fast top-up failed: {ex}")
    st.caption(
        "Use the fast top-up for the daily refresh once the full history is built. "
        "The full sync below is only needed the first time, or after widening the historical range."
    )

    if st.button("🔄 SYNC ONLY MISSING DATA",type="primary",key="dm_sync_missing"):
        try:
            sync_tickers=index_universe(sync_universe)
            sync_symbols=[str(t).upper().replace(".NS","") for t in sync_tickers]
            con=_db()
            try:
                qmarks=",".join(["?"]*len(sync_symbols))
                pre_max={r[0]:r[1] for r in con.execute(
                    f"SELECT symbol,MAX(dt) FROM candles WHERE symbol IN ({qmarks})",sync_symbols).fetchall()}
            finally:
                con.close()

            with st.spinner(f"Checking local ranges and downloading ONLY missing data for {len(sync_tickers):,} stocks..."):
                sync_missing_backtest_data(
                    sync_tickers,
                    last_expected_nse_session()-timedelta(days=int(sync_days)),
                    last_expected_nse_session(),
                    max_workers=5
                )
            st.success("Sync completed. Existing local candles were reused; only missing ranges were requested from Dhan.")
            if _DHAN_LAST_DATA_ERRORS:
                st.warning("Recent Dhan data errors: "+" | ".join(_DHAN_LAST_DATA_ERRORS[:8]))

            # One-line freshness log: did this sync actually pull a NEW
            # most-recent trading day's candle for at least one symbol?
            con=_db()
            try:
                post_rows=con.execute(
                    f"SELECT symbol,MAX(dt) FROM candles WHERE symbol IN ({qmarks}) GROUP BY symbol",
                    sync_symbols).fetchall()
            finally:
                con.close()
            post_max={r[0]:r[1] for r in post_rows}
            newest_pulled=max((v for v in post_max.values() if v),default=None)
            if newest_pulled:
                advanced=sum(1 for s in sync_symbols if post_max.get(s)==newest_pulled and pre_max.get(s)!=newest_pulled)
                if advanced>0:
                    _log_sync_freshness(newest_pulled,advanced)

            # Refresh the per-symbol sync-diagnostics table for this universe.
            compute_and_store_sync_diagnostics(sync_tickers)
            st.rerun()
        except Exception as ex:
            st.error(f"Data sync error: {ex}")

    con=_db()
    try:
        ns=con.execute("SELECT COUNT(DISTINCT symbol) FROM candles").fetchone()[0]
        nc=con.execute("SELECT COUNT(*) FROM candles").fetchone()[0]
        latest=con.execute("SELECT MAX(dt) FROM candles").fetchone()[0]
    finally:
        con.close()

    a,b,c=st.columns(3)
    a.metric("Cached stocks",ns)
    b.metric("Cached candles",f"{nc:,}")
    c.metric("Latest stored candle",latest or "—")

    if ns==0:
        st.warning("⚠️ Cache is empty. Run the Dhan Connection Test first, then use SYNC ONLY MISSING DATA in this Data Manager.")
    else:
        st.success(f"🟢 Local Dhan dataset contains {ns:,} stocks and {nc:,} candles.")

    st.info(
        "Architecture: Dhan → local candle cache → local backtest. "
        "The backtest runner does not call Dhan once the required local dataset is ready. "
        "Existing candles are reused and only missing historical ranges are downloaded."
    )

    if _DHAN_LAST_DATA_ERRORS:
        st.markdown("### ⚠️ Recent Dhan data-build errors")
        st.dataframe(
            pd.DataFrame({"Error":_DHAN_LAST_DATA_ERRORS}),
            width='stretch',
            hide_index=True
        )

    with st.expander("⚠️ Sync Diagnostics — why are stocks below the 260-bar threshold?"):
        st.caption(
            "Backtest/Scanner silently drop any stock with fewer than 260 usable local bars. "
            "This lists every such stock in the selected universe(s) with a specific reason, "
            "computed fresh each time this expander is rendered and persisted to sync_diagnostics."
        )
        diag_universes=st.multiselect(
            "Universe(s) to diagnose",
            ["Nifty 500","Nifty Smallcap 100","Nifty Smallcap 250","Nifty Midcap 150"],
            default=[sync_universe],
            key="dm_diag_universes"
        )
        if diag_universes:
            try:
                diag_tickers=sorted(set(sum([index_universe(u) for u in diag_universes],[])))
                diag_df=compute_and_store_sync_diagnostics(diag_tickers)
                if diag_df.empty:
                    st.success(f"✅ All {len(diag_tickers):,} stocks in the selected universe(s) have ≥260 local bars.")
                else:
                    st.warning(f"{len(diag_df):,} of {len(diag_tickers):,} stocks are below the 260-bar threshold.")
                    st.dataframe(
                        diag_df.rename(columns={"symbol":"Symbol","bar_count":"Bar Count","reason":"Reason"}),
                        width='stretch',
                        hide_index=True
                    )
            except Exception as ex:
                st.error(f"Could not compute sync diagnostics (index universe fetch failed): {ex}")
        else:
            st.info("Select at least one universe to diagnose.")

    with st.expander("🕒 Sync Freshness Log — last 10 syncs that pulled a new session"):
        st.caption(
            "One entry each time SYNC ONLY MISSING DATA successfully pulled a new most-recent "
            "trading day's candle for at least one symbol. Use this to observe, over real "
            "trading sessions, how soon after close Dhan's data actually becomes available."
        )
        con=_db()
        try:
            log_df=pd.read_sql_query(
                """SELECT synced_at AS "Synced At", most_recent_date_pulled AS "Most Recent Date Pulled",
                          symbols_updated AS "Symbols Updated"
                   FROM sync_freshness_log ORDER BY id DESC LIMIT 10""",
                con
            )
        finally:
            con.close()
        if log_df.empty:
            st.info("No freshness-log entries yet. This fills in as syncs pull new trading sessions.")
        else:
            st.dataframe(log_df,width='stretch',hide_index=True)

    if st.button("⛔ Stop Live WebSocket",key="stop_ws"):
        stop_persistent_live_feed()
        st.success("Dhan WebSocket stop requested.")

with tabs[9]:
    st.subheader("🎯 Strategy 4 — SEPA (Specific Entry Point Analysis)")
    st.caption(
        "Live S4 now uses the Minervini SEPA methodology (fundamental template, trend template, "
        "monthly/weekly/daily VCP-VCC entry timing) in place of the old literal-formula rule. This "
        "replaces the previous 'S4 Recovery Study' research tab - that pattern-study hypothesis is "
        "fully superseded by SEPA and has been removed."
    )
    st.info(
        "Pipeline: NSE universe (nse_liquid_universe) → safety/liquidity/price-action gate "
        "(clean_liquid_universe, shared with S1-S3) → SEPA watchlist + VCP/VCC entry timing "
        "(scan_s4_sepa) → optional fundamental Screen C."
    )

    sepa_c1, sepa_c2, sepa_c3 = st.columns(3)
    sepa_min_score = sepa_c1.slider("Minimum SEPA quality score", 0, 100, 60, 5, key="sepa_min_score")
    sepa_max_stocks = sepa_c2.number_input("Max stocks to scan (0 = all)", 0, 5000, 0, 100, key="sepa_max_stocks")
    sepa_fund_screen = sepa_c3.checkbox("Apply fundamental Screen C", value=False, key="sepa_fund_screen")
    st.caption(
        "Screen C's 'Sales QoQ growth' point always reports Unverifiable - Twelve Data's quarterly "
        "revenue coverage for Indian small/microcaps has never been confirmed. Treat it as a real "
        "data gap, not a pass."
    )

    if st.button("🎯 Scan S4 SEPA", type="primary", key="sepa_scan_run"):
        try:
            with st.spinner("Loading the NSE liquid universe..."):
                sepa_tickers = nse_liquid_universe()
                sepa_data = load_scan_dataset(sepa_tickers)
            if not sepa_data:
                st.error(
                    "Local dataset is empty/incomplete for this universe. Use Data Manager → "
                    "SYNC ONLY MISSING DATA once, then scan again."
                )
            else:
                with st.spinner(f"Running the SEPA pipeline across {len(sepa_data):,} stocks..."):
                    sepa_result, sepa_audit = scan_s4_sepa(
                        sepa_data,
                        min_score=sepa_min_score,
                        max_stocks=(sepa_max_stocks or None),
                        apply_fundamental_screen=sepa_fund_screen,
                    )
                st.session_state["sepa_scan_result"] = sepa_result
                st.session_state["sepa_scan_audit"] = sepa_audit
        except Exception as ex:
            st.error(f"S4 SEPA scan error: {ex}")

    sepa_result = st.session_state.get("sepa_scan_result", pd.DataFrame())
    sepa_audit = st.session_state.get("sepa_scan_audit", pd.DataFrame())
    if sepa_result.empty:
        st.info("Run the scan to see SEPA watchlist + entry-timing candidates.")
    else:
        st.success(f"Found {len(sepa_result)} SEPA candidate(s).")
        st.dataframe(sepa_result, width='stretch', hide_index=True)
        st.download_button(
            "⬇️ Download SEPA candidates", sepa_result.to_csv(index=False),
            "s4_sepa_candidates.csv", "text/csv",
        )
    if not sepa_audit.empty:
        passed = int(sepa_audit["Passed"].sum()) if "Passed" in sepa_audit.columns else 0
        with st.expander(f"🛡️ Universe safety audit ({passed}/{len(sepa_audit)} passed)", expanded=False):
            st.caption(
                "Every ticker considered for this scan, and why it was kept or excluded "
                "(manipulation risk, illiquidity, or choppy price action). Bad names being "
                "excluded is meant to be visible here, not silent."
            )
            st.dataframe(sepa_audit, width='stretch', hide_index=True)

    st.divider()
    st.subheader("📐 EMA20 Extension Calibration — is 3% actually the best cutoff?")
    st.caption(
        "Exact S4 requires daily close <= 1.03 x EMA20 (within 3% above EMA20), a fixed assumption. "
        "This runs every OTHER S4 condition unchanged and measures win rate/avg R by how far price "
        "actually was from EMA20 at signal time, so the 3% cutoff can be replaced with evidence "
        "instead of an assumption. Exact S4 itself is never changed by this."
    )
    ec1,ec2=st.columns(2)
    ext_universe=ec1.selectbox("Universe",["Nifty 500","Nifty Smallcap 100","Nifty Smallcap 250","Nifty Midcap 150"],key="s4ext_universe")
    ext_period=ec2.selectbox("Backtest span",["1 Year","2 Years","3 Years"],index=1,key="s4ext_period")
    if st.button("📐 Run EMA20 Extension Calibration",type="primary",key="s4ext_run"):
        try:
            tickers=index_universe(ext_universe)
        except Exception as e:
            st.error(f"Could not load index universe constituents (network/data issue): {e}")
            tickers=[]
        if tickers:
            estart,eend=_bt_period(ext_period)
            with st.spinner(f"Replaying Strategy 4's other conditions across {len(tickers):,} stocks..."):
                data=load_local_backtest_data(tickers,estart,eend)
                cal=s4_ema20_extension_calibration(data,estart,eend)
            st.session_state["s4_ext_calibration"]=cal

    cal=st.session_state.get("s4_ext_calibration",pd.DataFrame())
    if cal.empty:
        st.info("Run the calibration to see which EMA20 distance actually performed best historically.")
    else:
        report=s4_extension_bucket_report(cal)
        reliable_col=f"Reliable (>={S4_CALIBRATION_MIN_BUCKET_SAMPLES} samples)"
        st.dataframe(report,width='stretch',hide_index=True)
        st.caption(f"Total qualifying signals (ignoring the 3% rule): {len(cal):,}. Buckets below {S4_CALIBRATION_MIN_BUCKET_SAMPLES} samples are marked unreliable — treat them as noise, not evidence.")

        reliable=report[report[reliable_col]]
        if reliable.empty:
            st.warning("No bucket has enough samples yet to recommend a threshold. Try a longer span or wider universe.")
        else:
            best=reliable.sort_values(["WinRate","Samples"],ascending=[False,False]).iloc[0]
            st.success(f"Best-performing reliable bucket: **{best['Bucket']}** — {best['WinRate']}% win rate, {best['AvgR']} avg R over {int(best['Samples'])} trades.")
            exact_row=report[report.Bucket=="0-3% above (exact S4 rule)"]
            if not exact_row.empty and exact_row.iloc[0][reliable_col]:
                st.caption(f"For comparison, the exact-S4 0-3% rule: {exact_row.iloc[0]['WinRate']}% win rate, {exact_row.iloc[0]['AvgR']} avg R over {int(exact_row.iloc[0]['Samples'])} trades.")
            st.markdown("#### Paste this into Custom Strategy Lab to scan with the learned threshold instead of the fixed 3% rule")
            st.code(s4_custom_dsl_from_bucket(str(best["Bucket"])), language="text")
            st.caption(
                "This replicates S4's other rules but swaps the EMA20 distance for the bucket above. "
                "The DSL is AND-only, so exact S4's 'OR monthly reclaim' branch is approximated here by "
                "the monthly-cross-count condition alone — this scan is narrower than exact S4, not identical."
            )

with tabs[10]:
    st.subheader("🧪 Custom Strategy Lab")
    st.caption("Indian Stocks use Dhan. Forex and Crypto use Twelve Data for historical OHLCV and live price.")

    market=st.selectbox("Market",["Indian Stocks","Forex","Crypto"],key="custom_market")
    if market=="Indian Stocks":
        st.info("Indian Stocks → Dhan historical API + Dhan WebSocket.")
        symbol=st.text_input("Dhan symbol","RELIANCE",key="custom_symbol_stock")
    elif market=="Forex":
        st.info("Forex → Twelve Data composite FX feed. Example: EUR/USD, GBP/USD, USD/JPY.")
        symbol=st.text_input("Forex pair","EUR/USD",key="custom_symbol_fx")
    else:
        st.info("Crypto → Twelve Data digital-asset market data. Example: BTC/USD, ETH/USD.")
        symbol=st.text_input("Crypto pair","BTC/USD",key="custom_symbol_crypto")

    style=st.selectbox("Style",["Intraday","Swing","Positional"],key="custom_style")
    tf=st.selectbox("Timeframe",["5min","15min","1h","4h","1day","1week","1month"],index=4,key="custom_tf")

    if market!="Indian Stocks":
        if not twelvedata_configured():
            st.warning("Add TWELVEDATA_API_KEY to Streamlit Secrets to activate Forex/Crypto data.")
            st.markdown("Twelve Data provides historical OHLC/time-series data and real-time WebSocket quotes for Forex and Crypto.")
        else:
            c1,c2,c3=st.columns(3)
            if st.button("📥 Fetch Historical Data",key="td_fetch"):
                try:
                    years=2 if style!="Intraday" else 1
                    with st.spinner(f"Fetching {symbol} from Twelve Data..."):
                        d=td_market_history(symbol,market,tf,years)
                    st.session_state["td_custom_data"]=d
                    st.success(f"Fetched {len(d):,} candles.")
                except Exception as e:
                    st.error(str(e))
            if st.button("⚡ Get Live Price",key="td_live_price"):
                try:
                    with st.spinner(f"Fetching live price for {symbol}..."):
                        px=td_price(symbol)
                    st.session_state["td_live_px"]=px
                except Exception as e:
                    st.error(str(e))
            if st.button("🧪 Test Symbol",key="td_test_symbol"):
                with st.spinner(f"Validating {symbol}..."):
                    ok,n,msg=td_validate_symbol(symbol,market)
                if ok: st.success(f"Working: {symbol} — {n} recent daily candles available.")
                else: st.error(f"Symbol test failed: {msg}")

            if "td_live_px" in st.session_state:
                st.metric("Live Price",st.session_state["td_live_px"])
            d=st.session_state.get("td_custom_data",pd.DataFrame())
            if not d.empty:
                st.dataframe(d.tail(200),width='stretch')
                st.caption(f"Data source: Twelve Data | {market} | {symbol} | {tf}")

                if market == "Crypto":
                    st.subheader("🧠 Crypto Continuous Learning")
                    cq = crypto_learning_summary(symbol)
                    if cq.empty:
                        st.info("No completed crypto-learning observations yet.")
                    else:
                        ca, cb, cc = st.columns(3)
                        ca.metric("Observations", len(cq))
                        cb.metric("Win %", round(float((cq.result_r > 0).mean()*100), 1))
                        cc.metric("Avg R", round(float(cq.result_r.mean()), 3))
                        st.dataframe(cq.head(200), width='stretch', hide_index=True)

    st.divider()
    st.subheader("Strategy Rules")
    st.caption(
        "Whitelist rule DSL — never eval()/exec(). One condition per line, all lines AND-combined. "
        "Format: `<COLUMN> <op> <value>` where op is one of > >= < <= == != and value is a number, "
        "another known column, or `NUMBER * COLUMN`. Known columns: "
        + ", ".join(sorted(CUSTOM_DSL_COLUMNS)) + "."
    )
    st.text_area(
        "Strategy rules",height=160,key="custom_strategy",
        placeholder="RSI14 > 55\nCLOSE > EMA200\nVOLUME > 1.5 * VOL20",
        label_visibility="collapsed"
    )
    if st.button("🔍 Validate Strategy",key="custom_validate"):
        _,verr=parse_custom_strategy(st.session_state.get("custom_strategy",""))
        if verr:
            for e in verr: st.error(e)
        else:
            st.success("Strategy is valid. Ready to scan + backtest below.")

    st.markdown("### Indian Stocks — local-only scan + backtest")
    st.caption("Reuses the same local candle cache, fast features, and O(1) regime/safety lookups as the Daily Scanner and Backtest tabs. Makes zero Dhan/API calls.")
    cc1,cc2,cc3,cc4=st.columns(4)
    custom_universes=cc1.multiselect(
        "Universe",["Nifty 500","Nifty Smallcap 100","Nifty Smallcap 250","Nifty Midcap 150"],
        default=["Nifty 500"],key="custom_universe"
    )
    custom_period=cc2.selectbox("Backtest span",["6 Months","1 Year","2 Years","3 Years"],index=0,key="custom_period")
    custom_sl_pct=cc3.slider("Stop loss %",1.0,15.0,7.0,0.5,key="custom_sl_pct")/100
    custom_target_r=cc4.number_input("Target (R multiple)",1.0,10.0,3.0,0.5,key="custom_target_r")

    if st.button("🔬 Run Custom Strategy Scan + Backtest",type="primary",key="custom_run"):
        conditions,cerr=parse_custom_strategy(st.session_state.get("custom_strategy",""))
        if cerr:
            for e in cerr: st.error(e)
        elif not conditions:
            st.warning("Enter at least one rule line before running.")
        elif not custom_universes:
            st.warning("Select at least one universe.")
        else:
            try:
                tickers=sorted(set(sum([index_universe(u) for u in custom_universes],[])))
            except Exception as e:
                st.error(f"Could not load index universe constituents (network/data issue): {e}")
                tickers=[]
            if tickers:
                cstart,cend=_bt_period(custom_period)
                status=local_backtest_status(tickers,cstart,cend)
                ready=int(status.Ready.sum()) if not status.empty else 0
                if ready==0:
                    st.error("No local candle data for this universe. Use Data Manager → SYNC ONLY MISSING DATA first.")
                else:
                    try:
                        with st.spinner(f"Replaying {ready:,} locally cached stocks against the custom rules..."):
                            data=load_local_backtest_data(tickers,cstart,cend)
                            cbt=_custom_strategy_backtest(data,conditions,cstart,cend,custom_sl_pct,float(custom_target_r))
                        st.session_state["custom_backtest"]=cbt
                        learned=_learn_from_backtest(cbt)
                        st.success(f"{len(cbt):,} historical CUSTOM setups found; {learned:,} saved to the learning database as strategy='CUSTOM'.")

                        st.subheader("📡 Today's Custom Strategy Candidates")
                        ml_model_custom=train_win_probability_model("INDIA")
                        today_rows=[]
                        for ticker,df in data.items():
                            if len(df)<260: continue
                            f=features_fast(str(ticker),df).replace([np.inf,-np.inf],np.nan)
                            if f.empty or len(f)<260: continue
                            if not bool(custom_strategy_signal(f,conditions).iloc[-1]): continue
                            i=len(f)-1
                            avg_value,abnormal=_safety_fast_series(df)
                            regime,_=_regime_from_row(f,i)
                            safe,safe_status,_=_safety_from_row(avg_value,abnormal,i)
                            score,parts=final_setup_score(f,"CUSTOM",regime,safe)
                            entry=float(f.close.iloc[-1]); stop=entry*(1-custom_sl_pct)
                            target=entry+float(custom_target_r)*(entry-stop)
                            row={
                                "Ticker":str(ticker).replace(".NS",""),"Score":score,"Regime":regime,
                                "Safety":safe_status,"Entry":round(entry,2),"Stop":round(stop,2),
                                "Target":round(target,2),"HTF Score":parts["HTF Demand"],
                                "Footprint Score":parts["Footprint"],"Entry Quality":parts["Entry Quality"],
                                "Relative Strength":parts["Relative Strength"],"Strategy":"CUSTOM",
                            }
                            wp=ml_win_probability(ml_model_custom,row)
                            if pd.isna(wp): wp=fallback_win_probability("INDIA","CUSTOM",float(score))
                            row["Win Probability %"]=wp
                            today_rows.append(row)
                        if today_rows:
                            st.dataframe(pd.DataFrame(today_rows).sort_values("Score",ascending=False),width='stretch',hide_index=True)
                        else:
                            st.info("No stock currently satisfies every custom rule.")
                    except Exception as ex:
                        st.error(f"Custom strategy backtest error: {ex}")

    cbt=st.session_state.get("custom_backtest",pd.DataFrame())
    if not cbt.empty:
        st.subheader("🏆 Custom Strategy — Historical Results")
        a,b,c,d=st.columns(4)
        a.metric("Trades",len(cbt))
        b.metric("Win %",f"{(cbt.Outcome.str.upper()=='WIN').mean()*100:.1f}%")
        c.metric("Avg R",f"{cbt.R.mean():.2f}")
        d.metric("Total R",f"{cbt.R.sum():.2f}")
        st.dataframe(cbt.sort_values(['Score','Date'],ascending=[False,False]),width='stretch',hide_index=True)

st.markdown("---")
st.caption("Research / paper-testing system. Real-money Dhan order execution is intentionally disabled.")


# ========================= FINAL RESEARCH & RISK CONTROL =========================
with tabs[11]:
    st.subheader("🧬 Research & Risk Control — Final Architecture")
    st.caption("This control layer is intentionally separate from deterministic S1–S4 qualification. It measures whether the system is actually learning without changing the rules silently.")
    a,b,c,d=st.columns(4)
    con=_db()
    try:
        candles=int(con.execute("SELECT COUNT(*) FROM candles").fetchone()[0])
        stocks=int(con.execute("SELECT COUNT(DISTINCT symbol) FROM candles").fetchone()[0])
        learn=int(con.execute("SELECT COUNT(*) FROM learning_observations").fetchone()[0])
        ft=int(con.execute("SELECT COUNT(*) FROM forward_tests").fetchone()[0])
    finally: con.close()
    a.metric("Cached candles",f"{candles:,}"); b.metric("Cached stocks",f"{stocks:,}"); c.metric("Learning observations",f"{learn:,}"); d.metric("Forward records",f"{ft:,}")

    st.markdown("### Architecture safeguards")
    safeguards=pd.DataFrame([
        ["Exact S1–S4 qualification","ON","Learning cannot rewrite rules"],
        ["No-lookahead MTF features","ON","Historical week/month are as-of each date"],
        ["Dhan/local separation","ON","Backtest runner makes zero Dhan calls"],
        ["Persistent data cache","ON","Only missing ranges are downloaded"],
        ["Adaptive ranking","ON","Ranking only; qualification unchanged"],
        ["Fundamental enrichment","Candidate-only","Cached to avoid CPU/API overload"],
        ["News/event risk","Candidate-only","Press releases cached; risk never creates signals"],
        ["Real orders","OFF","Research/paper trading only"],
    ],columns=["Control","Status","Purpose"])
    st.dataframe(safeguards,width='stretch',hide_index=True)

    st.markdown("### 🧪 S4 Recovery — historical study")
    st.caption("Research hypothesis: large impulse → controlled consolidation/retracement → compression → reclaim → higher high. Exact S4 remains unchanged.")
    c1,c2,c3=st.columns(3)
    study_years=c1.selectbox("Study period",["6 Months","1 Year","2 Years","3 Years"],index=2,key="s4_walk_years")
    study_threshold=c2.slider("Recovery score",50,95,70,key="s4_walk_score")
    study_universe=c3.selectbox("Study universe",["Nifty 500","Nifty Smallcap 100","Nifty Smallcap 250","Nifty Midcap 150"],key="s4_walk_universe")
    if st.button("🔬 RUN S4 RECOVERY WALK-FORWARD STUDY",type="primary",key="s4_walk_run"):
        try:
            with st.spinner("Running S4 recovery walk-forward study..."):
                sd,ed=_bt_period(study_years); ticks=index_universe(study_universe)
                data=load_local_market_dataset(tuple(ticks),sd-timedelta(days=1000),ed,160)
                study=study_s4_recovery_walkforward(data,sd,ed,study_threshold)
            st.session_state["s4_recovery_bt_final"]=study
        except Exception as ex: st.error(f"S4 Recovery study error: {ex}")
    s4bt=st.session_state.get("s4_recovery_bt_final",pd.DataFrame())
    if s4bt.empty: st.info("Run the study to compare recovery setups against exact S4 behaviour.")
    else:
        m=research_metrics(s4bt)
        aa,bb,cc,dd=st.columns(4); aa.metric("Trades",m["trades"]); bb.metric("Win %",f"{m['win_rate']:.1f}%"); cc.metric("Avg R",f"{m['avg_r']:.2f}"); dd.metric("Profit Factor",f"{m['profit_factor']:.2f}")
        st.dataframe(s4bt.sort_values(["Score","Date"],ascending=[False,False]).head(300),width='stretch',hide_index=True)
        st.warning("Promotion rule: S4 Recovery is not allowed into the exact strategy until it survives out-of-sample/walk-forward evidence with adequate sample size and positive expectancy.")

    st.markdown("### 🛡️ Portfolio risk simulator")
    capital=st.number_input("Starting capital ₹",10000,100000000,100000,10000,key="risk_capital_final")
    risk_pct=st.slider("Risk per trade %",0.25,3.0,1.0,0.25,key="risk_pct_final")
    slots=st.slider("Maximum concurrent positions",1,20,5,key="risk_slots_final")
    bt=st.session_state.get("backtest_final",pd.DataFrame())
    if bt.empty: st.info("Run the local backtest first to simulate capital-aware portfolio results.")
    else:
        pr=portfolio_from_backtest(bt,float(capital),float(risk_pct),int(slots))
        st.dataframe(pd.DataFrame([pr]),width='stretch',hide_index=True)

    st.markdown("### 🧭 Advocate mode")
    st.info("The system should reject a trade when deterministic rules fail, safety is unacceptable, data quality is poor, or the learned evidence is insufficient. It should never manufacture a reason to trade.")

with tabs[12]:
    st.subheader("🎓 Strategy Coach")
    st.caption(
        "Read-only analysis of completed trades per strategy: regime win-rate/avg-R, high-vs-low "
        "component splits, and a shallow decision tree translated into plain-English rules. "
        "This never changes S1-S4/CUSTOM rules — it only reports what the evidence shows so far."
    )
    coach_strategy = st.selectbox("Strategy", ["S1", "S2", "S3", "S4", "CUSTOM"], key="coach_strategy")
    report = strategy_coach_report("INDIA", coach_strategy)

    if report is None:
        st.info(f"No completed {coach_strategy} observations yet. Run a backtest or complete forward-test trades first.")
    else:
        a, b = st.columns(2)
        a.metric("Completed observations", report["n_samples"])
        b.metric("Overall win % / avg R", f"{report['overall_win_rate']}% / {report['overall_avg_r']}")

        if not report["enough_for_breakdown"]:
            st.warning(
                f"Only {report['n_samples']} completed {coach_strategy} observations — need "
                f"≥{STRATEGY_COACH_MIN_SAMPLES} before the regime/component breakdown is shown. "
                "Treat any pattern below this threshold as noise, not evidence."
            )
        else:
            st.markdown("### 📊 Win rate / Avg R by regime")
            if report["regime_breakdown"].empty:
                st.info("No regime breakdown available yet.")
            else:
                st.dataframe(report["regime_breakdown"], width='stretch', hide_index=True)
                st.caption("Samples below ~10-15 per regime are too thin to draw conclusions from.")

            st.markdown("### 🔬 Component win-rate split (high half vs low half)")
            if report["component_breakdown"].empty:
                st.info("No component split available yet (not enough score variance in this strategy's history).")
            else:
                st.dataframe(report["component_breakdown"], width='stretch', hide_index=True)
                st.caption("Splits each score component at its median for this strategy's history and compares the two halves.")

        st.markdown("### 🌳 Auto-extracted rules")
        if report["tree_note"]:
            st.info(report["tree_note"])
        else:
            st.dataframe(pd.DataFrame(report["tree_rules"]), width='stretch', hide_index=True)
            st.caption(
                "Each row is one path through a shallow (depth ≤3) decision tree fit on completed "
                "outcomes, sorted by win rate then sample size. Read as: \"when these conditions held, "
                "this strategy's setups won at this rate over this many trades.\" These are patterns in "
                "past evidence, not guaranteed future performance — the smaller the sample, the less "
                "the rule should influence live decisions."
            )

with tabs[13]:
    st.subheader("💱 Forex/Crypto SMC — Smart Money Concepts (HTF 4h + LTF 15min)")
    st.caption(
        "Separate research engine from S1-S4. HTF (4h) establishes market structure/bias via "
        "MSB + order blocks + FVGs + premium/discount zones; LTF (15min) confirms entry with a "
        "micro-MSB or liquidity sweep inside the HTF zone. Real-money order execution remains disabled."
    )
    st.warning(
        "⚠️ No economic calendar / news-day filter is wired in. Manually check for CPI, NFP, and "
        "rate-decision days before acting on any signal below — this is not automated."
    )

    if not twelvedata_configured():
        st.warning("Add TWELVEDATA_API_KEY to Streamlit Secrets to activate this tab.")
    else:
        # "Market" is informational only — Twelve Data's symbol format (e.g.
        # "XAU/USD", "BTC/USD") is what actually matters to the API, so every
        # instrument (forex, metals, crypto) is offered in one combined list
        # instead of gating pairs behind a Forex/Crypto toggle.
        SMC_PRESET_PAIRS = [
            "EUR/USD", "GBP/USD", "USD/JPY", "USD/CHF", "AUD/USD", "USD/CAD", "NZD/USD",
            "XAU/USD", "XAG/USD",
            "BTC/USD", "ETH/USD", "SOL/USD", "XRP/USD", "BNB/USD", "DOGE/USD",
        ]
        smc_market = st.selectbox(
            "Market (informational only — affects labeling, not which pairs you can pick)",
            ["Forex", "Crypto"], key="smc_market"
        )
        c1, c2, c3 = st.columns(3)
        smc_confluence = c1.slider("Min confluence score", 1, 5, 2, key="smc_confluence")
        smc_body_pct = c2.slider("Strong MSB: min candle body %", 30, 90, 60, 5, key="smc_body_pct") / 100
        smc_beyond_pct = c3.slider("Strong MSB: min close-beyond %", 0, 30, 10, 1, key="smc_beyond_pct") / 100
        st.caption("These three are calibrated guesses from the source guide, not exact values from any source — tune freely.")

        st.markdown("### 🔍 Live Multi-Pair Scan")
        smc_scan_pairs = st.multiselect(
            "Pairs to scan", SMC_PRESET_PAIRS,
            default=["EUR/USD", "GBP/USD", "USD/JPY", "XAU/USD", "BTC/USD", "ETH/USD"],
            key="smc_scan_pairs"
        )
        smc_extra_pairs_raw = st.text_input(
            "Additional pairs not in the list above (comma separated, Twelve Data symbol format)",
            "", key="smc_extra_pairs", placeholder="e.g. USD/INR, LTC/USD, WTI/USD"
        )
        smc_extra_pairs = [p.strip().upper() for p in smc_extra_pairs_raw.split(",") if p.strip()]
        smc_all_scan_pairs = list(dict.fromkeys(smc_scan_pairs + smc_extra_pairs))  # dedupe, keep order

        if st.button("🔍 Scan SMC Setups", type="primary", key="smc_scan_run"):
            if not smc_all_scan_pairs:
                st.warning("Select or type at least one pair.")
            else:
                with st.spinner(f"Scanning {len(smc_all_scan_pairs)} pair(s) for SMC setups..."):
                    smc_results = scan_smc_pairs(smc_all_scan_pairs, smc_market, smc_confluence, smc_body_pct, smc_beyond_pct)
                st.session_state["smc_scan_results"] = smc_results

        smc_results = st.session_state.get("smc_scan_results", pd.DataFrame())
        if smc_results.empty:
            st.info("No SMC setups found yet. Run a scan above.")
        else:
            errors = smc_results[smc_results.get("direction") == "ERROR"] if "direction" in smc_results.columns else pd.DataFrame()
            valid = smc_results[smc_results.get("direction") != "ERROR"] if "direction" in smc_results.columns else smc_results
            if not errors.empty:
                for _, e in errors.iterrows():
                    st.caption(f"⚠️ {e['Pair']}: {e['zone_label']}")
            if valid.empty:
                st.info("No qualifying setups right now (all selected pairs either had no valid HTF zone or failed the confluence gate).")
            else:
                st.dataframe(valid.drop(columns=["confluence_matched", "note"], errors="ignore"), width='stretch', hide_index=True)
                for _, row in valid.iterrows():
                    st.caption(f"**{row['Pair']}** ({row['direction'].upper()}): {row.get('note','')}")
                added = add_smc_forward_candidates(valid)
                if added:
                    st.success(f"{added} setup(s) added to forward-test tracking as strategy='FX_SMC'.")

        st.markdown("### 🧪 Backtest")
        st.warning(
            "Backtest slippage is a fixed 0.05% placeholder, not a real spread/liquidity/session model. "
            "Do not treat these R-multiples as production-accurate."
        )
        st.info(
            "⏱️ **How much history you actually get**: Twelve Data returns at most 5,000 bars per request "
            "regardless of the lookback you pick below. At 15min (the LTF leg this backtest walks bar-by-bar), "
            "5,000 bars ≈ 52 days (~1.7 months) — that's the real ceiling even if you ask for 12 months. "
            "HTF (4h) easily covers a full year in 5,000 bars, but the LTF cap is what actually limits the "
            "backtest's trade count. The exact coverage you got is shown after each run below."
        )
        bc1, bc2, bc3, bc4 = st.columns(4)
        smc_bt_pair_choice = bc1.selectbox("Pair", SMC_PRESET_PAIRS + ["✏️ Custom..."], key="smc_bt_pair_choice")
        if smc_bt_pair_choice == "✏️ Custom...":
            smc_bt_pair = bc1.text_input("Custom pair (Twelve Data symbol)", "EUR/USD", key="smc_bt_pair_custom")
        else:
            smc_bt_pair = smc_bt_pair_choice
        smc_bt_years = bc2.selectbox("Requested lookback", [0.25, 0.5, 1, 2], index=2, format_func=lambda y: f"{y} yr", key="smc_bt_years")
        smc_bt_capital = bc3.number_input("Starting capital", 1000, 10000000, 100000, 1000, key="smc_bt_capital")
        smc_bt_risk = bc4.number_input("Risk per trade %", 0.25, 5.0, 1.0, 0.25, key="smc_bt_risk")
        if st.button("🧪 Run SMC Backtest", type="primary", key="smc_bt_run"):
            try:
                with st.spinner(f"Fetching HTF/LTF history and replaying {smc_bt_pair}..."):
                    smc_htf = td_market_history(smc_bt_pair, smc_market, "4h", years=smc_bt_years)
                    smc_ltf = td_market_history(smc_bt_pair, smc_market, "15min", years=smc_bt_years)
                    if smc_htf.empty or smc_ltf.empty or len(smc_htf) < 60 or len(smc_ltf) < 60:
                        st.error("Not enough HTF/LTF history returned for this pair.")
                    else:
                        htf_days = (smc_htf.index[-1] - smc_htf.index[0]).days
                        ltf_days = (smc_ltf.index[-1] - smc_ltf.index[0]).days
                        st.caption(
                            f"📊 Actually fetched: HTF {len(smc_htf):,} bars (~{htf_days} days) | "
                            f"LTF {len(smc_ltf):,} bars (~{ltf_days} days, ~{ltf_days/30.4:.1f} months)"
                        )
                        smc_trades, smc_equity = smc_backtest(
                            smc_htf, smc_ltf, float(smc_bt_capital), float(smc_bt_risk),
                            smc_confluence, 0.0005, smc_body_pct, smc_beyond_pct
                        )
                        st.session_state["smc_backtest_trades"] = smc_trades
                        st.session_state["smc_backtest_equity"] = smc_equity
            except Exception as ex:
                st.error(f"SMC backtest error: {ex}")

        smc_trades = st.session_state.get("smc_backtest_trades", pd.DataFrame())
        if smc_trades.empty:
            st.info("Run the backtest to see historical SMC trade results.")
        else:
            a, b, c, d = st.columns(4)
            a.metric("Trades", len(smc_trades))
            b.metric("Win %", f"{(smc_trades.Outcome=='WIN').mean()*100:.1f}%")
            c.metric("Avg R", f"{smc_trades.R.mean():.2f}")
            d.metric("Total R", f"{smc_trades.R.sum():.2f}")
            st.dataframe(smc_trades, width='stretch', hide_index=True)
            smc_equity = st.session_state.get("smc_backtest_equity", [])
            if len(smc_equity) > 1:
                st.line_chart(pd.Series(smc_equity, name="Equity"))

        with st.expander("🔬 Debug: Swing/MSB Detection (cross-check against a real chart)"):
            st.caption(
                "Prints the raw swing points and MSB events this engine detects for one pair/timeframe, "
                "with timestamps, so you can manually verify them against a real chart (e.g. TradingView) "
                "before trusting the scan/backtest above."
            )
            dc1, dc2 = st.columns(2)
            debug_pair = dc1.text_input("Pair", smc_bt_pair, key="smc_debug_pair")
            debug_tf = dc2.selectbox("Timeframe", ["4h", "15min"], key="smc_debug_tf")
            if st.button("🔬 Run Debug Detection", key="smc_debug_run"):
                try:
                    with st.spinner(f"Fetching {debug_pair} {debug_tf}..."):
                        debug_df = td_market_history(debug_pair, smc_market, debug_tf, years=1)
                    if debug_df.empty or len(debug_df) < 20:
                        st.error("Not enough history returned for this pair/timeframe.")
                    else:
                        d_swung = detect_swings(debug_df)
                        d_atr = _atr(d_swung)
                        d_msbs = detect_msb(d_swung, d_atr, smc_body_pct, smc_beyond_pct)
                        sh = d_swung[d_swung.swing_high][["close"]].rename(columns={"close": "Swing High"})
                        sl = d_swung[d_swung.swing_low][["close"]].rename(columns={"close": "Swing Low"})
                        st.markdown("**Swing highs:**")
                        if not sh.empty:
                            st.dataframe(sh, width='stretch')
                        else:
                            st.info("None detected.")
                        st.markdown("**Swing lows:**")
                        if not sl.empty:
                            st.dataframe(sl, width='stretch')
                        else:
                            st.info("None detected.")
                        st.markdown("**MSB events:**")
                        if d_msbs:
                            msb_rows = [{
                                "Timestamp": d_swung.index[m["idx"]], "Direction": m["direction"],
                                "Strength": m["strength"], "Broken Level": round(m["broken_level"], 5)
                            } for m in d_msbs]
                            st.dataframe(pd.DataFrame(msb_rows), width='stretch', hide_index=True)
                        else:
                            st.info("None detected.")
                except Exception as ex:
                    st.error(f"Debug detection error: {ex}")

with tabs[14]:
    st.subheader("🚨 Early Warning Radar — setups forming BEFORE they trigger")
    st.caption(
        "The Daily Scanner is binary: a stock is invisible until the day it passes every rule, "
        "which is the day the move has usually already started. This tab shows the stocks that are "
        "one or two rules away, names the rule that is blocking them, measures how far it has to "
        "travel, and weighs that against how tightly the stock is coiled. It changes nothing about "
        "S1–S4 qualification — it is a watchlist, not a signal."
    )

    ra, rb, rc = st.columns(3)
    radar_universes = ra.multiselect(
        "Universes",
        ["Nifty 500","Nifty Smallcap 100","Nifty Smallcap 250","Nifty Midcap 150"],
        ["Nifty 500"],
        key="radar_universes"
    )
    radar_strategies = rb.multiselect(
        "Strategies", [1,2,3,4], [1,2,3,4], key="radar_strategies"
    )
    radar_max_missing = rc.selectbox(
        "How close must a setup be?",
        [0,1,2],
        index=1,
        format_func=lambda n: {0:"Triggered only (0 rules missing)",
                               1:"1 rule away",
                               2:"Up to 2 rules away"}[n],
        key="radar_max_missing"
    )

    rd_, re_ = st.columns(2)
    radar_min_readiness = rd_.slider("Minimum readiness", 0, 100, 45, 5, key="radar_min_readiness")
    radar_use_live = re_.checkbox(
        "Use live intraday price", value=nse_market_is_open(), key="radar_use_live",
        help="Overlays today's forming candle so the radar reflects the price right now."
    )

    st.markdown("### 📅 Data Freshness")
    try:
        _radar_universe=set()
        for u in radar_universes:
            _radar_universe.update(index_universe(u))
        radar_tickers=sorted(_radar_universe)
    except Exception as ex:
        radar_tickers=[]
        st.caption(f"Could not verify data freshness: {ex}")
    render_data_freshness_banner(radar_tickers)

    if st.button("🚨 RUN EARLY WARNING RADAR", type="primary", key="radar_run"):
        if not radar_tickers:
            st.warning("Select at least one universe.")
        elif not radar_strategies:
            st.warning("Select at least one strategy.")
        else:
            try:
                radar_data={}
                with st.spinner(f"Loading local price cache for {len(radar_tickers):,} stocks..."):
                    con=_db()
                    try:
                        for ticker in radar_tickers:
                            clean=str(ticker).upper().replace(".NS","")
                            d=_read_cache(con,clean,date.today()-timedelta(days=1000),date.today())
                            if d is not None and len(d)>=260:
                                radar_data[ticker]=d
                    finally:
                        con.close()

                if not radar_data:
                    st.error("Local dataset is empty. Run a sync in the Data Manager or the Scanner tab first.")
                else:
                    radar_asof=None
                    if radar_use_live and nse_market_is_open():
                        with st.spinner("Fetching live intraday prices..."):
                            radar_data, radar_bars = attach_live_bars(radar_data)
                        if radar_bars:
                            radar_asof=max(b["ts"] for b in radar_bars.values())

                    radar_proxy=max(radar_data.values(), key=len)
                    radar_regime, _radar_rs = regime_from_index(radar_proxy)

                    radar_bar=st.progress(0.0)
                    radar_stats={}
                    with st.spinner(f"Evaluating {len(radar_data):,} stocks against every rule..."):
                        radar_df=early_warning_radar(
                            radar_data, radar_strategies, radar_regime,
                            max_missing=int(radar_max_missing),
                            min_readiness=int(radar_min_readiness),
                            progress_cb=lambda f: radar_bar.progress(min(1.0,f)),
                            stats=radar_stats
                        )
                    radar_bar.empty()
                    st.session_state["radar_result"]=radar_df
                    st.session_state["radar_meta"]={
                        "regime":radar_regime,"asof":radar_asof,
                        "stats":radar_stats,"universe":len(radar_data)
                    }
            except Exception as ex:
                st.error(f"Radar error: {ex}")

    radar_df=st.session_state.get("radar_result")
    radar_meta=st.session_state.get("radar_meta",{})
    if radar_df is not None:
        rstats=radar_meta.get("stats",{})
        st.caption(
            f"Regime: **{radar_meta.get('regime','—')}** · {rstats.get('scanned',0):,} stocks evaluated"
            + (f" · live price as of {radar_meta['asof']}" if radar_meta.get("asof") else " · last completed close")
        )
        if rstats.get("feature_error"):
            st.warning(
                f"{rstats['feature_error']:,} stock(s) were skipped because their features could not be "
                f"computed. Last error — {rstats.get('last_error','')}"
            )

        if radar_df.empty:
            st.info(
                "Nothing on the radar at this readiness level. Lower the minimum readiness, or widen "
                "'How close must a setup be?' to 2 rules."
            )
        else:
            triggered=int((radar_df["State"]=="🔥 TRIGGERED").sum())
            one_away=int((radar_df["State"]=="⚡ 1 RULE AWAY").sum())
            two_away=int((radar_df["State"]=="👀 2 RULES AWAY").sum())
            coiled=int((pd.to_numeric(radar_df["Compression"],errors="coerce")>=65).sum())
            m1,m2,m3,m4=st.columns(4)
            m1.metric("Triggered now",triggered)
            m2.metric("1 rule away",one_away)
            m3.metric("2 rules away",two_away)
            m4.metric("Tightly coiled",coiled)

            st.markdown("### 🎯 Highest-priority watchlist")
            st.caption(
                "Readiness blends how close the setup is to triggering (55%) with how compressed the "
                "stock is (35%) and the market regime. A coiled stock one rule away is where an early "
                "alert is worth the most."
            )
            st.dataframe(
                radar_df,
                width='stretch', hide_index=True,
                column_config={
                    "Readiness": st.column_config.ProgressColumn(
                        "Readiness", min_value=0, max_value=100, format="%.0f"),
                    "Compression": st.column_config.ProgressColumn(
                        "Compression", min_value=0, max_value=100, format="%.0f"),
                    "Worst Gap %": st.column_config.NumberColumn(
                        "Worst Gap %", format="%.2f%%",
                        help="How far the most distant failing rule still has to travel."),
                }
            )
            st.download_button(
                "⬇️ Download radar watchlist",
                radar_df.to_csv(index=False).encode(),
                "early_warning_radar.csv","text/csv",key="radar_download"
            )

            st.markdown("### 🧱 What is blocking the most stocks right now")
            st.caption(
                "When one rule holds back hundreds of otherwise-qualifying stocks, that rule is the "
                "binding constraint on the whole universe today — evidence about the market's state, "
                "not a per-stock accident."
            )
            try:
                st.dataframe(radar_missing_rule_summary(radar_df).head(25),
                             width='stretch',hide_index=True)
            except Exception as ex:
                st.error(f"Blocking-rule summary error: {ex}")

            st.markdown("### 🧨 Coiled springs — tightest setups near a trigger")
            spring=radar_df[
                (pd.to_numeric(radar_df["Compression"],errors="coerce")>=60) &
                (radar_df["State"]!="👀 2 RULES AWAY")
            ].head(25)
            if spring.empty:
                st.info("No tightly-compressed near-trigger setups in this scan.")
            else:
                st.dataframe(
                    spring[["Ticker","Strategy","State","Readiness","Compression","Squeeze %ile",
                            "Range Ratio","Vol Dry-Up","NR7","Inside Bars","From 52w High %",
                            "Close","ATR %","Missing Rules"]],
                    width='stretch',hide_index=True
                )
                st.caption(
                    "Squeeze %ile is today's range against its own 120-day distribution — low means "
                    "coiled. Range Ratio compares the last 5 days' range to the last 60. Vol Dry-Up "
                    "below 1.0 means volume is contracting into the base."
                )
    else:
        st.info("Set your filters and run the radar to build a pre-trigger watchlist.")

st.markdown("---")
st.caption(f"{APP_VERSION} • {ARCHITECTURE_STANDARD} • Research only • Real-money order execution disabled")

