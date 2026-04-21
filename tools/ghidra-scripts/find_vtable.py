# Find the symbol at a given address, useful for identifying vtables.
# Usage: -postScript find_vtable.py 0x0046C9F4 0x00463F74 0x0046C854
from ghidra.program.model.symbol import SymbolType

args = [a.strip() for a in getScriptArgs() if a.strip()]
sm = currentProgram.getSymbolTable()

for arg in args:
    addr = toAddr(arg)
    print("=== ADDR: %s ===" % arg)
    primary = sm.getPrimarySymbol(addr)
    if primary is not None:
        print("PRIMARY: %s type=%s ns=%s" % (primary.getName(), primary.getSymbolType(), primary.getParentNamespace()))
    for sym in sm.getSymbols(addr):
        print("SYM: %s type=%s ns=%s" % (sym.getName(), sym.getSymbolType(), sym.getParentNamespace()))
    # Read first 4 bytes (first vtable slot) to identify function
    mem = currentProgram.getMemory()
    try:
        first_slot_val = mem.getInt(addr) & 0xFFFFFFFF
        first_slot = toAddr(first_slot_val)
        print("FIRST_SLOT: 0x%08X" % first_slot_val)
        fn = getFunctionAt(first_slot) or getFunctionContaining(first_slot)
        if fn is not None:
            print("FIRST_SLOT_FN: %s @ %s" % (fn.getName(), fn.getEntryPoint()))
    except Exception as e:
        print("ERROR: %s" % e)
