#include "multiplayer_steam_session.h"

#include "logger.h"
#include "lobby_access.h"
#include "mod_loader.h"
#include "multiplayer_local_transport.h"
#include "multiplayer_runtime_protocol.h"
#include "multiplayer_runtime_state.h"
#include "startup_status.h"
#include "steam_bootstrap.h"

#include <Windows.h>
#include <Shellapi.h>

#include <algorithm>
#include <array>
#include <charconv>
#include <cctype>
#include <cstdlib>
#include <cstring>
#include <ctime>
#include <random>
#include <sstream>
#include <string>
#include <unordered_map>
#include <unordered_set>
#include <utility>
#include <vector>

namespace sdmod::multiplayer {
namespace {

#include "multiplayer_steam_session/state_and_helpers.inl"
#include "multiplayer_steam_session/lobby_and_events.inl"
#include "multiplayer_steam_session/network_messages.inl"

}  // namespace

#include "multiplayer_steam_session/public_lifecycle.inl"

}  // namespace sdmod::multiplayer
