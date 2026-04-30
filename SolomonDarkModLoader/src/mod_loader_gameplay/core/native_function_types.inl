using GameplayKeyboardEdgeFn = std::uint8_t(__thiscall*)(void* self, std::uint32_t scancode);
using GameplayMouseRefreshFn = void(__fastcall*)(void* self, void* unused_edx);
using PlayerActorTickFn = void(__thiscall*)(void* self);
using PlayerActorNoArgMethodFn = void(__thiscall*)(void* self);
using PlayerActorDtorFn = void(__thiscall*)(void* self, char free_flag);
using PuppetManagerDeletePuppetFn = void(__thiscall*)(void* self, void* actor);
using PointerListDeleteBatchFn = void(__thiscall*)(void* self, void* list);
using ObjectDeleteFn = void(__thiscall*)(void* self);
using GameplaySwitchRegionFn = void(__thiscall*)(void* self, int region_index);
using ArenaStartWavesFn = void(__thiscall*)(void* self);
using GameplayCombatPreludeModeFn = void(__thiscall*)(void* self, std::uint32_t arg0, std::uint32_t arg1);
using ArenaCombatPreludeDispatchFn = void(__thiscall*)(void* self, int mode);
using GameplayCreatePlayerSlotFn = void(__thiscall*)(void* self, int slot_index);
using WizardCloneFromSourceActorFn = void*(__fastcall*)(void* source_actor);
using PlayerActorCtorFn = void*(__thiscall*)(void* self);
using RawObjectCtorFn = void*(__thiscall*)(void* self);
using GameObjectAllocateFn = void*(__cdecl*)(std::size_t size);
using GameObjectFactoryFn = uintptr_t(__thiscall*)(void* self, int type_id);
using GameOperatorNewFn = void*(__cdecl*)(std::size_t size);
using ActorWorldRegisterFn = std::uint32_t(__thiscall*)(void* self, int actor_group, void* actor, int slot_index, char use_alt_list);
using ActorWorldUnregisterFn = void(__thiscall*)(void* self, void* actor, char remove_from_container);
using ActorWorldRegisterGameplaySlotActorFn = void(__thiscall*)(void* self, int slot_index);
using ActorWorldUnregisterGameplaySlotActorFn = void(__thiscall*)(void* self, int slot_index);
using WorldCellGridRebindActorFn = void(__thiscall*)(void* self, void* actor);
using MonsterPathfindingRefreshTargetFn = void(__fastcall*)(void* self, void* unused_edx);
using PlayerActorMoveStepFn = std::uint32_t(__thiscall*)(void* self, void* actor, float move_x, float move_y, unsigned int flags);
using SpellCastDispatcherFn = void(__thiscall*)(void* actor);
using PurePrimarySpellStartFn = void(__thiscall*)(void* actor);
using CastActiveHandleCleanupFn = void(__thiscall*)(void* actor);
using NativeTwoFloatGetterFn = float(__thiscall*)(void* self, float x, float y);
using ActorGetProfileFn = void*(__thiscall*)(void* self);
using ProfileResolveStatEntryFn = void*(__thiscall*)(void* self, int stat_index);
using StatBookComputeValueFn = float(__thiscall*)(void* self, float base_value, int entry_idx, char apply_modifier);
using MovementCollisionTestCirclePlacementFn = std::uint32_t(__thiscall*)(void* self, float x, float y, float radius, std::uint32_t mask);
using MovementCollisionTestCirclePlacementExtendedFn =
    std::uint32_t(__thiscall*)(
        void* self,
        float x,
        float y,
        float radius,
        std::uint32_t circle_block_mask,
        std::uint32_t overlap_allow_mask);
using ActorMoveByDeltaFn = void(__thiscall*)(void* self, float move_x, float move_y, int flags);
using ActorAnimationAdvanceFn = void(__thiscall*)(void* self);
using PlayerActorRefreshRuntimeHandlesFn = void(__thiscall*)(void* self);
using ActorProgressionRefreshFn = void(__thiscall*)(void* self);
using PlayerAppearanceApplyChoiceFn = void(__thiscall*)(void* progression, int choice_id, int ensure_assets);
using SkillsWizardBuildPrimarySpellFn = void(__thiscall*)(
    void* self,
    std::uint32_t primary_entry,
    std::uint32_t combo_entry,
    std::uint32_t reserved0,
    std::uint32_t reserved1,
    std::uint32_t reserved2,
    std::uint32_t reserved3);
using GameNpcSetMoveGoalFn = void(__thiscall*)(void* self, std::uint8_t mode, int follow_flag, float x, float y, float extra_scalar);
using GameNpcSetTrackedSlotAssistFn = void(__thiscall*)(void* self, int slot_index, int require_callback);
using EquipAttachmentSinkGetCurrentItemFn = int(__fastcall*)(int sink);
using SpellActionBuilderFn = void(__thiscall*)(void* self, int mode, int arg2);
using SpellBuilderResetFn = void(__cdecl*)();
using SpellBuilderFinalizeFn = void(__cdecl*)();
using GameplayActorAttachFn = void(__thiscall*)(void* self, void* actor);
using StandaloneWizardVisualLinkAttachFn = std::uint8_t(__thiscall*)(void* self, void* value);
using ActorBuildRenderDescriptorFromSourceFn = void(__thiscall*)(void* self);
using ScalarDeletingDestructorFn = void(__thiscall*)(void* self, int flags);
using SpawnRewardGoldFn = void(__thiscall*)(void* self, std::uint32_t x_bits, std::uint32_t y_bits, int amount, int lifetime);
using EnemyConfigCtorFn = void(__thiscall*)(void* self);
using EnemyConfigDtorFn = void(__thiscall*)(void* self);
using EnemyConfigBuildFn = void(__thiscall*)(void* self, int type_id, int variant, void* config_buffer, void* modifier_list);
using EnemySpawnFn =
    void* (__thiscall*)(void* self, void* spawn_anchor, void* enemy_config, int spawn_mode, int param_5, int param_6, char allow_override);
using GameFreeFn = void(__cdecl*)(void* memory);
using GameplayHudRenderDispatchFn = void(__thiscall*)(void* self, int render_case);

struct NativeGameString {
    uintptr_t vtable = 0;
    char* text = nullptr;
    std::uint32_t unknown_08 = 0;
    std::int32_t* ref_count = nullptr;
    std::uint32_t length = 0;
    std::uint8_t flags_14 = 0;
    std::uint8_t flags_15 = 0;
    std::uint16_t padding_16 = 0;
    std::uint32_t unknown_18 = 0;
};
static_assert(sizeof(NativeGameString) == 0x1C, "Native game string layout changed");

using NativeStringAssignFn = void(__thiscall*)(void* self, char* text);
using NativeExactTextObjectRenderFn = void(__thiscall*)(void* self, NativeGameString text, float x, float y);
