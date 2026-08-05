import { writeFile } from "node:fs/promises";

function canonicalize(value: unknown, path: string): unknown {
  if (
    value === null
    || typeof value === "string"
    || typeof value === "boolean"
  ) {
    return value;
  }
  if (typeof value === "number") {
    if (!Number.isFinite(value)) {
      throw new Error(`${path} contains a non-finite number`);
    }
    return Object.is(value, -0) ? 0 : value;
  }
  if (Array.isArray(value)) {
    return value.map((item, index) => canonicalize(item, `${path}[${index}]`));
  }
  if (typeof value === "object") {
    const output: Record<string, unknown> = {};
    for (const key of Object.keys(value).sort()) {
      const item = (value as Record<string, unknown>)[key];
      if (item === undefined) {
        throw new Error(`${path}.${key} is undefined`);
      }
      output[key] = canonicalize(item, `${path}.${key}`);
    }
    return output;
  }
  throw new Error(`${path} contains unsupported ${typeof value}`);
}

export function canonicalJson(value: unknown): string {
  return `${JSON.stringify(canonicalize(value, "$"), null, 2)}\n`;
}

export async function writeCanonicalJson(
  path: string,
  value: unknown,
): Promise<void> {
  await writeFile(path, canonicalJson(value), { encoding: "utf8", flag: "wx" });
}
