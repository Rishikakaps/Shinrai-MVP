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
        .map((a) => option(a.id, a.tag + " · " + (a.serial || "Serial unknown")))
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
  const registryFields = ["tag","manufacturer","model","serial","site","rated_power_kw","horse_power","rated_voltage_v","rated_speed_rpm","invoice_ref","payment_ref"];
  const registryLabels = ["Internal tag","Manufacturer","Model","Serial (blank if unknown)","Site association","Power kW","Horsepower","Voltage","Speed RPM","Invoice reference (if known)","Payment reference (if known)"];
  function registryProposal(r) {
    if (!analyst || !r.evidence_id || r.media_type.startsWith("audio/") || r.media_type.startsWith("video/") || ["queued","processing"].includes(r.processing_status)) return "";
    if (r.metadata.registry_proposal) return `<p>Registry proposal saved: ${esc(r.metadata.registry_proposal.action)}. <a href="/app#/overview">Open editable Overview records</a>.</p>`;
    const names={model:"model_number",serial:"serial_number"}, raw=r.raw_result.fields||[];
    const values=Object.fromEntries(registryFields.map(k=>{const readings=[...new Set(raw.filter(f=>f.name===(names[k]||k)).map(f=>f.value))];return [k,readings.length===1?readings[0]:""];}));
    values.site ||= visit()?.inspection.site||"";
    return `<details class="record"><summary>Create or update a registry record from this scan</summary><p>Review each value against the original. Saving changes the operational Overview and resets declaration confirmations. This does not accept evidence or verify claims.</p><form id="registry-proposal"><label>Action<select name="action"><option value="create">Propose a new record</option><option value="update">Update an existing record</option></select></label><label>Existing target (for update)<select id="registry-target" name="target_id">${option("","Choose a record")+assets().map(a=>option(a.id,a.tag+" · "+(a.serial||"Serial unknown"))).join("")}</select></label>${registryFields.map((k,n)=>`<label>${registryLabels[n]}<input name="registry_${k}" value="${esc(values[k])}" maxlength="200" ${["tag","model","site"].includes(k)?"required":""}></label>`).join("")}<label class="check"><input type="checkbox" name="checked_original" required>I checked the source and every proposed field.</label><label class="check"><input type="checkbox" name="acknowledge_conflicts">I reviewed the new/unresolved/conflicting identity; my reason explains the decision.</label><label>Reason<input name="reason" required maxlength="4000"></label><button data-write type="submit">Save reviewed registry proposal</button></form></details>`;
  }
  function adjustment(r) {
    if (!analyst || !r.media_type.startsWith("image/") && !r.raw_result.pages?.some(p=>p.frame)) return "";
    return `<details class="record"><summary>Crop / rotate / improve contrast</summary><form id="adjust-image"><p>Originals stay unchanged. Crop uses pixel bounds: left, top, right, bottom. Leave all blank to retain the full image.</p>${r.media_type.startsWith("video/")?`<label>Source frame<select name="frame_number">${r.raw_result.pages.filter(p=>p.frame).map(p=>option(p.page,"Timestamp "+p.timestamp+"s")).join("")}</select></label>`:""}${["left","top","right","bottom"].map(k=>`<label>${k}<input type="number" name="${k}" min="0"></label>`).join("")}<label>Clockwise rotation<select name="rotate">${[0,90,180,270].map(n=>option(n,n+"°")).join("")}</select></label><label class="check"><input type="checkbox" name="autocontrast">Improve contrast</label><label>Reason<input name="reason" required></label><button type="submit" data-write>Save adjusted image and queue OCR</button></form></details>`;
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
         `<option value="${a.id}" ${a.id === r.assigned_asset_id ? "selected" : ""}>${esc(a.tag + " · " + (a.serial || "Serial unknown"))}</option>`,
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
    if(r.metadata.parent_intake_id) $("#detail").insertAdjacentHTML("afterbegin", `<p class="field-source">Derived from <a href="/api/evidence/${esc(r.metadata.parent_intake_id)}/original" target="_blank" rel="noopener">parent original</a> · timestamp ${esc(r.metadata.source_timestamp_seconds ?? "photo")}s · source frame SHA-256 ${esc(r.metadata.source_frame_sha256)} · ${esc(JSON.stringify(r.metadata.adjustment))}</p>`);
    $("#detail").insertAdjacentHTML("beforeend", adjustment(r) + registryProposal(r));
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
      if (f.id === "registry-proposal") {
        const target=assets().find(a=>a.id===v.target_id);
        const fields={...Object.fromEntries(registryFields.map(k=>[k,v["registry_"+k]||null])),provenance:target?.provenance||{origin:"reviewed_scan",intake_id:S.selected},reason:v.reason};
        await api(prefix+"/registry-proposal","POST",{version,action:v.action,target_id:v.target_id||null,target_version:target?.version||null,fields,checked_original:!!v.checked_original,acknowledge_conflicts:!!v.acknowledge_conflicts,reason:v.reason});
        S.snapshot=await api("/api/v1/cases/"+$("#case").value+"/export");
      }
      if (f.id === "adjust-image") {
        const bounds=[v.left,v.top,v.right,v.bottom];
        if(bounds.some(Boolean)&&!bounds.every(x=>x!==""))throw Error("Enter all four crop bounds.");
        const child=await api(prefix+"/adjust-image","POST",{version,frame_number:v.frame_number?Number(v.frame_number):null,crop:bounds.some(Boolean)?bounds.map(Number):null,rotate:Number(v.rotate),autocontrast:!!v.autocontrast,reason:v.reason});
        S.selected=child.id;
      }
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
  document.addEventListener("change",e=>{
    if(e.target.id==="registry-target"){
      const a=assets().find(a=>a.id===e.target.value);
      if(a){for(const k of registryFields)e.target.form.elements["registry_"+k].value=a[k]||"";e.target.form.elements.action.value="update";}
    }
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
    const savedVisit=localStorage.getItem("cdi.inspection");
    if(savedVisit){for(const c of S.cases){const visits=await api("/api/v1/cases/"+c.id+"/inspections");if(visits.some(i=>i.id===savedVisit)){$("#case").value=c.id;break;}}}
    if (S.cases.length) {await loadCase();if([...$("#visit").options].some(o=>o.value===savedVisit)){$("#visit").value=savedVisit;await loadVisit();}}
    note(
      S.cases.length
        ? "Connected. Select a visit and upload evidence."
        : "Create or select a case in the main workspace first.",
    );
  });
})();
