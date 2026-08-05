export type JsonObject = Record<string, unknown>;

export function expectObject(value: unknown, label: string): JsonObject {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    throw new Error(`${label} must be an object`);
  }
  return value as JsonObject;
}

export function expectArray(value: unknown, label: string): readonly unknown[] {
  if (!Array.isArray(value)) {
    throw new Error(`${label} must be an array`);
  }
  return value;
}

export function expectString(value: unknown, label: string): string {
  if (typeof value !== "string" || value.length === 0) {
    throw new Error(`${label} must be a non-empty string`);
  }
  return value;
}

export function expectBoolean(value: unknown, label: string): boolean {
  if (typeof value !== "boolean") {
    throw new Error(`${label} must be a Boolean`);
  }
  return value;
}

export function expectNumber(value: unknown, label: string): number {
  if (typeof value !== "number" || !Number.isFinite(value)) {
    throw new Error(`${label} must be a finite number`);
  }
  return value;
}

export function expectInteger(value: unknown, label: string): number {
  const number = expectNumber(value, label);
  if (!Number.isSafeInteger(number)) {
    throw new Error(`${label} must be a safe integer`);
  }
  return number;
}

export function expectNonNegativeInteger(value: unknown, label: string): number {
  const number = expectInteger(value, label);
  if (number < 0) {
    throw new Error(`${label} must be non-negative`);
  }
  return number;
}

export function expectSha256(value: unknown, label: string): string {
  const hash = expectString(value, label);
  if (!/^[0-9a-f]{64}$/u.test(hash)) {
    throw new Error(`${label} must be a lowercase SHA-256`);
  }
  return hash;
}

export function expectUnique<T>(
  values: readonly T[],
  key: (value: T) => string,
  label: string,
): void {
  const seen = new Set<string>();
  for (const value of values) {
    const candidate = key(value);
    if (seen.has(candidate)) {
      throw new Error(`${label} is ambiguous because ${candidate} is duplicated`);
    }
    seen.add(candidate);
  }
}
