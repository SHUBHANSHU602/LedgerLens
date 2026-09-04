# LedgerLens: AI-Powered Financial Reconciliation Engine

LedgerLens is a deterministic, evidence-based, and bounded Groq AI financial reconciliation engine designed to compare internal transaction ledgers against external bank/settlement statements with high precision, auditability, and safety.

---

## Problem
Financial reconciliation is a critical accounting process where internal sales/orders ledgers must be matched against bank statement credits. Manual reconciliation is slow, expensive, and error-prone due to:
- Gateway fee deductions (e.g. 5,000 INR order credited as 4,950 INR with a 50 INR MDR fee).
- Settlement delays (1 to 3 days posting vs settlement date gaps).
- Narration noise, truncation, OCR errors, and missing order IDs.
- Ambiguous near-duplicate transactions on identical dates.

---

## Solution
LedgerLens solves financial reconciliation through a multi-tier pipeline:
1. **Deterministic Multi-Factor Core**: Evaluates candidate matches using weighted evidence (Reference 40%, Amount 30%, Date 20%, Customer Text 10%).
2. **Bounded Groq AI Assistance**: Invokes Groq LLM (`groq/compound`) **only** when deterministic rules identify genuine ambiguity.
3. **Pydantic & Safety Vetoes**: Enforces strict candidate pool boundaries, hallucinated bank ID vetoes, currency mismatch checks, and global one-to-one conflict resolution.
4. **Observable REST API & Web UI**: Offers structured JSON debug traces and a thin Streamlit web interface for accountants and developers.

---

## Architecture

```text
Ledger + Bank Datasets
        │
        ▼
Schema Validation & Normalization (Amount, Date, Text)
        │
        ▼
Candidate Generation & Multi-Weighted Evidence Scoring
        │
        ├── Tier 1: Exact Reference Match (Confidence 1.0)
        ├── Tier 2: Exact Amount & Date Unique Match (Confidence 0.90)
        └── Tier 3: Broad Candidate Pool & Ambiguity Gate
                │
                ├── Score >= 0.82 ─────────► High Confidence MATCHED
                ├── 0.45 <= Score < 0.82 ──► Bounded Groq AI Assist
                │                                │
                │                                ├── Pydantic Veto Passed ──► MATCHED
                │                                └── Veto Failed/Error ────► REVIEW
                └── Score < 0.45 ──────────► UNMATCHED
        │
        ▼
Global One-to-One Conflict Resolution (ONE_TO_ONE_CONFLICT Veto)
        │
        ▼
Final Reconciled Output & Audit Observability Traces
```

---

## How It Works
1. **Normalization**: Amounts are converted to clean numeric floats; dates are parsed to ISO format; narrations are uppercased and stripped of special noise characters.
2. **Tier 1 (Exact Ref)**: If the bank narration contains the exact order ID within the date window and matching currency, it is auto-matched immediately.
3. **Tier 2 (Exact Amount/Date)**: Unique amount/date matches without reference contradictions are auto-matched.
4. **Tier 3 (Candidate Scoring)**: Broad candidate pools are evaluated across multi-weighted evidence factors.
5. **Tier 4 (Unmatched Bank)**: Unclaimed bank statement records are logged as `UNMATCHED` for audit inspection.
6. **Global One-to-One Conflict Resolution**: If two ledger records claim the same bank record, the higher confidence score retains `MATCHED`, and the lower claim is downgraded to `REVIEW`.

---

## Role of AI
- **Bounded Invocation**: The LLM is NEVER used as the primary matcher. It is invoked **only** for ambiguous records reaching `REVIEW`.
- **Candidate Pool Restricting**: The engine passes ONLY the top 3 deterministically generated candidates to the LLM.
- **Deterministic Vetoes**: If the LLM returns a `selected_bank_id` outside the candidate pool, `ai_matcher` vetoes the decision and forces `same_transaction = False` and status `REVIEW`.
- **Safe Fallback**: API key absence, rate limits (HTTP 429), network errors, or malformed JSON output safely default to `REVIEW`.

---

## Dataset & Evaluation
LedgerLens includes a controlled synthetic benchmark generator (`scripts/generate_dataset.py`) producing 225+ ledger records and 250+ bank records across 12 scenario classes:
- `EASY_EXACT`, `NOISY_REFERENCE`, `FEE_DIFFERENCE`, `DATE_SHIFT`, `DUPLICATE_NEAR_DUPLICATE`, `AMBIGUOUS`, `FALSE_POSITIVE_TRAP`, `AMOUNT_NEAR_MATCH`, `UNMATCHED_LEDGER`, `UNMATCHED_BANK`, `REVERSAL_ADJUSTMENT`, `FEE_ONLY_SETTLEMENT`.

**Benchmark Performance**:
- **Pair Precision**: `0.9639`
- **Pair Recall**: `1.0000`
- **F1 Score**: `0.9816`
- **Deterministic Match Rate**: `73.78%`
- **AI Escalation Rate**: `23.11%`

---

## Installation & Setup

1. **Clone Repository & Install Dependencies**:
   ```bash
   git clone https://github.com/ZigzagDeck/LedgerLens.git
   cd LedgerLens
   pip install -r requirements.txt
   ```

2. **Configure Environment Secrets**:
   ```bash
   cp .env.example .env
   ```
   *(Optional: Edit `.env` to add your `GROQ_API_KEY` for live AI inference)*

---

## Developer Commands

- **Run Pytest Test Suite**:
  ```bash
  python -m pytest -q
  ```

- **Generate Benchmark Dataset**:
  ```bash
  python -m scripts.generate_dataset --seed 123 --ledger-count 200 --bank-count 200 --output-dir data
  ```

- **Run Repository & Data Audit**:
  ```bash
  python -m scripts.audit_repo
  ```

- **Run Benchmark Evaluator**:
  ```bash
  python -m scripts.run_benchmark
  ```

- **Launch FastAPI REST Server**:
  ```bash
  uvicorn api.server:app --reload
  ```

- **Launch Streamlit Web App**:
  ```bash
  streamlit run app/app.py
  ```

---

## Custom XLSX Usage

Save custom operational files to `data/custom/`:
- `data/custom/ledger.xlsx`
- `data/custom/bank_statement.xlsx`

Or upload via REST API:
```bash
curl -X POST "http://127.0.0.1:8000/api/v1/custom-data/upload" \
  -F "file_type=ledger" \
  -F "file=@path/to/ledger.xlsx"
```

---

## API Observability (Standard Mode vs Debug Mode)

### Standard Mode (`GET /api/v1/health` & `POST /api/v1/reconcile`):
Returns clean summary metrics suitable for production dashboards:
```json
{
  "status": "success",
  "data_source": "default_benchmark",
  "total_records": 258,
  "summary": {
    "matched": 166,
    "review": 52,
    "unmatched": 40
  }
}
```

### Debug Mode (`POST /api/v1/reconcile?debug=true`):
Exposes structured transaction traces per record for developer audit:
```json
{
  "ledger_id": "ORD-1111",
  "bank_id": "UTR500111",
  "status": "REVIEW",
  "matching_rule": "AI_REVIEW_REQUIRED",
  "score": 0.72,
  "reason": "AI Review: Rate limit reached. Safe fallback to REVIEW.",
  "decision_source": "groq",
  "ai_invoked": true,
  "candidate_count": 3,
  "amount_difference": 50.0,
  "date_difference": 0
}
```

---

## Limitations
1. **Multi-Legger Aggregates**: Batch payments where 10+ ledger orders are combined into 1 lump-sum bank credit require aggregate subset-sum solvers.
2. **Multi-Currency Conversion**: Live FX rate conversion is not included; currency mismatches are safely vetoed to `REVIEW`.
