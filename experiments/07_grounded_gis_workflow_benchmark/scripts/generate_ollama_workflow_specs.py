#!/usr/bin/env python3
"""Generate structured GeoGuard workflow specs with local Ollama models."""

from __future__ import annotations

import argparse
import json
import re
import urllib.request
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
TASKS_PATH = ROOT / "experiments/07_grounded_gis_workflow_benchmark/inputs/workflow_tasks_30.json"
OUT_ROOT = ROOT / "experiments/07_grounded_gis_workflow_benchmark/outputs/generated_specs"


DATA_PROFILE = """
Data profile:
- hospital_points: file hospital_points.gpkg, geometry Point, CRS EPSG:4326, fields source_id,name,org_name,addrln1,city,state,zip,url
- study_boundary: file study_boundary.gpkg, geometry MultiPolygon, CRS EPSG:4269, fields boundary_id,name,label
- census_tracts: file census_tracts.gpkg, geometry MultiPolygon, CRS EPSG:4269, fields tract_id,tract_name,land_area_m2,water_area_m2
- flood_zones: file flood_zones.gpkg, geometry Polygon, CRS EPSG:4326, fields source_id,dfirm_id,zone_code,zone_subty,sfha_tf
- school_points: file school_points.gpkg, geometry Point, CRS EPSG:4326, fields school_id,name,city,state,zip,county_name
- temperature_raster: file temperature_raster.tif, raster CRS EPSG:4326
- zonal_input_for_map: file zonal_input_for_map.gpkg, fields tract_id,tract_name,land_area_m2,water_area_m2,temp_mean,temp_sum
"""


TOOL_SCHEMA = """
Allowed operations:
- buffer_service_area: inputs source, clip_boundary; params distance_m, target_epsg, dissolve; output vector.
- overlay_intersection: inputs input_a, input_b; params target_epsg, aggregate_by optional, area_field optional; output vector.
- point_count_join: inputs target, join; params target_epsg, group_field, count_field, predicate; output vector.
- raster_clip: inputs raster, mask; params align_mask_to_raster_crs, nodata; output raster.
- zonal_statistics: inputs polygons, raster; params stats, column_prefix, align_polygons_to_raster_crs; output vector.
- choropleth_export: inputs layer; params field, classes, scheme, cmap, title, legend_title, source_note; output png.
"""


VALIDATION_RULES = """
GeoGuard validation rules:
- Metric buffers and area calculations require projected CRS EPSG:3857 or equivalent.
- Overlay/sjoin layers must be CRS-aligned.
- Raster masks/polygons must be reprojected to raster CRS before masking/zonal statistics.
- Required output fields must be preserved or created.
- Geometry outputs should be repaired with buffer(0) if invalid.
- Choropleth maps require title, legend, classification scheme, sequential color ramp, readable borders, and source note.
"""


MODE_CONTEXT = {
    "basic": "",
    "grounded": DATA_PROFILE + "\n" + TOOL_SCHEMA,
    "geoguard": DATA_PROFILE + "\n" + TOOL_SCHEMA + "\n" + VALIDATION_RULES,
}


def extract_json(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```json", "", text)
    text = re.sub(r"^```", "", text)
    text = re.sub(r"```$", "", text).strip()
    start = text.find("{")
    if start < 0:
        raise ValueError("No JSON object found")
    decoder = json.JSONDecoder()
    obj, _ = decoder.raw_decode(text[start:])
    return obj


def ask_ollama(model: str, prompt: str, timeout: int) -> str:
    payload = json.dumps({"model": model, "prompt": prompt, "stream": False, "options": {"temperature": 0.0, "num_predict": 900}}).encode("utf-8")
    req = urllib.request.Request("http://127.0.0.1:11434/api/generate", data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data.get("response", "")


def prompt_for(mode: str, task: dict) -> str:
    return f"""You are a GIS copilot planner.

Return only one valid JSON object. Do not include Markdown.

{MODE_CONTEXT[mode]}

Natural language task:
{task['prompt']}

Task id: {task['task_id']}
Expected operation type: {task['type']}
Required output filename: {task['output']}
Required output fields: {task.get('required_fields', [])}

JSON schema:
{{
  "task_id": "...",
  "operation": "one allowed operation",
  "inputs": {{}},
  "params": {{}},
  "output": {{"filename": "...", "type": "vector|raster|png", "required_fields": []}},
  "validation": {{"crs": [], "schema": [], "geometry": [], "raster": [], "map_quality": []}},
  "rationale": "short"
}}
"""


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="qwen2.5-coder:32b")
    parser.add_argument("--modes", nargs="+", default=["basic", "grounded", "geoguard"])
    parser.add_argument("--task-ids", nargs="*", default=None)
    parser.add_argument("--task-limit", type=int, default=None)
    parser.add_argument("--timeout", type=int, default=240)
    args = parser.parse_args()

    tasks = json.loads(TASKS_PATH.read_text(encoding="utf-8"))
    if args.task_ids:
        keep = set(args.task_ids)
        tasks = [t for t in tasks if t["task_id"] in keep]
    if args.task_limit:
        tasks = tasks[: args.task_limit]

    model_slug = args.model.replace(":", "_")
    manifest = []
    for mode in args.modes:
        out_dir = OUT_ROOT / model_slug / mode
        out_dir.mkdir(parents=True, exist_ok=True)
        for task in tasks:
            out_file = out_dir / f"{task['task_id']}_{mode}.json"
            raw_file = out_dir / f"{task['task_id']}_{mode}.raw.txt"
            print(f"running: {args.model} {mode} {task['task_id']}", flush=True)
            if out_file.exists():
                status = "cached"
            else:
                raw = ""
                try:
                    raw = ask_ollama(args.model, prompt_for(mode, task), args.timeout)
                    raw_file.write_text(raw, encoding="utf-8")
                    spec = extract_json(raw)
                    out_file.write_text(json.dumps(spec, indent=2), encoding="utf-8")
                    status = "generated"
                except Exception as exc:
                    if not raw:
                        raw_file.write_text(str(exc), encoding="utf-8")
                    else:
                        (out_dir / f"{task['task_id']}_{mode}.error.txt").write_text(str(exc), encoding="utf-8")
                    status = "failed"
            manifest.append({"model": args.model, "mode": mode, "task_id": task["task_id"], "spec": str(out_file.relative_to(ROOT)), "status": status})
            print(f"{status}: {args.model} {mode} {task['task_id']}", flush=True)
    manifest_path = OUT_ROOT / model_slug / "workflow_generation_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"Wrote {manifest_path.relative_to(ROOT)}", flush=True)


if __name__ == "__main__":
    main()
