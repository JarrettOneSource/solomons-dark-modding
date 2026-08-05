import { readFile } from "node:fs/promises";
import path from "node:path";

import type {
  AssetGroundTruth,
  BundleGroundTruth,
  FileGroundTruth,
} from "./types.js";
import {
  expectArray,
  expectInteger,
  expectObject,
  expectSha256,
  expectString,
  expectUnique,
} from "./validation.js";

const INVENTORY_PATH = "docs/reverse-engineering/native-content-inventory.json";
const OBJECT_MAP_PATH = "docs/reverse-engineering/native-asset-object-map.json";
const ENEMY_CATALOG_PATH = "docs/reverse-engineering/native-enemy-catalog.json";

function foldAsciiCase(value: string): string {
  return value.replace(/[A-Z]/gu, (character) =>
    String.fromCharCode(character.charCodeAt(0) + 0x20));
}

export function compareNativeNames(left: string, right: string): number {
  const foldedLeft = foldAsciiCase(left);
  const foldedRight = foldAsciiCase(right);
  if (foldedLeft !== foldedRight) {
    return foldedLeft < foldedRight ? -1 : 1;
  }
  return left === right ? 0 : left < right ? -1 : 1;
}

async function readJson(repoRoot: string, relativePath: string): Promise<unknown> {
  const text = await readFile(path.join(repoRoot, ...relativePath.split("/")), "utf8");
  return JSON.parse(text) as unknown;
}

function inventoryFile(value: unknown, label: string): FileGroundTruth {
  const entry = expectObject(value, label);
  return {
    path: expectString(entry.path, `${label}.path`),
    bytes: expectInteger(entry.bytes, `${label}.bytes`),
    sha256: expectSha256(entry.sha256, `${label}.sha256`),
  };
}

export async function loadProductionGroundTruth(
  repoRoot: string,
): Promise<AssetGroundTruth> {
  const inventory = expectObject(
    await readJson(repoRoot, INVENTORY_PATH),
    "native content inventory",
  );
  if (inventory.schema !== "solomon-dark-native-content-inventory/v1") {
    throw new Error("native content inventory schema drifted");
  }
  const objectMap = expectObject(
    await readJson(repoRoot, OBJECT_MAP_PATH),
    "native asset object map",
  );
  if (objectMap.schema !== "solomon-dark-native-asset-object-map-v1") {
    throw new Error("native asset object map schema drifted");
  }
  const objectAtlases = expectArray(objectMap.atlases, "native object-map atlases");
  if (objectAtlases.length !== 28) {
    throw new Error(`native object map must contain 28 atlases, found ${objectAtlases.length}`);
  }
  const recordCounts = new Map<string, number>();
  for (const [index, rawAtlas] of objectAtlases.entries()) {
    const atlas = expectObject(rawAtlas, `native object-map atlas[${index}]`);
    const name = expectString(atlas.name, `native object-map atlas[${index}].name`);
    if (recordCounts.has(name)) {
      throw new Error(`native object map is ambiguous because ${name} is duplicated`);
    }
    recordCounts.set(
      name,
      expectInteger(atlas.record_count, `native object-map ${name}.record_count`),
    );
  }

  const bundles: BundleGroundTruth[] = [];
  for (const [index, rawAtlas] of expectArray(inventory.atlases, "inventory atlases").entries()) {
    const atlas = expectObject(rawAtlas, `inventory atlas[${index}]`);
    const name = expectString(atlas.name, `inventory atlas[${index}].name`);
    const recordCount = recordCounts.get(name);
    if (recordCount === undefined) {
      throw new Error(`inventory atlas ${name} has no native object-map identity`);
    }
    const inventoryRecordCount = expectInteger(
      atlas.record_count,
      `inventory atlas ${name}.record_count`,
    );
    if (inventoryRecordCount !== recordCount) {
      throw new Error(
        `${name} record count disagrees between inventory (${inventoryRecordCount}) `
          + `and native object map (${recordCount})`,
      );
    }
    const pages = expectArray(atlas.pages, `inventory atlas ${name}.pages`);
    if (pages.length !== 1) {
      throw new Error(`${name} must have exactly one shipped PNG page, found ${pages.length}`);
    }
    const page = expectObject(pages[0], `inventory atlas ${name}.pages[0]`);
    bundles.push({
      name,
      bundlePath: expectString(atlas.bundle_path, `inventory atlas ${name}.bundle_path`),
      bundleBytes: expectInteger(atlas.bundle_bytes, `inventory atlas ${name}.bundle_bytes`),
      bundleSha256: expectSha256(
        atlas.bundle_sha256,
        `inventory atlas ${name}.bundle_sha256`,
      ),
      recordCount,
      atlasPath: expectString(page.path, `inventory atlas ${name}.page.path`),
      atlasBytes: expectInteger(page.bytes, `inventory atlas ${name}.page.bytes`),
      atlasSha256: expectSha256(page.sha256, `inventory atlas ${name}.page.sha256`),
      atlasWidth: expectInteger(page.width, `inventory atlas ${name}.page.width`),
      atlasHeight: expectInteger(page.height, `inventory atlas ${name}.page.height`),
    });
    recordCounts.delete(name);
  }
  if (recordCounts.size !== 0) {
    throw new Error(
      `inventory is missing native object-map atlas(es): ${[...recordCounts.keys()].sort().join(", ")}`,
    );
  }
  if (bundles.length !== 28) {
    throw new Error(`inventory must contain 28 bundle families, found ${bundles.length}`);
  }
  expectUnique(bundles, (bundle) => bundle.name, "bundle family names");
  expectUnique(bundles, (bundle) => bundle.bundlePath.toLowerCase(), "bundle source paths");

  const looseImages = expectArray(inventory.loose_images, "inventory loose images").map(
    (rawImage, index) => {
      const image = expectObject(rawImage, `inventory loose image[${index}]`);
      return {
        path: expectString(image.path, `inventory loose image[${index}].path`),
        bytes: expectInteger(image.bytes, `inventory loose image[${index}].bytes`),
        sha256: expectSha256(image.sha256, `inventory loose image[${index}].sha256`),
        width: expectInteger(image.width, `inventory loose image[${index}].width`),
        height: expectInteger(image.height, `inventory loose image[${index}].height`),
      };
    },
  );
  if (looseImages.length !== 12) {
    throw new Error(`inventory must contain 12 loose images, found ${looseImages.length}`);
  }
  expectUnique(looseImages, (image) => image.path.toLowerCase(), "loose-image paths");

  const installedFiles = expectArray(inventory.files, "inventory files")
    .map((value, index) => ({
      raw: expectObject(value, `inventory file[${index}]`),
      index,
    }))
    .filter(({ raw }) => raw.scope === "installed_content");
  const boneyards = installedFiles
    .filter(({ raw }) => raw.kind === "boneyard")
    .map(({ raw, index }) => inventoryFile(raw, `inventory file[${index}]`))
    .sort((left, right) => compareNativeNames(left.path, right.path));
  if (boneyards.length !== 4) {
    throw new Error(`inventory must contain four installed Boneyards, found ${boneyards.length}`);
  }
  expectUnique(boneyards, (entry) => entry.path.toLowerCase(), "Boneyard source paths");

  const waveCandidates = installedFiles
    .filter(({ raw }) => raw.path === "data/wave.txt")
    .map(({ raw, index }) => inventoryFile(raw, `inventory file[${index}]`));
  if (waveCandidates.length !== 1) {
    throw new Error(
      `inventory must identify exactly one data/wave.txt, found ${waveCandidates.length}`,
    );
  }
  const wave = waveCandidates[0];
  if (wave === undefined) {
    throw new Error("inventory data/wave.txt lookup failed after uniqueness validation");
  }

  const enemyCatalog = expectObject(
    await readJson(repoRoot, ENEMY_CATALOG_PATH),
    "native enemy catalog",
  );
  if (enemyCatalog.schema !== "solomon-dark-native-enemy-catalog-v1") {
    throw new Error("native enemy catalog schema drifted");
  }
  const waveFlags = new Map<string, number>();
  for (const [index, rawFlag] of expectArray(
    enemyCatalog.wave_flags,
    "native enemy wave flags",
  ).entries()) {
    const flag = expectObject(rawFlag, `native enemy wave flag[${index}]`);
    const token = expectString(flag.token, `native enemy wave flag[${index}].token`);
    if (waveFlags.has(token)) {
      throw new Error(`native enemy wave flags are ambiguous because ${token} is duplicated`);
    }
    waveFlags.set(
      token,
      expectInteger(flag.internal_code, `native enemy wave flag[${index}].internal_code`),
    );
  }
  if (waveFlags.size !== 43) {
    throw new Error(`native enemy catalog must contain 43 unique wave flags, found ${waveFlags.size}`);
  }

  return {
    bundles: bundles.sort((left, right) => compareNativeNames(left.name, right.name)),
    looseImages: [...looseImages].sort((left, right) => compareNativeNames(left.path, right.path)),
    boneyards,
    wave,
    waveFlags,
  };
}

export const GROUND_TRUTH_FILES = Object.freeze({
  inventory: INVENTORY_PATH,
  objectMap: OBJECT_MAP_PATH,
  enemyCatalog: ENEMY_CATALOG_PATH,
  atlasSpans: "SolomonDarkModLoader/src/native_scene_capture/generated_atlas_spans.inl",
});
