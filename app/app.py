"""Streamlit Financial Reconciliation Dashboard (Thin UI Wrapper)."""

import os
import io
import pandas as pd
import streamlit as st

try:
    from src.config import ReconciliationConfig, CONFIG
    from src.reconciliation import reconcile
    from src.evaluation import evaluate_reconciliation
except ModuleNotFoundError:
    import sys
    sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
    from src.config import ReconciliationConfig, CONFIG
    from src.reconciliation import reconcile
    from src.evaluation import evaluate_reconciliation

# -----------------------------------------------------------------------------
# 1. Page Configuration & Aesthetic Styling
# -----------------------------------------------------------------------------

st.set_page_config(
    page_title="AI Financial Reconciliation Engine",
    page_icon="⚖️",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    .main-header { font-size: 2.2rem; font-weight: 700; color: #1E293B; margin-bottom: 0.2rem; }
    .sub-header { font-size: 1.0rem; color: #64748B; margin-bottom: 1.5rem; }
    .stMetric { background-color: #F8FAFC; border-radius: 8px; padding: 12px; border: 1px solid #E2E8F0; }
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

user_config = ReconciliationConfig(
    AMOUNT_TOLERANCE=amt_tol,
    DATE_WINDOW_DAYS=date_win,
    HIGH_CONFIDENCE_THRESHOLD=high_thresh,
    REVIEW_THRESHOLD=review_thresh,
    ENABLE_AI_ASSIST=enable_ai,
)

# -----------------------------------------------------------------------------
# 3. Main Header & File Uploaders
# -----------------------------------------------------------------------------

st.markdown('<div class="main-header">AI Financial Reconciliation Engine</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-header">Multi-Tier Deterministic & Bounded Groq AI Matching Engine</div>', unsafe_allow_html=True)

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
    except Exception as err:
        st.error(f"Error reading uploaded CSV/XLSX files: {err}")
elif use_sample or (os.path.exists("data/ledger.csv") and os.path.exists("data/bank_statement.csv") and not ledger_file and not bank_file):
    if os.path.exists("data/ledger.csv") and os.path.exists("data/bank_statement.csv"):
        df_ledger = pd.read_csv("data/ledger.csv")
        df_bank = pd.read_csv("data/bank_statement.csv")
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

            # Run evaluation if answer key exists
            if os.path.exists("data/answer_key.csv"):
                try:
                    eval_metrics = evaluate_reconciliation("data")
                    st.session_state["eval_metrics"] = eval_metrics
                except Exception as eval_err:
                    st.warning(f"Ground truth evaluation notice: {eval_err}")

if "reconciled_results" in st.session_state:
    results = st.session_state["reconciled_results"]
    eval_m = st.session_state.get("eval_metrics", {})

    total_rows = len(results)
    matched_cnt = len(results[results["status"] == "MATCHED"])
    review_cnt = len(results[results["status"] == "REVIEW"])
    unmatched_cnt = len(results[results["status"] == "UNMATCHED"])
    ai_calls_cnt = len(results[results["decision_source"] == "groq"]) if "decision_source" in results.columns else 0
    fp_cnt = eval_m.get("false_positives", 0)

    st.markdown("### 📊 Reconciliation Performance Summary")
    kpi1, kpi2, kpi3, kpi4, kpi5, kpi6 = st.columns(6)
    kpi1.metric("Total Records", total_rows)
    kpi2.metric("Matched", matched_cnt, f"{matched_cnt/total_rows*100:.1f}%")
    kpi3.metric("Review Required", review_cnt, f"{review_cnt/total_rows*100:.1f}%")
    kpi4.metric("Unmatched", unmatched_cnt, f"{unmatched_cnt/total_rows*100:.1f}%")
    kpi5.metric("AI-Assisted Decisions", ai_calls_cnt, "REVIEW Pool Only")
    kpi6.metric("False Positives", fp_cnt, "0.0% Risk Target")

    if eval_m:
        st.caption(f"**Ground Truth Metrics** | Precision: **{eval_m.get('precision', 0):.4f}** | Recall: **{eval_m.get('recall', 0):.4f}** | F1 Score: **{eval_m.get('f1_score', 0):.4f}**")

    # -------------------------------------------------------------------------
    # 6. Detailed Results Tabs & CSV Download
    # -------------------------------------------------------------------------

    tab_matched, tab_review, tab_unmatched, tab_eval = st.tabs(["✅ Matched Records", "⚠️ Review Required", "❌ Unmatched Records", "🎯 Benchmark Evaluation"])

    cols_to_show = ["ledger_id", "bank_id", "status", "matching_rule", "score", "reason", "decision_source", "model_used"]
    cols_exist = [c for c in cols_to_show if c in results.columns]

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
            st.info("No ground truth answer key found in data/ to evaluate accuracy.")

    csv_data = results.to_csv(index=False).encode("utf-8")
    st.download_button(
        label="📥 Download Reconciliation Results (CSV)",
        data=csv_data,
        file_name="reconciliation_results.csv",
        mime="text/csv",
        use_container_width=True,
    )
