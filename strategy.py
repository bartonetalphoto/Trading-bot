"""
Trend Following Strategy — EMA Crossover
==========================================
Uses a fast and slow Exponential Moving Average.

  BUY  → fast EMA crosses ABOVE slow EMA  (uptrend confirmed)
  SELL → fast EMA crosses BELOW slow EMA  (downtrend confirmed)
  HOLD → no crossover, stay put

Why EMA over SMA?
  EMA gives more weight to recent prices, so it reacts faster
  to market moves — important for crypto's volatile swings.
"""

from config import FAST_EMA_PERIOD, SLOW_EMA_PERIOD


def _ema(prices: list[float], period: int) -> list[float]:
    """Calculate Exponential Moving Average for a price series."""
    if len(prices) < period:
        return prices  # Not enough data
    k   = 2 / (period + 1)
    ema = [sum(prices[:period]) / period]   # Seed with SMA
    for price in prices[period:]:
        ema.append(price * k + ema[-1] * (1 - k))
    return ema


class TrendStrategy:
    def __init__(self):
        self.last_signal = "HOLD"

    def signal(self, closes: list[float]) -> tuple[str, float, float]:
        """
        Analyse price series and return a trading signal.

        Returns:
            (signal, fast_ema_value, slow_ema_value)
            signal ∈ {"BUY", "SELL", "HOLD"}
        """
        if len(closes) < SLOW_EMA_PERIOD + 2:
            return "HOLD", 0.0, 0.0

        fast = _ema(closes, FAST_EMA_PERIOD)
        slow = _ema(closes, SLOW_EMA_PERIOD)

        # Align lengths (fast EMA is longer than slow EMA list)
        min_len   = min(len(fast), len(slow))
        fast_now  = fast[-1]
        fast_prev = fast[-2]
        slow_now  = slow[-1]
        slow_prev = slow[-2]

        crossed_above = fast_prev <= slow_prev and fast_now > slow_now
        crossed_below = fast_prev >= slow_prev and fast_now < slow_now

        if crossed_above:
            signal = "BUY"
        elif crossed_below:
            signal = "SELL"
        else:
            signal = "HOLD"

        self.last_signal = signal
        return signal, round(fast_now, 2), round(slow_now, 2)

    def trend_strength(self, closes: list[float]) -> str:
        """Returns a human-readable trend description."""
        fast = _ema(closes, FAST_EMA_PERIOD)
        slow = _ema(closes, SLOW_EMA_PERIOD)
        if not fast or not slow:
            return "unknown"
        gap_pct = ((fast[-1] - slow[-1]) / slow[-1]) * 100
        if gap_pct > 1.5:
            return f"Strong uptrend (+{gap_pct:.2f}%)"
        elif gap_pct > 0:
            return f"Weak uptrend (+{gap_pct:.2f}%)"
        elif gap_pct > -1.5:
            return f"Weak downtrend ({gap_pct:.2f}%)"
        else:
            return f"Strong downtrend ({gap_pct:.2f}%)"
