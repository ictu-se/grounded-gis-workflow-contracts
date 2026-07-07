#!/usr/bin/env python3
"""Build full benchmark summary tables for the grounded GIS workflow experiment."""

from __future__ import annotations

import csv
from collections import defaultdict
from pathlib import Path
from statistics import mean


ROOT = Path(__file__).resolve().parents[3]
EXP = ROOT / "experiments/07_grounded_gis_workflow_benchmark"
SCORE_ROOT = EXP / "outputs/scores"
MANUSCRIPT_TABLES = ROOT / "manuscripts/04_q1_grounded_gis_workflow_benchmark/tables"

METRICS = [
    "JSON_VALID",
    "TOOL_VALID",
    "DATA_VALID",
    "FIELD_VALID",
    "CRS_PLAN",
    "SCHEMA_PLAN",
    "MAP_PLAN",
    "OUTPUT_NAME",
    "PHR",
    "WPHR",
    "PRS",
]

FAILURE_RULES = {
    "json_invalid": lambda r: float(r["JSON_VALID"]) < 1,
    "tool_invalid": lambda r: float(r["JSON_VALID"]) >= 1 and float(r["TOOL_VALID"]) < 1,
    "data_invalid": lambda r: float(r["JSON_VALID"]) >= 1 and float(r["DATA_VALID"]) < 1,
    "field_weak": lambda r: float(r["JSON_VALID"]) >= 1 and float(r["FIELD_VALID"]) < 1,
    "crs_weak": lambda r: float(r["JSON_VALID"]) >= 1 and float(r["CRS_PLAN"]) < 1,
    "schema_weak": lambda r: float(r["JSON_VALID"]) >= 1 and float(r["SCHEMA_PLAN"]) < 1,
    "map_plan_weak": lambda r: float(r["JSON_VALID"]) >= 1 and float(r["MAP_PLAN"]) < 1,
    "output_name_wrong": lambda r: float(r["JSON_VALID"]) >= 1 and float(r["OUTPUT_NAME"]) < 1,
}


def read_task_rows() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for path in sorted(SCORE_ROOT.glob("*/workflow_task_scores.csv")):
        with path.open(newline="", encoding="utf-8") as f:
            rows.extend(csv.DictReader(f))
    return rows


def grouped(rows: list[dict[str, str]], keys: list[str]) -> list[dict[str, str]]:
    buckets: dict[tuple[str, ...], list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        buckets[tuple(row[k] for k in keys)].append(row)
    out = []
    for key, items in sorted(buckets.items()):
        record = {k: v for k, v in zip(keys, key)}
        for metric in METRICS:
            record[metric] = f"{mean(float(r[metric]) for r in items):.4f}"
        record["tasks"] = str(len(items))
        out.append(record)
    return out


def failure_rows(rows: list[dict[str, str]], keys: list[str]) -> list[dict[str, str]]:
    buckets: dict[tuple[str, ...], list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        buckets[tuple(row[k] for k in keys)].append(row)
    out = []
    for key, items in sorted(buckets.items()):
        record = {k: v for k, v in zip(keys, key)}
        for failure, rule in FAILURE_RULES.items():
            record[failure] = str(sum(1 for r in items if rule(r)))
        record["tasks"] = str(len(items))
        out.append(record)
    return out


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_md(path: Path, rows: list[dict[str, str]], columns: list[str], title: str) -> None:
    lines = [f"# {title}", ""]
    if not rows:
        lines.append("No rows.")
    else:
        lines.append("|" + "|".join(columns) + "|")
        lines.append("|" + "|".join(["---"] * len(columns)) + "|")
        for row in rows:
            lines.append("|" + "|".join(row.get(c, "") for c in columns) + "|")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    rows = read_task_rows()
    mode_summary = grouped(rows, ["mode"])
    model_mode_summary = grouped(rows, ["model", "mode"])
    category_mode_summary = grouped(rows, ["task_type", "mode"])
    category_model_mode_summary = grouped(rows, ["task_type", "model", "mode"])
    failure_mode_summary = failure_rows(rows, ["mode"])
    failure_category_mode_summary = failure_rows(rows, ["task_type", "mode"])

    outputs = [
        ("full_mode_summary", mode_summary, ["mode", *METRICS, "tasks"], "Full Mode Summary"),
        ("full_model_mode_summary", model_mode_summary, ["model", "mode", "JSON_VALID", "DATA_VALID", "FIELD_VALID", "CRS_PLAN", "MAP_PLAN", "WPHR", "PRS", "tasks"], "Full Model Mode Summary"),
        ("full_category_mode_summary", category_mode_summary, ["task_type", "mode", "JSON_VALID", "DATA_VALID", "FIELD_VALID", "CRS_PLAN", "MAP_PLAN", "WPHR", "PRS", "tasks"], "Full Category Mode Summary"),
        ("full_failure_mode_summary", failure_mode_summary, ["mode", *FAILURE_RULES.keys(), "tasks"], "Full Failure Mode Summary"),
        ("full_failure_category_mode_summary", failure_category_mode_summary, ["task_type", "mode", *FAILURE_RULES.keys(), "tasks"], "Full Failure Category Mode Summary"),
    ]

    for stem, table, columns, title in outputs:
        write_csv(SCORE_ROOT / f"{stem}.csv", table)
        write_md(SCORE_ROOT / f"{stem}.md", table, columns, title)
        write_csv(MANUSCRIPT_TABLES / f"{stem}.csv", table)
        write_md(MANUSCRIPT_TABLES / f"{stem}.md", table, columns, title)

    write_csv(SCORE_ROOT / "full_category_model_mode_summary.csv", category_model_mode_summary)
    write_csv(MANUSCRIPT_TABLES / "full_category_model_mode_summary.csv", category_model_mode_summary)

    print(f"Read {len(rows)} task-score rows")
    print(f"Wrote summaries to {SCORE_ROOT.relative_to(ROOT)}")
    print(f"Mirrored summaries to {MANUSCRIPT_TABLES.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
