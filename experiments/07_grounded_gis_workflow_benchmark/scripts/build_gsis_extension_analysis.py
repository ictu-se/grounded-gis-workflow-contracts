#!/usr/bin/env python3
"""Build GSIS-oriented robustness and execution-readiness analyses."""

from __future__ import annotations

import csv
import argparse
import random
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean


ROOT = Path(__file__).resolve().parents[3]
EXP = ROOT / "experiments/07_grounded_gis_workflow_benchmark"
SCORE_ROOT = EXP / "outputs/scores"
OUT_ROOT = EXP / "outputs/gsis_extension"

METRICS = ["DATA_VALID", "FIELD_VALID", "CRS_PLAN", "SCHEMA_PLAN", "MAP_PLAN", "WPHR", "PRS", "EXEC_READY"]
MODE_ORDER = ["basic", "grounded", "geoguard"]
MODE_LABEL = {"basic": "Basic", "grounded": "Grounded", "geoguard": "GeoGuard"}
FAMILY_LABEL = {
    "buffer_service_area": "Buffer",
    "overlay_intersection": "Overlay",
    "point_count_join": "Point-count",
    "raster_clip": "Raster",
    "zonal_statistics": "Zonal",
    "choropleth_export": "Choropleth",
}


def read_rows() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for path in sorted(SCORE_ROOT.glob("*/workflow_task_scores.csv")):
        with path.open(newline="", encoding="utf-8") as f:
            rows.extend(csv.DictReader(f))
    if not rows:
        raise SystemExit("No workflow_task_scores.csv files found.")
    return rows


def f(row: dict[str, str], key: str) -> float:
    return float(row[key])


def execution_ready(row: dict[str, str]) -> int:
    return int(
        f(row, "JSON_VALID") >= 1
        and f(row, "TOOL_VALID") >= 1
        and f(row, "DATA_VALID") >= 1
        and f(row, "FIELD_VALID") >= 0.8
        and f(row, "CRS_PLAN") >= 1
        and f(row, "SCHEMA_PLAN") >= 0.8
        and f(row, "MAP_PLAN") >= 0.8
        and f(row, "OUTPUT_NAME") >= 1
    )


def strict_ready(row: dict[str, str]) -> int:
    return int(
        f(row, "JSON_VALID") >= 1
        and f(row, "TOOL_VALID") >= 1
        and f(row, "DATA_VALID") >= 1
        and f(row, "FIELD_VALID") >= 1
        and f(row, "CRS_PLAN") >= 1
        and f(row, "SCHEMA_PLAN") >= 1
        and f(row, "MAP_PLAN") >= 1
        and f(row, "OUTPUT_NAME") >= 1
    )


def first_blocker(row: dict[str, str]) -> str:
    checks = [
        ("json", "JSON_VALID", 1),
        ("tool", "TOOL_VALID", 1),
        ("data", "DATA_VALID", 1),
        ("field", "FIELD_VALID", 0.8),
        ("crs", "CRS_PLAN", 1),
        ("schema", "SCHEMA_PLAN", 0.8),
        ("map", "MAP_PLAN", 0.8),
        ("output", "OUTPUT_NAME", 1),
    ]
    for label, key, threshold in checks:
        if f(row, key) < threshold:
            return label
    return "ready"


def add_readiness(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    out = []
    for row in rows:
        enriched = dict(row)
        enriched["EXEC_READY"] = str(execution_ready(row))
        enriched["STRICT_READY"] = str(strict_ready(row))
        enriched["FIRST_BLOCKER"] = first_blocker(row)
        out.append(enriched)
    return out


def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def mode_readiness(rows: list[dict[str, str]]) -> list[dict[str, object]]:
    result = []
    for mode in MODE_ORDER:
        items = [r for r in rows if r["mode"] == mode]
        blockers = Counter(r["FIRST_BLOCKER"] for r in items if r["FIRST_BLOCKER"] != "ready")
        top_blocker, top_count = blockers.most_common(1)[0]
        result.append(
            {
                "mode": mode,
                "rows": len(items),
                "exec_ready": sum(int(r["EXEC_READY"]) for r in items),
                "exec_ready_rate": f"{mean(int(r['EXEC_READY']) for r in items):.4f}",
                "strict_ready": sum(int(r["STRICT_READY"]) for r in items),
                "strict_ready_rate": f"{mean(int(r['STRICT_READY']) for r in items):.4f}",
                "top_blocker": top_blocker,
                "top_blocker_count": top_count,
            }
        )
    return result


def family_readiness(rows: list[dict[str, str]]) -> list[dict[str, object]]:
    result = []
    for task_type in sorted({r["task_type"] for r in rows}):
        record: dict[str, object] = {"task_family": FAMILY_LABEL.get(task_type, task_type)}
        for mode in MODE_ORDER:
            items = [r for r in rows if r["task_type"] == task_type and r["mode"] == mode]
            record[f"{mode}_ready_rate"] = f"{mean(int(r['EXEC_READY']) for r in items):.3f}"
            record[f"{mode}_ready_count"] = sum(int(r["EXEC_READY"]) for r in items)
        result.append(record)
    return result


def paired_units(rows: list[dict[str, str]]) -> dict[tuple[str, str], dict[str, dict[str, str]]]:
    units: dict[tuple[str, str], dict[str, dict[str, str]]] = defaultdict(dict)
    for row in rows:
        units[(row["model"], row["task_id"])][row["mode"]] = row
    return {k: v for k, v in units.items() if all(mode in v for mode in MODE_ORDER)}


def bootstrap_ci(values: list[float], reps: int = 5000, seed: int = 20260629) -> tuple[float, float, float]:
    rng = random.Random(seed)
    n = len(values)
    boot = []
    for _ in range(reps):
        boot.append(mean(values[rng.randrange(n)] for _ in range(n)))
    boot.sort()
    return mean(values), boot[int(0.025 * reps)], boot[int(0.975 * reps)]


def paired_effects(rows: list[dict[str, str]]) -> list[dict[str, object]]:
    units = paired_units(rows)
    result = []
    comparisons = [("grounded", "basic"), ("geoguard", "grounded"), ("geoguard", "basic")]
    for metric in METRICS:
        metric_row: dict[str, object] = {"metric": metric}
        for hi, lo in comparisons:
            deltas = [f(unit[hi], metric) - f(unit[lo], metric) for unit in units.values()]
            avg, low, high = bootstrap_ci(deltas)
            metric_row[f"{hi}_minus_{lo}_mean"] = f"{avg:.4f}"
            metric_row[f"{hi}_minus_{lo}_ci95"] = f"[{low:.4f}, {high:.4f}]"
        result.append(metric_row)
    return result


def write_mode_table(rows: list[dict[str, object]], latex_tables: Path) -> None:
    lines = [
        "\\begin{table}[htbp]",
        "\\centering",
        "\\caption{Execution-readiness gate by prompting mode. Counts are out of 360 rows per mode.}",
        "\\label{tab:execution-readiness}",
        "\\small",
        "\\begin{tabular}{lrrrrl}",
        "\\toprule",
        "Mode & Ready & Rate & Strict & Strict rate & Top blocker \\\\",
        "\\midrule",
    ]
    for row in rows:
        lines.append(
            f"{MODE_LABEL[row['mode']]} & {row['exec_ready']} & {float(row['exec_ready_rate']):.3f} & "
            f"{row['strict_ready']} & {float(row['strict_ready_rate']):.3f} & "
            f"{row['top_blocker']} ({row['top_blocker_count']}) \\\\"
        )
    lines.extend(["\\bottomrule", "\\end{tabular}", "\\end{table}", ""])
    (latex_tables / "execution_readiness_table.tex").write_text("\n".join(lines), encoding="utf-8")


def write_family_table(rows: list[dict[str, object]], latex_tables: Path) -> None:
    lines = [
        "\\begin{table}[htbp]",
        "\\centering",
        "\\caption{Execution-readiness rate by task family and prompting mode. Counts are out of 60 rows per family-mode pair.}",
        "\\label{tab:family-execution-readiness}",
        "\\scriptsize",
        "\\begin{tabular}{lrrrrrr}",
        "\\toprule",
        "Family & Basic & Grounded & GeoGuard & Basic n & Grounded n & GeoGuard n \\\\",
        "\\midrule",
    ]
    for row in rows:
        lines.append(
            f"{row['task_family']} & {float(row['basic_ready_rate']):.3f} & "
            f"{float(row['grounded_ready_rate']):.3f} & {float(row['geoguard_ready_rate']):.3f} & "
            f"{row['basic_ready_count']} & {row['grounded_ready_count']} & {row['geoguard_ready_count']} \\\\"
        )
    lines.extend(["\\bottomrule", "\\end{tabular}", "\\end{table}", ""])
    (latex_tables / "family_execution_readiness_table.tex").write_text("\n".join(lines), encoding="utf-8")


def write_effect_table(rows: list[dict[str, object]], latex_tables: Path) -> None:
    labels = {
        "DATA_VALID": "Data validity",
        "FIELD_VALID": "Field validity",
        "CRS_PLAN": "CRS plan",
        "SCHEMA_PLAN": "Schema plan",
        "MAP_PLAN": "Map plan",
        "WPHR": "WPHR",
        "PRS": "PRS",
        "EXEC_READY": "Execution-ready",
    }
    lines = [
        "\\begin{table}[htbp]",
        "\\centering",
        "\\caption{Paired mode effects with bootstrap 95\\% confidence intervals across 360 model-task units.}",
        "\\label{tab:bootstrap-mode-effects}",
        "\\small",
        "\\setlength{\\tabcolsep}{3pt}",
        "\\begin{tabular}{lrrr}",
        "\\toprule",
        "Metric & Grounded--Basic & GeoGuard--Grounded & GeoGuard--Basic \\\\",
        "\\midrule",
    ]
    for row in rows:
        metric = row["metric"]
        lines.append(
            f"{labels.get(metric, metric)} & "
            f"{row['grounded_minus_basic_mean']} {row['grounded_minus_basic_ci95']} & "
            f"{row['geoguard_minus_grounded_mean']} {row['geoguard_minus_grounded_ci95']} & "
            f"{row['geoguard_minus_basic_mean']} {row['geoguard_minus_basic_ci95']} \\\\"
        )
    lines.extend(["\\bottomrule", "\\end{tabular}", "\\end{table}", ""])
    (latex_tables / "bootstrap_mode_effects_table.tex").write_text("\n".join(lines), encoding="utf-8")


def write_markdown(path: Path, rows: list[dict[str, object]], title: str) -> None:
    columns = list(rows[0].keys())
    lines = [f"# {title}", "", "|" + "|".join(columns) + "|", "|" + "|".join(["---"] * len(columns)) + "|"]
    for row in rows:
        lines.append("|" + "|".join(str(row[c]) for c in columns) + "|")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--latex-table-dir",
        default=None,
        help="Optional directory for manuscript-ready LaTeX tables. Omit in public artifact reproduction runs.",
    )
    args = parser.parse_args()

    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    rows = add_readiness(read_rows())
    mode_rows = mode_readiness(rows)
    family_rows = family_readiness(rows)
    effect_rows = paired_effects(rows)

    write_csv(OUT_ROOT / "task_scores_with_execution_readiness.csv", rows)
    write_csv(OUT_ROOT / "execution_readiness_by_mode.csv", mode_rows)
    write_csv(OUT_ROOT / "execution_readiness_by_family.csv", family_rows)
    write_csv(OUT_ROOT / "bootstrap_mode_effects.csv", effect_rows)
    write_markdown(OUT_ROOT / "execution_readiness_by_mode.md", mode_rows, "Execution Readiness by Mode")
    write_markdown(OUT_ROOT / "execution_readiness_by_family.md", family_rows, "Execution Readiness by Family")
    write_markdown(OUT_ROOT / "bootstrap_mode_effects.md", effect_rows, "Bootstrap Mode Effects")

    if args.latex_table_dir:
        latex_tables = Path(args.latex_table_dir).resolve()
        latex_tables.mkdir(parents=True, exist_ok=True)
        write_mode_table(mode_rows, latex_tables)
        write_family_table(family_rows, latex_tables)
        write_effect_table(effect_rows, latex_tables)
        print(f"Wrote LaTeX tables to {latex_tables.relative_to(ROOT)}")
    print(f"Wrote GSIS extension analysis to {OUT_ROOT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
