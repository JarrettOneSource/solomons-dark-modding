#!/usr/bin/env python3
import argparse
import ctypes
import os
import pathlib
import sys
import time
from dataclasses import dataclass
from ctypes import wintypes

from PIL import Image


user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)

EnumWindowsProc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


@dataclass
class WindowInfo:
    hwnd: int
    pid: int
    title: str
    left: int
    top: int
    right: int
    bottom: int

    @property
    def width(self) -> int:
        return max(0, self.right - self.left)

    @property
    def height(self) -> int:
        return max(0, self.bottom - self.top)


def _raise_last_error(message: str) -> None:
    raise OSError(ctypes.get_last_error(), message)


def list_windows() -> list[WindowInfo]:
    windows: list[WindowInfo] = []

    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsWindowVisible.restype = wintypes.BOOL
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.restype = ctypes.c_int
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowTextW.restype = ctypes.c_int
    user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.GetWindowRect.restype = wintypes.BOOL
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD

    @EnumWindowsProc
    def callback(hwnd: int, _lparam: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True

        text_length = user32.GetWindowTextLengthW(hwnd)
        if text_length <= 0:
            return True

        title_buffer = ctypes.create_unicode_buffer(text_length + 1)
        user32.GetWindowTextW(hwnd, title_buffer, len(title_buffer))
        title = title_buffer.value.strip()
        if not title:
            return True

        rect = wintypes.RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            return True

        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

        windows.append(
            WindowInfo(
                hwnd=hwnd,
                pid=pid.value,
                title=title,
                left=rect.left,
                top=rect.top,
                right=rect.right,
                bottom=rect.bottom,
            )
        )
        return True

    user32.EnumWindows.argtypes = [EnumWindowsProc, wintypes.LPARAM]
    user32.EnumWindows.restype = wintypes.BOOL

    if not user32.EnumWindows(callback, 0):
        _raise_last_error("EnumWindows failed")

    return windows


def find_window(title_substring: str | None = None, exact_title: str | None = None, pid: int | None = None) -> WindowInfo:
    windows = list_windows()
    matches = windows

    if pid is not None:
        matches = [window for window in matches if window.pid == pid]
        if not matches:
            raise RuntimeError(f"No visible window belongs to PID {pid}.")
        if exact_title is None and title_substring is None:
            matches.sort(key=lambda window: (-window.width * window.height, window.hwnd))
            return matches[0]

    if exact_title is not None:
        normalized_exact = exact_title.casefold()
        matches = [window for window in matches if window.title.casefold() == normalized_exact]
        if not matches:
            raise RuntimeError(f'No visible window title exactly matched "{exact_title}".')
        matches.sort(key=lambda window: (-window.width * window.height, window.hwnd))
        return matches[0]

    if title_substring is None:
        raise RuntimeError("A title substring, exact title, or PID is required.")

    normalized_query = title_substring.casefold()
    matches = [window for window in matches if normalized_query in window.title.casefold()]
    if not matches:
        raise RuntimeError(f'No visible window title matched "{title_substring}".')

    matches.sort(key=lambda window: (window.title.casefold() != normalized_query, -window.width * window.height))
    return matches[0]


def activate_window(hwnd: int, delay_ms: int) -> None:
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.ShowWindow.restype = wintypes.BOOL
    user32.GetForegroundWindow.argtypes = []
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.SetForegroundWindow.restype = wintypes.BOOL
    user32.BringWindowToTop.argtypes = [wintypes.HWND]
    user32.BringWindowToTop.restype = wintypes.BOOL
    user32.SetWindowPos.argtypes = [
        wintypes.HWND,
        wintypes.HWND,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.UINT,
    ]
    user32.SetWindowPos.restype = wintypes.BOOL

    hwnd_topmost = wintypes.HWND(-1)
    swp_nosize = 0x0001
    swp_nomove = 0x0002
    swp_showwindow = 0x0040

    foreground = user32.GetForegroundWindow()
    if foreground and foreground != hwnd:
        user32.ShowWindow(foreground, 6)

    user32.ShowWindow(hwnd, 9)
    user32.BringWindowToTop(hwnd)
    user32.SetWindowPos(hwnd, hwnd_topmost, 0, 0, 0, 0, swp_nomove | swp_nosize | swp_showwindow)
    user32.SetForegroundWindow(hwnd)
    time.sleep(max(0, delay_ms) / 1000.0)


def capture_window_from_screen(window: WindowInfo, output_path: pathlib.Path) -> None:
    try:
        from mss import mss, tools
    except ModuleNotFoundError as exc:
        raise RuntimeError("Screen capture fallback requires the 'mss' package to be installed.") from exc

    if window.width <= 0 or window.height <= 0:
        raise RuntimeError(f'Window "{window.title}" has invalid bounds: {window.left},{window.top},{window.right},{window.bottom}')

    output_path.parent.mkdir(parents=True, exist_ok=True)
    monitor = {
        "left": window.left,
        "top": window.top,
        "width": window.width,
        "height": window.height,
    }

    with mss() as screen_capture:
        shot = screen_capture.grab(monitor)
        png_bytes = tools.to_png(shot.rgb, shot.size)
        output_path.write_bytes(png_bytes)


def capture_window_from_dc(window: WindowInfo, output_path: pathlib.Path) -> bool:
    width = window.width
    height = window.height
    if width <= 0 or height <= 0:
        return False

    user32.GetWindowDC.argtypes = [wintypes.HWND]
    user32.GetWindowDC.restype = wintypes.HDC
    user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    user32.ReleaseDC.restype = ctypes.c_int
    user32.PrintWindow.argtypes = [wintypes.HWND, wintypes.HDC, wintypes.UINT]
    user32.PrintWindow.restype = wintypes.BOOL

    gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
    gdi32.CreateCompatibleDC.restype = wintypes.HDC
    gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
    gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
    gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
    gdi32.SelectObject.restype = wintypes.HGDIOBJ
    gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
    gdi32.DeleteObject.restype = wintypes.BOOL
    gdi32.DeleteDC.argtypes = [wintypes.HDC]
    gdi32.DeleteDC.restype = wintypes.BOOL
    gdi32.GetDIBits.argtypes = [
        wintypes.HDC,
        wintypes.HBITMAP,
        wintypes.UINT,
        wintypes.UINT,
        wintypes.LPVOID,
        wintypes.LPVOID,
        wintypes.UINT,
    ]
    gdi32.GetDIBits.restype = ctypes.c_int

    window_dc = user32.GetWindowDC(window.hwnd)
    if not window_dc:
        return False

    memory_dc = gdi32.CreateCompatibleDC(window_dc)
    if not memory_dc:
        user32.ReleaseDC(window.hwnd, window_dc)
        return False

    bitmap = gdi32.CreateCompatibleBitmap(window_dc, width, height)
    if not bitmap:
        gdi32.DeleteDC(memory_dc)
        user32.ReleaseDC(window.hwnd, window_dc)
        return False

    old_bitmap = gdi32.SelectObject(memory_dc, bitmap)
    try:
        if not user32.PrintWindow(window.hwnd, memory_dc, 2):
            if not user32.PrintWindow(window.hwnd, memory_dc, 0):
                return False

        class BITMAPINFOHEADER(ctypes.Structure):
            _fields_ = [
                ("biSize", wintypes.DWORD),
                ("biWidth", ctypes.c_long),
                ("biHeight", ctypes.c_long),
                ("biPlanes", wintypes.WORD),
                ("biBitCount", wintypes.WORD),
                ("biCompression", wintypes.DWORD),
                ("biSizeImage", wintypes.DWORD),
                ("biXPelsPerMeter", ctypes.c_long),
                ("biYPelsPerMeter", ctypes.c_long),
                ("biClrUsed", wintypes.DWORD),
                ("biClrImportant", wintypes.DWORD),
            ]

        class BITMAPINFO(ctypes.Structure):
            _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]

        bitmap_info = BITMAPINFO()
        bitmap_info.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bitmap_info.bmiHeader.biWidth = width
        bitmap_info.bmiHeader.biHeight = -height
        bitmap_info.bmiHeader.biPlanes = 1
        bitmap_info.bmiHeader.biBitCount = 32
        bitmap_info.bmiHeader.biCompression = 0

        pixel_buffer = (ctypes.c_ubyte * (width * height * 4))()
        rows_copied = gdi32.GetDIBits(
            memory_dc,
            bitmap,
            0,
            height,
            ctypes.byref(pixel_buffer),
            ctypes.byref(bitmap_info),
            0,
        )
        if rows_copied != height:
            return False

        output_path.parent.mkdir(parents=True, exist_ok=True)
        image = Image.frombuffer("RGBA", (width, height), pixel_buffer, "raw", "BGRA", 0, 1)
        image.save(output_path)
        return True
    finally:
        gdi32.SelectObject(memory_dc, old_bitmap)
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(memory_dc)
        user32.ReleaseDC(window.hwnd, window_dc)


def capture_window(window: WindowInfo, output_path: pathlib.Path, method: str) -> None:
    if method == "window" and capture_window_from_dc(window, output_path):
        return

    capture_window_from_screen(window, output_path)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Capture a visible top-level window to a PNG file.")
    parser.add_argument("--title", default="SolomonDark", help="Case-insensitive substring to match against the window title.")
    parser.add_argument("--exact-title", help="Require an exact window title match.")
    parser.add_argument("--pid", type=int, help="Require the window to belong to this process ID.")
    parser.add_argument("--output", help="Output PNG path.")
    parser.add_argument(
        "--method",
        choices=("window", "screen"),
        default="window",
        help="Capture method. 'window' tries PrintWindow first, 'screen' grabs the on-screen pixels. Default: window.",
    )
    parser.add_argument("--activate", action="store_true", help="Bring the matched window to the foreground before capture.")
    parser.add_argument(
        "--activation-delay-ms",
        type=int,
        default=1000,
        help="Delay after foreground activation before capture. Default: 1000.",
    )
    parser.add_argument("--list", action="store_true", help="List visible windows and exit.")
    return parser


def main() -> int:
    if os.name != "nt":
        print("capture_window.py must be run with Windows Python.", file=sys.stderr)
        return 2

    parser = build_parser()
    args = parser.parse_args()

    if args.list:
        for window in list_windows():
            print(
                f"{window.hwnd:>10}  pid={window.pid:<6}  {window.left:>5},{window.top:<5} "
                f"{window.width:>5}x{window.height:<5}  {window.title}"
            )
        return 0

    window = find_window(args.title, args.exact_title, args.pid)

    if not args.output:
        parser.error("--output is required unless --list is used.")

    output_path = pathlib.Path(args.output).expanduser().resolve()

    if args.activate:
        activate_window(window.hwnd, args.activation_delay_ms)
        window = find_window(args.title, args.exact_title, args.pid)

    capture_window(window, output_path, args.method)
    print(f"captured {window.title} -> {output_path}")
    print(f"bounds={window.left},{window.top},{window.right},{window.bottom}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
