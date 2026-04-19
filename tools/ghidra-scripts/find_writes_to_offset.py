# -*- coding: utf-8 -*-
"""Search instructions that write a value to [reg + offset] for one or more offsets.

Only looks for FSTP-style float stores and MOV-style integer stores. Reports
function + address for each hit.

Usage:
    -postScript find_writes_to_offset.py 0x2d4 0x1b4
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
target_set = set(offsets)
program = currentProgram
listing = program.getListing()
fm = program.getFunctionManager()

hits = {off: [] for off in offsets}

inst_iter = listing.getInstructions(True)
while inst_iter.hasNext():
    inst = inst_iter.next()
    mnemonic = inst.getMnemonicString()
    # We want writes. Common float stores: FSTP; int stores: MOV with first op memory.
    is_store = mnemonic in ("FSTP", "FST", "MOV", "MOVSS", "MOVSD", "FISTP")
    if not is_store:
        continue
    # First operand must be memory
    op0_type = inst.getOperandType(0)
    # OP_TYPE_ADDR, OP_TYPE_DYNAMIC — but easier: check representation
    rep = inst.getDefaultOperandRepresentation(0)
    # representation looks like "[reg + 0x2d4]" or "[reg]"
    for off in offsets:
        # Accept both "+ 0x2d4" and "+ 0x2D4"
        variants = (
            "0x%x" % off,
            "0x%X" % off,
            "+ 0x%x" % off,
            "+ 0x%X" % off,
        )
        if any(v in rep for v in variants):
            # Ignore constant displacements on SP/BP (stack locals)
            if "ESP" in rep or "EBP" in rep:
                continue
            func = fm.getFunctionContaining(inst.getAddress())
            func_name = func.getName() if func else "-"
            hits[off].append((str(inst.getAddress()), func_name, rep, str(inst)))
            break

for off in offsets:
    print("=== OFFSET 0x%x - %d writes ===" % (off, len(hits[off])))
    for addr, func, rep, s in hits[off][:80]:
        print("  %s  %s  %s  %s" % (addr, func, rep, s))
    print()

print("=== DONE ===")
