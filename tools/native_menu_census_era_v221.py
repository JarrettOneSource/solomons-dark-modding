#!/usr/bin/env python3
"""Exact v2.21 disposition of the sealed post-v2.20 menu census."""

from __future__ import annotations

import copy
import hashlib
import json
from collections import Counter
from typing import Any


SCHEMA = "solomon-dark-native-menu-census-era-disposition-v221"
SETTLEMENT_SPEC = "2.21"
SEALED_CENSUS_SHA256 = (
    "b6d91abab8eaf67dfb9c4f92c688bf5ea027db8132e470c8fe4c763a6db08a72"
)
SEALED_OCCURRENCE_AUDIT_SHA256 = (
    "e327294f0aff85710e238dce6e0967afe0814a26908de3a0cfe8643d35e7dca2"
)
CLASS_F_WITNESS_AUDIT_SHA256 = (
    "66db25b623bdcf6ea82694e70a8ca662cc4a0567ceceb4b52f1eaaf0a46d6870"
)
CLASS_F_LAYOUTS = {
    "performance": ("settings_to_performance", 23),
    "profile-save-select": ("main_to_profile_select", 33),
}

CHOICE_LAYOUT_ID = "skill-picker"
CHOICE_SLOT_ID = "skill_picker.choice_slot.1"
CHOICE_MEMBER_KEY = "choice-slot:30-31"
CHOICE_ROWS = {
    "skill_picker.art.skills_84.1": (
        "3d925df7da100b9fd2336771e67cb0b11f9b43c74e7346f6d2752e178d43dcad"
    ),
    "skill_picker.art.skills_84.2": (
        "1bc7ef8cf3f065f0ee88d29035a692da25db994b0a23f6447233f885d74af70d"
    ),
}

CLASS_A_COUNTS = {
    "dark-cloud-login-settings": 26,
    "dark-cloud-menu": 40,
    "dark-cloud-options": 28,
    "dark-cloud-search": 45,
    "dark-cloud-sort": 28,
    "game-settings-dark-cloud": 33,
    "game-settings-title": 22,
    "hall-of-fame": 28,
    "map-picker": 1,
    "skill-picker": 10,
}
CLASS_B_COUNTS = {
    "dark-cloud-login-settings": 8,
    "dark-cloud-search": 2,
    "game-settings-dark-cloud": 6,
    "game-settings-gameplay": 6,
    "game-settings-title": 7,
    "hall-of-fame": 4,
    "map-picker": 5,
}
CLASS_A_MEMBER_SET_SHA256 = {
    "dark-cloud-login-settings": "f9b6a82e83985938a569336eaaf1b8321988417cacc6d41c6c806687545f58e8",
    "dark-cloud-menu": "a71e90b76daa470fc4a0c8d32ae53100f6113b8a3a96113ce735ed1f9ccd3873",
    "dark-cloud-options": "0c84136445c09516cfaf38753b03ac7273c0f4e2a54b64b5ff1884b8e1bdea49",
    "dark-cloud-search": "ea143d47121fa697122619f0548c95178d1f59a5780fb74763394c0f8ce3222b",
    "dark-cloud-sort": "7c2c7ebd2976163fa205e14eaea2fbffded2c19c82a946f703546b4692d19c00",
    "game-settings-dark-cloud": "3035cf202e6b0873942261f24e7511d8943ea080699558d0f4112255314dc196",
    "game-settings-title": "234d44934488ffb2544ad2d1b162b564fb4ba7004fa487ce98a5c2940ecb6ee8",
    "hall-of-fame": "5a1d626dc4c266d5ba9fb1444a78178f2528b010f85984d42e59b9fbbacd57c8",
    "map-picker": "fc5d68dc62de068945ec9720bf5a8e79d67d2cd731a0f9be59b274ae3497872f",
    "skill-picker": "107d71ad27ee0b6512136b39a11820ad697f28538f7dcb6c5e874cf7bed7f273",
}
CLASS_B_MEMBER_SET_SHA256 = {
    "dark-cloud-login-settings": "82ab499d870a8b137ce442028b3f74c411d0a77a448721b3f514184fd2bddf99",
    "dark-cloud-search": "76a4f0ec46f7a8b848d3b10c53d2a9468a93490816ab026a9b416c1087f4a6f0",
    "game-settings-dark-cloud": "a096c7b44caa5465747121a76d084ae94baa38854cd63cad9412b2653c2507f2",
    "game-settings-gameplay": "a096c7b44caa5465747121a76d084ae94baa38854cd63cad9412b2653c2507f2",
    "game-settings-title": "8df729edaab04be6a060f4274f27cfa182b3f656a898caf418c9b86ca159215d",
    "hall-of-fame": "4bab4e2874829dde46c27fcbab63199ca96f5cbbd752cb709e409b12c8553fe2",
    "map-picker": "53d5c50c28c12ea9c7155de6dd33296a2d12321da70fc0e969d3948d35d690d9",
}
GENERATION_LAYOUTS = {
    "dark-cloud-login-settings",
    "dark-cloud-menu",
    "dark-cloud-options",
    "dark-cloud-search",
    "dark-cloud-sort",
    "game-over",
    "game-settings-dark-cloud",
    "game-settings-title",
    "hall-of-fame",
    "map-picker",
    "performance",
    "profile-save-select",
    "skill-picker",
}
FIELD_CORRECTIONS = {
    ("dark-cloud-search", "screen_title"): ("", "Dark Cloud Search"),
    ("game-settings-dark-cloud", "screen_title"): ("", "GAME SETTINGS"),
    ("game-settings-gameplay", "screen_title"): ("", "GAME SETTINGS"),
    ("game-settings-title", "screen_title"): ("", "GAME SETTINGS"),
    ("hall-of-fame", "screen_title"): ("", "Hall of Fame"),
    ("dark-cloud-menu", "screen_id"): ("simple_menu", "dark_cloud_menu"),
}
GUARD_SUBSUMPTIONS = {
    ("dark-cloud-options", "dark_cloud_browser_chrome_supersession"),
    ("dark-cloud-sort", "dark_cloud_browser_chrome_supersession"),
    ("hall-of-fame", "dark_cloud_browser_chrome_supersession"),
    ("game-settings-dark-cloud", "dark_cloud_item_row_supersession"),
}
FORBIDDEN = [
    "member_filter",
    "count_tolerance",
    "partial_class_a_application",
    "single_instance_class_b_adoption",
    "unscoped_field_correction",
    "uncovered_guard_subsumption",
    "population_route_selection",
    "future_choice_slot_auto_extension",
]

CONTRACT_SCOPE_STOP = (
    "v2.21 census-era disposition contract changed its exact sealed scope"
)
CLASS_A_RESIDUAL_STOP = (
    "v2.21 census-era Class-A exact landed residual differs"
)
CLASS_A_OCCURRENCE_STOP = (
    "v2.21 census-era Class-A occurrence attestation found qualified presence"
)
CLASS_B_PAIR_STOP = (
    "v2.21 census-era Class-B member is not present in both qualified traces"
)
WRONG_SCOPE_STOP = (
    "v2.21 census-era disposition does not authorize another layout or member"
)
CHOICE_SLOT_STOP = (
    "v2.21 exact Skills.84 choice-slot reconciliation proof differs"
)
FIELD_CORRECTION_STOP = (
    "v2.21 exact census field correction differs or escaped its layout scope"
)
STALE_SCREEN_ID_STOP = (
    "v2.21 dark-cloud-menu screen-id correction left a stale aggregate reference"
)
PAUSE_EQUIVALENCE_STOP = (
    "v2.21 pause-menu population-witness equivalence did not converge exactly"
)
CLASS_F_WITNESS_STOP = (
    "v2.21 bounded Class-F population witness is not a paired exact core"
)


class CensusEraV221Error(ValueError):
    """The sealed census does not authorize the requested comparison."""


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def semantic_payload(element: dict[str, Any]) -> dict[str, Any]:
    return {
        key: copy.deepcopy(value)
        for key, value in element.items()
        if key not in {"id", "draw_order", "draw_order_semantics"}
    }


def semantic_sha256(element: dict[str, Any]) -> str:
    return sha256_json(semantic_payload(element))


def _receipt(value: Any, *, repository: bool | None = None) -> bool:
    if not isinstance(value, dict):
        return False
    path_keys = {"repo_relative_path", "evidence_path", "path"} & set(value)
    if len(path_keys) != 1:
        return False
    if repository is True and path_keys != {"repo_relative_path"}:
        return False
    if repository is False and path_keys == {"repo_relative_path"}:
        return False
    key = next(iter(path_keys))
    return (
        set(value) == {key, "sha256", "bytes"}
        and isinstance(value[key], str)
        and bool(value[key])
        and isinstance(value.get("sha256"), str)
        and len(value["sha256"]) == 64
        and not isinstance(value.get("bytes"), bool)
        and isinstance(value.get("bytes"), int)
        and value["bytes"] > 0
    )


def receipt_matches(recorded: Any, actual: Any) -> bool:
    return isinstance(recorded, dict) and isinstance(actual, dict) and {
        "sha256": recorded.get("sha256"),
        "bytes": recorded.get("bytes"),
    } == {
        "sha256": actual.get("sha256"),
        "bytes": actual.get("bytes"),
    }


def _member(value: Any, *, class_name: str) -> bool:
    required = {
        "element_id",
        "semantic_sha256",
        "semantic_payload",
        "source_census_occurrences",
        "qualified_occurrences",
    }
    if not isinstance(value, dict) or set(value) != required:
        return False
    payload = value.get("semantic_payload")
    occurrences = value.get("qualified_occurrences")
    if (
        not isinstance(payload, dict)
        or value.get("element_id") != payload.get("id")
        or value.get("semantic_sha256") != semantic_sha256(payload)
        or not isinstance(value.get("source_census_occurrences"), list)
        or not isinstance(occurrences, list)
        or len(occurrences) < 2
    ):
        return False
    for occurrence in occurrences:
        if not isinstance(occurrence, dict) or set(occurrence) != {
            "label",
            "instance",
            "process_id",
            "sample_count",
            "presence_sample_count",
        }:
            return False
        if (
            not isinstance(occurrence.get("label"), str)
            or not occurrence["label"]
            or not isinstance(occurrence.get("instance"), str)
            or not occurrence["instance"].startswith("menufx-")
            or isinstance(occurrence.get("process_id"), bool)
            or not isinstance(occurrence.get("process_id"), int)
            or occurrence.get("sample_count", 0) < 40
            or not isinstance(occurrence.get("presence_sample_count"), int)
        ):
            return False
        if class_name == "A" and occurrence["presence_sample_count"] != 0:
            return False
    if class_name == "B":
        paired = {
            occurrence["label"]: occurrence
            for occurrence in occurrences
            if occurrence["label"] in {
                "standalone.primary",
                "standalone.confirmation",
            }
        }
        if set(paired) != {"standalone.primary", "standalone.confirmation"}:
            return False
        if any(
            occurrence["presence_sample_count"] != occurrence["sample_count"]
            for occurrence in paired.values()
        ):
            return False
    return True


def _record(value: Any, *, class_name: str, expected_count: int) -> bool:
    required = {
        "layout_id",
        "landed_fixture",
        "candidate_fixture",
        "primary_trace",
        "confirmation_trace",
        "profile_state_identity_sha256",
        "bound_endpoints",
        "members",
    }
    if not isinstance(value, dict) or set(value) != required:
        return False
    members = value.get("members")
    return (
        _receipt(value.get("landed_fixture"), repository=True)
        and _receipt(value.get("candidate_fixture"), repository=False)
        and _receipt(value.get("primary_trace"), repository=False)
        and _receipt(value.get("confirmation_trace"), repository=False)
        and isinstance(value.get("profile_state_identity_sha256"), str)
        and len(value["profile_state_identity_sha256"]) == 64
        and isinstance(value.get("bound_endpoints"), list)
        and len(value["bound_endpoints"]) == len(set(value["bound_endpoints"]))
        and isinstance(members, list)
        and len(members) == expected_count
        and all(_member(member, class_name=class_name) for member in members)
        and len({member["element_id"] for member in members}) == len(members)
    )


def _member_set_sha256(record: dict[str, Any]) -> str:
    return sha256_json(
        [
            {
                "element_id": member["element_id"],
                "semantic_sha256": member["semantic_sha256"],
            }
            for member in record["members"]
        ]
    )


def require_contract(contract: dict[str, Any]) -> dict[str, Any]:
    required = {
        "schema",
        "settlement_spec",
        "class",
        "source_census",
        "occurrence_audit",
        "choice_slot_reconciliation",
        "class_a_records",
        "class_b_records",
        "generation_layouts",
        "field_corrections",
        "guard_subsumptions",
        "pause_menu_population_equivalence",
        "class_f_witnesses",
        "application",
        "forbidden",
        "derivation",
    }
    if (
        set(contract) != required
        or contract.get("schema") != SCHEMA
        or contract.get("settlement_spec") != SETTLEMENT_SPEC
        or contract.get("class") != "sealed_census_exact_disposition"
        or contract.get("forbidden") != FORBIDDEN
        or not _receipt(contract.get("source_census"), repository=False)
        or contract["source_census"].get("sha256") != SEALED_CENSUS_SHA256
        or not _receipt(contract.get("occurrence_audit"), repository=False)
        or contract["occurrence_audit"].get("sha256")
        != SEALED_OCCURRENCE_AUDIT_SHA256
    ):
        raise CensusEraV221Error(CONTRACT_SCOPE_STOP)

    choice = contract.get("choice_slot_reconciliation")
    if not isinstance(choice, dict) or set(choice) != {
        "layout_id",
        "source_audit",
        "slot_binding",
        "rows",
        "future_extension",
    }:
        raise CensusEraV221Error(CHOICE_SLOT_STOP)
    slot = choice.get("slot_binding")
    rows = choice.get("rows")
    if (
        choice.get("layout_id") != CHOICE_LAYOUT_ID
        or not _receipt(choice.get("source_audit"), repository=False)
        or choice["source_audit"].get("sha256")
        != SEALED_OCCURRENCE_AUDIT_SHA256
        or not isinstance(slot, dict)
        or slot.get("choice_slot_id") != CHOICE_SLOT_ID
        or slot.get("member_key") != CHOICE_MEMBER_KEY
        or slot.get("atlas_namespace") != "Skills"
        or slot.get("anchor") != {"x": 604, "y": 386.5}
        or slot.get("relative_draw_positions") != [30, 31]
        or slot.get("inter_draw_offset_vectors")
        != [
            {"relative_draw_position": 30, "x": 0, "y": 0},
            {"relative_draw_position": 31, "x": -4, "y": -4},
        ]
        or not isinstance(rows, list)
        or len(rows) != 2
        or {row.get("element_id"): row.get("semantic_sha256") for row in rows}
        != CHOICE_ROWS
        or not all(_member(row, class_name="choice") for row in rows)
        or any(
            not any(
                occurrence["presence_sample_count"]
                == occurrence["sample_count"]
                for occurrence in row["qualified_occurrences"]
            )
            for row in rows
        )
        or choice.get("future_extension") != "QUESTION_required"
    ):
        raise CensusEraV221Error(CHOICE_SLOT_STOP)

    class_a = contract.get("class_a_records")
    class_b = contract.get("class_b_records")
    if not isinstance(class_a, list) or not isinstance(class_b, list):
        raise CensusEraV221Error(CONTRACT_SCOPE_STOP)
    by_a = {record.get("layout_id"): record for record in class_a if isinstance(record, dict)}
    by_b = {record.get("layout_id"): record for record in class_b if isinstance(record, dict)}
    if set(by_a) != set(CLASS_A_COUNTS) or set(by_b) != set(CLASS_B_COUNTS):
        raise CensusEraV221Error(CONTRACT_SCOPE_STOP)
    if any(
        member["element_id"] in CHOICE_ROWS
        for record in class_a
        for member in record["members"]
    ):
        raise CensusEraV221Error(CLASS_A_OCCURRENCE_STOP)
    for layout_id, count in CLASS_A_COUNTS.items():
        record = by_a[layout_id]
        if not _record(record, class_name="choice", expected_count=count):
            raise CensusEraV221Error(CONTRACT_SCOPE_STOP)
        if any(
            occurrence["presence_sample_count"] != 0
            for member in record["members"]
            for occurrence in member["qualified_occurrences"]
        ):
            raise CensusEraV221Error(CLASS_A_OCCURRENCE_STOP)
        if _member_set_sha256(record) != CLASS_A_MEMBER_SET_SHA256[layout_id]:
            raise CensusEraV221Error(CONTRACT_SCOPE_STOP)
    for layout_id, count in CLASS_B_COUNTS.items():
        record = by_b[layout_id]
        if not _record(record, class_name="choice", expected_count=count):
            raise CensusEraV221Error(CONTRACT_SCOPE_STOP)
        for member in record["members"]:
            paired = {
                occurrence["label"]: occurrence
                for occurrence in member["qualified_occurrences"]
                if occurrence["label"]
                in {"standalone.primary", "standalone.confirmation"}
            }
            if set(paired) != {"standalone.primary", "standalone.confirmation"} or any(
                occurrence["presence_sample_count"] != occurrence["sample_count"]
                for occurrence in paired.values()
            ):
                raise CensusEraV221Error(CLASS_B_PAIR_STOP)
        if _member_set_sha256(record) != CLASS_B_MEMBER_SET_SHA256[layout_id]:
            raise CensusEraV221Error(CONTRACT_SCOPE_STOP)

    if set(contract.get("generation_layouts", [])) != GENERATION_LAYOUTS:
        raise CensusEraV221Error(CONTRACT_SCOPE_STOP)
    corrections = contract.get("field_corrections")
    if not isinstance(corrections, list) or len(corrections) != len(FIELD_CORRECTIONS):
        raise CensusEraV221Error(FIELD_CORRECTION_STOP)
    correction_map = {
        (entry.get("layout_id"), entry.get("field")): (
            entry.get("landed_value"),
            entry.get("settled_value"),
        )
        for entry in corrections
        if isinstance(entry, dict)
    }
    if correction_map != FIELD_CORRECTIONS:
        raise CensusEraV221Error(FIELD_CORRECTION_STOP)
    for correction in corrections:
        if set(correction) != {
            "correction_id",
            "layout_id",
            "field",
            "landed_value",
            "settled_value",
            "landed_fixture",
            "candidate_fixture",
            "primary_trace",
            "confirmation_trace",
            "profile_state_identity_sha256",
            "bound_endpoints",
        } or not all(
            _receipt(correction.get(field), repository=(field == "landed_fixture"))
            for field in (
                "landed_fixture",
                "candidate_fixture",
                "primary_trace",
                "confirmation_trace",
            )
        ):
            raise CensusEraV221Error(FIELD_CORRECTION_STOP)

    guards = contract.get("guard_subsumptions")
    if not isinstance(guards, list) or {
        (entry.get("layout_id"), entry.get("guard"))
        for entry in guards
        if isinstance(entry, dict)
    } != GUARD_SUBSUMPTIONS:
        raise CensusEraV221Error(CONTRACT_SCOPE_STOP)
    pause = contract.get("pause_menu_population_equivalence")
    if (
        not isinstance(pause, dict)
        or pause.get("layout_id") != "pause-menu"
        or pause.get("selection_performed") is not False
        or pause.get("diagnosis_converged") is not True
        or pause.get("unclassified_difference_count") != 0
        or not isinstance(pause.get("candidate_bindings"), list)
        or len(pause["candidate_bindings"]) != 2
        or len(
            {
                entry.get("unclassified_differences_sha256")
                for entry in pause["candidate_bindings"]
            }
        )
        != 1
    ):
        raise CensusEraV221Error(PAUSE_EQUIVALENCE_STOP)
    class_f = contract.get("class_f_witnesses")
    records = class_f.get("records") if isinstance(class_f, dict) else None
    if (
        not isinstance(class_f, dict)
        or set(class_f) != {"source_audit", "records", "counter_shopping_performed"}
        or not _receipt(class_f.get("source_audit"), repository=False)
        or class_f["source_audit"].get("sha256") != CLASS_F_WITNESS_AUDIT_SHA256
        or class_f.get("counter_shopping_performed") is not False
        or not isinstance(records, list)
        or len(records) != len(CLASS_F_LAYOUTS)
    ):
        raise CensusEraV221Error(CLASS_F_WITNESS_STOP)
    by_f = {
        record.get("layout_id"): record
        for record in records
        if isinstance(record, dict)
    }
    if set(by_f) != set(CLASS_F_LAYOUTS):
        raise CensusEraV221Error(CLASS_F_WITNESS_STOP)
    for layout_id, (edge_id, core_count) in CLASS_F_LAYOUTS.items():
        record = by_f[layout_id]
        pair = record.get("pair")
        required_record = {
            "layout_id",
            "edge_id",
            "profile_state_identity_sha256",
            "qualified_candidate",
            "projected_core_sha256",
            "projected_core_element_count",
            "pair",
            "acceptance_basis",
            "landed_generation_selection_performed",
        }
        if (
            set(record) != required_record
            or record.get("edge_id") != edge_id
            or record.get("projected_core_element_count") != core_count
            or not isinstance(record.get("projected_core_sha256"), str)
            or len(record["projected_core_sha256"]) != 64
            or record.get("profile_state_identity_sha256")
            != "0539412d5c91207d5b225e86f79795d260fe7b73b8d9a1c29166bd09b445e372"
            or not _receipt(record.get("qualified_candidate"), repository=False)
            or record.get("landed_generation_selection_performed") is not False
            or not isinstance(record.get("acceptance_basis"), str)
            or not record["acceptance_basis"]
            or not isinstance(pair, list)
            or len(pair) != 2
        ):
            raise CensusEraV221Error(CLASS_F_WITNESS_STOP)
        identities: set[tuple[str, int]] = set()
        for observation in pair:
            if (
                not isinstance(observation, dict)
                or set(observation)
                != {
                    "instance",
                    "process_id",
                    "measured_generation",
                    "settled_sample_count",
                    "settled_span_milliseconds",
                    "projected_core_sha256",
                    "navigation_recording",
                    "launch",
                    "launch_profile_state",
                    "stage_report",
                    "pre_navigation_durable_census",
                    "post_capture_durable_census",
                    "exact_pid_disposal",
                    "host_quiescence_after",
                }
                or not isinstance(observation.get("instance"), str)
                or not observation["instance"].startswith("menufx-")
                or isinstance(observation.get("process_id"), bool)
                or not isinstance(observation.get("process_id"), int)
                or observation["process_id"] <= 0
                or isinstance(observation.get("measured_generation"), bool)
                or not isinstance(observation.get("measured_generation"), int)
                or observation.get("settled_sample_count", 0) < 40
                or observation.get("settled_span_milliseconds", 0) < 2_000
                or observation.get("projected_core_sha256")
                != record["projected_core_sha256"]
                or not all(
                    _receipt(observation.get(field), repository=False)
                    for field in (
                        "navigation_recording",
                        "launch",
                        "launch_profile_state",
                        "stage_report",
                        "pre_navigation_durable_census",
                        "post_capture_durable_census",
                        "exact_pid_disposal",
                        "host_quiescence_after",
                    )
                )
            ):
                raise CensusEraV221Error(CLASS_F_WITNESS_STOP)
            identities.add((observation["instance"], observation["process_id"]))
        if len(identities) != 2:
            raise CensusEraV221Error(CLASS_F_WITNESS_STOP)
    derivation = contract.get("derivation")
    if contract.get("application") != {
        "class_a_member_count": 261,
        "class_b_member_count": 38,
        "choice_slot_reconciliation_count": 2,
        "field_correction_count": 6,
        "generation_layout_count": 13,
        "guard_subsumption_count": 4,
        "class_f_witness_count": 2,
        "all_or_nothing_per_layout": True,
        "candidate_member_rewrite": False,
    } or not isinstance(derivation, dict) or set(derivation) != {
        "tool",
        "tool_sha256",
        "tool_bytes",
        "mutation_tool",
        "mutation_tool_sha256",
        "mutation_tool_bytes",
        "source_row_count",
        "writes_only_contract",
        "future_choice_slot_rows_require_question",
    } or derivation.get("tool") != "tools/derive_native_menu_census_era_v221.py" or not isinstance(
        derivation.get("tool_sha256"), str
    ) or len(derivation["tool_sha256"]) != 64 or not isinstance(
        derivation.get("tool_bytes"), int
    ) or derivation["tool_bytes"] <= 0 or derivation.get(
        "mutation_tool"
    ) != "tools/run_native_menu_v221_mutations.py" or not isinstance(
        derivation.get("mutation_tool_sha256"), str
    ) or len(derivation["mutation_tool_sha256"]) != 64 or not isinstance(
        derivation.get("mutation_tool_bytes"), int
    ) or derivation["mutation_tool_bytes"] <= 0 or derivation.get("source_row_count") != 326 or derivation.get(
        "writes_only_contract"
    ) is not True or derivation.get("future_choice_slot_rows_require_question") is not True:
        raise CensusEraV221Error(CONTRACT_SCOPE_STOP)
    return {
        "class_a": by_a,
        "class_b": by_b,
        "choice": choice,
        "field_corrections": {
            (entry["layout_id"], entry["field"]): entry
            for entry in corrections
        },
        "generation_layouts": set(contract["generation_layouts"]),
        "pause_equivalence": pause,
        "class_f": by_f,
    }


def require_class_f_witness(
    layout_id: str,
    contract: dict[str, Any],
) -> dict[str, Any] | None:
    """Return the exact bounded witness record for one of the two Class-F layouts."""
    record = require_contract(contract)["class_f"].get(layout_id)
    return copy.deepcopy(record) if record is not None else None


def _actual_by_id(elements: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for element in elements:
        element_id = element.get("id")
        if not isinstance(element_id, str) or not element_id or element_id in result:
            raise CensusEraV221Error(CLASS_A_RESIDUAL_STOP)
        result[element_id] = element
    return result


def consume_choice_slot_rows(
    layout_id: str,
    residual: list[dict[str, Any]],
    contract: dict[str, Any],
    *,
    enabled: bool = True,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    if not contract:
        return None, residual
    view = require_contract(contract)
    if layout_id != CHOICE_LAYOUT_ID:
        return None, residual
    if not enabled:
        raise CensusEraV221Error(CLASS_A_OCCURRENCE_STOP)
    expected = {row["element_id"]: row for row in view["choice"]["rows"]}
    actual = _actual_by_id(residual)
    matched: list[dict[str, Any]] = []
    for element_id, row in expected.items():
        element = actual.get(element_id)
        if element is None or semantic_sha256(element) != row["semantic_sha256"]:
            raise CensusEraV221Error(CHOICE_SLOT_STOP)
        matched.append(element)
    remaining = [element for element in residual if element.get("id") not in expected]
    return (
        {
            "schema": "solomon-dark-native-menu-choice-slot-reconciliation-v221",
            "layout_id": layout_id,
            "slot_binding": copy.deepcopy(view["choice"]["slot_binding"]),
            "member_ids": sorted(expected),
            "semantic_sha256": sorted(row["semantic_sha256"] for row in expected.values()),
            "qualified_presence_proven": True,
            "v2_8_rule_unchanged": True,
        },
        remaining,
    )


def consume_class_a_residual(
    layout_id: str,
    residual: list[dict[str, Any]],
    contract: dict[str, Any],
    landed_fixture_receipt: dict[str, Any] | None,
    candidate_fixture_receipt: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    if not contract:
        return None, residual
    view = require_contract(contract)
    record = view["class_a"].get(layout_id)
    if record is None:
        return None, residual
    if not receipt_matches(record["landed_fixture"], landed_fixture_receipt) or not receipt_matches(
        record["candidate_fixture"], candidate_fixture_receipt
    ):
        raise CensusEraV221Error(CLASS_A_RESIDUAL_STOP)
    expected = {member["element_id"]: member for member in record["members"]}
    actual = _actual_by_id(residual)
    for element_id, member in expected.items():
        element = actual.get(element_id)
        if element is None or semantic_sha256(element) != member["semantic_sha256"]:
            raise CensusEraV221Error(CLASS_A_RESIDUAL_STOP)
    remaining = [element for element in residual if element.get("id") not in expected]
    return (
        {
            "schema": "solomon-dark-native-menu-census-era-class-a-v221",
            "layout_id": layout_id,
            "superseded_member_count": len(expected),
            "member_ids": sorted(expected),
            "all_members_absent_from_every_qualified_occurrence": True,
            "all_or_nothing": True,
        },
        remaining,
    )


def split_class_b_additions(
    layout_id: str,
    settled_elements: list[dict[str, Any]],
    contract: dict[str, Any],
    landed_fixture_receipt: dict[str, Any] | None,
    candidate_fixture_receipt: dict[str, Any] | None,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    if not contract:
        return None, settled_elements
    view = require_contract(contract)
    record = view["class_b"].get(layout_id)
    if record is None:
        return None, settled_elements
    if not receipt_matches(record["landed_fixture"], landed_fixture_receipt) or not receipt_matches(
        record["candidate_fixture"], candidate_fixture_receipt
    ):
        raise CensusEraV221Error(CLASS_B_PAIR_STOP)
    expected = {member["element_id"]: member for member in record["members"]}
    actual = _actual_by_id(settled_elements)
    for element_id, member in expected.items():
        element = actual.get(element_id)
        if element is None or semantic_sha256(element) != member["semantic_sha256"]:
            raise CensusEraV221Error(CLASS_B_PAIR_STOP)
    remaining = [
        element for element in settled_elements if element.get("id") not in expected
    ]
    return (
        {
            "schema": "solomon-dark-native-menu-census-era-class-b-v221",
            "layout_id": layout_id,
            "adopted_member_count": len(expected),
            "member_ids": sorted(expected),
            "present_in_both_qualified_traces": True,
            "candidate_members_unchanged": True,
        },
        remaining,
    )


def diagnose_field_corrections(
    layout_id: str,
    landed_layout: dict[str, Any],
    settled_layout: dict[str, Any],
    contract: dict[str, Any],
    landed_fixture_receipt: dict[str, Any] | None,
    candidate_fixture_receipt: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    view = require_contract(contract)
    corrections: list[dict[str, Any]] = []
    for field in ("screen_id", "screen_title"):
        landed = landed_layout.get(field)
        settled = settled_layout.get(field)
        if landed == settled:
            continue
        record = view["field_corrections"].get((layout_id, field))
        if (
            record is None
            or (landed, settled)
            != (record["landed_value"], record["settled_value"])
            or not receipt_matches(record["landed_fixture"], landed_fixture_receipt)
            or not receipt_matches(record["candidate_fixture"], candidate_fixture_receipt)
        ):
            raise CensusEraV221Error(FIELD_CORRECTION_STOP)
        corrections.append(
            {
                "schema": "solomon-dark-native-menu-field-correction-v221",
                "correction_id": record["correction_id"],
                "layout_id": layout_id,
                "field": field,
                "old_value": landed,
                "new_value": settled,
                "exact_data_bound": True,
            }
        )
    return corrections


def validate_dark_cloud_menu_references(
    aggregate: dict[str, Any],
    navigation: dict[str, Any],
) -> dict[str, Any]:
    reached: list[str] = []
    layouts = aggregate.get("layouts")
    edges = navigation.get("edges")
    if not isinstance(layouts, list) or not isinstance(edges, list) or not edges:
        raise CensusEraV221Error(STALE_SCREEN_ID_STOP)
    wrappers = [
        entry
        for entry in layouts
        if isinstance(entry, dict)
        and entry.get("fixture") == "menu-layouts/dark-cloud-menu.json"
    ]
    if len(wrappers) != 1 or wrappers[0].get("layout", {}).get("screen_id") != "dark_cloud_menu":
        raise CensusEraV221Error(STALE_SCREEN_ID_STOP)
    reached.append("aggregate.layout")
    for edge in edges:
        edge_id = edge.get("id") if isinstance(edge, dict) else None
        for side in ("before", "after"):
            endpoint = edge.get(side) if isinstance(edge, dict) else None
            if not isinstance(endpoint, dict) or endpoint.get("layout_id") != "dark-cloud-menu":
                continue
            layout = endpoint.get("layout")
            if (
                not isinstance(layout, dict)
                or layout.get("screen_id") != "dark_cloud_menu"
                or endpoint.get("semantic_surface") != "dark_cloud_menu"
                or endpoint.get("tagged_screen") != "dark_cloud_menu"
            ):
                raise CensusEraV221Error(STALE_SCREEN_ID_STOP)
            reached.append(f"{edge_id}.{side}")
    if len(reached) < 2:
        raise CensusEraV221Error(STALE_SCREEN_ID_STOP)
    return {"screen_id": "dark_cloud_menu", "references": sorted(reached), "dangling": 0}


def validate_pause_equivalence(
    contract: dict[str, Any],
    candidate_outcomes: list[dict[str, Any]],
) -> dict[str, Any]:
    expected = require_contract(contract)["pause_equivalence"]
    if not isinstance(candidate_outcomes, list) or len(candidate_outcomes) != 2:
        raise CensusEraV221Error(PAUSE_EQUIVALENCE_STOP)
    identities = {
        (entry.get("edge_id"), entry.get("side")) for entry in candidate_outcomes
    }
    expected_identities = {
        (entry.get("edge_id"), entry.get("side"))
        for entry in expected["candidate_bindings"]
    }
    hashes = {
        entry.get("unclassified_differences_sha256") for entry in candidate_outcomes
    }
    if (
        identities != expected_identities
        or any(entry.get("unclassified_difference_count") != 0 for entry in candidate_outcomes)
        or len(hashes) != 1
        or hashes
        != {
            expected["candidate_bindings"][0][
                "unclassified_differences_sha256"
            ]
        }
    ):
        raise CensusEraV221Error(PAUSE_EQUIVALENCE_STOP)
    return {
        "schema": "solomon-dark-native-menu-population-equivalence-v221",
        "layout_id": "pause-menu",
        "selection_performed": False,
        "candidate_outcomes": copy.deepcopy(candidate_outcomes),
        "diagnosis_converged": True,
        "zero_difference": True,
    }


def game_over_endpoint_precondition_is_vacuous(
    layout_id: str,
    navigation: dict[str, Any],
) -> bool:
    if layout_id != "game-over":
        return False
    edges = navigation.get("edges")
    if not isinstance(edges, list) or not edges:
        raise CensusEraV221Error(CONTRACT_SCOPE_STOP)
    inbound = [
        edge.get("id")
        for edge in edges
        if isinstance(edge, dict)
        and isinstance(edge.get("after"), dict)
        and edge["after"].get("layout_id") == layout_id
    ]
    if inbound:
        raise CensusEraV221Error(
            "v2.21 game-over generation endpoint precondition is not vacuous"
        )
    return True


def normalized_generation_pair(
    landed_layout: dict[str, Any],
    settled_layout: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Use the proven settled core while retaining each measured counter."""
    normalized_landed = copy.deepcopy(settled_layout)
    normalized_settled = copy.deepcopy(settled_layout)
    normalized_landed["generation"] = landed_layout.get("generation")
    return normalized_landed, normalized_settled
