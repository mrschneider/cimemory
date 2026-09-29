/* ============================================================
   THE GEMBA BOARD — replay engine + shift chrome
   ============================================================ */
const App = {
  meta: null,
  frames: [],
  frame: 0,
  playing: false,
  speed: 1,
  tickMs: 620,
  lastTs: 0,
  view: "andon",
  state: { pick: null },
};

function ctxOf() {
  return { meta: App.meta, frames: App.frames, i: App.frame, state: App.state,
           render: () => render() };
}

/* ------------------------------- boot ------------------------------- */

async function boot(source) {
  const q = source ? "?source=" + encodeURIComponent(source) : "";
  const r = await fetch("/api/data" + q);
  const data = await r.json();
  App.meta = data.meta;
  App.frames = data.frames;
  App.state.pick = App.frames[0].cap || Object.keys(App.meta.stations)[0];
  renderSource();
  buildNav();
  buildZones();
  wireTransport();
  setView("andon");
  // A live capture is a single observation, so open on the settled board and
  // let the scrubber walk back through how it was reached. The demo is a
  // programme and opens at its first frame.
  go(App.source === "live" ? App.frames.length - 1 : 0, true);
  requestAnimationFrame(tick);
}

/* Which memory is this board looking at — and can it write to it? */
function renderSource() {
  const chip = $("#src-chip"), m = App.meta;
  const served = m.served_source || "demo";
  const live = served === "live";
  App.source = served;
  chip.classList.toggle("live", live && !m.source_note);
  chip.classList.toggle("fallback", !live || !!m.source_note);
  $("#src-name").textContent = live ? "live · read-only" : "demo programme";
  const f = m.fleet || {};
  $("#src-detail").textContent = live
    ? `${f.tool_calls || 0} calls · ${f.defects || 0} defects · ${f.open_andons || 0} andons`
    : (m.source_note || "scripted seven-cycle programme");
  chip.title = (m.source || "") + (m.source_note ? "\n" + m.source_note : "");
  chip.onclick = function () { boot(live ? "demo" : "live"); };
  document.title = live
    ? "cimemory · live " + (f.defect_rate != null ? f.defect_rate + " per 100" : "") + " · Gemba Board"
    : "cimemory · demo · Gemba Board";
}

function buildNav() {
  const nav = $("#nav");
  clear(nav);
  nav.appendChild(el("div", "nav-k", "the shop floor"));
  window.GEMBA_VIEWS.forEach((v, i) => {
    const item = el("div", "nav-item" + (v.id === App.view ? " on" : ""));
    item.dataset.view = v.id;
    item.appendChild(el("span", "idx", String(i + 1)));
    item.appendChild(el("span", "lbl", v.label));
    item.onclick = () => setView(v.id);
    nav.appendChild(item);
  });
  const foot = el("div", "nav-foot");
  const src = App.source === "live" ? "live memory (ro)" : "demo";
  foot.innerHTML = `agent <b>${esc(App.meta.agent)}</b><br>` +
    `${App.meta.n_frames} frames · <b>${src}</b><br>` +
    `${esc(App.meta.window_label || (App.meta.n_cycles + " cycles"))}<br>` +
    `1–7 switch · space plays`;
  nav.appendChild(foot);
}

function setView(id) {
  App.view = id;
  $$(".nav-item").forEach((n) => n.classList.toggle("on", n.dataset.view === id));
  $$(".view").forEach((v) => v.classList.toggle("on", v.id === "view-" + id));
  render();
}

/* ------------------------------ transport ------------------------------ */

function go(i, force) {
  App.frame = Math.max(0, Math.min(App.frames.length - 1, i));
  render();
}

function render() {
  const f = App.frames[App.frame];
  if (!f) return;
  setClock();
  readouts(f);
  renderZonesCursor();
  const v = window.GEMBA_VIEWS.find((x) => x.id === App.view);
  if (v) v.render(f, ctxOf());
  ticker(f);
}

function setClock() {
  const f = App.frames[App.frame];
  const d = new Date(f.sim_ts * 1000);
  const p = (n) => String(n).padStart(2, "0");
  const phase = f.kind === "step" || f.kind === "why" ? f.title
    : f.kind === "check" ? "checking"
    : f.kind === "standard" ? "standardising"
    : f.kind === "andon" ? "andon"
    : f.kind === "refusal" ? "discipline holds"
    : f.kind === "kaikaku" ? "kaikaku gate"
    : f.kind;
  $("#clock").innerHTML =
    `<b>C${String(f.cycle).padStart(2, "0")}</b> · f${String(App.frame).padStart(3, "0")}/${App.frames.length - 1}` +
    ` · <span class="phase">${esc(phase)}</span><br>` +
    `${p(d.getUTCDate())}/${p(d.getUTCMonth() + 1)} ${p(d.getUTCHours())}:${p(d.getUTCMinutes())} · sim clock`;
}

function readouts(f) {
  const board = Object.values(f.board);
  const ok = board.filter((s) => s.status === "normal").length;
  const stds = (f.store.standards || []).filter((s) => s.active).length;
  const andons = (f.store.andons || []).filter((a) => !a.resolved).length;
  const kaizen = history(App.frames, App.frame, "standard").length;
  const by = {};
  (f.store.countermeasures || []).forEach((c) => { by[c.strength] = (by[c.strength] || 0) + 1; });
  const BEST_LABEL = { taisho: "contain", taisaku: "fix cause", mizen_boushi: "prevent" };
  const best = by.mizen_boushi ? "mizen_boushi" : by.taisaku ? "taisaku" : by.taisho ? "taisho" : null;

  $("#ro-ok").innerHTML = `${ok}<small>/${board.length}</small>`;
  $("#ro-std").textContent = stds;
  $("#ro-andon").innerHTML = andons
    ? `<span style="color:var(--red)">${andons}</span>` : "0";
  if (App.meta.loop_ran === false) {
    $("#ro-cyc").innerHTML = `–<small>not run</small>`;
  } else {
    $("#ro-cyc").textContent = f.cycle;
  }
  $("#ro-kaizen").innerHTML = kaizen + `<small> std'd</small>`;
  $("#ro-cm").innerHTML = best
    ? `<span style="color:${STRENGTH_COLOR[best]}">${BEST_LABEL[best]}</span>`
    : "–";

  /* master lamp */
  const stopped = board.some((s) => s.status === "stopped");
  const ab = board.some((s) => s.status === "abnormal");
  const lamp = $("#master-lamp");
  const openCritical = (f.store.andons || []).some((a) => !a.resolved && a.severity === "critical");
  let cls = "idle", lab = "OBSERVING";
  if (stopped || openCritical) { cls = "stopped"; lab = "LINE STOPPED"; }
  else if (ab) { cls = "abnormal"; lab = "ABNORMAL"; }
  else if (stds) { cls = "normal"; lab = "IN CONTROL"; }
  lamp.className = "lamp lg " + cls;
  $("#master-label").textContent = lab;
}

function ticker(f) {
  $("#ticker").innerHTML = `<b>${esc(f.title)}</b> — ${esc((f.text || "").slice(0, 130))}`;
}

/* ------------------------------ scrubber ------------------------------ */

function buildZones() {
  const z = $("#scrub-zones");
  clear(z);
  const byCycle = {};
  App.frames.forEach((f) => {
    (byCycle[f.cycle] = byCycle[f.cycle] || []).push(f);
  });
  Object.keys(byCycle).forEach((c) => {
    const fr = byCycle[c];
    const zone = el("div", "scrub-zone");
    zone.style.flex = String(fr.length);
    if (fr.some((x) => x.kind === "andon" || x.kind === "check" && x.extra && !x.extra.results_met))
      zone.classList.add("andon");
    if (fr.some((x) => x.kind === "kaikaku")) zone.classList.add("kaikaku");
    zone.title = "cycle " + c;
    z.appendChild(zone);
  });
}

function renderZonesCursor() {
  const cur = $("#scrub-cursor");
  const frac = App.frame / Math.max(1, App.frames.length - 1);
  cur.style.left = (frac * 100) + "%";
}

function wireTransport() {
  $("#btn-play").onclick = () => { App.playing ? pause() : play(); };
  $("#btn-step").onclick = () => { pause(); go(App.frame + 1); };
  $("#btn-restart").onclick = () => { pause(); go(0); };
  $("#btn-end").onclick = () => { pause(); go(App.frames.length - 1); };
  $("#spd").oninput = (e) => {
    App.speed = [0.5, 1, 2, 4, 8][Number(e.target.value)];
    $("#spd-val").textContent = App.speed + "×";
  };
  const scrub = $("#scrub");
  let dragging = false;
  const to = (e) => {
    const r = scrub.getBoundingClientRect();
    const frac = Math.max(0, Math.min(1, (e.clientX - r.left) / r.width));
    go(Math.round(frac * (App.frames.length - 1)));
  };
  scrub.addEventListener("mousedown", (e) => { dragging = true; pause(); to(e); });
  window.addEventListener("mousemove", (e) => dragging && to(e));
  window.addEventListener("mouseup", () => { dragging = false; });
  window.addEventListener("keydown", (e) => {
    if (e.target.tagName === "INPUT") return;
    if (e.code === "Space") { e.preventDefault(); App.playing ? pause() : play(); }
    else if (e.code === "ArrowRight") { pause(); go(App.frame + 1); }
    else if (e.code === "ArrowLeft") { pause(); go(App.frame - 1); }
    else if (e.code === "Home") { pause(); go(0); }
    else if (e.code === "End") { pause(); go(App.frames.length - 1); }
    else {
      const i = "1234567".indexOf(e.key);
      if (i >= 0 && window.GEMBA_VIEWS[i]) setView(window.GEMBA_VIEWS[i].id);
    }
  });
}

function play() {
  if (App.playing) return;
  if (App.frame >= App.frames.length - 1) go(0);
  App.playing = true;
  $("#btn-play").innerHTML = "❚❚&nbsp;&nbsp;pause";
}
function pause() {
  App.playing = false;
  $("#btn-play").innerHTML = "▶&nbsp;&nbsp;play";
}

function tick(ts) {
  requestAnimationFrame(tick);
  const dt = ts - App.lastTs;
  App.lastTs = ts;
  if (!App.playing) return;
  if (dt >= App.tickMs / App.speed) {
    App.lastTs = ts;
    if (App.frame >= App.frames.length - 1) { pause(); return; }
    go(App.frame + 1);
  }
}

boot();
