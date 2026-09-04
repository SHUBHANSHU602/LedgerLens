"""Typed schemas and data models for LedgerLens reconciliation system."""

from dataclasses import dataclass, asdict, field
from typing import Dict, Any, Optional, List


@dataclass
class EvidenceBreakdown:
    """Breakdown of individual evidence scores for candidate evaluation."""
    ref: float = 0.0
    amount: float = 0.0
    date: float = 0.0
    text: float = 0.5

    def to_dict(self) -> Dict[str, float]:
        return asdict(self)


@dataclass
class ReconciliationRecord:
    """Structured reconciliation result output record."""
    ledger_id: str
    bank_id: str
    status: str
    matching_rule: str
    score: float
    reason: str
    decision_source: str = "deterministic"
    model_used: str = "none"
    ai_reason: str = ""
    original_score: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "ledger_id": self.ledger_id,
            "bank_id": self.bank_id,
            "status": self.status,
            "matching_rule": self.matching_rule,
            "score": round(self.score, 4),
            "reason": self.reason,
            "decision_source": self.decision_source,
            "model_used": self.model_used,
            "ai_reason": self.ai_reason,
            "original_score": round(self.original_score, 4),
        }


@dataclass
class CandidateBank:
    """Structure representing a candidate bank statement match."""
    score: float
    utr_reference: str
    bank_row: Dict[str, Any]
    breakdown: EvidenceBreakdown


@dataclass
class EvaluationMetrics:
    """Metrics summary produced by evaluation benchmark against ground truth."""
    total_rows: int
    handled_without_ai: int
    sent_to_ai: int
    matches: int
    reviews: int
    unmatched: int
    true_positives: int
    false_positives: int
    false_negatives: int
    true_negatives: int
    precision: float
    recall: float
    f1_score: float
    auto_match_rate: float
    review_rate: float
    unmatched_rate: float
    ai_examples: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
