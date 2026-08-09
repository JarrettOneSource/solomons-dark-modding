import { describe, expect, it } from "vitest";

import { HUB_NPCS } from "./hub-data.js";
import { HubController } from "./hub-controller.js";

function controller(): HubController {
  return new HubController({ openPause: () => undefined, openMapPicker: () => undefined });
}

describe("P1 hub controller", () => {
  it("moves shell state from both G14 vector and target intents at the provisional G1 speed", () => {
    const hub = controller();
    const before = hub.snapshot().player;
    hub.handle({
      kind: "move",
      phase: "start",
      move: { type: "unit_vector", vector: { x: 1, y: 0 } },
    });
    hub.advance(500);
    expect(hub.snapshot().player.x - before.x).toBeCloseTo(50, 8);
    expect(hub.snapshot().player.heading).toBeCloseTo(90, 8);
    hub.handle({
      kind: "move",
      phase: "start",
      move: { type: "world_target", point: { x: before.x, y: before.y } },
    });
    hub.advance(500);
    expect(hub.snapshot().player.x).toBeCloseTo(before.x, 8);
  });

  it("drives every G8 NPC and Painting talk flow to completion", () => {
    const hub = controller();
    for (const npc of HUB_NPCS) {
      hub.showNpcForConformance(npc.id);
      for (let index = 0; index < npc.pages.length; index += 1) {
        hub.handle({ kind: "menu_nav", command: "confirm", phase: "press" });
      }
      if (hub.snapshot().surface.kind === "service") {
        hub.handle({ kind: "menu_nav", command: "back", phase: "press" });
      }
    }
    expect(hub.snapshot().completedTalkFlows).toEqual(HUB_NPCS.map((npc) => npc.id).sort());
    expect(hub.snapshot().completedTalkFlows).toHaveLength(20);
  });

  it("deducts the exact pinned Useful Thyngs price and transfers one item", () => {
    const hub = controller();
    hub.showServiceForConformance("hub.npc.fomentius");
    hub.handle({ kind: "menu_nav", command: "confirm", phase: "press" });
    expect(hub.snapshot().lastPurchase).toEqual({
      service: "useful-thyngs",
      offerId: "useful-thyngs.0",
      itemName: "Health Potion",
      price: 150,
      goldBefore: 698,
      goldAfter: 548,
      quantityBefore: 2,
      quantityAfter: 1,
    });
    expect(hub.snapshot().inventory["7001:0:0:-1"]).toBe(1);
  });

  it("enters the visible run shell through G13 and returns through scripted reset", () => {
    const hub = controller();
    hub.beginRunEntry();
    hub.advance(1000);
    expect(hub.snapshot().sessionState).toBe("gameplay.courtyard");
    hub.advance(20);
    expect(hub.snapshot().sessionState).toBe("loading.boneyard");
    hub.advance(250);
    expect(hub.snapshot()).toMatchObject({
      sessionState: "gameplay.arena",
      surface: { kind: "run-shell" },
    });
    expect(hub.snapshot().completedSessionEdges).toEqual([
      "gameplay.courtyard --start_run--> loading.boneyard",
      "loading.boneyard --arena_materialized--> gameplay.arena",
    ]);
    hub.handle({ kind: "interact", target: "run-shell.return", phase: "press" });
    hub.advance(1000);
    hub.advance(430);
    expect(hub.snapshot()).toMatchObject({
      region: "courtyard",
      sessionState: "gameplay.courtyard",
      surface: { kind: "world" },
    });
    expect(hub.snapshot().completedSessionEdges.at(-1)).toBe(
      "gameplay.arena --scripted_terminal_reset--> gameplay.courtyard",
    );
  });
});
