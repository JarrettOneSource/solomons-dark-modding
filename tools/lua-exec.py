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
        raise RuntimeError(f"ERROR: {kind} was empty.")
    if size > MAX_MESSAGE_SIZE:
        raise RuntimeError(
            f"ERROR: {kind} exceeded the maximum pipe payload size of {MAX_MESSAGE_SIZE} bytes."
        )


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
        raise RuntimeError("ERROR: powershell.exe was not found from WSL.") from exc

    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or "ERROR: PowerShell Lua exec bridge failed."
        raise RuntimeError(message)

    return result.stdout


def _format_response(payload: str) -> tuple[str, str, int]:
    stripped = payload.strip()
    if not stripped:
        return "", "Pipe closed without returning a response.\n", 1

    try:
        response = json.loads(stripped)
    except json.JSONDecodeError:
        if stripped.startswith("ERROR:"):
            return "", f"{stripped[len('ERROR:') :].strip() or stripped}\n", 1
        return payload, "", 0

    if not isinstance(response, dict):
        return payload, "", 0

    if not {"ok", "print_output", "results", "error"}.issubset(response):
        return payload, "", 0

    stdout_parts: list[str] = []
    print_output = response.get("print_output")
    if isinstance(print_output, str) and print_output:
        stdout_parts.append(print_output if print_output.endswith("\n") else f"{print_output}\n")

    if response.get("ok"):
        results = response.get("results")
        if isinstance(results, list) and results:
            stdout_parts.extend(f"{result}\n" for result in results)
        elif not stdout_parts:
            stdout_parts.append("ok\n")
        return "".join(stdout_parts), "", 0

    error = response.get("error")
    if isinstance(error, str) and error:
        return "".join(stdout_parts), f"{error}\n", 1
    return "".join(stdout_parts), "Lua execution failed.\n", 1


def send_lua(code: str) -> str:
    _ensure_message_size("Request", len(code.encode("utf-8")))

    if _is_wsl():
        return _send_lua_wsl(code)

    try:
        import pywintypes
        import win32file
        import win32pipe
    except ImportError:
        return _send_lua_ctypes(code)

    handle = None
    try:
        try:
            win32pipe.WaitNamedPipe(PIPE_NAME, 5000)
        except pywintypes.error as exc:
            if exc.winerror in {ERROR_FILE_NOT_FOUND, ERROR_SEM_TIMEOUT}:
                raise RuntimeError("ERROR: Cannot connect to pipe. Is the game running with the mod loader?") from exc
            raise RuntimeError(f"ERROR: WaitNamedPipe failed: {exc.strerror or exc}") from exc

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

        payload = code.encode("utf-8")
        status, written = win32file.WriteFile(handle, payload)
        if status != 0 or written != len(payload):
            raise RuntimeError(f"ERROR: Short pipe write: expected {len(payload)} bytes, wrote {written}.")

        chunks: list[bytes] = []
        total_size = 0
        while True:
            status, data = win32file.ReadFile(handle, BUFFER_SIZE)
            if data:
                total_size += len(data)
                if total_size > MAX_MESSAGE_SIZE:
                    raise RuntimeError(
                        f"ERROR: Response exceeded the maximum pipe payload size of {MAX_MESSAGE_SIZE} bytes."
                    )
                chunks.append(data)

            if status == 0:
                break
            if status != ERROR_MORE_DATA:
                raise RuntimeError(f"ERROR: ReadFile failed with status {status}.")

        if not chunks:
            raise RuntimeError("ERROR: Pipe closed without returning a response.")
        return b"".join(chunks).decode("utf-8", errors="replace")
    except pywintypes.error as exc:
        if exc.winerror in {ERROR_BROKEN_PIPE, ERROR_NO_DATA, ERROR_FILE_NOT_FOUND}:
            raise RuntimeError("ERROR: Cannot connect to pipe. Is the game running with the mod loader?") from exc
        raise RuntimeError(f"ERROR: {exc.strerror or exc}") from exc
    finally:
        if handle is not None:
            handle.Close()


def _send_lua_ctypes(code: str) -> str:
    if os.name != "nt":
        raise RuntimeError("ERROR: Native Lua exec requires Windows Python or WSL.")

    kernel32 = ctypes.windll.kernel32
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
        wintypes.LPVOID,
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

    if not kernel32.WaitNamedPipeW(PIPE_NAME, 5000):
        error = ctypes.get_last_error()
        if error in {ERROR_FILE_NOT_FOUND, ERROR_SEM_TIMEOUT}:
            raise RuntimeError("ERROR: Cannot connect to pipe. Is the game running with the mod loader?")
        raise RuntimeError(f"ERROR: WaitNamedPipeW failed: {ctypes.FormatError(error).strip()} (code={error})")

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
        raise RuntimeError(f"ERROR: CreateFileW failed: {ctypes.FormatError(error).strip()} (code={error})")

    try:
        mode = wintypes.DWORD(PIPE_READMODE_MESSAGE)
        if not kernel32.SetNamedPipeHandleState(handle, ctypes.byref(mode), None, None):
            error = ctypes.get_last_error()
            raise RuntimeError(
                f"ERROR: SetNamedPipeHandleState failed: {ctypes.FormatError(error).strip()} (code={error})"
            )

        payload = code.encode("utf-8")
        payload_buffer = ctypes.create_string_buffer(payload)
        written = wintypes.DWORD(0)
        if not kernel32.WriteFile(handle, payload_buffer, len(payload), ctypes.byref(written), None):
            error = ctypes.get_last_error()
            raise RuntimeError(f"ERROR: WriteFile failed: {ctypes.FormatError(error).strip()} (code={error})")
        if written.value != len(payload):
            raise RuntimeError(f"ERROR: Short pipe write: expected {len(payload)} bytes, wrote {written.value}.")

        chunks: list[bytes] = []
        total_size = 0
        while True:
            buffer = ctypes.create_string_buffer(BUFFER_SIZE)
            read = wintypes.DWORD(0)
            ok = kernel32.ReadFile(handle, buffer, len(buffer), ctypes.byref(read), None)
            if read.value:
                total_size += read.value
                if total_size > MAX_MESSAGE_SIZE:
                    raise RuntimeError(
                        f"ERROR: Response exceeded the maximum pipe payload size of {MAX_MESSAGE_SIZE} bytes."
                    )
                chunks.append(buffer.raw[: read.value])

            if ok:
                break

            error = ctypes.get_last_error()
            if error == ERROR_MORE_DATA:
                continue
            if error in {ERROR_BROKEN_PIPE, ERROR_NO_DATA} and not chunks:
                raise RuntimeError("ERROR: Pipe closed without returning a response.")
            raise RuntimeError(f"ERROR: ReadFile failed: {ctypes.FormatError(error).strip()} (code={error})")

        if not chunks:
            raise RuntimeError("ERROR: Pipe closed without returning a response.")
        return b"".join(chunks).decode("utf-8", errors="replace")
    finally:
        kernel32.CloseHandle(handle)


def _write_result(result: str) -> None:
    sys.stdout.write(result)
    sys.stdout.flush()


def _write_error(message: str) -> None:
    if not message:
        return

    sys.stderr.write(message)
    if not message.endswith("\n"):
        sys.stderr.write("\n")
    sys.stderr.flush()


def _run_repl() -> int:
    while True:
        line = sys.stdin.readline()
        if line == "":
            return 0

        code = line.rstrip("\r\n")
        stripped = code.strip()
        if not stripped:
            continue
        if stripped.lower() in {"exit", "quit"}:
            return 0

        try:
            stdout_text, stderr_text, exit_code = _format_response(send_lua(code))
            if stdout_text:
                _write_result(stdout_text)
            if stderr_text:
                _write_error(stderr_text.rstrip("\n"))
            if exit_code != 0:
                continue
        except RuntimeError as exc:
            _write_error(str(exc).strip())

    return 0


def main() -> int:
    if len(sys.argv) > 1:
        code = " ".join(sys.argv[1:])
        try:
            stdout_text, stderr_text, exit_code = _format_response(send_lua(code))
            if stdout_text:
                _write_result(stdout_text)
            if stderr_text:
                _write_error(stderr_text.rstrip("\n"))
            return exit_code
        except RuntimeError as exc:
            _write_error(str(exc).strip())
            return 1

    if not sys.stdin.isatty():
        code = sys.stdin.read()
        if not code.strip():
            return 0

        try:
            stdout_text, stderr_text, exit_code = _format_response(send_lua(code))
            if stdout_text:
                _write_result(stdout_text)
            if stderr_text:
                _write_error(stderr_text.rstrip("\n"))
            return exit_code
        except RuntimeError as exc:
            _write_error(str(exc).strip())
            return 1

    try:
        return _run_repl()
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
