# Decompile one or more functions by address or exact function name.
# Usage examples:
#   -postScript .../decompile_targets.py 0x140059900 0x1403451f0
#   -postScript .../decompile_targets.py FUN_140059900
# @category: Analysis

from ghidra.app.decompiler import DecompInterface


def get_targets():
    args = [a.strip() for a in getScriptArgs() if a.strip()]
    if not args:
        print("ERROR: expected at least one address or function name")
        raise SystemExit(1)
    return args


def resolve_target(program, text):
    fm = program.getFunctionManager()
    if text.startswith("0x") or text.startswith("0X"):
        addr = toAddr(text)
        func = getFunctionAt(addr)
        if func is None:
            func = getFunctionContaining(addr)
        return func

    funcs = fm.getFunctions(True)
    while funcs.hasNext():
        func = funcs.next()
        if func.getName() == text:
            return func
    return None


program = currentProgram
targets = get_targets()

decomp = DecompInterface()
decomp.openProgram(program)

print("=== TARGETS ===")
for target in targets:
    print("  " + target)
print()

for target in targets:
    func = resolve_target(program, target)
    print("=== TARGET: %s ===" % target)
    if func is None:
        print("ERROR: could not resolve target")
        print()
        continue

    print("FUNCTION %s @ %s" % (func.getName(), func.getEntryPoint()))
    print("SIGNATURE: %s" % func.getSignature())
    res = decomp.decompileFunction(func, 180, monitor)
    if res is None or not res.decompileCompleted():
        print("ERROR: decompilation failed")
    else:
        print(res.getDecompiledFunction().getC())
    print()

decomp.dispose()
print("=== DONE ===")
