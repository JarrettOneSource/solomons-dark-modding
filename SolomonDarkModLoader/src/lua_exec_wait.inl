LuaExecResult QueueLuaExecRequestAndWait(
    const std::string& code,
    std::uint32_t timeout_ms,
    const std::atomic<bool>* service_running) {
    LuaExecResult result;
    if (code.empty()) {
        result.error = "No Lua code was provided.";
        return result;
    }

    // Admission check + enqueue must happen under the same engine-mutex
    // critical section as ShutdownLuaEngine's flag flip and late drain,
    // otherwise a request can slip in after shutdown's late drain and
    // strand its caller until timeout (and survive into a later re-init,
    // since the queue is static). Holding LuaEngineMutex while briefly
    // taking LuaExecQueueMutex inside EnqueueLuaExecRequest does not
    // invert any lock order: ProcessLuaExecQueueOnMainThread releases
    // the queue mutex before acquiring LuaEngineMutex, so the two are
    // never held simultaneously in the opposite direction.
    detail::QueuedLuaExecRequest queued;
    {
        std::scoped_lock lock(detail::LuaEngineMutex());
        if (!detail::LuaEngineInitializedFlag()) {
            result.error = "Lua engine is not initialized.";
            return result;
        }
        queued = detail::EnqueueLuaExecRequest(code);
    }
    const auto pump_generation_at_enqueue =
        detail::LuaExecPumpGeneration().load(std::memory_order_acquire);
    const auto deadline =
        std::chrono::steady_clock::now() + std::chrono::milliseconds(timeout_ms);
    bool ready = false;
    bool service_stopped = false;
    bool pump_skipped_request = false;
    for (;;) {
        const auto now = std::chrono::steady_clock::now();
        if (now >= deadline) {
            break;
        }
        const auto remaining =
            std::chrono::duration_cast<std::chrono::milliseconds>(deadline - now);
        const auto wait_slice =
            (std::min)(remaining, std::chrono::milliseconds(100));
        if (queued.future.wait_for(wait_slice) == std::future_status::ready) {
            ready = true;
            break;
        }
        if (service_running != nullptr &&
            !service_running->load(std::memory_order_acquire)) {
            service_stopped = true;
            break;
        }
        const auto pump_generation =
            detail::LuaExecPumpGeneration().load(std::memory_order_acquire);
        const auto request_state =
            queued.request->state.load(std::memory_order_acquire);
        if (pump_generation - pump_generation_at_enqueue >= 2 &&
            request_state == detail::LuaExecRequestState::Pending) {
            pump_skipped_request = true;
            break;
        }
    }
    if (!ready) {
        const bool canceled = detail::TryCancelLuaExecRequest(queued.request);
        if (!canceled) {
            // Completion can race any wait exit. Prefer the completed result
            // if the gameplay thread published it before this second check.
            ready = queued.future.wait_for(std::chrono::milliseconds(0)) ==
                std::future_status::ready;
        }
        if (!ready) {
            if (service_stopped) {
                result.error = canceled
                    ? "Lua exec request was canceled because the pipe server is stopping."
                    : "Lua exec pipe server stopped after gameplay-thread execution began.";
                return result;
            }
            if (pump_skipped_request) {
                Log(
                    "[lua-exec-diag] invariant failure: gameplay-thread pump "
                    "advanced without claiming a queued request.");
                result.error = canceled
                    ? "Lua exec gameplay-thread pump skipped a queued request."
                    : "Lua exec gameplay-thread pump advanced after request execution began.";
                return result;
            }
            const auto now_ms = static_cast<std::uint64_t>(GetTickCount64());
            const auto endscene_ms =
                lua_exec_diag::g_last_endscene_ms.load(std::memory_order_acquire);
            const auto pump_enter_ms =
                lua_exec_diag::g_last_pump_enter_ms.load(std::memory_order_acquire);
            const auto pump_locked_ms =
                lua_exec_diag::g_last_pump_locked_ms.load(std::memory_order_acquire);
            const auto lua_locked_ms =
                lua_exec_diag::g_last_lua_locked_ms.load(std::memory_order_acquire);
            Log(
                "[lua-exec-diag] timeout. now_ms=" + std::to_string(now_ms) +
                " endscene_ago_ms=" + std::to_string(endscene_ms == 0 ? -1LL : static_cast<std::int64_t>(now_ms - endscene_ms)) +
                " pump_enter_ago_ms=" + std::to_string(pump_enter_ms == 0 ? -1LL : static_cast<std::int64_t>(now_ms - pump_enter_ms)) +
                " pump_locked_ago_ms=" + std::to_string(pump_locked_ms == 0 ? -1LL : static_cast<std::int64_t>(now_ms - pump_locked_ms)) +
                " lua_locked_ago_ms=" + std::to_string(lua_locked_ms == 0 ? -1LL : static_cast<std::int64_t>(now_ms - lua_locked_ms)));
            result.error = canceled
                ? "Lua exec request timed out and was canceled before gameplay-thread execution."
                : "Lua exec request timed out after gameplay-thread execution began.";
            return result;
        }
    }

    try {
        return queued.future.get();
    } catch (const std::future_error& e) {
        result.error = std::string("Lua exec promise error: ") + e.what();
        return result;
    } catch (...) {
        result.error = "Lua exec failed with an unknown exception.";
        return result;
    }
}
