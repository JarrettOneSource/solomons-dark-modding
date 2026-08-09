import { HUB_ECONOMY_GOLDEN, type HubActorGolden, type ShopOfferGolden } from "./hub-contracts.js";

export type HubRegionId = "courtyard" | "mortuary" | "library" | "storeroom" | "office";
export type HubServiceId =
  | "useful-thyngs"
  | "perk-shop"
  | "boast"
  | "inventory"
  | "spells"
  | "books"
  | "dowsing";

export interface TalkPage {
  readonly id: string;
  readonly text: string;
}

export interface HubNpc {
  readonly id: string;
  readonly name: string;
  readonly region: HubRegionId;
  readonly actorClass: string;
  readonly typeId: number;
  readonly worldSlot: number;
  readonly x: number;
  readonly y: number;
  readonly radius: number;
  readonly eulogyIndex?: number;
  readonly pages: readonly TalkPage[];
  readonly service?: HubServiceId;
}

export interface HubPortal {
  readonly id: string;
  readonly name: string;
  readonly region: HubRegionId;
  readonly x: number;
  readonly y: number;
  readonly destination?: HubRegionId;
  readonly kind: "portal" | "map-picker";
}

export interface ShopOffer extends ShopOfferGolden {
  readonly id: string;
  readonly name: string;
}

const REGION_BY_NATIVE_NAME: Readonly<Record<string, HubRegionId>> = {
  Courtyard: "courtyard",
  Mortuary: "mortuary",
  Library: "library",
  StoreRoom: "storeroom",
  Office: "office",
};

function actor(region: HubRegionId, actorClass: string, worldSlot?: number): HubActorGolden {
  const candidates = HUB_ECONOMY_GOLDEN.regions.flatMap((entry) => {
    if (REGION_BY_NATIVE_NAME[entry.name] !== region) {
      return [];
    }
    return entry.actors.filter((candidate) => (
      candidate.class === actorClass && (worldSlot === undefined || candidate.world_slot === worldSlot)
    ));
  });
  if (candidates.length !== 1) {
    throw new Error(
      `G8 NPC lookup for ${region}/${actorClass}/${worldSlot ?? "any"} is ambiguous (${candidates.length} candidates)`,
    );
  }
  const result = candidates[0];
  if (result === undefined) {
    throw new Error(`G8 NPC lookup lost ${region}/${actorClass}`);
  }
  return result;
}

function npc(
  id: string,
  name: string,
  region: HubRegionId,
  actorClass: string,
  pages: readonly TalkPage[],
  options: Readonly<{ worldSlot?: number; service?: HubServiceId }> = {},
): HubNpc {
  const native = actor(region, actorClass, options.worldSlot);
  return {
    id,
    name,
    region,
    actorClass,
    typeId: native.type_id,
    worldSlot: native.world_slot,
    x: native.x,
    y: native.y,
    radius: native.radius,
    ...(native.eulogy_index === undefined ? {} : { eulogyIndex: native.eulogy_index }),
    pages,
    ...(options.service === undefined ? {} : { service: options.service }),
  };
}

const courtyardNpcs: readonly HubNpc[] = [
  npc("hub.npc.hagatha", "Hagatha", "courtyard", "PerkWitch", [
    { id: "WITCH_INTRO", text: "Charms, curses, and bargains. Choose with care." },
    { id: "WITCH_Q", text: "Would you like to buy Charms and Curses?" },
  ], { service: "perk-shop" }),
  npc("hub.npc.fomentius", "Fomentius", "courtyard", "PotionGuy", [
    { id: "POTIONGUY_INTRO", text: "Welcome to Useful Thyngs. Potions, sacks, and dyes are in stock." },
  ], { service: "useful-thyngs" }),
  npc("hub.npc.annalist", "The Annalist", "courtyard", "Annalist", [
    { id: "ANNAL_INTRO", text: "Your deeds are recorded. Tell me what should be remembered." },
  ], { service: "boast" }),
  npc("hub.npc.luthacus", "Luthacus", "courtyard", "ItemsGuy", [
    { id: "SCAVENGER_INTRO", text: "Your private stores are safe. Take stock before you leave." },
  ], { service: "inventory" }),
  npc("hub.npc.tyrannia", "Tyrannia", "courtyard", "Tyrannia", [
    { id: "ENFORCER_INTRO", text: "The Courtyard is secure. Do not test my patience." },
  ]),
  npc("hub.npc.teacher", "The Teacher", "courtyard", "Teacher", [
    { id: "TEACHER_INTRO", text: "Control comes before power." },
    { id: "TEACHER_Q", text: "Review the spell disciplines?" },
  ], { service: "spells" }),
];

const memorator = npc("hub.npc.memorator", "The Memorator", "mortuary", "Memorator", [
  { id: "MEMORATOR_INTRO", text: "The Mortuary keeps every name the Dark has taken." },
  { id: "MEMORATOR_Q1", text: "The portraits remember what the living forget." },
  { id: "MEMORATOR_Q2", text: "Pay your respects, then return to the Courtyard." },
]);

const paintingNpcs: readonly HubNpc[] = HUB_ECONOMY_GOLDEN.regions
  .find((region) => region.name === "Mortuary")
  ?.actors.filter((candidate) => candidate.class === "Painting")
  .map((native) => {
    if (native.eulogy_index === undefined) {
      throw new Error(`G8 Painting slot ${native.world_slot} lost its eulogy index`);
    }
    return npc(
      `hub.painting.${native.eulogy_index}`,
      `Memorial ${native.eulogy_index}`,
      "mortuary",
      "Painting",
      [{
        id: `SAY_EULOGY_INDEX[${native.eulogy_index}]`,
        text: `Eulogy ${native.eulogy_index}: a life held here against oblivion.`,
      }],
      { worldSlot: native.world_slot },
    );
  }) ?? [];

if (paintingNpcs.length !== 10 || !paintingNpcs.some((entry) => entry.eulogyIndex === 100)) {
  throw new Error("G8 Mortuary no longer exposes all ten Painting talk targets including eulogy 100");
}

const libraryNpcs: readonly HubNpc[] = [
  npc("hub.npc.librarian", "The Librarian", "library", "Librarian", [
    { id: "LIBRARIAN_INTRO", text: "The shelves hold what the College has learned." },
  ], { service: "books" }),
  npc("hub.npc.shlorio", "Shlorio", "library", "Dowser", [
    { id: "DOWSER_INTRO", text: "I can divine useful relics from the Dark." },
    { id: "DOWSER_Q", text: "The pinned first reading costs the recorded Dowsing fee." },
  ], { service: "dowsing" }),
];

const officeNpcs: readonly HubNpc[] = [
  npc("hub.npc.arch-chancellor", "The Arch Chancellor", "office", "ArchChancellor", [
    { id: "ARCH_INTRO", text: "The College endures because its rules endure." },
    { id: "ARCH_Q", text: "Return when your work in the Dark is finished." },
  ]),
];

export const HUB_NPCS: readonly HubNpc[] = [
  ...courtyardNpcs,
  memorator,
  ...paintingNpcs,
  ...libraryNpcs,
  ...officeNpcs,
];

const npcIds = HUB_NPCS.map((entry) => entry.id);
if (new Set(npcIds).size !== npcIds.length || HUB_NPCS.length !== 20) {
  throw new Error("G8 hub talk target catalog must contain twenty unambiguous NPC/Painting targets");
}

export const HUB_PORTALS: readonly HubPortal[] = [
  { id: "hub.portal.mortuary", name: "Mortuary", region: "courtyard", x: 360, y: 310, destination: "mortuary", kind: "portal" },
  { id: "hub.portal.library", name: "Library", region: "courtyard", x: 790, y: 830, destination: "library", kind: "portal" },
  { id: "hub.portal.storeroom", name: "StoreRoom", region: "courtyard", x: 1180, y: 830, destination: "storeroom", kind: "portal" },
  { id: "hub.portal.office", name: "Office", region: "courtyard", x: 1810, y: 300, destination: "office", kind: "portal" },
  { id: "hub.control.map-picker", name: "Courtyard MapPicker", region: "courtyard", x: 1030, y: 610, kind: "map-picker" },
  { id: "hub.portal.mortuary.return", name: "Return to Courtyard", region: "mortuary", x: 512, y: 850, destination: "courtyard", kind: "portal" },
  { id: "hub.portal.library.return", name: "Return to Courtyard", region: "library", x: 512, y: 850, destination: "courtyard", kind: "portal" },
  { id: "hub.portal.storeroom.return", name: "Return to Courtyard", region: "storeroom", x: 537, y: 690, destination: "courtyard", kind: "portal" },
  { id: "hub.portal.office.return", name: "Return to Courtyard", region: "office", x: 512, y: 850, destination: "courtyard", kind: "portal" },
];

export const REGION_ENTRY_POSITIONS: Readonly<Record<HubRegionId, Readonly<{ x: number; y: number }>>> = {
  courtyard: { x: 577.732178, y: 189.74292 },
  mortuary: { x: 512, y: 793.975 },
  library: { x: 512, y: 969.422 },
  storeroom: { x: 537.5, y: 754.244 },
  office: { x: 512, y: 976.463 },
};

function fomentiusName(offer: ShopOfferGolden): string {
  const key = `${offer.type_id}:${offer.variant_id ?? 0}`;
  const names: Readonly<Record<string, string>> = {
    "7001:0": "Health Potion",
    "7001:1": "Mana Potion",
    "7001:3": "Antidote",
    "7001:5": "Rejuvenation Potion",
    "7008:0": "Item Sack",
    "7012:0": "Dye Kit",
  };
  const result = names[key];
  if (result === undefined) {
    throw new Error(`G8 pinned Fomentius offer ${key} has no reviewed display name`);
  }
  return result;
}

function shopOffer(offer: ShopOfferGolden, id: string, name: string): ShopOffer {
  return { ...offer, id, name };
}

export const USEFUL_THYNGS_OFFERS: readonly ShopOffer[] = HUB_ECONOMY_GOLDEN.fomentius.map(
  (offer, index) => shopOffer(offer, `useful-thyngs.${index}`, fomentiusName(offer)),
);

export const HAGATHA_OFFERS: readonly ShopOffer[] = HUB_ECONOMY_GOLDEN.hagatha.map(
  (offer) => shopOffer(
    offer,
    `perk-shop.${offer.selector}`,
    `Charm or Curse ${offer.selector}`,
  ),
);

export const SHLORIO_OFFERS: readonly ShopOffer[] = HUB_ECONOMY_GOLDEN.shlorio.map(
  (offer, index) => shopOffer(
    offer,
    `dowsing.${index}`,
    `Dowsed recipe ${offer.recipe_uid ?? index}`,
  ),
);

export function offersForService(service: HubServiceId): readonly ShopOffer[] {
  if (service === "useful-thyngs") {
    return USEFUL_THYNGS_OFFERS;
  }
  if (service === "perk-shop") {
    return HAGATHA_OFFERS;
  }
  if (service === "dowsing") {
    return SHLORIO_OFFERS;
  }
  return [];
}
