from __future__ import annotations

import argparse
import csv
import math
import json
import signal
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Optional, Tuple

import requests
from rich.console import Console
from rich.live import Live
from rich.table import Table

from models import AppConfig, MarketPair, load_config
from clients import KalshiClient, PolymarketClient, Quote, QuoteResponse
from state import MarketRuntimeState, OpportunityWindow, restore_windows, utc_now


console = Console()


@dataclass
class MarketObservation:
    timestamp: datetime
    market_pair: MarketPair
    kalshi_quote: Quote
    polymarket_quote: Quote
    total_cost_buy_k: float
    total_cost_sell_k: float
    net_spread_sell_p_buy_k: float
    net_spread_sell_k_buy_p: float


class TelegramAlerter:
    def __init__(self, token: Optional[str], chat_id: Optional[str], timeout: float = 10.0) -> None:
        self.token = token
        self.chat_id = chat_id
        self.timeout = timeout

    def is_configured(self) -> bool:
        return bool(self.token and self.chat_id)

    def send(self, message: str) -> None:
        if not self.is_configured():
            return
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        payload = {"chat_id": self.chat_id, "text": message}
        try:
            requests.post(url, json=payload, timeout=self.timeout)
        except requests.RequestException:
            console.log("[yellow]Failed to send Telegram alert[/yellow]")


class RateLimiter:
    def __init__(self, initial_interval: float) -> None:
        self.initial_interval = initial_interval
        self.current_interval = float(initial_interval)
        self._recent_429: list[datetime] = []
        self._last_429_time: Optional[datetime] = None
        self._last_cooldown_adjust: Optional[datetime] = None
        self._last_alert_time: Optional[datetime] = None

    def register_429(self, now: datetime) -> Tuple[int, bool]:
        self._last_429_time = now
        self._recent_429.append(now)
        thirty_minutes_ago = now - timedelta(minutes=30)
        self._recent_429 = [t for t in self._recent_429 if t >= thirty_minutes_ago]
        occurrences = len(self._recent_429)

        if occurrences == 1:
            wait = 30
            self.current_interval *= 1.5
        elif occurrences == 2:
            wait = 60
            self.current_interval *= 2
        else:
            wait = 120
            self.current_interval *= 2

        should_alert = occurrences >= 3 and (
            self._last_alert_time is None or (now - self._last_alert_time).total_seconds() >= 60
        )
        if should_alert:
            self._last_alert_time = now

        # reset cooldown counters after each 429
        self._last_cooldown_adjust = None
        return wait, should_alert

    def maybe_cooldown(self, now: datetime) -> None:
        if self._last_429_time is None:
            return
        time_since_last_429 = now - self._last_429_time
        if time_since_last_429 < timedelta(minutes=30):
            return
        if self.current_interval <= self.initial_interval:
            self.current_interval = self.initial_interval
            return
        if self._last_cooldown_adjust and (now - self._last_cooldown_adjust) < timedelta(minutes=10):
            return

        reduction = self.current_interval * 0.1
        new_interval = self.current_interval - reduction
        if new_interval <= self.initial_interval:
            self.current_interval = self.initial_interval
        else:
            self.current_interval = new_interval
        self._last_cooldown_adjust = now


class Monitor:
    STATUS_MONITORING = "🟡 MONITORING"
    STATUS_OPPORTUNITY = "🟢 OPPORTUNITY"
    STATUS_ERROR = "🔴 ERROR"

    DIR_SELL_P_BUY_K = "SELL_P_BUY_K"
    DIR_SELL_K_BUY_P = "SELL_K_BUY_P"

    def __init__(self, config: AppConfig, log_dir: Path) -> None:
        self.config = config
        self.log_dir = log_dir
        self.log_dir.mkdir(parents=True, exist_ok=True)

        self.price_snapshots_path = self.log_dir / "price_snapshots.csv"
        self.opportunity_windows_path = self.log_dir / "opportunity_windows.csv"
        self.errors_log_path = self.log_dir / "errors.log"
        self.window_state_path = self.log_dir / "window_state.json"

        self.polymarket_client = PolymarketClient()
        self.kalshi_client = KalshiClient()
        self.rate_limiter = RateLimiter(config.monitoring.polling_interval_seconds)
        self.alerter = TelegramAlerter(
            token=config.alerting.telegram_bot_token,
            chat_id=config.alerting.telegram_chat_id,
        )

        self.market_states: Dict[str, MarketRuntimeState] = {
            pair.id: MarketRuntimeState(
                market_pair_id=pair.id,
                kalshi_ticker=pair.kalshi_ticker,
                polymarket_token=pair.polymarket_token,
            )
            for pair in config.market_pairs
        }
        self.latest_observations: Dict[str, Optional[MarketObservation]] = {
            pair.id: None for pair in config.market_pairs
        }

        self._setup_logs()
        self._restore_previous_state()

    def _setup_logs(self) -> None:
        if not self.price_snapshots_path.exists():
            with self.price_snapshots_path.open("w", encoding="utf-8", newline="") as fh:
                writer = csv.writer(fh)
                writer.writerow(
                    [
                        "timestamp",
                        "market_pair",
                        "kalshi_bid",
                        "kalshi_ask",
                        "poly_bid",
                        "poly_ask",
                        "total_cost",
                        "net_spread_K_to_P",
                        "net_spread_P_to_K",
                    ]
                )
        if not self.opportunity_windows_path.exists():
            with self.opportunity_windows_path.open("w", encoding="utf-8", newline="") as fh:
                writer = csv.writer(fh)
                writer.writerow(
                    [
                        "window_id",
                        "market_pair",
                        "start_time",
                        "end_time",
                        "duration_seconds",
                        "peak_spread",
                        "avg_spread",
                        "direction",
                        "observation_count",
                        "interrupted",
                    ]
                )

    def _restore_previous_state(self) -> None:
        if not self.window_state_path.exists():
            return
        try:
            with self.window_state_path.open("r", encoding="utf-8") as fh:
                raw = json.load(fh)
        except (json.JSONDecodeError, OSError):
            return

        last_updated_str = raw.get("last_updated")
        active_windows = raw.get("active_windows", [])
        if not last_updated_str:
            return

        try:
            last_updated = datetime.fromisoformat(last_updated_str)
        except ValueError:
            return

        now = utc_now()
        restored = restore_windows(active_windows)
        if (now - last_updated) <= timedelta(minutes=5):
            for direction, window in restored.items():
                state = self.market_states.get(window.market_pair_id)
                if state:
                    state.active_windows[direction] = window
        else:
            for _, window in restored.items():
                window.interrupted = True
                self._write_opportunity_window(window)
            # reset persisted state after writing interrupted windows
            self._save_window_state({})

    def _save_window_state(self, active_windows_override: Optional[Dict[str, Dict[str, OpportunityWindow]]] = None) -> None:
        payload = {
            "last_updated": utc_now().isoformat(),
            "active_windows": [],
        }
        if active_windows_override is None:
            for state in self.market_states.values():
                for window in state.active_windows.values():
                    payload["active_windows"].append(window.to_state())
        else:
            for windows in active_windows_override.values():
                for window in windows.values():
                    payload["active_windows"].append(window.to_state())
        with self.window_state_path.open("w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)

    def run(self) -> None:
        start_time = utc_now()
        duration_hours = self.config.monitoring.monitoring_duration_hours
        stop_after: Optional[datetime] = (
            start_time + timedelta(hours=duration_hours) if duration_hours > 0 else None
        )
        checkpoint_due = start_time + timedelta(minutes=5)

        with Live(self._build_table(), console=console, refresh_per_second=4) as live:
            while True:
                loop_start = time.perf_counter()
                now = utc_now()
                if stop_after and now >= stop_after:
                    console.log("[green]Monitoring duration reached. Exiting.[/green]")
                    break

                for pair in self.config.market_pairs:
                    observation = self._poll_market(pair, now)
                    if observation:
                        self.latest_observations[pair.id] = observation
                        self._write_snapshot(observation)
                        self._update_windows(pair.id, observation)

                live.update(self._build_table())

                if now >= checkpoint_due:
                    self._save_window_state()
                    checkpoint_due = now + timedelta(minutes=5)

                self.rate_limiter.maybe_cooldown(utc_now())

                elapsed = time.perf_counter() - loop_start
                sleep_for = max(self.rate_limiter.current_interval - elapsed, 0.1)
                time.sleep(sleep_for)

    def _poll_market(self, pair: MarketPair, timestamp: datetime) -> Optional[MarketObservation]:
        state = self.market_states[pair.id]

        kalshi_resp = self.kalshi_client.get_quote(pair.kalshi_ticker)
        if self._handle_rate_limit(kalshi_resp):
            self._log_error(pair.id, "kalshi", kalshi_resp, "rate_limit")
            return None

        polymer_resp = self.polymarket_client.get_quote(pair.polymarket_token)
        if self._handle_rate_limit(polymer_resp):
            self._log_error(pair.id, "polymarket", polymer_resp, "rate_limit")
            return None

        if not kalshi_resp.ok:
            self._log_error(pair.id, "kalshi", kalshi_resp, "fetch_failed")
            state.mark_failure(kalshi_resp.error or "Kalshi fetch failed", timestamp)
            return None

        if not polymer_resp.ok:
            self._log_error(pair.id, "polymarket", polymer_resp, "fetch_failed")
            state.mark_failure(polymer_resp.error or "Polymarket fetch failed", timestamp)
            return None

        if not self._validate_quote(kalshi_resp.quote, "kalshi", pair, timestamp):
            state.mark_failure("Invalid Kalshi quote", timestamp)
            return None
        if not self._validate_quote(polymer_resp.quote, "polymarket", pair, timestamp):
            state.mark_failure("Invalid Polymarket quote", timestamp)
            return None

        state.mark_success(timestamp)

        kalshi_bid, kalshi_ask = kalshi_resp.quote.as_tuple()
        poly_bid, poly_ask = polymer_resp.quote.as_tuple()

        kalshi_fee_buy = self._kalshi_total_fee(kalshi_ask)
        kalshi_fee_sell = self._kalshi_total_fee(kalshi_bid)

        spread_poly = poly_ask - poly_bid
        gas_total = self.config.cost_assumptions.gas_fee_per_trade_usd * 2

        cost_buy_k = kalshi_fee_buy + spread_poly + gas_total
        cost_sell_k = kalshi_fee_sell + spread_poly + gas_total

        net_sell_p_buy_k = poly_bid - kalshi_ask - cost_buy_k
        net_sell_k_buy_p = kalshi_bid - poly_ask - cost_sell_k

        observation = MarketObservation(
            timestamp=timestamp,
            market_pair=pair,
            kalshi_quote=kalshi_resp.quote,
            polymarket_quote=polymer_resp.quote,
            total_cost_buy_k=cost_buy_k,
            total_cost_sell_k=cost_sell_k,
            net_spread_sell_p_buy_k=net_sell_p_buy_k,
            net_spread_sell_k_buy_p=net_sell_k_buy_p,
        )

        if net_sell_p_buy_k > 0 or net_sell_k_buy_p > 0:
            state.status = "OPPORTUNITY"
        else:
            state.status = "MONITORING"

        return observation

    def _handle_rate_limit(self, response: QuoteResponse) -> bool:
        if response.status_code == 429:
            wait, should_alert = self.rate_limiter.register_429(utc_now())
            console.log(f"[yellow]Received 429 -> sleeping additional {wait}s[/yellow]")
            if should_alert and self.alerter.is_configured():
                self.alerter.send("⚠️ Rate limit triggered three times within 30 minutes.")
            time.sleep(wait)
            return True
        return False

    def _validate_quote(self, quote: Optional[Quote], source: str, pair: MarketPair, timestamp: datetime) -> bool:
        if quote is None:
            self._log_validation_error(pair.id, source, "missing_quote", "Quote object is None")
            return False
        bid, ask = quote.as_tuple()
        if bid is None or ask is None:
            self._log_validation_error(pair.id, source, "missing_fields", "Bid/ask missing")
            return False
        if not (0.01 <= bid <= 0.99) or not (0.01 <= ask <= 0.99):
            self._log_validation_error(pair.id, source, "price_out_of_bounds", f"bid={bid}, ask={ask}")
            return False
        if bid > ask:
            self._log_validation_error(pair.id, source, "bid_gt_ask", f"bid={bid}, ask={ask}")
            return False
        if quote.source_timestamp:
            delta = abs((timestamp - quote.source_timestamp).total_seconds())
            if delta > 10:
                self._log_validation_error(
                    pair.id,
                    source,
                    "stale_timestamp",
                    f"delta={delta:.2f}s",
                )
                return False
        else:
            self._log_validation_error(pair.id, source, "missing_timestamp", "No timestamp provided")
            return False
        return True

    def _kalshi_total_fee(self, price: float) -> float:
        fee_raw = 0.07 * price * (1 - price) * 100
        fee_per_trade = math.ceil(fee_raw) / 100
        total_fee = fee_per_trade * 2
        return float(total_fee)

    def _write_snapshot(self, observation: MarketObservation) -> None:
        with self.price_snapshots_path.open("a", encoding="utf-8", newline="") as fh:
            writer = csv.writer(fh)
            writer.writerow(
                [
                    observation.timestamp.isoformat(),
                    observation.market_pair.id,
                    f"{observation.kalshi_quote.bid:.4f}",
                    f"{observation.kalshi_quote.ask:.4f}",
                    f"{observation.polymarket_quote.bid:.4f}",
                    f"{observation.polymarket_quote.ask:.4f}",
                    f"{observation.total_cost_buy_k:.4f}",
                    f"{observation.net_spread_sell_k_buy_p:.4f}",
                    f"{observation.net_spread_sell_p_buy_k:.4f}",
                ]
            )

    def _update_windows(self, market_pair_id: str, observation: MarketObservation) -> None:
        state = self.market_states[market_pair_id]
        timestamp = observation.timestamp

        positive_directions = []
        if observation.net_spread_sell_p_buy_k > 0:
            positive_directions.append((self.DIR_SELL_P_BUY_K, observation.net_spread_sell_p_buy_k))
        if observation.net_spread_sell_k_buy_p > 0:
            positive_directions.append((self.DIR_SELL_K_BUY_P, observation.net_spread_sell_k_buy_p))

        for direction, spread in positive_directions:
            window = state.active_windows.get(direction)
            if window is None:
                window = state.activate_window(direction, timestamp)
            window.update(spread, timestamp)

        for direction in list(state.active_windows.keys()):
            if direction == self.DIR_SELL_P_BUY_K and observation.net_spread_sell_p_buy_k <= 0:
                window = state.deactivate_window(direction)
                if window:
                    self._write_opportunity_window(window)
            if direction == self.DIR_SELL_K_BUY_P and observation.net_spread_sell_k_buy_p <= 0:
                window = state.deactivate_window(direction)
                if window:
                    self._write_opportunity_window(window)

    def _write_opportunity_window(self, window: OpportunityWindow) -> None:
        with self.opportunity_windows_path.open("a", encoding="utf-8", newline="") as fh:
            writer = csv.writer(fh)
            row = window.to_log_row()
            writer.writerow(
                [
                    row["window_id"],
                    row["market_pair"],
                    row["start_time"],
                    row["end_time"],
                    row["duration_seconds"],
                    row["peak_spread"],
                    row["avg_spread"],
                    row["direction"],
                    row["observation_count"],
                    row["interrupted"],
                ]
            )

    def _log_error(self, market_pair_id: str, stage: str, response: QuoteResponse, error_type: str) -> None:
        payload = {
            "timestamp": utc_now().isoformat(),
            "market_pair": market_pair_id,
            "stage": stage,
            "error_type": error_type,
            "status_code": response.status_code,
            "message": response.error,
        }
        with self.errors_log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def _log_validation_error(self, market_pair_id: str, source: str, code: str, message: str) -> None:
        payload = {
            "timestamp": utc_now().isoformat(),
            "market_pair": market_pair_id,
            "stage": source,
            "error_type": code,
            "message": message,
        }
        with self.errors_log_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def _build_table(self) -> Table:
        table = Table(title="Polymarket vs Kalshi Monitor", expand=True)
        table.add_column("Market Pair", justify="left")
        table.add_column("Status", justify="left")
        table.add_column("Kalshi (Bid/Ask)", justify="right")
        table.add_column("Polymarket (Bid/Ask)", justify="right")
        table.add_column("Direction", justify="center")
        table.add_column("Net Spread", justify="right")
        table.add_column("Updated", justify="right")

        for pair in self.config.market_pairs:
            state = self.market_states[pair.id]
            observation = self.latest_observations.get(pair.id)

            if state.status == "ERROR":
                status_display = self.STATUS_ERROR
            elif state.status == "OPPORTUNITY":
                status_display = self.STATUS_OPPORTUNITY
            else:
                status_display = self.STATUS_MONITORING

            if observation:
                kalshi_display = f"{observation.kalshi_quote.bid:.3f}/{observation.kalshi_quote.ask:.3f}"
                poly_display = f"{observation.polymarket_quote.bid:.3f}/{observation.polymarket_quote.ask:.3f}"
                direction_display, spread_display = self._direction_and_spread(observation)
                updated_display = observation.timestamp.astimezone().strftime("%H:%M:%S")
            else:
                kalshi_display = "N/A"
                poly_display = "N/A"
                direction_display = "-"
                spread_display = "-"
                updated_display = "-"

            table.add_row(
                pair.market_name or pair.id,
                status_display,
                kalshi_display,
                poly_display,
                direction_display,
                spread_display,
                updated_display,
            )

        return table

    def _direction_and_spread(self, observation: MarketObservation) -> Tuple[str, str]:
        dir_parts = []
        spreads = []
        if observation.net_spread_sell_p_buy_k > 0:
            dir_parts.append("P→K")
            spreads.append(observation.net_spread_sell_p_buy_k)
        if observation.net_spread_sell_k_buy_p > 0:
            dir_parts.append("K→P")
            spreads.append(observation.net_spread_sell_k_buy_p)
        if not dir_parts:
            return "-", "-"
        direction_display = "/".join(dir_parts)
        spread_value = max(spreads)
        spread_display = f"+${spread_value:.4f}"
        return direction_display, spread_display


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Polymarket vs Kalshi monitoring tool")
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config.json"),
        help="Path to configuration file",
    )
    parser.add_argument(
        "--log-dir",
        type=Path,
        default=Path("."),
        help="Directory for generated logs",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    try:
        config = load_config(str(args.config))
    except Exception as exc:  # pylint: disable=broad-except
        console.print(f"[red]Failed to load config: {exc}[/red]")
        sys.exit(1)

    monitor = Monitor(config=config, log_dir=args.log_dir)

    def shutdown_handler(signum: int, frame) -> None:  # type: ignore[override]
        console.print(f"[yellow]Received signal {signum}. Saving state and exiting...[/yellow]")
        monitor._save_window_state()  # pylint: disable=protected-access
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown_handler)
    signal.signal(signal.SIGTERM, shutdown_handler)

    monitor.run()
    monitor._save_window_state()  # pylint: disable=protected-access


if __name__ == "__main__":
    main()
