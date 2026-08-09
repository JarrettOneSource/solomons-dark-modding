import { spawn } from "node:child_process";
import path from "node:path";

import { serializeSimulationState } from "../sim/serialize.js";
import type { SimulationState } from "../sim/types.js";
import { runScriptedSimulation } from "./scripted-run.js";
import { sha256SerializedState } from "./state-hash.js";

interface WorkerResult {
  readonly pid: number;
  readonly ticks: number;
  readonly byte_length: number;
  readonly serialized_base64: string;
  readonly sha256: string;
}

function parseWorkerResult(stdout: string, label: string): WorkerResult {
  const value = JSON.parse(stdout) as unknown;
  if (value === null || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${label} did not return a JSON object`);
  }
  const result = value as Record<string, unknown>;
  if (
    !Number.isSafeInteger(result.pid)
    || !Number.isSafeInteger(result.ticks)
    || !Number.isSafeInteger(result.byte_length)
    || typeof result.serialized_base64 !== "string"
    || typeof result.sha256 !== "string"
    || !/^[0-9a-f]{64}$/.test(result.sha256)
  ) {
    throw new Error(`${label} returned an incomplete determinism receipt`);
  }
  return result as unknown as WorkerResult;
}

function launchWorker(ticks: number, label: string): Promise<WorkerResult> {
  const tsxCli = path.resolve(import.meta.dirname, "../node_modules/tsx/dist/cli.mjs");
  const worker = path.resolve(import.meta.dirname, "determinism-worker.ts");
  return new Promise((resolve, reject) => {
    const child = spawn(process.execPath, [tsxCli, worker, String(ticks)], {
      cwd: path.resolve(import.meta.dirname, ".."),
      stdio: ["ignore", "pipe", "pipe"],
      windowsHide: true,
    });
    let stdout = "";
    let stderr = "";
    child.stdout.setEncoding("utf8");
    child.stderr.setEncoding("utf8");
    child.stdout.on("data", (chunk: string) => {
      stdout += chunk;
    });
    child.stderr.on("data", (chunk: string) => {
      stderr += chunk;
    });
    child.once("error", (error) => {
      reject(new Error(`${label} could not run: ${error.message}`));
    });
    child.once("exit", (code, signal) => {
      if (code !== 0) {
        reject(new Error(`${label} exited ${String(code)} signal ${String(signal)}: ${stderr}`));
        return;
      }
      try {
        resolve(parseWorkerResult(stdout.trim(), label));
      } catch (error) {
        reject(error instanceof Error ? error : new Error(String(error)));
      }
    });
  });
}

function flipOneStateBit(state: SimulationState): SimulationState {
  const firstWord = state.rng.state_words[0];
  if (firstWord === undefined) {
    throw new Error("single-bit divergence control found no RNG word");
  }
  return {
    ...state,
    rng: {
      ...state.rng,
      state_words: [firstWord ^ 1, ...state.rng.state_words.slice(1)],
    },
  };
}

export interface DeterminismReceipt {
  readonly ticks: number;
  readonly process_ids: readonly [number, number];
  readonly byte_length: number;
  readonly sha256: string;
  readonly byte_identical: true;
  readonly single_bit_control_sha256: string;
  readonly single_bit_diverged: true;
}

export async function proveCrossProcessDeterminism(ticks: number): Promise<DeterminismReceipt> {
  if (!Number.isSafeInteger(ticks) || ticks < 1_000) {
    throw new Error("determinism proof requires at least 1000 fixed ticks");
  }
  const firstPromise = launchWorker(ticks, "determinism worker A");
  const secondPromise = launchWorker(ticks, "determinism worker B");
  const [first, second] = await Promise.all([firstPromise, secondPromise]);
  const firstBytes = Buffer.from(first.serialized_base64, "base64");
  const secondBytes = Buffer.from(second.serialized_base64, "base64");
  if (!firstBytes.equals(secondBytes) || first.sha256 !== second.sha256) {
    throw new Error(
      `cross-process determinism diverged: process ${first.pid} ${first.sha256}, process ${second.pid} ${second.sha256}`,
    );
  }
  const localState = runScriptedSimulation(ticks);
  const localSerialized = serializeSimulationState(localState);
  if (sha256SerializedState(localSerialized) !== first.sha256) {
    throw new Error("cross-process determinism workers disagree with the local canonical serializer");
  }
  const corruptedHash = sha256SerializedState(serializeSimulationState(flipOneStateBit(localState)));
  if (corruptedHash === first.sha256) {
    throw new Error("single-bit state divergence control did not change the serialized state hash");
  }
  return {
    ticks,
    process_ids: [first.pid, second.pid],
    byte_length: first.byte_length,
    sha256: first.sha256,
    byte_identical: true,
    single_bit_control_sha256: corruptedHash,
    single_bit_diverged: true,
  };
}
