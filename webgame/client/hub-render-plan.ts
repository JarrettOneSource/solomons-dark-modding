import { HUB_ECONOMY_GOLDEN } from "./hub-contracts.js";
import type { HubSnapshot } from "./hub-controller.js";
import { HUB_NPCS, offersForService, type HubServiceId } from "./hub-data.js";
import { buildHubScenePlan } from "./hub-scene.js";
import type { ManifestAssets } from "./manifest-assets.js";
import type { MenuLayout, NativeRect } from "./menu-catalog.js";
import {
  buildRenderPlan,
  G12_LAYER_ORDER,
  type AtlasTextDraw,
  type DrawCommand,
  type RenderPlan,
  type SolidDraw,
} from "./render-plan.js";

export function buildHubLayoutRenderPlan(
  assets: ManifestAssets,
  snapshot: HubSnapshot,
  layout: MenuLayout,
  focused: Readonly<{ id: string; rect: NativeRect }> | null,
  showFocus: boolean,
): RenderPlan {
  const menu = buildRenderPlan(layout, assets, focused, showFocus);
  const scene = buildHubScenePlan(
    assets,
    {
      player: snapshot.player,
      heading: snapshot.player.heading,
      moving: snapshot.player.moving,
      presentationMilliseconds: snapshot.presentationMilliseconds,
    },
    menu.commands,
    `hub.${snapshot.region}.${layout.id}`,
  );
  return {
    ...scene,
    layoutId: layout.id,
    elements: menu.elements,
  };
}

const BODY_FONT = "Fonts.216-307";
const TITLE_FONT = "Fonts.308-349";

function solid(
  id: string,
  order: number,
  rect: readonly [number, number, number, number],
  color: readonly [number, number, number, number],
  bottom = color,
): SolidDraw {
  return {
    kind: "solid",
    elementId: id,
    layer: "screen-overlay",
    drawOrder: order,
    rect,
    unclippedRect: rect,
    colorTop: color,
    colorBottom: bottom,
  };
}

function text(
  id: string,
  order: number,
  value: string,
  rect: readonly [number, number, number, number],
  fontId = BODY_FONT,
): AtlasTextDraw {
  return {
    kind: "atlas-text",
    elementId: id,
    layer: "screen-overlay",
    drawOrder: order,
    rect,
    unclippedRect: rect,
    fontId,
    text: value.toUpperCase(),
    tint: fontId === "Fonts.93-184" ? [1, 1, 1, 1] : [0.86, 0.74, 0.42, 1],
  };
}

function wrap(value: string, maxCharacters: number): readonly string[] {
  const words = value.toUpperCase().split(/\s+/);
  const lines: string[] = [];
  let line = "";
  for (const word of words) {
    if (line.length === 0) {
      line = word;
    } else if (`${line} ${word}`.length <= maxCharacters) {
      line = `${line} ${word}`;
    } else {
      lines.push(line);
      line = word;
    }
  }
  if (line.length > 0) {
    lines.push(line);
  }
  return lines;
}

function worldOverlay(snapshot: HubSnapshot): DrawCommand[] {
  const commands: DrawCommand[] = [
    solid("hub.hud.top", 2000, [0, 0, 1600, 72], [0.015, 0.02, 0.03, 0.88]),
    text("hub.hud.region", 2001, snapshot.region, [32, 18, 285, 50], TITLE_FONT),
    text("hub.hud.gold", 2002, `GOLD ${snapshot.gold}`, [1300, 20, 1568, 48]),
  ];
  if (snapshot.region !== "courtyard") {
    commands.push(
      solid("hub.region.private.tint", 1990, [0, 72, 1600, 900], [0.015, 0.01, 0.035, 0.24]),
    );
  }
  const target = snapshot.nearestTargetId;
  if (target !== null) {
    const npc = HUB_NPCS.find((candidate) => candidate.id === target);
    const label = npc?.name ?? (
      target === "hub.control.map-picker"
        ? "COURTYARD MAPPICKER"
        : target.includes("return")
          ? "RETURN TO COURTYARD"
          : target.split(".").at(-1) ?? target
    );
    commands.push(
      solid("hub.hud.interact.back", 2003, [500, 808, 1100, 872], [0.02, 0.025, 0.035, 0.9]),
      text("hub.hud.interact", 2004, `PRESS A - ${label}`, [535, 826, 1065, 856]),
    );
  }
  return commands;
}

function dialogueOverlay(snapshot: HubSnapshot): DrawCommand[] {
  if (snapshot.surface.kind !== "dialogue") {
    return [];
  }
  const surface = snapshot.surface;
  const npc = HUB_NPCS.find((candidate) => candidate.id === surface.npcId);
  if (npc === undefined) {
    throw new Error(`hub dialogue cannot render missing NPC ${surface.npcId}`);
  }
  const page = npc.pages[surface.pageIndex];
  if (page === undefined) {
    throw new Error(`hub dialogue ${npc.id} lost page ${surface.pageIndex}`);
  }
  const commands: DrawCommand[] = [
    solid("hub.dialogue.scrim", 2100, [0, 0, 1600, 900], [0, 0, 0, 0.3]),
    solid(
      "hub.dialogue.panel",
      2101,
      [170, 600, 1430, 860],
      [0.04, 0.035, 0.055, 0.97],
      [0.008, 0.006, 0.014, 0.98],
    ),
    solid("hub.dialogue.rule", 2102, [170, 600, 1430, 606], [0.78, 0.58, 0.2, 1]),
    text("hub.dialogue.name", 2103, npc.name, [220, 628, 620, 668], TITLE_FONT),
    text("hub.dialogue.id", 2104, page.id, [1040, 634, 1380, 662]),
  ];
  for (const [index, line] of wrap(page.text, 64).slice(0, 3).entries()) {
    commands.push(text(
      `hub.dialogue.line.${index}`,
      2110 + index,
      line,
      [220, 700 + index * 36, 1380, 728 + index * 36],
    ));
  }
  commands.push(text(
    "hub.dialogue.hint",
    2120,
    surface.pageIndex + 1 < npc.pages.length || npc.service !== undefined
      ? "A CONTINUE   B CLOSE"
      : "A FINISH   B CLOSE",
    [950, 816, 1380, 842],
  ));
  return commands;
}

function serviceTitle(service: HubServiceId): string {
  const titles: Readonly<Record<HubServiceId, string>> = {
    "useful-thyngs": "USEFUL THYNGS FOMENTIUS",
    "perk-shop": "HAGATHA CHARMS AND CURSES",
    boast: "ANNALS OF THE COLLEGE",
    inventory: "LUTHACUS PRIVATE STORAGE",
    spells: "THE TEACHER SPELLS",
    books: "THE LIBRARIAN BOOKS",
    dowsing: "SHLORIO PINNED DOWSING STOCK",
  };
  return titles[service];
}

function emptyServiceDetail(service: HubServiceId): string {
  const details: Partial<Record<HubServiceId, string>> = {
    boast: "YOUR CURRENT RUN DEEDS ARE READY TO BE RECORDED.",
    inventory: "PARTICIPANT PRIVATE STORAGE IS EMPTY IN THIS P1 SESSION.",
    spells: "SPELL CATALOG CONTENT IS DISPLAY ONLY IN THE P1 HUB.",
    books: "BOOK CATALOG CONTENT IS DISPLAY ONLY IN THE P1 HUB.",
  };
  return details[service] ?? "";
}

function serviceOverlay(snapshot: HubSnapshot): DrawCommand[] {
  if (snapshot.surface.kind !== "service") {
    return [];
  }
  const surface = snapshot.surface;
  const offers = offersForService(surface.service);
  const doneIndex = offers.length;
  const windowStart = offers.length <= 8
    ? 0
    : Math.max(0, Math.min(offers.length - 8, surface.focusIndex - 4));
  const visible = offers.slice(windowStart, windowStart + 8);
  const commands: DrawCommand[] = [
    solid("hub.service.scrim", 2200, [0, 0, 1600, 900], [0, 0, 0, 0.76]),
    solid(
      "hub.service.panel",
      2201,
      [230, 90, 1370, 840],
      [0.035, 0.03, 0.05, 0.99],
      [0.006, 0.005, 0.012, 1],
    ),
    solid("hub.service.rule", 2202, [230, 90, 1370, 98], [0.78, 0.58, 0.2, 1]),
    text("hub.service.title", 2203, serviceTitle(surface.service), [310, 126, 1120, 170], TITLE_FONT),
    text("hub.service.gold", 2204, `GOLD ${snapshot.gold}`, [1140, 134, 1320, 164]),
  ];
  if (surface.service === "dowsing") {
    commands.push(text(
      "hub.service.dowsing.note",
      2205,
      `PINNED FIRST INVENTORY - RECORDED FEE ${HUB_ECONOMY_GOLDEN.dowsingFee} - NO REGENERATION`,
      [310, 190, 1290, 218],
    ));
  }
  if (offers.length === 0) {
    commands.push(text(
      "hub.service.detail",
      2210,
      emptyServiceDetail(surface.service),
      [340, 300, 1260, 336],
    ));
  }
  for (const [visibleIndex, offer] of visible.entries()) {
    const index = windowStart + visibleIndex;
    const y = 245 + visibleIndex * 62;
    if (surface.focusIndex === index) {
      commands.push(solid(
        `hub.service.offer.${index}.focus`,
        2210 + visibleIndex * 3,
        [300, y - 8, 1300, y + 42],
        [0.34, 0.23, 0.07, 0.9],
      ));
    }
    commands.push(
      text(`hub.service.offer.${index}.name`, 2211 + visibleIndex * 3, offer.name, [330, y, 930, y + 28]),
      text(
        `hub.service.offer.${index}.price`,
        2212 + visibleIndex * 3,
        `${offer.price} GOLD   STOCK ${snapshot.stock[offer.id] ?? 0}`,
        [970, y, 1270, y + 28],
      ),
    );
  }
  const doneY = offers.length === 0 ? 650 : 755;
  if (surface.focusIndex === doneIndex) {
    commands.push(solid("hub.service.done.focus", 2290, [620, doneY - 8, 980, doneY + 40], [0.34, 0.23, 0.07, 0.9]));
  }
  commands.push(text("hub.service.done", 2291, "DONE", [690, doneY, 910, doneY + 28], TITLE_FONT));
  if (surface.status.length > 0) {
    commands.push(text("hub.service.status", 2292, surface.status, [400, 810, 1200, 836]));
  }
  return commands;
}

function transitionOverlay(snapshot: HubSnapshot): DrawCommand[] {
  const transition = snapshot.transition;
  if (transition === null) {
    return [];
  }
  return [
    solid("hub.transition.fade", 2400, [0, 0, 1600, 900], [0, 0, 0, transition.fadeAlpha]),
    text("hub.transition.phase", 2401, transition.phase, [500, 820, 1100, 848]),
  ];
}

function runShellPlan(): RenderPlan {
  const commands: DrawCommand[] = [
    solid(
      "hub.run-shell.background",
      1,
      [0, 0, 1600, 900],
      [0.035, 0.045, 0.075, 1],
      [0.005, 0.008, 0.018, 1],
    ),
    text("hub.run-shell.title", 2, "RUN SHELL READY", [480, 270, 1120, 330], TITLE_FONT),
    text(
      "hub.run-shell.message",
      3,
      "THE RUN ITSELF IS P2 AND P3 TERRITORY",
      [400, 405, 1200, 440],
    ),
    text(
      "hub.run-shell.detail",
      4,
      "G13 SOLO MATERIALIZATION BARRIER RELEASED - INPUT UNSEALED",
      [320, 485, 1280, 518],
    ),
    text("hub.run-shell.return", 5, "PRESS A TO RETURN TO THE COURTYARD", [500, 610, 1100, 642]),
  ];
  return {
    layoutId: "hub.run-shell",
    nativeViewport: [1600, 900],
    layerOrder: G12_LAYER_ORDER,
    clearColor: [0, 0, 0, 1],
    elements: [],
    commands,
  };
}

export function buildHubRenderPlan(assets: ManifestAssets, snapshot: HubSnapshot): RenderPlan {
  if (snapshot.surface.kind === "run-shell") {
    return runShellPlan();
  }
  let overlay: DrawCommand[];
  if (snapshot.surface.kind === "dialogue") {
    overlay = dialogueOverlay(snapshot);
  } else if (snapshot.surface.kind === "service") {
    overlay = serviceOverlay(snapshot);
  } else if (snapshot.surface.kind === "transition") {
    overlay = transitionOverlay(snapshot);
  } else {
    overlay = worldOverlay(snapshot);
  }
  return buildHubScenePlan(
    assets,
    {
      player: snapshot.player,
      heading: snapshot.player.heading,
      moving: snapshot.player.moving,
      presentationMilliseconds: snapshot.presentationMilliseconds,
    },
    overlay,
    `hub.${snapshot.region}.${snapshot.surface.kind}`,
  );
}
