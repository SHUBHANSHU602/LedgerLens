"""Pytest suite for Phase 1, Phase 2 & Phase 3 financial reconciliation engine."""

import pytest
import pandas as pd
from unittest.mock import patch, MagicMock
from datetime import date
from src.config import ReconciliationConfig
from src.reconciliation import (
    normalize_amount,
    normalize_date,
    normalize_text,
    extract_reference,
    reconcile,
)


def test_normalization_utilities():
    """Verify normalization helper functions for amounts, dates, and text."""
    assert normalize_amount("$1,234.56") == 1234.56
    assert normalize_amount(1000) == 1000.0
    assert normalize_amount(None) == 0.0

    assert normalize_date("2026-08-01") == date(2026, 8, 1)
    assert normalize_date("01/08/2026") == date(2026, 8, 1)

    assert normalize_text("  hello   world  ") == "HELLO WORLD"
    assert extract_reference("UPI PAYMENT FOR ORD-1001 REF 123") == "ORD-1001"
    assert extract_reference("NO ORDER ID HERE") is None


def test_exact_reference_matching():
    """Verify exact reference match returns status MATCHED."""
    df_ledger = pd.DataFrame([{
        "order_id": "ORD-1001", "customer_name": "Cust A", "amount": 1500.0,
        "currency": "INR", "order_date": "2026-08-01", "payment_method": "UPI"
    }])
    df_bank = pd.DataFrame([{
        "utr_reference": "UTR5001", "narration_text": "CREDIT ORD-1001 SETTLEMENT",
        "credited_amount": 1500.0, "currency": "INR", "value_date": "2026-08-01", "deduction_fee": 0.0
    }])

    res = reconcile(df_ledger, df_bank)
    row = res.iloc[0]
    assert row["ledger_id"] == "ORD-1001"
    assert row["bank_id"] == "UTR5001"
    assert row["status"] == "MATCHED"
    assert row["matching_rule"] == "EXACT_REFERENCE"


def test_exact_amount_date_matching():
    """Verify amount + date matching when reference is missing in narration."""
    df_ledger = pd.DataFrame([{
        "order_id": "ORD-1002", "customer_name": "Cust B", "amount": 750.0,
        "currency": "INR", "order_date": "2026-08-02", "payment_method": "CARD"
    }])
    df_bank = pd.DataFrame([{
        "utr_reference": "UTR5002", "narration_text": "POS CARD DEPOSIT NO REF",
        "credited_amount": 750.0, "currency": "INR", "value_date": "2026-08-02", "deduction_fee": 0.0
    }])

    res = reconcile(df_ledger, df_bank)
    match_row = res[res["ledger_id"] == "ORD-1002"].iloc[0]
    assert match_row["status"] == "MATCHED"
    assert match_row["matching_rule"] == "EXACT_AMOUNT_DATE"


def test_fee_difference_remains_unresolved():
    """Verify reference match with fee difference stays REVIEW / UNRESOLVED without AI."""
    cfg = ReconciliationConfig(ENABLE_AI_ASSIST=False)
    df_ledger = pd.DataFrame([{
        "order_id": "ORD-1003", "customer_name": "Cust C", "amount": 5000.0,
        "currency": "INR", "order_date": "2026-08-03", "payment_method": "NEFT"
    }])
    df_bank = pd.DataFrame([{
        "utr_reference": "UTR5003", "narration_text": "NET SETTLEMENT ORD-1003",
        "credited_amount": 4950.0, "currency": "INR", "value_date": "2026-08-03", "deduction_fee": 50.0
    }])

    res = reconcile(df_ledger, df_bank, config=cfg)
    row = res.iloc[0]
    assert row["ledger_id"] == "ORD-1003"
    assert row["status"] in ("REVIEW", "UNRESOLVED")


def test_missing_bank_transaction():
    """Verify unmatched ledger record returns status UNMATCHED."""
    df_ledger = pd.DataFrame([{
        "order_id": "ORD-1004", "customer_name": "Cust D", "amount": 200.0,
        "currency": "INR", "order_date": "2026-08-04", "payment_method": "UPI"
    }])
    df_bank = pd.DataFrame(columns=["utr_reference", "narration_text", "credited_amount", "currency", "value_date", "deduction_fee"])

    res = reconcile(df_ledger, df_bank)
    row = res[res["ledger_id"] == "ORD-1004"].iloc[0]
    assert row["status"] == "UNMATCHED"


def test_currency_mismatch():
    """Verify currency mismatch returns UNRESOLVED/UNMATCHED."""
    df_ledger = pd.DataFrame([{
        "order_id": "ORD-1005", "customer_name": "Cust E", "amount": 1000.0,
        "currency": "INR", "order_date": "2026-08-05", "payment_method": "RTGS"
    }])
    df_bank = pd.DataFrame([{
        "utr_reference": "UTR5005", "narration_text": "FOREIGN WIRE ORD-1005",
        "credited_amount": 1000.0, "currency": "USD", "value_date": "2026-08-05", "deduction_fee": 0.0
    }])

    res = reconcile(df_ledger, df_bank)
    row = res[res["ledger_id"] == "ORD-1005"].iloc[0]
    assert row["status"] in ("UNRESOLVED", "UNMATCHED")


def test_date_window_behavior():
    """Verify date window boundaries."""
    cfg = ReconciliationConfig(DATE_WINDOW_DAYS=3, BROAD_DATE_WINDOW_DAYS=10, ENABLE_AI_ASSIST=False)
    df_ledger = pd.DataFrame([
        {"order_id": "ORD-1006", "customer_name": "Cust F", "amount": 1200.0, "currency": "INR", "order_date": "2026-08-01", "payment_method": "UPI"},
        {"order_id": "ORD-1007", "customer_name": "Cust G", "amount": 1400.0, "currency": "INR", "order_date": "2026-08-01", "payment_method": "UPI"},
    ])
    df_bank = pd.DataFrame([
        {"utr_reference": "UTR5006", "narration_text": "PAYMENT ORD-1006", "credited_amount": 1200.0, "currency": "INR", "value_date": "2026-08-03", "deduction_fee": 0.0},
        {"utr_reference": "UTR5007", "narration_text": "PAYMENT ORD-1007", "credited_amount": 1400.0, "currency": "INR", "value_date": "2026-08-25", "deduction_fee": 0.0},
    ])

    res = reconcile(df_ledger, df_bank, config=cfg)
    row_in_win = res[res["ledger_id"] == "ORD-1006"].iloc[0]
    row_out_win = res[res["ledger_id"] == "ORD-1007"].iloc[0]

    assert row_in_win["status"] == "MATCHED"
    assert row_out_win["status"] == "UNMATCHED"


# -----------------------------------------------------------------------------
# Phase 3 Mocked Groq AI Unit Tests (Zero External API Calls)
# -----------------------------------------------------------------------------

@patch("src.ai_matcher.os.getenv", return_value="mock_groq_api_key")
@patch("groq.Groq")
def test_ai_matcher_positive_match(mock_groq_cls, mock_getenv):
    """Mock Groq returning positive structured JSON match."""
    mock_client = MagicMock()
    mock_groq_cls.return_value = mock_client
    mock_response = MagicMock()
    mock_response.choices[0].message.content = '{"same_transaction": true, "selected_bank_id": "UTR5003", "reason": "Confirmed match with fee adjustment"}'
    mock_client.chat.completions.create.return_value = mock_response

    df_ledger = pd.DataFrame([{"order_id": "ORD-5003", "customer_name": "Cust H", "amount": 5000.0, "currency": "INR", "order_date": "2026-08-03", "payment_method": "NEFT"}])
    df_bank = pd.DataFrame([{"utr_reference": "UTR5003", "narration_text": "NET SETTLEMENT ORD-5003", "credited_amount": 4950.0, "currency": "INR", "value_date": "2026-08-03", "deduction_fee": 50.0}])

    res = reconcile(df_ledger, df_bank)
    row = res.iloc[0]
    assert row["status"] == "MATCHED"
    assert row["matching_rule"] == "AI_CONFIRMED_MATCH"
    assert row["decision_source"] == "groq"


@patch("src.ai_matcher.os.getenv", return_value="mock_groq_api_key")
@patch("groq.Groq")
def test_ai_matcher_negative_match(mock_groq_cls, mock_getenv):
    """Mock Groq returning negative match -> safe fallback to REVIEW."""
    mock_client = MagicMock()
    mock_groq_cls.return_value = mock_client
    mock_response = MagicMock()
    mock_response.choices[0].message.content = '{"same_transaction": false, "reason": "Transaction details conflict"}'
    mock_client.chat.completions.create.return_value = mock_response

    df_ledger = pd.DataFrame([{"order_id": "ORD-5004", "customer_name": "Cust I", "amount": 5000.0, "currency": "INR", "order_date": "2026-08-03", "payment_method": "NEFT"}])
    df_bank = pd.DataFrame([{"utr_reference": "UTR5004", "narration_text": "NET SETTLEMENT ORD-5004", "credited_amount": 4950.0, "currency": "INR", "value_date": "2026-08-03", "deduction_fee": 50.0}])

    res = reconcile(df_ledger, df_bank)
    row = res.iloc[0]
    assert row["status"] == "REVIEW"
    assert row["matching_rule"] == "AI_REVIEW_REQUIRED"
    assert row["decision_source"] == "groq"


@patch("src.ai_matcher.os.getenv", return_value="mock_groq_api_key")
@patch("groq.Groq")
def test_ai_matcher_malformed_json(mock_groq_cls, mock_getenv):
    """Mock Groq returning malformed JSON -> safe fallback to REVIEW."""
    mock_client = MagicMock()
    mock_groq_cls.return_value = mock_client
    mock_response = MagicMock()
    mock_response.choices[0].message.content = "{NOT VALID JSON STRING..."
    mock_client.chat.completions.create.return_value = mock_response

    df_ledger = pd.DataFrame([{"order_id": "ORD-5005", "customer_name": "Cust J", "amount": 5000.0, "currency": "INR", "order_date": "2026-08-03", "payment_method": "NEFT"}])
    df_bank = pd.DataFrame([{"utr_reference": "UTR5005", "narration_text": "NET SETTLEMENT ORD-5005", "credited_amount": 4950.0, "currency": "INR", "value_date": "2026-08-03", "deduction_fee": 50.0}])

    res = reconcile(df_ledger, df_bank)
    row = res.iloc[0]
    assert row["status"] == "REVIEW"


@patch("src.ai_matcher.os.getenv", return_value="mock_groq_api_key")
@patch("groq.Groq")
def test_ai_matcher_api_failure(mock_groq_cls, mock_getenv):
    """Mock Groq raising API exception -> safe fallback to REVIEW."""
    mock_client = MagicMock()
    mock_groq_cls.return_value = mock_client
    mock_client.chat.completions.create.side_effect = Exception("Rate Limit Exceeded")

    df_ledger = pd.DataFrame([{"order_id": "ORD-5006", "customer_name": "Cust K", "amount": 5000.0, "currency": "INR", "order_date": "2026-08-03", "payment_method": "NEFT"}])
    df_bank = pd.DataFrame([{"utr_reference": "UTR5006", "narration_text": "NET SETTLEMENT ORD-5006", "credited_amount": 4950.0, "currency": "INR", "value_date": "2026-08-03", "deduction_fee": 50.0}])

    res = reconcile(df_ledger, df_bank)
    row = res.iloc[0]
    assert row["status"] == "REVIEW"
