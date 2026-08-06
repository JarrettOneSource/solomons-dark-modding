import type { MenuCatalog } from "../client/menu-catalog.js";

export const MENU_VISUAL_PIXEL_RULE =
  "Human side-by-side review at 1600x900 requires the same assetpack art at exact G11 positions; font rasterization may differ.";
export const MENU_VISUAL_STALE_MARKER = "stale controls omitted";
export const MENU_VISUAL_CORRECTIVE = "menufix task #97";

interface WaiverEntry {
  readonly fixture: string;
  readonly requiredMarker: string;
  readonly corrective: string;
}

export interface MenuVisualGateResult {
  readonly status: "pass_with_enumerated_waiver";
  readonly pixelRule: string;
  readonly reviewedPassFixtures: readonly string[];
  readonly waivedDivergentFixtures: readonly string[];
  readonly corrective: "menufix task #97";
}

type JsonObject = Record<string, unknown>;

function object(value: unknown, label: string): JsonObject {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${label} must be an object`);
  }
  return value as JsonObject;
}

function exactKeys(value: JsonObject, expected: readonly string[], label: string): void {
  const actual = Object.keys(value).sort();
  const wanted = [...expected].sort();
  if (actual.length !== wanted.length || actual.some((key, index) => key !== wanted[index])) {
    throw new Error(`${label} has keys ${actual.join(",")}; expected exactly ${wanted.join(",")}`);
  }
}

function string(value: unknown, label: string): string {
  if (typeof value !== "string") {
    throw new Error(`${label} must be a string`);
  }
  return value;
}

function stringArray(value: unknown, label: string): string[] {
  if (!Array.isArray(value)) {
    throw new Error(`${label} must be a string array`);
  }
  const entries = value as unknown[];
  const result = entries.map((entry) => string(entry, `${label} entry`));
  if (new Set(result).size !== result.length) {
    throw new Error(`${label} contains a duplicate fixture and makes visual ownership ambiguous`);
  }
  return result;
}

function parseEntry(value: unknown, index: number): WaiverEntry {
  const entry = object(value, `menu visual waiver entries[${index}]`);
  exactKeys(
    entry,
    ["corrective", "fixture", "required_marker"],
    `menu visual waiver entries[${index}]`,
  );
  return {
    fixture: string(entry.fixture, `menu visual waiver entries[${index}].fixture`),
    requiredMarker: string(
      entry.required_marker,
      `menu visual waiver entries[${index}].required_marker`,
    ),
    corrective: string(entry.corrective, `menu visual waiver entries[${index}].corrective`),
  };
}

export function validateMenuVisualGate(
  value: unknown,
  catalog: MenuCatalog,
): MenuVisualGateResult {
  const root = object(value, "menu visual gate");
  exactKeys(
    root,
    ["pixel_rule", "reviewed_divergent_fixtures", "reviewed_pass_fixtures", "schema", "waiver"],
    "menu visual gate",
  );
  if (root.schema !== "solomon-dark-menu-visual-gate-v1") {
    throw new Error("menu visual gate lost its versioned schema");
  }
  const pixelRule = string(root.pixel_rule, "menu visual gate pixel_rule");
  if (pixelRule !== MENU_VISUAL_PIXEL_RULE) {
    throw new Error("menu visual gate changed the original pixel-plausibility rule or added tolerance");
  }
  const reviewedPass = stringArray(root.reviewed_pass_fixtures, "reviewed pass fixtures");
  const reviewedDivergent = stringArray(
    root.reviewed_divergent_fixtures,
    "reviewed divergent fixtures",
  );
  const waiver = object(root.waiver, "menu visual waiver");
  exactKeys(waiver, ["decision", "entries"], "menu visual waiver");
  if (waiver.decision !== "ATC 2026-08-05 evening") {
    throw new Error("menu visual waiver lost the governing ATC decision");
  }
  if (!Array.isArray(waiver.entries)) {
    throw new Error("menu visual waiver entries must be an array");
  }
  const entries = waiver.entries.map(parseEntry);
  const entriesByFixture = new Map(entries.map((entry) => [entry.fixture, entry]));
  if (entriesByFixture.size !== entries.length) {
    throw new Error("menu visual waiver lists one fixture more than once and is ambiguous");
  }

  for (const fixture of reviewedDivergent) {
    if (!entriesByFixture.has(fixture)) {
      throw new Error(`unwaived visual divergence: ${fixture}`);
    }
  }
  for (const entry of entries) {
    if (!reviewedDivergent.includes(entry.fixture)) {
      throw new Error(`visual waiver names a fixture that passed review: ${entry.fixture}`);
    }
    if (entry.requiredMarker !== MENU_VISUAL_STALE_MARKER) {
      throw new Error(`visual waiver does not cite the literal stale marker: ${entry.fixture}`);
    }
    if (entry.corrective !== MENU_VISUAL_CORRECTIVE) {
      throw new Error(`visual waiver does not point ${entry.fixture} to menufix task #97`);
    }
    const layout = [...catalog.layouts.values()].find(
      (candidate) => candidate.fixture === entry.fixture,
    );
    if (layout === undefined) {
      throw new Error(`visual waiver names a fixture outside the G11 census: ${entry.fixture}`);
    }
    if (!layout.captureMethod.includes(MENU_VISUAL_STALE_MARKER)) {
      throw new Error(
        `illegal stale visual waiver: ${entry.fixture} no longer bears literal marker "${MENU_VISUAL_STALE_MARKER}"; delete the waiver and pass full visual match`,
      );
    }
  }

  const passedSet = new Set(reviewedPass);
  const divergentSet = new Set(reviewedDivergent);
  for (const fixture of reviewedPass) {
    if (divergentSet.has(fixture)) {
      throw new Error(`menu visual review classifies ${fixture} as both pass and divergent`);
    }
    const layout = [...catalog.layouts.values()].find(
      (candidate) => candidate.fixture === fixture,
    );
    if (layout === undefined) {
      throw new Error(`visual pass names a fixture outside the G11 census: ${fixture}`);
    }
    if (layout.captureMethod.includes(MENU_VISUAL_STALE_MARKER)) {
      throw new Error(`unwaived stale visual fixture: ${fixture}`);
    }
  }
  if (reviewedPass.length !== 18 || reviewedDivergent.length !== 10 || entries.length !== 10) {
    throw new Error("menu visual gate must remain exactly 18 ordinary passes and 10 stale waivers");
  }
  const reviewed = new Set([...reviewedPass, ...reviewedDivergent]);
  const canonical = new Set([...catalog.layouts.values()].map((layout) => layout.fixture));
  if (
    reviewed.size !== canonical.size
    || [...reviewed].some((fixture) => !canonical.has(fixture))
    || [...canonical].some((fixture) => !reviewed.has(fixture))
  ) {
    throw new Error("menu visual gate no longer covers the exact 28-fixture G11 census");
  }
  if (passedSet.size !== reviewedPass.length) {
    throw new Error("menu visual pass set became ambiguous");
  }
  return {
    status: "pass_with_enumerated_waiver",
    pixelRule,
    reviewedPassFixtures: [...reviewedPass].sort(),
    waivedDivergentFixtures: [...reviewedDivergent].sort(),
    corrective: MENU_VISUAL_CORRECTIVE,
  };
}
