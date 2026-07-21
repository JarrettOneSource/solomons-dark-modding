# Recover the compiled MyApp sound registry in native load order.
# Usage:
#   -postScript .../catalog_audio_registry.py [builder_address]
# @category: Analysis


def read_ascii(address, maximum=260):
    memory = currentProgram.getMemory()
    if not memory.contains(address):
        return None
    output = []
    cursor = address
    for _ in range(maximum):
        if not memory.contains(cursor):
            return None
        try:
            value = memory.getByte(cursor) & 0xff
        except:
            return None
        if value == 0:
            break
        if value < 0x20 or value > 0x7e:
            return None
        output.append(chr(value))
        cursor = cursor.add(1)
    return "".join(output) if output else None


arguments = getScriptArgs()
builder_address = arguments[0] if arguments else "0x004EE010"
builder = getFunctionContaining(toAddr(builder_address))
if builder is None:
    print("ERROR: no function contains %s" % builder_address)
    raise SystemExit(1)

listing = currentProgram.getListing()
instructions = []
iterator = listing.getInstructions(builder.getBody(), True)
while iterator.hasNext():
    instructions.append(iterator.next())

rows = []
for index, instruction in enumerate(instructions):
    path = None
    data_address = None
    for reference in instruction.getReferencesFrom():
        candidate = read_ascii(reference.getToAddress())
        if candidate is not None and candidate.lower().startswith("sounds\\"):
            path = candidate
            data_address = reference.getToAddress()
            break
    if path is None:
        continue

    destination = None
    load_call = None
    loader = None
    for following in instructions[index + 1:index + 24]:
        text = str(following)
        if text.startswith(("LEA EDI,", "LEA ECX,")) and "[ESI" in text:
            destination = text.split(",", 1)[1].strip()
        if text in (
            "CALL 0x004076d0",
            "CALL 0x00408220",
            "CALL 0x0040acf0",
        ):
            load_call = following.getAddress()
            loader = text.split(" ", 1)[1]
            break
    if load_call is None:
        print(
            "ERROR: no Sound load after path reference %s at %s" %
            (path, instruction.getAddress())
        )
        raise SystemExit(1)
    if destination is None:
        print(
            "ERROR: no ESI-relative destination before load %s at %s" %
            (path, load_call)
        )
        raise SystemExit(1)

    rows.append(
        (
            len(rows),
            instruction.getAddress(),
            data_address,
            load_call,
            loader,
            destination,
            path,
        )
    )

print("AUDIO_REGISTRY_BUILDER\t%s" % builder.getEntryPoint())
for row in rows:
    print(
        "AUDIO_REGISTRY\t%d\t%s\t%s\t%s\t%s\t%s\t%s" % row
    )
print("AUDIO_REGISTRY_COUNT\t%d" % len(rows))

if len(rows) != 233:
    print("ERROR: expected 233 compiled sound paths, recovered %d" % len(rows))
    raise SystemExit(1)
