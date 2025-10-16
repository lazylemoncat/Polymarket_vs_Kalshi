import requests
import logging
from datetime import datetime
from .base_client import BaseAPIClient

class PolymarketClient(BaseAPIClient):
    def __init__(self, base_url: str, polling_interval: int):
        super().__init__(name="Polymarket", base_url=base_url, polling_interval=polling_interval)
        
    def fetch_price(self, token_id: str):
        url = f"{self.base_url}/markets/{token_id}"
        try:
            resp = requests.get(url, timeout=5)
            if resp.status_code == 429:
                self.handle_rate_limit()
                return None
            resp.raise_for_status()
            data = resp.json()

            bid, ask = float(data["bestBid"]), float(data["bestAsk"])
            if not (0.01 <= bid <= 0.99 and 0.01 <= ask <= 0.99 and bid <= ask):
                raise ValueError(f"Invalid Polymarket price {bid}/{ask}")

            ts = self.validate_timestamp(data.get("updatedAt", datetime.utcnow().isoformat()))
            return {"bid": bid, "ask": ask, "timestamp": ts}
        except Exception as e:
            logging.error({"source": "Polymarket", "error": str(e), "time": datetime.utcnow().isoformat()})
            return None
