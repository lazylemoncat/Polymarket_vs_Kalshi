import requests
import logging
from datetime import datetime
from .base_client import BaseAPIClient

class KalshiClient(BaseAPIClient):
    def __init__(self, base_url: str, polling_interval: int, api_key=None):
        super().__init__(name="Kalshi", base_url=base_url, polling_interval=polling_interval)
        self.api_key = api_key

    def fetch_price(self, ticker: str):
        url = f"{self.base_url}/markets/{ticker}/book"
        headers = {"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}
        try:
            resp = requests.get(url, headers=headers, timeout=5)
            if resp.status_code == 429:
                self.handle_rate_limit()
                return None
            resp.raise_for_status()
            data = resp.json()
            bid, ask = float(data["yes_bid"]), float(data["yes_ask"])
            if not (0.01 <= bid <= 0.99 and 0.01 <= ask <= 0.99 and bid <= ask):
                raise ValueError(f"Invalid Kalshi price {bid}/{ask}")

            ts = self.validate_timestamp(data.get("timestamp", datetime.utcnow().isoformat()))
            return {"bid": bid, "ask": ask, "timestamp": ts}
        except Exception as e:
            logging.error({"source": "Kalshi", "error": str(e), "time": datetime.utcnow().isoformat()})
            return None
