import { copyFile, mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import os from "node:os";
import path from "node:path";

import AjvModule from "ajv";
import { afterEach, describe, expect, it } from "vitest";

import { buildAssets } from "../builder.js";
import { compareNativeNames } from "../ground-truth.js";
import { sha256Bytes, sha256File } from "../hash.js";
import type { AssetGroundTruth } from "../types.js";
import { expectArray, expectObject, expectSha256, expectString } from "../validation.js";

const REPO_ROOT = path.resolve(import.meta.dirname, "..", "..", "..");
const BONEYARD_FIXTURE = path.join(
  REPO_ROOT,
  "tests",
  "fixtures",
  "boneyards",
  "flat_multiplayer_test.boneyard",
);
const ONE_PIXEL_PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=",
  "base64",
);

const temporaryRoots: string[] = [];

afterEach(async () => {
  for (const root of temporaryRoots.splice(0)) {
    await rm(root, { recursive: true, force: true });
  }
});

function oneRecordBundle(): Buffer {
  const bytes = Buffer.alloc(45);
  bytes.writeFloatLE(0, 0x00);
  bytes.writeFloatLE(0, 0x04);
  bytes.writeFloatLE(1, 0x08);
  bytes.writeFloatLE(1, 0x0C);
  bytes.writeInt32LE(1, 0x10);
  bytes.writeUInt32LE(1, 0x14);
  bytes.writeFloatLE(1, 0x18);
  bytes.writeFloatLE(1, 0x1C);
  bytes.writeFloatLE(0, 0x20);
  bytes.writeFloatLE(0, 0x24);
  bytes.writeUInt8(0, 0x28);
  bytes.writeUInt32LE(0, 0x29);
  return bytes;
}

async function prepareRetail(root: string): Promise<AssetGroundTruth> {
  const images = path.join(root, "images");
  const levels = path.join(root, "data", "levels");
  await mkdir(images, { recursive: true });
  await mkdir(levels, { recursive: true });
  const bundle = oneRecordBundle();
  await writeFile(path.join(images, "Test.bundle"), bundle);
  await writeFile(path.join(images, "Test.png"), ONE_PIXEL_PNG);
  await copyFile(BONEYARD_FIXTURE, path.join(levels, "test.boneyard"));
  const wave = Buffer.from(
    [
      "WAVE",
      "NEXT:1",
      "SPAWN:1",
      "SPAWNDELAY:1-1",
      "WAVEDELAY:1-1",
      "MAXENEMIES:1",
      "GROUP",
      "SKELETON:FLAG_WEAK",
      "ENDWAVE",
      "",
    ].join("\n"),
    "utf8",
  );
  await writeFile(path.join(root, "data", "wave.txt"), wave);
  const boneyardBytes = (await readFile(BONEYARD_FIXTURE)).length;
  return {
    bundles: [{
      name: "Test",
      bundlePath: "images/Test.bundle",
      bundleBytes: bundle.length,
      bundleSha256: sha256Bytes(bundle),
      recordCount: 1,
      atlasPath: "images/Test.png",
      atlasBytes: ONE_PIXEL_PNG.length,
      atlasSha256: sha256Bytes(ONE_PIXEL_PNG),
      atlasWidth: 1,
      atlasHeight: 1,
    }],
    looseImages: [],
    boneyards: [{
      path: "data/levels/test.boneyard",
      bytes: boneyardBytes,
      sha256: await sha256File(BONEYARD_FIXTURE),
    }],
    wave: {
      path: "data/wave.txt",
      bytes: wave.length,
      sha256: sha256Bytes(wave),
    },
    waveFlags: new Map([["WEAK", 4]]),
  };
}

describe("deterministic asset pipeline", () => {
  it("runs the real Python decoders twice and emits byte-identical trees", { timeout: 30_000 }, async () => {
    expect(["Unholy", "loose:WallTop.png", "Loader", "loading:Wizards_dire_BG"]
      .sort(compareNativeNames))
      .toEqual(["Loader", "loading:Wizards_dire_BG", "loose:WallTop.png", "Unholy"]);
    const root = await mkdtemp(path.join(os.tmpdir(), "sd-web-assets-"));
    temporaryRoots.push(root);
    const retailRoot = path.join(root, "retail");
    await mkdir(retailRoot);
    const groundTruth = await prepareRetail(retailRoot);
    const common = {
      repoRoot: REPO_ROOT,
      retailRoot,
      pythonExecutable: "python3",
      groundTruth,
      includeLoadingArt: false,
    };
    const first = await buildAssets({ ...common, outputRoot: path.join(root, "first") });
    const second = await buildAssets({ ...common, outputRoot: path.join(root, "second") });
    expect(second.outputTreeSha256).toBe(first.outputTreeSha256);
    expect(second.files).toEqual(first.files);
    expect(first.manifest.entries["Test.0"]?.provenance.sourceBytesSha256)
      .toBe(sha256Bytes(oneRecordBundle()));
    expect(first.manifest.packs.boneyards.entryCount).toBe(1);
    expect(await sha256File(path.join(root, "first", "atlases", "Test.png")))
      .toBe(sha256Bytes(ONE_PIXEL_PNG));

    const boneyardPack = expectObject(
      JSON.parse(
        await readFile(path.join(root, "first", "packs", "boneyards.json"), "utf8"),
      ) as unknown,
      "synthetic boneyard pack",
    );
    const boneyards = expectArray(boneyardPack.boneyards, "synthetic boneyards");
    expect(boneyards).toHaveLength(1);
    const boneyard = expectObject(boneyards[0], "synthetic boneyard");
    const boneyardProvenance = expectObject(
      boneyard.provenance,
      "synthetic boneyard provenance",
    );
    expect(boneyardProvenance).toEqual({
      recordIndex: 0,
      sourceBundleFilename: "data/levels/test.boneyard",
      sourceBytesSha256: await sha256File(BONEYARD_FIXTURE),
    });
    expect(Buffer.from(expectString(boneyard.sourceFileBase64, "sourceFileBase64"), "base64"))
      .toEqual(await readFile(BONEYARD_FIXTURE));
    expectObject(boneyard.triggerControl, "synthetic trigger control");
    expectArray(boneyard.timelines, "synthetic timelines");

    const recipePack = expectObject(
      JSON.parse(
        await readFile(path.join(root, "first", "packs", "recipes.json"), "utf8"),
      ) as unknown,
      "synthetic recipe pack",
    );
    const recipeSources = expectArray(recipePack.sources, "synthetic recipe sources");
    expect(recipeSources).toHaveLength(1);
    expect(expectObject(recipeSources[0], "synthetic recipe source").provenance)
      .toEqual(boneyardProvenance);

    const wavePack = expectObject(
      JSON.parse(
        await readFile(path.join(root, "first", "packs", "waves.json"), "utf8"),
      ) as unknown,
      "synthetic wave pack",
    );
    const waveProvenance = {
      recordIndex: 0,
      sourceBundleFilename: "data/wave.txt",
      sourceBytesSha256: groundTruth.wave.sha256,
    };
    expect(wavePack.provenance).toEqual(waveProvenance);
    const waves = expectArray(wavePack.waves, "synthetic waves");
    expect(waves).toHaveLength(1);
    const waveRecordProvenance = expectObject(
      expectObject(waves[0], "synthetic wave").provenance,
      "synthetic wave provenance",
    );
    expect(waveRecordProvenance.recordIndex).toBe(0);
    expect(waveRecordProvenance.sourceBundleFilename).toBe("data/wave.txt");
    expect(expectSha256(
      waveRecordProvenance.sourceBytesSha256,
      "synthetic wave source bytes SHA-256",
    )).toHaveLength(64);

    const schema = expectObject(
      JSON.parse(
        await readFile(
          path.join(REPO_ROOT, "webgame", "assets", "asset-manifest.schema.json"),
          "utf8",
        ),
      ) as unknown,
      "asset manifest schema",
    );
    const validate = new AjvModule.default({ allErrors: true, strict: true }).compile(schema);
    expect(validate(first.manifest), JSON.stringify(validate.errors)).toBe(true);
  });

  it("distinguishes an interpreter that cannot run from a runnable decoder rejection", async () => {
    const root = await mkdtemp(path.join(os.tmpdir(), "sd-web-assets-probe-"));
    temporaryRoots.push(root);
    const { decodeBundles } = await import("../python-bridge.js");
    await expect(decodeBundles(REPO_ROOT, root, "python-that-does-not-exist", []))
      .rejects.toThrow("asset decoder could not run python-that-does-not-exist");
    await expect(decodeBundles(REPO_ROOT, root, "python3", []))
      .rejects.toThrow(
        "asset decoder failed (exit 1): asset decode failed: "
          + "bridge request must contain a non-empty sources array",
      );
  });
});
