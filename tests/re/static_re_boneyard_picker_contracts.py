"""Static contracts for the stock map-picker RE and loader hijack seam."""

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


def test_stock_map_picker_recovery_pins_selected_value_and_launch_path() -> str:
    findings = _read("docs/re/map-picker.md")
    layout = _read("config/binary-layout.ini")

    _require(
        findings,
        (
            "03a834566ce70fd8088f4cf9ee6693157130d8aec28c092cb814d6221231f1e3",
            "`0x00514A20`",
            "`0x0050E5E0`",
            "`0x00500980`",
            "Gameplay `+0x1CDC`",
            "`0xB4`-byte generic stock UI control",
            "`+0x6C`",
            "`0x00508E20`",
            "data\\levels\\story<index>.boneyard",
            "Gameplay selected-Boneyard String whose\nobject begins at `+0x1BD8`",
            "Gameplay\n`+0x1D40`",
            "`0x00500B40`",
            "`0x0050E320`",
            "`0x0046EA90`",
            "`0x0046DC60`",
            "Tutorial.boneyard",
            "The Tutorial controller never calls `MapPicker`",
            "[`tutorial-mechanics.md`](tutorial-mechanics.md#map-picker-handoff-for-mpk)",
        ),
        "stock map-picker recovery",
    )
    _require(
        layout,
        (
            "map_picker_start=0x0050E5E0",
            "gameplay_selected_boneyard=0x1BD8",
        ),
        "stock map-picker binary layout",
    )
    return (
        "stock trigger, fixed unlock list, entry shape, selection String, cancel, "
        "working-file launch, and the independent tutorial handoff are pinned"
    )


def test_boneyard_picker_provider_is_immutable_stock_routed_and_stock_transparent() -> str:
    design = _read("docs/design/boneyard-picker-seam.md")
    header = _read("SolomonDarkModLoader/include/boneyard_picker.h")
    internal = _read("SolomonDarkModLoader/src/boneyard_picker/internal.inl")
    frontend = _read(
        "SolomonDarkModLoader/src/boneyard_picker/frontend_render.inl"
    )
    resolution = _read(
        "SolomonDarkModLoader/src/boneyard_picker/content_resolution.inl"
    )
    public = _read("SolomonDarkModLoader/src/boneyard_picker/public.inl")
    materializer = _read(
        "SolomonDarkModLauncher/src/Staging/RuntimeMetadataStageMaterializer.cs"
    )

    _require(
        header,
        (
            "std::shared_ptr<const BoneyardPickerCatalog> catalog;",
            "bool is_open = false;",
            "BoneyardPickerSnapshot GetBoneyardPickerSnapshot();",
            "bool PickBoneyard(std::size_t index, std::string* error_message);",
            "bool CancelBoneyardPicker(std::string* error_message);",
            "std::string display_name;",
            "std::string source_mod_id;",
            "std::string source_mod_name;",
            "std::string filename;",
            "BoneyardPickerPreviewMetadata preview;",
        ),
        "stable frontend provider",
    )
    _require(
        materializer,
        (
            "IReadOnlyList<DiscoveredMod> enabledMods",
            "BoneyardFile.Inspect(sourcePath)",
            "SHA256.HashData(sourceStream)",
            'private const string BoneyardPickerDirectoryName = ".sdmod-picker";',
            "Directory.Delete(pickerRootPath, recursive: true);",
            'builder.Append("boneyard_count=")',
            'Append("boneyard.")',
        ),
        "launcher Boneyard catalog staging",
    )
    _require(
        internal + frontend + resolution,
        (
            "if (!ShouldHijackHostBoneyardStart()) {\n        original(courtyard);\n        return;\n    }",
            "kVisibleBoneyardRows = 12",
            "CryptHashData(",
            "actual_digest != entry.content_digest",
            "ApplyStockSelectionAndOpenNativePicker(",
            "kGameplaySelectedBoneyardOffset",
            "resolved_path = selection->stage_path.string();",
            "(!snapshot.is_open && snapshot.error_message.empty())",
        ),
        "stock-routed picker hook",
    )
    _require(
        public,
        (
            "PickBoneyard(",
            "CancelBoneyardPicker(",
            "g_picker.pending_event = PendingFrontendEvent::Pick;",
            "ApplyPendingPickLocked(index, now_ms);",
            "if (catalog->entries.empty()) {",
            'Log("Boneyard picker provider initialized. hook=disabled entries=0")',
            "ApplyStockSelectionAndOpenNativePicker(",
            "applied_stock_relative_path",
        ),
        "picker event and stock handoff",
    )
    if public.index("if (catalog->entries.empty()) {") > public.index(
        "InitializeGameplaySeams(error_message)"
    ):
        raise StaticReTestFailure(
            "zero-entry picker setup touches gameplay seams before opting out"
        )
    _require(
        design,
        (
            "ATC owns the visual frontend",
            "A process with zero catalog entries does not install\nthe MapPicker hook",
            "catalog is immutable for\nthe process lifetime",
            "`is_open`\nis the presentation gate",
            "The digest is checked again immediately before each native handoff",
        ),
        "picker seam design",
    )
    return (
        "immutable large-list provider, bounded frontend, enabled-mod staging, "
        "content verification, exact zero-entry branch, and stock String handoff are pinned"
    )


def test_boneyard_picker_replication_is_authoritative_missing_safe_and_late_joined() -> str:
    design = _read("docs/design/boneyard-picker-seam.md")
    protocol = _read("SolomonDarkModLoader/include/multiplayer_runtime_protocol.h")
    local_state = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/local_state_packet_sync.inl"
    )
    incoming = _read(
        "SolomonDarkModLoader/src/multiplayer_local_transport/incoming_participant_state_sync.inl"
    )
    picker_internal = _read("SolomonDarkModLoader/src/boneyard_picker/internal.inl")
    frontend = _read(
        "SolomonDarkModLoader/src/boneyard_picker/frontend_render.inl"
    )
    picker_public = _read("SolomonDarkModLoader/src/boneyard_picker/public.inl")
    dispatch = _read(
        "SolomonDarkModLoader/src/mod_loader_gameplay/dispatch_and_hooks_gameplay_thread_dispatch.inl"
    )
    scene = _read("SolomonDarkModLoader/src/lua_engine_bindings_scene.cpp")

    _require(
        protocol,
        (
            "kProtocolVersion = 90",
            "boneyard_selection_revision",
            "boneyard_resolution_status",
            "boneyard_selection_sha256",
            "sizeof(StatePacket) == 705",
            "sizeof(ParticipantFramePacket) == 422",
        ),
        "Boneyard packet protocol",
    )
    if protocol.count("boneyard_selection_revision") != 2 or protocol.count(
        "boneyard_selection_sha256"
    ) != 2:
        raise StaticReTestFailure(
            "Boneyard selection fields are not present in both state packet kinds"
        )
    _require(
        local_state,
        (
            "BuildLocalBoneyardPickerPacketState()",
            "boneyard_selection_revision = boneyard.revision",
            "boneyard_selection_sha256,",
        ),
        "local Boneyard packet publication",
    )
    _require(
        incoming,
        (
            "ApplyAuthoritativeBoneyardPickerPacket(boneyard_packet);",
            "RecordRemoteBoneyardPickerPacket(",
        ),
        "authenticated Boneyard packet routing",
    )
    _require(
        picker_internal,
        (
            "multiplayer::IsRemoteParticipant(participant)",
            "multiplayer::IsNativeControlledParticipant(participant)",
            "participant.transport_connected",
            "found->second.packet.revision != g_picker.selection_revision",
            "found->second.packet.digest != g_picker.selected_digest",
            "BoneyardResolutionStatus::Missing",
            "The run was not launched.",
            "Affected players cannot enter the active run.",
            "peer_resolution_error_active",
        ),
        "host-authoritative Boneyard barrier",
    )
    _require(
        picker_public,
        (
            "TryDispatchAuthoritativeBoneyardRunOnGameThread(",
            "ApplyAuthoritativeBoneyardPickerPacket(",
            "RecordRemoteBoneyardPickerPacket(",
            "kMissingResolutionRetryMs",
            "local_resolution = BoneyardResolutionStatus::Missing",
        ),
        "client resolution and retry path",
    )
    _require(
        dispatch,
        (
            "TryDispatchAuthoritativeBoneyardRunOnGameThread(",
            "if (boneyard_picker_handled) {\n        return true;\n    }",
        ),
        "client pre-stock dispatch ordering",
    )
    _require(
        scene,
        (
            '"boneyard_picker_phase"',
            '"boneyard_picker_open"',
            '"boneyard_revision"',
            '"boneyard_sha256"',
            '"boneyard_resolution"',
            '"boneyard_stock_path"',
            '"boneyard_error"',
        ),
        "per-peer Boneyard state evidence",
    )
    _require(
        design,
        (
            "Clients accept selection changes only from the authenticated configured\nauthority",
            "A late join therefore resolves the catalog entry before the existing scene\nfollow logic",
            "refuses\n  run entry",
            "no fallback to another Boneyard",
        ),
        "authoritative replication design",
    )
    return (
        "fixed-width authority selection, authenticated acknowledgements, human-peer "
        "barrier, missing/retry error, late join ordering, and per-peer evidence are pinned"
    )


def test_boneyard_picker_presents_mod_description_and_scales_with_viewport() -> str:
    header = _read("SolomonDarkModLoader/include/boneyard_picker.h")
    bootstrap_header = _read("SolomonDarkModLoader/include/runtime_bootstrap.h")
    bootstrap = _read("SolomonDarkModLoader/src/runtime_bootstrap.cpp")
    public = _read("SolomonDarkModLoader/src/boneyard_picker/public.inl")
    frontend = _read(
        "SolomonDarkModLoader/src/boneyard_picker/frontend_render.inl"
    )
    materializer = _read(
        "SolomonDarkModLauncher/src/Staging/RuntimeMetadataStageMaterializer.cs"
    )
    manifest = _read("SolomonDarkModLauncher/src/Mods/ModManifest.cs")

    # Presentation metadata flows launcher manifest -> stage ini -> loader
    # descriptor -> catalog entry; the keys stay optional so older stages
    # keep loading.
    _require(
        manifest,
        ("public string? Description { get; init; }",),
        "manifest description field",
    )
    _require(
        materializer,
        (
            "mod.Manifest.Description?.Trim() ?? string.Empty",
            'Append("source_mod_description=")',
            'Append("updated_utc=")',
            "File.GetLastWriteTimeUtc(sourcePath)",
        ),
        "staged presentation metadata",
    )
    _require(
        bootstrap_header + bootstrap,
        (
            "std::string source_mod_description;",
            "std::string updated_utc;",
            'sections, section_name, "source_mod_description"',
            'sections, section_name, "updated_utc"',
            "Optional presentation metadata; older stages simply omit the keys.",
        ),
        "optional bootstrap presentation keys",
    )
    _require(
        header + public,
        (
            "entry.source_mod_description = descriptor.source_mod_description;",
            "entry.updated_utc = descriptor.updated_utc;",
        ),
        "catalog entry presentation fields",
    )

    # Owner-directed layout: list zone on the top two-thirds, details below
    # showing name, source mod, update date, and description — never the
    # old size/layout/sha/file stat dump — with one viewport-derived scale
    # driving every text metric.
    _require(
        frontend,
        (
            "kPickerBaseViewportHeight = 720.0f",
            "vh / kPickerBaseViewportHeight",
            "kPickerMaxUiScale,",
            "const float list_panel_height = vh * 0.61f;",
            "const float detail_panel_height = vh * 0.26f;",
            "WrapPickerText(",
            "entry.source_mod_description;",
            '"Updated " + entry.updated_utc',
            '"No description provided."',
        ),
        "viewport-scaled description frontend",
    )
    for banished in ("FormatPickerByteSize", "ShortPickerSha", '"SHA-256"'):
        if banished in frontend:
            raise StaticReTestFailure(
                "picker details regressed to the stat dump: " + banished
            )
    return (
        "manifest description, stage ini keys, optional bootstrap parse, entry "
        "fields, two-thirds layout, viewport text scaling, and stat-dump removal "
        "are pinned"
    )
