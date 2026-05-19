import logging
import os
import time
from datetime import datetime, timedelta, timezone

from bot_service import daily_realized_pnl, ensure_default_bot, record_trade
from config import VALR_API_KEY, VALR_API_SECRET
from database import init_db, session_scope, utc_now
from exchanges import ExchangeClient, get_exchange_client
from models import Bot
from strategy import TrendStrategy


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("bot.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("bottrader")

RUNNER_SLEEP_SECONDS = int(os.getenv("RUNNER_SLEEP_SECONDS", "30"))
LIVE_TRADING_ENABLED = os.getenv("LIVE_TRADING_ENABLED", "false").lower() in {"1", "true", "yes", "on"}


def main():
    log.info("=" * 65)
    log.info("  BotTrader runner starting")
    log.info("  Live trading enabled: %s", LIVE_TRADING_ENABLED)
    log.info("=" * 65)

    init_db()
    with session_scope() as session:
        ensure_default_bot(session)

    while True:
        try:
            run_due_bots()
        except KeyboardInterrupt:
            log.info("Runner stopped.")
            break
        except Exception as exc:
            log.error("Runner error: %s", exc, exc_info=True)
        time.sleep(RUNNER_SLEEP_SECONDS)


def run_due_bots() -> None:
    now = utc_now()
    with session_scope() as session:
        ensure_default_bot(session)
        bots = session.query(Bot).filter(Bot.status == "running").order_by(Bot.created_at.asc()).all()
        for bot in bots:
            if not _is_due(bot, now):
                continue
            run_bot_cycle(session, bot)


def run_bot_cycle(session, bot: Bot) -> None:
    bot.cycle += 1
    bot.last_cycle_at = utc_now()
    bot.next_run_at = bot.last_cycle_at + timedelta(seconds=bot.poll_interval_seconds)
    bot.error = None

    log.info("-- %s cycle %s [%s]", bot.name, bot.cycle, bot.pair)

    try:
        if _daily_loss_limit_hit(session, bot):
            bot.status = "paused"
            bot.signal = "RISK_PAUSE"
            bot.trend = "Daily loss limit reached"
            bot.updated_at = utc_now()
            log.warning("  [%s] paused: daily loss limit reached", bot.name)
            return

        client = get_exchange_client(bot.exchange, VALR_API_KEY, VALR_API_SECRET)
        candles = client.get_candles(bot.pair, interval=bot.candle_interval, limit=bot.candle_limit)
        if len(candles) < bot.slow_ema_period + 2:
            bot.signal = "WAIT"
            bot.trend = f"Only {len(candles)} candles available"
            bot.updated_at = utc_now()
            log.info("  [%s] waiting for more candles", bot.name)
            return

        closes = [c["close"] for c in candles]
        current_price = closes[-1]
        strategy = TrendStrategy(bot.fast_ema_period, bot.slow_ema_period)
        signal, fast_ema, slow_ema = strategy.signal(closes)
        trend = strategy.trend_strength(closes)

        bot.last_price = current_price
        bot.fast_ema = fast_ema
        bot.slow_ema = slow_ema
        bot.signal = signal
        bot.trend = trend

        if bot.mode == "paper":
            _paper_trade(session, bot, signal, current_price)
        else:
            _live_trade(session, bot, client, signal, current_price)

        _update_portfolio(bot, current_price)
        bot.updated_at = utc_now()
        log.info("  [%s] %s @ %.2f | %s", bot.name, bot.signal, current_price, bot.trend)

    except Exception as exc:
        bot.signal = "ERROR"
        bot.trend = str(exc)[:240]
        bot.error = str(exc)
        bot.updated_at = utc_now()
        log.error("  [%s] cycle error: %s", bot.name, exc, exc_info=True)


def _paper_trade(session, bot: Bot, signal: str, price: float) -> None:
    exit_reason = _exit_reason(bot, price)
    if exit_reason:
        _paper_exit(session, bot, price, exit_reason)
        return

    if signal == "BUY" and bot.position is None and bot.quote_balance >= bot.min_quote_to_trade:
        available = bot.quote_balance * bot.trade_amount_pct
        max_position = bot.starting_capital * bot.max_position_pct
        quote_amount = min(available, max_position)
        if quote_amount < bot.min_quote_to_trade:
            bot.signal = "HOLD"
            bot.trend = "Trade amount below minimum"
            return
        base_amount = quote_amount / price
        bot.quote_balance -= quote_amount
        bot.base_balance += base_amount
        bot.position = "long"
        bot.entry_price = price
        record_trade(
            session,
            bot,
            trade_type="BUY",
            side="BUY",
            reason="SIGNAL",
            price=price,
            base_amount=base_amount,
            quote_amount=quote_amount,
        )
        return

    if signal == "SELL" and bot.position == "long":
        _paper_exit(session, bot, price, "SELL")


def _paper_exit(session, bot: Bot, price: float, reason: str) -> None:
    base_amount = bot.base_balance
    if base_amount <= 0:
        return
    entry_price = bot.entry_price or price
    quote_amount = base_amount * price
    profit = quote_amount - (base_amount * entry_price)

    bot.quote_balance += quote_amount
    bot.base_balance = 0.0
    bot.position = None
    bot.entry_price = None
    bot.signal = reason

    record_trade(
        session,
        bot,
        trade_type=reason,
        side="SELL",
        reason=reason,
        price=price,
        base_amount=base_amount,
        quote_amount=quote_amount,
        profit=profit,
    )


def _live_trade(session, bot: Bot, client: ExchangeClient, signal: str, price: float) -> None:
    if not LIVE_TRADING_ENABLED:
        bot.signal = "LIVE_DISABLED"
        bot.trend = "Set LIVE_TRADING_ENABLED=true before real orders are allowed"
        return

    balances = client.get_balances()
    bot.quote_balance = balances.get(bot.quote_currency, 0.0)
    bot.base_balance = balances.get(bot.base_currency, 0.0)
    bot.position = "long" if bot.base_balance > 0 else None

    exit_reason = _exit_reason(bot, price)
    if exit_reason and bot.base_balance > 0:
        order = client.place_market_sell(bot.pair, bot.base_balance)
        record_trade(
            session,
            bot,
            trade_type=f"LIVE-{exit_reason}",
            side="SELL",
            reason=exit_reason,
            price=price,
            base_amount=bot.base_balance,
            quote_amount=bot.base_balance * price,
            order=order,
        )
        bot.base_balance = 0.0
        bot.position = None
        bot.entry_price = None
        bot.signal = exit_reason
        return

    if signal == "BUY" and bot.position is None and bot.quote_balance >= bot.min_quote_to_trade:
        quote_amount = min(bot.quote_balance * bot.trade_amount_pct, bot.starting_capital * bot.max_position_pct)
        order = client.place_market_buy(bot.pair, quote_amount)
        record_trade(
            session,
            bot,
            trade_type="LIVE-BUY",
            side="BUY",
            reason="SIGNAL",
            price=price,
            base_amount=quote_amount / price,
            quote_amount=quote_amount,
            order=order,
        )
        bot.position = "long"
        bot.entry_price = price
        return

    if signal == "SELL" and bot.base_balance > 0:
        order = client.place_market_sell(bot.pair, bot.base_balance)
        record_trade(
            session,
            bot,
            trade_type="LIVE-SELL",
            side="SELL",
            reason="SIGNAL",
            price=price,
            base_amount=bot.base_balance,
            quote_amount=bot.base_balance * price,
            order=order,
        )
        bot.base_balance = 0.0
        bot.position = None
        bot.entry_price = None


def _exit_reason(bot: Bot, price: float) -> str | None:
    if bot.position != "long" or not bot.entry_price:
        return None
    change = (price - bot.entry_price) / bot.entry_price
    if change <= -bot.stop_loss_pct:
        return "STOP-LOSS"
    if change >= bot.take_profit_pct:
        return "TAKE-PROFIT"
    return None


def _daily_loss_limit_hit(session, bot: Bot) -> bool:
    if bot.max_daily_loss_pct <= 0:
        return False
    max_loss = bot.starting_capital * bot.max_daily_loss_pct
    return daily_realized_pnl(session, bot) <= -max_loss


def _update_portfolio(bot: Bot, price: float) -> None:
    value = bot.quote_balance + (bot.base_balance * price)
    bot.portfolio_value = round(value, 2)
    bot.pnl = round(value - bot.starting_capital, 2)
    bot.pnl_pct = round((bot.pnl / bot.starting_capital) * 100, 4) if bot.starting_capital else 0.0


def _is_due(bot: Bot, now: datetime) -> bool:
    if bot.next_run_at is None:
        return True
    next_run = bot.next_run_at
    if next_run.tzinfo is None:
        next_run = next_run.replace(tzinfo=timezone.utc)
    return next_run <= now


if __name__ == "__main__":
    main()
