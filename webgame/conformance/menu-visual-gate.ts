import type { MenuCatalog } from "../client/menu-catalog.js";
import {
  MENU_BASELINE_CORRECTIVE,
  MENU_BASELINE_COUNT,
  MENU_PENDING_SHELLFIX_COUNT,
  type VerifiedMenuBaseline,
} from "./menu-baseline.js";

export const MENU_VISUAL_PIXEL_RULE =
  "Human side-by-side review at 1600x900 requires the same assetpack art at exact G11 positions; font rasterization may differ.";

interface ReviewedSnapshot {
  readonly fixture: string;
  readonly baselineSnapshotSha256: string;
  readonly corrective: string;
}

interface PendingShellfix {
  readonly fixture: string;
  readonly settledFixtureSha256: string;
  readonly corrective: string;
}

export interface MenuVisualGateResult {
  readonly status: "pass_against_baseline_snapshots";
  readonly pixelRule: string;
  readonly reviewedPassFixtures: readonly string[];
  readonly reviewedDivergentFixtures: readonly string[];
  readonly pendingShellfixFixtures: readonly string[];
  readonly corrective: "shellfix task #101";
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
  if (typeof value !== "string" || value.length === 0) {
    throw new Error(`${label} must be a non-empty string`);
  }
  return value;
}

function sha256(value: unknown, label: string): string {
  const result = string(value, label);
  if (!/^[0-9a-f]{64}$/.test(result)) {
    throw new Error(`${label} must be a lowercase SHA-256`);
  }
  return result;
}

function array(value: unknown, label: string): unknown[] {
  if (!Array.isArray(value)) {
    throw new Error(`${label} must be an array`);
  }
  return value;
}

function parseReviewed(value: unknown, index: number, label: string): ReviewedSnapshot {
  const entry = object(value, `${label}[${index}]`);
  exactKeys(entry, ["baseline_snapshot_sha256", "corrective", "fixture"], `${label}[${index}]`);
  return {
    fixture: string(entry.fixture, `${label}[${index}].fixture`),
    baselineSnapshotSha256: sha256(
      entry.baseline_snapshot_sha256,
      `${label}[${index}].baseline_snapshot_sha256`,
    ),
    corrective: string(entry.corrective, `${label}[${index}].corrective`),
  };
}

function parsePending(value: unknown, index: number): PendingShellfix {
  const entry = object(value, `menu visual pending_shellfix[${index}]`);
  exactKeys(
    entry,
    ["corrective", "fixture", "settled_fixture_sha256"],
    `menu visual pending_shellfix[${index}]`,
  );
  return {
    fixture: string(entry.fixture, `menu visual pending_shellfix[${index}].fixture`),
    settledFixtureSha256: sha256(
      entry.settled_fixture_sha256,
      `menu visual pending_shellfix[${index}].settled_fixture_sha256`,
    ),
    corrective: string(entry.corrective, `menu visual pending_shellfix[${index}].corrective`),
  };
}

function uniqueByFixture<T extends { readonly fixture: string }>(values: readonly T[], label: string): Map<string, T> {
  const result = new Map(values.map((entry) => [entry.fixture, entry]));
  if (result.size !== values.length) {
    throw new Error(`${label} lists one fixture more than once and is ambiguous`);
  }
  return result;
}

export function validateMenuVisualGate(
  value: unknown,
  catalog: MenuCatalog,
  baseline: VerifiedMenuBaseline,
): MenuVisualGateResult {
  const root = object(value, "menu visual gate");
  exactKeys(
    root,
    [
      "pending_shellfix",
      "pixel_rule",
      "reviewed_divergent_snapshots",
      "reviewed_pass_snapshots",
      "schema",
    ],
    "menu visual gate",
  );
  if (root.schema !== "solomon-dark-menu-visual-gate-v2") {
    throw new Error("menu visual gate lost its baseline-snapshot schema");
  }
  const pixelRule = string(root.pixel_rule, "menu visual gate pixel_rule");
  if (pixelRule !== MENU_VISUAL_PIXEL_RULE) {
    throw new Error("menu visual gate changed the original pixel-plausibility rule or added tolerance");
  }
  const reviewedPass = array(root.reviewed_pass_snapshots, "reviewed pass snapshots")
    .map((entry, index) => parseReviewed(entry, index, "reviewed pass snapshots"));
  const reviewedDivergent = array(
    root.reviewed_divergent_snapshots,
    "reviewed divergent snapshots",
  ).map((entry, index) => parseReviewed(entry, index, "reviewed divergent snapshots"));
  const pending = array(root.pending_shellfix, "menu visual pending_shellfix")
    .map(parsePending);
  const passedByFixture = uniqueByFixture(reviewedPass, "reviewed pass snapshots");
  const divergentByFixture = uniqueByFixture(reviewedDivergent, "reviewed divergent snapshots");
  const pendingByFixture = uniqueByFixture(pending, "menu visual pending_shellfix");
  if (reviewedPass.length !== 18 || reviewedDivergent.length !== 10) {
    throw new Error("menu visual gate must preserve exactly 18 pass and 10 divergent baseline attestations");
  }
  if (pending.length !== MENU_PENDING_SHELLFIX_COUNT) {
    throw new Error("menu visual gate pending_shellfix census must remain exactly 29");
  }
  for (const entry of [...reviewedPass, ...reviewedDivergent]) {
    if (entry.corrective !== MENU_BASELINE_CORRECTIVE) {
      throw new Error(`menu visual review ${entry.fixture} lost shellfix task #101 ownership`);
    }
    const snapshot = baseline.snapshots.get(entry.fixture);
    if (snapshot === undefined || snapshot.sha256 !== entry.baselineSnapshotSha256) {
      throw new Error(`menu visual review ${entry.fixture} is not bound to its baseline snapshot hash`);
    }
  }
  for (const entry of pending) {
    if (entry.corrective !== MENU_BASELINE_CORRECTIVE) {
      throw new Error(`menu visual pending entry ${entry.fixture} lost shellfix task #101 ownership`);
    }
    const expected = baseline.pendingShellfix.get(entry.fixture);
    if (expected === undefined || expected.sha256 !== entry.settledFixtureSha256) {
      throw new Error(`menu visual pending entry ${entry.fixture} pins the wrong settled fixture hash`);
    }
  }
  const reviewed = new Set([...passedByFixture.keys(), ...divergentByFixture.keys()]);
  const canonical = new Set([...catalog.layouts.values()].map((layout) => layout.fixture));
  if (
    reviewed.size !== MENU_BASELINE_COUNT
    || canonical.size !== MENU_BASELINE_COUNT
    || pendingByFixture.size !== MENU_PENDING_SHELLFIX_COUNT
    || [...reviewed].some((fixture) => !canonical.has(fixture))
    || [...canonical].some((fixture) => !reviewed.has(fixture))
    || [...pendingByFixture].some(
      ([fixture]) => !baseline.pendingShellfix.has(fixture),
    )
    || [...baseline.pendingShellfix].some(
      ([fixture]) => !pendingByFixture.has(fixture),
    )
  ) {
    throw new Error("menu visual gate no longer covers the exact 28 historical fixtures and 29 pending states");
  }
  return {
    status: "pass_against_baseline_snapshots",
    pixelRule,
    reviewedPassFixtures: [...passedByFixture.keys()].sort(),
    reviewedDivergentFixtures: [...divergentByFixture.keys()].sort(),
    pendingShellfixFixtures: [...pendingByFixture.keys()].sort(),
    corrective: MENU_BASELINE_CORRECTIVE,
  };
}
