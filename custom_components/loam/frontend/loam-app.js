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
  const CELL = 26; // pixels per foot — keep in sync with --cell in loam-panel.html

  const state = {
    gardens: [],
    activeGardenId: null,
    beds: [],
    plants: [],
    plantings: [],
    drawing: false,
    selectedBedId: null,
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
      if (tab.dataset.tab === "garden") renderGrid();
    });
  });

  // ── Grid elements ──────────────────────────────────────────────────────────
  const canvas = document.getElementById("grid-canvas");
  const gridEmpty = document.getElementById("grid-empty");

  function renderGrid() {
    const g = activeGarden();
    if (!g) {
      canvas.style.display = "none";
      gridEmpty.style.display = "flex";
      return;
    }
    gridEmpty.style.display = "none";
    canvas.style.display = "block";

    const w = g.width_ft || 1;
    const h = g.height_ft || 1;
    canvas.style.width = (w * CELL) + "px";
    canvas.style.height = (h * CELL) + "px";

    canvas.innerHTML = "";
    state.beds.forEach(bed => {
      if (bed.grid_w == null || bed.grid_h == null) return; // skip beds with no footprint
      const div = document.createElement("div");
      div.className = "bed-rect" + (bed.id === state.selectedBedId ? " selected" : "");
      div.style.left   = (bed.grid_x * CELL) + "px";
      div.style.top    = (bed.grid_y * CELL) + "px";
      div.style.width  = (bed.grid_w * CELL) + "px";
      div.style.height = (bed.grid_h * CELL) + "px";
      div.innerHTML = `<span class="bed-rect-label">${escapeHtml(bed.name)}</span>`;
      div.addEventListener("click", e => {
        if (state.drawing) return;
        e.stopPropagation();
        selectBed(bed.id);
      });
      canvas.appendChild(div);
    });
  }

  // ── Bed drawing (snap to 1-ft cells) ─────────────────────────────────────────
  let dragStart = null;
  let selRect = null;
  let pendingBed = null;

  function cellFromEvent(e) {
    const g = activeGarden();
    const r = canvas.getBoundingClientRect();
    let cx = Math.floor((e.clientX - r.left) / CELL);
    let cy = Math.floor((e.clientY - r.top) / CELL);
    cx = Math.max(0, Math.min(cx, g.width_ft - 1));
    cy = Math.max(0, Math.min(cy, g.height_ft - 1));
    return { cx, cy };
  }

  function normalizeCells(sx, sy, ex, ey) {
    return {
      grid_x: Math.min(sx, ex),
      grid_y: Math.min(sy, ey),
      grid_w: Math.abs(ex - sx) + 1,
      grid_h: Math.abs(ey - sy) + 1,
    };
  }

  function paintSelection(rect) {
    if (!selRect) return;
    selRect.style.left   = (rect.grid_x * CELL) + "px";
    selRect.style.top    = (rect.grid_y * CELL) + "px";
    selRect.style.width  = (rect.grid_w * CELL) + "px";
    selRect.style.height = (rect.grid_h * CELL) + "px";
  }

  function rectsOverlap(a, b) {
    return a.grid_x < b.grid_x + b.grid_w &&
           a.grid_x + a.grid_w > b.grid_x &&
           a.grid_y < b.grid_y + b.grid_h &&
           a.grid_y + a.grid_h > b.grid_y;
  }

  canvas.addEventListener("mousedown", e => {
    if (!state.drawing) return;
    e.preventDefault();
    const { cx, cy } = cellFromEvent(e);
    dragStart = { cx, cy };
    selRect = document.createElement("div");
    selRect.className = "draw-selection";
    canvas.appendChild(selRect);
    paintSelection(normalizeCells(cx, cy, cx, cy));
  });

  canvas.addEventListener("mousemove", e => {
    if (!state.drawing || !dragStart) return;
    const { cx, cy } = cellFromEvent(e);
    paintSelection(normalizeCells(dragStart.cx, dragStart.cy, cx, cy));
  });

  window.addEventListener("mouseup", e => {
    if (!state.drawing || !dragStart) return;
    const { cx, cy } = cellFromEvent(e);
    const rect = normalizeCells(dragStart.cx, dragStart.cy, cx, cy);
    dragStart = null;
    if (selRect) { selRect.remove(); selRect = null; }

    if (state.beds.some(b => b.grid_w != null && rectsOverlap(rect, b))) {
      alert("Beds can't overlap. Try a different spot.");
      return;
    }
    pendingBed = rect;
    showBedForm(rect);
  });

  function enterDrawMode() {
    if (!state.activeGardenId) return;
    state.drawing = true;
    canvas.classList.add("drawing");
    document.getElementById("btn-add-bed").textContent = "Cancel";
  }

  function exitDrawMode() {
    state.drawing = false;
    canvas.classList.remove("drawing");
    if (selRect) { selRect.remove(); selRect = null; }
    dragStart = null;
    document.getElementById("btn-add-bed").textContent = "+ Bed";
  }

  // ── Garden selector ──────────────────────────────────────────────────────────
  async function loadGardens() {
    state.gardens = await get("/garden");
    const sel = document.getElementById("garden-select");
    const prev = state.activeGardenId;
    sel.innerHTML = '<option value="">— select garden —</option>' +
      state.gardens.map(g => `<option value="${g.id}">${escapeHtml(g.name)}</option>`).join("");
    if (prev && state.gardens.find(g => g.id === prev)) sel.value = prev;
    populatePlantingGardenDropdowns();
  }

  document.getElementById("garden-select").addEventListener("change", async e => {
    const id = parseInt(e.target.value, 10);
    state.activeGardenId = id || null;
    state.selectedBedId = null;
    exitDrawMode();
    document.getElementById("btn-add-bed").style.display = id ? "inline-block" : "none";
    await loadBeds();
  });

  document.getElementById("btn-new-garden").addEventListener("click", showGardenForm);

  function showGardenForm() {
    const list = document.getElementById("beds-list");
    if (document.getElementById("new-garden-form")) return;
    list.insertAdjacentHTML("afterbegin", `
      <div class="bed-form" id="new-garden-form">
        <h3>New garden</h3>
        <div class="form-group">
          <label>Name</label>
          <input type="text" id="ng-name" placeholder="e.g. Backyard" />
        </div>
        <div class="form-group">
          <label>Width (feet)</label>
          <input type="number" id="ng-width" min="1" max="200" value="20" />
        </div>
        <div class="form-group">
          <label>Height (feet)</label>
          <input type="number" id="ng-height" min="1" max="200" value="20" />
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
      renderBedList();
    });
    document.getElementById("ng-name").focus();
  }

  async function saveNewGarden() {
    const name = document.getElementById("ng-name").value.trim();
    const w = parseInt(document.getElementById("ng-width").value, 10);
    const h = parseInt(document.getElementById("ng-height").value, 10);
    if (!name) { alert("Name is required."); return; }
    if (!(w >= 1 && w <= 200) || !(h >= 1 && h <= 200)) {
      alert("Width and height must be between 1 and 200 feet.");
      return;
    }
    try {
      const g = await post("/garden", { name, width_ft: w, height_ft: h });
      state.activeGardenId = g.id;
      state.selectedBedId = null;
      await loadGardens();
      document.getElementById("garden-select").value = g.id;
      document.getElementById("btn-add-bed").style.display = "inline-block";
      await loadBeds();
    } catch (err) {
      alert("Error: " + err.message);
    }
  }

  // ── Beds ─────────────────────────────────────────────────────────────────────
  async function loadBeds() {
    if (state.activeGardenId) {
      state.beds = await get(`/beds?garden_id=${state.activeGardenId}`);
    } else {
      state.beds = [];
    }
    renderBedList();
    renderGrid();
  }

  function renderBedList() {
    const el = document.getElementById("beds-list");
    if (!state.activeGardenId) { el.innerHTML = ""; return; }
    if (!state.beds.length) {
      el.innerHTML = '<div class="empty-state">No beds yet.<br/>Click “+ Bed”, then drag on the grid to draw one.</div>';
      return;
    }
    el.innerHTML =
      '<div class="grid-hint">Each square is 1 ft. Click “+ Bed”, then drag across the grid to lay one out.</div>' +
      state.beds.map(bed => {
        const typeLabel = bed.type.replace("_", " ");
        const size = (bed.grid_w != null && bed.grid_h != null)
          ? `${bed.grid_w}×${bed.grid_h} ft · ` : "";
        const sel = bed.id === state.selectedBedId ? " selected" : "";
        return `
          <div class="bed-card${sel}" data-bed-id="${bed.id}">
            <div class="bed-card-header">
              <span class="bed-name">${escapeHtml(bed.name)}</span>
              <span class="bed-badge ${bed.type}">${typeLabel}</span>
            </div>
            <div class="bed-meta">${size}${bed.planting_count} active planting${bed.planting_count !== 1 ? "s" : ""}</div>
            <div class="planting-actions">
              <button class="btn btn-danger btn-sm" data-delete-bed="${bed.id}">Delete</button>
            </div>
          </div>`;
      }).join("");

    el.querySelectorAll(".bed-card").forEach(card => {
      card.addEventListener("click", e => {
        if (e.target.closest("[data-delete-bed]")) return;
        selectBed(parseInt(card.dataset.bedId, 10));
      });
    });

    el.querySelectorAll("[data-delete-bed]").forEach(btn => {
      btn.addEventListener("click", async e => {
        e.stopPropagation();
        if (!confirm("Delete this bed? Its plantings will be removed too.")) return;
        const id = parseInt(btn.dataset.deleteBed, 10);
        await del(`/beds/${id}`).catch(err => alert(err.message));
        if (state.selectedBedId === id) state.selectedBedId = null;
        await loadBeds();
      });
    });
  }

  function selectBed(id) {
    state.selectedBedId = (state.selectedBedId === id) ? null : id;
    renderGrid();
    renderBedList();
  }

  document.getElementById("btn-add-bed").addEventListener("click", () => {
    if (!state.activeGardenId) return;
    if (state.drawing) exitDrawMode();
    else enterDrawMode();
  });

  // ── Bed form (shown after drawing) ──────────────────────────────────────────
  function showBedForm(rect) {
    exitDrawMode();
    const list = document.getElementById("beds-list");
    const existing = document.getElementById("new-bed-form");
    if (existing) existing.remove();
    list.insertAdjacentHTML("afterbegin", `
      <div class="bed-form" id="new-bed-form">
        <h3>New bed · ${rect.grid_w} × ${rect.grid_h} ft</h3>
        <div class="form-group">
          <label>Name</label>
          <input type="text" id="new-bed-name" placeholder="e.g. South Raised Bed" />
        </div>
        <div class="form-group">
          <label>Type</label>
          <select id="new-bed-type">
            <option value="raised_bed">Raised Bed</option>
            <option value="in_ground">In Ground</option>
            <option value="container">Container</option>
            <option value="grow_bag">Grow Bag</option>
          </select>
        </div>
        <div class="form-group">
          <label>Notes (optional)</label>
          <textarea id="new-bed-notes"></textarea>
        </div>
        <div style="display:flex;gap:8px">
          <button class="btn btn-primary btn-sm" id="btn-save-bed">Save</button>
          <button class="btn btn-ghost btn-sm" id="btn-cancel-bed">Cancel</button>
        </div>
      </div>
    `);

    document.getElementById("btn-save-bed").addEventListener("click", () => saveNewBed(rect));
    document.getElementById("btn-cancel-bed").addEventListener("click", () => {
      pendingBed = null;
      renderBedList();
    });
    document.getElementById("new-bed-name").focus();
  }

  async function saveNewBed(rect) {
    const name = document.getElementById("new-bed-name").value.trim();
    if (!name) { alert("Name is required."); return; }
    const bedType = document.getElementById("new-bed-type").value;
    const notes = document.getElementById("new-bed-notes").value.trim();

    try {
      await post("/beds", {
        garden_id: state.activeGardenId,
        name,
        type: bedType,
        grid_x: rect.grid_x,
        grid_y: rect.grid_y,
        grid_w: rect.grid_w,
        grid_h: rect.grid_h,
        notes: notes || null,
      });
      pendingBed = null;
      await loadBeds();
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
            <div class="plant-card-name">${p.name}</div>
            <div class="plant-card-meta">${p.sun_requirements || ""}${p.days_to_maturity_min ? ` · ${p.days_to_maturity_min} days` : ""}</div>
          </div>
          <button class="btn btn-danger btn-sm" data-delete-plant="${p.id}">✕</button>
        </div>
        ${p.description ? `<div class="plant-card-meta" style="margin-top:6px">${p.description}</div>` : ""}
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
      el.innerHTML = results.map(p => `
        <div class="plant-card">
          <div class="plant-card-header">
            <div>
              <div class="plant-card-name">${p.name}</div>
              <div class="plant-card-meta">${p.sun_requirements || ""}${p.days_to_maturity_min ? ` · ${p.days_to_maturity_min} days` : ""}</div>
            </div>
            <button class="btn btn-primary btn-sm" data-save-plant='${JSON.stringify(p)}'>+ Save</button>
          </div>
          ${p.description ? `<div class="plant-card-meta" style="margin-top:6px">${p.description.substring(0, 120)}…</div>` : ""}
        </div>
      `).join("");

      el.querySelectorAll("[data-save-plant]").forEach(btn => {
        btn.addEventListener("click", async () => {
          const plantData = JSON.parse(btn.dataset.savePlant);
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
      <div class="bed-form">
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
      state.plants.map(p => `<option value="${p.id}">${p.name}</option>`).join("");
  }

  document.getElementById("planting-garden-select").addEventListener("change", async e => {
    const gid = parseInt(e.target.value) || null;
    const bedSel = document.getElementById("planting-bed-select");
    if (!gid) {
      bedSel.innerHTML = '<option value="">— select garden first —</option>';
      return;
    }
    const beds = await get(`/beds?garden_id=${gid}`);
    bedSel.innerHTML = '<option value="">— select bed —</option>' +
      beds.map(b => `<option value="${b.id}">${b.name}</option>`).join("");
  });

  document.getElementById("btn-log-planting").addEventListener("click", async () => {
    const bedId = document.getElementById("planting-bed-select").value;
    const plantId = document.getElementById("planting-plant-select").value;
    const date = document.getElementById("planting-date").value;
    const qty = document.getElementById("planting-quantity").value;
    const notes = document.getElementById("planting-notes").value.trim();

    if (!bedId) { alert("Select a bed."); return; }
    if (!plantId) { alert("Select a plant."); return; }
    if (!date) { alert("Enter the date planted."); return; }

    try {
      await post("/plantings", {
        bed_id: parseInt(bedId),
        plant_id: parseInt(plantId),
        planted_date: date,
        quantity: qty ? parseInt(qty) : null,
        notes: notes || null,
      });

      // Reset form fields
      document.getElementById("planting-bed-select").innerHTML = '<option value="">— select garden first —</option>';
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

    // Group by bed
    const byBed = {};
    items.forEach(p => {
      const key = `${p.bed_id}`;
      if (!byBed[key]) byBed[key] = { bedName: p.bed_name, items: [] };
      byBed[key].items.push(p);
    });

    el.innerHTML = Object.values(byBed).map(group => `
      <div class="section-label">${group.bedName}</div>
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
      const g = state.gardens[0];
      state.activeGardenId = g.id;
      document.getElementById("garden-select").value = g.id;
      document.getElementById("btn-add-bed").style.display = "inline-block";
      await loadBeds();
    } else {
      renderGrid();
    }
  }

})();
