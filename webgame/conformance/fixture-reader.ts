import { readFile } from "node:fs/promises";
import path from "node:path";

const repositoryRoot = path.resolve(import.meta.dirname, "../..");

export async function readRepositoryJson(relativePath: string): Promise<unknown> {
  const text = await readFile(path.join(repositoryRoot, relativePath), "utf8");
  return JSON.parse(text) as unknown;
}

export function fixtureRecord(value: unknown, label: string): Record<string, unknown> {
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${label} must be an object`);
  }
  return value as Record<string, unknown>;
}

export function fixtureArray(value: unknown, label: string): readonly unknown[] {
  if (!Array.isArray(value)) {
    throw new Error(`${label} must be an array`);
  }
  return value;
}

export function fixtureNumber(value: unknown, label: string): number {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new Error(`${label} must be a finite number`);
  }
  return value;
}

export function fixtureInteger(value: unknown, label: string): number {
  const number = fixtureNumber(value, label);
  if (!Number.isSafeInteger(number)) {
    throw new Error(`${label} must be a safe integer`);
  }
  return number;
}

export function fixtureString(value: unknown, label: string): string {
  if (typeof value !== "string") {
    throw new Error(`${label} must be a string`);
  }
  return value;
}

export function fixtureBoolean(value: unknown, label: string): boolean {
  if (typeof value !== "boolean") {
    throw new Error(`${label} must be a boolean`);
  }
  return value;
}
