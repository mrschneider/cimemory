/* ============================================================
   4 · THE A3 — the whole problem on one sheet
   ============================================================ */
(function () {
  function sec(title, phase, bodyNode, tag) {
    const s = el("div", "a3-sec");
    const h = el("div", "h");
    h.appendChild(el("span", null, esc(title)));
    if (tag) h.appendChild(el("span", "pdca-tag " + tag, tag));
    s.appendChild(h);
    s.appendChild(bodyNode);
    return s;
  }
  function kv(pairs) {
    const w = el("div");
    pairs.forEach(([k, v]) => {
      const r = el("div", "a3-kv");
      r.appendChild(el("div", "k", k));
      r.appendChild(el("div", "v", v));
      w.appendChild(r);
    });
    return w;
  }
  function bullets(items) {
    const u = el("ul", "bullets");
    (items || []).forEach((t) => u.appendChild(el("li", null, esc(t))));
    if (!items || !items.length) u.appendChild(el("li", null, "—"));
    return u;
  }
  function stamp(kind, text) {
    return `<span class="stamp ${kind}">${esc(text)}</span>`;
  }

  window.GEMBA_VIEWS = window.GEMBA_VIEWS || [];
  window.GEMBA_VIEWS.push({
    id: "a3",
    label: "The A3",
    render(f, ctx) {
      const host = $("#a3-sheet");
      clear(host);
      const a3 = f.a3;
      if (!a3) {
        host.appendChild(el("div", "a3-col left", `<div class="note"><p>No problem on the sheet yet.</p><p class="dim">An A3 opens the moment a gap against a standard is recorded.</p></div>`));
        host.appendChild(el("div", "a3-col", ""));
        $("#a3-hint").textContent = "waiting for the first problem";
        return;
      }
      const p = a3.problem, rc = a3.root_cause, t = a3.target,
            ex = a3.experiment, ck = a3.check, ha = a3.hansei, std = a3.standard;
      const meta = f.line ? ctx.meta.stations[f.line.capability] : ctx.meta.stations[p.capability];

      $("#a3-hint").innerHTML =
        `agent <b>${esc(f.agent)}</b> · status <b>${esc(p.status)}</b><br>` +
        `opened cycle <b>${f.cycle}</b> · ${esc(p.id)}`;

      /* ───────────── LEFT · PLAN ───────────── */
      const left = el("div", "a3-col left");
      const title = el("div", "a3-title");
      title.appendChild(el("h4", null, `A3 — ${esc(p.capability)}`));
      title.appendChild(el("div", "meta",
        `ideal vs actual<br>cycle ${f.cycle}`));
      left.appendChild(title);

      left.appendChild(sec("1 · Background — the standard", "Plan",
        kv([
          ["ideal", esc(p.ideal)],
          ["actual", esc(p.actual)],
          ["gap", `<b>${esc(p.gap)}</b>`],
        ]), "Plan"));

      const bd = el("div");
      bd.appendChild(bullets(p.breakdown));
      if (p.priority_point) {
        const pp = el("div");
        pp.style.cssText = "margin-top:8px;padding:7px 10px;border-left:3px solid var(--amber);background:rgba(255,176,32,0.06)";
        pp.innerHTML = `<div class="h" style="margin-bottom:3px;font-size:8.5px">priority point of cause</div><div style="font-size:12.5px;color:var(--paper)">${esc(p.priority_point)}</div>`;
        bd.appendChild(pp);
      }
      left.appendChild(sec("2 · Breakdown — narrow the focus", "Plan", bd, "Plan"));

      const tb = el("div");
      tb.appendChild(kv(t ? [
        ["metric", esc(t.metric)],
        ["baseline", num(t.baseline)],
        ["target", `<b>${num(t.goal)}</b> (${esc(t.direction)})`],
        ["deadline", esc(t.deadline)],
      ] : [["target", "not set yet"]]));
      if (t) {
        const met = t.direction === "decrease" ? (ck && ck.after_value <= t.goal) : (ck && ck.after_value >= t.goal);
        const st = el("div");
        st.style.marginTop = "8px";
        st.innerHTML = ck ? stamp(met ? "pass" : "fail", met ? "target met" : "target missed")
                          : stamp("hold", "target open");
        tb.appendChild(st);
      }
      left.appendChild(sec("3 · Target — measurable, time-bound", "Plan", tb, "Plan"));

      const rb = el("div");
      if (rc) {
        rb.appendChild(kv([
          ["cause", `<b>${esc(rc.statement)}</b>`],
          ["verified", esc(rc.verified_by)],
        ]));
      } else {
        rb.appendChild(el("div", "body", "root cause not yet verified"));
      }
      const wt = el("div");
      wt.style.marginTop = "8px";
      wt.innerHTML = a3.therefore_ok
        ? stamp("pass", "therefore test ✓")
        : stamp("hold", "chain incomplete");
      rb.appendChild(wt);
      const wc = el("div");
      wc.style.cssText = "margin-top:8px";
      const wl = el("ol");
      wl.style.cssText = "list-style:none;font-size:11.5px;line-height:1.5;color:var(--faint)";
      (a3.whys || []).forEach((w) => {
        const li = el("li", null, `<span style="color:var(--dim)">why ${w.level}</span> · ${esc(w.answer)}`);
        li.style.marginBottom = "3px";
        wl.appendChild(li);
      });
      wc.appendChild(wl);
      rb.appendChild(wc);
      left.appendChild(sec("4 · Root cause — the 5-Why chain", "Plan", rb, "Plan"));

      /* ───────────── RIGHT · DO · CHECK · ACT ───────────── */
      const right = el("div", "a3-col");
      const cmWrap = el("div");
      (a3.countermeasures || []).forEach((c) => {
        const row = el("div");
        row.style.cssText = "display:grid;grid-template-columns:96px 1fr;gap:10px;padding:7px 0;border-bottom:1px dashed var(--line)";
        const chip = el("span", "pdca-tag",
          esc(c.strength === "mizen_boushi" ? "mizen-boushi" : c.strength));
        chip.style.color = STRENGTH_COLOR[c.strength] || "var(--dim)";
        chip.style.borderColor = (STRENGTH_COLOR[c.strength] || "#313c43") + "66";
        row.appendChild(chip);
        const b = el("div");
        b.innerHTML = `<div style="font-size:12.5px;color:var(--paper)">${esc(c.description)}</div>` +
          (c.expected_effect ? `<div style="font-family:var(--mono);font-size:9.5px;color:var(--faint);margin-top:3px">→ ${esc(c.expected_effect)}</div>` : "");
        row.appendChild(b);
        cmWrap.appendChild(row);
      });
      if (!(a3.countermeasures || []).length) cmWrap.appendChild(el("div", "body", "none proposed yet"));
      right.appendChild(sec("5 · Countermeasures", "Plan", cmWrap, "Plan"));

      const db = el("div");
      if (ex) {
        db.appendChild(kv([["hypothesis", esc(ex.hypothesis)], ["metric", esc(ex.metric)]]));
        const dl = el("div");
        dl.style.marginTop = "7px";
        (ex.do_log || []).forEach((e) => {
          const d = el("div");
          d.style.cssText = "font-family:var(--mono);font-size:10px;color:var(--faint);line-height:1.7;padding-left:9px;border-left:2px solid var(--line2)";
          d.textContent = e;
          dl.appendChild(d);
        });
        db.appendChild(dl);
      } else db.appendChild(el("div", "body", "experiment not started"));
      right.appendChild(sec("6 · Do — see the countermeasure through", "Do", db, "Do"));

      const cb = el("div");
      if (ck) {
        cb.appendChild(kv([
          ["results", ck.results_met ? `<b style="color:var(--green)">met</b> — ${num(ck.after_value)} vs target ${num(t.goal)}`
                                     : `<b style="color:var(--red)">missed</b> — ${num(ck.after_value)}`],
          ["process", ck.process_holds ? "<b style=\"color:var(--green)\">holds</b> — the gain is anchored"
                                       : "<b style=\"color:var(--red)\">does not hold</b> — nothing keeps it"],
          ["period", esc(ck.period || "—")],
          ["notes", esc(ck.process_notes || "—")],
        ]));
        const cs = el("div");
        cs.style.marginTop = "8px";
        cs.innerHTML = stamp(ck.results_met && ck.process_holds ? "pass" : "fail",
                             ck.results_met && ck.process_holds ? "check passed" : "check failed");
        cb.appendChild(cs);
      } else cb.appendChild(el("div", "body", "not checked yet — implementation is not improvement"));
      right.appendChild(sec("7 · Check — results and process", "Check", cb, "Check"));

      const ab = el("div");
      if (ha) {
        const gw = el("div");
        gw.innerHTML = `<div style="font-family:var(--mono);font-size:9px;letter-spacing:.14em;text-transform:uppercase;color:var(--green);margin-bottom:3px">went well</div>`;
        gw.appendChild(bullets(ha.went_well));
        ab.appendChild(gw);
        const gp = el("div");
        gp.style.marginTop = "9px";
        gp.innerHTML = `<div style="font-family:var(--mono);font-size:9px;letter-spacing:.14em;text-transform:uppercase;color:var(--red);margin-bottom:3px">went poorly · hansei</div>`;
        gp.appendChild(bullets(ha.went_poorly));
        ab.appendChild(gp);
        if ((ha.next_time || []).length) {
          const nt = el("div");
          nt.style.marginTop = "9px";
          nt.innerHTML = `<div style="font-family:var(--mono);font-size:9px;letter-spacing:.14em;text-transform:uppercase;color:var(--faint);margin-bottom:3px">next time</div>`;
          nt.appendChild(bullets(ha.next_time));
          ab.appendChild(nt);
        }
      } else ab.appendChild(el("div", "body", "reflection is mandatory before a gain is locked in"));
      right.appendChild(sec("8 · Hansei — reflection", "Act", ab, "Act"));

      const sb = el("div");
      if (std) {
        sb.appendChild(kv([
          ["standard", `<b>v${std.version}</b> — ${esc(std.description)}`],
          ["supersedes", std.supersedes ? esc(std.supersedes) : "— (first version)"],
        ]));
      } else {
        sb.appendChild(el("div", "body", "not standardised — the baseline has not moved"));
      }
      const spreads = (f.store.spreads || []).filter((s) => std && s.standard_id === std.id);
      if (spreads.length) {
        const y = el("div");
        y.style.marginTop = "8px";
        y.innerHTML = `<div style="font-family:var(--mono);font-size:9px;letter-spacing:.14em;text-transform:uppercase;color:var(--violet);margin-bottom:4px">yokoten</div>`;
        spreads.forEach((sp) => {
          y.appendChild(el("div", null,
            `<span style="font-size:12.5px;color:var(--dim)">→ ${esc(sp.targets.join(", "))}</span>`));
        });
        sb.appendChild(y);
      }
      right.appendChild(sec("8 · Standardise and spread", "Act", sb, "Act"));

      host.appendChild(left);
      host.appendChild(right);
    },
  });
})();
