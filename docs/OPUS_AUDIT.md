# LedgerLens — Opus Audit Report

## Date: September 2026

## Architecture Summary

```
Input (Ledger CSV/XLSX + Bank CSV/XLSX)
  │
  ├── Razorpay Adapter (src/connectors/razorpay.py)
  │     Normalizes Razorpay settlements into canonical schema
  │
  ▼
Schema Validation (src/data_validation.py)
  │
  ▼
Normalization (src/normalization.py)
  │   Amount → float, Date → ISO, Text → uppercase, Reference extraction
  │
  ▼
Multi-Tier Reconciliation Engine (src/reconciliation.py)
  │
  ├── Tier 1: Exact Reference Match
  ├── Tier 2: Exact Amount + Date (unique)
  ├── Tier 3: Candidate Generation + Evidence Scoring
  │     ├── High Confidence (≥0.82) → MATCHED
  │     ├── Ambiguous (0.45–0.82) → Bounded AI
  │     │     ├── AI Confirms → MATCHED (with veto checks)
  │     │     └── AI Review/Error → REVIEW
  │     └── Low Score (<0.45) → UNMATCHED
  │
  └── Global One-to-One Conflict Resolution
        └── Duplicate bank claims → lower score downgraded to REVIEW
  │
  ▼
Finance Controller (src/services/finance_controller.py)
  │   Classifies exceptions, determines batch status, recommends actions
  │
  ▼
Output: MATCHED / REVIEW / UNMATCHED + Batch Summary + Debug Traces
```

## Entrypoints

| Entrypoint | Purpose |
|-----------|---------|
| `app/app.py` | Streamlit web dashboard |
| `api/server.py` | FastAPI REST server |
| `scripts/generate_dataset.py` | Benchmark dataset generator |
| `scripts/run_benchmark.py` | Evaluation benchmark runner |
| `scripts/run_throughput.py` | Throughput measurement |
| `scripts/audit_dataset.py` | Dataset quality audit |

## Data Flow

1. **Input**: Ledger + Bank CSVs/XLSX
2. **Validation**: Schema, types, duplicates, dates
3. **Normalization**: Amounts, dates, text, reference extraction
4. **Tier 1**: Exact reference substring match in bank narration
5. **Tier 2**: Unique amount+date match (no reference contradiction)
6. **Tier 3**: Broad candidate pool → evidence scoring → ambiguity gate → AI
7. **Conflict Resolution**: Global one-to-one deduplication
8. **Finance Controller**: Exception classification + batch status
9. **Output**: Results DataFrame + API response + debug traces

## AI Flow

1. Ambiguous record enters AI gate (score 0.45–0.82 OR top-2 candidates within margin)
2. Top `AI_CANDIDATE_LIMIT` (3) candidates sent to Groq LLM
3. LLM returns structured JSON with `same_transaction`, `selected_bank_id`
4. Pydantic validation of response schema
5. Safety vetoes: missing ID → REVIEW, hallucinated ID → REVIEW, malformed JSON → REVIEW
6. Validated AI match → MATCHED; all else → REVIEW

## Known Defects Found & Fixed

| Defect | Severity | Fix |
|--------|----------|-----|
| UI reads `precision`/`recall` but evaluator returns `pair_precision`/`pair_recall` | P0 | Fixed metric keys in app.py |
| Evaluation runs benchmark data regardless of uploaded custom data | P0 | Added `precomputed_results` parameter |
| `TOP_N_CANDIDATES=5` but AI only sees `[:3]` candidates, validation checks all 5 | P0 | Introduced `AI_CANDIDATE_LIMIT` constant |
| `.env.example` contains real API key | P0 | Replaced with placeholder |
| No Finance Controller loop | P1 | Created `src/services/finance_controller.py` |
| No Razorpay source adapter | P1 | Created `src/connectors/razorpay.py` |
| No holdout benchmark split | P1 | Added `--mode dev/holdout/demo` to generator |
| No throughput measurement | P1 | Created `scripts/run_throughput.py` |

## Files Modified

| File | Change |
|------|--------|
| `src/config.py` | Added `AI_CANDIDATE_LIMIT` |
| `src/reconciliation.py` | Use `AI_CANDIDATE_LIMIT` for candidate slicing |
| `src/ai_matcher.py` | Use `config.AI_CANDIDATE_LIMIT` instead of `[:3]` |
| `src/evaluation.py` | Configurable input, expanded metrics, precision@coverage |
| `app/app.py` | Fixed metric keys, STANDARD/BENCHMARK modes, exception tab |
| `app/api.py` | Wired Finance Controller |
| `.env.example` | Removed leaked API key |

## Files Created

| File | Purpose |
|------|---------|
| `src/services/finance_controller.py` | Batch orchestration + exception classification |
| `src/connectors/razorpay.py` | Razorpay settlement adapter |
| `scripts/run_throughput.py` | Throughput benchmark |
| `tests/test_finance_controller.py` | Finance Controller tests |
| `tests/test_razorpay.py` | Razorpay adapter tests |
| `docs/THROUGHPUT.md` | Throughput methodology |
| `docs/OPUS_AUDIT.md` | This audit document |
