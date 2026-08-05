import { describe, expect, it } from "vitest";

import { parseWaveFile } from "../wave.js";

const FLAGS = new Map([
  ["WEAK", 4],
  ["HPDOWN", 2],
]);

function schedule(enemyLine: string): Buffer {
  return Buffer.from(
    [
      "WAVE",
      "NEXT:1,-3",
      "SPAWN:2",
      "SPAWNDELAY:1-2",
      "WAVEDELAY:3-4",
      "MAXENEMIES:5",
      "GROUP",
      enemyLine,
      "ENDWAVE",
      "ENDWAVE",
      "",
    ].join("\r\n"),
    "utf8",
  );
}

describe("parseWaveFile", () => {
  it("preserves signed NEXT values, repeated modifiers, and native-ignored retail tokens", () => {
    const parsed = parseWaveFile(
      schedule("SKELETON:FLAG_WEAK|FLAG_WEAK|FLAG_IGNITE"),
      "data/wave.txt",
      FLAGS,
    );
    expect(parsed.waves).toHaveLength(1);
    expect(parsed.waves[0]?.next).toEqual([1, -3]);
    expect(parsed.waves[0]?.groups[0]?.enemies[0]?.flags).toEqual([
      {
        sourceToken: "FLAG_WEAK",
        catalogToken: "WEAK",
        nativeCode: 4,
        nativeBehavior: "applied",
      },
      {
        sourceToken: "FLAG_WEAK",
        catalogToken: "WEAK",
        nativeCode: 4,
        nativeBehavior: "applied",
      },
      {
        sourceToken: "FLAG_IGNITE",
        catalogToken: null,
        nativeCode: null,
        nativeBehavior: "logged-and-ignored",
      },
    ]);
    expect(parsed.ignoredNativeFlagTokens).toEqual(["FLAG_IGNITE"]);
    expect(parsed.toleratedOutsideWaveDirectives).toHaveLength(1);
  });

  it("hard-fails an unreviewed modifier with its line and token", () => {
    expect(() => parseWaveFile(
      schedule("SKELETON:FLAG_NOT_REVERSED"),
      "data/wave.txt",
      FLAGS,
    )).toThrow("wave line 8 has unknown flag FLAG_NOT_REVERSED");
  });

  it("hard-fails a group that has no enemy records", () => {
    const bytes = schedule("# no enemy");
    expect(() => parseWaveFile(bytes, "data/wave.txt", FLAGS)).toThrow(
      "wave 1 group 0 has no enemies",
    );
  });
});
