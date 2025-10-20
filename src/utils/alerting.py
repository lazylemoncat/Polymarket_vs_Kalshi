import json
import requests

def maybe_send_telegram(cfg_alerting: dict, payload: dict):
    """
    如果 alerting.enabled = True 且 token/chat_id 均存在，则把 payload 作为文本推送到 Telegram。
    """
    if not cfg_alerting or not cfg_alerting.get("enabled"):
        return

    token = cfg_alerting.get("telegram_bot_token")
    chat_id = cfg_alerting.get("telegram_chat_id")
    if not token or not chat_id:
        return

    text = "⚡ Arbitrage opportunity!\n" + json.dumps(payload, ensure_ascii=False, indent=2)
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        requests.post(url, json={"chat_id": chat_id, "text": text}, timeout=5)
    except Exception:
        # 静默失败，不影响主流程
        pass
