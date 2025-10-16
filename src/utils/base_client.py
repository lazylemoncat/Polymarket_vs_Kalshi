import time
import logging
from datetime import datetime, timezone

class BaseAPIClient:
    def __init__(self, name: str, base_url: str, polling_interval: int):
        self.name = name
        self.base_url = base_url
        self.interval = polling_interval
        self.last_429_time = None
        self.retry_count = 0

    def handle_rate_limit(self):
        """统一退避机制"""
        now = time.time()
        if not self.last_429_time:
            self.last_429_time = now
            self.retry_count = 1
            wait = 30
        elif now - self.last_429_time < 1800:  # 30分钟内
            self.retry_count += 1
            wait = [30, 60, 120][min(self.retry_count - 1, 2)]
        else:
            self.retry_count = 1
            wait = 30
        logging.warning(f"[{self.name}] Rate limit hit, waiting {wait}s")
        time.sleep(wait)

    def validate_timestamp(self, ts_str):
        """时间戳与UTC校验"""
        ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        delta = abs((datetime.now(timezone.utc) - ts).total_seconds())
        if delta > 10:
            raise ValueError(f"{self.name}: timestamp too old ({delta}s)")
        return ts

    def fetch_price(self, market_id):
        """必须由子类实现"""
        raise NotImplementedError("fetch_price must be implemented in subclass")
