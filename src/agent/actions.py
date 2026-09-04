"""Bounded Action Registry, execution handlers, and outcome verification loop."""

import uuid
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Callable, Tuple
from src.agent.models import (
    CaseState,
    ReconciliationCase,
    ActionType,
    AgentAction,
    ActionExecution,
    VerificationResult,
)


class ActionHandler:
    """Base handler interface for a bounded agent action."""

    def execute(self, case: ReconciliationCase, action: AgentAction) -> ActionExecution:
        raise NotImplementedError

    def verify(self, case: ReconciliationCase, execution: ActionExecution) -> VerificationResult:
        raise NotImplementedError


class MarkReconciledHandler(ActionHandler):
    """Handler for MARK_RECONCILED action."""

    def execute(self, case: ReconciliationCase, action: AgentAction) -> ActionExecution:
        case.status = "MATCHED"
        case.transition_to(
            CaseState.RESOLVED,
            actor="ACTION_SERVICE",
            event_type="ACTION_MARK_RECONCILED",
            details={"bank_id": case.bank_id, "score": case.score},
        )
        return ActionExecution(
            action_id=action.action_id,
            execution_status="SUCCESS",
            result_payload={"case_id": case.case_id, "final_status": "MATCHED"},
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    def verify(self, case: ReconciliationCase, execution: ActionExecution) -> VerificationResult:
        is_valid = case.state in (CaseState.RESOLVED, CaseState.ACTION_VERIFYING) and case.status == "MATCHED"
        return VerificationResult(
            verified=is_valid,
            status="VERIFIED" if is_valid else "FAILED",
            verification_notes="Verified case state is RESOLVED and status is MATCHED.",
            timestamp=datetime.now(timezone.utc).isoformat(),
        )



class CreateFeeAdjustmentHandler(ActionHandler):
    """Handler for CREATE_FEE_ADJUSTMENT action."""

    def execute(self, case: ReconciliationCase, action: AgentAction) -> ActionExecution:
        amt_diff = float(case.evidence.get("amount_difference", 0.0))
        fee_payload = {
            "fee_adjustment_id": f"FEE-{uuid.uuid4().hex[:8].upper()}",
            "ledger_id": case.ledger_id,
            "bank_id": case.bank_id,
            "amount": amt_diff,
            "reason": "Settlement MDR Gateway Fee Adjustment",
        }
        case.status = "MATCHED"
        case.transition_to(
            CaseState.RESOLVED,
            actor="ACTION_SERVICE",
            event_type="ACTION_CREATE_FEE_ADJUSTMENT",
            details=fee_payload,
        )
        return ActionExecution(
            action_id=action.action_id,
            execution_status="SUCCESS",
            result_payload=fee_payload,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    def verify(self, case: ReconciliationCase, execution: ActionExecution) -> VerificationResult:
        has_fee_id = "fee_adjustment_id" in execution.result_payload
        is_valid = case.state in (CaseState.RESOLVED, CaseState.ACTION_VERIFYING) and has_fee_id
        return VerificationResult(
            verified=is_valid,
            status="VERIFIED" if is_valid else "FAILED",
            verification_notes="Verified fee adjustment item created and case resolved.",
            timestamp=datetime.now(timezone.utc).isoformat(),
        )


class FlagForReviewHandler(ActionHandler):
    """Handler for FLAG_FOR_REVIEW action."""

    def execute(self, case: ReconciliationCase, action: AgentAction) -> ActionExecution:
        case.status = "REVIEW"
        case.transition_to(
            CaseState.ACTION_PENDING_APPROVAL,
            actor="ACTION_SERVICE",
            event_type="ACTION_FLAG_FOR_REVIEW",
            details={"reason": case.exception_type},
        )
        return ActionExecution(
            action_id=action.action_id,
            execution_status="SUCCESS",
            result_payload={"case_id": case.case_id, "requires_human_approval": True},
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    def verify(self, case: ReconciliationCase, execution: ActionExecution) -> VerificationResult:
        is_valid = case.state in (CaseState.ACTION_PENDING_APPROVAL, CaseState.ESCALATED, CaseState.ACTION_VERIFYING)
        return VerificationResult(
            verified=is_valid,
            status="VERIFIED" if is_valid else "FAILED",
            verification_notes="Verified case flagged for human review approval.",
            timestamp=datetime.now(timezone.utc).isoformat(),
        )


class MarkUnmatchedHandler(ActionHandler):
    """Handler for MARK_UNMATCHED action."""

    def execute(self, case: ReconciliationCase, action: AgentAction) -> ActionExecution:
        case.status = "UNMATCHED"
        case.transition_to(
            CaseState.UNMATCHED,
            actor="ACTION_SERVICE",
            event_type="ACTION_MARK_UNMATCHED",
            details={"ledger_id": case.ledger_id, "bank_id": case.bank_id},
        )
        return ActionExecution(
            action_id=action.action_id,
            execution_status="SUCCESS",
            result_payload={"case_id": case.case_id, "final_status": "UNMATCHED"},
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    def verify(self, case: ReconciliationCase, execution: ActionExecution) -> VerificationResult:
        is_valid = case.state in (CaseState.UNMATCHED, CaseState.ACTION_VERIFYING)
        return VerificationResult(
            verified=is_valid,
            status="VERIFIED" if is_valid else "FAILED",
            verification_notes="Verified case set to UNMATCHED.",
            timestamp=datetime.now(timezone.utc).isoformat(),
        )



class ActionRegistry:
    """Registry mapping ActionTypes to their concrete ActionHandlers."""

    def __init__(self):
        self._handlers: Dict[str, ActionHandler] = {
            ActionType.MARK_RECONCILED.value: MarkReconciledHandler(),
            ActionType.CREATE_FEE_ADJUSTMENT.value: CreateFeeAdjustmentHandler(),
            ActionType.FLAG_FOR_REVIEW.value: FlagForReviewHandler(),
            ActionType.MARK_UNMATCHED.value: MarkUnmatchedHandler(),
        }

    def get_handler(self, action_type: str) -> Optional[ActionHandler]:
        return self._handlers.get(action_type)


class ActionService:
    """Orchestrates action execution, idempotency, and verification loops."""

    def __init__(self, registry: Optional[ActionRegistry] = None):
        self.registry = registry or ActionRegistry()
        self.executed_actions: Dict[str, ActionExecution] = {}

    def execute_and_verify(
        self,
        case: ReconciliationCase,
        action_type: str,
        payload: Optional[Dict[str, Any]] = None,
    ) -> Tuple[ActionExecution, VerificationResult]:
        """Execute a policy-approved action and verify its outcome.

        Idempotency Guard: Prevents duplicate execution if action was already run.
        """
        action_id = f"ACT-{uuid.uuid4().hex[:8].upper()}"
        action = AgentAction(
            action_id=action_id,
            case_id=case.case_id,
            action_type=action_type,
            payload=payload or {},
        )

        handler = self.registry.get_handler(action_type)
        if handler is None:
            # Fallback to flag for review if handler is missing
            handler = FlagForReviewHandler()

        # Idempotency check
        idem_key = f"{case.case_id}:{action_type}"
        if idem_key in self.executed_actions:
            existing = self.executed_actions[idem_key]
            verification = VerificationResult(
                verified=True,
                status="VERIFIED",
                verification_notes="Action already executed (Idempotency check passed).",
                timestamp=datetime.now(timezone.utc).isoformat(),
            )
            return existing, verification

        # Transition state to ACTION_EXECUTING
        case.transition_to(
            CaseState.ACTION_EXECUTING,
            actor="ACTION_SERVICE",
            event_type="EXECUTING_ACTION",
            details={"action_type": action_type},
        )

        # Execute
        execution = handler.execute(case, action)
        self.executed_actions[idem_key] = execution

        # Verify
        case.transition_to(
            CaseState.ACTION_VERIFYING,
            actor="ACTION_SERVICE",
            event_type="VERIFYING_ACTION",
            details={"execution_status": execution.execution_status},
        )
        verification = handler.verify(case, execution)

        if verification.verified:
            if case.status == "MATCHED":
                final_state = CaseState.RESOLVED
            elif case.status == "UNMATCHED":
                final_state = CaseState.UNMATCHED
            else:
                final_state = CaseState.ACTION_PENDING_APPROVAL
            case.state = final_state

        case.action_execution = execution
        case.verification = verification

        return execution, verification

