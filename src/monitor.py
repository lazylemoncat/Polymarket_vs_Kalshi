import time
import datetime
from utils.polymarket_client import PolymarketClient
from utils.kalshi_client import KalshiClient
from utils import fees, spreads, logger, state_manager, terminal_ui, config_loader


def init_clients(cfg):
    """初始化 API 客户端"""
    polling_interval = cfg["monitoring"]["polling_interval_seconds"]

    poly = PolymarketClient(
        base_url="https://gamma-api.polymarket.com",
        polling_interval=polling_interval
    )

    kalshi = KalshiClient(
        base_url="https://api.elections.kalshi.com/trade-api/v2",
        polling_interval=polling_interval,
        api_key=cfg.get("kalshi_api_key")  # 如果有私钥
    )

    return {"poly": poly, "kalshi": kalshi}


def main():
    cfg = config_loader.load_config()
    clients = init_clients(cfg)
    wm = state_manager.WindowManager()

    polling_interval = cfg["monitoring"]["polling_interval_seconds"]
    gas_fee = cfg["cost_assumptions"]["gas_fee_per_trade_usd"]

    print("🚀 启动套利监控系统...")
    print(f"轮询间隔: {polling_interval}s | 监控市场数: {len(cfg['market_pairs'])}")

    while True:
        table_rows = []

        for pair in cfg["market_pairs"]:
            name = pair["market_name"]
            poly_id = pair["polymarket_token"]
            kalshi_id = pair["kalshi_ticker"]

            # 1️⃣ 拉取两平台价格
            poly_data = clients["poly"].fetch_price(poly_id)
            kalshi_data = clients["kalshi"].fetch_price(kalshi_id)

            # 2️⃣ 错误处理
            if not poly_data or not kalshi_data:
                table_rows.append([name, "🔴 ERROR", "-", "-", "-", "-", datetime.datetime.utcnow().strftime("%H:%M:%S")])
                logger.log_error({
                    "timestamp": datetime.datetime.utcnow().isoformat(),
                    "pair": name,
                    "error": "missing data"
                })
                continue

            # 3️⃣ 成本与净价差计算
            total_cost = fees.total_cost(
                kalshi_price=kalshi_data["ask"],
                poly_bid=poly_data["bid"],
                poly_ask=poly_data["ask"],
                gas_fee=gas_fee
            )

            spread_K_to_P, spread_P_to_K = spreads.calc_spreads(
                kalshi_bid=kalshi_data["bid"],
                kalshi_ask=kalshi_data["ask"],
                poly_bid=poly_data["bid"],
                poly_ask=poly_data["ask"],
                total_cost=total_cost
            )

            # 4️⃣ 状态更新与窗口跟踪
            now = datetime.datetime.utcnow()
            if spread_K_to_P > 0:
                wm.update(name, spread_K_to_P, "K→P", now)
                status, direction, net_spread = "🟢 OPPORTUNITY", "K→P", f"+${spread_K_to_P:.3f}"
            elif spread_P_to_K > 0:
                wm.update(name, spread_P_to_K, "P→K", now)
                status, direction, net_spread = "🟢 OPPORTUNITY", "P→K", f"+${spread_P_to_K:.3f}"
            else:
                wm.update(name, 0, "-", now)
                status, direction, net_spread = "⚪ MONITORING", "-", "-"

            # 5️⃣ 写入价格快照日志
            logger.log_snapshot({
                "timestamp": now.isoformat(),
                "market_pair": name,
                "kalshi_bid": kalshi_data["bid"],
                "kalshi_ask": kalshi_data["ask"],
                "poly_bid": poly_data["bid"],
                "poly_ask": poly_data["ask"],
                "total_cost": round(total_cost, 4),
                "net_spread_K_to_P": round(spread_K_to_P, 4),
                "net_spread_P_to_K": round(spread_P_to_K, 4)
            })

            # 6️⃣ 渲染表格行
            table_rows.append([
                name,
                status,
                f"{kalshi_data['bid']:.2f}/{kalshi_data['ask']:.2f}",
                f"{poly_data['bid']:.2f}/{poly_data['ask']:.2f}",
                direction,
                net_spread,
                now.strftime("%H:%M:%S")
            ])

        # 7️⃣ 刷新终端 UI
        terminal_ui.render_table(table_rows)

        # 8️⃣ 保存状态检查点（每 5分钟一次）
        if int(time.time()) % 300 < polling_interval:
            wm.save_checkpoint("data/window_state.json")

        time.sleep(polling_interval)


if __name__ == "__main__":
    main()
