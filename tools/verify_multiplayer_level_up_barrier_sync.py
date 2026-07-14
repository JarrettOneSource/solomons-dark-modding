#!/usr/bin/env python3
"""Verify all-player level-up pause, waiting UI, resume, and timeout auto-pick."""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path
from typing import Any

from verify_local_multiplayer_sync import (
    CLIENT_ID,
    CLIENT_NAME,
    CLIENT_PIPE,
    HOST_ID,
    HOST_NAME,
    HOST_PIPE,
    VerifyFailure,
    disable_bots,
    launch_pair,
    parse_int_text,
    start_host_testrun_and_wait_for_clients,
    stop_games,
    wait_for_remote,
)
from verify_multiplayer_level_up_offer_sync import (
    capture,
    choose_client_option,
    choose_host_option,
    publish_barrier_offer,
    query_progression_entry,
    query_progression_stats,
    wait_for_choice_result,
    wait_for_client_offer,
    wait_for_host_offer,
    wait_for_waiting_ids,
)
from verify_multiplayer_primary_kill_stress import set_manual_spawner_test_mode


ROOT = Path(__file__).resolve().parent.parent
RUNTIME_OUTPUT = ROOT / "runtime" / "multiplayer_level_up_barrier_sync.json"


def next_shared_level() -> tuple[int, int, dict[str, Any]]:
    host = query_progression_stats(HOST_PIPE)
    client = query_progression_stats(CLIENT_PIPE)
    if not host["available"] or not client["available"]:
        raise VerifyFailure(
            f"local progression unavailable: host={host} client={client}"
        )
    level = max(host["level"], client["level"]) + 1
    experience = int(
        max(
            host["next_xp_threshold"],
            client["next_xp_threshold"],
            125.0,
        )
        + 10.0
    )
    return level, experience, {"host": host, "client": client}


def summarize_wait(snapshot: dict[str, str]) -> dict[str, Any]:
    waiting_count = parse_int_text(snapshot.get("wait.waiting_count"), 0)
    return {
        "valid": snapshot.get("wait.valid") == "true",
        "pause_active": snapshot.get("wait.pause_active") == "true",
        "timed_out": snapshot.get("wait.timed_out") == "true",
        "barrier_id": parse_int_text(snapshot.get("wait.barrier_id"), 0),
        "revision": parse_int_text(snapshot.get("wait.revision"), 0),
        "deadline_remaining_ms": parse_int_text(
            snapshot.get("wait.deadline_remaining_ms"),
            0,
        ),
        "waiting_count": waiting_count,
        "waiting_participant_ids": [
            parse_int_text(snapshot.get(f"wait.participant.{index}"), 0)
            for index in range(1, waiting_count + 1)
        ],
        "display_text": snapshot.get("wait.display_text", ""),
    }


def verify_normal_barrier(timeout: float) -> dict[str, Any]:
    level, experience, before = next_shared_level()
    publish = publish_barrier_offer(level, experience)
    host_offer = wait_for_host_offer(level, timeout)
    client_offer = wait_for_client_offer(level, timeout)
    active = wait_for_waiting_ids(
        {HOST_ID, CLIENT_ID},
        timeout,
        require_timed_out=False,
    )
    active_host = summarize_wait(active["host"])
    active_client = summarize_wait(active["client"])
    if not (
        0 < active_host["deadline_remaining_ms"] <= 60_000
        and 0 < active_client["deadline_remaining_ms"] <= 60_000
    ):
        raise VerifyFailure(
            f"normal barrier did not publish a live 60-second deadline: {active}"
        )

    host_choice = choose_host_option(host_offer["offer_id"], 1)
    host_result = wait_for_choice_result(
        host_offer["offer_id"],
        level,
        timeout,
        target_participant_id=HOST_ID,
    )
    if host_result["auto_picked"]:
        raise VerifyFailure(f"manual host choice was marked auto-picked: {host_result}")
    waiting = wait_for_waiting_ids(
        {CLIENT_ID},
        timeout,
        host_display_text="Waiting on 1 player",
        require_timed_out=False,
    )
    waiting_host = summarize_wait(waiting["host"])
    waiting_client = summarize_wait(waiting["client"])
    if waiting_client["display_text"] != "Choose your skill upgrade":
        raise VerifyFailure(
            "unresolved client did not retain its choice prompt while the host "
            f"waited: {waiting_client}"
        )

    client_choice = choose_client_option(client_offer["offer_id"], 1)
    client_result = wait_for_choice_result(
        client_offer["offer_id"],
        level,
        timeout,
        target_participant_id=CLIENT_ID,
    )
    if client_result["auto_picked"]:
        raise VerifyFailure(
            f"manual client choice was marked auto-picked: {client_result}"
        )
    resumed = wait_for_waiting_ids(
        set(),
        timeout,
        require_timed_out=False,
    )
    resumed_host = summarize_wait(resumed["host"])
    resumed_client = summarize_wait(resumed["client"])
    if resumed_host["display_text"] or resumed_client["display_text"]:
        raise VerifyFailure(
            "completed normal barrier retained level-up wait text: "
            f"host={resumed_host} client={resumed_client}"
        )
    if not (
        active_host["barrier_id"]
        == waiting_host["barrier_id"]
        == resumed_host["barrier_id"]
        == active_client["barrier_id"]
        == waiting_client["barrier_id"]
        == resumed_client["barrier_id"]
    ):
        raise VerifyFailure("normal barrier id diverged between stages or peers")
    if not (
        active_host["revision"]
        < waiting_host["revision"]
        < resumed_host["revision"]
    ):
        raise VerifyFailure(
            "normal barrier revision did not advance through pick/resume: "
            f"active={active_host} waiting={waiting_host} resumed={resumed_host}"
        )

    return {
        "level": level,
        "experience": experience,
        "progression_before": before,
        "publish": publish,
        "host_offer_id": host_offer["offer_id"],
        "client_offer_id": client_offer["offer_id"],
        "active": {"host": active_host, "client": active_client},
        "host_choice": host_choice,
        "host_result_option_id": host_result["result_option_id"],
        "waiting_for_client": {
            "host": waiting_host,
            "client": waiting_client,
        },
        "client_choice": client_choice,
        "client_result_option_id": client_result["result_option_id"],
        "resumed": {"host": resumed_host, "client": resumed_client},
    }


def wait_for_timeout_auto_pick(
    *,
    barrier_id: int,
    client_offer_id: int,
    timeout: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last_host: dict[str, str] = {}
    last_client: dict[str, str] = {}
    while time.monotonic() < deadline:
        last_host = capture(HOST_PIPE)
        last_client = capture(CLIENT_PIPE)
        snapshots = (last_host, last_client)
        if all(
            snapshot.get("wait.pause_active") == "false"
            and snapshot.get("wait.timed_out") == "true"
            and parse_int_text(snapshot.get("wait.waiting_count"), 0) == 0
            and parse_int_text(snapshot.get("wait.barrier_id"), 0) == barrier_id
            and parse_int_text(snapshot.get("result.offer_id"), 0)
            == client_offer_id
            and parse_int_text(snapshot.get("result.target"), 0) == CLIENT_ID
            and parse_int_text(snapshot.get("result.code"), 0) == 1
            and snapshot.get("result.auto_picked") == "true"
            for snapshot in snapshots
        ):
            return {
                "host": last_host,
                "client": last_client,
                "option_id": parse_int_text(
                    last_client.get("result.option_id"),
                    -1,
                ),
                "resulting_active": parse_int_text(
                    last_client.get("result.resulting_active"),
                    0,
                ),
            }
        time.sleep(0.1)
    raise VerifyFailure(
        "60-second level-up timeout did not auto-pick and resume both peers: "
        f"barrier_id={barrier_id} client_offer_id={client_offer_id} "
        f"last_host={last_host} last_client={last_client}"
    )


def verify_timeout_barrier(setup_timeout: float, auto_timeout: float) -> dict[str, Any]:
    level, experience, before = next_shared_level()
    started = time.monotonic()
    publish = publish_barrier_offer(level, experience)
    host_offer = wait_for_host_offer(level, setup_timeout)
    client_offer = wait_for_client_offer(level, setup_timeout)
    active = wait_for_waiting_ids(
        {HOST_ID, CLIENT_ID},
        setup_timeout,
        require_timed_out=False,
    )
    active_host = summarize_wait(active["host"])

    host_choice = choose_host_option(host_offer["offer_id"], 1)
    host_result = wait_for_choice_result(
        host_offer["offer_id"],
        level,
        setup_timeout,
        target_participant_id=HOST_ID,
    )
    waiting = wait_for_waiting_ids(
        {CLIENT_ID},
        setup_timeout,
        host_display_text="Waiting on 1 player",
        require_timed_out=False,
    )
    waiting_host = summarize_wait(waiting["host"])

    auto_result = wait_for_timeout_auto_pick(
        barrier_id=active_host["barrier_id"],
        client_offer_id=client_offer["offer_id"],
        timeout=auto_timeout,
    )
    elapsed = time.monotonic() - started
    if elapsed < 58.0:
        raise VerifyFailure(
            f"level-up timeout fired too early: elapsed={elapsed:.3f}s"
        )

    final_host = summarize_wait(auto_result["host"])
    final_client = summarize_wait(auto_result["client"])
    if final_host["display_text"] or final_client["display_text"]:
        raise VerifyFailure(
            "timeout resume retained level-up wait text: "
            f"host={final_host} client={final_client}"
        )
    if final_host["revision"] <= waiting_host["revision"]:
        raise VerifyFailure(
            "timeout final barrier revision did not advance: "
            f"waiting={waiting_host} final={final_host}"
        )

    option_id = auto_result["option_id"]
    host_remote_entry = query_progression_entry(
        HOST_PIPE,
        option_id=option_id,
        participant_id=CLIENT_ID,
    )
    client_local_entry = query_progression_entry(
        CLIENT_PIPE,
        option_id=option_id,
    )
    resulting_active = auto_result["resulting_active"]
    if not (
        host_remote_entry["available"]
        and client_local_entry["available"]
        and host_remote_entry["active"] >= resulting_active > 0
        and client_local_entry["active"] >= resulting_active
    ):
        raise VerifyFailure(
            "timeout auto-pick did not converge the selected upgrade natively: "
            f"resulting_active={resulting_active} "
            f"host_remote={host_remote_entry} client_local={client_local_entry}"
        )

    return {
        "level": level,
        "experience": experience,
        "elapsed_seconds": elapsed,
        "progression_before": before,
        "publish": publish,
        "host_offer_id": host_offer["offer_id"],
        "client_offer_id": client_offer["offer_id"],
        "active": active_host,
        "host_choice": host_choice,
        "host_result_option_id": host_result["result_option_id"],
        "waiting_for_client": waiting_host,
        "auto_result": {
            "option_id": option_id,
            "resulting_active": resulting_active,
            "host": final_host,
            "client": final_client,
        },
        "native_upgrade": {
            "host_remote_client": host_remote_entry,
            "client_local": client_local_entry,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--keep-open", action="store_true")
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--auto-timeout", type=float, default=75.0)
    args = parser.parse_args()

    output: dict[str, Any] = {"ok": False}
    try:
        stop_games()
        output["launch"] = launch_pair()
        disable_bots()
        output["hub_ready"] = {
            "host_observes_client": wait_for_remote(
                HOST_PIPE,
                CLIENT_ID,
                CLIENT_NAME,
                "hub",
            ),
            "client_observes_host": wait_for_remote(
                CLIENT_PIPE,
                HOST_ID,
                HOST_NAME,
                "hub",
            ),
        }
        output["manual_spawner_mode"] = {
            "host": set_manual_spawner_test_mode(HOST_PIPE, True),
            "client": set_manual_spawner_test_mode(CLIENT_PIPE, True),
        }
        output["run_entry"] = start_host_testrun_and_wait_for_clients(
            timeout=args.timeout
        )
        output["run_ready"] = {
            "host_observes_client": wait_for_remote(
                HOST_PIPE,
                CLIENT_ID,
                CLIENT_NAME,
                "testrun",
            ),
            "client_observes_host": wait_for_remote(
                CLIENT_PIPE,
                HOST_ID,
                HOST_NAME,
                "testrun",
            ),
        }
        output["normal_barrier"] = verify_normal_barrier(args.timeout)
        output["timeout_barrier"] = verify_timeout_barrier(
            args.timeout,
            args.auto_timeout,
        )
        output["ok"] = True
    except (VerifyFailure, subprocess.TimeoutExpired) as exc:
        output["error"] = str(exc)
    finally:
        if not args.keep_open:
            stop_games()

    RUNTIME_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    RUNTIME_OUTPUT.write_text(
        json.dumps(output, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    if args.json:
        print(json.dumps(output, indent=2, sort_keys=True))
    elif output["ok"]:
        timeout_result = output["timeout_barrier"]
        print(
            "level-up barrier sync ok: normal all-player resume; "
            f"timeout_auto_pick={timeout_result['elapsed_seconds']:.3f}s "
            f"option={timeout_result['auto_result']['option_id']}"
        )
    else:
        print(f"level-up barrier sync verifier failed: {output.get('error', '')}")
    return 0 if output["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
