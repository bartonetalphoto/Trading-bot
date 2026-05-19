import unittest

from backtesting import BacktestConfig, compare_backtests, run_backtest
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
        self.assertIn("max_drawdown_pct", result)
        self.assertIn("equity_curve", result)
        self.assertIsInstance(result["trades"], list)

    def test_compare_backtests_returns_ranked_strategies(self):
        closes = [
            100, 99, 98, 97, 98, 100, 103, 106, 104, 101,
            99, 102, 106, 110, 108, 112, 115, 113, 111, 114,
            118, 121, 119, 116, 114, 117, 120, 124, 127, 125,
            123, 126, 130, 133, 131, 128, 126, 129, 134, 138,
            136, 132, 130, 135, 139, 142, 140, 137, 141, 145,
        ]
        candles = [{"close": close} for close in closes]

        results = compare_backtests(
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

        self.assertGreaterEqual(len(results), 4)
        self.assertGreaterEqual(results[0]["pnl_pct"], results[-1]["pnl_pct"])
        self.assertTrue(all("strategy" in result for result in results))


if __name__ == "__main__":
    unittest.main()
