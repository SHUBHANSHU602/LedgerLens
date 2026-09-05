"""Reconciliation Agent Orchestrator managing the stateful agent execution loop."""

import uuid
from datetime import datetime, timezone
from dataclasses import dataclass, field, asdict
from typing import Dict, Any, List, Optional
import pandas as pd

from src.agent.models import (
    CaseState,
    ReconciliationCase,
    ActionType,
    AuditEvent,
)
from src.agent.policy import PolicyEngine
from src.agent.actions import ActionService
from src.agent.investigator import ExceptionInvestigator
from src.reconciliation import reconcile
from src.services.finance_controller import _classify_exception


@dataclass
class AgentRunSummary:
    """Comprehensive summary produced by a full ReconciliationAgent execution loop."""
    run_id: str
    batch_status: str
    total_cases: int = 0
    resolved_count: int = 0
    auto_resolved_count: int = 0
    fee_adjusted_count: int = 0
    pending_approval_count: int = 0
    unmatched_count: int = 0
    verification_pass_rate: float = 1.0
    audit_events_count: int = 0
    summary_markdown: str = ""
    cases: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class ReconciliationAgent:
    """Bounded, production-minded Financial Reconciliation Agent.

    Executes the full agent loop:
    OBSERVE -> NORMALIZE -> RECONCILE -> INVESTIGATE -> POLICY CHECK -> ACT -> VERIFY -> AUDIT
    """

    def __init__(
        self,
        policy_engine: Optional[PolicyEngine] = None,
        action_service: Optional[ActionService] = None,
        investigator: Optional[ExceptionInvestigator] = None,
    ):
        self.policy_engine = policy_engine or PolicyEngine()
        self.action_service = action_service or ActionService()
        self.investigator = investigator or ExceptionInvestigator(policy_engine=self.policy_engine)
        self.cases: Dict[str, ReconciliationCase] = {}

    def observe_and_reconcile(
        self,
        df_ledger: pd.DataFrame,
        df_bank: pd.DataFrame,
        run_id: Optional[str] = None,
    ) -> AgentRunSummary:
        """Run the complete agent pipeline over input ledger and bank datasets."""
        if run_id is None:
            run_id = f"RUN-{uuid.uuid4().hex[:8].upper()}"

        # 1. OBSERVE & NORMALIZE: Run underlying deterministic matching core
        df_results = reconcile(df_ledger, df_bank)
        self.cases.clear()

        # Build bank record lookup keyed by utr_reference for O(1) row retrieval
        if "utr_reference" in df_bank.columns:
            bank_lookup: dict = df_bank.set_index("utr_reference").to_dict("index")
        else:
            bank_lookup = {}

        # 2. INITIALIZE CASES
        for idx, row in df_results.iterrows():
            l_id = str(row.get("ledger_id", ""))
            b_id = str(row.get("bank_id", ""))
            case_id = f"CASE-{uuid.uuid4().hex[:8].upper()}"

            status = str(row.get("status", "UNMATCHED"))
            score = float(row.get("score", 0.0))
            rule = str(row.get("matching_rule", ""))

            # Map initial state
            if status == "MATCHED":
                init_state = CaseState.MATCHED
            elif status == "REVIEW":
                init_state = CaseState.AMBIGUOUS
            else:
                init_state = CaseState.UNMATCHED

            # Classify exception type
            exc_obj = _classify_exception(row)
            exc_type = exc_obj.exception_type if exc_obj else "NONE"

            # Reconstruct evidence dictionary
            evidence = {
                "score": score,
                "matching_rule": rule,
                "amount_difference": float(row.get("amount_difference", 0.0)),
                "date_difference": int(row.get("date_difference", 0)),
                "decision_source": str(row.get("decision_source", "deterministic")),
            }

            ledger_row_data = row.to_dict()

            # Populate bank_record with actual bank data (not just the bank_id string)
            if b_id and b_id in bank_lookup:
                bank_row_data = dict(bank_lookup[b_id])
                bank_row_data["utr_reference"] = b_id  # ensure key is present
            else:
                bank_row_data = {"utr_reference": b_id, "bank_id": b_id}

            # Populate candidates for REVIEW cases where AI hasn't already processed them.
            # This activates the ExceptionInvestigator AI re-investigation path.
            decision_source = str(row.get("decision_source", "deterministic"))
            if status == "REVIEW" and decision_source != "groq" and b_id and b_id in bank_lookup:
                # Construct a minimal candidate tuple: (score, b_id, bank_row, breakdown_dict)
                candidates_for_case = [{
                    "score": score,
                    "utr_reference": b_id,
                    "bank_row": bank_row_data,
                    "breakdown": {
                        "ref": float(row.get("original_score", score)),
                        "amount": 0.0,
                        "date": 0.0,
                        "text": 0.0,
                    },
                }]
            else:
                candidates_for_case = []

            case = ReconciliationCase(
                case_id=case_id,
                ledger_id=l_id,
                bank_id=b_id,
                state=init_state,
                ledger_record=ledger_row_data,
                bank_record=bank_row_data,
                candidates=candidates_for_case,
                score=score,
                status=status,
                exception_type=exc_type,
                evidence=evidence,
            )

            case.transition_to(
                init_state,
                actor="RECONCILIATION_ENGINE",
                event_type="CASE_INITIALIZED",
                details={"matching_rule": rule, "score": score},
            )
            self.cases[case_id] = case

        # 3. INVESTIGATE & APPLY POLICY TO EACH CASE
        resolved_cnt = 0
        auto_resolved_cnt = 0
        fee_adjusted_cnt = 0
        pending_approval_cnt = 0
        unmatched_cnt = 0
        verified_cnt = 0
        total_actions = 0

        for case_id, case in self.cases.items():
            if case.state == CaseState.MATCHED:
                # High confidence auto-matched
                policy_dec = self.policy_engine.evaluate(case)
                case.policy_decision = policy_dec

                if policy_dec.allowed and not policy_dec.requires_approval:
                    exec_res, verif_res = self.action_service.execute_and_verify(
                        case, action_type=policy_dec.action_type
                    )
                    resolved_cnt += 1
                    auto_resolved_cnt += 1
                    if verif_res.verified:
                        verified_cnt += 1
                    total_actions += 1

            elif case.state == CaseState.UNMATCHED:
                policy_dec = self.policy_engine.evaluate(case)
                case.policy_decision = policy_dec
                exec_res, verif_res = self.action_service.execute_and_verify(
                    case, action_type=ActionType.MARK_UNMATCHED.value
                )
                unmatched_cnt += 1
                if verif_res.verified:
                    verified_cnt += 1
                total_actions += 1

            elif case.state == CaseState.AMBIGUOUS:
                # Transition to INVESTIGATING
                case.transition_to(
                    CaseState.INVESTIGATING,
                    actor="AGENT",
                    event_type="INVESTIGATION_STARTED",
                )

                # Investigate
                investigation = self.investigator.investigate(case)
                case.investigation = investigation
                case.transition_to(
                    CaseState.RECOMMENDATION_READY,
                    actor="EXCEPTION_INVESTIGATOR",
                    event_type="RECOMMENDATION_FORMULATED",
                    details={"recommended_action": investigation.recommended_action},
                )

                # Policy Check
                policy_dec = self.policy_engine.evaluate(case, investigation)
                case.policy_decision = policy_dec

                if policy_dec.allowed and not policy_dec.requires_approval:
                    case.transition_to(
                        CaseState.POLICY_APPROVED,
                        actor="POLICY_ENGINE",
                        event_type="POLICY_APPROVED",
                        details={"policy_code": policy_dec.policy_code},
                    )
                    exec_res, verif_res = self.action_service.execute_and_verify(
                        case, action_type=policy_dec.action_type
                    )
                    if policy_dec.action_type == ActionType.CREATE_FEE_ADJUSTMENT.value:
                        fee_adjusted_cnt += 1
                    resolved_cnt += 1
                    auto_resolved_cnt += 1
                    if verif_res.verified:
                        verified_cnt += 1
                    total_actions += 1
                else:
                    case.transition_to(
                        CaseState.ACTION_PENDING_APPROVAL,
                        actor="POLICY_ENGINE",
                        event_type="APPROVAL_REQUIRED",
                        details={"reason": policy_dec.reason},
                    )
                    pending_approval_cnt += 1

        # Calculate metrics
        total = len(self.cases)
        verif_rate = (verified_cnt / total_actions) if total_actions > 0 else 1.0
        batch_status = "READY_TO_CLOSE" if pending_approval_cnt == 0 else "REVIEW_REQUIRED"

        audit_cnt = sum(len(c.audit_history) for c in self.cases.values())

        summary_md = (
            f"### Agent Execution Summary for {run_id}\n\n"
            f"- **Total Cases**: {total}\n"
            f"- **Resolved**: {resolved_cnt} (Auto: {auto_resolved_cnt}, Fee Adjustments: {fee_adjusted_cnt})\n"
            f"- **Pending Human Approval**: {pending_approval_cnt}\n"
            f"- **Unmatched**: {unmatched_cnt}\n"
            f"- **Verification Pass Rate**: {verif_rate * 100:.1f}%\n"
            f"- **Audit Events Logged**: {audit_cnt}\n"
        )

        return AgentRunSummary(
            run_id=run_id,
            batch_status=batch_status,
            total_cases=total,
            resolved_count=resolved_cnt,
            auto_resolved_count=auto_resolved_cnt,
            fee_adjusted_count=fee_adjusted_cnt,
            pending_approval_count=pending_approval_cnt,
            unmatched_count=unmatched_cnt,
            verification_pass_rate=round(verif_rate, 4),
            audit_events_count=audit_cnt,
            summary_markdown=summary_md,
            cases=[c.to_dict() for c in self.cases.values()],
        )
