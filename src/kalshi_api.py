import json
import logging
from typing import Any, Optional

import requests


logger = logging.getLogger(__name__)

kalshi_baseurl = "https://api.elections.kalshi.com/trade-api/v2"
get_markets_url = f"{kalshi_baseurl}/markets"
get_event_by_event_ticker_url = f"{kalshi_baseurl}/events/{{event_ticker}}"


def get_kalshi_markets() -> list[dict]:
    response = requests.get(get_markets_url)
    return response.json().get("markets", [])


def get_event_ticker_by_title(title: str) -> Optional[str]:
    markets = get_kalshi_markets()
    for market in markets:
        if market.get("title") == title:
            return market.get("event_ticker")
    return None


def get_event_by_event_ticker(event_ticker: str) -> Any:
    url = get_event_by_event_ticker_url.format(event_ticker=event_ticker)
    response = requests.get(url)
    return response.json()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    event = get_event_by_event_ticker("KXPOWELLMENTION-25OCT15")
    logger.info(json.dumps(event, ensure_ascii=False))


if __name__ == "__main__":
    main()
