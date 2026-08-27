# Catalog scalar renderer-state displacements only in functions that reference
# the retail renderer singleton. This avoids treating unrelated object fields
# with the same numeric offset as renderer state.
#
# Usage:
#   -postScript .../catalog_renderer_state_accesses.py 0x3f1 0x3f3 0x409
#
# Offsets are relative to the renderer singleton at DAT_00B401A8. The output
# retains exact instructions so reads, writes, and requested values can be
# classified from the durable evidence rather than guessed from an offset hit.
# @category: Analysis

from ghidra.program.model.scalar import Scalar


def parse_offsets():
    offsets = []
    for argument in getScriptArgs():
        for value in argument.split(";"):
            value = value.strip()
            if not value:
                continue
            offsets.append(int(value, 16) if value.lower().startswith("0x") else int(value))
    if not offsets:
        print("ERROR: expected one or more renderer offsets")
        raise SystemExit(1)
    return offsets


offsets = parse_offsets()
offset_set = set(offsets)
listing = currentProgram.getListing()
function_manager = currentProgram.getFunctionManager()
renderer_global = toAddr("0x00B401A8")

print("=== RENDERER GLOBAL %s ===" % renderer_global)
print("=== TARGET OFFSETS %s ===" % ",".join("0x%x" % offset for offset in offsets))

functions = function_manager.getFunctions(True)
result_count = 0
while functions.hasNext():
    function = functions.next()
    instructions = list(listing.getInstructions(function.getBody(), True))
    references_renderer = False
    for instruction in instructions:
        for reference in instruction.getReferencesFrom():
            if reference.getToAddress() == renderer_global:
                references_renderer = True
                break
        if references_renderer:
            break
    if not references_renderer:
        continue

    hits = []
    for instruction in instructions:
        matched = set()
        for operand_index in range(instruction.getNumOperands()):
            for obj in instruction.getOpObjects(operand_index):
                if not isinstance(obj, Scalar):
                    continue
                value = obj.getUnsignedValue()
                if value in offset_set:
                    matched.add(value)
        if matched:
            hits.append((instruction, sorted(matched)))

    if not hits:
        continue
    result_count += 1
    print("FUNCTION %s @ %s HIT_COUNT %d" % (
        function.getName(),
        function.getEntryPoint(),
        len(hits),
    ))
    for instruction, matched in hits:
        print("  %s offsets=%s :: %s" % (
            instruction.getAddress(),
            ",".join("0x%x" % value for value in matched),
            instruction,
        ))

print("FUNCTION_COUNT %d" % result_count)
print("=== DONE ===")
