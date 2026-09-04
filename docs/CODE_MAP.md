# LedgerLens Code Map & Module Ownership Audit

A comprehensive reference mapping every major component in LedgerLens, detailing its purpose, inputs, outputs, dependencies, safety guarantees, and failure behaviors.

---

## Core Engine Modules (`src/`)

### 1. `src/reconciliation.py`
- **Role**: Core multi-tier reconciliation orchestrator.
- **Input**:
  - `df_ledger` (pandas DataFrame)
  - `df_bank` (pandas DataFrame)
  - `config` (`ReconciliationConfig`, optional)
- **Output**: Reconciliation DataFrame with match status, scores, rules, and candidate counts.
- **Important Functions**:
  - `compute_evidence_score(l_row, b_row, config)`: Multi-weighted score calculation (ref, amount, date, customer text).
  - `reconcile(df_ledger, df_bank, config)`: Tier 1 Exact Ref, Tier 2 Exact Amount/Date, Tier 3 Broad Candidate Scoring & AI Assist, Tier 4 Unmatched Bank. Includes global one-to-one conflict resolution (`ONE_TO_ONE_CONFLICT`).
- **Dependencies**: `src/normalization.py`, `src/data_validation.py`, `src/schemas.py`, `src/config.py`, `src/ai_matcher.py`.
- **Never Uses**: `answer_key.csv` (strictly isolated from ground truth).
- **Failure Behavior**: Missing columns raise `ValueError`. Scoring errors safely route records to `UNMATCHED` or `REVIEW`.

---

### 2. `src/ai_matcher.py`
- **Role**: Bounded Groq AI assistance module for ambiguous records reaching `REVIEW`.
- **Input**:
  - `l_row` (pandas Series)
  - `top_candidates` (List of candidate tuples)
  - `config` (`ReconciliationConfig`)
- **Output**: Dictionary with `same_transaction`, `selected_bank_id`, `status`, `reason`, and Pydantic validation flags.
- **Important Functions**:
  - `evaluate_ambiguous_record(l_row, top_candidates, config)`: Generates structured LLM prompt, validates JSON against Pydantic `AIEvaluationSchema`, enforces candidate bank ID pool vetoes, and caches results.
  - `clear_ai_cache()`: Invalidate in-memory composite cache.
- **Dependencies**: `groq`, `pydantic`, `dotenv`, `src/schemas.py`, `src/config.py`.
- **Never Uses**: `answer_key.csv`.
- **Failure Behavior**: Missing `GROQ_API_KEY`, API rate limits, network errors, or malformed JSON safely fallback to `status="REVIEW"` and `same_transaction=False` without crashing.

---

### 3. `src/normalization.py`
- **Role**: Normalization helper utilities for numeric amounts, dates, and narration text.
- **Input**: Raw strings, floats, datetimes.
- **Output**: Cleaned floats, datetime objects, uppercase strings, extracted reference strings.
- **Important Functions**:
  - `normalize_amount(val)`: Handles currency symbols, commas, and negative values.
  - `normalize_date(val)`: Converts multiple date formats to `datetime.date`.
  - `normalize_text(val)`: Uppercases and strips special noise characters.
  - `extract_reference(val)`: Extracts patterns like `ORD-XXXX` or UTR fragments.
- **Dependencies**: `re`, `rapidfuzz`.
- **Never Uses**: `answer_key.csv`.

---

### 4. `src/schemas.py`
- **Role**: Data structures and Pydantic validation schemas.
- **Input**: Engine dicts, LLM JSON output.
- **Output**: Validated Pydantic objects & typed dataclasses.
- **Important Classes**:
  - `AIEvaluationSchema`: Pydantic V2 schema with `coerce_boolean` field validators and `extra="ignore"` dict configuration.
  - `ReconciliationRecord`: Standardized output record tracking rank, candidate count, amount difference, and date difference.
  - `EvidenceBreakdown`: Structured multi-factor evidence scores.
- **Dependencies**: `pydantic`.
- **Never Uses**: `answer_key.csv`.

---

### 5. `src/data_validation.py`
- **Role**: Input schema validation and 16-point repository/dataset auditor.
- **Input**: DataFrames, file paths.
- **Output**: Schema validation tuple `(bool, list_of_errors)` and audit summary dictionary.
- **Important Functions**:
  - `validate_ledger_schema(df)`: Verifies required ledger columns (`order_id`, `amount`, `order_date`).
  - `validate_bank_schema(df)`: Verifies required bank columns (`utr_reference`, `credited_amount`, `value_date`).
  - `audit_repository_isolation()`: Guarantees matching engine never loads ground-truth answer keys.
  - `audit_dataset_and_repo(data_dir)`: Runs comprehensive 16-metric difficulty and quality audit.
- **Dependencies**: `pandas`, `src/config.py`, `src/reconciliation.py` (lazy imported inside audit).
- **Never Uses**: Ground truth during schema validation.

---

### 6. `src/evaluation.py`
- **Role**: Denominator-explicit benchmark evaluation engine.
- **Input**: `data_dir` containing `ledger.csv`, `bank_statement.csv`, and `answer_key.csv`.
- **Output**: Evaluation metrics dictionary (Precision, Recall, F1, FPR, FNR, escalation rates).
- **Important Functions**:
  - `evaluate_reconciliation(data_dir)`: Executes reconciliation, merges against ground truth answer key, calculates pair confusion matrix and performance metrics, and exports results workbook.
- **Dependencies**: `pandas`, `src/reconciliation.py`.
- **Note**: This is an evaluation module and IS allowed to read `answer_key.csv`.

---

### 7. `src/data_generator.py`
- **Role**: Controlled synthetic benchmark dataset generator.
- **Input**: `seed`, `output_dir`, `ledger_count`, `bank_count`.
- **Output**: `ledger.csv`, `bank_statement.csv`, `answer_key.csv`, `reconciliation_dataset.xlsx`.
- **Important Functions**:
  - `generate_synthetic_data(...)`: Generates 12 scenario categories (`EASY_EXACT`, `NOISY_REFERENCE`, `FEE_DIFFERENCE`, `DATE_SHIFT`, etc.) with controlled reference leakage.
- **Dependencies**: `pandas`, `openpyxl`, `src/config.py`.

---

### 8. `src/config.py`
- **Role**: Centralized system configuration constants and schema definitions.
- **Input**: None (dataclass defaults).
- **Output**: Immutable `ReconciliationConfig` instance `CONFIG`.
- **Dependencies**: `dataclasses`.

---

## Application & Web API Modules (`app/` & `api/`)

### 9. `app/api.py`
- **Role**: FastAPI REST API providing health checks, custom XLSX upload, and debug observability traces.
- **Endpoints**:
  - `GET /api/v1/health`: API status & custom data directory check.
  - `POST /api/v1/custom-data/upload`: Multipart file upload for custom ledger/bank XLSX files.
  - `POST /api/v1/reconcile`: Trigger reconciliation with optional `?debug=true` structured traces.
- **Dependencies**: `fastapi`, `pandas`, `openpyxl`, `src/reconciliation.py`, `src/data_validation.py`.

---

### 10. `app/app.py`
- **Role**: Thin Streamlit web interface for interactive file upload, parameter tuning, KPI dashboards, and CSV downloads.
- **Dependencies**: `streamlit`, `pandas`, `src/reconciliation.py`, `src/config.py`.

---

### 11. `api/server.py`
- **Role**: Uvicorn server entrypoint alias supporting `uvicorn api.server:app --reload`.
- **Dependencies**: `app/api.py`, `uvicorn`.

---

## CLI Script Utilities (`scripts/`)

- `scripts/generate_dataset.py`: CLI wrapper for `generate_synthetic_data`.
- `scripts/run_benchmark.py`: CLI runner for `evaluate_reconciliation` and repository audit.
- `scripts/audit_repo.py`: CLI runner for 16-metric repository and dataset quality audit.
