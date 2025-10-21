import json
import logging
from typing import Any

import requests


logger = logging.getLogger(__name__)

polymarket_baseurl = "https://gamma-api.polymarket.com"
list_market_url = f"{polymarket_baseurl}/markets"
public_search_url = f"{polymarket_baseurl}/public-search"
get_market_by_id_url = f"{polymarket_baseurl}/markets/{{market_id}}"


def get_market_list() -> Any:
    """获取所有市场列表"""
    response = requests.get(list_market_url)
    return response.json()


def get_market_by_id(market_id: str) -> Any:
    """根据市场 ID 获取市场详情"""
    url = get_market_by_id_url.format(market_id=market_id)
    response = requests.get(url)
    return response.json()


def get_market_public_search(querystring: str) -> Any:
    """根据问题关键词搜索市场"""
    params = {"q": querystring}
    response = requests.get(public_search_url, params=params)
    return response.json()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    market_list = get_market_list()

    from py_clob_client.client import ClobClient  # type: ignore

    client = ClobClient("https://clob.polymarket.com")  # read-only
    for market in market_list:
        try:
            market_id = market.get("id")
            market_by_id = get_market_by_id(market_id)
            clob_token_ids = market_by_id.get("clobTokenIds", [])
            token_ids = json.loads(clob_token_ids)
            token_id = token_ids[0]

            book = client.get_order_book(token_id)
            logger.info("Asks: %d | Bids: %d", len(book.asks), len(book.bids))
        except Exception as exc:  # noqa: BLE001
            logger.exception(
                json.dumps(
                    {
                        "message": "Error processing market",
                        "market_id": market_id,
                        "error": str(exc),
                    },
                    ensure_ascii=False,
                )
            )
            break


if __name__ == "__main__":
    main()
