/* ============================================================
   1 · THE ANDON BOARD — every station, live
   ============================================================ */
(function () {
  function stationCard(cap, st, railMax, railMin, openAndon) {
    const d = st.direction === "decrease" ? -1 : 1;
    const delta = st.actual - st.standard;
    const good = (d < 0 && delta <= 0) || (d > 0 && delta >= 0);
    const card = el("div", "station " + st.status);

    const top = el("div", "st-top");
    top.appendChild(el("span", "lamp " + st.status));
    top.appendChild(el("div", "st-name", `${esc(st.label)}<small>${esc(cap)}</small>`));
    top.appendChild(el("span", "st-state", esc(st.status)));
    card.appendChild(top);

    const nums = el("div", "st-nums");
    nums.appendChild(el("div", "st-big",
      `${num(st.actual)}<small>${esc(st.unit)}</small>`));
    nums.appendChild(el("div", "st-vs",
      `standard <b>${num(st.standard)}</b><br>goal <b>${num(st.goal)}</b>`));
    nums.appendChild(el("div", "st-delta " + (good ? "good" : "bad"),
      (delta > 0 ? "+" : "") + num(delta)));
    card.appendChild(nums);

    /* gauge: best value on the left, worst on the right */
    const g = el("div", "st-gauge");
    const rail = el("div", "gauge-rail");
    const frac = mapRange(st.actual, railMax, railMin, 0, 100);
    const fill = el("i", "gauge-fill");
    fill.style.width = frac + "%";
    rail.appendChild(fill);
    const ms = el("i", "gauge-mark std");
    ms.style.left = mapRange(st.standard, railMax, railMin, 0, 100) + "%";
    rail.appendChild(ms);
    const mg = el("i", "gauge-mark goal");
    mg.style.left = mapRange(st.goal, railMax, railMin, 0, 100) + "%";
    rail.appendChild(mg);
    g.appendChild(rail);
    const lg = el("div", "gauge-legend");
    lg.innerHTML = `<span>goal ${num(st.goal)}</span><span>std ${num(st.standard)}</span><span>worst ${num(railMax)}</span>`;
    g.appendChild(lg);
    card.appendChild(g);

    const w = el("div", "st-waste",
      `muda · <b>${esc(st.waste)}</b> — ${esc(st.waste_detail)}`);
    if (openAndon) w.innerHTML += `<br><span style="color:var(--red)">▲ andon open</span>`;
    card.appendChild(w);
    return card;
  }

  window.GEMBA_VIEWS = window.GEMBA_VIEWS || [];
  window.GEMBA_VIEWS.push({
    id: "andon",
    label: "Andon Board",
    render(f, ctx) {
      const stations = $("#andon-stations");
      clear(stations);

      /* rail extents per station, over the whole programme */
      const ext = {};
      for (const cap in ctx.meta.stations) {
        let mx = -Infinity;
        for (const fr of ctx.frames) {
          const b = fr.board[cap];
          if (b) mx = Math.max(mx, b.actual, b.standard);
        }
        const goal = f.board[cap].goal;
        ext[cap] = { max: Math.max(mx, goal * 1.15), min: goal };
      }

      const openByCap = {};
      (f.store.andons || []).forEach((a) => {
        if (!a.resolved && a.reason.indexOf(f.board[a.agent] ? "" : "") === 0) { /* noop */ }
      });

      for (const cap in f.board) {
        const openAndon = (f.store.andons || []).some(
          (a) => !a.resolved && a.reason.toLowerCase().indexOf(
            (ctx.meta.stations[cap].label || "").toLowerCase()) >= 0);
        stations.appendChild(stationCard(
          cap, f.board[cap], ext[cap].max, ext[cap].min, openAndon));
      }

      const ok = Object.values(f.board).filter((s) => s.status === "normal").length;
      const ab = Object.values(f.board).filter((s) => s.status === "abnormal").length;
      const st = Object.values(f.board).filter((s) => s.status === "stopped").length;
      $("#andon-hint").innerHTML =
        `<b>${ok}</b> normal · <b>${ab}</b> abnormal · <b>${st}</b> stopped<br>` +
        `frame ${f.i} of ${ctx.frames.length - 1} · cycle ${f.cycle}`;

      /* andon log */
      const log = $("#andon-log");
      clear(log);
      const list = (f.store.andons || []).slice().reverse();
      if (!list.length) log.appendChild(el("div", "ev empty", "no andon raised yet — the line has not needed stopping"));
      list.forEach((a) => {
        const row = el("div", "ev " + a.severity);
        row.appendChild(el("div", "bar"));
        const b = el("div", "ev-body");
        b.appendChild(el("div", "ev-t",
          `${a.severity} · ${a.stopped ? "LINE STOPPED" : "flag"} · ${a.resolved ? "resolved" : "open"}`));
        b.appendChild(el("div", "ev-m", esc(a.reason)));
        if (a.resolved && a.resolution)
          b.appendChild(el("div", "ev-t", "→ " + esc(a.resolution)));
        row.appendChild(b);
        log.appendChild(row);
      });

      /* refusals — the plugin saying no */
      const ref = $("#andon-refusals");
      clear(ref);
      const refs = history(ctx.frames, ctx.i, "refusal");
      if (!refs.length) ref.appendChild(el("div", "ev empty", "the plugin has not had to refuse anything yet"));
      refs.slice().reverse().forEach((r) => {
        const row = el("div", "ev refusal");
        row.appendChild(el("div", "bar"));
        const b = el("div", "ev-body");
        b.appendChild(el("div", "ev-t", `refusal · cycle ${r.cycle} · ${esc(r.cap || "–")}`));
        b.appendChild(el("div", "ev-m", esc(r.text)));
        row.appendChild(b);
        ref.appendChild(row);
      });
    },
  });
})();
