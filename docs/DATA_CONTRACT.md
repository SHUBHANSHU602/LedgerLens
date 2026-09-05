# LedgerLens Data Contract

This document defines the canonical input/output schemas, column requirements, data types, and validation rules for all data flowing through LedgerLens. This is the authoritative reference for anyone building integrations, writing tests, or uploading custom data.

---

## 1. Ledger Input Schema

The ledger represents your internal order management system records — one row per customer order that received payment.

### Required Columns

| Column | Type | Constraints | Example |
| :--- | :--- | :--- | :--- |
| `order_id` | `string` | Non-null, non-empty, unique per batch | `ORD-1024` |
| `amount` | `numeric` | Parseable as positive float | `5000.00` |
| `order_date` | `date` | Must parse in one of 4 supported formats | `2026-08-15` |

### Optional Columns (Improve Match Quality)

| Column | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `customer_name` | `string` | `""` | Used for fuzzy text evidence score (W_TEXT = 10%) |
| `currency` | `string` | `INR` | ISO 4217 code. Mismatch with bank record triggers CURRENCY_MISMATCH veto |
| `payment_method` | `string` | `""` | Informational: `UPI`, `NEFT`, `RTGS`, `CARD`, `NETBANKING` |

### Supported Date Formats

LedgerLens tries each format in order until one parses:

```
%Y-%m-%d  →  2026-08-15   (ISO 8601 — preferred)
%d/%m/%Y  →  15/08/2026   (Indian/European style)
%m/%d/%Y  →  08/15/2026   (US style)
%d-%m-%Y  →  15-08-2026   (dash-separated)
```

### Validation Rules (`validate_ledger_schema()`)

- `order_id`: Zero null values, zero empty strings, zero duplicates within the batch
- `amount`: All values must be parseable via `pd.to_numeric(errors="raise")`
- `order_date`: All values must be parseable via `pd.to_datetime(errors="raise")`
- Missing required columns → validation fails with a list of missing column names

---

## 2. Bank Statement Input Schema

The bank statement represents credits your bank account received — typically from a payment gateway settlement.

### Required Columns

| Column | Type | Constraints | Example |
| :--- | :--- | :--- | :--- |
| `utr_reference` | `string` | Non-null, non-empty, unique per batch | `UTR500143` |
| `credited_amount` | `numeric` | Parseable as positive float | `4950.00` |
| `value_date` | `date` | Must parse in one of 4 supported formats | `2026-08-16` |

### Optional Columns (Improve Match Quality)

| Column | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `narration_text` | `string` | `""` | Bank transaction description. Used for `ORD-\d+` reference extraction and fuzzy text scoring |
| `currency` | `string` | `INR` | ISO 4217 code |
| `deduction_fee` | `float` | `0.0` | Gateway MDR fee deducted before settlement credit (informational) |

### Validation Rules (`validate_bank_schema()`)

- `utr_reference`: Zero null values, zero empty strings, zero duplicates within the batch
- `credited_amount`: All values must be parseable as numeric
- `value_date`: All values must be parseable as a date
- Missing required columns → validation fails with list of missing column names

---

## 3. Reconciliation Output Schema

Output of `reconcile(df_ledger, df_bank)` — one row per ledger record, plus one row per unmatched bank record.

| Column | Type | Description |
| :--- | :--- | :--- |
| `ledger_id` | `string` | Order ID from ledger. Empty string for unmatched bank-only records |
| `bank_id` | `string` | UTR reference from bank. Empty string for unmatched ledger-only records |
| `status` | `string` | `MATCHED`, `REVIEW`, or `UNMATCHED` |
| `matching_rule` | `string` | Rule that determined the outcome (see Section 4) |
| `score` | `float` | Composite evidence score 0.0–1.0 |
| `reason` | `string` | Human-readable explanation of the decision |
| `decision_source` | `string` | `deterministic` or `groq` |
| `model_used` | `string` | Groq model name if AI-assisted; `none` for deterministic |
| `ai_reason` | `string` | AI reasoning text when `decision_source == "groq"`; empty otherwise |
| `original_score` | `float` | Pre-AI weighted evidence score (same as `score` for deterministic) |
| `amount_difference` | `float` | Absolute INR difference between ledger and matched bank amounts |
| `date_difference` | `int` | Absolute day difference between ledger and matched bank dates |
| `candidate_rank` | `int` | Rank of matched bank candidate within candidate pool (1 = best) |
| `candidate_count` | `int` | Total candidates generated for this ledger record |

---

## 4. Status Rules Reference

| Rule | Status | Tier | Description |
| :--- | :--- | :--- | :--- |
| `EXACT_REFERENCE` | `MATCHED` | 1 | Bank narration contains exact `ORD-XXXX` pattern, amount within ₹0.01, date within ±3 days |
| `EXACT_AMOUNT_DATE` | `MATCHED` | 2 | Exactly one bank record with identical amount + date, no conflicting order reference |
| `SCORE_MATCHED` | `MATCHED` | 3 | Weighted composite score ≥ 0.82 |
| `AI_CONFIRMED_MATCH` | `MATCHED` | AI | Groq AI confirmed match from ambiguous candidate pool |
| `AI_REVIEW_REQUIRED` | `REVIEW` | AI | AI invoked but could not confirm match with confidence |
| `AMBIGUOUS_CANDIDATES` | `REVIEW` | 3 | Top two candidates within 0.08 score margin of each other |
| `SCORE_REVIEW` | `REVIEW` | 3 | Score in zone: 0.45 ≤ score < 0.82 |
| `ONE_TO_ONE_CONFLICT` | `REVIEW` | Post | Bank ID already claimed by a higher-confidence ledger record |
| `CURRENCY_MISMATCH` | `REVIEW` | Veto | Currency strings differ; match blocked unconditionally |
| `LOW_SCORE` | `UNMATCHED` | 3 | Best candidate score below 0.45 |
| `NO_CANDIDATE` | `UNMATCHED` | 3 | No bank record found within ±10 days and ±5% amount window |
| `NO_MATCH` | `UNMATCHED` | Post | Bank record not claimed by any ledger order |

---

## 5. Evidence Scoring Formula

For Tier 3 candidates, signals are scored 0.0–1.0 and combined with weights:

```
composite_score = (0.40 × ref_score) + (0.30 × amount_score) + (0.20 × date_score) + (0.10 × text_score)
```

| Signal | Weight | Scoring Logic |
| :--- | :---: | :--- |
| Reference (`ref_score`) | 0.40 | 1.0 if exact `ORD-XXXX`; 0.6 if fuzzy partial; 0.0 if none |
| Amount (`amount_score`) | 0.30 | 1.0 if exact; 0.4 if fee-range diff ≤ ₹100; decay above |
| Date (`date_score`) | 0.20 | 1.0 if same day; graduated decay per day up to ±10 days |
| Text (`text_score`) | 0.10 | `rapidfuzz.token_set_ratio` similarity (customer name vs narration) |

---

## 6. Canonical Razorpay Transaction Schema

Used by `src/connectors/razorpay.py` for demo and future live integration.

| Column | Type | Description | Live API Note |
| :--- | :--- | :--- | :--- |
| `transaction_id` | `string` | Internal ID | Live: Razorpay `setlmt_XXX` |
| `external_reference` | `string` | Payment ID | Live: `pay_XXX` |
| `amount` | `float` | Amount in INR | **Live: Razorpay sends paise → divide by 100** |
| `currency` | `string` | ISO 4217 code | `INR` |
| `transaction_date` | `string` | Payment capture date | Live: `created_at` Unix timestamp |
| `settlement_date` | `string` | Bank credit date | Live: `settled_at` Unix timestamp |
| `customer` | `string` | Customer or merchant name | |
| `description` | `string` | Transaction description | |
| `source` | `string` | Data origin label | `"razorpay"` |
| `status` | `string` | Transaction status | `CAPTURED`, `SETTLED`, `CREDITED` |

---

## 7. Answer Key Schema (Benchmark Ground Truth Only)

Never read by matching modules. Exclusively read by `src/evaluation.py`.

| Column | Type | Description |
| :--- | :--- | :--- |
| `order_id` | `string` | Ledger order ID |
| `utr_reference` | `string` | Correct matching bank UTR. Empty string if no match |
| `scenario` | `string` | Dataset scenario class (e.g., `EASY_EXACT`, `FEE_DIFFERENCE`) |
| `expected_status` | `string` | `MATCHED`, `UNMATCHED`, or `UNRESOLVED` |
| `notes` | `string` | Human-readable scenario description |

---

## 8. Custom Data Upload Contract

When uploading via `POST /api/v1/custom-data/upload`:

- **Accepted formats**: `.xlsx` (preferred), `.csv`
- **Ledger**: upload with `file_type=ledger` → saved as `data/custom/ledger.xlsx`
- **Bank**: upload with `file_type=bank` → saved as `data/custom/bank_statement.xlsx`
- **Validation**: Schema validation runs immediately on upload. HTTP 400 if required columns are missing.
- **Isolation**: Custom data never overwrites benchmark data in `data/ledger.csv` or `data/bank_statement.csv`.

---

## 9. File Format Compatibility Matrix

| Format | Ledger | Bank Statement | Notes |
| :--- | :---: | :---: | :--- |
| CSV (comma-separated) | ✅ | ✅ | Via `pd.read_csv()` |
| XLSX (Excel 2007+) | ✅ | ✅ | Via `openpyxl` engine |
| XLS (old Excel) | ❌ | ❌ | Not supported — convert to XLSX first |
| JSON | ❌ | ❌ | Not directly supported — convert to CSV first |
| Razorpay Live API | ⚠️ | ⚠️ | Connector exists; `load_live_settlements()` stub only |
