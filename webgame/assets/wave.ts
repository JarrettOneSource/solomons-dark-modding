import { sha256Bytes } from "./hash.js";

const MAXIMUM_WAVE_VALUE = 4096;
const ENEMY_TYPES = Object.freeze<Record<string, number>>({
  COFFIN: 1013,
  DEMON: 1009,
  IMP: 1004,
  SKELETON: 1001,
  SKELETONARCHER: 1002,
  SKELETONMAGE: 1003,
  WRAITH: 1007,
  ZOMBIE: 1006,
});

const RETAIL_IGNORED_FLAGS = new Set(["FLAG_IGNITE", "FLAG_IMMORTALIZE"]);

interface SourceLine {
  readonly lineNumber: number;
  readonly start: number;
  readonly end: number;
  readonly text: string;
  readonly raw: Buffer;
}

export interface ParsedWaveEnemy {
  readonly token: string;
  readonly nativeTypeId: number;
  readonly flags: readonly {
    readonly sourceToken: string;
    readonly catalogToken: string | null;
    readonly nativeCode: number | null;
    readonly nativeBehavior: "applied" | "logged-and-ignored";
  }[];
}

export interface ParsedWaveGroup {
  readonly kind: "GROUP" | "FORMATION";
  readonly enemies: readonly ParsedWaveEnemy[];
}

export interface ParsedWave {
  readonly wave: number;
  readonly next: readonly number[];
  readonly spawn: number;
  readonly spawnDelay: readonly [number, number];
  readonly waveDelay: readonly [number, number];
  readonly maxEnemies: number;
  readonly zombieWave: boolean;
  readonly groups: readonly ParsedWaveGroup[];
  readonly provenance: {
    readonly sourceBundleFilename: string;
    readonly recordIndex: number;
    readonly sourceBytesSha256: string;
  };
}

interface WaveBuilder {
  readonly start: number;
  readonly groups: { kind: "GROUP" | "FORMATION"; enemies: ParsedWaveEnemy[] }[];
  next?: number[];
  spawn?: number;
  spawnDelay?: [number, number];
  waveDelay?: [number, number];
  maxEnemies?: number;
  zombieWave: boolean;
  currentGroup?: { kind: "GROUP" | "FORMATION"; enemies: ParsedWaveEnemy[] };
}

function splitSourceLines(bytes: Buffer): SourceLine[] {
  const decoder = new TextDecoder("utf-8", { fatal: true });
  const lines: SourceLine[] = [];
  let start = 0;
  let lineNumber = 1;
  for (let index = 0; index <= bytes.length; index += 1) {
    if (index !== bytes.length && bytes[index] !== 0x0a) {
      continue;
    }
    const end = index === bytes.length ? index : index + 1;
    const raw = bytes.subarray(start, end);
    let contentEnd = raw.length;
    if (contentEnd > 0 && raw[contentEnd - 1] === 0x0a) {
      contentEnd -= 1;
    }
    if (contentEnd > 0 && raw[contentEnd - 1] === 0x0d) {
      contentEnd -= 1;
    }
    let text = decoder.decode(raw.subarray(0, contentEnd));
    if (lineNumber === 1 && text.startsWith("\uFEFF")) {
      text = text.slice(1);
    }
    lines.push({ lineNumber, start, end, text, raw: Buffer.from(raw) });
    start = end;
    lineNumber += 1;
  }
  return lines;
}

function startsDirective(line: string, directive: string): boolean {
  return line === directive
    || (line.startsWith(directive) && line[directive.length] === ":");
}

function directivePayload(line: string, directive: string, lineNumber: number): string {
  if (!startsDirective(line, directive) || line[directive.length] !== ":") {
    throw new Error(`wave line ${lineNumber} has malformed ${directive} directive`);
  }
  const payload = line.slice(directive.length + 1).trim();
  if (payload.length === 0) {
    throw new Error(`wave line ${lineNumber} has empty ${directive} payload`);
  }
  return payload;
}

function parseNonNegative(value: string, label: string): number {
  if (!/^[0-9]+$/u.test(value)) {
    throw new Error(`${label} must be a base-10 non-negative integer`);
  }
  const parsed = Number(value);
  if (!Number.isSafeInteger(parsed) || parsed > MAXIMUM_WAVE_VALUE) {
    throw new Error(`${label} exceeds the native ${MAXIMUM_WAVE_VALUE} bound`);
  }
  return parsed;
}

function parseSigned(value: string, label: string): number {
  if (!/^-?[0-9]+$/u.test(value)) {
    throw new Error(`${label} must be a base-10 integer`);
  }
  const parsed = Number(value);
  if (!Number.isSafeInteger(parsed) || Math.abs(parsed) > MAXIMUM_WAVE_VALUE) {
    throw new Error(`${label} exceeds the native +/-${MAXIMUM_WAVE_VALUE} bound`);
  }
  return parsed;
}

function parseRange(value: string, label: string): [number, number] {
  const match = /^([0-9]+)\s*-\s*([0-9]+)$/u.exec(value);
  if (match === null) {
    throw new Error(`${label} must be MIN-MAX`);
  }
  const minimumToken = match[1];
  const maximumToken = match[2];
  if (minimumToken === undefined || maximumToken === undefined) {
    throw new Error(`${label} range capture is incomplete`);
  }
  const minimum = parseNonNegative(minimumToken, `${label} minimum`);
  const maximum = parseNonNegative(maximumToken, `${label} maximum`);
  if (maximum < minimum) {
    throw new Error(`${label} maximum is below its minimum`);
  }
  return [minimum, maximum];
}

function assignOnce<K extends keyof WaveBuilder>(
  wave: WaveBuilder,
  key: K,
  value: WaveBuilder[K],
  lineNumber: number,
): void {
  if (wave[key] !== undefined) {
    throw new Error(`wave line ${lineNumber} duplicates ${key}`);
  }
  wave[key] = value;
}

function finishWave(
  builder: WaveBuilder,
  recordIndex: number,
  sourceFilename: string,
  sourceBytes: Buffer,
  end: number,
): ParsedWave {
  if (builder.next === undefined) {
    throw new Error(`wave ${recordIndex + 1} has no NEXT directive`);
  }
  if (builder.spawn === undefined || builder.spawn <= 0) {
    throw new Error(`wave ${recordIndex + 1} has no positive SPAWN budget`);
  }
  if (builder.spawnDelay === undefined) {
    throw new Error(`wave ${recordIndex + 1} has no SPAWNDELAY directive`);
  }
  if (builder.waveDelay === undefined) {
    throw new Error(`wave ${recordIndex + 1} has no WAVEDELAY directive`);
  }
  if (builder.maxEnemies === undefined) {
    throw new Error(`wave ${recordIndex + 1} has no MAXENEMIES directive`);
  }
  if (builder.groups.length === 0) {
    throw new Error(`wave ${recordIndex + 1} has no GROUP or FORMATION`);
  }
  for (const [groupIndex, group] of builder.groups.entries()) {
    if (group.enemies.length === 0) {
      throw new Error(`wave ${recordIndex + 1} group ${groupIndex} has no enemies`);
    }
  }
  return {
    wave: recordIndex + 1,
    next: builder.next,
    spawn: builder.spawn,
    spawnDelay: builder.spawnDelay,
    waveDelay: builder.waveDelay,
    maxEnemies: builder.maxEnemies,
    zombieWave: builder.zombieWave,
    groups: builder.groups,
    provenance: {
      sourceBundleFilename: sourceFilename,
      recordIndex,
      sourceBytesSha256: sha256Bytes(sourceBytes.subarray(builder.start, end)),
    },
  };
}

export function parseWaveFile(
  sourceBytes: Buffer,
  sourceFilename: string,
  knownFlags: ReadonlyMap<string, number>,
): {
  readonly sourceTextBase64: string;
  readonly waves: readonly ParsedWave[];
  readonly toleratedOutsideWaveDirectives: readonly {
    readonly line: number;
    readonly directive: "ENDWAVE";
    readonly sourceBytesSha256: string;
  }[];
  readonly ignoredNativeFlagTokens: readonly string[];
} {
  const waves: ParsedWave[] = [];
  const toleratedOutsideWaveDirectives: {
    line: number;
    directive: "ENDWAVE";
    sourceBytesSha256: string;
  }[] = [];
  const ignoredNativeFlagTokens = new Set<string>();
  let current: WaveBuilder | undefined;
  const lines = splitSourceLines(sourceBytes);
  for (const sourceLine of lines) {
    const line = sourceLine.text.trim().toUpperCase();
    if (line.length === 0 || line.startsWith("#") || line.startsWith(";")) {
      continue;
    }
    if (line === "WAVE") {
      if (current !== undefined) {
        throw new Error(`wave line ${sourceLine.lineNumber} starts WAVE before ENDWAVE`);
      }
      current = { start: sourceLine.start, groups: [], zombieWave: false };
      continue;
    }
    if (line === "ENDWAVE") {
      if (current === undefined) {
        toleratedOutsideWaveDirectives.push({
          line: sourceLine.lineNumber,
          directive: "ENDWAVE",
          sourceBytesSha256: sha256Bytes(sourceLine.raw),
        });
      } else {
        waves.push(
          finishWave(
            current,
            waves.length,
            sourceFilename,
            sourceBytes,
            sourceLine.end,
          ),
        );
        current = undefined;
      }
      continue;
    }
    if (current === undefined) {
      throw new Error(
        `wave line ${sourceLine.lineNumber} has content outside WAVE: ${line}`,
      );
    }
    if (line === "GROUP" || line === "FORMATION") {
      const group = { kind: line, enemies: [] } satisfies {
        kind: "GROUP" | "FORMATION";
        enemies: ParsedWaveEnemy[];
      };
      current.groups.push(group);
      current.currentGroup = group;
      continue;
    }
    if (line === "ZOMBIEWAVE") {
      if (current.zombieWave) {
        throw new Error(`wave line ${sourceLine.lineNumber} duplicates ZOMBIEWAVE`);
      }
      current.zombieWave = true;
      delete current.currentGroup;
      continue;
    }
    if (startsDirective(line, "NEXT")) {
      const values = directivePayload(line, "NEXT", sourceLine.lineNumber)
        .split(",")
        .map((value, index) => parseSigned(
          value.trim(),
          `wave line ${sourceLine.lineNumber} NEXT[${index}]`,
        ));
      assignOnce(current, "next", values, sourceLine.lineNumber);
      delete current.currentGroup;
      continue;
    }
    if (startsDirective(line, "SPAWN")) {
      assignOnce(
        current,
        "spawn",
        parseNonNegative(
          directivePayload(line, "SPAWN", sourceLine.lineNumber),
          `wave line ${sourceLine.lineNumber} SPAWN`,
        ),
        sourceLine.lineNumber,
      );
      delete current.currentGroup;
      continue;
    }
    if (startsDirective(line, "SPAWNDELAY")) {
      assignOnce(
        current,
        "spawnDelay",
        parseRange(
          directivePayload(line, "SPAWNDELAY", sourceLine.lineNumber),
          `wave line ${sourceLine.lineNumber} SPAWNDELAY`,
        ),
        sourceLine.lineNumber,
      );
      delete current.currentGroup;
      continue;
    }
    if (startsDirective(line, "WAVEDELAY")) {
      assignOnce(
        current,
        "waveDelay",
        parseRange(
          directivePayload(line, "WAVEDELAY", sourceLine.lineNumber),
          `wave line ${sourceLine.lineNumber} WAVEDELAY`,
        ),
        sourceLine.lineNumber,
      );
      delete current.currentGroup;
      continue;
    }
    if (startsDirective(line, "MAXENEMIES")) {
      assignOnce(
        current,
        "maxEnemies",
        parseNonNegative(
          directivePayload(line, "MAXENEMIES", sourceLine.lineNumber),
          `wave line ${sourceLine.lineNumber} MAXENEMIES`,
        ),
        sourceLine.lineNumber,
      );
      delete current.currentGroup;
      continue;
    }
    if (current.currentGroup === undefined) {
      throw new Error(`wave line ${sourceLine.lineNumber} has unknown directive: ${line}`);
    }
    const separator = line.indexOf(":");
    const token = (separator === -1 ? line : line.slice(0, separator)).trim();
    const nativeTypeId = ENEMY_TYPES[token];
    if (nativeTypeId === undefined) {
      throw new Error(`wave line ${sourceLine.lineNumber} has unknown enemy token ${token}`);
    }
    const sourceFlags = separator === -1
      ? []
      : line.slice(separator + 1).split("|").map((flag) => flag.trim()).filter(Boolean);
    const flags = sourceFlags.map((sourceToken) => {
      const catalogToken = sourceToken.startsWith("FLAG_")
        ? sourceToken.slice("FLAG_".length)
        : "";
      const nativeCode = knownFlags.get(catalogToken);
      if (nativeCode !== undefined) {
        return { sourceToken, catalogToken, nativeCode, nativeBehavior: "applied" as const };
      }
      if (!RETAIL_IGNORED_FLAGS.has(sourceToken)) {
        throw new Error(`wave line ${sourceLine.lineNumber} has unknown flag ${sourceToken}`);
      }
      ignoredNativeFlagTokens.add(sourceToken);
      return {
        sourceToken,
        catalogToken: null,
        nativeCode: null,
        nativeBehavior: "logged-and-ignored" as const,
      };
    });
    current.currentGroup.enemies.push({ token, nativeTypeId, flags });
  }
  if (current !== undefined) {
    throw new Error(`wave ${waves.length + 1} reaches EOF without ENDWAVE`);
  }
  if (waves.length === 0) {
    throw new Error("wave schedule contains no WAVE records");
  }
  return {
    sourceTextBase64: sourceBytes.toString("base64"),
    waves,
    toleratedOutsideWaveDirectives,
    ignoredNativeFlagTokens: [...ignoredNativeFlagTokens].sort(),
  };
}
