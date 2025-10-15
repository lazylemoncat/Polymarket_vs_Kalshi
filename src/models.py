from dataclasses import dataclass
from typing import List, Optional
import json
import os


@dataclass
class MarketPair:
    id: str
    polymarket_token: str
    kalshi_ticker: str
    market_name: str
    settlement_date: str
    manually_verified: bool
    notes: Optional[str] = None


@dataclass
class MonitoringConfig:
    polling_interval_seconds: int
    monitoring_duration_hours: int


@dataclass
class CostAssumptions:
    gas_fee_per_trade_usd: float


@dataclass
class AlertingConfig:
    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None


@dataclass
class AppConfig:
    market_pairs: List[MarketPair]
    monitoring: MonitoringConfig
    cost_assumptions: CostAssumptions
    alerting: AlertingConfig


def load_config(path: str = "config.json") -> AppConfig:
    """从 JSON 文件加载配置并转换为 AppConfig 对象"""
    if not os.path.exists(path):
        raise FileNotFoundError(f"配置文件未找到：{path}")

    with open(path, "r", encoding="utf-8") as f:
        raw = json.load(f)

    # 解析各部分结构
    market_pairs = [MarketPair(**mp) for mp in raw.get("market_pairs", [])]
    monitoring = MonitoringConfig(**raw["monitoring"])
    cost_assumptions = CostAssumptions(**raw["cost_assumptions"])
    alerting = AlertingConfig(**raw["alerting"])

    return AppConfig(
        market_pairs=market_pairs,
        monitoring=monitoring,
        cost_assumptions=cost_assumptions,
        alerting=alerting
    )



if __name__ == "__main__":
    try:
        config = load_config("config.example.json")
        print("Config loaded successfully!")
        print(f"Markets loaded: {[m.market_name for m in config.market_pairs]}")
        print(f"Polling interval: {config.monitoring.polling_interval_seconds}s")
    except Exception as e:
        print(f"Failed to load config: {e}")
