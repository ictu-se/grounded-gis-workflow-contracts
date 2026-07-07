# Run Log

## 2026-07-01

Created `experiments/08_workflow_contract_execution` as a downstream execution
experiment for the grounded GIS workflow benchmark.

Implemented `scripts/run_contract_execution.py`, which reads experiment-07
ready contracts, checks whether each contract can be bound to the real GeoGuard
LA County layers, executes the corresponding deterministic GIS operation, and
validates generated artifacts.

Smoke command:

```bash
python3 experiments/08_workflow_contract_execution/scripts/run_contract_execution.py --only-ready --modes geoguard --max-contracts 12
```

Smoke result: 12 of 12 selected GeoGuard-ready contracts executed and produced
valid artifacts.

Full command:

```bash
python3 experiments/08_workflow_contract_execution/scripts/run_contract_execution.py --only-ready
```

Full result: 234 ready contracts executed. Valid artifact counts were 6/6 for
basic, 89/97 for grounded, and 115/131 for GeoGuard.

Primary observed downstream blockers:

- 13 contracts missed the `study_boundary` layer needed for clipping/masking.
- 7 contracts missed `zonal_input_for_map` for choropleth export.
- 2 contracts missed `hospital_points`.
- 2 contracts bound the correct data but used an invalid Matplotlib colormap
  spelling (`Viridis`).
