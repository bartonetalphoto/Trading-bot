# 🤖 VALR Trend Bot — Setup Guide

Automated BTC/ZAR trend-following bot for VALR.  
Runs 24/7 free on Railway. Paper trading on by default — safe to start immediately.

-----

## 📁 Files

|File              |Purpose                     |
|------------------|----------------------------|
|`bot.py`          |Main bot loop               |
|`strategy.py`     |EMA crossover signal logic  |
|`valr_client.py`  |VALR REST API wrapper       |
|`config.py`       |All settings (edit this)    |
|`analyze.py`      |Performance report generator|
|`requirements.txt`|Python dependencies         |
|`Procfile`        |Railway deployment config   |

-----

## ✅ Step 1 — Create your VALR Account

1. Go to [valr.com](https://www.valr.com) and sign up
1. Complete KYC (SA ID + selfie — usually approved within minutes)
1. Deposit ZAR via EFT from your bank (Capitec, FNB, ABSA, Nedbank all work)
- Minimum deposit: R100
- No deposit fees from VALR’s side

-----

## 🔑 Step 2 — Get API Keys

1. Log into VALR
1. Click your account name (top right) → **API Keys**
1. **Enable 2FA first** (Google Authenticator) — required before generating keys
1. Click **Create API Key**
1. Give it a name like `trend-bot`
1. Enable only: ✅ **View** and ✅ **Trade**
1. ❌ Do NOT enable Withdraw
1. Save your **API Key** and **API Secret** — you won’t see the secret again!

-----

## 🚀 Step 3 — Deploy on Railway (Free Hosting)

Railway hosts your bot 24/7 in the cloud at no cost.

### 3a. Push to GitHub

1. Create a free account at [github.com](https://github.com)
1. Create a **private** repository called `valr-bot`
1. Upload all bot files to it

### 3b. Deploy

1. Go to [railway.app](https://railway.app) — sign up with GitHub
1. Click **New Project** → **Deploy from GitHub repo**
1. Select `valr-bot`
1. Railway detects Python automatically — click **Deploy**

### 3c. Add environment variables

In Railway → your project → **Variables** tab:

```
VALR_API_KEY     = your_64_char_key_here
VALR_API_SECRET  = your_64_char_secret_here
DATABASE_URL     = Railway Postgres URL (recommended)
LIVE_TRADING_ENABLED = false
```

⚠️ Never put your keys directly in the code files.

`LIVE_TRADING_ENABLED` is an extra safety gate. Bots can be configured for live
mode, but real orders are blocked unless this is set to `true`.

If `DATABASE_URL` is not set, the app uses a local SQLite file. That is fine for
local development, but Railway Postgres is recommended for durable bot state,
trades, backtests, and multi-bot operation.

-----

## ⚙️ Step 4 — Configure (config.py)

Key settings to review:

```python
PAPER_TRADING = True          # ← Keep True! Switch to False after 30 days
STARTING_CAPITAL_ZAR = 1000  # ← Your ZAR amount
STOP_LOSS_PERCENT = 0.05      # ← Exit if price drops 5% from entry
TAKE_PROFIT_PERCENT = 0.08    # ← Exit if price rises 8% from entry
FAST_EMA_PERIOD = 9           # ← Leave as-is to start
SLOW_EMA_PERIOD = 21          # ← Leave as-is to start
```

-----

## 📊 Step 5 — Monitor Your Bot

**Live logs** appear in Railway’s console. Look for:

```
[PAPER BUY]       — Bot detected uptrend, entered position
[PAPER SELL]      — Downtrend detected, exited position
[TAKE-PROFIT]     — Price hit +8%, locked in gains ✅
[STOP-LOSS]       — Price dropped 5%, protected capital ❌
[PAPER HOLD]      — No signal, waiting
Portfolio: R1082  — Your running balance & P&L
```

**Run the performance analyzer anytime:**

```bash
python analyze.py
```

This shows win rate, avg profit/loss, and trade history.

-----

## 📅 30-Day Paper Trading Plan

|Week  |Focus                                                       |
|------|------------------------------------------------------------|
|Week 1|Read every log line — understand why each signal fires      |
|Week 2|Check if 5% stop-loss is triggering too often (adjust if so)|
|Week 3|Run `analyze.py` — is win rate above 50%? Is P&L positive?  |
|Week 4|Make your go-live decision based on data, not emotion       |

-----

## 💰 Going Live

Only after 30 days of profitable paper trading:

1. In `config.py`, change:
   
   ```python
   PAPER_TRADING = False
   ```
1. Or switch an individual bot to live mode through the backend/dashboard
1. Set `LIVE_TRADING_ENABLED=true` in Railway
1. Commit and push to GitHub - Railway auto-redeploys
1. The bot can now place real orders with real money

Recommended: keep `LIVE_TRADING_ENABLED=false` until paper trading, backtests,
and risk settings are reviewed.

-----

## Current App Architecture

The app now runs as one Railway web service:

- `server.py` serves the PWA dashboard and API
- `bot.py` runs bots in a background runner thread
- `database.py` stores bot state and trades in SQLite or Postgres
- `models.py` defines bots and trades
- `backtesting.py` runs strategy simulations against candle data
- `exchanges.py` is the exchange adapter layer, with VALR implemented first

The dashboard creates real backend bots now. Extra bots are no longer just saved
in browser local storage.

-----

## Local Development

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn server:app --host 127.0.0.1 --port 8000
```

Open:

```text
http://127.0.0.1:8000
```

Run tests:

```bash
.venv/bin/python -m unittest discover -s tests
```

-----

## 🔧 Tweaking for Better Performance

|Setting                                 |Effect                                  |
|----------------------------------------|----------------------------------------|
|Lower `FAST_EMA_PERIOD` (e.g. 7)        |More signals, reacts faster, more noise |
|Higher `SLOW_EMA_PERIOD` (e.g. 30)      |Fewer false signals, misses some moves  |
|Lower `STOP_LOSS_PERCENT` (e.g. 0.03)   |Tighter protection, more stop-outs      |
|Higher `TAKE_PROFIT_PERCENT` (e.g. 0.12)|Holds winners longer, needs bigger moves|

After your first month, run `python analyze.py` and review the database-backed trade history to tune settings.

-----

## 🆘 Troubleshooting

**“Only X candles available”**
→ VALR needs time to build data. Wait a few cycles.

**API 401 Unauthorized**
→ Double-check your API key/secret in Railway Variables. Regenerate if needed.

**API 429 Too Many Requests**
→ Increase `POLL_INTERVAL_SECONDS` to `7200` (2 hours).

**Bot exits immediately**
→ Check Railway logs for the error message and share it for help.

-----

## ⚠️ Disclaimer

For educational purposes. Crypto trading is high risk.  
Never trade money you cannot afford to lose.  
Past performance does not guarantee future results.
