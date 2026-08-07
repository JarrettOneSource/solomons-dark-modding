#!/usr/bin/env python3
"""Emit a machine-derived audit for a landed-vs-settled core-order STOP."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from native_menu_landed_diagnosis_v25 import (
    LandedDiagnosisError,
    _elements,
    _ordered,
    _signature,
    project_structural_core,
)
from native_menu_overlay_v25 import _reference_counter


def read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} is not a JSON object")
    return value


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def receipt(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.resolve()),
        "sha256": file_sha256(path),
        "bytes": path.stat().st_size,
    }


def evidence_receipt(path: Path, evidence_root: Path) -> dict[str, Any]:
    resolved = path.resolve()
    root = evidence_root.resolve()
    if not resolved.is_relative_to(root):
        raise ValueError(f"manifest artifact escapes evidence root: {resolved}")
    return {
        "path": resolved.relative_to(root).as_posix(),
        "bytes": resolved.stat().st_size,
        "sha256": file_sha256(resolved),
    }


def witness(element: dict[str, Any], index: int) -> dict[str, Any]:
    return {
        "relative_core_index": index,
        "id": element.get("id"),
        "kind": element.get("kind"),
        "art_id": element.get("art_id"),
        "text": element.get("text"),
        "action_id": element.get("action_id"),
        "rect": element.get("rect"),
        "unclipped_rect": element.get("unclipped_rect"),
        "captured_draw_order": element.get("draw_order"),
        "semantic_sha256": hashlib.sha256(_signature(element)).hexdigest(),
    }


def lcs_indexes(
    left: list[bytes], right: list[bytes]
) -> tuple[set[int], set[int]]:
    lengths = [[0] * (len(right) + 1) for _ in range(len(left) + 1)]
    for left_index in range(len(left) - 1, -1, -1):
        for right_index in range(len(right) - 1, -1, -1):
            lengths[left_index][right_index] = (
                1 + lengths[left_index + 1][right_index + 1]
                if left[left_index] == right[right_index]
                else max(
                    lengths[left_index + 1][right_index],
                    lengths[left_index][right_index + 1],
                )
            )
    left_indexes: set[int] = set()
    right_indexes: set[int] = set()
    left_index = right_index = 0
    while left_index < len(left) and right_index < len(right):
        if left[left_index] == right[right_index]:
            left_indexes.add(left_index)
            right_indexes.add(right_index)
            left_index += 1
            right_index += 1
        elif lengths[left_index + 1][right_index] >= lengths[left_index][right_index + 1]:
            left_index += 1
        else:
            right_index += 1
    return left_indexes, right_indexes


def build_audit(
    landed_path: Path,
    settled_path: Path,
    overlay_path: Path,
    primary_trace_path: Path,
    confirmation_trace_path: Path,
    layout_id: str,
) -> dict[str, Any]:
    landed_golden = read_object(landed_path)
    landed_matches = [
        entry
        for entry in landed_golden.get("layouts", [])
        if isinstance(entry, dict)
        and Path(str(entry.get("fixture", ""))).stem == layout_id
    ]
    if len(landed_matches) != 1:
        raise ValueError(f"landed layout lookup for {layout_id!r} is ambiguous")
    landed = landed_matches[0].get("layout")
    settled_fixture = read_object(settled_path)
    settled = settled_fixture.get("layout")
    if not isinstance(landed, dict) or not isinstance(settled, dict):
        raise ValueError("landed or settled layout is absent")

    expected_error = ""
    try:
        project_structural_core(landed, settled)
    except LandedDiagnosisError as error:
        expected_error = str(error)
    if expected_error != (
        "landed-vs-settled structural core mismatch: core relative draw sequence differs"
    ):
        raise ValueError(
            "audit no longer reproduces the named core relative-order STOP"
        )

    settled_elements = _elements(settled, "settled structural core")
    remaining: dict[bytes, int] = {}
    for element in settled_elements:
        signature = _signature(element)
        remaining[signature] = remaining.get(signature, 0) + 1
    projected: list[dict[str, Any]] = []
    residual: list[dict[str, Any]] = []
    for element in _ordered(_elements(landed, "landed layout"), "landed layout"):
        signature = _signature(element)
        if remaining.get(signature, 0) > 0:
            remaining[signature] -= 1
            projected.append(element)
        else:
            residual.append(element)
    if any(remaining.values()):
        raise ValueError("audit projection lost one or more settled members")

    projected_signatures = [_signature(element) for element in projected]
    settled_signatures = [_signature(element) for element in settled_elements]
    kept_projected, kept_settled = lcs_indexes(
        projected_signatures, settled_signatures
    )
    moved_projected = [
        index for index in range(len(projected)) if index not in kept_projected
    ]
    moved_settled = [
        index
        for index in range(len(settled_elements))
        if index not in kept_settled
    ]
    overlay_counter = _reference_counter(read_object(overlay_path), "audit")
    moved: list[dict[str, Any]] = []
    available_new = list(moved_settled)
    for old_index in moved_projected:
        signature = projected_signatures[old_index]
        matches = [
            index
            for index in available_new
            if settled_signatures[index] == signature
        ]
        if len(matches) != 1:
            raise ValueError("moved core member does not map unambiguously")
        new_index = matches[0]
        available_new.remove(new_index)
        item = witness(projected[old_index], old_index)
        item["settled_relative_core_index"] = new_index
        item["overlay_reference_member"] = overlay_counter[signature] > 0
        moved.append(item)

    header = settled_fixture.get("header")
    settlement = header.get("settlement") if isinstance(header, dict) else None
    generation_evidence: list[dict[str, Any]] = []
    for label, trace_path in (
        ("primary", primary_trace_path),
        ("confirmation", confirmation_trace_path),
    ):
        trace = read_object(trace_path)
        phases = trace.get("structural_phases")
        settled_samples = trace.get("settled_window_samples")
        if (
            not isinstance(phases, list)
            or not phases
            or not isinstance(settled_samples, list)
            or not settled_samples
        ):
            raise ValueError(f"{label} trace has no population/settled evidence")
        phase_generations = sorted(
            {
                phase.get("payload", {}).get("generation")
                for phase in phases
                if isinstance(phase, dict)
                and isinstance(phase.get("payload"), dict)
            }
        )
        settled_generations = sorted(
            {
                sample.get("payload", {}).get("generation")
                for sample in settled_samples
                if isinstance(sample, dict)
                and isinstance(sample.get("payload"), dict)
            }
        )
        generation_evidence.append(
            {
                "side": label,
                "trace": receipt(trace_path),
                "structural_phase_count": len(phases),
                "structural_phase_generations": phase_generations,
                "settled_sample_count": len(settled_samples),
                "settled_generations": settled_generations,
                "landed_generation_witnessed": landed.get("generation")
                in phase_generations,
            }
        )
    return {
        "schema": "solomon-dark-native-menu-landed-core-order-stop-audit-v1",
        "layout_id": layout_id,
        "finding": (
            "landed_core_relative_order_mismatch_with_unwitnessed_generation"
        ),
        "stop_message": expected_error,
        "inputs": {
            "landed_menu_golden": receipt(landed_path),
            "settled_fixture": receipt(settled_path),
            "derived_overlay_reference": receipt(overlay_path),
            "primary_trace": receipt(primary_trace_path),
            "confirmation_trace": receipt(confirmation_trace_path),
        },
        "landed": {
            "generation": landed.get("generation"),
            "element_count": len(_elements(landed, "landed layout")),
            "projected_core_element_count": len(projected),
            "projected_core_sequence_sha256": hashlib.sha256(
                b"".join(projected_signatures)
            ).hexdigest(),
        },
        "settled": {
            "generation": settled.get("generation"),
            "structural_core_element_count": len(settled_elements),
            "structural_core_sha256": settled.get("structural_core_sha256"),
            "structural_core_sequence_sha256": hashlib.sha256(
                b"".join(settled_signatures)
            ).hexdigest(),
            "settlement": settlement,
        },
        "semantic_members_missing_from_landed": 0,
        "landed_residual_member_count": len(residual),
        "longest_common_subsequence_count": len(kept_projected),
        "moved_core_member_count": len(moved),
        "moved_core_members": moved,
        "all_moved_members_belong_to_derived_overlay_reference": bool(moved)
        and all(item["overlay_reference_member"] for item in moved),
        "population_generation_evidence": generation_evidence,
        "landed_generation_witnessed_in_both_population_traces": all(
            entry["landed_generation_witnessed"]
            for entry in generation_evidence
        ),
        "decision_required": (
            "No v2.1-v2.8 override authorizes this historical structural-core "
            "relative-order change: the landed generation is absent from both "
            "fresh population traces, and overlay correction authorizes exact "
            "semantic subtraction rather than reordering members retained on "
            "the beta_notice reference screen."
        ),
    }


def write_object(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def write_stop_manifest(
    path: Path,
    evidence_root: Path,
    repo_root: Path,
    audit_path: Path,
    transcript_path: Path,
    quiescence_path: Path,
    artifact_paths: list[Path],
) -> None:
    quiescence = read_object(quiescence_path)
    if quiescence.get("quiescent") is not True:
        raise ValueError("host quiescence evidence is not green")
    generator_copy = path.parent / "generate_beta_notice_core_order_stop.py"
    temporary = generator_copy.with_name(generator_copy.name + ".tmp")
    shutil.copyfile(Path(__file__).resolve(), temporary)
    os.replace(temporary, generator_copy)
    head = subprocess.run(
        ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    all_artifacts = [
        audit_path,
        generator_copy,
        transcript_path,
        quiescence_path,
        *artifact_paths,
    ]
    resolved = [artifact.resolve() for artifact in all_artifacts]
    if len(resolved) != len(set(resolved)) or not all(
        artifact.is_file() for artifact in resolved
    ):
        raise ValueError("stop manifest artifact census is absent or ambiguous")
    manifest = {
        "schema": "solomon-dark-menufix-stop-manifest-v2",
        "generated_at_utc": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "status": "STOP",
        "settlement_spec": "2.8",
        "campaign_clone_head": head,
        "finding": (
            "beta-notice landed generation 13 projects all 34 settled core "
            "members but orders the dialog-button UI.101/UI.54/UI.54 trio at "
            "core slots 8-10 instead of the reproduced slots 31-33; neither "
            "fresh population trace witnesses generation 13"
        ),
        "promoter_exit_code": 1,
        "repo_fixture_promotion_performed": False,
        "host_quiescent": True,
        "artifacts": [
            evidence_receipt(artifact, evidence_root) for artifact in resolved
        ],
    }
    write_object(path, manifest)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--landed-menu-golden", type=Path, required=True)
    parser.add_argument("--settled-fixture", type=Path, required=True)
    parser.add_argument("--overlay-reference", type=Path, required=True)
    parser.add_argument("--primary-trace", type=Path, required=True)
    parser.add_argument("--confirmation-trace", type=Path, required=True)
    parser.add_argument("--layout-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--stop-manifest", type=Path)
    parser.add_argument("--evidence-root", type=Path)
    parser.add_argument("--repo-root", type=Path)
    parser.add_argument("--promoter-transcript", type=Path)
    parser.add_argument("--host-quiescence", type=Path)
    parser.add_argument("--manifest-artifact", type=Path, action="append", default=[])
    args = parser.parse_args()
    try:
        audit = build_audit(
            args.landed_menu_golden.resolve(),
            args.settled_fixture.resolve(),
            args.overlay_reference.resolve(),
            args.primary_trace.resolve(),
            args.confirmation_trace.resolve(),
            args.layout_id,
        )
        write_object(args.output.resolve(), audit)
        manifest_inputs = (
            args.stop_manifest,
            args.evidence_root,
            args.repo_root,
            args.promoter_transcript,
            args.host_quiescence,
        )
        if any(value is not None for value in manifest_inputs):
            if not all(value is not None for value in manifest_inputs):
                raise ValueError("stop manifest arguments must be supplied together")
            write_stop_manifest(
                args.stop_manifest.resolve(),
                args.evidence_root.resolve(),
                args.repo_root.resolve(),
                args.output.resolve(),
                args.promoter_transcript.resolve(),
                args.host_quiescence.resolve(),
                [path.resolve() for path in args.manifest_artifact],
            )
    except (KeyError, LandedDiagnosisError, OSError, TypeError, ValueError) as error:
        print(json.dumps({"success": False, "error": str(error)}))
        return 1
    print(
        json.dumps(
            {
                "success": True,
                "output": str(args.output.resolve()),
                "sha256": file_sha256(args.output.resolve()),
                "moved_core_member_count": audit["moved_core_member_count"],
                **(
                    {
                        "stop_manifest": str(args.stop_manifest.resolve()),
                        "stop_manifest_sha256": file_sha256(
                            args.stop_manifest.resolve()
                        ),
                    }
                    if args.stop_manifest is not None
                    else {}
                ),
            },
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
