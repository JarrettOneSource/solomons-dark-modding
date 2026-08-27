# Catalog every recovered stock rendering seam and all of its direct xrefs.
#
# Usage:
#   -postScript .../catalog_full_render_pipeline.py --json C:\\path\\catalog.json
#
# This is deliberately broader than catalog_renderer_callers.py.  It owns the
# complete Graphics/App/D3D pipeline boundary: application frame dispatch,
# renderer lifecycle, primitives, transforms/clipping, texture residency,
# render targets, fixed-function state, and the two compiled pixel shaders.
# @category: Analysis

import json

from ghidra.program.model.address import Address
from ghidra.program.model.scalar import Scalar


TARGET_GROUPS = [
    ("application_frame", [
        ("0x0040D230", "App_RenderFrame"),
        ("0x0040D2C0", "App_BeginRender"),
        ("0x0040D310", "App_RenderSurfaces"),
        ("0x0040D350", "App_EndRender"),
        ("0x004284B0", "ObjectManager_TickSurfaces"),
        ("0x004285B0", "ObjectManager_RenderSurfaces"),
        ("0x004278C0", "Object_RenderTree"),
    ]),
    ("graphics_lifecycle", [
        ("0x0041C780", "Graphics_Constructor"),
        ("0x0041CE20", "Graphics_Initialize"),
        ("0x0041D000", "Graphics_BeginFrameReset"),
        ("0x0041D2C0", "Graphics_EndFrame"),
        ("0x0041D840", "Graphics_Clear"),
        ("0x0041D8F0", "Graphics_Flush"),
    ]),
    ("sprite_entry", [
        ("0x004143D0", "Glyph_Draw"),
        ("0x00414540", "Sprite_DrawTransformed"),
        ("0x00414710", "Sprite_DrawArbitraryQuad"),
        ("0x00414EA0", "Sprite_DrawScaled"),
        ("0x00415130", "Text_Draw"),
    ]),
    ("primitive", [
        ("0x0041DA00", "Graphics_DrawIndexedMesh"),
        ("0x0041DD70", "Graphics_DrawSolidQuad"),
        ("0x0041DF10", "Graphics_DrawVerticalColorQuad"),
        ("0x0041E250", "Graphics_DrawHorizontalColorQuad"),
        ("0x0041E590", "Graphics_DrawBorderedColorQuad"),
        ("0x0041E990", "Graphics_DrawTexturedQuad"),
        ("0x0041EAE0", "Graphics_DrawTexturedVerticalColorQuad"),
        ("0x0041ED30", "Graphics_DrawTexturedHorizontalColorQuad"),
        ("0x0041EF80", "Graphics_DrawTexturedVertexColorQuad"),
        ("0x0041F310", "Graphics_DrawSolidLine"),
        ("0x0041F5D0", "Graphics_DrawTexturedLine"),
        ("0x0041F830", "Graphics_DrawTexturedGradientLine"),
        ("0x0041FB90", "Graphics_DrawGradientLine"),
    ]),
    ("color_and_state", [
        ("0x0041FE50", "Graphics_SetColor"),
        ("0x0041FF60", "Graphics_SetColorMultiplier"),
        ("0x00420030", "Graphics_BindTexture"),
        ("0x004208A0", "Graphics_DispatchState"),
        ("0x00421560", "Graphics_SetFilter"),
    ]),
    ("transform_and_clip", [
        ("0x00420AC0", "Graphics_SetWorldMatrix"),
        ("0x00420B10", "Graphics_SetWorldMatrixAroundPivot"),
        ("0x00420C60", "Graphics_CopyWorldMatrix"),
        ("0x00420CA0", "Graphics_ResetWorldMatrix"),
        ("0x00420D00", "Graphics_ResetTextureMatrix0"),
        ("0x00420DA0", "Graphics_ResetTextureMatrix1"),
        ("0x00420E40", "Graphics_DisableClip"),
        ("0x00420EC0", "Graphics_SetClip"),
        ("0x00421050", "Graphics_IntersectClip"),
        ("0x00421270", "Graphics_SetAbsoluteClip"),
        ("0x00421380", "Graphics_PopClip"),
    ]),
    ("texture_and_target", [
        ("0x0041FFE0", "Graphics_RegisterTexture"),
        ("0x00420140", "Graphics_LoadTexture"),
        ("0x00420640", "Graphics_UploadTextureMode1"),
        ("0x004206A0", "Graphics_UploadTextureMode2"),
        ("0x00420700", "Graphics_CreateRenderTexture"),
        ("0x00420760", "Graphics_ReleaseTexture"),
        ("0x00420840", "Graphics_GetTextureDimensions"),
        ("0x00421430", "Graphics_EndRenderToTexture"),
        ("0x00421480", "Graphics_GetRenderToPixels"),
        ("0x004214C0", "Graphics_BeginRenderToTexture"),
        ("0x00441180", "D3D_CreateTexture"),
        ("0x00441330", "D3D_RenewTexture"),
        ("0x00441420", "D3D_CreateRenderTexture"),
        ("0x004417F0", "D3D_BindTexture"),
    ]),
    ("shader", [
        ("0x0043FD80", "D3D_CompilePixelShaders"),
        ("0x00442AF0", "D3D_SelectBlurShader"),
    ]),
    ("device", [
        ("0x0043FAD0", "D3D_SetAlphaTest"),
        ("0x0043FB60", "D3D_ResetFixedFunctionState"),
        ("0x0043FF70", "D3D_CreateDevice"),
        ("0x00440520", "D3D_RestoreBackbuffer"),
        ("0x004405D0", "D3D_ResetDevice"),
        ("0x00440890", "D3D_SetViewport"),
        ("0x00440A30", "D3D_SetTargetDimensions"),
        ("0x00440B40", "D3D_Present"),
        ("0x00440BA0", "D3D_SetTransformProgram"),
        ("0x00440D40", "D3D_Clear"),
        ("0x00442810", "D3D_SetScissor"),
        ("0x00442BF0", "D3D_SetRenderTarget"),
        ("0x00442D90", "D3D_ReadRenderTarget"),
        ("0x00442E70", "D3D_SetClampAddressing"),
        ("0x00442ED0", "D3D_SetWrapAddressing"),
        ("0x00442F30", "D3D_SetDepthRange"),
    ]),
    ("scene_root", [
        ("0x005BCA40", "MyLoader_Render"),
        ("0x004D5F40", "Bonedit_Render"),
        ("0x0046EC80", "Arena_Render"),
        ("0x00470EE0", "Arena_RenderWorld"),
        ("0x0050EAC0", "Mortuary_Render"),
        ("0x00511320", "Library_Render"),
        ("0x00519070", "Storeroom_Render"),
        ("0x00519E40", "Office_Render"),
        ("0x0051EB60", "Courtyard_Render"),
        ("0x00512060", "Game_RenderHudDispatch"),
        ("0x005D2520", "Game_RenderHud"),
        ("0x00594FC0", "DarkCloudBrowser_Render"),
        ("0x00598780", "MainMenu_Render"),
        ("0x005A2C80", "HallOfFame_Render"),
        ("0x0058EA50", "PauseMenu_Render"),
        ("0x005D9A50", "Settings_Render"),
        ("0x005DAEF0", "Controls_Render"),
        ("0x005B9A30", "ControlSchemePicker_Render"),
        ("0x004FA460", "SpellPicker_Render"),
        ("0x005C9030", "GameOver_Render"),
        ("0x005BED10", "Portrait_Render"),
    ]),
    ("direct_device_global", [
        ("0x00B401E8", "D3D9_Device_Global"),
    ]),
]

RENDERER_STATE_OFFSETS = {
    0x221: "blend_selector",
    0x223: "texture_color_selector",
    0x239: "texture_address_selector",
    0x3F8: "arena_saturation_request_from_app_base",
}


def parse_arguments():
    values = []
    for argument in getScriptArgs():
        values.extend(value.strip() for value in argument.split(";") if value.strip())
    if len(values) != 2 or values[0] != "--json":
        print("ERROR: expected --json <path>")
        raise SystemExit(1)
    return values[1]


def catalog_target(function_manager, address_text, semantic_name):
    address = toAddr(address_text)
    function = function_manager.getFunctionAt(address)
    native_name = function.getName() if function is not None else None
    callers = {}
    orphan_sites = []
    reference_count = 0
    for reference in getReferencesTo(address):
        reference_count += 1
        site = reference.getFromAddress()
        caller = function_manager.getFunctionContaining(site)
        if caller is None:
            orphan_sites.append(site)
            continue
        key = str(caller.getEntryPoint())
        if key not in callers:
            callers[key] = {"function": caller, "sites": []}
        callers[key]["sites"].append(site)

    return {
        "address": "0x%s" % str(address).upper(),
        "semantic_name": semantic_name,
        "native_name": native_name,
        "reference_count": reference_count,
        "callers": [
            {
                "address": "0x%s" % str(callers[key]["function"].getEntryPoint()).upper(),
                "name": callers[key]["function"].getName(),
                "callsites": [
                    "0x%s" % str(site).upper()
                    for site in sorted(callers[key]["sites"], key=lambda value: str(value))
                ],
            }
            for key in sorted(callers)
        ],
        "orphan_sites": [
            "0x%s" % str(site).upper()
            for site in sorted(orphan_sites, key=lambda value: str(value))
        ],
    }


def references_address(instruction, address):
    for reference in instruction.getReferencesFrom():
        if reference.getToAddress() == address:
            return True
    for operand_index in range(instruction.getNumOperands()):
        for obj in instruction.getOpObjects(operand_index):
            if isinstance(obj, Address) and obj == address:
                return True
    return False


def destination_offsets(instruction):
    if instruction.getNumOperands() < 1:
        return []
    values = []
    for obj in instruction.getOpObjects(0):
        if isinstance(obj, Scalar):
            value = obj.getUnsignedValue()
            if value in RENDERER_STATE_OFFSETS:
                values.append(value)
    return sorted(set(values))


def catalog_renderer_state_writes(function_manager):
    listing = currentProgram.getListing()
    renderer_global = toAddr("0x00B401A8")
    results = []
    functions = function_manager.getFunctions(True)
    while functions.hasNext():
        function = functions.next()
        instructions = list(listing.getInstructions(function.getBody(), True))
        if not any(references_address(instruction, renderer_global) for instruction in instructions):
            continue
        for instruction in instructions:
            if instruction.getMnemonicString() not in ("MOV", "FST", "FSTP"):
                continue
            offsets = destination_offsets(instruction)
            if not offsets:
                continue
            destination = instruction.getDefaultOperandRepresentation(0)
            if "[" not in destination:
                continue
            if "ESP" in destination or "EBP" in destination:
                continue
            source = None
            if instruction.getNumOperands() > 1:
                source = instruction.getDefaultOperandRepresentation(1)
            for offset in offsets:
                results.append({
                    "address": "0x%s" % str(instruction.getAddress()).upper(),
                    "destination": destination,
                    "field": RENDERER_STATE_OFFSETS[offset],
                    "function": "0x%s" % str(function.getEntryPoint()).upper(),
                    "function_name": function.getName(),
                    "instruction": str(instruction),
                    "offset": "0x%X" % offset,
                    "source": source,
                })
    results.sort(key=lambda value: value["address"])
    return results


json_path = parse_arguments()
function_manager = currentProgram.getFunctionManager()
state_writes = catalog_renderer_state_writes(function_manager)
groups = []
all_callers = {}
target_count = 0
reference_count = 0

for group_name, target_specs in TARGET_GROUPS:
    targets = []
    for address_text, semantic_name in target_specs:
        target = catalog_target(function_manager, address_text, semantic_name)
        targets.append(target)
        target_count += 1
        reference_count += target["reference_count"]
        for caller in target["callers"]:
            key = caller["address"]
            if key not in all_callers:
                all_callers[key] = {"address": key, "name": caller["name"], "targets": []}
            all_callers[key]["targets"].append({
                "group": group_name,
                "address": target["address"],
                "semantic_name": semantic_name,
                "callsites": caller["callsites"],
            })
    groups.append({"name": group_name, "targets": targets})

try:
    executable_sha256 = currentProgram.getExecutableSHA256()
except:
    executable_sha256 = None

catalog = {
    "schema": "solomon-dark-native-full-render-pipeline-xrefs-v1",
    "program": currentProgram.getName(),
    "executable_sha256": executable_sha256,
    "image_base": "0x%s" % str(currentProgram.getImageBase()).upper(),
    "graphics_subobject_offset": "0x1D0",
    "summary": {
        "group_count": len(groups),
        "target_count": target_count,
        "reference_count": reference_count,
        "unique_caller_count": len(all_callers),
        "renderer_state_write_count": len(state_writes),
    },
    "groups": groups,
    "renderer_state_writes": state_writes,
    "callers": [all_callers[key] for key in sorted(all_callers)],
}

rendered = json.dumps(catalog, indent=2, sort_keys=True, separators=(",", ": ")).encode("utf-8")
with open(json_path, "wb") as output:
    output.write(rendered)
    output.write(b"\n")

print("JSON %s" % json_path)
print("GROUP_COUNT %d" % len(groups))
print("TARGET_COUNT %d" % target_count)
print("REFERENCE_COUNT %d" % reference_count)
print("UNIQUE_CALLER_COUNT %d" % len(all_callers))
print("RENDERER_STATE_WRITE_COUNT %d" % len(state_writes))
print("=== DONE ===")
