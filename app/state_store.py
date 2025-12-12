from __future__ import annotations

import json
from pathlib import Path
from typing import Dict

from app.models import BreathingParams

STATE_PATH = Path("agent_state.json")


def load_params() -> Dict[str, BreathingParams]:
    if not STATE_PATH.exists():
        return {}
    try:
        raw = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        params: Dict[str, BreathingParams] = {}
        for aid, cfg in raw.items():
            params[aid] = BreathingParams(
                pace=cfg.get("pace", 0.5),
                softness=cfg.get("softness", 0.5),
                initiative=cfg.get("initiative", 0.5),
                grounding=cfg.get("grounding", 0.5),
                verbosity=cfg.get("verbosity", 0.5),
            ).clamp()
        return params
    except Exception:
        return {}


def save_params(params: Dict[str, BreathingParams]) -> None:
    payload = {aid: bp.as_dict() for aid, bp in params.items()}
    STATE_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
