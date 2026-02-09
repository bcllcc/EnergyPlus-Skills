#!/usr/bin/env python
"""EnergyPlus model calibration tool.

Compare simulation results against measured data and calculate error metrics
per ASHRAE Guideline 14.

Usage:
    python calibration.py compare --simulated <csv_or_sql> --measured <csv>
        --variable <var_name> --output-dir <dir>
        [--sim-column <col>] [--meas-column <col>] [--key-value <zone>]
    python calibration.py metrics --simulated <csv_or_sql> --measured <csv>
        --variable <var_name>
        [--sim-column <col>] [--meas-column <col>] [--key-value <zone>]

Error metrics (ASHRAE Guideline 14):
    RMSE:     sqrt(mean((sim - meas)^2))
    CV(RMSE): RMSE / mean(meas) * 100%     [hourly <= 30%, monthly <= 15%]
    MBE:      mean(sim - meas)
    NMBE:     MBE / mean(meas) * 100%       [hourly <= +-10%, monthly <= +-5%]
    R2:       coefficient of determination
    Max deviation and its timestamp
"""

import argparse
import csv
import math
import os
import re
import sqlite3
import subprocess
import sys


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


def _normalize_header(value):
    """Normalize CSV header tokens for robust matching."""
    if value is None:
        return ""
    return str(value).replace("\ufeff", "").strip().lower()

def load_simulated_sql(sql_path, variable, key_value=None):
    """Load time-series data from EnergyPlus SQL output.

    Args:
        sql_path: Path to eplusout.sql
        variable: Variable name (e.g. "Zone Mean Air Temperature")
        key_value: Optional zone/surface key (e.g. "THERMAL ZONE: SPACE 108")

    Returns:
        list of (month, day, hour, value) tuples
    """
    conn = sqlite3.connect(sql_path)
    cur = conn.cursor()

    # Find matching variable(s)
    query = """SELECT rdd.ReportDataDictionaryIndex, rdd.KeyValue, rdd.Name, rdd.Units
        FROM ReportDataDictionary rdd
        WHERE rdd.Name LIKE ?"""
    params = [f"%{variable}%"]

    if key_value:
        query += " AND rdd.KeyValue LIKE ?"
        params.append(f"%{key_value}%")

    cur.execute(query, params)
    matches = cur.fetchall()

    if not matches:
        conn.close()
        print(f"Error: No variable matching '{variable}' found in SQL")
        if key_value:
            print(f"  (with key value matching '{key_value}')")
        # List available variables
        cur2 = conn.cursor()
        cur2.execute("SELECT DISTINCT Name, KeyValue FROM ReportDataDictionary LIMIT 20")
        print("  Available variables:")
        for name, kv in cur2.fetchall():
            print(f"    {name} [{kv}]")
        conn.close()
        sys.exit(1)

    if len(matches) > 1 and not key_value:
        print(f"Warning: Multiple matches for '{variable}', using first:")
        for idx, kv, name, units in matches:
            print(f"  [{idx}] {name} [{kv}] ({units})")

    rdd_idx = matches[0][0]
    actual_key = matches[0][1]
    actual_name = matches[0][2]
    units = matches[0][3]

    # Extract time-series
    cur.execute("""SELECT t.Month, t.Day, t.Hour, rd.Value
        FROM ReportData rd
        JOIN Time t ON rd.TimeIndex = t.TimeIndex
        WHERE rd.ReportDataDictionaryIndex = ?
        AND t.WarmupFlag IS NULL
        ORDER BY t.Month, t.Day, t.Hour""", (rdd_idx,))
    data = cur.fetchall()
    conn.close()

    if not data:
        print(f"Error: No data rows for {actual_name} [{actual_key}]")
        sys.exit(1)

    return data, actual_name, actual_key, units


def load_simulated_csv(csv_path, column=None):
    """Load time-series from EnergyPlus CSV output.

    EnergyPlus CSV format: first column is Date/Time like " 01/01  01:00:00",
    subsequent columns are variable values with headers like
    "ZONE:Variable Name [Units](Frequency)"

    Returns:
        list of (month, day, hour, value) tuples, variable_name, units
    """
    with open(csv_path, "r", encoding="utf-8-sig", errors="replace") as f:
        reader = csv.reader(f)
        headers = next(reader)

    # Clean headers
    headers = [h.strip() for h in headers]

    # Find the data column
    col_idx = None
    var_name = ""

    if column:
        # Try exact match first, then partial
        for i, h in enumerate(headers):
            if column.lower() == h.lower():
                col_idx = i
                var_name = h
                break
        if col_idx is None:
            for i, h in enumerate(headers):
                if column.lower() in h.lower():
                    col_idx = i
                    var_name = h
                    break
    else:
        # Use first non-time column
        if len(headers) > 1:
            col_idx = 1
            var_name = headers[1]

    if col_idx is None:
        print(f"Error: Column '{column}' not found in CSV")
        print(f"  Available columns: {headers}")
        sys.exit(1)

    # Parse units from header (e.g. "...Zone Mean Air Temperature [C](Hourly)")
    units = ""
    m = re.search(r'\[([^\]]+)\]', var_name)
    if m:
        units = m.group(1)

    # Read data
    data = []
    with open(csv_path, "r", encoding="utf-8-sig", errors="replace") as f:
        reader = csv.reader(f)
        next(reader)  # skip header
        for row in reader:
            if len(row) <= col_idx:
                continue
            # Parse date/time from first column
            dt_str = row[0].strip()
            month, day, hour = _parse_ep_datetime(dt_str)
            if month is None:
                continue
            try:
                val = float(row[col_idx].strip())
            except (ValueError, IndexError):
                continue
            data.append((month, day, hour, val))

    return data, var_name, "", units


def _parse_ep_datetime(dt_str):
    """Parse EnergyPlus date/time format like ' 01/01  01:00:00' or '01/01 01:00'.

    Returns (month, day, hour) or (None, None, None) on failure.
    """
    # Match patterns: "MM/DD  HH:MM:SS" or "MM/DD HH:MM"
    m = re.match(r'\s*(\d{1,2})/(\d{1,2})\s+(\d{1,2}):', dt_str)
    if m:
        return int(m.group(1)), int(m.group(2)), int(m.group(3))
    return None, None, None


def load_measured_csv(csv_path, column=None):
    """Load measured data from user CSV.

    Expected CSV format options:
    1. Month,Day,Hour,<value_column>  (EPW-style time columns)
    2. DateTime,<value_column>  (ISO datetime or similar)

    Returns:
        list of (month, day, hour, value) tuples
    """
    with open(csv_path, "r", encoding="utf-8-sig", errors="replace") as f:
        reader = csv.reader(f)
        headers = next(reader)

    headers_lower = [_normalize_header(h) for h in headers]
    headers_clean = [h.replace("\ufeff", "").strip() for h in headers]

    # Find time columns
    month_col = day_col = hour_col = dt_col = None
    for i, h in enumerate(headers_lower):
        if h == "month":
            month_col = i
        elif h == "day":
            day_col = i
        elif h == "hour":
            hour_col = i
        elif h in (
            "datetime",
            "date_time",
            "timestamp",
            "date/time",
            "date time",
            "date",
            "time",
            "data",
        ):
            dt_col = i

    has_mdy = month_col is not None and day_col is not None and hour_col is not None

    if not has_mdy and dt_col is None:
        print("Error: Measured CSV must have either Month/Day/Hour columns "
              "or a DateTime column")
        print(f"  Found columns: {headers_clean}")
        sys.exit(1)

    # Find value column
    val_col = None
    if column:
        target = _normalize_header(column)
        for i, h in enumerate(headers_lower):
            if target == h:
                val_col = i
                break
        if val_col is None:
            for i, h in enumerate(headers_lower):
                if target in h:
                    val_col = i
                    break
    else:
        # Use the last column that isn't a time column
        time_cols = {month_col, day_col, hour_col, dt_col}
        for i in range(len(headers) - 1, -1, -1):
            if i not in time_cols:
                val_col = i
                break

    if val_col is None:
        print(f"Error: Value column '{column}' not found in measured CSV")
        print(f"  Available columns: {headers_clean}")
        sys.exit(1)

    # Read data
    data = []
    with open(csv_path, "r", encoding="utf-8-sig", errors="replace") as f:
        reader = csv.reader(f)
        next(reader)  # skip header
        for row in reader:
            if not row or not row[0].strip():
                continue
            try:
                if has_mdy:
                    month = int(row[month_col].strip())
                    day = int(row[day_col].strip())
                    hour = int(row[hour_col].strip())
                else:
                    # Parse datetime
                    dt_str = row[dt_col].strip()
                    month, day, hour = _parse_datetime(dt_str)
                    if month is None:
                        continue
                val = float(row[val_col].strip())
                data.append((month, day, hour, val))
            except (ValueError, IndexError):
                continue

    return data, headers_clean[val_col]


def _parse_datetime(dt_str):
    """Parse various datetime formats. Returns (month, day, hour)."""
    # ISO: 2024-01-15T14:00:00 or 2024-01-15 14:00
    m = re.match(r'(\d{4})-(\d{1,2})-(\d{1,2})[T\s](\d{1,2})', dt_str)
    if m:
        return int(m.group(2)), int(m.group(3)), int(m.group(4))
    # US: 01/15/2024 14:00
    m = re.match(r'(\d{1,2})/(\d{1,2})/\d{2,4}\s+(\d{1,2})', dt_str)
    if m:
        return int(m.group(1)), int(m.group(2)), int(m.group(3))
    # EP-style (month/day without year): 05/19  01:00:00
    m = re.match(r'\s*(\d{1,2})/(\d{1,2})\s+(\d{1,2}):', dt_str)
    if m:
        return int(m.group(1)), int(m.group(2)), int(m.group(3))
    return None, None, None


# ---------------------------------------------------------------------------
# Data alignment
# ---------------------------------------------------------------------------

def align_data(sim_data, meas_data):
    """Align simulation and measured data by (month, day, hour) timestamp.

    Returns:
        sim_values: list of float
        meas_values: list of float
        timestamps: list of (month, day, hour) tuples
    """
    # Build lookup from measured data
    meas_map = {}
    for m, d, h, v in meas_data:
        meas_map[(m, d, h)] = v

    sim_values = []
    meas_values = []
    timestamps = []

    for m, d, h, v in sim_data:
        key = (m, d, h)
        if key in meas_map:
            sim_values.append(v)
            meas_values.append(meas_map[key])
            timestamps.append(key)

    return sim_values, meas_values, timestamps


# ---------------------------------------------------------------------------
# Error metrics (ASHRAE Guideline 14)
# ---------------------------------------------------------------------------

def calc_metrics(sim, meas):
    """Calculate calibration error metrics.

    Args:
        sim: list of simulated values
        meas: list of measured values (same length)

    Returns:
        dict with keys: n, rmse, cv_rmse, mbe, nmbe, r2,
        max_dev, max_dev_idx, mean_meas, mean_sim
    """
    n = len(sim)
    if n == 0:
        return {"n": 0, "error": "No data points"}

    mean_meas = sum(meas) / n
    mean_sim = sum(sim) / n

    # Differences
    diffs = [s - m for s, m in zip(sim, meas)]

    # MBE
    mbe = sum(diffs) / n

    # RMSE
    sq_diffs = [d * d for d in diffs]
    rmse = math.sqrt(sum(sq_diffs) / n)

    # CV(RMSE) and NMBE
    if abs(mean_meas) < 1e-10:
        cv_rmse = float('inf')
        nmbe = float('inf')
    else:
        cv_rmse = (rmse / abs(mean_meas)) * 100
        nmbe = (mbe / abs(mean_meas)) * 100

    # R-squared
    ss_res = sum(sq_diffs)
    ss_tot = sum((m - mean_meas) ** 2 for m in meas)
    if ss_tot < 1e-10:
        r2 = float('nan')
    else:
        r2 = 1 - (ss_res / ss_tot)

    # Max deviation
    abs_diffs = [abs(d) for d in diffs]
    max_dev_idx = abs_diffs.index(max(abs_diffs))
    max_dev = diffs[max_dev_idx]

    return {
        "n": n,
        "rmse": rmse,
        "cv_rmse": cv_rmse,
        "mbe": mbe,
        "nmbe": nmbe,
        "r2": r2,
        "max_dev": max_dev,
        "max_dev_idx": max_dev_idx,
        "mean_meas": mean_meas,
        "mean_sim": mean_sim,
    }


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------

def format_timestamp(ts):
    """Format (month, day, hour) as readable string."""
    m, d, h = ts
    return f"{m}/{d} {h:02d}:00"


def print_report(metrics, variable, timestamps, units="", granularity="hourly"):
    """Print formatted calibration report."""
    n = metrics["n"]
    if n == 0:
        print("Error: No overlapping data points between simulation and measured data")
        return

    # Determine time range
    first = timestamps[0]
    last = timestamps[-1]

    # ASHRAE Guideline 14 thresholds
    if granularity == "monthly":
        cv_threshold = 15.0
        nmbe_threshold = 5.0
    else:
        cv_threshold = 30.0
        nmbe_threshold = 10.0

    cv_pass = abs(metrics["cv_rmse"]) <= cv_threshold
    nmbe_pass = abs(metrics["nmbe"]) <= nmbe_threshold

    unit_str = f" {units}" if units else ""
    max_ts = format_timestamp(timestamps[metrics["max_dev_idx"]])

    print(f"=== Calibration Report ===")
    print(f"  Variable:   {variable}")
    print(f"  Data points: {n} ({granularity})")
    print(f"  Time range: {format_timestamp(first)} - {format_timestamp(last)}")
    print(f"  Mean (measured): {metrics['mean_meas']:.2f}{unit_str}")
    print(f"  Mean (simulated): {metrics['mean_sim']:.2f}{unit_str}")
    print()
    print(f"--- Error Metrics ---")
    print(f"  RMSE:      {metrics['rmse']:.3f}{unit_str}")
    cv_mark = "PASS" if cv_pass else "FAIL"
    print(f"  CV(RMSE):  {metrics['cv_rmse']:.1f}%  "
          f"[<={cv_threshold}%] {cv_mark}")
    print(f"  MBE:       {metrics['mbe']:.3f}{unit_str}")
    nmbe_mark = "PASS" if nmbe_pass else "FAIL"
    print(f"  NMBE:      {metrics['nmbe']:.1f}%  "
          f"[<=+-{nmbe_threshold}%] {nmbe_mark}")
    r2_str = f"{metrics['r2']:.4f}" if not math.isnan(metrics['r2']) else "N/A"
    print(f"  R2:        {r2_str}")
    print(f"  Max dev:   {metrics['max_dev']:.3f}{unit_str} ({max_ts})")
    print()

    if cv_pass and nmbe_pass:
        print(f"  Conclusion: CALIBRATED (ASHRAE Guideline 14, {granularity})")
    else:
        print(f"  Conclusion: NOT CALIBRATED (ASHRAE Guideline 14, {granularity})")
        if not cv_pass:
            print(f"    CV(RMSE) {metrics['cv_rmse']:.1f}% exceeds {cv_threshold}%")
        if not nmbe_pass:
            print(f"    NMBE {metrics['nmbe']:.1f}% exceeds +-{nmbe_threshold}%")


def generate_chart(sim, meas, timestamps, variable, units, output_path):
    """Generate comparison chart with time-series overlay and scatter plot."""
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        print("  Warning: matplotlib not available, skipping chart")
        return

    fig, axes = plt.subplots(2, 1, figsize=(12, 8), height_ratios=[2, 1])

    # X-axis labels
    x = list(range(len(sim)))
    # Create tick labels every N points
    tick_step = max(1, len(x) // 10)
    tick_positions = list(range(0, len(x), tick_step))
    tick_labels = [format_timestamp(timestamps[i]) for i in tick_positions]

    unit_str = f" ({units})" if units else ""

    # --- Top: Time-series overlay ---
    ax1 = axes[0]
    ax1.plot(x, meas, color="#2196F3", linewidth=1, alpha=0.8, label="Measured")
    ax1.plot(x, sim, color="#FF5722", linewidth=1, alpha=0.8, label="Simulated")
    ax1.set_ylabel(f"{variable}{unit_str}", fontsize=10)
    ax1.set_title(f"Calibration: {variable}", fontsize=13, fontweight="bold")
    ax1.legend(loc="upper right", fontsize=9)
    ax1.grid(alpha=0.3, linestyle="--")
    ax1.set_xticks(tick_positions)
    ax1.set_xticklabels(tick_labels, fontsize=8, rotation=30, ha="right")

    # --- Bottom: Residuals ---
    ax2 = axes[1]
    residuals = [s - m for s, m in zip(sim, meas)]
    colors = ["#4CAF50" if abs(r) <= 2 else "#FFC107" if abs(r) <= 5
              else "#F44336" for r in residuals]
    ax2.bar(x, residuals, color=colors, width=1, edgecolor="none", alpha=0.7)
    ax2.axhline(y=0, color="black", linewidth=0.5)
    ax2.set_ylabel(f"Residual{unit_str}", fontsize=10)
    ax2.set_xlabel("Time", fontsize=10)
    ax2.grid(axis="y", alpha=0.3, linestyle="--")
    ax2.set_xticks(tick_positions)
    ax2.set_xticklabels(tick_labels, fontsize=8, rotation=30, ha="right")

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches="tight")
    plt.close()
    print(f"  Chart saved: {output_path}")


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def _maybe_record_iteration(args):
    """Auto-record calibration iteration when tracking options are provided."""
    if not getattr(args, "record_dir", None):
        return

    required = {
        "iteration": getattr(args, "iteration", None),
        "idf-path": getattr(args, "idf_path", None),
        "epw-path": getattr(args, "epw_path", None),
    }
    missing = [k for k, v in required.items() if v is None]
    if missing:
        print("Error: Tracking enabled but missing required arguments:")
        print(f"  Missing: {', '.join(missing)}")
        print("  Required with --record-dir: --iteration --idf-path --epw-path")
        sys.exit(1)

    tracker_script = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "calibration_tracker.py",
    )
    if not os.path.exists(tracker_script):
        print(f"Error: Tracking script not found: {tracker_script}")
        sys.exit(1)

    cmd = [
        sys.executable,
        tracker_script,
        "record",
        "--run-dir",
        args.record_dir,
        "--iteration",
        str(args.iteration),
        "--idf-path",
        args.idf_path,
        "--epw-path",
        args.epw_path,
        "--simulated",
        args.simulated,
        "--measured",
        args.measured,
        "--variable",
        args.variable,
        "--granularity",
        args.track_granularity,
    ]

    # Optional pass-through arguments
    if getattr(args, "run_id", None):
        cmd.extend(["--run-id", args.run_id])
    if getattr(args, "idf_version", None):
        cmd.extend(["--idf-version", args.idf_version])
    if getattr(args, "sim_column", None):
        cmd.extend(["--sim-column", args.sim_column])
    if getattr(args, "meas_column", None):
        cmd.extend(["--meas-column", args.meas_column])
    if getattr(args, "key_value", None):
        cmd.extend(["--key-value", args.key_value])
    if getattr(args, "changed_params_file", None):
        cmd.extend(["--changed-params-file", args.changed_params_file])
    else:
        cmd.extend(["--changed-params", args.changed_params or "{}"])
    if getattr(args, "track_tag", None):
        cmd.extend(["--tag", args.track_tag])
    if getattr(args, "record_note", None):
        cmd.extend(["--note", args.record_note])

    proc = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        print("Error: Failed to auto-record calibration iteration")
        if proc.stdout.strip():
            print(proc.stdout.strip())
        if proc.stderr.strip():
            print(proc.stderr.strip())
        sys.exit(proc.returncode)

    if proc.stdout.strip():
        print("\n--- Tracking ---")
        print(proc.stdout.strip())


def _add_tracking_args(parser):
    """Add optional tracker integration arguments to a calibration command."""
    parser.add_argument("--record-dir",
                        help="Auto-record iteration to this run directory")
    parser.add_argument("--run-id",
                        help="Calibration run id (default: run-dir name)")
    parser.add_argument("--iteration", type=int,
                        help="Iteration index (required with --record-dir)")
    parser.add_argument("--idf-version",
                        help="IDF version label for tracking")
    parser.add_argument("--idf-path",
                        help="IDF path used for this iteration")
    parser.add_argument("--epw-path",
                        help="EPW path used for this iteration")
    parser.add_argument("--changed-params", default="{}",
                        help="JSON string of parameter changes")
    parser.add_argument("--changed-params-file",
                        help="JSON file containing parameter changes")
    parser.add_argument("--track-granularity",
                        choices=["hourly", "monthly"],
                        default="hourly",
                        help="Threshold mode for tracking PASS/FAIL")
    parser.add_argument("--track-tag",
                        help="Optional IDF snapshot filename tag")
    parser.add_argument("--record-note",
                        help="Free-text note saved in iteration log")


def cmd_compare(args):
    """Compare simulation results against measured data."""
    sim_path = os.path.abspath(args.simulated)
    meas_path = os.path.abspath(args.measured)
    output_dir = os.path.abspath(args.output_dir)

    if not os.path.exists(sim_path):
        print(f"Error: Simulated data not found: {sim_path}")
        sys.exit(1)
    if not os.path.exists(meas_path):
        print(f"Error: Measured data not found: {meas_path}")
        sys.exit(1)

    os.makedirs(output_dir, exist_ok=True)

    # Load simulation data
    if sim_path.lower().endswith(".sql"):
        sim_data, var_name, key_val, units = load_simulated_sql(
            sim_path, args.variable, args.key_value)
    else:
        sim_data, var_name, key_val, units = load_simulated_csv(
            sim_path, args.sim_column)

    # Load measured data
    meas_data, meas_col = load_measured_csv(meas_path, args.meas_column)

    if not sim_data:
        print("Error: No simulation data loaded")
        sys.exit(1)
    if not meas_data:
        print("Error: No measured data loaded")
        sys.exit(1)

    # Align
    sim_values, meas_values, timestamps = align_data(sim_data, meas_data)

    if not sim_values:
        print("Error: No overlapping timestamps between simulation and measured data")
        print(f"  Simulation range: ({sim_data[0][0]}/{sim_data[0][1]} H{sim_data[0][2]})"
              f" - ({sim_data[-1][0]}/{sim_data[-1][1]} H{sim_data[-1][2]})")
        print(f"  Measured range:   ({meas_data[0][0]}/{meas_data[0][1]} H{meas_data[0][2]})"
              f" - ({meas_data[-1][0]}/{meas_data[-1][1]} H{meas_data[-1][2]})")
        sys.exit(1)

    # Calculate metrics
    metrics = calc_metrics(sim_values, meas_values)

    # Print report
    print_report(metrics, var_name, timestamps, units)

    # Save comparison CSV
    comp_csv = os.path.join(output_dir, "calibration_comparison.csv")
    with open(comp_csv, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["Month", "Day", "Hour", "Simulated", "Measured", "Difference"])
        for ts, sv, mv in zip(timestamps, sim_values, meas_values):
            writer.writerow([ts[0], ts[1], ts[2], f"{sv:.4f}", f"{mv:.4f}",
                            f"{sv - mv:.4f}"])
    print(f"\n  Comparison CSV: {comp_csv}")

    # Generate chart
    chart_path = os.path.join(output_dir, "calibration_comparison.png")
    generate_chart(sim_values, meas_values, timestamps, var_name, units,
                   chart_path)

    _maybe_record_iteration(args)


def cmd_metrics(args):
    """Calculate and print error metrics only (no chart)."""
    sim_path = os.path.abspath(args.simulated)
    meas_path = os.path.abspath(args.measured)

    if not os.path.exists(sim_path):
        print(f"Error: Simulated data not found: {sim_path}")
        sys.exit(1)
    if not os.path.exists(meas_path):
        print(f"Error: Measured data not found: {meas_path}")
        sys.exit(1)

    # Load data
    if sim_path.lower().endswith(".sql"):
        sim_data, var_name, key_val, units = load_simulated_sql(
            sim_path, args.variable, args.key_value)
    else:
        sim_data, var_name, key_val, units = load_simulated_csv(
            sim_path, args.sim_column)

    meas_data, meas_col = load_measured_csv(meas_path, args.meas_column)

    sim_values, meas_values, timestamps = align_data(sim_data, meas_data)

    metrics = calc_metrics(sim_values, meas_values)
    print_report(metrics, var_name, timestamps, units)
    _maybe_record_iteration(args)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="EnergyPlus model calibration tool",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    subparsers = parser.add_subparsers(dest="command")

    # compare
    p_cmp = subparsers.add_parser("compare",
                                   help="Compare simulation vs measured data")
    p_cmp.add_argument("--simulated", required=True,
                       help="Simulation results (CSV or SQL)")
    p_cmp.add_argument("--measured", required=True,
                       help="Measured data CSV")
    p_cmp.add_argument("--variable", required=True,
                       help="Variable name to compare")
    p_cmp.add_argument("--output-dir", required=True,
                       help="Output directory for comparison files")
    p_cmp.add_argument("--sim-column",
                       help="Column name in simulation CSV (if not SQL)")
    p_cmp.add_argument("--meas-column",
                       help="Column name in measured CSV")
    p_cmp.add_argument("--key-value",
                       help="Zone/key value filter (for SQL source)")
    _add_tracking_args(p_cmp)

    # metrics
    p_met = subparsers.add_parser("metrics",
                                   help="Calculate error metrics only")
    p_met.add_argument("--simulated", required=True,
                       help="Simulation results (CSV or SQL)")
    p_met.add_argument("--measured", required=True,
                       help="Measured data CSV")
    p_met.add_argument("--variable", required=True,
                       help="Variable name to compare")
    p_met.add_argument("--sim-column",
                       help="Column name in simulation CSV (if not SQL)")
    p_met.add_argument("--meas-column",
                       help="Column name in measured CSV")
    p_met.add_argument("--key-value",
                       help="Zone/key value filter (for SQL source)")
    _add_tracking_args(p_met)

    args = parser.parse_args()
    if args.command is None:
        parser.print_help()
        sys.exit(1)

    commands = {
        "compare": cmd_compare,
        "metrics": cmd_metrics,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
