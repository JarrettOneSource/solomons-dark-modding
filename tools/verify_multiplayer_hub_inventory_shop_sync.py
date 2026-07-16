#!/usr/bin/env python3
"""Verify Luthacus storage preserves participant-owned inventory boundaries."""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path
from typing import Any, Callable

from verify_local_multiplayer_sync import (
    CLIENT_ID,
    CLIENT_PIPE,
    HOST_ID,
    HOST_PIPE,
    ROOT,
    VerifyFailure,
    disable_bots,
    launch_pair,
    place_player,
    stop_games,
    wait_for_both_hub_settled,
)
from verify_multiplayer_inventory_audit import (
    capture,
    find_participant,
    item_rows,
)


OUTPUT = ROOT / "runtime/multiplayer_hub_inventory_shop_sync.json"
CLICK_WINDOW = ROOT / "scripts/click_window.py"
SEND_WINDOW_KEYS = ROOT / "scripts/send_window_keys.py"
POTION_TYPE_ID = 0x1B59
PLACEHOLDER_TYPE_ID = 0x1B58


def windows_path(path: Path) -> str:
    completed = subprocess.run(
        ["wslpath", "-w", str(path.resolve())],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=5.0,
        check=False,
    )
    if completed.returncode != 0 or not completed.stdout.strip():
        raise VerifyFailure(f"could not convert Windows path {path}: {completed.stdout}")
    return completed.stdout.strip()


def run_windows_python(script: Path, arguments: list[str], timeout: float = 10.0) -> str:
    command = subprocess.list2cmdline(["py", "-3", windows_path(script), *arguments])
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-Command", command],
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        check=False,
    )
    if completed.returncode != 0:
        raise VerifyFailure(
            f"Windows UI helper failed ({completed.returncode}): {command}\n{completed.stdout}"
        )
    return completed.stdout.strip()


def hold_real_key(pid: int, key: str, hold_ms: int) -> str:
    return run_windows_python(
        SEND_WINDOW_KEYS,
        [
            "--pid", str(pid),
            "--activate",
            "--activation-delay-ms", "300",
            "--hold-ms", str(hold_ms),
            "--post-delay-ms", "150",
            key,
        ],
    )


def click_relative(pid: int, x: float, y: float) -> str:
    return run_windows_python(
        CLICK_WINDOW,
        [
            "--pid", str(pid),
            "--relative",
            "--x", str(x),
            "--y", str(y),
            "--activate",
            "--activation-delay-ms", "250",
            "--post-delay-ms", "200",
            "--hold-ms", "90",
            "--button", "left",
            "--global-only",
        ],
    )


def drag_relative(
    pid: int,
    source_x: float,
    source_y: float,
    destination_x: float,
    destination_y: float,
) -> str:
    return run_windows_python(
        CLICK_WINDOW,
        [
            "--pid", str(pid),
            "--relative",
            "--x", str(source_x),
            "--y", str(source_y),
            "--drag-x", str(destination_x),
            "--drag-y", str(destination_y),
            "--activate",
            "--activation-delay-ms", "250",
            "--post-delay-ms", "750",
            "--hold-ms", "600",
            "--button", "left",
            "--global-only",
        ],
    )


def settle_mouse_release() -> str:
    output = run_windows_python(
        CLICK_WINDOW,
        ["--release-only", "--button", "left"],
        timeout=5.0,
    )
    time.sleep(1.0)
    return output


def semantic_items(rows: list[dict[str, Any]]) -> list[tuple[int, int, int, int]]:
    return sorted(
        (
            int(row["type_id"]),
            int(row["recipe_uid"]),
            int(row["slot"]),
            int(row["stack_count"]),
        )
        for row in rows
    )


def local_inventory(values: dict[str, str]) -> dict[str, Any]:
    rows = item_rows(values)
    return {
        "raw_item_count": int(values.get("inventory.raw_item_count", "0"), 0),
        "item_count": int(values.get("inventory.item_count", "0"), 0),
        "enumerated_item_count": int(
            values.get("inventory.enumerated_item_count", "0"), 0
        ),
        "truncated": values.get("inventory.truncated") == "true",
        "items": rows,
        "semantic_items": semantic_items(rows),
    }


def participant_inventory(values: dict[str, str], participant_id: int) -> dict[str, Any]:
    row = find_participant(values, participant_id)
    if row is None:
        raise VerifyFailure(f"participant 0x{participant_id:X} is absent")
    return {
        "participant_id": participant_id,
        "revision": row["inventory_revision"],
        "item_count": row["inventory_item_count"],
        "item_total_count": row["inventory_item_total_count"],
        "truncated": row["inventory_truncated"],
        "items": row["inventory_items"],
        "semantic_items": semantic_items(row["inventory_items"]),
    }


def snapshot() -> dict[str, Any]:
    host = capture(HOST_PIPE)
    client = capture(CLIENT_PIPE)
    return {
        "host_local": local_inventory(host),
        "client_local": local_inventory(client),
        "host_view_client": participant_inventory(host, CLIENT_ID),
        "client_view_host": participant_inventory(client, HOST_ID),
    }


def assert_no_placeholders(label: str, inventory: dict[str, Any]) -> None:
    placeholders = [
        row for row in inventory["items"] if row["type_id"] == PLACEHOLDER_TYPE_ID
    ]
    if placeholders:
        raise VerifyFailure(f"{label} exposed native grid placeholders: {placeholders}")
    if inventory["truncated"]:
        raise VerifyFailure(f"{label} real-item snapshot was truncated: {inventory}")
    if inventory["item_count"] != len(inventory["items"]):
        raise VerifyFailure(f"{label} item count differs from real rows: {inventory}")


def assert_ledger_matches_local(
    label: str,
    local: dict[str, Any],
    *views: dict[str, Any],
) -> None:
    for view in views:
        if view["truncated"]:
            raise VerifyFailure(f"{label} replicated inventory was truncated: {view}")
        if view["item_total_count"] != local["item_count"]:
            raise VerifyFailure(f"{label} replicated total differs from native: {view}")
        if view["semantic_items"] != local["semantic_items"]:
            raise VerifyFailure(
                f"{label} replicated rows differ from native: local={local} view={view}"
            )


def wait_for(
    description: str,
    predicate: Callable[[dict[str, Any]], None],
    timeout: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    last: dict[str, Any] = {}
    last_error = ""
    while time.monotonic() < deadline:
        try:
            last = snapshot()
            predicate(last)
            return last
        except Exception as exc:
            last_error = str(exc)
            time.sleep(0.2)
    raise VerifyFailure(
        f"{description} did not converge: last_error={last_error} last={last}"
    )


def assert_baseline(current: dict[str, Any]) -> None:
    for label in ("host_local", "client_local"):
        inventory = current[label]
        assert_no_placeholders(label, inventory)
        if inventory["item_count"] < 2:
            raise VerifyFailure(f"{label} lacks starter potions: {inventory}")
        potion_slots = {
            row["slot"] for row in inventory["items"] if row["type_id"] == POTION_TYPE_ID
        }
        if not {0, 1}.issubset(potion_slots):
            raise VerifyFailure(f"{label} lacks potion slots zero and one: {inventory}")
    assert_ledger_matches_local(
        "host",
        current["host_local"],
        current["client_view_host"],
    )
    assert_ledger_matches_local(
        "client",
        current["client_local"],
        current["host_view_client"],
    )


def open_luthacus_inventory(host_pid: int) -> dict[str, Any]:
    placement = place_player(HOST_PIPE, 1635.0, 449.5, 90.0)
    movement = hold_real_key(host_pid, "D", 900)
    time.sleep(0.8)
    skip = click_relative(host_pid, 0.50, 0.46)
    time.sleep(0.7)
    examine = click_relative(host_pid, 0.50, 0.26)
    time.sleep(1.2)
    return {
        "placement": placement,
        "movement": movement,
        "skip": skip,
        "examine_items": examine,
    }


def run(args: argparse.Namespace, result: dict[str, Any]) -> dict[str, Any]:
    stop_games()
    launch = launch_pair(allow_focus_steal=True)
    result["launch"] = launch
    host_pid = int(launch["hostProcessId"])
    disable_bots()
    wait_for_both_hub_settled()

    baseline = wait_for("baseline inventory", assert_baseline, args.timeout)
    result["baseline"] = baseline
    baseline_host_items = baseline["host_local"]["semantic_items"]
    baseline_client_items = baseline["client_local"]["semantic_items"]
    baseline_revision = baseline["client_view_host"]["revision"]

    result["open_inventory"] = open_luthacus_inventory(host_pid)
    result["opened"] = snapshot()

    result["drag_to_private_storage"] = drag_relative(
        host_pid, 0.04, 0.60, 0.36, 0.10
    )
    result["outbound_mouse_release"] = settle_mouse_release()

    def outbound(current: dict[str, Any]) -> None:
        host = current["host_local"]
        client = current["client_local"]
        assert_no_placeholders("host outbound", host)
        if host["item_count"] != len(baseline_host_items) - 1:
            raise VerifyFailure(f"host item did not enter private storage: {host}")
        if client["semantic_items"] != baseline_client_items:
            raise VerifyFailure(f"client private inventory changed with host storage: {client}")
        assert_ledger_matches_local(
            "host outbound",
            host,
            current["client_view_host"],
        )
        assert_ledger_matches_local(
            "client outbound",
            client,
            current["host_view_client"],
        )
        if current["client_view_host"]["revision"] <= baseline_revision:
            raise VerifyFailure("host inventory revision did not advance on storage transfer")

    stored = wait_for("host private-storage transfer", outbound, args.timeout)
    result["stored"] = stored
    stored_revision = stored["client_view_host"]["revision"]
    time.sleep(1.0)

    result["drag_back_to_backpack"] = drag_relative(
        host_pid, 0.36, 0.10, 0.04, 0.61
    )
    result["return_mouse_release"] = settle_mouse_release()

    def restored(current: dict[str, Any]) -> None:
        host = current["host_local"]
        client = current["client_local"]
        assert_no_placeholders("host restored", host)
        if host["semantic_items"] != baseline_host_items:
            raise VerifyFailure(f"host backpack did not restore exact items: {host}")
        if host["raw_item_count"] <= host["item_count"] or host["raw_item_count"] <= 64:
            raise VerifyFailure(
                f"stock placeholder-heavy list was not exercised: {host}"
            )
        if client["semantic_items"] != baseline_client_items:
            raise VerifyFailure(f"client private inventory changed on host return: {client}")
        assert_ledger_matches_local(
            "host restored",
            host,
            current["client_view_host"],
        )
        assert_ledger_matches_local(
            "client restored",
            client,
            current["host_view_client"],
        )
        if current["client_view_host"]["revision"] <= stored_revision:
            raise VerifyFailure("host inventory revision did not advance on storage return")

    result["restored"] = wait_for(
        "host private-storage return and placeholder filtering",
        restored,
        args.timeout,
    )
    result["ok"] = True
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--keep-open", action="store_true")
    args = parser.parse_args()

    result: dict[str, Any] = {"ok": False}
    try:
        result = run(args, result)
        return_code = 0
    except Exception as exc:
        result["error"] = str(exc)
        return_code = 1
    finally:
        OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        OUTPUT.write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
        print(json.dumps({
            "ok": result.get("ok", False),
            "error": result.get("error", ""),
            "output": str(OUTPUT),
        }, indent=2, sort_keys=True))
        if not args.keep_open:
            stop_games()
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
