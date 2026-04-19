"""Dump N instructions before and M instructions after each target address.

Usage:
    -postScript dump_insns_around.py <before> <after> <addr1> [addr2 ...]
"""

def parse_args():
    args = [a.strip() for a in getScriptArgs() if a.strip()]
    if len(args) < 3:
        print("ERROR: expected <before> <after> <addr1> [addr2 ...]")
        raise SystemExit(1)
    before = int(args[0])
    after = int(args[1])
    return before, after, args[2:]


before, after, targets = parse_args()
listing = currentProgram.getListing()

for t in targets:
    print("=== TARGET: %s ===" % t)
    addr = toAddr(t)
    inst = listing.getInstructionAt(addr)
    if inst is None:
        inst = listing.getInstructionContaining(addr)
    if inst is None:
        print("ERROR: no instruction at %s" % t)
        continue
    cursor = inst
    pre = []
    for _ in range(before):
        prev = cursor.getPrevious()
        if prev is None:
            break
        pre.append(prev)
        cursor = prev
    for p in reversed(pre):
        print("  %s %s" % (p.getAddress(), p))
    print("->%s %s" % (inst.getAddress(), inst))
    cursor = inst
    for _ in range(after):
        nxt = cursor.getNext()
        if nxt is None:
            break
        print("  %s %s" % (nxt.getAddress(), nxt))
        cursor = nxt
    print()

print("=== DONE ===")
