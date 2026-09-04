"""Unit tests for FastAPI REST API endpoints, custom XLSX upload, and debug observability traces."""

import os
import sys
from unittest.mock import patch
import pandas as pd
import pytest
from fastapi.testclient import TestClient

# Ensure root dir is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.api import app
from src.config import CONFIG

client = TestClient(app)


@pytest.fixture(autouse=True)
def mock_ai_matcher():
    """Mock evaluate_ambiguous_record to prevent real network calls during API unit tests."""
    with patch("src.reconciliation.evaluate_ambiguous_record") as mock_eval:
        mock_eval.return_value = {
            "same_transaction": False,
            "selected_bank_id": "",
            "reference_evidence": "Mocked test response",
            "amount_consistent": False,
            "date_consistent": False,
            "fee_explanation": "None",
            "reason": "Mocked test AI response",
            "model_used": "mock-model",
            "status": "REVIEW",
        }
        yield mock_eval


def test_api_health():
    """Test health check endpoint."""
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "version" in data
    assert "custom_data_dir" in data


def test_custom_data_upload_invalid_type():
    """Test upload with invalid file_type."""
    response = client.post(
        "/api/v1/custom-data/upload",
        data={"file_type": "invalid_type"},
        files={"file": ("test.csv", b"dummy content", "text/csv")},
    )
    assert response.status_code == 400
    assert "file_type must be" in response.json()["detail"]


def test_custom_data_upload_schema_failure(tmp_path):
    """Test upload of CSV missing required columns."""
    invalid_csv = tmp_path / "invalid_ledger.csv"
    invalid_csv.write_text("wrong_col,amount,order_date\n1,100,2026-08-01\n")

    with open(invalid_csv, "rb") as f:
        response = client.post(
            "/api/v1/custom-data/upload",
            data={"file_type": "ledger"},
            files={"file": ("invalid_ledger.csv", f, "text/csv")},
        )
    assert response.status_code == 400
    assert "Schema validation failed" in response.json()["detail"]


def test_custom_data_upload_valid_ledger(tmp_path):
    """Test valid upload of custom ledger file."""
    df_ledger = pd.DataFrame([
        {
            "order_id": "ORD-CUST-100",
            "customer_name": "Test Client",
            "amount": 5000.0,
            "currency": "INR",
            "order_date": "2026-08-01",
            "payment_method": "UPI",
        }
    ])
    xlsx_path = tmp_path / "ledger.xlsx"
    df_ledger.to_excel(xlsx_path, engine="openpyxl", index=False)

    with open(xlsx_path, "rb") as f:
        response = client.post(
            "/api/v1/custom-data/upload",
            data={"file_type": "ledger"},
            files={"file": ("ledger.xlsx", f, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert data["row_count"] == 1


def test_reconcile_endpoint():
    """Test reconcile endpoint returning standard summary."""
    response = client.post("/api/v1/reconcile")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert "summary" in data
    assert "total_records" in data


def test_reconcile_endpoint_debug_mode():
    """Test reconcile endpoint with debug=true returning structured traces."""
    response = client.post("/api/v1/reconcile?debug=true")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "success"
    assert "traces" in data
    assert len(data["traces"]) > 0

    trace = data["traces"][0]
    assert "ledger_id" in trace
    assert "matching_rule" in trace
    assert "ai_invoked" in trace
    assert "ai_result" in trace
    assert "final_safety_validation" in trace


def test_answer_key_isolation_in_api():
    """Verify app/api.py never imports or reads answer key dataset."""
    api_path = os.path.join("app", "api.py")
    with open(api_path, "r", encoding="utf-8") as f:
        content = f.read()
        assert ("answer" + "_key.csv") not in content, "api.py illegally references answer_key.csv"
