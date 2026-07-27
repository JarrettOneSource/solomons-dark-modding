#!/usr/bin/env python3
"""Verify real single-player and multiplayer loading-screen stages and pixels."""

from __future__ import annotations

import argparse
import contextlib
import json
import math
import os
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from PIL import Image, ImageChops, ImageStat

import multiplayer_frame_capture as frame_capture
import verify_local_multiplayer_sync as local_sync


ROOT = Path(__file__).resolve().parents[1]
GAME_DIRECTORY = Path(
    "/mnt/c/Users/User/Documents/GitHub/SB Modding/"
    "Solomon Dark/SolomonDarkAbandonware"
)
EVIDENCE_ROOT = Path(
    "/mnt/d/codex-evidence/fieldfix-20260727"
)
OUTPUT_PATH = EVIDENCE_ROOT / "loading-screen-live.json"
BACKGROUND = ROOT / "assets/loading/Wizards_dire_BG.png"
FLAT_BONEYARD = (
    ROOT / "tests/fixtures/boneyards/flat_multiplayer_test.boneyard"
)

INSTANCE_PREFIX = "ffix"
HOST_PORT = 49711
CLIENT_PORT = 49712
HOST_PIPE = "SolomonDarkModLoader_LuaExec_ffix-host"
CLIENT_PIPE = "SolomonDarkModLoader_LuaExec_ffix-client"
ACCEPTANCE_MOD_ID = "sample.lua.ui_sandbox_lab"
CAPTURE_ENVIRONMENT = "SDMOD_LOADING_SCREEN_CAPTURE_DIRECTORY"

STAGE_PROGRESS = {
    "connecting_transport": 0.44,
    "creating_lobby": 0.48,
    "joining_lobby": 0.48,
    "authenticating_session": 0.52,
    "establishing_route": 0.56,
    "synchronizing_host_settings": 0.60,
    "receiving_host_checkpoint": 0.66,
    "preparing_host": 0.66,
    "receiving_run_plan": 0.70,
    "preparing_boneyard": 0.73,
    "generating_boneyard": 0.77,
    "serializing_boneyard": 0.80,
    "reading_boneyard": 0.83,
    "materializing_world": 0.87,
    "receiving_world_checkpoint": 0.90,
    "receiving_wave_checkpoint": 0.91,
    "materializing_participants": 0.92,
    "waiting_for_participants": 0.95,
    "confirming_participants": 0.98,
    "gameplay_ready": 1.00,
}
CONNECTION_STAGES = {
    "connecting_transport",
    "creating_lobby",
    "joining_lobby",
    "authenticating_session",
    "establishing_route",
    "synchronizing_host_settings",
    "receiving_host_checkpoint",
    "preparing_host",
    "materializing_participants",
}
NATIVE_STAGES = (
    "preparing_boneyard",
    "generating_boneyard",
    "serializing_boneyard",
    "reading_boneyard",
    "materializing_world",
    "materializing_participants",
)

TIMESTAMP_PATTERN = r"(?P<timestamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3})"
START_PATTERN = re.compile(
    rf"^\[{TIMESTAMP_PATTERN}\] Loading screen started\. "
    r"sequence=(?P<sequence>\d+) flow=(?P<flow>[a-z_]+)$",
    re.MULTILINE,
)
STAGE_PATTERN = re.compile(
    rf"^\[{TIMESTAMP_PATTERN}\] Loading screen stage\. "
    r"sequence=(?P<sequence>\d+) stage=(?P<stage>[a-z_]+) "
    r"progress=(?P<progress>[0-9.]+)$",
    re.MULTILINE,
)
RENDER_PATTERN = re.compile(
    rf"^\[{TIMESTAMP_PATTERN}\] Loading screen rendered\. "
    r"sequence=(?P<sequence>\d+) stage=(?P<stage>[a-z_]+) "
    r"progress=(?P<progress>[0-9.]+) "
    r"viewport=(?P<width>\d+)x(?P<height>\d+) "
    r"crop=(?P<crop>[0-9.,-]+)$",
    re.MULTILINE,
)
COMPLETE_PATTERN = re.compile(
    rf"^\[{TIMESTAMP_PATTERN}\] Loading screen completed\. "
    r"sequence=(?P<sequence>\d+) elapsed_ms=(?P<elapsed>\d+)$",
    re.MULTILINE,
)


class LoadingScreenFailure(RuntimeError):
    pass


def _timestamp(value: str) -> datetime:
    return datetime.strptime(
        value,
        "%Y-%m-%d %H:%M:%S.%f",
    ).replace(tzinfo=timezone.utc)


def _windows_path_to_wsl(value: object) -> Path:
    if not isinstance(value, str) or not value:
        raise LoadingScreenFailure(
            f"launcher path is missing: {value!r}"
        )
    completed = subprocess.run(
        ["wslpath", "-u", value],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=5.0,
        check=False,
    )
    path = completed.stdout.strip()
    if completed.returncode != 0 or not path:
        raise LoadingScreenFailure(
            f"could not convert launcher path {value!r}: "
            f"{completed.stdout}"
        )
    return Path(path)


@contextlib.contextmanager
def _export_capture_directory(
    directory: Path,
) -> Iterator[None]:
    old_capture = os.environ.get(CAPTURE_ENVIRONMENT)
    old_wslenv = os.environ.get("WSLENV")
    os.environ[CAPTURE_ENVIRONMENT] = (
        local_sync.path_for_powershell(directory)
    )
    entries = [
        entry
        for entry in os.environ.get("WSLENV", "").split(":")
        if entry
    ]
    exported = {
        entry.split("/", 1)[0]
        for entry in entries
    }
    if CAPTURE_ENVIRONMENT not in exported:
        entries.append(CAPTURE_ENVIRONMENT)
    os.environ["WSLENV"] = ":".join(entries)
    try:
        yield
    finally:
        if old_capture is None:
            os.environ.pop(CAPTURE_ENVIRONMENT, None)
        else:
            os.environ[CAPTURE_ENVIRONMENT] = old_capture
        if old_wslenv is None:
            os.environ.pop("WSLENV", None)
        else:
            os.environ["WSLENV"] = old_wslenv


def _wait_for_log(
    path: Path,
    predicate,
    *,
    timeout: float,
    label: str,
) -> str:
    deadline = time.monotonic() + timeout
    last = ""
    while time.monotonic() < deadline:
        if path.is_file():
            last = path.read_text(
                encoding="utf-8",
                errors="replace",
            )
            if predicate(last):
                return last
        time.sleep(0.05)
    raise LoadingScreenFailure(
        f"{label} timed out; log={path} tail={last[-2000:]!r}"
    )


def _completed_after_stage(text: str, stage: str) -> bool:
    stage_position = text.rfind(f"stage={stage}")
    return (
        stage_position >= 0
        and text.find(
            "Loading screen completed.",
            stage_position,
        ) >= 0
    )


def _start_testrun() -> None:
    last_error = ""
    for _ in range(80):
        try:
            local_sync.start_testrun(HOST_PIPE)
            return
        except (
            local_sync.VerifyFailure,
            subprocess.TimeoutExpired,
        ) as exc:
            last_error = str(exc)
            time.sleep(0.25)
    raise LoadingScreenFailure(
        f"host could not enter the test run: {last_error}"
    )


def _validate_launch(
    launch: dict[str, object],
    *,
    multiplayer_enabled: bool,
) -> None:
    if launch.get("audioDisabled") is not True:
        raise LoadingScreenFailure(
            f"game audio was not disabled: {launch}"
        )
    if (
        int(launch.get("hostPort", 0)) != HOST_PORT
        or int(launch.get("clientPort", 0)) != CLIENT_PORT
    ):
        raise LoadingScreenFailure(
            f"launcher used unexpected ports: {launch}"
        )
    if launch.get("instancePrefix") != INSTANCE_PREFIX:
        raise LoadingScreenFailure(
            f"launcher used unexpected instance prefix: {launch}"
        )
    if (
        launch.get("multiplayerTransportEnabled")
        is not multiplayer_enabled
    ):
        raise LoadingScreenFailure(
            "launcher transport mode did not match the requested "
            f"flow: {launch}"
        )

    expected_stage = str(
        (ROOT / "runtime/instances").resolve()
    ).lower()
    for role in ("host", "client"):
        executable = _windows_path_to_wsl(
            launch.get(f"{role}ExecutablePath")
        ).resolve()
        if expected_stage not in str(executable).lower():
            raise LoadingScreenFailure(
                f"{role} executable is outside the isolated runtime: "
                f"{executable}"
            )


def _parse_completed_sequence(
    text: str,
    *,
    expected_flow: str,
    required_stages: tuple[str, ...],
    completion_index: int = -1,
) -> dict[str, Any]:
    completions = list(COMPLETE_PATTERN.finditer(text))
    if not completions:
        raise LoadingScreenFailure(
            f"loading flow {expected_flow} never completed"
        )
    try:
        completion = completions[completion_index]
    except IndexError as exc:
        raise LoadingScreenFailure(
            f"loading flow {expected_flow} has no completed sequence "
            f"at index {completion_index}"
        ) from exc
    sequence = int(completion.group("sequence"))

    starts = [
        match
        for match in START_PATTERN.finditer(text)
        if int(match.group("sequence")) == sequence
    ]
    if len(starts) != 1:
        raise LoadingScreenFailure(
            f"loading sequence {sequence} has {len(starts)} starts"
        )
    start = starts[0]
    if start.group("flow") != expected_flow:
        raise LoadingScreenFailure(
            f"loading sequence {sequence} flow was "
            f"{start.group('flow')}, expected {expected_flow}"
        )

    stages = [
        {
            "timestamp": match.group("timestamp"),
            "stage": match.group("stage"),
            "progress": float(match.group("progress")),
        }
        for match in STAGE_PATTERN.finditer(text)
        if int(match.group("sequence")) == sequence
    ]
    progress = [event["progress"] for event in stages]
    if not progress or progress != sorted(progress):
        raise LoadingScreenFailure(
            f"loading sequence {sequence} was not monotonic: {stages}"
        )
    for event in stages:
        expected = STAGE_PROGRESS.get(event["stage"])
        if expected is None or not math.isclose(
            event["progress"],
            expected,
            abs_tol=0.0001,
        ):
            raise LoadingScreenFailure(
                f"loading sequence {sequence} has an unmapped "
                f"stage event: {event}"
            )
    observed = {event["stage"] for event in stages}
    missing = [
        stage for stage in required_stages
        if stage not in observed
    ]
    if missing:
        raise LoadingScreenFailure(
            f"loading sequence {sequence} missed real stages: {missing}"
        )

    renders = [
        {
            "timestamp": match.group("timestamp"),
            "stage": match.group("stage"),
            "progress": float(match.group("progress")),
            "viewport": {
                "width": int(match.group("width")),
                "height": int(match.group("height")),
            },
            "crop": [
                float(value)
                for value in match.group("crop").split(",")
            ],
        }
        for match in RENDER_PATTERN.finditer(text)
        if int(match.group("sequence")) == sequence
    ]
    if not renders:
        raise LoadingScreenFailure(
            f"loading sequence {sequence} was never rendered"
        )
    first_render_delay_ms = int(
        (
            _timestamp(renders[0]["timestamp"]) -
            _timestamp(start.group("timestamp"))
        ).total_seconds() *
        1000
    )
    if first_render_delay_ms < 150:
        raise LoadingScreenFailure(
            f"loading sequence {sequence} flashed before the "
            f"150 ms gate: {first_render_delay_ms} ms"
        )
    if any(render["crop"] != [0.0, 0.0, 1.0, 1.0] for render in renders):
        raise LoadingScreenFailure(
            "16:9 evidence unexpectedly used a non-full source crop: "
            f"{renders}"
        )

    elapsed_ms = int(completion.group("elapsed"))
    if elapsed_ms < first_render_delay_ms:
        raise LoadingScreenFailure(
            f"loading completion preceded its first rendered frame: "
            f"{elapsed_ms} < {first_render_delay_ms}"
        )
    return {
        "sequence": sequence,
        "flow": expected_flow,
        "started": start.group("timestamp"),
        "stages": stages,
        "renders": renders,
        "firstRenderDelayMs": first_render_delay_ms,
        "elapsedMs": elapsed_ms,
        "completed": completion.group("timestamp"),
    }


def _completion_index_containing_stage(
    text: str,
    stage: str,
    *,
    last: bool = False,
) -> int:
    completions = list(COMPLETE_PATTERN.finditer(text))
    matching_indices: list[int] = []
    for index, completion in enumerate(completions):
        sequence = int(completion.group("sequence"))
        if any(
            match.group("stage") == stage
            and int(match.group("sequence")) == sequence
            for match in STAGE_PATTERN.finditer(text)
        ):
            matching_indices.append(index)
    if not matching_indices:
        raise LoadingScreenFailure(
            f"no completed loading sequence contains {stage}"
        )
    return matching_indices[-1 if last else 0]


def _validate_connection_sequence(
    timeline: dict[str, Any],
    *,
    minimum_rendered_milestones: int = 2,
) -> tuple[str, ...]:
    stages = [
        event["stage"]
        for event in timeline["stages"]
        if event["stage"] in CONNECTION_STAGES
    ]
    distinct_progress = {
        STAGE_PROGRESS[stage]
        for stage in stages
    }
    if len(distinct_progress) < 2:
        raise LoadingScreenFailure(
            "connecting-to-match did not expose two real progress "
            f"milestones: {stages}"
        )

    rendered_stages = [
        event["stage"]
        for event in timeline["renders"]
        if event["stage"] in CONNECTION_STAGES
    ]
    distinct_rendered_progress = {
        STAGE_PROGRESS[stage]
        for stage in rendered_stages
    }
    if (
        len(distinct_rendered_progress) <
        minimum_rendered_milestones
    ):
        raise LoadingScreenFailure(
            "connecting-to-match did not render the required real "
            f"milestones ({minimum_rendered_milestones}): "
            f"{rendered_stages}"
        )
    return tuple(dict.fromkeys(rendered_stages))


def _measure_screenshot(
    bmp_path: Path,
) -> dict[str, Any]:
    png_path = bmp_path.with_suffix(".png")
    quality = frame_capture.convert_and_validate_backbuffer(
        bmp_path,
        png_path,
    )
    stage = next(
        (
            candidate
            for candidate in STAGE_PROGRESS
            if bmp_path.stem.endswith("-" + candidate)
        ),
        "",
    )
    if not stage:
        raise LoadingScreenFailure(
            f"capture filename has no real loading stage: {bmp_path}"
        )

    with Image.open(png_path) as captured_file:
        captured = captured_file.convert("RGB")
        width, height = captured.size
        with Image.open(BACKGROUND) as background_file:
            background = background_file.convert("RGB").resize(
                (width, height),
                Image.Resampling.BILINEAR,
            )
        comparison_height = int(height * 0.72)
        difference = ImageChops.difference(
            captured.crop((0, 0, width, comparison_height)),
            background.crop((0, 0, width, comparison_height)),
        )
        mean_background_error = sum(
            ImageStat.Stat(difference).mean
        ) / 3.0

        bar_left = int(round(width * 0.20))
        bar_right = int(round(width * 0.80))
        sample_y = min(
            height - 1,
            int(round(height * 0.925)) + 4,
        )
        row = [
            captured.getpixel((x, sample_y))
            for x in range(bar_left, bar_right)
        ]
        gold_pixels = sum(
            1
            for red, green, blue in row
            if (
                red >= 175
                and 110 <= green <= 205
                and blue <= 135
                and red > green
            )
        )
        measured_progress = gold_pixels / max(len(row), 1)

    expected_progress = STAGE_PROGRESS[stage]
    if mean_background_error > 8.0:
        raise LoadingScreenFailure(
            f"capture does not contain the canonical loading art: "
            f"path={png_path} mean_error={mean_background_error:.3f}"
        )
    if abs(measured_progress - expected_progress) > 0.025:
        raise LoadingScreenFailure(
            f"capture progress bar does not match its real stage: "
            f"path={png_path} stage={stage} "
            f"expected={expected_progress:.3f} "
            f"measured={measured_progress:.3f}"
        )
    return {
        "stage": stage,
        "progress": expected_progress,
        "path": str(png_path),
        "sourceBmp": str(bmp_path),
        "quality": quality,
        "canonicalBackgroundMeanError": mean_background_error,
        "measuredBarProgress": measured_progress,
    }


def _capture_inventory(
    directory: Path,
    *,
    required_role: str,
    required_stages: tuple[str, ...],
) -> list[dict[str, Any]]:
    bmps = sorted(directory.glob("*.bmp"))
    if not bmps:
        raise LoadingScreenFailure(
            f"loading renderer produced no evidence frames in {directory}"
        )
    captures = [
        _measure_screenshot(path)
        for path in bmps
    ]
    role_captures = [
        capture
        for capture in captures
        if required_role in Path(capture["sourceBmp"]).name
    ]
    stages = {capture["stage"] for capture in role_captures}
    missing = [
        stage for stage in required_stages
        if stage not in stages
    ]
    if missing:
        raise LoadingScreenFailure(
            f"{required_role} evidence missed stages {missing}; "
            f"captures={role_captures}"
        )
    return captures


def _nonempty_crash_artifacts(
    launch: dict[str, object],
) -> list[dict[str, Any]]:
    artifacts: list[dict[str, Any]] = []
    for role in ("host", "client"):
        executable = _windows_path_to_wsl(
            launch.get(f"{role}ExecutablePath")
        )
        logs = executable.parent / ".sdmod/logs"
        for pattern in ("*crash*", "*.dmp"):
            for path in logs.glob(pattern):
                if path.is_file() and path.stat().st_size > 0:
                    artifacts.append(
                        {
                            "role": role,
                            "path": str(path),
                            "bytes": path.stat().st_size,
                        }
                    )
    return artifacts


def _run_flow(
    *,
    flow_name: str,
    multiplayer_enabled: bool,
    capture_directory: Path,
    game_directory: Path,
) -> dict[str, Any]:
    launch: dict[str, object] = {}
    result: dict[str, Any] = {
        "flow": flow_name,
        "multiplayerEnabled": multiplayer_enabled,
        "captureDirectory": str(capture_directory),
    }
    failure: BaseException | None = None
    try:
        with _export_capture_directory(capture_directory):
            launch = local_sync.launch_pair(
                instance_prefix=INSTANCE_PREFIX,
                host_port=HOST_PORT,
                client_port=CLIENT_PORT,
                temporary_host_profile=True,
                kill_existing=False,
                god_mode=True,
                exact_mod_id=ACCEPTANCE_MOD_ID,
                test_survival_boneyard_override=FLAT_BONEYARD,
                test_blank_boneyard=True,
                use_sandbox_preset_flow=not multiplayer_enabled,
                quick_start=multiplayer_enabled,
                tile_windows=False,
                game_directory=game_directory,
                enable_audio=False,
                disable_multiplayer_transport=(
                    not multiplayer_enabled
                ),
            )
        result["launch"] = launch
        _validate_launch(
            launch,
            multiplayer_enabled=multiplayer_enabled,
        )
        host_log = _windows_path_to_wsl(launch.get("hostLog"))
        client_log = _windows_path_to_wsl(launch.get("clientLog"))

        _start_testrun()
        local_sync.wait_for_scene(
            HOST_PIPE,
            "testrun",
            timeout=45.0,
        )
        if multiplayer_enabled:
            local_sync.wait_for_scene(
                CLIENT_PIPE,
                "testrun",
                timeout=45.0,
            )

        expected_flow = (
            "multiplayer_host"
            if multiplayer_enabled
            else "single_player"
        )
        host_text = _wait_for_log(
            host_log,
            lambda text: (
                "Loading screen completed." in text
                and f"flow={expected_flow}" in text
                and (
                    not multiplayer_enabled
                    or _completed_after_stage(
                        text,
                        "generating_boneyard",
                    )
                )
            ),
            timeout=15.0,
            label=f"{flow_name} host loading completion",
        )
        required_host_stages = (
            NATIVE_STAGES +
            (
                (
                    "waiting_for_participants",
                    "confirming_participants",
                    "gameplay_ready",
                )
                if multiplayer_enabled
                else ()
            )
        )
        result["hostTimeline"] = _parse_completed_sequence(
            host_text,
            expected_flow=expected_flow,
            required_stages=required_host_stages,
        )
        if multiplayer_enabled:
            result["hostConnectionTimeline"] = (
                _parse_completed_sequence(
                    host_text,
                    expected_flow="multiplayer_host",
                    required_stages=(
                        "connecting_transport",
                    ),
                    completion_index=(
                        _completion_index_containing_stage(
                            host_text,
                            "connecting_transport",
                        )
                    ),
                )
            )
            host_connection_capture_stages = (
                _validate_connection_sequence(
                    result["hostConnectionTimeline"],
                    minimum_rendered_milestones=1,
                )
            )
            client_text = _wait_for_log(
                client_log,
                lambda text: (
                    "Loading screen completed." in text
                    and "flow=multiplayer_join" in text
                    and _completed_after_stage(
                        text,
                        "confirming_participants",
                    )
                ),
                timeout=15.0,
                label="multiplayer client loading completion",
            )
            result["clientConnectionTimeline"] = (
                _parse_completed_sequence(
                    client_text,
                    expected_flow="multiplayer_join",
                    required_stages=(
                        "connecting_transport",
                    ),
                    completion_index=(
                        _completion_index_containing_stage(
                            client_text,
                            "connecting_transport",
                        )
                    ),
                )
            )
            connection_capture_stages = (
                _validate_connection_sequence(
                    result["clientConnectionTimeline"]
                )
            )
            result["clientTimeline"] = (
                _parse_completed_sequence(
                    client_text,
                    expected_flow="multiplayer_join",
                    required_stages=(
                        "waiting_for_participants",
                        "confirming_participants",
                        "gameplay_ready",
                    ),
                    completion_index=(
                        _completion_index_containing_stage(
                            client_text,
                            "confirming_participants",
                            last=True,
                        )
                    ),
                )
            )
        else:
            client_scene = local_sync.lua(
                CLIENT_PIPE,
                "local s=sd.world.get_scene(); "
                "return tostring(s and (s.name or s.kind) or '')",
            ).strip()
            if client_scene != "hub":
                raise LoadingScreenFailure(
                    "transport-disabled control instance left the hub: "
                    f"{client_scene!r}"
                )
            result["controlClientScene"] = client_scene

        if any(
            marker in host_text
            for marker in (
                "Loading screen native-stage presentation failed.",
                "Loading screen evidence capture failed.",
            )
        ):
            raise LoadingScreenFailure(
                f"{flow_name} host reported a loading renderer failure"
            )
        if multiplayer_enabled and any(
            marker in client_text
            for marker in (
                "Loading screen native-stage presentation failed.",
                "Loading screen evidence capture failed.",
            )
        ):
            raise LoadingScreenFailure(
                "multiplayer client reported a loading renderer failure"
            )

        capture_deadline = time.monotonic() + 10.0
        required_capture_stages = (
            (
                "generating_boneyard",
                "reading_boneyard",
                "materializing_world",
            )
            if multiplayer_enabled
            else (
                "preparing_boneyard",
                "generating_boneyard",
                "reading_boneyard",
            )
        )
        required_role = "ffix-host"
        if multiplayer_enabled:
            required_capture_stages += (
                "waiting_for_participants",
            )
            required_role = ""
        while time.monotonic() < capture_deadline:
            names = [
                path.name
                for path in capture_directory.glob("*.bmp")
            ]
            if all(
                any(stage in name for name in names)
                for stage in required_capture_stages
            ):
                break
            time.sleep(0.05)
        captures = _capture_inventory(
            capture_directory,
            required_role=required_role,
            required_stages=required_capture_stages,
        )
        if multiplayer_enabled and not any(
            "ffix-client" in Path(capture["sourceBmp"]).name
            and capture["stage"] == "waiting_for_participants"
            for capture in captures
        ):
            raise LoadingScreenFailure(
                "no mid-multiplayer-join client frame was captured"
            )
        if multiplayer_enabled:
            connection_sequence = result[
                "clientConnectionTimeline"
            ]["sequence"]
            connection_captures = [
                capture
                for capture in captures
                if (
                    "ffix-client" in
                    Path(capture["sourceBmp"]).name
                    and f"-sequence-{connection_sequence}-" in
                    Path(capture["sourceBmp"]).name
                    and capture["stage"] in
                    connection_capture_stages
                )
            ]
            if len(
                {
                    capture["progress"]
                    for capture in connection_captures
                }
            ) < 2:
                raise LoadingScreenFailure(
                    "client join evidence did not capture two "
                    "different connecting-to-match labels and bar "
                    f"positions: {connection_captures}"
                )
            result["clientConnectionCaptures"] = (
                connection_captures
            )
            host_connection_sequence = result[
                "hostConnectionTimeline"
            ]["sequence"]
            host_connection_captures = [
                capture
                for capture in captures
                if (
                    "ffix-host" in
                    Path(capture["sourceBmp"]).name
                    and f"-sequence-{host_connection_sequence}-" in
                    Path(capture["sourceBmp"]).name
                    and capture["stage"] in
                    host_connection_capture_stages
                )
            ]
            if not host_connection_captures:
                raise LoadingScreenFailure(
                    "host session-formation evidence did not capture "
                    "a real label and bar position: "
                    f"{host_connection_captures}"
                )
            result["hostConnectionCaptures"] = (
                host_connection_captures
            )
        result["captures"] = captures
        result["nonemptyCrashArtifacts"] = (
            _nonempty_crash_artifacts(launch)
        )
        if result["nonemptyCrashArtifacts"]:
            raise LoadingScreenFailure(
                f"{flow_name} produced crash artifacts: "
                f"{result['nonemptyCrashArtifacts']}"
            )
        result["ok"] = True
    except BaseException as exc:
        failure = exc
        result["ok"] = False
        result["failure"] = {
            "type": type(exc).__name__,
            "message": str(exc),
        }
    finally:
        if launch:
            try:
                result["cleanup"] = (
                    local_sync.stop_exact_game_processes(launch)
                )
            except BaseException as cleanup_error:
                result["cleanupFailure"] = {
                    "type": type(cleanup_error).__name__,
                    "message": str(cleanup_error),
                }
                if failure is None:
                    failure = cleanup_error
                    result["ok"] = False
    if failure is not None:
        raise failure
    return result


def verify(
    *,
    game_directory: Path,
    output_path: Path,
) -> dict[str, Any]:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    run_stamp = datetime.now(timezone.utc).strftime(
        "%Y%m%dT%H%M%SZ"
    )
    record: dict[str, Any] = {
        "ok": False,
        "instancePrefix": INSTANCE_PREFIX,
        "ports": {
            "host": HOST_PORT,
            "client": CLIENT_PORT,
        },
        "audioExpectedDisabled": True,
        "captureMethod": (
            "D3D9 backbuffer after the loading draw at the shared "
            "EndScene or native-stage presentation boundary"
        ),
    }
    failure: BaseException | None = None
    try:
        record["multiplayer"] = _run_flow(
            flow_name="multiplayer",
            multiplayer_enabled=True,
            capture_directory=(
                EVIDENCE_ROOT /
                f"loading-screen-multiplayer-{run_stamp}"
            ),
            game_directory=game_directory,
        )
        record["singlePlayer"] = _run_flow(
            flow_name="single-player",
            multiplayer_enabled=False,
            capture_directory=(
                EVIDENCE_ROOT /
                f"loading-screen-single-player-{run_stamp}"
            ),
            game_directory=game_directory,
        )
        record["ok"] = True
    except BaseException as exc:
        failure = exc
        record["failure"] = {
            "type": type(exc).__name__,
            "message": str(exc),
        }
    finally:
        output_path.write_text(
            json.dumps(record, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    if failure is not None:
        raise failure
    return record


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--game-directory",
        type=Path,
        default=GAME_DIRECTORY,
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=OUTPUT_PATH,
    )
    args = parser.parse_args()
    result = verify(
        game_directory=args.game_directory,
        output_path=args.output,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
