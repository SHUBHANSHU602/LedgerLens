"""Deterministic & Evidence-based Financial Reconciliation Engine (Phase 3)."""

import re
from datetime import datetime, date
from typing import Dict, Any, List, Optional, Tuple
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

try:
    from src.config import ReconciliationConfig, CONFIG
except ModuleNotFoundError:
    from config import ReconciliationConfig, CONFIG

try:
    from src.ai_matcher import evaluate_ambiguous_record
except ModuleNotFoundError:
    try:
        from ai_matcher import evaluate_ambiguous_record
    except ModuleNotFoundError:
        evaluate_ambiguous_record = None


def normalize_amount(val: Any) -> float:
    """Normalize numeric amount to 2-decimal float."""
    if val is None or pd.isna(val):
        return 0.0
    if isinstance(val, (int, float)):
        return round(float(val), 2)
    clean_str = re.sub(r"[^\d.-]", "", str(val))
    return round(float(clean_str), 2) if clean_str else 0.0


def normalize_date(val: Any) -> date:
    """Normalize date inputs to datetime.date object."""
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
    """Normalize string text (uppercase, stripped, single spaces)."""
    if val is None or pd.isna(val):
        return ""
    return re.sub(r"\s+", " ", str(val).strip().upper())


def extract_reference(text: str) -> Optional[str]:
    """Extract standard order reference (e.g. ORD-1001) from narration text."""
    norm_text = normalize_text(text)
    match = re.search(r"ORD-\d+", norm_text)
    return match.group(0) if match else None


def compute_evidence_score(
    l_row: pd.Series,
    b_row: pd.Series,
    config: ReconciliationConfig = CONFIG,
) -> Tuple[float, Dict[str, float]]:
    """Compute weighted multi-factor evidence score between ledger and bank row."""
    l_id, l_amt, l_date = l_row["order_id"], l_row["norm_amount"], l_row["norm_date"]
    l_cust = l_row.get("customer_name", "")

    b_narration, b_ref = b_row["norm_narration"], b_row["extracted_ref"]
    b_amt, b_date = b_row["norm_amount"], b_row["norm_date"]

    if b_ref == l_id or (l_id and l_id in b_narration):
        ref_score = 1.0
    elif l_id:
        fuzzy_ref_ratio = fuzz.token_set_ratio(l_id, b_narration) / 100.0
        ref_score = max(0.0, (fuzzy_ref_ratio - 0.5) * 2.0)
    else:
        ref_score = 0.0

    amt_diff, fee_amt = abs(l_amt - b_amt), l_amt - b_amt
    if amt_diff <= config.AMOUNT_TOLERANCE:
        amount_score = 1.0
    elif 0 < fee_amt <= config.MAX_FEE_AMOUNT:
        amount_score = 0.40
    elif amt_diff <= (l_amt * config.BROAD_AMOUNT_TOLERANCE_PCT):
        amount_score = max(0.20, 0.80 - (amt_diff / (l_amt * config.BROAD_AMOUNT_TOLERANCE_PCT)))
    else:
        amount_score = 0.0

    date_diff = abs((l_date - b_date).days)
    if date_diff == 0:
        date_score = 1.0
    elif date_diff <= config.DATE_WINDOW_DAYS:
        date_score = 1.0 - (date_diff * 0.05)
    elif date_diff <= config.BROAD_DATE_WINDOW_DAYS:
        date_score = max(0.30, 0.85 - ((date_diff - config.DATE_WINDOW_DAYS) * 0.08))
    else:
        date_score = 0.0

    if l_cust and b_narration:
        cust_norm = normalize_text(l_cust)
        text_score = fuzz.partial_ratio(cust_norm, b_narration) / 100.0
    else:
        text_score = 0.5

    total_score = round(
        (config.W_REF * ref_score) +
        (config.W_AMOUNT * amount_score) +
        (config.W_DATE * date_score) +
        (config.W_TEXT * text_score),
        4,
    )
    return total_score, {"ref": round(ref_score, 2), "amount": round(amount_score, 2), "date": round(date_score, 2), "text": round(text_score, 2)}


def reconcile(
    df_ledger: pd.DataFrame,
    df_bank: pd.DataFrame,
    config: ReconciliationConfig = CONFIG,
) -> pd.DataFrame:
    """Perform multi-tier deterministic and AI-assisted reconciliation."""
    ledger, bank = df_ledger.copy(), df_bank.copy()

    ledger["norm_amount"] = ledger["amount"].apply(normalize_amount)
    ledger["norm_date"] = ledger["order_date"].apply(normalize_date)
    ledger["norm_curr"] = ledger["currency"].apply(normalize_text)

    bank["norm_amount"] = bank["credited_amount"].apply(normalize_amount)
    bank["norm_date"] = bank["value_date"].apply(normalize_date)
    bank["norm_curr"] = bank["currency"].apply(normalize_text)
    bank["norm_narration"] = bank["narration_text"].apply(normalize_text)
    bank["extracted_ref"] = bank["norm_narration"].apply(extract_reference)

    matched_results: List[Dict[str, Any]] = []
    assigned_ledger, assigned_bank = set(), set()

    def add_result(
        l_id: str, b_id: str, status: str, rule: str, score: float, reason: str,
        source: str = "deterministic", model: str = "none", ai_reason: str = "", orig_score: Optional[float] = None
    ):
        matched_results.append({
            "ledger_id": l_id, "bank_id": b_id, "status": status, "matching_rule": rule,
            "score": round(score, 4), "reason": reason, "decision_source": source,
            "model_used": model, "ai_reason": ai_reason, "original_score": round(orig_score if orig_score is not None else score, 4),
        })
        if l_id:
            assigned_ledger.add(l_id)
        if b_id and status == "MATCHED":
            assigned_bank.add(b_id)

    # Tier 1: Exact Reference Match
    for l_idx, l_row in ledger.iterrows():
        l_id, l_amt, l_date, l_curr = l_row["order_id"], l_row["norm_amount"], l_row["norm_date"], l_row["norm_curr"]
        candidates = bank[
            (~bank["utr_reference"].isin(assigned_bank)) &
            ((bank["extracted_ref"] == l_id) | (bank["norm_narration"].str.contains(l_id, regex=False)))
        ]
        if not candidates.empty:
            b_row = candidates.iloc[0]
            b_id, b_amt, b_date, b_curr = b_row["utr_reference"], b_row["norm_amount"], b_row["norm_date"], b_row["norm_curr"]
            amt_diff, date_diff = abs(l_amt - b_amt), abs((l_date - b_date).days)
            if l_curr != b_curr:
                add_result(l_id, b_id, "UNRESOLVED", "CURRENCY_MISMATCH", 0.0, f"Currency mismatch ({l_curr} vs {b_curr})")
            elif amt_diff <= config.AMOUNT_TOLERANCE and date_diff <= config.DATE_WINDOW_DAYS:
                add_result(l_id, b_id, "MATCHED", "EXACT_REFERENCE", 1.0, "Exact reference, amount, and date match")

    # Tier 2: Exact Amount + Date Unique Match
    for l_idx, l_row in ledger[~ledger["order_id"].isin(assigned_ledger)].iterrows():
        l_id, l_amt, l_date, l_curr = l_row["order_id"], l_row["norm_amount"], l_row["norm_date"], l_row["norm_curr"]
        candidates = bank[
            (~bank["utr_reference"].isin(assigned_bank)) &
            (bank["norm_amount"] == l_amt) & (bank["norm_date"] == l_date) & (bank["norm_curr"] == l_curr)
        ]
        if len(candidates) == 1:
            b_row = candidates.iloc[0]
            b_ref = b_row["extracted_ref"]
            if b_ref and b_ref != l_id:
                continue
            add_result(l_id, b_row["utr_reference"], "MATCHED", "EXACT_AMOUNT_DATE", 0.9, "Exact amount and date match")

    # Tier 3: Phase 3 Candidate Generation & Bounded AI Assistance
    unassigned = ledger[~ledger["order_id"].isin(assigned_ledger)]
    for l_idx, l_row in unassigned.iterrows():
        l_id, l_curr, l_date, l_amt = l_row["order_id"], l_row["norm_curr"], l_row["norm_date"], l_row["norm_amount"]
        candidate_pool = []

        for b_idx, b_row in bank[~bank["utr_reference"].isin(assigned_bank)].iterrows():
            if l_curr != b_row["norm_curr"]:
                continue
            date_diff = abs((l_date - b_row["norm_date"]).days)
            if date_diff > config.BROAD_DATE_WINDOW_DAYS:
                continue
            amt_diff, fee_amt = abs(l_amt - b_row["norm_amount"]), l_amt - b_row["norm_amount"]
            max_amt_tol = max(config.AMOUNT_TOLERANCE, l_amt * config.BROAD_AMOUNT_TOLERANCE_PCT)
            if amt_diff > max_amt_tol and not (0 < fee_amt <= config.MAX_FEE_AMOUNT):
                continue

            score, breakdown = compute_evidence_score(l_row, b_row, config)
            candidate_pool.append((score, b_row["utr_reference"], b_row, breakdown))

        candidate_pool.sort(key=lambda x: x[0], reverse=True)
        top_candidates = candidate_pool[:config.TOP_N_CANDIDATES]

        if not top_candidates:
            add_result(l_id, "", "UNMATCHED", "NO_CANDIDATE", 0.0, "No candidate within broad window and tolerance")
        else:
            top_score, top_b_id, _, _ = top_candidates[0]
            is_ambiguous = len(top_candidates) > 1 and (top_score - top_candidates[1][0]) < config.AMBIGUITY_MARGIN

            if is_ambiguous or (config.REVIEW_THRESHOLD <= top_score < config.HIGH_CONFIDENCE_THRESHOLD):
                if config.ENABLE_AI_ASSIST and evaluate_ambiguous_record is not None:
                    ai_eval = evaluate_ambiguous_record(l_row, top_candidates, config)
                    ai_status = ai_eval.get("status", "REVIEW")
                    ai_reason = ai_eval.get("reason", "")
                    ai_model = ai_eval.get("model_used", "none")
                    sel_b_id = ai_eval.get("selected_bank_id") or top_b_id

                    if ai_status == "MATCHED":
                        add_result(l_id, sel_b_id, "MATCHED", "AI_CONFIRMED_MATCH", top_score, f"AI Confirmed: {ai_reason}", source="groq", model=ai_model, ai_reason=ai_reason, orig_score=top_score)
                    else:
                        add_result(l_id, top_b_id, "REVIEW", "AI_REVIEW_REQUIRED", top_score, f"AI Review: {ai_reason}", source="groq", model=ai_model, ai_reason=ai_reason, orig_score=top_score)
                else:
                    rule = "AMBIGUOUS_CANDIDATES" if is_ambiguous else "SCORE_REVIEW"
                    add_result(l_id, top_b_id, "REVIEW", rule, top_score, f"Deterministic review required ({top_score:.2f})")
            elif top_score >= config.HIGH_CONFIDENCE_THRESHOLD:
                add_result(l_id, top_b_id, "MATCHED", "SCORE_MATCHED", top_score, f"High confidence match ({top_score:.2f})")
            else:
                add_result(l_id, "", "UNMATCHED", "LOW_SCORE", top_score, f"Top score ({top_score:.2f}) below review threshold")

    # Tier 4: Unmatched Remaining Bank Entries
    for b_id in bank[~bank["utr_reference"].isin(assigned_bank)]["utr_reference"]:
        if not any(r["bank_id"] == b_id for r in matched_results):
            add_result("", b_id, "UNMATCHED", "NO_MATCH", 0.0, "No matching ledger record found")

    return pd.DataFrame(matched_results)


if __name__ == "__main__":
    import os
    ledger_path, bank_path = os.path.join("data", "ledger.csv"), os.path.join("data", "bank_statement.csv")
    if os.path.exists(ledger_path) and os.path.exists(bank_path):
        results = reconcile(pd.read_csv(ledger_path), pd.read_csv(bank_path))
        print("Phase 3 Reconciliation Summary:")
        print(results["status"].value_counts().to_string())
        print("\nDecision Sources:")
        print(results["decision_source"].value_counts().to_string())
