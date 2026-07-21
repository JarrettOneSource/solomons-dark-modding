"""Select stable, mutually observed pickup locations for live multiplayer tests."""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


PairCapture = dict[str, dict[str, str]]
ParticipantRow = dict[str, Any]


@dataclass(frozen=True)
class PickupGeometryRuntime:
    client_pipe: str
    client_participant_id: int
    capture_pair: Callable[[], PairCapture]
    find_participant: Callable[[dict[str, str], int], ParticipantRow | None]
    place_player: Callable[[str, float, float, float], dict[str, str]]
    snap_to_nav: Callable[[str, float, float], tuple[float, float]]


class PickupGeometryFailure(RuntimeError):
    pass


def _coordinate(values: dict[str, str], key: str) -> float:
    try:
        value = float(values.get(key, "nan"))
    except (TypeError, ValueError):
        value = math.nan
    return value


def _distance(ax: float, ay: float, bx: float, by: float) -> float:
    return math.hypot(ax - bx, ay - by)


def _settle_candidate(
    runtime: PickupGeometryRuntime,
    *,
    requested_x: float,
    requested_y: float,
    nav_x: float,
    nav_y: float,
    host_x: float,
    host_y: float,
    pickup_suppression_radius: float,
    settle_tolerance: float,
    settle_seconds: float,
    timeout: float,
) -> dict[str, Any] | None:
    placement = runtime.place_player(runtime.client_pipe, nav_x, nav_y, 90.0)
    deadline = time.monotonic() + timeout
    stable_since: float | None = None
    previous_position: tuple[float, float] | None = None

    while time.monotonic() < deadline:
        pair = runtime.capture_pair()
        local_x = _coordinate(pair["client"], "player.x")
        local_y = _coordinate(pair["client"], "player.y")
        host_participant = runtime.find_participant(
            pair["host"], runtime.client_participant_id
        )
        finite = math.isfinite(local_x) and math.isfinite(local_y)
        observer_agrees = (
            finite
            and host_participant is not None
            and _distance(
                local_x,
                local_y,
                float(host_participant["x"]),
                float(host_participant["y"]),
            )
            <= settle_tolerance
        )
        separated_from_host = (
            finite
            and _distance(local_x, local_y, host_x, host_y)
            > pickup_suppression_radius + 20.0
        )
        stationary = (
            finite
            and previous_position is not None
            and _distance(local_x, local_y, *previous_position)
            <= settle_tolerance
        )

        if observer_agrees and separated_from_host and stationary:
            now = time.monotonic()
            if stable_since is None:
                stable_since = now
            elif now - stable_since >= settle_seconds:
                return {
                    "requested_x": requested_x,
                    "requested_y": requested_y,
                    "nav_x": nav_x,
                    "nav_y": nav_y,
                    "snapped_x": local_x,
                    "snapped_y": local_y,
                    "place": placement,
                    "client_capture": pair["client"],
                    "host_capture": pair["host"],
                    "host_participant": host_participant,
                }
        else:
            stable_since = None

        if finite:
            previous_position = (local_x, local_y)
        time.sleep(0.1)

    return None


def select_reachable_spawn_point(
    runtime: PickupGeometryRuntime,
    *,
    pickup_suppression_radius: float,
    timeout: float,
    settle_tolerance: float = 3.0,
    settle_seconds: float = 0.4,
) -> dict[str, Any]:
    before = runtime.capture_pair()
    client_x = _coordinate(before["client"], "player.x")
    client_y = _coordinate(before["client"], "player.y")
    host_x = _coordinate(before["host"], "player.x")
    host_y = _coordinate(before["host"], "player.y")
    if not all(map(math.isfinite, (client_x, client_y, host_x, host_y))):
        raise PickupGeometryFailure(f"player positions unavailable: {before}")

    away_x = client_x - host_x
    away_y = client_y - host_y
    away_length = math.hypot(away_x, away_y)
    if away_length < 1.0:
        away_x, away_y, away_length = 1.0, 0.0, 1.0
    away_x /= away_length
    away_y /= away_length
    directions = (
        (away_x, away_y),
        (-away_y, away_x),
        (away_y, -away_x),
        (-away_x, -away_y),
    )

    attempts: list[dict[str, float]] = []
    deadline = time.monotonic() + timeout
    for radius in (440.0, 520.0, 600.0):
        for direction_x, direction_y in directions:
            if time.monotonic() >= deadline:
                break
            requested_x = client_x + direction_x * radius
            requested_y = client_y + direction_y * radius
            nav_x, nav_y = runtime.snap_to_nav(
                runtime.client_pipe, requested_x, requested_y
            )
            candidate = _settle_candidate(
                runtime,
                requested_x=requested_x,
                requested_y=requested_y,
                nav_x=nav_x,
                nav_y=nav_y,
                host_x=host_x,
                host_y=host_y,
                pickup_suppression_radius=pickup_suppression_radius,
                settle_tolerance=settle_tolerance,
                settle_seconds=settle_seconds,
                timeout=min(4.0, max(0.0, deadline - time.monotonic())),
            )
            if candidate is not None:
                candidate["client_distance"] = _distance(
                    client_x,
                    client_y,
                    candidate["snapped_x"],
                    candidate["snapped_y"],
                )
                candidate["host_distance"] = _distance(
                    host_x,
                    host_y,
                    candidate["snapped_x"],
                    candidate["snapped_y"],
                )
                return {"before": before, **candidate}
            attempts.append(
                {
                    "requested_x": requested_x,
                    "requested_y": requested_y,
                    "nav_x": nav_x,
                    "nav_y": nav_y,
                }
            )

    raise PickupGeometryFailure(
        "no stable reachable pickup spawn point separated from the host: "
        f"{attempts}"
    )
