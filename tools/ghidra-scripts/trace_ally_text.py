# Trace the ALLY text rendering pipeline.
# - dumps raw bytes near DAT_00819978 + 0x4210
# - decompiles Text_Draw and FUN_00414540 in full
# - finds writers to DAT_00819978 + 0x4210
# - finds writers to DAT_00819978 base region
# - lists callers of Text_Draw and what arg patterns they use

from ghidra.app.decompiler import DecompInterface
from ghidra.program.model.mem import MemoryAccessException
from java.lang import Float

program = currentProgram
listing = program.getListing()
fm = program.getFunctionManager()
mem = program.getMemory()
ref_mgr = program.getReferenceManager()

decomp = DecompInterface()
decomp.openProgram(program)


def dump_bytes(label, addr_int, count):
    addr = toAddr(addr_int)
    print("=== %s @ 0x%x (count=%d bytes) ===" % (label, addr_int, count))
    bs = []
    for i in range(count):
        try:
            v = mem.getByte(addr.add(i)) & 0xff
            bs.append(v)
        except MemoryAccessException as exc:
            print("  ERROR @ %s: %s" % (addr.add(i), exc))
            return
    # hex dump in 16 byte rows with ASCII
    for row in range(0, len(bs), 16):
        chunk = bs[row:row+16]
        hex_part = " ".join("%02x" % b for b in chunk)
        ascii_part = "".join(chr(b) if 32 <= b < 127 else "." for b in chunk)
        print("  %08x  %-48s  %s" % (addr_int + row, hex_part, ascii_part))


def dump_ints(label, addr_int, count):
    addr = toAddr(addr_int)
    print("=== %s ints @ 0x%x (count=%d) ===" % (label, addr_int, count))
    for i in range(count):
        cur = addr.add(i * 4)
        try:
            v = mem.getInt(cur) & 0xffffffff
            f = Float.intBitsToFloat(mem.getInt(cur))
            sym = ""
            symref = getSymbolAt(toAddr(v))
            if symref is not None:
                sym = " sym=%s" % symref.getName()
            print("  +0x%04x  %s  int=0x%08x  float=%g%s" % (i*4, cur, v, f, sym))
        except MemoryAccessException as exc:
            print("  ERROR: %s" % exc)
            return


def decompile_fn(addr_int, label):
    addr = toAddr(addr_int)
    fn = fm.getFunctionAt(addr) or fm.getFunctionContaining(addr)
    if fn is None:
        print("=== %s @ 0x%x: NO_FN ===" % (label, addr_int))
        return
    print("=== %s @ %s [%s] ===" % (label, fn.getEntryPoint(), fn.getSignature()))
    res = decomp.decompileFunction(fn, 180, monitor)
    if res is None or not res.decompileCompleted():
        print("  DECOMP_FAILED")
        return
    print(res.getDecompiledFunction().getC())


def find_refs(addr_int, label):
    addr = toAddr(addr_int)
    print("=== refs to %s @ 0x%x ===" % (label, addr_int))
    refs = ref_mgr.getReferencesTo(addr)
    seen_funcs = set()
    for ref in refs:
        from_addr = ref.getFromAddress()
        fn = fm.getFunctionContaining(from_addr)
        fn_name = fn.getName() if fn else "-"
        fn_entry = str(fn.getEntryPoint()) if fn else "-"
        seen_funcs.add(fn_entry)
        print("  from %s  type=%s  fn=%s @ %s" % (from_addr, ref.getReferenceType(), fn_name, fn_entry))
    print("  unique funcs: %d" % len(seen_funcs))


# 1. Dump raw bytes at DAT_00819978 + 0x4210 (could be ptr/string/struct)
DAT_00819978 = 0x00819978
TEXT_OFF = 0x4210
text_struct_addr = DAT_00819978 + TEXT_OFF

print("\n#######################################")
print("# 1. RAW DATA AT TEXT RESOURCE         ")
print("#######################################")
dump_bytes("DAT_00819978+0x4210 raw", text_struct_addr, 0x80)
dump_ints("DAT_00819978+0x4210 ints", text_struct_addr, 32)

# also the area around it
print("\n# Surrounding entries (assume struct stride may vary):")
dump_ints("0x4200-0x4250", DAT_00819978 + 0x4200, 24)
dump_ints("0x4180-0x4200", DAT_00819978 + 0x4180, 32)

# 2. Decompile Text_Draw
print("\n#######################################")
print("# 2. Text_Draw and FUN_00414540        ")
print("#######################################")
decompile_fn(0x00415130, "Text_Draw")
decompile_fn(0x00414540, "FUN_00414540 (inner quad draw)")

# Also find what calls Text_Draw to see arg patterns
print("\n#######################################")
print("# 3. Callers of Text_Draw              ")
print("#######################################")
text_draw_fn = fm.getFunctionAt(toAddr(0x00415130))
if text_draw_fn is not None:
    callers = text_draw_fn.getCallingFunctions(monitor)
    print("Total caller functions: %d" % callers.size())
    sorted_callers = sorted(callers, key=lambda f: str(f.getEntryPoint()))
    for fn in sorted_callers[:60]:
        print("  caller %s @ %s" % (fn.getName(), fn.getEntryPoint()))

# 4. Refs to DAT_00819978+0x4210 and base DAT_00819978
print("\n#######################################")
print("# 4. References to DAT_00819978+0x4210 ")
print("#######################################")
find_refs(text_struct_addr, "DAT_00819978+0x4210")

print("\n# Refs to DAT_00819978 base:")
find_refs(DAT_00819978, "DAT_00819978")

print("\n# Refs to DAT_008199b8 (other text base):")
find_refs(0x008199b8, "DAT_008199b8")

# 5. Callers of FUN_0060c540 (the ally-bar draw fn)
print("\n#######################################")
print("# 5. Callers of FUN_0060c540           ")
print("#######################################")
fn_60c540 = fm.getFunctionAt(toAddr(0x0060c540))
if fn_60c540 is not None:
    callers = fn_60c540.getCallingFunctions(monitor)
    print("Total: %d" % callers.size())
    for fn in sorted(callers, key=lambda f: str(f.getEntryPoint())):
        print("  %s @ %s" % (fn.getName(), fn.getEntryPoint()))

decomp.dispose()
print("\n=== DONE ===")
