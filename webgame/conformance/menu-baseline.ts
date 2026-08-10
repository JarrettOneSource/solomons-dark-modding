import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import path from "node:path";

export const MENU_BASELINE_CORRECTIVE = "shellfix task #101";
export const MENU_BASELINE_COUNT = 28;
export const MENU_PENDING_SHELLFIX_COUNT = 29;
export const MENU_RETIRED_SCREEN_FIXTURE = "menu-layouts/dark-cloud-settings.json";
export const MENU_PENDING_ADDITIONS = [
  "menu-dialog-composites/beta-notice-first-boot.json",
  "menu-overlays/dark-cloud-settings.json",
] as const;

interface ShellGoldenSnapshot {
  readonly path: string;
  readonly sha256: string;
  readonly bytes: number;
}

interface BaselineEntry {
  readonly fixture: string;
  readonly snapshot: string;
  readonly sha256: string;
  readonly bytes: number;
  readonly corrective: string;
}

interface PendingEntry {
  readonly fixture: string;
  readonly sha256: string;
  readonly bytes: number;
  readonly corrective: string;
}

export interface VerifiedMenuBaseline {
  readonly shellGoldenSnapshot: ShellGoldenSnapshot;
  readonly snapshots: ReadonlyMap<string, BaselineEntry>;
  readonly pendingShellfix: ReadonlyMap<string, PendingEntry>;
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

function text(value: unknown, label: string): string {
  if (typeof value !== "string" || value.length === 0) {
    throw new Error(`${label} must be a non-empty string`);
  }
  return value;
}

function count(value: unknown, label: string): number {
  if (!Number.isSafeInteger(value) || (value as number) <= 0) {
    throw new Error(`${label} must be a positive integer`);
  }
  return value as number;
}

function sha256(value: unknown, label: string): string {
  const result = text(value, label);
  if (!/^[0-9a-f]{64}$/.test(result)) {
    throw new Error(`${label} must be a lowercase SHA-256`);
  }
  return result;
}

function rows(value: unknown, label: string): unknown[] {
  if (!Array.isArray(value)) {
    throw new Error(`${label} must be an array`);
  }
  return value;
}

function parseBaselineEntry(value: unknown, index: number): BaselineEntry {
  const entry = object(value, `menu baseline snapshots[${index}]`);
  exactKeys(entry, ["bytes", "corrective", "fixture", "sha256", "snapshot"], `menu baseline snapshots[${index}]`);
  const fixture = text(entry.fixture, `menu baseline snapshots[${index}].fixture`);
  const snapshot = text(entry.snapshot, `menu baseline snapshots[${index}].snapshot`);
  if (snapshot !== `webgame-contracts/baseline-snapshots/${fixture}`) {
    throw new Error(`menu baseline snapshot path does not derive exactly from ${fixture}`);
  }
  return {
    fixture,
    snapshot,
    sha256: sha256(entry.sha256, `menu baseline snapshots[${index}].sha256`),
    bytes: count(entry.bytes, `menu baseline snapshots[${index}].bytes`),
    corrective: text(entry.corrective, `menu baseline snapshots[${index}].corrective`),
  };
}

function parsePendingEntry(value: unknown, index: number): PendingEntry {
  const entry = object(value, `menu pending_shellfix[${index}]`);
  exactKeys(entry, ["bytes", "corrective", "fixture", "sha256"], `menu pending_shellfix[${index}]`);
  return {
    fixture: text(entry.fixture, `menu pending_shellfix[${index}].fixture`),
    sha256: sha256(entry.sha256, `menu pending_shellfix[${index}].sha256`),
    bytes: count(entry.bytes, `menu pending_shellfix[${index}].bytes`),
    corrective: text(entry.corrective, `menu pending_shellfix[${index}].corrective`),
  };
}

function parseShellGoldenSnapshot(value: unknown): ShellGoldenSnapshot {
  const entry = object(value, "menu shell golden snapshot");
  exactKeys(entry, ["bytes", "path", "sha256"], "menu shell golden snapshot");
  const snapshotPath = text(entry.path, "menu shell golden snapshot.path");
  if (snapshotPath !== "webgame-contracts/baseline-snapshots/menu-goldens.json") {
    throw new Error("menu shell golden snapshot path changed");
  }
  return {
    path: snapshotPath,
    sha256: sha256(entry.sha256, "menu shell golden snapshot.sha256"),
    bytes: count(entry.bytes, "menu shell golden snapshot.bytes"),
  };
}

function uniqueMap<T extends { readonly fixture: string }>(values: readonly T[], label: string): Map<string, T> {
  const result = new Map(values.map((entry) => [entry.fixture, entry]));
  if (result.size !== values.length) {
    throw new Error(`${label} contains an ambiguous duplicate fixture`);
  }
  return result;
}

async function verifyReceipt(filePath: string, expectedBytes: number, expectedSha256: string, claim: string): Promise<void> {
  const bytes = await readFile(filePath);
  if (bytes.byteLength !== expectedBytes) {
    throw new Error(`${claim} byte count mismatch`);
  }
  const actual = createHash("sha256").update(bytes).digest("hex");
  if (actual !== expectedSha256) {
    throw new Error(`${claim} SHA-256 mismatch`);
  }
}

export async function verifyMenuBaseline(
  value: unknown,
  repository: string,
  canonicalFixtures: ReadonlySet<string>,
): Promise<VerifiedMenuBaseline> {
  const root = object(value, "menu baseline manifest");
  exactKeys(
    root,
    [
      "baseline_snapshot_count",
      "baseline_snapshots",
      "corrective",
      "pending_shellfix",
      "pending_shellfix_count",
      "schema",
      "shell_golden_snapshot",
    ],
    "menu baseline manifest",
  );
  if (root.schema !== "solomon-dark-menu-baseline-v2") {
    throw new Error("menu baseline manifest lost its versioned schema");
  }
  if (root.corrective !== MENU_BASELINE_CORRECTIVE) {
    throw new Error("menu baseline manifest lost shellfix task #101 ownership");
  }
  if (root.baseline_snapshot_count !== MENU_BASELINE_COUNT || root.pending_shellfix_count !== MENU_PENDING_SHELLFIX_COUNT) {
    throw new Error("menu baseline manifest census must remain exactly 28 snapshots and 29 pending fixtures");
  }
  const shellGoldenSnapshot = parseShellGoldenSnapshot(root.shell_golden_snapshot);
  await verifyReceipt(
    path.join(repository, shellGoldenSnapshot.path),
    shellGoldenSnapshot.bytes,
    shellGoldenSnapshot.sha256,
    "menu shell golden snapshot",
  );
  const snapshots = uniqueMap(
    rows(root.baseline_snapshots, "menu baseline snapshots").map(parseBaselineEntry),
    "menu baseline snapshots",
  );
  const pending = uniqueMap(
    rows(root.pending_shellfix, "menu pending_shellfix").map(parsePendingEntry),
    "menu pending_shellfix",
  );
  if (snapshots.size !== MENU_BASELINE_COUNT || pending.size !== MENU_PENDING_SHELLFIX_COUNT) {
    throw new Error("menu baseline manifest arrays must enumerate exactly 28 snapshots and 29 pending fixtures");
  }
  if (canonicalFixtures.size !== MENU_BASELINE_COUNT || !canonicalFixtures.has(MENU_RETIRED_SCREEN_FIXTURE)) {
    throw new Error("menu shell baseline must name the exact 28 historical fixtures");
  }
  const expectedPendingFixtures = new Set(
    [...canonicalFixtures].filter((fixture) => fixture !== MENU_RETIRED_SCREEN_FIXTURE),
  );
  for (const fixture of MENU_PENDING_ADDITIONS) {
    expectedPendingFixtures.add(fixture);
  }
  if (
    [...canonicalFixtures].some((fixture) => !snapshots.has(fixture))
    || [...snapshots.keys()].some((fixture) => !canonicalFixtures.has(fixture))
    || [...expectedPendingFixtures].some((fixture) => !pending.has(fixture))
    || [...pending.keys()].some((fixture) => !expectedPendingFixtures.has(fixture))
  ) {
    throw new Error("menu pending_shellfix must enumerate the exact settled state census");
  }
  for (const fixture of canonicalFixtures) {
    const snapshot = snapshots.get(fixture);
    if (snapshot === undefined) {
      throw new Error(`menu baseline verification lost canonical fixture ${fixture}`);
    }
    if (snapshot.corrective !== MENU_BASELINE_CORRECTIVE) {
      throw new Error(`menu baseline entry ${fixture} lost shellfix task #101 ownership`);
    }
    await verifyReceipt(
      path.join(repository, snapshot.snapshot),
      snapshot.bytes,
      snapshot.sha256,
      `menu baseline snapshot ${fixture}`,
    );
  }
  for (const fixture of expectedPendingFixtures) {
    const pendingEntry = pending.get(fixture);
    if (pendingEntry === undefined) {
      throw new Error(`menu baseline verification lost pending fixture ${fixture}`);
    }
    if (pendingEntry.corrective !== MENU_BASELINE_CORRECTIVE) {
      throw new Error(`menu baseline entry ${fixture} lost shellfix task #101 ownership`);
    }
    await verifyReceipt(
      path.join(repository, "tests", "fixtures", "webgame", fixture),
      pendingEntry.bytes,
      pendingEntry.sha256,
      `menu pending_shellfix fixture ${fixture}`,
    );
  }
  return { shellGoldenSnapshot, snapshots, pendingShellfix: pending };
}
