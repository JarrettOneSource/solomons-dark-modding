void Initialize(HMODULE module_handle);
void Shutdown();

std::filesystem::path GetModulePath(HMODULE module_handle);
std::filesystem::path GetModuleDirectory(HMODULE module_handle);
std::filesystem::path GetHostProcessPath();
std::filesystem::path GetHostProcessDirectory();
std::filesystem::path GetStageRuntimeDirectory();
std::filesystem::path GetProjectRoot(HMODULE module_handle);
std::string HexString(uintptr_t value);

bool InitializeGameplayKeyboardInjection(std::string* error_message);
void ShutdownGameplayKeyboardInjection();
bool IsGameplayKeyboardInjectionInitialized();
bool QueueGameplayMouseLeftClick(std::string* error_message);
bool QueueGameplayMouseLeftHoldFrames(std::uint32_t frames, std::string* error_message);
bool QueueGameplayMouseRightClick(std::string* error_message);
bool QueueGameplayMouseRightHoldFrames(std::uint32_t frames, std::string* error_message);
bool QueueGameplayMovementHoldFrames(
    float direction_x,
    float direction_y,
    std::uint32_t frames,
    std::string* error_message);
bool SetGameplayNativeControlAllowanceFrames(
    std::uint32_t frames,
    std::string* error_message);
bool PinManualSpawnerPrimaryTarget(uintptr_t actor_address, std::string* error_message);
bool ApplyPinnedManualSpawnerPrimaryTarget(uintptr_t actor_address);
bool QueueLocalPlayerNativeDispatcherPrimaryCast(
    uintptr_t actor_address,
    std::int32_t dispatched_skill_id);
void ClearQueuedGameplayMouseLeft();
void ClearQueuedGameplayMouseRight();
bool ClearLocalPlayerGameplayCastState(std::string* error_message);
std::uint64_t GetGameplayMouseLeftEdgeSerial();
std::uint64_t GetGameplayMouseLeftEdgeTickMs();
std::uint64_t GetGameplayMouseRightEdgeSerial();
bool TryClaimGameplayMouseLeftPrimaryCastEdge(std::uint64_t edge_serial);
bool IsGameplayMouseLeftDown();
bool IsGameplayMouseRightDown();
bool QueueGameplayBindingPress(std::string_view binding_name, std::string* error_message);
bool QueueGameplayKeyPress(std::string_view binding_name, std::string* error_message);
bool QueueGameplayScancodePress(std::uint32_t scancode, std::string* error_message);
bool QueueGameplayStartWaves(std::string* error_message);
bool QueueGameplayEnableCombatPrelude(std::string* error_message);
bool QueueHubStartTestrun(std::string* error_message);
bool QueueHubOpenService(
    std::string_view service_name,
    std::string* error_message);
bool TryGetHubSurfaceState(
    SDModHubSurfaceState* state,
    std::string* error_message);
bool SetPendingRunGenerationSeed(std::uint32_t seed, std::string* error_message);
bool PrepareArenaRunGenerationSeed(const char* source, std::string* error_message);
bool ReinitializeAppliedRunGenerationSeedForArenaCreate(const char* source);
void ClearLocalRunGenerationSeed();
bool QueueGameplaySwitchRegion(int region_index, std::string* error_message);
bool QueueMultiplayerDampenEffect(
    std::uint64_t owner_participant_id,
    std::uint32_t cast_sequence,
    float position_x,
    float position_y,
    std::string* error_message);
bool QueueLocalPlayerVitalsCorrection(
    std::uint32_t correction_sequence,
    std::uint8_t transient_status_flags,
    std::int32_t poison_remaining_ticks,
    float poison_damage_per_tick,
    std::int32_t webbed_remaining_ticks,
    float webbed_strength,
    std::uint8_t correction_flags,
    float magic_shield_absorb_remaining,
    float magic_shield_absorb_capacity,
    float magic_shield_explosion_fraction,
    float magic_shield_hit_flash,
    std::string* error_message);
bool QueueNativePoisonBehaviorProbe(
    std::uint64_t target_participant_id,
    std::int32_t duration_ticks,
    float damage_per_tick,
    std::int8_t source_slot,
    std::string* error_message);
bool QueueNativeMagicHitBehaviorProbe(
    float projectile_damage,
    float magic_damage,
    float poison_damage,
    std::uint32_t attempts,
    std::uint64_t target_participant_id,
    std::uint64_t* request_serial,
    std::string* error_message);
bool GetNativeMagicHitBehaviorProbeResult(
    std::uint64_t request_serial,
    bool* completed,
    bool* success,
    float* hp_before,
    float* hp_after,
    std::string* error_message);
bool QueueNativeExperienceGainProbe(
    float amount,
    bool apply_native_scaling,
    std::uint64_t* request_serial,
    std::string* error_message);
bool GetNativeExperienceGainProbeResult(
    std::uint64_t request_serial,
    bool* completed,
    bool* success,
    float* xp_before,
    float* xp_after,
    std::uint32_t* exception_code,
    std::string* error_message);
bool QueueNativeStaffEffectProbe(
    uintptr_t source_actor,
    uintptr_t target_actor,
    std::uint32_t variant,
    std::uint64_t* request_serial,
    std::string* error_message);
bool GetNativeStaffEffectProbeResult(
    std::uint64_t request_serial,
    bool* completed,
    bool* success,
    float* hp_before,
    float* hp_after,
    std::string* error_message);
bool QueueParticipantEntitySync(
    std::uint64_t participant_id,
    const multiplayer::MultiplayerCharacterProfile& character_profile,
    const multiplayer::ParticipantSceneIntent& scene_intent,
    bool has_transform,
    bool has_heading,
    float position_x,
    float position_y,
    float heading,
    std::string* error_message);
bool QueueParticipantDestroy(std::uint64_t participant_id, std::string* error_message);

#include "mod_loader_gameplay_api.inl"
