import os
import sys
import io
import pandas as pd
import streamlit as st

# Ensure repository root is always in sys.path
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from src.config import ReconciliationConfig, CONFIG
from src.reconciliation import reconcile
from src.evaluation import evaluate_reconciliation
from src.agent import ReconciliationAgent


# -----------------------------------------------------------------------------
# 1. Page Configuration & Aesthetic Styling
# -----------------------------------------------------------------------------

st.set_page_config(
    page_title="LedgerLens — AI Finance Controller",
    page_icon="⚖️",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    .main-header {
        font-size: 2.2rem;
        font-weight: 700;
        margin-bottom: 0.2rem;
    }
    .sub-header {
        font-size: 1.0rem;
        opacity: 0.75;
        margin-bottom: 1.5rem;
    }
    .headline-metric {
        font-size: 1.05rem;
        font-weight: 600;
        background: rgba(20, 184, 166, 0.12);
        border-radius: 8px;
        border-left: 4px solid #14B8A6;
        padding: 10px 16px;
        margin: 10px 0;
    }
    div[data-testid="stMetric"], .stMetric {
        background-color: rgba(128, 128, 128, 0.08) !important;
        border-radius: 10px !important;
        padding: 14px 16px !important;
        border: 1px solid rgba(128, 128, 128, 0.18) !important;
        box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05);
    }
    div[data-testid="stMetric"]:hover {
        border-color: rgba(20, 184, 166, 0.5) !important;
    }
    </style>
    """,
    unsafe_allow_html=True,
)

# -----------------------------------------------------------------------------
# 2. Sidebar Configuration Controls
# -----------------------------------------------------------------------------

st.sidebar.title("⚙️ Reconciliation Settings")
st.sidebar.markdown("---")

amt_tol = st.sidebar.number_input("Amount Tolerance (INR)", min_value=0.0, max_value=10.0, value=float(CONFIG.AMOUNT_TOLERANCE), step=0.01)
date_win = st.sidebar.number_input("Date Window (Days)", min_value=0, max_value=30, value=int(CONFIG.DATE_WINDOW_DAYS), step=1)
high_thresh = st.sidebar.slider("Auto-Match Threshold", min_value=0.50, max_value=0.95, value=float(CONFIG.HIGH_CONFIDENCE_THRESHOLD), step=0.01)
review_thresh = st.sidebar.slider("Review Threshold", min_value=0.10, max_value=0.70, value=float(CONFIG.REVIEW_THRESHOLD), step=0.01)
enable_ai = st.sidebar.checkbox("Enable Groq AI Assistance", value=bool(CONFIG.ENABLE_AI_ASSIST))

if enable_ai:
    # Resolve initial key from os.environ or st.secrets
    current_key = os.getenv("GROQ_API_KEY", "")
    try:
        if not current_key and hasattr(st, "secrets") and "GROQ_API_KEY" in st.secrets:
            current_key = str(st.secrets["GROQ_API_KEY"]).strip()
    except Exception:
        pass

    user_groq_key = st.sidebar.text_input(
        "Groq API Key (Live Inference)",
        value=current_key,
        type="password",
        help="Enter your Groq API key (starts with gsk_...) for live AI assistance.",
    )
    if user_groq_key:
        os.environ["GROQ_API_KEY"] = user_groq_key.strip()
        st.sidebar.caption("🟢 Live Groq AI: Key configured")
    else:
        st.sidebar.caption("🟡 No Key: AI safely defaults to REVIEW")

    calls_per_min = st.sidebar.number_input(
        "Max Groq Calls / Min",
        min_value=5,
        max_value=60,
        value=int(getattr(CONFIG, "GROQ_MAX_CALLS_PER_MINUTE", 25)),
        step=5,
        help="Rate limit threshold for Groq API calls to avoid 429 errors.",
    )
else:
    calls_per_min = 25

st.sidebar.markdown("---")
st.sidebar.markdown("**Mode**")
run_mode = st.sidebar.radio("Evaluation Mode", ["Standard (Live Data)", "Benchmark (Ground Truth)"], index=0)
is_benchmark_mode = run_mode.startswith("Benchmark")

user_config = ReconciliationConfig(
    AMOUNT_TOLERANCE=amt_tol,
    DATE_WINDOW_DAYS=date_win,
    HIGH_CONFIDENCE_THRESHOLD=high_thresh,
    REVIEW_THRESHOLD=review_thresh,
    ENABLE_AI_ASSIST=enable_ai,
    GROQ_MAX_CALLS_PER_MINUTE=int(calls_per_min),
)

# -----------------------------------------------------------------------------
# 3. Main Header & File Uploaders
# -----------------------------------------------------------------------------

st.markdown('<div class="main-header">LedgerLens — AI Finance Controller</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-header">Deterministic + Bounded AI Reconciliation · "What broke at 2 AM?"</div>', unsafe_allow_html=True)

col_u1, col_u2 = st.columns(2)
with col_u1:
    ledger_file = st.file_uploader("Upload Internal Ledger (CSV or XLSX)", type=["csv", "xlsx"])
with col_u2:
    bank_file = st.file_uploader("Upload Bank Statement (CSV or XLSX)", type=["csv", "xlsx"])

# -----------------------------------------------------------------------------
# 4. Data Loading & Schema Validation
# -----------------------------------------------------------------------------

df_ledger, df_bank = None, None
use_sample = st.button("📁 Load Sample Datasets from data/", use_container_width=False)
data_source_label = "uploaded"

sample_ledger_path = os.path.join(ROOT_DIR, "data", "ledger.csv")
sample_bank_path = os.path.join(ROOT_DIR, "data", "bank_statement.csv")
sample_answer_key_path = os.path.join(ROOT_DIR, "data", "answer_key.csv")

if ledger_file and bank_file:
    try:
        if ledger_file.name.endswith(".xlsx"):
            df_ledger = pd.read_excel(ledger_file, engine="openpyxl")
        else:
            df_ledger = pd.read_csv(ledger_file)

        if bank_file.name.endswith(".xlsx"):
            df_bank = pd.read_excel(bank_file, engine="openpyxl")
        else:
            df_bank = pd.read_csv(bank_file)
        data_source_label = "uploaded"
    except Exception as err:
        st.error(f"Error reading uploaded CSV/XLSX files: {err}")
elif use_sample or (os.path.exists(sample_ledger_path) and os.path.exists(sample_bank_path) and not ledger_file and not bank_file):
    if os.path.exists(sample_ledger_path) and os.path.exists(sample_bank_path):
        df_ledger = pd.read_csv(sample_ledger_path)
        df_bank = pd.read_csv(sample_bank_path)
        data_source_label = "benchmark"
        st.info("Loaded sample datasets from `data/ledger.csv` and `data/bank_statement.csv`.")

def validate_datasets(df_l: pd.DataFrame, df_b: pd.DataFrame) -> bool:
    """Validate non-empty datasets and required schema columns."""
    if df_l is None or df_b is None:
        st.warning("Please upload both Ledger and Bank Statement files.")
        return False
    if df_l.empty:
        st.error("Validation Error: Ledger dataset is empty.")
        return False
    if df_b.empty:
        st.error("Validation Error: Bank statement dataset is empty.")
        return False

    missing_l = [c for c in ["order_id", "amount", "order_date"] if c not in df_l.columns]
    missing_b = [c for c in ["utr_reference", "credited_amount", "value_date"] if c not in df_b.columns]

    if missing_l:
        st.error(f"Validation Error: Ledger CSV/XLSX missing required columns: {missing_l}")
        return False
    if missing_b:
        st.error(f"Validation Error: Bank Statement CSV/XLSX missing required columns: {missing_b}")
        return False

    return True

# -----------------------------------------------------------------------------
# 5. Reconciliation Execution & KPI Dashboard
# -----------------------------------------------------------------------------

if validate_datasets(df_ledger, df_bank):
    if st.button("🚀 Run Reconciliation Engine", type="primary", use_container_width=True):
        with st.spinner("Executing Multi-Tier Deterministic & AI Reconciliation..."):
            results = reconcile(df_ledger, df_bank, config=user_config)
            st.session_state["reconciled_results"] = results
            st.session_state["data_source"] = data_source_label

            # Run evaluation ONLY in benchmark mode AND when answer key exists for the current dataset
            if is_benchmark_mode and data_source_label == "benchmark" and os.path.exists(sample_answer_key_path):
                try:
                    # Pass precomputed results so evaluation uses the SAME data+config
                    eval_metrics = evaluate_reconciliation(
                        data_dir=os.path.join(ROOT_DIR, "data"),
                        config=user_config,
                        precomputed_results=results,
                    )
                    st.session_state["eval_metrics"] = eval_metrics
                except Exception as eval_err:
                    st.warning(f"Ground truth evaluation notice: {eval_err}")
                    st.session_state["eval_metrics"] = {}
            else:
                st.session_state["eval_metrics"] = {}

if "reconciled_results" in st.session_state:
    results = st.session_state["reconciled_results"]
    eval_m = st.session_state.get("eval_metrics", {})
    current_source = st.session_state.get("data_source", "unknown")

    total_rows = len(results)
    matched_cnt = len(results[results["status"] == "MATCHED"])
    review_cnt = len(results[results["status"] == "REVIEW"])
    unmatched_cnt = len(results[results["status"] == "UNMATCHED"])
    ai_calls_cnt = len(results[results["decision_source"] == "groq"]) if "decision_source" in results.columns else 0

    st.markdown("### 📊 Reconciliation Performance Summary")

    # Show data source badge
    if current_source == "uploaded":
        st.caption("📎 **Mode: Standard (Live/Uploaded Data)** — No benchmark evaluation applied")
    else:
        st.caption("📊 **Mode: Benchmark (Sample Data)**")

    kpi1, kpi2, kpi3, kpi4, kpi5 = st.columns(5)
    kpi1.metric("Total Records", total_rows)
    kpi2.metric("Matched", matched_cnt, f"{matched_cnt/total_rows*100:.1f}%")
    kpi3.metric("Review Required", review_cnt, f"{review_cnt/total_rows*100:.1f}%")
    kpi4.metric("Unmatched", unmatched_cnt, f"{unmatched_cnt/total_rows*100:.1f}%")
    kpi5.metric("AI-Assisted", ai_calls_cnt, "REVIEW Pool Only")

    # Display ground truth metrics ONLY when they exist (benchmark mode)
    if eval_m:
        headline = eval_m.get("headline", "")
        if headline:
            st.markdown(f'<div class="headline-metric">🎯 {headline}</div>', unsafe_allow_html=True)

        cm = eval_m.get("confusion_matrix", {})
        fp_cnt = cm.get("FP", 0)
        fn_cnt = cm.get("FN", 0)

        m1, m2, m3, m4, m5, m6 = st.columns(6)
        m1.metric("Pair Precision", f"{eval_m.get('pair_precision', 0):.4f}")
        m2.metric("Pair Recall", f"{eval_m.get('pair_recall', 0):.4f}")
        m3.metric("F1 Score", f"{eval_m.get('f1_score', 0):.4f}")
        m4.metric("Auto-Res. Precision", f"{eval_m.get('auto_resolution_precision', 0):.4f}")
        m5.metric("False Positives", fp_cnt)
        m6.metric("False Negatives", fn_cnt)

    # -------------------------------------------------------------------------
    # 6. Detailed Results Tabs & Exception-First View
    # -------------------------------------------------------------------------

    tab_exceptions, tab_agent, tab_matched, tab_review, tab_unmatched, tab_eval = st.tabs([
        "🔍 Exception Summary", "🤖 Agent Activity & Trace", "✅ Matched", "⚠️ Review Required", "❌ Unmatched", "🎯 Benchmark"
    ])

    cols_to_show = ["ledger_id", "bank_id", "status", "matching_rule", "score", "reason", "decision_source", "model_used"]
    cols_exist = [c for c in cols_to_show if c in results.columns]

    with tab_exceptions:
        st.markdown("### 🔍 What Broke at 2 AM? — Exception Summary")
        df_exc = results[results["status"].isin(["REVIEW", "UNMATCHED"])].copy()
        if not df_exc.empty:
            exc_cols = ["ledger_id", "bank_id", "status", "matching_rule", "score", "reason"]
            exc_exist = [c for c in exc_cols if c in df_exc.columns]
            df_exc["action"] = df_exc["matching_rule"].map({
                "AMBIGUOUS_CANDIDATES": "Human review required",
                "AI_REVIEW_REQUIRED": "AI inconclusive — manual check",
                "SCORE_REVIEW": "Low confidence — verify manually",
                "ONE_TO_ONE_CONFLICT": "Resolve duplicate claim",
                "NO_CANDIDATE": "Missing counterparty — investigate",
                "LOW_SCORE": "No plausible match found",
                "NO_MATCH": "Bank record without ledger entry",
                "CURRENCY_MISMATCH": "Currency mismatch — verify",
            }).fillna("Review required")
            st.dataframe(df_exc[exc_exist + ["action"]], use_container_width=True, hide_index=True)
        else:
            st.success("No exceptions — all transactions reconciled successfully!")

    with tab_agent:
        st.markdown("### 🤖 Bounded Financial Reconciliation Agent Workflow")
        st.markdown("`OBSERVE → NORMALIZE → RECONCILE → INVESTIGATE → POLICY CHECK → ACT → VERIFY → AUDIT`")

        if st.button("▶ Run Agent Workflow", type="secondary"):
            with st.spinner("Executing Bounded Agent Loop..."):
                agent_inst = ReconciliationAgent()
                summary_inst = agent_inst.observe_and_reconcile(df_ledger, df_bank)
                st.session_state["agent_summary"] = summary_inst

        if "agent_summary" in st.session_state:
            ag_sum = st.session_state["agent_summary"]
            ac1, ac2, ac3, ac4, ac5 = st.columns(5)
            ac1.metric("Agent Cases", ag_sum.total_cases)
            ac2.metric("Resolved", ag_sum.resolved_count, f"Auto: {ag_sum.auto_resolved_count}")
            ac3.metric("Fee Adjustments", ag_sum.fee_adjusted_count)
            ac4.metric("Pending Approval", ag_sum.pending_approval_count)
            ac5.metric("Verification Rate", f"{ag_sum.verification_pass_rate*100:.1f}%")

            st.markdown(ag_sum.summary_markdown)

            if ag_sum.cases:
                st.markdown("#### 📋 Agent Case Registry")
                df_cases = pd.DataFrame(ag_sum.cases)
                show_c_cols = ["case_id", "ledger_id", "bank_id", "state", "status", "exception_type", "score"]
                exist_c_cols = [c for c in show_c_cols if c in df_cases.columns]
                st.dataframe(df_cases[exist_c_cols], use_container_width=True, hide_index=True)
        else:
            st.info("Click **'Run Agent Workflow'** above to view the case intelligence and audit trail.")

    with tab_matched:
        df_m = results[results["status"] == "MATCHED"]
        st.markdown(f"**{len(df_m)} Confirmed Matches**")
        st.dataframe(df_m[cols_exist], use_container_width=True, hide_index=True)

    with tab_review:
        df_r = results[results["status"] == "REVIEW"]
        st.markdown(f"**{len(df_r)} Ambiguous Transactions Requiring Review**")
        st.dataframe(df_r[cols_exist], use_container_width=True, hide_index=True)

    with tab_unmatched:
        df_u = results[results["status"] == "UNMATCHED"]
        st.markdown(f"**{len(df_u)} Unmatched Records**")
        st.dataframe(df_u[cols_exist], use_container_width=True, hide_index=True)

    with tab_eval:
        if eval_m:
            st.json(eval_m)
        else:
            if current_source == "uploaded":
                st.info("Benchmark evaluation is not available for uploaded data. Switch to **Benchmark mode** with sample data to see accuracy metrics.")
            else:
                st.info("Select **Benchmark** mode in the sidebar and re-run to evaluate against ground truth.")

    csv_data = results.to_csv(index=False).encode("utf-8")
    st.download_button(
        label="📥 Download Reconciliation Results (CSV)",
        data=csv_data,
        file_name="reconciliation_results.csv",
        mime="text/csv",
        use_container_width=True,
    )

