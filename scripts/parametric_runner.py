#!/usr/bin/env python
"""EnergyPlus parametric study runner.

Batch-run EnergyPlus simulations with parameter variants and generate comparison reports.

Usage:
    python parametric_runner.py run --base <base.idf> --variants <variants.json>
        --output-dir <dir> [--weather <epw>] [--design-day] [--annual]
        [--expand-objects] [--compare <variable>]
    python parametric_runner.py generate-template --base <base.idf>
        --object-type <type> --object-name <name> --fields <indices>
    python parametric_runner.py report --results-dir <dir>

Variant JSON format:
{
  "parameter_name": "Window Type",
  "variants": [
    {
      "name": "Single_6mm",
      "changes": [
        {"object_type": "...", "object_name": "...", "field_index": 1, "new_value": "5.8"}
      ]
    }
  ]
}

field_index is 0-based: 0 = Name field (first field after object type).
"""

import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import time


SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))
RUN_SIM = os.path.join(SCRIPTS_DIR, "run_simulation.py")
PARSE_OUT = os.path.join(SCRIPTS_DIR, "parse_outputs.py")


# ---------------------------------------------------------------------------
# IDF modification
# ---------------------------------------------------------------------------

def modify_idf(src_path, dst_path, changes):
    """Copy an IDF file and apply field-level changes to specific objects.

    Each change is a dict with:
      - object_type: str (e.g. "WindowMaterial:SimpleGlazingSystem")
      - object_name: str (e.g. "Window_Glazing") - matched against field[0]
      - field_index: int (0-based, 0 = Name field)
      - new_value: str

    Strategy: parse IDF to locate objects, then do line-level replacement
    in the raw text to preserve formatting and comments.
    """
    # Read all lines
    with open(src_path, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()

    # Build a change lookup: (type_lower, name_lower) -> [(field_index, new_value)]
    change_map = {}
    for ch in changes:
        key = (ch["object_type"].lower(), ch["object_name"].lower())
        if key not in change_map:
            change_map[key] = []
        change_map[key].append((ch["field_index"], ch["new_value"]))

    # Parse IDF to find objects that need modification
    modified_count = 0
    result_lines = list(lines)  # copy

    # Track parsing state
    in_object = False
    obj_type = ""
    obj_lines_start = 0
    obj_field_values = []
    obj_field_line_indices = []  # which line each field is on
    obj_field_positions = []  # (start_col, end_col) of value within line

    i = 0
    while i < len(result_lines):
        line = result_lines[i]
        stripped = line.strip()

        if not in_object:
            if not stripped or stripped.startswith("!"):
                i += 1
                continue
            if not line[0].isspace() and not line.startswith("\t"):
                code_part = stripped.split("!")[0].strip()
                if code_part and ("," in code_part or ";" in code_part):
                    in_object = True
                    obj_lines_start = i
                    obj_field_values = []
                    obj_field_line_indices = []
                    obj_field_positions = []

                    # Extract type and possibly first fields from this line
                    _extract_fields_from_line(
                        code_part, i, obj_field_values,
                        obj_field_line_indices, obj_field_positions, line)

                    # Check for type
                    if obj_field_values:
                        obj_type = obj_field_values[0]

                    if ";" in code_part:
                        # Single-line object complete
                        _apply_changes(
                            obj_type, obj_field_values, obj_field_line_indices,
                            obj_field_positions, change_map, result_lines)
                        modified_count += _count_matches(
                            obj_type, obj_field_values, change_map)
                        in_object = False
            i += 1
            continue

        # Inside an object
        code_part = stripped.split("!")[0].strip()
        if code_part:
            _extract_fields_from_line(
                code_part, i, obj_field_values,
                obj_field_line_indices, obj_field_positions, line)

        if ";" in code_part:
            # Object complete
            _apply_changes(
                obj_type, obj_field_values, obj_field_line_indices,
                obj_field_positions, change_map, result_lines)
            modified_count += _count_matches(
                obj_type, obj_field_values, change_map)
            in_object = False

        i += 1

    with open(dst_path, "w", encoding="utf-8", newline="") as f:
        f.writelines(result_lines)

    return modified_count


def _extract_fields_from_line(code_part, line_idx, values, line_indices,
                               positions, full_line):
    """Extract field values from a code line, tracking their positions."""
    # Remove trailing comma or semicolon for splitting
    clean = code_part.rstrip(",; ")
    parts = [p.strip() for p in clean.split(",")]
    code_only = full_line.split("!")[0]

    for part in parts:
        if part:
            # Find position of this value in the original line
            start = code_only.find(part)
            values.append(part)
            line_indices.append(line_idx)
            positions.append((start, start + len(part) if start >= 0 else -1))


def _count_matches(obj_type, field_values, change_map):
    """Count how many changes match this object."""
    if len(field_values) < 2:
        return 0
    key = (obj_type.lower(), field_values[1].lower())  # values[0]=type, values[1]=name
    return 1 if key in change_map else 0


def _apply_changes(obj_type, field_values, field_line_indices,
                   field_positions, change_map, all_lines):
    """Apply matching changes to the lines of a specific object."""
    if len(field_values) < 2:
        return

    # field_values[0] = object type, field_values[1] = name (field[0])
    key = (obj_type.lower(), field_values[1].lower())
    if key not in change_map:
        return

    for field_idx, new_value in change_map[key]:
        # field_idx is 0-based: 0=Name. In field_values, index 0=type, so
        # the actual index is field_idx + 1
        actual_idx = field_idx + 1
        if actual_idx >= len(field_values):
            continue

        line_idx = field_line_indices[actual_idx]
        start, end = field_positions[actual_idx]
        if start < 0:
            continue

        old_line = all_lines[line_idx]
        old_value = field_values[actual_idx]

        # Replace the value in the line, preserving surrounding text
        code_part = old_line.split("!")[0]
        comment_part = ""
        if "!" in old_line:
            comment_part = "!" + old_line.split("!", 1)[1]

        # Replace old value with new value in code part
        new_code = code_part.replace(old_value, new_value, 1)
        all_lines[line_idx] = new_code + comment_part


# ---------------------------------------------------------------------------
# Result extraction from SQL
# ---------------------------------------------------------------------------

def extract_results(output_dir):
    """Extract key energy metrics from simulation output SQL database.

    Returns dict with keys: total_energy_gj, heating_gj, cooling_gj,
    eui_mj_m2, area_m2, peak_heating_w, peak_cooling_w,
    unmet_heating_hr, unmet_cooling_hr, status
    """
    results = {
        "total_energy_gj": None,
        "heating_gj": None,
        "cooling_gj": None,
        "eui_mj_m2": None,
        "area_m2": None,
        "peak_heating_w": None,
        "peak_cooling_w": None,
        "unmet_heating_hr": None,
        "unmet_cooling_hr": None,
        "status": "unknown",
    }

    # Check for err file first
    err_file = None
    for name in ("eplusout.err", "eplus.err"):
        p = os.path.join(output_dir, name)
        if os.path.exists(p):
            err_file = p
            break

    if err_file:
        with open(err_file, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()
        if "Fatal" in content and "EnergyPlus Terminated" in content:
            results["status"] = "FATAL"
            return results

    # Find SQL file
    sql_file = None
    for name in ("eplusout.sql", "eplus.sql"):
        p = os.path.join(output_dir, name)
        if os.path.exists(p):
            sql_file = p
            break

    if not sql_file:
        results["status"] = "no_sql"
        return results

    try:
        conn = sqlite3.connect(sql_file)
        c = conn.cursor()

        # Total Site Energy
        c.execute("""SELECT Value FROM TabularDataWithStrings
            WHERE ReportName='AnnualBuildingUtilityPerformanceSummary'
            AND TableName='Site and Source Energy'
            AND RowName='Total Site Energy' AND Units='GJ'
            LIMIT 1""")
        row = c.fetchone()
        if row:
            results["total_energy_gj"] = _safe_float(row[0])

        # Heating and Cooling from End Uses
        for end_use, key in [("Heating", "heating_gj"), ("Cooling", "cooling_gj")]:
            c.execute("""SELECT Value FROM TabularDataWithStrings
                WHERE ReportName='AnnualBuildingUtilityPerformanceSummary'
                AND TableName='End Uses' AND RowName=?
                AND ColumnName='Electricity' AND Units='GJ'""", (end_use,))
            row = c.fetchone()
            elec = _safe_float(row[0]) if row else 0.0
            c.execute("""SELECT Value FROM TabularDataWithStrings
                WHERE ReportName='AnnualBuildingUtilityPerformanceSummary'
                AND TableName='End Uses' AND RowName=?
                AND ColumnName='Natural Gas' AND Units='GJ'""", (end_use,))
            row = c.fetchone()
            gas = _safe_float(row[0]) if row else 0.0
            results[key] = (elec or 0) + (gas or 0)

        # EUI
        c.execute("""SELECT Value FROM TabularDataWithStrings
            WHERE ReportName='AnnualBuildingUtilityPerformanceSummary'
            AND TableName='Site and Source Energy'
            AND RowName='Total Site Energy' AND Units='MJ/m2'
            LIMIT 1""")
        row = c.fetchone()
        if row:
            results["eui_mj_m2"] = _safe_float(row[0])

        # Building Area
        c.execute("""SELECT Value FROM TabularDataWithStrings
            WHERE ReportName='AnnualBuildingUtilityPerformanceSummary'
            AND TableName='Building Area'
            AND RowName='Net Conditioned Building Area'""")
        row = c.fetchone()
        if row:
            results["area_m2"] = _safe_float(row[0])

        # Peak Heating Load (sum of all zones)
        c.execute("""SELECT SUM(CAST(Value AS REAL)) FROM TabularDataWithStrings
            WHERE ReportName='HVACSizingSummary'
            AND TableName='Zone Sensible Heating'
            AND ColumnName='Calculated Design Load' AND Units='W'""")
        row = c.fetchone()
        if row and row[0]:
            results["peak_heating_w"] = row[0]

        # Peak Cooling Load
        c.execute("""SELECT SUM(CAST(Value AS REAL)) FROM TabularDataWithStrings
            WHERE ReportName='HVACSizingSummary'
            AND TableName='Zone Sensible Cooling'
            AND ColumnName='Calculated Design Load' AND Units='W'""")
        row = c.fetchone()
        if row and row[0]:
            results["peak_cooling_w"] = row[0]

        # Unmet hours
        c.execute("""SELECT RowName, Value FROM TabularDataWithStrings
            WHERE ReportName='AnnualBuildingUtilityPerformanceSummary'
            AND TableName='Comfort and Setpoint Not Met Summary'""")
        for row_name, val in c.fetchall():
            v = _safe_float(val)
            if "Heating" in row_name and "Occupied" in row_name:
                results["unmet_heating_hr"] = v
            elif "Cooling" in row_name and "Occupied" in row_name:
                results["unmet_cooling_hr"] = v

        conn.close()
        results["status"] = "OK"

    except Exception as e:
        results["status"] = f"error: {e}"

    return results


def _safe_float(val):
    """Convert string to float, returning None on failure."""
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_run(args):
    """Run parametric study: modify IDF, simulate, compare results."""
    base_idf = os.path.abspath(args.base)
    variants_file = os.path.abspath(args.variants)
    output_dir = os.path.abspath(args.output_dir)

    if not os.path.exists(base_idf):
        print(f"Error: Base IDF not found: {base_idf}")
        sys.exit(1)
    if not os.path.exists(variants_file):
        print(f"Error: Variants file not found: {variants_file}")
        sys.exit(1)

    # Load variants
    with open(variants_file, "r", encoding="utf-8") as f:
        config = json.load(f)

    param_name = config.get("parameter_name", "Parameter")
    variants = config.get("variants", [])
    if not variants:
        print("Error: No variants defined in JSON file")
        sys.exit(1)

    os.makedirs(output_dir, exist_ok=True)

    print(f"=== Parametric Study: {param_name} ===")
    print(f"  Base IDF: {os.path.basename(base_idf)}")
    print(f"  Variants: {len(variants)}")
    print(f"  Output:   {output_dir}")
    print()

    all_results = []
    total_time = 0

    for i, variant in enumerate(variants):
        vname = variant.get("name", f"variant_{i}")
        changes = variant.get("changes", [])
        vdir = os.path.join(output_dir, vname)

        print(f"--- [{i+1}/{len(variants)}] {vname} ---")

        # Skip if already completed (resume support)
        result_marker = os.path.join(vdir, ".parametric_done")
        if os.path.exists(result_marker):
            print(f"  Skipping (already completed)")
            # Load cached results
            try:
                with open(result_marker, "r") as f:
                    cached = json.load(f)
                all_results.append({"name": vname, **cached})
                continue
            except Exception:
                pass  # re-run if cache is corrupted

        os.makedirs(vdir, exist_ok=True)

        # Modify IDF
        modified_idf = os.path.join(vdir, "modified.idf")
        mod_count = modify_idf(base_idf, modified_idf, changes)
        print(f"  Changes applied: {len(changes)} ({mod_count} objects modified)")

        # Build simulation command
        sim_cmd = [sys.executable, RUN_SIM, "--idf", modified_idf,
                   "--output-dir", vdir]
        if args.weather:
            sim_cmd.extend(["--weather", os.path.abspath(args.weather)])
        if args.design_day:
            sim_cmd.append("--design-day")
        if args.expand_objects:
            sim_cmd.append("--expand-objects")

        # Run simulation
        t0 = time.time()
        try:
            result = subprocess.run(
                sim_cmd, capture_output=True, text=True, timeout=600)
            elapsed = time.time() - t0
            total_time += elapsed
            print(f"  Simulation: {'OK' if result.returncode == 0 else 'FAILED'}"
                  f" ({elapsed:.1f}s)")
            if result.returncode != 0:
                # Print first few error lines
                for line in result.stdout.split("\n")[-5:]:
                    if line.strip():
                        print(f"    {line.strip()}")
        except subprocess.TimeoutExpired:
            elapsed = time.time() - t0
            total_time += elapsed
            print(f"  Simulation: TIMEOUT ({elapsed:.1f}s)")
            all_results.append({"name": vname, "status": "TIMEOUT"})
            continue

        # Extract results
        res = extract_results(vdir)
        res["name"] = vname
        res["time_s"] = round(elapsed, 1)
        all_results.append(res)

        # Cache results for resume
        with open(result_marker, "w") as f:
            json.dump({k: v for k, v in res.items() if k != "name"}, f)

    print()
    _print_comparison(param_name, all_results, output_dir, args.compare)


def cmd_generate_template(args):
    """Generate a variants.json template from an existing IDF."""
    base_idf = os.path.abspath(args.base)
    if not os.path.exists(base_idf):
        print(f"Error: IDF not found: {base_idf}")
        sys.exit(1)

    # Use idf_helper to parse
    sys.path.insert(0, SCRIPTS_DIR)
    from idf_helper import parse_idf

    objects = parse_idf(base_idf)
    target_type = args.object_type.lower()
    target_name = args.object_name.lower() if args.object_name else None
    field_indices = [int(x) for x in args.fields.split(",")]

    # Find matching objects
    matched = []
    for obj in objects:
        if obj["type"].lower() != target_type:
            continue
        if target_name and (not obj["fields"] or
                            obj["fields"][0].lower() != target_name):
            continue
        matched.append(obj)

    if not matched:
        print(f"Error: No objects found matching type='{args.object_type}'"
              f"{' name=' + args.object_name if args.object_name else ''}")
        sys.exit(1)

    # Build template
    obj = matched[0]
    current_values = {}
    for fi in field_indices:
        if fi < len(obj["fields"]):
            current_values[fi] = obj["fields"][fi]
        else:
            current_values[fi] = ""

    template = {
        "parameter_name": f"{obj['type']} variations",
        "variants": [
            {
                "name": "baseline",
                "changes": [
                    {
                        "object_type": obj["type"],
                        "object_name": obj["fields"][0] if obj["fields"] else "",
                        "field_index": fi,
                        "new_value": current_values[fi]
                    }
                    for fi in field_indices
                ]
            },
            {
                "name": "variant_1",
                "changes": [
                    {
                        "object_type": obj["type"],
                        "object_name": obj["fields"][0] if obj["fields"] else "",
                        "field_index": fi,
                        "new_value": f"<CHANGE_{fi}>"
                    }
                    for fi in field_indices
                ]
            }
        ]
    }

    output = json.dumps(template, indent=2, ensure_ascii=False)
    print(output)

    print(f"\n--- Current values ---")
    for fi in field_indices:
        print(f"  field[{fi}] = {current_values.get(fi, 'N/A')}")


def cmd_report(args):
    """Regenerate comparison report from existing results."""
    results_dir = os.path.abspath(args.results_dir)
    if not os.path.isdir(results_dir):
        print(f"Error: Directory not found: {results_dir}")
        sys.exit(1)

    # Find all variant subdirectories with .parametric_done marker
    all_results = []
    for entry in sorted(os.listdir(results_dir)):
        vdir = os.path.join(results_dir, entry)
        marker = os.path.join(vdir, ".parametric_done")
        if os.path.isdir(vdir) and os.path.exists(marker):
            try:
                with open(marker, "r") as f:
                    cached = json.load(f)
                all_results.append({"name": entry, **cached})
            except Exception:
                # Re-extract from SQL
                res = extract_results(vdir)
                res["name"] = entry
                all_results.append(res)

    if not all_results:
        print("No completed variant results found.")
        sys.exit(1)

    _print_comparison("Parametric Study", all_results, results_dir,
                      args.compare if hasattr(args, "compare") else None)


# ---------------------------------------------------------------------------
# Comparison output
# ---------------------------------------------------------------------------

def _print_comparison(param_name, all_results, output_dir, compare_var=None):
    """Print comparison table and optionally generate chart."""
    print(f"=== Parametric Comparison: {param_name} ===")
    print(f"  Variants: {len(all_results)}")
    ok_count = sum(1 for r in all_results if r.get("status") == "OK")
    print(f"  Successful: {ok_count}/{len(all_results)}")
    print()

    # Determine which columns have data
    has_energy = any(r.get("total_energy_gj") for r in all_results)
    has_peak = any(r.get("peak_heating_w") for r in all_results)

    if has_energy:
        # Annual results table
        header = (f"  {'Variant':<30s} {'Total(GJ)':>10s} {'Heat(GJ)':>10s} "
                  f"{'Cool(GJ)':>10s} {'EUI(MJ/m2)':>11s} {'Status':>8s}")
        print(header)
        print(f"  {'-'*79}")
        for r in all_results:
            name = r.get("name", "?")[:30]
            total = _fmt(r.get("total_energy_gj"))
            heat = _fmt(r.get("heating_gj"))
            cool = _fmt(r.get("cooling_gj"))
            eui = _fmt(r.get("eui_mj_m2"))
            status = r.get("status", "?")
            print(f"  {name:<30s} {total:>10s} {heat:>10s} "
                  f"{cool:>10s} {eui:>11s} {status:>8s}")

    if has_peak:
        print()
        header = (f"  {'Variant':<30s} {'PeakHeat(W)':>12s} "
                  f"{'PeakCool(W)':>12s} {'Status':>8s}")
        print(header)
        print(f"  {'-'*62}")
        for r in all_results:
            name = r.get("name", "?")[:30]
            ph = _fmt(r.get("peak_heating_w"), 0)
            pc = _fmt(r.get("peak_cooling_w"), 0)
            status = r.get("status", "?")
            print(f"  {name:<30s} {ph:>12s} {pc:>12s} {status:>8s}")

    if not has_energy and not has_peak:
        for r in all_results:
            print(f"  {r.get('name', '?'):<30s} status={r.get('status', '?')}")

    # Save results as JSON
    results_json = os.path.join(output_dir, "comparison_results.json")
    with open(results_json, "w", encoding="utf-8") as f:
        json.dump({"parameter_name": param_name, "results": all_results},
                  f, indent=2, ensure_ascii=False)
    print(f"\n  Results saved: {results_json}")

    # Generate comparison chart if requested
    if compare_var and has_energy:
        _generate_chart(all_results, compare_var, param_name, output_dir)
    elif compare_var and has_peak:
        _generate_chart(all_results, compare_var, param_name, output_dir)


def _fmt(val, decimals=2):
    """Format a numeric value for display."""
    if val is None:
        return "N/A"
    if decimals == 0:
        return f"{val:.0f}"
    return f"{val:.{decimals}f}"


def _generate_chart(all_results, compare_var, param_name, output_dir):
    """Generate a horizontal bar chart comparing variants."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("  Warning: matplotlib not available, skipping chart")
        return

    # Map compare variable to result key
    var_map = {
        "total": ("total_energy_gj", "Total Energy (GJ)"),
        "heating": ("heating_gj", "Heating Energy (GJ)"),
        "cooling": ("cooling_gj", "Cooling Energy (GJ)"),
        "eui": ("eui_mj_m2", "EUI (MJ/m2)"),
        "peak_heating": ("peak_heating_w", "Peak Heating Load (W)"),
        "peak_cooling": ("peak_cooling_w", "Peak Cooling Load (W)"),
    }

    key_name = compare_var.lower().replace(" ", "_")
    if key_name not in var_map:
        # Try partial match
        for k in var_map:
            if key_name in k:
                key_name = k
                break
        else:
            print(f"  Warning: Unknown compare variable '{compare_var}'")
            print(f"  Available: {', '.join(var_map.keys())}")
            return

    result_key, label = var_map[key_name]

    # Extract data
    names = []
    values = []
    for r in all_results:
        v = r.get(result_key)
        if v is not None and r.get("status") == "OK":
            names.append(r["name"])
            values.append(v)

    if not values:
        print(f"  Warning: No data available for '{compare_var}'")
        return

    # Create horizontal bar chart
    fig, ax = plt.subplots(figsize=(10, max(4, len(names) * 0.5 + 1)))

    colors = plt.cm.Set2(range(len(names)))
    bars = ax.barh(range(len(names)), values, color=colors, edgecolor="white",
                   linewidth=0.5)

    ax.set_yticks(range(len(names)))
    ax.set_yticklabels(names, fontsize=9)
    ax.set_xlabel(label, fontsize=11)
    ax.set_title(f"Parametric Comparison: {param_name}", fontsize=13,
                 fontweight="bold")
    ax.invert_yaxis()
    ax.grid(axis="x", alpha=0.3, linestyle="--")

    # Add value labels
    for bar, val in zip(bars, values):
        ax.text(bar.get_width() + max(values) * 0.01, bar.get_y() + bar.get_height() / 2,
                f" {val:.2f}", va="center", fontsize=8)

    plt.tight_layout()
    chart_path = os.path.join(output_dir, "comparison_chart.png")
    plt.savefig(chart_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  Chart saved: {chart_path}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="EnergyPlus parametric study runner",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    subparsers = parser.add_subparsers(dest="command")

    # run
    p_run = subparsers.add_parser("run", help="Run parametric study")
    p_run.add_argument("--base", required=True, help="Base IDF file path")
    p_run.add_argument("--variants", required=True,
                       help="Variants JSON file path")
    p_run.add_argument("--output-dir", required=True,
                       help="Output directory for results")
    p_run.add_argument("--weather", help="EPW weather file path")
    p_run.add_argument("--design-day", action="store_true",
                       help="Run design-day simulation")
    p_run.add_argument("--annual", action="store_true",
                       help="Run annual simulation")
    p_run.add_argument("--expand-objects", "-x", action="store_true",
                       help="Expand HVACTemplate objects")
    p_run.add_argument("--compare",
                       help="Variable to compare (total/heating/cooling/eui/"
                            "peak_heating/peak_cooling)")

    # generate-template
    p_gen = subparsers.add_parser("generate-template",
                                  help="Generate variants.json template")
    p_gen.add_argument("--base", required=True, help="Base IDF file path")
    p_gen.add_argument("--object-type", required=True,
                       help="Object type to vary")
    p_gen.add_argument("--object-name",
                       help="Object name (field[0]) to match")
    p_gen.add_argument("--fields", required=True,
                       help="Comma-separated field indices to vary (0-based)")

    # report
    p_rep = subparsers.add_parser("report",
                                  help="Regenerate report from results")
    p_rep.add_argument("--results-dir", required=True,
                       help="Directory with variant subdirectories")
    p_rep.add_argument("--compare",
                       help="Variable to compare for chart")

    args = parser.parse_args()
    if args.command is None:
        parser.print_help()
        sys.exit(1)

    commands = {
        "run": cmd_run,
        "generate-template": cmd_generate_template,
        "report": cmd_report,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
