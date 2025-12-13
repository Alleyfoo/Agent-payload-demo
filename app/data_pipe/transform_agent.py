from __future__ import annotations

from typing import Dict, List, Tuple

import pandas as pd

from app.data_pipe.models import SchemaSpec, TransformReport


class TransformAgent:
    """Schema-driven deterministic transform."""

    def apply(self, df: pd.DataFrame, schema: SchemaSpec) -> Tuple[pd.DataFrame, TransformReport]:
        rename_map = {c.raw_name: c.canonical_name for c in schema.columns}
        df_named = df.rename(columns=rename_map)
        casts_failed: Dict[str, int] = {}

        for col in schema.columns:
            if col.canonical_name not in df_named.columns:
                continue
            series = df_named[col.canonical_name]
            if col.dtype == "int":
                casted = pd.to_numeric(series, errors="coerce")
                fail_count = int(casted.isna().sum()) - int(series.isna().sum())
                df_named[col.canonical_name] = casted.astype("Int64")
                casts_failed[col.canonical_name] = max(fail_count, 0)
            elif col.dtype == "float":
                casted = pd.to_numeric(series, errors="coerce")
                fail_count = int(casted.isna().sum()) - int(series.isna().sum())
                df_named[col.canonical_name] = casted
                casts_failed[col.canonical_name] = max(fail_count, 0)
            elif col.dtype == "bool":
                df_named[col.canonical_name] = series.astype(str).str.lower().isin({"true", "1", "yes"})
            elif col.dtype == "date":
                df_named[col.canonical_name] = pd.to_datetime(series, errors="coerce")
                casts_failed[col.canonical_name] = int(df_named[col.canonical_name].isna().sum()) - int(series.isna().sum())
            else:
                df_named[col.canonical_name] = series.astype(str)

        missing_required: List[str] = []
        for col in schema.columns:
            if col.required and col.canonical_name in df_named.columns:
                if df_named[col.canonical_name].isna().any():
                    missing_required.append(col.canonical_name)
        warnings: List[str] = []
        if missing_required:
            warnings.append("required_columns_missing_values")
        report = TransformReport(
            rows_in=len(df),
            rows_out=len(df_named),
            casts_failed={k: v for k, v in casts_failed.items() if v > 0},
            missing_required=missing_required,
            warnings=warnings,
        )
        return df_named, report
