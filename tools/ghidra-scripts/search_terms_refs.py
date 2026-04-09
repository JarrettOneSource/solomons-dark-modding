# Search symbols and ASCII strings for terms, but only print symbol/string hits and
# referencing function addresses. This is much faster than full decompilation.
# Usage:
#   -postScript .../search_terms_refs.py term1 term2 term3
#   -postScript .../search_terms_refs.py "term1;term2;term3"
# @category: Analysis


def parse_args():
    args = getScriptArgs()
    if len(args) < 1:
        print("ERROR: expected one or more search terms")
        raise SystemExit(1)

    terms = []
    for raw in args:
        if ";" in raw:
            for term in raw.split(";"):
                term = term.strip()
                if term:
                    terms.append(term)
        else:
            raw = raw.strip()
            if raw:
                terms.append(raw)
    return terms


def search_ascii(mem, text):
    hits = []
    search_bytes = text.encode("ascii")
    addr = mem.getMinAddress()
    while addr is not None:
        addr = mem.findBytes(addr, search_bytes, None, True, monitor)
        if addr is None:
            break
        hits.append(addr)
        addr = addr.add(1)
    return hits


terms = parse_args()
program = currentProgram
fm = program.getFunctionManager()
sym_table = program.getSymbolTable()
mem = program.getMemory()

print("=== SEARCH TERMS ===")
for term in terms:
    print("  " + term)
print()

for term in terms:
    print("=== TERM: %s ===" % term)
    funcs = {}
    seen_symbol_lines = set()

    sym_iter = sym_table.getAllSymbols(True)
    while sym_iter.hasNext():
        sym = sym_iter.next()
        name = sym.getName()
        if term.lower() not in name.lower():
            continue

        line = "SYMBOL %s @ %s type=%s" % (name, sym.getAddress(), sym.getSymbolType())
        if line not in seen_symbol_lines:
            print(line)
            seen_symbol_lines.add(line)

        func = fm.getFunctionContaining(sym.getAddress())
        if func is not None:
            funcs[str(func.getEntryPoint())] = func

        refs = getReferencesTo(sym.getAddress())
        for ref in refs:
            ref_addr = ref.getFromAddress()
            ref_func = fm.getFunctionContaining(ref_addr)
            if ref_func is not None:
                funcs[str(ref_func.getEntryPoint())] = ref_func
                print("  REF from %s in %s @ %s" %
                      (ref_addr, ref_func.getName(), ref_func.getEntryPoint()))

    ascii_hits = search_ascii(mem, term)
    for hit in ascii_hits[:100]:
        print("STRING %r @ %s" % (term, hit))
        refs = getReferencesTo(hit)
        for ref in refs:
            ref_addr = ref.getFromAddress()
            ref_func = fm.getFunctionContaining(ref_addr)
            if ref_func is not None:
                funcs[str(ref_func.getEntryPoint())] = ref_func
                print("  STRREF from %s in %s @ %s" %
                      (ref_addr, ref_func.getName(), ref_func.getEntryPoint()))

    func_list = list(funcs.values())
    func_list.sort(key=lambda f: str(f.getEntryPoint()))
    print("FUNCTION_COUNT %d" % len(func_list))
    for func in func_list:
        print("FUNCTION %s @ %s :: %s" %
              (func.getName(), func.getEntryPoint(), func.getSignature()))
    print()

print("=== DONE ===")
