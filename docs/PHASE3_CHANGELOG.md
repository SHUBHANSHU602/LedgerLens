# Phase 3 Changelog: Realistic Benchmark, Custom XLSX Backend & API Observability

## 1. Dataset Design & Scenario Proportions (`src/data_generator.py` & `scripts/generate_dataset.py`)

- **Record Counts**: Default benchmark scales to **225 Ledger records** and **250 Bank statement records** (235 Answer Key records).
- **12 Scenario Classes**:
  1. `EASY_EXACT` (30%): Exact reference, amount, and date match with mild narration noise.
  2. `NOISY_REFERENCE` (17%): Narration noise with OCR character substitutions (`O->0`), space/slash insertions (`ORD / 1024`), and prefix/suffix variations.
  3. `FEE_DIFFERENCE` (8.5%): Legitimate bank fee deduction (e.g. 5000 INR vs 4950 INR with 50 INR fee).
  4. `DATE_SHIFT` (8.5%): Legitimate settlement date delays (1 to 3 days).
  5. `DUPLICATE_NEAR_DUPLICATE` (8.5%): Legitimate repeated transactions resembling each other.
  6. `AMBIGUOUS` (6.4%): Multiple bank rows with identical amount/date without distinct order IDs.
  7. `FALSE_POSITIVE_TRAP` (4.3%): Intentionally similar decoy bank records (same amount, date, and merchant keyword, but different reference/customer).
  8. `AMOUNT_NEAR_MATCH` (4.3%): Minor near matches (5000 vs 4999).
  9. `UNMATCHED_LEDGER` (4.3%): Ledger records with no bank counterpart.
  10. `UNMATCHED_BANK` (4.3%): Bank statement records with no ledger counterpart.
  11. `REVERSAL_ADJUSTMENT` (2.5%): Chargeback and reversal credit adjustments.
  12. `FEE_ONLY_SETTLEMENT` (1.7%): Explicit settlement fee adjustments.

- **Reference Leakage Metrics**:
  - `exact_reference_rate`: 68.00%
  - `partial_reference_rate`: 8.00%
  - `no_reference_rate`: 24.00%

---

## 2. Data Quality & Repository Audit (`src/data_validation.py` & `scripts/audit_repo.py`)

- Implemented 16-point repository and dataset audit (`audit_dataset_and_repo`):
  - **Answer Key Isolation**: Verified `reconciliation.py`, `ai_matcher.py`, `normalization.py`, and `schemas.py` never import or read `answer_key.csv`.
  - **Difficulty & Candidate Pool Distributions**: Tracks candidate pool size frequency, exact reference matches %, exact amount/date matches %, rows with no candidates, and rows requiring AI escalation.

---

## 3. Denominator-Explicit Benchmark Methodology (`src/evaluation.py` & `scripts/run_benchmark.py`)

- **Evaluation Denominators**: Explicitly separates Total Ledger Records (225), Total Bank Records (250), and Answer Key Ground Truth.
- **Metrics Calculated**:
  - **Pair Precision**: `0.9639` (TP / (TP + FP))
  - **Pair Recall**: `1.0000` (TP / (TP + FN))
  - **F1 Score**: `0.9816`
  - **False Positive Rate (FPR)**: `0.0800`
  - **False Negative Rate (FNR)**: `0.0000`
  - **Deterministic Match Rate**: `73.78%`
  - **AI Escalation Rate**: `23.11%`
  - **One-to-One Conflict Vetoes**: `0`
  - **Invalid AI Selections**: `0`

---

## 4. Custom XLSX Operational Backend & REST API (`app/api.py` & `src/config.py`)

- **Custom Directory**: Supports `LEDGERLENS_CUSTOM_DATA_DIR=data/custom/` (`data/custom/ledger.xlsx` and `data/custom/bank_statement.xlsx`).
- **REST Endpoints**:
  - `GET /api/v1/health`: Returns API health, version, and custom XLSX availability status.
  - `POST /api/v1/custom-data/upload`: Accepts `ledger.xlsx` or `bank_statement.xlsx` file upload, validates schema via `validate_ledger_schema`/`validate_bank_schema`, and saves to `data/custom/` without modifying benchmark datasets.
  - `POST /api/v1/reconcile`: Executes reconciliation engine. When `?debug=true` or `LEDGERLENS_DEBUG_MODE=true` is set, returns structured transaction observability traces:
    `ledger_id`, `status`, `candidate_count`, `candidate_ids`, `candidate_scores`, `score_breakdown`, `selected_candidate`, `matching_rule`, `decision_source`, `ai_invoked`, `ai_result`, `final_safety_validation`, `reason`.

---

## 5. Command Reference

Generate synthetic benchmark dataset:
```bash
python -m scripts.generate_dataset --seed 123 --ledger-count 200 --bank-count 200 --output-dir data
```

Run repository isolation and dataset quality audit:
```bash
python -m scripts.audit_repo
```

Run evaluation benchmark:
```bash
python -m scripts.run_benchmark
```

Run full Pytest unit test suite:
```bash
python -m pytest -q
```

---

## 6. Code Modification Summary (`git diff --stat`)

```text
 app/api.py                   | 152 ++++++++++++++++++++++++++++++++++
 docs/PHASE3_CHANGELOG.md     |  95 +++++++++++++++++++++
 scripts/audit_repo.py        |  26 ++++++
 scripts/generate_dataset.py  |  30 +++++++
 scripts/run_benchmark.py     |  28 +++++++
 src/config.py                |   3 +-
 src/data_generator.py        | 216 ++++++++++++++++++++++++++++++-----------------
 src/data_validation.py       | 122 +++++++++++++++++++++++++--
 src/evaluation.py            | 131 +++++++++++++++++++----------
 tests/test_api.py            |  95 +++++++++++++++++++++
 tests/test_reconciliation.py |  10 +--
 11 files changed, 810 insertions(+), 98 deletions(-)
```
