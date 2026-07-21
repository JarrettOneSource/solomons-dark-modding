# Summarize direct calls and referenced data for one or more functions without
# printing a giant decompilation.
#
# Usage:
#   -postScript .../summarize_function_calls.py 0x006388b0
# @category: Analysis


def resolve_target(text):
    if text.startswith("0x") or text.startswith("0X"):
        address = toAddr(text)
        return getFunctionAt(address) or getFunctionContaining(address)

    functions = currentProgram.getFunctionManager().getFunctions(True)
    while functions.hasNext():
        function = functions.next()
        if function.getName() == text:
            return function
    return None


def format_sites(sites, limit):
    rendered = [str(site) for site in sites[:limit]]
    if len(sites) > limit:
        rendered.append("...+%d" % (len(sites) - limit))
    return ",".join(rendered)


targets = []
for argument in getScriptArgs():
    targets.extend(value.strip() for value in argument.split(";") if value.strip())

if not targets:
    print("ERROR: expected at least one function address or name")
    raise SystemExit(1)

listing = currentProgram.getListing()
function_manager = currentProgram.getFunctionManager()
reference_manager = currentProgram.getReferenceManager()
symbol_table = currentProgram.getSymbolTable()

for target in targets:
    function = resolve_target(target)
    print("=== TARGET: %s ===" % target)
    if function is None:
        print("ERROR: could not resolve target")
        print()
        continue

    print("FUNCTION %s @ %s" % (function.getName(), function.getEntryPoint()))
    calls = {}
    data_refs = {}
    instructions = listing.getInstructions(function.getBody(), True)
    instruction_count = 0

    while instructions.hasNext():
        instruction = instructions.next()
        instruction_count += 1
        address = instruction.getAddress()

        if instruction.getFlowType().isCall():
            flows = instruction.getFlows()
            if flows:
                destination = flows[0]
                called = function_manager.getFunctionAt(destination)
                if called is None:
                    called = function_manager.getFunctionContaining(destination)
                key = str(destination)
                if key not in calls:
                    calls[key] = {
                        "destination": destination,
                        "name": called.getName() if called is not None else "[no function]",
                        "sites": [],
                    }
                calls[key]["sites"].append(address)

        references = reference_manager.getReferencesFrom(address)
        for reference in references:
            destination = reference.getToAddress()
            if not destination.isMemoryAddress() or reference.getReferenceType().isFlow():
                continue
            symbol = symbol_table.getPrimarySymbol(destination)
            if symbol is None:
                continue
            name = symbol.getName(True)
            key = "%s|%s" % (destination, name)
            if key not in data_refs:
                data_refs[key] = {
                    "destination": destination,
                    "name": name,
                    "sites": [],
                }
            data_refs[key]["sites"].append(address)

    print("INSTRUCTION_COUNT %d" % instruction_count)
    print("DIRECT_CALL_TARGETS %d" % len(calls))
    for key in sorted(calls):
        entry = calls[key]
        print("CALL %s %s count=%d sites=%s" % (
            entry["destination"],
            entry["name"],
            len(entry["sites"]),
            format_sites(entry["sites"], 12),
        ))

    print("DATA_REFERENCES %d" % len(data_refs))
    for key in sorted(data_refs):
        entry = data_refs[key]
        print("DATA %s %s count=%d sites=%s" % (
            entry["destination"],
            entry["name"],
            len(entry["sites"]),
            format_sites(entry["sites"], 12),
        ))
    print()

print("=== DONE ===")
