#!/usr/bin/env python3
"""Drive and verify the owner-reported multiplayer flow without test seams."""

from __future__ import annotations

import argparse
from dataclasses import asdict
import json
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import time
import traceback
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools._real_flow_e2e.config import (  # noqa: E402
    ConfigError,
    HarnessConfig,
    LOCAL_WINDOWS,
)
from tools._real_flow_e2e.evidence import (  # noqa: E402
    EvidenceError,
    JsonlWriter,
    copy_runtime_artifacts,
    packet_accounting,
    paired_windows_capture,
    rendered_enemy_assertion,
    write_json,
    write_manifest,
)
from tools._real_flow_e2e.runtime import (  # noqa: E402
    LuaPipe,
    RuntimeProbeError,
    approach_solomon_and_complete_dialogue,
    damage_enemy_with_real_input,
    enemy_attack_assertion,
    enemy_motion_assertion,
    execute_actions,
    wait_for_state,
    wait_shared_hub,
)
from tools._real_flow_e2e.windows import (  # noqa: E402
    PowerShell,
    WindowsHarnessError,
    WindowsPeer,
    assert_ports_free,
    client_through_launcher,
    close_exact_owned_processes,
    exact_owned_processes,
    host_through_launcher,
    port_inventory,
    prepare_windows_peer,
    windows_processes,
)
from tools._real_flow_e2e.remote import RemoteHarnessError  # noqa: E402
from tools._real_flow_e2e.wan import (  # noqa: E402
    WanFlowFailure,
    run_wan_nfo,
)
from tools._real_flow_e2e.ws20 import (  # noqa: E402
    RemoteWindowsConnection,
    Ws20HarnessError,
    Ws20Peer,
)


class RealFlowFailure(RuntimeError):
    """The real-flow contract did not complete or an assertion failed."""


class PairSampler:
    def __init__(
        self,
        host: LuaPipe,
        client: LuaPipe,
        writer: JsonlWriter,
        interval_seconds: float,
    ) -> None:
        self.host = host
        self.client = client
        self.writer = writer
        self.interval_seconds = interval_seconds
        self.started = time.monotonic()
        self.phase = "not-started"
        self.rows: list[dict[str, Any]] = []
        self.errors: list[dict[str, Any]] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def set_phase(self, phase: str) -> None:
        with self._lock:
            self.phase = phase

    def start(self) -> None:
        if self._thread is not None:
            raise RealFlowFailure("pair sampler was started twice")
        self._thread = threading.Thread(
            target=self._run,
            name="real-flow-pair-sampler",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=20)
            if self._thread.is_alive():
                raise RealFlowFailure("pair sampler did not stop")

    def sample_now(self, label: str) -> dict[str, Any]:
        row = self._sample(label)
        self.rows.append(row)
        self.writer.append(row)
        return row

    def _sample(self, label: str) -> dict[str, Any]:
        with self._lock:
            phase = self.phase
        started_ns = time.time_ns()
        host = self.host.state()
        between_ns = time.time_ns()
        client = self.client.state()
        return {
            "schemaVersion": 1,
            "label": label,
            "phase": phase,
            "utcNanoseconds": started_ns,
            "betweenPeerUtcNanoseconds": between_ns,
            "completedUtcNanoseconds": time.time_ns(),
            "elapsedSeconds": time.monotonic() - self.started,
            "host": host,
            "clientB": client,
        }

    def _run(self) -> None:
        next_sample = time.monotonic()
        while not self._stop.is_set():
            try:
                row = self._sample("periodic")
                self.rows.append(row)
                self.writer.append(row)
            except BaseException as exc:
                error = {
                    "timeUtcNanoseconds": time.time_ns(),
                    "elapsedSeconds": time.monotonic() - self.started,
                    "phase": self.phase,
                    "error": f"{type(exc).__name__}: {exc}",
                }
                self.errors.append(error)
            next_sample += self.interval_seconds
            delay = max(0.01, next_sample - time.monotonic())
            self._stop.wait(delay)


def _git_sha(source_root: Path) -> str:
    completed = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=source_root,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=15,
        check=False,
    )
    sha = completed.stdout.strip().lower()
    if completed.returncode != 0 or len(sha) != 40:
        raise RealFlowFailure(
            f"could not resolve source SHA: {completed.stdout.strip()}"
        )
    return sha


def _process_rows(ps: PowerShell) -> list[dict[str, Any]]:
    return [asdict(record) for record in windows_processes(ps)]


def _owned_process_rows(
    ps: PowerShell,
    peers: tuple[WindowsPeer, ...],
) -> list[dict[str, Any]]:
    return [asdict(record) for record in exact_owned_processes(ps, peers)]


def _assert_client_enemy_materialization(
    state: dict[str, Any],
) -> dict[str, Any]:
    client = state["clientB"]
    replicas = [
        enemy
        for enemy in client["replicatedEnemies"]
        if not enemy["dead"] and enemy["hp"] > 0
    ]
    bindings = {
        int(binding["network_id"]): binding
        for binding in client["enemyBindings"]
        if binding["matched"]
        and not binding["parked"]
        and not binding["removed"]
        and int(binding["address"]) != 0
    }
    native_network_ids = {
        int(enemy["network_id"])
        for enemy in client["nativeEnemies"]
        if not enemy["dead"]
        and enemy["hp"] > 0
        and int(enemy["network_id"]) != 0
    }
    replica_ids = {
        int(enemy["network_id"])
        for enemy in replicas
        if int(enemy["network_id"]) != 0
    }
    bound_ids = replica_ids.intersection(bindings)
    native_ids = replica_ids.intersection(native_network_ids)
    if not replicas or not bound_ids or not native_ids:
        raise RealFlowFailure(
            "client B did not materialize host-authored enemies as native "
            f"replicas: replicas={sorted(replica_ids)} "
            f"bound={sorted(bound_ids)} native={sorted(native_ids)}"
        )
    return {
        "replicaIds": sorted(replica_ids),
        "boundReplicaIds": sorted(bound_ids),
        "nativeReplicaIds": sorted(native_ids),
        "replicaCount": len(replicas),
    }


def _copy_and_account(
    peer: Any,
    output_directory: Path,
) -> dict[str, Any]:
    remote_copy = getattr(peer, "copy_runtime_artifacts", None)
    if callable(remote_copy):
        copied = dict(remote_copy(output_directory))
    else:
        copied = copy_runtime_artifacts(peer, output_directory)
    telemetry = copied["networkTelemetry"]
    if not telemetry["copied"]:
        raise RealFlowFailure(
            f"{peer.config.role} did not produce mandatory network telemetry: "
            f"{telemetry}"
        )
    accounting = packet_accounting(Path(telemetry["path"]))
    if accounting["events"].get("telemetry_start", 0) != 1:
        raise RealFlowFailure(
            f"{peer.config.role} telemetry did not start exactly once: "
            f"{accounting['events']}"
        )
    return {"copied": copied, "packetAccounting": accounting}


def run(config: HarnessConfig, *, phase: str) -> dict[str, Any]:
    actual_sha = _git_sha(config.source_root)
    if actual_sha != config.expected_source_sha:
        raise RealFlowFailure(
            f"source SHA changed: expected {config.expected_source_sha}, "
            f"actual {actual_sha}"
        )
    if config.topology == "wan_udp_nfo":
        return run_wan_nfo(
            config,
            phase=phase,
            sampler_type=PairSampler,
        )
    is_ws20 = config.topology == "steam_windows_ws20"
    if config.host.platform != LOCAL_WINDOWS or (
        not is_ws20 and config.client.platform != LOCAL_WINDOWS
    ):
        raise RealFlowFailure(
            "this controller currently requires local Windows launcher peers; "
            "remote peer controllers are selected by their topology adapter"
        )
    config.evidence_root.mkdir(parents=True, exist_ok=False)
    write_json(config.evidence_root / "config.redacted.json", config.redacted())
    write_json(
        config.evidence_root / "source.json",
        {
            "expectedSha": config.expected_source_sha,
            "actualSha": actual_sha,
            "sourceRoot": str(config.source_root),
        },
    )

    ps = PowerShell(config.source_root)
    ports = {
        peer.local_port
        for peer in (config.host, config.client)
        if peer.local_port
    }
    ports.update(
        peer.remote_port
        for peer in (config.host, config.client)
        if peer.remote_port
    )
    assert_ports_free(ps, ports)
    connection: RemoteWindowsConnection | None = None
    remote_before: dict[str, int] | None = None
    if is_ws20:
        connection = RemoteWindowsConnection(config.client)
        remote_before = connection.inventory()
        if remote_before != {
            "ownedProcessCount": 0,
            "taskCount": 0,
            "interactiveSteamCount": 1,
        }:
            connection.close()
            raise RealFlowFailure(
                "workstation20 did not satisfy the isolated preflight "
                f"boundary: {remote_before}"
            )
    before = {
        "utcNanoseconds": time.time_ns(),
        "processes": _process_rows(ps),
        "reservedPorts": port_inventory(ps, ports),
    }
    if remote_before is not None:
        before["clientBRemote"] = remote_before
    write_json(config.evidence_root / "safety" / "before.json", before)

    try:
        host = prepare_windows_peer(config, config.host)
        if is_ws20:
            assert connection is not None
            client: Any = Ws20Peer.prepare(config, connection)
            peers = (host,)
        else:
            client = prepare_windows_peer(config, config.client)
            peers = (host, client)
    except BaseException:
        if connection is not None:
            try:
                connection.remove_tree(
                    connection.stage_root.rstrip("\\")
                    + "\\r\\"
                    + config.run_name
                )
            finally:
                connection.close()
        staging_root = config.evidence_root / "staging"
        if staging_root.is_dir():
            shutil.rmtree(staging_root)
        raise
    host_pipe = LuaPipe(config.source_root, config.host.pipe_name)
    if is_ws20:
        client_pipe = client.open_lua_pipe()
    else:
        client_pipe = LuaPipe(
            config.source_root,
            config.client.pipe_name,
        )
    timeline = JsonlWriter(config.evidence_root / "timeline.jsonl")
    sampler = PairSampler(
        host_pipe,
        client_pipe,
        timeline,
        config.sampling_seconds,
    )
    sampler_started = False
    result: dict[str, Any] = {
        "schemaVersion": 1,
        "ok": False,
        "runName": config.run_name,
        "topology": config.topology,
        "phaseRequested": phase,
        "sourceSha": actual_sha,
        "forbiddenSeamsUsed": False,
        "networkTelemetryRequired": True,
        "audioDisabledRequired": True,
    }
    cleanup: dict[str, Any] = {}
    primary_error: BaseException | None = None
    try:
        result["hostLauncher"] = host_through_launcher(ps, config, host)
        if is_ws20:
            result["clientBLauncher"] = client.launch(host.lobby_id)
        else:
            result["clientBLauncher"] = client_through_launcher(
                ps,
                config,
                client,
                host.lobby_id,
            )
        remote_ledger = (
            connection.inventory()
            if connection is not None
            else None
        )
        write_json(
            config.evidence_root / "process-ledger.json",
            {
                "host": result["hostLauncher"],
                "clientB": result["clientBLauncher"],
                "ownedProcesses": _owned_process_rows(ps, peers),
                **(
                    {
                        "clientBStaging": {
                            "validated": True,
                            "sha256": client.staged_hashes,
                        }
                    }
                    if is_ws20
                    else {}
                ),
                **(
                    {"clientBRemote": remote_ledger}
                    if remote_ledger is not None
                    else {}
                ),
            },
        )
        result["sharedHub"] = wait_shared_hub(
            host_pipe,
            client_pipe,
            timeout=config.timeout_seconds,
        )
        sampler.set_phase("shared-hub")
        sampler.start()
        sampler_started = True
        sampler.sample_now("shared-hub-ready")

        if phase == "shared-hub":
            result["ok"] = True
            result["completedPhase"] = "shared-hub"
            return result
        if not config.host.match_start_actions:
            raise RealFlowFailure(
                "full run requires host.matchStartActions with real key/click "
                "input for the native Start Match flow"
            )

        sampler.set_phase("match-start")
        result["hostMatchStartActions"] = execute_actions(
            config.source_root,
            host,
            host_pipe,
            config.host.match_start_actions,
        )
        result["sharedRun"] = {
            "host": wait_for_state(
                host_pipe,
                lambda state: (
                    state["solomon"]["valid"]
                    and state["scene"]["name"] == "testrun"
                ),
                timeout=config.timeout_seconds,
                label="host native testrun after Start Match",
            ),
            "clientB": wait_for_state(
                client_pipe,
                lambda state: state["scene"]["name"] == "testrun",
                timeout=config.timeout_seconds,
                label="client B native testrun after host Start Match",
            ),
        }
        sampler.sample_now("native-run-materialized")

        sampler.set_phase("host-solomon-dig")
        result["hostSolomonDig"] = approach_solomon_and_complete_dialogue(
            config.source_root,
            host,
            host_pipe,
            timeout=config.timeout_seconds,
        )
        sampler.sample_now("host-solomon-native-completion")

        sampler.set_phase("first-enemy-spawn")
        enemy_state = sampler.sample_now("first-enemy-wait-start")
        deadline = time.monotonic() + config.timeout_seconds
        materialization: dict[str, Any] | None = None
        materialization_error = ""
        while time.monotonic() < deadline:
            enemy_state = sampler.sample_now("first-enemy-wait")
            if (
                len(enemy_state["host"]["nativeEnemies"]) > 0
                and len(enemy_state["clientB"]["replicatedEnemies"]) > 0
            ):
                try:
                    materialization = (
                        _assert_client_enemy_materialization(
                            enemy_state
                        )
                    )
                    break
                except RealFlowFailure as exc:
                    materialization_error = str(exc)
            time.sleep(0.2)
        else:
            raise RealFlowFailure(
                "the real flow produced no aligned host/native and "
                "client/materialized replicated enemies; "
                f"last={materialization_error!r}"
            )
        assert materialization is not None
        result["clientEnemyMaterialization"] = materialization

        sampler.set_phase("paired-render-capture")
        capture_state = sampler.sample_now("paired-capture-state")
        result["pairedCapture"] = paired_windows_capture(
            config.source_root,
            host,
            client,
            config.evidence_root / "screenshots",
            label="first-wave",
        )
        client_capture_path = Path(
            result["pairedCapture"]["captures"]["clientB"]["path"]
        )
        result["clientEnemyRendered"] = rendered_enemy_assertion(
            capture_state["clientB"],
            client_capture_path,
        )

        sampler.set_phase("client-real-damage")
        result["clientEnemyDamage"] = damage_enemy_with_real_input(
            config.source_root,
            client,
            client_pipe,
            timeout=config.timeout_seconds,
        )
        sampler.sample_now("client-damage-observed")

        sampler.set_phase("enemy-motion")
        motion_deadline = time.monotonic() + min(
            5.0,
            config.timeout_seconds,
        )
        while time.monotonic() < motion_deadline:
            sampler.sample_now("enemy-motion")
            time.sleep(max(0.1, config.sampling_seconds))
        result["clientEnemyMotion"] = enemy_motion_assertion(sampler.rows)
        result["clientEnemyAttack"] = enemy_attack_assertion(sampler.rows)

        result["postDamageCapture"] = paired_windows_capture(
            config.source_root,
            host,
            client,
            config.evidence_root / "screenshots",
            label="post-client-damage",
        )
        result["completedPhase"] = "full"
        result["ok"] = True
        return result
    except BaseException as exc:
        primary_error = exc
        result["error"] = {
            "type": type(exc).__name__,
            "message": str(exc),
            "traceback": traceback.format_exc(),
        }
        return result
    finally:
        if sampler_started:
            try:
                sampler.stop()
                result["sampler"] = {
                    "rowCount": len(sampler.rows),
                    "errors": sampler.errors,
                }
            except BaseException as exc:
                cleanup["samplerStopError"] = (
                    f"{type(exc).__name__}: {exc}"
                )
                result["ok"] = False
        try:
            cleanup["processClose"] = close_exact_owned_processes(ps, peers)
        except BaseException as exc:
            cleanup["processCloseError"] = f"{type(exc).__name__}: {exc}"
            result["ok"] = False
        if is_ws20:
            try:
                cleanup["clientBProcessClose"] = client.close_processes()
            except BaseException as exc:
                cleanup["clientBProcessCloseError"] = (
                    f"{type(exc).__name__}: {exc}"
                )
                result["ok"] = False
        try:
            time.sleep(0.5)
            result["artifacts"] = {
                "host": _copy_and_account(
                    host,
                    config.evidence_root / "runtime",
                ),
                "clientB": _copy_and_account(
                    client,
                    config.evidence_root / "runtime",
                ),
            }
        except BaseException as exc:
            cleanup["artifactError"] = f"{type(exc).__name__}: {exc}"
            result["ok"] = False
        if is_ws20:
            try:
                client.delete_run()
                cleanup["clientBRunDeleted"] = True
            except BaseException as exc:
                cleanup["clientBRunDeleteError"] = (
                    f"{type(exc).__name__}: {exc}"
                )
                result["ok"] = False
        try:
            staging_root = config.evidence_root / "staging"
            if staging_root.is_dir():
                shutil.rmtree(staging_root)
                cleanup["stagingDeleted"] = str(staging_root)
        except BaseException as exc:
            cleanup["stagingDeleteError"] = (
                f"{type(exc).__name__}: {exc}"
            )
            result["ok"] = False
        try:
            after_ports = port_inventory(ps, ports)
            after_owned = _owned_process_rows(ps, peers)
            remote_after = (
                connection.inventory()
                if connection is not None
                else None
            )
            write_json(
                config.evidence_root / "safety" / "after.json",
                {
                    "utcNanoseconds": time.time_ns(),
                    "reservedPorts": after_ports,
                    "ownedProcesses": after_owned,
                    **(
                        {"clientBRemote": remote_after}
                        if remote_after is not None
                        else {}
                    ),
                },
            )
            expected_remote_after = {
                "ownedProcessCount": 0,
                "taskCount": 0,
                "interactiveSteamCount": 1,
            }
            if (
                after_ports
                or after_owned
                or (
                    remote_after is not None
                    and remote_after != expected_remote_after
                )
            ):
                cleanup["residualSafetyFailure"] = {
                    "reservedPorts": after_ports,
                    "ownedProcesses": after_owned,
                    "clientBRemote": remote_after,
                }
                result["ok"] = False
        except BaseException as exc:
            cleanup["afterInventoryError"] = (
                f"{type(exc).__name__}: {exc}"
            )
            result["ok"] = False
        result["cleanup"] = cleanup
        if connection is not None:
            connection.close()
        if primary_error is None and not result["ok"]:
            result.setdefault(
                "error",
                {
                    "type": "CleanupFailure",
                    "message": "the real flow passed but cleanup/evidence failed",
                },
            )
        write_json(config.evidence_root / "result.json", result)
        write_manifest(config.evidence_root)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Drive the real desktop-launcher multiplayer flow, host-native "
            "Start Match, host physical Solomon Dig conversation, and client "
            "enemy render/combat assertions."
        )
    )
    parser.add_argument("config", type=Path)
    parser.add_argument(
        "--phase",
        choices=("shared-hub", "full"),
        default="full",
        help="shared-hub is a bounded calibration run; full is acceptance",
    )
    args = parser.parse_args()
    try:
        config = HarnessConfig.load(args.config)
        result = run(config, phase=args.phase)
    except (
        ConfigError,
        EvidenceError,
        RealFlowFailure,
        RuntimeProbeError,
        RemoteHarnessError,
        WanFlowFailure,
        WindowsHarnessError,
        Ws20HarnessError,
    ) as exc:
        print(f"FAIL: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    if not result["ok"]:
        print(
            "FAIL: " + json.dumps(result.get("error", {}), sort_keys=True),
            file=sys.stderr,
        )
        return 1
    print(
        "PASS: "
        + json.dumps(
            {
                "evidenceRoot": str(config.evidence_root),
                "runName": config.run_name,
                "topology": config.topology,
                "completedPhase": result["completedPhase"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
