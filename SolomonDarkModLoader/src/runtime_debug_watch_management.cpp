#include "runtime_debug_internal.h"

bool RuntimeDebug_UnwatchMemoryByName(const char* name) {
    namespace rt = sdmod::detail::runtime_debug;

    if (name == nullptr || *name == '\0') {
        return false;
    }

    const std::string watch_name(name);
    auto removed = false;
    std::vector<rt::GuardedPageState> pages_to_restore;
    auto remove_write_handler = false;
    {
        std::scoped_lock lock(rt::g_runtime_debug_state.mutex);
        rt::RemoveNamedWatches(&rt::g_runtime_debug_state.watches, watch_name, &removed);
        auto write_it = rt::g_runtime_debug_state.write_watches.begin();
        while (write_it != rt::g_runtime_debug_state.write_watches.end()) {
            if (write_it->name != watch_name) {
                ++write_it;
                continue;
            }

            removed = true;
            for (const auto page_base : write_it->page_bases) {
                auto page_it = rt::g_runtime_debug_state.guarded_pages.find(page_base);
                if (page_it == rt::g_runtime_debug_state.guarded_pages.end()) {
                    continue;
                }
                if (page_it->second.ref_count > 0) {
                    --page_it->second.ref_count;
                }
                if (page_it->second.ref_count == 0) {
                    pages_to_restore.push_back(page_it->second);
                    rt::g_runtime_debug_state.guarded_pages.erase(page_it);
                }
            }
            write_it = rt::g_runtime_debug_state.write_watches.erase(write_it);
        }

        if (rt::g_runtime_debug_state.write_watches.empty() &&
            rt::g_runtime_debug_state.write_watch_handler != nullptr) {
            remove_write_handler = true;
        }
    }

    for (const auto& page : pages_to_restore) {
        (void)rt::TrySetPageProtection(page.page_base, page.base_protect);
    }

    if (remove_write_handler) {
        std::scoped_lock lock(rt::g_runtime_debug_state.mutex);
        if (rt::g_runtime_debug_state.write_watches.empty() &&
            rt::g_runtime_debug_state.write_watch_handler != nullptr) {
            RemoveVectoredExceptionHandler(rt::g_runtime_debug_state.write_watch_handler);
            rt::g_runtime_debug_state.write_watch_handler = nullptr;
        }
    }

    if (removed) {
        sdmod::Log("WATCH: disarmed " + watch_name);
    }
    return removed;
}

void RuntimeDebug_ListWatches(std::vector<RuntimeDebugWatchInfo>* watches) {
    namespace rt = sdmod::detail::runtime_debug;

    if (watches == nullptr) {
        return;
    }

    watches->clear();

    std::scoped_lock lock(rt::g_runtime_debug_state.mutex);
    watches->reserve(rt::g_runtime_debug_state.watches.size());
    for (const auto& watch : rt::g_runtime_debug_state.watches) {
        RuntimeDebugWatchInfo info;
        info.name = watch.name;
        info.requested_address = watch.requested_address;
        info.resolved_address = watch.resolved_address;
        info.last_base_address = watch.last_base_address;
        info.last_value_address = watch.last_value_address;
        info.offset = watch.offset;
        info.size = watch.size;
        info.is_ptr_field = watch.kind == rt::WatchKind::PtrField;
        info.last_valid = watch.last_valid;
        watches->push_back(std::move(info));
    }
}

void RuntimeDebug_ListWriteHits(std::vector<RuntimeDebugWriteHitInfo>* hits, const char* name_filter) {
    namespace rt = sdmod::detail::runtime_debug;

    if (hits == nullptr) {
        return;
    }

    hits->clear();
    const std::string filter = name_filter != nullptr ? std::string(name_filter) : std::string();

    std::scoped_lock lock(rt::g_runtime_debug_state.mutex);
    hits->reserve(rt::g_runtime_debug_state.write_hits.size());
    for (const auto& hit : rt::g_runtime_debug_state.write_hits) {
        if (!filter.empty() && hit.name != filter) {
            continue;
        }
        hits->push_back(hit);
    }
}

void RuntimeDebug_ClearWriteHits(const char* name_filter) {
    namespace rt = sdmod::detail::runtime_debug;

    const std::string filter = name_filter != nullptr ? std::string(name_filter) : std::string();

    std::scoped_lock lock(rt::g_runtime_debug_state.mutex);
    if (filter.empty()) {
        rt::g_runtime_debug_state.write_hits.clear();
        return;
    }

    rt::g_runtime_debug_state.write_hits.erase(
        std::remove_if(
            rt::g_runtime_debug_state.write_hits.begin(),
            rt::g_runtime_debug_state.write_hits.end(),
            [&](const RuntimeDebugWriteHitInfo& hit) { return hit.name == filter; }),
        rt::g_runtime_debug_state.write_hits.end());
}
