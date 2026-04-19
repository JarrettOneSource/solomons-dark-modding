# Find instructions that reference specific addresses in their operand
target_addrs_hex = [a.strip() for a in getScriptArgs() if a.strip()]
if not target_addrs_hex:
    print("usage: <addr1> [addr2 ...]")
    raise SystemExit(1)

targets = {}
for a in target_addrs_hex:
    n = int(a, 16) if a.lower().startswith("0x") else int(a, 16)
    targets[n] = a

program = currentProgram
listing = program.getListing()
hits = {a: [] for a in target_addrs_hex}

inst_iter = listing.getInstructions(True)
while inst_iter.hasNext():
    inst = inst_iter.next()
    mnemonic = inst.getMnemonicString()
    # Check each operand
    for i in range(inst.getNumOperands()):
        rep = inst.getDefaultOperandRepresentation(i)
        for addr_str in target_addrs_hex:
            addr_lower = addr_str.lower().replace("0x", "")
            if ("0x%s" % addr_lower) in rep.lower() or ("0x%s" % addr_str.lower()) in rep.lower():
                hits[addr_str].append((str(inst.getAddress()), mnemonic, rep, str(inst)))
                break

for addr in target_addrs_hex:
    print("=== ADDR %s - %d refs ===" % (addr, len(hits[addr])))
    for hit in hits[addr][:20]:
        print("  %s  %s  %s  %s" % hit)
    print()
print("=== DONE ===")
