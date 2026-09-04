"""Tests for Finance Controller batch orchestration."""

import pytest
import pandas as pd

from src.services.finance_controller import process_batch, BatchSummary, _classify_exception


def _make_results(rows):
    """Helper to create a minimal reconciliation results DataFrame."""
    return pd.DataFrame(rows)


def test_empty_batch():
    """Empty results should produce OPEN status."""
    df = _make_results([])
    batch = process_batch(df)
    assert batch.batch_status == "OPEN"
    assert batch.total_records == 0


def test_all_matched_batch():
    """All MATCHED should produce READY_TO_CLOSE."""
    df = _make_results([
        {"ledger_id": "ORD-1", "bank_id": "UTR-1", "status": "MATCHED", "matching_rule": "EXACT_REFERENCE",
         "score": 1.0, "reason": "Exact match", "decision_source": "deterministic", "amount_difference": 0.0},
        {"ledger_id": "ORD-2", "bank_id": "UTR-2", "status": "MATCHED", "matching_rule": "EXACT_AMOUNT_DATE",
         "score": 0.9, "reason": "Amount date", "decision_source": "deterministic", "amount_difference": 0.0},
    ])
    batch = process_batch(df)
    assert batch.batch_status == "READY_TO_CLOSE"
    assert batch.reconciled_count == 2
    assert batch.review_count == 0
    assert batch.unmatched_count == 0
    assert len(batch.exception_summary) == 0


def test_review_required_batch():
    """Batch with REVIEW records should be REVIEW_REQUIRED."""
    df = _make_results([
        {"ledger_id": "ORD-1", "bank_id": "UTR-1", "status": "MATCHED", "matching_rule": "EXACT_REFERENCE",
         "score": 1.0, "reason": "OK", "decision_source": "deterministic", "amount_difference": 0.0},
        {"ledger_id": "ORD-2", "bank_id": "UTR-2", "status": "REVIEW", "matching_rule": "AMBIGUOUS_CANDIDATES",
         "score": 0.7, "reason": "Two candidates", "decision_source": "deterministic", "amount_difference": 0.0},
    ])
    batch = process_batch(df)
    assert batch.batch_status == "REVIEW_REQUIRED"
    assert batch.review_count == 1
    assert len(batch.exception_summary) > 0
    assert any(e["exception_type"] == "AMBIGUOUS_MATCH" for e in batch.exception_summary)


def test_unmatched_exceptions():
    """Unmatched ledger should create MISSING_COUNTERPARTY exception."""
    df = _make_results([
        {"ledger_id": "ORD-1", "bank_id": "", "status": "UNMATCHED", "matching_rule": "NO_CANDIDATE",
         "score": 0.0, "reason": "No candidate", "decision_source": "deterministic", "amount_difference": 0.0},
    ])
    batch = process_batch(df)
    assert batch.batch_status == "REVIEW_REQUIRED"
    assert any(e["exception_type"] == "MISSING_COUNTERPARTY" for e in batch.exception_summary)


def test_fee_exception():
    """Fee difference should create FEE_ADJUSTMENT exception."""
    df = _make_results([
        {"ledger_id": "ORD-1", "bank_id": "UTR-1", "status": "REVIEW", "matching_rule": "SCORE_REVIEW",
         "score": 0.65, "reason": "Fee deduction", "decision_source": "deterministic", "amount_difference": 50.0},
    ])
    batch = process_batch(df)
    assert any(e["exception_type"] == "FEE_ADJUSTMENT" for e in batch.exception_summary)


def test_one_to_one_conflict_exception():
    """ONE_TO_ONE_CONFLICT rule should create corresponding exception."""
    df = _make_results([
        {"ledger_id": "ORD-1", "bank_id": "", "status": "REVIEW", "matching_rule": "ONE_TO_ONE_CONFLICT",
         "score": 0.8, "reason": "One-to-one conflict", "decision_source": "deterministic", "amount_difference": 0.0},
    ])
    batch = process_batch(df)
    assert any(e["exception_type"] == "ONE_TO_ONE_CONFLICT" for e in batch.exception_summary)


def test_ai_assisted_count():
    """AI-assisted matches should be counted separately."""
    df = _make_results([
        {"ledger_id": "ORD-1", "bank_id": "UTR-1", "status": "MATCHED", "matching_rule": "AI_CONFIRMED_MATCH",
         "score": 0.75, "reason": "AI confirmed", "decision_source": "groq", "amount_difference": 0.0},
        {"ledger_id": "ORD-2", "bank_id": "UTR-2", "status": "MATCHED", "matching_rule": "EXACT_REFERENCE",
         "score": 1.0, "reason": "Exact", "decision_source": "deterministic", "amount_difference": 0.0},
    ])
    batch = process_batch(df)
    assert batch.auto_resolved_count == 1
    assert batch.ai_assisted_count == 1


def test_batch_summary_serialization():
    """BatchSummary.to_dict() should produce a valid dictionary."""
    df = _make_results([
        {"ledger_id": "ORD-1", "bank_id": "UTR-1", "status": "MATCHED", "matching_rule": "EXACT_REFERENCE",
         "score": 1.0, "reason": "OK", "decision_source": "deterministic", "amount_difference": 0.0},
    ])
    batch = process_batch(df, run_id="TEST-RUN-001")
    d = batch.to_dict()
    assert d["run_id"] == "TEST-RUN-001"
    assert isinstance(d["exception_summary"], list)
    assert isinstance(d["recommended_actions"], list)


def test_custom_run_id():
    """Custom run_id should be preserved."""
    df = _make_results([])
    batch = process_batch(df, run_id="CUSTOM-123")
    assert batch.run_id == "CUSTOM-123"
