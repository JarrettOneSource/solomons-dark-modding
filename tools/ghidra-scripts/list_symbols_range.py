# List symbols in an address range.
# Usage:
#   -postScript .../list_symbols_range.py 0x1408f4b80 0x1408f4ec0
# @category: Analysis


def parse_args():
    args = [a.strip() for a in getScriptArgs() if a.strip()]
    if len(args) != 2:
        print("ERROR: expected <start_addr> <end_addr>")
        raise SystemExit(1)
    return toAddr(args[0]), toAddr(args[1])


start, end = parse_args()
sym_table = currentProgram.getSymbolTable()

print("=== SYMBOLS %s..%s ===" % (start, end))
syms = []
it = sym_table.getAllSymbols(True)
while it.hasNext():
    sym = it.next()
    addr = sym.getAddress()
    if addr is not None and addr.compareTo(start) >= 0 and addr.compareTo(end) <= 0:
        syms.append(sym)

syms.sort(key=lambda s: str(s.getAddress()))
for sym in syms:
    print("%s %s %s" % (sym.getAddress(), sym.getSymbolType(), sym.getName()))

print("COUNT %d" % len(syms))
print("=== DONE ===")
