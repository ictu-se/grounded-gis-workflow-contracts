# 08 Workflow Contract Execution

This follow-up experiment tests whether workflow contracts that pass the
planning-readiness gate in experiment 07 can be bound to real GeoGuard LA County
layers and executed into valid GIS artifacts. It also includes a synthetic
cross-dataset profile used to test whether repaired contract execution survives
a different CRS, geometry scale, file naming scheme, point distribution, and
raster transform.

## Research Question

Do workflow-contract readiness scores predict downstream deterministic GIS
execution success?

## Inputs

- Contract scores: `experiments/07_grounded_gis_workflow_benchmark/outputs/gsis_extension/task_scores_with_execution_readiness.csv`
- Contract JSON files: `experiments/07_grounded_gis_workflow_benchmark/outputs/generated_specs/`
- Primary GIS data: `data/raw/geoguard/geoguard/data/`
- Synthetic GIS data: `data/synthetic/workflow_contract_profile_v1/`

## Execution Gate

The runner records two downstream checks.

- `contract_compatible`: the contract mentions the real layers required for the
  task family, so a deterministic executor can bind inputs to roles.
- `execution_success` and `output_valid`: the bound operation runs and produces
  a non-empty vector, raster, or PNG artifact with required fields and basic
  geometry/raster/file checks.

## Commands

Smoke test:

```bash
python3 experiments/08_workflow_contract_execution/scripts/run_contract_execution.py \
  --only-ready --modes geoguard --max-contracts 12
```

Full ready-contract execution sweep:

```bash
python3 experiments/08_workflow_contract_execution/scripts/run_contract_execution.py --only-ready
```

Build and run the synthetic cross-dataset profile:

```bash
python3 experiments/08_workflow_contract_execution/scripts/build_synthetic_data_profile.py
python3 experiments/08_workflow_contract_execution/scripts/run_contract_execution.py \
  --data-profile synthetic \
  --repair-policy role_defaults \
  --output-prefix synthetic_repaired_contract_execution
```

Run the mutation-based negative-control audit:

```bash
python3 experiments/08_workflow_contract_execution/scripts/run_contract_negative_control_audit.py
```

## Current Results

The full sweep executed 234 contracts that had passed the experiment-07
readiness gate:

| Mode | Ready contracts executed | Compatible | Valid artifacts |
|---|---:|---:|---:|
| Basic | 6 | 6 | 6 |
| Grounded | 97 | 89 | 89 |
| GeoGuard | 131 | 117 | 115 |

Interpretation for the manuscript: the earlier readiness gate is directionally
useful, but not sufficient. Some contracts that score as execution-ready still
fail deterministic binding because layer mentions are incomplete or because map
parameters are syntactically invalid for the target rendering library.

The synthetic repaired full-cohort run produced the same mode-level valid
artifact counts as the GeoGuard repaired run: Basic 268, Grounded 304, and
GeoGuard 301 out of 360. Artifact-size signatures differ strongly between the
two profiles, confirming that the second run regenerates outputs on different
geometries and rasters rather than reusing LA County artifacts.

The negative-control audit started from 506 strict-valid base contracts and
created 2165 controlled contract mutations. Detection rates ranged from 94.3%
for missing-layer-role mutations to 100.0% for wrong operation, wrong output,
invalid colormap, and unsafe metric-buffer CRS mutations.

## Outputs

- `outputs/contract_execution_results.csv`: one row per executed ready contract.
- `outputs/execution_summary_by_mode.csv` and `.md`: mode-level rates.
- `outputs/execution_summary_by_family.csv` and `.md`: task-family rates.
- `outputs/synthetic_repaired_contract_execution_results.csv`: synthetic
  profile repaired full-cohort ledger.
- `outputs/cross_dataset_mode_comparison.csv`: GeoGuard vs synthetic mode-level
  comparison.
- `outputs/cross_dataset_artifact_signature.csv`: GeoGuard vs synthetic
  family-level validity and artifact-size signatures.
- `outputs/contract_negative_control_audit.csv`: one row per injected contract
  fault.
- `outputs/contract_negative_control_summary.csv`: detection rates by mutation
  type.
- `outputs/artifacts/`: generated `.gpkg`, `.tif`, and `.png` outputs.
