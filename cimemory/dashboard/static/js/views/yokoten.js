/* ============================================================
   7 · YOKOTEN — horizontal spread of a proven standard
   ============================================================ */
(function () {
  window.GEMBA_VIEWS = window.GEMBA_VIEWS || [];
  window.GEMBA_VIEWS.push({
    id: "yokoten",
    label: "Yokoten",
    render(f, ctx) {
      const host = $("#yoko-svg");
      clear(host);
      const spreads = f.store.spreads || [];
      const stds = f.store.standards || [];
      const sib = ctx.meta.siblings || [];
      const capOf = (sid) => {
        if (!sid) return "no standard yet";
        const s = stds.find((x) => x.id === sid);
        return s ? s.capability : "?";
      };
      const verOf = (sid) => {
        if (!sid) return "not standardised";
        const s = stds.find((x) => x.id === sid);
        return s ? "v" + s.version : "";
      };

      const W = 760, H = 420;
      const s = sv("svg", { viewBox: `0 0 ${W} ${H}`, preserveAspectRatio: "xMidYMid meet" }, host);
      const sx = 150, sy = H / 2;
      const tx = 590;
      const ys = {};
      sib.forEach((a, i) => { ys[a] = 96 + i * ((H - 200) / Math.max(1, sib.length - 1)); });

      /* lanes */
      sib.forEach((a) => {
        s.appendChild(sv("line", {
          x1: 240, y1: ys[a], x2: tx + 70, y2: ys[a],
          stroke: "#1b2226", "stroke-width": 1,
        }));
      });

      /* edges — fanned out so that several standards reaching the same
         sibling do not stack on top of each other */
      const prev = ctx.i > 0 ? ctx.frames[ctx.i - 1] : null;
      const prevIds = new Set(((prev && prev.store.spreads) || []).map((x) => x.id));
      const edgeList = [];
      spreads.forEach((sp) => {
        sp.targets.forEach((t) => { if (ys[t] != null) edgeList.push({ sp, t }); });
      });
      const perTarget = {};
      edgeList.forEach(({ t }) => { perTarget[t] = (perTarget[t] || 0) + 1; });
      const drawn = {};
      let freshN = 0;

      edgeList.forEach(({ sp, t }) => {
        const n = perTarget[t];
        const k = (drawn[t] = (drawn[t] || 0) + 1) - 1;
        const off = (k - (n - 1) / 2) * 22;
        const fresh = !prevIds.has(sp.id);
        if (fresh) freshN++;

        const mx = (sx + tx) / 2;
        const p0 = [sx + 46, sy], p1 = [mx + off, sy + off * 0.6],
            p2 = [mx + off, ys[t] + off * 0.2], p3 = [tx - 10, ys[t]];
        const d = `M${p0[0]},${p0[1]} C${p1[0]},${p1[1]} ${p2[0]},${p2[1]} ${p3[0]},${p3[1]}`;
        s.appendChild(sv("path", {
          d, fill: "none", stroke: "#a98bff",
          "stroke-width": fresh ? 1.7 : 1.2,
          opacity: fresh ? 0.95 : 0.42,
        }));

        /* stagger the caption along the curve so converging edges do not stack */
        const tt = 0.30 + (n > 1 ? 0.52 * (k / (n - 1)) : 0.0);
        const bez = (u) => [
          Math.pow(1 - u, 3) * p0[0] + 3 * Math.pow(1 - u, 2) * u * p1[0] + 3 * (1 - u) * u * u * p2[0] + u * u * u * p3[0],
          Math.pow(1 - u, 3) * p0[1] + 3 * Math.pow(1 - u, 2) * u * p1[1] + 3 * (1 - u) * u * u * p2[1] + u * u * u * p3[1],
        ];
        const [lx, ly] = bez(tt);
        const t1 = sv("text", {
          x: lx, y: ly - 5, "text-anchor": "middle", class: "sv-num",
          "font-size": 8.5, fill: "#a98bff", opacity: fresh ? 1 : 0.6,
        }, s);
        t1.textContent = capOf(sp.standard_id);
        const t2 = sv("text", {
          x: lx, y: ly + 7, "text-anchor": "middle", class: "sv-num",
          "font-size": 8, fill: "#8d999e", opacity: fresh ? 0.9 : 0.55,
        }, s);
        t2.textContent = verOf(sp.standard_id);
      });

      /* source node */
      sv("circle", { cx: sx, cy: sy, r: 30, fill: "#121619", stroke: "#ffb020", "stroke-width": 1.6 }, s);
      sv("circle", { cx: sx, cy: sy, r: 7, fill: "#ffb020" }, s);
      const sn = sv("text", { x: sx, y: sy + 50, "text-anchor": "middle", class: "sv-strong" }, s);
      sn.textContent = f.agent;
      const sn2 = sv("text", { x: sx, y: sy + 64, "text-anchor": "middle", class: "sv-label" }, s);
      sn2.textContent = "proving ground";

      /* sibling nodes */
      sib.forEach((a) => {
        const got = spreads.some((sp) => sp.targets.includes(a));
        sv("rect", {
          x: tx - 10, y: ys[a] - 19, width: 148, height: 38,
          fill: got ? "#141a1d" : "#0f1315",
          stroke: got ? "#a98bff" : "#222a2e", "stroke-width": got ? 1.3 : 1,
        }, s);
        sv("circle", { cx: tx + 6, cy: ys[a], r: 5,
                       fill: got ? "#a98bff" : "#2a3338" }, s);
        const t = sv("text", { x: tx + 20, y: ys[a] + 4, class: "sv-strong", "font-size": 13 }, s);
        t.textContent = a;
        const sub = sv("text", { x: tx + 20, y: ys[a] + 16, class: "sv-label", "font-size": 7.5 }, s);
        const got_n = spreads.filter((sp) => sp.targets.includes(a)).length;
        sub.textContent = got_n ? `${got_n} standard${got_n > 1 ? "s" : ""} received` : "nothing received yet";
      });

      $("#yokoten-hint").innerHTML =
        `<b>${spreads.length}</b> standards carried so far<br>` +
        `<b>${freshN}</b> landed on this frame`;

      /* log */
      const log = $("#yoko-log");
      clear(log);
      if (!spreads.length) log.appendChild(el("div", "ev empty",
        "nothing spread yet — a countermeasure travels only after it is standardised"));
      spreads.slice().reverse().forEach((sp) => {
        const row = el("div", "ev info");
        row.appendChild(el("div", "bar"));
        const b = el("div", "ev-body");
        b.appendChild(el("div", "ev-t", `${esc(capOf(sp.standard_id))} · ${verOf(sp.standard_id)} — carried to ${esc(sp.targets.join(", "))}`));
        b.appendChild(el("div", "ev-m", esc(sp.rationale)));
        row.appendChild(b);
        log.appendChild(row);
      });
    },
  });
})();
