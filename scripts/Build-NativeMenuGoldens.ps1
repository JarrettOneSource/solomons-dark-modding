[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$NavigationRecordingPath,

    [string]$OutputPath = ""
)

Set-StrictMode -Version 3.0
$ErrorActionPreference = "Stop"

$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).ProviderPath
$fixtureRoot = Join-Path $root "tests\fixtures\webgame"
$layoutRoot = Join-Path $fixtureRoot "menu-layouts"
$referenceRoot = Join-Path $fixtureRoot "menu-reference-captures"
if ([string]::IsNullOrWhiteSpace($OutputPath)) {
    $OutputPath = Join-Path $fixtureRoot "menu-goldens.json"
}
$OutputPath = [IO.Path]::GetFullPath($OutputPath)

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
$captureSessions = [Collections.Generic.List[object]]::new()
$latestCapture = [DateTimeOffset]::MinValue
foreach ($file in $layoutFiles) {
    $fixture = Get-Content -LiteralPath $file.FullName -Raw |
        ConvertFrom-Json
    if ($fixture.schema -ne "solomon-dark-native-menu-layout-v1") {
        throw "Unexpected layout schema in $($file.FullName)."
    }
    if (
        [string]::IsNullOrWhiteSpace([string]$fixture.header.instance) -or
        [string]$fixture.header.capture_commit -notmatch '^[0-9a-f]{40}$' -or
        [string]::IsNullOrWhiteSpace(
            [string]$fixture.header.capture_method
        )
    ) {
        throw "Capture provenance is incomplete in $($file.FullName)."
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
    $capturedAt = [DateTimeOffset]::Parse(
        [string]$fixture.header.captured_at_utc
    )
    if ($capturedAt -gt $latestCapture) {
        $latestCapture = $capturedAt
    }
    $captureSessions.Add([ordered]@{
        instance = [string]$fixture.header.instance
        process_id = [int]$fixture.header.process_id
        capture_commit = [string]$fixture.header.capture_commit
        native_exe_sha256 = [string]$fixture.header.native_exe_sha256
        loader_dll_sha256 = [string]$fixture.header.loader_dll_sha256
        capture_method = [string]$fixture.header.capture_method
        captured_at_utc = $capturedAt.ToString("o")
    })
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

$navigationItem = Get-Item -LiteralPath $NavigationRecordingPath
$navigation = Get-Content -LiteralPath $navigationItem.FullName -Raw |
    ConvertFrom-Json
if ($navigation.schema -ne "solomon-dark-native-menu-navigation-v1") {
    throw "Navigation recording schema was not recognized."
}

$edgeIds = @(
    "control_scheme_picker_to_create",
    "create_element_to_discipline",
    "create_discipline_to_hub",
    "hub_to_pause",
    "pause_to_hub_resume",
    "pause_to_game_settings",
    "settings_to_controls_verified",
    "controls_to_settings",
    "settings_to_performance",
    "performance_to_settings",
    "settings_to_dark_cloud_settings",
    "dark_cloud_settings_to_settings",
    "settings_to_hub",
    "pause_to_leave_confirmation",
    "beta_notice_to_main",
    "main_to_profile_select",
    "profile_select_to_main",
    "main_to_settings",
    "settings_to_main",
    "main_to_hall_of_fame",
    "hall_of_fame_to_main",
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
$recordedById = @{}
foreach ($edge in @($navigation.edges)) {
    $recordedById[[string]$edge.id] = $edge
}
$edges = [Collections.Generic.List[object]]::new()
foreach ($edgeId in $edgeIds) {
    if (-not $recordedById.ContainsKey($edgeId)) {
        throw "Required live navigation edge was not recorded: $edgeId"
    }
    $recorded = $recordedById[$edgeId]
    if (
        [string]$recorded.before.frame_sha256 -notmatch '^[0-9a-f]{64}$' -or
        [string]$recorded.after.frame_sha256 -notmatch '^[0-9a-f]{64}$'
    ) {
        throw "Navigation edge has incomplete live frame provenance: $edgeId"
    }
    $normalizedId = $edgeId
    $destination = [string]$recorded.destination
    $labelCorrection = ""
    if ($edgeId -eq "settings_to_controls_verified") {
        $normalizedId = "settings_to_controls"
    } elseif ($edgeId -eq "pause_to_leave_confirmation") {
        $normalizedId = "pause_to_beta_notice"
        $destination = "beta_notice"
        $labelCorrection = (
            "The operator-supplied destination tag said leave_game_confirmation; " +
            "the captured frame and dialog art are the beta notice."
        )
    } elseif ($edgeId -eq "hall_of_fame_to_main") {
        $normalizedId = "hall_of_fame_to_beta_notice"
        $destination = "beta_notice"
        $labelCorrection = (
            "The operator-supplied destination tag said main_menu; the captured " +
            "frame and semantic dialog surface are the beta notice."
        )
    }
    $observedAt = [DateTimeOffset]::Parse(
        [string]$recorded.observed_at_utc
    )
    if ($observedAt -gt $latestCapture) {
        $latestCapture = $observedAt
    }
    $entry = [ordered]@{
        id = $normalizedId
        screen = [string]$recorded.source
        edge = [string]$recorded.trigger
        trigger = [string]$recorded.trigger
        action_id = [string]$recorded.action_id
        destination = $destination
        dispatch_result = [string]$recorded.dispatch_result
        before = $recorded.before
        after = $recorded.after
        observed_at_utc = $observedAt.ToString("o")
    }
    if (-not [string]::IsNullOrWhiteSpace($labelCorrection)) {
        $entry["recording_label_correction"] = $labelCorrection
        $entry["raw_destination_tag"] = [string]$recorded.destination
    }
    $edges.Add($entry)
}

$uniqueSessionKeys = @{}
$uniqueSessions = [Collections.Generic.List[object]]::new()
foreach ($session in $captureSessions) {
    $key = (
        [string]$session.instance + "|" +
        [string]$session.process_id + "|" +
        [string]$session.capture_commit + "|" +
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
        [string]$session.capture_commit + "|navigation"
    )
    if (-not $uniqueSessionKeys.ContainsKey($key)) {
        $uniqueSessionKeys[$key] = $true
        $uniqueSessions.Add([ordered]@{
            instance = [string]$session.instance
            process_id = [int]$session.process_id
            capture_commit = [string]$session.capture_commit
            native_exe_sha256 = [string]$session.native_exe_sha256
            loader_dll_sha256 = [string]$session.loader_dll_sha256
            capture_method = [string]$navigation.header.capture_method
            captured_at_utc = [string]$session.captured_at_utc
        })
    }
}

$golden = [ordered]@{
    schema = "solomon-dark-menu-goldens-v1"
    header = [ordered]@{
        campaign = "menure"
        gap = "G11"
        generated_from_live_capture_at_utc = $latestCapture.ToString("o")
        capture_method = (
            "live native UI tree, native Sprite/text hooks, live D3D9 render " +
            "geometry, exact-process input, and before/after backbuffer hashes"
        )
        navigation_recording_sha256 = (
            Get-FileHash -LiteralPath $navigationItem.FullName -Algorithm SHA256
        ).Hash.ToLowerInvariant()
        screen_count = $layouts.Count
        edge_count = $edges.Count
        sessions = $uniqueSessions
    }
    screen_census = @($expectedLayouts)
    layouts = $layouts
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
