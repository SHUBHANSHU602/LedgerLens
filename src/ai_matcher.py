import os
import re
import json
import time
import threading
from collections import deque
from typing import Dict, Any, List, Optional
import pandas as pd
from dotenv import load_dotenv

try:
    from src.config import ReconciliationConfig, CONFIG
    from src.schemas import AIEvaluationSchema
except ModuleNotFoundError:
    from config import ReconciliationConfig, CONFIG
    from schemas import AIEvaluationSchema

load_dotenv()
_AI_CACHE: Dict[str, Dict[str, Any]] = {}
PROMPT_VERSION = "v2.0"


class GroqRateLimiter:
    """Sliding-window thread-safe rate limiter to strictly cap Groq API calls per minute."""

    def __init__(self, max_calls_per_minute: int = 25):
        self.max_calls_per_minute = max(1, max_calls_per_minute)
        self.timestamps: deque = deque()
        self.lock = threading.Lock()

    def update_limit(self, max_calls_per_minute: int) -> None:
        """Dynamically update the rate limit threshold."""
        with self.lock:
            self.max_calls_per_minute = max(1, max_calls_per_minute)

    def reset(self) -> None:
        """Clear recorded timestamps."""
        with self.lock:
            self.timestamps.clear()

    def acquire(self) -> float:
        """Wait if necessary to ensure calls do not exceed max_calls_per_minute in any 60-second window.

        Returns:
            Number of seconds slept (0.0 if capacity was immediately available).
        """
        with self.lock:
            total_slept = 0.0
            while True:
                now = time.time()
                # Remove timestamps outside the 60-second sliding window
                while self.timestamps and now - self.timestamps[0] >= 60.0:
                    self.timestamps.popleft()

                if len(self.timestamps) < self.max_calls_per_minute:
                    self.timestamps.append(time.time())
                    return total_slept

                # Calculate duration until oldest request exits the window
                oldest = self.timestamps[0]
                wait_time = 60.0 - (now - oldest) + 0.05
                if wait_time > 0:
                    time.sleep(wait_time)
                    total_slept += wait_time


def _parse_rpm(val: Any, default: int = 25) -> int:
    """Safely parse integer rate limit, returning default if invalid or mocked string."""
    try:
        if val is not None and str(val).strip().isdigit():
            return max(1, int(val))
    except Exception:
        pass
    return default


# Global rate limiter instance initialized from env or default config
_RATE_LIMITER = GroqRateLimiter(
    max_calls_per_minute=_parse_rpm(
        os.getenv("GROQ_MAX_CALLS_PER_MINUTE"),
        getattr(CONFIG, "GROQ_MAX_CALLS_PER_MINUTE", 25),
    )
)


def get_rate_limiter() -> GroqRateLimiter:
    """Return the active GroqRateLimiter instance."""
    return _RATE_LIMITER


def clear_ai_cache() -> None:
    """Clear in-memory AI cache and reset rate limiter history."""
    _AI_CACHE.clear()
    _RATE_LIMITER.reset()


def parse_json_from_llm(text: str) -> Dict[str, Any]:
    """Safely extract JSON object from LLM completion string."""
    try:
        return json.loads(text)
    except Exception:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if match:
            return json.loads(match.group(0))
        raise


def coerce_boolean(val: Any) -> bool:
    """Safely coerce boolean strings or integers to boolean."""
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return val != 0
    if isinstance(val, str):
        cleaned = val.strip().lower()
        if cleaned in ("true", "1", "yes", "y"):
            return True
        if cleaned in ("false", "0", "no", "n"):
            return False
    return False


def evaluate_ambiguous_record(
    l_row: pd.Series,
    top_candidates: List[Any],
    config: ReconciliationConfig = CONFIG,
) -> Dict[str, Any]:
    """Evaluate an ambiguous reconciliation record using Groq LLM assistance with Pydantic safety checks."""
    l_id = str(l_row.get("order_id", ""))
    valid_candidate_ids = [str(c[1]) for c in top_candidates if c[1]]
    candidate_ids_str = "-".join(valid_candidate_ids)

    config_hash = f"{config.AMOUNT_TOLERANCE}_{config.DATE_WINDOW_DAYS}_{config.HIGH_CONFIDENCE_THRESHOLD}_{config.REVIEW_THRESHOLD}"
    cache_key = f"{PROMPT_VERSION}_{config.GROQ_MODEL}_{config_hash}_{l_id}_{candidate_ids_str}"

    if cache_key in _AI_CACHE:
        return _AI_CACHE[cache_key]

    api_key = os.getenv("GROQ_API_KEY", "").strip()
    if not api_key:
        return {
            "same_transaction": False,
            "selected_bank_id": "",
            "reference_evidence": "API key missing",
            "amount_consistent": False,
            "date_consistent": False,
            "fee_explanation": "None",
            "reason": "GROQ_API_KEY not configured. Defaulting to REVIEW.",
            "model_used": "none",
            "status": "REVIEW",
        }

    try:
        from groq import Groq
        client = Groq(api_key=api_key)
    except Exception as e:
        return {
            "same_transaction": False,
            "selected_bank_id": "",
            "reference_evidence": "Client init error",
            "amount_consistent": False,
            "date_consistent": False,
            "fee_explanation": "None",
            "reason": f"Failed to initialize Groq client: {str(e)}",
            "model_used": "none",
            "status": "REVIEW",
        }

    ledger_summary = {
        "order_id": l_id,
        "customer_name": l_row.get("customer_name", ""),
        "amount": float(l_row.get("amount", 0.0)),
        "currency": l_row.get("currency", "INR"),
        "order_date": str(l_row.get("order_date", "")),
        "payment_method": l_row.get("payment_method", ""),
    }

    bank_candidates = []
    ai_limit = config.AI_CANDIDATE_LIMIT
    for score, b_id, b_row, breakdown in top_candidates[:ai_limit]:
        bank_candidates.append({
            "utr_reference": b_id,
            "narration_text": b_row.get("narration_text", ""),
            "credited_amount": float(b_row.get("credited_amount", 0.0)),
            "currency": b_row.get("currency", "INR"),
            "value_date": str(b_row.get("value_date", "")),
            "deduction_fee": float(b_row.get("deduction_fee", 0.0)),
            "deterministic_score": score,
            "score_breakdown": breakdown,
        })

    prompt_messages = [
        {
            "role": "system",
            "content": (
                "You are a financial reconciliation assistant. Analyze ledger vs bank candidates. "
                "Respond ONLY with raw JSON object strictly matching schema: "
                '{"same_transaction": boolean, "selected_bank_id": string, "reference_evidence": string, '
                '"amount_consistent": boolean, "date_consistent": boolean, "fee_explanation": string, "reason": string}'
            ),
        },
        {"role": "user", "content": json.dumps({"ledger": ledger_summary, "bank_candidates": bank_candidates}, indent=2)},
    ]

    # Synchronize rate limit configuration
    configured_rpm = _parse_rpm(os.getenv("GROQ_MAX_CALLS_PER_MINUTE"), getattr(config, "GROQ_MAX_CALLS_PER_MINUTE", 25))
    _RATE_LIMITER.update_limit(configured_rpm)

    max_retries = getattr(config, "GROQ_RETRY_ATTEMPTS", 2)
    backoff_base = getattr(config, "GROQ_RETRY_BACKOFF_BASE", 0.5)

    response = None
    last_error: Optional[Exception] = None

    for attempt in range(max_retries + 1):
        # Enforce rate limiter wait before dispatching call
        _RATE_LIMITER.acquire()
        try:
            response = client.chat.completions.create(
                model=config.GROQ_MODEL,
                messages=prompt_messages,
                timeout=10.0,
            )
            last_error = None
            break
        except Exception as exc:
            last_error = exc
            err_msg = str(exc).lower()
            is_rate_limit = "429" in err_msg or "rate limit" in err_msg or "too many requests" in err_msg

            # Retry with exponential backoff on rate limit errors
            if is_rate_limit and attempt < max_retries:
                sleep_time = backoff_base * (2 ** attempt)
                time.sleep(sleep_time)
                continue
            # For non-rate-limit errors or exhausted retries, exit retry loop
            break

    if last_error is not None or response is None:
        err_text = str(last_error) if last_error else "Empty response"
        result = {
            "same_transaction": False,
            "selected_bank_id": "",
            "reference_evidence": "API error",
            "amount_consistent": False,
            "date_consistent": False,
            "fee_explanation": "None",
            "reason": f"AI error: {err_text}. Safe fallback to REVIEW.",
            "model_used": config.GROQ_MODEL,
            "status": "REVIEW",
        }
        _AI_CACHE[cache_key] = result
        return result

    try:
        raw_json = parse_json_from_llm(response.choices[0].message.content)

        for k in ("same_transaction", "amount_consistent", "date_consistent"):
            if k in raw_json:
                raw_json[k] = coerce_boolean(raw_json[k])

        parsed = AIEvaluationSchema.model_validate(raw_json)
        same_tx, selected_id = parsed.same_transaction, parsed.selected_bank_id

        if same_tx:
            if not selected_id:
                same_tx, selected_id, reason_msg = False, "", "AI decision vetoed: same_transaction is true but selected_bank_id is missing."
            elif selected_id not in valid_candidate_ids:
                same_tx, selected_id, reason_msg = False, "", f"AI decision vetoed: hallucinated bank ID '{selected_id}' not in candidate pool."
            else:
                reason_msg = parsed.reason or "AI confirmed match."
        else:
            reason_msg = parsed.reason or "AI suggested review."

        result = {
            "same_transaction": same_tx,
            "selected_bank_id": selected_id or "",
            "reference_evidence": parsed.reference_evidence,
            "amount_consistent": parsed.amount_consistent,
            "date_consistent": parsed.date_consistent,
            "fee_explanation": parsed.fee_explanation,
            "reason": reason_msg,
            "model_used": config.GROQ_MODEL,
            "status": "MATCHED" if same_tx else "REVIEW",
        }
    except Exception as exc:
        result = {
            "same_transaction": False,
            "selected_bank_id": "",
            "reference_evidence": "Parse error",
            "amount_consistent": False,
            "date_consistent": False,
            "fee_explanation": "None",
            "reason": f"AI response parsing error: {str(exc)}. Safe fallback to REVIEW.",
            "model_used": config.GROQ_MODEL,
            "status": "REVIEW",
        }

    _AI_CACHE[cache_key] = result
    return result

