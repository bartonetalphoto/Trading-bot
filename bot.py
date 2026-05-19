"""
VALR Trend-Following Trading Bot  (v2 — with API integration)
================================================================
Now writes bot_status.json every cycle so the dashboard PWA can read it.
Respects bot_paused.flag — pause/resume via the PWA without redeploying.
"""

import json
import time
import logging
from datetime import datetime, timezone
from pathlib import Path

from config import (
    VALR_API_KEY, VALR_API_SECRET,
    PAIR, PAPER_TRADING,
    STARTING_CAPITAL_ZAR,
    TRADE_AMOUNT_PERCENT,
    STOP_LOSS_PERCENT,
    TAKE_PROFIT_PERCENT,
    POLL_INTERVAL_SECONDS,
    CANDLE_INTERVAL, CANDLE_LIMIT,
)
from strategy import TrendStrategy
from valr_client import ValrClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("bot.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("valr-bot")

TRADE_LOG_FILE  = Path("trades.json")
STATUS_FILE     = Path("bot_status.json")
PAUSE_FILE      = Path("bot_paused.flag")


def load_trades() -> list:
    if TRADE_LOG_FILE.exists():
        return json.loads(TRADE_LOG_FILE.read_text())
    return []


def save_trade(trade: dict):
    trades = load_trades()
    trades.append(trade)
    TRADE_LOG_FILE.write_text(json.dumps(trades, indent=2))


def write_status(data: dict):
    STATUS_FILE.write_text(json.dumps(data, indent=2))


def main():
    log.info("=" * 65)
    log.info("  VALR Trend Bot v2")
    log.info(f"  Pair     : {PAIR}")
    log.info(f"  Mode     : {'PAPER TRADING' if PAPER_TRADING else 'LIVE TRADING'}")
    log.info(f"  Capital  : R{STARTING_CAPITAL_ZAR:,.2f}")
    log.info("=" * 65)

    client   = ValrClient(VALR_API_KEY, VALR_API_SECRET)
    strategy = TrendStrategy()

    paper = {
        "zar":         STARTING_CAPITAL_ZAR,
        "btc":         0.0,
        "position":    None,
        "entry_price": None,
        "start_zar":   STARTING_CAPITAL_ZAR,
    }

    cycle = 0

    while True:
        cycle += 1
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        log.info(f"-- Cycle {cycle}  [{now}]")

        if PAUSE_FILE.exists():
            log.info("  [PAUSED] Bot paused via dashboard.")
            write_status({
                "pair": PAIR, "cycle": cycle, "price": 0,
                "signal": "PAUSED", "trend": "Bot paused by user",
                "fast_ema": 0, "slow_ema": 0,
                "portfolio_value": round(paper["zar"], 2),
                "pnl": round(paper["zar"] - paper["start_zar"], 2),
                "pnl_pct": round(((paper["zar"] - paper["start_zar"]) / paper["start_zar"]) * 100, 4),
                "paper_trading": PAPER_TRADING,
                "status": "paused",
                "last_updated": datetime.now(timezone.utc).isoformat(),
            })
            time.sleep(POLL_INTERVAL_SECONDS)
            continue

        try:
            candles = client.get_candles(PAIR, interval=CANDLE_INTERVAL, limit=CANDLE_LIMIT)
            if len(candles) < 30:
                log.warning(f"  Only {len(candles)} candles — waiting...")
                time.sleep(POLL_INTERVAL_SECONDS)
                continue

            closes        = [c["close"] for c in candles]
            current_price = closes[-1]
            signal, fast_ema, slow_ema = strategy.signal(closes)
            trend = strategy.trend_strength(closes)

            log.info(f"  BTC/ZAR  : R{current_price:>12,.2f}")
            log.info(f"  Signal   : {signal}  |  Trend: {trend}")

            if PAPER_TRADING:
                _paper_trade(paper, signal, current_price, cycle)
            else:
                _live_trade(client, signal, current_price)

            total = paper["zar"] + paper["btc"] * current_price
            pnl   = total - paper["start_zar"]
            pct   = (pnl / paper["start_zar"]) * 100

            write_status({
                "pair":            PAIR,
                "cycle":           cycle,
                "price":           current_price,
                "signal":          signal,
                "trend":           trend,
                "fast_ema":        fast_ema,
                "slow_ema":        slow_ema,
                "portfolio_value": round(total, 2),
                "pnl":             round(pnl, 2),
                "pnl_pct":         round(pct, 4),
                "paper_trading":   PAPER_TRADING,
                "status":          "active",
                "last_updated":    datetime.now(timezone.utc).isoformat(),
            })

        except KeyboardInterrupt:
            log.info("  Stopped.")
            break
        except Exception as e:
            log.error(f"  Error in cycle {cycle}: {e}", exc_info=True)
            write_status({
                "pair": PAIR, "cycle": cycle, "price": 0,
                "signal": "ERROR", "trend": str(e)[:80],
                "fast_ema": 0, "slow_ema": 0,
                "portfolio_value": round(paper["zar"], 2),
                "pnl": round(paper["zar"] - paper["start_zar"], 2),
                "pnl_pct": 0,
                "paper_trading": PAPER_TRADING,
                "status": "error",
                "last_updated": datetime.now(timezone.utc).isoformat(),
            })

        log.info(f"  Sleeping {POLL_INTERVAL_SECONDS // 60} min...\n")
        time.sleep(POLL_INTERVAL_SECONDS)


def _paper_trade(p, signal, price, cycle):
    if p["position"] == "long" and p["entry_price"]:
        change = (price - p["entry_price"]) / p["entry_price"]
        if change <= -STOP_LOSS_PERCENT:
            _paper_exit(p, price, "STOP-LOSS", cycle)
            return
        if change >= TAKE_PROFIT_PERCENT:
            _paper_exit(p, price, "TAKE-PROFIT", cycle)
            return

    if signal == "BUY" and p["position"] is None and p["zar"] > 10:
        invest = p["zar"] * TRADE_AMOUNT_PERCENT
        btc    = invest / price
        p["zar"] -= invest
        p["btc"] += btc
        p["position"]    = "long"
        p["entry_price"] = price
        log.info(f"  [PAPER BUY] {btc:.6f} BTC @ R{price:,.2f}")
        save_trade({
            "type": "BUY", "price": price, "btc": btc,
            "zar_spent": invest, "profit": None,
            "cycle": cycle, "time": datetime.now(timezone.utc).isoformat()
        })

    elif signal == "SELL" and p["position"] == "long":
        _paper_exit(p, price, "SELL", cycle)
    else:
        in_pos = f"holding {p['btc']:.6f} BTC" if p["position"] else f"R{p['zar']:,.2f} available"
        log.info(f"  [PAPER HOLD] {in_pos}")


def _paper_exit(p, price, reason, cycle):
    proceeds = p["btc"] * price
    profit   = proceeds - (p["btc"] * p["entry_price"])
    p["zar"] += proceeds
    p["btc"]  = 0.0
    p["position"]    = None
    p["entry_price"] = None
    log.info(f"  [{reason}] @ R{price:,.2f}  Profit: R{profit:+,.2f}")
    save_trade({
        "type": reason, "price": price,
        "profit": round(profit, 2),
        "cycle": cycle, "time": datetime.now(timezone.utc).isoformat()
    })


def _live_trade(client, signal, price):
    balances    = client.get_balances()
    zar_balance = balances.get("ZAR", 0.0)
    btc_balance = balances.get("BTC", 0.0)
    log.info(f"  Balance: R{zar_balance:,.2f} ZAR | {btc_balance:.8f} BTC")
    if signal == "BUY" and zar_balance > 50:
        order = client.place_market_buy(PAIR, zar_balance * TRADE_AMOUNT_PERCENT)
        log.info(f"  [LIVE BUY] {order}")
        save_trade({"type": "LIVE-BUY", "price": price, "profit": None,
                    "time": datetime.now(timezone.utc).isoformat()})
    elif signal == "SELL" and btc_balance > 0.00001:
        order = client.place_market_sell(PAIR, btc_balance)
        log.info(f"  [LIVE SELL] {order}")
        save_trade({"type": "LIVE-SELL", "price": price, "profit": None,
                    "time": datetime.now(timezone.utc).isoformat()})


if __name__ == "__main__":
    main()
