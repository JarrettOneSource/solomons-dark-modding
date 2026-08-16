# Catalog native audio dispatch calls made by selected functions.
# Usage:
#   -postScript .../catalog_function_audio_calls.py 0x0054CC50 0x006145D0
# @category: Analysis

AUDIO_TARGETS = {
    toAddr("0x00407B70"): "sound_play_gain",
    toAddr("0x00407CD0"): "sound_play_pitch_gain",
    toAddr("0x00407F90"): "sound_stop",
    toAddr("0x00408320"): "sound_loop_start",
    toAddr("0x00408350"): "sound_loop_stop",
    toAddr("0x0040AF70"): "sound_stream_play",
    toAddr("0x0040AFB0"): "sound_stream_pause",
    toAddr("0x0040AFD0"): "sound_stream_volume",
}


def targets():
    result = []
    for argument in getScriptArgs():
        result.extend(value.strip() for value in argument.split(";") if value.strip())
    if not result:
        print("ERROR: expected one or more function addresses or exact names")
        raise SystemExit(1)
    return result


def resolve(text):
    if text.lower().startswith("0x"):
        address = toAddr(text)
        return getFunctionAt(address) or getFunctionContaining(address)
    functions = currentProgram.getFunctionManager().getFunctions(True)
    while functions.hasNext():
        function = functions.next()
        if function.getName() == text:
            return function
    return None


listing = currentProgram.getListing()

for target in targets():
    function = resolve(target)
    print("=== TARGET: %s ===" % target)
    if function is None:
        print("ERROR: could not resolve target")
        continue
    print("FUNCTION %s @ %s" % (function.getName(), function.getEntryPoint()))
    count = 0
    instructions = listing.getInstructions(function.getBody(), True)
    while instructions.hasNext():
        instruction = instructions.next()
        if not instruction.getFlowType().isCall():
            continue
        flows = instruction.getFlows()
        if not flows or flows[0] not in AUDIO_TARGETS:
            continue
        count += 1
        call_address = instruction.getAddress()
        print(
            "AUDIO_CALL\t%s\t%s" %
            (call_address, AUDIO_TARGETS[flows[0]])
        )
        before = []
        cursor = instruction
        for _ in range(18):
            cursor = listing.getInstructionBefore(cursor.getAddress())
            if cursor is None:
                break
            before.append(cursor)
        before.reverse()
        for context in before:
            print("CTX\t%s\t%s" % (context.getAddress(), str(context)))
        print("CALL\t%s\t%s" % (call_address, str(instruction)))
    print("AUDIO_CALL_COUNT\t%d" % count)

print("=== DONE ===")
