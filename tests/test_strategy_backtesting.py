import unittest

from backtesting import BacktestConfig, run_backtest
from strategy import TrendStrategy


class StrategyBacktestingTests(unittest.TestCase):
    def test_trend_strategy_accepts_per_bot_periods(self):
        strategy = TrendStrategy(fast_period=3, slow_period=5)
        closes = [10, 9, 8, 7, 8, 9, 10, 11, 12]

        signal, fast_ema, slow_ema = strategy.signal(closes)

        self.assertIn(signal, {"BUY", "SELL", "HOLD"})
        self.assertGreater(fast_ema, 0)
        self.assertGreater(slow_ema, 0)

    def test_backtest_returns_portfolio_metrics(self):
        closes = [100, 98, 96, 94, 95, 97, 100, 104, 108, 112, 116, 114, 110]
        candles = [{"close": close} for close in closes]

        result = run_backtest(
            candles,
            BacktestConfig(
                starting_capital=1000,
                trade_amount_pct=0.5,
                stop_loss_pct=0.05,
                take_profit_pct=0.08,
                fast_ema_period=3,
                slow_ema_period=5,
            ),
        )

        self.assertTrue(result["ok"])
        self.assertIn("final_value", result)
        self.assertIn("pnl_pct", result)
        self.assertIsInstance(result["trades"], list)


if __name__ == "__main__":
    unittest.main()
