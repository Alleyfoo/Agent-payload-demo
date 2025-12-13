from __future__ import annotations

import uuid
from pathlib import Path
from typing import Optional

import pandas as pd

from app.data_pipe.models import RunResult, SaveReport, SchemaSpec, TransformReport
from app.data_pipe.save_agent import SaveAgent
from app.data_pipe.schema_agent import SchemaAgent
from app.data_pipe.transform_agent import TransformAgent


def _build_chat_summary(run_id: str, schema: SchemaSpec, transform: TransformReport, save: SaveReport, input_path: Path) -> str:
    lines = []
    lines.append(f"Run {run_id}: luettiin {input_path.name}, rivit: {transform.rows_in}.")
    lines.append(f"Schema: {len(schema.columns)} saraketta mapattiin, unmapped: {len(schema.unmapped_columns)}.")
    if schema.warnings:
        lines.append("Schema-varoitukset: " + "; ".join(schema.warnings[:3]))
    if transform.warnings:
        lines.append("Muunnosvaroitukset: " + "; ".join(transform.warnings[:3]))
    if transform.casts_failed:
        lines.append("Cast-epäonnistumiset: " + ", ".join(f"{k}={v}" for k, v in transform.casts_failed.items()))
    if transform.missing_required:
        lines.append("Puuttuvia pakollisia: " + ", ".join(transform.missing_required))
    lines.append(f"Tallennettu kansioon: {save.output_dir}.")
    return "\n".join(lines)


def run_data_pipe(input_excel_path: str, output_dir: str, schema_hints_path: Optional[str] = None, synonyms_path: Optional[str] = None) -> RunResult:
    run_id = str(uuid.uuid4())
    input_path = Path(input_excel_path)
    df = pd.read_excel(input_path)

    schema_agent = SchemaAgent(
        synonyms_path=Path(synonyms_path) if synonyms_path else Path(__file__).parent / "synonyms.json",
        schema_hints_path=Path(schema_hints_path) if schema_hints_path else None,
    )
    schema = schema_agent.build_schema(list(df.columns))

    transform_agent = TransformAgent()
    df_transformed, transform_report = transform_agent.apply(df, schema)

    # Build provisional RunResult for save
    provisional = RunResult(
        run_id=run_id,
        schema=schema,
        transform=transform_report,
        save=SaveReport(saved_files=[], output_dir=output_dir),
        chat_summary="",
    )

    save_agent = SaveAgent(allow_root=Path(output_dir))
    save_report = save_agent.save(df_transformed, provisional, Path(output_dir))

    chat_summary = _build_chat_summary(run_id, schema, transform_report, save_report, input_path)
    final_result = RunResult(
        run_id=run_id,
        schema=schema,
        transform=transform_report,
        save=save_report,
        chat_summary=chat_summary,
    )
    return final_result
