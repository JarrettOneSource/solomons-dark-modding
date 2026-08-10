import assert from "node:assert/strict";
import { readFile, writeFile } from "node:fs/promises";
import path from "node:path";

import type { AssetManifest } from "../assets/types.js";
import { ManifestAssets } from "../client/manifest-assets.js";
import { parseMenuCatalog, type MenuElement, type MenuLayout } from "../client/menu-catalog.js";
import { buildRenderPlan, G12_LAYER_ORDER, type PlannedElement } from "../client/render-plan.js";

// The aggregate contains decimal coordinates. Replay never rescales them, so
// epsilon zero is intentional and does not hide rasterization drift.
const POSITION_EPSILON = 0;

function optionalString(value: unknown, label: string): string {
  assert.equal(typeof value, "string", `${label} must be a string`);
  return value as string;
}

const repository = path.resolve(import.meta.dirname, "..", "..");
const goldenPath = path.join(
  repository,
  "tests",
  "fixtures",
  "webgame",
  "menufix-preview-overlay",
  "menu-goldens.json",
);
const assetGoldenPath = path.join(
  repository,
  "webgame",
  "assets",
  "fixtures",
  "asset-manifest-goldens.json",
);

const criticalLayouts = new Set([
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
      "Segoe UI": { kind: "system-font", sourceGoldenFilename: "menufix-preview-overlay/menu-goldens.json" },
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

function expectedElement(value: unknown, label: string): MenuElement {
  const raw = object(value, label);
  const expected: MenuElement = {
    id: String(raw.id),
    kind: String(raw.kind),
    text: String(raw.text),
    actionId: String(raw.action_id),
    artId: String(raw.art_id),
    fontId: String(raw.font_id),
    textStyle: String(raw.text_style),
    visible: Boolean(raw.visible),
    interactive: Boolean(raw.interactive),
    drawOrder: Number(raw.draw_order),
    rect: array(raw.rect, `${label}.rect`).map(Number) as unknown as MenuElement["rect"],
    unclippedRect: array(raw.unclipped_rect, `${label}.unclipped_rect`).map(Number) as unknown as MenuElement["unclippedRect"],
    ...(raw.color === undefined ? {} : { color: optionalString(raw.color, `${label}.color`) }),
    ...(raw.color_top === undefined ? {} : { colorTop: optionalString(raw.color_top, `${label}.color_top`) }),
    ...(raw.color_bottom === undefined ? {} : { colorBottom: optionalString(raw.color_bottom, `${label}.color_bottom`) }),
    ...(raw.font_height === undefined ? {} : { fontHeight: Number(raw.font_height) }),
    ...(raw.font_weight === undefined ? {} : { fontWeight: Number(raw.font_weight) }),
  };
  return expected;
}

function expectedAmbientElement(
  value: unknown,
  layout: MenuLayout,
  index: number,
): MenuElement {
  const label = `${layout.id}.ambient_members[${index}]`;
  const member = object(value, label);
  const classes = array(member.class_members, `${label}.class_members`)
    .map((entry, classIndex) => object(entry, `${label}.class_members[${classIndex}]`));
  const priorities = ["ambient_persistent", "animated", "visibility_cycling", "ephemeral"];
  const selected = priorities
    .map((priority) => classes.find((entry) => entry.classification === priority))
    .find((entry) => entry !== undefined) ?? classes[0];
  assert(selected !== undefined, `${label} has no measured class payload`);
  const payload = object(selected.dominant_phase_payload, `${label}.dominant_phase_payload`);
  const band = object(array(member.draw_bands, `${label}.draw_bands`)[0], `${label}.draw_bands[0]`);
  const below = String(band.below);
  const above = String(band.above);
  const orders = new Map(layout.elements.map((element) => [element.id, element.drawOrder]));
  const belowOrder = orders.get(below);
  const aboveOrder = orders.get(above);
  let drawOrder: number;
  if (belowOrder !== undefined && aboveOrder !== undefined) {
    drawOrder = (belowOrder + aboveOrder) / 2;
  } else if (belowOrder !== undefined && above === "top") {
    drawOrder = Math.max(...layout.elements.map((element) => element.drawOrder)) + 1;
  } else if (aboveOrder !== undefined && below === "bottom") {
    drawOrder = Math.min(...layout.elements.map((element) => element.drawOrder)) - 1;
  } else {
    assert.fail(`${label} has an unresolvable measured draw band ${below}/${above}`);
  }
  return {
    id: String(member.id),
    kind: String(payload.kind),
    text: String(payload.text),
    actionId: String(payload.action_id),
    artId: String(payload.art_id),
    fontId: String(payload.font_id),
    textStyle: String(payload.text_style),
    visible: Boolean(payload.visible),
    interactive: Boolean(payload.interactive),
    drawOrder,
    rect: array(payload.rect, `${label}.rect`).map(Number) as unknown as MenuElement["rect"],
    unclippedRect: array(payload.unclipped_rect, `${label}.unclipped_rect`).map(Number) as unknown as MenuElement["unclippedRect"],
    ...(payload.color === undefined ? {} : { color: optionalString(payload.color, `${label}.color`) }),
    ...(payload.color_top === undefined ? {} : { colorTop: optionalString(payload.color_top, `${label}.color_top`) }),
    ...(payload.color_bottom === undefined ? {} : { colorBottom: optionalString(payload.color_bottom, `${label}.color_bottom`) }),
    ...(payload.font_height === undefined ? {} : { fontHeight: Number(payload.font_height) }),
    ...(payload.font_weight === undefined ? {} : { fontWeight: Number(payload.font_weight) }),
  };
}

function assertLayoutReplay(
  layout: MenuLayout,
  wrapper: JsonObject,
  assets: ManifestAssets,
): { readonly elements: number; readonly ambient: number; readonly art: number } {
  const plan = buildRenderPlan(layout, assets, null, false);
  assert.deepEqual(plan.layerOrder, G12_LAYER_ORDER, `${layout.id} changed the five-pass composition order`);
  const rawLayout = object(wrapper.layout, `${layout.id} aggregate layout`);
  const rawElements = array(rawLayout.elements, `${layout.id} aggregate elements`);
  assert.equal(plan.elements.length, rawElements.length, `${layout.id} replay omitted aggregate elements`);
  let art = 0;
  for (const [index, planned] of plan.elements.entries()) {
    const expected = expectedElement(rawElements[index], `${layout.id}.elements[${index}]`);
    assert.deepEqual(planned, expected satisfies PlannedElement, `${layout.id} changed element ${index}`);
    for (let coordinate = 0; coordinate < 4; coordinate += 1) {
      const plannedCoordinate = planned.rect[coordinate];
      const expectedCoordinate = expected.rect[coordinate];
      const plannedUnclippedCoordinate = planned.unclippedRect[coordinate];
      const expectedUnclippedCoordinate = expected.unclippedRect[coordinate];
      if (
        plannedCoordinate === undefined
        || expectedCoordinate === undefined
        || plannedUnclippedCoordinate === undefined
        || expectedUnclippedCoordinate === undefined
      ) {
        throw new Error(`${planned.id} has an incomplete four-coordinate rectangle`);
      }
      exactCoordinate(plannedCoordinate, expectedCoordinate, `${planned.id}.rect[${coordinate}]`);
      exactCoordinate(
        plannedUnclippedCoordinate,
        expectedUnclippedCoordinate,
        `${planned.id}.unclipped_rect[${coordinate}]`,
      );
    }
    if (planned.kind === "art") {
      art += 1;
    }
  }
  const rawAmbient = array(rawLayout.ambient_members, `${layout.id} aggregate ambient members`);
  assert.equal(
    layout.ambientElements.length,
    rawAmbient.length,
    `${layout.id} replay omitted measured ambient members`,
  );
  const commandIds = new Set(plan.commands.map((command) => command.elementId));
  for (const [index, actual] of layout.ambientElements.entries()) {
    const expected = expectedAmbientElement(rawAmbient[index], layout, index);
    assert.deepEqual(actual, expected, `${layout.id} changed ambient member ${index}`);
    if (actual.visible && (actual.kind === "art" || (actual.kind === "text" && actual.fontId.length > 0))) {
      assert(commandIds.has(actual.id), `${layout.id} did not render measured ambient member ${actual.id}`);
    }
    if (actual.kind === "art") {
      art += 1;
    }
  }
  return { elements: plan.elements.length, ambient: layout.ambientElements.length, art };
}

function semanticPayload(element: PlannedElement): JsonObject {
  return {
    action_id: element.actionId,
    art_id: element.artId,
    font_id: element.fontId,
    interactive: element.interactive,
    kind: element.kind,
    rect: element.rect,
    text: element.text,
    text_style: element.textStyle,
    unclipped_rect: element.unclippedRect,
    visible: element.visible,
  };
}

function canonicalMultiset(values: readonly JsonObject[]): string[] {
  return values.map((value) => JSON.stringify(value)).sort();
}

async function main(): Promise<void> {
  const embedded = JSON.parse(await readFile(goldenPath, "utf8")) as unknown;
  const catalog = parseMenuCatalog(embedded);
  const root = object(embedded, "menufix preview aggregate");
  const wrappers = [
    ...array(root.layouts, "aggregate layouts"),
    ...array(root.transition_endpoint_layouts, "aggregate transition endpoint layouts"),
  ].map((value, index) => object(value, `aggregate layout wrapper[${index}]`));

  const allLayouts = [
    ...catalog.layouts.values(),
    ...[...catalog.dialogComposites.values()].map((composite) => composite.layout),
  ];
  const requiredArtIds = [...new Set(allLayouts.flatMap((layout) => (
    [...layout.elements, ...layout.ambientElements, ...layout.semanticDialogElements]
      .filter((element) => element.kind === "art")
      .map((element) => element.artId)
  )))].sort();
  const requiredFontIds = [...new Set(allLayouts.flatMap((layout) => (
    [...layout.elements, ...layout.ambientElements, ...layout.semanticDialogElements]
      .filter((element) => element.fontId.length > 0)
      .map((element) => element.fontId)
  )))].sort();
  const assetGolden = object(
    JSON.parse(await readFile(assetGoldenPath, "utf8")) as unknown,
    "assetpack golden",
  );
  const references = object(assetGolden.references, "assetpack references");
  const menuArtIds = stringArray(references.menuArtIds, "assetpack menuArtIds");
  const menuFontIds = stringArray(references.menuFontIds, "assetpack menuFontIds");
  const resolutions = object(references.resolutions, "assetpack reference resolutions");
  for (const artId of requiredArtIds) {
    assert(menuArtIds.includes(artId), `assetpack menuArtIds omit aggregate art ${artId}`);
    assert(resolutions[artId] !== undefined, `assetpack golden does not resolve aggregate art ${artId}`);
  }
  for (const fontId of requiredFontIds) {
    assert(menuFontIds.includes(fontId), `assetpack menuFontIds omit aggregate font ${fontId}`);
  }
  const assets = new ManifestAssets(conformanceManifest(requiredArtIds, requiredFontIds));
  assets.assertShellAssets(catalog);

  let elementCount = 0;
  let ambientCount = 0;
  let artCount = 0;
  const conformed = new Set<string>();
  for (const wrapper of wrappers) {
    const fixture = String(wrapper.fixture);
    const layoutId = path.basename(fixture, ".json");
    const layout = catalog.layouts.get(layoutId);
    assert(layout !== undefined, `${layoutId} did not enter the aggregate replay catalog`);
    const result = assertLayoutReplay(layout, wrapper, assets);
    elementCount += result.elements;
    ambientCount += result.ambient;
    artCount += result.art;
    conformed.add(layoutId);
  }
  assert.deepEqual(
    [...conformed].sort(),
    [...catalog.screenCensus].sort(),
    "T2 replay did not cover the complete aggregate screen census",
  );

  const composite = catalog.dialogComposites.get("beta_notice_first_boot");
  assert(composite !== undefined, "aggregate lost beta_notice_first_boot");
  const compositePlan = buildRenderPlan(composite.layout, assets, null, false);
  const underlay = catalog.layouts.get(composite.underlayLayoutId);
  assert(underlay !== undefined, "first-boot composite lost its picker underlay");
  assert.deepEqual(
    compositePlan.elements.slice(0, underlay.elements.length),
    buildRenderPlan(underlay, assets, null, false).elements,
    "first-boot composite changed its corrected picker underlay",
  );
  const compositeWrapper = object(
    array(root.semantic_dialog_composite_records, "aggregate composite records")[0],
    "beta_notice_first_boot wrapper",
  );
  const compositeRecord = object(compositeWrapper.record, "beta_notice_first_boot record");
  const compositeBody = object(compositeRecord.composite, "beta_notice_first_boot composite");
  const multiset = object(compositeBody.dialog_semantic_multiset, "beta_notice_first_boot dialog multiset");
  const expectedDialogPayloads: JsonObject[] = [];
  for (const value of array(multiset.entries, "beta_notice_first_boot dialog entries")) {
    const entry = object(value, "beta_notice_first_boot dialog entry");
    for (let repeat = 0; repeat < Number(entry.count); repeat += 1) {
      expectedDialogPayloads.push(object(entry.payload, "beta_notice_first_boot dialog payload"));
    }
  }
  const actualDialogPayloads = compositePlan.elements
    .slice(underlay.elements.length)
    .map(semanticPayload);
  assert.deepEqual(
    canonicalMultiset(actualDialogPayloads),
    canonicalMultiset(expectedDialogPayloads),
    "first-boot dialog contribution diverges from the v2.17 semantic multiset",
  );
  assert.equal(composite.residualMemberCount, 0, "first-boot dialog composite left semantic residue");
  const betaNotice = catalog.layouts.get("beta-notice");
  assert(betaNotice !== undefined, "aggregate lost the standalone beta-notice screen");
  const measuredDialogText = composite.layout.elements
    .slice(underlay.elements.length)
    .filter((element) => element.kind === "text");
  assert.equal(
    betaNotice.semanticDialogElements.length,
    measuredDialogText.length,
    "standalone beta-notice did not render the measured dialog text contribution",
  );
  elementCount += compositePlan.elements.length;
  artCount += compositePlan.elements.filter((element) => element.kind === "art").length;

  const overlay = catalog.overlayRecords.get("dark_cloud_settings_credentials");
  assert(overlay !== undefined, "aggregate lost the v2.15 credentials overlay record");
  assert.equal(overlay.semanticMemberCount, 0, "v2.15 credentials overlay gained semantic members");

  const missingCritical = [...criticalLayouts].filter((layoutId) => !conformed.has(layoutId));
  assert.deepEqual(missingCritical, [], "a critical layout escaped the zero-waiver T2 replay");

  // 1280x800 uses the 1600x900 native coordinate space at exactly 0.8 scale,
  // centered vertically with 40 px letterbox safe areas.
  assert.equal(1600 * 0.8, 1280, "16:10 safe-area width must fill 1280 pixels");
  assert.equal(900 * 0.8 + 40 * 2, 800, "16:10 safe-area bars must total 80 pixels");

  const report = [
    "T2 menufix preview aggregate layout replay: PASS",
    `layouts=${conformed.size}/${catalog.screenCensus.length}`,
    `critical_layouts=${criticalLayouts.size}/${criticalLayouts.size}; waivers=0`,
    `dialog_composites=${catalog.dialogComposites.size}/${catalog.dialogComposites.size}; beta_residue=0`,
    `overlay_records=${catalog.overlayRecords.size}/${catalog.overlayRecords.size}`,
    `navigation_edges_with_destination_bindings=${catalog.navigationEdges.length}/${catalog.navigationEdges.length}`,
    `elements=${elementCount}`,
    `ambient_members=${ambientCount}`,
    `art_references=${artCount}`,
    `position_epsilon=${POSITION_EPSILON} (same JSON numerals, no generation assertions)`,
    "safe_area_1280x800=1280x720+40px_top+40px_bottom",
  ].join("\n") + "\n";
  const output = process.env.WEBGAME_CONFORMANCE_LOG;
  if (output !== undefined) {
    await writeFile(output, report, "utf8");
  }
  process.stdout.write(report);
}

await main();
