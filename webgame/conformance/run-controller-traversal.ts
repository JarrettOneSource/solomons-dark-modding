import assert from "node:assert/strict";
import { readFile, writeFile } from "node:fs/promises";
import path from "node:path";

import { GamepadProducer, type GamepadSnapshot } from "../input/gamepad-producer.js";
import { parseFocusModel } from "../input/focus-model.js";
import { parseMenuCatalog } from "../client/menu-catalog.js";
import { ShellController } from "../client/shell-controller.js";

const repository = path.resolve(import.meta.dirname, "..", "..");

interface GoldenEdge {
  readonly id: string;
  readonly screen: string;
  readonly trigger: string;
  readonly action_id: string;
  readonly destination: string;
}

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
  if (surface.kind === "out-of-scope") {
    return "out_of_scope";
  }
  const aliases: Readonly<Record<string, string>> = {
    "control-scheme-picker": "control_scheme_picker",
    "create-element": "create_element",
    "create-discipline": "create_discipline",
    "pause-menu": "pause_menu",
    "game-settings-title": "settings",
    "game-settings-gameplay": "settings",
    "game-settings-dark-cloud": "settings",
    "dark-cloud-settings": "dark_cloud_settings",
    "beta-notice": "beta_notice",
    "main-menu-root": "main_menu",
    "profile-save-select": "profile_save_select",
    "hall-of-fame": "hall_of_fame",
    "dark-cloud-browser": "dark_cloud_browser",
    "dark-cloud-recent": "dark_cloud_recent",
    "dark-cloud-online-levels": "dark_cloud_online_levels",
    "dark-cloud-my-levels": "dark_cloud_my_levels",
    "dark-cloud-search": "dark_cloud_search",
    "dark-cloud-sort": "dark_cloud_sort",
    "dark-cloud-options": "dark_cloud_options",
    "dark-cloud-login-settings": "dark_cloud_login_settings",
    "dark-cloud-menu": "dark_cloud_menu",
  };
  return aliases[surface.layoutId] ?? surface.layoutId.replaceAll("-", "_");
}

async function main(): Promise<void> {
  const menuGolden = JSON.parse(
    await readFile(path.join(repository, "tests", "fixtures", "webgame", "menu-goldens.json"), "utf8"),
  ) as { navigation_graph: { edges: GoldenEdge[] } };
  const focusGolden = JSON.parse(
    await readFile(path.join(repository, "webgame-contracts", "menu-focus-model.json"), "utf8"),
  ) as unknown;
  const catalog = parseMenuCatalog(menuGolden);
  const focusModel = parseFocusModel(focusGolden);
  const edges = new Map(menuGolden.navigation_graph.edges.map((edge) => [edge.id, edge]));
  assert.equal(edges.size, 39, "controller traversal must ingest all 39 live G11 edges");
  let now = 0;
  const controller = new ShellController(catalog, focusModel, { clock: () => now });
  const producer = new GamepadProducer((intent) => {
    controller.handle(intent);
  }, () => ({ surface: controller.inputSurface }));
  const visited = new Set<string>();
  const lines = [
    "G11 CONTROLLER-ONLY TRAVERSAL",
    "Synthetic standard-gamepad snapshots only; branch resets are test setup, never edge triggers.",
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
    edgeId: string,
    commands: readonly (keyof typeof buttonForCommand)[],
    expectedDestination?: string,
  ): void => {
    const edge = edges.get(edgeId);
    assert(edge !== undefined, `traversal references unknown G11 edge ${edgeId}`);
    assert(!visited.has(edgeId), `G11 edge ${edgeId} was traversed twice instead of exactly once`);
    const before = surfaceName(controller);
    assert.equal(before, edge.screen, `${edgeId} started from ${before}, expected ${edge.screen}`);
    const focusBefore = controller.snapshot().focusId;
    presses(...commands);
    const after = surfaceName(controller);
    const accepted = new Set([edge.destination, expectedDestination].filter((value): value is string => value !== undefined));
    assert(accepted.has(after), `${edgeId} reached ${after}, expected ${[...accepted].join(" or ")}`);
    visited.add(edgeId);
    lines.push(
      `${String(visited.size).padStart(2, "0")}. ${edgeId}: ${before} --[${commands.join("+")}; focus=${focusBefore ?? "none"}]--> ${after}`,
    );
  };
  const resetLayout = (layoutId: string): void => {
    controller.showLayoutForConformance(layoutId);
    lines.push(`RESET: ${layoutId} (branch setup)`);
  };
  const resetHub = (): void => {
    controller.showHubForConformance();
    lines.push("RESET: hub-stub (branch setup)");
  };

  controller.completeBoot(true);
  now = 2001;
  press("confirm");
  record("control_scheme_picker_to_create", ["confirm"]);
  record("create_element_to_discipline", ["confirm"]);
  record("create_discipline_to_hub", ["confirm"]);
  record("hub_to_pause", ["start"]);
  record("pause_to_hub_resume", ["confirm"]);

  resetHub();
  press("start");
  record("pause_to_game_settings", ["down", "confirm"]);
  record("settings_to_controls", ["down", "down", "down", "down", "confirm"]);
  record("controls_to_settings", ["back"]);
  record("settings_to_performance", ["down", "down", "down", "down", "down", "confirm"]);
  record("performance_to_settings", ["back"]);
  record("settings_to_dark_cloud_settings", ["down", "down", "down", "confirm"]);
  record("dark_cloud_settings_to_settings", ["back"]);
  record("settings_to_hub", ["down", "down", "down", "down", "down", "down", "confirm"]);

  resetHub();
  press("start");
  record("pause_to_beta_notice", ["down", "down", "confirm"]);
  record("beta_notice_to_main", ["confirm"]);

  resetLayout("main-menu-root");
  record("main_to_profile_select", ["confirm"]);
  record("profile_select_to_main", ["back"]);
  record("main_to_settings", ["down", "down", "confirm"]);
  record("settings_to_main", ["down", "down", "down", "down", "down", "down", "down", "confirm"]);

  resetLayout("main-menu-root");
  record("main_to_hall_of_fame", ["down", "down", "down", "confirm"]);
  record("hall_of_fame_to_beta_notice", ["confirm"]);

  resetLayout("main-menu-root");
  record("main_to_dark_cloud", ["down", "confirm"]);
  record("dark_cloud_to_recent", ["left", "confirm"]);
  record("dark_cloud_recent_to_online", ["right", "confirm"]);
  record("dark_cloud_online_to_my_levels", ["right", "confirm"]);
  record("dark_cloud_to_search", ["down", "down", "left", "confirm"]);
  record("dark_cloud_search_to_browser", ["back"]);
  record("dark_cloud_to_sort", ["right", "confirm"]);
  record("dark_cloud_sort_to_browser", ["back"]);
  record("dark_cloud_to_options", ["right", "confirm"]);
  record("dark_cloud_options_to_browser", ["back"]);
  record("dark_cloud_to_login_settings", ["up", "up", "up", "confirm"], "dark_cloud_login_settings");
  record("dark_cloud_login_to_browser", ["down", "down", "down", "down", "confirm"]);
  record("dark_cloud_to_menu", ["up", "confirm"]);
  record("dark_cloud_menu_resume", ["confirm"]);

  resetLayout("dark-cloud-my-levels");
  presses("up", "up", "confirm");
  record("dark_cloud_menu_to_settings", ["down", "confirm"]);
  record("dark_cloud_settings_done", ["down", "down", "down", "down", "down", "down", "confirm"]);

  resetLayout("dark-cloud-my-levels");
  presses("up", "up", "confirm");
  record("dark_cloud_menu_to_beta_notice", ["down", "down", "confirm"]);

  resetLayout("profile-save-select");
  record("profile_select_resume_to_hub", ["confirm"]);

  assert.deepEqual(
    [...visited].sort(),
    [...edges.keys()].sort(),
    "controller traversal did not cover the complete 39-edge live G11 graph",
  );
  lines.push(`PASS: ${visited.size}/39 live graph edges traversed with synthetic gamepad intents.`);

  // G11 § "Focus — designed controller navigation" is DESIGN_NOT_OBSERVED.
  // These are separate designed-screen probes, not fabricated live graph edges.
  // Each enters by test setup and then uses only synthetic standard-gamepad
  // snapshots to verify the runtime default and wrap behavior.
  controller.setEligibilityForConformance({
    lightQualityAvailable: true,
    darkCloudSignedIn: true,
    selectedBoneyardCompatible: true,
    offeredSkillCount: 4,
    unlockedStoryIndices: [0, 1, 2],
  });
  const expectedDefault = new Map<string, string | null>([
    ["native-loader", null],
    ["loading-screen", null],
    ["beta-notice", "dialog.primary"],
    ["control-scheme-picker", "control_scheme_picker.select_wasd"],
    ["main-menu-root", "main_menu.play"],
    ["profile-save-select", "main_menu.resume_last_game"],
    ["create-element", "create.select_element_fire"],
    ["create-discipline", "create.select_discipline_mind"],
    ["game-settings-title", "settings.sound_volume"],
    ["game-settings-gameplay", "settings.sound_volume"],
    ["game-settings-dark-cloud", "settings.sound_volume"],
    ["dark-cloud-settings", "dark_account.dark_name"],
    ["controls", "controls.move_up"],
    ["performance", "performance.complex_lighting"],
    ["dark-cloud-browser", "dark_cloud_browser.online_levels"],
    ["dark-cloud-recent", "dark_cloud_browser.recent"],
    ["dark-cloud-online-levels", "dark_cloud_browser.online_levels"],
    ["dark-cloud-my-levels", "dark_cloud_browser.my_levels"],
    ["dark-cloud-search", "dark_cloud_search.name"],
    ["dark-cloud-sort", "dark_cloud_sort.newest"],
    ["dark-cloud-options", "dark_cloud_options.select_boneyard"],
    ["dark-cloud-login-settings", "dark_account.dark_name"],
    ["dark-cloud-menu", "profile.resume"],
    ["pause-menu", "pause_menu.resume_game"],
    ["skill-picker", "skill_picker.option[0]"],
    ["map-picker", "map_picker.story[0]"],
    ["game-over", "game_over.continue"],
    ["hall-of-fame", "hall_of_fame.continue"],
  ]);
  assert.equal(expectedDefault.size, 28, "screen probe must name one expected G11 default per layout");
  const probedScreens = new Set<string>();
  lines.push("", "G11 28-SCREEN CONTROLLER OPERABILITY CENSUS");
  for (const layoutId of catalog.screenCensus) {
    controller.showLayoutForConformance(layoutId);
    if (layoutId === "game-over") {
      now += 1000;
      controller.tick();
    }
    const before = controller.snapshot();
    const expected = expectedDefault.get(layoutId);
    assert(expectedDefault.has(layoutId), `screen probe has no expected G11 default for ${layoutId}`);
    assert.equal(before.focusId, expected, `${layoutId} did not enter at its designed G11 default`);
    if (layoutId === "native-loader" || layoutId === "loading-screen") {
      assert.equal(before.inputSurface, "blocked", `${layoutId} did not retain the G11 input seal`);
      press("confirm");
      assert.deepEqual(
        controller.snapshot().surface,
        { kind: "layout", layoutId },
        `${layoutId} accepted controller input through its G11 input seal`,
      );
      lines.push(`SCREEN ${layoutId}: sealed; synthetic confirm ignored`);
    } else {
      assert.equal(before.inputSurface, "menu", `${layoutId} is not controller-addressable`);
      assert(before.focusId !== null, `${layoutId} has no controller focus under enabled eligibility`);
      press("previous");
      const wrapped = controller.snapshot().focusId;
      press("next");
      assert.equal(
        controller.snapshot().focusId,
        before.focusId,
        `${layoutId} previous/next did not return to its designed G11 default`,
      );
      lines.push(
        `SCREEN ${layoutId}: default=${before.focusId}; previous=${wrapped}; next=${before.focusId}`,
      );
    }
    assert(!probedScreens.has(layoutId), `screen probe visited duplicate G11 layout ${layoutId}`);
    probedScreens.add(layoutId);
  }
  assert.deepEqual(
    [...probedScreens].sort(),
    [...catalog.screenCensus].sort(),
    "controller screen census did not cover the exact 28 G11 layouts",
  );
  lines.push(`PASS: ${probedScreens.size}/28 layouts have controller defaults and wrap/input-seal probes.`);

  resetLayout("skill-picker");
  press("back");
  assert.deepEqual(
    controller.snapshot().surface,
    { kind: "layout", layoutId: "skill-picker" },
    "mandatory skill picker accepted Back instead of retaining the choice",
  );
  press("confirm");
  assert.equal(surfaceName(controller), "hub", "skill picker confirm did not return to the shell hub stub");
  lines.push("DESIGNED skill-picker: Back ignored; Confirm -> hub-stub");

  resetLayout("map-picker");
  press("back");
  assert.equal(surfaceName(controller), "hub", "map picker Back did not return to the Courtyard stub");
  resetLayout("map-picker");
  press("confirm");
  assert.equal(surfaceName(controller), "out_of_scope", "map picker Start did not reach the visible P0 boundary");
  lines.push("DESIGNED map-picker: Back -> hub-stub; Start -> visible P0 boundary");

  resetLayout("game-over");
  press("confirm");
  assert.equal(surfaceName(controller), "game_over", "Game Over accepted confirm before its input-arm threshold");
  now += 1000;
  controller.tick();
  press("confirm");
  assert.equal(surfaceName(controller), "hall_of_fame", "armed Game Over confirm did not continue");
  lines.push("DESIGNED game-over: early Confirm ignored; armed Confirm -> hall-of-fame");

  const report = `${lines.join("\n")}\n`;
  const output = process.env.WEBGAME_TRAVERSAL_LOG;
  if (output !== undefined) {
    await writeFile(output, report, "utf8");
  }
  process.stdout.write(report);
}

await main();
