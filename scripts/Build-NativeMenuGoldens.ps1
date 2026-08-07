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
if ([string]::IsNullOrWhiteSpace($OutputPath)) {
    $OutputPath = Join-Path $fixtureRoot "menu-goldens.json"
}
$outputPath = [IO.Path]::GetFullPath($OutputPath)
$navigationPath = [IO.Path]::GetFullPath($NavigationRecordingPath)
$builder = Join-Path $root "tools\build_native_menu_goldens_v25.py"

if (-not (Test-Path -LiteralPath $navigationPath -PathType Leaf)) {
    throw "The resolved Settlement v2.9 navigation recording is missing."
}
if (-not (Test-Path -LiteralPath $builder -PathType Leaf)) {
    throw "The Settlement v2.9 aggregate builder is missing."
}

$python = Get-Command py.exe -ErrorAction SilentlyContinue
if ($null -eq $python) {
    throw "py.exe is required to build the Settlement v2.9 aggregate."
}
$probe = @(& py.exe -3 -c "print('native-menu-golden-python-ready')" 2>&1)
if ($LASTEXITCODE -ne 0 -or ($probe -join "`n") -notmatch "native-menu-golden-python-ready") {
    throw "py.exe exists but cannot run the Settlement v2.9 aggregate builder."
}

$result = @(
    & py.exe -3 $builder `
        --repo-root $root `
        --fixture-root $fixtureRoot `
        --navigation-recording $navigationPath `
        --output $outputPath 2>&1
)
if ($LASTEXITCODE -ne 0) {
    throw (
        "Settlement v2.9 menu-golden build failed: " +
        (($result | ForEach-Object { [string]$_ }) -join "`n")
    )
}
$result | ForEach-Object { Write-Output ([string]$_) }
