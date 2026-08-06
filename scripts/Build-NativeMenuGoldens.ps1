[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$NavigationRecordingPath,

    [string]$FixtureRoot = "",
    [string]$OutputPath = ""
)

Set-StrictMode -Version 3.0
$ErrorActionPreference = "Stop"

$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).ProviderPath
if ([string]::IsNullOrWhiteSpace($FixtureRoot)) {
    $FixtureRoot = Join-Path $root "tests\fixtures\webgame"
}
$fixtureRoot = [IO.Path]::GetFullPath($FixtureRoot)
$layoutRoot = Join-Path $fixtureRoot "menu-layouts"
$transitionLayoutRoot = Join-Path $fixtureRoot "menu-transition-layouts"
$referenceRoot = Join-Path $fixtureRoot "menu-reference-captures"
$confirmationRoot = Join-Path $fixtureRoot "menu-animation-confirmations"
if ([string]::IsNullOrWhiteSpace($OutputPath)) {
    $OutputPath = Join-Path $fixtureRoot "menu-goldens.json"
}
$OutputPath = [IO.Path]::GetFullPath($OutputPath)

function Get-NativeMenuStructuralSummary {
    param([Parameter(Mandatory = $true)][object]$Layout)

    $classifier = Join-Path $root "tools\native_menu_settlement_v2.py"
    $temporaryDirectory = Join-Path ([IO.Path]::GetTempPath()) (
        "sdmod-menu-structural-summary-" + [Guid]::NewGuid().ToString("N")
    )
    [IO.Directory]::CreateDirectory($temporaryDirectory) | Out-Null
    $inputPath = Join-Path $temporaryDirectory "layout.json"
    $outputPath = Join-Path $temporaryDirectory "summary.json"
    try {
        [IO.File]::WriteAllText(
            $inputPath,
            (($Layout | ConvertTo-Json -Depth 100) + [Environment]::NewLine),
            [Text.UTF8Encoding]::new($false)
        )
        $result = @(
            & py.exe -3 $classifier summarize-layout `
                --input $inputPath `
                --output $outputPath 2>&1
        )
        if ($LASTEXITCODE -ne 0) {
            throw (
                "Settlement v2 structural layout summary failed: " +
                (($result | ForEach-Object { [string]$_ }) -join "`n")
            )
        }
        return Get-Content -LiteralPath $outputPath -Raw | ConvertFrom-Json
    } finally {
        if (Test-Path -LiteralPath $temporaryDirectory -PathType Container) {
            Remove-Item -LiteralPath $temporaryDirectory -Recurse -Force
        }
    }
}

function ConvertTo-GoldenEndpoint {
    param([Parameter(Mandatory = $true)][object]$Observation)

    return [ordered]@{
        semantic_surface = [string]$Observation.semantic_surface
        semantic_generation = [uint64]$Observation.semantic_generation
        tagged_screen = [string]$Observation.tagged_screen
        layout_generation = [uint64]$Observation.layout_generation
        element_count = [int]$Observation.element_count
        animated_element_ids = @($Observation.animated_element_ids)
        structural_sha256 = [string]$Observation.settlement.structural_sha256
        capture_method = [string]$Observation.capture_method
        frame_sha256 = [string]$Observation.frame_sha256
        settlement = $Observation.settlement
        layout = $Observation.layout
    }
}

$expectedLayouts = @(
    "beta-notice",
    "controls",
    "control-scheme-picker",
    "create-discipline",
    "create-element",
    "dark-cloud-browser",
    "dark-cloud-login-settings",
    "dark-cloud-menu",
    "dark-cloud-my-levels",
    "dark-cloud-online-levels",
    "dark-cloud-options",
    "dark-cloud-recent",
    "dark-cloud-search",
    "dark-cloud-settings",
    "dark-cloud-sort",
    "game-over",
    "game-settings-dark-cloud",
    "game-settings-gameplay",
    "game-settings-title",
    "hall-of-fame",
    "loading-screen",
    "main-menu-root",
    "map-picker",
    "native-loader",
    "pause-menu",
    "performance",
    "profile-save-select",
    "skill-picker"
)

$layoutFiles = @(
    Get-ChildItem -LiteralPath $layoutRoot -File -Filter "*.json" |
        Sort-Object BaseName
)
$actualLayouts = @($layoutFiles | ForEach-Object { $_.BaseName })
if (
    $actualLayouts.Count -ne $expectedLayouts.Count -or
    @(Compare-Object $expectedLayouts $actualLayouts).Count -ne 0
) {
    throw (
        "Layout fixture census differs from the pinned G11 census. " +
        "Expected=$($expectedLayouts -join ',') Actual=$($actualLayouts -join ',')"
    )
}

$layouts = [Collections.Generic.List[object]]::new()
$layoutFixtureById = @{}
$captureSessions = [Collections.Generic.List[object]]::new()
$latestCapture = [DateTimeOffset]::MinValue
foreach ($file in $layoutFiles) {
    $fixture = Get-Content -LiteralPath $file.FullName -Raw |
        ConvertFrom-Json
    if ($fixture.schema -ne "solomon-dark-native-menu-layout-v2") {
        throw "Unexpected layout schema in $($file.FullName)."
    }
    $source = $fixture.header.source
    $settlement = $fixture.header.settlement
    if (
        [string]::IsNullOrWhiteSpace([string]$fixture.header.instance) -or
        [bool]$fixture.header.recorded_live -ne $true -or
        [string]$source.base_commit_sha -notmatch '^[0-9a-f]{40}$' -or
        [string]$source.source_tree_sha -notmatch '^[0-9a-f]{40}$' -or
        [string]$source.game_executable_sha256 -notmatch '^[0-9a-f]{64}$' -or
        [string]$source.loader_dll_sha256 -notmatch '^[0-9a-f]{64}$' -or
        [int]$settlement.consecutive_structural_samples -lt 40 -or
        [int]$settlement.animated_id_set_sample_count -lt 40 -or
        [int]$settlement.stable_span_milliseconds -lt 2000 -or
        [int]$settlement.settle_latency_milliseconds -lt 2000 -or
        [double]$settlement.animated_fraction -gt 0.30 -or
        [string]$settlement.structural_sha256 -notmatch '^[0-9a-f]{64}$' -or
        [string]::IsNullOrWhiteSpace([string]$fixture.header.capture_method)
    ) {
        throw "Capture provenance is incomplete in $($file.FullName)."
    }
    $fixtureStructural = Get-NativeMenuStructuralSummary -Layout $fixture.layout
    if (
        [string]$fixtureStructural.structural_sha256 -ne
            [string]$settlement.structural_sha256 -or
        (ConvertTo-Json -InputObject @(
            $fixtureStructural.animated_element_ids
        ) -Compress) -cne (ConvertTo-Json -InputObject @(
            $fixture.layout.animated_element_ids
        ) -Compress)
    ) {
        throw (
            "Settlement v2 header does not describe the structural layout " +
            "in $($file.FullName)."
        )
    }
    $referenceRelative = [string]$fixture.header.reference_capture
    $referencePath = [IO.Path]::GetFullPath(
        (Join-Path $layoutRoot $referenceRelative)
    )
    if (
        -not $referencePath.StartsWith(
            [IO.Path]::GetFullPath($referenceRoot),
            [StringComparison]::OrdinalIgnoreCase
        ) -or
        -not (Test-Path -LiteralPath $referencePath -PathType Leaf)
    ) {
        throw "Reference capture is missing or outside its fixture root: $referenceRelative"
    }
    $confirmation = $fixture.header.animation_confirmation
    $confirmationPath = [IO.Path]::GetFullPath(
        (Join-Path $confirmationRoot ([string]$confirmation.evidence_filename))
    )
    if (
        [string]::IsNullOrWhiteSpace([string]$confirmation.instance) -or
        [int]$confirmation.process_id -eq [int]$fixture.header.process_id -or
        [string]$confirmation.sha256 -notmatch '^[0-9a-f]{64}$' -or
        [string]$confirmation.structural_sha256 -ne
            [string]$settlement.structural_sha256 -or
        -not (Test-Path -LiteralPath $confirmationPath -PathType Leaf) -or
        [long]$confirmation.bytes -ne
            (Get-Item -LiteralPath $confirmationPath).Length -or
        [string]$confirmation.sha256 -ne (
            Get-FileHash -LiteralPath $confirmationPath -Algorithm SHA256
        ).Hash.ToLowerInvariant()
    ) {
        throw (
            "Fresh-instance animated-ID confirmation is incomplete or false " +
            "in $($file.FullName)."
        )
    }
    $capturedAt = [DateTimeOffset]::Parse(
        [string]$fixture.header.captured_at_utc
    )
    if ($capturedAt -gt $latestCapture) {
        $latestCapture = $capturedAt
    }
    $captureSessions.Add([ordered]@{
        instance = [string]$fixture.header.instance
        process_id = [int]$fixture.header.process_id
        source = $fixture.header.source
        recorded_live = [bool]$fixture.header.recorded_live
        capture_method = [string]$fixture.header.capture_method
        captured_at_utc = $capturedAt.ToString("o")
    })
    if ($layoutFixtureById.ContainsKey($file.BaseName)) {
        throw "Ambiguous duplicate layout fixture ID: $($file.BaseName)"
    }
    $layoutFixtureById[$file.BaseName] = $fixture
    $layouts.Add([ordered]@{
        fixture = "menu-layouts/$($file.Name)"
        reference_capture = "menu-reference-captures/$([IO.Path]::GetFileName($referencePath))"
        reference_sha256 = (
            Get-FileHash -LiteralPath $referencePath -Algorithm SHA256
        ).Hash.ToLowerInvariant()
        header = $fixture.header
        layout = $fixture.layout
    })
}

$transitionLayoutFiles = @(
    Get-ChildItem -LiteralPath $transitionLayoutRoot -File -Filter "*.json" |
        Sort-Object BaseName
)
if (
    $transitionLayoutFiles.Count -ne 1 -or
    $transitionLayoutFiles[0].BaseName -ne "hub"
) {
    throw (
        "The every-edge destination contract requires exactly the standalone " +
        "menu-transition-layouts/hub.json witness."
    )
}
$transitionEndpointLayouts = [Collections.Generic.List[object]]::new()
foreach ($file in $transitionLayoutFiles) {
    $fixture = Get-Content -LiteralPath $file.FullName -Raw |
        ConvertFrom-Json
    $source = $fixture.header.source
    $settlement = $fixture.header.settlement
    if (
        $fixture.schema -ne "solomon-dark-native-menu-layout-v2" -or
        [bool]$fixture.header.recorded_live -ne $true -or
        [string]$source.base_commit_sha -notmatch '^[0-9a-f]{40}$' -or
        [string]$source.source_tree_sha -notmatch '^[0-9a-f]{40}$' -or
        [string]$source.game_executable_sha256 -notmatch '^[0-9a-f]{64}$' -or
        [string]$source.loader_dll_sha256 -notmatch '^[0-9a-f]{64}$' -or
        [int]$settlement.consecutive_structural_samples -lt 40 -or
        [int]$settlement.animated_id_set_sample_count -lt 40 -or
        [int]$settlement.stable_span_milliseconds -lt 2000 -or
        [double]$settlement.animated_fraction -gt 0.30 -or
        [string]$settlement.structural_sha256 -notmatch '^[0-9a-f]{64}$'
    ) {
        throw "Transition-only standalone provenance is incomplete: hub"
    }
    $fixtureStructural = Get-NativeMenuStructuralSummary -Layout $fixture.layout
    if (
        [string]$fixtureStructural.structural_sha256 -ne
        [string]$settlement.structural_sha256
    ) {
        throw "Transition-only hub settlement header does not describe its layout."
    }
    $referencePath = [IO.Path]::GetFullPath((Join-Path `
        $transitionLayoutRoot `
        ([string]$fixture.header.reference_capture)
    ))
    if (-not (Test-Path -LiteralPath $referencePath -PathType Leaf)) {
        throw "Transition-only standalone reference capture is missing: hub"
    }
    $confirmation = $fixture.header.animation_confirmation
    $confirmationPath = [IO.Path]::GetFullPath(
        (Join-Path $confirmationRoot ([string]$confirmation.evidence_filename))
    )
    if (
        [int]$confirmation.process_id -eq [int]$fixture.header.process_id -or
        [string]$confirmation.sha256 -notmatch '^[0-9a-f]{64}$' -or
        [string]$confirmation.structural_sha256 -ne
            [string]$settlement.structural_sha256 -or
        -not (Test-Path -LiteralPath $confirmationPath -PathType Leaf) -or
        [string]$confirmation.sha256 -ne (
            Get-FileHash -LiteralPath $confirmationPath -Algorithm SHA256
        ).Hash.ToLowerInvariant()
    ) {
        throw "Transition-only hub lost its fresh-instance animation confirmation."
    }
    $capturedAt = [DateTimeOffset]::Parse(
        [string]$fixture.header.captured_at_utc
    )
    if ($capturedAt -gt $latestCapture) {
        $latestCapture = $capturedAt
    }
    $captureSessions.Add([ordered]@{
        instance = [string]$fixture.header.instance
        process_id = [int]$fixture.header.process_id
        source = $fixture.header.source
        recorded_live = [bool]$fixture.header.recorded_live
        capture_method = [string]$fixture.header.capture_method
        captured_at_utc = $capturedAt.ToString("o")
    })
    $layoutFixtureById["hub"] = $fixture
    $transitionEndpointLayouts.Add([ordered]@{
        fixture = "menu-transition-layouts/$($file.Name)"
        reference_capture = (
            "menu-reference-captures/$([IO.Path]::GetFileName($referencePath))"
        )
        reference_sha256 = (
            Get-FileHash -LiteralPath $referencePath -Algorithm SHA256
        ).Hash.ToLowerInvariant()
        header = $fixture.header
        layout = $fixture.layout
    })
}

$navigationItem = Get-Item -LiteralPath $NavigationRecordingPath
$navigation = Get-Content -LiteralPath $navigationItem.FullName -Raw |
    ConvertFrom-Json
if ($navigation.schema -ne "solomon-dark-native-menu-navigation-v2") {
    throw "Navigation recording schema was not recognized."
}

$edgeIds = @(
    "control_scheme_picker_to_create",
    "create_element_to_discipline",
    "create_discipline_to_hub",
    "hub_to_pause",
    "pause_to_hub_resume",
    "pause_to_game_settings",
    "settings_to_controls",
    "controls_to_settings",
    "settings_to_performance",
    "performance_to_settings",
    "settings_to_dark_cloud_settings",
    "dark_cloud_settings_to_settings",
    "settings_to_hub",
    "pause_to_beta_notice",
    "beta_notice_to_main",
    "main_to_profile_select",
    "profile_select_to_main",
    "main_to_settings",
    "settings_to_main",
    "main_to_hall_of_fame",
    "hall_of_fame_to_beta_notice",
    "main_to_dark_cloud",
    "dark_cloud_to_recent",
    "dark_cloud_recent_to_online",
    "dark_cloud_online_to_my_levels",
    "dark_cloud_to_search",
    "dark_cloud_search_to_browser",
    "dark_cloud_to_sort",
    "dark_cloud_sort_to_browser",
    "dark_cloud_to_options",
    "dark_cloud_options_to_browser",
    "dark_cloud_to_login_settings",
    "dark_cloud_login_to_browser",
    "dark_cloud_to_menu",
    "dark_cloud_menu_resume",
    "dark_cloud_menu_to_settings",
    "dark_cloud_settings_done",
    "dark_cloud_menu_to_beta_notice",
    "profile_select_resume_to_hub"
)
$destinationLayoutByEdge = [ordered]@{
    control_scheme_picker_to_create = "create-element"
    create_element_to_discipline = "create-discipline"
    create_discipline_to_hub = "hub"
    hub_to_pause = "pause-menu"
    pause_to_hub_resume = "hub"
    pause_to_game_settings = "game-settings-gameplay"
    settings_to_controls = "controls"
    controls_to_settings = "game-settings-gameplay"
    settings_to_performance = "performance"
    performance_to_settings = "game-settings-gameplay"
    settings_to_dark_cloud_settings = "dark-cloud-settings"
    dark_cloud_settings_to_settings = "game-settings-gameplay"
    settings_to_hub = "hub"
    pause_to_beta_notice = "beta-notice"
    beta_notice_to_main = "main-menu-root"
    main_to_profile_select = "profile-save-select"
    profile_select_to_main = "main-menu-root"
    main_to_settings = "game-settings-title"
    settings_to_main = "main-menu-root"
    main_to_hall_of_fame = "hall-of-fame"
    hall_of_fame_to_beta_notice = "beta-notice"
    main_to_dark_cloud = "dark-cloud-browser"
    dark_cloud_to_recent = "dark-cloud-recent"
    dark_cloud_recent_to_online = "dark-cloud-online-levels"
    dark_cloud_online_to_my_levels = "dark-cloud-my-levels"
    dark_cloud_to_search = "dark-cloud-search"
    dark_cloud_search_to_browser = "dark-cloud-my-levels"
    dark_cloud_to_sort = "dark-cloud-sort"
    dark_cloud_sort_to_browser = "dark-cloud-my-levels"
    dark_cloud_to_options = "dark-cloud-options"
    dark_cloud_options_to_browser = "dark-cloud-my-levels"
    dark_cloud_to_login_settings = "dark-cloud-login-settings"
    dark_cloud_login_to_browser = "dark-cloud-my-levels"
    dark_cloud_to_menu = "dark-cloud-menu"
    dark_cloud_menu_resume = "dark-cloud-my-levels"
    dark_cloud_menu_to_settings = "game-settings-dark-cloud"
    dark_cloud_settings_done = "dark-cloud-my-levels"
    dark_cloud_menu_to_beta_notice = "beta-notice"
    profile_select_resume_to_hub = "hub"
}
if (
    $destinationLayoutByEdge.Count -ne $edgeIds.Count -or
    @(Compare-Object $edgeIds @($destinationLayoutByEdge.Keys)).Count -ne 0
) {
    throw (
        "Every required navigation edge must name exactly one standalone " +
        "destination layout."
    )
}
$recordedById = @{}
foreach ($edge in @($navigation.edges)) {
    $recordedId = [string]$edge.id
    if ($recordedById.ContainsKey($recordedId)) {
        throw (
            "Navigation recording contains ambiguous duplicate edge ID: " +
            $recordedId
        )
    }
    $recordedById[$recordedId] = $edge
}
$edges = [Collections.Generic.List[object]]::new()
foreach ($edgeId in $edgeIds) {
    if (-not $recordedById.ContainsKey($edgeId)) {
        throw "Required live navigation edge was not recorded: $edgeId"
    }
    $recorded = $recordedById[$edgeId]
    $edgeSource = $recorded.header.source
    $edgeSettlement = $recorded.header.settlement
    if (
        [bool]$recorded.header.recorded_live -ne $true -or
        [string]$edgeSource.base_commit_sha -notmatch '^[0-9a-f]{40}$' -or
        [string]$edgeSource.source_tree_sha -notmatch '^[0-9a-f]{40}$' -or
        [string]$edgeSource.game_executable_sha256 -notmatch '^[0-9a-f]{64}$' -or
        [string]$edgeSource.loader_dll_sha256 -notmatch '^[0-9a-f]{64}$' -or
        [int]$edgeSettlement.source.consecutive_structural_samples -lt 40 -or
        [int]$edgeSettlement.source.animated_id_set_sample_count -lt 40 -or
        [int]$edgeSettlement.source.stable_span_milliseconds -lt 2000 -or
        [double]$edgeSettlement.source.animated_fraction -gt 0.30 -or
        [int]$edgeSettlement.destination.consecutive_structural_samples -lt 40 -or
        [int]$edgeSettlement.destination.animated_id_set_sample_count -lt 40 -or
        [int]$edgeSettlement.destination.stable_span_milliseconds -lt 2000 -or
        [double]$edgeSettlement.destination.animated_fraction -gt 0.30 -or
        $null -eq $recorded.before.layout -or
        $null -eq $recorded.after.layout
    ) {
        throw "Navigation edge has incomplete settled provenance: $edgeId"
    }
    if (
        [string]$recorded.before.frame_sha256 -notmatch '^[0-9a-f]{64}$' -or
        [string]$recorded.after.frame_sha256 -notmatch '^[0-9a-f]{64}$'
    ) {
        throw "Navigation edge has incomplete live frame provenance: $edgeId"
    }
    $destinationLayoutId = [string]$destinationLayoutByEdge[$edgeId]
    if (-not $layoutFixtureById.ContainsKey($destinationLayoutId)) {
        throw (
            "Navigation destination '$edgeId' names missing standalone " +
            "layout '$destinationLayoutId'."
        )
    }
    $destinationStructural = Get-NativeMenuStructuralSummary `
        -Layout $recorded.after.layout
    $standaloneStructural = Get-NativeMenuStructuralSummary `
        -Layout $layoutFixtureById[$destinationLayoutId].layout
    $destinationAnimatedJson = ConvertTo-Json `
        -InputObject @($destinationStructural.animated_element_ids) `
        -Compress
    $standaloneAnimatedJson = ConvertTo-Json `
        -InputObject @($standaloneStructural.animated_element_ids) `
        -Compress
    if ($destinationAnimatedJson -cne $standaloneAnimatedJson) {
        throw (
            "STOP: settled navigation destination '$edgeId' classified " +
            "animated ids $destinationAnimatedJson but standalone " +
            "'$destinationLayoutId' classified $standaloneAnimatedJson."
        )
    }
    if (
        [string]$destinationStructural.structural_sha256 -ne
        [string]$standaloneStructural.structural_sha256
    ) {
        throw (
            "STOP: settled navigation destination '$edgeId' does not " +
            "structurally byte-match standalone layout '$destinationLayoutId'."
        )
    }
    $observedAt = [DateTimeOffset]::Parse(
        [string]$recorded.observed_at_utc
    )
    if ($observedAt -gt $latestCapture) {
        $latestCapture = $observedAt
    }
    $entry = [ordered]@{
        header = $recorded.header
        id = $edgeId
        screen = [string]$recorded.source
        edge = [string]$recorded.trigger
        trigger = [string]$recorded.trigger
        action_id = [string]$recorded.action_id
        destination = [string]$recorded.destination
        destination_layout_fixture = $(if ($destinationLayoutId -eq "hub") {
            "menu-transition-layouts/hub.json"
        } else {
            "menu-layouts/$destinationLayoutId.json"
        })
        dispatch_result = [string]$recorded.dispatch_result
        before = ConvertTo-GoldenEndpoint $recorded.before
        after = ConvertTo-GoldenEndpoint $recorded.after
        observed_at_utc = $observedAt.ToString("o")
    }
    $edges.Add($entry)
}

$uniqueSessionKeys = @{}
$uniqueSessions = [Collections.Generic.List[object]]::new()
foreach ($session in $captureSessions) {
    $key = (
        [string]$session.instance + "|" +
        [string]$session.process_id + "|" +
        [string]$session.source.base_commit_sha + "|" +
        [string]$session.capture_method
    )
    if (-not $uniqueSessionKeys.ContainsKey($key)) {
        $uniqueSessionKeys[$key] = $true
        $uniqueSessions.Add($session)
    }
}
foreach ($session in @($navigation.header.sessions)) {
    $key = (
        [string]$session.instance + "|" +
        [string]$session.process_id + "|" +
        [string]$session.source.base_commit_sha + "|navigation"
    )
    if (-not $uniqueSessionKeys.ContainsKey($key)) {
        $uniqueSessionKeys[$key] = $true
        $uniqueSessions.Add([ordered]@{
            instance = [string]$session.instance
            process_id = [int]$session.process_id
            source = $session.source
            recorded_live = [bool]$session.recorded_live
            capture_method = [string]$navigation.header.capture_method
            captured_at_utc = [string]$session.captured_at_utc
        })
    }
}

$golden = [ordered]@{
    schema = "solomon-dark-menu-goldens-v2"
    header = [ordered]@{
        campaign = "menufix"
        gap = "G11"
        generated_from_live_capture_at_utc = $latestCapture.ToString("o")
        capture_method = (
            "Settlement v2 structural native UI capture, measured animated " +
            "geometry anchors/envelopes, native Sprite/text hooks, live D3D9 " +
            "frames, exact-process input, and fresh-instance animation confirmation"
        )
        raw_recording = [ordered]@{
            evidence_filename = $navigationItem.Name
            sha256 = (
                Get-FileHash `
                    -LiteralPath $navigationItem.FullName `
                    -Algorithm SHA256
            ).Hash.ToLowerInvariant()
            bytes = $navigationItem.Length
        }
        screen_count = $layouts.Count
        edge_count = $edges.Count
        sessions = $uniqueSessions
    }
    screen_census = @($expectedLayouts)
    layouts = $layouts
    transition_endpoint_layouts = $transitionEndpointLayouts
    navigation_graph = [ordered]@{
        capture_method = [string]$navigation.header.capture_method
        edges = $edges
    }
}

[IO.Directory]::CreateDirectory(
    (Split-Path -Parent $OutputPath)
) | Out-Null
$json = $golden | ConvertTo-Json -Depth 60
[IO.File]::WriteAllText(
    $OutputPath,
    $json + [Environment]::NewLine,
    [Text.UTF8Encoding]::new($false)
)
[ordered]@{
    success = $true
    output = $OutputPath
    screen_count = $layouts.Count
    edge_count = $edges.Count
    sha256 = (
        Get-FileHash -LiteralPath $OutputPath -Algorithm SHA256
    ).Hash.ToLowerInvariant()
} | ConvertTo-Json -Compress
