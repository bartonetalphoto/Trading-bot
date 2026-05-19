from typing import Protocol

from valr_client import ValrClient


class ExchangeClient(Protocol):
    def get_candles(self, pair: str, interval: int = 3600, limit: int = 100) -> list[dict]:
        ...

    def get_balances(self) -> dict:
        ...

    def place_market_buy(self, pair: str, zar_amount: float) -> dict:
        ...

    def place_market_sell(self, pair: str, btc_amount: float) -> dict:
        ...


def get_exchange_client(exchange: str, api_key: str, api_secret: str) -> ExchangeClient:
    normalized = (exchange or "valr").lower()
    if normalized == "valr":
        return ValrClient(api_key, api_secret)
    raise ValueError(f"Unsupported exchange: {exchange}")
