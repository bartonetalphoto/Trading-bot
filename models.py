from sqlalchemy import Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from database import Base, utc_now


class Bot(Base):
    __tablename__ = "bots"

    id = Column(String(36), primary_key=True)
    name = Column(String(120), nullable=False)
    exchange = Column(String(40), nullable=False, default="valr")
    pair = Column(String(40), nullable=False, index=True)
    strategy = Column(String(40), nullable=False, default="trend")
    mode = Column(String(20), nullable=False, default="paper")
    status = Column(String(20), nullable=False, default="running")

    base_currency = Column(String(20), nullable=False, default="BTC")
    quote_currency = Column(String(20), nullable=False, default="ZAR")
    starting_capital = Column(Float, nullable=False, default=1000.0)
    quote_balance = Column(Float, nullable=False, default=1000.0)
    base_balance = Column(Float, nullable=False, default=0.0)
    position = Column(String(20), nullable=True)
    entry_price = Column(Float, nullable=True)

    trade_amount_pct = Column(Float, nullable=False, default=0.95)
    stop_loss_pct = Column(Float, nullable=False, default=0.05)
    take_profit_pct = Column(Float, nullable=False, default=0.08)
    max_position_pct = Column(Float, nullable=False, default=0.95)
    max_daily_loss_pct = Column(Float, nullable=False, default=0.05)
    min_quote_to_trade = Column(Float, nullable=False, default=50.0)

    fast_ema_period = Column(Integer, nullable=False, default=9)
    slow_ema_period = Column(Integer, nullable=False, default=21)
    candle_interval = Column(Integer, nullable=False, default=3600)
    candle_limit = Column(Integer, nullable=False, default=100)
    poll_interval_seconds = Column(Integer, nullable=False, default=3600)

    cycle = Column(Integer, nullable=False, default=0)
    last_price = Column(Float, nullable=False, default=0.0)
    signal = Column(String(30), nullable=False, default="STARTING")
    trend = Column(String(255), nullable=False, default="Bot starting up...")
    fast_ema = Column(Float, nullable=False, default=0.0)
    slow_ema = Column(Float, nullable=False, default=0.0)
    portfolio_value = Column(Float, nullable=False, default=1000.0)
    pnl = Column(Float, nullable=False, default=0.0)
    pnl_pct = Column(Float, nullable=False, default=0.0)
    error = Column(Text, nullable=True)

    last_cycle_at = Column(DateTime(timezone=True), nullable=True)
    next_run_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now)

    trades = relationship("Trade", back_populates="bot", cascade="all, delete-orphan")


class Trade(Base):
    __tablename__ = "trades"

    id = Column(String(36), primary_key=True)
    bot_id = Column(String(36), ForeignKey("bots.id", ondelete="CASCADE"), nullable=False, index=True)
    exchange = Column(String(40), nullable=False, default="valr")
    pair = Column(String(40), nullable=False)
    mode = Column(String(20), nullable=False, default="paper")
    type = Column(String(40), nullable=False)
    side = Column(String(10), nullable=False)
    reason = Column(String(80), nullable=True)
    price = Column(Float, nullable=False, default=0.0)
    base_amount = Column(Float, nullable=False, default=0.0)
    quote_amount = Column(Float, nullable=False, default=0.0)
    profit = Column(Float, nullable=True)
    cycle = Column(Integer, nullable=False, default=0)
    order_id = Column(String(120), nullable=True)
    raw_order = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=utc_now, index=True)

    bot = relationship("Bot", back_populates="trades")
