import requests

polymarket_baseurl = "https://gamma-api.polymarket.com"
list_market_url = f"{polymarket_baseurl}/markets"
public_search_url = f"{polymarket_baseurl}/public-search"
get_market_by_id_url = f"{polymarket_baseurl}/markets/{{market_id}}"

def get_market_list():
    """获取所有市场列表"""
    response = requests.get(list_market_url)
    return response.json()

def get_market_by_id(market_id: str):
    """根据市场 ID 获取市场详情"""
    url = get_market_by_id_url.format(market_id=market_id)
    response = requests.get(url)
    return response.json()

def get_market_public_search(querystring: str):
    """根据问题关键词搜索市场"""
    params = {"q": querystring}
    response = requests.get(public_search_url, params=params)
    return response.json()

def main():
    market_list = get_market_list()
    from py_clob_client.client import ClobClient
    from py_clob_client.clob_types import BookParams
    import json

    client = ClobClient("https://clob.polymarket.com")  # read-only
    for market in market_list:
        try:
            id = market.get("id")
            market_by_id = get_market_by_id(id)
            clobTokenIds = market_by_id.get("clobTokenIds", [])
            # print(f"Market ID: {id} | clobTokenIds: {clobTokenIds}")
            # clobTokenIds = market.get("clobTokenIds", [])
            # ✅ 第一步：解析 JSON 字符串
            token_ids = json.loads(clobTokenIds)
            # print("Parsed token IDs:", token_ids)

            # ✅ 第二步：传入真实的 token_id（字符串，不是 int）
            token_id = token_ids[0]

            book = client.get_order_book(token_id)
            # print(f"✅ Token {token_id}")
            print(f"Asks: {len(book.asks)} | Bids: {len(book.bids)}")
        except Exception as e:
            print(f"❌ Error processing market ID {id}: {e}")
            # continue
            break
    

if __name__ == "__main__":
    main()