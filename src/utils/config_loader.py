import json
from pathlib import Path

def load_config(path: str = "config.json") -> dict:
    p = Path(path)
    with p.open("r", encoding="utf-8") as f:
        cfg = json.load(f)

    # 基本字段
    for k in ["event_pairs", "monitoring", "cost_assumptions", "alerting"]:
        if k not in cfg:
            raise ValueError(f"Missing top-level key: {k}")

    if not isinstance(cfg["event_pairs"], list) or len(cfg["event_pairs"]) == 0:
        raise ValueError("`event_pairs` must be a non-empty list.")

    # 事件级字段检查
    for i, ev in enumerate(cfg["event_pairs"], 1):
        for k in ["id", "name", "polymarket_event_id", "kalshi_event_ticker", "markets_map"]:
            if k not in ev:
                raise ValueError(f"[event_pairs[{i}]] missing key: {k}")
        if not isinstance(ev["markets_map"], list) or len(ev["markets_map"]) == 0:
            raise ValueError(f"[event_pairs[{i}]] `markets_map` must be a non-empty list.")
        for j, m in enumerate(ev["markets_map"], 1):
            if "polymarket_title" not in m or "kalshi_title" not in m:
                raise ValueError(f"[event_pairs[{i}].markets_map[{j}]] needs `polymarket_title` and `kalshi_title`.")

    # 监控字段
    mon = cfg["monitoring"]
    if "polling_interval_seconds" not in mon:
        raise ValueError("`monitoring.polling_interval_seconds` is required.")

    # 成本字段
    if "gas_fee_per_trade_usd" not in cfg["cost_assumptions"]:
        raise ValueError("`cost_assumptions.gas_fee_per_trade_usd` is required.")

    # alerting 可选开关
    alert = cfg.get("alerting", {})
    if "enabled" not in alert:
        alert["enabled"] = False
        cfg["alerting"] = alert

    return cfg
