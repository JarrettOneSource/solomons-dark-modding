# Scan instructions for any direct address operands/references that fall inside a range.
# Usage:
#   -postScript .../refs_in_range.py 0x1408f4bb0 0x1408f4bc0
# @category: Analysis

from ghidra.program.model.address import Address


def parse_args():
    args = [a.strip() for a in getScriptArgs() if a.strip()]
    if len(args) != 2:
        print("ERROR: expected <start_addr> <end_addr>")
        raise SystemExit(1)
    return toAddr(args[0]), toAddr(args[1])


start, end = parse_args()
listing = currentProgram.getListing()
fm = currentProgram.getFunctionManager()

print("=== REFS IN RANGE %s..%s ===" % (start, end))

insts = listing.getInstructions(True)
count = 0
while insts.hasNext():
    inst = insts.next()
    matched = []
    for op_index in range(inst.getNumOperands()):
        for obj in inst.getOpObjects(op_index):
            if isinstance(obj, Address):
                if obj.compareTo(start) >= 0 and obj.compareTo(end) <= 0:
                    matched.append(obj)
    if matched:
        func = fm.getFunctionContaining(inst.getAddress())
        func_name = "[no containing function]"
        func_addr = ""
        if func is not None:
            func_name = func.getName()
            func_addr = " @ %s" % func.getEntryPoint()
        print("%s %s%s :: %s" %
              (inst.getAddress(), func_name, func_addr, inst))
        print("  TARGETS %s" % ", ".join([str(x) for x in matched]))
        count += 1

print("COUNT %d" % count)
print("=== DONE ===")
