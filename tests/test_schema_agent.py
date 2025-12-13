from app.data_pipe.schema_agent import SchemaAgent


def test_schema_agent_deterministic_same_input_same_output(tmp_path):
    agent = SchemaAgent()
    headers = ["Name", "Amount"]
    first = agent.build_schema(headers)
    second = agent.build_schema(headers)
    assert first.dict() == second.dict()


def test_schema_agent_duplicate_headers_suffixing(tmp_path):
    agent = SchemaAgent()
    schema = agent.build_schema(["name", "Name", "NAME"])
    canonical = [c.canonical_name for c in schema.columns]
    assert canonical == sorted(canonical)
    assert len(set(canonical)) == len(canonical)
