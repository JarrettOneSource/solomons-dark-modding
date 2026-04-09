#!/usr/bin/env python3
import argparse
import ctypes
from ctypes import wintypes
import sys


PROCESS_VM_READ = 0x0010
PROCESS_QUERY_INFORMATION = 0x0400


kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

OpenProcess = kernel32.OpenProcess
OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
OpenProcess.restype = wintypes.HANDLE

ReadProcessMemory = kernel32.ReadProcessMemory
ReadProcessMemory.argtypes = [
    wintypes.HANDLE,
    wintypes.LPCVOID,
    wintypes.LPVOID,
    ctypes.c_size_t,
    ctypes.POINTER(ctypes.c_size_t),
]
ReadProcessMemory.restype = wintypes.BOOL

CloseHandle = kernel32.CloseHandle
CloseHandle.argtypes = [wintypes.HANDLE]
CloseHandle.restype = wintypes.BOOL


def parse_int(value: str) -> int:
    return int(value, 0)


def read_memory(process_handle: int, address: int, size: int) -> bytes:
    buffer = (ctypes.c_ubyte * size)()
    bytes_read = ctypes.c_size_t()
    if not ReadProcessMemory(
        process_handle,
        ctypes.c_void_p(address),
        buffer,
        size,
        ctypes.byref(bytes_read),
    ):
        raise OSError(ctypes.get_last_error(), f"ReadProcessMemory failed at 0x{address:08X}")
    return bytes(buffer[: bytes_read.value])


def format_ascii(data: bytes) -> str:
    chars = []
    for byte in data:
        if 32 <= byte <= 126:
            chars.append(chr(byte))
        else:
            chars.append(".")
    return "".join(chars)


def main() -> int:
    parser = argparse.ArgumentParser(description="Dump live process memory for Solomon Dark RE work.")
    parser.add_argument("--pid", required=True, type=parse_int, help="Target process id.")
    parser.add_argument(
        "--address",
        required=True,
        action="append",
        type=parse_int,
        help="Address to dump. Can be repeated.",
    )
    parser.add_argument("--size", type=parse_int, default=0x100, help="Byte count to dump per address.")
    parser.add_argument("--width", type=parse_int, default=16, help="Bytes per output row.")
    args = parser.parse_args()

    access = PROCESS_VM_READ | PROCESS_QUERY_INFORMATION
    process_handle = OpenProcess(access, False, args.pid)
    if not process_handle:
        print(f"Unable to open process {args.pid}. Win32 error={ctypes.get_last_error()}", file=sys.stderr)
        return 1

    try:
        for address in args.address:
            try:
                data = read_memory(process_handle, address, args.size)
            except OSError as error:
                print(str(error), file=sys.stderr)
                return 1

            print(f"== 0x{address:08X} ({len(data)} bytes) ==")
            for offset in range(0, len(data), args.width):
                chunk = data[offset : offset + args.width]
                hex_bytes = " ".join(f"{byte:02X}" for byte in chunk)
                dwords = []
                for index in range(0, len(chunk) - (len(chunk) % 4), 4):
                    dword = int.from_bytes(chunk[index : index + 4], "little")
                    dwords.append(f"{dword:08X}")
                dword_text = " ".join(dwords)
                ascii_text = format_ascii(chunk)
                print(f"0x{address + offset:08X}: {hex_bytes:<47} | {dword_text:<35} | {ascii_text}")
            print()
    finally:
        CloseHandle(process_handle)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
