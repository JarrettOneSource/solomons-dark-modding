"""Participant-owned nested inventory container contracts."""

from __future__ import annotations

import re

from static_re_contract_support import ROOT, StaticReTestFailure, read_text


def _require(label: str, text: str, tokens: tuple[str, ...], failures: list[str]) -> None:
    for token in tokens:
        if token not in text:
            failures.append(f"{label} is missing {token}")


def test_nested_sack_inventory_preserves_owner_authored_container_paths() -> str:
    """A sack and its contents must remain one participant-owned inventory tree."""

    mod_header = read_text(ROOT / "SolomonDarkModLoader/include/mod_loader.h")
    runtime_state = read_text(
        ROOT / "SolomonDarkModLoader/include/multiplayer_runtime_state.h"
    )
    protocol = read_text(
        ROOT / "SolomonDarkModLoader/include/multiplayer_runtime_protocol.h"
    )
    state_getters = read_text(
        ROOT
        / "SolomonDarkModLoader/src/mod_loader_gameplay/public_api_state_getters.inl"
    )
    snapshot_tree = read_text(
        ROOT
        / "SolomonDarkModLoader/src/mod_loader_gameplay/inventory_snapshot_tree.inl"
    )
    owned_progression = read_text(
        ROOT
        / "SolomonDarkModLoader/src/multiplayer_local_transport/owned_progression_state.inl"
    )
    outgoing = read_text(
        ROOT
        / "SolomonDarkModLoader/src/multiplayer_local_transport/participant_progression_snapshot_sync.inl"
    )
    incoming = read_text(
        ROOT
        / "SolomonDarkModLoader/src/multiplayer_local_transport/participant_progression_snapshot_sync.inl"
    )
    lua_gameplay = read_text(
        ROOT / "SolomonDarkModLoader/src/lua_engine_bindings_gameplay.cpp"
    )
    lua_runtime = read_text(
        ROOT / "SolomonDarkModLoader/src/lua_engine_bindings_runtime.cpp"
    )
    lua_debug = read_text(
        ROOT / "SolomonDarkModLoader/src/lua_engine_bindings_debug.cpp"
    )
    lua_debug_calls = read_text(
        ROOT
        / "SolomonDarkModLoader/src/lua_engine_bindings_debug/functions_native_calls.inl"
    )
    fixture = read_text(
        ROOT
        / "SolomonDarkModLoader/src/mod_loader_gameplay/execute_requests/nested_sack_inventory_fixture.inl"
    )
    gameplay_seams = read_text(ROOT / "SolomonDarkModLoader/src/gameplay_seams.h")
    size_bindings = read_text(
        ROOT / "SolomonDarkModLoader/src/gameplay_seams/size_bindings.inl"
    )
    binary_layout = read_text(ROOT / "config/binary-layout.ini")
    inventory_notes = read_text(ROOT / "docs/inventory-item-investigation.md")
    verifier_path = ROOT / "tools/verify_steam_nested_sack_inventory_sync.py"

    failures: list[str] = []
    _require(
        "local inventory row",
        mod_header,
        ("parent_item_index", "container_depth"),
        failures,
    )
    _require(
        "runtime inventory row",
        runtime_state,
        ("parent_item_index", "container_depth"),
        failures,
    )
    _require(
        "wire inventory row",
        protocol,
        (
            "std::int16_t parent_item_index;",
            "std::uint16_t container_depth;",
            "static_assert(sizeof(ParticipantInventoryItemPacketState) == 28",
        ),
        failures,
    )
    _require(
        "native inventory snapshot",
        state_getters + snapshot_tree,
        (
            "EnumerateInventoryItemTree",
            "kInventorySackItemTypeId",
            "kSDModInventorySnapshotMaxDepth",
            "kSackItemInventoryRootPointerOffset",
            "parent_item_index",
            "container_depth",
        ),
        failures,
    )
    _require(
        "owned inventory projection",
        owned_progression,
        ("built.parent_item_index", "built.container_depth"),
        failures,
    )
    _require(
        "outgoing inventory serialization",
        outgoing,
        (
            "packet_item.parent_item_index",
            "packet_item.container_depth",
        ),
        failures,
    )
    _require(
        "incoming inventory serialization",
        incoming,
        (
            "IsSaneParticipantInventorySnapshot",
            "item.parent_item_index",
            "item.container_depth",
            "parent.type_id != 0x1B60",
        ),
        failures,
    )
    _require(
        "local Lua inventory view",
        lua_gameplay,
        ('"parent_item_index"', '"container_depth"'),
        failures,
    )
    inventory_lua_function = re.search(
        r"void PushInventoryItemState\b.*?\n}", lua_gameplay, re.DOTALL
    )
    if inventory_lua_function is None or "lua_createtable(state, 0, 10);" not in (
        inventory_lua_function.group(0) if inventory_lua_function else ""
    ):
        failures.append("local Lua inventory row does not reserve its ten fields")
    equip_lua_function = re.search(
        r"void PushEquipVisualLaneState\b.*?\n}", lua_gameplay, re.DOTALL
    )
    if equip_lua_function is None or "lua_createtable(state, 0, 9);" not in (
        equip_lua_function.group(0) if equip_lua_function else ""
    ):
        failures.append("equipment Lua row does not reserve its nine fields")
    _require(
        "participant Lua inventory view",
        lua_runtime,
        ('"parent_item_index"', '"container_depth"'),
        failures,
    )
    _require(
        "gameplay seam declaration",
        gameplay_seams,
        ("kSackItemInventoryRootPointerOffset",),
        failures,
    )
    _require(
        "gameplay seam binding",
        size_bindings,
        ('"sack_item_inventory_root_pointer"',),
        failures,
    )
    _require(
        "binary layout",
        binary_layout,
        (
            "sack_item_inventory_root_pointer=0x88",
            "inventory_screen_current_root=0x158",
            "inventory_screen_parent_root_stack=0x174",
            "inventory_screen_parent_root_stack_count=0x184",
            "sack_inventory_root_owner_uid=0x04",
            "sack_inventory_root_live_owner=0x08",
        ),
        failures,
    )
    _require(
        "nested-sack reverse-engineering notes",
        inventory_notes,
        (
            "Item_Sack_GetInventoryRoot",
            "sack + 0x88",
            "0x0056DE50",
            "0x0056D920",
            "InventoryScreen+0x158",
            "game-back later",
            "sounds\\\\backpack_open",
            "sounds\\\\backpack_close",
        ),
        failures,
    )
    for stale_claim in (
        "current browsed inventory root lives at `screen + 0x88`",
        "`InventoryScreen + 0x88` is the right UI browse seam",
        "keep `InventoryScreen + 0x88` on the local owner root",
        "does not replace an inventory-screen browse root",
        "does not open a replacement inventory-screen browse target",
    ):
        if stale_claim in inventory_notes:
            failures.append(
                "nested-sack reverse-engineering notes retain disproven claim "
                + stale_claim
            )
    _require(
        "native nested-sack fixture",
        fixture,
        (
            "kInventorySackItemTypeId",
            "kInventoryPotionItemTypeId",
            "kSackItemInventoryRootPointerOffset",
            "CallInventoryInsertOrStackItemSafe",
            "FindInventoryRootItemPointer",
        ),
        failures,
    )
    _require(
        "nested-sack fixture Lua binding",
        lua_debug + lua_debug_calls,
        (
            "queue_nested_sack_inventory_fixture",
            "QueueNestedSackInventoryFixture",
        ),
        failures,
    )

    if not verifier_path.is_file():
        failures.append("real Steam nested-sack verifier is missing")
    else:
        verifier = read_text(verifier_path)
        _require(
            "real Steam nested-sack verifier",
            verifier,
            (
                "SACK_TYPE_ID",
                "parent_item_index",
                "container_depth",
                "owner_native_inventory_unchanged",
                "observer_native_inventory_unchanged",
                "container_inventory_root",
                "nested_potion",
                "baseline_observer_revision",
            ),
            failures,
        )
        if 'baseline_owner["participants"]' in verifier:
            failures.append(
                "real Steam nested-sack verifier treats the remote-only "
                "participant list as a local owner ledger"
            )
        if "owner_inventory_revision_delta" in verifier:
            failures.append(
                "real Steam nested-sack verifier reports an unavailable local "
                "owner ledger revision"
            )

    if failures:
        raise StaticReTestFailure("; ".join(failures))

    return (
        "native sack contents are enumerated as a bounded owner-authored tree, "
        "replicated with stable parent rows, browsed through screen-local pages, "
        "exposed through Lua, and covered by a two-account Steam verifier"
    )


def test_inventory_sack_pages_and_heterogeneous_belt_are_pinned() -> str:
    """Inventory browse state and Game belt state must keep their native owners."""

    binary_layout = read_text(ROOT / "config/binary-layout.ini")
    inventory_notes = read_text(ROOT / "docs/inventory-item-investigation.md")
    hub_report = read_text(ROOT / "docs/reverse-engineering/native-hub-and-economy.md")
    item_report = read_text(
        ROOT / "docs/reverse-engineering/native-items-equipment-and-loot.md"
    )
    belt_report = read_text(
        ROOT / "docs/reverse-engineering/native-skill-screen-and-quickbar.md"
    )

    failures: list[str] = []
    _require(
        "InventoryScreen Sack page report",
        inventory_notes + hub_report,
        (
            "InventoryScreen+0x158",
            "0x0056D920",
            "0x00560D30",
            "0x00551A10",
            "full 1,600-pixel stage width",
            "160 ticks / 1.6 seconds",
            "10 stage pixels per fixed tick",
            "backpack_open",
            "backpack_close",
        ),
        failures,
    )
    _require(
        "Item_Sack lifecycle and belt report",
        item_report,
        (
            "0x005A7520",
            "0x00573E00",
            "0x00570B90",
            "0x0056EC30 -> Game_BindBeltDrop 0x005C7090",
            "Item_Misc alone",
            "The belt never steals item ownership",
        ),
        failures,
    )
    _require(
        "heterogeneous BeltButton report",
        belt_report,
        (
            "BeltButton is heterogeneous, not skill-book state",
            "0x1B65",
            "0x1B66",
            "0x1B67",
            "another admitted item runtime type",
            "Game_RefreshBelt 0x005D50E0",
            "InventoryDragger release `0x0056EC30`",
            "Tutorial activation `0x005D5FE0`",
            "retains `0x1B65/0x1B66`",
            "Teleport row 48",
            "0x0054D625..0x0054D728",
        ),
        failures,
    )
    _require(
        "belt binary layout",
        binary_layout,
        (
            "game_belt_button_base=0x5EC",
            "game_belt_button_stride=0xEC",
            "belt_button_entry_type=0xB4",
            "belt_button_entry_identity=0xB8",
            "belt_button_resolved_item=0xBC",
            "belt_button_pull_offset=0xC0",
            "belt_button_quantity=0xE4",
        ),
        failures,
    )

    if failures:
        raise StaticReTestFailure("; ".join(failures))

    return (
        "InventoryScreen direct-child Sack pages and the Game-owned "
        "heterogeneous eight-entry belt are pinned through every producer, "
        "refresh, action, presentation, and teardown owner"
    )
