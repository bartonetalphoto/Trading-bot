"""
Performance Analyzer
=====================
Run this anytime to see how your bot is doing:

    python analyze.py

Reads trades.json and prints a full performance report.
"""

import json
from pathlib import Path
from datetime import datetime

TRADE_LOG = Path("trades.json")

def main():
    if not TRADE_LOG.exists():
        print("No trades.json found. Run the bot first!")
        return

    trades = json.loads(TRADE_LOG.read_text())
    if not trades:
        print("No trades recorded yet.")
        return

    print("\n" + "=" * 55)
    print("  VALR Bot — Performance Report")
    print("=" * 55)

    buys       = [t for t in trades if t["type"] in ("BUY", "LIVE-BUY")]
    sells      = [t for t in trades if t["type"] not in ("BUY", "LIVE-BUY")]
    profits    = [t.get("profit", 0) for t in sells if "profit" in t]
    wins       = [p for p in profits if p > 0]
    losses     = [p for p in profits if p < 0]
    total_pnl  = sum(profits)

    print(f"\n  Total trades    : {len(trades)}")
    print(f"  Buy orders      : {len(buys)}")
    print(f"  Exit orders     : {len(sells)}")
    print(f"  Winning trades  : {len(wins)}")
    print(f"  Losing trades   : {len(losses)}")

    if profits:
        win_rate = (len(wins) / len(profits)) * 100
        avg_win  = sum(wins)  / len(wins)  if wins   else 0
        avg_loss = sum(losses)/ len(losses)if losses else 0
        print(f"\n  Win rate        : {win_rate:.1f}%")
        print(f"  Avg win         : R{avg_win:+,.2f}")
        print(f"  Avg loss        : R{avg_loss:+,.2f}")
        print(f"\n  Total P&L       : R{total_pnl:+,.2f}")

    print(f"\n  First trade     : {trades[0].get('time', 'N/A')[:16]}")
    print(f"  Last trade      : {trades[-1].get('time', 'N/A')[:16]}")

    print("\n  Recent trades:")
    print(f"  {'TYPE':<14} {'PRICE':>12}  {'PROFIT':>10}  TIME")
    print("  " + "-" * 50)
    for t in trades[-10:]:
        ptype  = t.get("type", "?")
        price  = f"R{t.get('price', 0):>10,.0f}"
        profit = f"R{t.get('profit', 0):>+9,.2f}" if "profit" in t else "         —"
        time_s = t.get("time", "")[:16]
        print(f"  {ptype:<14} {price}  {profit}  {time_s}")

    print("\n" + "=" * 55 + "\n")


if __name__ == "__main__":
    main()
