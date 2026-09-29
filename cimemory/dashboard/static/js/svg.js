/* ============================================================
   shared helpers — DOM, SVG, formatting
   ============================================================ */
const NS = "http://www.w3.org/2000/svg";

const $ = (s, r) => (r || document).querySelector(s);
const $$ = (s, r) => [...(r || document).querySelectorAll(s)];

function el(tag, cls, html) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (html != null) n.innerHTML = html;
  return n;
}

function sv(tag, attrs, parent) {
  const n = document.createElementNS(NS, tag);
  for (const k in attrs || {}) n.setAttribute(k, attrs[k]);
  if (parent) parent.appendChild(n);
  return n;
}

function esc(s) {
  return String(s == null ? "" : s).replace(/[&<>"]/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
}

function clear(node) { while (node.firstChild) node.removeChild(node.firstChild); }

/* number formatting that respects magnitude */
function num(v, d) {
  if (v == null || isNaN(v)) return "–";
  const a = Math.abs(v);
  if (d != null) return v.toFixed(d);
  if (a >= 100) return v.toFixed(0);
  if (a >= 10) return v.toFixed(1);
  return v.toFixed(2);
}

function mapRange(v, v0, v1, r0, r1) {
  if (v1 === v0) return r0;
  const t = (v - v0) / (v1 - v0);
  return r0 + Math.max(0, Math.min(1, t)) * (r1 - r0);
}

/* PDCA + strength vocabularies, shared by every view */
const PHASE_COLOR = { Plan: "#4aa3ff", Do: "#ffb020", Check: "#2fd07f", Act: "#a98bff" };
const STRENGTH_COLOR = { taisho: "#8d999e", taisaku: "#ffb020", mizen_boushi: "#2fd07f" };
const STRENGTH_LABEL = { taisho: "taisho · contain", taisaku: "taisaku · fix the cause", mizen_boushi: "mizen-boushi · design it out" };
const STRENGTH_DISPLAY = { taisho: "taisho", taisaku: "taisaku", mizen_boushi: "mizen-boushi" };
const STRENGTH_ORDER = ["taisho", "taisaku", "mizen_boushi"];
const STATUS_COLOR = { normal: "#2fd07f", abnormal: "#ffb020", stopped: "#ff3b30" };

function phaseOf(step, meta) {
  return (meta && meta.pdca && meta.pdca[step]) || "Act";
}

/* frames of the current cycle up to index i — used to light the wheel */
function cycleSteps(frames, i) {
  const c = frames[i].cycle;
  const done = new Set();
  for (let k = i; k >= 0; k--) {
    if (frames[k].cycle !== c) break;
    if (frames[k].step) done.add(frames[k].step);
  }
  return done;
}

/* every frame up to and including i, of a given kind */
function history(frames, i, kind) {
  const out = [];
  for (let k = 0; k <= i; k++) if (frames[k].kind === kind) out.push(frames[k]);
  return out;
}
