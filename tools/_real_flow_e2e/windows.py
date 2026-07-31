from __future__ import annotations

from dataclasses import dataclass
import base64
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import time
from typing import Any, Callable

from .config import HarnessConfig, PeerConfig


class WindowsHarnessError(RuntimeError):
    """A local Windows launch, UI, input, or ownership check failed."""

OBSERVER_MOD_ID = "tool.real_flow_e2e_observer"
BOT_PLAY_MOD_ID = "bot.brain"
BOT_PLAY_TEAM_ROSTER = [
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
    {
        "name": "Gale",
        "element": "air",
        "discipline": "body",
        "behavior": "skirmisher",
    },
]


def ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def windows_path(path: Path) -> str:
    completed = subprocess.run(
        ["wslpath", "-w", str(path.resolve())],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=10,
        check=False,
    )
    result = completed.stdout.strip()
    if completed.returncode != 0 or not result:
        raise WindowsHarnessError(
            f"could not convert path for Windows: {path}: {completed.stdout}"
        )
    return result


def _json_array(value: Any) -> list[Any]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return value
    return [value]


class PowerShell:
    def __init__(self, working_directory: Path) -> None:
        self.working_directory = working_directory

    def run(self, script: str, *, timeout: float = 30.0) -> str:
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
                "powershell.exe",
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-EncodedCommand",
                encoded,
            ],
            cwd=self.working_directory,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=timeout,
            check=False,
        )
        if completed.returncode != 0:
            raise WindowsHarnessError(
                f"PowerShell failed ({completed.returncode}): "
                f"{completed.stdout.strip()}"
            )
        return completed.stdout.strip()

    def launch_and_read_result(
        self,
        script: str,
        result_path: Path,
        *,
        timeout: float = 30.0,
    ) -> str:
        if result_path.exists():
            raise WindowsHarnessError(
                f"detached launch result path must be new: {result_path}"
            )
        result_path.parent.mkdir(parents=True, exist_ok=True)
        prefix = (
            "$ErrorActionPreference='Stop';"
            "$ProgressPreference='SilentlyContinue';"
        )
        encoded = base64.b64encode(
            (prefix + script).encode("utf-16le")
        ).decode("ascii")
        process = subprocess.Popen(
            [
                "powershell.exe",
                "-NoLogo",
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-EncodedCommand",
                encoded,
            ],
            cwd=self.working_directory,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if result_path.is_file():
                value = result_path.read_text(
                    encoding="utf-8",
                    errors="replace",
                ).strip()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.terminate()
                    process.wait(timeout=5)
                return value
            status = process.poll()
            if status is not None:
                raise WindowsHarnessError(
                    "detached PowerShell launch exited before writing its "
                    f"result; exit={status}"
                )
            time.sleep(0.05)
        process.terminate()
        process.wait(timeout=5)
        raise WindowsHarnessError(
            f"detached PowerShell launch timed out: {result_path}"
        )


@dataclass(frozen=True)
class ProcessRecord:
    pid: int
    parent_pid: int
    executable_path: str
    command_line: str


@dataclass(frozen=True)
class UiElement:
    name: str
    control_type: str
    automation_id: str
    enabled: bool
    offscreen: bool
    value: str


@dataclass
class WindowsPeer:
    config: PeerConfig
    bundle_root: Path
    settings_root: Path
    runtime_root: Path
    ui_executable: Path
    game_executable: Path
    telemetry_path: Path
    ui_pid: int = 0
    game_pid: int = 0
    lobby_id: int = 0
    explicit_launch_game: bool = False

    @property
    def owned_roots(self) -> tuple[Path, ...]:
        return (self.bundle_root, self.settings_root, self.runtime_root)


def prepare_windows_peer(
    harness: HarnessConfig,
    peer: PeerConfig,
) -> WindowsPeer:
    staging_root = harness.windows_staging_root / peer.role
    bundle_root = staging_root / "launcher"
    if staging_root.exists():
        raise WindowsHarnessError(
            f"peer staging root must be new: {staging_root}"
        )
    staging_root.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        harness.package_root,
        bundle_root,
        symlinks=False,
        copy_function=shutil.copy2,
    )
    settings_root = (
        bundle_root
        / ".sdmod-test-data"
        / peer.launcher_scope
        / "SolomonDarkMultiplayerBeta"
    )
    settings_root.mkdir(parents=True, exist_ok=False)
    settings_path = settings_root / "settings.json"
    settings = {
        "gameDirectory": windows_path(harness.game_directory),
        "directoryUrl": harness.directory_url,
        "activeSaveSlot": 0,
        "showStockTutorial": False,
        "disableAudio": True,
    }
    settings_path.write_text(
        json.dumps(settings, indent=2) + "\n",
        encoding="utf-8",
    )
    runtime_root = settings_root / "runtime"
    observer_source = (
        harness.source_root
        / "tools"
        / "_real_flow_e2e"
        / "observer_mod"
    )
    observer_destination = (
        bundle_root / "mods" / OBSERVER_MOD_ID
    )
    if not (observer_source / "manifest.json").is_file():
        raise WindowsHarnessError(
            f"read-only observer mod is missing: {observer_source}"
        )
    observer_destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        observer_source,
        observer_destination,
        symlinks=False,
        copy_function=shutil.copy2,
    )
    mod_state_path = (
        runtime_root
        / "instances"
        / peer.instance
        / "mod-manager-state.json"
    )
    mod_state_path.parent.mkdir(parents=True, exist_ok=True)
    enabled_mods = {
        OBSERVER_MOD_ID: {
            "Enabled": True,
        },
    }
    if harness.bot_play_for_me:
        bot_source = harness.source_root / "mods" / "bot-brain"
        bot_destination = bundle_root / "mods" / "bot-brain"
        if not (bot_source / "manifest.json").is_file():
            raise WindowsHarnessError(
                f"Bot Play For Me mod is missing: {bot_source}"
            )
        shutil.copytree(
            bot_source,
            bot_destination,
            symlinks=False,
            copy_function=shutil.copy2,
        )
        enabled_mods[BOT_PLAY_MOD_ID] = {
            "Enabled": True,
        }
        settings_path = (
            runtime_root
            / "instances"
            / peer.instance
            / "stage"
            / ".sdmod"
            / "mod-settings"
            / f"{BOT_PLAY_MOD_ID}.json"
        )
        settings_path.parent.mkdir(parents=True, exist_ok=True)
        settings_path.write_text(
            json.dumps(
                {
                    "schemaVersion": 1,
                    "values": {
                        "play_for_me": False,
                        "play_for_me_behavior": "skirmisher",
                        "roster": [],
                    },
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
    mod_state_path.write_text(
        json.dumps(
            {
                "Mods": enabled_mods,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    game_executable = (
        runtime_root
        / "instances"
        / peer.instance
        / "stage"
        / "SolomonDark.exe"
    )
    telemetry_path = (
        runtime_root
        / "instances"
        / peer.instance
        / "stage"
        / ".sdmod"
        / "logs"
        / "network-telemetry.jsonl"
    )
    longest_runtime_asset = (
        runtime_root
        / "instances"
        / peer.instance
        / "stage"
        / ".sdmod"
        / "assets"
        / "loading"
        / "Wizards_dire_BG.png"
    )
    safe_path_candidates = [longest_runtime_asset]
    if harness.bot_play_for_me:
        bot_storage_key = hashlib.sha256(
            BOT_PLAY_MOD_ID.encode("utf-8")
        ).hexdigest()
        staged_bot_root = (
            runtime_root
            / "instances"
            / peer.instance
            / "stage"
            / ".sdmod"
            / "runtime"
            / "mods"
            / bot_storage_key
        )
        safe_path_candidates.extend(
            staged_bot_root / source.relative_to(bot_source)
            for source in bot_source.rglob("*")
            if source.is_file()
        )
    longest_windows_path = max(
        (windows_path(path) for path in safe_path_candidates),
        key=len,
    )
    if len(longest_windows_path) >= 248:
        raise WindowsHarnessError(
            "staged Windows runtime path exceeds the native safe path "
            f"budget ({len(longest_windows_path)} >= 248): "
            f"{longest_windows_path}"
        )
    return WindowsPeer(
        config=peer,
        bundle_root=bundle_root,
        settings_root=settings_root,
        runtime_root=runtime_root,
        ui_executable=bundle_root / "SolomonDarkMultiplayerBeta.exe",
        game_executable=game_executable,
        telemetry_path=telemetry_path,
    )


def windows_processes(ps: PowerShell) -> list[ProcessRecord]:
    output = ps.run(
        """
@(Get-CimInstance Win32_Process | ForEach-Object {
  [ordered]@{
    pid=[int]$_.ProcessId
    parentPid=[int]$_.ParentProcessId
    executablePath=[string]$_.ExecutablePath
    commandLine=[string]$_.CommandLine
  }
}) | ConvertTo-Json -Compress
""",
        timeout=30,
    )
    if not output:
        return []
    try:
        parsed = json.loads(output)
    except json.JSONDecodeError as exc:
        raise WindowsHarnessError(
            f"could not parse Windows process inventory: {output!r}"
        ) from exc
    return [
        ProcessRecord(
            pid=int(row["pid"]),
            parent_pid=int(row["parentPid"]),
            executable_path=str(row.get("executablePath") or ""),
            command_line=str(row.get("commandLine") or ""),
        )
        for row in _json_array(parsed)
    ]


def port_inventory(ps: PowerShell, ports: set[int]) -> list[dict[str, Any]]:
    if not ports:
        return []
    literals = ",".join(str(port) for port in sorted(ports))
    output = ps.run(
        f"""
$ports=@({literals})
$rows=@()
foreach($port in $ports) {{
  foreach($endpoint in @(Get-NetUDPEndpoint -LocalPort $port -ErrorAction SilentlyContinue)) {{
    $process=Get-CimInstance Win32_Process -Filter ('ProcessId=' + $endpoint.OwningProcess)
    $rows += [ordered]@{{
      protocol='udp'
      localAddress=[string]$endpoint.LocalAddress
      localPort=[int]$endpoint.LocalPort
      pid=[int]$endpoint.OwningProcess
      executablePath=[string]$process.ExecutablePath
      commandLine=[string]$process.CommandLine
    }}
  }}
  foreach($endpoint in @(Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue)) {{
    $process=Get-CimInstance Win32_Process -Filter ('ProcessId=' + $endpoint.OwningProcess)
    $rows += [ordered]@{{
      protocol='tcp'
      localAddress=[string]$endpoint.LocalAddress
      localPort=[int]$endpoint.LocalPort
      pid=[int]$endpoint.OwningProcess
      executablePath=[string]$process.ExecutablePath
      commandLine=[string]$process.CommandLine
    }}
  }}
}}
$rows | ConvertTo-Json -Compress
""",
        timeout=30,
    )
    if not output:
        return []
    return [
        dict(row)
        for row in _json_array(json.loads(output))
    ]


def assert_ports_free(ps: PowerShell, ports: set[int]) -> None:
    occupied = port_inventory(ps, ports)
    if occupied:
        raise WindowsHarnessError(
            f"reserved ports are already occupied: {occupied}"
        )


def launch_environment(
    harness: HarnessConfig,
    peer: WindowsPeer,
) -> dict[str, str]:
    config = peer.config
    environment = {
        "SDMOD_NETWORK_TELEMETRY": "1",
        "SDMOD_DISABLE_AUDIO": "1",
        "SDMOD_LUA_EXEC_PIPE_NAME": config.pipe_name,
        "SDMOD_LUA_EXEC_TARGET_MOD_ID": OBSERVER_MOD_ID,
        "SDMOD_MULTIPLAYER_PLAYER_NAME": config.player_name,
        # The production launcher enables the stock quick-start join flow.
        # A fresh harness profile also needs deterministic choices on the
        # actual create-character surface so it can complete that same flow.
        "SDMOD_MULTIPLAYER_QUICK_START_ELEMENT":
            config.loadout_element,
        "SDMOD_MULTIPLAYER_QUICK_START_DISCIPLINE":
            config.loadout_discipline,
        "SDMOD_MULTIPLAYER_QUICK_START_RUN": "",
    }
    if harness.topology in {
        "loopback_windows",
        "loopback_windows_botplay",
        "wan_udp_nfo",
    }:
        environment.update(
            {
                "SDMOD_MULTIPLAYER_TRANSPORT": "local_udp",
                "SDMOD_MULTIPLAYER_ROLE": config.role,
                "SDMOD_MULTIPLAYER_LOCAL_PORT": str(config.local_port),
                "SDMOD_MULTIPLAYER_REMOTE_HOST": config.remote_host,
                "SDMOD_MULTIPLAYER_REMOTE_PORT": str(config.remote_port),
                "SDMOD_MULTIPLAYER_PARTICIPANT_ID": str(
                    config.participant_id
                ),
            }
        )
        if harness.topology == "loopback_windows_botplay":
            environment["SDMOD_MULTIPLAYER_MAX_PARTICIPANTS"] = "4"
    else:
        environment["SDMOD_MULTIPLAYER_TRANSPORT"] = "steam"
        environment["SDMOD_MULTIPLAYER_ROLE"] = config.role
    return environment


def start_ui(
    ps: PowerShell,
    harness: HarnessConfig,
    peer: WindowsPeer,
) -> int:
    if not peer.ui_executable.is_file():
        raise WindowsHarnessError(
            f"staged desktop launcher is missing: {peer.ui_executable}"
        )
    env_rows = "\n".join(
        (
            f"$start.EnvironmentVariables[{ps_quote(key)}]="
            f"{ps_quote(value)};"
        )
        for key, value in launch_environment(harness, peer).items()
    )
    argument = f"--test-activation-scope={peer.config.launcher_scope}"
    result_path = peer.bundle_root.parent / "launcher-ui.pid"
    output = ps.launch_and_read_result(
        f"""
$start=[System.Diagnostics.ProcessStartInfo]::new()
$start.FileName={ps_quote(windows_path(peer.ui_executable))}
$start.WorkingDirectory={ps_quote(windows_path(peer.bundle_root))}
$start.UseShellExecute=$false
$start.CreateNoWindow=$false
$start.Arguments={ps_quote(argument)}
{env_rows}
$process=[System.Diagnostics.Process]::Start($start)
if($null -eq $process){{throw 'desktop launcher did not start'}}
[System.IO.File]::WriteAllText(
  {ps_quote(windows_path(result_path))},
  [string]$process.Id,
  [System.Text.UTF8Encoding]::new($false))
""",
        result_path,
        timeout=20,
    )
    if not output.isdigit():
        raise WindowsHarnessError(
            f"desktop launcher returned no PID: {output!r}"
        )
    peer.ui_pid = int(output)
    return peer.ui_pid


def ui_elements(ps: PowerShell, pid: int) -> list[UiElement]:
    output = ps.run(
        f"""
Add-Type -AssemblyName UIAutomationClient
$process=Get-Process -Id {pid}
$process.Refresh()
if($process.MainWindowHandle -eq 0){{throw 'launcher has no main window'}}
$root=[System.Windows.Automation.AutomationElement]::FromHandle(
  $process.MainWindowHandle)
$elements=$root.FindAll(
  [System.Windows.Automation.TreeScope]::Descendants,
  [System.Windows.Automation.Condition]::TrueCondition)
$rows=@()
for($index=0;$index -lt $elements.Count;$index++){{
  $element=$elements.Item($index)
  $value=''
  $pattern=$null
  if($element.TryGetCurrentPattern(
      [System.Windows.Automation.ValuePattern]::Pattern,
      [ref]$pattern)){{
    $value=[string]$pattern.Current.Value
  }}
  $rows += [ordered]@{{
    name=[string]$element.Current.Name
    controlType=[string]$element.Current.ControlType.ProgrammaticName
    automationId=[string]$element.Current.AutomationId
    enabled=[bool]$element.Current.IsEnabled
    offscreen=[bool]$element.Current.IsOffscreen
    value=$value
  }}
}}
$rows | ConvertTo-Json -Compress
""",
        timeout=20,
    )
    if not output:
        return []
    return [
        UiElement(
            name=str(row.get("name") or ""),
            control_type=str(row.get("controlType") or ""),
            automation_id=str(row.get("automationId") or ""),
            enabled=bool(row.get("enabled")),
            offscreen=bool(row.get("offscreen")),
            value=str(row.get("value") or ""),
        )
        for row in _json_array(json.loads(output))
    ]


def wait_ui(
    ps: PowerShell,
    pid: int,
    predicate: Callable[[list[UiElement]], bool],
    *,
    timeout: float,
    label: str,
) -> list[UiElement]:
    deadline = time.monotonic() + timeout
    last: list[UiElement] = []
    last_error = ""
    while time.monotonic() < deadline:
        try:
            last = ui_elements(ps, pid)
            if predicate(last):
                return last
        except (WindowsHarnessError, json.JSONDecodeError) as exc:
            last_error = str(exc)
        time.sleep(0.1)
    names = [element.name for element in last if element.name]
    raise WindowsHarnessError(
        f"{label} timed out; names={names!r} last_error={last_error!r}"
    )


def invoke_button(ps: PowerShell, pid: int, name: str) -> None:
    ps.run(
        f"""
Add-Type -AssemblyName UIAutomationClient
$process=Get-Process -Id {pid}
$root=[System.Windows.Automation.AutomationElement]::FromHandle(
  $process.MainWindowHandle)
$condition=New-Object System.Windows.Automation.AndCondition(
  (New-Object System.Windows.Automation.PropertyCondition(
    [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
    [System.Windows.Automation.ControlType]::Button)),
  (New-Object System.Windows.Automation.PropertyCondition(
    [System.Windows.Automation.AutomationElement]::NameProperty,
    {ps_quote(name)})))
$matches=$root.FindAll(
  [System.Windows.Automation.TreeScope]::Descendants,
  $condition)
$usable=@()
for($index=0;$index -lt $matches.Count;$index++){{
  $candidate=$matches.Item($index)
  if($candidate.Current.IsEnabled -and -not $candidate.Current.IsOffscreen){{
    $usable += $candidate
  }}
}}
if($usable.Count -ne 1){{
  throw ('expected exactly one visible enabled button named {name}; count=' +
    $usable.Count)
}}
$pattern=$usable[0].GetCurrentPattern(
  [System.Windows.Automation.InvokePattern]::Pattern)
([System.Windows.Automation.InvokePattern]$pattern).Invoke()
""",
        timeout=20,
    )


def select_radio(ps: PowerShell, pid: int, name: str) -> None:
    ps.run(
        f"""
Add-Type -AssemblyName UIAutomationClient
$process=Get-Process -Id {pid}
$root=[System.Windows.Automation.AutomationElement]::FromHandle(
  $process.MainWindowHandle)
$condition=New-Object System.Windows.Automation.PropertyCondition(
  [System.Windows.Automation.AutomationElement]::NameProperty,
  {ps_quote(name)})
$matches=$root.FindAll(
  [System.Windows.Automation.TreeScope]::Descendants,
  $condition)
$walker=[System.Windows.Automation.TreeWalker]::ControlViewWalker
$selected=$false
for($index=0;$index -lt $matches.Count -and -not $selected;$index++){{
  $candidate=$matches.Item($index)
  for($depth=0;$depth -lt 5 -and $null -ne $candidate;$depth++){{
    if($candidate.Current.IsEnabled -and -not $candidate.Current.IsOffscreen){{
      $pattern=$null
      if($candidate.TryGetCurrentPattern(
          [System.Windows.Automation.SelectionItemPattern]::Pattern,
          [ref]$pattern)){{
        ([System.Windows.Automation.SelectionItemPattern]$pattern).Select()
        $selected=$true
        break
      }}
      if($candidate.TryGetCurrentPattern(
          [System.Windows.Automation.TogglePattern]::Pattern,
          [ref]$pattern)){{
        $toggle=[System.Windows.Automation.TogglePattern]$pattern
        if($toggle.Current.ToggleState -ne
            [System.Windows.Automation.ToggleState]::On){{
          $toggle.Toggle()
        }}
        $selected=$true
        break
      }}
    }}
    $candidate=$walker.GetParent($candidate)
  }}
}}
if(-not $selected){{
  throw 'requested lobby privacy radio is unavailable'
}}
""",
        timeout=20,
    )


def set_instance(ps: PowerShell, peer: WindowsPeer) -> None:
    pid = peer.ui_pid
    ps.run(
        f"""
Add-Type -AssemblyName UIAutomationClient
$process=Get-Process -Id {pid}
$root=[System.Windows.Automation.AutomationElement]::FromHandle(
  $process.MainWindowHandle)
$advanced=$root.FindFirst(
  [System.Windows.Automation.TreeScope]::Descendants,
  (New-Object System.Windows.Automation.PropertyCondition(
    [System.Windows.Automation.AutomationElement]::NameProperty,
    'Advanced')))
if($null -eq $advanced){{throw 'Advanced expander was not found'}}
$expand=$advanced.GetCurrentPattern(
  [System.Windows.Automation.ExpandCollapsePattern]::Pattern)
([System.Windows.Automation.ExpandCollapsePattern]$expand).Expand()
Start-Sleep -Milliseconds 150
$condition=New-Object System.Windows.Automation.AndCondition(
  (New-Object System.Windows.Automation.PropertyCondition(
    [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
    [System.Windows.Automation.ControlType]::Edit)),
  (New-Object System.Windows.Automation.PropertyCondition(
    [System.Windows.Automation.AutomationElement]::NameProperty,
    'Instance')))
$instance=$root.FindFirst(
  [System.Windows.Automation.TreeScope]::Descendants,
  $condition)
if($null -eq $instance){{throw 'Instance edit was not found'}}
$value=$instance.GetCurrentPattern(
  [System.Windows.Automation.ValuePattern]::Pattern)
([System.Windows.Automation.ValuePattern]$value).SetValue(
  {ps_quote(peer.config.instance)})
$apply=$root.FindFirst(
  [System.Windows.Automation.TreeScope]::Descendants,
  (New-Object System.Windows.Automation.PropertyCondition(
    [System.Windows.Automation.AutomationElement]::NameProperty,
    'Apply')))
if($null -eq $apply){{throw 'Instance Apply button was not found'}}
$invoke=$apply.GetCurrentPattern(
  [System.Windows.Automation.InvokePattern]::Pattern)
([System.Windows.Automation.InvokePattern]$invoke).Invoke()
([System.Windows.Automation.ExpandCollapsePattern]$expand).Collapse()
""",
        timeout=20,
    )
    wait_ui(
        ps,
        pid,
        lambda elements: any(
            element.name == "Ready" and not element.offscreen
            for element in elements
        ),
        timeout=45,
        label=f"{peer.config.role} instance apply",
    )


def set_lobby_id(ps: PowerShell, pid: int, lobby_id: int) -> None:
    ps.run(
        f"""
Add-Type -AssemblyName UIAutomationClient
$process=Get-Process -Id {pid}
$root=[System.Windows.Automation.AutomationElement]::FromHandle(
  $process.MainWindowHandle)
$condition=New-Object System.Windows.Automation.PropertyCondition(
  [System.Windows.Automation.AutomationElement]::ControlTypeProperty,
  [System.Windows.Automation.ControlType]::Edit)
$matches=$root.FindAll(
  [System.Windows.Automation.TreeScope]::Descendants,
  $condition)
$usable=@()
for($index=0;$index -lt $matches.Count;$index++){{
  $candidate=$matches.Item($index)
  if($candidate.Current.IsEnabled -and -not $candidate.Current.IsOffscreen){{
    $pattern=$null
    if($candidate.TryGetCurrentPattern(
        [System.Windows.Automation.ValuePattern]::Pattern,
        [ref]$pattern)){{
      $usable += [pscustomobject]@{{
        element=$candidate
        pattern=$pattern
        name=[string]$candidate.Current.Name
      }}
    }}
  }}
}}
$named=@($usable | Where-Object {{
  $_.name -eq 'Lobby ID' -or $_.name -like '*Lobby ID*'
}})
$target=if($named.Count -eq 1){{$named[0]}}elseif($usable.Count -eq 1){{
  $usable[0]
}}else{{$null}}
if($null -eq $target){{
  throw ('could not uniquely resolve the visible Lobby ID edit; count=' +
    $usable.Count)
}}
([System.Windows.Automation.ValuePattern]$target.pattern).SetValue(
  {ps_quote(str(lobby_id))})
""",
        timeout=20,
    )


def read_lobby_id(ps: PowerShell, pid: int) -> int:
    elements = ui_elements(ps, pid)
    candidates: set[int] = set()
    for element in elements:
        if element.value.isdigit():
            value = int(element.value)
            if value > 4:
                candidates.add(value)
        match = re.fullmatch(r"Lobby\s+([0-9]+)", element.name)
        if match:
            candidates.add(int(match.group(1)))
    if len(candidates) != 1:
        raise WindowsHarnessError(
            f"could not uniquely resolve launcher lobby ID: {candidates}"
        )
    return candidates.pop()


def expected_game_path(peer: WindowsPeer) -> str:
    return windows_path(peer.game_executable)


def resolve_game_process(
    ps: PowerShell,
    peer: WindowsPeer,
) -> ProcessRecord | None:
    expected = expected_game_path(peer)
    matches = [
        process
        for process in windows_processes(ps)
        if process.executable_path.casefold() == expected.casefold()
    ]
    if len(matches) > 1:
        raise WindowsHarnessError(
            f"multiple processes own staged game path {expected}: {matches}"
        )
    if not matches:
        return None
    peer.game_pid = matches[0].pid
    return matches[0]


def wait_game_process(
    ps: PowerShell,
    peer: WindowsPeer,
    *,
    timeout: float,
) -> ProcessRecord:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        record = resolve_game_process(ps, peer)
        if record is not None:
            return record
        time.sleep(0.2)
    raise WindowsHarnessError(
        f"staged {peer.config.role} game did not start: "
        f"{expected_game_path(peer)}"
    )


def host_through_launcher(
    ps: PowerShell,
    harness: HarnessConfig,
    peer: WindowsPeer,
) -> dict[str, Any]:
    start_ui(ps, harness, peer)
    wait_ui(
        ps,
        peer.ui_pid,
        lambda elements: any(
            element.name == "Ready" and not element.offscreen
            for element in elements
        ),
        timeout=45,
        label="host launcher readiness",
    )
    set_instance(ps, peer)
    invoke_button(ps, peer.ui_pid, "Host Game")
    wait_ui(
        ps,
        peer.ui_pid,
        lambda elements: any(
            element.name == "Start Lobby" and not element.offscreen
            for element in elements
        ),
        timeout=10,
        label="host lobby setup",
    )
    select_radio(
        ps,
        peer.ui_pid,
        "Friends Only" if harness.privacy == "friends" else "Public",
    )
    invoke_button(ps, peer.ui_pid, "Start Lobby")
    process = wait_game_process(ps, peer, timeout=harness.timeout_seconds)
    deadline = time.monotonic() + harness.timeout_seconds
    last_error = ""
    while time.monotonic() < deadline:
        try:
            peer.lobby_id = read_lobby_id(ps, peer.ui_pid)
            break
        except WindowsHarnessError as exc:
            last_error = str(exc)
            time.sleep(0.2)
    if peer.lobby_id == 0:
        raise WindowsHarnessError(
            f"host launcher did not publish a lobby ID: {last_error}"
        )
    return {
        "uiPid": peer.ui_pid,
        "gamePid": process.pid,
        "gameExecutable": process.executable_path,
        "lobbyId": peer.lobby_id,
        "privacy": harness.privacy,
    }


def client_through_launcher(
    ps: PowerShell,
    harness: HarnessConfig,
    peer: WindowsPeer,
    lobby_id: int,
) -> dict[str, Any]:
    start_ui(ps, harness, peer)
    wait_ui(
        ps,
        peer.ui_pid,
        lambda elements: any(
            element.name == "Ready" and not element.offscreen
            for element in elements
        ),
        timeout=45,
        label="client launcher readiness",
    )
    set_instance(ps, peer)
    set_lobby_id(ps, peer.ui_pid, lobby_id)
    invoke_button(ps, peer.ui_pid, "Join Game")
    deadline = time.monotonic() + harness.timeout_seconds
    joined_names: list[str] = []
    process: ProcessRecord | None = None
    while time.monotonic() < deadline:
        process = resolve_game_process(ps, peer)
        elements = ui_elements(ps, peer.ui_pid)
        joined_names = [
            element.name
            for element in elements
            if element.name and not element.offscreen
        ]
        if "Launch Game" in joined_names:
            invoke_button(ps, peer.ui_pid, "Launch Game")
            peer.explicit_launch_game = True
            process = wait_game_process(
                ps,
                peer,
                timeout=harness.timeout_seconds,
            )
            break
        if process is not None:
            # The supported local_udp desktop path combines Join Game and
            # launch because no Steam lobby helper exists for that backend.
            peer.explicit_launch_game = False
            break
        time.sleep(0.2)
    if process is None:
        raise WindowsHarnessError(
            "client launcher neither reached its explicit Launch Game "
            f"boundary nor started its staged game; visible={joined_names}"
        )
    if harness.topology.startswith("steam_") and not peer.explicit_launch_game:
        raise WindowsHarnessError(
            "Steam topology bypassed the required explicit Launch Game boundary"
        )
    peer.lobby_id = lobby_id
    return {
        "uiPid": peer.ui_pid,
        "gamePid": process.pid,
        "gameExecutable": process.executable_path,
        "lobbyId": lobby_id,
        "explicitLaunchGame": peer.explicit_launch_game,
        "visibleAtLaunch": joined_names,
    }


def run_windows_python(
    script: Path,
    arguments: list[str],
    *,
    cwd: Path,
    timeout: float,
) -> str:
    completed = subprocess.run(
        ["py.exe", "-3", windows_path(script), *arguments],
        cwd=cwd,
        text=True,
        encoding="utf-8",
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        check=False,
    )
    if completed.returncode != 0:
        raise WindowsHarnessError(
            f"Windows input/capture helper failed ({completed.returncode}): "
            f"{completed.stdout.strip()}"
        )
    return completed.stdout.strip()


def run_owned_input(
    script: Path,
    arguments: list[str],
    *,
    cwd: Path,
    timeout: float,
) -> str:
    last_error: WindowsHarnessError | None = None
    for attempt in range(3):
        try:
            return run_windows_python(
                script,
                arguments,
                cwd=cwd,
                timeout=timeout,
            )
        except WindowsHarnessError as exc:
            last_error = exc
            if "Windows refused to activate window handle" not in str(exc):
                raise
            time.sleep(0.2 * (attempt + 1))
    assert last_error is not None
    raise last_error


def send_key(
    source_root: Path,
    peer: WindowsPeer,
    key: str,
    hold_ms: int,
) -> str:
    if peer.game_pid <= 0:
        raise WindowsHarnessError("game PID is unavailable for key input")
    arguments = [
        "--pid",
        str(peer.game_pid),
        "--activate",
        "--activation-delay-ms",
        "150",
        "--post-delay-ms",
        "100",
    ]
    if hold_ms > 0:
        arguments += ["--hold-ms", str(hold_ms)]
    arguments.append(key)
    return run_owned_input(
        source_root / "scripts/send_window_keys.py",
        arguments,
        cwd=source_root,
        timeout=max(10.0, hold_ms / 1000.0 + 5.0),
    )


def click(
    source_root: Path,
    peer: WindowsPeer,
    x: float,
    y: float,
    hold_ms: int = 300,
    *,
    button: str = "left",
) -> str:
    if peer.game_pid <= 0:
        raise WindowsHarnessError("game PID is unavailable for pointer input")
    return run_owned_input(
        source_root / "scripts/click_window.py",
        [
            "--pid",
            str(peer.game_pid),
            "--relative",
            "--x",
            f"{x:.8f}",
            "--y",
            f"{y:.8f}",
            "--hold-ms",
            str(hold_ms),
            "--button",
            button,
            "--global-only",
            "--activate",
            "--activation-delay-ms",
            "150",
            "--post-delay-ms",
            "100",
        ],
        cwd=source_root,
        timeout=15,
    )


def capture_window(
    source_root: Path,
    peer: WindowsPeer,
    output: Path,
) -> dict[str, Any]:
    output.parent.mkdir(parents=True, exist_ok=True)
    started_ns = time.time_ns()
    text = run_windows_python(
        source_root / "scripts/capture_window.py",
        [
            "--pid",
            str(peer.game_pid),
            "--method",
            "window",
            "--output",
            windows_path(output),
        ],
        cwd=source_root,
        timeout=20,
    )
    ended_ns = time.time_ns()
    if not output.is_file() or output.stat().st_size == 0:
        raise WindowsHarnessError(
            f"capture helper returned no image: {output}"
        )
    match = re.search(
        r"(?m)^captureUtcNanoseconds=([0-9]+)$",
        text,
    )
    if match is None:
        raise WindowsHarnessError(
            "capture helper did not report its wall-clock capture instant: "
            f"{text!r}"
        )
    return {
        "path": str(output),
        "startedUtcNanoseconds": started_ns,
        "captureUtcNanoseconds": int(match.group(1)),
        "endedUtcNanoseconds": ended_ns,
        "helper": text,
    }


def exact_owned_processes(
    ps: PowerShell,
    peers: tuple[WindowsPeer, ...],
) -> list[ProcessRecord]:
    roots = [
        windows_path(root).rstrip("\\").casefold() + "\\"
        for peer in peers
        for root in peer.owned_roots
    ]
    records = []
    for process in windows_processes(ps):
        path = process.executable_path.casefold()
        if path and any(path.startswith(root) for root in roots):
            records.append(process)
    return records


def _run_owned_process_action(
    ps: PowerShell,
    peers: tuple[WindowsPeer, ...],
    pid: int,
    script: str,
    *,
    exited_result: str,
) -> str:
    try:
        return ps.run(script, timeout=15)
    except WindowsHarnessError:
        if any(
            process.pid == pid
            for process in exact_owned_processes(ps, peers)
        ):
            raise
        return exited_result


def stop_exact_owned_processes(
    ps: PowerShell,
    peers: tuple[WindowsPeer, ...],
) -> list[dict[str, Any]]:
    expected_paths: dict[int, str] = {}
    for peer in peers:
        if peer.ui_pid:
            expected_paths[peer.ui_pid] = windows_path(peer.ui_executable)
        if peer.game_pid:
            expected_paths[peer.game_pid] = windows_path(peer.game_executable)
    for process in exact_owned_processes(ps, peers):
        expected_paths.setdefault(process.pid, process.executable_path)
    stopped: list[dict[str, Any]] = []
    for pid, expected_path in sorted(
        expected_paths.items(),
        reverse=True,
    ):
        output = _run_owned_process_action(
            ps,
            peers,
            pid,
            f"""
$target=Get-CimInstance Win32_Process -Filter 'ProcessId={pid}'
if($null -eq $target){{
  [Console]::Out.Write('absent')
  return
}}
if(-not [string]::Equals(
    [string]$target.ExecutablePath,
    {ps_quote(expected_path)},
    [System.StringComparison]::OrdinalIgnoreCase)){{
  throw ('refusing PID {pid}; path changed to ' + $target.ExecutablePath)
}}
Stop-Process -Id {pid} -Force
[Console]::Out.Write('stopped')
""",
            exited_result="exited-before-stop",
        )
        stopped.append(
            {
                "pid": pid,
                "expectedPath": expected_path,
                "result": output,
            }
        )
    deadline = time.monotonic() + 15
    remaining: list[ProcessRecord] = []
    while time.monotonic() < deadline:
        remaining = exact_owned_processes(ps, peers)
        if not remaining:
            return stopped
        time.sleep(0.2)
    raise WindowsHarnessError(
        f"owned processes remained after exact cleanup: {remaining}"
    )


def close_exact_owned_processes(
    ps: PowerShell,
    peers: tuple[WindowsPeer, ...],
    *,
    graceful_timeout: float = 20.0,
) -> dict[str, Any]:
    records = exact_owned_processes(ps, peers)
    requested: list[dict[str, Any]] = []
    for record in sorted(records, key=lambda row: row.pid, reverse=True):
        expected_path = record.executable_path
        output = _run_owned_process_action(
            ps,
            peers,
            record.pid,
            f"""
$target=Get-CimInstance Win32_Process -Filter 'ProcessId={record.pid}'
if($null -eq $target){{
  [Console]::Out.Write('absent')
  return
}}
if(-not [string]::Equals(
    [string]$target.ExecutablePath,
    {ps_quote(expected_path)},
    [System.StringComparison]::OrdinalIgnoreCase)){{
  throw ('refusing PID {record.pid}; path changed to ' +
    $target.ExecutablePath)
}}
$process=Get-Process -Id {record.pid}
if($process.MainWindowHandle -eq 0){{
  [Console]::Out.Write('no-main-window')
}}elseif($process.CloseMainWindow()){{
  [Console]::Out.Write('close-requested')
}}else{{
  [Console]::Out.Write('close-declined')
}}
""",
            exited_result="exited-before-close",
        )
        requested.append(
            {
                "pid": record.pid,
                "expectedPath": expected_path,
                "result": output,
            }
        )
    deadline = time.monotonic() + graceful_timeout
    remaining: list[ProcessRecord] = []
    while time.monotonic() < deadline:
        remaining = exact_owned_processes(ps, peers)
        if not remaining:
            return {
                "gracefulRequests": requested,
                "forced": [],
                "allExitedGracefully": True,
            }
        time.sleep(0.2)
    forced = stop_exact_owned_processes(ps, peers)
    return {
        "gracefulRequests": requested,
        "remainingBeforeForce": [
            record.__dict__ for record in remaining
        ],
        "forced": forced,
        "allExitedGracefully": False,
    }
