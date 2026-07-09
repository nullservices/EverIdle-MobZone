/**
 * EQ Mob & Camp Manager — Frontend (v2)
 * Search-first design: grid starts empty, data loads only on search/filter.
 * AG Grid Community for virtual scrolling + inline editing.
 */

// =========================================================================
// State
// =========================================================================
let gridApi = null;
let gridColumnApi = null;
let selectedCamp = null;
let debounceTimer = null;
let suggestTimer = null;
let activeSuggestionIdx = -1;
let suggestions = [];
const DEBOUNCE_MS = 300;
const SUGGEST_MS = 150;

// =========================================================================
// AG Grid Column Definitions
// =========================================================================
const columnDefs = [
  {
    field: "npc_type_id", headerName: "ID", width: 90,
    pinned: "left", editable: false, filter: true, sort: "asc",
  },
  {
    field: "mob_name", headerName: "Name", width: 210,
    editable: true, filter: true,
  },
  {
    field: "mob_level", headerName: "Lvl", width: 60,
    editable: true, type: "numericColumn", filter: true,
    cellClass: "cell-center",
  },
  {
    field: "zone_short_name", headerName: "Zone", width: 130,
    filter: true,
  },
  {
    field: "CampName", headerName: "Camp Name", width: 180,
    editable: true, filter: true,
    cellClass: "cell-camp",
    cellStyle: { fontWeight: 500 },
  },
  {
    field: "campId", headerName: "Camp ID", width: 170,
    editable: true, filter: true,
    cellClass: "cell-camp",
  },
  {
    field: "zone_name", headerName: "Zone Name", width: 170, filter: true,
  },
  {
    field: "x", headerName: "X", width: 72,
    editable: true, type: "numericColumn",
    valueFormatter: p => p.value != null ? Number(p.value).toFixed(1) : "",
  },
  {
    field: "y", headerName: "Y", width: 72,
    editable: true, type: "numericColumn",
    valueFormatter: p => p.value != null ? Number(p.value).toFixed(1) : "",
  },
  {
    field: "z", headerName: "Z", width: 72,
    editable: true, type: "numericColumn",
    valueFormatter: p => p.value != null ? Number(p.value).toFixed(1) : "",
  },
  {
    field: "heading", headerName: "Head", width: 64,
    editable: true, type: "numericColumn",
  },
  {
    field: "spawn_chance", headerName: "Spawn%", width: 72,
    editable: true, type: "numericColumn",
  },
  {
    field: "respawntime", headerName: "Respawn", width: 80,
    editable: true, type: "numericColumn",
  },
  {
    field: "spawn_group_id", headerName: "Group ID", width: 90, hide: true,
  },
  {
    field: "spawn_group_name", headerName: "Group Name", width: 140, hide: true,
  },
  {
    field: "loottable_id", headerName: "Loot ID", width: 70, hide: true,
  },
  {
    field: "spawn2_id", headerName: "Spawn2", width: 70, hide: true,
  },
  {
    field: "zone_id", headerName: "ZoneID", width: 60, hide: true,
  },
  {
    field: "expansion", headerName: "Exp", width: 50, hide: true,
  },
];

const defaultColDef = {
  resizable: true,
  sortable: true,
  suppressMenu: false,
};

// =========================================================================
// Init
// =========================================================================
const mapCache = {};
let mapPopupTimer = null;
let currentMapZone = null;

document.addEventListener("DOMContentLoaded", () => {
  initGrid();
  loadZones();
  loadCamps();
  loadStats();
  bindEvents();
  bindKeyboardShortcuts();
  restoreTheme();
});

function initGrid() {
  const gridOptions = {
    columnDefs,
    defaultColDef,
    rowModelType: "clientSide",
    rowData: [],
    enableCellTextSelection: true,
    rowSelection: "multiple",
    suppressRowClickSelection: false,

    onCellValueChanged: onCellEdited,
    onSelectionChanged: onSelectionChanged,
    onGridReady: (params) => {
      gridApi = params.api;
      gridColumnApi = params.columnApi;
      // Start empty — user must search
      gridApi.showNoRowsOverlay();
      // Wire up map hover
      bindMapPopupEvents();
    },

    getRowId: (params) => String(params.data._idx),
    overlayLoadingTemplate: '<div class="grid-overlay"><div class="spinner"></div><span>Loading…</span></div>',
    overlayNoRowsTemplate: `
      <div class="grid-overlay grid-hint">
        <div class="hint-icon">🔍</div>
        <div class="hint-title">Search to Begin</div>
        <div class="hint-text">Type a mob name, zone, or NPC ID above to load data.</div>
        <div class="hint-text hint-sub">Or select a zone / camp from the sidebar.</div>
      </div>`,
  };

  const gridDiv = document.getElementById("grid-container");
  gridDiv.style.height = "100%";
  gridDiv.style.width = "100%";
  new agGrid.Grid(gridDiv, gridOptions);
}

// =========================================================================
// Data Loading (search-first)
// =========================================================================
async function loadData() {
  if (!gridApi) return;

  const params = buildFilterParams();

  // Require at least one filter to fetch
  if (Object.keys(params).length === 0) {
    gridApi.setGridOption("rowData", []);
    gridApi.showNoRowsOverlay();
    updateStatus("Type a search term or select a filter to begin", "");
    return;
  }

  showLoading("Searching…");

  const qs = new URLSearchParams(params).toString();
  try {
    const res = await fetch(`/api/mobs?${qs}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const json = await res.json();

    gridApi.setGridOption("rowData", json.rows);
    hideLoading();

    if (json.rows.length === 0) {
      gridApi.showNoRowsOverlay();
    }

    const filterDesc = Object.keys(params).length > 0 ? "(filtered)" : "";
    updateStatus(
      `Showing ${json.total.toLocaleString()} of ${json.grand_total.toLocaleString()} mobs ${filterDesc}`,
      json.total > 0 ? `${json.total.toLocaleString()} results` : ""
    );
  } catch (err) {
    hideLoading();
    toast(`Error: ${err.message}`, "error");
    updateStatus("Error loading data", "");
  }
}

function buildFilterParams() {
  const params = {};

  const search = document.getElementById("search-input").value.trim();
  if (search) params.search = search;

  const zone = document.getElementById("filter-zone").value;
  if (zone) params.zone = zone;

  const lmin = document.getElementById("filter-level-min").value;
  if (lmin && lmin !== "0") params.level_min = lmin;
  const lmax = document.getElementById("filter-level-max").value;
  if (lmax && lmax !== "100") params.level_max = lmax;

  const hasCamp = document.getElementById("filter-has-camp").value;
  if (hasCamp) params.has_camp = hasCamp;

  if (document.getElementById("filter-named").checked) params.named = "1";

  if (selectedCamp && selectedCamp.camp_id) {
    params.camp_id = selectedCamp.camp_id;
  }

  return params;
}

// =========================================================================
// Filter Events
// =========================================================================
function onFilterChange(fromSuggestion) {
  // Show suggestions as user types
  clearTimeout(suggestTimer);
  suggestTimer = setTimeout(fetchSuggestions, SUGGEST_MS);

  // Only auto-search for non-text filter changes (zone dropdown, checkboxes, etc.)
  // Text search fires on Enter or suggestion selection
  if (fromSuggestion) {
    hideSuggestions();
    doSearch();
  }
}

function onSearchKeydown(e) {
  // Enter in search box triggers search
  if (e.key === "Enter") {
    // If suggestions are visible and one is highlighted, select it
    const dropdown = document.getElementById("suggestions-dropdown");
    if (!dropdown.classList.contains("hidden") && activeSuggestionIdx >= 0) {
      e.preventDefault();
      selectSuggestion(activeSuggestionIdx);
      return;
    }
    // Otherwise, trigger search with whatever is typed
    e.preventDefault();
    hideSuggestions();
    doSearch();
  }
}

function doSearch() {
  const search = document.getElementById("search-input").value.trim();
  const zone = document.getElementById("filter-zone").value;
  const hasFilters = search || zone ||
    document.getElementById("filter-has-camp").value ||
    document.getElementById("filter-named").checked ||
    document.getElementById("filter-level-min").value !== "0" ||
    document.getElementById("filter-level-max").value !== "100" ||
    selectedCamp;

  if (!hasFilters) {
    if (gridApi) {
      gridApi.setGridOption("rowData", []);
      gridApi.showNoRowsOverlay();
      updateStatus("Type a search term or select a filter to begin", "");
      document.getElementById("status-right").textContent = "";
    }
    return;
  }
  loadData();
}

// =========================================================================
// Autocomplete / Suggestions
// =========================================================================
async function fetchSuggestions() {
  const q = document.getElementById("search-input").value.trim();
  if (!q || q.length < 1) {
    hideSuggestions();
    return;
  }

  try {
    const res = await fetch(`/api/suggest?q=${encodeURIComponent(q)}`);
    suggestions = await res.json();
    renderSuggestions(q);
  } catch (e) {
    hideSuggestions();
  }
}

function renderSuggestions(query) {
  const dropdown = document.getElementById("suggestions-dropdown");
  if (!suggestions.length) {
    hideSuggestions();
    return;
  }

  const qLower = query.toLowerCase();
  dropdown.innerHTML = "";

  // Group by kind
  const kindLabels = { mob: "Mob", zone: "Zone", zone_full: "Zone", camp: "Camp", id: "NPC ID" };
  const kindIcons = { mob: "🐺", zone: "🗺️", zone_full: "🗺️", camp: "🏕️", id: "🔢" };

  suggestions.forEach((s, i) => {
    const item = document.createElement("div");
    item.className = "suggestion-item";

    // Highlight matching portion
    const idx = s.text.toLowerCase().indexOf(qLower);
    let displayed = escHtml(s.text);
    if (idx >= 0) {
      displayed =
        escHtml(s.text.slice(0, idx)) +
        `<span class="sug-highlight">${escHtml(s.text.slice(idx, idx + query.length))}</span>` +
        escHtml(s.text.slice(idx + query.length));
    }

    const secondary = s.secondary ? ` (${escHtml(s.secondary)})` : "";
    item.innerHTML = `
      <span class="sug-text">${kindIcons[s.kind] || ""} ${displayed}${secondary}</span>
      <span class="sug-type">${kindLabels[s.kind] || s.kind}</span>
    `;

    item.addEventListener("mousedown", (e) => {
      e.preventDefault();
      selectSuggestion(i);
    });
    item.addEventListener("mouseenter", () => highlightSuggestion(i));

    dropdown.appendChild(item);
  });

  activeSuggestionIdx = -1;
  dropdown.classList.remove("hidden");
}

function highlightSuggestion(idx) {
  const items = document.querySelectorAll(".suggestion-item");
  items.forEach((el, i) => el.classList.toggle("active", i === idx));
  activeSuggestionIdx = idx;
}

function selectSuggestion(idx) {
  if (idx < 0 || idx >= suggestions.length) return;
  const s = suggestions[idx];
  document.getElementById("search-input").value = s.text;
  hideSuggestions();
  doSearch();
}

function hideSuggestions() {
  document.getElementById("suggestions-dropdown").classList.add("hidden");
  suggestions = [];
  activeSuggestionIdx = -1;
}

// =========================================================================
// Inline Editing
// =========================================================================
let saveDebounce = null;
const SAVE_DEBOUNCE_MS = 400;

async function onCellEdited(event) {
  const { data, colDef, newValue, oldValue } = event;
  if (newValue === oldValue) return;

  const field = colDef.field;

  // If multiple rows selected, apply to all
  const selectedRows = gridApi.getSelectedRows();
  if (selectedRows.length > 1) {
    // Update the current cell's data immediately so the grid doesn't revert
    data[field] = newValue;
    gridApi.applyTransaction({ update: [data] });

    // Apply to all selected rows
    const val = newValue;
    let done = 0, failed = 0;
    for (const row of selectedRows) {
      if (row[field] === val) { done++; continue; }
      try {
        const res = await fetch(`/api/mobs/${row.npc_type_id}`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ [field]: val }),
        });
        if (res.ok) {
          row[field] = val;
          done++;
        } else { failed++; }
      } catch (e) { failed++; }
    }

    // Refresh grid to show all changes
    gridApi.applyTransaction({ update: selectedRows });
    clearTimeout(saveDebounce);
    saveDebounce = setTimeout(() => saveData(), SAVE_DEBOUNCE_MS);

    if (field === "CampName" || field === "campId") {
      loadCamps();
      loadStats();
    }

    const label = field === "CampName" ? "Camp Name" : field === "campId" ? "Camp ID" : field;
    if (failed === 0) {
      toast(`Set ${label} = "${val}" on ${done} mobs`, "success");
    } else {
      toast(`Set ${label} on ${done} mobs (${failed} failed)`, "error");
    }
    return;
  }

  // Single-row edit
  const mobId = data.npc_type_id;
  try {
    const res = await fetch(`/api/mobs/${mobId}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ [field]: newValue }),
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const json = await res.json();
    if (json.ok) {
      clearTimeout(saveDebounce);
      saveDebounce = setTimeout(() => saveData(), SAVE_DEBOUNCE_MS);

      toast(`Updated ${field} on ${mobId}`, "success");
      if (field === "CampName" || field === "campId") {
        loadCamps();
        loadStats();
      }
    }
  } catch (err) {
    toast(`Edit failed: ${err.message}`, "error");
    data[field] = oldValue;
    gridApi.applyTransaction({ update: [data] });
  }
}

// =========================================================================
// Selection
// =========================================================================
function onSelectionChanged() {
  if (!gridApi) return;
  const count = gridApi.getSelectedRows().length;
  document.getElementById("btn-assign-camp").disabled = count === 0;
  document.getElementById("btn-remove-camp").disabled = count === 0;

  if (count > 0) {
    document.getElementById("status-left").textContent =
      `Selected ${count} mob${count > 1 ? "s" : ""}`;
  }
}

function getSelectedMobIds() {
  if (!gridApi) return [];
  return gridApi.getSelectedRows().map(r => r.npc_type_id);
}

function getSelectedZone() {
  if (!gridApi) return null;
  const rows = gridApi.getSelectedRows();
  if (rows.length === 0) return null;
  const zone = rows[0].zone_short_name;
  if (rows.some(r => r.zone_short_name !== zone)) return null;
  return zone;
}

// =========================================================================
// Zones Dropdown
// =========================================================================
async function loadZones() {
  try {
    const res = await fetch("/api/zones");
    const zones = await res.json();
    const sel = document.getElementById("filter-zone");
    sel.innerHTML = '<option value="">All Zones</option>';
    zones.forEach(z => {
      const opt = document.createElement("option");
      opt.value = z;
      opt.textContent = z;
      sel.appendChild(opt);
    });
  } catch (err) {
    console.error("Failed to load zones:", err);
  }
}

// =========================================================================
// Camp Tree
// =========================================================================
async function loadCamps() {
  const tree = document.getElementById("camp-tree");
  try {
    const res = await fetch("/api/camps");
    const data = await res.json();
    renderCampTree(data);
  } catch (err) {
    tree.innerHTML = '<div class="muted">Failed to load camps</div>';
  }
}

function renderCampTree(data) {
  const tree = document.getElementById("camp-tree");
  if (!data.length) {
    tree.innerHTML = '<div class="muted">No camps defined</div>';
    return;
  }

  tree.innerHTML = "";

  data.forEach(zoneData => {
    const zoneDiv = document.createElement("div");
    zoneDiv.className = "camp-zone";
    zoneDiv.innerHTML = `<span class="arrow">▼</span> ${zoneData.zone}`;
    zoneDiv.onclick = () => {
      zoneDiv.classList.toggle("collapsed");
      const children = zoneDiv.nextElementSibling;
      if (children) children.classList.toggle("hidden");
    };

    const childrenDiv = document.createElement("div");
    childrenDiv.className = "camp-children";

    zoneData.camps.forEach(camp => {
      const item = document.createElement("div");
      item.className = "camp-item";
      item.innerHTML = `
        <span>${escHtml(camp.name)}</span>
        <span class="camp-count">${camp.mob_count}</span>
      `;
      item.dataset.zone = zoneData.zone;
      item.dataset.campId = camp.id;
      item.dataset.campName = camp.name;
      item.onclick = (e) => onCampClick(item, zoneData.zone, camp, e);

      if (selectedCamp && selectedCamp.camp_id === camp.id && selectedCamp.zone === zoneData.zone) {
        item.classList.add("selected");
      }

      childrenDiv.appendChild(item);
    });

    tree.appendChild(zoneDiv);
    tree.appendChild(childrenDiv);
  });
}

function onCampClick(el, zone, camp, event) {
  document.querySelectorAll(".camp-item.selected").forEach(i => i.classList.remove("selected"));

  if (selectedCamp && selectedCamp.camp_id === camp.id && selectedCamp.zone === zone) {
    selectedCamp = null;
    el.classList.remove("selected");
  } else {
    selectedCamp = { zone, camp_id: camp.id, camp_name: camp.name };
    el.classList.add("selected");
    document.getElementById("filter-zone").value = zone;
  }

  doSearch();
}

// =========================================================================
// Camp Bulk Assign / Remove
// =========================================================================
function openAssignCampDialog() {
  const mobIds = getSelectedMobIds();
  if (mobIds.length === 0) {
    toast("Select mobs first", "info");
    return;
  }

  const zone = getSelectedZone();
  if (!zone) {
    toast("All selected mobs must be in the same zone", "info");
    return;
  }

  document.getElementById("camp-dialog-info").textContent =
    `Assigning ${mobIds.length} mob(s) in zone: ${zone}`;
  document.getElementById("camp-dialog-id").value = "";
  document.getElementById("camp-dialog-name").value = "";

  // Populate existing camps
  const existing = document.getElementById("camp-dialog-existing");
  existing.innerHTML = '<option value="">-- Select or type new below --</option>';
  fetch("/api/camps")
    .then(r => r.json())
    .then(data => {
      const zoneData = data.find(z => z.zone === zone);
      if (zoneData) {
        zoneData.camps.forEach(c => {
          const opt = document.createElement("option");
          opt.value = JSON.stringify({ id: c.id, name: c.name });
          opt.textContent = `${c.name} (${c.id})`;
          existing.appendChild(opt);
        });
      }
    });

  document.getElementById("camp-dialog-overlay").classList.remove("hidden");

  // OK handler
  const btn = document.getElementById("camp-dialog-ok");
  const newBtn = btn.cloneNode(true);
  btn.parentNode.replaceChild(newBtn, btn);
  newBtn.onclick = async () => {
    const existingVal = document.getElementById("camp-dialog-existing").value;
    const newId = document.getElementById("camp-dialog-id").value.trim();
    const newName = document.getElementById("camp-dialog-name").value.trim();

    let campId, campName;
    if (existingVal) {
      const p = JSON.parse(existingVal);
      campId = p.id;
      campName = p.name;
    } else if (newId && newName) {
      campId = newId;
      campName = newName;
    } else {
      toast("Select existing or enter new camp ID + name", "info");
      return;
    }

    // Bulk update via individual PUTs
    let done = 0;
    for (const mid of mobIds) {
      try {
        const res = await fetch(`/api/mobs/${mid}`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ CampName: campName, campId }),
        });
        if (res.ok) done++;
      } catch (e) { /* skip */ }
    }

    closeCampDialog();
    saveData();  // auto-save
    loadData();
    loadCamps();
    loadStats();
    toast(`Assigned ${done} mob(s) to "${campName}"`, "success");
  };
}

function closeCampDialog() {
  document.getElementById("camp-dialog-overlay").classList.add("hidden");
}

async function removeCampFromSelected() {
  const mobIds = getSelectedMobIds();
  if (mobIds.length === 0) return;

  if (!confirm(`Remove camp from ${mobIds.length} mob(s)?`)) return;

  let done = 0;
  for (const mid of mobIds) {
    try {
      const res = await fetch(`/api/mobs/${mid}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ CampName: "", campId: "" }),
      });
      if (res.ok) done++;
    } catch (e) { /* skip */ }
  }

  saveData();  // auto-save
  loadData();
  loadCamps();
  loadStats();
  toast(`Removed camp from ${done} mob(s)`, "success");
}

// =========================================================================
// Save / Reload / Export
// =========================================================================
async function saveData() {
  try {
    const res = await fetch("/api/save", { method: "POST" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    loadCamps();
    loadStats();
  } catch (err) {
    toast(`Save failed: ${err.message}`, "error");
  }
}

async function reloadData() {
  if (!confirm("Discard unsaved changes and reload from disk?")) return;
  try {
    const res = await fetch("/api/reload", { method: "POST" });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    loadData();
    loadCamps();
    loadStats();
    toast("Reloaded from disk", "info");
  } catch (err) {
    toast(`Reload failed: ${err.message}`, "error");
  }
}

function exportCSV() {
  if (!gridApi) return;
  const rows = gridApi.getSelectedRows().length > 0
    ? gridApi.getSelectedRows()
    : null;

  const params = rows ? { onlySelected: true } : {};
  gridApi.exportDataAsCsv({
    fileName: "mobs_export.csv",
    columnSeparator: "|",
    onlySelected: rows && rows.length > 0,
  });
  toast("CSV exported", "success");
}

// =========================================================================
// Stats
// =========================================================================
async function loadStats() {
  try {
    const res = await fetch("/api/stats");
    const stats = await res.json();
    document.getElementById("stats-panel").innerHTML = `
      <div class="stats-grid">
        <div class="stat-item">
          <div class="stat-value">${stats.total_mobs.toLocaleString()}</div>
          <div class="stat-label">Total Mobs</div>
        </div>
        <div class="stat-item">
          <div class="stat-value">${stats.total_zones}</div>
          <div class="stat-label">Zones</div>
        </div>
        <div class="stat-item">
          <div class="stat-value">${stats.camp_assigned_rows.toLocaleString()}</div>
          <div class="stat-label">Camp Assigned</div>
        </div>
        <div class="stat-item">
          <div class="stat-value">${stats.coverage_pct}%</div>
          <div class="stat-label">Coverage</div>
        </div>
      </div>
    `;
  } catch (err) {
    console.error("Stats load failed:", err);
  }
}

// =========================================================================
// Clear Filters
// =========================================================================
function clearAllFilters() {
  document.getElementById("search-input").value = "";
  document.getElementById("filter-zone").value = "";
  document.getElementById("filter-level-min").value = "0";
  document.getElementById("filter-level-max").value = "100";
  document.getElementById("filter-has-camp").value = "";
  document.getElementById("filter-named").checked = false;
  document.querySelectorAll(".camp-item.selected").forEach(i => i.classList.remove("selected"));
  selectedCamp = null;

  if (gridApi) {
    gridApi.setGridOption("rowData", []);
    gridApi.showNoRowsOverlay();
  }
  updateStatus("Type a search term or select a filter to begin", "");
}

// =========================================================================
// Theme
// =========================================================================
function toggleTheme() {
  const html = document.documentElement;
  const next = html.getAttribute("data-theme") === "light" ? "dark" : "light";
  html.setAttribute("data-theme", next);

  const gridDiv = document.getElementById("grid-container");
  gridDiv.classList.toggle("ag-theme-alpine-dark", next === "dark");
  gridDiv.classList.toggle("ag-theme-alpine", next === "light");

  localStorage.setItem("eq-mob-manager-theme", next);
}

function restoreTheme() {
  const saved = localStorage.getItem("eq-mob-manager-theme");
  if (saved === "light") {
    document.documentElement.setAttribute("data-theme", "light");
    const gridDiv = document.getElementById("grid-container");
    gridDiv.classList.remove("ag-theme-alpine-dark");
    gridDiv.classList.add("ag-theme-alpine");
  }
}

// =========================================================================
// Loading overlay
// =========================================================================
function showLoading(msg) {
  const overlay = document.getElementById("loading-overlay");
  if (!overlay) return;
  document.getElementById("loading-text").textContent = msg;
  overlay.classList.remove("hidden");
  // Also show AG Grid's own overlay
  if (gridApi) gridApi.showLoadingOverlay();
}

function hideLoading() {
  const overlay = document.getElementById("loading-overlay");
  if (overlay) overlay.classList.add("hidden");
  if (gridApi) gridApi.hideOverlay();
}

function updateStatus(left, right) {
  document.getElementById("status-left").textContent = left;
  document.getElementById("status-right").textContent = right || "";
}

// =========================================================================
// Toast
// =========================================================================
function toast(message, type = "info") {
  const container = document.getElementById("toast-container");
  const el = document.createElement("div");
  el.className = `toast toast-${type}`;
  el.textContent = message;
  container.appendChild(el);
  setTimeout(() => {
    el.classList.add("out");
    setTimeout(() => el.remove(), 250);
  }, 3000);
}

// =========================================================================
// Event Bindings
// =========================================================================
function bindEvents() {
  // Search box: suggestions on type, search on Enter
  document.getElementById("search-input").addEventListener("input", onFilterChange);
  document.getElementById("search-input").addEventListener("keydown", onSearchKeydown);

  // Filters: search immediately on change
  document.getElementById("filter-zone").addEventListener("change", doSearch);
  document.getElementById("filter-level-min").addEventListener("input", () => { clearTimeout(debounceTimer); debounceTimer = setTimeout(doSearch, DEBOUNCE_MS); });
  document.getElementById("filter-level-max").addEventListener("input", () => { clearTimeout(debounceTimer); debounceTimer = setTimeout(doSearch, DEBOUNCE_MS); });
  document.getElementById("filter-has-camp").addEventListener("change", doSearch);
  document.getElementById("filter-named").addEventListener("change", doSearch);
  document.getElementById("btn-clear-filters").addEventListener("click", clearAllFilters);
  document.getElementById("btn-refresh-camps").addEventListener("click", () => { loadCamps(); doSearch(); });
  document.getElementById("btn-assign-camp").addEventListener("click", openAssignCampDialog);
  document.getElementById("btn-remove-camp").addEventListener("click", removeCampFromSelected);
  document.getElementById("btn-save").addEventListener("click", saveData);
  document.getElementById("btn-reload").addEventListener("click", reloadData);
  document.getElementById("btn-export").addEventListener("click", exportCSV);
  document.getElementById("btn-theme").addEventListener("click", toggleTheme);
  document.getElementById("camp-dialog-cancel").addEventListener("click", closeCampDialog);

  document.getElementById("camp-dialog-existing").addEventListener("change", function () {
    if (this.value) {
      const p = JSON.parse(this.value);
      document.getElementById("camp-dialog-id").value = p.id;
      document.getElementById("camp-dialog-name").value = p.name;
      document.getElementById("camp-dialog-id").disabled = true;
      document.getElementById("camp-dialog-name").disabled = true;
    } else {
      document.getElementById("camp-dialog-id").value = "";
      document.getElementById("camp-dialog-name").value = "";
      document.getElementById("camp-dialog-id").disabled = false;
      document.getElementById("camp-dialog-name").disabled = false;
    }
  });

  document.getElementById("camp-dialog-overlay").addEventListener("click", (e) => {
    if (e.target === e.currentTarget) closeCampDialog();
  });
}

// =========================================================================
// Keyboard Shortcuts
// =========================================================================
function bindKeyboardShortcuts() {
  document.addEventListener("keydown", (e) => {
    // Suggestions navigation
    const dropdown = document.getElementById("suggestions-dropdown");
    if (!dropdown.classList.contains("hidden")) {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        activeSuggestionIdx = Math.min(activeSuggestionIdx + 1, suggestions.length - 1);
        highlightSuggestion(activeSuggestionIdx);
        return;
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        activeSuggestionIdx = Math.max(activeSuggestionIdx - 1, 0);
        highlightSuggestion(activeSuggestionIdx);
        return;
      }
      if (e.key === "Enter" && activeSuggestionIdx >= 0) {
        e.preventDefault();
        selectSuggestion(activeSuggestionIdx);
        return;
      }
      if (e.key === "Escape") {
        hideSuggestions();
        return;
      }
    }

    if (e.ctrlKey && e.key === "s") { e.preventDefault(); saveData(); }
    if (e.ctrlKey && e.key === "f") { e.preventDefault(); document.getElementById("search-input").focus(); }
    if (e.key === "Escape") {
      if (!document.getElementById("camp-dialog-overlay").classList.contains("hidden")) {
        closeCampDialog();
      }
    }
  });

  // Click outside to dismiss suggestions
  document.addEventListener("click", (e) => {
    const input = document.getElementById("search-input");
    const dropdown = document.getElementById("suggestions-dropdown");
    if (!input.contains(e.target) && !dropdown.contains(e.target)) {
      hideSuggestions();
    }
  });
}

// =========================================================================
// Map Popup — hover preview, click to pin + zoom/pan
// =========================================================================
let mapPinned = false;
let mapPinnedMob = null;
let mapView = { scale: 1, offsetX: 0, offsetY: 0 }; // zoom/pan state
let mapDragging = false;
let mapDragStart = { x: 0, y: 0, ox: 0, oy: 0 };
let mapLayers = [];           // all layers for current zone
let mapActiveLayer = 0;       // currently visible layer index

function bindMapPopupEvents() {
  if (!gridApi) return;

  // Hover: preview after 400ms delay (only if not pinned, only on mob_name)
  gridApi.addEventListener("cellMouseOver", (e) => {
    if (!e.data || mapPinned) return;
    if (!e.column || e.column.getColId() !== "mob_name") return;
    const data = e.data;
    if (data.x == null || data.y == null || !data.zone_short_name) return;
    clearTimeout(mapPopupTimer);
    mapPopupTimer = setTimeout(() => showMapPopup(data, e.event, false), 400);
  });

  gridApi.addEventListener("cellMouseOut", () => {
    if (mapPinned) return;
    clearTimeout(mapPopupTimer);
    mapPopupTimer = setTimeout(() => {
      if (!mapPinned) hideMapPopup();
    }, 200);
  });

  // Click on mob NAME cell: pin/unpin map
  gridApi.addEventListener("cellClicked", (e) => {
    if (!e.data) return;
    // Only trigger on mob_name column
    if (!e.column || e.column.getColId() !== "mob_name") return;

    const data = e.data;
    if (data.x == null || data.y == null || !data.zone_short_name) return;

    // If same mob is already pinned, unpin
    if (mapPinned && mapPinnedMob && mapPinnedMob.npc_type_id === data.npc_type_id) {
      hideMapPopup();
      return;
    }

    // Pin this mob's map
    clearTimeout(mapPopupTimer);
    showMapPopup(data, e.event, true);
  });

  // Popup hover keeps preview open
  const popup = document.getElementById("map-popup");
  popup.addEventListener("mouseenter", () => clearTimeout(mapPopupTimer));
  popup.addEventListener("mouseleave", () => {
    if (!mapPinned) hideMapPopup();
  });

  // Close button
  document.getElementById("map-popup-close").addEventListener("click", hideMapPopup);

  // Zoom controls
  document.getElementById("map-zoom-in").addEventListener("click", () => zoomMap(0.3));
  document.getElementById("map-zoom-out").addEventListener("click", () => zoomMap(-0.3));
  document.getElementById("map-zoom-reset").addEventListener("click", resetMapView);

  // Canvas zoom/pan
  const canvas = document.getElementById("map-canvas");
  canvas.addEventListener("wheel", onMapWheel, { passive: false });
  canvas.addEventListener("mousedown", onMapDragStart);
  canvas.addEventListener("mousemove", onMapDragMove);
  canvas.addEventListener("mouseup", onMapDragEnd);
  canvas.addEventListener("mouseleave", onMapDragEnd);
}

function showMapPopup(mobData, event, pin) {
  const zone = mobData.zone_short_name;
  const x = Number(mobData.x);
  const y = Number(mobData.y);

  mapPinned = !!pin;
  mapPinnedMob = pin ? mobData : null;
  if (pin) resetMapView();

  // Position popup
  const popup = document.getElementById("map-popup");
  const popupW = 524;
  const popupH = 580;
  let left, top;

  if (pin) {
    // Pinned: center on screen
    left = (window.innerWidth - popupW) / 2;
    top = (window.innerHeight - popupH) / 2;
    if (top < 60) top = 60;
    popup.classList.add("pinned");
  } else {
    // Hover: near cursor
    left = (event.clientX || event.x) + 20;
    top = (event.clientY || event.y) - popupH / 2;
    if (left + popupW > window.innerWidth - 10) left = window.innerWidth - popupW - 10;
    if (top < 60) top = 60;
    if (top + popupH > window.innerHeight - 10) top = window.innerHeight - popupH - 10;
    popup.classList.remove("pinned");
  }

  popup.style.left = left + "px";
  popup.style.top = top + "px";

  document.getElementById("map-popup-title").textContent =
    `${mobData.mob_name} (Lv ${mobData.mob_level}) · ${zone}  [${x.toFixed(0)}, ${y.toFixed(0)}]`;
  popup.classList.remove("hidden");

  // Fetch and render — auto-detect which layer contains the mob
  fetchMap(zone).then(mapData => {
    if (!mapData) { hideMapPopup(); return; }
    mapLayers = mapData.layers || [];
    // Find layer containing the mob
    mapActiveLayer = 0;
    for (let i = 0; i < mapLayers.length; i++) {
      const b = mapLayers[i].bounds;
      if (x >= b.minX && x <= b.maxX && y >= b.minY && y <= b.maxY) {
        mapActiveLayer = i;
        break;
      }
    }
    buildLayerTabs();
    renderCurrentLayer(x, y, mobData.mob_name);
  });
}

function hideMapPopup() {
  document.getElementById("map-popup").classList.add("hidden");
  document.getElementById("map-popup").classList.remove("pinned");
  mapPinned = false;
  mapPinnedMob = null;
  currentMapZone = null;
  mapLayers = [];
  mapActiveLayer = 0;
  resetMapView();
}

function buildLayerTabs() {
  const container = document.getElementById("map-layer-tabs");
  container.innerHTML = "";
  if (mapLayers.length <= 1) {
    container.classList.add("hidden");
    return;
  }
  container.classList.remove("hidden");
  mapLayers.forEach((layer, i) => {
    const tab = document.createElement("button");
    tab.className = "map-layer-tab" + (i === mapActiveLayer ? " active" : "");
    tab.textContent = layer.name;
    tab.onclick = () => {
      mapActiveLayer = i;
      buildLayerTabs();
      if (mapPinnedMob) {
        renderCurrentLayer(Number(mapPinnedMob.x), Number(mapPinnedMob.y), mapPinnedMob.mob_name);
      }
    };
    container.appendChild(tab);
  });
}

function renderCurrentLayer(mobX, mobY, mobName) {
  if (mapActiveLayer < 0 || mapActiveLayer >= mapLayers.length) return;
  renderMap(mapLayers[mapActiveLayer], mobX, mobY, mobName);
}

// --- Zoom/Pan ---
function zoomMap(delta) {
  mapView.scale = Math.max(0.3, Math.min(5, mapView.scale + delta));
  document.getElementById("map-zoom-level").textContent = Math.round(mapView.scale * 100) + "%";
  if (mapPinnedMob) reRenderPinnedMap();
}

function resetMapView() {
  mapView = { scale: 1, offsetX: 0, offsetY: 0 };
  document.getElementById("map-zoom-level").textContent = "100%";
  if (mapPinnedMob) reRenderPinnedMap();
}

function onMapWheel(e) {
  e.preventDefault();
  const delta = e.deltaY > 0 ? -0.15 : 0.15;
  // Zoom toward cursor position
  const canvas = document.getElementById("map-canvas");
  const rect = canvas.getBoundingClientRect();
  const cx = e.clientX - rect.left;
  const cy = e.clientY - rect.top;

  const oldScale = mapView.scale;
  mapView.scale = Math.max(0.3, Math.min(5, mapView.scale + delta));
  const ratio = mapView.scale / oldScale;

  mapView.offsetX = cx - ratio * (cx - mapView.offsetX);
  mapView.offsetY = cy - ratio * (cy - mapView.offsetY);

  document.getElementById("map-zoom-level").textContent = Math.round(mapView.scale * 100) + "%";
  if (mapPinnedMob) reRenderPinnedMap();
}

function onMapDragStart(e) {
  mapDragging = true;
  mapDragStart = {
    x: e.clientX,
    y: e.clientY,
    ox: mapView.offsetX,
    oy: mapView.offsetY,
  };
  e.preventDefault();
}

function onMapDragMove(e) {
  if (!mapDragging) return;
  mapView.offsetX = mapDragStart.ox + (e.clientX - mapDragStart.x);
  mapView.offsetY = mapDragStart.oy + (e.clientY - mapDragStart.y);
  if (mapPinnedMob) reRenderPinnedMap();
}

function onMapDragEnd() {
  mapDragging = false;
}

function reRenderPinnedMap() {
  if (!mapPinnedMob) return;
  renderCurrentLayer(Number(mapPinnedMob.x), Number(mapPinnedMob.y), mapPinnedMob.mob_name);
}

// --- Map Fetching ---
async function fetchMap(zone) {
  if (mapCache[zone]) return mapCache[zone];
  if (mapCache[zone] === null) return null;
  try {
    const res = await fetch(`/api/map/${encodeURIComponent(zone)}`);
    if (!res.ok) { mapCache[zone] = null; return null; }
    const data = await res.json();
    mapCache[zone] = data;
    return data;
  } catch (e) {
    mapCache[zone] = null;
    return null;
  }
}

// --- Canvas Rendering ---
function renderMap(mapData, mobX, mobY, mobName) {
  const canvas = document.getElementById("map-canvas");
  const ctx = canvas.getContext("2d");
  const w = canvas.width;
  const h = canvas.height;
  const s = mapView.scale;

  // Clear — EQ parchment background
  ctx.fillStyle = "#c8b898";
  ctx.fillRect(0, 0, w, h);

  // Subtle parchment texture (noise-like grain)
  ctx.fillStyle = "rgba(180,160,130,0.08)";
  for (let i = 0; i < 200; i++) {
    const gx = Math.random() * w;
    const gy = Math.random() * h;
    ctx.fillRect(gx, gy, 2, 2);
  }

  // Grid lines (EQ-style coordinate grid)
  ctx.strokeStyle = "rgba(160,140,110,0.25)";
  ctx.lineWidth = 0.5;
  const gridSize = 40;
  for (let gx = gridSize; gx < w; gx += gridSize) {
    ctx.beginPath();
    ctx.moveTo(gx, 0);
    ctx.lineTo(gx, h);
    ctx.stroke();
  }
  for (let gy = gridSize; gy < h; gy += gridSize) {
    ctx.beginPath();
    ctx.moveTo(0, gy);
    ctx.lineTo(w, gy);
    ctx.stroke();
  }

  // Border inside canvas (map frame)
  ctx.strokeStyle = "#3b2008";
  ctx.lineWidth = 4;
  ctx.strokeRect(2, 2, w - 4, h - 4);

  if (!mapData) {
    ctx.fillStyle = "#6b5a3e";
    ctx.font = "bold 15px serif";
    ctx.textAlign = "center";
    ctx.fillText("No map available for this zone", w / 2, h / 2);
    return;
  }

  const b = mapData.bounds;
  const mapW = b.maxX - b.minX;
  const mapH = b.maxY - b.minY;
  if (mapW <= 0 || mapH <= 0) return;

  // Base scale to fit canvas
  const pad = 20;
  const fitScale = Math.min((w - pad * 2) / mapW, (h - pad * 2) / mapH);
  const baseScale = fitScale;
  const scale = baseScale * s;

  // Base offset (centered)
  const baseOX = pad + (w - pad * 2 - mapW * fitScale) / 2;
  const baseOY = pad + (h - pad * 2 - mapH * fitScale) / 2;

  // Apply zoom/pan: zoom toward center, then add pan offset
  const cx = w / 2;
  const cy = h / 2;
  const ox = cx - s * (cx - baseOX) + mapView.offsetX;
  const oy = cy - s * (cy - baseOY) + mapView.offsetY;

  function tx(px) { return ox + (px - b.minX) * scale; }
  function ty(py) { return oy + (py - b.minY) * scale; }

  // Draw lines — darken Brewall colors for parchment visibility
  for (const line of mapData.lines) {
    const sx = tx(line.x1), sy = ty(line.y1);
    const ex = tx(line.x2), ey = ty(line.y2);
    if ((sx < -50 && ex < -50) || (sx > w + 50 && ex > w + 50) ||
        (sy < -50 && ey < -50) || (sy > h + 50 && ey > h + 50)) continue;
    ctx.beginPath();
    ctx.moveTo(sx, sy);
    ctx.lineTo(ex, ey);

    // Parse original Brewall color and darken for parchment
    const orig = line.color || "rgb(150,150,150)";
    const match = orig.match(/rgb\((\d+),\s*(\d+),\s*(\d+)\)/);
    if (match) {
      // Darken and shift toward brown for EQ parchment look
      const r = Math.round(parseInt(match[1]) * 0.5 + 40);
      const g = Math.round(parseInt(match[2]) * 0.45 + 30);
      const b = Math.round(parseInt(match[3]) * 0.4 + 20);
      ctx.strokeStyle = `rgb(${r},${g},${b})`;
    } else {
      ctx.strokeStyle = "#4a3020";
    }
    ctx.lineWidth = Math.max(1, s * 1.2);
    ctx.stroke();
  }

  // Draw POI points
  if (s > 0.5) {
    for (const pt of mapData.points) {
      const sx = tx(pt.x), sy = ty(pt.y);
      if (sx < 0 || sx > w || sy < 0 || sy > h) continue;
      // Small label dot
      ctx.fillStyle = "#8b2020";
      ctx.beginPath();
      ctx.arc(sx, sy, Math.max(2, s * 2.5), 0, Math.PI * 2);
      ctx.fill();
      ctx.strokeStyle = "#3b1008";
      ctx.lineWidth = 0.8;
      ctx.stroke();
    }
  }

  // Draw mob position — bright marker on parchment
  if (mobX != null && mobY != null) {
    const mx = tx(mobX), my = ty(mobY);

    // Outer glow (red pulse on parchment)
    const glowR = Math.max(10, 18 * s);
    const gradient = ctx.createRadialGradient(mx, my, 3 * s, mx, my, glowR);
    gradient.addColorStop(0, "rgba(200,30,30,0.7)");
    gradient.addColorStop(0.5, "rgba(200,40,20,0.2)");
    gradient.addColorStop(1, "rgba(200,40,20,0)");
    ctx.fillStyle = gradient;
    ctx.beginPath();
    ctx.arc(mx, my, glowR, 0, Math.PI * 2);
    ctx.fill();

    // Main dot
    const dotR = Math.max(4, 6 * s);
    ctx.fillStyle = "#cc2222";
    ctx.beginPath();
    ctx.arc(mx, my, dotR, 0, Math.PI * 2);
    ctx.fill();
    // Dark border
    ctx.strokeStyle = "#1a0505";
    ctx.lineWidth = Math.max(1.5, 2 * s);
    ctx.stroke();
    // Inner highlight
    ctx.fillStyle = "#ff6655";
    ctx.beginPath();
    ctx.arc(mx - dotR * 0.25, my - dotR * 0.25, dotR * 0.4, 0, Math.PI * 2);
    ctx.fill();

    // Label
    if (mobName && s > 0.4) {
      const coordLabel = `${mobName} (${mobX.toFixed(0)}, ${mobY.toFixed(0)})`;
      const fontSize = Math.max(10, 12 * s);
      ctx.font = `bold ${fontSize}px serif`;
      ctx.textAlign = "center";
      const textW = ctx.measureText(coordLabel).width;
      const textY = my - dotR - 8;
      // Parchment-style label background
      ctx.fillStyle = "rgba(200,180,140,0.9)";
      ctx.fillRect(mx - textW / 2 - 6, textY - fontSize, textW + 12, fontSize + 6);
      ctx.strokeStyle = "#3b2008";
      ctx.lineWidth = 1;
      ctx.strokeRect(mx - textW / 2 - 6, textY - fontSize, textW + 12, fontSize + 6);
      ctx.fillStyle = "#4a1010";
      ctx.fillText(coordLabel, mx, textY);
    }
  }
}
