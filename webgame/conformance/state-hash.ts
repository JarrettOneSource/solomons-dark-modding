import { createHash } from "node:crypto";

export function sha256SerializedState(serializedState: string): string {
  return createHash("sha256").update(serializedState, "utf8").digest("hex");
}
