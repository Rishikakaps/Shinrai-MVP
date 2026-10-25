/* Intake proposals remain separate from source acceptance and deterministic reconciliation. */
"use strict";
(() => {
  const $ = (s) => document.querySelector(s),
    esc = (v) =>
      String(v ?? "").replace(
        /[&<>"']/g,
        (c) =>
          ({
            "&": "&amp;",
            "<": "&lt;",
            ">": "&gt;",
            '"': "&quot;",
            "'": "&#39;",
          })[c],
      ),
    analyst = document.body.dataset.role === "analyst";
  const S = {
    cases: [],
    snapshot: null,
    rows: [],
    selected: null,
    busy: false,
    pending: null,
    dirty: false,
  };
  const option = (v, t) => `<option value="${esc(v)}">${esc(t)}</option>`,
    csrf = $('meta[name="csrf-token"]').content;
  const categories = [
    "commissioning_certificate",
    "technical_specification",
    "purchase_invoice",
    "purchase_order",
    "machine_nameplate",
    "inspection_report",
    "maintenance_record",
    "installation_evidence",
    "acoustic_recording",
    "other",
  ];
  const api = async (path, method = "GET", body = null, key = null) => {
    const headers = {};
    if (method !== "GET") {
      headers["X-CSRF-Token"] = csrf;
      headers["Idempotency-Key"] = key || crypto.randomUUID();
    }
    if (body && !(body instanceof FormData)) {
      headers["Content-Type"] = "application/json";
      body = JSON.stringify(body);
    }
    const r = await fetch(path, {
      method,
      headers,
      body,
      credentials: "same-origin",
      signal: AbortSignal.timeout(130000),
    });
    if (!r.ok) {
      const x = await r.json().catch(() => ({ detail: r.statusText }));
      throw Error(
        typeof x.detail === "string" ? x.detail : JSON.stringify(x.detail),
      );
    }
    return r.json();
  };
  const note = (t, error = false) => {
    $("#notice").textContent = t;
    $("#notice").classList.toggle("error", error);
  };
  const visit = () =>
      S.snapshot?.v1_inspections.find(
        (v) => v.inspection.id === $("#visit").value,
      ),
    assets = () => visit()?.assets || [];
  async function action(fn) {
    if (S.busy) return;
    S.busy = true;
    try {
      await fn();
    } catch (e) {
      note(e.message, true);
    } finally {
      S.busy = false;
      document
        .querySelectorAll("[data-write]")
        .forEach((b) => (b.disabled = !analyst));
    }
  }
  async function loadCase() {
    S.snapshot = await api("/api/v1/cases/" + $("#case").value + "/export");
    $("#visit").innerHTML = S.snapshot.v1_inspections
      .map((v) => option(v.inspection.id, v.inspection.name))
      .join("");
    await loadVisit();
  }
  async function loadVisit() {
    $("#hint").innerHTML =
      option("", "No hint — resolve from source identifiers") +
      assets()
        .map((a) => option(a.id, a.tag + " · " + a.serial))
        .join("");
    S.selected = null;
    $("#detail").hidden = true;
    await refresh();
  }
  async function refresh() {
    if (!$("#visit").value) return;
    const p = new URLSearchParams({
      inspection_id: $("#visit").value,
      q: $("#search").value,
    });
    if ($("#filter").value) p.set("state", $("#filter").value);
    S.rows = await api("/api/evidence/inbox?" + p);
    $("#items").innerHTML =
      S.rows
        .map(
          (r) =>
            `<article class="record"><button type="button" data-open="${r.id}">${esc(r.display_filename)}</button><p>${esc(r.processing_status)} · ${esc(r.category)} · ${esc(r.source_type)} · ${esc(r.created_at)}${r.synthetic_demo ? " · SYNTHETIC DEMO" : ""}</p>${r.duplicate_of ? '<p class="muted">Duplicate bytes; separate upload history retained.</p>' : ""}${r.last_error ? `<p class="intake-conflict">${esc(r.last_error)}</p>` : ""}</article>`,
        )
        .join("") || "<p>No evidence matches this filter.</p>";
    if (S.selected && !S.dirty) await detail(S.selected, false);
  }
  async function detail(id, scroll = true) {
    const data = await api("/api/evidence/" + id + "/processing-status");
    S.selected = id;
    const r = data.intake,
      ev = data.evidence,
      raw = r.raw_result,
      fields = raw.fields || [],
      resolved = r.resolution || {},
      prefix = "/api/evidence/" + r.id;
    const source =
      r.media_type === "application/pdf"
        ? `<iframe title="Original PDF" class="intake-source" src="${prefix}/original"></iframe>`
        : r.media_type.startsWith("image/")
          ? `<img class="intake-source" alt="Original evidence" src="${prefix}/original">`
          : r.media_type.startsWith("video/")
            ? `<video controls class="intake-source" src="${prefix}/original"></video>`
            : r.media_type.startsWith("audio/")
              ? `<audio controls src="${prefix}/original"></audio>`
              : "";
    const frameLinks = (raw.pages || [])
      .filter((p) => p.frame)
      .map(
        (p) =>
          `<button type="button" data-frame="${p.page}" data-id="${id}">Frame at ${p.timestamp}s</button>`,
      )
      .join("");
    $("#detail").innerHTML =
      `<h2>${esc(r.display_filename)}</h2><p>${esc(r.processing_status)} · ${esc(r.classification_method)} · Apparent category, not authenticity.</p><p class="${resolved.decision === "EXACT_SERIAL_CANDIDATE" ? "muted" : "intake-conflict"}">${esc(resolved.decision || "Processing not completed")} · ${esc(resolved.reason || "")}</p><div class="intake-layout"><div>${source}<a href="${prefix}/original" target="_blank" rel="noopener">Open protected original</a><p class="field-source">Original SHA-256: ${esc(r.content_sha256)}</p>${frameLinks}<div id="frame-preview"></div></div><div><h3>Source-linked extraction</h3><p>Readings are unconfirmed. Confidence states are not probabilities.</p><div class="intake-grid"><table><thead><tr><th>Field</th><th>Observed value and source</th></tr></thead><tbody>${fields.map((f) => `<tr><td>${esc(f.name)}</td><td><mark>${esc(f.value)}</mark><p class="field-source">Page/frame ${f.page}${f.video_timestamp !== null && f.video_timestamp !== undefined ? " · " + f.video_timestamp + "s" : ""} · ${esc(f.method)} · ${esc(f.uncertainty)}</p><details><summary>Source span</summary><p>${esc(f.source_text)}</p><p>Characters ${f.start ?? "code"}–${f.end ?? "code"}; coordinates ${f.bounding_box ? "available" : "not estimated"}.</p></details></td></tr>`).join("")}</tbody></table></div><details><summary>Extracted page text</summary>${(raw.pages || []).map((p) => `<h4>Page/frame ${p.page}</h4><pre>${esc(p.text)}</pre>`).join("")}</details><h3>Asset candidates</h3>${(resolved.candidates || []).map((c) => `<p>${esc(c.tag)} · ${esc(c.serial)}<br>Matching: ${esc(c.matching_identifiers.join(", ") || "none")}; conflicting: ${esc(c.conflicting_identifiers.join(", ") || "none")}</p>`).join("") || "<p>Unassigned — source identifiers do not establish a machine.</p>"}</div></div>
 <form id="association"><h3>1. Review asset association</h3><label>Machine<select name="asset_id">${
   option("", "Choose explicitly") +
   assets()
     .map(
       (a) =>
         `<option value="${a.id}" ${a.id === r.assigned_asset_id ? "selected" : ""}>${esc(a.tag + " · " + a.serial)}</option>`,
     )
     .join("")
 }</select></label><label class="check"><input name="checked_original" type="checkbox">I inspected the original.</label><label class="check"><input name="acknowledge_conflicts" type="checkbox">I reviewed ambiguous/conflicting identifiers and explain the override below.</label><label>Reason<input name="reason" required></label>${["confirm", "reject", "unassign"].map((a) => `<button type="submit" value="${a}" data-write>${a}</button>`).join("")}</form>
 ${ev && r.processing_status === "linked" ? `<form id="accept-document"><h3>2. Review the document and extracted facts</h3><p>Asset association alone does not accept evidence or prove commissioning.</p><label>Reviewed category<select name="category">${categories.map((c) => `<option value="${c}" ${c === r.category ? "selected" : ""}>${esc(c.replaceAll("_", " "))}</option>`).join("")}</select></label><label>Working facts — edit against the original, never fill unknowns from expectations<textarea name="facts" rows="8">${esc(JSON.stringify(ev.confirmed ? ev.facts : data.proposed_facts, null, 2))}</textarea></label><label class="check"><input name="checked_original" type="checkbox" required>I checked the actual source and every fact I am accepting.</label><label>Review reason<input name="reason" required></label><button data-write type="submit">Accept reviewed facts</button></form>` : ""}
 ${
   ev?.confirmed && r.assigned_asset_id
     ? `<form id="claim-link"><h3>3. Propose a claim link, then reconcile</h3><label>Claim<select name="claim_id">${visit()
         .claims.filter((c) => c.asset_id === r.assigned_asset_id)
         .map((c) => option(c.id, c.kind))
         .join(
           "",
         )}</select></label><label>Relationship<select name="relation"><option value="supports">Supports</option><option value="contradicts">Contradicts</option><option value="context">Context only</option></select></label><label>Source page/region or timestamp<input name="locator" required></label><label>Reason<input name="reason" required></label><button type="submit" data-write>Save claim link</button></form><p><a href="/app#/assessment">Open existing reconciliation and review</a> · <a href="/app#/followups">Follow-up workflow</a></p>`
     : ""
 }
 ${
   r.media_type.startsWith("audio/") && !r.audio_recording_id
     ? `<form id="acoustic"><h3>Hand off to the existing audio module</h3><label>Confirmed physical machine<select name="physical_asset_id">${
         option("", "Choose a current accepted binding") +
         S.snapshot.asset_bindings
           .filter((b) => b.active && b.inspection_id === r.inspection_id)
           .map((b) =>
             option(
               b.physical_asset_id,
               S.snapshot.physical_assets.find(
                 (p) => p.id === b.physical_asset_id,
               )?.label || b.physical_asset_id,
             ),
           )
           .join("")
       }</select></label><label>Reason<input name="reason" required></label><button type="submit" data-write>Attach original to audio memory</button></form>`
     : ""
 }
 <button id="retry-process" type="button" data-write>Retry/reprocess saved original</button><p class="muted">Reprocessing revokes prior source acceptance. Prior versions remain in audit history.</p>`;
    $("#detail").hidden = false;
    $("#detail").dataset.version = r.version;
    $("#detail").dataset.evVersion = ev?.version || "";
    $("#detail").dataset.evidence = r.evidence_id || "";
    const processing = ["queued", "processing"].includes(r.processing_status);
    $("#association").hidden = processing;
    $("#retry-process").hidden = processing;
    document
      .querySelectorAll("[data-write]")
      .forEach((b) => (b.disabled = !analyst));
    if (scroll)
      $("#detail").scrollIntoView({ behavior: "smooth", block: "start" });
  }
  document.addEventListener("submit", (event) => {
    event.preventDefault();
    const f = event.target,
      v = Object.fromEntries(new FormData(f));
    action(async () => {
      if (f.id === "upload") {
        if (!S.pending) {
          const file = f.elements.file.files[0];
          const body = new FormData();
          body.set("file", file);
          body.set(
            "metadata",
            JSON.stringify({
              case_id: $("#case").value,
              inspection_id: $("#visit").value,
              asset_hint: $("#hint").value || null,
              captured_at: new Date(v.captured_at).toISOString(),
              source_type: v.source_type,
              synthetic_demo: !!v.synthetic_demo,
              recording_authorized: !!v.recording_authorized,
              audio_purpose: v.audio_purpose || null,
              capture_conditions: v.capture_conditions,
              reason: v.reason,
            }),
          );
          S.pending = { body, key: crypto.randomUUID() };
        }
        const r = await api(
          "/api/evidence/intake",
          "POST",
          S.pending.body,
          S.pending.key,
        );
        S.pending = null;
        note(
          "Original saved. Processing is queued; association and acceptance require review.",
        );
        await refresh();
        await detail(r.id);
        return;
      }
      const id = S.selected,
        prefix = "/api/evidence/" + id,
        version = Number($("#detail").dataset.version);
      if (f.id === "association")
        await api(prefix + "/confirm-asset", "POST", {
          ...v,
          version,
          action: event.submitter.value,
          asset_id: v.asset_id || null,
          checked_original: !!v.checked_original,
          acknowledge_conflicts: !!v.acknowledge_conflicts,
        });
      if (f.id === "accept-document")
        await api(prefix + "/review-document", "POST", {
          version,
          evidence_version: Number($("#detail").dataset.evVersion),
          category: v.category,
          facts: JSON.parse(v.facts),
          checked_original: !!v.checked_original,
          reason: v.reason,
        });
      if (f.id === "claim-link")
        await api(
          "/api/v1/inspections/" + $("#visit").value + "/evidence-links",
          "POST",
          { ...v, evidence_id: $("#detail").dataset.evidence },
        );
      if (f.id === "acoustic")
        await api(
          prefix +
            "/attach-acoustic?physical_asset_id=" +
            encodeURIComponent(v.physical_asset_id),
          "POST",
          { version, reason: v.reason },
        );
      S.dirty = false;
      await refresh();
      note("Review saved. Existing reconciliation remains authoritative.");
    });
  });
  document.addEventListener("click", (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    if (b.dataset.open) action(() => detail(b.dataset.open));
    if (b.id === "refresh") action(refresh);
    if (b.dataset.frame)
      $("#frame-preview").innerHTML =
        `<img class="intake-source" alt="Selected source frame" src="/api/evidence/${b.dataset.id}/frames/${b.dataset.frame}">`;
    if (b.id === "retry-process")
      action(async () => {
        await api("/api/evidence/" + S.selected + "/retry", "POST", {
          version: Number($("#detail").dataset.version),
          reason: "Analyst requested processing of retained original",
        });
        await detail(S.selected, false);
        note("Processing queued; original bytes remain unchanged.");
      });
  });
  document.addEventListener("input", (e) => {
    if (e.target.closest("#detail form")) S.dirty = true;
  });
  $("#case").onchange = () => action(loadCase);
  $("#visit").onchange = () => action(loadVisit);
  $("#filter").onchange = () => action(refresh);
  let searchTimer;
  $("#search").oninput = () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => action(refresh), 300);
  };
  setInterval(() => {
    if (
      !S.busy &&
      !document.querySelector(
        "#detail input:focus,#detail textarea:focus,#detail select:focus",
      ) &&
      S.rows.some((r) => ["queued", "processing"].includes(r.processing_status))
    )
      action(refresh);
  }, 2000);
  window.addEventListener("beforeunload", (e) => {
    if (S.pending || S.dirty) {
      e.preventDefault();
      e.returnValue = "";
    }
  });
  action(async () => {
    S.cases = await api("/api/v1/cases");
    $("#case").innerHTML = S.cases
      .map((c) => option(c.id, c.company + " · " + c.site))
      .join("");
    $("#upload input[name=captured_at]").value = new Date(
      Date.now() - new Date().getTimezoneOffset() * 60000,
    )
      .toISOString()
      .slice(0, 16);
    if (S.cases.length) await loadCase();
    note(
      S.cases.length
        ? "Connected. Select a visit and upload evidence."
        : "Create or select a case in the main workspace first.",
    );
  });
})();
