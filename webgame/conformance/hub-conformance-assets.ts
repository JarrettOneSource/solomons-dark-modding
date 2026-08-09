import type { AssetManifest } from "../assets/types.js";
import { HUB_SCENE_GOLDEN } from "../client/hub-contracts.js";

export function hubConformanceManifest(): AssetManifest {
  const provenance = {
    sourceBundleFilename: "hub-conformance-only",
    recordIndex: 0,
    sourceBytesSha256: "0".repeat(64),
  };
  const sceneIds = [...new Set(
    HUB_SCENE_GOLDEN.draws
      .map((draw) => draw.sprite.id)
      .filter((id) => !id.startsWith("native.")),
  )];
  if (!sceneIds.includes("College.63") || !sceneIds.includes("Clothes.880")) {
    throw new Error("hub conformance manifest did not reach backdrop and player witnesses");
  }
  const entries: AssetManifest["entries"] = Object.fromEntries(
    [...sceneIds, "Conformance.0"].map((id) => [id, {
      kind: "sprite" as const,
      atlas: "Conformance",
      rect: { x: 0, y: 0, width: 1, height: 1 },
      pivot: { x: 0, y: 0 },
      logicalSize: { width: 1, height: 1 },
      rotated: false,
      points: [],
      provenance: { ...provenance, sourceOffset: 0, sourceLength: 1 },
    }]),
  );
  const glyphs = Object.fromEntries(
    Array.from({ length: 94 }, (_, index) => [String(index + 33), "Conformance.0"]),
  );
  return {
    schema: "solomon-dark-web-asset-manifest-v1",
    nativeIdFormat: "<Atlas>.<record-index>",
    sources: {
      bundleDecoder: "tools/extract_bundles.py",
      boneyardDecoder: "tools/decode_boneyard_scripts.py",
      nativeAssetObjectMap: "hub-conformance-only",
      nativeSceneAtlasSpans: "hub-conformance-only",
      nativeContentInventory: "hub-conformance-only",
    },
    summary: {
      atlasCount: 1,
      bundleAtlasCount: 1,
      looseAtlasCount: 0,
      spriteCount: Object.keys(entries).length,
      aliasCount: 0,
      fontGroupCount: 2,
    },
    atlases: [{
      id: "Conformance",
      file: "conformance-only.png",
      width: 1,
      height: 1,
      bytes: 1,
      sha256: "0".repeat(64),
      provenance,
    }],
    entries,
    aliases: {},
    fontGroups: {
      "Fonts.216-307": {
        atlas: "Conformance",
        firstRecord: 0,
        lastRecord: 0,
        metrics: [24, 6, 28],
        kerning: [],
        glyphs,
        provenance: { ...provenance, sourceOffset: 0, sourceLength: 1 },
      },
      "Fonts.308-349": {
        atlas: "Conformance",
        firstRecord: 0,
        lastRecord: 0,
        metrics: [24, 6, 28],
        kerning: [],
        glyphs,
        provenance: { ...provenance, sourceOffset: 0, sourceLength: 1 },
      },
    },
    specialDraws: {
      "native.framebuffer-clear": {
        kind: "framebuffer-clear",
        sourceGoldenFilename: "tests/fixtures/webgame/scene-composition-goldens.json",
      },
      "native.textured-quad@0x41474C": {
        kind: "textured-quad",
        sourceGoldenFilename: "tests/fixtures/webgame/scene-composition-goldens.json",
      },
    },
    packs: {
      boneyards: { file: "unused", bytes: 1, sha256: "0".repeat(64), entryCount: 0 },
      recipes: { file: "unused", bytes: 1, sha256: "0".repeat(64), entryCount: 0 },
      waves: { file: "unused", bytes: 1, sha256: "0".repeat(64), entryCount: 0 },
    },
  };
}
