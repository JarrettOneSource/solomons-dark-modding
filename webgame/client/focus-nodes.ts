import { effectiveFocusOrder, type FocusModel, type FocusNode } from "../input/focus-model.js";
import type { MenuLayout, NativeRect } from "./menu-catalog.js";
import { nativeRectToBox } from "./menu-catalog.js";

export interface ShellEligibility {
  readonly resumeAvailable: boolean;
  readonly lightQualityAvailable: boolean;
  readonly darkCloudSignedIn: boolean;
  readonly selectedBoneyardCompatible: boolean;
  readonly gameOverArmed: boolean;
  readonly offeredSkillCount: 3 | 4;
  readonly unlockedStoryIndices: readonly number[];
}

export interface ShellFocusNode extends FocusNode {
  readonly rect: ReturnType<typeof nativeRectToBox>;
  readonly nativeRect: NativeRect;
  readonly textEntry: boolean;
}

const settingsRows: Readonly<Record<string, NativeRect>> = {
  "settings.sound_volume": [520, 207, 1080, 252],
  "settings.music_volume": [520, 252, 1080, 297],
  "settings.fullscreen": [520, 339, 1080, 383],
  "settings.resolution": [520, 383, 1080, 428],
  "settings.login_info": [520, 470, 1080, 519],
  "settings.customize_keyboard": [520, 562, 1080, 611],
  "settings.tweak_game": [520, 653, 1080, 702],
  "settings.done": [650, 740, 950, 780],
};

const accountRows: Readonly<Record<string, Readonly<Record<string, NativeRect>>>> = {
  "dark-cloud-settings": {
    "dark_account.dark_name": [663, 200, 1060, 229],
    "dark_account.password": [663, 241, 1060, 270],
    "dark_account.back": [650, 743, 950, 782],
  },
  "dark-cloud-login-settings": {
    "dark_account.dark_name": [663, 370, 1060, 399],
    "dark_account.password": [663, 410, 1060, 439],
    "dark_account.sign_in": [520, 446, 1080, 490],
    "dark_account.create_new": [520, 517, 1080, 566],
    "dark_account.done": [650, 586, 950, 628],
  },
};

const searchRows: Readonly<Record<string, NativeRect>> = {
  "dark_cloud_search.name": [669, 405, 1010, 436],
  "dark_cloud_search.search_now": [570, 470, 1030, 518],
};

const sortRows: Readonly<Record<string, NativeRect>> = {
  "dark_cloud_sort.newest": [670, 174, 925, 216],
  "dark_cloud_sort.oldest": [670, 216, 925, 257],
  "dark_cloud_sort.updated_recently": [670, 257, 925, 298],
  "dark_cloud_sort.best_rating": [670, 298, 925, 340],
};

const performanceRows: readonly NativeRect[] = [
  [520, 200, 1080, 246],
  [520, 246, 1080, 287],
  [520, 287, 1080, 328],
  [520, 328, 1080, 378],
  [520, 378, 1080, 419],
  [520, 419, 1080, 460],
  [520, 510, 1080, 551],
  [520, 551, 1080, 592],
  [520, 592, 1080, 633],
  [650, 650, 950, 697],
];

const controlsRows: readonly NativeRect[] = Array.from({ length: 16 }, (_, index) => {
  const top = 190 + index * 31;
  return [520, top, 1080, top + 30] as const;
});

function exactControlRect(layout: MenuLayout, actionId: string): NativeRect | undefined {
  return layout.elements.find((element) => (
    element.visible && element.interactive && element.actionId === actionId
  ))?.rect;
}

function proxyRect(layout: MenuLayout, actionId: string, orderIndex: number): NativeRect {
  const exact = exactControlRect(layout, actionId);
  if (exact !== undefined) {
    return exact;
  }
  if (actionId === "control_scheme_picker.select_arrows_mouse") {
    return [477.5, 290, 722.5, 610];
  }
  if (actionId === "main_menu.quit") {
    return [1480, 834, 1580, 886];
  }
  if (actionId === "dark_cloud_browser.play" || actionId === "dark_cloud_browser.edit") {
    return [623.5, 809.5, 976.5, 878.5];
  }
  if (settingsRows[actionId] !== undefined) {
    return settingsRows[actionId];
  }
  const accountRow = accountRows[layout.id]?.[actionId];
  if (accountRow !== undefined) {
    return accountRow;
  }
  if (searchRows[actionId] !== undefined) {
    return searchRows[actionId];
  }
  if (sortRows[actionId] !== undefined) {
    return sortRows[actionId];
  }
  if (actionId.startsWith("controls.")) {
    return controlsRows[orderIndex] ?? [650, 740, 950, 780];
  }
  if (actionId.startsWith("performance.")) {
    return performanceRows[orderIndex] ?? [650, 650, 950, 697];
  }
  if (actionId === "dark_cloud_options.select_boneyard") {
    return [590, 460, 1010, 510];
  }
  if (actionId === "game_over.continue") {
    return [647, 515, 953, 635];
  }
  if (actionId === "hall_of_fame.continue") {
    return [623.5, 815.5, 976.5, 884.5];
  }
  throw new Error(`${layout.id} has no focus-only geometry for G11 action ${actionId}`);
}

function region(actionId: string): FocusNode["region"] {
  if (actionId === "dark_cloud_browser.login") {
    return "login";
  }
  if (/dark_cloud_browser\.(recent|online_levels|my_levels)/.test(actionId)) {
    return "tabs";
  }
  if (actionId.startsWith("dark_cloud_browser.level_row")) {
    return "rows";
  }
  if (actionId === "dark_cloud_browser.menu") {
    return "menu";
  }
  if (actionId.startsWith("dark_cloud_browser.")) {
    return "footer";
  }
  return undefined;
}

function enabled(actionId: string, eligibility: ShellEligibility): boolean {
  if (actionId === "main_menu.resume_last_game") {
    return eligibility.resumeAvailable;
  }
  if (actionId === "performance.light_quality") {
    return eligibility.lightQualityAvailable;
  }
  if (actionId === "profile.sign_out") {
    return eligibility.darkCloudSignedIn;
  }
  if (
    actionId === "dark_cloud_browser.play"
    || actionId === "dark_cloud_browser.edit"
    || actionId === "dark_cloud_options.select_boneyard"
  ) {
    return eligibility.selectedBoneyardCompatible;
  }
  if (actionId === "game_over.continue") {
    return eligibility.gameOverArmed;
  }
  return true;
}

function node(
  id: string,
  rectangle: NativeRect,
  eligibility: ShellEligibility,
): ShellFocusNode {
  const nodeRegion = region(id);
  return {
    id,
    enabled: enabled(id, eligibility),
    rect: nativeRectToBox(rectangle),
    nativeRect: rectangle,
    textEntry: id.endsWith(".dark_name") || id.endsWith(".password") || id === "dark_cloud_search.name",
    ...(nodeRegion === undefined ? {} : { region: nodeRegion }),
  };
}

/**
 * G11 DESIGN_NOT_OBSERVED: native-menus-and-boot.md, "Focus & designed
 * controller navigation". Older baked-label menus expose no native semantic
 * hit rectangles. Their rectangles below are focus-only row proxies, never a
 * claim that the native click ABI used those bounds.
 */
export function buildFocusNodes(
  layout: MenuLayout,
  model: FocusModel,
  eligibility: ShellEligibility,
): readonly ShellFocusNode[] {
  const rule = model.screens.get(layout.id);
  if (rule === undefined) {
    throw new Error(`G11 focus model has no screen rule for ${layout.id}`);
  }
  if (layout.id === "skill-picker") {
    return Array.from({ length: eligibility.offeredSkillCount }, (_, index) => node(
      `skill_picker.option[${index}]`,
      [556.5 + index * 200, 338.5, 643.5 + index * 200, 426.5],
      eligibility,
    ));
  }
  if (layout.id === "map-picker") {
    return eligibility.unlockedStoryIndices.map((storyIndex, index) => node(
      `map_picker.story[${storyIndex}]`,
      index === 0 ? [817, 457.5, 890, 511.5] : [817 + index * 82, 457.5, 890 + index * 82, 511.5],
      eligibility,
    ));
  }

  const result: ShellFocusNode[] = [];
  for (const [orderIndex, actionId] of effectiveFocusOrder(rule).entries()) {
    if (actionId === "dark_cloud_browser.level_rows") {
      result.push(node("dark_cloud_browser.level_row[0]", [105, 258, 1495, 318], eligibility));
      continue;
    }
    result.push(node(actionId, proxyRect(layout, actionId, orderIndex), eligibility));
  }
  return result;
}
