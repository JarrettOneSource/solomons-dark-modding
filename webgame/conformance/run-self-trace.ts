import { writeFile } from "node:fs/promises";

import { createSoloSimulation } from "../sim/simulation.js";
import { SCRIPTED_RUN_TICKS } from "./scripted-run.js";
import {
  corruptTraceSingleBit,
  createSelfTrace,
  parseTraceTimeline,
  replayTrace,
} from "./trace-replay.js";

function option(name: string): string | undefined {
  const index = process.argv.indexOf(name);
  if (index === -1) {
    return undefined;
  }
  const value = process.argv[index + 1];
  if (value === undefined || value.startsWith("--")) {
    throw new Error(`${name} requires a value`);
  }
  return value;
}

const tickText = option("--ticks");
const ticks = tickText === undefined ? SCRIPTED_RUN_TICKS : Number(tickText);
if (!Number.isSafeInteger(ticks) || ticks < 1) {
  throw new Error("--ticks must be a positive integer");
}
const initial = createSoloSimulation({
  elapsed_app_ticks: 1485,
  position: { x: 0, y: 0 },
  heading_degrees: 0,
});
const trace = createSelfTrace(initial, ticks);
const reparsed = parseTraceTimeline(JSON.parse(JSON.stringify(trace)) as unknown);
const replay = replayTrace(reparsed);

let corruptionMessage = "";
try {
  replayTrace(corruptTraceSingleBit(reparsed));
} catch (error) {
  corruptionMessage = error instanceof Error ? error.message : String(error);
}
if (!corruptionMessage.includes("rng divergence")) {
  throw new Error(`corrupted self-trace did not fail loudly in RNG: ${corruptionMessage}`);
}

const output = option("--output");
if (output !== undefined) {
  await writeFile(output, `${JSON.stringify(trace)}\n`, "utf8");
}
process.stdout.write(`${JSON.stringify({
  tick_rate_hz: trace.tick_rate_hz,
  ticks_recorded: trace.timeline.length,
  seconds_recorded: trace.timeline.length / trace.tick_rate_hz,
  replay_exact: true,
  final_state_bytes: Buffer.byteLength(replay.final_serialized_state, "utf8"),
  corrupted_trace_failed: true,
  corrupted_trace_message: corruptionMessage,
  output: output ?? null,
}, null, 2)}\n`);
