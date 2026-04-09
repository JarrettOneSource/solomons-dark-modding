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


def read_i32(kernel32, handle, address: int):
    data = read_bytes(kernel32, handle, address, 4)
    if data is None or len(data) != 4:
        return None
    return int.from_bytes(data, "little", signed=True)


def read_f32(kernel32, handle, address: int):
    data = read_bytes(kernel32, handle, address, 4)
    if data is None or len(data) != 4:
        return None
    return c.c_float.from_buffer_copy(data).value


def read_cstr(kernel32, handle, address: int, limit: int = 96):
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


def candidate_pointer_strings(kernel32, handle, base: int, max_offset: int):
    candidates = []
    for offset in range(0, max_offset, 4):
        pointer = read_u32(kernel32, handle, base + offset)
        if pointer is None or pointer < 0x10000:
            continue
        string_value = read_cstr(kernel32, handle, pointer)
        if string_value and any(ch.isalpha() for ch in string_value):
            candidates.append((offset, pointer, string_value))
    return candidates


def dump_object(kernel32, handle, base: int, settings_address: int, prefix: str):
    vtable = read_u32(kernel32, handle, base)
    rect = [read_f32(kernel32, handle, base + offset) for offset in (0x14, 0x18, 0x1C, 0x20)]
    label_enabled = read_bytes(kernel32, handle, base + 0xDD, 1)
    label_enabled = label_enabled[0] if label_enabled else None
    label_pointer = read_u32(kernel32, handle, base + 0xCC)
    label = read_cstr(kernel32, handle, label_pointer) if label_pointer else None
    child_count = read_i32(kernel32, handle, base + 0x84)
    child_entries = read_u32(kernel32, handle, base + 0x90)
    print(
        f"{prefix}obj=0x{base:08X} rel=0x{base - settings_address:08X} "
        f"vtable=0x{(vtable or 0):08X} rect={rect} "
        f"labelEnabled={label_enabled} labelPtr=0x{(label_pointer or 0):08X} label={label!r} "
        f"childCount={child_count} childEntries=0x{(child_entries or 0):08X}"
    )
    return child_count, child_entries


def main():
    parser = argparse.ArgumentParser(description="Dump owned settings controls from a live Solomon Dark process.")
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--settings", type=lambda value: int(value, 0), required=True)
    parser.add_argument("--max-controls", type=int, default=16)
    parser.add_argument("--scan-bytes", type=lambda value: int(value, 0), default=0x180)
    args = parser.parse_args()

    kernel32, handle = open_process(args.pid)
    try:
        count = read_i32(kernel32, handle, args.settings + 0x84)
        entries = read_u32(kernel32, handle, args.settings + 0x90)
        print(f"settings=0x{args.settings:08X} count={count} entries=0x{(entries or 0):08X}")
        dump_object(kernel32, handle, args.settings, args.settings, "[root] ")
        if not count or not entries:
            return

        for index in range(min(count, args.max_controls)):
            child = read_u32(kernel32, handle, entries + index * 4)
            if not child:
                continue

            child_count, child_entries = dump_object(kernel32, handle, child, args.settings, f"[{index}] ")
            for offset, pointer, string_value in candidate_pointer_strings(kernel32, handle, child, args.scan_bytes)[:12]:
                print(f"    cand off=0x{offset:03X} ptr=0x{pointer:08X} str={string_value!r}")
            if child_count and child_entries:
                for nested_index in range(min(child_count, 8)):
                    nested_child = read_u32(kernel32, handle, child_entries + nested_index * 4)
                    if not nested_child:
                        continue
                    dump_object(kernel32, handle, nested_child, args.settings, f"    [{index}.{nested_index}] ")
    finally:
        kernel32.CloseHandle(handle)


if __name__ == "__main__":
    main()
