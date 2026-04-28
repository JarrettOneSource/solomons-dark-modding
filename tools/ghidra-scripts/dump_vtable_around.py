# -*- coding: utf-8 -*-
# Dump entries near a vtable address, look up function names, and find vtable owner.
# Usage: -postScript dump_vtable_around.py 0x0079e0a8

from ghidra.app.decompiler import DecompInterface


def parse_args():
    args = [a.strip() for a in getScriptArgs() if a.strip()]
    if not args:
        print("usage: <addr_hex>")
        raise SystemExit(1)
    return args


program = currentProgram
fm = program.getFunctionManager()
mem = program.getMemory()
ref_mgr = program.getReferenceManager()
sym_table = program.getSymbolTable()

decomp = DecompInterface()
decomp.openProgram(program)


def lookup_at(addr_int):
    addr = toAddr(addr_int)
    sym = getSymbolAt(addr)
    sym_name = sym.getName() if sym is not None else ""
    fn = fm.getFunctionAt(addr) or fm.getFunctionContaining(addr)
    fn_name = fn.getName() if fn is not None else ""
    return sym_name, fn_name


for arg in parse_args():
    base = int(arg, 16) if arg.lower().startswith("0x") else int(arg, 16)
    print("===== Around 0x%x =====" % base)
    # Look 16 entries before and 32 after
    for i in range(-16, 64):
        cur_addr = toAddr(base + i * 4)
        try:
            v = mem.getInt(cur_addr) & 0xffffffff
        except:
            print("  +%4d  %s  ERROR" % (i*4, cur_addr))
            continue
        sym, fn_name = lookup_at(v)
        # Find a label at this slot (i.e., what symbol points here)
        slot_sym = getSymbolAt(cur_addr)
        slot_name = slot_sym.getName() if slot_sym is not None else ""
        print("  %s [%-30s] = 0x%08x  %s %s" % (cur_addr, slot_name, v, sym, ("(%s)" % fn_name) if fn_name else ""))

    # Find references TO base — that's the class vtable user
    print("\nReferences TO 0x%x:" % base)
    refs = ref_mgr.getReferencesTo(toAddr(base))
    seen_funcs = set()
    for ref in refs:
        from_addr = ref.getFromAddress()
        fn = fm.getFunctionContaining(from_addr)
        fn_name = fn.getName() if fn else "-"
        seen_funcs.add(str(fn.getEntryPoint()) if fn else None)
        print("  from %s type=%s in=%s" % (from_addr, ref.getReferenceType(), fn_name))
    print("  unique src funcs: %d" % len(seen_funcs))

    # Decompile the source functions (if any) to reveal the constructor / installer
    if seen_funcs:
        print("\n=== Decompiling source functions of vtable refs ===")
        for fn_entry in seen_funcs:
            if fn_entry is None:
                continue
            fn = fm.getFunctionAt(toAddr(fn_entry))
            if fn is None:
                continue
            print("\n--- %s @ %s ---" % (fn.getName(), fn.getEntryPoint()))
            res = decomp.decompileFunction(fn, 240, monitor)
            if res is not None and res.decompileCompleted():
                print(res.getDecompiledFunction().getC())

decomp.dispose()
print("\n=== DONE ===")
