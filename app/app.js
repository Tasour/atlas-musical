const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

const FAMILY_LABELS = {
  acoustique: "Acoustique / folk",
  cinematique: "Cinématique / ambient",
  tropical: "Tropical / chill",
  intense: "Intense / aventure",
};

const FAMILY_SHORT = {
  acoustique: "Acoustique",
  cinematique: "Cinématique",
  tropical: "Tropical",
  intense: "Intense",
};

const SORT_LABELS = {
  relevance: "pertinence",
  energy: "énergie",
  valence: "valence",
  tension: "tension",
  bpm: "BPM",
  duration: "durée",
  title: "titre",
};

const MAP = { width: 900, height: 620, pad: 58 };

const state = {
  library: null,
  tracks: [],
  tags: [],
  families: [],
  favorites: new Set(),
  selectedId: null,
  currentId: null,
  loop: false,
  pendingPlay: false,
  pendingSeek: null,
  previewStop: null,
  preset: "Tout",
  sort: "relevance",
  mapPositions: new Map(),
  filters: {
    q: "",
    families: new Set(),
    tags: new Set(),
    bpmMin: 0,
    bpmMax: 240,
    durMin: 0,
    durMax: 20,
    confMin: 0,
    favoritesOnly: false,
  },
};

const audio = $("#audio");
const tooltip = $("#mapTooltip");
const mapWrap = $("#mapWrap");
const svg = $("#emotionMap");

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
  const s = Math.max(0, Math.round(Number(seconds) || 0));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

function fmtDur(seconds) {
  const s = Math.round(Number(seconds) || 0);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

function fmtPct(value, digits = 0) {
  return `${(Number(value || 0) * 100).toFixed(digits)} %`;
}

function fmtSigned(value) {
  const n = Number(value || 0);
  return `${n >= 0 ? "+" : ""}${n.toFixed(2)}`;
}

function tensionColor(t) {
  const hue = 190 - 190 * clamp01(t);
  return `hsl(${hue.toFixed(1)} 46% 58%)`;
}

function tagMeta(name) {
  return state.tags.find((t) => t.name === name) || { color: "var(--accent)", category: "autre" };
}

function effective(track) {
  const a = track.annotation || {};
  const has = (key) => a[key] !== null && a[key] !== undefined;
  const valence = has("valence") ? Number(a.valence) : Number(track.valence);
  const arousal = has("arousal") ? Number(a.arousal) : Number(track.arousal);
  const tension = has("tension") ? Number(a.tension) : Number(track.tension);
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
  return Array.from(new Set([...(track.tags || []), ...((track.annotation && track.annotation.tags) || [])]));
}

function tagColorStyle(name) {
  return `--tag:${tagMeta(name).color}`;
}

function tagChip(name, compact = false) {
  return `<span class="chip${compact ? " compact" : ""}" style="${tagColorStyle(name)}"><i class="dot"></i>${esc(name)}</span>`;
}

function trackMatches(track) {
  const f = state.filters;
  const eff = effective(track);
  const tags = trackTags(track);
  if (f.q) {
    const hay = [track.title, track.artist, track.genre, track.family, track.key, ...tags]
      .join(" ")
      .toLowerCase();
    if (!hay.includes(f.q)) return false;
  }
  if (f.families.size && !f.families.has(track.family)) return false;
  for (const tag of f.tags) {
    if (!tags.includes(tag)) return false;
  }
  const bpm = Number(track.bpm) || 0;
  if (bpm < f.bpmMin || bpm > f.bpmMax) return false;
  const minutes = (Number(track.duration) || 0) / 60;
  if (minutes < f.durMin || minutes > f.durMax) return false;
  if ((Number(track.confidence) || 0) * 100 < f.confMin) return false;
  if (f.favoritesOnly && !state.favorites.has(track.id)) return false;
  if (state.preset !== "Tout") {
    const score = Number(track.usage_scores?.[state.preset] || 0);
    if (score < 0.65) return false;
  }
  return true;
}

function relevance(track) {
  if (state.preset !== "Tout") return Number(track.usage_scores?.[state.preset] || 0);
  const eff = effective(track);
  return 0.40 * (Number(track.confidence) || 0) + 0.32 * eff.valence01 + 0.28 * eff.arousal01;
}

function filteredTracks() {
  const list = state.tracks.filter(trackMatches);
  const sort = state.sort;
  list.sort((a, b) => {
    if (sort === "title") return a.title.localeCompare(b.title, "fr");
    if (sort === "bpm") return (Number(a.bpm) || 0) - (Number(b.bpm) || 0);
    if (sort === "duration") return (Number(a.duration) || 0) - (Number(b.duration) || 0);
    if (sort === "energy") return (Number(b.energy) || 0) - (Number(a.energy) || 0);
    if (sort === "valence") return effective(b).valence01 - effective(a).valence01;
    if (sort === "tension") return effective(b).tension01 - effective(a).tension01;
    return relevance(b) - relevance(a);
  });
  return list;
}

function selectedTrack() {
  return state.tracks.find((t) => t.id === state.selectedId) || null;
}

function currentTrack() {
  return state.tracks.find((t) => t.id === state.currentId) || null;
}

function renderFilters() {
  const familyHost = $("#familyFilters");
  familyHost.innerHTML = state.families
    .map((family) => {
      const count = state.tracks.filter((t) => t.family === family).length;
      const active = state.filters.families.has(family);
      return `<button class="chip${active ? " active" : ""}" type="button" data-family="${esc(family)}" aria-pressed="${active}">${esc(FAMILY_SHORT[family] || family)} <span class="count">${count}</span></button>`;
    })
    .join("");

  const tagHost = $("#tagFilters");
  const categories = [
    ["émotion", "Émotions"],
    ["texture", "Texture"],
    ["contexte", "Contexte"],
  ];
  tagHost.innerHTML = categories
    .map(([category, label]) => {
      const tags = state.tags.filter((t) => t.category === category);
      if (!tags.length) return "";
      return `<div class="tag-group"><div class="tag-group-title">${label}</div><div class="chips">${tags
        .map((tag) => {
          const active = state.filters.tags.has(tag.name);
          const count = state.tracks.filter((t) => trackTags(t).includes(tag.name)).length;
          return `<button class="chip${active ? " active" : ""}" type="button" data-tag="${esc(tag.name)}" aria-pressed="${active}" style="--tag:${tag.color}" title="${esc(tag.description || "")}"><i class="dot"></i>${esc(tag.name)} <span class="count">${count}</span></button>`;
        })
        .join("")}</div></div>`;
    })
    .join("");

  $("#bpmMin").value = state.filters.bpmMin;
  $("#bpmMax").value = state.filters.bpmMax;
  $("#durMin").value = state.filters.durMin;
  $("#durMax").value = state.filters.durMax;
  $("#confMin").value = state.filters.confMin;
  $("#confOut").value = `${state.filters.confMin} %`;
  $("#favoritesOnly").checked = state.filters.favoritesOnly;
  const filtered = filteredTracks().length;
  $("#filterSummary").textContent = `${filtered} / ${state.tracks.length} pistes`;
}

function renderPresets() {
  $$("#presets .chip").forEach((button) => {
    const active = button.dataset.preset === state.preset;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", active);
  });
  const caption = state.preset === "Tout" ? "Toutes les pistes" : `Preset : ${state.preset} — score d’usage ≥ 0.65`;
  $("#presetCaption").textContent = caption;
}

function buildMapBase() {
  const { width, height, pad } = MAP;
  const innerW = width - pad * 2;
  const innerH = height - pad * 2;
  const fills = [
    ["rgba(95,168,184,.035)", 0, 0],
    ["rgba(201,194,180,.035)", 0, 1],
    ["rgba(109,143,184,.035)", 1, 0],
    ["rgba(196,90,90,.035)", 1, 1],
  ];
  const quadrants = $("#mapQuadrants");
  quadrants.innerHTML = fills
    .map(([fill, col, row]) => {
      const x = pad + col * innerW / 2;
      const y = pad + row * innerH / 2;
      return `<rect x="${x}" y="${y}" width="${innerW / 2}" height="${innerH / 2}" fill="${fill}"/>`;
    })
    .join("");

  const grid = $("#mapGrid");
  const lines = [];
  [0.0, 0.25, 0.5, 0.75, 1.0].forEach((v) => {
    const x = pad + v * innerW;
    const y = height - pad - v * innerH;
    const mid = v === 0.5 ? " class=\"mid\"" : "";
    lines.push(`<line${mid} x1="${x}" y1="${pad}" x2="${x}" y2="${height - pad}"/>`);
    lines.push(`<line${mid} x1="${pad}" y1="${y}" x2="${width - pad}" y2="${y}"/>`);
  });
  grid.innerHTML = lines.join("");
}

function renderMap() {
  const { width, height, pad } = MAP;
  const innerW = width - pad * 2;
  const innerH = height - pad * 2;
  const filteredIds = new Set(filteredTracks().map((t) => t.id));
  state.mapPositions.clear();

  const points = state.tracks.map((track) => {
    const eff = effective(track);
    const x = pad + eff.arousal01 * innerW;
    const y = height - pad - eff.valence01 * innerH;
    state.mapPositions.set(track.id, { x, y, track });
    const color = tensionColor(eff.tension01);
    const selected = track.id === state.selectedId;
    const dimmed = !filteredIds.has(track.id);
    const favorite = state.favorites.has(track.id);
    const r = 6 + 7 * clamp01(track.confidence);
    const rx = 14 + 120 * Number(track.ellipse_rx || 0.06);
    const ry = 14 + 150 * Number(track.ellipse_ry || 0.06);
    return `<g class="point${selected ? " selected" : ""}${dimmed ? " dimmed" : ""}${favorite ? " favorite" : ""}" data-id="${esc(track.id)}" tabindex="0" role="button" aria-pressed="${selected}" aria-label="${esc(track.title)} — ${esc(track.artist)}" style="--pt-color:${color}" transform="translate(${x.toFixed(2)} ${y.toFixed(2)})">
      <ellipse class="halo" cx="0" cy="0" rx="${rx.toFixed(1)}" ry="${ry.toFixed(1)}"></ellipse>
      <circle class="ring" cx="0" cy="0" r="${(r + 7).toFixed(1)}"></circle>
      <circle class="core" cx="0" cy="0" r="${r.toFixed(1)}"></circle>
      <text class="label" x="0" y="${(-r - 11).toFixed(1)}" text-anchor="middle">${esc(track.title)}</text>
      <circle class="hit" cx="0" cy="0" r="${Math.max(18, r + 10)}"></circle>
    </g>`;
  });
  $("#mapPoints").innerHTML = points.join("");
  $$("#mapPoints .point").forEach((node) => {
    const track = state.tracks.find((t) => t.id === node.dataset.id);
    if (!track) return;
    node.addEventListener("click", (event) => {
      event.stopPropagation();
      selectTrack(track.id, { play: true });
    });
    node.addEventListener("keydown", (event) => {
      if (event.key === "Enter" || event.key === " ") {
        event.preventDefault();
        selectTrack(track.id, { play: true });
      }
    });
    node.addEventListener("mouseenter", (event) => showTooltip(track, event));
    node.addEventListener("mousemove", (event) => moveTooltip(event));
    node.addEventListener("mouseleave", hideTooltip);
    node.addEventListener("focus", () => showTooltipAtPoint(track, node));
    node.addEventListener("blur", hideTooltip);
  });
}

function showTooltip(track, event) {
  const eff = effective(track);
  tooltip.innerHTML = `<strong>${esc(track.title)}</strong>
    <div class="t-artist">${esc(track.artist)}</div>
    <div class="t-tags">${trackTags(track).slice(0, 3).map((tag) => `<span class="t-tag" style="${tagColorStyle(tag)}">${esc(tag)}</span>`).join("")}</div>
    <div class="t-row"><span>${Math.round((Number(track.bpm) || 0))} BPM · ${esc(track.key || "—")}</span><b>${fmtDur(track.duration)}</b></div>
    <div class="t-row"><span>valence ${fmtSigned(eff.valence)} · tension ${fmtSigned(eff.tension)}</span><b>${fmtPct(track.confidence)} conf.</b></div>`;
  tooltip.hidden = false;
  moveTooltip(event);
}

function showTooltipAtPoint(track, node) {
  const rect = node.getBoundingClientRect();
  showTooltip(track, { clientX: rect.left + rect.width / 2, clientY: rect.top });
}

function moveTooltip(event) {
  const wrap = mapWrap.getBoundingClientRect();
  const x = event.clientX - wrap.left;
  const y = event.clientY - wrap.top;
  const tw = tooltip.offsetWidth || 230;
  const th = tooltip.offsetHeight || 100;
  const left = x + 14 + tw > wrap.width ? x - tw - 14 : x + 14;
  const top = Math.max(8, Math.min(wrap.height - th - 8, y - th / 2));
  tooltip.style.left = `${Math.max(8, left)}px`;
  tooltip.style.top = `${top}px`;
  tooltip.style.transform = "none";
}

function hideTooltip() {
  tooltip.hidden = true;
}

function renderList() {
  const list = filteredTracks();
  $("#resultCount").textContent = list.length;
  $("#listCaption").textContent = `Tri par ${SORT_LABELS[state.sort] || state.sort}${state.preset !== "Tout" ? ` · preset ${state.preset}` : ""}`;
  const host = $("#trackList");
  if (!list.length) {
    host.innerHTML = `<div class="track-empty">Aucune piste ne correspond. Élargissez les filtres ou choisissez « Tout ».</div>`;
    return;
  }
  host.innerHTML = list
    .map((track) => {
      const eff = effective(track);
      const selected = track.id === state.selectedId;
      const favorite = state.favorites.has(track.id);
      const tags = trackTags(track);
      return `<div class="track-row${selected ? " selected" : ""}" role="listitem" tabindex="0" data-id="${esc(track.id)}" aria-label="${esc(track.title)} par ${esc(track.artist)}">
        <button class="track-play" type="button" data-play="${esc(track.id)}" aria-label="Écouter ${esc(track.title)}">${icon("play")}</button>
        <div class="track-main">
          <div class="track-title">${esc(track.title)} ${eff.manual ? '<span class="track-manual">manuel</span>' : ""}</div>
          <div class="track-artist">${esc(track.artist)} · ${esc(FAMILY_SHORT[track.family] || track.family)}</div>
          <div class="track-tags">${tags.slice(0, 4).map((tag) => `<span style="${tagColorStyle(tag)}">${esc(tag)}</span>`).join("")}</div>
        </div>
        <div class="track-side">
          <button class="track-fav" type="button" data-fav="${esc(track.id)}" aria-label="Favori" aria-pressed="${favorite}">${icon("star")}</button>
          <span class="track-bpm">${Math.round(Number(track.bpm) || 0)} BPM</span>
        </div>
      </div>`;
    })
    .join("");
}

function keyWheel(track) {
  const chroma = track.features?.chroma_mean || [];
  const root = Number(track.features?.key_root ?? 0);
  const names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"];
  const cx = 43;
  const cy = 43;
  const base = 34;
  const parts = [];
  for (let i = 0; i < 12; i++) {
    const angle = (-90 + i * 30) * (Math.PI / 180);
    const value = Number(chroma[i] || 0);
    const radius = 22 + 16 * clamp01(value / 0.22);
    const x1 = cx + Math.cos(angle) * 19;
    const y1 = cy + Math.sin(angle) * 19;
    const x2 = cx + Math.cos(angle) * radius;
    const y2 = cy + Math.sin(angle) * radius;
    const isRoot = i === root;
    const x = cx + Math.cos(angle) * base;
    const y = cy + Math.sin(angle) * base;
    parts.push(`<line x1="${x1.toFixed(1)}" y1="${y1.toFixed(1)}" x2="${x2.toFixed(1)}" y2="${y2.toFixed(1)}"/>`);
    parts.push(`<circle class="${isRoot ? "root" : "note"}" cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="${isRoot ? 3.8 : 2.2}"/>`);
    if (isRoot) {
      parts.push(`<text x="${x.toFixed(1)}" y="${(y + 2.8).toFixed(1)}" text-anchor="middle" fill="var(--bg)" font-size="4.2" font-family="monospace">${names[i]}</text>`);
    }
  }
  return `<svg class="key-wheel" viewBox="0 0 86 86" aria-hidden="true"><circle class="outer" cx="${cx}" cy="${cy}" r="39"/>${parts.join("")}</svg>`;
}

function arcBars(track) {
  const arc = Array.isArray(track.arc) && track.arc.length ? track.arc : Array(12).fill(0.4);
  const peak = Number(track.features?.arc_peak_index ?? -1);
  return arc
    .map((value, index) => `<i class="${index === peak ? "hot" : ""}" style="height:${(8 + clamp01(value) * 42).toFixed(1)}px"></i>`)
    .join("");
}

function similarTracks(track) {
  const eff = effective(track);
  return state.tracks
    .filter((t) => t.id !== track.id)
    .map((t) => {
      const e = effective(t);
      const d = Math.hypot(e.valence - eff.valence, e.arousal - eff.arousal, 0.8 * (e.tension - eff.tension));
      return { track: t, d };
    })
    .sort((a, b) => a.d - b.d)
    .slice(0, 3);
}

function annotationTagChips(track) {
  const selected = new Set(track.annotation?.tags || []);
  return state.tags
    .filter((tag) => tag.category === "émotion" || tag.category === "contexte")
    .map((tag) => `<button type="button" class="chip${selected.has(tag.name) ? " active" : ""}" data-ann-tag="${esc(tag.name)}" aria-pressed="${selected.has(tag.name)}" style="--tag:${tag.color}"><i class="dot"></i>${esc(tag.name)}</button>`)
    .join("");
}

function renderDetail() {
  const track = selectedTrack();
  if (!track) {
    $("#detailEmpty").hidden = false;
    $("#detailContent").hidden = true;
    return;
  }
  $("#detailEmpty").hidden = true;
  $("#detailContent").hidden = false;
  const eff = effective(track);
  const a = track.annotation || {};
  const tags = trackTags(track);
  const topTags = Object.entries(track.tag_scores || {})
    .filter(([name, score]) => !["Instrumental", "Littoral", "Aride/outback", "Brousse", "Nuit/route"].includes(name) && score >= 0.3)
    .sort((x, y) => y[1] - x[1])
    .slice(0, 6);
  const usages = Object.entries(track.usage_scores || {}).sort((x, y) => y[1] - x[1]);
  const similar = similarTracks(track);
  const manualBadge = eff.manual ? `<span class="badge-manual">annotation manuelle</span>` : "";
  const cuts = (track.cut_points || [])
    .map((time) => `<button type="button" data-time="${Number(time)}">${fmtTime(time)}</button>`)
    .join("");
  const cutMarkers = (track.cut_points || []).length
    ? `<div class="cut-list" aria-label="Points de coupe proposés">${cuts}</div>`
    : `<div class="annotation-hint">Aucun point de coupe fiable détecté.</div>`;

  $("#detailContent").innerHTML = `<div class="detail-inner">
    <div class="detail-hero">
      <div class="detail-kicker">${esc(FAMILY_SHORT[track.family] || track.family)} · ${esc(track.genre)} ${manualBadge}</div>
      <h2>${esc(track.title)}</h2>
      <div class="detail-artist">${esc(track.artist)}</div>
      <div class="detail-tags">${tags.map((tag) => tagChip(tag)).join("")}</div>
      <div class="detail-actions">
        <button class="btn primary" type="button" data-action="play-hook">${icon("play")} Écouter le hook</button>
        <button class="btn ghost" type="button" data-action="fav" aria-pressed="${state.favorites.has(track.id)}">${icon("star")} ${state.favorites.has(track.id) ? "Favori" : "Favoris"}</button>
        <a class="btn ghost" href="${esc(track.source_url)}" target="_blank" rel="noopener">Source ${icon("external")}</a>
      </div>
    </div>

    <div class="detail-section">
      <div class="stat-grid">
        <div class="stat"><span>BPM</span><b>${Math.round(Number(track.bpm) || 0)}</b></div>
        <div class="stat"><span>Tonalité</span><b>${esc(track.key || "—")}</b></div>
        <div class="stat"><span>Durée</span><b>${fmtDur(track.duration)}</b></div>
        <div class="stat"><span>Confiance</span><b>${fmtPct(track.confidence)}</b></div>
        <div class="stat"><span>Loudness source</span><b>${track.loudness_lufs ?? track.features?.loudness_input_lufs ?? "—"} LUFS</b></div>
        <div class="stat"><span>Hook</span><b>${fmtTime(track.hook_start)} (+${Math.round(track.hook_duration || 12)} s)</b></div>
      </div>
    </div>

    <div class="detail-section">
      <h3>Profil affectif estimé</h3>
      <div class="gauges">
        ${gauge("Valence", eff.valence, "mélancolique → solaire", "var(--accent-2)")}
        ${gauge("Arousal", eff.arousal, "calme → énergique", "var(--calm)")}
        ${gauge("Tension", eff.tension, "résolution → attente", "var(--tense)")}
      </div>
    </div>

    <div class="detail-section">
      <h3>Tonalité et chroma</h3>
      <div class="key-wrap">
        ${keyWheel(track)}
        <div class="key-info">
          <strong>${esc(track.key || "—")}</strong>
          <span>${esc(track.mode === "major" ? "mode majeur" : "mode mineur")} · ${Math.round(Number(track.bpm) || 0)} BPM</span>
          <span class="key-conf">confiance tonale ${fmtPct(track.key_confidence)}</span>
        </div>
      </div>
    </div>

    <div class="detail-section">
      <h3>Arc temporel</h3>
      <div class="arc">${arcBars(track)}</div>
      <div class="arc-meta"><span>intro ${fmtTime(track.intro_end)}</span><span>pic ${fmtTime(track.peak_time)}</span><span>sortie ${fmtTime(track.outro_start)}</span></div>
      <div class="arc-meta" style="margin-top:5px"><span>${esc(track.arc_type || "steady")}</span><span>loop ${fmtPct(track.loopability)}</span></div>
      <h3 style="margin-top:12px">Points de coupe</h3>
      ${cutMarkers}
    </div>

    <div class="detail-section">
      <h3>Tags estimés</h3>
      <div class="tag-score-list">
        ${topTags.map(([name, score]) => `<div class="tag-score" style="--tag:${tagMeta(name).color}"><span>${esc(name)}</span><span class="bar"><i style="width:${(clamp01(score) * 100).toFixed(1)}%"></i></span><b>${score.toFixed(2)}</b></div>`).join("")}
      </div>
    </div>

    <div class="detail-section">
      <h3>Usages cinéma</h3>
      <div class="usage-list">
        ${usages.map(([name, score]) => `<div class="usage-row"><span>${esc(name)}</span><span class="bar"><i style="width:${(clamp01(score) * 100).toFixed(1)}%"></i></span><b>${score.toFixed(2)}</b></div>`).join("")}
      </div>
    </div>

    <div class="detail-section">
      <h3>Pistes proches</h3>
      <div class="similar-list">
        ${similar.map(({ track: near, d }) => `<button class="similar" type="button" data-similar="${esc(near.id)}"><span>${esc(near.title)} · ${esc(near.artist)}</span><b>d ${d.toFixed(2)}</b></button>`).join("")}
      </div>
    </div>

    <div class="detail-section">
      <h3>Licence et crédit</h3>
      <div class="license-box">
        <strong>${esc(track.license)}</strong> · crédit : ${esc(track.credit)}<br>
        <a href="${esc(track.source_url)}" target="_blank" rel="noopener">Page source YouTube ${icon("external")}</a>
        ${track.license_url ? ` · <a href="${esc(track.license_url)}" target="_blank" rel="noopener">Texte de la licence</a>` : ""}
        <div class="license-note">Vérifier la licence et conserver ce crédit avant publication. Content ID peut revendiquer une piste même sous licence libre.</div>
      </div>
    </div>

    <div class="detail-section">
      <h3>Annotation manuelle</h3>
      <form class="annotation-form" id="annotationForm">
        ${annSlider("valence", "Valence", a.valence ?? eff.valence)}
        ${annSlider("arousal", "Arousal", a.arousal ?? eff.arousal)}
        ${annSlider("tension", "Tension", a.tension ?? eff.tension)}
        <div class="ann-tags">${annotationTagChips(track)}</div>
        <textarea id="annNote" placeholder="Note d’écoute, plan prévu, réserve…">${esc(a.note || "")}</textarea>
        <div class="annotation-actions">
          <button class="btn primary" type="submit">${icon("check")} Enregistrer</button>
          ${a.updated_at ? `<button class="link" type="button" data-action="clear-annotation">Effacer</button>` : ""}
        </div>
        <div class="annotation-hint">Les annotations sont locales, exportées dans la base. Elles remplacent les valeurs auto sur la carte.</div>
      </form>
    </div>
  </div>`;
}

function gauge(label, value, legend, color) {
  const v = Math.max(-1, Math.min(1, Number(value) || 0));
  const pct = ((v + 1) / 2) * 100;
  return `<div><div class="gauge-head"><span>${esc(label)} <span class="micro">${esc(legend)}</span></span><b>${fmtSigned(v)}</b></div><div class="gauge-track"><span class="gauge-fill" style="width:${pct.toFixed(1)}%;--gauge-color:${color}"></span><span class="gauge-mid"></span></div></div>`;
}

function annSlider(key, label, value) {
  const v = Math.max(-1, Math.min(1, Number(value) || 0));
  return `<label class="ann-slider"><span>${esc(label)}</span><input type="range" id="ann-${key}" min="-1" max="1" step="0.01" value="${v.toFixed(2)}"><output for="ann-${key}">${fmtSigned(v)}</output></label>`;
}

function renderPlayer() {
  const track = selectedTrack();
  const current = currentTrack();
  const shown = current || track;
  $("#playerTitle").textContent = shown ? shown.title : "Aucune piste sélectionnée";
  $("#playerArtist").textContent = shown ? `${shown.artist} · ${FAMILY_SHORT[shown.family] || shown.family}` : "Sélectionnez une piste pour commencer";
  const favorite = shown ? state.favorites.has(shown.id) : false;
  $("#favPlayerBtn").setAttribute("aria-pressed", favorite);
  $("#favPlayerBtn").style.color = favorite ? "var(--accent-2)" : "";
  $("#favPlayerBtn").querySelector(".icon").style.fill = favorite ? "currentColor" : "none";
  $("#playBtn").disabled = !shown;
  const playing = current && !audio.paused;
  $("#playBtn").innerHTML = icon(playing ? "pause" : "play");
  $("#loopBtn").setAttribute("aria-pressed", state.loop);
  $("#loopBtn").classList.toggle("active", state.loop);
  if (!current) {
    $("#timeCurrent").textContent = "0:00";
    $("#timeTotal").textContent = shown ? fmtDur(shown.duration) : "0:00";
    $("#seek").value = 0;
  }
}

function renderAll() {
  renderFilters();
  renderPresets();
  renderMap();
  renderList();
  renderDetail();
  renderPlayer();
}

function selectTrack(id, { play = false } = {}) {
  const track = state.tracks.find((t) => t.id === id);
  if (!track) return;
  state.selectedId = id;
  renderAll();
  if (play) {
    loadTrack(track, true);
  } else if (!state.currentId) {
    renderPlayer();
  }
}

function loadTrack(track, play = false) {
  if (!track) return;
  const same = state.currentId === track.id;
  if (!same) {
    state.currentId = track.id;
    state.pendingPlay = play;
    state.pendingSeek = Number(track.hook_start) || 0;
    state.previewStop = null;
    audio.src = track.audio_url;
    audio.load();
  } else {
    state.pendingPlay = play;
    if (play) {
      const start = Number(track.hook_start) || 0;
      if (audio.readyState >= 1) audio.currentTime = start;
      audio.play().catch(() => {});
    }
  }
  renderPlayer();
  updateNowPlayingTrack(track);
}

function updateNowPlayingTrack(track) {
  $("#playerTitle").textContent = track.title;
  $("#playerArtist").textContent = `${track.artist} · ${FAMILY_SHORT[track.family] || track.family}`;
  $("#timeTotal").textContent = fmtDur(track.duration);
  const favorite = state.favorites.has(track.id);
  $("#favPlayerBtn").setAttribute("aria-pressed", favorite);
  $("#favPlayerBtn").querySelector(".icon").style.fill = favorite ? "currentColor" : "none";
  $("#playBtn").disabled = false;
}

function togglePlay() {
  const track = currentTrack() || selectedTrack();
  if (!track) return;
  if (state.currentId !== track.id) {
    loadTrack(track, true);
    return;
  }
  if (audio.paused) {
    if (!audio.currentTime) audio.currentTime = Number(track.hook_start) || 0;
    audio.play().catch(() => {});
  } else {
    audio.pause();
  }
}

function toggleFavorite(id) {
  if (!id) return;
  if (state.favorites.has(id)) state.favorites.delete(id);
  else state.favorites.add(id);
  localStorage.setItem("atlas:favorites", JSON.stringify([...state.favorites]));
  renderMap();
  renderList();
  renderDetail();
  renderPlayer();
}

function hookEnd(track) {
  return (Number(track.hook_start) || 0) + (Number(track.hook_duration) || 12);
}

function updateTimeline() {
  const duration = Number(audio.duration) || 0;
  const current = Number(audio.currentTime) || 0;
  $("#timeCurrent").textContent = fmtTime(current);
  $("#timeTotal").textContent = fmtTime(duration);
  $("#seek").value = duration ? Math.round((current / duration) * 1000) : 0;
  const track = currentTrack();
  if (state.loop && track && duration) {
    const end = hookEnd(track);
    if (current >= end - 0.05) {
      audio.currentTime = Number(track.hook_start) || 0;
    }
  }
  if (state.previewStop && current >= state.previewStop) {
    audio.pause();
    state.previewStop = null;
  }
}

function showToast(message, kind = "") {
  const toast = $("#toast");
  toast.textContent = message;
  toast.className = `toast${kind ? ` ${kind}` : ""}`;
  toast.hidden = false;
  clearTimeout(showToast.timer);
  showToast.timer = setTimeout(() => {
    toast.hidden = true;
  }, 3200);
}

function openModal(title, html) {
  $("#modalTitle").textContent = title;
  $("#modalBody").innerHTML = html;
  $("#modal").hidden = false;
  document.body.style.overflow = "hidden";
}

function closeModal() {
  $("#modal").hidden = true;
  document.body.style.overflow = "";
}

function methodologyHtml() {
  return `<h3>Ce que fait l’application</h3>
    <p>Elle estime un <strong>profil affectif perçu</strong> pour chaque piste : valence (mélancolique → solaire), arousal (calme → énergique) et tension (résolution → attente). Ce n’est pas un détecteur d’émotions et encore moins un outil clinique.</p>
    <h3>Lecture de la carte</h3>
    <p>L’axe horizontal représente l’arousal, l’axe vertical la valence. La couleur encode la tension, la taille du point la confiance. Les ellipses indiquent l’incertitude : plus elles sont larges, plus le score doit être vérifié à l’écoute.</p>
    <h3>Scores</h3>
    <span class="formula">A = tanh(0.95 × (0.24·tempo + 0.16·onsets + 0.13·flux + 0.12·centroïde + 0.10·percussif + 0.08·crest + 0.06·dynamique + 0.05·basses + 0.04·pulse + 0.30·prior de famille))</span>
    <span class="formula">V = tanh(0.90 × (0.28·mode×confiance + 0.14·harmonie − 0.14·rugosité + 0.10·pulse + 0.08·stabilité − 0.06·flatness + 0.24·prior de famille))</span>
    <span class="formula">T = tanh(0.85 × (0.30·rugosité + 0.20·entropie harmonique + 0.18·hors-tonalité + 0.12·flux − 0.10·pulse + 0.10·flatness + 0.04·centroïde + 0.20·prior de famille))</span>
    <p>Les features sont standardisées robustement (médiane/MAD) sur les 20 pistes. Les scores sont donc relatifs à ce corpus. Les poids sont fixés a priori, pas appris sur 20 exemples.</p>
    <h3>Analyse acoustique</h3>
    <ul>
      <li>WAV 48 kHz normalisé à −16 LUFS avant analyse, pour limiter les biais de codec et de mastering.</li>
      <li>Tempo, onsets, clarté de pulse, RMS, dynamique, crest, centroïde, bande passante, rolloff, flatness, contraste, flux, ZCR.</li>
      <li>MFCC, chroma, tonnetz, détection de tonalité par profils de Krumhansl + marge de confiance.</li>
      <li>Rugosité Plomp-Levelt/Sethares sur les pics spectraux, ratio harmonique/percussif, largeur stéréo.</li>
      <li>Arc temporel en 12 segments, hook de 12 s, points de coupe sur les temps, loopabilité.</li>
    </ul>
    <h3>Confiance et limites</h3>
    <ul>
      <li>La valence est moins fiable que l’arousal, surtout sur les drones, le didgeridoo et les textures non tempérées.</li>
      <li>Le mode majeur/mineur n’est utilisé qu’avec une marge de confiance ; une piste atonale est signalée.</li>
      <li>Les tags sont multi-étiquettes et doivent être validés par écoute. Les annotations manuelles remplacent les valeurs automatiques sur la carte.</li>
      <li>Les différences culturelles et individuelles de perception ne sont pas modélisées.</li>
    </ul>
    <h3>Références principales</h3>
    <ul>
      <li>Russell, J. A. (1980). A circumplex model of affect.</li>
      <li>Krumhansl, C. L. (1982). Key-finding profiles.</li>
      <li>Plomp, R. &amp; Levelt, W. J. M. (1965). Tonal consonance and critical bandwidth.</li>
      <li>Sethares, W. A. (1993). Local consonance and the relationship between timbre and scale.</li>
      <li>Eerola, T. &amp; Vuoskoski, J. K. (2011). A comparison of the discrete and dimensional models of emotion in music.</li>
      <li>Zentner, M., Grandjean, D. &amp; Scherer, K. R. (2008). Emotions evoked by the sound of music (GEMS).</li>
      <li>Huron, D. (2006). Sweet Anticipation.</li>
    </ul>
    <p class="micro">Le détail des features et des décisions est dans <code>METHODOLOGY.md</code>. Les crédits complets sont dans <code>CREDITS.md</code>.</p>`;
}

function creditsHtml() {
  return `<h3>Crédits et licences</h3>
    <p>Conserver ces crédits avec les MP3. Vérifier chaque licence avant publication monétisée : Content ID peut revendiquer une piste même sous licence libre.</p>
    <div class="credit-list">${state.tracks
      .map(
        (t) => `<div class="credit-item"><strong>${esc(t.title)} — ${esc(t.artist)}</strong><span>${esc(t.license)} · crédit : ${esc(t.credit)}</span><span><a href="${esc(t.source_url)}" target="_blank" rel="noopener">Source YouTube</a>${t.license_url ? ` · <a href="${esc(t.license_url)}" target="_blank" rel="noopener">Licence</a>` : ""}</span></div>`
      )
      .join("")}</div>`;
}

async function exportBase(format) {
  $("#exportMenu").hidden = true;
  $("#exportBtn").setAttribute("aria-expanded", "false");
  const specs = {
    sqlite: { name: "atlas-musical.sqlite", mime: "application/octet-stream", desc: "Base SQLite" },
    json: { name: "atlas-musical.json", mime: "application/json", desc: "Snapshot JSON" },
    zip: { name: "atlas-musical.zip", mime: "application/zip", desc: "Archive complète" },
  };
  const spec = specs[format];
  if (!spec) return;
  showToast(`Préparation de ${spec.desc.toLowerCase()}…`);
  try {
    if ("showSaveFilePicker" in window) {
      const handle = await window.showSaveFilePicker({
        suggestedName: spec.name,
        types: [{ description: spec.desc, accept: { [spec.mime]: [`.${spec.name.split(".").pop()}`] } }],
      });
      const response = await fetch(`/api/export?format=${format}`);
      if (!response.ok) throw new Error(`Export impossible (${response.status})`);
      const writable = await handle.createWritable();
      await writable.write(await response.blob());
      await writable.close();
      showToast("Base enregistrée.");
      return;
    }
    const link = document.createElement("a");
    link.href = `/api/export?format=${format}`;
    link.download = spec.name;
    document.body.appendChild(link);
    link.click();
    link.remove();
    showToast("Téléchargement lancé.");
  } catch (error) {
    if (error && error.name === "AbortError") {
      showToast("Enregistrement annulé.");
      return;
    }
    showToast(error.message || "Export impossible.", "error");
  }
}

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
  $("#themeBadge").textContent = `thème ${theme.theme || "local"}`;
  const meta = document.querySelector('meta[name="theme-color"]');
  if (meta && theme.background) meta.setAttribute("content", theme.background);
}

function bindEvents() {
  $("#searchInput").addEventListener("input", (event) => {
    state.filters.q = event.target.value.trim().toLowerCase();
    renderFilters();
    renderMap();
    renderList();
  });

  $("#familyFilters").addEventListener("click", (event) => {
    const button = event.target.closest("[data-family]");
    if (!button) return;
    const family = button.dataset.family;
    if (state.filters.families.has(family)) state.filters.families.delete(family);
    else state.filters.families.add(family);
    renderFilters();
    renderMap();
    renderList();
  });

  $("#tagFilters").addEventListener("click", (event) => {
    const button = event.target.closest("[data-tag]");
    if (!button) return;
    const tag = button.dataset.tag;
    if (state.filters.tags.has(tag)) state.filters.tags.delete(tag);
    else state.filters.tags.add(tag);
    renderFilters();
    renderMap();
    renderList();
  });

  $("#presets").addEventListener("click", (event) => {
    const button = event.target.closest("[data-preset]");
    if (!button) return;
    state.preset = button.dataset.preset;
    state.sort = "relevance";
    $("#sortSelect").value = "relevance";
    renderPresets();
    renderFilters();
    renderMap();
    renderList();
  });

  $("#sortSelect").addEventListener("change", (event) => {
    state.sort = event.target.value;
    renderList();
  });

  const numberFilter = (id, key) => {
    $(`#${id}`).addEventListener("input", (event) => {
      const value = Number(event.target.value);
      state.filters[key] = Number.isFinite(value) ? value : state.filters[key];
      renderFilters();
      renderMap();
      renderList();
    });
  };
  numberFilter("bpmMin", "bpmMin");
  numberFilter("bpmMax", "bpmMax");
  numberFilter("durMin", "durMin");
  numberFilter("durMax", "durMax");

  $("#confMin").addEventListener("input", (event) => {
    state.filters.confMin = Number(event.target.value);
    renderFilters();
    renderMap();
    renderList();
  });

  $("#favoritesOnly").addEventListener("change", (event) => {
    state.filters.favoritesOnly = event.target.checked;
    renderFilters();
    renderMap();
    renderList();
  });

  $("#resetFilters").addEventListener("click", () => {
    state.filters = { q: "", families: new Set(), tags: new Set(), bpmMin: 0, bpmMax: 240, durMin: 0, durMax: 20, confMin: 0, favoritesOnly: false };
    state.preset = "Tout";
    state.sort = "relevance";
    $("#searchInput").value = "";
    $("#sortSelect").value = "relevance";
    renderPresets();
    renderAll();
  });

  $("#trackList").addEventListener("click", (event) => {
    const play = event.target.closest("[data-play]");
    if (play) {
      event.stopPropagation();
      selectTrack(play.dataset.play, { play: true });
      return;
    }
    const fav = event.target.closest("[data-fav]");
    if (fav) {
      event.stopPropagation();
      toggleFavorite(fav.dataset.fav);
      return;
    }
    const row = event.target.closest("[data-id]");
    if (row) selectTrack(row.dataset.id, { play: true });
  });

  $("#trackList").addEventListener("keydown", (event) => {
    if (event.key !== "Enter" && event.key !== " ") return;
    const row = event.target.closest(".track-row");
    if (!row) return;
    event.preventDefault();
    selectTrack(row.dataset.id, { play: true });
  });

  $("#detailContent").addEventListener("click", (event) => {
    const action = event.target.closest("[data-action]");
    if (action) {
      const track = selectedTrack();
      if (!track) return;
      if (action.dataset.action === "play-hook") {
        loadTrack(track, true);
        const start = Number(track.hook_start) || 0;
        state.pendingSeek = start;
        if (audio.readyState >= 1) audio.currentTime = start;
      }
      if (action.dataset.action === "fav") toggleFavorite(track.id);
      if (action.dataset.action === "clear-annotation") clearAnnotation(track);
      return;
    }
    const cut = event.target.closest("[data-time]");
    if (cut) {
      const track = selectedTrack();
      if (!track) return;
      if (state.currentId !== track.id) loadTrack(track, false);
      state.pendingSeek = Number(cut.dataset.time);
      if (audio.readyState >= 1) audio.currentTime = Number(cut.dataset.time);
      audio.play().catch(() => {});
      return;
    }
    const similar = event.target.closest("[data-similar]");
    if (similar) selectTrack(similar.dataset.similar, { play: true });
    const annTag = event.target.closest("[data-ann-tag]");
    if (annTag) {
      annTag.classList.toggle("active");
      annTag.setAttribute("aria-pressed", annTag.classList.contains("active"));
    }
  });

  $("#detailContent").addEventListener("input", (event) => {
    if (event.target.matches(".ann-slider input")) {
      const output = event.target.parentElement.querySelector("output");
      if (output) output.textContent = fmtSigned(event.target.value);
    }
  });

  $("#detailContent").addEventListener("submit", (event) => {
    event.preventDefault();
    if (event.target.id === "annotationForm") saveAnnotation(event.target);
  });

  $("#playBtn").addEventListener("click", togglePlay);
  $("#favPlayerBtn").addEventListener("click", () => toggleFavorite(state.currentId || state.selectedId));
  $("#loopBtn").addEventListener("click", () => {
    state.loop = !state.loop;
    const track = currentTrack() || selectedTrack();
    if (state.loop && track) {
      const start = Number(track.hook_start) || 0;
      if (audio.readyState >= 1 && (audio.currentTime < start || audio.currentTime > hookEnd(track))) {
        audio.currentTime = start;
      }
    }
    renderPlayer();
  });

  $("#seek").addEventListener("input", (event) => {
    const duration = Number(audio.duration) || 0;
    if (!duration) return;
    audio.currentTime = (Number(event.target.value) / 1000) * duration;
  });

  $("#volume").addEventListener("input", (event) => {
    audio.volume = Number(event.target.value) / 100;
    localStorage.setItem("atlas:volume", String(audio.volume));
  });

  audio.addEventListener("loadedmetadata", () => {
    const track = currentTrack();
    if (track) {
      $("#timeTotal").textContent = fmtTime(audio.duration);
      if (state.pendingSeek !== null) {
        audio.currentTime = Math.min(state.pendingSeek, Math.max(0, audio.duration - 0.1));
        state.pendingSeek = null;
      }
    }
    if (state.pendingPlay) {
      state.pendingPlay = false;
      audio.play().catch(() => {});
    }
    renderPlayer();
  });
  audio.addEventListener("timeupdate", updateTimeline);
  audio.addEventListener("play", renderPlayer);
  audio.addEventListener("pause", renderPlayer);
  audio.addEventListener("ended", () => {
    state.loop = false;
    renderPlayer();
  });
  audio.addEventListener("error", () => showToast("Lecture audio impossible.", "error"));

  $("#exportBtn").addEventListener("click", (event) => {
    event.stopPropagation();
    const menu = $("#exportMenu");
    menu.hidden = !menu.hidden;
    $("#exportBtn").setAttribute("aria-expanded", String(!menu.hidden));
  });
  $("#exportMenu").addEventListener("click", (event) => {
    const button = event.target.closest("[data-format]");
    if (button) exportBase(button.dataset.format);
  });
  document.addEventListener("click", () => {
    $("#exportMenu").hidden = true;
    $("#exportBtn").setAttribute("aria-expanded", "false");
  });

  $("#methodologyBtn").addEventListener("click", () => openModal("Méthodologie", methodologyHtml()));
  $("#creditsBtn").addEventListener("click", () => openModal("Crédits", creditsHtml()));
  $("#modal").addEventListener("click", (event) => {
    if (event.target.closest("[data-close-modal]")) closeModal();
  });

  mapWrap.addEventListener("mousemove", (event) => {
    const rect = svg.getBoundingClientRect();
    const x = ((event.clientX - rect.left) / rect.width) * MAP.width;
    const y = ((event.clientY - rect.top) / rect.height) * MAP.height;
    if (x < MAP.pad || x > MAP.width - MAP.pad || y < MAP.pad || y > MAP.height - MAP.pad) {
      $("#mapCrosshair").hidden = true;
      return;
    }
    $("#mapCrosshair").hidden = false;
    $("#crossX").setAttribute("x1", x);
    $("#crossX").setAttribute("x2", x);
    $("#crossY").setAttribute("y1", y);
    $("#crossY").setAttribute("y2", y);
    let nearest = null;
    let best = Infinity;
    for (const pos of state.mapPositions.values()) {
      const d = Math.hypot(pos.x - x, pos.y - y);
      if (d < best) {
        best = d;
        nearest = pos.track;
      }
    }
    const px = Math.round(((x - MAP.pad) / (MAP.width - MAP.pad * 2)) * 100);
    const py = Math.round(((MAP.height - MAP.pad - y) / (MAP.height - MAP.pad * 2)) * 100);
    $("#mapReadout").textContent = nearest
      ? `curseur ${px}% · ${py}% — plus proche : ${nearest.title} (${Math.round(best)} px)`
      : `curseur ${px}% · ${py}%`;
  });
  mapWrap.addEventListener("mouseleave", () => {
    $("#mapCrosshair").hidden = true;
    $("#mapReadout").textContent = "Survolez la carte pour lire une position.";
  });

  document.addEventListener("keydown", (event) => {
    const tag = (event.target.tagName || "").toLowerCase();
    const typing = tag === "input" || tag === "textarea" || tag === "select";
    if (event.key === "/" && !typing) {
      event.preventDefault();
      $("#searchInput").focus();
    } else if (event.key === "Escape") {
      closeModal();
      $("#exportMenu").hidden = true;
      hideTooltip();
      $("#searchInput").blur();
    } else if (event.code === "Space" && !typing) {
      event.preventDefault();
      togglePlay();
    } else if (!typing && event.key.toLowerCase() === "f") {
      toggleFavorite(state.currentId || state.selectedId);
    } else if (!typing && event.key.toLowerCase() === "l") {
      $("#loopBtn").click();
    }
  });
}

async function saveAnnotation(form) {
  const track = selectedTrack();
  if (!track) return;
  const tags = $$(".ann-tags .chip.active", form).map((node) => node.dataset.annTag);
  const payload = {
    track_id: track.id,
    valence: Number($("#ann-valence", form).value),
    arousal: Number($("#ann-arousal", form).value),
    tension: Number($("#ann-tension", form).value),
    tags,
    note: $("#annNote", form).value.trim(),
  };
  try {
    const response = await fetch("/api/annotations", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!response.ok) throw new Error(`Enregistrement impossible (${response.status})`);
    const data = await response.json();
    track.annotation = {
      valence: payload.valence,
      arousal: payload.arousal,
      tension: payload.tension,
      tags: payload.tags,
      note: payload.note,
      updated_at: data.updated_at,
    };
    renderAll();
    showToast("Annotation enregistrée.");
  } catch (error) {
    showToast(error.message || "Annotation impossible.", "error");
  }
}

async function clearAnnotation(track) {
  try {
    const response = await fetch(`/api/annotations/${encodeURIComponent(track.id)}`, { method: "DELETE" });
    if (!response.ok) throw new Error("Suppression impossible");
    track.annotation = null;
    renderAll();
    showToast("Annotation effacée.");
  } catch (error) {
    showToast(error.message || "Suppression impossible.", "error");
  }
}

function loadFavorites() {
  try {
    const raw = JSON.parse(localStorage.getItem("atlas:favorites") || "[]");
    state.favorites = new Set(Array.isArray(raw) ? raw : []);
  } catch {
    state.favorites = new Set();
  }
  const volume = Number(localStorage.getItem("atlas:volume") || 0.8);
  audio.volume = Math.max(0, Math.min(1, volume));
  $("#volume").value = Math.round(audio.volume * 100);
}

async function init() {
  loadFavorites();
  buildMapBase();
  bindEvents();
  try {
    const [libResponse, themeResponse] = await Promise.all([fetch("/api/library"), fetch("/api/theme")]);
    if (!libResponse.ok) throw new Error("Bibliothèque indisponible. Lancer analysis/analyze.py.");
    state.library = await libResponse.json();
    state.tracks = state.library.tracks || [];
    state.tags = state.library.tags || [];
    state.families = Array.from(new Set(state.tracks.map((t) => t.family))).sort();
    if (themeResponse.ok) applyTheme(await themeResponse.json());
    $("#subtitle").textContent = `${state.tracks.length} pistes · ${state.tags.length} tags · modèle ${state.library.meta.model_version}`;
    if (state.tracks.length) state.selectedId = state.tracks[0].id;
    renderAll();
  } catch (error) {
    $("#subtitle").textContent = "Erreur de chargement";
    $("#trackList").innerHTML = `<div class="track-empty">${esc(error.message || "Bibliothèque indisponible.")}</div>`;
    showToast(error.message || "Bibliothèque indisponible.", "error");
  }
}

init();
