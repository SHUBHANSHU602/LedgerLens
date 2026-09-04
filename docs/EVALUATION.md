# LedgerLens Evaluation & Benchmark Methodology

This document outlines the evaluation methodology, metric formulas, ground truth pairing rules, and benchmark reproducibility instructions for LedgerLens.

---

## 1. Ground Truth Pairing & Isolation

### Architecture
- **Runtime Execution**: Reads `ledger.csv` and `bank_statement.csv`. Produces `df_results`. Ground truth `answer_key.csv` is NEVER loaded by matching engine modules.
- **Evaluation Execution**: Reads `answer_key.csv` and merges with `df_results` on `order_id` / `ledger_id`.

---

## 2. Benchmark Metric Definitions

- **Pair Precision**: Rate of correct positive matches among all auto-matched predictions:
  $$\text{Precision} = \frac{\text{TP}}{\text{TP} + \text{FP}}$$
- **Pair Recall**: Rate of correctly matched ground truth pairs identified by the system:
  $$\text{Recall} = \frac{\text{TP}}{\text{TP} + \text{FN}}$$
- **F1 Score**: Harmonic mean of Precision and Recall:
  $$\text{F1} = \frac{2 \times \text{Precision} \times \text{Recall}}{\text{Precision} + \text{Recall}}$$
- **False Positive Rate (FPR)**: $\frac{\text{FP}}{\text{FP} + \text{TN}}$
- **False Negative Rate (FNR)**: $\frac{\text{FN}}{\text{FN} + \text{TP}}$
- **Deterministic Match Rate**: Percentage of ledger transactions matched automatically without AI.
- **AI Escalation Rate**: Percentage of ledger transactions routed to Groq AI assistance.

---

## 3. Running Benchmark Evaluation

```bash
python -m scripts.run_benchmark
```
