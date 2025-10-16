import time
import os
import json
import datetime

from utils.polymarket_client import PolymarketClient
from utils.kalshi_client import KalshiClient
from utils import fees, config_loader


# ===== 写出接口：当前写文件，后续可改 Telegram =====
def handle_arbitrage_signal(signal: dict):
    os.makedirs("data", exist_ok=True)
    payload = dict(signal)
    payload["timestamp"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    with open(os.path.join("data", "arbitrage.log"), "a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    print("💾 已记录套利机会 -> data/arbitrage.log")


# ===== 兼容老/新配置结构 =====
def normalize_event_pairs(cfg: dict):
    pairs = []

    # 新版：event_pairs
    if isinstance(cfg.get("event_pairs"), list):
        for x in cfg["event_pairs"]:
            pairs.append({
                "name": x.get("name") or x.get("market_name") or "Untitled Event",
                "polymarket_event_id": x.get("polymarket_event_id") or x.get("polymarket_token"),
                "kalshi_event_ticker": x.get("kalshi_event_ticker") or x.get("kalshi_ticker"),
            })

    # 旧版：market_pairs（把 token/ticker 视为事件ID / 事件ticker）
    elif isinstance(cfg.get("market_pairs"), list):
        for x in cfg["market_pairs"]:
            pairs.append({
                "name": x.get("market_name") or x.get("id") or "Untitled Event",
                "polymarket_event_id": x.get("polymarket_token"),
                "kalshi_event_ticker": x.get("kalshi_ticker"),
            })

    # 过滤缺失
    return [p for p in pairs if p["polymarket_event_id"] and p["kalshi_event_ticker"]]


# ===== 按“标题完全一致”匹配 =====
def match_markets_by_title(poly_markets, kalshi_markets):
    """
    poly_markets / kalshi_markets: [{title, bid, ask, ...}]
    返回配对列表 [(poly, kalshi), ...]，只匹配标题完全一致的条目
    """
    kd = {m["title"]: m for m in kalshi_markets if m.get("title")}
    matched, skipped = [], []
    for pm in poly_markets:
        t = pm.get("title")
        if not t:
            continue
        km = kd.get(t)
        if km:
            matched.append((pm, km))
        else:
            skipped.append(t)
    if skipped:
        print(f"⚠️ 未在 Kalshi 找到同名市场（被跳过）：{', '.join(skipped[:5])}" + (" ..." if len(skipped) > 5 else ""))
    return matched


# ===== 组装事件级比较 + 净价差 =====
def build_event_comparison(event_name, matched_pairs, gas_fee_usd: float):
    results = {"event": event_name, "markets": []}
    for poly_m, kalshi_m in matched_pairs:
        pb, pa = poly_m["bid"], poly_m["ask"]
        kb, ka = kalshi_m["bid"], kalshi_m["ask"]

        # 方向1：卖 Kalshi(吃 bid) + 买 Polymarket(吃 ask)
        total_cost_K_to_P = fees.total_cost(
            kalshi_price=kb, poly_bid=pb, poly_ask=pa, gas_fee=gas_fee_usd
        )
        net_K_to_P = kb - pa - total_cost_K_to_P

        # 方向2：卖 Polymarket(吃 bid) + 买 Kalshi(吃 ask)
        total_cost_P_to_K = fees.total_cost(
            kalshi_price=ka, poly_bid=pb, poly_ask=pa, gas_fee=gas_fee_usd
        )
        net_P_to_K = pb - ka - total_cost_P_to_K

        results["markets"].append({
            "title": poly_m["title"],  # 两边同名
            "poly_bid": round(pb, 4), "poly_ask": round(pa, 4),
            "kalshi_bid": round(kb, 4), "kalshi_ask": round(ka, 4),
            "net_spread_sell_K_buy_P": round(net_K_to_P, 4),
            "net_spread_sell_P_buy_K": round(net_P_to_K, 4),
        })
    return results


# ===== 输出套利机会（多市场/双方向） =====
def display_arbitrage_opportunities(event_comparisons, log_if_positive=True):
    any_arb = False
    for ev in event_comparisons:
        print(f"\n📊 事件: {ev['event']}")
        for m in ev["markets"]:
            k2p = m["net_spread_sell_K_buy_P"]
            p2k = m["net_spread_sell_P_buy_K"]
            if k2p > 0 or p2k > 0:
                any_arb = True
                print(f"⚖️ 市场: {m['title']}")
                print(f"    Polymarket: {m['poly_bid']:.3f}/{m['poly_ask']:.3f} | Kalshi: {m['kalshi_bid']:.3f}/{m['kalshi_ask']:.3f}")
                if k2p > 0:
                    print(f"    ▶ 方向 K→P (卖K 买P) 净价差: +{k2p:.3f}")
                if p2k > 0:
                    print(f"    ▶ 方向 P→K (卖P 买K) 净价差: +{p2k:.3f}")
                print("-" * 72)
                if log_if_positive:
                    handle_arbitrage_signal({
                        "event": ev["event"],
                        "title": m["title"],
                        "poly_bid": m["poly_bid"], "poly_ask": m["poly_ask"],
                        "kalshi_bid": m["kalshi_bid"], "kalshi_ask": m["kalshi_ask"],
                        "net_spread_sell_K_buy_P": k2p,
                        "net_spread_sell_P_buy_K": p2k,
                    })
    if not any_arb:
        print("暂无套利机会。")


def main():
    print("🚀 启动套利监控系统...")
    cfg = config_loader.load_config()

    polling_interval = cfg.get("monitoring", {}).get("polling_interval_seconds") or cfg.get("polling_interval", 2)

    poly = PolymarketClient(
        base_url="https://gamma-api.polymarket.com",
        polling_interval=polling_interval
    )
    kalshi = KalshiClient(
        base_url="https://api.elections.kalshi.com/trade-api/v2",
        polling_interval=polling_interval,
        api_key=cfg.get("kalshi_api_key")
    )

    pairs = normalize_event_pairs(cfg)
    gas_fee = cfg.get("cost_assumptions", {}).get("gas_fee_per_trade_usd", 0.10)
    print(f"轮询间隔: {polling_interval}s | 监控事件数: {len(pairs)}")

    while True:
        round_results = []
        for pair in pairs:
            event_name = pair["name"]
            pid = pair["polymarket_event_id"]
            kt = pair["kalshi_event_ticker"]

            print(f"\n🔎 拉取事件：{event_name}")
            poly_markets = poly.fetch_event_markets(pid)      # [{title,bid,ask}]
            kalshi_markets = kalshi.fetch_event_markets(kt)   # [{title,bid,ask}]

            if not poly_markets or not kalshi_markets:
                print("⚠️ 任一平台未返回市场数据，跳过该事件。")
                continue

            matched = match_markets_by_title(poly_markets, kalshi_markets)
            if not matched:
                print("⚠️ 没有标题相同的市场，跳过该事件。")
                continue

            ev_comp = build_event_comparison(event_name, matched, gas_fee_usd=gas_fee)
            round_results.append(ev_comp)

        if round_results:
            display_arbitrage_opportunities(round_results, log_if_positive=True)
        else:
            print("⚠️ 本轮无可比对事件或无匹配市场。")

        print(f"\n⏳ 等待 {polling_interval} 秒后继续轮询...")
        time.sleep(polling_interval)


if __name__ == "__main__":
    main()
