/* Full-stack DOM harness: actual app scripts + actual HTTP API, no browser/hardware emulation claims. */
"use strict";
const fs = require("node:fs"),
  assert = require("node:assert/strict");
const { JSDOM } = require(process.env.CDI_JSDOM_PATH || "jsdom");
const base = process.env.CDI_UI_URL || "http://127.0.0.1:8003";
const token = process.env.CDI_ANALYST_TOKEN;
const report = {
  kind: "actual HTTP plus DOM script execution; not a physical-browser/camera test",
  checks: [],
  issues: [],
};
const wait = async (fn, label) => {
  for (let i = 0; i < 150; i++) {
    if (fn()) return;
    await new Promise((r) => setTimeout(r, 60));
  }
  throw Error("Timed out: " + label);
};
(async () => {
  if (!token) throw Error("Private analyst token required");
  const login = await fetch(base + "/login");
  const nonce = /name="nonce" value="([^"]+)"/.exec(await login.text())[1];
  const nonceCookie = login.headers
    .getSetCookie()
    .map((c) => c.split(";")[0])
    .join("; ");
  const signed = await fetch(base + "/login", {
    method: "POST",
    redirect: "manual",
    headers: {
      Cookie: nonceCookie,
      Origin: base,
      "Content-Type": "application/x-www-form-urlencoded",
    },
    body: new URLSearchParams({ token, nonce }),
  });
  assert.equal(signed.status, 303);
  const cookie = signed.headers
    .getSetCookie()
    .map((c) => c.split(";")[0])
    .join("; ");
  const html = await (
    await fetch(base + "/app", { headers: { Cookie: cookie } })
  ).text();
  assert.match(html, /v2-app.js/);
  const dom = new JSDOM(html, {
      url: base + "/app",
      runScripts: "outside-only",
      pretendToBeVisual: true,
    }),
    w = dom.window;
  w.fetch = (path, init = {}) =>
    fetch(new URL(path, base), {
      ...init,
      headers: { ...init.headers, Cookie: cookie, Origin: base },
    });
  w.AbortSignal = AbortSignal;
  w.crypto.randomUUID = require("node:crypto").randomUUID;
  w.confirm = () => true;
  w.matchMedia = () => ({ matches: false });
  w.HTMLElement.prototype.scrollIntoView = () => {};
  w.HTMLElement.prototype.scrollBy = () => {};
  w.addEventListener("error", (e) => report.issues.push(e.message));
  w.eval(fs.readFileSync("app/static/app.js", "utf8"));
  w.eval(fs.readFileSync("app/static/v2-app.js", "utf8"));
  const $ = (s) => w.document.querySelector(s);
  await wait(() => $("#v2-machine"), "initial case and view loaded");
  report.checks.push("Authenticated initial app boot and case/visit state");
  const U = w.IntegrityUI;
  const api = (path, options) => U.api(path, options);
  const cases = await api("/api/v1/cases");
  let snapshot = await api("/api/v1/cases/" + cases.at(-1).id + "/export");
  const active = snapshot.asset_bindings.filter(
    (b) => b.active && b.inspection_id === U.state.iid,
  )[0];
  assert.ok(active, "Trial needs one confirmed machine");
  U.state.aid = active.local_asset_id;
  await U.refresh();
  for (const view of [
    "overview",
    "evidence",
    "site",
    "assessment",
    "investments",
    "followups",
    "wearable",
  ]) {
    U.state.view = view;
    U.render();
    assert.ok($("#workspace h1"), view);
    assert.doesNotMatch(
      $("#workspace").textContent,
      /undefined|\[object Object\]/,
    );
    report.checks.push("Render connected " + view);
  }
  async function page(v) {
    U.state.view = v;
    U.render();
    await new Promise((r) => setTimeout(r, 10));
  }
  async function submit(form) {
    form.dispatchEvent(
      new w.Event("submit", { bubbles: true, cancelable: true }),
    );
    await wait(
      () => !w.document.body.classList.contains("v2-saving"),
      "save operation completed",
    );
    const msg = $("#message");
    if (msg?.classList.contains("error")) throw Error(msg.textContent);
  }
  function fill(f, values) {
    for (const [key, v] of Object.entries(values)) {
      const el = f.elements.namedItem(key);
      assert.ok(el, "Field " + key);
      el.value = v;
    }
  }
  await page("investments");
  let f = $("[data-v2-form=project]");
  fill(f, {
    title: "DOM trial repair " + Date.now(),
    kind: "repair",
    rationale: "Synthetic manager reports repair needs",
    source_quote: "Synthetic repair proposal",
    attribution: "Synthetic manager",
    proposed_amount: "1200",
    currency: "JPY",
  });
  await submit(f);
  report.checks.push("Project create through actual rendered form/API");
  f = $("[data-v2-form=target]");
  if (!f) {
    const details = [...w.document.querySelectorAll("details")].find((d) =>
      d.textContent.includes("Add a target"),
    );
    if (details) details.open = true;
    f = $("[data-v2-form=target]");
  }
  assert.ok(f);
  fill(f, {
    target_value: "60",
    unit: "hours",
    quote: "Synthetic expected reduction of 60 percent",
    attribution: "Synthetic manager",
  });
  await submit(f);
  report.checks.push(
    "Forecast target saved without fabricating baseline/outcome",
  );
  await page("followups");
  f = $("[data-v2-form=task]");
  fill(f, {
    request: "Synthetic commissioning evidence " + Date.now(),
    contact: "Synthetic plant manager",
    due_date: "2026-10-01",
    required_evidence: "Accepted machine-specific commissioning certificate",
  });
  f.elements.claim_id.value = U.state.report.claims.find(
    (c) => c.asset_id === active.local_asset_id && c.kind === "commissioning",
  ).id;
  await submit(f);
  report.checks.push("Task creation with owner/reviewer/date/requirement");
  const latest = (
    await api("/api/v1/cases/" + cases.at(-1).id + "/follow-ups")
  ).at(-1);
  assert.ok(latest);
  const transition = await fetch(
    base +
      "/api/v1/cases/" +
      cases.at(-1).id +
      "/follow-ups/" +
      latest.task.id +
      "/transition",
    {
      method: "POST",
      headers: {
        Cookie: cookie,
        Origin: base,
        "X-CSRF-Token": $('meta[name="csrf-token"]').content,
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        version: latest.details.version,
        status: "closed",
        verification_supported: true,
        reason: "Attempt premature closure",
      }),
    },
  );
  assert.equal(transition.status, 409);
  report.checks.push("Premature closure rejected at core workflow boundary");
  await page("site");
  $("#v2-consent").checked = true;
  f = $("[data-v2-form=segment]");
  fill(f, {
    text: "交換すると停止時間は約60%減る見込みです。",
    language: "ja",
    reason: "Save synthetic interview source",
  });
  f.elements.correct_existing.checked = false;
  await submit(f);
  report.checks.push("Japanese source segment persisted through actual UI/API");
  f = $("[data-v2-form=segment]");
  fill(f, {
    text: "交換すると停止時間は約50%減る見込みです。",
    reason: "Correct synthetic numeric transcription",
  });
  f.elements.correct_existing.checked = true;
  await submit(f);
  report.checks.push("Saved transcript correction with source versioning");
  const events = await api("/api/v1/cases/" + cases.at(-1).id + "/activity");
  assert.ok(
    events.some(
      (e) =>
        e.action === "v2.transcript.analyst_corrected" &&
        e.before.text.includes("60%") &&
        e.after.text.includes("50%"),
    ),
  );
  report.checks.push(
    "Original/corrected transcript values both present in audit",
  );
  assert.equal(report.issues.length, 0);
  dom.window.close();
  report.status = "passed";
  fs.writeFileSync(
    process.env.CDI_UI_REPORT || "/private/tmp/cdi-v2-fullstack-dom.json",
    JSON.stringify(report, null, 2),
  );
  console.log(
    JSON.stringify({
      status: report.status,
      checks: report.checks.length,
      issues: report.issues,
    }),
  );
})().catch((e) => {
  report.status = "failed";
  report.issues.push(e.message);
  fs.writeFileSync(
    process.env.CDI_UI_REPORT || "/private/tmp/cdi-v2-fullstack-dom.json",
    JSON.stringify(report, null, 2),
  );
  console.error(e.message);
  process.exitCode = 1;
});
