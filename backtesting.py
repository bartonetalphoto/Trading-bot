from dataclasses import dataclass
from typing import Any

from strategy import STRATEGY_PRESETS, build_strategy, strategy_label, strategy_preset


@dataclass
class BacktestConfig:
    strategy: str = "trend"
    starting_capital: float = 1000.0
    trade_amount_pct: float = 0.95
    stop_loss_pct: float = 0.05
    take_profit_pct: float = 0.08
    max_position_pct: float = 0.95
    fast_ema_period: int = 9
    slow_ema_period: int = 21


def run_backtest(candles: list[dict[str, Any]], config: BacktestConfig) -> dict[str, Any]:
    valid_candles = [c for c in candles if c.get("close") is not None]
    closes = [float(c["close"]) for c in valid_candles]
    strategy = build_strategy(config.strategy, config.fast_ema_period, config.slow_ema_period)
    min_candles = max(config.slow_ema_period + 2, getattr(strategy, "min_candles", 0))
    if len(closes) < min_candles:
        return {
            "ok": False,
            "error": f"Need at least {min_candles} candles",
            "trades": [],
        }

    quote = config.starting_capital
    base = 0.0
    entry_price = None
    trades = []
    equity_curve = []
    peak_value = config.starting_capital
    max_drawdown_pct = 0.0

    for idx in range(min_candles, len(closes) + 1):
        price = closes[idx - 1]
        candle = valid_candles[idx - 1]
        decision = strategy.evaluate(valid_candles[:idx])
        signal = decision.signal
        fast_ema = decision.fast_ema
        slow_ema = decision.slow_ema

        if base > 0 and entry_price:
            change = (price - entry_price) / entry_price
            if change <= -config.stop_loss_pct:
                quote, base, entry_price = _exit_trade(trades, quote, base, entry_price, price, "STOP-LOSS", idx, candle)
                signal = "HOLD"
            elif change >= config.take_profit_pct:
                quote, base, entry_price = _exit_trade(trades, quote, base, entry_price, price, "TAKE-PROFIT", idx, candle)
                signal = "HOLD"

        can_scale_in = getattr(strategy, "allows_scale_in", False) and base > 0
        if signal == "BUY" and quote > 0 and (base == 0 or can_scale_in):
            current_exposure = base * price
            max_position = config.starting_capital * config.max_position_pct
            remaining_position = max(0.0, max_position - current_exposure)
            quote_amount = min(quote * config.trade_amount_pct, remaining_position)
            if quote_amount <= 0:
                signal = "HOLD"
            else:
                base_added = quote_amount / price
                previous_cost = (base * entry_price) if entry_price else 0.0
                base += base_added
                entry_price = (previous_cost + quote_amount) / base if base else None
                trade_type = "DCA-BUY" if can_scale_in else "BUY"
                quote -= quote_amount
                trades.append({
                    "type": trade_type,
                    "price": price,
                    "base_amount": base_added,
                    "quote_amount": quote_amount,
                    "profit": None,
                    "candle": idx,
                    "fast_ema": fast_ema,
                    "slow_ema": slow_ema,
                    "reason": decision.reason,
                    "confidence": decision.confidence,
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
            "signal": signal,
            "reason": decision.reason,
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
        "strategy_label": strategy_label(config.strategy),
        "fast_ema_period": config.fast_ema_period,
        "slow_ema_period": config.slow_ema_period,
        "trade_amount_pct": config.trade_amount_pct,
        "stop_loss_pct": config.stop_loss_pct,
        "take_profit_pct": config.take_profit_pct,
        "max_position_pct": config.max_position_pct,
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
            max_position_pct=base_config.max_position_pct,
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
    preset = strategy_preset(strategy)
    return BacktestConfig(
        strategy=strategy,
        starting_capital=float(payload.get("starting_capital") or payload.get("capital") or 1000.0),
        trade_amount_pct=float(payload.get("trade_amount_pct") or preset["trade_amount_pct"]),
        stop_loss_pct=float(payload.get("stop_loss_pct") or preset["stop_loss_pct"]),
        take_profit_pct=float(payload.get("take_profit_pct") or preset["take_profit_pct"]),
        max_position_pct=float(payload.get("max_position_pct") or preset["max_position_pct"]),
        fast_ema_period=int(payload.get("fast_ema_period") or preset["fast_ema_period"]),
        slow_ema_period=int(payload.get("slow_ema_period") or preset["slow_ema_period"]),
    )


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
