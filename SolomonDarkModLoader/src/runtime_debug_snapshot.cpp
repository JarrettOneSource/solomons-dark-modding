#include "runtime_debug_internal.h"

extern "C" void RuntimeDebug_Snapshot(const char* name, uintptr_t address, size_t size) {
    namespace rt = sdmod::detail::runtime_debug;

    const auto resolved_address = rt::ResolveRuntimeAddress(address);
    if (resolved_address == 0 || size == 0) {
        sdmod::Log("SNAPSHOT: failed to capture unnamed snapshot at " + sdmod::HexString(address));
        return;
    }

    rt::Snapshot snapshot;
    snapshot.name = rt::NormalizeName(name, "snapshot", address);
    snapshot.requested_address = address;
    snapshot.resolved_address = resolved_address;
    snapshot.bytes.assign(size, 0);

    if (!sdmod::ProcessMemory::Instance().TryRead(resolved_address, snapshot.bytes.data(), snapshot.bytes.size())) {
        sdmod::Log(
            "SNAPSHOT: failed to capture " + snapshot.name + " from " + sdmod::HexString(address) +
            " size=" + std::to_string(size));
        return;
    }

    {
        std::scoped_lock lock(rt::g_runtime_debug_state.mutex);
        rt::g_runtime_debug_state.snapshots[snapshot.name] = snapshot;
    }

    sdmod::Log(
        "SNAPSHOT: captured " + snapshot.name + " addr=" + sdmod::HexString(snapshot.requested_address) +
        " size=" + std::to_string(snapshot.bytes.size()));
}

extern "C" void RuntimeDebug_SnapshotPtrField(const char* name, uintptr_t ptr_address, size_t offset, size_t size) {
    namespace rt = sdmod::detail::runtime_debug;

    const auto resolved_ptr_address = rt::ResolveRuntimeAddress(ptr_address);
    if (resolved_ptr_address == 0 || size == 0) {
        sdmod::Log("SNAPSHOT: failed to capture ptr-field snapshot at " + sdmod::HexString(ptr_address));
        return;
    }

    uintptr_t base_address = 0;
    if (!sdmod::ProcessMemory::Instance().TryReadValue(resolved_ptr_address, &base_address) || base_address == 0) {
        sdmod::Log(
            "SNAPSHOT: failed to resolve ptr-field snapshot " + rt::NormalizeName(name, "snapshot", ptr_address) +
            " ptr=" + sdmod::HexString(ptr_address));
        return;
    }

    uintptr_t field_address = 0;
    if (!rt::TryAddRuntimeOffset(base_address, offset, &field_address)) {
        sdmod::Log(
            "SNAPSHOT: ptr-field offset overflow for " + rt::NormalizeName(name, "snapshot", ptr_address) +
            " base=" + sdmod::HexString(base_address));
        return;
    }

    RuntimeDebug_Snapshot(name, field_address, size);
}

extern "C" void RuntimeDebug_SnapshotNestedPtrField(
    const char* name,
    uintptr_t ptr_address,
    size_t outer_offset,
    size_t inner_offset,
    size_t size) {
    namespace rt = sdmod::detail::runtime_debug;

    const auto resolved_ptr_address = rt::ResolveRuntimeAddress(ptr_address);
    if (resolved_ptr_address == 0 || size == 0) {
        sdmod::Log("SNAPSHOT: failed to capture nested ptr-field snapshot at " + sdmod::HexString(ptr_address));
        return;
    }

    uintptr_t base_address = 0;
    if (!sdmod::ProcessMemory::Instance().TryReadValue(resolved_ptr_address, &base_address) || base_address == 0) {
        sdmod::Log(
            "SNAPSHOT: failed to resolve nested ptr-field snapshot " +
            rt::NormalizeName(name, "snapshot", ptr_address) +
            " ptr=" + sdmod::HexString(ptr_address));
        return;
    }

    uintptr_t nested_slot_address = 0;
    if (!rt::TryAddRuntimeOffset(base_address, outer_offset, &nested_slot_address)) {
        sdmod::Log(
            "SNAPSHOT: nested ptr-field outer offset overflow for " +
            rt::NormalizeName(name, "snapshot", ptr_address) +
            " base=" + sdmod::HexString(base_address));
        return;
    }

    uintptr_t nested_address = 0;
    if (!sdmod::ProcessMemory::Instance().TryReadValue(nested_slot_address, &nested_address) || nested_address == 0) {
        sdmod::Log(
            "SNAPSHOT: failed to resolve nested base for " +
            rt::NormalizeName(name, "snapshot", ptr_address) +
            " base=" + sdmod::HexString(nested_slot_address));
        return;
    }

    uintptr_t field_address = 0;
    if (!rt::TryAddRuntimeOffset(nested_address, inner_offset, &field_address)) {
        sdmod::Log(
            "SNAPSHOT: nested ptr-field inner offset overflow for " +
            rt::NormalizeName(name, "snapshot", ptr_address) +
            " base=" + sdmod::HexString(nested_address));
        return;
    }

    RuntimeDebug_Snapshot(name, field_address, size);
}

extern "C" void RuntimeDebug_SnapshotDoubleNestedPtrField(
    const char* name,
    uintptr_t ptr_address,
    size_t outer_offset,
    size_t middle_offset,
    size_t inner_offset,
    size_t size) {
    namespace rt = sdmod::detail::runtime_debug;

    const auto resolved_ptr_address = rt::ResolveRuntimeAddress(ptr_address);
    if (resolved_ptr_address == 0 || size == 0) {
        sdmod::Log("SNAPSHOT: failed to capture double nested ptr-field snapshot at " + sdmod::HexString(ptr_address));
        return;
    }

    uintptr_t base_address = 0;
    if (!sdmod::ProcessMemory::Instance().TryReadValue(resolved_ptr_address, &base_address) || base_address == 0) {
        sdmod::Log(
            "SNAPSHOT: failed to resolve double nested ptr-field snapshot " +
            rt::NormalizeName(name, "snapshot", ptr_address) +
            " ptr=" + sdmod::HexString(ptr_address));
        return;
    }

    uintptr_t nested_slot_address = 0;
    if (!rt::TryAddRuntimeOffset(base_address, outer_offset, &nested_slot_address)) {
        sdmod::Log(
            "SNAPSHOT: double nested outer offset overflow for " +
            rt::NormalizeName(name, "snapshot", ptr_address) +
            " base=" + sdmod::HexString(base_address));
        return;
    }

    uintptr_t nested_address = 0;
    if (!sdmod::ProcessMemory::Instance().TryReadValue(nested_slot_address, &nested_address) || nested_address == 0) {
        sdmod::Log(
            "SNAPSHOT: failed to resolve first nested base for " +
            rt::NormalizeName(name, "snapshot", ptr_address) +
            " base=" + sdmod::HexString(nested_slot_address));
        return;
    }

    uintptr_t inner_slot_address = 0;
    if (!rt::TryAddRuntimeOffset(nested_address, middle_offset, &inner_slot_address)) {
        sdmod::Log(
            "SNAPSHOT: double nested middle offset overflow for " +
            rt::NormalizeName(name, "snapshot", ptr_address) +
            " base=" + sdmod::HexString(nested_address));
        return;
    }

    uintptr_t inner_address = 0;
    if (!sdmod::ProcessMemory::Instance().TryReadValue(inner_slot_address, &inner_address) || inner_address == 0) {
        sdmod::Log(
            "SNAPSHOT: failed to resolve second nested base for " +
            rt::NormalizeName(name, "snapshot", ptr_address) +
            " base=" + sdmod::HexString(inner_slot_address));
        return;
    }

    uintptr_t field_address = 0;
    if (!rt::TryAddRuntimeOffset(inner_address, inner_offset, &field_address)) {
        sdmod::Log(
            "SNAPSHOT: double nested inner offset overflow for " +
            rt::NormalizeName(name, "snapshot", ptr_address) +
            " base=" + sdmod::HexString(inner_address));
        return;
    }

    RuntimeDebug_Snapshot(name, field_address, size);
}

extern "C" void RuntimeDebug_DiffSnapshots(const char* name_a, const char* name_b) {
    namespace rt = sdmod::detail::runtime_debug;

    const auto snapshot_name_a = rt::NormalizeName(name_a, "snapshot_a", 0);
    const auto snapshot_name_b = rt::NormalizeName(name_b, "snapshot_b", 0);

    rt::Snapshot snapshot_a;
    rt::Snapshot snapshot_b;
    {
        std::scoped_lock lock(rt::g_runtime_debug_state.mutex);
        const auto it_a = rt::g_runtime_debug_state.snapshots.find(snapshot_name_a);
        const auto it_b = rt::g_runtime_debug_state.snapshots.find(snapshot_name_b);
        if (it_a == rt::g_runtime_debug_state.snapshots.end() ||
            it_b == rt::g_runtime_debug_state.snapshots.end()) {
            sdmod::Log("SNAPSHOT: diff failed because one or both snapshots are missing.");
            return;
        }
        snapshot_a = it_a->second;
        snapshot_b = it_b->second;
    }

    std::vector<std::string> diff_lines;
    size_t change_count = 0;
    const auto common_size = (std::min)(snapshot_a.bytes.size(), snapshot_b.bytes.size());
    for (size_t index = 0; index < common_size; ++index) {
        if (snapshot_a.bytes[index] == snapshot_b.bytes[index]) {
            continue;
        }

        ++change_count;
        if (diff_lines.size() < rt::kMaxLoggedDiffs) {
            std::ostringstream line;
            line << "SNAPSHOT DIFF: " << snapshot_name_a << " -> " << snapshot_name_b
                 << " +0x" << std::uppercase << std::hex << index
                 << " " << std::setw(2) << std::setfill('0') << static_cast<unsigned int>(snapshot_a.bytes[index])
                 << " -> " << std::setw(2) << std::setfill('0') << static_cast<unsigned int>(snapshot_b.bytes[index]);
            diff_lines.push_back(line.str());
        }
    }

    if (snapshot_a.bytes.size() != snapshot_b.bytes.size()) {
        const auto smaller = common_size;
        const auto larger = (std::max)(snapshot_a.bytes.size(), snapshot_b.bytes.size());
        for (size_t index = smaller; index < larger; ++index) {
            ++change_count;
            if (diff_lines.size() < rt::kMaxLoggedDiffs) {
                std::ostringstream line;
                line << "SNAPSHOT DIFF: " << snapshot_name_a << " -> " << snapshot_name_b
                     << " +0x" << std::uppercase << std::hex << index;
                if (index < snapshot_a.bytes.size()) {
                    line << " " << std::setw(2) << std::setfill('0')
                         << static_cast<unsigned int>(snapshot_a.bytes[index]) << " -> <missing>";
                } else {
                    line << " <missing> -> " << std::setw(2) << std::setfill('0')
                         << static_cast<unsigned int>(snapshot_b.bytes[index]);
                }
                diff_lines.push_back(line.str());
            }
        }
    }

    sdmod::Log(
        "SNAPSHOT DIFF: " + snapshot_name_a + " vs " + snapshot_name_b +
        " changed=" + std::to_string(change_count) +
        " size_a=" + std::to_string(snapshot_a.bytes.size()) +
        " size_b=" + std::to_string(snapshot_b.bytes.size()));
    for (const auto& line : diff_lines) {
        sdmod::Log(line);
    }
    if (change_count > diff_lines.size()) {
        sdmod::Log(
            "SNAPSHOT DIFF: " + std::to_string(change_count - diff_lines.size()) +
            " additional byte changes not logged.");
    }
}
