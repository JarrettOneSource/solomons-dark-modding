"""List sprite-record stream loads performed by a bundle build function.

Usage:
    -postScript trace_bundle_sprite_loads.py <builder-address> [record-loader-address]

The Solomon Dark bundle builders read one serialized record per call to the
sprite loader. Inline destinations execute once; dynamic-array destinations
sit in fixed-stride loops. This script reports the serialized record index
assigned to each destination without relying on object-layout slot numbers.
"""

import re


def parse_args():
    args = [arg.strip() for arg in getScriptArgs() if arg.strip()]
    if not args:
        print("ERROR: expected <builder-address> [record-loader-address]")
        raise SystemExit(1)
    loader = args[1] if len(args) > 1 else "0x00413b10"
    return toAddr(args[0]), toAddr(loader)


def scalar_hex(text):
    return int(text, 16)


builder_address, loader_address = parse_args()
builder = getFunctionAt(builder_address)
if builder is None:
    builder = getFunctionContaining(builder_address)
if builder is None:
    print("ERROR: no function contains %s" % builder_address)
    raise SystemExit(1)

listing = currentProgram.getListing()
instructions = list(listing.getInstructions(builder.getBody(), True))
call_indices = []
for index, instruction in enumerate(instructions):
    if instruction.getMnemonicString() != "CALL":
        continue
    flows = instruction.getFlows()
    if loader_address in flows:
        call_indices.append(index)

destination_pattern = re.compile(
    r"^(LEA|MOV) ECX,(?:dword ptr )?\[ESI \+ (0x[0-9a-f]+)\]$",
    re.IGNORECASE,
)
stride_pattern = re.compile(
    r"^ADD ([A-Z]+),(0x[0-9a-f]+)$",
    re.IGNORECASE,
)
limit_pattern = re.compile(
    r"^CMP ([A-Z]+),(0x[0-9a-f]+)$",
    re.IGNORECASE,
)

stream_index = 0
print("=== BUNDLE SPRITE LOADS ===")
print("BUILDER %s @ %s" % (builder.getName(), builder.getEntryPoint()))
print("RECORD_LOADER %s" % loader_address)
print()

for call_index in call_indices:
    call = instructions[call_index]
    destination_kind = "unknown"
    destination_offset = None
    for previous in reversed(instructions[max(0, call_index - 14) : call_index]):
        match = destination_pattern.match(str(previous))
        if match:
            destination_kind = "inline" if match.group(1).upper() == "LEA" else "array"
            destination_offset = scalar_hex(match.group(2))
            break

    multiplicity = 1
    following = instructions[call_index + 1 : call_index + 16]
    for follow_index, instruction in enumerate(following):
        stride_match = stride_pattern.match(str(instruction))
        if not stride_match:
            continue
        register = stride_match.group(1).upper()
        stride = scalar_hex(stride_match.group(2))
        if stride == 0:
            continue
        for later in following[follow_index + 1 :]:
            limit_match = limit_pattern.match(str(later))
            if limit_match and limit_match.group(1).upper() == register:
                limit = scalar_hex(limit_match.group(2))
                if limit % stride == 0:
                    multiplicity = limit // stride
                break
        break

    offset_text = "?" if destination_offset is None else "0x%04X" % destination_offset
    end_index = stream_index + multiplicity - 1
    print(
        "%s call=%s destination=%s+%s count=%d records=%d..%d"
        % (
            destination_kind.upper(),
            call.getAddress(),
            "object" if destination_kind == "inline" else "array",
            offset_text,
            multiplicity,
            stream_index,
            end_index,
        )
    )
    stream_index += multiplicity

print()
print("TOTAL_RECORDS %d" % stream_index)
print("=== DONE ===")
