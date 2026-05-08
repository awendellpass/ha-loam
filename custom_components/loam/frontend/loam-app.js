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
  const state = {
    gardens: [],
    activeGardenId: null,
    beds: [],
    plants: [],
    plantings: [],
    drawingActive: false,
  };

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
      if (tab.dataset.tab === "garden") map.invalidateSize();
    });
  });

  // ── Map setup ──────────────────────────────────────────────────────────────
  const map = L.map("map", { zoomControl: true }).setView([39.5, -98.35], 4);

  L.tileLayer(
    "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    { attribution: "Tiles © Esri", maxZoom: 21 }
  ).addTo(map);

  const drawnItems = new L.FeatureGroup().addTo(map);

  const drawControl = new L.Control.Draw({
    edit: { featureGroup: drawnItems },
    draw: {
      polygon:   { shapeOptions: { color: "#4caf50", fillOpacity: 0.25 } },
      rectangle: { shapeOptions: { color: "#4caf50", fillOpacity: 0.25 } },
      polyline:  false,
      circle:    false,
      circlemarker: false,
      marker:    false,
    },
  });

  let pendingShape = null;

  map.on(L.Draw.Event.CREATED, e => {
    drawnItems.clearLayers();
    drawnItems.addLayer(e.layer);
    pendingShape = e.layer.toGeoJSON();
    showBedForm();
  });

  map.on(L.Draw.Event.EDITED, async e => {
    e.layers.eachLayer(async layer => {
      const bedId = layer.loamBedId;
      if (!bedId) return;
      const geo = JSON.stringify(layer.toGeoJSON());
      await put(`/beds/${bedId}`, { shape_geojson: geo }).catch(() => {});
    });
    await loadBeds();
  });

  map.on(L.Draw.Event.DELETED, async e => {
    e.layers.eachLayer(async layer => {
      if (layer.loamBedId) {
        await del(`/beds/${layer.loamBedId}`).catch(() => {});
      }
    });
    await loadBeds();
  });

  // ── Garden selector ────────────────────────────────────────────────────────
  async function loadGardens() {
    state.gardens = await get("/garden");
    const sel = document.getElementById("garden-select");
    const prev = state.activeGardenId;
    sel.innerHTML = '<option value="">— select garden —</option>' +
      state.gardens.map(g => `<option value="${g.id}">${g.name}</option>`).join("");
    if (prev && state.gardens.find(g => g.id === prev)) sel.value = prev;
    populatePlantingGardenDropdowns();
  }

  document.getElementById("garden-select").addEventListener("change", async e => {
    const id = parseInt(e.target.value);
    state.activeGardenId = id || null;
    document.getElementById("location-bar").style.display = id ? "flex" : "none";
    document.getElementById("btn-add-bed").style.display = id ? "inline-block" : "none";
    if (id) {
      const garden = state.gardens.find(g => g.id === id);
      if (garden && garden.lat && garden.lon) {
        map.setView([garden.lat, garden.lon], 17);
      }
      await loadBeds();
    } else {
      state.beds = [];
      renderBedList();
      drawnItems.clearLayers();
    }
  });

  document.getElementById("btn-new-garden").addEventListener("click", () => {
    const name = prompt("Garden name:");
    if (!name || !name.trim()) return;
    post("/garden", { name: name.trim() })
      .then(g => {
        state.activeGardenId = g.id;
        return loadGardens();
      })
      .then(() => {
        document.getElementById("garden-select").value = state.activeGardenId;
        document.getElementById("location-bar").style.display = "flex";
        document.getElementById("btn-add-bed").style.display = "inline-block";
        loadBeds();
      })
      .catch(err => alert("Error: " + err.message));
  });

  // ── Location / geocode ─────────────────────────────────────────────────────
  document.getElementById("btn-geocode").addEventListener("click", async () => {
    const query = document.getElementById("location-input").value.trim();
    if (!query) return;
    try {
      const res = await fetch(
        `https://nominatim.openstreetmap.org/search?format=json&q=${encodeURIComponent(query)}&limit=1`,
        { headers: { "Accept-Language": "en" } }
      );
      const data = await res.json();
      if (!data.length) { alert("Address not found."); return; }
      const { lat, lon, display_name } = data[0];
      map.setView([parseFloat(lat), parseFloat(lon)], 17);
      await put(`/garden/${state.activeGardenId}`, {
        lat: parseFloat(lat),
        lon: parseFloat(lon),
        address: display_name,
      });
      const idx = state.gardens.findIndex(g => g.id === state.activeGardenId);
      if (idx !== -1) {
        state.gardens[idx].lat = parseFloat(lat);
        state.gardens[idx].lon = parseFloat(lon);
        state.gardens[idx].address = display_name;
      }
    } catch (e) {
      alert("Geocode failed: " + e.message);
    }
  });

  // ── Beds ───────────────────────────────────────────────────────────────────
  async function loadBeds() {
    if (!state.activeGardenId) return;
    state.beds = await get(`/beds?garden_id=${state.activeGardenId}`);
    renderBedList();
    renderBedsOnMap();
  }

  function renderBedList() {
    const el = document.getElementById("beds-list");
    if (!state.beds.length) {
      el.innerHTML = '<div class="empty-state">No beds yet.<br/>Draw a shape on the map to add one.</div>';
      return;
    }
    el.innerHTML = state.beds.map(bed => {
      const typeLabel = bed.type.replace("_", " ");
      const area = bed.area_sqft ? `${bed.area_sqft.toFixed(1)} sqft · ` : "";
      return `
        <div class="bed-card" data-bed-id="${bed.id}">
          <div class="bed-card-header">
            <span class="bed-name">${bed.name}</span>
            <span class="bed-badge ${bed.type}">${typeLabel}</span>
          </div>
          <div class="bed-meta">${area}${bed.planting_count} active planting${bed.planting_count !== 1 ? "s" : ""}</div>
        </div>`;
    }).join("");
  }

  function renderBedsOnMap() {
    drawnItems.clearLayers();
    state.beds.forEach(bed => {
      if (!bed.shape_geojson) return;
      try {
        const geo = typeof bed.shape_geojson === "string"
          ? JSON.parse(bed.shape_geojson)
          : bed.shape_geojson;
        const layer = L.geoJSON(geo, {
          style: { color: "#4caf50", weight: 2, fillOpacity: 0.2 },
        });
        layer.eachLayer(l => {
          l.loamBedId = bed.id;
          l.bindTooltip(bed.name, { permanent: false, direction: "center" });
        });
        drawnItems.addLayer(layer);
      } catch (_) {}
    });
  }

  document.getElementById("btn-add-bed").addEventListener("click", () => {
    if (!state.activeGardenId) return;
    if (!map.hasControl(drawControl)) map.addControl(drawControl);
    new L.Draw.Polygon(map, drawControl.options.draw.polygon).enable();
  });

  // ── Bed form (shown after drawing) ────────────────────────────────────────
  function showBedForm() {
    const list = document.getElementById("beds-list");
    list.insertAdjacentHTML("afterbegin", `
      <div class="bed-form" id="new-bed-form">
        <h3>Name this bed</h3>
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

    document.getElementById("btn-save-bed").addEventListener("click", saveNewBed);
    document.getElementById("btn-cancel-bed").addEventListener("click", cancelBedForm);
  }

  async function saveNewBed() {
    const name = document.getElementById("new-bed-name").value.trim();
    if (!name) { alert("Name is required."); return; }
    const bedType = document.getElementById("new-bed-type").value;
    const notes = document.getElementById("new-bed-notes").value.trim();

    const area = pendingShape ? calcAreaSqft(pendingShape) : null;

    try {
      await post("/beds", {
        garden_id: state.activeGardenId,
        name,
        type: bedType,
        shape_geojson: pendingShape ? JSON.stringify(pendingShape) : null,
        area_sqft: area,
        notes: notes || null,
      });
      pendingShape = null;
      document.getElementById("new-bed-form").remove();
      await loadBeds();
    } catch (e) {
      alert("Error: " + e.message);
    }
  }

  function cancelBedForm() {
    pendingShape = null;
    drawnItems.clearLayers();
    document.getElementById("new-bed-form").remove();
    renderBedsOnMap();
  }

  function calcAreaSqft(geojson) {
    const coords = geojson.geometry?.coordinates?.[0];
    if (!coords || coords.length < 3) return null;
    // Shoelace in degrees → crude sqft (good enough for small areas)
    let area = 0;
    for (let i = 0, j = coords.length - 1; i < coords.length; j = i++) {
      area += (coords[j][0] + coords[i][0]) * (coords[j][1] - coords[i][1]);
    }
    const sqDeg = Math.abs(area / 2);
    const sqMeters = sqDeg * 111320 * 111320 * Math.cos((coords[0][1] * Math.PI) / 180);
    return parseFloat((sqMeters * 10.7639).toFixed(1));
  }

  // ── Library ────────────────────────────────────────────────────────────────
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

  // ── Plantings ──────────────────────────────────────────────────────────────
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
    const opts = state.gardens.map(g => `<option value="${g.id}">${g.name}</option>`).join("");
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
      document.getElementById("location-bar").style.display = "flex";
      document.getElementById("btn-add-bed").style.display = "inline-block";
      if (g.lat && g.lon) map.setView([g.lat, g.lon], 17);
      await loadBeds();
    }
  }

})();
