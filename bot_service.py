import json
from datetime import datetime, time, timezone
from typing import Any
from uuid import uuid4

from sqlalchemy import func

from config import (
    CANDLE_INTERVAL,
    CANDLE_LIMIT,
    FAST_EMA_PERIOD,
    PAIR,
    PAPER_TRADING,
    POLL_INTERVAL_SECONDS,
    SLOW_EMA_PERIOD,
    STARTING_CAPITAL_ZAR,
    STOP_LOSS_PERCENT,
    TAKE_PROFIT_PERCENT,
    TRADE_AMOUNT_PERCENT,
)
from database import utc_now
from models import Bot, Trade


QUOTE_SUFFIXES = ("USDT", "USDC", "ZAR", "USD", "EUR", "GBP", "BTC", "ETH")


def pair_currencies(pair: str) -> tuple[str, str]:
    upper = pair.upper()
    for quote in QUOTE_SUFFIXES:
        if upper.endswith(quote) and len(upper) > len(quote):
            return upper[: -len(quote)], quote
    return upper[:3] or "BASE", upper[3:] or "QUOTE"


def normalize_mode(mode: str | None) -> str:
    return "live" if str(mode).lower() == "live" else "paper"


def default_bot_payload() -> dict[str, Any]:
    base, quote = pair_currencies(PAIR)
    return {
        "id": "main",
        "name": f"{base} Trend Bot",
        "exchange": "valr",
        "pair": PAIR,
        "strategy": "trend",
        "mode": "paper" if PAPER_TRADING else "live",
        "status": "running",
        "base_currency": base,
        "quote_currency": quote,
        "starting_capital": STARTING_CAPITAL_ZAR,
        "quote_balance": STARTING_CAPITAL_ZAR,
        "base_balance": 0.0,
        "trade_amount_pct": TRADE_AMOUNT_PERCENT,
        "stop_loss_pct": STOP_LOSS_PERCENT,
        "take_profit_pct": TAKE_PROFIT_PERCENT,
        "max_position_pct": TRADE_AMOUNT_PERCENT,
        "max_daily_loss_pct": 0.05,
        "min_quote_to_trade": 50.0,
        "fast_ema_period": FAST_EMA_PERIOD,
        "slow_ema_period": SLOW_EMA_PERIOD,
        "candle_interval": CANDLE_INTERVAL,
        "candle_limit": CANDLE_LIMIT,
        "poll_interval_seconds": POLL_INTERVAL_SECONDS,
        "portfolio_value": STARTING_CAPITAL_ZAR,
    }


def ensure_default_bot(session) -> Bot:
    bot = session.query(Bot).order_by(Bot.created_at.asc()).first()
    if bot:
        return bot
    bot = Bot(**default_bot_payload())
    session.add(bot)
    session.flush()
    return bot


def create_bot(session, payload: dict[str, Any]) -> Bot:
    pair = str(payload.get("pair") or PAIR).upper().replace("/", "")
    base, quote = pair_currencies(pair)
    starting_capital = float(payload.get("starting_capital") or payload.get("capital") or STARTING_CAPITAL_ZAR)

    bot = Bot(
        id=str(payload.get("id") or uuid4()),
        name=str(payload.get("name") or f"{pair} Bot")[:120],
        exchange=str(payload.get("exchange") or "valr").lower(),
        pair=pair,
        strategy=str(payload.get("strategy") or "trend").lower(),
        mode=normalize_mode(payload.get("mode")),
        status=str(payload.get("status") or "running").lower(),
        base_currency=str(payload.get("base_currency") or base).upper(),
        quote_currency=str(payload.get("quote_currency") or quote).upper(),
        starting_capital=starting_capital,
        quote_balance=float(payload.get("quote_balance") or starting_capital),
        base_balance=float(payload.get("base_balance") or 0.0),
        trade_amount_pct=float(payload.get("trade_amount_pct") or TRADE_AMOUNT_PERCENT),
        stop_loss_pct=float(payload.get("stop_loss_pct") or payload.get("stoploss", STOP_LOSS_PERCENT)),
        take_profit_pct=float(payload.get("take_profit_pct") or TAKE_PROFIT_PERCENT),
        max_position_pct=float(payload.get("max_position_pct") or payload.get("trade_amount_pct") or TRADE_AMOUNT_PERCENT),
        max_daily_loss_pct=float(payload.get("max_daily_loss_pct") or 0.05),
        min_quote_to_trade=float(payload.get("min_quote_to_trade") or 50.0),
        fast_ema_period=int(payload.get("fast_ema_period") or FAST_EMA_PERIOD),
        slow_ema_period=int(payload.get("slow_ema_period") or SLOW_EMA_PERIOD),
        candle_interval=int(payload.get("candle_interval") or CANDLE_INTERVAL),
        candle_limit=int(payload.get("candle_limit") or CANDLE_LIMIT),
        poll_interval_seconds=int(payload.get("poll_interval_seconds") or POLL_INTERVAL_SECONDS),
        portfolio_value=starting_capital,
    )
    session.add(bot)
    session.flush()
    return bot


def update_bot(session, bot: Bot, payload: dict[str, Any]) -> Bot:
    editable = {
        "name",
        "exchange",
        "pair",
        "strategy",
        "mode",
        "status",
        "trade_amount_pct",
        "stop_loss_pct",
        "take_profit_pct",
        "max_position_pct",
        "max_daily_loss_pct",
        "min_quote_to_trade",
        "fast_ema_period",
        "slow_ema_period",
        "candle_interval",
        "candle_limit",
        "poll_interval_seconds",
    }
    for key in editable:
        if key in payload:
            value = payload[key]
            if key in {"exchange", "pair", "strategy", "mode", "status"}:
                value = str(value).lower() if key != "pair" else str(value).upper().replace("/", "")
            setattr(bot, key, value)
    if "pair" in payload:
        bot.base_currency, bot.quote_currency = pair_currencies(bot.pair)
    bot.updated_at = utc_now()
    session.flush()
    return bot


def record_trade(
    session,
    bot: Bot,
    *,
    trade_type: str,
    side: str,
    reason: str | None,
    price: float,
    base_amount: float,
    quote_amount: float,
    profit: float | None = None,
    order: dict[str, Any] | None = None,
) -> Trade:
    order_id = None
    if order:
        order_id = str(order.get("id") or order.get("orderId") or order.get("order_id") or "") or None
    trade = Trade(
        id=str(uuid4()),
        bot_id=bot.id,
        exchange=bot.exchange,
        pair=bot.pair,
        mode=bot.mode,
        type=trade_type,
        side=side,
        reason=reason,
        price=float(price),
        base_amount=float(base_amount),
        quote_amount=float(quote_amount),
        profit=round(profit, 2) if profit is not None else None,
        cycle=bot.cycle,
        order_id=order_id,
        raw_order=json.dumps(order) if order else None,
    )
    session.add(trade)
    return trade


def daily_realized_pnl(session, bot: Bot) -> float:
    start = datetime.combine(utc_now().date(), time.min, tzinfo=timezone.utc)
    total = (
        session.query(func.coalesce(func.sum(Trade.profit), 0.0))
        .filter(Trade.bot_id == bot.id, Trade.created_at >= start)
        .scalar()
    )
    return float(total or 0.0)


def bot_to_dict(bot: Bot) -> dict[str, Any]:
    paused = bot.status == "paused"
    return {
        "id": bot.id,
        "name": bot.name,
        "exchange": bot.exchange,
        "pair": bot.pair,
        "strategy": bot.strategy,
        "mode": bot.mode,
        "status": bot.status,
        "paused": paused,
        "paper_trading": bot.mode == "paper",
        "isMain": bot.id == "main",
        "base_currency": bot.base_currency,
        "quote_currency": bot.quote_currency,
        "starting_capital": bot.starting_capital,
        "capital": bot.starting_capital,
        "quote_balance": bot.quote_balance,
        "base_balance": bot.base_balance,
        "position": bot.position,
        "entry_price": bot.entry_price,
        "trade_amount_pct": bot.trade_amount_pct,
        "stop_loss_pct": bot.stop_loss_pct,
        "take_profit_pct": bot.take_profit_pct,
        "max_position_pct": bot.max_position_pct,
        "max_daily_loss_pct": bot.max_daily_loss_pct,
        "min_quote_to_trade": bot.min_quote_to_trade,
        "fast_ema": bot.fast_ema,
        "slow_ema": bot.slow_ema,
        "fast_ema_period": bot.fast_ema_period,
        "slow_ema_period": bot.slow_ema_period,
        "candle_interval": bot.candle_interval,
        "candle_limit": bot.candle_limit,
        "poll_interval_seconds": bot.poll_interval_seconds,
        "cycle": bot.cycle,
        "price": bot.last_price,
        "signal": bot.signal,
        "trend": bot.trend,
        "portfolio_value": round(bot.portfolio_value, 2),
        "pnl": round(bot.pnl, 2),
        "pnl_pct": round(bot.pnl_pct, 4),
        "error": bot.error,
        "last_updated": (bot.last_cycle_at or bot.updated_at).isoformat(),
        "created_at": bot.created_at.isoformat(),
    }


def trade_to_dict(trade: Trade) -> dict[str, Any]:
    return {
        "id": trade.id,
        "bot_id": trade.bot_id,
        "exchange": trade.exchange,
        "pair": trade.pair,
        "mode": trade.mode,
        "type": trade.type,
        "side": trade.side,
        "reason": trade.reason,
        "price": trade.price,
        "base_amount": trade.base_amount,
        "quote_amount": trade.quote_amount,
        "profit": trade.profit,
        "cycle": trade.cycle,
        "order_id": trade.order_id,
        "time": trade.created_at.isoformat(),
    }


def status_with_stats(session, bot: Bot) -> dict[str, Any]:
    status = bot_to_dict(bot)
    exits = session.query(Trade).filter(Trade.bot_id == bot.id, Trade.profit.isnot(None)).all()
    wins = [trade for trade in exits if trade.profit and trade.profit > 0]
    status["total_trades"] = session.query(Trade).filter(Trade.bot_id == bot.id).count()
    status["win_rate"] = round(len(wins) / len(exits) * 100, 1) if exits else 0
    return status
