"""
monitor_windows.py
----------------------------------------
机会窗口追踪 + 状态持久化模块
对齐《Polymarket vs. Kalshi 套利监控系统 PRD》：
  - FR4 机会窗口定义与日志记录
  - FR6 状态持久化与恢复
----------------------------------------
"""

import csv
import json
import datetime
import time
from pathlib import Path
from typing import Dict


# ---------- 文件路径 ----------
DATA_DIR = Path("data")
DATA_DIR.mkdir(parents=True, exist_ok=True)

PRICE_SNAPSHOTS_CSV = DATA_DIR / "price_snapshots.csv"
OPP_WINDOWS_CSV = DATA_DIR / "opportunity_windows.csv"
WINDOW_STATE_JSON = DATA_DIR / "window_state.json"

# ---------- CSV 头 ----------
SNAPSHOT_HEADERS = [
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

WINDOW_HEADERS = [
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


# ---------- 工具函数 ----------
def _ensure_csv(file_path: Path, headers):
    """确保 CSV 存在并写入表头"""
    if not file_path.exists():
        with file_path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()


def _append_csv_row(file_path: Path, headers, row: Dict):
    _ensure_csv(file_path, headers)
    with file_path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=headers)
        writer.writerow(row)


def _utc_now_iso() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


# ---------- 主类 ----------
class OpportunityWindowManager:
    """
    机会窗口追踪与状态持久化管理器
    ----------------------------------------
    支持功能：
      - price_snapshots.csv：每次轮询记录价差数据
      - opportunity_windows.csv：套利机会窗口打开/关闭日志
      - window_state.json：进行中窗口的定期检查点与恢复
    """

    def __init__(self, checkpoint_interval_sec: int = 300):
        self.active_windows: Dict[str, Dict] = {}
        self.last_checkpoint_ts = 0.0
        self.checkpoint_interval_sec = checkpoint_interval_sec

        _ensure_csv(PRICE_SNAPSHOTS_CSV, SNAPSHOT_HEADERS)
        _ensure_csv(OPP_WINDOWS_CSV, WINDOW_HEADERS)

    # ---------- 工具 ----------
    @staticmethod
    def _pair_key(event_id: str, p_title: str, k_title: str) -> str:
        return f"{event_id}::{p_title} <-> {k_title}"

    @staticmethod
    def _dir_label(direction: str) -> str:
        return "K→P" if direction == "K_to_P" else "P→K"

    def _window_key(self, pair_key: str, direction: str) -> str:
        return f"{pair_key}::{direction}"

    # ---------- 核心 ----------
    def _new_window(self, pair_key: str, direction: str, market_pair_label: str,
                    start_iso: str, first_spread: float) -> Dict:
        window_id = f"{hash(pair_key) & 0xffffffff:x}-{direction}-{int(time.time())}"
        return {
            "window_id": window_id,
            "pair_key": pair_key,
            "market_pair": market_pair_label,
            "direction": direction,
            "start_time": start_iso,
            "last_time": start_iso,
            "peak_spread": first_spread,
            "sum_spread": first_spread,
            "observation_count": 1,
        }

    def open_or_update(self, pair_key: str, direction: str,
                       market_pair_label: str, spread_val: float, now_iso: str):
        wk = self._window_key(pair_key, direction)
        w = self.active_windows.get(wk)
        if w is None:
            self.active_windows[wk] = self._new_window(pair_key, direction, market_pair_label,
                                                       now_iso, spread_val)
        else:
            w["last_time"] = now_iso
            w["observation_count"] += 1
            w["sum_spread"] += spread_val
            if spread_val > w["peak_spread"]:
                w["peak_spread"] = spread_val

    def close_if_open(self, pair_key: str, direction: str, end_iso: str, interrupted=False):
        wk = self._window_key(pair_key, direction)
        w = self.active_windows.pop(wk, None)
        if not w:
            return
        start_dt = datetime.datetime.fromisoformat(w["start_time"])
        end_dt = datetime.datetime.fromisoformat(end_iso)
        duration_sec = max(0, int((end_dt - start_dt).total_seconds()))
        avg_spread = round(w["sum_spread"] / max(1, w["observation_count"]), 6)

        row = {
            "window_id": w["window_id"],
            "market_pair": w["market_pair"],
            "start_time": w["start_time"],
            "end_time": end_iso,
            "duration_seconds": duration_sec,
            "peak_spread": round(w["peak_spread"], 6),
            "avg_spread": avg_spread,
            "direction": self._dir_label(w["direction"]),
            "observation_count": w["observation_count"],
            "interrupted": bool(interrupted),
        }
        _append_csv_row(OPP_WINDOWS_CSV, WINDOW_HEADERS, row)

    def write_snapshot(self, market_pair_label: str, kb: float, ka: float,
                       pb: float, pa: float, total_cost: float,
                       net_K_to_P: float, net_P_to_K: float, now_iso: str):
        row = {
            "timestamp": now_iso,
            "market_pair": market_pair_label,
            "kalshi_bid": round(kb, 6),
            "kalshi_ask": round(ka, 6),
            "poly_bid": round(pb, 6),
            "poly_ask": round(pa, 6),
            "total_cost": round(total_cost, 6),
            "net_spread_K_to_P": round(net_K_to_P, 6),
            "net_spread_P_to_K": round(net_P_to_K, 6),
        }
        _append_csv_row(PRICE_SNAPSHOTS_CSV, SNAPSHOT_HEADERS, row)

    # ---------- 状态持久化 ----------
    def maybe_checkpoint(self):
        now = time.time()
        if now - self.last_checkpoint_ts < self.checkpoint_interval_sec:
            return
        payload = {
            "last_updated": _utc_now_iso(),
            "active_windows": list(self.active_windows.values()),
        }
        with WINDOW_STATE_JSON.open("w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        self.last_checkpoint_ts = now

    def load_or_recover(self):
        if not WINDOW_STATE_JSON.exists():
            return
        try:
            with WINDOW_STATE_JSON.open("r", encoding="utf-8") as f:
                state = json.load(f)

            last_updated = state.get("last_updated")
            active_windows = state.get("active_windows", [])
            if not last_updated or not isinstance(active_windows, list):
                return

            last_dt = datetime.datetime.fromisoformat(last_updated)
            delta_sec = abs(
                (datetime.datetime.now(datetime.timezone.utc) - last_dt).total_seconds()
            )

            if delta_sec <= 300:
                self.active_windows = {}
                for w in active_windows:
                    if all(k in w for k in ("window_id", "market_pair", "direction",
                                            "start_time", "last_time", "pair_key")):
                        wk = self._window_key(w["pair_key"], w["direction"])
                        self.active_windows[wk] = w
                print(f"🟢 恢复 {len(self.active_windows)} 个进行中窗口。")
            else:
                now_iso = _utc_now_iso()
                forced = 0
                for w in active_windows:
                    try:
                        start_dt = datetime.datetime.fromisoformat(w["start_time"])
                        end_dt = datetime.datetime.fromisoformat(now_iso)
                        duration_sec = max(0, int((end_dt - start_dt).total_seconds()))
                        avg_spread = round(
                            w.get("sum_spread", 0.0) / max(1, w.get("observation_count", 1)), 6
                        )
                        row = {
                            "window_id": w.get("window_id", f"forced-{int(time.time())}"),
                            "market_pair": w.get("market_pair", "Unknown"),
                            "start_time": w.get("start_time", now_iso),
                            "end_time": now_iso,
                            "duration_seconds": duration_sec,
                            "peak_spread": round(w.get("peak_spread", 0.0), 6),
                            "avg_spread": avg_spread,
                            "direction": self._dir_label(w.get("direction", "K_to_P")),
                            "observation_count": int(w.get("observation_count", 1)),
                            "interrupted": True,
                        }
                        _append_csv_row(OPP_WINDOWS_CSV, WINDOW_HEADERS, row)
                        forced += 1
                    except Exception:
                        continue
                if forced:
                    print(f"🟡 检测到过期状态，强制结束 {forced} 个窗口。")
                WINDOW_STATE_JSON.unlink(missing_ok=True)
        except Exception:
            pass
