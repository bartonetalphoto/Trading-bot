import unittest

from backtesting import BacktestConfig, compare_backtests, optimize_backtests, run_backtest
from strategy import STRATEGY_PRESETS, TrendStrategy, build_strategy
from valr_client import _sort_candles_oldest_first


class StrategyBacktestingTests(unittest.TestCase):
    def test_trend_strategy_accepts_per_bot_periods(self):
        strategy = TrendStrategy(fast_period=3, slow_period=5)
        closes = [100 + (idx * 0.4) for idx in range(45)]

        signal, fast_ema, slow_ema = strategy.signal(closes)

        self.assertIn(signal, {"BUY", "SELL", "HOLD"})
        self.assertGreater(fast_ema, 0)
        self.assertGreater(slow_ema, 0)

    def test_backtest_returns_portfolio_metrics(self):
        closes = [
            100, 99, 98, 97, 98, 100, 103, 106, 104, 101,
            99, 102, 106, 110, 108, 112, 115, 113, 111, 114,
            118, 121, 119, 116, 114, 117, 120, 124, 127, 125,
            123, 126, 130, 133, 131, 128, 126, 129, 134, 138,
            136, 132, 130, 135, 139, 142, 140, 137, 141, 145,
        ]
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

    def test_breakout_strategy_requires_volume_and_range_break(self):
        candles = []
        for idx in range(44):
            close = 100 + (idx * 0.04)
            candles.append({
                "open": close - 0.2,
                "high": close + 0.5,
                "low": close - 0.5,
                "close": close,
                "volume": 1000,
            })
        candles.append({"open": 103, "high": 107, "low": 102.5, "close": 106, "volume": 2500})

        decision = build_strategy("breakout", fast_period=10, slow_period=24).evaluate(candles)

        self.assertEqual(decision.signal, "BUY")
        self.assertIn("volume", decision.reason.lower())

    def test_dca_backtest_can_scale_into_position(self):
        closes = [100] * 35 + [96, 95, 94, 95, 94, 93, 94, 95, 96, 95]
        candles = [{"close": close} for close in closes]

        result = run_backtest(
            candles,
            BacktestConfig(
                strategy="dca",
                starting_capital=1000,
                trade_amount_pct=0.25,
                stop_loss_pct=0.2,
                take_profit_pct=0.5,
                max_position_pct=0.95,
                fast_ema_period=9,
                slow_ema_period=30,
            ),
        )

        entries = [trade for trade in result["trades"] if trade["type"] in {"BUY", "DCA-BUY"}]
        self.assertGreater(len(entries), 1)
        self.assertTrue(any(trade["type"] == "DCA-BUY" for trade in entries))

    def test_candles_are_sorted_oldest_first(self):
        candles = [
            {"timestamp": "2026-05-19T20:00:00Z", "close": 103},
            {"timestamp": "2026-05-19T18:00:00Z", "close": 101},
            {"timestamp": "2026-05-19T19:00:00Z", "close": 102},
        ]

        sorted_candles = _sort_candles_oldest_first(candles)

        self.assertEqual([c["close"] for c in sorted_candles], [101, 102, 103])

    def test_backtest_includes_transaction_friction(self):
        candles = [
            {"timestamp": f"2026-05-19T00:{i:02d}:00Z", "close": 100 + i}
            for i in range(50)
        ]

        result = run_backtest(
            list(reversed(candles)),
            BacktestConfig(
                strategy="scalp",
                starting_capital=1000,
                trade_amount_pct=0.5,
                stop_loss_pct=0.05,
                take_profit_pct=0.08,
                max_position_pct=0.8,
                fee_pct=0.001,
                slippage_pct=0.0005,
                fast_ema_period=5,
                slow_ema_period=13,
            ),
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["equity_curve"][0]["timestamp"], "2026-05-19T00:19:00Z")
        self.assertIn("fees_paid", result)

    def test_optimizer_returns_validation_ranked_candidates(self):
        closes = [
            100, 99, 98, 97, 98, 100, 103, 106, 104, 101,
            99, 102, 106, 110, 108, 112, 115, 113, 111, 114,
            118, 121, 119, 116, 114, 117, 120, 124, 127, 125,
            123, 126, 130, 133, 131, 128, 126, 129, 134, 138,
            136, 132, 130, 135, 139, 142, 140, 137, 141, 145,
            144, 143, 146, 149, 152, 150, 148, 151, 154, 158,
            156, 153, 155, 159, 162, 161, 158, 160, 164, 167,
            169, 166, 163, 165, 168, 171, 173, 170, 172, 176,
            174, 171, 169, 172, 175, 178, 181, 179, 177, 180,
        ]
        candles = [
            {"close": close}
            for i, close in enumerate(closes)
        ]

        results = optimize_backtests(candles, BacktestConfig(fee_pct=0.0, slippage_pct=0.0), limit=3)

        self.assertGreater(len(results), 0)
        self.assertLessEqual(len(results), 3)
        self.assertIn("validation", results[0])
        self.assertGreaterEqual(results[0]["score"], results[-1]["score"])

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

        self.assertEqual(len(results), len(STRATEGY_PRESETS))
        self.assertGreaterEqual(results[0]["pnl_pct"], results[-1]["pnl_pct"])
        self.assertTrue(all("strategy" in result for result in results))
        self.assertIn("breakout", {result["strategy"] for result in results})
        self.assertIn("conservative", {result["strategy"] for result in results})


if __name__ == "__main__":
    unittest.main()
