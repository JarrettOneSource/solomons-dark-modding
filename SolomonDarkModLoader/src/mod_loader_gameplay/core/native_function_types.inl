using GameplayKeyboardEdgeFn = std::uint8_t(__thiscall*)(void* self, std::uint32_t scancode);
using GameplayMouseRefreshFn = void(__fastcall*)(void* self, void* unused_edx);
using PlayerActorTickFn = void(__thiscall*)(void* self);
using PlayerActorActionManagerTickFn = void(__thiscall*)(void* self);
using PlayerActorNoArgMethodFn = void(__thiscall*)(void* self);
using PlayerActorSecondarySpellCastFn = std::uint8_t(__thiscall*)(void* self, int skill_entry_index);
using SecondaryCursorWorldProjectionFn = void*(__thiscall*)(
    void* self,
    void* output_point,
    float screen_x,
    float screen_y);
using PlayerActorMagicDamageFn = std::uint32_t(__thiscall*)(void* self);
using BadguyDamageFn = std::uint8_t(__thiscall*)(void* self);
using PoisonedModifierTickFn = void(__thiscall*)(void* self);
using WebbedModifierTickFn = void(__thiscall*)(void* self);
using DamageContextResetFn = void(__thiscall*)(void* self);
using StaffEffectResolverFn = void(__thiscall*)(void* self, std::uint32_t variant);
using NativeSpellEffectCtorFn = uintptr_t(__thiscall*)(void* self);
using PlayerActorApplyManaDeltaFn = std::uint8_t(__thiscall*)(void* self, float delta, std::uint8_t allow_prompt);
using PlayerActorDtorFn = void(__thiscall*)(void* self, char free_flag);
using PuppetManagerDeletePuppetFn = void(__thiscall*)(void* self, void* actor);
using PointerListDeleteBatchFn = void(__thiscall*)(void* self, void* list);
using ObjectDeleteFn = void(__thiscall*)(void* self);
using GameplaySwitchRegionFn = void(__thiscall*)(void* self, int region_index);
using HubServiceDispatchFn = void(__thiscall*)(void* self, void* action);
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
using ActorRequestRetirementFn = void(__thiscall*)(void* self);
using ActorWorldRegisterGameplaySlotActorFn = void(__thiscall*)(void* self, int slot_index);
using ActorWorldUnregisterGameplaySlotActorFn = void(__thiscall*)(void* self, int slot_index);
using ActorWorldLookupObjectByHandleFn = uintptr_t(__thiscall*)(void* self, void* handle);
using WorldCellGridRebindActorFn = void(__thiscall*)(void* self, void* actor);
using MonsterPathfindingRefreshTargetFn = void(__fastcall*)(void* self, void* unused_edx);
using BadguyMoveStepFn = std::uint32_t(__thiscall*)(
    void* movement_context,
    void* actor,
    float move_x,
    float move_y);
using PlayerActorMoveStepFn = std::uint32_t(__thiscall*)(void* self, void* actor, float move_x, float move_y, unsigned int flags);
using SpellCastDispatcherFn = void(__thiscall*)(void* actor);
using PurePrimarySpellStartFn = void(__thiscall*)(void* actor);
using CastActiveHandleCleanupFn = void(__thiscall*)(void* actor);
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
using ActorWorldAttachFn = void(__thiscall*)(void* self, void* actor);
using PlayerActorInitializeControlBrainFn = void(__thiscall*)(void* self);
using ActorProgressionRefreshFn = void(__thiscall*)(void* self);
using PlayerAppearanceApplyChoiceFn = void(__thiscall*)(void* progression, int choice_id, int ensure_assets);
using SkillsWizardBuildPrimarySpellFn = std::uint32_t(__thiscall*)(
    void* self,
    std::uint32_t primary_entry,
    std::uint32_t combo_entry,
    std::uint32_t reserved0,
    std::uint32_t reserved1,
    std::uint32_t reserved2,
    std::uint32_t reserved3);
using SkillsWizardGetPrimaryColorFn = void(__thiscall*)(
    void* self,
    float* out_color,
    std::uint32_t primary_entry);
using SpellActionBuilderFn = void(__thiscall*)(void* self, int mode, int arg2);
using SpellBuilderResetFn = void(__cdecl*)();
using SpellBuilderFinalizeFn = void(__cdecl*)();
using GameplayActorAttachFn = void(__thiscall*)(void* self, void* actor);
using GameplayActorDetachFn = void(__thiscall*)(void* self, void* actor);
using StandaloneWizardVisualLinkAttachFn = std::uint8_t(__thiscall*)(void* self, void* value);
using ActorBuildRenderDescriptorFromSourceFn = void(__thiscall*)(void* self);
using ScalarDeletingDestructorFn = void(__thiscall*)(void* self, int flags);
using NativeModifierApplyFn = std::uint32_t(__thiscall*)(void* self, void* actor);
using PointerListAddSmartPointerFn = void(__thiscall*)(void* self, uintptr_t control_block);
using PointerListRemoveValueFn = void(__thiscall*)(void* self, uintptr_t value);
using SpawnRewardGoldFn = void(__thiscall*)(void* self, std::uint32_t x_bits, std::uint32_t y_bits, int amount, int lifetime);
using SpawnPotionDropFn = void(__thiscall*)(void* self, std::uint32_t x_bits, std::uint32_t y_bits, int potion_slot);
using GameFreeFn = void(__cdecl*)(void* memory);
using NativeRngInitializeFn = void(__thiscall*)(void* self, std::uint32_t seed);
using OrbRewardInitializeFn = void(__thiscall*)(void* self, void* rng_state);
using GoldPickupTickFn = void(__thiscall*)(void* self);
using OrbPickupTickFn = void(__thiscall*)(void* self);
using ItemDropPickupTickFn = void(__thiscall*)(void* self);
using PowerupPickupTickFn = void(__thiscall*)(void* self);
using InventoryInsertOrStackItemFn = void(__thiscall*)(
    void* inventory_root,
    void* item,
    std::uint8_t allow_potion_stacking,
    std::uint8_t remove_placeholder);
using ItemRecipeCloneFn = void*(__cdecl*)(void* recipe);
using ItemDropCarrierResetFn = void(__thiscall*)(void* self);
// ItemDrop_PostRegister ends in RET 0x4, so it owns its single stack argument.
using ItemDropPostRegisterFn = void(__stdcall*)(void* actor);
using GameplayUiGlyphDrawFn = void(__thiscall*)(void* self, float x, float y);
// GameplayHud_RenderDispatch reads only render_case, but its stock RET 0x0C
// proves three stack arguments. Preserve all three across the detour.
using GameplayHudRenderDispatchFn = void(__thiscall*)(void* self, int render_case, uintptr_t arg1, uintptr_t arg2);

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
