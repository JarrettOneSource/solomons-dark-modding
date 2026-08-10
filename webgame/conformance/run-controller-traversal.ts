import assert from "node:assert/strict";
import { readFile, writeFile } from "node:fs/promises";
import path from "node:path";

import { parseInertControls } from "../client/inert-controls.js";
import { parseMenuCatalog, type MenuCatalog } from "../client/menu-catalog.js";
import {
  CRITICAL_MENU_EDGE_IDS,
  ShellController,
  type CriticalMenuEdgeId,
} from "../client/shell-controller.js";
import { GamepadProducer, type GamepadSnapshot } from "../input/gamepad-producer.js";
import { parseFocusModel } from "../input/focus-model.js";

const repository = path.resolve(import.meta.dirname, "..", "..");

const buttonForCommand: Readonly<Record<string, number>> = {
  confirm: 0,
  back: 1,
  previous: 4,
  next: 5,
  start: 9,
  up: 12,
  down: 13,
  left: 14,
  right: 15,
};

function snapshot(buttonIndex: number | null): GamepadSnapshot {
  return {
    connected: true,
    axes: [0, 0, 0, 0],
    buttons: Array.from({ length: 16 }, (_, index) => ({
      pressed: index === buttonIndex,
      value: index === buttonIndex ? 1 : 0,
    })),
  };
}

function surfaceName(controller: ShellController): string {
  const surface = controller.snapshot().surface;
  if (surface.kind === "hub-stub") {
    return "hub";
  }
  if (surface.kind === "dialog-composite") {
    return surface.compositeId;
  }
  return controllerLayoutSurface(controller, surface.layoutId);
}

function controllerLayoutSurface(controller: ShellController, layoutId: string): string {
  const snapshot = controller.snapshot();
  if (snapshot.surface.kind !== "layout" || snapshot.surface.layoutId !== layoutId) {
    throw new Error(`surface mapper expected active layout ${layoutId}`);
  }
  const aliases: Readonly<Record<string, string>> = {
    "control-scheme-picker": "control_scheme_picker",
    "create-element": "create_element",
    "create-discipline": "create_discipline",
    "pause-menu": "pause_menu",
    "beta-notice": "beta_notice",
    "main-menu-root": "main_menu",
    "profile-save-select": "profile_save_select",
  };
  return aliases[layoutId] ?? layoutId.replaceAll("-", "_");
}

function destinationSurface(catalog: MenuCatalog, edgeId: CriticalMenuEdgeId): string {
  const edge = catalog.navigationEdges.find((candidate) => candidate.id === edgeId);
  assert(edge !== undefined, `critical traversal references missing graph edge ${edgeId}`);
  assert.equal(edge.destinationType, "layout", `${edgeId} must bind a layout destination`);
  assert(edge.destinationLayoutId !== null, `${edgeId} must carry destination_layout_fixture`);
  return edge.destination;
}

async function main(): Promise<void> {
  const menuGolden = JSON.parse(await readFile(path.join(
    repository,
    "tests",
    "fixtures",
    "webgame",
    "menufix-preview-overlay",
    "menu-goldens.json",
  ), "utf8")) as unknown;
  const focusGolden = JSON.parse(await readFile(
    path.join(repository, "webgame-contracts", "menu-focus-model.json"),
    "utf8",
  )) as unknown;
  const inertGolden = JSON.parse(await readFile(
    path.join(repository, "webgame-contracts", "inert-controls.json"),
    "utf8",
  )) as unknown;
  const catalog = parseMenuCatalog(menuGolden);
  const inert = parseInertControls(inertGolden);
  let now = 0;
  const controller = new ShellController(
    catalog,
    parseFocusModel(focusGolden),
    inert,
    { clock: () => now },
  );
  const producer = new GamepadProducer((intent) => {
    controller.handle(intent);
  }, () => ({ surface: controller.inputSurface }));
  const visited = new Set<CriticalMenuEdgeId>();
  const lines = [
    "SHELLFIX CONTROLLER-ONLY CRITICAL TRAVERSAL",
    "Synthetic standard-gamepad snapshots only; setup resets never count as graph edges.",
  ];

  const press = (command: keyof typeof buttonForCommand): void => {
    const index = buttonForCommand[command];
    assert(index !== undefined, `synthetic gamepad command ${command} has a button mapping`);
    producer.sample(snapshot(index));
    producer.sample(snapshot(null));
  };
  const presses = (...commands: (keyof typeof buttonForCommand)[]): void => {
    for (const command of commands) {
      press(command);
    }
  };
  const record = (
    edgeId: CriticalMenuEdgeId,
    commands: readonly (keyof typeof buttonForCommand)[],
  ): void => {
    const edge = catalog.navigationEdges.find((candidate) => candidate.id === edgeId);
    assert(edge !== undefined, `traversal references unknown corrected edge ${edgeId}`);
    assert(!visited.has(edgeId), `critical edge ${edgeId} was recorded twice`);
    const before = surfaceName(controller);
    assert.equal(before, edge.source, `${edgeId} started from ${before}, expected ${edge.source}`);
    const focusBefore = controller.snapshot().focusId;
    presses(...commands);
    const after = surfaceName(controller);
    assert.equal(after, destinationSurface(catalog, edgeId), `${edgeId} reached the wrong destination`);
    visited.add(edgeId);
    lines.push(
      `${String(visited.size).padStart(2, "0")}. ${edgeId}: ${before} --[${commands.join("+")}; focus=${focusBefore ?? "none"}]--> ${after}`,
    );
  };

  controller.showMatchLoading();
  controller.completeBoot();
  now = 2001;
  record("beta_notice_first_boot_to_control_scheme_picker", ["confirm"]);
  record("control_scheme_picker_to_create", ["confirm"]);
  record("create_element_to_discipline", ["confirm"]);
  record("create_discipline_to_hub", ["confirm"]);
  record("hub_to_pause", ["start"]);
  record("pause_to_hub_resume", ["confirm"]);

  press("start");
  record("pause_to_beta_notice", ["down", "down", "confirm"]);
  record("beta_notice_to_main", ["confirm"]);
  record("main_to_profile_select", ["confirm"]);
  record("profile_select_to_main", ["back"]);

  controller.showLayoutForConformance("profile-save-select", "main_menu.resume_last_game");
  record("profile_select_resume_to_hub", ["confirm"]);

  assert.deepEqual(
    [...visited].sort(),
    [...CRITICAL_MENU_EDGE_IDS].sort(),
    "controller traversal did not cover the corrected critical-edge set",
  );
  lines.push(`PASS: ${visited.size}/${CRITICAL_MENU_EDGE_IDS.length} corrected critical edges traversed.`);

  const families = [
    {
      layoutId: "control-scheme-picker",
      prefix: "control_scheme_picker.select_",
      destination: "create_element",
      sampleEdge: "control_scheme_picker_to_create" as const,
    },
    {
      layoutId: "create-element",
      prefix: "create.select_element_",
      destination: "create_discipline",
      sampleEdge: "create_element_to_discipline" as const,
    },
    {
      layoutId: "create-discipline",
      prefix: "create.select_discipline_",
      destination: "hub",
      sampleEdge: "create_discipline_to_hub" as const,
    },
  ];
  lines.push("", "CRITICAL ACTION FAMILIES");
  for (const family of families) {
    controller.showLayoutForConformance(family.layoutId);
    const actions = controller.snapshot().focusNodes
      .map((node) => node.id)
      .filter((actionId) => actionId.startsWith(family.prefix));
    const sample = catalog.navigationEdges.find((edge) => edge.id === family.sampleEdge)?.actionId;
    assert(sample !== undefined && actions.includes(sample), `${family.layoutId} lost its measured sample action`);
    assert(actions.length > 0, `${family.layoutId} exposes no members of ${family.prefix}`);
    for (const actionId of actions) {
      controller.showLayoutForConformance(family.layoutId, actionId);
      assert.equal(controller.snapshot().focusId, actionId, `${family.layoutId} could not focus ${actionId}`);
      press("confirm");
      assert.equal(surfaceName(controller), family.destination, `${family.layoutId}/${actionId} did not dispatch`);
      lines.push(`FAMILY ${family.layoutId}/${actionId} -> ${family.destination}`);
    }
  }

  lines.push("", "MANIFEST-DRIVEN INERT SWEEP");
  let ownerDescoped = 0;
  let pendingCapture = 0;
  for (const entry of inert.entries) {
    controller.showLayoutForConformance(entry.screen, entry.actionId);
    assert.equal(controller.snapshot().focusId, entry.actionId, `${entry.screen}/${entry.actionId} is not clickable`);
    const before = structuredClone(controller.snapshot());
    press("confirm");
    assert.deepEqual(
      controller.snapshot(),
      before,
      `${entry.screen}/${entry.actionId} navigated or mutated shell state`,
    );
    if (entry.disposition === "owner_descoped") {
      ownerDescoped += 1;
    } else {
      pendingCapture += 1;
    }
    lines.push(`INERT ${entry.disposition} ${entry.screen}/${entry.actionId}: unchanged`);
  }
  assert.equal(pendingCapture, 1, "inert sweep must contain exactly the ruled NEW GAME capture gap");
  assert(ownerDescoped > 0, "inert sweep did not exercise the owner-descoped worklist");
  lines.push(
    `PASS: ${inert.entries.length}/${inert.entries.length} inert controls unchanged (${ownerDescoped} owner_descoped, ${pendingCapture} pending_capture).`,
  );

  const report = `${lines.join("\n")}\n`;
  const output = process.env.WEBGAME_TRAVERSAL_LOG;
  if (output !== undefined) {
    await writeFile(output, report, "utf8");
  }
  process.stdout.write(report);
}

await main();
