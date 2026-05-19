from database import init_db, session_scope
from models import Bot, Trade


def main():
    init_db()
    with session_scope() as session:
        bots = session.query(Bot).order_by(Bot.created_at.asc()).all()
        if not bots:
            print("No bots found yet. Run the app first.")
            return

        print("\n" + "=" * 62)
        print("  BotTrader Performance Report")
        print("=" * 62)

        for bot in bots:
            trades = session.query(Trade).filter(Trade.bot_id == bot.id).order_by(Trade.created_at.asc()).all()
            exits = [trade for trade in trades if trade.profit is not None]
            wins = [trade for trade in exits if trade.profit and trade.profit > 0]
            losses = [trade for trade in exits if trade.profit and trade.profit < 0]
            total_pnl = sum(trade.profit or 0 for trade in exits)
            win_rate = (len(wins) / len(exits) * 100) if exits else 0
            avg_win = sum(trade.profit or 0 for trade in wins) / len(wins) if wins else 0
            avg_loss = sum(trade.profit or 0 for trade in losses) / len(losses) if losses else 0

            print(f"\n  {bot.name} [{bot.pair}]")
            print(f"  Mode            : {bot.mode.upper()} | {bot.status}")
            print(f"  Portfolio       : R{bot.portfolio_value:,.2f}")
            print(f"  P&L             : R{bot.pnl:+,.2f} ({bot.pnl_pct:+.2f}%)")
            print(f"  Total trades    : {len(trades)}")
            print(f"  Exit trades     : {len(exits)}")
            print(f"  Win rate        : {win_rate:.1f}%")
            print(f"  Avg win/loss    : R{avg_win:+,.2f} / R{avg_loss:+,.2f}")
            print(f"  Realized P&L    : R{total_pnl:+,.2f}")

            if trades:
                print("\n  Recent trades:")
                print(f"  {'TYPE':<14} {'PRICE':>12}  {'PROFIT':>10}  TIME")
                print("  " + "-" * 54)
                for trade in trades[-10:]:
                    profit = f"R{trade.profit:+9,.2f}" if trade.profit is not None else "         -"
                    time_s = trade.created_at.isoformat()[:16]
                    print(f"  {trade.type:<14} R{trade.price:>10,.0f}  {profit}  {time_s}")

        print("\n" + "=" * 62 + "\n")


if __name__ == "__main__":
    main()
