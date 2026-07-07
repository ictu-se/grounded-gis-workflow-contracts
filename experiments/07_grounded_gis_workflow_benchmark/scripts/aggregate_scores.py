#!/usr/bin/env python3
"""Aggregate per-model workflow benchmark summaries."""

from __future__ import annotations

import csv
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
SCORE_ROOT = ROOT / "experiments/07_grounded_gis_workflow_benchmark/outputs/scores"
OUT_CSV = SCORE_ROOT / "model_comparison_summary.csv"
OUT_MD = SCORE_ROOT / "model_comparison_summary.md"


def read_rows() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for path in sorted(SCORE_ROOT.glob("*/workflow_summary.csv")):
        with path.open(newline="", encoding="utf-8") as f:
            rows.extend(csv.DictReader(f))
    return rows


def write_csv(rows: list[dict[str, str]]) -> None:
    if not rows:
        return
    with OUT_CSV.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def write_markdown(rows: list[dict[str, str]]) -> None:
    if not rows:
        OUT_MD.write_text("# Model Comparison Summary\n\nNo rows found.\n", encoding="utf-8")
        return
    columns = ["model", "mode", "JSON_VALID", "TOOL_VALID", "DATA_VALID", "FIELD_VALID", "CRS_PLAN", "SCHEMA_PLAN", "MAP_PLAN", "OUTPUT_NAME", "PHR", "WPHR", "PRS", "tasks"]
    lines = ["# Model Comparison Summary", "", "|" + "|".join(columns) + "|", "|" + "|".join(["---"] * len(columns)) + "|"]
    for row in sorted(rows, key=lambda r: (r["model"], r["mode"])):
        lines.append("|" + "|".join(row.get(c, "") for c in columns) + "|")
    OUT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    SCORE_ROOT.mkdir(parents=True, exist_ok=True)
    rows = read_rows()
    write_csv(rows)
    write_markdown(rows)
    print(f"Wrote {OUT_CSV.relative_to(ROOT)}")
    print(f"Wrote {OUT_MD.relative_to(ROOT)}")


if __name__ == "__main__":
    main()

