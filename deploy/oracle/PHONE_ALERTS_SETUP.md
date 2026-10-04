# Phone Alerts Setup Guide

## Quick Start (3 Minutes)

### 1. Install ntfy App
- **iOS**: Search "ntfy" in App Store → Install
- **Android**: Search "ntfy" in Play Store → Install
- **Alternative**: Visit https://ntfy.sh in your browser

### 2. Get Your Alert Topic
1. Open your browser
2. Go to: `http://{ORACLE_IP}/reports/trend.html`
3. Scroll to **"Phone alerts"** section
4. Copy the topic name (format: `ati-trend-{8-random-chars}`)

### 3. Subscribe in ntfy App

**iOS/Android:**
1. Open ntfy app
2. Tap the **+** button (bottom right)
3. Paste your topic name
4. Select server: **ntfy.sh**
5. Tap **Subscribe**
6. ✅ Done! First alert arrives in 5 minutes

**Web (https://ntfy.sh):**
1. Go to https://ntfy.sh
2. In the URL bar, add your topic: `https://ntfy.sh/ati-trend-xyz123`
3. Press Enter
4. ✅ Keep the page open to receive alerts

---

## How Alerts Work

### Alert Schedule
- **Every 5 minutes**: trend_paper.py scans all 9 pairs
- **On breakout**: Normal alert "Wait for retest"
- **On retest**: 🔴 URGENT alert "Execute immediately"
- **On exit**: Normal alert "Position closed"

### Example Alert Flow
```
14:00 IST → 🔔 BTCUSDT Breakout Detected
           Entry: 43,250 | Stop: 42,800 | Leverage: 8x
           [ACTION: Wait for price to retest 43,250]

14:05 IST → 🔴🔴 BTCUSDT RETEST ENTRY NOW!
           Entry: 43,250 | Stop: 42,800 | Leverage: 8x
           [ACTION: Enter immediately - price is retesting!]

14:20 IST → 🔔 BTCUSDT Position Filled
           Entry confirmed at 43,250
           [ACTION: Monitor for exit signal]

15:30 IST → 🔔 BTCUSDT Exit Alert
           Exit triggered: 4h close below 20-bar low
           Exit price: 43,500 | P&L: +250 (0.58R)
           [ACTION: Trade closed - review results]
```

---

## Alert Types & Meanings

### 🟢 Breakout Detected (Green)
- **When**: Price closes above 55-bar high on 4h chart
- **What to do**: Wait for retest (don't chase)
- **Info provided**: Entry price, stop loss, leverage
- **Timeline**: Usually happens once per pair per week

### 🔴 RETEST ENTRY NOW! (Red/Urgent)
- **When**: Price comes back to test the breakout level
- **What to do**: Execute trade immediately
- **Info provided**: Exact entry, stop, leverage, position size
- **Priority**: Read immediately - this is your entry signal
- **Note**: Only in retest mode; urgent alert from trend_paper.py

### 🟡 Position Filled (Neutral)
- **When**: Entry order executed
- **What to do**: Set stop-loss, monitor position
- **Info provided**: Entry price, stop level, leverage
- **Important**: Stop is auto-managed in paper trading

### ⚠️ Exit Alert (Warning)
- **When**: Exit condition met (20-bar low close or stop hit)
- **What to do**: Review P&L, prepare next signal
- **Info provided**: Exit price, P&L in rupees, R-multiple
- **Example**: "Exit: 43,500 | P&L: +500 | +1.15R"

---

## Understanding the Alert Content

### Standard Alert Format
```
🚀 BTCUSDT RETEST ENTRY NOW
───────────────────────────
Entry: 43,250
Stop:  42,800
Leverage: 8x
Risk: 2% of equity
Position size: 0.45 BTC
Expected R: 0.66R
```

### What Each Field Means
| Field | Meaning | What to do |
|-------|---------|-----------|
| **BTCUSDT** | Trading pair (Crypto or Forex) | The instrument being traded |
| **Entry** | Price to buy at | Your entry point |
| **Stop** | Price to exit if wrong | Set stop order here |
| **Leverage** | How many times equity | Position sizing already done |
| **Risk** | % of account risked | 2% standard risk rule |
| **Position size** | How much to buy | Already calculated |
| **Expected R** | Expected profit multiple | Historical average |

---

## Phone Alert Permissions

### iOS
1. Open **Settings** → **Notifications**
2. Find **ntfy** app
3. Toggle **Allow Notifications** ON
4. Select **Sound** (important for timely alerts)
5. Select **Banners** (shows on lock screen)

### Android
1. Open **Settings** → **Apps** → **ntfy**
2. Tap **Notifications**
3. Toggle **Allow notifications** ON
4. Go back, tap **Advanced**
5. Select **Importance level**: **High**
6. Enable **Sound** and **Vibrate**

### Web Browser
- Keep https://ntfy.sh tab open in your browser
- Browser notifications must be enabled
- Alerts appear even if tab is in background

---

## Testing Your Alerts

### Test Alert #1: Direct Message
```bash
# On any device with internet
curl -d "Test message from Claude" https://ntfy.sh/ati-trend-test123
```
You should see the alert in your ntfy app within 1 second.

### Test Alert #2: Through Oracle Server
```bash
# SSH to Oracle server
ssh ubuntu@{ORACLE_IP}

# Trigger a test trend alert
cd /opt/ati-lab && \
  docker compose -f deploy/oracle/docker-compose.yml exec api \
  python -c "
    import os
    os.environ['NTFY_TOPIC'] = '{your-topic}'
    from app.tasks.trend_paper import notify
    notify('test', 'System Test', 'Alerts working! 🚀')
  "
```

### Test Alert #3: Wait for First Real Signal
The easiest test: just wait 5 minutes. If a pair breaks out on the 4h chart, you'll get a real alert.

---

## Troubleshooting Phone Alerts

### Not Receiving Alerts?

**Check 1: Correct Topic?**
```bash
# On Oracle server
cat /data/reports/trend-state.json | grep ntfy_topic
```
Make sure you're subscribed to the EXACT topic (case-sensitive).

**Check 2: ntfy App Running?**
- iOS/Android: Swipe down to verify app has notification permission
- Web: Refresh https://ntfy.sh in browser

**Check 3: Network Connection?**
- Verify your phone has internet (Wi-Fi or cellular)
- Try a test message: `curl -d "test" https://ntfy.sh/test-topic`

**Check 4: ntfy Server Status?**
- Visit https://ntfy.sh in browser
- You should see the website load
- If it doesn't, the ntfy service might be down (rare)

### Alerts Too Frequent?
- That's normal! 9 pairs × 5-min updates = potential alerts every 30-60 seconds
- Each pair breaks out ~1-2 times per week
- Most alerts are "waiting for retest" (can ignore if busy)

### Alerts Not Detailed Enough?
- All important info is included: entry, stop, leverage
- Full trade details are in `/reports/trend.html`
- Price updates visible on `/trading` dashboard

### Accidental Alert Spam?
- If testing creates too many alerts: unsubscribe and re-subscribe
- The topic is private (only you know it)
- No one else can send to your topic without the name

---

## Advanced: Custom Alert Topics

### Use Your Own Topic Name
Instead of auto-generated topic, set custom name on Oracle:

```bash
# SSH to Oracle server
ssh ubuntu@{ORACLE_IP}

# Edit .env file
sudo nano /opt/ati-lab/deploy/oracle/.env

# Add or modify:
NTFY_TOPIC=my-crypto-alerts

# Restart trend service
sudo systemctl restart ati-lab-trend.timer
```

Now alerts will use `my-crypto-alerts` instead of auto-generated name.

### Private vs Public Topic
- **Private**: Only you know the topic name = secure
- **Public**: Anyone who knows the topic can see alerts
- **ntfy.sh default**: Topics are unlisted but findable if URL is shared
- **Recommendation**: Keep topic name private, don't share it

---

## Integration with Other Apps

### Forward Alerts to Slack
1. Go to https://ntfy.sh/docs/integrations/
2. Find Slack integration
3. Set webhook in your Slack workspace
4. Alerts will post to Slack channel

### Forward Alerts to Email
1. Find your email-to-ntfy address format
2. Forward ntfy topics to your email
3. Get alerts via email (slower delivery)

### Forward Alerts to Telegram
1. Set up Telegram bot via ntfy integration
2. Forward crypto alerts to Telegram group
3. Share with trading partners

---

## Alert Best Practices

### ✅ DO
- Keep ntfy app open during trading hours
- Set high notification volume
- Enable lock screen notifications
- Check `/trading` dashboard when you get retest alert
- Review full trade details on `/crypto` dashboard
- Keep phone nearby during market hours

### ❌ DON'T
- Share your topic name publicly
- Ignore urgent (red) alerts
- Add others' topics to your app
- Assume alert = guaranteed profit (backtest, not guaranteed)
- Trade on other pairs without monitoring alerts

---

## Monitoring Dashboard

### Real-time Updates Available
While waiting for phone alerts, monitor in real-time on:

**Live Signals Dashboard**
- URL: `http://{ORACLE_IP}/trading`
- Shows: All 9 pairs, current status, entry/exit levels
- Updates: Every 5 seconds

**Crypto Trading Dashboard**
- URL: `http://{ORACLE_IP}/crypto`
- Shows: Equity, trades, P&L, recent closures
- Updates: Every 30 seconds

**Trend Report (HTML)**
- URL: `http://{ORACLE_IP}/reports/trend.html`
- Shows: Full trading journal, alert topic, backtest stats
- Updates: Every 5 minutes

---

## Summary

1. ✅ Download ntfy app (iOS/Android) or visit https://ntfy.sh
2. ✅ Get topic from `{ORACLE_IP}/reports/trend.html`
3. ✅ Subscribe to topic in ntfy app
4. ✅ Wait for first breakout alert (5 min - 1 week depending on market)
5. ✅ Act on urgent alerts immediately
6. ✅ Monitor dashboards for full trade details

**You're all set!** 🚀 Alerts start flowing the next time a pair breaks out on the 4h chart.

---

**Questions?** Check the main guide: `FINAL_DEPLOYMENT_GUIDE.md`
