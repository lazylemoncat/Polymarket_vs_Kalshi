import json
import logging
from datetime import datetime, timezone

import requests

from .base_client import BaseAPIClient


logger = logging.getLogger(__name__)

class PolymarketClient(BaseAPIClient):
    """
    /events/{id} -> 返回该事件下所有子市场
    标准结构：{ "title": str, "bid": float, "ask": float, "raw": dict }
    价格单位：0~1 美元
    """

    def __init__(self, base_url: str, polling_interval: int):
        super().__init__(name="Polymarket", base_url=base_url, polling_interval=polling_interval)

    def fetch_event_markets(self, event_id: str):
        url = f"{self.base_url}/events/{event_id}"
        try:
            resp = requests.get(url, timeout=10)
            if resp.status_code == 429:
                self.handle_rate_limit()
                return []
            resp.raise_for_status()
            data = resp.json()
            markets = data.get("markets") or []

            out = []
            for m in markets:
                title = m.get("groupItemTitle") or m.get("question") or m.get("slug") or str(m.get("id"))

                bid = m.get("bestBid")
                ask = m.get("bestAsk")

                # 兜底：尝试 outcomePrices（如 '["0","1"]'）
                if bid is None or ask is None:
                    op = (m.get("outcomePrices") or "").strip()
                    if op.startswith("["):
                        try:
                            parts = op.strip("[]").replace('"', '').split(",")
                            vals = [float(x) for x in parts if x.strip() != ""]
                            if len(vals) >= 2:
                                bid, ask = min(vals), max(vals)
                        except Exception:
                            pass

                if bid is None or ask is None:
                    continue

                try:
                    bid = float(bid)
                    ask = float(ask)
                except Exception:
                    continue

                if not (0 <= bid <= 1 and 0 <= ask <= 1 and bid <= ask):
                    continue

                out.append({
                    "title": title,
                    "bid": bid,
                    "ask": ask,
                    "raw": m,
                })

            logger.info("[Polymarket] event %s parsed %d markets.", event_id, len(out))
            return out

        except Exception as e:  # noqa: BLE001
            logger.error(
                json.dumps(
                    {
                        "source": "Polymarket",
                        "error": str(e),
                        "time": datetime.now(timezone.utc).isoformat(),
                    },
                    ensure_ascii=False,
                )
            )
            return []


# 单文件测试
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    client = PolymarketClient(
        base_url="https://gamma-api.polymarket.com", polling_interval=2
    )
    markets = client.fetch_event_markets("58873")
    logger.info("markets: %d", len(markets))
    for market in markets:
        logger.debug(json.dumps(market, ensure_ascii=False))
