import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.futures_workflow.models import OptionQuoteRow, QuoteRow
from src.futures_workflow.selection import parse_selection


def _row(exchange: str, variety_code: str) -> QuoteRow:
    return QuoteRow(
        trade_date="2026-04-16",
        exchange=exchange,
        variety_code=variety_code,
        variety_name=variety_code,
        contract=f"{variety_code}2605",
        delivery_month="2605",
        open="1",
        high="2",
        low="0.5",
        close="1.5",
        prev_settlement="1.2",
        settlement="1.4",
        change_close="0.3",
        change_settlement="0.2",
        volume="10",
        open_interest="20",
        open_interest_change="2",
        turnover="30",
        source_url="u",
        source_type="official",
        retrieved_at="2026-04-17T00:00:00+08:00",
        raw_path="data/raw/test.json",
    )


def _option_row(exchange: str, product_code: str, underlying_contract: str, contract: str) -> OptionQuoteRow:
    return OptionQuoteRow(
        trade_date="2026-04-16",
        exchange=exchange,
        product_code=product_code,
        product_name=product_code,
        contract=contract,
        underlying_exchange=exchange,
        underlying_kind="futures",
        underlying_product_code=product_code,
        underlying_contract=underlying_contract,
        option_type="call",
        strike_price="2500",
        exercise_type="european",
        expire_date="2026-04-22",
        last_trade_date="2026-04-22",
        open="1",
        high="2",
        low="0.5",
        close="1.5",
        prev_settlement="1.2",
        settlement="1.4",
        change_close="0.3",
        change_settlement="0.2",
        volume="10",
        open_interest="20",
        open_interest_change="2",
        turnover="30",
        delta="0.5",
        implied_volatility="0.2",
        exercise_volume="",
        source_url="u",
        source_type="official",
        retrieved_at="2026-04-17T00:00:00+08:00",
        raw_path="data/raw/test.json",
    )


class SelectionTests(unittest.TestCase):
    def test_parse_selection_accepts_single_exchange_shorthand(self):
        selection = parse_selection(
            exchange_values=["shfe"],
            variety_values=["cu,au"],
            known_exchanges=["SHFE", "CFFEX", "CZCE", "GFEX", "DCE"],
        )
        self.assertEqual(selection.exchanges, ["SHFE"])
        self.assertEqual(selection.to_summary()["varieties"], {"SHFE": ["AU", "CU"]})

    def test_parse_selection_accepts_exchange_scoped_varieties(self):
        selection = parse_selection(
            variety_values=["shfe:cu", "dce:a"],
            known_exchanges=["SHFE", "CFFEX", "CZCE", "GFEX", "DCE"],
        )
        self.assertEqual(selection.exchanges, ["DCE", "SHFE"])
        self.assertEqual(selection.to_summary()["varieties"], {"DCE": ["A"], "SHFE": ["CU"]})

    def test_parse_selection_requires_explicit_exchange_for_multi_exchange_varieties(self):
        with self.assertRaises(ValueError):
            parse_selection(
                exchange_values=[],
                variety_values=["CU"],
                known_exchanges=["SHFE", "CFFEX", "CZCE", "GFEX", "DCE"],
            )

    def test_filter_rows_keeps_only_selected_varieties(self):
        selection = parse_selection(
            exchange_values=["SHFE"],
            variety_values=["CU"],
            known_exchanges=["SHFE", "CFFEX", "CZCE", "GFEX", "DCE"],
        )
        rows = [_row("SHFE", "CU"), _row("SHFE", "AU")]
        filtered = selection.filter_rows("SHFE", rows)
        self.assertEqual([row.variety_code for row in filtered], ["CU"])

    def test_filter_rows_supports_underlying_and_contract_filters_without_variety_filter(self):
        selection = parse_selection(
            underlying_values=["SSE:510050"],
            contract_values=["SSE:510050C2604M02650"],
            instrument_group="options",
            known_exchanges=["SHFE", "CFFEX", "CZCE", "GFEX", "DCE", "SSE", "SZSE"],
        )
        rows = [
            _option_row("SSE", "510050", "510050", "510050C2604M02650"),
            _option_row("SSE", "510300", "510300", "510300C2604M04000"),
        ]
        filtered = selection.filter_rows("SSE", rows)
        self.assertEqual([row.contract for row in filtered], ["510050C2604M02650"])

    def test_selection_id_is_stable_and_changes_with_dataset_scope(self):
        selection = parse_selection(
            exchange_values=["SZSE"],
            instrument_group="options",
            known_exchanges=["SHFE", "CFFEX", "CZCE", "GFEX", "DCE", "SSE", "SZSE"],
        )
        first = selection.selection_id(["options_daily_quotes", "options_chain_matrix"])
        second = selection.selection_id(["options_chain_matrix", "options_daily_quotes"])
        third = selection.selection_id(["options_daily_quotes"])
        self.assertEqual(first, second)
        self.assertNotEqual(first, third)


if __name__ == "__main__":
    unittest.main()
