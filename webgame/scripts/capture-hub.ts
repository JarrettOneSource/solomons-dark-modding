import { execFileSync, spawn, type ChildProcess } from "node:child_process";
import { createHash } from "node:crypto";
import { mkdir, readFile, readlink, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";
import process from "node:process";

import { chromium, type Browser, type Page } from "playwright-core";

import { HUB_NPCS, offersForService, type HubNpc } from "../client/hub-data.js";
import { ManifestAssets } from "../client/manifest-assets.js";
import { parseMenuCatalog } from "../client/menu-catalog.js";
import { G13_PHASE_ORDER } from "../client/session-flow.js";

interface ProcessIdentity {
  readonly pid: number;
  readonly executable: string;
  readonly commandLine: string;
}

interface BrowserFailure {
  readonly kind: "console" | "pageerror";
  readonly surface: string;
  readonly text: string;
}

interface SettleReceipt {
  readonly sampleCount: number;
  readonly consecutiveMatches: number;
  readonly spanMilliseconds: number;
  readonly payloadSha256: string;
  readonly layoutId: string;
  readonly commandCount: number;
  readonly animatedElements: readonly string[];
}

type SurfaceSpec =
  | Readonly<{ id: "hub"; kind: "hub" }>
  | Readonly<{ id: string; kind: "npc"; npc: HubNpc }>
  | Readonly<{ id: string; kind: "service"; npc: HubNpc }>
  | Readonly<{ id: "run-shell"; kind: "run-shell" }>;

const REPO_ROOT = path.resolve(import.meta.dirname, "..", "..");
const WEBGAME_ROOT = path.join(REPO_ROOT, "webgame");
const EVIDENCE_ROOT = process.env.WEBGAME_EVIDENCE_ROOT
  ?? "/mnt/d/codex-evidence/hubbuild-20260808";
const ASSET_ROOT = process.env.WEBGAME_ASSET_ROOT;
const CHROME = process.env.CHROME_PATH ?? "/usr/bin/google-chrome";
const SERVER_PORT = Number(process.env.WEBGAME_CAPTURE_PORT ?? "4186");
const SERVER_URL = `http://127.0.0.1:${SERVER_PORT}`;

function requireConfiguration(): string {
  if (ASSET_ROOT === undefined || ASSET_ROOT.length === 0) {
    throw new Error("hub capture requires WEBGAME_ASSET_ROOT pointing at the landed assetpack output");
  }
  if (!Number.isInteger(SERVER_PORT) || SERVER_PORT < 1024 || SERVER_PORT > 65_535) {
    throw new Error("WEBGAME_CAPTURE_PORT must be an unprivileged TCP port");
  }
  return ASSET_ROOT;
}

function delay(milliseconds: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, milliseconds));
}

async function sha256File(filePath: string): Promise<string> {
  return createHash("sha256").update(await readFile(filePath)).digest("hex");
}

function sha256Text(value: string): string {
  return createHash("sha256").update(value).digest("hex");
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
      throw new Error(`hub capture server is broken, not busy: exited ${child.exitCode}\n${log()}`);
    }
    if (await endpointResponds(`${SERVER_URL}/`)) {
      return;
    }
    await delay(100);
  }
  throw new Error(`hub capture server stayed busy for 30 seconds without becoming runnable\n${log()}`);
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
  throw new Error(`owned hub server PID ${child.pid ?? "unknown"} did not exit after SIGKILL`);
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
  return current?.executable === identity.executable && current.commandLine === identity.commandLine;
}

function installFailureCapture(page: Page, surface: () => string, failures: BrowserFailure[]): void {
  page.on("console", (message) => {
    if (message.type() === "error") {
      failures.push({ kind: "console", surface: surface(), text: message.text() });
    }
  });
  page.on("pageerror", (error) => {
    failures.push({ kind: "pageerror", surface: surface(), text: error.stack ?? error.message });
  });
}

async function waitForHub(page: Page, label: string): Promise<void> {
  const deadline = Date.now() + 120_000;
  let lastBody = "";
  while (Date.now() < deadline) {
    if (page.isClosed()) {
      throw new Error(`${label} hub page is broken, not busy: Chromium closed it before readiness`);
    }
    try {
      const state = await page.evaluate(() => ({
        ready: window.__webshell?.ready === true,
        body: document.body.innerText.slice(-6000),
      }));
      lastBody = state.body;
      if (state.ready) {
        return;
      }
      if (state.body.includes("Browser shell failed hard:")) {
        throw new Error(`${label} hub page is broken, not busy:\n${state.body}`);
      }
    } catch (error: unknown) {
      if (error instanceof Error && error.message.includes("broken, not busy")) {
        throw error;
      }
      // A navigation execution-context swap is transient; the next probe
      // distinguishes it from a stable browser failure surface.
    }
    await delay(250);
  }
  throw new Error(`${label} hub page stayed busy for 120 seconds without a runnable harness\n${lastBody}`);
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

async function setupSurface(page: Page, spec: SurfaceSpec): Promise<void> {
  await page.evaluate(async (surface) => {
    const harness = window.__webshell;
    if (harness === undefined) {
      throw new Error("hub surface setup cannot reach the live harness");
    }
    await harness.setHubCaptureFreeze(true);
    if (surface.kind === "hub") {
      await harness.showHub();
    } else if (surface.kind === "npc") {
      if (surface.npcId === undefined) {
        throw new Error("NPC capture surface lost its unambiguous NPC id");
      }
      await harness.showHubNpc(surface.npcId);
    } else if (surface.kind === "service") {
      if (surface.npcId === undefined) {
        throw new Error("service capture surface lost its unambiguous NPC id");
      }
      await harness.showHubService(surface.npcId);
    } else {
      await harness.showRunShell();
    }
  }, {
    kind: spec.kind,
    ...(spec.kind === "npc" || spec.kind === "service" ? { npcId: spec.npc.id } : {}),
  });
  await settleFrame(page);
}

async function settleStructuralPayload(page: Page): Promise<SettleReceipt> {
  return page.evaluate(async () => {
    const harness = window.__webshell;
    if (harness === undefined) {
      throw new Error("settle gate cannot reach the live hub harness");
    }
    const payload = JSON.stringify(harness.renderPlan());
    const plan = harness.renderPlan();
    const started = performance.now();
    for (let sample = 1; sample <= 40; sample += 1) {
      await new Promise<void>((resolve) => setTimeout(resolve, 50));
      if (JSON.stringify(harness.renderPlan()) !== payload) {
        throw new Error(`hub structural payload changed before settle sample ${sample + 1}`);
      }
    }
    const spanMilliseconds = performance.now() - started;
    if (spanMilliseconds < 2000) {
      throw new Error(`hub settle gate sampled 41 structures across only ${spanMilliseconds.toFixed(3)} ms`);
    }
    const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(payload));
    const payloadSha256 = [...new Uint8Array(digest)]
      .map((value) => value.toString(16).padStart(2, "0"))
      .join("");
    return {
      sampleCount: 41,
      consecutiveMatches: 40,
      spanMilliseconds,
      payloadSha256,
      layoutId: plan.layoutId,
      commandCount: plan.commands.length,
      animatedElements: [],
    };
  });
}

function fileId(value: string): string {
  return value.replaceAll(".", "-");
}

function html(value: string): string {
  return value
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function pngDataUrl(bytes: Buffer): string {
  return `data:image/png;base64,${bytes.toString("base64")}`;
}

async function renderContractReference(
  page: Page,
  spec: SurfaceSpec,
  nativeVocabulary: Buffer,
  nativeMapPicker: Buffer,
  outputPath: string,
): Promise<void> {
  let heading: string;
  let rows: readonly string[];
  let note: string;
  let nativeImage: Buffer;
  let nativeImageLabel: string;
  if (spec.kind === "npc") {
    heading = `G8 NATIVE TALK REFERENCE — ${spec.npc.name}`;
    rows = [
      `region=${spec.npc.region}; class=${spec.npc.actorClass}; type_id=${spec.npc.typeId}; world_slot=${spec.npc.worldSlot}`,
      `position=(${spec.npc.x}, ${spec.npc.y}); radius=${spec.npc.radius}`,
      `flow=${spec.npc.pages.map((pageValue) => pageValue.id).join(" -> ")}`,
      ...(spec.npc.eulogyIndex === undefined ? [] : [`eulogy_index=${spec.npc.eulogyIndex}`]),
    ];
    note = "G8 landed actor, position, and flow data, but no native dialogue pixels. The P0 native pause panel below is visual-vocabulary evidence only.";
    nativeImage = nativeVocabulary;
    nativeImageLabel = "LANDED NATIVE PAUSE PANEL — STYLE VOCABULARY, NOT THIS NPC";
  } else if (spec.kind === "service") {
    const service = spec.npc.service;
    if (service === undefined) {
      throw new Error(`reference surface ${spec.npc.id} lost its service id`);
    }
    const offers = offersForService(service);
    heading = `G8 NATIVE SERVICE REFERENCE — ${spec.npc.name} / ${service}`;
    rows = offers.length === 0
      ? [`service=${service}; recorded flow=${spec.npc.pages.map((pageValue) => pageValue.id).join(" -> ")}`, "pinned offer rows=0"]
      : offers.slice(0, 8).map((offer, index) => (
        `${index}. ${offer.name}; type=${offer.type_id}; variant=${offer.variant_id ?? 0}; recipe=${offer.recipe_uid ?? 0}; price=${offer.price}; stock=${offer.quantity}`
      ));
    note = offers.length > 8
      ? `G8 pins ${offers.length} offers; this reference lists the eight rows visible at once. Exact full-table equality is separately replayed at T2.`
      : "G8 pins the values above. No native service pixels landed; the P0 native pause panel below is visual-vocabulary evidence only.";
    nativeImage = nativeVocabulary;
    nativeImageLabel = "LANDED NATIVE PAUSE PANEL — STYLE VOCABULARY, NOT THIS SERVICE";
  } else if (spec.kind === "run-shell") {
    heading = "G8/G13 NATIVE RUN-ENTRY REFERENCE";
    rows = [
      "entry=Courtyard MapPicker UI; portal_actor=false",
      "start_run=gameplay.courtyard -> loading.boneyard -> gameplay.arena",
      `phase_order=${G13_PHASE_ORDER.join(" -> ")}`,
      "solo barrier=participant set [0], stable 250 ms, timeout 25000 ms, release=all-ready",
      "destination after materialization=P1 visible run shell; gameplay=P2/P3",
    ];
    note = "The landed native MapPicker pixels are shown below; G13 supplies the transition ordering and barrier evidence. The run-shell itself is a new explicit scope boundary.";
    nativeImage = nativeMapPicker;
    nativeImageLabel = "LANDED NATIVE MAPPICKER — ACTUAL RUN-ENTRY UI";
  } else {
    throw new Error("the G12 hub reference is a direct rendered replay, not a generated contract panel");
  }
  const rowMarkup = rows.map((row) => `<li>${html(row)}</li>`).join("");
  await page.setViewportSize({ width: 1600, height: 900 });
  await page.setContent(`<!doctype html>
    <style>
      * { box-sizing: border-box; }
      html, body { width: 1600px; height: 900px; margin: 0; overflow: hidden; background: #05060a; color: #f2e5c7; }
      main { width: 100%; height: 100%; padding: 42px 58px; font-family: Georgia, serif; background: radial-gradient(circle at 50% 0%, #202033, #05060a 68%); }
      h1 { margin: 0 0 24px; color: #e2bc56; font: 30px/1.2 Georgia, serif; letter-spacing: 1px; }
      ul { min-height: 230px; margin: 0; padding: 22px 32px 18px 54px; border: 2px solid #8f6b24; background: rgb(4 3 9 / 92%); font: 19px/1.55 ui-monospace, monospace; }
      .note { margin: 18px 0 16px; color: #d4c8ad; font: 18px/1.35 Georgia, serif; }
      figure { display: grid; grid-template-columns: 650px 1fr; gap: 24px; align-items: center; margin: 0; }
      img { display: block; width: 650px; height: 365px; object-fit: cover; border: 1px solid #6e603e; }
      figcaption { color: #e2bc56; font: 20px/1.45 Georgia, serif; }
      .provenance { display: block; margin-top: 16px; color: #aaa; font: 15px/1.35 ui-monospace, monospace; }
    </style>
    <main>
      <h1>${html(heading)}</h1>
      <ul>${rowMarkup}</ul>
      <p class="note">${html(note)}</p>
      <figure><img alt="native visual vocabulary" src="${pngDataUrl(nativeImage)}"><figcaption>${html(nativeImageLabel)}<span class="provenance">Source: landed G8/G13 fixtures and committed G11 native reference capture.</span></figcaption></figure>
    </main>`);
  await page.waitForFunction(() => [...document.images].every((image) => image.complete));
  await page.screenshot({ path: outputPath, animations: "disabled" });
}

async function makeSideBySide(
  page: Page,
  label: string,
  referencePath: string,
  renderedPath: string,
  outputPath: string,
): Promise<void> {
  const [reference, rendered] = await Promise.all([readFile(referencePath), readFile(renderedPath)]);
  await page.setViewportSize({ width: 3200, height: 936 });
  await page.setContent(`<!doctype html>
    <style>
      * { box-sizing: border-box; }
      html, body { width: 3200px; height: 936px; margin: 0; overflow: hidden; background: #111; }
      main { display: grid; grid-template-columns: 1600px 1600px; grid-template-rows: 36px 900px; }
      h1 { margin: 0; color: #eee; background: #222; font: 19px/36px sans-serif; text-align: center; }
      img { display: block; width: 1600px; height: 900px; }
    </style>
    <main>
      <h1>LANDED NATIVE REFERENCE — ${html(label)}</h1><h1>P1 WEBGL — ${html(label)}</h1>
      <img alt="landed reference" src="${pngDataUrl(reference)}"><img alt="P1 WebGL" src="${pngDataUrl(rendered)}">
    </main>`);
  await page.waitForFunction(() => [...document.images].every((image) => image.complete));
  await page.screenshot({ path: outputPath, animations: "disabled" });
}

async function main(): Promise<void> {
  const assetRoot = requireConfiguration();
  const sourceSha = execFileSync("git", ["rev-parse", "HEAD"], {
    cwd: REPO_ROOT,
    encoding: "utf8",
  }).trim();
  const sourceStatus = execFileSync("git", ["status", "--porcelain=v1", "--untracked-files=all"], {
    cwd: REPO_ROOT,
    encoding: "utf8",
  }).trim();
  if (!/^[0-9a-f]{40}$/.test(sourceSha) || sourceStatus.length > 0) {
    throw new Error("final hub capture requires a clean checkout and a recorder-derived 40-hex source SHA");
  }
  const chromeVersion = execFileSync(CHROME, ["--version"], { encoding: "utf8" }).trim();
  const rawManifest = JSON.parse(await readFile(path.join(assetRoot, "asset-manifest.json"), "utf8")) as unknown;
  const manifestAssets = new ManifestAssets(rawManifest);
  const allowedAssetpackPaths = new Set([
    "/assetpack/asset-manifest.json",
    ...manifestAssets.manifest.atlases.map((atlas) => `/assetpack/${atlas.file}`),
  ]);
  assertAssetWitnesses(allowedAssetpackPaths);

  const menuGolden = JSON.parse(
    await readFile(path.join(REPO_ROOT, "tests", "fixtures", "webgame", "menu-goldens.json"), "utf8"),
  ) as unknown;
  const catalog = parseMenuCatalog(menuGolden);
  const pauseLayout = catalog.layouts.get("pause-menu");
  const mapPickerLayout = catalog.layouts.get("map-picker");
  if (pauseLayout === undefined || mapPickerLayout === undefined) {
    throw new Error("hub visual references lost the landed pause-menu or MapPicker witness");
  }
  const pauseReferencePath = path.join(REPO_ROOT, "tests", "fixtures", "webgame", pauseLayout.referenceCapture);
  const mapPickerReferencePath = path.join(REPO_ROOT, "tests", "fixtures", "webgame", mapPickerLayout.referenceCapture);
  const [pauseReferenceHash, mapPickerReferenceHash] = await Promise.all([
    sha256File(pauseReferencePath),
    sha256File(mapPickerReferencePath),
  ]);
  if (pauseReferenceHash !== pauseLayout.referenceSha256 || mapPickerReferenceHash !== mapPickerLayout.referenceSha256) {
    throw new Error("hub visual reference hash no longer matches the committed G11 fixture");
  }
  const [pauseReference, mapPickerReference] = await Promise.all([
    readFile(pauseReferencePath),
    readFile(mapPickerReferencePath),
  ]);

  const renderedRoot = path.join(EVIDENCE_ROOT, "hub-rendered-1600x900");
  const deckRoot = path.join(EVIDENCE_ROOT, "hub-rendered-1280x800");
  const referenceRoot = path.join(EVIDENCE_ROOT, "hub-native-references");
  const comparisonRoot = path.join(EVIDENCE_ROOT, "hub-side-by-side");
  await Promise.all([
    mkdir(renderedRoot, { recursive: true }),
    mkdir(deckRoot, { recursive: true }),
    mkdir(referenceRoot, { recursive: true }),
    mkdir(comparisonRoot, { recursive: true }),
  ]);

  const serviceNpcs = HUB_NPCS.filter((npc) => npc.service !== undefined);
  const specs: readonly SurfaceSpec[] = [
    { id: "hub", kind: "hub" },
    ...HUB_NPCS.map((npc): SurfaceSpec => ({ id: `npc-${fileId(npc.id)}`, kind: "npc", npc })),
    ...serviceNpcs.map((npc): SurfaceSpec => ({ id: `service-${fileId(npc.id)}`, kind: "service", npc })),
    { id: "run-shell", kind: "run-shell" },
  ];
  if (HUB_NPCS.length !== 20 || serviceNpcs.length !== 7 || specs.length !== 29) {
    throw new Error("hub capture census must reach one hub, twenty NPCs, seven services, and one run shell");
  }

  if (await endpointResponds(`${SERVER_URL}/`)) {
    throw new Error(`hub capture port ${SERVER_PORT} is busy; refusing to attach to an unowned server`);
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
  let activeSurface = "startup";
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
    const context = await browser.newContext({ viewport: { width: 1600, height: 900 } });
    const independentContext = await browser.newContext({ viewport: { width: 1600, height: 900 } });
    const page = await context.newPage();
    const independentPage = await independentContext.newPage();
    installFailureCapture(page, () => activeSurface, failures);
    installFailureCapture(independentPage, () => `${activeSurface}:independent`, failures);
    await Promise.all([
      page.goto(`${SERVER_URL}/?hub=1&focus=0`, { waitUntil: "domcontentloaded" }),
      independentPage.goto(`${SERVER_URL}/?hub=1&focus=0`, { waitUntil: "domcontentloaded" }),
    ]);
    await Promise.all([
      waitForHub(page, "primary"),
      waitForHub(independentPage, "independent"),
    ]);
    await Promise.all([
      page.evaluate(async () => window.__webshell?.setHubCaptureFreeze(true)),
      independentPage.evaluate(async () => window.__webshell?.setHubCaptureFreeze(true)),
    ]);

    activeSurface = "hub-g12-reference";
    await page.evaluate(async () => window.__webshell?.showHubReference());
    await settleFrame(page);
    const hubReferencePath = path.join(referenceRoot, "hub-g12-draw-list.png");
    await page.screenshot({ path: hubReferencePath, animations: "disabled" });
    const referencePlan = await page.evaluate(() => ({
      layoutId: window.__webshell?.renderPlan().layoutId,
      commandCount: window.__webshell?.renderPlan().commands.length,
    }));
    if (referencePlan.layoutId !== "hub.g12-reference" || referencePlan.commandCount !== 1319) {
      throw new Error("G12 rendered reference did not contain exactly the canonical 1,319 draws");
    }

    const settleReceipts: Record<string, readonly [SettleReceipt, SettleReceipt]> = {};
    const artifacts: Record<string, unknown>[] = [];
    for (const spec of specs) {
      activeSurface = spec.id;
      await Promise.all([setupSurface(page, spec), setupSurface(independentPage, spec)]);
      const [firstSettle, secondSettle] = await Promise.all([
        settleStructuralPayload(page),
        settleStructuralPayload(independentPage),
      ]);
      if (firstSettle.payloadSha256 !== secondSettle.payloadSha256) {
        throw new Error(`${spec.id} structural payload did not reproduce across two independent captures`);
      }
      if (firstSettle.animatedElements.length > firstSettle.commandCount * 0.3) {
        throw new Error(`${spec.id} classified more than 30 percent of its elements as animated`);
      }
      settleReceipts[spec.id] = [firstSettle, secondSettle];
      const renderedPath = path.join(renderedRoot, `${spec.id}.png`);
      await page.screenshot({ path: renderedPath, animations: "disabled" });

      let referencePath: string;
      let referenceKind: string;
      if (spec.kind === "hub") {
        referencePath = hubReferencePath;
        referenceKind = "exact_g12_draw_list_replay";
      } else {
        referencePath = path.join(referenceRoot, `${spec.id}.png`);
        const referencePage = await context.newPage();
        await renderContractReference(
          referencePage,
          spec,
          pauseReference,
          mapPickerReference,
          referencePath,
        );
        await referencePage.close();
        referenceKind = spec.kind === "run-shell"
          ? "g8_map_picker_pixels_plus_g13_contract"
          : "g8_data_plus_g11_native_style_vocabulary";
      }
      const sideBySidePath = path.join(comparisonRoot, `${spec.id}.png`);
      const comparisonPage = await context.newPage();
      await makeSideBySide(comparisonPage, spec.id, referencePath, renderedPath, sideBySidePath);
      await comparisonPage.close();
      const [referenceSha256, renderedSha256, sideBySideSha256] = await Promise.all([
        sha256File(referencePath),
        sha256File(renderedPath),
        sha256File(sideBySidePath),
      ]);
      artifacts.push({
        id: spec.id,
        kind: spec.kind,
        referenceKind,
        referenceSha256,
        renderedSha256,
        sideBySideSha256,
        structuralPayloadSha256: firstSettle.payloadSha256,
      });
      process.stdout.write(`settled/captured ${artifacts.length}/${specs.length}: ${spec.id}\n`);
    }
    // The second context exists only to reproduce each settle payload. Close
    // it before the single-client frame-time gate so SwiftShader is not asked
    // to benchmark two live 1,319-draw hubs at once.
    await independentContext.close();

    await page.setViewportSize({ width: 1280, height: 800 });
    for (const spec of specs) {
      activeSurface = `${spec.id}:1280x800`;
      await setupSurface(page, spec);
      const canvasRect = await page.locator("#game-canvas").evaluate((canvas) => {
        const rect = canvas.getBoundingClientRect();
        return [rect.x, rect.y, rect.width, rect.height];
      });
      if (JSON.stringify(canvasRect) !== JSON.stringify([0, 40, 1280, 720])) {
        throw new Error(`${spec.id} lost the 16:10 safe area: ${JSON.stringify(canvasRect)}`);
      }
      await page.screenshot({ path: path.join(deckRoot, `${spec.id}.png`), animations: "disabled" });
    }
    await context.close();

    activeSurface = "hub-performance";
    const performanceContext = await browser.newContext({ viewport: { width: 1280, height: 800 } });
    const performancePage = await performanceContext.newPage();
    installFailureCapture(performancePage, () => activeSurface, failures);
    await performancePage.goto(`${SERVER_URL}/?hub=1&focus=0`, { waitUntil: "domcontentloaded" });
    await waitForHub(performancePage, "performance");
    await performancePage.evaluate(async () => {
      await window.__webshell?.showHub();
      await window.__webshell?.setHubCaptureFreeze(false);
    });
    const liveHubPlan = await performancePage.evaluate(() => {
      const plan = window.__webshell?.renderPlan();
      return {
        commandCount: plan?.commands.length ?? 0,
        sceneCommandCount: plan?.commands.filter((command) => (
          command.kind === "scene-sprite" || command.kind === "scene-special"
        )).length ?? 0,
      };
    });
    if (liveHubPlan.sceneCommandCount !== 1319 || liveHubPlan.commandCount <= 1319) {
      throw new Error("live frame-time probe did not render the complete G12 hub plus P1 HUD");
    }
    const performanceReport = await performancePage.evaluate(async () => window.__webshell?.measureFrameTimes(600));
    if (performanceReport === undefined) {
      throw new Error("frame-time probe could not reach the live hub harness");
    }
    const framesPerSecond = 1000 / performanceReport.meanMs;
    if (framesPerSecond < 58 || performanceReport.p95Ms > 20.5) {
      throw new Error(
        `1280x800 live hub missed its 60fps budget: ${framesPerSecond.toFixed(2)}fps, p95 ${performanceReport.p95Ms.toFixed(3)}ms`,
      );
    }
    await performancePage.evaluate(async () => window.__webshell?.setHubCaptureFreeze(true));

    const browserAudit = await performancePage.evaluate(() => ({
      imageElements: document.images.length,
      canvasElements: document.querySelectorAll("canvas").length,
      inputElements: document.querySelectorAll("input").length,
      resources: performance.getEntriesByType("resource").map((entry) => ({
        name: entry.name,
        initiatorType: (entry as PerformanceResourceTiming).initiatorType,
      })),
    }));
    if (browserAudit.imageElements !== 0 || browserAudit.canvasElements !== 1 || browserAudit.inputElements !== 0) {
      throw new Error("live hub DOM must contain one WebGL canvas and no img or input elements");
    }
    const assetpackResources = browserAudit.resources.filter((entry) => (
      new URL(entry.name).pathname.startsWith("/assetpack/")
    ));
    if (assetpackResources.length === 0) {
      throw new Error("live hub asset audit reached no assetpack requests");
    }
    for (const resource of assetpackResources) {
      const pathname = new URL(resource.name).pathname;
      if (!allowedAssetpackPaths.has(pathname)) {
        throw new Error(`hub loaded asset outside the assetpack manifest: ${pathname}`);
      }
    }
    const webgl = await performancePage.locator("#game-canvas").evaluate((canvas) => {
      if (!(canvas instanceof HTMLCanvasElement)) {
        throw new Error("game canvas changed element type");
      }
      const gl = canvas.getContext("webgl2");
      if (gl === null) {
        throw new Error("live hub renderer lost WebGL2");
      }
      return {
        version: String(gl.getParameter(gl.VERSION)),
        renderer: String(gl.getParameter(gl.RENDERER)),
        vendor: String(gl.getParameter(gl.VENDOR)),
      };
    });
    await performanceContext.close();

    ownedDuringRun = (await descendants(process.pid)).filter((identity) => !baselinePids.has(identity.pid));
    if (ownedDuringRun.length === 0 || server.pid === undefined) {
      throw new Error("hub owned-process evidence did not reach the Vite/Chromium process tree");
    }
    if (failures.length > 0) {
      throw new Error(`hub browser emitted ${failures.length} console/page failures`);
    }
    report = {
      schema: "solomon-dark-p1-hub-capture-v1",
      source: { sha: sourceSha, dirty: false, provenance: "recorder-derived git rev-parse/status" },
      surfaceCount: specs.length,
      npcSurfaceCount: HUB_NPCS.length,
      serviceSurfaceCount: serviceNpcs.length,
      sideBySideCount: artifacts.length,
      deckRenderCount: specs.length,
      artifacts,
      settleGate: {
        rule: "two independent captures; 41 samples each; 40 consecutive byte-identical structural payloads spanning at least 2 seconds",
        animatedClassificationRule: "rect/unclipped_rect-only variation; capture freeze produced the stable empty animated set",
        receipts: settleReceipts,
      },
      references: {
        hub: "exact rendered replay of the landed G12 hub draw list",
        npcAndService: "landed G8 data beside actual P1 pixels; native dialogue/service pixels were not landed",
        nativeVocabulary: {
          pauseMenu: { path: pauseLayout.referenceCapture, sha256: pauseReferenceHash },
          mapPicker: { path: mapPickerLayout.referenceCapture, sha256: mapPickerReferenceHash },
        },
      },
      assetAudit: {
        manifestAtlasCount: manifestAssets.manifest.atlases.length,
        observedAssetpackRequestCount: assetpackResources.length,
        observedPaths: [...new Set(assetpackResources.map((resource) => new URL(resource.name).pathname))].sort(),
        domImageElementCount: browserAudit.imageElements,
      },
      safeArea1280x800: [0, 40, 1280, 720],
      performance: { ...performanceReport, framesPerSecond, liveHubPlan },
      webgl,
      machine: {
        platform: os.platform(),
        release: os.release(),
        cpu: os.cpus()[0]?.model ?? "unknown",
        logicalCpuCount: os.cpus().length,
        totalMemoryBytes: os.totalmem(),
        chrome: chromeVersion,
        node: process.version,
        headless: true,
        timingContext: "fresh single-client Chromium context after settle and capture contexts closed",
        deckHardwareGate: "OPEN",
        blindSpots: [
          "This is headless Chromium timing on the campaign machine, not Steam Deck hardware.",
          "No Deck compositor, thermal, battery, touchscreen, or physical-controller latency is represented.",
        ],
      },
      browserFailures: failures,
      server: { pid: server.pid, url: SERVER_URL, logTailSha256: sha256Text(serverLog), logTail: serverLog },
    };
  } catch (error: unknown) {
    const message = error instanceof Error ? error.stack ?? error.message : String(error);
    await writeFile(
      path.join(EVIDENCE_ROOT, "hub-capture-failure.log"),
      [message, "", "BROWSER FAILURES", JSON.stringify(failures, null, 2), "", "SERVER LOG", serverLog, ""].join("\n"),
      "utf8",
    );
    throw error;
  } finally {
    if (browser !== null) {
      await browser.close();
    }
    if (ownedDuringRun.length === 0) {
      ownedDuringRun = (await descendants(process.pid)).filter((identity) => !baselinePids.has(identity.pid));
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
    throw new Error(`owned hub capture processes survived cleanup: ${survivors.map((identity) => identity.pid).join(",")}`);
  }
  report.processCleanup = {
    capturePid: process.pid,
    baselineChildren,
    ownedDuringRun,
    serverTermination,
    verifiedGone: ownedDuringRun.map((identity) => identity.pid),
  };
  await writeFile(
    path.join(EVIDENCE_ROOT, "hub-capture-report.json"),
    `${JSON.stringify(report, null, 2)}\n`,
    "utf8",
  );
  const measuredPerformance = report.performance as { framesPerSecond: number; p95Ms: number };
  process.stdout.write([
    `captured ${specs.length} hub surfaces at native and Deck-safe sizes with ${specs.length} side-by-sides`,
    `1280x800 live hub: ${measuredPerformance.framesPerSecond.toFixed(2)}fps mean; ${measuredPerformance.p95Ms.toFixed(3)}ms p95`,
    `owned cleanup verified for ${ownedDuringRun.length} exact process identities`,
    "Deck hardware gate: OPEN",
    "",
  ].join("\n"));
}

function assertAssetWitnesses(allowedPaths: ReadonlySet<string>): void {
  if (allowedPaths.size < 2 || !allowedPaths.has("/assetpack/asset-manifest.json")) {
    throw new Error("hub asset audit did not reach a real manifest and at least one atlas witness");
  }
}

await main();
