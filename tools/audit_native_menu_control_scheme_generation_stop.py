#!/usr/bin/env python3
"""Derive the fail-closed Control Scheme Picker generation-only STOP audit."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import Counter
from pathlib import Path
from typing import Any

from native_menu_landed_diagnosis_v25 import (
    LandedDiagnosisError,
    _signature,
    project_structural_core,
)


class ControlSchemeGenerationAuditError(RuntimeError):
    """The observed data does not reproduce the generation-only STOP."""


def read_object(path: Path, label: str) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ControlSchemeGenerationAuditError(f"{label} is not a JSON object")
    return value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def receipt(path: Path, root: Path) -> dict[str, Any]:
    resolved = path.resolve()
    base = root.resolve()
    if not resolved.is_relative_to(base):
        raise ControlSchemeGenerationAuditError(
            f"evidence receipt {resolved} escapes {base}"
        )
    return {
        "evidence_path": resolved.relative_to(base).as_posix(),
        "sha256": sha256_file(resolved),
        "bytes": resolved.stat().st_size,
    }


def file_receipt(path: Path, repo_root: Path) -> dict[str, Any]:
    resolved = path.resolve()
    root = repo_root.resolve()
    if not resolved.is_relative_to(root):
        raise ControlSchemeGenerationAuditError(
            f"repository receipt {resolved} escapes {root}"
        )
    return {
        "repo_relative_path": resolved.relative_to(root).as_posix(),
        "sha256": sha256_file(resolved),
        "bytes": resolved.stat().st_size,
    }


def semantic_multiset(layout: dict[str, Any]) -> Counter[bytes]:
    elements = layout.get("elements")
    if not isinstance(elements, list) or not elements or not all(
        isinstance(element, dict) for element in elements
    ):
        raise ControlSchemeGenerationAuditError(
            "Control Scheme Picker semantic sweep reached no element objects"
        )
    return Counter(_signature(element) for element in elements)


def canonical_sha256(value: Any) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def semantic_identity(layout: dict[str, Any]) -> str:
    counter = semantic_multiset(layout)
    entries = [
        {
            "count": counter[signature],
            "payload": json.loads(signature.decode("utf-8")),
        }
        for signature in sorted(counter)
    ]
    return canonical_sha256(
        {
            "screen_id": layout.get("screen_id"),
            "screen_title": layout.get("screen_title"),
            "elements": entries,
        }
    )


def settled_trace_identity(trace: dict[str, Any], label: str) -> dict[str, Any]:
    samples = trace.get("settled_window_samples")
    header = trace.get("header")
    if (
        not isinstance(samples, list)
        or len(samples) < 40
        or not all(isinstance(sample, dict) for sample in samples)
        or not isinstance(header, dict)
    ):
        raise ControlSchemeGenerationAuditError(
            f"{label} did not reach 40 real settled samples"
        )
    span = samples[-1].get("elapsed_milliseconds", 0) - samples[0].get(
        "elapsed_milliseconds", 0
    )
    if span < 2000:
        raise ControlSchemeGenerationAuditError(
            f"{label} settled window spans less than two seconds"
        )
    payloads = [sample.get("payload") for sample in samples]
    if not all(isinstance(payload, dict) for payload in payloads):
        raise ControlSchemeGenerationAuditError(
            f"{label} settled samples have no semantic payloads"
        )
    generations = {payload.get("generation") for payload in payloads}
    surfaces = {sample.get("semantic_surface") for sample in samples}
    semantic_generations = {sample.get("semantic_generation") for sample in samples}
    if (
        len(generations) != 1
        or len(surfaces) != 1
        or len(semantic_generations) != 1
        or surfaces != {"control_scheme_picker"}
    ):
        raise ControlSchemeGenerationAuditError(
            f"{label} did not settle on one Control Scheme Picker generation"
        )
    profile = header.get("profile_state")
    source = header.get("source")
    if (
        not isinstance(profile, dict)
        or not isinstance(source, dict)
        or profile.get("baseline_id") != "pristine_fresh_install"
        or source.get("profile_state_identity_sha256")
        != profile.get("profile_state_identity_sha256")
    ):
        raise ControlSchemeGenerationAuditError(
            f"{label} lost machine-derived pristine profile provenance"
        )
    semantic_hashes = {semantic_identity(payload) for payload in payloads}
    if len(semantic_hashes) != 1:
        raise ControlSchemeGenerationAuditError(
            f"{label} structural core varied inside the settled window"
        )
    return {
        "instance": header.get("instance"),
        "process_id": header.get("process_id"),
        "sample_count": len(samples),
        "stable_span_milliseconds": span,
        "layout_generation": next(iter(generations)),
        "semantic_generation": next(iter(semantic_generations)),
        "semantic_surface": next(iter(surfaces)),
        "element_count": len(payloads[0]["elements"]),
        "semantic_multiset_sha256": next(iter(semantic_hashes)),
        "profile_state_identity_sha256": profile.get(
            "profile_state_identity_sha256"
        ),
        "source": source,
    }


def build(
    repo_root: Path,
    candidate_root: Path,
    evidence_root: Path,
    navigation_path: Path,
    promoter_log: Path,
) -> dict[str, Any]:
    layout_name = "control-scheme-picker.json"
    landed_path = repo_root / "tests/fixtures/webgame/menu-layouts" / layout_name
    candidate_path = candidate_root / "menu-layouts" / layout_name
    primary_path = (
        candidate_root
        / "menu-settlement-traces/control-scheme-picker.settlement.json"
    )
    confirmation_path = (
        candidate_root
        / "menu-animation-confirmations/control-scheme-picker.confirmation.json"
    )
    composite_path = (
        candidate_root / "menu-dialog-composites/beta-notice-first-boot.json"
    )
    paths = (
        landed_path,
        candidate_path,
        primary_path,
        confirmation_path,
        composite_path,
        navigation_path,
        promoter_log,
    )
    if any(not path.is_file() for path in paths):
        raise ControlSchemeGenerationAuditError(
            "generation-only STOP audit did not reach every named witness"
        )
    landed = read_object(landed_path, "landed Control Scheme Picker fixture")
    candidate = read_object(candidate_path, "candidate Control Scheme Picker fixture")
    landed_layout = landed.get("layout")
    candidate_layout = candidate.get("layout")
    if not isinstance(landed_layout, dict) or not isinstance(candidate_layout, dict):
        raise ControlSchemeGenerationAuditError(
            "Control Scheme Picker fixture has no layout payload"
        )
    try:
        projected, residual = project_structural_core(
            landed_layout, candidate_layout
        )
    except LandedDiagnosisError as error:
        raise ControlSchemeGenerationAuditError(
            "Control Scheme Picker differs outside layout generation"
        ) from error
    if residual or semantic_multiset(landed_layout) != semantic_multiset(
        candidate_layout
    ):
        raise ControlSchemeGenerationAuditError(
            "Control Scheme Picker leaves a structural member residual"
        )
    differing_layout_fields = sorted(
        field
        for field in set(landed_layout) | set(candidate_layout)
        if field in {"screen_id", "screen_title", "generation"}
        and landed_layout.get(field) != candidate_layout.get(field)
    )
    if differing_layout_fields != ["generation"]:
        raise ControlSchemeGenerationAuditError(
            "Control Scheme Picker mismatch is not confined to generation"
        )
    landed_semantic_identity = semantic_identity(landed_layout)
    candidate_semantic_identity = semantic_identity(candidate_layout)
    if landed_semantic_identity != candidate_semantic_identity:
        raise ControlSchemeGenerationAuditError(
            "Control Scheme Picker landed and candidate semantic identities differ"
        )
    primary = settled_trace_identity(
        read_object(primary_path, "primary picker trace"), "primary picker trace"
    )
    confirmation = settled_trace_identity(
        read_object(confirmation_path, "confirmation picker trace"),
        "confirmation picker trace",
    )
    if (
        (primary["instance"], primary["process_id"])
        == (confirmation["instance"], confirmation["process_id"])
        or primary["semantic_multiset_sha256"]
        != confirmation["semantic_multiset_sha256"]
        or primary["semantic_multiset_sha256"] != candidate_semantic_identity
        or primary["layout_generation"] != confirmation["layout_generation"]
        or primary["source"] != confirmation["source"]
        or primary["profile_state_identity_sha256"]
        != confirmation["profile_state_identity_sha256"]
    ):
        raise ControlSchemeGenerationAuditError(
            "Control Scheme Picker candidate did not reproduce in two fresh instances"
        )
    log_text = promoter_log.read_text(encoding="utf-8-sig").strip()
    expected_stop = (
        "STOP: standalone control-scheme-picker: landed-vs-settled generation "
        "changed without an authorized differing member"
    )
    if expected_stop not in log_text:
        raise ControlSchemeGenerationAuditError(
            "promoter transcript does not contain the exact generation-only STOP"
        )
    composite = read_object(composite_path, "v2.17 composite record")
    underlay_binding = composite.get("composite", {}).get("underlay_binding")
    if (
        not isinstance(underlay_binding, dict)
        or underlay_binding.get("fixture", {}).get("sha256")
        != sha256_file(candidate_path)
        or underlay_binding.get("member_count") != len(projected)
    ):
        raise ControlSchemeGenerationAuditError(
            "v2.17 composite does not bind the exact qualified picker core"
        )
    navigation = read_object(navigation_path, "resolved navigation graph")
    endpoints: list[dict[str, Any]] = []
    edges = navigation.get("edges")
    if not isinstance(edges, list) or not edges:
        raise ControlSchemeGenerationAuditError(
            "picker endpoint sweep reached no navigation edges"
        )
    for edge in edges:
        if not isinstance(edge, dict):
            continue
        for side in ("before", "after"):
            endpoint = edge.get(side)
            if (
                isinstance(endpoint, dict)
                and endpoint.get("layout_id") == "control-scheme-picker"
            ):
                layout = endpoint.get("layout")
                if not isinstance(layout, dict):
                    raise ControlSchemeGenerationAuditError(
                        "picker navigation endpoint has no layout payload"
                    )
                endpoints.append(
                    {
                        "edge_id": edge.get("id"),
                        "side": side,
                        "trigger": edge.get("trigger"),
                        "layout_generation": layout.get("generation"),
                        "element_count": len(layout.get("elements", [])),
                        "semantic_multiset_sha256": semantic_identity(layout),
                    }
                )
    if not endpoints:
        raise ControlSchemeGenerationAuditError(
            "picker endpoint sweep reached no Control Scheme Picker binding"
        )
    if any(
        endpoint["semantic_multiset_sha256"] != candidate_semantic_identity
        for endpoint in endpoints
    ):
        raise ControlSchemeGenerationAuditError(
            "picker navigation endpoint does not equal the settled standalone core"
        )
    return {
        "schema": "solomon-dark-control-scheme-picker-generation-question-v1",
        "status": "QUESTION",
        "candidate_applied": False,
        "finding": (
            "the two-instance settled Control Scheme Picker candidate has the exact "
            "landed structural member multiset and relative sequence, but its "
            "path-local layout generation differs from the landed fixture"
        ),
        "promoter_stop": expected_stop,
        "differing_layout_fields": differing_layout_fields,
        "landed": {
            "fixture": file_receipt(landed_path, repo_root),
            "generation": landed_layout.get("generation"),
            "element_count": len(landed_layout.get("elements", [])),
            "semantic_multiset_sha256": landed_semantic_identity,
        },
        "candidate": {
            "fixture": receipt(candidate_path, evidence_root),
            "generation": candidate_layout.get("generation"),
            "element_count": len(candidate_layout.get("elements", [])),
            "projected_core_element_count": len(projected),
            "landed_residual_count": len(residual),
            "semantic_multiset_sha256": candidate_semantic_identity,
            "primary": primary,
            "confirmation": confirmation,
        },
        "v2_17_composite_underlay_binding": {
            "record": receipt(composite_path, evidence_root),
            "underlay_binding": underlay_binding,
        },
        "existing_navigation_endpoints": endpoints,
        "receipts": {
            "primary_trace": receipt(primary_path, evidence_root),
            "confirmation_trace": receipt(confirmation_path, evidence_root),
            "resolved_navigation": receipt(navigation_path, evidence_root),
            "promoter_stop": receipt(promoter_log, evidence_root),
        },
        "decision_boundary": {
            "possible_capture_path_metadata_rule": (
                "exclude absolute layout generation from landed cross-path identity "
                "while retaining per-window and paired-instance constancy"
            ),
            "possible_path_qualified_fixture_rule": (
                "retain generation as contractual and qualify the Picker by entry path"
            ),
            "forbidden_without_ruling": [
                "silently ignore the generation mismatch",
                "hand-edit the candidate generation",
                "select a capture solely because its counter matches landed",
                "promote any fixture or aggregate",
            ],
        },
    }


def write_atomically(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    os.replace(temporary, path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, required=True)
    parser.add_argument("--candidate-root", type=Path, required=True)
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--navigation-recording", type=Path, required=True)
    parser.add_argument("--promoter-log", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        audit = build(
            args.repo_root.resolve(),
            args.candidate_root.resolve(),
            args.evidence_root.resolve(),
            args.navigation_recording.resolve(),
            args.promoter_log.resolve(),
        )
        write_atomically(args.output.resolve(), audit)
    except (
        ControlSchemeGenerationAuditError,
        OSError,
        KeyError,
        TypeError,
        ValueError,
    ) as error:
        print(json.dumps({"success": False, "error": str(error)}))
        return 1
    print(
        json.dumps(
            {
                "success": True,
                "output": str(args.output.resolve()),
                "sha256": sha256_file(args.output.resolve()),
                "bytes": args.output.resolve().stat().st_size,
            },
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
