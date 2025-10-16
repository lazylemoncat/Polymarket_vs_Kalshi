from math import ceil

def kalshi_fee(price):
    return ceil(0.07 * price * (1 - price) * 100) / 100

def total_cost(kalshi_price, poly_bid, poly_ask, gas_fee):
    kalshi_total_fee = kalshi_fee(kalshi_price) * 2
    return kalshi_total_fee + (poly_ask - poly_bid) + (gas_fee * 2)
