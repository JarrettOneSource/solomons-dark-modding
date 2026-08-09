import { serializeSimulationState } from "../sim/serialize.js";
import { runScriptedSimulation } from "./scripted-run.js";
import { sha256SerializedState } from "./state-hash.js";

const tickArgument = process.argv[2];
const ticks = tickArgument === undefined ? Number.NaN : Number(tickArgument);
if (!Number.isSafeInteger(ticks) || ticks < 1) {
  throw new Error("determinism worker requires a positive integer tick count");
}

const serialized = serializeSimulationState(runScriptedSimulation(ticks));
process.stdout.write(`${JSON.stringify({
  pid: process.pid,
  ticks,
  byte_length: Buffer.byteLength(serialized, "utf8"),
  serialized_base64: Buffer.from(serialized, "utf8").toString("base64"),
  sha256: sha256SerializedState(serialized),
})}\n`);
