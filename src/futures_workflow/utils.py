import csv
import io
import json
import re
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional

from .constants import ASIA_SHANGHAI


def ensure_directory(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def parse_trade_date(value: str) -> date:
    if isinstance(value, date):
        return value
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return datetime.strptime(value, "%Y-%m-%d").date()
    if re.fullmatch(r"\d{8}", value):
        return datetime.strptime(value, "%Y%m%d").date()
    raise ValueError(f"Unsupported trade date format: {value}")


def format_trade_date(value: date) -> str:
    return value.strftime("%Y-%m-%d")


def compact_trade_date(value: date) -> str:
    return value.strftime("%Y%m%d")


def now_shanghai() -> datetime:
    return datetime.now(ASIA_SHANGHAI)


def iso_timestamp() -> str:
    return now_shanghai().isoformat()


def decode_bytes(payload: bytes) -> str:
    for encoding in ("utf-8", "utf-8-sig", "gb18030", "gbk"):
        try:
            return payload.decode(encoding)
        except UnicodeDecodeError:
            continue
    return payload.decode("utf-8", errors="replace")


def normalize_text(value: object) -> str:
    if value is None:
        return ""
    text = str(value).replace("\xa0", " ").strip()
    if text in {"", "-", "--", "None", "null", "nan", "NaN"}:
        return ""
    return text


def normalize_number(value: object) -> str:
    text = normalize_text(value)
    if not text:
        return ""
    text = text.replace(",", "")
    if text in {"", "."}:
        return ""
    try:
        number = Decimal(text)
    except InvalidOperation:
        return text
    if number == number.to_integral():
        return str(number.quantize(Decimal("1")))
    return format(number.normalize(), "f")


def normalize_contract_code(contract: str) -> str:
    return normalize_text(contract).replace(" ", "").upper()


def extract_alpha_prefix(contract: str) -> str:
    match = re.match(r"([A-Za-z]+)", contract or "")
    return match.group(1).upper() if match else ""


def extract_digits_suffix(contract: str) -> str:
    match = re.search(r"(\d+)$", contract or "")
    return match.group(1) if match else ""


def infer_czce_delivery_month(contract: str, trade_date: date) -> str:
    digits = extract_digits_suffix(contract)
    if len(digits) == 4:
        return digits
    if len(digits) != 3:
        return digits
    year_digit = int(digits[0])
    month = digits[1:]
    trade_yy = trade_date.year % 100
    base_tens = (trade_yy // 10) * 10
    candidates = [base_tens - 10 + year_digit, base_tens + year_digit, base_tens + 10 + year_digit]
    best = min(candidates, key=lambda candidate: abs(candidate - trade_yy))
    return f"{best:02d}{month}"


def relative_to_project(path: Path, project_root: Path) -> str:
    try:
        return str(path.relative_to(project_root))
    except ValueError:
        return str(path)


def previous_weekday(reference: date) -> date:
    current = reference - timedelta(days=1)
    while current.weekday() >= 5:
        current -= timedelta(days=1)
    return current


def safe_json_dumps(payload: Dict[str, object]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def write_json(path: Path, payload: Dict[str, object]) -> None:
    ensure_directory(path.parent)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def iter_csv_rows(path: Path) -> Iterator[Dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            yield row


def parse_pipe_table(raw_text: str) -> List[Dict[str, str]]:
    lines = [line.rstrip() for line in raw_text.splitlines() if line.strip()]
    header_index = next((idx for idx, line in enumerate(lines) if "合约代码" in line or "合约代码" in line.replace(" ", "")), None)
    if header_index is None:
        return []
    headers = [item.strip() for item in lines[header_index].split("|")]
    rows: List[Dict[str, str]] = []
    for line in lines[header_index + 1 :]:
        parts = [item.strip() for item in line.split("|")]
        if len(parts) < len(headers):
            parts.extend([""] * (len(headers) - len(parts)))
        row = dict(zip(headers, parts))
        rows.append(row)
    return rows


def read_html_tables(raw_text: str) -> List[Dict[str, str]]:
    import pandas as pd

    tables = pd.read_html(io.StringIO(raw_text))
    if not tables:
        return []
    frame = tables[0].fillna("")
    return frame.to_dict(orient="records")
