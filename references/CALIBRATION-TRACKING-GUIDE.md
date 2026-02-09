# Calibration Tracking Guide

## Purpose

This guide defines the required tracking format for calibration runs.  
Every calibration iteration must be reproducible and auditable:

- Which IDF version was used
- Which parameters changed in that iteration
- How metrics changed relative to measured data

## Required Folder Layout

```text
test_output/calibration_history/
  run_<YYYYMMDD_HHMMSS>/
    run_meta.json
    iteration_log.csv
    iteration_log.jsonl
    idf_versions/
      iter_000_baseline.idf
      iter_001_<tag>.idf
      iter_002_<tag>.idf
    metrics/
      iter_000_metrics.json
      iter_001_metrics.json
      iter_002_metrics.json
    notes/
      iter_000.md
      iter_001.md
      iter_002.md
```

## Required Fields (`iteration_log.csv`)

- `run_id`
- `iteration`
- `timestamp`
- `idf_version`
- `idf_path`
- `epw_path`
- `simulated_path`
- `measured_path`
- `variable`
- `key_value`
- `changed_params_json`
- `n_points`
- `rmse`
- `cv_rmse`
- `mbe`
- `nmbe`
- `r2`
- `max_dev`
- `delta_cv_rmse_vs_prev`
- `delta_nmbe_vs_prev`
- `pass_ashrae14`
- `granularity`
- `note`

`changed_params_json` should be a compact JSON object with parameter deltas, for example:

```json
{
  "People:Office Occupancy Schedule": {
    "from": "Office_Weekday_Sch",
    "to": "Office_Weekday_Sch_v2"
  },
  "WindowMaterial:SimpleGlazingSystem.UFactor": {
    "from": 3.1,
    "to": 2.6
  }
}
```

## Tracking Rules

1. Log one row for every calibration iteration, including baseline iteration `0`.
2. Save an IDF snapshot for every iteration under `idf_versions/`.
3. Save metrics JSON for every iteration under `metrics/`.
4. `delta_cv_rmse_vs_prev` and `delta_nmbe_vs_prev` are relative to the previous iteration.
5. `pass_ashrae14` is `true` only when both criteria pass:
   - Hourly: `CV(RMSE) <= 30%` and `|NMBE| <= 10%`
   - Monthly: `CV(RMSE) <= 15%` and `|NMBE| <= 5%`
6. Do not overwrite prior iteration artifacts.

## Recommended Commands

1. Compute metrics:

```bash
python scripts/calibration.py metrics \
  --simulated "output/eplusout.sql" \
  --measured "measured.csv" \
  --variable "Zone Mean Air Temperature"
```

2. Compute metrics and auto-record in one command (preferred):

```bash
python scripts/calibration.py metrics \
  --simulated "output/eplusout.sql" \
  --measured "measured.csv" \
  --variable "Zone Mean Air Temperature" \
  --record-dir "test_output/calibration_history/run_20260209_143000" \
  --run-id "run_20260209_143000" \
  --iteration 1 \
  --idf-version "v1_window_u26" \
  --idf-path "models/W0_v1.idf" \
  --epw-path "weather/lhasa.epw" \
  --changed-params "{\"WindowMaterial:SimpleGlazingSystem.UFactor\":{\"from\":3.1,\"to\":2.6}}" \
  --record-note "Reduced glazing U-factor"
```

3. Record iteration with tracker script (fallback):

```bash
python scripts/calibration_tracker.py record \
  --run-dir "test_output/calibration_history/run_20260209_143000" \
  --run-id "run_20260209_143000" \
  --iteration 1 \
  --idf-version "v1_window_u26" \
  --idf-path "models/W0_v1.idf" \
  --epw-path "weather/lhasa.epw" \
  --simulated "output/eplusout.sql" \
  --measured "实测数据.csv" \
  --variable "Zone Mean Air Temperature" \
  --changed-params "{\"WindowMaterial:SimpleGlazingSystem.UFactor\":{\"from\":3.1,\"to\":2.6}}" \
  --note "Reduced glazing U-factor"
```

4. Review summary:

```bash
python scripts/calibration_tracker.py summary \
  --run-dir "test_output/calibration_history/run_20260209_143000"
```
