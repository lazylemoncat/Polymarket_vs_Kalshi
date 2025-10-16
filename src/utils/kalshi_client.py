import requests
import logging
from datetime import datetime
from .base_client import BaseAPIClient


class KalshiClient(BaseAPIClient):
    """
    Kalshi API 客户端
    通过 /events/{event_ticker} 获取事件详情和其所有市场行情。
    文档：https://trading-api.readme.io/reference/get_events-event-ticker
    """

    def __init__(self, base_url: str, polling_interval: int, api_key: str = None):
        super().__init__(name="Kalshi", base_url=base_url, polling_interval=polling_interval)
        self.api_key = api_key

    def fetch_event_markets(self, event_ticker: str):
        """
        根据事件ticker获取所有市场的行情。
        :param event_ticker: 如 "KXHIGHNY-25OCT15"
        :return: list[dict]
        """
        url = f"{self.base_url}/events/{event_ticker}"
        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        try:
            resp = requests.get(url, headers=headers, timeout=10)
            if resp.status_code == 429:
                self.handle_rate_limit()
                return []
            resp.raise_for_status()

            data = resp.json()
            if "markets" not in data:
                logging.warning(f"[Kalshi] Event {event_ticker} has no markets field.")
                return []

            results = []
            for m in data["markets"]:
                try:
                    yes_bid = float(m.get("yes_bid_dollars", "0").strip('"'))
                    yes_ask = float(m.get("yes_ask_dollars", "1").strip('"'))
                    no_bid = float(m.get("no_bid_dollars", "0").strip('"'))
                    no_ask = float(m.get("no_ask_dollars", "1").strip('"'))

                    # 简化取价：我们主要关注 yes 方向
                    bid = yes_bid
                    ask = yes_ask

                    if not (0 <= bid <= 1 and 0 <= ask <= 1):
                        continue

                    results.append({
                        "ticker": m.get("ticker"),
                        "subtitle": m.get("subtitle", ""),
                        "bid": bid,
                        "ask": ask,
                        "volume": m.get("volume", 0),
                        "status": m.get("status"),
                        "strike_type": m.get("strike_type"),
                        "floor_strike": m.get("floor_strike"),
                        "cap_strike": m.get("cap_strike"),
                        "open_interest": m.get("open_interest"),
                        "updatedAt": datetime.utcnow().isoformat()
                    })
                except Exception as inner_e:
                    logging.warning(f"[Kalshi] skip invalid market: {inner_e}")

            logging.info(f"[Kalshi] Event {event_ticker} => {len(results)} markets parsed.")
            return results

        except Exception as e:
            logging.error({
                "source": "Kalshi",
                "error": str(e),
                "time": datetime.utcnow().isoformat()
            })
            return []


# ------------------------------------------------------------------------------
# ✅ 独立测试区块
# ------------------------------------------------------------------------------
if __name__ == "__main__":
    from pprint import pprint

    print("🔍 Testing Kalshi API connection...")

    kalshi = KalshiClient(
        base_url="https://api.elections.kalshi.com/trade-api/v2",
        polling_interval=2,
        api_key=None
    )

    event_ticker = "KXHIGHNY-25OCT15"
    print(f"Fetching event {event_ticker} from Kalshi...")
    markets = kalshi.fetch_event_markets(event_ticker)

    if not markets:
        print("❌ No markets returned or API request failed.")
    else:
        print(f"✅ Retrieved {len(markets)} markets from event {event_ticker}")
        print("-" * 80)
        for m in markets:
            pprint(m)
