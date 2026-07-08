#!/usr/bin/env python3
"""
EQ Emulator Mob & Camp Manager — Web Edition
Flask backend: loads pipe-delimited CSV, serves REST API for AG Grid frontend.
"""

import sys
import os
import json
import re
from collections import defaultdict
from pathlib import Path

import pandas as pd
from flask import Flask, request, jsonify, render_template

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
app = Flask(__name__)

CSV_PATH = Path(__file__).parent / "Mobs and Zones.csv"
CSV_SEP = "|"
CSV_ENCODING = "utf-8"
CSV_QUOTE = '"'

# ---------------------------------------------------------------------------
# Global in-memory state
# ---------------------------------------------------------------------------
df: pd.DataFrame | None = None
camps: dict[str, dict[str, str]] = {}          # zone -> {camp_id: camp_name}
camp_assignments: dict[str, str] = {}           # npc_type_id (str) -> camp_id
modified_mobs: set[str] = set()                 # npc_type_ids with unsaved changes
file_path: Path | None = None


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------

def load_csv(path: Path | str | None = None) -> bool:
    """Load the mob CSV into memory and parse camp data."""
    global df, camps, camp_assignments, modified_mobs, file_path

    src = Path(path) if path else CSV_PATH
    if not src.exists():
        print(f"ERROR: File not found: {src}")
        return False

    try:
        df = pd.read_csv(
            src, sep=CSV_SEP, encoding=CSV_ENCODING,
            quotechar=CSV_QUOTE, on_bad_lines="skip",
        )
        file_path = src
    except Exception as e:
        print(f"ERROR loading CSV: {e}")
        return False

    # Convert npc_type_id to string for consistent lookups
    df["npc_type_id"] = df["npc_type_id"].astype(str)

    # Parse existing camps from spawn_group_id / spawn_group_name
    camps = defaultdict(dict)
    camp_assignments = {}
    for _, row in df.iterrows():
        gid = row.get("spawn_group_id")
        gname = row.get("spawn_group_name")
        mob_id = str(row["npc_type_id"])
        zone = str(row.get("zone_short_name", "unknown"))
        if pd.notna(gid) and pd.notna(gname) and mob_id:
            gid_str = str(int(gid)) if isinstance(gid, float) else str(gid)
            camps[zone][gid_str] = str(gname)
            camp_assignments[mob_id] = gid_str

    camps = dict(camps)
    modified_mobs = set()
    print(f"Loaded {len(df):,} rows from {src}, {len(camp_assignments)} camp assignments")
    return True


def save_csv(path: Path | str | None = None) -> bool:
    """Persist current state back to CSV, preserving pipe-delimited format."""
    global df, file_path, modified_mobs

    if df is None:
        return False

    dest = Path(path) if path else file_path
    if dest is None:
        return False

    try:
        # Write spawn_group_id / spawn_group_name back from camp assignments
        for idx, row in df.iterrows():
            mob_id = str(row["npc_type_id"])
            zone = str(row.get("zone_short_name", "unknown"))
            if mob_id in camp_assignments:
                cid = camp_assignments[mob_id]
                cname = camps.get(zone, {}).get(cid, "")
                df.at[idx, "spawn_group_id"] = cid
                df.at[idx, "spawn_group_name"] = cname
            else:
                # Clear camp fields for mobs that were unassigned
                if mob_id in modified_mobs:
                    df.at[idx, "spawn_group_id"] = ""
                    df.at[idx, "spawn_group_name"] = ""

        df.to_csv(dest, sep=CSV_SEP, index=False, encoding=CSV_ENCODING, quotechar=CSV_QUOTE)
        file_path = dest
        modified_mobs = set()
        return True
    except Exception as e:
        print(f"ERROR saving CSV: {e}")
        return False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

COLUMNS = [
    "npc_type_id", "mob_name", "mob_level", "loottable_id",
    "spawn_group_id", "spawn_group_name", "spawn2_id",
    "x", "y", "z", "heading", "respawntime", "spawn_chance",
    "zone_id", "zone_short_name", "zone_name", "expansion",
]

EDITABLE_COLUMNS = [
    "mob_name", "mob_level", "x", "y", "z", "heading",
    "respawntime", "spawn_chance",
]

DISPLAY_COLUMNS = COLUMNS + ["camp"]  # "camp" is computed


def _row_to_dict(idx: int, row: pd.Series) -> dict:
    """Convert a DataFrame row to a JSON-safe dict with computed camp field."""
    d = {}
    for col in COLUMNS:
        val = row.get(col)
        if pd.isna(val):
            d[col] = None
        elif isinstance(val, (int, float)):
            d[col] = val
        else:
            d[col] = str(val)
    # Ensure npc_type_id is string
    d["npc_type_id"] = str(row["npc_type_id"])

    # Computed camp field
    mob_id = d["npc_type_id"]
    cid = camp_assignments.get(mob_id, "")
    zone = d.get("zone_short_name") or "unknown"
    cname = camps.get(zone, {}).get(cid, "") if cid else ""
    d["camp"] = f"{cname} ({cid})" if cid else ""
    d["camp_id"] = cid
    d["camp_name"] = cname
    return d


def _filter_df(params: dict):
    """Apply filters to a copy of df; return filtered DataFrame."""
    if df is None:
        return pd.DataFrame()

    f = df.copy()

    # Text search
    search = (params.get("search") or "").strip().lower()
    if search:
        mask = (
            f["mob_name"].astype(str).str.lower().str.contains(search, na=False)
            | f["zone_name"].astype(str).str.lower().str.contains(search, na=False)
            | f["zone_short_name"].astype(str).str.lower().str.contains(search, na=False)
            | f["npc_type_id"].astype(str).str.contains(search, na=False)
            | f["spawn_group_name"].astype(str).str.lower().str.contains(search, na=False)
        )
        f = f[mask]

    # Zone filter
    zone = (params.get("zone") or "").strip()
    if zone:
        f = f[f["zone_short_name"].astype(str) == zone]

    # Level range
    try:
        lmin = int(params.get("level_min", 0))
    except (ValueError, TypeError):
        lmin = 0
    try:
        lmax = int(params.get("level_max", 999))
    except (ValueError, TypeError):
        lmax = 999
    if lmin > 0 or lmax < 999:
        lvl = pd.to_numeric(f["mob_level"], errors="coerce").fillna(0)
        f = f[(lvl >= lmin) & (lvl <= lmax)]

    # Named only
    if params.get("named") in ("true", "1", True):
        f = f[
            f["mob_name"].astype(str).str.contains(
                "|".join(["#", "named", "boss", "guardian"]),
                case=False, na=False,
            )
        ]

    # Camp assignment filter
    has_camp = params.get("has_camp")
    if has_camp == "1":
        f = f[f["npc_type_id"].astype(str).isin(camp_assignments.keys())]
    elif has_camp == "0":
        f = f[~f["npc_type_id"].astype(str).isin(camp_assignments.keys())]

    # Specific camp filter
    camp_id = (params.get("camp_id") or "").strip()
    if camp_id:
        f = f[f["npc_type_id"].astype(str).map(
            lambda mid: camp_assignments.get(mid, "") == camp_id
        )]

    return f


# ---------------------------------------------------------------------------
# API Routes
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/mobs", methods=["GET"])
def api_mobs():
    """Return filtered mob data. Supports server-side pagination if
    page/page_size are provided; otherwise returns all rows."""
    if df is None:
        return jsonify({"error": "No data loaded"}), 500

    filtered = _filter_df(request.args)

    # Sort by npc_type_id for consistent ordering
    filtered = filtered.sort_values("npc_type_id")

    total = len(filtered)

    # Pagination (optional — client may request all)
    page = request.args.get("page", type=int)
    page_size = request.args.get("page_size", type=int)
    if page is not None and page_size is not None:
        start = (page - 1) * page_size
        end = start + page_size
        page_data = filtered.iloc[start:end]
    else:
        page_data = filtered

    rows = [_row_to_dict(idx, row) for idx, row in page_data.iterrows()]
    return jsonify({"total": total, "rows": rows})


@app.route("/api/mobs/<mob_id>", methods=["GET"])
def api_mob_get(mob_id):
    """Get a single mob by npc_type_id."""
    if df is None:
        return jsonify({"error": "No data loaded"}), 500

    match = df[df["npc_type_id"].astype(str) == str(mob_id)]
    if match.empty:
        return jsonify({"error": "Mob not found"}), 404

    row = _row_to_dict(match.index[0], match.iloc[0])
    row["_df_index"] = int(match.index[0])
    return jsonify(row)


@app.route("/api/mobs/<mob_id>", methods=["PUT"])
def api_mob_update(mob_id):
    """Update fields on a single mob. Body: {field: value, ...}"""
    global modified_mobs
    if df is None:
        return jsonify({"error": "No data loaded"}), 500

    match = df[df["npc_type_id"].astype(str) == str(mob_id)]
    if match.empty:
        return jsonify({"error": "Mob not found"}), 404

    body = request.get_json(silent=True)
    if not body:
        return jsonify({"error": "No JSON body"}), 400

    idx = match.index[0]
    updated_fields = []
    for field, value in body.items():
        if field in COLUMNS:
            df.at[idx, field] = value
            updated_fields.append(field)
            modified_mobs.add(str(mob_id))

    return jsonify({
        "ok": True,
        "updated": updated_fields,
        "mob": _row_to_dict(idx, df.iloc[idx]),
    })


@app.route("/api/zones", methods=["GET"])
def api_zones():
    if df is None:
        return jsonify([])
    zones = sorted(df["zone_short_name"].dropna().unique().tolist())
    return jsonify([z for z in zones if str(z) != "nan"])


@app.route("/api/camps", methods=["GET"])
def api_camps():
    """Return all camps as nested zone -> camps list."""
    result = []
    for zone_name, zone_camps in sorted(camps.items()):
        camp_list = []
        for cid, cname in sorted(zone_camps.items()):
            # Count mobs in this camp
            count = sum(
                1 for mid, ac in camp_assignments.items()
                if ac == cid
            )
            camp_list.append({"id": cid, "name": cname, "mob_count": count})
        result.append({"zone": zone_name, "camps": camp_list})
    return jsonify(result)


@app.route("/api/camps/assign", methods=["POST"])
def api_camps_assign():
    """Assign mobs to a camp. Body: {mob_ids: [...], camp_id: str, camp_name: str, zone: str}"""
    global modified_mobs
    body = request.get_json(silent=True)
    if not body:
        return jsonify({"error": "No JSON body"}), 400

    mob_ids = body.get("mob_ids", [])
    camp_id = str(body.get("camp_id", ""))
    camp_name = str(body.get("camp_name", ""))
    zone = str(body.get("zone", "unknown"))

    if not mob_ids or not camp_id or not camp_name:
        return jsonify({"error": "mob_ids, camp_id, camp_name required"}), 400

    # Ensure camps dict has the zone and camp
    camps.setdefault(zone, {})[camp_id] = camp_name

    assigned = 0
    for mid in mob_ids:
        mid = str(mid)
        # Verify mob exists and is in the right zone
        match = df[df["npc_type_id"].astype(str) == mid]
        if match.empty:
            continue
        mob_zone = str(match.iloc[0].get("zone_short_name", "unknown"))
        if mob_zone != zone and zone != "unknown":
            continue

        if camp_assignments.get(mid) != camp_id:
            camp_assignments[mid] = camp_id
            modified_mobs.add(mid)
            assigned += 1

    return jsonify({"ok": True, "assigned": assigned})


@app.route("/api/camps/remove", methods=["POST"])
def api_camps_remove():
    """Remove camp assignments from mobs. Body: {mob_ids: [...]}"""
    global modified_mobs
    body = request.get_json(silent=True)
    if not body:
        return jsonify({"error": "No JSON body"}), 400

    mob_ids = body.get("mob_ids", [])
    removed = 0
    for mid in mob_ids:
        mid = str(mid)
        if mid in camp_assignments:
            del camp_assignments[mid]
            modified_mobs.add(mid)
            removed += 1

    return jsonify({"ok": True, "removed": removed})


@app.route("/api/camps/<camp_id>", methods=["DELETE"])
def api_camp_delete(camp_id):
    """Delete a camp entirely and unassign all its mobs."""
    global modified_mobs
    # Find which zone this camp belongs to
    for zone_name, zone_camps in camps.items():
        if camp_id in zone_camps:
            # Unassign all mobs
            for mid, cid in list(camp_assignments.items()):
                if cid == camp_id:
                    del camp_assignments[mid]
                    modified_mobs.add(mid)
            del zone_camps[camp_id]
            return jsonify({"ok": True, "deleted": camp_id})

    return jsonify({"error": "Camp not found"}), 404


@app.route("/api/camps/<camp_id>", methods=["PUT"])
def api_camp_rename(camp_id):
    """Rename a camp. Body: {name: str}"""
    body = request.get_json(silent=True)
    new_name = (body or {}).get("name", "").strip()
    if not new_name:
        return jsonify({"error": "name required"}), 400

    for zone_camps in camps.values():
        if camp_id in zone_camps:
            zone_camps[camp_id] = new_name
            return jsonify({"ok": True, "name": new_name})

    return jsonify({"error": "Camp not found"}), 404


@app.route("/api/stats", methods=["GET"])
def api_stats():
    """Return summary statistics."""
    if df is None:
        return jsonify({"error": "No data"}), 500

    total = len(df)
    assigned = len(camp_assignments)
    zones = df["zone_short_name"].dropna().nunique()
    zone_dist = (
        df["zone_short_name"]
        .value_counts()
        .head(20)
        .to_dict()
    )
    level_dist = (
        pd.to_numeric(df["mob_level"], errors="coerce")
        .dropna()
        .value_counts()
        .sort_index()
        .to_dict()
    )
    # Convert numpy ints to regular ints
    level_dist = {int(k): int(v) for k, v in level_dist.items()}
    zone_dist = {str(k): int(v) for k, v in zone_dist.items()}

    return jsonify({
        "total_mobs": int(total),
        "total_zones": int(zones),
        "camp_assignments": assigned,
        "coverage_pct": round(assigned / total * 100, 1) if total else 0,
        "dirty_count": len(modified_mobs),
        "top_zones": zone_dist,
        "level_distribution": level_dist,
    })


@app.route("/api/save", methods=["POST"])
def api_save():
    """Persist to CSV. Returns count of saved changes."""
    if df is None:
        return jsonify({"error": "No data loaded"}), 500

    dirty = len(modified_mobs)
    ok = save_csv()
    if ok:
        return jsonify({"ok": True, "saved_changes": dirty, "path": str(file_path)})
    return jsonify({"error": "Save failed"}), 500


@app.route("/api/reload", methods=["POST"])
def api_reload():
    """Discard unsaved changes and reload from disk."""
    ok = load_csv(file_path)
    if ok:
        return jsonify({"ok": True, "rows": len(df)})
    return jsonify({"error": "Reload failed"}), 500


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

def main():
    import argparse
    parser = argparse.ArgumentParser(description="EQ Mob Manager Web Server")
    parser.add_argument("--csv", type=str, default=None, help="Path to CSV file")
    parser.add_argument("--port", type=int, default=5000, help="Server port")
    parser.add_argument("--debug", action="store_true", help="Debug mode")
    args = parser.parse_args()

    path = args.csv or CSV_PATH
    if not load_csv(path):
        print("Failed to load CSV. Starting with empty dataset.")
    else:
        print(f"Ready. Open http://localhost:{args.port} in your browser.")

    app.run(host="127.0.0.1", port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
