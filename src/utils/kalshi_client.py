"""Client for fetching market data from Kalshi's public API."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List

import requests

from .base_client import BaseAPIClient


LOGGER = logging.getLogger(__name__)


class KalshiClient(BaseAPIClient):
    """Thin wrapper around the Kalshi event API with rate-limit awareness."""

    RATE_LIMIT_STATUS = 429
    COOLDOWN_SECONDS = 300

    def __init__(self, base_url: str, polling_interval: int, api_key: str | None = None):
        super().__init__(name="Kalshi", base_url=base_url, polling_interval=polling_interval)
        self.api_key = api_key
        self.retry_count = 0
        self.last_retry_ts = 0.0

    def fetch_event_markets(self, event_ticker: str) -> List[Dict[str, Any]]:
        url = f"{self.base_url}/events/{event_ticker}"
        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        try:
            response = requests.get(url, headers=headers, timeout=10)

            if response.status_code == self.RATE_LIMIT_STATUS:
                self._register_retry()
                self.handle_rate_limit()
                LOGGER.warning("[Kalshi] HTTP 429 (rate limited). retry_count=%s", self.retry_count)
                return []

            response.raise_for_status()
            markets = (response.json() or {}).get("markets") or []
            parsed = [market for market in map(self._parse_market, markets) if market]

            if self.retry_count:
                LOGGER.info("[Kalshi] ✅ 请求恢复正常，重试计数清零 (was %s)", self.retry_count)
            self.retry_count = 0
            return parsed

        except Exception as exc:  # noqa: BLE001
            self._register_retry()
            LOGGER.error(
                {
                    "source": "Kalshi",
                    "error": str(exc),
                    "retry_count": self.retry_count,
                    "time": datetime.now(timezone.utc).isoformat(),
                }
            )
            return []

    def should_extend_interval(self) -> bool:
        """Return True when the caller should apply a longer polling interval."""

        within_cooldown = time.time() - self.last_retry_ts < self.COOLDOWN_SECONDS
        return self.retry_count >= 5 and within_cooldown

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------
    def _register_retry(self) -> None:
        self.retry_count += 1
        self.last_retry_ts = time.time()

    @staticmethod
    def _parse_market(market: Dict[str, Any]) -> Dict[str, Any] | None:
        def to_float(value, default):
            if value is None:
                return default
            try:
                return float(str(value).strip('"'))
            except Exception:  # noqa: BLE001
                return default

        def pick_title(entry: Dict[str, Any]) -> str:
            for key in ("title", "subtitle", "yes_sub_title", "no_sub_title", "ticker"):
                candidate = entry.get(key)
                if isinstance(candidate, str) and candidate.strip():
                    return candidate.strip().replace("$", "").strip()
            return "Unknown"

        bid = to_float(market.get("yes_bid_dollars"), 0.0)
        ask = to_float(market.get("yes_ask_dollars"), 1.0)

        if not (0 <= bid <= 1 and 0 <= ask <= 1 and bid <= ask):
            return None

        return {
            "title": pick_title(market),
            "bid": bid,
            "ask": ask,
            "raw": market,
        }
