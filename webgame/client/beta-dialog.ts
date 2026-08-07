import type { ResolvedAsset } from "./manifest-assets.js";
import type { NativeRect } from "./menu-catalog.js";
import type {
  AtlasTextDraw,
  DrawCommand,
  RenderPlan,
  SolidDraw,
  SpriteDraw,
} from "./render-plan.js";

// ATC-preview beta-notice dialog reconstruction (superseded by shellfix #101).
//
// The native beta dialog's opaque panel background and multi-line body text
// never reached the capture pipeline — that draw path was unhooked, so the G11
// fixture holds only the dialog's chrome skeleton over a fully visible main
// menu (capture-method gap, routed to the #96 architecture docs). This layer
// rebuilds the missing panel and text from the native reference capture:
//   menu-reference-captures/beta-notice.png
//   sha256 a10f40d3ea5c72e8e6e634134ab845a6779f981e9d2bd61e6aa8b69a777c1126
// Every rectangle and color below is pixel-measured from that capture. Text
// widths come from the assetpack font advances scaled by per-font calibration
// constants measured on the capture (body 388px / 1767 raw, heading 284px /
// 1374 raw); the native engine compresses advances at these sizes, so glyph
// heights follow the captured-label convention instead of the raw aspect.

interface DialogAssets {
  resolve(id: string): ResolvedAsset;
}

const DIALOG_LAYOUT = "beta-notice";

// Screens whose native captures show the top-right version stamp. The
// game-settings Title screen verifiably omits it.
const STAMP_SCREENS: ReadonlySet<string> = new Set([
  "beta-notice",
  "main-menu-root",
  "profile-save-select",
]);

// Menu labels that sit fully under the opaque dialog panel. Natively they are
// invisible on this screen; the shell draws text above sprites, so they must
// not survive into the dialog plan. quit.1 sits outside the panel and stays.
const COVERED_MENU_TEXT: ReadonlySet<string> = new Set([
  "beta_notice.text.play.1",
  "beta_notice.text.explore_the.1",
  "beta_notice.text.dark_cloud.1",
  "beta_notice.text.settings.1",
  "beta_notice.text.hall_of_fame.1",
]);

const HEADING_FONT = "Fonts.308-349";
const BODY_FONT = "Fonts.216-307";

const WHITE = [1, 1, 1, 1] as const;
const YELLOW = [1, 1, 0, 1] as const;
const RULE_GOLD = [0.85, 0.75, 0.5, 1] as const;
const PANEL_BLACK = [0.008, 0.008, 0.01, 1] as const;

const PANEL: NativeRect = [516.5, 99.5, 1083.5, 800.5];
const CHAIN_ART = "UI.79";
const CHAIN_THICKNESS = 21;
const CHAIN_LENGTH = 108;
const LEATHER_ART = "UI.49";
const LEATHER_TILE = 264;
const LEATHER_REGION: NativeRect = [550, 133, 1051, 768];
const RULE_OUTER: NativeRect = [538, 120, 1062.5, 781];
const RULE_INNER: NativeRect = [547, 130, 1053.5, 771];
const RULE_THICKNESS = 3;

// The ambient static contract orders menu content at or below 87 and dialog
// chrome at 88 and above; the panel stack slots strictly between them.
const ORDER_BASE = 87.3;
const ORDER_CHAIN = 87.4;
const ORDER_LEATHER = 87.5;
const ORDER_RULE_OUTER = 87.6;
const ORDER_RULE_INNER = 87.7;

interface TextLine {
  readonly id: string;
  readonly fontId: string;
  readonly color: readonly [number, number, number, number] | null;
  readonly rect: NativeRect;
  readonly text: string;
}

// Native body copy transcribed verbatim from the reference capture, including
// the native "becompleted" typo and double spaces. Line pitch is exactly 17.
const TEXT_LINES: readonly TextLine[] = [
  { id: "heading", fontId: HEADING_FONT, color: WHITE, rect: [607, 189.2, 891, 205.8], text: "BETA VERSION V.0.72" },
  { id: "body.1", fontId: BODY_FONT, color: WHITE, rect: [605, 229.5, 971.261, 244.5], text: "This is an incomplete version of Solomon" },
  { id: "body.2", fontId: BODY_FONT, color: WHITE, rect: [605, 245.5, 647.16, 260.5], text: "Dark" },
  { id: "body.3", fontId: BODY_FONT, color: WHITE, rect: [605, 280.5, 722.037, 295.5], text: "It contains:" },
  { id: "list.1", fontId: BODY_FONT, color: YELLOW, rect: [622, 298.5, 761.654, 313.5], text: "ONE story level" },
  { id: "list.2", fontId: BODY_FONT, color: YELLOW, rect: [622, 315.5, 845.095, 330.5], text: "UNLIMITED survival play" },
  { id: "list.3", fontId: BODY_FONT, color: YELLOW, rect: [622, 332.5, 749.796, 347.5], text: "LIMITED items" },
  { id: "list.4", fontId: BODY_FONT, color: YELLOW, rect: [622, 349.5, 793.273, 364.5], text: "LIMITED Dark Cloud" },
  { id: "list.5", fontId: BODY_FONT, color: YELLOW, rect: [622, 366.5, 802.496, 381.5], text: "UNREFINED Dialogue" },
  { id: "list.6", fontId: BODY_FONT, color: YELLOW, rect: [622, 383.5, 834.994, 398.5], text: "PLACEHOLDER voice work" },
  { id: "list.7", fontId: BODY_FONT, color: YELLOW, rect: [622, 400.5, 877.593, 415.5], text: "UNFINISHED memorial screen" },
  { id: "body.4", fontId: BODY_FONT, color: WHITE, rect: [605, 438.5, 993, 453.5], text: "Sadly, this game has been derailed and will" },
  { id: "body.5", fontId: BODY_FONT, color: WHITE, rect: [605, 455.5, 929.102, 470.5], text: "not be becompleted.  Although it has" },
  { id: "body.6", fontId: BODY_FONT, color: WHITE, rect: [605, 472.5, 1011.445, 487.5], text: "passed preliminary testing, you will likely" },
  { id: "body.7", fontId: BODY_FONT, color: WHITE, rect: [605, 489.5, 789.229, 504.5], text: "find a glitch or two!" },
  { id: "body.8", fontId: BODY_FONT, color: WHITE, rect: [605, 526.5, 930.419, 541.5], text: "When closed, game will open a link to" },
  { id: "body.9", fontId: BODY_FONT, color: WHITE, rect: [605, 543.5, 980.484, 558.5], text: "www.raptisoft.com news.  Please read the" },
  { id: "body.10", fontId: BODY_FONT, color: WHITE, rect: [605, 560.5, 949.962, 575.5], text: "news there and vote on any greenlights" },
  { id: "body.11", fontId: BODY_FONT, color: WHITE, rect: [605, 577.5, 959.843, 592.5], text: "or take advantage of any special offers" },
  { id: "body.12", fontId: BODY_FONT, color: WHITE, rect: [605, 594.5, 908.9, 609.5], text: "that I have up!  I'd appreciate it!" },
  // OK label centered on the native slab center x=800 at its measured width.
  { id: "ok", fontId: HEADING_FONT, color: null, rect: [781.5, 669, 818.5, 686], text: "OK" },
];

// Top-right build stamp, right-aligned at its measured native edge.
const STAMP: TextLine = {
  id: "stamp",
  fontId: BODY_FONT,
  color: null,
  rect: [1496, 2.25, 1595, 16.75],
  text: "V.0.72BETA",
};

function textCommand(line: TextLine): AtlasTextDraw {
  return {
    kind: "atlas-text",
    elementId: `dialog.text.${line.id}`,
    layer: "screen-overlay",
    drawOrder: 0,
    rect: line.rect,
    unclippedRect: line.rect,
    fontId: line.fontId,
    text: line.text,
    ...(line.color === null ? {} : { color: line.color }),
  };
}

function solid(
  elementId: string,
  rect: NativeRect,
  drawOrder: number,
  color: readonly [number, number, number, number],
): SolidDraw {
  return {
    kind: "solid",
    elementId,
    layer: "screen-overlay",
    drawOrder,
    rect,
    unclippedRect: rect,
    colorTop: color,
    colorBottom: color,
  };
}

function ruleBars(idPrefix: string, rect: NativeRect, drawOrder: number): SolidDraw[] {
  const [left, top, right, bottom] = rect;
  return [
    solid(`${idPrefix}.top`, [left, top, right, top + RULE_THICKNESS], drawOrder, RULE_GOLD),
    solid(`${idPrefix}.bottom`, [left, bottom - RULE_THICKNESS, right, bottom], drawOrder, RULE_GOLD),
    solid(`${idPrefix}.left`, [left, top, left + RULE_THICKNESS, bottom], drawOrder, RULE_GOLD),
    solid(`${idPrefix}.right`, [right - RULE_THICKNESS, top, right, bottom], drawOrder, RULE_GOLD),
  ];
}

export class BetaNoticeDialog {
  readonly #assets: DialogAssets;

  public constructor(assets: DialogAssets) {
    this.#assets = assets;
  }

  public handles(layoutId: string): boolean {
    return layoutId === DIALOG_LAYOUT;
  }

  // Pure and time-free: prepare() reuses it directly for texture warm-up. On
  // the dialog screen it must run after the ambient layer's static reorder,
  // which is what assigns the <=87 / >=88 order bands the panel slots between.
  public apply(plan: RenderPlan): RenderPlan {
    const wantsStamp = STAMP_SCREENS.has(plan.layoutId);
    const wantsDialog = this.handles(plan.layoutId);
    if (!wantsStamp && !wantsDialog) {
      return plan;
    }
    const visual: DrawCommand[] = [];
    const text: DrawCommand[] = [];
    const focus: DrawCommand[] = [];
    for (const command of plan.commands) {
      if (wantsDialog && COVERED_MENU_TEXT.has(command.elementId)) {
        continue;
      }
      if (command.kind === "focus") {
        focus.push(command);
      } else if (command.kind === "atlas-text" || command.kind === "system-text") {
        text.push(command);
      } else {
        visual.push(command);
      }
    }
    if (wantsDialog) {
      visual.push(...this.#panelCommands());
      visual.sort((left, right) => left.drawOrder - right.drawOrder);
      text.push(...TEXT_LINES.map(textCommand));
    }
    if (wantsStamp) {
      text.push(textCommand(STAMP));
    }
    return { ...plan, commands: [...visual, ...text, ...focus] };
  }

  #sprite(elementId: string, artId: string, rect: NativeRect, unclippedRect: NativeRect, drawOrder: number): SpriteDraw {
    return {
      kind: "sprite",
      elementId,
      layer: "screen-overlay",
      drawOrder,
      rect,
      unclippedRect,
      asset: this.#assets.resolve(artId),
    };
  }

  #panelCommands(): DrawCommand[] {
    const commands: DrawCommand[] = [solid("dialog.panel.base", PANEL, ORDER_BASE, PANEL_BLACK)];
    commands.push(...this.#chainRing());
    commands.push(...this.#leatherTiles());
    commands.push(...ruleBars("dialog.rule.outer", RULE_OUTER, ORDER_RULE_OUTER));
    commands.push(...ruleBars("dialog.rule.inner", RULE_INNER, ORDER_RULE_INNER));
    return commands;
  }

  // Chain border flush with the panel edges: full-width horizontal runs, with
  // vertical runs spanning between them. The 21x108 source auto-quarter-turns
  // for the horizontal runs. Corner joins hide under the UI.107-110 stones.
  #chainRing(): SpriteDraw[] {
    const [left, top, right, bottom] = PANEL;
    const tiles: SpriteDraw[] = [];
    let index = 0;
    for (let x = left; x < right; x += CHAIN_LENGTH) {
      const clipRight = Math.min(x + CHAIN_LENGTH, right);
      tiles.push(this.#sprite(
        `dialog.chain.top.${index}`,
        CHAIN_ART,
        [x, top, clipRight, top + CHAIN_THICKNESS],
        [x, top, x + CHAIN_LENGTH, top + CHAIN_THICKNESS],
        ORDER_CHAIN,
      ));
      tiles.push(this.#sprite(
        `dialog.chain.bottom.${index}`,
        CHAIN_ART,
        [x, bottom - CHAIN_THICKNESS, clipRight, bottom],
        [x, bottom - CHAIN_THICKNESS, x + CHAIN_LENGTH, bottom],
        ORDER_CHAIN,
      ));
      index += 1;
    }
    index = 0;
    for (let y = top + CHAIN_THICKNESS; y < bottom - CHAIN_THICKNESS; y += CHAIN_LENGTH) {
      const clipBottom = Math.min(y + CHAIN_LENGTH, bottom - CHAIN_THICKNESS);
      tiles.push(this.#sprite(
        `dialog.chain.left.${index}`,
        CHAIN_ART,
        [left, y, left + CHAIN_THICKNESS, clipBottom],
        [left, y, left + CHAIN_THICKNESS, y + CHAIN_LENGTH],
        ORDER_CHAIN,
      ));
      tiles.push(this.#sprite(
        `dialog.chain.right.${index}`,
        CHAIN_ART,
        [right - CHAIN_THICKNESS, y, right, clipBottom],
        [right - CHAIN_THICKNESS, y, right, y + CHAIN_LENGTH],
        ORDER_CHAIN,
      ));
      index += 1;
    }
    return tiles;
  }

  #leatherTiles(): SpriteDraw[] {
    const [left, top, right, bottom] = LEATHER_REGION;
    const tiles: SpriteDraw[] = [];
    let index = 0;
    for (let y = top; y < bottom; y += LEATHER_TILE) {
      for (let x = left; x < right; x += LEATHER_TILE) {
        tiles.push(this.#sprite(
          `dialog.leather.${index}`,
          LEATHER_ART,
          [x, y, Math.min(x + LEATHER_TILE, right), Math.min(y + LEATHER_TILE, bottom)],
          [x, y, x + LEATHER_TILE, y + LEATHER_TILE],
          ORDER_LEATHER,
        ));
        index += 1;
      }
    }
    return tiles;
  }
}
