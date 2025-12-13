from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Optional

from app.data_pipe.data_pipe_state import DataPipePhase


@dataclass
class DataPipeSession:
    run_id: str
    input_path: Optional[str] = None
    output_path: Optional[str] = None
    df_preview: Any = None
    header_plan: Dict[str, Any] | None = None
    transform_plan: Dict[str, Any] | None = None
    preview_report: Dict[str, Any] | None = None
    save_report: Dict[str, Any] | None = None
    phase: DataPipePhase = DataPipePhase.IDLE


class DataPipeSessionStore:
    def __init__(self) -> None:
        self._sessions: Dict[str, DataPipeSession] = {}

    def get(self, run_id: str) -> Optional[DataPipeSession]:
        return self._sessions.get(run_id)

    def upsert(self, session: DataPipeSession) -> DataPipeSession:
        self._sessions[session.run_id] = session
        return session

    def update_phase(self, run_id: str, phase: DataPipePhase) -> None:
        if run_id in self._sessions:
            self._sessions[run_id].phase = phase

    def ensure(self, run_id: str) -> DataPipeSession:
        if run_id not in self._sessions:
            self._sessions[run_id] = DataPipeSession(run_id=run_id, phase=DataPipePhase.IDLE)
        return self._sessions[run_id]

    def reset(self, run_id: str) -> None:
        if run_id in self._sessions:
            del self._sessions[run_id]
