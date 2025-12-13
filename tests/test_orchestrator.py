import pandas as pd

from app.data_pipe.orchestrator import run_data_pipe


def test_orchestrator_returns_chat_summary(tmp_path):
    input_path = tmp_path / "in.xlsx"
    df = pd.DataFrame([{"Name": "Alice", "Amount": 10}])
    df.to_excel(input_path, index=False)
    output_dir = tmp_path / "out"

    result = run_data_pipe(str(input_path), str(output_dir))

    assert result.chat_summary
    assert "Tallennettu" in result.chat_summary or "Tallennettu kansioon" in result.chat_summary
    assert result.save.saved_files
