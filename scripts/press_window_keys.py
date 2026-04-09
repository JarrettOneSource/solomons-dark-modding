#!/usr/bin/env python3
import argparse
import ctypes
import os
import sys
import time
from ctypes import wintypes

from capture_window import activate_window, find_window


user32 = ctypes.WinDLL("user32", use_last_error=True)


KEY_ALIASES = {
    "down": 0x28,
    "up": 0x26,
    "left": 0x25,
    "right": 0x27,
    "enter": 0x0D,
    "esc": 0x1B,
    "escape": 0x1B,
    "space": 0x20,
    "tab": 0x09,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Send keyboard input to a visible top-level window.")
    parser.add_argument("--title", default="SolomonDark", help="Case-insensitive substring to match against the window title.")
    parser.add_argument("--exact-title", help="Require an exact window title match.")
    parser.add_argument("--pid", type=int, help="Require the window to belong to this process ID.")
    parser.add_argument(
        "--keys",
        required=True,
        nargs="+",
        help="Key sequence. Supported values include down, up, left, right, enter, esc, space, tab.",
    )
    parser.add_argument("--activate", action="store_true", help="Bring the matched window to the foreground before typing.")
    parser.add_argument(
        "--activation-delay-ms",
        type=int,
        default=250,
        help="Delay after foreground activation before typing. Default: 250.",
    )
    parser.add_argument(
        "--key-delay-ms",
        type=int,
        default=120,
        help="Delay between keys in milliseconds. Default: 120.",
    )
    parser.add_argument(
        "--post-delay-ms",
        type=int,
        default=250,
        help="Delay after the final key before exiting. Default: 250.",
    )
    return parser


MAPVK_VK_TO_VSC = 0


def _send_input(key_code: int, key_up: bool) -> None:
    user32.keybd_event.argtypes = [wintypes.BYTE, wintypes.BYTE, wintypes.DWORD, ctypes.c_size_t]
    user32.keybd_event.restype = None

    scan_code = user32.MapVirtualKeyW(key_code, MAPVK_VK_TO_VSC) & 0xFF
    keyeventf_keyup = 0x0002
    flags = keyeventf_keyup if key_up else 0
    user32.keybd_event(key_code, scan_code, flags, 0)


def send_keypress(key_name: str) -> None:
    key_code = KEY_ALIASES.get(key_name.casefold())
    if key_code is None:
        raise ValueError(f"Unsupported key: {key_name}")
    _send_input(key_code, key_up=False)
    time.sleep(0.03)
    _send_input(key_code, key_up=True)


def main() -> int:
    if os.name != "nt":
        print("press_window_keys.py must be run with Windows Python.", file=sys.stderr)
        return 2

    args = build_parser().parse_args()
    window = find_window(args.title, args.exact_title, args.pid)
    if args.activate:
        activate_window(window.hwnd, args.activation_delay_ms)

    for key_name in args.keys:
        send_keypress(key_name)
        time.sleep(max(0, args.key_delay_ms) / 1000.0)

    time.sleep(max(0, args.post_delay_ms) / 1000.0)
    print(f"sent keys to {window.title}: {' '.join(args.keys)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
