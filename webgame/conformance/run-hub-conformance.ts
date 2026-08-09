import assert from "node:assert/strict";

import economyGoldenJson from "../../tests/fixtures/webgame/hub-economy-goldens.json" with { type: "json" };
import { G12_LAYER_ORDER, HUB_SCENE_GOLDEN } from "../client/hub-contracts.js";
import {
  HAGATHA_OFFERS,
  SHLORIO_OFFERS,
  USEFUL_THYNGS_OFFERS,
} from "../client/hub-data.js";
import {
  HUB_BASE_PLAYER_POSITION,
  assembleHubScene,
  buildHubScenePlan,
} from "../client/hub-scene.js";
import { ManifestAssets } from "../client/manifest-assets.js";
import { hubConformanceManifest } from "./hub-conformance-assets.js";

const assembly = assembleHubScene();
assert.deepEqual(
  assembly.layerOrder,
  G12_LAYER_ORDER,
  "T2 hub replay changed the exact G12 physical layer order",
);
assert.equal(assembly.draws.length, 1319, "T2 hub replay did not examine all 1,319 G12 draws");
for (const [index, actual] of assembly.draws.entries()) {
  const expected = HUB_SCENE_GOLDEN.draws[index];
  assert(expected !== undefined, `T2 hub replay lost G12 draw ${index}`);
  assert.equal(actual.drawOrder, expected.draw_order, `T2 hub draw ${index} changed draw order`);
  assert.equal(actual.spriteId, expected.sprite.id, `T2 hub draw ${index} changed sprite id`);
  assert.equal(actual.layer, expected.layer, `T2 hub draw ${index} changed physical layer`);
  assert.equal(actual.semanticRole, expected.semantic_role, `T2 hub draw ${index} changed semantic role`);
  assert.equal(actual.nativePhase, expected.native_phase, `T2 hub draw ${index} changed native phase`);
  assert.equal(actual.drawKind, expected.draw_kind, `T2 hub draw ${index} changed draw kind`);
  assert.deepEqual(actual.worldTransform, expected.world_transform, `T2 hub draw ${index} changed native transform`);
  assert.deepEqual(actual.tint, expected.tint, `T2 hub draw ${index} changed native tint`);
  assert.deepEqual(actual.blend, expected.blend, `T2 hub draw ${index} changed native blend state`);
  assert.deepEqual(
    actual.resolvedScreenRect,
    expected.resolved_screen_rect,
    `T2 hub draw ${index} changed resolved screen rectangle`,
  );
  assert.deepEqual(actual.sortKey, expected.sort_key, `T2 hub draw ${index} changed sort key`);
  assert.equal(actual.visible, expected.visible, `T2 hub draw ${index} changed native visibility`);
}

const assets = new ManifestAssets(hubConformanceManifest());
assets.assertHubSceneAssets(HUB_SCENE_GOLDEN.draws);
const renderedPlan = buildHubScenePlan(assets, {
  player: HUB_BASE_PLAYER_POSITION,
  heading: 180,
  moving: false,
  presentationMilliseconds: 0,
});
assert.equal(renderedPlan.commands.length, 1319, "T2 rendered replay did not examine all 1,319 G12 draws");
for (const [index, command] of renderedPlan.commands.entries()) {
  const expected = HUB_SCENE_GOLDEN.draws[index];
  assert(expected !== undefined, `T2 rendered replay lost G12 draw ${index}`);
  for (const [coordinate, expectedValue] of expected.resolved_screen_rect.entries()) {
    const delta = Math.abs((command.rect[coordinate] ?? Number.NaN) - expectedValue);
    assert(
      delta <= HUB_SCENE_GOLDEN.epsilon.screen_pixels,
      `T2 hub draw ${index} screen coordinate ${coordinate} exceeded G12's declared pixel tolerance`,
    );
  }
}

const freshCandidates = economyGoldenJson.trader_captures.filter(
  (captureValue) => captureValue.progression_state.id === "fresh",
);
assert.equal(freshCandidates.length, 1, "T2 economy replay refuses ambiguous fresh trader candidates");
const fresh = freshCandidates[0];
assert(fresh !== undefined, "T2 economy replay did not reach the fresh G8 trader witness");
const stripDisplay = (offer: typeof USEFUL_THYNGS_OFFERS[number]): Record<string, number> => ({
  type_id: offer.type_id,
  variant_id: offer.variant_id ?? 0,
  recipe_uid: offer.recipe_uid ?? 0,
  quantity: offer.quantity,
  price: offer.price,
});
assert.deepEqual(
  USEFUL_THYNGS_OFFERS.map(stripDisplay),
  fresh.fomentius.offers,
  "T2 economy replay changed Fomentius pinned stock or prices",
);
assert.deepEqual(
  HAGATHA_OFFERS.map((offer) => ({
    price: offer.price,
    quantity: offer.quantity,
    selector: offer.selector,
    type_id: offer.type_id,
  })),
  fresh.hagatha.offers,
  "T2 economy replay changed Hagatha pinned selectors or prices",
);
const firstRoll = fresh.shlorio_dowsing_rolls[0];
assert(firstRoll !== undefined, "T2 economy replay did not reach Shlorio's pinned first roll");
assert.deepEqual(
  SHLORIO_OFFERS.map((offer) => ({
    price: offer.price,
    recipe_uid: offer.recipe_uid,
    type_id: offer.type_id,
    variant_id: offer.variant_id,
  })),
  firstRoll.offers,
  "T2 economy replay changed Shlorio's pinned first-roll stock or prices",
);

process.stdout.write([
  "T2 P1 HUB CONFORMANCE: PASS",
  `draws=${assembly.draws.length}/1319`,
  `layers=${assembly.layerOrder.join(" -> ")}`,
  `manifest_draws_checked=${HUB_SCENE_GOLDEN.draws.length}`,
  `rendered_rects_checked=${renderedPlan.commands.length}; tolerance=${HUB_SCENE_GOLDEN.epsilon.screen_pixels}px`,
  `useful_thyngs_offers=${USEFUL_THYNGS_OFFERS.length}; stock=${fresh.fomentius.stock_count}`,
  `hagatha_offers=${HAGATHA_OFFERS.length}`,
  `shlorio_pinned_offers=${SHLORIO_OFFERS.length}; regeneration=OUT_OF_SCOPE`,
  "position_tolerance=0 (same landed JSON numerals)",
  "",
].join("\n"));
