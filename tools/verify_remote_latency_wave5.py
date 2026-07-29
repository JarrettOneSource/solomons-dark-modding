#!/usr/bin/env python3
"""Run and analyze the two-machine local-UDP wave-five WAN scenario.

The verifier deliberately does not provision arbitrary remote hosts. Its
configuration names the exact Windows OpenSSH binaries, SSH alias, isolated
remote root, staged package/game roots, ports, and evidence directory. Every
remote command goes through the configured Windows OpenSSH executable.
"""

from __future__ import annotations

import argparse
import base64
import bisect
import hashlib
import json
import math
import os
import re
import select
import shlex
import shutil
import statistics
import struct
import subprocess
import sys
import tarfile
import time
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
LOCAL_LAUNCH_SCRIPT = ROOT / "scripts/Launch-RemoteLatencyPeer.ps1"
LOCAL_STOP_SCRIPT = ROOT / "scripts/Stop-RemoteLatencyPeer.ps1"
LOCAL_LUA_SCRIPT = ROOT / "scripts/Invoke-LuaExec.ps1"
REMOTE_HELPER_NAME = "Run-RemoteLatencyPeer.sh"

HOST_PARTICIPANT_ID_TEXT = "0x200000000000C101"
CLIENT_PARTICIPANT_ID_TEXT = "0x200000000000C102"
HOST_PARTICIPANT_ID = int(HOST_PARTICIPANT_ID_TEXT, 16)
CLIENT_PARTICIPANT_ID = int(CLIENT_PARTICIPANT_ID_TEXT, 16)
HOST_NAME = "WAN host"
CLIENT_NAME = "client B"
BOT_NAMES = ("Ember", "Brook")
BOT_BRAIN_MOD_ID = "bot.brain"
LUA_EXEC_TARGET_DIRECTIVE = "-- sdmod-exec-target: "
BOT_ROSTER = (
    {
        "name": "Ember",
        "element": "fire",
        "discipline": "arcane",
        "behavior": "skirmisher",
    },
    {
        "name": "Brook",
        "element": "water",
        "discipline": "mind",
        "behavior": "striker",
    },
)
HARD_SPIKE_THRESHOLD_US = 150_000
PACKET_MTU_PAYLOAD_BYTES = 1472
WAVE_STALL_ASSIST_SECONDS = 20.0
WAVE_STALL_ASSIST_INTERVAL_SECONDS = 1.0
WAVE_TIMELINE_INTERVAL_SECONDS = 1.0
WAVE_MONITOR_INTERVAL_SECONDS = 1.0
MAX_EXPECTED_ENEMY_STEP = 350.0
MAX_EXPECTED_IN_FLIGHT_LIFE_DELTA = 25.0

Location = Literal["local", "remote"]
Role = Literal["host", "client"]
Direction = Literal["a", "b"]


class VerificationFailure(RuntimeError):
    """Raised when a WAN acceptance invariant fails."""


def read_bounded_line(
    stream: Any,
    buffer: bytearray,
    *,
    timeout: float,
    label: str,
) -> bytes:
    deadline = time.monotonic() + timeout
    descriptor = stream.fileno()
    while True:
        newline = buffer.find(b"\n")
        if newline >= 0:
            line = bytes(buffer[:newline]).rstrip(b"\r")
            del buffer[: newline + 1]
            return line
        wait = deadline - time.monotonic()
        if wait <= 0:
            raise VerificationFailure(f"{label} timed out.")
        ready, _, _ = select.select(
            [descriptor],
            [],
            [],
            wait,
        )
        if not ready:
            raise VerificationFailure(f"{label} timed out.")
        chunk = os.read(descriptor, 64 * 1024)
        if not chunk:
            return b""
        buffer.extend(chunk)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def atomic_write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(
        f".{path.name}.{os.getpid()}.{time.monotonic_ns()}.tmp"
    )
    with temporary.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(payload, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def windows_path(path: Path) -> str:
    completed = subprocess.run(
        ["wslpath", "-w", str(path)],
        capture_output=True,
        text=True,
        timeout=15,
        check=False,
    )
    if completed.returncode != 0:
        raise VerificationFailure(
            f"Could not convert path for Windows: {path}: "
            f"{completed.stderr.strip()}"
        )
    return completed.stdout.replace("\r", "").strip()


def run_checked(
    command: Sequence[str],
    *,
    timeout: float,
    cwd: Path = ROOT,
    environment: dict[str, str] | None = None,
) -> str:
    completed = subprocess.run(
        list(command),
        cwd=cwd,
        env=environment,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if completed.returncode != 0:
        raise VerificationFailure(
            "Command failed with exit code "
            f"{completed.returncode}: {command!r}\n"
            f"stdout={completed.stdout!r}\n"
            f"stderr={completed.stderr!r}"
        )
    return completed.stdout.replace("\r", "")


def parse_key_values(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in text.replace("\r", "").splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def unwrap_lua_exec_response(text: str) -> str:
    """Match Invoke-LuaExec.ps1 formatting for the remote Win32 client."""
    try:
        response = json.loads(text)
    except json.JSONDecodeError:
        return text
    if not isinstance(response, dict) or not {
        "ok",
        "print_output",
        "results",
        "error",
    }.issubset(response):
        return text

    output = ""
    print_output = response["print_output"]
    if isinstance(print_output, str) and print_output:
        output += print_output
        if not output.endswith(("\n", "\r")):
            output += "\n"
    if not response["ok"]:
        error = response["error"]
        raise VerificationFailure(
            error if isinstance(error, str) and error.strip()
            else "Lua execution failed."
        )

    results = response["results"]
    if isinstance(results, list) and results:
        output += "".join(f"{result}\n" for result in results)
    elif not output:
        output = "ok\n"
    return output


def number(
    values: dict[str, str],
    key: str,
    default: float = math.nan,
) -> float:
    try:
        return float(values.get(key, str(default)))
    except (TypeError, ValueError):
        return default


def integer(
    values: dict[str, str],
    key: str,
    default: int = 0,
) -> int:
    text = values.get(key, str(default))
    try:
        return int(text, 10)
    except (TypeError, ValueError):
        value = number(values, key, float(default))
        return int(value) if math.isfinite(value) else default


def boolean(values: dict[str, str], key: str) -> bool:
    return values.get(key, "").casefold() == "true"


def percentile(values: Sequence[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    position = (len(ordered) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(ordered[lower])
    fraction = position - lower
    return float(
        ordered[lower] * (1.0 - fraction)
        + ordered[upper] * fraction
    )


def distribution(values: Iterable[int | float]) -> dict[str, float | int]:
    rows = [float(value) for value in values]
    if not rows:
        return {
            "count": 0,
            "maximum": 0.0,
            "mean": 0.0,
            "p50": 0.0,
            "p95": 0.0,
            "p99": 0.0,
        }
    return {
        "count": len(rows),
        "maximum": max(rows),
        "mean": statistics.fmean(rows),
        "p50": percentile(rows, 0.50),
        "p95": percentile(rows, 0.95),
        "p99": percentile(rows, 0.99),
    }


@dataclass(frozen=True)
class HarnessConfig:
    path: Path
    ssh_executable: Path
    scp_executable: Path
    ssh_alias: str
    remote_root: str
    remote_public_host: str
    local_public_host: str
    evidence_root: Path
    local_package_root: Path
    local_game_root: Path
    local_runtime_root: Path
    local_lua_client: Path
    local_host_port: int
    local_client_port: int
    remote_host_port: int
    remote_client_port: int
    timeout_seconds: float

    @property
    def local_launcher(self) -> Path:
        return (
            self.local_package_root
            / "launcher"
            / "SolomonDarkModLauncher.exe"
        )

    @property
    def remote_helper(self) -> str:
        return f"{self.remote_root}/tools/{REMOTE_HELPER_NAME}"

    @property
    def remote_package_root(self) -> str:
        return f"{self.remote_root}/package"

    @property
    def remote_game_root(self) -> str:
        return f"{self.remote_root}/game"

    @property
    def remote_runtime_root(self) -> str:
        return f"{self.remote_root}/runtime"


def _path_field(
    document: dict[str, Any],
    section: str,
    key: str,
) -> Path:
    value = document.get(section, {}).get(key)
    if not isinstance(value, str) or not value:
        raise VerificationFailure(
            f"Configuration field {section}.{key} must be a path."
        )
    return Path(value).expanduser().resolve()


def _port_field(
    document: dict[str, Any],
    section: str,
    key: str,
) -> int:
    value = document.get(section, {}).get(key)
    if not isinstance(value, int) or not 1024 <= value <= 65535:
        raise VerificationFailure(
            f"Configuration field {section}.{key} must be a high UDP port."
        )
    return value


def load_config(path: Path) -> HarnessConfig:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise VerificationFailure("Harness configuration must be an object.")
    ssh = document.get("ssh", {})
    network = document.get("network", {})
    execution = document.get("execution", {})
    if not isinstance(ssh, dict) or not isinstance(network, dict):
        raise VerificationFailure("ssh and network configuration are required.")

    alias = ssh.get("alias")
    remote_root = ssh.get("remote_root")
    remote_public = network.get("remote_public_host")
    local_public = network.get("local_public_host")
    if not isinstance(alias, str) or not re.fullmatch(
        r"[A-Za-z0-9._-]+", alias
    ):
        raise VerificationFailure("ssh.alias is not a safe OpenSSH alias.")
    if not isinstance(remote_root, str) or not re.fullmatch(
        r"/root/sd-netlag-[A-Za-z0-9._-]+", remote_root
    ):
        raise VerificationFailure(
            "ssh.remote_root must be one exact /root/sd-netlag-* directory."
        )
    for label, value in (
        ("network.remote_public_host", remote_public),
        ("network.local_public_host", local_public),
    ):
        if not isinstance(value, str) or not re.fullmatch(
            r"[A-Za-z0-9.:-]+", value
        ):
            raise VerificationFailure(f"{label} is not a safe host literal.")

    ssh_executable = _path_field(document, "ssh", "executable")
    scp_executable = _path_field(document, "ssh", "scp_executable")
    if ssh_executable.name.casefold() != "ssh.exe":
        raise VerificationFailure("ssh.executable must name Windows ssh.exe.")
    if scp_executable.name.casefold() != "scp.exe":
        raise VerificationFailure("ssh.scp_executable must name Windows scp.exe.")
    if (
        "windows/system32/openssh"
        not in ssh_executable.as_posix().casefold()
        or "windows/system32/openssh"
        not in scp_executable.as_posix().casefold()
    ):
        raise VerificationFailure(
            "Only Windows System32 OpenSSH is accepted for this harness."
        )

    config = HarnessConfig(
        path=path.resolve(),
        ssh_executable=ssh_executable,
        scp_executable=scp_executable,
        ssh_alias=alias,
        remote_root=remote_root,
        remote_public_host=remote_public,
        local_public_host=local_public,
        evidence_root=_path_field(document, "local", "evidence_root"),
        local_package_root=_path_field(document, "local", "package_root"),
        local_game_root=_path_field(document, "local", "game_root"),
        local_runtime_root=_path_field(document, "local", "runtime_root"),
        local_lua_client=_path_field(document, "local", "lua_client"),
        local_host_port=_port_field(
            document, "network", "local_host_port"
        ),
        local_client_port=_port_field(
            document, "network", "local_client_port"
        ),
        remote_host_port=_port_field(
            document, "network", "remote_host_port"
        ),
        remote_client_port=_port_field(
            document, "network", "remote_client_port"
        ),
        timeout_seconds=float(execution.get("timeout_seconds", 900.0)),
    )
    if config.local_host_port != 50311 or config.local_client_port != 50312:
        raise VerificationFailure(
            "This owner-authorized run requires local ports 50311/50312."
        )
    if config.remote_host_port != 51511 or config.remote_client_port != 51512:
        raise VerificationFailure(
            "This owner-authorized run requires NFO ports 51511/51512."
        )
    if len(
        {
            config.local_host_port,
            config.local_client_port,
            config.remote_host_port,
            config.remote_client_port,
        }
    ) != 4:
        raise VerificationFailure("All four pinned ports must be distinct.")
    if config.timeout_seconds < 120 or config.timeout_seconds > 1800:
        raise VerificationFailure(
            "execution.timeout_seconds must be between 120 and 1800."
        )
    return config


def validate_staged_config(config: HarnessConfig) -> dict[str, Any]:
    required_local = (
        config.ssh_executable,
        config.scp_executable,
        config.local_launcher,
        config.local_game_root / "SolomonDark.exe",
        config.local_lua_client,
        LOCAL_LAUNCH_SCRIPT,
        LOCAL_STOP_SCRIPT,
        LOCAL_LUA_SCRIPT,
    )
    missing = [str(path) for path in required_local if not path.exists()]
    if missing:
        raise VerificationFailure(
            f"Required staged inputs are missing: {missing}"
        )
    if config.evidence_root != Path(
        "/mnt/d/codex-evidence/netlag-20260728"
    ):
        raise VerificationFailure(
            "Evidence must remain in the owner-scoped netlag directory."
        )
    return {
        "configuration": str(config.path),
        "sshExecutable": str(config.ssh_executable),
        "scpExecutable": str(config.scp_executable),
        "sshAlias": config.ssh_alias,
        "remoteRoot": config.remote_root,
        "localPorts": [
            config.local_host_port,
            config.local_client_port,
        ],
        "remotePorts": [
            config.remote_host_port,
            config.remote_client_port,
        ],
        "localPackageRoot": str(config.local_package_root),
        "localGameRoot": str(config.local_game_root),
        "localRuntimeRoot": str(config.local_runtime_root),
    }


def write_bot_settings(
    config: HarnessConfig,
) -> dict[str, Any]:
    if config.evidence_root != Path(
        "/mnt/d/codex-evidence/netlag-20260728"
    ):
        raise VerificationFailure(
            "Bot settings may only be staged in the owner-scoped "
            "netlag evidence directory."
        )
    output = config.evidence_root / "staging/tools"
    output.mkdir(parents=True, exist_ok=True)
    common = {
        "focus_bot_key": "NONE",
        "kite_radius": 340,
        "offense_enabled": True,
        "think_profile": "standard",
    }
    written: dict[str, Any] = {}
    for role, roster in (
        ("host", list(BOT_ROSTER)),
        ("client", []),
    ):
        path = output / f"bot-settings-{role}.json"
        atomic_write_json(
            path,
            {
                "schemaVersion": 1,
                "values": {
                    **common,
                    "roster": roster,
                },
            },
        )
        written[role] = {
            "path": str(path),
            "sha256": sha256_file(path),
        }
    return written


def ssh(config: HarnessConfig, remote_command: str, timeout: float = 60) -> str:
    return run_checked(
        [
            str(config.ssh_executable),
            "-o",
            "BatchMode=yes",
            config.ssh_alias,
            remote_command,
        ],
        timeout=timeout,
    )


def ssh_read_only(
    config: HarnessConfig,
    remote_command: str,
    *,
    timeout: float = 20,
    attempts: int = 3,
) -> str:
    last_timeout: subprocess.TimeoutExpired | None = None
    for attempt in range(attempts):
        try:
            return ssh(config, remote_command, timeout=timeout)
        except subprocess.TimeoutExpired as error:
            last_timeout = error
            if attempt + 1 < attempts:
                time.sleep(0.5)
    assert last_timeout is not None
    raise last_timeout


def scp_from(
    config: HarnessConfig,
    remote_path: str,
    local_path: Path,
    timeout: float = 120,
) -> None:
    local_path.parent.mkdir(parents=True, exist_ok=True)
    run_checked(
        [
            str(config.scp_executable),
            "-o",
            "BatchMode=yes",
            f"{config.ssh_alias}:{remote_path}",
            windows_path(local_path),
        ],
        timeout=timeout,
    )


def scp_to(
    config: HarnessConfig,
    local_path: Path,
    remote_path: str,
    timeout: float = 600,
) -> None:
    run_checked(
        [
            str(config.scp_executable),
            "-o",
            "BatchMode=yes",
            windows_path(local_path),
            f"{config.ssh_alias}:{remote_path}",
        ],
        timeout=timeout,
    )


def remote_helper(
    config: HarnessConfig,
    command_name: str,
    *arguments: str,
    timeout: float = 90,
) -> str:
    command = [
        config.remote_helper,
        config.remote_root,
        command_name,
        *arguments,
    ]
    return ssh(
        config,
        " ".join(shlex.quote(value) for value in command),
        timeout=timeout,
    )


class RemoteLineStream:
    def __init__(
        self,
        config: HarnessConfig,
        command_name: str,
        *arguments: str,
    ) -> None:
        command = [
            config.remote_helper,
            config.remote_root,
            command_name,
            *arguments,
        ]
        remote_command = " ".join(
            shlex.quote(value) for value in command
        )
        self.process = subprocess.Popen(
            [
                str(config.ssh_executable),
                "-o",
                "BatchMode=yes",
                config.ssh_alias,
                remote_command,
            ],
            cwd=ROOT,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )

    def request(self, line: str, *, timeout: float) -> str:
        if (
            self.process.stdin is None
            or self.process.stdout is None
        ):
            raise VerificationFailure(
                "Remote control stream has no standard I/O."
            )
        self.process.stdin.write(line + "\n")
        self.process.stdin.flush()
        ready, _, _ = select.select(
            [self.process.stdout],
            [],
            [],
            timeout,
        )
        if not ready:
            raise VerificationFailure(
                f"Remote control stream timed out after {timeout}s."
            )
        response = self.process.stdout.readline()
        if response:
            return response.rstrip("\r\n")
        stderr = ""
        if self.process.stderr is not None:
            stderr = self.process.stderr.read().strip()
        raise VerificationFailure(
            "Remote control stream closed unexpectedly"
            + (f": {stderr}" if stderr else ".")
        )

    def close(self) -> None:
        if self.process.stdin is not None:
            self.process.stdin.close()
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)


class RemoteLuaStream:
    def __init__(
        self,
        config: HarnessConfig,
        instance: str,
    ) -> None:
        command = [
            config.remote_helper,
            config.remote_root,
            "lua-daemon",
            instance,
        ]
        remote_command = " ".join(
            shlex.quote(value) for value in command
        )
        self.process = subprocess.Popen(
            [
                str(config.ssh_executable),
                "-o",
                "BatchMode=yes",
                config.ssh_alias,
                remote_command,
            ],
            cwd=ROOT,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def _read_exact(self, size: int, *, timeout: float) -> bytes:
        if self.process.stdout is None:
            raise VerificationFailure(
                "Remote Lua daemon has no stdout."
            )
        deadline = time.monotonic() + timeout
        chunks: list[bytes] = []
        remaining = size
        descriptor = self.process.stdout.fileno()
        while remaining:
            wait = deadline - time.monotonic()
            if wait <= 0:
                raise VerificationFailure(
                    "Remote Lua daemon response timed out."
                )
            ready, _, _ = select.select(
                [descriptor],
                [],
                [],
                wait,
            )
            if not ready:
                raise VerificationFailure(
                    "Remote Lua daemon response timed out."
                )
            chunk = os.read(descriptor, remaining)
            if not chunk:
                stderr = ""
                if self.process.stderr is not None:
                    stderr = self.process.stderr.read().decode(
                        "utf-8",
                        errors="replace",
                    ).strip()
                raise VerificationFailure(
                    "Remote Lua daemon closed unexpectedly"
                    + (f": {stderr}" if stderr else ".")
                )
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    def request(self, code: str, *, timeout: float) -> str:
        if self.process.stdin is None:
            raise VerificationFailure(
                "Remote Lua daemon has no stdin."
            )
        payload = code.encode("utf-8")
        self.process.stdin.write(struct.pack("<I", len(payload)))
        self.process.stdin.write(payload)
        self.process.stdin.flush()
        response_size = struct.unpack(
            "<I",
            self._read_exact(4, timeout=timeout),
        )[0]
        if response_size > 16 * 1024 * 1024:
            raise VerificationFailure(
                "Remote Lua daemon returned an oversized response."
            )
        return self._read_exact(
            response_size,
            timeout=timeout,
        ).decode("utf-8")

    def close(self) -> None:
        if self.process.stdin is not None:
            self.process.stdin.close()
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)


class LocalLuaStream:
    def __init__(self, pipe_name: str) -> None:
        self.process = subprocess.Popen(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                windows_path(LOCAL_LUA_SCRIPT),
                "-Daemon",
                "-PipeName",
                pipe_name,
            ],
            cwd=ROOT,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self.stdout_buffer = bytearray()

    def request(self, code: str, *, timeout: float) -> str:
        if (
            self.process.stdin is None
            or self.process.stdout is None
        ):
            raise VerificationFailure(
                "Local Lua daemon has no standard I/O."
            )
        encoded = base64.b64encode(
            code.encode("utf-8")
        )
        self.process.stdin.write(encoded + b"\n")
        self.process.stdin.flush()
        response = read_bounded_line(
            self.process.stdout,
            self.stdout_buffer,
            timeout=timeout,
            label="Local Lua daemon response",
        )
        if not response:
            raise VerificationFailure(
                "Local Lua daemon closed unexpectedly."
            )
        try:
            decoded = base64.b64decode(
                response,
                validate=True,
            ).decode("utf-8")
        except (ValueError, UnicodeDecodeError) as error:
            raise VerificationFailure(
                "Local Lua daemon returned invalid base64."
            ) from error
        if decoded.startswith("ERROR:"):
            raise VerificationFailure(decoded)
        return decoded

    def close(self) -> None:
        if self.process.stdin is not None:
            self.process.stdin.close()
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)


_REMOTE_LUA_STREAMS: dict[tuple[str, str], RemoteLuaStream] = {}
_LOCAL_LUA_STREAMS: dict[tuple[str, str], LocalLuaStream] = {}


def close_lua_streams(config: HarnessConfig) -> None:
    prefix = str(config.path)
    for streams in (_REMOTE_LUA_STREAMS, _LOCAL_LUA_STREAMS):
        for key, stream in list(streams.items()):
            if key[0] != prefix:
                continue
            stream.close()
            del streams[key]


def remote_lua(
    config: HarnessConfig,
    peer: Peer,
    code: str,
) -> str:
    key = (str(config.path), peer.instance)
    stream = _REMOTE_LUA_STREAMS.get(key)
    if stream is None:
        stream = RemoteLuaStream(
            config,
            peer.instance,
        )
        _REMOTE_LUA_STREAMS[key] = stream
    try:
        return stream.request(code, timeout=30)
    except BaseException:
        stream.close()
        _REMOTE_LUA_STREAMS.pop(key, None)
        raise


def local_lua(
    config: HarnessConfig,
    peer: Peer,
    code: str,
) -> str:
    key = (str(config.path), peer.instance)
    stream = _LOCAL_LUA_STREAMS.get(key)
    if stream is None:
        stream = LocalLuaStream(peer.pipe_name)
        _LOCAL_LUA_STREAMS[key] = stream
    try:
        return stream.request(code, timeout=25)
    except BaseException:
        stream.close()
        _LOCAL_LUA_STREAMS.pop(key, None)
        raise


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", errors="strict") as stream:
        for line_number, line in enumerate(stream, start=1):
            if not line.strip():
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError as error:
                raise VerificationFailure(
                    f"Invalid telemetry JSONL at {path}:{line_number}: {error}"
                ) from error
            if not isinstance(event, dict):
                raise VerificationFailure(
                    f"Telemetry row is not an object at {path}:{line_number}."
                )
            events.append(event)
    return events


def event_rows(
    events: Sequence[dict[str, Any]],
    event_name: str,
) -> list[dict[str, Any]]:
    return [row for row in events if row.get("event") == event_name]


def logger_caller_rows(
    events: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        row
        for row in events
        if row.get("event") in ("logger_write", "logger_enqueue")
    ]


def wire_arrival_gap_us(row: dict[str, Any]) -> int:
    if "wire_arrival_gap_us" in row:
        if (
            row.get("event") == "packet_receive"
            and not bool(row.get("physical_datagram", True))
        ):
            return 0
        return int(row.get("wire_arrival_gap_us", 0))
    return int(row.get("arrival_gap_us", 0))


def wire_arrival_gaps(
    events: Sequence[dict[str, Any]],
) -> list[int]:
    gaps: list[int] = []
    for event_name in ("packet_receive", "fragment_receive"):
        gaps.extend(
            gap
            for row in event_rows(events, event_name)
            if (gap := wire_arrival_gap_us(row)) > 0
        )
    return gaps


def summarize_telemetry(
    events: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    counts = Counter(str(row.get("event", "")) for row in events)
    receives = event_rows(events, "packet_receive")
    sends = event_rows(events, "packet_send")
    applies = event_rows(events, "packet_apply")
    batches = event_rows(events, "receive_batch")
    ticks = event_rows(events, "transport_tick")
    stages = event_rows(events, "transport_stage")
    worlds = event_rows(events, "world_apply")
    presents = event_rows(events, "present")
    logger = logger_caller_rows(events)
    logger_flushes = event_rows(events, "logger_flush")
    recovery_sends = event_rows(events, "recovery_send")
    recovery_acks = event_rows(events, "recovery_ack")
    fragments = event_rows(events, "fragment_receive")
    ingress_drops = event_rows(events, "ingress_drop")
    starts = event_rows(events, "transport_start")
    stops = event_rows(events, "telemetry_stop")
    largest_by_kind: dict[str, int] = {}
    for row in sends:
        key = str(int(row.get("kind", 0)))
        largest_by_kind[key] = max(
            largest_by_kind.get(key, 0),
            int(
                row.get(
                    "largest_datagram_bytes",
                    row.get("bytes", 0),
                )
            ),
        )

    return {
        "eventCount": len(events),
        "eventCounts": dict(sorted(counts.items())),
        "transportStart": starts[-1] if starts else None,
        "droppedLines": (
            int(stops[-1].get("dropped_lines", 0))
            if stops
            else None
        ),
        "receiveArrivalGapUs": distribution(
            wire_arrival_gaps(events)
        ),
        "packetQueueAgeUs": distribution(
            int(row.get("queue_age_us", 0))
            for row in applies
        ),
        "packetApplyDurationUs": distribution(
            int(row.get("duration_us", 0)) for row in applies
        ),
        "receiveBatchSize": distribution(
            int(row.get("packet_count", 0)) for row in batches
        ),
        "receiveBatchDurationUs": distribution(
            int(row.get("duration_us", 0)) for row in batches
        ),
        "receiveBatchLimitHits": sum(
            bool(row.get("packet_limit_reached")) for row in batches
        ),
        "receiveBatchTimeLimitHits": sum(
            bool(row.get("time_limit_reached")) for row in batches
        ),
        "receiveBatchQueueDepthStart": distribution(
            int(row.get("queue_depth_start", 0))
            for row in batches
        ),
        "receiveBatchQueueDepthEnd": distribution(
            int(row.get("queue_depth_end", 0))
            for row in batches
        ),
        "transportTickGapUs": distribution(
            int(row.get("gap_us", 0))
            for row in ticks
            if int(row.get("gap_us", 0)) > 0
        ),
        "transportTickDurationUs": distribution(
            int(row.get("duration_us", 0)) for row in ticks
        ),
        "transportStageDurationUs": distribution(
            int(row.get("duration_us", 0)) for row in stages
        ),
        "transportStageMaximumUs": {
            stage: max(
                int(row.get("duration_us", 0))
                for row in stages
                if str(row.get("stage", "")) == stage
            )
            for stage in sorted(
                {
                    str(row.get("stage", ""))
                    for row in stages
                    if str(row.get("stage", ""))
                }
            )
        },
        "transportSendBurstCount": distribution(
            int(row.get("send_attempt_count", 0)) for row in ticks
        ),
        "transportSendBurstBytes": distribution(
            int(row.get("send_bytes", 0)) for row in ticks
        ),
        "worldApplyDurationUs": distribution(
            int(row.get("duration_us", 0)) for row in worlds
        ),
        "worldSnapshotAgeMs": distribution(
            int(row.get("snapshot_age_ms", 0))
            for row in worlds
            if bool(row.get("valid"))
        ),
        "worldApplyCreatedActors": distribution(
            int(row.get("created_actor_count", 0)) for row in worlds
        ),
        "holdingStaleCount": sum(
            bool(row.get("holding_stale")) for row in worlds
        ),
        "presentGapUs": distribution(
            int(row.get("gap_us", 0))
            for row in presents
            if int(row.get("gap_us", 0)) > 0
        ),
        "presentDurationUs": distribution(
            int(row.get("duration_us", 0)) for row in presents
        ),
        "hardPresentSpikeCount": sum(
            int(row.get("gap_us", 0)) >= HARD_SPIKE_THRESHOLD_US
            for row in presents
        ),
        "loggerMutexWaitUs": distribution(
            int(row.get("mutex_wait_us", 0)) for row in logger
        ),
        "loggerFlushUs": distribution(
            [
                *(
                    int(row.get("flush_us", 0))
                    for row in logger
                    if row.get("event") == "logger_write"
                ),
                *(
                    int(row.get("duration_us", 0))
                    for row in logger_flushes
                ),
            ]
        ),
        "loggerAsyncFlushUs": distribution(
            int(row.get("duration_us", 0))
            for row in logger_flushes
        ),
        "loggerQueueDepth": distribution(
            int(row.get("queue_depth", 0))
            for row in logger
            if row.get("event") == "logger_enqueue"
        ),
        "loggerDroppedLineCount": max(
            (
                int(row.get("dropped_line_count", 0))
                for row in (*logger, *logger_flushes)
            ),
            default=0,
        ),
        "loggerTotalUs": distribution(
            int(row.get("total_us", 0)) for row in logger
        ),
        "recoverySendCount": len(recovery_sends),
        "retransmitCount": sum(
            bool(row.get("retransmit")) for row in recovery_sends
        ),
        "recoveryPreviousSendAgeMs": distribution(
            int(row.get("previous_send_age_ms", 0))
            for row in recovery_sends
            if bool(row.get("retransmit"))
        ),
        "recoveryPendingCount": distribution(
            int(row.get("pending_count", 0))
            for row in recovery_sends
        ),
        "recoveryInFlightCount": distribution(
            int(row.get("in_flight_count", 0))
            for row in recovery_sends
        ),
        "recoverySendWindow": distribution(
            int(row.get("send_window", 0))
            for row in recovery_sends
        ),
        "recoveryAckCount": len(recovery_acks),
        "recoveryRetiredCount": sum(
            int(row.get("retired_count", 0))
            for row in recovery_acks
        ),
        "sendFailureCount": sum(
            int(row.get("result", 0)) < 0 for row in sends
        ),
        "oversizedDatagramCount": sum(
            int(
                row.get(
                    "largest_datagram_bytes",
                    row.get("bytes", 0),
                )
            )
            > PACKET_MTU_PAYLOAD_BYTES
            for row in sends
            if row.get("backend") == "local_udp"
        ),
        "transportFragmentedPacketCount": sum(
            bool(row.get("transport_fragmented"))
            for row in sends
            if row.get("backend") == "local_udp"
        ),
        "fragmentReceiveCount": len(fragments),
        "fragmentAssemblyCompleteCount": sum(
            bool(row.get("assembly_complete"))
            for row in fragments
        ),
        "ingressDropCount": len(ingress_drops),
        "largestDatagramBytes": max(
            (
                int(
                    row.get(
                        "largest_datagram_bytes",
                        row.get("bytes", 0),
                    )
                )
                for row in sends
            ),
            default=0,
        ),
        "largestDatagramByKind": largest_by_kind,
        "inferredMissingAtEnd": (
            int(receives[-1].get("cumulative_missing", 0))
            if receives
            else 0
        ),
        "reorderedAtEnd": (
            int(receives[-1].get("cumulative_reordered", 0))
            if receives
            else 0
        ),
        "duplicatesAtEnd": (
            int(receives[-1].get("cumulative_duplicates", 0))
            if receives
            else 0
        ),
    }


def _sequence_rows(
    events: Sequence[dict[str, Any]],
    event_name: str,
) -> dict[int, dict[str, Any]]:
    rows: dict[int, dict[str, Any]] = {}
    for row in event_rows(events, event_name):
        sequence = int(row.get("sequence", 0))
        if sequence <= 0:
            continue
        rows.setdefault(sequence, row)
    return rows


def correlate_sequences(
    sender_events: Sequence[dict[str, Any]],
    receiver_events: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    sends = _sequence_rows(sender_events, "packet_send")
    receives = _sequence_rows(receiver_events, "packet_receive")
    if not sends or not receives:
        return {
            "comparable": False,
            "sentInReceiveSpan": 0,
            "receivedInSpan": 0,
            "missingSequences": [],
            "missingCount": 0,
            "receiveWithoutSend": [],
        }

    first_received = min(receives)
    last_received = max(receives)
    sent_span = {
        sequence: row
        for sequence, row in sends.items()
        if first_received <= sequence <= last_received
    }
    received_span = {
        sequence: row
        for sequence, row in receives.items()
        if first_received <= sequence <= last_received
    }
    missing = sorted(set(sent_span) - set(received_span))
    unexplained_receive = sorted(set(received_span) - set(sent_span))
    missing_details = [
        {
            "sequence": sequence,
            "kind": int(sent_span[sequence].get("kind", 0)),
            "bytes": int(sent_span[sequence].get("bytes", 0)),
            "likelyFragmented": bool(
                sent_span[sequence].get("likely_fragmented")
            ),
            "transportFragmented": bool(
                sent_span[sequence].get("transport_fragmented")
            ),
            "largestDatagramBytes": int(
                sent_span[sequence].get(
                    "largest_datagram_bytes",
                    sent_span[sequence].get("bytes", 0),
                )
            ),
            "senderMonoUs": int(
                sent_span[sequence].get("mono_us", 0)
            ),
        }
        for sequence in missing
    ]
    return {
        "comparable": True,
        "firstReceivedSequence": first_received,
        "lastReceivedSequence": last_received,
        "sentInReceiveSpan": len(sent_span),
        "receivedInSpan": len(received_span),
        "missingCount": len(missing),
        "missingSequences": missing_details,
        "missingLikelyFragmentedCount": sum(
            row["likelyFragmented"] for row in missing_details
        ),
        "receiveWithoutSend": unexplained_receive,
    }


def _time_index(
    rows: Sequence[dict[str, Any]],
) -> tuple[list[int], list[dict[str, Any]]]:
    ordered = sorted(
        rows,
        key=lambda row: int(row.get("mono_us", 0)),
    )
    return (
        [int(row.get("mono_us", 0)) for row in ordered],
        ordered,
    )


def _rows_between(
    index: tuple[list[int], list[dict[str, Any]]],
    start_us: int,
    end_us: int,
) -> list[dict[str, Any]]:
    timestamps, rows = index
    start = bisect.bisect_left(timestamps, start_us)
    end = bisect.bisect_right(timestamps, end_us)
    return rows[start:end]


def classify_client_spikes(
    client_events: Sequence[dict[str, Any]],
    host_events: Sequence[dict[str, Any]],
    *,
    threshold_us: int = HARD_SPIKE_THRESHOLD_US,
) -> list[dict[str, Any]]:
    presents = event_rows(client_events, "present")
    receives = event_rows(client_events, "packet_receive")
    applies = event_rows(client_events, "packet_apply")
    batches = event_rows(client_events, "receive_batch")
    ticks = event_rows(client_events, "transport_tick")
    stages = event_rows(client_events, "transport_stage")
    worlds = event_rows(client_events, "world_apply")
    logger = logger_caller_rows(client_events)
    receive_index = _time_index(receives)
    apply_index = _time_index(applies)
    batch_index = _time_index(batches)
    tick_index = _time_index(ticks)
    stage_index = _time_index(stages)
    world_index = _time_index(worlds)
    logger_index = _time_index(logger)
    host_sends = _sequence_rows(host_events, "packet_send")
    spikes: list[dict[str, Any]] = []

    for present in presents:
        gap_us = int(present.get("gap_us", 0))
        if gap_us < threshold_us:
            continue
        end_us = int(present.get("mono_us", 0))
        start_us = max(0, end_us - gap_us)
        nearby_receives = _rows_between(
            receive_index,
            start_us - 50_000,
            end_us + 50_000,
        )
        nearby_applies = _rows_between(
            apply_index,
            start_us,
            end_us + 50_000,
        )
        nearby_batches = _rows_between(
            batch_index,
            start_us,
            end_us + 50_000,
        )
        nearby_ticks = _rows_between(
            tick_index,
            start_us,
            end_us + 50_000,
        )
        nearby_stages = _rows_between(
            stage_index,
            start_us,
            end_us + 50_000,
        )
        nearby_worlds = _rows_between(
            world_index,
            start_us,
            end_us + 50_000,
        )
        nearby_logs = _rows_between(
            logger_index,
            start_us,
            end_us + 50_000,
        )

        largest_arrival = max(
            (
                int(row.get("arrival_gap_us", 0))
                for row in nearby_receives
            ),
            default=0,
        )
        largest_apply = max(
            (
                int(row.get("duration_us", 0))
                for row in nearby_applies
            ),
            default=0,
        )
        largest_batch = max(
            (
                int(row.get("duration_us", 0))
                for row in nearby_batches
            ),
            default=0,
        )
        largest_tick = max(
            (
                int(row.get("duration_us", 0))
                for row in nearby_ticks
            ),
            default=0,
        )
        largest_tick_gap = max(
            (
                int(row.get("gap_us", 0))
                for row in nearby_ticks
            ),
            default=0,
        )
        slowest_stage = max(
            nearby_stages,
            key=lambda row: int(row.get("duration_us", 0)),
            default=None,
        )
        slowest_stage_name = (
            str(slowest_stage.get("stage", ""))
            if slowest_stage is not None
            else ""
        )
        slowest_stage_us = (
            int(slowest_stage.get("duration_us", 0))
            if slowest_stage is not None
            else 0
        )
        largest_world = max(
            (
                int(row.get("duration_us", 0))
                for row in nearby_worlds
            ),
            default=0,
        )
        largest_logger = max(
            (
                int(row.get("total_us", 0))
                for row in nearby_logs
            ),
            default=0,
        )
        recovery_batch = max(
            (
                int(row.get("packet_count", 0))
                for row in nearby_batches
            ),
            default=0,
        )
        largest_ingress_depth = max(
            (
                int(row.get("ingress_queue_depth", 0))
                for row in nearby_receives
            ),
            default=0,
        )
        largest_queue_age = max(
            (
                int(row.get("queue_age_us", 0))
                for row in nearby_applies
            ),
            default=0,
        )

        receive_edge = max(
            nearby_receives,
            key=lambda row: int(row.get("arrival_gap_us", 0)),
            default=None,
        )
        host_send_gap_us: int | None = None
        edge_sequence: int | None = None
        previous_sequence: int | None = None
        if receive_edge is not None:
            edge_sequence = int(receive_edge.get("sequence", 0))
            delta = int(receive_edge.get("sequence_delta", 0))
            if edge_sequence > 0 and delta > 0:
                previous_sequence = edge_sequence - delta
                current_send = host_sends.get(edge_sequence)
                previous_send = host_sends.get(previous_sequence)
                if current_send is not None and previous_send is not None:
                    host_send_gap_us = max(
                        0,
                        int(current_send.get("mono_us", 0))
                        - int(previous_send.get("mono_us", 0)),
                    )

        if largest_logger >= threshold_us // 2:
            stage = "blocking_log_write"
        elif largest_apply >= threshold_us // 2 or largest_batch >= threshold_us:
            stage = "receive_apply_stall"
        elif largest_world >= threshold_us // 2:
            stage = "world_apply_stall"
        elif slowest_stage_us >= threshold_us // 2:
            stage = f"transport_stage_stall:{slowest_stage_name}"
        elif (
            largest_arrival >= threshold_us
            and host_send_gap_us is not None
            and host_send_gap_us < threshold_us // 2
        ):
            stage = "receive_gap_with_host_send_continuity"
        elif (
            largest_tick_gap >= threshold_us
            and largest_arrival >= threshold_us
        ):
            stage = "app_thread_not_receiving"
        elif largest_tick >= threshold_us // 2:
            stage = "transport_tick_stall"
        else:
            stage = "render_present_stall"

        spikes.append(
            {
                "durationUs": gap_us,
                "clientMonoStartUs": start_us,
                "clientMonoEndUs": end_us,
                "stage": stage,
                "edgeSequence": edge_sequence,
                "previousSequence": previous_sequence,
                "clientReceiveGapUs": largest_arrival,
                "hostSendGapUs": host_send_gap_us,
                "maxPacketApplyUs": largest_apply,
                "maxReceiveBatchUs": largest_batch,
                "recoveryBatchPackets": recovery_batch,
                "maxIngressQueueDepth": largest_ingress_depth,
                "maxPacketQueueAgeUs": largest_queue_age,
                "maxTransportTickUs": largest_tick,
                "maxTransportTickGapUs": largest_tick_gap,
                "slowestTransportStage": slowest_stage_name,
                "maxTransportStageUs": slowest_stage_us,
                "maxWorldApplyUs": largest_world,
                "maxLoggerWriteUs": largest_logger,
                "holdingStaleObserved": any(
                    bool(row.get("holding_stale"))
                    for row in nearby_worlds
                ),
            }
        )
    return spikes


def classify_client_transport_stalls(
    client_events: Sequence[dict[str, Any]],
    host_events: Sequence[dict[str, Any]],
    *,
    threshold_us: int = HARD_SPIKE_THRESHOLD_US,
) -> list[dict[str, Any]]:
    receives = event_rows(client_events, "packet_receive")
    applies = event_rows(client_events, "packet_apply")
    batches = event_rows(client_events, "receive_batch")
    ticks = event_rows(client_events, "transport_tick")
    worlds = event_rows(client_events, "world_apply")
    presents = event_rows(client_events, "present")
    logger = logger_caller_rows(client_events)
    apply_index = _time_index(applies)
    batch_index = _time_index(batches)
    tick_index = _time_index(ticks)
    world_index = _time_index(worlds)
    present_index = _time_index(presents)
    logger_index = _time_index(logger)
    host_sends = _sequence_rows(host_events, "packet_send")
    stalls: list[dict[str, Any]] = []

    for received in receives:
        arrival_gap_us = int(received.get("arrival_gap_us", 0))
        if arrival_gap_us < threshold_us:
            continue
        sequence = int(received.get("sequence", 0))
        sequence_delta = int(received.get("sequence_delta", 0))
        previous_sequence = (
            sequence - sequence_delta
            if sequence > 0 and 0 < sequence_delta <= sequence
            else None
        )
        sender_span: list[dict[str, Any]] = []
        if previous_sequence is not None:
            sender_span = [
                row
                for candidate, row in host_sends.items()
                if previous_sequence <= candidate <= sequence
            ]
            sender_span.sort(
                key=lambda row: int(row.get("mono_us", 0))
            )
        sender_intervals = [
            int(current.get("mono_us", 0))
            - int(previous.get("mono_us", 0))
            for previous, current in zip(
                sender_span,
                sender_span[1:],
                strict=False,
            )
        ]
        host_span_us = (
            int(sender_span[-1].get("mono_us", 0))
            - int(sender_span[0].get("mono_us", 0))
            if len(sender_span) >= 2
            else None
        )
        host_max_send_gap_us = (
            max(sender_intervals)
            if sender_intervals
            else None
        )
        client_end_us = int(received.get("mono_us", 0))
        client_start_us = max(0, client_end_us - arrival_gap_us)
        nearby_start = client_start_us - 50_000
        nearby_end = client_end_us + 100_000
        nearby_applies = _rows_between(
            apply_index, nearby_start, nearby_end
        )
        nearby_batches = _rows_between(
            batch_index, nearby_start, nearby_end
        )
        nearby_ticks = _rows_between(
            tick_index, nearby_start, nearby_end
        )
        nearby_worlds = _rows_between(
            world_index, nearby_start, nearby_end
        )
        nearby_presents = _rows_between(
            present_index, nearby_start, nearby_end
        )
        nearby_logger = _rows_between(
            logger_index, nearby_start, nearby_end
        )

        max_apply_us = max(
            (
                int(row.get("duration_us", 0))
                for row in nearby_applies
            ),
            default=0,
        )
        max_batch_us = max(
            (
                int(row.get("duration_us", 0))
                for row in nearby_batches
            ),
            default=0,
        )
        recovery_batch_packets = max(
            (
                int(row.get("packet_count", 0))
                for row in nearby_batches
            ),
            default=0,
        )
        max_tick_gap_us = max(
            (
                int(row.get("gap_us", 0))
                for row in nearby_ticks
            ),
            default=0,
        )
        max_world_us = max(
            (
                int(row.get("duration_us", 0))
                for row in nearby_worlds
            ),
            default=0,
        )
        max_present_gap_us = max(
            (
                int(row.get("gap_us", 0))
                for row in nearby_presents
            ),
            default=0,
        )
        max_logger_us = max(
            (
                int(row.get("total_us", 0))
                for row in nearby_logger
            ),
            default=0,
        )
        sender_continuous = (
            host_span_us is not None
            and host_span_us >= threshold_us
            and host_max_send_gap_us is not None
            and host_max_send_gap_us < threshold_us // 2
        )
        if max_logger_us >= threshold_us // 2:
            stage = "blocking_log_write"
        elif max_batch_us >= threshold_us or max_apply_us >= threshold_us // 2:
            stage = "catch_up_apply"
        elif max_world_us >= threshold_us // 2:
            stage = "world_apply"
        elif sender_continuous:
            stage = (
                "client_app_thread_gap"
                if max_tick_gap_us >= threshold_us
                else "network_receive_gap"
            )
        else:
            stage = "sender_or_network_idle"

        if stage == "sender_or_network_idle":
            continue

        expected_sender_sequences = {
            candidate
            for candidate in host_sends
            if previous_sequence is not None
            and previous_sequence < candidate < sequence
        }
        stalls.append(
            {
                "durationUs": arrival_gap_us,
                "stage": stage,
                "sequence": sequence,
                "previousSequence": previous_sequence,
                "sequenceDelta": sequence_delta,
                "missingBefore": int(
                    received.get("missing_before", 0)
                ),
                "senderPacketsInSpan": len(sender_span),
                "senderSpanUs": host_span_us,
                "senderMaxInterSendGapUs": host_max_send_gap_us,
                "senderContinuous": sender_continuous,
                "missingSenderSequencesInGap": len(
                    expected_sender_sequences
                ),
                "missingLikelyFragmentedInGap": sum(
                    int(
                        host_sends[candidate].get(
                            "largest_datagram_bytes",
                            host_sends[candidate].get(
                                "bytes", 0
                            ),
                        )
                    ) > PACKET_MTU_PAYLOAD_BYTES
                    for candidate in expected_sender_sequences
                ),
                "recoveryBatchPackets": recovery_batch_packets,
                "maxPacketApplyUs": max_apply_us,
                "maxReceiveBatchUs": max_batch_us,
                "maxTransportTickGapUs": max_tick_gap_us,
                "maxWorldApplyUs": max_world_us,
                "maxPresentGapUs": max_present_gap_us,
                "maxLoggerWriteUs": max_logger_us,
                "holdingStaleObserved": any(
                    bool(row.get("holding_stale"))
                    for row in nearby_worlds
                ),
            }
        )
    return stalls


def analyze_pair(
    host_path: Path,
    client_path: Path,
) -> dict[str, Any]:
    host_events = load_jsonl(host_path)
    client_events = load_jsonl(client_path)
    host_to_client = correlate_sequences(host_events, client_events)
    client_to_host = correlate_sequences(client_events, host_events)
    return {
        "hostTelemetry": str(host_path),
        "clientTelemetry": str(client_path),
        "host": summarize_telemetry(host_events),
        "client": summarize_telemetry(client_events),
        "hostToClient": host_to_client,
        "clientToHost": client_to_host,
        "clientSpikes": classify_client_spikes(
            client_events,
            host_events,
        ),
        "clientTransportStalls": classify_client_transport_stalls(
            client_events,
            host_events,
        ),
    }


PAIR_PROBE = r"""
local output = {}
local function emit(key, value)
  table.insert(
    output,
    key .. "=" .. tostring(value == nil and "" or value))
end
local function safe(callable, fallback)
  local ok, value = pcall(callable)
  if ok then return value end
  return fallback
end

local scene = sd.world.get_scene() or {}
local wave = sd.waves.get_state() or {}
local multiplayer = sd.runtime.get_multiplayer_state() or {}
local player = sd.player.get_state() or {}
local replicated = sd.world.get_replicated_actors() or {}
local debug = rawget(_G, "bot_brain_debug") or {}

emit("scene", scene.name or scene.kind or "")
emit("authority", sd.state.is_authority())
emit("wave.number", wave.wave or 0)
emit("wave.phase", wave.phase or "")
emit("wave.planned", wave.planned or 0)
emit("wave.remaining", wave.remaining_to_spawn or 0)
emit("wave.spawned", wave.spawned or 0)
emit("wave.alive", wave.alive or 0)
emit("wave.killed", wave.killed or 0)
emit("local.player_id", multiplayer.local_steam_id or 0)
emit("local.hp", player.hp or 0)
emit("local.max_hp", player.max_hp or 0)
emit("local.mp", player.mp or 0)
emit("local.max_mp", player.max_mp or 0)
emit("local.x", player.x or 0)
emit("local.y", player.y or 0)

local player_actor = tonumber(player.actor_address) or 0
local hit_primary_offset = sd.debug.layout_offset(
  "actor_hit_reaction_primary_alpha")
local hit_intensity_offset = sd.debug.layout_offset(
  "actor_hit_reaction_intensity")
local hit_secondary_offset = sd.debug.layout_offset(
  "actor_hit_reaction_secondary_alpha")
emit("local.hit_primary",
  player_actor ~= 0 and hit_primary_offset ~= nil and
    sd.debug.read_float(player_actor + hit_primary_offset) or 0)
emit("local.hit_intensity",
  player_actor ~= 0 and hit_intensity_offset ~= nil and
    sd.debug.read_float(player_actor + hit_intensity_offset) or 0)
emit("local.hit_secondary",
  player_actor ~= 0 and hit_secondary_offset ~= nil and
    sd.debug.read_float(player_actor + hit_secondary_offset) or 0)

local participants = multiplayer.participants or {}
emit("participant.count", #participants)
for index, participant in ipairs(participants) do
  if index > 4 then break end
  local prefix = "participant." .. tostring(index) .. "."
  local transport_id = tonumber(participant.steam_id) or 0
  emit(prefix .. "id",
    transport_id ~= 0 and transport_id or
      participant.participant_id or 0)
  emit(prefix .. "name", participant.name or "")
  emit(prefix .. "controller", participant.controller_kind or "")
  emit(prefix .. "is_bot",
    participant.controller_kind == "LuaBrain")
  emit(prefix .. "connected", participant.transport_connected or false)
  emit(prefix .. "in_run", participant.in_run or false)
  emit(prefix .. "run_nonce", participant.run_nonce or 0)
  emit(prefix .. "life", participant.life_current or 0)
  emit(prefix .. "max_life", participant.life_max or 0)
  emit(prefix .. "mana", participant.mana_current or 0)
  emit(prefix .. "max_mana", participant.mana_max or 0)
end

local debug_by_id = {}
for _, row in ipairs(debug.bots or {}) do
  debug_by_id[tonumber(row.participant_id) or 0] = row
end
local bots = sd.bots.list() or {}
emit("bot.count", #bots)
for index, handle in ipairs(bots) do
  if index > 4 then break end
  local participant_id =
    safe(function() return tonumber(handle:participant_id()) end, 0) or 0
  local state = sd.bots.get_participant_state(participant_id) or {}
  local profile = state.profile or {}
  local row = debug_by_id[participant_id] or {}
  local prefix = "bot." .. tostring(index) .. "."
  emit(prefix .. "id", participant_id)
  emit(prefix .. "name", state.name or "")
  emit(prefix .. "element", profile.element_id or -1)
  emit(prefix .. "discipline", profile.discipline_id or -1)
  emit(prefix .. "slot", state.gameplay_slot or -1)
  emit(prefix .. "materialized", state.entity_materialized or false)
  emit(prefix .. "alive",
    safe(function() return handle:alive() end, false))
  emit(prefix .. "hp", safe(function() return handle:hp() end, 0))
  emit(prefix .. "max_hp",
    safe(function() return handle:max_hp() end, 0))
  emit(prefix .. "x", state.x or 0)
  emit(prefix .. "y", state.y or 0)
  emit(prefix .. "mode", row.mode or "")
  emit(prefix .. "cast_issued", row.cast_issued or 0)
  emit(prefix .. "cast_accepted", row.cast_accepted or 0)
  emit(prefix .. "target", row.target_network_actor_id or 0)
  emit(prefix .. "last_error", row.last_error or "")
end
emit("brain.active", debug.active_bot_count or -1)
emit("brain.desired", debug.desired_bot_count or -1)
emit("brain.respawn_actions", debug.respawn_action_count or 0)

emit("replicated.valid", replicated.valid or false)
emit("replicated.sequence", replicated.sequence or 0)
emit("replicated.actor_count", replicated.actor_count or 0)
emit("replicated.apply_valid", replicated.apply_valid or false)
emit("replicated.holding_stale",
  replicated.holding_stale_snapshot or false)
emit("replicated.source_age_ms",
  replicated.source_snapshot_age_ms or 0)
local live_enemies = 0
local enemy_index = 0
for _, actor in ipairs(replicated.actors or {}) do
  if actor.tracked_enemy == true then
    enemy_index = enemy_index + 1
    if actor.dead ~= true and (tonumber(actor.hp) or 0) > 0 then
      live_enemies = live_enemies + 1
    end
    if enemy_index <= 16 then
      local prefix = "enemy." .. tostring(enemy_index) .. "."
      emit(prefix .. "id", actor.network_actor_id or 0)
      emit(prefix .. "dead", actor.dead or false)
      emit(prefix .. "x", actor.x or actor.position_x or 0)
      emit(prefix .. "y", actor.y or actor.position_y or 0)
      emit(prefix .. "hp", actor.hp or 0)
      emit(prefix .. "max_hp", actor.max_hp or 0)
      emit(prefix .. "target", actor.target_participant_id or 0)
    end
  end
end
emit("enemy.count", enemy_index)
emit("enemy.live", live_enemies)

local offer = multiplayer.active_level_up_offer or {}
emit("offer.valid", offer.valid or false)
emit("offer.submitted", offer.selection_submitted or false)
emit("offer.id", offer.offer_id or 0)
emit("offer.target", offer.target_participant_id or 0)
emit("offer.count", offer.option_count or 0)
for index, option in ipairs(offer.options or {}) do
  emit("offer.option." .. tostring(index),
    option.option_id or option.id or -1)
end
return table.concat(output, "\n")
"""

SCENE_PROBE = r"""
local scene = sd.world.get_scene() or {}
print("scene=" .. tostring(scene.name or scene.kind or ""))
"""

UI_NAVIGATION_PROBE = r"""
local scene = sd.world.get_scene() or {}
local snapshot = sd.ui.get_snapshot() or {}
local actions = {}
for _, element in ipairs(snapshot.elements or {}) do
  local action = tostring(element.action_id or "")
  if action ~= "" then
    actions[action] = true
  end
end
local ordered = {}
for action in pairs(actions) do
  table.insert(ordered, action)
end
table.sort(ordered)
print("scene=" .. tostring(scene.name or scene.kind or ""))
print("surface=" .. tostring(snapshot.surface_id or ""))
print("actions=" .. table.concat(ordered, ","))
"""

WAVE_START_PROBE = r"""
local wave = sd.waves.get_state() or {}
local combat = sd.gameplay.get_combat_state() or {}
print("wave.number=" .. tostring(wave.wave or 0))
print("wave.phase=" .. tostring(wave.phase or ""))
print("combat.available=" .. tostring(next(combat) ~= nil))
print("combat.wave_index=" .. tostring(combat.wave_index or 0))
print("combat.active=" .. tostring(combat.active or false))
print("combat.wait_ticks=" .. tostring(combat.wait_ticks or 0))
print("combat.wave_counter=" .. tostring(combat.wave_counter or 0))
print("combat.started_music=" ..
  tostring(combat.started_music or false))
print("combat.transition_requested=" ..
  tostring(combat.transition_requested or false))
"""

SOLOMON_DIG_FLOW_PROBE = r"""
local function emit(key, value)
  print(key .. "=" .. tostring(value))
end
local flow = rawget(_G, "__netlag_solomon_dig") or {}
emit("armed", flow.armed == true)
emit("samples", flow.samples or 0)
emit("seen", flow.seen == true)
emit("placed", flow.placed == true)
emit("write_x", flow.write_x == true)
emit("write_y", flow.write_y == true)
emit("rebind", flow.rebind == true)
emit("error", flow.error or "")
emit("actor", flow.actor or 0)
emit("x", flow.x or 0)
emit("y", flow.y or 0)
emit("state", flow.state or -1)
emit("max_state", flow.max_state or -1)
emit("acquired", flow.acquired == true)
emit("target_slot", flow.target_slot or -1)
emit("player_before_x", flow.player_before_x or 0)
emit("player_before_y", flow.player_before_y or 0)
emit("player_after_x", flow.player_after_x or 0)
emit("player_after_y", flow.player_after_y or 0)
"""

SOLOMON_DIG_PROBE = r"""
local function offset(name)
  return sd.debug.layout_offset(name)
end
local function read_i32(actor, name, fallback)
  local value_offset = offset(name)
  if actor == 0 or value_offset == nil then return fallback end
  return tonumber(sd.debug.read_i32(actor + value_offset)) or fallback
end
local function read_u8(actor, name, fallback)
  local value_offset = offset(name)
  if actor == 0 or value_offset == nil then return fallback end
  return tonumber(sd.debug.read_u8(actor + value_offset)) or fallback
end
local function read_float(actor, name)
  local value_offset = offset(name)
  if actor == 0 or value_offset == nil then return 0 end
  return tonumber(sd.debug.read_float(actor + value_offset)) or 0
end
local solomon = 0
for _, actor in ipairs(sd.world.list_actors() or {}) do
  if tonumber(actor.object_type_id) == 0x1391 then
    solomon = tonumber(actor.actor_address) or 0
    break
  end
end
local observer = rawget(_G, "__netlag_solomon_dig") or {}
local wave = sd.waves.get_state() or {}
print("solomon.actor=" .. tostring(solomon))
print("solomon.x=" .. tostring(
  read_float(solomon, "actor_position_x")))
print("solomon.y=" .. tostring(
  read_float(solomon, "actor_position_y")))
print("solomon.state=" .. tostring(read_i32(
  solomon, "solomon_dig_interaction_state", -1)))
print("solomon.acquired=" .. tostring(read_u8(
  solomon, "solomon_dig_participant_acquired", 0)))
print("solomon.target_slot=" .. tostring(read_i32(
  solomon, "solomon_dig_target_gameplay_slot", -1)))
print("observer.seen=" .. tostring(observer.seen or false))
print("observer.acquired=" ..
  tostring(observer.acquired or false))
print("observer.target_slot=" ..
  tostring(observer.target_slot or -1))
print("observer.max_state=" ..
  tostring(observer.max_state or -1))
print("wave.number=" .. tostring(wave.wave or 0))
"""

@dataclass(frozen=True)
class Peer:
    location: Location
    role: Role
    instance: str
    local_port: int
    remote_host: str
    remote_port: int
    participant_id_text: str
    participant_id: int
    player_name: str
    element: str
    discipline: str

    @property
    def pipe_name(self) -> str:
        return f"SolomonDarkModLoader_LuaExec_{self.instance}"


def direction_peers(
    config: HarnessConfig,
    direction: Direction,
    instance_prefix: str = "netlag",
) -> tuple[Peer, Peer]:
    if not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9._-]{0,39}",
        instance_prefix,
    ):
        raise VerificationFailure(
            f"Unsafe or overlong instance prefix: {instance_prefix!r}"
        )
    if direction == "a":
        host = Peer(
            location="local",
            role="host",
            instance=f"{instance_prefix}-host",
            local_port=config.local_host_port,
            remote_host=config.remote_public_host,
            remote_port=config.remote_client_port,
            participant_id_text=HOST_PARTICIPANT_ID_TEXT,
            participant_id=HOST_PARTICIPANT_ID,
            player_name=HOST_NAME,
            element="fire",
            discipline="mind",
        )
        client = Peer(
            location="remote",
            role="client",
            instance=f"{instance_prefix}-client",
            local_port=config.remote_client_port,
            remote_host=config.local_public_host,
            remote_port=config.local_host_port,
            participant_id_text=CLIENT_PARTICIPANT_ID_TEXT,
            participant_id=CLIENT_PARTICIPANT_ID,
            player_name=CLIENT_NAME,
            element="water",
            discipline="arcane",
        )
    elif direction == "b":
        host = Peer(
            location="remote",
            role="host",
            instance=f"{instance_prefix}-host",
            local_port=config.remote_host_port,
            remote_host=config.local_public_host,
            remote_port=config.local_client_port,
            participant_id_text=HOST_PARTICIPANT_ID_TEXT,
            participant_id=HOST_PARTICIPANT_ID,
            player_name=HOST_NAME,
            element="fire",
            discipline="mind",
        )
        client = Peer(
            location="local",
            role="client",
            instance=f"{instance_prefix}-client",
            local_port=config.local_client_port,
            remote_host=config.remote_public_host,
            remote_port=config.remote_host_port,
            participant_id_text=CLIENT_PARTICIPANT_ID_TEXT,
            participant_id=CLIENT_PARTICIPANT_ID,
            player_name=CLIENT_NAME,
            element="water",
            discipline="arcane",
        )
    else:
        raise VerificationFailure(f"Unsupported matrix direction: {direction}")
    return host, client


def local_instance_root(config: HarnessConfig, peer: Peer) -> Path:
    return (
        config.local_runtime_root
        / "instances"
        / peer.instance.casefold()
    )


def local_stage_root(config: HarnessConfig, peer: Peer) -> Path:
    return local_instance_root(config, peer) / "stage"


def local_process_ledger(
    session_directory: Path,
    peer: Peer,
) -> Path:
    return session_directory / f"{peer.role}-local-process.json"


_LOCAL_LAUNCH_WRAPPERS: dict[
    tuple[str, str],
    subprocess.Popen[str],
] = {}


def close_local_launch_wrapper(
    session_directory: Path,
    peer: Peer,
) -> None:
    key = (str(session_directory), peer.instance)
    process = _LOCAL_LAUNCH_WRAPPERS.pop(key, None)
    if process is None:
        return
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


def settings_path(config: HarnessConfig, role: Role) -> Path:
    return (
        config.evidence_root
        / "staging"
        / "tools"
        / f"bot-settings-{role}.json"
    )


def launch_local_peer(
    config: HarnessConfig,
    peer: Peer,
    session_directory: Path,
) -> dict[str, Any]:
    if peer.location != "local":
        raise VerificationFailure("launch_local_peer received a remote peer.")
    ledger = local_process_ledger(session_directory, peer)
    command = [
        "powershell.exe",
        "-NoProfile",
        "-NonInteractive",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        windows_path(LOCAL_LAUNCH_SCRIPT),
        "-Role",
        peer.role,
        "-LocalPort",
        str(peer.local_port),
        "-RemoteHost",
        peer.remote_host,
        "-RemotePort",
        str(peer.remote_port),
        "-ParticipantId",
        peer.participant_id_text,
        "-PlayerName",
        peer.player_name,
        "-Instance",
        peer.instance,
        "-GameDirectory",
        windows_path(config.local_game_root),
        "-RuntimeRoot",
        windows_path(config.local_runtime_root),
        "-LauncherPath",
        windows_path(config.local_launcher),
        "-BotSettingsPath",
        windows_path(settings_path(config, peer.role)),
        "-ProcessIdOutputPath",
        windows_path(ledger),
        "-Element",
        peer.element,
        "-Discipline",
        peer.discipline,
    ]
    launch_log = (
        session_directory / f"{peer.role}-local-launch.log"
    )
    stream = launch_log.open(
        "x",
        encoding="utf-8",
        newline="\n",
    )
    try:
        process = subprocess.Popen(
            command,
            cwd=ROOT,
            stdout=stream,
            stderr=subprocess.STDOUT,
            text=True,
        )
    finally:
        stream.close()
    key = (str(session_directory), peer.instance)
    _LOCAL_LAUNCH_WRAPPERS[key] = process
    deadline = time.monotonic() + 120
    while time.monotonic() < deadline:
        if ledger.is_file():
            try:
                return json.loads(
                    ledger.read_text(encoding="utf-8")
                )
            except json.JSONDecodeError:
                pass
        return_code = process.poll()
        if return_code is not None:
            raise VerificationFailure(
                "Local launcher exited before writing its exact "
                f"process ledger (exit {return_code}): "
                f"{launch_log.read_text(
                    encoding='utf-8', errors='replace')!r}"
            )
        time.sleep(0.1)
    raise VerificationFailure(
        "Local launcher did not write its exact process ledger "
        f"within 120 seconds: {launch_log.read_text(
            encoding='utf-8', errors='replace')!r}"
    )


def launch_remote_peer(
    config: HarnessConfig,
    peer: Peer,
) -> dict[str, Any]:
    if peer.location != "remote":
        raise VerificationFailure("launch_remote_peer received a local peer.")
    output = remote_helper(
        config,
        "launch",
        peer.role,
        str(peer.local_port),
        peer.remote_host,
        str(peer.remote_port),
        peer.participant_id_text,
        peer.player_name,
        peer.instance,
        peer.element,
        peer.discipline,
        timeout=30,
    )
    rows = [line for line in output.splitlines() if line.startswith("{")]
    if not rows:
        raise VerificationFailure(
            f"Remote launcher returned no JSON: {output!r}"
        )
    return json.loads(rows[-1])


def launch_peer(
    config: HarnessConfig,
    peer: Peer,
    session_directory: Path,
) -> dict[str, Any]:
    if peer.location == "local":
        return launch_local_peer(config, peer, session_directory)
    return launch_remote_peer(config, peer)


def stop_local_peer(
    session_directory: Path,
    peer: Peer,
) -> dict[str, Any]:
    ledger = local_process_ledger(session_directory, peer)
    if not ledger.is_file():
        close_local_launch_wrapper(session_directory, peer)
        return {"skipped": True, "reason": "ledger_missing"}
    try:
        output = run_checked(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                windows_path(LOCAL_STOP_SCRIPT),
                "-ProcessLedgerPath",
                windows_path(ledger),
            ],
            timeout=30,
        )
    finally:
        close_local_launch_wrapper(session_directory, peer)
    rows = [line for line in output.splitlines() if line.startswith("{")]
    return json.loads(rows[-1]) if rows else {"raw": output}


def lua(
    config: HarnessConfig,
    peer: Peer,
    code: str,
    *,
    target_mod_id: str = "",
) -> str:
    if target_mod_id:
        if not re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}",
            target_mod_id,
        ):
            raise VerificationFailure(
                f"Invalid Lua exec target mod id: {target_mod_id!r}"
            )
        code = (
            LUA_EXEC_TARGET_DIRECTIVE +
            target_mod_id +
            "\n" +
            code
        )
    if peer.location == "local":
        return unwrap_lua_exec_response(
            local_lua(config, peer, code)
        )
    return unwrap_lua_exec_response(
        remote_lua(config, peer, code)
    )


def peer_values(
    config: HarnessConfig,
    peer: Peer,
    code: str | None = None,
) -> dict[str, str]:
    target_mod_id = ""
    if code is None:
        code = PAIR_PROBE
        target_mod_id = BOT_BRAIN_MOD_ID
    return parse_key_values(
        lua(
            config,
            peer,
            code,
            target_mod_id=target_mod_id,
        )
    )


def activate_ui_action(
    config: HarnessConfig,
    peer: Peer,
    action: str,
    surface: str,
) -> dict[str, str]:
    requested = parse_key_values(
        lua(
            config,
            peer,
            f"""
local ok, request = sd.ui.activate_action(
  {json.dumps(action)}, {json.dumps(surface)})
print("ok=" .. tostring(ok))
print("request=" .. tostring(request or 0))
""",
        )
    )
    if requested.get("ok") != "true":
        raise VerificationFailure(
            f"Semantic UI action {action!r} failed on "
            f"{peer.role}: {requested}"
        )
    request = integer(requested, "request")
    if request <= 0:
        raise VerificationFailure(
            f"Semantic UI action {action!r} returned no request "
            f"on {peer.role}: {requested}"
        )
    completed = wait_for(
        lambda: parse_key_values(
            lua(
                config,
                peer,
                f"""
local dispatch = sd.ui.get_action_dispatch({request}) or {{}}
print("status=" .. tostring(dispatch.status or ""))
print("error=" .. tostring(dispatch.error_message or ""))
""",
            )
        ),
        lambda values: values.get("status") not in (
            "",
            "queued",
            "dispatching",
        ),
        label=f"{peer.role} semantic UI action {action}",
        timeout=10,
        interval=0.1,
    )
    if completed.get("status") == "failed":
        raise VerificationFailure(
            f"Semantic UI action {action!r} failed on "
            f"{peer.role}: {completed}"
        )
    return {
        **requested,
        "status": completed.get("status", ""),
    }


def create_selection_values(
    config: HarnessConfig,
    peer: Peer,
    action: str = "",
) -> dict[str, str]:
    return parse_key_values(
        lua(
            config,
            peer,
            f"""
local function emit(key, value)
  print(key .. "=" .. tostring(value == nil and "" or value))
end
local scene = sd.world.get_scene() or {{}}
local snapshot = sd.ui.get_snapshot() or {{}}
local owner = 0
for _, element in ipairs(snapshot.elements or {{}}) do
  if element.surface_id == "create" or
      element.surface_root_id == "create" then
    owner = tonumber(element.surface_object_ptr) or 0
    break
  end
end
local function read_u32(offset)
  if owner == 0 then return nil end
  local ok, value = pcall(sd.debug.read_u32, owner + offset)
  return ok and tonumber(value) or nil
end
local function read_u8(offset)
  local value = read_u32(offset)
  return value == nil and nil or value % 256
end
local action_id = {json.dumps(action)}
local found = action_id ~= "" and
  sd.ui.find_action(action_id, "create") or nil
emit("scene", scene.name or scene.kind or "")
emit("surface", snapshot.surface_id or "")
emit("owner", owner)
emit("element.enabled", read_u8(0x18C))
emit("element.selected", read_u32(0x1A4))
emit("discipline.enabled", read_u8(0x228))
emit("discipline.selected", read_u32(0x22C))
emit("action.found", found ~= nil)
emit("action.enabled", found and found.enabled or false)
emit("action.interactive", found and found.interactive or false)
""",
        )
    )


def selection_unset(value: str | None) -> bool:
    return value in (None, "", "-1", "4294967295")


def enter_hub_through_stock_ui(
    config: HarnessConfig,
    peer: Peer,
) -> dict[str, Any]:
    navigation: list[dict[str, str]] = []
    navigation_surface = ""
    dispatched_on_surface: set[str] = set()
    deadline = time.monotonic() + 45
    last: dict[str, str] = {}
    last_action_error = ""
    while time.monotonic() < deadline:
        try:
            last = peer_values(
                config,
                peer,
                UI_NAVIGATION_PROBE,
            )
            last_action_error = ""
        except VerificationFailure as error:
            last_action_error = str(error)
            time.sleep(0.1)
            continue
        if last.get("scene") == "hub":
            return {
                "navigation": navigation,
                "selection": "already-in-hub",
            }
        if last.get("surface") == "create":
            break
        actions = set(filter(None, last.get("actions", "").split(",")))
        candidate = ""
        surface = last.get("surface", "")
        if surface != navigation_surface:
            navigation_surface = surface
            dispatched_on_surface.clear()
        if (
            surface == "control_scheme_picker"
            and "control_scheme_picker.select_wasd" in actions
            and "control_scheme_picker.select_wasd"
            not in dispatched_on_surface
        ):
            candidate = "control_scheme_picker.select_wasd"
        elif (
            surface == "dialog"
            and "dialog.primary" in actions
            and "dialog.primary" not in dispatched_on_surface
        ):
            candidate = "dialog.primary"
        elif surface == "main_menu":
            if (
                "main_menu.play" in actions
                and "main_menu.play" not in dispatched_on_surface
            ):
                candidate = "main_menu.play"
            elif (
                "main_menu.new_game" in actions
                and "main_menu.new_game" not in dispatched_on_surface
            ):
                candidate = "main_menu.new_game"
        if candidate:
            try:
                navigation.append(
                    activate_ui_action(
                        config,
                        peer,
                        candidate,
                        surface,
                    )
                )
                dispatched_on_surface.add(candidate)
                last_action_error = ""
            except VerificationFailure as error:
                last_action_error = str(error)
        time.sleep(0.1)
    else:
        raise VerificationFailure(
            f"{peer.role} did not reach the stock create surface: "
            f"{last}; last_action_error={last_action_error!r}"
        )

    element_ids = {
        "ether": 0,
        "fire": 1,
        "air": 2,
        "water": 3,
        "earth": 4,
    }
    discipline_ids = {
        "mind": 0,
        "body": 1,
        "arcane": 2,
    }
    element_action = f"create.select_element_{peer.element}"
    element_ready = wait_for(
        lambda: create_selection_values(
            config,
            peer,
            element_action,
        ),
        lambda values: (
            integer(values, "owner") > 0
            and integer(values, "element.enabled") != 0
            and selection_unset(values.get("element.selected"))
            and values.get("surface") == "create"
            and values.get("action.found") == "true"
        ),
        label=f"{peer.role} stock element selection",
        timeout=30,
    )
    element_dispatch = activate_ui_action(
        config,
        peer,
        element_action,
        "create",
    )
    element_latched = wait_for(
        lambda: create_selection_values(config, peer),
        lambda values: (
            integer(values, "element.selected", -1)
            == element_ids[peer.element]
            and integer(values, "discipline.enabled") != 0
        ),
        label=f"{peer.role} stock element latch",
        timeout=10,
    )

    discipline_action = (
        f"create.select_discipline_{peer.discipline}"
    )
    discipline_ready = wait_for(
        lambda: create_selection_values(
            config,
            peer,
            discipline_action,
        ),
        lambda values: (
            integer(values, "owner") > 0
            and integer(values, "discipline.enabled") != 0
            and selection_unset(values.get("discipline.selected"))
            and values.get("surface") == "create"
            and values.get("action.found") == "true"
        ),
        label=f"{peer.role} stock discipline selection",
        timeout=30,
    )
    discipline_dispatch = activate_ui_action(
        config,
        peer,
        discipline_action,
        "create",
    )
    accepted = wait_for(
        lambda: create_selection_values(config, peer),
        lambda values: (
            values.get("scene") == "hub"
            or values.get("surface") != "create"
            or integer(values, "discipline.selected", -1)
            == discipline_ids[peer.discipline]
        ),
        label=f"{peer.role} stock discipline acceptance",
        timeout=15,
    )
    return {
        "navigation": navigation,
        "elementReady": element_ready,
        "elementDispatch": element_dispatch,
        "elementLatched": element_latched,
        "disciplineReady": discipline_ready,
        "disciplineDispatch": discipline_dispatch,
        "accepted": accepted,
    }


def wait_for(
    operation: Callable[[], Any],
    predicate: Callable[[Any], bool],
    *,
    label: str,
    timeout: float,
    interval: float = 0.25,
) -> Any:
    deadline = time.monotonic() + timeout
    last: Any = None
    last_error = ""
    while time.monotonic() < deadline:
        try:
            last = operation()
            last_error = ""
            if predicate(last):
                return last
        except (
            VerificationFailure,
            json.JSONDecodeError,
            OSError,
            subprocess.SubprocessError,
        ) as error:
            last_error = str(error)
        time.sleep(interval)
    raise VerificationFailure(
        f"Timed out waiting for {label}; last={last!r}; "
        f"last_error={last_error!r}"
    )


def participant_rows(
    values: dict[str, str],
) -> dict[int, dict[str, Any]]:
    rows: dict[int, dict[str, Any]] = {}
    for index in range(1, integer(values, "participant.count") + 1):
        prefix = f"participant.{index}."
        participant_id = integer(values, prefix + "id")
        if participant_id <= 0:
            continue
        rows[participant_id] = {
            "name": values.get(prefix + "name", ""),
            "controller": values.get(prefix + "controller", ""),
            "isBot": boolean(values, prefix + "is_bot"),
            "connected": boolean(values, prefix + "connected"),
            "inRun": boolean(values, prefix + "in_run"),
            "runNonce": integer(values, prefix + "run_nonce"),
            "life": number(values, prefix + "life", 0.0),
            "maxLife": number(values, prefix + "max_life", 0.0),
            "mana": number(values, prefix + "mana", 0.0),
            "maxMana": number(values, prefix + "max_mana", 0.0),
        }
    return rows


def bot_rows(
    values: dict[str, str],
) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for index in range(1, integer(values, "bot.count") + 1):
        prefix = f"bot.{index}."
        name = values.get(prefix + "name", "")
        if not name:
            continue
        rows[name] = {
            "id": integer(values, prefix + "id"),
            "element": integer(values, prefix + "element", -1),
            "discipline": integer(
                values, prefix + "discipline", -1
            ),
            "slot": integer(values, prefix + "slot", -1),
            "materialized": boolean(values, prefix + "materialized"),
            "alive": boolean(values, prefix + "alive"),
            "hp": number(values, prefix + "hp", 0.0),
            "maxHp": number(values, prefix + "max_hp", 0.0),
            "x": number(values, prefix + "x", 0.0),
            "y": number(values, prefix + "y", 0.0),
            "mode": values.get(prefix + "mode", ""),
            "castIssued": integer(values, prefix + "cast_issued"),
            "castAccepted": integer(
                values, prefix + "cast_accepted"
            ),
            "target": integer(values, prefix + "target"),
            "lastError": values.get(prefix + "last_error", ""),
        }
    return rows


def enemy_rows(
    values: dict[str, str],
) -> dict[int, dict[str, Any]]:
    rows: dict[int, dict[str, Any]] = {}
    for index in range(1, integer(values, "enemy.count") + 1):
        prefix = f"enemy.{index}."
        network_id = integer(values, prefix + "id")
        if network_id <= 0:
            continue
        rows[network_id] = {
            "dead": boolean(values, prefix + "dead"),
            "x": number(values, prefix + "x", 0.0),
            "y": number(values, prefix + "y", 0.0),
            "hp": number(values, prefix + "hp", 0.0),
            "maxHp": number(values, prefix + "max_hp", 0.0),
            "target": integer(values, prefix + "target"),
        }
    return rows


def valid_roster(values: dict[str, str], expected_scene: str) -> bool:
    participants = participant_rows(values)
    participants_by_name = {
        row["name"]: row for row in participants.values()
    }
    bots = bot_rows(values)
    brain_valid = (
        integer(values, "brain.desired", -1) == 2
        and integer(values, "brain.active", -1) == 2
    )
    bots_materialized = (
        expected_scene == "hub"
        or all(
            1 <= row["slot"] <= 3
            and row["materialized"]
            for row in bots.values()
        )
    )
    return (
        values.get("scene") == expected_scene
        and len(participants) == 4
        and set(participants_by_name) == {
            HOST_NAME,
            CLIENT_NAME,
            *BOT_NAMES,
        }
        and participants_by_name[HOST_NAME]["controller"] == "Native"
        and participants_by_name[CLIENT_NAME]["controller"] == "Native"
        and participants_by_name[HOST_NAME]["connected"]
        and participants_by_name[CLIENT_NAME]["connected"]
        and set(bots) == set(BOT_NAMES)
        and bots["Ember"]["element"] == 0
        and bots["Brook"]["element"] == 1
        and all(row["id"] > 0 for row in bots.values())
        and bots_materialized
        and brain_valid
    )


def pair_views(
    config: HarnessConfig,
    host: Peer,
    client: Peer,
) -> dict[str, dict[str, str]]:
    return {
        "host": peer_values(config, host),
        "client": peer_values(config, client),
    }


def wait_pair_roster(
    config: HarnessConfig,
    host: Peer,
    client: Peer,
    *,
    scene: str,
    timeout: float,
) -> dict[str, dict[str, str]]:
    return wait_for(
        lambda: pair_views(config, host, client),
        lambda views: all(
            valid_roster(views[role], scene)
            for role in ("host", "client")
        ),
        label=f"four-seat fire/water bot roster in {scene}",
        timeout=timeout,
        interval=0.5,
    )


def recoverable_run_bot_materialization(
    views: dict[str, dict[str, str]],
) -> bool:
    for role in ("host", "client"):
        values = views.get(role, {})
        bots = bot_rows(values)
        if (
            values.get("scene") != "testrun"
            or integer(values, "brain.desired", -1) != 2
            or integer(values, "brain.active", -1) != 2
            or set(bots) != set(BOT_NAMES)
            or all(bot["materialized"] for bot in bots.values())
        ):
            return False
    return True


def wait_run_roster(
    config: HarnessConfig,
    host: Peer,
    client: Peer,
) -> dict[str, Any]:
    try:
        views = wait_pair_roster(
            config,
            host,
            client,
            scene="testrun",
            timeout=15,
        )
        return {"views": views, "recovery": None}
    except VerificationFailure as initial_error:
        stalled_views = pair_views(config, host, client)
        if not recoverable_run_bot_materialization(stalled_views):
            raise
        action = request_bot_respawn(config, host)
        views = wait_pair_roster(
            config,
            host,
            client,
            scene="testrun",
            timeout=105,
        )
        return {
            "views": views,
            "recovery": {
                "reason":
                    "post-switch bot sync was not requeued",
                "initialFailure": str(initial_error),
                "stalledViews": stalled_views,
                "action": action,
            },
        }


def start_testrun(config: HarnessConfig, host: Peer) -> dict[str, str]:
    code = r"""
local invoked, ok, result = pcall(sd.hub.start_testrun)
print("ok=" .. tostring(invoked and ok == true))
print("result=" .. tostring(
  invoked and (result or "") or ok or ""))
"""
    last: dict[str, str] = {}
    for _ in range(80):
        last = parse_key_values(lua(config, host, code))
        if last.get("ok") == "true":
            return last
        if "settling" not in last.get("result", "").casefold():
            raise VerificationFailure(
                f"Host could not enter the retail test run: {last}"
            )
        time.sleep(0.25)
    raise VerificationFailure(
        f"Host run transition never settled: {last}"
    )


def arm_solomon_dig_flow(
    config: HarnessConfig,
    peer: Peer,
) -> dict[str, str]:
    values = parse_key_values(
        lua(
            config,
            peer,
            r"""
local flow = {
  armed = true,
  samples = 0,
  seen = false,
  placed = false,
  write_x = false,
  write_y = false,
  rebind = false,
  error = "",
  actor = 0,
  x = 0,
  y = 0,
  state = -1,
  max_state = -1,
  acquired = false,
  target_slot = -1,
}
_G.__netlag_solomon_dig = flow
local function read(actor, name, reader, fallback)
  local offset = sd.debug.layout_offset(name)
  if actor == 0 or offset == nil then return fallback end
  local value = reader(actor + offset)
  return tonumber(value) or fallback
end
local function sample()
  if rawget(_G, "__netlag_solomon_dig") ~= flow then
    return
  end
  flow.samples = flow.samples + 1
  local scene_state = sd.world.get_scene() or {}
  local scene = tostring(
    scene_state.name or scene_state.kind or "")
  if scene ~= "testrun" then return end
  local solomon = 0
  for _, actor in ipairs(sd.world.list_actors() or {}) do
    if tonumber(actor.object_type_id) == 0x1391 then
      solomon = tonumber(actor.actor_address) or 0
      break
    end
  end
  if solomon == 0 then return end
  flow.seen = true
  flow.actor = solomon
  flow.x = read(
    solomon, "actor_position_x", sd.debug.read_float, 0)
  flow.y = read(
    solomon, "actor_position_y", sd.debug.read_float, 0)
  flow.state = read(
    solomon, "solomon_dig_interaction_state",
    sd.debug.read_i32, -1)
  flow.max_state = math.max(flow.max_state, flow.state)
  flow.acquired = read(
    solomon, "solomon_dig_participant_acquired",
    sd.debug.read_u8, 0) ~= 0
  flow.target_slot = read(
    solomon, "solomon_dig_target_gameplay_slot",
    sd.debug.read_i32, -1)
end
sd.events.on("runtime.tick", sample)
sample()
print("armed=" .. tostring(flow.armed))
print("samples=" .. tostring(flow.samples))
""",
        )
    )
    if values.get("armed") != "true":
        raise VerificationFailure(
            f"Could not arm Solomon Dig flow on {peer.role}: {values}"
        )
    return values


def place_client_at_solomon(
    config: HarnessConfig,
    client: Peer,
) -> dict[str, str]:
    values = parse_key_values(
        lua(
            config,
            client,
            r"""
local function emit(key, value)
  print(key .. "=" .. tostring(value))
end
local solomon = 0
for _, actor in ipairs(sd.world.list_actors() or {}) do
  if tonumber(actor.object_type_id) == 0x1391 then
    solomon = tonumber(actor.actor_address) or 0
    break
  end
end
if solomon == 0 then error("Solomon_Dig actor unavailable") end
local function read(actor, name, reader, fallback)
  local offset = sd.debug.layout_offset(name)
  if offset == nil then return fallback end
  return tonumber(reader(actor + offset)) or fallback
end
local state = read(
  solomon, "solomon_dig_interaction_state",
  sd.debug.read_i32, -1)
local acquired = read(
  solomon, "solomon_dig_participant_acquired",
  sd.debug.read_u8, 0)
if state ~= 0 or acquired ~= 0 then
  error("Solomon_Dig was acquired before client placement")
end
local x = read(
  solomon, "actor_position_x", sd.debug.read_float, 0)
local y = read(
  solomon, "actor_position_y", sd.debug.read_float, 0)
local player = sd.player.get_state() or {}
local player_actor = tonumber(player.actor_address) or 0
local x_offset = sd.debug.layout_offset("actor_position_x")
local y_offset = sd.debug.layout_offset("actor_position_y")
if player_actor == 0 or x_offset == nil or y_offset == nil then
  error("local player placement surface unavailable")
end
local flow = rawget(_G, "__netlag_solomon_dig")
if type(flow) ~= "table" then
  error("Solomon Dig observer unavailable")
end
flow.player_before_x = tonumber(player.x) or 0
flow.player_before_y = tonumber(player.y) or 0
flow.write_x =
  sd.debug.write_float(player_actor + x_offset, x) == true
flow.write_y =
  sd.debug.write_float(player_actor + y_offset, y) == true
local rebind_ok, rebind_error = true, ""
if sd.world.rebind_actor ~= nil then
  rebind_ok, rebind_error = sd.world.rebind_actor(player_actor)
end
flow.rebind = rebind_ok == true
local after = sd.player.get_state() or {}
flow.player_after_x = tonumber(after.x) or 0
flow.player_after_y = tonumber(after.y) or 0
flow.placed = flow.write_x and flow.write_y and flow.rebind
if not flow.placed then
  flow.error = tostring(rebind_error or "placement failed")
end
emit("solomon_actor", solomon)
emit("solomon_state", state)
emit("solomon_acquired", acquired)
emit("solomon_x", x)
emit("solomon_y", y)
emit("player_before_x", flow.player_before_x)
emit("player_before_y", flow.player_before_y)
emit("write_x", flow.write_x)
emit("write_y", flow.write_y)
emit("rebind", flow.rebind)
emit("placed", flow.placed)
emit("error", flow.error)
""",
        )
    )
    if (
        values.get("placed") != "true"
        or values.get("write_x") != "true"
        or values.get("write_y") != "true"
        or values.get("rebind") != "true"
        or integer(values, "solomon_state", -1) != 0
        or integer(values, "solomon_acquired", -1) != 0
    ):
        raise VerificationFailure(
            f"Could not place client B at Solomon: {values}"
        )
    return values


def wait_client_solomon_dig(
    config: HarnessConfig,
    host: Peer,
    client: Peer,
    *,
    timeout: float = 60,
) -> dict[str, dict[str, str]]:
    deadline = time.monotonic() + timeout
    last: dict[str, dict[str, str]] = {}
    last_error = ""
    while time.monotonic() < deadline:
        try:
            last = {
                "host": peer_values(
                    config, host, SOLOMON_DIG_FLOW_PROBE
                ),
                "clientB": peer_values(
                    config, client, SOLOMON_DIG_FLOW_PROBE
                ),
            }
            last_error = ""
        except VerificationFailure as error:
            last_error = str(error)
            time.sleep(0.05)
            continue
        host_values = last["host"]
        client_values = last["clientB"]
        if host_values.get("error") or client_values.get("error"):
            raise VerificationFailure(
                f"Solomon Dig observer failed: {last}"
            )
        if (
            boolean(host_values, "acquired")
            and integer(host_values, "target_slot", -1) == 0
        ):
            raise VerificationFailure(
                "The host acquired its local Solomon interaction "
                f"before client B: {last}"
            )
        if (
            boolean(client_values, "placed")
            and boolean(client_values, "acquired")
            and integer(client_values, "target_slot", -1) == 0
            and boolean(host_values, "acquired")
            and integer(host_values, "target_slot", -1) > 0
        ):
            return last
        time.sleep(0.05)
    raise VerificationFailure(
        "Timed out waiting for the real client-B Solomon Dig "
        f"interaction; last={last}; last_error={last_error!r}"
    )


def wait_retail_wave_start(
    config: HarnessConfig,
    host: Peer,
    *,
    timeout: float = 90,
) -> dict[str, Any]:
    return wait_for(
        lambda: peer_values(
            config,
            host,
            WAVE_START_PROBE,
        ),
        lambda values: (
            integer(values, "wave.number") >= 1
            and values.get("combat.available") == "true"
            and integer(values, "combat.wave_index") >= 1
            and values.get("combat.active") == "true"
        ),
        label="host retail wave start",
        timeout=timeout,
        interval=0.1,
    )


def arm_human_survival_guard(
    config: HarnessConfig,
    peer: Peer,
) -> dict[str, str]:
    code = r"""
local hp_offset = sd.debug.layout_offset("progression_hp")
local max_hp_offset = sd.debug.layout_offset("progression_max_hp")
local protected_hp = 10000.0
local function sustain()
  if _G.__netlag_human_survival ~= true then return end
  local player = sd.player.get_state()
  local progression =
    tonumber(player and player.progression_address) or 0
  if progression == 0 or hp_offset == nil or max_hp_offset == nil then
    return
  end
  sd.debug.write_float(
    progression + max_hp_offset, protected_hp)
  sd.debug.write_float(progression + hp_offset, protected_hp)
end
if _G.__netlag_human_survival ~= true then
  _G.__netlag_human_survival = true
  sd.events.on("runtime.tick", sustain)
end
sustain()
print("registered=" .. tostring(
  _G.__netlag_human_survival == true))
local player = sd.player.get_state() or {}
print("player=" .. tostring(
  (tonumber(player.progression_address) or 0) > 0))
"""
    result = parse_key_values(lua(config, peer, code))
    if (
        result.get("registered") != "true"
        or result.get("player") != "true"
    ):
        raise VerificationFailure(
            f"Could not arm human survival on {peer.role}: {result}"
        )
    return result


def disarm_human_survival_guard(
    config: HarnessConfig,
    peer: Peer,
) -> dict[str, str]:
    result = parse_key_values(
        lua(
            config,
            peer,
            r"""
_G.__netlag_human_survival = false
print("disabled=" .. tostring(
  _G.__netlag_human_survival == false))
""",
        )
    )
    if result.get("disabled") != "true":
        raise VerificationFailure(
            "Could not disarm human survival on "
            f"{peer.role}: {result}"
        )
    return result


def resolve_level_offer(
    config: HarnessConfig,
    peer: Peer,
    values: dict[str, str],
    resolved: set[tuple[str, int]],
) -> dict[str, Any] | None:
    if (
        not boolean(values, "offer.valid")
        or boolean(values, "offer.submitted")
    ):
        return None
    offer_id = integer(values, "offer.id")
    target = integer(values, "offer.target")
    count = integer(values, "offer.count")
    key = (peer.pipe_name, offer_id)
    if (
        offer_id <= 0
        or count <= 0
        or target != peer.participant_id
        or key in resolved
    ):
        return None
    option_ids = [
        integer(values, f"offer.option.{index}", -1)
        for index in range(1, count + 1)
    ]
    preferred = (64, 16, 18, 17)
    option_index = 1
    for option_id in preferred:
        if option_id in option_ids:
            option_index = option_ids.index(option_id) + 1
            break
    response = parse_key_values(
        lua(
            config,
            peer,
            f"""
local ok, result = pcall(
  sd.runtime.choose_level_up_option,
  {{offer_id={offer_id}, option_index={option_index}}})
print("pcall_ok=" .. tostring(ok))
print("result=" .. tostring(result))
""",
        )
    )
    accepted = (
        response.get("pcall_ok") == "true"
        and response.get("result") == "true"
    )
    if accepted:
        resolved.add(key)
    return {
        "role": peer.role,
        "offerId": offer_id,
        "targetParticipantId": target,
        "optionIds": option_ids,
        "optionIndex": option_index,
        "accepted": accepted,
        "response": response,
    }


def queue_native_hit(
    config: HarnessConfig,
    host: Peer,
    participant_id: int,
    damage: float,
) -> dict[str, Any]:
    queued = parse_key_values(
        lua(
            config,
            host,
            f"""
local ok, err, serial =
  sd.debug.queue_native_magic_hit_behavior_probe(
    0.0, {damage:.9f}, 1, {participant_id}, 0.0)
print("ok=" .. tostring(ok))
print("error=" .. tostring(err or ""))
print("serial=" .. tostring(serial or 0))
""",
        )
    )
    serial = integer(queued, "serial")
    if queued.get("ok") != "true" or serial <= 0:
        raise VerificationFailure(
            f"Native hit probe did not queue: {queued}"
        )

    completed = wait_for(
        lambda: parse_key_values(
            lua(
                config,
                host,
                f"""
local completed, success, hp_before, hp_after, err =
  sd.debug.get_native_magic_hit_behavior_probe_result({serial})
print("completed=" .. tostring(completed))
print("success=" .. tostring(success))
print("hp_before=" .. tostring(hp_before))
print("hp_after=" .. tostring(hp_after))
print("error=" .. tostring(err or ""))
""",
            )
        ),
        lambda values: values.get("completed") == "true",
        label=f"native hit result {serial}",
        timeout=10,
        interval=0.1,
    )
    if completed.get("success") != "true":
        raise VerificationFailure(
            f"Native hit probe failed: {completed}"
        )
    return {
        "serial": serial,
        "damage": damage,
        "queue": queued,
        "result": completed,
        "hpBefore": number(completed, "hp_before", 0.0),
        "hpAfter": number(completed, "hp_after", 0.0),
    }


def force_bot_death_and_respawn(
    config: HarnessConfig,
    host: Peer,
    client: Peer,
    views: dict[str, dict[str, str]],
) -> dict[str, Any]:
    ember = bot_rows(views["host"]).get("Ember")
    if ember is None or ember["id"] <= 0:
        raise VerificationFailure(
            f"Ember was unavailable for death acceptance: {views['host']}"
        )
    participant_id = int(ember["id"])
    lethal_hits: list[dict[str, Any]] = []
    dead: dict[str, dict[str, str]] | None = None
    current = views
    for _ in range(4):
        current_bots = {
            role: bot_rows(current[role]).get("Ember", {})
            for role in ("host", "client")
        }
        if all(
            bot.get("alive") is False
            for bot in current_bots.values()
        ):
            dead = current
            break
        hp_before = min(
            float(bot.get("hp", 0.0))
            for bot in current_bots.values()
        )
        native_hit = queue_native_hit(
            config,
            host,
            participant_id,
            10000.0,
        )
        current = wait_for(
            lambda: pair_views(config, host, client),
            lambda rows: all(
                (
                    bot := bot_rows(rows[role]).get("Ember", {})
                ).get("alive") is False
                or float(bot.get("hp", hp_before)) < hp_before
                for role in ("host", "client")
            ),
            label="Ember native hit convergence on both peers",
            timeout=15,
            interval=0.2,
        )
        lethal_hits.append(
            {
                **native_hit,
                "observedBeforeHp": hp_before,
                "observedAfter": {
                    role: bot_rows(current[role]).get("Ember")
                    for role in ("host", "client")
                },
            }
        )
        if all(
            (
                bot_rows(current[role])
                .get("Ember", {})
                .get("alive")
                is False
            )
            for role in ("host", "client")
        ):
            dead = current
            break
    if dead is None:
        raise VerificationFailure(
            "Ember remained alive after four converged native "
            f"hits: {current}"
        )
    action = parse_key_values(
        lua(
            config,
            host,
            r"""
local result =
  sd.__settings_invoke_action("bot.brain", "respawn_bot")
print("ok=" .. tostring(result and result.ok))
print("error=" .. tostring(
  result and result.error or ""))
""",
        )
    )
    if action.get("ok") != "true":
        raise VerificationFailure(
            f"Bot respawn action failed: {action}"
        )
    respawned = wait_for(
        lambda: pair_views(config, host, client),
        lambda rows: all(
            set(bot_rows(rows[role])) == set(BOT_NAMES)
            and all(
                bot["alive"] and bot["materialized"]
                for bot in bot_rows(rows[role]).values()
            )
            for role in ("host", "client")
        ),
        label="fire/water bot respawn convergence",
        timeout=20,
        interval=0.25,
    )
    return {
        "participantId": participant_id,
        "lethalHits": lethal_hits,
        "dead": {
            role: bot_rows(dead[role]).get("Ember")
            for role in ("host", "client")
        },
        "action": action,
        "respawned": {
            role: bot_rows(respawned[role])
            for role in ("host", "client")
        },
    }


def game_path_for_capture(
    config: HarnessConfig,
    peer: Peer,
    local_raw_path: Path,
    remote_raw_path: str,
) -> str:
    if peer.location == "local":
        return windows_path(local_raw_path)
    return "Z:" + remote_raw_path.replace("/", "\\")


def wave_screenshot_artifact(
    config: HarnessConfig,
    peer: Peer,
    session_directory: Path,
    wave: int,
    *,
    clear_existing: bool = False,
) -> tuple[dict[str, Any], str]:
    label = f"wave-{wave:02d}"
    output_path = (
        session_directory
        / "screenshots"
        / f"{label}-{peer.role}.png"
    )
    raw_path = output_path.with_suffix(".bmp")
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    if clear_existing:
        raw_path.unlink(missing_ok=True)
        output_path.unlink(missing_ok=True)
    remote_relative = (
        f".sdmod/logs/netlag-{label}-{peer.role}.bmp"
    )
    remote_raw = (
        f"{config.remote_root}/runtime/instances/{peer.instance}/"
        f"stage/{remote_relative}"
    )
    target = game_path_for_capture(
        config,
        peer,
        raw_path,
        remote_raw,
    )
    artifact: dict[str, Any] = {
        "role": peer.role,
        "location": peer.location,
        "path": str(output_path),
    }
    if peer.location == "remote":
        artifact["pendingRemoteArtifact"] = Path(
            remote_relative
        ).name
    else:
        artifact["pendingLocalArtifact"] = str(raw_path)
    return artifact, target


def validate_backbuffer(
    raw_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    if not raw_path.is_file() or raw_path.stat().st_size < 10_000:
        raise VerificationFailure(
            f"Backbuffer capture is absent or tiny: {raw_path}"
        )
    with Image.open(raw_path) as raw:
        image = raw.convert("RGB")
        colors = image.getcolors(
            maxcolors=image.width * image.height
        )
        unique_colors = (
            len(colors)
            if colors is not None
            else image.width * image.height
        )
        dominant_fraction = (
            max(count for count, _ in colors)
            / float(image.width * image.height)
            if colors
            else 0.0
        )
        if unique_colors < 500 or dominant_fraction >= 0.92:
            raise VerificationFailure(
                "Backbuffer is blank or low-information: "
                f"{raw_path} unique={unique_colors} "
                f"dominant={dominant_fraction:.4f}"
            )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        image.save(output_path)
        return {
            "width": image.width,
            "height": image.height,
            "uniqueColors": unique_colors,
            "dominantFraction": dominant_fraction,
            "bytes": output_path.stat().st_size,
        }


def capture_peer(
    config: HarnessConfig,
    peer: Peer,
    session_directory: Path,
    label: str,
) -> dict[str, Any]:
    match = re.fullmatch(r"wave-(\d{2})", label)
    if match is None:
        raise VerificationFailure(
            f"Invalid wave capture label: {label!r}"
        )
    artifact, target = wave_screenshot_artifact(
        config,
        peer,
        session_directory,
        int(match.group(1)),
        clear_existing=True,
    )
    result = parse_key_values(
        lua(
            config,
            peer,
            f"""
local ok, err = sd.debug.capture_backbuffer({json.dumps(target)})
print("ok=" .. tostring(ok))
print("error=" .. tostring(err or ""))
""",
        )
    )
    if result.get("ok") != "true":
        raise VerificationFailure(
            f"Backbuffer capture failed on {peer.role}: {result}"
        )
    return artifact


def arm_wave_screenshot_capture(
    config: HarnessConfig,
    peer: Peer,
    session_directory: Path,
) -> dict[str, str]:
    paths: list[str] = []
    for wave in range(1, 6):
        _, target = wave_screenshot_artifact(
            config,
            peer,
            session_directory,
            wave,
            clear_existing=True,
        )
        paths.append(
            f"[{wave}] = {json.dumps(target)}"
        )
    path_table = ",\n  ".join(paths)
    return parse_key_values(
        lua(
            config,
            peer,
            f"""
local state = {{
  paths = {{
  {path_table}
  }},
  records = {{}},
}}
_G.__netlag_wave_screenshots = state
if _G.__netlag_wave_screenshots_registered ~= true then
  sd.events.on("wave.started", function(event)
    local active = _G.__netlag_wave_screenshots
    local wave = tonumber(event and event.wave) or 0
    local path = type(active) == "table" and
      type(active.paths) == "table" and active.paths[wave] or nil
    if path ~= nil and active.records[wave] == nil then
      local ok, err = sd.debug.capture_backbuffer(path)
      active.records[wave] = {{
        ok = ok == true,
        error = tostring(err or ""),
      }}
    end
  end)
  _G.__netlag_wave_screenshots_registered = true
end
print("registered=" .. tostring(
  _G.__netlag_wave_screenshots_registered == true))
""",
        )
    )


def query_wave_screenshot_capture(
    config: HarnessConfig,
    peer: Peer,
) -> dict[str, str]:
    return parse_key_values(
        lua(
            config,
            peer,
            r"""
local output = {}
local function emit(key, value)
  output[#output + 1] =
    key .. "=" .. tostring(value == nil and "" or value)
end
local state = rawget(_G, "__netlag_wave_screenshots") or {}
local records = state.records or {}
for wave = 1, 5 do
  local record = records[wave]
  local prefix = "wave." .. tostring(wave) .. "."
  emit(prefix .. "seen", type(record) == "table")
  emit(prefix .. "ok",
    type(record) == "table" and record.ok == true)
  emit(prefix .. "error",
    type(record) == "table" and record.error or "")
end
return table.concat(output, "\n")
""",
        )
    )


def collect_wave_screenshot_records(
    config: HarnessConfig,
    host: Peer,
    client: Peer,
    session_directory: Path,
) -> tuple[
    dict[str, Any],
    dict[str, dict[str, str]],
    str,
]:
    def statuses() -> dict[str, dict[str, str]]:
        return {
            "host": query_wave_screenshot_capture(config, host),
            "client": query_wave_screenshot_capture(config, client),
        }

    error = ""
    try:
        observed = wait_for(
            statuses,
            lambda rows: all(
                rows[role].get(f"wave.{wave}.seen") == "true"
                for role in ("host", "client")
                for wave in range(1, 6)
            ),
            label="event-driven wave screenshots on both peers",
            timeout=30,
            interval=0.25,
        )
    except VerificationFailure as failure:
        error = str(failure)
        observed = statuses()

    screenshots: dict[str, Any] = {}
    for wave in range(1, 6):
        key = str(wave)
        if not all(
            observed[role].get(f"wave.{wave}.ok") == "true"
            for role in ("host", "client")
        ):
            continue
        host_artifact, _ = wave_screenshot_artifact(
            config, host, session_directory, wave
        )
        client_artifact, _ = wave_screenshot_artifact(
            config, client, session_directory, wave
        )
        screenshots[key] = {
            "captureTrigger": "wave.started",
            "capturedAtHostWave": wave,
            "capturedAtClientWave": wave,
            "peers": {
                "host": host_artifact,
                "client": client_artifact,
            },
        }
    return screenshots, observed, error


def finalize_deferred_screenshots(
    result: dict[str, Any],
    session_directory: Path,
) -> None:
    wave_five = result.get("waveFive")
    if not isinstance(wave_five, dict):
        return
    screenshots = wave_five.get("screenshots")
    if not isinstance(screenshots, dict):
        return
    for wave in screenshots.values():
        peers = wave.get("peers") if isinstance(wave, dict) else None
        if not isinstance(peers, dict):
            continue
        for peer in peers.values():
            if not isinstance(peer, dict):
                continue
            remote_artifact = peer.get("pendingRemoteArtifact")
            local_artifact = peer.get("pendingLocalArtifact")
            if isinstance(remote_artifact, str):
                source = (
                    session_directory
                    / "runtime-evidence"
                    / f"{peer['role']}-remote"
                    / remote_artifact
                )
            elif isinstance(local_artifact, str):
                source = Path(local_artifact)
            else:
                continue
            output_path = Path(str(peer["path"]))
            quality = validate_backbuffer(source, output_path)
            peer["rawBytes"] = source.stat().st_size
            peer["quality"] = quality
            peer.pop("pendingRemoteArtifact", None)
            peer.pop("pendingLocalArtifact", None)
            if isinstance(local_artifact, str):
                source.unlink(missing_ok=True)


def capture_wave_pair(
    config: HarnessConfig,
    host: Peer,
    client: Peer,
    session_directory: Path,
    wave: int,
) -> dict[str, Any]:
    label = f"wave-{wave:02d}"
    return {
        "host": capture_peer(
            config, host, session_directory, label
        ),
        "client": capture_peer(
            config, client, session_directory, label
        ),
    }


def arm_client_hit_observer(
    config: HarnessConfig,
    client: Peer,
) -> dict[str, str]:
    result = parse_key_values(
        lua(
            config,
            client,
            r"""
local function emit(key, value)
  print(key .. "=" .. tostring(value))
end
_G.__netlag_hit_observer = {
  maximum = 0.0,
  actor_maximum = 0.0,
  samples = 0,
}
if _G.__netlag_hit_observer_registered ~= true then
  sd.events.on("runtime.tick", function()
    local observer = _G.__netlag_hit_observer
    if type(observer) ~= "table" then return end
    local player = sd.player.get_state() or {}
    local actor = tonumber(player.actor_address) or 0
    local owner_offset = sd.debug.layout_offset("actor_owner")
    local actor_alpha_offset = sd.debug.layout_offset(
      "actor_hit_reaction_primary_alpha")
    local alpha_offset = sd.debug.layout_offset(
      "arena_hit_feedback_alpha")
    local arena = actor ~= 0 and owner_offset ~= nil and
      (tonumber(sd.debug.read_ptr(actor + owner_offset)) or 0) or 0
    local alpha = arena ~= 0 and alpha_offset ~= nil and
      (tonumber(sd.debug.read_float(arena + alpha_offset)) or 0.0)
      or 0.0
    local actor_alpha = actor ~= 0 and
      actor_alpha_offset ~= nil and
      (tonumber(sd.debug.read_float(
        actor + actor_alpha_offset)) or 0.0) or 0.0
    observer.samples = observer.samples + 1
    observer.maximum = math.max(observer.maximum, alpha)
    observer.actor_maximum =
      math.max(observer.actor_maximum, actor_alpha)
  end)
  _G.__netlag_hit_observer_registered = true
end
emit("registered", _G.__netlag_hit_observer_registered)
emit("armed", type(_G.__netlag_hit_observer) == "table")
""",
        )
    )
    if (
        result.get("registered") != "true"
        or result.get("armed") != "true"
    ):
        raise VerificationFailure(
            f"Could not arm client hit observer: {result}"
        )
    return result


def query_client_hit_observer(
    config: HarnessConfig,
    client: Peer,
) -> dict[str, str]:
    result = parse_key_values(
        lua(
            config,
            client,
            r"""
local observer = _G.__netlag_hit_observer
print("available=" .. tostring(type(observer) == "table"))
print("maximum=" .. tostring(observer and observer.maximum or -1))
print("actor_maximum=" ..
  tostring(observer and observer.actor_maximum or -1))
print("samples=" .. tostring(observer and observer.samples or 0))
""",
        )
    )
    if result.get("available") != "true":
        raise VerificationFailure(
            f"Client hit observer disappeared: {result}"
        )
    return result


def compact_pair_sample(
    elapsed_seconds: float,
    views: dict[str, dict[str, str]],
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "elapsedSeconds": round(elapsed_seconds, 3),
    }
    for role in ("host", "client"):
        values = views[role]
        result[role] = {
            "scene": values.get("scene", ""),
            "wave": integer(values, "wave.number"),
            "phase": values.get("wave.phase", ""),
            "aliveEnemies": integer(values, "enemy.live"),
            "replicatedSequence": integer(
                values, "replicated.sequence"
            ),
            "snapshotAgeMs": integer(
                values, "replicated.source_age_ms"
            ),
            "holdingStale": boolean(
                values, "replicated.holding_stale"
            ),
            "participants": participant_rows(values),
            "bots": bot_rows(values),
            "enemies": enemy_rows(values),
        }
    return result


def update_enemy_motion(
    values: dict[str, str],
    previous: dict[int, tuple[float, float]],
    metrics: dict[str, Any],
) -> None:
    current = enemy_rows(values)
    live_positions: dict[int, tuple[float, float]] = {}
    for network_id, enemy in current.items():
        if enemy["dead"] or enemy["hp"] <= 0.0:
            continue
        position = (float(enemy["x"]), float(enemy["y"]))
        live_positions[network_id] = position
        if network_id not in previous:
            continue
        distance = math.hypot(
            position[0] - previous[network_id][0],
            position[1] - previous[network_id][1],
        )
        metrics["observedSteps"] += 1
        metrics["maximumStep"] = max(
            metrics["maximumStep"], distance
        )
        if distance > MAX_EXPECTED_ENEMY_STEP:
            metrics["unexpectedLargeStepCount"] += 1
        if distance >= 0.5:
            metrics["movingSteps"] += 1
            metrics["totalDistance"] += distance
    previous.clear()
    previous.update(live_positions)


def compare_pair_vitals(
    views: dict[str, dict[str, str]],
) -> dict[str, Any]:
    host_by_id = participant_rows(views["host"])
    client_by_id = participant_rows(views["client"])
    host = {row["name"]: row for row in host_by_id.values()}
    client = {row["name"]: row for row in client_by_id.values()}
    shared = sorted(set(host) & set(client))
    differences: dict[str, Any] = {}
    maximum_life_delta = 0.0
    maximum_mana_delta = 0.0
    for participant_name in shared:
        life_delta = abs(
            float(host[participant_name]["life"])
            - float(client[participant_name]["life"])
        )
        mana_delta = abs(
            float(host[participant_name]["mana"])
            - float(client[participant_name]["mana"])
        )
        maximum_life_delta = max(maximum_life_delta, life_delta)
        maximum_mana_delta = max(maximum_mana_delta, mana_delta)
        if life_delta > 0.01 or mana_delta > 0.01:
            differences[participant_name] = {
                "lifeDelta": life_delta,
                "manaDelta": mana_delta,
            }
    return {
        "sameParticipantNames": set(host) == set(client),
        "sameControllerKinds": all(
            host[name]["controller"] == client[name]["controller"]
            for name in shared
        ),
        "sameTransportIdsAsExposed": (
            set(host_by_id) == set(client_by_id)
        ),
        "maximumLifeDelta": maximum_life_delta,
        "maximumManaDelta": maximum_mana_delta,
        "differences": differences,
    }


def request_bot_respawn(
    config: HarnessConfig,
    host: Peer,
) -> dict[str, str]:
    result = parse_key_values(
        lua(
            config,
            host,
            r"""
local result =
  sd.__settings_invoke_action("bot.brain", "respawn_bot")
print("ok=" .. tostring(result and result.ok))
print("error=" ..
  tostring(result and result.error or ""))
""",
        )
    )
    if result.get("ok") != "true":
        raise VerificationFailure(
            f"Bot respawn action failed: {result}"
        )
    return result


def retire_one_host_enemy(
    config: HarnessConfig,
    host: Peer,
) -> dict[str, str]:
    result = parse_key_values(
        lua(
            config,
            host,
            r"""
local target = nil
for _, actor in ipairs(
    sd.world.list_actors and sd.world.list_actors() or {}) do
  if actor.tracked_enemy == true and actor.dead ~= true and
      (tonumber(actor.hp) or 0) > 0 then
    if target == nil or
        (tonumber(actor.actor_address) or 0) <
          (tonumber(target.actor_address) or 0) then
      target = actor
    end
  end
end
if target == nil then
  print("ok=false")
  print("reason=no_live_enemy")
  return
end
local address = tonumber(target.actor_address) or 0
local maximum = math.max(tonumber(target.max_hp) or 1, 1)
local health = sd.gameplay.set_run_enemy_health(
  address, 0, maximum)
local death, seh = false, 0
if health == true and sd.world.trigger_enemy_death ~= nil then
  death, seh = sd.world.trigger_enemy_death(address)
end
print("ok=" .. tostring(health == true and death == true))
print("health=" .. tostring(health))
print("death=" .. tostring(death))
print("seh=" .. tostring(seh or 0))
print("actor=" .. tostring(address))
print("network_id=" .. tostring(target.network_actor_id or 0))
print("old_hp=" .. tostring(target.hp or 0))
print("max_hp=" .. tostring(maximum))
""",
        )
    )
    if result.get("ok") != "true":
        raise VerificationFailure(
            f"Host-authority enemy retirement failed: {result}"
        )
    return result


def monitor_wave_five(
    config: HarnessConfig,
    host: Peer,
    client: Peer,
    session_directory: Path,
    *,
    timeout: float,
) -> dict[str, Any]:
    started = time.monotonic()
    highest_wave = {"host": 0, "client": 0}
    timeline: list[dict[str, Any]] = []
    screenshots: dict[str, Any] = {}
    offer_choices: list[dict[str, Any]] = []
    resolved_offers: set[tuple[str, int]] = set()
    enemy_motion: dict[str, Any] = {
        "observedSteps": 0,
        "movingSteps": 0,
        "totalDistance": 0.0,
        "maximumStep": 0.0,
        "unexpectedLargeStepCount": 0,
    }
    previous_enemy_positions: dict[int, tuple[float, float]] = {}
    roster_failures: list[dict[str, Any]] = []
    vital_samples: list[dict[str, Any]] = []
    forced_bot_lifecycle: dict[str, Any] | None = None
    automatic_respawns: list[dict[str, Any]] = []
    hit_feedback: dict[str, Any] | None = None
    survival_guard_disarm: dict[str, Any] | None = None
    progression_assists: list[dict[str, Any]] = []
    assisted_waves: set[int] = set()
    bot_combat_by_wave: dict[str, Any] = {}
    previous_host_casts = {
        name: 0 for name in BOT_NAMES
    }
    cast_baselines: dict[int, dict[str, int]] = {}
    last_wave = 0
    last_progress_key: tuple[Any, ...] | None = None
    last_progress_at = started
    last_assist_at = 0.0
    last_timeline_sample = -WAVE_TIMELINE_INTERVAL_SECONDS
    wave_five_since: float | None = None
    last_views: dict[str, dict[str, str]] = {}
    consecutive_query_failures = 0

    while time.monotonic() - started < timeout:
        elapsed = time.monotonic() - started
        try:
            views = pair_views(config, host, client)
            last_views = views
            consecutive_query_failures = 0
        except (
            VerificationFailure,
            OSError,
            subprocess.SubprocessError,
        ) as error:
            consecutive_query_failures += 1
            if consecutive_query_failures >= 5:
                raise VerificationFailure(
                    "Both peers stopped responding during wave-five "
                    f"monitoring: {error}"
                ) from error
            time.sleep(0.25)
            continue

        for role, peer in (("host", host), ("client", client)):
            choice = resolve_level_offer(
                config,
                peer,
                views[role],
                resolved_offers,
            )
            if choice is not None:
                choice["elapsedSeconds"] = round(elapsed, 3)
                offer_choices.append(choice)

        host_wave = integer(views["host"], "wave.number")
        client_wave = integer(views["client"], "wave.number")
        host_bots = bot_rows(views["host"])
        host_casts_now = {
            name: int(host_bots.get(name, {}).get("castAccepted", 0))
            for name in BOT_NAMES
        }
        if host_wave > 0 and host_wave != last_wave:
            cast_baselines[host_wave] = dict(previous_host_casts)
            last_wave = host_wave
        baseline = cast_baselines.get(host_wave)
        if (
            baseline is not None
            and all(
                host_casts_now[name] > baseline[name]
                for name in BOT_NAMES
            )
        ):
            bot_combat_by_wave.setdefault(
                str(host_wave),
                {
                    "elapsedSeconds": round(elapsed, 3),
                    "baselineAcceptedCasts": baseline,
                    "observedAcceptedCasts": dict(host_casts_now),
                },
            )
        previous_host_casts = host_casts_now
        highest_wave["host"] = max(
            highest_wave["host"], host_wave
        )
        highest_wave["client"] = max(
            highest_wave["client"], client_wave
        )
        update_enemy_motion(
            views["client"],
            previous_enemy_positions,
            enemy_motion,
        )
        vital_agreement = compare_pair_vitals(views)
        vital_agreement["elapsedSeconds"] = round(elapsed, 3)
        vital_samples.append(vital_agreement)

        invalid_roles = [
            role
            for role in ("host", "client")
            if not valid_roster(views[role], "testrun")
        ]
        if invalid_roles:
            roster_failures.append(
                {
                    "elapsedSeconds": round(elapsed, 3),
                    "roles": invalid_roles,
                    "views": {
                        role: compact_pair_sample(
                            elapsed, views
                        )[role]
                        for role in invalid_roles
                    },
                }
            )

        if (
            elapsed - last_timeline_sample
            >= WAVE_TIMELINE_INTERVAL_SECONDS
        ):
            timeline.append(compact_pair_sample(elapsed, views))
            last_timeline_sample = elapsed

        progress_key = (
            host_wave,
            views["host"].get("wave.phase", ""),
            integer(views["host"], "wave.remaining"),
            integer(views["host"], "wave.spawned"),
            integer(views["host"], "wave.alive"),
            integer(views["host"], "wave.killed"),
            integer(views["host"], "enemy.live"),
        )
        if progress_key != last_progress_key:
            last_progress_key = progress_key
            last_progress_at = time.monotonic()

        if (
            forced_bot_lifecycle is None
            and host_wave >= 2
            and client_wave >= 2
            and all(
                row.get("alive") is True
                for row in bot_rows(views["host"]).values()
            )
        ):
            forced_bot_lifecycle = force_bot_death_and_respawn(
                config,
                host,
                client,
                views,
            )

        if (
            hit_feedback is None
            and host_wave >= 3
            and client_wave >= 3
        ):
            hit_feedback = {
                "nativeHit": queue_native_hit(
                    config,
                    host,
                    CLIENT_PARTICIPANT_ID,
                    1.0,
                )
            }
            observer = wait_for(
                lambda: query_client_hit_observer(
                    config, client
                ),
                lambda values: (
                    number(values, "maximum", 0.0) > 0.01
                    or number(
                        values, "actor_maximum", 0.0
                    )
                    > 0.01
                ),
                label="client B stock hit feedback",
                timeout=12,
                interval=0.1,
            )
            hit_feedback["clientObserver"] = observer

        dead_bots = [
            name
            for name, bot in host_bots.items()
            if not bot["alive"]
        ]
        if (
            forced_bot_lifecycle is not None
            and dead_bots
        ):
            action = request_bot_respawn(config, host)
            automatic_respawns.append(
                {
                    "elapsedSeconds": round(elapsed, 3),
                    "wave": host_wave,
                    "deadBots": dead_bots,
                    "action": action,
                }
            )
            time.sleep(1.0)

        current_time = time.monotonic()
        can_assist_progression = (
            host_wave == client_wave
            and 1 <= host_wave < 5
            and integer(views["host"], "enemy.live") > 0
            and (
                host_wave != 2
                or forced_bot_lifecycle is not None
            )
        )
        if (
            can_assist_progression
            and host_wave not in assisted_waves
            and current_time - last_progress_at
                >= WAVE_STALL_ASSIST_SECONDS
        ):
            assisted_waves.add(host_wave)
        if (
            can_assist_progression
            and host_wave in assisted_waves
            and current_time - last_assist_at
                >= WAVE_STALL_ASSIST_INTERVAL_SECONDS
        ):
            progression_assists.append(
                {
                    "elapsedSeconds": round(elapsed, 3),
                    "wave": host_wave,
                    "reason": (
                        "stock wave state remained unchanged after "
                        "the organic combat window"
                    ),
                    "acceptedCasts": dict(host_casts_now),
                    "result": retire_one_host_enemy(config, host),
                }
            )
            last_assist_at = time.monotonic()

        wave_five_ready = (
            host_wave >= 5
            and client_wave >= 5
            and all(
                bot["alive"] and bot["materialized"]
                for role in ("host", "client")
                for bot in bot_rows(views[role]).values()
            )
        )
        if wave_five_ready and survival_guard_disarm is None:
            survival_guard_disarm = {
                "host": disarm_human_survival_guard(
                    config, host
                ),
                "clientB": disarm_human_survival_guard(
                    config, client
                ),
                "reason": (
                    "remove harness HP writes before the final "
                    "vital-convergence gate"
                ),
            }
            wave_five_ready = False
        elif (
            wave_five_ready
            and (
                vital_agreement["maximumLifeDelta"]
                > MAX_EXPECTED_IN_FLIGHT_LIFE_DELTA
                or vital_agreement["maximumManaDelta"] > 0.01
            )
        ):
            wave_five_ready = False
        if wave_five_ready:
            if wave_five_since is None:
                wave_five_since = time.monotonic()
            elif time.monotonic() - wave_five_since >= 5.0:
                break
        else:
            wave_five_since = None
        time.sleep(WAVE_MONITOR_INTERVAL_SECONDS)

    if not last_views:
        raise VerificationFailure(
            "The wave-five monitor collected no peer state."
        )

    screenshot_status: dict[str, dict[str, str]] = {}
    screenshot_error = ""
    if all(value >= 5 for value in highest_wave.values()):
        (
            screenshots,
            screenshot_status,
            screenshot_error,
        ) = collect_wave_screenshot_records(
            config,
            host,
            client,
            session_directory,
        )

    final_vitals = compare_pair_vitals(last_views)
    final_bots = {
        role: bot_rows(last_views[role])
        for role in ("host", "client")
    }
    host_casts = {
        name: int(row["castAccepted"])
        for name, row in final_bots["host"].items()
    }
    validation = {
        "bothPeersReachedWaveFive": all(
            value >= 5 for value in highest_wave.values()
        ),
        "allWaveScreenshotsCaptured": all(
            key in screenshots
            for key in ("1", "2", "3", "4", "5")
        ),
        "forcedBotDeathAndRespawn": (
            forced_bot_lifecycle is not None
        ),
        "botsFought": (
            len(host_casts) == 2
            and all(value > 0 for value in host_casts.values())
        ),
        "botsAliveOnBothPeersAtFinish": all(
            set(final_bots[role]) == set(BOT_NAMES)
            and all(
                bot["alive"] and bot["materialized"]
                for bot in final_bots[role].values()
            )
            for role in ("host", "client")
        ),
        "clientEnemyMovementObserved": (
            enemy_motion["movingSteps"] >= 3
            and enemy_motion["totalDistance"] > 10.0
            and enemy_motion["unexpectedLargeStepCount"] == 0
        ),
        "clientHitFeedbackObserved": hit_feedback is not None,
        "rosterStayedSynchronized": not roster_failures,
        "finalRosterAndVitalsSynchronized": (
            final_vitals["sameParticipantNames"]
            and final_vitals["sameControllerKinds"]
            and final_vitals["maximumLifeDelta"]
                <= MAX_EXPECTED_IN_FLIGHT_LIFE_DELTA
            and final_vitals["maximumManaDelta"] <= 0.01
        ),
    }
    success = all(validation.values())
    return {
        "success": success,
        "highestWave": highest_wave,
        "validation": validation,
        "screenshots": screenshots,
        "screenshotCaptureStatus": screenshot_status,
        "screenshotCaptureError": screenshot_error,
        "forcedBotLifecycle": forced_bot_lifecycle,
        "automaticRespawns": automatic_respawns,
        "hitFeedback": hit_feedback,
        "survivalGuardDisarm": survival_guard_disarm,
        "enemyMotion": enemy_motion,
        "botCombatByWave": bot_combat_by_wave,
        "progressionAssists": progression_assists,
        "hostAcceptedCasts": host_casts,
        "rosterFailures": roster_failures,
        "vitalAgreement": {
            "final": final_vitals,
            "acceptedInFlightLifeDelta":
                MAX_EXPECTED_IN_FLIGHT_LIFE_DELTA,
            "maximumLifeDelta": max(
                (
                    float(row["maximumLifeDelta"])
                    for row in vital_samples
                ),
                default=0.0,
            ),
            "maximumManaDelta": max(
                (
                    float(row["maximumManaDelta"])
                    for row in vital_samples
                ),
                default=0.0,
            ),
            "divergentSampleCount": sum(
                bool(row["differences"])
                for row in vital_samples
            ),
        },
        "offerChoices": offer_choices,
        "timeline": timeline,
        "lastViews": last_views,
        "timedOut": not success and (
            time.monotonic() - started >= timeout
        ),
    }


def run_capture(
    command: Sequence[str],
    *,
    timeout: float,
    cwd: Path = ROOT,
) -> dict[str, Any]:
    started = time.monotonic()
    completed = subprocess.run(
        list(command),
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    return {
        "command": list(command),
        "returnCode": completed.returncode,
        "stdout": completed.stdout.replace("\r", ""),
        "stderr": completed.stderr.replace("\r", ""),
        "durationMs": round(
            (time.monotonic() - started) * 1000.0, 3
        ),
    }


def preflight_ports(config: HarnessConfig) -> dict[str, Any]:
    local = run_capture(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            (
                "$rows=@(Get-NetUDPEndpoint -ErrorAction "
                "SilentlyContinue | Where-Object { "
                "$_.LocalPort -in @(50311,50312) } | "
                "Select-Object LocalAddress,LocalPort,"
                "OwningProcess); $rows | ConvertTo-Json -Compress"
            ),
        ],
        timeout=30,
    )
    if local["returnCode"] != 0:
        raise VerificationFailure(
            f"Could not inspect local UDP ownership: {local}"
        )
    local_output = str(local["stdout"]).strip()
    if local_output not in ("", "null", "[]"):
        raise VerificationFailure(
            "A pinned local UDP port is already owned; no process "
            f"was touched: {local_output}"
        )

    remote_command = (
        "ss -H -lunp | awk "
        + shlex.quote(
            '$5 ~ /:(51511|51512)$/ { print }'
        )
    )
    remote_output = ssh_read_only(
        config, remote_command
    ).strip()
    if remote_output:
        raise VerificationFailure(
            "A pinned NFO UDP port is already owned; no process "
            f"was touched: {remote_output}"
        )
    status_command = " ".join(
        shlex.quote(value)
        for value in (
            config.remote_helper,
            config.remote_root,
            "status",
        )
    )
    owned = ssh_read_only(
        config, status_command
    ).strip()
    if owned:
        raise VerificationFailure(
            "The isolated NFO root still owns processes; no launch "
            f"was attempted: {owned}"
        )
    return {
        "checkedUtc": utc_now(),
        "local": local,
        "remoteCommand": remote_command,
        "remoteOutput": remote_output,
        "remoteOwnedProcesses": owned,
    }


def measure_clock_offset(
    config: HarnessConfig,
    *,
    samples: int = 7,
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    stream = RemoteLineStream(config, "clock-stream")
    try:
        for _ in range(samples):
            before_ns = time.time_ns()
            response = stream.request("now", timeout=20)
            after_ns = time.time_ns()
            response_code, separator, remote_text = (
                response.partition("\t")
            )
            if not separator or response_code != "OK":
                raise VerificationFailure(
                    f"NFO clock probe returned {response!r}."
                )
            try:
                remote_ns = int(remote_text, 10)
            except ValueError as error:
                raise VerificationFailure(
                    f"NFO clock probe returned {remote_text!r}."
                ) from error
            midpoint_ns = before_ns + (after_ns - before_ns) // 2
            rows.append(
                {
                    "roundTripNs": after_ns - before_ns,
                    "remoteMinusLocalMidpointNs":
                        remote_ns - midpoint_ns,
                    "localBeforeNs": before_ns,
                    "localAfterNs": after_ns,
                    "remoteNs": remote_ns,
                }
            )
    finally:
        stream.close()
    best = min(rows, key=lambda row: row["roundTripNs"])
    return {
        "measuredUtc": utc_now(),
        "sampleCount": len(rows),
        "bestRoundTripNs": best["roundTripNs"],
        "bestRemoteMinusLocalMidpointNs":
            best["remoteMinusLocalMidpointNs"],
        "offsetDistributionNs": distribution(
            row["remoteMinusLocalMidpointNs"] for row in rows
        ),
        "roundTripDistributionNs": distribution(
            row["roundTripNs"] for row in rows
        ),
        "samples": rows,
        "correlationPreference":
            "packet sequence first; adjusted UTC only as secondary",
    }


def collect_path_diagnostics(
    config: HarnessConfig,
) -> dict[str, Any]:
    local_basic = run_capture(
        ["ping.exe", "-n", "6", config.remote_public_host],
        timeout=30,
    )
    local_mtu = run_capture(
        [
            "ping.exe",
            "-n",
            "4",
            "-f",
            "-l",
            "1472",
            config.remote_public_host,
        ],
        timeout=30,
    )
    remote_basic_command = (
        "ping -c 6 -W 3 "
        + shlex.quote(config.local_public_host)
    )
    remote_mtu_command = (
        "ping -c 4 -W 3 -M do -s 1472 "
        + shlex.quote(config.local_public_host)
    )
    remote_route_command = (
        "ip route get "
        + shlex.quote(config.local_public_host)
    )
    remote_basic = run_capture(
        [
            str(config.ssh_executable),
            "-o",
            "BatchMode=yes",
            config.ssh_alias,
            remote_basic_command,
        ],
        timeout=40,
    )
    remote_mtu = run_capture(
        [
            str(config.ssh_executable),
            "-o",
            "BatchMode=yes",
            config.ssh_alias,
            remote_mtu_command,
        ],
        timeout=40,
    )
    remote_route = run_capture(
        [
            str(config.ssh_executable),
            "-o",
            "BatchMode=yes",
            config.ssh_alias,
            remote_route_command,
        ],
        timeout=20,
    )
    return {
        "capturedUtc": utc_now(),
        "localToNfoPing": local_basic,
        "localToNfoMtu1500Probe": local_mtu,
        "nfoToLocalPing": remote_basic,
        "nfoToLocalMtu1500Probe": remote_mtu,
        "nfoRouteToLocal": remote_route,
        "mutations": [],
    }


ARTIFACTS: tuple[tuple[str, str], ...] = (
    (
        ".sdmod/logs/network-telemetry.jsonl",
        "network-telemetry.jsonl",
    ),
    (
        ".sdmod/logs/solomondarkmodloader.log",
        "solomondarkmodloader.log",
    ),
    (
        ".sdmod/loader-startup-status.json",
        "loader-startup-status.json",
    ),
    (
        ".sdmod/startup-status.json",
        "startup-status.json",
    ),
    (
        ".sdmod/multiplayer-session-status.json",
        "multiplayer-session-status.json",
    ),
    (
        ".sdmod/multiplayer-compatibility.json",
        "multiplayer-compatibility.json",
    ),
    (
        ".sdmod/stage-report.json",
        "stage-report.json",
    ),
)


def collect_peer_artifacts(
    config: HarnessConfig,
    peer: Peer,
    session_directory: Path,
) -> dict[str, Any]:
    output = (
        session_directory
        / "runtime-evidence"
        / f"{peer.role}-{peer.location}"
    )
    output.mkdir(parents=True, exist_ok=True)
    copied: dict[str, Any] = {}
    if peer.location == "local":
        stage = local_stage_root(config, peer)
        sources = [
            (stage / relative, name)
            for relative, name in ARTIFACTS
        ]
        logs = stage / ".sdmod/logs"
        if logs.is_dir():
            sources.extend(
                (path, path.name)
                for path in logs.glob("*crash*")
                if path.is_file()
            )
        for source, name in sources:
            if not source.is_file():
                continue
            destination = output / name
            shutil.copy2(source, destination)
            copied[name] = {
                "path": str(destination),
                "bytes": destination.stat().st_size,
                "sha256": sha256_file(destination),
            }
    else:
        remote_archive = remote_helper(
            config,
            "pack-artifacts",
            peer.instance,
            timeout=60,
        ).strip()
        expected_prefix = f"{config.remote_root}/evidence/"
        if (
            not remote_archive.startswith(expected_prefix)
            or not remote_archive.endswith("-artifacts.tar")
        ):
            raise VerificationFailure(
                "Remote artifact packer returned an unsafe path: "
                f"{remote_archive!r}"
            )
        local_archive = output / "remote-artifacts.tar"
        scp_from(
            config,
            remote_archive,
            local_archive,
            timeout=300,
        )
        names_by_relative = dict(ARTIFACTS)
        with tarfile.open(local_archive, "r:") as archive:
            for member in archive.getmembers():
                if not member.isfile():
                    raise VerificationFailure(
                        "Remote artifact archive contained a non-file: "
                        f"{member.name!r}"
                    )
                name = names_by_relative.get(member.name)
                if (
                    name is None
                    and member.name.startswith(".sdmod/logs/")
                    and "crash" in Path(member.name).name.casefold()
                ):
                    name = Path(member.name).name
                if (
                    name is None
                    and member.name.startswith(".sdmod/logs/")
                    and Path(member.name).name.startswith(
                        "netlag-wave-"
                    )
                    and Path(member.name).suffix.casefold() == ".bmp"
                ):
                    name = Path(member.name).name
                if name is None:
                    raise VerificationFailure(
                        "Remote artifact archive contained an "
                        f"unexpected member: {member.name!r}"
                    )
                source = archive.extractfile(member)
                if source is None:
                    raise VerificationFailure(
                        f"Could not read remote artifact {member.name!r}."
                    )
                destination = output / name
                with source, destination.open("xb") as destination_stream:
                    shutil.copyfileobj(source, destination_stream)
                copied[name] = {
                    "remoteArchive": remote_archive,
                    "remoteMember": member.name,
                    "path": str(destination),
                    "bytes": destination.stat().st_size,
                    "sha256": sha256_file(destination),
                }
        copied["remote-artifacts.tar"] = {
            "remotePath": remote_archive,
            "path": str(local_archive),
            "bytes": local_archive.stat().st_size,
            "sha256": sha256_file(local_archive),
        }
    return copied


def find_crash_artifacts(
    peer: Peer,
    session_directory: Path,
) -> list[dict[str, Any]]:
    logs = (
        session_directory
        / "runtime-evidence"
        / f"{peer.role}-{peer.location}"
    )
    if not logs.is_dir():
        return []
    return [
        {
            "path": str(path),
            "bytes": path.stat().st_size,
        }
        for path in logs.glob("*crash*")
        if path.is_file() and path.stat().st_size > 0
    ]


def stop_peer(
    config: HarnessConfig,
    peer: Peer,
    session_directory: Path,
) -> dict[str, Any]:
    if peer.location == "local":
        return stop_local_peer(session_directory, peer)
    output = remote_helper(config, "stop", timeout=45)
    return {
        "stopped": True,
        "remainingOwnedProcesses": output.strip(),
    }


def wait_peer_scene(
    config: HarnessConfig,
    peer: Peer,
    scene: str,
    *,
    timeout: float,
) -> dict[str, str]:
    return wait_for(
        lambda: peer_values(config, peer, SCENE_PROBE),
        lambda values: values.get("scene") == scene,
        label=f"{peer.location} {peer.role} scene {scene}",
        timeout=timeout,
        interval=0.05,
    )


def run_session(
    config: HarnessConfig,
    *,
    phase: Literal["before", "after"],
    direction: Direction,
    run_index: int,
) -> dict[str, Any]:
    phase_token = "pre" if phase == "before" else "post"
    instance_prefix = (
        f"netlag-{phase_token}-{direction}{run_index:02d}"
    )
    host, client = direction_peers(
        config,
        direction,
        instance_prefix,
    )
    session_directory = (
        config.evidence_root
        / phase
        / f"direction-{direction}"
        / f"run-{run_index:02d}"
    )
    result_path = session_directory / "session-result.json"
    if result_path.exists():
        raise VerificationFailure(
            f"Refusing to overwrite an existing WAN session: "
            f"{result_path}"
        )
    session_directory.mkdir(parents=True, exist_ok=True)
    result: dict[str, Any] = {
        "success": False,
        "phase": phase,
        "direction": direction,
        "runIndex": run_index,
        "sessionDirectory": str(session_directory),
        "instancePrefix": instance_prefix,
        "startedUtc": utc_now(),
        "host": {
            "location": host.location,
            "port": host.local_port,
            "instance": host.instance,
        },
        "clientB": {
            "location": client.location,
            "port": client.local_port,
            "instance": client.instance,
        },
        "scenario": {
            "humanEquivalentPeers": 2,
            "bots": [
                {
                    "name": "Ember",
                    "element": "fire",
                    "behavior": "skirmisher",
                },
                {
                    "name": "Brook",
                    "element": "water",
                    "behavior": "striker",
                },
            ],
            "rosterCapacity": 4,
            "waveTarget": 5,
            "hubEntryFlow":
                "stock semantic UI actions through create; native "
                "multiplayer quick-start is disabled because it does "
                "not initialize a playable Boneyard run",
            "waveStartFlow":
                "client B enters the real Solomon_Dig proximity "
                "interaction after sd.hub.start_testrun; native "
                "Solomon state owns combat prelude and wave start",
            "solomonDigFlowUsed": True,
            "solomonDigDiscovery": "sd.world.list_actors",
            "solomonDigInitiator": CLIENT_NAME,
            "luaWaveStartUsed": False,
            "audioDisabled": True,
        },
    }
    launched: list[Peer] = []
    failure: BaseException | None = None
    try:
        result["preflight"] = preflight_ports(config)
        result["clockBefore"] = measure_clock_offset(config)
        result["launch"] = {
            "host": launch_peer(
                config, host, session_directory
            )
        }
        launched.append(host)
        result["hubEntry"] = {
            "host": enter_hub_through_stock_ui(config, host)
        }
        result["hostHub"] = wait_peer_scene(
            config,
            host,
            "hub",
            timeout=120,
        )
        result["launch"]["clientB"] = launch_peer(
            config, client, session_directory
        )
        launched.append(client)
        result["hubEntry"]["clientB"] = (
            enter_hub_through_stock_ui(config, client)
        )
        result["clientHub"] = wait_peer_scene(
            config,
            client,
            "hub",
            timeout=120,
        )
        result["fourSeatHub"] = wait_pair_roster(
            config,
            host,
            client,
            scene="hub",
            timeout=120,
        )
        result["survivalGuard"] = {
            "host": arm_human_survival_guard(config, host),
            "clientB": arm_human_survival_guard(
                config, client
            ),
            "scope": "human HP only; bots, movement, transport, "
                     "waves, and rendering remain live",
        }
        result["clientHitObserver"] = arm_client_hit_observer(
            config, client
        )
        result["solomonDigArm"] = {
            "host": arm_solomon_dig_flow(config, host),
            "clientB": arm_solomon_dig_flow(config, client),
        }
        result["waveScreenshotArm"] = {
            "host": arm_wave_screenshot_capture(
                config,
                host,
                session_directory,
            ),
            "clientB": arm_wave_screenshot_capture(
                config,
                client,
                session_directory,
            ),
        }
        result["runStart"] = start_testrun(config, host)
        result["runScene"] = {
            "host": wait_peer_scene(
                config, host, "testrun", timeout=45
            )
        }
        result["runScene"]["clientB"] = wait_peer_scene(
            config, client, "testrun", timeout=45
        )
        run_roster = wait_run_roster(config, host, client)
        result["fourSeatRun"] = run_roster["views"]
        if run_roster["recovery"] is not None:
            result["runBotMaterializationRecovery"] = (
                run_roster["recovery"]
            )
        result["solomonDigPlacement"] = place_client_at_solomon(
            config,
            client,
        )
        result["solomonDig"] = wait_client_solomon_dig(
            config,
            host,
            client,
        )
        result["waveStart"] = wait_retail_wave_start(
            config, host
        )
        result["waveFive"] = monitor_wave_five(
            config,
            host,
            client,
            session_directory,
            timeout=config.timeout_seconds,
        )
        if not result["waveFive"]["success"]:
            raise VerificationFailure(
                "Wave-five acceptance failed: "
                f"{result['waveFive']['validation']}"
            )
        result["success"] = True
    except BaseException as error:
        failure = error
        result["errorType"] = type(error).__name__
        result["error"] = str(error)
    finally:
        result["finishedScenarioUtc"] = utc_now()
        close_lua_streams(config)
        cleanup: dict[str, Any] = {}
        for peer in reversed(launched):
            key = f"{peer.role}-{peer.location}"
            try:
                cleanup[key] = stop_peer(
                    config, peer, session_directory
                )
            except BaseException as cleanup_error:
                cleanup[key] = {
                    "error": (
                        f"{type(cleanup_error).__name__}: "
                        f"{cleanup_error}"
                    )
                }
                if failure is None:
                    failure = cleanup_error
                    result["success"] = False
                    result["errorType"] = type(
                        cleanup_error
                    ).__name__
                    result["error"] = str(cleanup_error)
        result["cleanup"] = cleanup

        try:
            result["postStopRemoteOwnedProcesses"] = (
                remote_helper(config, "status").strip()
            )
            if result["postStopRemoteOwnedProcesses"]:
                raise VerificationFailure(
                    "NFO-owned processes remained after session stop: "
                    + result["postStopRemoteOwnedProcesses"]
                )
            result["clockAfter"] = measure_clock_offset(config)
            evidence_keys = {
                host: "host",
                client: "clientB",
            }
            result["runtimeEvidence"] = {
                evidence_keys[peer]: collect_peer_artifacts(
                    config, peer, session_directory
                )
                for peer in launched
            }
            result["crashArtifacts"] = {
                evidence_keys[peer]: find_crash_artifacts(
                    peer, session_directory
                )
                for peer in launched
            }
            nonempty_crashes = [
                row
                for rows in result["crashArtifacts"].values()
                for row in rows
            ]
            if nonempty_crashes:
                raise VerificationFailure(
                    "A peer produced a nonempty crash artifact: "
                    f"{nonempty_crashes}"
                )

            host_telemetry = (
                session_directory
                / "runtime-evidence"
                / f"{host.role}-{host.location}"
                / "network-telemetry.jsonl"
            )
            client_telemetry = (
                session_directory
                / "runtime-evidence"
                / f"{client.role}-{client.location}"
                / "network-telemetry.jsonl"
            )
            if (
                host_telemetry.is_file()
                and client_telemetry.is_file()
            ):
                result["telemetryAnalysis"] = analyze_pair(
                    host_telemetry, client_telemetry
                )
                atomic_write_json(
                    session_directory
                    / "telemetry-analysis.json",
                    result["telemetryAnalysis"],
                )
            elif len(launched) == 2:
                raise VerificationFailure(
                    "Launched peers did not both produce network "
                    f"telemetry: host={host_telemetry.is_file()} "
                    f"client={client_telemetry.is_file()}"
                )
            finalize_deferred_screenshots(
                result, session_directory
            )
        except BaseException as evidence_error:
            result["evidenceError"] = (
                f"{type(evidence_error).__name__}: "
                f"{evidence_error}"
            )
            if failure is None:
                failure = evidence_error
                result["success"] = False
                result["errorType"] = type(
                    evidence_error
                ).__name__
                result["error"] = str(evidence_error)
        result["finishedUtc"] = utc_now()
        atomic_write_json(result_path, result)
    return result


def run_matrix(
    config: HarnessConfig,
    *,
    phase: Literal["before", "after"],
    directions: Sequence[Direction],
    runs_per_direction: int,
) -> dict[str, Any]:
    if runs_per_direction < 1:
        raise VerificationFailure(
            "runs_per_direction must be positive."
        )
    summary: dict[str, Any] = {
        "phase": phase,
        "startedUtc": utc_now(),
        "runsPerDirection": runs_per_direction,
        "directions": list(directions),
        "sessions": [],
        "success": False,
    }
    output_path = (
        config.evidence_root / phase / "matrix-result.json"
    )
    for direction in directions:
        for run_index in range(1, runs_per_direction + 1):
            try:
                result = run_session(
                    config,
                    phase=phase,
                    direction=direction,
                    run_index=run_index,
                )
            except BaseException as error:
                result = {
                    "success": False,
                    "phase": phase,
                    "direction": direction,
                    "runIndex": run_index,
                    "errorType": type(error).__name__,
                    "error": str(error),
                }
            summary["sessions"].append(
                {
                    "direction": direction,
                    "runIndex": run_index,
                    "success": bool(result.get("success")),
                    "result": str(
                        config.evidence_root
                        / phase
                        / f"direction-{direction}"
                        / f"run-{run_index:02d}"
                        / "session-result.json"
                    ),
                    "error": result.get("error"),
                }
            )
            atomic_write_json(output_path, summary)
    summary["finishedUtc"] = utc_now()
    summary["success"] = all(
        session["success"] for session in summary["sessions"]
    )
    atomic_write_json(output_path, summary)
    return summary


def aggregate_phase(
    config: HarnessConfig,
    phase: Literal["before", "after"],
) -> dict[str, Any]:
    session_paths = sorted(
        (config.evidence_root / phase).glob(
            "direction-*/run-*/session-result.json"
        )
    )
    sessions: list[dict[str, Any]] = []
    all_arrival_gaps: list[int] = []
    all_apply_durations: list[int] = []
    all_present_gaps: list[int] = []
    all_batch_sizes: list[int] = []
    stages: Counter[str] = Counter()
    for path in session_paths:
        document = json.loads(path.read_text(encoding="utf-8"))
        analysis_path = path.with_name(
            "telemetry-analysis.json"
        )
        analysis = (
            json.loads(
                analysis_path.read_text(encoding="utf-8")
            )
            if analysis_path.is_file()
            else document.get("telemetryAnalysis")
        )
        row: dict[str, Any] = {
            "direction": document.get("direction"),
            "runIndex": document.get("runIndex"),
            "scenarioSuccess": bool(document.get("success")),
            "result": str(path),
            "error": document.get("error"),
            "hardTransportStallCount": 0,
            "hardPresentSpikeCount": 0,
            "maximumTransportStallUs": 0,
            "maximumPresentGapUs": 0,
        }
        if isinstance(analysis, dict):
            stalls = analysis.get("clientTransportStalls", [])
            spikes = analysis.get("clientSpikes", [])
            row["hardTransportStallCount"] = len(stalls)
            row["hardPresentSpikeCount"] = len(spikes)
            row["maximumTransportStallUs"] = max(
                (
                    int(stall.get("durationUs", 0))
                    for stall in stalls
                ),
                default=0,
            )
            row["maximumPresentGapUs"] = max(
                (
                    int(spike.get("durationUs", 0))
                    for spike in spikes
                ),
                default=0,
            )
            row["transportStallStages"] = dict(
                Counter(
                    str(stall.get("stage", "unknown"))
                    for stall in stalls
                )
            )
            stages.update(row["transportStallStages"])
            client_summary = analysis.get("client", {})
            row["oversizedDatagramCount"] = int(
                client_summary.get(
                    "oversizedDatagramCount", 0
                )
            )
            row["holdingStaleCount"] = int(
                client_summary.get("holdingStaleCount", 0)
            )
            row["retransmitCount"] = int(
                client_summary.get("retransmitCount", 0)
            )
            row["hostToClientMissingCount"] = int(
                analysis.get("hostToClient", {}).get(
                    "missingCount", 0
                )
            )
            client_path = Path(
                str(analysis.get("clientTelemetry", ""))
            )
            if client_path.is_file():
                events = load_jsonl(client_path)
                all_arrival_gaps.extend(
                    wire_arrival_gaps(events)
                )
                all_apply_durations.extend(
                    int(event.get("duration_us", 0))
                    for event in event_rows(
                        events, "packet_apply"
                    )
                )
                all_present_gaps.extend(
                    int(event.get("gap_us", 0))
                    for event in event_rows(events, "present")
                    if int(event.get("gap_us", 0)) > 0
                )
                all_batch_sizes.extend(
                    int(event.get("packet_count", 0))
                    for event in event_rows(
                        events, "receive_batch"
                    )
                )
        sessions.append(row)

    aggregate = {
        "phase": phase,
        "generatedUtc": utc_now(),
        "sessionCount": len(sessions),
        "successfulWaveFiveSessions": sum(
            bool(row["scenarioSuccess"]) for row in sessions
        ),
        "hardTransportStallCount": sum(
            int(row["hardTransportStallCount"])
            for row in sessions
        ),
        "hardPresentSpikeCount": sum(
            int(row["hardPresentSpikeCount"])
            for row in sessions
        ),
        "maximumTransportStallUs": max(
            (
                int(row["maximumTransportStallUs"])
                for row in sessions
            ),
            default=0,
        ),
        "maximumPresentGapUs": max(
            (
                int(row["maximumPresentGapUs"])
                for row in sessions
            ),
            default=0,
        ),
        "transportStallStages": dict(stages),
        "clientArrivalGapUs": distribution(
            all_arrival_gaps
        ),
        "clientPacketApplyDurationUs": distribution(
            all_apply_durations
        ),
        "clientPresentGapUs": distribution(
            all_present_gaps
        ),
        "clientReceiveBatchSize": distribution(
            all_batch_sizes
        ),
        "sessions": sessions,
    }
    atomic_write_json(
        config.evidence_root / phase / "aggregate.json",
        aggregate,
    )
    return aggregate


def compare_phases(config: HarnessConfig) -> dict[str, Any]:
    before = aggregate_phase(config, "before")
    after = aggregate_phase(config, "after")
    comparison = {
        "generatedUtc": utc_now(),
        "before": before,
        "after": after,
        "delta": {
            "hardTransportStallCount": (
                after["hardTransportStallCount"]
                - before["hardTransportStallCount"]
            ),
            "hardPresentSpikeCount": (
                after["hardPresentSpikeCount"]
                - before["hardPresentSpikeCount"]
            ),
            "maximumTransportStallUs": (
                after["maximumTransportStallUs"]
                - before["maximumTransportStallUs"]
            ),
            "maximumPresentGapUs": (
                after["maximumPresentGapUs"]
                - before["maximumPresentGapUs"]
            ),
            "p99ArrivalGapUs": (
                after["clientArrivalGapUs"]["p99"]
                - before["clientArrivalGapUs"]["p99"]
            ),
            "p99PacketApplyDurationUs": (
                after["clientPacketApplyDurationUs"]["p99"]
                - before[
                    "clientPacketApplyDurationUs"
                ]["p99"]
            ),
        },
    }
    atomic_write_json(
        config.evidence_root / "before-after-comparison.json",
        comparison,
    )
    return comparison


def stop_all_owned(config: HarnessConfig) -> dict[str, Any]:
    result: dict[str, Any] = {
        "startedUtc": utc_now(),
        "local": [],
    }
    for ledger in sorted(
        config.evidence_root.glob(
            "**/*-local-process.json"
        )
    ):
        try:
            output = run_checked(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-NonInteractive",
                    "-ExecutionPolicy",
                    "Bypass",
                    "-File",
                    windows_path(LOCAL_STOP_SCRIPT),
                    "-ProcessLedgerPath",
                    windows_path(ledger),
                ],
                timeout=30,
            )
            result["local"].append(
                {"ledger": str(ledger), "result": output.strip()}
            )
        except BaseException as error:
            result["local"].append(
                {
                    "ledger": str(ledger),
                    "error": (
                        f"{type(error).__name__}: {error}"
                    ),
                }
            )
    result["remoteStop"] = remote_helper(
        config, "stop", timeout=45
    ).strip()
    result["remoteRemaining"] = remote_helper(
        config, "status"
    ).strip()
    result["finishedUtc"] = utc_now()
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__,
    )
    parser.add_argument(
        "--config",
        type=Path,
        required=True,
        help="Owner-scoped JSON configuration outside the repository.",
    )
    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
    )
    subparsers.add_parser("check-config")
    subparsers.add_parser("write-settings")
    subparsers.add_parser("diagnostics")

    analyze = subparsers.add_parser("analyze")
    analyze.add_argument("--host-telemetry", type=Path, required=True)
    analyze.add_argument("--client-telemetry", type=Path, required=True)
    analyze.add_argument("--output", type=Path)

    run_one = subparsers.add_parser("run-session")
    run_one.add_argument(
        "--phase",
        choices=("before", "after"),
        required=True,
    )
    run_one.add_argument(
        "--direction",
        choices=("a", "b"),
        required=True,
    )
    run_one.add_argument("--run-index", type=int, required=True)

    run_all = subparsers.add_parser("run-matrix")
    run_all.add_argument(
        "--phase",
        choices=("before", "after"),
        required=True,
    )
    run_all.add_argument(
        "--directions",
        nargs="+",
        choices=("a", "b"),
        default=("a", "b"),
    )
    run_all.add_argument(
        "--runs-per-direction",
        type=int,
        default=2,
    )

    aggregate = subparsers.add_parser("aggregate")
    aggregate.add_argument(
        "--phase",
        choices=("before", "after"),
        required=True,
    )
    subparsers.add_parser("compare")
    subparsers.add_parser("stop-owned")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        config = load_config(args.config)
        if args.command == "check-config":
            result = validate_staged_config(config)
        elif args.command == "write-settings":
            result = write_bot_settings(config)
        elif args.command == "diagnostics":
            validate_staged_config(config)
            result = {
                "preflight": preflight_ports(config),
                "clock": measure_clock_offset(config),
                "path": collect_path_diagnostics(config),
            }
            atomic_write_json(
                config.evidence_root
                / "baseline"
                / "wan-path-diagnostics.json",
                result,
            )
        elif args.command == "analyze":
            result = analyze_pair(
                args.host_telemetry.resolve(),
                args.client_telemetry.resolve(),
            )
            if args.output is not None:
                atomic_write_json(
                    args.output.resolve(), result
                )
        elif args.command == "run-session":
            validate_staged_config(config)
            result = run_session(
                config,
                phase=args.phase,
                direction=args.direction,
                run_index=args.run_index,
            )
        elif args.command == "run-matrix":
            validate_staged_config(config)
            result = run_matrix(
                config,
                phase=args.phase,
                directions=args.directions,
                runs_per_direction=args.runs_per_direction,
            )
        elif args.command == "aggregate":
            result = aggregate_phase(
                config, args.phase
            )
        elif args.command == "compare":
            result = compare_phases(config)
        elif args.command == "stop-owned":
            result = stop_all_owned(config)
        else:
            raise VerificationFailure(
                f"Unsupported command: {args.command}"
            )
        console_result = result
        if args.command == "run-session":
            wave_five = result.get("waveFive", {})
            telemetry = result.get("telemetryAnalysis", {})
            console_result = {
                "success": bool(result.get("success")),
                "phase": result.get("phase"),
                "direction": result.get("direction"),
                "runIndex": result.get("runIndex"),
                "error": result.get("error"),
                "result": str(
                    config.evidence_root
                    / args.phase
                    / f"direction-{args.direction}"
                    / f"run-{args.run_index:02d}"
                    / "session-result.json"
                ),
                "highestWave": wave_five.get("highestWave"),
                "validation": wave_five.get("validation"),
                "clientHardPresentSpikes": len(
                    telemetry.get("clientSpikes", [])
                ),
                "clientTransportStalls": len(
                    telemetry.get("clientTransportStalls", [])
                ),
            }
        print(json.dumps(console_result, indent=2, sort_keys=True))
        return 0 if result.get("success", True) else 1
    except (
        VerificationFailure,
        OSError,
        subprocess.SubprocessError,
        json.JSONDecodeError,
    ) as error:
        print(
            f"FAIL: {type(error).__name__}: {error}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
