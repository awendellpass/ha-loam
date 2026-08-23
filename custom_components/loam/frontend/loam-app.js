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

  function addDaysISO(dateStr, days) {
    if (!dateStr || days == null) return null;
    const d = new Date(dateStr + "T00:00:00");
    if (isNaN(d.getTime())) return null;
    d.setDate(d.getDate() + Number(days));
    return d.toISOString().slice(0, 10);
  }

  function harvestLine(p) {
    if (!p.days_to_maturity_min) {
      return 'Est. harvest: — <span style="opacity:.7">(set days to maturity in Library)</span>';
    }
    const h = addDaysISO(p.planted_date, p.days_to_maturity_min);
    return h ? `Est. harvest ~ ${h} (${p.days_to_maturity_min} days)` : "Est. harvest: —";
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

      if (tab.dataset.tab === "plantings") renderPlantings();
      if (tab.dataset.tab === "garden")    loadGardenBoard();
      if (tab.dataset.tab === "calendar")  loadCalendar();
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
      hint.textContent = "No plants yet — add some in the Plants & Plantings tab first.";
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
      el.innerHTML = '<div class="empty-state">No plants yet.<br/>Search above or add a custom plant.</div>';
      return;
    }
    el.innerHTML = state.plants.map(p => `
      <div class="plant-card">
        <div class="plant-card-header">
          <div>
            <div class="plant-card-name">${escapeHtml(p.name)}</div>
            ${p.scientific_name ? `<div class="plant-card-latin">${escapeHtml(p.scientific_name)}</div>` : ""}
          </div>
          <div style="display:flex;align-items:center;gap:4px">
            <button class="wishlist-btn${p.wishlist ? " wishlisted" : ""}" data-wishlist-plant="${p.id}" title="${p.wishlist ? "Remove from wishlist" : "Add to calendar wishlist"}">${p.wishlist ? "★" : "☆"}</button>
            <button class="btn btn-danger btn-sm" data-delete-plant="${p.id}">✕</button>
          </div>
        </div>
        <div class="edit-row">
          <label>Days to maturity</label>
          <input type="number" min="0" class="num-input" data-dtm="${p.id}" value="${p.days_to_maturity_min ?? ""}" placeholder="—" />
          <button class="btn btn-ghost btn-sm" data-save-dtm="${p.id}">Save</button>
        </div>
        <div class="plant-card-meta">Sun: ${escapeHtml(p.sun_requirements || "—")}</div>
        ${p.is_custom ? '<div class="plant-card-meta" style="color:#66bb6a">Custom</div>' : ""}
      </div>
    `).join("");

    el.querySelectorAll("[data-wishlist-plant]").forEach(btn => {
      btn.addEventListener("click", async () => {
        const pid = btn.dataset.wishlistPlant;
        const plant = state.plants.find(x => String(x.id) === pid);
        if (!plant) return;
        const newVal = !plant.wishlist;
        try {
          const updated = await put(`/plants/${pid}`, { wishlist: newVal });
          plant.wishlist = updated.wishlist;
          btn.textContent = plant.wishlist ? "★" : "☆";
          btn.classList.toggle("wishlisted", !!plant.wishlist);
          btn.title = plant.wishlist ? "Remove from wishlist" : "Add to calendar wishlist";
        } catch (e) {
          alert(e.message);
        }
      });
    });

    el.querySelectorAll("[data-delete-plant]").forEach(btn => {
      btn.addEventListener("click", async () => {
        if (!confirm("Remove this plant from your library?")) return;
        const pid = btn.dataset.deletePlant;
        await del(`/plants/${pid}`).catch(e => alert(e.message));
        await renderLibrary();
      });
    });

    el.querySelectorAll("[data-save-dtm]").forEach(btn => {
      btn.addEventListener("click", async () => {
        const pid = btn.dataset.saveDtm;
        const input = el.querySelector(`.num-input[data-dtm="${pid}"]`);
        const val = input.value.trim();
        try {
          await put(`/plants/${pid}`, { days_to_maturity_min: val === "" ? null : parseInt(val, 10) });
          btn.textContent = "Saved ✓";
          setTimeout(() => { btn.textContent = "Save"; }, 1200);
          // keep local copy fresh so plantings harvest dates pick it up
          const plant = state.plants.find(x => String(x.id) === pid);
          if (plant) plant.days_to_maturity_min = val === "" ? null : parseInt(val, 10);
        } catch (e) {
          alert(e.message);
        }
      });
    });
  }

  // OpenFarm search
  document.getElementById("btn-search-openfarm").addEventListener("click", doSearch);
  document.getElementById("openfarm-search").addEventListener("keydown", e => {
    if (e.key === "Enter") doSearch();
  });

  function openSearchRegion() {
    document.getElementById("search-region").classList.add("open");
  }

  function closeSearchRegion() {
    document.getElementById("search-region").classList.remove("open");
    document.getElementById("search-results").innerHTML = "";
    state.searchResults = [];
  }

  document.getElementById("btn-clear-search").addEventListener("click", () => {
    document.getElementById("openfarm-search").value = "";
    closeSearchRegion();
  });

  async function doSearch() {
    const q = document.getElementById("openfarm-search").value.trim();
    if (!q) { closeSearchRegion(); return; }
    openSearchRegion();
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
              ${p.scientific_name ? `<div class="plant-card-latin">${escapeHtml(p.scientific_name)}</div>` : ""}
            </div>
            <button class="btn btn-primary btn-sm" data-save-idx="${i}">+ Save</button>
          </div>
          <div class="plant-card-meta">Sun: ${escapeHtml(p.sun_requirements || "—")}</div>
        </div>
      `).join("");

      el.querySelectorAll("[data-save-idx]").forEach(btn => {
        btn.addEventListener("click", async () => {
          const plantData = state.searchResults[parseInt(btn.dataset.saveIdx, 10)];
          if (!plantData) return;
          btn.textContent = "Saving…";  // Claude is estimating days to maturity
          btn.disabled = true;
          try {
            await post("/plants", plantData);
            btn.textContent = "Saved ✓";
            await renderLibrary();
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
    openSearchRegion();
    const el = document.getElementById("search-results");
    el.innerHTML = `
      <div class="form-card">
        <h3>Add Custom Plant</h3>
        <div class="form-group"><label>Name *</label><input type="text" id="custom-name" /></div>
        <div class="form-group"><label>Scientific name</label><input type="text" id="custom-latin" placeholder="e.g. Solanum lycopersicum" /></div>
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
          scientific_name: document.getElementById("custom-latin").value.trim() || null,
          sun_requirements: document.getElementById("custom-sun").value.trim() || null,
          sowing_method: document.getElementById("custom-sow").value.trim() || null,
          days_to_maturity_min: parseInt(document.getElementById("custom-days").value) || null,
          description: document.getElementById("custom-desc").value.trim() || null,
          is_custom: true,
        });
        closeSearchRegion();
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
    renderPlantLibrary();
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

  // The grid is the main way to plant; manual logging is an opt-in form.
  document.getElementById("btn-toggle-log").addEventListener("click", () => {
    const form = document.getElementById("manual-log-form");
    const show = form.style.display === "none";
    form.style.display = show ? "block" : "none";
    document.getElementById("btn-toggle-log").textContent = show ? "Close" : "+ Log manually";
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
              <div class="planting-card-name">${escapeHtml(p.plant_name)}</div>
              <div class="planting-card-meta edit-row">
                <label>Planted</label>
                <input type="date" class="date-input" data-planted="${p.id}" value="${p.planted_date}" />
                ${p.quantity ? `<span>· qty ${p.quantity}</span>` : ""}
              </div>
              <div class="planting-card-meta">${harvestLine(p)}</div>
              ${p.notes ? `<div class="planting-card-meta">${escapeHtml(p.notes)}</div>` : ""}
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

    el.querySelectorAll("[data-planted]").forEach(input => {
      input.addEventListener("change", async () => {
        if (!input.value) return;
        try {
          await put(`/plantings/${input.dataset.planted}`, { planted_date: input.value });
          await renderPlantings();
        } catch (e) {
          alert(e.message);
        }
      });
    });

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

  // ── Calendar ─────────────────────────────────────────────────────────────────
  // Display range: March 1 → October 31 (245 days).
  // All months calculated for a non-leap year; close enough for display positioning.
  const CAL_MONTHS = [
    { name: "Mar", doy: 60,  days: 31 },
    { name: "Apr", doy: 91,  days: 30 },
    { name: "May", doy: 121, days: 31 },
    { name: "Jun", doy: 152, days: 30 },
    { name: "Jul", doy: 182, days: 31 },
    { name: "Aug", doy: 213, days: 31 },
    { name: "Sep", doy: 244, days: 30 },
    { name: "Oct", doy: 274, days: 31 },
  ];
  const CAL_START = 60;   // March 1 day-of-year
  const CAL_END   = 305;  // November 1 day-of-year (exclusive)
  const CAL_DAYS  = CAL_END - CAL_START; // 245

  function doyFromDate(year, month, day) {
    const d = new Date(year, month - 1, day);
    return Math.round((d - new Date(year, 0, 1)) / 86400000) + 1;
  }

  function frostDoy(frostMd, year) {
    const [mm, dd] = frostMd.split("-").map(Number);
    return doyFromDate(year, mm, dd);
  }

  function weekToPct(weekOffset, fdoy) {
    const doy = fdoy + weekOffset * 7;
    return Math.max(0, Math.min(100, (doy - CAL_START) / CAL_DAYS * 100));
  }

  function todayPct() {
    const t = new Date();
    const doy = doyFromDate(t.getFullYear(), t.getMonth() + 1, t.getDate());
    if (doy < CAL_START || doy > CAL_END) return null;
    return (doy - CAL_START) / CAL_DAYS * 100;
  }

  // Shared month-grid HTML injected into each bars area.
  function monthGridHtml() {
    return CAL_MONTHS.slice(1).map(m => {
      const pct = ((m.doy - CAL_START) / CAL_DAYS * 100).toFixed(2);
      return `<div class="cal-grid-line" style="left:${pct}%"></div>`;
    }).join("");
  }

  function barsHtml(ph, fdoy) {
    if (!ph) {
      return '<div class="cal-bar pending"></div>';
    }
    const bars = [];

    // Start-indoors bar: from start_indoors_week → first outdoor event.
    if (ph.start_indoors_week != null) {
      const endW = ph.transplant_week ?? ph.direct_sow_week;
      if (endW != null && endW > ph.start_indoors_week) {
        const l = weekToPct(ph.start_indoors_week, fdoy);
        const r = weekToPct(endW, fdoy);
        if (r > l) bars.push(`<div class="cal-bar indoor" style="left:${l.toFixed(1)}%;width:${(r-l).toFixed(1)}%"></div>`);
      }
    }

    // Plant/transplant bar: outdoor planting → harvest or bloom start.
    const plantW = ph.transplant_week ?? ph.direct_sow_week;
    const plantEndW = ph.harvest_start_week ?? ph.bloom_start_week;
    if (plantW != null && plantEndW != null && plantEndW > plantW) {
      const l = weekToPct(plantW, fdoy);
      const r = weekToPct(plantEndW, fdoy);
      if (r > l) bars.push(`<div class="cal-bar plant" style="left:${l.toFixed(1)}%;width:${(r-l).toFixed(1)}%"></div>`);
    }

    // Harvest bar.
    if (ph.harvest_start_week != null && ph.harvest_end_week != null) {
      const l = weekToPct(ph.harvest_start_week, fdoy);
      const r = weekToPct(ph.harvest_end_week, fdoy);
      if (r > l) bars.push(`<div class="cal-bar harvest" style="left:${l.toFixed(1)}%;width:${(r-l).toFixed(1)}%"></div>`);
    }

    // Bloom bar (ornamentals — color from Ollama).
    if (ph.bloom_start_week != null && ph.bloom_end_week != null) {
      const l = weekToPct(ph.bloom_start_week, fdoy);
      const r = weekToPct(ph.bloom_end_week, fdoy);
      if (r > l) {
        const color = ph.bloom_color || "#9c27b0";
        bars.push(`<div class="cal-bar" style="left:${l.toFixed(1)}%;width:${(r-l).toFixed(1)}%;background:${escapeHtml(color)}"></div>`);
      }
    }

    if (!bars.length) bars.push('<div class="cal-bar pending"></div>');
    return bars.join("");
  }

  function renderCalendar(calData) {
    const body = document.getElementById("cal-body");
    const { frost_date, frost_from_config, sections } = calData;

    // Update frost display in header.
    document.getElementById("cal-frost-display").textContent = frost_date || "—";
    const fromCfg = document.getElementById("cal-frost-from-config");
    fromCfg.style.display = frost_from_config ? "inline" : "none";
    document.getElementById("btn-edit-frost").style.display = frost_from_config ? "none" : "inline-block";

    if (!frost_date) {
      body.innerHTML = `
        <div class="cal-no-frost">
          <strong>Set your last frost date to see the calendar.</strong><br/>
          Click <strong>Edit</strong> above and enter your last spring frost date (MM-DD).<br/>
          For the Twin Cities, that's usually <strong>05-07</strong>.
        </div>`;
      return;
    }

    const year = new Date().getFullYear();
    const fdoy = frostDoy(frost_date, year);
    const tPct  = todayPct();

    const todayLine = tPct != null
      ? `<div class="cal-today-line" style="left:${tPct.toFixed(2)}%"></div>`
      : "";
    const grid = monthGridHtml();

    // Month header row.
    const monthsHtml = CAL_MONTHS.map(m => {
      const w = (m.days / CAL_DAYS * 100).toFixed(2);
      return `<div class="cal-month-cell" style="width:${w}%">${m.name}</div>`;
    }).join("");

    function plantRowHtml(p) {
      const wl = p.wishlist;
      return `
        <div class="cal-row">
          <div class="cal-plant-name">
            <button class="cal-wishlist-btn${wl ? " wishlisted" : ""}"
                    data-cal-wishlist="${p.id}"
                    title="${wl ? "Remove from wishlist" : "Add to wishlist"}">${wl ? "★" : "☆"}</button>
            <span class="cal-plant-name-text" title="${escapeHtml(p.name)}">${escapeHtml(p.name)}</span>
          </div>
          <div class="cal-bars-area" data-plant-bars="${p.id}">
            ${grid}${todayLine}${barsHtml(p.phenology, fdoy)}
          </div>
        </div>`;
    }

    const allPlants = sections.flatMap(s => s.plants);
    const hasAny = allPlants.length > 0;

    let html = `
      <div class="cal-inner">
        <div class="cal-month-row">
          <div class="cal-name-col"></div>
          <div class="cal-months-header">${monthsHtml}</div>
        </div>`;

    html += fireflyRowHtml(grid, todayLine);
    html += grantsRowHtml(grid, todayLine);

    if (!hasAny) {
      html += '<div class="cal-empty-state">No plants yet — add some in Plants &amp; Plantings to see the calendar.</div>';
    } else {
      sections.forEach(s => {
        if (!s.plants.length) return;
        html += `
          <div class="cal-section-header">
            <div class="cal-section-label">${s.label}</div>
            <div class="cal-section-line"></div>
          </div>
          ${s.plants.map(plantRowHtml).join("")}`;
      });
    }

    html += "</div>";
    body.innerHTML = html;

    // Wishlist toggles.
    body.querySelectorAll("[data-cal-wishlist]").forEach(btn => {
      btn.addEventListener("click", async () => {
        const pid = btn.dataset.calWishlist;
        const plant = allPlants.find(p => String(p.id) === pid);
        if (!plant) return;
        try {
          const updated = await put(`/plants/${pid}`, { wishlist: !plant.wishlist });
          plant.wishlist = updated.wishlist;
          btn.textContent = plant.wishlist ? "★" : "☆";
          btn.classList.toggle("wishlisted", !!plant.wishlist);
          btn.title = plant.wishlist ? "Remove from wishlist" : "Add to wishlist";
        } catch (e) {
          alert(e.message);
        }
      });
    });

    // Fill in phenology for uncached plants, one at a time.
    const uncached = allPlants.filter(p => !p.phenology);
    if (uncached.length) estimatePhenologySequential(uncached, fdoy, todayLine, grid);
  }

  async function estimatePhenologySequential(plants, fdoy, todayLine, grid) {
    for (const plant of plants) {
      const barsArea = document.querySelector(`[data-plant-bars="${plant.id}"]`);
      if (!barsArea) continue;
      try {
        const result = await post("/phenology", { plant_id: plant.id });
        plant.phenology = result.phenology;
        barsArea.innerHTML = grid + todayLine + barsHtml(plant.phenology, fdoy);
        // If Ollama corrected a Latin name to a common name, update the row label.
        const correctedName = result.phenology._name_updated;
        if (correctedName) {
          plant.name = correctedName;
          const nameSpan = barsArea.parentElement.querySelector(".cal-plant-name-text");
          if (nameSpan) {
            nameSpan.textContent = correctedName;
            nameSpan.title = correctedName;
          }
        }
      } catch (_e) {
        // Leave the pending pulse — phenology unavailable for this plant.
      }
    }
  }

  async function loadCalendar() {
    document.getElementById("cal-body").innerHTML =
      '<div class="cal-empty-state">Loading…</div>';
    try {
      const calData = await get("/calendar");
      renderCalendar(calData);
    } catch (e) {
      document.getElementById("cal-body").innerHTML =
        `<div class="cal-empty-state">Error loading calendar: ${escapeHtml(e.message)}</div>`;
    }
    loadDynamicRows();
  }

  function mdToPct(md) {
    const [mm, dd] = md.split("-").map(Number);
    const doy = doyFromDate(2001, mm, dd); // fixed non-leap reference, matches CAL_MONTHS
    return Math.max(0, Math.min(100, (doy - CAL_START) / CAL_DAYS * 100));
  }

  function lawnBarHtml(startMd, endMd) {
    const l = mdToPct(startMd);
    const r = mdToPct(endMd);
    if (r <= l) return "";
    return `<div class="cal-bar plant" style="left:${l.toFixed(1)}%;width:${(r - l).toFixed(1)}%"></div>`;
  }

  const MONTH_NAMES = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"];
  function mdToLabel(md) {
    const [mm, dd] = md.split("-").map(Number);
    return `${MONTH_NAMES[mm - 1]} ${dd}`;
  }

  // Static estimate, not weather-driven — typical dusk mating-flash window for
  // the Twin Cities. Adjust these two dates if your yard runs earlier/later.
  const FIREFLY_SEASON = { start: "06-15", end: "08-05" };

  function fireflyRowHtml(grid, todayLine) {
    const l = mdToPct(FIREFLY_SEASON.start);
    const r = mdToPct(FIREFLY_SEASON.end);
    const bar = r > l
      ? `<div class="cal-bar plant" style="left:${l.toFixed(1)}%;width:${(r - l).toFixed(1)}%"></div>`
      : "";
    return `
      <div class="cal-section-header">
        <div class="cal-section-label">Firefly Season</div>
        <div class="cal-section-line"></div>
      </div>
      <div class="cal-row" title="Typical dusk-to-dark mating-flash activity — a rough seasonal estimate, not live data">
        <div class="cal-plant-name"><span class="cal-plant-name-text">Fireflies</span></div>
        <div class="cal-bars-area">${grid}${todayLine}${bar}</div>
      </div>
      <div class="cal-caption">${mdToLabel(FIREFLY_SEASON.start)}–${mdToLabel(FIREFLY_SEASON.end)}</div>`;
  }

  // Static, not live-fetched — grant windows are published dates, not weather.
  // Update these every year; sources: dakotaswcd.org (651-480-7777) and
  // bluethumb.org/lawns-to-legumes.
  const GRANT_WINDOWS = {
    lcw: {
      label: "Dakota Co. — Landscaping for Clean Water",
      start: "02-20",
      end: "06-18",
      color: "#2f9e8f",
      tip: "Intro class opens Feb 20; Design Course registration closes Jun 18. " +
           "$250 grant applications open Apr 30 — dakotaswcd.org, 651-480-7777.",
      caption: "Feb 20 – Jun 18 &nbsp;·&nbsp; classes &amp; design course &nbsp;·&nbsp; $250 grant opens Apr 30",
    },
    l2l: {
      label: "MN — Lawns to Legumes",
      color: "#c99a2e",
      tip: "Statewide pollinator-habitat grant, up to $400 reimbursed. Spring 2026 window has closed; " +
           "next window not yet announced — check bluethumb.org/lawns-to-legumes.",
      caption: "Spring 2026 window closed &nbsp;·&nbsp; next window TBD — check bluethumb.org",
    },
  };

  function grantsRowHtml(grid, todayLine) {
    const lcw = GRANT_WINDOWS.lcw;
    const l2l = GRANT_WINDOWS.l2l;
    const lcwL = mdToPct(lcw.start);
    const lcwR = mdToPct(lcw.end);
    const lcwBar = lcwR > lcwL
      ? `<div class="cal-bar" style="left:${lcwL.toFixed(1)}%;width:${(lcwR - lcwL).toFixed(1)}%;background:${lcw.color}"></div>`
      : "";
    return `
      <div class="cal-section-header">
        <div class="cal-section-label">Grants</div>
        <div class="cal-section-line"></div>
      </div>
      <div class="cal-row" title="${escapeHtml(lcw.tip)}">
        <div class="cal-plant-name"><span class="cal-plant-name-text">${lcw.label}</span></div>
        <div class="cal-bars-area">${grid}${todayLine}${lcwBar}</div>
      </div>
      <div class="cal-caption">${lcw.caption}</div>
      <div class="cal-row" title="${escapeHtml(l2l.tip)}">
        <div class="cal-plant-name"><span class="cal-plant-name-text">${l2l.label}</span></div>
        <div class="cal-bars-area">${grid}${todayLine}</div>
      </div>
      <div class="cal-caption">${l2l.caption}</div>`;
  }

  function lawnRowHtml(lawn) {
    const grid = monthGridHtml();
    const tPct = todayPct();
    const todayLine = tPct != null ? `<div class="cal-today-line" style="left:${tPct.toFixed(2)}%"></div>` : "";

    const bars = lawn.available
      ? lawnBarHtml(lawn.spring_start, lawn.spring_end) + lawnBarHtml(lawn.fall_start, lawn.fall_end)
      : '<div class="cal-bar pending"></div>';
    const tip = lawn.available ? lawn.message : "Grass-seed timing unavailable — couldn't reach Open-Meteo.";
    const caption = lawn.available
      ? `Spring: ${mdToLabel(lawn.spring_start)}–${mdToLabel(lawn.spring_end)}` +
        ` &nbsp;·&nbsp; Fall: ${mdToLabel(lawn.fall_start)}–${mdToLabel(lawn.fall_end)}`
      : "Couldn't reach Open-Meteo for soil-temperature data.";

    return `
      <div class="cal-section-header">
        <div class="cal-section-label">Lawn</div>
        <div class="cal-section-line"></div>
      </div>
      <div class="cal-row" title="${escapeHtml(tip)}">
        <div class="cal-plant-name"><span class="cal-plant-name-text">Grass seed</span></div>
        <div class="cal-bars-area">${grid}${todayLine}${bars}</div>
      </div>
      <div class="cal-caption">${caption}</div>`;
  }

  function herbicideRowHtml(h) {
    const grid = monthGridHtml();
    const tPct = todayPct();
    const todayLine = tPct != null ? `<div class="cal-today-line" style="left:${tPct.toFixed(2)}%"></div>` : "";

    const bars = h.available
      ? lawnBarHtml(h.spring_start, h.spring_end) + lawnBarHtml(h.fall_start, h.fall_end)
      : '<div class="cal-bar pending"></div>';
    const tip = h.available ? h.message : "Spray timing unavailable — couldn't reach Open-Meteo.";
    const caption = h.available
      ? `Spring: ${mdToLabel(h.spring_start)}–${mdToLabel(h.spring_end)}` +
        ` &nbsp;·&nbsp; Fall: ${mdToLabel(h.fall_start)}–${mdToLabel(h.fall_end)} (primary)`
      : "Couldn't reach Open-Meteo for spray conditions.";

    return `
      <div class="cal-section-header">
        <div class="cal-section-label">Herbicide</div>
        <div class="cal-section-line"></div>
      </div>
      <div class="cal-row" title="${escapeHtml(tip)}">
        <div class="cal-plant-name"><span class="cal-plant-name-text">Creeping Charlie (triclopyr)</span></div>
        <div class="cal-bars-area">${grid}${todayLine}${bars}</div>
      </div>
      <div class="cal-caption">${caption}</div>`;
  }

  async function loadDynamicRows() {
    const monthRow = document.querySelector("#cal-body .cal-month-row");
    if (!monthRow) return; // no frost date set yet — calendar body isn't built
    // Fetch in parallel but insert as a single block so the two async rows
    // land in a fixed order regardless of which network call resolves first.
    const [herbicide, lawn] = await Promise.all([
      get("/herbicide").catch(() => ({ available: false })),
      get("/lawn").catch(() => ({ available: false })),
    ]);
    monthRow.insertAdjacentHTML("afterend", herbicideRowHtml(herbicide) + lawnRowHtml(lawn));
  }

  // Frost date edit controls.
  document.getElementById("btn-edit-frost").addEventListener("click", () => {
    document.getElementById("cal-frost-edit-row").style.display = "flex";
    document.getElementById("cal-frost-input").focus();
  });

  document.getElementById("btn-cancel-frost").addEventListener("click", () => {
    document.getElementById("cal-frost-edit-row").style.display = "none";
  });

  document.getElementById("btn-save-frost").addEventListener("click", async () => {
    const val = document.getElementById("cal-frost-input").value.trim();
    if (!val) return;
    try {
      await put("/settings", { frost_date: val });
      document.getElementById("cal-frost-edit-row").style.display = "none";
      await loadCalendar();
    } catch (e) {
      alert("Invalid frost date: " + e.message);
    }
  });

  document.getElementById("cal-frost-input").addEventListener("keydown", e => {
    if (e.key === "Enter") document.getElementById("btn-save-frost").click();
    if (e.key === "Escape") document.getElementById("btn-cancel-frost").click();
  });

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
