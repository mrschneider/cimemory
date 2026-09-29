/* ============================================================
   3 · THE STAIRCASE — the standards ratchet
   ============================================================ */
(function () {
  window.GEMBA_VIEWS = window.GEMBA_VIEWS || [];
  window.GEMBA_VIEWS.push({
    id: "staircase",
    label: "The Staircase",
    render(f, ctx) {
      const caps = Object.keys(ctx.meta.stations);
      const pick = ctx.state.pick && caps.includes(ctx.state.pick) ? ctx.state.pick : (f.cap || caps[0]);

      /* chip picker */
      const pk = $("#stair-pick");
      clear(pk);
      caps.forEach((c) => {
        const chip = el("div", "chip" + (c === pick ? " on" : ""), ctx.meta.stations[c].label);
        chip.onclick = () => { ctx.state.pick = c; ctx.render(); };
        pk.appendChild(chip);
      });

      const st = ctx.meta.stations[pick];
      const goal = f.board[pick].goal;
      const start = ctx.frames[0].board[pick].standard;
      const series = ctx.frames.map((fr) => ({
        k: fr.i, cycle: fr.cycle,
        std: fr.board[pick].standard,
        act: fr.board[pick].actual,
        ctl: pick === (fr.line && fr.line.capability) ? fr.line.control : null,
      }));
      /* the control has no per-station trace in the frames — rebuild its drift */
      series.forEach((p) => { if (p.ctl == null) p.ctl = start * Math.pow(1.0028, p.cycle); });

      const vals = series.flatMap((p) => [p.std, p.act, p.ctl]).concat([goal]);
      let lo = Math.min(...vals), hi = Math.max(...vals);
      const pad = (hi - lo) * 0.14 || 1;
      lo -= pad; hi += pad;

      const W = 940, H = 300, PL = 62, PR = 118, PT = 22, PB = 28;
      const host = $("#stair-svg");
      clear(host);
      const s = sv("svg", { viewBox: `0 0 ${W} ${H}`, preserveAspectRatio: "xMidYMid meet" }, host);

      const dec = st.direction === "decrease";
      const yOf = (v) => dec
        ? PT + (v - lo) / (hi - lo) * (H - PT - PB)
        : PT + (hi - v) / (hi - lo) * (H - PT - PB);
      const xOf = (k) => PL + (k / Math.max(1, ctx.frames.length - 1)) * (W - PL - PR);

      /* y grid + ticks */
      for (let t = 0; t <= 4; t++) {
        const v = lo + (hi - lo) * (t / 4);
        const y = yOf(v);
        s.appendChild(sv("line", {
          x1: PL, y1: y, x2: W - PR + 20, y2: y,
          stroke: "#1b2226", "stroke-width": 1,
        }));
        const tx = sv("text", { x: PL - 10, y: y + 3.5, "text-anchor": "end", class: "sv-num" }, s);
        tx.textContent = num(v);
      }
      const yl = sv("text", {
        x: 14, y: H / 2, "text-anchor": "middle", class: "sv-label",
        transform: `rotate(-90 14 ${H / 2})`,
      }, s);
      yl.textContent = `${st.metric} (${st.unit})`;

      /* cycle separators, labelled at the centre of each cycle band */
      const bands = {};
      ctx.frames.forEach((fr) => {
        const b = bands[fr.cycle] || (bands[fr.cycle] = { first: fr.i, last: fr.i });
        b.last = fr.i;
      });
      Object.keys(bands).forEach((c) => {
        const b = bands[c];
        s.appendChild(sv("line", {
          x1: xOf(b.first), y1: PT - 9, x2: xOf(b.first), y2: H - PB + 6,
          stroke: "#232b30", "stroke-width": 1, "stroke-dasharray": "2 4",
        }));
        const xm = (xOf(b.first) + xOf(b.last)) / 2;
        const t2 = sv("text", { x: xm, y: PT - 13, "text-anchor": "middle",
                                class: "sv-label", "font-size": 8 }, s);
        t2.textContent = "C" + String(c).padStart(2, "0");
      });

      /* goal */
      s.appendChild(sv("line", {
        x1: PL, y1: yOf(goal), x2: W - PR + 20, y2: yOf(goal),
        stroke: "#2fd07f", "stroke-width": 1.4, "stroke-dasharray": "7 5", opacity: 0.8,
      }));
      const gt = sv("text", { x: W - PR + 26, y: yOf(goal) + 3.5, class: "sv-num", fill: "#2fd07f" }, s);
      gt.textContent = `goal ${num(goal)}`;

      /* control: the no-memory agent, drifting the wrong way */
      let dctl = "";
      series.forEach((p) => { dctl += (dctl ? " L" : "M") + xOf(p.k) + "," + yOf(p.ctl); });
      s.appendChild(sv("path", {
        d: dctl, fill: "none", stroke: "#ff3b30", "stroke-width": 1.2,
        "stroke-dasharray": "4 4", opacity: 0.6,
      }));
      const ct = sv("text", { x: W - PR + 26, y: yOf(series[0].ctl) + 3.5, class: "sv-num", fill: "#ff3b30", opacity: 0.85 }, s);
      ct.textContent = "no memory";

      /* the standard: a step function, never lowered */
      let dstd = "", prev = null;
      series.forEach((p) => {
        const y = yOf(p.std), x = xOf(p.k);
        if (prev === null) { dstd = `M${x},${y}`; }
        else if (p.std !== prev.std) { dstd += ` L${x},${yOf(prev.std)} L${x},${y}`; }
        else { dstd += ` L${x},${y}`; }
        prev = p;
      });
      s.appendChild(sv("path", { d: dstd, fill: "none", stroke: "#e9ece9", "stroke-width": 2.2 }));

      /* actual: what the floor is really doing */
      let dact = "";
      series.forEach((p) => { dact += (dact ? " L" : "M") + xOf(p.k) + "," + yOf(p.act); });
      s.appendChild(sv("path", {
        d: dact, fill: "none", stroke: "#ffb020", "stroke-width": 1.7, opacity: 0.95,
      }));

      /* markers */
      ctx.frames.forEach((fr) => {
        const x = xOf(fr.i), y = yOf(fr.board[pick].actual);
        if (fr.kind === "check" && fr.extra && fr.extra.results_met === false) {
          sv("path", { d: `M${x - 4},${y - 4} L${x + 4},${y + 4} M${x + 4},${y - 4} L${x - 4},${y + 4}`,
                       stroke: "#ff3b30", "stroke-width": 1.8 }, s);
        } else if (fr.kind === "check" && fr.extra && fr.extra.process_holds === false) {
          sv("circle", { cx: x, cy: y, r: 4.6, fill: "none", stroke: "#ff3b30", "stroke-width": 1.6 }, s);
        } else if (fr.kind === "standard") {
          sv("path", { d: `M${x},${y - 8} L${x - 5},${y + 2} L${x + 5},${y + 2} Z`, fill: "#2fd07f" }, s);
          const v = sv("text", { x: x, y: y - 13, "text-anchor": "middle", class: "sv-num", fill: "#2fd07f", "font-size": 8.5 }, s);
          v.textContent = "v" + (fr.extra && fr.extra.version);
        } else if (fr.kind === "kaikaku" && fr.extra && fr.extra.approved) {
          sv("path", { d: `M${x},${y - 9} L${x + 5},${y} L${x},${y + 9} L${x - 5},${y} Z`, fill: "#ffe14d" }, s);
        } else if (fr.kind === "andon") {
          sv("circle", { cx: x, cy: y, r: 3.2, fill: "#ff3b30", opacity: 0.9 }, s);
        }
      });

      /* current position marker */
      const cx2 = xOf(f.i), cy2 = yOf(f.board[pick].actual);
      s.appendChild(sv("line", { x1: cx2, y1: PT - 8, x2: cx2, y2: H - PB + 6, stroke: "#ffb020", "stroke-width": 1, opacity: 0.55 }, s));
      sv("circle", { cx: cx2, cy: cy2, r: 5, fill: "#ffb020", stroke: "#0a0c0d", "stroke-width": 2 }, s);

      /* x label */
      const xl = sv("text", { x: PL + (W - PL - PR) / 2, y: H - 6, "text-anchor": "middle", class: "sv-label" }, s);
      xl.textContent = "improvement programme →  each dashed column is one cycle";

      $("#stair-title").textContent = `${st.label} — standard, actual and the no-memory control`;
      $("#stair-hint") && ($("#stair-hint").textContent = "");

      /* version history */
      const hist = $("#stair-versions");
      clear(hist);
      const stds = (f.store.standards || []).filter((x) => x.capability === pick);
      if (!stds.length) hist.appendChild(el("div", "ev empty", "no standard yet — the baseline is still the starting guess"));
      stds.slice().reverse().forEach((x) => {
        const row = el("div", "ev " + (x.active ? "info" : "info"));
        row.appendChild(el("div", "bar"));
        const b = el("div", "ev-body");
        b.appendChild(el("div", "ev-t",
          `v${x.version} · ${x.active ? "active standard" : "superseded"}`));
        b.appendChild(el("div", "ev-m", esc(x.description)));
        row.appendChild(b);
        hist.appendChild(row);
      });
    },
  });
})();
