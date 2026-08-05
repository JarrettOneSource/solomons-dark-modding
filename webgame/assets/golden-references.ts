import { readFile } from "node:fs/promises";
import path from "node:path";

import { sha256Bytes } from "./hash.js";
import { expectArray, expectObject, expectString } from "./validation.js";

export const SCENE_GOLDEN_PATH = "tests/fixtures/webgame/scene-composition-goldens.json";
export const MENU_GOLDEN_PATH = "tests/fixtures/webgame/menu-goldens.json";

export interface GoldenReferences {
  readonly sceneSpriteIds: ReadonlySet<string>;
  readonly menuArtIds: ReadonlySet<string>;
  readonly menuFontIds: ReadonlySet<string>;
  readonly sourceHashes: Readonly<Record<string, string>>;
}

function collectStringFields(
  value: unknown,
  fieldNames: ReadonlySet<string>,
  output: Set<string>,
): void {
  if (Array.isArray(value)) {
    for (const item of value) {
      collectStringFields(item, fieldNames, output);
    }
    return;
  }
  if (typeof value !== "object" || value === null) {
    return;
  }
  for (const [key, item] of Object.entries(value)) {
    if (fieldNames.has(key) && typeof item === "string" && item.length > 0) {
      output.add(item);
    }
    collectStringFields(item, fieldNames, output);
  }
}

function collectSceneSpriteObjects(value: unknown, output: Set<string>): void {
  if (Array.isArray(value)) {
    for (const item of value) {
      collectSceneSpriteObjects(item, output);
    }
    return;
  }
  if (typeof value !== "object" || value === null) {
    return;
  }
  const object = value as Record<string, unknown>;
  if (object.sprite !== undefined) {
    const sprite = expectObject(object.sprite, "scene golden sprite reference");
    output.add(expectString(sprite.id, "scene golden sprite.id"));
  }
  for (const item of Object.values(object)) {
    collectSceneSpriteObjects(item, output);
  }
}

async function loadJsonWithHash(
  repoRoot: string,
  relativePath: string,
): Promise<{ readonly value: unknown; readonly sha256: string }> {
  const bytes = await readFile(path.join(repoRoot, ...relativePath.split("/")));
  return {
    value: JSON.parse(bytes.toString("utf8")) as unknown,
    sha256: sha256Bytes(bytes),
  };
}

export async function collectGoldenReferences(repoRoot: string): Promise<GoldenReferences> {
  const [sceneSource, menuSource] = await Promise.all([
    loadJsonWithHash(repoRoot, SCENE_GOLDEN_PATH),
    loadJsonWithHash(repoRoot, MENU_GOLDEN_PATH),
  ]);
  const scene = expectObject(sceneSource.value, "scene-composition golden");
  if (scene.schema !== "solomon-dark-scene-composition-goldens-v1") {
    throw new Error("scene-composition golden schema drifted");
  }
  const captures = expectArray(scene.captures, "scene-composition golden captures");
  if (captures.length === 0) {
    throw new Error("scene-composition golden contains no captures to resolve");
  }
  const sceneSpriteIds = new Set<string>();
  collectSceneSpriteObjects(captures, sceneSpriteIds);
  collectStringFields(scene.cross_capture_observations, new Set(["sprite_id"]), sceneSpriteIds);
  if (!sceneSpriteIds.has("native.framebuffer-clear") || !sceneSpriteIds.has("DeadHawg.12")) {
    throw new Error("scene-composition reference sweep missed required native witnesses");
  }

  const menu = expectObject(menuSource.value, "menu golden");
  if (menu.schema !== "solomon-dark-menu-goldens-v1") {
    throw new Error("menu golden schema drifted");
  }
  const layouts = expectArray(menu.layouts, "menu golden layouts");
  if (layouts.length === 0) {
    throw new Error("menu golden contains no layouts to resolve");
  }
  const menuArtIds = new Set<string>();
  const menuFontIds = new Set<string>();
  collectStringFields(layouts, new Set(["art_id"]), menuArtIds);
  collectStringFields(layouts, new Set(["font_id"]), menuFontIds);
  if (!menuArtIds.has("Wizards_dire_BG") || !menuArtIds.has("Title.0")) {
    throw new Error("menu art reference sweep missed required native witnesses");
  }
  if (!menuFontIds.has("Fonts.93-184") || !menuFontIds.has("Segoe UI")) {
    throw new Error("menu font reference sweep missed required font witnesses");
  }
  return {
    sceneSpriteIds,
    menuArtIds,
    menuFontIds,
    sourceHashes: {
      [SCENE_GOLDEN_PATH]: sceneSource.sha256,
      [MENU_GOLDEN_PATH]: menuSource.sha256,
    },
  };
}
