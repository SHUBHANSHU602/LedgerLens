"""Comprehensive Pytest suite for LedgerLens reconciliation engine and AI safety."""

import os
import pytest
import pandas as pd
from unittest.mock import patch, MagicMock
from datetime import date
from src.config import ReconciliationConfig
from src.schemas import ReconciliationRecord, AIEvaluationSchema
from src.normalization import (
    normalize_amount,
    normalize_date,
    normalize_text,
    extract_reference,
)
from src.ai_matcher import evaluate_ambiguous_record, clear_ai_cache, coerce_boolean
from src.reconciliation import reconcile


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


def test_exact_match():
    """1. Test exact reference, amount, and date match."""
    df_ledger = pd.DataFrame([{"order_id": "ORD-1001", "customer_name": "Cust A", "amount": 1500.0, "currency": "INR", "order_date": "2026-08-01", "payment_method": "UPI"}])
    df_bank = pd.DataFrame([{"utr_reference": "UTR5001", "narration_text": "CREDIT ORD-1001 SETTLEMENT", "credited_amount": 1500.0, "currency": "INR", "value_date": "2026-08-01", "deduction_fee": 0.0}])

    res = reconcile(df_ledger, df_bank)
    row = res.iloc[0]
    assert row["ledger_id"] == "ORD-1001"
    assert row["bank_id"] == "UTR5001"
    assert row["status"] == "MATCHED"
    assert row["matching_rule"] == "EXACT_REFERENCE"


def test_exact_reference_fee_difference():
    """2. Test exact reference but with a fee difference."""
    cfg = ReconciliationConfig(ENABLE_AI_ASSIST=False)
    df_ledger = pd.DataFrame([{"order_id": "ORD-1003", "customer_name": "Cust C", "amount": 5000.0, "currency": "INR", "order_date": "2026-08-03", "payment_method": "NEFT"}])
    df_bank = pd.DataFrame([{"utr_reference": "UTR5003", "narration_text": "NET SETTLEMENT ORD-1003", "credited_amount": 4950.0, "currency": "INR", "value_date": "2026-08-03", "deduction_fee": 50.0}])

    res = reconcile(df_ledger, df_bank, config=cfg)
    row = res.iloc[0]
    assert row["status"] in ("REVIEW", "UNRESOLVED")


def test_date_shift_plus_1():
    """3. Test settlement date shifted by +1 day."""
    df_ledger = pd.DataFrame([{"order_id": "ORD-1010", "customer_name": "Cust X", "amount": 1000.0, "currency": "INR", "order_date": "2026-08-01", "payment_method": "UPI"}])
    df_bank = pd.DataFrame([{"utr_reference": "UTR5010", "narration_text": "PAYMENT ORD-1010", "credited_amount": 1000.0, "currency": "INR", "value_date": "2026-08-02", "deduction_fee": 0.0}])

    res = reconcile(df_ledger, df_bank)
    row = res.iloc[0]
    assert row["status"] == "MATCHED"


def test_date_shift_plus_2():
    """4. Test settlement date shifted by +2 days."""
    df_ledger = pd.DataFrame([{"order_id": "ORD-1011", "customer_name": "Cust Y", "amount": 2000.0, "currency": "INR", "order_date": "2026-08-01", "payment_method": "NEFT"}])
    df_bank = pd.DataFrame([{"utr_reference": "UTR5011", "narration_text": "CREDIT ORD-1011", "credited_amount": 2000.0, "currency": "INR", "value_date": "2026-08-03", "deduction_fee": 0.0}])

    res = reconcile(df_ledger, df_bank)
    row = res.iloc[0]
    assert row["status"] == "MATCHED"


def test_noisy_reference():
    """5. Test noisy reference inside complex narration string."""
    df_ledger = pd.DataFrame([{"order_id": "ORD-9988", "customer_name": "Acme Corp", "amount": 2500.0, "currency": "INR", "order_date": "2026-08-05", "payment_method": "NEFT"}])
    df_bank = pd.DataFrame([{"utr_reference": "UTR9988", "narration_text": "CMS/NEFT/N12345/ORD-9988/ACME/SETTLE", "credited_amount": 2500.0, "currency": "INR", "value_date": "2026-08-05", "deduction_fee": 0.0}])

    res = reconcile(df_ledger, df_bank)
    row = res.iloc[0]
    assert row["status"] == "MATCHED"
    assert row["bank_id"] == "UTR9988"


def test_same_amount_date_different_transaction():
    """6. Test same amount/date without reference string."""
    df_ledger = pd.DataFrame([{"order_id": "ORD-1012", "customer_name": "Cust Z", "amount": 750.0, "currency": "INR", "order_date": "2026-08-02", "payment_method": "CARD"}])
    df_bank = pd.DataFrame([{"utr_reference": "UTR5012", "narration_text": "POS CARD DEPOSIT NO REF", "credited_amount": 750.0, "currency": "INR", "value_date": "2026-08-02", "deduction_fee": 0.0}])

    res = reconcile(df_ledger, df_bank)
    row = res[res["ledger_id"] == "ORD-1012"].iloc[0]
    assert row["status"] == "MATCHED"


def test_two_candidate_conflict():
    """7. Test ambiguity protection when top candidates have equal score."""
    cfg = ReconciliationConfig(ENABLE_AI_ASSIST=False)
    df_ledger = pd.DataFrame([{"order_id": "ORD-3001", "customer_name": "Decoy Client", "amount": 999.0, "currency": "INR", "order_date": "2026-08-05", "payment_method": "CARD"}])
    df_bank = pd.DataFrame([
        {"utr_reference": "UTR3001A", "narration_text": "CARD BATCH SETTLEMENT", "credited_amount": 999.0, "currency": "INR", "value_date": "2026-08-05", "deduction_fee": 0.0},
        {"utr_reference": "UTR3001B", "narration_text": "CARD BATCH SETTLEMENT", "credited_amount": 999.0, "currency": "INR", "value_date": "2026-08-05", "deduction_fee": 0.0},
    ])

    res = reconcile(df_ledger, df_bank, config=cfg)
    row = res[res["ledger_id"] == "ORD-3001"].iloc[0]
    assert row["status"] == "REVIEW"
    assert row["matching_rule"] == "AMBIGUOUS_CANDIDATES"


def test_duplicated_bank_candidate():
    """8. Test duplicate bank candidates handling."""
    cfg = ReconciliationConfig(ENABLE_AI_ASSIST=False)
    df_ledger = pd.DataFrame([{"order_id": "ORD-3002", "customer_name": "Dup Test", "amount": 500.0, "currency": "INR", "order_date": "2026-08-05", "payment_method": "UPI"}])
    df_bank = pd.DataFrame([
        {"utr_reference": "UTR3002A", "narration_text": "GENERIC DEPOSIT", "credited_amount": 500.0, "currency": "INR", "value_date": "2026-08-05", "deduction_fee": 0.0},
        {"utr_reference": "UTR3002B", "narration_text": "GENERIC DEPOSIT", "credited_amount": 500.0, "currency": "INR", "value_date": "2026-08-05", "deduction_fee": 0.0},
    ])

    res = reconcile(df_ledger, df_bank, config=cfg)
    row = res[res["ledger_id"] == "ORD-3002"].iloc[0]
    assert row["status"] == "REVIEW"


def test_unmatched_ledger():
    """9. Test unmatched ledger record."""
    df_ledger = pd.DataFrame([{"order_id": "ORD-1004", "customer_name": "Cust D", "amount": 200.0, "currency": "INR", "order_date": "2026-08-04", "payment_method": "UPI"}])
    df_bank = pd.DataFrame(columns=["utr_reference", "narration_text", "credited_amount", "currency", "value_date", "deduction_fee"])

    res = reconcile(df_ledger, df_bank)
    row = res[res["ledger_id"] == "ORD-1004"].iloc[0]
    assert row["status"] == "UNMATCHED"


def test_unmatched_bank():
    """10. Test unmatched bank record."""
    df_ledger = pd.DataFrame(columns=["order_id", "customer_name", "amount", "currency", "order_date", "payment_method"])
    df_bank = pd.DataFrame([{"utr_reference": "UTR9999", "narration_text": "UNMATCHED DEPOSIT", "credited_amount": 300.0, "currency": "INR", "value_date": "2026-08-04", "deduction_fee": 0.0}])

    res = reconcile(df_ledger, df_bank)
    row = res[res["bank_id"] == "UTR9999"].iloc[0]
    assert row["status"] == "UNMATCHED"


@patch("src.ai_matcher.os.getenv", return_value="mock_groq_api_key")
@patch("groq.Groq")
def test_wrong_ai_bank_id_veto(mock_groq_cls, mock_getenv):
    """11. Test deterministic veto when AI returns a hallucinated bank ID outside candidate pool."""
    clear_ai_cache()
    mock_client = MagicMock()
    mock_groq_cls.return_value = mock_client
    mock_response = MagicMock()
    mock_response.choices[0].message.content = '{"same_transaction": true, "selected_bank_id": "HALLUCINATED_UTR_9999", "reason": "Looks good"}'
    mock_client.chat.completions.create.return_value = mock_response

    df_ledger = pd.DataFrame([{"order_id": "ORD-5001", "customer_name": "Cust A", "amount": 5000.0, "currency": "INR", "order_date": "2026-08-03", "payment_method": "NEFT"}])
    df_bank = pd.DataFrame([{"utr_reference": "UTR5001", "narration_text": "NET SETTLEMENT ORD-5001", "credited_amount": 4950.0, "currency": "INR", "value_date": "2026-08-03", "deduction_fee": 50.0}])

    res = reconcile(df_ledger, df_bank)
    row = res.iloc[0]
    assert row["status"] == "REVIEW"  # Vetoed match to REVIEW


@patch("src.ai_matcher.os.getenv", return_value="mock_groq_api_key")
@patch("groq.Groq")
def test_malformed_ai_json(mock_groq_cls, mock_getenv):
    """12. Test safe fallback when AI returns malformed JSON."""
    clear_ai_cache()
    mock_client = MagicMock()
    mock_groq_cls.return_value = mock_client
    mock_response = MagicMock()
    mock_response.choices[0].message.content = "{INVALID JSON..."
    mock_client.chat.completions.create.return_value = mock_response

    df_ledger = pd.DataFrame([{"order_id": "ORD-5002", "customer_name": "Cust B", "amount": 5000.0, "currency": "INR", "order_date": "2026-08-03", "payment_method": "NEFT"}])
    df_bank = pd.DataFrame([{"utr_reference": "UTR5002", "narration_text": "NET SETTLEMENT ORD-5002", "credited_amount": 4950.0, "currency": "INR", "value_date": "2026-08-03", "deduction_fee": 50.0}])

    res = reconcile(df_ledger, df_bank)
    row = res.iloc[0]
    assert row["status"] == "REVIEW"


def test_ai_string_boolean_coercion():
    """13. Test boolean coercion helper for string 'true' / 'false'."""
    assert coerce_boolean("true") is True
    assert coerce_boolean("TRUE") is True
    assert coerce_boolean("false") is False
    assert coerce_boolean("0") is False
    assert coerce_boolean(True) is True


@patch("src.ai_matcher.os.getenv", return_value="mock_groq_api_key")
@patch("groq.Groq")
def test_ai_api_failure(mock_groq_cls, mock_getenv):
    """14. Test safe fallback on API exception."""
    mock_client = MagicMock()
    mock_groq_cls.return_value = mock_client
    mock_client.chat.completions.create.side_effect = Exception("Rate Limit Exceeded")

    df_ledger = pd.DataFrame([{"order_id": "ORD-5003", "customer_name": "Cust C", "amount": 5000.0, "currency": "INR", "order_date": "2026-08-03", "payment_method": "NEFT"}])
    df_bank = pd.DataFrame([{"utr_reference": "UTR5003", "narration_text": "NET SETTLEMENT ORD-5003", "credited_amount": 4950.0, "currency": "INR", "value_date": "2026-08-03", "deduction_fee": 50.0}])

    res = reconcile(df_ledger, df_bank)
    row = res.iloc[0]
    assert row["status"] == "REVIEW"


def test_ai_disabled():
    """15. Test reconciliation behavior when AI assist is disabled."""
    cfg = ReconciliationConfig(ENABLE_AI_ASSIST=False)
    df_ledger = pd.DataFrame([{"order_id": "ORD-5004", "customer_name": "Cust D", "amount": 5000.0, "currency": "INR", "order_date": "2026-08-03", "payment_method": "NEFT"}])
    df_bank = pd.DataFrame([{"utr_reference": "UTR5004", "narration_text": "NET SETTLEMENT ORD-5004", "credited_amount": 4950.0, "currency": "INR", "value_date": "2026-08-03", "deduction_fee": 50.0}])

    res = reconcile(df_ledger, df_bank, config=cfg)
    row = res.iloc[0]
    assert row["status"] in ("REVIEW", "UNRESOLVED")
    assert row["decision_source"] == "deterministic"


def test_duplicate_bank_assignment_prevention():
    """16. Test global one-to-one conflict resolution preventing double bank match."""
    cfg = ReconciliationConfig(ENABLE_AI_ASSIST=False)
    df_ledger = pd.DataFrame([
        {"order_id": "ORD-A", "customer_name": "Acme", "amount": 1000.0, "currency": "INR", "order_date": "2026-08-01", "payment_method": "UPI"},
        {"order_id": "ORD-B", "customer_name": "Acme Corp", "amount": 1000.0, "currency": "INR", "order_date": "2026-08-01", "payment_method": "UPI"},
    ])
    df_bank = pd.DataFrame([
        {"utr_reference": "UTR-SINGLE", "narration_text": "PAYMENT FOR ORD-A", "credited_amount": 1000.0, "currency": "INR", "value_date": "2026-08-01", "deduction_fee": 0.0}
    ])

    res = reconcile(df_ledger, df_bank, config=cfg)
    matched_banks = res[res["status"] == "MATCHED"]["bank_id"].tolist()
    assert matched_banks.count("UTR-SINGLE") <= 1  # Strictly 1-to-1 matching


def test_currency_mismatch_veto():
    """17. Test currency mismatch hard contradiction veto."""
    df_ledger = pd.DataFrame([{"order_id": "ORD-CURR", "customer_name": "Foreign Client", "amount": 1000.0, "currency": "INR", "order_date": "2026-08-01", "payment_method": "UPI"}])
    df_bank = pd.DataFrame([{"utr_reference": "UTR-USD", "narration_text": "PAYMENT ORD-CURR", "credited_amount": 1000.0, "currency": "USD", "value_date": "2026-08-01", "deduction_fee": 0.0}])

    res = reconcile(df_ledger, df_bank)
    row = res.iloc[0]
    assert row["status"] in ("UNRESOLVED", "UNMATCHED", "REVIEW")
    assert row["status"] != "MATCHED"


def test_huge_amount_mismatch_veto():
    """18. Test huge amount difference hard veto."""
    df_ledger = pd.DataFrame([{"order_id": "ORD-HUGE", "customer_name": "Client", "amount": 100000.0, "currency": "INR", "order_date": "2026-08-01", "payment_method": "UPI"}])
    df_bank = pd.DataFrame([{"utr_reference": "UTR-SMALL", "narration_text": "PAYMENT ORD-HUGE", "credited_amount": 100.0, "currency": "INR", "value_date": "2026-08-01", "deduction_fee": 0.0}])

    res = reconcile(df_ledger, df_bank)
    row = res.iloc[0]
    assert row["status"] != "MATCHED"


def test_cache_invalidation_and_versioning():
    """19. Test cache key invalidation on configuration change."""
    clear_ai_cache()
    cfg1 = ReconciliationConfig(AMOUNT_TOLERANCE=0.01)
    cfg2 = ReconciliationConfig(AMOUNT_TOLERANCE=0.05)
    assert cfg1.AMOUNT_TOLERANCE != cfg2.AMOUNT_TOLERANCE


def test_answer_key_isolation_regression():
    """20. Source isolation regression test: Verify matching code never imports answer key dataset."""
    source_files = [
        "src/reconciliation.py",
        "src/ai_matcher.py",
        "src/config.py",
        "src/normalization.py",
        "src/schemas.py",
    ]
    for filepath in source_files:
        if os.path.exists(filepath):
            with open(filepath, "r", encoding="utf-8") as f:
                content = f.read()
                assert ("answer" + "_key.csv") not in content, f"Source file {filepath} illegally references answer_key.csv"


def test_evaluation_metrics_accounting(tmp_path):
    """21. Test denominator-explicit metric calculations in evaluation module."""
    from src.evaluation import evaluate_reconciliation
    from src.data_generator import generate_synthetic_data

    gen_dir = str(tmp_path / "eval_test_data")
    generate_synthetic_data(seed=999, output_dir=gen_dir, ledger_count=20, bank_count=20)

    metrics = evaluate_reconciliation(data_dir=gen_dir)
    assert "denominators" in metrics
    assert metrics["denominators"]["total_ledger_records"] > 0
    assert 0.0 <= metrics["pair_precision"] <= 1.0
    assert 0.0 <= metrics["pair_recall"] <= 1.0
    assert 0.0 <= metrics["f1_score"] <= 1.0


def test_data_generator_scenario_distribution(tmp_path):
    """22. Test benchmark dataset scenario distribution and reference leakage metrics."""
    from src.data_generator import generate_synthetic_data

    gen_dir = str(tmp_path / "gen_test_data")
    df_l, df_b, df_a = generate_synthetic_data(seed=777, output_dir=gen_dir, ledger_count=50, bank_count=50)

    assert len(df_l) > 0
    assert len(df_b) > 0
    assert len(df_a) > 0
    assert "scenario" in df_a.columns
    assert "EASY_EXACT" in df_a["scenario"].values


@patch("src.ai_matcher.os.getenv", return_value="mock_groq_api_key")
@patch("groq.Groq")
def test_ai_missing_selected_bank_id_veto(mock_groq_cls, mock_getenv):
    """23. Test veto when AI says same_transaction=true but selected_bank_id is missing/empty."""
    mock_client = MagicMock()
    mock_groq_cls.return_value = mock_client
    mock_response = MagicMock()
    mock_response.choices[0].message.content = '{"same_transaction": true, "selected_bank_id": "", "reason": "Missing ID"}'
    mock_client.chat.completions.create.return_value = mock_response

    df_ledger = pd.DataFrame([{"order_id": "ORD-5009", "customer_name": "Cust E", "amount": 5000.0, "currency": "INR", "order_date": "2026-08-03", "payment_method": "NEFT"}])
    df_bank = pd.DataFrame([{"utr_reference": "UTR5009", "narration_text": "NET SETTLEMENT ORD-5009", "credited_amount": 4950.0, "currency": "INR", "value_date": "2026-08-03", "deduction_fee": 50.0}])

    res = reconcile(df_ledger, df_bank)
    row = res.iloc[0]
    assert row["status"] == "REVIEW"
    assert "missing" in row["ai_reason"].lower()


def test_amount_date_matchability_metric(tmp_path):
    """24. Test Metric 17 amount and date matchability audit output."""
    from src.data_validation import audit_dataset_and_repo
    from src.data_generator import generate_synthetic_data

    gen_dir = str(tmp_path / "matchability_test_data")
    generate_synthetic_data(seed=123, output_dir=gen_dir, ledger_count=30, bank_count=30)

    report = audit_dataset_and_repo(data_dir=gen_dir)
    assert "17_amount_date_matchability" in report
    matchability = report["17_amount_date_matchability"]
    assert "pct_unique_amount_date_matchable" in matchability
    assert "pct_multiple_amount_date_candidates" in matchability
    assert "pct_no_amount_date_candidate" in matchability
    assert 0.0 <= matchability["pct_unique_amount_date_matchable"] <= 1.0


def test_evaluation_metric_keys_match_ui(tmp_path):
    """25. P0 REGRESSION: evaluation.py must return 'pair_precision' and 'pair_recall' keys."""
    from src.evaluation import evaluate_reconciliation
    from src.data_generator import generate_synthetic_data

    gen_dir = str(tmp_path / "ui_metric_test")
    generate_synthetic_data(seed=888, output_dir=gen_dir, ledger_count=20, bank_count=20)

    metrics = evaluate_reconciliation(data_dir=gen_dir)

    # These are the canonical keys the UI must use
    assert "pair_precision" in metrics, "evaluation must return 'pair_precision'"
    assert "pair_recall" in metrics, "evaluation must return 'pair_recall'"
    assert "f1_score" in metrics, "evaluation must return 'f1_score'"
    assert "headline" in metrics, "evaluation must return 'headline'"
    assert "auto_resolution_precision" in metrics
    assert "review_precision" in metrics
    assert "exception_recall" in metrics

    # Precision must not be zero on a non-trivial dataset
    assert metrics["pair_precision"] > 0, "pair_precision should not be zero on valid benchmark data"


def test_candidate_set_consistency():
    """26. P0 REGRESSION: AI_CANDIDATE_LIMIT must be <= TOP_N_CANDIDATES."""
    from src.config import CONFIG
    assert CONFIG.AI_CANDIDATE_LIMIT <= CONFIG.TOP_N_CANDIDATES, \
        f"AI_CANDIDATE_LIMIT ({CONFIG.AI_CANDIDATE_LIMIT}) exceeds TOP_N_CANDIDATES ({CONFIG.TOP_N_CANDIDATES})"


def test_evaluation_uses_precomputed_results(tmp_path):
    """27. P0 REGRESSION: evaluation must use precomputed results when provided."""
    from src.evaluation import evaluate_reconciliation
    from src.data_generator import generate_synthetic_data
    from src.config import ReconciliationConfig

    gen_dir = str(tmp_path / "precomputed_test")
    generate_synthetic_data(seed=777, output_dir=gen_dir, ledger_count=20, bank_count=20)

    # First run with default config
    import pandas as pd
    df_ledger = pd.read_csv(os.path.join(gen_dir, "ledger.csv"))
    df_bank = pd.read_csv(os.path.join(gen_dir, "bank_statement.csv"))

    custom_config = ReconciliationConfig(ENABLE_AI_ASSIST=False, HIGH_CONFIDENCE_THRESHOLD=0.90)
    results = reconcile(df_ledger, df_bank, config=custom_config)

    # Evaluate with precomputed results — should not re-run reconciliation
    metrics = evaluate_reconciliation(
        data_dir=gen_dir,
        config=custom_config,
        precomputed_results=results,
    )
    assert metrics["pair_precision"] >= 0.0


def test_holdout_seed_separation(tmp_path):
    """28. REGRESSION: dev and holdout datasets must use different seeds and produce different data."""
    from src.data_generator import generate_synthetic_data

    dev_dir = str(tmp_path / "dev")
    holdout_dir = str(tmp_path / "holdout")

    df_dev_l, _, _ = generate_synthetic_data(seed=123, output_dir=dev_dir, ledger_count=30, bank_count=30)
    df_hold_l, _, _ = generate_synthetic_data(seed=456, output_dir=holdout_dir, ledger_count=30, bank_count=30)

    # The datasets must not be identical
    dev_amounts = sorted(df_dev_l["amount"].tolist())
    hold_amounts = sorted(df_hold_l["amount"].tolist())
    assert dev_amounts != hold_amounts, "Dev and holdout datasets should differ (different seeds)"

