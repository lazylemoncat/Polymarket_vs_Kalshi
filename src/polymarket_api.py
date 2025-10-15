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
    # market_list = get_market_list()
    # print(market_list)
    # print(market_list[0])
    # market = get_market_by_id(market_list[0].get('id'))
    # print(market)
    market = get_market_public_search("Highest temperature in NYC on Oct 14, 2025?")
    print(market)

if __name__ == "__main__":
    main()