# Lookup vtable symbols for Item_Staff, Item_Potion, and Item
from ghidra.program.model.symbol import SymbolType
sm = currentProgram.getSymbolTable()
for name in ["Item_Staff", "Item_Potion", "Item"]:
    # Search for vftable or RTTI symbols
    for sym in sm.getSymbolIterator():
        sname = sym.getName()
        if name in sname and ("vftable" in sname or "vbtable" in sname or "RTTI" in sname or "::" in sname):
            print("SYMBOL: %s = 0x%08X (type=%s)" % (sname, sym.getAddress().getOffset(), sym.getSymbolType()))
            break
    # Also search in labels
    for sym in sm.getExternalSymbols():
        sname = sym.getName()
        if name in sname:
            print("EXT_SYMBOL: %s = 0x%08X" % (sname, sym.getAddress().getOffset()))
