from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

import requests


def _parse_iso_timestamp(value: Optional[str]) -> Optional[datetime]:
    """Parse ISO formatted timestamp strings into aware datetime objects."""
    if not value:
        return None
    try:
        # Handle trailing Z and fractional seconds gracefully
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        return datetime.fromisoformat(value)
    except ValueError:
        return None


@dataclass
class Quote:
    bid: float
    ask: float
    source_timestamp: Optional[datetime]

    def as_tuple(self) -> Tuple[float, float]:
        return self.bid, self.ask


@dataclass
class QuoteResponse:
    ok: bool
    quote: Optional[Quote] = None
    status_code: Optional[int] = None
    error: Optional[str] = None
    raw: Optional[Dict[str, Any]] = None


class BaseHTTPClient:
    def __init__(self, timeout: float = 10.0) -> None:
        self.session = requests.Session()
        self.timeout = timeout

    def _get(self, url: str) -> Tuple[Optional[requests.Response], Optional[str]]:
        try:
            response = self.session.get(url, timeout=self.timeout)
            return response, None
        except requests.RequestException as exc:
            return None, str(exc)


class PolymarketClient(BaseHTTPClient):
    BASE_URL = "https://gamma-api.polymarket.com"

    def get_quote(self, market_id: str) -> QuoteResponse:
        url = f"{self.BASE_URL}/markets/{market_id}"
        response, error = self._get(url)
        if error:
            return QuoteResponse(ok=False, error=error)
        if response is None:
            return QuoteResponse(ok=False, error="Empty response object")

        raw: Dict[str, Any]
        try:
            raw = response.json()
        except ValueError as exc:
            return QuoteResponse(
                ok=False,
                error=f"Invalid JSON payload: {exc}",
                status_code=response.status_code,
            )

        if response.status_code != 200:
            return QuoteResponse(
                ok=False,
                error=f"HTTP {response.status_code}",
                status_code=response.status_code,
                raw=raw,
            )

        quote = self._extract_quote(raw)
        if quote is None:
            return QuoteResponse(
                ok=False,
                error="Unable to extract bid/ask from Polymarket payload",
                status_code=response.status_code,
                raw=raw,
            )

        return QuoteResponse(ok=True, quote=quote, status_code=200, raw=raw)

    def _extract_quote(self, payload: Dict[str, Any]) -> Optional[Quote]:
        # The Polymarket payload may embed prices either at the root level or inside order books
        price_sources = [
            ("bestBid", "bestAsk"),
            ("bestBidYes", "bestAskYes"),
            ("yesBid", "yesAsk"),
            ("bestYesBid", "bestYesAsk"),
        ]

        for bid_key, ask_key in price_sources:
            bid = payload.get(bid_key)
            ask = payload.get(ask_key)
            if isinstance(bid, (float, int)) and isinstance(ask, (float, int)):
                timestamp = _parse_iso_timestamp(payload.get("updatedAt") or payload.get("lastTradeTime"))
                return Quote(float(bid), float(ask), timestamp)

        orderbooks = payload.get("orderbooks") or {}
        yes_book = orderbooks.get("yes") or orderbooks.get("YES") or orderbooks.get("Yes")
        if isinstance(yes_book, dict):
            bid = self._first_price(yes_book.get("bids"))
            ask = self._first_price(yes_book.get("asks"))
            if bid is not None and ask is not None:
                timestamp = _parse_iso_timestamp(payload.get("updatedAt") or payload.get("lastTradeTime"))
                return Quote(bid, ask, timestamp)

        return None

    @staticmethod
    def _first_price(orders: Any) -> Optional[float]:
        if not isinstance(orders, list):
            return None
        for order in orders:
            price = order.get("price") if isinstance(order, dict) else None
            if isinstance(price, (float, int)):
                return float(price)
        return None


class KalshiClient(BaseHTTPClient):
    BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"

    def get_quote(self, ticker: str) -> QuoteResponse:
        url = f"{self.BASE_URL}/markets/{ticker}"
        response, error = self._get(url)
        if error:
            return QuoteResponse(ok=False, error=error)
        if response is None:
            return QuoteResponse(ok=False, error="Empty response object")

        raw: Dict[str, Any]
        try:
            raw = response.json()
        except ValueError as exc:
            return QuoteResponse(
                ok=False,
                error=f"Invalid JSON payload: {exc}",
                status_code=response.status_code,
            )

        if response.status_code != 200:
            return QuoteResponse(
                ok=False,
                error=f"HTTP {response.status_code}",
                status_code=response.status_code,
                raw=raw,
            )

        market = raw.get("market")
        if not isinstance(market, dict):
            return QuoteResponse(
                ok=False,
                error="Kalshi payload missing market object",
                status_code=response.status_code,
                raw=raw,
            )

        quote = self._extract_quote(market)
        if quote is None:
            return QuoteResponse(
                ok=False,
                error="Unable to extract bid/ask from Kalshi payload",
                status_code=response.status_code,
                raw=raw,
            )

        return QuoteResponse(ok=True, quote=quote, status_code=200, raw=raw)

    def _extract_quote(self, market: Dict[str, Any]) -> Optional[Quote]:
        price_fields = [
            ("yes_bid", "yes_ask"),
            ("best_yes_bid", "best_yes_ask"),
            ("bid", "ask"),
        ]
        for bid_key, ask_key in price_fields:
            bid = market.get(bid_key)
            ask = market.get(ask_key)
            if isinstance(bid, (float, int)) and isinstance(ask, (float, int)):
                timestamp = _parse_iso_timestamp(market.get("updated_time") or market.get("last_traded_time"))
                return Quote(float(bid), float(ask), timestamp)

        orderbook = market.get("orderbook")
        if isinstance(orderbook, dict):
            yes = orderbook.get("yes") or {}
            bid = self._first_price(yes.get("bids"))
            ask = self._first_price(yes.get("asks"))
            if bid is not None and ask is not None:
                timestamp = _parse_iso_timestamp(market.get("updated_time") or market.get("last_traded_time"))
                return Quote(bid, ask, timestamp)

        return None

    @staticmethod
    def _first_price(entries: Any) -> Optional[float]:
        if not isinstance(entries, list):
            return None
        for entry in entries:
            if isinstance(entry, dict):
                price = entry.get("price")
                if isinstance(price, (float, int)):
                    return float(price)
        return None
