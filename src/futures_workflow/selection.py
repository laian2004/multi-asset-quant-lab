import hashlib
import json
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Set

from .constants import SUPPORTED_INSTRUMENT_GROUPS


def parse_selection(
    exchange_values: Iterable[str] = (),
    variety_values: Iterable[str] = (),
    product_values: Iterable[str] = (),
    underlying_values: Iterable[str] = (),
    contract_values: Iterable[str] = (),
    instrument_group: str = "futures",
    known_exchanges: Iterable[str] = (),
) -> "CrawlSelection":
    normalized_group = str(instrument_group or "futures").strip().lower()
    if normalized_group not in SUPPORTED_INSTRUMENT_GROUPS:
        raise ValueError(f"Unsupported instrument group: {instrument_group}")

    known = {value.strip().upper() for value in known_exchanges if str(value).strip()}
    selected_exchanges = _normalize_tokens(exchange_values)
    unknown_exchanges = sorted(exchange for exchange in selected_exchanges if known and exchange not in known)
    if unknown_exchanges:
        raise ValueError(f"Unsupported exchanges: {', '.join(unknown_exchanges)}")

    varieties_by_exchange: Dict[str, Set[str]] = {}
    for token in _normalize_tokens(list(variety_values or []) + list(product_values or [])):
        if ":" in token:
            exchange, variety_code = token.split(":", 1)
            exchange = exchange.strip().upper()
            variety_code = variety_code.strip().upper()
        else:
            if len(selected_exchanges) != 1:
                raise ValueError(
                    "Use EXCHANGE:VARIETY format for --variety when multiple exchanges are selected."
                )
            exchange = next(iter(selected_exchanges))
            variety_code = token
        if not exchange or not variety_code:
            raise ValueError(f"Invalid variety selector: {token}")
        if known and exchange not in known:
            raise ValueError(f"Unsupported exchange in variety selector: {exchange}")
        varieties_by_exchange.setdefault(exchange, set()).add(variety_code)
        selected_exchanges.add(exchange)

    underlyings_by_exchange = _parse_exchange_tokens(
        values=underlying_values,
        selected_exchanges=selected_exchanges,
        known=known,
        label="underlying",
    )
    contracts_by_exchange = _parse_exchange_tokens(
        values=contract_values,
        selected_exchanges=selected_exchanges,
        known=known,
        label="contract",
    )

    return CrawlSelection(
        instrument_group=normalized_group,
        exchanges=sorted(selected_exchanges),
        varieties_by_exchange={exchange: set(sorted(varieties)) for exchange, varieties in sorted(varieties_by_exchange.items())},
        underlyings_by_exchange=underlyings_by_exchange,
        contracts_by_exchange=contracts_by_exchange,
    )


@dataclass
class CrawlSelection:
    instrument_group: str = "futures"
    exchanges: List[str] = field(default_factory=list)
    varieties_by_exchange: Dict[str, Set[str]] = field(default_factory=dict)
    underlyings_by_exchange: Dict[str, Set[str]] = field(default_factory=dict)
    contracts_by_exchange: Dict[str, Set[str]] = field(default_factory=dict)

    @property
    def active(self) -> bool:
        return bool(
            self.exchanges
            or self.varieties_by_exchange
            or self.underlyings_by_exchange
            or self.contracts_by_exchange
            or self.instrument_group != "futures"
        )

    @property
    def has_row_filters(self) -> bool:
        return bool(self.exchanges or self.varieties_by_exchange or self.underlyings_by_exchange or self.contracts_by_exchange)

    def includes_instrument_group(self, group: str) -> bool:
        normalized = str(group).strip().lower()
        return self.instrument_group in {"all", normalized}

    def includes_exchange(self, exchange: str) -> bool:
        if not self.exchanges:
            return True
        return exchange.upper() in self.exchanges

    def has_variety_filter(self, exchange: str) -> bool:
        return exchange.upper() in self.varieties_by_exchange

    def has_filters_for_exchange(self, exchange: str) -> bool:
        exchange_key = exchange.upper()
        return any(
            exchange_key in bucket
            for bucket in (
                self.varieties_by_exchange,
                self.underlyings_by_exchange,
                self.contracts_by_exchange,
            )
        )

    def filter_rows(self, exchange: str, rows: List[Any]) -> List[Any]:
        allowed = self.varieties_by_exchange.get(exchange.upper())
        allowed_underlyings = self.underlyings_by_exchange.get(exchange.upper())
        allowed_contracts = self.contracts_by_exchange.get(exchange.upper())
        filtered = list(rows)
        if allowed:
            filtered = [
                row
                for row in filtered
                if _row_attr(row, "variety_code", "product_code").upper() in allowed
                or _row_attr(row, "underlying_product_code").upper() in allowed
            ]
        if allowed_underlyings:
            filtered = [
                row
                for row in filtered
                if _row_attr(row, "underlying_contract", "underlying_product_code", "contract").upper() in allowed_underlyings
            ]
        if allowed_contracts:
            filtered = [row for row in filtered if _row_attr(row, "contract").upper() in allowed_contracts]
        return filtered

    def to_summary(self) -> Dict[str, object]:
        return {
            "instrument_group": self.instrument_group,
            "exchanges": list(self.exchanges),
            "varieties": {exchange: sorted(varieties) for exchange, varieties in self.varieties_by_exchange.items()},
            "underlyings": {exchange: sorted(values) for exchange, values in self.underlyings_by_exchange.items()},
            "contracts": {exchange: sorted(values) for exchange, values in self.contracts_by_exchange.items()},
        }

    def selection_id(self, dataset_names: Iterable[str]) -> str:
        payload = self.to_summary()
        payload["datasets"] = sorted(str(name) for name in dataset_names)
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        return hashlib.sha1(encoded).hexdigest()[:16]


def _normalize_tokens(values: Iterable[str]) -> Set[str]:
    tokens: Set[str] = set()
    for value in values or []:
        for token in str(value).split(","):
            cleaned = token.strip().upper()
            if cleaned:
                tokens.add(cleaned)
    return tokens


def _parse_exchange_tokens(
    *,
    values: Iterable[str],
    selected_exchanges: Set[str],
    known: Set[str],
    label: str,
) -> Dict[str, Set[str]]:
    parsed: Dict[str, Set[str]] = {}
    for token in _normalize_tokens(values):
        if ":" in token:
            exchange, value = token.split(":", 1)
            exchange = exchange.strip().upper()
            value = value.strip().upper()
        else:
            if len(selected_exchanges) != 1:
                raise ValueError(f"Use EXCHANGE:{label.upper()} format for --{label} when multiple exchanges are selected.")
            exchange = next(iter(selected_exchanges))
            value = token
        if known and exchange not in known:
            raise ValueError(f"Unsupported exchange in {label} selector: {exchange}")
        parsed.setdefault(exchange, set()).add(value)
        selected_exchanges.add(exchange)
    return {exchange: set(sorted(values)) for exchange, values in sorted(parsed.items())}


def _row_attr(row: Any, *names: str) -> str:
    for name in names:
        if isinstance(row, dict):
            value = row.get(name, "")
        else:
            value = getattr(row, name, "")
        if value:
            return str(value)
    return ""
