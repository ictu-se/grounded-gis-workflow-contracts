# Run Log

## 2026-06-29

- Initialized experiment track for a local Ollama panel with 12 models.
- Copied the 30-task GIS workflow-spec suite from the prior GeoGuard evaluator track into this standalone experiment.
- Added standalone generation, scoring, panel-runner, and aggregation scripts.
- Completed smoke run: 12 local Ollama models x 3 modes x first 3 workflow tasks = 108 attempted workflow specifications.
- Aggregated outputs:
  - `outputs/scores/model_comparison_summary.csv`
  - `outputs/scores/model_comparison_summary.md`
- Mirrored smoke summary into the manuscript track:
  - `manuscripts/04_q1_grounded_gis_workflow_benchmark/tables/model_comparison_summary_smoke.csv`
  - `manuscripts/04_q1_grounded_gis_workflow_benchmark/tables/model_comparison_summary_smoke.md`
- Early result pattern:
  - Several coder/general models fail or weaken in `basic` mode because they hallucinate data or emit malformed JSON.
  - `grounded` usually improves data validity and output compliance.
  - `geoguard` often produces the strongest plan reliability score for the buffer-task smoke subset.
  - `qwen3:4b` and `phi3:mini` failed JSON/spec extraction across the smoke subset under the current prompt protocol.

Next run:

```bash
python3 experiments/07_grounded_gis_workflow_benchmark/scripts/run_model_panel.py --timeout 300
python3 experiments/07_grounded_gis_workflow_benchmark/scripts/aggregate_scores.py
```
