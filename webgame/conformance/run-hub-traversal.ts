import assert from "node:assert/strict";
import { readFile, writeFile } from "node:fs/promises";
import path from "node:path";

import { HubController } from "../client/hub-controller.js";
import { HUB_NPCS, HUB_PORTALS, type HubNpc, type HubPortal, type HubRegionId } from "../client/hub-data.js";
import { parseInertControls } from "../client/inert-controls.js";
import { parseMenuCatalog } from "../client/menu-catalog.js";
import { ShellController } from "../client/shell-controller.js";
import { GamepadProducer, type GamepadSnapshot } from "../input/gamepad-producer.js";
import { parseFocusModel } from "../input/focus-model.js";
import type { Intent } from "../input/intent.js";

const repository = path.resolve(import.meta.dirname, "..", "..");

function gamepad(axes: readonly number[] = [0, 0, 0, 0], buttonIndex: number | null = null): GamepadSnapshot {
  return {
    connected: true,
    axes,
    buttons: Array.from({ length: 16 }, (_, index) => ({
      pressed: index === buttonIndex,
      value: index === buttonIndex ? 1 : 0,
    })),
  };
}

async function main(): Promise<void> {
  const menuGolden = JSON.parse(
    await readFile(path.join(repository, "tests", "fixtures", "webgame", "menufix-preview-overlay", "menu-goldens.json"), "utf8"),
  ) as unknown;
  const focusGolden = JSON.parse(
    await readFile(path.join(repository, "webgame-contracts", "menu-focus-model.json"), "utf8"),
  ) as unknown;
  const inertGolden = JSON.parse(
    await readFile(path.join(repository, "webgame-contracts", "inert-controls.json"), "utf8"),
  ) as unknown;
  const shell = new ShellController(
    parseMenuCatalog(menuGolden),
    parseFocusModel(focusGolden),
    parseInertControls(inertGolden),
  );
  const lines = [
    "P1 HUB CONTROLLER-ONLY WALKTHROUGH",
    "All locomotion and actions below came from synthetic standard-gamepad snapshots.",
    "Room-entry placement is owned by the exercised G13 transition; no conformance teleport helper is used.",
  ];
  let mapPickerOpened = false;
  const hub = new HubController({
    openPause: () => {
      shell.handle({ kind: "interact", target: "pause", phase: "press" });
    },
    openMapPicker: () => {
      mapPickerOpened = true;
      shell.showLayoutForConformance("map-picker");
    },
  });

  const route = (intent: Intent): void => {
    const shellBefore = shell.snapshot().surface;
    if (shellBefore.kind === "hub-stub") {
      hub.handle(intent);
      return;
    }
    shell.handle(intent);
  };

  shell.showHubForConformance();
  const producer = new GamepadProducer(route, () => {
    const shellSurface = shell.snapshot().surface;
    if (shellSurface.kind !== "hub-stub") {
      return { surface: shell.inputSurface };
    }
    return {
      surface: hub.inputSurface,
      ...(hub.interactTarget === null ? {} : { interactTarget: hub.interactTarget }),
    };
  });

  let analogSamples = 0;
  let simulatedWalkDistance = 0;
  const press = (buttonIndex: number): void => {
    producer.sample(gamepad([0, 0, 0, 0], buttonIndex));
    producer.sample(gamepad());
  };
  const south = (): void => {
    press(0);
  };
  const east = (): void => {
    press(1);
  };
  const start = (): void => {
    press(9);
  };

  const walkTo = (target: Readonly<{ x: number; y: number }>, label: string): void => {
    assert.equal(hub.snapshot().surface.kind, "world", `${label} walk did not start on the hub world surface`);
    const startPoint = hub.snapshot().player;
    for (let step = 0; step < 100; step += 1) {
      const player = hub.snapshot().player;
      const dx = target.x - player.x;
      const dy = target.y - player.y;
      const distance = Math.hypot(dx, dy);
      if (distance <= 0.0001) {
        producer.sample(gamepad());
        simulatedWalkDistance += Math.hypot(target.x - startPoint.x, target.y - startPoint.y);
        lines.push(
          `WALK ${hub.snapshot().region}: (${startPoint.x.toFixed(2)},${startPoint.y.toFixed(2)}) -> ${label} (${target.x.toFixed(2)},${target.y.toFixed(2)})`,
        );
        return;
      }
      const x = dx / distance;
      const y = dy / distance;
      producer.sample(gamepad([x, y, 0, 0]));
      analogSamples += 1;
      hub.advance(Math.min(1000, distance * 10));
    }
    throw new Error(`${label} was not reachable after 100 synthetic analog samples`);
  };

  const finishTransition = (expectedRegion?: HubRegionId): void => {
    const initial = hub.snapshot();
    assert.equal(initial.surface.kind, "transition", "gamepad interaction did not start a G13 transition");
    const replay = initial.transition?.replay;
    assert(replay !== undefined, "active G13 transition lost its conformance replay");
    for (let frame = 0; frame < 100 && hub.snapshot().surface.kind === "transition"; frame += 1) {
      hub.advance(1000);
    }
    assert.notEqual(hub.snapshot().surface.kind, "transition", `${replay.edge} did not finish in bounded virtual time`);
    if (expectedRegion !== undefined) {
      assert.equal(hub.snapshot().region, expectedRegion, `${replay.edge} reached the wrong hub region`);
    }
    lines.push(
      `G13 ${replay.source} --${replay.edge}--> ${replay.destination}; ${replay.durationMilliseconds} ms; phases=${replay.phaseEvents.length}`,
    );
  };

  const talk = (npc: HubNpc): void => {
    walkTo(npc, npc.name);
    assert.equal(hub.interactTarget, npc.id, `${npc.name} was not the unambiguous nearby interaction target`);
    south();
    assert.deepEqual(
      hub.snapshot().surface,
      { kind: "dialogue", npcId: npc.id, pageIndex: 0 },
      `${npc.name} did not open its G8 talk flow from the gamepad interact verb`,
    );
    for (const page of npc.pages) {
      const surface = hub.snapshot().surface;
      assert.equal(surface.kind, "dialogue", `${npc.name} talk flow ended before page ${page.id}`);
      south();
    }
    assert(
      hub.snapshot().completedTalkFlows.includes(npc.id),
      `${npc.name} did not record completion of its complete G8 talk flow`,
    );
    const service = hub.snapshot().surface;
    if (npc.service === "useful-thyngs") {
      assert.equal(service.kind, "service", "Fomentius talk did not reach Useful Thyngs");
      south();
      assert.deepEqual(
        hub.snapshot().lastPurchase,
        {
          service: "useful-thyngs",
          offerId: "useful-thyngs.0",
          itemName: "Health Potion",
          price: 150,
          goldBefore: 698,
          goldAfter: 548,
          quantityBefore: 2,
          quantityAfter: 1,
        },
        "Useful Thyngs gamepad purchase did not deduct the pinned G8 Health Potion price and stock",
      );
      lines.push("PURCHASE Fomentius/Useful Thyngs: Health Potion; 698 - 150 = 548 gold; stock 2 -> 1");
      east();
    } else if (service.kind === "service") {
      east();
    }
    assert.equal(hub.snapshot().surface.kind, "world", `${npc.name} talk/service flow did not return to walking`);
    lines.push(`TALK ${npc.name}: ${npc.pages.map((page) => page.id).join(" -> ")} COMPLETE${npc.service === undefined ? "" : `; ${npc.service} opened and left`}`);
  };

  const takePortal = (portal: HubPortal, expectedRegion: HubRegionId): void => {
    walkTo(portal, portal.name);
    assert.equal(hub.interactTarget, portal.id, `${portal.name} was not the unambiguous nearby interaction target`);
    south();
    finishTransition(expectedRegion);
  };

  start();
  assert.deepEqual(
    shell.snapshot().surface,
    { kind: "layout", layoutId: "pause-menu" },
    "Start did not reuse the frozen P0 pause-menu surface",
  );
  south();
  assert.deepEqual(
    shell.snapshot().surface,
    { kind: "hub-stub", endpointLayoutId: "hub_resumed" },
    "pause-menu resume did not return to the measured resumed hub endpoint",
  );
  lines.push("PAUSE frozen P0 pause-menu opened with Start and resumed with South.");

  for (const npc of HUB_NPCS.filter((candidate) => candidate.region === "courtyard")) {
    talk(npc);
  }

  const portal = (id: string): HubPortal => {
    const matches = HUB_PORTALS.filter((candidate) => candidate.id === id);
    assert.equal(matches.length, 1, `traversal portal lookup ${id} must be unambiguous`);
    const result = matches[0];
    assert(result !== undefined, `traversal portal lookup ${id} lost its witness`);
    return result;
  };

  takePortal(portal("hub.portal.mortuary"), "mortuary");
  for (const npc of HUB_NPCS.filter((candidate) => candidate.region === "mortuary")) {
    talk(npc);
  }
  takePortal(portal("hub.portal.mortuary.return"), "courtyard");

  takePortal(portal("hub.portal.library"), "library");
  for (const npc of HUB_NPCS.filter((candidate) => candidate.region === "library")) {
    talk(npc);
  }
  takePortal(portal("hub.portal.library.return"), "courtyard");

  takePortal(portal("hub.portal.storeroom"), "storeroom");
  lines.push("ROOM StoreRoom: walked in; G8 census has no talk target here.");
  takePortal(portal("hub.portal.storeroom.return"), "courtyard");

  takePortal(portal("hub.portal.office"), "office");
  for (const npc of HUB_NPCS.filter((candidate) => candidate.region === "office")) {
    talk(npc);
  }
  takePortal(portal("hub.portal.office.return"), "courtyard");

  const mapPicker = portal("hub.control.map-picker");
  walkTo(mapPicker, mapPicker.name);
  assert.equal(hub.interactTarget, mapPicker.id, "Courtyard MapPicker was not the nearby control");
  south();
  assert(mapPickerOpened, "Courtyard run entry did not invoke the landed P0 MapPicker UI");
  assert.deepEqual(
    shell.snapshot().surface,
    { kind: "layout", layoutId: "map-picker" },
    "run entry substituted a portal actor for the landed MapPicker UI",
  );
  lines.push("RUN ENTRY: Courtyard interact opened the rendered, owner-descoped map-picker.");
  const beforeMapConfirm = structuredClone(shell.snapshot());
  south();
  assert.deepEqual(shell.snapshot(), beforeMapConfirm, "owner-descoped MapPicker confirmation mutated shell state");
  assert.equal(hub.snapshot().transition, null, "owner-descoped MapPicker confirmation started a session edge");
  lines.push("MAP PICKER INERT: controller confirmation caused no navigation or state mutation.");

  assert.deepEqual(
    hub.snapshot().completedTalkFlows,
    HUB_NPCS.map((npc) => npc.id).sort(),
    "controller-only walkthrough did not complete every G8 NPC/Painting talk flow",
  );
  assert.equal(hub.snapshot().completedTalkFlows.length, 20, "controller-only walkthrough did not cover all 20 talk targets");
  assert.equal(hub.snapshot().gold, 548, "controller-only walkthrough did not retain the exact post-purchase gold ledger");
  assert.equal(hub.snapshot().stock["useful-thyngs.0"], 1, "controller-only walkthrough did not retain the exact post-purchase stock ledger");
  assert.equal(hub.snapshot().inventory["7001:0:0:-1"], 1, "controller-only walkthrough did not retain the purchased Health Potion");
  assert(analogSamples > 0, "controller-only walkthrough did not exercise the analog movement producer");
  lines.push(
    `PASS: 20/20 talk targets; 1 pinned purchase; map picker inert; ${analogSamples} analog samples; ${simulatedWalkDistance.toFixed(2)} world units walked.`,
  );

  const report = `${lines.join("\n")}\n`;
  const output = process.env.WEBGAME_HUB_TRAVERSAL_LOG;
  if (output !== undefined) {
    await writeFile(output, report, "utf8");
  }
  process.stdout.write(report);
}

await main();
