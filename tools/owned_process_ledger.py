#!/usr/bin/env python3
"""Exact PID and staged-executable ownership for game verifier processes."""

from __future__ import annotations

import base64
import json
import ntpath
import re
import subprocess
import threading
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path, PureWindowsPath
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


class OwnedProcessError(RuntimeError):
    """Raised when a process cannot be proven to belong to this verifier."""


@dataclass(frozen=True)
class OwnedProcessIdentity:
    role: str
    process_id: int
    executable_path: str
    instance: str = ""


def _positive_process_id(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        process_id = value
    elif isinstance(value, str) and value.isdigit():
        process_id = int(value)
    else:
        return None
    return process_id if process_id > 0 else None


def normalize_windows_path(path: str) -> str:
    normalized = path.strip().replace("/", "\\")
    if normalized.startswith("\\\\?\\"):
        normalized = normalized[4:]
    return ntpath.normcase(ntpath.normpath(normalized))


def _require_staged_executable(path: object, *, key: str) -> str:
    if not isinstance(path, str) or not path.strip():
        raise OwnedProcessError(f"owned process is missing {key}")
    value = path.strip()
    if (
        re.match(r"^[A-Za-z]:[\\/]", value) is None
        and not value.startswith("\\\\")
    ):
        raise OwnedProcessError(
            f"owned process {key} is not an absolute Windows path: {value!r}"
        )
    parsed = PureWindowsPath(value)
    if (
        parsed.name.casefold() != "solomondark.exe"
        or parsed.parent.name.casefold() != "stage"
    ):
        raise OwnedProcessError(
            f"owned process {key} is not a staged SolomonDark.exe: {value!r}"
        )
    return str(parsed)


def _role_for_instance(instance: str) -> str:
    lowered = instance.casefold()
    for role in ("host", "client", "third"):
        if lowered.endswith(f"-{role}"):
            return role
    return instance or "game"


def identities_from_launch(
    launch: Mapping[str, object],
) -> list[OwnedProcessIdentity]:
    """Extract complete PID/path identities from launcher-owned JSON."""

    identities: list[OwnedProcessIdentity] = []
    instance_prefix = str(launch.get("instancePrefix") or "")
    for role, process_key, path_key in (
        ("host", "hostProcessId", "hostExecutablePath"),
        ("client", "clientProcessId", "clientExecutablePath"),
        ("third", "thirdProcessId", "thirdExecutablePath"),
    ):
        process_id = _positive_process_id(launch.get(process_key))
        if process_id is None:
            continue
        identities.append(
            OwnedProcessIdentity(
                role=role,
                process_id=process_id,
                executable_path=_require_staged_executable(
                    launch.get(path_key),
                    key=path_key,
                ),
                instance=(
                    f"{instance_prefix}-{role}" if instance_prefix else role
                ),
            )
        )

    process_id = _positive_process_id(launch.get("processId"))
    if process_id is not None:
        instance = str(launch.get("instance") or "")
        identities.append(
            OwnedProcessIdentity(
                role=str(
                    launch.get("processRole")
                    or _role_for_instance(instance)
                ),
                process_id=process_id,
                executable_path=_require_staged_executable(
                    launch.get("executablePath"),
                    key="executablePath",
                ),
                instance=instance,
            )
        )

    by_id: dict[int, OwnedProcessIdentity] = {}
    for identity in identities:
        previous = by_id.get(identity.process_id)
        if previous is not None and (
            normalize_windows_path(previous.executable_path)
            != normalize_windows_path(identity.executable_path)
        ):
            raise OwnedProcessError(
                "launcher assigned conflicting staged paths to PID "
                f"{identity.process_id}: {previous.executable_path!r} and "
                f"{identity.executable_path!r}"
            )
        by_id[identity.process_id] = identity
    return [by_id[process_id] for process_id in sorted(by_id)]


def new_launcher_ledger_path(
    *,
    root: Path = ROOT,
    label: str = "owned-processes",
) -> Path:
    runtime_root = root / "runtime"
    runtime_root.mkdir(parents=True, exist_ok=True)
    return runtime_root / f".{label}-{uuid.uuid4().hex}.json"


def read_launcher_ledger(path: Path | None) -> dict[str, object]:
    if path is None or not path.is_file():
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _encoded_identities(
    identities: Iterable[OwnedProcessIdentity],
) -> str:
    payload = [
        {
            "role": identity.role,
            "process_id": identity.process_id,
            "executable_path": identity.executable_path,
            "instance": identity.instance,
        }
        for identity in identities
    ]
    return base64.b64encode(
        json.dumps(payload, separators=(",", ":")).encode("utf-8")
    ).decode("ascii")


def _parse_process_results(output: str) -> list[dict[str, Any]]:
    raw = output.strip().lstrip("\ufeff")
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise OwnedProcessError(
            f"owned-process probe returned invalid JSON: {output!r}"
        ) from exc
    if isinstance(parsed, dict):
        return [parsed]
    if isinstance(parsed, list) and all(
        isinstance(item, dict) for item in parsed
    ):
        return parsed
    raise OwnedProcessError(
        f"owned-process probe returned an unexpected value: {parsed!r}"
    )


def _inspect_identities(
    identities: list[OwnedProcessIdentity],
) -> list[dict[str, Any]]:
    if not identities:
        return []
    payload = _encoded_identities(identities)
    script = r"""
$ErrorActionPreference = "Stop"
$payload = [System.Text.Encoding]::UTF8.GetString(
    [System.Convert]::FromBase64String("__PAYLOAD__"))
$decodedTargets = ConvertFrom-Json -InputObject $payload
$targets = @($decodedTargets)
$results = @()
foreach ($target in $targets) {
    $processId = [int]$target.process_id
    $expectedPath = [System.IO.Path]::GetFullPath(
        [string]$target.executable_path)
    $process = Get-CimInstance -ClassName Win32_Process `
        -Filter "ProcessId = $processId" `
        -ErrorAction SilentlyContinue
    $actualPath = if ($null -eq $process) {
        $null
    } else {
        [string]$process.ExecutablePath
    }
    $pathMatched = $false
    if (-not [string]::IsNullOrWhiteSpace($actualPath)) {
        $actualPath = [System.IO.Path]::GetFullPath($actualPath)
        $pathMatched = [string]::Equals(
            $actualPath,
            $expectedPath,
            [System.StringComparison]::OrdinalIgnoreCase)
    }
    $results += [pscustomobject]@{
        role = [string]$target.role
        instance = [string]$target.instance
        processId = $processId
        expectedPath = $expectedPath
        actualPath = $actualPath
        alreadyExited = $null -eq $process
        pathMatched = $pathMatched
    }
}
[Console]::Write(
    (ConvertTo-Json -InputObject @($results) -Compress))
""".replace("__PAYLOAD__", payload)
    completed = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            script,
        ],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=15.0,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise OwnedProcessError(
            f"owned-process inspection failed: {detail}"
        )
    return _parse_process_results(completed.stdout)


def _stop_identities(
    identities: list[OwnedProcessIdentity],
) -> list[dict[str, Any]]:
    if not identities:
        return []
    payload = _encoded_identities(identities)
    script = r"""
$ErrorActionPreference = "Stop"
$payload = [System.Text.Encoding]::UTF8.GetString(
    [System.Convert]::FromBase64String("__PAYLOAD__"))
$decodedTargets = ConvertFrom-Json -InputObject $payload
$targets = @($decodedTargets)
$results = @()
$refused = $false
foreach ($target in $targets) {
    $processId = [int]$target.process_id
    $expectedPath = [System.IO.Path]::GetFullPath(
        [string]$target.executable_path)
    $process = Get-CimInstance -ClassName Win32_Process `
        -Filter "ProcessId = $processId" `
        -ErrorAction SilentlyContinue
    $actualPath = if ($null -eq $process) {
        $null
    } else {
        [string]$process.ExecutablePath
    }
    $pathMatched = $false
    if (-not [string]::IsNullOrWhiteSpace($actualPath)) {
        $actualPath = [System.IO.Path]::GetFullPath($actualPath)
        $pathMatched = [string]::Equals(
            $actualPath,
            $expectedPath,
            [System.StringComparison]::OrdinalIgnoreCase)
    }
    if ($null -ne $process -and -not $pathMatched) {
        $refused = $true
    }
    $results += [pscustomobject]@{
        role = [string]$target.role
        instance = [string]$target.instance
        processId = $processId
        expectedPath = $expectedPath
        actualPath = $actualPath
        alreadyExited = $null -eq $process
        pathMatched = $pathMatched
        stopped = $false
    }
}
if (-not $refused) {
    foreach ($result in $results) {
        if (-not $result.alreadyExited) {
            Stop-Process -Id ([int]$result.processId) -Force
            $result.stopped = $true
        }
    }
    $deadline = [DateTime]::UtcNow.AddSeconds(10)
    do {
        $ownedRemaining = @()
        foreach ($result in $results) {
            $processId = [int]$result.processId
            $process = Get-CimInstance -ClassName Win32_Process `
                -Filter "ProcessId = $processId" `
                -ErrorAction SilentlyContinue
            if ($null -eq $process) {
                continue
            }
            $actualPath = [string]$process.ExecutablePath
            if (-not [string]::IsNullOrWhiteSpace($actualPath) -and
                [string]::Equals(
                    [System.IO.Path]::GetFullPath($actualPath),
                    [string]$result.expectedPath,
                    [System.StringComparison]::OrdinalIgnoreCase)) {
                $ownedRemaining += $processId
            }
        }
        if ($ownedRemaining.Count -eq 0) {
            break
        }
        Start-Sleep -Milliseconds 100
    } while ([DateTime]::UtcNow -lt $deadline)
    if ($ownedRemaining.Count -ne 0) {
        throw "owned staged game processes did not exit: $ownedRemaining"
    }
}
[Console]::Write(
    (ConvertTo-Json -InputObject @($results) -Compress))
""".replace("__PAYLOAD__", payload)
    completed = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-Command",
            script,
        ],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=20.0,
        check=False,
    )
    if completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise OwnedProcessError(
            f"exact PID/path cleanup failed: {detail}"
        )
    return _parse_process_results(completed.stdout)


class OwnedProcessLedger:
    """In-process ownership ledger populated only by launcher-returned data."""

    def __init__(self) -> None:
        self._identities: dict[int, OwnedProcessIdentity] = {}
        self._lock = threading.RLock()

    def clear_for_test(self) -> None:
        with self._lock:
            self._identities.clear()

    def snapshot(self) -> list[OwnedProcessIdentity]:
        with self._lock:
            return [
                self._identities[process_id]
                for process_id in sorted(self._identities)
            ]

    def acquire(
        self,
        identities: Iterable[OwnedProcessIdentity],
        *,
        validate: bool = True,
    ) -> list[OwnedProcessIdentity]:
        candidates = list(identities)
        if not candidates:
            return []
        if validate:
            results = _inspect_identities(candidates)
            by_id = {
                int(result["processId"]): result
                for result in results
            }
            for identity in candidates:
                result = by_id.get(identity.process_id)
                if result is None or result.get("alreadyExited"):
                    raise OwnedProcessError(
                        f"launcher-owned PID {identity.process_id} exited "
                        "before ownership acquisition"
                    )
                if not result.get("pathMatched"):
                    raise OwnedProcessError(
                        "refusing ownership of launcher PID with a different "
                        f"executable: pid={identity.process_id} "
                        f"expected={identity.executable_path!r} "
                        f"actual={result.get('actualPath')!r}"
                    )

        with self._lock:
            for identity in candidates:
                previous = self._identities.get(identity.process_id)
                if previous is not None and (
                    normalize_windows_path(previous.executable_path)
                    != normalize_windows_path(identity.executable_path)
                ):
                    raise OwnedProcessError(
                        "PID ownership changed inside the verifier ledger: "
                        f"pid={identity.process_id}"
                    )
                self._identities[identity.process_id] = identity
        return candidates

    def acquire_launch(
        self,
        launch: Mapping[str, object],
        *,
        validate: bool = True,
        require_processes: bool = True,
    ) -> list[OwnedProcessIdentity]:
        identities = identities_from_launch(launch)
        if require_processes and not identities:
            raise OwnedProcessError(
                "launcher result did not contain a complete owned process"
            )
        return self.acquire(identities, validate=validate)

    def inspect(self) -> list[dict[str, Any]]:
        identities = self.snapshot()
        results = _inspect_identities(identities)
        by_id = {
            int(result["processId"]): result
            for result in results
        }
        exited: list[int] = []
        for identity in identities:
            result = by_id.get(identity.process_id)
            if result is None or result.get("alreadyExited"):
                exited.append(identity.process_id)
                continue
            if not result.get("pathMatched"):
                raise OwnedProcessError(
                    "owned PID now resolves to a different executable: "
                    f"pid={identity.process_id} "
                    f"expected={identity.executable_path!r} "
                    f"actual={result.get('actualPath')!r}"
                )
        if exited:
            with self._lock:
                for process_id in exited:
                    self._identities.pop(process_id, None)
        return [
            result
            for result in results
            if int(result["processId"]) not in exited
        ]

    def process_ids_by_role(self) -> dict[str, int]:
        self.inspect()
        result: dict[str, int] = {}
        for identity in self.snapshot():
            previous = result.get(identity.role)
            if previous is not None and previous != identity.process_id:
                raise OwnedProcessError(
                    f"multiple live owned processes claim role "
                    f"{identity.role!r}: {previous}, {identity.process_id}"
                )
            result[identity.role] = identity.process_id
        return result

    def stop(
        self,
        process_ids: Iterable[int] | None = None,
    ) -> list[dict[str, Any]]:
        with self._lock:
            if process_ids is None:
                selected = list(self._identities.values())
            else:
                requested = {
                    process_id
                    for process_id in process_ids
                    if isinstance(process_id, int)
                    and not isinstance(process_id, bool)
                    and process_id > 0
                }
                if not requested:
                    return []
                unknown = requested.difference(self._identities)
                if unknown:
                    raise OwnedProcessError(
                        "refusing cleanup of PIDs absent from the owned "
                        f"process ledger: {sorted(unknown)}"
                    )
                selected = [
                    self._identities[process_id]
                    for process_id in sorted(requested)
                ]
        results = _stop_identities(selected)
        mismatches = [
            result
            for result in results
            if not result.get("alreadyExited")
            and not result.get("pathMatched")
        ]
        if mismatches:
            raise OwnedProcessError(
                "refused to stop launcher PIDs with different executables: "
                f"{mismatches}"
            )
        removable = {
            int(result["processId"])
            for result in results
            if result.get("alreadyExited") or result.get("stopped")
        }
        with self._lock:
            for process_id in removable:
                self._identities.pop(process_id, None)
        return results

    def as_json(self) -> list[dict[str, object]]:
        return [asdict(identity) for identity in self.snapshot()]


OWNED_GAME_PROCESSES = OwnedProcessLedger()


def register_owned_launch(
    launch: Mapping[str, object],
    *,
    validate: bool = True,
    require_processes: bool = True,
) -> list[OwnedProcessIdentity]:
    return OWNED_GAME_PROCESSES.acquire_launch(
        launch,
        validate=validate,
        require_processes=require_processes,
    )


def stop_owned_game_processes() -> list[dict[str, Any]]:
    return OWNED_GAME_PROCESSES.stop()


def stop_owned_process_ids(
    process_ids: Iterable[int],
) -> list[dict[str, Any]]:
    return OWNED_GAME_PROCESSES.stop(process_ids)


def owned_process_ids_by_role() -> dict[str, int]:
    return OWNED_GAME_PROCESSES.process_ids_by_role()
