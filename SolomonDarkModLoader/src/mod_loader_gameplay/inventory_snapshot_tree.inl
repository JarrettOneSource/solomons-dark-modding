namespace {

constexpr std::size_t kInventoryTreeMaxVisitedSlots = 4096;

struct InventoryTreeWalkState {
    SDModInventoryState* snapshot = nullptr;
    std::size_t visited_slots = 0;
    std::array<uintptr_t, kSDModInventorySnapshotMaxDepth + 1> active_roots = {};
};

bool EnumerateInventoryItemTree(
    uintptr_t item_list_root,
    std::int16_t parent_item_index,
    std::uint16_t container_depth,
    InventoryTreeWalkState* walk) {
    if (walk == nullptr || walk->snapshot == nullptr || item_list_root == 0 ||
        container_depth > kSDModInventorySnapshotMaxDepth) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    if (!memory.IsReadableRange(
            item_list_root,
            kGameplayItemListItemsOffset + sizeof(uintptr_t))) {
        return false;
    }

    int raw_item_count = 0;
    uintptr_t item_array_address = 0;
    if (!memory.TryReadField(
            item_list_root,
            kGameplayItemListCountOffset,
            &raw_item_count) ||
        !memory.TryReadField(
            item_list_root,
            kGameplayItemListItemsOffset,
            &item_array_address) ||
        raw_item_count < 0 || raw_item_count > 4096) {
        return false;
    }
    if (raw_item_count == 0) {
        return true;
    }
    if (item_array_address == 0 ||
        !memory.IsReadableRange(
            item_array_address,
            static_cast<std::size_t>(raw_item_count) * sizeof(std::uint32_t))) {
        return false;
    }

    for (std::uint16_t depth = 0; depth < container_depth; ++depth) {
        if (walk->active_roots[depth] == item_list_root) {
            walk->snapshot->truncated = true;
            return true;
        }
    }
    walk->active_roots[container_depth] = item_list_root;

    for (int index = 0; index < raw_item_count; ++index) {
        if (walk->visited_slots >= kInventoryTreeMaxVisitedSlots) {
            walk->snapshot->truncated = true;
            break;
        }
        ++walk->visited_slots;

        std::uint32_t raw_item_address = 0;
        if (!memory.TryReadValue(
                item_array_address +
                    static_cast<std::size_t>(index) * sizeof(std::uint32_t),
                &raw_item_address) ||
            raw_item_address == 0) {
            continue;
        }

        const uintptr_t item_address = static_cast<uintptr_t>(raw_item_address);
        if (!memory.IsReadableRange(item_address, kItemSlotOffset + sizeof(int))) {
            continue;
        }

        std::uint32_t item_type_id = 0;
        if (!memory.TryReadField(
                item_address,
                kGameObjectTypeIdOffset,
                &item_type_id) ||
            item_type_id == 0 ||
            item_type_id == kInventoryPlaceholderItemTypeId) {
            continue;
        }

        ++walk->snapshot->item_count;
        std::int16_t snapshot_index = -1;
        if (walk->snapshot->items.size() < kSDModInventorySnapshotMaxItems) {
            snapshot_index = static_cast<std::int16_t>(
                walk->snapshot->items.size());

            SDModInventoryItemState item{};
            item.valid = true;
            item.item_address = item_address;
            item.type_id = item_type_id;
            item.parent_item_index = parent_item_index;
            item.container_depth = container_depth;
            if (kItemInstanceRecipeUidOffset != 0) {
                (void)memory.TryReadField(
                    item_address,
                    kItemInstanceRecipeUidOffset,
                    &item.recipe_uid);
            }
            (void)memory.TryReadField(item_address, kItemSlotOffset, &item.slot);
            if (item.type_id == kInventoryPotionItemTypeId &&
                memory.IsReadableRange(
                    item_address + kPotionStackCountOffset,
                    sizeof(int))) {
                (void)memory.TryReadField(
                    item_address,
                    kPotionStackCountOffset,
                    &item.stack_count);
            }
            if ((item.type_id == kStandaloneWizardHatVisualTypeId ||
                 item.type_id == kStandaloneWizardRobeVisualTypeId) &&
                memory.TryRead(
                    item_address + kItemWearableColorStateOffset,
                    item.color_state.data(),
                    item.color_state.size())) {
                item.color_state_valid = true;
            }
            walk->snapshot->items.push_back(item);
        } else {
            walk->snapshot->truncated = true;
        }

        if (item_type_id != kInventorySackItemTypeId) {
            continue;
        }
        if (container_depth >= kSDModInventorySnapshotMaxDepth) {
            walk->snapshot->truncated = true;
            continue;
        }

        uintptr_t nested_root = 0;
        if (kSackItemInventoryRootPointerOffset == 0 ||
            !memory.TryReadField(
                item_address,
                kSackItemInventoryRootPointerOffset,
                &nested_root)) {
            walk->snapshot->truncated = true;
            continue;
        }
        if (nested_root != 0 &&
            !EnumerateInventoryItemTree(
                nested_root,
                snapshot_index,
                static_cast<std::uint16_t>(container_depth + 1),
                walk)) {
            walk->snapshot->truncated = true;
        }
    }

    walk->active_roots[container_depth] = 0;
    return true;
}

}  // namespace
