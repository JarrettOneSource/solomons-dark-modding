import { readFile } from "node:fs/promises";
import { spawnSync } from "node:child_process";
import path from "node:path";

const workspace = path.resolve(import.meta.dirname, "..");
const floors = JSON.parse(
  await readFile(path.join(workspace, "quality-floors.json"), "utf8"),
);
for (const key of ["unitTestFiles", "unitTests"]) {
  if (!Number.isSafeInteger(floors[key]) || floors[key] <= 0) {
    throw new Error(`${key} must be a positive integer`);
  }
}

const result = spawnSync("vitest", ["run", "--reporter=json"], {
  cwd: workspace,
  encoding: "utf8",
  shell: process.platform === "win32",
});
if (result.error) {
  throw new Error(`unit-test runner could not execute: ${result.error.message}`);
}
if (result.status !== 0) {
  process.stdout.write(result.stdout);
  process.stderr.write(result.stderr);
  process.exit(result.status ?? 1);
}

const report = JSON.parse(result.stdout);
const testFiles = Array.isArray(report.testResults) ? report.testResults.length : undefined;
const tests = report.numTotalTests;
if (!Number.isSafeInteger(testFiles) || !Number.isSafeInteger(tests)) {
  throw new Error("Vitest JSON report did not contain suite and test counts");
}
if (testFiles < floors.unitTestFiles) {
  throw new Error(
    `unit tests reached ${testFiles} files; floor is ${floors.unitTestFiles}`,
  );
}
if (tests < floors.unitTests) {
  throw new Error(`unit tests reached ${tests} cases; floor is ${floors.unitTests}`);
}
console.log(
  `${testFiles}/${testFiles} webgame test files passed (${tests} tests); `
    + `floors ${floors.unitTestFiles} files/${floors.unitTests} tests`,
);
