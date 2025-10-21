"""Configuration loader that maps JSON input into typed data classes."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from models import (
    AppConfig,
    CostAssumptions,
    MarketPair,
    MonitoringConfig,
    TelegramSettings,
)


def _require(obj: dict[str, Any], keys: Iterable[str], context: str) -> None:
    missing = [key for key in keys if key not in obj]
    if missing:
        joined = ", ".join(sorted(missing))
        raise ValueError(f"{context} missing required field(s): {joined}")


def _load_market_pairs(raw_pairs: Any) -> list[MarketPair]:
    if not isinstance(raw_pairs, list) or not raw_pairs:
        raise ValueError("`market_pairs` must be a non-empty list")

    pairs: list[MarketPair] = []
    for idx, entry in enumerate(raw_pairs, start=1):
        if not isinstance(entry, dict):
            raise ValueError(f"market_pairs[{idx}] must be an object")

        _require(
            entry,
            (
                "id",
                "market_name",
                "polymarket_token",
                "polymarket_market_id",
                "kalshi_ticker",
                "kalshi_market_id",
                "settlement_date",
            ),
            f"market_pairs[{idx}]",
        )

        pairs.append(
            MarketPair(
                id=str(entry["id"]),
                market_name=str(entry["market_name"]),
                polymarket_token=str(entry["polymarket_token"]),
                polymarket_market_id=str(entry["polymarket_market_id"]),
                kalshi_ticker=str(entry["kalshi_ticker"]),
                kalshi_market_id=str(entry["kalshi_market_id"]),
                settlement_date=str(entry["settlement_date"]),
                manually_verified=bool(entry.get("manually_verified", False)),
                notes=entry.get("notes") or None,
                polymarket_title=entry.get("polymarket_title") or None,
                kalshi_title=entry.get("kalshi_title") or None,
            )
        )

    return pairs


def _load_monitoring(raw_monitoring: Any) -> MonitoringConfig:
    if not isinstance(raw_monitoring, dict):
        raise ValueError("`monitoring` must be an object")

    if "monitoring_duration_hours" not in raw_monitoring and "duration_hours" in raw_monitoring:
        raw_monitoring["monitoring_duration_hours"] = raw_monitoring.pop("duration_hours")

    _require(
        raw_monitoring,
        ("polling_interval_seconds", "monitoring_duration_hours"),
        "monitoring",
    )

    try:
        interval = int(raw_monitoring["polling_interval_seconds"])
        duration = int(raw_monitoring["monitoring_duration_hours"])
    except (TypeError, ValueError) as exc:
        raise ValueError("monitoring values must be integers") from exc

    if interval <= 0:
        raise ValueError("monitoring.polling_interval_seconds must be > 0")
    if duration <= 0:
        raise ValueError("monitoring.monitoring_duration_hours must be > 0")

    return MonitoringConfig(
        polling_interval_seconds=interval,
        monitoring_duration_hours=duration,
    )


def _load_cost_assumptions(raw_cost: Any) -> CostAssumptions:
    if not isinstance(raw_cost, dict):
        raise ValueError("`cost_assumptions` must be an object")

    _require(raw_cost, ("gas_fee_per_trade_usd",), "cost_assumptions")

    try:
        gas_fee = float(raw_cost["gas_fee_per_trade_usd"])
    except (TypeError, ValueError) as exc:
        raise ValueError("gas_fee_per_trade_usd must be a number") from exc

    if gas_fee < 0:
        raise ValueError("gas_fee_per_trade_usd must be ≥ 0")

    return CostAssumptions(gas_fee_per_trade_usd=gas_fee)


def _load_telegram(raw_cfg: dict[str, Any]) -> TelegramSettings:
    if "telegram" in raw_cfg and isinstance(raw_cfg["telegram"], dict):
        tele = raw_cfg["telegram"]
        return TelegramSettings(
            bot_token=tele.get("bot_token") or tele.get("token"),
            chat_id=tele.get("chat_id"),
        )

    return TelegramSettings(
        bot_token=raw_cfg.get("telegram_bot_token"),
        chat_id=raw_cfg.get("telegram_chat_id"),
    )


def load_config(path: str = "config.json") -> AppConfig:
    config_path = Path(path)
    with config_path.open("r", encoding="utf-8") as handle:
        raw: dict[str, Any] = json.load(handle)

    if "market_pairs" not in raw:
        raise ValueError("Missing top-level key: market_pairs")

    market_pairs = _load_market_pairs(raw["market_pairs"])
    monitoring = _load_monitoring(raw.get("monitoring"))
    cost_assumptions = _load_cost_assumptions(raw.get("cost_assumptions"))
    telegram = _load_telegram(raw)

    return AppConfig(
        market_pairs=market_pairs,
        monitoring=monitoring,
        cost_assumptions=cost_assumptions,
        telegram=telegram,
        kalshi_api_key=raw.get("kalshi_api_key"),
    )
