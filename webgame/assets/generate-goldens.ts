import { mkdir, readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

import AjvModule from "ajv";
import type { ValidateFunction } from "ajv";

import { canonicalJson, writeCanonicalJson } from "./canonical-json.js";
import {
  collectGoldenReferences,
  MENU_GOLDEN_PATH,
  MENU_SHELL_GOLDEN_PATH,
  SCENE_GOLDEN_PATH,
} from "./golden-references.js";
import { GROUND_TRUTH_FILES, loadProductionGroundTruth } from "./ground-truth.js";
import { hashOutputTree, sha256Bytes, sha256File } from "./hash.js";
import type { AssetManifest } from "./types.js";
import {
  expectArray,
  expectInteger,
  expectObject,
  expectSha256,
  expectString,
} from "./validation.js";

const MANIFEST_SCHEMA_PATH = "webgame/assets/asset-manifest.schema.json";
const LOADING_ART_PATH = "assets/loading/Wizards_dire_BG.png";

interface GoldenOptions {
  readonly repoRoot: string;
  readonly firstBuild: string;
  readonly secondBuild: string;
  readonly output: string;
}

function parseArguments(arguments_: readonly string[]): GoldenOptions {
  const values = new Map<string, string>();
  for (let index = 0; index < arguments_.length; index += 1) {
    const flag = arguments_[index];
    if (flag === undefined || !["--repo-root", "--first-build", "--second-build", "--output"].includes(flag)) {
      throw new Error(`unknown golden-generator option: ${flag ?? "<missing>"}`);
    }
    if (values.has(flag)) {
      throw new Error(`golden-generator option is duplicated: ${flag}`);
    }
    const value = arguments_[index + 1];
    if (value === undefined || value.startsWith("--")) {
      throw new Error(`golden-generator option requires a value: ${flag}`);
    }
    values.set(flag, value);
    index += 1;
  }
  const firstBuild = values.get("--first-build");
  const secondBuild = values.get("--second-build");
  if (firstBuild === undefined || secondBuild === undefined) {
    throw new Error("--first-build and --second-build are required");
  }
  const repoRoot = path.resolve(
    values.get("--repo-root") ?? path.resolve(import.meta.dirname, "..", ".."),
  );
  return {
    repoRoot,
    firstBuild: path.resolve(firstBuild),
    secondBuild: path.resolve(secondBuild),
    output: path.resolve(
      values.get("--output")
        ?? path.join(repoRoot, "webgame", "assets", "fixtures", "asset-manifest-goldens.json"),
    ),
  };
}

async function readJson(file: string): Promise<unknown> {
  return JSON.parse(await readFile(file, "utf8")) as unknown;
}

async function loadManifest(
  buildRoot: string,
  validate: ValidateFunction,
): Promise<AssetManifest> {
  const value = await readJson(path.join(buildRoot, "asset-manifest.json"));
  if (!validate(value)) {
    throw new Error(`asset manifest schema failed in ${buildRoot}: ${JSON.stringify(validate.errors)}`);
  }
  return value as AssetManifest;
}

function resolveKind(
  manifest: AssetManifest,
  id: string,
): "entry" | "alias" | "font-group" | "special-draw" | undefined {
  if (Object.hasOwn(manifest.entries, id)) {
    return "entry";
  }
  if (Object.hasOwn(manifest.aliases, id)) {
    return "alias";
  }
  if (Object.hasOwn(manifest.fontGroups, id)) {
    return "font-group";
  }
  if (Object.hasOwn(manifest.specialDraws, id)) {
    return "special-draw";
  }
  return undefined;
}

async function committedFileHashes(
  repoRoot: string,
  goldenSourceHashes: Readonly<Record<string, string>>,
): Promise<Record<string, string>> {
  const paths = [
    MANIFEST_SCHEMA_PATH,
    GROUND_TRUTH_FILES.inventory,
    GROUND_TRUTH_FILES.objectMap,
    GROUND_TRUTH_FILES.atlasSpans,
    LOADING_ART_PATH,
  ];
  const output: Record<string, string> = { ...goldenSourceHashes };
  for (const relativePath of paths) {
    output[relativePath] = await sha256File(path.join(repoRoot, ...relativePath.split("/")));
  }
  return output;
}

function outputFileMap(
  files: readonly { readonly file: string; readonly bytes: number; readonly sha256: string }[],
): Record<string, { readonly bytes: number; readonly sha256: string }> {
  const output: Record<string, { readonly bytes: number; readonly sha256: string }> = {};
  for (const file of files) {
    if (Object.hasOwn(output, file.file)) {
      throw new Error(`determinism inventory is ambiguous because ${file.file} is duplicated`);
    }
    output[file.file] = { bytes: file.bytes, sha256: file.sha256 };
  }
  return output;
}

async function generate(options: GoldenOptions): Promise<void> {
  const schema = expectObject(
    await readJson(path.join(options.repoRoot, ...MANIFEST_SCHEMA_PATH.split("/"))),
    "asset manifest schema",
  );
  const ajv = new AjvModule.default({ allErrors: true, strict: true });
  const validate = ajv.compile(schema);
  const [firstTree, secondTree, firstManifest, secondManifest, references, groundTruth] = await Promise.all([
    hashOutputTree(options.firstBuild),
    hashOutputTree(options.secondBuild),
    loadManifest(options.firstBuild, validate),
    loadManifest(options.secondBuild, validate),
    collectGoldenReferences(options.repoRoot),
    loadProductionGroundTruth(options.repoRoot),
  ]);
  if (
    firstTree.sha256 !== secondTree.sha256
    || canonicalJson(firstTree.files) !== canonicalJson(secondTree.files)
  ) {
    throw new Error(
      `double build is not byte-identical: ${firstTree.sha256} != ${secondTree.sha256}`,
    );
  }
  if (canonicalJson(firstManifest) !== canonicalJson(secondManifest)) {
    throw new Error("double build manifests differ despite output inventory comparison");
  }

  const allReferences = new Set([
    ...references.sceneSpriteIds,
    ...references.menuArtIds,
    ...references.menuFontIds,
  ]);
  const resolutions: Record<string, { readonly kind: string; readonly target?: string }> = {};
  const selectedEntryIds = new Set<string>();
  const referencedAliasIds = new Set<string>();
  const referencedFontGroupIds = new Set<string>();
  const referencedSpecialIds = new Set<string>();
  for (const id of [...allReferences].sort()) {
    const kind = resolveKind(firstManifest, id);
    if (kind === undefined) {
      throw new Error(`golden asset reference does not resolve: ${id}`);
    }
    if (kind === "entry") {
      selectedEntryIds.add(id);
      resolutions[id] = { kind };
    } else if (kind === "alias") {
      const target = firstManifest.aliases[id];
      if (target === undefined || !Object.hasOwn(firstManifest.entries, target)) {
        throw new Error(`golden alias ${id} points to missing entry ${target ?? "<undefined>"}`);
      }
      selectedEntryIds.add(target);
      referencedAliasIds.add(id);
      resolutions[id] = { kind, target };
    } else if (kind === "font-group") {
      referencedFontGroupIds.add(id);
      resolutions[id] = { kind };
    } else {
      referencedSpecialIds.add(id);
      resolutions[id] = { kind };
    }
  }

  const bundleRepresentatives: Record<string, string> = {};
  for (const bundle of groundTruth.bundles) {
    const id = `${bundle.name}.0`;
    if (!Object.hasOwn(firstManifest.entries, id)) {
      throw new Error(`bundle family ${bundle.name} has no record-zero representative`);
    }
    bundleRepresentatives[bundle.name] = id;
    selectedEntryIds.add(id);
  }
  const entryHashes: Record<string, string> = {};
  for (const id of [...selectedEntryIds].sort()) {
    const entry = firstManifest.entries[id];
    if (entry === undefined) {
      throw new Error(`selected fixture entry disappeared: ${id}`);
    }
    entryHashes[id] = sha256Bytes(canonicalJson(entry));
  }
  const aliasMappings: Record<string, string> = {};
  for (const id of [...referencedAliasIds].sort()) {
    const target = firstManifest.aliases[id];
    if (target === undefined) {
      throw new Error(`selected alias disappeared: ${id}`);
    }
    aliasMappings[id] = target;
  }
  const fontGroupHashes: Record<string, string> = {};
  for (const id of [...referencedFontGroupIds].sort()) {
    const group = firstManifest.fontGroups[id];
    if (group === undefined) {
      throw new Error(`selected font group disappeared: ${id}`);
    }
    fontGroupHashes[id] = sha256Bytes(canonicalJson(group));
  }
  const specialDrawHashes: Record<string, string> = {};
  for (const id of [...referencedSpecialIds].sort()) {
    const special = firstManifest.specialDraws[id];
    if (special === undefined) {
      throw new Error(`selected special draw disappeared: ${id}`);
    }
    specialDrawHashes[id] = sha256Bytes(canonicalJson(special));
  }

  const report = expectObject(
    await readJson(path.join(options.firstBuild, "build-report.json")),
    "asset build report",
  );
  const emitted = expectObject(report.emittedAssetBytes, "asset build emitted bytes");
  const wavePack = expectObject(
    await readJson(path.join(options.firstBuild, "packs", "waves.json")),
    "wave pack",
  );
  const ignoredFlags = expectArray(
    wavePack.ignoredNativeFlagTokens,
    "wave pack ignoredNativeFlagTokens",
  ).map((value, index) => expectString(value, `ignoredNativeFlagTokens[${index}]`));
  const fixture = {
    schema: "solomon-dark-web-asset-manifest-goldens-v1",
    generatedBy: "webgame/assets/generate-goldens.ts",
    manifestSchema: firstManifest.schema,
    determinism: {
      firstOutputTreeSha256: firstTree.sha256,
      secondOutputTreeSha256: secondTree.sha256,
      fileCount: firstTree.files.length,
      outputFiles: outputFileMap(firstTree.files),
    },
    counts: firstManifest.summary,
    emittedBytes: {
      atlases: expectInteger(emitted.atlases, "emittedAssetBytes.atlases"),
      boneyards: expectInteger(emitted.boneyards, "emittedAssetBytes.boneyards"),
      waves: expectInteger(emitted.waves, "emittedAssetBytes.waves"),
      recipes: expectInteger(emitted.recipes, "emittedAssetBytes.recipes"),
      total: expectInteger(emitted.total, "emittedAssetBytes.total"),
    },
    atlases: firstManifest.atlases.map((atlas) => ({
      id: atlas.id,
      file: atlas.file,
      width: atlas.width,
      height: atlas.height,
      bytes: atlas.bytes,
      sha256: atlas.sha256,
    })),
    bundleRepresentatives,
    references: {
      sceneSpriteIds: [...references.sceneSpriteIds].sort(),
      menuArtIds: [...references.menuArtIds].sort(),
      menuFontIds: [...references.menuFontIds].sort(),
      resolutions,
      unresolved: [],
    },
    selected: {
      entryHashes,
      aliasMappings,
      fontGroupHashes,
      specialDrawHashes,
    },
    packDescriptors: firstManifest.packs,
    ignoredNativeFlagTokens: ignoredFlags,
    committedSourceHashes: await committedFileHashes(options.repoRoot, references.sourceHashes),
    manifestSha256: expectSha256(
      firstTree.files.find((file) => file.file === "asset-manifest.json")?.sha256,
      "asset-manifest output SHA-256",
    ),
    sourceGoldenPaths: [
      SCENE_GOLDEN_PATH,
      MENU_GOLDEN_PATH,
      MENU_SHELL_GOLDEN_PATH,
    ],
  };
  await mkdir(path.dirname(options.output), { recursive: true });
  await writeCanonicalJson(options.output, fixture);
  process.stdout.write(canonicalJson({
    output: options.output,
    outputTreeSha256: firstTree.sha256,
    selectedEntries: Object.keys(entryHashes).length,
    resolvedReferences: Object.keys(resolutions).length,
  }));
}

const entrypoint = process.argv[1];
if (entrypoint !== undefined && fileURLToPath(import.meta.url) === path.resolve(entrypoint)) {
  generate(parseArguments(process.argv.slice(2))).catch((error: unknown) => {
    console.error(error instanceof Error ? error.message : String(error));
    process.exitCode = 1;
  });
}
