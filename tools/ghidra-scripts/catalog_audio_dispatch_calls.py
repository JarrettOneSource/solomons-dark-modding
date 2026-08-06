# Catalog every native audio dispatch call site with decompiler context.
# Usage:
#   -postScript .../catalog_audio_dispatch_calls.py
# @category: Analysis

from ghidra.app.decompiler import ClangStatement, ClangTokenGroup, DecompInterface
from ghidra.program.model.symbol import RefType


TARGETS = (
    ("sound_play_gain", "0x00407B70"),
    ("sound_play_pitch_gain", "0x00407CD0"),
    ("sound_stop", "0x00407F90"),
    ("sound_loop_start", "0x00408320"),
    ("sound_loop_stop", "0x00408350"),
    ("sound_stream_play", "0x0040AF70"),
    ("sound_stream_pause", "0x0040AFB0"),
    ("sound_stream_volume", "0x0040AFD0"),
    ("music_play_immediate", "0x00409A10"),
    ("music_play_crossfade", "0x00409CD0"),
    ("music_transition", "0x00409FA0"),
    ("music_stop", "0x0040A3F0"),
    ("music_set_track_gain", "0x0040A440"),
    ("music_set_song_gain", "0x0040A7F0"),
    ("music_set_track_target", "0x0040A990"),
)


def statement_for_address(group, address):
    if isinstance(group, ClangStatement):
        minimum = group.getMinAddress()
        maximum = group.getMaxAddress()
        if minimum is not None and maximum is not None:
            if minimum.compareTo(address) <= 0 and maximum.compareTo(address) >= 0:
                return " ".join(str(group).split())
    if isinstance(group, ClangTokenGroup):
        for index in range(group.numChildren()):
            found = statement_for_address(group.Child(index), address)
            if found is not None:
                return found
    return None


def instruction_window(listing, call, before=18, after=3):
    instructions = []
    cursor = call
    for _ in range(before):
        cursor = listing.getInstructionBefore(cursor)
        if cursor is None:
            break
        instructions.append(cursor)
        cursor = cursor.getAddress()
    instructions.reverse()
    call_instruction = listing.getInstructionAt(call)
    if call_instruction is None:
        return instructions
    instructions.append(call_instruction)
    cursor = call
    for _ in range(after):
        cursor = listing.getInstructionAfter(cursor)
        if cursor is None:
            break
        instructions.append(cursor)
        cursor = cursor.getAddress()
    return instructions


listing = currentProgram.getListing()
references = currentProgram.getReferenceManager()
decompiler = DecompInterface()
decompiler.openProgram(currentProgram)

rows = []
for api_name, target_text in TARGETS:
    target = toAddr(target_text)
    iterator = references.getReferencesTo(target)
    while iterator.hasNext():
        reference = iterator.next()
        if not reference.getReferenceType().isCall():
            continue
        call = reference.getFromAddress()
        caller = getFunctionContaining(call)
        if caller is None:
            print("ERROR\t%s\t%s\tno containing function" % (api_name, call))
            raise SystemExit(1)
        rows.append((call, api_name, target, caller))

rows.sort(key=lambda row: row[0].getOffset())
print("AUDIO_DISPATCH_TARGET_COUNT\t%d" % len(TARGETS))
print("AUDIO_DISPATCH_CALL_COUNT\t%d" % len(rows))

decompiled = {}
for call, api_name, target, caller in rows:
    entry = caller.getEntryPoint()
    if entry not in decompiled:
        result = decompiler.decompileFunction(caller, 60, monitor)
        if not result.decompileCompleted():
            print(
                "ERROR\t%s\t%s\tdecompile failed: %s" %
                (api_name, entry, result.getErrorMessage())
            )
            raise SystemExit(1)
        decompiled[entry] = result.getCCodeMarkup()
    statement = statement_for_address(decompiled[entry], call)
    if statement is None:
        statement = "UNRESOLVED_DECOMPILER_STATEMENT"

    print(
        "AUDIO_CALL\t%s\t%s\t%s\t%s\t%s" %
        (call, api_name, target, entry, caller.getName())
    )
    print("AUDIO_C\t%s" % statement)
    for instruction in instruction_window(listing, call):
        marker = "CALL" if instruction.getAddress() == call else "CTX"
        print(
            "AUDIO_%s\t%s\t%s" %
            (marker, instruction.getAddress(), str(instruction))
        )
    print("AUDIO_END\t%s" % call)

decompiler.dispose()
