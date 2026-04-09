# Find functions that reference a specific global pointer and one or more field
# offsets somewhere in the same function body.
# Usage:
#   -postScript .../find_global_field_accesses.py 0x00B401A8 0x69 0x70
#   -postScript .../find_global_field_accesses.py 0x00B401A8 0x69 0x70 --decompile 8
# @category: Analysis

from ghidra.app.decompiler import DecompInterface
from ghidra.program.model.address import Address
from ghidra.program.model.scalar import Scalar


def parse_args():
    raw = [a.strip() for a in getScriptArgs() if a.strip()]
    if len(raw) < 2:
        print("ERROR: expected <global_addr> <offset> [more offsets] [--decompile N]")
        raise SystemExit(1)

    global_addr = raw[0]
    offsets = []
    decompile_count = 0
    i = 1
    while i < len(raw):
        cur = raw[i]
        if cur == "--decompile":
            if i + 1 >= len(raw):
                print("ERROR: --decompile requires a count")
                raise SystemExit(1)
            decompile_count = int(raw[i + 1])
            i += 2
            continue
        offsets.append(int(cur, 16) if cur.lower().startswith("0x") else int(cur))
        i += 1

    if not offsets:
        print("ERROR: no offsets parsed")
        raise SystemExit(1)
    return global_addr, offsets, decompile_count


target_global_text, target_offsets, decompile_count = parse_args()
target_global = toAddr(target_global_text)
target_offset_set = set(target_offsets)

program = currentProgram
listing = program.getListing()
fm = program.getFunctionManager()

results = []

funcs = fm.getFunctions(True)
while funcs.hasNext():
    func = funcs.next()
    saw_global = False
    global_hits = []
    offset_counts = {}
    offset_hits = []

    insts = listing.getInstructions(func.getBody(), True)
    while insts.hasNext():
        inst = insts.next()

        has_global_here = False
        refs = inst.getReferencesFrom()
        for ref in refs:
            if ref.getToAddress() == target_global:
                has_global_here = True
                break

        if not has_global_here:
            for op_index in range(inst.getNumOperands()):
                objs = inst.getOpObjects(op_index)
                for obj in objs:
                    if isinstance(obj, Address) and obj == target_global:
                        has_global_here = True
                        break
                if has_global_here:
                    break

        if has_global_here:
            saw_global = True
            global_hits.append(str(inst.getAddress()))

        matched_offsets = []
        for op_index in range(inst.getNumOperands()):
            objs = inst.getOpObjects(op_index)
            for obj in objs:
                if isinstance(obj, Scalar):
                    value = obj.getUnsignedValue()
                    if value in target_offset_set:
                        matched_offsets.append(value)

        if matched_offsets:
            offset_hits.append(str(inst.getAddress()))
            for value in matched_offsets:
                offset_counts[value] = offset_counts.get(value, 0) + 1

    if saw_global and offset_counts:
        score = sum(offset_counts.values())
        results.append((score, func, global_hits, offset_counts, offset_hits))

results.sort(key=lambda item: (-item[0], str(item[1].getEntryPoint())))

print("=== TARGET GLOBAL ===")
print("  %s" % target_global)
print("=== TARGET OFFSETS ===")
for off in target_offsets:
    print("  0x%x" % off)
print()

for score, func, global_hits, offset_counts, offset_hits in results:
    parts = []
    for off in target_offsets:
        if off in offset_counts:
            parts.append("0x%x=%d" % (off, offset_counts[off]))
    print("FUNCTION %s @ %s score=%d %s" %
          (func.getName(), func.getEntryPoint(), score, " ".join(parts)))
    print("  GLOBAL_HITS %s" % ", ".join(global_hits[:8]))
    if len(global_hits) > 8:
        print("  GLOBAL_HITS_MORE %d" % (len(global_hits) - 8))
    print("  OFFSET_HITS %s" % ", ".join(offset_hits[:16]))
    if len(offset_hits) > 16:
        print("  OFFSET_HITS_MORE %d" % (len(offset_hits) - 16))
print()

if decompile_count > 0:
    decomp = DecompInterface()
    decomp.openProgram(program)
    print("=== TOP DECOMPILES ===")
    for score, func, global_hits, offset_counts, offset_hits in results[:decompile_count]:
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
