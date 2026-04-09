#!/usr/bin/env python3
import argparse
import ctypes as c
from ctypes import wintypes as w


PROCESS_VM_READ = 0x0010
PROCESS_QUERY_INFORMATION = 0x0400


def open_process(pid: int):
    kernel32 = c.WinDLL("kernel32", use_last_error=True)
    open_process_fn = kernel32.OpenProcess
    open_process_fn.argtypes = [w.DWORD, w.BOOL, w.DWORD]
    open_process_fn.restype = w.HANDLE
    handle = open_process_fn(PROCESS_VM_READ | PROCESS_QUERY_INFORMATION, False, pid)
    if not handle:
        raise OSError(c.get_last_error(), f"OpenProcess failed for pid {pid}")
    return kernel32, handle


def read_bytes(kernel32, handle, address: int, size: int):
    read_process_memory = kernel32.ReadProcessMemory
    read_process_memory.argtypes = [w.HANDLE, w.LPCVOID, w.LPVOID, c.c_size_t, c.POINTER(c.c_size_t)]
    read_process_memory.restype = w.BOOL
    buffer = (c.c_ubyte * size)()
    bytes_read = c.c_size_t()
    if not read_process_memory(handle, c.c_void_p(address), buffer, size, c.byref(bytes_read)):
        return None
    return bytes(buffer[: bytes_read.value])


def read_u32(kernel32, handle, address: int):
    data = read_bytes(kernel32, handle, address, 4)
    if data is None or len(data) != 4:
        return None
    return int.from_bytes(data, "little", signed=False)


def read_f32(kernel32, handle, address: int):
    data = read_bytes(kernel32, handle, address, 4)
    if data is None or len(data) != 4:
        return None
    return c.c_float.from_buffer_copy(data).value


def read_cstr(kernel32, handle, address: int, limit: int = 128):
    data = read_bytes(kernel32, handle, address, limit)
    if not data:
        return None

    out = bytearray()
    for value in data:
        if value == 0:
            break
        if value < 32 or value > 126:
            return None
        out.append(value)

    if not out:
        return None
    return out.decode("ascii", errors="ignore")


def is_plausible_rect(left: float, top: float, width: float, height: float) -> bool:
    if left is None or top is None or width is None or height is None:
        return False
    if width <= 0.0 or height <= 0.0:
        return False
    if width > 4000.0 or height > 4000.0:
        return False
    if left < -4096.0 or top < -4096.0:
        return False
    if left + width > 8192.0 or top + height > 8192.0:
        return False
    return True


def main():
    parser = argparse.ArgumentParser(description="Scan an object region for embedded UI-like controls.")
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--base", type=lambda value: int(value, 0), required=True)
    parser.add_argument("--size", type=lambda value: int(value, 0), required=True)
    parser.add_argument("--step", type=lambda value: int(value, 0), default=4)
    parser.add_argument("--left-offset", type=lambda value: int(value, 0), default=0x14)
    parser.add_argument("--top-offset", type=lambda value: int(value, 0), default=0x18)
    parser.add_argument("--width-offset", type=lambda value: int(value, 0), default=0x1C)
    parser.add_argument("--height-offset", type=lambda value: int(value, 0), default=0x20)
    parser.add_argument("--label-pointer-offset", type=lambda value: int(value, 0), default=0xCC)
    parser.add_argument("--must-contain", default="")
    parser.add_argument("--max-results", type=int, default=128)
    parser.add_argument(
        "--deref-pointers",
        action="store_true",
        help="Treat each aligned field in the region as a potential object pointer and scan the pointed-to object.",
    )
    args = parser.parse_args()

    kernel32, handle = open_process(args.pid)
    try:
        hits = 0
        needle = args.must_contain.casefold()
        seen_addresses = set()
        for offset in range(0, args.size, args.step):
            address = args.base + offset
            if args.deref_pointers:
                pointer_value = read_u32(kernel32, handle, address)
                if pointer_value is None or pointer_value < 0x10000:
                    continue
                address = pointer_value
            if address in seen_addresses:
                continue
            seen_addresses.add(address)

            vtable = read_u32(kernel32, handle, address)
            if vtable is None or vtable < 0x01000000 or vtable > 0x02000000:
                continue

            left = read_f32(kernel32, handle, address + args.left_offset)
            top = read_f32(kernel32, handle, address + args.top_offset)
            width = read_f32(kernel32, handle, address + args.width_offset)
            height = read_f32(kernel32, handle, address + args.height_offset)
            if not is_plausible_rect(left, top, width, height):
                continue

            label_pointer = read_u32(kernel32, handle, address + args.label_pointer_offset)
            label = read_cstr(kernel32, handle, label_pointer) if label_pointer else None
            if needle and (label is None or needle not in label.casefold()):
                continue

            print(
                f"offset=0x{offset:04X} obj=0x{address:08X} vtable=0x{vtable:08X} "
                f"rect=({left:.3f},{top:.3f},{width:.3f},{height:.3f}) "
                f"labelPtr=0x{(label_pointer or 0):08X} label={label!r}"
            )
            hits += 1
            if hits >= args.max_results:
                break
    finally:
        kernel32.CloseHandle(handle)


if __name__ == "__main__":
    main()
