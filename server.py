#!/usr/bin/env python3
"""
EQ Emulator Mob & Camp Manager — Web Edition (v3)
Fast: CSV preloaded at startup, vectorized pandas filtering, bulk JSON serialization.
"""

import sys
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
# In-memory state (loaded at startup)
# ---------------------------------------------------------------------------
df: pd.DataFrame = None          # full DataFrame
df_lower: dict[str, pd.Series] = {}  # lowercase precomputed text columns
file_path: Path | None = None
zones_list: list[str] = []
camps_cache: list[dict] = []

ALL_COLUMNS = [
    "npc_type_id", "mob_name", "mob_level", "loottable_id",
    "spawn_group_id", "spawn_group_name", "spawn2_id",
    "x", "y", "z", "heading", "respawntime", "spawn_chance",
    "zone_id", "zone_short_name", "zone_name", "expansion",
    "CampName", "campId",
]

# Columns to include in API responses (skip heavy internal fields)
API_COLUMNS = [
    "npc_type_id", "mob_name", "mob_level",
    "zone_short_name", "zone_name",
    "CampName", "campId",
    "x", "y", "z", "heading",
    "spawn_chance", "respawntime",
    "spawn_group_id", "spawn_group_name",
    "loottable_id", "spawn2_id", "zone_id", "expansion",
]

# =========================================================================
# Startup — load once
# =========================================================================
def load_all():
    global df, df_lower, file_path, zones_list, camps_cache

    src = CSV_PATH
    if not src.exists():
        print(f"ERROR: CSV not found: {src}")
        return False

    print(f"Loading {src} …", end=" ", flush=True)
    df = pd.read_csv(
        src, sep=CSV_SEP, encoding=CSV_ENCODING,
        quotechar=CSV_QUOTE, on_bad_lines="skip",
        dtype={"CampName": object, "campId": object},
    )
    file_path = src

    # Normalize types once
    df["npc_type_id"] = df["npc_type_id"].astype(str)
    for col in ["CampName", "campId"]:
        if col in df.columns:
            df[col] = df[col].astype(object).fillna("")

    # Precompute lowercase text columns (avoids .astype(str).str.lower() on every filter)
    df_lower = {}
    for col in ["mob_name", "zone_name", "zone_short_name", "CampName", "campId", "npc_type_id"]:
        if col in df.columns:
            df_lower[col] = df[col].astype(str).str.lower()

    # Precompute has_camp mask
    df_lower["_has_camp"] = df["CampName"].astype(str).str.strip().ne("")

    # Cache zones
    zones_list = sorted(
        z for z in df["zone_short_name"].dropna().unique().tolist()
        if str(z) != "nan"
    )

    # Cache camps
    camps_cache = _build_camps()

    print(f"done ({len(df):,} rows, {len(zones_list)} zones, {len(camps_cache)} camp zones)")
    return True


def _build_camps():
    """Build camp cache from CampName/campId columns."""
    if "campId" not in df.columns:
        return []
    mask = df_lower["_has_camp"]
    camp_rows = df[mask].copy()
    if camp_rows.empty:
        return []

    camp_rows["campId"] = camp_rows["campId"].astype(str).str.strip()
    camp_rows["CampName"] = camp_rows["CampName"].astype(str).str.strip()

    result = []
    for zone_name, zg in camp_rows.groupby("zone_short_name"):
        camp_list = []
        for cid, cg in zg.groupby("campId"):
            camp_list.append({
                "id": cid,
                "name": cg["CampName"].iloc[0],
                "mob_count": len(cg),
            })
        result.append({
            "zone": str(zone_name),
            "camps": sorted(camp_list, key=lambda x: x["name"]),
        })
    return sorted(result, key=lambda x: x["zone"])


def save_df() -> bool:
    if df is None or file_path is None:
        return False
    df.to_csv(file_path, sep=CSV_SEP, index=False,
              encoding=CSV_ENCODING, quotechar=CSV_QUOTE)
    return True


def reload_all():
    global df, df_lower, zones_list, camps_cache
    df = None
    df_lower = {}
    zones_list = []
    camps_cache = []
    return load_all()


# =========================================================================
# Fast filtering — vectorized, no copies until final step
# =========================================================================
def fast_filter(params: dict) -> pd.DataFrame:
    """Apply filters using precomputed lowercase columns. Returns filtered DataFrame."""
    # Start with all rows, build a boolean mask
    mask = pd.Series(True, index=df.index)

    # Text search
    search = (params.get("search") or "").strip().lower()
    if search:
        search_mask = pd.Series(False, index=df.index)
        for col in ["mob_name", "zone_name", "zone_short_name", "CampName", "campId"]:
            if col in df_lower:
                search_mask |= df_lower[col].str.contains(search, na=False, regex=False)
        # npc_type_id is exact (not lowercase)
        search_mask |= df["npc_type_id"].astype(str).str.contains(search, na=False, regex=False)
        mask &= search_mask

    # Zone
    zone = (params.get("zone") or "").strip()
    if zone:
        mask &= df_lower.get("zone_short_name", df["zone_short_name"].astype(str).str.lower()) == zone.lower()

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
        lvl = pd.to_numeric(df["mob_level"], errors="coerce").fillna(0)
        mask &= (lvl >= lmin) & (lvl <= lmax)

    # Named only
    if params.get("named") in ("true", "1", True):
        mask &= df_lower.get("mob_name", df["mob_name"].astype(str).str.lower()).str.contains(
            "|".join(["#", "named", "boss", "guardian"]),
            case=False, na=False, regex=True,
        )

    # Has camp
    has_camp = params.get("has_camp")
    if has_camp == "1":
        mask &= df_lower["_has_camp"]
    elif has_camp == "0":
        mask &= ~df_lower["_has_camp"]

    # Specific camp
    camp_id = (params.get("camp_id") or "").strip()
    if camp_id:
        mask &= df["campId"].astype(str).str.strip() == camp_id

    # Apply mask and sort
    return df.loc[mask].sort_values("npc_type_id")


# =========================================================================
# Fast JSON serialization — bulk to_dict
# =========================================================================
def rows_to_json(filtered: pd.DataFrame, start: int, end: int) -> list[dict]:
    """Convert a slice of filtered DataFrame to list of JSON-safe dicts."""
    chunk = filtered.iloc[start:end][API_COLUMNS]
    # Replace NaN with None so JSON outputs null (not NaN which is invalid JSON)
    chunk = chunk.where(chunk.notna(), None)
    records = chunk.to_dict(orient="records")
    # Add _idx from original index, clean up types
    idxs = chunk.index.tolist()
    for i, rec in enumerate(records):
        rec["_idx"] = int(idxs[i])
        rec["npc_type_id"] = str(rec.get("npc_type_id", ""))
        # Empty strings for text fields with None
        for fld in ["CampName", "campId"]:
            if rec.get(fld) is None:
                rec[fld] = ""
    return records


# =========================================================================
# API Routes
# =========================================================================

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/mobs", methods=["GET"])
def api_mobs():
    if df is None:
        return jsonify({"error": "Data not loaded"}), 500

    params = dict(request.args)
    has_filters = any(
        params.get(k) for k in ["search", "zone", "camp_id"]
    ) or params.get("level_min", "0") != "0" or params.get("level_max", "100") != "100" \
      or params.get("named") or params.get("has_camp")

    if not has_filters:
        return jsonify({
            "rows": [], "total": 0,
            "hint": "Type a search term or select a filter to begin.",
            "grand_total": len(df),
        })

    filtered = fast_filter(params)
    total = len(filtered)

    page = max(1, request.args.get("page", type=int, default=1))
    page_size = min(max(1, request.args.get("page_size", type=int, default=500)), 2000)
    start = (page - 1) * page_size
    rows = rows_to_json(filtered, start, start + page_size)

    return jsonify({"rows": rows, "total": total, "page": page, "page_size": page_size, "grand_total": len(df)})


@app.route("/api/mobs/<mob_id>", methods=["GET"])
def api_mob_get(mob_id):
    if df is None:
        return jsonify({"error": "Data not loaded"}), 500
    match = df[df["npc_type_id"].astype(str) == str(mob_id)]
    if match.empty:
        return jsonify({"error": "Not found"}), 404
    rows = rows_to_json(match, 0, 1)
    return jsonify(rows[0])


@app.route("/api/mobs/<mob_id>", methods=["PUT"])
def api_mob_update(mob_id):
    if df is None:
        return jsonify({"error": "Data not loaded"}), 500
    match = df[df["npc_type_id"].astype(str) == str(mob_id)]
    if match.empty:
        return jsonify({"error": "Not found"}), 404

    body = request.get_json(silent=True)
    if not body:
        return jsonify({"error": "No JSON body"}), 400

    idx = match.index[0]
    updated = []
    for field, value in body.items():
        if field in ALL_COLUMNS:
            df.at[idx, field] = value
            # Update lowercase cache if this is a text column
            if field in df_lower:
                df_lower[field].at[idx] = str(value).lower() if value else ""
            if field == "CampName":
                df_lower["_has_camp"].at[idx] = bool(str(value).strip())
            updated.append(field)

    rows = rows_to_json(df.loc[[idx]], 0, 1)
    return jsonify({"ok": True, "updated": updated, "mob": rows[0]})


@app.route("/api/camps", methods=["GET"])
def api_camps():
    return jsonify(camps_cache)


@app.route("/api/suggest", methods=["GET"])
def api_suggest():
    """Fast autocomplete — returns top matches across names, zones, camps, IDs."""
    if df is None:
        return jsonify([])

    q = (request.args.get("q") or "").strip().lower()
    if len(q) < 1:
        return jsonify([])

    suggestions = []
    seen = set()

    def add(text, kind, secondary=""):
        key = (text.lower(), kind)
        if key in seen:
            return
        seen.add(key)
        suggestions.append({"text": str(text), "kind": kind, "secondary": str(secondary)})

    # Match mob names (most useful)
    mask = df_lower["mob_name"].str.contains(q, na=False, regex=False)
    matches = df.loc[mask, ["mob_name", "zone_short_name", "npc_type_id"]].drop_duplicates("mob_name")
    for _, r in matches.head(8).iterrows():
        add(r["mob_name"], "mob", str(r["zone_short_name"]))

    # Match zone short names
    mask = df_lower["zone_short_name"].str.contains(q, na=False, regex=False)
    matches = df.loc[mask, "zone_short_name"].dropna().unique()[:5]
    for z in matches:
        add(z, "zone")

    # Match zone full names
    mask = df_lower["zone_name"].str.contains(q, na=False, regex=False)
    matches = df.loc[mask, ["zone_name", "zone_short_name"]].drop_duplicates("zone_name").head(3)
    for _, r in matches.iterrows():
        add(r["zone_name"], "zone_full", str(r["zone_short_name"]))

    # Match camp names
    mask = df_lower["CampName"].str.contains(q, na=False, regex=False)
    matches = df.loc[mask, ["CampName", "campId"]].drop_duplicates("CampName").head(4)
    for _, r in matches.iterrows():
        if r["CampName"] and str(r["CampName"]).strip():
            add(r["CampName"], "camp", str(r.get("campId", "")))

    # Match by NPC ID (exact prefix)
    mask = df["npc_type_id"].astype(str).str.startswith(q, na=False)
    matches = df.loc[mask, ["npc_type_id", "mob_name"]].drop_duplicates("npc_type_id").head(3)
    for _, r in matches.iterrows():
        add(str(r["npc_type_id"]), "id", str(r["mob_name"]))

    return jsonify(suggestions[:12])


@app.route("/api/zones", methods=["GET"])
def api_zones():
    return jsonify(zones_list)


@app.route("/api/stats", methods=["GET"])
def api_stats():
    if df is None:
        return jsonify({"error": "No data"}), 500
    total = len(df)
    assigned = int(df_lower.get("_has_camp", pd.Series(False)).sum())
    top_zones = {str(k): int(v) for k, v in df["zone_short_name"].value_counts().head(10).to_dict().items()}
    return jsonify({
        "total_mobs": total,
        "total_zones": len(zones_list),
        "camp_assigned_rows": assigned,
        "coverage_pct": round(assigned / total * 100, 1) if total else 0,
        "top_zones": top_zones,
    })


@app.route("/api/save", methods=["POST"])
def api_save():
    # Rebuild caches after save
    if save_df():
        reload_all()
        return jsonify({"ok": True})
    return jsonify({"error": "Save failed"}), 500


@app.route("/api/reload", methods=["POST"])
def api_reload():
    if reload_all():
        return jsonify({"ok": True, "rows": len(df)})
    return jsonify({"error": "Reload failed"}), 500


# =========================================================================
# Startup
# =========================================================================
def main():
    import argparse
    parser = argparse.ArgumentParser(description="EQ Mob Manager")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--debug", action="store_true")
    args = parser.parse_args()

    if not load_all():
        print("WARNING: Starting without data. API calls will fail until data is loaded.")

    print(f"Ready. Open http://localhost:{args.port}")
    app.run(host="127.0.0.1", port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
