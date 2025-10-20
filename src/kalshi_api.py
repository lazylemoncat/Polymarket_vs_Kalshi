import requests

kalshi_baseurl = "https://api.elections.kalshi.com/trade-api/v2"
get_markets_url = f"{kalshi_baseurl}/markets"
get_event_by_event_ticker_url = f"{kalshi_baseurl}/events/{{event_ticker}}"

def get_kalshi_markets():
    response = requests.get(get_markets_url)
    return response.json().get("markets", [])

def get_event_ticker_by_title(title: str):
    markets = get_kalshi_markets()
    for market in markets:
        if market.get("title") == title:
            return market.get("event_ticker")
    return None

def get_event_by_event_ticker(event_ticker: str):
    url = get_event_by_event_ticker_url.format(event_ticker=event_ticker)
    response = requests.get(url)
    return response.json()

def main():
    # print(get_event_ticker_by_title("Highest temperature in NYC on Oct 14, 2025?"))
    event = get_event_by_event_ticker("KXPOWELLMENTION-25OCT15")
    from pprint import pprint
    pprint(event)

if __name__ == "__main__":
    main()