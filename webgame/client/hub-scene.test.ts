import { describe, expect, it } from "vitest";

import { hubConformanceManifest } from "../conformance/hub-conformance-assets.js";
import { HUB_SCENE_GOLDEN } from "./hub-contracts.js";
import { HUB_BASE_PLAYER_POSITION, assembleHubScene, buildHubScenePlan } from "./hub-scene.js";
import { ManifestAssets } from "./manifest-assets.js";

describe("G12 P1 hub scene assembly", () => {
  it("replays every sprite id, transform, layer, and order exactly", () => {
    const assembly = assembleHubScene();
    expect(assembly.draws).toHaveLength(1319);
    expect(assembly.draws).toEqual(HUB_SCENE_GOLDEN.draws.map((draw) => ({
      drawOrder: draw.draw_order,
      spriteId: draw.sprite.id,
      layer: draw.layer,
      semanticRole: draw.semantic_role,
      nativePhase: draw.native_phase,
      drawKind: draw.draw_kind,
      worldTransform: draw.world_transform,
      tint: draw.tint,
      blend: draw.blend,
      resolvedScreenRect: draw.resolved_screen_rect,
      sortKey: draw.sort_key,
      visible: draw.visible,
    })));
  });

  it("builds the exact default plan through manifest-only asset resolution", () => {
    const assets = new ManifestAssets(hubConformanceManifest());
    const plan = buildHubScenePlan(assets, {
      player: HUB_BASE_PLAYER_POSITION,
      heading: 180,
      moving: false,
      presentationMilliseconds: 0,
    });
    expect(plan.commands).toHaveLength(1319);
    expect(plan.layerOrder).toEqual([
      "framebuffer-clear", "scene-underlay", "world-sorted", "scene-overdraw", "screen-overlay",
    ]);
    expect(plan.commands[95]).toMatchObject({
      kind: "scene-sprite",
      sourceSpriteId: "Clothes.880",
      layer: "world-sorted",
      drawOrder: 95,
    });
    for (const [index, command] of plan.commands.entries()) {
      const expected = HUB_SCENE_GOLDEN.draws[index];
      expect(expected, `G12 default projection lost draw ${index}`).toBeDefined();
      if (expected === undefined) {
        continue;
      }
      const actual = command.rect;
      for (const [coordinate, expectedValue] of expected.resolved_screen_rect.entries()) {
        expect(
          Math.abs((actual[coordinate] ?? Number.NaN) - expectedValue),
          `G12 draw ${index} screen coordinate ${coordinate} exceeded its declared pixel tolerance`,
        ).toBeLessThanOrEqual(HUB_SCENE_GOLDEN.epsilon.screen_pixels);
      }
    }
  });

  it("hard-fails with the exact missing hub asset id", () => {
    const source = hubConformanceManifest();
    const entries = { ...source.entries };
    delete entries["College.63"];
    const manifest = { ...source, entries };
    const assets = new ManifestAssets(manifest);
    expect(() => {
      assets.assertHubSceneAssets(HUB_SCENE_GOLDEN.draws);
    }).toThrow(
      "assetpack manifest is missing required asset id College.63",
    );
  });
});
