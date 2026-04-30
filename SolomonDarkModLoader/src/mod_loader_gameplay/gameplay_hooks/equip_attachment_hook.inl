uintptr_t ResolveActorAttachmentLaneItem(uintptr_t actor_address) {
    if (actor_address == 0) {
        return 0;
    }

    auto& memory = ProcessMemory::Instance();
    const auto equip_runtime =
        memory.ReadFieldOr<uintptr_t>(actor_address, kActorEquipRuntimeStateOffset, 0);
    const auto attachment_lane = ReadEquipVisualLaneState(
        equip_runtime,
        kActorEquipRuntimeVisualLinkAttachmentOffset);
    if (attachment_lane.current_object_address == 0 ||
        !memory.IsReadableRange(attachment_lane.current_object_address, 0x0C)) {
        return 0;
    }

    return attachment_lane.current_object_address;
}

int __fastcall HookEquipAttachmentSinkGetCurrentItem(int sink, void* /*unused_edx*/) {
    const auto original = GetX86HookTrampoline<EquipAttachmentSinkGetCurrentItemFn>(
        g_gameplay_keyboard_injection.equip_attachment_get_current_item_hook);
    if (original == nullptr) {
        return 0;
    }

    auto& memory = ProcessMemory::Instance();
    const auto sink_address = static_cast<uintptr_t>(sink);
    const auto sink_vtable =
        sink_address != 0 && memory.IsReadableRange(sink_address, sizeof(uintptr_t))
            ? memory.ReadValueOr<uintptr_t>(sink_address, 0)
            : 0;
    const auto sink_item_before =
        sink_address != 0 && memory.IsReadableRange(sink_address + 4, sizeof(uintptr_t))
            ? memory.ReadValueOr<uintptr_t>(sink_address + 4, 0)
            : 0;

    const auto result = original(sink);
    uintptr_t fallback_result = 0;
    if (g_spell_dispatch_probe.depth > 0 &&
        !g_spell_dispatch_probe.local_player &&
        g_spell_dispatch_probe.actor_address != 0) {
        fallback_result = g_spell_dispatch_probe.pure_primary_item_sink_fallback;
        if (fallback_result == 0) {
            fallback_result = ResolveActorAttachmentLaneItem(g_spell_dispatch_probe.actor_address);
        }
        if (fallback_result == static_cast<uintptr_t>(result)) {
            fallback_result = 0;
        }
    }

    if (g_spell_dispatch_probe.depth > 0) {
        const auto item_type =
            (result != 0 || fallback_result != 0) &&
                    memory.IsReadableRange((result != 0 ? static_cast<uintptr_t>(result) : fallback_result) + 8, sizeof(std::uint32_t))
                ? memory.ReadValueOr<std::uint32_t>((result != 0 ? static_cast<uintptr_t>(result) : fallback_result) + 8, 0)
                : 0;
        Log(
            "[bots] equip_sink_get_current_item actor=" + HexString(g_spell_dispatch_probe.actor_address) +
            " bot_id=" + std::to_string(g_spell_dispatch_probe.bot_id) +
            " startup=" + std::to_string(g_spell_dispatch_probe.startup ? 1 : 0) +
            " pure_primary_startup=" + std::to_string(g_spell_dispatch_probe.pure_primary_startup ? 1 : 0) +
            " local_player=" + std::to_string(g_spell_dispatch_probe.local_player ? 1 : 0) +
            " sink=" + HexString(sink_address) +
            " sink_vtable=" + HexString(sink_vtable) +
            " sink_item_before=" + HexString(sink_item_before) +
            " result=" + HexString(static_cast<uintptr_t>(result)) +
            " fallback_result=" + HexString(fallback_result) +
            " result_type=" + HexString(item_type));
    }

    return fallback_result != 0 ? static_cast<int>(fallback_result) : result;
}
