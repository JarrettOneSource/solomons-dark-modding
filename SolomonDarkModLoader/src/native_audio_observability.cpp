#include "native_audio_observability.h"

#include "binary_layout.h"
#include "gameplay_seams.h"
#include "logger.h"
#include "memory_access.h"
#include "mod_loader.h"
#include "x86_hook.h"

#include <Windows.h>
#include <intrin.h>

#include <algorithm>
#include <array>
#include <cmath>
#include <mutex>
#include <sstream>
#include <string>
#include <unordered_map>
#include <utility>

namespace sdmod {
namespace {

#include "native_audio_observability/native_audio_state_and_capture.inl"
#include "native_audio_observability/native_audio_lifecycle_hooks.inl"

}  // namespace

#include "native_audio_observability/native_audio_public_api.inl"
#include "native_audio_observability/native_audio_census_probe.inl"

}  // namespace sdmod
