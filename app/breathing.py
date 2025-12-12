from __future__ import annotations

from typing import Dict

from app.models import BreathingParams


def default_params() -> Dict[str, BreathingParams]:
    return {
        "healing": BreathingParams(pace=0.6, softness=0.7, initiative=0.6, grounding=0.8, verbosity=0.55),
        "selfish": BreathingParams(pace=0.3, softness=0.2, initiative=0.6, grounding=0.2, verbosity=0.35),
    }


def apply_deltas(params: BreathingParams, deltas: Dict[str, float]) -> BreathingParams:
    for k, v in deltas.items():
        if hasattr(params, k):
            setattr(params, k, getattr(params, k) + v)
    return params.clamp()
