# Dump a sequence of ints/floats from memory.
# Usage:
#   -postScript .../dump_array.py 0x140898d20 int 64
#   -postScript .../dump_array.py 0x140898d20 float 64
# @category: Analysis

from ghidra.program.model.mem import MemoryAccessException
from java.lang import Float


def parse_args():
    args = [a.strip() for a in getScriptArgs() if a.strip()]
    if len(args) < 3:
        print("ERROR: expected <addr> <int|float|byte> <count>")
        raise SystemExit(1)
    return args[0], args[1].lower(), int(args[2])


addr_text, kind, count = parse_args()
addr = toAddr(addr_text)
mem = currentProgram.getMemory()

sizes = {"byte": 1, "int": 4, "float": 4}
if kind not in sizes:
    print("ERROR: unsupported kind %s" % kind)
    raise SystemExit(1)

size = sizes[kind]
print("=== DUMP %s %s count=%d ===" % (addr, kind, count))
for i in range(count):
    cur = addr.add(i * size)
    try:
        if kind == "byte":
            val = mem.getByte(cur) & 0xff
        elif kind == "int":
            val = mem.getInt(cur)
        else:
            val = Float.intBitsToFloat(mem.getInt(cur))
        print("%04d %s %s" % (i, cur, val))
    except MemoryAccessException as exc:
        print("%04d %s ERROR %s" % (i, cur, exc))
        break

print("=== DONE ===")
