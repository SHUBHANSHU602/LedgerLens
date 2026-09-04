"""Bounded Groq AI Assistance module for financial reconciliation ambiguity resolution."""

import os
import re
import json
from typing import Dict, Any, List
import pandas as pd
from dotenv import load_dotenv

try:
    from src.config import ReconciliationConfig, CONFIG
except ModuleNotFoundError:
    from config import ReconciliationConfig, CONFIG

load_dotenv()
_AI_CACHE: Dict[str, Dict[str, Any]] = {}


def parse_json_from_llm(text: str) -> Dict[str, Any]:
    """Safely extract JSON object from LLM completion string."""
    try:
        return json.loads(text)
    except Exception:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        raise


def evaluate_ambiguous_record(
    l_row: pd.Series,
    top_candidates: List[Any],
    config: ReconciliationConfig = CONFIG,
) -> Dict[str, Any]:
    """Evaluate an ambiguous reconciliation record using Groq LLM assistance."""
    l_id = str(l_row.get("order_id", ""))
    candidate_ids = "-".join([str(c[1]) for c in top_candidates])
    cache_key = f"{l_id}_{candidate_ids}"

    if cache_key in _AI_CACHE:
        return _AI_CACHE[cache_key]

    api_key = os.getenv("GROQ_API_KEY", "").strip()
    if not api_key:
        return {
            "same_transaction": False, "selected_bank_id": "", "reference_evidence": "API key missing",
            "amount_consistent": False, "date_consistent": False, "fee_explanation": "None",
            "reason": "GROQ_API_KEY not configured. Defaulting to REVIEW.", "model_used": "none", "status": "REVIEW",
        }

    try:
        from groq import Groq
        client = Groq(api_key=api_key)
    except Exception as e:
        return {
            "same_transaction": False, "selected_bank_id": "", "reference_evidence": "Client init error",
            "amount_consistent": False, "date_consistent": False, "fee_explanation": "None",
            "reason": f"Failed to initialize Groq client: {str(e)}", "model_used": "none", "status": "REVIEW",
        }

    ledger_summary = {
        "order_id": l_id, "customer_name": l_row.get("customer_name", ""),
        "amount": float(l_row.get("amount", 0.0)), "currency": l_row.get("currency", "INR"),
        "order_date": str(l_row.get("order_date", "")), "payment_method": l_row.get("payment_method", ""),
    }

    bank_candidates = []
    for score, b_id, b_row, breakdown in top_candidates[:3]:
        bank_candidates.append({
            "utr_reference": b_id, "narration_text": b_row.get("narration_text", ""),
            "credited_amount": float(b_row.get("credited_amount", 0.0)), "currency": b_row.get("currency", "INR"),
            "value_date": str(b_row.get("value_date", "")), "deduction_fee": float(b_row.get("deduction_fee", 0.0)),
            "deterministic_score": score, "score_breakdown": breakdown,
        })

    prompt_messages = [
        {"role": "system", "content": "You are a financial reconciliation assistant. Respond ONLY with raw JSON: {\"same_transaction\": boolean, \"selected_bank_id\": string, \"reference_evidence\": string, \"amount_consistent\": boolean, \"date_consistent\": boolean, \"fee_explanation\": string, \"reason\": string}"},
        {"role": "user", "content": json.dumps({"ledger": ledger_summary, "bank_candidates": bank_candidates}, indent=2)},
    ]

    try:
        response = client.chat.completions.create(
            model=config.GROQ_MODEL, messages=prompt_messages, timeout=10.0,
        )
        content = response.choices[0].message.content
        data = parse_json_from_llm(content)
        same_tx = bool(data.get("same_transaction", False))
        result = {
            "same_transaction": same_tx,
            "selected_bank_id": str(data.get("selected_bank_id", top_candidates[0][1] if top_candidates else "")),
            "reference_evidence": str(data.get("reference_evidence", "")),
            "amount_consistent": bool(data.get("amount_consistent", False)),
            "date_consistent": bool(data.get("date_consistent", False)),
            "fee_explanation": str(data.get("fee_explanation", "")),
            "reason": str(data.get("reason", "AI analyzed transaction compatibility")),
            "model_used": config.GROQ_MODEL,
            "status": "MATCHED" if same_tx else "REVIEW",
        }
    except Exception as exc:
        result = {
            "same_transaction": False, "selected_bank_id": "", "reference_evidence": "API error",
            "amount_consistent": False, "date_consistent": False, "fee_explanation": "None",
            "reason": f"AI error: {str(exc)}. Safe fallback to REVIEW.",
            "model_used": config.GROQ_MODEL, "status": "REVIEW",
        }

    _AI_CACHE[cache_key] = result
    return result
