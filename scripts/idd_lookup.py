#!/usr/bin/env python
"""EnergyPlus IDD (Input Data Dictionary) lookup tool.

Queries the Energy+.idd file for object type definitions without loading
the entire file into memory. Streams line-by-line for efficiency.

Usage:
    python idd_lookup.py "ObjectType"              # Full object definition
    python idd_lookup.py --fields "ObjectType"      # Condensed field table
    python idd_lookup.py --list-objects              # List all object types
    python idd_lookup.py --search "keyword"          # Search object names
    python idd_lookup.py --check-env                 # Discovery diagnostics only
    python idd_lookup.py --doctor                    # Alias for --check-env
"""

import argparse
import glob
import os
import re
import shutil
import sys


def _version_key(path):
    """Extract semantic-ish version tuple from an EnergyPlus install path."""
    match = re.search(
        r"energyplus(?:v|-)?(\d+)(?:[._-](\d+))?(?:[._-](\d+))?",
        path.replace("\\", "/").lower(),
    )
    if not match:
        return (0, 0, 0)
    return tuple(int(match.group(i) or 0) for i in (1, 2, 3))


def _pick_best(candidates):
    """Pick the newest-looking candidate based on version in path."""
    valid = [c for c in candidates if c and os.path.isfile(c)]
    if not valid:
        return None
    return max(valid, key=lambda p: (_version_key(p), p.lower()))


def _windows_drive_roots():
    """Return existing Windows drive roots like 'C:' and 'D:'."""
    roots = []
    for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
        root = f"{letter}:\\"
        if os.path.isdir(root):
            roots.append(root.rstrip("\\"))
    return roots


def _common_idd_candidates():
    """Return common EnergyPlus IDD paths by platform."""
    if os.name == "nt":
        patterns = []
        for root in _windows_drive_roots():
            patterns.extend([
                f"{root}\\EnergyPlus*\\Energy+.idd",
                f"{root}\\Program Files\\EnergyPlus*\\Energy+.idd",
                f"{root}\\Program Files (x86)\\EnergyPlus*\\Energy+.idd",
            ])
    else:
        patterns = [
            "/usr/local/EnergyPlus-*/Energy+.idd",
            "/opt/EnergyPlus-*/Energy+.idd",
            "/Applications/EnergyPlus-*/Energy+.idd",
        ]
    candidates = []
    for pattern in patterns:
        candidates.extend(glob.glob(pattern))
    return candidates


def _normalize_path(path):
    """Normalize user input paths consistently."""
    return os.path.abspath(os.path.expanduser(path))


def _append_attempt(attempts, source, value, ok):
    """Record one discovery attempt in a consistent format."""
    attempts.append({
        "source": source,
        "value": value if value else "(not set)",
        "ok": bool(ok),
    })


def _discover_idd(cli_path=None):
    """Discover Energy+.idd with trace metadata."""
    attempts = []

    if cli_path:
        candidate = _normalize_path(cli_path)
        ok = os.path.isfile(candidate)
        _append_attempt(attempts, "CLI --idd", candidate, ok)
        return {"path": candidate if ok else None, "source": "CLI --idd" if ok else None, "attempts": attempts}

    env = os.environ.get("ENERGYPLUS_IDD")
    if env:
        candidate = _normalize_path(env)
        ok = os.path.isfile(candidate)
        _append_attempt(attempts, "ENV ENERGYPLUS_IDD", candidate, ok)
        if ok:
            return {"path": candidate, "source": "ENV ENERGYPLUS_IDD", "attempts": attempts}
    else:
        _append_attempt(attempts, "ENV ENERGYPLUS_IDD", None, False)

    home = os.environ.get("ENERGYPLUS_HOME") or os.environ.get("EPLUS_HOME")
    if home:
        candidate = _normalize_path(os.path.join(home, "Energy+.idd"))
        ok = os.path.isfile(candidate)
        _append_attempt(attempts, "ENV ENERGYPLUS_HOME/EPLUS_HOME", candidate, ok)
        if ok:
            return {
                "path": candidate,
                "source": "ENV ENERGYPLUS_HOME/EPLUS_HOME",
                "attempts": attempts,
            }
    else:
        _append_attempt(attempts, "ENV ENERGYPLUS_HOME/EPLUS_HOME", None, False)

    exe_env = os.environ.get("ENERGYPLUS_EXE")
    exe = exe_env if (exe_env and os.path.isfile(exe_env)) else _pick_best(
        [shutil.which("energyplus"), shutil.which("energyplus.exe")]
    )
    if exe:
        candidate = _normalize_path(os.path.join(os.path.dirname(exe), "Energy+.idd"))
        ok = os.path.isfile(candidate)
        _append_attempt(attempts, "Next to ENERGYPLUS_EXE/PATH executable", candidate, ok)
        if ok:
            return {
                "path": candidate,
                "source": "Next to ENERGYPLUS_EXE/PATH executable",
                "attempts": attempts,
            }
    else:
        _append_attempt(attempts, "Next to ENERGYPLUS_EXE/PATH executable", None, False)

    cwd_candidate = _normalize_path(os.path.join(os.getcwd(), "Energy+.idd"))
    cwd_ok = os.path.isfile(cwd_candidate)
    _append_attempt(attempts, "Current working directory", cwd_candidate, cwd_ok)
    if cwd_ok:
        return {"path": cwd_candidate, "source": "Current working directory", "attempts": attempts}

    common_candidates = _common_idd_candidates()
    found_common = _pick_best(common_candidates)
    _append_attempt(
        attempts,
        "Common install scan",
        found_common if found_common else f"(scanned {len(common_candidates)} candidates)",
        bool(found_common),
    )
    if found_common:
        return {"path": found_common, "source": "Common install scan", "attempts": attempts}

    return {"path": None, "source": None, "attempts": attempts}


def _find_idd():
    """Compatibility wrapper: return discovered IDD path only."""
    return _discover_idd().get("path")


def _print_discovery_report(result):
    """Print discovery chain and final selected path."""
    print("=== Discovery: Energy+.idd ===")
    for idx, item in enumerate(result.get("attempts", []), 1):
        status = "OK" if item["ok"] else "MISS"
        print(f"  [{idx}] {status:<4} {item['source']}: {item['value']}")
    if result.get("path"):
        print(f"  -> Selected: {result['path']} (via {result['source']})")
    else:
        print("  -> Selected: (none)")
    print()


def _print_fix_instructions():
    """Print copy-paste environment variable fix commands."""
    print("One-click fix (PowerShell, auto-detect):")
    print("  $roots=(Get-PSDrive -PSProvider FileSystem | Select-Object -ExpandProperty Root)")
    print("  $epExe=foreach($r in $roots){Get-ChildItem -Path \"$r\\EnergyPlus*\\energyplus.exe\",\"$r\\Program Files\\EnergyPlus*\\energyplus.exe\",\"$r\\Program Files (x86)\\EnergyPlus*\\energyplus.exe\" -ErrorAction SilentlyContinue}|Sort-Object FullName -Descending|Select-Object -First 1 -ExpandProperty FullName")
    print("  if ($epExe) { $env:ENERGYPLUS_IDD=(Join-Path (Split-Path $epExe) 'Energy+.idd') }")
    print("Fix commands (PowerShell, persistent):")
    print('  setx ENERGYPLUS_IDD \"C:\\EnergyPlusV23-2-0\\Energy+.idd\"')
    print("One-click fix (bash/zsh, auto-detect):")
    print("  ep_exe=\"$(ls -1 /opt/EnergyPlus-*/energyplus /usr/local/EnergyPlus-*/energyplus /Applications/EnergyPlus-*/energyplus 2>/dev/null | sort -V | tail -n 1)\"")
    print("  if [ -n \"$ep_exe\" ]; then export ENERGYPLUS_IDD=\"$(dirname \"$ep_exe\")/Energy+.idd\"; fi")


def is_object_header(line):
    """Check if a line is an object type header (e.g., 'Building,')."""
    stripped = line.strip()
    if not stripped or stripped.startswith("!") or stripped.startswith("\\"):
        return False
    # Object headers: a name followed by comma, no leading whitespace indicating a field
    if stripped.endswith(",") and not line.startswith(" ") and not line.startswith("\t"):
        name = stripped[:-1].strip()
        # Must not be a field (fields start with A or N followed by digit)
        if re.match(r"^[AN]\d+\s*$", name):
            return False
        return len(name) > 0
    return False


def get_object_name(line):
    """Extract object type name from header line."""
    return line.strip().rstrip(",").strip()


def list_objects(idd_path):
    """List all object type names in the IDD."""
    if not idd_path or not os.path.exists(idd_path):
        print("Error: IDD file not found. Set ENERGYPLUS_IDD/ENERGYPLUS_HOME or add energyplus to PATH.")
        sys.exit(1)

    objects = []
    with open(idd_path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            if is_object_header(line):
                objects.append(get_object_name(line))

    print(f"=== EnergyPlus IDD Object Types ({len(objects)} total) ===\n")
    for i, obj in enumerate(objects, 1):
        print(f"  {i:4d}. {obj}")
    print(f"\nTotal: {len(objects)} object types")


def search_objects(keyword, idd_path):
    """Search object type names containing the keyword (case-insensitive)."""
    if not idd_path or not os.path.exists(idd_path):
        print("Error: IDD file not found. Set ENERGYPLUS_IDD/ENERGYPLUS_HOME or add energyplus to PATH.")
        sys.exit(1)

    keyword_lower = keyword.lower()
    matches = []
    with open(idd_path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            if is_object_header(line):
                name = get_object_name(line)
                if keyword_lower in name.lower():
                    matches.append(name)

    print(f'=== Search Results for "{keyword}" ({len(matches)} matches) ===\n')
    for m in matches:
        print(f"  - {m}")
    if not matches:
        print("  No matching object types found.")


def parse_object_definition(object_type, idd_path):
    """Parse a single object definition from the IDD, streaming line-by-line."""
    if not idd_path or not os.path.exists(idd_path):
        print("Error: IDD file not found. Set ENERGYPLUS_IDD/ENERGYPLUS_HOME or add energyplus to PATH.")
        sys.exit(1)

    target = object_type.strip()
    target_lower = target.lower()

    found = False
    memo_lines = []
    object_attrs = {}
    fields = []
    current_field = None

    with open(idd_path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            stripped = line.strip()

            if not found:
                # Look for the object header
                if is_object_header(line):
                    name = get_object_name(line)
                    if name.lower() == target_lower:
                        found = True
                        target = name  # preserve original case
                        continue
                continue

            # We're inside the target object definition
            # Check if we've hit the next object header (end of current definition)
            if is_object_header(line):
                break

            # Skip pure comment lines (not annotations)
            if stripped.startswith("!") and not stripped.startswith("\\"):
                continue

            # Empty line within object - skip
            if not stripped:
                continue

            # Object-level annotations
            if stripped.startswith("\\"):
                annotation = stripped
                if annotation.startswith("\\memo"):
                    memo_lines.append(annotation[len("\\memo"):].strip())
                elif annotation.startswith("\\unique-object"):
                    object_attrs["unique-object"] = True
                elif annotation.startswith("\\required-object"):
                    object_attrs["required-object"] = True
                elif annotation.startswith("\\min-fields"):
                    val = annotation[len("\\min-fields"):].strip()
                    object_attrs["min-fields"] = val
                elif annotation.startswith("\\extensible"):
                    val = annotation[len("\\extensible"):].strip().lstrip(":")
                    object_attrs["extensible"] = val
                elif annotation.startswith("\\obsolete"):
                    object_attrs["obsolete"] = annotation[len("\\obsolete"):].strip()
                elif annotation.startswith("\\format"):
                    object_attrs["format"] = annotation[len("\\format"):].strip()
                # Field-level annotations (when we have a current field)
                elif current_field is not None:
                    _parse_field_annotation(annotation, current_field)
                continue

            # Field definition line: starts with A or N followed by digit
            field_match = re.match(
                r"^\s*([AN]\d+)\s*([,;])\s*(\\.*)?$", stripped
            )
            if field_match:
                field_id = field_match.group(1)
                terminator = field_match.group(2)
                rest = field_match.group(3)

                current_field = {
                    "id": field_id,
                    "name": "",
                    "type": "alpha" if field_id.startswith("A") else "real",
                    "required": False,
                    "default": None,
                    "units": None,
                    "minimum": None,
                    "minimum_exclusive": False,
                    "maximum": None,
                    "maximum_exclusive": False,
                    "keys": [],
                    "notes": [],
                    "autosizable": False,
                    "autocalculatable": False,
                    "object_list": None,
                    "reference": None,
                    "is_last": terminator == ";",
                }
                fields.append(current_field)

                if rest:
                    _parse_field_annotation(rest.strip(), current_field)

                if terminator == ";":
                    # Last field - but continue reading annotations
                    pass
                continue

            # Continued annotation for current field
            if current_field is not None and stripped.startswith("\\"):
                _parse_field_annotation(stripped, current_field)

    if not found:
        print(f'Error: Object type "{object_type}" not found in IDD.')
        print(f"Try: python {sys.argv[0]} --search \"{object_type.split(':')[0]}\"")
        sys.exit(1)

    return target, memo_lines, object_attrs, fields


def _parse_field_annotation(annotation, field):
    """Parse a field-level annotation and update the field dict."""
    ann = annotation.strip()

    if ann.startswith("\\field"):
        field["name"] = ann[len("\\field"):].strip()
    elif ann.startswith("\\note"):
        field["notes"].append(ann[len("\\note"):].strip())
    elif ann.startswith("\\required-field"):
        field["required"] = True
    elif ann.startswith("\\type"):
        field["type"] = ann[len("\\type"):].strip()
    elif ann.startswith("\\default"):
        field["default"] = ann[len("\\default"):].strip()
    elif ann.startswith("\\units"):
        if not ann.startswith("\\unitsBasedOnField"):
            field["units"] = ann[len("\\units"):].strip()
    elif ann.startswith("\\minimum>"):
        field["minimum"] = ann[len("\\minimum>"):].strip()
        field["minimum_exclusive"] = True
    elif ann.startswith("\\minimum"):
        field["minimum"] = ann[len("\\minimum"):].strip()
        field["minimum_exclusive"] = False
    elif ann.startswith("\\maximum<"):
        field["maximum"] = ann[len("\\maximum<"):].strip()
        field["maximum_exclusive"] = True
    elif ann.startswith("\\maximum"):
        field["maximum"] = ann[len("\\maximum"):].strip()
        field["maximum_exclusive"] = False
    elif ann.startswith("\\key"):
        field["keys"].append(ann[len("\\key"):].strip())
    elif ann.startswith("\\autosizable"):
        field["autosizable"] = True
    elif ann.startswith("\\autocalculatable"):
        field["autocalculatable"] = True
    elif ann.startswith("\\object-list"):
        field["object_list"] = ann[len("\\object-list"):].strip()
    elif ann.startswith("\\reference"):
        field["reference"] = ann[len("\\reference"):].strip()


def print_full_definition(object_type, idd_path):
    """Print the full object definition."""
    name, memo, attrs, fields = parse_object_definition(object_type, idd_path)

    print(f"=== Object: {name} ===")

    if memo:
        print(f"\nDescription: {' '.join(memo)}")

    if attrs:
        attr_parts = []
        if attrs.get("unique-object"):
            attr_parts.append("unique-object")
        if attrs.get("required-object"):
            attr_parts.append("required-object")
        if attrs.get("min-fields"):
            attr_parts.append(f"min-fields: {attrs['min-fields']}")
        if attrs.get("extensible"):
            attr_parts.append(f"extensible: {attrs['extensible']}")
        if attrs.get("format"):
            attr_parts.append(f"format: {attrs['format']}")
        if attrs.get("obsolete"):
            attr_parts.append(f"OBSOLETE: {attrs['obsolete']}")
        if attr_parts:
            print(f"Attributes: {', '.join(attr_parts)}")

    print(f"\nFields ({len(fields)}):")
    print("-" * 90)

    for f in fields:
        # Build field info line
        parts = []

        # Required/optional
        if f["required"]:
            parts.append("[required]")

        # Type
        if f["type"] and f["type"] not in ("alpha", "real", "integer"):
            parts.append(f"type: {f['type']}")

        # Units
        if f["units"]:
            parts.append("{" + f["units"] + "}")

        # Default
        if f["default"] is not None:
            parts.append(f"default: {f['default']}")

        # Range
        range_parts = []
        if f["minimum"] is not None:
            op = ">" if f["minimum_exclusive"] else ">="
            range_parts.append(f"{op} {f['minimum']}")
        if f["maximum"] is not None:
            op = "<" if f["maximum_exclusive"] else "<="
            range_parts.append(f"{op} {f['maximum']}")
        if range_parts:
            parts.append("range: " + ", ".join(range_parts))

        # Autosizable / Autocalculatable
        if f["autosizable"]:
            parts.append("autosizable")
        if f["autocalculatable"]:
            parts.append("autocalculatable")

        # Keys (choices)
        if f["keys"]:
            if len(f["keys"]) <= 6:
                parts.append("choices: " + " | ".join(f["keys"]))
            else:
                shown = " | ".join(f["keys"][:6])
                parts.append(f"choices: {shown} | ... ({len(f['keys'])} total)")

        info = "  ".join(parts)
        print(f"  {f['id']:4s}  {f['name']:<40s}  {info}")

    print("-" * 90)
    print(f"Total: {len(fields)} fields")


def print_fields_table(object_type, idd_path):
    """Print a condensed field table."""
    name, _, _, fields = parse_object_definition(object_type, idd_path)

    print(f"=== {name} - Field Summary ===\n")
    print(f"  {'ID':<5s} {'Field Name':<45s} {'Req':>3s} {'Default':<15s} {'Units':<12s} {'Type':<10s}")
    print("  " + "-" * 95)

    for f in fields:
        req = "Y" if f["required"] else ""
        default = f["default"] if f["default"] is not None else ""
        units = f["units"] if f["units"] else ""
        ftype = f["type"] if f["type"] else ""
        if f["keys"]:
            ftype = "choice"
        print(f"  {f['id']:<5s} {f['name']:<45s} {req:>3s} {str(default):<15s} {units:<12s} {ftype:<10s}")


def main():
    parser = argparse.ArgumentParser(
        description="EnergyPlus IDD Lookup Tool - Query object definitions"
    )
    parser.add_argument("--idd", help="Manual Energy+.idd path override")

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "object_type",
        nargs="?",
        default=None,
        help="Object type name to look up (e.g., 'Material', 'Building')",
    )
    group.add_argument(
        "--list-objects",
        action="store_true",
        help="List all object type names",
    )
    group.add_argument(
        "--search",
        metavar="KEYWORD",
        help="Search object names containing keyword",
    )
    group.add_argument(
        "--fields",
        metavar="OBJECT_TYPE",
        help="Show condensed field table for object type",
    )
    group.add_argument(
        "--doctor", "--check-env",
        dest="doctor",
        action="store_true",
        help="Check discovery chain and resolved IDD path only",
    )

    args = parser.parse_args()
    idd_result = _discover_idd(args.idd)
    idd_path = idd_result["path"]
    _print_discovery_report(idd_result)

    if args.doctor:
        if not idd_path:
            print("Environment check: FAIL (Energy+.idd not resolved)")
            _print_fix_instructions()
            sys.exit(1)
        print("Environment check: PASS (Energy+.idd resolved)")
        sys.exit(0)

    if not idd_path:
        print("Error: IDD file not found.")
        _print_fix_instructions()
        sys.exit(1)

    if args.list_objects:
        list_objects(idd_path)
    elif args.search:
        search_objects(args.search, idd_path)
    elif args.fields:
        print_fields_table(args.fields, idd_path)
    elif args.object_type:
        print_full_definition(args.object_type, idd_path)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
