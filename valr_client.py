"""
VALR API Client
================
Uses VALR's REST API directly with HMAC-SHA512 authentication.
Docs: https://docs.valr.com
"""

import hashlib
import hmac
import time
from datetime import datetime, timezone
import requests


BASE_URL = "https://api.valr.com"


class ValrClient:
    def __init__(self, api_key: str, api_secret: str):
        self.api_key    = api_key
        self.api_secret = api_secret
        self.session    = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})

    # ── Auth ───────────────────────────────────────────────────────────────

    def _sign(self, method: str, path: str, body: str = "") -> dict:
        """Generate HMAC-SHA512 signature headers required by VALR."""
        timestamp = str(int(time.time() * 1000))
        payload   = timestamp + method.upper() + path + body
        signature = hmac.new(
            self.api_secret.encode(),
            payload.encode(),
            hashlib.sha512,
        ).hexdigest()
        return {
            "X-VALR-API-KEY":   self.api_key,
            "X-VALR-SIGNATURE": signature,
            "X-VALR-TIMESTAMP": timestamp,
        }

    def _get(self, path: str) -> dict:
        headers = self._sign("GET", path)
        resp    = self.session.get(BASE_URL + path, headers=headers, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def _post(self, path: str, body: dict) -> dict:
        import json
        body_str = json.dumps(body)
        headers  = self._sign("POST", path, body_str)
        resp     = self.session.post(BASE_URL + path, headers=headers, data=body_str, timeout=30)
        resp.raise_for_status()
        return resp.json()

    # ── Market data ────────────────────────────────────────────────────────

    def get_candles(self, pair: str, interval: int = 3600, limit: int = 100) -> list[dict]:
        """
        Fetch OHLC candles for a pair.
        interval = seconds per candle (3600 = 1hr)
        Returns list sorted oldest → newest.
        """
        # VALR candle endpoint — public, no auth needed
        path = f"/v1/public/{pair}/markprice/buckets"
        # Fallback: use trade history to build closes if candles unavailable
        # Primary: use the public OHLC endpoint
        path = f"/v1/public/{pair}/ohlc"
        params = f"?periodSeconds={interval}&limit={limit}"
        resp = self.session.get(BASE_URL + path + params, timeout=30)
        if resp.status_code == 200:
            data = resp.json()
            candles = []
            for c in data:
                candles.append({
                    "timestamp": c.get("startTime", ""),
                    "open":   float(c.get("open",  0)),
                    "high":   float(c.get("high",  0)),
                    "low":    float(c.get("low",   0)),
                    "close":  float(c.get("close", 0)),
                    "volume": float(c.get("volume", 0)),
                })
            return _sort_candles_oldest_first(candles)
        # Fallback: build close prices from recent trades
        return self._candles_from_ticker(pair, limit)

    def _candles_from_ticker(self, pair: str, limit: int) -> list[dict]:
        """Fallback: get recent trade history to build a price series."""
        path = f"/v1/public/{pair}/trades?limit={min(limit, 100)}"
        resp = self.session.get(BASE_URL + path, timeout=30)
        resp.raise_for_status()
        trades = resp.json()
        candles = [{"close": float(t["price"]), "timestamp": t["tradedAt"]} for t in trades]
        return _sort_candles_oldest_first(candles)

    def get_ticker(self, pair: str) -> dict:
        """Get current best bid/ask and last trade price."""
        path = f"/v1/public/{pair}/markprice"
        resp = self.session.get(BASE_URL + path, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        return {"last_trade": float(data.get("markPrice", 0))}

    # ── Account ────────────────────────────────────────────────────────────

    def get_balances(self) -> dict:
        """Returns dict like {'ZAR': 5000.0, 'BTC': 0.00012}"""
        data = self._get("/v1/account/balances")
        result = {}
        for wallet in data:
            result[wallet["currency"]] = float(wallet.get("available", 0))
        return result

    # ── Orders ────────────────────────────────────────────────────────────

    def place_market_buy(self, pair: str, zar_amount: float) -> dict:
        """Buy BTC spending exactly zar_amount ZAR at market price."""
        body = {
            "side":            "BUY",
            "quoteAmount":     str(round(zar_amount, 2)),
            "pair":            pair,
            "timeInForce":     "FOK",   # Fill or Kill — instant or cancel
        }
        return self._post("/v1/orders/market", body)

    def place_market_sell(self, pair: str, btc_amount: float) -> dict:
        """Sell btc_amount BTC at market price."""
        body = {
            "side":        "SELL",
            "baseAmount":  str(round(btc_amount, 8)),
            "pair":        pair,
            "timeInForce": "FOK",
        }
        return self._post("/v1/orders/market", body)


def _sort_candles_oldest_first(candles: list[dict]) -> list[dict]:
    timestamps = [_timestamp_value(candle.get("timestamp")) for candle in candles]
    if len(candles) <= 1 or any(value is None for value in timestamps):
        return candles
    return [candle for _, candle in sorted(zip(timestamps, candles), key=lambda item: item[0])]


def _timestamp_value(raw: str | None) -> float | None:
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()
