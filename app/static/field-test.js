/* Capture/display/input client. Processing, comparisons and decisions stay on the server. */
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
      );
  const csrf = $('meta[name="csrf-token"]').content,
    analyst = document.body.dataset.role === "analyst";
  const S = {
    snap: null,
    session: null,
    capture: null,
    segment: null,
    analysis: null,
    audio: null,
    busy: false,
    camera: null,
    stream: null,
    recorder: null,
    sequence: 0,
    previewTimer: null,
    recordTimer: null,
    epoch: 0,
    pendingCapture: null,
    pendingAudio: null,
  };
  const key = () => crypto.randomUUID(),
    root = () => "/api/v1/cases/" + encodeURIComponent($("#case").value);
  const option = (v, label) =>
    `<option value="${esc(v)}">${esc(label)}</option>`;
  const fill = (selector, items, empty = "Choose…") => {
    const el = $(selector),
      old = el.value;
    el.innerHTML =
      option("", empty) + items.map((i) => option(i.id, i.label)).join("");
    if (items.some((i) => i.id === old)) el.value = old;
  };
  function notice(message, error = false) {
    $("#notice").textContent = message;
    $("#notice").classList.toggle("error", error);
  }
  async function api(path, { method = "GET", body, retryKey } = {}) {
    const headers = {};
    if (method !== "GET") {
      headers["X-CSRF-Token"] = csrf;
      headers["Idempotency-Key"] = retryKey || key();
    }
    if (body && !(body instanceof FormData) && !(body instanceof Blob)) {
      headers["Content-Type"] = "application/json";
      body = JSON.stringify(body);
    }
    const response = await fetch(path, {
      method,
      body,
      headers,
      credentials: "same-origin",
      signal: AbortSignal.timeout(90000),
    });
    if (!response.ok) {
      let detail;
      try {
        detail = (await response.json()).detail;
      } catch {
        detail = response.statusText;
      }
      const text = Array.isArray(detail)
        ? detail.map((e) => e.msg).join("; ")
        : typeof detail === "object"
          ? detail.message
          : detail;
      const error = new Error(
        `${text || "Request failed"} (HTTP ${response.status}; request ${response.headers.get("X-Request-ID") || "unknown"})`,
      );
      error.status = response.status;
      throw error;
    }
    return response.status === 204 ? null : response.json();
  }
  async function write(task, message) {
    if (S.busy) return;
    S.busy = true;
    document.body.classList.add("busy");
    try {
      await task();
      notice(message);
    } catch (e) {
      notice(e.message, true);
    } finally {
      S.busy = false;
      document.body.classList.remove("busy");
    }
  }
  function active(purpose) {
    if (!S.session || S.session.state === "CLOSED")
      throw Error("Start or reconnect a field session first.");
    if (purpose && S.session.purpose !== purpose)
      throw Error("Start a session for " + purpose + " first.");
    return S.session;
  }
  function visit() {
    return S.snap?.v1_inspections.find(
      (v) => v.inspection.id === $("#visit").value,
    );
  }
  function audioMeta() {
    const session = active();
    if (!["interview", "machine_acoustic"].includes(session.purpose))
      throw Error(
        "Choose Interview or Machine acoustic memory for this session.",
      );
    if (!$("#consent").checked)
      throw Error("Confirm recording authorization first.");
    if (session.purpose === "interview" && !$("#speaker").value.trim())
      throw Error(
        "Enter speaker attribution; roles are never inferred from voice.",
      );
    return {
      inspection_id: session.inspection_id,
      physical_asset_id: session.physical_asset_id,
      field_session_id: session.id,
      speaker_label:
        session.purpose === "interview" ? $("#speaker").value.trim() : null,
      capture_type:
        session.purpose === "machine_acoustic"
          ? "machine_acoustic"
          : "interview_speech",
      captured_at: new Date().toISOString(),
      device: session.device,
      operating_mode: $("#operating-mode").value || "unknown",
      load: $("#load").value || null,
      microphone_distance_cm: $("#distance").value
        ? Number($("#distance").value)
        : null,
      signal_processing:
        session.purpose === "machine_acoustic" ? "none_requested" : "unknown",
      note: $("#audio-note").value || "Field recording",
      consent_confirmed: true,
      consent_note:
        "Analyst confirmed recording authorization in the field client",
      synthetic: $("#synthetic").checked,
      reason: "Preserve authorized " + session.purpose + " original",
    };
  }
  async function loadCases() {
    const cases = await api("/api/v1/cases");
    fill(
      "#case",
      cases.map((c) => ({ id: c.id, label: c.company + " · " + c.site })),
      "Choose a case",
    );
    if (cases.length && !$("#case").value) $("#case").value = cases.at(-1).id;
    if ($("#case").value) await loadCase();
  }
  async function loadCase() {
    S.snap = await api(root() + "/export");
    fill(
      "#visit",
      S.snap.v1_inspections.map((v) => ({
        id: v.inspection.id,
        label: v.inspection.name,
      })),
      "Choose a visit",
    );
    if (!$("#visit").value)
      $("#visit").value = S.snap.v1_inspections.at(-1)?.inspection.id || "";
    fillContext();
    await records();
  }
  function fillContext() {
    const v = visit();
    fill(
      "#asset",
      (v?.assets || []).map((a) => ({
        id: a.id,
        label: [a.tag,a.nameplate_metadata?.manufacturer,a.model,(!a.serial||a.serial?.startsWith("UNVERIFIED-"))?"Serial unavailable / review":a.serial].filter(Boolean).join(" · "),
      })),
      "No intended machine yet",
    );
    const bindings = S.snap.asset_bindings.filter(
      (b) => b.active && b.inspection_id === v?.inspection.id,
    );
    fill(
      "#physical",
      bindings.map((b) => {
        const p = S.snap.physical_assets.find(
          (p) => p.id === b.physical_asset_id,
        );
        return { id: p.id, label: p.label + " · " + p.serial };
      }),
      "Case/project context only",
    );
    fill(
      "#project",
      S.snap.investments.map((p) => ({ id: p.id, label: p.title })),
      "No project selected",
    );
    fill(
      "#task",
      S.snap.follow_ups
        .filter((t) => t.task.inspection_id === v?.inspection.id)
        .map((t) => ({ id: t.task.id, label: t.task.request })),
      "No specific task",
    );
    fill(
      "#documentary-evidence",
      (v?.evidence || [])
        .filter(
          (e) =>
            e.confirmed &&
            ![
              "site_image",
              "site_observation",
              "management_statement",
              "financial_statement",
            ].includes(e.kind),
        )
        .map((e) => ({ id: e.id, label: e.filename })),
      "Select accepted documents",
    );
  }
  function showSession() {
    const session = S.session;
    $("#session-status").textContent = session
      ? `${session.id} · ${session.purpose} · ${session.state} · physical machine ${session.physical_asset_id || "not bound"}`
      : "No active session.";
    $("#context")
      .querySelectorAll("input,select,button")
      .forEach(
        (el) =>
          (el.disabled = !analyst || (!!session && session.state !== "CLOSED")),
      );
    $("#prepare").disabled =
      !analyst || (!!session && session.state !== "CLOSED");
  }
  async function sessionStatus() {
    const result = await api(root() + "/field-sessions/" + S.session.id);
    S.session = result.session;
    S.sequence = Math.max(S.sequence, result.transport.last_sequence + 1);
    showSession();
    return result;
  }
  async function startSession(event) {
    event.preventDefault();
    return write(async () => {
      if (S.session && S.session.state !== "CLOSED")
        throw Error("Close the current session before switching context.");
      const body = {
        inspection_id: $("#visit").value,
        purpose: $("#purpose").value,
        device: $("#device").value,
        intended_asset_id: $("#asset").value || null,
        physical_asset_id: $("#physical").value || null,
        project_id: $("#project").value || null,
        task_id: $("#task").value || null,
        expected_manufacturer: $("#manufacturer").value || null,
        reason: "Begin explicit field capture context",
      };
      S.session = await api(root() + "/field-sessions", {
        method: "POST",
        body,
      });
      S.capture = null;
      S.segment = null;
      S.audio = null;
      S.analysis = null;
      localStorage.setItem(
        "cdi.field.session",
        JSON.stringify({ caseId: $("#case").value, id: S.session.id }),
      );
      showSession();
    }, "Session saved. Camera scans can establish identity before binding.");
  }
  function stopCamera() {
    S.epoch++;
    clearTimeout(S.previewTimer);
    S.camera?.getTracks().forEach((t) => t.stop());
    S.camera = null;
    $("#camera").srcObject = null;
    $("#camera").hidden = true;
    $("#transport").textContent =
      "Camera stopped. Deliberate originals remain saved.";
  }
  async function camera() {
    active("identifier");
    if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia)
      throw Error(
        "Camera requires HTTPS on the tablet (localhost is desktop-only). File capture remains available.",
      );
    stopCamera();
    S.camera = await navigator.mediaDevices.getUserMedia({
      video: { facingMode: { ideal: "environment" }, width: { ideal: 1920 } },
      audio: false,
    });
    const video = $("#camera");
    video.srcObject = S.camera;
    video.hidden = false;
    await video.play();
    await sessionStatus();
    if (S.session.state !== "CONNECTED")
      S.session = await api(root() + "/field-sessions/" + S.session.id, {
        method: "PATCH",
        body: {
          version: S.session.version,
          state: "CONNECTED",
          reason: "Connect live camera preview",
        },
      });
    S.camera.getVideoTracks()[0].addEventListener("ended", () => {
      stopCamera();
      notice(
        "Camera permission or stream ended. Reopen the camera to reconnect.",
        true,
      );
    });
    showSession();
    sample(S.epoch);
  }
  async function frame(preview) {
    const video = $("#camera");
    if (!video.videoWidth) throw Error("Wait for the live camera preview.");
    let scale = 1;
    if (preview)
      scale = Math.min(
        1,
        640 / Math.max(video.videoWidth, video.videoHeight),
        Math.sqrt(307200 / (video.videoWidth * video.videoHeight)),
      );
    const canvas = document.createElement("canvas");
    canvas.width = Math.floor(video.videoWidth * scale);
    canvas.height = Math.floor(video.videoHeight * scale);
    canvas.getContext("2d").drawImage(video, 0, 0, canvas.width, canvas.height);
    return new Promise((resolve, reject) =>
      canvas.toBlob(
        (blob) =>
          blob
            ? resolve(blob)
            : reject(Error("Camera could not encode a frame.")),
        "image/jpeg",
        preview ? 0.55 : 0.93,
      ),
    );
  }
  async function sample(epoch, delay = 1000) {
    if (!S.camera || epoch !== S.epoch) return;
    try {
      const blob = await frame(true);
      if (epoch !== S.epoch) return;
      const ack = await api(
        root() +
          "/field-sessions/" +
          S.session.id +
          "/preview?sequence=" +
          S.sequence,
        { method: "POST", body: blob },
      );
      S.sequence = ack.sequence + 1;
      $("#transport").textContent =
        `Backend connected · ${ack.received_samples ?? "duplicate"} preview samples · server receipt ${ack.received_at}. Preview is not evidence.`;
      delay = 1000;
    } catch (e) {
      $("#transport").textContent =
        "Interrupted: " + e.message + " · reconnecting with bounded backoff.";
      delay = Math.min(delay * 2, 10000);
      if (e.status === 401 || e.status === 403) {
        stopCamera();
        return;
      }
      if (e.status === 409) {
        try {
          await sessionStatus();
        } catch {}
      }
    }
    if (epoch === S.epoch && S.camera)
      S.previewTimer = setTimeout(() => sample(epoch, delay), delay);
  }
  async function sendCapture(file) {
    active("identifier");
    if (!file?.size || file.size > 12 * 1024 * 1024)
      throw Error("Choose a JPEG/PNG original up to 12 MiB.");
    const body = new FormData();
    body.set("file", file);
    body.set(
      "metadata",
      JSON.stringify({
        captured_at: new Date().toISOString(),
        reason: "Deliberate evidence still; preview frames are separate",
      }),
    );
    S.pendingCapture = { body, file, key: key() };
    await retryCapture();
  }
  async function retryCapture() {
    const pending = S.pendingCapture;
    if (!pending) throw Error("No unsaved capture.");
    $("#capture-retry").hidden = false;
    $("#capture-download").hidden = false;
    S.capture = await api(
      root() + "/field-sessions/" + active("identifier").id + "/captures",
      { method: "POST", body: pending.body, retryKey: pending.key },
    );
    S.pendingCapture = null;
    $("#capture-retry").hidden = true;
    $("#capture-download").hidden = true;
    renderCapture();
    await records();
  }
  function renderCapture() {
    const c = S.capture;
    if (!c) return;
    const observed = c.working_fields || {};
    $("#capture-review").innerHTML =
      `<h3>${esc(c.state)}</h3>${c.raw_result?.registry_association?.tag?`<p>Registry candidate: ${esc(c.raw_result.registry_association.tag)} · ${esc(c.raw_result.registry_association.state)}. Original remains unaccepted; review required.</p>`:""}<p>${esc(c.comparison.decision || c.error || "Source saved")}</p><p>${esc(c.comparison.guidance || "Processing can be retried; the original remains saved.")}</p><a href="/api/v1/inspections/${esc(c.inspection_id)}/evidence/${esc(c.evidence_id)}/original" target="_blank" rel="noopener">Open protected original</a><details><summary>Raw OCR, QR, barcode and comparisons</summary><pre>${esc(JSON.stringify({ raw: c.raw_result, comparison: c.comparison }, null, 2))}</pre></details>
    <form id="review-capture"><label>Intended machine for this review<select name="intended_asset_id" required>${option("", "Choose explicitly")}${(visit()?.assets || []).map((a) => `<option value="${a.id}" ${a.id === c.intended_asset_id ? "selected" : ""}>${esc([a.tag,a.nameplate_metadata?.manufacturer,a.model,(!a.serial||a.serial?.startsWith("UNVERIFIED-"))?"Serial unavailable / review":a.serial].filter(Boolean).join(" · "))}</option>`).join("")}</select></label><div class="grid">${["manufacturer", "model", "serial", "site"].map((f) => `<label>Observed ${f}<input name="${f}" value="${esc(observed[f] || "")}" maxlength="200"></label>`).join("")}</div><p class="muted">Working values come from observed sources, never from expected database identifiers. Enter corrections only after checking the original.</p>
    <label class="check"><input name="checked_original" type="checkbox">I checked the original and explicitly confirm the reviewed identity.</label><label class="check"><input name="acknowledge_conflicts" type="checkbox">I reviewed conflicting sources and explain their resolution below.</label><label>Review reason<input name="reason" required maxlength="4000"></label>
    ${["correct", "accept", "reject", "rescan"].map((a) => `<button type="submit" value="${a}" data-write ${["ACCEPTED", "REJECTED"].includes(c.state) ? "disabled" : ""}>${a === "accept" ? "Accept and bind identity" : a === "correct" ? "Save correction" : a === "reject" ? "Reject" : "Request rescan"}</button>`).join("")}</form><button id="reprocess" type="button" data-write>Retry processing saved original</button>`;
  }
  async function reviewCapture(event) {
    event.preventDefault();
    const form = event.target,
      values = Object.fromEntries(new FormData(form)),
      action = event.submitter.value;
    await write(async () => {
      const fields = Object.fromEntries(
        ["manufacturer", "model", "serial", "site"].map((f) => [
          f,
          values[f]?.trim() || null,
        ]),
      );
      S.capture = await api(
        root() + "/visual-captures/" + S.capture.id + "/review",
        {
          method: "PATCH",
          body: {
            version: S.capture.version,
            action,
            fields,
            intended_asset_id: values.intended_asset_id || null,
            checked_original: !!values.checked_original,
            acknowledge_conflicts: !!values.acknowledge_conflicts,
            reason: values.reason,
          },
        },
      );
      renderCapture();
      await sessionStatus();
      await records();
    }, "Capture decision saved with the original processor output and audit history.");
  }
  function pendingAudio(file, metadata) {
    if (!file?.size || file.size > 12 * 1024 * 1024)
      throw Error("Audio must contain 1 byte to 12 MiB.");
    const body = new FormData();
    body.set("file", file);
    body.set("metadata", JSON.stringify(metadata));
    S.pendingAudio = { file, body, key: key(), metadata };
    return retryAudio();
  }
  async function retryAudio() {
    const p = S.pendingAudio;
    if (!p) throw Error("No unsaved audio.");
    $("#audio-retry").hidden = false;
    $("#audio-download").hidden = false;
    S.audio = await api(root() + "/audio", {
      method: "POST",
      body: p.body,
      retryKey: p.key,
    });
    S.pendingAudio = null;
    $("#audio-retry").hidden = true;
    $("#audio-download").hidden = true;
    $("#playback").src = root() + "/audio/" + S.audio.id + "/original";
    $("#playback").hidden = false;
    $("#audio-status").textContent =
      `Original saved · ${S.audio.duration_seconds}s · SHA-256 ${S.audio.sha256} · ${S.audio.processing_state}`;
    await records();
  }
  async function record() {
    const metadata = audioMeta();
    if (S.recorder?.state === "recording")
      throw Error("A recording is already active.");
    if (
      !window.isSecureContext ||
      !navigator.mediaDevices?.getUserMedia ||
      !window.MediaRecorder
    )
      throw Error(
        "Microphone capture requires HTTPS and MediaRecorder. Saved WAV/WebM/M4A files remain supported.",
      );
    const mime = [
      "audio/webm;codecs=opus",
      "audio/mp4;codecs=mp4a.40.2",
      "audio/mp4",
    ].find((m) => MediaRecorder.isTypeSupported(m));
    if (!mime)
      throw Error(
        "No supported recorder codec; upload a saved PCM WAV or M4A.",
      );
    S.stream = await navigator.mediaDevices.getUserMedia({
      audio:
        metadata.capture_type === "machine_acoustic"
          ? {
              echoCancellation: false,
              noiseSuppression: false,
              autoGainControl: false,
            }
          : true,
    });
    const chunks = [];
    try {
      S.recorder = new MediaRecorder(S.stream, { mimeType: mime });
    } catch (e) {
      S.stream.getTracks().forEach((t) => t.stop());
      S.stream = null;
      throw e;
    }
    S.recorder.ondataavailable = (e) => {
      if (e.data.size) chunks.push(e.data);
    };
    S.recorder.onstop = () => {
      clearTimeout(S.recordTimer);
      S.stream?.getTracks().forEach((t) => t.stop());
      S.stream = null;
      const blob = new Blob(chunks, { type: mime }),
        file = new File(
          [blob],
          "field-audio." + (mime.includes("mp4") ? "m4a" : "webm"),
          { type: mime },
        );
      write(
        () => pendingAudio(file, metadata),
        "Audio original saved. Interview processing is a separate deliberate action.",
      );
    };
    S.recorder.onerror = (e) => {
      notice(
        "Recorder error: " +
          (e.error?.message || "capture interrupted") +
          ". Completed bytes remain available after stop.",
        true,
      );
      if (S.recorder.state !== "inactive") S.recorder.stop();
    };
    S.stream.getAudioTracks()[0].onended = () => {
      if (S.recorder?.state === "recording") S.recorder.stop();
    };
    S.recorder.start();
    S.recordTimer = setTimeout(() => {
      if (S.recorder.state === "recording") S.recorder.stop();
    }, 115000);
    $("#audio-status").textContent =
      "Recording " +
      metadata.capture_type +
      " · stops before 120 seconds. Stop to save original.";
  }
  async function interviewForAudio() {
    if (!S.audio || S.audio.capture_type === "machine_acoustic")
      throw Error(
        "Select saved interview speech, not a machine acoustic clip.",
      );
    const prior = S.snap.segments.find((s) => s.recording_id === S.audio.id);
    if (prior)
      return S.snap.interviews.find((i) => i.id === prior.interview_id);
    const session = S.audio.field_session_id
        ? (await api(root() + "/field-sessions/" + S.audio.field_session_id))
            .session
        : null,
      speaker = S.audio.speaker_label || $("#speaker").value.trim();
    if (!speaker) throw Error("Enter analyst-provided speaker attribution.");
    return api(root() + "/interviews", {
      method: "POST",
      retryKey: "field-interview-" + S.audio.id,
      body: {
        inspection_id: S.audio.inspection_id,
        physical_asset_id: S.audio.physical_asset_id,
        project_id: session?.project_id || null,
        speaker_label: speaker,
        speaker_confirmed: false,
        consent_confirmed: true,
        consent_note: S.audio.consent_note,
        synthetic: S.audio.synthetic,
        reason: "Create attributed interview for saved field audio",
      },
    });
  }
  async function transcribe() {
    const interview = await interviewForAudio();
    S.segment = await api(root() + "/audio/" + S.audio.id + "/transcribe", {
      method: "POST",
      retryKey: "field-transcribe-" + S.audio.id + "-" + $("#language").value,
      body: {
        interview_id: interview.id,
        language: $("#language").value,
        reason: "Transcribe preserved original and retain source language",
      },
    });
    renderSegment();
    await records();
  }
  function renderSegment() {
    const s = S.segment;
    if (!s) return;
    $("#transcript").innerHTML =
      `<h3>Source-linked transcript · revision ${s.version}</h3><details><summary>Unchanged provider output</summary><pre>${esc(s.provider_text || "Manual or legacy source; see audit history.")}</pre><pre>${esc(s.provider_translation || "")}</pre></details><form id="correct-transcript"><label>Original-language working transcript<textarea name="text" required maxlength="4000">${esc(s.text)}</textarea></label><label>English translation<textarea name="translation" maxlength="4000">${esc(s.english_translation || "")}</textarea></label><label>Correction reason<input name="reason" required maxlength="4000"></label><button type="submit" data-write>Save transcript correction</button></form><label class="check"><input id="rules-fallback" type="checkbox">Allow labeled rules-only question fallback if Gemini is unavailable (no AI extraction).</label><button id="analyse" type="button" data-write>Suggest contextual questions and extraction proposals</button>`;
  }
  function renderAnalysis() {
    if (!S.analysis) return;
    const a = S.analysis;
    $("#analysis").innerHTML =
      `<h3>Analysis from ${esc(a.provider)} · proposals require review</h3>${a.notices.map((n) => `<p class="warning">${esc(n)}</p>`).join("")}<ul>${a.questions.map((q, i) => `<li>${esc(q.question)}<p>${esc(q.why)} · ${esc(q.source_quote)} · ${esc(q.status)}</p><button type="button" data-question="${i}" data-status="asked" data-write>Asked</button><button type="button" data-question="${i}" data-status="dismissed" data-write>Dismiss</button></li>`).join("")}</ul><label>Destination investment<select id="proposal-project">${option("", "Select a project when required")}${S.snap.investments.map((p) => option(p.id, p.title)).join("")}</select></label><div id="proposal-list"></div>`;
    $("#proposal-project").value = S.session?.project_id || "";
    const items = S.snap.candidates.filter((c) =>
      a.candidate_ids.includes(c.id),
    );
    $("#proposal-list").innerHTML = items
      .map(
        (c) =>
          `<form class="candidate record" data-candidate="${c.id}"><h3>${esc(c.payload.kind)} · ${esc(c.review_status)}</h3><p>Source: ${esc(c.payload.quote)}</p><label>Editable structured proposal<textarea name="payload" required>${esc(JSON.stringify(c.payload, null, 2))}</textarea></label><label class="check"><input name="confirmed_source" type="checkbox">I checked the original and interpreted this as a reported statement or forecast.</label><details><summary>Required only for a follow-up proposal</summary><label>Contact<input name="contact" maxlength="200"></label><label>Due date<input name="due_date" type="date"></label><label>Evidence requirement<textarea name="required_evidence" maxlength="4000"></textarea></label></details><label>Review reason<input name="reason" required maxlength="4000"></label><button value="edit" type="submit" data-write>Save edited proposal</button><button value="accept" type="submit" data-write>Accept attributed record</button><button value="reject" type="submit" data-write>Reject proposal</button></form>`,
      )
      .join("");
  }
  async function records() {
    if (!S.snap) return;
    S.snap = await api(root() + "/export");
    const captures = await api(root() + "/visual-captures");
    const docs = await api(root() + "/documentary-reviews");
    $("#records").innerHTML =
      `<h3>Visual captures</h3>${captures.map((c) => `<p><button type="button" data-capture="${c.id}">${esc(c.state)} · ${esc(c.received_at)}</button> ${esc(c.comparison.decision || c.error || "Persisted original")}</p>`).join("") || "<p>No saved visual captures.</p>"}<h3>Protected audio and transcripts</h3>${S.snap.audio.map((a) => `<p>${esc(a.capture_type)} · ${a.duration_seconds}s · ${esc(a.processing_state)} <button type="button" data-audio="${a.id}">Select saved recording</button> <a href="${root()}/audio/${a.id}/original" target="_blank" rel="noopener">Original</a></p>`).join("")}${S.snap.segments.map((s) => `<p><button type="button" data-segment="${s.id}">Transcript revision ${s.version}</button> ${esc(s.text.slice(0, 90))}</p>`).join("")}`;
    $("#documentary-results").innerHTML = docs
      .map(
        (d) =>
          `<p>${esc(d.review.proposition)} · ${esc(d.review.status)} · ${d.source_current ? "Sources current" : "REVIEW REQUIRED: source changed"} · documentary, not physical verification.</p>`,
      )
      .join("");
    const audio = S.snap.audio.filter(
      (a) => a.capture_type === "machine_acoustic",
    );
    fill(
      "#first-audio",
      audio.map((a) => ({
        id: a.id,
        label: a.captured_at + " · " + a.physical_asset_id,
      })),
    );
    fill(
      "#second-audio",
      audio.map((a) => ({
        id: a.id,
        label: a.captured_at + " · " + a.physical_asset_id,
      })),
    );
    $("#tasks").innerHTML = S.snap.follow_ups
      .map(
        (t) =>
          `<form class="task record" data-task="${t.task.id}"><h3>${esc(t.task.request)}</h3><p>${esc(t.details.workflow_status)} · ${esc(t.details.required_evidence)} · reviewer ${esc(t.details.reviewer)}</p><label>Next state<select name="status">${["awaiting_information", "submitted_for_review", "needs_more_evidence", "closed", "open"].map((s) => option(s, s)).join("")}</select></label><label>Stored evidence IDs, comma-separated<input name="evidence_ids" value="${esc(t.details.submitted_evidence_ids.join(","))}"></label><label class="check"><input name="verification_supported" type="checkbox">I verified the underlying requirement using accepted sources.</label><label>Response/reason<input name="reason" required maxlength="4000"></label><button type="submit" data-write>Save task transition</button></form>`,
      )
      .join("");
    $("#audit").textContent = JSON.stringify(
      S.snap.audit_events?.slice(-30) || [],
      null,
      2,
    );
    $("#exports").innerHTML =
      `<a href="${root()}/report.pdf" target="_blank" rel="noopener">PDF report</a> · <a href="${root()}/report" target="_blank" rel="noopener">Readable report</a> · <a href="${root()}/export" target="_blank" rel="noopener">JSON export</a>`;
  }
  function download(file) {
    const url = URL.createObjectURL(file),
      a = document.createElement("a");
    a.href = url;
    a.download = file.name || "unsaved-original";
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1500);
  }
  const actions = {
    prepare: () =>
      write(async () => {
        const trial = await api("/api/v1/demo/prepare", {
          method: "POST",
          body: { reason: "Separate synthetic field bench trial" },
        });
        await api("/api/v1/cases", {
          method: "POST",
          body: {
            inspection_id: trial.id,
            company: "Synthetic field trial",
            site: trial.site,
            reason:
              "Group field bench evidence without resetting existing records",
          },
        });
        await loadCases();
      }, "Fresh synthetic case ready."),
    resume: () =>
      write(async () => {
        const saved = JSON.parse(
          localStorage.getItem("cdi.field.session") || "null",
        );
        if (!saved) throw Error("No saved session in this browser.");
        if (S.camera || S.recorder?.state === "recording")
          throw Error("Stop capture before reconnecting context.");
        $("#case").value = saved.caseId;
        await loadCase();
        const result = await api(root() + "/field-sessions/" + saved.id);
        S.session = result.session;
        if (S.session.state === "CLOSED")
          throw Error("Saved session is closed; start a new one.");
        $("#visit").value = S.session.inspection_id;
        fillContext();
        S.sequence = result.transport.last_sequence + 1;
        showSession();
      }, "Session retrieved. Reopen camera/microphone explicitly; permission is never assumed."),
    "close-session": () =>
      write(async () => {
        if (
          S.pendingCapture ||
          S.pendingAudio ||
          S.recorder?.state === "recording"
        )
          throw Error("Stop and save/download pending media before closing.");
        stopCamera();
        await sessionStatus();
        S.session = await api(root() + "/field-sessions/" + S.session.id, {
          method: "PATCH",
          body: {
            version: S.session.version,
            state: "CLOSED",
            reason: "Analyst closed field capture session",
          },
        });
        showSession();
      }, "Session closed; persisted evidence and history retained."),
    "camera-start": () =>
      write(
        camera,
        "Live camera connected. Deliberate evidence capture remains separate.",
      ),
    "camera-stop": stopCamera,
    capture: () =>
      write(async () => {
        const blob = await frame(false);
        await sendCapture(
          new File([blob], "field-label.jpg", { type: "image/jpeg" }),
        );
      }, "Capture source and processing result saved. Review deliberately."),
    "capture-retry": () =>
      write(
        retryCapture,
        "Capture retry retrieved the saved result without duplicating it.",
      ),
    "capture-download": () =>
      S.pendingCapture && download(S.pendingCapture.file),
    reprocess: () =>
      write(async () => {
        S.capture = await api(
          root() + "/visual-captures/" + S.capture.id + "/process",
          {
            method: "POST",
            body: {
              version: S.capture.version,
              reason: "Retry processor using the saved original",
            },
          },
        );
        renderCapture();
      }, "Saved source reprocessed; review its explicit result."),
    "record-start": () => write(record, "Microphone recording started."),
    "record-stop": () => {
      if (S.recorder?.state === "recording") S.recorder.stop();
    },
    "audio-retry": () =>
      write(retryAudio, "Original audio saved without duplicate retry."),
    "audio-download": () => S.pendingAudio && download(S.pendingAudio.file),
    transcribe: () =>
      write(
        transcribe,
        "Transcript and translation saved alongside the original audio.",
      ),
    analyse: () =>
      write(async () => {
        S.analysis = await api(
          root() + "/segments/" + S.segment.id + "/analyse",
          {
            method: "POST",
            body: {
              allow_rule_fallback: $("#rules-fallback").checked,
              reason: "Request source-linked questions and editable proposals",
            },
          },
        );
        await records();
        renderAnalysis();
      }, "Analysis saved as proposals; no statement was automatically accepted."),
    refresh: () =>
      write(async () => {
        await records();
        fillContext();
      }, "Saved backend records refreshed."),
  };
  document.addEventListener("click", (event) => {
    const button = event.target.closest("button");
    if (!button) return;
    if (actions[button.id]) {
      event.preventDefault();
      actions[button.id]();
    } else if (button.dataset.capture)
      write(async () => {
        S.capture = (await api(root() + "/visual-captures")).find(
          (c) => c.id === button.dataset.capture,
        );
        renderCapture();
      }, "Saved capture retrieved.");
    else if (button.dataset.audio)
      write(async () => {
        S.audio = S.snap.audio.find((a) => a.id === button.dataset.audio);
        $("#playback").src = root() + "/audio/" + S.audio.id + "/original";
        $("#playback").hidden = false;
      }, "Saved recording selected.");
    else if (button.dataset.segment)
      write(async () => {
        S.segment = await api(root() + "/segments/" + button.dataset.segment);
        renderSegment();
      }, "Saved transcript retrieved.");
    else if (button.dataset.question !== undefined)
      write(async () => {
        S.analysis = await api(
          root() + "/analyses/" + S.analysis.id + "/question",
          {
            method: "PATCH",
            body: {
              version: S.analysis.version,
              index: Number(button.dataset.question),
              status: button.dataset.status,
              reason:
                "Analyst marked contextual question " + button.dataset.status,
            },
          },
        );
        renderAnalysis();
      }, "Question disposition saved.");
  });
  document.addEventListener("submit", (event) => {
    if (event.target.id === "context") return startSession(event);
    event.preventDefault();
    const form = event.target,
      v = Object.fromEntries(new FormData(form));
    if (form.id === "review-capture") return reviewCapture(event);
    if (form.id === "manual-transcript")
      return write(async () => {
        const i = await interviewForAudio();
        S.segment = await api(root() + "/interviews/" + i.id + "/segments", {
          method: "POST",
          body: {
            text: v.text,
            language: $("#language").value,
            english_translation: v.translation || null,
            translation_origin: v.translation ? "human" : null,
            recording_id: S.audio.id,
            start_ms: 0,
            end_ms: Math.floor(S.audio.duration_seconds * 1000),
            mode: "manual",
            reason: v.reason,
          },
        });
        renderSegment();
        await records();
      }, "Human transcript saved and labeled manual. No provider output was fabricated.");
    if (form.id === "correct-transcript")
      return write(async () => {
        const s = S.segment;
        S.segment = await api(root() + "/segments/" + s.id, {
          method: "PATCH",
          body: {
            version: s.version,
            text: v.text,
            language: s.language,
            english_translation: v.translation || null,
            translation_origin: v.translation ? "human" : null,
            recording_id: s.recording_id,
            start_ms: s.start_ms,
            end_ms: s.end_ms,
            mode: s.mode,
            reason: v.reason,
          },
        });
        renderSegment();
        await records();
      }, "Correction saved. Original provider output remains; dependent proposals require review.");
    if (form.id === "investment")
      return write(async () => {
        const session = active();
        const p = await api(root() + "/investments", {
          method: "POST",
          body: {
            ...v,
            inspection_id: session.inspection_id,
            asset_links: session.physical_asset_id
              ? [
                  {
                    physical_asset_id: session.physical_asset_id,
                    role: "existing",
                  },
                ]
              : [],
            source: {
              kind: "management_report",
              attribution:
                $("#speaker").value || "Analyst-entered reported rationale",
              quote: v.rationale,
            },
            reason: "Record an attributed proposal, not verified spending",
          },
        });
        await records();
        fillContext();
        $("#project").value = p.id;
      }, "Investment proposal saved. Forecasts remain separate from achieved outcomes.");
    if (form.id === "documentary")
      return write(async () => {
        await api(root() + "/documentary-reviews", {
          method: "POST",
          body: {
            ...v,
            inspection_id: $("#visit").value,
            project_id: $("#project").value || null,
            declared_quantity: Number(v.declared_quantity),
            supported_quantity:
              v.supported_quantity === "" ? null : Number(v.supported_quantity),
            evidence_ids: new FormData(form)
              .getAll("evidence_ids")
              .filter(Boolean),
            checked_originals: !!v.checked_originals,
          },
        });
        await records();
      }, "Documentary review saved without claiming physical verification.");
    if (form.id === "compare-audio")
      return write(async () => {
        $("#comparison").textContent = JSON.stringify(
          await api(root() + "/audio-comparisons", {
            method: "POST",
            body: {
              first_id: $("#first-audio").value,
              second_id: $("#second-audio").value,
              reason:
                "Compare descriptive signal features with recorded capture context",
            },
          }),
          null,
          2,
        );
      }, "Descriptive comparison saved; no health or fault verdict.");
    if (form.dataset.task)
      return write(async () => {
        const t = S.snap.follow_ups.find(
          (t) => t.task.id === form.dataset.task,
        );
        await api(root() + "/follow-ups/" + t.task.id + "/transition", {
          method: "POST",
          body: {
            version: t.details.version,
            status: v.status,
            evidence_ids: v.evidence_ids
              .split(",")
              .map((s) => s.trim())
              .filter(Boolean),
            verification_supported: !!v.verification_supported,
            review_inspection_id: $("#visit").value,
            reason: v.reason,
          },
        });
        await records();
      }, "Task transition saved under the existing evidence review rules.");
    if (form.dataset.candidate) {
      const action = event.submitter.value;
      return write(async () => {
        const c = S.snap.candidates.find(
            (c) => c.id === form.dataset.candidate,
          ),
          payload = JSON.parse(v.payload);
        if (action === "edit")
          await api(root() + "/candidates/" + c.id, {
            method: "PATCH",
            body: { version: c.version, payload, reason: v.reason },
          });
        else {
          const projectId = $("#proposal-project").value || null,
            p = S.snap.investments.find((p) => p.id === projectId);
          const followUp =
            c.payload.kind === "follow_up"
              ? {
                  inspection_id: c.inspection_id,
                  physical_asset_id: c.physical_asset_id,
                  project_id: projectId,
                  request: payload.text,
                  contact: v.contact,
                  reviewer: S.capabilities.analyst_actors[0],
                  due_date: v.due_date,
                  required_evidence: v.required_evidence,
                  verification_method: "document_review",
                  source: {
                    kind: "management_report",
                    attribution: "Interview proposal",
                    quote: payload.quote,
                  },
                  reason: v.reason,
                }
              : null;
          await api(root() + "/candidates/" + c.id + "/confirm", {
            method: "POST",
            body: {
              version: c.version,
              action,
              edited: payload,
              project_id: projectId,
              project_version: p?.version || null,
              confirmed_source: !!v.confirmed_source,
              follow_up: followUp,
              reason: v.reason,
            },
          });
        }
        await records();
        renderAnalysis();
      }, "Proposal decision saved with attribution and source linkage.");
    }
  });
  $("#case").addEventListener("change", () => write(loadCase, "Case loaded."));
  $("#visit").addEventListener("change", fillContext);
  $("#label-file").addEventListener("change", (event) => {
    const file = event.target.files[0];
    if (file)
      write(
        () => sendCapture(file),
        "Original label and processing result saved.",
      );
  });
  $("#audio-file").addEventListener("change", (event) => {
    const file = event.target.files[0];
    if (file)
      write(
        () => pendingAudio(file, audioMeta()),
        "Original audio saved; processing is separate.",
      );
  });
  window.addEventListener("beforeunload", (event) => {
    if (
      S.pendingCapture ||
      S.pendingAudio ||
      S.recorder?.state === "recording"
    ) {
      event.preventDefault();
      event.returnValue = "";
    }
  });
  window.addEventListener("pagehide", () => {
    stopCamera();
    S.stream?.getTracks().forEach((t) => t.stop());
  });
  if (!analyst)
    document
      .querySelectorAll("[data-write]")
      .forEach((el) => (el.disabled = true));
  (async () => {
    try {
      S.capabilities = await api("/api/v1/capabilities");
      $("#diagnostics").textContent = JSON.stringify(
        {
          ...S.capabilities,
          secure_context: window.isSecureContext,
          media_api: !!navigator.mediaDevices?.getUserMedia,
        },
        null,
        2,
      );
      await loadCases();
      notice(
        analyst
          ? "Backend connected. Start a field session or prepare a separate synthetic trial."
          : "Judge access: saved permitted records only; writes remain server-restricted.",
      );
    } catch (e) {
      notice(e.message, true);
    }
  })();
})();
