import { spawn } from "node:child_process";
import path from "node:path";

import type { BundleGroundTruth, FileGroundTruth } from "./types.js";
import type { JsonObject } from "./validation.js";
import {
  expectArray,
  expectBoolean,
  expectInteger,
  expectNonNegativeInteger,
  expectNumber,
  expectObject,
  expectSha256,
  expectString,
  expectUnique,
} from "./validation.js";

export interface DecodedBundleRecord {
  readonly recordIndex: number;
  readonly sourceOffset: number;
  readonly sourceLength: number;
  readonly sourceBytesSha256: string;
  readonly x: number;
  readonly y: number;
  readonly width: number;
  readonly height: number;
  readonly logicalWidth: number;
  readonly logicalHeight: number;
  readonly contentWidth: number;
  readonly contentHeight: number;
  readonly centerOffsetX: number;
  readonly centerOffsetY: number;
  readonly rotated: boolean;
  readonly points: readonly { readonly x: number; readonly y: number }[];
}

export interface DecodedFontGroup {
  readonly groupIndex: number;
  readonly sourceOffset: number;
  readonly sourceLength: number;
  readonly sourceBytesSha256: string;
  readonly firstRecord: number;
  readonly lastRecord: number;
  readonly metrics: readonly [number, number, number];
  readonly kerningPairs: readonly {
    readonly leftGlyphId: number;
    readonly rightGlyphId: number;
    readonly adjustment: number;
  }[];
  readonly glyphIds: readonly number[];
}

export interface DecodedBundle {
  readonly name: string;
  readonly relativePath: string;
  readonly bytes: number;
  readonly sha256: string;
  readonly records: readonly DecodedBundleRecord[];
  readonly fontGroups: readonly DecodedFontGroup[];
}

interface BridgeSource {
  readonly path: string;
  readonly relativePath: string;
  readonly name?: string;
}

async function runBridge(
  repoRoot: string,
  pythonExecutable: string,
  command: "bundles" | "boneyards",
  sources: readonly BridgeSource[],
): Promise<unknown> {
  const bridge = path.join(
    repoRoot,
    "webgame",
    "assets",
    "python",
    "asset_decode_bridge.py",
  );
  return await new Promise((resolve, reject) => {
    const child = spawn(pythonExecutable, [bridge], {
      cwd: repoRoot,
      stdio: ["pipe", "pipe", "pipe"],
      windowsHide: true,
    });
    const stdout: Buffer[] = [];
    const stderr: Buffer[] = [];
    child.stdout.on("data", (chunk: Buffer) => stdout.push(chunk));
    child.stderr.on("data", (chunk: Buffer) => stderr.push(chunk));
    child.once("error", (error) => {
      reject(
        new Error(
          `asset decoder could not run ${pythonExecutable}: ${error.message}`,
          { cause: error },
        ),
      );
    });
    child.once("close", (code, signal) => {
      const errorText = Buffer.concat(stderr).toString("utf8").trim();
      if (code !== 0) {
        reject(
          new Error(
            `asset decoder failed (${signal === null ? `exit ${String(code)}` : signal}): `
              + (errorText || "no diagnostic"),
          ),
        );
        return;
      }
      try {
        resolve(JSON.parse(Buffer.concat(stdout).toString("utf8")) as unknown);
      } catch (error: unknown) {
        reject(
          new Error(
            `asset decoder emitted invalid JSON${errorText ? `: ${errorText}` : ""}`,
            { cause: error },
          ),
        );
      }
    });
    child.stdin.end(JSON.stringify({ command, sources }));
  });
}

function numberPair(value: unknown, label: string): { readonly x: number; readonly y: number } {
  const values = expectArray(value, label);
  if (values.length !== 2) {
    throw new Error(`${label} must contain exactly two coordinates`);
  }
  return {
    x: expectNumber(values[0], `${label}[0]`),
    y: expectNumber(values[1], `${label}[1]`),
  };
}

function numberTriple(value: unknown, label: string): readonly [number, number, number] {
  const values = expectArray(value, label);
  if (values.length !== 3) {
    throw new Error(`${label} must contain exactly three metrics`);
  }
  return [
    expectNumber(values[0], `${label}[0]`),
    expectNumber(values[1], `${label}[1]`),
    expectNumber(values[2], `${label}[2]`),
  ];
}

function decodeBundleRecord(value: unknown, label: string): DecodedBundleRecord {
  const record = expectObject(value, label);
  return {
    recordIndex: expectNonNegativeInteger(record.recordIndex, `${label}.recordIndex`),
    sourceOffset: expectNonNegativeInteger(record.sourceOffset, `${label}.sourceOffset`),
    sourceLength: expectNonNegativeInteger(record.sourceLength, `${label}.sourceLength`),
    sourceBytesSha256: expectSha256(
      record.sourceBytesSha256,
      `${label}.sourceBytesSha256`,
    ),
    x: expectNumber(record.x, `${label}.x`),
    y: expectNumber(record.y, `${label}.y`),
    width: expectNumber(record.width, `${label}.width`),
    height: expectNumber(record.height, `${label}.height`),
    logicalWidth: expectInteger(record.logicalWidth, `${label}.logicalWidth`),
    logicalHeight: expectInteger(record.logicalHeight, `${label}.logicalHeight`),
    contentWidth: expectNumber(record.contentWidth, `${label}.contentWidth`),
    contentHeight: expectNumber(record.contentHeight, `${label}.contentHeight`),
    centerOffsetX: expectNumber(record.centerOffsetX, `${label}.centerOffsetX`),
    centerOffsetY: expectNumber(record.centerOffsetY, `${label}.centerOffsetY`),
    rotated: expectBoolean(record.rotated, `${label}.rotated`),
    points: expectArray(record.points, `${label}.points`).map(
      (point, index) => numberPair(point, `${label}.points[${index}]`),
    ),
  };
}

function decodeFontGroup(value: unknown, label: string): DecodedFontGroup {
  const group = expectObject(value, label);
  const kerningPairs = expectArray(group.kerningPairs, `${label}.kerningPairs`).map(
    (rawPair, index) => {
      const pair = expectObject(rawPair, `${label}.kerningPairs[${index}]`);
      return {
        leftGlyphId: expectNonNegativeInteger(
          pair.leftGlyphId,
          `${label}.kerningPairs[${index}].leftGlyphId`,
        ),
        rightGlyphId: expectNonNegativeInteger(
          pair.rightGlyphId,
          `${label}.kerningPairs[${index}].rightGlyphId`,
        ),
        adjustment: expectNumber(
          pair.adjustment,
          `${label}.kerningPairs[${index}].adjustment`,
        ),
      };
    },
  );
  return {
    groupIndex: expectNonNegativeInteger(group.groupIndex, `${label}.groupIndex`),
    sourceOffset: expectNonNegativeInteger(group.sourceOffset, `${label}.sourceOffset`),
    sourceLength: expectNonNegativeInteger(group.sourceLength, `${label}.sourceLength`),
    sourceBytesSha256: expectSha256(
      group.sourceBytesSha256,
      `${label}.sourceBytesSha256`,
    ),
    firstRecord: expectNonNegativeInteger(group.firstRecord, `${label}.firstRecord`),
    lastRecord: expectNonNegativeInteger(group.lastRecord, `${label}.lastRecord`),
    metrics: numberTriple(group.metrics, `${label}.metrics`),
    kerningPairs,
    glyphIds: expectArray(group.glyphIds, `${label}.glyphIds`).map(
      (glyph, index) => expectNonNegativeInteger(glyph, `${label}.glyphIds[${index}]`),
    ),
  };
}

function parseDecodedBundle(value: unknown, label: string): DecodedBundle {
  const bundle = expectObject(value, label);
  const records = expectArray(bundle.records, `${label}.records`).map(
    (record, index) => decodeBundleRecord(record, `${label}.records[${index}]`),
  );
  const fontGroups = expectArray(bundle.fontGroups, `${label}.fontGroups`).map(
    (group, index) => decodeFontGroup(group, `${label}.fontGroups[${index}]`),
  );
  expectUnique(records, (record) => String(record.recordIndex), `${label} record indexes`);
  return {
    name: expectString(bundle.name, `${label}.name`),
    relativePath: expectString(bundle.relativePath, `${label}.relativePath`),
    bytes: expectNonNegativeInteger(bundle.bytes, `${label}.bytes`),
    sha256: expectSha256(bundle.sha256, `${label}.sha256`),
    records,
    fontGroups,
  };
}

function retailFile(retailRoot: string, relativePath: string): string {
  return path.join(retailRoot, ...relativePath.split("/"));
}

export async function decodeBundles(
  repoRoot: string,
  retailRoot: string,
  pythonExecutable: string,
  bundles: readonly BundleGroundTruth[],
): Promise<readonly DecodedBundle[]> {
  const sources = bundles.map((bundle) => ({
    name: bundle.name,
    path: retailFile(retailRoot, bundle.bundlePath),
    relativePath: bundle.bundlePath,
  }));
  const response = expectArray(
    await runBridge(repoRoot, pythonExecutable, "bundles", sources),
    "bundle decoder response",
  );
  const decoded = response.map((value, index) => (
    parseDecodedBundle(value, `bundle decoder response[${index}]`)
  ));
  expectUnique(decoded, (bundle) => bundle.name, "decoded bundle names");
  return decoded;
}

function validateBoneyard(value: unknown, expected: FileGroundTruth, index: number): JsonObject {
  const label = `Boneyard decoder response[${index}]`;
  const decoded = expectObject(value, label);
  if (expectString(decoded.filename, `${label}.filename`) !== expected.path) {
    throw new Error(`${label} filename does not match requested ${expected.path}`);
  }
  if (expectInteger(decoded.bytes, `${label}.bytes`) !== expected.bytes) {
    throw new Error(`${label} byte count does not match native inventory`);
  }
  const decodedProvenance = expectObject(decoded.provenance, `${label}.provenance`);
  if (
    expectSha256(
      decodedProvenance.sourceBytesSha256,
      `${label}.provenance.sourceBytesSha256`,
    ) !== expected.sha256
  ) {
    throw new Error(`${label} source hash does not match native inventory`);
  }
  expectObject(decoded.recipes, `${label}.recipes`);
  expectObject(decoded.layout, `${label}.layout`);
  expectObject(decoded.triggerControl, `${label}.triggerControl`);
  expectArray(decoded.timelines, `${label}.timelines`);
  return decoded;
}

export async function decodeBoneyards(
  repoRoot: string,
  retailRoot: string,
  pythonExecutable: string,
  boneyards: readonly FileGroundTruth[],
): Promise<readonly JsonObject[]> {
  const sources = boneyards.map((boneyard) => ({
    path: retailFile(retailRoot, boneyard.path),
    relativePath: boneyard.path,
  }));
  const response = expectArray(
    await runBridge(repoRoot, pythonExecutable, "boneyards", sources),
    "Boneyard decoder response",
  );
  if (response.length !== boneyards.length) {
    throw new Error(
      `Boneyard decoder returned ${response.length} files for ${boneyards.length} inputs`,
    );
  }
  return response.map((value, index) => {
    const expected = boneyards[index];
    if (expected === undefined) {
      throw new Error(`Boneyard decoder response ${index} has no requested source`);
    }
    return validateBoneyard(value, expected, index);
  });
}
