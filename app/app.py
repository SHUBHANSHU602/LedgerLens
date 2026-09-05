import os
import sys
import io
import importlib
import pandas as pd
import streamlit as st

# Ensure repository root is always in sys.path
ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

import src.config
importlib.reload(src.config)

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

os.environ["GROQ_MAX_CALLS_PER_MINUTE"] = str(calls_per_min)
try:
    from src.ai_matcher import get_rate_limiter
    get_rate_limiter().update_limit(int(calls_per_min))
except Exception:
    pass

st.sidebar.markdown("---")
st.sidebar.markdown("**Mode**")
run_mode = st.sidebar.radio(
    "Evaluation Mode",
    ["Standard (Live Data)", "Benchmark (Ground Truth)"],
    index=0,
    help="Standard Mode reconciles uploaded or sample data. Benchmark Mode evaluates against canonical ground-truth data with Precision, Recall, F1, and confusion matrix.",
)
is_benchmark_mode = run_mode.startswith("Benchmark")

# Build user configuration safely to prevent unexpected keyword argument TypeError
config_kwargs = {
    "AMOUNT_TOLERANCE": amt_tol,
    "DATE_WINDOW_DAYS": date_win,
    "HIGH_CONFIDENCE_THRESHOLD": high_thresh,
    "REVIEW_THRESHOLD": review_thresh,
    "ENABLE_AI_ASSIST": enable_ai,
}
dataclass_fields = getattr(ReconciliationConfig, "__dataclass_fields__", {})
if "GROQ_MAX_CALLS_PER_MINUTE" in dataclass_fields:
    config_kwargs["GROQ_MAX_CALLS_PER_MINUTE"] = int(calls_per_min)

user_config = ReconciliationConfig(**config_kwargs)

sample_ledger_path = os.path.join(ROOT_DIR, "data", "ledger.csv")
sample_bank_path = os.path.join(ROOT_DIR, "data", "bank_statement.csv")
sample_answer_key_path = os.path.join(ROOT_DIR, "data", "answer_key.csv")

# -----------------------------------------------------------------------------
# 3. Session State Management & Mode-Toggle Handling
# -----------------------------------------------------------------------------

if "active_mode" not in st.session_state:
    st.session_state["active_mode"] = run_mode
    st.session_state["uploader_key"] = 0

# Reactive Mode-Switching: immediately clears stale results and prepares the target mode environment
if st.session_state["active_mode"] != run_mode:
    st.session_state["active_mode"] = run_mode
    st.session_state.pop("reconciled_results", None)
    st.session_state.pop("eval_metrics", None)
    st.session_state.pop("agent_summary", None)
    st.session_state["uploader_key"] = st.session_state.get("uploader_key", 0) + 1

    if is_benchmark_mode:
        # Automatically load canonical benchmark data
        if os.path.exists(sample_ledger_path) and os.path.exists(sample_bank_path):
            st.session_state["df_ledger"] = pd.read_csv(sample_ledger_path)
            st.session_state["df_bank"] = pd.read_csv(sample_bank_path)
            st.session_state["data_source"] = "benchmark"
            st.session_state["data_source_label"] = "Canonical Benchmark Dataset (data/)"
        else:
            st.session_state.pop("df_ledger", None)
            st.session_state.pop("df_bank", None)
            st.session_state.pop("data_source", None)
            st.session_state.pop("data_source_label", None)
    else:
        # Switch back to clean Standard mode
        st.session_state.pop("df_ledger", None)
        st.session_state.pop("df_bank", None)
        st.session_state.pop("data_source", None)
        st.session_state.pop("data_source_label", None)
        st.session_state.pop("uploaded_filenames", None)

    st.rerun()

# -----------------------------------------------------------------------------
# 4. Main Header & Data Input Controls
# -----------------------------------------------------------------------------

st.markdown('<div class="main-header">LedgerLens — AI Finance Controller</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-header">Deterministic + Bounded AI Reconciliation · "What broke at 2 AM?"</div>', unsafe_allow_html=True)

if is_benchmark_mode:
    st.markdown(
        """
        <div style="padding: 14px 18px; border-radius: 10px; background: rgba(20, 184, 166, 0.12); border: 1px solid rgba(20, 184, 166, 0.35); margin-bottom: 18px;">
            <div style="font-weight: 700; font-size: 1.12rem; color: #14B8A6; margin-bottom: 4px;">🎯 Benchmark Mode Active: Ground-Truth Evaluation</div>
            <div style="font-size: 0.95rem; opacity: 0.9;">
                Reconciliation is benchmarked against canonical datasets (<code>data/ledger.csv</code> and <code>data/bank_statement.csv</code>)
                and evaluated against <code>data/answer_key.csv</code> to measure Precision, Recall, F1-Score, and Confusion Matrix across 225 edge-case scenarios.
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    col_bm1, col_bm2 = st.columns([2, 4])
    with col_bm1:
        if st.button("🔄 Reload Benchmark Dataset", use_container_width=True, help="Reload fresh copies of canonical benchmark data"):
            if os.path.exists(sample_ledger_path) and os.path.exists(sample_bank_path):
                st.session_state["df_ledger"] = pd.read_csv(sample_ledger_path)
                st.session_state["df_bank"] = pd.read_csv(sample_bank_path)
                st.session_state["data_source"] = "benchmark"
                st.session_state["data_source_label"] = "Canonical Benchmark Dataset (data/)"
                st.session_state.pop("reconciled_results", None)
                st.session_state.pop("eval_metrics", None)
                st.session_state.pop("agent_summary", None)
                st.rerun()

    # Ensure benchmark data is loaded if not already in session state
    if "df_ledger" not in st.session_state or "df_bank" not in st.session_state:
        if os.path.exists(sample_ledger_path) and os.path.exists(sample_bank_path):
            st.session_state["df_ledger"] = pd.read_csv(sample_ledger_path)
            st.session_state["df_bank"] = pd.read_csv(sample_bank_path)
            st.session_state["data_source"] = "benchmark"
            st.session_state["data_source_label"] = "Canonical Benchmark Dataset (data/)"

else:
    # Standard Mode: File uploaders + Functional Sample Data loading + Reset buttons
    u_key = st.session_state.get("uploader_key", 0)
    col_u1, col_u2 = st.columns(2)
    with col_u1:
        ledger_file = st.file_uploader(
            "Upload Internal Ledger (CSV or XLSX)",
            type=["csv", "xlsx"],
            key=f"ledger_uploader_{u_key}",
        )
    with col_u2:
        bank_file = st.file_uploader(
            "Upload Bank Statement (CSV or XLSX)",
            type=["csv", "xlsx"],
            key=f"bank_uploader_{u_key}",
        )

    # Handle file uploads
    if ledger_file and bank_file:
        current_pair = (ledger_file.name, bank_file.name)
        if st.session_state.get("uploaded_filenames") != current_pair:
            try:
                df_l = pd.read_excel(ledger_file, engine="openpyxl") if ledger_file.name.endswith(".xlsx") else pd.read_csv(ledger_file)
                df_b = pd.read_excel(bank_file, engine="openpyxl") if bank_file.name.endswith(".xlsx") else pd.read_csv(bank_file)
                st.session_state["df_ledger"] = df_l
                st.session_state["df_bank"] = df_b
                st.session_state["data_source"] = "uploaded"
                st.session_state["data_source_label"] = f"Uploaded ({ledger_file.name}, {bank_file.name})"
                st.session_state["uploaded_filenames"] = current_pair
                st.session_state.pop("reconciled_results", None)
                st.session_state.pop("eval_metrics", None)
                st.session_state.pop("agent_summary", None)
                st.rerun()
            except Exception as err:
                st.error(f"Error parsing uploaded files: {err}")

    col_btn1, col_btn2, col_spacer = st.columns([1.8, 1.8, 3.4])
    with col_btn1:
        if st.button("📁 Load Sample Datasets", use_container_width=True, help="Load sample datasets from data/ for quick exploration"):
            if os.path.exists(sample_ledger_path) and os.path.exists(sample_bank_path):
                st.session_state["df_ledger"] = pd.read_csv(sample_ledger_path)
                st.session_state["df_bank"] = pd.read_csv(sample_bank_path)
                st.session_state["data_source"] = "sample"
                st.session_state["data_source_label"] = "Sample Datasets (data/ledger.csv & data/bank_statement.csv)"
                st.session_state.pop("uploaded_filenames", None)
                st.session_state.pop("reconciled_results", None)
                st.session_state.pop("eval_metrics", None)
                st.session_state.pop("agent_summary", None)
                st.rerun()
            else:
                st.error("Sample files data/ledger.csv or data/bank_statement.csv not found.")
    with col_btn2:
        if st.button("🔄 Reset / Clear Active Data", use_container_width=True, help="Clear loaded datasets, results, and reset upload fields"):
            st.session_state.pop("df_ledger", None)
            st.session_state.pop("df_bank", None)
            st.session_state.pop("data_source", None)
            st.session_state.pop("data_source_label", None)
            st.session_state.pop("uploaded_filenames", None)
            st.session_state.pop("reconciled_results", None)
            st.session_state.pop("eval_metrics", None)
            st.session_state.pop("agent_summary", None)
            st.session_state["uploader_key"] = st.session_state.get("uploader_key", 0) + 1
            st.rerun()

# -----------------------------------------------------------------------------
# 5. Active Dataset Status & Preview Section
# -----------------------------------------------------------------------------

df_ledger = st.session_state.get("df_ledger")
df_bank = st.session_state.get("df_bank")
data_label = st.session_state.get("data_source_label", "")

if df_ledger is not None and df_bank is not None:
    st.success(f"✅ **Active Data Ready:** {data_label} · **Ledger:** {len(df_ledger):,} records · **Bank Statement:** {len(df_bank):,} records")
    with st.expander("👁️ View Active Dataset Previews (First 5 Rows)", expanded=False):
        c_prev1, c_prev2 = st.columns(2)
        with c_prev1:
            st.markdown(f"**Internal Ledger (`{len(df_ledger):,}` rows)**")
            st.dataframe(df_ledger.head(5), use_container_width=True, hide_index=True)
        with c_prev2:
            st.markdown(f"**Bank Statement (`{len(df_bank):,}` rows)**")
            st.dataframe(df_bank.head(5), use_container_width=True, hide_index=True)
else:
    if is_benchmark_mode:
        st.warning("⚠️ Benchmark datasets not found in `data/`. Please ensure `data/ledger.csv` and `data/bank_statement.csv` are present.")
    else:
        st.info("ℹ️ **No dataset active.** Upload your Ledger and Bank Statement above, or click **'📁 Load Sample Datasets'** to load sample data.")


def validate_datasets(df_l: pd.DataFrame, df_b: pd.DataFrame) -> bool:
    """Validate non-empty datasets and required schema columns."""
    if df_l is None or df_b is None:
        return False
    if df_l.empty or df_b.empty:
        st.error("Validation Error: One or both datasets are empty.")
        return False

    missing_l = [c for c in ["order_id", "amount", "order_date"] if c not in df_l.columns]
    missing_b = [c for c in ["utr_reference", "credited_amount", "value_date"] if c not in df_b.columns]

    if missing_l:
        st.error(f"Validation Error: Ledger dataset missing required columns: {missing_l}")
        return False
    if missing_b:
        st.error(f"Validation Error: Bank statement dataset missing required columns: {missing_b}")
        return False

    return True

# -----------------------------------------------------------------------------
# 6. Reconciliation Execution & KPI Dashboard
# -----------------------------------------------------------------------------

if validate_datasets(df_ledger, df_bank):
    button_label = "🎯 Run Reconciliation & Benchmark Evaluation" if is_benchmark_mode else "🚀 Run Reconciliation Engine"
    if st.button(button_label, type="primary", use_container_width=True):
        with st.spinner("Executing Multi-Tier Deterministic & AI Reconciliation..."):
            results = reconcile(df_ledger, df_bank, config=user_config)
            st.session_state["reconciled_results"] = results
            st.session_state["data_source"] = st.session_state.get("data_source", "uploaded")

            # In Benchmark mode, execute full ground-truth evaluation
            if is_benchmark_mode and os.path.exists(sample_answer_key_path):
                try:
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

        st.rerun()

if "reconciled_results" in st.session_state:
    results = st.session_state["reconciled_results"]
    eval_m = st.session_state.get("eval_metrics", {})
    current_source = st.session_state.get("data_source", "unknown")

    total_rows = len(results)
    matched_cnt = len(results[results["status"] == "MATCHED"])
    review_cnt = len(results[results["status"] == "REVIEW"])
    unmatched_cnt = len(results[results["status"] == "UNMATCHED"])
    ai_calls_cnt = len(results[results["decision_source"] == "groq"]) if "decision_source" in results.columns else 0

    st.markdown("---")
    st.markdown("### 📊 Reconciliation Performance Summary")

    if is_benchmark_mode:
        st.caption("🎯 **Mode: Benchmark (Ground Truth)** — Reconciled and evaluated against canonical answer key")
    elif current_source == "uploaded":
        st.caption("📎 **Mode: Standard (Uploaded Live Data)** — Reconciled with multi-tier engine")
    else:
        st.caption("📁 **Mode: Standard (Sample Data)** — Reconciled with multi-tier engine")

    kpi1, kpi2, kpi3, kpi4, kpi5 = st.columns(5)
    kpi1.metric("Total Records", total_rows)
    kpi2.metric("Matched", matched_cnt, f"{matched_cnt/total_rows*100:.1f}%" if total_rows > 0 else "0%")
    kpi3.metric("Review Required", review_cnt, f"{review_cnt/total_rows*100:.1f}%" if total_rows > 0 else "0%")
    kpi4.metric("Unmatched", unmatched_cnt, f"{unmatched_cnt/total_rows*100:.1f}%" if total_rows > 0 else "0%")
    kpi5.metric("AI-Assisted", ai_calls_cnt, "REVIEW Pool Only")

    # Display ground truth metrics when in benchmark mode
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
    # 7. Detailed Results Tabs & Exception-First View
    # -------------------------------------------------------------------------

    tab_titles = (
        ["🎯 Benchmark Evaluation", "🔍 Exception Summary", "🤖 Agent Activity & Trace", "✅ Matched", "⚠️ Review Required", "❌ Unmatched"]
        if is_benchmark_mode
        else ["🔍 Exception Summary", "🤖 Agent Activity & Trace", "✅ Matched", "⚠️ Review Required", "❌ Unmatched", "🎯 Benchmark Evaluation"]
    )
    all_tabs = st.tabs(tab_titles)

    if is_benchmark_mode:
        tab_eval, tab_exceptions, tab_agent, tab_matched, tab_review, tab_unmatched = all_tabs
    else:
        tab_exceptions, tab_agent, tab_matched, tab_review, tab_unmatched, tab_eval = all_tabs

    cols_to_show = ["ledger_id", "bank_id", "status", "matching_rule", "score", "reason", "decision_source", "model_used"]
    cols_exist = [c for c in cols_to_show if c in results.columns]

    with tab_eval:
        st.markdown("### 🎯 Ground Truth Benchmark Evaluation")
        if eval_m:
            st.markdown(f"**Benchmark Summary:** `{eval_m.get('headline', '')}`")

            col_ev1, col_ev2, col_ev3, col_ev4 = st.columns(4)
            col_ev1.metric("Pair Precision", f"{eval_m.get('pair_precision', 0):.4f}", "TP / (TP + FP)")
            col_ev2.metric("Pair Recall", f"{eval_m.get('pair_recall', 0):.4f}", "TP / (TP + FN)")
            col_ev3.metric("F1 Score", f"{eval_m.get('f1_score', 0):.4f}", "Harmonic Mean")
            col_ev4.metric("Auto-Res. Precision", f"{eval_m.get('auto_resolution_precision', 0):.4f}", "Deterministic accuracy")

            st.markdown("#### ⚖️ Confusion Matrix")
            cm = eval_m.get("confusion_matrix", {})
            tp_val, fp_val = cm.get("TP", 0), cm.get("FP", 0)
            fn_val, tn_val = cm.get("FN", 0), cm.get("TN", 0)

            cm_html = f"""
            <table style="width: 100%; border-collapse: collapse; margin: 10px 0 20px 0; text-align: center;">
              <thead>
                <tr style="background: rgba(128,128,128,0.12); font-weight: 600;">
                  <th style="padding: 10px; border: 1px solid rgba(128,128,128,0.25); text-align: left;">Ground Truth \\ Engine Decision</th>
                  <th style="padding: 10px; border: 1px solid rgba(128,128,128,0.25); color: #10B981;">MATCHED (Predicted)</th>
                  <th style="padding: 10px; border: 1px solid rgba(128,128,128,0.25); color: #EF4444;">NON-MATCHED (Predicted)</th>
                </tr>
              </thead>
              <tbody>
                <tr>
                  <td style="padding: 10px; border: 1px solid rgba(128,128,128,0.25); font-weight: 600; text-align: left;">MATCHED (Actual)</td>
                  <td style="padding: 10px; border: 1px solid rgba(128,128,128,0.25); background: rgba(16,185,129,0.12); font-weight: 700; font-size: 1.1rem; color: #10B981;">TP: {tp_val}</td>
                  <td style="padding: 10px; border: 1px solid rgba(128,128,128,0.25); background: rgba(239,68,68,0.12); font-weight: 700; font-size: 1.1rem; color: #EF4444;">FN: {fn_val}</td>
                </tr>
                <tr>
                  <td style="padding: 10px; border: 1px solid rgba(128,128,128,0.25); font-weight: 600; text-align: left;">NON-MATCHED (Actual)</td>
                  <td style="padding: 10px; border: 1px solid rgba(128,128,128,0.25); background: rgba(239,68,68,0.12); font-weight: 700; font-size: 1.1rem; color: #EF4444;">FP: {fp_val}</td>
                  <td style="padding: 10px; border: 1px solid rgba(128,128,128,0.25); background: rgba(16,185,129,0.12); font-weight: 700; font-size: 1.1rem; color: #10B981;">TN: {tn_val}</td>
                </tr>
              </tbody>
            </table>
            """
            st.markdown(cm_html, unsafe_allow_html=True)

            rates = eval_m.get("rates", {})
            st.markdown("#### 📈 Operational Coverage & Safety Metrics")
            r1, r2, r3, r4 = st.columns(4)
            r1.metric("Automated Coverage", f"{rates.get('automated_coverage', 0)*100:.1f}%")
            r2.metric("Review Rate", f"{rates.get('review_rate', 0)*100:.1f}%")
            r3.metric("Deterministic Match Rate", f"{rates.get('deterministic_match_rate', 0)*100:.1f}%")
            r4.metric("AI Escalation Rate", f"{rates.get('ai_escalation_rate', 0)*100:.1f}%")

            safety = eval_m.get("safety_checks", {})
            st.caption(f"🔒 **Safety Audits:** One-to-One Conflicts: `{safety.get('duplicate_assignment_conflicts', 0)}` · Invalid AI Selections: `{safety.get('invalid_ai_selections', 0)}`")

            with st.expander("📄 Export Raw Benchmark Metrics JSON"):
                st.json(eval_m)
        else:
            if is_benchmark_mode:
                st.info("Click **'🎯 Run Reconciliation & Benchmark Evaluation'** above to compute ground-truth benchmark metrics.")
            else:
                st.info("Benchmark evaluation is available in **Benchmark (Ground Truth)** mode. Switch modes in the sidebar to benchmark against the canonical answer key.")

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
                st.rerun()

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

    csv_data = results.to_csv(index=False).encode("utf-8")
    st.download_button(
        label="📥 Download Reconciliation Results (CSV)",
        data=csv_data,
        file_name="reconciliation_results.csv",
        mime="text/csv",
        use_container_width=True,
    )


