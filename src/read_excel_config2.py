import argparse
import json
import re
from dataclasses import asdict, dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

import pandas as pd

from models import EventPair, MarketMapping
from polymarket_api import get_market_public_search
from utils.kalshi_client import KalshiClient
from utils.polymarket_client import PolymarketClient


POLY_BASE_URL = "https://gamma-api.polymarket.com"
KALSHI_BASE_URL = "https://api.elections.kalshi.com/trade-api/v2"

DEFAULT_MONITORING = {"polling_interval_seconds": 2, "monitoring_duration_hours": 48}
DEFAULT_COSTS = {"gas_fee_per_trade_usd": 0.10}
DEFAULT_ALERTING = {"enabled": False, "telegram_bot_token": "", "telegram_chat_id": ""}


@dataclass
class ExcelRow:
    index: int
    event_type: str
    kalshi_title: str
    polymarket_title: str
    status: str
    kalshi_url: str
    polymarket_url: str
    notes: str

    @property
    def is_verified(self) -> bool:
        text = (self.status or "").lower()
        return any(marker in text for marker in ["confirm", "✅", "✔", "√"])


def _normalize_header(header: str) -> str:
    return re.sub(r"\W+", "_", header.strip()).lower()


def load_rows(excel_path: Path) -> List[ExcelRow]:
    df = pd.read_excel(excel_path)
    header_map = {_normalize_header(col): col for col in df.columns}

    def col(name: str) -> str:
        key = _normalize_header(name)
        if key not in header_map:
            raise KeyError(f"Missing expected column: {name}")
        return header_map[key]

    rows: List[ExcelRow] = []
    for idx, record in enumerate(df.to_dict(orient="records"), start=1):
        rows.append(
            ExcelRow(
                index=idx,
                event_type=str(record.get(col("类型"), "")).strip(),
                kalshi_title=str(record.get(col("Kalshi 标题"), "")).strip(),
                polymarket_title=str(record.get(col("Polymarket 标题"), "")).strip(),
                status=str(record.get(col("状态"), "")).strip(),
                kalshi_url=str(record.get(col("Kalshi URL"), "")).strip(),
                polymarket_url=str(record.get(col("Polymarket URL"), "")).strip(),
                notes=str(record.get(col("验证备注"), "") or "").strip(),
            )
        )
    return rows


def extract_kalshi_ticker(url: str) -> str:
    if not url:
        raise ValueError("Kalshi URL is empty.")
    ticker = url.rstrip("/").split("/")[-1].strip()
    if not ticker:
        raise ValueError(f"Cannot extract ticker from Kalshi URL: {url}")
    return ticker.upper()


def normalize_text(text: str) -> str:
    if not text:
        return ""
    lowered = text.lower()
    lowered = lowered.replace("°f", "f").replace("°", "")
    lowered = lowered.replace("$", "")
    lowered = lowered.replace("%", " percent ")
    lowered = lowered.replace("≥", ">=").replace("≤", "<=")
    cleaned = re.sub(r"[^a-z0-9\.\-\s]+", " ", lowered)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, normalize_text(a), normalize_text(b)).ratio()


def pick_polymarket_event(title: str) -> Dict:
    response = get_market_public_search(title)
    events = response.get("events") or []
    if not events:
        raise LookupError(f"No Polymarket events found for title `{title}`.")

    def score(event: Dict) -> float:
        candidate = event.get("question") or event.get("title") or ""
        return similarity(title, candidate)

    return max(events, key=score)


def pick_settlement_date(event: Dict) -> str:
    for key in ("endDate", "settlementDate", "closeDate", "end_date"):
        val = event.get(key)
        if val:
            return str(val)
    return str(event.get("resolutionTime") or "")


def match_markets(
    poly_markets: Iterable[Dict],
    kalshi_markets: Iterable[Dict],
) -> List[MarketMapping]:
    kalshi_list = list(kalshi_markets)
    polymarket_list = list(poly_markets)
    used_indices: set[int] = set()
    mappings: List[MarketMapping] = []

    for poly_market in polymarket_list:
        poly_title = str(poly_market.get("title") or "").strip()
        if not poly_title:
            continue
        best_idx: Optional[int] = None
        best_score = -1.0
        for idx, kalshi_market in enumerate(kalshi_list):
            if idx in used_indices:
                continue
            kalshi_title = str(kalshi_market.get("title") or "").strip()
            if not kalshi_title:
                continue
            score = similarity(poly_title, kalshi_title)
            if score > best_score:
                best_idx = idx
                best_score = score
        if best_idx is None:
            continue
        used_indices.add(best_idx)
        kalshi_title = str(kalshi_list[best_idx].get("title") or "").strip()
        mappings.append(MarketMapping(polymarket_title=poly_title, kalshi_title=kalshi_title))

    return mappings


def build_event_pair(
    row: ExcelRow,
    ordinal: int,
    poly_client: PolymarketClient,
    kalshi_client: KalshiClient,
) -> EventPair:
    event = pick_polymarket_event(row.polymarket_title)
    event_id = str(event.get("id") or event.get("eventId") or "")
    if not event_id:
        raise ValueError(f"Unable to determine Polymarket event id for `{row.polymarket_title}`.")

    settlement_date = pick_settlement_date(event)
    kalshi_ticker = extract_kalshi_ticker(row.kalshi_url)

    poly_markets = poly_client.fetch_event_markets(event_id)
    kalshi_markets = kalshi_client.fetch_event_markets(kalshi_ticker)
    if not poly_markets:
        raise RuntimeError(f"Polymarket returned no markets for event id {event_id}.")
    if not kalshi_markets:
        raise RuntimeError(f"Kalshi returned no markets for ticker {kalshi_ticker}.")

    mappings = match_markets(poly_markets, kalshi_markets)
    if not mappings:
        raise RuntimeError(f"Failed to match any markets for `{row.polymarket_title}`.")

    return EventPair(
        id=f"event_{ordinal:03d}",
        name=row.polymarket_title or row.kalshi_title,
        polymarket_event_id=event_id,
        kalshi_event_ticker=kalshi_ticker,
        settlement_date=settlement_date,
        manually_verified=row.is_verified,
        markets_map=mappings,
        notes=row.notes or None,
    )


def merge_config(existing: Dict, event_pairs: List[EventPair]) -> Dict:
    config = dict(existing)
    config["event_pairs"] = [asdict(pair) for pair in event_pairs]

    if "monitoring" not in config:
        config["monitoring"] = DEFAULT_MONITORING.copy()
    if "cost_assumptions" not in config:
        config["cost_assumptions"] = DEFAULT_COSTS.copy()
    if "alerting" not in config:
        config["alerting"] = DEFAULT_ALERTING.copy()
    else:
        config["alerting"].setdefault("enabled", False)
        config["alerting"].setdefault("telegram_bot_token", "")
        config["alerting"].setdefault("telegram_chat_id", "")

    return config


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate config.json from Excel + API data.")
    parser.add_argument(
        "--excel",
        default="Kalshi vs Polymarket 候选对.xlsx",
        help="Path to the input Excel file.",
    )
    parser.add_argument(
        "--output",
        default="config.json",
        help="Path to the output config.json file.",
    )
    parser.add_argument(
        "--kalshi-api-key",
        default=None,
        help="Optional Kalshi API key for authenticated requests.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    excel_path = Path(args.excel)
    if not excel_path.exists():
        raise FileNotFoundError(f"Excel file not found: {excel_path}")

    rows = load_rows(excel_path)
    poly_client = PolymarketClient(base_url=POLY_BASE_URL, polling_interval=1)
    kalshi_client = KalshiClient(
        base_url=KALSHI_BASE_URL,
        polling_interval=1,
        api_key=args.kalshi_api_key,
    )

    event_pairs: List[EventPair] = []
    for row in rows:
        try:
            pair = build_event_pair(row, len(event_pairs) + 1, poly_client, kalshi_client)
            event_pairs.append(pair)
            print(f"[OK] Added pair for `{row.polymarket_title}` -> ticker `{pair.kalshi_event_ticker}`")
        except Exception as exc:
            print(f"[WARN] Skipping `{row.polymarket_title}` (row {row.index}): {exc}")

    if not event_pairs:
        raise RuntimeError("No event pairs were generated; aborting.")

    output_path = Path(args.output)
    if output_path.exists():
        with output_path.open("r", encoding="utf-8") as handle:
            existing = json.load(handle)
    else:
        existing = {}

    merged = merge_config(existing, event_pairs)
    if args.kalshi_api_key:
        merged["kalshi_api_key"] = args.kalshi_api_key

    with output_path.open("w", encoding="utf-8") as handle:
        json.dump(merged, handle, ensure_ascii=False, indent=2)

    print(f"\nWrote {len(event_pairs)} event pair(s) to {output_path}")


if __name__ == "__main__":
    main()
