"""Evaluation module for financial reconciliation engine against canonical ground truth (Phase 3)."""

import os
from typing import Dict, Any, List
import pandas as pd

try:
    from src.reconciliation import reconcile
except ModuleNotFoundError:
    from reconciliation import reconcile


def evaluate_reconciliation(data_dir: str = "data") -> Dict[str, Any]:
    """Evaluate reconciliation results against answer_key.csv with denominator-explicit metrics."""
    ledger_path = os.path.join(data_dir, "ledger.csv")
    bank_path = os.path.join(data_dir, "bank_statement.csv")
    answer_path = os.path.join(data_dir, "answer_key.csv")

    if not (os.path.exists(ledger_path) and os.path.exists(bank_path) and os.path.exists(answer_path)):
        raise FileNotFoundError(f"Dataset CSVs missing in '{data_dir}/'. Run scripts/generate_dataset.py first.")

    df_ledger = pd.read_csv(ledger_path)
    df_bank = pd.read_csv(bank_path)
    df_answer = pd.read_csv(answer_path)

    df_results = reconcile(df_ledger, df_bank)

    # Merge results on ledger_id / order_id
    merged = pd.merge(
        df_answer,
        df_results[df_results["ledger_id"] != ""],
        left_on="order_id",
        right_on="ledger_id",
        how="outer",
    )

    tp, fp, fn, tn = 0, 0, 0, 0
    invalid_ai_selection_count = 0
    ai_assisted_examples: List[Dict[str, Any]] = []

    for idx, row in merged.iterrows():
        exp_status = str(row.get("expected_status", "UNMATCHED")).strip().upper()
        act_status = str(row.get("status", "UNMATCHED")).strip().upper()

        exp_utr = str(row.get("utr_reference", "")).strip() if pd.notna(row.get("utr_reference")) else ""
        act_utr = str(row.get("bank_id", "")).strip() if pd.notna(row.get("bank_id")) else ""

        is_match_correct = (exp_utr == act_utr) if (exp_utr and act_utr) else (not exp_utr and not act_utr)

        if act_status == "MATCHED":
            if exp_status == "MATCHED" and is_match_correct:
                tp += 1
            else:
                fp += 1
        else:
            if exp_status == "MATCHED":
                fn += 1
            else:
                tn += 1

        # Check for invalid AI selection (AI picked a bank ID that was not correct)
        if str(row.get("decision_source", "")).lower() == "groq":
            if act_status == "MATCHED" and not is_match_correct:
                invalid_ai_selection_count += 1
            ai_assisted_examples.append({
                "order_id": row.get("order_id", ""),
                "bank_id": row.get("bank_id", ""),
                "scenario": row.get("scenario", ""),
                "ai_reason": row.get("ai_reason", row.get("reason", "")),
                "model": row.get("model_used", ""),
                "final_decision": act_status,
                "orig_score": row.get("original_score", 0.0),
            })

    total_ledger = len(df_ledger)
    total_bank = len(df_bank)
    total_results = len(df_results)

    ai_calls_count = len(df_results[df_results["decision_source"] == "groq"])
    ai_matched_count = len(df_results[(df_results["decision_source"] == "groq") & (df_results["status"] == "MATCHED")])
    deterministic_count = total_results - ai_calls_count
    deterministic_matched = len(df_results[(df_results["decision_source"] == "deterministic") & (df_results["status"] == "MATCHED")])

    matches_count = len(df_results[df_results["status"] == "MATCHED"])
    reviews_count = len(df_results[df_results["status"] == "REVIEW"])
    unmatched_ledger_count = len(df_results[(df_results["ledger_id"] != "") & (df_results["status"] == "UNMATCHED")])
    unmatched_bank_count = len(df_results[(df_results["ledger_id"] == "") & (df_results["status"] == "UNMATCHED")])

    duplicate_assignments = len(df_results[df_results["matching_rule"] == "ONE_TO_ONE_CONFLICT"])

    precision = round(tp / (tp + fp), 4) if (tp + fp) > 0 else 0.0
    recall = round(tp / (tp + fn), 4) if (tp + fn) > 0 else 0.0
    f1_score = round(2 * precision * recall / (precision + recall), 4) if (precision + recall) > 0 else 0.0

    fpr = round(fp / (fp + tn), 4) if (fp + tn) > 0 else 0.0
    fnr = round(fn / (fn + tp), 4) if (fn + tp) > 0 else 0.0

    review_rate = round(reviews_count / total_ledger, 4) if total_ledger > 0 else 0.0
    deterministic_match_rate = round(deterministic_matched / total_ledger, 4) if total_ledger > 0 else 0.0
    ai_escalation_rate = round(ai_calls_count / total_ledger, 4) if total_ledger > 0 else 0.0
    ai_match_rate = round(ai_matched_count / ai_calls_count, 4) if ai_calls_count > 0 else 0.0

    metrics = {
        "denominators": {
            "total_ledger_records": total_ledger,
            "total_bank_records": total_bank,
            "total_results_rows": total_results,
        },
        "pair_precision": precision,
        "pair_recall": recall,
        "f1_score": f1_score,
        "false_positive_rate": fpr,
        "false_negative_rate": fnr,
        "confusion_matrix": {"TP": tp, "FP": fp, "FN": fn, "TN": tn},
        "status_counts": {
            "MATCHED": matches_count,
            "REVIEW": reviews_count,
            "UNMATCHED_LEDGER": unmatched_ledger_count,
            "UNMATCHED_BANK": unmatched_bank_count,
        },
        "rates": {
            "review_rate": review_rate,
            "deterministic_match_rate": deterministic_match_rate,
            "ai_escalation_rate": ai_escalation_rate,
            "ai_match_rate": ai_match_rate,
        },
        "safety_checks": {
            "duplicate_assignment_conflicts": duplicate_assignments,
            "invalid_ai_selections": invalid_ai_selection_count,
        },
        "ai_examples": ai_assisted_examples[:3],
    }

    print("=" * 65)
    print("FINANCIAL RECONCILIATION BENCHMARK EVALUATION REPORT")
    print("=" * 65)
    print(f"Total Ledger Records : {total_ledger}")
    print(f"Total Bank Records   : {total_bank}")
    print("-" * 65)
    print(f"Pair Precision       : {precision:.4f}  (TP / (TP + FP))")
    print(f"Pair Recall          : {recall:.4f}  (TP / (TP + FN))")
    print(f"F1 Score             : {f1_score:.4f}")
    print(f"False Positive Rate  : {fpr:.4f}")
    print(f"False Negative Rate  : {fnr:.4f}")
    print("-" * 65)
    print(f"Matches (MATCHED)    : {matches_count} ({matches_count/total_ledger*100:.1f}%)")
    print(f"Reviews (REVIEW)     : {reviews_count} ({review_rate*100:.1f}%)")
    print(f"Unmatched Ledger     : {unmatched_ledger_count}")
    print(f"Unmatched Bank       : {unmatched_bank_count}")
    print("-" * 65)
    print(f"Deterministic Match Rate : {deterministic_match_rate:.2%}")
    print(f"AI Escalation Rate       : {ai_escalation_rate:.2%}")
    print(f"AI Match Success Rate    : {ai_match_rate:.2%}")
    print(f"One-to-One Conflicts     : {duplicate_assignments}")
    print(f"Invalid AI Selections    : {invalid_ai_selection_count}")
    print("=" * 65)

    # Save to Excel
    results_excel_path = os.path.join(data_dir, "reconciliation_results.xlsx")
    try:
        with pd.ExcelWriter(results_excel_path, engine="openpyxl") as writer:
            df_results.to_excel(writer, sheet_name="Reconciliation Results", index=False)
            pd.DataFrame([metrics["rates"]]).to_excel(writer, sheet_name="Evaluation Metrics", index=False)
    except Exception as e:
        print(f"Note: Could not update Excel results ({e}). Results calculated successfully.")

    return metrics


if __name__ == "__main__":
    evaluate_reconciliation()
