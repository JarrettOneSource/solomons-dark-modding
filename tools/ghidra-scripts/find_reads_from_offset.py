# -*- coding: utf-8 -*-
"""Search instructions that read a value from [reg + offset] for one or more offsets.

Only looks for FLD-style float loads and MOV-style integer loads where the
memory operand is the SECOND operand (source). Reports function + address.

Usage:
    -postScript find_reads_from_offset.py 0x2d4 0x1b4
"""


def parse_args():
    raw = [a.strip() for a in getScriptArgs() if a.strip()]
    if not raw:
        print("ERROR: expected offsets")
        raise SystemExit(1)
    out = []
    for r in raw:
        if r.lower().startswith("0x"):
            out.append(int(r, 16))
        else:
            out.append(int(r))
    return out


offsets = parse_args()
program = currentProgram
listing = program.getListing()
fm = program.getFunctionManager()

hits = {off: [] for off in offsets}

inst_iter = listing.getInstructions(True)
while inst_iter.hasNext():
    inst = inst_iter.next()
    mnemonic = inst.getMnemonicString()
    # Float load or integer load patterns
    is_load = mnemonic in ("FLD", "FILD", "MOV", "MOVSS", "MOVSD", "MOVSX", "MOVZX",
                           "LEA", "FADD", "FSUB", "FMUL", "FDIV", "FCOMP", "FCOM",
                           "CMP", "TEST", "PUSH")
    if not is_load:
        continue
    # For FLD/FADD/etc the memory operand is op0 (loading into ST).
    # For MOV/MOVSS/etc with memory source, it's op1.
    # For PUSH it's op0. We just scan all operands for the offset pattern.
    found = False
    num_ops = inst.getNumOperands()
    for i in range(num_ops):
        rep = inst.getDefaultOperandRepresentation(i)
        for off in offsets:
            variants = (
                "+ 0x%x" % off,
                "+ 0x%X" % off,
            )
            if any(v in rep for v in variants):
                if "ESP" in rep or "EBP" in rep:
                    continue
                # For MOV we need the memory op to be the SOURCE (op1), not dest.
                # If the mnemonic is MOV and this is op0 (dest), it's a write.
                if mnemonic.startswith("MOV") and i == 0:
                    continue
                func = fm.getFunctionContaining(inst.getAddress())
                func_name = func.getName() if func else "-"
                hits[off].append((str(inst.getAddress()), func_name, rep, str(inst)))
                found = True
                break
        if found:
            break

for off in offsets:
    print("=== OFFSET 0x%x - %d reads ===" % (off, len(hits[off])))
    for addr, func, rep, s in hits[off][:80]:
        print("  %s  %s  %s  %s" % (addr, func, rep, s))
    print()

print("=== DONE ===")
