BotEntityBinding* FindBotEntity(std::uint64_t bot_id) {
    const auto it = std::find_if(
        g_bot_entities.begin(),
        g_bot_entities.end(),
        [&](const BotEntityBinding& binding) {
            return binding.bot_id == bot_id;
        });
    return it == g_bot_entities.end() ? nullptr : &(*it);
}

BotEntityBinding* FindBotEntityForActor(uintptr_t actor_address) {
    if (actor_address == 0) {
        return nullptr;
    }

    const auto it = std::find_if(
        g_bot_entities.begin(),
        g_bot_entities.end(),
        [&](const BotEntityBinding& binding) {
            return binding.actor_address == actor_address;
        });
    return it == g_bot_entities.end() ? nullptr : &(*it);
}

BotEntityBinding* EnsureBotEntity(std::uint64_t bot_id) {
    auto* binding = FindBotEntity(bot_id);
    if (binding != nullptr) {
        return binding;
    }

    g_bot_entities.push_back(BotEntityBinding{});
    g_bot_entities.back().bot_id = bot_id;
    return &g_bot_entities.back();
}

BotEntityBinding* FindBotEntityForGameplaySlot(int gameplay_slot) {
    const auto it = std::find_if(
        g_bot_entities.begin(),
        g_bot_entities.end(),
        [&](const BotEntityBinding& binding) {
            return binding.gameplay_slot == gameplay_slot;
        });
    return it == g_bot_entities.end() ? nullptr : &(*it);
}

PendingWizardBotSyncRequest* FindPendingWizardBotSyncRequest(std::uint64_t bot_id) {
    const auto it = std::find_if(
        g_gameplay_keyboard_injection.pending_wizard_bot_sync_requests.begin(),
        g_gameplay_keyboard_injection.pending_wizard_bot_sync_requests.end(),
        [&](const PendingWizardBotSyncRequest& request) {
            return request.bot_id == bot_id;
        });
    return it == g_gameplay_keyboard_injection.pending_wizard_bot_sync_requests.end() ? nullptr : &(*it);
}

void UpsertPendingWizardBotSyncRequest(const PendingWizardBotSyncRequest& request) {
    auto* pending_request = FindPendingWizardBotSyncRequest(request.bot_id);
    if (pending_request == nullptr) {
        g_gameplay_keyboard_injection.pending_wizard_bot_sync_requests.push_back(request);
        return;
    }

    *pending_request = request;
}

void RemovePendingWizardBotSyncRequest(std::uint64_t bot_id) {
    g_gameplay_keyboard_injection.pending_wizard_bot_sync_requests.erase(
        std::remove_if(
            g_gameplay_keyboard_injection.pending_wizard_bot_sync_requests.begin(),
            g_gameplay_keyboard_injection.pending_wizard_bot_sync_requests.end(),
            [&](const PendingWizardBotSyncRequest& request) {
                return request.bot_id == bot_id;
            }),
        g_gameplay_keyboard_injection.pending_wizard_bot_sync_requests.end());
}

void RemovePendingWizardBotDestroyRequest(std::uint64_t bot_id) {
    g_gameplay_keyboard_injection.pending_wizard_bot_destroy_requests.erase(
        std::remove(
            g_gameplay_keyboard_injection.pending_wizard_bot_destroy_requests.begin(),
            g_gameplay_keyboard_injection.pending_wizard_bot_destroy_requests.end(),
            bot_id),
        g_gameplay_keyboard_injection.pending_wizard_bot_destroy_requests.end());
}

void UpsertPendingWizardBotDestroyRequest(std::uint64_t bot_id) {
    if (bot_id == 0) {
        return;
    }

    const auto it = std::find(
        g_gameplay_keyboard_injection.pending_wizard_bot_destroy_requests.begin(),
        g_gameplay_keyboard_injection.pending_wizard_bot_destroy_requests.end(),
        bot_id);
    if (it == g_gameplay_keyboard_injection.pending_wizard_bot_destroy_requests.end()) {
        g_gameplay_keyboard_injection.pending_wizard_bot_destroy_requests.push_back(bot_id);
    }
}

void RememberBotEntity(
    std::uint64_t bot_id,
    std::int32_t wizard_id,
    uintptr_t actor_address,
    BotEntityBinding::Kind kind,
    int gameplay_slot = -1,
    bool raw_allocation = false) {
    std::lock_guard<std::recursive_mutex> lock(g_bot_entities_mutex);
    auto* binding = EnsureBotEntity(bot_id);
    if (binding == nullptr) {
        return;
    }

    if (binding->actor_address != 0 && binding->actor_address != actor_address) {
        binding->materialized_scene_address = 0;
        binding->materialized_world_address = 0;
        binding->materialized_region_index = -1;
        binding->gameplay_attach_applied = false;
        binding->standalone_idle_animation_drive_profile = ObservedActorAnimationDriveProfile{};
        binding->standalone_moving_animation_drive_profile = ObservedActorAnimationDriveProfile{};
        binding->standalone_progression_wrapper_address = 0;
        binding->standalone_progression_inner_address = 0;
        binding->standalone_equip_wrapper_address = 0;
        binding->standalone_equip_inner_address = 0;
        binding->synthetic_source_profile_address = 0;
    }

    binding->wizard_id = wizard_id;
    binding->actor_address = actor_address;
    binding->gameplay_slot = gameplay_slot;
    binding->kind = kind;
    binding->raw_allocation = raw_allocation;
    if (actor_address == 0) {
        binding->gameplay_attach_applied = false;
        binding->standalone_idle_animation_drive_profile = ObservedActorAnimationDriveProfile{};
        binding->standalone_moving_animation_drive_profile = ObservedActorAnimationDriveProfile{};
        binding->standalone_progression_wrapper_address = 0;
        binding->standalone_progression_inner_address = 0;
        binding->standalone_equip_wrapper_address = 0;
        binding->standalone_equip_inner_address = 0;
        binding->synthetic_source_profile_address = 0;
        binding->raw_allocation = false;
    }
}

void ResetBotEntityMaterializationState(BotEntityBinding* binding) {
    if (binding == nullptr) {
        return;
    }

    binding->actor_address = 0;
    binding->next_scene_materialize_retry_ms = 0;
    binding->materialized_scene_address = 0;
    binding->materialized_world_address = 0;
    binding->materialized_region_index = -1;
    binding->last_applied_animation_state_id = kUnknownAnimationStateId - 1;
    binding->standalone_idle_animation_drive_profile = ObservedActorAnimationDriveProfile{};
    binding->standalone_moving_animation_drive_profile = ObservedActorAnimationDriveProfile{};
    binding->standalone_progression_wrapper_address = 0;
    binding->standalone_progression_inner_address = 0;
    binding->standalone_equip_wrapper_address = 0;
    binding->standalone_equip_inner_address = 0;
    binding->gameplay_attach_applied = false;
    binding->raw_allocation = false;
    binding->synthetic_source_profile_address = 0;
}

void ForgetBotEntity(std::uint64_t bot_id) {
    std::lock_guard<std::recursive_mutex> entity_lock(g_bot_entities_mutex);
    g_bot_entities.erase(
        std::remove_if(
            g_bot_entities.begin(),
            g_bot_entities.end(),
            [&](const BotEntityBinding& binding) {
                return binding.bot_id == bot_id;
            }),
        g_bot_entities.end());

    std::lock_guard<std::mutex> snapshot_lock(g_wizard_bot_snapshot_mutex);
    g_wizard_bot_gameplay_snapshots.erase(
        std::remove_if(
            g_wizard_bot_gameplay_snapshots.begin(),
            g_wizard_bot_gameplay_snapshots.end(),
            [&](const WizardBotGameplaySnapshot& snapshot) {
                return snapshot.bot_id == bot_id;
            }),
        g_wizard_bot_gameplay_snapshots.end());
    RefreshWizardBotCrashSummaryLocked();
}

void DematerializeWizardBotEntityNow(std::uint64_t bot_id, bool forget_binding, std::string_view reason) {
    auto& memory = ProcessMemory::Instance();
    std::lock_guard<std::recursive_mutex> lock(g_bot_entities_mutex);
    auto* binding = FindBotEntity(bot_id);
    if (binding == nullptr) {
        if (forget_binding) {
            ForgetBotEntity(bot_id);
        }
        return;
    }

    if (binding->actor_address != 0) {
        StopWizardBotActorMotion(binding->actor_address);

        std::string destroy_error;
        bool destroyed = false;
        if (binding->kind == BotEntityBinding::Kind::StandaloneWizard &&
            binding->gameplay_slot >= kFirstWizardBotSlot) {
            auto gameplay_address = binding->materialized_scene_address;
            if (gameplay_address == 0) {
                (void)TryResolveCurrentGameplayScene(&gameplay_address);
            }

            if (gameplay_address != 0) {
                destroyed = DestroyGameplaySlotBotResources(
                    gameplay_address,
                    binding->gameplay_slot,
                    binding->actor_address,
                    binding->materialized_world_address,
                    binding->gameplay_attach_applied,
                    binding->synthetic_source_profile_address,
                    &destroy_error);
            } else {
                destroy_error = "Gameplay slot cleanup could not resolve a gameplay scene.";
            }
        } else {
            if (binding->kind == BotEntityBinding::Kind::StandaloneWizard &&
                (binding->standalone_progression_wrapper_address != 0 ||
                 binding->standalone_progression_inner_address != 0 ||
                 binding->standalone_equip_wrapper_address != 0 ||
                 binding->standalone_equip_inner_address != 0)) {
                ReleaseStandaloneWizardVisualResources(
                    binding->actor_address,
                    binding->standalone_progression_wrapper_address,
                    binding->standalone_progression_inner_address,
                    binding->standalone_equip_wrapper_address,
                    binding->standalone_equip_inner_address);
                binding->standalone_progression_wrapper_address = 0;
                binding->standalone_progression_inner_address = 0;
                binding->standalone_equip_wrapper_address = 0;
                binding->standalone_equip_inner_address = 0;
            }
            destroyed = DestroyLoaderOwnedWizardActor(
                binding->actor_address,
                binding->materialized_world_address,
                binding->raw_allocation,
                &destroy_error);
        }
        if (destroyed) {
            DestroySyntheticWizardSourceProfile(binding->synthetic_source_profile_address);
            binding->synthetic_source_profile_address = 0;
        }
        if (!destroyed) {
            (void)memory.TryWriteField(binding->actor_address, kActorPositionXOffset, 100000.0f);
            (void)memory.TryWriteField(binding->actor_address, kActorPositionYOffset, 100000.0f);
            (void)memory.TryWriteField(binding->actor_address, kActorHeadingOffset, 0.0f);
        }
        Log(
            "[bots] dematerialized bot entity. bot_id=" + std::to_string(bot_id) +
            " slot=" + std::to_string(binding->gameplay_slot) +
            " kind=" + std::to_string(static_cast<int>(binding->kind)) +
            " actor=" + HexString(binding->actor_address) +
            " reason=" + std::string(reason) +
            (destroy_error.empty() ? std::string() : " detail=" + destroy_error));
    }

    ResetBotEntityMaterializationState(binding);
    PublishWizardBotGameplaySnapshot(*binding);
    if (forget_binding) {
        ForgetBotEntity(bot_id);
    }
}

WizardBotGameplaySnapshot BuildWizardBotGameplaySnapshot(const BotEntityBinding& binding) {
    WizardBotGameplaySnapshot snapshot;
    snapshot.bot_id = binding.bot_id;
    snapshot.entity_materialized = binding.actor_address != 0;
    snapshot.moving = binding.movement_active;
    snapshot.wizard_id = binding.wizard_id;
    snapshot.actor_address = binding.actor_address;
    snapshot.hub_visual_proxy_address = 0;
    snapshot.gameplay_slot = binding.gameplay_slot;
    snapshot.gameplay_attach_applied = binding.gameplay_attach_applied;

    if (binding.actor_address == 0) {
        return snapshot;
    }

    auto& memory = ProcessMemory::Instance();
    const auto render_probe_address = binding.actor_address;
    snapshot.world_address = memory.ReadFieldOr<uintptr_t>(binding.actor_address, kActorOwnerOffset, 0);
    snapshot.actor_slot = memory.ReadFieldOr<std::int8_t>(binding.actor_address, kActorSlotOffset, -1);
    snapshot.slot_anim_state_index = ResolveActorAnimationStateSlotIndex(binding.actor_address);
    snapshot.animation_state_ptr =
        memory.ReadFieldOr<uintptr_t>(render_probe_address, kActorAnimationSelectionStateOffset, 0);
    snapshot.render_frame_table =
        memory.ReadFieldOr<uintptr_t>(render_probe_address, kActorRenderFrameTableOffset, 0);
    snapshot.hub_visual_attachment_ptr =
        memory.ReadFieldOr<uintptr_t>(render_probe_address, kActorHubVisualAttachmentPtrOffset, 0);
    snapshot.hub_visual_source_profile_address =
        memory.ReadFieldOr<uintptr_t>(render_probe_address, kActorHubVisualSourceProfileOffset, 0);
    snapshot.hub_visual_descriptor_signature = HashMemoryBlockFNV1a32(
        render_probe_address + kActorHubVisualDescriptorBlockOffset,
        kActorHubVisualDescriptorBlockSize);
    snapshot.progression_handle_address =
        memory.ReadFieldOr<uintptr_t>(render_probe_address, kActorProgressionHandleOffset, 0);
    snapshot.equip_handle_address =
        memory.ReadFieldOr<uintptr_t>(render_probe_address, kActorEquipHandleOffset, 0);
    snapshot.progression_runtime_state_address =
        memory.ReadFieldOr<uintptr_t>(render_probe_address, kActorProgressionRuntimeStateOffset, 0);
    snapshot.equip_runtime_state_address =
        memory.ReadFieldOr<uintptr_t>(render_probe_address, kActorEquipRuntimeStateOffset, 0);
    if (snapshot.progression_runtime_state_address == 0 && snapshot.progression_handle_address != 0) {
        snapshot.progression_runtime_state_address =
            ReadSmartPointerInnerObject(snapshot.progression_handle_address);
    }
    if (snapshot.equip_runtime_state_address == 0 && snapshot.equip_handle_address != 0) {
        snapshot.equip_runtime_state_address =
            ReadSmartPointerInnerObject(snapshot.equip_handle_address);
    }
    snapshot.primary_visual_lane = ReadEquipVisualLaneState(
        snapshot.equip_runtime_state_address,
        kActorEquipRuntimeVisualLinkPrimaryOffset);
    snapshot.secondary_visual_lane = ReadEquipVisualLaneState(
        snapshot.equip_runtime_state_address,
        kActorEquipRuntimeVisualLinkSecondaryOffset);
    snapshot.attachment_visual_lane = ReadEquipVisualLaneState(
        snapshot.equip_runtime_state_address,
        kActorEquipRuntimeVisualLinkAttachmentOffset);
    snapshot.resolved_animation_state_id = ResolveActorAnimationStateId(render_probe_address);
    snapshot.hub_visual_source_kind =
        memory.ReadFieldOr<std::int32_t>(render_probe_address, kActorHubVisualSourceKindOffset, 0);
    snapshot.render_drive_flags =
        memory.ReadFieldOr<std::uint32_t>(render_probe_address, kActorRenderDriveFlagsOffset, 0);
    snapshot.anim_drive_state =
        memory.ReadFieldOr<std::uint8_t>(render_probe_address, kActorAnimationDriveStateByteOffset, 0);
    snapshot.render_variant_primary =
        memory.ReadFieldOr<std::uint8_t>(render_probe_address, kActorRenderVariantPrimaryOffset, 0);
    snapshot.render_variant_secondary =
        memory.ReadFieldOr<std::uint8_t>(render_probe_address, kActorRenderVariantSecondaryOffset, 0);
    snapshot.render_weapon_type =
        memory.ReadFieldOr<std::uint8_t>(render_probe_address, kActorRenderWeaponTypeOffset, 0);
    snapshot.render_selection_byte =
        memory.ReadFieldOr<std::uint8_t>(render_probe_address, kActorRenderSelectionByteOffset, 0);
    snapshot.render_variant_tertiary =
        memory.ReadFieldOr<std::uint8_t>(render_probe_address, kActorRenderVariantTertiaryOffset, 0);
    snapshot.x = memory.ReadFieldOr<float>(binding.actor_address, kActorPositionXOffset, 0.0f);
    snapshot.y = memory.ReadFieldOr<float>(binding.actor_address, kActorPositionYOffset, 0.0f);
    snapshot.heading = memory.ReadFieldOr<float>(binding.actor_address, kActorHeadingOffset, 0.0f);
    snapshot.walk_cycle_primary =
        memory.ReadFieldOr<float>(render_probe_address, kActorWalkCyclePrimaryOffset, 0.0f);
    snapshot.walk_cycle_secondary =
        memory.ReadFieldOr<float>(render_probe_address, kActorWalkCycleSecondaryOffset, 0.0f);
    snapshot.render_drive_stride =
        memory.ReadFieldOr<float>(render_probe_address, kActorRenderDriveStrideScaleOffset, 0.0f);
    snapshot.render_advance_rate =
        memory.ReadFieldOr<float>(render_probe_address, kActorRenderAdvanceRateOffset, 0.0f);
    snapshot.render_advance_phase =
        memory.ReadFieldOr<float>(render_probe_address, kActorRenderAdvancePhaseOffset, 0.0f);
    snapshot.render_drive_overlay_alpha =
        memory.ReadFieldOr<float>(render_probe_address, kActorRenderDriveOverlayAlphaOffset, 0.0f);
    snapshot.render_drive_move_blend =
        memory.ReadFieldOr<float>(render_probe_address, kActorRenderDriveMoveBlendOffset, 0.0f);

    auto progression_address =
        memory.ReadFieldOr<uintptr_t>(binding.actor_address, kActorProgressionRuntimeStateOffset, 0);
    if (progression_address == 0 && snapshot.progression_handle_address != 0) {
        progression_address = ReadSmartPointerInnerObject(snapshot.progression_handle_address);
    }
    if (progression_address != 0) {
        snapshot.hp = memory.ReadFieldOr<float>(progression_address, kProgressionHpOffset, 0.0f);
        snapshot.max_hp = memory.ReadFieldOr<float>(progression_address, kProgressionMaxHpOffset, 0.0f);
        snapshot.mp = memory.ReadFieldOr<float>(progression_address, kProgressionMpOffset, 0.0f);
        snapshot.max_mp = memory.ReadFieldOr<float>(progression_address, kProgressionMaxMpOffset, 0.0f);
    }

    return snapshot;
}

void PublishWizardBotGameplaySnapshot(const BotEntityBinding& binding) {
    const auto snapshot = BuildWizardBotGameplaySnapshot(binding);
    std::lock_guard<std::mutex> lock(g_wizard_bot_snapshot_mutex);
    const auto it = std::find_if(
        g_wizard_bot_gameplay_snapshots.begin(),
        g_wizard_bot_gameplay_snapshots.end(),
        [&](const WizardBotGameplaySnapshot& existing) {
            return existing.bot_id == binding.bot_id;
        });
    if (it == g_wizard_bot_gameplay_snapshots.end()) {
        g_wizard_bot_gameplay_snapshots.push_back(snapshot);
        RefreshWizardBotCrashSummaryLocked();
        return;
    }

    *it = snapshot;
    RefreshWizardBotCrashSummaryLocked();
}

bool TryBuildBotRematerializationRequest(
    uintptr_t gameplay_address,
    const BotEntityBinding& binding,
    BotRematerializationRequest* request) {
    if (request == nullptr || binding.actor_address == 0) {
        return false;
    }

    *request = BotRematerializationRequest{};
    if (binding.materialized_scene_address == 0 && binding.materialized_world_address == 0) {
        return false;
    }

    SceneContextSnapshot scene_context;
    if (!TryBuildSceneContextSnapshot(gameplay_address, &scene_context)) {
        return false;
    }

    if (!HasBotMaterializedSceneChanged(binding, scene_context)) {
        return false;
    }

    multiplayer::BotSnapshot bot_snapshot;
    if (!multiplayer::ReadBotSnapshot(binding.bot_id, &bot_snapshot) || !bot_snapshot.available) {
        return false;
    }

    request->bot_id = binding.bot_id;
    request->wizard_id = bot_snapshot.wizard_id;
    request->has_transform = bot_snapshot.transform_valid;
    request->x = bot_snapshot.position_x;
    request->y = bot_snapshot.position_y;
    request->heading = bot_snapshot.heading;
    request->previous_scene_address = binding.materialized_scene_address;
    request->previous_world_address = binding.materialized_world_address;
    request->previous_region_index = binding.materialized_region_index;
    request->next_scene_address = scene_context.gameplay_scene_address;
    request->next_world_address = scene_context.world_address;
    request->next_region_index = scene_context.current_region_index;
    return true;
}

void QueueBotRematerialization(const BotRematerializationRequest& request) {
    Log(
        "[bots] rematerializing entity. bot_id=" + std::to_string(request.bot_id) +
        " old_scene=" + HexString(request.previous_scene_address) +
        " new_scene=" + HexString(request.next_scene_address) +
        " old_world=" + HexString(request.previous_world_address) +
        " new_world=" + HexString(request.next_world_address) +
        " old_region=" + std::to_string(request.previous_region_index) +
        " new_region=" + std::to_string(request.next_region_index));

    DematerializeWizardBotEntityNow(request.bot_id, false, "scene transition");

    std::string error_message;
    if (!QueueWizardBotEntitySync(
            request.bot_id,
            request.wizard_id,
            request.has_transform,
            true,
            request.x,
            request.y,
            request.heading,
            &error_message)) {
        Log(
            "[bots] rematerialize queue failed. bot_id=" + std::to_string(request.bot_id) +
            " error=" + error_message);
    }
}

bool ResolveWizardBotTransform(
    uintptr_t gameplay_address,
    const PendingWizardBotSyncRequest& request,
    float* out_x,
    float* out_y,
    float* out_heading) {
    if (out_x == nullptr || out_y == nullptr || out_heading == nullptr) {
        return false;
    }

    float x = request.x;
    float y = request.y;
    float heading = request.heading;
    if (!request.has_transform) {
        uintptr_t local_actor_address = 0;
        if (!TryResolvePlayerActorForSlot(gameplay_address, 0, &local_actor_address) || local_actor_address == 0) {
            return false;
        }

        auto& memory = ProcessMemory::Instance();
        x = memory.ReadFieldOr<float>(local_actor_address, kActorPositionXOffset, 0.0f) + kDefaultWizardBotOffsetX;
        y = memory.ReadFieldOr<float>(local_actor_address, kActorPositionYOffset, 0.0f) + kDefaultWizardBotOffsetY;
        heading = memory.ReadFieldOr<float>(local_actor_address, kActorHeadingOffset, 0.0f);
    } else if (!request.has_heading) {
        uintptr_t existing_actor_address = 0;
        if (request.bot_id != 0) {
            if (const auto* binding = FindBotEntity(request.bot_id); binding != nullptr) {
                existing_actor_address = binding->actor_address;
            }
        }

        auto& memory = ProcessMemory::Instance();
        if (existing_actor_address != 0) {
            heading = memory.ReadFieldOr<float>(existing_actor_address, kActorHeadingOffset, 0.0f);
        } else {
            uintptr_t local_actor_address = 0;
            if (!TryResolvePlayerActorForSlot(gameplay_address, 0, &local_actor_address) || local_actor_address == 0) {
                return false;
            }
            heading = memory.ReadFieldOr<float>(local_actor_address, kActorHeadingOffset, 0.0f);
        }
    }

    *out_x = x;
    *out_y = y;
    *out_heading = heading;
    return true;
}

void ResetEnemyModifierList(EnemyModifierList* modifier_list) {
    if (modifier_list == nullptr) {
        return;
    }

    modifier_list->vtable =
        ProcessMemory::Instance().ResolveGameAddressOrZero(kEnemyModifierListVtable);
    modifier_list->items = nullptr;
    modifier_list->count = 0;
    modifier_list->capacity = 0;
    modifier_list->reserved = 0;
}

void CleanupEnemyModifierList(EnemyModifierList* modifier_list) {
    if (modifier_list == nullptr) {
        return;
    }

    const auto free_address = ProcessMemory::Instance().ResolveGameAddressOrZero(kGameFree);
    auto* items = modifier_list->items;
    ResetEnemyModifierList(modifier_list);
    if (items == nullptr || free_address == 0) {
        return;
    }

    auto free_memory = reinterpret_cast<GameFreeFn>(free_address);
    free_memory(items);
}

int CaptureSehCode(EXCEPTION_POINTERS* exception_pointers, DWORD* exception_code) {
    if (exception_code != nullptr) {
        *exception_code = 0;
        if (exception_pointers != nullptr && exception_pointers->ExceptionRecord != nullptr) {
            *exception_code = exception_pointers->ExceptionRecord->ExceptionCode;
        }
    }
    return EXCEPTION_EXECUTE_HANDLER;
}

int CaptureSehDetails(
    EXCEPTION_POINTERS* exception_pointers,
    SehExceptionDetails* exception_details) {
    if (exception_details != nullptr) {
        *exception_details = {};
        if (exception_pointers != nullptr) {
            if (exception_pointers->ExceptionRecord != nullptr) {
                const auto* record = exception_pointers->ExceptionRecord;
                exception_details->code = record->ExceptionCode;
                exception_details->exception_address =
                    reinterpret_cast<uintptr_t>(record->ExceptionAddress);
                if (record->NumberParameters >= 2 &&
                    (record->ExceptionCode == EXCEPTION_ACCESS_VIOLATION ||
                     record->ExceptionCode == EXCEPTION_IN_PAGE_ERROR)) {
                    exception_details->access_type =
                        static_cast<DWORD>(record->ExceptionInformation[0]);
                    exception_details->access_address =
                        static_cast<uintptr_t>(record->ExceptionInformation[1]);
                }
            }
            if (exception_pointers->ContextRecord != nullptr) {
                exception_details->eip =
                    static_cast<uintptr_t>(exception_pointers->ContextRecord->Eip);
            }
        }
    }
    return EXCEPTION_EXECUTE_HANDLER;
}

std::string FormatSehExceptionDetails(const SehExceptionDetails& details) {
    std::ostringstream out;
    out << "code=0x" << HexString(details.code)
        << " exception_address=0x" << HexString(details.exception_address)
        << " eip=0x" << HexString(details.eip);
    if (details.access_address != 0 || details.access_type != 0) {
        out << " access_type=" << details.access_type
            << " access_address=0x" << HexString(details.access_address);
    }
    return out.str();
}

bool CallGameplayCreatePlayerSlotSafe(
    uintptr_t create_player_slot_address,
    uintptr_t gameplay_address,
    int slot_index,
    DWORD* exception_code) {
    auto* create_player_slot = reinterpret_cast<GameplayCreatePlayerSlotFn>(create_player_slot_address);
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (create_player_slot == nullptr || gameplay_address == 0 || slot_index < 0) {
        return false;
    }

    __try {
        create_player_slot(reinterpret_cast<void*>(gameplay_address), slot_index);
        return true;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool CallPuppetManagerDeletePuppetSafe(
    uintptr_t delete_puppet_address,
    uintptr_t manager_address,
    uintptr_t actor_address,
    DWORD* exception_code) {
    auto* delete_puppet = reinterpret_cast<PuppetManagerDeletePuppetFn>(delete_puppet_address);
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (delete_puppet == nullptr || manager_address == 0 || actor_address == 0) {
        return false;
    }

    __try {
        delete_puppet(reinterpret_cast<void*>(manager_address), reinterpret_cast<void*>(actor_address));
        return true;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool CallObjectDeleteSafe(
    uintptr_t object_delete_address,
    uintptr_t object_address,
    DWORD* exception_code) {
    auto* object_delete = reinterpret_cast<ObjectDeleteFn>(object_delete_address);
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (object_delete == nullptr || object_address == 0) {
        return false;
    }

    __try {
        object_delete(reinterpret_cast<void*>(object_address));
        return true;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool CallActorWorldRegisterSafe(
    uintptr_t actor_world_register_address,
    uintptr_t world_address,
    int actor_group,
    uintptr_t actor_address,
    int slot_index,
    char use_alt_list,
    DWORD* exception_code) {
    auto* actor_world_register = reinterpret_cast<ActorWorldRegisterFn>(actor_world_register_address);
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (actor_world_register == nullptr || world_address == 0 || actor_address == 0) {
        return false;
    }

    __try {
        return actor_world_register(
                   reinterpret_cast<void*>(world_address),
                   actor_group,
                   reinterpret_cast<void*>(actor_address),
                   slot_index,
                   use_alt_list) != 0;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool CallGameObjectFactorySafe(
    uintptr_t factory_address,
    uintptr_t factory_context_address,
    int type_id,
    uintptr_t* object_address,
    DWORD* exception_code) {
    if (object_address != nullptr) {
        *object_address = 0;
    }
    if (exception_code != nullptr) {
        *exception_code = 0;
    }

    auto* factory = reinterpret_cast<GameObjectFactoryFn>(factory_address);
    if (factory == nullptr || factory_context_address == 0) {
        return false;
    }

    __try {
        const auto object_address_value =
            factory(reinterpret_cast<void*>(factory_context_address), type_id);
        if (object_address != nullptr) {
            *object_address = object_address_value;
        }
        return object_address_value != 0;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool CallGameOperatorNewSafe(
    uintptr_t operator_new_address,
    std::size_t allocation_size,
    uintptr_t* allocation_address,
    DWORD* exception_code) {
    if (allocation_address != nullptr) {
        *allocation_address = 0;
    }
    if (exception_code != nullptr) {
        *exception_code = 0;
    }

    auto* operator_new_fn = reinterpret_cast<GameOperatorNewFn>(operator_new_address);
    if (operator_new_fn == nullptr) {
        return false;
    }

    __try {
        const auto allocation = operator_new_fn(allocation_size);
        if (allocation_address != nullptr) {
            *allocation_address = reinterpret_cast<uintptr_t>(allocation);
        }
        return allocation != nullptr;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool CallGameObjectAllocateSafe(
    uintptr_t object_allocate_address,
    std::size_t allocation_size,
    uintptr_t* allocation_address,
    DWORD* exception_code) {
    if (allocation_address != nullptr) {
        *allocation_address = 0;
    }
    if (exception_code != nullptr) {
        *exception_code = 0;
    }

    auto* object_allocate_fn = reinterpret_cast<GameObjectAllocateFn>(object_allocate_address);
    if (object_allocate_fn == nullptr) {
        return false;
    }

    __try {
        const auto allocation = object_allocate_fn(allocation_size);
        if (allocation_address != nullptr) {
            *allocation_address = reinterpret_cast<uintptr_t>(allocation);
        }
        return allocation != nullptr;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool CallGameFreeSafe(
    uintptr_t free_address,
    uintptr_t allocation_address,
    DWORD* exception_code) {
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (allocation_address == 0) {
        return true;
    }

    auto* free_fn = reinterpret_cast<GameFreeFn>(free_address);
    if (free_fn == nullptr) {
        return false;
    }

    __try {
        free_fn(reinterpret_cast<void*>(allocation_address));
        return true;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool CallRawObjectCtorSafe(
    uintptr_t ctor_address,
    void* object_memory,
    uintptr_t* object_address,
    DWORD* exception_code) {
    if (object_address != nullptr) {
        *object_address = 0;
    }
    if (exception_code != nullptr) {
        *exception_code = 0;
    }

    auto* ctor = reinterpret_cast<RawObjectCtorFn>(ctor_address);
    if (ctor == nullptr || object_memory == nullptr) {
        return false;
    }

    __try {
        auto* object = ctor(object_memory);
        if (object_address != nullptr) {
            *object_address = reinterpret_cast<uintptr_t>(object);
        }
        return object != nullptr;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool CallPlayerActorCtorSafe(
    uintptr_t ctor_address,
    void* actor_memory,
    uintptr_t* actor_address,
    DWORD* exception_code) {
    if (actor_address != nullptr) {
        *actor_address = 0;
    }
    if (exception_code != nullptr) {
        *exception_code = 0;
    }

    auto* ctor = reinterpret_cast<PlayerActorCtorFn>(ctor_address);
    if (ctor == nullptr || actor_memory == nullptr) {
        return false;
    }

    __try {
        auto* actor = ctor(actor_memory);
        if (actor_address != nullptr) {
            *actor_address = reinterpret_cast<uintptr_t>(actor);
        }
        return actor != nullptr;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

uintptr_t ReadSmartPointerInnerObject(uintptr_t wrapper_address) {
    if (wrapper_address == 0) {
        return 0;
    }

    auto& memory = ProcessMemory::Instance();
    const auto direct_inner = memory.ReadValueOr<uintptr_t>(wrapper_address, 0);
    if (direct_inner != 0 && memory.IsReadableRange(direct_inner, 1)) {
        return direct_inner;
    }

    // Gameplay-slot wrappers are not the loader-owned 8-byte clone wrappers.
    // Their live object pointer sits at +0x0C, so support both contracts here.
    const auto gameplay_inner = memory.ReadValueOr<uintptr_t>(wrapper_address + 0x0C, 0);
    if (gameplay_inner != 0 && memory.IsReadableRange(gameplay_inner, 1)) {
        return gameplay_inner;
    }

    return direct_inner;
}

bool RetainSmartPointerWrapperSafe(uintptr_t wrapper_address, DWORD* exception_code) {
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (wrapper_address == 0) {
        return true;
    }

    __try {
        auto* wrapper = reinterpret_cast<std::int32_t*>(wrapper_address);
        ++wrapper[1];
        return true;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool ReleaseSmartPointerWrapperSafe(uintptr_t wrapper_address, DWORD* exception_code) {
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (wrapper_address == 0) {
        return true;
    }

    const auto free_address = ProcessMemory::Instance().ResolveGameAddressOrZero(kGameFree);
    if (free_address == 0) {
        return false;
    }

    __try {
        auto* wrapper = reinterpret_cast<std::int32_t*>(wrapper_address);
        --wrapper[1];
        if (wrapper[1] > 0) {
            return true;
        }

        auto* inner_object = reinterpret_cast<void*>(static_cast<uintptr_t>(wrapper[0]));
        if (inner_object != nullptr) {
            const auto vtable = *reinterpret_cast<uintptr_t*>(inner_object);
            const auto destructor_address = *reinterpret_cast<uintptr_t*>(vtable);
            auto* destructor = reinterpret_cast<ScalarDeletingDestructorFn>(destructor_address);
            destructor(inner_object, 1);
        }

        auto* free_memory = reinterpret_cast<GameFreeFn>(free_address);
        free_memory(reinterpret_cast<void*>(wrapper_address));
        return true;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool AssignActorSmartPointerWrapperSafe(
    uintptr_t actor_address,
    std::size_t wrapper_offset,
    std::size_t runtime_state_offset,
    uintptr_t source_wrapper_address,
    DWORD* exception_code) {
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (actor_address == 0) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const auto existing_wrapper_address = memory.ReadFieldOr<uintptr_t>(actor_address, wrapper_offset, 0);
    if (existing_wrapper_address == source_wrapper_address) {
        const auto inner_object = ReadSmartPointerInnerObject(source_wrapper_address);
        return memory.TryWriteField(actor_address, runtime_state_offset, inner_object);
    }

    if (source_wrapper_address != 0 &&
        !RetainSmartPointerWrapperSafe(source_wrapper_address, exception_code)) {
        return false;
    }

    if (!memory.TryWriteField(actor_address, wrapper_offset, source_wrapper_address)) {
        if (source_wrapper_address != 0) {
            DWORD release_exception = 0;
            (void)ReleaseSmartPointerWrapperSafe(source_wrapper_address, &release_exception);
        }
        return false;
    }

    const auto inner_object = ReadSmartPointerInnerObject(source_wrapper_address);
    if (!memory.TryWriteField(actor_address, runtime_state_offset, inner_object)) {
        return false;
    }

    if (existing_wrapper_address != 0) {
        DWORD release_exception = 0;
        if (!ReleaseSmartPointerWrapperSafe(existing_wrapper_address, &release_exception) &&
            exception_code != nullptr &&
            *exception_code == 0) {
            *exception_code = release_exception;
        }
    }

    return true;
}

bool CallPlayerActorEnsureProgressionHandleSafe(
    uintptr_t ensure_progression_handle_address,
    uintptr_t actor_address,
    DWORD* exception_code) {
    auto* ensure_progression_handle =
        reinterpret_cast<PlayerActorNoArgMethodFn>(ensure_progression_handle_address);
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (ensure_progression_handle == nullptr || actor_address == 0) {
        return false;
    }

    __try {
        ensure_progression_handle(reinterpret_cast<void*>(actor_address));
        return true;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool CallPlayerActorRefreshRuntimeHandlesSafe(
    uintptr_t refresh_address,
    uintptr_t actor_address,
    DWORD* exception_code) {
    auto* refresh_runtime_handles = reinterpret_cast<PlayerActorRefreshRuntimeHandlesFn>(refresh_address);
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (refresh_runtime_handles == nullptr || actor_address == 0) {
        return false;
    }

    __try {
        refresh_runtime_handles(reinterpret_cast<void*>(actor_address));
        return true;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool CallActorProgressionRefreshSafe(
    uintptr_t refresh_address,
    uintptr_t actor_address,
    DWORD* exception_code) {
    auto* refresh_progression = reinterpret_cast<ActorProgressionRefreshFn>(refresh_address);
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (refresh_progression == nullptr || actor_address == 0) {
        return false;
    }

    __try {
        auto& memory = ProcessMemory::Instance();
        const auto progression_handle =
            memory.ReadFieldOr<uintptr_t>(actor_address, kActorProgressionHandleOffset, 0);
        const auto progression_runtime =
            progression_handle != 0 ? ReadSmartPointerInnerObject(progression_handle) : 0;
        if (progression_runtime == 0) {
            return false;
        }

        refresh_progression(reinterpret_cast<void*>(progression_runtime));
        return true;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool CallPlayerAppearanceApplyChoiceSafe(
    uintptr_t apply_choice_address,
    uintptr_t progression_address,
    int choice_id,
    int ensure_assets,
    DWORD* exception_code) {
    auto* apply_choice = reinterpret_cast<PlayerAppearanceApplyChoiceFn>(apply_choice_address);
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (apply_choice == nullptr || progression_address == 0 || choice_id < 0) {
        return false;
    }

    __try {
        apply_choice(reinterpret_cast<void*>(progression_address), choice_id, ensure_assets);
        return true;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool CallGameplayActorAttachSafe(
    uintptr_t gameplay_address,
    uintptr_t actor_address,
    DWORD* exception_code) {
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (gameplay_address == 0 || actor_address == 0) {
        return false;
    }

    __try {
        const auto subobject_address = gameplay_address + kGameplayActorAttachSubobjectOffset;
        const auto vtable = *reinterpret_cast<uintptr_t*>(subobject_address);
        if (vtable == 0) {
            return false;
        }

        const auto attach_address = *reinterpret_cast<uintptr_t*>(vtable + 0x10);
        if (attach_address == 0) {
            return false;
        }

        auto* attach_actor = reinterpret_cast<GameplayActorAttachFn>(attach_address);
        attach_actor(reinterpret_cast<void*>(subobject_address), reinterpret_cast<void*>(actor_address));
        return true;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool CallActorBuildRenderDescriptorFromSourceSafe(
    uintptr_t build_address,
    uintptr_t actor_address,
    DWORD* exception_code) {
    auto* build_descriptor = reinterpret_cast<ActorBuildRenderDescriptorFromSourceFn>(build_address);
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (build_descriptor == nullptr || actor_address == 0) {
        return false;
    }

    __try {
        build_descriptor(reinterpret_cast<void*>(actor_address));
        return true;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool CallWizardCloneFromSourceActorSafe(
    uintptr_t clone_address,
    uintptr_t source_actor_address,
    uintptr_t* clone_actor_address,
    DWORD* exception_code) {
    if (clone_actor_address != nullptr) {
        *clone_actor_address = 0;
    }
    if (exception_code != nullptr) {
        *exception_code = 0;
    }

    auto* clone_from_source = reinterpret_cast<WizardCloneFromSourceActorFn>(clone_address);
    if (clone_from_source == nullptr || source_actor_address == 0) {
        return false;
    }

    __try {
        auto* clone_actor = clone_from_source(reinterpret_cast<void*>(source_actor_address));
        if (clone_actor_address != nullptr) {
            *clone_actor_address = reinterpret_cast<uintptr_t>(clone_actor);
        }
        return clone_actor != nullptr;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool CallStandaloneWizardVisualLinkAttachSafe(
    uintptr_t attach_address,
    uintptr_t self_address,
    uintptr_t value_address,
    DWORD* exception_code) {
    auto* attach = reinterpret_cast<StandaloneWizardVisualLinkAttachFn>(attach_address);
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (attach == nullptr || self_address == 0) {
        return false;
    }

    __try {
        return attach(reinterpret_cast<void*>(self_address), reinterpret_cast<void*>(value_address)) != 0;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool CallActorWorldRegisterGameplaySlotActorSafe(
    uintptr_t register_address,
    uintptr_t world_address,
    int slot_index,
    DWORD* exception_code) {
    auto* register_slot_actor =
        reinterpret_cast<ActorWorldRegisterGameplaySlotActorFn>(register_address);
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (register_slot_actor == nullptr || world_address == 0 || slot_index < 0) {
        return false;
    }

    __try {
        register_slot_actor(reinterpret_cast<void*>(world_address), slot_index);
        return true;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool CallPlayerActorMoveStepSafe(
    uintptr_t move_step_address,
    uintptr_t owner_address,
    uintptr_t actor_address,
    float move_x,
    float move_y,
    int flags,
    DWORD* exception_code) {
    auto* move_step = reinterpret_cast<PlayerActorMoveStepFn>(move_step_address);
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (move_step == nullptr || owner_address == 0 || actor_address == 0) {
        return false;
    }

    __try {
        move_step(reinterpret_cast<void*>(owner_address), reinterpret_cast<void*>(actor_address), move_x, move_y, flags);
        return true;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool CallActorMoveByDeltaSafe(
    uintptr_t move_by_delta_address,
    uintptr_t actor_address,
    float move_x,
    float move_y,
    DWORD* exception_code) {
    auto* move_by_delta = reinterpret_cast<ActorMoveByDeltaFn>(move_by_delta_address);
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (move_by_delta == nullptr || actor_address == 0) {
        return false;
    }

    __try {
        move_by_delta(reinterpret_cast<void*>(actor_address), move_x, move_y, 0);
        return true;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool CallActorWorldUnregisterSafe(
    uintptr_t actor_world_unregister_address,
    uintptr_t world_address,
    uintptr_t actor_address,
    char remove_from_container,
    DWORD* exception_code) {
    auto* actor_world_unregister = reinterpret_cast<ActorWorldUnregisterFn>(actor_world_unregister_address);
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (actor_world_unregister == nullptr || world_address == 0 || actor_address == 0) {
        return false;
    }

    __try {
        actor_world_unregister(
            reinterpret_cast<void*>(world_address),
            reinterpret_cast<void*>(actor_address),
            remove_from_container);
        return true;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool CallActorWorldUnregisterGameplaySlotActorSafe(
    uintptr_t unregister_address,
    uintptr_t world_address,
    int slot_index,
    DWORD* exception_code) {
    auto* unregister_slot_actor =
        reinterpret_cast<ActorWorldUnregisterGameplaySlotActorFn>(unregister_address);
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (unregister_slot_actor == nullptr || world_address == 0 || slot_index < 0) {
        return false;
    }

    __try {
        unregister_slot_actor(reinterpret_cast<void*>(world_address), slot_index);
        return true;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool CallScalarDeletingDestructorSafe(
    uintptr_t object_address,
    int flags,
    DWORD* exception_code) {
    if (exception_code != nullptr) {
        *exception_code = 0;
    }
    if (object_address == 0) {
        return true;
    }

    __try {
        const auto vtable = *reinterpret_cast<uintptr_t*>(object_address);
        if (vtable == 0) {
            return false;
        }

        const auto destructor_address = *reinterpret_cast<uintptr_t*>(vtable);
        if (destructor_address == 0) {
            return false;
        }

        auto* destructor = reinterpret_cast<ScalarDeletingDestructorFn>(destructor_address);
        destructor(reinterpret_cast<void*>(object_address), flags);
        return true;
    } __except (CaptureSehCode(GetExceptionInformation(), exception_code)) {
        return false;
    }
}

bool CallScalarDeletingDestructorDetailedSafe(
    uintptr_t object_address,
    int flags,
    SehExceptionDetails* exception_details) {
    if (exception_details != nullptr) {
        *exception_details = {};
    }
    if (object_address == 0) {
        return true;
    }

    __try {
        const auto vtable = *reinterpret_cast<uintptr_t*>(object_address);
        if (vtable == 0) {
            return false;
        }

        const auto destructor_address = *reinterpret_cast<uintptr_t*>(vtable);
        if (destructor_address == 0) {
            return false;
        }

        auto* destructor = reinterpret_cast<ScalarDeletingDestructorFn>(destructor_address);
        destructor(reinterpret_cast<void*>(object_address), flags);
        return true;
    } __except (CaptureSehDetails(GetExceptionInformation(), exception_details)) {
        return false;
    }
}

float ReadResolvedGameFloatOr(uintptr_t absolute_address, float fallback) {
    auto& memory = ProcessMemory::Instance();
    const auto resolved_address = memory.ResolveGameAddressOrZero(absolute_address);
    if (resolved_address == 0) {
        return fallback;
    }

    return memory.ReadValueOr<float>(resolved_address, fallback);
}

void StopWizardBotActorMotion(uintptr_t actor_address) {
    if (actor_address == 0) {
        return;
    }

    BotEntityBinding* binding = nullptr;
    {
        std::lock_guard<std::recursive_mutex> lock(g_bot_entities_mutex);
        binding = FindBotEntityForActor(actor_address);
    }

    if (binding != nullptr && binding->kind == BotEntityBinding::Kind::StandaloneWizard) {
        ApplyObservedBotAnimationState(binding, actor_address, false);
        return;
    }

    ApplyActorAnimationDriveState(actor_address, false);
}

void ApplyObservedBotAnimationState(BotEntityBinding* binding, uintptr_t actor_address, bool moving) {
    if (binding == nullptr || actor_address == 0 || binding->kind != BotEntityBinding::Kind::StandaloneWizard) {
        return;
    }

    ApplyStandaloneWizardAnimationDriveProfile(binding, actor_address, moving);
    ApplyStandaloneWizardPuppetDriveState(actor_address, moving);

    const auto desired_state_id = ResolveStandaloneWizardSelectionState(binding->wizard_id);
    if (TryWriteActorAnimationStateIdDirect(actor_address, desired_state_id)) {
        binding->last_applied_animation_state_id = desired_state_id;
        return;
    }

    binding->last_applied_animation_state_id = ResolveActorAnimationStateId(actor_address);
}

void LogWizardBotMovementFrame(
    BotEntityBinding* binding,
    uintptr_t actor_address,
    uintptr_t owner_address,
    uintptr_t movement_controller_address,
    float direction_x,
    float direction_y,
    float velocity_x,
    float velocity_y,
    float position_before_x,
    float position_before_y,
    float position_after_x,
    float position_after_y,
    const char* path_label) {
    (void)binding;
    (void)actor_address;
    (void)owner_address;
    (void)movement_controller_address;
    (void)direction_x;
    (void)direction_y;
    (void)velocity_x;
    (void)velocity_y;
    (void)position_before_x;
    (void)position_before_y;
    (void)position_after_x;
    (void)position_after_y;
    (void)path_label;
}

void LogLocalPlayerAnimationProbe() {
    uintptr_t gameplay_address = 0;
    uintptr_t actor_address = 0;
    if (!TryResolveCurrentGameplayScene(&gameplay_address) || gameplay_address == 0 ||
        !TryResolvePlayerActorForSlot(gameplay_address, 0, &actor_address) ||
        actor_address == 0) {
        return;
    }

    auto& memory = ProcessMemory::Instance();
    const auto animation_drive_state =
        memory.ReadFieldOr<std::uint8_t>(actor_address, kActorAnimationDriveStateByteOffset, 0);
    CaptureObservedPlayerAnimationDriveProfile(actor_address, animation_drive_state != 0);
}

bool ApplyWizardBotMovementStep(BotEntityBinding* binding, std::string* error_message) {
    if (binding == nullptr || binding->actor_address == 0) {
        if (error_message != nullptr) {
            *error_message = "Bot actor is not materialized.";
        }
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const auto actor_address = binding->actor_address;
    if (binding->kind == BotEntityBinding::Kind::StandaloneWizard) {
        (void)EnsureStandaloneWizardWorldOwner(
            actor_address,
            binding->materialized_world_address,
            "movement_step",
            nullptr);
    }
    const auto magnitude = std::sqrt(
        binding->direction_x * binding->direction_x + binding->direction_y * binding->direction_y);
    if (!binding->movement_active || magnitude <= 0.0001f) {
        ApplyObservedBotAnimationState(binding, actor_address, false);
        StopWizardBotActorMotion(binding->actor_address);
        PublishWizardBotGameplaySnapshot(*binding);
        return true;
    }

    float direction_x = binding->direction_x / magnitude;
    float direction_y = binding->direction_y / magnitude;

    const auto position_before_x = memory.ReadFieldOr<float>(actor_address, kActorPositionXOffset, 0.0f);
    const auto position_before_y = memory.ReadFieldOr<float>(actor_address, kActorPositionYOffset, 0.0f);
    const auto speed_scalar = ReadResolvedGameFloatOr(kMovementSpeedScalarGlobal, 1.0f);
    const auto speed_scale_a = memory.ReadFieldOr<float>(actor_address, kActorMoveSpeedScaleOffset, 1.0f);
    const auto speed_scale_b =
        memory.ReadFieldOr<float>(actor_address, kActorMovementSpeedMultiplierOffset, 1.0f);
    auto move_step_scale = memory.ReadFieldOr<float>(actor_address, kActorMoveStepScaleOffset, 1.0f);
    const auto progression_address =
        binding->kind == BotEntityBinding::Kind::StandaloneWizard
            ? static_cast<uintptr_t>(0)
            : memory.ReadFieldOr<uintptr_t>(actor_address, kActorProgressionRuntimeStateOffset, 0);
    const auto progression_speed =
        progression_address != 0
            ? memory.ReadFieldOr<float>(progression_address, kProgressionMoveSpeedOffset, 1.0f)
            : 1.0f;

    if (!std::isfinite(move_step_scale) || std::fabs(move_step_scale) <= 0.0001f) {
        move_step_scale = 1.0f;
    }

    auto movement_speed = progression_speed * speed_scale_a * speed_scale_b * speed_scalar;
    if (!std::isfinite(movement_speed) || std::fabs(movement_speed) <= 0.0001f) {
        movement_speed = 1.0f;
    }

    const auto velocity_x = movement_speed * direction_x;
    const auto velocity_y = movement_speed * direction_y;
    ApplyObservedBotAnimationState(binding, actor_address, true);

    const auto owner_address =
        binding->kind == BotEntityBinding::Kind::StandaloneWizard
            ? static_cast<uintptr_t>(0)
            : memory.ReadFieldOr<uintptr_t>(actor_address, kActorOwnerOffset, 0);
    const auto movement_controller_address =
        binding->kind == BotEntityBinding::Kind::StandaloneWizard || owner_address == 0
            ? static_cast<uintptr_t>(0)
            : owner_address + kActorOwnerMovementControllerOffset;
    const auto move_step_address =
        ProcessMemory::Instance().ResolveGameAddressOrZero(kPlayerActorMoveStep);
    const auto move_by_delta_address =
        ProcessMemory::Instance().ResolveGameAddressOrZero(kActorMoveByDelta);
    auto move_step_x = velocity_x * move_step_scale;
    auto move_step_y = velocity_y * move_step_scale;
    if ((binding->kind == BotEntityBinding::Kind::PlaceholderEnemy ||
         binding->kind == BotEntityBinding::Kind::StandaloneWizard) &&
        std::fabs(move_step_x) <= 0.0001f &&
        std::fabs(move_step_y) <= 0.0001f) {
        move_step_x = direction_x;
        move_step_y = direction_y;
    }
    DWORD exception_code = 0;
    bool player_step_succeeded = false;
    float player_step_after_x = position_before_x;
    float player_step_after_y = position_before_y;
    const char* player_step_path_label = nullptr;
    struct MoveStepAttempt {
        uintptr_t self_address = 0;
        const char* path_label = nullptr;
    };
    const MoveStepAttempt move_step_attempts[] = {
        {owner_address, "player_step_owner"},
        {movement_controller_address, "player_step_controller"},
    };
    for (const auto& attempt : move_step_attempts) {
        if (attempt.self_address == 0 || move_step_address == 0) {
            continue;
        }
        if (player_step_path_label != nullptr && attempt.self_address == owner_address) {
            continue;
        }
        if (owner_address != 0 &&
            movement_controller_address != 0 &&
            movement_controller_address == owner_address &&
            attempt.self_address == movement_controller_address &&
            player_step_path_label != nullptr) {
            continue;
        }

        DWORD attempt_exception_code = 0;
        if (!CallPlayerActorMoveStepSafe(
                move_step_address,
                attempt.self_address,
                actor_address,
                move_step_x,
                move_step_y,
                0,
                &attempt_exception_code)) {
            if (exception_code == 0 && attempt_exception_code != 0) {
                exception_code = attempt_exception_code;
            }
            continue;
        }

        player_step_succeeded = true;
        player_step_path_label = attempt.path_label;
        player_step_after_x = memory.ReadFieldOr<float>(actor_address, kActorPositionXOffset, 0.0f);
        player_step_after_y = memory.ReadFieldOr<float>(actor_address, kActorPositionYOffset, 0.0f);
        const auto player_step_delta_x = player_step_after_x - position_before_x;
        const auto player_step_delta_y = player_step_after_y - position_before_y;
        if (std::fabs(player_step_delta_x) > 0.001f || std::fabs(player_step_delta_y) > 0.001f) {
            LogWizardBotMovementFrame(
                binding,
                actor_address,
                owner_address,
                movement_controller_address,
                direction_x,
                direction_y,
                velocity_x,
                velocity_y,
                position_before_x,
                position_before_y,
                player_step_after_x,
                player_step_after_y,
                attempt.path_label);
            PublishWizardBotGameplaySnapshot(*binding);
            return true;
        }
    }

    if ((binding->kind == BotEntityBinding::Kind::PlaceholderEnemy ||
         binding->kind == BotEntityBinding::Kind::StandaloneWizard) &&
        move_by_delta_address != 0 &&
        CallActorMoveByDeltaSafe(
            move_by_delta_address,
            actor_address,
            move_step_x,
            move_step_y,
            &exception_code)) {
        const auto position_after_x = memory.ReadFieldOr<float>(actor_address, kActorPositionXOffset, 0.0f);
        const auto position_after_y = memory.ReadFieldOr<float>(actor_address, kActorPositionYOffset, 0.0f);
        const std::string fallback_path_label =
            player_step_succeeded && player_step_path_label != nullptr
                ? std::string(player_step_path_label) + "_plus_actor_delta"
                : "actor_delta";
        LogWizardBotMovementFrame(
            binding,
            actor_address,
            owner_address,
            movement_controller_address,
            direction_x,
            direction_y,
            velocity_x,
            velocity_y,
            player_step_succeeded ? player_step_after_x : position_before_x,
            player_step_succeeded ? player_step_after_y : position_before_y,
            position_after_x,
            position_after_y,
            fallback_path_label.c_str());
        PublishWizardBotGameplaySnapshot(*binding);
        return true;
    }

    if (exception_code != 0 && error_message != nullptr) {
        *error_message = "PlayerActor_MoveStep threw 0x" + HexString(exception_code) + ".";
    }

    PublishWizardBotGameplaySnapshot(*binding);
    return true;
}

void SyncWizardBotMovementIntent(BotEntityBinding* binding) {
    if (binding == nullptr || binding->bot_id == 0) {
        return;
    }

    multiplayer::BotMovementIntentSnapshot intent;
    if (!multiplayer::ReadBotMovementIntent(binding->bot_id, &intent) || !intent.available) {
        return;
    }

    binding->controller_state = intent.state;
    binding->movement_active = intent.moving;
    binding->has_target = intent.has_target;
    binding->direction_x = intent.direction_x;
    binding->direction_y = intent.direction_y;
    binding->desired_heading_valid = intent.desired_heading_valid;
    binding->desired_heading = intent.desired_heading;
    binding->target_x = intent.target_x;
    binding->target_y = intent.target_y;
    binding->distance_to_target = intent.distance_to_target;
}

void TickWizardBotMovementControllers(uintptr_t gameplay_address, std::uint64_t now_ms) {
    SceneContextSnapshot scene_context;
    const bool have_scene_context = TryBuildSceneContextSnapshot(gameplay_address, &scene_context);
    std::vector<BotRematerializationRequest> rematerialization_requests;
    std::vector<std::uint64_t> dematerialize_requests;
    std::vector<PendingWizardBotSyncRequest> materialize_requests;
    {
        std::lock_guard<std::recursive_mutex> lock(g_bot_entities_mutex);
        for (auto& binding : g_bot_entities) {
            SyncWizardBotMovementIntent(&binding);
            const bool should_be_materialized =
                have_scene_context && ShouldBotBeMaterializedInScene(binding, scene_context);
            if (binding.actor_address == 0) {
                if (should_be_materialized && now_ms >= binding.next_scene_materialize_retry_ms) {
                    multiplayer::BotSnapshot bot_snapshot;
                    if (multiplayer::ReadBotSnapshot(binding.bot_id, &bot_snapshot) && bot_snapshot.available) {
                        PendingWizardBotSyncRequest sync_request;
                        sync_request.bot_id = binding.bot_id;
                        sync_request.wizard_id = bot_snapshot.wizard_id;
                        sync_request.has_transform = bot_snapshot.transform_valid;
                        sync_request.has_heading = bot_snapshot.transform_valid;
                        sync_request.x = bot_snapshot.position_x;
                        sync_request.y = bot_snapshot.position_y;
                        sync_request.heading = bot_snapshot.heading;
                        materialize_requests.push_back(sync_request);
                        binding.next_scene_materialize_retry_ms = now_ms + kWizardBotSyncRetryDelayMs;
                    }
                }
                PublishWizardBotGameplaySnapshot(binding);
                continue;
            }

            if (have_scene_context && HasBotMaterializedSceneChanged(binding, scene_context)) {
                if (should_be_materialized) {
                    BotRematerializationRequest rematerialization_request;
                    if (TryBuildBotRematerializationRequest(gameplay_address, binding, &rematerialization_request)) {
                        rematerialization_requests.push_back(rematerialization_request);
                    }
                } else {
                    dematerialize_requests.push_back(binding.bot_id);
                }
                continue;
            }

            std::string error_message;
            if (!ApplyWizardBotMovementStep(&binding, &error_message) && !error_message.empty()) {
                Log(
                    "[bots] movement step failed. bot_id=" + std::to_string(binding.bot_id) +
                    " actor=" + HexString(binding.actor_address) +
                    " error=" + error_message);
            }
            PublishWizardBotGameplaySnapshot(binding);
        }
    }

    for (const auto bot_id : dematerialize_requests) {
        DematerializeWizardBotEntityNow(bot_id, false, "scene mismatch");
    }

    for (const auto& rematerialization_request : rematerialization_requests) {
        QueueBotRematerialization(rematerialization_request);
    }

    for (const auto& sync_request : materialize_requests) {
        std::string error_message;
        if (!QueueWizardBotEntitySync(
                sync_request.bot_id,
                sync_request.wizard_id,
                sync_request.has_transform,
                sync_request.has_heading,
                sync_request.x,
                sync_request.y,
                sync_request.heading,
                &error_message)) {
            Log(
                "[bots] queued scene materialize failed. bot_id=" + std::to_string(sync_request.bot_id) +
                " wizard_id=" + std::to_string(sync_request.wizard_id) +
                " error=" + error_message);
        }
    }
}

void TickWizardBotMovementControllersIfActive() {
    if (!g_gameplay_keyboard_injection.initialized) {
        return;
    }

    uintptr_t gameplay_address = 0;
    if (!TryResolveCurrentGameplayScene(&gameplay_address) || gameplay_address == 0) {
        return;
    }

    std::lock_guard<std::recursive_mutex> pump_lock(g_gameplay_action_pump_mutex);
    TickWizardBotMovementControllers(gameplay_address, static_cast<std::uint64_t>(::GetTickCount64()));
}
