"""Domain models, state machine definitions, and typed schemas for LedgerLens Agent."""

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field, asdict
from pydantic import BaseModel, Field, ConfigDict


class CaseState(str, Enum):
    """Explicit state machine states for a reconciliation case."""
    NEW = "NEW"
    INGESTING = "INGESTING"
    NORMALIZING = "NORMALIZING"
    RECONCILING = "RECONCILING"
    MATCHED = "MATCHED"
    AMBIGUOUS = "AMBIGUOUS"
    INVESTIGATING = "INVESTIGATING"
    RECOMMENDATION_READY = "RECOMMENDATION_READY"
    POLICY_APPROVED = "POLICY_APPROVED"
    POLICY_DENIED = "POLICY_DENIED"
    ACTION_PENDING_APPROVAL = "ACTION_PENDING_APPROVAL"
    ACTION_EXECUTING = "ACTION_EXECUTING"
    ACTION_VERIFYING = "ACTION_VERIFYING"
    RESOLVED = "RESOLVED"
    UNMATCHED = "UNMATCHED"
    ESCALATED = "ESCALATED"
    FAILED = "FAILED"


class ActionType(str, Enum):
    """Bounded supported action types for the agent."""
    MARK_RECONCILED = "MARK_RECONCILED"
    CREATE_FEE_ADJUSTMENT = "CREATE_FEE_ADJUSTMENT"
    FLAG_FOR_REVIEW = "FLAG_FOR_REVIEW"
    MARK_UNMATCHED = "MARK_UNMATCHED"
    ADD_RESOLUTION_NOTE = "ADD_RESOLUTION_NOTE"
    REQUEST_HUMAN_APPROVAL = "REQUEST_HUMAN_APPROVAL"


@dataclass
class AuditEvent:
    """Immutable audit trail log entry for agent decisions and actions."""
    event_id: str
    timestamp: str
    case_id: str
    actor: str  # e.g., "ENGINE", "AI_INVESTIGATOR", "POLICY_ENGINE", "ACTION_SERVICE", "HUMAN"
    event_type: str
    from_state: str
    to_state: str
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class CaseInvestigation:
    """Findings from exception investigation (AI or rule-based)."""
    reason_code: str
    fee_explanation: str
    date_explanation: str
    confidence: float
    reasoning: str
    evidence_summary: Dict[str, Any] = field(default_factory=dict)
    recommended_action: str = ActionType.FLAG_FOR_REVIEW.value

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PolicyDecision:
    """Result of policy evaluation on a proposed agent recommendation."""
    allowed: bool
    action_type: str
    requires_approval: bool
    policy_code: str
    risk_level: str  # LOW, MEDIUM, HIGH
    reason: str

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class AgentAction:
    """Concrete executable action item bound to a case."""
    action_id: str
    case_id: str
    action_type: str
    payload: Dict[str, Any] = field(default_factory=dict)
    status: str = "PENDING"  # PENDING, EXECUTED, FAILED, CANCELLED

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ActionExecution:
    """Recorded result of an executed action."""
    action_id: str
    execution_status: str  # SUCCESS, FAILED
    result_payload: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class VerificationResult:
    """Verification output ensuring executed action was successful and idempotent."""
    verified: bool
    status: str  # VERIFIED, UNVERIFIED, FAILED
    verification_notes: str
    timestamp: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ReconciliationCase:
    """Central domain object representing a transaction reconciliation case lifecycle."""
    case_id: str
    ledger_id: str
    bank_id: str
    state: CaseState
    ledger_record: Dict[str, Any] = field(default_factory=dict)
    bank_record: Dict[str, Any] = field(default_factory=dict)
    candidates: List[Dict[str, Any]] = field(default_factory=list)
    evidence: Dict[str, Any] = field(default_factory=dict)
    score: float = 0.0
    status: str = "UNMATCHED"  # MATCHED, REVIEW, UNMATCHED
    exception_type: str = "NONE"
    investigation: Optional[CaseInvestigation] = None
    policy_decision: Optional[PolicyDecision] = None
    action_execution: Optional[ActionExecution] = None
    verification: Optional[VerificationResult] = None
    audit_history: List[AuditEvent] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def transition_to(
        self,
        new_state: CaseState,
        actor: str,
        event_type: str,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Deterministically transition case state and record audit event."""
        old_state_str = self.state.value
        self.state = new_state
        self.updated_at = datetime.now(timezone.utc).isoformat()

        event = AuditEvent(
            event_id=f"EVT-{uuid.uuid4().hex[:8].upper()}",
            timestamp=self.updated_at,
            case_id=self.case_id,
            actor=actor,
            event_type=event_type,
            from_state=old_state_str,
            to_state=new_state.value,
            details=details or {},
        )
        self.audit_history.append(event)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "case_id": self.case_id,
            "ledger_id": self.ledger_id,
            "bank_id": self.bank_id,
            "state": self.state.value,
            "ledger_record": self.ledger_record,
            "bank_record": self.bank_record,
            "score": round(self.score, 4),
            "status": self.status,
            "exception_type": self.exception_type,
            "investigation": self.investigation.to_dict() if self.investigation else None,
            "policy_decision": self.policy_decision.to_dict() if self.policy_decision else None,
            "action_execution": self.action_execution.to_dict() if self.action_execution else None,
            "verification": self.verification.to_dict() if self.verification else None,
            "audit_history": [e.to_dict() for e in self.audit_history],
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }
