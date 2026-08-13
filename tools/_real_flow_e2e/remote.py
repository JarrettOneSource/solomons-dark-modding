from __future__ import annotations

from dataclasses import dataclass
import base64
import hashlib
import json
import os
from pathlib import Path
import select
import shlex
import struct
import subprocess
import tarfile
import threading
import time
from typing import Any

from .config import HarnessConfig, PeerConfig
from .runtime import STATE_LUA, normalize_state, parse_key_values
from .windows import windows_path


class RemoteHarnessError(RuntimeError):
    """An isolated remote peer operation failed."""


REMOTE_HELPER = "tools/Run-RealFlowRemotePeer.sh"


def _remote_command(arguments: list[str]) -> str:
    return " ".join(shlex.quote(value) for value in arguments)


@dataclass
class RemoteConnection:
    config: PeerConfig
    source_root: Path

    def _ssh_arguments(self) -> list[str]:
        assert self.config.ssh is not None
        arguments = [
            self.config.ssh.executable,
            "-o",
            "BatchMode=yes",
        ]
        if self.config.ssh.key_path:
            arguments.extend(("-i", self.config.ssh.key_path))
        arguments.append(self.config.ssh.target)
        return arguments

    @property
    def stage_root(self) -> str:
        assert self.config.ssh is not None
        return self.config.ssh.stage_root

    @property
    def helper(self) -> str:
        return f"{self.stage_root}/{REMOTE_HELPER}"

    def run(self, command: str, *, timeout: float = 60.0) -> str:
        completed = subprocess.run(
            [*self._ssh_arguments(), command],
            cwd=self.source_root,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            check=False,
        )
        if completed.returncode != 0:
            raise RemoteHarnessError(
                f"remote command failed ({completed.returncode}): "
                f"{completed.stdout.strip()}"
            )
        return completed.stdout

    def clock_offset_sample(self) -> dict[str, int]:
        """Estimate remote UTC offset with a bounded SSH round trip."""
        started = time.time_ns()
        output = self.run("date +%s%N", timeout=15).strip()
        ended = time.time_ns()
        try:
            remote = int(output)
        except ValueError as exc:
            raise RemoteHarnessError(
                "remote clock returned an invalid nanosecond value: "
                f"{output!r}"
            ) from exc
        midpoint = started + (ended - started) // 2
        return {
            "controllerStartedUtcNanoseconds": started,
            "controllerEndedUtcNanoseconds": ended,
            "roundTripNanoseconds": ended - started,
            "remoteUtcNanoseconds": remote,
            "remoteToControllerOffsetNanoseconds": midpoint - remote,
            "uncertaintyNanoseconds": (ended - started) // 2,
        }

    def clock_alignment(self, *, samples: int = 5) -> dict[str, Any]:
        if not 1 <= samples <= 9:
            raise RemoteHarnessError(
                "remote clock alignment sample count must be 1..9"
            )
        rows = [self.clock_offset_sample() for _ in range(samples)]
        selected = min(
            rows,
            key=lambda row: row["roundTripNanoseconds"],
        )
        return {
            "method": "minimum-rtt-ssh-midpoint",
            "selected": selected,
            "samples": rows,
        }

    def helper_command(
        self,
        command: str,
        *arguments: str,
        timeout: float = 60.0,
    ) -> str:
        return self.run(
            _remote_command(
                [
                    self.helper,
                    self.stage_root,
                    command,
                    *arguments,
                ]
            ),
            timeout=timeout,
        )

    def scp_from(
        self,
        remote_path: str,
        local_path: Path,
        *,
        timeout: float = 300.0,
    ) -> None:
        assert self.config.ssh is not None
        executable = Path(self.config.ssh.executable)
        scp_name = (
            "scp.exe"
            if executable.name.casefold() == "ssh.exe"
            else "scp"
        )
        scp = executable.with_name(scp_name)
        arguments = [str(scp), "-q"]
        if self.config.ssh.key_path:
            arguments.extend(("-i", self.config.ssh.key_path))
        target = f"{self.config.ssh.target}:{remote_path}"
        destination = (
            windows_path(local_path)
            if scp.name.casefold() == "scp.exe"
            else str(local_path)
        )
        local_path.parent.mkdir(parents=True, exist_ok=True)
        completed = subprocess.run(
            [*arguments, target, destination],
            cwd=self.source_root,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            check=False,
        )
        if completed.returncode != 0:
            raise RemoteHarnessError(
                f"remote artifact copy failed ({completed.returncode}): "
                f"{completed.stdout.strip()}"
            )

    def scp_to(
        self,
        local_path: Path,
        remote_path: str,
        *,
        timeout: float = 900.0,
    ) -> None:
        assert self.config.ssh is not None
        if not local_path.is_file():
            raise RemoteHarnessError(
                f"local remote-stage input is missing: {local_path}"
            )
        executable = Path(self.config.ssh.executable)
        scp_name = (
            "scp.exe"
            if executable.name.casefold() == "ssh.exe"
            else "scp"
        )
        scp = executable.with_name(scp_name)
        arguments = [str(scp), "-q"]
        if self.config.ssh.key_path:
            arguments.extend(("-i", self.config.ssh.key_path))
        source = (
            windows_path(local_path)
            if scp.name.casefold() == "scp.exe"
            else str(local_path)
        )
        target = f"{self.config.ssh.target}:{remote_path}"
        completed = subprocess.run(
            [*arguments, source, target],
            cwd=self.source_root,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            check=False,
        )
        if completed.returncode != 0:
            raise RemoteHarnessError(
                f"remote stage copy failed ({completed.returncode}): "
                f"{completed.stdout.strip()}"
            )


class RemoteLuaPipe:
    def __init__(
        self,
        connection: RemoteConnection,
        instance: str,
    ) -> None:
        self.connection = connection
        self.instance = instance
        self.lock = threading.Lock()
        self.process = self._start_process()

    def _start_process(self) -> subprocess.Popen[bytes]:
        command = _remote_command(
            [
                self.connection.helper,
                self.connection.stage_root,
                "lua-daemon",
                self.instance,
            ]
        )
        return subprocess.Popen(
            [*self.connection._ssh_arguments(), command],
            cwd=self.connection.source_root,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )

    def _close_process(self) -> None:
        if self.process.stdin is not None:
            try:
                self.process.stdin.close()
            except OSError:
                pass
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)

    def _restart_process(self) -> None:
        self._close_process()
        self.process = self._start_process()

    def _read_exact(self, size: int, *, timeout: float) -> bytes:
        if self.process.stdout is None:
            raise RemoteHarnessError("remote Lua daemon has no stdout")
        deadline = time.monotonic() + timeout
        result = bytearray()
        descriptor = self.process.stdout.fileno()
        while len(result) < size:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise RemoteHarnessError("remote Lua daemon timed out")
            ready, _, _ = select.select(
                [descriptor],
                [],
                [],
                remaining,
            )
            if not ready:
                raise RemoteHarnessError("remote Lua daemon timed out")
            chunk = os.read(descriptor, size - len(result))
            if not chunk:
                error = ""
                if self.process.stderr is not None:
                    error = self.process.stderr.read().decode(
                        "utf-8",
                        errors="replace",
                    ).strip()
                raise RemoteHarnessError(
                    "remote Lua daemon closed"
                    + (f": {error}" if error else "")
                )
            result.extend(chunk)
        return bytes(result)

    def execute(self, code: str) -> str:
        payload = code.encode("utf-8")
        with self.lock:
            deadline = time.monotonic() + 45.0
            errors: list[str] = []
            response: str | None = None
            for attempt in range(4):
                try:
                    if self.process.stdin is None:
                        raise RemoteHarnessError(
                            "remote Lua daemon has no stdin"
                        )
                    self.process.stdin.write(
                        struct.pack("<I", len(payload))
                    )
                    self.process.stdin.write(payload)
                    self.process.stdin.flush()
                    response_size = struct.unpack(
                        "<I",
                        self._read_exact(4, timeout=30.0),
                    )[0]
                    if response_size > 16 * 1024 * 1024:
                        raise RemoteHarnessError(
                            "remote Lua daemon returned an oversized "
                            "response"
                        )
                    response = self._read_exact(
                        response_size,
                        timeout=30.0,
                    ).decode("utf-8")
                    break
                except (
                    BrokenPipeError,
                    OSError,
                    RemoteHarnessError,
                ) as exc:
                    errors.append(f"{type(exc).__name__}: {exc}")
                    if (
                        attempt == 3
                        or time.monotonic() >= deadline
                    ):
                        raise RemoteHarnessError(
                            "remote Lua daemon could not survive the "
                            "runtime transition: "
                            + " | ".join(errors)
                        ) from exc
                    self._restart_process()
                    time.sleep(0.25 * (attempt + 1))
            if response is None:
                raise RemoteHarnessError(
                    "remote Lua daemon returned no response"
                )
        try:
            document = json.loads(response)
        except json.JSONDecodeError:
            return response
        if not isinstance(document, dict) or "results" not in document:
            return response
        if document.get("ok") is not True:
            raise RemoteHarnessError(
                f"remote Lua command failed: {document}"
            )
        results = document.get("results")
        if not isinstance(results, list):
            raise RemoteHarnessError(
                f"remote Lua response has invalid results: {document}"
            )
        return "\n".join(str(value) for value in results)

    def state(self) -> dict[str, Any]:
        return normalize_state(parse_key_values(self.execute(STATE_LUA)))

    def close(self) -> None:
        with self.lock:
            self._close_process()


@dataclass
class RemoteProtonPeer:
    config: PeerConfig
    connection: RemoteConnection

    @staticmethod
    def _archive_tree(source: Path, destination: Path) -> None:
        if not source.is_dir():
            raise RemoteHarnessError(
                f"remote stage source is not a directory: {source}"
            )
        destination.parent.mkdir(parents=True, exist_ok=True)
        with tarfile.open(
            destination,
            "w:gz",
            compresslevel=1,
            dereference=True,
        ) as archive:
            for entry in sorted(source.iterdir(), key=lambda path: path.name):
                archive.add(
                    entry,
                    arcname=entry.name,
                    recursive=True,
                )

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

    @staticmethod
    def _build_helper(
        source_root: Path,
        script_name: str,
        destination: Path,
    ) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        completed = subprocess.run(
            [
                "powershell.exe",
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                windows_path(source_root / "scripts" / script_name),
                "-OutputPath",
                windows_path(destination),
            ],
            cwd=source_root,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=180,
            check=False,
        )
        if completed.returncode != 0 or not destination.is_file():
            raise RemoteHarnessError(
                f"{script_name} failed ({completed.returncode}): "
                f"{completed.stdout.strip()}"
            )

    def prepare(
        self,
        harness: HarnessConfig,
        workspace: Path,
    ) -> dict[str, Any]:
        if (
            self.connection.stage_root
            != "/root/sd-fieldbreak25-20260730"
        ):
            raise RemoteHarnessError(
                "NFO preparation is confined to "
                "/root/sd-fieldbreak25-20260730"
            )
        if harness.proton_archive is None:
            raise RemoteHarnessError(
                "NFO preparation requires a local Proton archive"
            )
        stage_probe = self.connection.run(
            "if test -e /root/sd-fieldbreak25-20260730; "
            "then printf present; else printf absent; fi"
        ).strip()
        if stage_probe != "absent":
            raise RemoteHarnessError(
                "NFO stage root must be absent before config-driven "
                f"preparation; probe={stage_probe!r}"
            )

        workspace.mkdir(parents=True, exist_ok=False)
        stage_script = (
            harness.source_root / "scripts" / "Stage-RealFlowNfo.sh"
        )
        inputs = {
            "package.tar.gz": workspace / "package.tar.gz",
            "game.tar.gz": workspace / "game.tar.gz",
            "GE-Proton.tar.gz": harness.proton_archive,
            "observer.tar.gz": workspace / "observer.tar.gz",
            "Run-RealFlowRemotePeer.sh": (
                harness.source_root
                / "scripts"
                / "Run-RealFlowRemotePeer.sh"
            ),
            "win32_lua_exec_client.exe": (
                workspace / "win32_lua_exec_client.exe"
            ),
            "win32_real_input.exe": (
                workspace / "win32_real_input.exe"
            ),
            "Stage-RealFlowNfo.sh": stage_script,
        }
        self._archive_tree(
            harness.package_root,
            inputs["package.tar.gz"],
        )
        self._archive_tree(
            harness.game_directory,
            inputs["game.tar.gz"],
        )
        self._archive_tree(
            harness.source_root
            / "tools"
            / "_real_flow_e2e"
            / "observer_mod",
            inputs["observer.tar.gz"],
        )
        self._build_helper(
            harness.source_root,
            "Build-Win32LuaExecClient.ps1",
            inputs["win32_lua_exec_client.exe"],
        )
        self._build_helper(
            harness.source_root,
            "Build-Win32RealInput.ps1",
            inputs["win32_real_input.exe"],
        )
        for label, path in inputs.items():
            if not path.is_file():
                raise RemoteHarnessError(
                    f"remote stage input is missing: {label}: {path}"
                )

        digests = {
            label: self._sha256(path)
            for label, path in inputs.items()
        }
        manifest = workspace / "input-sha256.txt"
        manifest.write_text(
            "".join(
                f"{digest}  {label}\n"
                for label, digest in sorted(digests.items())
            ),
            encoding="utf-8",
        )
        upload_inputs = {
            **inputs,
            "input-sha256.txt": manifest,
        }
        self.connection.run(
            "install -d -m 700 "
            "/root/sd-fieldbreak25-20260730/incoming"
        )
        for name, path in upload_inputs.items():
            self.connection.scp_to(
                path,
                f"/root/sd-fieldbreak25-20260730/incoming/{name}",
            )
        output = self.connection.run(
            "chmod 700 "
            "/root/sd-fieldbreak25-20260730/incoming/"
            "Stage-RealFlowNfo.sh "
            "&& /root/sd-fieldbreak25-20260730/incoming/"
            "Stage-RealFlowNfo.sh /root/sd-fieldbreak25-20260730",
            timeout=900,
        )
        if output.strip().splitlines()[-1:] != ["prepared"]:
            raise RemoteHarnessError(
                f"NFO stage preparation did not complete: {output!r}"
            )
        prepared = self.assert_prepared()
        return {
            **prepared,
            "configDriven": True,
            "inputSha256": digests,
            "stageOutput": output.splitlines(),
        }

    def delete_stage(self) -> dict[str, Any]:
        if (
            self.connection.stage_root
            != "/root/sd-fieldbreak25-20260730"
        ):
            raise RemoteHarnessError(
                "refusing to delete an unexpected remote stage root"
            )
        helper_exists = self.connection.run(
            "if test -x "
            "/root/sd-fieldbreak25-20260730/tools/"
            "Run-RealFlowRemotePeer.sh; "
            "then printf yes; else printf no; fi"
        ).strip()
        owned = (
            self.connection.helper_command("status").strip()
            if helper_exists == "yes"
            else ""
        )
        ports = self.connection.run(
            "ss -H -lunp | "
            "grep -E ':(50911|50912)[[:space:]]' || true"
        ).strip()
        path_processes = self.connection.run(
            "for proc in /proc/[0-9]*; do "
            "pid=${proc#/proc/}; "
            "test \"$pid\" = \"$$\" && continue; "
            "exe=$(readlink -f \"$proc/exe\" 2>/dev/null || true); "
            "cwd=$(readlink -f \"$proc/cwd\" 2>/dev/null || true); "
            "case \"$exe $cwd\" in "
            "*'/root/sd-fieldbreak25-20260730'*) "
            "printf '%s\\t%s\\t%s\\n' \"$pid\" \"$exe\" \"$cwd\";; "
            "esac; "
            "done"
        ).strip()
        if owned or ports or path_processes:
            raise RemoteHarnessError(
                "refusing remote stage deletion with owned state alive: "
                f"processes={owned!r} pathProcesses={path_processes!r} "
                f"ports={ports!r}"
            )
        output = self.connection.run(
            "rm -rf -- /root/sd-fieldbreak25-20260730 "
            "&& test ! -e /root/sd-fieldbreak25-20260730 "
            "&& printf deleted"
        ).strip()
        if output != "deleted":
            raise RemoteHarnessError(
                f"remote stage deletion returned {output!r}"
            )
        return {
            "stageRoot": "/root/sd-fieldbreak25-20260730",
            "deleted": True,
            "recoverable": False,
        }

    def assert_prepared(self) -> dict[str, Any]:
        output = self.connection.run(
            _remote_command(
                [
                    "set",
                    "-eu",
                ]
            )
            + "; "
            + "; ".join(
                (
                    f"test -x {shlex.quote(self.connection.helper)}",
                    f"test -f {shlex.quote(self.connection.stage_root + '/package/SolomonDarkMultiplayerBeta.exe')}",
                    f"test -f {shlex.quote(self.connection.stage_root + '/game/SolomonDark.exe')}",
                    f"test -x {shlex.quote(self.connection.stage_root + '/proton/proton')}",
                    f"test -x {shlex.quote(self.connection.stage_root + '/x11/usr/bin/Xvfb')}",
                    f"test -x {shlex.quote(self.connection.stage_root + '/x11/usr/bin/ffmpeg')}",
                    "printf prepared",
                )
            )
        ).strip()
        if output != "prepared":
            raise RemoteHarnessError(
                f"remote stage verification returned {output!r}"
            )
        return {
            "stageRoot": self.connection.stage_root,
            "helper": self.connection.helper,
            "selfContainedProton": True,
            "selfContainedXvfb": True,
        }

    def start_and_join(self, lobby_id: int) -> dict[str, Any]:
        peer = self.config
        self.connection.helper_command(
            "prepare-client",
            peer.launcher_scope,
            peer.instance,
            str(peer.local_port),
            peer.remote_host,
            str(peer.remote_port),
            str(peer.participant_id),
            peer.loadout_element,
            peer.loadout_discipline,
        )
        self.connection.helper_command("launch-ui", timeout=45)
        deadline = time.monotonic() + 60.0
        windows = ""
        while time.monotonic() < deadline:
            windows = self.connection.helper_command("windows")
            if "Solomon Darker" in windows:
                break
            time.sleep(0.5)
        else:
            raise RemoteHarnessError(
                f"remote desktop launcher did not render: {windows!r}"
            )

        # The packaged WPF launcher is 760x884 on the isolated 1600x900
        # display. These clicks operate its real Advanced, Instance, Apply,
        # Lobby ID, and Join Game controls.
        self.connection.helper_command("launcher-click", "60", "622")
        self.connection.helper_command(
            "launcher-type",
            "154",
            "670",
            peer.instance,
        )
        self.connection.helper_command("launcher-click", "266", "670")
        time.sleep(3)
        self.connection.helper_command("launcher-key", "ctrl+Home")
        self.connection.helper_command(
            "launcher-type",
            "409",
            "334",
            str(lobby_id),
        )
        self.connection.helper_command("launcher-click", "246", "273")

        deadline = time.monotonic() + 120.0
        while time.monotonic() < deadline:
            windows = self.connection.helper_command("windows")
            if "\tSolomonDark\n" in windows:
                return {
                    "lobbyId": lobby_id,
                    "explicitLaunchGame": False,
                    "desktopLauncher": True,
                    "windows": windows.splitlines(),
                }
            time.sleep(0.5)
        raise RemoteHarnessError(
            f"remote Join Game did not launch the game: {windows!r}"
        )

    def wait_connected_session(
        self,
        *,
        timeout: float,
    ) -> dict[str, Any]:
        deadline = time.monotonic() + timeout
        last: dict[str, Any] = {}
        last_error = ""
        while time.monotonic() < deadline:
            try:
                output = self.connection.helper_command(
                    "session-status",
                    self.config.launcher_scope,
                    self.config.instance,
                    timeout=15,
                )
                parsed = json.loads(output)
                if not isinstance(parsed, dict):
                    raise RemoteHarnessError(
                        "remote session status was not an object"
                    )
                last = parsed
                members = parsed.get("members")
                if (
                    parsed.get("phase") == "Connected"
                    and parsed.get("sessionState")
                    in {"in-hub", "in-boneyard"}
                    and int(parsed.get("authenticatedPeerCount", 0)) >= 1
                    and isinstance(members, list)
                    and len(members) >= 2
                ):
                    return parsed
            except (
                json.JSONDecodeError,
                RemoteHarnessError,
            ) as exc:
                last_error = str(exc)
            time.sleep(0.25)
        raise RemoteHarnessError(
            "remote game did not reach an authenticated shared session "
            "before Lua observation began: "
            f"last={last} error={last_error!r}"
        )

    def click_game(self, x: float, y: float) -> dict[str, Any]:
        started = time.time_ns()
        self.connection.helper_command(
            "game-click",
            f"{x:.8f}",
            f"{y:.8f}",
        )
        return {
            "startedUtcNanoseconds": started,
            "endedUtcNanoseconds": time.time_ns(),
            "xFraction": x,
            "yFraction": y,
        }

    def capture(
        self,
        name: str,
        destination: Path,
    ) -> dict[str, Any]:
        started = time.time_ns()
        output = self.connection.helper_command(
            "capture-png",
            name,
            timeout=45,
        ).strip()
        fields = output.split("\t", 1)
        if len(fields) != 2:
            raise RemoteHarnessError(
                f"remote capture returned an invalid result: {output!r}"
            )
        try:
            capture_ns = int(fields[0])
        except ValueError as exc:
            raise RemoteHarnessError(
                f"remote capture returned an invalid timestamp: {output!r}"
            ) from exc
        remote_path = f"{self.connection.stage_root}/evidence/{name}.png"
        if fields[1] != remote_path:
            raise RemoteHarnessError(
                f"remote capture returned an unsafe path: {fields[1]!r}"
            )
        self.connection.scp_from(remote_path, destination)
        return {
            "startedUtcNanoseconds": started,
            "remoteCaptureUtcNanoseconds": capture_ns,
            "endedUtcNanoseconds": time.time_ns(),
            "remoteResult": output,
            "path": str(destination),
        }

    def copy_runtime_artifacts(
        self,
        destination: Path,
    ) -> Path:
        remote_archive = self.connection.helper_command(
            "pack-artifacts",
            self.config.launcher_scope,
            self.config.instance,
            timeout=60,
        ).strip()
        expected = (
            f"{self.connection.stage_root}/evidence/"
            f"{self.config.instance}-runtime.tar"
        )
        if remote_archive != expected:
            raise RemoteHarnessError(
                f"remote artifact path was unsafe: {remote_archive!r}"
            )
        self.connection.scp_from(remote_archive, destination)
        return destination

    def stop(self) -> str:
        return self.connection.helper_command("stop", timeout=45)
