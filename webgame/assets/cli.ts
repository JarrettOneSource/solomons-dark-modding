import path from "node:path";
import { fileURLToPath } from "node:url";

import { buildAssets } from "./builder.js";
import { canonicalJson } from "./canonical-json.js";
import { loadProductionGroundTruth } from "./ground-truth.js";

interface CliOptions {
  readonly repoRoot: string;
  readonly retailRoot: string;
  readonly outputRoot: string;
  readonly pythonExecutable: string;
}

function usage(): string {
  return [
    "Usage: npm run assets:build -- --retail-root <path> --output <path>",
    "",
    "Options:",
    "  --retail-root  Read-only SolomonDarkAbandonware install root (required)",
    "  --output       New artifact directory; the path must not exist (required)",
    "  --repo-root    Repository root (defaults from this script)",
    "  --python       Runnable Python 3 executable (default: python3)",
  ].join("\n");
}

function parseArguments(arguments_: readonly string[]): CliOptions {
  const values = new Map<string, string>();
  for (let index = 0; index < arguments_.length; index += 1) {
    const flag = arguments_[index];
    if (flag === "--help" || flag === "-h") {
      console.log(usage());
      process.exit(0);
    }
    if (flag === undefined || !flag.startsWith("--")) {
      throw new Error(`unexpected argument: ${flag ?? "<missing>"}`);
    }
    if (!["--retail-root", "--output", "--repo-root", "--python"].includes(flag)) {
      throw new Error(`unknown option: ${flag}`);
    }
    if (values.has(flag)) {
      throw new Error(`option may only be supplied once: ${flag}`);
    }
    const value = arguments_[index + 1];
    if (value === undefined || value.startsWith("--")) {
      throw new Error(`option requires a value: ${flag}`);
    }
    values.set(flag, value);
    index += 1;
  }
  const retailRoot = values.get("--retail-root");
  const outputRoot = values.get("--output");
  if (retailRoot === undefined || outputRoot === undefined) {
    throw new Error(`--retail-root and --output are required\n\n${usage()}`);
  }
  return {
    repoRoot: path.resolve(
      values.get("--repo-root") ?? path.resolve(import.meta.dirname, "..", ".."),
    ),
    retailRoot: path.resolve(retailRoot),
    outputRoot: path.resolve(outputRoot),
    pythonExecutable: values.get("--python") ?? "python3",
  };
}

export async function runCli(arguments_: readonly string[]): Promise<void> {
  const options = parseArguments(arguments_);
  const groundTruth = await loadProductionGroundTruth(options.repoRoot);
  const result = await buildAssets({
    ...options,
    groundTruth,
    includeLoadingArt: true,
  });
  process.stdout.write(canonicalJson({
    schema: result.manifest.schema,
    outputRoot: options.outputRoot,
    outputTreeSha256: result.outputTreeSha256,
    emittedBytes: result.categoryBytes,
    files: result.files.length,
    sprites: result.manifest.summary.spriteCount,
  }));
}

const entrypoint = process.argv[1];
if (entrypoint !== undefined && fileURLToPath(import.meta.url) === path.resolve(entrypoint)) {
  runCli(process.argv.slice(2)).catch((error: unknown) => {
    console.error(error instanceof Error ? error.message : String(error));
    process.exitCode = 1;
  });
}
