"""Main entrypoint for the Polymarket vs. Kalshi arbitrage monitor."""

from __future__ import annotations

import asyncio
import json
import logging
import math
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable, Optional, Sequence

from rich import box
from rich.console import Console
from rich.live import Live
from rich.table import Table

from logger_setup import setup_logging
from models import AppConfig, MarketPair, TelegramSettings
from monitor_windows import OpportunityWindowManager
from utils import config_loader
from utils.fees import kalshi_fee
from utils.kalshi_client import KalshiClient
from utils.polymarket_client import PolymarketClient
from utils.telegramNotifier import TelegramNotifier

setup_logging()
LOGGER = logging.getLogger("monitor")
CONSOLE = Console()


class SnapshotStatus(Enum):
    """Simple lifecycle states for the snapshot table."""

    FAILED = "Failed"
    SKIPPED = "Skipped"
    IDLE = "Idle"
    OPEN = "Open"

    @property
    def rich_label(self) -> str:
        mapping = {
            SnapshotStatus.FAILED: "[red]❌ Failed",
            SnapshotStatus.SKIPPED: "[yellow]Skipped",
            SnapshotStatus.IDLE: "[dim]Idle",
            SnapshotStatus.OPEN: "[green]Open",
        }
        return mapping[self]


@dataclass(slots=True)
class SnapshotRow:
    pair: MarketPair
    status: SnapshotStatus
    buy_k_sell_p: Optional[float] = None
    buy_p_sell_k: Optional[float] = None
    poly_bid: Optional[float] = None
    poly_ask: Optional[float] = None
    kalshi_bid: Optional[float] = None
    kalshi_ask: Optional[float] = None

    def to_log_dict(self) -> dict[str, object]:
        return {
            "pair_id": self.pair.id,
            "market": self.pair.market_name,
            "k_to_p": None if self.buy_k_sell_p is None else round(self.buy_k_sell_p, 4),
            "p_to_k": None if self.buy_p_sell_k is None else round(self.buy_p_sell_k, 4),
            "status": self.status.value,
        }

    def table_values(self) -> tuple[str, str, str, str, str]:
        def fmt(value: Optional[float]) -> str:
            return "-" if value is None else f"{value:.3f}"

        return (
            self.pair.id,
            self.pair.market_name,
            fmt(self.buy_k_sell_p),
            fmt(self.buy_p_sell_k),
            self.status.rich_label,
        )


@dataclass(slots=True)
class ArbitrageSignal:
    pair: MarketPair
    poly_market_id: str
    kalshi_market_id: str
    poly_bid: float
    poly_ask: float
    kalshi_bid: float
    kalshi_ask: float
    buy_k_sell_p: float
    buy_p_sell_k: float

    def to_payload(self) -> dict[str, object]:
        return {
            "pair_id": self.pair.id,
            "market_pair": self.pair.market_name,
            "polymarket_market_id": self.poly_market_id,
            "kalshi_market_id": self.kalshi_market_id,
            "poly_bid": round(self.poly_bid, 4),
            "poly_ask": round(self.poly_ask, 4),
            "kalshi_bid": round(self.kalshi_bid, 4),
            "kalshi_ask": round(self.kalshi_ask, 4),
            "net_spread_buy_K_sell_P": round(self.buy_k_sell_p, 4),
            "net_spread_buy_P_sell_K": round(self.buy_p_sell_k, 4),
        }


@dataclass(slots=True)
class FailureTracker:
    threshold: int = 3
    counts: dict[str, int] = field(default_factory=dict)

    def record_failure(self, key: str) -> None:
        failures = self.counts.get(key, 0) + 1
        if failures >= self.threshold:
            LOGGER.error(
                json.dumps(
                    {
                        "source": key,
                        "error": "连续3次数据获取失败",
                        "time": utc_now_iso(),
                    },
                    ensure_ascii=False,
                )
            )
            self.counts[key] = 0
        else:
            self.counts[key] = failures

    def record_success(self, key: str) -> None:
        self.counts.pop(key, None)


def normalize_title(title: str | None) -> str:
    if not title:
        return ""
    normalised = title.strip().lower()
    for needle, replacement in {"–": "-", "—": "-", "°f": "°", " °": "°"}.items():
        normalised = normalised.replace(needle, replacement)
    return " ".join(normalised.split())


def utc_now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class ArbitrageMonitor:
    """Coordinates fetching, evaluation, and notifications for all market pairs."""

    POLYMARKET_API = "https://gamma-api.polymarket.com"
    KALSHI_API = "https://api.elections.kalshi.com/trade-api/v2"

    def __init__(self, config: AppConfig):
        self.config = config
        interval = config.monitoring.polling_interval_seconds
        self.poly_client = PolymarketClient(base_url=self.POLYMARKET_API, polling_interval=interval)
        self.kalshi_client = KalshiClient(
            base_url=self.KALSHI_API,
            polling_interval=interval,
            api_key=config.kalshi_api_key,
        )
        self.window_manager = OpportunityWindowManager()
        self.failure_tracker = FailureTracker()
        self.notifier = self._build_notifier(config.telegram)

    @staticmethod
    def _build_notifier(settings: TelegramSettings | None) -> TelegramNotifier | None:
        try:
            if settings and settings.is_configured:
                notifier = TelegramNotifier(token=settings.bot_token, chat_id=settings.chat_id)
                LOGGER.info("📨 已启用 Telegram 通知。")
                return notifier
            LOGGER.warning("⚠️ 未配置 Telegram 通知凭据。")
        except ValueError as exc:
            LOGGER.warning("⚠️ Telegram 通知不可用：%s", exc)
        return None

    async def run(self) -> None:
        LOGGER.info("🚀 启动套利监控系统...")
        self.window_manager.load_or_recover()

        interval = self.config.monitoring.polling_interval_seconds
        base_interval = interval
        duration_hours = self.config.monitoring.monitoring_duration_hours
        start_time = time.time()
        extended = False

        LOGGER.info("轮询间隔: %ss | 持续时长: %sh", interval, duration_hours)

        with Live(console=CONSOLE, refresh_per_second=4) as live:
            while True:
                table = await self._run_iteration()
                live.update(table)

                elapsed_hours = (time.time() - start_time) / 3600
                if elapsed_hours >= duration_hours:
                    LOGGER.info("⏹ 达到配置的监控时长 (%sh)，自动退出。", duration_hours)
                    break

                interval, extended = self._maybe_adjust_interval(interval, base_interval, extended)
                await asyncio.sleep(interval)

        LOGGER.info("✅ 监控任务已结束。")

    async def _run_iteration(self) -> Table:
        snapshots: list[SnapshotRow] = []
        signals: list[ArbitrageSignal] = []

        for pair in self.config.market_pairs:
            snapshot, signal = self._evaluate_pair(pair)
            snapshots.append(snapshot)
            if signal:
                signals.append(signal)

        self.window_manager.maybe_checkpoint()
        self._log_snapshot(snapshots)

        for signal in signals:
            await self._emit_signal(signal)

        return self._build_table(snapshots)

    def _evaluate_pair(self, pair: MarketPair) -> tuple[SnapshotRow, Optional[ArbitrageSignal]]:
        poly_markets = self.poly_client.fetch_event_markets(pair.polymarket_token)
        kalshi_markets = self.kalshi_client.fetch_event_markets(pair.kalshi_ticker)

        if not poly_markets or not kalshi_markets:
            self.failure_tracker.record_failure(pair.id)
            return SnapshotRow(pair=pair, status=SnapshotStatus.FAILED), None

        self.failure_tracker.record_success(pair.id)

        poly_market = self._find_market(
            poly_markets,
            target_id=pair.polymarket_market_id,
            fallback_title=pair.polymarket_title or pair.market_name,
            id_key="id",
        )
        kalshi_market = self._find_market(
            kalshi_markets,
            target_id=pair.kalshi_market_id,
            fallback_title=pair.kalshi_title or pair.market_name,
            id_key="ticker",
        )

        if not poly_market or not kalshi_market:
            return SnapshotRow(pair=pair, status=SnapshotStatus.SKIPPED), None

        poly_bid, poly_ask = poly_market["bid"], poly_market["ask"]
        kalshi_bid, kalshi_ask = kalshi_market["bid"], kalshi_market["ask"]

        fee_component = round(kalshi_fee(kalshi_bid) * 2, 4)
        total_cost = self.config.cost_assumptions.gas_fee_per_trade_usd + fee_component

        buy_k_sell_p = poly_bid - kalshi_ask - total_cost
        buy_p_sell_k = kalshi_bid - poly_ask - total_cost

        timestamp = utc_now_iso()
        self.window_manager.write_snapshot(
            pair.market_name,
            kalshi_bid,
            kalshi_ask,
            poly_bid,
            poly_ask,
            total_cost,
            buy_k_sell_p,
            buy_p_sell_k,
            timestamp,
        )

        pair_key = f"{pair.id}::{pair.kalshi_market_id}::{pair.polymarket_market_id}"
        opened = False

        if buy_k_sell_p > 0:
            self.window_manager.open_or_update(pair_key, "K_to_P", pair.market_name, buy_k_sell_p, timestamp)
            opened = True
        else:
            self.window_manager.close_if_open(pair_key, "K_to_P", timestamp)

        if buy_p_sell_k > 0:
            self.window_manager.open_or_update(pair_key, "P_to_K", pair.market_name, buy_p_sell_k, timestamp)
            opened = True
        else:
            self.window_manager.close_if_open(pair_key, "P_to_K", timestamp)

        snapshot = SnapshotRow(
            pair=pair,
            status=SnapshotStatus.OPEN if opened else SnapshotStatus.IDLE,
            buy_k_sell_p=buy_k_sell_p,
            buy_p_sell_k=buy_p_sell_k,
            poly_bid=poly_bid,
            poly_ask=poly_ask,
            kalshi_bid=kalshi_bid,
            kalshi_ask=kalshi_ask,
        )

        if not opened:
            return snapshot, None

        signal = ArbitrageSignal(
            pair=pair,
            poly_market_id=pair.polymarket_market_id,
            kalshi_market_id=pair.kalshi_market_id,
            poly_bid=poly_bid,
            poly_ask=poly_ask,
            kalshi_bid=kalshi_bid,
            kalshi_ask=kalshi_ask,
            buy_k_sell_p=buy_k_sell_p,
            buy_p_sell_k=buy_p_sell_k,
        )
        return snapshot, signal

    def _find_market(
        self,
        markets: Iterable[dict],
        *,
        target_id: str,
        fallback_title: str,
        id_key: str,
    ) -> Optional[dict]:
        if not target_id:
            return None

        normalized_target = str(target_id).lower()
        for market in markets:
            raw = market.get("raw") or {}
            candidate = raw.get(id_key) or market.get(id_key)
            if candidate is not None and str(candidate).lower() == normalized_target:
                return market

        fallback_normalised = normalize_title(fallback_title)
        if not fallback_normalised:
            return None

        for market in markets:
            if normalize_title(market.get("title")) == fallback_normalised:
                return market
        return None

    async def _emit_signal(self, signal: ArbitrageSignal) -> None:
        payload = signal.to_payload() | {"timestamp": utc_now_iso()}
        LOGGER.info(json.dumps({"type": "arbitrage_signal", **payload}, ensure_ascii=False))

        if not self.notifier:
            return

        message = (
            "⚡ *套利机会！*\n"
            f"市场对: {payload['market_pair']} (ID: {payload['pair_id']})\n"
            f"Poly 市场: {payload['polymarket_market_id']}\n"
            f"Kalshi 市场: {payload['kalshi_market_id']}\n"
            f"Poly: {payload['poly_bid']}/{payload['poly_ask']}\n"
            f"Kalshi: {payload['kalshi_bid']}/{payload['kalshi_ask']}\n"
            f"K→P: {payload['net_spread_buy_K_sell_P']}, P→K: {payload['net_spread_buy_P_sell_K']}"
        )

        try:
            await self.notifier.send_message(message, parse_mode="Markdown")
        except Exception:  # noqa: BLE001
            LOGGER.exception(
                json.dumps(
                    {
                        "source": "telegram",
                        "error": "发送通知失败",
                        "time": utc_now_iso(),
                    },
                    ensure_ascii=False,
                )
            )

    def _log_snapshot(self, rows: Sequence[SnapshotRow]) -> None:
        LOGGER.info(
            json.dumps(
                {
                    "type": "monitor_snapshot",
                    "generated_at": utc_now_iso(),
                    "rows": [row.to_log_dict() for row in rows],
                },
                ensure_ascii=False,
            )
        )

    def _build_table(self, rows: Sequence[SnapshotRow]) -> Table:
        table = Table(title="Arbitrage Monitor Snapshot", box=box.MINIMAL_DOUBLE_HEAD)
        table.add_column("Pair ID", justify="left")
        table.add_column("Market", justify="left")
        table.add_column("K→P", justify="right")
        table.add_column("P→K", justify="right")
        table.add_column("Status", justify="center")

        for row in rows:
            table.add_row(*row.table_values())
        return table

    def _maybe_adjust_interval(self, current: int, base: int, extended: bool) -> tuple[int, bool]:
        if self.kalshi_client.should_extend_interval() and not extended:
            new_interval = max(base, math.ceil(current * 1.5))
            LOGGER.warning("⚠️ 检测到频繁429，临时延长轮询间隔至 %ss", new_interval)
            return new_interval, True

        if extended and self.kalshi_client.retry_count == 0:
            LOGGER.info("✅ 已恢复正常轮询频率")
            return base, False

        return current, extended


def main() -> None:
    config = config_loader.load_config()
    monitor = ArbitrageMonitor(config)
    asyncio.run(monitor.run())


if __name__ == "__main__":
    main()
