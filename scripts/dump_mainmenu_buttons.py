#!/usr/bin/env python3
import argparse
import ctypes
import os
import struct
import sys


PROCESS_VM_READ = 0x0010
PROCESS_QUERY_INFORMATION = 0x0400


def read_memory(handle: int, address: int, size: int) -> bytes:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    buffer = ctypes.create_string_buffer(size)
    bytes_read = ctypes.c_size_t()
    if not kernel32.ReadProcessMemory(
        handle,
        ctypes.c_void_p(address),
        buffer,
        size,
        ctypes.byref(bytes_read),
    ):
        raise OSError(ctypes.get_last_error(), f"ReadProcessMemory failed at 0x{address:X}")
    if bytes_read.value != size:
        raise OSError(0, f"Short read at 0x{address:X}: expected {size}, got {bytes_read.value}")
    return buffer.raw


def main() -> int:
    if os.name != "nt":
        print("dump_mainmenu_buttons.py must be run with Windows Python.", file=sys.stderr)
        return 2

    parser = argparse.ArgumentParser(description="Dump live Solomon Dark MainMenu button rectangles.")
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--base", required=True, help="MainMenu object address, e.g. 0x2EE5470")
    parser.add_argument("--count", type=int, default=4)
    args = parser.parse_args()

    base = int(args.base, 0)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_INFORMATION, False, args.pid)
    if not handle:
        raise OSError(ctypes.get_last_error(), "OpenProcess failed")

    try:
        mode = struct.unpack("<I", read_memory(handle, base + 0x3FC, 4))[0]
        print(f"mode={mode}")
        for index in range(args.count):
            rect_address = base + 0x78 + index * 0xB4 + 0x14
            left, top, width, height = struct.unpack("<4f", read_memory(handle, rect_address, 16))
            print(
                f"button[{index}] addr=0x{rect_address:X} "
                f"left={left:.3f} top={top:.3f} width={width:.3f} height={height:.3f}"
            )
    finally:
        kernel32.CloseHandle(handle)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
