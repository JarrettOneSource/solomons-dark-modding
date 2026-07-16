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


def click_screen_point(
    hwnd: int,
    client_x: int,
    client_y: int,
    screen_x: int,
    screen_y: int,
    hold_ms: int,
    global_only: bool,
    button: str,
    drag_client_point: tuple[int, int] | None = None,
    drag_screen_point: tuple[int, int] | None = None,
) -> None:
    user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
    user32.SetCursorPos.restype = wintypes.BOOL
    user32.mouse_event.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_size_t]
    user32.mouse_event.restype = None
    user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    user32.SendMessageW.restype = wintypes.LPARAM

    wm_mousemove = 0x0200
    if button == "right":
        mouseeventf_down = 0x0008
        mouseeventf_up = 0x0010
        wm_buttondown = 0x0204
        wm_buttonup = 0x0205
        mk_button = 0x0002
    else:
        mouseeventf_down = 0x0002
        mouseeventf_up = 0x0004
        wm_buttondown = 0x0201
        wm_buttonup = 0x0202
        mk_button = 0x0001
    client_lparam = ((client_y & 0xFFFF) << 16) | (client_x & 0xFFFF)
    release_client_lparam = client_lparam

    if not user32.SetCursorPos(screen_x, screen_y):
        raise OSError(ctypes.get_last_error(), "SetCursorPos failed")

    window_button_down = False
    global_button_down = False
    try:
        user32.mouse_event(mouseeventf_down, 0, 0, 0, 0)
        global_button_down = True
        if not global_only:
            user32.SendMessageW(hwnd, wm_mousemove, 0, client_lparam)
            user32.SendMessageW(hwnd, wm_buttondown, mk_button, client_lparam)
            window_button_down = True
        if drag_client_point is not None and drag_screen_point is not None:
            drag_hold_ms = max(hold_ms, 200)
            drag_x, drag_y = drag_client_point
            drag_screen_x, drag_screen_y = drag_screen_point
            drag_lparam = ((drag_y & 0xFFFF) << 16) | (drag_x & 0xFFFF)
            release_client_lparam = drag_lparam
            step_count = max(6, min(24, drag_hold_ms // 40))
            time.sleep(drag_hold_ms / 4000.0)
            for step in range(1, step_count + 1):
                fraction = step / step_count
                step_screen_x = round(screen_x + (drag_screen_x - screen_x) * fraction)
                step_screen_y = round(screen_y + (drag_screen_y - screen_y) * fraction)
                if not user32.SetCursorPos(step_screen_x, step_screen_y):
                    raise OSError(ctypes.get_last_error(), "SetCursorPos failed while dragging")
                if not global_only:
                    step_client_x = round(client_x + (drag_x - client_x) * fraction)
                    step_client_y = round(client_y + (drag_y - client_y) * fraction)
                    step_lparam = (
                        ((step_client_y & 0xFFFF) << 16)
                        | (step_client_x & 0xFFFF)
                    )
                    user32.SendMessageW(hwnd, wm_mousemove, mk_button, step_lparam)
                time.sleep(drag_hold_ms / (2000.0 * step_count))
            time.sleep(drag_hold_ms / 4000.0)
        elif hold_ms > 0:
            time.sleep(hold_ms / 1000.0)
    finally:
        if global_button_down:
            user32.mouse_event(mouseeventf_up, 0, 0, 0, 0)
        if window_button_down:
            user32.SendMessageW(hwnd, wm_buttonup, 0, release_client_lparam)


def release_mouse_button(button: str) -> None:
    user32.mouse_event.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_size_t]
    user32.mouse_event.restype = None
    mouseeventf_up = 0x0010 if button == "right" else 0x0004
    user32.mouse_event(mouseeventf_up, 0, 0, 0, 0)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Click inside a visible top-level window by client coordinates.")
    parser.add_argument("--title", default="SolomonDark", help="Case-insensitive substring to match against the window title.")
    parser.add_argument("--exact-title", help="Require an exact window title match.")
    parser.add_argument("--pid", type=int, help="Require the window to belong to this process ID.")
    parser.add_argument("--x", type=float, help="Client X coordinate. Use pixels by default or a 0-1 fraction with --relative.")
    parser.add_argument("--y", type=float, help="Client Y coordinate. Use pixels by default or a 0-1 fraction with --relative.")
    parser.add_argument("--drag-x", type=float, help="Optional drag destination X coordinate in the same coordinate space as --x.")
    parser.add_argument("--drag-y", type=float, help="Optional drag destination Y coordinate in the same coordinate space as --y.")
    parser.add_argument("--relative", action="store_true", help="Interpret --x and --y as 0-1 fractions of client width and height.")
    parser.add_argument("--virtual-width", type=float, help="Scale pixel coordinates from this virtual client width.")
    parser.add_argument("--virtual-height", type=float, help="Scale pixel coordinates from this virtual client height.")
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
    parser.add_argument(
        "--hold-ms",
        type=int,
        default=0,
        help="Keep the selected mouse button down for this many milliseconds before release.",
    )
    parser.add_argument(
        "--button",
        choices=("left", "right"),
        default="left",
        help="Mouse button to click. Default: left.",
    )
    parser.add_argument(
        "--global-only",
        action="store_true",
        help="Use only foreground OS mouse state events after positioning the cursor.",
    )
    parser.add_argument(
        "--release-only",
        action="store_true",
        help="Release the selected global mouse button without finding or clicking a window.",
    )
    return parser


def main() -> int:
    if os.name != "nt":
        print("click_window.py must be run with Windows Python.", file=sys.stderr)
        return 2

    parser = build_parser()
    args = parser.parse_args()

    if args.release_only:
        release_mouse_button(args.button)
        print(f"released global {args.button} mouse button")
        return 0
    if args.x is None or args.y is None:
        parser.error("--x and --y are required unless --release-only is used.")
    if (args.drag_x is None) != (args.drag_y is None):
        parser.error("--drag-x and --drag-y must be provided together.")

    window = find_window(args.title, args.exact_title, args.pid)
    if args.activate:
        activate_window(window.hwnd, args.activation_delay_ms)
        window = find_window(args.title, args.exact_title, args.pid)

    origin_x, origin_y, client_width, client_height = get_client_origin(window.hwnd)
    click_x = args.x
    click_y = args.y
    if args.screen and args.relative:
        parser.error("--screen and --relative cannot be used together.")
    if args.screen and (args.virtual_width is not None or args.virtual_height is not None):
        parser.error("--screen cannot be combined with --virtual-width or --virtual-height.")
    if args.relative and (args.virtual_width is not None or args.virtual_height is not None):
        parser.error("--relative cannot be combined with --virtual-width or --virtual-height.")
    if (args.virtual_width is None) != (args.virtual_height is None):
        parser.error("--virtual-width and --virtual-height must be provided together.")
    if args.virtual_width is not None and (args.virtual_width <= 0 or args.virtual_height <= 0):
        parser.error("--virtual-width and --virtual-height must be positive.")

    if args.screen:
        absolute_x = int(round(click_x))
        absolute_y = int(round(click_y))
        click_x, click_y = screen_to_client(window.hwnd, absolute_x, absolute_y)
    else:
        if args.relative:
            click_x *= client_width
            click_y *= client_height
        elif args.virtual_width is not None and args.virtual_height is not None:
            click_x = (click_x / args.virtual_width) * client_width
            click_y = (click_y / args.virtual_height) * client_height

        absolute_x = origin_x + int(round(click_x))
        absolute_y = origin_y + int(round(click_y))

    drag_client_point = None
    drag_screen_point = None
    if args.drag_x is not None and args.drag_y is not None:
        drag_x = args.drag_x
        drag_y = args.drag_y
        if args.screen:
            drag_screen_x = int(round(drag_x))
            drag_screen_y = int(round(drag_y))
            drag_x, drag_y = screen_to_client(window.hwnd, drag_screen_x, drag_screen_y)
        else:
            if args.relative:
                drag_x *= client_width
                drag_y *= client_height
            elif args.virtual_width is not None and args.virtual_height is not None:
                drag_x = (drag_x / args.virtual_width) * client_width
                drag_y = (drag_y / args.virtual_height) * client_height
            drag_screen_x = origin_x + int(round(drag_x))
            drag_screen_y = origin_y + int(round(drag_y))
        drag_client_point = (int(round(drag_x)), int(round(drag_y)))
        drag_screen_point = (drag_screen_x, drag_screen_y)

    click_screen_point(
        window.hwnd,
        int(round(click_x)),
        int(round(click_y)),
        absolute_x,
        absolute_y,
        max(0, args.hold_ms),
        args.global_only,
        args.button,
        drag_client_point,
        drag_screen_point,
    )
    time.sleep(max(0, args.post_delay_ms) / 1000.0)
    action = "dragged" if drag_client_point is not None else "clicked"
    destination = (
        f" to client={drag_client_point} screen={drag_screen_point}"
        if drag_client_point is not None
        else ""
    )
    print(
        f"{args.button}-{action} {window.title} at "
        f"client=({int(round(click_x))},{int(round(click_y))}) "
        f"screen=({absolute_x},{absolute_y}){destination}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
