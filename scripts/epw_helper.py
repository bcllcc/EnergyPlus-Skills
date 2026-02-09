#!/usr/bin/env python
"""EnergyPlus EPW weather file helper tool.

Provides reading, writing, validation, and statistics for EPW files.

Usage:
    python epw_helper.py summary <epw_path>
    python epw_helper.py read <epw_path> --field <name_or_index> [--month M] [--day D] [--hour H] [--start M/D --end M/D]
    python epw_helper.py write <epw_path> --output <out.epw> --field <name_or_index> --value <val> [time filters]
    python epw_helper.py inject <epw_path> --csv <data.csv> --output <out.epw> --mapping <map>
    python epw_helper.py validate <epw_path>
    python epw_helper.py stats <epw_path> [--monthly] [--field <name_or_index>]
    python epw_helper.py create --location "<city,state,country,source,wmo,lat,lon,tz,elev>" --csv <data.csv> --output <out.epw>
    python epw_helper.py compare <epw_a> <epw_b>

Field reference: EnergyPlus AuxiliaryPrograms.pdf, Section 2.9
"""

import argparse
import csv
import os
import sys
from statistics import mean, stdev

# ---------------------------------------------------------------------------
# EPW field definitions — Source: AuxiliaryPrograms.pdf Section 2.9, p.62-63
# (index, name, units, missing_value, min_val, max_val, used_by_ep)
# index is 0-based position in the comma-separated data line (35 fields total)
# ---------------------------------------------------------------------------
EPW_FIELDS = [
    (0,  "Year",                                    "",           None,    None,   None,    False),
    (1,  "Month",                                   "",           None,    1,      12,      True),
    (2,  "Day",                                     "",           None,    1,      31,      True),
    (3,  "Hour",                                    "",           None,    1,      24,      True),
    (4,  "Minute",                                  "",           None,    1,      60,      True),
    (5,  "Data Source and Uncertainty Flags",        "",           None,    None,   None,    True),
    (6,  "Dry Bulb Temperature",                    "C",          99.9,    -70,    70,      True),
    (7,  "Dew Point Temperature",                   "C",          99.9,    -70,    70,      True),
    (8,  "Relative Humidity",                       "%",          999,     0,      110,     True),
    (9,  "Atmospheric Station Pressure",            "Pa",         999999,  31000,  120000,  True),
    (10, "Extraterrestrial Horizontal Radiation",   "Wh/m2",      9999,    0,      None,    False),
    (11, "Extraterrestrial Direct Normal Radiation","Wh/m2",      9999,    0,      None,    False),
    (12, "Horizontal Infrared Radiation Intensity", "Wh/m2",      9999,    0,      None,    True),
    (13, "Global Horizontal Radiation",             "Wh/m2",      9999,    0,      None,    False),
    (14, "Direct Normal Radiation",                 "Wh/m2",      9999,    0,      None,    True),
    (15, "Diffuse Horizontal Radiation",            "Wh/m2",      9999,    0,      None,    True),
    (16, "Global Horizontal Illuminance",           "lux",        999999,  0,      None,    False),
    (17, "Direct Normal Illuminance",               "lux",        999999,  0,      None,    False),
    (18, "Diffuse Horizontal Illuminance",          "lux",        999999,  0,      None,    False),
    (19, "Zenith Luminance",                        "Cd/m2",      9999,    0,      None,    False),
    (20, "Wind Direction",                          "deg",        999,     0,      360,     True),
    (21, "Wind Speed",                              "m/s",        999,     0,      40,      True),
    (22, "Total Sky Cover",                         "tenths",     99,      0,      10,      True),
    (23, "Opaque Sky Cover",                        "tenths",     99,      0,      10,      True),
    (24, "Visibility",                              "km",         9999,    None,   None,    False),
    (25, "Ceiling Height",                          "m",          99999,   None,   None,    False),
    (26, "Present Weather Observation",             "",           None,    None,   None,    True),
    (27, "Present Weather Codes",                   "",           None,    None,   None,    True),
    (28, "Precipitable Water",                      "mm",         999,     None,   None,    False),
    (29, "Aerosol Optical Depth",                   "thousandths",0.999,   None,   None,    False),
    (30, "Snow Depth",                              "cm",         999,     None,   None,    True),
    (31, "Days Since Last Snowfall",                "days",       99,      None,   None,    False),
    (32, "Albedo",                                  "",           999,     None,   None,    False),
    (33, "Liquid Precipitation Depth",              "mm",         999,     None,   None,    True),
    (34, "Liquid Precipitation Quantity",           "hr",         99,      None,   None,    False),
]

# Indices of key numeric fields for statistics (skip time, flags, weather codes)
KEY_STAT_FIELDS = [6, 7, 8, 9, 14, 15, 20, 21, 22]

HEADER_LINE_COUNT = 8
DEFAULT_DATA_SOURCE_FLAGS = "?9?9?9?9?9?9?9?9?9?9?9?9?9?9?9?9?9?9?9?9?9?9?9?9"


def _normalize_name(value):
    """Normalize names for robust fuzzy matching."""
    if value is None:
        return ""
    return "".join(ch for ch in str(value).lower() if ch.isalnum())


FIELD_NAME_MAP = {_normalize_name(f[1]): f[0] for f in EPW_FIELDS}
FIELD_ALIAS_MAP = {
    "temp": 6,
    "temperature": 6,
    "drybulb": 6,
    "drybulbtemp": 6,
    "drybulbtemperature": 6,
    "dewpoint": 7,
    "dewpointtemp": 7,
    "dewpointtemperature": 7,
    "rh": 8,
    "relativehumidity": 8,
    "pressure": 9,
    "atmosphericpressure": 9,
    "stationpressure": 9,
    "globalhorizontalradiation": 13,
    "directnormalradiation": 14,
    "diffusehorizontalradiation": 15,
    "winddir": 20,
    "winddirection": 20,
    "windspeed": 21,
    "totalskycover": 22,
    "opaqueskycover": 23,
    "datasourceflags": 5,
    "datasourceanduncertaintyflags": 5,
}


def _format_missing(value):
    """Format numeric missing markers without trailing .0 where possible."""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def _resolve_header_to_field_index(header):
    """Resolve CSV header text to EPW field index, or None if unknown."""
    normalized = _normalize_name(header).replace("whm2", "")
    if normalized in FIELD_NAME_MAP:
        return FIELD_NAME_MAP[normalized]
    return FIELD_ALIAS_MAP.get(normalized)


def _parse_location(location_str):
    """Parse --location argument for create command."""
    parts = [p.strip() for p in location_str.split(",")]
    if len(parts) != 9:
        print("Error: --location must have 9 comma-separated values:")
        print("  City,State,Country,Source,WMO,Lat,Lon,TZ,Elev")
        sys.exit(1)
    try:
        float(parts[5])  # lat
        float(parts[6])  # lon
        float(parts[7])  # tz
        float(parts[8])  # elev
    except ValueError:
        print("Error: Location fields Lat/Lon/TZ/Elev must be numeric")
        sys.exit(1)
    return parts


def _build_default_row(year, month, day, hour, minute=60):
    """Build a default EPW data row with required time fields and missing markers."""
    row = []
    for idx, _, _, missing_val, _, _, _ in EPW_FIELDS:
        if idx == 0:
            row.append(str(year))
        elif idx == 1:
            row.append(str(month))
        elif idx == 2:
            row.append(str(day))
        elif idx == 3:
            row.append(str(hour))
        elif idx == 4:
            row.append(str(minute))
        elif idx == 5:
            row.append(DEFAULT_DATA_SOURCE_FLAGS)
        elif missing_val is None:
            row.append("")
        else:
            row.append(_format_missing(missing_val))
    return row


def resolve_field(field_arg):
    """Resolve a field name or 1-based index to (0-based_index, field_tuple).

    Supports:
      - Integer (1-based position as shown in docs, e.g. 7 = Dry Bulb Temperature)
      - Name substring match (case-insensitive, e.g. "dry bulb")
    """
    # Try integer index first (1-based as in documentation)
    try:
        idx = int(field_arg) - 1  # convert to 0-based
        if 0 <= idx < len(EPW_FIELDS):
            return idx, EPW_FIELDS[idx]
        print(f"Error: Field index {field_arg} out of range (1-35)")
        sys.exit(1)
    except ValueError:
        pass

    # Name substring match (case-insensitive)
    query = field_arg.lower()
    matches = [(i, f) for i, f in enumerate(EPW_FIELDS) if query in f[1].lower()]
    if len(matches) == 1:
        return matches[0]
    elif len(matches) > 1:
        print(f"Error: Ambiguous field name '{field_arg}'. Matches:")
        for idx, f in matches:
            print(f"  {idx + 1:2d}. {f[1]}")
        sys.exit(1)
    else:
        print(f"Error: No field matching '{field_arg}'. Available fields:")
        for f in EPW_FIELDS:
            print(f"  {f[0] + 1:2d}. {f[1]} [{f[2]}]")
        sys.exit(1)


def parse_header(filepath):
    """Parse the 8 header lines of an EPW file.

    Returns dict with keys: location, design_conditions, typical_extreme,
    ground_temps, holidays, comments1, comments2, data_periods, raw_headers.
    """
    info = {"raw_headers": []}
    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        for i in range(HEADER_LINE_COUNT):
            line = f.readline().rstrip("\n\r")
            info["raw_headers"].append(line)

    # Line 1: LOCATION
    parts = info["raw_headers"][0].split(",")
    if len(parts) >= 10 and parts[0].upper() == "LOCATION":
        info["location"] = {
            "city": parts[1].strip(),
            "state": parts[2].strip(),
            "country": parts[3].strip(),
            "source": parts[4].strip(),
            "wmo": parts[5].strip(),
            "latitude": float(parts[6]) if parts[6].strip() else 0.0,
            "longitude": float(parts[7]) if parts[7].strip() else 0.0,
            "timezone": float(parts[8]) if parts[8].strip() else 0.0,
            "elevation": float(parts[9]) if parts[9].strip() else 0.0,
        }
    else:
        info["location"] = {"city": "Unknown", "state": "", "country": "",
                            "source": "", "wmo": "", "latitude": 0.0,
                            "longitude": 0.0, "timezone": 0.0, "elevation": 0.0}

    # Line 8: DATA PERIODS
    dp_parts = info["raw_headers"][7].split(",")
    if len(dp_parts) >= 7 and dp_parts[0].upper() == "DATA PERIODS":
        info["data_periods"] = {
            "count": int(dp_parts[1].strip()) if dp_parts[1].strip() else 1,
            "records_per_hour": int(dp_parts[2].strip()) if dp_parts[2].strip() else 1,
            "name": dp_parts[3].strip(),
            "start_weekday": dp_parts[4].strip(),
            "start_date": dp_parts[5].strip(),
            "end_date": dp_parts[6].strip(),
        }
    else:
        info["data_periods"] = {"count": 1, "records_per_hour": 1,
                                "name": "", "start_weekday": "",
                                "start_date": "", "end_date": ""}
    return info


def iter_data_rows(filepath):
    """Yield (line_number, fields_list) for each data row (after 8 header lines).

    Uses generator to avoid loading entire file into memory.
    """
    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        for i in range(HEADER_LINE_COUNT):
            f.readline()  # skip header lines
        line_num = HEADER_LINE_COUNT
        for line in f:
            line_num += 1
            stripped = line.rstrip("\n\r")
            if not stripped:
                continue
            fields = stripped.split(",")
            yield line_num, fields


def parse_numeric(value_str, missing_val=None):
    """Parse a string to float, returning None if it's a missing value."""
    try:
        val = float(value_str)
        if missing_val is not None and val >= missing_val:
            return None
        return val
    except (ValueError, TypeError):
        return None


def time_matches(fields, month=None, day=None, hour=None,
                 start_md=None, end_md=None):
    """Check if a data row's time matches the given filters."""
    try:
        m = int(fields[1])
        d = int(fields[2])
        h = int(fields[3])
    except (ValueError, IndexError):
        return False

    if month is not None and m != month:
        return False
    if day is not None and d != day:
        return False
    if hour is not None and h != hour:
        return False
    if start_md is not None:
        sm, sd = start_md
        if (m, d) < (sm, sd):
            return False
    if end_md is not None:
        em, ed = end_md
        if (m, d) > (em, ed):
            return False
    return True


def parse_md(md_str):
    """Parse 'M/D' string to (month, day) tuple."""
    parts = md_str.strip().split("/")
    if len(parts) != 2:
        print(f"Error: Invalid date format '{md_str}'. Expected M/D (e.g. 6/15)")
        sys.exit(1)
    try:
        return int(parts[0]), int(parts[1])
    except ValueError:
        print(f"Error: Invalid date format '{md_str}'. Expected M/D (e.g. 6/15)")
        sys.exit(1)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_summary(args):
    """Display EPW file summary with location and climate statistics."""
    filepath = os.path.abspath(args.epw_path)
    if not os.path.exists(filepath):
        print(f"Error: File not found: {filepath}")
        sys.exit(1)

    info = parse_header(filepath)
    loc = info["location"]
    dp = info["data_periods"]

    # Collect statistics from data rows
    row_count = 0
    stats = {}
    for idx in KEY_STAT_FIELDS:
        stats[idx] = []
    temp_for_dd = []  # for degree days

    for _, fields in iter_data_rows(filepath):
        row_count += 1
        for idx in KEY_STAT_FIELDS:
            if idx < len(fields):
                finfo = EPW_FIELDS[idx]
                val = parse_numeric(fields[idx], finfo[3])
                if val is not None:
                    stats[idx].append(val)
        # Dry bulb for degree days
        if len(fields) > 6:
            db = parse_numeric(fields[6], 99.9)
            if db is not None:
                temp_for_dd.append(db)

    # Calculate HDD and CDD (base 18C)
    hdd18 = sum(max(0, 18.0 - t) / 24.0 for t in temp_for_dd)
    cdd18 = sum(max(0, t - 18.0) / 24.0 for t in temp_for_dd)

    # Radiation totals (Wh/m2 -> kWh/m2/year)
    rad_14 = sum(v for v in stats.get(14, []))  # Direct Normal
    rad_15 = sum(v for v in stats.get(15, []))  # Diffuse Horizontal

    # Output
    lat_dir = "N" if loc["latitude"] >= 0 else "S"
    lon_dir = "E" if loc["longitude"] >= 0 else "W"

    print("=== EPW File Summary ===")
    print(f"  File: {os.path.basename(filepath)}")
    print(f"  Location: {loc['city']}, {loc['state']}, {loc['country']}")
    print(f"  WMO: {loc['wmo']}")
    print(f"  Coordinates: {abs(loc['latitude']):.2f}{lat_dir}, "
          f"{abs(loc['longitude']):.2f}{lon_dir}")
    print(f"  Elevation: {loc['elevation']:.1f} m")
    print(f"  Time Zone: UTC{loc['timezone']:+.1f}")
    print(f"  Data Source: {loc['source']}")
    print(f"  Data Period: {dp['start_date']} - {dp['end_date']} "
          f"({row_count} hours)")
    print()

    print("--- Climate Statistics ---")
    for idx in KEY_STAT_FIELDS:
        finfo = EPW_FIELDS[idx]
        vals = stats.get(idx, [])
        if not vals:
            continue
        name = finfo[1]
        units = finfo[2]
        if idx in (14, 15):
            # Radiation: show total kWh/m2/year
            total = sum(vals) / 1000.0
            print(f"  {name + ':':<42s} total={total:>8.1f} kWh/m2/year")
        else:
            mn = min(vals)
            mx = max(vals)
            avg = mean(vals)
            print(f"  {name + ':':<42s} min={mn:>8.1f}  max={mx:>8.1f}"
                  f"  mean={avg:>8.1f}  {units}")

    print(f"  {'HDD18:':<42s} {hdd18:>8.0f}")
    print(f"  {'CDD18:':<42s} {cdd18:>8.0f}")
    print(f"  {'Data rows:':<42s} {row_count}")


def cmd_read(args):
    """Read a specific field from EPW data rows with optional time filters."""
    filepath = os.path.abspath(args.epw_path)
    if not os.path.exists(filepath):
        print(f"Error: File not found: {filepath}")
        sys.exit(1)

    field_idx, finfo = resolve_field(args.field)
    start_md = parse_md(args.start) if args.start else None
    end_md = parse_md(args.end) if args.end else None

    print(f"=== EPW Read: {finfo[1]} [{finfo[2]}] ===")
    print(f"  Field position: {field_idx + 1}")
    if finfo[3] is not None:
        print(f"  Missing value: >= {finfo[3]}")
    print()

    values = []
    rows_shown = 0
    max_show = 50

    for _, fields in iter_data_rows(filepath):
        if not time_matches(fields, args.month, args.day, args.hour,
                            start_md, end_md):
            continue
        if field_idx >= len(fields):
            continue

        raw_val = fields[field_idx]
        val = parse_numeric(raw_val, finfo[3])

        if rows_shown < max_show:
            try:
                m, d, h = int(fields[1]), int(fields[2]), int(fields[3])
                ts = f"{m:02d}/{d:02d} {h:02d}:00"
            except (ValueError, IndexError):
                ts = "??/?? ??:00"
            status = "" if val is not None else " [MISSING]"
            print(f"  {ts}  {raw_val}{status}")
            rows_shown += 1

        if val is not None:
            values.append(val)

    if rows_shown >= max_show:
        # Count remaining
        remaining = len(values) - max_show
        if remaining > 0:
            print(f"  ... and {remaining} more data points")

    print()
    if values:
        print("--- Statistics ---")
        print(f"  Count:   {len(values)}")
        print(f"  Min:     {min(values):.4f}")
        print(f"  Max:     {max(values):.4f}")
        print(f"  Mean:    {mean(values):.4f}")
        if len(values) > 1:
            print(f"  StdDev:  {stdev(values):.4f}")
    else:
        print("  No valid data points found.")


def cmd_write(args):
    """Write (modify) a specific field in EPW data rows."""
    filepath = os.path.abspath(args.epw_path)
    outpath = os.path.abspath(args.output)
    if not os.path.exists(filepath):
        print(f"Error: File not found: {filepath}")
        sys.exit(1)
    if os.path.abspath(filepath) == os.path.abspath(outpath):
        print("Error: Output path must be different from input path")
        sys.exit(1)

    field_idx, finfo = resolve_field(args.field)
    start_md = parse_md(args.start) if args.start else None
    end_md = parse_md(args.end) if args.end else None

    # Determine the new value
    try:
        new_value = args.value
        # Validate it's a reasonable value for numeric fields
        if field_idx not in (5, 27):  # skip text fields
            float(new_value)
    except ValueError:
        print(f"Error: Invalid value '{args.value}' for field {finfo[1]}")
        sys.exit(1)

    modified_count = 0
    total_data_rows = 0

    with open(filepath, "r", encoding="utf-8", errors="replace") as fin, \
         open(outpath, "w", encoding="utf-8", newline="") as fout:

        # Copy header lines
        for i in range(HEADER_LINE_COUNT):
            fout.write(fin.readline())

        # Process data lines
        for line in fin:
            stripped = line.rstrip("\n\r")
            if not stripped:
                fout.write(line)
                continue

            total_data_rows += 1
            fields = stripped.split(",")

            if (time_matches(fields, args.month, args.day, args.hour,
                             start_md, end_md) and field_idx < len(fields)):
                fields[field_idx] = new_value
                modified_count += 1

            fout.write(",".join(fields) + "\n")

    print(f"=== EPW Write Complete ===")
    print(f"  Field: {finfo[1]} (position {field_idx + 1})")
    print(f"  New value: {new_value}")
    print(f"  Rows modified: {modified_count} / {total_data_rows}")
    print(f"  Output: {outpath}")


def cmd_inject(args):
    """Inject data from a CSV file into an EPW file."""
    filepath = os.path.abspath(args.epw_path)
    csv_path = os.path.abspath(args.csv)
    outpath = os.path.abspath(args.output)

    if not os.path.exists(filepath):
        print(f"Error: File not found: {filepath}")
        sys.exit(1)
    if not os.path.exists(csv_path):
        print(f"Error: CSV file not found: {csv_path}")
        sys.exit(1)
    if os.path.abspath(filepath) == os.path.abspath(outpath):
        print("Error: Output path must be different from input path")
        sys.exit(1)

    # Parse mapping: "csv_col:epw_field,csv_col:epw_field"
    mappings = []
    for pair in args.mapping.split(","):
        parts = pair.strip().split(":")
        if len(parts) != 2:
            print(f"Error: Invalid mapping '{pair}'. Expected 'csv_col:epw_field'")
            sys.exit(1)
        csv_col = parts[0].strip()
        epw_idx, epw_finfo = resolve_field(parts[1].strip())
        mappings.append((csv_col, epw_idx, epw_finfo))

    # Read CSV data into a lookup dict keyed by (month, day, hour)
    csv_data = {}
    time_cols = None
    with open(csv_path, "r", encoding="utf-8", errors="replace") as cf:
        reader = csv.DictReader(cf)
        headers_lower = {h.lower().strip(): h for h in reader.fieldnames}

        # Detect time columns
        for month_key in ["month", "mon", "m"]:
            if month_key in headers_lower:
                time_cols = "mdy"
                month_col = headers_lower[month_key]
                break

        if time_cols is None:
            print("Error: CSV must contain Month/Day/Hour columns")
            sys.exit(1)

        day_col = None
        for dk in ["day", "d"]:
            if dk in headers_lower:
                day_col = headers_lower[dk]
                break
        if day_col is None:
            print("Error: CSV must contain a 'Day' column")
            sys.exit(1)

        hour_col = None
        for hk in ["hour", "hr", "h"]:
            if hk in headers_lower:
                hour_col = headers_lower[hk]
                break
        if hour_col is None:
            print("Error: CSV must contain an 'Hour' column")
            sys.exit(1)

        # Verify mapping columns exist in CSV
        for csv_col, _, _ in mappings:
            if csv_col not in reader.fieldnames:
                print(f"Error: CSV column '{csv_col}' not found. "
                      f"Available: {', '.join(reader.fieldnames)}")
                sys.exit(1)

        for row in reader:
            try:
                m = int(row[month_col])
                d = int(row[day_col])
                h = int(row[hour_col])
            except (ValueError, KeyError):
                continue
            csv_data[(m, d, h)] = row

    print(f"  CSV data loaded: {len(csv_data)} rows")

    # Process EPW file
    injected_count = 0
    total_data_rows = 0

    with open(filepath, "r", encoding="utf-8", errors="replace") as fin, \
         open(outpath, "w", encoding="utf-8", newline="") as fout:

        # Copy header lines
        for i in range(HEADER_LINE_COUNT):
            fout.write(fin.readline())

        # Process data lines
        for line in fin:
            stripped = line.rstrip("\n\r")
            if not stripped:
                fout.write(line)
                continue

            total_data_rows += 1
            fields = stripped.split(",")

            try:
                m = int(fields[1])
                d = int(fields[2])
                h = int(fields[3])
            except (ValueError, IndexError):
                fout.write(",".join(fields) + "\n")
                continue

            key = (m, d, h)
            if key in csv_data:
                row = csv_data[key]
                for csv_col, epw_idx, _ in mappings:
                    if csv_col in row and row[csv_col].strip():
                        fields[epw_idx] = row[csv_col].strip()
                injected_count += 1

            fout.write(",".join(fields) + "\n")

    print(f"=== EPW Inject Complete ===")
    print(f"  Source CSV: {os.path.basename(csv_path)}")
    print(f"  Mappings:")
    for csv_col, epw_idx, epw_finfo in mappings:
        print(f"    {csv_col} -> {epw_finfo[1]} (position {epw_idx + 1})")
    print(f"  Rows injected: {injected_count} / {total_data_rows}")
    print(f"  Output: {outpath}")


def cmd_validate(args):
    """Validate EPW file format and data quality."""
    filepath = os.path.abspath(args.epw_path)
    if not os.path.exists(filepath):
        print(f"Error: File not found: {filepath}")
        sys.exit(1)

    errors = []
    warnings = []

    # Check header
    info = parse_header(filepath)
    loc = info["location"]
    if not loc["city"] or loc["city"] == "Unknown":
        errors.append("Line 1: LOCATION header missing or malformed")
    if loc["latitude"] == 0.0 and loc["longitude"] == 0.0:
        warnings.append("Line 1: Latitude and longitude are both 0.0")

    dp = info["data_periods"]
    if dp["records_per_hour"] not in (1, 2, 4, 6):
        warnings.append(f"Line 8: Unusual records_per_hour = {dp['records_per_hour']}")

    # Check data rows
    row_count = 0
    missing_counts = {}
    range_violations = []
    field_count_errors = []
    prev_time = None

    for line_num, fields in iter_data_rows(filepath):
        row_count += 1

        # Field count check
        if len(fields) != 35:
            field_count_errors.append(
                f"Line {line_num}: Expected 35 fields, got {len(fields)}")
            if len(field_count_errors) <= 5:
                continue

        # Time continuity
        try:
            m, d, h = int(fields[1]), int(fields[2]), int(fields[3])
            curr_time = (m, d, h)
            if prev_time is not None:
                pm, pd, ph = prev_time
                expected_h = ph + 1
                if expected_h > 24:
                    expected_h = 1
                if h != expected_h and not (pm != m or pd != d):
                    warnings.append(
                        f"Line {line_num}: Time discontinuity "
                        f"{pm:02d}/{pd:02d} {ph:02d}:00 -> "
                        f"{m:02d}/{d:02d} {h:02d}:00")
            prev_time = curr_time
        except (ValueError, IndexError):
            errors.append(f"Line {line_num}: Cannot parse time fields")
            continue

        # Numeric range checks
        for fdef in EPW_FIELDS[6:]:  # skip time and flags fields
            idx = fdef[0]
            if idx >= len(fields):
                continue
            if idx in (27,):  # text field (weather codes)
                continue
            val = parse_numeric(fields[idx], None)
            if val is None:
                continue
            missing_val = fdef[3]
            if missing_val is not None and val >= missing_val:
                missing_counts[idx] = missing_counts.get(idx, 0) + 1
                continue
            min_val = fdef[4]
            max_val = fdef[5]
            if min_val is not None and val < min_val:
                range_violations.append(
                    f"Line {line_num}: {fdef[1]} = {val} < min {min_val}")
            if max_val is not None and val > max_val:
                range_violations.append(
                    f"Line {line_num}: {fdef[1]} = {val} > max {max_val}")

    # Expected row count
    expected = 8760
    if row_count == 8784:
        expected = 8784  # leap year
    if row_count != expected and row_count != 8760 and row_count != 8784:
        errors.append(
            f"Data rows: {row_count} (expected 8760 or 8784)")

    # Output
    print("=== EPW Validation Report ===")
    print(f"  File: {os.path.basename(filepath)}")
    print(f"  Location: {loc['city']}, {loc['country']}")
    print(f"  Data rows: {row_count}")
    print()

    if field_count_errors:
        print(f"--- Field Count Errors ({len(field_count_errors)}) ---")
        for e in field_count_errors[:10]:
            print(f"  {e}")
        if len(field_count_errors) > 10:
            print(f"  ... and {len(field_count_errors) - 10} more")
        print()

    if errors:
        print(f"--- Errors ({len(errors)}) ---")
        for e in errors:
            print(f"  {e}")
        print()

    if range_violations:
        print(f"--- Range Violations ({len(range_violations)}) ---")
        for rv in range_violations[:20]:
            print(f"  {rv}")
        if len(range_violations) > 20:
            print(f"  ... and {len(range_violations) - 20} more")
        print()

    if missing_counts:
        print("--- Missing Data Summary ---")
        for idx in sorted(missing_counts.keys()):
            fdef = EPW_FIELDS[idx]
            cnt = missing_counts[idx]
            pct = cnt / row_count * 100 if row_count > 0 else 0
            print(f"  {fdef[1]:<42s} {cnt:>5d} ({pct:.1f}%)")
        print()

    if warnings:
        print(f"--- Warnings ({len(warnings)}) ---")
        for w in warnings[:20]:
            print(f"  {w}")
        if len(warnings) > 20:
            print(f"  ... and {len(warnings) - 20} more")
        print()

    total_issues = len(errors) + len(field_count_errors)
    total_warnings = len(warnings) + len(range_violations)
    print(f"  Total: {total_issues} errors, {total_warnings} warnings, "
          f"{sum(missing_counts.values())} missing values")

    if total_issues > 0:
        print("  Status: INVALID")
        sys.exit(1)
    else:
        print("  Status: VALID")


def cmd_stats(args):
    """Display statistical summary of EPW data."""
    filepath = os.path.abspath(args.epw_path)
    if not os.path.exists(filepath):
        print(f"Error: File not found: {filepath}")
        sys.exit(1)

    info = parse_header(filepath)
    loc = info["location"]

    # Determine which fields to analyze
    if args.field:
        field_idx, finfo = resolve_field(args.field)
        target_fields = [field_idx]
    else:
        target_fields = KEY_STAT_FIELDS

    if args.monthly:
        # Monthly statistics
        monthly_data = {m: {idx: [] for idx in target_fields} for m in range(1, 13)}

        for _, fields in iter_data_rows(filepath):
            try:
                m = int(fields[1])
            except (ValueError, IndexError):
                continue
            if m < 1 or m > 12:
                continue
            for idx in target_fields:
                if idx < len(fields):
                    fdef = EPW_FIELDS[idx]
                    val = parse_numeric(fields[idx], fdef[3])
                    if val is not None:
                        monthly_data[m][idx].append(val)

        month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                       "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

        print(f"=== EPW Monthly Statistics: {loc['city']} ===")
        print()

        for idx in target_fields:
            fdef = EPW_FIELDS[idx]
            print(f"--- {fdef[1]} [{fdef[2]}] ---")
            print(f"  {'Month':<6s} {'Count':>6s} {'Min':>8s} {'Max':>8s} "
                  f"{'Mean':>8s} {'StdDev':>8s}")
            print(f"  {'-'*46}")
            for m in range(1, 13):
                vals = monthly_data[m][idx]
                if not vals:
                    print(f"  {month_names[m-1]:<6s} {'N/A':>6s}")
                    continue
                mn = min(vals)
                mx = max(vals)
                avg = mean(vals)
                sd = stdev(vals) if len(vals) > 1 else 0.0
                print(f"  {month_names[m-1]:<6s} {len(vals):>6d} {mn:>8.1f} "
                      f"{mx:>8.1f} {avg:>8.1f} {sd:>8.1f}")
            print()

    else:
        # Annual statistics
        annual_data = {idx: [] for idx in target_fields}

        for _, fields in iter_data_rows(filepath):
            for idx in target_fields:
                if idx < len(fields):
                    fdef = EPW_FIELDS[idx]
                    val = parse_numeric(fields[idx], fdef[3])
                    if val is not None:
                        annual_data[idx].append(val)

        print(f"=== EPW Annual Statistics: {loc['city']} ===")
        print()
        print(f"  {'Field':<42s} {'Count':>6s} {'Min':>8s} {'Max':>8s} "
              f"{'Mean':>8s} {'StdDev':>8s} {'Units':<10s}")
        print(f"  {'-'*84}")

        for idx in target_fields:
            fdef = EPW_FIELDS[idx]
            vals = annual_data[idx]
            if not vals:
                print(f"  {fdef[1]:<42s} {'N/A':>6s}")
                continue
            mn = min(vals)
            mx = max(vals)
            avg = mean(vals)
            sd = stdev(vals) if len(vals) > 1 else 0.0
            print(f"  {fdef[1]:<42s} {len(vals):>6d} {mn:>8.1f} {mx:>8.1f} "
                  f"{avg:>8.1f} {sd:>8.1f} {fdef[2]:<10s}")


def cmd_create(args):
    """Create a new EPW file from CSV data and location metadata."""
    csv_path = os.path.abspath(args.csv)
    outpath = os.path.abspath(args.output)

    if not os.path.exists(csv_path):
        print(f"Error: CSV file not found: {csv_path}")
        sys.exit(1)

    location = _parse_location(args.location)

    data_rows = {}
    with open(csv_path, "r", encoding="utf-8-sig", errors="replace") as cf:
        reader = csv.DictReader(cf)
        if not reader.fieldnames:
            print("Error: CSV has no header row")
            sys.exit(1)

        headers = [h.replace("\ufeff", "").strip() for h in reader.fieldnames]
        headers_norm = {_normalize_name(h): h for h in headers}

        month_col = headers_norm.get("month") or headers_norm.get("mon") or headers_norm.get("m")
        day_col = headers_norm.get("day") or headers_norm.get("d")
        hour_col = headers_norm.get("hour") or headers_norm.get("hr") or headers_norm.get("h")
        year_col = headers_norm.get("year") or headers_norm.get("yr") or headers_norm.get("yyyy")
        minute_col = headers_norm.get("minute") or headers_norm.get("min")

        if not month_col or not day_col or not hour_col:
            print("Error: CSV must include Month/Day/Hour columns")
            print(f"  Found columns: {', '.join(headers)}")
            sys.exit(1)

        resolved_headers = {}
        for h in headers:
            idx = _resolve_header_to_field_index(h)
            if idx is not None:
                resolved_headers[h] = idx

        for row in reader:
            try:
                month = int(row.get(month_col, "").strip())
                day = int(row.get(day_col, "").strip())
                hour = int(row.get(hour_col, "").strip())
            except ValueError:
                continue

            try:
                year = int(row.get(year_col, "").strip()) if year_col and row.get(year_col, "").strip() else 2002
            except ValueError:
                year = 2002
            try:
                minute = int(row.get(minute_col, "").strip()) if minute_col and row.get(minute_col, "").strip() else 60
            except ValueError:
                minute = 60

            fields = _build_default_row(year, month, day, hour, minute)
            for header, idx in resolved_headers.items():
                if idx in (0, 1, 2, 3, 4):
                    continue
                value = row.get(header, "")
                if value is None:
                    continue
                value = value.strip()
                if value:
                    fields[idx] = value

            data_rows[(month, day, hour)] = fields

    if not data_rows:
        print("Error: No valid data rows found in CSV")
        sys.exit(1)

    sorted_keys = sorted(data_rows.keys())

    with open(outpath, "w", encoding="utf-8", newline="") as f:
        f.write(
            f"LOCATION,{location[0]},{location[1]},{location[2]},{location[3]},"
            f"{location[4]},{location[5]},{location[6]},{location[7]},{location[8]}\n"
        )
        f.write("DESIGN CONDITIONS,0\n")
        f.write("TYPICAL/EXTREME PERIODS,0\n")
        f.write("GROUND TEMPERATURES,0\n")
        f.write("HOLIDAYS/DAYLIGHT SAVING,No,0,0,0\n")
        f.write("COMMENTS 1,Generated by epw_helper create\n")
        f.write(f"COMMENTS 2,Source CSV: {os.path.basename(csv_path)}\n")
        f.write("DATA PERIODS,1,1,Data,Sunday, 1/ 1,12/31\n")

        for key in sorted_keys:
            row = data_rows[key]
            if len(row) < 35:
                row = row + [""] * (35 - len(row))
            elif len(row) > 35:
                row = row[:35]
            f.write(",".join(row) + "\n")

    count = len(sorted_keys)
    print("=== EPW Create Complete ===")
    print(f"  Source CSV: {os.path.basename(csv_path)}")
    print(f"  Output:     {outpath}")
    print(f"  Data rows:  {count}")
    if count not in (8760, 8784):
        print("  Warning: row count is not 8760/8784; file may fail strict EPW validation.")


def _collect_compare_metrics(epw_path):
    """Collect compact EPW metrics for side-by-side compare."""
    info = parse_header(epw_path)
    stats = {idx: [] for idx in KEY_STAT_FIELDS}
    dry_bulb = []
    rows = 0

    for _, fields in iter_data_rows(epw_path):
        rows += 1
        for idx in KEY_STAT_FIELDS:
            if idx < len(fields):
                fdef = EPW_FIELDS[idx]
                value = parse_numeric(fields[idx], fdef[3])
                if value is not None:
                    stats[idx].append(value)
        if len(fields) > 6:
            value = parse_numeric(fields[6], 99.9)
            if value is not None:
                dry_bulb.append(value)

    means = {}
    for idx in KEY_STAT_FIELDS:
        values = stats.get(idx, [])
        means[idx] = mean(values) if values else None

    hdd18 = sum(max(0, 18.0 - t) / 24.0 for t in dry_bulb)
    cdd18 = sum(max(0, t - 18.0) / 24.0 for t in dry_bulb)

    return {
        "info": info,
        "rows": rows,
        "means": means,
        "hdd18": hdd18,
        "cdd18": cdd18,
    }


def cmd_compare(args):
    """Compare two EPW files (location + key climate stats)."""
    epw_a = os.path.abspath(args.epw_a)
    epw_b = os.path.abspath(args.epw_b)

    if not os.path.exists(epw_a):
        print(f"Error: File not found: {epw_a}")
        sys.exit(1)
    if not os.path.exists(epw_b):
        print(f"Error: File not found: {epw_b}")
        sys.exit(1)

    a = _collect_compare_metrics(epw_a)
    b = _collect_compare_metrics(epw_b)

    loc_a = a["info"]["location"]
    loc_b = b["info"]["location"]

    print("=== EPW Compare ===")
    print(f"  A: {os.path.basename(epw_a)}")
    print(f"  B: {os.path.basename(epw_b)}")
    print()

    print("--- Location ---")
    loc_fields = [
        ("City", loc_a["city"], loc_b["city"]),
        ("State", loc_a["state"], loc_b["state"]),
        ("Country", loc_a["country"], loc_b["country"]),
        ("Source", loc_a["source"], loc_b["source"]),
        ("WMO", loc_a["wmo"], loc_b["wmo"]),
        ("Latitude", loc_a["latitude"], loc_b["latitude"]),
        ("Longitude", loc_a["longitude"], loc_b["longitude"]),
        ("Time Zone", loc_a["timezone"], loc_b["timezone"]),
        ("Elevation", loc_a["elevation"], loc_b["elevation"]),
    ]
    for name, va, vb in loc_fields:
        same = "OK" if str(va) == str(vb) else "DIFF"
        print(f"  {name:<10s} A={va} | B={vb} [{same}]")

    print()
    print("--- Climate Means (B - A) ---")
    compare_fields = [6, 7, 8, 9, 14, 15, 20, 21]
    for idx in compare_fields:
        name = EPW_FIELDS[idx][1]
        units = EPW_FIELDS[idx][2]
        va = a["means"].get(idx)
        vb = b["means"].get(idx)
        if va is None or vb is None:
            print(f"  {name:<42s} A=N/A  B=N/A  Delta=N/A")
            continue
        print(f"  {name:<42s} A={va:>8.2f}  B={vb:>8.2f}  Delta={vb - va:>8.2f} {units}")

    print(f"  {'HDD18':<42s} A={a['hdd18']:>8.1f}  B={b['hdd18']:>8.1f}  Delta={b['hdd18'] - a['hdd18']:>8.1f}")
    print(f"  {'CDD18':<42s} A={a['cdd18']:>8.1f}  B={b['cdd18']:>8.1f}  Delta={b['cdd18'] - a['cdd18']:>8.1f}")
    print(f"  {'Data rows':<42s} A={a['rows']:>8d}  B={b['rows']:>8d}  Delta={b['rows'] - a['rows']:>8d}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="EnergyPlus EPW weather file helper tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Field reference: AuxiliaryPrograms.pdf Section 2.9"
    )
    subparsers = parser.add_subparsers(dest="command")

    # summary
    p_sum = subparsers.add_parser("summary", help="EPW file summary")
    p_sum.add_argument("epw_path", help="Path to EPW file")

    # read
    p_read = subparsers.add_parser("read", help="Read field data")
    p_read.add_argument("epw_path", help="Path to EPW file")
    p_read.add_argument("--field", required=True,
                        help="Field name or 1-based index (e.g. 'Dry Bulb' or 7)")
    p_read.add_argument("--month", type=int, help="Filter by month (1-12)")
    p_read.add_argument("--day", type=int, help="Filter by day (1-31)")
    p_read.add_argument("--hour", type=int, help="Filter by hour (1-24)")
    p_read.add_argument("--start", help="Start date M/D (e.g. 6/1)")
    p_read.add_argument("--end", help="End date M/D (e.g. 6/30)")

    # write
    p_write = subparsers.add_parser("write", help="Modify field values")
    p_write.add_argument("epw_path", help="Path to EPW file")
    p_write.add_argument("--output", required=True, help="Output EPW path")
    p_write.add_argument("--field", required=True,
                         help="Field name or 1-based index")
    p_write.add_argument("--value", required=True, help="New value to set")
    p_write.add_argument("--month", type=int, help="Filter by month")
    p_write.add_argument("--day", type=int, help="Filter by day")
    p_write.add_argument("--hour", type=int, help="Filter by hour")
    p_write.add_argument("--start", help="Start date M/D")
    p_write.add_argument("--end", help="End date M/D")

    # inject
    p_inj = subparsers.add_parser("inject", help="Inject CSV data into EPW")
    p_inj.add_argument("epw_path", help="Path to EPW file")
    p_inj.add_argument("--csv", required=True, help="Path to CSV data file")
    p_inj.add_argument("--output", required=True, help="Output EPW path")
    p_inj.add_argument("--mapping", required=True,
                       help="Column mapping: 'csv_col:epw_field,...'")

    # validate
    p_val = subparsers.add_parser("validate", help="Validate EPW format")
    p_val.add_argument("epw_path", help="Path to EPW file")

    # stats
    p_stat = subparsers.add_parser("stats", help="Statistical summary")
    p_stat.add_argument("epw_path", help="Path to EPW file")
    p_stat.add_argument("--monthly", action="store_true",
                        help="Show monthly breakdown")
    p_stat.add_argument("--field", help="Specific field name or index")

    # create
    p_create = subparsers.add_parser("create", help="Create EPW from CSV")
    p_create.add_argument("--location", required=True,
                          help="City,State,Country,Source,WMO,Lat,Lon,TZ,Elev")
    p_create.add_argument("--csv", required=True,
                          help="Path to source CSV with weather data")
    p_create.add_argument("--output", required=True,
                          help="Output EPW path")

    # compare
    p_cmp = subparsers.add_parser("compare", help="Compare two EPW files")
    p_cmp.add_argument("epw_a", help="First EPW file")
    p_cmp.add_argument("epw_b", help="Second EPW file")

    args = parser.parse_args()
    if args.command is None:
        parser.print_help()
        sys.exit(1)

    commands = {
        "summary": cmd_summary,
        "read": cmd_read,
        "write": cmd_write,
        "inject": cmd_inject,
        "validate": cmd_validate,
        "stats": cmd_stats,
        "create": cmd_create,
        "compare": cmd_compare,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
