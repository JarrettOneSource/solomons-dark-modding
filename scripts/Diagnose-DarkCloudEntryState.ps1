[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$Root,

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9._-]{0,47}$')]
    [string]$Instance,

    [Parameter(Mandatory = $true)]
    [ValidateRange(1, [int]::MaxValue)]
    [int]$ProcessId,

    [Parameter(Mandatory = $true)]
    [string]$OutputDirectory,

    [ValidateSet(
        "Lifecycle", "EntryOnly", "ResumeFromBeta", "ResumeFromDialog",
        "ResumeFromPause"
    )]
    [string]$Mode = "Lifecycle"
)

Set-StrictMode -Version 3.0
$ErrorActionPreference = "Stop"

$resolvedRoot = (Resolve-Path -LiteralPath $Root).ProviderPath
$resolvedOutput = [IO.Path]::GetFullPath($OutputDirectory)
[IO.Directory]::CreateDirectory($resolvedOutput) | Out-Null
. (Join-Path $resolvedRoot "scripts\NativeMenuCaptureSupport.ps1")

$context = New-NativeMenuCaptureContext `
    -Root $resolvedRoot `
    -Instance $Instance `
    -ProcessId $ProcessId
$instanceRoot = Join-Path $resolvedRoot (
    "runtime\instances\" + $Instance.ToLowerInvariant()
)
$observations = [Collections.Generic.List[object]]::new()
$stateSnapshots = [Collections.Generic.List[object]]::new()
$dispatches = [Collections.Generic.List[object]]::new()

function Write-Utf8Json {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][object]$Value
    )

    [IO.File]::WriteAllText(
        $Path,
        (($Value | ConvertTo-Json -Depth 100) + [Environment]::NewLine),
        [Text.UTF8Encoding]::new($false)
    )
}

function ConvertTo-RelativePath {
    param(
        [Parameter(Mandatory = $true)][string]$BasePath,
        [Parameter(Mandatory = $true)][string]$ChildPath
    )

    $baseUri = [Uri]::new($BasePath.TrimEnd('\') + '\')
    return [Uri]::UnescapeDataString(
        $baseUri.MakeRelativeUri([Uri]::new($ChildPath)).ToString()
    ).Replace('/', '\')
}

function Get-DarkCloudSettingValue {
    param([Parameter(Mandatory = $true)][string]$Path)

    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) {
        return $null
    }
    $match = Select-String `
        -LiteralPath $Path `
        -Pattern '^DarkCloud\.ViewingLevels=(.*)$' |
        Select-Object -First 1
    if ($null -eq $match) {
        return $null
    }
    return [string]$match.Matches[0].Groups[1].Value
}

function Save-DurableStateSnapshot {
    param([Parameter(Mandatory = $true)][string]$Label)

    $roots = @(
        [pscustomobject]@{
            label = "stage_sandbox"
            path = (Join-Path $instanceRoot "stage\sandbox")
        },
        [pscustomobject]@{
            label = "profile"
            path = (Join-Path $instanceRoot "profile")
        },
        [pscustomobject]@{
            label = "temporary_client_profile"
            path = (Join-Path $instanceRoot "temporary-client-profile")
        }
    )
    $files = [Collections.Generic.List[object]]::new()
    foreach ($stateRoot in $roots) {
        if (-not (Test-Path -LiteralPath $stateRoot.path -PathType Container)) {
            continue
        }
        foreach ($item in @(
            Get-ChildItem -LiteralPath $stateRoot.path -Recurse -File |
                Sort-Object FullName
        )) {
            $files.Add([ordered]@{
                root = [string]$stateRoot.label
                relative_path = ConvertTo-RelativePath `
                    -BasePath $stateRoot.path `
                    -ChildPath $item.FullName
                bytes = [long]$item.Length
                sha256 = (Get-FileHash `
                    -LiteralPath $item.FullName `
                    -Algorithm SHA256).Hash.ToLowerInvariant()
                last_write_utc = $item.LastWriteTimeUtc.ToString("o")
            })
        }
    }
    $settingsPath = Join-Path $instanceRoot "stage\sandbox\settings.txt"
    $snapshot = [ordered]@{
        label = $Label
        captured_at_utc = [DateTime]::UtcNow.ToString("o")
        instance = $Instance
        process_id = $ProcessId
        dark_cloud_viewing_levels = Get-DarkCloudSettingValue `
            -Path $settingsPath
        files = @($files)
    }
    $snapshotPath = Join-Path $resolvedOutput "$Label.profile-state.json"
    Write-Utf8Json -Path $snapshotPath -Value $snapshot
    $stateSnapshots.Add([ordered]@{
        label = $Label
        path = $snapshotPath
        sha256 = (Get-FileHash `
            -LiteralPath $snapshotPath `
            -Algorithm SHA256).Hash.ToLowerInvariant()
        dark_cloud_viewing_levels = $snapshot.dark_cloud_viewing_levels
        files = @($snapshot.files)
    })
}

function Get-StateDiff {
    param(
        [Parameter(Mandatory = $true)][object]$Before,
        [Parameter(Mandatory = $true)][object]$After
    )

    $beforeByPath = @{}
    foreach ($file in @($Before.files)) {
        $beforeByPath[([string]$file.root + "\" +
            [string]$file.relative_path)] = $file
    }
    $afterByPath = @{}
    foreach ($file in @($After.files)) {
        $afterByPath[([string]$file.root + "\" +
            [string]$file.relative_path)] = $file
    }
    $allPaths = @($beforeByPath.Keys + $afterByPath.Keys) |
        Sort-Object -Unique
    $changes = [Collections.Generic.List[object]]::new()
    foreach ($path in $allPaths) {
        $beforeFile = $beforeByPath[$path]
        $afterFile = $afterByPath[$path]
        if ($null -eq $beforeFile) {
            $changes.Add([ordered]@{
                path = $path
                disposition = "added"
                before_sha256 = $null
                after_sha256 = $afterFile.sha256
            })
        } elseif ($null -eq $afterFile) {
            $changes.Add([ordered]@{
                path = $path
                disposition = "removed"
                before_sha256 = $beforeFile.sha256
                after_sha256 = $null
            })
        } elseif ([string]$beforeFile.sha256 -cne [string]$afterFile.sha256) {
            $changes.Add([ordered]@{
                path = $path
                disposition = "changed"
                before_sha256 = $beforeFile.sha256
                after_sha256 = $afterFile.sha256
            })
        }
    }
    return @($changes)
}

function Get-SettledObservation {
    param(
        [Parameter(Mandatory = $true)][string]$ScreenId,
        [Parameter(Mandatory = $true)][string]$Label,
        [string]$TransitionalSource = ""
    )

    $framePath = Join-Path $resolvedOutput "$Label.bmp"
    $clock = [Diagnostics.Stopwatch]::StartNew()
    $arguments = @{
        Context = $context
        ScreenId = $ScreenId
        FramePath = $framePath
        LatencyClock = $clock
    }
    if (-not [string]::IsNullOrWhiteSpace($TransitionalSource)) {
        $arguments.TransitionalSourceScreen = $TransitionalSource
    }
    $observation = Get-SettledNativeMenuObservation @arguments
    $payloadJson = $observation.layout | ConvertTo-Json -Depth 100 -Compress
    $receipt = [ordered]@{
        label = $Label
        screen_id = $ScreenId
        semantic_surface = $observation.semantic_surface
        semantic_generation = $observation.semantic_generation
        layout_generation = $observation.layout_generation
        element_count = $observation.element_count
        layout_sha256 = Get-NativeMenuStringSha256 -Value $payloadJson
        frame_path = $framePath
        frame_sha256 = $observation.frame_sha256
        settlement = $observation.settlement
        tab = $(if ($ScreenId -like "dark_cloud*") {
            Resolve-DarkCloudTab -Layout $observation.layout
        } else { $null })
    }
    $observations.Add($receipt)
    Write-Utf8Json `
        -Path (Join-Path $resolvedOutput "$Label.observation.json") `
        -Value ([ordered]@{
            receipt = $receipt
            layout = $observation.layout
            settlement_trace = $observation.settlement_trace
        })
    return $observation
}

function Resolve-DarkCloudTab {
    param([Parameter(Mandatory = $true)][object]$Layout)

    $tabDefinitions = @(
        [pscustomobject]@{
            name = "recent"
            left = 460.0
            right = 596.0
            text = "recent"
            selected_text_top = 158.0
        },
        [pscustomobject]@{
            name = "online_levels"
            left = 630.0
            right = 936.0
            text = "ONLINE LEVELS"
            selected_text_top = 155.0
        },
        [pscustomobject]@{
            name = "my_levels"
            left = 970.0
            right = 1106.0
            text = "my levels"
            selected_text_top = 158.0
        }
    )
    $elements = @($Layout.elements)
    $measuredMembers = @(
        $elements | Where-Object {
            ([string]$_.kind -ceq "art" -and
                [string]$_.art_id -ceq "UI.13") -or
            ([string]$_.kind -ceq "text" -and
                [string]$_.text -in @(
                    "recent", "ONLINE LEVELS", "my levels"
                ))
        } | ForEach-Object {
            [ordered]@{
                id = [string]$_.id
                kind = [string]$_.kind
                text = [string]$_.text
                art_id = [string]$_.art_id
                rect = @($_.rect)
            }
        }
    )
    $matches = [Collections.Generic.List[string]]::new()
    foreach ($definition in $tabDefinitions) {
        $leftBracket = @(
            $measuredMembers | Where-Object {
                $_.art_id -ceq "UI.13" -and
                @($_.rect).Count -eq 4 -and
                [double]$_.rect[0] -eq $definition.left -and
                [double]$_.rect[1] -eq 128.0
            }
        )
        $rightBracket = @(
            $measuredMembers | Where-Object {
                $_.art_id -ceq "UI.13" -and
                @($_.rect).Count -eq 4 -and
                [double]$_.rect[0] -eq $definition.right -and
                [double]$_.rect[1] -eq 128.0
            }
        )
        $label = @(
            $measuredMembers | Where-Object {
                $_.kind -ceq "text" -and
                $_.text -ceq $definition.text -and
                @($_.rect).Count -eq 4 -and
                [double]$_.rect[1] -eq $definition.selected_text_top
            }
        )
        if (
            $leftBracket.Count -eq 1 -and
            $rightBracket.Count -eq 1 -and
            $label.Count -eq 1
        ) {
            $matches.Add($definition.name)
        }
    }
    if ($matches.Count -ne 1) {
        throw (
            "STOP: dark-cloud tab verification could not resolve exactly " +
            "one selected tab from the measured bracket/text members; " +
            "matches=$($matches.Count)."
        )
    }
    return [ordered]@{
        selected = $matches[0]
        measured_members = $measuredMembers
    }
}

function Invoke-NativeMenuAction {
    param(
        [Parameter(Mandatory = $true)][object]$Source,
        [Parameter(Mandatory = $true)][string]$ActionId,
        [Parameter(Mandatory = $true)][string]$SurfaceId,
        [Parameter(Mandatory = $true)][string]$DestinationScreen,
        [Parameter(Mandatory = $true)][string]$Label
    )

    $machineDestination = $DestinationScreen
    $expectedTab = ""
    if ($DestinationScreen -ceq "dark_cloud_recent") {
        $machineDestination = "dark_cloud_browser"
        $expectedTab = "recent"
    } elseif ($DestinationScreen -ceq "dark_cloud_online_levels") {
        $machineDestination = "dark_cloud_browser"
        $expectedTab = "online_levels"
    } elseif ($DestinationScreen -ceq "dark_cloud_my_levels") {
        $machineDestination = "dark_cloud_browser"
        $expectedTab = "my_levels"
    } elseif ($DestinationScreen -ceq "dark_cloud_menu") {
        $machineDestination = "simple_menu"
    } elseif ($DestinationScreen -ceq "beta_notice") {
        $machineDestination = "dialog"
    }
    $result = Invoke-NativeMenuLua -Context $context -LuaCode @"
local snapshot = sd.ui.get_snapshot()
local measured_surface = tostring(snapshot and snapshot.surface_id or '')
local action = sd.ui.find_action([=[$ActionId]=], measured_surface)
if action == nil then
  error("UI action '$ActionId' is not available on measured surface '" ..
    measured_surface .. "'.")
end
local ok, request = sd.ui.activate_action(
  [=[$ActionId]=], measured_surface)
if not ok then error(tostring(request)) end
return tostring(request) .. '|' .. measured_surface
"@
    $activationParts = @([string]$result.Text -split '\|', 2)
    $requestId = 0
    if (
        $activationParts.Count -ne 2 -or
        -not [int]::TryParse($activationParts[0], [ref]$requestId) -or
        $requestId -le 0) {
        throw "BROKEN: action '$ActionId' returned invalid request '$($result.Text)'."
    }
    $measuredSourceSurface = $activationParts[1]
    $dispatch = Wait-NativeMenuActionDispatch `
        -Context $context `
        -RequestId $requestId `
        -ActionId $ActionId `
        -SourceLayoutGeneration $Source.layout_generation `
        -ExpectedDestinationScreen $machineDestination
    $transitionClock = [Diagnostics.Stopwatch]::StartNew()
    $transitionProbe = $null
    while ($transitionClock.ElapsedMilliseconds -le 45000) {
        $transitionProbe = Get-NativeMenuLayoutProbe `
            -Context $context `
            -ScreenId $machineDestination
        if ($transitionProbe.Status -eq "ready") {
            break
        }
        $measuredTransitionSurface = [string]$transitionProbe.SemanticSurface
        $compatibleCreateTransition = (
            $DestinationScreen -ceq "create_element" -and
            $measuredTransitionSurface -ceq "create"
        ) -or (
            $DestinationScreen -ceq "create_discipline" -and
            $measuredTransitionSurface -in @("create", "create_element")
        )
        if (
            $transitionProbe.Status -eq "wrong_surface" -and
            $measuredTransitionSurface -cne
                [string]$Source.semantic_surface -and
            -not $compatibleCreateTransition
        ) {
            throw [string]$transitionProbe.Detail
        }
        Start-Sleep -Milliseconds 50
    }
    if ($null -eq $transitionProbe -or $transitionProbe.Status -ne "ready") {
        $lastStatus = if ($null -eq $transitionProbe) {
            "absent"
        } else {
            [string]$transitionProbe.Status
        }
        $lastDetail = if ($null -eq $transitionProbe) {
            "no destination probe completed"
        } else {
            [string]$transitionProbe.Detail
        }
        throw (
            "STOP: action '$ActionId' did not reach machine-classified " +
            "destination '$machineDestination' within 45 seconds; " +
            "last_status='$lastStatus' last_detail='$lastDetail'."
        )
    }
    $dispatches.Add([ordered]@{
        label = $Label
        action_id = $ActionId
        declared_surface_id = $SurfaceId
        measured_surface_id = $measuredSourceSurface
        request_id = $requestId
        expected_destination = $DestinationScreen
        machine_destination = $machineDestination
        destination_observed_milliseconds = (
            [long]$transitionClock.ElapsedMilliseconds
        )
        dispatch = $dispatch
    })
    if (
        $DestinationScreen -ceq "beta_notice" -or
        $DestinationScreen -ceq "dialog"
    ) {
        $transientLayout = $transitionProbe.SemanticPayload
        $transient = [pscustomobject]@{
            semantic_surface = [string]$transitionProbe.SemanticSurface
            semantic_generation = [uint64]$transitionProbe.SemanticGeneration
            layout_generation = [uint64]$transitionProbe.SemanticGeneration
            element_count = @($transientLayout.elements).Count
            layout = $transientLayout
        }
        $observations.Add([ordered]@{
            label = $Label
            screen_id = $DestinationScreen
            semantic_surface = $transient.semantic_surface
            semantic_generation = $transient.semantic_generation
            layout_generation = $transient.layout_generation
            element_count = $transient.element_count
            layout_sha256 = Get-NativeMenuStringSha256 -Value (
                $transientLayout | ConvertTo-Json -Depth 100 -Compress
            )
            frame_path = $null
            frame_sha256 = $null
            settlement = (
                "navigation-only dialog observation; not golden input"
            )
            tab = $null
        })
        return $transient
    }
    $settled = Get-SettledObservation `
        -ScreenId $machineDestination `
        -Label $Label
    if (-not [string]::IsNullOrWhiteSpace($expectedTab)) {
        $measuredTab = [string](
            Resolve-DarkCloudTab -Layout $settled.layout
        ).selected
        if ($measuredTab -cne $expectedTab) {
            throw (
                "STOP: dark-cloud tab verification rejected action " +
                "'$ActionId': expected '$expectedTab', measured " +
                "'$measuredTab' from the six geometry-bearing members."
            )
        }
    }
    return $settled
}

function Invoke-KeyAndSettle {
    param(
        [Parameter(Mandatory = $true)][object]$Source,
        [Parameter(Mandatory = $true)][string]$Key,
        [Parameter(Mandatory = $true)][string]$DestinationScreen,
        [Parameter(Mandatory = $true)][string]$Label
    )

    $result = Invoke-NativeMenuLua -Context $context -LuaCode @"
local ok, message = sd.input.press_key([=[$Key]=])
if not ok then error(tostring(message)) end
return 'key'
"@
    $dispatches.Add([ordered]@{
        label = $Label
        action_id = "key:$Key"
        surface_id = $Source.semantic_surface
        request_id = $null
        expected_destination = $DestinationScreen
        dispatch = [string]$result.Text
    })
    return Get-SettledObservation `
        -ScreenId $DestinationScreen `
        -Label $Label
}

function Dismiss-StockBetaOverlay {
    $probe = Get-NativeMenuLayoutProbe `
        -Context $context `
        -ScreenId "control_scheme_picker"
    if (
        $probe.Status -eq "wrong_surface" -and
        [string]$probe.SemanticSurface -cne "dialog"
    ) {
        return [string]$probe.SemanticSurface
    }
    if (
        $probe.Status -eq "wrong_surface" -and
        [string]$probe.SemanticSurface -ceq "dialog"
    ) {
        $probe = Get-NativeMenuLayoutProbe `
            -Context $context `
            -ScreenId "dialog"
    }
    if ($probe.Status -ne "ready") {
        throw "BROKEN: initial picker probe was not runnable: $($probe.Detail)"
    }
    $allPlates = @(
        $probe.SemanticPayload.elements | Where-Object {
            [string]$_.art_id -ceq "UI.101" -and
            [bool]$_.visible -and
            @($_.rect).Count -eq 4 -and
            [double]$_.rect[2] -gt [double]$_.rect[0] -and
            [double]$_.rect[3] -gt [double]$_.rect[1]
        }
    )
    if ($allPlates.Count -eq 0) {
        return [string]$probe.SemanticSurface
    }
    $maximumDrawOrder = @(
        $allPlates | ForEach-Object { [int64]$_.draw_order }
    ) | Measure-Object -Maximum | Select-Object -ExpandProperty Maximum
    $plates = @(
        $allPlates | Where-Object {
            [int64]$_.draw_order -eq [int64]$maximumDrawOrder
        }
    )
    if ($plates.Count -ne 1) {
        throw (
            "STOP: stock beta overlay dismissal resolved $($plates.Count) " +
            "top-draw live UI.101 plate candidates from " +
            "$($allPlates.Count) total; refusing ambiguity."
        )
    }
    $rect = @($plates[0].rect)
    $clientX = ([double]$rect[0] + [double]$rect[2]) / 2.0
    $clientY = ([double]$rect[1] + [double]$rect[3]) / 2.0
    & (Join-Path $resolvedRoot "scripts\Invoke-ExactProcessClientClick.ps1") `
        -Instance $Instance `
        -ProcessId $ProcessId `
        -ClientX $clientX `
        -ClientY $clientY |
        Out-Null
    $dispatches.Add([ordered]@{
        label = "dismiss_stock_beta_overlay"
        action_id = "live_measured_click"
        surface_id = "control_scheme_picker"
        request_id = $null
        expected_destination = "control_scheme_picker"
        dispatch = [ordered]@{
            element_id = [string]$plates[0].id
            art_id = [string]$plates[0].art_id
            rect = $rect
            client_point = @($clientX, $clientY)
        }
    })
    return "dismissed"
}

function Reach-MainMenu {
    $initialDisposition = Dismiss-StockBetaOverlay
    $surfaceClock = [Diagnostics.Stopwatch]::StartNew()
    $underlaySurface = $initialDisposition
    while (
        $underlaySurface -ceq "dismissed" -and
        $surfaceClock.ElapsedMilliseconds -le 10000
    ) {
        $surfaceProbe = Get-NativeMenuLayoutProbe `
            -Context $context `
            -ScreenId "control_scheme_picker"
        if ($surfaceProbe.Status -eq "ready") {
            $underlaySurface = "control_scheme_picker"
        } elseif (
            $surfaceProbe.Status -eq "wrong_surface" -and
            [string]$surfaceProbe.SemanticSurface -cne "dialog"
        ) {
            $underlaySurface = [string]$surfaceProbe.SemanticSurface
        } else {
            Start-Sleep -Milliseconds 100
        }
    }
    if ($underlaySurface -ceq "main_menu") {
        return Get-SettledObservation `
            -ScreenId "main_menu" `
            -Label "route-01-main-menu"
    }
    if ($underlaySurface -cne "control_scheme_picker") {
        throw (
            "STOP: beta-dialog underlay resolved unexpected surface " +
            "'$underlaySurface'."
        )
    }
    $picker = Get-SettledObservation `
        -ScreenId "control_scheme_picker" `
        -Label "route-01-picker"
    $element = Invoke-NativeMenuAction `
        -Source $picker `
        -ActionId "control_scheme_picker.select_wasd" `
        -SurfaceId "control_scheme_picker" `
        -DestinationScreen "create_element" `
        -Label "route-02-create-element"
    $discipline = Invoke-NativeMenuAction `
        -Source $element `
        -ActionId "create.select_element_fire" `
        -SurfaceId "create" `
        -DestinationScreen "create_discipline" `
        -Label "route-03-create-discipline"

    $result = Invoke-NativeMenuLua -Context $context -LuaCode @'
local ok, request = sd.ui.activate_action('create.select_discipline_mind', 'create')
if not ok then error(tostring(request)) end
return tostring(request)
'@
    $requestId = 0
    if (-not [int]::TryParse([string]$result.Text, [ref]$requestId) -or
        $requestId -le 0) {
        throw "BROKEN: create discipline action returned an invalid request."
    }
    $sceneClock = [Diagnostics.Stopwatch]::StartNew()
    $scene = ""
    while ($sceneClock.ElapsedMilliseconds -le 30000) {
        $scene = (Invoke-NativeMenuLua -Context $context -LuaCode @'
local value = sd.world.get_scene()
return tostring(value and value.name or '')
'@).Text.Trim()
        if ($scene -ceq "hub") {
            break
        }
        Start-Sleep -Milliseconds 100
    }
    if ($scene -cne "hub") {
        throw "STOP: create route did not reach the hub within 30 seconds."
    }
    $dispatches.Add([ordered]@{
        label = "route-04-create-to-hub"
        action_id = "create.select_discipline_mind"
        surface_id = "create"
        request_id = $requestId
        expected_destination = "hub"
        dispatch = "scene=hub"
    })
    Start-Sleep -Milliseconds 500
    $pause = Invoke-KeyAndSettle `
        -Source $discipline `
        -Key "ESCAPE" `
        -DestinationScreen "pause_menu" `
        -Label "route-05-pause"
    $dialog = Invoke-NativeMenuAction `
        -Source $pause `
        -ActionId "pause_menu.leave_game" `
        -SurfaceId "pause_menu" `
        -DestinationScreen "dialog" `
        -Label "route-06-leave-dialog"
    return Invoke-NativeMenuAction `
        -Source $dialog `
        -ActionId "dialog.primary" `
        -SurfaceId "dialog" `
        -DestinationScreen "main_menu" `
        -Label "route-07-main-menu"
}

if ($Mode -ceq "ResumeFromPause") {
    Save-DurableStateSnapshot -Label "00-resume-pause"
    $pauseProbe = Get-NativeMenuLayoutProbe `
        -Context $context `
        -ScreenId "simple_menu"
    if (
        $pauseProbe.Status -eq "wrong_surface" -and
        [string]$pauseProbe.SemanticSurface -ceq "pause_menu"
    ) {
        $pauseProbe = Get-NativeMenuLayoutProbe `
            -Context $context `
            -ScreenId "pause_menu"
    }
    if ($pauseProbe.Status -ne "ready") {
        throw (
            "STOP: pause-resume expected machine-classified pause surface, " +
            "got status '$($pauseProbe.Status)' surface " +
            "'$($pauseProbe.SemanticSurface)'."
        )
    }
    $pause = [pscustomobject]@{
        semantic_surface = [string]$pauseProbe.SemanticSurface
        semantic_generation = [uint64]$pauseProbe.SemanticGeneration
        layout_generation = [uint64]$pauseProbe.SemanticGeneration
        element_count = @($pauseProbe.SemanticPayload.elements).Count
        layout = $pauseProbe.SemanticPayload
    }
    $dialog = Invoke-NativeMenuAction `
        -Source $pause `
        -ActionId "pause_menu.leave_game" `
        -SurfaceId "measured-current-surface" `
        -DestinationScreen "dialog" `
        -Label "01-leave-dialog"
    $main = Invoke-NativeMenuAction `
        -Source $dialog `
        -ActionId "dialog.primary" `
        -SurfaceId "measured-current-surface" `
        -DestinationScreen "main_menu" `
        -Label "02-main-menu"
    Save-DurableStateSnapshot -Label "02-main-menu"
    $browser = Invoke-NativeMenuAction `
        -Source $main `
        -ActionId "main_menu.explore_dark_cloud" `
        -SurfaceId "measured-current-surface" `
        -DestinationScreen "dark_cloud_browser" `
        -Label "03-browser-entry"
    Save-DurableStateSnapshot -Label "03-browser-entry"
    $finalBrowser = $browser
} elseif (
    $Mode -ceq "ResumeFromBeta" -or
    $Mode -ceq "ResumeFromDialog"
) {
    Save-DurableStateSnapshot -Label "00-resume-beta-notice"
    $betaProbe = Get-NativeMenuLayoutProbe `
        -Context $context `
        -ScreenId "dialog"
    if ($betaProbe.Status -ne "ready") {
        throw (
            "STOP: beta-resume expected machine-classified dialog, got " +
            "status '$($betaProbe.Status)' surface " +
            "'$($betaProbe.SemanticSurface)'."
        )
    }
    $beta = [pscustomobject]@{
        semantic_surface = "dialog"
        semantic_generation = [uint64]$betaProbe.SemanticGeneration
        layout_generation = [uint64]$betaProbe.SemanticGeneration
        element_count = @($betaProbe.SemanticPayload.elements).Count
        layout = $betaProbe.SemanticPayload
    }
    $main = Invoke-NativeMenuAction `
        -Source $beta `
        -ActionId "dialog.primary" `
        -SurfaceId "dialog" `
        -DestinationScreen "main_menu" `
        -Label "01-main-menu-after-beta"
    Save-DurableStateSnapshot -Label "01-main-menu-after-beta"
    $browser = Invoke-NativeMenuAction `
        -Source $main `
        -ActionId "main_menu.explore_dark_cloud" `
        -SurfaceId "main_menu" `
        -DestinationScreen "dark_cloud_browser" `
        -Label "02-browser-reentry"
    Save-DurableStateSnapshot -Label "02-browser-reentry"
    $finalBrowser = $browser
} else {
    Save-DurableStateSnapshot -Label "00-process-start"
    $main = Reach-MainMenu
    Save-DurableStateSnapshot -Label "01-main-menu-before-entry"
    $browser = Invoke-NativeMenuAction `
        -Source $main `
        -ActionId "main_menu.explore_dark_cloud" `
        -SurfaceId "main_menu" `
        -DestinationScreen "dark_cloud_browser" `
        -Label "02-browser-entry"
    Save-DurableStateSnapshot -Label "02-browser-entry"
    $finalBrowser = $browser
}

if ($Mode -ceq "Lifecycle") {
    $entryTab = [string](Resolve-DarkCloudTab -Layout $browser.layout).selected
    if ($entryTab -ceq "recent") {
        $targetTab = "online_levels"
        $targetScreen = "dark_cloud_online_levels"
        $targetAction = "dark_cloud_browser.online_levels"
    } elseif ($entryTab -ceq "online_levels") {
        $targetTab = "recent"
        $targetScreen = "dark_cloud_recent"
        $targetAction = "dark_cloud_browser.recent"
    } else {
        throw (
            "STOP: lifecycle diagnosis expected Recent or Online Levels at " +
            "entry, measured '$entryTab'."
        )
    }
    $changed = Invoke-NativeMenuAction `
        -Source $browser `
        -ActionId $targetAction `
        -SurfaceId "dark_cloud_browser" `
        -DestinationScreen $targetScreen `
        -Label "03-tab-changed-to-$targetTab"
    Save-DurableStateSnapshot -Label "03-tab-changed-to-$targetTab"
    $menu = Invoke-NativeMenuAction `
        -Source $changed `
        -ActionId "dark_cloud_browser.menu" `
        -SurfaceId "dark_cloud_browser" `
        -DestinationScreen "dark_cloud_menu" `
        -Label "04-dark-cloud-menu"
    $beta = Invoke-NativeMenuAction `
        -Source $menu `
        -ActionId "profile.main_menu" `
        -SurfaceId "simple_menu" `
        -DestinationScreen "beta_notice" `
        -Label "05-beta-notice"
    $mainAgain = Invoke-NativeMenuAction `
        -Source $beta `
        -ActionId "dialog.primary" `
        -SurfaceId "dialog" `
        -DestinationScreen "main_menu" `
        -Label "06-main-menu-reentry"
    Save-DurableStateSnapshot -Label "06-main-menu-reentry"
    $browserAgain = Invoke-NativeMenuAction `
        -Source $mainAgain `
        -ActionId "main_menu.explore_dark_cloud" `
        -SurfaceId "main_menu" `
        -DestinationScreen "dark_cloud_browser" `
        -Label "07-browser-reentry"
    $finalBrowser = $browserAgain
    Save-DurableStateSnapshot -Label "07-browser-reentry"
}

$diffs = [Collections.Generic.List[object]]::new()
for ($index = 1; $index -lt $stateSnapshots.Count; $index += 1) {
    $before = $stateSnapshots[$index - 1]
    $after = $stateSnapshots[$index]
    $diffs.Add([ordered]@{
        before = $before.label
        after = $after.label
        dark_cloud_viewing_levels_before = $before.dark_cloud_viewing_levels
        dark_cloud_viewing_levels_after = $after.dark_cloud_viewing_levels
        file_changes = @(Get-StateDiff -Before $before -After $after)
    })
}
$audit = [ordered]@{
    schema = "solomon-dark-dark-cloud-entry-state-diagnosis-v1"
    instance = $Instance
    process_id = $ProcessId
    mode = $Mode
    source = $context.Source
    captured_at_utc = [DateTime]::UtcNow.ToString("o")
    observations = @($observations)
    state_snapshots = @(
        $stateSnapshots | ForEach-Object {
            [ordered]@{
                label = $_.label
                path = $_.path
                sha256 = $_.sha256
                dark_cloud_viewing_levels = $_.dark_cloud_viewing_levels
            }
        }
    )
    state_diffs = @($diffs)
    dispatches = @($dispatches)
}
$auditPath = Join-Path $resolvedOutput "dark-cloud-entry-state-diagnosis.json"
Write-Utf8Json -Path $auditPath -Value $audit
[pscustomobject]@{
    success = $true
    instance = $Instance
    process_id = $ProcessId
    mode = $Mode
    entry_tab = [string](Resolve-DarkCloudTab -Layout $browser.layout).selected
    final_tab = [string](
        Resolve-DarkCloudTab -Layout $finalBrowser.layout
    ).selected
    output = $auditPath
} | ConvertTo-Json -Compress
