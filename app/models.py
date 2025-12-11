from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional


@dataclass
class Message:
    run_id: str
    sender: str
    recipient: str
    role: str
    payload: Dict[str, Any]
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())


@dataclass
class TaskSpec:
    run_id: str
    task_type: str
    topic: str
    language: str
    target_level: str
    constraints: List[str]
    status: str


@dataclass
class MethodPlan:
    format: str
    sections: List[str]


@dataclass
class ContentPackage:
    run_id: str
    content: Dict[str, Any]
    method_respected: bool
    warnings: List[str]


@dataclass
class ReviewReport:
    format_ok: bool
    internal_consistency: str
    potential_hallucinations: List[str]
    notes: List[str]


@dataclass
class JudgeDecision:
    decision: str
    reason: str


@dataclass
class CircuitResult:
    task_spec: TaskSpec
    method_plan: MethodPlan
    content: ContentPackage
    review: ReviewReport
    decision: JudgeDecision
    shadow_report: Dict[str, Any]


@dataclass
class UserResponse:
    run_id: str
    decision: str
    summary: str
    content: Dict[str, Any]
    shadow_report_path: Optional[str]
