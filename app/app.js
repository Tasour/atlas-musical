const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

const STORAGE = {
  brief: "atlas:brief:v2",
  shortlist: "atlas:shortlist:v2",
  favorites: "atlas:favorites",
  volume: "atlas:volume",
};

const STATUS = {
  "a-ecouter": "À écouter",
  retenu: "Retenu",
  ecarte: "Écarté",
  choisi: "Choisi",
};

const STATUS_ORDER = ["a-ecouter", "retenu", "ecarte", "choisi"];

const TONES = {
  lumineux: { label: "Lumineux", valence: 0.55, arousal: 0.1 },
  sombre: { label: "Sombre", valence: -0.55, arousal: 0.1 },
  calme: { label: "Calme", valence: 0.1, arousal: -0.55 },
  energique: { label: "Énergique", valence: 0.15, arousal: 0.6 },
  intime: { label: "Intime", valence: 0.3, arousal: -0.35 },
  epique: { label: "Épique", valence: 0, arousal: 0.65 },
};

const state = {
  library: null,
  tracks: [],
  tags: [],
  tagMap: new Map(),
  usages: [],
  clusters: null,
  nodes: new Map(),
  roots: [],
  trackById: new Map(),
  route: { name: "groups" },
  brief: readJSON(STORAGE.brief, null),
  shortlist: new Map(),
  compare: [],
  search: "",
  groupFilters: { tag: "", duration: "all" },
  groupSort: "auto",
  lastGroupId: null,
  lastGroupParams: null,
  player: { currentId: null, preview: false, loop: false },
  ab: null,
};

const audio = $("#audio");
const abA = $("#abA");
const abB = $("#abB");

function readJSON(key, fallback) {
  try {
    const raw = localStorage.getItem(key);
    return raw ? JSON.parse(raw) : fallback;
  } catch {
    return fallback;
  }
}

function writeJSON(key, value) {
  try {
    localStorage.setItem(key, JSON.stringify(value));
  } catch {
    /* stockage indisponible */
  }
}

function esc(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function icon(name, cls = "icon") {
  return `<svg class="${cls}" aria-hidden="true"><use href="#i-${name}"></use></svg>`;
}

function clamp01(value) {
  return Math.max(0, Math.min(1, Number(value) || 0));
}

function fmtTime(seconds) {
  const value = Math.max(0, Math.round(Number(seconds) || 0));
  return `${Math.floor(value / 60)}:${String(value % 60).padStart(2, "0")}`;
}

function fmtDur(seconds) {
  return fmtTime(seconds);
}

function fmtPct(value, digits = 0) {
  return `${(Number(value || 0) * 100).toFixed(digits)} %`;
}

function fmtSigned(value) {
  const n = Number(value || 0);
  return `${n >= 0 ? "+" : ""}${n.toFixed(2)}`;
}

function norm(value) {
  return String(value ?? "")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase();
}

function effective(track) {
  const annotation = track.annotation || {};
  const has = (key) => annotation[key] !== null && annotation[key] !== undefined;
  const valence = has("valence") ? Number(annotation.valence) : Number(track.valence || 0);
  const arousal = has("arousal") ? Number(annotation.arousal) : Number(track.arousal || 0);
  const tension = has("tension") ? Number(annotation.tension) : Number(track.tension || 0);
  return {
    valence,
    arousal,
    tension,
    valence01: clamp01((valence + 1) / 2),
    arousal01: clamp01((arousal + 1) / 2),
    tension01: clamp01((tension + 1) / 2),
    manual: has("valence") || has("arousal") || has("tension"),
  };
}

function trackTags(track) {
  return Array.from(
    new Set([...(track.tags || []), ...((track.annotation && track.annotation.tags) || [])])
  );
}

function visibleTags(track) {
  return trackTags(track).filter((tag) => tag !== "Instrumental");
}

function tagColor(name) {
  return state.tagMap.get(name)?.color || "var(--accent)";
}

function clusterOf(track) {
  return state.nodes.get(track.cluster) || null;
}

function rootOf(node) {
  let current = node;
  while (current && current.parent) current = state.nodes.get(current.parent);
  return current;
}

function clusterPath(track) {
  const names = track.cluster_path_names || [];
  if (names.length) return names;
  const namesFromIds = (track.cluster_path || []).map(
    (id) => state.nodes.get(id)?.name || id
  );
  return namesFromIds;
}

function clustersAvailable() {
  return state.roots.length > 0;
}

function shortlistEntry(id) {
  return state.shortlist.get(id) || null;
}

function loadShortlist() {
  const raw = readJSON(STORAGE.shortlist, null);
  const entries = new Map();
  if (Array.isArray(raw)) {
    raw.forEach((item, index) => {
      if (!item || !item.id) return;
      entries.set(item.id, {
        id: item.id,
        status: STATUS[item.status] ? item.status : "a-ecouter",
        note: String(item.note || ""),
        licenseChecked: Boolean(item.licenseChecked),
        order: Number.isFinite(item.order) ? item.order : index,
      });
    });
  } else {
    const favorites = readJSON(STORAGE.favorites, []);
    if (Array.isArray(favorites)) {
      favorites.forEach((id, index) => {
        if (typeof id === "string") {
          entries.set(id, { id, status: "a-ecouter", note: "", licenseChecked: false, order: index });
        }
      });
    }
  }
  return entries;
}

function saveShortlist() {
  const items = [...state.shortlist.values()].sort((a, b) => a.order - b.order);
  writeJSON(STORAGE.shortlist, items);
  updateShortlistCount();
}

function updateShortlistCount() {
  const count = String(state.shortlist.size);
  $("#shortlistCount").textContent = count;
  const inline = $("#shortlistInline");
  if (inline) inline.textContent = count;
}

function nextOrder() {
  return state.shortlist.size ? Math.max(...[...state.shortlist.values()].map((e) => e.order)) + 1 : 0;
}

function updateAddButtons(id) {
  const entry = shortlistEntry(id);
  $$(`[data-add="${CSS.escape(id)}"]`).forEach((button) => {
    button.classList.toggle("active", Boolean(entry));
    button.innerHTML = `${icon("plus")} ${entry ? STATUS[entry.status] : "+ Short-list"}`;
  });
  updateShortlistCount();
}

function addToShortlist(id, status = "a-ecouter") {
  if (!state.trackById.has(id)) return;
  const existing = state.shortlist.get(id);
  if (existing) {
    if (existing.status !== status) {
      existing.status = status;
      saveShortlist();
    }
    showToast(`Déjà dans la short-list · ${STATUS[existing.status]}`);
    return;
  }
  state.shortlist.set(id, { id, status, note: "", licenseChecked: false, order: nextOrder() });
  localStorage.setItem("atlas:onboarded", "1");
  saveShortlist();
  showToast(`Ajouté à la short-list · ${STATUS[status]}`);
}

function removeFromShortlist(id) {
  const removed = state.shortlist.get(id);
  if (!removed) return;
  state.shortlist.delete(id);
  state.compare = state.compare.filter((item) => item !== id);
  saveShortlist();
  showToast("Retiré de la short-list.", "", {
    label: "Annuler",
    fn: () => {
      state.shortlist.set(id, removed);
      saveShortlist();
      refreshView();
    },
  });
}

function moveShortlist(id, delta) {
  const items = [...state.shortlist.values()].sort((a, b) => a.order - b.order);
  const index = items.findIndex((entry) => entry.id === id);
  const target = index + delta;
  if (index < 0 || target < 0 || target >= items.length) return;
  items.splice(target, 0, items.splice(index, 1)[0]);
  items.forEach((entry, position) => {
    entry.order = position;
  });
  saveShortlist();
  refreshView();
}

function setShortlistStatus(id, status) {
  const entry = state.shortlist.get(id);
  if (!entry) return;
  if (status === "choisi") {
    chooseTrack(id, { silent: true });
    return;
  }
  entry.status = STATUS[status] ? status : "a-ecouter";
  saveShortlist();
}

function chooseTrack(id, { silent = false } = {}) {
  for (const entry of state.shortlist.values()) {
    if (entry.id === id) entry.status = "choisi";
    else if (entry.status === "choisi") entry.status = "retenu";
  }
  if (!state.shortlist.has(id)) {
    state.shortlist.set(id, { id, status: "choisi", note: "", licenseChecked: false, order: nextOrder() });
  }
  saveShortlist();
  if (!silent) showToast("Piste choisie. Le crédit est prêt dans la fiche.");
}

function briefSummary() {
  if (!state.brief) return "Aucun brief";
  const tone = TONES[state.brief.tone]?.label || state.brief.tone;
  const parts = [state.brief.type, `${state.brief.duration} s`, tone];
  if (state.brief.loop) parts.push("boucle");
  if (state.brief.dialogue) parts.push("dialogue");
  return parts.join(" · ");
}

function briefScore(track) {
  if (!state.brief) return null;
  const effect = effective(track);
  const tone = TONES[state.brief.tone] || TONES.calme;
  const usage = Number(track.usage_scores?.[state.brief.type] || 0);
  const valenceMatch = 1 - Math.abs(effect.valence - tone.valence) / 2;
  const arousalMatch = 1 - Math.abs(effect.arousal - tone.arousal) / 2;
  const target = Math.max(10, Number(state.brief.duration) || 30);
  const durationFit = 1 - Math.min(1, Math.abs(Number(track.duration || 0) - target) / target);
  const loopFit = state.brief.loop ? clamp01(track.loopability) : 0.5;
  const score =
    0.35 * usage +
    0.25 * valenceMatch +
    0.2 * arousalMatch +
    0.1 * durationFit +
    0.1 * loopFit;
  return clamp01(score);
}

function briefReasons(track) {
  if (!state.brief) return [];
  const effect = effective(track);
  const tone = TONES[state.brief.tone] || TONES.calme;
  const usage = Number(track.usage_scores?.[state.brief.type] || 0);
  const target = Math.max(10, Number(state.brief.duration) || 30);
  const durationFit = 1 - Math.min(1, Math.abs(Number(track.duration || 0) - target) / target);
  const reasons = [];
  if (usage > 0.6) reasons.push(`usage ${state.brief.type} ${usage.toFixed(2)}`);
  if (Math.abs(effect.valence - tone.valence) < 0.35) reasons.push(`ton ${tone.label.toLowerCase()}`);
  if (state.brief.loop && Number(track.loopability) > 0.55) reasons.push("boucle propre");
  if (durationFit > 0.7) reasons.push("durée proche du plan");
  return reasons.slice(0, 3);
}

function groupScore(node) {
  if (!state.brief) return null;
  const scores = (node.track_ids || []).map((id) => {
    const track = state.trackById.get(id);
    return track ? briefScore(track) : null;
  }).filter((value) => value !== null);
  if (!scores.length) return null;
  return scores.reduce((sum, value) => sum + value, 0) / scores.length;
}

function sortedTracks(tracks) {
  const list = [...tracks];
  if (state.brief) {
    list.sort((a, b) => briefScore(b) - briefScore(a));
  } else {
    list.sort((a, b) => Number(b.confidence || 0) - Number(a.confidence || 0));
  }
  return list;
}

function searchTracks(query) {
  const needle = norm(query);
  if (!needle) return [];
  return state.tracks
    .filter((track) => {
      const hay = [
        track.title,
        track.artist,
        track.genre,
        ...trackTags(track),
        ...clusterPath(track),
      ].join(" ");
      return norm(hay).includes(needle);
    })
    .sort((a, b) => {
      if (state.brief) return briefScore(b) - briefScore(a);
      return Number(b.confidence || 0) - Number(a.confidence || 0);
    })
    .slice(0, 40);
}

function navigate(path) {
  const target = path.startsWith("#") ? path : `#/${path}`;
  if (window.location.hash === target) {
    renderRoute(true);
  } else {
    window.location.hash = target;
  }
}

function parseRoute() {
  const raw = window.location.hash.replace(/^#\/?/, "");
  const [pathPart, queryPart] = raw.split("?");
  const params = new URLSearchParams(queryPart || "");
  const parts = pathPart.split("/").filter(Boolean);
  if (!parts.length) return { name: "groups", params };
  if (parts[0] === "brief") return { name: "brief", params };
  if (parts[0] === "shortlist") return { name: "shortlist", params };
  if (parts[0] === "group" && parts[1]) {
    return { name: "group", groupId: decodeURIComponent(parts.slice(1).join("/")), params };
  }
  if (parts[0] === "track" && parts[1]) {
    return { name: "track", trackId: decodeURIComponent(parts.slice(1).join("/")), params };
  }
  return { name: "groups", params };
}

function syncUrl() {
  const route = state.route;
  let base = "groups";
  if (route.name === "brief") base = "brief";
  else if (route.name === "shortlist") base = "shortlist";
  else if (route.name === "group") base = `group/${encodeURIComponent(route.groupId)}`;
  else if (route.name === "track") base = `track/${encodeURIComponent(route.trackId)}`;
  const params = new URLSearchParams();
  if (route.name === "groups" && state.search) params.set("q", state.search);
  if (route.name === "group") {
    if (state.groupFilters.tag) params.set("tag", state.groupFilters.tag);
    if (state.groupFilters.duration !== "all") params.set("dur", state.groupFilters.duration);
    if (state.groupSort !== "auto") params.set("sort", state.groupSort);
    if (state.showTracks) params.set("tracks", "1");
  }
  if (route.name === "shortlist" && state.shortlistFilter) params.set("status", state.shortlistFilter);
  const suffix = params.toString() ? `?${params.toString()}` : "";
  const target = `#/${base}${suffix}`;
  state.route.params = params;
  if (window.location.hash !== target) {
    window.history.replaceState(null, "", target);
  }
}

function renderRoute(focus = false) {
  state.route = parseRoute();
  if (state.route.name === "groups") state.search = state.route.params.get("q") || "";
  if (state.route.name === "shortlist") state.shortlistFilter = state.route.params.get("status") || null;
  updateFlowNav();
  renderView();
  if (focus) {
    window.scrollTo(0, 0);
    const heading = $("#view h1");
    if (heading) {
      heading.tabIndex = -1;
      heading.focus({ preventScroll: true });
    }
  }
  const titles = {
    brief: "Brief du plan",
    groups: "Explorer",
    group: "Affiner",
    shortlist: "Short-list",
    track: "Décider",
  };
  document.title = `${titles[state.route.name] || "Atlas Musical"} — Atlas Musical`;
  const detail =
    state.route.name === "group"
      ? state.nodes.get(state.route.groupId)?.name
      : state.route.name === "track"
        ? state.trackById.get(state.route.trackId)?.title
        : state.route.name === "shortlist"
          ? `${state.shortlist.size} piste(s)`
          : "";
  const announcer = $("#routeAnnouncer");
  if (announcer) announcer.textContent = `${titles[state.route.name] || "Atlas Musical"}${detail ? ` — ${detail}` : ""}`;
}

function refreshView(focusSelector = null) {
  const scroll = window.scrollY;
  renderView();
  window.scrollTo(0, scroll);
  if (focusSelector) {
    const target = $(focusSelector);
    if (target) target.focus({ preventScroll: true });
  }
}

function updateFlowNav() {
  const route = state.route;
  const buttons = $$("#flowNav [data-nav]");
  buttons.forEach((button) => {
    const nav = button.dataset.nav;
    const active =
      (nav === "brief" && route.name === "brief") ||
      (nav === "groups" && route.name === "groups") ||
      (nav === "group" && route.name === "group") ||
      (nav === "shortlist" && route.name === "shortlist") ||
      (nav === "track" && route.name === "track");
    button.classList.toggle("active", active);
    button.setAttribute("aria-current", active ? "step" : "false");
    if (nav === "group") {
      const fallback = route.groupId || state.trackById.get(route.trackId)?.cluster || state.lastGroupId;
      button.disabled = !fallback;
      button.dataset.group = fallback || "";
    }
    if (nav === "track") button.disabled = !route.trackId && route.name !== "track";
  });
  updateShortlistCount();
}

function renderView() {
  const route = state.route;
  if (route.name === "brief") renderBrief();
  else if (route.name === "group") renderGroup(route.groupId);
  else if (route.name === "shortlist") renderShortlist();
  else if (route.name === "track") renderTrack(route.trackId);
  else renderGroups();
}

function pageHead(kicker, title, subtitle, actions = "") {
  return `<header class="page-head">
    <div>
      <div class="kicker">${esc(kicker)}</div>
      <h1>${esc(title)}</h1>
      <p class="lede">${esc(subtitle)}</p>
    </div>
    ${actions ? `<div class="page-actions">${actions}</div>` : ""}
  </header>`;
}

/* ------------------------------ Brief ------------------------------ */

function renderBrief() {
  const brief = state.brief;
  const types = state.usages.length
    ? state.usages
    : ["Ouverture", "Paysage/drone", "Transition", "Action/montage", "Portrait/intime", "Résolution/générique"];
  const tones = Object.entries(TONES)
    .map(
      ([key, value]) =>
        `<button class="chip${brief?.tone === key ? " active" : ""}" type="button" data-tone="${key}">${esc(value.label)}</button>`
    )
    .join("");
  const typeChips = types
    .map(
      (type) =>
        `<button class="chip${brief?.type === type ? " active" : ""}" type="button" data-brief-type="${esc(type)}">${esc(type)}</button>`
    )
    .join("");
  const durations = [8, 15, 30, 60]
    .map(
      (value) =>
        `<button class="chip${Number(brief?.duration) === value ? " active" : ""}" type="button" data-duration="${value}">${value} s</button>`
    )
    .join("");

  $("#view").innerHTML = `<div class="page">
    ${pageHead(
      "Étape 1 · optionnel",
      "Cadrer le plan",
      "Quelques secondes pour orienter la recherche. Vous pouvez passer cette étape."
    )}
    <form class="panel brief-form" id="briefForm">
      <div class="field">
        <label>Type de plan</label>
        <input type="hidden" name="type" value="${esc(brief?.type || types[0])}">
        <div class="chips" data-brief-types>${typeChips}</div>
      </div>
      <div class="field">
        <label for="briefDuration">Durée du plan</label>
        <div class="inline">
          <input id="briefDuration" name="duration" type="number" min="4" max="600" step="1" value="${Number(brief?.duration) || 30}">
          <span class="unit">secondes</span>
        </div>
        <div class="chips" data-durations>${durations}</div>
      </div>
      <div class="field">
        <label>Ton recherché</label>
        <input type="hidden" name="tone" value="${esc(brief?.tone || "calme")}">
        <div class="chips" data-tones>${tones}</div>
      </div>
      <div class="field inline-checks">
        <label class="check"><input type="checkbox" name="loop" ${brief?.loop ? "checked" : ""}> Le plan boucle</label>
        <label class="check"><input type="checkbox" name="dialogue" ${brief?.dialogue ? "checked" : ""}> Il y a du dialogue</label>
      </div>
      <div class="form-actions">
        <button class="btn primary" type="submit">${icon("arrow-right")} Explorer les groupes</button>
        <a class="btn ghost" href="#/groups">Passer le brief</a>
      </div>
      ${brief ? `<p class="micro">Brief actuel : ${esc(briefSummary())} · <button class="link" type="button" data-clear-brief>Réinitialiser</button></p>` : ""}
    </form>
  </div>`;

  $$("[data-brief-type]").forEach((button) => {
    button.addEventListener("click", () => {
      $('[name="type"]').value = button.dataset.briefType;
      $$("[data-brief-type]").forEach((item) => item.classList.toggle("active", item === button));
    });
  });
  $$("[data-tone]").forEach((button) => {
    button.addEventListener("click", () => {
      $('[name="tone"]').value = button.dataset.tone;
      $$("[data-tone]").forEach((item) => item.classList.toggle("active", item === button));
    });
  });
  $$("[data-duration]").forEach((button) => {
    button.addEventListener("click", () => {
      $("#briefDuration").value = button.dataset.duration;
      $$("[data-duration]").forEach((item) => item.classList.toggle("active", item === button));
    });
  });
  const clear = $("[data-clear-brief]");
  if (clear) {
    clear.addEventListener("click", () => {
      state.brief = null;
      writeJSON(STORAGE.brief, null);
      renderBrief();
    });
  }
  $("#briefForm").addEventListener("submit", (event) => {
    event.preventDefault();
    const form = new FormData(event.target);
    state.brief = {
      type: String(form.get("type") || ""),
      duration: Number(form.get("duration")) || 30,
      tone: String(form.get("tone") || "calme"),
      loop: form.get("loop") === "on",
      dialogue: form.get("dialogue") === "on",
    };
    writeJSON(STORAGE.brief, state.brief);
    localStorage.setItem("atlas:onboarded", "1");
    navigate("groups");
  });
}

/* ------------------------------ Groups ------------------------------ */

function renderGroups() {
  if (!state.library) {
    renderFatal(new Error("Bibliothèque indisponible."));
    return;
  }
  const briefLine = state.brief
    ? `<button class="brief-pill" type="button" data-edit-brief>${icon("info")} ${esc(briefSummary())} <span>modifier</span></button>`
    : `<a class="brief-pill" href="#/brief">${icon("plus")} Cadrer le plan (optionnel)</a>`;
  const results = state.search ? searchTracks(state.search) : [];
  const groups = clustersAvailable() ? sortedRoots() : [];
  const onboarded = localStorage.getItem("atlas:onboarded") === "1";
  const onboarding = !onboarded && !state.brief && state.shortlist.size === 0
    ? `<section class="onboarding" aria-label="Premiers pas">
        <div class="onboarding-steps">
          <span><b>1</b> Cadrer le plan (optionnel)</span>
          <span><b>2</b> Explorer un groupe</span>
          <span><b>3</b> Affiner et garder 5 à 15 pistes</span>
          <span><b>4</b> Décider et exporter</span>
        </div>
        <div class="onboarding-actions">
          <a class="btn small primary" href="#/brief">Cadrer le plan</a>
          <button class="btn small ghost" type="button" data-onboard="dismiss">Explorer directement</button>
        </div>
      </section>`
    : "";
  const treemap = groups.length
    ? treemapHtml(
        groups.map(({ node, score }) => ({
          id: node.id,
          label: node.name,
          value: node.size,
          color: node.color,
          meta: `${node.size} pistes${score !== null ? ` · ${Math.round(score * 100)} % brief` : ""}`,
          sort: score !== null ? score : node.size,
          tags: (node.top_tags || []).slice(0, 2).map((tag) => tag.name),
          stability: node.stability,
        })),
        "group"
      )
    : `<div class="empty">Aucun groupe disponible. Relancez l’analyse pour générer les clusters.</div>`;

  $("#view").innerHTML = `<div class="page">
    ${pageHead(
      "Étape 2",
      state.search ? "Résultats de recherche" : "Explorer par groupes",
      state.search
        ? `${results.length} piste(s) trouvée(s) pour « ${state.search} »`
        : "Partez d’un grand groupe, puis affinez. Chaque clic réduit réellement le nombre de pistes.",
      `<a class="btn primary" href="#/shortlist">${icon("star")} Ma short-list <b id="shortlistInline">${state.shortlist.size}</b></a>`
    )}
    <div class="toolbar">
      <label class="searchbox">
        ${icon("search")}
        <input id="searchInput" type="search" value="${esc(state.search)}" placeholder="Rechercher un titre, un artiste, un tag…" aria-label="Rechercher dans la bibliothèque" autocomplete="off">
        ${state.search ? `<button class="icon-btn" type="button" data-clear-search aria-label="Effacer">${icon("close")}</button>` : "<kbd>/</kbd>"}
      </label>
      ${briefLine}
      <span class="toolbar-note">${groups.length ? `${groups.length} groupes · ${state.tracks.length} pistes` : ""}</span>
    </div>
    ${onboarding}
    ${state.search ? renderSearchResults(results) : treemap}
    <div class="flow-hint">
      <span>${icon("arrow-right")} Cliquez un groupe pour voir ses sous-groupes et ses pistes.</span>
      ${state.shortlist.size ? `<a href="#/shortlist">Continuer avec ${state.shortlist.size} piste(s) →</a>` : ""}
    </div>
  </div>`;

  bindSearch();
  if (state.search) bindTrackGrid();
  $$("[data-onboard]").forEach((button) => {
    button.addEventListener("click", () => {
      localStorage.setItem("atlas:onboarded", "1");
      refreshView();
    });
  });
}

function sortedRoots() {
  return state.roots
    .map((id) => {
      const node = state.nodes.get(id);
      return { node, score: groupScore(node) };
    })
    .filter((item) => item.node)
    .sort((a, b) => {
      if (state.brief) return (b.score || 0) - (a.score || 0);
      return b.node.size - a.node.size;
    });
}

function renderSearchResults(results) {
  if (!results.length) {
    return `<div class="empty">Aucun résultat. Essayez un autre terme ou <button class="link" type="button" data-clear-search>effacez la recherche</button>.</div>`;
  }
  return `<div class="track-grid">${results.map((track) => trackCard(track)).join("")}</div>`;
}

function bindSearch() {
  const input = $("#searchInput");
  if (!input) return;
  let timer = null;
  input.addEventListener("input", () => {
    const value = input.value.trim();
    clearTimeout(timer);
    timer = setTimeout(() => {
      state.search = value;
      syncUrl();
      refreshView("#searchInput");
    }, 160);
  });
  const clear = $("[data-clear-search]");
  if (clear) {
    clear.addEventListener("click", () => {
      state.search = "";
      syncUrl();
      refreshView("#searchInput");
    });
  }
  const edit = $("[data-edit-brief]");
  if (edit) edit.addEventListener("click", () => navigate("brief"));
}

/* ------------------------------ Group ------------------------------ */

function renderGroup(groupId) {
  const node = state.nodes.get(groupId);
  if (!node) {
    $("#view").innerHTML = `<div class="page">${pageHead("Étape 3", "Groupe introuvable", "Ce groupe n’existe pas.")}<a class="btn primary" href="#/groups">Retour aux groupes</a></div>`;
    return;
  }
  const params = state.route.params || new URLSearchParams();
  const signature = params.toString();
  if (state.lastGroupId !== groupId || state.lastGroupParams !== signature) {
    state.groupFilters = { tag: params.get("tag") || "", duration: params.get("dur") || "all" };
    state.groupSort = params.get("sort") || "auto";
    state.showTracks = params.get("tracks") === "1";
    state.lastGroupId = groupId;
    state.lastGroupParams = signature;
  }
  const path = [];
  let cursor = node;
  while (cursor) {
    path.unshift(cursor);
    cursor = cursor.parent ? state.nodes.get(cursor.parent) : null;
  }
  const breadcrumb = `<nav class="breadcrumb" aria-label="Fil d’Ariane">
    <a href="#/groups">Explorer</a>
    ${path
      .map((item, index) => {
        const last = index === path.length - 1;
        return `<span aria-hidden="true">›</span>${
          last
            ? `<span aria-current="page">${esc(item.name)}</span>`
            : `<a href="#/group/${encodeURIComponent(item.id)}">${esc(item.name)}</a>`
        }`;
      })
      .join("")}
  </nav>`;

  const children = (node.children || [])
    .map((id) => state.nodes.get(id))
    .filter(Boolean);
  const tracks = filteredNodeTracks(node);
  const showChildren = children.length > 0 && !state.showTracks;
  const lead = children.length
    ? `${children.length} sous-groupes · ${node.size} pistes au total`
    : `${node.size} pistes · ${clusterPathLabel(node)}`;

  let body = "";
  if (showChildren) {
    body = treemapHtml(
      children.map((child) => ({
        id: child.id,
        label: child.name,
        value: child.size,
        color: child.color || node.color,
        meta: `${child.size} pistes`,
        tags: (child.top_tags || []).slice(0, 2).map((tag) => tag.name),
        stability: child.stability,
      })),
      "group"
    );
  } else {
    body = `<div class="split">
      <div class="split-main">${renderTrackList(tracks, node)}</div>
      <aside class="split-side">${scatterHtml(tracks, node)}</aside>
    </div>`;
  }

  $("#view").innerHTML = `<div class="page">
    ${breadcrumb}
    ${pageHead(
      node.level === 1 ? "Groupe" : node.level === 2 ? "Sous-groupe" : "Famille fine",
      node.name,
      lead,
      `${children.length ? `<button class="btn ghost" type="button" data-toggle-tracks>${state.showTracks ? "Voir les sous-groupes" : `Voir les ${node.size} pistes`}</button>` : ""}
       <a class="btn primary" href="#/shortlist">${icon("star")} Short-list <b id="shortlistInline">${state.shortlist.size}</b></a>`
    )}
    <div class="group-meta">
      ${node.stability ? `<span class="badge" title="Jaccard bootstrap : proportion de fois où ce groupe est retrouvé sur des rééchantillonnages.">stabilité ${Math.round(node.stability * 100)} %</span>` : ""}
      ${node.silhouette ? `<span class="badge" title="Silhouette : cohésion interne du groupe (plus haut = mieux séparé).">silhouette ${Number(node.silhouette).toFixed(2)}</span>` : ""}
      ${(node.top_tags || []).slice(0, 4).map((tag) => `<span class="tag" style="--tag:${tagColor(tag.name)}">${esc(tag.name)}</span>`).join("")}
      <span class="micro">${esc(node.description || "")}</span>
    </div>
    <details class="quality">
      <summary>Qualité du groupe</summary>
      <div class="quality-body">
        <p><strong>Stabilité bootstrap :</strong> ${node.stability ? `${Math.round(node.stability * 100)} %` : "non calculée"} — part des rééchantillonnages où ce groupe est retrouvé.</p>
        <p><strong>Silhouette :</strong> ${node.silhouette ? Number(node.silhouette).toFixed(2) : "globale " + Number(state.clusters?.silhouette || 0).toFixed(2)} — cohésion interne, plus haut = mieux séparé.</p>
        <p><strong>ACP :</strong> ${(state.clusters?.pca?.explained_variance || []).slice(0, 3).map((value) => `${Math.round(value * 100)} %`).join(" · ") || "—"} de variance expliquée par les premières composantes.</p>
        ${children.length ? `<div class="quality-bars"><h3>Stabilité des sous-groupes</h3><div class="bars">${children.map((child) => barRow(child.name, child.stability || 0, child.color || "var(--accent)")).join("")}</div></div>` : ""}
        <div class="quality-bars"><h3>Variance ACP</h3><div class="bars">${(state.clusters?.pca?.explained_variance || []).slice(0, 4).map((value, index) => barRow(`PC${index + 1}`, value, "var(--calm)")).join("")}</div></div>
        <p class="micro">Ces indicateurs décrivent la partition, pas la qualité musicale. Les noms doivent être confirmés à l’écoute.</p>
      </div>
    </details>
    ${body}
  </div>`;

  bindTrackGrid();
}

function clusterPathLabel(node) {
  const parts = [];
  let cursor = node;
  while (cursor && cursor.parent) {
    cursor = state.nodes.get(cursor.parent);
    if (cursor) parts.unshift(cursor.name);
  }
  return parts.length ? parts.join(" › ") : "groupe racine";
}

function filteredNodeTracks(node) {
  let list = (node.track_ids || [])
    .map((id) => state.trackById.get(id))
    .filter(Boolean);
  if (state.groupFilters.tag) {
    list = list.filter((track) => trackTags(track).includes(state.groupFilters.tag));
  }
  if (state.groupFilters.duration !== "all") {
    list = list.filter((track) => {
      const minutes = Number(track.duration || 0) / 60;
      if (state.groupFilters.duration === "short") return minutes < 2;
      if (state.groupFilters.duration === "medium") return minutes >= 2 && minutes <= 4;
      return minutes > 4;
    });
  }
  return sortGroupTracks(list);
}

function sortGroupTracks(list) {
  const items = [...list];
  if (state.groupSort === "bpm") items.sort((a, b) => Number(a.bpm || 0) - Number(b.bpm || 0));
  else if (state.groupSort === "duration") items.sort((a, b) => Number(a.duration || 0) - Number(b.duration || 0));
  else if (state.groupSort === "title") items.sort((a, b) => a.title.localeCompare(b.title, "fr"));
  else if (state.groupSort === "confidence") items.sort((a, b) => Number(b.confidence || 0) - Number(a.confidence || 0));
  else return sortedTracks(items);
  return items;
}

function renderTrackList(tracks, node) {
  const tagChips = (node.top_tags || [])
    .slice(0, 4)
    .map((tag) => {
      const active = state.groupFilters.tag === tag.name;
      return `<button class="chip${active ? " active" : ""}" type="button" data-tag-filter="${esc(tag.name)}" aria-pressed="${active}" style="--tag:${tagColor(tag.name)}"><i class="dot"></i>${esc(tag.name)}</button>`;
    })
    .join("");
  const durations = [
    ["all", "Toutes"],
    ["short", "< 2 min"],
    ["medium", "2–4 min"],
    ["long", "> 4 min"],
  ]
    .map(
      ([key, label]) =>
        `<button class="chip${state.groupFilters.duration === key ? " active" : ""}" type="button" data-duration-filter="${key}" aria-pressed="${state.groupFilters.duration === key}">${label}</button>`
    )
    .join("");
  const sortOptions = [["auto", "Auto"], ["brief", "Brief"], ["confidence", "Confiance"], ["bpm", "BPM"], ["duration", "Durée"], ["title", "Titre"]];
  return `<div class="filter-bar">
      <span class="micro">Affiner :</span>
      <div class="chips">${tagChips}${durations}</div>
      <label class="field-inline">Tri
        <select id="groupSort">${sortOptions.map(([value, label]) => `<option value="${value}" ${state.groupSort === value ? "selected" : ""}>${label}</option>`).join("")}</select>
      </label>
      <span class="micro">${tracks.length} piste(s)</span>
    </div>
    <div class="track-grid">${tracks.length ? tracks.map((track) => trackCard(track)).join("") : `<div class="empty">Aucune piste avec ces filtres.</div>`}</div>`;
}

function bindTrackGrid() {
  $$("[data-tag-filter]").forEach((button) => {
    button.addEventListener("click", () => {
      const tag = button.dataset.tagFilter;
      state.groupFilters.tag = state.groupFilters.tag === tag ? "" : tag;
      syncUrl();
      refreshView(`[data-tag-filter="${CSS.escape(tag)}"]`);
    });
  });
  const groupSort = $("#groupSort");
  if (groupSort) {
    groupSort.addEventListener("change", () => {
      state.groupSort = groupSort.value;
      syncUrl();
      refreshView("#groupSort");
    });
  }
  $$("[data-duration-filter]").forEach((button) => {
    button.addEventListener("click", () => {
      state.groupFilters.duration = button.dataset.durationFilter;
      syncUrl();
      refreshView(`[data-duration-filter="${button.dataset.durationFilter}"]`);
    });
  });
  $$("[data-preview]").forEach((button) => {
    button.addEventListener("click", () => {
      const track = state.trackById.get(button.dataset.preview);
      if (track) playTrack(track, { preview: true });
    });
  });
  $$("[data-move-id]").forEach((button) => {
    button.addEventListener("click", () => moveShortlist(button.dataset.moveId, Number(button.dataset.move)));
  });
  $$("[data-remove]").forEach((button) => {
    button.addEventListener("click", () => {
      removeFromShortlist(button.dataset.remove);
      refreshView();
    });
  });
  $$("[data-compare]").forEach((checkbox) => {
    checkbox.addEventListener("change", () => {
      const id = checkbox.dataset.compare;
      if (checkbox.checked) {
        if (state.compare.length >= 3) {
          checkbox.checked = false;
          showToast("Comparaison limitée à 3 pistes.", "warn");
          return;
        }
        state.compare.push(id);
      } else {
        state.compare = state.compare.filter((item) => item !== id);
      }
      refreshView(`[data-compare="${CSS.escape(id)}"]`);
    });
  });
  $$("[data-status]").forEach((select) => {
    select.addEventListener("change", () => {
      setShortlistStatus(select.dataset.status, select.value);
      refreshView(`[data-status="${CSS.escape(select.dataset.status)}"]`);
    });
  });
  $$("[data-license]").forEach((checkbox) => {
    checkbox.addEventListener("change", () => {
      const entry = state.shortlist.get(checkbox.dataset.license);
      if (entry) {
        entry.licenseChecked = checkbox.checked;
        saveShortlist();
        showToast(checkbox.checked ? "Licence marquée vérifiée." : "Licence à revérifier.");
        refreshView(`[data-license="${CSS.escape(checkbox.dataset.license)}"]`);
      }
    });
  });
  $$("[data-note]").forEach((input) => {
    input.addEventListener("change", () => {
      const entry = state.shortlist.get(input.dataset.note);
      if (entry) {
        entry.note = input.value.trim();
        saveShortlist();
        showToast("Note enregistrée.");
      }
    });
  });
}

/* ------------------------------ Cards ------------------------------ */

function trackCard(track) {
  const entry = shortlistEntry(track.id);
  const path = clusterPath(track);
  const effect = effective(track);
  const addLabel = entry ? `${STATUS[entry.status]}` : "+ Short-list";
  const reasons = briefReasons(track);
  return `<article class="track-card">
    <div class="tc-top">
      <a class="tc-title" href="#/track/${encodeURIComponent(track.id)}">${esc(track.title)}</a>
      <span class="tc-dur">${fmtDur(track.duration)}</span>
    </div>
    <div class="tc-sub">${esc(track.artist)}${path.length ? ` · ${esc(path[path.length - 1])}` : ""}</div>
    <div class="tc-tags">${visibleTags(track).slice(0, 3).map((tag) => `<span class="tag" style="--tag:${tagColor(tag)}">${esc(tag)}</span>`).join("")}</div>
    <div class="tc-meta">
      <span>${Math.round(Number(track.bpm) || 0)} BPM</span>
      <span>V ${fmtSigned(effect.valence)}</span>
      <span>A ${fmtSigned(effect.arousal)}</span>
      ${state.brief ? `<span class="score">${Math.round(briefScore(track) * 100)} %</span>` : ""}
    </div>
    ${reasons.length ? `<div class="tc-reasons">${reasons.map((reason) => `<span>${esc(reason)}</span>`).join("")}</div>` : ""}
    <div class="tc-actions">
      <button class="btn small" type="button" data-preview="${esc(track.id)}">${icon("play")} 12 s</button>
      <button class="btn small ghost${entry ? " active" : ""}" type="button" data-add="${esc(track.id)}">${icon("plus")} ${esc(addLabel)}</button>
      <a class="btn small ghost" href="#/track/${encodeURIComponent(track.id)}">Analyser</a>
    </div>
  </article>`;
}

/* ------------------------------ Treemap ------------------------------ */

function binaryTreemap(items, x, y, width, height, output = []) {
  if (!items.length) return output;
  if (items.length === 1) {
    output.push({ ...items[0], x, y, width, height });
    return output;
  }
  const total = items.reduce((sum, item) => sum + item.value, 0);
  let running = 0;
  let split = 1;
  let best = Infinity;
  for (let index = 0; index < items.length - 1; index += 1) {
    running += items[index].value;
    const difference = Math.abs(running - total / 2);
    if (difference < best) {
      best = difference;
      split = index + 1;
    }
  }
  const left = items.slice(0, split);
  const right = items.slice(split);
  const leftValue = left.reduce((sum, item) => sum + item.value, 0);
  const ratio = total ? leftValue / total : 0.5;
  if (width >= height) {
    const leftWidth = width * ratio;
    binaryTreemap(left, x, y, leftWidth, height, output);
    binaryTreemap(right, x + leftWidth, y, width - leftWidth, height, output);
  } else {
    const leftHeight = height * ratio;
    binaryTreemap(left, x, y, width, leftHeight, output);
    binaryTreemap(right, x, y + leftHeight, width, height - leftHeight, output);
  }
  return output;
}

function treemapHtml(items, mode) {
  if (!items.length) return `<div class="empty">Aucun élément.</div>`;
  const sorted = [...items].sort((a, b) => (b.sort ?? b.value) - (a.sort ?? a.value));
  const rects = binaryTreemap(sorted, 0, 0, 1, 1);
  return `<div class="treemap">${rects
    .map((rect) => {
      const area = rect.width * rect.height;
      const small = area < 0.045;
      const tiny = area < 0.018;
      const stability = rect.stability ? ` · stabilité ${Math.round(rect.stability * 100)} %` : "";
      return `<button class="tm-tile${small ? " small" : ""}${tiny ? " tiny" : ""}" type="button" data-${mode}="${esc(rect.id)}" style="left:${(rect.x * 100).toFixed(3)}%;top:${(rect.y * 100).toFixed(3)}%;width:${(rect.width * 100).toFixed(3)}%;height:${(rect.height * 100).toFixed(3)}%;--c:${rect.color || "var(--accent)"}" aria-label="${esc(rect.label)} — ${esc(rect.meta || "")}${stability}">
        <span class="tm-name">${esc(rect.label)}</span>
        <span class="tm-meta">${esc(rect.meta || "")}${stability}</span>
        ${rect.tags?.length && !small ? `<span class="tm-tags">${rect.tags.map((tag) => esc(tag)).join(" · ")}</span>` : ""}
      </button>`;
    })
    .join("")}</div>`;
}

/* ------------------------------ Shortlist ------------------------------ */

function renderShortlist() {
  const entries = [...state.shortlist.values()]
    .map((entry) => ({ entry, track: state.trackById.get(entry.id) }))
    .filter((item) => item.track)
    .sort((a, b) => a.entry.order - b.entry.order);
  const counts = Object.fromEntries(STATUS_ORDER.map((status) => [status, 0]));
  entries.forEach(({ entry }) => {
    counts[entry.status] = (counts[entry.status] || 0) + 1;
  });
  const chosen = entries.find(({ entry }) => entry.status === "choisi");
  const filtered = state.shortlistFilter
    ? entries.filter(({ entry }) => entry.status === state.shortlistFilter)
    : entries;
  const compareTracks = state.compare
    .map((id) => state.trackById.get(id))
    .filter(Boolean);

  const targetHint = entries.length > 15
    ? " · au-delà de 15, écartez pour converger"
    : entries.length > 0 && entries.length < 5
      ? ` · encore ${5 - entries.length} pour une short-list confortable`
      : "";
  const decision = chosen
    ? `<section class="decision-banner">
        <div><span class="kicker">Décision</span><strong>${esc(chosen.track.title)}</strong><span>${esc(chosen.track.artist)} · ${esc(chosen.track.license)}</span></div>
        <div class="chips"><button class="btn small primary" type="button" data-export-pack>${icon("download")} Pack MP3 + crédits</button><button class="btn small ghost" type="button" data-copy-credit="${esc(chosen.track.id)}">${icon("copy")} Copier le crédit</button></div>
      </section>`
    : "";
  let body = "";
  if (!entries.length) {
    body = `<div class="empty big">
      <h2>Votre short-list est vide</h2>
      <p>Parcourez un groupe, écoutez quelques extraits et ajoutez 5 à 15 candidates. Vous pourrez les comparer ici.</p>
      <a class="btn primary" href="#/groups">Explorer les groupes</a>
    </div>`;
  } else {
    const cards = filtered
      .map(({ entry, track }) => shortlistCard(entry, track))
      .join("");
    body = `<div class="status-tabs" role="tablist" aria-label="Statuts">
        <button class="chip${!state.shortlistFilter ? " active" : ""}" type="button" role="tab" aria-selected="${!state.shortlistFilter}" data-status-filter="">Toutes <b>${entries.length}</b></button>
        ${STATUS_ORDER.map(
          (status) =>
            `<button class="chip${state.shortlistFilter === status ? " active" : ""}" type="button" role="tab" aria-selected="${state.shortlistFilter === status}" data-status-filter="${status}">${STATUS[status]} <b>${counts[status] || 0}</b></button>`
        ).join("")}
      </div>
      ${compareTracks.length >= 2 ? renderCompare(compareTracks) : ""}
      <div class="sl-list">${cards || `<div class="empty">Aucune piste dans ce statut.</div>`}</div>`;
  }

  $("#view").innerHTML = `<div class="page">
    ${pageHead(
      "Étape 4",
      "Short-list",
      chosen
        ? `Piste choisie : ${chosen.track.title} — ${chosen.track.artist}.`
        : entries.length
          ? "Écoutez, statuez, comparez. Objectif : 5 à 15 candidates, puis une décision."
          : "Constituez votre sélection de finalistes.",
      `<a class="btn ghost" href="#/groups">${icon("arrow-left")} Explorer</a>
       <button class="btn ghost" type="button" data-export="json" ${entries.length ? "" : "disabled"}>Export JSON</button>
       <button class="btn primary" type="button" data-export-pack ${entries.length ? "" : "disabled"}>${icon("download")} Pack MP3 + crédits</button>`
    )}
    ${decision}
    <div class="toolbar">
      <span class="micro">${entries.length} piste(s) · ${counts.retenu || 0} retenue(s) · ${counts.choisi || 0} choisie(s)${entries.some(({ entry }) => !entry.licenseChecked) ? ` · ${entries.filter(({ entry }) => !entry.licenseChecked).length} licence(s) à vérifier` : " · licences vérifiées"}${targetHint}</span>
      <div class="chips">
        <button class="chip" type="button" data-export="csv" ${entries.length ? "" : "disabled"}>CSV</button>
        <button class="chip" type="button" data-action="copy-credits" ${entries.length ? "" : "disabled"}>Copier les crédits</button>
        ${chosen ? `<button class="chip" type="button" data-export="md">Fiche de décision</button>` : ""}
      </div>
    </div>
    ${body}
  </div>`;

  $$("[data-status-filter]").forEach((button) => {
    button.addEventListener("click", () => {
      state.shortlistFilter = button.dataset.statusFilter || null;
      syncUrl();
      refreshView(`[data-status-filter="${CSS.escape(state.shortlistFilter || "")}"]`);
    });
  });
  const tabList = $(".status-tabs");
  if (tabList) {
    tabList.addEventListener("keydown", (event) => {
      if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
      const tabs = $$("[data-status-filter]", tabList);
      const current = tabs.indexOf(document.activeElement);
      if (current < 0) return;
      event.preventDefault();
      let next = current;
      if (event.key === "ArrowRight") next = (current + 1) % tabs.length;
      if (event.key === "ArrowLeft") next = (current - 1 + tabs.length) % tabs.length;
      if (event.key === "Home") next = 0;
      if (event.key === "End") next = tabs.length - 1;
      tabs[next].focus();
    });
  }
  bindTrackGrid();
}

function shortlistCard(entry, track) {
  const path = clusterPath(track);
  return `<article class="sl-card${entry.status === "choisi" ? " chosen" : ""}">
    <div class="sl-top">
      <a class="tc-title" href="#/track/${encodeURIComponent(track.id)}">${esc(track.title)}</a>
      <span class="tc-dur">${fmtDur(track.duration)}</span>
    </div>
    <div class="tc-sub">${esc(track.artist)}${path.length ? ` · ${esc(path.join(" › "))}` : ""}</div>
    <div class="sl-controls">
      <label class="field-inline">Statut
        <select data-status="${esc(track.id)}">
          ${STATUS_ORDER.map(
            (status) =>
              `<option value="${status}" ${entry.status === status ? "selected" : ""}>${STATUS[status]}</option>`
          ).join("")}
        </select>
      </label>
      <label class="field-inline grow">Note
        <input type="text" data-note="${esc(track.id)}" value="${esc(entry.note)}" placeholder="Plan, réserve, raison…">
      </label>
    </div>
    <div class="sl-license">
      <span class="micro">${esc(track.license)} · crédit ${esc(track.credit)}</span>
      <label class="check small"><input type="checkbox" data-license="${esc(track.id)}" ${entry.licenseChecked ? "checked" : ""}> Licence vérifiée</label>
    </div>
    <div class="sl-actions">
      <button class="btn small" type="button" data-preview="${esc(track.id)}">${icon("play")} 12 s</button>
      <a class="btn small ghost" href="#/track/${encodeURIComponent(track.id)}">Analyser</a>
      <label class="check small"><input type="checkbox" data-compare="${esc(track.id)}" ${state.compare.includes(track.id) ? "checked" : ""}> Comparer</label>
      <button class="btn small ghost" type="button" data-move-id="${esc(track.id)}" data-move="-1" aria-label="Monter dans la short-list">↑</button>
      <button class="btn small ghost" type="button" data-move-id="${esc(track.id)}" data-move="1" aria-label="Descendre dans la short-list">↓</button>
      <button class="btn small danger" type="button" data-remove="${esc(track.id)}">${icon("trash")} Retirer</button>
    </div>
  </article>`;
}

function renderCompare(tracks) {
  const rows = [
    ["Valence", (track) => fmtSigned(effective(track).valence)],
    ["Arousal", (track) => fmtSigned(effective(track).arousal)],
    ["Tension", (track) => fmtSigned(effective(track).tension)],
    ["Énergie", (track) => fmtPct(track.energy)],
    ["BPM", (track) => Math.round(Number(track.bpm) || 0)],
    ["Durée", (track) => fmtDur(track.duration)],
    ["Confiance", (track) => fmtPct(track.confidence)],
    ["Boucle", (track) => fmtPct(track.loopability)],
  ];
  if (state.brief) rows.push(["Brief", (track) => `${Math.round(briefScore(track) * 100)} %`]);
  rows.push(["Licence", (track) => track.license || "—"]);
  return `<section class="panel compare-panel">
    <div class="panel-head"><div><h2>Comparer</h2><p class="micro">${tracks.length} pistes sélectionnées</p></div><button class="btn ghost small" type="button" data-compare-clear>Vider</button></div>
    <div class="table-scroll"><table class="compare-table">
      <thead><tr><th></th>${tracks.map((track) => `<th>${esc(track.title)}</th>`).join("")}</tr></thead>
      <tbody>${rows
        .map(
          ([label, render]) =>
            `<tr><th>${esc(label)}</th>${tracks.map((track) => `<td>${esc(render(track))}</td>`).join("")}</tr>`
        )
        .join("")}</tbody>
    </table></div>
    <div class="panel-actions">
      <button class="btn small" type="button" data-ab-start="${esc(tracks[0].id)}|${esc(tracks[1].id)}">${icon("compare")} Comparer A/B</button>
      ${tracks.length > 2 ? `<button class="btn small ghost" type="button" data-play-compare>Écouter la suite (6 s)</button>` : ""}
      ${state.ab ? `<span class="ab-status">A/B en cours · écoute <b>${state.ab.active.toUpperCase()}</b> · <button class="link" type="button" data-ab-toggle>Basculer</button> · <button class="link" type="button" data-ab-stop>Arrêter</button></span>` : ""}
      ${tracks.some((track) => shortlistEntry(track.id)?.status === "choisi") ? "" : `<button class="btn small primary" type="button" data-choose="${esc(tracks[0].id)}">Choisir ${esc(tracks[0].title)}</button>`}
    </div>
  </section>`;
}

/* ------------------------------ Track ------------------------------ */

function renderTrack(trackId) {
  const track = state.trackById.get(trackId);
  if (!track) {
    $("#view").innerHTML = `<div class="page">${pageHead("Étape 5", "Piste introuvable", "Cette piste n’existe pas.")}<a class="btn primary" href="#/groups">Retour</a></div>`;
    return;
  }
  const effect = effective(track);
  const entry = shortlistEntry(track.id);
  const path = clusterPath(track);
  const reasons = briefReasons(track);
  const topTags = Object.entries(track.tag_scores || {})
    .filter(([name]) => name !== "Instrumental")
    .sort((a, b) => b[1] - a[1])
    .slice(0, 7);
  const usages = Object.entries(track.usage_scores || {}).sort((a, b) => b[1] - a[1]);
  const similar = state.tracks
    .filter((item) => item.id !== track.id)
    .map((item) => {
      const other = effective(item);
      const distance = Math.hypot(
        other.valence - effect.valence,
        other.arousal - effect.arousal,
        0.8 * (other.tension - effect.tension)
      );
      return { track: item, distance };
    })
    .sort((a, b) => a.distance - b.distance)
    .slice(0, 4);

  $("#view").innerHTML = `<div class="page">
    <a class="back-link" href="${path.length ? `#/group/${encodeURIComponent(track.cluster)}` : "#/groups"}">${icon("arrow-left")} Retour au groupe</a>
    <header class="track-hero">
      <div>
        <div class="kicker">${esc(track.family)} · ${esc(track.genre)}${effect.manual ? " · annotation manuelle" : ""}${state.brief ? ` · ${Math.round(briefScore(track) * 100)} % brief` : ""}</div>
        <h1>${esc(track.title)}</h1>
        <p class="lede">${esc(track.artist)}${path.length ? ` · ${esc(path.join(" › "))}` : ""}</p>
        <div class="tc-tags">${visibleTags(track).map((tag) => `<span class="tag" style="--tag:${tagColor(tag)}">${esc(tag)}</span>`).join("")}</div>
      </div>
      <div class="hero-actions">
        <button class="btn primary" type="button" data-preview="${esc(track.id)}">${icon("play")} Écouter 12 s</button>
        <button class="btn ghost" type="button" data-play-full="${esc(track.id)}">Écouter en entier</button>
        ${entry ? `<span class="badge">${STATUS[entry.status]}</span>` : `<button class="btn ghost" type="button" data-add="${esc(track.id)}">${icon("plus")} Short-list</button>`}
      </div>
    </header>
    ${reasons.length ? `<div class="reason-bar">${reasons.map((reason) => `<span>${esc(reason)}</span>`).join("")}</div>` : ""}
    <div class="detail-grid">
      <section class="panel decision">
        <div class="panel-head"><div><h2>Décider</h2><p class="micro">Les chiffres utiles au montage</p></div></div>
        <div class="stat-grid">
          <div class="stat"><span>Durée</span><b>${fmtDur(track.duration)}</b></div>
          <div class="stat"><span>BPM</span><b>${Math.round(Number(track.bpm) || 0)}</b></div>
          <div class="stat"><span>Tonalité</span><b>${esc(track.key || "—")}</b></div>
          <div class="stat"><span>Hook</span><b>${fmtTime(track.hook_start)}</b></div>
          <div class="stat"><span>Boucle</span><b>${fmtPct(track.loopability)}</b></div>
          <div class="stat"><span>Confiance</span><b>${fmtPct(track.confidence)}</b></div>
        </div>
        <div class="gauges">
          ${gauge("Valence", effect.valence, "mélancolique → solaire", "var(--accent-2)")}
          ${gauge("Arousal", effect.arousal, "calme → énergique", "var(--calm)")}
          ${gauge("Tension", effect.tension, "résolution → attente", "var(--tense)")}
        </div>
        <div class="panel-actions">
          ${entry?.status === "choisi" ? `<span class="chosen-pill">${icon("check")} Piste choisie</span>` : `<button class="btn primary" type="button" data-choose="${esc(track.id)}">${icon("check")} Choisir cette piste</button>`}
          <button class="btn ghost" type="button" data-download="${esc(track.id)}">${icon("download")} MP3</button>
        </div>
      </section>
      <section class="panel">
        <div class="panel-head"><div><h2>Comprendre</h2><p class="micro">Graphiques et structure</p></div></div>
        <details class="fold">
          <summary>Arc temporel</summary>
          ${arcHtml(track)}
        </details>
        <details class="fold">
          <summary>Chroma et tonalité</summary>
          ${chromaHtml(track)}
        </details>
        <details class="fold">
          <summary>Tags estimés</summary>
          <div class="bars">${topTags.map(([name, score]) => barRow(name, score, tagColor(name))).join("")}</div>
        </details>
        <details class="fold">
          <summary>Usages cinéma</summary>
          <div class="bars">${usages.map(([name, score]) => barRow(name, score, "var(--accent)")).join("")}</div>
        </details>
      </section>
      <section class="panel">
        <div class="panel-head"><div><h2>Licence et crédit</h2><p class="micro">À conserver avec le MP3</p></div></div>
        <div class="license-box">
          <p><strong>${esc(track.license)}</strong> · crédit : ${esc(track.credit)}</p>
          <p class="micro">Vérifiez la licence et conservez ce crédit avant publication. Content ID peut revendiquer une piste même sous licence libre.</p>
          <div class="chips">
            <button class="chip" type="button" data-copy-credit="${esc(track.id)}">${icon("copy")} Copier le crédit</button>
            <a class="chip" href="${esc(track.source_url)}" target="_blank" rel="noopener">${icon("external")} Source</a>
            ${track.license_url ? `<a class="chip" href="${esc(track.license_url)}" target="_blank" rel="noopener">Texte de la licence</a>` : ""}
          </div>
        </div>
        <details class="annotation-details">
          <summary>Annotation manuelle <span class="micro">locale, prioritaire sur les scores auto</span></summary>
          ${annotationHtml(track)}
        </details>
      </section>
      <section class="panel">
        <div class="panel-head"><div><h2>Pistes proches</h2><p class="micro">Même voisinage affectif</p></div></div>
        <div class="similar-list">
          ${similar.map(({ track: near, distance }) => `<a class="similar" href="#/track/${encodeURIComponent(near.id)}"><span>${esc(near.title)} · ${esc(near.artist)}</span><b>d ${distance.toFixed(2)}</b></a>`).join("")}
        </div>
      </section>
    </div>
  </div>`;

  bindTrackGrid();
  bindTrackExtras(track);
  if (!track.features || !track.tag_scores) loadTrackDetail(track);
}

const detailLoading = new Set();

async function loadTrackDetail(track) {
  if (detailLoading.has(track.id)) return;
  detailLoading.add(track.id);
  try {
    const response = await fetch(`/api/track/${encodeURIComponent(track.id)}`);
    if (!response.ok) throw new Error("Analyse indisponible");
    Object.assign(track, await response.json());
    if (state.route.name === "track" && state.route.trackId === track.id) refreshView();
  } catch (error) {
    showToast(error.message || "Analyse indisponible.", "error");
  } finally {
    detailLoading.delete(track.id);
  }
}

function bindTrackExtras(track) {
  $$("[data-play-full]").forEach((button) => {
    button.addEventListener("click", () => playTrack(track, { preview: false }));
  });
  $$("[data-download]").forEach((button) => {
    button.addEventListener("click", () => downloadTrack(track.id));
  });
  const form = $("#annotationForm");
  if (form) {
    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      const payload = {
        track_id: track.id,
        valence: Number($("#ann-valence").value),
        arousal: Number($("#ann-arousal").value),
        tension: Number($("#ann-tension").value),
        tags: $$(".ann-tag.active").map((node) => node.dataset.annTag),
        note: $("#annNote").value.trim(),
      };
      try {
        const response = await fetch("/api/annotations", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(payload),
        });
        if (!response.ok) throw new Error("Enregistrement impossible");
        const data = await response.json();
        track.annotation = { ...payload, updated_at: data.updated_at };
        showToast("Annotation enregistrée.");
        refreshView();
      } catch (error) {
        showToast(error.message || "Annotation impossible.", "error");
      }
    });
    form.addEventListener("input", (event) => {
      if (event.target.matches(".ann-slider input")) {
        const output = event.target.parentElement.querySelector("output");
        if (output) output.textContent = fmtSigned(event.target.value);
      }
    });
    const clear = $("[data-clear-annotation]");
    if (clear) {
      clear.addEventListener("click", async () => {
        try {
          await fetch(`/api/annotations/${encodeURIComponent(track.id)}`, { method: "DELETE" });
          track.annotation = null;
          showToast("Annotation effacée.");
          refreshView();
        } catch {
          showToast("Suppression impossible.", "error");
        }
      });
    }
  }
  $$(".ann-tag").forEach((button) => {
    button.addEventListener("click", () => {
      button.classList.toggle("active");
      button.setAttribute("aria-pressed", button.classList.contains("active") ? "true" : "false");
    });
  });
}

function annotationHtml(track) {
  const annotation = track.annotation || {};
  const effect = effective(track);
  const selected = new Set(annotation.tags || []);
  const tags = state.tags
    .filter((tag) => tag.category === "émotion" || tag.category === "contexte")
    .map(
      (tag) =>
        `<button class="chip ann-tag${selected.has(tag.name) ? " active" : ""}" type="button" data-ann-tag="${esc(tag.name)}" aria-pressed="${selected.has(tag.name)}" style="--tag:${tag.color}"><i class="dot"></i>${esc(tag.name)}</button>`
    )
    .join("");
  return `<form class="annotation-form" id="annotationForm">
    ${annSlider("valence", "Valence", annotation.valence ?? effect.valence)}
    ${annSlider("arousal", "Arousal", annotation.arousal ?? effect.arousal)}
    ${annSlider("tension", "Tension", annotation.tension ?? effect.tension)}
    <div class="chips ann-tags">${tags}</div>
    <textarea id="annNote" rows="2" aria-label="Note d’écoute" placeholder="Note d’écoute, plan prévu, réserve…">${esc(annotation.note || "")}</textarea>
    <div class="form-actions">
      <button class="btn small primary" type="submit">${icon("check")} Enregistrer</button>
      ${annotation.updated_at ? `<button class="btn small ghost" type="button" data-clear-annotation>Effacer</button>` : ""}
    </div>
  </form>`;
}

function annSlider(key, label, value) {
  const v = Math.max(-1, Math.min(1, Number(value) || 0));
  return `<label class="ann-slider"><span>${label}</span><input type="range" id="ann-${key}" min="-1" max="1" step="0.01" value="${v.toFixed(2)}"><output>${fmtSigned(v)}</output></label>`;
}

function gauge(label, value, legend, color) {
  const v = Math.max(-1, Math.min(1, Number(value) || 0));
  const width = Math.abs(v) * 50;
  const left = v >= 0 ? 50 : 50 - width;
  return `<div class="gauge"><div class="gauge-head"><span>${esc(label)}</span><b>${fmtSigned(v)}</b></div><div class="gauge-track"><span style="left:${left.toFixed(1)}%;width:${width.toFixed(1)}%;--g:${color}"></span><i></i></div><div class="gauge-legend">${esc(legend)}</div></div>`;
}

function barRow(label, value, color) {
  return `<div class="bar-row"><span>${esc(label)}</span><span class="bar"><i style="width:${(clamp01(value) * 100).toFixed(1)}%;--g:${color}"></i></span><b>${Number(value).toFixed(2)}</b></div>`;
}

function arcHtml(track) {
  const arc = Array.isArray(track.arc) && track.arc.length ? track.arc : Array(12).fill(0.4);
  const peak = Number(track.features?.arc_peak_index ?? -1);
  return `<div class="arc">${arc
    .map((value, index) => `<i class="${index === peak ? "peak" : ""}" style="height:${(8 + clamp01(value) * 82).toFixed(1)}%"></i>`)
    .join("")}</div>
    <div class="arc-meta"><span>intro ${fmtTime(track.intro_end)}</span><span>pic ${fmtTime(track.peak_time)}</span><span>sortie ${fmtTime(track.outro_start)}</span><span>hook ${fmtTime(track.hook_start)}</span></div>`;
}

function chromaHtml(track) {
  const chroma = track.features?.chroma_mean || [];
  const root = Number(track.features?.key_root ?? 0);
  const names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];
  const max = Math.max(...chroma, 0.001);
  return `<div class="chroma">${names
    .map((name, index) => {
      const value = Number(chroma[index] || 0);
      return `<div class="chroma-bar${index === root ? " root" : ""}"><span style="height:${(clamp01(value / max) * 100).toFixed(1)}%"></span><small>${name}</small></div>`;
    })
    .join("")}</div>
    <p class="micro">Tonalité ${esc(track.key || "—")} · confiance ${fmtPct(track.key_confidence)}</p>`;
}

function scatterHtml(tracks, node) {
  if (!tracks.length) return "";
  const width = 360;
  const height = 240;
  const pad = 28;
  const points = tracks
    .map((track, index) => {
      const effect = effective(track);
      const jitter = ((index * 37) % 10) / 400 - 0.0125;
      const x = pad + clamp01(effect.arousal01 + jitter) * (width - pad * 2);
      const y = height - pad - clamp01(effect.valence01 - jitter) * (height - pad * 2);
      const hue = 190 - 190 * effect.tension01;
      return `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="4.2" fill="hsl(${hue.toFixed(1)} 46% 58%)" opacity=".85"><title>${esc(track.title)}</title></circle>`;
    })
    .join("");
  return `<section class="panel mini-map">
    <div class="panel-head"><div><h2>Position du groupe</h2><p class="micro">Carte affective du cohorte</p></div></div>
    <svg class="scatter" viewBox="0 0 ${width} ${height}" role="img" aria-label="Carte valence-arousal des ${tracks.length} pistes de ${esc(node.name)} : ${tracks.length} points, la liste ci-contre donne le détail accessible.">
      <rect x="${pad}" y="${pad}" width="${width - pad * 2}" height="${height - pad * 2}" fill="none" stroke="var(--line)"/>
      <line x1="${width / 2}" y1="${pad}" x2="${width / 2}" y2="${height - pad}" stroke="var(--line)"/>
      <line x1="${pad}" y1="${height / 2}" x2="${width - pad}" y2="${height / 2}" stroke="var(--line)"/>
      ${points}
    </svg>
    <div class="axis-labels"><span>calme</span><span>énergique</span><span>mélancolique</span><span>solaire</span></div>
    <p class="micro">${tracks.length} pistes · couleur = tension</p>
  </section>`;
}

/* ------------------------------ Player ------------------------------ */

function currentTrack() {
  return state.player.currentId ? state.trackById.get(state.player.currentId) : null;
}

function stopAB({ refresh = false } = {}) {
  if (!state.ab) return;
  abA.pause();
  abB.pause();
  state.ab = null;
  if (refresh) refreshView();
}

function startAB(aId, bId) {
  const first = state.trackById.get(aId);
  const second = state.trackById.get(bId);
  if (!first || !second || first.id === second.id) return;
  stopAB();
  state.player.preview = false;
  state.player.currentId = null;
  audio.pause();
  audio.removeAttribute("src");
  abA.pause();
  abB.pause();
  const offset = Math.max(0, Math.min(30, Math.min(first.duration, second.duration) - 20));
  const ready = { a: false, b: false };
  const start = () => {
    if (!ready.a || !ready.b || !state.ab) return;
    abA.currentTime = offset;
    abB.currentTime = offset;
    abA.volume = audio.volume;
    abB.volume = audio.volume;
    abA.play().catch(() => {});
  };
  abA.onloadedmetadata = () => { ready.a = true; start(); };
  abB.onloadedmetadata = () => { ready.b = true; start(); };
  abA.src = first.audio_url;
  abB.src = second.audio_url;
  state.ab = { aId, bId, active: "a", offset };
  abA.load();
  abB.load();
  $("#nowTitle").textContent = "Comparaison A/B";
  $("#nowArtist").textContent = `${first.title} ↔ ${second.title}`;
  refreshView();
  showToast("Comparaison A/B · même position, bascule instantanée.");
}

function toggleAB() {
  if (!state.ab) return;
  const isA = state.ab.active === "a";
  const from = isA ? abA : abB;
  const to = isA ? abB : abA;
  const position = Number(from.currentTime) || state.ab.offset;
  from.pause();
  to.currentTime = position;
  to.play().catch(() => {});
  state.ab.active = isA ? "b" : "a";
  refreshView();
}

function playTrack(track, { preview = true } = {}) {
  if (!track) return;
  stopAB();
  const start = Number(track.hook_start) || 0;
  const same = state.player.currentId === track.id;
  state.player.preview = preview;
  state.player.currentId = track.id;
  if (!same) {
    audio.src = track.audio_url;
    audio.load();
    audio.dataset.seek = String(start);
  } else if (audio.readyState >= 1) {
    audio.currentTime = start;
  }
  const play = () => audio.play().catch(() => {});
  if (same) play();
  updateNowPlaying(track);
  updatePreviewBadge();
}

function playFull(track) {
  playTrack(track, { preview: false });
}

function updateNowPlaying(track) {
  $("#nowTitle").textContent = track.title;
  $("#nowArtist").textContent = `${track.artist}${track.cluster_name ? ` · ${track.cluster_name}` : ""}`;
  $("#playBtn").disabled = false;
  $("#downloadBtn").disabled = false;
  $("#shortlistBtn").disabled = false;
  const entry = shortlistEntry(track.id);
  $("#shortlistBtn").style.color = entry ? "var(--accent-2)" : "";
  $("#shortlistBtn").querySelector(".icon").style.fill = entry ? "currentColor" : "none";
  $("#timeTotal").textContent = fmtDur(track.duration);
}

function updatePreviewBadge() {
  const badge = $("#previewBadge");
  const playing = !audio.paused && state.player.preview;
  badge.hidden = !playing;
}

function togglePlay() {
  const track = currentTrack() || state.trackById.get(state.route.trackId);
  if (!track) {
    showToast("Choisissez d’abord une piste.");
    return;
  }
  if (state.player.currentId !== track.id) {
    playTrack(track, { preview: true });
    return;
  }
  if (audio.paused) audio.play().catch(() => {});
  else audio.pause();
}

function updateTimeline() {
  const duration = Number(audio.duration) || 0;
  const current = Number(audio.currentTime) || 0;
  $("#timeCurrent").textContent = fmtTime(current);
  $("#timeTotal").textContent = duration ? fmtTime(duration) : "0:00";
  $("#seek").value = duration ? Math.round((current / duration) * 1000) : 0;
  $("#seek").setAttribute("aria-valuetext", `${fmtTime(current)} sur ${fmtTime(duration)}`);
  const track = currentTrack();
  if (!track || !duration) return;
  const hookStart = Number(track.hook_start) || 0;
  const hookEnd = hookStart + (Number(track.hook_duration) || 12);
  if (state.player.loop && current >= hookEnd - 0.05) {
    audio.currentTime = hookStart;
    return;
  }
  if (state.player.preview && current >= hookEnd - 0.05) {
    audio.pause();
    state.player.preview = false;
    updatePreviewBadge();
  }
}

function downloadTrack(id) {
  const track = state.trackById.get(id);
  if (!track) return;
  showToast(`Préparation de ${track.title}…`);
  fetch(`/api/download/${encodeURIComponent(id)}`)
    .then((response) => {
      if (!response.ok) throw new Error("Téléchargement impossible");
      const disposition = response.headers.get("content-disposition") || "";
      const match = /filename\*=UTF-8''([^;]+)/i.exec(disposition);
      const name = match ? decodeURIComponent(match[1]) : `${track.artist} - ${track.title}.mp3`;
      return response.blob().then((blob) => ({ blob, name }));
    })
    .then(({ blob, name }) => {
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = name;
      document.body.appendChild(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      showToast("Téléchargement lancé.");
    })
    .catch((error) => showToast(error.message || "Téléchargement impossible.", "error"));
}

/* ------------------------------ Export ------------------------------ */

function selectionRows() {
  return [...state.shortlist.values()]
    .sort((a, b) => a.order - b.order)
    .map((entry) => {
      const track = state.trackById.get(entry.id);
      if (!track) return null;
      return {
        title: track.title,
        artist: track.artist,
        status: STATUS[entry.status],
        note: entry.note,
        license_checked: entry.licenseChecked ? "oui" : "non",
        duration: fmtDur(track.duration),
        bpm: Math.round(Number(track.bpm) || 0),
        license: track.license,
        credit: track.credit,
        source_url: track.source_url,
        cluster: clusterPath(track).join(" › "),
        brief: state.brief ? briefSummary() : "",
      };
    })
    .filter(Boolean);
}

function exportSelection(format) {
  const rows = selectionRows();
  if (!rows.length) {
    showToast("La short-list est vide.");
    return;
  }
  if (format === "json") {
    downloadBlob("atlas-selection.json", JSON.stringify(rows, null, 2), "application/json");
    return;
  }
  if (format === "csv") {
    const headers = ["title", "artist", "status", "note", "license_checked", "duration", "bpm", "license", "credit", "source_url", "cluster", "brief"];
    const escapeCsv = (value) => `"${String(value ?? "").replaceAll('"', '""')}"`;
    const csv = [headers.join(","), ...rows.map((row) => headers.map((header) => escapeCsv(row[header])).join(","))].join("\n");
    downloadBlob("atlas-selection.csv", csv, "text/csv");
    return;
  }
  if (format === "md") {
    const chosen = [...state.shortlist.values()].find((entry) => entry.status === "choisi");
    const track = chosen ? state.trackById.get(chosen.id) : null;
    const lines = [
      "# Décision musicale",
      "",
      track ? `**Piste choisie :** ${track.title} — ${track.artist}` : "**Aucune piste choisie**",
      state.brief ? `**Brief :** ${briefSummary()}` : "",
      "",
      "| Piste | Artiste | Statut | Licence vérifiée | Durée | BPM | Licence |",
      "|---|---|---|---|---|---|---|",
      ...rows.map((row) => `| ${row.title} | ${row.artist} | ${row.status} | ${row.license_checked} | ${row.duration} | ${row.bpm} | ${row.license} |`),
      "",
      "## Crédits",
      "",
      ...rows.map((row) => `- ${row.title} — ${row.artist} · ${row.license} · ${row.credit} · ${row.source_url}`),
    ];
    downloadBlob("atlas-decision.md", lines.join("\n"), "text/markdown");
  }
}

function downloadBlob(name, content, type) {
  const blob = new Blob([content], { type });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = name;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  showToast("Export lancé.");
}

function exportSelectionPack() {
  const items = [...state.shortlist.values()].map((entry) => ({
    id: entry.id,
    status: entry.status,
    note: entry.note,
    license_checked: Boolean(entry.licenseChecked),
  }));
  if (!items.length) {
    showToast("La short-list est vide.");
    return;
  }
  showToast("Préparation du pack MP3…");
  fetch("/api/export-selection", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ items, brief: state.brief ? briefSummary() : "" }),
  })
    .then((response) => {
      if (!response.ok) throw new Error("Export impossible");
      return response.blob();
    })
    .then((blob) => {
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = "atlas-selection.zip";
      document.body.appendChild(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      showToast("Pack MP3 téléchargé.");
    })
    .catch((error) => showToast(error.message || "Export impossible.", "error"));
}

function copyText(text) {
  navigator.clipboard
    ?.writeText(text)
    .then(() => showToast("Copié."))
    .catch(() => showToast("Copie impossible.", "error"));
}

function copyCredits() {
  const rows = selectionRows();
  if (!rows.length) {
    showToast("La short-list est vide.");
    return;
  }
  copyText(rows.map((row) => `${row.title} — ${row.artist} · ${row.license} · ${row.credit} · ${row.source_url}`).join("\n"));
}

/* ------------------------------ Dialog / theme ------------------------------ */

function applyTheme(theme) {
  const root = document.documentElement;
  const vars = {
    "--bg": theme.background,
    "--bg-2": theme.dark_background,
    "--bg-3": theme.darker_background,
    "--panel": theme.dark_background || theme.background,
    "--panel-2": theme.lighter_background,
    "--line": theme.lighter_background,
    "--line-2": theme.selection,
    "--fg": theme.foreground,
    "--fg-strong": theme.foreground || "#f0f1f1",
    "--muted": "#8a9094",
    "--muted-2": "#62686c",
    "--accent": theme.accent,
    "--accent-2": theme.light_foreground || theme.bright_foreground || theme.foreground,
    "--selection": theme.selection,
    "--danger": theme.bright_red || theme.red,
    "--calm": theme.cyan || "#5fa8b8",
    "--tense": theme.bright_red || theme.red || "#c45a5a",
  };
  for (const [key, value] of Object.entries(vars)) {
    if (value) root.style.setProperty(key, value);
  }
  root.dataset.theme = theme.mode || "dark";
}

function openDialog(title, html) {
  $("#dialogTitle").textContent = title;
  $("#dialogBody").innerHTML = html;
  const dialog = $("#appDialog");
  if (!dialog.open) dialog.showModal();
  $("#dialogClose").focus();
}

function helpHtml() {
  return `<h3>Le parcours en 5 étapes</h3>
    <ol class="help-list">
      <li><strong>Brief</strong> — optionnel : type de plan, durée, ton, boucle.</li>
      <li><strong>Explorer</strong> — choisissez un grand groupe.</li>
      <li><strong>Affiner</strong> — descendez dans les sous-groupes puis les pistes.</li>
      <li><strong>Short-list</strong> — écoutez 12 s, statuez, comparez 2-3 pistes.</li>
      <li><strong>Décider</strong> — analysez, choisissez, exportez le crédit.</li>
    </ol>
    <h3>Ce que veulent dire les chiffres</h3>
    <p>Valence : mélancolique → solaire. Arousal : calme → énergique. Tension : résolution → attente. Ces scores sont relatifs au corpus et estimés, pas mesurés cliniquement.</p>
    <h3>Raccourcis</h3>
    <p><kbd>/</kbd> recherche · <kbd>Espace</kbd> lecture/pause hors champ de saisie · <kbd>Échap</kbd> ferme les menus.</p>`;
}

function methodologyHtml() {
  return `<h3>Comment les groupes sont construits</h3>
    <p>Les pistes sont décrites par 24 features audio et trois axes affectifs. Les tags ne servent pas au clustering : ils servent à nommer les groupes. Une ACP réduit l’espace, puis Ward construit une hiérarchie de groupes et sous-groupes. La stabilité est estimée par bootstrap.</p>
    <h3>Comment lire les scores</h3>
    <p>Valence, arousal et tension sont des estimations relatives au corpus, avec une confiance. Elles ne mesurent pas une émotion ressentie. Les annotations manuelles remplacent les valeurs automatiques.</p>
    <h3>Licences</h3>
    <p>Chaque piste affiche sa licence, son crédit et sa source. Vérifiez-les avant publication : Content ID peut revendiquer une piste même sous licence libre.</p>`;
}

function creditsHtml() {
  return `<h3>Crédits</h3>
    <p>Les crédits complets sont générés localement dans <code>CREDITS.md</code>. Chaque fiche piste affiche son crédit et sa licence ; le bouton « Copier le crédit » prépare la ligne à coller dans une description.</p>
    <p>La short-list peut être exportée en JSON, CSV ou fiche de décision Markdown avec les crédits.</p>`;
}

/* ------------------------------ Events ------------------------------ */

function bindEvents() {
  $("#flowNav").addEventListener("click", (event) => {
    const button = event.target.closest("[data-nav]");
    if (!button || button.disabled) return;
    const nav = button.dataset.nav;
    if (nav === "brief") navigate("brief");
    else if (nav === "groups") navigate("groups");
    else if (nav === "group") {
      const id = state.route.groupId || state.trackById.get(state.route.trackId)?.cluster || state.lastGroupId;
      if (id) navigate(`group/${id}`);
    }
    else if (nav === "shortlist") navigate("shortlist");
    else if (nav === "track") navigate(state.route.trackId ? `track/${state.route.trackId}` : "shortlist");
  });

  $("#playBtn").addEventListener("click", togglePlay);
  $("#seek").addEventListener("input", (event) => {
    const duration = Number(audio.duration) || 0;
    if (duration) audio.currentTime = (Number(event.target.value) / 1000) * duration;
  });
  $("#volume").addEventListener("input", (event) => {
    audio.volume = Number(event.target.value) / 100;
    abA.volume = audio.volume;
    abB.volume = audio.volume;
    writeJSON(STORAGE.volume, audio.volume);
  });
  $("#loopBtn").addEventListener("click", () => {
    state.player.loop = !state.player.loop;
    $("#loopBtn").classList.toggle("active", state.player.loop);
    $("#loopBtn").setAttribute("aria-pressed", String(state.player.loop));
  });
  $("#downloadBtn").addEventListener("click", () => {
    const track = currentTrack();
    if (track) downloadTrack(track.id);
  });
  $("#shortlistBtn").addEventListener("click", () => {
    const track = currentTrack();
    if (track) {
      addToShortlist(track.id);
      updateNowPlaying(track);
    }
  });

  audio.addEventListener("loadedmetadata", () => {
    const seek = Number(audio.dataset.seek || 0);
    if (seek) audio.currentTime = Math.min(seek, Math.max(0, audio.duration - 0.1));
    audio.dataset.seek = "";
    audio.play().catch(() => {});
  });
  audio.addEventListener("timeupdate", updateTimeline);
  audio.addEventListener("play", () => {
    $("#playBtn").innerHTML = icon("pause");
    $("#playBtn").setAttribute("aria-label", "Pause");
    updatePreviewBadge();
  });
  audio.addEventListener("pause", () => {
    $("#playBtn").innerHTML = icon("play");
    $("#playBtn").setAttribute("aria-label", "Lecture");
    updatePreviewBadge();
  });
  audio.addEventListener("ended", () => {
    state.player.preview = false;
    updatePreviewBadge();
  });
  audio.addEventListener("error", () => showToast("Lecture audio impossible.", "error"));

  $("#menuBtn").addEventListener("click", (event) => {
    event.stopPropagation();
    const menu = $("#moreMenu");
    menu.hidden = !menu.hidden;
    $("#menuBtn").setAttribute("aria-expanded", String(!menu.hidden));
    if (!menu.hidden) $("button", menu)?.focus();
  });
  $("#moreMenu").addEventListener("keydown", (event) => {
    const items = $$("button", $("#moreMenu"));
    const index = items.indexOf(document.activeElement);
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      const next = event.key === "ArrowDown" ? (index + 1) % items.length : (index - 1 + items.length) % items.length;
      items[next]?.focus();
    } else if (event.key === "Home" || event.key === "End") {
      event.preventDefault();
      items[event.key === "Home" ? 0 : items.length - 1]?.focus();
    } else if (event.key === "Escape") {
      $("#moreMenu").hidden = true;
      $("#menuBtn").setAttribute("aria-expanded", "false");
      $("#menuBtn").focus();
    }
  });
  document.addEventListener("click", () => {
    $("#moreMenu").hidden = true;
    $("#menuBtn").setAttribute("aria-expanded", "false");
  });
  $("#moreMenu").addEventListener("click", (event) => {
    event.stopPropagation();
    const format = event.target.closest("[data-format]");
    if (format) {
      exportSelection(format.dataset.format);
      $("#moreMenu").hidden = true;
      return;
    }
    const action = event.target.closest("[data-action]");
    if (!action) return;
    $("#moreMenu").hidden = true;
    if (action.dataset.action === "export-pack") exportSelectionPack();
    else if (action.dataset.action === "copy-credits") copyCredits();
    else if (action.dataset.action === "methodology") openDialog("Méthodologie", methodologyHtml());
    else if (action.dataset.action === "credits") openDialog("Crédits", creditsHtml());
    else if (action.dataset.action === "export-base-json") window.location.href = "/api/export?format=json";
    else if (action.dataset.action === "export-base-sqlite") window.location.href = "/api/export?format=sqlite";
  });

  $("#globalSearchBtn").addEventListener("click", () => {
    navigate("groups");
    setTimeout(() => $("#searchInput")?.focus(), 80);
  });
  $("#helpBtn").addEventListener("click", () => openDialog("Aide", helpHtml()));
  $("#dialogClose").addEventListener("click", () => $("#appDialog").close());
  $("#appDialog").addEventListener("click", (event) => {
    if (event.target === $("#appDialog")) $("#appDialog").close();
  });

  $("#view").addEventListener("click", (event) => {
    const exportPack = event.target.closest("[data-export-pack]");
    if (exportPack) {
      exportSelectionPack();
      return;
    }
    const exportButton = event.target.closest("[data-export]");
    if (exportButton) {
      exportSelection(exportButton.dataset.export);
      return;
    }
    const action = event.target.closest("[data-action]");
    if (action?.dataset.action === "copy-credits") {
      copyCredits();
      return;
    }
    const copy = event.target.closest("[data-copy-credit]");
    if (copy) {
      const track = state.trackById.get(copy.dataset.copyCredit);
      if (track) copyText(`${track.title} — ${track.artist} · ${track.license} · ${track.credit} · ${track.source_url}`);
      return;
    }
    const group = event.target.closest("[data-group]");
    if (group) {
      navigate(`group/${encodeURIComponent(group.dataset.group)}`);
      return;
    }
    const clearCompare = event.target.closest("[data-compare-clear]");
    if (clearCompare) {
      state.compare = [];
      refreshView();
      return;
    }
    const abStart = event.target.closest("[data-ab-start]");
    if (abStart) {
      const [aId, bId] = abStart.dataset.abStart.split("|");
      startAB(aId, bId);
      return;
    }
    const abToggle = event.target.closest("[data-ab-toggle]");
    if (abToggle) {
      toggleAB();
      return;
    }
    const abStop = event.target.closest("[data-ab-stop]");
    if (abStop) {
      stopAB({ refresh: true });
      return;
    }
    const playCompare = event.target.closest("[data-play-compare]");
    if (playCompare) {
      playCompareSequence();
      return;
    }
    const add = event.target.closest("[data-add]");
    if (add) {
      event.preventDefault();
      addToShortlist(add.dataset.add);
      updateAddButtons(add.dataset.add);
      return;
    }
    const choose = event.target.closest("[data-choose]");
    if (choose) {
      chooseTrack(choose.dataset.choose);
      refreshView();
      return;
    }
    const toggle = event.target.closest("[data-toggle-tracks]");
    if (toggle) {
      state.showTracks = !state.showTracks;
      syncUrl();
      refreshView("[data-toggle-tracks]");
    }
  });

  document.addEventListener("keydown", (event) => {
    const tag = (event.target.tagName || "").toLowerCase();
    const typing = tag === "input" || tag === "textarea" || tag === "select";
    const interactive = event.target.closest("button, a, input, textarea, select, summary");
    if (event.key === "/" && !typing) {
      event.preventDefault();
      const input = $("#searchInput");
      if (input) input.focus();
    } else if (event.key === "Escape") {
      $("#moreMenu").hidden = true;
      if ($("#appDialog").open) $("#appDialog").close();
    } else if (event.code === "Space" && !typing && !interactive) {
      event.preventDefault();
      togglePlay();
    }
  });

  window.addEventListener("hashchange", () => renderRoute(true));
}

function playCompareSequence() {
  const tracks = state.compare.map((id) => state.trackById.get(id)).filter(Boolean);
  if (tracks.length < 2) return;
  let index = 0;
  const playNext = () => {
    if (index >= tracks.length) return;
    const track = tracks[index];
    index += 1;
    playTrack(track, { preview: true });
    const start = Number(track.hook_start) || 0;
    const stop = start + 6;
    const check = () => {
      if (!state.player.currentId || state.player.currentId !== track.id) return;
      if (audio.currentTime >= stop) {
        audio.pause();
        audio.removeEventListener("timeupdate", check);
        setTimeout(playNext, 250);
      }
    };
    audio.addEventListener("timeupdate", check);
  };
  playNext();
}

/* ------------------------------ Init ------------------------------ */

function showToast(message, kind = "", action = null) {
  const toast = $("#toast");
  toast.innerHTML = `<span>${esc(message)}</span>${action ? `<button class="toast-action" type="button">${esc(action.label)}</button>` : ""}`;
  toast.className = `toast${kind ? ` ${kind}` : ""}`;
  toast.setAttribute("role", kind === "error" ? "alert" : "status");
  toast.hidden = false;
  clearTimeout(showToast.timer);
  const timeout = action ? 6000 : 3200;
  showToast.timer = setTimeout(() => {
    toast.hidden = true;
  }, timeout);
  if (action) {
    $(".toast-action", toast)?.addEventListener("click", () => {
      clearTimeout(showToast.timer);
      toast.hidden = true;
      action.fn();
    });
  }
}

function renderFatal(error) {
  $("#view").innerHTML = `<div class="page"><div class="empty big">
    <h1>Bibliothèque indisponible</h1>
    <p>${esc(error.message || "Erreur inconnue.")}</p>
    <p class="micro">Lancez <code>python -m analysis.analyze</code> puis rechargez.</p>
    <button class="btn primary" type="button" onclick="location.reload()">Réessayer</button>
  </div></div>`;
}

async function init() {
  bindEvents();
  state.shortlist = loadShortlist();
  updateShortlistCount();
  const volume = Number(readJSON(STORAGE.volume, 0.8));
  audio.volume = Math.max(0, Math.min(1, volume));
  $("#volume").value = Math.round(audio.volume * 100);

  try {
    const [libraryResponse, themeResponse] = await Promise.all([
      fetch("/api/library/summary"),
      fetch("/api/theme"),
    ]);
    if (!libraryResponse.ok) throw new Error("Bibliothèque indisponible. Lancer analysis/analyze.py.");
    const library = await libraryResponse.json();
    state.library = library;
    state.tracks = library.tracks || [];
    state.tags = library.tags || [];
    state.usages = library.usages || [];
    state.tagMap = new Map(state.tags.map((tag) => [tag.name, tag]));
    state.trackById = new Map(state.tracks.map((track) => [track.id, track]));
    state.clusters = library.clusters || null;
    const nodes = state.clusters?.nodes || state.clusters?.clusters || [];
    state.nodes = new Map(nodes.map((node) => [node.id, node]));
    state.roots = state.clusters?.roots || (state.clusters?.clusters || []).map((node) => node.id);
    if (themeResponse.ok) applyTheme(await themeResponse.json());
    renderRoute(true);
  } catch (error) {
    renderFatal(error);
  }
}

init();
