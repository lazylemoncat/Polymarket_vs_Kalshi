import requests

kalshi_baseurl = "https://api.elections.kalshi.com/trade-api/v2"
get_markets_url = f"{kalshi_baseurl}/markets"

def get_kalshi_markets():
    response = requests.get(get_markets_url)
    return response.json().get("markets", [])

def get_event_ticker_by_title(title: str):
    markets = get_kalshi_markets()
    for market in markets:
        if market.get("title") == title:
            return market.get("event_ticker")
    return None

def main():
    print(get_event_ticker_by_title("Highest temperature in NYC on Oct 14, 2025?"))

if __name__ == "__main__":
    main()