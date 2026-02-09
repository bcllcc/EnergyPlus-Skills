#!/usr/bin/env python
"""EnergyPlus output file parser.

Parses .err, .csv, .html, .sql, .rdd, .mdd output files.

Usage:
    python parse_outputs.py errors <output_dir> [--prefix <name>]
    python parse_outputs.py summary <output_dir> [--prefix <name>]
    python parse_outputs.py timeseries <output_dir> --variable <name> [--zone <name>] [--start <date>] [--end <date>] [--prefix <name>]
    python parse_outputs.py sql <output_dir> --query <SQL> [--prefix <name>]
    python parse_outputs.py available-vars <output_dir> [--prefix <name>]
    python parse_outputs.py available-meters <output_dir> [--prefix <name>]
"""

import argparse
import csv
import os
import re
import sqlite3
import sys
from html.parser import HTMLParser
from statistics import mean, stdev


def find_file(output_dir, prefix, extension):
    """Find an output file by extension, trying common naming patterns."""
    candidates = [
        os.path.join(output_dir, f"{prefix}{extension}"),
        os.path.join(output_dir, f"eplusout{extension}"),
        os.path.join(output_dir, f"eplus{extension}"),
    ]
    for c in candidates:
        if os.path.exists(c):
            return c

    # Search for any matching file
    for f in os.listdir(output_dir):
        if f.endswith(extension):
            return os.path.join(output_dir, f)
    return None


def cmd_errors(args):
    """Parse .err file for errors and warnings."""
    err_path = find_file(args.output_dir, args.prefix, ".err")
    if not err_path:
        print(f"No .err file found in {args.output_dir}")
        sys.exit(1)

    fatal_lines = []
    severe_lines = []
    warning_lines = []
    info_lines = []
    current_category = None

    with open(err_path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            stripped = line.strip()
            if not stripped:
                continue

            if "** Fatal **" in stripped or "**  Fatal  **" in stripped:
                current_category = "fatal"
                fatal_lines.append(stripped)
            elif "** Severe  **" in stripped:
                current_category = "severe"
                severe_lines.append(stripped)
            elif "** Warning **" in stripped:
                current_category = "warning"
                warning_lines.append(stripped)
            elif "**   ~~~   **" in stripped:
                # Continuation line
                if current_category == "fatal":
                    fatal_lines.append(stripped)
                elif current_category == "severe":
                    severe_lines.append(stripped)
                elif current_category == "warning":
                    warning_lines.append(stripped)
            else:
                current_category = None

    print(f"=== Error Report: {os.path.basename(err_path)} ===\n")
    print(f"  Fatal:   {len([l for l in fatal_lines if 'Fatal' in l])}")
    print(f"  Severe:  {len([l for l in severe_lines if 'Severe' in l])}")
    print(f"  Warning: {len([l for l in warning_lines if 'Warning' in l])}")

    if fatal_lines:
        print(f"\n--- FATAL ERRORS ---")
        for line in fatal_lines:
            print(f"  {line}")

    if severe_lines:
        print(f"\n--- SEVERE ERRORS ---")
        for line in severe_lines[:40]:
            print(f"  {line}")
        if len(severe_lines) > 40:
            print(f"  ... and {len(severe_lines) - 40} more severe lines")

    if warning_lines:
        print(f"\n--- WARNINGS (first 20) ---")
        for line in warning_lines[:20]:
            print(f"  {line}")
        if len(warning_lines) > 20:
            print(f"  ... and {len(warning_lines) - 20} more warning lines")

    if not fatal_lines and not severe_lines and not warning_lines:
        print("\n  No errors or warnings found. Simulation completed cleanly.")


def cmd_summary(args):
    """Extract summary from HTML report or SQL database."""
    # Try SQL first (more structured)
    sql_path = find_file(args.output_dir, args.prefix, ".sql")
    if sql_path:
        _summary_from_sql(sql_path)
        return

    # Fallback to HTML
    html_path = find_file(args.output_dir, args.prefix, "tbl.htm")
    if not html_path:
        html_path = find_file(args.output_dir, args.prefix, "Table.html")
    if not html_path:
        html_path = find_file(args.output_dir, args.prefix, ".html")

    if html_path:
        _summary_from_html(html_path)
        return

    print(f"No summary report (.sql or .html) found in {args.output_dir}")
    sys.exit(1)


def _summary_from_sql(sql_path):
    """Extract summary data from SQLite database."""
    print(f"=== Energy Summary (from {os.path.basename(sql_path)}) ===\n")

    conn = sqlite3.connect(sql_path)
    cursor = conn.cursor()

    # Get available tables
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
    )
    tables = [row[0] for row in cursor.fetchall()]

    # Site and Source Energy
    try:
        cursor.execute("""
            SELECT RowName, Value, Units
            FROM TabularDataWithStrings
            WHERE TableName='Site and Source Energy'
            AND ReportName='AnnualBuildingUtilityPerformanceSummary'
            ORDER BY RowName
        """)
        rows = cursor.fetchall()
        if rows:
            print("  Site and Source Energy:")
            for row in rows:
                print(f"    {row[0]:<40s} {row[1]:>15s} {row[2]}")
            print()
    except sqlite3.OperationalError:
        pass

    # End Uses
    try:
        cursor.execute("""
            SELECT RowName, ColumnName, Value, Units
            FROM TabularDataWithStrings
            WHERE TableName='End Uses'
            AND ReportName='AnnualBuildingUtilityPerformanceSummary'
            ORDER BY RowName, ColumnName
        """)
        rows = cursor.fetchall()
        if rows:
            print("  End Uses:")
            current_row = None
            for row in rows:
                if row[0] != current_row:
                    current_row = row[0]
                    print(f"\n    {current_row}:")
                val = row[2]
                if val and val.strip() and val.strip() != "0.00":
                    print(f"      {row[1]:<30s} {val:>12s} {row[3]}")
            print()
    except sqlite3.OperationalError:
        pass

    # Unmet Hours
    try:
        cursor.execute("""
            SELECT RowName, Value, Units
            FROM TabularDataWithStrings
            WHERE TableName='Comfort and Setpoint Not Met Summary'
            AND ReportName='AnnualBuildingUtilityPerformanceSummary'
            ORDER BY RowName
        """)
        rows = cursor.fetchall()
        if rows:
            print("  Comfort and Setpoint Not Met:")
            for row in rows:
                print(f"    {row[0]:<50s} {row[1]:>10s} {row[2]}")
            print()
    except sqlite3.OperationalError:
        pass

    # Building Area
    try:
        cursor.execute("""
            SELECT RowName, Value, Units
            FROM TabularDataWithStrings
            WHERE TableName='Building Area'
            AND ReportName='AnnualBuildingUtilityPerformanceSummary'
            ORDER BY RowName
        """)
        rows = cursor.fetchall()
        if rows:
            print("  Building Area:")
            for row in rows:
                print(f"    {row[0]:<40s} {row[1]:>15s} {row[2]}")
            print()
    except sqlite3.OperationalError:
        pass

    conn.close()


def _summary_from_html(html_path):
    """Extract summary from HTML report table."""
    print(f"=== Energy Summary (from {os.path.basename(html_path)}) ===\n")

    with open(html_path, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()

    # Simple extraction: find key sections
    # Look for "Site and Source Energy" table
    sections = [
        "Site and Source Energy",
        "End Uses",
        "Building Area",
        "Comfort and Setpoint Not Met",
    ]

    for section in sections:
        idx = content.find(section)
        if idx != -1:
            # Extract a chunk around the section
            chunk = content[idx : idx + 3000]
            # Strip HTML tags for basic display
            clean = re.sub(r"<[^>]+>", " ", chunk)
            clean = re.sub(r"\s+", " ", clean).strip()
            # Take first 500 chars
            print(f"  {section}:")
            print(f"    {clean[:500]}")
            print()


def cmd_timeseries(args):
    """Parse CSV or SQL for time-series data."""
    # Try CSV first
    csv_path = find_file(args.output_dir, args.prefix, ".csv")

    if csv_path:
        _timeseries_from_csv(csv_path, args.variable, args.zone, args.start, args.end)
        return

    # Fallback to SQL
    sql_path = find_file(args.output_dir, args.prefix, ".sql")
    if sql_path:
        _timeseries_from_sql(sql_path, args.variable, args.zone)
        return

    print(f"No .csv or .sql file found in {args.output_dir}")
    print("Ensure simulation was run with --readvars flag for CSV output,")
    print("or Output:SQLite object is in the IDF for SQL output.")
    sys.exit(1)


def _timeseries_from_csv(csv_path, variable, zone=None, start=None, end=None):
    """Extract time-series data from CSV file."""
    print(f"=== Time Series: {variable} ===")
    print(f"  Source: {os.path.basename(csv_path)}\n")

    with open(csv_path, "r", encoding="utf-8", errors="replace") as f:
        reader = csv.reader(f)
        headers = next(reader)

    # Find matching columns
    var_lower = variable.lower()
    zone_lower = zone.lower() if zone else None

    matching_cols = []
    for i, h in enumerate(headers):
        h_lower = h.lower()
        if var_lower in h_lower:
            if zone_lower is None or zone_lower in h_lower:
                matching_cols.append((i, h))

    if not matching_cols:
        print(f"  Variable '{variable}' not found in CSV columns.")
        print(f"\n  Available columns ({len(headers)}):")
        for h in headers[:50]:
            print(f"    - {h}")
        if len(headers) > 50:
            print(f"    ... and {len(headers) - 50} more")
        return

    print(f"  Matching columns ({len(matching_cols)}):")
    for _, h in matching_cols:
        print(f"    - {h}")
    print()

    # Read data for matching columns
    data = {i: [] for i, _ in matching_cols}
    row_count = 0

    with open(csv_path, "r", encoding="utf-8", errors="replace") as f:
        reader = csv.reader(f)
        next(reader)  # skip header
        for row in reader:
            row_count += 1
            for i, _ in matching_cols:
                if i < len(row):
                    try:
                        data[i].append(float(row[i]))
                    except (ValueError, IndexError):
                        pass

    # Statistics
    print(f"  Data Points: {row_count}\n")
    print(f"  {'Column':<60s} {'Min':>10s} {'Max':>10s} {'Mean':>10s} {'StdDev':>10s}")
    print("  " + "-" * 95)

    for i, h in matching_cols:
        values = data[i]
        if values:
            v_min = min(values)
            v_max = max(values)
            v_mean = mean(values)
            v_std = stdev(values) if len(values) > 1 else 0.0
            # Truncate header for display
            h_short = h[:58] if len(h) > 58 else h
            print(f"  {h_short:<60s} {v_min:>10.2f} {v_max:>10.2f} {v_mean:>10.2f} {v_std:>10.2f}")

    # Show first N rows
    print(f"\n  First 30 data rows:")
    with open(csv_path, "r", encoding="utf-8", errors="replace") as f:
        reader = csv.reader(f)
        headers = next(reader)
        # Print header for selected columns
        col_headers = [headers[0]] + [headers[i] for i, _ in matching_cols]
        print(f"  {col_headers[0]:<25s}", end="")
        for ch in col_headers[1:]:
            ch_short = ch[:25] if len(ch) > 25 else ch
            print(f"  {ch_short:>25s}", end="")
        print()

        count = 0
        for row in reader:
            if count >= 30:
                break
            dt = row[0] if row else ""
            print(f"  {dt:<25s}", end="")
            for i, _ in matching_cols:
                val = row[i] if i < len(row) else ""
                print(f"  {val:>25s}", end="")
            print()
            count += 1


def _timeseries_from_sql(sql_path, variable, zone=None):
    """Extract time-series data from SQL database."""
    print(f"=== Time Series: {variable} (from SQL) ===\n")

    conn = sqlite3.connect(sql_path)
    cursor = conn.cursor()

    # Find matching variables in ReportDataDictionary
    cursor.execute("""
        SELECT ReportDataDictionaryIndex, KeyValue, Name, Units
        FROM ReportDataDictionary
        WHERE Name LIKE ?
        ORDER BY KeyValue, Name
    """, (f"%{variable}%",))

    matches = cursor.fetchall()
    if not matches:
        print(f"  Variable '{variable}' not found in SQL database.")
        cursor.execute("SELECT DISTINCT Name FROM ReportDataDictionary ORDER BY Name")
        all_vars = cursor.fetchall()
        print(f"\n  Available variables ({len(all_vars)}):")
        for v in all_vars[:50]:
            print(f"    - {v[0]}")
        conn.close()
        return

    # Filter by zone if specified
    if zone:
        matches = [m for m in matches if zone.lower() in m[1].lower()]

    print(f"  Found {len(matches)} matching variable(s):")
    for m in matches:
        print(f"    [{m[0]}] {m[1]} : {m[2]} [{m[3]}]")

    # Get data for first match
    if matches:
        idx = matches[0][0]
        cursor.execute("""
            SELECT t.Month, t.Day, t.Hour, t.Minute, rd.Value
            FROM ReportData rd
            JOIN Time t ON rd.TimeIndex = t.TimeIndex
            WHERE rd.ReportDataDictionaryIndex = ?
            ORDER BY t.TimeIndex
            LIMIT 100
        """, (idx,))

        rows = cursor.fetchall()
        if rows:
            values = [r[4] for r in rows if r[4] is not None]
            if values:
                print(f"\n  Statistics: min={min(values):.2f}, max={max(values):.2f}, "
                      f"mean={mean(values):.2f}")

            print(f"\n  First {min(30, len(rows))} data points:")
            print(f"  {'Month':>5s} {'Day':>4s} {'Hour':>5s} {'Min':>4s} {'Value':>12s}")
            for r in rows[:30]:
                print(f"  {r[0]:>5d} {r[1]:>4d} {r[2]:>5d} {r[3]:>4d} {r[4]:>12.4f}")

    conn.close()


def cmd_sql(args):
    """Execute SQL query against the output database."""
    sql_path = find_file(args.output_dir, args.prefix, ".sql")
    if not sql_path:
        print(f"No .sql file found in {args.output_dir}")
        print("Ensure the IDF has 'Output:SQLite, SimpleAndTabular;'")
        sys.exit(1)

    print(f"=== SQL Query Result ===")
    print(f"  Database: {os.path.basename(sql_path)}")
    print(f"  Query: {args.query}\n")

    conn = sqlite3.connect(sql_path)
    cursor = conn.cursor()

    try:
        cursor.execute(args.query)
        columns = [desc[0] for desc in cursor.description] if cursor.description else []
        rows = cursor.fetchall()

        if columns:
            # Print header
            header = "  ".join(f"{c:<20s}" for c in columns)
            print(f"  {header}")
            print("  " + "-" * len(header))

            # Print rows
            for row in rows[:50]:
                vals = "  ".join(f"{str(v):<20s}" for v in row)
                print(f"  {vals}")

            if len(rows) > 50:
                print(f"\n  ... showing 50 of {len(rows)} rows")
            else:
                print(f"\n  {len(rows)} row(s)")
        else:
            print("  Query executed successfully (no results returned).")

    except sqlite3.OperationalError as e:
        print(f"  SQL Error: {e}")
        print("\n  Available tables:")
        cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        for row in cursor.fetchall():
            print(f"    - {row[0]}")

    conn.close()


def cmd_available_vars(args):
    """List available output variables from .rdd file."""
    rdd_path = find_file(args.output_dir, args.prefix, ".rdd")
    if not rdd_path:
        print(f"No .rdd file found in {args.output_dir}")
        print("Run a simulation first to generate the .rdd file.")
        sys.exit(1)

    print(f"=== Available Output Variables ===")
    print(f"  Source: {os.path.basename(rdd_path)}\n")

    variables = []
    with open(rdd_path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            stripped = line.strip()
            if stripped and not stripped.startswith("Program Version"):
                variables.append(stripped)

    for v in variables:
        print(f"  {v}")

    print(f"\n  Total: {len(variables)} variables")


def cmd_available_meters(args):
    """List available meters from .mdd file."""
    mdd_path = find_file(args.output_dir, args.prefix, ".mdd")
    if not mdd_path:
        print(f"No .mdd file found in {args.output_dir}")
        print("Run a simulation first to generate the .mdd file.")
        sys.exit(1)

    print(f"=== Available Meters ===")
    print(f"  Source: {os.path.basename(mdd_path)}\n")

    meters = []
    with open(mdd_path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            stripped = line.strip()
            if stripped and not stripped.startswith("Program Version"):
                meters.append(stripped)

    for m in meters:
        print(f"  {m}")

    print(f"\n  Total: {len(meters)} meters")


def main():
    parser = argparse.ArgumentParser(
        description="EnergyPlus Output Parser"
    )
    subparsers = parser.add_subparsers(dest="command", help="Command")

    # errors
    p_err = subparsers.add_parser("errors", help="Parse .err file")
    p_err.add_argument("output_dir", help="Output directory path")
    p_err.add_argument("--prefix", default="eplusout", help="Output file prefix")

    # summary
    p_sum = subparsers.add_parser("summary", help="Extract energy summary")
    p_sum.add_argument("output_dir", help="Output directory path")
    p_sum.add_argument("--prefix", default="eplusout", help="Output file prefix")

    # timeseries
    p_ts = subparsers.add_parser("timeseries", help="Extract time-series data")
    p_ts.add_argument("output_dir", help="Output directory path")
    p_ts.add_argument("--variable", required=True, help="Variable name to extract")
    p_ts.add_argument("--zone", help="Zone name to filter by")
    p_ts.add_argument("--start", help="Start date (YYYY-MM-DD)")
    p_ts.add_argument("--end", help="End date (YYYY-MM-DD)")
    p_ts.add_argument("--prefix", default="eplusout", help="Output file prefix")

    # sql
    p_sql = subparsers.add_parser("sql", help="Execute SQL query")
    p_sql.add_argument("output_dir", help="Output directory path")
    p_sql.add_argument("--query", required=True, help="SQL query string")
    p_sql.add_argument("--prefix", default="eplusout", help="Output file prefix")

    # available-vars
    p_av = subparsers.add_parser("available-vars", help="List available output variables")
    p_av.add_argument("output_dir", help="Output directory path")
    p_av.add_argument("--prefix", default="eplusout", help="Output file prefix")

    # available-meters
    p_am = subparsers.add_parser("available-meters", help="List available meters")
    p_am.add_argument("output_dir", help="Output directory path")
    p_am.add_argument("--prefix", default="eplusout", help="Output file prefix")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    # Validate output directory
    if not os.path.isdir(args.output_dir):
        print(f"Error: Output directory not found: {args.output_dir}")
        sys.exit(1)

    commands = {
        "errors": cmd_errors,
        "summary": cmd_summary,
        "timeseries": cmd_timeseries,
        "sql": cmd_sql,
        "available-vars": cmd_available_vars,
        "available-meters": cmd_available_meters,
    }

    commands[args.command](args)


if __name__ == "__main__":
    main()
