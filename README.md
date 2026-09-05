# LedgerLens: AI-Powered Financial Reconciliation Engine

LedgerLens is an enterprise-grade financial reconciliation engine combining multi-tier deterministic matching with guardrailed Groq AI assistance. It reconciles internal sales/order ledgers against bank statements and payment gateway settlements with mathematical rigor, bounded LLM invocation, policy-driven automation, and an immutable audit trail.

---

## 📌 Table of Contents
- [The Problem](#-the-problem)
- [The Solution: Multi-Tier Bounded Architecture](#-the-solution-multi-tier-bounded-architecture)
- [Bounded Agent Workflow Loop](#-bounded-agent-workflow-loop)
- [Core Agent Components](#-core-agent-components)
- [The Role of AI & Rate Limit Governance](#-the-role-of-ai--rate-limit-governance)
- [Interactive Streamlit Web Dashboard](#-interactive-streamlit-web-dashboard)
- [Benchmark Ground-Truth Evaluation](#-benchmark-ground-truth-evaluation)
- [REST API & Observability](#-rest-api--observability)
- [Installation & Quickstart](#-installation--quickstart)
- [Groq API Key Configuration & Rate Limits](#-groq-api-key-configuration--rate-limits)
- [Streamlit Cloud Deployment](#-streamlit-cloud-deployment)
- [Developer CLI Commands](#-developer-cli-commands)
- [Known Limitations](#-known-limitations)

---

## ⚠️ The Problem

Financial reconciliation is a mandatory accounting process where internal transaction ledgers must be verified against external bank credits. Manual reconciliation is slow, expensive, and error-prone due to:
- **Gateway Fee Deductions (MDR)**: A ₹5,000 internal order credited as ₹4,950 due to a ₹50 deduction.
- **Settlement Date Delays**: Orders placed on Monday may appear in bank statements 1 to 3 business days later.
- **Narration Noise & Truncation**: Banking rails append prefixes, bank codes, or truncate references (e.g. `CMS/N1024/SETTL` instead of `ORD-1024`).
- **Duplicate & Near-Duplicate Ambiguity**: Multiple identical-amount orders on the same date requiring one-to-one conflict resolution.

---

## 💡 The Solution: Multi-Tier Bounded Architecture

LedgerLens operates on a **deterministic-first, bounded-AI** principle:

```
                  ┌─────────────────────────────────────┐
                  │   Internal Ledger & Bank Statement  │
                  └──────────────────┬──────────────────┘
                                     │
                         1. Schema Normalization
                         (Floats, ISO dates, text)
                                     │
                                     ▼
                   ┌───────────────────────────────────┐
                   │ Tier 1: Exact Reference Matching  │──▶ MATCHED (~60%)
                   └─────────────────┬─────────────────┘
                                     │ Unmatched
                                     ▼
                   ┌───────────────────────────────────┐
                   │ Tier 2: Unique Amount + Date Match│──▶ MATCHED (~10%)
                   └─────────────────┬─────────────────┘
                                     │ Unmatched
                                     ▼
                   ┌───────────────────────────────────┐
                   │ Tier 3: Multi-Evidence Scoring    │──▶ MATCHED (Score ≥ 0.82)
                   │ (Ref 40%, Amt 30%, Date 20%, Name)│──▶ UNMATCHED (Score < 0.45)
                   └─────────────────┬─────────────────┘
                                     │
                        Ambiguous Pool (0.45 ≤ Score < 0.82)
                                     │
                                     ▼
                   ┌───────────────────────────────────┐
                   │ Bounded Groq LLM Assistant        │──▶ MATCHED (AI validated)
                   │ (Top 3 candidates only + Vetoes)  │──▶ REVIEW (Safe fallback)
                   └───────────────────────────────────┘
```

1. **Deterministic Core (70–75% Coverage)**: High-confidence exact reference matches and unique amount/date pairs are reconciled instantaneously with zero API cost.
2. **Multi-Evidence Weighted Scoring**: Balances reference similarity, date proximity, amount difference, and customer text.
3. **Bounded AI Assistance (~15–25% Escalation)**: Only ambiguous records are sent to the Groq LLM with strictly restricted candidate pools and deterministic validation vetoes.
4. **Stateful Policy & Action Engine**: Automatically executes low-risk actions (e.g., fee adjustments $\le ₹100$) and routes high-risk conflicts to human review.

---

## 🔄 Bounded Agent Workflow Loop

```mermaid
graph TD
    A[Data Sources: Ledger & Bank Statement] --> B[1. OBSERVE & INGEST]
    B --> C[2. NORMALIZE & VALIDATE]
    C --> D[3. RECONCILE: Multi-Tier Engine]
    D --> E{Deterministic Match Status?}
    E -- "High Confidence MATCHED" --> F[4. POLICY ENGINE Check]
    E -- "Ambiguous / Review Exception" --> G[5. EXCEPTION INVESTIGATOR Agent]
    E -- "UNMATCHED Record" --> F
    G --> H[6. STRUCTURED RECOMMENDATION]
    H --> F
    F -- "Low-Risk Auto-Allowed" --> I[7. ACTION SERVICE Execution]
    F -- "High-Risk / Human Required" --> J[8. ACTION_PENDING_APPROVAL Human Review]
    I --> K[9. VERIFICATION LOOP]
    J -- "Human Approved" --> I
    K -- "Outcome Verified" --> L[10. APPEND-ONLY AUDIT LOG & State Update]
```

---

## 🧩 Core Agent Components

### 1. Stateful Case Machine (`src/agent/models.py`)
Tracks transaction reconciliation through explicit states:
`NEW` → `INGESTING` → `NORMALIZING` → `RECONCILING` → `INVESTIGATING` → `RECOMMENDATION_READY` → `POLICY_APPROVED` → `ACTION_EXECUTING` → `ACTION_VERIFYING` → `RESOLVED`.

### 2. Exception Investigator (`src/agent/investigator.py`)
Classifies discrepancies into domain exceptions (`FEE_ADJUSTMENT`, `DATE_MISMATCH`, `ONE_TO_ONE_CONFLICT`, `CURRENCY_MISMATCH`, `BATCH_AGGREGATE_SUSPECTED`) and generates actionable recommendations.

### 3. Deterministic Policy Engine (`src/agent/policy.py`)
Enforces financial guardrails:
- **Fee Adjustment Tolerance**: Auto-adjustment allowed **only** if fee variance $\le ₹100.0$.
- **Auto-Match Threshold**: Auto-approval allowed **only** if confidence score $\ge 0.82$.
- **Prompt Injection Defense**: Defense-in-depth sanitization (`sanitize_untrusted_text`) stripping control characters, redacting URLs (`[REDACTED_URL]`), limiting character flooding, sanitizing jailbreak/override phrases (`[REDACTED_TEXT]`), and truncating untrusted text.
- **Risk Tiers**: Assigns `LOW`, `MEDIUM`, or `HIGH` risk classifications.

### 4. Action Handlers & Outcome Verification (`src/agent/actions.py`)
Bounded actions (`MARK_RECONCILED`, `CREATE_FEE_ADJUSTMENT`, `FLAG_FOR_REVIEW`, `MARK_UNMATCHED`) run through post-execution verification checks and idempotency guards (`case_id:action_type` keys).

---

## 🤖 The Role of AI & Rate Limit Governance

### Why 200+ Rows ≠ 200 API Calls
In LedgerLens, the LLM is **never** invoked for all rows. Because deterministic matching handles ~75% of transactions and rejects clear non-matches:
- In a canonical **225-row dataset**, only **15 to 25 records** require AI evaluation.
- A single free-tier Groq API key (30 RPM) can process the entire 225-record benchmark without exceeding rate limits.

### Built-in Governance & Safety Guards
1. **Sliding-Window Rate Limiter**: Controls outgoing requests via a sliding 60-second window (default 25 RPM) configured via `GROQ_MAX_CALLS_PER_MINUTE`. Calls pause automatically to avoid HTTP 429 errors.
2. **HTTP 429 Exponential Backoff**: Automatically pauses and retries up to 3 times (`2s`, `4s`, `8s`) if rate limits are reached.
3. **Deterministic Hallucination Veto**: The engine supplies only the top 3 candidates to the model. If the LLM selects a bank ID outside this candidate set, the decision is immediately vetoed and routed to `REVIEW`.
4. **In-Memory Decision Cache**: Identical candidate comparisons are cached in memory, preventing duplicate API calls.
5. **Safe Degradation**: If an API key is missing, network fails, or output JSON is malformed, transactions safely default to `REVIEW` with clear audit logs.

---

## 🖥️ Interactive Streamlit Web Dashboard

Launch the web application:
```bash
streamlit run app/app.py
```

### Modes of Operation
- **Standard (Live Data)**:
  - Upload custom internal ledgers and bank statements (CSV or XLSX).
  - One-click **"📁 Load Sample Datasets"** for instant local exploration.
  - Interactive **"👁️ View Active Dataset Previews"** showing live tables and row counts.
  - **"🔄 Reset / Clear Active Data"** button to reset session state and browser uploaders.
- **Benchmark (Ground Truth)**:
  - Automatically loads canonical benchmark files (`data/ledger.csv` and `data/bank_statement.csv`).
  - Evaluates engine and AI matcher performance against `data/answer_key.csv`.
  - Displays Pair Precision, Pair Recall, F1 Score, Auto-Resolution Precision, and an interactive **2×2 Confusion Matrix** (TP, FP, FN, TN).

### Complete Results Dashboard
- **Performance Summary KPIs**: Exact batch totals and percentages (`Total Records`, `Matched`, `Review Required`, `Unmatched`, `AI Escalations`) with clean layout and no misleading trend arrows.
- **Exception Summary Tab**: Lists ambiguous and unmatched items with explicit `resolution_guidance`.
- **Agent Activity & Trace Tab**: Displays case intelligence, verification pass rates, and the full audit registry generated automatically upon reconciliation.
- **Audit & CSV Export**: Download reconciled results as CSV with one click.

---

## 📊 Benchmark Ground-Truth Evaluation

LedgerLens includes a synthetic benchmark generator (`scripts/generate_dataset.py`) producing 225+ ledger records and 250+ bank statement records across 12 real-world scenarios:
- `EASY_EXACT`, `NOISY_REFERENCE`, `FEE_DIFFERENCE`, `DATE_SHIFT`, `DUPLICATE_NEAR_DUPLICATE`, `AMBIGUOUS`, `FALSE_POSITIVE_TRAP`, `AMOUNT_NEAR_MATCH`, `UNMATCHED_LEDGER`, `UNMATCHED_BANK`, `REVERSAL_ADJUSTMENT`, `FEE_ONLY_SETTLEMENT`.

### Benchmark Accuracy Metrics
| Metric | Formula | Benchmark Score | Description |
| :--- | :--- | :---: | :--- |
| **Pair Precision** | $\frac{TP}{TP + FP}$ | **96.4%** | Accuracy of matches made |
| **Pair Recall** | $\frac{TP}{TP + FN}$ | **100.0%** | Fraction of true matches captured |
| **F1 Score** | $2 \cdot \frac{P \cdot R}{P + R}$ | **98.2%** | Harmonic balance of precision & recall |
| **Auto-Resolution Precision** | $\frac{AutoTP}{AutoTP + AutoFP}$ | **96.4%** | Accuracy of deterministic rules before AI |
| **Automated Coverage** | $\frac{Matched}{Total}$ | **73.8%** | Fraction resolved without human review |
| **AI Escalation Rate** | $\frac{AI Calls}{Total}$ | **23.1%** | Fraction routed to Groq compound LLM |

---

## 🌐 REST API & Observability

Start the FastAPI server:
```bash
uvicorn app.api:app --reload --port 8000
```

### Endpoints
- `GET /api/v1/health`: System status, data source, and configuration health.
- `POST /api/v1/reconcile`: Executes reconciliation over active datasets.
  - Supports `?debug=true` to include per-transaction evidence breakdown and AI traces.
- `POST /api/v1/custom-data/upload`: Uploads custom ledger or bank statement files.
- `POST /api/v1/agent/run`: Triggers the bounded agent lifecycle and returns an `AgentRunSummary`.
- `GET /api/v1/audit`: Returns chronological `AuditEvent` history.

---

## 🚀 Installation & Quickstart

### 1. Prerequisites
- Python 3.10, 3.11, or 3.12 (Python 3.11 recommended).
- Git.

### 2. Clone & Install
```bash
git clone https://github.com/ZigzagDeck/LedgerLens.git
cd LedgerLens
python -m venv venv
source venv/bin/activate   # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 3. Configure Secrets
Create a `.env` file from the provided template:
```bash
cp .env.example .env
```
Edit `.env` to include your Groq API key:
```env
GROQ_API_KEY=gsk_your_groq_api_key_here
GROQ_MAX_CALLS_PER_MINUTE=25
```

---

## 🔑 Groq API Key Configuration & Rate Limits

1. **Obtaining a Free Key (30 RPM)**:
   - Create a free account at [console.groq.com](https://console.groq.com/).
   - Navigate to **API Keys** ➔ **Create API Key**.
   - Copy the key starting with `gsk_...`.
2. **Where to Configure**:
   - **Local `.env`**: Set `GROQ_API_KEY=gsk_...`
   - **Streamlit Sidebar**: Paste directly into the password field under **"Groq API Key (Live Inference)"**.
   - **Streamlit Cloud**: Add `GROQ_API_KEY = "gsk_..."` under App Settings ➔ Secrets.
3. **Upgrading Beyond 30 RPM (100–1,000 RPM)**:
   - In Groq Console, visit **Settings ➔ Billing** and add payment details ($5–$10 credit).
   - Upgrades your account to On-Demand Tier with 100–1,000 RPM.
   - You can then raise **"Max Groq Calls / Min"** in the sidebar to `60` for rapid bulk reconciliation.

---

## ☁️ Streamlit Cloud Deployment

1. Fork or push this repository to GitHub.
2. Sign in to [share.streamlit.io](https://share.streamlit.io/).
3. Create a new app:
   - **Repository**: `YourUsername/LedgerLens`
   - **Branch**: `main`
   - **Main file path**: `app/app.py`
4. Under **Advanced Settings ➔ Secrets**, provide:
   ```toml
   GROQ_API_KEY = "gsk_your_key_here"
   ```
5. Deployment automatically uses Python 3.11 as specified in `.python-version`.

---

## 🛠️ Developer CLI Commands

```bash
# Run complete test suite (62 tests)
python -m pytest -q

# Generate fresh synthetic benchmark dataset
python -m scripts.generate_dataset --seed 123 --ledger-count 200 --bank-count 200 --output-dir data

# Verify data & source repository isolation
python -m scripts.audit_repo

# Run benchmark evaluation CLI
python -m scripts.run_benchmark

# Run throughput scalability benchmark (250 to 10K rows)
python -m scripts.run_throughput
```

---

## ⚠️ Known Limitations

1. **Multi-Order Batch Settlement Detection**: Payment gateways often aggregate multiple ledger orders into a single net settlement credit. LedgerLens includes a `detect_batch_aggregates()` heuristic detector that flags nearby candidate order combinations. Full subset-sum optimization for arbitrary 10+ order combinations is under active development.
2. **Multi-Currency Conversion**: Live foreign exchange (FX) conversion is not implemented; cross-currency pairs are safely flagged and routed to `REVIEW`.

---

## 📄 License

MIT License. Designed and engineered for transparent, deterministic financial reconciliation.
