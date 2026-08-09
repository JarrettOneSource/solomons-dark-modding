import menuGoldenJson from "../../tests/fixtures/webgame/menu-goldens.json" with { type: "json" };
import focusModelJson from "../../webgame-contracts/menu-focus-model.json" with { type: "json" };
import { GamepadProducer } from "../input/gamepad-producer.js";
import { parseFocusModel } from "../input/focus-model.js";
import type { Intent, Point2 } from "../input/intent.js";
import { parseIntent } from "../input/intent.js";
import { KeyboardMouseProducer } from "../input/keyboard-mouse-producer.js";
import { DEFAULT_HUB_CAMERA_SCALE } from "../input/twin-stick.js";
import { loadManifestAssets } from "./manifest-assets.js";
import { parseMenuCatalog } from "./menu-catalog.js";
import { HubController, type HubSnapshot } from "./hub-controller.js";
import { buildHubRenderPlan } from "./hub-render-plan.js";
import { buildHubScenePlan } from "./hub-scene.js";
import {
  buildOutOfScopePlan,
  buildRenderPlan,
  withLoaderProgress,
  type RenderPlan,
} from "./render-plan.js";
import { ShellController, type ShellSnapshot, type ShellStore } from "./shell-controller.js";
import { TextInputOverlay } from "./text-inputs.js";
import { WebGlShellRenderer } from "./webgl-renderer.js";

export interface FrameTimeReport {
  readonly sampleCount: number;
  readonly meanMs: number;
  readonly p50Ms: number;
  readonly p95Ms: number;
  readonly maxMs: number;
  readonly canvasPixels: readonly [number, number];
  readonly cssPixels: readonly [number, number];
}

export interface WebShellHarness {
  readonly ready: true;
  snapshot(): ShellSnapshot;
  hubSnapshot(): HubSnapshot;
  renderPlan(): RenderPlan;
  dispatch(value: unknown): void;
  showLayout(layoutId: string, preferredFocus?: string): Promise<void>;
  showHub(): Promise<void>;
  showHubReference(): Promise<void>;
  showHubNpc(npcId: string): Promise<void>;
  showHubService(npcId: string): Promise<void>;
  showRunShell(): Promise<void>;
  setHubCaptureFreeze(frozen: boolean): Promise<void>;
  advanceHub(milliseconds: number): Promise<void>;
  setEligibility(values: Parameters<ShellController["setEligibilityForConformance"]>[0]): Promise<void>;
  measureFrameTimes(sampleCount: number): Promise<FrameTimeReport>;
}

declare global {
  interface Window {
    __webshell?: WebShellHarness;
  }
}

function requiredElement<T extends Element>(selector: string, constructor: { new(): T }): T {
  const element = document.querySelector(selector);
  if (!(element instanceof constructor)) {
    throw new Error(`browser shell requires ${selector}`);
  }
  return element;
}

function browserStore(): ShellStore {
  return {
    get: (key) => window.localStorage.getItem(`webshell.${key}`),
    set: (key, value) => {
      window.localStorage.setItem(`webshell.${key}`, value);
    },
  };
}

function toNative(canvas: HTMLCanvasElement, point: Point2): Point2 {
  const bounds = canvas.getBoundingClientRect();
  return {
    x: (point.x - bounds.left) / bounds.width * 1600,
    y: (point.y - bounds.top) / bounds.height * 900,
  };
}

function percentile(sorted: readonly number[], fraction: number): number {
  return sorted[Math.min(sorted.length - 1, Math.floor((sorted.length - 1) * fraction))] ?? 0;
}

async function main(): Promise<void> {
  const canvas = requiredElement("#game-canvas", HTMLCanvasElement);
  const inputRoot = requiredElement("#text-inputs", HTMLDivElement);
  const catalog = parseMenuCatalog(menuGoldenJson);
  const focusModel = parseFocusModel(focusModelJson);
  const assets = await loadManifestAssets();
  assets.assertShellAssets(catalog);
  const renderer = new WebGlShellRenderer(canvas, assets);
  const controller = new ShellController(catalog, focusModel, { store: browserStore() });
  const hub = new HubController({
    openPause: () => {
      controller.handle({ kind: "interact", target: "pause", phase: "press" });
    },
    openMapPicker: () => {
      controller.showLayoutForConformance("map-picker");
    },
  });

  const loaderLayout = catalog.layouts.get("native-loader");
  if (loaderLayout === undefined) {
    throw new Error("G11 catalog lost the Raptisoft loader");
  }
  const loaderPlan = buildRenderPlan(loaderLayout, assets, null, false);
  await renderer.prepare(loaderPlan);
  renderer.render(withLoaderProgress(loaderPlan, 0));
  window.dispatchEvent(new CustomEvent("webshell:loader-progress", {
    detail: { completed: 0, total: catalog.screenCensus.length },
  }));

  // G11 boot is work-bound with no timer and no skip. Each completed unit is a
  // real layout dependency preparation; the loader exits only when all 28 can
  // draw without a deferred asset lookup.
  let completed = 0;
  for (const layoutId of catalog.screenCensus) {
    const layout = catalog.layouts.get(layoutId);
    if (layout === undefined) {
      throw new Error(`startup workload lost G11 layout ${layoutId}`);
    }
    await renderer.prepare(buildRenderPlan(layout, assets, null, false));
    completed += 1;
    renderer.render(withLoaderProgress(loaderPlan, completed / catalog.screenCensus.length));
    window.dispatchEvent(new CustomEvent("webshell:loader-progress", {
      detail: { completed, total: catalog.screenCensus.length },
    }));
  }

  const inputs = new TextInputOverlay(inputRoot, canvas, controller);
  const parameters = new URLSearchParams(window.location.search);
  const showFocus = parameters.get("focus") !== "0";
  let activePlan = loaderPlan;
  let currentSnapshot = controller.snapshot();
  let bareHubReference = false;
  let preparedHubWorldKey: string | null = null;
  let renderGeneration = 0;
  let renderSettled: Promise<void> = Promise.resolve();

  const hubWorldDependencyKey = (snapshot: HubSnapshot): string | null => (
    snapshot.surface.kind === "world"
      ? `${bareHubReference ? "reference" : "hub"}\0${snapshot.region}\0${snapshot.gold}\0${snapshot.nearestTargetId ?? ""}`
      : null
  );

  const installSnapshot = async (snapshot: ShellSnapshot): Promise<void> => {
    const generation = ++renderGeneration;
    currentSnapshot = snapshot;
    let nextPlan: RenderPlan;
    if (snapshot.surface.kind === "layout") {
      const layout = catalog.layouts.get(snapshot.surface.layoutId);
      if (layout === undefined) {
        throw new Error(`renderer cannot find active G11 layout ${snapshot.surface.layoutId}`);
      }
      nextPlan = buildRenderPlan(
        layout,
        assets,
        snapshot.focusId === null || snapshot.focusRect === null
          ? null
          : { id: snapshot.focusId, rect: snapshot.focusRect },
        showFocus,
      );
    } else if (snapshot.surface.kind === "hub-stub") {
      const hubSnapshot = hub.snapshot();
      nextPlan = bareHubReference
        ? buildHubScenePlan(assets, {
          player: hubSnapshot.player,
          heading: hubSnapshot.player.heading,
          moving: hubSnapshot.player.moving,
          presentationMilliseconds: hubSnapshot.presentationMilliseconds,
        }, [], "hub.g12-reference")
        : buildHubRenderPlan(assets, hubSnapshot);
    } else {
      nextPlan = buildOutOfScopePlan(snapshot.surface.message);
    }
    await renderer.prepare(nextPlan);
    if (generation !== renderGeneration) {
      return;
    }
    activePlan = nextPlan;
    if (snapshot.surface.kind === "hub-stub") {
      preparedHubWorldKey = hubWorldDependencyKey(hub.snapshot());
    }
    inputs.update(snapshot);
    renderer.render(activePlan);
  };
  controller.subscribe((snapshot) => {
    renderSettled = installSnapshot(snapshot);
  });

  hub.subscribe((snapshot) => {
    if (controller.snapshot().surface.kind === "hub-stub") {
      const generation = ++renderGeneration;
      const nextPlan = bareHubReference
        ? buildHubScenePlan(assets, {
          player: snapshot.player,
          heading: snapshot.player.heading,
          moving: snapshot.player.moving,
          presentationMilliseconds: snapshot.presentationMilliseconds,
        }, [], "hub.g12-reference")
        : buildHubRenderPlan(assets, snapshot);
      const worldKey = hubWorldDependencyKey(snapshot);
      if (worldKey !== null && worldKey === preparedHubWorldKey) {
        activePlan = nextPlan;
        renderSettled = Promise.resolve();
        return;
      }
      renderSettled = renderer.prepare(nextPlan).then(() => {
        if (generation !== renderGeneration) {
          return;
        }
        activePlan = nextPlan;
        preparedHubWorldKey = worldKey;
      });
    }
  });

  const sink = (intent: Intent): void => {
    controller.handle(intent);
  };
  const routeIntent = (intent: Intent): void => {
    const before = controller.snapshot();
    if (before.surface.kind === "hub-stub") {
      hub.handle(intent);
      return;
    }
    sink(intent);
    const after = controller.snapshot();
    if (
      before.surface.kind === "layout"
      && before.surface.layoutId === "map-picker"
      && after.surface.kind === "out-of-scope"
    ) {
      controller.showHubForConformance();
      hub.beginRunEntry();
    }
  };
  const menuTargetAt = (point: Point2): string | null => {
    const native = toNative(canvas, point);
    return currentSnapshot.focusNodes.find((node) => (
      node.enabled
      && native.x >= node.nativeRect[0]
      && native.x <= node.nativeRect[2]
      && native.y >= node.nativeRect[1]
      && native.y <= node.nativeRect[3]
    ))?.id ?? null;
  };
  const keyboardMouse = new KeyboardMouseProducer(routeIntent, () => ({
    surface: controller.snapshot().surface.kind === "hub-stub"
      ? hub.inputSurface
      : controller.inputSurface,
    screenToWorld: (point) => toNative(canvas, point),
    menuTargetAt,
  }));
  const gamepad = new GamepadProducer(routeIntent, () => {
    const interactTarget = hub.interactTarget;
    return {
      surface: controller.snapshot().surface.kind === "hub-stub"
        ? hub.inputSurface
        : controller.inputSurface,
      aimProjection: {
        playerWorld: hub.snapshot().player,
        projectedPlayerPx: {
          x: (hub.snapshot().player.x - 333.333374) * DEFAULT_HUB_CAMERA_SCALE,
          y: hub.snapshot().player.y * DEFAULT_HUB_CAMERA_SCALE,
        },
        viewportPx: { width: 1600, height: 900 },
        cameraScale: DEFAULT_HUB_CAMERA_SCALE,
      },
      ...(interactTarget === null ? {} : { interactTarget }),
    };
  });
  keyboardMouse.start();

  const requestedLayout = parameters.get("screen");
  if (parameters.get("hub") === "1") {
    controller.showHubForConformance();
  } else if (requestedLayout !== null) {
    controller.showLayoutForConformance(requestedLayout);
  } else {
    controller.completeBoot(browserStore().get("control_scheme") === null);
    // G11 section "Presentation rules" records this 1.1-second fade only for
    // first Title/MainMenu entry. The controller separately enforces the
    // native 2.0-second input gate; neither timing is generalized to edges.
    canvas.animate(
      [{ opacity: 0 }, { opacity: 1 }],
      { duration: 1100, easing: "linear", fill: "both" },
    );
    window.dispatchEvent(new CustomEvent("webshell:title-enter", {
      detail: { fadeMilliseconds: 1100, inputGateMilliseconds: 2000 },
    }));
  }
  await renderSettled;

  const measureFrameTimes = async (sampleCount: number): Promise<FrameTimeReport> => {
    if (!Number.isInteger(sampleCount) || sampleCount < 2 || sampleCount > 3600) {
      throw new Error("frame-time sample count must be an integer in [2,3600]");
    }
    const samples: number[] = [];
    let previous = await new Promise<number>((resolve) => requestAnimationFrame(resolve));
    while (samples.length < sampleCount) {
      const next = await new Promise<number>((resolve) => requestAnimationFrame(resolve));
      samples.push(next - previous);
      previous = next;
    }
    const sorted = [...samples].sort((left, right) => left - right);
    const css = canvas.getBoundingClientRect();
    return {
      sampleCount,
      meanMs: samples.reduce((total, value) => total + value, 0) / samples.length,
      p50Ms: percentile(sorted, 0.5),
      p95Ms: percentile(sorted, 0.95),
      maxMs: sorted.at(-1) ?? 0,
      canvasPixels: [canvas.width, canvas.height],
      cssPixels: [css.width, css.height],
    };
  };

  window.__webshell = {
    ready: true,
    snapshot: () => controller.snapshot(),
    hubSnapshot: () => hub.snapshot(),
    renderPlan: () => activePlan,
    dispatch: (value) => {
      routeIntent(parseIntent(value));
    },
    showLayout: async (layoutId, preferredFocus) => {
      controller.showLayoutForConformance(layoutId, preferredFocus);
      await renderSettled;
      renderer.render(activePlan);
    },
    showHub: async () => {
      bareHubReference = false;
      hub.showCourtyardForConformance();
      controller.showHubForConformance();
      await renderSettled;
      renderer.render(activePlan);
    },
    showHubReference: async () => {
      bareHubReference = true;
      hub.showCourtyardForConformance();
      controller.showHubForConformance();
      await renderSettled;
      renderer.render(activePlan);
    },
    showHubNpc: async (npcId) => {
      bareHubReference = false;
      controller.showHubForConformance();
      hub.showNpcForConformance(npcId);
      await renderSettled;
      renderer.render(activePlan);
    },
    showHubService: async (npcId) => {
      bareHubReference = false;
      controller.showHubForConformance();
      hub.showServiceForConformance(npcId);
      await renderSettled;
      renderer.render(activePlan);
    },
    showRunShell: async () => {
      bareHubReference = false;
      controller.showHubForConformance();
      hub.showCourtyardForConformance();
      hub.beginRunEntry();
      hub.advance(1000);
      hub.advance(270);
      await renderSettled;
      renderer.render(activePlan);
    },
    setHubCaptureFreeze: async (frozen) => {
      hub.setPresentationFrozenForCapture(frozen);
      await renderSettled;
      renderer.render(activePlan);
    },
    advanceHub: async (milliseconds) => {
      hub.advance(milliseconds);
      await renderSettled;
      renderer.render(activePlan);
    },
    setEligibility: async (values) => {
      controller.setEligibilityForConformance(values);
      await renderSettled;
      renderer.render(activePlan);
    },
    measureFrameTimes,
  };

  let previousFrame = performance.now();
  const frame = (timestamp: number): void => {
    const delta = Math.min(100, Math.max(0, timestamp - previousFrame));
    previousFrame = timestamp;
    controller.tick();
    if (controller.snapshot().surface.kind === "hub-stub") {
      hub.advance(delta);
      renderer.setHubPresentationMilliseconds(hub.snapshot().presentationMilliseconds);
      // P1 exercises the complete G12 draw list in the live frame loop. The
      // measured 60 Hz gate therefore includes real hub WebGL work.
      renderer.render(activePlan);
    }
    gamepad.pollBrowserGamepads();
    keyboardMouse.tick();
    requestAnimationFrame(frame);
  };
  requestAnimationFrame(frame);
}

void main().catch((error: unknown) => {
  const message = error instanceof Error ? error.stack ?? error.message : String(error);
  document.body.textContent = `Browser shell failed hard:\n${message}`;
  throw error;
});
