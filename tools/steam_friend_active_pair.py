#!/usr/bin/env python3
"""Lua endpoints and identity discovery for an already-running Steam friend pair."""

from __future__ import annotations

import atexit
import base64
import binascii
import os
import re
import select
import struct
import subprocess
import threading
import time
from pathlib import Path
from typing import Any

from verify_local_multiplayer_sync import (
    VerifyFailure,
    _format_lua_response,
    lua as windows_lua,
    parse_int_text,
    parse_key_values,
)


ROOT = Path(__file__).resolve().parent.parent
HOST_ENDPOINT = "steam-friend-host"
CLIENT_ENDPOINT = "steam-friend-wsl-client"
WINDOWS_PIPE = "SolomonDarkModLoader_LuaExec"
MAXIMUM_FRAME_BYTES = 16 * 1024 * 1024
REMOTE_BRIDGE_PING_LENGTH = 0xFFFFFFFF
PAIR_BACKEND = os.environ.get("SDMOD_STEAM_PAIR_BACKEND", "wsl").strip().lower()
LUA_TRANSITION_TIMEOUT_SECONDS = 35.0
PAIR_DISCOVERY_TIMEOUT_SECONDS = 90.0
PAIR_DISCOVERY_STABLE_SECONDS = 3.0


class WslLuaDaemon:
    """Persistent Proton-side client for the WSL Steam account's named pipe."""

    def __init__(self) -> None:
        self._process: subprocess.Popen[bytes] | None = None
        self._lock = threading.Lock()
        atexit.register(self.close)

    def _start(self) -> subprocess.Popen[bytes]:
        process = self._process
        if process is not None and process.poll() is None:
            return process
        process = subprocess.Popen(
            ["./scripts/Invoke-WslLuaExec.sh", "--daemon"],
            cwd=ROOT,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )
        self._process = process
        return process

    @staticmethod
    def _read_exact(
        process: subprocess.Popen[bytes], size: int, deadline: float
    ) -> bytes:
        assert process.stdout is not None
        chunks: list[bytes] = []
        remaining = size
        descriptor = process.stdout.fileno()
        while remaining:
            wait = deadline - time.monotonic()
            if wait <= 0 or not select.select([descriptor], [], [], wait)[0]:
                raise TimeoutError("WSL Lua daemon response timed out")
            chunk = os.read(descriptor, remaining)
            if not chunk:
                raise EOFError("WSL Lua daemon closed its response stream")
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    @staticmethod
    def _exit_detail(process: subprocess.Popen[bytes]) -> str:
        if process.stderr is None or process.poll() is None:
            return ""
        try:
            return process.stderr.read().decode("utf-8", "replace").strip()
        except OSError:
            return ""

    def execute(self, code: str, timeout: float) -> str:
        request = code.encode("utf-8")
        if not request or len(request) > MAXIMUM_FRAME_BYTES:
            raise VerifyFailure(f"invalid WSL Lua request size: {len(request)}")
        deadline = time.monotonic() + max(0.05, float(timeout))
        with self._lock:
            process = self._start()
            assert process.stdin is not None
            try:
                process.stdin.write(struct.pack("<I", len(request)))
                process.stdin.write(request)
                process.stdin.flush()
                header = self._read_exact(process, 4, deadline)
                response_size = struct.unpack("<I", header)[0]
                if response_size > MAXIMUM_FRAME_BYTES:
                    raise VerifyFailure(
                        f"invalid WSL Lua response size: {response_size}"
                    )
                raw = self._read_exact(process, response_size, deadline).decode(
                    "utf-8", "replace"
                )
            except (BrokenPipeError, EOFError, OSError, TimeoutError) as exc:
                detail = self._exit_detail(process)
                self.close()
                suffix = f": {detail}" if detail else ""
                raise VerifyFailure(f"WSL Lua daemon failed: {exc}{suffix}") from exc

        stdout_text, stderr_text, exit_code = _format_lua_response(raw)
        if exit_code != 0:
            detail = stderr_text.strip() or stdout_text.strip() or "Lua execution failed"
            raise VerifyFailure(f"Lua failed on WSL Steam client: {detail}")
        return stdout_text.strip()

    def close(self) -> None:
        process = self._process
        self._process = None
        if process is None:
            return
        try:
            if process.stdin is not None:
                process.stdin.close()
        except OSError:
            pass
        try:
            process.wait(timeout=1.0)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=1.0)


class RemoteWindowsLuaBridge:
    """Relay framed Lua through an OS-assigned remote loopback listener."""

    def __init__(self) -> None:
        self._process: subprocess.Popen[bytes] | None = None
        self._server_process: subprocess.Popen[bytes] | None = None
        self._lock = threading.Lock()
        self._ssh_host = os.environ.get("SDMOD_STEAM_REMOTE_SSH_HOST", "").strip()
        self._ssh_user = os.environ.get(
            "SDMOD_STEAM_REMOTE_SSH_USER", "TailscaleToday"
        ).strip()
        self._ssh_key = Path(
            os.environ.get(
                "SDMOD_STEAM_REMOTE_SSH_KEY",
                "~/.ssh/id_ed25519_workstation20_tailscale",
            )
        ).expanduser()
        self._pipe_name = os.environ.get(
            "SDMOD_STEAM_REMOTE_PIPE_NAME", WINDOWS_PIPE
        )
        self._bridge_path = os.environ.get(
            "SDMOD_STEAM_REMOTE_LUA_BRIDGE",
            r"C:\Users\Public\Documents\SolomonDarkBeta5RemoteTest\Invoke-RemoteLuaExecBridge.ps1",
        )
        if not self._ssh_host:
            raise VerifyFailure(
                "SDMOD_STEAM_REMOTE_SSH_HOST is required for the "
                "remote-windows-host Steam pair backend"
            )
        if not self._ssh_key.is_file():
            raise VerifyFailure(f"remote Windows SSH key not found: {self._ssh_key}")
        atexit.register(self.close)

    def _encoded_bridge_command(self) -> str:
        bridge_path = self._bridge_path.replace("'", "''")
        pipe_name = self._pipe_name.replace("'", "''")
        command = (
            "$ProgressPreference='SilentlyContinue';"
            "$ErrorActionPreference='Stop';"
            f"& '{bridge_path}' -ListenPort 0 -PipeName '{pipe_name}' "
            "-MaximumResponseTimeoutMilliseconds 300000"
        )
        return base64.b64encode(command.encode("utf-16le")).decode("ascii")

    def _start(self) -> subprocess.Popen[bytes]:
        process = self._process
        server_process = self._server_process
        if (
            process is not None
            and process.poll() is None
            and server_process is not None
            and server_process.poll() is None
        ):
            return process

        self.close()
        server_process = subprocess.Popen(
            [
                "ssh",
                "-T",
                "-i",
                str(self._ssh_key),
                "-o",
                "BatchMode=yes",
                "-o",
                "ConnectTimeout=10",
                "-o",
                "ExitOnForwardFailure=yes",
                "-o",
                "ServerAliveInterval=15",
                "-o",
                "ServerAliveCountMax=2",
                f"{self._ssh_user}@{self._ssh_host}",
                "powershell.exe",
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-OutputFormat",
                "Text",
                "-ExecutionPolicy",
                "Bypass",
                "-EncodedCommand",
                self._encoded_bridge_command(),
            ],
            cwd=ROOT,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )
        self._server_process = server_process

        try:
            line = self._read_line(server_process, time.monotonic() + 15.0)
            match = re.fullmatch(r"SDMOD_BRIDGE_PORT=(\d+)", line)
            if match is None:
                raise VerifyFailure(
                    f"invalid remote Windows bridge startup response: {line!r}"
                )
            remote_port = int(match.group(1))
            if not 1 <= remote_port <= 65535:
                raise VerifyFailure(
                    f"invalid remote Windows bridge port: {remote_port}"
                )

            process = subprocess.Popen(
                [
                    "ssh",
                    "-T",
                    "-i",
                    str(self._ssh_key),
                    "-o",
                    "BatchMode=yes",
                    "-o",
                    "ConnectTimeout=10",
                    "-o",
                    "ServerAliveInterval=15",
                    "-o",
                    "ServerAliveCountMax=2",
                    "-W",
                    f"127.0.0.1:{remote_port}",
                    f"{self._ssh_user}@{self._ssh_host}",
                ],
                cwd=ROOT,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
            )
            self._process = process
            assert process.stdin is not None
            process.stdin.write(
                struct.pack("<II", REMOTE_BRIDGE_PING_LENGTH, 100)
            )
            process.stdin.flush()
            response_size = struct.unpack(
                "<I",
                self._read_exact(process, 4, time.monotonic() + 15.0),
            )[0]
        except (
            BrokenPipeError,
            EOFError,
            OSError,
            TimeoutError,
            struct.error,
            VerifyFailure,
        ) as exc:
            details = [
                self._exit_detail(candidate)
                for candidate in (self._process, self._server_process)
                if candidate is not None
            ]
            self.close()
            detail = "; ".join(item for item in details if item)
            suffix = f": {detail}" if detail else ""
            raise VerifyFailure(
                f"remote Windows Lua bridge failed its startup handshake: {exc}{suffix}"
            ) from exc

        if response_size != 0:
            self.close()
            raise VerifyFailure(
                "remote Windows Lua bridge failed its startup handshake: "
                f"invalid response size {response_size}"
            )
        return process

    @staticmethod
    def _exit_detail(process: subprocess.Popen[bytes]) -> str:
        if process.stderr is None or process.poll() is None:
            return ""
        try:
            return process.stderr.read().decode("utf-8", "replace").strip()
        except OSError:
            return ""

    @staticmethod
    def _read_line(process: subprocess.Popen[bytes], deadline: float) -> str:
        assert process.stdout is not None
        descriptor = process.stdout.fileno()
        data = bytearray()
        while len(data) < 256:
            wait = deadline - time.monotonic()
            if wait <= 0 or not select.select([descriptor], [], [], wait)[0]:
                raise TimeoutError("remote Windows Lua bridge startup timed out")
            chunk = os.read(descriptor, 1)
            if not chunk:
                raise EOFError("remote Windows Lua bridge closed during startup")
            if chunk == b"\n":
                return data.decode("utf-8", "replace").rstrip("\r")
            data.extend(chunk)
        raise VerifyFailure("remote Windows Lua bridge startup line is too long")

    @staticmethod
    def _read_exact(
        process: subprocess.Popen[bytes], size: int, deadline: float
    ) -> bytes:
        assert process.stdout is not None
        chunks: list[bytes] = []
        remaining = size
        descriptor = process.stdout.fileno()
        while remaining:
            wait = deadline - time.monotonic()
            if wait <= 0 or not select.select([descriptor], [], [], wait)[0]:
                raise TimeoutError("remote Windows Lua bridge response timed out")
            chunk = os.read(descriptor, remaining)
            if not chunk:
                raise EOFError("remote Windows Lua bridge closed its response")
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    def _exchange(
        self,
        process: subprocess.Popen[bytes],
        request: bytes,
        response_timeout_milliseconds: int,
        deadline: float,
    ) -> str:
        assert process.stdin is not None
        process.stdin.write(
            struct.pack(
                "<II",
                len(request),
                response_timeout_milliseconds,
            )
        )
        process.stdin.write(request)
        process.stdin.flush()
        response_size = struct.unpack(
            "<I", self._read_exact(process, 4, deadline)
        )[0]
        if response_size > MAXIMUM_FRAME_BYTES:
            raise VerifyFailure(
                f"invalid remote Windows Lua response size: {response_size}"
            )
        return self._read_exact(process, response_size, deadline).decode(
            "utf-8", "replace"
        )

    def execute(self, code: str, timeout: float) -> str:
        request = code.encode("utf-8")
        if not request or len(request) > MAXIMUM_FRAME_BYTES:
            raise VerifyFailure(f"invalid remote Windows Lua request size: {len(request)}")
        response_timeout_seconds = min(300.0, max(0.1, float(timeout)))
        response_timeout_milliseconds = max(
            100,
            int(response_timeout_seconds * 1000.0),
        )
        with self._lock:
            process = self._start()
            try:
                raw = self._exchange(
                    process,
                    request,
                    response_timeout_milliseconds,
                    time.monotonic() + response_timeout_seconds + 6.0,
                )
            except (
                BrokenPipeError,
                EOFError,
                OSError,
                TimeoutError,
                struct.error,
            ) as exc:
                detail = self._exit_detail(process)
                self.close()
                suffix = f": {detail}" if detail else ""
                raise VerifyFailure(
                    f"remote Windows Lua bridge failed: {exc}{suffix}"
                ) from exc

        stdout_text, stderr_text, exit_code = _format_lua_response(raw)
        if exit_code != 0:
            detail = stderr_text.strip() or stdout_text.strip() or "Lua execution failed"
            raise VerifyFailure(f"Lua failed on remote Windows Steam peer: {detail}")
        return stdout_text.strip()

    def close(self) -> None:
        process = self._process
        server_process = self._server_process
        self._process = None
        self._server_process = None
        if (
            process is not None
            and process.poll() is None
            and process.stdin is not None
        ):
            try:
                process.stdin.write(struct.pack("<II", 0, 100))
                process.stdin.flush()
                self._read_exact(process, 4, time.monotonic() + 1.0)
            except (
                BrokenPipeError,
                EOFError,
                OSError,
                TimeoutError,
                struct.error,
            ):
                pass
        if process is not None and process.stdin is not None:
            try:
                process.stdin.close()
            except OSError:
                pass
        for candidate in (process, server_process):
            if candidate is None:
                continue
            try:
                candidate.wait(timeout=3.0)
            except subprocess.TimeoutExpired:
                candidate.terminate()
                try:
                    candidate.wait(timeout=3.0)
                except subprocess.TimeoutExpired:
                    candidate.kill()
                    candidate.wait(timeout=3.0)


class RemoteWindowsLogMirror:
    """Mirror a remote loader log into the local path expected by verifiers."""

    def __init__(self) -> None:
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._remote_path = ""
        self._destination: Path | None = None
        self._ssh_host = ""
        self._ssh_user = ""
        self._ssh_key = Path()
        self._remote_offset = 0
        remote_path = os.environ.get("SDMOD_STEAM_REMOTE_LOG_PATH", "").strip()
        mirror_path = os.environ.get(
            "SDMOD_STEAM_REMOTE_LOG_MIRROR_PATH", ""
        ).strip()
        if not remote_path or not mirror_path:
            return

        ssh_host = os.environ.get("SDMOD_STEAM_REMOTE_SSH_HOST", "").strip()
        ssh_user = os.environ.get(
            "SDMOD_STEAM_REMOTE_SSH_USER", "TailscaleToday"
        ).strip()
        ssh_key = Path(
            os.environ.get(
                "SDMOD_STEAM_REMOTE_SSH_KEY",
                "~/.ssh/id_ed25519_workstation20_tailscale",
            )
        ).expanduser()
        destination = Path(mirror_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.unlink(missing_ok=True)
        remote_spec = f"{ssh_user}@{ssh_host}:{remote_path.replace(chr(92), '/')}"
        copied = subprocess.run(
            ["scp", "-q", "-i", str(ssh_key), remote_spec, str(destination)],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        if copied.returncode != 0:
            raise VerifyFailure(
                "failed to seed remote loader log mirror: "
                + (copied.stderr.strip() or copied.stdout.strip())
            )

        self._remote_path = remote_path
        self._destination = destination
        self._ssh_host = ssh_host
        self._ssh_user = ssh_user
        self._ssh_key = ssh_key
        self._remote_offset = destination.stat().st_size
        self._thread = threading.Thread(
            target=self._poll,
            name="remote-windows-log-mirror",
            daemon=True,
        )
        self._thread.start()
        atexit.register(self.close)

    def _append_available_bytes(self) -> None:
        destination = self._destination
        if destination is None:
            return
        escaped_path = self._remote_path.replace("'", "''")
        requested_offset = self._remote_offset
        powershell = (
            "$ErrorActionPreference='Stop';"
            f"$path='{escaped_path}';"
            f"$requested=[int64]{requested_offset};"
            "$stream=[IO.FileStream]::new($path,[IO.FileMode]::Open,"
            "[IO.FileAccess]::Read,[IO.FileShare]::ReadWrite);"
            "try{"
            "$length=[int64]$stream.Length;"
            "$offset=$requested;"
            "$reset='0';"
            "if($offset -gt $length){$offset=0;$reset='1'};"
            "$available=[int][Math]::Min([int64]2097152,$length-$offset);"
            "$buffer=New-Object byte[] $available;"
            "$stream.Seek($offset,[IO.SeekOrigin]::Begin)|Out-Null;"
            "$total=0;"
            "while($total -lt $available){"
            "$read=$stream.Read($buffer,$total,$available-$total);"
            "if($read -le 0){break};"
            "$total+=$read"
            "};"
            "$payload=[Convert]::ToBase64String($buffer,0,$total);"
            "[Console]::Out.Write($reset+'|'+$offset+'|'+($offset+$total)+'|'+$payload)"
            "}finally{$stream.Dispose()}"
        )
        encoded = base64.b64encode(powershell.encode("utf-16le")).decode("ascii")
        completed = subprocess.run(
            [
                "ssh",
                "-T",
                "-i",
                str(self._ssh_key),
                "-o",
                "BatchMode=yes",
                "-o",
                "ConnectTimeout=5",
                f"{self._ssh_user}@{self._ssh_host}",
                "powershell.exe",
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-OutputFormat",
                "Text",
                "-EncodedCommand",
                encoded,
            ],
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10.0,
            check=False,
        )
        if completed.returncode != 0:
            return
        fields = completed.stdout.strip().split("|", 3)
        if len(fields) != 4:
            return
        try:
            reset = fields[0] == "1"
            start = int(fields[1])
            next_offset = int(fields[2])
            data = base64.b64decode(fields[3], validate=True)
        except (ValueError, binascii.Error):
            return
        if next_offset - start != len(data):
            return
        if not reset and start != self._remote_offset:
            return
        mode = "wb" if reset else "ab"
        with destination.open(mode) as output:
            output.write(data)
        self._remote_offset = next_offset

    def _poll(self) -> None:
        while not self._stop_event.wait(0.25):
            try:
                self._append_available_bytes()
            except (OSError, subprocess.SubprocessError):
                continue

    def close(self) -> None:
        self._stop_event.set()
        thread = self._thread
        self._thread = None
        if thread is not None:
            thread.join(timeout=11.0)


class SteamFriendActivePair:
    """Route Lua to the two physical Steam participants."""

    def __init__(self) -> None:
        self._wsl: WslLuaDaemon | None = None
        self._remote_windows: RemoteWindowsLuaBridge | None = None
        self._remote_windows_endpoint: str | None = None
        self._remote_log: RemoteWindowsLogMirror | None = None
        if PAIR_BACKEND == "wsl":
            self._wsl = WslLuaDaemon()
        elif PAIR_BACKEND in ("remote-windows-host", "remote-windows-client"):
            self._remote_windows = RemoteWindowsLuaBridge()
            self._remote_windows_endpoint = (
                HOST_ENDPOINT if PAIR_BACKEND == "remote-windows-host" else CLIENT_ENDPOINT
            )
            self._remote_log = RemoteWindowsLogMirror()
        else:
            raise VerifyFailure(f"unsupported Steam pair backend: {PAIR_BACKEND!r}")
        self.host_participant_id = 0
        self.client_participant_id = 0

    def lua(self, endpoint: str, code: str, timeout: float = 10.0) -> str:
        if self._remote_windows_endpoint is not None:
            if endpoint == self._remote_windows_endpoint:
                assert self._remote_windows is not None
                return self._remote_windows.execute(code, timeout)
            if endpoint in (HOST_ENDPOINT, CLIENT_ENDPOINT):
                return windows_lua(WINDOWS_PIPE, code, timeout=timeout)
            raise VerifyFailure(f"unknown Steam friend Lua endpoint: {endpoint}")

        if endpoint == HOST_ENDPOINT:
            return windows_lua(WINDOWS_PIPE, code, timeout=timeout)
        if endpoint == CLIENT_ENDPOINT:
            assert self._wsl is not None
            return self._wsl.execute(code, timeout)
        raise VerifyFailure(f"unknown Steam friend Lua endpoint: {endpoint}")

    def _remote_identity(self, endpoint: str) -> tuple[int, int, str, str]:
        code = r"""
local function emit(key, value)
  print(key .. '=' .. tostring(value == nil and '' or value))
end
local state = sd.runtime and sd.runtime.get_multiplayer_state and
  sd.runtime.get_multiplayer_state() or nil
local scene = sd.world and sd.world.get_scene and sd.world.get_scene() or nil
local remotes = {}
for _, participant in ipairs(state and state.participants or {}) do
  if participant.kind == 'RemoteParticipant' then
    table.insert(remotes, participant)
  end
end
emit('scene', scene and (scene.name or scene.kind) or '')
emit('remote_count', #remotes)
if #remotes == 1 then
  emit('remote_id', remotes[1].participant_id or 0)
  emit('remote_name', remotes[1].name or remotes[1].display_name or '')
end
"""
        values = parse_key_values(
            self.lua(endpoint, code, timeout=LUA_TRANSITION_TIMEOUT_SECONDS)
        )
        remote_count = parse_int_text(values.get("remote_count"), 0)
        remote_id = parse_int_text(values.get("remote_id"), 0)
        return (
            remote_count,
            remote_id,
            values.get("remote_name", ""),
            values.get("scene", ""),
        )

    def discover(self) -> dict[str, Any]:
        deadline = time.monotonic() + PAIR_DISCOVERY_TIMEOUT_SECONDS
        stable_since: float | None = None
        last_host_count = 0
        last_client_count = 0
        last_read_error = ""
        while time.monotonic() < deadline:
            try:
                host_snapshot = self._remote_identity(HOST_ENDPOINT)
                client_snapshot = self._remote_identity(CLIENT_ENDPOINT)
            except VerifyFailure as exc:
                # Discovery is read-only. A Proton named-pipe server can close
                # the first connection while a newly launched process replaces
                # the previous prefix endpoint; restart that same exact pipe
                # client on the next bounded discovery sample. Never retry a
                # caller-supplied gameplay mutation here.
                stable_since = None
                last_read_error = str(exc)
                time.sleep(0.25)
                continue
            host_count, client_id, client_name, host_scene = host_snapshot
            client_count, host_id, host_name, client_scene = client_snapshot
            last_host_count = host_count
            last_client_count = client_count
            ready = (
                host_count == 1
                and client_count == 1
                and host_id > 1
                and client_id > 1
                and host_id != client_id
            )
            if not ready:
                stable_since = None
                time.sleep(0.25)
                continue

            now = time.monotonic()
            if stable_since is None:
                stable_since = now
            if now - stable_since < PAIR_DISCOVERY_STABLE_SECONDS:
                time.sleep(0.25)
                continue

            self.host_participant_id = host_id
            self.client_participant_id = client_id
            return {
                "host": {
                    "scene": host_scene,
                    "remote_count": 1,
                    "remote_name_available": bool(client_name),
                },
                "client": {
                    "scene": client_scene,
                    "remote_count": 1,
                    "remote_name_available": bool(host_name),
                },
                "identities_distinct": True,
                "stable_seconds": PAIR_DISCOVERY_STABLE_SECONDS,
            }

        raise VerifyFailure(
            "Steam friend pair did not remain mutually authenticated through "
            f"the readiness window: host_remote_count={last_host_count} "
            f"client_remote_count={last_client_count} "
            f"last_read_error={last_read_error}"
        )

    def redact(self, value: Any) -> Any:
        replacements = {
            participant_id: label
            for participant_id, label in (
                (self.host_participant_id, "host"),
                (self.client_participant_id, "client"),
            )
            if participant_id > 1
        }
        if isinstance(value, dict):
            return {str(key): self.redact(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self.redact(item) for item in value]
        if isinstance(value, tuple):
            return [self.redact(item) for item in value]
        if isinstance(value, bool):
            return value
        if isinstance(value, int) and value in replacements:
            return replacements[value]
        if isinstance(value, str):
            for participant_id, label in replacements.items():
                value = re.sub(
                    rf"(?<!\d){participant_id}(?!\d)",
                    label,
                    value,
                )
            return value
        return value

    def close(self) -> None:
        if self._wsl is not None:
            self._wsl.close()
        if self._remote_log is not None:
            self._remote_log.close()
        if self._remote_windows is not None:
            self._remote_windows.close()
