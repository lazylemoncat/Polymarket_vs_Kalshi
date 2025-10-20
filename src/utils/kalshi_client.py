import requests
import logging
import time
from datetime import datetime, timezone
from .base_client import BaseAPIClient


class KalshiClient(BaseAPIClient):
    """
    Kalshi 市场数据客户端
    ----------------------
    - 接口: /events/{event_ticker}
    - 返回结构: { "title": str, "bid": float, "ask": float, "raw": dict }
    - 单位: 美元 (yes_*_dollars)
    - 支持自动限速退避与 retry 计数
    """

    def __init__(self, base_url: str, polling_interval: int, api_key: str | None = None):
        super().__init__(name="Kalshi", base_url=base_url, polling_interval=polling_interval)
        self.api_key = api_key
        self.retry_count = 0            # ✅ 初始化重试计数
        self.last_retry_ts = 0.0        # 最近一次错误时间戳
        self.cooldown_seconds = 300     # 连续错误后冷却期（秒）

    def fetch_event_markets(self, event_ticker: str):
        url = f"{self.base_url}/events/{event_ticker}"
        headers = {"Accept": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"  # 使用 API Key 认证

        try:
            resp = requests.get(url, headers=headers, timeout=10)

            # ---------- 429 限速逻辑 ----------
            if resp.status_code == 429:
                self.retry_count += 1
                self.last_retry_ts = time.time()
                self.handle_rate_limit()
                logging.warning(f"[Kalshi] HTTP 429 (rate limited). retry_count={self.retry_count}")
                return []

            resp.raise_for_status()
            data = resp.json()
            markets = data.get("markets") or []

            # ---------- 解析 ----------
            def to_float_dollars(s, default):
                if s is None:
                    return default
                try:
                    return float(str(s).strip('"'))
                except Exception:
                    return default

            def normalize_title(m):
                """容错提取标题"""
                for key in ("title", "subtitle", "yes_sub_title", "no_sub_title", "ticker"):
                    val = m.get(key)
                    if val and isinstance(val, str) and val.strip():
                        t = val.strip().replace("$", "").strip()
                        return t
                return "Unknown"

            out = []
            for m in markets:
                title = normalize_title(m)
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

            # ---------- 成功：清空 retry_count ----------
            if self.retry_count > 0:
                logging.info(f"[Kalshi] ✅ 请求恢复正常，重试计数清零 (was {self.retry_count})")
            self.retry_count = 0
            return out

        except Exception as e:
            self.retry_count += 1
            self.last_retry_ts = time.time()
            logging.error({
                "source": "Kalshi",
                "error": str(e),
                "retry_count": self.retry_count,
                "time": datetime.now(timezone.utc).isoformat()
            })
            return []

    # ---------- 额外辅助方法 ----------
    def should_extend_interval(self) -> bool:
        """
        主循环可调用，用于判断是否进入冷却期
        """
        # 若最近 5 分钟内有 5 次以上失败，则建议延长间隔
        if self.retry_count >= 5 and (time.time() - self.last_retry_ts < self.cooldown_seconds):
            return True
        return False

    def should_restore_interval(self) -> bool:
        """
        若冷却后恢复成功，重置状态
        """
        if self.retry_count == 0:
            return True
        return False