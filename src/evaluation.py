"""Evaluation module for financial reconciliation engine against canonical ground truth (Phase 3)."""

import os
import pandas as pd
from typing import Dict, Any

try:
    from src.reconciliation import reconcile
except ModuleNotFoundError:
    from reconciliation import reconcile


def evaluate_reconciliation(data_dir: str = "data") -> Dict[str, Any]:
    """Evaluate reconciliation results against answer_key.csv."""
    ledger_path, bank_path = os.path.join(data_dir, "ledger.csv"), os.path.join(data_dir, "bank_statement.csv")
    answer_path = os.path.join(data_dir, "answer_key.csv")

    if not (os.path.exists(ledger_path) and os.path.exists(bank_path) and os.path.exists(answer_path)):
        raise FileNotFoundError("Dataset CSVs missing in data/ directory. Run data_generator.py first.")

    df_results = reconcile(pd.read_csv(ledger_path), pd.read_csv(bank_path))
    merged = pd.merge(pd.read_csv(answer_path), df_results[df_results["ledger_id"] != ""], left_on="order_id", right_on="ledger_id", how="outer")

    tp, fp, fn, tn = 0, 0, 0, 0
    ai_assisted_examples = []

    for idx, row in merged.iterrows():
        exp_status, act_status = str(row.get("expected_status", "UNMATCHED")).upper(), str(row.get("status", "UNMATCHED")).upper()
        exp_utr, act_utr = str(row.get("utr_reference", "")).strip(), str(row.get("bank_id", "")).strip()
        is_match_correct = (exp_utr == act_utr) if (exp_utr and act_utr) else True

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

        if str(row.get("decision_source", "")).lower() == "groq":
            ai_assisted_examples.append({
                "order_id": row.get("order_id", ""),
                "bank_id": row.get("bank_id", ""),
                "scenario": row.get("scenario", ""),
                "ai_reason": row.get("ai_reason", row.get("reason", "")),
                "model": row.get("model_used", ""),
                "final_decision": act_status,
                "orig_score": row.get("original_score", 0.0),
            })

    total_rows = len(df_results)
    ai_calls_count = len(df_results[df_results["decision_source"] == "groq"])
    deterministic_count = total_rows - ai_calls_count

    precision = round(tp / (tp + fp), 4) if (tp + fp) > 0 else 0.0
    recall = round(tp / (tp + fn), 4) if (tp + fn) > 0 else 0.0
    f1_score = round(2 * precision * recall / (precision + recall), 4) if (precision + recall) > 0 else 0.0

    matches_count = len(df_results[df_results["status"] == "MATCHED"])
    reviews_count = len(df_results[df_results["status"] == "REVIEW"])
    unmatched_count = len(df_results[df_results["status"] == "UNMATCHED"])

    metrics = {
        "total_rows": total_rows,
        "handled_without_ai": deterministic_count,
        "sent_to_ai": ai_calls_count,
        "matches": matches_count,
        "reviews": reviews_count,
        "unmatched": unmatched_count,
        "true_positives": tp,
        "false_positives": fp,
        "false_negatives": fn,
        "true_negatives": tn,
        "precision": precision,
        "recall": recall,
        "f1_score": f1_score,
        "ai_examples": ai_assisted_examples[:3],
    }

    print("=" * 65)
    print("FINANCIAL RECONCILIATION EVALUATION REPORT (PHASE 3 WITH GROQ AI)")
    print("=" * 65)
    print(f"Total Records Evaluated        : {total_rows}")
    print(f"Handled Deterministically (No AI): {deterministic_count}")
    print(f"Sent to Groq AI (REVIEW pool)  : {ai_calls_count} (AI calls << Total Records)")
    print("-" * 65)
    print(f"Matches (Auto-matched)         : {matches_count} ({matches_count/total_rows*100:.1f}%)")
    print(f"Reviews (Requires Manual Review): {reviews_count} ({reviews_count/total_rows*100:.1f}%)")
    print(f"Unmatched                      : {unmatched_count} ({unmatched_count/total_rows*100:.1f}%)")
    print("-" * 65)
    print(f"True Positives (TP) : {tp} | False Positives (FP) : {fp}")
    print(f"False Negatives (FN): {fn} | True Negatives (TN)  : {tn}")
    print(f"Precision : {precision:.4f} | Recall : {recall:.4f} | F1 Score : {f1_score:.4f}")
    print("=" * 65)

    if ai_assisted_examples:
        print("\nTop 3 AI-Assisted Examples:")
        for i, ex in enumerate(ai_assisted_examples[:3], 1):
            print(f"\n  [{i}] Ledger Order: {ex['order_id']} | Candidate Bank ID: {ex['bank_id']}")
            print(f"      Scenario: {ex['scenario']} | Deterministic Score: {ex['orig_score']}")
            print(f"      Model: {ex['model']} | AI Evidence: {ex['ai_reason']}")
            print(f"      Final Decision: {ex['final_decision']}")

    # Export results to Excel workbook
    results_excel_path = os.path.join(data_dir, "reconciliation_results.xlsx")
    with pd.ExcelWriter(results_excel_path, engine="openpyxl") as writer:
        df_results.to_excel(writer, sheet_name="Reconciliation Results", index=False)
        pd.DataFrame([metrics]).to_excel(writer, sheet_name="Evaluation Metrics", index=False)
    print(f"\nSaved Reconciliation Results Workbook: {results_excel_path}")

    return metrics


if __name__ == "__main__":
    evaluate_reconciliation()
