# List direct data references, symbols, and printable ASCII targets in functions.
# Usage:
#   -postScript .../dump_function_data_refs.py 0x005722A0 0x00573570
# @category: Analysis


def parse_args():
    targets = []
    for argument in getScriptArgs():
        targets.extend(value.strip() for value in argument.split(";") if value.strip())
    if not targets:
        print("ERROR: expected one or more function addresses or names")
        raise SystemExit(1)
    return targets


def resolve_target(text):
    if text.lower().startswith("0x"):
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


def read_ascii(address, maximum=256):
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
    if len(output) < 2:
        return None
    return "".join(output)


listing = currentProgram.getListing()
symbols = currentProgram.getSymbolTable()

for target in parse_args():
    print("=== TARGET: %s ===" % target)
    function = resolve_target(target)
    if function is None:
        print("ERROR: could not resolve target")
        continue
    print("FUNCTION %s @ %s" % (function.getName(), function.getEntryPoint()))
    seen = set()
    instructions = listing.getInstructions(function.getBody(), True)
    while instructions.hasNext():
        instruction = instructions.next()
        references = instruction.getReferencesFrom()
        for reference in references:
            destination = reference.getToAddress()
            key = (str(instruction.getAddress()), str(destination))
            if key in seen:
                continue
            seen.add(key)
            symbol = symbols.getPrimarySymbol(destination)
            text = read_ascii(destination)
            details = []
            if symbol is not None:
                details.append("symbol=%s" % symbol.getName())
            if text is not None:
                details.append("ascii=%r" % text)
            if not details:
                data = listing.getDataAt(destination)
                if data is not None:
                    details.append("data=%s" % data)
            if details:
                print(
                    "%s -> %s :: %s" %
                    (instruction.getAddress(), destination, " ".join(details))
                )
    print()

print("=== DONE ===")
