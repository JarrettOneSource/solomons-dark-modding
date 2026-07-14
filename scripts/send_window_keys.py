#!/usr/bin/env python3
import argparse
import ctypes
import os
import sys
import time
from ctypes import wintypes

from capture_window import activate_window, find_window


user32 = ctypes.WinDLL("user32", use_last_error=True)

KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_SCANCODE = 0x0008
INPUT_KEYBOARD = 1
MAPVK_VK_TO_VSC = 0


KEY_CODES = {
    "enter": 0x0D,
    "escape": 0x1B,
    "space": 0x20,
    "tab": 0x09,
    "up": 0x26,
    "down": 0x28,
    "left": 0x25,
    "right": 0x27,
    "home": 0x24,
    "end": 0x23,
    "pageup": 0x21,
    "pagedown": 0x22,
    "f1": 0x70,
    "f2": 0x71,
    "f3": 0x72,
    "f4": 0x73,
    "f5": 0x74,
    "f6": 0x75,
    "f7": 0x76,
    "f8": 0x77,
    "f9": 0x78,
    "f10": 0x79,
    "f11": 0x7A,
    "f12": 0x7B,
    "a": 0x41, "b": 0x42, "c": 0x43, "d": 0x44, "e": 0x45,
    "f": 0x46, "g": 0x47, "h": 0x48, "i": 0x49, "j": 0x4A,
    "k": 0x4B, "l": 0x4C, "m": 0x4D, "n": 0x4E, "o": 0x4F,
    "p": 0x50, "q": 0x51, "r": 0x52, "s": 0x53, "t": 0x54,
    "u": 0x55, "v": 0x56, "w": 0x57, "x": 0x58, "y": 0x59,
    "z": 0x5A,
}


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", wintypes.WPARAM),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", wintypes.WPARAM),
    ]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class INPUT_UNION(ctypes.Union):
    _fields_ = [
        ("mi", MOUSEINPUT),
        ("ki", KEYBDINPUT),
        ("hi", HARDWAREINPUT),
    ]


class INPUT(ctypes.Structure):
    _anonymous_ = ("data",)
    _fields_ = [("type", wintypes.DWORD), ("data", INPUT_UNION)]


user32.SendInput.argtypes = [
    wintypes.UINT,
    ctypes.POINTER(INPUT),
    ctypes.c_int,
]
user32.SendInput.restype = wintypes.UINT


def send_key_event(vk_code: int, *, key_up: bool) -> None:
    scan_code = user32.MapVirtualKeyW(vk_code, MAPVK_VK_TO_VSC) & 0xFF
    event = INPUT(
        type=INPUT_KEYBOARD,
        ki=KEYBDINPUT(
            wVk=0,
            wScan=scan_code,
            dwFlags=KEYEVENTF_SCANCODE | (KEYEVENTF_KEYUP if key_up else 0),
            time=0,
            dwExtraInfo=0,
        ),
    )
    events = (INPUT * 1)(event)
    if user32.SendInput(1, events, ctypes.sizeof(INPUT)) != 1:
        raise ctypes.WinError(ctypes.get_last_error())


def send_key(vk_code: int) -> None:
    send_key_event(vk_code, key_up=False)
    send_key_event(vk_code, key_up=True)


def hold_key(vk_code: int, hold_ms: int) -> None:
    send_key_event(vk_code, key_up=False)
    try:
        time.sleep(max(0, hold_ms) / 1000.0)
    finally:
        send_key_event(vk_code, key_up=True)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Send keyboard input to a visible top-level window.")
    parser.add_argument("--title", default="SolomonDark", help="Case-insensitive substring to match against the window title.")
    parser.add_argument("--exact-title", help="Require an exact window title match.")
    parser.add_argument("--pid", type=int, help="Require the window to belong to this process ID.")
    parser.add_argument("--activate", action="store_true", help="Bring the matched window to the foreground before sending keys.")
    parser.add_argument(
        "--activation-delay-ms",
        type=int,
        default=250,
        help="Delay after foreground activation before sending input. Default: 250.",
    )
    parser.add_argument(
        "--interval-ms",
        type=int,
        default=120,
        help="Delay between sent keys. Default: 120.",
    )
    parser.add_argument(
        "--post-delay-ms",
        type=int,
        default=150,
        help="Delay after sending the final key before exiting. Default: 150.",
    )
    parser.add_argument(
        "--hold-ms",
        type=int,
        default=0,
        help="Hold one key down for this many milliseconds before releasing it.",
    )
    parser.add_argument(
        "keys",
        nargs="+",
        help="Keys to send in order. Supported: " + ", ".join(sorted(KEY_CODES.keys())),
    )
    return parser


def main() -> int:
    if os.name != "nt":
        print("send_window_keys.py must be run with Windows Python.", file=sys.stderr)
        return 2

    parser = build_parser()
    args = parser.parse_args()

    unknown_keys = [key for key in args.keys if key.casefold() not in KEY_CODES]
    if unknown_keys:
        parser.error("Unsupported keys: " + ", ".join(unknown_keys))
    if args.hold_ms < 0:
        parser.error("--hold-ms cannot be negative")
    if args.hold_ms > 0 and len(args.keys) != 1:
        parser.error("--hold-ms requires exactly one key")

    window = find_window(args.title, args.exact_title, args.pid)
    if args.activate:
        activate_window(window.hwnd, args.activation_delay_ms)
        window = find_window(args.title, args.exact_title, args.pid)

    if args.hold_ms > 0:
        hold_key(KEY_CODES[args.keys[0].casefold()], args.hold_ms)
    else:
        for index, key in enumerate(args.keys):
            send_key(KEY_CODES[key.casefold()])
            if index + 1 != len(args.keys):
                time.sleep(max(0, args.interval_ms) / 1000.0)

    time.sleep(max(0, args.post_delay_ms) / 1000.0)
    print(f"sent keys to {window.title}: {' '.join(args.keys)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
