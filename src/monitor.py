import asyncio
import datetime
import json
import logging
import math
import time
from pathlib import Path

from rich import box
from rich.console import Console
from rich.live import Live
from rich.table import Table

from logger_setup import setup_logging
from utils import config_loader
from utils.kalshi_client import KalshiClient
from utils.polymarket_client import PolymarketClient
from utils.telegramNotifier import TelegramNotifier

setup_logging()
logger = logging.getLogger("monitor")


# ---------- 全局常量 ----------
DATA_DIR = Path("data")
DATA_DIR.mkdir(parents=True, exist_ok=True)

ERROR_LOG = DATA_DIR / "errors.log"
ARBITRAGE_LOG = DATA_DIR / "arbitrage.log"
WINDOW_STATE_JSON = DATA_DIR / "window_state.json"
PRICE_SNAPSHOTS_CSV = DATA_DIR / "price_snapshots.csv"
OPP_WINDOWS_CSV = DATA_DIR / "opportunity_windows.csv"

console = Console()


# ---------- 工具函数 ----------
def _utc_now_iso():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _log_error(source: str, message: str):
    row = {"time": _utc_now_iso(), "source": source, "error": message}
    with ERROR_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")


def calc_kalshi_fee(prob: float) -> float:
    """Kalshi taker 费率模型（PRD公式）"""
    try:
        fee = math.ceil(0.07 * prob * (1 - prob) * 100) / 100 * 2
        return round(fee, 4)
    except Exception:
        return 0.0


def normalize(s: str):
    if not s:
        return ""
    t = s.strip().lower()
    t = t.replace("–", "-").replace("—", "-")
    t = t.replace("°f", "°").replace(" °", "°")
    t = " ".join(t.split())
    return t


def find_market_by_title(markets: list, target_title: str):
    nt = normalize(target_title)
    for m in markets:
        if normalize(m.get("title", "")) == nt:
            return m
    return None


# ---------- 机会窗口管理类（前文已完整实现） ----------
from monitor_windows import (
    OpportunityWindowManager,  # 这里假设已拆出为独立模块，逻辑同前版
)


# ---------- 错误计数器 ----------
class FailureTracker:
    def __init__(self):
        self.counts = {}

    def mark_failure(self, key):
        self.counts[key] = self.counts.get(key, 0) + 1
        if self.counts[key] >= 3:
            _log_error(key, f"连续3次数据获取失败")
            self.counts[key] = 0

    def mark_success(self, key):
        self.counts[key] = 0


# ---------- 核心监控逻辑 ----------
async def handle_arbitrage_signal(signal: dict, notifier: TelegramNotifier):
    payload = dict(signal)
    payload["timestamp"] = _utc_now_iso()
    with ARBITRAGE_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")

    msg = (
        f"⚡ *套利机会！*\n"
        f"事件: {payload['event']}\n"
        f"市场: {payload['polymarket_title']} ↔ {payload['kalshi_title']}\n"
        f"Poly: {payload['poly_bid']}/{payload['poly_ask']}\n"
        f"Kalshi: {payload['kalshi_bid']}/{payload['kalshi_ask']}\n"
        f"K→P: {payload['net_spread_sell_K_buy_P']}, P→K: {payload['net_spread_sell_P_buy_K']}"
    )
    try:
        await notifier.send_message(msg, parse_mode="Markdown")
    except Exception as e:
        _log_error("telegram", str(e))


async def monitor_once(cfg, notifier, window_mgr, fail_tracker):
    polling_interval = cfg["monitoring"]["polling_interval_seconds"]
    gas_fee = cfg["cost_assumptions"]["gas_fee_per_trade_usd"]

    poly = PolymarketClient(
        base_url="https://gamma-api.polymarket.com",
        polling_interval=polling_interval
    )
    kalshi = KalshiClient(
        base_url="https://api.elections.kalshi.com/trade-api/v2",
        polling_interval=polling_interval,
        api_key=cfg.get("kalshi_api_key")
    )

    pairs = cfg["event_pairs"]
    table = Table(title="Arbitrage Monitor Snapshot", box=box.MINIMAL_DOUBLE_HEAD)
    table.add_column("Event", justify="left")
    table.add_column("Market Pair", justify="left")
    table.add_column("K→P", justify="right")
    table.add_column("P→K", justify="right")
    table.add_column("Status", justify="center")

    any_event = False

    for ev in pairs:
        name = ev["name"]
        eid = ev.get("id", name)
        pid = ev["polymarket_event_id"]
        kt = ev["kalshi_event_ticker"]
        mapping = ev["markets_map"]

        poly_markets = poly.fetch_event_markets(pid)
        kalshi_markets = kalshi.fetch_event_markets(kt)

        if not poly_markets or not kalshi_markets:
            fail_tracker.mark_failure(name)
            table.add_row(name, "-", "-", "-", "[red]❌ Failed")
            continue
        fail_tracker.mark_success(name)

        any_event = True
        for mp in mapping:
            p_title = mp["polymarket_title"]
            k_title = mp["kalshi_title"]
            market_pair_label = f"{p_title} ↔ {k_title}"
            pair_key = f"{eid}::{p_title}::{k_title}"
            pm = find_market_by_title(poly_markets, p_title)
            km = find_market_by_title(kalshi_markets, k_title)

            if not pm or not km:
                table.add_row(name, market_pair_label, "-", "-", "[yellow]Skipped")
                continue

            pb, pa = pm["bid"], pm["ask"]
            kb, ka = km["bid"], km["ask"]

            # Kalshi 费用纳入 total_cost
            kalshi_fee = calc_kalshi_fee(kb)
            total_cost = gas_fee + kalshi_fee

            net_K_to_P = pb - ka - total_cost
            net_P_to_K = kb - pa - total_cost
            now_iso = _utc_now_iso()

            window_mgr.write_snapshot(market_pair_label, kb, ka, pb, pa, total_cost,
                                      net_K_to_P, net_P_to_K, now_iso)

            opened = False
            if net_K_to_P > 0:
                window_mgr.open_or_update(pair_key, "K_to_P", market_pair_label, net_K_to_P, now_iso)
                opened = True
            else:
                window_mgr.close_if_open(pair_key, "K_to_P", now_iso)

            if net_P_to_K > 0:
                window_mgr.open_or_update(pair_key, "P_to_K", market_pair_label, net_P_to_K, now_iso)
                opened = True
            else:
                window_mgr.close_if_open(pair_key, "P_to_K", now_iso)

            status = "[green]Open" if opened else "[dim]Idle"
            table.add_row(name, market_pair_label,
                          f"{net_K_to_P:.3f}", f"{net_P_to_K:.3f}", status)

            if opened:
                await handle_arbitrage_signal({
                    "event": name,
                    "polymarket_title": p_title,
                    "kalshi_title": k_title,
                    "poly_bid": round(pb, 4), "poly_ask": round(pa, 4),
                    "kalshi_bid": round(kb, 4), "kalshi_ask": round(ka, 4),
                    "net_spread_sell_K_buy_P": round(net_K_to_P, 4),
                    "net_spread_sell_P_buy_K": round(net_P_to_K, 4),
                }, notifier)

    console.clear()
    console.print(table)
    window_mgr.maybe_checkpoint()


async def main():
    logger.info("🚀 启动套利监控系统...")
    cfg = config_loader.load_config()

    # --- 配置校验 ---
    assert cfg["monitoring"]["polling_interval_seconds"] > 0, "polling_interval_seconds 必须 > 0"
    assert cfg["monitoring"]["duration_hours"] > 0, "duration_hours 必须 > 0"
    assert cfg["cost_assumptions"]["gas_fee_per_trade_usd"] >= 0, "gas_fee_per_trade_usd 必须 ≥ 0"

    notifier = TelegramNotifier(
        token=cfg["alerting"]["telegram_bot_token"],
        chat_id=cfg["alerting"]["telegram_chat_id"]
    )

    window_mgr = OpportunityWindowManager()
    window_mgr.load_or_recover()
    fail_tracker = FailureTracker()

    polling_interval = cfg["monitoring"]["polling_interval_seconds"]
    duration_hours = cfg["monitoring"]["duration_hours"]
    start_time = time.time()
    base_interval = polling_interval
    extended = False

    console.print(f"轮询间隔: {polling_interval}s | 持续时长: {duration_hours}h")

    with Live(console=console, refresh_per_second=4):
        while True:
            await monitor_once(cfg, notifier, window_mgr, fail_tracker)
            elapsed_h = (time.time() - start_time) / 3600
            if elapsed_h >= duration_hours:
                console.print(f"[bold yellow]⏹ 达到配置的监控时长 ({duration_hours}h)，自动退出。")
                break

            # 动态调整轮询间隔（冷却恢复）
            if getattr(KalshiClient, "retry_count", 0) > 5 and not extended:
                polling_interval = int(polling_interval * 1.5)
                console.print(f"[yellow]⚠️ 检测到频繁429，临时延长轮询间隔至 {polling_interval}s")
                extended = True
            elif extended and getattr(KalshiClient, "retry_count", 0) == 0:
                polling_interval = base_interval
                extended = False
                console.print("[green]✅ 已恢复正常轮询频率")

            await asyncio.sleep(polling_interval)

    console.print("[bold green]✅ 监控任务已结束。")


if __name__ == "__main__":
    asyncio.run(main())
