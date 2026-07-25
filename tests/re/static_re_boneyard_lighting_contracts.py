"""Static contracts for the recovered Boneyard Tree render-lighting path."""

from pathlib import Path

from static_re_contract_support import ROOT, StaticReTestFailure


def _read(relative_path: str) -> str:
    return (ROOT / Path(relative_path)).read_text(encoding="utf-8")


def test_boneyard_tree_last_writer_render_path_is_registered() -> str:
    findings = _read(
        "docs/reverse-engineering/native-default-boneyard-load-seed-and-decor.md"
    )
    layout = _read("config/binary-layout.ini")

    required_findings = (
        "common scenery render dispatcher",
        "`0x00624B40`",
        "`0x00624C2F`",
        "`0x00624C4E`",
        "`0x00624C89`",
        "`0x00624D3E`",
        "`0x00624DAD`",
        "`0x00624DC7`",
        "overlay entry",
        "`0x00608830`",
        "`0x00608912`",
        "`0x3DD62F07`",
        "`0x3E145B97`",
        "last-writer failure",
    )
    missing_findings = [
        token for token in required_findings if token not in findings
    ]
    if missing_findings:
        raise StaticReTestFailure(
            "Boneyard Tree render-lighting findings are incomplete: "
            + ", ".join(missing_findings)
        )

    required_layout = (
        "scenery_render_lighting=0x00624B40",
        "scenery_render_lighting_common_scalar_write_0=0x00624C2F",
        "scenery_render_lighting_common_scalar_write_1=0x00624C4E",
        "scenery_render_lighting_common_scalar_write_2=0x00624C89",
        "scenery_render_lighting_common_scalar_write_3=0x00624D3E",
        "scenery_render_lighting_common_scalar_write_4=0x00624DAD",
        "scenery_render_lighting_common_scalar_write_5=0x00624DC7",
        "tree_render_overlay=0x00608830",
        "tree_render_overlay_common_scalar_read=0x00608912",
        "boneyard_scenery_common_scalar=0xCC",
    )
    missing_layout = [token for token in required_layout if token not in layout]
    if missing_layout:
        raise StaticReTestFailure(
            "Boneyard Tree render-lighting layout is incomplete: "
            + ", ".join(missing_layout)
        )

    return (
        "Boneyard Tree +0xCC last-writer render path and final overlay read "
        "are documented and registered"
    )
