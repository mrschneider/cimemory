/* ============================================================
   6 · THE LEDGER — waste accounted for, countermeasures ranked
   ============================================================ */
(function () {
  window.GEMBA_VIEWS = window.GEMBA_VIEWS || [];
  window.GEMBA_VIEWS.push({
    id: "ledger",
    label: "The Ledger",
    render(f, ctx) {
      const rows = $("#ledger-rows");
      clear(rows);
      const store = f.store;
      let eliminated = 0, contained = 0, open = 0;

      for (const cap in ctx.meta.stations) {
        const s = ctx.meta.stations[cap];
        const probs = (store.problems || []).filter((p) => p.capability === cap);
        const last = probs[probs.length - 1];
        const cms = last
          ? (store.countermeasures || []).filter((c) => c.problem_id === last.id)
          : [];
        let state = "open";
        if (last && last.status === "standardised") state = "eliminated";
        else if (cms.length) state = "contained";
        if (state === "eliminated") eliminated++;
        else if (state === "contained") contained++;
        else open++;

        const r = el("div", "led-row");
        const top = el("div", "led-top");
        top.appendChild(el("div", "led-cap", esc(s.label)));
        top.appendChild(el("div", "led-state " + state, esc(state)));
        r.appendChild(top);

        const mid = el("div", "led-mid");
        mid.appendChild(el("div", "led-waste", esc(s.waste)));
        const det = el("div", "led-detail");
        det.innerHTML = esc(s.waste_detail) +
          (last ? `<span style="font-family:var(--mono);font-size:9px;color:var(--faint)"> — ${
            state === "eliminated" ? "countermeasure folded into the standard" :
            state === "contained" ? "countermeasure proposed, not yet standardised" :
            "no countermeasure yet"}</span>` : "");
        mid.appendChild(det);
        r.appendChild(mid);
        rows.appendChild(r);
      }

      $("#ledger-hint").innerHTML =
        `<b>${eliminated}</b> eliminated · <b>${contained}</b> contained · <b>${open}</b> open<br>` +
        `muda · mura · muri`;

      /* strength ladder */
      const lad = $("#ledger-ladder");
      clear(lad);
      const all = store.countermeasures || [];
      const by = { taisho: 0, taisaku: 0, mizen_boushi: 0 };
      all.forEach((c) => { by[c.strength] = (by[c.strength] || 0) + 1; });
      const max = Math.max(1, by.taisho, by.taisaku, by.mizen_boushi);

      const wrap = el("div", "lad");
      [["taisho", "t1"], ["taisaku", "t2"], ["mizen_boushi", "t3"]].forEach(([k, cls]) => {
        const tier = el("div", "lad-tier " + cls);
        tier.appendChild(el("div", "lb", esc(STRENGTH_LABEL[k] || k)));
        const bar = el("div", "bar");
        const i = el("i");
        i.style.width = (by[k] / max) * 100 + "%";
        bar.appendChild(i);
        tier.appendChild(bar);
        tier.appendChild(el("div", "n", String(by[k] || 0)));
        wrap.appendChild(tier);
      });
      wrap.appendChild(el("div", "lad-note",
        "taisho contains the symptom so work continues · taisaku attacks a verified root cause" +
        " · mizen-boushi changes the conditions so the failure cannot arise."));
      lad.appendChild(wrap);

      const note = el("div", "lad-note");
      note.style.marginTop = "14px";
      const mizen = by.mizen_boushi || 0;
      note.innerHTML = all.length
        ? `<b style="color:${mizen > by.taisaku ? "var(--green)" : "var(--amber)"}">${
            mizen}/${all.length}</b> countermeasures design the failure out. ` +
          (mizen >= by.taisaku
            ? "The programme is pushing up the strength ladder, not settling for containment."
            : "Most countermeasures are still fixes rather than prevention — push further up the ladder.")
        : "no countermeasure proposed yet.";
      lad.appendChild(note);

      const excl = el("div", "lad-note");
      excl.style.marginTop = "10px";
      const tais = by.taisho || 0;
      excl.innerHTML = tais
        ? `${tais} containment action${tais > 1 ? "s" : ""} on the ledger. Containment is legitimate — ` +
          `but declaring victory there is how a solved problem comes back.`
        : `no containment-only actions: every countermeasure on the ledger names a cause.`;
      lad.appendChild(excl);
    },
  });
})();
