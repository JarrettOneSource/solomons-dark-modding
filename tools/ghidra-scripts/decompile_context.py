# Print only matching source lines and nearby context from selected decompiles.
# Usage:
#   -postScript .../decompile_context.py 0x004FECB0 --match 0xf28 --context 4
#   -postScript .../decompile_context.py 0x004FECB0 0x0067DF80 --match 0xf28 0xf2c
# Matches are case-insensitive literal substrings. Multiple matches are ORed.
# @category: Analysis

from ghidra.app.decompiler import DecompInterface


def flatten_args():
    values = []
    for raw in getScriptArgs():
        for value in raw.split(";"):
            value = value.strip()
            if value:
                values.append(value)
    return values


def parse_args():
    raw = flatten_args()
    targets = []
    matches = []
    context = 4
    mode = "targets"
    index = 0
    while index < len(raw):
        value = raw[index]
        if value == "--match":
            mode = "matches"
            index += 1
            continue
        if value == "--context":
            if index + 1 >= len(raw):
                print("ERROR: --context requires a line count")
                raise SystemExit(1)
            context = int(raw[index + 1])
            index += 2
            continue
        if mode == "targets":
            targets.append(value)
        else:
            matches.append(value.lower())
        index += 1

    if not targets or not matches:
        print("ERROR: expected targets followed by --match and one or more substrings")
        raise SystemExit(1)
    if context < 0 or context > 100:
        print("ERROR: context must be in the range 0..100")
        raise SystemExit(1)
    return targets, matches, context


def resolve_target(text):
    if text.startswith("0x") or text.startswith("0X"):
        address = toAddr(text)
        function = getFunctionAt(address)
        if function is None:
            function = getFunctionContaining(address)
        return function

    functions = currentProgram.getFunctionManager().getFunctions(True)
    while functions.hasNext():
        function = functions.next()
        if function.getName() == text:
            return function
    return None


targets, matches, context = parse_args()
decompiler = DecompInterface()
decompiler.openProgram(currentProgram)

print("=== MATCHES ===")
for match in matches:
    print("  " + match)
print("CONTEXT %d" % context)
print()

for target in targets:
    function = resolve_target(target)
    print("=== TARGET: %s ===" % target)
    if function is None:
        print("ERROR: could not resolve target")
        print()
        continue

    print("FUNCTION %s @ %s" % (function.getName(), function.getEntryPoint()))
    result = decompiler.decompileFunction(function, 180, monitor)
    if result is None or not result.decompileCompleted():
        print("ERROR: decompilation failed")
        print()
        continue

    lines = result.getDecompiledFunction().getC().splitlines()
    matched_lines = []
    for line_index, line in enumerate(lines):
        lower = line.lower()
        if any(match in lower for match in matches):
            matched_lines.append(line_index)

    ranges = []
    for line_index in matched_lines:
        start = max(0, line_index - context)
        end = min(len(lines), line_index + context + 1)
        if ranges and start <= ranges[-1][1]:
            ranges[-1] = (ranges[-1][0], max(ranges[-1][1], end))
        else:
            ranges.append((start, end))

    print("MATCH_COUNT %d" % len(matched_lines))
    for range_index, (start, end) in enumerate(ranges):
        if range_index:
            print("  ...")
        for line_index in range(start, end):
            marker = ">" if line_index in matched_lines else " "
            print("%s %5d | %s" % (marker, line_index + 1, lines[line_index]))
    print()

decompiler.dispose()
print("=== DONE ===")
