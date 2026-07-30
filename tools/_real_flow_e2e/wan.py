from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import shutil
import tarfile
from pathlib import Path
import time
import traceback
from typing import Any

from .config import HarnessConfig
from .evidence import (
    JsonlWriter,
    copy_runtime_artifacts,
    packet_accounting,
    rendered_enemy_assertion,
    write_json,
    write_manifest,
)
from .remote import (
    RemoteConnection,
    RemoteHarnessError,
    RemoteLuaPipe,
    RemoteProtonPeer,
)
from .runtime import (
    LuaPipe,
    approach_solomon_and_complete_dialogue,
    damage_click_targets,
    enemy_attack_assertion,
    enemy_motion_assertion,
    execute_actions,
    wait_for_state,
    wait_shared_hub,
)
from .windows import (
    PowerShell,
    WindowsPeer,
    capture_window,
    close_exact_owned_processes,
    host_through_launcher,
    port_inventory,
    prepare_windows_peer,
)


class WanFlowFailure(RuntimeError):
    """The real-flow WAN acceptance contract failed."""


def _client_materialization(state: dict[str, Any]) -> dict[str, Any]:
    client = state["clientB"]
    replicas = [
        enemy
        for enemy in client["replicatedEnemies"]
        if not enemy["dead"] and enemy["hp"] > 0
    ]
    bindings = {
        int(binding["network_id"])
        for binding in client["enemyBindings"]
        if binding["matched"]
        and not binding["parked"]
        and not binding["removed"]
        and int(binding["address"]) != 0
    }
    native = {
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
    if not replica_ids or not replica_ids.intersection(bindings, native):
        raise WanFlowFailure(
            "client B did not materialize host enemies as native replicas: "
            f"replicas={sorted(replica_ids)} "
            f"bound={sorted(replica_ids.intersection(bindings))} "
            f"native={sorted(replica_ids.intersection(native))}"
        )
    return {
        "replicaIds": sorted(replica_ids),
        "boundReplicaIds": sorted(replica_ids.intersection(bindings)),
        "nativeReplicaIds": sorted(replica_ids.intersection(native)),
        "replicaCount": len(replicas),
    }


def _paired_capture(
    config: HarnessConfig,
    host: WindowsPeer,
    remote: RemoteProtonPeer,
    output: Path,
) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    stamp = (
        time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
        + f"-{time.time_ns() % 1_000_000_000:09d}"
    )
    clock_alignment = remote.connection.clock_alignment()
    selected_clock = clock_alignment["selected"]
    with ThreadPoolExecutor(max_workers=2) as executor:
        host_future = executor.submit(
            capture_window,
            config.source_root,
            host,
            output / f"first-wave-{stamp}-host.png",
        )
        client_future = executor.submit(
            remote.capture,
            f"first-wave-{stamp}",
            output / f"first-wave-{stamp}-client-b.png",
        )
        captures = {
            "host": host_future.result(),
            "clientB": client_future.result(),
        }
    captures["clientB"]["captureUtcNanoseconds"] = (
        captures["clientB"]["remoteCaptureUtcNanoseconds"]
        + selected_clock["remoteToControllerOffsetNanoseconds"]
    )
    skew = abs(
        captures["host"]["captureUtcNanoseconds"]
        - captures["clientB"]["captureUtcNanoseconds"]
    )
    conservative_skew = (
        skew + selected_clock["uncertaintyNanoseconds"]
    )
    if conservative_skew > 1_000_000_000:
        raise WanFlowFailure(
            "paired WAN screenshot wall-clock skew exceeded one second: "
            f"estimated={skew / 1e6:.1f} ms "
            f"uncertainty="
            f"{selected_clock['uncertaintyNanoseconds'] / 1e6:.1f} ms"
        )
    return {
        "captureSkewNanoseconds": skew,
        "conservativeCaptureSkewNanoseconds": conservative_skew,
        "clockAlignment": clock_alignment,
        "captures": captures,
    }


def _damage_remote_enemy(
    remote: RemoteProtonPeer,
    pipe: RemoteLuaPipe,
    *,
    timeout: float,
) -> dict[str, Any]:
    def live_candidates(state: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            enemy
            for enemy in state["replicatedEnemies"]
            if not enemy["dead"] and enemy["hp"] > 0
        ]

    before = wait_for_state(
        pipe,
        lambda state: (
            state["scene"]["name"] == "testrun"
            and state["player"]["valid"]
            and state["player"]["hp"] > 0
            and bool(
                damage_click_targets(
                    live_candidates(state),
                    state["player"],
                    state["viewport"],
                    state["camera"],
                )
            )
        ),
        timeout=timeout,
        label="client B native-camera-aimable replica for real damage",
    )
    viewport = before["viewport"]
    if viewport["width"] <= 0 or viewport["height"] <= 0:
        raise WanFlowFailure(
            f"client B reported an invalid viewport: {viewport}"
        )
    live = live_candidates(before)
    hp_before = {
        int(enemy["network_id"]): float(enemy["hp"])
        for enemy in live
    }

    actions: list[dict[str, Any]] = []
    deadline = time.monotonic() + min(timeout, 25.0)
    last = before
    while time.monotonic() < deadline:
        if (
            last["scene"]["name"] != "testrun"
            or not last["player"]["valid"]
            or last["player"]["hp"] <= 0
        ):
            raise WanFlowFailure(
                "client B left live combat before real pointer input "
                f"damaged an enemy; actions={actions}"
            )
        targets = damage_click_targets(
            live_candidates(last),
            last["player"],
            last["viewport"],
            last["camera"],
        )
        if not targets:
            time.sleep(0.12)
            last = pipe.state()
            continue
        target = targets[len(actions) % len(targets)]
        actions.append(remote.click_game(*target))
        time.sleep(0.12)
        last = pipe.state()
        current = {
            int(enemy["network_id"]): enemy
            for enemy in last["replicatedEnemies"]
        }
        for network_id, original_hp in hp_before.items():
            enemy = current.get(network_id)
            current_hp = (
                0.0
                if enemy is None or enemy["dead"]
                else float(enemy["hp"])
            )
            if current_hp < original_hp - 0.01:
                return {
                    "networkActorId": network_id,
                    "hpBefore": original_hp,
                    "hpAfter": current_hp,
                    "actions": actions,
                    "before": before,
                    "after": last,
                }
    raise WanFlowFailure(
        "client B real pointer input did not damage a replicated enemy; "
        f"baseline={hp_before}; actions={actions}"
    )


def _extract_remote_runtime(
    archive_path: Path,
    destination: Path,
) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive_path, "r:") as archive:
        for member in archive.getmembers():
            path = Path(member.name)
            if (
                not member.isfile()
                or path.is_absolute()
                or ".." in path.parts
            ):
                raise WanFlowFailure(
                    f"remote runtime archive member was unsafe: {member.name}"
                )
        archive.extractall(destination, filter="data")
    telemetry = (
        destination / ".sdmod" / "logs" / "network-telemetry.jsonl"
    )
    if not telemetry.is_file() or telemetry.stat().st_size == 0:
        raise WanFlowFailure(
            "remote client did not produce mandatory network telemetry"
        )
    return telemetry


def run_wan_nfo(
    config: HarnessConfig,
    *,
    phase: str,
    sampler_type: type,
) -> dict[str, Any]:
    config.evidence_root.mkdir(parents=True, exist_ok=False)
    write_json(
        config.evidence_root / "config.redacted.json",
        config.redacted(),
    )
    ps = PowerShell(config.source_root)
    connection = RemoteConnection(config.client, config.source_root)
    remote = RemoteProtonPeer(config.client, connection)
    remote_before = connection.run(
        "ss -H -lunp | grep -E ':(51611|51612)[[:space:]]' || true; "
        "ps auxww | grep -F /root/sd-netrepro-20260729 | "
        "grep -v grep || true"
    )
    local_before = port_inventory(ps, {config.host.local_port})
    if local_before:
        raise WanFlowFailure(
            f"local WAN port is already occupied: {local_before}"
        )
    if remote_before.strip():
        raise WanFlowFailure(
            "NFO stage already owns a process or reserved port: "
            f"{remote_before.strip()}"
        )
    write_json(
        config.evidence_root / "safety" / "before.json",
        {
            "utcNanoseconds": time.time_ns(),
            "localReservedPorts": local_before,
            "remoteOwnedProcessesAndPorts": remote_before,
        },
    )

    result: dict[str, Any] = {
        "schemaVersion": 1,
        "ok": False,
        "runName": config.run_name,
        "topology": config.topology,
        "phaseRequested": phase,
        "sourceSha": config.expected_source_sha,
        "forbiddenSeamsUsed": False,
        "networkTelemetryRequired": True,
        "audioDisabledRequired": True,
    }
    cleanup: dict[str, Any] = {}
    host: WindowsPeer | None = None
    remote_pipe: RemoteLuaPipe | None = None
    sampler: Any = None
    remote_prepared = False
    try:
        result["remoteStage"] = remote.prepare(
            config,
            config.evidence_root / "staging" / "remote",
        )
        remote_prepared = True
        host = prepare_windows_peer(config, config.host)
        result["hostLauncher"] = host_through_launcher(ps, config, host)
        result["clientBLauncher"] = remote.start_and_join(host.lobby_id)
        try:
            result["clientBAuthenticatedSession"] = (
                remote.wait_connected_session(
                    timeout=min(45.0, config.timeout_seconds),
                )
            )
        except RemoteHarnessError as cold_error:
            cold_archive = remote.copy_runtime_artifacts(
                config.evidence_root
                / "runtime"
                / "client-b-cold-start-runtime.tar"
            )
            result["clientBColdStartRetry"] = {
                "required": True,
                "reason": str(cold_error),
                "launcher": result["clientBLauncher"],
                "runtimeArchive": str(cold_archive),
                "stop": remote.stop(),
            }
            time.sleep(1.0)
            result["clientBLauncher"] = remote.start_and_join(
                host.lobby_id
            )
            result["clientBAuthenticatedSession"] = (
                remote.wait_connected_session(
                    timeout=config.timeout_seconds,
                )
            )
        host_pipe = LuaPipe(config.source_root, config.host.pipe_name)
        remote_pipe = RemoteLuaPipe(
            connection,
            config.client.instance,
        )
        result["sharedHub"] = wait_shared_hub(
            host_pipe,
            remote_pipe,
            timeout=config.timeout_seconds,
        )
        sampler = sampler_type(
            host_pipe,
            remote_pipe,
            JsonlWriter(config.evidence_root / "timeline.jsonl"),
            config.sampling_seconds,
        )
        sampler.set_phase("shared-hub")
        sampler.start()
        sampler.sample_now("shared-hub-ready")
        if phase == "shared-hub":
            result["completedPhase"] = phase
            result["ok"] = True
            return result

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
                label="host native run",
            ),
            "clientB": wait_for_state(
                remote_pipe,
                lambda state: state["scene"]["name"] == "testrun",
                timeout=config.timeout_seconds,
                label="client B native run",
            ),
        }
        sampler.sample_now("native-run-materialized")

        sampler.set_phase("host-solomon-dig")
        result["hostSolomonDig"] = (
            approach_solomon_and_complete_dialogue(
                config.source_root,
                host,
                host_pipe,
                timeout=config.timeout_seconds,
            )
        )
        sampler.sample_now("host-solomon-native-completion")

        sampler.set_phase("first-enemy-spawn")
        deadline = time.monotonic() + config.timeout_seconds
        enemy_state: dict[str, Any] | None = None
        materialization: dict[str, Any] | None = None
        materialization_error = ""
        while time.monotonic() < deadline:
            enemy_state = sampler.sample_now("first-enemy-wait")
            if (
                enemy_state["host"]["nativeEnemies"]
                and enemy_state["clientB"]["replicatedEnemies"]
            ):
                try:
                    materialization = _client_materialization(
                        enemy_state
                    )
                    break
                except WanFlowFailure as exc:
                    materialization_error = str(exc)
            time.sleep(0.1)
        else:
            raise WanFlowFailure(
                "host enemies and client materialized replicas never "
                f"aligned; last={materialization_error!r}"
            )
        assert enemy_state is not None
        assert materialization is not None
        result["clientEnemyMaterialization"] = materialization

        sampler.set_phase("client-real-damage")
        result["clientEnemyDamage"] = _damage_remote_enemy(
            remote,
            remote_pipe,
            timeout=config.timeout_seconds,
        )
        sampler.sample_now("client-damage-observed")

        sampler.set_phase("paired-render-capture")
        capture_state = sampler.sample_now("paired-capture-state")
        result["pairedCapture"] = _paired_capture(
            config,
            host,
            remote,
            config.evidence_root / "screenshots",
        )
        client_capture = Path(
            result["pairedCapture"]["captures"]["clientB"]["path"]
        )
        result["clientEnemyRendered"] = rendered_enemy_assertion(
            capture_state["clientB"],
            client_capture,
        )

        sampler.set_phase("enemy-motion")
        time.sleep(5)
        sampler.sample_now("enemy-motion-end")
        result["clientEnemyMotion"] = enemy_motion_assertion(
            sampler.rows
        )
        result["clientEnemyAttack"] = enemy_attack_assertion(
            sampler.rows
        )
        result["completedPhase"] = "full"
        result["ok"] = True
        return result
    except BaseException as exc:
        result["error"] = {
            "type": type(exc).__name__,
            "message": str(exc),
            "traceback": traceback.format_exc(),
        }
        return result
    finally:
        if sampler is not None:
            try:
                sampler.stop()
                result["sampler"] = {
                    "rowCount": len(sampler.rows),
                    "errors": sampler.errors,
                }
            except BaseException as exc:
                cleanup["samplerStopError"] = str(exc)
                result["ok"] = False
        if remote_pipe is not None:
            try:
                remote_pipe.close()
            except BaseException as exc:
                cleanup["remoteLuaCloseError"] = str(exc)
                result["ok"] = False
        if host is not None:
            try:
                copied = copy_runtime_artifacts(
                    host,
                    config.evidence_root / "runtime",
                )
                result.setdefault("artifacts", {})["host"] = {
                    "copied": copied,
                    "packetAccounting": packet_accounting(
                        Path(copied["networkTelemetry"]["path"])
                    ),
                }
            except BaseException as exc:
                cleanup["hostArtifactError"] = str(exc)
                result["ok"] = False
        if remote_prepared:
            try:
                remote.stop()
                remote_archive = remote.copy_runtime_artifacts(
                    config.evidence_root
                    / "runtime"
                    / "client-b-runtime.tar"
                )
                telemetry = _extract_remote_runtime(
                    remote_archive,
                    config.evidence_root / "runtime" / "client",
                )
                result.setdefault("artifacts", {})["clientB"] = {
                    "archive": str(remote_archive),
                    "networkTelemetry": str(telemetry),
                    "packetAccounting": packet_accounting(telemetry),
                }
            except BaseException as exc:
                cleanup["remoteArtifactError"] = (
                    f"{type(exc).__name__}: {exc}"
                )
                result["ok"] = False
        if host is not None:
            try:
                cleanup["localProcessClose"] = (
                    close_exact_owned_processes(ps, (host,))
                )
            except BaseException as exc:
                cleanup["localProcessCloseError"] = str(exc)
                result["ok"] = False
        try:
            staging = config.evidence_root / "staging"
            if staging.is_dir():
                shutil.rmtree(staging)
                cleanup["localStagingDeleted"] = str(staging)
        except BaseException as exc:
            cleanup["localStagingDeleteError"] = str(exc)
            result["ok"] = False
        try:
            stage_exists = connection.run(
                "if test -e /root/sd-netrepro-20260729; "
                "then printf yes; else printf no; fi"
            ).strip()
            if stage_exists == "yes":
                cleanup["remoteStageDelete"] = remote.delete_stage()
            elif stage_exists != "no":
                raise WanFlowFailure(
                    f"remote stage probe returned {stage_exists!r}"
                )
        except BaseException as exc:
            cleanup["remoteStageDeleteError"] = (
                f"{type(exc).__name__}: {exc}"
            )
            result["ok"] = False
        try:
            after_remote = connection.run(
                "ss -H -lunp | "
                "grep -E ':(51611|51612)[[:space:]]' || true; "
                "ps auxww | grep -F /root/sd-netrepro-20260729 | "
                "grep -v grep || true"
            )
            after_local = port_inventory(ps, {config.host.local_port})
            write_json(
                config.evidence_root / "safety" / "after.json",
                {
                    "utcNanoseconds": time.time_ns(),
                    "localReservedPorts": after_local,
                    "remoteOwnedProcessesAndPorts": after_remote,
                },
            )
            if after_local or after_remote.strip():
                cleanup["residualSafetyFailure"] = {
                    "local": after_local,
                    "remote": after_remote,
                }
                result["ok"] = False
        except BaseException as exc:
            cleanup["afterSafetyError"] = str(exc)
            result["ok"] = False
        result["cleanup"] = cleanup
        write_json(config.evidence_root / "result.json", result)
        write_manifest(config.evidence_root)
