import { readFile } from "node:fs/promises";
import path from "node:path";

import AjvModule from "ajv";
import { describe, expect, it } from "vitest";

import { expectObject } from "../validation.js";

const SCHEMA_PATH = path.resolve(import.meta.dirname, "..", "asset-manifest.schema.json");

async function validator(): Promise<ReturnType<InstanceType<typeof AjvModule.default>["compile"]>> {
  const schema = expectObject(
    JSON.parse(await readFile(SCHEMA_PATH, "utf8")) as unknown,
    "asset manifest schema",
  );
  return new AjvModule.default({ allErrors: true, strict: true }).compile(schema);
}

function minimalManifest(): Record<string, unknown> {
  const provenance = {
    sourceBundleFilename: "images/Test.bundle",
    recordIndex: 0,
    sourceBytesSha256: "1".repeat(64),
  };
  return {
    schema: "solomon-dark-web-asset-manifest-v1",
    nativeIdFormat: "<Atlas>.<record-index>",
    sources: {
      bundleDecoder: "tools/extract_bundles.py",
      boneyardDecoder: "tools/decode_boneyard_scripts.py",
      nativeAssetObjectMap: "map.json",
      nativeSceneAtlasSpans: "spans.inl",
      nativeContentInventory: "inventory.json",
    },
    summary: {
      atlasCount: 1,
      bundleAtlasCount: 1,
      looseAtlasCount: 0,
      spriteCount: 1,
      aliasCount: 0,
      fontGroupCount: 0,
    },
    atlases: [{
      id: "Test",
      file: "atlases/Test.png",
      width: 1,
      height: 1,
      bytes: 68,
      sha256: "2".repeat(64),
      provenance,
    }],
    entries: {
      "Test.0": {
        kind: "sprite",
        atlas: "Test",
        rect: { x: 0, y: 0, width: 1, height: 1 },
        pivot: { x: 0, y: 0 },
        logicalSize: { width: 1, height: 1 },
        rotated: false,
        points: [],
        provenance: { ...provenance, sourceOffset: 0, sourceLength: 45 },
      },
    },
    aliases: {},
    fontGroups: {},
    specialDraws: {},
    packs: {
      boneyards: { file: "packs/boneyards.json", bytes: 1, sha256: "3".repeat(64), entryCount: 1 },
      recipes: { file: "packs/recipes.json", bytes: 1, sha256: "4".repeat(64), entryCount: 0 },
      waves: { file: "packs/waves.json", bytes: 1, sha256: "5".repeat(64), entryCount: 1 },
    },
  };
}

describe("asset manifest JSON Schema", () => {
  it("accepts the complete v1 lookup shape", async () => {
    const validate = await validator();
    expect(validate(minimalManifest()), JSON.stringify(validate.errors)).toBe(true);
  });

  it("rejects an entry that loses record-level provenance", async () => {
    const validate = await validator();
    const manifest = minimalManifest();
    const entries = manifest.entries as Record<string, Record<string, unknown>>;
    const entry = entries["Test.0"];
    if (entry === undefined) {
      throw new Error("minimal manifest lost Test.0 witness");
    }
    entry.provenance = {
      sourceBundleFilename: "images/Test.bundle",
      recordIndex: 0,
      sourceBytesSha256: "1".repeat(64),
    };
    expect(validate(manifest)).toBe(false);
    expect(validate.errors?.some((error) => error.message === "must have required property 'sourceOffset'"))
      .toBe(true);
  });
});
