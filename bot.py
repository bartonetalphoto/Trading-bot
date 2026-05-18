"""
VALR Trend-Following Trading Bot
==================================
Paper trading is ON by default. Safe to run immediately.
Flip PAPER_TRADING = False in config.py only after 30 profitable paper days.

Run locally:   python bot.py
Deploy:        Push to GitHub → connect Railway → set env vars → deploy
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

# ── Logging ───────────────────────────────────────────────────────────────────
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

# ── Trade log file ────────────────────────────────────────────────────────────
TRADE_LOG_FILE = Path("trades.json")


def load_trade_log() -> list:
    if TRADE_LOG_FILE.exists():
        return json.loads(TRADE_LOG_FILE.read_text())
    return []


def save_trade(trade: dict):
    trades = load_trade_log()
    trades.append(trade)
    TRADE_LOG_FILE.write_text(json.dumps(trades, indent=2))


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    log.info("=" * 65)
    log.info("  VALR Trend Bot")
    log.info(f"  Pair     : {PAIR}")
    log.info(f"  Mode     : {'📄 PAPER TRADING (safe — no real money)' if PAPER_TRADING else '💰 LIVE TRADING'}")
    log.info(f"  Capital  : R{STARTING_CAPITAL_ZAR:,.2f}")
    log.info(f"  Stop-loss: {STOP_LOSS_PERCENT*100:.0f}%   Take-profit: {TAKE_PROFIT_PERCENT*100:.0f}%")
    log.info("=" * 65)

    client   = ValrClient(VALR_API_KEY, VALR_API_SECRET)
    strategy = TrendStrategy()

    # Paper trading state
    paper = {
        "zar":         STARTING_CAPITAL_ZAR,
        "btc":         0.0,
        "position":    None,    # "long" or None
        "entry_price": None,
        "start_zar":   STARTING_CAPITAL_ZAR,
    }

    cycle = 0

    while True:
        cycle += 1
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        log.info(f"── Cycle {cycle}  [{now}] {'─'*35}")

        try:
            # 1. Fetch candle data
            candles = client.get_candles(PAIR, interval=CANDLE_INTERVAL, limit=CANDLE_LIMIT)

            if len(candles) < 30:
                log.warning(f"  Only {len(candles)} candles available — need 30+. Waiting...")
                time.sleep(POLL_INTERVAL_SECONDS)
                continue

            closes        = [c["close"] for c in candles]
            current_price = closes[-1]

            log.info(f"  BTC/ZAR Price : R{current_price:>12,.2f}")

            # 2. Get signal
            signal, fast_ema, slow_ema = strategy.signal(closes)
            trend = strategy.trend_strength(closes)

            log.info(f"  Fast EMA (9)  : R{fast_ema:>12,.2f}")
            log.info(f"  Slow EMA (21) : R{slow_ema:>12,.2f}")
            log.info(f"  Trend         : {trend}")
            log.info(f"  Signal        : ▶ {signal}")

            # 3. Execute
            if PAPER_TRADING:
                _paper_trade(paper, signal, current_price, cycle)
            else:
                _live_trade(client, signal, current_price)

        except KeyboardInterrupt:
            log.info("  Bot stopped by user.")
            break
        except Exception as e:
            log.error(f"  ⚠ Error in cycle {cycle}: {e}", exc_info=True)

        log.info(f"  Sleeping {POLL_INTERVAL_SECONDS // 60} minutes...\n")
        time.sleep(POLL_INTERVAL_SECONDS)


# ── Paper trading ─────────────────────────────────────────────────────────────

def _paper_trade(p: dict, signal: str, price: float, cycle: int):
    """Simulate trades without moving real money."""

    # Check stop-loss and take-profit first
    if p["position"] == "long" and p["entry_price"]:
        change = (price - p["entry_price"]) / p["entry_price"]

        if change <= -STOP_LOSS_PERCENT:
            _paper_exit(p, price, reason="STOP-LOSS")
            return

        if change >= TAKE_PROFIT_PERCENT:
            _paper_exit(p, price, reason="TAKE-PROFIT")
            return

    # Act on signal
    if signal == "BUY" and p["position"] is None and p["zar"] > 10:
        invest       = p["zar"] * TRADE_AMOUNT_PERCENT
        btc_bought   = invest / price
        p["zar"]    -= invest
        p["btc"]    += btc_bought
        p["position"]    = "long"
        p["entry_price"] = price

        log.info(f"  [PAPER BUY]  {btc_bought:.6f} BTC @ R{price:,.2f}  (spent R{invest:,.2f})")
        save_trade({"type": "BUY", "price": price, "btc": btc_bought,
                    "zar_spent": invest, "cycle": cycle,
                    "time": datetime.now(timezone.utc).isoformat()})

    elif signal == "SELL" and p["position"] == "long":
        _paper_exit(p, price, reason="SELL-SIGNAL")

    else:
        in_pos = f"holding {p['btc']:.6f} BTC" if p["position"] else f"R{p['zar']:,.2f} ZAR available"
        log.info(f"  [PAPER HOLD] {in_pos}")

    _paper_summary(p, price)


def _paper_exit(p: dict, price: float, reason: str):
    proceeds     = p["btc"] * price
    profit       = proceeds - (p["btc"] * p["entry_price"])
    p["zar"]    += proceeds
    p["btc"]     = 0.0
    p["position"]    = None
    p["entry_price"] = None

    emoji = "✅" if profit >= 0 else "❌"
    log.info(f"  [{reason}] {emoji}  Sold @ R{price:,.2f}  |  Profit: R{profit:+,.2f}")
    save_trade({"type": reason, "price": price, "profit": profit,
                "time": datetime.now(timezone.utc).isoformat()})


def _paper_summary(p: dict, price: float):
    total = p["zar"] + p["btc"] * price
    pnl   = total - p["start_zar"]
    pct   = (pnl / p["start_zar"]) * 100
    log.info(f"  Portfolio : R{total:>10,.2f}  |  P&L: R{pnl:>+8,.2f}  ({pct:>+.2f}%)")


# ── Live trading ──────────────────────────────────────────────────────────────

def _live_trade(client: ValrClient, signal: str, price: float):
    """Execute real orders on VALR."""
    balances    = client.get_balances()
    zar_balance = balances.get("ZAR", 0.0)
    btc_balance = balances.get("BTC", 0.0)

    log.info(f"  Balance   : R{zar_balance:,.2f} ZAR  |  {btc_balance:.8f} BTC")

    if signal == "BUY" and zar_balance > 50:
        invest = zar_balance * TRADE_AMOUNT_PERCENT
        order  = client.place_market_buy(PAIR, invest)
        log.info(f"  [LIVE BUY]  R{invest:,.2f} → order: {order.get('id', order)}")
        save_trade({"type": "LIVE-BUY", "price": price, "zar_spent": invest,
                    "order": order, "time": datetime.now(timezone.utc).isoformat()})

    elif signal == "SELL" and btc_balance > 0.00001:
        order = client.place_market_sell(PAIR, btc_balance)
        log.info(f"  [LIVE SELL] {btc_balance:.8f} BTC → order: {order.get('id', order)}")
        save_trade({"type": "LIVE-SELL", "price": price, "btc_sold": btc_balance,
                    "order": order, "time": datetime.now(timezone.utc).isoformat()})

    else:
        log.info(f"  [LIVE HOLD] Signal: {signal} — no action needed.")


if __name__ == "__main__":
    main()
