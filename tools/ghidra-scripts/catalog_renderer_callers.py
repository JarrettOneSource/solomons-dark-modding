# Catalog direct callers of renderer functions without decompiling them.
#
# Usage:
#   -postScript .../catalog_renderer_callers.py 0x004143D0 0x0041FE50
#   -postScript .../catalog_renderer_callers.py --json C:\\out.json 0x004143D0
#
# Each target reports every containing caller once, the number of direct
# references from that caller, and the exact callsites. Non-function references
# are retained separately so data/vtable membership is not silently lost.
# @category: Analysis

import json


def parse_arguments():
    values = []
    for argument in getScriptArgs():
        values.extend(value.strip() for value in argument.split(";") if value.strip())

    targets = []
    json_path = None
    index = 0
    while index < len(values):
        value = values[index]
        if value == "--json":
            if index + 1 >= len(values):
                print("ERROR: --json requires a path")
                raise SystemExit(1)
            json_path = values[index + 1]
            index += 2
            continue
        targets.append(value)
        index += 1
    if not targets:
        print("ERROR: expected one or more function addresses")
        raise SystemExit(1)
    return targets, json_path


function_manager = currentProgram.getFunctionManager()
targets, json_path = parse_arguments()
catalog_targets = []

for target_text in targets:
    target = toAddr(target_text)
    target_function = function_manager.getFunctionAt(target)
    target_name = target_function.getName() if target_function is not None else "[no function]"
    callers = {}
    orphan_sites = []
    reference_count = 0

    for reference in getReferencesTo(target):
        reference_count += 1
        site = reference.getFromAddress()
        caller = function_manager.getFunctionContaining(site)
        if caller is None:
            orphan_sites.append(site)
            continue
        key = str(caller.getEntryPoint())
        if key not in callers:
            callers[key] = {"function": caller, "sites": []}
        callers[key]["sites"].append(site)

    print("=== TARGET %s %s ===" % (target, target_name))
    print("REFERENCE_COUNT %d" % reference_count)
    print("CALLER_COUNT %d" % len(callers))
    for key in sorted(callers):
        entry = callers[key]
        sites = sorted(entry["sites"], key=lambda address: str(address))
        print("CALLER %s %s count=%d sites=%s" % (
            entry["function"].getEntryPoint(),
            entry["function"].getName(),
            len(sites),
            ",".join(str(site) for site in sites),
        ))
    print("ORPHAN_COUNT %d" % len(orphan_sites))
    for site in sorted(orphan_sites, key=lambda address: str(address)):
        print("ORPHAN %s" % site)
    print()

    catalog_targets.append({
        "address": "0x%s" % str(target).upper(),
        "name": target_name,
        "reference_count": reference_count,
        "callers": [
            {
                "address": "0x%s" % str(callers[key]["function"].getEntryPoint()).upper(),
                "name": callers[key]["function"].getName(),
                "callsites": [
                    "0x%s" % str(site).upper()
                    for site in sorted(callers[key]["sites"], key=lambda address: str(address))
                ],
            }
            for key in sorted(callers)
        ],
        "orphan_sites": [
            "0x%s" % str(site).upper()
            for site in sorted(orphan_sites, key=lambda address: str(address))
        ],
    })

if json_path is not None:
    try:
        executable_sha256 = currentProgram.getExecutableSHA256()
    except:
        executable_sha256 = None
    catalog = {
        "schema": 1,
        "program": currentProgram.getName(),
        "executable_sha256": executable_sha256,
        "image_base": "0x%s" % str(currentProgram.getImageBase()).upper(),
        "targets": catalog_targets,
    }
    rendered = json.dumps(
        catalog,
        indent=2,
        sort_keys=True,
        separators=(",", ": "),
    ).encode("utf-8")
    with open(json_path, "wb") as output:
        output.write(rendered)
        output.write(b"\n")
    print("JSON %s" % json_path)

print("=== DONE ===")
