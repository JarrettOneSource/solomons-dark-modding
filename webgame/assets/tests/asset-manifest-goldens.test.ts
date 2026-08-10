import { readFile } from "node:fs/promises";
import path from "node:path";

import { describe, expect, it } from "vitest";

import { sha256File } from "../hash.js";
import {
  expectArray,
  expectInteger,
  expectObject,
  expectSha256,
  expectString,
} from "../validation.js";

const REPO_ROOT = path.resolve(import.meta.dirname, "..", "..", "..");
const FIXTURE_PATH = path.join(
  REPO_ROOT,
  "webgame",
  "assets",
  "fixtures",
  "asset-manifest-goldens.json",
);

async function loadFixture(): Promise<Record<string, unknown>> {
  return expectObject(
    JSON.parse(await readFile(FIXTURE_PATH, "utf8")) as unknown,
    "asset-manifest golden fixture",
  );
}

describe("asset-manifest golden fixture", () => {
  it("records a byte-identical double build and every emitted file", async () => {
    const fixture = await loadFixture();
    expect(fixture.schema).toBe("solomon-dark-web-asset-manifest-goldens-v1");
    expect(fixture.manifestSchema).toBe("solomon-dark-web-asset-manifest-v1");

    const determinism = expectObject(fixture.determinism, "fixture determinism");
    const first = expectSha256(
      determinism.firstOutputTreeSha256,
      "first output tree SHA-256",
    );
    const second = expectSha256(
      determinism.secondOutputTreeSha256,
      "second output tree SHA-256",
    );
    expect(second).toBe(first);
    expect(expectInteger(determinism.fileCount, "determinism file count")).toBe(46);
    const outputFiles = expectObject(determinism.outputFiles, "determinism output files");
    expect(Object.keys(outputFiles)).toHaveLength(46);
    expect(outputFiles["asset-manifest.json"]).toBeDefined();
    expect(outputFiles["atlases/DeadHawg.png"]).toBeDefined();
    expect(outputFiles["packs/boneyards.json"]).toBeDefined();
    expect(outputFiles["packs/recipes.json"]).toBeDefined();
    expect(outputFiles["packs/waves.json"]).toBeDefined();
  });

  it("pins dimensions and representative entry hashes for every bundle family", async () => {
    const fixture = await loadFixture();
    const counts = expectObject(fixture.counts, "fixture counts");
    expect(expectInteger(counts.atlasCount, "atlas count")).toBe(41);
    expect(expectInteger(counts.bundleAtlasCount, "bundle atlas count")).toBe(28);
    expect(expectInteger(counts.looseAtlasCount, "loose atlas count")).toBe(13);
    expect(expectInteger(counts.spriteCount, "sprite count")).toBe(10_511);

    const atlases = expectArray(fixture.atlases, "fixture atlases");
    expect(atlases).toHaveLength(41);
    const atlasIds = new Set(
      atlases.map((value, index) =>
        expectString(expectObject(value, `atlas ${index}`).id, `atlas ${index} id`),
      ),
    );
    expect(atlasIds).toContain("DeadHawg");
    expect(atlasIds).toContain("loading:Wizards_dire_BG");

    const representatives = expectObject(
      fixture.bundleRepresentatives,
      "bundle representatives",
    );
    expect(Object.keys(representatives)).toHaveLength(28);
    expect(representatives.DeadHawg).toBe("DeadHawg.0");
    expect(representatives.Unholy).toBe("Unholy.0");
    const selected = expectObject(fixture.selected, "selected fixture records");
    const entryHashes = expectObject(selected.entryHashes, "selected entry hashes");
    expect(Object.keys(entryHashes)).toHaveLength(502);
    expect(entryHashes["DeadHawg.12"]).toBeDefined();
    for (const id of Object.values(representatives)) {
      expect(entryHashes[expectString(id, "bundle representative id")]).toBeDefined();
    }
    for (const [id, hash] of Object.entries(entryHashes)) {
      expect(expectSha256(hash, `entry hash ${id}`)).toHaveLength(64);
    }
  });

  it("resolves every landed scene and menu reference", async () => {
    const fixture = await loadFixture();
    const references = expectObject(fixture.references, "fixture references");
    const sceneIds = expectArray(references.sceneSpriteIds, "scene sprite ids");
    const menuArtIds = expectArray(references.menuArtIds, "menu art ids");
    const menuFontIds = expectArray(references.menuFontIds, "menu font ids");
    expect(sceneIds).toHaveLength(378);
    expect(menuArtIds).toHaveLength(107);
    expect(menuFontIds).toHaveLength(4);
    expect(sceneIds).toContain("DeadHawg.12");
    expect(sceneIds).toContain("native.framebuffer-clear");
    expect(menuArtIds).toContain("Wizards_dire_BG");
    expect(menuArtIds).toContain("Create.4");
    expect(menuArtIds).toContain("LevelPicker.1");
    expect(menuFontIds).toContain("Fonts.308-349");
    expect(menuFontIds).toContain("Fonts.93-184");
    expect(menuFontIds).toContain("Segoe UI");
    expect(expectArray(references.unresolved, "unresolved references")).toEqual([]);

    const ids = new Set(
      [...sceneIds, ...menuArtIds, ...menuFontIds].map((value) =>
        expectString(value, "golden reference id"),
      ),
    );
    const resolutions = expectObject(references.resolutions, "golden resolutions");
    expect(ids.size).toBe(488);
    expect(Object.keys(resolutions)).toHaveLength(488);
    expect(resolutions["native.framebuffer-clear"]).toEqual({ kind: "special-draw" });
    for (const id of ids) {
      expect(resolutions[id], `golden asset reference does not resolve: ${id}`).toBeDefined();
    }
  });

  it("matches every recorded hash for a committed source file", async () => {
    const fixture = await loadFixture();
    const hashes = expectObject(fixture.committedSourceHashes, "committed source hashes");
    expect(Object.keys(hashes)).toHaveLength(8);
    expect(hashes["SolomonDarkModLoader/src/native_scene_capture/generated_atlas_spans.inl"])
      .toBeDefined();
    expect(hashes["tests/fixtures/webgame/scene-composition-goldens.json"])
      .toBeDefined();
    expect(hashes["tests/fixtures/webgame/menu-goldens.json"]).toBeDefined();
    expect(hashes["webgame-contracts/baseline-snapshots/menu-goldens.json"])
      .toBeDefined();
    expect(hashes["webgame/assets/asset-manifest.schema.json"]).toBeDefined();
    for (const [relativePath, recordedHash] of Object.entries(hashes)) {
      expect(await sha256File(path.join(REPO_ROOT, ...relativePath.split("/"))))
        .toBe(expectSha256(recordedHash, `committed source hash ${relativePath}`));
    }
  });
});
