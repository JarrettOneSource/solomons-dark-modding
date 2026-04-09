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
        print("dump_msgbox.py must be run with Windows Python.", file=sys.stderr)
        return 2

    parser = argparse.ArgumentParser(description="Dump live Solomon Dark MsgBox geometry.")
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--base", required=True, help="MsgBox object address, e.g. 0x2F60CA0")
    args = parser.parse_args()

    base = int(args.base, 0)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = kernel32.OpenProcess(PROCESS_VM_READ | PROCESS_QUERY_INFORMATION, False, args.pid)
    if not handle:
        raise OSError(ctypes.get_last_error(), "OpenProcess failed")

    try:
        panel_left, panel_top, panel_width, panel_height = struct.unpack("<4f", read_memory(handle, base + 0x78, 16))
        button_left, button_top, button_width, button_height = struct.unpack("<4f", read_memory(handle, base + 0xD8, 16))
        print(
            f"panel left={panel_left:.3f} top={panel_top:.3f} "
            f"width={panel_width:.3f} height={panel_height:.3f}"
        )
        print(
            f"primary left={button_left:.3f} top={button_top:.3f} "
            f"width={button_width:.3f} height={button_height:.3f}"
        )
    finally:
        kernel32.CloseHandle(handle)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
