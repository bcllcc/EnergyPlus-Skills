#!/usr/bin/env python
"""EnergyPlus building geometry helper.

List, inspect, and modify building surface geometry in IDF files.

Usage:
    python geometry_helper.py list-surfaces <idf> [--zone <zone>] [--type <type>]
    python geometry_helper.py surface-info <idf> --name <surface_name>
    python geometry_helper.py scale <idf> --zone <zone> --axis <X|Y|Z> --factor <f> --output <out.idf>
    python geometry_helper.py set-height <idf> --zone <zone> --height <m> --output <out.idf>
    python geometry_helper.py move-wall <idf> --surface <name> --offset <m> --output <out.idf>
    python geometry_helper.py summary <idf>
"""

import argparse
import math
import os
import sys

SCRIPTS_DIR = os.path.dirname(os.path.abspath(__file__))


# ---------------------------------------------------------------------------
# IDF parsing (reuse idf_helper)
# ---------------------------------------------------------------------------

def _load_idf_helper():
    sys.path.insert(0, SCRIPTS_DIR)
    from idf_helper import parse_idf
    return parse_idf


def _get_objects_by_type(objects, type_name):
    """Filter objects by type (case-insensitive)."""
    t = type_name.lower()
    return [o for o in objects if o["type"].lower() == t]


# ---------------------------------------------------------------------------
# Vertex parsing
# ---------------------------------------------------------------------------

def parse_vertices(fields, vertex_start=11):
    """Parse XYZ vertex coordinates from surface fields.

    BuildingSurface:Detailed: vertex_start=11 (after 11 header fields)
    FenestrationSurface:Detailed: vertex_start=9 (after 9 header fields)

    Returns list of (x, y, z) tuples.
    """
    coords = []
    i = vertex_start
    while i + 2 < len(fields):
        try:
            x = float(fields[i].strip())
            y = float(fields[i + 1].strip())
            z = float(fields[i + 2].strip())
            coords.append((x, y, z))
        except (ValueError, IndexError):
            break
        i += 3
    return coords


def vertices_to_fields(vertices):
    """Convert list of (x,y,z) to flat field strings."""
    result = []
    for x, y, z in vertices:
        result.extend([_fmt_coord(x), _fmt_coord(y), _fmt_coord(z)])
    return result


def _fmt_coord(val):
    """Format coordinate value, avoiding unnecessary decimals."""
    if val == int(val):
        return str(int(val))
    return f"{val:.6g}"


# ---------------------------------------------------------------------------
# Geometry math (pure Python, no numpy)
# ---------------------------------------------------------------------------

def newell_normal(vertices):
    """Compute surface normal using Newell's method.

    Returns (nx, ny, nz) — not normalized.
    Reference: Newell (1972), adapted for EnergyPlus coordinate system.
    """
    n = len(vertices)
    nx = ny = nz = 0.0
    for i in range(n):
        j = (i + 1) % n
        vi = vertices[i]
        vj = vertices[j]
        nx += (vi[1] - vj[1]) * (vi[2] + vj[2])
        ny += (vi[2] - vj[2]) * (vi[0] + vj[0])
        nz += (vi[0] - vj[0]) * (vi[1] + vj[1])
    return (nx, ny, nz)


def vec_length(v):
    return math.sqrt(v[0]**2 + v[1]**2 + v[2]**2)


def vec_normalize(v):
    length = vec_length(v)
    if length < 1e-10:
        return (0, 0, 0)
    return (v[0]/length, v[1]/length, v[2]/length)


def polygon_area(vertices):
    """Compute area of a 3D polygon using Newell's method."""
    normal = newell_normal(vertices)
    return vec_length(normal) / 2.0


def surface_azimuth_tilt(vertices):
    """Compute azimuth and tilt from surface vertices.

    Returns (azimuth_deg, tilt_deg):
    - tilt: 0=facing up (floor/ceiling), 90=vertical (wall), 180=facing down
    - azimuth: degrees from north, clockwise (0=N, 90=E, 180=S, 270=W)
    """
    nx, ny, nz = vec_normalize(newell_normal(vertices))

    # Tilt from Z-axis
    tilt = math.degrees(math.acos(max(-1, min(1, nz))))

    # Azimuth from Y-axis (north), clockwise
    if abs(nx) < 1e-10 and abs(ny) < 1e-10:
        azimuth = 0.0  # horizontal surface
    else:
        azimuth = math.degrees(math.atan2(nx, ny))
        if azimuth < 0:
            azimuth += 360

    return azimuth, tilt


def centroid(vertices):
    """Compute centroid of a polygon."""
    n = len(vertices)
    if n == 0:
        return (0, 0, 0)
    cx = sum(v[0] for v in vertices) / n
    cy = sum(v[1] for v in vertices) / n
    cz = sum(v[2] for v in vertices) / n
    return (cx, cy, cz)


# ---------------------------------------------------------------------------
# Surface data extraction
# ---------------------------------------------------------------------------

def extract_surface_data(obj, vertex_start=11):
    """Extract geometry data from a BuildingSurface:Detailed object."""
    f = obj["fields"]
    verts = parse_vertices(f, vertex_start)
    area = polygon_area(verts) if verts else 0
    az, tilt = surface_azimuth_tilt(verts) if verts else (0, 0)

    return {
        "name": f[0].strip() if len(f) > 0 else "",
        "surface_type": f[1].strip() if len(f) > 1 else "",
        "construction": f[2].strip() if len(f) > 2 else "",
        "zone": f[3].strip() if len(f) > 3 else "",
        "space": f[4].strip() if len(f) > 4 else "",
        "boundary": f[5].strip() if len(f) > 5 else "",
        "boundary_obj": f[6].strip() if len(f) > 6 else "",
        "vertices": verts,
        "area": area,
        "azimuth": az,
        "tilt": tilt,
        "n_vertices": len(verts),
        "_obj": obj,
    }


def extract_fenestration_data(obj):
    """Extract geometry data from a FenestrationSurface:Detailed object."""
    f = obj["fields"]
    verts = parse_vertices(f, vertex_start=9)
    area = polygon_area(verts) if verts else 0

    return {
        "name": f[0].strip() if len(f) > 0 else "",
        "surface_type": f[1].strip() if len(f) > 1 else "",
        "construction": f[2].strip() if len(f) > 2 else "",
        "parent_surface": f[3].strip() if len(f) > 3 else "",
        "vertices": verts,
        "area": area,
        "n_vertices": len(verts),
        "_obj": obj,
    }


# ---------------------------------------------------------------------------
# IDF modification helpers
# ---------------------------------------------------------------------------

def _rebuild_surface_text(obj_type, fields, vertices, vertex_start):
    """Rebuild an IDF object's text with updated vertices.

    Preserves header fields, replaces vertex fields.
    """
    lines = [f"{obj_type},"]
    header_fields = fields[:vertex_start]
    vert_fields = vertices_to_fields(vertices)

    # Header fields with commas
    for i, val in enumerate(header_fields):
        pad = " " * 4
        comment = ""
        # Preserve original comment if available from raw
        lines.append(f"{pad}{val},")

    # Vertex fields - last one gets semicolon
    for i, val in enumerate(vert_fields):
        pad = " " * 4
        sep = ";" if i == len(vert_fields) - 1 else ","
        lines.append(f"{pad}{val}{sep}")

    return "\n".join(lines) + "\n"


def modify_idf_surfaces(src_path, dst_path, surface_mods):
    """Modify surface vertices in an IDF file.

    surface_mods: dict mapping surface_name -> new_vertices list
    """
    parse_idf = _load_idf_helper()
    objects = parse_idf(src_path)

    with open(src_path, "r", encoding="utf-8", errors="replace") as f:
        lines = f.readlines()

    # Build modification map
    mod_map = {name.lower(): verts for name, verts in surface_mods.items()}
    modified_count = 0

    # Process objects in reverse order (to not invalidate line numbers)
    targets = []
    for obj in objects:
        if obj["type"].lower() in ("buildingsurface:detailed",
                                    "fenestrationsurface:detailed"):
            name = obj["fields"][0].strip().lower() if obj["fields"] else ""
            if name in mod_map:
                targets.append(obj)

    targets.sort(key=lambda o: o["line_start"], reverse=True)

    for obj in targets:
        name = obj["fields"][0].strip().lower()
        new_verts = mod_map[name]
        vstart = 11 if obj["type"].lower() == "buildingsurface:detailed" else 9

        # Build new fields: header + new vertex coords
        header = obj["fields"][:vstart]
        new_vert_fields = vertices_to_fields(new_verts)
        all_fields = header + new_vert_fields

        # Rebuild the object text preserving comments from original
        new_text = _rebuild_object_from_raw(obj, all_fields, vstart)

        # Replace lines (line_start/line_end are 1-based from parse_idf)
        start = obj["line_start"] - 1  # convert to 0-based
        end = obj["line_end"]          # 1-based end = 0-based exclusive end
        lines[start:end] = [new_text]
        modified_count += 1

    with open(dst_path, "w", encoding="utf-8", newline="") as f:
        f.writelines(lines)

    return modified_count


def _rebuild_object_from_raw(obj, new_fields, vertex_start):
    """Rebuild object text preserving formatting where possible.

    Uses original raw text for header fields, regenerates vertex section.
    """
    raw_lines = obj["raw"].split("\n")

    # Strategy: keep raw lines up through header, replace vertex lines
    # Count fields in raw lines to find where vertices start
    field_count = 0
    header_end_line = 0

    for i, line in enumerate(raw_lines):
        code = line.split("!")[0]
        if "," in code or ";" in code:
            # Count fields (separated by commas or terminated by semicolon)
            parts = code.replace(";", ",").split(",")
            for p in parts:
                if p.strip():
                    field_count += 1
            if field_count > vertex_start:
                header_end_line = i
                break
            header_end_line = i + 1

    # Keep header lines (type line + header fields)
    result_lines = []

    # Type line
    result_lines.append(f"{obj['type']},")

    # Header fields (indices 0 to vertex_start-1)
    for fi in range(vertex_start):
        val = new_fields[fi] if fi < len(new_fields) else ""
        result_lines.append(f"    {val},")

    # Vertex fields
    vert_fields = new_fields[vertex_start:]
    for i, val in enumerate(vert_fields):
        sep = ";" if i == len(vert_fields) - 1 else ","
        result_lines.append(f"    {val}{sep}")

    return "\n".join(result_lines) + "\n"


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_list_surfaces(args):
    """List all building surfaces with geometry info."""
    parse_idf = _load_idf_helper()
    objects = parse_idf(os.path.abspath(args.idf))

    surfaces = _get_objects_by_type(objects, "BuildingSurface:Detailed")
    if not surfaces:
        print("No BuildingSurface:Detailed objects found")
        sys.exit(1)

    # Extract data
    data = [extract_surface_data(s) for s in surfaces]

    # Filter
    if args.zone:
        zone_filter = args.zone.lower()
        data = [d for d in data if zone_filter in d["zone"].lower()]
    if args.type:
        type_filter = args.type.lower()
        data = [d for d in data if d["surface_type"].lower() == type_filter]

    if not data:
        print("No surfaces matching filter criteria")
        sys.exit(1)

    print(f"=== Building Surfaces ({len(data)}) ===")
    print()
    header = (f"  {'Name':<25s} {'Type':<10s} {'Zone':<30s} "
              f"{'Area(m2)':>9s} {'Az(deg)':>8s} {'Tilt':>6s} {'Verts':>5s}")
    print(header)
    print(f"  {'-'*93}")

    for d in data:
        name = d["name"][:25]
        stype = d["surface_type"][:10]
        zone = d["zone"][:30]
        area = f"{d['area']:.2f}"
        az = f"{d['azimuth']:.0f}"
        tilt = f"{d['tilt']:.0f}"
        nv = str(d["n_vertices"])
        print(f"  {name:<25s} {stype:<10s} {zone:<30s} "
              f"{area:>9s} {az:>8s} {tilt:>6s} {nv:>5s}")


def cmd_surface_info(args):
    """Show detailed info for a specific surface."""
    parse_idf = _load_idf_helper()
    objects = parse_idf(os.path.abspath(args.idf))

    # Search in both surface types
    target = args.name.lower()
    found = None

    for obj in objects:
        if obj["type"].lower() == "buildingsurface:detailed":
            if obj["fields"] and obj["fields"][0].strip().lower() == target:
                found = ("building", extract_surface_data(obj))
                break
        elif obj["type"].lower() == "fenestrationsurface:detailed":
            if obj["fields"] and obj["fields"][0].strip().lower() == target:
                found = ("fenestration", extract_fenestration_data(obj))
                break

    if not found:
        print(f"Error: Surface '{args.name}' not found")
        sys.exit(1)

    kind, d = found

    print(f"=== Surface: {d['name']} ===")
    print(f"  Type:           {d['surface_type']}")
    print(f"  Construction:   {d['construction']}")

    if kind == "building":
        print(f"  Zone:           {d['zone']}")
        print(f"  Space:          {d['space']}")
        print(f"  Boundary:       {d['boundary']}")
        if d["boundary_obj"]:
            print(f"  Boundary obj:   {d['boundary_obj']}")
    else:
        print(f"  Parent surface: {d['parent_surface']}")

    print(f"  Area:           {d['area']:.4f} m2")

    if kind == "building":
        print(f"  Azimuth:        {d['azimuth']:.1f} deg")
        print(f"  Tilt:           {d['tilt']:.1f} deg")

    print(f"  Vertices:       {d['n_vertices']}")
    for i, (x, y, z) in enumerate(d["vertices"]):
        print(f"    [{i+1}] ({x:.6g}, {y:.6g}, {z:.6g})")

    # Find associated fenestration (for building surfaces)
    if kind == "building":
        fens = _get_objects_by_type(objects, "FenestrationSurface:Detailed")
        children = []
        for f in fens:
            fd = extract_fenestration_data(f)
            if fd["parent_surface"].lower() == target:
                children.append(fd)
        if children:
            print(f"\n  --- Associated Fenestration ({len(children)}) ---")
            for c in children:
                print(f"    {c['name']}: {c['surface_type']}, "
                      f"{c['area']:.2f} m2, {c['n_vertices']} verts")


def cmd_scale(args):
    """Scale zone geometry along an axis."""
    parse_idf = _load_idf_helper()
    idf_path = os.path.abspath(args.idf)
    objects = parse_idf(idf_path)

    axis = args.axis.upper()
    axis_idx = {"X": 0, "Y": 1, "Z": 2}.get(axis)
    if axis_idx is None:
        print(f"Error: Invalid axis '{args.axis}', must be X, Y, or Z")
        sys.exit(1)

    factor = args.factor
    zone_filter = args.zone.lower()

    # Find zone centroid for scaling reference
    surfaces = _get_objects_by_type(objects, "BuildingSurface:Detailed")
    zone_surfaces = [extract_surface_data(s) for s in surfaces
                     if zone_filter in s["fields"][3].strip().lower()]

    if not zone_surfaces:
        print(f"Error: No surfaces found for zone matching '{args.zone}'")
        sys.exit(1)

    # Compute zone centroid (average of all vertices)
    all_verts = []
    for sd in zone_surfaces:
        all_verts.extend(sd["vertices"])
    ref = centroid(all_verts)

    # Scale vertices relative to centroid
    surface_mods = {}
    for sd in zone_surfaces:
        new_verts = []
        for v in sd["vertices"]:
            nv = list(v)
            nv[axis_idx] = ref[axis_idx] + (v[axis_idx] - ref[axis_idx]) * factor
            new_verts.append(tuple(nv))
        surface_mods[sd["name"]] = new_verts

    # Also scale fenestration surfaces on matching parent walls
    fens = _get_objects_by_type(objects, "FenestrationSurface:Detailed")
    zone_surface_names = {sd["name"].lower() for sd in zone_surfaces}
    for fobj in fens:
        fd = extract_fenestration_data(fobj)
        if fd["parent_surface"].lower() in zone_surface_names:
            new_verts = []
            for v in fd["vertices"]:
                nv = list(v)
                nv[axis_idx] = ref[axis_idx] + (v[axis_idx] - ref[axis_idx]) * factor
                new_verts.append(tuple(nv))
            surface_mods[fd["name"]] = new_verts

    output = os.path.abspath(args.output)
    count = modify_idf_surfaces(idf_path, output, surface_mods)
    print(f"=== Scale: {axis} x {factor} ===")
    print(f"  Zone:     {args.zone}")
    print(f"  Modified: {count} surfaces")
    print(f"  Output:   {output}")


def cmd_set_height(args):
    """Set zone ceiling height by adjusting Z coordinates."""
    parse_idf = _load_idf_helper()
    idf_path = os.path.abspath(args.idf)
    objects = parse_idf(idf_path)

    new_height = args.height
    zone_filter = args.zone.lower()

    surfaces = _get_objects_by_type(objects, "BuildingSurface:Detailed")
    zone_surfaces = [extract_surface_data(s) for s in surfaces
                     if zone_filter in s["fields"][3].strip().lower()]

    if not zone_surfaces:
        print(f"Error: No surfaces found for zone matching '{args.zone}'")
        sys.exit(1)

    # Find current Z range
    all_z = []
    for sd in zone_surfaces:
        for v in sd["vertices"]:
            all_z.append(v[2])

    z_min = min(all_z)
    z_max = max(all_z)
    current_height = z_max - z_min

    if current_height < 0.01:
        print(f"Error: Zone appears to be flat (height={current_height:.3f}m)")
        sys.exit(1)

    z_factor = new_height / current_height

    # Scale Z coordinates relative to z_min
    surface_mods = {}
    for sd in zone_surfaces:
        new_verts = []
        for v in sd["vertices"]:
            new_z = z_min + (v[2] - z_min) * z_factor
            new_verts.append((v[0], v[1], new_z))
        surface_mods[sd["name"]] = new_verts

    # Also update fenestration
    fens = _get_objects_by_type(objects, "FenestrationSurface:Detailed")
    zone_surface_names = {sd["name"].lower() for sd in zone_surfaces}
    for fobj in fens:
        fd = extract_fenestration_data(fobj)
        if fd["parent_surface"].lower() in zone_surface_names:
            new_verts = []
            for v in fd["vertices"]:
                new_z = z_min + (v[2] - z_min) * z_factor
                new_verts.append((v[0], v[1], new_z))
            surface_mods[fd["name"]] = new_verts

    output = os.path.abspath(args.output)
    count = modify_idf_surfaces(idf_path, output, surface_mods)
    print(f"=== Set Height: {new_height}m ===")
    print(f"  Zone:            {args.zone}")
    print(f"  Previous height: {current_height:.2f}m")
    print(f"  New height:      {new_height:.2f}m")
    print(f"  Modified:        {count} surfaces")
    print(f"  Output:          {output}")


def cmd_move_wall(args):
    """Move a wall surface along its outward normal direction."""
    parse_idf = _load_idf_helper()
    idf_path = os.path.abspath(args.idf)
    objects = parse_idf(idf_path)

    target = args.surface.lower()
    offset = args.offset

    # Find the target surface
    surfaces = _get_objects_by_type(objects, "BuildingSurface:Detailed")
    wall_data = None
    for s in surfaces:
        sd = extract_surface_data(s)
        if sd["name"].lower() == target:
            wall_data = sd
            break

    if not wall_data:
        print(f"Error: Surface '{args.surface}' not found")
        sys.exit(1)

    if wall_data["surface_type"].lower() != "wall":
        print(f"Warning: Surface is type '{wall_data['surface_type']}', not Wall")

    # Compute outward normal (unit vector)
    normal = vec_normalize(newell_normal(wall_data["vertices"]))

    # Translate all vertices along normal
    surface_mods = {}
    new_verts = []
    for v in wall_data["vertices"]:
        new_verts.append((
            v[0] + normal[0] * offset,
            v[1] + normal[1] * offset,
            v[2] + normal[2] * offset,
        ))
    surface_mods[wall_data["name"]] = new_verts

    # Also move fenestration on this wall
    fens = _get_objects_by_type(objects, "FenestrationSurface:Detailed")
    for fobj in fens:
        fd = extract_fenestration_data(fobj)
        if fd["parent_surface"].lower() == target:
            new_fverts = []
            for v in fd["vertices"]:
                new_fverts.append((
                    v[0] + normal[0] * offset,
                    v[1] + normal[1] * offset,
                    v[2] + normal[2] * offset,
                ))
            surface_mods[fd["name"]] = new_fverts

    output = os.path.abspath(args.output)
    count = modify_idf_surfaces(idf_path, output, surface_mods)
    print(f"=== Move Wall ===")
    print(f"  Surface:   {wall_data['name']}")
    print(f"  Normal:    ({normal[0]:.3f}, {normal[1]:.3f}, {normal[2]:.3f})")
    print(f"  Offset:    {offset}m")
    print(f"  Modified:  {count} surfaces")
    print(f"  Output:    {output}")


def cmd_summary(args):
    """Print geometry summary by zone."""
    parse_idf = _load_idf_helper()
    objects = parse_idf(os.path.abspath(args.idf))

    surfaces = _get_objects_by_type(objects, "BuildingSurface:Detailed")
    fens = _get_objects_by_type(objects, "FenestrationSurface:Detailed")

    if not surfaces:
        print("No BuildingSurface:Detailed objects found")
        sys.exit(1)

    # Extract all data
    surf_data = [extract_surface_data(s) for s in surfaces]
    fen_data = [extract_fenestration_data(f) for f in fens]

    # Build fenestration parent map
    fen_by_parent = {}
    for fd in fen_data:
        parent = fd["parent_surface"].lower()
        if parent not in fen_by_parent:
            fen_by_parent[parent] = []
        fen_by_parent[parent].append(fd)

    # Group by zone
    zones = {}
    for sd in surf_data:
        zone = sd["zone"]
        if zone not in zones:
            zones[zone] = []
        zones[zone].append(sd)

    print(f"=== Geometry Summary ===")
    print(f"  Zones: {len(zones)}")
    print(f"  Surfaces: {len(surf_data)}")
    print(f"  Fenestration: {len(fen_data)}")
    print()

    total_floor = 0
    total_wall_ext = 0
    total_window = 0

    header = (f"  {'Zone':<30s} {'Floor(m2)':>10s} {'Wall-Ext(m2)':>12s} "
              f"{'Window(m2)':>11s} {'WWR(%)':>7s} {'Surfaces':>8s}")
    print(header)
    print(f"  {'-'*78}")

    for zone_name in sorted(zones.keys()):
        zone_surfs = zones[zone_name]
        floor_area = sum(sd["area"] for sd in zone_surfs
                        if sd["surface_type"].lower() == "floor")
        ext_wall_area = sum(sd["area"] for sd in zone_surfs
                           if sd["surface_type"].lower() == "wall"
                           and sd["boundary"].lower() == "outdoors")

        # Window area on exterior walls
        window_area = 0
        for sd in zone_surfs:
            if sd["surface_type"].lower() == "wall" and sd["boundary"].lower() == "outdoors":
                children = fen_by_parent.get(sd["name"].lower(), [])
                for c in children:
                    if c["surface_type"].lower() == "window":
                        window_area += c["area"]

        wwr = (window_area / ext_wall_area * 100) if ext_wall_area > 0.01 else 0

        total_floor += floor_area
        total_wall_ext += ext_wall_area
        total_window += window_area

        zn = zone_name[:30]
        print(f"  {zn:<30s} {floor_area:>10.2f} {ext_wall_area:>12.2f} "
              f"{window_area:>11.2f} {wwr:>7.1f} {len(zone_surfs):>8d}")

    # Totals
    total_wwr = (total_window / total_wall_ext * 100) if total_wall_ext > 0.01 else 0
    print(f"  {'-'*78}")
    print(f"  {'TOTAL':<30s} {total_floor:>10.2f} {total_wall_ext:>12.2f} "
          f"{total_window:>11.2f} {total_wwr:>7.1f} {len(surf_data):>8d}")


# ---------------------------------------------------------------------------
# Geometry creation helpers
# ---------------------------------------------------------------------------

def _idf_surface(name, stype, construction, zone, space, boundary,
                 boundary_obj, sun, wind, vertices):
    """Generate BuildingSurface:Detailed IDF text."""
    lines = ["BuildingSurface:Detailed,"]
    fields = [
        (name, "Name"),
        (stype, "Surface Type"),
        (construction, "Construction Name"),
        (zone, "Zone Name"),
        (space, "Space Name"),
        (boundary, "Outside Boundary Condition"),
        (boundary_obj, "Outside Boundary Condition Object"),
        (sun, "Sun Exposure"),
        (wind, "Wind Exposure"),
        ("", "View Factor to Ground"),
        ("", "Number of Vertices"),
    ]
    for val, comment in fields:
        lines.append(f"    {val},  !- {comment}")
    for i, (x, y, z) in enumerate(vertices):
        vi = i + 1
        coord_idx = (i % 1) + 1  # simplified
        xs = _fmt_coord(x)
        ys = _fmt_coord(y)
        zs = _fmt_coord(z)
        if i == len(vertices) - 1:
            lines.append(f"    {xs},  !- Vertex {vi} X-coordinate {{m}}")
            lines.append(f"    {ys},  !- Vertex {vi} Y-coordinate {{m}}")
            lines.append(f"    {zs};  !- Vertex {vi} Z-coordinate {{m}}")
        else:
            lines.append(f"    {xs},  !- Vertex {vi} X-coordinate {{m}}")
            lines.append(f"    {ys},  !- Vertex {vi} Y-coordinate {{m}}")
            lines.append(f"    {zs},  !- Vertex {vi} Z-coordinate {{m}}")
    return "\n".join(lines)


def _idf_fenestration(name, stype, construction, parent_surface, vertices):
    """Generate FenestrationSurface:Detailed IDF text."""
    lines = ["FenestrationSurface:Detailed,"]
    fields = [
        (name, "Name"),
        (stype, "Surface Type"),
        (construction, "Construction Name"),
        (parent_surface, "Building Surface Name"),
        ("", "Outside Boundary Condition Object"),
        ("", "View Factor to Ground"),
        ("", "Frame and Divider Name"),
        ("", "Multiplier"),
        ("", "Number of Vertices"),
    ]
    for val, comment in fields:
        lines.append(f"    {val},  !- {comment}")
    for i, (x, y, z) in enumerate(vertices):
        vi = i + 1
        xs = _fmt_coord(x)
        ys = _fmt_coord(y)
        zs = _fmt_coord(z)
        sep = ";" if i == len(vertices) - 1 else ","
        lines.append(f"    {xs},  !- Vertex {vi} X-coordinate {{m}}")
        lines.append(f"    {ys},  !- Vertex {vi} Y-coordinate {{m}}")
        lines.append(f"    {zs}{sep}  !- Vertex {vi} Z-coordinate {{m}}")
    return "\n".join(lines)


def _box_surfaces(zone_name, space_name, w, d, h,
                  wall_constr, floor_constr, roof_constr, prefix=""):
    """Generate 6 surfaces for a rectangular box zone.

    Vertices follow GlobalGeometryRules: UpperLeftCorner, Counterclockwise.
    Coordinate system: Relative (to zone origin).
    """
    p = prefix
    surfaces = []

    # Floor: outward normal = (0,0,-1) = downward
    surfaces.append(_idf_surface(
        f"{p}Floor", "Floor", floor_constr, zone_name, space_name,
        "Ground", "", "NoSun", "NoWind",
        [(w, d, 0), (w, 0, 0), (0, 0, 0), (0, d, 0)]))

    # Roof: outward normal = (0,0,+1) = upward
    surfaces.append(_idf_surface(
        f"{p}Roof", "Roof", roof_constr, zone_name, space_name,
        "Outdoors", "", "SunExposed", "WindExposed",
        [(w, 0, h), (w, d, h), (0, d, h), (0, 0, h)]))

    # South wall (Y=0): outward normal = (0,-1,0)
    surfaces.append(_idf_surface(
        f"{p}Wall-S", "Wall", wall_constr, zone_name, space_name,
        "Outdoors", "", "SunExposed", "WindExposed",
        [(0, 0, h), (0, 0, 0), (w, 0, 0), (w, 0, h)]))

    # North wall (Y=D): outward normal = (0,+1,0)
    surfaces.append(_idf_surface(
        f"{p}Wall-N", "Wall", wall_constr, zone_name, space_name,
        "Outdoors", "", "SunExposed", "WindExposed",
        [(w, d, h), (w, d, 0), (0, d, 0), (0, d, h)]))

    # East wall (X=W): outward normal = (+1,0,0)
    surfaces.append(_idf_surface(
        f"{p}Wall-E", "Wall", wall_constr, zone_name, space_name,
        "Outdoors", "", "SunExposed", "WindExposed",
        [(w, 0, h), (w, 0, 0), (w, d, 0), (w, d, h)]))

    # West wall (X=0): outward normal = (-1,0,0)
    surfaces.append(_idf_surface(
        f"{p}Wall-W", "Wall", wall_constr, zone_name, space_name,
        "Outdoors", "", "SunExposed", "WindExposed",
        [(0, d, h), (0, d, 0), (0, 0, 0), (0, 0, h)]))

    return surfaces


def cmd_create_box(args):
    """Create a rectangular single-zone building geometry."""
    w = args.width
    d = args.depth
    h = args.height
    zone_name = args.zone_name or "Zone1"
    space_name = zone_name.replace("Zone", "Space") if "Zone" in zone_name else f"{zone_name}_Space"

    wall_c = args.wall_construction or "ExternalWall"
    floor_c = args.floor_construction or "GroundFloor"
    roof_c = args.roof_construction or "ExternalRoof"

    # Generate IDF objects
    parts = []

    # GlobalGeometryRules
    parts.append("""GlobalGeometryRules,
    UpperLeftCorner,  !- Starting Vertex Position
    Counterclockwise,  !- Vertex Entry Direction
    Relative;  !- Coordinate System""")

    # Zone
    ox, oy, oz = 0, 0, 0
    if args.origin:
        coords = [float(x) for x in args.origin.split(",")]
        ox, oy, oz = coords[0], coords[1], coords[2] if len(coords) > 2 else 0

    rot = args.orientation or 0

    parts.append(f"""Zone,
    {zone_name},  !- Name
    {rot},  !- Direction of Relative North {{deg}}
    {_fmt_coord(ox)},  !- X Origin {{m}}
    {_fmt_coord(oy)},  !- Y Origin {{m}}
    {_fmt_coord(oz)};  !- Z Origin {{m}}""")

    # Surfaces
    surfaces = _box_surfaces(zone_name, space_name, w, d, h,
                             wall_c, floor_c, roof_c)
    parts.extend(surfaces)

    output = os.path.abspath(args.output)
    with open(output, "w", encoding="utf-8") as f:
        f.write("\n\n".join(parts) + "\n")

    floor_area = w * d
    volume = w * d * h
    wall_area = 2 * (w + d) * h

    print(f"=== Create Box ===")
    print(f"  Zone:       {zone_name}")
    print(f"  Dimensions: {w} x {d} x {h} m")
    print(f"  Floor area: {floor_area:.1f} m2")
    print(f"  Volume:     {volume:.1f} m3")
    print(f"  Wall area:  {wall_area:.1f} m2 (exterior)")
    print(f"  Surfaces:   6 (4 walls + floor + roof)")
    print(f"  Output:     {output}")


def cmd_create_l_shape(args):
    """Create an L-shaped two-zone building geometry."""
    w1 = args.width1
    d1 = args.depth1
    w2 = args.width2
    d2 = args.depth2
    h = args.height

    zone_names = ["Zone1", "Zone2"]
    if args.zone_names:
        names = args.zone_names.split(",")
        zone_names = [n.strip() for n in names[:2]]
        while len(zone_names) < 2:
            zone_names.append(f"Zone{len(zone_names)+1}")

    wall_c = args.wall_construction or "ExternalWall"
    floor_c = args.floor_construction or "GroundFloor"
    roof_c = args.roof_construction or "ExternalRoof"

    parts = []

    # GlobalGeometryRules
    parts.append("""GlobalGeometryRules,
    UpperLeftCorner,  !- Starting Vertex Position
    Counterclockwise,  !- Vertex Entry Direction
    Relative;  !- Coordinate System""")

    # Zone 1 at origin (0,0,0)
    z1 = zone_names[0]
    s1 = z1.replace("Zone", "Space") if "Zone" in z1 else f"{z1}_Space"
    parts.append(f"""Zone,
    {z1},  !- Name
    0,  !- Direction of Relative North {{deg}}
    0,  !- X Origin {{m}}
    0,  !- Y Origin {{m}}
    0;  !- Z Origin {{m}}""")

    # Zone 2 at (w1, 0, 0) — adjacent to east wall of zone 1
    z2 = zone_names[1]
    s2 = z2.replace("Zone", "Space") if "Zone" in z2 else f"{z2}_Space"
    parts.append(f"""Zone,
    {z2},  !- Name
    0,  !- Direction of Relative North {{deg}}
    {_fmt_coord(w1)},  !- X Origin {{m}}
    0,  !- Y Origin {{m}}
    0;  !- Z Origin {{m}}""")

    # --- Zone 1 surfaces (box minus east wall, replaced with internal wall) ---
    # Floor
    parts.append(_idf_surface(
        f"{z1}_Floor", "Floor", floor_c, z1, s1,
        "Ground", "", "NoSun", "NoWind",
        [(w1, d1, 0), (w1, 0, 0), (0, 0, 0), (0, d1, 0)]))
    # Roof
    parts.append(_idf_surface(
        f"{z1}_Roof", "Roof", roof_c, z1, s1,
        "Outdoors", "", "SunExposed", "WindExposed",
        [(w1, 0, h), (w1, d1, h), (0, d1, h), (0, 0, h)]))
    # South wall
    parts.append(_idf_surface(
        f"{z1}_Wall-S", "Wall", wall_c, z1, s1,
        "Outdoors", "", "SunExposed", "WindExposed",
        [(0, 0, h), (0, 0, 0), (w1, 0, 0), (w1, 0, h)]))
    # North wall
    parts.append(_idf_surface(
        f"{z1}_Wall-N", "Wall", wall_c, z1, s1,
        "Outdoors", "", "SunExposed", "WindExposed",
        [(w1, d1, h), (w1, d1, 0), (0, d1, 0), (0, d1, h)]))
    # West wall
    parts.append(_idf_surface(
        f"{z1}_Wall-W", "Wall", wall_c, z1, s1,
        "Outdoors", "", "SunExposed", "WindExposed",
        [(0, d1, h), (0, d1, 0), (0, 0, 0), (0, 0, h)]))
    # East wall (internal, shared with Zone 2) — only the portion that overlaps
    # Shared height from 0 to min(d1, d2)
    shared_d = min(d1, d2)
    parts.append(_idf_surface(
        f"{z1}_Wall-E-Int", "Wall", wall_c, z1, s1,
        "Surface", f"{z2}_Wall-W-Int", "NoSun", "NoWind",
        [(w1, 0, h), (w1, 0, 0), (w1, shared_d, 0), (w1, shared_d, h)]))
    # If d1 > d2, there's an exposed portion of east wall above the shared area
    if d1 > d2:
        parts.append(_idf_surface(
            f"{z1}_Wall-E-Ext", "Wall", wall_c, z1, s1,
            "Outdoors", "", "SunExposed", "WindExposed",
            [(w1, shared_d, h), (w1, shared_d, 0), (w1, d1, 0), (w1, d1, h)]))

    # --- Zone 2 surfaces ---
    # Note: Zone 2 coordinates are relative to its origin (w1, 0, 0)
    # So in Zone 2's local coords, it's a box from (0,0,0) to (w2, d2, h)
    parts.append(_idf_surface(
        f"{z2}_Floor", "Floor", floor_c, z2, s2,
        "Ground", "", "NoSun", "NoWind",
        [(w2, d2, 0), (w2, 0, 0), (0, 0, 0), (0, d2, 0)]))
    parts.append(_idf_surface(
        f"{z2}_Roof", "Roof", roof_c, z2, s2,
        "Outdoors", "", "SunExposed", "WindExposed",
        [(w2, 0, h), (w2, d2, h), (0, d2, h), (0, 0, h)]))
    # South wall
    parts.append(_idf_surface(
        f"{z2}_Wall-S", "Wall", wall_c, z2, s2,
        "Outdoors", "", "SunExposed", "WindExposed",
        [(0, 0, h), (0, 0, 0), (w2, 0, 0), (w2, 0, h)]))
    # North wall
    parts.append(_idf_surface(
        f"{z2}_Wall-N", "Wall", wall_c, z2, s2,
        "Outdoors", "", "SunExposed", "WindExposed",
        [(w2, d2, h), (w2, d2, 0), (0, d2, 0), (0, d2, h)]))
    # East wall
    parts.append(_idf_surface(
        f"{z2}_Wall-E", "Wall", wall_c, z2, s2,
        "Outdoors", "", "SunExposed", "WindExposed",
        [(w2, 0, h), (w2, 0, 0), (w2, d2, 0), (w2, d2, h)]))
    # West wall (internal, shared with Zone 1)
    parts.append(_idf_surface(
        f"{z2}_Wall-W-Int", "Wall", wall_c, z2, s2,
        "Surface", f"{z1}_Wall-E-Int", "NoSun", "NoWind",
        [(0, shared_d, h), (0, shared_d, 0), (0, 0, 0), (0, 0, h)]))
    # If d2 > d1, exposed portion of west wall
    if d2 > d1:
        parts.append(_idf_surface(
            f"{z2}_Wall-W-Ext", "Wall", wall_c, z2, s2,
            "Outdoors", "", "SunExposed", "WindExposed",
            [(0, d2, h), (0, d2, 0), (0, shared_d, 0), (0, shared_d, h)]))

    output = os.path.abspath(args.output)
    with open(output, "w", encoding="utf-8") as f:
        f.write("\n\n".join(parts) + "\n")

    total_floor = w1 * d1 + w2 * d2
    print(f"=== Create L-Shape ===")
    print(f"  Zone 1:     {z1} ({w1} x {d1} x {h} m)")
    print(f"  Zone 2:     {z2} ({w2} x {d2} x {h} m)")
    print(f"  Total floor: {total_floor:.1f} m2")
    print(f"  Shared wall: {shared_d} x {h} = {shared_d * h:.1f} m2")
    print(f"  Output:     {output}")


def cmd_add_window(args):
    """Add a window to a specified wall surface."""
    parse_idf = _load_idf_helper()
    idf_path = os.path.abspath(args.idf)
    objects = parse_idf(idf_path)

    # Find the target wall
    target = args.wall.lower()
    surfaces = _get_objects_by_type(objects, "BuildingSurface:Detailed")
    wall_data = None
    for s in surfaces:
        sd = extract_surface_data(s)
        if sd["name"].lower() == target:
            wall_data = sd
            break

    if not wall_data:
        print(f"Error: Wall surface '{args.wall}' not found")
        sys.exit(1)

    if wall_data["surface_type"].lower() != "wall":
        print(f"Warning: Surface is type '{wall_data['surface_type']}', not Wall")

    # Compute window vertices on the wall plane
    verts = wall_data["vertices"]
    if len(verts) != 4:
        print(f"Error: Wall must have 4 vertices (has {len(verts)})")
        sys.exit(1)

    # Wall local coordinate system:
    # For UpperLeftCorner+CCW wall: v1=UL, v2=LL, v3=LR, v4=UR
    # U-axis = v3 - v2 (horizontal, left to right from outside)
    # V-axis = v1 - v2 (vertical, bottom to top)
    v1, v2, v3, v4 = verts
    u_vec = (v3[0] - v2[0], v3[1] - v2[1], v3[2] - v2[2])
    v_vec = (v1[0] - v2[0], v1[1] - v2[1], v1[2] - v2[2])
    u_len = vec_length(u_vec)
    v_len = vec_length(v_vec)

    u_hat = vec_normalize(u_vec)
    v_hat = vec_normalize(v_vec)

    win_w = args.width
    win_h = args.height
    sill_h = args.sill_height

    # Check fit
    if win_h + sill_h > v_len:
        print(f"Error: Window height ({win_h}m) + sill ({sill_h}m) > wall height ({v_len:.2f}m)")
        sys.exit(1)
    if win_w > u_len:
        print(f"Error: Window width ({win_w}m) > wall width ({u_len:.2f}m)")
        sys.exit(1)

    # Horizontal offset
    if args.centered or args.offset is None:
        u_offset = (u_len - win_w) / 2
    else:
        u_offset = args.offset

    if u_offset + win_w > u_len:
        print(f"Error: Window extends beyond wall (offset {u_offset}m + width {win_w}m > {u_len:.2f}m)")
        sys.exit(1)

    # Compute window vertices (UL, LL, LR, UR — same winding as wall)
    def _point(u, v):
        return (
            v2[0] + u_hat[0] * u + v_hat[0] * v,
            v2[1] + u_hat[1] * u + v_hat[1] * v,
            v2[2] + u_hat[2] * u + v_hat[2] * v,
        )

    win_verts = [
        _point(u_offset, sill_h + win_h),           # UL
        _point(u_offset, sill_h),                     # LL
        _point(u_offset + win_w, sill_h),             # LR
        _point(u_offset + win_w, sill_h + win_h),    # UR
    ]

    # Generate fenestration text
    win_name = args.name or f"{wall_data['name']}_Window"
    construction = args.construction

    fen_text = _idf_fenestration(
        win_name, "Window", construction, wall_data["name"], win_verts)

    # Append to IDF file
    with open(idf_path, "r", encoding="utf-8", errors="replace") as f:
        content = f.read()

    output = os.path.abspath(args.output)
    with open(output, "w", encoding="utf-8") as f:
        f.write(content)
        f.write("\n\n")
        f.write(fen_text)
        f.write("\n")

    win_area = win_w * win_h
    print(f"=== Add Window ===")
    print(f"  Wall:        {wall_data['name']}")
    print(f"  Window:      {win_name}")
    print(f"  Size:        {win_w} x {win_h} m ({win_area:.2f} m2)")
    print(f"  Sill height: {sill_h} m")
    print(f"  H-offset:    {u_offset:.2f} m from left edge")
    print(f"  Output:      {output}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="EnergyPlus building geometry helper",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    subparsers = parser.add_subparsers(dest="command")

    # list-surfaces
    p_ls = subparsers.add_parser("list-surfaces", help="List building surfaces")
    p_ls.add_argument("idf", help="IDF file path")
    p_ls.add_argument("--zone", help="Filter by zone name (partial match)")
    p_ls.add_argument("--type", help="Filter by surface type (Wall/Floor/Roof/Ceiling)")

    # surface-info
    p_si = subparsers.add_parser("surface-info", help="Detailed surface info")
    p_si.add_argument("idf", help="IDF file path")
    p_si.add_argument("--name", required=True, help="Surface name")

    # scale
    p_sc = subparsers.add_parser("scale", help="Scale zone geometry")
    p_sc.add_argument("idf", help="IDF file path")
    p_sc.add_argument("--zone", required=True, help="Zone name (partial match)")
    p_sc.add_argument("--axis", required=True, help="Axis: X, Y, or Z")
    p_sc.add_argument("--factor", required=True, type=float, help="Scale factor")
    p_sc.add_argument("--output", required=True, help="Output IDF path")

    # set-height
    p_sh = subparsers.add_parser("set-height", help="Set zone ceiling height")
    p_sh.add_argument("idf", help="IDF file path")
    p_sh.add_argument("--zone", required=True, help="Zone name (partial match)")
    p_sh.add_argument("--height", required=True, type=float, help="New height (m)")
    p_sh.add_argument("--output", required=True, help="Output IDF path")

    # move-wall
    p_mw = subparsers.add_parser("move-wall", help="Move wall along normal")
    p_mw.add_argument("idf", help="IDF file path")
    p_mw.add_argument("--surface", required=True, help="Wall surface name")
    p_mw.add_argument("--offset", required=True, type=float,
                      help="Offset in meters (+ = outward)")
    p_mw.add_argument("--output", required=True, help="Output IDF path")

    # summary
    p_sum = subparsers.add_parser("summary", help="Geometry summary by zone")
    p_sum.add_argument("idf", help="IDF file path")

    # create-box
    p_box = subparsers.add_parser("create-box",
                                   help="Create rectangular single-zone geometry")
    p_box.add_argument("--width", required=True, type=float, help="Width in X (m)")
    p_box.add_argument("--depth", required=True, type=float, help="Depth in Y (m)")
    p_box.add_argument("--height", required=True, type=float, help="Height in Z (m)")
    p_box.add_argument("--zone-name", help="Zone name (default: Zone1)")
    p_box.add_argument("--output", required=True, help="Output IDF path")
    p_box.add_argument("--orientation", type=float,
                       help="Building rotation in degrees (default: 0)")
    p_box.add_argument("--origin", help="Zone origin as x,y,z (default: 0,0,0)")
    p_box.add_argument("--wall-construction", help="Wall construction name")
    p_box.add_argument("--floor-construction", help="Floor construction name")
    p_box.add_argument("--roof-construction", help="Roof construction name")

    # create-l-shape
    p_lsh = subparsers.add_parser("create-l-shape",
                                   help="Create L-shaped two-zone geometry")
    p_lsh.add_argument("--width1", required=True, type=float, help="Zone 1 width (m)")
    p_lsh.add_argument("--depth1", required=True, type=float, help="Zone 1 depth (m)")
    p_lsh.add_argument("--width2", required=True, type=float, help="Zone 2 width (m)")
    p_lsh.add_argument("--depth2", required=True, type=float, help="Zone 2 depth (m)")
    p_lsh.add_argument("--height", required=True, type=float, help="Height (m)")
    p_lsh.add_argument("--output", required=True, help="Output IDF path")
    p_lsh.add_argument("--zone-names", help="Comma-separated zone names")
    p_lsh.add_argument("--wall-construction", help="Wall construction name")
    p_lsh.add_argument("--floor-construction", help="Floor construction name")
    p_lsh.add_argument("--roof-construction", help="Roof construction name")

    # add-window
    p_win = subparsers.add_parser("add-window",
                                   help="Add window to a wall surface")
    p_win.add_argument("--idf", required=True, help="Input IDF file")
    p_win.add_argument("--wall", required=True, help="Parent wall surface name")
    p_win.add_argument("--width", required=True, type=float, help="Window width (m)")
    p_win.add_argument("--height", required=True, type=float, help="Window height (m)")
    p_win.add_argument("--sill-height", required=True, type=float,
                       help="Sill height from floor (m)")
    p_win.add_argument("--construction", required=True, help="Window construction name")
    p_win.add_argument("--output", required=True, help="Output IDF path")
    p_win.add_argument("--name", help="Window name (default: auto)")
    p_win.add_argument("--centered", action="store_true",
                       help="Center window horizontally (default)")
    p_win.add_argument("--offset", type=float,
                       help="Horizontal offset from left edge (m)")

    args = parser.parse_args()
    if args.command is None:
        parser.print_help()
        sys.exit(1)

    commands = {
        "list-surfaces": cmd_list_surfaces,
        "surface-info": cmd_surface_info,
        "scale": cmd_scale,
        "set-height": cmd_set_height,
        "move-wall": cmd_move_wall,
        "summary": cmd_summary,
        "create-box": cmd_create_box,
        "create-l-shape": cmd_create_l_shape,
        "add-window": cmd_add_window,
    }
    commands[args.command](args)


if __name__ == "__main__":
    main()
