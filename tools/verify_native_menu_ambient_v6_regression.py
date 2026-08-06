#!/usr/bin/env python3
"""Reclassify the sealed v6 beta-dialog STOP traces under Settlement v2.5."""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

if __package__:
    from .native_menu_ambient_lifecycle import (
        AmbientLifecycleError,
        canonical_bytes,
        read_samples,
        resolve_ambient_lifecycle,
    )
else:
    from native_menu_ambient_lifecycle import (  # type: ignore[no-redef]
        AmbientLifecycleError,
        canonical_bytes,
        read_samples,
        resolve_ambient_lifecycle,
    )


def _file_receipt(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.resolve()),
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "bytes": path.stat().st_size,
    }


def _ui_semantics(element: dict[str, Any]) -> bytes | None:
    art_id = element.get("art_id")
    if element.get("kind") != "art" or not str(art_id).startswith("UI."):
        return None
    return canonical_bytes(
        {
            key: copy.deepcopy(value)
            for key, value in element.items()
            if key not in {"id", "draw_order", "draw_order_semantics"}
        }
    )


def _stable_ui_counter(samples: list[dict[str, Any]], label: str) -> Counter[bytes]:
    counters = [
        Counter(
            signature
            for element in sample["payload"]["elements"]
            if (signature := _ui_semantics(element)) is not None
        )
        for sample in samples
    ]
    if not counters or not counters[0]:
        raise AmbientLifecycleError(
            f"v6 offline regression: {label} reached no dialog UI draw semantics"
        )
    if any(counter != counters[0] for counter in counters[1:]):
        raise AmbientLifecycleError(
            f"v6 offline regression: {label} dialog UI block is not sample-stable"
        )
    return counters[0]


def verify(args: argparse.Namespace) -> dict[str, Any]:
    primary_samples = read_samples(args.primary)
    confirmation_samples = read_samples(args.confirmation)
    primary_ui = _stable_ui_counter(primary_samples, "primary")
    confirmation_ui = _stable_ui_counter(confirmation_samples, "confirmation")
    if primary_ui != confirmation_ui:
        raise AmbientLifecycleError(
            "v6 offline regression: independent dialog UI blocks differ semantically"
        )
    observations = [
        {
            "label": "sealed-v6-primary",
            "kind": "settled_window",
            "instance": args.primary_instance,
            "process_id": args.primary_process_id,
            "samples": primary_samples,
            "evidence": _file_receipt(args.primary),
        },
        {
            "label": "sealed-v6-confirmation",
            "kind": "settled_window",
            "instance": args.confirmation_instance,
            "process_id": args.confirmation_process_id,
            "samples": confirmation_samples,
            "evidence": _file_receipt(args.confirmation),
        },
    ]
    resolved = resolve_ambient_lifecycle(observations)
    core_ui = Counter(
        signature
        for element in resolved["structural_core"]["elements"]
        if (signature := _ui_semantics(element)) is not None
    )
    if core_ui != primary_ui:
        raise AmbientLifecycleError(
            "v6 offline regression: complete dialog UI block did not enter the "
            "cross-instance structural core"
        )
    return {
        "schema": "solomon-dark-native-menu-v6-ambient-regression-v1",
        "result": "SETTLED",
        "settlement_spec": resolved["settlement_spec"],
        "claims": {
            "formerly_stopping_inputs_settle": True,
            "structural_core_equal_cross_instance": True,
            "complete_dialog_ui_block_in_core": True,
        },
        "dialog_ui_semantic_draw_count": sum(primary_ui.values()),
        "primary_input": _file_receipt(args.primary),
        "confirmation_input": _file_receipt(args.confirmation),
        "resolution": resolved,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--primary", type=Path, required=True)
    parser.add_argument("--confirmation", type=Path, required=True)
    parser.add_argument("--primary-instance", required=True)
    parser.add_argument("--primary-process-id", type=int, required=True)
    parser.add_argument("--confirmation-instance", required=True)
    parser.add_argument("--confirmation-process-id", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        result = verify(args)
    except (AmbientLifecycleError, OSError, ValueError) as error:
        print(f"STOP: {error}")
        return 2
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        "SETTLED: sealed v6 beta-dialog traces reproduce structural core "
        f"{result['resolution']['structural_core_sha256']} with "
        f"{result['dialog_ui_semantic_draw_count']} dialog UI draws in core"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
