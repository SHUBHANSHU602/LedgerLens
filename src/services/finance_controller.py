"""Finance Controller — Lightweight batch orchestration for reconciliation runs.

Accepts a reconciliation result DataFrame and produces a structured batch summary
with exception classification, auto-resolution actions, and batch lifecycle states.

Batch States: OPEN → PROCESSING → REVIEW_REQUIRED → READY_TO_CLOSE → CLOSED
"""

import uuid
from dataclasses import dataclass, field, asdict
from typing import Dict, Any, List, Optional
import pandas as pd


# ---------------------------------------------------------------------------
# Exception Types
# ---------------------------------------------------------------------------

EXCEPTION_TYPES = {
    "FEE_ADJUSTMENT": "Settlement fee deduction detected",
    "MISSING_COUNTERPARTY": "No matching counterparty found",
    "AMBIGUOUS_MATCH": "Multiple plausible candidates — requires human review",
    "FALSE_POSITIVE_RISK": "High-similarity decoy detected — auto-resolution blocked",
    "DATE_MISMATCH": "Settlement date outside expected window",
    "CURRENCY_MISMATCH": "Currency contradiction between ledger and bank",
    "ONE_TO_ONE_CONFLICT": "Duplicate bank assignment prevented",
    "AI_INCONCLUSIVE": "AI could not confirm match — escalated to review",
}


@dataclass
class BatchException:
    """A single exception within a reconciliation batch."""
    ledger_id: str
    bank_id: str
    exception_type: str
    description: str
    recommended_action: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class BatchSummary:
    """Complete batch reconciliation summary produced by the Finance Controller."""
    run_id: str
    batch_status: str  # OPEN, PROCESSING, REVIEW_REQUIRED, READY_TO_CLOSE, CLOSED
    total_records: int = 0
    reconciled_count: int = 0
    review_count: int = 0
    unmatched_count: int = 0
    auto_resolved_count: int = 0
    ai_assisted_count: int = 0
    exception_summary: List[Dict[str, Any]] = field(default_factory=list)
    recommended_actions: List[str] = field(default_factory=list)
    closing_summary: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _classify_exception(row: pd.Series) -> Optional[BatchException]:
    """Classify a reconciliation result row into an exception type, if applicable."""
    status = str(row.get("status", ""))
    rule = str(row.get("matching_rule", ""))
    reason = str(row.get("reason", ""))
    l_id = str(row.get("ledger_id", ""))
    b_id = str(row.get("bank_id", ""))
    amt_diff = float(row.get("amount_difference", 0.0))

    if status == "MATCHED":
        return None

    # Fee-related exceptions
    if "FEE" in rule.upper() or "fee" in reason.lower() or (amt_diff > 0 and amt_diff <= 100):
        return BatchException(
            ledger_id=l_id, bank_id=b_id,
            exception_type="FEE_ADJUSTMENT",
            description=f"Amount difference ₹{amt_diff:.2f} — likely settlement fee",
            recommended_action="Verify fee matches gateway MDR schedule",
        )

    # Currency mismatch
    if "CURRENCY" in rule.upper() or "currency" in reason.lower():
        return BatchException(
            ledger_id=l_id, bank_id=b_id,
            exception_type="CURRENCY_MISMATCH",
            description="Currency mismatch between ledger and bank record",
            recommended_action="Verify correct currency and FX conversion",
        )

    # One-to-one conflict
    if rule == "ONE_TO_ONE_CONFLICT":
        return BatchException(
            ledger_id=l_id, bank_id=b_id,
            exception_type="ONE_TO_ONE_CONFLICT",
            description="Multiple ledger records claimed the same bank entry",
            recommended_action="Manually verify which ledger record owns this bank credit",
        )

    # Ambiguity
    if rule in ("AMBIGUOUS_CANDIDATES", "SCORE_REVIEW"):
        return BatchException(
            ledger_id=l_id, bank_id=b_id,
            exception_type="AMBIGUOUS_MATCH",
            description=reason,
            recommended_action="Human review required — compare candidates manually",
        )

    # AI inconclusive
    if rule == "AI_REVIEW_REQUIRED":
        return BatchException(
            ledger_id=l_id, bank_id=b_id,
            exception_type="AI_INCONCLUSIVE",
            description=reason,
            recommended_action="AI could not confirm — manual verification needed",
        )

    # Unmatched
    if status == "UNMATCHED":
        if l_id and not b_id:
            return BatchException(
                ledger_id=l_id, bank_id="",
                exception_type="MISSING_COUNTERPARTY",
                description="No bank statement counterpart found",
                recommended_action="Investigate missing settlement — check payment gateway",
            )
        elif b_id and not l_id:
            return BatchException(
                ledger_id="", bank_id=b_id,
                exception_type="MISSING_COUNTERPARTY",
                description="Bank credit without matching ledger order",
                recommended_action="Investigate unrecognized bank deposit",
            )

    # Generic review fallback
    if status == "REVIEW":
        return BatchException(
            ledger_id=l_id, bank_id=b_id,
            exception_type="AMBIGUOUS_MATCH",
            description=reason,
            recommended_action="Manual review required",
        )

    return None


def process_batch(
    df_results: pd.DataFrame,
    run_id: Optional[str] = None,
    auto_close_if_clean: bool = False,
) -> BatchSummary:
    """Process a reconciliation result DataFrame through the Finance Controller.

    Args:
        df_results: Output from reconcile().
        run_id: Optional run identifier. Auto-generated if not provided.
        auto_close_if_clean: If True and no exceptions remain, set batch to READY_TO_CLOSE.

    Returns:
        BatchSummary with batch status, counts, exceptions, and recommended actions.
    """
    if run_id is None:
        run_id = f"BATCH-{uuid.uuid4().hex[:8].upper()}"

    if df_results.empty or "status" not in df_results.columns:
        return BatchSummary(
            run_id=run_id,
            batch_status="OPEN",
            total_records=0,
        )

    matched = df_results[df_results["status"] == "MATCHED"]
    reviews = df_results[df_results["status"] == "REVIEW"]
    unmatched = df_results[df_results["status"] == "UNMATCHED"]

    # Count auto-resolved (deterministic MATCHED) vs AI-assisted
    auto_resolved = len(matched[matched["decision_source"] == "deterministic"]) if "decision_source" in matched.columns else len(matched)
    ai_assisted = len(matched[matched["decision_source"] == "groq"]) if "decision_source" in matched.columns else 0

    # Classify exceptions
    exceptions: List[BatchException] = []
    for _, row in df_results.iterrows():
        exc = _classify_exception(row)
        if exc is not None:
            exceptions.append(exc)

    # Determine batch status
    has_exceptions = len(exceptions) > 0
    if len(df_results) == 0:
        batch_status = "OPEN"
    elif has_exceptions:
        batch_status = "REVIEW_REQUIRED"
    elif auto_close_if_clean:
        batch_status = "READY_TO_CLOSE"
    else:
        batch_status = "READY_TO_CLOSE"

    # Build recommended actions
    actions: List[str] = []
    exception_type_counts: Dict[str, int] = {}
    for exc in exceptions:
        exception_type_counts[exc.exception_type] = exception_type_counts.get(exc.exception_type, 0) + 1

    for exc_type, count in sorted(exception_type_counts.items(), key=lambda x: -x[1]):
        desc = EXCEPTION_TYPES.get(exc_type, exc_type)
        actions.append(f"{count}x {exc_type}: {desc}")

    if not has_exceptions:
        actions.append("All transactions reconciled — batch ready for closure")

    # Build closing summary
    total = len(df_results)
    closing_summary = (
        f"Batch {run_id}: {len(matched)}/{total} matched "
        f"({auto_resolved} auto, {ai_assisted} AI-assisted), "
        f"{len(reviews)} review, {len(unmatched)} unmatched, "
        f"{len(exceptions)} exceptions"
    )

    return BatchSummary(
        run_id=run_id,
        batch_status=batch_status,
        total_records=total,
        reconciled_count=len(matched),
        review_count=len(reviews),
        unmatched_count=len(unmatched),
        auto_resolved_count=auto_resolved,
        ai_assisted_count=ai_assisted,
        exception_summary=[e.to_dict() for e in exceptions],
        recommended_actions=actions,
        closing_summary=closing_summary,
    )
