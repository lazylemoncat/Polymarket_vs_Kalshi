import json
import os
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


logger = logging.getLogger(__name__)


@dataclass
class MarketPair:
    """Legacy structure that older scripts still import."""

    id: str
    polymarket_token: str
    kalshi_ticker: str
    market_name: str
    settlement_date: str
    manually_verified: bool
    notes: Optional[str] = None


@dataclass
class MarketMapping:
    polymarket_title: str
    kalshi_title: str


@dataclass
class EventPair:
    id: str
    name: str
    polymarket_event_id: str
    kalshi_event_ticker: str
    settlement_date: str
    manually_verified: bool
    markets_map: List[MarketMapping] = field(default_factory=list)
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
    enabled: bool = False
    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None


@dataclass
class AppConfig:
    event_pairs: List[EventPair]
    monitoring: MonitoringConfig
    cost_assumptions: CostAssumptions
    alerting: AlertingConfig
    kalshi_api_key: Optional[str] = None
    legacy_market_pairs: List[MarketPair] = field(default_factory=list)


def _ensure_keys(data: Dict[str, Any], required: List[str], context: str) -> None:
    missing = [key for key in required if key not in data]
    if missing:
        joined = ", ".join(missing)
        raise ValueError(f"{context} is missing required field(s): {joined}")


def load_config(path: str = "config.json") -> AppConfig:
    """Load configuration JSON and map into AppConfig dataclasses."""
    if not os.path.exists(path):
        raise FileNotFoundError(f"Config file not found: {path}")

    with open(path, "r", encoding="utf-8") as handle:
        raw: Dict[str, Any] = json.load(handle)

    event_pairs_data = raw.get("event_pairs") or []
    if not event_pairs_data:
        raise ValueError("Config must include a non-empty `event_pairs` list.")

    event_pairs: List[EventPair] = []
    for index, ep in enumerate(event_pairs_data, start=1):
        context = f"event_pairs[{index}]"
        _ensure_keys(
            ep,
            ["id", "name", "polymarket_event_id", "kalshi_event_ticker", "settlement_date"],
            context,
        )

        markets_raw = ep.get("markets_map")
        if not isinstance(markets_raw, list) or not markets_raw:
            raise ValueError(f"{context} `markets_map` must be a non-empty list.")

        markets_map: List[MarketMapping] = []
        for map_index, item in enumerate(markets_raw, start=1):
            item_context = f"{context}.markets_map[{map_index}]"
            _ensure_keys(item, ["polymarket_title", "kalshi_title"], item_context)
            markets_map.append(
                MarketMapping(
                    polymarket_title=str(item["polymarket_title"]),
                    kalshi_title=str(item["kalshi_title"]),
                )
            )

        event_pairs.append(
            EventPair(
                id=str(ep["id"]),
                name=str(ep["name"]),
                polymarket_event_id=str(ep["polymarket_event_id"]),
                kalshi_event_ticker=str(ep["kalshi_event_ticker"]),
                settlement_date=str(ep["settlement_date"]),
                manually_verified=bool(ep.get("manually_verified", False)),
                markets_map=markets_map,
                notes=ep.get("notes"),
            )
        )

    monitoring_data = raw.get("monitoring") or {}
    _ensure_keys(
        monitoring_data,
        ["polling_interval_seconds", "monitoring_duration_hours"],
        "monitoring",
    )
    monitoring = MonitoringConfig(
        polling_interval_seconds=int(monitoring_data["polling_interval_seconds"]),
        monitoring_duration_hours=int(monitoring_data["monitoring_duration_hours"]),
    )

    cost_data = raw.get("cost_assumptions") or {}
    _ensure_keys(cost_data, ["gas_fee_per_trade_usd"], "cost_assumptions")
    cost_assumptions = CostAssumptions(
        gas_fee_per_trade_usd=float(cost_data["gas_fee_per_trade_usd"])
    )

    alerting_data = raw.get("alerting") or {}
    alerting = AlertingConfig(
        enabled=bool(alerting_data.get("enabled", False)),
        telegram_bot_token=alerting_data.get("telegram_bot_token"),
        telegram_chat_id=alerting_data.get("telegram_chat_id"),
    )

    legacy_market_pairs = [
        MarketPair(**item) for item in raw.get("market_pairs", [])
    ]

    return AppConfig(
        event_pairs=event_pairs,
        monitoring=monitoring,
        cost_assumptions=cost_assumptions,
        alerting=alerting,
        kalshi_api_key=raw.get("kalshi_api_key"),
        legacy_market_pairs=legacy_market_pairs,
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    try:
        cfg = load_config("config.json")
        logger.info("Config loaded successfully.")
        logger.info("Loaded %d event pair(s).", len(cfg.event_pairs))
        logger.info(
            "Polling interval: %ss",
            cfg.monitoring.polling_interval_seconds,
        )
    except Exception:
        logger.exception("Failed to load config")
