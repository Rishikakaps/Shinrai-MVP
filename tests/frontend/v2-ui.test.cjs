/* DOM/state unit checks only. These do not replace real Chrome/camera tests. */
const { test } = require("node:test");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const { JSDOM } = require(process.env.CDI_JSDOM_PATH || "jsdom");
const code = fs.readFileSync("app/static/v2-app.js", "utf8");
const tick = () => new Promise((r) => setTimeout(r, 15));
function fixture({ judge = false, unconfirmed = false, noCase = false } = {}) {
  const dom = new JSDOM(
    '<body data-role="' +
      (judge ? "judge" : "analyst") +
      '" data-actor="Demo Analyst"><div id="workspace"></div><div id="v2-case-control"></div><select id="inspection-picker"></select></body>',
    { url: "http://localhost/app", runScripts: "outside-only" },
  );
  const w = dom.window;
  w.crypto.randomUUID = require("node:crypto").randomUUID;
  w.structuredClone = structuredClone;
  const asset = {
    id: "local-1",
    tag: "CNC-003",
    serial: "SYN-001",
    model: "DemoMill",
    site: "Plant A",
  };
  const report = {
    inspection: { id: "visit-1", site: "Plant A", name: "Visit 1" },
    assets: [asset],
    claims: [{ id: "claim-1", asset_id: asset.id, kind: "commissioning" }],
    evidence: [
      {
        id: "ev-1",
        filename: "identity.txt",
        confirmed: true,
        kind: "equipment_register",
        facts: { serial: asset.serial, model: asset.model, site: asset.site },
      },
    ],
    findings: [],
    reconciliation_current: true,
  };
  const snap = {
    case: { id: "case-1", company: "Synthetic Company", site: "Plant A" },
    v1_inspections: [report],
    physical_assets: unconfirmed
      ? []
      : [
          {
            id: "physical-1",
            label: asset.tag,
            serial: asset.serial,
            model: asset.model,
          },
        ],
    asset_bindings: unconfirmed
      ? []
      : [
          {
            id: "bind-1",
            active: true,
            inspection_id: "visit-1",
            local_asset_id: asset.id,
            physical_asset_id: "physical-1",
          },
        ],
    investments: [
      {
        id: "project-1",
        inspection_id: "visit-1",
        version: 1,
        title: "Replace CNC",
        kind: "replacement",
        stage: "proposed",
        rationale: "Reported downtime",
        asset_links: [{ physical_asset_id: "physical-1", role: "existing" }],
        source: {
          kind: "management_report",
          attribution: "Manager",
          quote: "Considering replacement",
        },
      },
    ],
    targets: [],
    investment_reviews: [],
    follow_ups: [],
    audio: [],
    segments: [],
    interviews: [],
    comparisons: [],
    analyses: [],
    candidates: [],
  };
  const calls = [],
    messages = [];
  let fail = false;
  const U = {
    state: { iid: "visit-1", aid: asset.id, view: "interview", report },
    analyst: !judge,
    legacy: {
      overview: () => "<p>Legacy claims</p>",
      siteView: () => "<p>Legacy observations</p>",
    },
    note: (m, e) => messages.push({ m, e }),
    api: async (url, o = {}) => {
      calls.push({ url, ...o });
      if (o.method && fail) throw Error("Simulated network interruption");
      if (url === "/api/v1/cases") return noCase ? [] : [snap.case];
      if (url === "/api/v1/capabilities")
        return {
          ai_configured: false,
          audio_decode_available: true,
          analyst_actors: ["Demo Analyst"],
        };
      if (url.endsWith("/inspections")) return [report.inspection];
      if (url.endsWith("/export")) return structuredClone(snap);
      if (url.endsWith("/chat")) return [];
      return { id: "new-record" };
    },
    render: () => {
      const x = w.CDIV2.render(U.state.view);
      w.document.querySelector("#workspace").innerHTML =
        x || "<p>Legacy page</p>";
      w.CDIV2.afterRender();
    },
    refresh: async () => {
      await w.CDIV2.load();
      U.render();
    },
    changeVisit: async () => {},
  };
  w.IntegrityUI = U;
  w.eval(code);
  return {
    dom,
    w,
    U,
    snap,
    report,
    calls,
    messages,
    setFail: (v) => (fail = v),
    async ready() {
      await tick();
      return this;
    },
    page(view) {
      U.state.view = view;
      U.render();
    },
    get: (s) => w.document.querySelector(s),
    all: (s) => [...w.document.querySelectorAll(s)],
  };
}
function submit(f, form) {
  form.dispatchEvent(
    new f.w.Event("submit", { bubbles: true, cancelable: true }),
  );
}

test("all seven surfaces render without replacing the legacy review contract", async () => {
  const f = await fixture().ready();
  for (const v of [
    "overview",
    "site",
    "investments",
    "followups",
    "wearable",
  ]) {
    f.page(v);
    assert.ok(f.get("#workspace h1"), v);
  }
  for (const v of ["evidence", "assessment"]) {
    f.page(v);
    f.w.CDIV2.decorate(v);
    if(v==="assessment")assert.ok(f.get("#v2-machine"),v);
    else {assert.equal(f.get("[data-v2-form=identity]"),null);assert.equal(f.get("#v2-label-file"),null);}
  }
  f.dom.window.close();
});
test("unconfirmed identity disables recording and exposes explicit confirmation", async () => {
  const f = await fixture({ unconfirmed: true }).ready();
  f.page("identity");
  assert.ok(f.get("[data-v2-form=identity]"));
  f.page("interview");
  assert.equal(f.get("[data-v2=record]"), null);
  assert.match(f.get("#workspace").textContent, /Identity not confirmed/);
  f.dom.window.close();
});
test("empty V2 case offers enrollment and preserves V1 work", async () => {
  const f = await fixture({ noCase: true }).ready();
  f.page("overview");
  assert.ok(f.get("[data-v2-form=case]"));
  assert.match(f.get("#workspace").textContent, /Legacy claims/);
  f.dom.window.close();
});
test("judge sees records but no capture/project/task write forms", async () => {
  const f = await fixture({ judge: true }).ready();
  assert.equal(f.get("[data-v2=record]"), null);
  assert.equal(f.get("[data-v2-form=segment]"), null);
  f.page("investments");
  assert.equal(f.get("[data-v2-form=project]"), null);
  f.page("followups");
  assert.equal(f.get("[data-v2-form=task]"), null);
  f.dom.window.close();
});
test("judge cannot dispatch a write via a forged DOM button", async () => {
  const f = await fixture({ judge: true }).ready();
  const b = f.w.document.createElement("button");
  b.dataset.v2 = "reminders";
  f.get("#workspace").append(b);
  b.click();
  await tick();
  assert.ok(f.messages.some((m) => /read-only/.test(m.m)));
  assert.equal(f.calls.filter((c) => c.method === "POST").length, 0);
  f.dom.window.close();
});
test("microphone permission requires informed consent before any capture request", async () => {
  const f = await fixture().ready();
  f.get("[data-v2=record]").click();
  await tick();
  assert.match(f.messages.at(-1).m, /authorization/);
  assert.equal(f.calls.filter((c) => c.url.endsWith("/audio")).length, 0);
  f.dom.window.close();
});
test("camera API absence explains HTTPS/file-upload fallback", async () => {
  const f = await fixture().ready();
  f.page("site");
  f.get("[data-v2=camera]").click();
  await tick();
  assert.match(f.messages.at(-1).m, /HTTPS/);
  assert.ok(f.get("#v2-label-file"));
  f.dom.window.close();
});
test("project retry preserves fields and idempotency key; changed payload gets a new key", async () => {
  const f = await fixture().ready();
  f.page("investments");
  const form = f.get("[data-v2-form=project]");
  form.elements.title.value = "Replacement";
  form.elements.rationale.value = "Downtime reported";
  form.elements.source_quote.value = "Considering replacement";
  f.setFail(true);
  submit(f, form);
  await tick();
  submit(f, form);
  await tick();
  let writes = f.calls.filter(
    (c) => c.url.endsWith("/investments") && c.method === "POST",
  );
  assert.equal(writes.length, 2);
  assert.equal(writes[0].key, writes[1].key);
  assert.equal(form.elements.title.value, "Replacement");
  form.elements.title.value = "Revised replacement";
  submit(f, form);
  await tick();
  writes = f.calls.filter(
    (c) => c.url.endsWith("/investments") && c.method === "POST",
  );
  assert.notEqual(writes[1].key, writes[2].key);
  f.dom.window.close();
});
test("same-audio comparison is blocked before sending a request", async () => {
  const f = await fixture().ready();
  f.snap.audio = [
    {
      id: "a1",
      physical_asset_id: "physical-1",
      capture_type: "machine_acoustic",
      filename: "one.wav",
      duration_seconds: 1,
      created_at: "2026-10-25",
      quality_flags: [],
    },
    {
      id: "a2",
      physical_asset_id: "physical-1",
      capture_type: "machine_acoustic",
      filename: "two.wav",
      duration_seconds: 1,
      created_at: "2026-10-25",
      quality_flags: [],
    },
  ];
  await f.U.refresh();
  f.page("recordings");
  const form = f.get("[data-v2-form=compare]");
  form.elements.second_id.value = "a1";
  submit(f, form);
  await tick();
  assert.match(f.messages.at(-1).m, /different clips/);
  assert.equal(
    f.calls.filter((c) => c.url.endsWith("/audio-comparisons")).length,
    0,
  );
  f.dom.window.close();
});
test("backend text is escaped in the rendered investment and questions", async () => {
  const f = await fixture().ready();
  f.snap.investments[0].rationale = "<img src=x onerror=alert(1)>";
  await f.U.refresh();
  f.page("investments");
  assert.equal(f.get("img[onerror]"), null);
  assert.match(f.get("#workspace").textContent, /<img src=x/);
  f.dom.window.close();
});
test("wearable preview explicitly states no hardware connection", async () => {
  const f = await fixture().ready();
  f.page("wearable");
  assert.match(f.get("#workspace").textContent, /no glasses connected/);
  assert.match(f.get("#workspace").textContent, /SDK integration is pending/);
  f.dom.window.close();
});

test("denied microphone permission leaves capture idle and retryable", async () => {
  const f = await fixture().ready();
  Object.defineProperty(f.w.navigator, "mediaDevices", {
    value: {
      getUserMedia: async () => {
        throw new f.w.DOMException("Permission denied", "NotAllowedError");
      },
    },
  });
  f.w.MediaRecorder = class {
    static isTypeSupported() {
      return true;
    }
  };
  f.get("#v2-consent").checked = true;
  f.get("[data-v2=record]").click();
  await tick();
  assert.match(f.messages.at(-1).m, /Permission denied/);
  assert.equal(f.get("[data-v2=record]").disabled, false);
  f.dom.window.close();
});
test("revised target does not inherit a supported outcome from an older target version", async () => {
  const f = await fixture().ready();
  f.snap.targets = [
    {
      id: "target-1",
      project_id: "project-1",
      version: 2,
      metric: "downtime_hours",
      target_value: "50",
      target_type: "reduction_percent",
      unit: "hours",
      source: { quote: "Forecast", attribution: "Manager" },
    },
  ];
  f.snap.investment_reviews = [
    {
      target_id: "target-1",
      target_version: 1,
      status: "supported",
      kind: "outcome",
      methodology: "Prior review",
      calculation: {},
    },
  ];
  await f.U.refresh();
  f.page("investments");
  assert.match(f.get("table").textContent, /Target revised/);
  f.dom.window.close();
});
test("cancelled context change retains unsaved source text", async () => {
  const f = await fixture().ready();
  const field = f.get("[data-v2-form=segment] textarea");
  field.value = "Unsaved source";
  field.dispatchEvent(new f.w.Event("input", { bubbles: true }));
  f.w.confirm = () => false;
  const picker = f.get("#v2-project");
  picker.value = "";
  picker.dispatchEvent(new f.w.Event("change", { bubbles: true }));
  assert.equal(field.value, "Unsaved source");
  assert.equal(picker.value, "project-1");
  f.dom.window.close();
});
test("chat failure preserves the question and never fabricates an answer", async () => {
  const f = await fixture().ready();
  const form = f.get("[data-v2-form=chat]");
  form.elements.question.value = "What evidence is missing?";
  f.setFail(true);
  submit(f, form);
  await tick();
  assert.equal(form.elements.question.value, "What evidence is missing?");
  assert.match(f.messages.at(-1).m, /network interruption/);
  assert.equal(f.get(".v2-chat article"), null);
  f.dom.window.close();
});

for (const kind of ['camera', 'microphone']) {
  test(`pending ${kind} permission can be cancelled and a late stream is stopped`, async () => {
    const f = await fixture().ready();
    let resolvePermission;
    let stopped = 0;
    Object.defineProperty(f.w.navigator, 'mediaDevices', {
      value: { getUserMedia: () => new Promise(resolve => { resolvePermission = resolve; }) },
    });
    f.w.MediaRecorder = class { static isTypeSupported() { return true; } };
    if(kind==='camera')f.page('site');
    if(f.get('#v2-consent'))f.get('#v2-consent').checked = true;
    f.get(kind === 'camera' ? '[data-v2=camera]' : '[data-v2=record]').click();
    await tick();
    assert.match(f.messages.at(-1).m, new RegExp(`Waiting for ${kind} permission`));
    assert.equal(f.get('#inspection-picker').disabled, true);
    const stop = f.get(kind === 'camera' ? '[data-v2=camera-stop]' : '[data-v2=stop]');
    assert.equal(stop.disabled, false);
    stop.click();
    await tick();
    assert.match(f.messages.at(-1).m, /cancelled/);
    assert.equal(f.get('#inspection-picker').disabled, false);
    resolvePermission({ getTracks: () => [{ stop: () => stopped++ }] });
    await tick();
    assert.equal(stopped, 1);
    if(kind==='camera'){assert.equal(f.get('#v2-camera').hidden,true);assert.equal(f.get('[data-v2=camera]').disabled,false);}
    else assert.equal(f.get('[data-v2=record]').disabled,false);
    f.dom.window.close();
  });
}


test("empty identity source shows a disabled explanation and no submission form", async()=>{
 const f=await fixture({unconfirmed:true}).ready();f.report.evidence[0].confirmed=false;f.page('identity');
 const select=f.get('[name=identity_evidence_id]');assert.equal(select.disabled,true);assert.match(select.textContent,/No accepted identity evidence/);assert.equal(f.get('[data-v2-form=identity]'),null);assert.ok(f.get('a[href="#/evidence"]'));f.dom.window.close();
});
test("capture, identity and interview are separate surfaces",async()=>{
 const f=await fixture().ready();f.page('site');assert.ok(f.get('#v2-label-file'));assert.equal(f.get('[data-v2-form=identity]'),null);assert.equal(f.get('[data-v2=record]'),null);
 f.page('identity');assert.equal(f.get('#v2-label-file'),null);assert.equal(f.get('[data-v2=record]'),null);
 f.page('interview');assert.ok(f.get('[data-v2=record]'));assert.equal(f.get('#v2-label-file'),null);assert.equal(f.get('[data-v2-form=identity]'),null);f.dom.window.close();
});

test("review source action changes route rather than scrolling to another section",async()=>{
 const f=await fixture().ready();f.page('site');f.get('#workspace').insertAdjacentHTML('beforeend','<button data-v2="review-scan">Review saved source</button>');f.get('[data-v2=review-scan]').click();await tick();assert.equal(f.w.location.hash,'#/evidence');assert.equal(f.U.state.view,'evidence');assert.equal(f.U.state.evidenceStep,2);assert.ok(!f.messages.some(m=>m.e));f.dom.window.close();
});
