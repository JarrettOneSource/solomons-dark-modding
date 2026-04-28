# -*- coding: utf-8 -*-
# Dump assembly of Text_Draw and FUN_00414540, plus look at the HUD render path.

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


def disasm_fn(addr_int, label):
    fn = fm.getFunctionAt(toAddr(addr_int)) or fm.getFunctionContaining(toAddr(addr_int))
    if fn is None:
        print("=== %s @ 0x%x: NO_FN ===" % (label, addr_int))
        return
    print("=== ASM %s @ %s [body=%s] ===" % (label, fn.getEntryPoint(), fn.getBody()))
    iter_ = listing.getInstructions(fn.getBody(), True)
    while iter_.hasNext():
        ins = iter_.next()
        print("  %s  %s" % (ins.getAddress(), ins))


def decomp_fn(addr_int, label):
    fn = fm.getFunctionAt(toAddr(addr_int)) or fm.getFunctionContaining(toAddr(addr_int))
    if fn is None:
        print("=== %s @ 0x%x: NO_FN ===" % (label, addr_int))
        return
    print("=== DECOMP %s @ %s ===" % (label, fn.getEntryPoint()))
    res = decomp.decompileFunction(fn, 240, monitor)
    if res is None or not res.decompileCompleted():
        print("  DECOMP_FAILED")
        return
    print(res.getDecompiledFunction().getC())


# Text_Draw
disasm_fn(0x00415130, "Text_Draw")
print()

# FUN_00414540 (TextQuad_Draw inner)
disasm_fn(0x00414540, "FUN_00414540")
print()

# Look at FUN_00420030 (referenced by FUN_00414540 for texture handle)
decomp_fn(0x00420030, "FUN_00420030 (texture set?)")
print()

# Look at TextQuad_Draw
print("=== TextQuad_Draw symbol search ===")
sym_iter = program.getSymbolTable().getSymbols("TextQuad_Draw")
for s in sym_iter:
    print("  found %s @ %s" % (s.getName(), s.getAddress()))
    decomp_fn(int(str(s.getAddress()), 16), "TextQuad_Draw")

# Find writes to DAT_00819978 + 0x4210 (= 0x81db88)
print("\n#######################################")
print("# Writes to DAT_00819978+0x4210 (0x81db88) and table base")
print("#######################################")
for offset in [0x4210, 0x4204, 0x4208, 0x4200, 0]:
    target = 0x00819978 + offset
    print("=== WRITES to 0x%x ===" % target)
    refs = ref_mgr.getReferencesTo(toAddr(target))
    for ref in refs:
        if str(ref.getReferenceType()).startswith("WRITE") or "WRITE" in str(ref.getReferenceType()):
            from_addr = ref.getFromAddress()
            fn = fm.getFunctionContaining(from_addr)
            fn_name = fn.getName() if fn else "-"
            print("  WRITE from %s in %s" % (from_addr, fn_name))

# Also: dump FUN_00512060 (HUD dispatch) — it calls Text_Draw and references DAT_008199b8
decomp_fn(0x00512060, "FUN_00512060 (HUD dispatch)")
print()

# FUN_005ae510 — has WRITE reference to DAT_008199b8
decomp_fn(0x005ae510, "FUN_005ae510 (writer to DAT_008199b8 base)")
print()

decomp.dispose()
print("=== DONE ===")
