#!/usr/bin/env python3
"""Run the grounded GIS workflow benchmark across a local Ollama model panel."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
EXP_ROOT = ROOT / "experiments/07_grounded_gis_workflow_benchmark"
MODEL_PANEL = EXP_ROOT / "inputs/model_panel.json"
GENERATOR = EXP_ROOT / "scripts/generate_ollama_workflow_specs.py"
SCORER = EXP_ROOT / "scripts/score_workflow_specs.py"


def run(cmd: list[str]) -> None:
    print(" ".join(cmd), flush=True)
    subprocess.run(cmd, cwd=ROOT, check=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--models", nargs="*", default=None)
    parser.add_argument("--modes", nargs="+", default=["basic", "grounded", "geoguard"])
    parser.add_argument("--task-limit", type=int, default=None)
    parser.add_argument("--timeout", type=int, default=240)
    parser.add_argument("--skip-generation", action="store_true")
    args = parser.parse_args()

    models = args.models or json.loads(MODEL_PANEL.read_text(encoding="utf-8"))
    if len(models) < 10:
        raise SystemExit(f"Need at least 10 models for this experiment; got {len(models)}.")

    for model in models:
        if not args.skip_generation:
            cmd = [
                sys.executable,
                str(GENERATOR),
                "--model",
                model,
                "--modes",
                *args.modes,
                "--timeout",
                str(args.timeout),
            ]
            if args.task_limit:
                cmd.extend(["--task-limit", str(args.task_limit)])
            run(cmd)
        run([sys.executable, str(SCORER), "--model", model, "--modes", *args.modes])


if __name__ == "__main__":
    main()

