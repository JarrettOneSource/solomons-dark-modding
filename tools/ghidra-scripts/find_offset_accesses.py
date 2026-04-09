# Scan instructions for specific scalar offsets/displacements and report functions
# that reference them. Useful for finding constructors or init routines that write
# to object fields like +0x194, +0x1c4, +0x204.
# Usage:
#   -postScript .../find_offset_accesses.py 0x194 0x1c4 0x204
#   -postScript .../find_offset_accesses.py 0x194 0x1c4 0x204 --decompile 8
# @category: Analysis

from ghidra.app.decompiler import DecompInterface
from ghidra.program.model.scalar import Scalar


def parse_args():
    raw = [a.strip() for a in getScriptArgs() if a.strip()]
    if not raw:
        print("ERROR: expected one or more offsets")
        raise SystemExit(1)

    offsets = []
    decompile_count = 0
    i = 0
    while i < len(raw):
        cur = raw[i]
        if cur == "--decompile":
            if i + 1 >= len(raw):
                print("ERROR: --decompile requires a count")
                raise SystemExit(1)
            decompile_count = int(raw[i + 1])
            i += 2
            continue
        if cur.startswith("0x") or cur.startswith("0X"):
            offsets.append(int(cur, 16))
        else:
            offsets.append(int(cur))
        i += 1

    if not offsets:
        print("ERROR: no offsets parsed")
        raise SystemExit(1)
    return offsets, decompile_count


targets, decompile_count = parse_args()
target_set = set(targets)
program = currentProgram
listing = program.getListing()
fm = program.getFunctionManager()

results = []

funcs = fm.getFunctions(True)
while funcs.hasNext():
    func = funcs.next()
    counts = {}
    hit_addrs = []
    insts = listing.getInstructions(func.getBody(), True)
    while insts.hasNext():
        inst = insts.next()
        matched = []
        for op_index in range(inst.getNumOperands()):
            objs = inst.getOpObjects(op_index)
            for obj in objs:
                if isinstance(obj, Scalar):
                    val = obj.getUnsignedValue()
                    if val in target_set:
                        matched.append(val)
        if matched:
            hit_addrs.append(str(inst.getAddress()))
            for val in matched:
                counts[val] = counts.get(val, 0) + 1
    if counts:
        score = sum(counts.values())
        results.append((score, func, counts, hit_addrs))

results.sort(key=lambda item: (-item[0], str(item[1].getEntryPoint())))

print("=== TARGET OFFSETS ===")
for off in targets:
    print("  0x%x" % off)
print()

for score, func, counts, hit_addrs in results:
    parts = []
    for off in targets:
        if off in counts:
            parts.append("0x%x=%d" % (off, counts[off]))
    print("FUNCTION %s @ %s score=%d %s" %
          (func.getName(), func.getEntryPoint(), score, " ".join(parts)))
    print("  HIT_ADDRS %s" % ", ".join(hit_addrs[:16]))
    if len(hit_addrs) > 16:
        print("  HIT_ADDRS_MORE %d" % (len(hit_addrs) - 16))
print()

if decompile_count > 0:
    decomp = DecompInterface()
    decomp.openProgram(program)
    print("=== TOP DECOMPILES ===")
    for score, func, counts, hit_addrs in results[:decompile_count]:
        print("--- FUNCTION %s @ %s score=%d ---" %
              (func.getName(), func.getEntryPoint(), score))
        res = decomp.decompileFunction(func, 180, monitor)
        if res is None or not res.decompileCompleted():
            print("ERROR: decompilation failed")
        else:
            print(res.getDecompiledFunction().getC())
        print()
    decomp.dispose()

print("=== DONE ===")
