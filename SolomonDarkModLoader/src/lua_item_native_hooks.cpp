#include "lua_item_runtime.h"

#include "gameplay_seams.h"
#include "logger.h"
#include "memory_access.h"
#include "mod_loader.h"
#include "multiplayer_local_transport.h"
#include "x86_hook.h"

#include <array>
#include <cstddef>
#include <cstdint>
#include <limits>
#include <string>
#include <utility>

namespace sdmod {
namespace {

constexpr std::size_t kNativeSpriteSize = 0xC4;
constexpr std::size_t kNativeSpriteActiveOffset = 0x04;
constexpr std::size_t kNativeSpriteGeometryOffset = 0x2C;
constexpr std::size_t kNativeSpriteGeometryEndOffset = 0xA4;
constexpr std::size_t kNativeSpriteGeometryBytes =
    kNativeSpriteGeometryEndOffset - kNativeSpriteGeometryOffset;
constexpr std::size_t kInventorySpriteListOffset = 0xE64;
constexpr std::size_t kInventorySpriteCountOffset = 0xE68;
constexpr std::size_t kWorldSpriteListOffset = 0x489C;
constexpr std::size_t kWorldSpriteCountOffset = 0x48A0;
constexpr std::int32_t kMaximumPlausibleNativeSpriteCount = 4096;
constexpr std::size_t kSpriteDrawHookPatchSize = 6;
constexpr std::size_t kInventoryUseHookPatchSize = 7;
constexpr std::size_t kItemTextHookPatchSize = 7;
constexpr std::uint32_t kPotionItemTypeId = 0x1B59;

using SpriteDrawAtPositionFn =
    void(__thiscall*)(void* sprite, float x, float y, float z);
using SpriteDrawTransformedFn =
    void(__thiscall*)(void* sprite, const float* transform);
using InventoryUseItemFn =
    uintptr_t(__thiscall*)(void* inventory_root, std::uint32_t item_uid);
using InventoryFindItemByUidFn =
    void*(__thiscall*)(void* inventory_root, std::uint32_t item_uid);
using ItemTextFn =
    void*(__thiscall*)(void* item, void* output_string);
using NativeStringAssignFn =
    void(__thiscall*)(void* output_string, char* text);

struct NativeCustomPotionSprite {
    LuaConsumableDefinition definition;
    uintptr_t stock_health_sprite = 0;
};

X86Hook g_sprite_draw_at_position_hook;
X86Hook g_sprite_draw_transformed_hook;
X86Hook g_inventory_use_item_hook;
X86Hook g_item_display_name_hook;
X86Hook g_potion_help_hook;
thread_local uintptr_t g_seeded_custom_sprite = 0;

std::optional<LuaConsumableDefinition>
TryFindCustomPotionDefinition(uintptr_t item_address) {
    if (item_address == 0 ||
        kGameObjectTypeIdOffset == 0 ||
        kItemSlotOffset == 0) {
        return std::nullopt;
    }
    auto& memory = ProcessMemory::Instance();
    std::uint32_t type_id = 0;
    std::int32_t subtype = -1;
    if (!memory.TryReadField(
            item_address,
            kGameObjectTypeIdOffset,
            &type_id) ||
        type_id != kPotionItemTypeId ||
        !memory.TryReadField(
            item_address,
            kItemSlotOffset,
            &subtype)) {
        return std::nullopt;
    }
    return FindLuaConsumableDefinitionByNativeSubtype(subtype);
}

bool TryMatchSpriteList(
    uintptr_t sprite_address,
    uintptr_t bundle_global,
    std::size_t list_offset,
    std::size_t count_offset,
    NativeCustomPotionSprite* match) {
    if (sprite_address == 0 || bundle_global == 0 || match == nullptr) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const auto resolved_global =
        memory.ResolveGameAddressOrZero(bundle_global);
    uintptr_t bundle = 0;
    uintptr_t sprites = 0;
    std::int32_t count = 0;
    if (resolved_global == 0 ||
        !memory.TryReadValue(resolved_global, &bundle) ||
        bundle == 0 ||
        !memory.TryReadField(bundle, list_offset, &sprites) ||
        !memory.TryReadField(bundle, count_offset, &count) ||
        sprites == 0 ||
        count <= kLuaFirstConsumablePotionSubtype ||
        count > kMaximumPlausibleNativeSpriteCount ||
        sprite_address < sprites) {
        return false;
    }

    const auto byte_offset = sprite_address - sprites;
    if (byte_offset % kNativeSpriteSize != 0) {
        return false;
    }
    const auto raw_subtype = byte_offset / kNativeSpriteSize;
    if (raw_subtype >= static_cast<std::size_t>(count) ||
        raw_subtype >
            static_cast<std::size_t>((std::numeric_limits<std::int32_t>::max)())) {
        return false;
    }
    const auto definition = FindLuaConsumableDefinitionByNativeSubtype(
        static_cast<std::int32_t>(raw_subtype));
    if (!definition.has_value()) {
        return false;
    }

    match->definition = *definition;
    match->stock_health_sprite = sprites;
    return true;
}

bool TryMatchCustomPotionSprite(
    uintptr_t sprite_address,
    NativeCustomPotionSprite* match) {
    return TryMatchSpriteList(
               sprite_address,
               kInventorySpriteBundleGlobal,
               kInventorySpriteListOffset,
               kInventorySpriteCountOffset,
               match) ||
        TryMatchSpriteList(
               sprite_address,
               kWorldSpriteBundleGlobal,
               kWorldSpriteListOffset,
               kWorldSpriteCountOffset,
               match);
}

bool SeedStockPotionGeometry(
    uintptr_t custom_sprite,
    uintptr_t stock_health_sprite) {
    std::uint8_t active = 0;
    std::array<std::uint8_t, kNativeSpriteGeometryBytes> geometry{};
    auto& memory = ProcessMemory::Instance();
    return memory.TryReadField(
               stock_health_sprite,
               kNativeSpriteActiveOffset,
               &active) &&
        memory.TryRead(
            stock_health_sprite + kNativeSpriteGeometryOffset,
            geometry.data(),
            geometry.size()) &&
        memory.TryWriteField(
            custom_sprite,
            kNativeSpriteActiveOffset,
            active) &&
        memory.TryWrite(
            custom_sprite + kNativeSpriteGeometryOffset,
            geometry.data(),
            geometry.size());
}

bool BuildCustomPotionQuad(
    const NativeCustomPotionSprite& match,
    const float* transform,
    LuaConsumableRenderQuad* quad) {
    if (transform == nullptr || quad == nullptr) {
        return false;
    }

    std::array<float, 8> local_vertices{};
    std::array<float, 16> matrix{};
    auto& memory = ProcessMemory::Instance();
    if (!memory.TryRead(
            match.stock_health_sprite + kNativeSpriteGeometryOffset,
            local_vertices.data(),
            sizeof(local_vertices)) ||
        !memory.TryRead(
            reinterpret_cast<uintptr_t>(transform),
            matrix.data(),
            sizeof(matrix))) {
        return false;
    }

    quad->content_id = match.definition.content_id;
    quad->icon_atlas = match.definition.icon_atlas;
    quad->icon_frame = match.definition.icon_frame;
    for (std::size_t index = 0; index < 4; ++index) {
        const float x = local_vertices[index * 2];
        const float y = local_vertices[index * 2 + 1];
        quad->vertices[index * 2] =
            x * matrix[0] + y * matrix[4] + matrix[12];
        quad->vertices[index * 2 + 1] =
            x * matrix[1] + y * matrix[5] + matrix[13];
    }
    return true;
}

void __fastcall HookSpriteDrawAtPosition(
    void* self,
    void* /*unused_edx*/,
    float x,
    float y,
    float z) {
    const auto original = GetX86HookTrampoline<SpriteDrawAtPositionFn>(
        g_sprite_draw_at_position_hook);
    if (original == nullptr) {
        return;
    }

    NativeCustomPotionSprite match;
    const auto sprite_address = reinterpret_cast<uintptr_t>(self);
    const bool seeded =
        TryMatchCustomPotionSprite(sprite_address, &match) &&
        SeedStockPotionGeometry(
            sprite_address,
            match.stock_health_sprite);
    g_seeded_custom_sprite = seeded ? sprite_address : 0;
    original(self, x, y, z);
    g_seeded_custom_sprite = 0;
}

void __fastcall HookSpriteDrawTransformed(
    void* self,
    void* /*unused_edx*/,
    const float* transform) {
    const auto original = GetX86HookTrampoline<SpriteDrawTransformedFn>(
        g_sprite_draw_transformed_hook);
    if (original == nullptr) {
        return;
    }

    const auto sprite_address = reinterpret_cast<uintptr_t>(self);
    NativeCustomPotionSprite match;
    LuaConsumableRenderQuad quad;
    if (sprite_address == g_seeded_custom_sprite &&
        TryMatchCustomPotionSprite(sprite_address, &match)) {
        if (BuildCustomPotionQuad(match, transform, &quad)) {
            (void)QueueLuaConsumableRenderQuad(std::move(quad));
        }
        return;
    }
    original(self, transform);
}

void AssignCustomPotionText(
    void* output_string,
    const std::string& text) {
    const auto assign_address =
        ProcessMemory::Instance().ResolveGameAddressOrZero(
            kGameplayStringAssign);
    if (output_string == nullptr ||
        assign_address == 0 ||
        text.empty()) {
        return;
    }
    auto* assign =
        reinterpret_cast<NativeStringAssignFn>(assign_address);
    assign(
        output_string,
        const_cast<char*>(text.c_str()));
}

void* __fastcall HookItemDisplayName(
    void* self,
    void* /*unused_edx*/,
    void* output_string) {
    const auto original =
        GetX86HookTrampoline<ItemTextFn>(
            g_item_display_name_hook);
    if (original == nullptr) {
        return output_string;
    }
    void* result = original(self, output_string);
    const auto definition = TryFindCustomPotionDefinition(
        reinterpret_cast<uintptr_t>(self));
    if (definition.has_value()) {
        AssignCustomPotionText(
            output_string,
            definition->name);
    }
    return result;
}

void* __fastcall HookPotionHelp(
    void* self,
    void* /*unused_edx*/,
    void* output_string) {
    const auto original =
        GetX86HookTrampoline<ItemTextFn>(
            g_potion_help_hook);
    if (original == nullptr) {
        return output_string;
    }
    void* result = original(self, output_string);
    const auto definition = TryFindCustomPotionDefinition(
        reinterpret_cast<uintptr_t>(self));
    if (definition.has_value()) {
        AssignCustomPotionText(
            output_string,
            definition->description);
    }
    return result;
}

uintptr_t __fastcall HookInventoryUseItem(
    void* self,
    void* /*unused_edx*/,
    std::uint32_t item_uid) {
    const auto original =
        GetX86HookTrampoline<InventoryUseItemFn>(
            g_inventory_use_item_hook);
    if (original == nullptr) {
        return 0;
    }

    std::optional<LuaConsumableDefinition> definition;
    const auto find_address =
        ProcessMemory::Instance().ResolveGameAddressOrZero(
            kInventoryFindItemByUid);
    if (self != nullptr && find_address != 0) {
        auto* find_item =
            reinterpret_cast<InventoryFindItemByUidFn>(
                find_address);
        void* item = find_item(self, item_uid);
        definition = TryFindCustomPotionDefinition(
            reinterpret_cast<uintptr_t>(item));
    }

    const auto result = original(self, item_uid);
    if (definition.has_value()) {
        std::uint64_t use_id = 0;
        std::string error_message;
        if (!multiplayer::QueueLocalLuaConsumableUse(
                definition->content_id,
                &use_id,
                &error_message)) {
            Log(
                "lua_items: native custom potion was consumed but its Lua "
                "callback could not be queued. content_id=" +
                std::to_string(definition->content_id) +
                " error=" + error_message);
        }
    }
    return result;
}

}  // namespace

bool InitializeLuaItemNativeHooks(std::string* error_message) {
    if (error_message != nullptr) {
        error_message->clear();
    }
    if (g_sprite_draw_at_position_hook.installed &&
        g_sprite_draw_transformed_hook.installed &&
        g_inventory_use_item_hook.installed &&
        g_item_display_name_hook.installed &&
        g_potion_help_hook.installed) {
        return true;
    }
    if (error_message == nullptr) {
        return false;
    }

    auto& memory = ProcessMemory::Instance();
    const auto draw_at_position =
        memory.ResolveGameAddressOrZero(kSpriteDrawAtPosition);
    const auto draw_transformed =
        memory.ResolveGameAddressOrZero(kSpriteDrawTransformed);
    const auto inventory_use =
        memory.ResolveGameAddressOrZero(kInventoryUseItem);
    const auto item_display_name =
        memory.ResolveGameAddressOrZero(kItemDisplayName);
    const auto potion_help =
        memory.ResolveGameAddressOrZero(kPotionHelp);
    if (draw_at_position == 0 || draw_transformed == 0 ||
        inventory_use == 0 || item_display_name == 0 ||
        potion_help == 0 || kInventoryFindItemByUid == 0 ||
        kGameplayStringAssign == 0 ||
        kInventorySpriteBundleGlobal == 0 ||
        kWorldSpriteBundleGlobal == 0) {
        *error_message =
            "Lua item presentation could not resolve its sprite draw seams.";
        return false;
    }

    std::string hook_error;
    if (!InstallX86Hook(
            reinterpret_cast<void*>(draw_transformed),
            reinterpret_cast<void*>(&HookSpriteDrawTransformed),
            kSpriteDrawHookPatchSize,
            &g_sprite_draw_transformed_hook,
            &hook_error)) {
        *error_message =
            "Failed to install Lua item transformed-sprite hook: " +
            hook_error;
        return false;
    }
    if (!InstallX86Hook(
            reinterpret_cast<void*>(draw_at_position),
            reinterpret_cast<void*>(&HookSpriteDrawAtPosition),
            kSpriteDrawHookPatchSize,
            &g_sprite_draw_at_position_hook,
            &hook_error)) {
        RemoveX86Hook(&g_sprite_draw_transformed_hook);
        *error_message =
            "Failed to install Lua item positioned-sprite hook: " +
            hook_error;
        return false;
    }
    if (!InstallX86Hook(
            reinterpret_cast<void*>(item_display_name),
            reinterpret_cast<void*>(&HookItemDisplayName),
            kItemTextHookPatchSize,
            &g_item_display_name_hook,
            &hook_error)) {
        RemoveX86Hook(&g_sprite_draw_at_position_hook);
        RemoveX86Hook(&g_sprite_draw_transformed_hook);
        *error_message =
            "Failed to install Lua item display-name hook: " +
            hook_error;
        return false;
    }
    if (!InstallX86Hook(
            reinterpret_cast<void*>(potion_help),
            reinterpret_cast<void*>(&HookPotionHelp),
            kItemTextHookPatchSize,
            &g_potion_help_hook,
            &hook_error)) {
        RemoveX86Hook(&g_item_display_name_hook);
        RemoveX86Hook(&g_sprite_draw_at_position_hook);
        RemoveX86Hook(&g_sprite_draw_transformed_hook);
        *error_message =
            "Failed to install Lua potion help hook: " +
            hook_error;
        return false;
    }
    if (!InstallX86Hook(
            reinterpret_cast<void*>(inventory_use),
            reinterpret_cast<void*>(&HookInventoryUseItem),
            kInventoryUseHookPatchSize,
            &g_inventory_use_item_hook,
            &hook_error)) {
        RemoveX86Hook(&g_potion_help_hook);
        RemoveX86Hook(&g_item_display_name_hook);
        RemoveX86Hook(&g_sprite_draw_at_position_hook);
        RemoveX86Hook(&g_sprite_draw_transformed_hook);
        *error_message =
            "Failed to install Lua inventory-use hook: " +
            hook_error;
        return false;
    }

    Log(
        "Lua item native presentation hooks initialized. positioned=" +
        HexString(draw_at_position) +
        " transformed=" + HexString(draw_transformed) +
        " use=" + HexString(inventory_use) +
        " name=" + HexString(item_display_name) +
        " help=" + HexString(potion_help));
    return true;
}

void ShutdownLuaItemNativeHooks() {
    RemoveX86Hook(&g_inventory_use_item_hook);
    RemoveX86Hook(&g_potion_help_hook);
    RemoveX86Hook(&g_item_display_name_hook);
    RemoveX86Hook(&g_sprite_draw_at_position_hook);
    RemoveX86Hook(&g_sprite_draw_transformed_hook);
    g_seeded_custom_sprite = 0;
    (void)TakeLuaConsumableRenderQuads();
}

}  // namespace sdmod
