import { constants as fsConstants } from "node:fs";
import {
  copyFile,
  mkdir,
  readFile,
  rename,
  rm,
  stat,
} from "node:fs/promises";
import path from "node:path";
import { promisify } from "node:util";
import { execFile } from "node:child_process";

import { writeCanonicalJson } from "./canonical-json.js";
import { compareNativeNames, GROUND_TRUTH_FILES } from "./ground-truth.js";
import { hashOutputTree, sha256Bytes, sha256File } from "./hash.js";
import { readPngDimensions } from "./png.js";
import {
  decodeBoneyards,
  decodeBundles,
  type DecodedBundle,
  type DecodedBundleRecord,
} from "./python-bridge.js";
import type {
  AssetEntry,
  AssetManifest,
  AtlasDescriptor,
  BuildInputs,
  BuildResult,
  FileGroundTruth,
  FontGroup,
  PackDescriptor,
  Provenance,
} from "./types.js";
import { expectArray, expectObject } from "./validation.js";
import { parseWaveFile } from "./wave.js";

const execFileAsync = promisify(execFile);
const LOADING_ART_SOURCE = "assets/loading/Wizards_dire_BG.png";
const LOADING_ART_ID = "Wizards_dire_BG";

function normalizeAbsolute(candidate: string, label: string): string {
  if (!path.isAbsolute(candidate)) {
    throw new Error(`${label} must be an absolute path: ${candidate}`);
  }
  return path.resolve(candidate);
}

function isInside(parent: string, candidate: string): boolean {
  if (path.parse(parent).root.toLowerCase() !== path.parse(candidate).root.toLowerCase()) {
    return false;
  }
  const relative = path.relative(parent, candidate);
  return relative === "" || (!relative.startsWith(`..${path.sep}`) && relative !== "..");
}

function validateBuildRoots(inputs: BuildInputs): {
  readonly repoRoot: string;
  readonly retailRoot: string;
  readonly outputRoot: string;
} {
  const repoRoot = normalizeAbsolute(inputs.repoRoot, "repository root");
  const retailRoot = normalizeAbsolute(inputs.retailRoot, "retail root");
  const outputRoot = normalizeAbsolute(inputs.outputRoot, "output root");
  if (isInside(retailRoot, outputRoot)) {
    throw new Error("asset output may not be the retail install or live below it");
  }
  if (outputRoot === path.parse(outputRoot).root) {
    throw new Error("asset output may not be a filesystem root");
  }
  if (isInside(outputRoot, repoRoot) || isInside(outputRoot, retailRoot)) {
    throw new Error("asset output may not contain the repository or retail install");
  }
  return { repoRoot, retailRoot, outputRoot };
}

function sourcePath(root: string, relativePath: string): string {
  if (
    path.posix.isAbsolute(relativePath)
    || relativePath.split("/").some((segment) => segment === ".." || segment === "")
  ) {
    throw new Error(`native inventory contains unsafe source path: ${relativePath}`);
  }
  const resolved = path.resolve(root, ...relativePath.split("/"));
  if (!isInside(root, resolved) || resolved === root) {
    throw new Error(`native inventory source escapes retail root: ${relativePath}`);
  }
  return resolved;
}

async function assertFileMatches(
  absolutePath: string,
  expected: FileGroundTruth,
  label: string,
): Promise<void> {
  const metadata = await stat(absolutePath);
  if (!metadata.isFile()) {
    throw new Error(`${label} is not a regular file: ${absolutePath}`);
  }
  if (metadata.size !== expected.bytes) {
    throw new Error(
      `${label} byte count drifted: expected ${expected.bytes}, found ${metadata.size}`,
    );
  }
  const actualHash = await sha256File(absolutePath);
  if (actualHash !== expected.sha256) {
    throw new Error(
      `${label} SHA-256 drifted: expected ${expected.sha256}, found ${actualHash}`,
    );
  }
}

async function verifyRetailInputs(inputs: BuildInputs, retailRoot: string): Promise<void> {
  for (const bundle of inputs.groundTruth.bundles) {
    await assertFileMatches(
      sourcePath(retailRoot, bundle.bundlePath),
      { path: bundle.bundlePath, bytes: bundle.bundleBytes, sha256: bundle.bundleSha256 },
      `${bundle.name} bundle`,
    );
    const atlasPath = sourcePath(retailRoot, bundle.atlasPath);
    await assertFileMatches(
      atlasPath,
      { path: bundle.atlasPath, bytes: bundle.atlasBytes, sha256: bundle.atlasSha256 },
      `${bundle.name} atlas`,
    );
    const dimensions = readPngDimensions(await readFile(atlasPath), `${bundle.name} atlas`);
    if (dimensions.width !== bundle.atlasWidth || dimensions.height !== bundle.atlasHeight) {
      throw new Error(
        `${bundle.name} atlas dimensions drifted: expected ${bundle.atlasWidth}x`
          + `${bundle.atlasHeight}, found ${dimensions.width}x${dimensions.height}`,
      );
    }
  }
  for (const image of inputs.groundTruth.looseImages) {
    const imagePath = sourcePath(retailRoot, image.path);
    await assertFileMatches(imagePath, image, `loose image ${image.path}`);
    const dimensions = readPngDimensions(await readFile(imagePath), image.path);
    if (dimensions.width !== image.width || dimensions.height !== image.height) {
      throw new Error(
        `${image.path} dimensions drifted: expected ${image.width}x${image.height}, `
          + `found ${dimensions.width}x${dimensions.height}`,
      );
    }
  }
  for (const boneyard of inputs.groundTruth.boneyards) {
    await assertFileMatches(
      sourcePath(retailRoot, boneyard.path),
      boneyard,
      `Boneyard ${boneyard.path}`,
    );
  }
  await assertFileMatches(
    sourcePath(retailRoot, inputs.groundTruth.wave.path),
    inputs.groundTruth.wave,
    "wave schedule",
  );
}

async function verifyAtlasGroundTruth(repoRoot: string, pythonExecutable: string): Promise<void> {
  try {
    await execFileAsync(
      pythonExecutable,
      [
        path.join(repoRoot, "tools", "generate_native_scene_atlas_spans.py"),
        "--source",
        path.join(repoRoot, ...GROUND_TRUTH_FILES.objectMap.split("/")),
        "--output",
        path.join(repoRoot, ...GROUND_TRUTH_FILES.atlasSpans.split("/")),
        "--check",
      ],
      { cwd: repoRoot, encoding: "utf8", windowsHide: true },
    );
  } catch (error: unknown) {
    if (typeof error === "object" && error !== null && "code" in error && error.code === "ENOENT") {
      throw new Error(`native atlas-span generator cannot run ${pythonExecutable}`, { cause: error });
    }
    throw new Error("native atlas spans are stale or their generator failed", { cause: error });
  }
}

function setUnique<T>(target: Record<string, T>, key: string, value: T, label: string): void {
  if (Object.hasOwn(target, key)) {
    throw new Error(`${label} is ambiguous because ${key} is duplicated`);
  }
  target[key] = value;
}

function integerRectangle(record: DecodedBundleRecord, bundle: DecodedBundle): {
  readonly x: number;
  readonly y: number;
  readonly width: number;
  readonly height: number;
} {
  const fields = [record.x, record.y, record.width, record.height];
  if (!fields.every(Number.isInteger)) {
    throw new Error(`${bundle.name}.${record.recordIndex} has a non-integral atlas rectangle`);
  }
  if (record.width <= 0 || record.height <= 0) {
    throw new Error(`${bundle.name}.${record.recordIndex} has a non-positive atlas rectangle`);
  }
  if (record.contentWidth !== record.width || record.contentHeight !== record.height) {
    throw new Error(
      `${bundle.name}.${record.recordIndex} content dimensions disagree with its atlas rectangle`,
    );
  }
  return { x: record.x, y: record.y, width: record.width, height: record.height };
}

function bundleRecordEntry(
  bundle: DecodedBundle,
  atlasWidth: number,
  atlasHeight: number,
  record: DecodedBundleRecord,
): AssetEntry {
  const rect = integerRectangle(record, bundle);
  if (rect.x < 0 || rect.y < 0 || rect.x + rect.width > atlasWidth || rect.y + rect.height > atlasHeight) {
    throw new Error(`${bundle.name}.${record.recordIndex} lies outside its shipped atlas`);
  }
  if (record.logicalWidth <= 0 || record.logicalHeight <= 0) {
    throw new Error(`${bundle.name}.${record.recordIndex} has a non-positive logical canvas`);
  }
  const trimOriginX = (record.logicalWidth - record.contentWidth) / 2 + record.centerOffsetX;
  const trimOriginY = (record.logicalHeight - record.contentHeight) / 2 + record.centerOffsetY;
  return {
    kind: "sprite",
    atlas: bundle.name,
    rect,
    pivot: { x: -trimOriginX, y: -trimOriginY },
    logicalSize: { width: record.logicalWidth, height: record.logicalHeight },
    rotated: record.rotated,
    points: record.points,
    provenance: {
      sourceBundleFilename: bundle.relativePath,
      recordIndex: record.recordIndex,
      sourceBytesSha256: record.sourceBytesSha256,
      sourceOffset: record.sourceOffset,
      sourceLength: record.sourceLength,
    },
  };
}

function fileProvenance(filename: string, hash: string): Provenance {
  return { sourceBundleFilename: filename, recordIndex: 0, sourceBytesSha256: hash };
}

async function copyExact(source: string, destination: string): Promise<number> {
  await copyFile(source, destination, fsConstants.COPYFILE_EXCL);
  return (await stat(destination)).size;
}

function countRecipeEntries(recipes: readonly Record<string, unknown>[]): number {
  let count = 0;
  for (const [sourceIndex, source] of recipes.entries()) {
    const groups = expectObject(source.recipes, `recipe source[${sourceIndex}].recipes`);
    for (const [name, value] of Object.entries(groups)) {
      count += expectArray(value, `recipe source[${sourceIndex}].recipes.${name}`).length;
    }
  }
  return count;
}

async function descriptorForPack(
  outputRoot: string,
  relativePath: string,
  entryCount: number,
): Promise<PackDescriptor> {
  const absolute = path.join(outputRoot, ...relativePath.split("/"));
  return {
    file: relativePath,
    bytes: (await stat(absolute)).size,
    sha256: await sha256File(absolute),
    entryCount,
  };
}

async function createOutputRoot(outputRoot: string): Promise<string> {
  const parent = path.dirname(outputRoot);
  const outputName = path.basename(outputRoot);
  const staging = path.join(parent, `.${outputName}.partial-${String(process.pid)}`);
  try {
    await stat(outputRoot);
    throw new Error(`asset output already exists: ${outputRoot}`);
  } catch (error: unknown) {
    if (!(typeof error === "object" && error !== null && "code" in error && error.code === "ENOENT")) {
      throw error;
    }
  }
  try {
    await stat(staging);
    throw new Error(`asset staging path already exists: ${staging}`);
  } catch (error: unknown) {
    if (!(typeof error === "object" && error !== null && "code" in error && error.code === "ENOENT")) {
      throw error;
    }
  }
  await mkdir(staging);
  return staging;
}

export async function buildAssets(inputs: BuildInputs): Promise<BuildResult> {
  const { repoRoot, retailRoot, outputRoot } = validateBuildRoots(inputs);
  await verifyAtlasGroundTruth(repoRoot, inputs.pythonExecutable);
  await verifyRetailInputs(inputs, retailRoot);
  const [decodedBundles, decodedBoneyards] = await Promise.all([
    decodeBundles(
      repoRoot,
      retailRoot,
      inputs.pythonExecutable,
      inputs.groundTruth.bundles,
    ),
    decodeBoneyards(
      repoRoot,
      retailRoot,
      inputs.pythonExecutable,
      inputs.groundTruth.boneyards,
    ),
  ]);
  if (decodedBundles.length !== inputs.groundTruth.bundles.length) {
    throw new Error(
      `bundle decoder returned ${decodedBundles.length} families for `
        + `${inputs.groundTruth.bundles.length} native atlases`,
    );
  }

  const stagingRoot = await createOutputRoot(outputRoot);
  try {
    await mkdir(path.join(stagingRoot, "atlases"));
    await mkdir(path.join(stagingRoot, "atlases", "loose"));
    await mkdir(path.join(stagingRoot, "packs"));

    const atlases: AtlasDescriptor[] = [];
    const entries: Record<string, AssetEntry> = {};
    const aliases: Record<string, string> = {};
    const fontGroups: Record<string, FontGroup> = {};
    let atlasBytes = 0;

    for (const [bundleIndex, bundleTruth] of inputs.groundTruth.bundles.entries()) {
      const bundle = decodedBundles[bundleIndex];
      if (bundle === undefined || bundle.name !== bundleTruth.name) {
        throw new Error(`decoded bundle order diverged at native atlas ${bundleTruth.name}`);
      }
      if (
        bundle.bytes !== bundleTruth.bundleBytes
        || bundle.sha256 !== bundleTruth.bundleSha256
        || bundle.records.length !== bundleTruth.recordCount
      ) {
        throw new Error(`${bundle.name} decoder output disagrees with native inventory`);
      }
      const atlasFile = `atlases/${bundle.name}.png`;
      atlasBytes += await copyExact(
        sourcePath(retailRoot, bundleTruth.atlasPath),
        path.join(stagingRoot, ...atlasFile.split("/")),
      );
      atlases.push({
        id: bundle.name,
        file: atlasFile,
        width: bundleTruth.atlasWidth,
        height: bundleTruth.atlasHeight,
        bytes: bundleTruth.atlasBytes,
        sha256: bundleTruth.atlasSha256,
        provenance: fileProvenance(bundleTruth.atlasPath, bundleTruth.atlasSha256),
      });
      for (const [recordIndex, record] of bundle.records.entries()) {
        if (record.recordIndex !== recordIndex) {
          throw new Error(
            `${bundle.name} record index ${record.recordIndex} is not contiguous at ${recordIndex}`,
          );
        }
        const id = `${bundle.name}.${String(recordIndex)}`;
        setUnique(
          entries,
          id,
          bundleRecordEntry(
            bundle,
            bundleTruth.atlasWidth,
            bundleTruth.atlasHeight,
            record,
          ),
          "native sprite ids",
        );
      }
      for (const group of bundle.fontGroups) {
        const groupId = `${bundle.name}.${String(group.firstRecord)}-${String(group.lastRecord)}`;
        if (group.glyphIds.length !== group.lastRecord - group.firstRecord + 1) {
          throw new Error(`${groupId} glyph count does not span its native record range`);
        }
        const glyphs: Record<string, string> = {};
        for (const [glyphIndex, glyphId] of group.glyphIds.entries()) {
          const target = `${bundle.name}.${String(group.firstRecord + glyphIndex)}`;
          if (!Object.hasOwn(entries, target)) {
            throw new Error(`${groupId} resolves glyph ${glyphId} to missing ${target}`);
          }
          const alias = `${groupId}@0x${(0x10 + glyphId * 0xD4).toString(16).toUpperCase()}`;
          setUnique(aliases, alias, target, "native font glyph aliases");
          setUnique(glyphs, String(glyphId), target, `${groupId} glyph ids`);
        }
        setUnique(
          fontGroups,
          groupId,
          {
            atlas: bundle.name,
            firstRecord: group.firstRecord,
            lastRecord: group.lastRecord,
            metrics: group.metrics,
            kerning: group.kerningPairs,
            glyphs,
            provenance: {
              sourceBundleFilename: bundle.relativePath,
              recordIndex: group.groupIndex,
              sourceBytesSha256: group.sourceBytesSha256,
              sourceOffset: group.sourceOffset,
              sourceLength: group.sourceLength,
            },
          },
          "native font group ids",
        );
      }
    }

    for (const image of inputs.groundTruth.looseImages) {
      const id = path.posix.basename(image.path);
      const atlasId = `loose:${id}`;
      const atlasFile = `atlases/loose/${id}`;
      atlasBytes += await copyExact(
        sourcePath(retailRoot, image.path),
        path.join(stagingRoot, ...atlasFile.split("/")),
      );
      atlases.push({
        id: atlasId,
        file: atlasFile,
        width: image.width,
        height: image.height,
        bytes: image.bytes,
        sha256: image.sha256,
        provenance: fileProvenance(image.path, image.sha256),
      });
      setUnique(
        entries,
        id,
        {
          kind: "loose-image",
          atlas: atlasId,
          rect: { x: 0, y: 0, width: image.width, height: image.height },
          pivot: { x: 0, y: 0 },
          logicalSize: { width: image.width, height: image.height },
          rotated: false,
          points: [],
          provenance: {
            ...fileProvenance(image.path, image.sha256),
            sourceOffset: 0,
            sourceLength: image.bytes,
          },
        },
        "loose native image ids",
      );
    }

    if (inputs.includeLoadingArt) {
      const loadingPath = sourcePath(repoRoot, LOADING_ART_SOURCE);
      const loadingBytes = await readFile(loadingPath);
      const loadingDimensions = readPngDimensions(loadingBytes, LOADING_ART_SOURCE);
      const loadingHash = sha256Bytes(loadingBytes);
      const atlasFile = `atlases/loading/${LOADING_ART_ID}.png`;
      await mkdir(path.join(stagingRoot, "atlases", "loading"));
      atlasBytes += await copyExact(
        loadingPath,
        path.join(stagingRoot, ...atlasFile.split("/")),
      );
      const atlasId = `loading:${LOADING_ART_ID}`;
      atlases.push({
        id: atlasId,
        file: atlasFile,
        width: loadingDimensions.width,
        height: loadingDimensions.height,
        bytes: loadingBytes.length,
        sha256: loadingHash,
        provenance: fileProvenance(LOADING_ART_SOURCE, loadingHash),
      });
      setUnique(
        entries,
        LOADING_ART_ID,
        {
          kind: "loose-image",
          atlas: atlasId,
          rect: { x: 0, y: 0, ...loadingDimensions },
          pivot: { x: 0, y: 0 },
          logicalSize: loadingDimensions,
          rotated: false,
          points: [],
          provenance: {
            ...fileProvenance(LOADING_ART_SOURCE, loadingHash),
            sourceOffset: 0,
            sourceLength: loadingBytes.length,
          },
        },
        "loading art ids",
      );
    }

    const boneyardPackEntries: Record<string, unknown>[] = [];
    const recipePackEntries: Record<string, unknown>[] = [];
    for (const [index, decoded] of decodedBoneyards.entries()) {
      const filename = inputs.groundTruth.boneyards[index]?.path;
      if (filename === undefined) {
        throw new Error(`decoded Boneyard ${index} has no native inventory source`);
      }
      const recipes = expectObject(decoded.recipes, `${filename}.recipes`);
      const boneyard = { ...decoded };
      delete boneyard.recipes;
      boneyardPackEntries.push(boneyard);
      recipePackEntries.push({
        filename,
        provenance: decoded.provenance,
        recipes,
      });
    }
    const boneyardPack = {
      schema: "solomon-dark-web-boneyards-v1",
      decoder: "tools/inspect_boneyard.py + tools/decode_boneyard_scripts.py",
      boneyards: boneyardPackEntries,
    };
    const recipePack = {
      schema: "solomon-dark-web-recipes-v1",
      decoder: "tools/decode_boneyard_scripts.py",
      sources: recipePackEntries,
    };
    const waveBytes = await readFile(sourcePath(retailRoot, inputs.groundTruth.wave.path));
    const parsedWaves = parseWaveFile(
      waveBytes,
      inputs.groundTruth.wave.path,
      inputs.groundTruth.waveFlags,
    );
    const wavePack = {
      schema: "solomon-dark-web-waves-v1",
      provenance: fileProvenance(inputs.groundTruth.wave.path, inputs.groundTruth.wave.sha256),
      ...parsedWaves,
    };
    await writeCanonicalJson(path.join(stagingRoot, "packs", "boneyards.json"), boneyardPack);
    await writeCanonicalJson(path.join(stagingRoot, "packs", "recipes.json"), recipePack);
    await writeCanonicalJson(path.join(stagingRoot, "packs", "waves.json"), wavePack);

    const packs = {
      boneyards: await descriptorForPack(
        stagingRoot,
        "packs/boneyards.json",
        boneyardPackEntries.length,
      ),
      recipes: await descriptorForPack(
        stagingRoot,
        "packs/recipes.json",
        countRecipeEntries(recipePackEntries),
      ),
      waves: await descriptorForPack(
        stagingRoot,
        "packs/waves.json",
        parsedWaves.waves.length,
      ),
    };
    const manifest: AssetManifest = {
      schema: "solomon-dark-web-asset-manifest-v1",
      nativeIdFormat: "<Atlas>.<record-index>",
      sources: {
        bundleDecoder: "tools/extract_bundles.py",
        boneyardDecoder: "tools/decode_boneyard_scripts.py",
        nativeAssetObjectMap: GROUND_TRUTH_FILES.objectMap,
        nativeSceneAtlasSpans: GROUND_TRUTH_FILES.atlasSpans,
        nativeContentInventory: GROUND_TRUTH_FILES.inventory,
      },
      summary: {
        atlasCount: atlases.length,
        bundleAtlasCount: inputs.groundTruth.bundles.length,
        looseAtlasCount: atlases.length - inputs.groundTruth.bundles.length,
        spriteCount: Object.keys(entries).length,
        aliasCount: Object.keys(aliases).length,
        fontGroupCount: Object.keys(fontGroups).length,
      },
      atlases: atlases.sort((left, right) => compareNativeNames(left.id, right.id)),
      entries,
      aliases,
      fontGroups,
      specialDraws: {
        "native.framebuffer-clear": {
          kind: "framebuffer-clear",
          sourceGoldenFilename: "tests/fixtures/webgame/scene-composition-goldens.json",
        },
        "native.textured-quad@0x41474C": {
          kind: "textured-quad",
          sourceGoldenFilename: "tests/fixtures/webgame/scene-composition-goldens.json",
        },
        "Segoe UI": {
          kind: "system-font",
          sourceGoldenFilename:
            "tests/fixtures/webgame/menufix-preview-overlay/menu-goldens.json",
        },
      },
      packs,
    };
    await writeCanonicalJson(path.join(stagingRoot, "asset-manifest.json"), manifest);
    const emittedAssetBytes = {
      atlases: atlasBytes,
      boneyards: packs.boneyards.bytes,
      waves: packs.waves.bytes,
      recipes: packs.recipes.bytes,
    };
    await writeCanonicalJson(path.join(stagingRoot, "build-report.json"), {
      schema: "solomon-dark-web-asset-build-report-v1",
      emittedAssetBytes: {
        ...emittedAssetBytes,
        total: Object.values(emittedAssetBytes).reduce((sum, bytes) => sum + bytes, 0),
      },
      sourceCounts: {
        bundles: inputs.groundTruth.bundles.length,
        looseImages: inputs.groundTruth.looseImages.length + (inputs.includeLoadingArt ? 1 : 0),
        boneyards: inputs.groundTruth.boneyards.length,
        waves: parsedWaves.waves.length,
        recipes: packs.recipes.entryCount,
      },
    });

    const outputTree = await hashOutputTree(stagingRoot);
    const metadata = outputTree.files
      .filter((file) => file.file === "asset-manifest.json" || file.file === "build-report.json")
      .reduce((sum, file) => sum + file.bytes, 0);
    const categoryBytes = {
      ...emittedAssetBytes,
      metadata,
      total: outputTree.files.reduce((sum, file) => sum + file.bytes, 0),
    };
    const result = {
      manifest,
      files: outputTree.files,
      outputTreeSha256: outputTree.sha256,
      categoryBytes,
    };
    await rename(stagingRoot, outputRoot);
    return result;
  } catch (error: unknown) {
    await rm(stagingRoot, { recursive: true, force: true });
    throw error;
  }
}
