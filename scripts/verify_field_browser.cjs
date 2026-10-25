/* Real browser + isolated real backend/dependencies. Media is explicitly synthetic.
 * Optional dev tool: Playwright 1.62.1. Set NODE_PATH if installed outside the repo.
 * CDI_BROWSER_TEST_PYTHON selects the venv; CDI_BROWSER_EXECUTABLE selects Edge.
 */
"use strict";
const assert = require("node:assert/strict");
const { spawn, spawnSync } = require("node:child_process");
const { randomBytes } = require("node:crypto");
const fs = require("node:fs/promises");
const net = require("node:net");
const os = require("node:os");
const path = require("node:path");
const { chromium, expect } = require("playwright/test");

(async () => {
  const directory = await fs.mkdtemp(
    path.join(os.tmpdir(), "cdi-field-browser-"),
  );
  const python = process.env.CDI_BROWSER_TEST_PYTHON || "python";
  const cwd = path.resolve(__dirname, "..");
  const png = path.join(directory, "synthetic-label.png");
  const video = path.join(directory, "synthetic-label.y4m");
  const fixture = spawnSync(
    python,
    [
      "-c",
      'from pathlib import Path; import sys; from tests.test_field_workflow import label; Path(sys.argv[1]).write_bytes(label(code="SYN-001"))',
      png,
    ],
    { cwd, encoding: "utf8" },
  );
  assert.equal(fixture.status, 0, fixture.stderr);
  const encoded = spawnSync(
    "ffmpeg",
    [
      "-v",
      "error",
      "-loop",
      "1",
      "-i",
      png,
      "-t",
      "2",
      "-r",
      "5",
      "-pix_fmt",
      "yuv420p",
      video,
    ],
    { encoding: "utf8" },
  );
  assert.equal(encoded.status, 0, encoded.stderr);
  const listener = net.createServer();
  await new Promise((resolve) => listener.listen(0, "127.0.0.1", resolve));
  const port = listener.address().port;
  await new Promise((resolve) => listener.close(resolve));
  const token = randomBytes(32).toString("hex"),
    base = `http://127.0.0.1:${port}`;
  const server = spawn(
    python,
    [
      "-m",
      "uvicorn",
      "app.main:create_app",
      "--factory",
      "--host",
      "127.0.0.1",
      "--port",
      String(port),
      "--no-access-log",
    ],
    {
      cwd,
      env: {
        ...process.env,
        DATABASE_URL: "",
        CDI_REQUIRE_POSTGRES: "false",
        GEMINI_API_KEY: "",
        GOOGLE_API_KEY: "",
        CDI_TOKENS: JSON.stringify({
          [token]: {
            actor: "Synthetic field browser analyst",
            role: "analyst",
          },
        }),
        CDI_DATA_DIR: path.join(directory, "data"),
      },
      stdio: ["ignore", "pipe", "pipe"],
    },
  );
  let logs = "",
    browser,
    launchError;
  server.stdout.on("data", (chunk) => (logs += chunk));
  server.stderr.on("data", (chunk) => (logs += chunk));
  server.on("error", (error) => (launchError = error));
  try {
    let ready = false;
    for (let i = 0; i < 100; i++) {
      if (launchError) throw launchError;
      if (server.exitCode !== null) throw Error(logs);
      try {
        ready = (await fetch(base + "/health")).ok;
      } catch {}
      if (ready) break;
      await new Promise((resolve) => setTimeout(resolve, 100));
    }
    assert.ok(ready, "Real isolated backend starts");
    browser = await chromium.launch({
      headless: true,
      ...(process.env.CDI_BROWSER_EXECUTABLE
        ? { executablePath: process.env.CDI_BROWSER_EXECUTABLE }
        : {}),
      args: [
        "--use-fake-ui-for-media-stream",
        "--use-fake-device-for-media-stream",
        `--use-file-for-fake-video-capture=${video}`,
      ],
    });
    const page = await browser.newPage({
      viewport: { width: 1100, height: 1000 },
    });
    const errors = [];
    page.on("pageerror", (error) => errors.push(error.message));
    await page.goto(base + "/field-test");
    await page.locator("#token").fill(token);
    await page.locator("button[type=submit]").click();
    await expect(page).toHaveURL(base + "/field-test");
    await expect(page.locator("#notice")).toContainText("Backend connected");
    await page.locator("#prepare").click();
    await expect(page.locator("#notice")).toHaveText(
      "Fresh synthetic case ready.",
    );
    const caseId = await page.locator("#case").inputValue(),
      root = base + "/api/v1/cases/" + caseId;
    const headers = { Authorization: "Bearer " + token };
    const get = async (suffix) => {
      const r = await page.request.get(root + suffix, { headers });
      assert.ok(r.ok(), await r.text());
      return r.json();
    };
    const snapshot = await get("/export");
    const asset = snapshot.v1_inspections[0].assets.find(
      (a) => a.tag === "CNC-001",
    );
    await page.locator("#asset").selectOption(asset.id);
    await page.locator("#context button[type=submit]").click();
    await expect(page.locator("#notice")).toContainText("Session saved");
    await page.locator("#camera-start").click();
    await expect(page.locator("#transport")).toContainText(
      "Backend connected",
      { timeout: 20000 },
    );
    let sessionId = (await get("/field-sessions"))[0].id;
    await expect
      .poll(
        async () =>
          (await get("/field-sessions/" + sessionId)).transport
            .received_samples,
        { timeout: 15000 },
      )
      .toBeGreaterThanOrEqual(3);
    await page.locator("#capture").click();
    await expect(page.locator("#notice")).toContainText(
      "Capture source and processing result saved",
      { timeout: 45000 },
    );
    let capture = (await get("/visual-captures"))[0];
    assert.ok(capture.evidence_id && capture.raw_result.ocr_text);
    assert.ok(
      await page.locator("#camera").isVisible(),
      "Deliberate still does not rebuild/stop camera session",
    );
    await page
      .locator("#review-capture input[name=reason]")
      .fill("Reviewed the synthetic plate and every decoded source");
    await page.locator("#review-capture button[value=accept]").click();
    await expect(page.locator("#notice")).toContainText("Review the original");
    for (const [field, value] of Object.entries({
      serial: "SYN-001",
      model: "DemoMill X3",
      site: "Plant A",
    }))
      await page.locator(`#review-capture input[name=${field}]`).fill(value);
    await page.locator("#review-capture input[name=checked_original]").check();
    if (capture.comparison.decision === "CONFLICTING_SOURCES")
      await page
        .locator("#review-capture input[name=acknowledge_conflicts]")
        .check();
    await page.locator("#review-capture button[value=accept]").click();
    await expect(page.locator("#notice")).toContainText(
      "Capture decision saved",
    );
    capture = (await get("/visual-captures"))[0];
    assert.equal(capture.state, "ACCEPTED");
    assert.ok(capture.physical_asset_id);
    assert.deepEqual(errors, []);
    const artifactDir = path.resolve(
      process.env.CDI_BROWSER_ARTIFACTS ||
        path.join(cwd, ".run", "browser-proof"),
    );
    await fs.mkdir(artifactDir, { recursive: true });
    await page.locator("#visual").screenshot({
      path: path.join(artifactDir, "field-camera-reviewed.png"),
    });
    await page.locator("#camera-stop").click();
    await page.locator("#close-session").click();
    await expect(page.locator("#notice")).toContainText("Session closed");

    // Company-level interview: a real MediaRecorder with fake audio and real FFmpeg validation.
    await page.locator("#purpose").selectOption("interview");
    await page.locator("#physical").selectOption("");
    await page.locator("#context button[type=submit]").click();
    await expect(page.locator("#notice")).toContainText("Session saved");
    await page
      .locator("#speaker")
      .fill("Synthetic interview speaker, analyst attributed");
    await page.locator("#consent").check();
    await page.locator("#record-start").click();
    await expect(page.locator("#audio-status")).toContainText(
      "Recording interview_speech",
    );
    await page.waitForTimeout(1400); // Deliberate recording duration, not a UI synchronization sleep.
    await page.locator("#record-stop").click();
    await expect(page.locator("#audio-status")).toContainText(
      "Original saved",
      { timeout: 30000 },
    );
    const audio = (await get("/audio")).at(-1);
    assert.equal(audio.physical_asset_id, null);
    assert.equal(
      audio.speaker_label,
      "Synthetic interview speaker, analyst attributed",
    );
    await page.locator("#close-session").click();
    await expect(page.locator("#notice")).toContainText("Session closed");
    await page.locator("#transcribe").click();
    await expect(page.locator("#notice")).toContainText(
      "Gemini is not configured",
    );
    const failed = (await get("/audio")).at(-1);
    assert.equal(failed.processing_state, "PROCESSING_FAILED");
    assert.ok(
      (
        await page.request.get(root + "/audio/" + audio.id + "/original", {
          headers,
        })
      ).ok(),
    );
    await page
      .getByText("Manual continuation when speech processing is unavailable", {
        exact: true,
      })
      .click();
    await page
      .locator("#manual-transcript textarea[name=text]")
      .fill("修理費は八百万円でした。停止時間は減っていません。");
    await page
      .locator("#manual-transcript textarea[name=translation]")
      .fill(
        "Reported repair costs were eight million yen. Downtime did not decrease.",
      );
    await page
      .locator("#manual-transcript input[name=reason]")
      .fill("Explicit human-entered synthetic transcript; provider failed");
    await page.locator("#manual-transcript button[type=submit]").click();
    await expect(page.locator("#notice")).toContainText(
      "Human transcript saved",
    );
    await page
      .locator("#correct-transcript textarea[name=text]")
      .fill("訂正：修理費は概算です。停止時間は減っていません。");
    await page
      .locator("#correct-transcript input[name=reason]")
      .fill("Preserve reported uncertainty and negation");
    await page.locator("#correct-transcript button[type=submit]").click();
    await expect(page.locator("#notice")).toContainText("Correction saved");
    await page.locator("#rules-fallback").check();
    await page.locator("#analyse").click();
    await expect(page.locator("#notice")).toContainText("Analysis saved");
    await expect(page.locator("#analysis")).toContainText("context_rules");
    const report = await page.request.get(root + "/report.pdf", { headers });
    assert.ok(report.ok());
    await fs.writeFile(
      path.join(artifactDir, "field-report.pdf"),
      await report.body(),
    );
    await page.setViewportSize({ width: 390, height: 844 });
    await page.locator("#transcript").screenshot({
      path: path.join(artifactDir, "field-mobile-interview.png"),
    });
    assert.ok(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth + 1,
      ),
    );
    assert.deepEqual(errors, []);
    console.log(
      "Field browser passed: authenticated real backend, sustained synthetic camera transport, retained still, explicit binding, real MediaRecorder/FFmpeg, provider failure with retained source, manual Japanese transcript/correction, labeled fallback, PDF, mobile layout. Hardware and live Gemini NOT verified.",
    );
  } catch (error) {
    console.error(logs.slice(-6000));
    throw error;
  } finally {
    if (browser) await browser.close();
    if (server.pid && server.exitCode === null && server.signalCode === null) {
      const exited = new Promise((resolve) => server.once("exit", resolve));
      if (process.platform === "win32") {
        const interpreter = Number(
          logs.match(/Started server process \[(\d+)\]/)?.[1],
        );
        if (interpreter && interpreter !== server.pid) {
          try {
            process.kill(interpreter);
          } catch (e) {
            if (e.code !== "ESRCH") throw e;
          }
        }
      }
      server.kill();
      await Promise.race([
        exited,
        new Promise((_, reject) =>
          setTimeout(() => reject(Error("Isolated server did not stop")), 5000),
        ),
      ]);
    }
    const resolved = path.resolve(directory),
      allowedRoot = path.resolve(os.tmpdir()) + path.sep;
    assert.ok(
      resolved.startsWith(allowedRoot) &&
        path.basename(resolved).startsWith("cdi-field-browser-"),
    );
    await fs.rm(resolved, {
      recursive: true,
      force: true,
      maxRetries: 5,
      retryDelay: 200,
    });
  }
})().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
