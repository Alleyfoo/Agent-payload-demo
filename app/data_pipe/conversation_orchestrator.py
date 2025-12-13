from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

import pandas as pd

from app.data_pipe.data_pipe_state import DataPipePhase
from app.data_pipe.data_session_store import DataPipeSessionStore, DataPipeSession
from app.data_pipe.models import RunResult, SaveReport, SchemaSpec
from app.data_pipe.save_agent import SaveAgent, _default_allow_root
from app.data_pipe.schema_agent import SchemaAgent
from app.data_pipe.transform_agent import TransformAgent


def _extract_first_json_object(text: str) -> Dict[str, object]:
    try:
        first_brace = text.index("{")
        snippet = text[first_brace:]
        depth = 0
        collected = ""
        for ch in snippet:
            if ch == "{":
                depth += 1
            if ch == "}":
                depth -= 1
            collected += ch
            if depth == 0:
                break
        return json.loads(collected)
    except Exception:
        return {}


def _build_chat_summary(run_id: str, schema: SchemaSpec, transform_rows_in: int, transform_report: Dict[str, Any], input_path: Path, output_dir: str) -> str:
    lines = []
    lines.append(f"Run {run_id}: luettiin {input_path.name}, rivit: {transform_rows_in}.")
    lines.append(f"Schema: {len(schema.columns)} saraketta mapattiin, unmapped: {len(schema.unmapped_columns)}.")
    if schema.warnings:
        lines.append("Schema-varoitukset: " + "; ".join(schema.warnings[:3]))
    warnings = transform_report.get("warnings") or []
    casts_failed = transform_report.get("casts_failed") or {}
    missing_required = transform_report.get("missing_required") or []
    if warnings:
        lines.append("Muunnosvaroitukset: " + "; ".join(warnings[:3]))
    if casts_failed:
        lines.append("Cast-epäonnistumiset: " + ", ".join(f"{k}={v}" for k, v in casts_failed.items()))
    if missing_required:
        lines.append("Puuttuvia pakollisia: " + ", ".join(missing_required))
    lines.append(f"Tallennettu kansioon: {output_dir}.")
    return "\n".join(lines)


class DataPipeConversationOrchestrator:
    def __init__(self, store: DataPipeSessionStore, allow_root: Path | None = None) -> None:
        self.store = store
        self.allow_root = (allow_root or _default_allow_root()).resolve()

    def _guard_output_dir(self, output_dir: Path) -> Path | None:
        try:
            resolved = output_dir.resolve()
        except Exception:
            return None
        if not str(resolved).startswith(str(self.allow_root)):
            return None
        return resolved

    def _response(
        self,
        session: DataPipeSession,
        run_id: str,
        content: str,
        output_path: str | None = None,
    ) -> Dict[str, Any]:
        return {
            "run_id": run_id,
            "content": content,
            "state": {"phase": session.phase.value, "run_id": run_id},
            "header_plan": session.header_plan,
            "transform_plan": session.transform_plan,
            "preview_report": session.preview_report,
            "save_report": session.save_report,
            "output_path": output_path or session.output_path,
        }

    def handle(self, run_id: str, user_message: str) -> Dict[str, Any]:
        payload = _extract_first_json_object(user_message)
        if not isinstance(payload, dict):
            payload = {}

        payload_run_id = payload.get("run_id")
        if isinstance(payload_run_id, str) and payload_run_id.strip():
            run_id = payload_run_id

        action = (payload.get("action") or "").strip().lower()
        session = self.store.ensure(run_id)

        if action == "reset":
            self.store.reset(run_id)
            session = self.store.ensure(run_id)
            return self._response(session, run_id, "Data pipe -sessio nollattu.", output_path=None)

        if action == "status":
            fields = {
                "header_plan": bool(session.header_plan),
                "transform_plan": bool(session.transform_plan),
                "preview_report": bool(session.preview_report),
                "save_report": bool(session.save_report),
                "input_path": session.input_path,
                "output_path": session.output_path,
            }
            return self._response(session, run_id, f"Nykyinen vaihe: {session.phase.value}. Kentät: {fields}", output_path=session.output_path)

        if action == "start":
            input_path = payload.get("input_path")
            output_dir = payload.get("output_dir")
            preview_rows = int(payload.get("preview_rows") or 20)
            synonyms_path = payload.get("synonyms_path")
            schema_hints_path = payload.get("schema_hints_path")
            if not input_path or not output_dir:
                session.phase = DataPipePhase.IDLE
                return self._response(
                    session,
                    run_id,
                    'Anna input_path ja output_dir. Esim: {"action":"start","input_path":"/polku/in.xlsx","output_dir":"/tmp/out"}',
                )
            guard = self._guard_output_dir(Path(output_dir))
            if guard is None:
                session.phase = DataPipePhase.IDLE
                return self._response(session, run_id, f"output_dir {output_dir} ei sallittu (sallittu juuripolku {self.allow_root}).")
            try:
                preview_df = pd.read_excel(input_path, nrows=preview_rows)
            except Exception as exc:
                session.phase = DataPipePhase.IDLE
                return self._response(session, run_id, f"Excelin luku epäonnistui: {exc}")

            headers = list(preview_df.columns)
            schema_agent = SchemaAgent(
                synonyms_path=Path(synonyms_path) if synonyms_path else None,
                schema_hints_path=Path(schema_hints_path) if schema_hints_path else None,
            )
            schema = schema_agent.build_schema(headers)
            rename_map = {c.raw_name: c.canonical_name for c in schema.columns}

            session.input_path = str(input_path)
            session.output_path = str(guard)
            session.df_preview = preview_df.head(preview_rows).to_dict("records")
            session.header_plan = {"headers": headers, "rename_map": rename_map, "schema": schema.model_dump()}
            session.transform_plan = None
            session.preview_report = None
            session.save_report = None
            session.phase = DataPipePhase.HEADERS_PROPOSED_WAITING_CONFIRM
            self.store.upsert(session)

            summary = f"Löydettiin {len(headers)} headeria. Schema valmis. Lähetä action=confirm_headers jos ok."
            return self._response(session, run_id, summary)

        if action == "confirm_headers":
            if session.phase != DataPipePhase.HEADERS_PROPOSED_WAITING_CONFIRM or not session.header_plan:
                return self._response(session, run_id, "Ei header-suunnitelmaa vahvistettavaksi.")
            schema = SchemaSpec.model_validate(session.header_plan.get("schema"))
            df_preview = pd.DataFrame(session.df_preview or [])
            transform_agent = TransformAgent()
            df_out, report = transform_agent.apply(df_preview, schema)
            sample_rows = df_out.head(5).to_dict("records")

            session.transform_plan = {"sample_rows": sample_rows}
            session.preview_report = report.model_dump()
            session.save_report = None
            session.phase = DataPipePhase.TRANSFORM_PROPOSED_WAITING_CONFIRM
            self.store.upsert(session)

            summary = f"Transform preview valmis {len(sample_rows)} riviä. Lähetä action=confirm_transform jos ok."
            return self._response(session, run_id, summary)

        if action in {"confirm_transform", "save"}:
            if session.phase != DataPipePhase.TRANSFORM_PROPOSED_WAITING_CONFIRM or not session.header_plan:
                return self._response(session, run_id, "Ei transform-suunnitelmaa vahvistettavaksi.")
            if not session.input_path or not session.output_path:
                return self._response(session, run_id, "Puuttuva input/output polku tallennukseen.")
            try:
                df_full = pd.read_excel(session.input_path)
            except Exception as exc:
                return self._response(session, run_id, f"Datan luku epäonnistui: {exc}")

            schema = SchemaSpec.model_validate(session.header_plan.get("schema"))
            transform_agent = TransformAgent()
            df_out, report = transform_agent.apply(df_full, schema)

            provisional = RunResult(
                run_id=run_id,
                schema=schema,
                transform=report,
                save=SaveReport(saved_files=[], output_dir=session.output_path),
                chat_summary="",
            )
            save_agent = SaveAgent(allow_root=self.allow_root)
            save_report = save_agent.save(df_out, provisional, Path(session.output_path))
            session.output_path = save_report.output_dir
            session.save_report = save_report.model_dump()
            session.phase = DataPipePhase.DONE
            self.store.upsert(session)

            chat_summary = _build_chat_summary(run_id, schema, len(df_full), report.model_dump(), Path(session.input_path), save_report.output_dir)
            content = chat_summary + "\n" + json.dumps(save_report.model_dump(), ensure_ascii=False)
            return self._response(session, run_id, content, output_path=save_report.output_dir)

        return self._response(session, run_id, "Tuntematon action. Käytä start|confirm_headers|confirm_transform|save|status|reset.")
