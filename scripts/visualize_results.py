#!/usr/bin/env python
"""EnergyPlus simulation result visualization tool.

Generates charts from EnergyPlus simulation output data.

Usage:
    python visualize_results.py --type line --data <output_dir> --variable <name> --output <image_path>
    python visualize_results.py --type end-use-bar --data <output_dir> --output <image_path>
    python visualize_results.py --type monthly --data <output_dir> --output <image_path>
    python visualize_results.py --type heatmap --data <output_dir> --variable <name> --zone <name> --output <image_path>
    python visualize_results.py --type comparison --data <output_dir> --variables <v1,v2> --output <image_path>
    python visualize_results.py --type load-profile --data <output_dir> --variable <name> --output <image_path>
"""

import argparse
import csv
import os
import sqlite3
import sys
from datetime import datetime, timedelta
from statistics import mean

try:
    import matplotlib
    matplotlib.use("Agg")  # Non-interactive backend
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    from matplotlib.colors import LinearSegmentedColormap
    import numpy as np
except ImportError:
    print("Error: matplotlib is required for visualization.")
    print("Install with: pip install matplotlib")
    sys.exit(1)


# Style configuration
plt.rcParams.update({
    "figure.facecolor": "white",
    "axes.facecolor": "#f8f9fa",
    "axes.grid": True,
    "grid.alpha": 0.3,
    "font.size": 10,
})


def find_file(output_dir, extension):
    """Find an output file by extension."""
    for f in os.listdir(output_dir):
        if f.endswith(extension):
            return os.path.join(output_dir, f)
    return None


def read_csv_data(csv_path, variable=None, zone=None):
    """Read CSV data, optionally filtering by variable and zone."""
    with open(csv_path, "r", encoding="utf-8", errors="replace") as f:
        reader = csv.reader(f)
        headers = next(reader)
        data = list(reader)

    if variable is None:
        return headers, data

    var_lower = variable.lower()
    zone_lower = zone.lower() if zone else None

    matching_cols = []
    for i, h in enumerate(headers):
        h_lower = h.lower()
        if var_lower in h_lower:
            if zone_lower is None or zone_lower in h_lower:
                matching_cols.append(i)

    return headers, data, matching_cols


def parse_datetime_column(data):
    """Parse the first column (Date/Time) from EnergyPlus CSV output."""
    datetimes = []
    for row in data:
        if not row:
            continue
        dt_str = row[0].strip()
        try:
            # EnergyPlus format: " 01/01  01:00:00" or "01/01 01:00:00"
            dt_str = dt_str.strip()
            # Try common EnergyPlus datetime formats
            for fmt in [
                "%m/%d  %H:%M:%S",
                "%m/%d %H:%M:%S",
                "%Y-%m-%d %H:%M:%S",
                "%m/%d/%Y %H:%M:%S",
                "%m/%d/%Y  %H:%M:%S",
            ]:
                try:
                    dt = datetime.strptime(dt_str, fmt)
                    # If no year, use 2024
                    if dt.year == 1900:
                        dt = dt.replace(year=2024)
                    datetimes.append(dt)
                    break
                except ValueError:
                    continue
            else:
                # Try to parse as a number (hours from start)
                datetimes.append(None)
        except Exception:
            datetimes.append(None)
    return datetimes


def chart_line(args):
    """Generate time-series line chart."""
    csv_path = find_file(args.data, ".csv")
    if not csv_path:
        print("Error: No .csv file found. Run simulation with --readvars.")
        sys.exit(1)

    headers, data, matching_cols = read_csv_data(csv_path, args.variable, args.zone)

    if not matching_cols:
        print(f"Error: Variable '{args.variable}' not found in CSV.")
        print(f"Available columns: {headers[1:6]}...")
        sys.exit(1)

    datetimes = parse_datetime_column(data)

    fig, ax = plt.subplots(figsize=tuple(map(float, args.figsize.split(","))))

    for col_idx in matching_cols:
        values = []
        valid_dts = []
        for i, row in enumerate(data):
            if i < len(datetimes) and datetimes[i] and col_idx < len(row):
                try:
                    values.append(float(row[col_idx]))
                    valid_dts.append(datetimes[i])
                except (ValueError, IndexError):
                    pass

        label = headers[col_idx]
        # Shorten label if too long
        if len(label) > 60:
            label = label[:57] + "..."
        ax.plot(valid_dts, values, linewidth=0.8, label=label, alpha=0.85)

    ax.set_xlabel("Date/Time")
    ax.set_ylabel(args.variable)
    ax.set_title(args.title or f"Time Series: {args.variable}")

    if len(matching_cols) <= 10:
        ax.legend(fontsize=8, loc="best")

    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d"))
    ax.xaxis.set_major_locator(mdates.MonthLocator())
    fig.autofmt_xdate()
    plt.tight_layout()
    plt.savefig(args.output, dpi=int(args.dpi))
    plt.close()

    print(f"Chart saved to: {args.output}")
    print(f"  Type: line chart")
    print(f"  Variable: {args.variable}")
    print(f"  Series: {len(matching_cols)}")
    print(f"  Data points per series: {len(data)}")


def chart_end_use_bar(args):
    """Generate energy end-use breakdown bar chart."""
    sql_path = find_file(args.data, ".sql")
    if not sql_path:
        print("Error: No .sql file found. Ensure IDF has 'Output:SQLite, SimpleAndTabular;'")
        sys.exit(1)

    conn = sqlite3.connect(sql_path)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT RowName, ColumnName, Value
        FROM TabularDataWithStrings
        WHERE TableName='End Uses'
        AND ReportName='AnnualBuildingUtilityPerformanceSummary'
        AND Value != ''
        AND Value != '0.00'
        ORDER BY RowName
    """)
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        print("Error: No 'End Uses' data found in SQL database.")
        sys.exit(1)

    # Organize data
    end_uses = {}
    fuel_types = set()
    for row_name, col_name, value in rows:
        try:
            val = float(value)
            if val > 0:
                if row_name not in end_uses:
                    end_uses[row_name] = {}
                end_uses[row_name][col_name] = val
                fuel_types.add(col_name)
        except ValueError:
            pass

    # Remove "Total End Uses" if present for the bar chart
    end_uses.pop("Total End Uses", None)

    if not end_uses:
        print("Error: No non-zero end use data found.")
        sys.exit(1)

    fuel_types = sorted(fuel_types)
    categories = list(end_uses.keys())

    fig, ax = plt.subplots(figsize=tuple(map(float, args.figsize.split(","))))

    colors = plt.cm.Set2(range(len(fuel_types)))
    bottom = [0.0] * len(categories)

    for j, fuel in enumerate(fuel_types):
        vals = [end_uses.get(cat, {}).get(fuel, 0) for cat in categories]
        ax.barh(categories, vals, left=bottom, label=fuel, color=colors[j])
        bottom = [b + v for b, v in zip(bottom, vals)]

    ax.set_xlabel("Energy (GJ)")
    ax.set_title(args.title or "Energy End-Use Breakdown")
    ax.legend(loc="lower right", fontsize=8)
    plt.tight_layout()
    plt.savefig(args.output, dpi=int(args.dpi))
    plt.close()

    print(f"Chart saved to: {args.output}")
    print(f"  Type: end-use bar chart")
    print(f"  End uses: {len(categories)}")
    print(f"  Fuel types: {', '.join(fuel_types)}")


def chart_monthly(args):
    """Generate monthly energy consumption bar chart."""
    sql_path = find_file(args.data, ".sql")
    if not sql_path:
        print("Error: No .sql file found.")
        sys.exit(1)

    conn = sqlite3.connect(sql_path)
    cursor = conn.cursor()

    # Try to get monthly data from End Uses By Month
    cursor.execute("""
        SELECT RowName, ColumnName, Value
        FROM TabularDataWithStrings
        WHERE TableName='End Uses By Month'
        AND ReportName='AnnualBuildingUtilityPerformanceSummary'
        AND Value != ''
        ORDER BY RowName
    """)
    rows = cursor.fetchall()

    if not rows:
        # Fallback: aggregate from ReportData by month
        cursor.execute("""
            SELECT t.Month, SUM(rd.Value) as TotalValue
            FROM ReportData rd
            JOIN Time t ON rd.TimeIndex = t.TimeIndex
            GROUP BY t.Month
            ORDER BY t.Month
        """)
        monthly_rows = cursor.fetchall()
        conn.close()

        if not monthly_rows:
            print("Error: No monthly data available.")
            sys.exit(1)

        months = [r[0] for r in monthly_rows]
        values = [r[1] for r in monthly_rows]
        month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                       "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

        fig, ax = plt.subplots(figsize=tuple(map(float, args.figsize.split(","))))
        labels = [month_names[m - 1] if 1 <= m <= 12 else str(m) for m in months]
        ax.bar(labels, values, color="#4285f4")
        ax.set_xlabel("Month")
        ax.set_ylabel("Energy")
        ax.set_title(args.title or "Monthly Energy Consumption")
        plt.tight_layout()
        plt.savefig(args.output, dpi=int(args.dpi))
        plt.close()
        print(f"Chart saved to: {args.output}")
        return

    conn.close()

    # Parse monthly end-use data
    months_order = ["January", "February", "March", "April", "May", "June",
                    "July", "August", "September", "October", "November", "December"]
    month_short = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                   "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

    end_uses_by_month = {}
    end_use_names = set()
    for row_name, col_name, value in rows:
        try:
            val = float(value)
            if val > 0 and col_name in months_order:
                if row_name not in end_uses_by_month:
                    end_uses_by_month[row_name] = {}
                end_uses_by_month[row_name][col_name] = val
                end_use_names.add(row_name)
        except ValueError:
            pass

    fig, ax = plt.subplots(figsize=tuple(map(float, args.figsize.split(","))))

    x = range(12)
    width = 0.8 / max(len(end_use_names), 1)
    colors = plt.cm.Set2(range(len(end_use_names)))

    for i, eu in enumerate(sorted(end_use_names)):
        vals = [end_uses_by_month.get(eu, {}).get(m, 0) for m in months_order]
        offset = (i - len(end_use_names) / 2 + 0.5) * width
        ax.bar([xi + offset for xi in x], vals, width, label=eu, color=colors[i])

    ax.set_xticks(x)
    ax.set_xticklabels(month_short)
    ax.set_xlabel("Month")
    ax.set_ylabel("Energy (GJ)")
    ax.set_title(args.title or "Monthly Energy Consumption by End Use")
    ax.legend(fontsize=7, loc="upper right")
    plt.tight_layout()
    plt.savefig(args.output, dpi=int(args.dpi))
    plt.close()

    print(f"Chart saved to: {args.output}")
    print(f"  Type: monthly bar chart")
    print(f"  End uses: {len(end_use_names)}")


def chart_heatmap(args):
    """Generate hourly data heatmap (24h x days)."""
    if not args.variable:
        print("Error: --variable is required for heatmap charts.")
        sys.exit(1)

    csv_path = find_file(args.data, ".csv")
    if not csv_path:
        print("Error: No .csv file found. Run simulation with --readvars.")
        sys.exit(1)

    headers, data, matching_cols = read_csv_data(csv_path, args.variable, args.zone)

    if not matching_cols:
        print(f"Error: Variable '{args.variable}' not found.")
        sys.exit(1)

    col_idx = matching_cols[0]

    # Parse values with datetime
    datetimes = parse_datetime_column(data)
    hourly_data = {}

    for i, row in enumerate(data):
        if i < len(datetimes) and datetimes[i] and col_idx < len(row):
            try:
                dt = datetimes[i]
                day_of_year = dt.timetuple().tm_yday
                hour = dt.hour
                val = float(row[col_idx])
                hourly_data[(day_of_year, hour)] = val
            except (ValueError, IndexError):
                pass

    if not hourly_data:
        print("Error: No valid data for heatmap.")
        sys.exit(1)

    # Build 24 x 365 matrix
    max_day = max(d for d, h in hourly_data.keys())
    matrix = [[float("nan")] * max_day for _ in range(24)]

    for (day, hour), val in hourly_data.items():
        if 0 <= hour < 24 and 1 <= day <= max_day:
            matrix[hour][day - 1] = val

    fig, ax = plt.subplots(figsize=tuple(map(float, args.figsize.split(","))))

    im = ax.imshow(
        matrix,
        aspect="auto",
        cmap="RdYlBu_r",
        interpolation="nearest",
        origin="lower",
    )

    ax.set_ylabel("Hour of Day")
    ax.set_xlabel("Day of Year")
    ax.set_title(args.title or f"Heatmap: {headers[col_idx]}")

    # Month labels on x-axis
    month_starts = [1, 32, 60, 91, 121, 152, 182, 213, 244, 274, 305, 335]
    month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                   "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    valid_ticks = [(d - 1) for d in month_starts if d <= max_day]
    valid_labels = [month_names[i] for i, d in enumerate(month_starts) if d <= max_day]
    ax.set_xticks(valid_ticks)
    ax.set_xticklabels(valid_labels)

    ax.set_yticks(range(0, 24, 3))
    ax.set_yticklabels([f"{h:02d}:00" for h in range(0, 24, 3)])

    cbar = plt.colorbar(im, ax=ax, shrink=0.8)
    cbar.set_label(args.variable)

    plt.tight_layout()
    plt.savefig(args.output, dpi=int(args.dpi))
    plt.close()

    print(f"Chart saved to: {args.output}")
    print(f"  Type: heatmap (24h x {max_day} days)")
    print(f"  Variable: {headers[col_idx]}")


def chart_comparison(args):
    """Generate multi-variable or multi-zone comparison chart."""
    csv_path = find_file(args.data, ".csv")
    if not csv_path:
        print("Error: No .csv file found.")
        sys.exit(1)

    variables = args.variables.split(",") if args.variables else []
    zones = args.zones.split(",") if args.zones else []

    with open(csv_path, "r", encoding="utf-8", errors="replace") as f:
        reader = csv.reader(f)
        headers = next(reader)
        data = list(reader)

    datetimes = parse_datetime_column(data)

    fig, ax = plt.subplots(figsize=tuple(map(float, args.figsize.split(","))))

    series_count = 0
    for var in (variables or [args.variable or ""]):
        var_lower = var.strip().lower()
        for i, h in enumerate(headers):
            h_lower = h.lower()
            if var_lower and var_lower in h_lower:
                # Zone filter
                if zones:
                    zone_match = any(z.strip().lower() in h_lower for z in zones)
                    if not zone_match:
                        continue

                values = []
                valid_dts = []
                for j, row in enumerate(data):
                    if j < len(datetimes) and datetimes[j] and i < len(row):
                        try:
                            values.append(float(row[i]))
                            valid_dts.append(datetimes[j])
                        except (ValueError, IndexError):
                            pass

                if values:
                    label = h[:60] if len(h) > 60 else h
                    ax.plot(valid_dts, values, linewidth=0.8, label=label, alpha=0.85)
                    series_count += 1

    ax.set_xlabel("Date/Time")
    ax.set_title(args.title or "Variable Comparison")
    if series_count <= 10:
        ax.legend(fontsize=7, loc="best")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%m/%d"))
    fig.autofmt_xdate()
    plt.tight_layout()
    plt.savefig(args.output, dpi=int(args.dpi))
    plt.close()

    print(f"Chart saved to: {args.output}")
    print(f"  Type: comparison chart")
    print(f"  Series plotted: {series_count}")


def chart_load_profile(args):
    """Generate average daily load profile (24-hour curve)."""
    if not args.variable:
        print("Error: --variable is required for load profile charts.")
        sys.exit(1)

    csv_path = find_file(args.data, ".csv")
    if not csv_path:
        print("Error: No .csv file found.")
        sys.exit(1)

    headers, data, matching_cols = read_csv_data(csv_path, args.variable, args.zone)

    if not matching_cols:
        print(f"Error: Variable '{args.variable}' not found.")
        sys.exit(1)

    col_idx = matching_cols[0]
    datetimes = parse_datetime_column(data)

    # Group by hour of day
    hourly_values = {h: [] for h in range(24)}
    for i, row in enumerate(data):
        if i < len(datetimes) and datetimes[i] and col_idx < len(row):
            try:
                hour = datetimes[i].hour
                val = float(row[col_idx])
                hourly_values[hour].append(val)
            except (ValueError, IndexError):
                pass

    hours = list(range(24))
    avg_values = [mean(hourly_values[h]) if hourly_values[h] else 0 for h in hours]
    min_values = [min(hourly_values[h]) if hourly_values[h] else 0 for h in hours]
    max_values = [max(hourly_values[h]) if hourly_values[h] else 0 for h in hours]

    fig, ax = plt.subplots(figsize=tuple(map(float, args.figsize.split(","))))

    ax.fill_between(hours, min_values, max_values, alpha=0.2, color="#4285f4",
                    label="Min-Max Range")
    ax.plot(hours, avg_values, linewidth=2, color="#4285f4", label="Average",
            marker="o", markersize=4)

    ax.set_xlabel("Hour of Day")
    ax.set_ylabel(args.variable)
    ax.set_title(args.title or f"Daily Load Profile: {headers[col_idx][:50]}")
    ax.set_xticks(range(0, 24, 2))
    ax.set_xticklabels([f"{h:02d}:00" for h in range(0, 24, 2)])
    ax.legend()
    plt.tight_layout()
    plt.savefig(args.output, dpi=int(args.dpi))
    plt.close()

    print(f"Chart saved to: {args.output}")
    print(f"  Type: daily load profile")
    print(f"  Variable: {headers[col_idx]}")
    print(f"  Average values by hour: min={min(avg_values):.2f}, max={max(avg_values):.2f}")


def main():
    parser = argparse.ArgumentParser(
        description="EnergyPlus Visualization Tool"
    )
    parser.add_argument(
        "--type", required=True,
        choices=["line", "end-use-bar", "monthly", "heatmap", "comparison", "load-profile"],
        help="Chart type"
    )
    parser.add_argument("--data", required=True, help="Output directory path")
    parser.add_argument("--variable", help="Variable name")
    parser.add_argument("--zone", help="Zone name filter")
    parser.add_argument("--variables", help="Comma-separated variable names (for comparison)")
    parser.add_argument("--zones", help="Comma-separated zone names (for comparison)")
    parser.add_argument("--output", required=True, help="Output image path (.png)")
    parser.add_argument("--title", help="Custom chart title")
    parser.add_argument("--figsize", default="12,6", help="Figure size as W,H (default: 12,6)")
    parser.add_argument("--dpi", default="150", help="Output DPI (default: 150)")

    args = parser.parse_args()

    if not os.path.isdir(args.data):
        print(f"Error: Data directory not found: {args.data}")
        sys.exit(1)

    chart_functions = {
        "line": chart_line,
        "end-use-bar": chart_end_use_bar,
        "monthly": chart_monthly,
        "heatmap": chart_heatmap,
        "comparison": chart_comparison,
        "load-profile": chart_load_profile,
    }

    chart_functions[args.type](args)


if __name__ == "__main__":
    main()
