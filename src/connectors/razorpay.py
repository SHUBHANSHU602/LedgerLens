"""Razorpay Source Adapter — Normalizes Razorpay settlement data into canonical transaction schema.

Supports two modes:
  DEMO: Returns checked-in fixture data demonstrating the Razorpay settlement flow.
  LIVE: Optional Razorpay API integration when credentials exist (never required for tests/demo).

Canonical Transaction Schema:
  transaction_id, external_reference, amount, currency, transaction_date,
  settlement_date, customer, description, source, status
"""

import os
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass, asdict
import pandas as pd


@dataclass
class CanonicalTransaction:
    """Normalized transaction model shared across all source types."""
    transaction_id: str
    external_reference: str
    amount: float
    currency: str
    transaction_date: str
    settlement_date: str
    customer: str
    description: str
    source: str  # "ledger", "razorpay", "bank"
    status: str  # "CAPTURED", "SETTLED", "CREDITED", etc.

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Demo Fixtures
# ---------------------------------------------------------------------------

def _demo_ledger_records() -> List[CanonicalTransaction]:
    """Internal ledger orders for the Razorpay demo scenario."""
    return [
        CanonicalTransaction("ORD-RZP-001", "pay_RZP001", 5000.00, "INR", "2026-08-15", "", "Acme Corp", "Enterprise subscription payment", "ledger", "CAPTURED"),
        CanonicalTransaction("ORD-RZP-002", "pay_RZP002", 2500.00, "INR", "2026-08-15", "", "Beta Traders", "Quarterly invoice", "ledger", "CAPTURED"),
        CanonicalTransaction("ORD-RZP-003", "pay_RZP003", 10000.00, "INR", "2026-08-16", "", "Gamma Tech", "Annual license renewal", "ledger", "CAPTURED"),
        CanonicalTransaction("ORD-RZP-004", "pay_RZP004", 1500.00, "INR", "2026-08-17", "", "Delta Retail", "Product purchase", "ledger", "CAPTURED"),
        CanonicalTransaction("ORD-RZP-005", "pay_RZP005", 7500.00, "INR", "2026-08-17", "", "Epsilon Co", "Consulting fee", "ledger", "CAPTURED"),
    ]


def _demo_razorpay_settlements() -> List[CanonicalTransaction]:
    """Razorpay settlement records — includes settlement fees and next-day processing."""
    return [
        CanonicalTransaction("setl_RZP001", "pay_RZP001", 5000.00, "INR", "2026-08-15", "2026-08-16", "Acme Corp", "Razorpay settlement for pay_RZP001", "razorpay", "SETTLED"),
        CanonicalTransaction("setl_RZP002", "pay_RZP002", 2500.00, "INR", "2026-08-15", "2026-08-16", "Beta Traders", "Razorpay settlement for pay_RZP002", "razorpay", "SETTLED"),
        CanonicalTransaction("setl_RZP003", "pay_RZP003", 10000.00, "INR", "2026-08-16", "2026-08-17", "Gamma Tech", "Razorpay settlement for pay_RZP003", "razorpay", "SETTLED"),
        CanonicalTransaction("setl_RZP004", "pay_RZP004", 1500.00, "INR", "2026-08-17", "2026-08-18", "Delta Retail", "Razorpay settlement for pay_RZP004", "razorpay", "SETTLED"),
        CanonicalTransaction("setl_RZP005", "pay_RZP005", 7500.00, "INR", "2026-08-17", "2026-08-18", "Epsilon Co", "Razorpay settlement for pay_RZP005", "razorpay", "SETTLED"),
    ]


def _demo_bank_credits() -> List[CanonicalTransaction]:
    """Bank credits — net of Razorpay MDR fees, settled next day."""
    return [
        CanonicalTransaction("UTR-RZP-001", "pay_RZP001", 4950.00, "INR", "2026-08-16", "2026-08-16", "Razorpay Settlements", "NEFT/RAZORPAY/SETTLEMENT/ORD-RZP-001", "bank", "CREDITED"),
        CanonicalTransaction("UTR-RZP-002", "pay_RZP002", 2475.00, "INR", "2026-08-16", "2026-08-16", "Razorpay Settlements", "NEFT/RAZORPAY/SETTLEMENT/ORD-RZP-002", "bank", "CREDITED"),
        CanonicalTransaction("UTR-RZP-003", "pay_RZP003", 9900.00, "INR", "2026-08-17", "2026-08-17", "Razorpay Settlements", "NEFT/RAZORPAY/SETTLEMENT/ORD-RZP-003", "bank", "CREDITED"),
        CanonicalTransaction("UTR-RZP-004", "pay_RZP004", 1485.00, "INR", "2026-08-18", "2026-08-18", "Razorpay Settlements", "NEFT/RAZORPAY/SETTLEMENT/ORD-RZP-004", "bank", "CREDITED"),
        CanonicalTransaction("UTR-RZP-005", "pay_RZP005", 7425.00, "INR", "2026-08-18", "2026-08-18", "Razorpay Settlements", "NEFT/RAZORPAY/SETTLEMENT/ORD-RZP-005", "bank", "CREDITED"),
    ]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def load_demo_settlements() -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Load demo Razorpay fixture data as (ledger_df, razorpay_df, bank_df).

    Demonstrates the three-way reconciliation flow:
      Internal ledger (₹5000) → Razorpay settlement (₹5000) → Bank credit (₹4950, ₹50 MDR fee)

    Returns DataFrames in canonical transaction schema.
    """
    ledger = pd.DataFrame([t.to_dict() for t in _demo_ledger_records()])
    razorpay = pd.DataFrame([t.to_dict() for t in _demo_razorpay_settlements()])
    bank = pd.DataFrame([t.to_dict() for t in _demo_bank_credits()])
    return ledger, razorpay, bank


def normalize_to_reconciliation_schema(
    canonical_df: pd.DataFrame,
    source_type: str,
) -> pd.DataFrame:
    """Convert canonical transaction DataFrame to the reconciliation engine's expected schema.

    Args:
        canonical_df: DataFrame with canonical transaction columns.
        source_type: One of 'ledger' or 'bank'.

    Returns:
        DataFrame with columns matching the reconciliation engine's expected input schema.
    """
    if source_type == "ledger":
        return pd.DataFrame({
            "order_id": canonical_df["transaction_id"],
            "customer_name": canonical_df["customer"],
            "amount": canonical_df["amount"],
            "currency": canonical_df["currency"],
            "order_date": canonical_df["transaction_date"],
            "payment_method": "RAZORPAY",
        })
    elif source_type == "bank":
        return pd.DataFrame({
            "utr_reference": canonical_df["transaction_id"],
            "narration_text": canonical_df["description"],
            "credited_amount": canonical_df["amount"],
            "currency": canonical_df["currency"],
            "value_date": canonical_df.get("settlement_date", canonical_df["transaction_date"]),
            "deduction_fee": canonical_df["amount"].apply(lambda _: 0.0),  # Fee already deducted from amount
        })
    else:
        raise ValueError(f"Unknown source_type: {source_type}. Expected 'ledger' or 'bank'.")


def load_live_settlements(api_key: Optional[str] = None, api_secret: Optional[str] = None) -> pd.DataFrame:
    """Load settlements from live Razorpay API.

    This is a stub for optional live integration.
    When credentials are available, this would call:
      GET https://api.razorpay.com/v1/settlements

    Args:
        api_key: Razorpay API Key ID.
        api_secret: Razorpay API Key Secret.

    Returns:
        DataFrame in canonical transaction schema.

    Raises:
        NotImplementedError: Always, until live integration is configured.
    """
    key = api_key or os.getenv("RAZORPAY_KEY_ID", "")
    secret = api_secret or os.getenv("RAZORPAY_KEY_SECRET", "")

    if not key or not secret:
        raise NotImplementedError(
            "Live Razorpay integration requires RAZORPAY_KEY_ID and RAZORPAY_KEY_SECRET. "
            "Use load_demo_settlements() for demo/test mode."
        )

    # Placeholder for actual Razorpay API call
    raise NotImplementedError("Live Razorpay API integration not yet implemented. Use demo mode.")
