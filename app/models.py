from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import json
from typing import Any, Dict, List, Optional
from typing import Literal
import uuid


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
    revision_number: int = 0
    revision_history: List[Dict[str, Any]] = field(default_factory=list)


@dataclass
class ReviewReport:
    format_ok: bool
    internal_consistency: str
    potential_hallucinations: List[str]
    notes: List[str]
    missing_sections: List[str]
    section_coverage: float


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
    force_guidance: Dict[str, Any] | None = None


@dataclass
class UserResponse:
    run_id: str
    decision: str
    summary: str
    content: Dict[str, Any]
    shadow_report_path: Optional[str]
    revision_summary: Dict[str, Any] = field(default_factory=dict)


# Force Guidance structures
@dataclass
class ForceProfile:
    tension: float = 0.4
    uncertainty: float = 0.45
    inertia: float = 0.45
    polarity: float = 0.0
    agency: float = 0.6

    def as_dict(self) -> Dict[str, float]:
        return {
            "tension": self.tension,
            "uncertainty": self.uncertainty,
            "inertia": self.inertia,
            "polarity": self.polarity,
            "agency": self.agency,
        }


@dataclass
class ForceLever:
    name: str
    rationale: str
    first_step: str

    def as_dict(self) -> Dict[str, Any]:
        return {"name": self.name, "rationale": self.rationale, "first_step": self.first_step}


@dataclass
class ForceGuidance:
    situation_summary: str
    primary_lever: ForceLever
    adjacent_options: List[ForceLever]
    profile: ForceProfile
    reason_codes: List[str]
    state_pattern: str

    def as_dict(self) -> Dict[str, Any]:
        return {
            "situation_summary": self.situation_summary,
            "primary_lever": self.primary_lever.as_dict(),
            "adjacent_options": [opt.as_dict() for opt in self.adjacent_options],
            "profile": self.profile.as_dict(),
            "reason_codes": list(self.reason_codes),
            "state_pattern": self.state_pattern,
        }

    def as_json(self) -> str:
        return json.dumps(self.as_dict(), ensure_ascii=False, separators=(",", ":"))


@dataclass
class EnergyVector:
    tension: float = 0.5
    entropy: float = 0.5
    polarity: float = 0.0
    coherence: float = 0.5

    @classmethod
    def infer(cls, text: str) -> "EnergyVector":
        """Very small heuristic to infer energy from text shape."""
        length = len(text)
        exclamations = text.count("!")
        questions = text.count("?")
        capital_words = sum(1 for token in text.split() if token.isupper())

        tension = min(1.0, 0.3 + 0.1 * exclamations + 0.001 * length + 0.02 * capital_words)
        entropy = min(1.0, 0.3 + 0.05 * questions + 0.0005 * length)
        polarity = max(-1.0, min(1.0, 0.1 * (exclamations - questions)))
        coherence = max(0.1, min(1.0, 0.9 - 0.05 * questions))

        return cls(
            tension=round(tension, 3),
            entropy=round(entropy, 3),
            polarity=round(polarity, 3),
            coherence=round(coherence, 3),
        )

    def as_dict(self) -> Dict[str, float]:
        return {
            "tension": self.tension,
            "entropy": self.entropy,
            "polarity": self.polarity,
            "coherence": self.coherence,
        }


@dataclass
class HexagramState:
    hexagram_id: Optional[int] = None
    name: str = "neutral"
    archetype: str = "balanced"

    def label(self) -> str:
        return self.name or f"Hexagram {self.hexagram_id or '-'}"


@dataclass
class TaoistIntent:
    intent: str
    energy: EnergyVector
    hexagram: HexagramState


@dataclass
class BuddhistResponse:
    content: str
    role: str
    grounded: bool = True


@dataclass
class PuhemiesHeader:
    task_type: str
    user_intent: str
    required_grounding: bool
    allowed_style: str
    notes: str = ""


@dataclass
class GroundingPlan:
    grounding_status: str
    tool: Optional[str] = None
    location_needed: Optional[str] = None
    fallback_if_no_tool: Optional[str] = None
    do_not_do: List[str] = field(default_factory=list)


@dataclass
class CandidateScores:
    correctness: int = 0
    truth: int = 0
    task_fit: int = 0
    clarity: int = 0
    tone: int = 0
    safety: str = "pass"
    utility: int = 0


@dataclass
class Verdict:
    winner: str
    scores: Dict[str, CandidateScores]
    reason: str
    confidence: float
    ranked: List[str] = field(default_factory=list)
    issues: Dict[str, List[str]] = field(default_factory=dict)
    required_grounding: bool = False
    gate_violations: Dict[str, List[str]] = field(default_factory=dict)


@dataclass
class CandidateOutput:
    agent_id: str
    text: str
    meta: Dict[str, Any]


@dataclass
class BreathingParams:
    pace: float = 0.5        # 0 fast/reactive -> 1 slow/reflective
    softness: float = 0.5    # 0 blunt -> 1 gentle
    initiative: float = 0.5  # 0 passive -> 1 proactive
    grounding: float = 0.5   # 0 freeform -> 1 strictly grounded
    verbosity: float = 0.5   # 0 minimal -> 1 detailed

    def clamp(self) -> "BreathingParams":
        self.pace = min(1.0, max(0.0, self.pace))
        self.softness = min(1.0, max(0.0, self.softness))
        self.initiative = min(1.0, max(0.0, self.initiative))
        self.grounding = min(1.0, max(0.0, self.grounding))
        self.verbosity = min(1.0, max(0.0, self.verbosity))
        return self

    def as_dict(self) -> Dict[str, float]:
        return {
            "pace": self.pace,
            "softness": self.softness,
            "initiative": self.initiative,
            "grounding": self.grounding,
            "verbosity": self.verbosity,
        }


@dataclass
class CorrectionPlan:
    agent_id: str
    intervention: str
    parameter_deltas: Dict[str, float]
    behavioral_constraints: List[str]
    retry: bool


@dataclass
class Deliverable:
    type: str
    description: str
    count: int | None = None


@dataclass
class EvaluationContract:
    task_summary: str
    deliverables: List[Deliverable]
    truth_critical: str
    needs_external_grounding: str
    rubric: Dict[str, float]
    hard_gates: List[str]
    target_expression: Optional[str] = None
    expected_result: Optional[int] = None
    patch_requires_artifact: bool = False
    patch_requires_render: bool = False
    pipeline_required: bool = False
    crypto_sanity_required: bool = False
    math_list_required: bool = False
    extraction_required: bool = False
    force_guidance_required: bool = False
    math_expected_mean: Optional[float] = None
    math_expected_median: Optional[float] = None
    strict_numeric_truth: bool = False
    tip_domain_required: Optional[str] = None
    expected_schema: Optional[List[str]] = None
    force_guidance_schema: Optional[List[str]] = None


@dataclass
class ToolLimits:
    timeout_seconds: int = 15
    max_memory_mb: int = 256
    allow_imports: List[str] = field(default_factory=lambda: ["pandas", "numpy", "math", "re", "json", "datetime", "csv"])
    allow_files: bool = True
    network_enabled: bool = False


@dataclass
class ToolStep:
    step_id: str
    kind: Literal["python", "sql"]
    payload: str
    inputs: Dict[str, Any] = field(default_factory=dict)
    expected_output: Optional[List[str]] = None  # expected columns/keys
    output_artifact_key: str = "output"


@dataclass
class ToolPlan:
    plan_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    steps: List[ToolStep] = field(default_factory=list)
    limits: ToolLimits = field(default_factory=ToolLimits)


@dataclass
class ToolResult:
    success: bool
    stdout: str = ""
    stderr: str = ""
    metrics: Dict[str, Any] = field(default_factory=dict)
    artifacts: Dict[str, Any] = field(default_factory=dict)
    schema_ok: bool = True
    schema_errors: List[str] = field(default_factory=list)
    new_keys: List[str] = field(default_factory=list)
