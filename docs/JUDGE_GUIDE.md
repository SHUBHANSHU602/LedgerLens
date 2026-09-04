# LedgerLens: Hackathon & Judge Explanation Guide

A plain-language explanation of LedgerLens architecture, decision rules, AI safety mechanisms, and evaluation methodology.

---

### 1. What problem does LedgerLens solve?
Businesses process hundreds of payments daily across different bank accounts, payment gateways, and internal order management systems. Manual reconciliation—matching an internal order ledger against bank statements—is slow, expensive, and error-prone due to messy transaction narrations, fee deductions, and date delays. LedgerLens automates this matching process with high accuracy, determinism, and safety.

---

### 2. Why is reconciliation difficult?
Reconciliation is difficult because bank statements rarely contain clean, exact order IDs. Common real-world issues include:
- Bank fees deducted before credit (e.g. 5,000 INR order credited as 4,950 INR).
- Settlement delays (ledger date is Monday; bank credits on Wednesday).
- Narration noise, truncation, and OCR errors (e.g. `ORD-1024` converted to `CMS/N1024/SETTL`).
- Duplicate payments of identical amounts on the same day.

---

### 3. What happens to one transaction?
1. **Schema & Normalization**: The ledger row and candidate bank rows are normalized (amounts converted to floats, dates to standard ISO strings, text uppercased and stripped of noise).
2. **Tier 1 (Exact Reference Match)**: If the bank narration contains the exact order ID, date is within window, and currency matches, it is immediately matched (`MATCHED`).
3. **Tier 2 (Exact Amount & Date Unique Match)**: If an exact amount and date match a single unique bank row without conflicting order IDs, it is matched (`MATCHED`).
4. **Tier 3 (Candidate Scoring & Ambiguity Gate)**: The top 5 bank candidates are scored across weighted factors (Reference 40%, Amount 30%, Date 20%, Text 10%). High-confidence scores (>= 0.82) auto-match. Ambiguous scores (0.45 <= score < 0.82) trigger bounded AI review. Low evidence (< 0.45) defaults to `UNMATCHED`.
5. **Global One-to-One Conflict Resolution**: If two ledger records claim the same bank record, the higher-scoring match retains it, while the lower-scoring record is downgraded to `REVIEW` with rule `ONE_TO_ONE_CONFLICT`.

---

### 4. Why are deterministic rules used first?
Deterministic rules are fast, 100% predictable, reproducible, free to execute, and mathematically transparent. Over 70% of real-world financial transactions can be resolved deterministically without sending financial data to external APIs.

---

### 5. When is AI used?
AI is used **only** when deterministic rules identify genuine ambiguity (e.g. candidate score between 0.45 and 0.82, or multiple top candidates with score differences within the ambiguity margin of 0.08). The LLM is used as an evidence assistant to inspect complex narrations or fee deductions.

---

### 6. Why not send every transaction to AI?
- **Cost**: Calling LLM APIs for millions of simple transactions is extremely expensive.
- **Speed & Scalability**: Deterministic rules process thousands of transactions per second locally.
- **Hallucination Risk**: LLMs can hallucinate non-existent matches if relied upon for every decision.
- **Privacy & Security**: Minimizes data sent across network boundaries.

---

### 7. How is a false AI match prevented?
1. **Candidate Pool Restricting**: The engine passes ONLY the top 3 deterministically verified candidates to the LLM.
2. **Bank ID Hallucination Veto**: If the LLM returns a `selected_bank_id` that is not present in the candidate pool, `ai_matcher` vetoes the decision, forces `same_transaction = False`, and sets status to `REVIEW`.
3. **Hard Contradiction Vetoes**: Date delays exceeding maximum windows or currency mismatches immediately veto any match.
4. **Fallback Safety**: Network errors, missing API keys, or malformed JSON output safely default to `REVIEW`.

---

### 8. How are unmatched records handled?
- **Unmatched Ledger**: If no bank candidate exists within tolerance, the record is flagged as `UNMATCHED` with rule `NO_CANDIDATE`.
- **Unmatched Bank**: Remaining unclaimed bank statement records are reported as `UNMATCHED` with rule `NO_MATCH` so accountants can inspect unlinked bank deposits.

---

### 9. What happens with fee deductions?
When a payment gateway deducts a processing fee (e.g. 5,000 INR order credited as 4,950 INR with a 50 INR fee), deterministic scoring detects the fee amount (<= 100 INR max fee threshold) and assigns partial amount evidence (0.40). The candidate is routed to `REVIEW` / AI assistance where the evidence reasoning confirms the fee deduction and upgrades to `MATCHED`.

---

### 10. What happens with date shifts?
Transactions with settlement delays (1–3 days) receive full date score (1.0 for same day, 0.95 for 1 day, 0.90 for 2 days, 0.85 for 3 days). Broader windows (up to 10 days) receive scaled partial scores to allow candidate generation while preventing false matches across months.

---

### 11. How does one-to-one matching work?
In financial accounting, one bank credit can match at most one ledger debit (unless batch aggregate). LedgerLens tracks all assigned bank IDs in `confirmed_bank_map`. If two ledger records attempt to claim the same bank record, the higher-scoring match retains `MATCHED`, and the lower-scoring claim is downgraded to `REVIEW` with rule `ONE_TO_ONE_CONFLICT`.

---

### 12. How is the benchmark generated?
The benchmark generator (`src/data_generator.py`) generates controlled synthetic datasets (225+ ledger, 250+ bank records) spanning 12 distinct scenario classes (`EASY_EXACT`, `NOISY_REFERENCE`, `FEE_DIFFERENCE`, `DATE_SHIFT`, `AMBIGUOUS`, `FALSE_POSITIVE_TRAP`, `UNMATCHED_LEDGER`, `UNMATCHED_BANK`, etc.).

---

### 13. How is leakage prevented?
- **Strict Module Isolation**: `reconciliation.py`, `ai_matcher.py`, `config.py`, `normalization.py`, and `schemas.py` never import or read `answer_key.csv`.
- **Reference Leakage Variations**: Bank statement narrations do not simply copy `ORD-XXXX` strings. 32% of generated bank records use partial references, OCR mutations, or no references.

---

### 14. How can a user upload custom XLSX data?
Users can upload custom `ledger.xlsx` and `bank_statement.xlsx` files via:
1. **Streamlit Web UI**: Simple drag-and-drop file uploaders in `app/app.py`.
2. **REST API**: `POST /api/v1/custom-data/upload` endpoint in `app/api.py`, which validates schema and saves to `data/custom/`.

---

### 15. What does the API return?
- **Standard Mode**: Returns overall status (`success`), `total_records`, and status summary counts (`matched`, `review`, `unmatched`, `decision_sources`).
- **Debug Mode** (`?debug=true`): Returns structured per-transaction observability traces showing candidate scores, rule decisions, AI invocation, and safety validation flags.

---

### 16. What does debug mode show?
For every transaction, debug mode exposes:
- `ledger_id` & `bank_id`
- `status` (`MATCHED`, `REVIEW`, `UNMATCHED`)
- `matching_rule` (e.g. `EXACT_REFERENCE`, `AI_CONFIRMED_MATCH`, `ONE_TO_ONE_CONFLICT`)
- `score` & candidate rank / candidate count
- `amount_difference` & `date_difference`
- `ai_invoked`, `ai_result`, and `final_safety_validation`
