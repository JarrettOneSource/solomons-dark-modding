import type { SimulationState } from "./types.js";

function canonicalize(value: unknown, path: string): unknown {
  if (value === null || typeof value === "string" || typeof value === "boolean") {
    return value;
  }
  if (typeof value === "number") {
    if (!Number.isFinite(value)) {
      throw new Error(`${path} contains a non-finite simulation number`);
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
        throw new Error(`${path}.${key} is undefined in simulation state`);
      }
      output[key] = canonicalize(item, `${path}.${key}`);
    }
    return output;
  }
  throw new Error(`${path} contains unsupported simulation state type ${typeof value}`);
}

export function serializeSimulationState(state: SimulationState): string {
  return `${JSON.stringify(canonicalize(state, "$"))}\n`;
}
