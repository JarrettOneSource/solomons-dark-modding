def parse_addr(text):
    if text.lower().startswith("0x"):
        return toAddr(int(text, 16))
    return toAddr(int(text, 16))


def run():
    args = getScriptArgs()
    if not args:
        print("usage: dump_values.py <addr> [<addr> ...]")
        return
    print("=== VALUES ===")
    for raw in args:
        addr = parse_addr(raw)
        print("%s %.9g" % (addr, getFloat(addr)))
    print("=== DONE ===")


run()
