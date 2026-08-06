import type { Intent, MenuNavIntent } from "../input/intent.js";
import { FocusNavigator, type FocusAction, type FocusModel } from "../input/focus-model.js";
import type { InputSurface } from "../input/gamepad-producer.js";
import { buildFocusNodes, type ShellEligibility, type ShellFocusNode } from "./focus-nodes.js";
import type { MenuCatalog, MenuLayout, NativeRect } from "./menu-catalog.js";

export type ShellSurface =
  | { readonly kind: "layout"; readonly layoutId: string }
  | { readonly kind: "hub-stub" }
  | { readonly kind: "out-of-scope"; readonly message: string };

export interface ShellSnapshot {
  readonly surface: ShellSurface;
  readonly inputSurface: InputSurface;
  readonly focusId: string | null;
  readonly focusRect: NativeRect | null;
  readonly focusNodes: readonly ShellFocusNode[];
  readonly values: Readonly<Record<string, string | number | boolean>>;
  readonly inputGated: boolean;
}

export interface ShellStore {
  get(key: string): string | null;
  set(key: string, value: string): void;
}

interface ModalReturn {
  readonly layoutId: string;
  readonly focusId: string;
}

type SettingsOrigin = "main-menu-root" | "hub-stub" | "dark-cloud-my-levels";

const NOOP_STORE: ShellStore = {
  get: () => null,
  set: () => undefined,
};

function settingLayout(origin: SettingsOrigin): string {
  if (origin === "main-menu-root") {
    return "game-settings-title";
  }
  if (origin === "dark-cloud-my-levels") {
    return "game-settings-dark-cloud";
  }
  return "game-settings-gameplay";
}

function clamp(value: number): number {
  return Math.max(0, Math.min(1, value));
}

export class ShellController {
  readonly #catalog: MenuCatalog;
  readonly #focusModel: FocusModel;
  readonly #focus: FocusNavigator;
  readonly #clock: () => number;
  readonly #store: ShellStore;
  readonly #listeners = new Set<(snapshot: ShellSnapshot) => void>();
  #surface: ShellSurface = { kind: "layout", layoutId: "native-loader" };
  #nodes: readonly ShellFocusNode[] = [];
  #settingsOrigin: SettingsOrigin = "main-menu-root";
  #settingsChildReturn: string | null = null;
  #modalReturn: ModalReturn | null = null;
  #betaDestination = "main-menu-root";
  #inputGateUntil = 0;
  #enteredAt = 0;
  #gameOverArmed = false;
  #resumeAvailable = true;
  #lightQualityAvailable = false;
  #signedIn = false;
  #selectedBoneyardCompatible = false;
  #offeredSkillCount: 3 | 4 = 3;
  #unlockedStoryIndices: readonly number[] = [0];
  #selectedElement = "create.select_element_fire";
  #selectedDiscipline = "create.select_discipline_mind";
  #selectedMap = "map_picker.story[0]";
  #sort = "dark_cloud_sort.newest";
  #values: Record<string, string | number | boolean>;

  public constructor(
    catalog: MenuCatalog,
    focusModel: FocusModel,
    options: Readonly<{
      clock?: () => number;
      store?: ShellStore;
    }> = {},
  ) {
    this.#catalog = catalog;
    this.#focusModel = focusModel;
    this.#focus = new FocusNavigator(focusModel);
    this.#clock = options.clock ?? (() => performance.now());
    this.#store = options.store ?? NOOP_STORE;
    this.#values = {
      "settings.sound_volume": Number(this.#store.get("settings.sound_volume") ?? "0.8"),
      "settings.music_volume": Number(this.#store.get("settings.music_volume") ?? "0.65"),
      "settings.fullscreen": this.#store.get("settings.fullscreen") === "true",
      "settings.resolution": this.#store.get("settings.resolution") ?? "1280x800",
      "dark_account.dark_name": this.#store.get("dark_account.dark_name") ?? "",
      "dark_account.password": "",
      "dark_cloud_search.name": "",
    };
    this.#enterLayout("native-loader");
  }

  public subscribe(listener: (snapshot: ShellSnapshot) => void): () => void {
    this.#listeners.add(listener);
    listener(this.snapshot());
    return () => this.#listeners.delete(listener);
  }

  public snapshot(): ShellSnapshot {
    const focusId = this.#focus.focusedId;
    const focusRect = this.#nodes.find((node) => node.id === focusId)?.nativeRect ?? null;
    return {
      surface: this.#surface,
      inputSurface: this.inputSurface,
      focusId,
      focusRect,
      focusNodes: this.#nodes,
      values: { ...this.#values },
      inputGated: this.#clock() < this.#inputGateUntil,
    };
  }

  public get inputSurface(): InputSurface {
    if (this.#clock() < this.#inputGateUntil) {
      return "blocked";
    }
    if (this.#surface.kind === "hub-stub" || this.#surface.kind === "out-of-scope") {
      return "gameplay";
    }
    return this.#surface.layoutId === "native-loader" || this.#surface.layoutId === "loading-screen"
      ? "blocked"
      : "menu";
  }

  public completeBoot(firstRun: boolean): void {
    this.#betaDestination = firstRun ? "control-scheme-picker" : "main-menu-root";
    this.#inputGateUntil = this.#clock() + 2000;
    this.#enterLayout("beta-notice");
  }

  public showMatchLoading(): void {
    this.#enterLayout("loading-screen");
  }

  public finishMatchLoading(): void {
    this.#enterHub();
  }

  public showLayoutForConformance(layoutId: string, preferredFocus?: string): void {
    this.#inputGateUntil = 0;
    this.#enterLayout(layoutId, preferredFocus);
  }

  public showHubForConformance(): void {
    this.#inputGateUntil = 0;
    this.#enterHub();
  }

  public setEligibilityForConformance(
    values: Partial<Pick<ShellEligibility,
      | "resumeAvailable"
      | "lightQualityAvailable"
      | "darkCloudSignedIn"
      | "selectedBoneyardCompatible"
      | "gameOverArmed"
      | "offeredSkillCount"
      | "unlockedStoryIndices"
    >>,
  ): void {
    this.#resumeAvailable = values.resumeAvailable ?? this.#resumeAvailable;
    this.#lightQualityAvailable = values.lightQualityAvailable ?? this.#lightQualityAvailable;
    this.#signedIn = values.darkCloudSignedIn ?? this.#signedIn;
    this.#selectedBoneyardCompatible = values.selectedBoneyardCompatible
      ?? this.#selectedBoneyardCompatible;
    this.#gameOverArmed = values.gameOverArmed ?? this.#gameOverArmed;
    this.#offeredSkillCount = values.offeredSkillCount ?? this.#offeredSkillCount;
    this.#unlockedStoryIndices = values.unlockedStoryIndices ?? this.#unlockedStoryIndices;
    this.#refreshNodes();
  }

  public tick(): void {
    if (
      this.#surface.kind === "layout"
      && this.#surface.layoutId === "game-over"
      && !this.#gameOverArmed
      && this.#clock() - this.#enteredAt >= 1000
    ) {
      this.#gameOverArmed = true;
      this.#refreshNodes();
    }
  }

  public setTextValue(actionId: string, value: string): void {
    if (!this.#nodes.some((node) => node.id === actionId && node.textEntry)) {
      throw new Error(`${actionId} is not an active G11 text-entry node`);
    }
    this.#values[actionId] = value;
    if (actionId === "dark_account.dark_name") {
      this.#store.set(actionId, value);
    }
    this.#emit();
  }

  public handle(intent: Intent): void {
    if (this.inputSurface === "blocked") {
      return;
    }
    if (this.#surface.kind === "hub-stub" || this.#surface.kind === "out-of-scope") {
      if (intent.kind === "interact" && intent.phase === "press" && intent.target === "pause") {
        this.#enterLayout("pause-menu");
      }
      return;
    }
    if (intent.kind === "interact" && intent.phase === "press") {
      const target = this.#nodes.find((node) => node.id === intent.target && node.enabled);
      if (target !== undefined) {
        this.#activate(target.id);
      }
      return;
    }
    if (intent.kind !== "menu_nav") {
      return;
    }
    this.#applyFocusAction(intent, this.#focus.handle(intent));
  }

  #applyFocusAction(intent: MenuNavIntent, action: FocusAction): void {
    if (action.kind === "none") {
      return;
    }
    if (action.kind === "focus") {
      this.#emit();
      return;
    }
    if (action.kind === "activate") {
      this.#activate(action.id);
      return;
    }
    if (action.kind === "adjust") {
      this.#adjust(action.id, action.direction);
      return;
    }
    if (intent.command === "back") {
      this.#back();
    }
  }

  #activate(actionId: string): void {
    const layoutId = this.#requireLayout().id;
    if (actionId === "dialog.primary") {
      this.#enterLayout(this.#betaDestination);
    } else if (actionId.startsWith("control_scheme_picker.select_")) {
      this.#store.set("control_scheme", actionId);
      this.#enterLayout("create-element", this.#selectedElement);
    } else if (actionId === "main_menu.play") {
      this.#enterLayout("profile-save-select");
    } else if (actionId === "main_menu.explore_dark_cloud") {
      this.#enterLayout("dark-cloud-browser", "dark_cloud_browser.online_levels");
    } else if (actionId === "main_menu.settings") {
      this.#openSettings("main-menu-root");
    } else if (actionId === "main_menu.hall_of_fame") {
      this.#enterLayout("hall-of-fame");
    } else if (actionId === "main_menu.quit") {
      this.#enterOutOfScope("Quit is owned by the browser host; no native confirmation screen was recovered.");
    } else if (actionId === "main_menu.resume_last_game") {
      this.#enterHub();
    } else if (actionId === "main_menu.new_game") {
      this.#enterLayout("create-element", this.#selectedElement);
    } else if (actionId === "main_menu.back") {
      this.#enterLayout("main-menu-root");
    } else if (actionId.startsWith("create.select_element_")) {
      this.#selectedElement = actionId;
      this.#store.set("create.element", actionId);
      this.#enterLayout("create-discipline", this.#selectedDiscipline);
    } else if (actionId.startsWith("create.select_discipline_")) {
      this.#selectedDiscipline = actionId;
      this.#store.set("create.discipline", actionId);
      this.#resumeAvailable = true;
      this.#enterHub();
    } else if (actionId.startsWith("settings.")) {
      this.#activateSetting(actionId);
    } else if (actionId === "controls.back" || actionId === "performance.back") {
      this.#returnToSettings();
    } else if (layoutId === "dark-cloud-settings" && actionId === "dark_account.back") {
      this.#returnToSettings();
    } else if (actionId === "dark_account.dark_name" || actionId === "dark_account.password") {
      this.#emit();
    } else if (actionId === "dark_account.sign_in") {
      this.#signedIn = true;
      this.#closeModal();
    } else if (actionId === "dark_account.create_new") {
      this.#enterOutOfScope("Account creation is outside the P0 shell and makes no network request.");
    } else if (actionId === "dark_account.done") {
      this.#closeModal();
    } else if (actionId.startsWith("dark_cloud_browser.")) {
      this.#activateDarkCloud(actionId);
    } else if (actionId === "dark_cloud_search.name") {
      this.#emit();
    } else if (actionId === "dark_cloud_search.search_now") {
      this.#closeModal();
    } else if (actionId.startsWith("dark_cloud_sort.")) {
      this.#sort = actionId;
      this.#closeModal();
    } else if (actionId === "dark_cloud_options.select_boneyard") {
      this.#enterLayout("map-picker", this.#selectedMap);
    } else if (actionId === "profile.resume") {
      this.#enterLayout("dark-cloud-my-levels", "dark_cloud_browser.my_levels");
    } else if (actionId === "profile.game_settings") {
      this.#openSettings("dark-cloud-my-levels");
    } else if (actionId === "profile.sign_out") {
      this.#signedIn = false;
      this.#enterLayout("dark-cloud-my-levels", "dark_cloud_browser.my_levels");
    } else if (actionId === "profile.main_menu") {
      this.#betaDestination = "main-menu-root";
      this.#enterLayout("beta-notice");
    } else if (actionId === "pause_menu.resume_game") {
      this.#enterHub();
    } else if (actionId === "pause_menu.game_settings") {
      this.#openSettings("hub-stub");
    } else if (actionId === "pause_menu.leave_game") {
      this.#betaDestination = "main-menu-root";
      this.#enterLayout("beta-notice");
    } else if (actionId.startsWith("skill_picker.option[")) {
      this.#enterHub();
    } else if (actionId.startsWith("map_picker.story[")) {
      this.#selectedMap = actionId;
      this.#enterOutOfScope("Gameplay and Boneyard startup are outside P0; selection is retained by shell state.");
    } else if (actionId === "game_over.continue") {
      this.#enterLayout("hall-of-fame");
    } else if (actionId === "hall_of_fame.continue") {
      this.#betaDestination = "main-menu-root";
      this.#enterLayout("beta-notice");
    } else {
      throw new Error(`${layoutId} has no shell action for ${actionId}`);
    }
  }

  #activateSetting(actionId: string): void {
    if (actionId === "settings.sound_volume" || actionId === "settings.music_volume") {
      this.#adjust(actionId, "right");
    } else if (actionId === "settings.fullscreen") {
      this.#values[actionId] = !this.#values[actionId];
      this.#persistValue(actionId);
      this.#emit();
    } else if (actionId === "settings.resolution") {
      this.#values[actionId] = this.#values[actionId] === "1280x800" ? "1600x900" : "1280x800";
      this.#persistValue(actionId);
      this.#emit();
    } else if (actionId === "settings.login_info") {
      this.#settingsChildReturn = settingLayout(this.#settingsOrigin);
      this.#enterLayout("dark-cloud-settings");
    } else if (actionId === "settings.customize_keyboard") {
      this.#settingsChildReturn = settingLayout(this.#settingsOrigin);
      this.#enterLayout("controls");
    } else if (actionId === "settings.tweak_game") {
      this.#settingsChildReturn = settingLayout(this.#settingsOrigin);
      this.#enterLayout("performance");
    } else if (actionId === "settings.done") {
      this.#closeSettings();
    }
  }

  #adjust(actionId: string, direction: "left" | "right"): void {
    const value = this.#values[actionId];
    if (typeof value === "number") {
      this.#values[actionId] = clamp(value + (direction === "right" ? 0.05 : -0.05));
    } else if (typeof value === "boolean") {
      this.#values[actionId] = !value;
    } else if (actionId.startsWith("performance.") || actionId.startsWith("controls.")) {
      this.#values[actionId] = direction;
    }
    this.#persistValue(actionId);
    this.#emit();
  }

  #activateDarkCloud(actionId: string): void {
    if (actionId === "dark_cloud_browser.recent") {
      this.#enterLayout("dark-cloud-recent", actionId);
    } else if (actionId === "dark_cloud_browser.online_levels") {
      this.#enterLayout("dark-cloud-online-levels", actionId);
    } else if (actionId === "dark_cloud_browser.my_levels") {
      this.#enterLayout("dark-cloud-my-levels", actionId);
    } else if (actionId.startsWith("dark_cloud_browser.level_row[")) {
      this.#selectedBoneyardCompatible = true;
      this.#refreshNodes();
    } else if (actionId === "dark_cloud_browser.search") {
      this.#openModal("dark-cloud-search", actionId);
    } else if (actionId === "dark_cloud_browser.sort") {
      this.#openModal("dark-cloud-sort", actionId, this.#sort);
    } else if (actionId === "dark_cloud_browser.options") {
      this.#openModal("dark-cloud-options", actionId);
    } else if (actionId === "dark_cloud_browser.login") {
      this.#openModal("dark-cloud-login-settings", actionId);
    } else if (actionId === "dark_cloud_browser.menu") {
      this.#openModal("dark-cloud-menu", actionId);
    } else if (actionId === "dark_cloud_browser.play" || actionId === "dark_cloud_browser.edit") {
      this.#enterOutOfScope("Multiplayer, rooms, hub gameplay, and Boneyard gameplay are outside P0.");
    }
  }

  #back(): void {
    if (this.#surface.kind !== "layout") {
      return;
    }
    const layoutId = this.#surface.layoutId;
    if (layoutId === "beta-notice") {
      this.#activate("dialog.primary");
    } else if (layoutId === "profile-save-select") {
      this.#activate("main_menu.back");
    } else if (layoutId === "create-element") {
      this.#enterLayout("profile-save-select");
    } else if (layoutId === "create-discipline") {
      this.#enterLayout("create-element", this.#selectedElement);
    } else if (layoutId.startsWith("game-settings-")) {
      this.#closeSettings();
    } else if (layoutId === "controls" || layoutId === "performance" || layoutId === "dark-cloud-settings") {
      this.#returnToSettings();
    } else if (
      layoutId === "dark-cloud-search"
      || layoutId === "dark-cloud-sort"
      || layoutId === "dark-cloud-options"
      || layoutId === "dark-cloud-login-settings"
    ) {
      this.#closeModal();
    } else if (layoutId === "dark-cloud-menu") {
      this.#activate("profile.resume");
    } else if (layoutId.startsWith("dark-cloud-")) {
      this.#openModal("dark-cloud-menu", "dark_cloud_browser.menu");
    } else if (layoutId === "pause-menu") {
      this.#enterHub();
    } else if (layoutId === "map-picker") {
      this.#enterHub();
    } else if (layoutId === "hall-of-fame") {
      this.#activate("hall_of_fame.continue");
    }
  }

  #openSettings(origin: SettingsOrigin): void {
    this.#settingsOrigin = origin;
    this.#settingsChildReturn = null;
    this.#modalReturn = null;
    this.#enterLayout(settingLayout(origin));
  }

  #returnToSettings(): void {
    if (this.#settingsChildReturn === null) {
      throw new Error("settings child cannot return without an invoking settings surface");
    }
    this.#enterLayout(this.#settingsChildReturn);
  }

  #closeSettings(): void {
    if (this.#settingsOrigin === "hub-stub") {
      this.#enterHub();
    } else {
      this.#enterLayout(this.#settingsOrigin);
    }
  }

  #openModal(layoutId: string, invoker: string, preferredFocus?: string): void {
    const current = this.#requireLayout();
    this.#modalReturn = { layoutId: current.id, focusId: invoker };
    this.#enterLayout(layoutId, preferredFocus);
  }

  #closeModal(): void {
    if (this.#modalReturn === null) {
      throw new Error("G11 modal cannot close without an invoker to restore");
    }
    const target = this.#modalReturn;
    this.#modalReturn = null;
    this.#enterLayout(target.layoutId, target.focusId);
  }

  #enterLayout(layoutId: string, preferredFocus?: string): void {
    const layout = this.#catalog.layouts.get(layoutId);
    if (layout === undefined) {
      throw new Error(`shell cannot enter missing G11 layout ${layoutId}`);
    }
    this.#surface = { kind: "layout", layoutId };
    this.#enteredAt = this.#clock();
    if (layoutId === "game-over") {
      this.#gameOverArmed = false;
    }
    this.#nodes = buildFocusNodes(layout, this.#focusModel, this.#eligibility());
    this.#focus.enter(layoutId, this.#nodes, preferredFocus ?? this.#preferredFocus(layoutId));
    this.#emit();
  }

  #enterHub(): void {
    this.#surface = { kind: "hub-stub" };
    this.#nodes = [];
    this.#emit();
  }

  #enterOutOfScope(message: string): void {
    this.#surface = { kind: "out-of-scope", message };
    this.#nodes = [];
    this.#emit();
  }

  #refreshNodes(): void {
    if (this.#surface.kind !== "layout") {
      return;
    }
    const layout = this.#requireLayout();
    this.#nodes = buildFocusNodes(layout, this.#focusModel, this.#eligibility());
    this.#focus.updateAvailable(this.#nodes);
    this.#emit();
  }

  #preferredFocus(layoutId: string): string | undefined {
    if (layoutId === "create-element") {
      return this.#selectedElement;
    }
    if (layoutId === "create-discipline") {
      return this.#selectedDiscipline;
    }
    if (layoutId === "dark-cloud-browser" || layoutId === "dark-cloud-online-levels") {
      return "dark_cloud_browser.online_levels";
    }
    if (layoutId === "dark-cloud-recent") {
      return "dark_cloud_browser.recent";
    }
    if (layoutId === "dark-cloud-my-levels") {
      return "dark_cloud_browser.my_levels";
    }
    if (layoutId === "dark-cloud-sort") {
      return this.#sort;
    }
    if (layoutId === "map-picker") {
      return this.#selectedMap;
    }
    return undefined;
  }

  #eligibility(): ShellEligibility {
    return {
      resumeAvailable: this.#resumeAvailable,
      lightQualityAvailable: this.#lightQualityAvailable,
      darkCloudSignedIn: this.#signedIn,
      selectedBoneyardCompatible: this.#selectedBoneyardCompatible,
      gameOverArmed: this.#gameOverArmed,
      offeredSkillCount: this.#offeredSkillCount,
      unlockedStoryIndices: this.#unlockedStoryIndices,
    };
  }

  #requireLayout(): MenuLayout {
    if (this.#surface.kind !== "layout") {
      throw new Error("shell action requires an active G11 layout");
    }
    const layout = this.#catalog.layouts.get(this.#surface.layoutId);
    if (layout === undefined) {
      throw new Error(`shell lost G11 layout ${this.#surface.layoutId}`);
    }
    return layout;
  }

  #persistValue(actionId: string): void {
    const value = this.#values[actionId];
    if (value !== undefined) {
      this.#store.set(actionId, String(value));
    }
  }

  #emit(): void {
    const snapshot = this.snapshot();
    for (const listener of this.#listeners) {
      listener(snapshot);
    }
  }
}
