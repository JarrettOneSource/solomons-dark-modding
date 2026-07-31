from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
import math
from typing import Any


ROLES = ("host", "clientB")


def effective_wave(state: dict[str, Any]) -> int:
    # sd.waves is authority-owned and replicated. The native combat/world
    # counters remain peer-local and can advance independently while a client
    # is disconnected, so they are diagnostics rather than endurance progress.
    return int(state["wave"]["index"])


def terminal_game_over(state: dict[str, Any]) -> bool:
    terminal = state["gameOver"]
    command_epoch = int(terminal["commandEpoch"])
    return (
        command_epoch > 0
        and int(terminal["acceptedEpoch"]) == command_epoch
        and int(terminal["runNonce"]) > 0
        and int(terminal["authorityParticipantId"]) > 0
        and terminal["pendingDispatch"] is False
        and int(terminal["dispatchCount"]) == 1
    )


def is_capture_milestone(wave: int) -> bool:
    return wave in {1, 2, 3, 5} or (wave > 5 and wave % 5 == 0)


def _local_participant(state: dict[str, Any]) -> dict[str, Any] | None:
    owners = [
        row
        for row in state["multiplayer"]["participants"]
        if row["owner"]
    ]
    return owners[0] if len(owners) == 1 else None


def _local_life(state: dict[str, Any]) -> tuple[float, float]:
    participant = _local_participant(state)
    if participant is not None:
        return float(participant["hp"]), float(participant["life_max"])
    return float(state["player"]["hp"]), float(state["player"]["maxHp"])


@dataclass
class _Fighter:
    participant_id: int
    samples: int = 0
    deaths: int = 0
    respawns: int = 0
    furthest_wave: int = 0
    minimum_hp: float | None = None
    maximum_hp: float = 0.0
    distance_travelled: float = 0.0
    last_alive: bool | None = None
    death_in_progress: bool = False
    last_death_tick: int = 0
    last_position: tuple[float, float] | None = None
    last_wave: int = 0
    transitions: list[dict[str, Any]] = field(default_factory=list)


class FighterStatsTracker:
    def __init__(self, participant_ids: dict[str, int]) -> None:
        self.fighters = {
            role: _Fighter(participant_ids[role]) for role in ROLES
        }

    def observe(self, sample: dict[str, Any]) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        for role in ROLES:
            state = sample[role]
            fighter = self.fighters[role]
            hp, max_hp = _local_life(state)
            participant = _local_participant(state)
            death_tick = (
                int(participant["death_presentation_tick"])
                if participant is not None
                else 0
            )
            wave = effective_wave(state)
            alive = math.isfinite(hp) and hp > 0.0
            fighter.samples += 1
            fighter.furthest_wave = max(fighter.furthest_wave, wave)
            fighter.maximum_hp = max(fighter.maximum_hp, max_hp, hp)
            if math.isfinite(hp):
                fighter.minimum_hp = (
                    hp
                    if fighter.minimum_hp is None
                    else min(fighter.minimum_hp, hp)
                )
            death_started = (
                not fighter.death_in_progress
                and (
                    (fighter.last_alive is True and not alive)
                    or (fighter.last_death_tick == 0 and death_tick > 0)
                )
            )
            if death_started:
                fighter.deaths += 1
                fighter.death_in_progress = True
                event = {
                    "event": "death",
                    "role": role,
                    "wave": wave,
                    "hp": hp,
                    "elapsedSeconds": sample["elapsedSeconds"],
                    "utcNanoseconds": sample["utcNanoseconds"],
                    "deathPresentationTick": death_tick,
                }
                fighter.transitions.append(event)
                events.append(event)
            elif fighter.death_in_progress and alive and death_tick == 0:
                fighter.respawns += 1
                fighter.death_in_progress = False
                event = {
                    "event": "respawn",
                    "role": role,
                    "wave": wave,
                    "hp": hp,
                    "elapsedSeconds": sample["elapsedSeconds"],
                    "utcNanoseconds": sample["utcNanoseconds"],
                }
                fighter.transitions.append(event)
                events.append(event)
            fighter.last_alive = alive
            fighter.last_death_tick = death_tick

            player = state["player"]
            position = (float(player["x"]), float(player["y"]))
            if (
                player["valid"]
                and fighter.last_position is not None
                and fighter.last_wave == wave
            ):
                displacement = math.dist(fighter.last_position, position)
                if math.isfinite(displacement) and displacement <= 250.0:
                    fighter.distance_travelled += displacement
            fighter.last_position = position if player["valid"] else None
            fighter.last_wave = wave
        return events

    def result(
        self,
        enemy_rows: list[dict[str, Any]],
        player_rows: list[dict[str, Any]],
    ) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for role, fighter in self.fighters.items():
            dealt = [
                row
                for row in enemy_rows
                if int(row["sourceParticipantId"]) == fighter.participant_id
                and float(row["damage"]) > 0.0
            ]
            taken = [
                row
                for row in player_rows
                if int(row["targetParticipantId"]) == fighter.participant_id
                and float(row["damage"]) > 0.0
            ]
            result[role] = {
                "participantId": fighter.participant_id,
                "samples": fighter.samples,
                "furthestWave": fighter.furthest_wave,
                "deaths": fighter.deaths,
                "respawns": fighter.respawns,
                "minimumHp": fighter.minimum_hp,
                "maximumHp": fighter.maximum_hp,
                "distanceTravelled": fighter.distance_travelled,
                "damageDealt": sum(float(row["damage"]) for row in dealt),
                "damageDealtEdges": len(dealt),
                "damageTaken": sum(float(row["damage"]) for row in taken),
                "damageTakenEdges": len(taken),
                "transitions": fighter.transitions,
            }
        return result


@dataclass
class _ActiveAnomaly:
    started_elapsed: float
    evidence: dict[str, Any]
    finding: dict[str, Any] | None = None


class EnduranceAnomalyMonitor:
    _THRESHOLDS = {
        "wave-divergence": 10.0,
        "scene-divergence": 10.0,
        "terminal-divergence": 10.0,
        "transport-not-ready": 5.0,
        "packet-stall": 0.0,
        "client-materialization-loss": 8.0,
        "host-bot-not-driving": 5.0,
        "clientB-bot-not-driving": 5.0,
        "host-bot-think-stall": 0.0,
        "clientB-bot-think-stall": 0.0,
        "host-bot-idle": 0.0,
        "clientB-bot-idle": 0.0,
        "host-bot-stuck": 0.0,
        "clientB-bot-stuck": 0.0,
        "host-bot-oscillation": 0.0,
        "clientB-bot-oscillation": 0.0,
        "host-bot-no-damage-progress": 0.0,
        "clientB-bot-no-damage-progress": 0.0,
        "steam-send-failure": 0.0,
    }

    def __init__(self) -> None:
        self.active: dict[str, _ActiveAnomaly] = {}
        self.findings: list[dict[str, Any]] = []
        self.last_packets: dict[str, int] = {}
        self.last_packet_progress_elapsed = {
            "hostSent": 0.0,
            "hostReceived": 0.0,
            "clientBSent": 0.0,
            "clientBReceived": 0.0,
        }
        self.last_thinks = {role: 0 for role in ROLES}
        self.last_think_progress_elapsed = {role: 0.0 for role in ROLES}
        self.last_casts = {role: 0 for role in ROLES}
        self.initialized_roles: set[str] = set()
        self.last_positions: dict[str, tuple[float, float] | None] = {
            role: None for role in ROLES
        }
        self.last_activity_elapsed = {role: 0.0 for role in ROLES}
        self.last_motion_elapsed = {role: 0.0 for role in ROLES}
        self.motion_windows: dict[
            str, deque[tuple[float, float, float, int]]
        ] = {role: deque() for role in ROLES}
        self.last_enemy_wave = {role: 0 for role in ROLES}
        self.last_enemy_count = {role: 0 for role in ROLES}
        self.last_enemy_hp = {role: 0.0 for role in ROLES}
        self.last_enemy_progress_elapsed = {role: 0.0 for role in ROLES}
        self.casts_at_enemy_progress = {role: 0 for role in ROLES}

    @staticmethod
    def _living_enemies(state: dict[str, Any]) -> int:
        return sum(
            1
            for enemy in state["nativeEnemies"]
            if not enemy["dead"] and float(enemy["hp"]) > 0.0
        )

    @staticmethod
    def _living_replicas(state: dict[str, Any]) -> int:
        return sum(
            1
            for enemy in state["replicatedEnemies"]
            if not enemy["dead"] and float(enemy["hp"]) > 0.0
        )

    @staticmethod
    def _living_enemy_hp(state: dict[str, Any]) -> float:
        return sum(
            float(enemy["hp"])
            for enemy in state["nativeEnemies"]
            if not enemy["dead"] and float(enemy["hp"]) > 0.0
        )

    def observe(
        self,
        sample: dict[str, Any],
        bots: dict[str, dict[str, Any]],
        driving: dict[str, bool],
    ) -> list[dict[str, Any]]:
        elapsed = float(sample["elapsedSeconds"])
        host = sample["host"]
        client = sample["clientB"]
        host_wave = effective_wave(host)
        client_wave = effective_wave(client)
        host_terminal = terminal_game_over(host)
        client_terminal = terminal_game_over(client)
        host_hp, _ = _local_life(host)
        client_hp, _ = _local_life(client)
        host_enemies = self._living_enemies(host)
        client_enemies = self._living_enemies(client)

        packets = {
            "hostSent": int(host["multiplayer"]["packetsSent"]),
            "hostReceived": int(host["multiplayer"]["packetsReceived"]),
            "clientBSent": int(client["multiplayer"]["packetsSent"]),
            "clientBReceived": int(client["multiplayer"]["packetsReceived"]),
        }
        for counter, value in packets.items():
            if counter not in self.last_packets or value != self.last_packets[counter]:
                self.last_packets[counter] = value
                self.last_packet_progress_elapsed[counter] = elapsed
        receive_stalls = {
            role: elapsed - self.last_packet_progress_elapsed[counter]
            for role, counter in (
                ("host", "hostReceived"),
                ("clientB", "clientBReceived"),
            )
        }

        conditions: dict[str, tuple[bool, dict[str, Any]]] = {
            "wave-divergence": (
                abs(host_wave - client_wave) > 1,
                {"hostWave": host_wave, "clientBWave": client_wave},
            ),
            "scene-divergence": (
                host["scene"]["name"] != client["scene"]["name"]
                and not host_terminal
                and not client_terminal,
                {
                    "hostScene": host["scene"]["name"],
                    "clientBScene": client["scene"]["name"],
                },
            ),
            "terminal-divergence": (
                host_terminal != client_terminal,
                {
                    "hostTerminal": host_terminal,
                    "clientBTerminal": client_terminal,
                },
            ),
            "transport-not-ready": (
                (
                    not host["multiplayer"]["transportReady"]
                    or not client["multiplayer"]["transportReady"]
                )
                and not (host_terminal and client_terminal),
                {
                    "hostReady": host["multiplayer"]["transportReady"],
                    "clientBReady": client["multiplayer"]["transportReady"],
                    "hostStatus": host["multiplayer"]["sessionStatus"],
                    "clientBStatus": client["multiplayer"]["sessionStatus"],
                },
            ),
            "packet-stall": (
                max(receive_stalls.values()) >= 30.0
                and host["scene"]["name"] == "testrun"
                and client["scene"]["name"] == "testrun",
                {
                    "packets": packets,
                    "secondsWithoutReceiveProgress": receive_stalls,
                },
            ),
            "client-materialization-loss": (
                host_enemies > 0
                and self._living_replicas(client) == 0
                and client_enemies == 0,
                {
                    "hostLivingEnemies": host_enemies,
                    "clientBLivingReplicas": self._living_replicas(client),
                    "clientBNativeEnemies": client_enemies,
                },
            ),
            "steam-send-failure": (
                any(
                    int(state["multiplayer"][key]) > 0
                    for state in (host, client)
                    for key in (
                        "steamSendFailures",
                        "steamReliableSendFailures",
                    )
                ),
                {
                    "hostFailures": host["multiplayer"]["steamSendFailures"],
                    "hostReliableFailures": host["multiplayer"]
                    ["steamReliableSendFailures"],
                    "clientBFailures": client["multiplayer"]
                    ["steamSendFailures"],
                    "clientBReliableFailures": client["multiplayer"]
                    ["steamReliableSendFailures"],
                    "hostLastResult": host["multiplayer"]
                    ["lastSteamSendFailureResult"],
                    "clientBLastResult": client["multiplayer"]
                    ["lastSteamSendFailureResult"],
                },
            ),
        }

        for role, state, hp, enemies in (
            ("host", host, host_hp, host_enemies),
            ("clientB", client, client_hp, client_enemies),
        ):
            bot = bots[role]
            if role not in self.initialized_roles:
                self.initialized_roles.add(role)
                self.last_thinks[role] = int(
                    bot.get("brain.think_count", 0)
                )
                self.last_casts[role] = int(
                    bot.get("brain.cast_accepted", 0)
                )
                self.last_think_progress_elapsed[role] = elapsed
                self.last_activity_elapsed[role] = elapsed
                self.last_motion_elapsed[role] = elapsed
            combat_relevant = (
                hp > 0.0
                and enemies > 0
                and state["scene"]["name"] == "testrun"
            )
            conditions[f"{role}-bot-not-driving"] = (
                combat_relevant and not driving[role],
                {
                    "hp": hp,
                    "livingEnemies": enemies,
                    "bot": bot,
                },
            )
            thinks = int(bot.get("brain.think_count", 0))
            if thinks != self.last_thinks[role] or not combat_relevant:
                self.last_thinks[role] = thinks
                self.last_think_progress_elapsed[role] = elapsed
            conditions[f"{role}-bot-think-stall"] = (
                combat_relevant
                and driving[role]
                and elapsed - self.last_think_progress_elapsed[role] >= 15.0,
                {
                    "hp": hp,
                    "livingEnemies": enemies,
                    "thinkCount": thinks,
                },
            )
            casts = int(bot.get("brain.cast_accepted", 0))
            enemy_hp = self._living_enemy_hp(state)
            wave = effective_wave(state)
            enemy_progress = (
                role not in self.initialized_roles
                or wave != self.last_enemy_wave[role]
                or enemies > self.last_enemy_count[role]
                or enemy_hp > self.last_enemy_hp[role] + 0.0005
                or enemies < self.last_enemy_count[role]
                or enemy_hp < self.last_enemy_hp[role] - 0.0005
            )
            if enemy_progress or not combat_relevant:
                self.last_enemy_progress_elapsed[role] = elapsed
                self.casts_at_enemy_progress[role] = casts
            self.last_enemy_wave[role] = wave
            self.last_enemy_count[role] = enemies
            self.last_enemy_hp[role] = enemy_hp
            player = state["player"]
            position = (float(player["x"]), float(player["y"]))
            previous = self.last_positions[role]
            displacement = (
                math.dist(previous, position)
                if previous is not None and player["valid"]
                else 0.0
            )
            if displacement >= 2.0:
                self.last_motion_elapsed[role] = elapsed
            if displacement >= 2.0 or casts != self.last_casts[role]:
                self.last_activity_elapsed[role] = elapsed
            if not combat_relevant:
                self.last_activity_elapsed[role] = elapsed
                self.last_motion_elapsed[role] = elapsed
                self.motion_windows[role].clear()
            self.last_positions[role] = position if player["valid"] else None
            self.last_casts[role] = casts

            move_x = float(
                bot.get("takeover.control_brain_move_x", 0.0)
            )
            move_y = float(
                bot.get("takeover.control_brain_move_y", 0.0)
            )
            target_distance = float(bot.get("brain.target_distance", 0.0))
            movement_requested = math.hypot(move_x, move_y) >= 0.3
            conditions[f"{role}-bot-idle"] = (
                combat_relevant
                and driving[role]
                and elapsed - self.last_activity_elapsed[role] >= 20.0,
                {
                    "hp": hp,
                    "livingEnemies": enemies,
                    "secondsWithoutMovementOrCast": (
                        elapsed - self.last_activity_elapsed[role]
                    ),
                    "targetDistance": target_distance,
                    "castAccepted": casts,
                },
            )
            conditions[f"{role}-bot-stuck"] = (
                combat_relevant
                and driving[role]
                and movement_requested
                and target_distance >= 150.0
                and elapsed - self.last_motion_elapsed[role] >= 12.0,
                {
                    "hp": hp,
                    "livingEnemies": enemies,
                    "secondsWithoutMotion": (
                        elapsed - self.last_motion_elapsed[role]
                    ),
                    "targetDistance": target_distance,
                    "requestedMovement": [move_x, move_y],
                },
            )
            casts_without_damage = max(
                casts - self.casts_at_enemy_progress[role],
                0,
            )
            seconds_without_damage = (
                elapsed - self.last_enemy_progress_elapsed[role]
            )
            conditions[f"{role}-bot-no-damage-progress"] = (
                combat_relevant
                and driving[role]
                and seconds_without_damage >= 60.0
                and casts_without_damage >= 8,
                {
                    "hp": hp,
                    "wave": wave,
                    "livingEnemies": enemies,
                    "livingEnemyHp": enemy_hp,
                    "secondsWithoutEnemyHpProgress": seconds_without_damage,
                    "castsWithoutEnemyHpProgress": casts_without_damage,
                    "targetDistance": target_distance,
                    "targetNetworkActorId": int(
                        bot.get("brain.target_network_actor_id", 0)
                    ),
                    "mode": str(bot.get("brain.mode", "")),
                },
            )

            window = self.motion_windows[role]
            if combat_relevant and player["valid"]:
                window.append((elapsed, position[0], position[1], casts))
                while window and elapsed - window[0][0] > 15.0:
                    window.popleft()
            oscillating = False
            oscillation_evidence: dict[str, Any] = {}
            if len(window) >= 5 and elapsed - window[0][0] >= 12.0:
                travelled = sum(
                    math.dist(
                        (before[1], before[2]),
                        (after[1], after[2]),
                    )
                    for before, after in zip(window, list(window)[1:])
                )
                net = math.dist(
                    (window[0][1], window[0][2]),
                    (window[-1][1], window[-1][2]),
                )
                cast_progress = window[-1][3] - window[0][3]
                oscillating = (
                    driving[role]
                    and target_distance >= 150.0
                    and travelled >= 80.0
                    and net <= 12.0
                    and cast_progress == 0
                )
                oscillation_evidence = {
                    "windowSeconds": window[-1][0] - window[0][0],
                    "travelled": travelled,
                    "netDisplacement": net,
                    "targetDistance": target_distance,
                    "castProgress": cast_progress,
                }
            conditions[f"{role}-bot-oscillation"] = (
                oscillating,
                oscillation_evidence,
            )

        emitted: list[dict[str, Any]] = []
        for kind, (present, evidence) in conditions.items():
            active = self.active.get(kind)
            if not present:
                if active is not None and active.finding is not None:
                    active.finding["resolvedElapsedSeconds"] = elapsed
                    active.finding["finalEvidence"] = active.evidence
                self.active.pop(kind, None)
                continue
            if active is None:
                active = _ActiveAnomaly(elapsed, evidence)
                self.active[kind] = active
            else:
                active.evidence = evidence
            threshold = self._THRESHOLDS[kind]
            if (
                active.finding is None
                and elapsed - active.started_elapsed >= threshold
            ):
                finding = {
                    "id": f"F{len(self.findings) + 1:03d}",
                    "kind": kind,
                    "detectedElapsedSeconds": elapsed,
                    "startedElapsedSeconds": active.started_elapsed,
                    "evidence": evidence,
                }
                active.finding = finding
                self.findings.append(finding)
                emitted.append(finding)
        return emitted

    def finish(self, elapsed: float) -> list[dict[str, Any]]:
        for active in self.active.values():
            if active.finding is not None:
                active.finding.setdefault("ongoingAtEnd", True)
                active.finding["finalElapsedSeconds"] = elapsed
                active.finding["finalEvidence"] = active.evidence
        return self.findings
