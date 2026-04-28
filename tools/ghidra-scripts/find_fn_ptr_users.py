# -*- coding: utf-8 -*-
# Find data references to a function address (i.e., function pointer installations).
# Plus dump what calls it through indirect means.
# Usage: -postScript find_fn_ptr_users.py 0x0060c540

import sys


def parse_args():
    args = [a.strip() for a in getScriptArgs() if a.strip()]
    if not args:
        print("usage: <fn_addr_hex>")
        raise SystemExit(1)
    return args


targets = parse_args()
program = currentProgram
ref_mgr = program.getReferenceManager()
fm = program.getFunctionManager()
listing = program.getListing()
mem = program.getMemory()

for target in targets:
    addr = toAddr(target)
    print("\n===== Target function: %s =====" % addr)

    # Direct references
    refs = ref_mgr.getReferencesTo(addr)
    print("References (any):")
    seen_funcs = set()
    for ref in refs:
        from_addr = ref.getFromAddress()
        ref_type = ref.getReferenceType()
        fn = fm.getFunctionContaining(from_addr)
        fn_name = fn.getName() if fn else "-"
        seen_funcs.add(str(fn.getEntryPoint())) if fn else None
        # Try to read the data at from_addr
        print("  from=%s type=%s in=%s" % (from_addr, ref_type, fn_name))
    print("  unique src funcs: %d" % len(seen_funcs))

    # Search for the int value of the target as a 4-byte little-endian dword in memory
    target_int = int(target, 16)
    print("\nSearching for raw dword 0x%x in .data/.bss..." % target_int)
    blocks = mem.getBlocks()
    for blk in blocks:
        if not blk.isInitialized():
            continue
        if blk.isExecute():
            # Skip code blocks for raw search since refs handle these
            continue
        start = blk.getStart()
        end = blk.getEnd()
        cur = start
        try:
            data = mem.getBytes(start, blk.getSize() if blk.getSize() < (1 << 24) else (1 << 24))
        except Exception as exc:
            print("  block %s: skip %s" % (blk.getName(), exc))
            continue
        # Java bytes are signed; we'll iterate via getInt
        # Just iterate as 4-byte aligned
        size = blk.getSize() if blk.getSize() < (1 << 24) else (1 << 24)
        for off in range(0, size - 4, 4):
            cur = start.add(off)
            try:
                val = mem.getInt(cur) & 0xffffffff
            except:
                continue
            if val == target_int:
                print("  found %s = 0x%x  in block %s" % (cur, val, blk.getName()))

print("\n=== DONE ===")
