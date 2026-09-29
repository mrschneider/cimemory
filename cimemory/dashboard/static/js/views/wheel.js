/* ============================================================
   2 · THE WHEEL — PDCA / Toyota Business Practices, eight steps
   ============================================================ */
(function () {
  const STEP_LABEL = {
    "1-clarify": "Clarify the problem",
    "2-breakdown": "Break it down",
    "3-target": "Set a target",
    "4-root-cause": "Root cause",
    "5-countermeasures": "Countermeasures",
    "6-do": "Do",
    "7-check": "Check",
    "8-hansei": "Hansei",
    "8-standardise": "Standardise",
    "8-yokoten": "Yokoten",
  };

  function polar(cx, cy, r, a) {
    return [cx + r * Math.cos(a), cy + r * Math.sin(a)];
  }
  function arcPath(cx, cy, r0, r1, a0, a1) {
    const [x0, y0] = polar(cx, cy, r1, a0), [x1, y1] = polar(cx, cy, r1, a1);
    const [x2, y2] = polar(cx, cy, r0, a1), [x3, y3] = polar(cx, cy, r0, a0);
    const large = a1 - a0 > Math.PI ? 1 : 0;
    return `M${x0},${y0} A${r1},${r1} 0 ${large} 1 ${x1},${y1} ` +
           `L${x2},${y2} A${r0},${r0} 0 ${large} 0 ${x3},${y3} Z`;
  }

  window.GEMBA_VIEWS = window.GEMBA_VIEWS || [];
  window.GEMBA_VIEWS.push({
    id: "wheel",
    label: "The Wheel",
    render(f, ctx) {
      const host = $("#wheel-svg");
      clear(host);
      const W = 760, H = 516, cx = 380, cy = 256;
      const R0 = 92, R1 = 158, RN = 124, RL = 194;
      const s = sv("svg", { viewBox: `0 0 ${W} ${H}`, preserveAspectRatio: "xMidYMid meet" }, host);
      const defs = sv("defs", {}, s);
      const filt = sv("filter", { id: "glow", x: "-50%", y: "-50%", width: "200%", height: "200%" }, defs);
      sv("feGaussianBlur", { stdDeviation: "4.5", result: "b" }, filt);
      const mm = sv("feMerge", {}, filt);
      sv("feMergeNode", { in: "b" }, mm);
      sv("feMergeNode", { in: "SourceGraphic" }, mm);

      const steps = ctx.meta.steps;
      const n = steps.length;
      const done = cycleSteps(ctx.frames, ctx.i);
      const cur = f.step;
      const gap = 0.06;

      steps.forEach((st, k) => {
        const a0 = -Math.PI / 2 + (k / n) * Math.PI * 2 + gap / 2;
        const a1 = -Math.PI / 2 + ((k + 1) / n) * Math.PI * 2 - gap / 2;
        const ph = phaseOf(st, ctx.meta);
        const lit = cur === st;
        const used = done.has(st);

        s.appendChild(sv("path", {
          d: arcPath(cx, cy, R0, R1, a0, a1),
          fill: PHASE_COLOR[ph],
          opacity: lit ? 0.40 : used ? 0.20 : 0.075,
          stroke: PHASE_COLOR[ph],
          "stroke-width": 1,
          "stroke-opacity": lit ? 1 : used ? 0.55 : 0.3,
        }));
        if (lit) {
          s.appendChild(sv("path", {
            d: arcPath(cx, cy, R0, R1, a0, a1),
            fill: "none", stroke: PHASE_COLOR[ph], "stroke-width": 2.6,
            opacity: 0.95, filter: "url(#glow)",
          }));
        }

        const am = (a0 + a1) / 2;
        const [nx, ny] = polar(cx, cy, RN, am);
        s.appendChild(sv("circle", {
          cx: nx, cy: ny, r: lit ? 9 : used ? 6.2 : 4.6,
          fill: lit ? PHASE_COLOR[ph] : used ? "rgba(233,236,233,0.8)" : "#2a3338",
          stroke: lit ? "#0a0c0d" : "none", "stroke-width": 2,
          filter: lit ? "url(#glow)" : undefined,
        }));

        const [lx, ly] = polar(cx, cy, RL, am);
        const anchor = lx > cx + 14 ? "start" : lx < cx - 14 ? "end" : "middle";
        const t = sv("text", {
          x: lx, y: ly + 4, "text-anchor": anchor,
          class: "sv-step" + (lit ? " on" : ""),
          fill: lit ? PHASE_COLOR[ph] : (used ? "#c3cbcd" : undefined),
        }, s);
        t.textContent = STEP_LABEL[st] || st;
        if (used || lit) {
          const c = sv("text", {
            x: lx, y: ly + 17, "text-anchor": anchor, class: "sv-num",
            "font-size": 8.5, opacity: 0.8,
          }, s);
          c.textContent = `run ${(f.steps_tally && f.steps_tally[st]) || 0}×`;
        }
      });

      /* sweep marker */
      if (cur && steps.indexOf(cur) >= 0) {
        const k = steps.indexOf(cur);
        const a = -Math.PI / 2 + ((k + 0.5) / n) * Math.PI * 2;
        const [ax, ay] = polar(cx, cy, R1 + 44, a);
        const [bx, by] = polar(cx, cy, R1 + 12, a);
        const col = PHASE_COLOR[phaseOf(cur, ctx.meta)];
        s.appendChild(sv("line", { x1: ax, y1: ay, x2: bx, y2: by, stroke: col,
                                   "stroke-width": 1.6, opacity: 0.8, "stroke-dasharray": "3 3" }, s));
        s.appendChild(sv("circle", { cx: ax, cy: ay, r: 3.4, fill: col, filter: "url(#glow)" }, s));
      }

      /* hub */
      const hub = sv("g", {}, s);
      sv("circle", { cx, cy, r: R0 - 15, fill: "#0d1113", stroke: "#222a2e", "stroke-width": 1 }, hub);
      const stat = f.cap ? ctx.meta.stations[f.cap] : null;
      const rows = [
        ["CYCLE", String(f.cycle).padStart(2, "0"), 17],
        ["STATION", stat ? stat.label : "idle", stat ? 13 : 15],
        ["STEPS LIT", `${done.size} / ${n}`, 17],
      ];
      let y = cy - 34;
      rows.forEach(([k, v, size]) => {
        const kk = sv("text", { x: cx, y, "text-anchor": "middle", class: "sv-label", "font-size": 8 }, hub);
        kk.textContent = k;
        y += 13;
        const vv = sv("text", { x: cx, y, "text-anchor": "middle", class: "sv-strong", "font-size": size }, hub);
        vv.textContent = v;
        y += 23;
      });
      const pl = phaseOf(f.step, ctx.meta);
      const plt = sv("text", { x: cx, y: cy + 62, "text-anchor": "middle", class: "sv-label",
                               fill: f.step ? PHASE_COLOR[pl] : "#5c686d", "letter-spacing": "2" }, hub);
      plt.textContent = f.step ? `— ${pl.toUpperCase()} —` : "— IDLE —";

      $("#wheel-aux").textContent = `frame ${f.i} · cycle ${f.cycle}`;
      $("#wheel-hint").innerHTML =
        `<b>plan</b> holds 5 of the 8 tbp steps<br>` +
        `act splits into hansei · standardise · yokoten`;

      /* phase legend, in HTML so it can never collide with the ring */
      const lg = el("div", "wheel-legend");
      [["Plan", 5], ["Do", 1], ["Check", 1], ["Act", 3]].forEach(([ph, c]) => {
        const bang = el("span");
        bang.innerHTML = `<i style="background:${PHASE_COLOR[ph]}"></i>${ph} <b>${c}</b>`;
        lg.appendChild(bang);
      });
      host.appendChild(lg);

      /* counters */
      const tal = $("#wheel-tally");
      clear(tal);
      const tally = f.steps_tally || {};
      const max = Math.max(1, ...Object.values(tally));
      steps.forEach((st) => {
        const v = tally[st] || 0;
        const col = PHASE_COLOR[phaseOf(st, ctx.meta)];
        const row = el("div", "lad-tier");
        row.style.cssText = "margin-bottom:7px";
        const lb = el("div", "lb");
        lb.style.width = "140px";
        lb.style.color = v ? "var(--paper)" : "var(--faint)";
        lb.textContent = STEP_LABEL[st] || st;
        row.appendChild(lb);
        const bar = el("div", "bar");
        const fill = el("i");
        fill.style.width = (v / max) * 100 + "%";
        fill.style.background = `linear-gradient(90deg, ${col}, ${col}44)`;
        bar.appendChild(fill);
        row.appendChild(bar);
        row.appendChild(el("div", "n", String(v)));
        tal.appendChild(row);
      });
      const note = el("div", "lad-note");
      note.style.marginTop = "12px";
      note.innerHTML = "Five of the eight TBP steps live in Plan. A cycle that looks cheap on Do " +
        "is usually a cycle that skipped the thinking.";
      tal.appendChild(note);
    },
  });
})();
