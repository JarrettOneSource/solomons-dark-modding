#!/usr/bin/env python3
"""Lua endpoints and identity discovery for an already-running Steam friend pair."""

from __future__ import annotations

import atexit
import os
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


class SteamFriendActivePair:
    """Routes Lua to the Windows host or isolated WSL/Proton Steam client."""

    def __init__(self) -> None:
        self._wsl = WslLuaDaemon()
        self.host_participant_id = 0
        self.client_participant_id = 0

    def lua(self, endpoint: str, code: str, timeout: float = 10.0) -> str:
        if endpoint == HOST_ENDPOINT:
            return windows_lua(WINDOWS_PIPE, code, timeout=timeout)
        if endpoint == CLIENT_ENDPOINT:
            return self._wsl.execute(code, timeout)
        raise VerifyFailure(f"unknown Steam friend Lua endpoint: {endpoint}")

    def _remote_identity(self, endpoint: str) -> tuple[int, str, str]:
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
        values = parse_key_values(self.lua(endpoint, code, timeout=8.0))
        remote_count = parse_int_text(values.get("remote_count"), 0)
        remote_id = parse_int_text(values.get("remote_id"), 0)
        if remote_count != 1 or remote_id <= 1:
            raise VerifyFailure(
                f"expected exactly one authenticated Steam friend on {endpoint}; "
                f"remote_count={remote_count}"
            )
        return remote_id, values.get("remote_name", ""), values.get("scene", "")

    def discover(self) -> dict[str, Any]:
        client_id, client_name, host_scene = self._remote_identity(HOST_ENDPOINT)
        host_id, host_name, client_scene = self._remote_identity(CLIENT_ENDPOINT)
        if host_id == client_id:
            raise VerifyFailure("Steam friend endpoints resolved the same account identity")
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
        }

    def redact(self, value: Any) -> Any:
        replacements = {
            self.host_participant_id: "host",
            self.client_participant_id: "client",
        }
        if isinstance(value, dict):
            return {str(key): self.redact(item) for key, item in value.items()}
        if isinstance(value, list):
            return [self.redact(item) for item in value]
        if isinstance(value, tuple):
            return [self.redact(item) for item in value]
        if isinstance(value, int) and value in replacements:
            return replacements[value]
        if isinstance(value, str):
            for participant_id, label in replacements.items():
                value = value.replace(str(participant_id), label)
            return value
        return value

    def close(self) -> None:
        self._wsl.close()
