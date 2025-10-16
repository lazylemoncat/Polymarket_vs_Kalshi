def calc_spreads(kalshi_bid, kalshi_ask, poly_bid, poly_ask, total_cost):
    spread_K_to_P = kalshi_bid - poly_ask - total_cost
    spread_P_to_K = poly_bid - kalshi_ask - total_cost
    return spread_K_to_P, spread_P_to_K
