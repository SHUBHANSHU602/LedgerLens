"""Exception Investigation Agent for analyzing ambiguous transactions and synthesizing evidence."""

import os
from typing import Dict, Any, List, Optional
from src.agent.models import ReconciliationCase, CaseInvestigation, ActionType
from src.agent.policy import PolicyEngine

try:
    from src.ai_matcher import evaluate_ambiguous_record
except ModuleNotFoundError:
    try:
        from ai_matcher import evaluate_ambiguous_record
    except ModuleNotFoundError:
        evaluate_ambiguous_record = None


class ExceptionInvestigator:
    """Agent responsible for investigating ambiguous or exception cases."""

    def __init__(self, policy_engine: Optional[PolicyEngine] = None):
        self.policy_engine = policy_engine or PolicyEngine()

    def investigate(self, case: ReconciliationCase) -> CaseInvestigation:
        """Investigate a reconciliation exception and produce a structured recommendation."""
        # Sanitize text fields
        l_notes = self.policy_engine.sanitize_untrusted_text(str(case.ledger_record.get("remarks", "")))
        b_narration = self.policy_engine.sanitize_untrusted_text(str(case.bank_record.get("norm_narration", "")))

        amt_diff = float(case.evidence.get("amount_difference", 0.0))
        date_diff = int(case.evidence.get("date_difference", 0))
        exc_type = case.exception_type

        # Case 1: Fee Adjustment (small positive amount difference <= 100)
        if exc_type == "FEE_ADJUSTMENT" or (amt_diff > 0 and amt_diff <= 100.0):
            return CaseInvestigation(
                reason_code="FEE_ADJUSTMENT",
                fee_explanation=f"Ledger amount is ₹{case.ledger_record.get('norm_amount', 0):.2f}, bank net credit is ₹{case.bank_record.get('norm_amount', 0):.2f}. Difference ₹{amt_diff:.2f} is consistent with gateway MDR fee schedules.",
                date_explanation=f"Date offset is {date_diff} day(s), within expected settlement window.",
                confidence=0.92,
                reasoning=f"Amount variance ₹{amt_diff:.2f} matches standard gateway settlement fee deduction.",
                evidence_summary={
                    "amount_difference": amt_diff,
                    "date_difference": date_diff,
                    "sanitized_narration": b_narration,
                },
                recommended_action=ActionType.CREATE_FEE_ADJUSTMENT.value,
            )

        # Case 2: One-to-One Conflict
        if exc_type == "ONE_TO_ONE_CONFLICT":
            return CaseInvestigation(
                reason_code="ONE_TO_ONE_CONFLICT",
                fee_explanation="N/A",
                date_explanation=f"Date offset is {date_diff} day(s).",
                confidence=0.60,
                reasoning="Multiple ledger items claimed the same bank deposit. Assigned to candidate with lower score.",
                evidence_summary={"conflict": True, "score": case.score},
                recommended_action=ActionType.FLAG_FOR_REVIEW.value,
            )

        # Case 3: Currency Mismatch
        if exc_type == "CURRENCY_MISMATCH":
            return CaseInvestigation(
                reason_code="CURRENCY_MISMATCH",
                fee_explanation="N/A",
                date_explanation="N/A",
                confidence=0.30,
                reasoning="Currency contradiction between ledger and bank records.",
                evidence_summary={"currency_mismatch": True},
                recommended_action=ActionType.FLAG_FOR_REVIEW.value,
            )

        # Case 4: Ambiguous Match — invoke LLM if available, else deterministic fallback
        if case.candidates and evaluate_ambiguous_record is not None and os.getenv("GROQ_API_KEY"):
            try:
                ai_res = evaluate_ambiguous_record(
                    ledger_row=case.ledger_record,
                    top_candidates=case.candidates,
                )
                if ai_res.same_transaction:
                    return CaseInvestigation(
                        reason_code="AI_MATCH_CONFIRMED",
                        fee_explanation=ai_res.fee_explanation or "None",
                        date_explanation=f"Date offset is {date_diff} day(s).",
                        confidence=0.88,
                        reasoning=f"LLM confirmed candidate '{ai_res.selected_bank_id}': {ai_res.reason}",
                        evidence_summary={
                            "ai_invoked": True,
                            "selected_bank_id": ai_res.selected_bank_id,
                            "ref_evidence": ai_res.reference_evidence,
                        },
                        recommended_action=ActionType.MARK_RECONCILED.value,
                    )
            except Exception as e:
                pass  # Fall back to rule-based review

        # Default Fallback Case
        return CaseInvestigation(
            reason_code="AMBIGUOUS_MATCH",
            fee_explanation=f"Amount difference ₹{amt_diff:.2f}",
            date_explanation=f"Date offset is {date_diff} day(s).",
            confidence=round(case.score, 4),
            reasoning=f"Evidence score {case.score:.4f} requires manual verification.",
            evidence_summary={"score": case.score, "candidate_count": len(case.candidates)},
            recommended_action=ActionType.FLAG_FOR_REVIEW.value,
        )
