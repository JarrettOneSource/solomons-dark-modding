#!/usr/bin/env python3
import argparse
import ctypes
import os
import sys
import time
from ctypes import wintypes

from capture_window import activate_window, find_window


user32 = ctypes.WinDLL("user32", use_last_error=True)


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


def get_client_origin(hwnd: int) -> tuple[int, int, int, int]:
    rect = wintypes.RECT()
    if not user32.GetClientRect(hwnd, ctypes.byref(rect)):
        raise OSError(ctypes.get_last_error(), "GetClientRect failed")

    origin = POINT(0, 0)
    if not user32.ClientToScreen(hwnd, ctypes.byref(origin)):
        raise OSError(ctypes.get_last_error(), "ClientToScreen failed")

    width = max(0, rect.right - rect.left)
    height = max(0, rect.bottom - rect.top)
    return origin.x, origin.y, width, height


def screen_to_client(hwnd: int, screen_x: int, screen_y: int) -> tuple[int, int]:
    point = POINT(screen_x, screen_y)
    user32.ScreenToClient.argtypes = [wintypes.HWND, ctypes.POINTER(POINT)]
    user32.ScreenToClient.restype = wintypes.BOOL
    if not user32.ScreenToClient(hwnd, ctypes.byref(point)):
        raise OSError(ctypes.get_last_error(), "ScreenToClient failed")
    return point.x, point.y


def click_screen_point(hwnd: int, client_x: int, client_y: int, screen_x: int, screen_y: int) -> None:
    user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
    user32.SetCursorPos.restype = wintypes.BOOL
    user32.mouse_event.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_size_t]
    user32.mouse_event.restype = None
    user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.SendMessageW.restype = wintypes.LPARAM

    mouseeventf_leftdown = 0x0002
    mouseeventf_leftup = 0x0004
    wm_mousemove = 0x0200
    wm_lbuttondown = 0x0201
    wm_lbuttonup = 0x0202
    mk_lbutton = 0x0001
    client_lparam = ((client_y & 0xFFFF) << 16) | (client_x & 0xFFFF)

    if not user32.SetCursorPos(screen_x, screen_y):
        raise OSError(ctypes.get_last_error(), "SetCursorPos failed")

    user32.SendMessageW(hwnd, wm_mousemove, 0, client_lparam)
    user32.SendMessageW(hwnd, wm_lbuttondown, mk_lbutton, client_lparam)
    user32.SendMessageW(hwnd, wm_lbuttonup, 0, client_lparam)
    user32.mouse_event(mouseeventf_leftdown, 0, 0, 0, 0)
    user32.mouse_event(mouseeventf_leftup, 0, 0, 0, 0)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Click inside a visible top-level window by client coordinates.")
    parser.add_argument("--title", default="SolomonDark", help="Case-insensitive substring to match against the window title.")
    parser.add_argument("--exact-title", help="Require an exact window title match.")
    parser.add_argument("--pid", type=int, help="Require the window to belong to this process ID.")
    parser.add_argument("--x", type=float, required=True, help="Client X coordinate. Use pixels by default or a 0-1 fraction with --relative.")
    parser.add_argument("--y", type=float, required=True, help="Client Y coordinate. Use pixels by default or a 0-1 fraction with --relative.")
    parser.add_argument("--relative", action="store_true", help="Interpret --x and --y as 0-1 fractions of client width and height.")
    parser.add_argument("--screen", action="store_true", help="Interpret --x and --y as absolute screen coordinates.")
    parser.add_argument("--activate", action="store_true", help="Bring the matched window to the foreground before clicking.")
    parser.add_argument(
        "--activation-delay-ms",
        type=int,
        default=250,
        help="Delay after foreground activation before clicking. Default: 250.",
    )
    parser.add_argument(
        "--post-delay-ms",
        type=int,
        default=150,
        help="Delay after the click before exiting. Default: 150.",
    )
    return parser


def main() -> int:
    if os.name != "nt":
        print("click_window.py must be run with Windows Python.", file=sys.stderr)
        return 2

    parser = build_parser()
    args = parser.parse_args()

    window = find_window(args.title, args.exact_title, args.pid)
    if args.activate:
        activate_window(window.hwnd, args.activation_delay_ms)
        window = find_window(args.title, args.exact_title, args.pid)

    origin_x, origin_y, client_width, client_height = get_client_origin(window.hwnd)
    click_x = args.x
    click_y = args.y
    if args.screen and args.relative:
        parser.error("--screen and --relative cannot be used together.")

    if args.screen:
        absolute_x = int(round(click_x))
        absolute_y = int(round(click_y))
        click_x, click_y = screen_to_client(window.hwnd, absolute_x, absolute_y)
    else:
        if args.relative:
            click_x *= client_width
            click_y *= client_height

        absolute_x = origin_x + int(round(click_x))
        absolute_y = origin_y + int(round(click_y))

    click_screen_point(window.hwnd, int(round(click_x)), int(round(click_y)), absolute_x, absolute_y)
    time.sleep(max(0, args.post_delay_ms) / 1000.0)
    print(f"clicked {window.title} at client=({int(round(click_x))},{int(round(click_y))}) screen=({absolute_x},{absolute_y})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
