from dataclasses import dataclass
from datetime import datetime, timezone
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
    fee_pct: float = 0.001
    slippage_pct: float = 0.0005
    fast_ema_period: int = 9
    slow_ema_period: int = 21


def run_backtest(candles: list[dict[str, Any]], config: BacktestConfig) -> dict[str, Any]:
    valid_candles = _sorted_valid_candles(candles)
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
    fees_paid = 0.0

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
                quote, base, entry_price, fee = _exit_trade(
                    trades, quote, base, entry_price, price, "STOP-LOSS", idx, candle, config
                )
                fees_paid += fee
                signal = "HOLD"
            elif change >= config.take_profit_pct:
                quote, base, entry_price, fee = _exit_trade(
                    trades, quote, base, entry_price, price, "TAKE-PROFIT", idx, candle, config
                )
                fees_paid += fee
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
                execution_price = price * (1 + config.slippage_pct)
                fee = quote_amount * config.fee_pct
                net_quote = max(0.0, quote_amount - fee)
                base_added = net_quote / execution_price
                previous_cost = (base * entry_price) if entry_price else 0.0
                base += base_added
                entry_price = (previous_cost + quote_amount) / base if base else None
                trade_type = "DCA-BUY" if can_scale_in else "BUY"
                quote -= quote_amount
                fees_paid += fee
                trades.append({
                    "type": trade_type,
                    "price": execution_price,
                    "market_price": price,
                    "base_amount": base_added,
                    "quote_amount": quote_amount,
                    "fee": round(fee, 2),
                    "profit": None,
                    "candle": idx,
                    "fast_ema": fast_ema,
                    "slow_ema": slow_ema,
                    "reason": decision.reason,
                    "confidence": decision.confidence,
                    "timestamp": candle.get("timestamp"),
                })
        elif signal == "SELL" and base > 0:
            quote, base, entry_price, fee = _exit_trade(trades, quote, base, entry_price, price, "SELL", idx, candle, config)
            fees_paid += fee

        value = _portfolio_value(quote, base, price, config)
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
    final_value = _portfolio_value(quote, base, final_price, config)
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
        "fee_pct": config.fee_pct,
        "slippage_pct": config.slippage_pct,
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
        "fees_paid": round(fees_paid, 2),
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
            fee_pct=base_config.fee_pct,
            slippage_pct=base_config.slippage_pct,
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
        starting_capital=_payload_float(payload, "starting_capital", _payload_float(payload, "capital", 1000.0)),
        trade_amount_pct=_payload_float(payload, "trade_amount_pct", preset["trade_amount_pct"]),
        stop_loss_pct=_payload_float(payload, "stop_loss_pct", preset["stop_loss_pct"]),
        take_profit_pct=_payload_float(payload, "take_profit_pct", preset["take_profit_pct"]),
        max_position_pct=_payload_float(payload, "max_position_pct", preset["max_position_pct"]),
        fee_pct=_payload_float(payload, "fee_pct", 0.001),
        slippage_pct=_payload_float(payload, "slippage_pct", 0.0005),
        fast_ema_period=int(payload.get("fast_ema_period") or preset["fast_ema_period"]),
        slow_ema_period=int(payload.get("slow_ema_period") or preset["slow_ema_period"]),
    )


def optimize_backtests(candles: list[dict[str, Any]], base_config: BacktestConfig, limit: int = 10) -> list[dict[str, Any]]:
    valid_candles = _sorted_valid_candles(candles)
    if len(valid_candles) < 80:
        return []

    split_idx = max(50, int(len(valid_candles) * 0.7))
    train_candles = valid_candles[:split_idx]
    validation_candles = valid_candles[split_idx:]
    if len(validation_candles) < 30:
        validation_candles = valid_candles[-30:]
        train_candles = valid_candles[:-30]

    candidates = []
    for config in _candidate_configs(base_config):
        train = run_backtest(train_candles, config)
        validation = run_backtest(validation_candles, config)
        if not train.get("ok") or not validation.get("ok"):
            continue
        stability_penalty = abs(train.get("pnl_pct", 0.0) - validation.get("pnl_pct", 0.0)) * 0.08
        score = (
            validation.get("pnl_pct", 0.0)
            - validation.get("max_drawdown_pct", 0.0) * 0.55
            + min(validation.get("win_rate", 0.0), 80.0) * 0.01
            - stability_penalty
        )
        candidates.append({
            "strategy": config.strategy,
            "strategy_label": strategy_label(config.strategy),
            "score": round(score, 4),
            "fast_ema_period": config.fast_ema_period,
            "slow_ema_period": config.slow_ema_period,
            "trade_amount_pct": config.trade_amount_pct,
            "stop_loss_pct": config.stop_loss_pct,
            "take_profit_pct": config.take_profit_pct,
            "max_position_pct": config.max_position_pct,
            "fee_pct": config.fee_pct,
            "slippage_pct": config.slippage_pct,
            "train": _trim_result(train, trades_limit=8, equity_limit=30),
            "validation": _trim_result(validation, trades_limit=12, equity_limit=50),
        })

    return sorted(candidates, key=lambda item: item["score"], reverse=True)[:limit]


def _candidate_configs(base_config: BacktestConfig) -> list[BacktestConfig]:
    configs = []
    seen = set()
    for strategy_name, preset in STRATEGY_PRESETS.items():
        fast_values = _int_options(preset["fast_ema_period"], [preset["fast_ema_period"] - 2, preset["fast_ema_period"]])
        slow_values = _int_options(preset["slow_ema_period"], [preset["slow_ema_period"], preset["slow_ema_period"] + 5])
        trade_values = _float_options(preset["trade_amount_pct"], [base_config.trade_amount_pct], 0.15, 0.95)
        stop_values = _float_options(preset["stop_loss_pct"], [base_config.stop_loss_pct, preset["stop_loss_pct"] * 0.75], 0.015, 0.15)
        take_values = _float_options(preset["take_profit_pct"], [base_config.take_profit_pct, preset["take_profit_pct"] * 1.25], 0.025, 0.25)
        max_position_values = _float_options(preset["max_position_pct"], [base_config.max_position_pct], 0.2, 0.98)

        for fast in fast_values:
            for slow in slow_values:
                if fast >= slow:
                    continue
                for trade_amount in trade_values:
                    for stop_loss in stop_values:
                        for take_profit in take_values:
                            for max_position in max_position_values:
                                key = (strategy_name, fast, slow, trade_amount, stop_loss, take_profit, max_position)
                                if key in seen:
                                    continue
                                seen.add(key)
                                configs.append(BacktestConfig(
                                    strategy=strategy_name,
                                    starting_capital=base_config.starting_capital,
                                    trade_amount_pct=trade_amount,
                                    stop_loss_pct=stop_loss,
                                    take_profit_pct=take_profit,
                                    max_position_pct=max_position,
                                    fee_pct=base_config.fee_pct,
                                    slippage_pct=base_config.slippage_pct,
                                    fast_ema_period=fast,
                                    slow_ema_period=slow,
                                ))
    return configs


def _exit_trade(trades, quote, base, entry_price, price, reason, idx, candle, config: BacktestConfig):
    execution_price = price * (1 - config.slippage_pct)
    gross_quote = base * execution_price
    fee = gross_quote * config.fee_pct
    quote_amount = gross_quote - fee
    profit = quote_amount - (base * entry_price)
    quote += quote_amount
    trades.append({
        "type": reason,
        "price": execution_price,
        "market_price": price,
        "base_amount": base,
        "quote_amount": quote_amount,
        "fee": round(fee, 2),
        "profit": round(profit, 2),
        "candle": idx,
        "timestamp": candle.get("timestamp"),
    })
    return quote, 0.0, None, fee


def _portfolio_value(quote: float, base: float, price: float, config: BacktestConfig) -> float:
    if base <= 0:
        return quote
    execution_price = price * (1 - config.slippage_pct)
    liquidation_value = base * execution_price * (1 - config.fee_pct)
    return quote + liquidation_value


def _sorted_valid_candles(candles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    valid = [c for c in candles if c.get("close") is not None]
    timestamps = [_timestamp_value(c.get("timestamp")) for c in valid]
    if len(valid) <= 1 or any(value is None for value in timestamps):
        return valid
    return [candle for _, candle in sorted(zip(timestamps, valid), key=lambda item: item[0])]


def _timestamp_value(raw: Any) -> float | None:
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


def _payload_float(payload: dict[str, Any], key: str, default: float) -> float:
    value = payload.get(key)
    if value is None or value == "":
        return float(default)
    return float(value)


def _float_options(default: float, values: list[float], min_value: float, max_value: float) -> list[float]:
    result = {round(_clamp(default, min_value, max_value), 4)}
    for value in values:
        result.add(round(_clamp(float(value), min_value, max_value), 4))
    return sorted(result)


def _int_options(default: int, values: list[int]) -> list[int]:
    result = {max(2, int(default))}
    for value in values:
        result.add(max(2, int(value)))
    return sorted(result)


def _clamp(value: float, min_value: float, max_value: float) -> float:
    return max(min_value, min(max_value, value))


def _trim_result(result: dict[str, Any], trades_limit: int, equity_limit: int) -> dict[str, Any]:
    trimmed = dict(result)
    trimmed["trades"] = trimmed.get("trades", [])[-trades_limit:]
    trimmed["equity_curve"] = trimmed.get("equity_curve", [])[-equity_limit:]
    return trimmed
