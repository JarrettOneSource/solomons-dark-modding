import { describe, expect, it } from "vitest";

import type { AssetManifest } from "../assets/types.js";
import { ManifestAssets } from "./manifest-assets.js";

const provenance = {
  sourceBundleFilename: "images/Test.bundle",
  recordIndex: 0,
  sourceBytesSha256: "1".repeat(64),
} as const;

function manifest(): AssetManifest {
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
      spriteCount: 2,
      aliasCount: 1,
      fontGroupCount: 1,
    },
    atlases: [{
      id: "Test",
      file: "atlases/Test.png",
      width: 2,
      height: 1,
      bytes: 72,
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
      "Test.1": {
        kind: "sprite",
        atlas: "Test",
        rect: { x: 1, y: 0, width: 1, height: 1 },
        pivot: { x: 0, y: 0 },
        logicalSize: { width: 1, height: 1 },
        rotated: false,
        points: [],
        provenance: { ...provenance, recordIndex: 1, sourceOffset: 45, sourceLength: 45 },
      },
    },
    aliases: { "legacy.test": "Test.0" },
    fontGroups: {
      "Fonts.Test": {
        atlas: "Test",
        firstRecord: 0,
        lastRecord: 1,
        metrics: [16, 4, 28],
        kerning: [],
        glyphs: { "65": "Test.1" },
        provenance: { ...provenance, sourceOffset: 0, sourceLength: 90 },
      },
    },
    specialDraws: {
      "Segoe UI": { kind: "system-font", sourceGoldenFilename: "menu-goldens.json" },
    },
    packs: {
      boneyards: { file: "packs/boneyards.json", bytes: 1, sha256: "3".repeat(64), entryCount: 0 },
      recipes: { file: "packs/recipes.json", bytes: 1, sha256: "4".repeat(64), entryCount: 0 },
      waves: { file: "packs/waves.json", bytes: 1, sha256: "5".repeat(64), entryCount: 0 },
    },
  };
}

describe("manifest-only shell asset lookup", () => {
  it("resolves direct and single-hop alias ids to the same manifest entry", () => {
    const assets = new ManifestAssets(manifest());
    expect(assets.resolve("Test.0").canonicalId).toBe("Test.0");
    expect(assets.resolve("legacy.test")).toMatchObject({
      requestedId: "legacy.test",
      canonicalId: "Test.0",
      atlas: { id: "Test" },
    });
  });

  it("refuses a direct-entry and alias collision", () => {
    const value = manifest();
    const ambiguous = { ...value, aliases: { ...value.aliases, "Test.0": "Test.1" } };
    expect(() => new ManifestAssets(ambiguous).resolve("Test.0"))
      .toThrow("ambiguous for Test.0: entry and alias both exist");
  });

  it("refuses alias chains rather than guessing a terminal record", () => {
    const value = manifest();
    const chained = { ...value, aliases: { a: "legacy.test", ...value.aliases } };
    expect(() => new ManifestAssets(chained).resolve("a"))
      .toThrow("alias a chains through legacy.test; resolution is ambiguous");
  });

  it("names the exact missing asset id", () => {
    expect(() => new ManifestAssets(manifest()).resolve("Missing.9"))
      .toThrow("missing required asset id Missing.9");
  });

  it("fails if an entry's named atlas is absent", () => {
    const value = manifest();
    const entry = value.entries["Test.0"];
    if (entry === undefined) {
      throw new Error("test manifest lost its Test.0 witness");
    }
    const broken = {
      ...value,
      entries: { ...value.entries, "Test.0": { ...entry, atlas: "Gone" } },
    };
    expect(() => new ManifestAssets(broken).resolve("Test.0"))
      .toThrow("asset Test.0 names missing atlas Gone");
  });

  it("refuses duplicate atlas candidates", () => {
    const value = manifest();
    const duplicate = { ...value, atlases: [...value.atlases, value.atlases[0]] };
    expect(() => new ManifestAssets(duplicate)).toThrow("ambiguously defines atlas Test");
  });

  it("resolves bitmap glyphs and rejects missing glyphs by code point", () => {
    const assets = new ManifestAssets(manifest());
    expect(assets.glyph("Fonts.Test", "A")?.canonicalId).toBe("Test.1");
    expect(assets.glyph("Fonts.Test", " ")).toBeNull();
    expect(() => assets.glyph("Fonts.Test", "B")).toThrow("missing glyph U+42");
  });

  it("keeps system-font special draws distinct from bitmap glyph groups", () => {
    const assets = new ManifestAssets(manifest());
    expect(assets.font("Segoe UI")).toMatchObject({ kind: "system-font" });
    expect(() => assets.glyph("Segoe UI", "A"))
      .toThrow("Segoe UI is a system-font draw and has no assetpack glyph records");
  });
});
