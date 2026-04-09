# Resolve one or more vtable symbols and print the function pointer found at a slot.
# Usage:
#   -postScript .../vtable_slot_lookup.py 0x180 "Skeleton::vftable" "Zombie::vftable"
# @category: Analysis

from ghidra.program.model.mem import MemoryAccessException


def parse_args():
    args = [a for a in getScriptArgs() if a.strip()]
    if len(args) < 2:
        print("ERROR: expected <slot_offset> <vtable_symbol> [more symbols]")
        raise SystemExit(1)
    slot_text = args[0].strip()
    slot = int(slot_text, 16) if slot_text.lower().startswith("0x") else int(slot_text)
    return slot, [a.strip() for a in args[1:] if a.strip()]


def find_symbol_exact_or_contains(name):
    sym_table = currentProgram.getSymbolTable()
    exact = []
    it = sym_table.getSymbols(name)
    while it.hasNext():
        exact.append(it.next())
    if exact:
        return exact

    hits = []
    it = sym_table.getAllSymbols(True)
    while it.hasNext():
        sym = it.next()
        if name.lower() in sym.getName().lower():
            hits.append(sym)
    return hits


slot, names = parse_args()
mem = currentProgram.getMemory()
fm = currentProgram.getFunctionManager()

print("=== VTABLE SLOT LOOKUP slot=0x%x ===" % slot)
for name in names:
    print("--- SYMBOL QUERY: %s ---" % name)
    if name.startswith("0x") or name.startswith("0X"):
        addr = toAddr(name)
        try:
            target = toAddr(mem.getLong(addr.add(slot)))
        except MemoryAccessException as exc:
            print("%s slot_addr=%s ERROR %s" % (name, addr.add(slot), exc))
            continue
        func = fm.getFunctionContaining(target)
        if func is None:
            print("%s slot_addr=%s -> %s [no containing function]" %
                  (name, addr.add(slot), target))
        else:
            print("%s slot_addr=%s -> %s %s" %
                  (name, addr.add(slot), target, func.getName()))
        continue
    syms = find_symbol_exact_or_contains(name)
    if not syms:
        print("NO SYMBOLS FOUND")
        continue
    for sym in syms:
        addr = sym.getAddress()
        slot_addr = addr.add(slot)
        try:
            target = toAddr(mem.getLong(slot_addr))
        except MemoryAccessException as exc:
            print("%s @ %s slot_addr=%s ERROR %s" % (sym.getName(), addr, slot_addr, exc))
            continue
        func = fm.getFunctionContaining(target)
        if func is None:
            print("%s @ %s slot_addr=%s -> %s [no containing function]" %
                  (sym.getName(), addr, slot_addr, target))
        else:
            print("%s @ %s slot_addr=%s -> %s %s" %
                  (sym.getName(), addr, slot_addr, target, func.getName()))

print("=== DONE ===")
