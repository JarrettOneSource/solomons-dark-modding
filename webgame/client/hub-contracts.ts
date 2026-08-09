import economyGoldenJson from "../../tests/fixtures/webgame/hub-economy-goldens.json" with { type: "json" };
import sceneGoldenJson from "../../tests/fixtures/webgame/scene-composition-goldens.json" with { type: "json" };
import sessionGoldenJson from "../../tests/fixtures/webgame/session-flow-goldens.json" with { type: "json" };

import type { G12Layer } from "./render-plan.js";

type JsonObject = Record<string, unknown>;

export interface SceneTint {
  readonly r: number;
  readonly g: number;
  readonly b: number;
  readonly a: number;
}

export interface SceneDraw {
  readonly draw_order: number;
  readonly layer: G12Layer;
  readonly semantic_role: string;
  readonly native_phase: string;
  readonly draw_kind: string;
  readonly sprite: {
    readonly id: string;
    readonly atlas: string;
    readonly index: number | null;
    readonly resolution: string;
  };
  readonly world_transform: {
    readonly space: "world" | "screen";
    readonly kind: string;
    readonly submitted_position: readonly [number, number];
    readonly matrix: readonly number[] | null;
    readonly inverse_projected_quad: readonly number[] | null;
    readonly object: {
      readonly type_id: number;
      readonly x: number;
      readonly y: number;
    } | null;
  };
  readonly tint: SceneTint;
  readonly blend: {
    readonly enabled: boolean;
    readonly source: number;
    readonly destination: number;
    readonly operation: number;
  };
  readonly resolved_screen_rect: readonly [number, number, number, number];
  readonly visible: boolean;
  readonly sort_key: unknown;
}

export interface HubSceneGolden {
  readonly label: "hub_camera_1000_375_final";
  readonly camera: {
    readonly scale: number;
    readonly world_bounds: readonly [number, number, number, number];
    readonly primary_view: readonly [number, number, number, number];
  };
  readonly epsilon: {
    readonly screen_pixels: number;
    readonly world_units: number;
  };
  readonly draws: readonly SceneDraw[];
}

export interface HubActorGolden {
  readonly class: string;
  readonly radius: number;
  readonly type_id: number;
  readonly world_slot: number;
  readonly x: number;
  readonly y: number;
  readonly eulogy_index?: number;
}

export interface HubRegionGolden {
  readonly name: string;
  readonly region_index: number;
  readonly region_type_id: number;
  readonly actor_count: number;
  readonly actors: readonly HubActorGolden[];
}

export interface ShopOfferGolden {
  readonly type_id: number;
  readonly variant_id?: number;
  readonly selector?: number;
  readonly recipe_uid?: number;
  readonly quantity: number;
  readonly price: number;
}

export interface HubEconomyGolden {
  readonly regions: readonly HubRegionGolden[];
  readonly freshGold: number;
  readonly fomentiusStockCount: number;
  readonly fomentius: readonly ShopOfferGolden[];
  readonly hagathaStockCount: number;
  readonly hagatha: readonly ShopOfferGolden[];
  readonly dowsingFee: number;
  readonly shlorio: readonly ShopOfferGolden[];
}

export interface SessionEdgeGolden {
  readonly state: string;
  readonly edge: string;
  readonly destination: string;
  readonly trigger: string;
}

export interface SessionTimelineGolden {
  readonly edge: string;
  readonly source: string;
  readonly destination: string;
  readonly ordered_lifecycle_steps: readonly JsonObject[];
}

export interface SessionFlowGolden {
  readonly states: readonly string[];
  readonly edges: readonly SessionEdgeGolden[];
  readonly timelines: readonly SessionTimelineGolden[];
}

export const G12_LAYER_ORDER = [
  "framebuffer-clear",
  "scene-underlay",
  "world-sorted",
  "scene-overdraw",
  "screen-overlay",
] as const;

function object(value: unknown, claim: string): JsonObject {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(claim);
  }
  return value as JsonObject;
}

function array(value: unknown, claim: string): unknown[] {
  if (!Array.isArray(value)) {
    throw new Error(claim);
  }
  return value;
}

function string(value: unknown, claim: string): string {
  if (typeof value !== "string") {
    throw new Error(claim);
  }
  return value;
}

function number(value: unknown, claim: string): number {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new Error(claim);
  }
  return value;
}

function integer(value: unknown, claim: string): number {
  const result = number(value, claim);
  if (!Number.isSafeInteger(result)) {
    throw new Error(claim);
  }
  return result;
}

function tuple2(value: unknown, claim: string): readonly [number, number] {
  const values = array(value, claim);
  if (values.length !== 2) {
    throw new Error(claim);
  }
  return [number(values[0], claim), number(values[1], claim)];
}

function tuple4(value: unknown, claim: string): readonly [number, number, number, number] {
  const values = array(value, claim);
  if (values.length !== 4) {
    throw new Error(claim);
  }
  return [
    number(values[0], claim),
    number(values[1], claim),
    number(values[2], claim),
    number(values[3], claim),
  ];
}

function unique(values: readonly string[], claim: string): void {
  if (new Set(values).size !== values.length) {
    throw new Error(claim);
  }
}

export function parseHubSceneGolden(value: unknown): HubSceneGolden {
  const root = object(value, "G12 scene golden must be an object");
  if (root.schema !== "solomon-dark-scene-composition-goldens-v1") {
    throw new Error("G12 scene golden lost its versioned schema");
  }
  const layerOrder = array(root.layer_order, "G12 scene golden lost its physical layer order");
  if (layerOrder.length !== G12_LAYER_ORDER.length
    || layerOrder.some((layer, index) => layer !== G12_LAYER_ORDER[index])) {
    throw new Error("G12 scene golden no longer uses the five exact physical layers");
  }
  const captures = array(root.captures, "G12 scene golden lost its capture census");
  const labels = captures.map((capture) => string(
    object(object(capture, "G12 capture must be an object").header, "G12 capture header is absent").label,
    "G12 capture label is absent",
  ));
  unique(labels, "G12 scene golden contains ambiguous duplicate capture labels");
  const index = labels.indexOf("hub_camera_1000_375_final");
  if (index < 0) {
    throw new Error("G12 scene golden lost the canonical Courtyard camera capture");
  }
  const capture = object(captures[index], "G12 canonical Courtyard capture is malformed");
  const header = object(capture.header, "G12 canonical Courtyard header is malformed");
  const validation = object(header.validation, "G12 canonical Courtyard validation is absent");
  const camera = object(header.camera, "G12 canonical Courtyard camera is absent");
  const epsilon = object(header.epsilon, "G12 canonical Courtyard tolerance is absent");
  const rawDraws = array(capture.draws, "G12 canonical Courtyard draw list is absent");
  if (integer(validation.draw_count, "G12 Courtyard draw-count witness is malformed") !== 1319
      || rawDraws.length !== 1319) {
    throw new Error("G12 canonical Courtyard draw list no longer contains exactly 1,319 draws");
  }
  const draws = rawDraws.map((raw, indexValue): SceneDraw => {
    const draw = object(raw, `G12 Courtyard draw ${indexValue} is malformed`);
    const order = integer(draw.draw_order, `G12 Courtyard draw ${indexValue} lost its order`);
    if (order !== indexValue) {
      throw new Error(`G12 Courtyard draw ${indexValue} no longer has exact draw order ${indexValue}`);
    }
    const layer = string(draw.layer, `G12 Courtyard draw ${indexValue} lost its layer`);
    if (!(G12_LAYER_ORDER as readonly string[]).includes(layer)) {
      throw new Error(`G12 Courtyard draw ${indexValue} names an unknown physical layer ${layer}`);
    }
    const sprite = object(draw.sprite, `G12 Courtyard draw ${indexValue} lost its sprite record`);
    const transform = object(draw.world_transform, `G12 Courtyard draw ${indexValue} lost its transform`);
    const submitted = tuple2(
      transform.submitted_position,
      `G12 Courtyard draw ${indexValue} lost its submitted position`,
    );
    const rawQuad = transform.inverse_projected_quad;
    const quad = rawQuad === null
      ? null
      : array(rawQuad, `G12 Courtyard draw ${indexValue} has a malformed inverse quad`).map((entry) => (
        number(entry, `G12 Courtyard draw ${indexValue} has a non-numeric inverse quad`)
      ));
    if (quad !== null && quad.length !== 8) {
      throw new Error(`G12 Courtyard draw ${indexValue} no longer has a four-corner inverse quad`);
    }
    const rawObject = transform.object;
    let transformObject: SceneDraw["world_transform"]["object"] = null;
    if (rawObject !== null) {
      const actor = object(rawObject, `G12 Courtyard draw ${indexValue} has a malformed object key`);
      transformObject = {
        type_id: integer(actor.type_id, `G12 Courtyard draw ${indexValue} lost object type`),
        x: number(actor.x, `G12 Courtyard draw ${indexValue} lost object x`),
        y: number(actor.y, `G12 Courtyard draw ${indexValue} lost object y`),
      };
    }
    const tint = object(draw.tint, `G12 Courtyard draw ${indexValue} lost tint`);
    const blend = object(draw.blend, `G12 Courtyard draw ${indexValue} lost blend state`);
    const spriteIndex = sprite.index;
    if (spriteIndex !== null && !Number.isSafeInteger(spriteIndex)) {
      throw new Error(`G12 Courtyard draw ${indexValue} has a malformed sprite index`);
    }
    return {
      draw_order: order,
      layer: layer as G12Layer,
      semantic_role: string(draw.semantic_role, `G12 Courtyard draw ${indexValue} lost semantic role`),
      native_phase: string(draw.native_phase, `G12 Courtyard draw ${indexValue} lost native phase`),
      draw_kind: string(draw.draw_kind, `G12 Courtyard draw ${indexValue} lost draw kind`),
      sprite: {
        id: string(sprite.id, `G12 Courtyard draw ${indexValue} lost sprite id`),
        atlas: string(sprite.atlas, `G12 Courtyard draw ${indexValue} lost sprite atlas`),
        index: spriteIndex as number | null,
        resolution: string(sprite.resolution, `G12 Courtyard draw ${indexValue} lost sprite resolution`),
      },
      world_transform: {
        space: string(transform.space, `G12 Courtyard draw ${indexValue} lost transform space`) as "world" | "screen",
        kind: string(transform.kind, `G12 Courtyard draw ${indexValue} lost transform kind`),
        submitted_position: submitted,
        matrix: transform.matrix === null
          ? null
          : array(transform.matrix, `G12 Courtyard draw ${indexValue} has malformed matrix`).map((entry) => (
            number(entry, `G12 Courtyard draw ${indexValue} has non-numeric matrix`)
          )),
        inverse_projected_quad: quad,
        object: transformObject,
      },
      tint: {
        r: number(tint.r, `G12 Courtyard draw ${indexValue} lost red tint`),
        g: number(tint.g, `G12 Courtyard draw ${indexValue} lost green tint`),
        b: number(tint.b, `G12 Courtyard draw ${indexValue} lost blue tint`),
        a: number(tint.a, `G12 Courtyard draw ${indexValue} lost alpha tint`),
      },
      blend: {
        enabled: Boolean(blend.enabled),
        source: integer(blend.source, `G12 Courtyard draw ${indexValue} lost source blend`),
        destination: integer(blend.destination, `G12 Courtyard draw ${indexValue} lost destination blend`),
        operation: integer(blend.operation, `G12 Courtyard draw ${indexValue} lost blend operation`),
      },
      resolved_screen_rect: tuple4(
        draw.resolved_screen_rect,
        `G12 Courtyard draw ${indexValue} lost its resolved screen rectangle`,
      ),
      visible: Boolean(draw.visible),
      sort_key: draw.sort_key,
    };
  });
  return {
    label: "hub_camera_1000_375_final",
    camera: {
      scale: number(camera.scale, "G12 Courtyard camera scale is malformed"),
      world_bounds: tuple4(camera.world_bounds, "G12 Courtyard world bounds are malformed"),
      primary_view: tuple4(camera.primary_view, "G12 Courtyard primary view is malformed"),
    },
    epsilon: {
      screen_pixels: number(epsilon.screen_pixels, "G12 screen epsilon is malformed"),
      world_units: number(epsilon.world_units, "G12 world epsilon is malformed"),
    },
    draws,
  };
}

function parseOffer(value: unknown, claim: string): ShopOfferGolden {
  const offer = object(value, claim);
  const optionalInteger = (key: string): number | undefined => (
    offer[key] === undefined ? undefined : integer(offer[key], claim)
  );
  return {
    type_id: integer(offer.type_id, claim),
    ...(offer.variant_id === undefined ? {} : { variant_id: optionalInteger("variant_id") as number }),
    ...(offer.selector === undefined ? {} : { selector: optionalInteger("selector") as number }),
    ...(offer.recipe_uid === undefined ? {} : { recipe_uid: optionalInteger("recipe_uid") as number }),
    quantity: offer.quantity === undefined ? 1 : integer(offer.quantity, claim),
    price: integer(offer.price, claim),
  };
}

export function parseHubEconomyGolden(value: unknown): HubEconomyGolden {
  const root = object(value, "G8 hub economy golden must be an object");
  if (root.schema !== "solomon-dark-native-hub-economy-goldens-v1") {
    throw new Error("G8 hub economy golden lost its versioned schema");
  }
  const census = object(root.hub_entity_census, "G8 hub entity census is absent");
  const rawRegions = array(census.regions, "G8 hub region census is absent");
  const regions = rawRegions.map((valueRegion, regionIndex): HubRegionGolden => {
    const region = object(valueRegion, `G8 hub region ${regionIndex} is malformed`);
    const actors = array(region.actors, `G8 hub region ${regionIndex} lost its actor census`).map(
      (valueActor, actorIndex): HubActorGolden => {
        const actor = object(valueActor, `G8 hub actor ${regionIndex}/${actorIndex} is malformed`);
        const eulogy = actor.eulogy_index;
        return {
          class: string(actor.class, `G8 hub actor ${regionIndex}/${actorIndex} lost its class`),
          radius: number(actor.radius, `G8 hub actor ${regionIndex}/${actorIndex} lost its radius`),
          type_id: integer(actor.type_id, `G8 hub actor ${regionIndex}/${actorIndex} lost its type`),
          world_slot: integer(actor.world_slot, `G8 hub actor ${regionIndex}/${actorIndex} lost its slot`),
          x: number(actor.x, `G8 hub actor ${regionIndex}/${actorIndex} lost x`),
          y: number(actor.y, `G8 hub actor ${regionIndex}/${actorIndex} lost y`),
          ...(eulogy === undefined
            ? {}
            : { eulogy_index: integer(eulogy, `G8 hub actor ${regionIndex}/${actorIndex} lost eulogy index`) }),
        };
      },
    );
    const actorCount = integer(region.actor_count, `G8 hub region ${regionIndex} lost actor count`);
    if (actors.length !== actorCount) {
      throw new Error(`G8 hub region ${regionIndex} actor census no longer matches its recorded count`);
    }
    return {
      name: string(region.name, `G8 hub region ${regionIndex} lost its name`),
      region_index: integer(region.region_index, `G8 hub region ${regionIndex} lost its index`),
      region_type_id: integer(region.region_type_id, `G8 hub region ${regionIndex} lost its type`),
      actor_count: actorCount,
      actors,
    };
  });
  if (regions.length !== 5
      || regions.some((region, index) => region.region_index !== index)
      || regions.map((region) => region.name).join("|") !== "Courtyard|Mortuary|Library|StoreRoom|Office") {
    throw new Error("G8 hub no longer has the exact five ordered native regions");
  }
  const captures = array(root.trader_captures, "G8 trader captures are absent");
  const freshCandidates = captures.filter((capture) => (
    object(object(capture, "G8 trader capture is malformed").progression_state, "G8 progression state is absent").id === "fresh"
  ));
  if (freshCandidates.length !== 1) {
    throw new Error("G8 pinned inventory cannot choose unambiguously between fresh trader captures");
  }
  const fresh = object(freshCandidates[0], "G8 fresh trader capture is malformed");
  const fomentius = object(fresh.fomentius, "G8 Fomentius capture is absent");
  const hagatha = object(fresh.hagatha, "G8 Hagatha capture is absent");
  const rolls = array(fresh.shlorio_dowsing_rolls, "G8 Shlorio capture is absent");
  if (rolls.length < 1) {
    throw new Error("G8 pinned Shlorio inventory has no first-roll witness");
  }
  const firstRoll = object(rolls[0], "G8 first Shlorio roll is malformed");
  const fomentiusOffers = array(fomentius.offers, "G8 Fomentius offers are absent").map(
    (offer, index) => parseOffer(offer, `G8 Fomentius offer ${index} is malformed`),
  );
  const hagathaOffers = array(hagatha.offers, "G8 Hagatha offers are absent").map(
    (offer, index) => parseOffer(offer, `G8 Hagatha offer ${index} is malformed`),
  );
  const shlorioOffers = array(firstRoll.offers, "G8 Shlorio first-roll offers are absent").map(
    (offer, index) => parseOffer(offer, `G8 Shlorio offer ${index} is malformed`),
  );
  if (fomentiusOffers.length !== 6 || integer(fomentius.stock_count, "G8 Fomentius stock count is malformed") !== 12) {
    throw new Error("G8 pinned Fomentius inventory no longer has six offer stacks and twelve items");
  }
  if (hagathaOffers.length !== 27 || integer(hagatha.stock_count, "G8 Hagatha stock count is malformed") !== 27) {
    throw new Error("G8 pinned Hagatha inventory no longer has selectors 0..27 except 8");
  }
  return {
    regions,
    freshGold: integer(fresh.profile_gold, "G8 fresh profile gold is malformed"),
    fomentiusStockCount: integer(fomentius.stock_count, "G8 Fomentius stock count is malformed"),
    fomentius: fomentiusOffers,
    hagathaStockCount: integer(hagatha.stock_count, "G8 Hagatha stock count is malformed"),
    hagatha: hagathaOffers,
    dowsingFee: integer(fresh.dowsing_cost_before_first_roll, "G8 initial Dowsing fee is malformed"),
    shlorio: shlorioOffers,
  };
}

export function parseSessionFlowGolden(value: unknown): SessionFlowGolden {
  const root = object(value, "G13 session-flow golden must be an object");
  if (root.schema_version !== 1) {
    throw new Error("G13 session-flow golden lost its versioned schema");
  }
  const graph = object(root.transition_graph, "G13 transition graph is absent");
  const states = array(graph.states, "G13 state census is absent").map((raw, index) => (
    string(object(raw, `G13 state ${index} is malformed`).state, `G13 state ${index} lost its semantic id`)
  ));
  if (states.length !== 12) {
    throw new Error("G13 session graph no longer contains exactly twelve stable states");
  }
  unique(states, "G13 session graph contains ambiguous duplicate stable states");
  const edges = array(graph.edges, "G13 edge graph is absent").map((raw, index): SessionEdgeGolden => {
    const edge = object(raw, `G13 edge ${index} is malformed`);
    return {
      state: string(edge.state, `G13 edge ${index} lost its source`),
      edge: string(edge.edge, `G13 edge ${index} lost its name`),
      destination: string(edge.destination, `G13 edge ${index} lost its destination`),
      trigger: string(edge.trigger, `G13 edge ${index} lost its trigger`),
    };
  });
  if (edges.length !== 23) {
    throw new Error("G13 session graph no longer contains exactly twenty-three legal edges");
  }
  unique(
    edges.map((edge) => `${edge.state}\0${edge.edge}\0${edge.destination}`),
    "G13 session graph contains an ambiguous duplicate legal edge",
  );
  for (const edge of edges) {
    if (!states.includes(edge.state) || !states.includes(edge.destination)) {
      throw new Error(`G13 edge ${edge.edge} no longer joins two recorded stable states`);
    }
  }
  const timeline = object(root.session_timeline, "G13 session timeline is absent");
  const timelines = array(timeline.transitions, "G13 recorded transitions are absent").map(
    (raw, index): SessionTimelineGolden => {
      const transition = object(raw, `G13 timeline ${index} is malformed`);
      const steps = array(
        transition.ordered_lifecycle_steps,
        `G13 timeline ${index} lost ordered lifecycle steps`,
      ).map((step) => object(step, `G13 timeline ${index} has a malformed lifecycle step`));
      if (steps.length === 0) {
        throw new Error(`G13 timeline ${index} contains no lifecycle evidence`);
      }
      return {
        edge: string(transition.edge, `G13 timeline ${index} lost edge name`),
        source: string(transition.source, `G13 timeline ${index} lost source`),
        destination: string(transition.destination, `G13 timeline ${index} lost destination`),
        ordered_lifecycle_steps: steps,
      };
    },
  );
  return { states, edges, timelines };
}

export function facing24(heading: number): number {
  if (!Number.isFinite(heading)) {
    throw new Error("G4 wizard facing requires a finite heading");
  }
  let facing = Math.trunc(Math.trunc(heading) + 7) / 15;
  facing = Math.trunc(facing);
  if (facing >= 24) {
    facing -= 24;
  }
  if (facing < 0 || facing >= 24) {
    throw new Error("G4 wizard facing input must stay in the native [0,360) heading domain");
  }
  return facing;
}

export interface WizardPresentationFrame {
  readonly locomotion: "idle" | "walk";
  readonly facing: number;
  readonly clothesSpriteIds: readonly string[];
  readonly auraSpriteId: string;
}

const CLOTHES_BANKS = [868, 1228, 1612, 2428, 2020, 2836, 3244, 3484, 316, 412] as const;
const WIZARD_AURA_IDS = Array.from({ length: 12 }, (_, index) => `BadGuys.${255 + index}`);

export function wizardAuraSpriteId(presentationMilliseconds: number): string {
  const auraPhase = Math.floor(Math.max(0, presentationMilliseconds) / 50) % WIZARD_AURA_IDS.length;
  const result = WIZARD_AURA_IDS[auraPhase];
  if (result === undefined) {
    throw new Error("G4 wizard aura selector left its exact twelve-frame list");
  }
  return result;
}

export function wizardPresentation(
  heading: number,
  moving: boolean,
  presentationMilliseconds: number,
): WizardPresentationFrame {
  const facing = facing24(heading);
  // G4's idle_walk_idle recording selects the second 24-facing locomotion
  // bank for the first two equipment lanes when the fixed-tick walk phase
  // crosses one. P1 advances this as presentation state only; it is not the
  // P2 deterministic movement integrator and carries no movement-fidelity
  // claim.
  const walkBankOffset = moving && Math.floor(Math.max(0, presentationMilliseconds) / 100) % 2 === 1
    ? 24
    : 0;
  return {
    locomotion: moving ? "walk" : "idle",
    facing,
    clothesSpriteIds: CLOTHES_BANKS.map((base, index) => (
      `Clothes.${base + facing + (index < 2 ? walkBankOffset : 0)}`
    )),
    auraSpriteId: wizardAuraSpriteId(presentationMilliseconds),
  };
}

export const HUB_SCENE_GOLDEN = parseHubSceneGolden(sceneGoldenJson);
export const HUB_ECONOMY_GOLDEN = parseHubEconomyGolden(economyGoldenJson);
export const SESSION_FLOW_GOLDEN = parseSessionFlowGolden(sessionGoldenJson);

// The landed G4 fixture contains native non-finite diagnostic scalars and is
// intentionally consumed by the Node conformance replay rather than Vite's
// strict JSON module parser. These names bind this presentation selector to
// the two normative captures without copying either recording into client/.
export const G4_PRESENTATION_WITNESSES = ["idle", "idle_walk_idle"] as const;
