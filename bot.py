import logging
import os
import time
from datetime import datetime, timedelta, timezone

from bot_service import daily_realized_pnl, ensure_default_bot, record_trade
from config import VALR_API_KEY, VALR_API_SECRET
from database import init_db, session_scope, utc_now
from exchanges import ExchangeClient, get_exchange_client
from models import Bot
from strategy import build_strategy


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
        strategy = build_strategy(bot.strategy, bot.fast_ema_period, bot.slow_ema_period)
        min_candles = max(bot.slow_ema_period + 2, getattr(strategy, "min_candles", 0))
        if len(candles) < min_candles:
            bot.signal = "WAIT"
            bot.trend = f"Only {len(candles)} candles available"
            bot.updated_at = utc_now()
            log.info("  [%s] waiting for more candles", bot.name)
            return

        closes = [c["close"] for c in candles]
        current_price = closes[-1]
        decision = strategy.evaluate(candles)
        signal = decision.signal

        bot.last_price = current_price
        bot.fast_ema = decision.fast_ema
        bot.slow_ema = decision.slow_ema
        bot.signal = signal
        bot.trend = f"{decision.trend} | {decision.reason}"[:255]

        if bot.mode == "paper":
            _paper_trade(
                session,
                bot,
                signal,
                current_price,
                allow_scale_in=getattr(strategy, "allows_scale_in", False),
                signal_reason=decision.reason,
            )
        else:
            _live_trade(
                session,
                bot,
                client,
                signal,
                current_price,
                allow_scale_in=getattr(strategy, "allows_scale_in", False),
                signal_reason=decision.reason,
            )

        _update_portfolio(bot, current_price)
        bot.updated_at = utc_now()
        log.info("  [%s] %s @ %.2f | %s", bot.name, bot.signal, current_price, bot.trend)

    except Exception as exc:
        bot.signal = "ERROR"
        bot.trend = str(exc)[:240]
        bot.error = str(exc)
        bot.updated_at = utc_now()
        log.error("  [%s] cycle error: %s", bot.name, exc, exc_info=True)


def _paper_trade(
    session,
    bot: Bot,
    signal: str,
    price: float,
    *,
    allow_scale_in: bool = False,
    signal_reason: str | None = None,
) -> None:
    exit_reason = _exit_reason(bot, price)
    if exit_reason:
        _paper_exit(session, bot, price, exit_reason)
        return

    can_enter = bot.position is None
    can_add = allow_scale_in and bot.position == "long"
    if signal == "BUY" and (can_enter or can_add) and bot.quote_balance >= bot.min_quote_to_trade:
        _paper_enter_or_add(session, bot, price, signal_reason=signal_reason)
        return

    if signal == "SELL" and bot.position == "long":
        _paper_exit(session, bot, price, "SELL")


def _paper_enter_or_add(session, bot: Bot, price: float, signal_reason: str | None = None) -> None:
    current_exposure = bot.base_balance * price
    max_position = bot.starting_capital * bot.max_position_pct
    remaining_position = max(0.0, max_position - current_exposure)
    available = bot.quote_balance * bot.trade_amount_pct
    quote_amount = min(available, remaining_position)
    if quote_amount < bot.min_quote_to_trade:
        bot.signal = "HOLD"
        bot.trend = "Trade amount below minimum or position cap reached"
        return

    is_scale_in = bot.position == "long" and bot.base_balance > 0
    base_amount = quote_amount / price
    previous_cost = bot.base_balance * (bot.entry_price or price)
    new_base_balance = bot.base_balance + base_amount

    bot.quote_balance -= quote_amount
    bot.base_balance = new_base_balance
    bot.position = "long"
    bot.entry_price = (previous_cost + quote_amount) / new_base_balance if new_base_balance else price
    bot.signal = "DCA-BUY" if is_scale_in else "BUY"

    record_trade(
        session,
        bot,
        trade_type="DCA-BUY" if is_scale_in else "BUY",
        side="BUY",
        reason=signal_reason or "SIGNAL",
        price=price,
        base_amount=base_amount,
        quote_amount=quote_amount,
    )


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


def _live_trade(
    session,
    bot: Bot,
    client: ExchangeClient,
    signal: str,
    price: float,
    *,
    allow_scale_in: bool = False,
    signal_reason: str | None = None,
) -> None:
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

    can_enter = bot.position is None
    can_add = allow_scale_in and bot.position == "long"
    if signal == "BUY" and (can_enter or can_add) and bot.quote_balance >= bot.min_quote_to_trade:
        current_exposure = bot.base_balance * price
        max_position = bot.starting_capital * bot.max_position_pct
        remaining_position = max(0.0, max_position - current_exposure)
        quote_amount = min(bot.quote_balance * bot.trade_amount_pct, remaining_position)
        if quote_amount < bot.min_quote_to_trade:
            bot.signal = "HOLD"
            bot.trend = "Trade amount below minimum or position cap reached"
            return
        is_scale_in = bot.position == "long" and bot.base_balance > 0
        base_amount = quote_amount / price
        order = client.place_market_buy(bot.pair, quote_amount)
        record_trade(
            session,
            bot,
            trade_type="LIVE-DCA-BUY" if is_scale_in else "LIVE-BUY",
            side="BUY",
            reason=signal_reason or "SIGNAL",
            price=price,
            base_amount=base_amount,
            quote_amount=quote_amount,
            order=order,
        )
        previous_cost = bot.base_balance * (bot.entry_price or price)
        bot.base_balance += base_amount
        bot.quote_balance -= quote_amount
        bot.position = "long"
        bot.entry_price = (previous_cost + quote_amount) / bot.base_balance if bot.base_balance else price
        bot.signal = "DCA-BUY" if is_scale_in else "BUY"
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
