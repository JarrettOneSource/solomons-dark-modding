from __future__ import annotations

import base64
from dataclasses import dataclass
import hashlib
import json
import ntpath
import os
from pathlib import Path
import re
import select
import shutil
import struct
import subprocess
import tempfile
import threading
import time
from typing import Any

from PIL import Image

from .config import HarnessConfig, PeerConfig
from .runtime import LuaPipe, RuntimeProbeError, parse_key_values
from .windows import (
    PowerShell,
    WindowsPeer,
    launch_environment,
    prepare_windows_peer,
    ps_quote,
    windows_path,
)


MAXIMUM_FRAME_BYTES = 16 * 1024 * 1024
BRIDGE_PING_LENGTH = 0xFFFFFFFF


class Ws20HarnessError(RuntimeError):
    """The workstation20 Steam peer could not be controlled safely."""


def _format_lua_response(raw: str) -> str:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return raw
    if not isinstance(value, dict) or "ok" not in value:
        return raw
    printed = value.get("print_output")
    pieces: list[str] = []
    if isinstance(printed, str) and printed:
        pieces.append(printed.rstrip("\r\n"))
    results = value.get("results")
    if isinstance(results, list):
        pieces.extend(str(item) for item in results)
    if not value.get("ok"):
        error = str(value.get("error") or "Lua execution failed")
        raise RuntimeProbeError(error)
    return "\n".join(pieces)


class RemoteWindowsLuaBridge:
    """Relay framed Lua through an SSH-forwarded ws20 loopback listener."""

    def __init__(
        self,
        peer: PeerConfig,
        *,
        key_path: str | None = None,
        stage_root: str | None = None,
    ) -> None:
        if peer.ssh is None:
            raise Ws20HarnessError("ws20 client is missing SSH configuration")
        self.peer = peer
        self.ssh = peer.ssh
        self.key_path = key_path or self.ssh.key_path
        self.stage_root = stage_root or self.ssh.stage_root
        self._server: subprocess.Popen[bytes] | None = None
        self._tunnel: subprocess.Popen[bytes] | None = None
        self._lock = threading.Lock()
        self.last_execution_utc_nanoseconds = 0

    @property
    def bridge_path(self) -> str:
        return (
            self.stage_root.rstrip("\\/")
            + r"\tools\Invoke-RemoteLuaExecBridge.ps1"
        )

    def _ssh_base(self) -> list[str]:
        arguments = [
            self.ssh.executable,
            "-T",
            "-i",
            self.key_path,
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=10",
            "-o",
            "ServerAliveInterval=15",
            "-o",
            "ServerAliveCountMax=2",
        ]
        return arguments

    @staticmethod
    def _read_exact(
        process: subprocess.Popen[bytes],
        size: int,
        deadline: float,
    ) -> bytes:
        if process.stdout is None:
            raise Ws20HarnessError("remote bridge has no stdout pipe")
        chunks: list[bytes] = []
        remaining = size
        descriptor = process.stdout.fileno()
        while remaining:
            wait = deadline - time.monotonic()
            if wait <= 0 or not select.select([descriptor], [], [], wait)[0]:
                raise TimeoutError("remote Windows Lua bridge timed out")
            chunk = os.read(descriptor, remaining)
            if not chunk:
                raise EOFError("remote Windows Lua bridge closed its stream")
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)

    @classmethod
    def _read_line(
        cls,
        process: subprocess.Popen[bytes],
        deadline: float,
    ) -> str:
        data = bytearray()
        while len(data) < 256:
            byte = cls._read_exact(process, 1, deadline)
            if byte == b"\n":
                return data.decode("utf-8", "replace").rstrip("\r")
            data.extend(byte)
        raise Ws20HarnessError("remote bridge startup line is too long")

    @staticmethod
    def _exit_detail(process: subprocess.Popen[bytes] | None) -> str:
        if (
            process is None
            or process.stderr is None
            or process.poll() is None
        ):
            return ""
        try:
            return process.stderr.read().decode("utf-8", "replace").strip()
        except OSError:
            return ""

    def _start(self) -> subprocess.Popen[bytes]:
        if (
            self._tunnel is not None
            and self._tunnel.poll() is None
            and self._server is not None
            and self._server.poll() is None
        ):
            return self._tunnel
        self.close()
        bridge = self.bridge_path.replace("'", "''")
        pipe_name = self.peer.pipe_name.replace("'", "''")
        command = (
            "$ProgressPreference='SilentlyContinue';"
            "$ErrorActionPreference='Stop';"
            f"& '{bridge}' -ListenPort 0 -PipeName '{pipe_name}' "
            "-MaximumResponseTimeoutMilliseconds 300000 "
            "-IncludeExecutionUtcNanoseconds"
        )
        encoded = base64.b64encode(
            command.encode("utf-16le")
        ).decode("ascii")
        server = subprocess.Popen(
            [
                *self._ssh_base(),
                self.ssh.target,
                "powershell.exe -NoLogo -NoProfile -NonInteractive "
                "-OutputFormat Text -ExecutionPolicy Bypass "
                f"-EncodedCommand {encoded}",
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            bufsize=0,
        )
        self._server = server
        try:
            line = self._read_line(server, time.monotonic() + 20.0)
            match = re.fullmatch(r"SDMOD_BRIDGE_PORT=([0-9]+)", line)
            if match is None:
                raise Ws20HarnessError(
                    f"remote bridge returned invalid startup text: {line!r}"
                )
            port = int(match.group(1))
            if not 1 <= port <= 65535:
                raise Ws20HarnessError(
                    f"remote bridge returned invalid port: {port}"
                )
            tunnel = subprocess.Popen(
                [
                    *self._ssh_base(),
                    "-W",
                    f"127.0.0.1:{port}",
                    self.ssh.target,
                ],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
            )
            self._tunnel = tunnel
            if tunnel.stdin is None:
                raise Ws20HarnessError("remote bridge has no stdin pipe")
            tunnel.stdin.write(
                struct.pack("<II", BRIDGE_PING_LENGTH, 100)
            )
            tunnel.stdin.flush()
            response_size, _ = struct.unpack(
                "<IQ",
                self._read_exact(
                    tunnel,
                    12,
                    time.monotonic() + 15.0,
                ),
            )
            if response_size != 0:
                raise Ws20HarnessError(
                    "remote bridge returned a nonempty ping response"
                )
            return tunnel
        except BaseException as exc:
            detail = "; ".join(
                item
                for item in (
                    self._exit_detail(self._tunnel),
                    self._exit_detail(self._server),
                )
                if item
            )
            self.close()
            suffix = f": {detail}" if detail else ""
            raise Ws20HarnessError(
                f"remote bridge startup failed: {exc}{suffix}"
            ) from exc

    def execute(self, code: str, timeout: float) -> str:
        request = code.encode("utf-8")
        if not request or len(request) > MAXIMUM_FRAME_BYTES:
            raise RuntimeProbeError(
                f"invalid remote Lua request size: {len(request)}"
            )
        response_timeout = min(300.0, max(0.1, timeout))
        response_timeout_ms = max(100, round(response_timeout * 1000))
        with self._lock:
            process = self._start()
            if process.stdin is None:
                raise Ws20HarnessError("remote bridge has no stdin pipe")
            try:
                process.stdin.write(
                    struct.pack(
                        "<II",
                        len(request),
                        response_timeout_ms,
                    )
                )
                process.stdin.write(request)
                process.stdin.flush()
                deadline = time.monotonic() + response_timeout + 6.0
                response_size, execution_utc_nanoseconds = struct.unpack(
                    "<IQ",
                    self._read_exact(process, 12, deadline),
                )
                self.last_execution_utc_nanoseconds = (
                    execution_utc_nanoseconds
                )
                if response_size > MAXIMUM_FRAME_BYTES:
                    raise RuntimeProbeError(
                        "remote Lua response exceeded the frame limit"
                    )
                raw = self._read_exact(
                    process,
                    response_size,
                    deadline,
                ).decode("utf-8", "replace")
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
                raise RuntimeProbeError(
                    f"remote Lua bridge failed: {exc}{suffix}"
                ) from exc
        return _format_lua_response(raw)

    def close(self) -> None:
        tunnel = self._tunnel
        server = self._server
        self._tunnel = None
        self._server = None
        if (
            tunnel is not None
            and tunnel.poll() is None
            and tunnel.stdin is not None
        ):
            try:
                tunnel.stdin.write(struct.pack("<II", 0, 100))
                tunnel.stdin.flush()
                self._read_exact(
                    tunnel,
                    12,
                    time.monotonic() + 1.0,
                )
            except (
                BrokenPipeError,
                EOFError,
                OSError,
                TimeoutError,
                struct.error,
            ):
                pass
        if tunnel is not None and tunnel.stdin is not None:
            try:
                tunnel.stdin.close()
            except OSError:
                pass
        for process in (tunnel, server):
            if process is None:
                continue
            try:
                process.wait(timeout=3.0)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    process.wait(timeout=3.0)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3.0)


class RemoteWindowsLuaPipe(LuaPipe):
    """LuaPipe-compatible state reader for the staged ws20 game."""

    def __init__(
        self,
        peer: PeerConfig,
        *,
        timeout_seconds: float = 8.0,
        key_path: str | None = None,
        stage_root: str | None = None,
    ) -> None:
        self.source_root = Path()
        self.name = peer.pipe_name
        self.timeout_seconds = timeout_seconds
        self.bridge = RemoteWindowsLuaBridge(
            peer,
            key_path=key_path,
            stage_root=stage_root,
        )

    def execute(self, code: str) -> str:
        return self.bridge.execute(code, self.timeout_seconds)

    def close(self) -> None:
        self.bridge.close()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class RemoteWindowsConnection:
    """Bounded SSH/SCP access to the temporary workstation20 stage."""

    def __init__(self, peer: PeerConfig) -> None:
        if peer.ssh is None:
            raise Ws20HarnessError("ws20 client is missing SSH configuration")
        self.ssh = peer.ssh
        source_key = Path(self.ssh.key_path).expanduser().resolve()
        if not source_key.is_file():
            raise Ws20HarnessError("the configured ws20 SSH key is missing")
        descriptor, copied_key = tempfile.mkstemp(
            prefix="sd-netrepro-ws20-key.",
            dir="/tmp",
        )
        os.close(descriptor)
        self.key_path = Path(copied_key)
        shutil.copyfile(source_key, self.key_path)
        self.key_path.chmod(0o600)
        self.stage_root = ""
        try:
            self.stage_root = self.run_ps(
                """
$expected=Join-Path $env:USERPROFILE 'sd-netrepro-stage'
[Console]::Out.Write([System.IO.Path]::GetFullPath($expected).TrimEnd('\\'))
"""
            )
            if not re.fullmatch(
                r"[A-Za-z]:\\Users\\[^\\]+\\sd-netrepro-stage",
                self.stage_root,
                flags=re.IGNORECASE,
            ):
                raise Ws20HarnessError(
                    "workstation20 returned an unsafe staging root"
                )
        except BaseException:
            self.close()
            raise

    def _ssh_base(self) -> list[str]:
        return [
            self.ssh.executable,
            "-T",
            "-i",
            str(self.key_path),
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=10",
            "-o",
            "ServerAliveInterval=15",
            "-o",
            "ServerAliveCountMax=2",
        ]

    def _scp_executable(self) -> str:
        executable = Path(self.ssh.executable)
        if executable.name == "ssh":
            candidate = executable.with_name("scp")
            return str(candidate)
        return "scp"

    def _scp_base(self) -> list[str]:
        return [
            self._scp_executable(),
            "-q",
            "-i",
            str(self.key_path),
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=10",
            "-o",
            "ServerAliveInterval=15",
            "-o",
            "ServerAliveCountMax=2",
        ]

    def run_ps(self, script: str, *, timeout: float = 60.0) -> str:
        prefix = (
            "$ErrorActionPreference='Stop';"
            "$ProgressPreference='SilentlyContinue';"
            "$OutputEncoding=[System.Text.UTF8Encoding]::new($false);"
            "[Console]::OutputEncoding="
            "[System.Text.UTF8Encoding]::new($false);"
        )
        encoded = base64.b64encode(
            (prefix + script).encode("utf-16le")
        ).decode("ascii")
        completed = subprocess.run(
            [
                *self._ssh_base(),
                self.ssh.target,
                "powershell.exe -NoLogo -NoProfile -NonInteractive "
                "-OutputFormat Text -ExecutionPolicy Bypass "
                f"-EncodedCommand {encoded}",
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            check=False,
        )
        output = completed.stdout.decode("utf-8", "replace").lstrip("\ufeff")
        if completed.returncode != 0:
            raise Ws20HarnessError(
                "remote Windows PowerShell failed "
                f"({completed.returncode})"
            )
        return output.strip()

    def sanitize_text(self, value: str) -> str:
        sanitized = value.replace(self.ssh.target, "workstation20")
        stage_root = getattr(self, "stage_root", "")
        if stage_root:
            sanitized = re.sub(
                re.escape(stage_root),
                r"%USERPROFILE%\\sd-netrepro-stage",
                sanitized,
                flags=re.IGNORECASE,
            )
        return sanitized

    def run_ps_json(
        self,
        script: str,
        *,
        timeout: float = 60.0,
    ) -> dict[str, Any]:
        output = self.run_ps(script, timeout=timeout)
        try:
            parsed = json.loads(output)
        except json.JSONDecodeError as exc:
            raise Ws20HarnessError(
                f"remote Windows returned invalid JSON: {output!r}"
            ) from exc
        if not isinstance(parsed, dict):
            raise Ws20HarnessError(
                "remote Windows JSON result was not an object"
            )
        return parsed

    @staticmethod
    def _scp_path(path: str) -> str:
        return path.replace("\\", "/")

    def copy_file_to(self, source: Path, destination: str) -> None:
        if not source.is_file():
            raise Ws20HarnessError(f"upload source is missing: {source}")
        completed = subprocess.run(
            [
                *self._scp_base(),
                str(source),
                f"{self.ssh.target}:{self._scp_path(destination)}",
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=180,
            check=False,
        )
        if completed.returncode != 0:
            raise Ws20HarnessError(
                "workstation20 file upload failed "
                f"({completed.returncode})"
            )

    def copy_tree_to(
        self,
        source: Path,
        destination_parent: str,
        *,
        timeout: float = 900.0,
    ) -> None:
        if not source.is_dir():
            raise Ws20HarnessError(f"upload directory is missing: {source}")
        completed = subprocess.run(
            [
                *self._scp_base(),
                "-r",
                str(source),
                f"{self.ssh.target}:{self._scp_path(destination_parent)}",
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            check=False,
        )
        if completed.returncode != 0:
            raise Ws20HarnessError(
                "workstation20 directory upload failed "
                f"({completed.returncode})"
            )

    def copy_file_from(self, source: str, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            raise Ws20HarnessError(
                f"download destination must be new: {destination}"
            )
        completed = subprocess.run(
            [
                *self._scp_base(),
                f"{self.ssh.target}:{self._scp_path(source)}",
                str(destination),
            ],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=180,
            check=False,
        )
        if completed.returncode != 0:
            raise Ws20HarnessError(
                "workstation20 file download failed "
                f"({completed.returncode})"
            )

    def _require_confined(self, path: str) -> None:
        prefix = self.stage_root.rstrip("\\") + "\\"
        if not path.casefold().startswith(prefix.casefold()):
            raise Ws20HarnessError(
                "refusing a remote path outside the workstation20 stage"
            )

    def remove_tree(self, path: str) -> None:
        self._require_confined(path)
        escaped = path.replace("'", "''")
        escaped_stage = self.stage_root.replace("'", "''")
        self.run_ps(
            f"""
$target=[System.IO.Path]::GetFullPath('{escaped}').TrimEnd('\\')
$stage=[System.IO.Path]::GetFullPath('{escaped_stage}').TrimEnd('\\')
if(-not $target.StartsWith(
    $stage + '\\',
    [System.StringComparison]::OrdinalIgnoreCase)){{
  throw 'Deletion target escaped the workstation20 stage.'
}}
if(Test-Path -LiteralPath $target){{
  & $env:ComSpec /d /c rd /s /q ('\\\\?\\' + $target)
  if($LASTEXITCODE -ne 0 -or (Test-Path -LiteralPath $target)){{
    throw 'The exact workstation20 run root remained after deletion.'
  }}
}}
"""
        )

    def inventory(self) -> dict[str, int]:
        escaped_stage = self.stage_root.replace("'", "''")
        result = self.run_ps_json(
            f"""
$prefix=[System.IO.Path]::GetFullPath('{escaped_stage}').TrimEnd('\\') + '\\'
$owned=@(
  Get-CimInstance Win32_Process |
    Where-Object {{
      -not [string]::IsNullOrWhiteSpace($_.ExecutablePath) -and
      $_.ExecutablePath.StartsWith(
        $prefix,
        [System.StringComparison]::OrdinalIgnoreCase)
    }}
)
$tasks=@(
  Get-ScheduledTask -TaskName 'SolomonDarkNetrepro_*' `
    -ErrorAction SilentlyContinue
)
$steam=@(
  Get-Process steam -IncludeUserName -ErrorAction SilentlyContinue |
    Where-Object {{ $_.SessionId -gt 0 }}
)
[ordered]@{{
  ownedProcessCount=$owned.Count
  taskCount=$tasks.Count
  interactiveSteamCount=$steam.Count
}} | ConvertTo-Json -Compress
"""
        )
        return {
            "ownedProcessCount": int(result.get("ownedProcessCount", 0)),
            "taskCount": int(result.get("taskCount", 0)),
            "interactiveSteamCount": int(
                result.get("interactiveSteamCount", 0)
            ),
        }

    def file_info(self, path: str) -> dict[str, Any]:
        self._require_confined(path)
        escaped = path.replace("'", "''")
        return self.run_ps_json(
            f"""
$path='{escaped}'
if(Test-Path -LiteralPath $path -PathType Leaf){{
  $file=Get-Item -LiteralPath $path
  [ordered]@{{exists=$true;size=[int64]$file.Length}} |
    ConvertTo-Json -Compress
}}else{{
  [ordered]@{{exists=$false;size=0}} | ConvertTo-Json -Compress
}}
"""
        )

    def close(self) -> None:
        key_path = getattr(self, "key_path", None)
        if isinstance(key_path, Path):
            key_path.unlink(missing_ok=True)


@dataclass
class Ws20Peer:
    """WindowsPeer-compatible adapter for the isolated remote client B."""

    harness: HarnessConfig
    config: PeerConfig
    connection: RemoteWindowsConnection
    local_peer: WindowsPeer
    run_root: str
    bundle_root: str
    settings_root: str
    runtime_root: str
    ui_executable: str
    game_executable: str
    telemetry_path: str
    input_helper: str
    ui_pid: int = 0
    game_pid: int = 0
    lobby_id: int = 0
    explicit_launch_game: bool = False
    staged_hashes: dict[str, str] | None = None
    _action_counter: int = 0
    _lua_pipe: RemoteWindowsLuaPipe | None = None

    @classmethod
    def prepare(
        cls,
        harness: HarnessConfig,
        connection: RemoteWindowsConnection,
    ) -> "Ws20Peer":
        client = prepare_windows_peer(harness, harness.client)
        run_root = ntpath.join(
            connection.stage_root,
            "r",
            harness.run_name,
        )
        bundle_root = ntpath.join(run_root, client.bundle_root.name)
        game_directory = ntpath.join(
            run_root,
            harness.game_directory.name,
        )
        settings_root = ntpath.join(
            bundle_root,
            ".sdmod-test-data",
            harness.client.launcher_scope,
            "SolomonDarkMultiplayerBeta",
        )
        runtime_root = ntpath.join(settings_root, "runtime")
        game_executable = ntpath.join(
            runtime_root,
            "instances",
            harness.client.instance,
            "stage",
            "SolomonDark.exe",
        )
        telemetry_path = ntpath.join(
            ntpath.dirname(game_executable),
            ".sdmod",
            "logs",
            "network-telemetry.jsonl",
        )
        longest_path = ntpath.join(
            ntpath.dirname(game_executable),
            ".sdmod",
            "assets",
            "loading",
            "Wizards_dire_BG.png",
        )
        if len(longest_path) >= 248:
            raise Ws20HarnessError(
                "staged workstation20 runtime path exceeds the native "
                f"safe path budget ({len(longest_path)} >= 248)"
            )

        settings_path = client.settings_root / "settings.json"
        settings = json.loads(settings_path.read_text(encoding="utf-8"))
        settings["gameDirectory"] = game_directory
        settings_path.write_text(
            json.dumps(settings, indent=2) + "\n",
            encoding="utf-8",
        )

        local_tools = (
            harness.evidence_root / "staging" / "ws20-tools"
        )
        local_tools.mkdir(parents=True, exist_ok=False)
        input_executable = local_tools / "win32_real_input.exe"
        ps = PowerShell(harness.source_root)
        ps.run(
            "& "
            + ps_quote(
                windows_path(
                    harness.source_root
                    / "scripts"
                    / "Build-Win32RealInput.ps1"
                ),
            )
            + " -OutputPath "
            + ps_quote(windows_path(input_executable)),
            timeout=180,
        )
        if not input_executable.is_file():
            raise Ws20HarnessError(
                "the workstation20 real-input helper did not build"
            )

        if connection.run_ps(
            f"""
[Console]::Out.Write(
  [bool](Test-Path -LiteralPath '{run_root.replace("'", "''")}'))
"""
        ).casefold() == "true":
            raise Ws20HarnessError(
                "workstation20 run root must be new"
            )
        escaped_run = run_root.replace("'", "''")
        escaped_tools = ntpath.join(
            connection.stage_root,
            "tools",
        ).replace("'", "''")
        connection.run_ps(
            f"""
New-Item -ItemType Directory -Path '{escaped_run}' -Force | Out-Null
New-Item -ItemType Directory -Path '{escaped_tools}' -Force | Out-Null
"""
        )
        connection.copy_tree_to(client.bundle_root, run_root)
        connection.copy_tree_to(harness.game_directory, run_root)
        tool_sources = (
            harness.source_root
            / "scripts"
            / "Invoke-RealFlowWindowsSession.ps1",
            harness.source_root
            / "scripts"
            / "Run-RealFlowWindowsSessionWorker.ps1",
            harness.source_root
            / "scripts"
            / "Invoke-RemoteLuaExecBridge.ps1",
            input_executable,
        )
        remote_tools = ntpath.join(connection.stage_root, "tools")
        for source in tool_sources:
            connection.copy_file_to(
                source,
                ntpath.join(remote_tools, source.name),
            )

        local_hashes = {
            "launcherUi": _sha256(client.ui_executable),
            "launcherCli": _sha256(
                client.bundle_root
                / "launcher"
                / "SolomonDarkModLauncher.exe"
            ),
            "game": _sha256(
                harness.game_directory / "SolomonDark.exe"
            ),
            "inputHelper": _sha256(input_executable),
        }
        remote_paths = {
            "launcherUi": ntpath.join(
                bundle_root,
                "SolomonDarkMultiplayerBeta.exe",
            ),
            "launcherCli": ntpath.join(
                bundle_root,
                "launcher",
                "SolomonDarkModLauncher.exe",
            ),
            "game": ntpath.join(game_directory, "SolomonDark.exe"),
            "inputHelper": ntpath.join(
                remote_tools,
                input_executable.name,
            ),
        }
        path_rows = ",".join(
            (
                "[pscustomobject]@{label='"
                + label
                + "';path='"
                + path.replace("'", "''")
                + "'}"
            )
            for label, path in remote_paths.items()
        )
        remote_hashes = connection.run_ps_json(
            f"""
$rows=@({path_rows})
$values=[ordered]@{{}}
foreach($row in $rows){{
  if(-not (Test-Path -LiteralPath $row.path -PathType Leaf)){{
    throw "Missing staged file: $($row.label)"
  }}
  $values[$row.label]=(
    Get-FileHash -LiteralPath $row.path -Algorithm SHA256
  ).Hash.ToLowerInvariant()
}}
$values | ConvertTo-Json -Compress
"""
        )
        if remote_hashes != local_hashes:
            raise Ws20HarnessError(
                "workstation20 staged-file hashes do not match"
            )

        return cls(
            harness=harness,
            config=harness.client,
            connection=connection,
            local_peer=client,
            run_root=run_root,
            bundle_root=bundle_root,
            settings_root=settings_root,
            runtime_root=runtime_root,
            ui_executable=remote_paths["launcherUi"],
            game_executable=game_executable,
            telemetry_path=telemetry_path,
            input_helper=remote_paths["inputHelper"],
            staged_hashes=local_hashes,
        )

    def _invoke(
        self,
        action: str,
        request: dict[str, Any],
        *,
        timeout: int,
    ) -> dict[str, Any]:
        self._action_counter += 1
        safe_run_name = re.sub(
            r"[^a-z0-9-]",
            "-",
            self.harness.run_name,
        ).strip("-")
        token = f"{safe_run_name[:24]}-{self._action_counter:03d}"
        control_root = ntpath.join(
            self.connection.stage_root,
            "control",
            self.harness.run_name,
        )
        request_path = ntpath.join(
            control_root,
            f"{self._action_counter:03d}-request.json",
        )
        result_path = ntpath.join(
            control_root,
            f"{self._action_counter:03d}-result.json",
        )
        payload = {"Action": action, **request}
        encoded_payload = base64.b64encode(
            (
                json.dumps(payload, separators=(",", ":")) + "\n"
            ).encode("utf-8")
        ).decode("ascii")
        controller = ntpath.join(
            self.connection.stage_root,
            "tools",
            "Invoke-RealFlowWindowsSession.ps1",
        )
        quote = lambda value: "'" + value.replace("'", "''") + "'"
        output = self.connection.run_ps(
            "$requestPath="
            + quote(request_path)
            + "\n$requestParent=Split-Path -Parent $requestPath"
            + "\nNew-Item -ItemType Directory -Path $requestParent "
            "-Force | Out-Null"
            + "\n[System.IO.File]::WriteAllBytes("
            "$requestPath,[System.Convert]::FromBase64String("
            + quote(encoded_payload)
            + "))"
            + "\n& "
            + quote(controller)
            + " -StageRoot "
            + quote(self.connection.stage_root)
            + " -RequestPath "
            + quote(request_path)
            + " -ResultPath "
            + quote(result_path)
            + " -TaskToken "
            + quote(token)
            + f" -TimeoutSeconds {timeout}",
            timeout=timeout + 30,
        )
        try:
            result = json.loads(output.lstrip("\ufeff"))
        except json.JSONDecodeError as exc:
            raise Ws20HarnessError(
                "workstation20 controller returned invalid JSON"
            ) from exc
        if not isinstance(result, dict) or result.get("ok") is not True:
            raise Ws20HarnessError(
                "workstation20 interactive action did not succeed"
            )
        detail = result.get("detail")
        if not isinstance(detail, dict):
            raise Ws20HarnessError(
                "workstation20 interactive action returned no detail"
            )
        return detail

    def launch(self, lobby_id: int) -> dict[str, Any]:
        detail = self._invoke(
            "launch-client",
            {
                "LauncherExecutable": self.ui_executable,
                "LauncherRoot": self.bundle_root,
                "LauncherScope": self.config.launcher_scope,
                "Environment": launch_environment(self.harness, self),
                "Instance": self.config.instance,
                "LobbyId": str(lobby_id),
                "GameExecutable": self.game_executable,
                "TimeoutSeconds": round(self.harness.timeout_seconds),
            },
            timeout=min(
                600,
                round(self.harness.timeout_seconds) + 20,
            ),
        )
        self.ui_pid = int(detail.get("uiPid", 0))
        self.game_pid = int(detail.get("gamePid", 0))
        self.lobby_id = lobby_id
        self.explicit_launch_game = bool(
            detail.get("explicitLaunchGame", False)
        )
        if (
            self.ui_pid <= 0
            or self.game_pid <= 0
            or not self.explicit_launch_game
            or int(detail.get("lobbyId", 0)) != lobby_id
        ):
            raise Ws20HarnessError(
                "workstation20 client did not cross the explicit launcher "
                "boundary"
            )
        boundaries = detail.get("boundariesAtLaunch", {})
        if not isinstance(boundaries, dict):
            boundaries = {}
        return {
            "uiPid": self.ui_pid,
            "gamePid": self.game_pid,
            "lobbyId": lobby_id,
            "explicitLaunchGame": True,
            "sessionId": int(detail.get("sessionId", 0)),
            "boundariesAtLaunch": {
                "ready": bool(boundaries.get("ready", False)),
                "launchGame": bool(
                    boundaries.get("launchGame", False)
                ),
                "playerCount": str(
                    boundaries.get("playerCount", "")
                ),
            },
        }

    def open_lua_pipe(self) -> RemoteWindowsLuaPipe:
        if self._lua_pipe is None:
            self._lua_pipe = RemoteWindowsLuaPipe(
                self.config,
                timeout_seconds=8.0,
                key_path=str(self.connection.key_path),
                stage_root=self.connection.stage_root,
            )
        return self._lua_pipe

    def send_key(self, key: str, hold_ms: int) -> str:
        detail = self._invoke(
            "key",
            {
                "ProcessId": self.game_pid,
                "GameExecutable": self.game_executable,
                "InputHelper": self.input_helper,
                "Key": key,
                "HoldMilliseconds": hold_ms,
            },
            timeout=30,
        )
        return json.dumps(
            {
                "action": "key",
                "key": key,
                "holdMilliseconds": hold_ms,
                "processId": int(detail.get("processId", 0)),
            },
            sort_keys=True,
        )

    def click(self, x: float, y: float, hold_ms: int) -> str:
        detail = self._invoke(
            "click",
            {
                "ProcessId": self.game_pid,
                "GameExecutable": self.game_executable,
                "InputHelper": self.input_helper,
                "X": f"{x:.8f}",
                "Y": f"{y:.8f}",
                "HoldMilliseconds": hold_ms,
            },
            timeout=30,
        )
        return json.dumps(
            {
                "action": "click",
                "x": x,
                "y": y,
                "holdMilliseconds": hold_ms,
                "processId": int(detail.get("processId", 0)),
            },
            sort_keys=True,
        )

    def click_sequence(
        self,
        targets: list[tuple[float, float]],
        hold_ms: int,
        interval_ms: int,
    ) -> str:
        if not 2 <= len(targets) <= 8:
            raise Ws20HarnessError(
                "workstation20 click sequence must contain 2 through 8 targets"
            )
        if not 100 <= interval_ms <= 1500:
            raise Ws20HarnessError(
                "workstation20 click sequence interval must be 100 through "
                "1500 milliseconds"
            )
        detail = self._invoke(
            "click-sequence",
            {
                "ProcessId": self.game_pid,
                "GameExecutable": self.game_executable,
                "InputHelper": self.input_helper,
                "Targets": [
                    {"X": f"{x:.8f}", "Y": f"{y:.8f}"}
                    for x, y in targets
                ],
                "HoldMilliseconds": hold_ms,
                "IntervalMilliseconds": interval_ms,
            },
            timeout=30,
        )
        click_count = int(detail.get("clickCount", 0))
        if click_count != len(targets):
            raise Ws20HarnessError(
                "workstation20 click sequence returned an unexpected count"
            )
        return json.dumps(
            {
                "action": "click-sequence",
                "clickCount": click_count,
                "holdMilliseconds": hold_ms,
                "intervalMilliseconds": interval_ms,
                "processId": int(detail.get("processId", 0)),
            },
            sort_keys=True,
        )

    def capture_window(self, output: Path) -> dict[str, Any]:
        output.parent.mkdir(parents=True, exist_ok=True)
        if output.exists():
            raise Ws20HarnessError(
                f"capture output must be new: {output}"
            )
        remote_capture = ntpath.join(
            self.run_root,
            "captures",
            output.with_suffix(".bmp").name,
        )
        escaped_capture_root = ntpath.dirname(
            remote_capture
        ).replace("'", "''")
        self.connection.run_ps(
            "New-Item -ItemType Directory -Path '"
            + escaped_capture_root
            + "' -Force | Out-Null"
        )
        escaped_capture = json.dumps(remote_capture)
        started_ns = time.time_ns()
        response = self.open_lua_pipe().execute(
            "local ok,err=sd.debug.capture_backbuffer("
            + escaped_capture
            + ");print('ok='..tostring(ok));"
            "print('error='..tostring(err or ''))"
        )
        remote_capture_ns = (
            self.open_lua_pipe().bridge
            .last_execution_utc_nanoseconds
        )
        if remote_capture_ns <= 0:
            raise Ws20HarnessError(
                "workstation20 capture returned no remote wall-clock instant"
            )
        values = parse_key_values(response)
        if values.get("ok") != "true":
            raise Ws20HarnessError(
                "workstation20 D3D9 backbuffer capture failed"
            )
        raw = output.with_suffix(".bmp")
        self.connection.copy_file_from(remote_capture, raw)
        with Image.open(raw) as source:
            image = source.convert("RGB")
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
            if unique_colors < 1000 or dominant_fraction >= 0.85:
                raise Ws20HarnessError(
                    "workstation20 backbuffer capture was blank or "
                    "low-information"
                )
            image.save(output)
            size = [image.width, image.height]
        raw_size = raw.stat().st_size
        raw.unlink()
        ended_ns = time.time_ns()
        return {
            "path": str(output),
            "startedUtcNanoseconds": started_ns,
            "captureUtcNanoseconds": remote_capture_ns,
            "endedUtcNanoseconds": ended_ns,
            "captureMethod": "remote-d3d9-backbuffer",
            "rawBmpBytes": raw_size,
            "quality": {
                "width": size[0],
                "height": size[1],
                "uniqueColors": unique_colors,
                "dominantFraction": dominant_fraction,
            },
        }

    def close_lua_pipe(self) -> None:
        if self._lua_pipe is not None:
            self._lua_pipe.close()
            self._lua_pipe = None

    def close_processes(self) -> dict[str, Any]:
        self.close_lua_pipe()
        detail = self._invoke(
            "close",
            {"RunRoot": self.run_root},
            timeout=60,
        )
        graceful = detail.get("gracefulRequests", [])
        forced = detail.get("forced", [])
        return {
            "gracefulRequestCount": (
                len(graceful) if isinstance(graceful, list) else 0
            ),
            "forcedCount": (
                len(forced) if isinstance(forced, list) else 0
            ),
        }

    def copy_runtime_artifacts(
        self,
        output_directory: Path,
    ) -> dict[str, Any]:
        destination = output_directory / self.config.role
        destination.mkdir(parents=True, exist_ok=True)
        stage = ntpath.dirname(self.game_executable)
        candidates = {
            "networkTelemetry": self.telemetry_path,
            "loaderLog": ntpath.join(
                stage,
                ".sdmod",
                "logs",
                "solomondarkmodloader.log",
            ),
            "crashLog": ntpath.join(
                stage,
                ".sdmod",
                "logs",
                "solomondarkmodloader.crash.log",
            ),
            "startupStatus": ntpath.join(
                stage,
                ".sdmod",
                "startup-status.json",
            ),
            "multiplayerSessionStatus": ntpath.join(
                stage,
                ".sdmod",
                "multiplayer-session-status.json",
            ),
        }
        copied: dict[str, Any] = {}
        for label, source in candidates.items():
            info = self.connection.file_info(source)
            size = int(info.get("size", 0))
            if not info.get("exists") or size == 0:
                copied[label] = {
                    "source": self._sanitized_path(source),
                    "copied": False,
                    "size": size,
                }
                continue
            target = destination / ntpath.basename(source)
            self.connection.copy_file_from(source, target)
            copied[label] = {
                "source": self._sanitized_path(source),
                "path": str(target),
                "copied": True,
                "size": target.stat().st_size,
            }
        return copied

    def _sanitized_path(self, path: str) -> str:
        prefix = self.connection.stage_root.rstrip("\\")
        if path.casefold().startswith(prefix.casefold()):
            return (
                r"%USERPROFILE%\sd-netrepro-stage"
                + path[len(prefix):]
            )
        return ntpath.basename(path)

    def delete_run(self) -> None:
        self.connection.remove_tree(self.run_root)
