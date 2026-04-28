# -*- coding: utf-8 -*-
# Find all CALL <target> instructions, then walk backward to find what's loaded
# into ECX immediately before. Useful for finding callers of __thiscall fn that
# pass a specific value as 'this'.
# Usage: -postScript find_callsites_with_arg.py <call_target_hex> <expected_this_hex>

import sys


def parse_args():
    args = [a.strip() for a in getScriptArgs() if a.strip()]
    if len(args) < 2:
        print("usage: <call_target_hex> <expected_this_hex>")
        raise SystemExit(1)
    return args


program = currentProgram
listing = program.getListing()
fm = program.getFunctionManager()
ref_mgr = program.getReferenceManager()

call_target_str, expected_this_str = parse_args()
call_target = int(call_target_str, 16)
expected_this = int(expected_this_str, 16)
print("Looking for callers of 0x%x with this=0x%x" % (call_target, expected_this))

call_target_addr = toAddr(call_target)
target_fn = fm.getFunctionAt(call_target_addr)
if target_fn is None:
    print("No function at target")
    raise SystemExit(1)

callers = target_fn.getCallingFunctions(monitor)
print("Total caller functions: %d" % callers.size())

found = []
for caller in callers:
    iter_ = listing.getInstructions(caller.getBody(), True)
    last_ecx_load = None  # tuple (addr, value) of most recent MOV ECX, imm or LEA ECX, [imm]
    while iter_.hasNext():
        ins = iter_.next()
        mnemonic = ins.getMnemonicString()
        if mnemonic in ("MOV", "LEA"):
            # Want first operand to be ECX
            try:
                op0 = ins.getDefaultOperandRepresentation(0)
                op1 = ins.getDefaultOperandRepresentation(1)
            except:
                continue
            if op0 == "ECX":
                # Try to parse the source as an absolute address
                # MOV ECX, 0x81db88 => op1 = "0x81db88"
                # LEA ECX, [0x81db88] => op1 = "[0x81db88]"
                val_str = op1.strip("[] ")
                try:
                    val = int(val_str, 16) if "0x" in val_str.lower() else int(val_str)
                    last_ecx_load = (str(ins.getAddress()), val, str(ins))
                except:
                    last_ecx_load = (str(ins.getAddress()), None, str(ins))  # invalidates
        elif mnemonic == "CALL":
            # Check if this is a call to our target
            try:
                op0 = ins.getDefaultOperandRepresentation(0)
                target_str = op0.strip("[] ")
                target_val = int(target_str, 16)
            except:
                target_val = None
            if target_val == call_target:
                if last_ecx_load is not None and last_ecx_load[1] == expected_this:
                    found.append({
                        "caller_fn": caller.getName(),
                        "caller_entry": str(caller.getEntryPoint()),
                        "ecx_load_at": last_ecx_load[0],
                        "ecx_load_ins": last_ecx_load[2],
                        "call_at": str(ins.getAddress()),
                    })
                # reset after the call (next call needs fresh load)
                last_ecx_load = None

print("\n=== HITS: %d ===" % len(found))
for hit in found:
    print("  call=%s ecx_at=%s ins=%s caller=%s @ %s" %
          (hit["call_at"], hit["ecx_load_at"], hit["ecx_load_ins"],
           hit["caller_fn"], hit["caller_entry"]))

print("=== DONE ===")
