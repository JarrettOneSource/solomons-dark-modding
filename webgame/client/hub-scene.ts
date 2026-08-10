import type { NativeRect } from "./menu-catalog.js";
import type { ManifestAssets } from "./manifest-assets.js";
import {
  HUB_SCENE_GOLDEN,
  wizardPresentation,
  type SceneDraw,
} from "./hub-contracts.js";
import {
  G12_LAYER_ORDER,
  type DrawCommand,
  type RenderPlan,
  type SceneSpecialDraw,
  type ScreenQuad,
} from "./render-plan.js";

export interface HubSceneState {
  readonly player: Readonly<{ x: number; y: number }>;
  readonly heading: number;
  readonly moving: boolean;
  readonly presentationMilliseconds: number;
}

export interface HubSceneAssemblyDraw {
  readonly drawOrder: number;
  readonly spriteId: string;
  readonly layer: string;
  readonly semanticRole: string;
  readonly nativePhase: string;
  readonly drawKind: string;
  readonly worldTransform: SceneDraw["world_transform"];
  readonly tint: SceneDraw["tint"];
  readonly blend: SceneDraw["blend"];
  readonly resolvedScreenRect: SceneDraw["resolved_screen_rect"];
  readonly sortKey: unknown;
  readonly visible: boolean;
}

export interface HubSceneAssembly {
  readonly label: string;
  readonly layerOrder: typeof G12_LAYER_ORDER;
  readonly draws: readonly HubSceneAssemblyDraw[];
}

const BASE_PLAYER = (() => {
  const candidates = HUB_SCENE_GOLDEN.draws
    .map((draw) => draw.world_transform.object)
    .filter((actor): actor is NonNullable<typeof actor> => actor?.type_id === 1);
  if (candidates.length === 0) {
    throw new Error("G12 Courtyard draw list lost the player object witness");
  }
  const first = candidates[0];
  if (first === undefined || candidates.some((actor) => actor.x !== first.x || actor.y !== first.y)) {
    throw new Error("G12 Courtyard draw list ambiguously places the player at multiple coordinates");
  }
  return { x: first.x, y: first.y };
})();

const PLAYER_CLOTHES_ORDERS = [95, 96, 97, 98, 99, 100, 102, 103, 104, 105] as const;
const PLAYER_AURA_ORDERS = new Set([107, 108]);
const PLAYER_DRAW_INDICES = HUB_SCENE_GOLDEN.draws
  .filter((draw) => draw.world_transform.object?.type_id === 1)
  .map((draw) => draw.draw_order);
const VERIFIED_ASSETS = new WeakSet<ManifestAssets>();
const STATIC_COMMAND_CACHE = new WeakMap<
  ManifestAssets,
  { viewX: number; commands: readonly DrawCommand[] }
>();

if (PLAYER_DRAW_INDICES.length !== 14 || PLAYER_DRAW_INDICES[0] !== 95 || PLAYER_DRAW_INDICES.at(-1) !== 108) {
  throw new Error("G12 Courtyard player presentation no longer occupies the exact fourteen draws 95..108");
}

function presentationSpriteId(draw: SceneDraw, state: HubSceneState): string {
  if (draw.world_transform.object?.type_id !== 1) {
    return draw.sprite.id;
  }
  const presentation = wizardPresentation(
    state.heading,
    state.moving,
    state.presentationMilliseconds,
  );
  const clothesIndex = PLAYER_CLOTHES_ORDERS.indexOf(
    draw.draw_order as typeof PLAYER_CLOTHES_ORDERS[number],
  );
  if (clothesIndex >= 0) {
    return presentation.clothesSpriteIds[clothesIndex] ?? draw.sprite.id;
  }
  return PLAYER_AURA_ORDERS.has(draw.draw_order) ? presentation.auraSpriteId : draw.sprite.id;
}

function activeViewX(playerX: number): number {
  const [recordedX, , viewWidth] = HUB_SCENE_GOLDEN.camera.primary_view;
  // PROVISIONAL shell camera: preserve G12's recorded base view, then follow only
  // after the G14 intent-driven player has moved beyond a presentation margin.
  // Camera fidelity, like the deterministic movement integrator, belongs to P2.
  const margin = 260;
  const offsetFromRecordedPlayer = playerX - BASE_PLAYER.x;
  const worldWidth = HUB_SCENE_GOLDEN.camera.world_bounds[2];
  if (offsetFromRecordedPlayer < -margin) {
    return Math.max(0, recordedX + offsetFromRecordedPlayer + margin);
  }
  if (offsetFromRecordedPlayer > margin) {
    return Math.min(worldWidth - viewWidth, recordedX + offsetFromRecordedPlayer - margin);
  }
  return recordedX;
}

function screenQuad(draw: SceneDraw, state: HubSceneState): ScreenQuad {
  const quad = draw.world_transform.inverse_projected_quad;
  if (quad === null) {
    const [left, top, right, bottom] = draw.resolved_screen_rect;
    return [left, top, right, top, left, bottom, right, bottom];
  }
  const [, recordedViewY] = HUB_SCENE_GOLDEN.camera.primary_view;
  const viewX = activeViewX(state.player.x);
  const player = draw.world_transform.object?.type_id === 1;
  const playerOffsetX = player ? state.player.x - BASE_PLAYER.x : 0;
  const playerOffsetY = player ? state.player.y - BASE_PLAYER.y : 0;
  const scale = HUB_SCENE_GOLDEN.camera.scale;
  const points = Array.from({ length: 4 }, (_, index): readonly [number, number] => {
    const worldX = quad[index * 2];
    const worldY = quad[index * 2 + 1];
    if (worldX === undefined || worldY === undefined) {
      throw new Error(`G12 draw ${draw.draw_order} lost a projected quad corner`);
    }
    return [
      (worldX + playerOffsetX - viewX) * scale,
      (worldY + playerOffsetY - recordedViewY) * scale,
    ];
  });
  return [
    points[0]?.[0] ?? 0, points[0]?.[1] ?? 0,
    points[1]?.[0] ?? 0, points[1]?.[1] ?? 0,
    points[2]?.[0] ?? 0, points[2]?.[1] ?? 0,
    points[3]?.[0] ?? 0, points[3]?.[1] ?? 0,
  ];
}

function bounds(quad: ScreenQuad): NativeRect {
  const xs = [quad[0], quad[2], quad[4], quad[6]];
  const ys = [quad[1], quad[3], quad[5], quad[7]];
  return [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)];
}

function specialCommand(draw: SceneDraw, state: HubSceneState): SceneSpecialDraw {
  const quad = screenQuad(draw, state);
  const specialKind = draw.sprite.id === "native.framebuffer-clear"
    ? "framebuffer-clear"
    : "textured-quad";
  return {
    kind: "scene-special",
    specialKind,
    elementId: `hub.draw.${draw.draw_order}`,
    layer: draw.layer,
    drawOrder: draw.draw_order,
    rect: bounds(quad),
    unclippedRect: bounds(quad),
    screenQuad: quad,
    tint: [draw.tint.r, draw.tint.g, draw.tint.b, draw.tint.a],
    blend: draw.blend,
    sourceSpriteId: draw.sprite.id,
    nativeTransform: draw.world_transform,
    sortKey: draw.sort_key,
  };
}

export function assembleHubScene(): HubSceneAssembly {
  return {
    label: HUB_SCENE_GOLDEN.label,
    layerOrder: G12_LAYER_ORDER,
    draws: HUB_SCENE_GOLDEN.draws.map((draw) => ({
      drawOrder: draw.draw_order,
      spriteId: draw.sprite.id,
      layer: draw.layer,
      semanticRole: draw.semantic_role,
      nativePhase: draw.native_phase,
      drawKind: draw.draw_kind,
      worldTransform: draw.world_transform,
      tint: draw.tint,
      blend: draw.blend,
      resolvedScreenRect: draw.resolved_screen_rect,
      sortKey: draw.sort_key,
      visible: draw.visible,
    })),
  };
}

export function buildHubScenePlan(
  assets: ManifestAssets,
  state: HubSceneState,
  overlayCommands: readonly DrawCommand[] = [],
  layoutId = "hub.courtyard",
): RenderPlan {
  if (!VERIFIED_ASSETS.has(assets)) {
    assets.assertHubSceneAssets(HUB_SCENE_GOLDEN.draws);
    VERIFIED_ASSETS.add(assets);
  }
  const buildCommand = (draw: SceneDraw): DrawCommand => {
    const spriteId = presentationSpriteId(draw, state);
    const special = assets.manifest.specialDraws[spriteId];
    if (special !== undefined) {
      assets.special(spriteId);
      return specialCommand({ ...draw, sprite: { ...draw.sprite, id: spriteId } }, state);
    }
    const quad = screenQuad(draw, state);
    return {
      kind: "scene-sprite" as const,
      elementId: `hub.draw.${draw.draw_order}`,
      layer: draw.layer,
      drawOrder: draw.draw_order,
      rect: bounds(quad),
      unclippedRect: bounds(quad),
      screenQuad: quad,
      tint: [draw.tint.r, draw.tint.g, draw.tint.b, draw.tint.a] as const,
      blend: draw.blend,
      asset: assets.resolve(spriteId),
      sourceSpriteId: spriteId,
      nativeTransform: draw.world_transform,
      sortKey: draw.sort_key,
    };
  };
  const viewX = activeViewX(state.player.x);
  let cached = STATIC_COMMAND_CACHE.get(assets);
  if (cached === undefined || cached.viewX !== viewX) {
    cached = {
      viewX,
      commands: HUB_SCENE_GOLDEN.draws.map(buildCommand),
    };
    STATIC_COMMAND_CACHE.set(assets, cached);
  }
  const commands = [...cached.commands];
  for (const drawIndex of PLAYER_DRAW_INDICES) {
    const draw = HUB_SCENE_GOLDEN.draws[drawIndex];
    if (draw === undefined || draw.world_transform.object?.type_id !== 1) {
      throw new Error(`G12 player draw ${drawIndex} disappeared from the dynamic presentation seam`);
    }
    commands[drawIndex] = buildCommand(draw);
  }
  return {
    layoutId,
    nativeViewport: [1600, 900],
    layerOrder: G12_LAYER_ORDER,
    clearColor: [0, 0, 0, 1],
    elements: [],
    commands: [...commands, ...overlayCommands],
  };
}

export const HUB_BASE_PLAYER_POSITION = BASE_PLAYER;
