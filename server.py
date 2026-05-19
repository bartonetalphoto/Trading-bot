import logging
import os
from datetime import datetime, timezone
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
import uvicorn

from backtesting import compare_backtests, config_from_payload, optimize_backtests, run_backtest
from bot_service import (
    bot_to_dict,
    create_bot,
    ensure_default_bot,
    status_with_stats,
    trade_to_dict,
    update_bot,
)
from config import VALR_API_KEY, VALR_API_SECRET
from database import init_db, session_scope, utc_now
from exchanges import get_exchange_client
from models import Bot, Trade


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

BASE_DIR = Path(__file__).parent
APP_DIR = BASE_DIR / "app"

app = FastAPI(title="BotTrader")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup():
    init_db()
    with session_scope() as session:
        ensure_default_bot(session)


@app.get("/bots")
def list_bots(include_stopped: bool = Query(False)):
    with session_scope() as session:
        query = session.query(Bot)
        if not include_stopped:
            query = query.filter(Bot.status != "stopped")
        bots = query.order_by(Bot.created_at.asc()).all()
        return JSONResponse({"bots": [status_with_stats(session, bot) for bot in bots], "count": len(bots)})


@app.post("/bots")
def create_bot_endpoint(payload: dict = Body(...)):
    with session_scope() as session:
        bot = create_bot(session, payload)
        return JSONResponse(status_with_stats(session, bot), status_code=201)


@app.get("/bots/{bot_id}")
def get_bot(bot_id: str):
    with session_scope() as session:
        bot = _get_bot_or_404(session, bot_id)
        return JSONResponse(status_with_stats(session, bot))


@app.patch("/bots/{bot_id}")
def patch_bot(bot_id: str, payload: dict = Body(...)):
    with session_scope() as session:
        bot = _get_bot_or_404(session, bot_id)
        update_bot(session, bot, payload)
        return JSONResponse(status_with_stats(session, bot))


@app.delete("/bots/{bot_id}")
def delete_bot(bot_id: str):
    with session_scope() as session:
        bot = _get_bot_or_404(session, bot_id)
        bot.status = "stopped"
        bot.updated_at = utc_now()
        return JSONResponse({"deleted": True, "bot": bot_to_dict(bot)})


@app.post("/bots/{bot_id}/pause")
def pause_bot(bot_id: str):
    with session_scope() as session:
        bot = _get_bot_or_404(session, bot_id)
        bot.status = "running" if bot.status == "paused" else "paused"
        bot.updated_at = utc_now()
        return JSONResponse({"paused": bot.status == "paused", "bot": bot_to_dict(bot)})


@app.post("/bots/{bot_id}/start")
def start_bot(bot_id: str):
    with session_scope() as session:
        bot = _get_bot_or_404(session, bot_id)
        bot.status = "running"
        bot.updated_at = utc_now()
        return JSONResponse({"started": True, "bot": bot_to_dict(bot)})


@app.post("/bots/{bot_id}/stop")
def stop_bot(bot_id: str):
    with session_scope() as session:
        bot = _get_bot_or_404(session, bot_id)
        bot.status = "stopped"
        bot.updated_at = utc_now()
        return JSONResponse({"stopped": True, "bot": bot_to_dict(bot)})


@app.get("/status")
def get_status():
    with session_scope() as session:
        bot = ensure_default_bot(session)
        return JSONResponse(status_with_stats(session, bot))


@app.get("/trades")
def get_trades(bot_id: str | None = None):
    with session_scope() as session:
        query = session.query(Trade)
        if bot_id:
            query = query.filter(Trade.bot_id == bot_id)
        trades = query.order_by(Trade.created_at.desc()).limit(500).all()
        return JSONResponse({"trades": [trade_to_dict(trade) for trade in trades], "count": len(trades)})


@app.post("/backtest")
def backtest(payload: dict = Body(...)):
    pair = str(payload.get("pair") or "BTCZAR").upper().replace("/", "")
    interval = int(payload.get("candle_interval") or 3600)
    limit = int(payload.get("candle_limit") or 300)
    client = get_exchange_client(str(payload.get("exchange") or "valr"), VALR_API_KEY, VALR_API_SECRET)
    candles = client.get_candles(pair, interval=interval, limit=limit)
    result = run_backtest(candles, config_from_payload(payload))
    result["pair"] = pair
    result["candle_count"] = len(candles)
    return JSONResponse(result)


@app.post("/backtest/compare")
def compare_backtest(payload: dict = Body(...)):
    pair = str(payload.get("pair") or "BTCZAR").upper().replace("/", "")
    interval = int(payload.get("candle_interval") or 3600)
    limit = int(payload.get("candle_limit") or 300)
    client = get_exchange_client(str(payload.get("exchange") or "valr"), VALR_API_KEY, VALR_API_SECRET)
    candles = client.get_candles(pair, interval=interval, limit=limit)
    results = compare_backtests(candles, config_from_payload(payload))
    for result in results:
        result["pair"] = pair
        result["candle_count"] = len(candles)
        result["trades"] = result.get("trades", [])[:20]
        result["equity_curve"] = result.get("equity_curve", [])[-80:]
    return JSONResponse({"pair": pair, "candle_count": len(candles), "results": results})


@app.post("/backtest/optimize")
def optimize_backtest(payload: dict = Body(...)):
    pair = str(payload.get("pair") or "BTCZAR").upper().replace("/", "")
    interval = int(payload.get("candle_interval") or 3600)
    limit = int(payload.get("candle_limit") or 300)
    result_limit = int(payload.get("result_limit") or 8)
    client = get_exchange_client(str(payload.get("exchange") or "valr"), VALR_API_KEY, VALR_API_SECRET)
    candles = client.get_candles(pair, interval=interval, limit=limit)
    results = optimize_backtests(candles, config_from_payload(payload), limit=result_limit)
    return JSONResponse({
        "pair": pair,
        "candle_count": len(candles),
        "train_pct": 70,
        "results": results,
    })


@app.get("/config")
def get_config():
    with session_scope() as session:
        bot = ensure_default_bot(session)
        return JSONResponse({
            "pair": bot.pair,
            "paper_trading": bot.mode == "paper",
            "starting_capital": bot.starting_capital,
            "trade_amount_pct": bot.trade_amount_pct,
            "stop_loss_pct": bot.stop_loss_pct,
            "take_profit_pct": bot.take_profit_pct,
            "fast_ema": bot.fast_ema_period,
            "slow_ema": bot.slow_ema_period,
            "poll_interval_secs": bot.poll_interval_seconds,
        })


@app.post("/pause")
def toggle_pause():
    with session_scope() as session:
        bot = ensure_default_bot(session)
        bot.status = "running" if bot.status == "paused" else "paused"
        bot.updated_at = utc_now()
        return JSONResponse({"paused": bot.status == "paused", "message": "Bot paused" if bot.status == "paused" else "Bot resumed"})


@app.get("/health")
def health():
    return {"ok": True, "time": datetime.now(timezone.utc).isoformat()}


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


@app.get("/index.html")
def index_html():
    return FileResponse(str(APP_DIR / "index.html"), media_type="text/html")


def run_bot():
    log.info("Bot runner thread starting...")
    try:
        import bot

        bot.main()
    except Exception as exc:
        log.error("Bot runner crashed: %s", exc, exc_info=True)


def _get_bot_or_404(session, bot_id: str) -> Bot:
    bot = session.get(Bot, bot_id)
    if not bot:
        raise HTTPException(status_code=404, detail="Bot not found")
    return bot


if __name__ == "__main__":
    import threading

    port = int(os.environ.get("PORT", 3000))
    log.info("Starting BotTrader server on port %s", port)

    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    log.info("Bot runner thread started")

    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")
