"""List sprite-record stream loads performed by a bundle build function.

Usage:
    -postScript trace_bundle_sprite_loads.py <builder-address> \
        [record-loader-address] [aux-loader-address]

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
    aux_loader = args[2] if len(args) > 2 else "0x0043ad20"
    return toAddr(args[0]), toAddr(loader), toAddr(aux_loader)


def scalar_hex(text):
    return int(text, 16)


builder_address, loader_address, aux_loader_address = parse_args()
builder = getFunctionAt(builder_address)
if builder is None:
    builder = getFunctionContaining(builder_address)
if builder is None:
    print("ERROR: no function contains %s" % builder_address)
    raise SystemExit(1)

listing = currentProgram.getListing()
instructions = list(listing.getInstructions(builder.getBody(), True))
call_indices = []
aux_call_indices = []
for index, instruction in enumerate(instructions):
    if instruction.getMnemonicString() != "CALL":
        continue
    flows = instruction.getFlows()
    if loader_address in flows:
        call_indices.append(index)
    if aux_loader_address in flows:
        aux_call_indices.append(index)

destination_pattern = re.compile(
    r"^(LEA|MOV) ([A-Z]+),(?:dword ptr )?\[[A-Z]+ \+ (0x[0-9a-f]+)\]$",
    re.IGNORECASE,
)
register_copy_pattern = re.compile(
    r"^MOV ([A-Z]+),([A-Z]+)$",
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
print("AUX_LOADER %s" % aux_loader_address)
print()


def destination_before(call_index):
    target_register = "ECX"
    for previous in reversed(instructions[max(0, call_index - 20) : call_index]):
        text = str(previous)
        match = destination_pattern.match(text)
        if match and match.group(2).upper() == target_register:
            kind = "inline" if match.group(1).upper() == "LEA" else "array"
            return kind, scalar_hex(match.group(3))

        match = register_copy_pattern.match(text)
        if match and match.group(1).upper() == target_register:
            target_register = match.group(2).upper()
    return "unknown", None

for call_index in call_indices:
    call = instructions[call_index]
    destination_kind, destination_offset = destination_before(call_index)

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
for group_index, call_index in enumerate(aux_call_indices):
    call = instructions[call_index]
    destination_kind, destination_offset = destination_before(call_index)
    offset_text = "?" if destination_offset is None else "0x%04X" % destination_offset
    print(
        "AUX_GROUP call=%s destination=%s+%s group=%d"
        % (call.getAddress(), destination_kind, offset_text, group_index)
    )
print("TOTAL_AUX_GROUPS %d" % len(aux_call_indices))
print("=== DONE ===")
