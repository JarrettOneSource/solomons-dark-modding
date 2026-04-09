# Dump the first N instructions of one or more functions.
# Usage:
#   -postScript .../dump_function_instructions.py 24 0x140209ac0 0x140221730
# @category: Analysis


def parse_args():
    args = [a.strip() for a in getScriptArgs() if a.strip()]
    if len(args) < 2:
        print("ERROR: expected <count> <func_addr_or_name> [more]")
        raise SystemExit(1)
    count = int(args[0], 16) if args[0].lower().startswith("0x") else int(args[0])
    return count, args[1:]


def resolve_target(text):
    if text.startswith("0x") or text.startswith("0X"):
        addr = toAddr(text)
        func = getFunctionAt(addr)
        if func is None:
            func = getFunctionContaining(addr)
        return func
    fm = currentProgram.getFunctionManager()
    it = fm.getFunctions(True)
    while it.hasNext():
        func = it.next()
        if func.getName() == text:
            return func
    return None


count, targets = parse_args()
listing = currentProgram.getListing()

for target in targets:
    print("=== TARGET: %s ===" % target)
    func = resolve_target(target)
    if func is None:
        print("ERROR: could not resolve target")
        continue
    print("FUNCTION %s @ %s" % (func.getName(), func.getEntryPoint()))
    insts = listing.getInstructions(func.getBody(), True)
    seen = 0
    while insts.hasNext() and seen < count:
        inst = insts.next()
        print("%s %s" % (inst.getAddress(), inst))
        seen += 1
    print()

print("=== DONE ===")
