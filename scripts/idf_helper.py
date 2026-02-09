#!/usr/bin/env python
"""EnergyPlus IDF file helper tool.

Provides parsing, validation, and structured operations on IDF files.

Usage:
    python idf_helper.py validate <idf_path>
    python idf_helper.py list-objects <idf_path>
    python idf_helper.py get-object <idf_path> --type <ObjectType> [--name <name>]
    python idf_helper.py summary <idf_path>
    python idf_helper.py add-output <idf_path> --variable <name> [--key <key>] [--frequency <freq>]
    python idf_helper.py check-hvactemplate <idf_path>
"""

import argparse
import os
import re
import sys
from collections import OrderedDict


def parse_idf(filepath):
    """Parse an IDF file into a list of (object_type, fields, raw_text) tuples.

    Returns a list of dicts with keys:
        - type: object type name (str)
        - fields: list of field values (str)
        - raw: raw text of the object (str)
        - line_start: starting line number (int)
        - line_end: ending line number (int)
    """
    if not os.path.exists(filepath):
        print(f"Error: IDF file not found: {filepath}")
        sys.exit(1)

    objects = []
    current_lines = []
    current_start = 0
    in_object = False

    with open(filepath, "r", encoding="utf-8", errors="replace") as f:
        for line_num, line in enumerate(f, 1):
            # Remove inline comments (but preserve the line for raw text)
            stripped = line.strip()

            # Skip pure comment lines and empty lines when not in object
            if not in_object:
                if not stripped or stripped.startswith("!"):
                    continue

                # Check if this starts a new object
                # Object lines have no leading whitespace and contain a comma or semicolon
                if not line.startswith(" ") and not line.startswith("\t"):
                    # Remove comment portion
                    code_part = stripped.split("!")[0].strip()
                    if code_part and ("," in code_part or ";" in code_part):
                        in_object = True
                        current_lines = [line]
                        current_start = line_num
                        if ";" in code_part:
                            # Single-line object
                            obj = _finalize_object(current_lines, current_start, line_num)
                            if obj:
                                objects.append(obj)
                            in_object = False
                continue

            # We're inside an object
            current_lines.append(line)

            # Check if this line terminates the object
            code_part = stripped.split("!")[0].strip()
            if ";" in code_part:
                obj = _finalize_object(current_lines, current_start, line_num)
                if obj:
                    objects.append(obj)
                in_object = False

    # Handle unclosed object at end of file
    if in_object and current_lines:
        obj = _finalize_object(current_lines, current_start, -1)
        if obj:
            obj["error"] = "Unclosed object (missing semicolon)"
            objects.append(obj)

    return objects


def _finalize_object(lines, start_line, end_line):
    """Convert accumulated lines into an object dict."""
    raw = "".join(lines)

    # Extract all content, removing comments
    content_parts = []
    for line in lines:
        # Remove comment portion
        code = line.split("!")[0]
        content_parts.append(code)

    content = "".join(content_parts)

    # Split by comma and semicolon to get fields
    # Replace semicolon with comma for uniform splitting
    content = content.replace(";", ",")
    parts = [p.strip() for p in content.split(",")]

    # Remove empty trailing parts
    while parts and not parts[-1]:
        parts.pop()

    if not parts:
        return None

    obj_type = parts[0]
    field_values = parts[1:] if len(parts) > 1 else []

    return {
        "type": obj_type,
        "fields": field_values,
        "raw": raw,
        "line_start": start_line,
        "line_end": end_line,
    }


def cmd_validate(args):
    """Validate an IDF file for common issues."""
    filepath = args.idf_path
    objects = parse_idf(filepath)

    errors = []
    warnings = []

    # Check Version
    versions = [o for o in objects if o["type"].lower() == "version"]
    if not versions:
        errors.append("Missing 'Version' object")
    elif versions:
        ver = versions[0]["fields"][0] if versions[0]["fields"] else ""
        if not ver.startswith("23.2"):
            errors.append(
                f"Version mismatch: IDF has '{ver}', expected '23.2' "
                f"(line {versions[0]['line_start']})"
            )

    # Check for unclosed objects
    for o in objects:
        if o.get("error"):
            errors.append(
                f"Unclosed object '{o['type']}' starting at line {o['line_start']}: "
                f"{o['error']}"
            )

    # Build name indexes for reference checking
    zone_names = set()
    construction_names = set()
    schedule_names = set()
    material_names = set()

    for o in objects:
        otype = o["type"]
        if otype == "Zone" and o["fields"]:
            zone_names.add(o["fields"][0])
        elif otype == "Construction" and o["fields"]:
            construction_names.add(o["fields"][0])
        elif otype.startswith("Schedule") and o["fields"]:
            schedule_names.add(o["fields"][0])
        elif otype.startswith("Material") and o["fields"]:
            material_names.add(o["fields"][0])
        elif otype.startswith("WindowMaterial") and o["fields"]:
            material_names.add(o["fields"][0])

    # Check surface references
    # BuildingSurface:Detailed fields: [0]=Name, [1]=Surface Type, [2]=Construction, [3]=Zone, [4]=Space
    for o in objects:
        otype = o["type"]
        if otype == "BuildingSurface:Detailed" and len(o["fields"]) >= 4:
            construction = o["fields"][2] if len(o["fields"]) > 2 else ""
            zone = o["fields"][3] if len(o["fields"]) > 3 else ""
            if construction and construction not in construction_names:
                warnings.append(
                    f"Surface '{o['fields'][0]}' references unknown construction "
                    f"'{construction}' (line {o['line_start']})"
                )
            if zone and zone not in zone_names:
                warnings.append(
                    f"Surface '{o['fields'][0]}' references unknown zone "
                    f"'{zone}' (line {o['line_start']})"
                )

    # Check Construction material references
    for o in objects:
        if o["type"] == "Construction" and len(o["fields"]) > 1:
            for layer in o["fields"][1:]:
                if layer and layer not in material_names:
                    warnings.append(
                        f"Construction '{o['fields'][0]}' references unknown material "
                        f"'{layer}' (line {o['line_start']})"
                    )

    # Check for duplicate names within same type
    type_names = {}
    for o in objects:
        if o["fields"]:
            key = (o["type"], o["fields"][0])
            if key in type_names:
                warnings.append(
                    f"Duplicate {o['type']} name '{o['fields'][0]}' "
                    f"at lines {type_names[key]} and {o['line_start']}"
                )
            else:
                type_names[key] = o["line_start"]

    # Print results
    print(f"=== IDF Validation: {os.path.basename(filepath)} ===\n")

    if errors:
        print(f"ERRORS ({len(errors)}):")
        for e in errors:
            print(f"  [ERROR] {e}")
        print()

    if warnings:
        print(f"WARNINGS ({len(warnings)}):")
        for w in warnings[:30]:
            print(f"  [WARN]  {w}")
        if len(warnings) > 30:
            print(f"  ... and {len(warnings) - 30} more warnings")
        print()

    if not errors and not warnings:
        print("Validation PASSED - No errors or warnings found.")
    elif not errors:
        print(f"Validation PASSED with {len(warnings)} warning(s).")
    else:
        print(f"Validation FAILED: {len(errors)} error(s), {len(warnings)} warning(s).")

    return len(errors)


def cmd_list_objects(args):
    """List all object types and their counts in the IDF."""
    objects = parse_idf(args.idf_path)

    counts = OrderedDict()
    for o in objects:
        counts[o["type"]] = counts.get(o["type"], 0) + 1

    print(f"=== IDF Object Summary: {os.path.basename(args.idf_path)} ===\n")
    print(f"  {'Object Type':<50s} {'Count':>6s}")
    print("  " + "-" * 58)

    total = 0
    for otype, count in sorted(counts.items()):
        print(f"  {otype:<50s} {count:>6d}")
        total += count

    print("  " + "-" * 58)
    print(f"  {'TOTAL':<50s} {total:>6d}")
    print(f"\n  {len(counts)} distinct object types")


def cmd_get_object(args):
    """Extract specific object(s) from the IDF."""
    objects = parse_idf(args.idf_path)

    target_type = args.type
    target_name = args.name

    matches = []
    for o in objects:
        if o["type"].lower() == target_type.lower():
            if target_name:
                if o["fields"] and o["fields"][0].lower() == target_name.lower():
                    matches.append(o)
            else:
                matches.append(o)

    print(f"=== {target_type} objects in {os.path.basename(args.idf_path)} ===\n")

    if not matches:
        print(f"  No '{target_type}' objects found.")
        if target_name:
            print(f"  (filtered by name: '{target_name}')")
        return

    print(f"  Found {len(matches)} match(es):\n")

    for i, m in enumerate(matches):
        print(f"--- [{i+1}] Lines {m['line_start']}-{m['line_end']} ---")
        print(m["raw"])


def cmd_summary(args):
    """Print a high-level summary of the IDF."""
    objects = parse_idf(args.idf_path)

    # Extract key info
    version = ""
    building_name = ""
    location = ""
    num_zones = 0
    num_surfaces = 0
    num_fenestrations = 0
    hvac_types = set()
    run_period = ""
    has_sqlite = False
    has_summary_reports = False
    output_vars = 0

    for o in objects:
        otype = o["type"]
        fields = o["fields"]

        if otype == "Version" and fields:
            version = fields[0]
        elif otype == "Building" and fields:
            building_name = fields[0]
        elif otype == "Site:Location" and fields:
            location = fields[0]
        elif otype == "Zone":
            num_zones += 1
        elif otype == "BuildingSurface:Detailed":
            num_surfaces += 1
        elif otype == "FenestrationSurface:Detailed":
            num_fenestrations += 1
        elif otype.startswith("HVACTemplate:"):
            hvac_types.add(otype)
        elif otype == "RunPeriod" and fields:
            if len(fields) >= 5:
                run_period = (
                    f"{fields[1]}/{fields[2]} - {fields[3]}/{fields[4]}"
                )
        elif otype == "Output:SQLite":
            has_sqlite = True
        elif otype == "Output:Table:SummaryReports":
            has_summary_reports = True
        elif otype == "Output:Variable":
            output_vars += 1

    # Count object types
    type_counts = {}
    for o in objects:
        type_counts[o["type"]] = type_counts.get(o["type"], 0) + 1

    print(f"=== IDF Summary: {os.path.basename(args.idf_path)} ===\n")
    print(f"  Version:              {version}")
    print(f"  Building:             {building_name}")
    print(f"  Location:             {location}")
    print(f"  Run Period:           {run_period or 'Not specified'}")
    print(f"  Zones:                {num_zones}")
    print(f"  Building Surfaces:    {num_surfaces}")
    print(f"  Fenestration Surfaces:{num_fenestrations}")
    print(f"  Total Objects:        {sum(type_counts.values())}")
    print(f"  Distinct Types:       {len(type_counts)}")
    print()

    if hvac_types:
        print("  HVAC Template Objects:")
        for ht in sorted(hvac_types):
            print(f"    - {ht} ({type_counts.get(ht, 0)})")
        print("  WARNING: HVACTemplate objects detected. Use --expand-objects (-x) flag when running simulation.")
    else:
        print("  HVAC: No HVACTemplate objects (detailed HVAC or none)")

    print()
    print("  Output Configuration:")
    print(f"    SQLite output:      {'Yes' if has_sqlite else 'No'}")
    print(f"    Summary reports:    {'Yes' if has_summary_reports else 'No'}")
    print(f"    Output variables:   {output_vars}")


def cmd_add_output(args):
    """Append an Output:Variable object to the IDF."""
    filepath = args.idf_path

    if not os.path.exists(filepath):
        print(f"Error: IDF file not found: {filepath}")
        sys.exit(1)

    key_value = args.key if args.key else "*"
    frequency = args.frequency if args.frequency else "Hourly"

    valid_frequencies = ["Timestep", "Hourly", "Daily", "Monthly", "RunPeriod",
                         "Environment", "Annual"]
    if frequency not in valid_frequencies:
        print(f"Error: Invalid frequency '{frequency}'. "
              f"Valid: {', '.join(valid_frequencies)}")
        sys.exit(1)

    output_line = (
        f"\n\nOutput:Variable,\n"
        f"    {key_value},                     !- Key Value\n"
        f"    {args.variable},  !- Variable Name\n"
        f"    {frequency};                     !- Reporting Frequency\n"
    )

    with open(filepath, "a", encoding="utf-8") as f:
        f.write(output_line)

    print(f"Added Output:Variable to {os.path.basename(filepath)}:")
    print(f"  Key: {key_value}")
    print(f"  Variable: {args.variable}")
    print(f"  Frequency: {frequency}")


def cmd_check_hvactemplate(args):
    """Check for HVACTemplate objects in the IDF."""
    objects = parse_idf(args.idf_path)

    templates = [o for o in objects if o["type"].startswith("HVACTemplate:")]

    print(f"=== HVACTemplate Check: {os.path.basename(args.idf_path)} ===\n")

    if not templates:
        print("  No HVACTemplate objects found.")
        print("  The -x (--expand-objects) flag is NOT required.")
        return

    print(f"  Found {len(templates)} HVACTemplate object(s):\n")

    type_counts = {}
    for t in templates:
        type_counts[t["type"]] = type_counts.get(t["type"], 0) + 1
        name = t["fields"][0] if t["fields"] else "(unnamed)"
        print(f"    Line {t['line_start']:>5d}: {t['type']}  ->  {name}")

    print(f"\n  Summary:")
    for ttype, count in sorted(type_counts.items()):
        print(f"    {ttype}: {count}")

    print(f"\n  WARNING: The -x (--expand-objects) flag is REQUIRED when running simulation.")
    print(f"  Use: python run_simulation.py --idf <file> --expand-objects ...")


def main():
    parser = argparse.ArgumentParser(
        description="EnergyPlus IDF Helper Tool"
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # validate
    p_validate = subparsers.add_parser("validate", help="Validate IDF file")
    p_validate.add_argument("idf_path", help="Path to IDF file")

    # list-objects
    p_list = subparsers.add_parser("list-objects", help="List object types and counts")
    p_list.add_argument("idf_path", help="Path to IDF file")

    # get-object
    p_get = subparsers.add_parser("get-object", help="Extract specific objects")
    p_get.add_argument("idf_path", help="Path to IDF file")
    p_get.add_argument("--type", required=True, help="Object type name")
    p_get.add_argument("--name", help="Object name to filter by")

    # summary
    p_summary = subparsers.add_parser("summary", help="Show IDF summary")
    p_summary.add_argument("idf_path", help="Path to IDF file")

    # add-output
    p_add = subparsers.add_parser("add-output", help="Add Output:Variable to IDF")
    p_add.add_argument("idf_path", help="Path to IDF file")
    p_add.add_argument("--variable", required=True, help="Variable name")
    p_add.add_argument("--key", help="Key value (default: *)")
    p_add.add_argument("--frequency", help="Reporting frequency (default: Hourly)")

    # check-hvactemplate
    p_hvac = subparsers.add_parser(
        "check-hvactemplate", help="Check for HVACTemplate objects"
    )
    p_hvac.add_argument("idf_path", help="Path to IDF file")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        sys.exit(1)

    commands = {
        "validate": cmd_validate,
        "list-objects": cmd_list_objects,
        "get-object": cmd_get_object,
        "summary": cmd_summary,
        "add-output": cmd_add_output,
        "check-hvactemplate": cmd_check_hvactemplate,
    }

    commands[args.command](args)


if __name__ == "__main__":
    main()
