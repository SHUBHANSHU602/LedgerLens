# Engineering Decisions & Tradeoffs in LedgerLens

This document explains the core engineering choices, design patterns, and safety tradeoffs made during the development of LedgerLens.

---

## 1. Multi-Tier Deterministic Engine Before AI

### Decision
Prioritize deterministic rules (exact reference extraction, exact amount/date matching, weighted multi-factor scoring) before escalating to Groq LLM assistance.

### Rationale
- **Cost Efficiency**: Over 70% of financial transactions can be matched deterministically with 100% precision for $0 in API costs.
- **Speed & Latency**: Deterministic matching runs in milliseconds per thousand transactions locally.
- **Auditability**: Deterministic rules are fully reproducible and easy for auditors to verify.
- **Privacy**: Keeps sensitive transaction logs local whenever possible.

---

## 2. Bounded AI Assistance & Hard Safety Vetoes

### Decision
The Groq LLM is used **only** as an evidence assistant for ambiguous records reaching `REVIEW`. AI decisions are strictly validated against deterministic safety invariants.

### Rationale
- **Hallucination Protection**: LLMs can occasionally generate non-existent IDs. If the LLM returns a `selected_bank_id` not present in the candidate pool, `ai_matcher` vetoes the decision and forces `same_transaction = False` and status `REVIEW`.
- **Contradiction Vetoes**: Hard constraints (currency mismatches, excessive amount gaps) can never be overridden by AI reasoning.

---

## 3. Score-Based One-to-One Conflict Resolution

### Decision
Implement score-based one-to-one conflict resolution for bank transaction assignments.

### Rationale
In accounting, a bank credit can match at most one ledger order. When multiple ledger records attempt to claim the same bank record, LedgerLens compares their evidence scores:
- The record with the higher confidence score retains `MATCHED`.
- The lower-scoring conflicting record is downgraded to `REVIEW` with rule `ONE_TO_ONE_CONFLICT`.

---

## 4. Strict Ground Truth Separation

### Decision
Isolate matching runtime modules (`reconciliation.py`, `ai_matcher.py`, `normalization.py`, `schemas.py`) completely from `answer_key.csv`.

### Rationale
In real-world production reconciliation, an answer key does not exist. To prevent data leakage and guarantee genuine generalization, runtime matching modules must never import or read ground truth files.
