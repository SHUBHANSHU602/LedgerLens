# LedgerLens System Architecture & Data Flow

This document details the multi-tier architectural layout, data pipelines, normalization stages, scoring mechanics, and AI safety boundaries of LedgerLens.

---

## 1. System Pipeline Layout

```text
[ Ledger Dataset ]       [ Bank Statement ]
        │                       │
        └───────────┬───────────┘
                    ▼
       [ Data Validation & Schema Gate ]
                    │
                    ▼
    [ Normalization & Reference Extraction ]
    (Amount float, Date ISO, Text Uppercase)
                    │
                    ▼
     ┌──────────────┴──────────────┐
     │ Multi-Tier Match Pipeline   │
     └──────────────┬──────────────┘
                    │
 ┌──────────────────┼──────────────────┐
 │                  │                  │
 ▼                  ▼                  ▼
[Tier 1: Exact]   [Tier 2: Unique]   [Tier 3: Candidate Scoring]
(Ref + Date + Amt)  (Amount + Date)    (Weighted Score Breakdown)
                                               │
                                      ┌────────┴────────┐
                                      ▼                 ▼
                                [High Confidence]   [Ambiguous / Review]
                                (Score >= 0.82)      (0.45 <= Score < 0.82)
                                      │                 │
                                      │                 ▼
                                      │         [Bounded Groq AI Assist]
                                      │                 │
                                      │       ┌─────────┴─────────┐
                                      │       ▼                   ▼
                                      │  [Pydantic Veto]     [Fallback Review]
                                      │       │
                                      └───────┼───────────────────┘
                                              │
                                              ▼
                             [Global One-to-One Conflict Resolution]
                                              │
                                              ▼
                             [Final Status & Observability Traces]
```

---

## 2. Evidence Scoring Formula

The evidence score between a ledger row and bank statement candidate is calculated as:

$$\text{Score} = (W_{\text{ref}} \times S_{\text{ref}}) + (W_{\text{amount}} \times S_{\text{amount}}) + (W_{\text{date}} \times S_{\text{date}}) + (W_{\text{text}} \times S_{\text{text}})$$

Default Weights:
- $W_{\text{ref}} = 0.40$ (Reference ID match / fuzzy token ratio)
- $W_{\text{amount}} = 0.30$ (Exact amount match or fee deduction fit)
- $W_{\text{date}} = 0.20$ (Calendar date proximity)
- $W_{\text{text}} = 0.10$ (Customer name partial similarity)

---

## 3. Decision Thresholds

- **High Confidence Match**: $\text{Score} \ge 0.82$
- **Review Threshold**: $0.45 \le \text{Score} < 0.82$
- **Ambiguity Margin**: $(\text{Score}_{\text{top1}} - \text{Score}_{\text{top2}}) < 0.08$
- **Low Evidence Unmatched**: $\text{Score} < 0.45$
