"""Dump the bytes at given VA as both hex and interpreted as float/int.

Usage:
    -postScript dump_floats_at.py 0x007847b0 0x00786410 ...
"""
import struct


def parse_args():
    args = [a.strip() for a in getScriptArgs() if a.strip()]
    if not args:
        print("ERROR: expected addresses")
        raise SystemExit(1)
    return args


targets = parse_args()
mem = currentProgram.getMemory()

for t in targets:
    addr = toAddr(t)
    try:
        raw = bytearray(4)
        for i in range(4):
            raw[i] = mem.getByte(addr.add(i)) & 0xFF
        as_f = struct.unpack("<f", bytes(raw))[0]
        as_u = struct.unpack("<I", bytes(raw))[0]
        print("%s  bytes=%02X%02X%02X%02X  float=%.6g  uint=0x%08X  int=%d"
              % (t, raw[0], raw[1], raw[2], raw[3], as_f, as_u, as_u))
        # Also try as double (8 bytes)
        raw8 = bytearray(8)
        for i in range(8):
            raw8[i] = mem.getByte(addr.add(i)) & 0xFF
        as_d = struct.unpack("<d", bytes(raw8))[0]
        print("            double=%.9g" % as_d)
    except Exception as e:
        print("%s  ERROR %s" % (t, e))

print("=== DONE ===")
