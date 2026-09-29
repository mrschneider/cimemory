/* ============================================================
   5 · THE FIVE WHYS — symptom to cause, then read it backwards
   ============================================================ */
(function () {
  window.GEMBA_VIEWS = window.GEMBA_VIEWS || [];
  window.GEMBA_VIEWS.push({
    id: "whys",
    label: "Five Whys",
    render(f, ctx) {
      const lad = $("#whys-ladder");
      clear(lad);
      const a3 = f.a3;
      const whys = (a3 && a3.whys) || [];

      if (!a3) {
        lad.appendChild(el("div", "ev empty", "no problem open — nothing to ask why about yet"));
        $("#whys-test").innerHTML = "";
        $("#whys-hint").textContent = "waiting";
        return;
      }

      /* rung 0: the symptom as measured at the gemba */
      const sym = el("div", "rung");
      sym.appendChild(el("div", "n", "0"));
      const sb = el("div");
      sb.appendChild(el("div", "q", "Symptom — what we actually see"));
      sb.appendChild(el("div", "a", esc(a3.problem.gap)));
      sb.appendChild(el("div", "ev", esc(a3.problem.actual)));
      sym.appendChild(sb);
      lad.appendChild(sym);

      whys.forEach((w, i) => {
        const r = el("div", "rung" + (i === whys.length - 1 ? " deep" : ""));
        r.appendChild(el("div", "n", String(w.level)));
        const b = el("div");
        b.appendChild(el("div", "q", esc(w.question)));
        b.appendChild(el("div", "a", esc(w.answer)));
        if (w.evidence) b.appendChild(el("div", "ev", "observed · " + esc(w.evidence)));
        r.appendChild(b);
        lad.appendChild(r);
      });

      /* the verified root cause */
      const rc = a3.root_cause;
      if (rc) {
        const r = el("div", "rung root");
        r.appendChild(el("div", "n", "★"));
        const b = el("div");
        b.appendChild(el("div", "q", "Root cause — verified, not assumed"));
        b.appendChild(el("div", "a", esc(rc.statement)));
        b.appendChild(el("div", "ev", "verified by · " + esc(rc.verified_by)));
        r.appendChild(b);
        lad.appendChild(r);
      }

      $("#whys-hint").innerHTML =
        `<b>${whys.length}</b> rungs recorded<br>` +
        (rc ? `root cause <b>verified</b>` : `root cause <b>not yet asserted</b>`);

      /* therefore test */
      const test = $("#whys-test");
      clear(test);
      const chain = whys.map((w) => w.answer);
      if (chain.length < 2) {
        test.appendChild(el("div", "ev empty",
          "a chain of fewer than two whys cannot be validated"));
        return;
      }
      const back = chain.slice().reverse();
      const lines = [];
      for (let i = 0; i < back.length - 1; i++) lines.push([back[i], back[i + 1]]);

      const wrap = el("div");
      lines.forEach(([cause, effect], i) => {
        const row = el("div");
        row.style.cssText = "padding:8px 0;border-bottom:1px dashed var(--line)";
        row.innerHTML =
          `<div style="font-size:12.5px;color:var(--paper);line-height:1.5">${esc(effect)}</div>` +
          `<div style="font-family:var(--mono);font-size:9px;letter-spacing:.16em;text-transform:uppercase;color:var(--amber);margin:4px 0">therefore</div>` +
          `<div style="font-size:12.5px;color:var(--dim);line-height:1.5">${esc(cause)}</div>`;
        wrap.appendChild(row);
      });
      test.appendChild(wrap);

      const verdict = el("div");
      verdict.style.marginTop = "12px";
      const ok = a3.therefore_ok;
      verdict.innerHTML = ok
        ? `<span class="stamp pass">chain reads true</span>
           <div class="p-note" style="margin-top:9px">Read bottom-up the sentence holds, so the
           chain is a cause-and-effect argument and not a list of opinions.
           ${whys.length} whys were asked; the rule of thumb is five.</div>`
        : `<span class="stamp hold">chain incomplete</span>
           <div class="p-note" style="margin-top:9px">At least one rung has no observed answer.
           An unverified cause cannot back a countermeasure — the plugin will refuse it.</div>`;
      test.appendChild(verdict);

      const rootNote = el("div", "p-note");
      rootNote.style.marginTop = "10px";
      rootNote.innerHTML = ok
        ? `therefore <b style="color:var(--amber)">${esc(back[0])}</b> — this is the cause the
           countermeasure must attack.`
        : "";
      test.appendChild(rootNote);
    },
  });
})();
