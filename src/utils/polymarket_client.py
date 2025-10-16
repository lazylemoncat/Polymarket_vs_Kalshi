import requests
import logging
from datetime import datetime
from .base_client import BaseAPIClient


class PolymarketClient(BaseAPIClient):
    """
    Polymarket API 客户端
    支持通过 /events/{id} 获取事件详情，并提取其中的所有市场行情。
    文档：https://docs.polymarket.com/api-reference/events/get-event-by-id
    """

    def __init__(self, base_url: str, polling_interval: int):
        super().__init__(name="Polymarket", base_url=base_url, polling_interval=polling_interval)

    def fetch_event_markets(self, event_id: str):
        """
        根据事件ID获取所有子市场行情。
        :param event_id: 事件ID（例如 "58873"）
        :return: list[dict] -> [{"id": ..., "question": ..., "bid": ..., "ask": ...}, ...]
        """
        url = f"{self.base_url}/events/{event_id}"
        try:
            resp = requests.get(url, timeout=10)
            if resp.status_code == 429:
                self.handle_rate_limit()
                return []
            resp.raise_for_status()

            data = resp.json()

            if "markets" not in data:
                logging.warning(f"[Polymarket] Event {event_id} has no markets field.")
                return []

            markets = data["markets"]
            results = []

            for m in markets:
                # 优先使用 bestBid / bestAsk，如果没有则尝试 outcomePrices
                bid = m.get("bestBid")
                ask = m.get("bestAsk")

                if (bid is None or ask is None) and m.get("outcomePrices"):
                    try:
                        # outcomePrices 是字符串，如 '["0", "1"]'
                        prices = [float(p) for p in m.get("outcomePrices").strip("[]").replace('"', '').split(",")]
                        bid = min(prices)
                        ask = max(prices)
                    except Exception:
                        bid = ask = None

                # 跳过无效行情
                if bid is None or ask is None:
                    continue

                # 构造统一格式
                results.append({
                    "id": m.get("id"),
                    "question": m.get("question", ""),
                    "bid": float(bid),
                    "ask": float(ask),
                    "volume": float(m.get("volume", 0)),
                    "active": m.get("active", False),
                    "updatedAt": m.get("updatedAt", None)
                })

            logging.info(f"[Polymarket] Event {event_id} => {len(results)} markets parsed.")
            return results

        except Exception as e:
            logging.error({
                "source": "Polymarket",
                "error": str(e),
                "time": datetime.utcnow().isoformat()
            })
            return []


# ------------------------------------------------------------------------------
# ✅ 独立测试区块
# ------------------------------------------------------------------------------
if __name__ == "__main__":
    from pprint import pprint

    print("🔍 Testing Polymarket API connection...")
    poly = PolymarketClient(
        base_url="https://gamma-api.polymarket.com",  # gamma-api 用于测试环境
        polling_interval=2
    )

    event_id = "58873"  # 示例事件ID
    print(f"Fetching event {event_id} from Polymarket...")
    markets = poly.fetch_event_markets(event_id)

    if not markets:
        print("❌ No markets returned or API request failed.")
    else:
        print(f"✅ Retrieved {len(markets)} markets from event {event_id}")
        print("-" * 80)
        for m in markets:
            pprint(m)
