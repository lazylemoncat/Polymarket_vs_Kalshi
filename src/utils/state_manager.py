import json
import uuid
import datetime
import os


class WindowManager:
    def __init__(self):
        # active: {market_pair: {...window data...}}
        self.active = {}

    def update(self, pair_name, spread_value, direction, ts):
        """
        更新状态机:
        - 若 spread > 0：创建或更新一个“活动窗口”
        - 若 spread <= 0 且当前有活动窗口：关闭该窗口
        """
        state = self.active.get(pair_name)

        if spread_value > 0:
            if not state:
                # 新窗口开始
                self.active[pair_name] = {
                    "window_id": str(uuid.uuid4()),
                    "market_pair": pair_name,
                    "start_time": ts,
                    "direction": direction,
                    "spreads": [spread_value],
                }
            else:
                # 窗口持续中
                state["spreads"].append(spread_value)
        elif state:
            # 窗口结束
            self.close_window(pair_name, ts)

    def close_window(self, pair_name, end_time):
        """
        关闭窗口并写入 opportunity_windows.csv
        """
        from utils import logger

        state = self.active.pop(pair_name, None)
        if not state:
            return

        duration = (end_time - state["start_time"]).total_seconds()
        spreads = state["spreads"]
        avg_spread = sum(spreads) / len(spreads)
        peak_spread = max(spreads)

        record = {
            "window_id": state["window_id"],
            "market_pair": pair_name,
            "start_time": state["start_time"].isoformat(),
            "end_time": end_time.isoformat(),
            "duration_seconds": round(duration, 2),
            "peak_spread": round(peak_spread, 4),
            "avg_spread": round(avg_spread, 4),
            "direction": state["direction"],
            "observation_count": len(spreads),
        }

        logger.log_window(record)

    def save_checkpoint(self, filepath="data/window_state.json"):
        """
        定期保存活动窗口状态 (FR6.1)
        """
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        checkpoint = {
            "last_updated": datetime.datetime.utcnow().isoformat(),
            "active_windows": {},
        }
        for k, v in self.active.items():
            checkpoint["active_windows"][k] = {
                **v,
                "start_time": v["start_time"].isoformat(),
            }

        with open(filepath, "w") as f:
            json.dump(checkpoint, f, indent=2)

    def load_checkpoint(self, filepath="data/window_state.json", timeout_minutes=5):
        """
        启动时恢复上次状态 (FR6.2)
        - 若上次保存时间小于5分钟，恢复活跃窗口
        - 否则将其标记为“中断结束”并写入opportunity_windows.csv
        """
        if not os.path.exists(filepath):
            return

        from utils import logger

        with open(filepath, "r") as f:
            data = json.load(f)

        last_updated = datetime.datetime.fromisoformat(data["last_updated"])
        now = datetime.datetime.utcnow()
        delta = (now - last_updated).total_seconds() / 60

        if delta <= timeout_minutes:
            # 恢复活跃窗口
            for k, v in data["active_windows"].items():
                v["start_time"] = datetime.datetime.fromisoformat(v["start_time"])
                self.active[k] = v
            print(f"♻️ 恢复 {len(self.active)} 个未结束窗口")
        else:
            # 超时 → 强制结束
            for k, v in data["active_windows"].items():
                v["start_time"] = datetime.datetime.fromisoformat(v["start_time"])
                record = {
                    "window_id": v["window_id"],
                    "market_pair": k,
                    "start_time": v["start_time"].isoformat(),
                    "end_time": now.isoformat(),
                    "duration_seconds": round((now - v["start_time"]).total_seconds(), 2),
                    "peak_spread": round(max(v["spreads"]), 4),
                    "avg_spread": round(sum(v["spreads"]) / len(v["spreads"]), 4),
                    "direction": v["direction"],
                    "observation_count": len(v["spreads"]),
                    "interrupted": True,
                }
                logger.log_window(record)
            print("⚠️ 检测到过期检查点，已强制关闭所有窗口")
            os.remove(filepath)
