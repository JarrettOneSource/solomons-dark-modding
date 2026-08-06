import assert from "node:assert/strict";
import { readFile, writeFile } from "node:fs/promises";
import path from "node:path";

import type { AssetManifest } from "../assets/types.js";
import { ManifestAssets } from "../client/manifest-assets.js";
import { parseMenuCatalog } from "../client/menu-catalog.js";
import { buildRenderPlan, G12_LAYER_ORDER } from "../client/render-plan.js";

// The golden contains decimal coordinates, but replay never rescales them
// before comparison. IEEE-754 parses the same JSON numeral identically on both
// sides, so epsilon 0 is intentional; rasterization tolerance is not smuggled
// into this T2 layout gate.
const POSITION_EPSILON = 0;

const repository = path.resolve(import.meta.dirname, "..", "..");
const goldenPath = path.join(repository, "tests", "fixtures", "webgame", "menu-goldens.json");
const assetGoldenPath = path.join(
  repository,
  "webgame",
  "assets",
  "fixtures",
  "asset-manifest-goldens.json",
);

type JsonObject = Record<string, unknown>;

function object(value: unknown, label: string): JsonObject {
  assert(value !== null && typeof value === "object" && !Array.isArray(value), `${label} must exist`);
  return value as JsonObject;
}

function array(value: unknown, label: string): unknown[] {
  assert(Array.isArray(value), `${label} must be an array`);
  return value;
}

function stringArray(value: unknown, label: string): string[] {
  const result = array(value, label);
  assert(result.every((entry) => typeof entry === "string"), `${label} must contain ids`);
  return result;
}

function conformanceManifest(artIds: readonly string[], fontIds: readonly string[]): AssetManifest {
  const provenance = {
    sourceBundleFilename: "conformance-only",
    recordIndex: 0,
    sourceBytesSha256: "0".repeat(64),
  };
  const entries: AssetManifest["entries"] = Object.fromEntries(
    [...artIds, "Conformance.0"].map((id) => [id, {
      kind: "sprite" as const,
      atlas: "Conformance",
      rect: { x: 0, y: 0, width: 1, height: 1 },
      pivot: { x: 0, y: 0 },
      logicalSize: { width: 1, height: 1 },
      rotated: false,
      points: [],
      provenance: { ...provenance, sourceOffset: 0, sourceLength: 1 },
    }]),
  );
  const glyphs = Object.fromEntries(
    Array.from({ length: 94 }, (_, index) => [String(index + 33), "Conformance.0"]),
  );
  const bitmapFonts = Object.fromEntries(
    fontIds.filter((id) => id !== "Segoe UI").map((id) => [id, {
      atlas: "Conformance",
      firstRecord: 0,
      lastRecord: 0,
      metrics: [24, 6, 28] as const,
      kerning: [],
      glyphs,
      provenance: { ...provenance, sourceOffset: 0, sourceLength: 1 },
    }]),
  );
  return {
    schema: "solomon-dark-web-asset-manifest-v1",
    nativeIdFormat: "<Atlas>.<record-index>",
    sources: {
      bundleDecoder: "tools/extract_bundles.py",
      boneyardDecoder: "tools/decode_boneyard_scripts.py",
      nativeAssetObjectMap: "conformance-only",
      nativeSceneAtlasSpans: "conformance-only",
      nativeContentInventory: "conformance-only",
    },
    summary: {
      atlasCount: 1,
      bundleAtlasCount: 1,
      looseAtlasCount: 0,
      spriteCount: Object.keys(entries).length,
      aliasCount: 0,
      fontGroupCount: Object.keys(bitmapFonts).length,
    },
    atlases: [{
      id: "Conformance",
      file: "conformance-only.png",
      width: 1,
      height: 1,
      bytes: 1,
      sha256: "0".repeat(64),
      provenance,
    }],
    entries,
    aliases: {},
    fontGroups: bitmapFonts,
    specialDraws: {
      "Segoe UI": { kind: "system-font", sourceGoldenFilename: "menu-goldens.json" },
    },
    packs: {
      boneyards: { file: "unused", bytes: 1, sha256: "0".repeat(64), entryCount: 0 },
      recipes: { file: "unused", bytes: 1, sha256: "0".repeat(64), entryCount: 0 },
      waves: { file: "unused", bytes: 1, sha256: "0".repeat(64), entryCount: 0 },
    },
  };
}

function exactCoordinate(actual: number, expected: number, claim: string): void {
  assert(
    Math.abs(actual - expected) <= POSITION_EPSILON,
    `${claim} moved from ${expected} to ${actual}; T2 positions are exact`,
  );
}

async function main(): Promise<void> {
  const embedded = JSON.parse(await readFile(goldenPath, "utf8")) as unknown;
  const catalog = parseMenuCatalog(embedded);
  const root = object(embedded, "G11 embedded golden");
  const wrappers = array(root.layouts, "G11 embedded layouts");
  const assetGolden = object(
    JSON.parse(await readFile(assetGoldenPath, "utf8")) as unknown,
    "assetpack golden",
  );
  const references = object(assetGolden.references, "assetpack references");
  const menuArtIds = stringArray(references.menuArtIds, "assetpack menuArtIds");
  const menuFontIds = stringArray(references.menuFontIds, "assetpack menuFontIds");
  const resolutions = object(references.resolutions, "assetpack reference resolutions");
  assert(menuArtIds.includes("Loader.2"), "assetpack menu audit must reach the Raptisoft logo witness");
  assert(menuArtIds.includes("Wizards_dire_BG"), "assetpack menu audit must reach loading art");
  for (const artId of menuArtIds) {
    assert(resolutions[artId] !== undefined, `assetpack golden does not resolve menu art ${artId}`);
  }
  const assets = new ManifestAssets(conformanceManifest(menuArtIds, menuFontIds));
  assets.assertShellAssets(catalog);

  let elementCount = 0;
  let artCount = 0;
  for (const wrapperValue of wrappers) {
    const wrapper = object(wrapperValue, "G11 embedded layout wrapper");
    const fixture = String(wrapper.fixture);
    const standalonePath = path.join(repository, "tests", "fixtures", "webgame", fixture);
    const standalone = object(
      JSON.parse(await readFile(standalonePath, "utf8")) as unknown,
      `${fixture} standalone fixture`,
    );
    assert.deepEqual(
      standalone.layout,
      wrapper.layout,
      `${fixture} standalone layout diverges from the embedded G11 recording`,
    );
    const layoutId = path.basename(fixture, ".json");
    const layout = catalog.layouts.get(layoutId);
    assert(layout !== undefined, `${layoutId} did not enter the replay catalog`);
    const plan = buildRenderPlan(layout, assets, null, false);
    assert.deepEqual(
      plan.layerOrder,
      G12_LAYER_ORDER,
      `${layoutId} did not retain the five-pass G12 composition order`,
    );
    const rawLayout = object(wrapper.layout, `${layoutId} embedded layout`);
    const rawElements = array(rawLayout.elements, `${layoutId} embedded elements`);
    assert.equal(
      plan.elements.length,
      rawElements.length,
      `${layoutId} replay omitted G11 elements`,
    );
    for (const [index, planned] of plan.elements.entries()) {
      const raw = object(rawElements[index], `${layoutId} element ${index}`);
      assert.equal(planned.id, raw.id, `${layoutId} replay changed element identity at ${index}`);
      assert.equal(planned.kind, raw.kind, `${planned.id} replay changed element kind`);
      assert.equal(planned.artId, raw.art_id, `${planned.id} replay changed manifest art id`);
      assert.equal(planned.fontId, raw.font_id, `${planned.id} replay changed manifest font id`);
      assert.equal(planned.actionId, raw.action_id, `${planned.id} replay changed action id`);
      assert.equal(planned.visible, raw.visible, `${planned.id} replay changed visibility`);
      assert.equal(planned.interactive, raw.interactive, `${planned.id} replay changed interactivity`);
      assert.equal(planned.drawOrder, raw.draw_order, `${planned.id} replay changed draw order`);
      const rawRect = array(raw.rect, `${planned.id}.rect`) as number[];
      const rawUnclipped = array(raw.unclipped_rect, `${planned.id}.unclipped_rect`) as number[];
      for (let coordinate = 0; coordinate < 4; coordinate += 1) {
        exactCoordinate(
          planned.rect[coordinate] ?? Number.NaN,
          rawRect[coordinate] ?? Number.NaN,
          `${planned.id}.rect[${coordinate}]`,
        );
        exactCoordinate(
          planned.unclippedRect[coordinate] ?? Number.NaN,
          rawUnclipped[coordinate] ?? Number.NaN,
          `${planned.id}.unclipped_rect[${coordinate}]`,
        );
      }
      if (planned.kind === "art") {
        artCount += 1;
        assert(menuArtIds.includes(planned.artId), `${planned.id} references art outside assetpack menuArtIds`);
      }
      elementCount += 1;
    }
  }

  // 1280x800 uses the G11 1600x900 coordinate space at exactly 0.8 scale,
  // centered vertically with 40 px letterbox safe areas.
  assert.equal(1600 * 0.8, 1280, "16:10 safe-area width must fill 1280 pixels");
  assert.equal(900 * 0.8 + 40 * 2, 800, "16:10 safe-area bars must total 80 pixels");

  const report = [
    "T2 G11 layout replay: PASS",
    `screens=${catalog.layouts.size}/28`,
    `elements=${elementCount}`,
    `art_references=${artCount}`,
    `position_epsilon=${POSITION_EPSILON} (same JSON numerals, no pre-assert scaling)`,
    "safe_area_1280x800=1280x720+40px_top+40px_bottom",
  ].join("\n") + "\n";
  const output = process.env.WEBGAME_CONFORMANCE_LOG;
  if (output !== undefined) {
    await writeFile(output, report, "utf8");
  }
  process.stdout.write(report);
}

await main();
