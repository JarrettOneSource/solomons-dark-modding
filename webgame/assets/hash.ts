import { createHash } from "node:crypto";
import { readFile, readdir, stat } from "node:fs/promises";
import path from "node:path";

import type { OutputFileHash } from "./types.js";

export function sha256Bytes(bytes: Uint8Array | string): string {
  return createHash("sha256").update(bytes).digest("hex");
}

export async function sha256File(file: string): Promise<string> {
  return sha256Bytes(await readFile(file));
}

async function collectFiles(root: string, directory: string): Promise<string[]> {
  const output: string[] = [];
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    const absolute = path.join(directory, entry.name);
    if (entry.isDirectory()) {
      output.push(...await collectFiles(root, absolute));
    } else if (entry.isFile()) {
      output.push(path.relative(root, absolute).split(path.sep).join("/"));
    } else {
      throw new Error(`output contains unsupported filesystem entry: ${absolute}`);
    }
  }
  return output;
}

export async function hashOutputTree(root: string): Promise<{
  readonly files: readonly OutputFileHash[];
  readonly sha256: string;
}> {
  const relativeFiles = (await collectFiles(root, root)).sort();
  if (relativeFiles.length === 0) {
    throw new Error(`output tree is empty: ${root}`);
  }
  const files: OutputFileHash[] = [];
  const treeHash = createHash("sha256");
  for (const file of relativeFiles) {
    const absolute = path.join(root, ...file.split("/"));
    const metadata = await stat(absolute);
    const hash = await sha256File(absolute);
    const entry = { file, bytes: metadata.size, sha256: hash };
    files.push(entry);
    treeHash.update(file, "utf8");
    treeHash.update("\0", "utf8");
    treeHash.update(String(metadata.size), "utf8");
    treeHash.update("\0", "utf8");
    treeHash.update(hash, "ascii");
    treeHash.update("\n", "utf8");
  }
  return { files, sha256: treeHash.digest("hex") };
}
