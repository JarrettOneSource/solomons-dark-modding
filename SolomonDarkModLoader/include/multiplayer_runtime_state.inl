#pragma once

#include <mutex>
#include <utility>

namespace sdmod::multiplayer {
namespace detail {

std::mutex& RuntimeStateMutex();
RuntimeState& MutableRuntimeState();

}  // namespace detail

template <typename Fn>
void UpdateRuntimeState(Fn&& updater) {
    std::scoped_lock lock(detail::RuntimeStateMutex());
    updater(detail::MutableRuntimeState());
}

}  // namespace sdmod::multiplayer
