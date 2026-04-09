#include "multiplayer_foundation.h"

#include "logger.h"
#include "multiplayer_runtime_protocol.h"
#include "multiplayer_service_loop.h"
#include "runtime_flags.h"

#include <mutex>
#include <sstream>

namespace sdmod::multiplayer {
namespace {

std::mutex g_foundation_mutex;
bool g_foundation_initialized = false;

void LogProtocolSummary() {
    std::ostringstream message;
    message << "Multiplayer foundation protocol ready. version=" << kProtocolVersion
            << " magic=SDMP"
            << " sizes{header=" << sizeof(PacketHeader)
            << ",state=" << sizeof(StatePacket)
            << ",launch=" << sizeof(LaunchPacket)
            << ",cast=" << sizeof(CastPacket)
            << ",progression=" << sizeof(ProgressionPacket)
            << "} service_tick_ms=" << GetServiceTickIntervalMs();
    Log(message.str());
}

}  // namespace

void InitializeFoundation() {
    std::scoped_lock lock(g_foundation_mutex);
    if (g_foundation_initialized) {
        return;
    }

    InitializeRuntimeState();
    LogProtocolSummary();

    const auto& runtime_flags = GetActiveRuntimeFeatureFlags();
    if (!runtime_flags.multiplayer.service_loop) {
        UpdateRuntimeState([](RuntimeState& state) {
            state.foundation_ready = true;
            state.service_loop_running = false;
            state.status_text = "Multiplayer foundation initialized with the service loop disabled by runtime flags.";
        });
        Log("Multiplayer foundation initialized with the service loop disabled by runtime flags.");
        g_foundation_initialized = true;
        return;
    }

    if (!StartServiceLoop()) {
        UpdateRuntimeState([](RuntimeState& state) {
            state.session_status = SessionStatus::Error;
            state.status_text = "Multiplayer foundation failed to start the service loop.";
            state.error_text = "Service loop startup failed.";
        });
        Log("Multiplayer foundation failed to initialize.");
        return;
    }

    UpdateRuntimeState([](RuntimeState& state) {
        state.foundation_ready = true;
        state.status_text = "Multiplayer foundation service loop started.";
    });
    Log("Multiplayer foundation initialized.");
    g_foundation_initialized = true;
}

void ShutdownFoundation() {
    std::scoped_lock lock(g_foundation_mutex);
    if (!g_foundation_initialized) {
        ShutdownRuntimeState();
        return;
    }

    MarkRuntimeShuttingDown();
    StopServiceLoop();
    ShutdownRuntimeState();
    g_foundation_initialized = false;
    Log("Multiplayer foundation shut down.");
}

bool IsFoundationInitialized() {
    std::scoped_lock lock(g_foundation_mutex);
    return g_foundation_initialized;
}

RuntimeState SnapshotFoundationState() {
    return SnapshotRuntimeState();
}

}  // namespace sdmod::multiplayer
