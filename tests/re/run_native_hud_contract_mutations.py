#!/usr/bin/env python3
"""Mutation-test every G9 native HUD static contract claim family."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import shutil
from typing import Callable, Iterator

import static_re_native_hud_contracts as contracts
from static_re_contract_support import ROOT, StaticReTestFailure


TextMutator = Callable[[str], str]


@dataclass(frozen=True)
class Mutation:
    claim: str
    contract: str
    target: Path
    mutate: TextMutator
    expected_message: str


@dataclass(frozen=True)
class MutationResult:
    claim: str
    contract: str
    expected_message: str
    observed_message: str
    baseline_before: str
    baseline_after: str


def edit_json(mutator: Callable[[dict], None]) -> TextMutator:
    def mutate(text: str) -> str:
        payload = json.loads(text)
        mutator(payload)
        return json.dumps(payload, indent=2, sort_keys=True) + "\n"

    return mutate


def element(payload: dict, element_id: str) -> dict:
    matches = [
        row
        for row in payload["element_census"]["elements"]
        if row.get("id") == element_id
    ]
    if len(matches) != 1:
        raise RuntimeError(
            f"mutation setup cannot uniquely resolve element {element_id!r}: {len(matches)}"
        )
    return matches[0]


def visibility_row(payload: dict, state: str) -> dict:
    matches = [
        row
        for row in payload["visibility_contract"]["matrix"]
        if row.get("state") == state
    ]
    if len(matches) != 1:
        raise RuntimeError(
            f"mutation setup cannot uniquely resolve visibility state {state!r}: {len(matches)}"
        )
    return matches[0]


def replace_once(old: str, new: str) -> TextMutator:
    def mutate(text: str) -> str:
        if text.count(old) != 1:
            raise RuntimeError(
                f"mutation setup expected one source occurrence of {old!r}, found {text.count(old)}"
            )
        return text.replace(old, new, 1)

    return mutate


def set_census_count(payload: dict) -> None:
    payload["element_census"]["count"] = 25


def move_xp_track(payload: dict) -> None:
    element(payload, "progression.xp.track")["native_rect"][0] = 795.5


def swap_xp_atlas(payload: dict) -> None:
    element(payload, "progression.xp.track")["atlas_id"] = "UI.999"


def rename_shield_crop(payload: dict) -> None:
    matches = [
        row
        for row in payload["reference_crops"]
        if row.get("id") == "state.health.magic_shield_below_life"
    ]
    if len(matches) != 1:
        raise RuntimeError(
            "mutation setup cannot uniquely resolve the shield crossover crop"
        )
    matches[0]["id"] = "state.health.magic_shield_below_life_mutated"


def linearize_health(payload: dict) -> None:
    payload["behavior_contract"]["health_fill"]["function"] = (
        "visible_width_px = 100 * clamp(current / maximum, 0, 1)"
    )


def reverse_shield_order(payload: dict) -> None:
    rows = payload["behavior_contract"]["health_fill"]["magic_shield"][
        "observed_compositions"
    ]
    below = [
        row for row in rows if row["scenario"] == "magic_shield_below_health_fill"
    ]
    if len(below) != 1:
        raise RuntimeError(
            "mutation setup cannot uniquely resolve the below-life shield witness"
        )
    below[0]["shield_first_draw_order"] = 99


def widen_cooldown_segments(payload: dict) -> None:
    payload["behavior_contract"]["cooldown"]["segment_size_degrees"] = 90.0


def change_earth_increment(payload: dict) -> None:
    payload["behavior_contract"]["earth_charge"]["increment_per_fixed_tick"] = 0.0025


def restore_dead_hud(payload: dict) -> None:
    visibility_row(payload, "local_death")["stock_hud"] = (
        "all stock HUD elements remain visible"
    )


def include_self_ally(payload: dict) -> None:
    payload["visibility_contract"]["participant_count_rule"]["n_participants"] = (
        "n rows including local participant"
    )


def naively_shift_scaling(payload: dict) -> None:
    payload["scaling_contract"]["target_transform"]["center_x_delta_px"] = -200


def dirty_provenance(payload: dict) -> None:
    payload["header"]["worktree_dirty_at_capture_start"] = True


MUTATIONS = (
    Mutation(
        "semantic census count",
        "test_native_hud_element_census_and_rects_are_pinned",
        contracts.GOLDEN_PATH,
        edit_json(set_census_count),
        "HUD semantic census would no longer contain exactly the 26 reviewed elements",
    ),
    Mutation(
        "per-element native rect",
        "test_native_hud_element_census_and_rects_are_pinned",
        contracts.GOLDEN_PATH,
        edit_json(move_xp_track),
        "progression.xp.track would move from its native rect [794.5, 829.0, 806.5, 885.0]",
    ),
    Mutation(
        "per-element atlas id",
        "test_native_hud_element_census_and_rects_are_pinned",
        contracts.GOLDEN_PATH,
        edit_json(swap_xp_atlas),
        "progression.xp.track would select a different retail atlas record than UI.82",
    ),
    Mutation(
        "per-state visual crop",
        "test_native_hud_element_census_and_rects_are_pinned",
        contracts.GOLDEN_PATH,
        edit_json(rename_shield_crop),
        "HUD visual diffing would lose the shield/life draw-order crossover witness",
    ),
    Mutation(
        "squared health fill",
        "test_native_hud_fill_cooldown_charge_and_notification_behavior_are_pinned",
        contracts.GOLDEN_PATH,
        edit_json(linearize_health),
        "health fill would cease to use the retail squared current/max clip",
    ),
    Mutation(
        "shield shorter-first ordering",
        "test_native_hud_fill_cooldown_charge_and_notification_behavior_are_pinned",
        contracts.GOLDEN_PATH,
        edit_json(reverse_shield_order),
        "health layers would no longer draw shorter-first and longer-last across the crossover",
    ),
    Mutation(
        "cooldown 45-degree sectors",
        "test_native_hud_fill_cooldown_charge_and_notification_behavior_are_pinned",
        contracts.GOLDEN_PATH,
        edit_json(widen_cooldown_segments),
        "cooldown presentation would change the reviewed segment_size_degrees constant",
    ),
    Mutation(
        "G2 Earth charge increment",
        "test_native_hud_fill_cooldown_charge_and_notification_behavior_are_pinned",
        contracts.GOLDEN_PATH,
        edit_json(change_earth_increment),
        "Earth hold would gain a fabricated HUD meter or drift from the G2 float32 charge curve",
    ),
    Mutation(
        "death cursor-tail visibility",
        "test_native_hud_visibility_scaling_and_multiplayer_are_pinned",
        contracts.GOLDEN_PATH,
        edit_json(restore_dead_hud),
        "death visibility would restore stock HUD elements that retail skips",
    ),
    Mutation(
        "n-minus-one durable ally rows",
        "test_native_hud_visibility_scaling_and_multiplayer_are_pinned",
        contracts.GOLDEN_PATH,
        edit_json(include_self_ally),
        "ally rows would regress to self, duplicate, phantom, or nondeterministic participants",
    ),
    Mutation(
        "1280x800 center anchor",
        "test_native_hud_visibility_scaling_and_multiplayer_are_pinned",
        contracts.GOLDEN_PATH,
        edit_json(naively_shift_scaling),
        "1280x800 HUD would use naive uniform scaling instead of native center/top/bottom anchors",
    ),
    Mutation(
        "clean self-derived provenance",
        "test_native_hud_recorder_is_self_provenanced_settled_and_visual_diffable",
        contracts.GOLDEN_PATH,
        edit_json(dirty_provenance),
        "published HUD golden would come from an uncommitted source tree",
    ),
    Mutation(
        "40-sample settle floor",
        "test_native_hud_recorder_is_self_provenanced_settled_and_visual_diffable",
        contracts.RECORDER_PATH,
        replace_once("SETTLE_SAMPLE_FLOOR = 40", "SETTLE_SAMPLE_FLOOR = 39"),
        "HUD recorder could accept fewer than 40 consecutive structural samples",
    ),
    Mutation(
        "no caller-supplied provenance",
        "test_native_hud_recorder_is_self_provenanced_settled_and_visual_diffable",
        contracts.RECORDER_PATH,
        replace_once(
            '    parser.add_argument("--smoke", action="store_true")',
            '    parser.add_argument("--smoke", action="store_true")\n'
            '    parser.add_argument("--source-commit")',
        ),
        "HUD recorder would accept a caller-supplied provenance or uncontrolled capture parameter",
    ),
    Mutation(
        "duplicate lookup refusal",
        "test_native_hud_recorder_is_self_provenanced_settled_and_visual_diffable",
        contracts.RECORDER_PATH,
        replace_once("lookup is ambiguous", "lookup silently selected the first candidate"),
        "HUD recorder could silently choose between duplicate native candidates",
    ),
)


def clear_contract_bytecode() -> None:
    for directory in (
        ROOT / "tests/re/__pycache__",
        ROOT / "tools/__pycache__",
    ):
        if directory.is_dir():
            shutil.rmtree(directory)


@contextmanager
def active_mutation(mutation: Mutation) -> Iterator[None]:
    original_read = contracts._read  # noqa: SLF001 - intentional mutation seam.
    target = mutation.target.resolve()
    reached = False

    def mutated_read(path: Path) -> str:
        nonlocal reached
        text = original_read(path)
        if path.resolve() == target:
            reached = True
            return mutation.mutate(text)
        return text

    contracts._read = mutated_read  # type: ignore[assignment]  # noqa: SLF001
    try:
        yield
    finally:
        contracts._read = original_read  # type: ignore[assignment]  # noqa: SLF001
    if not reached:
        raise RuntimeError(
            f"mutation {mutation.claim!r} never reached {mutation.target}"
        )


def run_contract(contract_name: str) -> str:
    return str(getattr(contracts, contract_name)())


def run_mutation(mutation: Mutation) -> MutationResult:
    clear_contract_bytecode()
    baseline_before = run_contract(mutation.contract)
    observed = ""
    with active_mutation(mutation):
        clear_contract_bytecode()
        try:
            run_contract(mutation.contract)
        except StaticReTestFailure as exc:
            observed = str(exc)
        if not observed:
            raise RuntimeError(
                f"mutation {mutation.claim!r} failed to trip {mutation.contract}"
            )
        if observed != mutation.expected_message:
            raise RuntimeError(
                f"mutation {mutation.claim!r} tripped the wrong claim:\n"
                f"expected: {mutation.expected_message}\n"
                f"observed: {observed}"
            )
    clear_contract_bytecode()
    baseline_after = run_contract(mutation.contract)
    return MutationResult(
        claim=mutation.claim,
        contract=mutation.contract,
        expected_message=mutation.expected_message,
        observed_message=observed,
        baseline_before=baseline_before,
        baseline_after=baseline_after,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()

    results = []
    for index, mutation in enumerate(MUTATIONS, start=1):
        result = run_mutation(mutation)
        results.append(result)
        print(
            f"PASS {index:02d}/{len(MUTATIONS):02d} {result.claim}: "
            f"{result.observed_message}"
        )

    payload = {
        "schema": "solomon-dark-native-hud-contract-mutations-v1",
        "count": len(results),
        "results": [asdict(result) for result in results],
    }
    if args.json is not None:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    print(
        f"{len(results)}/{len(MUTATIONS)} HUD contract mutations tripped their named claim"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
