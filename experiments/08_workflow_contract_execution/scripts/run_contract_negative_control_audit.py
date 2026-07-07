#!/usr/bin/env python3
"""Mutation-based negative-control audit for workflow contracts.

The audit starts from strict-valid contracts and injects controlled contract
faults that should be rejected before artifact production. It evaluates the
contract validator rather than the original LLM.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from copy import deepcopy
from pathlib import Path
from statistics import mean
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

from run_contract_execution import (  # noqa: E402
    DATA_PROFILES,
    EXP08,
    MODE_ORDER,
    ROOT,
    TASKS_PATH,
    expected_layers,
    metric_epsg,
    read_json,
    spec_layer_mentions,
)


OUT = EXP08 / "outputs"
STRICT_RESULTS = OUT / "full_contract_execution_results.csv"
AUDIT_RESULTS = OUT / "contract_negative_control_audit.csv"
AUDIT_SUMMARY = OUT / "contract_negative_control_summary.csv"


def write_table(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def write_markdown(path: Path, rows: list[dict[str, Any]], title: str) -> None:
    if not rows:
        return
    cols = list(rows[0])
    lines = [f"# {title}", "", "|" + "|".join(cols) + "|", "|" + "|".join(["---"] * len(cols)) + "|"]
    for row in rows:
        lines.append("|" + "|".join(str(row[c]) for c in cols) + "|")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def output_filename(spec: dict[str, Any]) -> str:
    candidates = [
        spec.get("output"),
        spec.get("outputs"),
        spec.get("params", {}).get("output") if isinstance(spec.get("params"), dict) else None,
        spec.get("params", {}).get("output_filename") if isinstance(spec.get("params"), dict) else None,
        spec.get("params", {}).get("filename") if isinstance(spec.get("params"), dict) else None,
    ]
    for item in candidates:
        if isinstance(item, str):
            return item
        if isinstance(item, dict):
            for key in ("filename", "file", "path", "name"):
                if isinstance(item.get(key), str):
                    return item[key]
    return ""


def set_output_filename(spec: dict[str, Any], filename: str) -> None:
    output = spec.setdefault("output", {})
    if isinstance(output, dict):
        output["filename"] = filename
    else:
        spec["output"] = {"filename": filename}


def replace_string(value: Any, old: str, new: str) -> Any:
    if isinstance(value, str):
        return value.replace(old, new).replace(old.replace("_", " "), new)
    if isinstance(value, list):
        return [replace_string(item, old, new) for item in value]
    if isinstance(value, dict):
        return {key: replace_string(child, old, new) for key, child in value.items()}
    return value


def remove_layer_mentions(spec: dict[str, Any], layer: str) -> dict[str, Any]:
    mutated = deepcopy(spec)
    for alias in {layer, layer.replace("_", " "), DATA_PROFILES["geoguard"][layer].name}:
        mutated = replace_string(mutated, alias, "")
    return mutated


def make_params(spec: dict[str, Any]) -> dict[str, Any]:
    params = spec.setdefault("params", {})
    if not isinstance(params, dict):
        spec["params"] = {}
    return spec["params"]


def mutations(task: dict[str, Any], spec: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    out: list[tuple[str, dict[str, Any]]] = []
    task_type = task["type"]

    wrong_op = deepcopy(spec)
    wrong_op["operation"] = "raster_clip" if task_type != "raster_clip" else "overlay_intersection"
    out.append(("wrong_operation_family", wrong_op))

    expected = sorted(expected_layers(task["task_id"], task_type))
    mentioned = sorted(spec_layer_mentions(spec) & set(expected))
    if mentioned:
        out.append(("missing_required_layer_role", remove_layer_mentions(spec, mentioned[0])))
        hallucinated = deepcopy(spec)
        for alias in {mentioned[0], mentioned[0].replace("_", " "), DATA_PROFILES["geoguard"][mentioned[0]].name}:
            hallucinated = replace_string(hallucinated, alias, "imaginary_layer_999.gpkg")
        out.append(("hallucinated_layer_alias", hallucinated))

    wrong_file = deepcopy(spec)
    set_output_filename(wrong_file, f"wrong_{task['task_id']}.gpkg")
    out.append(("wrong_output_filename", wrong_file))

    if task_type == "choropleth_export":
        bad_cmap = deepcopy(spec)
        make_params(bad_cmap)["cmap"] = "not_a_matplotlib_colormap"
        out.append(("invalid_choropleth_colormap", bad_cmap))

    if task_type == "buffer_service_area":
        bad_crs = deepcopy(spec)
        make_params(bad_crs)["target_epsg"] = 4326
        out.append(("geographic_crs_for_metric_buffer", bad_crs))

    return out


def detect(task: dict[str, Any], spec: dict[str, Any], mutation_type: str) -> tuple[int, str]:
    task_type = task["type"]
    reasons: list[str] = []

    if spec.get("operation") != task_type:
        reasons.append("operation_mismatch")

    expected = expected_layers(task["task_id"], task_type)
    missing = sorted(expected - spec_layer_mentions(spec))
    if missing:
        reasons.append("missing_layer_roles")

    if output_filename(spec) and output_filename(spec) != task["output"]:
        reasons.append("output_filename_mismatch")

    params = spec.get("params", {}) if isinstance(spec.get("params"), dict) else {}
    if task_type == "choropleth_export" and isinstance(params.get("cmap"), str):
        if params["cmap"] not in plt.colormaps():
            reasons.append("invalid_colormap")

    if task_type == "buffer_service_area" and metric_epsg(params) == 4326:
        reasons.append("unsafe_metric_crs")

    if mutation_type == "hallucinated_layer_alias":
        text = json.dumps(spec).lower()
        if "imaginary_layer_999" in text:
            reasons.append("hallucinated_layer_name")

    return int(bool(reasons)), ";".join(sorted(set(reasons)))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--max-base-contracts", type=int, default=None)
    args = parser.parse_args()

    tasks = {t["task_id"]: t for t in read_json(TASKS_PATH)}
    rows = list(csv.DictReader(STRICT_RESULTS.open(newline="", encoding="utf-8")))
    base_rows = [r for r in rows if r["output_valid"] == "1" and Path(ROOT / r["spec_path"]).exists()]
    base_rows.sort(key=lambda r: (MODE_ORDER.index(r["mode"]), r["model"], r["task_id"]))
    if args.max_base_contracts:
        base_rows = base_rows[: args.max_base_contracts]

    audit: list[dict[str, Any]] = []
    for row in base_rows:
        task = tasks[row["task_id"]]
        spec = read_json(ROOT / row["spec_path"])
        for mutation_type, mutated in mutations(task, spec):
            detected, reasons = detect(task, mutated, mutation_type)
            audit.append(
                {
                    "model": row["model"],
                    "mode": row["mode"],
                    "task_id": row["task_id"],
                    "task_type": row["task_type"],
                    "mutation_type": mutation_type,
                    "detected": detected,
                    "detection_reasons": reasons,
                }
            )

    write_table(AUDIT_RESULTS, audit)
    summary: list[dict[str, Any]] = []
    for mutation_type in sorted({r["mutation_type"] for r in audit}):
        items = [r for r in audit if r["mutation_type"] == mutation_type]
        summary.append(
            {
                "mutation_type": mutation_type,
                "cases": len(items),
                "detected": sum(int(r["detected"]) for r in items),
                "detection_rate": f"{mean(int(r['detected']) for r in items):.4f}",
                "top_detection_reason": Counter(
                    reason
                    for r in items
                    for reason in str(r["detection_reasons"]).split(";")
                    if reason
                ).most_common(1)[0][0],
            }
        )
    write_table(AUDIT_SUMMARY, summary)
    write_markdown(OUT / "contract_negative_control_summary.md", summary, "Contract Negative-Control Summary")
    print(f"Audited {len(base_rows)} strict-valid base contracts and {len(audit)} mutations")
    print(f"Wrote {AUDIT_RESULTS.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
