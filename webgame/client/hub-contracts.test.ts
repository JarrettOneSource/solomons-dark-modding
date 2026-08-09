import { describe, expect, it } from "vitest";

import economyGoldenJson from "../../tests/fixtures/webgame/hub-economy-goldens.json" with { type: "json" };
import sceneGoldenJson from "../../tests/fixtures/webgame/scene-composition-goldens.json" with { type: "json" };
import sessionGoldenJson from "../../tests/fixtures/webgame/session-flow-goldens.json" with { type: "json" };
import {
  facing24,
  parseHubEconomyGolden,
  parseHubSceneGolden,
  parseSessionFlowGolden,
  wizardPresentation,
} from "./hub-contracts.js";

type MutableSceneFixture = {
  captures: Array<{
    header: { validation: { draw_count: number } };
  }>;
};

type MutableEconomyFixture = {
  trader_captures: unknown[];
};

describe("landed P1 hub contracts", () => {
  it("parses the canonical G12 Courtyard draw list without a copied fixture", () => {
    const scene = parseHubSceneGolden(sceneGoldenJson);
    expect(scene.label).toBe("hub_camera_1000_375_final");
    expect(scene.draws).toHaveLength(1319);
    expect(scene.draws[0]?.sprite.id).toBe("native.framebuffer-clear");
    expect(scene.draws[95]?.sprite.id).toBe("Clothes.880");
  });

  it("rejects a changed G12 draw-count claim by name", () => {
    const mutant = structuredClone(sceneGoldenJson) as unknown as MutableSceneFixture;
    const capture = mutant.captures[0];
    expect(capture).toBeDefined();
    if (capture === undefined) {
      throw new Error("mutation fixture lost the canonical G12 capture witness");
    }
    capture.header.validation.draw_count = 1318;
    expect(() => parseHubSceneGolden(mutant)).toThrow(
      "G12 canonical Courtyard draw list no longer contains exactly 1,319 draws",
    );
  });

  it("parses exact G8 regions and pinned fresh stock", () => {
    const economy = parseHubEconomyGolden(economyGoldenJson);
    expect(economy.regions.map((region) => region.name)).toEqual([
      "Courtyard", "Mortuary", "Library", "StoreRoom", "Office",
    ]);
    expect(economy.fomentius.map((offer) => [offer.type_id, offer.variant_id, offer.price, offer.quantity]))
      .toEqual([
        [7001, 0, 150, 2],
        [7001, 1, 75, 3],
        [7001, 5, 200, 2],
        [7012, 0, 300, 3],
        [7008, 0, 50, 1],
        [7001, 3, 100, 1],
      ]);
    expect(economy.hagatha).toHaveLength(27);
    expect(economy.dowsingFee).toBe(650);
  });

  it("refuses ambiguous duplicate G8 fresh captures", () => {
    const mutant = structuredClone(economyGoldenJson) as unknown as MutableEconomyFixture;
    const capture = mutant.trader_captures[0];
    expect(capture).toBeDefined();
    if (capture === undefined) {
      throw new Error("mutation fixture lost the fresh G8 trader witness");
    }
    mutant.trader_captures.push(structuredClone(capture));
    expect(() => parseHubEconomyGolden(mutant)).toThrow(
      "G8 pinned inventory cannot choose unambiguously between fresh trader captures",
    );
  });

  it("parses all twelve G13 states and twenty-three edges", () => {
    const flow = parseSessionFlowGolden(sessionGoldenJson);
    expect(flow.states).toHaveLength(12);
    expect(flow.edges).toHaveLength(23);
    expect(flow.edges.some((edge) => edge.edge === "start_run" && edge.destination === "loading.boneyard"))
      .toBe(true);
  });

  it("rejects a shortened G13 edge graph by claim", () => {
    const mutant = structuredClone(sessionGoldenJson);
    mutant.transition_graph.edges.pop();
    expect(() => parseSessionFlowGolden(mutant)).toThrow(
      "G13 session graph no longer contains exactly twenty-three legal edges",
    );
  });

  it("selects G4 wizard idle/walk presentation with the native 24-facing formula", () => {
    expect(facing24(0)).toBe(0);
    expect(facing24(90.0000076)).toBe(6);
    expect(facing24(180)).toBe(12);
    expect(facing24(359)).toBe(0);
    expect(wizardPresentation(90, true, 100).clothesSpriteIds.slice(0, 2))
      .toEqual(["Clothes.898", "Clothes.1258"]);
    expect(wizardPresentation(180, false, 0)).toMatchObject({
      locomotion: "idle",
      facing: 12,
      auraSpriteId: "BadGuys.255",
    });
  });
});
