#!/usr/bin/env python3
"""Send Lua code to a running Solomon Dark game and print the result."""

from __future__ import annotations

import ctypes
import json
import os
import subprocess
import sys
from ctypes import wintypes
from pathlib import Path
from typing import Any

PIPE_NAME = r"\\.\pipe\SolomonDarkModLoader_LuaExec"
BUFFER_SIZE = 4096
MAX_MESSAGE_SIZE = 1024 * 1024

ERROR_BROKEN_PIPE = 109
ERROR_FILE_NOT_FOUND = 2
ERROR_MORE_DATA = 234
ERROR_NO_DATA = 232
ERROR_SEM_TIMEOUT = 121

GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
OPEN_EXISTING = 3
PIPE_READMODE_MESSAGE = 2
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value


class PipeError(RuntimeError):
    """Transport error while talking to the Lua exec pipe."""


def _is_wsl() -> bool:
    try:
        with open("/proc/version", "r", encoding="utf-8", errors="replace") as handle:
            return "microsoft" in handle.read().lower()
    except OSError:
        return False


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _ensure_message_size(kind: str, size: int) -> None:
    if size <= 0:
        raise PipeError(f"{kind} was empty.")
    if size > MAX_MESSAGE_SIZE:
        raise PipeError(f"{kind} exceeded the maximum pipe payload size of {MAX_MESSAGE_SIZE} bytes.")


def _normalize_response(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if not stripped:
        raise PipeError("Pipe closed without returning a response.")

    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        if stripped.startswith("ERROR:"):
            return {
                "ok": False,
                "print_output": "",
                "results": [],
                "error": stripped[len("ERROR:") :].strip() or stripped,
            }
        return {
            "ok": True,
            "print_output": "",
            "results": [text.rstrip("\r\n")],
            "error": "",
        }

    if not isinstance(payload, dict):
        raise PipeError("Pipe returned an unexpected JSON payload.")
    return payload


def _send_lua_wsl(code: str) -> str:
    command = [
        "powershell.exe",
        "-NoProfile",
        "-File",
        "scripts/Invoke-LuaExec.ps1",
        "-Code",
        code,
    ]

    try:
        result = subprocess.run(
            command,
            cwd=_repo_root(),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except FileNotFoundError as exc:
        raise PipeError("powershell.exe was not found from WSL.") from exc

    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or "PowerShell Lua exec bridge failed."
        raise PipeError(message)

    return result.stdout


def _send_lua_pywin32(code: str, timeout_ms: int) -> str:
    import pywintypes
    import win32file
    import win32pipe

    payload = code.encode("utf-8")
    _ensure_message_size("Request", len(payload))

    try:
        win32pipe.WaitNamedPipe(PIPE_NAME, timeout_ms)
    except pywintypes.error as exc:
        if exc.winerror in {ERROR_FILE_NOT_FOUND, ERROR_SEM_TIMEOUT}:
            raise PipeError("Cannot connect to pipe. Is the game running with the mod loader?") from exc
        raise PipeError(f"WaitNamedPipe failed: {exc.strerror or exc}") from exc

    handle = None
    try:
        handle = win32file.CreateFile(
            PIPE_NAME,
            win32file.GENERIC_READ | win32file.GENERIC_WRITE,
            0,
            None,
            win32file.OPEN_EXISTING,
            0,
            None,
        )
        win32pipe.SetNamedPipeHandleState(handle, win32pipe.PIPE_READMODE_MESSAGE, None, None)

        status, written = win32file.WriteFile(handle, payload)
        if status != 0 or written != len(payload):
            raise PipeError(f"Short pipe write: expected {len(payload)} bytes, wrote {written}")

        chunks: list[bytes] = []
        total_size = 0
        while True:
            status, data = win32file.ReadFile(handle, BUFFER_SIZE)
            if data:
                total_size += len(data)
                if total_size > MAX_MESSAGE_SIZE:
                    raise PipeError(
                        f"Response exceeded the maximum pipe payload size of {MAX_MESSAGE_SIZE} bytes."
                    )
                chunks.append(data)

            if status == 0:
                break
            if status != ERROR_MORE_DATA:
                raise PipeError(f"ReadFile failed with status {status}.")

        if not chunks:
            raise PipeError("Pipe closed without returning a response.")
        return b"".join(chunks).decode("utf-8", errors="replace")
    except pywintypes.error as exc:
        if exc.winerror in {ERROR_BROKEN_PIPE, ERROR_NO_DATA}:
            raise PipeError("The Lua exec pipe closed before returning a response.") from exc
        raise PipeError(exc.strerror or str(exc)) from exc
    finally:
        if handle is not None:
            handle.Close()


def _send_lua_ctypes(code: str, timeout_ms: int) -> str:
    if os.name != "nt":
        raise PipeError("Native Lua exec requires Windows Python or WSL.")

    payload = code.encode("utf-8")
    _ensure_message_size("Request", len(payload))

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.ReadFile.argtypes = [
        wintypes.HANDLE,
        wintypes.LPVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        wintypes.LPVOID,
    ]
    kernel32.ReadFile.restype = wintypes.BOOL
    kernel32.WriteFile.argtypes = [
        wintypes.HANDLE,
        wintypes.LPCVOID,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        wintypes.LPVOID,
    ]
    kernel32.WriteFile.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    kernel32.SetNamedPipeHandleState.argtypes = [
        wintypes.HANDLE,
        ctypes.POINTER(wintypes.DWORD),
        wintypes.LPVOID,
        wintypes.LPVOID,
    ]
    kernel32.SetNamedPipeHandleState.restype = wintypes.BOOL
    kernel32.WaitNamedPipeW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD]
    kernel32.WaitNamedPipeW.restype = wintypes.BOOL

    if not kernel32.WaitNamedPipeW(PIPE_NAME, timeout_ms):
        error = ctypes.get_last_error()
        if error in {ERROR_FILE_NOT_FOUND, ERROR_SEM_TIMEOUT}:
            raise PipeError("Cannot connect to pipe. Is the game running with the mod loader?")
        raise PipeError(f"WaitNamedPipeW failed: {ctypes.FormatError(error).strip()} (code={error})")

    handle = kernel32.CreateFileW(
        PIPE_NAME,
        GENERIC_READ | GENERIC_WRITE,
        0,
        None,
        OPEN_EXISTING,
        0,
        None,
    )
    if handle == INVALID_HANDLE_VALUE:
        error = ctypes.get_last_error()
        raise PipeError(f"CreateFileW failed: {ctypes.FormatError(error).strip()} (code={error})")

    try:
        mode = wintypes.DWORD(PIPE_READMODE_MESSAGE)
        if not kernel32.SetNamedPipeHandleState(handle, ctypes.byref(mode), None, None):
            error = ctypes.get_last_error()
            raise PipeError(
                f"SetNamedPipeHandleState failed: {ctypes.FormatError(error).strip()} (code={error})"
            )

        written = wintypes.DWORD(0)
        if not kernel32.WriteFile(handle, payload, len(payload), ctypes.byref(written), None):
            error = ctypes.get_last_error()
            raise PipeError(f"WriteFile failed: {ctypes.FormatError(error).strip()} (code={error})")
        if written.value != len(payload):
            raise PipeError(f"Short pipe write: expected {len(payload)} bytes, wrote {written.value}")

        chunks: list[bytes] = []
        total_size = 0
        while True:
            buffer = ctypes.create_string_buffer(BUFFER_SIZE)
            read = wintypes.DWORD(0)
            ok = kernel32.ReadFile(handle, buffer, len(buffer), ctypes.byref(read), None)
            if read.value:
                total_size += read.value
                if total_size > MAX_MESSAGE_SIZE:
                    raise PipeError(
                        f"Response exceeded the maximum pipe payload size of {MAX_MESSAGE_SIZE} bytes."
                    )
                chunks.append(buffer.raw[: read.value])

            if ok:
                break

            error = ctypes.get_last_error()
            if error == ERROR_MORE_DATA:
                continue
            if error in {ERROR_BROKEN_PIPE, ERROR_NO_DATA} and not chunks:
                raise PipeError("The Lua exec pipe closed before returning a response.")
            raise PipeError(f"ReadFile failed: {ctypes.FormatError(error).strip()} (code={error})")

        if not chunks:
            raise PipeError("Pipe closed without returning a response.")
        return b"".join(chunks).decode("utf-8", errors="replace")
    finally:
        kernel32.CloseHandle(handle)


def send_lua(code: str, timeout_ms: int = 5000) -> dict[str, Any]:
    if not code.strip():
        raise PipeError("No Lua code was provided.")

    if _is_wsl():
        return _normalize_response(_send_lua_wsl(code))

    try:
        import win32file  # noqa: F401
        import win32pipe  # noqa: F401
    except ImportError:
        return _normalize_response(_send_lua_ctypes(code, timeout_ms))

    return _normalize_response(_send_lua_pywin32(code, timeout_ms))


def _write_result(result: str, *, append_newline: bool = False) -> None:
    sys.stdout.write(result)
    if append_newline and result and not result.endswith("\n"):
        sys.stdout.write("\n")
    sys.stdout.flush()


def _write_error(message: str) -> None:
    if not message:
        return

    sys.stderr.write(message)
    if not message.endswith("\n"):
        sys.stderr.write("\n")
    sys.stderr.flush()


def _emit_response(response: dict[str, Any], *, append_newline: bool = False) -> int:
    print_output = response.get("print_output")
    if isinstance(print_output, str) and print_output:
        _write_result(print_output, append_newline=not print_output.endswith("\n"))

    if response.get("ok"):
        results = response.get("results")
        if isinstance(results, list) and results:
            for result in results:
                _write_result(f"{result}", append_newline=True)
        elif not print_output:
            _write_result("ok", append_newline=True)
        elif append_newline and not print_output.endswith("\n"):
            _write_result("", append_newline=True)
        return 0

    error = response.get("error")
    _write_error(str(error).strip() if error else "Lua execution failed.")
    return 1


def _run_repl() -> int:
    print("Solomon Dark Lua REPL (type 'exit' to quit)")
    while True:
        try:
            code = input("> ")
        except EOFError:
            print()
            return 0
        except KeyboardInterrupt:
            print()
            continue

        stripped = code.strip()
        if not stripped:
            continue
        if stripped.lower() in {"exit", "quit"}:
            return 0

        try:
            response = send_lua(code)
        except PipeError as exc:
            _write_error(str(exc))
            continue
        _emit_response(response, append_newline=True)


def main() -> int:
    if len(sys.argv) > 1:
        code = " ".join(sys.argv[1:])
        try:
            return _emit_response(send_lua(code))
        except PipeError as exc:
            _write_error(str(exc))
            return 1

    if not sys.stdin.isatty():
        code = sys.stdin.read()
        if not code.strip():
            return 0
        try:
            return _emit_response(send_lua(code))
        except PipeError as exc:
            _write_error(str(exc))
            return 1

    try:
        return _run_repl()
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
