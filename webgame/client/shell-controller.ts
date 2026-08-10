import type { Intent, MenuNavIntent } from "../input/intent.js";
import { FocusNavigator, type FocusAction, type FocusModel } from "../input/focus-model.js";
import type { InputSurface } from "../input/gamepad-producer.js";
import { buildFocusNodes, type ShellEligibility, type ShellFocusNode } from "./focus-nodes.js";
import { type InertControlCatalog, withInertControls } from "./inert-controls.js";
import type {
  MenuCatalog,
  MenuDialogComposite,
  MenuLayout,
  NativeRect,
  NavigationEdge,
} from "./menu-catalog.js";

export const CRITICAL_MENU_EDGE_IDS = [
  "beta_notice_first_boot_to_control_scheme_picker",
  "control_scheme_picker_to_create",
  "create_element_to_discipline",
  "create_discipline_to_hub",
  "hub_to_pause",
  "pause_to_hub_resume",
  "pause_to_beta_notice",
  "beta_notice_to_main",
  "main_to_profile_select",
  "profile_select_to_main",
  "profile_select_resume_to_hub",
] as const;

export type CriticalMenuEdgeId = typeof CRITICAL_MENU_EDGE_IDS[number];

export type ShellSurface =
  | { readonly kind: "layout"; readonly layoutId: string }
  | { readonly kind: "dialog-composite"; readonly compositeId: string }
  | { readonly kind: "hub-stub"; readonly endpointLayoutId: string };

export interface ShellSnapshot {
  readonly surface: ShellSurface;
  readonly inputSurface: InputSurface;
  readonly focusId: string | null;
  readonly focusRect: NativeRect | null;
  readonly focusNodes: readonly ShellFocusNode[];
  readonly values: Readonly<Record<string, string | number | boolean>>;
  readonly inputGated: boolean;
}

const DEFAULT_ELIGIBILITY: ShellEligibility = {
  resumeAvailable: true,
  lightQualityAvailable: true,
  darkCloudSignedIn: true,
  selectedBoneyardCompatible: true,
  gameOverArmed: true,
  offeredSkillCount: 3,
  unlockedStoryIndices: [0],
};

function indexCriticalEdges(catalog: MenuCatalog): ReadonlyMap<CriticalMenuEdgeId, NavigationEdge> {
  const graph = new Map(catalog.navigationEdges.map((edge) => [edge.id, edge]));
  const critical = new Map<CriticalMenuEdgeId, NavigationEdge>();
  for (const id of CRITICAL_MENU_EDGE_IDS) {
    const edge = graph.get(id);
    if (edge === undefined) {
      throw new Error(`corrected navigation graph is missing critical edge ${id}`);
    }
    if (edge.destinationType !== "layout" || edge.destinationLayoutId === null) {
      throw new Error(`critical edge ${id} has no destination layout binding`);
    }
    critical.set(id, edge);
  }
  return critical;
}

export class ShellController {
  readonly #catalog: MenuCatalog;
  readonly #inert: InertControlCatalog;
  readonly #focusModel: FocusModel;
  readonly #focus: FocusNavigator;
  readonly #clock: () => number;
  readonly #criticalEdges: ReadonlyMap<CriticalMenuEdgeId, NavigationEdge>;
  readonly #listeners = new Set<(snapshot: ShellSnapshot) => void>();
  #surface: ShellSurface = { kind: "layout", layoutId: "native-loader" };
  #nodes: readonly ShellFocusNode[] = [];
  #inputGateUntil = 0;
  #eligibility: ShellEligibility = DEFAULT_ELIGIBILITY;
  #selectedElement = "create.select_element_fire";
  #selectedDiscipline = "create.select_discipline_mind";
  #values: Record<string, string | number | boolean> = {};

  public constructor(
    catalog: MenuCatalog,
    focusModel: FocusModel,
    inert: InertControlCatalog,
    options: Readonly<{ clock?: () => number }> = {},
  ) {
    this.#catalog = catalog;
    this.#inert = inert;
    this.#focusModel = withInertControls(focusModel, inert);
    this.#focus = new FocusNavigator(this.#focusModel);
    this.#clock = options.clock ?? (() => performance.now());
    this.#criticalEdges = indexCriticalEdges(catalog);
    this.#enterLayout("native-loader");
  }

  public subscribe(listener: (snapshot: ShellSnapshot) => void): () => void {
    this.#listeners.add(listener);
    listener(this.snapshot());
    return () => this.#listeners.delete(listener);
  }

  public snapshot(): ShellSnapshot {
    const focusedId = this.#focus.focusedId;
    const focusId = this.#nodes.some((node) => node.id === focusedId) ? focusedId : null;
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
    if (this.#surface.kind === "hub-stub") {
      return "gameplay";
    }
    if (
      this.#surface.kind === "layout"
      && (this.#surface.layoutId === "native-loader" || this.#surface.layoutId === "loading-screen")
    ) {
      return "blocked";
    }
    return "menu";
  }

  public completeBoot(): void {
    this.#inputGateUntil = this.#clock() + 2000;
    this.#enterDialogComposite("beta_notice_first_boot");
  }

  public showMatchLoading(): void {
    this.#enterLayout("loading-screen");
  }

  public finishMatchLoading(): void {
    this.#enterHub("hub_new_game");
  }

  public showLayoutForConformance(layoutId: string, preferredFocus?: string): void {
    this.#inputGateUntil = 0;
    if (this.#catalog.transitionLayoutIds.includes(layoutId)) {
      this.#enterHub(layoutId);
      return;
    }
    this.#enterLayout(layoutId, preferredFocus);
  }

  public showDialogCompositeForConformance(compositeId: string): void {
    this.#inputGateUntil = 0;
    this.#enterDialogComposite(compositeId);
  }

  public showHubForConformance(endpointLayoutId = "hub_new_game"): void {
    this.#inputGateUntil = 0;
    this.#enterHub(endpointLayoutId);
  }

  public setEligibilityForConformance(values: Partial<ShellEligibility>): void {
    this.#eligibility = { ...this.#eligibility, ...values };
    this.#refreshNodes();
  }

  public tick(): void {
    // Phase 1 has no time-armed menu actions. Retained for the frame-loop seam.
  }

  public setTextValue(actionId: string, value: string): void {
    void value;
    const screen = this.#activeScreenId();
    if (!this.#nodes.some((node) => node.id === actionId && node.textEntry)) {
      throw new Error(`${actionId} is not an active text-entry node`);
    }
    if (!this.#inert.has(screen, actionId)) {
      throw new Error(`${screen}/${actionId} is not classified by the inert-controls manifest`);
    }
  }

  public handle(intent: Intent): void {
    if (this.inputSurface === "blocked") {
      return;
    }
    if (this.#surface.kind === "hub-stub") {
      if (intent.kind === "interact" && intent.phase === "press" && intent.target === "pause") {
        this.#enterCriticalDestination("hub_to_pause");
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
      this.#activate(action.id);
      return;
    }
    if (intent.command === "back") {
      this.#back();
    }
  }

  #activate(actionId: string): void {
    const screen = this.#activeScreenId();
    if (this.#inert.has(screen, actionId)) {
      return;
    }
    if (screen === "beta_notice_first_boot" && actionId === "dialog.primary") {
      this.#enterCriticalDestination("beta_notice_first_boot_to_control_scheme_picker");
    } else if (
      screen === "control-scheme-picker"
      && actionId.startsWith("control_scheme_picker.select_")
    ) {
      this.#values.control_scheme = actionId;
      this.#enterCriticalDestination("control_scheme_picker_to_create", this.#selectedElement);
    } else if (screen === "create-element" && actionId.startsWith("create.select_element_")) {
      this.#selectedElement = actionId;
      this.#values["create.element"] = actionId;
      this.#enterCriticalDestination("create_element_to_discipline", this.#selectedDiscipline);
    } else if (
      screen === "create-discipline"
      && actionId.startsWith("create.select_discipline_")
    ) {
      this.#selectedDiscipline = actionId;
      this.#values["create.discipline"] = actionId;
      this.#enterCriticalDestination("create_discipline_to_hub");
    } else if (screen === "pause-menu" && actionId === "pause_menu.resume_game") {
      this.#enterCriticalDestination("pause_to_hub_resume");
    } else if (screen === "pause-menu" && actionId === "pause_menu.leave_game") {
      this.#enterCriticalDestination("pause_to_beta_notice");
    } else if (screen === "beta-notice" && actionId === "dialog.primary") {
      this.#enterCriticalDestination("beta_notice_to_main");
    } else if (screen === "main-menu-root" && actionId === "main_menu.play") {
      this.#enterCriticalDestination("main_to_profile_select");
    } else if (screen === "profile-save-select" && actionId === "main_menu.back") {
      this.#enterCriticalDestination("profile_select_to_main");
    } else if (
      screen === "profile-save-select"
      && actionId === "main_menu.resume_last_game"
    ) {
      this.#enterCriticalDestination("profile_select_resume_to_hub");
    } else {
      throw new Error(`${screen} has no measured critical action for ${actionId}`);
    }
  }

  #back(): void {
    const screen = this.#activeScreenId();
    if (screen === "beta_notice_first_boot" || screen === "beta-notice") {
      this.#activate("dialog.primary");
    } else if (screen === "profile-save-select") {
      this.#activate("main_menu.back");
    } else if (screen === "pause-menu") {
      this.#activate("pause_menu.resume_game");
    }
  }

  #enterCriticalDestination(edgeId: CriticalMenuEdgeId, preferredFocus?: string): void {
    const edge = this.#criticalEdges.get(edgeId);
    if (edge?.destinationLayoutId === undefined || edge.destinationLayoutId === null) {
      throw new Error(`critical edge ${edgeId} lost its destination fixture binding`);
    }
    if (edge.destination === "hub") {
      this.#enterHub(edge.destinationLayoutId);
    } else {
      this.#enterLayout(edge.destinationLayoutId, preferredFocus);
    }
  }

  #enterLayout(layoutId: string, preferredFocus?: string): void {
    const layout = this.#catalog.layouts.get(layoutId);
    if (layout === undefined) {
      throw new Error(`shell cannot enter missing aggregate layout ${layoutId}`);
    }
    this.#surface = { kind: "layout", layoutId };
    this.#nodes = buildFocusNodes(layout, this.#focusModel, this.#eligibility);
    this.#focus.enter(layoutId, this.#nodes, preferredFocus ?? this.#preferredFocus(layoutId));
    this.#emit();
  }

  #enterDialogComposite(compositeId: string): void {
    const composite = this.#requireComposite(compositeId);
    const actionNode: ShellFocusNode = {
      id: composite.actionId,
      enabled: true,
      rect: {
        x: composite.actionRect[0],
        y: composite.actionRect[1],
        width: composite.actionRect[2] - composite.actionRect[0],
        height: composite.actionRect[3] - composite.actionRect[1],
      },
      nativeRect: composite.actionRect,
      textEntry: false,
    };
    this.#surface = { kind: "dialog-composite", compositeId };
    this.#nodes = [actionNode];
    this.#focus.enter("beta-notice", this.#nodes, composite.actionId);
    this.#emit();
  }

  #enterHub(endpointLayoutId: string): void {
    if (!this.#catalog.transitionLayoutIds.includes(endpointLayoutId)) {
      throw new Error(`hub entry requires a measured transition endpoint, received ${endpointLayoutId}`);
    }
    this.#surface = { kind: "hub-stub", endpointLayoutId };
    this.#nodes = [];
    this.#emit();
  }

  #refreshNodes(): void {
    if (this.#surface.kind !== "layout") {
      return;
    }
    const layout = this.#requireLayout();
    this.#nodes = buildFocusNodes(layout, this.#focusModel, this.#eligibility);
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
    return undefined;
  }

  #activeScreenId(): string {
    if (this.#surface.kind === "layout") {
      return this.#surface.layoutId;
    }
    if (this.#surface.kind === "dialog-composite") {
      return this.#surface.compositeId;
    }
    return "hub";
  }

  #requireLayout(): MenuLayout {
    if (this.#surface.kind !== "layout") {
      throw new Error("shell action requires an active aggregate layout");
    }
    const layout = this.#catalog.layouts.get(this.#surface.layoutId);
    if (layout === undefined) {
      throw new Error(`shell lost aggregate layout ${this.#surface.layoutId}`);
    }
    return layout;
  }

  #requireComposite(compositeId: string): MenuDialogComposite {
    const composite = this.#catalog.dialogComposites.get(compositeId);
    if (composite === undefined) {
      throw new Error(`shell cannot enter missing semantic dialog composite ${compositeId}`);
    }
    return composite;
  }

  #emit(): void {
    const snapshot = this.snapshot();
    for (const listener of this.#listeners) {
      listener(snapshot);
    }
  }
}
