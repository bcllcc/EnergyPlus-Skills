#!/usr/bin/env python
"""Calibration iteration tracker for EnergyPlus model tuning.

This tool records each calibration round with:
- changed parameters
- metrics against measured data
- corresponding IDF snapshot/version

Usage:
    python calibration_tracker.py record --run-dir <dir> --iteration <n> \
        --idf-path <idf> --epw-path <epw> --simulated <sql_or_csv> \
        --measured <csv> --variable <name> [options]

    python calibration_tracker.py summary --run-dir <dir>
"""

import argparse
import csv
import datetime as dt
import json
import math
import os
import shutil
import sys

import calibration


CSV_FIELDS = [
    "run_id",
    "iteration",
    "timestamp",
    "idf_version",
    "idf_path",
    "epw_path",
    "simulated_path",
    "measured_path",
    "variable",
    "key_value",
    "changed_params_json",
    "n_points",
    "rmse",
    "cv_rmse",
    "mbe",
    "nmbe",
    "r2",
    "max_dev",
    "delta_cv_rmse_vs_prev",
    "delta_nmbe_vs_prev",
    "pass_ashrae14",
    "granularity",
    "note",
]


def _now_iso():
    return dt.datetime.now().isoformat(timespec="seconds")


def _abs_path(path):
    return os.path.abspath(path)


def _ensure_dir(path):
    os.makedirs(path, exist_ok=True)


def _slugify(value):
    out = []
    for ch in str(value):
        if ch.isalnum():
            out.append(ch.lower())
        elif ch in ("-", "_"):
            out.append(ch)
        else:
            out.append("_")
    text = "".join(out).strip("_")
    return text or "version"


def _safe_float(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_json_dumps(obj):
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def _read_rows(csv_path):
    if not os.path.exists(csv_path):
        return []
    with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        return list(reader)


def _write_rows(csv_path, rows):
    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def _write_jsonl(jsonl_path, rows):
    with open(jsonl_path, "w", encoding="utf-8", newline="") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def _load_changed_params(args):
    if args.changed_params_file:
        with open(args.changed_params_file, "r", encoding="utf-8-sig") as f:
            return json.load(f)
    if not args.changed_params:
        return {}
    try:
        return json.loads(args.changed_params)
    except json.JSONDecodeError as exc:
        print(f"Error: --changed-params is not valid JSON: {exc}")
        sys.exit(1)


def _metrics_thresholds(granularity):
    if granularity == "monthly":
        return 15.0, 5.0
    return 30.0, 10.0


def _is_calibrated(metrics, granularity):
    cv_limit, nmbe_limit = _metrics_thresholds(granularity)
    cv_ok = abs(metrics["cv_rmse"]) <= cv_limit
    nmbe_ok = abs(metrics["nmbe"]) <= nmbe_limit
    return cv_ok and nmbe_ok


def _fmt_num(value, digits=6):
    if value is None:
        return ""
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return str(value)
    return f"{value:.{digits}f}"


def _format_range(timestamps):
    if not timestamps:
        return "", ""
    first = calibration.format_timestamp(timestamps[0])
    last = calibration.format_timestamp(timestamps[-1])
    return first, last


def _init_run_meta(run_dir, run_id):
    meta_path = os.path.join(run_dir, "run_meta.json")
    if os.path.exists(meta_path):
        with open(meta_path, "r", encoding="utf-8-sig") as f:
            meta = json.load(f)
    else:
        meta = {
            "run_id": run_id,
            "created_at": _now_iso(),
        }
    meta["updated_at"] = _now_iso()
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)


def _copy_idf_snapshot(idf_path, idf_versions_dir, iteration, idf_version, tag):
    ext = os.path.splitext(idf_path)[1] or ".idf"
    suffix = _slugify(tag or idf_version)
    base_name = f"iter_{iteration:03d}_{suffix}{ext}"
    dst = os.path.join(idf_versions_dir, base_name)
    if os.path.exists(dst):
        stamp = dt.datetime.now().strftime("%H%M%S")
        dst = os.path.join(idf_versions_dir, f"iter_{iteration:03d}_{suffix}_{stamp}{ext}")
    shutil.copy2(idf_path, dst)
    return dst


def _load_and_align(args):
    sim_path = _abs_path(args.simulated)
    meas_path = _abs_path(args.measured)

    if not os.path.exists(sim_path):
        print(f"Error: Simulated data not found: {sim_path}")
        sys.exit(1)
    if not os.path.exists(meas_path):
        print(f"Error: Measured data not found: {meas_path}")
        sys.exit(1)

    if sim_path.lower().endswith(".sql"):
        sim_data, sim_var_name, key_val, units = calibration.load_simulated_sql(
            sim_path, args.variable, args.key_value
        )
    else:
        sim_data, sim_var_name, key_val, units = calibration.load_simulated_csv(
            sim_path, args.sim_column
        )

    meas_data, _ = calibration.load_measured_csv(meas_path, args.meas_column)
    sim_values, meas_values, timestamps = calibration.align_data(sim_data, meas_data)

    if not sim_values:
        print("Error: No overlapping timestamps between simulation and measured data")
        if sim_data and meas_data:
            print(
                f"  Simulation range: ({sim_data[0][0]}/{sim_data[0][1]} H{sim_data[0][2]})"
                f" - ({sim_data[-1][0]}/{sim_data[-1][1]} H{sim_data[-1][2]})"
            )
            print(
                f"  Measured range:   ({meas_data[0][0]}/{meas_data[0][1]} H{meas_data[0][2]})"
                f" - ({meas_data[-1][0]}/{meas_data[-1][1]} H{meas_data[-1][2]})"
            )
        sys.exit(1)

    metrics = calibration.calc_metrics(sim_values, meas_values)
    return metrics, timestamps, sim_var_name, key_val, units, sim_path, meas_path


def _row_sort_key(row):
    try:
        return int(row.get("iteration", 0))
    except ValueError:
        return 0


def cmd_record(args):
    run_dir = _abs_path(args.run_dir)
    run_id = args.run_id or os.path.basename(run_dir.rstrip("\\/")) or "run"
    idf_path = _abs_path(args.idf_path)
    epw_path = _abs_path(args.epw_path)
    if not os.path.exists(idf_path):
        print(f"Error: IDF file not found: {idf_path}")
        sys.exit(1)
    if not os.path.exists(epw_path):
        print(f"Error: EPW file not found: {epw_path}")
        sys.exit(1)
    if args.iteration < 0:
        print("Error: --iteration must be >= 0")
        sys.exit(1)

    _ensure_dir(run_dir)
    idf_versions_dir = os.path.join(run_dir, "idf_versions")
    metrics_dir = os.path.join(run_dir, "metrics")
    notes_dir = os.path.join(run_dir, "notes")
    _ensure_dir(idf_versions_dir)
    _ensure_dir(metrics_dir)
    _ensure_dir(notes_dir)
    _init_run_meta(run_dir, run_id)

    changed_params = _load_changed_params(args)
    metrics, timestamps, sim_var_name, key_val, units, sim_path, meas_path = _load_and_align(args)
    pass_flag = _is_calibrated(metrics, args.granularity)

    idf_version = args.idf_version or os.path.splitext(os.path.basename(idf_path))[0]
    snapshot_path = _copy_idf_snapshot(
        idf_path=idf_path,
        idf_versions_dir=idf_versions_dir,
        iteration=args.iteration,
        idf_version=idf_version,
        tag=args.tag,
    )

    first_ts, last_ts = _format_range(timestamps)
    metrics_payload = {
        "run_id": run_id,
        "iteration": args.iteration,
        "timestamp": _now_iso(),
        "idf_version": idf_version,
        "idf_path": idf_path,
        "idf_snapshot": snapshot_path,
        "epw_path": epw_path,
        "simulated_path": sim_path,
        "measured_path": meas_path,
        "variable_requested": args.variable,
        "variable_actual": sim_var_name,
        "key_value": key_val or "",
        "units": units or "",
        "granularity": args.granularity,
        "n_points": metrics["n"],
        "metrics": {
            "rmse": metrics["rmse"],
            "cv_rmse": metrics["cv_rmse"],
            "mbe": metrics["mbe"],
            "nmbe": metrics["nmbe"],
            "r2": metrics["r2"],
            "max_dev": metrics["max_dev"],
        },
        "time_range": {
            "first": first_ts,
            "last": last_ts,
        },
        "changed_params": changed_params,
        "note": args.note or "",
        "pass_ashrae14": pass_flag,
    }
    metrics_path = os.path.join(metrics_dir, f"iter_{args.iteration:03d}_metrics.json")
    with open(metrics_path, "w", encoding="utf-8") as f:
        json.dump(metrics_payload, f, ensure_ascii=False, indent=2)

    note_path = os.path.join(notes_dir, f"iter_{args.iteration:03d}.md")
    with open(note_path, "w", encoding="utf-8") as f:
        f.write(f"# Iteration {args.iteration}\n\n")
        f.write(f"- run_id: `{run_id}`\n")
        f.write(f"- idf_version: `{idf_version}`\n")
        f.write(f"- idf_snapshot: `{snapshot_path}`\n")
        f.write(f"- simulated: `{sim_path}`\n")
        f.write(f"- measured: `{meas_path}`\n")
        f.write(f"- variable: `{sim_var_name}`\n")
        if key_val:
            f.write(f"- key_value: `{key_val}`\n")
        f.write(f"- data_points: `{metrics['n']}`\n")
        f.write(f"- cv_rmse: `{metrics['cv_rmse']:.4f}`\n")
        f.write(f"- nmbe: `{metrics['nmbe']:.4f}`\n")
        f.write(f"- pass_ashrae14: `{str(pass_flag).lower()}`\n")
        if args.note:
            f.write(f"- note: {args.note}\n")
        f.write("\n## Changed Params\n\n")
        f.write("```json\n")
        f.write(json.dumps(changed_params, ensure_ascii=False, indent=2))
        f.write("\n```\n")

    csv_path = os.path.join(run_dir, "iteration_log.csv")
    rows = _read_rows(csv_path)
    rows = [
        r
        for r in rows
        if not (
            r.get("run_id") == run_id
            and str(r.get("iteration", "")) == str(args.iteration)
        )
    ]
    prev_rows = [r for r in rows if r.get("run_id") == run_id]
    prev_rows.sort(key=_row_sort_key)
    prev = prev_rows[-1] if prev_rows else None
    prev_cv = _safe_float(prev.get("cv_rmse")) if prev else None
    prev_nmbe = _safe_float(prev.get("nmbe")) if prev else None
    delta_cv = metrics["cv_rmse"] - prev_cv if prev_cv is not None else None
    delta_nmbe = metrics["nmbe"] - prev_nmbe if prev_nmbe is not None else None

    new_row = {
        "run_id": run_id,
        "iteration": str(args.iteration),
        "timestamp": _now_iso(),
        "idf_version": idf_version,
        "idf_path": idf_path,
        "epw_path": epw_path,
        "simulated_path": sim_path,
        "measured_path": meas_path,
        "variable": sim_var_name,
        "key_value": key_val or "",
        "changed_params_json": _safe_json_dumps(changed_params),
        "n_points": str(metrics["n"]),
        "rmse": _fmt_num(metrics["rmse"]),
        "cv_rmse": _fmt_num(metrics["cv_rmse"]),
        "mbe": _fmt_num(metrics["mbe"]),
        "nmbe": _fmt_num(metrics["nmbe"]),
        "r2": _fmt_num(metrics["r2"]),
        "max_dev": _fmt_num(metrics["max_dev"]),
        "delta_cv_rmse_vs_prev": _fmt_num(delta_cv),
        "delta_nmbe_vs_prev": _fmt_num(delta_nmbe),
        "pass_ashrae14": str(bool(pass_flag)).lower(),
        "granularity": args.granularity,
        "note": args.note or "",
    }
    rows.append(new_row)
    rows.sort(key=_row_sort_key)
    _write_rows(csv_path, rows)
    _write_jsonl(os.path.join(run_dir, "iteration_log.jsonl"), rows)

    print("=== Calibration Iteration Recorded ===")
    print(f"  Run dir:     {run_dir}")
    print(f"  Run id:      {run_id}")
    print(f"  Iteration:   {args.iteration}")
    print(f"  IDF version: {idf_version}")
    print(f"  Points:      {metrics['n']}")
    print(f"  CV(RMSE):    {metrics['cv_rmse']:.4f}%")
    print(f"  NMBE:        {metrics['nmbe']:.4f}%")
    print(f"  PASS:        {str(pass_flag).lower()}")
    if delta_cv is not None:
        print(f"  Delta CV:    {delta_cv:+.4f}")
    if delta_nmbe is not None:
        print(f"  Delta NMBE:  {delta_nmbe:+.4f}")
    print(f"  Snapshot:    {snapshot_path}")
    print(f"  Metrics:     {metrics_path}")
    print(f"  Note:        {note_path}")


def cmd_summary(args):
    run_dir = _abs_path(args.run_dir)
    csv_path = os.path.join(run_dir, "iteration_log.csv")
    rows = _read_rows(csv_path)
    if not rows:
        print(f"Error: No iteration logs found: {csv_path}")
        sys.exit(1)
    rows.sort(key=_row_sort_key)

    print("=== Calibration Run Summary ===")
    print(f"  Run dir: {run_dir}")
    print(f"  Rows:    {len(rows)}")
    print()
    print("Iteration | IDF Version | CV(RMSE)% | NMBE% | Delta CV | Delta NMBE | PASS")
    print("-" * 78)
    for row in rows:
        print(
            f"{int(row['iteration']):>9} | "
            f"{row['idf_version'][:20]:<20} | "
            f"{_safe_float(row['cv_rmse']) if row['cv_rmse'] else float('nan'):>9.4f} | "
            f"{_safe_float(row['nmbe']) if row['nmbe'] else float('nan'):>6.4f} | "
            f"{(_safe_float(row['delta_cv_rmse_vs_prev']) if row['delta_cv_rmse_vs_prev'] else 0.0):>8.4f} | "
            f"{(_safe_float(row['delta_nmbe_vs_prev']) if row['delta_nmbe_vs_prev'] else 0.0):>10.4f} | "
            f"{row['pass_ashrae14']}"
        )

    best = min(
        rows,
        key=lambda r: abs(_safe_float(r.get("cv_rmse")) or float("inf"))
        + abs(_safe_float(r.get("nmbe")) or float("inf")),
    )
    print()
    print("Best iteration (min |CV| + |NMBE|):")
    print(f"  iteration={best['iteration']}, idf_version={best['idf_version']}")


def main():
    parser = argparse.ArgumentParser(
        description="Calibration iteration tracker",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command")

    p_rec = subparsers.add_parser("record", help="Record one calibration iteration")
    p_rec.add_argument("--run-dir", required=True, help="Run directory")
    p_rec.add_argument("--run-id", help="Run ID (default: run-dir name)")
    p_rec.add_argument("--iteration", required=True, type=int, help="Iteration index (0-based)")
    p_rec.add_argument("--idf-version", help="Human-readable IDF version label")
    p_rec.add_argument("--idf-path", required=True, help="Path to current IDF")
    p_rec.add_argument("--epw-path", required=True, help="Path to EPW used for this iteration")
    p_rec.add_argument("--simulated", required=True, help="Simulation output path (SQL or CSV)")
    p_rec.add_argument("--measured", required=True, help="Measured CSV path")
    p_rec.add_argument("--variable", required=True, help="Variable name for calibration")
    p_rec.add_argument("--sim-column", help="Simulation CSV value column (if CSV source)")
    p_rec.add_argument("--meas-column", help="Measured CSV value column")
    p_rec.add_argument("--key-value", help="Zone/key value filter (SQL source)")
    p_rec.add_argument("--changed-params", default="{}", help="JSON string of changed parameters")
    p_rec.add_argument("--changed-params-file", help="JSON file path of changed parameters")
    p_rec.add_argument(
        "--granularity",
        choices=["hourly", "monthly"],
        default="hourly",
        help="Metric threshold mode",
    )
    p_rec.add_argument("--tag", help="Optional suffix used in IDF snapshot filename")
    p_rec.add_argument("--note", help="Free-text note for this iteration")

    p_sum = subparsers.add_parser("summary", help="Show concise run summary")
    p_sum.add_argument("--run-dir", required=True, help="Run directory")

    args = parser.parse_args()
    if args.command is None:
        parser.print_help()
        sys.exit(1)

    commands = {
        "record": cmd_record,
        "summary": cmd_summary,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
