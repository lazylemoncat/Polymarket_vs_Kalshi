import requests
import logging
from datetime import datetime, timezone
from .base_client import BaseAPIClient


class KalshiClient(BaseAPIClient):
    """
    /events/{event_ticker} -> 返回该事件下所有子市场
    输出标准结构：{ "title": str, "bid": float, "ask": float, "raw": dict }
    价格单位：0~1 美元（yes_*_dollars）
    """

    def __init__(self, base_url: str, polling_interval: int, api_key: str = None):
        super().__init__(name="Kalshi", base_url=base_url, polling_interval=polling_interval)
        self.api_key = api_key

    def fetch_event_markets(self, event_ticker: str):
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
            markets = data.get("markets") or []

            def to_float_dollars(s, default):
                if s is None:
                    return default
                try:
                    return float(str(s).strip('"'))
                except Exception:
                    return default

            out = []
            for m in markets:
                title = m.get("subtitle") or m.get("yes_sub_title") or m.get("ticker")
                bid = to_float_dollars(m.get("yes_bid_dollars"), 0.0)
                ask = to_float_dollars(m.get("yes_ask_dollars"), 1.0)

                if not (0 <= bid <= 1 and 0 <= ask <= 1 and bid <= ask):
                    continue

                out.append({
                    "title": title,
                    "bid": bid,
                    "ask": ask,
                    "raw": m,
                })

            logging.info(f"[Kalshi] event {event_ticker} parsed {len(out)} markets.")
            return out

        except Exception as e:
            logging.error({
                "source": "Kalshi",
                "error": str(e),
                "time": datetime.now(timezone.utc).isoformat()
            })
            return []


# 独立测试
if __name__ == "__main__":
    from pprint import pprint
    print("🔍 Testing Kalshi /events/{event_ticker} ...")
    client = KalshiClient(
        base_url="https://api.elections.kalshi.com/trade-api/v2",
        polling_interval=2,
        api_key=None
    )
    event_ticker = "KXHIGHNY-25OCT15"
    markets = client.fetch_event_markets(event_ticker)
    print(f"✅ markets: {len(markets)}")
    for m in markets:
        pprint(m)
