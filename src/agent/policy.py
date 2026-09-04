"""Deterministic Policy Engine enforcing financial safety boundaries and autonomy rules."""

import re
from typing import Dict, Any, List, Optional
from src.agent.models import (
    CaseState,
    ReconciliationCase,
    ActionType,
    PolicyDecision,
    CaseInvestigation,
)


class PolicyEngine:
    """Evaluates proposed agent recommendations against strict deterministic policy rules."""

    def __init__(
        self,
        max_auto_fee_amount: float = 100.0,
        min_auto_match_score: float = 0.82,
        require_approval_for_fees: bool = False,
    ):
        self.max_auto_fee_amount = max_auto_fee_amount
        self.min_auto_match_score = min_auto_match_score
        self.require_approval_for_fees = require_approval_for_fees

    def sanitize_untrusted_text(self, text: str) -> str:
        """Strip potential prompt injection strings or command directives from untrusted transaction fields."""
        if not text:
            return ""
        # Remove known prompt injection patterns
        sanitized = re.sub(
            r"(?i)(ignore\s+all\s+previous|system\s*prompt|mark\s+as\s+reconciled|override\s+policy)",
            "[REDACTED_TEXT]",
            str(text),
        )
        return sanitized.strip()

    def evaluate(
        self,
        case: ReconciliationCase,
        investigation: Optional[CaseInvestigation] = None,
    ) -> PolicyDecision:
        """Evaluate a reconciliation case and its investigation recommendation against safety policies.

        Returns:
            PolicyDecision detailing whether the action is allowed, requires approval, risk tier, and policy code.
        """
        # Rule 1: High confidence deterministic MATCHED case -> Auto approve MARK_RECONCILED
        if case.status == "MATCHED" and case.score >= self.min_auto_match_score:
            return PolicyDecision(
                allowed=True,
                action_type=ActionType.MARK_RECONCILED.value,
                requires_approval=False,
                policy_code="POL_HIGH_CONFIDENCE_MATCH",
                risk_level="LOW",
                reason=f"Score {case.score:.4f} exceeds auto-match threshold {self.min_auto_match_score}",
            )

        # Rule 2: Unmatched record -> Mark unmatched
        if case.status == "UNMATCHED":
            return PolicyDecision(
                allowed=True,
                action_type=ActionType.MARK_UNMATCHED.value,
                requires_approval=False,
                policy_code="POL_CONFIRMED_UNMATCHED",
                risk_level="LOW",
                reason="No matching candidate found in bank statement",
            )

        # Rule 3: Investigate recommendation policy check
        rec_action = investigation.recommended_action if investigation else ActionType.FLAG_FOR_REVIEW.value
        reason_code = investigation.reason_code if investigation else "AMBIGUOUS"

        # Check for Fee Adjustment policy
        if reason_code == "FEE_ADJUSTMENT" or rec_action == ActionType.CREATE_FEE_ADJUSTMENT.value:
            amt_diff = float(case.evidence.get("amount_difference", 0.0))
            if amt_diff <= self.max_auto_fee_amount and not self.require_approval_for_fees:
                return PolicyDecision(
                    allowed=True,
                    action_type=ActionType.CREATE_FEE_ADJUSTMENT.value,
                    requires_approval=False,
                    policy_code="POL_FEE_WITHIN_TOLERANCE",
                    risk_level="LOW",
                    reason=f"Fee variance ₹{amt_diff:.2f} is within auto-adjustment limit ₹{self.max_auto_fee_amount:.2f}",
                )
            else:
                return PolicyDecision(
                    allowed=True,
                    action_type=ActionType.CREATE_FEE_ADJUSTMENT.value,
                    requires_approval=True,
                    policy_code="POL_FEE_EXCEEDS_AUTO_LIMIT",
                    risk_level="MEDIUM",
                    reason=f"Fee variance ₹{amt_diff:.2f} exceeds limit ₹{self.max_auto_fee_amount:.2f} — human approval required",
                )

        # Rule 4: One-to-one conflicts & currency mismatches always require human approval
        if case.exception_type in ("ONE_TO_ONE_CONFLICT", "CURRENCY_MISMATCH"):
            return PolicyDecision(
                allowed=True,
                action_type=ActionType.FLAG_FOR_REVIEW.value,
                requires_approval=True,
                policy_code="POL_HIGH_RISK_EXCEPTION",
                risk_level="HIGH",
                reason=f"High risk exception type '{case.exception_type}' requires human review",
            )

        # Default Fallback: Any ambiguous or review case requires human approval
        return PolicyDecision(
            allowed=True,
            action_type=ActionType.FLAG_FOR_REVIEW.value,
            requires_approval=True,
            policy_code="POL_REQUIRE_HUMAN_REVIEW",
            risk_level="MEDIUM",
            reason=f"Case status '{case.status}' with score {case.score:.4f} requires human review",
        )
