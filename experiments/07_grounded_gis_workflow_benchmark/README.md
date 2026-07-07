# 07 Grounded GIS Workflow Benchmark

This track evaluates local Ollama models as GIS copilot planners. The experimental unit is a structured workflow specification, not free-form Python code.

## Research Question

Do metadata grounding, tool schemas, and GeoGuard-style validation rules reduce hallucination and planning failures in LLM-generated GIS workflow specifications?

## Initial Local Model Panel

The first panel intentionally includes at least 10 locally available Ollama models:

- `qwen2.5-coder:1.5b`
- `qwen2.5-coder:3b`
- `qwen2.5-coder:7b`
- `qwen2.5-coder:14b`
- `qwen2.5-coder:32b`
- `deepseek-coder:6.7b`
- `qwen2.5:3b`
- `qwen3:4b`
- `llama3.2:3b`
- `phi3:mini`
- `mistral:7b`
- `gemma3:4b`

`mixtral:8x7b` is available locally but excluded from the initial full sweep because it is much larger; keep it as a reserve model if runtime permits.

## Modes

- `basic`: task only.
- `grounded`: task plus data profile and allowed tool schema.
- `geoguard`: grounded context plus validation and cartographic quality rules.

## Commands

Smoke test, 12 models x 3 modes x 3 tasks:

```bash
python3 experiments/07_grounded_gis_workflow_benchmark/scripts/run_model_panel.py --task-limit 3 --timeout 240
python3 experiments/07_grounded_gis_workflow_benchmark/scripts/aggregate_scores.py
```

Full planning benchmark, 12 models x 3 modes x 30 tasks:

```bash
python3 experiments/07_grounded_gis_workflow_benchmark/scripts/run_model_panel.py --timeout 300
python3 experiments/07_grounded_gis_workflow_benchmark/scripts/aggregate_scores.py
python3 experiments/07_grounded_gis_workflow_benchmark/scripts/build_gsis_extension_analysis.py
```

## Outputs

- `outputs/generated_specs/<model>/<mode>/*.json`
- `outputs/generated_specs/<model>/<mode>/*.raw.txt`
- `outputs/scores/<model>/workflow_task_scores.csv`
- `outputs/scores/<model>/workflow_summary.csv`
- `outputs/scores/model_comparison_summary.csv`
- `outputs/scores/model_comparison_summary.md`
- `outputs/gsis_extension/bootstrap_mode_effects.csv`
- `outputs/gsis_extension/execution_readiness_by_mode.csv`
- `outputs/gsis_extension/execution_readiness_by_family.csv`
