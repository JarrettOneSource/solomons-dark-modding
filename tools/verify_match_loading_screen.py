#!/usr/bin/env python3
"""Prove the launcher keeps its plain utility UI through real pre-game join/mod sync.

The desktop launcher window must never present the match loading screen
(owner direction, 2026-07-27); that presentation belongs to the staged
game's D3D9 renderer only. This verifier drives a real join preview,
consent, and throttled mod download without launching the game, and fails
if any overlay signature becomes visible.
"""

from __future__ import annotations

import argparse
import hashlib
import http.server
import json
import shutil
import socketserver
import subprocess
import threading
import time
import urllib.parse
import zipfile
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_ROOT = Path(
    "/mnt/d/codex-evidence/launcher-plain-sync-20260727"
)
GAME_DIRECTORY = Path(
    "/mnt/c/Users/User/Documents/GitHub/SB Modding/"
    "Solomon Dark/SolomonDarkAbandonware"
)
UI_EXECUTABLE = (
    ROOT / "dist/ui/SolomonDarkMultiplayerBeta.exe"
)
CAPTURE_SCRIPT = ROOT / "scripts/capture_window.py"
OUTPUT_PATH = EVIDENCE_ROOT / "match-loading-screen-live.json"

# Signatures of the removed launcher match-loading overlay: its themed
# status labels and the a11y name of its dedicated progress bar. None of
# these may ever be visible in the launcher window; the plain UI's own
# elements ("Update progress", status text) are the only progress surface.
OVERLAY_MARKERS = (
    "Reading the host's grimoire",
    "Waiting for your mod choice",
    "Match loading progress",
)

INSTANCE_NAME = "ffix-loading"
TEST_SCOPE = "ffix-loading"
LOBBY_ID = 424242
PORT = 49712
MOD_ID = "tests.loading-screen-evidence"
MOD_VERSION = "1.0.0"
PACKAGE_BYTES = 4 * 1024 * 1024
DOWNLOAD_PAUSE_BYTES = 1024 * 1024


class MatchLoadingFailure(RuntimeError):
    pass


def _assert_overlay_absent(names: list[str]) -> None:
    for name in names:
        for marker in OVERLAY_MARKERS:
            if marker in name:
                raise MatchLoadingFailure(
                    "the launcher window presented match loading "
                    f"screen content: {marker!r} appeared as {name!r}"
                )


def _windows_path(path: Path) -> str:
    completed = subprocess.run(
        ["wslpath", "-w", str(path.resolve())],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=5,
        check=False,
    )
    value = completed.stdout.strip()
    if completed.returncode != 0 or not value:
        raise MatchLoadingFailure(
            f"could not convert path for Windows: {path}: "
            f"{completed.stdout}"
        )
    return value


def _ps_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _powershell(script: str, *, timeout: float = 20) -> str:
    encoded_script = (
        "$OutputEncoding = "
        "[System.Text.UTF8Encoding]::new($false); "
        "[Console]::OutputEncoding = "
        "[System.Text.UTF8Encoding]::new($false); "
        + script
    )
    completed = subprocess.run(
        [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            encoded_script,
        ],
        cwd=ROOT,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        check=False,
    )
    if completed.returncode != 0:
        raise MatchLoadingFailure(
            f"PowerShell failed ({completed.returncode}): "
            f"{completed.stdout}"
        )
    return completed.stdout.strip()


def _visible_names(pid: int) -> list[str]:
    output = _powershell(
        f"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName UIAutomationClient
$process = Get-Process -Id {pid}
$root = [System.Windows.Automation.AutomationElement]::FromHandle(
    $process.MainWindowHandle)
$elements = $root.FindAll(
    [System.Windows.Automation.TreeScope]::Descendants,
    [System.Windows.Automation.Condition]::TrueCondition)
$names = @(
    for ($i = 0; $i -lt $elements.Count; $i++) {{
        $name = $elements.Item($i).Current.Name
        if (-not [string]::IsNullOrWhiteSpace($name)) {{ $name }}
    }})
$names | ConvertTo-Json -Compress
"""
    )
    if not output:
        return []
    parsed = json.loads(output)
    return [parsed] if isinstance(parsed, str) else list(parsed)


def _wait_for_names(
    pid: int,
    predicate,
    *,
    timeout: float,
    label: str,
) -> list[str]:
    deadline = time.monotonic() + timeout
    last: list[str] = []
    while time.monotonic() < deadline:
        try:
            last = _visible_names(pid)
        except (MatchLoadingFailure, json.JSONDecodeError):
            time.sleep(0.1)
            continue
        if predicate(last):
            return last
        time.sleep(0.1)
    raise MatchLoadingFailure(
        f"{label} timed out; visible text={last}"
    )


def _set_instance(pid: int) -> None:
    _powershell(
        f"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName UIAutomationClient
$process = Get-Process -Id {pid}
$root = [System.Windows.Automation.AutomationElement]::FromHandle(
    $process.MainWindowHandle)
$advanced = $root.FindFirst(
    [System.Windows.Automation.TreeScope]::Descendants,
    (New-Object System.Windows.Automation.PropertyCondition(
        [System.Windows.Automation.AutomationElement]::NameProperty,
        'Advanced')))
if ($null -eq $advanced) {{ throw 'Advanced expander was not found.' }}
$expand = $advanced.GetCurrentPattern(
    [System.Windows.Automation.ExpandCollapsePattern]::Pattern)
([System.Windows.Automation.ExpandCollapsePattern]$expand).Expand()
Start-Sleep -Milliseconds 150
$instance = $root.FindFirst(
    [System.Windows.Automation.TreeScope]::Descendants,
    (New-Object System.Windows.Automation.AndCondition(
        (New-Object System.Windows.Automation.PropertyCondition(
            [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
            [System.Windows.Automation.ControlType]::Edit)),
        (New-Object System.Windows.Automation.PropertyCondition(
            [System.Windows.Automation.AutomationElement]::NameProperty,
            'Instance')))))
if ($null -eq $instance) {{ throw 'Instance field was not found.' }}
$value = $instance.GetCurrentPattern(
    [System.Windows.Automation.ValuePattern]::Pattern)
([System.Windows.Automation.ValuePattern]$value).SetValue('{INSTANCE_NAME}')
$apply = $root.FindFirst(
    [System.Windows.Automation.TreeScope]::Descendants,
    (New-Object System.Windows.Automation.PropertyCondition(
        [System.Windows.Automation.AutomationElement]::NameProperty,
        'Apply')))
if ($null -eq $apply) {{ throw 'Instance Apply button was not found.' }}
$invoke = $apply.GetCurrentPattern(
    [System.Windows.Automation.InvokePattern]::Pattern)
([System.Windows.Automation.InvokePattern]$invoke).Invoke()
"""
    )


def _invoke_button(pid: int, name: str) -> None:
    _powershell(
        f"""
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName UIAutomationClient
$process = Get-Process -Id {pid}
$root = [System.Windows.Automation.AutomationElement]::FromHandle(
    $process.MainWindowHandle)
$button = $root.FindFirst(
    [System.Windows.Automation.TreeScope]::Descendants,
    (New-Object System.Windows.Automation.AndCondition(
        (New-Object System.Windows.Automation.PropertyCondition(
            [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
            [System.Windows.Automation.ControlType]::Button)),
        (New-Object System.Windows.Automation.PropertyCondition(
            [System.Windows.Automation.AutomationElement]::NameProperty,
            {_ps_literal(name)})))))
if ($null -eq $button) {{ throw 'Button was not found: {name}' }}
$invoke = $button.GetCurrentPattern(
    [System.Windows.Automation.InvokePattern]::Pattern)
([System.Windows.Automation.InvokePattern]$invoke).Invoke()
"""
    )


def _start_ui(activation: str = "") -> int:
    arguments = [f"--test-activation-scope={TEST_SCOPE}"]
    if activation:
        arguments.append(activation)
    ps_arguments = ",".join(_ps_literal(value) for value in arguments)
    output = _powershell(
        f"""
$ErrorActionPreference = 'Stop'
$process = Start-Process `
    -FilePath {_ps_literal(_windows_path(UI_EXECUTABLE))} `
    -ArgumentList @({ps_arguments}) `
    -PassThru
$process.Id
"""
    )
    try:
        return int(output.splitlines()[-1])
    except (ValueError, IndexError) as exc:
        raise MatchLoadingFailure(
            f"could not read desktop launcher PID: {output!r}"
        ) from exc


def _capture(pid: int, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        [
            "py.exe",
            "-3",
            _windows_path(CAPTURE_SCRIPT),
            "--pid",
            str(pid),
            "--title",
            "Solomon Dark",
            "--method",
            "window",
            "--output",
            _windows_path(path),
        ],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=20,
        check=False,
    )
    if completed.returncode != 0 or not path.is_file():
        raise MatchLoadingFailure(
            f"window capture failed: {completed.stdout}"
        )


def _descendants(pid: int) -> list[dict[str, Any]]:
    output = _powershell(
        f"""
$ErrorActionPreference = 'Stop'
$all = @(Get-CimInstance Win32_Process)
$pending = [System.Collections.Generic.Queue[uint32]]::new()
$pending.Enqueue([uint32]{pid})
$found = @()
while ($pending.Count -gt 0) {{
    $parent = $pending.Dequeue()
    foreach ($child in $all | Where-Object ParentProcessId -eq $parent) {{
        $found += [ordered]@{{
            pid = [int]$child.ProcessId
            path = [string]$child.ExecutablePath
            commandLine = [string]$child.CommandLine
        }}
        $pending.Enqueue([uint32]$child.ProcessId)
    }}
}}
$found | ConvertTo-Json -Compress
"""
    )
    if not output:
        return []
    parsed = json.loads(output)
    return [parsed] if isinstance(parsed, dict) else list(parsed)


def _stop_owned_processes(pid: int) -> dict[str, Any]:
    descendants = _descendants(pid)
    descendants.append(
        {
            "pid": pid,
            "path": _windows_path(UI_EXECUTABLE),
            "commandLine": "",
        }
    )
    expected_root = _windows_path(ROOT).rstrip("\\").lower() + "\\"
    owned = [
        process
        for process in descendants
        if str(process.get("path") or "")
        .lower()
        .startswith(expected_root)
    ]
    ignored = [
        process
        for process in descendants
        if process not in owned
    ]
    process_ids = ",".join(
        str(int(process["pid"]))
        for process in reversed(owned)
    )
    _powershell(
        f"""
$ErrorActionPreference = 'Stop'
foreach ($target in @({process_ids})) {{
    Stop-Process -Id $target -Force -ErrorAction SilentlyContinue
}}
"""
    )
    return {
        "stopped": owned,
        "ignoredOutsideWorktree": ignored,
    }


def _build_package() -> tuple[bytes, str]:
    manifest = json.dumps(
        {
            "id": MOD_ID,
            "name": "Loading Screen Evidence",
            "version": MOD_VERSION,
            "runtime": {
                "apiVersion": "0.2.0",
                "entryScript": "scripts/main.lua",
                "requiredCapabilities": [],
                "optionalCapabilities": [],
            },
        },
        separators=(",", ":"),
    ).encode()
    script = b"return true\n"
    payload = bytearray()
    counter = 0
    while len(payload) < PACKAGE_BYTES:
        payload.extend(
            hashlib.sha256(
                f"fieldfix-loading-{counter}".encode()
            ).digest()
        )
        counter += 1
    entries = {
        "manifest.json": manifest,
        "scripts/main.lua": script,
        "files/evidence.bin": bytes(payload[:PACKAGE_BYTES]),
    }
    aggregate = hashlib.sha256()
    for name, value in sorted(entries.items()):
        aggregate.update(
            name.encode()
            + b"\0"
            + hashlib.sha256(value).hexdigest().encode()
            + b"\n"
        )
    buffer = BytesIO()
    with zipfile.ZipFile(
        buffer,
        mode="w",
        compression=zipfile.ZIP_STORED,
    ) as archive:
        for name, value in entries.items():
            archive.writestr(name, value)
    return buffer.getvalue(), aggregate.hexdigest()


class _ThreadedHttpServer(
    socketserver.ThreadingMixIn,
    http.server.HTTPServer,
):
    daemon_threads = True
    allow_reuse_address = True


class DirectoryFixture:
    def __init__(
        self,
        package: bytes,
        content_sha256: str,
    ) -> None:
        self.package = package
        self.content_sha256 = content_sha256
        self.package_sha256 = hashlib.sha256(package).hexdigest()
        self.manifest_requested = threading.Event()
        self.allow_manifest = threading.Event()
        self.download_started = threading.Event()
        self.download_paused = threading.Event()
        self.allow_download_finish = threading.Event()
        self.download_bytes_sent = 0
        self.requests: list[dict[str, Any]] = []
        fixture = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                path = urllib.parse.urlsplit(self.path).path
                fixture.requests.append(
                    {"method": "GET", "path": path}
                )
                if path == (
                    f"/community/api/lobbies/{LOBBY_ID}/"
                    "join-manifest"
                ):
                    fixture.manifest_requested.set()
                    if not fixture.allow_manifest.wait(30):
                        self.send_error(504)
                        return
                    self._json(
                        {
                            "lobbyId": str(LOBBY_ID),
                            "mods": [
                                {
                                    "id": MOD_ID,
                                    "version": MOD_VERSION,
                                    "contentSha256":
                                        fixture.content_sha256,
                                }
                            ],
                        }
                    )
                    return
                if path == "/community/api/mods/loading-screen/download":
                    fixture.download_started.set()
                    self.send_response(200)
                    self.send_header(
                        "Content-Type",
                        "application/zip",
                    )
                    self.send_header(
                        "Content-Length",
                        str(len(fixture.package)),
                    )
                    self.end_headers()
                    try:
                        for offset in range(
                            0,
                            len(fixture.package),
                            64 * 1024,
                        ):
                            end = min(
                                offset + 64 * 1024,
                                len(fixture.package),
                            )
                            self.wfile.write(
                                fixture.package[offset:end]
                            )
                            self.wfile.flush()
                            fixture.download_bytes_sent = end
                            if (
                                end >= DOWNLOAD_PAUSE_BYTES
                                and not
                                fixture.allow_download_finish.is_set()
                            ):
                                fixture.download_paused.set()
                                fixture.allow_download_finish.wait(30)
                            time.sleep(0.05)
                    except (
                        BrokenPipeError,
                        ConnectionResetError,
                    ):
                        return
                    return
                self.send_error(404)

            def do_POST(self) -> None:  # noqa: N802
                path = urllib.parse.urlsplit(self.path).path
                length = int(
                    self.headers.get("Content-Length", "0")
                )
                payload = self.rfile.read(length)
                fixture.requests.append(
                    {
                        "method": "POST",
                        "path": path,
                        "body": payload.decode(
                            errors="replace"
                        ),
                    }
                )
                if path == "/community/api/mods/updates":
                    self._json({"updates": []})
                    return
                if path != "/community/api/mods/resolve":
                    self.send_error(404)
                    return
                self._json(
                    {
                        "mods": [
                            {
                                "id": MOD_ID,
                                "version": MOD_VERSION,
                                "contentSha256":
                                    fixture.content_sha256,
                                "packageSha256":
                                    fixture.package_sha256,
                                "name":
                                    "Loading Screen Evidence",
                                "fileSize": len(
                                    fixture.package
                                ),
                                "downloadUrl":
                                    "api/mods/loading-screen/"
                                    "download",
                            }
                        ],
                        "missing": [],
                    }
                )

            def _json(self, value: object) -> None:
                encoded = json.dumps(value).encode()
                self.send_response(200)
                self.send_header(
                    "Content-Type",
                    "application/json",
                )
                self.send_header(
                    "Content-Length",
                    str(len(encoded)),
                )
                self.end_headers()
                self.wfile.write(encoded)

            def log_message(
                self,
                format: str,
                *args: object,
            ) -> None:
                return

        self.server = _ThreadedHttpServer(
            ("127.0.0.1", PORT),
            Handler,
        )
        self.thread = threading.Thread(
            target=self.server.serve_forever,
            daemon=True,
        )

    def __enter__(self) -> DirectoryFixture:
        self.thread.start()
        return self

    def __exit__(self, *args: object) -> None:
        self.allow_manifest.set()
        self.allow_download_finish.set()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)


def _prepare_isolated_state() -> None:
    if not UI_EXECUTABLE.is_file():
        raise MatchLoadingFailure(
            f"desktop launcher is missing: {UI_EXECUTABLE}"
        )
    if not (GAME_DIRECTORY / "SolomonDark.exe").is_file():
        raise MatchLoadingFailure(
            f"game directory is invalid: {GAME_DIRECTORY}"
        )
    test_root = (
        UI_EXECUTABLE.parent
        / ".sdmod-test-data"
        / TEST_SCOPE
    )
    instance_root = (
        ROOT / "runtime/instances" / INSTANCE_NAME
    )
    for path, expected_parent in (
        (test_root, UI_EXECUTABLE.parent / ".sdmod-test-data"),
        (instance_root, ROOT / "runtime/instances"),
    ):
        resolved = path.resolve()
        if resolved.parent != expected_parent.resolve():
            raise MatchLoadingFailure(
                f"refusing to reset unexpected path: {resolved}"
            )
        if resolved.exists():
            shutil.rmtree(resolved)
    settings_root = (
        test_root / "SolomonDarkMultiplayerBeta"
    )
    settings_root.mkdir(parents=True)
    settings = {
        "gameDirectory": _windows_path(GAME_DIRECTORY),
        "directoryUrl":
            f"http://127.0.0.1:{PORT}/community",
        "activeSaveSlot": 0,
        "showStockTutorial": False,
        "disableAudio": True,
    }
    (settings_root / "settings.json").write_text(
        json.dumps(settings, indent=2) + "\n",
        encoding="utf-8",
    )


def _image_metrics(path: Path) -> dict[str, Any]:
    with Image.open(path) as image_file:
        width, height = image_file.size
    return {
        "path": str(path),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "width": width,
        "height": height,
    }


def verify(output_path: Path) -> dict[str, Any]:
    _prepare_isolated_state()
    package, content_sha256 = _build_package()
    run_stamp = datetime.now(timezone.utc).strftime(
        "%Y%m%dT%H%M%SZ"
    )
    capture_root = (
        EVIDENCE_ROOT
        / f"match-loading-launcher-{run_stamp}"
    )
    record: dict[str, Any] = {
        "ok": False,
        "instance": INSTANCE_NAME,
        "testScope": TEST_SCOPE,
        "port": PORT,
        "audioExpectedDisabled": True,
        "gameLaunched": False,
    }
    ui_pid = 0
    fixture: DirectoryFixture | None = None
    failure: BaseException | None = None
    try:
        with DirectoryFixture(
            package,
            content_sha256,
        ) as fixture:
            ui_pid = _start_ui()
            record["uiPid"] = ui_pid
            _wait_for_names(
                ui_pid,
                lambda names: "Ready" in names,
                timeout=30,
                label="desktop launcher readiness",
            )
            _set_instance(ui_pid)
            _wait_for_names(
                ui_pid,
                lambda names: "Ready" in names,
                timeout=30,
                label="ffix instance readiness",
            )

            directory = urllib.parse.quote(
                f"http://127.0.0.1:{PORT}/community",
                safe="",
            )
            activation = (
                "solomondarkrevived://join/"
                f"{LOBBY_ID}?directory={directory}"
            )
            forwarding_pid = _start_ui(activation)
            record["forwardingPid"] = forwarding_pid
            if not fixture.manifest_requested.wait(15):
                raise MatchLoadingFailure(
                    "join preview never requested the live lobby "
                    "manifest"
                )
            inspecting_names = _wait_for_names(
                ui_pid,
                lambda names: (
                    "The launcher checks the host's mod list."
                    in names
                ),
                timeout=10,
                label="plain host-mod inspection status",
            )
            _assert_overlay_absent(inspecting_names)
            inspecting_path = (
                capture_root / "01-inspecting-host-mods.png"
            )
            _capture(ui_pid, inspecting_path)

            fixture.allow_manifest.set()
            consent_names = _wait_for_names(
                ui_pid,
                lambda names: (
                    "The host has mods" in names
                    and "Yes" in names
                ),
                timeout=15,
                label="plain host-mod consent dialog",
            )
            _assert_overlay_absent(consent_names)
            consent_path = (
                capture_root / "02-awaiting-mod-consent.png"
            )
            _capture(ui_pid, consent_path)
            _invoke_button(ui_pid, "Yes")

            if not fixture.download_started.wait(20):
                raise MatchLoadingFailure(
                    "confirmed join never started the real package "
                    "download"
                )
            if not fixture.download_paused.wait(20):
                raise MatchLoadingFailure(
                    "real package download did not reach its paused "
                    "byte checkpoint"
                )
            stalled_names_a = _wait_for_names(
                ui_pid,
                lambda names: (
                    any(
                        name.startswith(
                            f"Downloading {MOD_ID}"
                        )
                        for name in names
                    )
                    and any("1 MB of 4 MB" in name for name in names)
                    and "Update progress" in names
                ),
                timeout=10,
                label="plain mod download progress",
            )
            _assert_overlay_absent(stalled_names_a)
            download_path_a = (
                capture_root / "03-mod-sync-paused-a.png"
            )
            _capture(ui_pid, download_path_a)
            time.sleep(1.0)
            stalled_names_b = _visible_names(ui_pid)
            download_path_b = (
                capture_root / "04-mod-sync-paused-b.png"
            )
            _capture(ui_pid, download_path_b)
            if stalled_names_a != stalled_names_b:
                raise MatchLoadingFailure(
                    "paused mod sync changed its honest visible "
                    "state without new bytes"
                )

            record["stages"] = [
                {
                    "stage": "inspecting_host_mods",
                    "status":
                        "The launcher checks the host's mod list.",
                    "visibleText": inspecting_names,
                    "capture": _image_metrics(
                        inspecting_path
                    ),
                },
                {
                    "stage": "awaiting_mod_consent",
                    "visibleText": consent_names,
                    "capture": _image_metrics(consent_path),
                },
                {
                    "stage": "synchronizing_host_mods",
                    "source": {
                        "bytesCompleted":
                            fixture.download_bytes_sent,
                        "bytesTotal": len(package),
                    },
                    "visibleText": stalled_names_a,
                    "capture": _image_metrics(
                        download_path_a
                    ),
                },
            ]
            record["overlayAbsent"] = True
            record["overlayMarkers"] = list(OVERLAY_MARKERS)
            record["stalledStage"] = {
                "waitMilliseconds": 1000,
                "visibleStateUnchanged": True,
                "firstCapture": _image_metrics(
                    download_path_a
                ),
                "secondCapture": _image_metrics(
                    download_path_b
                ),
            }
            record["requests"] = fixture.requests
            record["ok"] = True
    except BaseException as exc:
        failure = exc
        record["failure"] = {
            "type": type(exc).__name__,
            "message": str(exc),
        }
    finally:
        if fixture is not None:
            fixture.allow_manifest.set()
            fixture.allow_download_finish.set()
        if ui_pid:
            try:
                record["cleanup"] = _stop_owned_processes(
                    ui_pid
                )
            except BaseException as cleanup_error:
                record["cleanupFailure"] = {
                    "type": type(cleanup_error).__name__,
                    "message": str(cleanup_error),
                }
                if failure is None:
                    failure = cleanup_error
                    record["ok"] = False
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(record, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
    if failure is not None:
        raise failure
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=OUTPUT_PATH,
    )
    args = parser.parse_args()
    result = verify(args.output)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
