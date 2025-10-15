import json
import re
from dataclasses import asdict, dataclass
from pathlib import Path

import pandas as pd

from models import MarketPair
from polymarket_api import get_market_public_search


@dataclass
class Pair:
    id: str
    type: str
    kalshi_title: str
    polymarket_title: str
    status: str
    kalshi_url: str
    polymarket_url: str
    notes: str

@dataclass
class MarketPairMapping:
    """定义 Excel 列名与 dataclass 字段的对应关系"""
    type_col: str = "类型"
    kalshi_title_col: str = "Kalshi 标题"
    polymarket_title_col: str = "Polymarket 标题"
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
        attr_name = attr_map.get(col_name)
        return getattr(row, attr_name, default)

    pairs = []
    for i, row in enumerate(df.itertuples(index=False), start=1):
        pair = Pair(
            id=f"pair_{i:03d}",
            type=get_attr(row, mapping.type_col),
            kalshi_title=get_attr(row, mapping.kalshi_title_col),
            polymarket_title=get_attr(row, mapping.polymarket_title_col),
            status=get_attr(row, mapping.status_col),
            kalshi_url=get_attr(row, mapping.kalshi_url_col),
            polymarket_url=get_attr(row, mapping.polymarket_url_col),
            notes=get_attr(row, mapping.notes_col)
        )
        pairs.append(pair)

    return pairs


def main():
    input_file = Path("Kalshi vs Polymarket 候选对.xlsx")

    mapping = MarketPairMapping()
    pairs = load_market_pairs(str(input_file), mapping)

    marketPairs = []
    for p in pairs:
        events = get_market_public_search(p.polymarket_title).get('events')[0]
        polymarket_token = events.get('id')
        settlement_date = events.get('endDate')
        marketPairs.append(MarketPair(
            id=p.id,
            polymarket_token=polymarket_token,
            kalshi_ticker="",
            market_name=p.polymarket_title,
            settlement_date=settlement_date,
            manually_verified=True,
            notes=p.notes
        ))
    


if __name__ == "__main__":
    main()
