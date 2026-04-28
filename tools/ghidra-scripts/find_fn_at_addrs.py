# -*- coding: utf-8 -*-
# Resolve a list of addresses to their containing function (entry point + name).
# Usage: -postScript find_fn_at_addrs.py 0x60b236 0x60cb98 0x77287c ...

import sys

args = [a.strip() for a in getScriptArgs() if a.strip()]
fm = currentProgram.getFunctionManager()

for arg in args:
    try:
        addr = toAddr(arg)
    except:
        print("BADARG: %s" % arg)
        continue
    fn = fm.getFunctionContaining(addr)
    if fn is None:
        print("%s -> NO_FN" % arg)
    else:
        print("%s -> %s @ %s (size=%d)" % (
            arg, fn.getName(), fn.getEntryPoint(),
            fn.getBody().getNumAddresses()))
