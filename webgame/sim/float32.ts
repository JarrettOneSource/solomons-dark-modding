export function f32(value: number): number {
  return Math.fround(value);
}

export function f32Add(left: number, right: number): number {
  return f32(left + right);
}

export function f32Multiply(left: number, right: number): number {
  return f32(left * right);
}

export function float32Bits(value: number): string {
  const bytes = new ArrayBuffer(4);
  const view = new DataView(bytes);
  view.setFloat32(0, value, false);
  return `0x${view.getUint32(0, false).toString(16).padStart(8, "0").toUpperCase()}`;
}
