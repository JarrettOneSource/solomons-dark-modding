#!/usr/bin/env python3
"""Audit the two bounded Settlement v2.21 Class-F witness pairs."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

if __package__:
    from .native_menu_landed_diagnosis_v25 import _signature, canonical_bytes
else:
    from native_menu_landed_diagnosis_v25 import (  # type: ignore[no-redef]
        _signature,
        canonical_bytes,
    )


PROFILE_IDENTITY = (
    "0539412d5c91207d5b225e86f79795d260fe7b73b8d9a1c29166bd09b445e372"
)
CONFIG = {
    "performance": {
        "screen_id": "performance",
        "edge_id": "settings_to_performance",
        "roles": (
            "performance/primary-rerun2",
            "performance/confirmation",
        ),
        "rejected_roles": (
            "performance/primary",
            "performance/primary-rerun",
        ),
    },
    "profile-save-select": {
        "screen_id": "profile_save_select",
        "edge_id": "main_to_profile_select",
        "roles": (
            "profile-save-select/primary",
            "profile-save-select/confirmation",
        ),
        "rejected_roles": (),
    },
}


class ClassFWitnessError(ValueError):
    """The bounded Class-F capture evidence is incomplete or disagrees."""


def read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ClassFWitnessError(f"Class-F evidence '{path}' is not an object")
    return value


def receipt(path: Path, root: Path) -> dict[str, Any]:
    data = path.read_bytes()
    return {
        "evidence_path": path.resolve().relative_to(root.resolve()).as_posix(),
        "sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
    }


def require_receipt(path: Path, root: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise ClassFWitnessError(f"Class-F {label} receipt is absent: {path}")
    return receipt(path, root)


def _ordered(elements: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        elements,
        key=lambda element: (
            float(element["draw_order"]),
            _signature(element),
            str(element.get("id", "")),
        ),
    )


def project_sample(
    sample: dict[str, Any], expected_sequence: list[bytes], label: str
) -> dict[str, Any]:
    payload = sample.get("payload")
    elements = payload.get("elements") if isinstance(payload, dict) else None
    if not isinstance(elements, list) or not all(
        isinstance(element, dict) for element in elements
    ):
        raise ClassFWitnessError(f"Class-F {label} sample has no element census")
    remaining = Counter(expected_sequence)
    projected: list[bytes] = []
    for element in _ordered(elements):
        signature = _signature(element)
        if remaining[signature] <= 0:
            continue
        remaining[signature] -= 1
        projected.append(signature)
    missing_count = sum(remaining.values())
    if missing_count:
        raise ClassFWitnessError(
            f"Class-F {label} sample is missing {missing_count} qualified core members"
        )
    if projected != expected_sequence:
        raise ClassFWitnessError(
            f"Class-F {label} sample changed the qualified core relative sequence"
        )
    return {
        "projected_core_sha256": hashlib.sha256(
            canonical_bytes([value.decode("utf-8") for value in projected])
        ).hexdigest(),
        "raw_element_count": len(elements),
        "ambient_or_noncore_count": len(elements) - len(projected),
    }


def _phase_generations(trace: dict[str, Any]) -> list[int]:
    values: list[int] = []
    for key in ("high_cadence_structural_phases", "structural_phases"):
        phases = trace.get(key, [])
        if not isinstance(phases, list):
            raise ClassFWitnessError(
                f"Class-F population trace field '{key}' is not a list"
            )
        for phase in phases:
            payload = phase.get("payload") if isinstance(phase, dict) else None
            generation = payload.get("generation") if isinstance(payload, dict) else None
            if isinstance(generation, bool) or not isinstance(generation, int):
                raise ClassFWitnessError(
                    f"Class-F population phase in '{key}' has no measured generation"
                )
            values.append(generation)
    if not values:
        raise ClassFWitnessError("Class-F population trace reached no real phases")
    return values


def audit_role(
    *,
    layout_id: str,
    config: dict[str, Any],
    role_root: Path,
    evidence_root: Path,
    expected_sequence: list[bytes],
    candidate_layout: dict[str, Any],
) -> dict[str, Any]:
    navigation_path = role_root / "population-witness-navigation.json"
    navigation = read_object(navigation_path)
    edges = navigation.get("edges")
    if not isinstance(edges, list) or len(edges) != 1 or not isinstance(edges[0], dict):
        raise ClassFWitnessError(
            f"Class-F {layout_id} role does not contain exactly one measured edge"
        )
    edge = edges[0]
    if edge.get("id") != config["edge_id"]:
        raise ClassFWitnessError(
            f"Class-F {layout_id} role changed its bounded edge identity"
        )
    header = edge.get("header")
    after = edge.get("after")
    if not isinstance(header, dict) or not isinstance(after, dict):
        raise ClassFWitnessError(f"Class-F {layout_id} role has no endpoint header")
    profile_state = header.get("profile_state")
    if (
        not isinstance(profile_state, dict)
        or profile_state.get("profile_state_identity_sha256") != PROFILE_IDENTITY
        or profile_state.get("baseline_id") != "pristine_fresh_install"
        or profile_state.get("durable_file_count") != 0
    ):
        raise ClassFWitnessError(
            f"Class-F {layout_id} role did not use the pinned pristine baseline"
        )
    if after.get("tagged_screen") != config["screen_id"]:
        raise ClassFWitnessError(
            f"Class-F {layout_id} role settled a different native screen"
        )
    layout = after.get("layout")
    trace = after.get("settlement_trace")
    samples = trace.get("settled_window_samples") if isinstance(trace, dict) else None
    if not isinstance(layout, dict) or not isinstance(samples, list):
        raise ClassFWitnessError(f"Class-F {layout_id} role has no settled window")
    if layout.get("screen_id") != config["screen_id"]:
        raise ClassFWitnessError(
            f"Class-F {layout_id} role changed the measured layout screen id"
        )
    if layout.get("screen_title") != candidate_layout.get("screen_title"):
        raise ClassFWitnessError(
            f"Class-F {layout_id} role changed the qualified screen title"
        )
    if len(samples) < 40:
        raise ClassFWitnessError(
            f"Class-F {layout_id} role has fewer than 40 settled samples"
        )
    elapsed = [sample.get("elapsed_milliseconds") for sample in samples]
    if not all(isinstance(value, int) for value in elapsed):
        raise ClassFWitnessError(
            f"Class-F {layout_id} role has an invalid sample clock"
        )
    if elapsed != sorted(elapsed) or elapsed[-1] - elapsed[0] < 2_000:
        raise ClassFWitnessError(
            f"Class-F {layout_id} role does not span the required settled window"
        )
    generations = {
        sample.get("payload", {}).get("generation")
        for sample in samples
        if isinstance(sample, dict) and isinstance(sample.get("payload"), dict)
    }
    if len(generations) != 1 or next(iter(generations)) != layout.get("generation"):
        raise ClassFWitnessError(
            f"Class-F {layout_id} role generation changed within its settled window"
        )
    projections = [
        project_sample(sample, expected_sequence, f"{layout_id} sample {index}")
        for index, sample in enumerate(samples)
    ]
    projection_hashes = {row["projected_core_sha256"] for row in projections}
    if len(projection_hashes) != 1:
        raise ClassFWitnessError(
            f"Class-F {layout_id} role changed its projected core within the window"
        )
    launch = read_object(role_root / "launch.json")
    if (
        launch.get("freshInstall") is not True
        or launch.get("profileStateIdentitySha256") != PROFILE_IDENTITY
    ):
        raise ClassFWitnessError(
            f"Class-F {layout_id} launch receipt lost fresh-install provenance"
        )
    quiescence = read_object(role_root / "host-quiescence-after.json")
    if quiescence.get("quiescent") is not True:
        raise ClassFWitnessError(
            f"Class-F {layout_id} role lacks exact-PID disposal quiescence"
        )
    return {
        "instance": header.get("instance"),
        "process_id": header.get("process_id"),
        "profile_state_identity_sha256": PROFILE_IDENTITY,
        "measured_generation": layout.get("generation"),
        "settled_sample_count": len(samples),
        "settled_span_milliseconds": elapsed[-1] - elapsed[0],
        "projected_core_sha256": next(iter(projection_hashes)),
        "projected_core_element_count": len(expected_sequence),
        "raw_element_count_range": [
            min(row["raw_element_count"] for row in projections),
            max(row["raw_element_count"] for row in projections),
        ],
        "noncore_count_range": [
            min(row["ambient_or_noncore_count"] for row in projections),
            max(row["ambient_or_noncore_count"] for row in projections),
        ],
        "population_phase_generations": _phase_generations(trace),
        "navigation_recording": receipt(navigation_path, evidence_root),
        "launch": receipt(role_root / "launch.json", evidence_root),
        "launch_profile_state": require_receipt(
            role_root / "launch-profile-state.json",
            evidence_root,
            f"{layout_id} launch profile state",
        ),
        "stage_report": require_receipt(
            role_root / "stage-report.json",
            evidence_root,
            f"{layout_id} stage report",
        ),
        "pre_navigation_durable_census": receipt(
            role_root / "pre-navigation-durable-file-census.json", evidence_root
        ),
        "post_capture_durable_census": receipt(
            role_root / "post-capture-durable-file-census.json", evidence_root
        ),
        "exact_pid_disposal": receipt(
            role_root / "exact-pid-disposal.json", evidence_root
        ),
        "host_quiescence_after": receipt(
            role_root / "host-quiescence-after.json", evidence_root
        ),
    }


def build_audit(
    repo_root: Path,
    candidate_root: Path,
    evidence_root: Path,
    capture_root: Path,
) -> dict[str, Any]:
    layouts: dict[str, Any] = {}
    seen_identities: set[tuple[str, int]] = set()
    for layout_id, config in CONFIG.items():
        candidate_path = candidate_root / "menu-layouts" / f"{layout_id}.json"
        candidate = read_object(candidate_path)
        candidate_layout = candidate.get("layout")
        if not isinstance(candidate_layout, dict):
            raise ClassFWitnessError(
                f"Class-F {layout_id} candidate has no qualified layout"
            )
        elements = candidate_layout.get("elements")
        if not isinstance(elements, list) or not elements:
            raise ClassFWitnessError(
                f"Class-F {layout_id} candidate has no structural core"
            )
        expected_sequence = [_signature(element) for element in elements]
        roles = [
            audit_role(
                layout_id=layout_id,
                config=config,
                role_root=capture_root / relative,
                evidence_root=evidence_root,
                expected_sequence=expected_sequence,
                candidate_layout=candidate_layout,
            )
            for relative in config["roles"]
        ]
        identities = {(row["instance"], row["process_id"]) for row in roles}
        if len(identities) != 2 or identities & seen_identities:
            raise ClassFWitnessError(
                f"Class-F {layout_id} pair is not two independent fresh instances"
            )
        seen_identities.update(identities)
        core_hashes = {row["projected_core_sha256"] for row in roles}
        if len(core_hashes) != 1:
            raise ClassFWitnessError(
                f"Class-F {layout_id} paired projected cores differ"
            )
        layouts[layout_id] = {
            "status": "class_f_population_witness_satisfied",
            "qualified_candidate": receipt(candidate_path, evidence_root),
            "qualified_structural_core_sha256": candidate_layout.get(
                "structural_core_sha256"
            ),
            "projected_core_sha256": next(iter(core_hashes)),
            "projected_core_element_count": len(expected_sequence),
            "pair": roles,
            "paired_generations": [row["measured_generation"] for row in roles],
            "landed_generation_selection_performed": False,
            "acceptance_basis": (
                "each fresh instance is individually window-constant and every "
                "settled sample projects with zero residue in the qualified core "
                "direction and an identical relative core sequence"
            ),
            "rejected_wrapper_runs": [
                {
                    "failure": require_receipt(
                        capture_root / relative / "failure.json",
                        evidence_root,
                        f"{layout_id} rejected wrapper run",
                    ),
                    "post_failure_quiescence": require_receipt(
                        capture_root / relative / "host-quiescence-after.json",
                        evidence_root,
                        f"{layout_id} rejected wrapper run quiescence",
                    ),
                }
                for relative in config["rejected_roles"]
            ],
        }
    return {
        "schema": "solomon-dark-native-menu-census-era-class-f-audit-v221",
        "settlement_spec": "2.21",
        "profile_state_identity_sha256": PROFILE_IDENTITY,
        "source_contract": receipt(
            repo_root
            / "tests/fixtures/webgame/native-menu-census-era-disposition-v221.json",
            repo_root,
        ),
        "class_f_layout_count": len(layouts),
        "layouts": layouts,
        "all_pairs_window_constant": True,
        "all_pairs_project_to_exact_qualified_cores": True,
        "counter_shopping_performed": False,
        "candidate_applied": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--capture-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    audit = build_audit(
        args.repo_root.resolve(),
        args.candidate_root.resolve(),
        args.evidence_root.resolve(),
        args.capture_root.resolve(),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(audit, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
                "sha256": hashlib.sha256(args.output.read_bytes()).hexdigest(),
                "bytes": args.output.stat().st_size,
                "class_f_layout_count": audit["class_f_layout_count"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
