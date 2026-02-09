#!/usr/bin/env python
"""EnergyPlus simulation runner wrapper.

Wraps energyplus.exe with structured output, error capture, and path handling.

Usage:
    python run_simulation.py --idf <path> [--weather <path>] [--output-dir <path>]
        [--design-day] [--annual] [--expand-objects] [--readvars]
        [--epmacro] [--jobs N] [--energyplus-exe <path>] [--idd <path>]
        [--output-prefix <name>] [--timeout <seconds>]
    python run_simulation.py --check-env [--energyplus-exe <path>] [--idd <path>]
    python run_simulation.py --doctor [--energyplus-exe <path>] [--idd <path>]
"""

import argparse
import glob
import os
import re
import shutil
import subprocess
import sys
import time

DEFAULT_TIMEOUT = 600  # 10 minutes


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


def _common_exe_candidates():
    """Return common EnergyPlus executable paths by platform."""
    if os.name == "nt":
        patterns = []
        for root in _windows_drive_roots():
            patterns.extend([
                f"{root}\\EnergyPlus*\\energyplus.exe",
                f"{root}\\Program Files\\EnergyPlus*\\energyplus.exe",
                f"{root}\\Program Files (x86)\\EnergyPlus*\\energyplus.exe",
            ])
    else:
        patterns = [
            "/usr/local/EnergyPlus-*/energyplus",
            "/opt/EnergyPlus-*/energyplus",
            "/Applications/EnergyPlus-*/energyplus",
        ]
    candidates = []
    for pattern in patterns:
        candidates.extend(glob.glob(pattern))
    return candidates


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


def _discover_energyplus_exe(cli_path=None):
    """Discover EnergyPlus executable with trace metadata."""
    attempts = []

    if cli_path:
        candidate = _normalize_path(cli_path)
        ok = os.path.isfile(candidate)
        _append_attempt(attempts, "CLI --energyplus-exe", candidate, ok)
        return {
            "path": candidate if ok else None,
            "source": "CLI --energyplus-exe" if ok else None,
            "attempts": attempts,
        }

    env = os.environ.get("ENERGYPLUS_EXE")
    if env:
        candidate = _normalize_path(env)
        ok = os.path.isfile(candidate)
        _append_attempt(attempts, "ENV ENERGYPLUS_EXE", candidate, ok)
        if ok:
            return {"path": candidate, "source": "ENV ENERGYPLUS_EXE", "attempts": attempts}
    else:
        _append_attempt(attempts, "ENV ENERGYPLUS_EXE", None, False)

    home = os.environ.get("ENERGYPLUS_HOME") or os.environ.get("EPLUS_HOME")
    if home:
        exe_name = "energyplus.exe" if os.name == "nt" else "energyplus"
        candidate = _normalize_path(os.path.join(home, exe_name))
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

    path_candidates = [shutil.which("energyplus"), shutil.which("energyplus.exe")]
    found_on_path = _pick_best(path_candidates)
    _append_attempt(attempts, "PATH energyplus", found_on_path, bool(found_on_path))
    if found_on_path:
        return {"path": found_on_path, "source": "PATH energyplus", "attempts": attempts}

    common_candidates = _common_exe_candidates()
    found_common = _pick_best(common_candidates)
    _append_attempt(
        attempts,
        "Common install scan",
        found_common if found_common else f"(scanned {len(common_candidates)} candidates)",
        bool(found_common),
    )
    if found_common:
        return {
            "path": found_common,
            "source": "Common install scan",
            "attempts": attempts,
        }

    return {"path": None, "source": None, "attempts": attempts}


def _discover_idd(cli_path=None, exe_path=None, idf_path=None):
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

    if exe_path:
        candidate = _normalize_path(os.path.join(os.path.dirname(exe_path), "Energy+.idd"))
        ok = os.path.isfile(candidate)
        _append_attempt(attempts, "Next to resolved executable", candidate, ok)
        if ok:
            return {
                "path": candidate,
                "source": "Next to resolved executable",
                "attempts": attempts,
            }
    else:
        _append_attempt(attempts, "Next to resolved executable", None, False)

    local_candidates = []
    if idf_path:
        local_candidates.append(os.path.join(os.path.dirname(idf_path), "Energy+.idd"))
    local_candidates.append(os.path.join(os.getcwd(), "Energy+.idd"))
    found_local = _pick_best(local_candidates)
    _append_attempt(attempts, "IDF/CWD fallback", found_local, bool(found_local))
    if found_local:
        return {"path": found_local, "source": "IDF/CWD fallback", "attempts": attempts}

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


def _find_energyplus_exe():
    """Compatibility wrapper: return discovered executable path only."""
    return _discover_energyplus_exe().get("path")


def _find_idd(exe_path=None, idf_path=None):
    """Compatibility wrapper: return discovered IDD path only."""
    return _discover_idd(exe_path=exe_path, idf_path=idf_path).get("path")


def _print_discovery_report(label, result):
    """Print discovery chain and final selected path."""
    print(f"=== Discovery: {label} ===")
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
    print("  if ($epExe) { $env:ENERGYPLUS_EXE=$epExe; $env:ENERGYPLUS_IDD=(Join-Path (Split-Path $epExe) 'Energy+.idd') }")
    print("Fix commands (PowerShell, persistent):")
    print('  setx ENERGYPLUS_EXE \"C:\\EnergyPlusV23-2-0\\energyplus.exe\"')
    print('  setx ENERGYPLUS_IDD \"C:\\EnergyPlusV23-2-0\\Energy+.idd\"')
    print("One-click fix (bash/zsh, auto-detect):")
    print("  ep_exe=\"$(ls -1 /opt/EnergyPlus-*/energyplus /usr/local/EnergyPlus-*/energyplus /Applications/EnergyPlus-*/energyplus 2>/dev/null | sort -V | tail -n 1)\"")
    print("  if [ -n \"$ep_exe\" ]; then export ENERGYPLUS_EXE=\"$ep_exe\"; export ENERGYPLUS_IDD=\"$(dirname \"$ep_exe\")/Energy+.idd\"; fi")


def find_err_file(output_dir, prefix="eplusout"):
    """Find the .err file in the output directory."""
    # Try common names
    candidates = [
        os.path.join(output_dir, f"{prefix}.err"),
        os.path.join(output_dir, "eplusout.err"),
    ]
    for c in candidates:
        if os.path.exists(c):
            return c

    # Search for any .err file
    for f in os.listdir(output_dir):
        if f.endswith(".err"):
            return os.path.join(output_dir, f)
    return None


def parse_err_summary(err_path):
    """Parse .err file and return error counts and first error lines."""
    if not err_path or not os.path.exists(err_path):
        return {"fatal": 0, "severe": 0, "warning": 0, "lines": []}

    fatal = 0
    severe = 0
    warning = 0
    error_lines = []

    with open(err_path, "r", encoding="utf-8", errors="replace") as f:
        for line in f:
            stripped = line.strip()
            if stripped.startswith("**  Fatal  **"):
                fatal += 1
                error_lines.append(stripped)
            elif stripped.startswith("** Fatal **"):
                fatal += 1
                error_lines.append(stripped)
            elif stripped.startswith("** Severe  **"):
                severe += 1
                error_lines.append(stripped)
            elif stripped.startswith("**   ~~~   **") and error_lines:
                # Continuation of previous error
                error_lines.append(stripped)
            elif stripped.startswith("** Warning **"):
                warning += 1
                if len(error_lines) < 30:
                    error_lines.append(stripped)

    return {
        "fatal": fatal,
        "severe": severe,
        "warning": warning,
        "lines": error_lines[:20],
    }


def list_output_files(output_dir):
    """List generated output files with sizes."""
    if not os.path.exists(output_dir):
        return []

    files = []
    for f in sorted(os.listdir(output_dir)):
        fpath = os.path.join(output_dir, f)
        if os.path.isfile(fpath):
            size = os.path.getsize(fpath)
            if size < 1024:
                size_str = f"{size} B"
            elif size < 1024 * 1024:
                size_str = f"{size / 1024:.1f} KB"
            else:
                size_str = f"{size / (1024 * 1024):.1f} MB"
            files.append((f, size_str))
    return files


def main():
    parser = argparse.ArgumentParser(
        description="EnergyPlus Simulation Runner"
    )
    parser.add_argument("--idf", help="Path to IDF input file")
    parser.add_argument("--weather", "-w", help="Path to EPW weather file")
    parser.add_argument(
        "--output-dir", "-d", help="Output directory (default: current dir)"
    )
    parser.add_argument(
        "--design-day", "-D", action="store_true", help="Design-day only simulation"
    )
    parser.add_argument(
        "--annual", "-a", action="store_true", help="Force annual simulation"
    )
    parser.add_argument(
        "--expand-objects", "-x", action="store_true",
        help="Run ExpandObjects (required for HVACTemplate)"
    )
    parser.add_argument(
        "--readvars", "-r", action="store_true",
        help="Run ReadVarsESO to generate CSV output"
    )
    parser.add_argument(
        "--epmacro", "-m", action="store_true", help="Run EPMacro preprocessor"
    )
    parser.add_argument(
        "--jobs", "-j", type=int, help="Number of threads for multi-threading"
    )
    parser.add_argument(
        "--energyplus-exe", help="Manual EnergyPlus executable path override"
    )
    parser.add_argument(
        "--idd", help="Custom IDD path (default: auto-detect)"
    )
    parser.add_argument(
        "--check-env", action="store_true",
        help="Check discovery chain and resolved paths without running simulation"
    )
    parser.add_argument(
        "--doctor", action="store_true",
        help="Alias for --check-env"
    )
    parser.add_argument(
        "--output-prefix", help="Output file prefix (default: eplus)"
    )
    parser.add_argument(
        "--timeout", type=int, default=DEFAULT_TIMEOUT,
        help=f"Timeout in seconds (default: {DEFAULT_TIMEOUT})"
    )

    args = parser.parse_args()
    check_env_mode = args.check_env or args.doctor

    idf_hint = os.path.abspath(args.idf) if args.idf else None

    # Resolve environment and print discovery chains before execution.
    exe_result = _discover_energyplus_exe(args.energyplus_exe)
    ep_exe = exe_result["path"]
    idd_result = _discover_idd(args.idd, ep_exe, idf_hint)
    idd_path = idd_result["path"]

    _print_discovery_report("EnergyPlus executable", exe_result)
    _print_discovery_report("Energy+.idd", idd_result)

    if check_env_mode:
        status = 0
        if not ep_exe:
            print("Environment check: FAIL (EnergyPlus executable not resolved)")
            status = 1
        else:
            print("Environment check: PASS (EnergyPlus executable resolved)")
        if args.idd and not idd_path:
            print("Environment check: FAIL (--idd provided but file not resolved)")
            status = 1
        elif not idd_path:
            print("Environment check: WARN (Energy+.idd not resolved)")
        else:
            print("Environment check: PASS (Energy+.idd resolved)")
        if status != 0:
            print()
            _print_fix_instructions()
        sys.exit(status)

    if not ep_exe:
        print("Error: EnergyPlus executable not found.")
        _print_fix_instructions()
        sys.exit(1)

    if args.idd and not idd_path:
        print(f"Error: --idd file not found: {_normalize_path(args.idd)}")
        _print_fix_instructions()
        sys.exit(1)

    if not args.idf:
        parser.error("--idf is required unless --check-env/--doctor is used.")

    # Validate inputs
    idf_path = os.path.abspath(args.idf)
    if not os.path.exists(idf_path):
        print(f"Error: IDF file not found: {idf_path}")
        sys.exit(1)

    weather_path = None
    if args.weather:
        weather_path = os.path.abspath(args.weather)
        if not os.path.exists(weather_path):
            print(f"Error: Weather file not found: {weather_path}")
            sys.exit(1)

    # Determine output directory
    if args.output_dir:
        output_dir = os.path.abspath(args.output_dir)
    else:
        output_dir = os.path.join(os.path.dirname(idf_path), "output")

    os.makedirs(output_dir, exist_ok=True)

    # Build command
    cmd = [ep_exe]

    # IDD
    if idd_path:
        cmd.extend(["--idd", idd_path])

    # Output directory
    cmd.extend(["--output-directory", output_dir])

    # Output prefix
    if args.output_prefix:
        cmd.extend(["--output-prefix", args.output_prefix])

    # Weather file
    if weather_path:
        cmd.extend(["--weather", weather_path])

    # Flags
    if args.design_day:
        cmd.append("--design-day")
    if args.annual:
        cmd.append("--annual")
    if args.expand_objects:
        cmd.append("--expandobjects")
    if args.readvars:
        cmd.append("--readvars")
    if args.epmacro:
        cmd.append("--epmacro")
    if args.jobs:
        cmd.extend(["--jobs", str(args.jobs)])

    # Input file (must be last)
    cmd.append(idf_path)

    # Print pre-run info
    print("=== EnergyPlus Simulation ===\n")
    print(f"  IDF:          {idf_path}")
    print(f"  Weather:      {weather_path or 'None (Design-Day Only)'}")
    print(f"  Output Dir:   {output_dir}")
    print(f"  IDD:          {idd_path or '(not specified, using EnergyPlus default)'}")
    print(f"  Expand Obj:   {'Yes' if args.expand_objects else 'No'}")
    print(f"  ReadVars:     {'Yes' if args.readvars else 'No'}")
    print(f"  Timeout:      {args.timeout}s")
    print(f"\n  Command: {' '.join(cmd)}\n")
    print("  Running simulation...")

    # Execute
    start_time = time.time()
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=args.timeout,
            cwd=output_dir,
        )
        elapsed = time.time() - start_time
        returncode = result.returncode
    except subprocess.TimeoutExpired:
        elapsed = time.time() - start_time
        print(f"\n  TIMEOUT: Simulation exceeded {args.timeout}s limit.")
        print(f"  Elapsed: {elapsed:.1f}s")
        sys.exit(2)
    except Exception as e:
        elapsed = time.time() - start_time
        print(f"\n  EXECUTION ERROR: {e}")
        sys.exit(3)

    # Results
    status = "SUCCESS" if returncode == 0 else "FAILED"

    print(f"\n=== Simulation Result ===\n")
    print(f"  Status:       {status}")
    print(f"  Return Code:  {returncode}")
    print(f"  Duration:     {elapsed:.1f}s")

    # List output files
    files = list_output_files(output_dir)
    if files:
        print(f"\n  Generated Files ({len(files)}):")
        for fname, fsize in files:
            print(f"    - {fname} ({fsize})")

    # Parse and show error summary
    prefix = args.output_prefix if args.output_prefix else "eplusout"
    err_path = find_err_file(output_dir, prefix)

    if err_path:
        err_summary = parse_err_summary(err_path)
        print(f"\n  Error Summary (from {os.path.basename(err_path)}):")
        print(f"    Fatal:   {err_summary['fatal']}")
        print(f"    Severe:  {err_summary['severe']}")
        print(f"    Warning: {err_summary['warning']}")

        if err_summary["lines"]:
            print(f"\n  First errors/warnings:")
            for line in err_summary["lines"][:15]:
                print(f"    {line}")
    else:
        print("\n  No .err file found in output directory.")

    # Show stdout/stderr if there was an error
    if returncode != 0:
        if result.stdout.strip():
            print(f"\n  STDOUT:\n{result.stdout[:2000]}")
        if result.stderr.strip():
            print(f"\n  STDERR:\n{result.stderr[:2000]}")

    sys.exit(0 if returncode == 0 else 1)


if __name__ == "__main__":
    main()
