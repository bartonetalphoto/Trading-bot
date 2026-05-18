"""
Bot Configuration — VALR Edition
===================================
Keep PAPER_TRADING = True for your first 30 days!
"""

import os

# ── Credentials (set these as Railway env variables) ───────────────────────
# Get from: https://www.valr.com → top-right account menu → API Keys
# Enable 2FA first, then generate a key with: View + Trade permissions only.
VALR_API_KEY    = os.getenv("VALR_API_KEY",    "YOUR_API_KEY_HERE")
VALR_API_SECRET = os.getenv("VALR_API_SECRET", "YOUR_API_SECRET_HERE")

# ── Trading pair ────────────────────────────────────────────────────────────
# BTCZAR = Bitcoin priced in South African Rand
PAIR = "BTCZAR"

# ── Safety ──────────────────────────────────────────────────────────────────
# True  → paper trading only, no real money moves  ← START HERE
# False → live trading (only flip after 30 days of profitable paper trading)
PAPER_TRADING = True

# ── Capital ─────────────────────────────────────────────────────────────────
STARTING_CAPITAL_ZAR = 1000.00   # Your ZAR starting amount (paper or real)

# ── Risk management ─────────────────────────────────────────────────────────
TRADE_AMOUNT_PERCENT = 0.95      # Use 95% of available ZAR per buy
STOP_LOSS_PERCENT    = 0.05      # Hard stop-loss: exit if price drops 5% from entry
TAKE_PROFIT_PERCENT  = 0.08      # Take profit: exit if price rises 8% from entry

# ── EMA strategy settings ───────────────────────────────────────────────────
FAST_EMA_PERIOD = 9              # Sensitive short-term trend line
SLOW_EMA_PERIOD = 21             # Smoother long-term trend line
CANDLE_INTERVAL  = 3600          # Candle size in seconds (3600 = 1 hour)
CANDLE_LIMIT     = 100           # Number of candles to fetch per cycle

# ── Timing ──────────────────────────────────────────────────────────────────
POLL_INTERVAL_SECONDS = 3600     # Run every 1 hour (matches candle interval)
