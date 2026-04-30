#include "runtime_debug_internal.h"

extern "C" void RuntimeDebug_Tick() {
    namespace rt = sdmod::detail::runtime_debug;

    std::vector<std::string> log_lines;

    {
        std::scoped_lock lock(rt::g_runtime_debug_state.mutex);
        for (auto& watch : rt::g_runtime_debug_state.watches) {
            uintptr_t base_address = 0;
            uintptr_t value_address = 0;
            std::vector<std::uint8_t> current_bytes;
            const auto valid = rt::ReadWatchValue(watch, &base_address, &value_address, &current_bytes);
            if (!valid) {
                if (watch.last_valid) {
                    if (watch.kind == rt::WatchKind::Direct) {
                        log_lines.push_back(
                            "WATCH: " + watch.name + " became unreadable at " +
                            sdmod::HexString(watch.requested_address));
                    } else {
                        log_lines.push_back(
                            "WATCH: " + watch.name + " became unreadable ptr=" +
                            sdmod::HexString(watch.requested_address) +
                            " base=" + sdmod::HexString(watch.last_base_address) +
                            " field=" + sdmod::HexString(watch.last_value_address));
                    }
                }
                watch.last_valid = false;
                watch.last_base_address = base_address;
                watch.last_value_address = value_address;
                watch.last_bytes.clear();
                continue;
            }

            if (!watch.last_valid) {
                if (watch.kind == rt::WatchKind::Direct) {
                    log_lines.push_back(
                        "WATCH: " + watch.name + " initial addr=" + sdmod::HexString(watch.requested_address) +
                        " value=" + rt::FormatBytes(current_bytes));
                } else {
                    log_lines.push_back(
                        "WATCH: " + watch.name + " initial ptr=" + sdmod::HexString(watch.requested_address) +
                        " base=" + sdmod::HexString(base_address) +
                        " field=" + sdmod::HexString(value_address) +
                        " value=" + rt::FormatBytes(current_bytes));
                }
                watch.last_valid = true;
                watch.last_base_address = base_address;
                watch.last_value_address = value_address;
                watch.last_bytes = std::move(current_bytes);
                continue;
            }

            const auto base_changed = watch.kind == rt::WatchKind::PtrField && base_address != watch.last_base_address;
            const auto value_changed = watch.last_bytes != current_bytes;
            if (!base_changed && !value_changed) {
                watch.last_base_address = base_address;
                watch.last_value_address = value_address;
                continue;
            }

            if (watch.kind == rt::WatchKind::Direct) {
                log_lines.push_back(
                    "WATCH: " + watch.name + " changed addr=" + sdmod::HexString(watch.requested_address) +
                    " old=" + rt::FormatBytes(watch.last_bytes) +
                    " new=" + rt::FormatBytes(current_bytes));
            } else {
                log_lines.push_back(
                    "WATCH: " + watch.name + " changed ptr=" + sdmod::HexString(watch.requested_address) +
                    " base=" + sdmod::HexString(watch.last_base_address) +
                    " -> " + sdmod::HexString(base_address) +
                    " field=" + sdmod::HexString(watch.last_value_address) +
                    " -> " + sdmod::HexString(value_address) +
                    " old=" + rt::FormatBytes(watch.last_bytes) +
                    " new=" + rt::FormatBytes(current_bytes));
            }

            watch.last_valid = true;
            watch.last_base_address = base_address;
            watch.last_value_address = value_address;
            watch.last_bytes = std::move(current_bytes);
        }
    }

    for (const auto& line : log_lines) {
        sdmod::Log(line);
    }
}

extern "C" void RuntimeDebug_Shutdown() {
    namespace rt = sdmod::detail::runtime_debug;

    std::vector<rt::FunctionTrace*> active_traces;

    {
        std::scoped_lock lock(rt::g_runtime_debug_state.mutex);
        active_traces.reserve(rt::g_runtime_debug_state.active_traces.size());
        for (const auto& entry : rt::g_runtime_debug_state.active_traces) {
            active_traces.push_back(entry.second);
        }
        rt::g_runtime_debug_state.active_traces.clear();
        rt::g_runtime_debug_state.watches.clear();
        for (const auto& [page_base, state] : rt::g_runtime_debug_state.guarded_pages) {
            (void)rt::TrySetPageProtection(page_base, state.base_protect);
        }
        rt::g_runtime_debug_state.guarded_pages.clear();
        rt::g_runtime_debug_state.write_watches.clear();
        rt::g_runtime_debug_state.pending_write_hits.clear();
        rt::g_runtime_debug_state.trace_hits.clear();
        rt::g_runtime_debug_state.write_hits.clear();
        if (rt::g_runtime_debug_state.write_watch_handler != nullptr) {
            RemoveVectoredExceptionHandler(rt::g_runtime_debug_state.write_watch_handler);
            rt::g_runtime_debug_state.write_watch_handler = nullptr;
        }
        rt::g_runtime_debug_state.snapshots.clear();
    }

    for (auto* trace : active_traces) {
        if (trace == nullptr) {
            continue;
        }

        trace->active.store(false, std::memory_order_release);
        sdmod::RemoveX86Hook(&trace->hook);
    }
}

std::string RuntimeDebug_GetLastError() {
    return sdmod::detail::runtime_debug::GetRuntimeDebugLastError();
}
