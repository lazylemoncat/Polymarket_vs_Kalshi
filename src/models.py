"""Lightweight data models used across the arbitrage monitor."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass(slots=True)
class MarketPair:
    """Represents a Polymarket/Kalshi market mapping defined in the config file."""

    id: str
    market_name: str
    polymarket_token: str
    polymarket_market_id: str
    kalshi_ticker: str
    kalshi_market_id: str
    settlement_date: str
    manually_verified: bool = False
    notes: Optional[str] = None
    polymarket_title: Optional[str] = None
    kalshi_title: Optional[str] = None


@dataclass(slots=True)
class MonitoringConfig:
    polling_interval_seconds: int
    monitoring_duration_hours: int


@dataclass(slots=True)
class CostAssumptions:
    gas_fee_per_trade_usd: float


@dataclass(slots=True)
class TelegramSettings:
    """Optional credentials used for Telegram notifications."""

    bot_token: Optional[str] = None
    chat_id: Optional[str] = None

    @property
    def is_configured(self) -> bool:
        return bool(self.bot_token and self.chat_id)


@dataclass(slots=True)
class AppConfig:
    market_pairs: list[MarketPair]
    monitoring: MonitoringConfig
    cost_assumptions: CostAssumptions
    telegram: TelegramSettings
    kalshi_api_key: Optional[str] = None
