# -*- coding: utf-8 -*-
# Dump full disassembly of a function

from ghidra.app.decompiler import DecompInterface

program = currentProgram
listing = program.getListing()
fm = program.getFunctionManager()

args = [a.strip() for a in getScriptArgs() if a.strip()]
if not args:
    raise SystemExit(1)

for arg in args:
    addr = toAddr(arg)
    fn = fm.getFunctionAt(addr) or fm.getFunctionContaining(addr)
    if fn is None:
        print("NO_FN: %s" % arg)
        continue
    print("=== ASM %s @ %s ===" % (fn.getName(), fn.getEntryPoint()))
    iter_ = listing.getInstructions(fn.getBody(), True)
    while iter_.hasNext():
        ins = iter_.next()
        print("  %s  %s" % (ins.getAddress(), ins))
print("=== DONE ===")
