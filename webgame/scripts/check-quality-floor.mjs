import { readFile, readdir } from "node:fs/promises";
import path from "node:path";

const mode = process.argv[2];
if (mode !== "lint" && mode !== "typecheck") {
  throw new Error("quality-floor mode must be lint or typecheck");
}

const workspace = path.resolve(import.meta.dirname, "..");
const floors = JSON.parse(
  await readFile(path.join(workspace, "quality-floors.json"), "utf8"),
);
const ignoredDirectories = new Set(["dist", "node_modules"]);

async function collect(directory) {
  const files = [];
  for (const entry of await readdir(directory, { withFileTypes: true })) {
    if (entry.isDirectory()) {
      if (!ignoredDirectories.has(entry.name)) {
        files.push(...await collect(path.join(directory, entry.name)));
      }
      continue;
    }
    if (!entry.isFile()) {
      continue;
    }
    const extension = path.extname(entry.name);
    if (
      extension === ".ts"
      || (mode === "lint" && (extension === ".js" || extension === ".mjs"))
    ) {
      files.push(path.join(directory, entry.name));
    }
  }
  return files;
}

const files = await collect(workspace);
const floor = mode === "lint" ? floors.lintFiles : floors.typecheckedFiles;
if (!Number.isSafeInteger(floor) || floor <= 0) {
  throw new Error(`${mode} file floor must be a positive integer`);
}
if (files.length < floor) {
  throw new Error(
    `${mode} reached ${files.length} files; floor is ${floor}, so source escaped the gate`,
  );
}
console.log(`${mode} floor passed: ${files.length} files (floor ${floor})`);
