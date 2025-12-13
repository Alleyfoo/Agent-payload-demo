from __future__ import annotations

import json
from pathlib import Path

from app.circuits.comparison_judge import ComparisonJudge


def main() -> None:
    path = Path("data/shadow_reports.jsonl")
    if not path.exists():
        print("No shadow_reports.jsonl found.")
        return

    for line in path.read_text().splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        if record.get("kind") != "comparison":
            continue
        alternatives = record.get("alternatives", [])
        mode = record.get("mode") or "create"
        deliverable_ids = record.get("deliverable_ids") or []
        judge = ComparisonJudge(mode=mode, deliverable_ids=deliverable_ids)
        result = judge.evaluate(alternatives)
        existing = record.get("gate_violations", {})
        if existing != result.gate_violations:
            print(f"Run {record.get('run_id')} has gate mismatch:")
            print(" existing:", existing)
            print(" computed:", result.gate_violations)


if __name__ == "__main__":
    main()
