"""Data validation utilities for ledger, bank statement, and custom XLSX inputs."""

import os
from typing import Tuple, List, Optional, Dict, Any
import pandas as pd

try:
    from src.config import ReconciliationConfig, CONFIG
except ModuleNotFoundError:
    from config import ReconciliationConfig, CONFIG


def validate_ledger_schema(
    df: pd.DataFrame,
    config: ReconciliationConfig = CONFIG,
) -> Tuple[bool, List[str]]:
    """Validate ledger DataFrame schema and completeness."""
    errors = []
    if df is None:
        return False, ["Ledger dataset is None."]

    missing_cols = [c for c in ["order_id", "amount", "order_date"] if c not in df.columns]
    if missing_cols:
        errors.append(f"Ledger missing required schema columns: {missing_cols}")

    return len(errors) == 0, errors


def validate_bank_schema(
    df: pd.DataFrame,
    config: ReconciliationConfig = CONFIG,
) -> Tuple[bool, List[str]]:
    """Validate bank statement DataFrame schema and completeness."""
    errors = []
    if df is None:
        return False, ["Bank statement dataset is None."]

    missing_cols = [c for c in ["utr_reference", "credited_amount", "value_date"] if c not in df.columns]
    if missing_cols:
        errors.append(f"Bank statement missing required schema columns: {missing_cols}")

    return len(errors) == 0, errors


def validate_custom_data_paths(
    custom_dir: Optional[str] = None,
    config: ReconciliationConfig = CONFIG,
) -> Tuple[bool, Dict[str, str]]:
    """Validate existence of custom XLSX operational input datasets."""
    target_dir = custom_dir or config.LEDGERLENS_CUSTOM_DATA_DIR
    ledger_xlsx = os.path.join(target_dir, "ledger.xlsx")
    bank_xlsx = os.path.join(target_dir, "bank_statement.xlsx")

    found = {
        "ledger_xlsx": ledger_xlsx if os.path.exists(ledger_xlsx) else "",
        "bank_xlsx": bank_xlsx if os.path.exists(bank_xlsx) else "",
    }
    is_valid = bool(found["ledger_xlsx"] and found["bank_xlsx"])
    return is_valid, found
