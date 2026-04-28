# -*- coding: utf-8 -*-
# For each candidate address that adds 0x4210 to a register, find the
# containing function and dump ~16 instructions of context (8 before, 8 after).
# Also report any CALL targets within that window.
#
# Args: list of hex addresses to probe.

import sys

args = [a.strip() for a in getScriptArgs() if a.strip()]
listing = currentProgram.getListing()
fm = currentProgram.getFunctionManager()

for arg in args:
    try:
        addr = toAddr(arg)
    except:
        print("BADARG: %s" % arg)
        continue
    fn = fm.getFunctionContaining(addr)
    if fn is None:
        print("\n=== %s: NO_FN ===" % arg)
        continue
    print("\n=== %s in %s @ %s (size=%d) ===" % (
        arg, fn.getName(), fn.getEntryPoint(),
        fn.getBody().getNumAddresses()))
    body_iter = listing.getInstructions(fn.getBody(), True)
    insns = []
    for ins in body_iter:
        insns.append(ins)
    target_idx = -1
    for i, ins in enumerate(insns):
        if ins.getAddress() == addr:
            target_idx = i
            break
    if target_idx < 0:
        # find closest
        for i, ins in enumerate(insns):
            if ins.getAddress().getOffset() >= addr.getOffset():
                target_idx = i
                break
    lo = max(0, target_idx - 8)
    hi = min(len(insns), target_idx + 9)
    for i in range(lo, hi):
        ins = insns[i]
        marker = " >>>" if i == target_idx else "    "
        print("%s%s  %s" % (marker, ins.getAddress(), ins.toString()))
