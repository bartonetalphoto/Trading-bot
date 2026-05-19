"""
Trading strategies used by the live runner and backtester.

Each strategy returns a small StrategyDecision so the rest of the app can keep
using a simple BUY / SELL / HOLD contract while still seeing the reason and
indicator values that produced the signal.
"""

from dataclasses import dataclass
from typing import Any

from config import FAST_EMA_PERIOD, SLOW_EMA_PERIOD


STRATEGY_PRESETS: dict[str, dict[str, Any]] = {
    "trend": {
        "label": "Trend follow",
        "fast_ema_period": 9,
        "slow_ema_period": 21,
        "trade_amount_pct": 0.85,
        "stop_loss_pct": 0.05,
        "take_profit_pct": 0.08,
        "max_position_pct": 0.9,
    },
    "scalp": {
        "label": "Scalping",
        "fast_ema_period": 5,
        "slow_ema_period": 13,
        "trade_amount_pct": 0.45,
        "stop_loss_pct": 0.025,
        "take_profit_pct": 0.04,
        "max_position_pct": 0.65,
    },
    "grid": {
        "label": "Grid range",
        "fast_ema_period": 7,
        "slow_ema_period": 21,
        "trade_amount_pct": 0.35,
        "stop_loss_pct": 0.04,
        "take_profit_pct": 0.045,
        "max_position_pct": 0.7,
    },
    "dca": {
        "label": "DCA dip",
        "fast_ema_period": 9,
        "slow_ema_period": 30,
        "trade_amount_pct": 0.25,
        "stop_loss_pct": 0.1,
        "take_profit_pct": 0.12,
        "max_position_pct": 0.95,
    },
    "breakout": {
        "label": "Breakout",
        "fast_ema_period": 10,
        "slow_ema_period": 24,
        "trade_amount_pct": 0.6,
        "stop_loss_pct": 0.045,
        "take_profit_pct": 0.09,
        "max_position_pct": 0.75,
    },
    "conservative": {
        "label": "Conservative",
        "fast_ema_period": 12,
        "slow_ema_period": 30,
        "trade_amount_pct": 0.35,
        "stop_loss_pct": 0.035,
        "take_profit_pct": 0.07,
        "max_position_pct": 0.5,
    },
}


@dataclass
class StrategyDecision:
    signal: str
    fast_ema: float
    slow_ema: float
    trend: str
    reason: str
    confidence: float = 0.0


def strategy_label(strategy_name: str) -> str:
    return STRATEGY_PRESETS.get(strategy_name, {}).get("label", strategy_name.title())


def strategy_preset(strategy_name: str) -> dict[str, Any]:
    normalized = (strategy_name or "trend").lower()
    return STRATEGY_PRESETS.get(normalized, STRATEGY_PRESETS["trend"])


def build_strategy(
    strategy_name: str,
    fast_period: int = FAST_EMA_PERIOD,
    slow_period: int = SLOW_EMA_PERIOD,
) -> "BaseStrategy":
    normalized = (strategy_name or "trend").lower()
    classes = {
        "trend": TrendStrategy,
        "scalp": ScalpingStrategy,
        "grid": GridStrategy,
        "dca": DCAStrategy,
        "breakout": BreakoutStrategy,
        "conservative": ConservativeStrategy,
    }
    strategy_cls = classes.get(normalized, TrendStrategy)
    return strategy_cls(fast_period=fast_period, slow_period=slow_period)


def _ema(prices: list[float], period: int) -> list[float]:
    """Calculate Exponential Moving Average for a price series."""
    if len(prices) < period:
        return prices[:]
    k = 2 / (period + 1)
    ema = [sum(prices[:period]) / period]
    for price in prices[period:]:
        ema.append(price * k + ema[-1] * (1 - k))
    return ema


def _ema_value(prices: list[float], period: int) -> float:
    values = _ema(prices, period)
    return values[-1] if values else 0.0


def _round(value: float) -> float:
    return round(float(value or 0.0), 2)


def _closes(candles_or_closes: list[Any]) -> list[float]:
    if not candles_or_closes:
        return []
    if isinstance(candles_or_closes[0], dict):
        return [float(c["close"]) for c in candles_or_closes if c.get("close") is not None]
    return [float(price) for price in candles_or_closes]


def _candles(candles_or_closes: list[Any]) -> list[dict[str, float]]:
    if not candles_or_closes:
        return []
    if isinstance(candles_or_closes[0], dict):
        result = []
        for candle in candles_or_closes:
            close = float(candle.get("close") or 0.0)
            result.append({
                "open": float(candle.get("open") or close),
                "high": float(candle.get("high") or close),
                "low": float(candle.get("low") or close),
                "close": close,
                "volume": float(candle.get("volume") or 0.0),
            })
        return result
    return [{"open": float(p), "high": float(p), "low": float(p), "close": float(p), "volume": 0.0} for p in candles_or_closes]


def _volume_confirmed(candles: list[dict[str, float]], multiplier: float = 0.8, lookback: int = 20) -> bool:
    volumes = [c["volume"] for c in candles[-lookback:] if c.get("volume", 0.0) > 0]
    if len(volumes) < max(3, lookback // 4):
        return True
    average = sum(volumes[:-1] or volumes) / len(volumes[:-1] or volumes)
    return volumes[-1] >= average * multiplier


def _macd(closes: list[float]) -> tuple[float, float, float, float, float]:
    if len(closes) < 35:
        return 0.0, 0.0, 0.0, 0.0, 0.0
    ema12 = _ema(closes, 12)
    ema26 = _ema(closes, 26)
    size = min(len(ema12), len(ema26))
    line = [ema12[-size + idx] - ema26[-size + idx] for idx in range(size)]
    signal_line = _ema(line, 9)
    if len(signal_line) < 2 or len(line) < 2:
        return line[-1], 0.0, line[-1], 0.0, 0.0
    macd_now = line[-1]
    macd_prev = line[-2]
    signal_now = signal_line[-1]
    signal_prev = signal_line[-2]
    return macd_now, signal_now, macd_now - signal_now, macd_prev, signal_prev


def _atr_pct(candles: list[dict[str, float]], lookback: int = 14) -> float:
    if len(candles) < 2:
        return 0.0
    recent = candles[-lookback:]
    ranges = []
    previous_close = candles[-len(recent) - 1]["close"] if len(candles) > len(recent) else recent[0]["close"]
    for candle in recent:
        true_range = max(
            candle["high"] - candle["low"],
            abs(candle["high"] - previous_close),
            abs(candle["low"] - previous_close),
        )
        ranges.append(true_range)
        previous_close = candle["close"]
    atr = sum(ranges) / len(ranges)
    current = candles[-1]["close"] or 1.0
    return (atr / current) * 100


class BaseStrategy:
    min_candles = 35
    allows_scale_in = False

    def __init__(self, fast_period: int = FAST_EMA_PERIOD, slow_period: int = SLOW_EMA_PERIOD):
        self.last_signal = "HOLD"
        self.fast_period = fast_period
        self.slow_period = slow_period

    def signal(self, closes: list[float]) -> tuple[str, float, float]:
        decision = self.evaluate(closes)
        return decision.signal, decision.fast_ema, decision.slow_ema

    def evaluate(self, candles_or_closes: list[Any]) -> StrategyDecision:
        candles = _candles(candles_or_closes)
        closes = [c["close"] for c in candles]
        fast, slow = self._emas(closes)
        decision = self._hold(fast, slow, "No strategy signal")
        self.last_signal = decision.signal
        return decision

    def trend_strength(self, candles_or_closes: list[Any]) -> str:
        closes = _closes(candles_or_closes)
        fast, slow = self._emas(closes)
        return self._trend_text(closes, fast, slow)

    def _emas(self, closes: list[float]) -> tuple[float, float]:
        if not closes:
            return 0.0, 0.0
        return _ema_value(closes, self.fast_period), _ema_value(closes, self.slow_period)

    def _hold(self, fast: float, slow: float, reason: str, confidence: float = 0.0) -> StrategyDecision:
        return StrategyDecision("HOLD", _round(fast), _round(slow), self._trend_text([], fast, slow), reason, confidence)

    def _decision(
        self,
        signal: str,
        closes: list[float],
        fast: float,
        slow: float,
        reason: str,
        confidence: float,
    ) -> StrategyDecision:
        decision = StrategyDecision(signal, _round(fast), _round(slow), self._trend_text(closes, fast, slow), reason, confidence)
        self.last_signal = signal
        return decision

    def _trend_text(self, closes: list[float], fast: float, slow: float) -> str:
        if not slow:
            return "Waiting for indicator history"
        gap_pct = ((fast - slow) / slow) * 100
        if gap_pct > 1.5:
            return f"Strong uptrend (+{gap_pct:.2f}%)"
        if gap_pct > 0:
            return f"Weak uptrend (+{gap_pct:.2f}%)"
        if gap_pct > -1.5:
            return f"Weak downtrend ({gap_pct:.2f}%)"
        return f"Strong downtrend ({gap_pct:.2f}%)"


class TrendStrategy(BaseStrategy):
    """EMA trend following with MACD and volume confirmation."""

    def evaluate(self, candles_or_closes: list[Any]) -> StrategyDecision:
        candles = _candles(candles_or_closes)
        closes = [c["close"] for c in candles]
        if len(closes) < max(self.slow_period + 2, 35):
            return self._hold(0.0, 0.0, "Waiting for EMA/MACD history")

        fast = _ema(closes, self.fast_period)
        slow = _ema(closes, self.slow_period)
        fast_now, fast_prev = fast[-1], fast[-2]
        slow_now, slow_prev = slow[-1], slow[-2]
        macd_now, macd_signal, hist, macd_prev, macd_signal_prev = _macd(closes)
        volume_ok = _volume_confirmed(candles, multiplier=0.75)

        crossed_above = fast_prev <= slow_prev and fast_now > slow_now
        crossed_below = fast_prev >= slow_prev and fast_now < slow_now
        macd_bull = macd_now > macd_signal and hist > 0
        macd_bear = macd_now < macd_signal and hist < 0
        macd_turn_up = macd_prev <= macd_signal_prev and macd_bull
        macd_turn_down = macd_prev >= macd_signal_prev and macd_bear

        if volume_ok and macd_bull and (crossed_above or (fast_now > slow_now and macd_turn_up)):
            return self._decision("BUY", closes, fast_now, slow_now, "EMA trend confirmed by MACD and volume", 0.74)
        if crossed_below or (fast_now < slow_now and (macd_bear or macd_turn_down)):
            return self._decision("SELL", closes, fast_now, slow_now, "EMA/MACD trend has weakened", 0.7)
        return self._decision("HOLD", closes, fast_now, slow_now, "Trend confirmation incomplete", 0.35)


class ScalpingStrategy(BaseStrategy):
    """Short-period momentum strategy for faster entries and exits."""

    min_candles = 20

    def evaluate(self, candles_or_closes: list[Any]) -> StrategyDecision:
        candles = _candles(candles_or_closes)
        closes = [c["close"] for c in candles]
        if len(closes) < max(self.slow_period + 2, 20):
            return self._hold(0.0, 0.0, "Waiting for scalp history")

        fast = _ema(closes, self.fast_period)
        slow = _ema(closes, self.slow_period)
        fast_now, slow_now = fast[-1], slow[-1]
        momentum_3 = (closes[-1] - closes[-4]) / closes[-4] if closes[-4] else 0.0
        momentum_6 = (closes[-1] - closes[-7]) / closes[-7] if len(closes) > 7 and closes[-7] else momentum_3
        volume_ok = _volume_confirmed(candles, multiplier=0.7, lookback=12)

        if fast_now > slow_now and momentum_3 > 0.0015 and volume_ok:
            return self._decision("BUY", closes, fast_now, slow_now, "Fast momentum with volume support", 0.62)
        if fast_now < slow_now or momentum_3 < -0.0015 or momentum_6 < -0.003:
            return self._decision("SELL", closes, fast_now, slow_now, "Short-term momentum faded", 0.58)
        return self._decision("HOLD", closes, fast_now, slow_now, "No clean scalp setup", 0.3)


class GridStrategy(BaseStrategy):
    """Range strategy that buys lower-band weakness and sells upper-band strength."""

    min_candles = 30

    def evaluate(self, candles_or_closes: list[Any]) -> StrategyDecision:
        candles = _candles(candles_or_closes)
        closes = [c["close"] for c in candles]
        if len(closes) < max(self.slow_period + 2, 30):
            return self._hold(0.0, 0.0, "Waiting for range history")

        fast, slow = self._emas(closes)
        window = candles[-48:] if len(candles) >= 48 else candles
        range_low = min(c["low"] for c in window)
        range_high = max(c["high"] for c in window)
        width = range_high - range_low
        if width <= 0:
            return self._decision("HOLD", closes, fast, slow, "Range is too narrow", 0.0)

        current = closes[-1]
        lower_band = range_low + width * 0.28
        upper_band = range_low + width * 0.72
        breakout_buffer = width * 0.08

        if current < range_low - breakout_buffer or current > range_high + breakout_buffer:
            return self._decision("HOLD", closes, fast, slow, "Price has left the grid range", 0.18)
        if current <= lower_band:
            return self._decision("BUY", closes, fast, slow, "Price near lower grid bound", 0.58)
        if current >= upper_band:
            return self._decision("SELL", closes, fast, slow, "Price near upper grid bound", 0.58)
        return self._decision("HOLD", closes, fast, slow, "Price inside grid mid-range", 0.28)


class DCAStrategy(BaseStrategy):
    """Dip and scheduled accumulation strategy."""

    min_candles = 34
    allows_scale_in = True
    scheduled_interval = 24

    def evaluate(self, candles_or_closes: list[Any]) -> StrategyDecision:
        candles = _candles(candles_or_closes)
        closes = [c["close"] for c in candles]
        if len(closes) < max(self.slow_period + 2, 34):
            return self._hold(0.0, 0.0, "Waiting for DCA history")

        fast, slow = self._emas(closes)
        window = closes[-30:]
        average = sum(window) / len(window)
        current = closes[-1]
        dip_pct = (average - current) / average if average else 0.0
        scheduled = len(closes) % self.scheduled_interval == 0

        if dip_pct >= 0.025:
            return self._decision("BUY", closes, fast, slow, "DCA dip below rolling average", 0.66)
        if scheduled and current <= average * 1.01:
            return self._decision("BUY", closes, fast, slow, "Scheduled DCA accumulation", 0.52)
        if current >= average * 1.065 and fast < slow:
            return self._decision("SELL", closes, fast, slow, "DCA bounce has lost trend support", 0.55)
        return self._decision("HOLD", closes, fast, slow, "No DCA accumulation trigger", 0.25)


class BreakoutStrategy(BaseStrategy):
    """Breakout strategy requiring volatility expansion and volume confirmation."""

    min_candles = 40

    def evaluate(self, candles_or_closes: list[Any]) -> StrategyDecision:
        candles = _candles(candles_or_closes)
        closes = [c["close"] for c in candles]
        if len(closes) < max(self.slow_period + 2, 40):
            return self._hold(0.0, 0.0, "Waiting for breakout history")

        fast, slow = self._emas(closes)
        previous = candles[-37:-1] if len(candles) >= 37 else candles[:-1]
        previous_high = max(c["high"] for c in previous)
        previous_low = min(c["low"] for c in previous)
        current = candles[-1]
        atr = _atr_pct(candles, lookback=14)
        volume_ok = _volume_confirmed(candles, multiplier=1.15, lookback=30)
        trend_ok = fast > slow

        if current["close"] > previous_high and trend_ok and atr >= 0.35 and volume_ok:
            return self._decision("BUY", closes, fast, slow, "Price broke resistance with volatility and volume", 0.78)
        if current["close"] < previous_low or (fast < slow and current["close"] < previous_high):
            return self._decision("SELL", closes, fast, slow, "Breakout failed or broke support", 0.7)
        return self._decision("HOLD", closes, fast, slow, "No confirmed breakout", 0.32)


class ConservativeStrategy(TrendStrategy):
    """Lower-frequency trend strategy with stronger confirmations."""

    min_candles = 50

    def evaluate(self, candles_or_closes: list[Any]) -> StrategyDecision:
        candles = _candles(candles_or_closes)
        closes = [c["close"] for c in candles]
        if len(closes) < max(self.slow_period + 2, 50):
            return self._hold(0.0, 0.0, "Waiting for conservative history")

        fast, slow = self._emas(closes)
        macd_now, macd_signal, hist, _macd_prev, _signal_prev = _macd(closes)
        volume_ok = _volume_confirmed(candles, multiplier=1.0, lookback=30)
        gap_pct = ((fast - slow) / slow) * 100 if slow else 0.0
        recent_high = max(closes[-12:-1])
        recent_low = min(closes[-12:-1])
        current = closes[-1]

        if current > recent_high and gap_pct > 0.25 and macd_now > macd_signal and hist > 0 and volume_ok:
            return self._decision("BUY", closes, fast, slow, "Conservative trend, MACD, volume and price confirmation", 0.82)
        if current < recent_low or (gap_pct < -0.15 and macd_now < macd_signal):
            return self._decision("SELL", closes, fast, slow, "Conservative trend confirmation failed", 0.74)
        return self._decision("HOLD", closes, fast, slow, "Waiting for stronger confirmation", 0.4)
