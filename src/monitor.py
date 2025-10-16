import time
from utils.polymarket_client import PolymarketClient
from utils.kalshi_client import KalshiClient
from utils.config_loader import load_config


def compare_markets(poly_markets, kalshi_markets):
    """
    比较 Polymarket 与 Kalshi 对应市场价格差异。
    暂时按顺序匹配(第1对第1),后续可改用温度区间或市场标题匹配。
    """
    results = []
    for i, poly_m in enumerate(poly_markets):
        if i >= len(kalshi_markets):
            break

        kalshi_m = kalshi_markets[i]

        poly_name = poly_m.get("question") or poly_m.get("id")
        kalshi_name = kalshi_m.get("subtitle") or kalshi_m.get("ticker")

        poly_yes = poly_m.get("bestAsk") or poly_m.get("ask") or 0
        poly_no = poly_m.get("bestBid") or poly_m.get("bid") or 0
        kalshi_yes = kalshi_m.get("yes_ask") or kalshi_m.get("yes_price") or 0
        kalshi_no = kalshi_m.get("no_ask") or kalshi_m.get("no_price") or 0

        diff_yes = kalshi_yes - poly_yes
        diff_no = kalshi_no - poly_no

        results.append({
            "poly_market": poly_name,
            "kalshi_market": kalshi_name,
            "poly_yes": poly_yes,
            "kalshi_yes": kalshi_yes,
            "diff_yes": diff_yes,
            "poly_no": poly_no,
            "kalshi_no": kalshi_no,
            "diff_no": diff_no
        })
    return results


def display_arbitrage_opportunities(results):
    """打印套利机会（仅展示价差大的市场）"""
    has_arb = False
    for r in results:
        if abs(r["diff_yes"]) > 0.05 or abs(r["diff_no"]) > 0.05:  # 可调整阈值
            has_arb = True
            print(f"市场: {r['poly_market']} ↔ {r['kalshi_market']}")
            print(f"Polymarket Yes: {r['poly_yes']} | Kalshi Yes: {r['kalshi_yes']} | Δ = {r['diff_yes']:.3f}")
            print(f"Polymarket No : {r['poly_no']}  | Kalshi No : {r['kalshi_no']}  | Δ = {r['diff_no']:.3f}")
            print("-" * 60)
    if not has_arb:
        print("暂无套利机会。")


def main():
    print("启动套利监控系统...")
    cfg = load_config()

    poly = PolymarketClient(
        base_url="https://gamma-api.polymarket.com",
        polling_interval=cfg.get("polling_interval", 2)
    )
    kalshi = KalshiClient(
        base_url="https://api.elections.kalshi.com/trade-api/v2",
        polling_interval=cfg.get("polling_interval", 2)
    )

    event_pairs = cfg.get("event_pairs", [])
    interval = cfg.get("polling_interval", 2)

    print(f"轮询间隔: {interval}s | 监控事件数: {len(event_pairs)}")

    while True:
        for pair in event_pairs:
            event_name = pair.get("name")
            poly_event_id = pair.get("polymarket_event_id")
            kalshi_event_ticker = pair.get("kalshi_event_ticker")

            print(f"\n正在监控事件: {event_name}")

            try:
                poly_markets = poly.fetch_event_markets(poly_event_id)
                kalshi_markets = kalshi.fetch_event_markets(kalshi_event_ticker)

                results = compare_markets(poly_markets, kalshi_markets)
                display_arbitrage_opportunities(results)

            except Exception as e:
                print(f"事件 {event_name} 报错: {e}")

        print(f"等待 {interval} 秒后继续轮询...\n")
        time.sleep(interval)


if __name__ == "__main__":
    main()
