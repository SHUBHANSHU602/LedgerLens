"""Normalization and reference extraction utilities for financial reconciliation."""

import re
from datetime import datetime, date
from typing import Any, Optional
import pandas as pd

try:
    from rapidfuzz import fuzz
except ModuleNotFoundError:
    class DummyFuzz:
        @staticmethod
        def token_set_ratio(s1, s2):
            t1, t2 = set(str(s1).upper().split()), set(str(s2).upper().split())
            union = t1.union(t2)
            return (len(t1.intersection(t2)) / len(union) * 100.0) if union else 0.0

        @staticmethod
        def partial_ratio(s1, s2):
            return 80.0 if str(s1).upper() in str(s2).upper() else 0.0

    fuzz = DummyFuzz()


def normalize_amount(val: Any) -> float:
    """Normalize numeric amount to a rounded 2-decimal float."""
    if val is None or pd.isna(val):
        return 0.0
    if isinstance(val, (int, float)):
        return round(float(val), 2)
    clean_str = re.sub(r"[^\d.-]", "", str(val))
    return round(float(clean_str), 2) if clean_str else 0.0


def normalize_date(val: Any) -> date:
    """Normalize date string or object to standard datetime.date."""
    if isinstance(val, date) and not isinstance(val, datetime):
        return val
    if isinstance(val, datetime):
        return val.date()
    val_str = str(val).strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(val_str, fmt).date()
        except ValueError:
            pass
    raise ValueError(f"Unable to parse date string: {val}")


def normalize_text(val: Any) -> str:
    """Normalize string text (uppercase, stripped, collapsed whitespace)."""
    if val is None or pd.isna(val):
        return ""
    return re.sub(r"\s+", " ", str(val).strip().upper())


def extract_reference(text: str) -> Optional[str]:
    """Extract standard order reference pattern (e.g. ORD-1001) from narration text."""
    norm_text = normalize_text(text)
    match = re.search(r"ORD-\d+", norm_text)
    return match.group(0) if match else None
