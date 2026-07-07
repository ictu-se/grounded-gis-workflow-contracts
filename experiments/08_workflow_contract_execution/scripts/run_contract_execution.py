#!/usr/bin/env python3
"""Execute GIS workflow contracts that passed the planning-readiness gate.

This experiment tests the downstream consequence of workflow-contract quality:
can a scored contract be bound to real layers and converted into a valid GIS
artifact without asking the LLM for code?
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import time
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean
from typing import Any

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import rasterio
from rasterio.mask import mask
from rasterstats import zonal_stats


ROOT = Path(__file__).resolve().parents[3]
EXP07 = ROOT / "experiments/07_grounded_gis_workflow_benchmark"
EXP08 = ROOT / "experiments/08_workflow_contract_execution"
GEOGUARD_DATA = ROOT / "data/raw/geoguard/geoguard/data"
SYNTHETIC_DATA = ROOT / "data/synthetic/workflow_contract_profile_v1"
TASKS_PATH = EXP07 / "inputs/workflow_tasks_30.json"
SCORES_PATH = EXP07 / "outputs/gsis_extension/task_scores_with_execution_readiness.csv"
SPECS = EXP07 / "outputs/generated_specs"
OUT = EXP08 / "outputs"
ARTIFACTS = OUT / "artifacts"

DATA_PROFILES = {
    "geoguard": {
        "hospital_points": GEOGUARD_DATA / "hospital_points.gpkg",
        "study_boundary": GEOGUARD_DATA / "study_boundary.gpkg",
        "census_tracts": GEOGUARD_DATA / "census_tracts.gpkg",
        "flood_zones": GEOGUARD_DATA / "flood_zones.gpkg",
        "school_points": GEOGUARD_DATA / "school_points.gpkg",
        "temperature_raster": GEOGUARD_DATA / "temperature_raster.tif",
        "zonal_input_for_map": GEOGUARD_DATA / "zonal_input_for_map.gpkg",
    },
    "synthetic": {
        "hospital_points": SYNTHETIC_DATA / "health_facilities.gpkg",
        "study_boundary": SYNTHETIC_DATA / "metro_boundary.gpkg",
        "census_tracts": SYNTHETIC_DATA / "planning_districts.gpkg",
        "flood_zones": SYNTHETIC_DATA / "river_flood_hazard.gpkg",
        "school_points": SYNTHETIC_DATA / "education_sites.gpkg",
        "temperature_raster": SYNTHETIC_DATA / "surface_temperature_utm.tif",
        "zonal_input_for_map": SYNTHETIC_DATA / "district_map_input.gpkg",
    },
}
LAYER_FILES = DATA_PROFILES["geoguard"]

MODE_ORDER = ["basic", "grounded", "geoguard"]


def slug_model(model: str) -> str:
    return model.replace(":", "_")


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def flatten_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        out: list[str] = []
        for key, child in value.items():
            out.append(str(key))
            out.extend(flatten_strings(child))
        return out
    if isinstance(value, list):
        out: list[str] = []
        for child in value:
            out.extend(flatten_strings(child))
        return out
    return []


def spec_layer_mentions(spec: dict[str, Any]) -> set[str]:
    text = " ".join(flatten_strings(spec.get("inputs", {}))).lower()
    mentions = set()
    for layer in LAYER_FILES:
        aliases = {layer, layer.replace("_", " "), LAYER_FILES[layer].name.lower()}
        if any(alias in text for alias in aliases):
            mentions.add(layer)
    return mentions


def expected_layers(task_id: str, task_type: str) -> set[str]:
    if task_type == "buffer_service_area":
        return {"hospital_points", "study_boundary"}
    if task_type == "overlay_intersection":
        return {"census_tracts", "flood_zones"}
    if task_type == "point_count_join":
        if task_id == "T015":
            return {"census_tracts", "school_points", "hospital_points"}
        return {"census_tracts", "hospital_points"} if task_id == "T012" else {"census_tracts", "school_points"}
    if task_type == "raster_clip":
        return {"temperature_raster", "study_boundary"}
    if task_type == "zonal_statistics":
        base = {"census_tracts", "temperature_raster"}
        if task_id == "T024":
            base.add("school_points")
        if task_id == "T025":
            base.update({"school_points", "flood_zones"})
        return base
    if task_type == "choropleth_export":
        return {"zonal_input_for_map"}
    return set()


def output_dir(row: dict[str, str], data_profile: str) -> Path:
    path = ARTIFACTS / data_profile / slug_model(row["model"]) / row["mode"] / row["task_id"]
    path.mkdir(parents=True, exist_ok=True)
    return path


def gdf(layer: str) -> gpd.GeoDataFrame:
    return gpd.read_file(LAYER_FILES[layer])


def write_vector(data: gpd.GeoDataFrame, path: Path) -> None:
    if path.exists():
        path.unlink()
    data.to_file(path, driver="GPKG")


def repo_relative_message(message: str) -> str:
    """Remove machine-specific absolute prefixes from benchmark ledgers."""
    return message.replace(str(ROOT) + "/", "")


def metric_epsg(params: dict[str, Any]) -> int:
    value = params.get("target_epsg") or params.get("output_epsg") or 3857
    if isinstance(value, str):
        found = re.search(r"(\d{4,5})", value)
        return int(found.group(1)) if found else 3857
    if isinstance(value, int):
        return value
    return 3857


def buffer_distance(task: dict[str, Any], params: dict[str, Any]) -> float:
    value = params.get("distance_m") or params.get("buffer_distance_m")
    if isinstance(value, (int, float)):
        return float(value)
    found = re.search(r"(\d+(?:\.\d+)?)\s*(?:km|kilometer)", task["prompt"], re.I)
    if found:
        return float(found.group(1)) * 1000.0
    found = re.search(r"(\d+(?:\.\d+)?)\s*(?:m|meter)", task["prompt"], re.I)
    return float(found.group(1)) if found else 1000.0


def execute_buffer(task: dict[str, Any], spec: dict[str, Any], out_dir: Path) -> Path:
    params = spec.get("params", {}) if isinstance(spec.get("params"), dict) else {}
    epsg = metric_epsg(params)
    hospitals = gdf("hospital_points").to_crs(epsg)
    boundary = gdf("study_boundary").to_crs(epsg)
    result = hospitals.copy()
    result["geometry"] = result.geometry.buffer(buffer_distance(task, params))
    result = gpd.clip(result, boundary)
    if task["task_id"] == "T003" or params.get("dissolve") is True and task["task_id"] == "T003":
        result = gpd.GeoDataFrame({"coverage_id": [task["task_id"]]}, geometry=[result.unary_union], crs=f"EPSG:{epsg}")
    if "area_m2" in task.get("required_fields", []):
        result["area_m2"] = result.geometry.area
    path = out_dir / task["output"]
    write_vector(result.to_crs(4326), path)
    return path


def flood_overlay_by_tract() -> gpd.GeoDataFrame:
    tracts = gdf("census_tracts").to_crs(3857)
    floods = gdf("flood_zones").to_crs(3857)
    over = gpd.overlay(tracts, floods, how="intersection", keep_geom_type=True)
    over["flood_area_m2"] = over.geometry.area
    return over


def execute_overlay(task: dict[str, Any], _spec: dict[str, Any], out_dir: Path) -> Path:
    over = flood_overlay_by_tract()
    if task["task_id"] in {"T009", "T010"}:
        summary = over.groupby("tract_id", as_index=False)["flood_area_m2"].sum()
        result = gdf("census_tracts").merge(summary, on="tract_id", how="left")
        result["flood_area_m2"] = result["flood_area_m2"].fillna(0.0)
        if task["task_id"] == "T010":
            result = result[result["flood_area_m2"] > 0].copy()
    else:
        result = over
    path = out_dir / task["output"]
    write_vector(result.to_crs(4326), path)
    return path


def count_points(points_layer: str, count_field: str) -> gpd.GeoDataFrame:
    tracts = gdf("census_tracts").to_crs(4326)
    points = gdf(points_layer).to_crs(4326)
    joined = gpd.sjoin(points[[points.geometry.name]], tracts[["tract_id", "geometry"]], predicate="within", how="left")
    counts = joined.groupby("tract_id").size().rename(count_field).reset_index()
    result = tracts.merge(counts, on="tract_id", how="left")
    result[count_field] = result[count_field].fillna(0).astype(int)
    return result


def execute_point_count(task: dict[str, Any], _spec: dict[str, Any], out_dir: Path) -> Path:
    if task["task_id"] == "T012":
        result = count_points("hospital_points", "hospital_count")
    elif task["task_id"] == "T015":
        schools = count_points("school_points", "school_count").drop(columns="geometry")
        hospitals = count_points("hospital_points", "hospital_count")[["tract_id", "hospital_count", "geometry"]]
        result = hospitals.merge(schools[["tract_id", "school_count"]], on="tract_id", how="left")
    else:
        result = count_points("school_points", "school_count")
        if task["task_id"] == "T013":
            result["schools_per_km2"] = result["school_count"] / (result["land_area_m2"] / 1_000_000)
        if task["task_id"] == "T014":
            result = result[result["school_count"] > 0].copy()
    path = out_dir / task["output"]
    write_vector(result, path)
    return path


def execute_raster_clip(task: dict[str, Any], spec: dict[str, Any], out_dir: Path) -> Path:
    boundary = gdf("study_boundary")
    path = out_dir / task["output"]
    with rasterio.open(LAYER_FILES["temperature_raster"]) as src:
        geoms = boundary.to_crs(src.crs).geometry
        nodata = spec.get("params", {}).get("nodata", src.nodata) if isinstance(spec.get("params"), dict) else src.nodata
        data, transform = mask(src, geoms, crop=True, nodata=nodata)
        profile = src.profile.copy()
        profile.update(height=data.shape[1], width=data.shape[2], transform=transform, nodata=nodata)
        if task["task_id"] == "T019":
            profile.update(compress="deflate")
        with rasterio.open(path, "w", **profile) as dst:
            dst.write(data)
    return path


def zonal_temperature() -> gpd.GeoDataFrame:
    tracts = gdf("census_tracts")
    with rasterio.open(LAYER_FILES["temperature_raster"]) as src:
        work = tracts.to_crs(src.crs)
        stats = zonal_stats(work, str(LAYER_FILES["temperature_raster"]), stats=["mean", "sum"], nodata=src.nodata)
    out = tracts.copy()
    out["temp_mean"] = [s.get("mean") for s in stats]
    out["temp_sum"] = [s.get("sum") for s in stats]
    return out


def execute_zonal(task: dict[str, Any], _spec: dict[str, Any], out_dir: Path) -> Path:
    result = zonal_temperature()
    if task["task_id"] == "T022":
        result = result.drop(columns=["temp_sum"])
    if task["task_id"] == "T023":
        cutoff = result["temp_mean"].quantile(0.75)
        result = result[result["temp_mean"] >= cutoff].copy()
    if task["task_id"] in {"T024", "T025"}:
        counts = count_points("school_points", "school_count").drop(columns="geometry")
        result = result.merge(counts[["tract_id", "school_count"]], on="tract_id", how="left")
    if task["task_id"] == "T025":
        flood = flood_overlay_by_tract().groupby("tract_id", as_index=False)["flood_area_m2"].sum()
        result = result.merge(flood, on="tract_id", how="left")
        result["flood_area_m2"] = result["flood_area_m2"].fillna(0.0)
    path = out_dir / task["output"]
    write_vector(result, path)
    return path


def choropleth_data(task_id: str) -> tuple[gpd.GeoDataFrame, str, str]:
    data = gdf("zonal_input_for_map")
    if task_id == "T026":
        return data, "temp_mean", "Mean temperature"
    if task_id == "T027":
        counts = count_points("school_points", "school_count").drop(columns="geometry")
        data = data.merge(counts[["tract_id", "school_count"]], on="tract_id", how="left")
        data["schools_per_km2"] = data["school_count"] / (data["land_area_m2"] / 1_000_000)
        return data, "schools_per_km2", "Schools per km2"
    if task_id == "T028":
        flood = flood_overlay_by_tract().groupby("tract_id", as_index=False)["flood_area_m2"].sum()
        data = data.merge(flood, on="tract_id", how="left")
        data["flood_area_m2"] = data["flood_area_m2"].fillna(0.0)
        return data, "flood_area_m2", "Flood exposure area"
    if task_id == "T029":
        counts = count_points("hospital_points", "hospital_count").drop(columns="geometry")
        data = data.merge(counts[["tract_id", "hospital_count"]], on="tract_id", how="left")
        return data, "hospital_count", "Hospital count"
    flood = flood_overlay_by_tract().groupby("tract_id", as_index=False)["flood_area_m2"].sum()
    schools = count_points("school_points", "school_count").drop(columns="geometry")
    data = data.merge(flood, on="tract_id", how="left").merge(schools[["tract_id", "school_count"]], on="tract_id", how="left")
    data[["flood_area_m2", "school_count"]] = data[["flood_area_m2", "school_count"]].fillna(0.0)
    data["combined_risk"] = data["temp_mean"].rank(pct=True) + data["flood_area_m2"].rank(pct=True) + (1 - data["school_count"].rank(pct=True))
    return data, "combined_risk", "Combined risk"


def execute_choropleth(task: dict[str, Any], spec: dict[str, Any], out_dir: Path) -> Path:
    data, fallback_field, legend = choropleth_data(task["task_id"])
    params = spec.get("params", {}) if isinstance(spec.get("params"), dict) else {}
    requested_field = params.get("field") if isinstance(params.get("field"), str) else fallback_field
    field = requested_field if requested_field in data.columns else fallback_field
    title = params.get("title") if isinstance(params.get("title"), str) else task["prompt"].split(".")[0]
    cmap = params.get("cmap") if isinstance(params.get("cmap"), str) else "viridis"
    path = out_dir / task["output"]
    fig, ax = plt.subplots(figsize=(9, 7))
    data.to_crs(3857).plot(column=field, ax=ax, cmap=cmap, legend=True, linewidth=0.05, edgecolor="white", missing_kwds={"color": "lightgrey"})
    ax.set_axis_off()
    ax.set_title(title, fontsize=12)
    fig.text(0.01, 0.02, f"{legend}. Source: controlled benchmark data profile.", fontsize=8)
    fig.tight_layout()
    fig.savefig(path, dpi=160)
    plt.close(fig)
    return path


def normalize_repairable_params(spec: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    repaired = json.loads(json.dumps(spec))
    repairs: list[str] = []
    params = repaired.get("params")
    if isinstance(params, dict) and isinstance(params.get("cmap"), str):
        original = params["cmap"]
        normalized = original.strip()
        if normalized.lower() == "viridis" and normalized != "viridis":
            params["cmap"] = "viridis"
            repairs.append(f"normalize_cmap:{original}->viridis")
    return repaired, repairs


EXECUTORS = {
    "buffer_service_area": execute_buffer,
    "overlay_intersection": execute_overlay,
    "point_count_join": execute_point_count,
    "raster_clip": execute_raster_clip,
    "zonal_statistics": execute_zonal,
    "choropleth_export": execute_choropleth,
}


def validate_output(task: dict[str, Any], path: Path) -> dict[str, Any]:
    if not path.exists() or path.stat().st_size == 0:
        return {"output_valid": 0, "row_or_pixel_count": 0, "required_fields_ok": 0, "geometry_or_raster_ok": 0}
    if path.suffix.lower() == ".gpkg":
        data = gpd.read_file(path)
        required = set(task.get("required_fields", []))
        required_ok = int(required.issubset(set(data.columns)))
        geom_ok = int(len(data) > 0 and data.geometry.notna().all() and bool(data.is_valid.all()))
        return {
            "output_valid": int(required_ok and geom_ok),
            "row_or_pixel_count": len(data),
            "required_fields_ok": required_ok,
            "geometry_or_raster_ok": geom_ok,
        }
    if path.suffix.lower() == ".tif":
        with rasterio.open(path) as src:
            arr = src.read(1, masked=True)
            valid_pixels = int(np.ma.count(arr))
            raster_ok = int(valid_pixels > 0 and src.crs is not None and src.transform is not None)
        return {"output_valid": raster_ok, "row_or_pixel_count": valid_pixels, "required_fields_ok": 1, "geometry_or_raster_ok": raster_ok}
    if path.suffix.lower() == ".png":
        return {"output_valid": int(path.stat().st_size > 10_000), "row_or_pixel_count": path.stat().st_size, "required_fields_ok": 1, "geometry_or_raster_ok": 1}
    return {"output_valid": 0, "row_or_pixel_count": 0, "required_fields_ok": 0, "geometry_or_raster_ok": 0}


def select_rows(args: argparse.Namespace) -> list[dict[str, str]]:
    rows = list(csv.DictReader(SCORES_PATH.open(newline="", encoding="utf-8")))
    if args.only_ready:
        rows = [r for r in rows if r["EXEC_READY"] == "1"]
    if args.modes:
        rows = [r for r in rows if r["mode"] in set(args.modes)]
    if args.models:
        rows = [r for r in rows if r["model"] in set(args.models)]
    if args.task_ids:
        rows = [r for r in rows if r["task_id"] in set(args.task_ids)]
    if args.families:
        rows = [r for r in rows if r["task_type"] in set(args.families)]
    rows.sort(key=lambda r: (MODE_ORDER.index(r["mode"]), r["model"], r["task_id"]))
    if args.max_contracts:
        rows = rows[: args.max_contracts]
    return rows


def summarize(rows: list[dict[str, Any]], prefix: str) -> None:
    if not rows:
        return
    OUT.mkdir(parents=True, exist_ok=True)
    by_mode: list[dict[str, Any]] = []
    for mode in MODE_ORDER:
        items = [r for r in rows if r["mode"] == mode]
        if not items:
            continue
        by_mode.append(
            {
                "mode": mode,
                "contracts": len(items),
                "contract_compatible_rate": f"{mean(int(r['contract_compatible']) for r in items):.4f}",
                "execution_success_rate": f"{mean(int(r['execution_success']) for r in items):.4f}",
                "output_valid_rate": f"{mean(int(r['output_valid']) for r in items):.4f}",
                "median_seconds": f"{pd.Series([float(r['duration_seconds']) for r in items]).median():.3f}",
            }
        )
    write_table(OUT / f"{prefix}_summary_by_mode.csv", by_mode)
    by_family: list[dict[str, Any]] = []
    for family in sorted({r["task_type"] for r in rows}):
        items = [r for r in rows if r["task_type"] == family]
        by_family.append(
            {
                "task_type": family,
                "contracts": len(items),
                "contract_compatible_rate": f"{mean(int(r['contract_compatible']) for r in items):.4f}",
                "execution_success_rate": f"{mean(int(r['execution_success']) for r in items):.4f}",
                "output_valid_rate": f"{mean(int(r['output_valid']) for r in items):.4f}",
                "top_error": Counter(r["error_type"] for r in items if r["error_type"]).most_common(1)[0][0]
                if any(r["error_type"] for r in items)
                else "",
            }
        )
    write_table(OUT / f"{prefix}_summary_by_family.csv", by_family)
    write_markdown(OUT / f"{prefix}_summary_by_mode.md", by_mode, "Execution Summary by Mode")
    write_markdown(OUT / f"{prefix}_summary_by_family.md", by_family, "Execution Summary by Task Family")


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
    cols = list(rows[0].keys())
    lines = [f"# {title}", "", "|" + "|".join(cols) + "|", "|" + "|".join(["---"] * len(cols)) + "|"]
    for row in rows:
        lines.append("|" + "|".join(str(row[c]) for c in cols) + "|")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-profile", choices=sorted(DATA_PROFILES), default="geoguard")
    parser.add_argument("--only-ready", action="store_true")
    parser.add_argument("--modes", nargs="*", default=None)
    parser.add_argument("--models", nargs="*", default=None)
    parser.add_argument("--task-ids", nargs="*", default=None)
    parser.add_argument("--families", nargs="*", default=None)
    parser.add_argument("--max-contracts", type=int, default=None)
    parser.add_argument("--output-prefix", default="contract_execution")
    parser.add_argument("--repair-policy", choices=["none", "role_defaults"], default="none")
    args = parser.parse_args()

    global LAYER_FILES
    LAYER_FILES = DATA_PROFILES[args.data_profile]
    missing_layers = [str(path.relative_to(ROOT)) for path in LAYER_FILES.values() if not path.exists()]
    if missing_layers:
        raise FileNotFoundError(f"data profile {args.data_profile} is missing files: {missing_layers}")

    tasks = {t["task_id"]: t for t in read_json(TASKS_PATH)}
    selected = select_rows(args)
    results: list[dict[str, Any]] = []
    for i, row in enumerate(selected, start=1):
        task = tasks[row["task_id"]]
        spec_path = SPECS / slug_model(row["model"]) / row["mode"] / f"{row['task_id']}_{row['mode']}.json"
        base = {
            "data_profile": args.data_profile,
            "model": row["model"],
            "mode": row["mode"],
            "task_id": row["task_id"],
            "task_type": row["task_type"],
            "planning_exec_ready": row["EXEC_READY"],
            "spec_path": str(spec_path.relative_to(ROOT)),
        }
        start = time.perf_counter()
        error_type = ""
        error_message = ""
        output_path = ""
        compatible = 0
        repair_applied = 0
        repair_notes = ""
        try:
            spec = read_json(spec_path)
            spec, param_repairs = normalize_repairable_params(spec) if args.repair_policy == "role_defaults" else (spec, [])
            expected = expected_layers(row["task_id"], row["task_type"])
            mentioned = spec_layer_mentions(spec)
            compatible = int(expected.issubset(mentioned))
            if not compatible:
                missing = sorted(expected - mentioned)
                if args.repair_policy == "role_defaults":
                    repair_applied = 1
                    repair_notes = ";".join(param_repairs + [f"default_layer_roles:{','.join(missing)}"])
                    compatible = 1
                else:
                    raise ValueError(f"missing expected layer mentions: {missing}")
            elif param_repairs:
                repair_applied = 1
                repair_notes = ";".join(param_repairs)
            path = EXECUTORS[row["task_type"]](task, spec, output_dir(row, args.data_profile))
            output_path = str(path.relative_to(ROOT))
            validation = validate_output(task, path)
            execution_success = 1
        except Exception as exc:  # noqa: BLE001 - captured into benchmark ledger
            validation = {"output_valid": 0, "row_or_pixel_count": 0, "required_fields_ok": 0, "geometry_or_raster_ok": 0}
            execution_success = 0
            error_type = type(exc).__name__
            error_message = repo_relative_message(str(exc))[:240]
        duration = time.perf_counter() - start
        result = {
            **base,
            "contract_compatible": compatible,
            "execution_success": execution_success,
            **validation,
            "duration_seconds": f"{duration:.3f}",
            "output_path": output_path,
            "repair_policy": args.repair_policy,
            "repair_applied": repair_applied,
            "repair_notes": repair_notes,
            "error_type": error_type,
            "error_message": error_message,
        }
        results.append(result)
        print(
            f"[{i}/{len(selected)}] {row['mode']} {row['model']} {row['task_id']} "
            f"compatible={compatible} success={execution_success} valid={validation['output_valid']}",
            flush=True,
        )

    OUT.mkdir(parents=True, exist_ok=True)
    result_path = OUT / f"{args.output_prefix}_results.csv"
    write_table(result_path, results)
    summarize(results, args.output_prefix)
    print(f"Wrote {result_path.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
