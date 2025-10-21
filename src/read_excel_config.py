import json
import logging
import re
from dataclasses import asdict, dataclass
from pathlib import Path

import pandas as pd

from .models import MarketPair
from .polymarket_api import get_market_public_search
from .kalshi_api import get_event_by_event_ticker


logger = logging.getLogger(__name__)


@dataclass
class Pair:
    id: str
    type: str
    kalshi_title: str
    polymarket_title: str
    polymarket_market: str
    status: str
    kalshi_url: str
    kalshi_market: str
    polymarket_url: str
    notes: str

@dataclass
class MarketPairMapping:
    """定义 Excel 列名与 dataclass 字段的对应关系"""
    type_col: str = "类型"
    kalshi_title_col: str = "Kalshi 标题"
    kalshi_market_col: str = "Kalshi 市场"
    polymarket_title_col: str = "Polymarket 标题"
    poymarket_market_col: str = "Polymarket 市场"
    status_col: str = "状态"
    kalshi_url_col: str = "Kalshi URL"
    polymarket_url_col: str = "Polymarket URL"
    notes_col: str = "验证备注"


def load_market_pairs(excel_path: str, mapping: MarketPairMapping):
    """从 Excel 文件加载市场配对表"""

    df = pd.read_excel(excel_path)
    df.columns = [col.strip() for col in df.columns]

    # Pandas 在 itertuples() 时会将列名中的空格、符号替换成下划线
    def normalize_col_name(col: str) -> str:
        """模仿 Pandas 内部规则：空格和特殊字符替换为下划线"""
        return re.sub(r'\W+', '_', col.strip())

    attr_map = {col: normalize_col_name(col) for col in df.columns}

    df.columns = list(attr_map.values())

    def get_attr(row, col_name: str, default=""):
        # 根据 mapping 中原始列名找到对应的 tuple 属性名
        attr_name = attr_map.get(col_name, "")
        return getattr(row, attr_name, default)

    pairs = []
    for i, row in enumerate(df.itertuples(index=False), start=1):
        pair = Pair(
            id=f"pair_{i:03d}",
            type=get_attr(row, mapping.type_col),
            kalshi_title=get_attr(row, mapping.kalshi_title_col),
            kalshi_market=get_attr(row, mapping.kalshi_market_col),
            polymarket_title=get_attr(row, mapping.polymarket_title_col),
            polymarket_market=get_attr(row, mapping.poymarket_market_col),
            status=get_attr(row, mapping.status_col),
            kalshi_url=get_attr(row, mapping.kalshi_url_col),
            polymarket_url=get_attr(row, mapping.polymarket_url_col),
            notes=get_attr(row, mapping.notes_col)
        )
        pairs.append(pair)

    return pairs


def main():
    input_file = Path("Kalshi vs Polymarket 候选对.xlsx")
    config_path = Path("config.json")

    mapping = MarketPairMapping()
    pairs = load_market_pairs(str(input_file), mapping)

    marketPairs = []
    for p in pairs:
        events = get_market_public_search(p.polymarket_title).get('events')[0]
        markets = events.get('markets', [])
        polymarket_market_id = ""
        for market in markets:
            if market.get('groupItemTitle') == p.polymarket_market:
                polymarket_market_id = market.get('id')
                break

        polymarket_token = events.get('id')
        settlement_date = events.get('endDate')

        kalshi_ticker = p.kalshi_url.rstrip("/").split("/")[-1].upper()
        kalshi_markets = get_event_by_event_ticker(kalshi_ticker).get('markets', [])
        kalshi_market_id = ""
        for kalshi_market in kalshi_markets:
            title = kalshi_market.get('sub_title') or kalshi_market.get('yes_sub_title') \
                    or kalshi_market.get('no_sub_title')
            if title == p.kalshi_market:
                kalshi_market_id = kalshi_market.get('ticker')
                break

        marketPairs.append(MarketPair(
            id=p.id,
            polymarket_token=polymarket_token,
            kalshi_ticker=kalshi_ticker,
            market_name=p.polymarket_title,
            settlement_date=settlement_date,
            manually_verified=True,
            polymarket_market_id=polymarket_market_id,
            kalshi_market_id=kalshi_market_id,
            notes=p.notes
        ))
    
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
    else:
        config = {}

    # 转换 dataclass → dict
    config["market_pairs"] = [asdict(mp) for mp in marketPairs]

    # 写回 JSON 文件（格式化输出）
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)

    logger.info(
        "已更新 %s 中的 market_pairs (%d 条)",
        config_path,
        len(marketPairs),
    )



if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    try:
        main()
    except Exception:
        logger.exception("Failed to update market_pairs from Excel")
