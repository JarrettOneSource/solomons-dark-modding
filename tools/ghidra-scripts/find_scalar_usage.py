# -*- coding: utf-8 -*-
"""Find instruction operands whose scalar value matches one of the targets.

Usage:
    -postScript find_scalar_usage.py <value1> [value2 ...] [--max-hits N] [--decompile N]

Values may be decimal or hex.  The script checks scalar operand objects rather
than address-form text, so it catches small constants such as 4, 0x2000, and
0xBBE that do not appear as references.
"""

import sys

from ghidra.app.decompiler import DecompInterface
from ghidra.program.model.scalar import Scalar


def parse_int(text):
    text = text.strip()
    return int(text, 16) if text.lower().startswith("0x") else int(text, 10)


args = [a.strip() for a in getScriptArgs() if a.strip()]
if not args:
    print("usage: <value1> [value2 ...] [--max-hits N] [--decompile N]")
    raise SystemExit(1)

max_hits = 120
max_decompile = 0
values = []
index = 0
while index < len(args):
    arg = args[index]
    if arg == "--max-hits":
        index += 1
        max_hits = int(args[index])
    elif arg == "--decompile":
        index += 1
        max_decompile = int(args[index])
    else:
        values.append(parse_int(arg))
    index += 1

if not values:
    print("ERROR: no scalar values supplied")
    raise SystemExit(1)

targets = set(values)
hits = {value: [] for value in values}
program = currentProgram
listing = program.getListing()
fm = program.getFunctionManager()

inst_iter = listing.getInstructions(True)
while inst_iter.hasNext():
    inst = inst_iter.next()
    for operand_index in range(inst.getNumOperands()):
        matched = []
        for obj in inst.getOpObjects(operand_index):
            if not isinstance(obj, Scalar):
                continue
            scalar_value = obj.getValue()
            signed_value = obj.getSignedValue()
            if scalar_value in targets:
                matched.append(scalar_value)
            if signed_value in targets:
                matched.append(signed_value)
        for value in matched:
            if len(hits[value]) >= max_hits:
                continue
            func = fm.getFunctionContaining(inst.getAddress())
            hits[value].append((inst, operand_index, func))

for value in values:
    print("=== SCALAR %s / 0x%x - %d hits shown ===" % (value, value, len(hits[value])))
    seen_funcs = {}
    for inst, operand_index, func in hits[value]:
        func_text = "[no function]"
        if func is not None:
            func_text = "%s @ %s" % (func.getName(), func.getEntryPoint())
            seen_funcs[str(func.getEntryPoint())] = func
        print(
            "  %s op%d %s :: %s"
            % (inst.getAddress(), operand_index, inst, func_text)
        )
    if max_decompile > 0 and seen_funcs:
        decomp = DecompInterface()
        decomp.openProgram(program)
        funcs = list(seen_funcs.values())
        funcs.sort(key=lambda f: str(f.getEntryPoint()))
        for func in funcs[:max_decompile]:
            print("--- FUNCTION %s @ %s ---" % (func.getName(), func.getEntryPoint()))
            res = decomp.decompileFunction(func, 180, monitor)
            if res is None or not res.decompileCompleted():
                print("ERROR: decompilation failed")
            else:
                print(res.getDecompiledFunction().getC())
            print()
        decomp.dispose()
    print()

print("=== DONE ===")
