"""
BotTrader — Combined Server
=============================
Single entry point that does everything:
  - Serves the PWA app (index.html, manifest, sw.js, icons)
  - Exposes the /status, /trades, /config, /pause API endpoints
  - Runs the trading bot in a background thread

Railway only needs to run: python server.py
"""

import json
import threading
import logging
import time
from pathlib import Path
from datetime import datetime, timezone

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("bot.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("server")

# ── Paths ─────────────────────────────────────────────────────────────────────
BASE_DIR       = Path(__file__).parent
APP_DIR        = BASE_DIR / "app"
TRADE_LOG_FILE = BASE_DIR / "trades.json"
STATUS_FILE    = BASE_DIR / "bot_status.json"
PAUSE_FILE     = BASE_DIR / "bot_paused.flag"

# ── FastAPI app ───────────────────────────────────────────────────────────────
app = FastAPI(title="BotTrader")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── API routes (must be defined BEFORE static mount) ─────────────────────────

@app.get("/status")
def get_status():
    status = _read_json(STATUS_FILE, {
        "pair": "BTCZAR", "cycle": 0, "price": 0,
        "signal": "STARTING", "trend": "Bot starting up...",
        "fast_ema": 0, "slow_ema": 0,
        "portfolio_value": 1000.0, "pnl": 0.0, "pnl_pct": 0.0,
        "paper_trading": True, "status": "starting",
        "last_updated": datetime.now(timezone.utc).isoformat(),
    })
    trades = _read_json(TRADE_LOG_FILE, [])
    wins   = [t for t in trades if t.get("profit", 0) and t["profit"] > 0]
    exits  = [t for t in trades if t.get("profit") is not None]
    status["total_trades"] = len(trades)
    status["win_rate"]     = round(len(wins) / len(exits) * 100, 1) if exits else 0
    status["paused"]       = PAUSE_FILE.exists()
    return JSONResponse(status)


@app.get("/trades")
def get_trades():
    trades = _read_json(TRADE_LOG_FILE, [])
    return JSONResponse({"trades": list(reversed(trades)), "count": len(trades)})


@app.get("/config")
def get_config():
    try:
        from config import (
            PAIR, PAPER_TRADING, STARTING_CAPITAL_ZAR,
            TRADE_AMOUNT_PERCENT, STOP_LOSS_PERCENT,
            TAKE_PROFIT_PERCENT, FAST_EMA_PERIOD,
            SLOW_EMA_PERIOD, POLL_INTERVAL_SECONDS,
        )
        return JSONResponse({
            "pair":               PAIR,
            "paper_trading":      PAPER_TRADING,
            "starting_capital":   STARTING_CAPITAL_ZAR,
            "trade_amount_pct":   TRADE_AMOUNT_PERCENT,
            "stop_loss_pct":      STOP_LOSS_PERCENT,
            "take_profit_pct":    TAKE_PROFIT_PERCENT,
            "fast_ema":           FAST_EMA_PERIOD,
            "slow_ema":           SLOW_EMA_PERIOD,
            "poll_interval_secs": POLL_INTERVAL_SECONDS,
        })
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/pause")
def toggle_pause():
    if PAUSE_FILE.exists():
        PAUSE_FILE.unlink()
        return JSONResponse({"paused": False, "message": "Bot resumed"})
    PAUSE_FILE.touch()
    return JSONResponse({"paused": True, "message": "Bot paused"})


@app.get("/health")
def health():
    return {"ok": True, "time": datetime.now(timezone.utc).isoformat()}


# ── PWA static files ──────────────────────────────────────────────────────────

@app.get("/manifest.json")
def manifest():
    return FileResponse(str(APP_DIR / "manifest.json"), media_type="application/json")

@app.get("/sw.js")
def sw():
    return FileResponse(str(APP_DIR / "sw.js"), media_type="application/javascript")

@app.get("/icon-192.png")
def icon192():
    return FileResponse(str(APP_DIR / "icon-192.png"), media_type="image/png")

@app.get("/icon-512.png")
def icon512():
    return FileResponse(str(APP_DIR / "icon-512.png"), media_type="image/png")

@app.get("/")
def index():
    return FileResponse(str(APP_DIR / "index.html"), media_type="text/html")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _read_json(path: Path, default):
    try:
        if path.exists():
            return json.loads(path.read_text())
    except Exception:
        pass
    return default


# ── Bot thread ────────────────────────────────────────────────────────────────

def run_bot():
    """Run the trading bot in a background thread."""
    log.info("Bot thread starting...")
    try:
        import bot
        bot.main()
    except Exception as e:
        log.error(f"Bot thread crashed: {e}", exc_info=True)


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import os

    port = int(os.environ.get("PORT", 3000))
    log.info(f"Starting BotTrader server on port {port}")

    # Start bot in background thread
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    log.info("Bot thread started")

    # Start web server (blocks here)
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")
