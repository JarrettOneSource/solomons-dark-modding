# Find all functions referencing one or more addresses and decompile them.
# Usage:
#   -postScript .../refs_to_addr_decompile.py 0x1408a7c08 0x1408a7c0c [max_funcs]
# @category: Analysis

from ghidra.app.decompiler import DecompInterface


def parse_args():
    args = [a.strip() for a in getScriptArgs() if a.strip()]
    if not args:
        print("ERROR: expected at least one address")
        raise SystemExit(1)

    max_funcs = 30
    try:
        max_funcs = int(args[-1])
        args = args[:-1]
    except:
        pass

    if not args:
        print("ERROR: no addresses after parsing")
        raise SystemExit(1)
    return args, max_funcs


targets, max_funcs = parse_args()
program = currentProgram
fm = program.getFunctionManager()

decomp = DecompInterface()
decomp.openProgram(program)

print("=== REF TARGETS ===")
for target in targets:
    print("  " + target)
print()

for target in targets:
    addr = toAddr(target)
    print("=== ADDRESS: %s ===" % addr)
    funcs = {}
    refs = getReferencesTo(addr)
    count = 0
    for ref in refs:
        count += 1
        ref_addr = ref.getFromAddress()
        func = fm.getFunctionContaining(ref_addr)
        if func is not None:
            funcs[str(func.getEntryPoint())] = (func, ref_addr)
            print("REF from %s in %s" % (ref_addr, func.getName()))
        else:
            print("REF from %s in [no containing function]" % ref_addr)

    func_list = [x[0] for x in funcs.values()]
    func_list.sort(key=lambda f: str(f.getEntryPoint()))
    print("REF_COUNT %d" % count)
    print("FUNCTION_COUNT %d" % len(func_list))
    print()

    for func in func_list[:max_funcs]:
        print("--- FUNCTION %s @ %s ---" % (func.getName(), func.getEntryPoint()))
        print("SIGNATURE: %s" % func.getSignature())
        res = decomp.decompileFunction(func, 180, monitor)
        if res is None or not res.decompileCompleted():
            print("ERROR: decompilation failed")
        else:
            print(res.getDecompiledFunction().getC())
        print()

decomp.dispose()
print("=== DONE ===")
