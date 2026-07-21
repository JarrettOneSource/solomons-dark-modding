# Catalog RTTI-named native classes, their vtable slots, and constructor refs.
#
# Usage:
#   -postScript catalog_native_classes.py [name-regex] [max-slot-bytes]
#
# Examples:
#   -postScript catalog_native_classes.py \
#       "^(MagicMissile|Fireball|Anim_|Mod_)" 0xA0
# @category: Analysis

import re


def parse_args():
    args = []
    for argument in getScriptArgs():
        args.extend(value.strip() for value in argument.split(";") if value.strip())
    pattern = args[0] if args else ".*"
    max_slot_bytes = 0xA0
    if len(args) > 1:
        text = args[1]
        max_slot_bytes = int(text, 16) if text.lower().startswith("0x") else int(text)
    return re.compile(pattern, re.IGNORECASE), max_slot_bytes


def read_pointer(memory, address):
    pointer_size = currentProgram.getDefaultPointerSize()
    if pointer_size == 4:
        return memory.getInt(address) & 0xffffffff
    if pointer_size == 8:
        return memory.getLong(address) & 0xffffffffffffffff
    raise ValueError("unsupported pointer size %d" % pointer_size)


name_pattern, max_slot_bytes = parse_args()
symbol_table = currentProgram.getSymbolTable()
function_manager = currentProgram.getFunctionManager()
memory = currentProgram.getMemory()
pointer_size = currentProgram.getDefaultPointerSize()

vtables = []
symbols = symbol_table.getAllSymbols(True)
while symbols.hasNext():
    symbol = symbols.next()
    if symbol.getName() != "vftable":
        continue
    qualified_name = symbol.getName(True)
    class_name = qualified_name[:-len("::vftable")] if qualified_name.endswith("::vftable") else qualified_name
    if name_pattern.search(class_name):
        vtables.append((symbol.getAddress(), class_name))

vtables.sort(key=lambda entry: str(entry[0]))

print("=== NATIVE CLASS CATALOG ===")
print("FILTER %s" % name_pattern.pattern)
print("MAX_SLOT_BYTES 0x%X" % max_slot_bytes)
print("CLASS_COUNT %d" % len(vtables))
print()

for vtable_address, class_name in vtables:
    print("CLASS %s VTABLE %s" % (class_name, vtable_address))

    constructors = {}
    for reference in getReferencesTo(vtable_address):
        function = function_manager.getFunctionContaining(reference.getFromAddress())
        if function is not None:
            constructors[str(function.getEntryPoint())] = function
    for key in sorted(constructors):
        function = constructors[key]
        print("  VTABLE_REF %s %s" % (function.getEntryPoint(), function.getName()))

    slot = 0
    while slot < max_slot_bytes:
        slot_address = vtable_address.add(slot)
        try:
            target_address = toAddr(read_pointer(memory, slot_address))
        except:
            break
        target_block = memory.getBlock(target_address)
        if target_block is None or not target_block.isExecute():
            break
        function = function_manager.getFunctionAt(target_address)
        if function is None:
            function = function_manager.getFunctionContaining(target_address)
        print("  SLOT 0x%02X %s %s" % (
            slot,
            target_address,
            function.getName() if function is not None else "[no function]",
        ))
        slot += pointer_size
    print("  SLOT_BYTES 0x%X" % slot)
    print()

print("=== DONE ===")
