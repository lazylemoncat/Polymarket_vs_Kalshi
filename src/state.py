from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional
import uuid


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class OpportunityWindow:
    market_pair_id: str
    direction: str
    start_time: datetime
    last_update: datetime
    observation_count: int = 0
    spreads: List[float] = field(default_factory=list)
    peak_spread: float = 0.0
    interrupted: bool = False
    window_id: str = field(default_factory=lambda: uuid.uuid4().hex)

    def update(self, spread: float, timestamp: datetime) -> None:
        self.last_update = timestamp
        self.observation_count += 1
        self.spreads.append(spread)
        if spread > self.peak_spread:
            self.peak_spread = spread

    @property
    def avg_spread(self) -> float:
        if not self.spreads:
            return 0.0
        return sum(self.spreads) / len(self.spreads)

    def to_log_row(self) -> Dict[str, str]:
        end_time = self.last_update.isoformat()
        duration = (self.last_update - self.start_time).total_seconds()
        return {
            "window_id": self.window_id,
            "market_pair": self.market_pair_id,
            "start_time": self.start_time.isoformat(),
            "end_time": end_time,
            "duration_seconds": f"{duration:.2f}",
            "peak_spread": f"{self.peak_spread:.4f}",
            "avg_spread": f"{self.avg_spread:.4f}",
            "direction": self.direction,
            "observation_count": str(self.observation_count),
            "interrupted": "true" if self.interrupted else "false",
        }

    def to_state(self) -> Dict[str, str]:
        return {
            "window_id": self.window_id,
            "market_pair_id": self.market_pair_id,
            "direction": self.direction,
            "start_time": self.start_time.isoformat(),
            "last_update": self.last_update.isoformat(),
            "observation_count": self.observation_count,
            "spreads": self.spreads,
            "peak_spread": self.peak_spread,
            "interrupted": self.interrupted,
        }

    @classmethod
    def from_state(cls, data: Dict[str, object]) -> "OpportunityWindow":
        start = datetime.fromisoformat(data["start_time"])
        last = datetime.fromisoformat(data["last_update"])
        window = cls(
            market_pair_id=data["market_pair_id"],
            direction=data["direction"],
            start_time=start,
            last_update=last,
            window_id=data.get("window_id") or uuid.uuid4().hex,
        )
        window.observation_count = int(data.get("observation_count", 0))
        window.spreads = [float(x) for x in data.get("spreads", [])]
        window.peak_spread = float(data.get("peak_spread", 0.0))
        window.interrupted = bool(data.get("interrupted", False))
        return window


@dataclass
class MarketRuntimeState:
    market_pair_id: str
    kalshi_ticker: str
    polymarket_token: str
    consecutive_failures: int = 0
    status: str = "MONITORING"
    last_error: Optional[str] = None
    last_updated: Optional[datetime] = None
    active_windows: Dict[str, OpportunityWindow] = field(default_factory=dict)

    def mark_failure(self, message: str, timestamp: datetime) -> None:
        self.consecutive_failures += 1
        self.status = "ERROR" if self.consecutive_failures >= 3 else "MONITORING"
        self.last_error = message
        self.last_updated = timestamp

    def mark_success(self, timestamp: datetime) -> None:
        self.consecutive_failures = 0
        self.status = "MONITORING"
        self.last_error = None
        self.last_updated = timestamp

    def activate_window(self, direction: str, timestamp: datetime) -> OpportunityWindow:
        window = OpportunityWindow(
            market_pair_id=self.market_pair_id,
            direction=direction,
            start_time=timestamp,
            last_update=timestamp,
        )
        self.active_windows[direction] = window
        return window

    def deactivate_window(self, direction: str) -> Optional[OpportunityWindow]:
        return self.active_windows.pop(direction, None)


def restore_windows(serialized: List[Dict[str, object]]) -> Dict[str, OpportunityWindow]:
    result: Dict[str, OpportunityWindow] = {}
    for item in serialized:
        window = OpportunityWindow.from_state(item)
        result[window.direction] = window
    return result
