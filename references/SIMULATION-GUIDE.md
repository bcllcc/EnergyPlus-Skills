# Simulation Guide

## EnergyPlus CLI Reference

### Basic Usage
```
energyplus [options] input.idf
```

### All CLI Flags

| Flag | Short | Description |
|------|-------|-------------|
| `--help` | `-h` | Display help message |
| `--version` | `-v` | Show version info |
| `--weather FILE` | `-w` | Weather file path (.epw) |
| `--output-directory DIR` | `-d` | Output directory |
| `--output-prefix NAME` | | Prefix for output files |
| `--output-suffix STYLE` | | L=Legacy, C=Capital, D=Dash |
| `--idd FILE` | | Custom IDD path |
| `--design-day` | `-D` | Design-day only simulation |
| `--annual` | `-a` | Force annual simulation |
| `--expandobjects` | `-x` | Run ExpandObjects (required for HVACTemplate) |
| `--readvars` | `-r` | Run ReadVarsESO after simulation (generates CSV) |
| `--epmacro` | `-m` | Run EPMacro preprocessor |
| `--jobs N` | `-j` | Multi-thread with N threads |
| `--convert` | `-c` | Convert IDF to epJSON (or vice versa) |
| `--convert-only` | | Convert without simulation |

## Run Modes

### Design-Day Only (Fast)
For sizing and quick checks. No weather file needed.
```
python run_simulation.py --idf model.idf --design-day --expand-objects --readvars
```

### Annual Simulation (Full)
Requires weather file. Produces complete energy results.
```
python run_simulation.py --idf model.idf --weather path/to/weather.epw --expand-objects --readvars
```

### Design-Day + Annual (Two-Step)
1. Run design-day first to check for errors
2. If clean, run annual for full results

## HVACTemplate Expansion

### Why `-x` is Required
HVACTemplate objects are simplified HVAC specifications. EnergyPlus cannot simulate them directly. The `ExpandObjects` preprocessor converts them into detailed HVAC objects.

When HVACTemplate objects are present:
- **Without `-x`**: Simulation fails with "IP: IDF line~NNN Object=HVACTemplate..."
- **With `-x`**: ExpandObjects runs first, creating an expanded IDF

### What Happens During Expansion
1. ExpandObjects reads the IDF
2. Converts each HVACTemplate into multiple detailed objects (ZoneHVAC, AirLoop, Plant, etc.)
3. Writes an expanded IDF file (`expanded.idf`) in the output directory
4. EnergyPlus simulates the expanded version

### Detecting HVACTemplate Usage
```
python idf_helper.py check-hvactemplate model.idf
```

## EPMacro Preprocessor

Use `-m` flag when the IDF contains `##include` or `##def` directives.

```
##include CommonObjects.idf
##def MyMaterial[]
Material,
    ...;
##enddef
```

## Post-Processing Pipeline

### Standard Pipeline
```
IDF → EnergyPlus → .eso/.mtr → ReadVarsESO → .csv
                  → .err (always generated)
                  → .html (if Output:Table:SummaryReports)
                  → .sql (if Output:SQLite)
```

### ReadVarsESO
Converts binary .eso output to human-readable .csv.
Triggered by `--readvars` flag.
Located in the EnergyPlus installation: `PostProcess/ReadVarsESO.exe`

### Direct CSV vs SQL
- **CSV** (via ReadVarsESO): Simple time-series data, easy to parse
- **SQL** (via Output:SQLite): Complete database with tabular reports, time-series, and metadata

Recommendation: Always include both `--readvars` flag and `Output:SQLite` in IDF for maximum flexibility.

## Multi-Threading

Use `-j N` for large models to speed up simulation:
```
python run_simulation.py --idf large_model.idf --weather weather.epw --jobs 4 --expand-objects --readvars
```

Benefits are most significant for:
- Models with many zones (>20)
- Models with complex HVAC systems
- Annual simulations

## Batch Simulation

For parametric studies, create variants and run sequentially:
```python
# Example workflow:
# 1. Copy base IDF
# 2. Modify parameter (e.g., insulation thickness)
# 3. Run simulation with unique output directory
# 4. Repeat for each variant
# 5. Compare results
```

## IDF to epJSON Conversion

Convert between formats without running simulation:
```
energyplus --convert-only model.idf
```

## Timeout Handling

Default timeout: 600 seconds (10 minutes).

Expected run times:
- Design-day, small model: 5-30 seconds
- Annual, small model (10 zones): 1-5 minutes
- Annual, medium model (50 zones): 5-20 minutes
- Annual, large model (100+ zones): 20-60+ minutes

If timeout occurs, consider:
1. Running design-day only first
2. Reducing the number of output variables
3. Using multi-threading (`--jobs`)
4. Increasing the timestep (fewer timesteps per hour)
5. Increasing the timeout value

## Weather File Selection

EnergyPlus ships with sample EPW files in its `WeatherData/` directory.

For other locations, download from:
- https://climate.onebuilding.org
- https://energyplus.net/weather
