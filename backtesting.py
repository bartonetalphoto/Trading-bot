from dataclasses import dataclass
from typing import Any

from strategy import TrendStrategy


@dataclass
class BacktestConfig:
    strategy: str = "trend"
    starting_capital: float = 1000.0
    trade_amount_pct: float = 0.95
    stop_loss_pct: float = 0.05
    take_profit_pct: float = 0.08
    fast_ema_period: int = 9
    slow_ema_period: int = 21


STRATEGY_PRESETS = {
    "trend": {
        "label": "Trend follow",
        "fast_ema_period": 9,
        "slow_ema_period": 21,
        "trade_amount_pct": 0.95,
        "stop_loss_pct": 0.05,
        "take_profit_pct": 0.08,
    },
    "scalp": {
        "label": "Scalping",
        "fast_ema_period": 5,
        "slow_ema_period": 13,
        "trade_amount_pct": 0.65,
        "stop_loss_pct": 0.025,
        "take_profit_pct": 0.04,
    },
    "grid": {
        "label": "Grid range",
        "fast_ema_period": 7,
        "slow_ema_period": 21,
        "trade_amount_pct": 0.5,
        "stop_loss_pct": 0.04,
        "take_profit_pct": 0.045,
    },
    "dca": {
        "label": "DCA dip",
        "fast_ema_period": 9,
        "slow_ema_period": 30,
        "trade_amount_pct": 0.35,
        "stop_loss_pct": 0.08,
        "take_profit_pct": 0.1,
    },
}


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
    equity_curve = []
    peak_value = config.starting_capital
    max_drawdown_pct = 0.0

    for idx in range(config.slow_ema_period + 2, len(closes) + 1):
        price = closes[idx - 1]
        candle = candles[idx - 1]
        signal, fast_ema, slow_ema = _signal_for_strategy(config.strategy, closes[:idx], strategy)

        if base > 0 and entry_price:
            change = (price - entry_price) / entry_price
            if change <= -config.stop_loss_pct:
                quote, base, entry_price = _exit_trade(trades, quote, base, entry_price, price, "STOP-LOSS", idx, candle)
                continue
            if change >= config.take_profit_pct:
                quote, base, entry_price = _exit_trade(trades, quote, base, entry_price, price, "TAKE-PROFIT", idx, candle)
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
                "timestamp": candle.get("timestamp"),
            })
        elif signal == "SELL" and base > 0:
            quote, base, entry_price = _exit_trade(trades, quote, base, entry_price, price, "SELL", idx, candle)

        value = quote + (base * price)
        peak_value = max(peak_value, value)
        drawdown_pct = ((peak_value - value) / peak_value) * 100 if peak_value else 0.0
        max_drawdown_pct = max(max_drawdown_pct, drawdown_pct)
        equity_curve.append({
            "candle": idx,
            "value": round(value, 2),
            "price": price,
            "timestamp": candle.get("timestamp"),
        })

    final_price = closes[-1]
    final_value = quote + (base * final_price)
    exits = [trade for trade in trades if trade.get("profit") is not None]
    wins = [trade for trade in exits if trade["profit"] > 0]
    losses = [trade for trade in exits if trade["profit"] < 0]
    pnl = final_value - config.starting_capital

    return {
        "ok": True,
        "strategy": config.strategy,
        "strategy_label": STRATEGY_PRESETS.get(config.strategy, {}).get("label", config.strategy.title()),
        "fast_ema_period": config.fast_ema_period,
        "slow_ema_period": config.slow_ema_period,
        "trade_amount_pct": config.trade_amount_pct,
        "stop_loss_pct": config.stop_loss_pct,
        "take_profit_pct": config.take_profit_pct,
        "starting_capital": round(config.starting_capital, 2),
        "final_value": round(final_value, 2),
        "pnl": round(pnl, 2),
        "pnl_pct": round((pnl / config.starting_capital) * 100, 4) if config.starting_capital else 0.0,
        "max_drawdown_pct": round(max_drawdown_pct, 2),
        "total_trades": len(trades),
        "exit_trades": len(exits),
        "win_rate": round((len(wins) / len(exits)) * 100, 2) if exits else 0.0,
        "avg_win": round(sum(t["profit"] for t in wins) / len(wins), 2) if wins else 0.0,
        "avg_loss": round(sum(t["profit"] for t in losses) / len(losses), 2) if losses else 0.0,
        "open_position": base > 0,
        "equity_curve": equity_curve,
        "trades": trades,
    }


def compare_backtests(candles: list[dict[str, Any]], base_config: BacktestConfig) -> list[dict[str, Any]]:
    results = []
    for strategy_name, preset in STRATEGY_PRESETS.items():
        config = BacktestConfig(
            strategy=strategy_name,
            starting_capital=base_config.starting_capital,
            trade_amount_pct=base_config.trade_amount_pct,
            stop_loss_pct=base_config.stop_loss_pct,
            take_profit_pct=base_config.take_profit_pct,
            fast_ema_period=preset["fast_ema_period"],
            slow_ema_period=preset["slow_ema_period"],
        )
        result = run_backtest(candles, config)
        result["strategy"] = strategy_name
        result["strategy_label"] = preset["label"]
        results.append(result)
    return sorted(results, key=lambda item: item.get("pnl_pct", -999), reverse=True)


def config_from_payload(payload: dict[str, Any]) -> BacktestConfig:
    strategy = str(payload.get("strategy") or "trend").lower()
    preset = STRATEGY_PRESETS.get(strategy, STRATEGY_PRESETS["trend"])
    return BacktestConfig(
        strategy=strategy,
        starting_capital=float(payload.get("starting_capital") or payload.get("capital") or 1000.0),
        trade_amount_pct=float(payload.get("trade_amount_pct") or preset["trade_amount_pct"]),
        stop_loss_pct=float(payload.get("stop_loss_pct") or preset["stop_loss_pct"]),
        take_profit_pct=float(payload.get("take_profit_pct") or preset["take_profit_pct"]),
        fast_ema_period=int(payload.get("fast_ema_period") or preset["fast_ema_period"]),
        slow_ema_period=int(payload.get("slow_ema_period") or preset["slow_ema_period"]),
    )


def _signal_for_strategy(strategy_name: str, closes: list[float], strategy: TrendStrategy) -> tuple[str, float, float]:
    if strategy_name in {"trend", "scalp"}:
        return strategy.signal(closes)

    fast = _ema_value(closes, strategy.fast_period)
    slow = _ema_value(closes, strategy.slow_period)
    current = closes[-1]

    if strategy_name == "grid":
        window = closes[-24:] if len(closes) >= 24 else closes
        low = min(window)
        high = max(window)
        spread = high - low or 1
        lower_band = low + (spread * 0.25)
        upper_band = low + (spread * 0.75)
        if current <= lower_band:
            return "BUY", round(fast, 2), round(slow, 2)
        if current >= upper_band:
            return "SELL", round(fast, 2), round(slow, 2)
        return "HOLD", round(fast, 2), round(slow, 2)

    if strategy_name == "dca":
        window = closes[-30:] if len(closes) >= 30 else closes
        avg = sum(window) / len(window)
        if current <= avg * 0.975:
            return "BUY", round(fast, 2), round(slow, 2)
        if current >= avg * 1.04:
            return "SELL", round(fast, 2), round(slow, 2)
        return "HOLD", round(fast, 2), round(slow, 2)

    return strategy.signal(closes)


def _ema_value(closes: list[float], period: int) -> float:
    if len(closes) < period:
        return closes[-1]
    k = 2 / (period + 1)
    ema = sum(closes[:period]) / period
    for price in closes[period:]:
        ema = price * k + ema * (1 - k)
    return ema


def _exit_trade(trades, quote, base, entry_price, price, reason, idx, candle):
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
        "timestamp": candle.get("timestamp"),
    })
    return quote, 0.0, None
