"""FastAPI REST API for LedgerLens Financial Reconciliation Core & Observability (Phase 3)."""

import os
import sys
from typing import Optional, Dict, Any, List
import pandas as pd
from fastapi import FastAPI, UploadFile, File, Form, Query, HTTPException
from fastapi.responses import JSONResponse

# Ensure root dir is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.config import CONFIG, ReconciliationConfig
from src.data_validation import validate_ledger_schema, validate_bank_schema, validate_custom_data_paths
from src.reconciliation import reconcile

app = FastAPI(
    title="LedgerLens API",
    description="Financial Reconciliation Engine with Bounded Groq AI & Observability Traces",
    version="1.0.0",
)


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
    except Exception:
        # Fallback to CSV if openpyxl excel writer runs into file lock
        target_path = os.path.join(custom_dir, target_filename.replace(".xlsx", ".csv"))
        df.to_csv(target_path, index=False)

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

    status_counts = df_results["status"].value_counts().to_dict()
    sources = df_results["decision_source"].value_counts().to_dict()

    response_data: Dict[str, Any] = {
        "status": "success",
        "data_source": data_source,
        "total_records": len(df_results),
        "summary": {
            "matched": status_counts.get("MATCHED", 0),
            "review": status_counts.get("REVIEW", 0),
            "unmatched": status_counts.get("UNMATCHED", 0),
            "decision_sources": sources,
        },
    }

    if debug_mode:
        traces = []
        for idx, row in df_results.iterrows():
            traces.append({
                "ledger_id": row.get("ledger_id", ""),
                "bank_id": row.get("bank_id", ""),
                "status": row.get("status", ""),
                "matching_rule": row.get("matching_rule", ""),
                "score": row.get("score", 0.0),
                "reason": row.get("reason", ""),
                "decision_source": row.get("decision_source", "deterministic"),
                "ai_invoked": str(row.get("decision_source", "")).lower() == "groq",
                "ai_result": {
                    "model_used": row.get("model_used", "none"),
                    "ai_reason": row.get("ai_reason", ""),
                    "original_score": row.get("original_score", 0.0),
                },
                "final_safety_validation": True,
                "candidate_count": row.get("candidate_count", 0),
                "candidate_rank": row.get("candidate_rank", 1),
                "amount_difference": row.get("amount_difference", 0.0),
                "date_difference": row.get("date_difference", 0),
            })
        response_data["traces"] = traces

    return response_data
