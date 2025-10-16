import json

def load_config(path='config.json'):
    with open(path, 'r', encoding='utf-8') as f:
        cfg = json.load(f)
    required_keys = ["market_pairs", "monitoring", "cost_assumptions"]
    for k in required_keys:
        if k not in cfg:
            raise ValueError(f"Missing key in config: {k}")
    return cfg