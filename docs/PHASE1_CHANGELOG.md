# Phase 1 Changelog: Foundation — Normalization, Tier 1 Matching & Evaluation Scaffolding

## Overview

Phase 1 established the foundational engineering layer of LedgerLens. The goal was to create a working end-to-end reconciliation pipeline for the simplest, most tractable case: exact order reference matching. All subsequent phases build on top of this foundation without modifying its public interfaces.

---

## 1. Core Modules Created

### `src/normalization.py` [NEW]

Standalone normalization utilities used by the matching engine and all downstream modules.

**Functions added**:
- `normalize_amount(val)` → `float`: Strips currency symbols/commas, returns 2-decimal float. Safe on `None` / `pd.NA`.
- `normalize_date(val)` → `datetime.date`: Tries 4 date format strings in order; raises `ValueError` on failure.
- `normalize_text(val)` → `str`: Strips, uppercases, collapses whitespace. Safe on `None` / `pd.NA`.
- `extract_reference(text)` → `Optional[str]`: Applies `r"ORD-\d+"` regex to normalized text. Returns first match or `None`.

**Design decision**: `rapidfuzz` imported with a `DummyFuzz` fallback class if the library is not installed, ensuring the module works in minimal environments.

---

### `src/schemas.py` [NEW]

Typed data structures for all system outputs.

**Classes added**:
- `EvidenceBreakdown`: Dataclass holding per-signal scores (`ref`, `amount`, `date`, `text`).
- `ReconciliationRecord`: Dataclass for reconciliation output rows with all metadata fields.
- `AIEvaluationSchema`: Pydantic v2 `BaseModel` for validating Groq AI responses.
- `CandidateBank`: Dataclass representing a scored bank candidate.
- `EvaluationMetrics`: Dataclass for benchmark evaluation results.

---

### `src/config.py` [NEW]

Frozen `ReconciliationConfig` dataclass holding all tuneable parameters.

**Key parameters established**:
- `AMOUNT_TOLERANCE = 0.01` — Max INR difference for exact amount match
- `DATE_WINDOW_DAYS = 3` — ±3 day window for close date matching
- `W_REF, W_AMOUNT, W_DATE, W_TEXT = 0.40, 0.30, 0.20, 0.10` — Evidence weights
- `HIGH_CONFIDENCE_THRESHOLD = 0.82` — Auto-match score cutoff
- `REVIEW_THRESHOLD = 0.45` — Minimum score to escalate to review
- Column name constants: `LEDGER_COLUMNS`, `BANK_COLUMNS`, `ANSWER_KEY_COLUMNS`

---

### `src/data_validation.py` [NEW]

Schema validation functions for ledger and bank statement DataFrames.

**Functions added**:
- `validate_ledger_schema(df, config)` → `(bool, List[str])`: Validates required columns, non-null IDs, no duplicates, numeric amounts, parseable dates.
- `validate_bank_schema(df, config)` → `(bool, List[str])`: Same pattern for bank statement.
- `validate_custom_data_paths(custom_dir)` → `(bool, Dict)`: Checks existence of custom XLSX files in configured directory.

---

### `src/reconciliation.py` [NEW — Tier 1 Only]

Initial reconciliation engine implementing Tier 1 exact reference matching.

**Phase 1 behavior**:
- For each ledger record, scan all bank records for narration containing `ORD-XXXX` matching the order ID.
- If found: verify currency, amount within ₹0.01, date within ±3 days.
- If all pass: emit `ReconciliationRecord` with `status=MATCHED`, `rule=EXACT_REFERENCE`, `score=1.0`.
- Otherwise: emit `status=UNMATCHED`, `rule=NO_CANDIDATE`.
- Output: `pd.DataFrame` of `ReconciliationRecord` rows.

**Coverage**: ~68% of real-world scenarios where bank narrations contain the exact order ID.

---

### `src/evaluation.py` [NEW — Scaffold Only]

Evaluation module comparing reconciliation output against `answer_key.csv` ground truth.

**Phase 1 scope**: Basic TP/FP/FN/TN computation with `pair_precision`, `pair_recall`, `f1_score`. Full denominator-explicit metrics added in Phase 3.

---

## 2. Test Suite Created

### `tests/test_reconciliation.py` [NEW — 5 tests]

| Test | What It Verifies |
| :--- | :--- |
| `test_normalization_utilities` | All 4 normalize functions with edge cases |
| `test_exact_match` | Ledger + bank with exact ORD reference → `MATCHED`, score `1.0` |
| `test_no_match` | Ledger with no bank counterpart → `UNMATCHED` |
| `test_validate_ledger_schema` | Valid and invalid ledger schemas |
| `test_validate_bank_schema` | Valid and invalid bank schemas |

**Result**: 5/5 passed.

---

## 3. Project Scaffolding

- `requirements.txt` created with initial dependencies: `pandas`, `rapidfuzz`, `groq`, `python-dotenv`, `openpyxl`, `pytest`
- `.env.example` created with `GROQ_API_KEY=your_groq_api_key_here` placeholder
- `.gitignore` created: `.env`, `__pycache__`, `.pytest_cache`, `data/`, `*.pyc`
- `README.md` scaffold created (expanded in Phase 4)

---

## 4. Code Size Summary

```text
src/normalization.py    |  62 lines
src/schemas.py          |  82 lines
src/config.py           |  77 lines
src/data_validation.py  | 112 lines (Phase 1 scope)
src/reconciliation.py   | 148 lines (Phase 1 scope)
src/evaluation.py       |  95 lines (Phase 1 scaffold)
tests/test_reconciliation.py | 45 lines (Phase 1 tests)
```

---

## 5. Design Decisions Made in Phase 1

| Decision | Rationale |
| :--- | :--- |
| Frozen dataclass for config | Prevents accidental mutation of thresholds during a run |
| `(bool, List[str])` for validation | Accumulate all errors before returning — better UX than failing on first |
| `DummyFuzz` fallback | Ensures normalization works even without `rapidfuzz` installed |
| `Optional[str]` for `extract_reference` | Explicit `None` return is safer than empty string |
| Score `1.0` for Tier 1 | Exact reference matches are definitively correct — no scoring ambiguity |
