from dataclasses import dataclass
from typing import Any

from strategy import TrendStrategy


@dataclass
class BacktestConfig:
    starting_capital: float = 1000.0
    trade_amount_pct: float = 0.95
    stop_loss_pct: float = 0.05
    take_profit_pct: float = 0.08
    fast_ema_period: int = 9
    slow_ema_period: int = 21


def run_backtest(candles: list[dict[str, Any]], config: BacktestConfig) -> dict[str, Any]:
    closes = [float(c["close"]) for c in candles if c.get("close") is not None]
    if len(closes) < config.slow_ema_period + 2:
        return {
            "ok": False,
            "error": f"Need at least {config.slow_ema_period + 2} candles",
            "trades": [],
        }

    quote = config.starting_capital
    base = 0.0
    entry_price = None
    trades = []
    strategy = TrendStrategy(config.fast_ema_period, config.slow_ema_period)

    for idx in range(config.slow_ema_period + 2, len(closes) + 1):
        price = closes[idx - 1]
        signal, fast_ema, slow_ema = strategy.signal(closes[:idx])

        if base > 0 and entry_price:
            change = (price - entry_price) / entry_price
            if change <= -config.stop_loss_pct:
                quote, base, entry_price = _exit_trade(trades, quote, base, entry_price, price, "STOP-LOSS", idx)
                continue
            if change >= config.take_profit_pct:
                quote, base, entry_price = _exit_trade(trades, quote, base, entry_price, price, "TAKE-PROFIT", idx)
                continue

        if signal == "BUY" and base == 0 and quote > 0:
            quote_amount = quote * config.trade_amount_pct
            base = quote_amount / price
            quote -= quote_amount
            entry_price = price
            trades.append({
                "type": "BUY",
                "price": price,
                "base_amount": base,
                "quote_amount": quote_amount,
                "profit": None,
                "candle": idx,
                "fast_ema": fast_ema,
                "slow_ema": slow_ema,
            })
        elif signal == "SELL" and base > 0:
            quote, base, entry_price = _exit_trade(trades, quote, base, entry_price, price, "SELL", idx)

    final_price = closes[-1]
    final_value = quote + (base * final_price)
    exits = [trade for trade in trades if trade.get("profit") is not None]
    wins = [trade for trade in exits if trade["profit"] > 0]
    losses = [trade for trade in exits if trade["profit"] < 0]
    pnl = final_value - config.starting_capital

    return {
        "ok": True,
        "starting_capital": round(config.starting_capital, 2),
        "final_value": round(final_value, 2),
        "pnl": round(pnl, 2),
        "pnl_pct": round((pnl / config.starting_capital) * 100, 4) if config.starting_capital else 0.0,
        "total_trades": len(trades),
        "exit_trades": len(exits),
        "win_rate": round((len(wins) / len(exits)) * 100, 2) if exits else 0.0,
        "avg_win": round(sum(t["profit"] for t in wins) / len(wins), 2) if wins else 0.0,
        "avg_loss": round(sum(t["profit"] for t in losses) / len(losses), 2) if losses else 0.0,
        "open_position": base > 0,
        "trades": trades,
    }


def _exit_trade(trades, quote, base, entry_price, price, reason, idx):
    quote_amount = base * price
    profit = quote_amount - (base * entry_price)
    quote += quote_amount
    trades.append({
        "type": reason,
        "price": price,
        "base_amount": base,
        "quote_amount": quote_amount,
        "profit": round(profit, 2),
        "candle": idx,
    })
    return quote, 0.0, None
