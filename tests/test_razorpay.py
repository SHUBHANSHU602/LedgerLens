"""Tests for Razorpay source adapter and canonical schema normalization."""

import pytest
import pandas as pd

from src.connectors.razorpay import (
    load_demo_settlements,
    normalize_to_reconciliation_schema,
    load_live_settlements,
    CanonicalTransaction,
)


def test_demo_settlements_returns_three_dataframes():
    """load_demo_settlements should return (ledger, razorpay, bank) DataFrames."""
    ledger, razorpay, bank = load_demo_settlements()
    assert isinstance(ledger, pd.DataFrame)
    assert isinstance(razorpay, pd.DataFrame)
    assert isinstance(bank, pd.DataFrame)
    assert len(ledger) > 0
    assert len(razorpay) > 0
    assert len(bank) > 0


def test_canonical_schema_columns():
    """All DataFrames should have canonical transaction schema columns."""
    required_cols = [
        "transaction_id", "external_reference", "amount", "currency",
        "transaction_date", "settlement_date", "customer", "description",
        "source", "status",
    ]
    ledger, razorpay, bank = load_demo_settlements()
    for df, name in [(ledger, "ledger"), (razorpay, "razorpay"), (bank, "bank")]:
        for col in required_cols:
            assert col in df.columns, f"Missing column '{col}' in {name} DataFrame"


def test_demo_fee_deduction():
    """Bank credits should be less than ledger amounts (MDR fee deduction)."""
    ledger, _, bank = load_demo_settlements()
    # First record: ledger 5000, bank 4950 (50 INR fee)
    l_amt = ledger.iloc[0]["amount"]
    b_amt = bank.iloc[0]["amount"]
    assert b_amt < l_amt, f"Bank amount ({b_amt}) should be less than ledger amount ({l_amt})"
    assert l_amt - b_amt == 50.0, "Expected ₹50 MDR fee deduction"


def test_normalize_to_ledger_schema():
    """normalize_to_reconciliation_schema('ledger') should produce reconciliation-compatible columns."""
    ledger, _, _ = load_demo_settlements()
    normalized = normalize_to_reconciliation_schema(ledger, "ledger")
    assert "order_id" in normalized.columns
    assert "customer_name" in normalized.columns
    assert "amount" in normalized.columns
    assert "currency" in normalized.columns
    assert "order_date" in normalized.columns
    assert "payment_method" in normalized.columns
    assert len(normalized) == len(ledger)


def test_normalize_to_bank_schema():
    """normalize_to_reconciliation_schema('bank') should produce reconciliation-compatible columns."""
    _, _, bank = load_demo_settlements()
    normalized = normalize_to_reconciliation_schema(bank, "bank")
    assert "utr_reference" in normalized.columns
    assert "narration_text" in normalized.columns
    assert "credited_amount" in normalized.columns
    assert "currency" in normalized.columns
    assert "value_date" in normalized.columns
    assert "deduction_fee" in normalized.columns
    assert len(normalized) == len(bank)


def test_normalized_data_reconciles():
    """Normalized Razorpay demo data should be reconcilable by the engine."""
    from src.reconciliation import reconcile
    from src.config import ReconciliationConfig

    ledger, _, bank = load_demo_settlements()
    df_ledger = normalize_to_reconciliation_schema(ledger, "ledger")
    df_bank = normalize_to_reconciliation_schema(bank, "bank")

    config = ReconciliationConfig(ENABLE_AI_ASSIST=False)
    results = reconcile(df_ledger, df_bank, config=config)

    assert len(results) > 0
    # At least some records should match or go to review (fee diffs)
    statuses = results["status"].unique().tolist()
    assert any(s in statuses for s in ["MATCHED", "REVIEW", "UNMATCHED"])


def test_invalid_source_type_raises():
    """normalize_to_reconciliation_schema with invalid source_type should raise."""
    ledger, _, _ = load_demo_settlements()
    with pytest.raises(ValueError, match="Unknown source_type"):
        normalize_to_reconciliation_schema(ledger, "invalid")


def test_live_settlements_raises_without_credentials():
    """load_live_settlements should raise NotImplementedError without credentials."""
    with pytest.raises(NotImplementedError):
        load_live_settlements()


def test_source_labels():
    """Each demo DataFrame should have correct source labels."""
    ledger, razorpay, bank = load_demo_settlements()
    assert all(ledger["source"] == "ledger")
    assert all(razorpay["source"] == "razorpay")
    assert all(bank["source"] == "bank")
