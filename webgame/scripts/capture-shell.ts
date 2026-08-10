import { execFileSync, spawn, type ChildProcess } from "node:child_process";
import { mkdir, readFile, readlink, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import process from "node:process";

import { chromium, type Browser, type Page } from "playwright-core";

import menuGoldenJson from "../../tests/fixtures/webgame/menufix-preview-overlay/menu-goldens.json" with { type: "json" };
import { ManifestAssets } from "../client/manifest-assets.js";
import { parseMenuCatalog } from "../client/menu-catalog.js";

interface ProcessIdentity {
  readonly pid: number;
  readonly executable: string;
  readonly commandLine: string;
}

interface BrowserFailure {
  readonly kind: "console" | "pageerror";
  readonly text: string;
}

interface BootEvent {
  readonly name: string;
  readonly milliseconds: number;
  readonly detail: unknown;
}

const REPO_ROOT = path.resolve(import.meta.dirname, "..", "..");
const WEBGAME_ROOT = path.join(REPO_ROOT, "webgame");
const EVIDENCE_ROOT = process.env.WEBGAME_EVIDENCE_ROOT
  ?? "/mnt/d/codex-evidence/shellfix-20260809/captures/predeploy";
const MENUFIX_REFERENCE_ROOT = process.env.MENUFIX_REFERENCE_ROOT
  ?? "/mnt/d/codex-evidence/menufix-20260805/raw-v9/candidates/candidate-v214-profile-final";
const ASSET_ROOT = process.env.WEBGAME_ASSET_ROOT;
const CHROME = process.env.CHROME_PATH ?? "/usr/bin/google-chrome";
const SERVER_PORT = Number(process.env.WEBGAME_CAPTURE_PORT ?? "4174");
const SERVER_URL = `http://127.0.0.1:${SERVER_PORT}`;

function requireConfiguration(): string {
  if (ASSET_ROOT === undefined || ASSET_ROOT.length === 0) {
    throw new Error("capture requires WEBGAME_ASSET_ROOT pointing at the landed assetpack output");
  }
  if (!Number.isInteger(SERVER_PORT) || SERVER_PORT < 1024 || SERVER_PORT > 65_535) {
    throw new Error("WEBGAME_CAPTURE_PORT must be an unprivileged TCP port");
  }
  return ASSET_ROOT;
}

function delay(milliseconds: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

function windowsPath(filePath: string): string {
  const match = /^\/mnt\/([a-z])\/(.*)$/i.exec(path.resolve(filePath));
  if (match?.[1] === undefined || match[2] === undefined) {
    throw new Error(`Windows-side hashing requires a mounted drive path: ${filePath}`);
  }
  return `${match[1].toUpperCase()}:\\${match[2].replaceAll("/", "\\")}`;
}

function sha256File(filePath: string): string {
  const encodedCommand = Buffer.from(
    `$ProgressPreference='SilentlyContinue';$p=[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('${Buffer.from(windowsPath(filePath), "utf8").toString("base64")}'));(Get-FileHash -Algorithm SHA256 -LiteralPath $p).Hash.ToLowerInvariant()`,
    "utf16le",
  ).toString("base64");
  return execFileSync("powershell.exe", [
    "-NoProfile",
    "-NonInteractive",
    "-EncodedCommand",
    encodedCommand,
  ], { encoding: "utf8" }).trim();
}

async function endpointResponds(url: string): Promise<boolean> {
  try {
    await fetch(url, { signal: AbortSignal.timeout(750) });
    return true;
  } catch (error: unknown) {
    const code = (error as { cause?: { code?: unknown } }).cause?.code;
    if (code === "ECONNREFUSED" || code === "ECONNRESET" || error instanceof TypeError) {
      return false;
    }
    throw error;
  }
}

async function waitForRunnableServer(child: ChildProcess, log: () => string): Promise<void> {
  const deadline = Date.now() + 30_000;
  while (Date.now() < deadline) {
    if (child.exitCode !== null) {
      throw new Error(
        `browser shell server is broken, not busy: exited ${child.exitCode}\n${log()}`,
      );
    }
    if (await endpointResponds(`${SERVER_URL}/`)) {
      return;
    }
    await delay(100);
  }
  throw new Error(`browser shell server stayed busy for 30 seconds without becoming runnable\n${log()}`);
}

async function terminateOwnedChild(child: ChildProcess): Promise<"natural" | "sigterm" | "sigkill"> {
  const hasExited = (): boolean => child.exitCode !== null;
  if (hasExited()) {
    return "natural";
  }
  child.kill("SIGTERM");
  for (let attempt = 0; attempt < 50; attempt += 1) {
    if (hasExited()) {
      return "sigterm";
    }
    await delay(100);
  }
  child.kill("SIGKILL");
  for (let attempt = 0; attempt < 50; attempt += 1) {
    if (hasExited()) {
      return "sigkill";
    }
    await delay(100);
  }
  throw new Error(`owned server PID ${child.pid ?? "unknown"} did not exit after SIGKILL`);
}

async function childPids(pid: number): Promise<number[]> {
  try {
    const value = await readFile(`/proc/${pid}/task/${pid}/children`, "utf8");
    return value.trim().length === 0
      ? []
      : value.trim().split(/\s+/).map((entry) => Number(entry));
  } catch (error: unknown) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") {
      return [];
    }
    throw error;
  }
}

async function processIdentity(pid: number): Promise<ProcessIdentity | null> {
  try {
    const [executable, commandBytes] = await Promise.all([
      readlink(`/proc/${pid}/exe`),
      readFile(`/proc/${pid}/cmdline`),
    ]);
    return {
      pid,
      executable,
      commandLine: commandBytes.toString("utf8").replaceAll("\0", " ").trim(),
    };
  } catch (error: unknown) {
    if ((error as NodeJS.ErrnoException).code === "ENOENT") {
      return null;
    }
    throw error;
  }
}

async function descendants(rootPid: number): Promise<ProcessIdentity[]> {
  const result: ProcessIdentity[] = [];
  const queue = await childPids(rootPid);
  const seen = new Set<number>();
  while (queue.length > 0) {
    const pid = queue.shift();
    if (pid === undefined || seen.has(pid)) {
      continue;
    }
    seen.add(pid);
    const identity = await processIdentity(pid);
    if (identity !== null) {
      result.push(identity);
      queue.push(...await childPids(pid));
    }
  }
  return result.sort((left, right) => left.pid - right.pid);
}

async function sameProcessStillRuns(identity: ProcessIdentity): Promise<boolean> {
  const current = await processIdentity(identity.pid);
  return current?.executable === identity.executable
    && current.commandLine === identity.commandLine;
}

function installFailureCapture(page: Page, failures: BrowserFailure[]): void {
  page.on("console", (message) => {
    if (message.type() === "error") {
      failures.push({ kind: "console", text: message.text() });
    }
  });
  page.on("pageerror", (error) => {
    failures.push({ kind: "pageerror", text: error.stack ?? error.message });
  });
}

async function waitForShell(page: Page): Promise<void> {
  await page.waitForFunction(() => window.__webshell?.ready === true, undefined, {
    timeout: 60_000,
  });
}

async function settleFrame(page: Page): Promise<void> {
  await page.evaluate(async () => {
    await new Promise<void>((resolve) => {
      requestAnimationFrame(() => requestAnimationFrame(() => {
        resolve();
      }));
    });
  });
}

function pngDataUrl(bytes: Buffer): string {
  return `data:image/png;base64,${bytes.toString("base64")}`;
}

async function makeSideBySide(
  page: Page,
  layoutId: string,
  nativePath: string,
  renderedPath: string,
  outputPath: string,
): Promise<void> {
  const [native, rendered] = await Promise.all([readFile(nativePath), readFile(renderedPath)]);
  await page.setViewportSize({ width: 3200, height: 936 });
  await page.setContent(`<!doctype html>
    <style>
      * { box-sizing: border-box; }
      html, body { width: 3200px; height: 936px; margin: 0; overflow: hidden; background: #111; }
      main { display: grid; grid-template-columns: 1600px 1600px; grid-template-rows: 36px 900px; }
      h1 { margin: 0; color: #eee; background: #222; font: 20px/36px sans-serif; text-align: center; }
      img { display: block; width: 1600px; height: 900px; }
    </style>
    <main>
      <h1>NATIVE REFERENCE — ${layoutId}</h1><h1>WEBGL SHELL — ${layoutId}</h1>
      <img alt="native" src="${pngDataUrl(native)}"><img alt="webgl" src="${pngDataUrl(rendered)}">
    </main>`);
  await page.waitForFunction(() => [...document.images].every((image) => image.complete));
  await page.screenshot({ path: outputPath, animations: "disabled" });
}

async function main(): Promise<void> {
  const assetRoot = requireConfiguration();
  const catalog = parseMenuCatalog(menuGoldenJson);
  const criticalLayoutIds = new Set([
    "native-loader",
    "loading-screen",
    "control-scheme-picker",
    "create-element",
    "create-discipline",
    "hub_new_game",
    "hub_resumed",
    "pause-menu",
    "beta-notice",
    "main-menu-root",
    "profile-save-select",
  ]);
  const rawManifest = JSON.parse(await readFile(path.join(assetRoot, "asset-manifest.json"), "utf8")) as unknown;
  const manifestAssets = new ManifestAssets(rawManifest);
  const allowedImagePaths = new Set(
    manifestAssets.manifest.atlases.map((atlas) => `/assetpack/${atlas.file}`),
  );
  if (allowedImagePaths.size === 0 || !allowedImagePaths.has("/assetpack/atlases/Loader.png")) {
    throw new Error("capture asset audit did not reach the landed Loader atlas witness");
  }

  const renderedRoot = path.join(EVIDENCE_ROOT, "rendered-1600x900");
  const deckRoot = path.join(EVIDENCE_ROOT, "rendered-1280x800");
  const comparisonRoot = path.join(EVIDENCE_ROOT, "side-by-side");
  await Promise.all([
    mkdir(renderedRoot, { recursive: true }),
    mkdir(deckRoot, { recursive: true }),
    mkdir(comparisonRoot, { recursive: true }),
  ]);

  if (await endpointResponds(`${SERVER_URL}/`)) {
    throw new Error(`capture port ${SERVER_PORT} is busy; refusing to attach to an unowned server`);
  }
  const baselineChildren = await descendants(process.pid);
  const baselinePids = new Set(baselineChildren.map((identity) => identity.pid));
  let serverLog = "";
  const viteEntry = path.join(WEBGAME_ROOT, "node_modules", "vite", "bin", "vite.js");
  const server = spawn(process.execPath, [
    viteEntry,
    "--host", "127.0.0.1",
    "--port", String(SERVER_PORT),
    "--strictPort",
  ], {
    cwd: WEBGAME_ROOT,
    env: { ...process.env, WEBGAME_ASSET_ROOT: assetRoot },
    stdio: ["ignore", "pipe", "pipe"],
  });
  for (const stream of [server.stdout, server.stderr]) {
    stream.on("data", (chunk: Buffer | string) => {
      serverLog = `${serverLog}${String(chunk)}`.slice(-20_000);
    });
  }

  let browser: Browser | null = null;
  let ownedDuringRun: ProcessIdentity[] = [];
  let serverTermination: "natural" | "sigterm" | "sigkill";
  const failures: BrowserFailure[] = [];
  let report: Record<string, unknown>;
  try {
    await waitForRunnableServer(server, () => serverLog);
    browser = await chromium.launch({
      executablePath: CHROME,
      headless: true,
      args: [
        "--disable-dev-shm-usage",
        "--enable-webgl",
        "--ignore-gpu-blocklist",
        "--use-angle=swiftshader",
      ],
    });

    const bootContext = await browser.newContext({ viewport: { width: 1600, height: 900 } });
    await bootContext.addInitScript(() => {
      const host = window as Window & { __webshellBootEvidence?: BootEvent[] };
      const events: BootEvent[] = [];
      host.__webshellBootEvidence = events;
      for (const name of ["webshell:loader-progress", "webshell:title-enter"]) {
        window.addEventListener(name, (event) => {
          events.push({
            name,
            milliseconds: performance.now(),
            detail: (event as CustomEvent<unknown>).detail,
          });
        });
      }
      localStorage.clear();
    });
    const bootPage = await bootContext.newPage();
    installFailureCapture(bootPage, failures);
    const bootStarted = Date.now();
    await bootPage.goto(`${SERVER_URL}/`, { waitUntil: "domcontentloaded" });
    await bootPage.waitForSelector("#game-canvas");
    await bootPage.waitForFunction(() => (
      (window as Window & { __webshellBootEvidence?: BootEvent[] })
        .__webshellBootEvidence?.some((event) => event.name === "webshell:loader-progress") === true
    ));
    const loaderCapturedBeforeReady = await bootPage.evaluate(() => window.__webshell === undefined);
    await bootPage.screenshot({
      path: path.join(EVIDENCE_ROOT, "boot-live-work-bound.png"),
      animations: "disabled",
    });
    await waitForShell(bootPage);
    const bootReadyMilliseconds = Date.now() - bootStarted;
    const bootEvidence = await bootPage.evaluate(() => ({
      events: (window as Window & { __webshellBootEvidence?: BootEvent[] })
        .__webshellBootEvidence ?? [],
      snapshot: window.__webshell?.snapshot(),
      animationDurations: document.getAnimations().map((animation) => (
        Number(animation.effect?.getTiming().duration)
      )),
    }));
    const progress = bootEvidence.events.filter((event) => event.name === "webshell:loader-progress");
    const firstProgress = progress[0]?.detail as { completed?: unknown; total?: unknown } | undefined;
    const lastProgress = progress.at(-1)?.detail as { completed?: unknown; total?: unknown } | undefined;
    if (
      progress.length !== catalog.screenCensus.length + 1
      || firstProgress?.completed !== 0
      || firstProgress.total !== catalog.screenCensus.length
      || lastProgress?.completed !== catalog.screenCensus.length
      || lastProgress.total !== catalog.screenCensus.length
    ) {
      throw new Error("work-bound boot evidence did not record every aggregate layout preparation unit");
    }
    const titleEvent = bootEvidence.events.find((event) => event.name === "webshell:title-enter");
    if (JSON.stringify(titleEvent?.detail) !== JSON.stringify({
      fadeMilliseconds: 1100,
      inputGateMilliseconds: 2000,
    })) {
      throw new Error("first-boot entry evidence lost the 1.1-second fade or 2.0-second input gate");
    }
    if (!bootEvidence.animationDurations.includes(1100) || bootEvidence.snapshot?.inputGated !== true) {
      throw new Error("live boot did not retain the title fade and gated-input state");
    }
    await bootContext.close();

    const context = await browser.newContext({ viewport: { width: 1600, height: 900 } });
    const page = await context.newPage();
    installFailureCapture(page, failures);
    await page.goto(`${SERVER_URL}/?screen=native-loader&focus=0`, { waitUntil: "domcontentloaded" });
    await waitForShell(page);

    const inputCensus: Record<string, readonly { type: string; actionId: string }[]> = {};
    for (const layoutId of catalog.screenCensus) {
      await page.evaluate(async (id) => window.__webshell?.showLayout(id), layoutId);
      await settleFrame(page);
      const state = await page.evaluate(() => ({
        surface: window.__webshell?.snapshot().surface,
        inputs: [...document.querySelectorAll("input")].map((input) => ({
          type: input.type,
          actionId: input.dataset.actionId ?? "",
        })),
        renderedText: window.__webshell?.renderPlan().commands.flatMap((command) => (
          command.kind === "atlas-text" || command.kind === "system-text"
            ? [command.text]
            : []
        )) ?? [],
      }));
      const settledOnLayout = state.surface?.kind === "layout" && state.surface.layoutId === layoutId;
      const settledOnHubEndpoint = (
        state.surface?.kind === "hub-stub"
        && state.surface.endpointLayoutId === layoutId
      );
      if (!settledOnLayout && !settledOnHubEndpoint) {
        throw new Error(`live renderer did not settle on requested G11 screen ${layoutId}`);
      }
      if (layoutId === "profile-save-select" && !state.renderedText.includes("HALL OF FAME")) {
        throw new Error("profile-save-select rendered its HALL OF FAME control without a label");
      }
      if (
        layoutId === "pause-menu"
        && !["RESUME GAME", "GAME SETTINGS", "LEAVE GAME"]
          .every((label) => state.renderedText.includes(label))
      ) {
        throw new Error("pause-menu did not render all three measured control labels");
      }
      inputCensus[layoutId] = state.inputs;
      await page.screenshot({
        path: path.join(renderedRoot, `${layoutId}.png`),
        animations: "disabled",
      });
    }
    await page.evaluate(async () => window.__webshell?.showDialogComposite("beta_notice_first_boot"));
    await settleFrame(page);
    const compositeState = await page.evaluate(() => window.__webshell?.snapshot());
    if (
      compositeState?.surface.kind !== "dialog-composite"
      || compositeState.surface.compositeId !== "beta_notice_first_boot"
    ) {
      throw new Error("live renderer did not settle on beta_notice_first_boot");
    }
    await page.screenshot({
      path: path.join(renderedRoot, "beta_notice_first_boot.png"),
      animations: "disabled",
    });

    const domAudit = await page.evaluate(() => ({
      imageElements: document.images.length,
      canvasElements: document.querySelectorAll("canvas").length,
      resources: performance.getEntriesByType("resource").map((entry) => ({
        name: entry.name,
        initiatorType: (entry as PerformanceResourceTiming).initiatorType,
      })),
    }));
    if (domAudit.imageElements !== 0 || domAudit.canvasElements !== 1) {
      throw new Error("shell DOM must contain one WebGL canvas and zero image elements");
    }
    const imageResources = domAudit.resources.filter((entry) => entry.initiatorType === "img");
    if (imageResources.length === 0) {
      throw new Error("manifest-only live asset audit reached no atlas image requests");
    }
    for (const resource of imageResources) {
      const pathname = new URL(resource.name).pathname;
      if (!allowedImagePaths.has(pathname)) {
        throw new Error(`shell loaded image outside the assetpack manifest: ${pathname}`);
      }
    }
    if (
      inputCensus["dark-cloud-login-settings"]?.length !== 2
      || inputCensus["dark-cloud-search"]?.length !== 1
    ) {
      throw new Error("real DOM text-entry census disagrees with the corrected keyboard surfaces");
    }

    await page.setViewportSize({ width: 1280, height: 800 });
    for (const layoutId of catalog.screenCensus) {
      await page.evaluate(async (id) => window.__webshell?.showLayout(id), layoutId);
      await settleFrame(page);
      const canvasRect = await page.locator("#game-canvas").evaluate((canvas) => {
        const rect = canvas.getBoundingClientRect();
        return [rect.x, rect.y, rect.width, rect.height];
      });
      if (JSON.stringify(canvasRect) !== JSON.stringify([0, 40, 1280, 720])) {
        throw new Error(`${layoutId} lost the G11 16:10 safe area at 1280x800: ${JSON.stringify(canvasRect)}`);
      }
      await page.screenshot({
        path: path.join(deckRoot, `${layoutId}.png`),
        animations: "disabled",
      });
    }

    await page.evaluate(async () => window.__webshell?.showLayout("game-settings-title"));
    const performanceReport = await page.evaluate(async () => (
      window.__webshell?.measureFrameTimes(600)
    ));
    if (performanceReport === undefined) {
      throw new Error("frame-time probe could not reach the live shell harness");
    }
    const framesPerSecond = 1000 / performanceReport.meanMs;
    if (framesPerSecond < 58 || performanceReport.p95Ms > 20.5) {
      throw new Error(
        `1280x800 headless frame loop missed its 60fps budget: ${framesPerSecond.toFixed(2)}fps, p95 ${performanceReport.p95Ms.toFixed(3)}ms`,
      );
    }
    const webgl = await page.locator("#game-canvas").evaluate((canvas) => {
      if (!(canvas instanceof HTMLCanvasElement)) {
        throw new Error("game canvas changed element type");
      }
      const gl = canvas.getContext("webgl2");
      if (gl === null) {
        throw new Error("live renderer lost WebGL2");
      }
      return {
        version: String(gl.getParameter(gl.VERSION)),
        renderer: String(gl.getParameter(gl.RENDERER)),
        vendor: String(gl.getParameter(gl.VENDOR)),
      };
    });

    const comparisonPage = await context.newPage();
    for (const layoutId of criticalLayoutIds) {
      const layout = catalog.layouts.get(layoutId);
      if (layout === undefined) {
        throw new Error(`side-by-side capture lost critical layout ${layoutId}`);
      }
      await makeSideBySide(
        comparisonPage,
        layoutId,
        path.join(MENUFIX_REFERENCE_ROOT, layout.referenceCapture),
        path.join(renderedRoot, `${layoutId}.png`),
        path.join(comparisonRoot, `${layoutId}.png`),
      );
    }
    const firstBootComposite = catalog.dialogComposites.get("beta_notice_first_boot");
    if (firstBootComposite === undefined) {
      throw new Error("side-by-side capture lost beta_notice_first_boot composite");
    }
    await makeSideBySide(
      comparisonPage,
      firstBootComposite.id,
      path.join(MENUFIX_REFERENCE_ROOT, firstBootComposite.referenceCapture),
      path.join(renderedRoot, `${firstBootComposite.id}.png`),
      path.join(comparisonRoot, `${firstBootComposite.id}.png`),
    );
    const visualArtifacts = catalog.screenCensus.map((layoutId) => {
      const layout = catalog.layouts.get(layoutId);
      if (layout === undefined) {
        throw new Error(`visual artifact audit lost aggregate layout ${layoutId}`);
      }
      const referencePath = path.join(MENUFIX_REFERENCE_ROOT, layout.referenceCapture);
      const renderedPath = path.join(renderedRoot, `${layoutId}.png`);
      const [referenceSha256, renderedSha256] = [
        sha256File(referencePath),
        sha256File(renderedPath),
      ];
      if (referenceSha256 !== layout.referenceSha256) {
        throw new Error(`visual comparison reference hash changed for ${layout.fixture}`);
      }
      const isCritical = criticalLayoutIds.has(layoutId);
      const sideBySideSha256 = isCritical
        ? sha256File(path.join(comparisonRoot, `${layoutId}.png`))
        : null;
      return {
        layoutId,
        fixture: layout.fixture,
        referenceCapture: layout.referenceCapture,
        referenceSha256,
        renderedSha256,
        sideBySideSha256,
        disposition: isCritical ? "critical_exact_review_required" : "inert_rendered",
      };
    });
    const compositeReferencePath = path.join(
      MENUFIX_REFERENCE_ROOT,
      firstBootComposite.referenceCapture,
    );
    const compositeRenderedPath = path.join(renderedRoot, `${firstBootComposite.id}.png`);
    const compositeSideBySidePath = path.join(comparisonRoot, `${firstBootComposite.id}.png`);
    const [compositeReferenceSha256, compositeRenderedSha256, compositeSideBySideSha256] = [
      sha256File(compositeReferencePath),
      sha256File(compositeRenderedPath),
      sha256File(compositeSideBySidePath),
    ];
    if (compositeReferenceSha256 !== firstBootComposite.referenceSha256) {
      throw new Error("visual comparison reference hash changed for beta_notice_first_boot");
    }
    const compositeArtifacts = [{
      compositeId: firstBootComposite.id,
      fixture: firstBootComposite.fixture,
      referenceCapture: firstBootComposite.referenceCapture,
      referenceSha256: compositeReferenceSha256,
      renderedSha256: compositeRenderedSha256,
      sideBySideSha256: compositeSideBySideSha256,
      disposition: "critical_exact_review_required",
    }];
    await context.close();

    ownedDuringRun = (await descendants(process.pid))
      .filter((identity) => !baselinePids.has(identity.pid));
    if (ownedDuringRun.length === 0 || server.pid === undefined) {
      throw new Error("owned-process evidence did not reach the Vite/Chromium process tree");
    }
    report = {
      schema: "solomon-dark-shellfix-capture-v1",
      screenCount: catalog.screenCensus.length,
      compositeCount: compositeArtifacts.length,
      sideBySideCount: criticalLayoutIds.size + compositeArtifacts.length,
      deckRenderCount: catalog.screenCensus.length,
      visualEvidence: {
        criticalWaivers: 0,
        criticalLayoutIds: [...criticalLayoutIds],
        criticalCompositeIds: compositeArtifacts.map((artifact) => artifact.compositeId),
        artifacts: visualArtifacts,
        composites: compositeArtifacts,
      },
      boot: {
        readyMilliseconds: bootReadyMilliseconds,
        loaderCapturedBeforeReady,
        events: bootEvidence.events,
        animationDurations: bootEvidence.animationDurations,
        snapshot: bootEvidence.snapshot,
      },
      assetAudit: {
        manifestAtlasCount: allowedImagePaths.size,
        observedAtlasRequestCount: imageResources.length,
        domImageElementCount: domAudit.imageElements,
        observedPaths: imageResources.map((resource) => new URL(resource.name).pathname).sort(),
      },
      textInputs: inputCensus,
      safeArea1280x800: [0, 40, 1280, 720],
      performance: { ...performanceReport, framesPerSecond },
      webgl,
      machine: {
        platform: os.platform(),
        release: os.release(),
        cpu: os.cpus()[0]?.model ?? "unknown",
        logicalCpuCount: os.cpus().length,
        totalMemoryBytes: os.totalmem(),
        chrome: execFileSync(CHROME, ["--version"], { encoding: "utf8" }).trim(),
        node: process.version,
        headless: true,
        blindSpots: [
          "This is software/headless Chromium timing on the campaign machine, not Steam Deck hardware.",
          "No Deck compositor, thermal, battery, touchscreen, or physical-controller latency is represented.",
          "The true Deck-hardware gate remains open until the owner provides the device.",
        ],
      },
      browserFailures: failures,
      server: { pid: server.pid, url: SERVER_URL, log: serverLog },
    };
    if (failures.length > 0) {
      throw new Error(`browser emitted ${failures.length} console/page failures`);
    }
  } finally {
    if (browser !== null) {
      await browser.close();
    }
    if (ownedDuringRun.length === 0) {
      ownedDuringRun = (await descendants(process.pid))
        .filter((identity) => !baselinePids.has(identity.pid));
    }
    serverTermination = await terminateOwnedChild(server);
  }

  await delay(500);
  const survivors: ProcessIdentity[] = [];
  for (const identity of ownedDuringRun) {
    if (await sameProcessStillRuns(identity)) {
      survivors.push(identity);
    }
  }
  if (survivors.length > 0) {
    throw new Error(
      `owned capture processes survived cleanup: ${survivors.map((identity) => identity.pid).join(",")}`,
    );
  }
  report.processCleanup = {
    capturePid: process.pid,
    baselineChildren,
    ownedDuringRun,
    serverTermination,
    verifiedGone: ownedDuringRun.map((identity) => identity.pid),
  };
  await writeFile(
    path.join(EVIDENCE_ROOT, "capture-report.json"),
    `${JSON.stringify(report, null, 2)}\n`,
    "utf8",
  );
  console.log(
    `captured ${catalog.screenCensus.length + 1} native-size, ${catalog.screenCensus.length} Deck-size, and ${criticalLayoutIds.size + 1} side-by-side frames`,
  );
  const measured = report.performance as { framesPerSecond: number; p95Ms: number };
  console.log(`1280x800: ${measured.framesPerSecond.toFixed(2)}fps mean, ${measured.p95Ms.toFixed(3)}ms p95`);
  console.log(`owned cleanup verified for ${ownedDuringRun.length} PIDs`);
}

await main();
