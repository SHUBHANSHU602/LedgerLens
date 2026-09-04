"""FastAPI REST API for LedgerLens Financial Reconciliation Core & Observability."""

import os
import sys
import uuid
from typing import Optional, Dict, Any, List
import pandas as pd
from fastapi import FastAPI, UploadFile, File, Form, Query, HTTPException

# Ensure root dir is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.config import CONFIG, ReconciliationConfig
from src.data_validation import validate_ledger_schema, validate_bank_schema, validate_custom_data_paths
from src.reconciliation import reconcile
from src.services.finance_controller import process_batch
from src.agent import ReconciliationAgent, ActionType

app = FastAPI(
    title="LedgerLens API",
    description="Financial Reconciliation Engine with Bounded Groq AI & Observability Traces",
    version="1.0.0",
)

_RUN_CACHE: Dict[str, Dict[str, Any]] = {}


@app.get("/health")
@app.get("/api/v1/health")
def health_check():
    """Health check endpoint for LedgerLens system status."""
    custom_valid, custom_paths = validate_custom_data_paths()
    return {
        "status": "ok",
        "service": "LedgerLens Financial Reconciliation API",
        "version": "1.0.0",
        "custom_data_dir": CONFIG.LEDGERLENS_CUSTOM_DATA_DIR,
        "custom_data_available": custom_valid,
        "custom_paths": custom_paths,
    }


@app.post("/api/v1/custom-data/upload")
async def upload_custom_data(
    file: UploadFile = File(...),
    file_type: str = Form(..., description="Type of dataset: 'ledger' or 'bank'"),
):
    """Upload custom operational ledger or bank statement XLSX file."""
    ft = file_type.strip().lower()
    if ft not in ["ledger", "bank"]:
        raise HTTPException(status_code=400, detail="file_type must be either 'ledger' or 'bank'.")

    filename = file.filename or ""
    if not (filename.endswith(".xlsx") or filename.endswith(".csv")):
        raise HTTPException(status_code=400, detail="Only .xlsx or .csv files are supported for upload.")

    custom_dir = CONFIG.LEDGERLENS_CUSTOM_DATA_DIR
    os.makedirs(custom_dir, exist_ok=True)

    try:
        if filename.endswith(".xlsx"):
            df = pd.read_excel(file.file, engine="openpyxl")
        else:
            df = pd.read_csv(file.file)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to parse uploaded file: {str(e)}")

    if ft == "ledger":
        is_valid, errs = validate_ledger_schema(df)
        target_filename = "ledger.xlsx"
    else:
        is_valid, errs = validate_bank_schema(df)
        target_filename = "bank_statement.xlsx"

    if not is_valid:
        raise HTTPException(status_code=400, detail=f"Schema validation failed: {errs}")

    target_path = os.path.join(custom_dir, target_filename)
    try:
        with pd.ExcelWriter(target_path, engine="openpyxl") as writer:
            df.to_excel(writer, sheet_name="Data", index=False)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to save custom dataset as XLSX: {str(exc)}")

    return {
        "status": "success",
        "file_type": ft,
        "filename": filename,
        "saved_path": target_path,
        "row_count": len(df),
    }


@app.post("/api/v1/reconcile")
def run_reconciliation_endpoint(
    debug: Optional[bool] = Query(None, description="Enable structured reconciliation trace output"),
    use_custom_data: bool = Query(False, description="Use custom XLSX datasets from data/custom/ if available"),
):
    """Execute reconciliation engine and return summary or detailed observability traces."""
    debug_mode = debug if debug is not None else (
        os.getenv("LEDGERLENS_DEBUG_MODE", "").lower() == "true" or CONFIG.LEDGERLENS_DEBUG_MODE
    )

    custom_dir = CONFIG.LEDGERLENS_CUSTOM_DATA_DIR
    ledger_xlsx = os.path.join(custom_dir, "ledger.xlsx")
    bank_xlsx = os.path.join(custom_dir, "bank_statement.xlsx")

    if use_custom_data and os.path.exists(ledger_xlsx) and os.path.exists(bank_xlsx):
        df_ledger = pd.read_excel(ledger_xlsx, engine="openpyxl")
        df_bank = pd.read_excel(bank_xlsx, engine="openpyxl")
        data_source = "custom_xlsx"
    else:
        ledger_csv = os.path.join("data", "ledger.csv")
        bank_csv = os.path.join("data", "bank_statement.csv")
        if not (os.path.exists(ledger_csv) and os.path.exists(bank_csv)):
            raise HTTPException(status_code=404, detail="Default dataset missing. Generate dataset first or upload custom files.")
        df_ledger = pd.read_csv(ledger_csv)
        df_bank = pd.read_csv(bank_csv)
        data_source = "default_benchmark"

    try:
        df_results = reconcile(df_ledger, df_bank)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Reconciliation error: {str(e)}")

    run_id = f"RUN-{uuid.uuid4().hex[:8].upper()}"
    status_counts = df_results["status"].value_counts().to_dict()
    sources = df_results["decision_source"].value_counts().to_dict()

    response_data: Dict[str, Any] = {
        "status": "success",
        "run_id": run_id,
        "data_source": data_source,
        "total_records": len(df_results),
        "matched_count": status_counts.get("MATCHED", 0),
        "review_count": status_counts.get("REVIEW", 0),
        "unmatched_count": status_counts.get("UNMATCHED", 0),
        "summary": {
            "matched": status_counts.get("MATCHED", 0),
            "review": status_counts.get("REVIEW", 0),
            "unmatched": status_counts.get("UNMATCHED", 0),
            "decision_sources": sources,
        },
    }

    traces = []
    for idx, row in df_results.iterrows():
        ai_invoked = (row.get("decision_source", "") == "groq") or bool(row.get("ai_reason", ""))
        ai_reason_text = str(row.get("ai_reason", ""))
        status_val = str(row.get("status", ""))
        matching_rule = str(row.get("matching_rule", ""))
        rule_reason = str(row.get("reason", ""))
        amt_diff = float(row.get("amount_difference", 0.0))

        if not ai_invoked:
            ai_validation_result = "not_invoked"
        elif "VETO" in ai_reason_text or "vetoed" in ai_reason_text.lower():
            ai_validation_result = "vetoed"
        elif status_val == "MATCHED":
            ai_validation_result = "passed"
        else:
            ai_validation_result = "review_suggested"

        if "VETO: AI bank ID" in ai_reason_text or "hallucinated" in ai_reason_text.lower():
            candidate_id_check = "failed_hallucinated_id"
        else:
            candidate_id_check = "passed"

        currency_safety_check = "failed" if (matching_rule == "CURRENCY_MISMATCH" or "Currency mismatch" in rule_reason) else "passed"
        amount_safety_check = "passed" if currency_safety_check == "passed" and amt_diff <= 500.0 else "failed"
        one_to_one_check = "conflict_downgraded" if (matching_rule == "ONE_TO_ONE_CONFLICT" or "One-to-one conflict" in rule_reason) else "passed"

        all_checks_passed = (
            candidate_id_check == "passed" and
            amount_safety_check == "passed" and
            currency_safety_check == "passed" and
            one_to_one_check == "passed"
        )
        hard_safety_checks_summary = "passed" if all_checks_passed else "flagged"

        traces.append({
            "ledger_id": row.get("ledger_id", ""),
            "bank_id": row.get("bank_id", ""),
            "status": status_val,
            "matching_rule": matching_rule,
            "score": row.get("score", 0.0),
            "reason": rule_reason,
            "decision_source": row.get("decision_source", "deterministic"),
            "ai_invoked": ai_invoked,
            "ai_result_summary": ai_reason_text if ai_invoked else "N/A",
            "ai_validation_result": ai_validation_result,
            "hard_safety_checks": hard_safety_checks_summary,
            "candidate_id_check": candidate_id_check,
            "amount_safety_check": amount_safety_check,
            "currency_safety_check": currency_safety_check,
            "amount_check": amount_safety_check,
            "currency_check": currency_safety_check,
            "one_to_one_check": one_to_one_check,
            "final_decision": status_val,
            "candidate_count": row.get("candidate_count", 0),
            "candidate_rank": row.get("candidate_rank", 1),
            "amount_difference": amt_diff,
            "date_difference": row.get("date_difference", 0),
        })

    if debug_mode:
        response_data["traces"] = traces

    # Finance Controller batch processing
    batch = process_batch(df_results, run_id=run_id)
    response_data["batch"] = batch.to_dict()

    _RUN_CACHE[run_id] = response_data
    _RUN_CACHE["latest"] = response_data
    return response_data


@app.get("/api/v1/reconcile/")
@app.get("/api/v1/reconcile/{run_id}")
def get_reconciliation_run(run_id: str = "latest"):
    """Retrieve reconciliation run summary and traces by run_id or 'latest'."""
    if not run_id or run_id in ("latest", ""):
        if "latest" not in _RUN_CACHE:
            raise HTTPException(status_code=404, detail="No reconciliation run found in memory cache. Execute POST /api/v1/reconcile first.")
        return _RUN_CACHE["latest"]

    if run_id not in _RUN_CACHE:
        raise HTTPException(status_code=404, detail=f"Reconciliation run '{run_id}' not found.")
    return _RUN_CACHE[run_id]


# ---------------------------------------------------------------------------
# Bounded Agent Workflow Endpoints
# ---------------------------------------------------------------------------

_ACTIVE_AGENT: Optional[ReconciliationAgent] = None


@app.post("/api/v1/agent/run")
def run_agent_endpoint(
    use_custom_data: bool = Query(False, description="Use custom XLSX datasets if available"),
):
    """Execute bounded ReconciliationAgent pipeline across input datasets."""
    global _ACTIVE_AGENT
    custom_dir = CONFIG.LEDGERLENS_CUSTOM_DATA_DIR
    ledger_xlsx = os.path.join(custom_dir, "ledger.xlsx")
    bank_xlsx = os.path.join(custom_dir, "bank_statement.xlsx")

    if use_custom_data and os.path.exists(ledger_xlsx) and os.path.exists(bank_xlsx):
        df_ledger = pd.read_excel(ledger_xlsx, engine="openpyxl")
        df_bank = pd.read_excel(bank_xlsx, engine="openpyxl")
    else:
        ledger_csv = os.path.join("data", "ledger.csv")
        bank_csv = os.path.join("data", "bank_statement.csv")
        if not (os.path.exists(ledger_csv) and os.path.exists(bank_csv)):
            raise HTTPException(status_code=404, detail="Default dataset missing. Generate dataset first or upload custom files.")
        df_ledger = pd.read_csv(ledger_csv)
        df_bank = pd.read_csv(bank_csv)

    agent = ReconciliationAgent()
    try:
        summary = agent.observe_and_reconcile(df_ledger, df_bank)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Agent pipeline error: {str(e)}")

    _ACTIVE_AGENT = agent
    return summary.to_dict()


@app.get("/api/v1/cases")
def list_cases_endpoint():
    """List all active reconciliation cases and their current states."""
    if _ACTIVE_AGENT is None:
        raise HTTPException(status_code=404, detail="No agent run found in memory. Call POST /api/v1/agent/run first.")
    return {
        "case_count": len(_ACTIVE_AGENT.cases),
        "cases": [c.to_dict() for c in _ACTIVE_AGENT.cases.values()],
    }


@app.get("/api/v1/cases/{case_id}")
def get_case_endpoint(case_id: str):
    """Retrieve single case details, investigation, policy verdict, and audit history."""
    if _ACTIVE_AGENT is None or case_id not in _ACTIVE_AGENT.cases:
        raise HTTPException(status_code=404, detail=f"Case '{case_id}' not found.")
    return _ACTIVE_AGENT.cases[case_id].to_dict()


@app.post("/api/v1/cases/{case_id}/approve")
def approve_case_action_endpoint(case_id: str):
    """Approve pending action for a case and execute action handler + verification loop."""
    if _ACTIVE_AGENT is None or case_id not in _ACTIVE_AGENT.cases:
        raise HTTPException(status_code=404, detail=f"Case '{case_id}' not found.")

    case = _ACTIVE_AGENT.cases[case_id]
    if not case.policy_decision:
        raise HTTPException(status_code=400, detail="Case has no policy decision.")

    action_type = case.policy_decision.action_type
    exec_res, verif_res = _ACTIVE_AGENT.action_service.execute_and_verify(
        case, action_type=action_type
    )
    return {
        "status": "success",
        "case": case.to_dict(),
        "execution": exec_res.to_dict(),
        "verification": verif_res.to_dict(),
    }


@app.get("/api/v1/audit")
def get_audit_trail_endpoint():
    """Retrieve append-only audit trail logs from the active agent run."""
    if _ACTIVE_AGENT is None:
        raise HTTPException(status_code=404, detail="No agent run found in memory. Call POST /api/v1/agent/run first.")

    events = []
    for c in _ACTIVE_AGENT.cases.values():
        for evt in c.audit_history:
            events.append(evt.to_dict())

    # Sort chronologically
    events.sort(key=lambda x: x.get("timestamp", ""))
    return {
        "event_count": len(events),
        "audit_events": events,
    }

