# LedgerLens Debugging & Transaction Tracing Guide

This guide explains how developers can debug reconciliation runs, inspect intermediate scores, trace failed transactions, and interpret API observability outputs.

---

## 1. Enabling Debug Mode

### Environment Variable:
Set in `.env` or shell:
```bash
LEDGERLENS_DEBUG_MODE=true
```

### REST API Query Parameter:
Append `?debug=true` to reconciliation requests:
```bash
curl -X POST "http://127.0.0.1:8000/api/v1/reconcile?debug=true"
```

---

## 2. Inspecting Transaction Traces

When debug mode is enabled, the API returns a structured `traces` array per ledger transaction:

```json
{
  "ledger_id": "ORD-1043",
  "bank_id": "UTR500143",
  "status": "REVIEW",
  "matching_rule": "AI_REVIEW_REQUIRED",
  "score": 0.72,
  "reason": "AI Review: Two plausible settlement candidates",
  "decision_source": "groq",
  "ai_invoked": true,
  "ai_result": {
    "model_used": "groq/compound",
    "ai_reason": "Bank narration shows MDR fee deduction of 50 INR.",
    "original_score": 0.72
  },
  "final_safety_validation": true,
  "candidate_count": 3,
  "amount_difference": 50.0,
  "date_difference": 0
}
```

---

## 3. Common Transaction Status Rules

- `EXACT_REFERENCE`: Tier-1 match on exact order ID and clean date/amount.
- `EXACT_AMOUNT_DATE`: Tier-2 match on unique exact amount and date.
- `SCORE_MATCHED`: Tier-3 high confidence score (>= 0.82).
- `AI_CONFIRMED_MATCH`: Tier-3 match upgraded after Groq AI evidence confirmation.
- `AI_REVIEW_REQUIRED`: Routed to human audit by AI or safe fallback on rate limit / network error.
- `AMBIGUOUS_CANDIDATES`: Top candidates have score delta within ambiguity margin (0.08).
- `ONE_TO_ONE_CONFLICT`: Bank transaction was claimed by a higher-scoring match.
- `CURRENCY_MISMATCH`: Hard safety veto triggered by conflicting currency strings.
- `NO_CANDIDATE`: No candidate within broad window (10 days) or tolerance (5%).

---

## 4. Retrieving the Last Reconciliation Run Traces

To inspect traces of the most recent reconciliation run:
```bash
curl -X GET "http://127.0.0.1:8000/api/v1/reconcile/"
```
