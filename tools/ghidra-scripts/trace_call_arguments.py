# Print instruction context around every direct reference to a callee.
# Usage:
#   -postScript .../trace_call_arguments.py 0x005B7080 12 4
# @category: Analysis


def parse_count(value, default):
    if value is None:
        return default
    if value.lower().startswith("0x"):
        return int(value, 16)
    return int(value)


args = getScriptArgs()
if len(args) < 1:
    print("ERROR: expected <callee_addr> [instructions_before] [instructions_after]")
    raise SystemExit(1)

callee = toAddr(args[0])
before_count = parse_count(args[1] if len(args) > 1 else None, 12)
after_count = parse_count(args[2] if len(args) > 2 else None, 4)
listing = currentProgram.getListing()
function_manager = currentProgram.getFunctionManager()
reference_manager = currentProgram.getReferenceManager()

references = []
iterator = reference_manager.getReferencesTo(callee)
while iterator.hasNext():
    reference = iterator.next()
    instruction = listing.getInstructionAt(reference.getFromAddress())
    if instruction is not None:
        references.append(reference)

references.sort(key=lambda reference: reference.getFromAddress().getOffset())
print("=== CALLEE: %s ===" % callee)
print("REFERENCE_COUNT %d" % len(references))

for reference in references:
    call_address = reference.getFromAddress()
    caller = function_manager.getFunctionContaining(call_address)
    caller_text = "<none>"
    if caller is not None:
        caller_text = "%s @ %s" % (caller.getName(), caller.getEntryPoint())
    print("=== CALL: %s FROM %s ===" % (call_address, caller_text))

    before = []
    instruction = listing.getInstructionAt(call_address)
    cursor = instruction
    for _ in range(before_count):
        cursor = listing.getInstructionBefore(cursor.getAddress())
        if cursor is None:
            break
        before.append(cursor)
    before.reverse()
    for item in before:
        print("  %s %s" % (item.getAddress(), item))
    print("> %s %s" % (instruction.getAddress(), instruction))

    cursor = instruction
    for _ in range(after_count):
        cursor = listing.getInstructionAfter(cursor.getAddress())
        if cursor is None:
            break
        print("  %s %s" % (cursor.getAddress(), cursor))
    print()

print("=== DONE ===")
