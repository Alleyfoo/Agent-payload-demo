import pandas as pd

from app.data_pipe.models import ColumnSpec, SchemaSpec
from app.data_pipe.transform_agent import TransformAgent


def test_transform_agent_missing_required_reported():
    schema = SchemaSpec(
        schema_id="s1",
        version=1,
        columns=[
            ColumnSpec(raw_name="A", canonical_name="a", dtype="int", required=True, notes=""),
            ColumnSpec(raw_name="B", canonical_name="b", dtype="string", required=False, notes=""),
        ],
        unmapped_columns=[],
        warnings=[],
    )
    df = pd.DataFrame([{"A": "x", "B": "ok"}])
    agent = TransformAgent()
    _, report = agent.apply(df, schema)
    assert "a" in report.casts_failed
    assert "a" in report.missing_required
