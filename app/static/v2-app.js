/* V2 uses the original application's authenticated client and review workflow. */
(() => {
  "use strict";
  const U = window.IntegrityUI;
  if (!U) return;
  const $ = (s, r = document) => r.querySelector(s),
    $$ = (s, r = document) => [...r.querySelectorAll(s)];
  const esc = (v) =>
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
    );
  const title = (v) => String(v ?? "").replaceAll("_", " "),
    uid = () => crypto.randomUUID(),
    analyst = U.analyst;
  const S = {
    cases: [],
    snap: null,
    caps: null,
    physical: null,
    project: null,
    segment: null,
    interview: null,
    task: null,
    recording: false,
    stream: null,
    recorder: null,
    timer: null,
    preview: null,
    clips: [],
    camera: null,
    mediaRequest: null,
    scan: null,
    scanFile: null,
    analysis: null,
    pendingCandidate: null,
    queue: Promise.resolve(),
    pending: 0,
    captureBusy: false,
    busy: false,
    dirty: false,
    lastAnalysis: 0,
    chat: [],
    operationKeys: new Map(),
  };
  const root = () => "/api/v1/cases/" + S.snap.case.id;
  const visit = () => U.state.iid;
  const asset = () => U.state.report?.assets.find((a) => a.id === U.state.aid);
  const physical = () =>
    S.snap?.physical_assets.find((a) => a.id === S.physical);
  const project = () => S.snap?.investments.find((p) => p.id === S.project);
  const binding = () =>
    S.snap?.asset_bindings.find(
      (b) =>
        b.active &&
        b.inspection_id === visit() &&
        b.local_asset_id === U.state.aid,
    );
  const canNavigate = () => !S.recording && !S.pending && !S.camera && !S.mediaRequest;
  const reason = "Analyst saved change through the connected V2 interface";
  const source = (quote) => ({
    kind: "analyst_observation",
    attribution: document.body.dataset.actor,
    quote,
  });
  const val = (name, label, value = "", extra = "") =>
    `<label class="v2-field">${esc(label)}<input name="${name}" value="${esc(value)}" ${extra}></label>`;
  const text = (name, label, value = "", extra = "") =>
    `<label class="v2-field v2-wide">${esc(label)}<textarea name="${name}" ${extra}>${esc(value)}</textarea></label>`;
  const opts = (rows, value, label = (r) => r.name) =>
    rows
      .map(
        (r) =>
          `<option value="${esc(r.id)}" ${r.id === value ? "selected" : ""}>${esc(label(r))}</option>`,
      )
      .join("");
  const select = (name, label, items, value) =>
    `<label class="v2-field">${esc(label)}<select name="${name}">${items.map(([id, l]) => `<option value="${esc(id)}" ${id === value ? "selected" : ""}>${esc(l)}</option>`).join("")}</select></label>`;
  const btn = (name, label, extra = "", cls = "") =>
    `<button type="button" data-v2="${name}" ${extra} class="${cls}">${label}</button>`;
  const form = (id, body) =>
    `<form data-v2-form="${id}" class="v2-form">${body}</form>`;
  function formKey(f) {
    const signature = JSON.stringify([...new FormData(f)]);
    if (f.dataset.requestSignature !== signature) {
      f.dataset.requestSignature = signature;
      f.dataset.requestKey = uid();
    }
    return f.dataset.requestKey;
  }
  const save = (label) =>
    `<div class="section-actions"><button type="submit" class="primary" ${!analyst ? "disabled" : ""}>${label}</button></div>`;
  const head = (name, sub, tools = "") =>
    `<header class="page-header"><div><h1>${name}</h1><p class="muted">${sub}</p></div><div class="tools">${tools}</div></header>`;
  const ctx = () =>
    `<div class="v2-context"><label>Machine <select id="v2-machine" ${!canNavigate() ? "disabled" : ""}>${opts(U.state.report.assets, U.state.aid, (a) => a.tag + " · " + (a.serial || "serial unknown"))}</select></label><span class="status ${S.physical ? "supported" : "unresolved"}">${S.physical ? "Identity confirmed" : "Identity not confirmed"}</span><label>Investment <select id="v2-project" ${!canNavigate() ? "disabled" : ""}><option value="">No project selected</option>${opts(S.snap?.investments.filter((p) => p.asset_links.some((l) => l.physical_asset_id === S.physical)) || [], S.project, (p) => p.title)}</select></label></div>`;
  async function load() {
    S.cases = await U.api("/api/v1/cases");
    S.caps = await U.api("/api/v1/capabilities");
    let found = null;
    for (const c of S.cases) {
      const members = await U.api("/api/v1/cases/" + c.id + "/inspections");
      if (members.some((v) => v.id === visit())) {
        found = c;
        break;
      }
    }
    const old = S.snap?.case.id;
    S.snap = found
      ? await U.api("/api/v1/cases/" + found.id + "/export")
      : null;
    S.physical = binding()?.physical_asset_id || null;
    S.chat =
      S.snap && analyst
        ? (await U.api("/api/v1/cases/" + S.snap.case.id + "/chat"))
            .filter((c) => c.physical_asset_id === S.physical)
            .slice(-12)
        : [];
    if (old !== S.snap?.case.id) {
      S.interview = null;
      S.segment = null;
      S.analysis = null;
    }
    if (
      !S.snap?.investments.some(
        (p) =>
          p.id === S.project &&
          p.asset_links.some((l) => l.physical_asset_id === S.physical),
      )
    )
      S.project =
        S.snap?.investments.find((p) =>
          p.asset_links.some((l) => l.physical_asset_id === S.physical),
        )?.id || null;
  }
  async function refresh() {
    await U.refresh();
  }
  async function act(fn) {
    if (S.busy) return;
    S.busy = true;
    document.body.classList.add("v2-saving");
    try {
      await fn();
      S.dirty = false;
      U.state.dirty = false;
    } catch (e) {
      U.note(e.message || "Save failed. Your entries are retained.", true);
    } finally {
      S.busy = false;
      document.body.classList.remove("v2-saving");
    }
  }
  function requireIdentity() {
    if (S.scan && S.scan.identity_result !== "matches_declared_serial")
      throw Error(
        "The latest label is unreadable or differs from this machine. Rescan or review the identity evidence before capture.",
      );
    if (!S.physical)
      throw Error(
        "Confirm machine identity against accepted evidence before capturing or assigning records.",
      );
  }
  function setup() {
    return (
      head(
        "Keep the same history across visits",
        "Create a company/site case for this inspection.",
      ) +
      (!analyst
        ? "<p>Ask an analyst to enroll this visit in a case.</p>"
        : form(
            "case",
            `<section class="work-sheet"><h2>Use this inspection as the first visit</h2><div class="v2-grid">${val("company", "Company", "Synthetic demonstration company", 'required maxlength="200"')}${val("site", "Site", U.state.report?.inspection.site || "Plant A", 'required maxlength="200"')}</div>${save("Create case")}</section>`,
          ) +
          `<details class="subdisclosure"><summary>Add this visit to an existing case</summary>${form(
            "enrol",
            select(
              "case_id",
              "Case",
              S.cases.map((c) => [c.id, c.company + " / " + c.site]),
            ) + save("Enroll current visit"),
          )}</details>`)
    );
  }
  function identity() {
    const a = asset();
    if (!a) return "<p>Select a machine first.</p>";
    const ev = U.state.report.evidence.filter(
      (e) =>
        e.confirmed &&
        !["management_statement", "financial_statement"].includes(e.kind) &&
        e.facts.serial?.trim().toLowerCase() ===
          (a.serial || "").trim().toLowerCase() &&
        e.facts.model === a.model &&
        e.facts.site === a.site,
    );
    return `<details class="work-sheet" ${!S.physical ? "open" : ""}><summary>${S.physical ? "✓ Confirmed identity · " + esc(a.tag) : "1 · Confirm machine identity"}</summary><p>Match the serial, model and site against accepted evidence. Selecting a machine alone does not confirm it.</p>${
      S.physical
        ? `<p>${esc(physical().serial)} · ${esc(physical().model)}</p>`
        : analyst
          ? form(
              "identity",
              select(
                "identity_evidence_id",
                "Accepted identity evidence",
                ev.map((e) => [e.id, e.filename]),
              ) +
                val(
                  "identity_locator",
                  "Where the identifier is shown",
                  "Serial/model/site fields",
                  'required maxlength="200"',
                ) +
                `<label class="check-label"><input name="checked" type="checkbox" required>I checked the original and confirm this machine’s identity.</label>` +
                save("Confirm physical machine"),
            )
          : "<p>Identity confirmation is restricted to analysts.</p>"
    }${!ev.length && !S.physical ? '<p class="banner">No matching accepted identity source is available. <a href="#/evidence">Review an original in Evidence</a>, or capture a clearer label below.</p>' : ""}</details>`;
  }
  function overview() {
    const snap = S.snap;
    const rows = U.state.report.assets
      .map((a) => {
        const bind = snap.asset_bindings.find(
            (b) =>
              b.active &&
              b.inspection_id === visit() &&
              b.local_asset_id === a.id,
          ),
          p = snap.investments.find((p) =>
            p.asset_links.some(
              (l) => l.physical_asset_id === bind?.physical_asset_id,
            ),
          ),
          gaps = U.state.report.claims
            .filter((c) => c.asset_id === a.id)
            .filter(
              (c) =>
                !U.state.report.findings.some(
                  (f) =>
                    f.claim_id === c.id && f.computed_status === "supported",
                ),
            );
        return `<tr><td><strong>${esc(a.tag)}</strong><br><small>${esc(a.serial)}</small></td><td>${bind ? "✓ Confirmed" : "Needs confirmation"}</td><td>${U.state.report.reconciliation_current ? (gaps.length ? esc(gaps.map((c) => c.kind).join(", ")) + " unresolved" : "Supported") : "Reconcile first"}</td><td>${esc(p?.title || "No proposal")}</td><td>${btn("open-machine", "Open inspection →", `data-id="${a.id}"`)}</td></tr>`;
      })
      .join("");
    return (
      head(
        "A clear view of " + esc(snap.case.site),
        "Multiple visits. One machine history. Review what still needs evidence.",
        analyst ? btn("repeat-visit", "Prepare repeat trial visit") : "",
      ) +
      `<p>${esc(snap.case.company)} · ${snap.v1_inspections.length} visits · ${snap.investments.length} investment proposals · Synthetic demo</p><div class="table-region"><div class="table-scroll"><table><thead><tr><th>Machine</th><th>Identity</th><th>Deployment gaps</th><th>Investment</th><th>Next action</th></tr></thead><tbody>${rows}</tbody></table></div></div>${ctx()}${history()}<details class="subdisclosure"><summary>Original claims and declaration setup</summary>${U.legacy.overview()}</details>`
    );
  }
  function history() {
    const previous = S.snap.v1_inspections.filter(
      (v) => v.inspection.id !== visit(),
    );
    const tasks = S.snap.follow_ups.filter(
      (f) =>
        f.details.physical_asset_id === S.physical &&
        f.details.workflow_status !== "closed",
    );
    return `<section class="work-sheet"><h2>Since the previous visit</h2>${!S.physical ? "<p>Confirm identity to retrieve this machine’s history.</p>" : `<p>${previous.length ? "Earlier visits are retained; select one in the visit picker to inspect its original findings." : "This is the first visit for this case."}</p><p>${tasks.length} open evidence requests · ${S.snap.audio.filter((a) => a.physical_asset_id === S.physical).length} saved recordings</p>${project() ? `<p><strong>${esc(project().title)}</strong> · ${esc(project().stage)} · Reported proposal</p><p>${esc(project().rationale)}</p>` : "<p>No investment proposal is linked yet.</p>"}`}</section>`;
  }
  function scan() {
    return `<section class="work-sheet"><h2>Read the machine label</h2><p>Capture a barcode and printed serial. A scan proposes identifiers; review still determines identity.</p><p><a href="/api/v1/inspections/${visit()}/demo-label/${U.state.aid}" target="_blank" rel="noopener">Open synthetic trial label on the laptop</a> · Prepared Plant A trials only; this is not independent evidence.</p>${analyst ? `<div class="section-actions">${btn("camera", "Open phone camera")}${btn("camera-stop", "Close camera")}</div><video id="v2-camera" class="v2-camera" playsinline muted autoplay hidden></video><button type="button" data-v2="capture-photo" id="v2-capture-photo" hidden>Capture this label</button><label class="v2-field">Or take/upload a label photo<input id="v2-label-file" type="file" accept="image/jpeg,image/png" capture="environment"></label><p class="small">Use HTTPS on the phone. Keep the label centered, still and well-lit. Originals are saved unaccepted.</p>` : ""}<div id="v2-scan-result">${scanResult()}</div></section>`;
  }
  function scanResult() {
    if (!S.scan)
      return '<p class="muted">No label has been scanned in this session.</p>';
    const x = S.scan;
    return `<p class="banner">${esc(title(x.identity_result))}. ${esc(x.next_action)}</p><p>Quality: ${esc(x.quality_flags.map(title).join(", ") || "No readability warning")}</p><p>Decoded candidates: ${esc(x.serial_suggestions.join(" · ") || "None — rescan or flag unclear")}</p><details><summary>Read OCR text</summary><pre>${esc(x.ocr_text || "No text read")}</pre></details><p><a href="#/evidence" data-v2="review-scan">Review the saved original and correct fields →</a></p>`;
  }
  function segmentPanel() {
    const segments = S.snap.segments.filter((s) =>
      S.snap.interviews.some(
        (i) => i.id === s.interview_id && i.physical_asset_id === S.physical,
      ),
    );
    const seg = S.segment || segments.at(-1);
    if (seg && !S.segment) S.segment = seg;
    return `<div class="v2-interview"><div><h3>Transcript and translation</h3><div id="v2-transcript-view">${seg ? `<p class="small">${esc(title(seg.mode))} · ${esc(seg.provider || "Human-entered")} · Review before using</p><p lang="${esc(seg.language)}">${esc(seg.text)}</p><p>${esc(seg.english_translation || "No translation saved.")}</p>` : "<p>No transcript yet. Record speech or save manual source text.</p>"}</div>${
      analyst
        ? form(
            "segment",
            text(
              "text",
              "Original source text",
              seg?.text || "",
              'required maxlength="4000"',
            ) +
              select(
                "language",
                "Language",
                [
                  ["ja", "Japanese"],
                  ["en", "English"],
                ],
                seg?.language || "ja",
              ) +
              text(
                "english_translation",
                "English translation (if manually corrected)",
                seg?.english_translation || "",
              ) +
              `<label class="check-label"><input name="correct_existing" type="checkbox" ${seg ? "checked" : ""}>Correct the selected saved segment, preserving its audit history</label>` +
              val(
                "reason",
                "Reason",
                "Review and correct interview text",
                "required",
              ) +
              save("Save source text"),
          )
        : ""
    }<div class="section-actions">${analyst ? btn("translate", "Translate saved Japanese text") + btn("analyse", "Suggest contextual questions", "", "primary") : ""}</div><label class="check-label"><input id="v2-fallback" type="checkbox">Allow explicitly labelled rules fallback if Google is unavailable</label><details class="subdisclosure"><summary>Saved transcript history (${segments.length})</summary>${segments.map((s) => `<p>${btn("select-segment", esc(s.text.slice(0, 95)), `data-id="${s.id}"`)} <small>${esc(s.created_at)}</small></p>`).join("")}</details></div><aside id="v2-questions">${questions()}</aside></div><div id="v2-candidates">${candidates()}</div>`;
  }
  function questions() {
    const a =
      S.analysis ||
      S.snap?.analyses.filter((a) => a.segment_id === S.segment?.id).at(-1);
    if (!a)
      return "<h3>Suggested next question</h3><p>Save a source, then generate questions from its context.</p>";
    S.analysis = a;
    return `<h3>Suggested next questions</h3><p class="small">${esc(a.provider)} · ${esc(a.notices.join(" "))}</p>${a.questions.map((q, i) => `<section class="v2-question"><h3>${esc(q.question)}</h3><p>${esc(q.why)}</p><p class="small">Source: “${esc(q.source_quote)}”</p><p>Requested evidence: ${esc(q.proposed_evidence)}</p><p>${esc(q.status)}</p>${analyst ? btn("question", "Asked", `data-index="${i}" data-status="asked"`) + btn("question", "Dismiss", `data-index="${i}" data-status="dismissed"`) : ""}</section>`).join("") || "<p>No new questions; earlier handled topics are retained.</p>"}`;
  }
  function candidates() {
    return (S.snap?.candidates || [])
      .filter((c) => c.segment_id === S.segment?.id)
      .map(
        (c) =>
          `<details class="work-sheet" ${c.review_status === "pending" ? "open" : ""}><summary>${esc(title(c.payload.kind))} · ${esc(c.review_status)}</summary><p>Source: “${esc(c.payload.quote)}”</p>${c.review_status === "pending" && analyst ? form("candidate", `<input type="hidden" name="id" value="${c.id}">${text("text", "Proposed statement", c.payload.text, "required")}<div class="v2-grid">${val("value", "Value", c.payload.value ?? "", 'type="number" min="0" step="any"')}${val("unit", "Unit", c.payload.unit || "")}${val("currency", "Currency", c.payload.currency || "")}${val("due_date", "Due date if confirmed", c.payload.due_date || "", 'type="date"')}</div><label class="check-label"><input name="confirmed_source" type="checkbox" required>I checked the original source, values and uncertainty.</label><p>Acceptance records a report/forecast, not independent verification.</p>${save(c.payload.kind === "follow_up" ? "Review follow-up details" : "Accept reviewed proposal")}${btn("reject-candidate", "Reject proposal", `data-id="${c.id}"`)}`) : `<p>${esc(c.payload.text)}</p>`}</details>`,
      )
      .join("");
  }
  function capture() {
    return `<section class="work-sheet"><h2>Interview and capture</h2><p id="v2-provider">Google Gemini: ${S.caps.ai_configured ? "key configured; live calls may still fail" : "key not configured"} · Audio decoder ${S.caps.audio_decode_available ? "available" : "unavailable"}</p><div class="v2-grid">${select(
      "capture_type",
      "Recording purpose",
      [
        ["interview_speech", "Interview speech"],
        ["machine_acoustic", "Machine sound"],
        ["inspector_voice_note", "Analyst voice note"],
      ],
      "interview_speech",
    )}${select(
      "audio_language",
      "Language",
      [
        ["ja", "Japanese"],
        ["en", "English"],
      ],
      "ja",
    )}${val("speaker", "Speaker label", "Speaker 1 — unconfirmed", 'maxlength="200"')}${val("operating_mode", "Operating mode", "unknown", 'maxlength="200"')}</div><label class="check-label"><input id="v2-speaker-confirmed" type="checkbox">Speaker attribution checked</label><label class="check-label"><input id="v2-consent" type="checkbox">Recording is authorized and speakers have been informed.</label><label class="check-label"><input id="v2-synthetic" type="checkbox" checked>This is a synthetic demonstration recording.</label><label class="check-label"><input id="v2-share" type="checkbox">Share this synthetic recording with judges</label><label class="check-label"><input id="v2-incremental" type="checkbox">Process interview speech in separate short clips while recording</label><div class="section-actions">${analyst ? btn("record", "Start recording", !S.physical || (S.scan && S.scan.identity_result !== "matches_declared_serial") ? "disabled" : "", "primary") + btn("stop", "Stop recording", !S.recording ? "disabled" : "") : ""}</div><p id="v2-record-status" role="status">${S.recording ? "Recording — originals save after each completed clip." : "Idle. Permission is requested only when you start recording."}</p><audio id="v2-audio-preview" controls hidden></audio><div id="v2-unsaved">${unsaved()}</div>${analyst ? `<label class="v2-field">Or upload a saved clip<input id="v2-audio-file" type="file" accept="audio/wav,audio/webm,audio/mp4,.wav,.webm,.m4a,.mp4"></label>` : ""}${segmentPanel()}${chatPanel()}</section>`;
  }
  function site() {
    return (
      head(
        "Inspect " + esc(asset()?.tag || "a machine"),
        "Capture the source. Review what was said. Ask what is still missing.",
        `<a href="#/wearable">Wearable preview →</a>`,
      ) +
      ctx() +
      identity() +
      scan() +
      capture() +
      recordings() +
      history() +
      `<details class="subdisclosure"><summary>Record direct observations and link them to claims</summary>${U.legacy.siteView()}</details>`
    );
  }
  function chatPanel() {
    return !analyst
      ? ""
      : `<section class="v2-chat"><h3>Ask the case copilot</h3><p>Answers use saved case records. They cannot change findings or approve funding.</p>${form("chat", text("question", "Your question", "", 'required maxlength="4000" placeholder="What evidence is missing before this machine can be commissioned?"') + save("Ask Google Gemini"))}${S.chat.map((c) => `<article class="v2-question"><strong>${esc(c.question)}</strong><p>${esc(c.answer)}</p><p class="small">Sources: ${c.sources.map((s) => esc(s.kind) + " · " + esc(s.id)).join("; ") || "No supporting source cited"} · ${esc(c.provider)}</p></article>`).join("")}</section>`;
  }
  function recordings() {
    const list = S.snap.audio.filter((a) => a.physical_asset_id === S.physical);
    const clips = list.filter((a) => a.capture_type === "machine_acoustic");
    return `<section class="work-sheet"><h2>Saved recordings</h2>${list.map((a) => `<article class="v2-audio"><strong>${esc(title(a.capture_type))}</strong> · ${a.duration_seconds}s · ${esc(a.created_at)}<p>${esc(a.note)} ${esc(a.quality_flags.join(", "))}</p><audio controls preload="none" src="${root()}/audio/${a.id}/original"></audio>${analyst && a.capture_type !== "machine_acoustic" ? btn("transcribe", "Transcribe / retry speech processing", `data-id="${a.id}"`) : ""}</article>`).join("") || "<p>No recording is saved for this machine.</p>"}${
      clips.length >= 2
        ? form(
            "compare",
            select(
              "first_id",
              "First machine clip",
              clips.map((a) => [a.id, a.filename + " · " + a.created_at]),
            ) +
              select(
                "second_id",
                "Second machine clip",
                clips.map((a) => [a.id, a.filename + " · " + a.created_at]),
                clips.at(-1).id,
              ) +
              save("Compare recorded signals"),
          )
        : '<p class="small">Two machine clips are needed for a descriptive comparison. Sound does not establish commissioning.</p>'
    }${S.snap.comparisons
      .filter((c) => clips.some((a) => a.id === c.first_id))
      .map(
        (c) =>
          `<p class="banner">${esc(c.conclusion)} ${esc(c.warnings.join("; "))}</p>`,
      )
      .join("")}</section>`;
  }
  function projectForm(p = null) {
    return form(
      "project",
      `<input type="hidden" name="id" value="${p?.id || ""}"><div class="v2-grid">${val("title", "Title", p?.title || "", 'required maxlength="200"')}${select(
        "kind",
        "Type",
        ["replacement", "new_purchase", "repair", "upgrade", "expansion"].map(
          (k) => [k, title(k)],
        ),
        p?.kind || "replacement",
      )}${val("proposed_amount", "Proposed amount", p?.proposed_amount || "", 'type="number" min="0" step="0.01"')}${val("currency", "Currency", p?.currency || "JPY", 'maxlength="3"')}${
        p
          ? select(
              "stage",
              "Stage",
              [
                "proposed",
                "evaluating",
                "in_progress",
                "outcome_review",
                "closed",
                "cancelled",
              ].map((x) => [x, title(x)]),
              p.stage,
            )
          : ""
      }</div>${text("rationale", "Reported rationale", p?.rationale || "", 'required maxlength="4000"')}${text("source_quote", "Quoted source", p?.source.quote || "", "required")}${val("attribution", "Who reported it?", p?.source.attribution || "Management representative", "required")}${S.snap.physical_assets
        .map(
          (a) =>
            `<label class="check-label"><input name="linked_assets" type="checkbox" value="${a.id}" ${p?.asset_links.some((l) => l.physical_asset_id === a.id) || (!p && a.id === S.physical) ? "checked" : ""}>${esc(a.label)} · ${esc(a.serial)} ${select(
              "role_" + a.id,
              "Role",
              [
                ["existing", "Existing"],
                ["replacement", "Replacement"],
                ["acquired", "Acquired"],
                ["supporting", "Supporting"],
              ],
              p?.asset_links.find((l) => l.physical_asset_id === a.id)?.role ||
                "existing",
            )}</label>`,
        )
        .join(
          "",
        )}${save(p ? "Save project changes" : "Save reported proposal")}`,
    );
  }
  function targetForm(t = null) {
    return form(
      "target",
      `<input type="hidden" name="id" value="${t?.id || ""}"><div class="v2-grid">${select(
        "metric",
        "Metric",
        [
          "downtime_hours",
          "repair_cost",
          "output_rate",
          "defect_rate",
          "energy_consumption",
        ].map((x) => [x, title(x)]),
        t?.metric || "downtime_hours",
      )}${select(
        "target_type",
        "Target type",
        [
          ["reduction_percent", "Reduction percent"],
          ["increase_percent", "Increase percent"],
          ["absolute", "Absolute value"],
        ],
        t?.target_type || "reduction_percent",
      )}${val("target_value", "Target value", t?.target_value ?? "", 'type="number" min="0" step="any" required')}${val("unit", "Unit", t?.unit || "hours", "required")}${val("currency", "Currency (repair costs)", t?.currency || "")}${val("baseline_value", "Reported baseline, if known", t?.baseline_value ?? "", 'type="number" min="0" step="any"')}${val("baseline_period", "Baseline period definition", t?.baseline_period || "")}${val("due_date", "Absolute deadline, if known", t?.due_date || "", 'type="date"')}${val("relative_months", "Or months after commissioning", t?.relative_months ?? "", 'type="number" min="1" max="120"')}</div>${text("quote", "Exact reported source", t?.source.quote || "", "required")}${val("attribution", "Source attribution", t?.source.attribution || "Management representative", "required")}${save(t ? "Save revised target" : "Save forecast target")}`,
    );
  }
  function outcomeLabel(t) {
    const r = S.snap.investment_reviews
      .filter((r) => r.target_id === t.id)
      .at(-1);
    return !r
      ? "Not measured"
      : r.target_version !== t.version
        ? "Target revised — new review required"
        : title(r.status);
  }
  function sourceWarning(source) {
    const current = S.snap.segments.find((s) => s.id === source?.segment_id);
    return current && current.version !== source.segment_version
      ? '<p class="banner">Source transcript was corrected. Review this saved report/forecast against the newer source before relying on it.</p>'
      : "";
  }
  function investments() {
    const p = project(),
      ts = S.snap.targets.filter((t) => t.project_id === p?.id);
    return (
      head(
        "Plan the investment. Keep the target separate.",
        "Forecasts stay separate from verified deployment and measured outcomes.",
      ) +
      ctx() +
      `<details class="work-sheet" ${!p ? "open" : ""}><summary>New investment proposal</summary>${analyst ? projectForm() : "<p>Read-only judge access.</p>"}</details>` +
      (p
        ? `<section class="work-sheet"><h2>${esc(p.title)}</h2><p>${esc(title(p.kind))} · ${esc(p.stage)} · Reported proposal</p><p>Proposed amount: ${esc(p.proposed_amount ?? "Unknown")} ${esc(p.currency || "")}</p><p>${esc(p.rationale)}</p>${sourceWarning(p.source)}<p class="small">Source: ${esc(p.source.attribution)} · “${esc(p.source.quote)}”</p>${analyst ? `<details><summary>Edit project and machine roles</summary>${projectForm(p)}</details>` : ""}<h3>Targets and supporting records</h3><div class="table-scroll"><table><thead><tr><th>Metric</th><th>Target</th><th>Baseline</th><th>Outcome</th></tr></thead><tbody>${ts.map((t) => `<tr><td>${esc(title(t.metric))}</td><td>${esc(t.target_value)} ${esc(title(t.target_type))}</td><td>${esc(t.baseline_value ?? "Missing")} ${esc(t.unit)}</td><td>${esc(outcomeLabel(t))}</td></tr>`).join("")}</tbody></table></div><p class="banner">A forecast is not evidence of achieved savings.</p>${ts.map((t) => `<details class="subdisclosure"><summary>${esc(title(t.metric))} · review/edit</summary>${sourceWarning(t.source)}${analyst ? targetForm(t) : ""}${outcomeForm(t)}</details>`).join("")}${analyst ? `<details class="subdisclosure"><summary>Add a target</summary>${targetForm()}</details>` : ""}<h3>Deployment and outcome reviews</h3>${
            S.snap.investment_reviews
              .filter((r) => r.project_id === p.id)
              .map(
                (r) =>
                  `<p>${esc(title(r.kind))} · ${esc(r.status)} · ${esc(r.methodology)}<br><small>${esc(r.reviewed_by)} · ${esc(JSON.stringify(r.calculation))}</small></p>`,
              )
              .join("") || "<p>No investment review recorded.</p>"
          }${analyst ? milestoneForm() : ""}</section>`
        : "<p>Select or create an investment project.</p>")
    );
  }
  function evidenceOptions() {
    return S.snap.v1_inspections.flatMap((v) =>
      v.evidence.map((e) => [
        e.id,
        v.inspection.name +
          " · " +
          e.filename +
          (e.confirmed ? " · Accepted" : " · Unaccepted"),
      ]),
    );
  }
  function outcomeForm(t) {
    return !analyst
      ? ""
      : `<h3>Record measured outcome review</h3>${form(
          "outcome",
          `<input type="hidden" name="target_id" value="${t.id}">${select(
            "status",
            "Review status",
            [
              "not_yet_measurable",
              "unresolved",
              "inconclusive",
              "reported",
              "supported",
              "contradicted",
            ].map((x) => [x, title(x)]),
            "not_yet_measurable",
          )}<div class="v2-grid">${val("baseline_value", "Reviewed baseline value", "", 'type="number" min="0" step="any"')}${val("measured_value", "Reviewed measured value", "", 'type="number" min="0" step="any"')}${val("period", "Comparable period definition, e.g. hours/month", "", 'maxlength="200"')}${select("baseline_evidence", "Baseline source", evidenceOptions())}${select("measurement_evidence", "Measurement source", evidenceOptions())}</div>${text("baseline_quote", "Exact baseline quote")}${text("measurement_quote", "Exact measurement quote")}<label class="check-label"><input name="comparable" type="checkbox">The measurement method and period definitions are comparable.</label>${text("methodology", "Review method and limitations", "", "required")}${save("Save reviewed measurement")}`,
        )}`;
  }
  function milestoneForm() {
    return `<details class="subdisclosure"><summary>Record a deployment milestone review</summary>${form(
      "milestone",
      select(
        "kind",
        "Milestone",
        [
          "purchase",
          "payment",
          "delivery",
          "installation",
          "commissioning",
        ].map((x) => [x, title(x)]),
        "installation",
      ) +
        select(
          "status",
          "Conclusion",
          [
            "reported",
            "supported",
            "unresolved",
            "contradicted",
            "inconclusive",
          ].map((x) => [x, title(x)]),
          "unresolved",
        ) +
        select("evidence_id", "Relevant evidence", evidenceOptions()) +
        text("methodology", "Review explanation", "", "required") +
        '<p class="small">Supported milestones require a current supported and reviewed underlying finding for this machine.</p>' +
        save("Save milestone review"),
    )}</details>`;
  }
  function taskForm(f = null) {
    const d = f?.details,
      origin = d
        ? S.snap.v1_inspections.find((v) => v.inspection.id === d.inspection_id)
        : U.state.report,
      local = d
        ? S.snap.asset_bindings.find(
            (b) =>
              b.active &&
              b.inspection_id === d.inspection_id &&
              b.physical_asset_id === d.physical_asset_id,
          )?.local_asset_id
        : U.state.aid,
      claims = origin?.claims.filter((c) => c.asset_id === local) || [];
    return form(
      "task",
      `<input type="hidden" name="id" value="${f?.task.id || ""}">${text("request", "What evidence is needed?", f?.task.request || S.pendingCandidate?.edited.text || "", "required")}<div class="v2-grid">${select("claim_id", "Underlying claim", [["", "Project/asset requirement"], ...claims.map((c) => [c.id, title(c.kind)])], f?.task.claim_id || "")}${val("contact", "Reported contact", d?.contact || "", 'required maxlength="200"')}${select(
        "reviewer",
        "Reviewer",
        (S.caps.analyst_actors || []).map((a) => [a, a]),
        d?.reviewer || document.body.dataset.actor,
      )}${val("due_date", "Due date", d?.due_date || S.pendingCandidate?.edited.due_date || "", 'type="date" required')}${select(
        "verification_method",
        "Verification method",
        [
          "document_review",
          "issuer_confirmation",
          "site_test",
          "site_inspection",
        ].map((x) => [x, title(x)]),
        d?.verification_method || "document_review",
      )}</div>${text("required_evidence", "Exact requirement for closure", d?.required_evidence || "", "required")}${save(f ? "Save revised requirement" : "Save follow-up")}`,
    );
  }
  function followups() {
    return (
      head(
        "Turn missing evidence into a clear next step",
        "Review submissions against the requirement before closing a request.",
      ) +
      ctx() +
      (analyst
        ? `<details class="work-sheet" ${S.pendingCandidate ? "open" : ""}><summary>New evidence request${S.pendingCandidate ? " · Confirm AI proposal" : ""}</summary>${taskForm()}</details>`
        : "") +
      `<div class="table-region"><div class="table-scroll"><table><thead><tr><th>Request</th><th>Machine</th><th>Contact</th><th>Due</th><th>Status</th></tr></thead><tbody>${S.snap.follow_ups.map((f) => `<tr><td>${btn("select-task", esc(f.task.request), `data-id="${f.task.id}"`)}</td><td>${esc(S.snap.physical_assets.find((a) => a.id === f.details.physical_asset_id)?.label)}</td><td>${esc(f.details.contact)}</td><td>${esc(f.details.due_date)}</td><td>${esc(title(f.details.workflow_status))}</td></tr>`).join("")}</tbody></table></div></div>${taskDetail()}${analyst ? `<div class="section-actions">${btn("reminders", "Run due-date test reminders")}${btn("audit", "Show saved-edit audit")}</div><div id="v2-audit"></div>` : ""}`
    );
  }
  function taskDetail() {
    const f =
      S.snap.follow_ups.find((f) => f.task.id === S.task) ||
      S.snap.follow_ups.find((f) => f.details.physical_asset_id === S.physical);
    if (!f) return "<p>No follow-up selected.</p>";
    S.task = f.task.id;
    const d = f.details;
    const allowed = {
      open: ["awaiting_information", "submitted_for_review"],
      awaiting_information: ["submitted_for_review"],
      submitted_for_review: ["needs_more_evidence", "closed"],
      needs_more_evidence: ["awaiting_information", "submitted_for_review"],
      closed: ["open"],
    }[d.workflow_status];
    return `<section class="work-sheet"><h2>${esc(f.task.request)}</h2><p>Contact ${esc(d.contact)} · Reviewer ${esc(d.reviewer)} · Due ${esc(d.due_date)}</p><p>Required: ${esc(d.required_evidence)}</p><p class="banner">Status: ${esc(title(d.workflow_status))}. Closure requires accepted evidence and verified support for the underlying requirement.</p>${
      analyst
        ? form(
            "transition",
            `<input type="hidden" name="id" value="${f.task.id}">${select(
              "status",
              "Next action",
              allowed.map((x) => [x, title(x)]),
            )}${select(
              "review_inspection_id",
              "Review visit",
              S.snap.v1_inspections.map((v) => [
                v.inspection.id,
                v.inspection.name,
              ]),
              d.review_inspection_id || visit(),
            )}<fieldset><legend>Evidence submitted/reviewed</legend>${evidenceOptions()
              .map(
                ([id, name]) =>
                  `<label class="check-label"><input type="checkbox" name="evidence_ids" value="${id}" ${d.submitted_evidence_ids.includes(id) ? "checked" : ""}>${esc(name)}</label>`,
              )
              .join(
                "",
              )}</fieldset><label class="check-label"><input name="verification_supported" type="checkbox">I verified that the underlying requirement is supported by the selected accepted evidence.</label>${text("reason", "Review explanation", "", "required")}${save("Save workflow transition")}`,
          )
        : ""
    }${analyst && d.workflow_status !== "closed" ? `<details><summary>Edit saved request (resets review)</summary>${taskForm(f)}</details>` : ""}</section>`;
  }
  function assessment() {
    return `<section class="work-sheet v2-assessment"><h2>Investment context and visit memory</h2>${ctx()}${
      (S.snap.targets || [])
        .filter((t) => t.project_id === S.project)
        .map(
          (t) =>
            `<p>${esc(title(t.metric))}: ${esc(t.target_value)} ${esc(title(t.target_type))} · Management forecast · ${esc(outcomeLabel(t))}</p>`,
        )
        .join("") || "<p>No target selected.</p>"
    }<div class="section-actions"><a href="${root()}/report.pdf" download>Download case PDF</a><a href="${root()}/export" download>Export case JSON</a><a href="${root()}/report" download>Download text</a><a href="#/investments">Review investments</a></div>${history()}</section>`;
  }
  function wearable() {
    return (
      head(
        "Wearable mode · glanceable inspection",
        "Browser preview — no glasses connected.",
      ) +
      ctx() +
      `<div class="v2-hud"><p>${esc(asset()?.tag)} · ${S.physical ? "Identity confirmed" : "Identity not confirmed"}</p><h2>${!S.physical ? "Capture a readable label" : esc((S.analysis || S.snap.analyses.at(-1))?.questions.find((q) => q.status === "suggested")?.question || "Review the latest transcript")}</h2><p>${esc(S.segment?.text || "No source segment selected.")}</p><p>${esc(S.segment?.english_translation || "")}</p><div class="section-actions"><a href="#/site">${!S.physical ? "Rescan label" : "Record / correct transcript"}</a></div><p class="small">Source and save controls are in Site Inspection. Headset SDK integration is pending.</p></div>`
    );
  }
  function render(view) {
    if (!U.state.report) return undefined;
    if (
      ["overview", "site", "investments", "followups", "wearable"].includes(
        view,
      )
    ) {
      if (!S.snap)
        return setup() + (view === "overview" ? U.legacy.overview() : "") + (window.CDIIntake?.panel(view) || "");
      return { overview, site, investments, followups, wearable }[view]() + (window.CDIIntake?.panel(view) || "");
    }
    return undefined;
  }
  function decorate(view) {
    if (view === "evidence") $("#workspace").insertAdjacentHTML("afterbegin", window.CDIIntake?.panel(view) || "");
    if (S.snap && view === "assessment")
      $("#workspace").insertAdjacentHTML("beforeend", assessment());
    if (S.snap && view === "evidence")
      $("#workspace").insertAdjacentHTML(
        "beforeend",
        ctx() + identity() + scan(),
      );
    afterRender();
  }
  function afterRender() {
    $$(
      "[data-v2-form] input,[data-v2-form] textarea,[data-v2-form] select",
    ).forEach((el) => {
      el.disabled = S.recording || S.pending > 0 || !analyst;
    });
    const active = S.recording || S.pending > 0 || !!S.mediaRequest;
    const recordButton = $("[data-v2=record]");
    if (recordButton)
      recordButton.disabled = active || !S.physical || !!(S.scan && S.scan.identity_result !== "matches_declared_serial");
    const stopButton = $("[data-v2=stop]");
    if (stopButton)
      stopButton.disabled = !(S.recording || S.mediaRequest?.kind === "microphone");
    const cameraButton = $("[data-v2=camera]");
    if (cameraButton) cameraButton.disabled = active || !!S.camera;
    for (const el of $$(
      "[name=capture_type],[name=audio_language],[name=speaker],[name=operating_mode],#v2-consent,#v2-share,#v2-synthetic,#v2-incremental,#v2-speaker-confirmed",
    ))
      el.disabled = active;
    const host = $("#v2-case-control");
    if (host)
      host.innerHTML = `<label class="small">Case <select id="v2-case" ${!canNavigate() ? "disabled" : ""}><option value="">Unenrolled visit</option>${opts(S.cases, S.snap?.case.id, (c) => c.company)}</select></label>`;
    const picker = $("#inspection-picker");
    if (picker) {
      picker.innerHTML = opts(U.state.inspections || [], visit(), (v) => v.name);
      picker.disabled = !canNavigate();
    }
    if (S.recording || S.pending) {
      $("#v2-record-status")?.replaceChildren(
        document.createTextNode(
          "Recording/processing in progress. Do not change machine or visit.",
        ),
      );
    }
  }
  function unsaved() {
    return S.clips
      .filter((c) => !c.saved)
      .map(
        (c) =>
          `<p class="banner">Unsaved clip: ${esc(c.filename)} ${btn("save-clip", "Retry save", `data-id="${c.id}"`)} ${btn("download-clip", "Download local copy", `data-id="${c.id}"`)}</p>`,
      )
      .join("");
  }
  function operationKey(name) {
    if (!S.operationKeys.has(name)) S.operationKeys.set(name, uid());
    return S.operationKeys.get(name);
  }
  async function getInterview(context) {
    if (
      S.interview &&
      S.interview.inspection_id === context.visit &&
      S.interview.physical_asset_id === context.physical &&
      S.interview.speaker_label === context.speaker
    )
      return S.interview;
    S.interview = await U.api(context.root + "/interviews", {
      method: "POST",
      key: operationKey("interview:" + JSON.stringify(context)),
      body: {
        inspection_id: context.visit,
        physical_asset_id: context.physical,
        project_id: context.project,
        speaker_label: context.speaker,
        speaker_confirmed: context.speakerConfirmed,
        consent_confirmed: true,
        consent_note: "Analyst confirmed authorization and informed speakers",
        synthetic: context.synthetic,
        reason: "Create source-linked interview",
      },
    });
    return S.interview;
  }
  function captureContext() {
    requireIdentity();
    if (!$("#v2-consent")?.checked)
      throw Error("Confirm recording authorization and inform speakers first.");
    return {
      root: root(),
      visit: visit(),
      physical: S.physical,
      project: S.project,
      speaker: $("[name=speaker]")?.value || "Speaker 1 — unconfirmed",
      speakerConfirmed: !!$("#v2-speaker-confirmed")?.checked,
      language: $("[name=audio_language]")?.value || "ja",
      kind: $("[name=capture_type]")?.value || "interview_speech",
      share: !!$("#v2-share")?.checked,
      synthetic: !!$("#v2-synthetic")?.checked,
      operating: $("[name=operating_mode]")?.value || "unknown",
    };
  }
  async function saveClip(c) {
    if (c.saved) return c.saved;
    const body = new FormData();
    body.append("file", new File([c.blob], c.filename, { type: c.blob.type }));
    body.append(
      "metadata",
      JSON.stringify({
        inspection_id: c.context.visit,
        physical_asset_id: c.context.physical,
        capture_type: c.context.kind,
        captured_at: c.at,
        device: navigator.userAgent.slice(0, 200),
        operating_mode: c.context.operating,
        note: "Analyst capture; load, distance and ambient conditions require review",
        consent_confirmed: true,
        consent_note: "Analyst confirmed authorized recording",
        synthetic: c.context.synthetic,
        share_with_judges: c.context.share,
        signal_processing:
          c.context.kind === "machine_acoustic"
            ? "none_requested"
            : "speech_enhancement",
        reason: "Save original recording with capture context",
      }),
    );
    c.saved = await U.api(c.context.root + "/audio", {
      method: "POST",
      body,
      key: c.id,
    });
    $("#v2-unsaved")?.replaceChildren();
    return c.saved;
  }
  async function speech(recording, context) {
    const session = await getInterview(context);
    S.segment = await U.api(
      context.root + "/audio/" + recording.id + "/transcribe",
      {
        method: "POST",
        key: operationKey(
          "speech:" + recording.id + ":" + session.id + ":" + context.language,
        ),
        body: {
          interview_id: session.id,
          language: context.language,
          mode: "microphone_chunk",
          reason:
            "Transcribe real saved audio and preserve Japanese/English text",
        },
      },
    );
    S.analysis = null;
  }
  async function analyse() {
    if (!S.segment) throw Error("Save or transcribe a source first.");
    S.analysis = await U.api(
      root() + "/segments/" + S.segment.id + "/analyse",
      {
        method: "POST",
        body: {
          reason: "Suggest contextual questions from saved source",
          allow_rule_fallback: !!$("#v2-fallback")?.checked,
        },
        key: uid(),
      },
    );
    S.lastAnalysis = Date.now();
  }
  async function startRecording() {
    const context = captureContext();
    if (context.share && !context.synthetic)
      throw Error(
        "Only synthetic demonstration recordings can be shared with judges.",
      );
    if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder)
      throw Error(
        "Microphone recording requires HTTPS and a supported browser. Use a saved clip instead.",
      );
    const incremental = !!$("#v2-incremental")?.checked;
    if (incremental && context.kind === "machine_acoustic")
      throw Error(
        "Use interview mode for incremental speech; machine samples must preserve their signal.",
      );
    const mime = ["audio/webm;codecs=opus", "audio/mp4"].find((t) =>
      MediaRecorder.isTypeSupported(t),
    );
    if (!mime)
      throw Error("No supported microphone codec; upload a WAV/M4A clip.");
    if (S.recording || S.pending)
      throw Error("Finish the current capture and processing first.");
    S.stream = await requestMedia({
      audio:
        context.kind === "machine_acoustic"
          ? {
              echoCancellation: false,
              noiseSuppression: false,
              autoGainControl: false,
            }
          : true,
      video: false,
    }, "microphone");
    S.recording = true;
    afterRender();
    $("#v2-record-status").textContent =
      "Recording. Each clip is saved before speech processing.";
    $("[data-v2=record]").disabled = true;
    $("[data-v2=stop]").disabled = false;
    function next() {
      if (!S.recording) return;
      const chunks = [],
        startedAt = new Date().toISOString();
      const recorder = new MediaRecorder(S.stream, { mimeType: mime });
      S.recorder = recorder;
      recorder.ondataavailable = (e) => {
        if (e.data.size) chunks.push(e.data);
      };
      recorder.onerror = () => {
        stopRecording();
        U.note(
          "Microphone stopped unexpectedly. Saved clips remain available.",
          true,
        );
      };
      recorder.onstop = () => {
        clearTimeout(S.timer);
        const blob = new Blob(chunks, { type: recorder.mimeType });
        if (!blob.size) {
          stopRecording();
          return;
        }
        const c = {
          id: uid(),
          blob,
          filename:
            "inspection-" +
            Date.now() +
            "." +
            (mime.includes("webm") ? "webm" : "m4a"),
          at: startedAt,
          context,
        };
        S.clips.push(c);
        S.pending++;
        S.queue = S.queue
          .then(async () => {
            await saveClip(c);
            if (context.kind !== "machine_acoustic") {
              await speech(c.saved, context);
              if (Date.now() - S.lastAnalysis > 30000) await analyse();
              if (S.recording) await updateLivePanels();
            }
          })
          .catch((e) => {
            stopRecording();
            U.note(
              e.message +
                (c.saved
                  ? " Original audio is saved; retry speech from Saved recordings."
                  : " Clip is local and unsaved; retry or download it below."),
              true,
            );
          })
          .finally(async () => {
            S.pending--;
            if (!S.recording && S.pending === 0) await refresh();
            else if ($("#v2-record-status"))
              $("#v2-record-status").textContent =
                "Recording; " +
                S.pending +
                " clip(s) processing. Saved transcripts update as each clip completes.";
          });
        if (incremental && S.recording && S.pending < 3) next();
        else {
          stopRecording();
          if (S.pending >= 3)
            U.note(
              "Capture paused while processing catches up. Originals are retained.",
            );
        }
      };
      recorder.start();
      S.timer = setTimeout(
        () => {
          if (recorder.state === "recording") recorder.stop();
        },
        incremental ? 8000 : 110000,
      );
    }
    try {
      next();
    } catch (e) {
      stopRecording();
      throw e;
    }
  }
  async function updateLivePanels() {
    S.snap = await U.api(root() + "/export");
    const panel = $("#v2-transcript-view");
    if (panel && S.segment)
      panel.innerHTML = `<p lang="${esc(S.segment.language)}">${esc(S.segment.text)}</p><p>${esc(S.segment.english_translation || "")}</p><p class="small">Saved transcript. Stop capture to correct the source.</p>`;
    const q = $("#v2-questions");
    if (q) q.innerHTML = questions();
    const c = $("#v2-candidates");
    if (c) c.innerHTML = candidates();
  }
  function stopRecording() {
    if (S.mediaRequest?.kind === "microphone") S.mediaRequest.cancel();
    S.recording = false;
    clearTimeout(S.timer);
    if (S.recorder?.state === "recording") S.recorder.stop();
    S.stream?.getTracks().forEach((t) => t.stop());
    $("[data-v2=record]")?.removeAttribute("disabled");
    if ($("[data-v2=stop]")) $("[data-v2=stop]").disabled = true;
    afterRender();
  }
  async function scanPhoto(file) {
    if (!file?.size) throw Error("Choose a label photograph.");
    if (file.size > 12 * 1024 * 1024) throw Error("Photo exceeds 12 MiB.");
    const body = new FormData();
    body.append("file", file);
    body.append("kind", "site_image");
    body.append("source", "Analyst phone label capture");
    body.append("captured_at", new Date().toISOString());
    body.append(
      "reason",
      "Preserve label original for scan and explicit identity review",
    );
    const ev = await U.api("/api/v1/inspections/" + visit() + "/evidence", {
      method: "POST",
      body,
    });
    S.scan = await U.api(
      "/api/v1/inspections/" + visit() + "/evidence/" + ev.id + "/scan-label",
      {
        method: "POST",
        body: {
          asset_id: U.state.aid,
          reason: "Check barcode readability and declared serial",
        },
      },
    );
    U.state.eid = ev.id;
    await refresh();
    U.note(
      "Original saved unaccepted. " +
        title(S.scan.identity_result) +
        ". Review it before confirming identity.",
    );
  }
  async function openCamera() {
    if (!navigator.mediaDevices?.getUserMedia)
      throw Error(
        "Camera access needs HTTPS or localhost. Use the Take/upload photo control instead.",
      );
    if (S.recording || S.pending)
      throw Error("Stop recording before changing capture devices.");
    closeCamera();
    S.camera = await requestMedia({
      video: { facingMode: { ideal: "environment" }, width: { ideal: 1920 } },
      audio: false,
    }, "camera");
    const v = $("#v2-camera");
    v.hidden = false;
    v.srcObject = S.camera;
    await v.play();
    $("#v2-capture-photo").hidden = false;
    afterRender();
  }
  function closeCamera() {
    if (S.mediaRequest?.kind === "camera") S.mediaRequest.cancel();
    S.camera?.getTracks().forEach((t) => t.stop());
    S.camera = null;
    const v = $("#v2-camera");
    if (v) {
      v.srcObject = null;
      v.hidden = true;
    }
    if ($("#v2-capture-photo")) $("#v2-capture-photo").hidden = true;
    afterRender();
  }
  async function requestMedia(constraints, kind) {
    if (S.mediaRequest) throw Error("Finish or cancel the current permission request first.");
    const request = { kind, cancelled: false, cancel: null };
    let timer;
    const interrupted = new Promise((_, reject) => {
      request.cancel = (message = "Permission request cancelled. No recording was saved.") => {
        request.cancelled = true;
        reject(Error(message));
      };
      timer = setTimeout(() => request.cancel("Permission request timed out. Check the browser permission prompt, then retry."), 45000);
    });
    S.mediaRequest = request;
    afterRender();
    U.note(`Waiting for ${kind} permission. Use ${kind === "camera" ? "Close camera" : "Stop recording"} to cancel.`);
    const pending = Promise.resolve().then(() => navigator.mediaDevices.getUserMedia(constraints));
    pending.then(stream => {
      if (request.cancelled) stream.getTracks().forEach(track => track.stop());
    }, () => {});
    try {
      return await Promise.race([pending, interrupted]);
    } finally {
      clearTimeout(timer);
      if (S.mediaRequest === request) S.mediaRequest = null;
      afterRender();
    }
  }
  function discardConfirmed() {
    return (
      !(S.dirty || U.state.dirty) ||
      confirm("You have unsaved entries. Discard them and change context?")
    );
  }
  function contextChanged() {
    S.interview = null;
    S.segment = null;
    S.analysis = null;
    S.pendingCandidate = null;
    S.scan = null;
    S.chat = [];
  }
  const actions = {
    "open-machine": async (b) => {
      U.state.aid = b.dataset.id;
      contextChanged();
      await refresh();
      location.hash = "/site";
    },
    camera: openCamera,
    "camera-stop": closeCamera,
    "capture-photo": async () => {
      const v = $("#v2-camera");
      if (!v?.videoWidth) throw Error("Wait for the camera preview.");
      const canvas = document.createElement("canvas");
      canvas.width = v.videoWidth;
      canvas.height = v.videoHeight;
      canvas.getContext("2d").drawImage(v, 0, 0);
      const blob = await new Promise((r) =>
        canvas.toBlob(r, "image/jpeg", 0.94),
      );
      closeCamera();
      await scanPhoto(
        new File([blob], "label-" + Date.now() + ".jpg", {
          type: "image/jpeg",
        }),
      );
    },
    "review-scan": () => {
      U.state.view = "evidence";
      U.state.evidenceStep = 2;
      U.render();
    },
    record: startRecording,
    stop: stopRecording,
    analyse: async () => {
      await analyse();
      await refresh();
      U.note("Questions and proposals saved; review their sources.");
    },
    translate: async () => {
      if (!S.segment) throw Error("Save a Japanese segment first.");
      S.segment = await U.api(
        root() + "/segments/" + S.segment.id + "/translate",
        {
          method: "POST",
          body: {
            version: S.segment.version,
            reason: "Translate saved original Japanese text",
          },
        },
      );
      await refresh();
    },
    "select-segment": async (b) => {
      S.segment = S.snap.segments.find((s) => s.id === b.dataset.id);
      S.analysis = null;
      U.render();
    },
    transcribe: async (b) => {
      const a = S.snap.audio.find((a) => a.id === b.dataset.id);
      if (a.inspection_id !== visit())
        throw Error("Select the recording’s original visit first.");
      const c = captureContext();
      await speech(a, c);
      await refresh();
    },
    question: async (b) => {
      if (!S.analysis) throw Error("Select an analysis first.");
      S.analysis = await U.api(
        root() + "/analyses/" + S.analysis.id + "/question",
        {
          method: "PATCH",
          body: {
            version: S.analysis.version,
            index: Number(b.dataset.index),
            status: b.dataset.status,
            reason: "Analyst records question disposition",
          },
        },
      );
      await refresh();
    },
    "reject-candidate": async (b) => {
      const c = S.snap.candidates.find((c) => c.id === b.dataset.id);
      await U.api(root() + "/candidates/" + c.id + "/confirm", {
        method: "POST",
        body: {
          version: c.version,
          action: "reject",
          reason: "Analyst rejected AI proposal",
        },
      });
      await refresh();
    },
    "save-clip": async (b) => {
      const c = S.clips.find((c) => c.id === b.dataset.id);
      await saveClip(c);
      await refresh();
    },
    "download-clip": (b) => {
      const c = S.clips.find((c) => c.id === b.dataset.id),
        url = URL.createObjectURL(c.blob),
        a = document.createElement("a");
      a.href = url;
      a.download = c.filename;
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 1500);
    },
    "select-task": async (b) => {
      S.task = b.dataset.id;
      const f = S.snap.follow_ups.find((f) => f.task.id === S.task);
      const bind =
        S.snap.asset_bindings.find(
          (b) =>
            b.active &&
            b.physical_asset_id === f.details.physical_asset_id &&
            b.inspection_id === visit(),
        ) ||
        S.snap.asset_bindings.find(
          (b) =>
            b.active && b.physical_asset_id === f.details.physical_asset_id,
        );
      if (bind && bind.inspection_id !== visit())
        await U.changeVisit(bind.inspection_id);
      if (bind) {
        U.state.aid = bind.local_asset_id;
        S.physical = bind.physical_asset_id;
      }
      U.render();
    },
    reminders: async () => {
      const r = await U.api(root() + "/reminders/run", {
        method: "POST",
        body: { reason: "Run due-date reminder delivery to local test inbox" },
      });
      U.note(
        r.length ? r.map((d) => d.status).join(", ") : "No requests are due.",
      );
    },
    audit: async () => {
      const rows = await U.api(root() + "/activity");
      $("#v2-audit").innerHTML =
        rows
          .map(
            (e) =>
              `<details><summary>${esc(e.action)} · ${esc(e.author)} · ${esc(e.time)}</summary><pre>${esc(JSON.stringify({ before: e.before, after: e.after, reason: e.reason }, null, 2))}</pre></details>`,
          )
          .join("") || "<p>No audit events.</p>";
    },
    "repeat-visit": async () => {
      const caseId = S.snap.case.id;
      const v = await U.api("/api/v1/demo/prepare", {
        method: "POST",
        body: {
          reason:
            "Create a separate synthetic repeat visit; preserve previous visit",
        },
      });
      await U.api("/api/v1/cases/" + caseId + "/inspections", {
        method: "POST",
        body: {
          inspection_id: v.id,
          reason: "Enroll synthetic repeat inspection",
        },
      });
      contextChanged();
      await U.changeVisit(v.id);
      U.note(
        "New visit saved. Confirm each physical-machine association against this visit’s identity evidence.",
      );
    },
  };
  document.addEventListener("click", (e) => {
    const b = e.target.closest("[data-v2]");
    if (!b) return;
    e.preventDefault();
    if (
      [
        "open-machine",
        "select-task",
        "select-segment",
        "repeat-visit",
      ].includes(b.dataset.v2) &&
      !discardConfirmed()
    )
      return;
    if (
      (S.recording || S.pending || S.mediaRequest) &&
      !["stop", "camera-stop", "question"].includes(b.dataset.v2)
    ) {
      U.note("Stop capture and wait for pending processing first.", true);
      return;
    }
    if (
      !analyst &&
      !["open-machine", "select-segment", "select-task"].includes(b.dataset.v2)
    ) {
      U.note("Judge access is read-only.", true);
      return;
    }
    // Stop must remain usable while an asynchronous permission dialog is open.
    if (["stop", "camera-stop"].includes(b.dataset.v2)) {
      actions[b.dataset.v2](b);
      return;
    }
    act(() => actions[b.dataset.v2]?.(b));
  });
  document.addEventListener("change", (e) => {
    if (e.target.id === "v2-machine") {
      if (!discardConfirmed()) {
        e.target.value = U.state.aid;
        return;
      }
      if (!canNavigate()) {
        U.note("Stop capture and wait for processing first.", true);
        return;
      }
      U.state.aid = e.target.value;
      contextChanged();
      act(refresh);
    } else if (e.target.id === "v2-project") {
      if (!discardConfirmed()) {
        e.target.value = S.project || "";
        return;
      }
      S.project = e.target.value || null;
      contextChanged();
      U.render();
    } else if (e.target.id === "v2-case") {
      if (!discardConfirmed()) {
        e.target.value = S.snap?.case.id || "";
        return;
      }
      act(async () => {
        if (!canNavigate()) throw Error("Stop capture first.");
        const vs = await U.api(
          "/api/v1/cases/" + e.target.value + "/inspections",
        );
        contextChanged();
        await U.changeVisit(vs.at(-1).id);
      });
    } else if (e.target.id === "v2-label-file") {
      const file = e.target.files[0];
      act(() => scanPhoto(file));
    } else if (e.target.id === "v2-audio-file") {
      const file = e.target.files[0];
      act(async () => {
        const context = captureContext();
        if (file.size > 12 * 1024 * 1024) throw Error("Audio exceeds 12 MiB.");
        const c = {
          id: uid(),
          blob: file,
          filename: file.name,
          context,
          at: new Date().toISOString(),
        };
        S.clips.push(c);
        await saveClip(c);
        await refresh();
        U.note("Original audio saved. Choose Transcribe to process speech.");
      });
    }
  });
  document.addEventListener("submit", (e) => {
    const f = e.target,
      id = f.dataset.v2Form;
    if (id === undefined) return;
    e.preventDefault();
    if (!analyst) {
      U.note("Judge access is read-only.", true);
      return;
    }
    const d = new FormData(f),
      v = Object.fromEntries(d),
      requestKey = formKey(f);
    act(async () => {
      if (id === "chat") {
        requireIdentity();
        const reply = await U.api(root() + "/chat", {
          method: "POST",
          key: requestKey,
          body: {
            inspection_id: visit(),
            physical_asset_id: S.physical,
            question: v.question,
            reason: "Analyst asks a source-linked case question",
          },
        });
        S.chat.push(reply);
        await refresh();
      }
      if (id === "case") {
        await U.api("/api/v1/cases", {
          method: "POST",
          key: requestKey,
          body: {
            inspection_id: visit(),
            company: v.company,
            site: v.site,
            timezone: "Asia/Tokyo",
            reason,
          },
        });
        await refresh();
      }
      if (id === "enrol") {
        await U.api("/api/v1/cases/" + v.case_id + "/inspections", {
          method: "POST",
          body: { inspection_id: visit(), reason },
        });
        await refresh();
      }
      if (id === "identity") {
        if (!v.identity_evidence_id)
          throw Error("Accept matching identity evidence first.");
        const prior = S.snap.physical_assets.find(
          (a) =>
            (a.serial || "").trim().toLowerCase() ===
            (asset().serial || "").trim().toLowerCase(),
        );
        const body = {
          inspection_id: visit(),
          local_asset_id: U.state.aid,
          identity_evidence_id: v.identity_evidence_id,
          identity_locator: v.identity_locator,
          reason,
        };
        await U.api(root() + (prior ? "/asset-bindings" : "/physical-assets"), {
          method: "POST",
          body: prior ? { ...body, physical_asset_id: prior.id } : body,
        });
        await refresh();
      }
      if (id === "segment") {
        const old = S.segment;
        if (v.correct_existing && old) {
          S.segment = await U.api(root() + "/segments/" + old.id, {
            method: "PATCH",
            body: {
              version: old.version,
              text: v.text,
              language: v.language,
              english_translation: v.english_translation || null,
              translation_origin: v.english_translation ? "human" : null,
              recording_id: old.recording_id,
              start_ms: old.start_ms,
              end_ms: old.end_ms,
              mode: old.mode,
              reason: v.reason,
            },
          });
        } else {
          const context = captureContext(),
            session = await getInterview(context);
          S.segment = await U.api(
            root() + "/interviews/" + session.id + "/segments",
            {
              method: "POST",
              key: requestKey,
              body: {
                text: v.text,
                language: v.language,
                english_translation: v.english_translation || null,
                translation_origin: v.english_translation ? "human" : null,
                mode: "manual",
                reason: v.reason,
              },
            },
          );
        }
        S.analysis = null;
        await refresh();
      }
      if (id === "project") {
        requireIdentity();
        const old = S.snap.investments.find((p) => p.id === v.id);
        const body = {
          inspection_id: old?.inspection_id || visit(),
          title: v.title,
          kind: v.kind,
          rationale: v.rationale,
          proposed_amount: v.proposed_amount || null,
          currency: v.proposed_amount ? v.currency.toUpperCase() : null,
          asset_links: d
            .getAll("linked_assets")
            .map((id) => ({ physical_asset_id: id, role: v["role_" + id] })),
          source: {
            kind: "management_report",
            attribution: v.attribution,
            quote: v.source_quote,
          },
          reason,
        };
        const p = await U.api(
          root() + "/investments" + (old ? "/" + old.id : ""),
          {
            method: old ? "PATCH" : "POST",
            key: requestKey,
            body: old
              ? { ...body, version: old.version, stage: v.stage }
              : body,
          },
        );
        S.project = p.id;
        await refresh();
      }
      if (id === "target") {
        if (!S.project) throw Error("Select a project.");
        const old = S.snap.targets.find((t) => t.id === v.id);
        const body = {
          inspection_id: old?.inspection_id || visit(),
          metric: v.metric,
          unit: v.unit,
          baseline_value: v.baseline_value || null,
          baseline_period: v.baseline_period || null,
          target_type: v.target_type,
          target_value: v.target_value,
          currency: v.currency?.toUpperCase() || null,
          due_date: v.due_date || null,
          relative_months: v.relative_months ? Number(v.relative_months) : null,
          anchor: v.relative_months ? "commissioning" : null,
          source: {
            kind: "management_report",
            attribution: v.attribution,
            quote: v.quote,
          },
          reason,
        };
        await U.api(
          root() +
            (old
              ? "/targets/" + old.id
              : "/investments/" + S.project + "/targets"),
          {
            method: old ? "PATCH" : "POST",
            key: requestKey,
            body: old ? { ...body, version: old.version } : body,
          },
        );
        await refresh();
      }
      if (id === "outcome") {
        const t = S.snap.targets.find((t) => t.id === v.target_id);
        const has = v.status === "supported";
        await U.api(root() + "/investments/" + S.project + "/reviews", {
          method: "POST",
          body: {
            inspection_id: visit(),
            kind: "outcome",
            status: v.status,
            target_id: t.id,
            measured_value: v.measured_value || null,
            baseline_value: v.baseline_value || null,
            unit: t.unit,
            currency: t.currency,
            measurement_period: v.period || null,
            baseline_period: v.period || null,
            comparable: !!v.comparable,
            methodology: v.methodology,
            baseline_source: has
              ? {
                  evidence_id: v.baseline_evidence,
                  locator: "Quoted baseline record",
                  quote: v.baseline_quote,
                }
              : null,
            measurement_source: has
              ? {
                  evidence_id: v.measurement_evidence,
                  locator: "Quoted measurement record",
                  quote: v.measurement_quote,
                }
              : null,
            evidence_ids: has
              ? [...new Set([v.baseline_evidence, v.measurement_evidence])]
              : [],
            reason,
          },
        });
        await refresh();
      }
      if (id === "milestone") {
        requireIdentity();
        await U.api(root() + "/investments/" + S.project + "/reviews", {
          method: "POST",
          body: {
            inspection_id: visit(),
            physical_asset_id: S.physical,
            kind: v.kind,
            status: v.status,
            methodology: v.methodology,
            evidence_ids: v.evidence_id ? [v.evidence_id] : [],
            reason,
          },
        });
        await refresh();
      }
      if (id === "task") {
        requireIdentity();
        const old = S.snap.follow_ups.find((f) => f.task.id === v.id);
        const body = {
          inspection_id: old?.details.inspection_id || visit(),
          physical_asset_id: old?.details.physical_asset_id || S.physical,
          project_id: old?.details.project_id || S.project,
          claim_id: v.claim_id || null,
          request: v.request,
          contact: v.contact,
          reviewer: v.reviewer,
          due_date: v.due_date,
          required_evidence: v.required_evidence,
          verification_method: v.verification_method,
          source: source(v.request),
          reason,
        };
        if (S.pendingCandidate) {
          const c = S.pendingCandidate;
          await U.api(root() + "/candidates/" + c.id + "/confirm", {
            method: "POST",
            body: {
              version: c.version,
              action: "accept",
              edited: c.edited,
              confirmed_source: true,
              follow_up: body,
              reason,
            },
          });
          S.pendingCandidate = null;
        } else
          await U.api(root() + "/follow-ups" + (old ? "/" + old.task.id : ""), {
            method: old ? "PATCH" : "POST",
            key: requestKey,
            body: old ? { ...body, version: old.details.version } : body,
          });
        await refresh();
      }
      if (id === "transition") {
        const f = S.snap.follow_ups.find((f) => f.task.id === v.id);
        await U.api(root() + "/follow-ups/" + f.task.id + "/transition", {
          method: "POST",
          body: {
            version: f.details.version,
            status: v.status,
            evidence_ids: d.getAll("evidence_ids"),
            verification_supported: !!v.verification_supported,
            review_inspection_id: v.review_inspection_id,
            reason: v.reason,
          },
        });
        await refresh();
      }
      if (id === "candidate") {
        const c = S.snap.candidates.find((c) => c.id === v.id);
        const edited = {
          ...c.payload,
          text: v.text,
          value: v.value || null,
          unit: v.unit || null,
          currency: v.currency || null,
          due_date: v.due_date || null,
        };
        if (edited.kind === "follow_up") {
          S.pendingCandidate = { ...c, edited };
          location.hash = "/followups";
          U.render();
        } else {
          await U.api(root() + "/candidates/" + c.id + "/confirm", {
            method: "POST",
            body: {
              version: c.version,
              action: "accept",
              project_id: S.project,
              project_version: project()?.version,
              edited,
              confirmed_source: !!v.confirmed_source,
              reason,
            },
          });
          await refresh();
        }
      }
      if (id === "compare") {
        if (v.first_id === v.second_id)
          throw Error("Choose two different clips.");
        await U.api(root() + "/audio-comparisons", {
          method: "POST",
          body: { first_id: v.first_id, second_id: v.second_id, reason },
        });
        await refresh();
      }
      U.note("Saved. Source attribution and audit history are retained.");
    });
  });
  document.addEventListener("input", (e) => {
    if (e.target.closest("[data-v2-form]")) S.dirty = true;
  });
  // Guard capture before the existing router or visit selector can replace the active context.
  document.addEventListener(
    "click",
    (e) => {
      if (
        (S.recording || S.pending || S.camera || S.mediaRequest) &&
        e.target.closest('a[href^="#/"],#logout')
      ) {
        e.preventDefault();
        e.stopImmediatePropagation();
        U.note(
          "Stop capture and wait for pending processing before leaving this view.",
          true,
        );
      }
    },
    true,
  );
  window.addEventListener(
    "hashchange",
    () => {
      if (!canNavigate()) {
        history.replaceState(null, "", "#/" + U.state.view);
        U.note("Capture is still active; stop it first.", true);
      }
    },
    true,
  );
  window.addEventListener("beforeunload", (e) => {
    if (S.recording || S.pending || S.clips.some((c) => !c.saved)) {
      e.preventDefault();
      e.returnValue = "";
    }
  });
  window.CDIV2 = { load, render, decorate, afterRender };
  // The case/visit header wraps differently on each phone and after case load.
  // Measure its actual height instead of guessing a fixed sticky offset.
  const appHeader = document.querySelector(".app-header");
  const appNav = document.querySelector(".nav-rail");
  function updateChromeSize() {
    for (const [element, name] of [
      [appHeader, "--app-header-height"],
      [appNav, "--app-nav-height"],
    ]) {
      const height = element?.getBoundingClientRect().height;
      if (height > 0)
        document.documentElement.style.setProperty(name, Math.ceil(height) + "px");
    }
  }
  if (typeof ResizeObserver !== "undefined") {
    const chromeObserver = new ResizeObserver(updateChromeSize);
    if (appHeader) chromeObserver.observe(appHeader);
    if (appNav) chromeObserver.observe(appNav);
  }
  window.addEventListener("resize", updateChromeSize);
  updateChromeSize();
  if (U.state.report) U.refresh().catch((e) => U.note(e.message, true));
})();
