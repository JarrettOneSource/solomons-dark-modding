import { proveCrossProcessDeterminism } from "./determinism.js";

const tickArgument = process.argv[2];
const ticks = tickArgument === undefined ? 1_000 : Number(tickArgument);
const receipt = await proveCrossProcessDeterminism(ticks);
process.stdout.write(`${JSON.stringify(receipt, null, 2)}\n`);
