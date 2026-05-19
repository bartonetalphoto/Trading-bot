"""
Bot Dashboard API
==================
A lightweight FastAPI server that runs alongside bot.py on Railway.
The PWA fetches data from this API every 60 seconds.

Endpoints:
  GET /          → health check
  GET /status    → live bot status, portfolio, current signal
  GET /trades    → full trade history from trades.json
  GET /config    → current bot config (safe fields only)
  POST /pause    → toggle bot pause state
"""

import json
import os
from pathlib import Path
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

app = FastAPI(title="BotTrader API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

TRADE_LOG   = Path("trades.json")
STATUS_FILE = Path("bot_status.json")   # written by bot.py each cycle
CONFIG_FILE = Path("config.py")

# ── Shared pause state ────────────────────────────────────────────────────────
PAUSE_FILE = Path("bot_paused.flag")


def read_trades() -> list:
    if TRADE_LOG.exists():
        try:
            return json.loads(TRADE_LOG.read_text())
        except Exception:
            return []
    return []


def read_status() -> dict:
    if STATUS_FILE.exists():
        try:
            return json.loads(STATUS_FILE.read_text())
        except Exception:
            pass
    return {
        "pair": "BTCZAR",
        "cycle": 0,
        "price": 0,
        "signal": "HOLD",
        "trend": "Unknown",
        "fast_ema": 0,
        "slow_ema": 0,
        "portfolio_value": 1000.0,
        "pnl": 0.0,
        "pnl_pct": 0.0,
        "paper_trading": True,
        "status": "starting",
        "last_updated": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/")
def health():
    return {"ok": True, "service": "BotTrader API", "time": datetime.now(timezone.utc).isoformat()}


@app.get("/status")
def get_status():
    status = read_status()
    trades = read_trades()
    wins   = [t for t in trades if t.get("profit", 0) > 0]
    exits  = [t for t in trades if "profit" in t]
    status["total_trades"] = len(trades)
    status["win_rate"]     = round(len(wins) / len(exits) * 100, 1) if exits else 0
    status["paused"]       = PAUSE_FILE.exists()
    return JSONResponse(status)


@app.get("/trades")
def get_trades():
    trades = read_trades()
    return JSONResponse({"trades": list(reversed(trades)), "count": len(trades)})


@app.get("/config")
def get_config():
    """Return safe (non-secret) config values."""
    try:
        from config import (
            PAIR, PAPER_TRADING, STARTING_CAPITAL_ZAR,
            TRADE_AMOUNT_PERCENT, STOP_LOSS_PERCENT,
            TAKE_PROFIT_PERCENT, FAST_EMA_PERIOD,
            SLOW_EMA_PERIOD, POLL_INTERVAL_SECONDS,
        )
        return {
            "pair":                 PAIR,
            "paper_trading":        PAPER_TRADING,
            "starting_capital":     STARTING_CAPITAL_ZAR,
            "trade_amount_pct":     TRADE_AMOUNT_PERCENT,
            "stop_loss_pct":        STOP_LOSS_PERCENT,
            "take_profit_pct":      TAKE_PROFIT_PERCENT,
            "fast_ema":             FAST_EMA_PERIOD,
            "slow_ema":             SLOW_EMA_PERIOD,
            "poll_interval_secs":   POLL_INTERVAL_SECONDS,
        }
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/pause")
def toggle_pause():
    if PAUSE_FILE.exists():
        PAUSE_FILE.unlink()
        return {"paused": False, "message": "Bot resumed"}
    else:
        PAUSE_FILE.touch()
        return {"paused": True, "message": "Bot paused"}
