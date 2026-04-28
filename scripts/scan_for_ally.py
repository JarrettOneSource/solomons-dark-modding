#!/usr/bin/env python3
"""Scan SolomonDark.exe process memory for the literal 'ALLY' string."""
import ctypes
from ctypes import wintypes
import sys

PROCESS_VM_READ = 0x0010
PROCESS_QUERY_INFORMATION = 0x0400

MEM_COMMIT = 0x1000
PAGE_NOACCESS = 0x01
PAGE_GUARD = 0x100

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)


class MEMORY_BASIC_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("BaseAddress", ctypes.c_void_p),
        ("AllocationBase", ctypes.c_void_p),
        ("AllocationProtect", wintypes.DWORD),
        ("RegionSize", ctypes.c_size_t),
        ("State", wintypes.DWORD),
        ("Protect", wintypes.DWORD),
        ("Type", wintypes.DWORD),
    ]


VirtualQueryEx = kernel32.VirtualQueryEx
VirtualQueryEx.argtypes = [wintypes.HANDLE, wintypes.LPCVOID,
                           ctypes.POINTER(MEMORY_BASIC_INFORMATION), ctypes.c_size_t]
VirtualQueryEx.restype = ctypes.c_size_t

ReadProcessMemory = kernel32.ReadProcessMemory
ReadProcessMemory.argtypes = [wintypes.HANDLE, wintypes.LPCVOID, wintypes.LPVOID,
                              ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
ReadProcessMemory.restype = wintypes.BOOL

OpenProcess = kernel32.OpenProcess
OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
OpenProcess.restype = wintypes.HANDLE


def main():
    pid = int(sys.argv[1])
    needles = []
    for arg in sys.argv[2:]:
        if arg.startswith("0x"):
            needles.append(bytes.fromhex(arg[2:]))
        else:
            needles.append(arg.encode("ascii"))

    print(f"PID={pid}, scanning for {len(needles)} needle(s):")
    for n in needles:
        print(f"  needle: {n!r} ({n.hex()})")

    h = OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_INFORMATION, False, pid)
    if not h:
        print(f"OpenProcess failed: {ctypes.get_last_error()}")
        return 1

    addr = 0
    end = 0x80000000  # 2 GiB user space (32-bit)
    mbi = MEMORY_BASIC_INFORMATION()
    total_hits = {n.hex(): 0 for n in needles}

    while addr < end:
        ret = VirtualQueryEx(h, ctypes.c_void_p(addr), ctypes.byref(mbi), ctypes.sizeof(mbi))
        if ret == 0:
            addr += 0x1000
            continue

        region_base = mbi.BaseAddress or 0
        region_size = mbi.RegionSize or 0x1000

        if mbi.State == MEM_COMMIT and not (mbi.Protect & PAGE_NOACCESS) and not (mbi.Protect & PAGE_GUARD):
            buf = (ctypes.c_ubyte * region_size)()
            read = ctypes.c_size_t()
            ok = ReadProcessMemory(h, ctypes.c_void_p(region_base), buf, region_size, ctypes.byref(read))
            if ok and read.value > 0:
                data = bytes(buf[:read.value])
                for needle in needles:
                    pos = 0
                    while True:
                        idx = data.find(needle, pos)
                        if idx < 0:
                            break
                        va = region_base + idx
                        # context window
                        c0 = max(0, idx - 16)
                        c1 = min(len(data), idx + len(needle) + 16)
                        ctx = data[c0:c1]
                        ctx_ascii = "".join(chr(b) if 32 <= b <= 126 else "." for b in ctx)
                        print(f"HIT {needle!r} @ 0x{va:08X} (region 0x{region_base:08X} prot=0x{mbi.Protect:X}) ctx={ctx_ascii!r}")
                        total_hits[needle.hex()] += 1
                        pos = idx + 1

        addr = region_base + region_size
        if addr <= region_base:
            addr += 0x1000

    print()
    print("=== TOTALS ===")
    for n_hex, count in total_hits.items():
        print(f"  {n_hex}: {count} hit(s)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
