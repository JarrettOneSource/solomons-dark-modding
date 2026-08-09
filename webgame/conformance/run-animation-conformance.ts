import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import path from "node:path";

import { facing24, wizardPresentation } from "../client/hub-contracts.js";

type JsonObject = Record<string, unknown>;

function object(value: unknown, claim: string): JsonObject {
  assert(value !== null && typeof value === "object" && !Array.isArray(value), claim);
  return value as JsonObject;
}

function array(value: unknown, claim: string): unknown[] {
  assert(Array.isArray(value), claim);
  return value;
}

function string(value: unknown, claim: string): string {
  assert.equal(typeof value, "string", claim);
  return value as string;
}

function number(value: unknown, claim: string): number {
  assert.equal(typeof value, "number", claim);
  assert(Number.isFinite(value), claim);
  return value as number;
}

function spriteIds(frame: unknown): string[] {
  return array(object(frame, "G4 frame must be an object").sprites, "G4 frame lost its sprite list")
    .map((rawSprite) => {
      const sprite = object(rawSprite, "G4 sprite record must be an object");
      return `${string(sprite.atlas, "G4 sprite lost its atlas")}.${number(sprite.sprite_index, "G4 sprite lost its index")}`;
    });
}

const repository = path.resolve(import.meta.dirname, "..", "..");
const fixturePath = path.join(repository, "tests", "fixtures", "webgame", "animation-goldens.json");
const original = await readFile(fixturePath, "utf8");
const diagnosticNan = /:\s*NaN(?=\s*[,}])/g;
assert.equal(
  [...original.matchAll(diagnosticNan)].length,
  4,
  "G4 conformance normalization no longer names all four native NaN diagnostic scalars",
);
const root = object(
  JSON.parse(original.replace(diagnosticNan, ": null")) as unknown,
  "G4 animation fixture must be an object",
);
assert.equal(root.schema, "solomon-dark-animation-goldens-v1", "G4 animation fixture lost its versioned schema");
const wizardCaptures = array(root.wizard, "G4 animation fixture lost the wizard capture census");
const names = wizardCaptures.map((capture) => string(object(capture, "G4 wizard capture must be an object").name, "G4 wizard capture lost its name"));
assert.equal(new Set(names).size, names.length, "G4 conformance refuses ambiguous duplicate wizard capture names");

const capture = (name: string): JsonObject => {
  const matches = wizardCaptures.filter((candidate) => object(candidate, "G4 wizard candidate must be an object").name === name);
  assert.equal(matches.length, 1, `G4 conformance requires exactly one ${name} wizard capture`);
  return object(matches[0], `G4 ${name} wizard capture disappeared after resolution`);
};

const idle = capture("idle");
const idleFrames = array(idle.frames, "G4 idle capture lost its render frames");
assert.equal(idleFrames.length, 30, "G4 idle capture no longer contains all thirty render frames");
const idleClothes = spriteIds(idleFrames[0]).filter((id) => id.startsWith("Clothes."));
assert.deepEqual(
  wizardPresentation(180, false, 0).clothesSpriteIds,
  idleClothes,
  "G4 P1 idle selector changed the native heading-180 Clothes frame ids",
);

const walk = capture("idle_walk_idle");
const walkFrames = array(walk.frames, "G4 idle-walk-idle capture lost its render frames");
assert.equal(walkFrames.length, 100, "G4 idle-walk-idle capture no longer contains all one hundred render frames");
const transitions = array(walk.transitions, "G4 idle-walk-idle capture lost its transitions").map((raw) => {
  const transition = object(raw, "G4 locomotion transition must be an object");
  return `${string(transition.from, "G4 locomotion transition lost its source")}->${string(transition.to, "G4 locomotion transition lost its target")}`;
});
assert.deepEqual(
  transitions,
  ["absent->idle", "idle->walk", "walk->idle"],
  "G4 P1 locomotion surface changed the complete native idle/walk transition sequence",
);
const firstWalkClothes = spriteIds(walkFrames[0]).filter((id) => id.startsWith("Clothes."));
assert.deepEqual(
  wizardPresentation(90.0000076, true, 0).clothesSpriteIds,
  firstWalkClothes,
  "G4 P1 walk selector changed the first native heading-90 locomotion bank",
);
const secondBankClothes = spriteIds(walkFrames[5]).filter((id) => id.startsWith("Clothes."));
assert.deepEqual(
  wizardPresentation(90.0000076, true, 100).clothesSpriteIds,
  secondBankClothes,
  "G4 P1 walk selector changed the native second locomotion bank",
);
assert.deepEqual(
  wizardPresentation(90.0000076, false, 100).clothesSpriteIds,
  firstWalkClothes,
  "G4 P1 walk-to-idle selector did not restore the native idle locomotion bank",
);

const recordedAuraIds = new Set(
  [...idleFrames, ...walkFrames]
    .flatMap(spriteIds)
    .filter((id) => /^BadGuys\.25[5-9]$|^BadGuys\.26[0-6]$/.test(id)),
);
const selectedAuraIds = new Set(Array.from({ length: 12 }, (_, phase) => (
  wizardPresentation(180, false, phase * 50).auraSpriteId
)));
assert.deepEqual(
  [...selectedAuraIds].sort(),
  [...recordedAuraIds].sort(),
  "G4 P1 aura selector no longer covers the exact native idle/walk frame list",
);
assert.deepEqual(
  [0, 15, 90.0000076, 180, 345, 359].map(facing24),
  [0, 1, 6, 12, 23, 0],
  "G4 P1 facing selector changed the native 24-facing truncation and single-wrap rule",
);

process.stdout.write([
  "G4 P1 WIZARD PRESENTATION CONFORMANCE: PASS",
  `idle_frames=${idleFrames.length}`,
  `idle_walk_idle_frames=${walkFrames.length}`,
  `locomotion_transitions=${transitions.join(" -> ")}`,
  `directional_clothes_lanes=${idleClothes.length}; facings=24`,
  `aura_frames=${selectedAuraIds.size}`,
  "combat_states=OUT_OF_SCOPE",
  "movement_fidelity_and_determinism=NOT_CLAIMED",
  "",
].join("\n"));
