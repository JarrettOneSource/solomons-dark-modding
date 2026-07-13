bool TryReadNativeStringEquals(
    uintptr_t string_object_address,
    std::string_view expected) {
    if (string_object_address == 0 || expected.empty() || expected.size() > 128 ||
        kNativeStringDataOffset == 0 || kNativeStringLengthOffset == 0) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    uintptr_t text_address = 0;
    std::int32_t text_length = 0;
    if (!memory.TryReadField(
            string_object_address,
            kNativeStringDataOffset,
            &text_address) ||
        !memory.TryReadField(
            string_object_address,
            kNativeStringLengthOffset,
            &text_length) ||
        text_address == 0 ||
        text_length != static_cast<std::int32_t>(expected.size())) {
        return false;
    }

    std::string actual;
    return memory.TryReadCString(
               text_address,
               static_cast<std::size_t>(text_length) + 1,
               &actual) &&
           actual == expected;
}

bool TryReadProgressionRankedNumericStat(
    uintptr_t progression_address,
    int entry_index,
    std::string_view property_name,
    float* value,
    int* active_rank = nullptr) {
    if (value == nullptr) {
        return false;
    }
    *value = 0.0f;
    if (active_rank != nullptr) {
        *active_rank = 0;
    }
    if (progression_address == 0 || entry_index < 0 || property_name.empty() ||
        kStandaloneWizardProgressionEntryStride == 0 ||
        kStandaloneWizardProgressionEntryStatbookOffset == 0 ||
        kStatbookNumericPropertyListOffset == 0 ||
        kStatbookNumericPropertyValuesOffset == 0 ||
        kStatbookNumericPropertyValueCountOffset == 0 ||
        kPointerListCountOffset == 0 ||
        kPointerListItemsOffset == 0) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    uintptr_t table_address = 0;
    std::int32_t table_count = 0;
    if (!memory.TryReadField(
            progression_address,
            kStandaloneWizardProgressionTableBaseOffset,
            &table_address) ||
        !memory.TryReadField(
            progression_address,
            kStandaloneWizardProgressionTableCountOffset,
            &table_count) ||
        table_address == 0 ||
        entry_index >= table_count ||
        table_count <= 0 ||
        table_count > 4096) {
        return false;
    }

    const auto entry_address =
        table_address +
        static_cast<std::size_t>(entry_index) *
            kStandaloneWizardProgressionEntryStride;
    std::uint16_t rank = 0;
    uintptr_t statbook_address = 0;
    if (!memory.TryReadField(
            entry_address,
            kStandaloneWizardProgressionActiveFlagOffset,
            &rank) ||
        !memory.TryReadField(
            entry_address,
            kStandaloneWizardProgressionEntryStatbookOffset,
            &statbook_address) ||
        statbook_address == 0) {
        return false;
    }
    if (active_rank != nullptr) {
        *active_rank = static_cast<int>(rank);
    }

    const auto property_list_address =
        statbook_address + kStatbookNumericPropertyListOffset;
    std::int32_t property_count = 0;
    uintptr_t property_items_address = 0;
    if (!memory.TryReadField(
            property_list_address,
            kPointerListCountOffset,
            &property_count) ||
        !memory.TryReadField(
            property_list_address,
            kPointerListItemsOffset,
            &property_items_address) ||
        property_count <= 0 ||
        property_count > 64 ||
        property_items_address == 0 ||
        !memory.IsReadableRange(
            property_items_address,
            static_cast<std::size_t>(property_count) * sizeof(uintptr_t))) {
        return false;
    }

    for (int property_index = 0;
         property_index < property_count;
         ++property_index) {
        uintptr_t shared_wrapper_address = 0;
        uintptr_t property_address = 0;
        if (!memory.TryReadValue(
                property_items_address +
                    static_cast<std::size_t>(property_index) * sizeof(uintptr_t),
                &shared_wrapper_address) ||
            shared_wrapper_address == 0 ||
            !memory.TryReadValue(shared_wrapper_address, &property_address) ||
            property_address == 0 ||
            !TryReadNativeStringEquals(property_address, property_name)) {
            continue;
        }

        uintptr_t values_address = 0;
        std::int32_t value_count = 0;
        if (!memory.TryReadField(
                property_address,
                kStatbookNumericPropertyValuesOffset,
                &values_address) ||
            !memory.TryReadField(
                property_address,
                kStatbookNumericPropertyValueCountOffset,
                &value_count) ||
            values_address == 0 ||
            value_count <= 0 ||
            value_count > 1024 ||
            !memory.IsReadableRange(
                values_address,
                static_cast<std::size_t>(value_count) * sizeof(float))) {
            return false;
        }

        // FUN_0065D540 clamps the requested/active rank to the final value in
        // the property array. Mirror that stock behavior while leaving the
        // native StatBook authoritative for custom skill data.
        const auto resolved_rank = std::min<int>(rank, value_count - 1);
        float resolved_value = 0.0f;
        if (!memory.TryReadValue(
                values_address +
                    static_cast<std::size_t>(resolved_rank) * sizeof(float),
                &resolved_value) ||
            !std::isfinite(resolved_value) ||
            std::fabs(resolved_value) > 1000000.0f) {
            return false;
        }
        *value = resolved_value;
        return true;
    }
    return false;
}
