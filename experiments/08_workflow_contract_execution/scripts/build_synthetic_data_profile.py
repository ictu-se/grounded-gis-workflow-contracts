#!/usr/bin/env python3
"""Build a deterministic synthetic data profile for cross-dataset execution tests."""

from __future__ import annotations

import shutil
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
from rasterio.transform import from_origin
from shapely.geometry import Point, box


ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "data/synthetic/workflow_contract_profile_v1"
CRS = "EPSG:32648"


def write_gpkg(data: gpd.GeoDataFrame, name: str) -> None:
    path = OUT / name
    if path.exists():
        path.unlink()
    data.to_file(path, driver="GPKG")


def main() -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True, exist_ok=True)

    origin_x, origin_y = 500_000.0, 1_200_000.0
    cell = 2_000.0
    rows, cols = 5, 6

    tracts = []
    for row in range(rows):
        for col in range(cols):
            x0 = origin_x + col * cell
            y0 = origin_y - (row + 1) * cell
            geom = box(x0, y0, x0 + cell, y0 + cell)
            idx = row * cols + col + 1
            tracts.append(
                {
                    "tract_id": f"S{idx:03d}",
                    "land_area_m2": geom.area,
                    "district_name": f"Synthetic District {idx:03d}",
                    "geometry": geom,
                }
            )
    tracts_gdf = gpd.GeoDataFrame(tracts, crs=CRS)
    write_gpkg(tracts_gdf, "planning_districts.gpkg")

    boundary = gpd.GeoDataFrame(
        [{"boundary_id": "synthetic_metro", "geometry": box(origin_x, origin_y - rows * cell, origin_x + cols * cell, origin_y)}],
        crs=CRS,
    )
    write_gpkg(boundary, "metro_boundary.gpkg")

    hospitals = []
    for i, (col, row, dx, dy) in enumerate(
        [(0, 0, 900, -850), (2, 1, 500, -650), (4, 1, 1400, -1200), (1, 3, 1100, -600), (5, 4, 700, -900), (3, 4, 1500, -500)],
        start=1,
    ):
        hospitals.append(
            {
                "name": f"Synthetic Hospital {i}",
                "source_id": f"H{i:03d}",
                "geometry": Point(origin_x + col * cell + dx, origin_y - row * cell + dy),
            }
        )
    write_gpkg(gpd.GeoDataFrame(hospitals, crs=CRS), "health_facilities.gpkg")

    schools = []
    school_id = 1
    for row in range(rows):
        for col in range(cols):
            if (row + col) % 2 == 0:
                schools.append(
                    {
                        "name": f"Synthetic School {school_id}",
                        "source_id": f"SC{school_id:03d}",
                        "geometry": Point(origin_x + col * cell + 550, origin_y - row * cell - 550),
                    }
                )
                school_id += 1
            if row in {1, 3} and col in {1, 4}:
                schools.append(
                    {
                        "name": f"Synthetic School {school_id}",
                        "source_id": f"SC{school_id:03d}",
                        "geometry": Point(origin_x + col * cell + 1450, origin_y - row * cell - 1450),
                    }
                )
                school_id += 1
    write_gpkg(gpd.GeoDataFrame(schools, crs=CRS), "education_sites.gpkg")

    flood_zones = gpd.GeoDataFrame(
        [
            {"zone_id": "river_north", "sfha_tf": "T", "geometry": box(origin_x + 1_200, origin_y - 7_300, origin_x + 5_500, origin_y - 1_100)},
            {"zone_id": "river_south", "sfha_tf": "T", "geometry": box(origin_x + 6_000, origin_y - 10_000, origin_x + 10_800, origin_y - 4_600)},
            {"zone_id": "local_lowland", "sfha_tf": "F", "geometry": box(origin_x + 8_300, origin_y - 3_500, origin_x + 11_600, origin_y - 900)},
        ],
        crs=CRS,
    )
    write_gpkg(flood_zones, "river_flood_hazard.gpkg")

    width, height = 60, 50
    pixel = 200.0
    transform = from_origin(origin_x, origin_y, pixel, pixel)
    yy, xx = np.mgrid[0:height, 0:width]
    data = (23.0 + 0.08 * xx + 0.04 * yy + 1.5 * np.sin(xx / 8.0)).astype("float32")
    profile = {
        "driver": "GTiff",
        "height": height,
        "width": width,
        "count": 1,
        "dtype": "float32",
        "crs": CRS,
        "transform": transform,
        "nodata": -9999.0,
        "compress": "deflate",
    }
    with rasterio.open(OUT / "surface_temperature_utm.tif", "w", **profile) as dst:
        dst.write(data, 1)

    centroids = tracts_gdf.geometry.centroid
    tracts_gdf["temp_mean"] = 24.0 + (centroids.x - origin_x) / 4_000.0 + (origin_y - centroids.y) / 5_000.0
    tracts_gdf["temp_sum"] = tracts_gdf["temp_mean"] * 100
    write_gpkg(tracts_gdf, "district_map_input.gpkg")

    (OUT / "README.md").write_text(
        "Synthetic cross-dataset profile for experiment 08. "
        "It preserves benchmark layer roles while changing file names, CRS, geometries, point density, and raster transform.\n",
        encoding="utf-8",
    )
    print(f"Wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
