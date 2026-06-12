(() => {
  "use strict";

  // ── Auth ───────────────────────────────────────────────────────────────────
  let hassToken = null;
  let booted = false;

  window.addEventListener("message", e => {
    if (e.origin !== window.location.origin) return;
    if (e.data?.type !== "loam-auth") return;
    hassToken = e.data.token;
    if (!booted) {
      booted = true;
      boot();
    }
  });

  // ── State ──────────────────────────────────────────────────────────────────
  const CELL = 44; // pixels per foot — keep in sync with --cell in loam-panel.html

  const state = {
    gardens: [],
    activeGardenId: null,
    plants: [],
    plantings: [],
    searchResults: [],       // latest plant-search results (saved by index, not via DOM attrs)
    placements: [],          // cell plant assignments for the active garden
    companions: {},          // {"a,b": "good"|"bad"|"neutral"} for active garden's plants
    brush: "",               // "" (none), "erase", or a plant id (string)
    copyMode: false,         // next click picks up a cell's plant as the brush
    painting: false,         // mouse is down, painting cells
    paintChanges: new Map(), // pending cell changes for the current drag
  };

  const activeGarden = () => state.gardens.find(g => g.id === state.activeGardenId);

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, c =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  // ── API helpers ────────────────────────────────────────────────────────────
  async function api(method, path, body) {
    const opts = {
      method,
      headers: {
        "Content-Type": "application/json",
        ...(hassToken ? { "Authorization": `Bearer ${hassToken}` } : {}),
      },
    };
    if (body !== undefined) opts.body = JSON.stringify(body);
    const res = await fetch(`/api/loam${path}`, opts);
    const json = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(json.error || `HTTP ${res.status}`);
    return json;
  }

  const get  = (path)        => api("GET",    path);
  const post = (path, body)  => api("POST",   path, body);
  const put  = (path, body)  => api("PUT",    path, body);
  const del  = (path)        => api("DELETE", path);

  // ── Tab switching ──────────────────────────────────────────────────────────
  document.querySelectorAll(".tab").forEach(tab => {
    tab.addEventListener("click", () => {
      document.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
      document.querySelectorAll(".tab-content").forEach(c => c.classList.remove("active"));
      tab.classList.add("active");
      document.getElementById(`tab-${tab.dataset.tab}`).classList.add("active");

      if (tab.dataset.tab === "library") renderLibrary();
      if (tab.dataset.tab === "plantings") renderPlantings();
      if (tab.dataset.tab === "garden") loadGardenBoard();
    });
  });

  // ── Grid ─────────────────────────────────────────────────────────────────────
  const canvas = document.getElementById("grid-canvas");
  const gridEmpty = document.getElementById("grid-empty");

  const toolbar = document.getElementById("grid-toolbar");

  function renderGrid() {
    const g = activeGarden();
    if (!g) {
      canvas.style.display = "none";
      gridEmpty.style.display = "flex";
      toolbar.style.display = "none";
      return;
    }
    gridEmpty.style.display = "none";
    canvas.style.display = "block";
    toolbar.style.display = "flex";
    const w = g.width_ft || 1;
    const h = g.height_ft || 1;
    canvas.style.width = (w * CELL) + "px";
    canvas.style.height = (h * CELL) + "px";
    renderCells();
  }

  // ── Cell placements (plant per square) ──────────────────────────────────────
  function renderCells() {
    canvas.innerHTML = "";
    state.placements.forEach(pc => {
      const div = document.createElement("div");
      div.className = "cell-chip";
      div.style.left = (pc.grid_col * CELL + 1) + "px";
      div.style.top = (pc.grid_row * CELL + 1) + "px";
      div.style.width = (CELL - 2) + "px";
      div.style.height = (CELL - 2) + "px";
      div.title = pc.plant_name;
      div.innerHTML = `<span class="cell-chip-label">${escapeHtml(pc.plant_name)}</span>`;
      canvas.appendChild(div);
    });
  }

  function placementAt(col, row) {
    return state.placements.find(pc => pc.grid_col === col && pc.grid_row === row);
  }

  // Companion edges: red/green lines on the border between adjacent, differing plants.
  async function loadCompanions() {
    const g = activeGarden();
    if (!g) return;
    try {
      const data = await get(`/companions?garden_id=${g.id}`);
      state.companions = data.relationships || {};
    } catch (e) {
      state.companions = {};
    }
    renderCompanionEdges();
  }

  function companionRel(a, b) {
    const key = a < b ? `${a},${b}` : `${b},${a}`;
    return state.companions[key];
  }

  function renderCompanionEdges() {
    canvas.querySelectorAll(".cell-edge").forEach(e => e.remove());
    const byCell = {};
    state.placements.forEach(pc => { byCell[`${pc.grid_col},${pc.grid_row}`] = pc.plant_id; });

    state.placements.forEach(pc => {
      const c = pc.grid_col, r = pc.grid_row, pid = pc.plant_id;
      const right = byCell[`${c + 1},${r}`];
      if (right && right !== pid) addCompanionEdge(companionRel(pid, right), "v", c + 1, r);
      const down = byCell[`${c},${r + 1}`];
      if (down && down !== pid) addCompanionEdge(companionRel(pid, down), "h", c, r + 1);
    });
  }

  function addCompanionEdge(relationship, orient, col, row) {
    if (relationship !== "good" && relationship !== "bad") return;
    const div = document.createElement("div");
    div.className = `cell-edge ${relationship}`;
    if (orient === "v") {
      div.style.left = (col * CELL - 1.5) + "px";
      div.style.top = (row * CELL) + "px";
      div.style.width = "3px";
      div.style.height = CELL + "px";
    } else {
      div.style.left = (col * CELL) + "px";
      div.style.top = (row * CELL - 1.5) + "px";
      div.style.width = CELL + "px";
      div.style.height = "3px";
    }
    canvas.appendChild(div);
  }

  function cellFromEvent(e) {
    const g = activeGarden();
    const r = canvas.getBoundingClientRect();
    let col = Math.floor((e.clientX - r.left) / CELL);
    let row = Math.floor((e.clientY - r.top) / CELL);
    col = Math.max(0, Math.min(col, g.width_ft - 1));
    row = Math.max(0, Math.min(row, g.height_ft - 1));
    return { col, row };
  }

  function setLocalPlacement(col, row, plantId, plantName) {
    const existing = placementAt(col, row);
    if (existing) {
      existing.plant_id = plantId;
      existing.plant_name = plantName;
    } else {
      state.placements.push({
        garden_id: state.activeGardenId,
        grid_col: col, grid_row: row,
        plant_id: plantId, plant_name: plantName,
      });
    }
  }

  function removeLocalPlacement(col, row) {
    state.placements = state.placements.filter(
      pc => !(pc.grid_col === col && pc.grid_row === row));
  }

  function applyBrushToCell(col, row) {
    const key = col + "," + row;
    if (state.brush === "erase") {
      if (!placementAt(col, row)) return;
      removeLocalPlacement(col, row);
      state.paintChanges.set(key, { grid_col: col, grid_row: row, plant_id: null });
    } else {
      const plantId = parseInt(state.brush, 10);
      if (!plantId) return;
      const existing = placementAt(col, row);
      if (existing && existing.plant_id === plantId) return;
      const plant = state.plants.find(p => p.id === plantId);
      setLocalPlacement(col, row, plantId, plant ? plant.name : "");
      state.paintChanges.set(key, { grid_col: col, grid_row: row, plant_id: plantId });
    }
    renderCells();
  }

  async function commitPaint() {
    if (!state.paintChanges.size) return;
    const cells = [...state.paintChanges.values()];
    state.paintChanges = new Map();
    try {
      state.placements = await post("/placements", { garden_id: state.activeGardenId, cells });
      renderCells();
      loadCompanions();
    } catch (e) {
      alert("Error: " + e.message);
      await loadGardenBoard();
    }
  }

  canvas.addEventListener("mousedown", e => {
    const g = activeGarden();
    if (!g) return;
    const { col, row } = cellFromEvent(e);
    if (state.copyMode) {
      const pc = placementAt(col, row);
      if (pc) setBrush(String(pc.plant_id));
      state.copyMode = false;
      updateBrushHint();
      updateCanvasMode();
      return;
    }
    if (state.brush === "") return;
    e.preventDefault();
    state.painting = true;
    state.paintChanges = new Map();
    applyBrushToCell(col, row);
  });

  canvas.addEventListener("mousemove", e => {
    if (!state.painting) return;
    const { col, row } = cellFromEvent(e);
    applyBrushToCell(col, row);
  });

  window.addEventListener("mouseup", () => {
    if (!state.painting) return;
    state.painting = false;
    commitPaint();
  });

  // ── Brush toolbar ────────────────────────────────────────────────────────────
  function populateBrushSelect() {
    const sel = document.getElementById("brush-select");
    const cur = state.brush;
    const opts = state.plants.map(p =>
      `<option value="${p.id}">${escapeHtml(p.name)}</option>`).join("");
    sel.innerHTML = '<option value="">— none —</option>' +
      (state.plants.length ? '<option value="erase">Erase</option>' : "") + opts;
    const valid = cur === "erase" || (cur && state.plants.find(p => String(p.id) === cur));
    sel.value = valid ? cur : "";
    state.brush = sel.value;
    updateBrushHint();
    updateCanvasMode();
  }

  function setBrush(value) {
    state.brush = value;
    const sel = document.getElementById("brush-select");
    if (sel) sel.value = value;
    updateBrushHint();
    updateCanvasMode();
  }

  function updateBrushHint() {
    const hint = document.getElementById("brush-hint");
    if (!state.plants.length) {
      hint.textContent = "No plants yet — add some in the Library tab first.";
    } else if (state.copyMode) {
      hint.textContent = "Copy mode: click a planted square to pick up its plant.";
    } else if (state.brush === "") {
      hint.textContent = "Pick a plant above, then click or drag squares.";
    } else if (state.brush === "erase") {
      hint.textContent = "Click or drag squares to clear them.";
    } else {
      hint.textContent = "Click or drag squares to plant. Choose “Erase” to clear.";
    }
  }

  function updateCanvasMode() {
    canvas.classList.toggle("copy", state.copyMode);
    canvas.classList.toggle("planting", !state.copyMode && state.brush !== "");
  }

  document.getElementById("brush-select").addEventListener("change", e => {
    state.brush = e.target.value;
    state.copyMode = false;
    updateBrushHint();
    updateCanvasMode();
  });

  document.getElementById("btn-copy-cell").addEventListener("click", () => {
    if (!state.plants.length) return;
    state.copyMode = !state.copyMode;
    updateBrushHint();
    updateCanvasMode();
  });

  async function loadGardenBoard() {
    state.placements = [];
    renderGrid();
    const g = activeGarden();
    if (!g) return;
    const [placements, plants] = await Promise.all([
      get(`/placements?garden_id=${g.id}`),
      get("/plants"),
    ]);
    state.placements = placements;
    state.plants = plants;
    populateBrushSelect();
    renderCells();
    loadCompanions();
  }

  // ── Gardens ──────────────────────────────────────────────────────────────────
  async function loadGardens() {
    state.gardens = await get("/garden");
    if (state.activeGardenId && !state.gardens.find(g => g.id === state.activeGardenId)) {
      state.activeGardenId = null;
    }
    renderGardensList();
    populatePlantingGardenDropdowns();
  }

  function renderGardensList() {
    const el = document.getElementById("gardens-list");
    if (!state.gardens.length) {
      el.innerHTML = '<div class="empty-state">No gardens yet.<br/>Click “+ New” to create one.</div>';
      return;
    }
    el.innerHTML = state.gardens.map(g => {
      const typeLabel = g.type.replace("_", " ");
      const size = (g.width_ft != null && g.height_ft != null)
        ? `${g.width_ft}×${g.height_ft} ft · ` : "";
      const sel = g.id === state.activeGardenId ? " selected" : "";
      return `
        <div class="garden-card${sel}" data-garden-id="${g.id}">
          <div class="garden-card-header">
            <span class="garden-name">${escapeHtml(g.name)}</span>
            <span class="type-badge ${g.type}">${typeLabel}</span>
          </div>
          <div class="garden-meta">${size}${g.planting_count} active planting${g.planting_count !== 1 ? "s" : ""}</div>
          <div class="planting-actions">
            <button class="btn btn-danger btn-sm" data-delete-garden="${g.id}">Delete</button>
          </div>
        </div>`;
    }).join("");

    el.querySelectorAll(".garden-card").forEach(card => {
      card.addEventListener("click", e => {
        if (e.target.closest("[data-delete-garden]")) return;
        selectGarden(parseInt(card.dataset.gardenId, 10));
      });
    });

    el.querySelectorAll("[data-delete-garden]").forEach(btn => {
      btn.addEventListener("click", async e => {
        e.stopPropagation();
        if (!confirm("Delete this garden? Its plantings will be removed too.")) return;
        const id = parseInt(btn.dataset.deleteGarden, 10);
        await del(`/garden/${id}`).catch(err => alert(err.message));
        if (state.activeGardenId === id) state.activeGardenId = null;
        await loadGardens();
        renderGrid();
      });
    });
  }

  function selectGarden(id) {
    state.activeGardenId = id;
    renderGardensList();
    loadGardenBoard();
  }

  document.getElementById("btn-new-garden").addEventListener("click", showGardenForm);

  function showGardenForm() {
    const list = document.getElementById("gardens-list");
    if (document.getElementById("new-garden-form")) return;
    list.insertAdjacentHTML("afterbegin", `
      <div class="form-card" id="new-garden-form">
        <h3>New garden</h3>
        <div class="form-group">
          <label>Name</label>
          <input type="text" id="ng-name" placeholder="e.g. South Raised Bed" />
        </div>
        <div class="form-group">
          <label>Type</label>
          <select id="ng-type">
            <option value="raised_bed">Raised Bed</option>
            <option value="in_ground">In Ground</option>
            <option value="container">Container</option>
            <option value="grow_bag">Grow Bag</option>
          </select>
        </div>
        <div class="form-group">
          <label>Width (feet)</label>
          <input type="number" id="ng-width" min="1" max="200" value="4" />
        </div>
        <div class="form-group">
          <label>Height (feet)</label>
          <input type="number" id="ng-height" min="1" max="200" value="8" />
        </div>
        <div style="display:flex;gap:8px">
          <button class="btn btn-primary btn-sm" id="ng-save">Create</button>
          <button class="btn btn-ghost btn-sm" id="ng-cancel">Cancel</button>
        </div>
      </div>
    `);
    document.getElementById("ng-save").addEventListener("click", saveNewGarden);
    document.getElementById("ng-cancel").addEventListener("click", () => {
      document.getElementById("new-garden-form").remove();
      renderGardensList();
    });
    document.getElementById("ng-name").focus();
  }

  async function saveNewGarden() {
    const name = document.getElementById("ng-name").value.trim();
    const type = document.getElementById("ng-type").value;
    const w = parseInt(document.getElementById("ng-width").value, 10);
    const h = parseInt(document.getElementById("ng-height").value, 10);
    if (!name) { alert("Name is required."); return; }
    if (!(w >= 1 && w <= 200) || !(h >= 1 && h <= 200)) {
      alert("Width and height must be between 1 and 200 feet.");
      return;
    }
    try {
      const g = await post("/garden", { name, type, width_ft: w, height_ft: h });
      state.activeGardenId = g.id;
      await loadGardens();
      await loadGardenBoard();
    } catch (e) {
      alert("Error: " + e.message);
    }
  }

  // ── Library ──────────────────────────────────────────────────────────────────
  async function renderLibrary() {
    state.plants = await get("/plants");
    renderPlantLibrary();
  }

  function renderPlantLibrary() {
    const el = document.getElementById("library-list");
    if (!state.plants.length) {
      el.innerHTML = '<div class="empty-state">No plants saved yet.<br/>Search OpenFarm or add a custom plant.</div>';
      return;
    }
    el.innerHTML = state.plants.map(p => `
      <div class="plant-card">
        <div class="plant-card-header">
          <div>
            <div class="plant-card-name">${escapeHtml(p.name)}</div>
            <div class="plant-card-meta">${escapeHtml(p.sun_requirements || "")}${p.days_to_maturity_min ? ` · ${p.days_to_maturity_min} days` : ""}</div>
          </div>
          <button class="btn btn-danger btn-sm" data-delete-plant="${p.id}">✕</button>
        </div>
        ${p.description ? `<div class="plant-card-meta" style="margin-top:6px">${escapeHtml(p.description)}</div>` : ""}
        ${p.is_custom ? '<div class="plant-card-meta" style="color:#66bb6a;margin-top:4px">Custom</div>' : ""}
      </div>
    `).join("");

    el.querySelectorAll("[data-delete-plant]").forEach(btn => {
      btn.addEventListener("click", async () => {
        if (!confirm("Remove this plant from your library?")) return;
        const pid = btn.dataset.deletePlant;
        await del(`/plants/${pid}`).catch(e => alert(e.message));
        await renderLibrary();
      });
    });
  }

  // OpenFarm search
  document.getElementById("btn-search-openfarm").addEventListener("click", doSearch);
  document.getElementById("openfarm-search").addEventListener("keydown", e => {
    if (e.key === "Enter") doSearch();
  });

  async function doSearch() {
    const q = document.getElementById("openfarm-search").value.trim();
    if (!q) return;
    const el = document.getElementById("search-results");
    el.innerHTML = '<div class="empty-state">Searching…</div>';
    try {
      const results = await get(`/plants/search?q=${encodeURIComponent(q)}`);
      if (!results.length) {
        el.innerHTML = '<div class="empty-state">No results found.</div>';
        return;
      }
      state.searchResults = results;
      el.innerHTML = results.map((p, i) => `
        <div class="plant-card">
          <div class="plant-card-header">
            <div>
              <div class="plant-card-name">${escapeHtml(p.name)}</div>
              <div class="plant-card-meta">${escapeHtml(p.sun_requirements || "")}${p.days_to_maturity_min ? ` · ${p.days_to_maturity_min} days` : ""}</div>
            </div>
            <button class="btn btn-primary btn-sm" data-save-idx="${i}">+ Save</button>
          </div>
          ${p.description ? `<div class="plant-card-meta" style="margin-top:6px">${escapeHtml(p.description.substring(0, 120))}…</div>` : ""}
        </div>
      `).join("");

      el.querySelectorAll("[data-save-idx]").forEach(btn => {
        btn.addEventListener("click", async () => {
          const plantData = state.searchResults[parseInt(btn.dataset.saveIdx, 10)];
          if (!plantData) return;
          btn.textContent = "Saving…";
          btn.disabled = true;
          try {
            await post("/plants", plantData);
            btn.textContent = "Saved ✓";
            if (document.querySelector(".tab.active")?.dataset.tab === "library") {
              await renderLibrary();
            } else {
              state.plants = await get("/plants");
            }
            populatePlantDropdown();
          } catch (e) {
            btn.textContent = e.message.includes("409") ? "Already saved" : "Error";
            btn.disabled = false;
          }
        });
      });
    } catch (e) {
      el.innerHTML = `<div class="empty-state">Error: ${e.message}</div>`;
    }
  }

  // Custom plant form
  document.getElementById("btn-custom-plant").addEventListener("click", () => {
    const el = document.getElementById("search-results");
    el.innerHTML = `
      <div class="form-card">
        <h3>Add Custom Plant</h3>
        <div class="form-group"><label>Name *</label><input type="text" id="custom-name" /></div>
        <div class="form-group"><label>Sun requirements</label><input type="text" id="custom-sun" placeholder="e.g. Full sun" /></div>
        <div class="form-group"><label>Sowing method</label><input type="text" id="custom-sow" placeholder="e.g. Direct sow" /></div>
        <div class="form-group"><label>Days to maturity</label><input type="number" id="custom-days" placeholder="e.g. 60" /></div>
        <div class="form-group"><label>Notes</label><textarea id="custom-desc"></textarea></div>
        <div style="display:flex;gap:8px">
          <button class="btn btn-primary btn-sm" id="btn-save-custom">Save</button>
          <button class="btn btn-ghost btn-sm" id="btn-cancel-custom">Cancel</button>
        </div>
      </div>`;

    document.getElementById("btn-save-custom").addEventListener("click", async () => {
      const name = document.getElementById("custom-name").value.trim();
      if (!name) { alert("Name is required."); return; }
      try {
        await post("/plants", {
          name,
          sun_requirements: document.getElementById("custom-sun").value.trim() || null,
          sowing_method: document.getElementById("custom-sow").value.trim() || null,
          days_to_maturity_min: parseInt(document.getElementById("custom-days").value) || null,
          description: document.getElementById("custom-desc").value.trim() || null,
          is_custom: true,
        });
        el.innerHTML = '<div class="empty-state">Plant added to library.</div>';
        await renderLibrary();
        populatePlantDropdown();
      } catch (e) {
        alert("Error: " + e.message);
      }
    });

    document.getElementById("btn-cancel-custom").addEventListener("click", () => {
      el.innerHTML = "";
    });
  });

  // ── Plantings ────────────────────────────────────────────────────────────────
  async function renderPlantings() {
    await loadAllDataForPlantings();
    renderPlantingsList();
  }

  async function loadAllDataForPlantings() {
    const [gardens, plants, plantings] = await Promise.all([
      get("/garden"),
      get("/plants"),
      get("/plantings?status=active"),
    ]);
    state.gardens = gardens;
    state.plants = plants;
    state.plantings = plantings;
    populatePlantingGardenDropdowns();
    populatePlantDropdown();
  }

  function populatePlantingGardenDropdowns() {
    const opts = state.gardens.map(g => `<option value="${g.id}">${escapeHtml(g.name)}</option>`).join("");
    const filterOpts = '<option value="">All gardens</option>' + opts;

    const sel = document.getElementById("planting-garden-select");
    const filterSel = document.getElementById("plantings-filter-garden");
    if (sel) sel.innerHTML = '<option value="">— select —</option>' + opts;
    if (filterSel) filterSel.innerHTML = filterOpts;
  }

  function populatePlantDropdown() {
    const sel = document.getElementById("planting-plant-select");
    if (!sel) return;
    sel.innerHTML = '<option value="">— select —</option>' +
      state.plants.map(p => `<option value="${p.id}">${escapeHtml(p.name)}</option>`).join("");
  }

  document.getElementById("btn-log-planting").addEventListener("click", async () => {
    const gardenId = document.getElementById("planting-garden-select").value;
    const plantId = document.getElementById("planting-plant-select").value;
    const date = document.getElementById("planting-date").value;
    const qty = document.getElementById("planting-quantity").value;
    const notes = document.getElementById("planting-notes").value.trim();

    if (!gardenId) { alert("Select a garden."); return; }
    if (!plantId) { alert("Select a plant."); return; }
    if (!date) { alert("Enter the date planted."); return; }

    try {
      await post("/plantings", {
        garden_id: parseInt(gardenId),
        plant_id: parseInt(plantId),
        planted_date: date,
        quantity: qty ? parseInt(qty) : null,
        notes: notes || null,
      });

      // Reset form fields
      document.getElementById("planting-garden-select").value = "";
      document.getElementById("planting-plant-select").value = "";
      document.getElementById("planting-date").value = "";
      document.getElementById("planting-quantity").value = "";
      document.getElementById("planting-notes").value = "";

      await renderPlantings();
    } catch (e) {
      alert("Error: " + e.message);
    }
  });

  document.getElementById("plantings-filter-garden").addEventListener("change", () => {
    renderPlantingsList();
  });

  function renderPlantingsList() {
    const filterGid = parseInt(document.getElementById("plantings-filter-garden").value) || null;
    const el = document.getElementById("plantings-list");

    let items = state.plantings;
    if (filterGid) items = items.filter(p => p.garden_id === filterGid);

    if (!items.length) {
      el.innerHTML = '<div class="empty-state">No active plantings.</div>';
      return;
    }

    // Group by garden
    const byGarden = {};
    items.forEach(p => {
      const key = `${p.garden_id}`;
      if (!byGarden[key]) byGarden[key] = { gardenName: p.garden_name, items: [] };
      byGarden[key].items.push(p);
    });

    el.innerHTML = Object.values(byGarden).map(group => `
      <div class="section-label">${group.gardenName}</div>
      ${group.items.map(p => `
        <div class="planting-card">
          <div class="planting-card-header">
            <div>
              <div class="planting-card-name">${p.plant_name}</div>
              <div class="planting-card-meta">
                Planted ${p.planted_date}${p.quantity ? ` · qty ${p.quantity}` : ""}
              </div>
              ${p.notes ? `<div class="planting-card-meta">${p.notes}</div>` : ""}
            </div>
            <span class="status-chip ${p.status}">${p.status}</span>
          </div>
          <div class="planting-actions">
            <button class="btn btn-ghost btn-sm" data-harvest="${p.id}">Harvested</button>
            <button class="btn btn-ghost btn-sm" data-remove="${p.id}">Remove</button>
          </div>
        </div>
      `).join("")}
    `).join("");

    el.querySelectorAll("[data-harvest]").forEach(btn => {
      btn.addEventListener("click", async () => {
        await put(`/plantings/${btn.dataset.harvest}`, {
          status: "harvested",
          removed_date: new Date().toISOString().slice(0, 10),
        }).catch(e => alert(e.message));
        await renderPlantings();
      });
    });

    el.querySelectorAll("[data-remove]").forEach(btn => {
      btn.addEventListener("click", async () => {
        if (!confirm("Mark this planting as removed?")) return;
        await put(`/plantings/${btn.dataset.remove}`, {
          status: "removed",
          removed_date: new Date().toISOString().slice(0, 10),
        }).catch(e => alert(e.message));
        await renderPlantings();
      });
    });
  }

  // ── Boot ───────────────────────────────────────────────────────────────────
  async function boot() {
    await loadGardens();

    // If there's exactly one garden, auto-select it
    if (state.gardens.length === 1) {
      state.activeGardenId = state.gardens[0].id;
      renderGardensList();
      await loadGardenBoard();
    } else {
      renderGrid();
    }
  }

})();
