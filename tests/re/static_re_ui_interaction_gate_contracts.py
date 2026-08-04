"""Static contracts for beta.32 modal UI and Courtyard authority gates."""

from __future__ import annotations

from static_re_contract_support import ROOT, StaticReTestFailure


def _read(relative_path: str) -> str:
    return (ROOT / relative_path).read_text(encoding="utf-8")


def _require(source: str, tokens: tuple[str, ...], contract: str) -> None:
    missing = [token for token in tokens if token not in source]
    if missing:
        raise StaticReTestFailure(
            f"{contract} is incomplete: " + ", ".join(missing)
        )


def test_connected_client_courtyard_start_is_render_and_activation_suppressed() -> str:
    layout = _read("config/binary-layout.ini")
    seams = _read("SolomonDarkModLoader/src/gameplay_seams.h")
    picker_header = _read("SolomonDarkModLoader/include/boneyard_picker.h")
    picker_internal = _read(
        "SolomonDarkModLoader/src/boneyard_picker/internal.inl"
    )
    picker_public = _read(
        "SolomonDarkModLoader/src/boneyard_picker/public.inl"
    )
    findings = _read("docs/re/map-picker.md")
    bug = _read(
        "docs/bugs/beta32-ungated-client-interactions-2026-08-04.md"
    )

    _require(
        layout + seams + findings + bug,
        (
            "courtyard_start_affordance_render=0x0050DBF0",
            "kCourtyardStartAffordanceRender",
            "`0x0050DBF0`",
            "`0x00514A20`",
            "`0x00514AB9`",
            "`0x0050E5E0`",
        ),
        "recovered Courtyard start seams",
    )
    _require(
        picker_header + picker_internal + picker_public,
        (
            "start_affordance_render_hook",
            "using CourtyardStartAffordanceRenderFn =",
            "kCourtyardStartAffordanceRenderHookMinimumPatchSize = 6",
            "HookCourtyardStartAffordanceRender",
            "InstallBoneyardAuthorityHooks(",
            "RemoveX86Hook(&g_picker.start_affordance_render_hook)",
        ),
        "always-on Courtyard authority hooks",
    )

    start_at = picker_internal.index("void __fastcall HookMapPickerStart(")
    start_body = picker_internal[start_at : start_at + 1500]
    _require(
        start_body,
        (
            "if (!HasBoneyardAuthority()) {",
            "return;",
            "if (!ShouldHijackHostBoneyardStart()) {",
            "original(courtyard);",
        ),
        "client activation suppression with host/solo trampoline",
    )
    if start_body.index("if (!HasBoneyardAuthority()) {") > start_body.index(
        "if (!ShouldHijackHostBoneyardStart()) {"
    ):
        raise StaticReTestFailure(
            "client activation must be rejected before the stock trampoline"
        )

    render_at = picker_internal.index(
        "void __fastcall HookCourtyardStartAffordanceRender("
    )
    render_body = picker_internal[render_at : render_at + 1200]
    _require(
        render_body,
        (
            "if (!HasBoneyardAuthority()) {",
            "return;",
            "original(courtyard, control);",
        ),
        "client affordance render suppression with host/solo trampoline",
    )

    initialize_at = picker_public.index("bool InitializeBoneyardPicker(")
    initialize_body = picker_public[initialize_at:]
    install_at = initialize_body.index("InstallBoneyardAuthorityHooks(")
    empty_at = initialize_body.index("if (!has_custom_entries) {")
    if install_at > empty_at:
        raise StaticReTestFailure(
            "zero-entry setup bypasses the connected-client authority hooks"
        )
    return (
        "the recovered Courtyard renderer and sole activation path are both "
        "suppressed only for connected clients, including zero-entry catalogs"
    )


def test_blocking_overlay_owns_all_gameplay_input_without_deferral() -> str:
    loading_header = _read("SolomonDarkModLoader/include/loading_screen.h")
    loading = _read("SolomonDarkModLoader/src/loading_screen.cpp")
    gameplay_root = _read("SolomonDarkModLoader/src/mod_loader_gameplay.cpp")
    ownership = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/core/"
        "blocking_overlay_input_ownership.inl"
    )
    input_hooks = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/"
        "input_hooks.inl"
    )
    mouse_hook = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/"
        "dispatch_and_hooks_mouse_refresh_hook.inl"
    )
    stock_input = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/"
        "actor_tick/local_player_stock_input_runtime.inl"
    )
    player_tick = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/gameplay_hooks/"
        "actor_tick/player_actor_tick_hook.inl"
    )
    queues = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/"
        "public_api_input_queueing.inl"
    )
    lua_input = _read(
        "SolomonDarkModLoader/src/lua_engine_bindings_input.cpp"
    )

    _require(
        loading_header + loading,
        (
            "bool BlockingOverlayOwnsGameplayInput();",
            "bool BlockingOverlayOwnsGameplayInput() {",
            "return GetLoadingScreenSnapshot().active;",
        ),
        "single blocking-overlay ownership predicate",
    )
    _require(
        gameplay_root + ownership,
        (
            '#include "mod_loader_gameplay/core/blocking_overlay_input_ownership.inl"',
            "void DiscardQueuedGameplayInputForBlockingOverlay()",
            "pending_movement_frames.store(",
            "pending_mouse_left_frames.store(",
            "pending_mouse_right_frames.store(",
            "pending_mouse_left_edge_events.store(",
            "pending_scancode.store(0",
        ),
        "blocking-overlay queue discard",
    )
    _require(
        input_hooks,
        (
            "BlockingOverlayOwnsGameplayInput()",
            "DiscardQueuedGameplayInputForBlockingOverlay();",
            "original_fn(self, scancode)",
            "return 0;",
            "BoneyardPickerOwnsScancode(scancode)",
        ),
        "all-key modal ownership with picker ownership preserved",
    )
    _require(
        mouse_hook,
        (
            "BlockingOverlayOwnsGameplayInput()",
            "DiscardQueuedGameplayInputForBlockingOverlay();",
            "SuppressGameplayMouseForBlockingOverlay(self_address);",
            "return;",
        ),
        "mouse and cast ingress suppression",
    )
    _require(
        stock_input + player_tick,
        (
            "class ScopedBlockingOverlayGameplayInput final",
            "BlockingOverlayOwnsGameplayInput()",
            "kGameplayLocalMovementInputXOffset",
            "kGameplayLocalMovementInputYOffset",
            "kGameplayCastIntentOffset",
            "kGameplayMouseLeftButtonOffset",
            "kGameplayMouseRightButtonOffset",
            "~ScopedBlockingOverlayGameplayInput()",
            "DiscardQueuedGameplayInputForBlockingOverlay();",
            "SuppressNativeGameplayInput();",
            "ScopedBlockingOverlayGameplayInput blocking_overlay_input(",
        ),
        "stock local-player input mask",
    )
    guard_at = stock_input.index(
        "class ScopedBlockingOverlayGameplayInput final"
    )
    next_guard_at = stock_input.index(
        "class ScopedLocalPlayerScriptedMovementInput final"
    )
    overlay_guard = stock_input[guard_at:next_guard_at]
    if "RestoreField(" in overlay_guard:
        raise StaticReTestFailure(
            "blocked native input must be discarded, not restored after the stock tick"
        )
    _require(
        queues + lua_input,
        (
            "BlockingOverlayOwnsGameplayInput()",
            "DiscardQueuedGameplayInputForBlockingOverlay();",
            "LuaInputQueueLocalSpellCast",
        ),
        "injected input drop instead of post-overlay deferral",
    )
    return (
        "one overlay-ownership predicate drops queued input and masks physical "
        "movement, keys, mouse buttons, and cast intent around the stock tick"
    )
