# Decompile every function that references a SpriteBundle singleton and print
# the exact source lines that use it.
#
# Usage:
#   -postScript trace_bundle_field_consumers.py \
#       "Skills=0x008199cc;Inventory=0x008199b0"
#
# The PowerShell headless wrapper may split `Name=address` at `=`, so the
# parser also accepts alternating `Name address` arguments.
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


def function_for_reference(function_manager, reference):
    return function_manager.getFunctionContaining(reference.getFromAddress())


def sorted_functions(functions):
    return sorted(functions.values(), key=lambda fn: str(fn.getEntryPoint()))


entries = parse_args()
program = currentProgram
function_manager = program.getFunctionManager()
decompiler = DecompInterface()
decompiler.openProgram(program)

print("=== SPRITE BUNDLE FIELD CONSUMERS ===")
for name, singleton_address in entries:
    singleton_token = "DAT_%08x" % singleton_address.getOffset()
    singleton_pattern = re.compile(r"_?%s\b" % singleton_token, re.IGNORECASE)

    consumers = {}
    reference_count = 0
    for reference in getReferencesTo(singleton_address):
        reference_count += 1
        consumer = function_for_reference(function_manager, reference)
        if consumer is not None:
            consumers[str(consumer.getEntryPoint())] = consumer

    print("ATLAS %s" % name)
    print("  SINGLETON %s" % singleton_address)
    print("  REFERENCE_COUNT %d" % reference_count)
    print("  FUNCTION_COUNT %d" % len(consumers))

    for consumer in sorted_functions(consumers):
        result = decompiler.decompileFunction(consumer, 240, monitor)
        if result is None or not result.decompileCompleted():
            print("  FUNCTION %s %s ERROR decompilation failed" % (
                consumer.getEntryPoint(), consumer.getName()))
            continue

        source = result.getDecompiledFunction().getC()
        matched_lines = []
        for line_number, line in enumerate(source.splitlines(), 1):
            if singleton_pattern.search(line):
                matched_lines.append((line_number, line.strip()))

        print("  FUNCTION %s %s MATCHES %d" % (
            consumer.getEntryPoint(), consumer.getName(), len(matched_lines)))
        for line_number, line in matched_lines:
            print("    USE line=%d %s" % (line_number, line))
    print()

decompiler.dispose()
print("=== DONE ===")
