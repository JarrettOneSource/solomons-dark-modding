param(
    [string]$Preset = "",
    [ValidateSet("None", "Search", "Sort", "Recent", "OnlineLevels", "MyLevels")]
    [string]$BrowserAction = "None",
    [string]$ScreenshotPath = "",
    [ValidateSet("screen", "window")]
    [string]$CaptureMethod = "screen",
    [ValidateRange(10, 300)]
    [int]$CompletionTimeoutSeconds = 90,
    [switch]$KeepRunning
)

$ErrorActionPreference = "Stop"

$replayScript = Join-Path $PSScriptRoot "Replay-UiSandbox.ps1"
$presetByBrowserAction = @{
    None         = "title_menu_to_explore_dark_cloud"
    Search       = "title_menu_to_explore_dark_cloud_search"
    Sort         = "title_menu_to_explore_dark_cloud_sort"
    Recent       = "title_menu_to_explore_dark_cloud_recent"
    OnlineLevels = "title_menu_to_explore_dark_cloud_online_levels"
    MyLevels     = "title_menu_to_explore_dark_cloud_my_levels"
}

if (-not (Test-Path -LiteralPath $replayScript)) {
    throw "Replay script not found: $replayScript"
}

$resolvedPreset = $Preset
if ([string]::IsNullOrWhiteSpace($resolvedPreset)) {
    $resolvedPreset = $presetByBrowserAction[$BrowserAction]
}

if ([string]::IsNullOrWhiteSpace($resolvedPreset)) {
    throw "Unable to resolve a sandbox preset for BrowserAction '$BrowserAction'."
}

$invokeArguments = @{
    Preset = $resolvedPreset
    CompletionTimeoutSeconds = $CompletionTimeoutSeconds
}

if (-not [string]::IsNullOrWhiteSpace($ScreenshotPath)) {
    $invokeArguments.ScreenshotPath = $ScreenshotPath
    $invokeArguments.CaptureMethod = $CaptureMethod
}

if ($KeepRunning) {
    $invokeArguments.KeepRunning = $true
}

& $replayScript @invokeArguments
exit $LASTEXITCODE
