# Resolve generated SpriteBundle builders to their concrete singleton types.
#
# Usage:
#   -postScript trace_bundle_registry.py \
#       "BadGuys=0x004e0dd0;Inventory=0x004eb0f0"
#
# For each builder this reports the one-entry derived vtable, constructor(s),
# singleton global written by the constructor, direct builder callers, and all
# functions that reference that singleton global.
# @category: Analysis

import re

from ghidra.app.decompiler import DecompInterface


def parse_args():
    values = []
    for argument in getScriptArgs():
        for value in argument.split(";"):
            value = value.strip()
            if value:
                values.append(value)
    entries = []
    index = 0
    while index < len(values):
        value = values[index]
        if "=" in value:
            name, address = value.split("=", 1)
            index += 1
        elif index + 1 < len(values):
            name, address = value, values[index + 1]
            index += 2
        else:
            print("ERROR: expected Name=address or alternating Name address")
            raise SystemExit(1)
        entries.append((name.strip(), toAddr(address.strip())))
    if not entries:
        print("ERROR: expected at least one Name=address entry")
        raise SystemExit(1)
    return entries


def function_for_reference(fm, ref):
    return fm.getFunctionContaining(ref.getFromAddress())


def sorted_functions(functions):
    return sorted(functions.values(), key=lambda fn: str(fn.getEntryPoint()))


entries = parse_args()
program = currentProgram
fm = program.getFunctionManager()
mem = program.getMemory()
decomp = DecompInterface()
decomp.openProgram(program)

singleton_pattern = re.compile(
    r"_?DAT_([0-9a-fA-F]{8})\s*=\s*param_1(?:\s*\+\s*[^;]+)?\s*;"
)

print("=== SPRITE BUNDLE REGISTRY ===")
for name, builder_addr in entries:
    builder = fm.getFunctionAt(builder_addr) or fm.getFunctionContaining(builder_addr)
    print("ATLAS %s" % name)
    print("  BUILDER %s %s" % (
        builder_addr,
        builder.getName() if builder is not None else "[no function]",
    ))

    vtable_candidates = []
    direct_callers = {}
    for ref in getReferencesTo(builder_addr):
        source = ref.getFromAddress()
        source_function = function_for_reference(fm, ref)
        if source_function is not None:
            direct_callers[str(source_function.getEntryPoint())] = source_function
            continue
        try:
            if (source.isMemoryAddress() and
                    (mem.getInt(source) & 0xffffffff) == builder_addr.getOffset()):
                vtable_candidates.append(source)
        except:
            pass

    for caller in sorted_functions(direct_callers):
        print("  DIRECT_CALLER %s %s" % (caller.getEntryPoint(), caller.getName()))

    if not vtable_candidates:
        print("  ERROR no vtable candidate")
        continue

    for vtable_addr in sorted(vtable_candidates, key=str):
        symbol = getSymbolAt(vtable_addr)
        symbol_name = symbol.getName(True) if symbol is not None else "[unnamed]"
        print("  VTABLE %s %s" % (vtable_addr, symbol_name))

        constructors = {}
        for ref in getReferencesTo(vtable_addr):
            constructor = function_for_reference(fm, ref)
            if constructor is not None:
                constructors[str(constructor.getEntryPoint())] = constructor

        for constructor in sorted_functions(constructors):
            print("  CONSTRUCTOR %s %s" % (
                constructor.getEntryPoint(), constructor.getName()))
            result = decomp.decompileFunction(constructor, 240, monitor)
            if result is None or not result.decompileCompleted():
                print("  ERROR constructor decompilation failed")
                continue
            source = result.getDecompiledFunction().getC()
            singleton_matches = singleton_pattern.findall(source)
            if not singleton_matches:
                print("  ERROR no singleton assignment recovered")
                continue

            for singleton_text in sorted(set(singleton_matches)):
                singleton_addr = toAddr(singleton_text)
                print("  SINGLETON %s" % singleton_addr)
                consumers = {}
                for singleton_ref in getReferencesTo(singleton_addr):
                    consumer = function_for_reference(fm, singleton_ref)
                    if consumer is not None:
                        consumers[str(consumer.getEntryPoint())] = consumer
                for consumer in sorted_functions(consumers):
                    print("    CONSUMER %s %s" % (
                        consumer.getEntryPoint(), consumer.getName()))
    print()

decomp.dispose()
print("=== DONE ===")
