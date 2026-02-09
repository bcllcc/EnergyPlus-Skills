---
name: energyplus-skill
description: Create, edit, and validate EnergyPlus IDF input files. Run building energy simulations and analyze results. Generate visualizations from simulation output data. Modify weather files (EPW), run parametric studies, and calibrate models against measured data. Use when working with EnergyPlus, IDF files, building energy modeling, HVAC design, thermal simulation, energy analysis, EPW weather files, parametric comparison, baseline calibration, or building geometry.
---

# EnergyPlus-Skill

## Environment

- EnergyPlus executable: auto-detected via `ENERGYPLUS_EXE` env var, PATH, or fallback
- IDD schema: auto-detected via `ENERGYPLUS_IDD` env var, or next to EnergyPlus exe
- Scripts: relative to this skill at `scripts/`
- All scripts use Python standard library + matplotlib. No additional pip installs.

## Quick Decision Tree

- **Create/edit IDF file** -> Workflow 1: IDF Editing
- **Run a simulation** -> Workflow 2: Simulation
- **Analyze results or view data** -> Workflow 3: Analysis
- **Generate charts/plots** -> Workflow 4: Visualization
- **EPW file operations** -> use `epw_helper.py` (run `--help` for subcommands)
- **Baseline calibration** -> Workflow 5: Calibration
- **Parametric comparison** -> Workflow 6: Parametric Study
- **Building geometry** -> use `geometry_helper.py` (run `--help` for subcommands)
- **Look up an IDF object type** -> use `idd_lookup.py` (run `--help` for options)

## Workflow 1: IDF File Editing

1. **Clarify scope**: Determine which IDF objects need modification.

2. **Look up object schema** if unsure about fields or valid values:
   ```
   python .../scripts/idd_lookup.py "ObjectType"
   ```
   NEVER read the full IDD file directly.

3. **Read relevant IDF section**: Search for `!- =========== ALL OBJECTS IN CLASS: OBJECTTYPE ===========`. Do NOT read the entire IDF at once.

4. **Edit the IDF** following syntax rules:
   - Objects: `ObjectType, field1, field2, ..., lastfield;`
   - Commas separate fields, semicolon terminates
   - Comments: `!- description`

5. **Validate** after editing:
   ```
   python .../scripts/idf_helper.py validate "path/to/file.idf"
   ```

For detailed syntax, read [IDF-EDITING-GUIDE.md](references/IDF-EDITING-GUIDE.md).

## Workflow 2: Running Simulations

1. **Pre-flight check**:
   - Verify runtime discovery first:
   ```
   python .../scripts/run_simulation.py --check-env
   ```
   - If auto-discovery fails, use manual overrides:
   ```
   python .../scripts/run_simulation.py --check-env --energyplus-exe "path/to/energyplus" --idd "path/to/Energy+.idd"
   ```
   - You can also set `ENERGYPLUS_EXE` / `ENERGYPLUS_IDD` environment variables.

2. **Determine run mode**:
   - Design-day only: `--design-day` (fast, for sizing)
   - Annual: `--weather <epw>` required
   - Uses HVACTemplate: MUST add `--expand-objects`

3. **Run simulation**:
   ```
   python .../scripts/run_simulation.py --idf "file.idf" --weather "weather.epw" --output-dir "output" [--design-day] [--expand-objects] [--readvars] [--energyplus-exe "path/to/energyplus"] [--idd "path/to/Energy+.idd"]
   ```

4. **Check .err file** IMMEDIATELY:
   ```
   python .../scripts/parse_outputs.py errors "path/to/output"
   ```
   Fatal = failed; Severe = review; Warnings = OK.

5. **If failed**: Consult [COMMON-ERRORS.md](references/COMMON-ERRORS.md).

For CLI details, read [SIMULATION-GUIDE.md](references/SIMULATION-GUIDE.md).

### Critical Flags

| Scenario | Required Flags |
|---|---|
| IDF uses HVACTemplate | `--expand-objects` |
| Annual run | `--weather <epw>` |
| Design-day only | `--design-day` |
| Want CSV output | `--readvars` |

## Workflow 3: Output Analysis

1. **Parse outputs**:
   ```
   python .../scripts/parse_outputs.py summary "path/to/output"
   python .../scripts/parse_outputs.py timeseries "path/to/output" --variable "Zone Mean Air Temperature"
   python .../scripts/parse_outputs.py sql "path/to/output" --query "SELECT ..."
   python .../scripts/parse_outputs.py available-vars "path/to/output"
   ```

2. **Interpret results**: Analyze key metrics (total energy, EUI, peak loads, unmet hours).

For output formats and SQL schema, read [OUTPUT-ANALYSIS-GUIDE.md](references/OUTPUT-ANALYSIS-GUIDE.md).

## Workflow 4: Visualization

### Decision
1. If the need matches a preset type -> use `visualize_results.py` (run `--help` for types)
2. If custom chart is needed -> write matplotlib code directly
3. **All charts** must follow [VISUALIZATION-STYLE-GUIDE.md](references/VISUALIZATION-STYLE-GUIDE.md)

Preset types: `line`, `end-use-bar`, `monthly`, `heatmap`, `comparison`, `load-profile`.

### Custom Charts
When preset types don't suffice, write matplotlib code following the style guide's color palette, typography, layout, and annotation standards. Reference the guide before creating any custom chart.

## Workflow 5: Baseline Calibration

### Trigger
User mentions: calibration, baseline verification, measured data comparison, RMSE, CV(RMSE), model validation

### SOP
1. **Understand requirements**: Confirm measured data format (CSV), comparison variable, time range.
2. **Initialize a calibration run**:
   - Define `run_id` and `run_dir` (example: `test_output/calibration_history/run_20260209_143000`)
   - Decide baseline IDF version label (example: `baseline`)
   - Read [CALIBRATION-TRACKING-GUIDE.md](references/CALIBRATION-TRACKING-GUIDE.md)
3. **Process weather data** (if needed):
   - Read [EPW-FORMAT-GUIDE.md](references/EPW-FORMAT-GUIDE.md)
   - Use `epw_helper.py inject` to inject measured weather into EPW
4. **Run simulation**: Use `run_simulation.py` with baseline/modified IDF + target EPW
5. **Calculate metrics and compare**:
   ```
   python .../scripts/calibration.py compare --simulated "output/eplusout.sql" --measured "measured.csv" --variable "Zone Mean Air Temperature" --output-dir "calibration" --meas-column "Temperature"
   ```
   Or for metrics only (no chart):
   ```
   python .../scripts/calibration.py metrics --simulated "output/eplusout.sql" --measured "measured.csv" --variable "Zone Mean Air Temperature"
   ```
6. **Record this iteration immediately** (required for every round):
   - Preferred: use built-in auto-tracking in `calibration.py`:
   ```
   python .../scripts/calibration.py metrics \
       --simulated "output/eplusout.sql" \
       --measured "measured.csv" \
       --variable "Zone Mean Air Temperature" \
       --record-dir "test_output/calibration_history/run_20260209_143000" \
       --run-id "run_20260209_143000" \
       --iteration 0 \
       --idf-version "baseline" \
       --idf-path "W0_baseline.idf" \
       --epw-path "weather.epw" \
       --changed-params "{}" \
       --record-note "Initial baseline run"
   ```
   - Fallback: call tracker directly:
   ```
   python .../scripts/calibration_tracker.py record \
       --run-dir "test_output/calibration_history/run_20260209_143000" \
       --run-id "run_20260209_143000" \
       --iteration 0 \
       --idf-version "baseline" \
       --idf-path "W0_baseline.idf" \
       --epw-path "weather.epw" \
       --simulated "output/eplusout.sql" \
       --measured "measured.csv" \
       --variable "Zone Mean Air Temperature" \
       --changed-params "{}" \
       --note "Initial baseline run"
   ```
7. **Judge compliance**: ASHRAE Guideline 14 criteria:
   - Hourly: CV(RMSE) <= 30%, NMBE <= +-10%
   - Monthly: CV(RMSE) <= 15%, NMBE <= +-5%
8. **If not calibrated**:
   - Analyze deviation patterns and propose parameter adjustments
   - Get user confirmation before modifying IDF
   - Re-run from step 4 with `iteration + 1`
   - Update `--changed-params` and `--idf-version` for the new round
9. **Produce run summary**:
   ```
   python .../scripts/calibration_tracker.py summary --run-dir "test_output/calibration_history/run_20260209_143000"
   ```

## Workflow 6: Parametric Study

### Trigger
User mentions: parametric, comparison, variant, batch simulation, sensitivity analysis, parameter sweep

### SOP
1. **Define parameter and variants**: Identify which IDF object/field to vary and the values
2. **Generate template** (optional, helps identify current values):
   ```
   python .../scripts/parametric_runner.py generate-template --base "file.idf" --object-type "ObjectType" --object-name "Name" --fields "1,2"
   ```
3. **Create variants JSON**: Define parameter_name, variants array with name + changes.
   Run `parametric_runner.py --help` for JSON format details.
   Key: field_index is 0-based (0 = Name field, first field after object type).
4. **Run batch simulation**:
   ```
   python .../scripts/parametric_runner.py run --base "file.idf" --variants "variants.json" --output-dir "parametric" [--design-day] [--expand-objects] [--weather "file.epw"] [--compare total]
   ```
   Supports resume: re-running skips completed variants automatically.
5. **Regenerate report** (from existing results):
   ```
   python .../scripts/parametric_runner.py report --results-dir "parametric" [--compare peak_heating]
   ```
   Compare variables: total, heating, cooling, eui, peak_heating, peak_cooling

## Key Constraints

1. Always check .err file after every simulation.
2. NEVER load the full IDD into context. Use idd_lookup.py.
3. NEVER read the entire IDF at once. Read sections on demand.
4. Use parse_outputs.py to extract specific data rather than reading raw output files.
5. EPW field index is 0-based in code (position 6 = Dry Bulb Temperature). See EPW-FORMAT-GUIDE.md.
6. Parametric runner field_index is 0-based: 0 = Name field (first field after object type).
7. Every calibration iteration MUST be logged to local history with IDF version and changed parameters.

## Tools Reference

| Script | Purpose |
|--------|---------|
| `idd_lookup.py` | IDD schema query |
| `idf_helper.py` | IDF validate / summary / object extraction |
| `run_simulation.py` | Simulation execution wrapper |
| `parse_outputs.py` | Output parsing (err/csv/sql/html) |
| `visualize_results.py` | 6 preset chart types |
| `epw_helper.py` | EPW read/write/inject/validate/stats |
| `parametric_runner.py` | Batch parametric study with comparison |
| `calibration.py` | Model calibration (ASHRAE Guideline 14) |
| `calibration_tracker.py` | Calibration iteration tracking and history logging |
| `geometry_helper.py` | Surface geometry list/modify/create |

All scripts support `--help` for detailed usage.

## Reference Materials

- [IDF Editing Guide](references/IDF-EDITING-GUIDE.md) - IDF syntax, common objects, field rules
- [Simulation Guide](references/SIMULATION-GUIDE.md) - CLI flags, HVACTemplate expansion
- [Output Analysis Guide](references/OUTPUT-ANALYSIS-GUIDE.md) - File formats, SQL schema, reports
- [Common Errors](references/COMMON-ERRORS.md) - Error patterns and resolution strategies
- [Object Quick Reference](references/OBJECT-QUICK-REF.md) - Top 50 object types with field summaries
- [EPW Format Guide](references/EPW-FORMAT-GUIDE.md) - EPW file structure, 35 fields, missing data rules
- [Calibration Tracking Guide](references/CALIBRATION-TRACKING-GUIDE.md) - Required run folder layout and iteration log schema
- [Visualization Style Guide](references/VISUALIZATION-STYLE-GUIDE.md) - Chart colors, fonts, layout standards
