#!/usr/bin/env python3
"""Score structured workflow specs for GeoGuard planning reliability."""

from __future__ import annotations

import argparse
import csv
import json
import re
from pathlib import Path
from statistics import mean


ROOT = Path(__file__).resolve().parents[3]
TASKS_PATH = ROOT / "experiments/07_grounded_gis_workflow_benchmark/inputs/workflow_tasks_30.json"
SPEC_ROOT = ROOT / "experiments/07_grounded_gis_workflow_benchmark/outputs/generated_specs"
SCORE_ROOT = ROOT / "experiments/07_grounded_gis_workflow_benchmark/outputs/scores"


LAYERS = {
    "hospital_points": {"fields": {"source_id", "name", "org_name", "addrln1", "city", "state", "zip", "url"}},
    "study_boundary": {"fields": {"boundary_id", "name", "label"}},
    "census_tracts": {"fields": {"tract_id", "tract_name", "land_area_m2", "water_area_m2"}},
    "flood_zones": {"fields": {"source_id", "dfirm_id", "zone_code", "zone_subty", "sfha_tf"}},
    "school_points": {"fields": {"school_id", "name", "city", "state", "zip", "county_name"}},
    "temperature_raster": {"fields": set()},
    "zonal_input_for_map": {"fields": {"tract_id", "tract_name", "land_area_m2", "water_area_m2", "temp_mean", "temp_sum"}},
}

ALLOWED_OPS = {"buffer_service_area", "overlay_intersection", "point_count_join", "raster_clip", "zonal_statistics", "choropleth_export"}


def flatten_strings(value) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        items = []
        for child in value.values():
            items.extend(flatten_strings(child))
        return items
    if isinstance(value, list):
        items = []
        for child in value:
            items.extend(flatten_strings(child))
        return items
    return []


def normalize_layer_name(value: str) -> str:
    token = Path(value).name
    token = re.sub(r"\.(gpkg|shp|geojson|tif|tiff)$", "", token, flags=re.IGNORECASE)
    return token


def epsg_values(value) -> set[int]:
    vals = set()
    for text in flatten_strings(value):
        vals.update(int(m) for m in re.findall(r"(?:EPSG:)?(\d{4,5})", text, flags=re.IGNORECASE))
    if isinstance(value, dict):
        for key in ("target_epsg", "epsg"):
            if isinstance(value.get(key), int):
                vals.add(value[key])
    if isinstance(value, list):
        vals.update(v for v in value if isinstance(v, int))
    return vals


def field_refs(params: dict) -> list[str]:
    refs = []
    for key, value in params.items():
        key_l = key.lower()
        if key_l in {"field", "group_field", "area_field", "join_field", "variable"} or key_l.endswith("_field"):
            refs.extend(flatten_strings(value))
        if key_l == "aggregate_by":
            refs.extend(flatten_strings(value))
    return refs


def has_projected_crs(epsgs: set[int], text: str) -> bool:
    return bool(epsgs - {4326, 4269}) or "projected" in text or "utm" in text


def score_spec(task: dict, spec_path: Path) -> dict:
    if not spec_path.exists():
        return {"JSON_VALID": 0, "TOOL_VALID": 0, "DATA_VALID": 0, "FIELD_VALID": 0, "CRS_PLAN": 0, "SCHEMA_PLAN": 0, "MAP_PLAN": 0, "OUTPUT_NAME": 0, "PHR": 1.0, "WPHR": 1.0, "PRS": 0}
    try:
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
    except Exception:
        return {"JSON_VALID": 0, "TOOL_VALID": 0, "DATA_VALID": 0, "FIELD_VALID": 0, "CRS_PLAN": 0, "SCHEMA_PLAN": 0, "MAP_PLAN": 0, "OUTPUT_NAME": 0, "PHR": 1.0, "WPHR": 1.0, "PRS": 0}

    op = spec.get("operation")
    tool_valid = int(op == task["type"] and op in ALLOWED_OPS)
    inputs = spec.get("inputs", {}) if isinstance(spec.get("inputs", {}), dict) else {}
    params = spec.get("params", {}) if isinstance(spec.get("params", {}), dict) else {}
    output = spec.get("output", {}) if isinstance(spec.get("output", {}), dict) else {}
    validation = spec.get("validation", {}) if isinstance(spec.get("validation", {}), dict) else {}

    referenced_layers = [normalize_layer_name(v) for v in flatten_strings(inputs)]
    known_layers = [v for v in referenced_layers if v in LAYERS]
    data_valid = int(bool(referenced_layers) and len(known_layers) == len(referenced_layers))

    required = set(task.get("required_fields", []))
    declared_required = set(output.get("required_fields", [])) if isinstance(output.get("required_fields", []), list) else set()
    schema_plan = 1.0 if required.issubset(declared_required) or not required else len(required & declared_required) / len(required)

    existing_fields = set()
    for layer in known_layers:
        existing_fields.update(LAYERS[layer]["fields"])
    created_fields = set()
    if task["type"] == "buffer_service_area":
        created_fields.update(f for f in required if f.endswith("_m2") or f in {"area", "area_m2"})
    if task["type"] == "point_count_join" and isinstance(params.get("count_field"), str):
        created_fields.add(params["count_field"])
    if task["type"] == "zonal_statistics":
        prefix = params.get("column_prefix", "")
        for stat in params.get("stats", []):
            if isinstance(stat, str):
                created_fields.add(f"{prefix}{stat}")
    field_checks = field_refs(params) + list(declared_required)
    if field_checks:
        valid_field_count = sum(1 for f in field_checks if f in existing_fields or f in created_fields)
        field_valid = valid_field_count / len(field_checks)
    else:
        field_valid = 1.0
    # Required output fields must still be declared even when the executor creates them.
    if required and schema_plan < 1:
        field_valid = min(field_valid, schema_plan)

    crs_text = json.dumps(params).lower() + json.dumps(validation).lower()
    epsgs = epsg_values(params) | epsg_values(validation)
    if task["type"] == "buffer_service_area":
        crs_plan = 1.0 if has_projected_crs(epsgs, crs_text) else 0.0
    elif task["type"] == "overlay_intersection":
        if has_projected_crs(epsgs, crs_text):
            crs_plan = 1.0
        elif epsgs or "crs" in crs_text:
            crs_plan = 0.5
        else:
            crs_plan = 0.0
    elif task["type"] == "point_count_join":
        crs_plan = 1.0 if epsgs or "align" in crs_text or "crs" in crs_text or "reproject" in crs_text else 0.0
    elif task["type"] in {"raster_clip", "zonal_statistics"}:
        crs_plan = 1.0 if "raster" in crs_text and ("align" in crs_text or "crs" in crs_text or "reproject" in crs_text) else 0.0
    else:
        crs_plan = 1.0

    map_plan = 1.0
    if task["type"] == "choropleth_export":
        map_text = json.dumps(params).lower() + json.dumps(validation).lower()
        checks = ["title", "legend", "cmap", "scheme", "source"]
        map_plan = sum(1 for c in checks if c in map_text) / len(checks)

    filename_ok = int(output.get("filename") == task["output"])
    hallucination_issues = 0
    hallucination_checks = 5
    hallucination_issues += 0 if tool_valid else 1
    hallucination_issues += 0 if data_valid else 1
    hallucination_issues += 0 if field_valid >= 1 else 1
    hallucination_issues += 0 if crs_plan >= 1 else 1
    hallucination_issues += 0 if filename_ok else 1
    weighted_phr = mean([
        1 - tool_valid,
        1 - data_valid,
        1 - field_valid,
        1 - crs_plan,
        1 - filename_ok,
    ])
    plan_reliability = mean([
        1,
        tool_valid,
        data_valid,
        field_valid,
        crs_plan,
        schema_plan,
        map_plan,
        filename_ok,
        1 - weighted_phr,
    ])

    return {
        "JSON_VALID": 1,
        "TOOL_VALID": tool_valid,
        "DATA_VALID": data_valid,
        "FIELD_VALID": round(field_valid, 4),
        "CRS_PLAN": round(crs_plan, 4),
        "SCHEMA_PLAN": round(schema_plan, 4),
        "MAP_PLAN": round(map_plan, 4),
        "OUTPUT_NAME": filename_ok,
        "PHR": round(hallucination_issues / hallucination_checks, 4),
        "WPHR": round(weighted_phr, 4),
        "PRS": round(plan_reliability, 4),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="qwen2.5-coder:32b")
    parser.add_argument("--modes", nargs="+", default=["basic", "grounded", "geoguard"])
    args = parser.parse_args()

    model_slug = args.model.replace(":", "_")
    tasks = {t["task_id"]: t for t in json.loads(TASKS_PATH.read_text(encoding="utf-8"))}
    rows = []
    for mode in args.modes:
        mode_dir = SPEC_ROOT / model_slug / mode
        task_ids = sorted({p.name.split("_")[0] for p in mode_dir.glob("*.json")} | {p.name.split("_")[0] for p in mode_dir.glob("*.raw.txt")})
        for task_id in task_ids:
            if task_id not in tasks:
                continue
            spec_path = mode_dir / f"{task_id}_{mode}.json"
            score = score_spec(tasks[task_id], spec_path)
            rows.append({"model": args.model, "mode": mode, "task_id": task_id, "task_type": tasks[task_id]["type"], **score})

    summary = []
    for mode in sorted({r["mode"] for r in rows}):
        items = [r for r in rows if r["mode"] == mode]
        summary.append({"model": args.model, "mode": mode, **{k: round(mean(r[k] for r in items), 4) for k in ["JSON_VALID", "TOOL_VALID", "DATA_VALID", "FIELD_VALID", "CRS_PLAN", "SCHEMA_PLAN", "MAP_PLAN", "OUTPUT_NAME", "PHR", "WPHR", "PRS"]}, "tasks": len(items)})

    out_dir = SCORE_ROOT / model_slug
    out_dir.mkdir(parents=True, exist_ok=True)
    for path, data in [(out_dir / "workflow_task_scores.csv", rows), (out_dir / "workflow_summary.csv", summary)]:
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=list(data[0].keys()), lineterminator="\n")
            writer.writeheader()
            writer.writerows(data)
        print(f"Wrote {path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
