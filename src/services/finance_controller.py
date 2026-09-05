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
    "BATCH_AGGREGATE_SUSPECTED": "Bank credit may be a batch aggregate of multiple ledger orders",
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


def detect_batch_aggregates(
    df_ledger: pd.DataFrame,
    df_bank: pd.DataFrame,
    df_results: pd.DataFrame,
    tolerance_pct: float = 0.02,
    date_window_days: int = 5,
) -> List[Dict[str, Any]]:
    """Detect unmatched bank credits that may be batch aggregate settlements of multiple ledger orders.

    A payment gateway (e.g. Razorpay) sometimes batches multiple orders into a single bank settlement.
    For example, three orders for ₹1,000 + ₹2,000 + ₹3,000 arrive as a single ₹5,940 bank credit
    (after 1% MDR fee). This function detects such patterns using a greedy cumulative-sum heuristic.

    Args:
        df_ledger: Original ledger DataFrame with order records.
        df_bank: Original bank statement DataFrame.
        df_results: Reconciliation results DataFrame from reconcile().
        tolerance_pct: Max fractional difference allowed between cumulative ledger sum and bank amount (default 2%).
        date_window_days: Max days between ledger order dates and bank credit date to consider (default ±5 days).

    Returns:
        List of suspected batch aggregate dicts, each containing:
            - bank_utr: Bank UTR reference of the unmatched credit
            - bank_amount: Bank credit amount
            - bank_date: Bank credit value date
            - suspected_ledger_ids: List of order IDs whose amounts sum near the bank amount
            - combined_ledger_amount: Sum of suspected ledger order amounts
            - variance_pct: Percentage difference between combined amount and bank amount
            - recommendation: Human-readable action recommendation
    """
    from datetime import datetime, timedelta

    if df_results.empty or df_ledger.empty or df_bank.empty:
        return []

    required_ledger = {"order_id", "amount", "order_date"}
    required_bank = {"utr_reference", "credited_amount", "value_date"}
    if not required_ledger.issubset(df_ledger.columns) or not required_bank.issubset(df_bank.columns):
        return []

    # Identify unmatched ledger order IDs
    unmatched_ledger_ids: set = set(
        df_results[
            (df_results["status"] == "UNMATCHED") &
            (df_results["ledger_id"].astype(str) != "")
        ]["ledger_id"].astype(str).tolist()
    )

    # Identify unmatched bank UTRs
    unmatched_bank_utrs: set = set(
        df_results[
            (df_results["status"] == "UNMATCHED") &
            (df_results["bank_id"].astype(str) != "")
        ]["bank_id"].astype(str).tolist()
    )

    if not unmatched_ledger_ids or not unmatched_bank_utrs:
        return []

    # Filter DataFrames to unmatched records only
    unmatched_ledger = df_ledger[df_ledger["order_id"].astype(str).isin(unmatched_ledger_ids)].copy()
    unmatched_bank = df_bank[df_bank["utr_reference"].astype(str).isin(unmatched_bank_utrs)].copy()

    if unmatched_ledger.empty or unmatched_bank.empty:
        return []

    def parse_date(val: Any):
        """Safe date parser returning a datetime.date or None."""
        try:
            if hasattr(val, "date"):
                return val.date() if hasattr(val.date, "__call__") else val
            return datetime.strptime(str(val)[:10], "%Y-%m-%d").date()
        except Exception:
            return None

    suspected_aggregates: List[Dict[str, Any]] = []

    for _, bank_row in unmatched_bank.iterrows():
        bank_amt = float(bank_row.get("credited_amount", 0.0))
        bank_date = parse_date(bank_row.get("value_date", ""))
        bank_utr = str(bank_row.get("utr_reference", ""))

        if bank_amt <= 0:
            continue

        # Filter ledger records within the date window
        nearby_ledger = []
        for _, l_row in unmatched_ledger.iterrows():
            l_date = parse_date(l_row.get("order_date", ""))
            if l_date is None or bank_date is None:
                nearby_ledger.append((str(l_row.get("order_id", "")), float(l_row.get("amount", 0.0))))
            elif abs((bank_date - l_date).days) <= date_window_days:
                nearby_ledger.append((str(l_row.get("order_id", "")), float(l_row.get("amount", 0.0))))

        if not nearby_ledger:
            continue

        # Greedy cumulative-sum search: keep adding orders until sum ≥ bank_amt or within tolerance
        cumulative_sum = 0.0
        matched_ids: List[str] = []

        for order_id, amt in nearby_ledger:
            cumulative_sum += amt
            matched_ids.append(order_id)

            if cumulative_sum <= 0:
                continue

            variance = abs(cumulative_sum - bank_amt) / bank_amt
            if variance <= tolerance_pct and len(matched_ids) >= 2:
                suspected_aggregates.append({
                    "bank_utr": bank_utr,
                    "bank_amount": round(bank_amt, 2),
                    "bank_date": str(bank_date) if bank_date else "",
                    "suspected_ledger_ids": list(matched_ids),
                    "combined_ledger_amount": round(cumulative_sum, 2),
                    "variance_pct": round(variance * 100, 3),
                    "recommendation": (
                        f"Suspected batch aggregate of {len(matched_ids)} orders totalling "
                        f"₹{cumulative_sum:.2f} (variance {variance * 100:.2f}% from bank credit ₹{bank_amt:.2f}). "
                        "Manually verify with payment gateway settlement report."
                    ),
                })
                break

            # If we've exceeded bank_amt by more than tolerance, no point continuing
            if cumulative_sum > bank_amt * (1.0 + tolerance_pct):
                break

    return suspected_aggregates


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
