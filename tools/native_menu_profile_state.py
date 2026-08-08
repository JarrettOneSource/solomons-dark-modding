#!/usr/bin/env python3
"""Machine-derived durable-state provenance for the G11 menu campaign."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path
from typing import Any


BASELINE_SCHEMA = "solomon-dark-native-menu-profile-state-baseline-v1"
RECEIPT_SCHEMA = "solomon-dark-native-menu-profile-state-v1"
IDENTITY_SCHEMA = "solomon-dark-native-menu-profile-state-input-v1"
BASELINE_REPO_PATH = Path(
    "tests/fixtures/webgame/native-menu-profile-state-baseline.json"
)
HUB_BINDINGS_REPO_PATH = Path(
    "tests/fixtures/webgame/native-menu-hub-bindings-v213.json"
)
HUB_BINDINGS_SCHEMA = "solomon-dark-native-menu-hub-bindings-v213"
FRESH_BASELINE_ID = "pristine_fresh_install"
DERIVED_HUB_BASELINE_ID = "hub_new_game_two_action_v213"
PROFILE_MISMATCH_REASON = "native-menu profile-state provenance mismatch"
PER_BINDING_MISMATCH_REASON = (
    "native-menu per-binding profile-state baseline mismatch"
)
DERIVATION_MISMATCH_REASON = "native-menu derivation receipt mismatch"
V212_EXACT_LAYOUT_REASON = "Settlement v2.12 exact pristine Hub layout mismatch"
V212_SCOPE_REASON = "Settlement v2.12 exact pristine Hub layout scope mismatch"
V213_EXACT_LAYOUT_REASON = "Settlement v2.13 exact derived Hub layout mismatch"


class NativeMenuProfileStateError(RuntimeError):
    """A capture does not reproduce the pinned pristine durable state."""


def _read_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as error:
        raise NativeMenuProfileStateError(
            f"{label} is not readable JSON: {error}"
        ) from error
    if not isinstance(value, dict):
        raise NativeMenuProfileStateError(f"{label} is not a JSON object")
    return value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _lower_sha256(value: object, label: str) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise NativeMenuProfileStateError(
            f"{label} is not a lowercase SHA-256"
        )
    return value


def _identity_payload(profile_state: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": IDENTITY_SCHEMA,
        "baseline_mode": profile_state.get("baseline_mode"),
        "source_sandbox_excluded": profile_state.get(
            "source_sandbox_excluded"
        ),
        "retail_appdata_seeded": profile_state.get("retail_appdata_seeded"),
        "files": profile_state.get("files"),
    }


def compute_profile_state_identity(profile_state: dict[str, Any]) -> str:
    payload = json.dumps(
        _identity_payload(profile_state),
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def hub_resolved_semantic_multiset(layout: dict[str, Any]) -> dict[str, Any]:
    """Hash Hub semantics with v2.3 motion capability, not synthetic identity."""

    elements = layout.get("elements")
    if not isinstance(elements, list) or not elements or not all(
        isinstance(element, dict) for element in elements
    ):
        raise NativeMenuProfileStateError(
            "Hub exact-layout contract reached no semantic members"
        )
    members: list[list[Any]] = []
    for element in elements:
        geometry: list[Any]
        if element.get("art_id") == "UI.28":
            geometry = ["v2.3-motion-capable-geometry"]
        else:
            geometry = [
                list(element.get("rect", [])),
                list(element.get("unclipped_rect", [])),
            ]
        members.append(
            [
                element.get("kind"),
                element.get("text"),
                element.get("action_id"),
                element.get("art_id"),
                element.get("font_id"),
                element.get("text_style"),
                element.get("visible"),
                element.get("interactive"),
                geometry,
            ]
        )
    members.sort(
        key=lambda member: json.dumps(
            member, ensure_ascii=False, separators=(",", ":")
        )
    )
    payload = json.dumps(
        members, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    return {
        "element_count": len(elements),
        "resolved_semantic_multiset_sha256": hashlib.sha256(payload).hexdigest(),
        "resolved_semantic_multiset": members,
    }


def load_profile_state_baseline(repo_root: Path) -> dict[str, Any]:
    path = (repo_root / BASELINE_REPO_PATH).resolve()
    if not path.is_file():
        raise NativeMenuProfileStateError(
            "pinned native-menu profile-state baseline is absent"
        )
    baseline = _read_object(path, "native-menu profile-state baseline")
    if baseline.get("schema") != BASELINE_SCHEMA:
        raise NativeMenuProfileStateError(
            "native-menu profile-state baseline schema is not recognized"
        )
    profile_state = baseline.get("profile_state")
    if not isinstance(profile_state, dict):
        raise NativeMenuProfileStateError(
            "native-menu profile-state baseline has no state payload"
        )
    identity = _lower_sha256(
        profile_state.get("profile_state_identity_sha256"),
        "native-menu profile-state baseline identity",
    )
    if (
        profile_state.get("identity_schema") != IDENTITY_SCHEMA
        or profile_state.get("baseline_mode") != "fresh_install"
        or profile_state.get("source_sandbox_excluded") is not True
        or profile_state.get("retail_appdata_seeded") is not False
        or profile_state.get("files") != []
    ):
        raise NativeMenuProfileStateError(
            "native-menu profile-state baseline is not the pristine fresh-install state"
        )
    if compute_profile_state_identity(profile_state) != identity:
        raise NativeMenuProfileStateError(
            "native-menu profile-state baseline records a false identity"
        )
    return {
        "path": path,
        "sha256": sha256_file(path),
        "bytes": path.stat().st_size,
        "identity": identity,
        "profile_state": profile_state,
        "value": baseline,
    }


def load_hub_binding_contract(repo_root: Path) -> dict[str, Any]:
    path = (repo_root / HUB_BINDINGS_REPO_PATH).resolve()
    if not path.is_file():
        raise NativeMenuProfileStateError(
            "pinned native-menu Hub baseline/binding contract is absent"
        )
    contract = _read_object(path, "native-menu Hub baseline/binding contract")
    if (
        contract.get("schema") != HUB_BINDINGS_SCHEMA
        or contract.get("settlement_spec") != "2.13"
        or contract.get("baseline_legitimacy", {}).get(
            "copied_profile_state_forbidden"
        )
        is not True
    ):
        raise NativeMenuProfileStateError(
            "native-menu Hub baseline/binding contract is not the fail-closed v2.13 contract"
        )
    baselines = contract.get("baselines")
    if not isinstance(baselines, dict) or set(baselines) != {
        FRESH_BASELINE_ID,
        DERIVED_HUB_BASELINE_ID,
    }:
        raise NativeMenuProfileStateError(
            "native-menu Hub baseline registry changed its exact two-baseline census"
        )
    pristine = load_profile_state_baseline(repo_root)
    fresh = baselines[FRESH_BASELINE_ID]
    fresh_fixture = fresh.get("fixture") if isinstance(fresh, dict) else None
    if (
        not isinstance(fresh_fixture, dict)
        or fresh.get("kind") != "pristine_fresh_install"
        or fresh.get("profile_state_identity_sha256") != pristine["identity"]
        or fresh_fixture.get("repo_relative_path")
        != BASELINE_REPO_PATH.as_posix()
        or fresh_fixture.get("sha256") != pristine["sha256"]
        or fresh_fixture.get("bytes") != pristine["bytes"]
    ):
        raise NativeMenuProfileStateError(
            "native-menu Hub baseline registry records a false pristine baseline"
        )
    derived = baselines[DERIVED_HUB_BASELINE_ID]
    witnesses = derived.get("witnesses") if isinstance(derived, dict) else None
    if (
        not isinstance(witnesses, list)
        or len(witnesses) != 2
        or derived.get("kind")
        != "documented_deterministic_receipted_in_game_derivation"
        or derived.get("parent_baseline_id") != FRESH_BASELINE_ID
        or not isinstance(derived.get("procedure"), list)
        or not derived.get("procedure")
        or not isinstance(derived.get("required_profile_fields"), list)
        or not derived.get("required_profile_fields")
    ):
        raise NativeMenuProfileStateError(
            "native-menu Hub derived baseline lost its exact receipted derivation"
        )
    roles: set[str] = set()
    identities: set[str] = set()
    for witness in witnesses:
        if not isinstance(witness, dict):
            raise NativeMenuProfileStateError(
                "native-menu Hub derived baseline contains a malformed witness"
            )
        role = witness.get("role")
        identity = _lower_sha256(
            witness.get("profile_state_identity_sha256"),
            "native-menu Hub derived witness identity",
        )
        profile_receipt = witness.get("profile_state_receipt")
        if (
            role not in {"primary", "confirmation"}
            or not isinstance(profile_receipt, dict)
            or not isinstance(profile_receipt.get("evidence_path"), str)
            or not isinstance(profile_receipt.get("bytes"), int)
            or profile_receipt.get("bytes", 0) <= 0
        ):
            raise NativeMenuProfileStateError(
                "native-menu Hub derived baseline witness receipt is incomplete"
            )
        _lower_sha256(
            profile_receipt.get("sha256"),
            "native-menu Hub derived witness receipt SHA-256",
        )
        roles.add(role)
        identities.add(identity)
    if roles != {"primary", "confirmation"} or len(identities) != 2:
        raise NativeMenuProfileStateError(
            "native-menu Hub derived baseline did not pin two independent witness roles"
        )
    layouts = contract.get("layouts")
    if not isinstance(layouts, dict) or set(layouts) != {
        "hub_resumed",
        "hub_pristine_second_new_game",
        "hub_new_game",
    }:
        raise NativeMenuProfileStateError(
            "native-menu Hub binding contract changed its exact three-layout census"
        )
    for layout_id, layout in layouts.items():
        if (
            not isinstance(layout, dict)
            or layout.get("parent_screen_id") != "hub"
            or layout.get("required_baseline_id") not in baselines
            or not isinstance(layout.get("measured_settled_element_count"), int)
            or layout.get("measured_settled_element_count", 0) <= 0
        ):
            raise NativeMenuProfileStateError(
                f"native-menu Hub layout '{layout_id}' lost its exact baseline selector"
            )
    exact_layout_ids = {
        "hub_pristine_second_new_game",
        "hub_new_game",
    }
    for layout_id in exact_layout_ids:
        layout = layouts[layout_id]
        members = layout.get("resolved_semantic_multiset")
        expected_count = layout["measured_settled_element_count"]
        expected_digest = _lower_sha256(
            layout.get("resolved_semantic_multiset_sha256"),
            f"native-menu Hub layout '{layout_id}' semantic multiset",
        )
        if not isinstance(members, list) or len(members) != expected_count:
            raise NativeMenuProfileStateError(
                f"native-menu Hub layout '{layout_id}' lost its complete exact semantic multiset"
            )
        payload = json.dumps(
            members, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
        if hashlib.sha256(payload).hexdigest() != expected_digest:
            raise NativeMenuProfileStateError(
                f"native-menu Hub layout '{layout_id}' records a false semantic multiset digest"
            )
    bindings = contract.get("bindings")
    if not isinstance(bindings, list) or len(bindings) != 6:
        raise NativeMenuProfileStateError(
            "native-menu Hub binding contract changed its exact endpoint census"
        )
    binding_keys: set[tuple[str, str, str]] = set()
    for binding in bindings:
        if not isinstance(binding, dict):
            raise NativeMenuProfileStateError(
                "native-menu Hub binding contract contains a malformed endpoint"
            )
        key = (
            str(binding.get("edge_id", "")),
            str(binding.get("endpoint", "")),
            str(binding.get("required_baseline_id", "")),
        )
        layout_id = binding.get("layout_id")
        if (
            not all(key)
            or key in binding_keys
            or layout_id not in layouts
            or layouts[layout_id]["required_baseline_id"] != key[2]
        ):
            raise NativeMenuProfileStateError(
                "native-menu Hub endpoint binding is absent, ambiguous, or cross-baseline"
            )
        binding_keys.add(key)
    return {
        "path": path,
        "sha256": sha256_file(path),
        "bytes": path.stat().st_size,
        "value": contract,
        "baselines": baselines,
    }


def required_baseline_for_layout(repo_root: Path, layout_id: str) -> str:
    contract = load_hub_binding_contract(repo_root)["value"]
    layout = contract["layouts"].get(layout_id)
    if layout is None:
        return FRESH_BASELINE_ID
    return str(layout["required_baseline_id"])


def resolve_navigation_profile_binding(
    repo_root: Path,
    *,
    edge_id: str,
    endpoint: str,
    baseline_id: str,
) -> str | None:
    contract = load_hub_binding_contract(repo_root)["value"]
    known = [
        binding
        for binding in contract["bindings"]
        if binding["edge_id"] == edge_id and binding["endpoint"] == endpoint
    ]
    if not known:
        edge_baselines = {
            binding["required_baseline_id"]
            for binding in contract["bindings"]
            if binding["edge_id"] == edge_id
        }
        if baseline_id != FRESH_BASELINE_ID and baseline_id not in edge_baselines:
            raise NativeMenuProfileStateError(
                f"{PER_BINDING_MISMATCH_REASON}: edge '{edge_id}' endpoint "
                f"'{endpoint}' is not authorized under '{baseline_id}'"
            )
        return None
    matches = [
        binding
        for binding in known
        if binding["required_baseline_id"] == baseline_id
    ]
    if len(matches) != 1:
        raise NativeMenuProfileStateError(
            f"{PER_BINDING_MISMATCH_REASON}: edge '{edge_id}' endpoint "
            f"'{endpoint}' has no unique binding under '{baseline_id}'"
        )
    return str(matches[0]["layout_id"])


def assert_navigation_baseline_allowed(
    repo_root: Path,
    *,
    edge_id: str,
    baseline_id: str,
) -> None:
    contract = load_hub_binding_contract(repo_root)["value"]
    allowed = {
        binding["required_baseline_id"]
        for binding in contract["bindings"]
        if binding["edge_id"] == edge_id
    }
    if not allowed:
        allowed = {FRESH_BASELINE_ID}
    if baseline_id not in allowed:
        raise NativeMenuProfileStateError(
            f"{PER_BINDING_MISMATCH_REASON}: edge '{edge_id}' requires one of "
            f"{sorted(allowed)} but capture proves '{baseline_id}'"
        )


def validate_exact_hub_layout_pair(
    repo_root: Path,
    *,
    layout_id: str,
    primary_layout: dict[str, Any],
    confirmation_layout: dict[str, Any],
    baseline_id: str,
) -> dict[str, Any] | None:
    """Validate exact v2.12/v2.13 raw Hub multisets and their scope."""

    contract = load_hub_binding_contract(repo_root)["value"]
    layouts = contract["layouts"]
    primary = hub_resolved_semantic_multiset(primary_layout)
    confirmation = hub_resolved_semantic_multiset(confirmation_layout)
    exact_contracts = {
        candidate_id: {
            "element_count": candidate["measured_settled_element_count"],
            "resolved_semantic_multiset_sha256": candidate[
                "resolved_semantic_multiset_sha256"
            ],
            "resolved_semantic_multiset": candidate[
                "resolved_semantic_multiset"
            ],
        }
        for candidate_id, candidate in layouts.items()
        if "resolved_semantic_multiset_sha256" in candidate
    }
    matching_ids = {
        candidate_id
        for candidate_id, expected in exact_contracts.items()
        if primary == expected
    }
    if matching_ids and layout_id not in matching_ids:
        matched = sorted(matching_ids)
        raise NativeMenuProfileStateError(
            f"{V212_SCOPE_REASON}: exact Hub multiset for {matched} claimed as "
            f"'{layout_id}'"
        )
    if layout_id not in layouts:
        return None
    required_baseline_id = layouts[layout_id]["required_baseline_id"]
    if baseline_id != required_baseline_id:
        raise NativeMenuProfileStateError(
            f"{PER_BINDING_MISMATCH_REASON}: layout '{layout_id}' requires "
            f"'{required_baseline_id}' but capture proves '{baseline_id}'"
        )
    expected = exact_contracts.get(layout_id)
    if expected is None:
        return {
            "layout_id": layout_id,
            "baseline_id": baseline_id,
            "element_count": primary["element_count"],
        }
    reason = (
        V212_EXACT_LAYOUT_REASON
        if layout_id == "hub_pristine_second_new_game"
        else V213_EXACT_LAYOUT_REASON
    )
    if primary != expected or confirmation != expected:
        raise NativeMenuProfileStateError(
            f"{reason}: '{layout_id}' does not reproduce both exact instances"
        )
    return {
        "layout_id": layout_id,
        "baseline_id": baseline_id,
        **expected,
    }


def _resolve_baseline_identity(
    *,
    receipt: dict[str, Any],
    identity: str,
    contract: dict[str, Any],
    label: str,
) -> dict[str, Any]:
    state = {
        "baseline_mode": receipt.get("baseline_mode"),
        "source_sandbox_excluded": receipt.get("source_sandbox_excluded"),
        "retail_appdata_seeded": receipt.get("retail_appdata_seeded"),
        "files": receipt.get("files"),
    }
    if compute_profile_state_identity(state) != identity:
        raise NativeMenuProfileStateError(
            f"{PROFILE_MISMATCH_REASON}: {label} receipt records a false identity"
        )
    fresh = contract["baselines"][FRESH_BASELINE_ID]
    if identity == fresh["profile_state_identity_sha256"]:
        if state != {
            "baseline_mode": "fresh_install",
            "source_sandbox_excluded": True,
            "retail_appdata_seeded": False,
            "files": [],
        }:
            raise NativeMenuProfileStateError(
                f"{PROFILE_MISMATCH_REASON}: {label} does not reproduce the pristine state"
            )
        return {
            "baseline_id": FRESH_BASELINE_ID,
            "witness_role": None,
            "witness": None,
        }
    witnesses = contract["baselines"][DERIVED_HUB_BASELINE_ID]["witnesses"]
    matches = [
        witness
        for witness in witnesses
        if witness["profile_state_identity_sha256"] == identity
    ]
    if len(matches) != 1:
        raise NativeMenuProfileStateError(
            f"{PROFILE_MISMATCH_REASON}: {label} identity '{identity}' is not "
            "one exact pinned baseline witness"
        )
    if (
        state["baseline_mode"] != "persistent_profile"
        or state["source_sandbox_excluded"] is not False
        or state["retail_appdata_seeded"] is not False
        or not isinstance(state["files"], list)
        or not state["files"]
    ):
        raise NativeMenuProfileStateError(
            f"{DERIVATION_MISMATCH_REASON}: {label} did not record the derived durable files"
        )
    witness = matches[0]
    return {
        "baseline_id": DERIVED_HUB_BASELINE_ID,
        "witness_role": witness["role"],
        "witness": witness,
    }


def _derivation_evidence(witness: dict[str, Any]) -> dict[str, Any]:
    return {
        "instance": witness["instance"],
        "profile_state_receipt": witness["profile_state_receipt"],
        "potionguy_action_receipt": witness["potionguy_action_receipt"],
        "clean_completion_receipt": witness["clean_completion_receipt"],
        "settled_hub_observation": witness["settled_hub_observation"],
    }


def materialize_capture_profile_state(
    *,
    repo_root: Path,
    launch_receipt_path: Path,
    evidence_path: Path,
    label: str,
) -> dict[str, Any]:
    baseline = load_profile_state_baseline(repo_root)
    contract = load_hub_binding_contract(repo_root)
    receipt = _read_object(launch_receipt_path, f"{label} launch receipt")
    receipt_state = {
        "baseline_mode": receipt.get("baseline_mode"),
        "source_sandbox_excluded": receipt.get("source_sandbox_excluded"),
        "retail_appdata_seeded": receipt.get("retail_appdata_seeded"),
        "files": receipt.get("files"),
    }
    identity = _lower_sha256(
        receipt.get("profile_state_identity_sha256"),
        f"{label} launch receipt identity",
    )
    if receipt.get("schema") != RECEIPT_SCHEMA:
        raise NativeMenuProfileStateError(
            f"{PROFILE_MISMATCH_REASON}: {label} launch receipt schema is not recognized"
        )
    resolved = _resolve_baseline_identity(
        receipt=receipt,
        identity=identity,
        contract=contract,
        label=f"{label} launch receipt",
    )
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    if evidence_path.exists():
        raise NativeMenuProfileStateError(
            f"{label} profile-state evidence path already exists"
        )
    temporary = evidence_path.with_name(evidence_path.name + ".menufix.tmp")
    try:
        shutil.copyfile(launch_receipt_path, temporary)
        temporary.replace(evidence_path)
    finally:
        if temporary.exists():
            temporary.unlink()
    launch_sha256 = sha256_file(evidence_path)
    launch_bytes = evidence_path.stat().st_size
    baseline_fixture = (
        {
            "repo_relative_path": BASELINE_REPO_PATH.as_posix(),
            "sha256": baseline["sha256"],
            "bytes": baseline["bytes"],
        }
        if resolved["baseline_id"] == FRESH_BASELINE_ID
        else {
            "repo_relative_path": HUB_BINDINGS_REPO_PATH.as_posix(),
            "sha256": contract["sha256"],
            "bytes": contract["bytes"],
        }
    )
    value = {
        "schema": RECEIPT_SCHEMA,
        "profile_state_identity_sha256": identity,
        "baseline_id": resolved["baseline_id"],
        "baseline_mode": receipt_state["baseline_mode"],
        "source_sandbox_excluded": receipt_state["source_sandbox_excluded"],
        "retail_appdata_seeded": receipt_state["retail_appdata_seeded"],
        "durable_file_count": len(receipt_state["files"]),
        "baseline_fixture": baseline_fixture,
        "binding_contract": {
            "repo_relative_path": HUB_BINDINGS_REPO_PATH.as_posix(),
            "sha256": contract["sha256"],
            "bytes": contract["bytes"],
        },
        "launch_receipt": {
            "evidence_filename": evidence_path.name,
            "sha256": launch_sha256,
            "bytes": launch_bytes,
        },
    }
    if resolved["witness_role"] is not None:
        value["derivation_witness_role"] = resolved["witness_role"]
        value["derivation_witness_instance"] = resolved["witness"][
            "instance"
        ]
        value["derivation_evidence"] = _derivation_evidence(
            resolved["witness"]
        )
    return value


def _resolve_unique_receipt(
    evidence_root: Path, evidence_filename: str, label: str
) -> Path:
    if not evidence_filename or Path(evidence_filename).name != evidence_filename:
        raise NativeMenuProfileStateError(
            f"{label} launch receipt filename is unsafe or absent"
        )
    root = evidence_root.resolve()
    matches = sorted(
        path.resolve()
        for path in root.rglob(evidence_filename)
        if path.is_file()
    )
    if len(matches) != 1:
        raise NativeMenuProfileStateError(
            f"{label} launch receipt lookup is absent or ambiguous: {matches}"
        )
    if not matches[0].is_relative_to(root):
        raise NativeMenuProfileStateError(
            f"{label} launch receipt escapes the evidence root"
        )
    return matches[0]


def validate_capture_profile_state(
    *,
    repo_root: Path,
    header: dict[str, Any],
    label: str,
    evidence_root: Path | None,
    required_baseline_id: str | None = None,
    binding_label: str | None = None,
) -> dict[str, Any]:
    baseline = load_profile_state_baseline(repo_root)
    contract = load_hub_binding_contract(repo_root)
    source = header.get("source")
    profile_state = header.get("profile_state")
    if not isinstance(source, dict) or not isinstance(profile_state, dict):
        raise NativeMenuProfileStateError(
            f"{label} has no machine-derived profile-state provenance"
        )
    identity = _lower_sha256(
        profile_state.get("profile_state_identity_sha256"),
        f"{label} profile-state identity",
    )
    source_identity = _lower_sha256(
        source.get("profile_state_identity_sha256"),
        f"{label} source profile-state identity",
    )
    if identity != source_identity:
        raise NativeMenuProfileStateError(
            f"{PROFILE_MISMATCH_REASON}: {label} header/source identities disagree"
        )
    if profile_state.get("schema") != RECEIPT_SCHEMA:
        raise NativeMenuProfileStateError(
            f"{label} profile-state schema is not recognized"
        )
    fresh = contract["baselines"][FRESH_BASELINE_ID]
    derived = contract["baselines"][DERIVED_HUB_BASELINE_ID]
    if identity == fresh["profile_state_identity_sha256"]:
        resolved = {
            "baseline_id": FRESH_BASELINE_ID,
            "witness_role": None,
            "witness": None,
        }
        if (
            profile_state.get("baseline_mode") != "fresh_install"
            or profile_state.get("source_sandbox_excluded") is not True
            or profile_state.get("retail_appdata_seeded") is not False
            or profile_state.get("durable_file_count") != 0
        ):
            raise NativeMenuProfileStateError(
                f"{label} does not prove the pristine fresh-install file state"
            )
    else:
        witness_matches = [
            witness
            for witness in derived["witnesses"]
            if witness["profile_state_identity_sha256"] == identity
        ]
        if len(witness_matches) != 1:
            raise NativeMenuProfileStateError(
                f"{PROFILE_MISMATCH_REASON}: {label} identity '{identity}' is not "
                "one exact pinned baseline witness"
            )
        witness = witness_matches[0]
        resolved = {
            "baseline_id": DERIVED_HUB_BASELINE_ID,
            "witness_role": witness["role"],
            "witness": witness,
        }
        if (
            profile_state.get("baseline_mode") != "persistent_profile"
            or profile_state.get("source_sandbox_excluded") is not False
            or profile_state.get("retail_appdata_seeded") is not False
            or isinstance(profile_state.get("durable_file_count"), bool)
            or not isinstance(profile_state.get("durable_file_count"), int)
            or profile_state.get("durable_file_count", 0) <= 0
        ):
            raise NativeMenuProfileStateError(
                f"{DERIVATION_MISMATCH_REASON}: {label} header does not identify "
                "the pinned derived durable state"
            )
    recorded_baseline_id = profile_state.get("baseline_id")
    if recorded_baseline_id is not None and (
        recorded_baseline_id != resolved["baseline_id"]
    ):
        raise NativeMenuProfileStateError(
            f"{PROFILE_MISMATCH_REASON}: {label} records the wrong baseline id"
        )
    recorded_role = profile_state.get("derivation_witness_role")
    if recorded_role is not None and recorded_role != resolved["witness_role"]:
        raise NativeMenuProfileStateError(
            f"{DERIVATION_MISMATCH_REASON}: {label} records the wrong derivation witness role"
        )
    if resolved["witness"] is not None:
        expected_instance = resolved["witness"]["instance"]
        if (
            header.get("instance") != expected_instance
            or profile_state.get("derivation_witness_instance")
            != expected_instance
            or profile_state.get("derivation_evidence")
            != _derivation_evidence(resolved["witness"])
        ):
            raise NativeMenuProfileStateError(
                f"{DERIVATION_MISMATCH_REASON}: {label} does not bind the "
                "exact witness instance and derivation evidence"
            )
    if required_baseline_id is not None and (
        resolved["baseline_id"] != required_baseline_id
    ):
        consequence = binding_label or label
        raise NativeMenuProfileStateError(
            f"{PER_BINDING_MISMATCH_REASON}: {consequence} requires "
            f"'{required_baseline_id}' but capture proves "
            f"'{resolved['baseline_id']}'"
        )
    baseline_receipt = profile_state.get("baseline_fixture")
    if not isinstance(baseline_receipt, dict):
        raise NativeMenuProfileStateError(
            f"{label} has no committed profile-state baseline receipt"
        )
    expected_baseline_fixture = (
        {
            "repo_relative_path": BASELINE_REPO_PATH.as_posix(),
            "sha256": baseline["sha256"],
            "bytes": baseline["bytes"],
        }
        if resolved["baseline_id"] == FRESH_BASELINE_ID
        else {
            "repo_relative_path": HUB_BINDINGS_REPO_PATH.as_posix(),
            "sha256": contract["sha256"],
            "bytes": contract["bytes"],
        }
    )
    if baseline_receipt != expected_baseline_fixture:
        raise NativeMenuProfileStateError(
            f"{label} records a false committed profile-state baseline receipt"
        )
    binding_contract = profile_state.get("binding_contract")
    if binding_contract is not None and binding_contract != {
        "repo_relative_path": HUB_BINDINGS_REPO_PATH.as_posix(),
        "sha256": contract["sha256"],
        "bytes": contract["bytes"],
    }:
        raise NativeMenuProfileStateError(
            f"{label} records a false committed per-binding baseline contract"
        )
    launch_receipt = profile_state.get("launch_receipt")
    if not isinstance(launch_receipt, dict):
        raise NativeMenuProfileStateError(
            f"{label} has no exact pre-launch profile-state receipt"
        )
    expected_sha256 = _lower_sha256(
        launch_receipt.get("sha256"), f"{label} launch receipt SHA-256"
    )
    expected_bytes = launch_receipt.get("bytes")
    if (
        isinstance(expected_bytes, bool)
        or not isinstance(expected_bytes, int)
        or expected_bytes <= 0
    ):
        raise NativeMenuProfileStateError(
            f"{label} launch receipt has no positive byte count"
        )
    if evidence_root is not None:
        filename = launch_receipt.get("evidence_filename")
        if not isinstance(filename, str):
            raise NativeMenuProfileStateError(
                f"{label} launch receipt has no evidence filename"
            )
        receipt_path = _resolve_unique_receipt(evidence_root, filename, label)
        if (
            receipt_path.stat().st_size != expected_bytes
            or sha256_file(receipt_path) != expected_sha256
        ):
            raise NativeMenuProfileStateError(
                f"{label} launch receipt byte/hash provenance is false"
            )
        receipt = _read_object(receipt_path, f"{label} launch receipt")
        receipt_identity = _lower_sha256(
            receipt.get("profile_state_identity_sha256"),
            f"{label} launch receipt identity",
        )
        if receipt.get("schema") != RECEIPT_SCHEMA:
            raise NativeMenuProfileStateError(
                f"{PROFILE_MISMATCH_REASON}: {label} launch receipt schema is not recognized"
            )
        resolved_receipt = _resolve_baseline_identity(
            receipt=receipt,
            identity=receipt_identity,
            contract=contract,
            label=f"{label} launch receipt",
        )
        if (
            receipt_identity != identity
            or resolved_receipt["baseline_id"] != resolved["baseline_id"]
            or resolved_receipt["witness_role"] != resolved["witness_role"]
            or (
                resolved_receipt["witness"] is not None
                and resolved_receipt["witness"]["instance"]
                != resolved["witness"]["instance"]
            )
        ):
            raise NativeMenuProfileStateError(
                f"{PROFILE_MISMATCH_REASON}: {label} launch receipt and header disagree"
            )
    return {
        "identity": identity,
        "baseline_id": resolved["baseline_id"],
        "witness_role": resolved["witness_role"],
        "witness_instance": (
            resolved["witness"]["instance"]
            if resolved["witness"] is not None
            else None
        ),
        "baseline_sha256": baseline["sha256"],
        "baseline_bytes": baseline["bytes"],
        "binding_contract_sha256": contract["sha256"],
        "binding_contract_bytes": contract["bytes"],
        "launch_receipt_sha256": expected_sha256,
        "launch_receipt_bytes": expected_bytes,
    }
