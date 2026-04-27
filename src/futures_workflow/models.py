from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional


@dataclass
class QuoteRow:
    trade_date: str
    exchange: str
    variety_code: str
    variety_name: str
    contract: str
    delivery_month: str
    open: str
    high: str
    low: str
    close: str
    prev_settlement: str
    settlement: str
    change_close: str
    change_settlement: str
    volume: str
    open_interest: str
    open_interest_change: str
    turnover: str
    source_url: str
    source_type: str
    retrieved_at: str
    raw_path: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @property
    def instrument_type(self) -> str:
        return "future"


@dataclass
class OptionQuoteRow:
    trade_date: str
    exchange: str
    product_code: str
    product_name: str
    contract: str
    underlying_exchange: str
    underlying_kind: str
    underlying_product_code: str
    underlying_contract: str
    option_type: str
    strike_price: str
    exercise_type: str
    expire_date: str
    last_trade_date: str
    open: str
    high: str
    low: str
    close: str
    prev_settlement: str
    settlement: str
    change_close: str
    change_settlement: str
    volume: str
    open_interest: str
    open_interest_change: str
    turnover: str
    delta: str
    implied_volatility: str
    exercise_volume: str
    source_url: str
    source_type: str
    retrieved_at: str
    raw_path: str
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @property
    def instrument_type(self) -> str:
        return "option"


@dataclass
class RawPayload:
    content: str
    url: str
    extension: str
    source_type: str
    meta: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SourceRunResult:
    exchange: str
    trade_date: str
    status: str
    dataset: str = "futures_daily_quotes"
    source_url: str = ""
    source_type: str = "official"
    raw_path: Optional[Path] = None
    row_count: int = 0
    rows: List[Any] = field(default_factory=list)
    message: str = ""
    error: str = ""

    def to_summary(self) -> Dict[str, Any]:
        return {
            "dataset": self.dataset,
            "exchange": self.exchange,
            "trade_date": self.trade_date,
            "status": self.status,
            "source_url": self.source_url,
            "source_type": self.source_type,
            "raw_path": str(self.raw_path) if self.raw_path else "",
            "row_count": self.row_count,
            "message": self.message,
            "error": self.error,
        }
