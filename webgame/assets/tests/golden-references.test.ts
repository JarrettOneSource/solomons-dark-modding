import path from "node:path";

import { describe, expect, it } from "vitest";

import { collectGoldenReferences } from "../golden-references.js";

const REPO_ROOT = path.resolve(import.meta.dirname, "..", "..", "..");

describe("golden asset reference discovery", () => {
  it("reaches the landed scene and menu recordings", async () => {
    const references = await collectGoldenReferences(REPO_ROOT);
    expect(references.sceneSpriteIds.size).toBe(378);
    expect(references.menuArtIds.size).toBe(107);
    expect(references.menuFontIds.size).toBe(4);
    expect(references.sceneSpriteIds).toContain("native.textured-quad@0x41474C");
    expect(references.menuArtIds).toContain("Wizards_dire_BG");
    expect(references.menuArtIds).toContain("Create.4");
    expect(references.menuArtIds).toContain("LevelPicker.1");
    expect(references.menuFontIds).toContain("Fonts.308-349");
    expect(references.menuFontIds).toContain("Fonts.93-184");
  });
});
