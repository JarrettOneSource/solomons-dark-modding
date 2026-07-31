from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path
import re
from typing import Any, Literal


SCHEMA_VERSION = 1
LOCAL_WINDOWS = "windows_local"
LINUX_SSH_PROTON = "linux_ssh_proton"
WINDOWS_SSH = "windows_ssh"
PEER_PLATFORMS = frozenset((LOCAL_WINDOWS, LINUX_SSH_PROTON, WINDOWS_SSH))
TOPOLOGIES = frozenset(
    (
        "loopback_windows",
        "loopback_windows_botplay",
        "wan_udp_nfo",
        "steam_windows_proton",
        "steam_windows_ws20",
    )
)
SAFE_TOKEN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,47}$")
PARTICIPANT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._-]{0,31}$")
LOADOUT_ELEMENTS = frozenset(("ether", "fire", "air", "water", "earth"))
LOADOUT_DISCIPLINES = frozenset(("mind", "body", "arcane"))


class ConfigError(ValueError):
    """The harness configuration is unsafe, ambiguous, or incomplete."""


def _require_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ConfigError(f"{label} must be a JSON object")
    return value


def _require_string(
    value: Any,
    label: str,
    *,
    allow_empty: bool = False,
) -> str:
    if not isinstance(value, str):
        raise ConfigError(f"{label} must be a string")
    normalized = value.strip()
    if not allow_empty and not normalized:
        raise ConfigError(f"{label} cannot be empty")
    return normalized


def _require_int(
    value: Any,
    label: str,
    *,
    minimum: int,
    maximum: int,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"{label} must be an integer")
    if value < minimum or value > maximum:
        raise ConfigError(
            f"{label} must be between {minimum} and {maximum}"
        )
    return value


def _require_bool(value: Any, label: str) -> bool:
    if not isinstance(value, bool):
        raise ConfigError(f"{label} must be a boolean")
    return value


def _optional_path(
    value: Any,
    label: str,
    base: Path,
) -> Path | None:
    if value is None:
        return None
    text = _require_string(value, label)
    path = Path(text).expanduser()
    if not path.is_absolute():
        path = base / path
    return path.resolve()


def _required_path(value: Any, label: str, base: Path) -> Path:
    path = _optional_path(value, label, base)
    if path is None:
        raise ConfigError(f"{label} is required")
    return path


@dataclass(frozen=True)
class InputAction:
    kind: Literal["key", "click", "walk_to", "wait_scene"]
    key: str = ""
    hold_ms: int = 0
    x: float = 0.0
    y: float = 0.0
    target_x: float = 0.0
    target_y: float = 0.0
    tolerance: float = 18.0
    scene: str = ""
    timeout_seconds: float = 30.0

    @staticmethod
    def parse(value: Any, label: str) -> "InputAction":
        row = _require_object(value, label)
        kind = _require_string(row.get("kind"), f"{label}.kind")
        if kind not in {"key", "click", "walk_to", "wait_scene"}:
            raise ConfigError(f"{label}.kind is unsupported: {kind!r}")
        timeout = float(row.get("timeoutSeconds", 30.0))
        if not 0.1 <= timeout <= 180.0:
            raise ConfigError(
                f"{label}.timeoutSeconds must be between 0.1 and 180"
            )
        if kind == "key":
            key = _require_string(row.get("key"), f"{label}.key").lower()
            hold_ms = _require_int(
                row.get("holdMilliseconds", 0),
                f"{label}.holdMilliseconds",
                minimum=0,
                maximum=15000,
            )
            return InputAction(
                kind=kind,
                key=key,
                hold_ms=hold_ms,
                timeout_seconds=timeout,
            )
        if kind == "click":
            x = float(row.get("x", -1))
            y = float(row.get("y", -1))
            if not 0.0 <= x <= 1.0 or not 0.0 <= y <= 1.0:
                raise ConfigError(
                    f"{label} click coordinates must be 0..1 fractions"
                )
            return InputAction(
                kind=kind,
                x=x,
                y=y,
                hold_ms=_require_int(
                    row.get("holdMilliseconds", 300),
                    f"{label}.holdMilliseconds",
                    minimum=0,
                    maximum=5000,
                ),
                timeout_seconds=timeout,
            )
        if kind == "walk_to":
            tolerance = float(row.get("tolerance", 18.0))
            if not 1.0 <= tolerance <= 100.0:
                raise ConfigError(
                    f"{label}.tolerance must be between 1 and 100"
                )
            return InputAction(
                kind=kind,
                target_x=float(row.get("x")),
                target_y=float(row.get("y")),
                tolerance=tolerance,
                timeout_seconds=timeout,
            )
        scene = _require_string(row.get("scene"), f"{label}.scene")
        return InputAction(
            kind=kind,
            scene=scene,
            timeout_seconds=timeout,
        )


@dataclass(frozen=True)
class SshConfig:
    executable: str
    target: str
    key_path: str = ""
    stage_root: str = ""
    display: str = ""
    proton_path: str = ""
    xvfb_path: str = ""

    @staticmethod
    def parse(value: Any, label: str) -> "SshConfig":
        row = _require_object(value, label)
        executable = _require_string(
            row.get("executable", "ssh"),
            f"{label}.executable",
        )
        target = _require_string(row.get("target"), f"{label}.target")
        stage_root = _require_string(
            row.get("stageRoot"),
            f"{label}.stageRoot",
        )
        if stage_root in {"/", "~", r"C:\\", "C:"}:
            raise ConfigError(f"{label}.stageRoot is dangerously broad")
        return SshConfig(
            executable=executable,
            target=target,
            key_path=_require_string(
                row.get("keyPath", ""),
                f"{label}.keyPath",
                allow_empty=True,
            ),
            stage_root=stage_root,
            display=_require_string(
                row.get("display", ""),
                f"{label}.display",
                allow_empty=True,
            ),
            proton_path=_require_string(
                row.get("protonPath", ""),
                f"{label}.protonPath",
                allow_empty=True,
            ),
            xvfb_path=_require_string(
                row.get("xvfbPath", ""),
                f"{label}.xvfbPath",
                allow_empty=True,
            ),
        )


@dataclass(frozen=True)
class PeerConfig:
    role: Literal["host", "client"]
    platform: str
    launcher_scope: str
    instance: str
    player_name: str
    pipe_name: str
    participant_id: int
    loadout_element: str
    loadout_discipline: str
    local_port: int
    remote_host: str
    remote_port: int
    match_start_actions: tuple[InputAction, ...] = ()
    ssh: SshConfig | None = None

    @staticmethod
    def parse(
        value: Any,
        label: str,
        *,
        role: Literal["host", "client"],
    ) -> "PeerConfig":
        row = _require_object(value, label)
        platform = _require_string(
            row.get("platform"),
            f"{label}.platform",
        )
        if platform not in PEER_PLATFORMS:
            raise ConfigError(
                f"{label}.platform is unsupported: {platform!r}"
            )
        launcher_scope = _require_string(
            row.get("launcherScope"),
            f"{label}.launcherScope",
        ).lower()
        instance = _require_string(
            row.get("instance"),
            f"{label}.instance",
        ).lower()
        for value_name, token in (
            ("launcherScope", launcher_scope),
            ("instance", instance),
        ):
            if not SAFE_TOKEN.fullmatch(token):
                raise ConfigError(
                    f"{label}.{value_name} must be filename-safe"
                )
        player_name = _require_string(
            row.get("playerName"),
            f"{label}.playerName",
        )
        if not PARTICIPANT_NAME.fullmatch(player_name):
            raise ConfigError(
                f"{label}.playerName must be a safe display name"
            )
        pipe_name = _require_string(
            row.get("pipeName"),
            f"{label}.pipeName",
        )
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,100}", pipe_name):
            raise ConfigError(f"{label}.pipeName is not safe")
        participant_text = row.get("participantId")
        try:
            participant_id = int(str(participant_text), 0)
        except (TypeError, ValueError) as exc:
            raise ConfigError(
                f"{label}.participantId must be an integer or 0x literal"
            ) from exc
        if not 1 <= participant_id <= 0xFFFFFFFFFFFFFFFF:
            raise ConfigError(
                f"{label}.participantId must fit an unsigned 64-bit integer"
            )
        loadout_element = _require_string(
            row.get("loadoutElement", "fire"),
            f"{label}.loadoutElement",
        ).lower()
        if loadout_element not in LOADOUT_ELEMENTS:
            raise ConfigError(
                f"{label}.loadoutElement is unsupported: "
                f"{loadout_element!r}"
            )
        loadout_discipline = _require_string(
            row.get("loadoutDiscipline", "body"),
            f"{label}.loadoutDiscipline",
        ).lower()
        if loadout_discipline not in LOADOUT_DISCIPLINES:
            raise ConfigError(
                f"{label}.loadoutDiscipline is unsupported: "
                f"{loadout_discipline!r}"
            )
        actions = tuple(
            InputAction.parse(action, f"{label}.matchStartActions[{index}]")
            for index, action in enumerate(
                row.get("matchStartActions", [])
            )
        )
        ssh = (
            SshConfig.parse(row.get("ssh"), f"{label}.ssh")
            if platform != LOCAL_WINDOWS
            else None
        )
        return PeerConfig(
            role=role,
            platform=platform,
            launcher_scope=launcher_scope,
            instance=instance,
            player_name=player_name,
            pipe_name=pipe_name,
            participant_id=participant_id,
            loadout_element=loadout_element,
            loadout_discipline=loadout_discipline,
            local_port=_require_int(
                row.get("localPort", 0),
                f"{label}.localPort",
                minimum=0,
                maximum=65535,
            ),
            remote_host=_require_string(
                row.get("remoteHost", ""),
                f"{label}.remoteHost",
                allow_empty=True,
            ),
            remote_port=_require_int(
                row.get("remotePort", 0),
                f"{label}.remotePort",
                minimum=0,
                maximum=65535,
            ),
            match_start_actions=actions,
            ssh=ssh,
        )


@dataclass(frozen=True)
class HarnessConfig:
    source_path: Path
    run_name: str
    topology: str
    source_root: Path
    package_root: Path
    game_directory: Path
    evidence_root: Path
    proton_archive: Path | None
    directory_url: str
    privacy: Literal["friends", "public"]
    expected_source_sha: str
    host: PeerConfig
    client: PeerConfig
    solomon_interactor: Literal["host", "client"] = "host"
    verify_through_wave: int = 1
    require_water_contact_observation: bool = False
    expected_water_contact_damage: float = 0.025
    wave_boundary_max_displacement: float = 64.0
    timeout_seconds: float = 120.0
    sampling_seconds: float = 0.25
    bot_play_for_me: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)

    @staticmethod
    def load(path: Path) -> "HarnessConfig":
        source_path = path.expanduser().resolve()
        try:
            raw = json.loads(source_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ConfigError(
                f"could not read harness config {source_path}: {exc}"
            ) from exc
        row = _require_object(raw, "config")
        schema = _require_int(
            row.get("schemaVersion"),
            "schemaVersion",
            minimum=SCHEMA_VERSION,
            maximum=SCHEMA_VERSION,
        )
        if schema != SCHEMA_VERSION:
            raise ConfigError(f"unsupported schemaVersion: {schema}")
        base = source_path.parent
        run_name = _require_string(row.get("runName"), "runName").lower()
        if not SAFE_TOKEN.fullmatch(run_name):
            raise ConfigError("runName must be filename-safe")
        topology = _require_string(row.get("topology"), "topology")
        if topology not in TOPOLOGIES:
            raise ConfigError(f"unsupported topology: {topology!r}")
        privacy = _require_string(
            row.get("privacy", "friends"),
            "privacy",
        )
        if privacy not in {"friends", "public"}:
            raise ConfigError("privacy must be friends or public")
        directory_url = _require_string(
            row.get("directoryUrl", "https://solomondarker.com"),
            "directoryUrl",
        )
        if not (
            directory_url.startswith("https://")
            or directory_url.startswith("http://127.0.0.1")
            or directory_url.startswith("http://localhost")
        ):
            raise ConfigError(
                "directoryUrl must use HTTPS or an explicit loopback HTTP URL"
            )
        solomon_interactor = _require_string(
            row.get("solomonInteractor", "host"),
            "solomonInteractor",
        ).lower()
        if solomon_interactor not in {"host", "client"}:
            raise ConfigError(
                "solomonInteractor must be host or client"
            )
        config = HarnessConfig(
            source_path=source_path,
            run_name=run_name,
            topology=topology,
            source_root=_required_path(
                row.get("sourceRoot"),
                "sourceRoot",
                base,
            ),
            package_root=_required_path(
                row.get("packageRoot"),
                "packageRoot",
                base,
            ),
            game_directory=_required_path(
                row.get("gameDirectory"),
                "gameDirectory",
                base,
            ),
            evidence_root=_required_path(
                row.get("evidenceRoot"),
                "evidenceRoot",
                base,
            ),
            proton_archive=_optional_path(
                row.get("protonArchive"),
                "protonArchive",
                base,
            ),
            directory_url=directory_url.rstrip("/"),
            privacy=privacy,
            expected_source_sha=_require_string(
                row.get("expectedSourceSha"),
                "expectedSourceSha",
            ).lower(),
            host=PeerConfig.parse(row.get("host"), "host", role="host"),
            client=PeerConfig.parse(
                row.get("client"),
                "client",
                role="client",
            ),
            solomon_interactor=solomon_interactor,
            verify_through_wave=_require_int(
                row.get("verifyThroughWave", 1),
                "verifyThroughWave",
                minimum=1,
                maximum=10,
            ),
            require_water_contact_observation=_require_bool(
                row.get("requireWaterContactObservation", False),
                "requireWaterContactObservation",
            ),
            expected_water_contact_damage=float(
                row.get("expectedWaterContactDamage", 0.025)
            ),
            wave_boundary_max_displacement=float(
                row.get("waveBoundaryMaxDisplacement", 64.0)
            ),
            timeout_seconds=float(row.get("timeoutSeconds", 120.0)),
            sampling_seconds=float(row.get("samplingSeconds", 0.25)),
            bot_play_for_me=_require_bool(
                row.get("botPlayForMe", False),
                "botPlayForMe",
            ),
            metadata=_require_object(row.get("metadata", {}), "metadata"),
        )
        config.validate()
        return config

    def validate(self) -> None:
        if not re.fullmatch(r"[0-9a-f]{40}", self.expected_source_sha):
            raise ConfigError("expectedSourceSha must be a full Git SHA")
        if not 30.0 <= self.timeout_seconds <= 600.0:
            raise ConfigError(
                "timeoutSeconds must be between 30 and 600"
            )
        if not 0.05 <= self.sampling_seconds <= 2.0:
            raise ConfigError(
                "samplingSeconds must be between 0.05 and 2.0"
            )
        if not 0.0 < self.expected_water_contact_damage <= 10.0:
            raise ConfigError(
                "expectedWaterContactDamage must be greater than zero and "
                "at most 10"
            )
        if (
            self.require_water_contact_observation
            and self.client.loadout_element != "water"
        ):
            raise ConfigError(
                "requireWaterContactObservation requires client Water"
            )
        if not 1.0 <= self.wave_boundary_max_displacement <= 500.0:
            raise ConfigError(
                "waveBoundaryMaxDisplacement must be between 1 and 500"
            )
        for path, label in (
            (self.source_root, "sourceRoot"),
            (self.package_root, "packageRoot"),
            (self.game_directory, "gameDirectory"),
        ):
            if not path.is_dir():
                raise ConfigError(f"{label} is not a directory: {path}")
        if not (self.source_root / ".git").exists():
            raise ConfigError(
                f"sourceRoot is not the requested worktree: {self.source_root}"
            )
        if not (
            self.package_root / "SolomonDarkMultiplayerBeta.exe"
        ).is_file():
            raise ConfigError(
                "packageRoot is missing SolomonDarkMultiplayerBeta.exe"
            )
        if not (
            self.package_root / "launcher/SolomonDarkModLauncher.exe"
        ).is_file():
            raise ConfigError(
                "packageRoot is missing the packaged CLI launcher"
            )
        if not (self.game_directory / "SolomonDark.exe").is_file():
            raise ConfigError(
                "gameDirectory is missing SolomonDark.exe"
            )
        if self.evidence_root.exists():
            raise ConfigError(
                "evidenceRoot must be new; the harness never overwrites an "
                f"earlier run: {self.evidence_root}"
            )
        if (
            self.proton_archive is not None
            and not self.proton_archive.is_file()
        ):
            raise ConfigError(
                "protonArchive is not a file: "
                f"{self.proton_archive}"
            )
        if self.host.participant_id == self.client.participant_id:
            raise ConfigError("host and client participant IDs must differ")
        if self.host.pipe_name == self.client.pipe_name:
            raise ConfigError("host and client pipe names must differ")
        if self.host.launcher_scope == self.client.launcher_scope:
            raise ConfigError("launcher scopes must differ")
        if self.topology in {
            "loopback_windows",
            "loopback_windows_botplay",
        }:
            if (
                self.host.platform != LOCAL_WINDOWS
                or self.client.platform != LOCAL_WINDOWS
            ):
                raise ConfigError(
                    f"{self.topology} requires two windows_local peers"
                )
            ports = {
                self.host.local_port,
                self.host.remote_port,
                self.client.local_port,
                self.client.remote_port,
            }
            if (
                self.topology == "loopback_windows"
                and ports != {50911, 50912}
            ):
                raise ConfigError(
                    "loopback_windows is reserved to ports 50911/50912"
                )
            if (
                self.topology == "loopback_windows_botplay"
                and (
                    len(ports) != 2
                    or min(ports) < 51400
                    or self.host.local_port != self.client.remote_port
                    or self.client.local_port != self.host.remote_port
                )
            ):
                raise ConfigError(
                    "loopback_windows_botplay requires a reciprocal distinct "
                    "port pair at or above 51400"
                )
            if (
                self.host.remote_host not in {"127.0.0.1", "localhost"}
                or self.client.remote_host
                not in {"127.0.0.1", "localhost"}
            ):
                raise ConfigError(
                    "loopback_windows peers must target loopback"
                )
        if self.topology == "loopback_windows_botplay":
            if not self.bot_play_for_me:
                raise ConfigError(
                    "loopback_windows_botplay requires botPlayForMe=true"
                )
            if not self.run_name.startswith("bply"):
                raise ConfigError(
                    "bot-play runName must use the bply prefix"
                )
            for peer in (self.host, self.client):
                if (
                    not peer.launcher_scope.startswith("bply")
                    or not peer.instance.startswith("bply")
                    or not peer.pipe_name.casefold().startswith("bply")
                ):
                    raise ConfigError(
                        "bot-play launcher scopes, instances, and pipe names "
                        "must use the bply prefix"
                    )
            if not (self.source_root / "mods/bot-brain/manifest.json").is_file():
                raise ConfigError(
                    "bot-play source is missing mods/bot-brain"
                )
            if self.verify_through_wave < 4:
                raise ConfigError(
                    "bot-play acceptance requires verifyThroughWave >= 4"
                )
        elif self.bot_play_for_me:
            raise ConfigError(
                "botPlayForMe is confined to loopback_windows_botplay"
            )
        if self.topology == "wan_udp_nfo":
            if self.host.platform != LOCAL_WINDOWS:
                raise ConfigError(
                    "wan_udp_nfo requires a local Windows host"
                )
            if self.client.platform != LINUX_SSH_PROTON:
                raise ConfigError(
                    "wan_udp_nfo requires a Linux SSH Proton client"
                )
            if self.client.ssh is None:
                raise ConfigError(
                    "wan_udp_nfo client is missing SSH configuration"
                )
            if (
                self.client.ssh.stage_root
                != "/root/sd-fieldbreak25-20260730"
            ):
                raise ConfigError(
                    "wan_udp_nfo is confined to "
                    "/root/sd-fieldbreak25-20260730"
                )
            if self.proton_archive is None:
                raise ConfigError(
                    "wan_udp_nfo requires protonArchive so the harness "
                    "can stage its own Proton runtime"
                )
            ports = {
                self.host.local_port,
                self.host.remote_port,
                self.client.local_port,
                self.client.remote_port,
            }
            if ports != {50911, 50912}:
                raise ConfigError(
                    "wan_udp_nfo is reserved to ports 50911/50912"
                )
            if (
                self.host.local_port != 50911
                or self.host.remote_port != 50912
                or self.client.local_port != 50912
                or self.client.remote_port != 50911
            ):
                raise ConfigError(
                    "wan_udp_nfo requires host 50911 and client B 50912"
                )
        if self.topology == "steam_windows_ws20":
            if self.host.platform != LOCAL_WINDOWS:
                raise ConfigError(
                    "steam_windows_ws20 requires a local Windows host"
                )
            if self.client.platform != WINDOWS_SSH:
                raise ConfigError(
                    "steam_windows_ws20 requires a Windows SSH client"
                )
            if self.client.ssh is None:
                raise ConfigError(
                    "steam_windows_ws20 client is missing SSH configuration"
                )
            normalized_stage = self.client.ssh.stage_root.replace("/", "\\")
            if not (
                normalized_stage.casefold()
                == r"%userprofile%\sd-netrepro-stage".casefold()
                or re.fullmatch(
                    r"[A-Za-z]:\\Users\\[^\\]+\\sd-netrepro-stage",
                    normalized_stage,
                    flags=re.IGNORECASE,
                )
            ):
                raise ConfigError(
                    "steam_windows_ws20 is confined to "
                    r"%USERPROFILE%\sd-netrepro-stage"
                )
            if not self.client.ssh.key_path:
                raise ConfigError(
                    "steam_windows_ws20 requires an SSH key path"
                )
            if self.privacy != "friends":
                raise ConfigError(
                    "steam_windows_ws20 requires a friends-only lobby"
                )
        if (
            self.topology.startswith("steam_")
            and any(
                peer.local_port != 0 or peer.remote_port != 0
                for peer in (self.host, self.client)
            )
        ):
            raise ConfigError(
                "Steam topologies must not claim local UDP ports"
            )
        if self.client.match_start_actions:
            raise ConfigError(
                "only the host may own matchStartActions"
            )

    def redacted(self) -> dict[str, Any]:
        def peer_value(peer: PeerConfig) -> dict[str, Any]:
            return {
                "role": peer.role,
                "platform": peer.platform,
                "launcherScope": peer.launcher_scope,
                "instance": peer.instance,
                "playerName": peer.player_name,
                "pipeName": peer.pipe_name,
                "participantId": str(peer.participant_id),
                "loadoutElement": peer.loadout_element,
                "loadoutDiscipline": peer.loadout_discipline,
                "localPort": peer.local_port,
                "remoteHost": peer.remote_host,
                "remotePort": peer.remote_port,
                "matchStartActions": [
                    action.__dict__ for action in peer.match_start_actions
                ],
                "sshConfigured": peer.ssh is not None,
                "sshStageRoot": (
                    r"%USERPROFILE%\sd-netrepro-stage"
                    if peer.platform == WINDOWS_SSH and peer.ssh
                    else (peer.ssh.stage_root if peer.ssh else "")
                ),
            }

        return {
            "schemaVersion": SCHEMA_VERSION,
            "runName": self.run_name,
            "topology": self.topology,
            "sourceRoot": str(self.source_root),
            "packageRoot": str(self.package_root),
            "gameDirectory": str(self.game_directory),
            "evidenceRoot": str(self.evidence_root),
            "protonArchive": (
                str(self.proton_archive)
                if self.proton_archive is not None
                else ""
            ),
            "directoryUrl": self.directory_url,
            "privacy": self.privacy,
            "expectedSourceSha": self.expected_source_sha,
            "solomonInteractor": self.solomon_interactor,
            "verifyThroughWave": self.verify_through_wave,
            "requireWaterContactObservation": (
                self.require_water_contact_observation
            ),
            "expectedWaterContactDamage": (
                self.expected_water_contact_damage
            ),
            "waveBoundaryMaxDisplacement": (
                self.wave_boundary_max_displacement
            ),
            "timeoutSeconds": self.timeout_seconds,
            "samplingSeconds": self.sampling_seconds,
            "botPlayForMe": self.bot_play_for_me,
            "host": peer_value(self.host),
            "client": peer_value(self.client),
            "metadata": self.metadata,
        }
