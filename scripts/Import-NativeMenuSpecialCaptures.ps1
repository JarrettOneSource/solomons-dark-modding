[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$LoaderPrimaryCapturePath,

    [Parameter(Mandatory = $true)]
    [string]$LoaderConfirmationCapturePath,

    [Parameter(Mandatory = $true)]
    [string]$LoadingPrimaryCapturePath,

    [Parameter(Mandatory = $true)]
    [string]$LoadingConfirmationCapturePath,

    [Parameter(Mandatory = $true)]
    [string]$OutputRoot
)

Set-StrictMode -Version 3.0
$ErrorActionPreference = "Stop"

$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).ProviderPath
$importer = Join-Path $root "tools\import_native_menu_special_captures_v25.py"
$inputs = @(
    $LoaderPrimaryCapturePath,
    $LoaderConfirmationCapturePath,
    $LoadingPrimaryCapturePath,
    $LoadingConfirmationCapturePath
)
foreach ($inputPath in $inputs) {
    if (-not (Test-Path -LiteralPath $inputPath -PathType Leaf)) {
        throw "A required native-menu special capture is missing: $inputPath"
    }
}
if (-not (Test-Path -LiteralPath $importer -PathType Leaf)) {
    throw "The Settlement v2.5 special-capture importer is missing."
}

$python = Get-Command py.exe -ErrorAction SilentlyContinue
if ($null -eq $python) {
    throw "py.exe is required to import native-menu special captures."
}
$probe = @(
    & py.exe -3 -c `
        "import PIL; print('native-menu-special-import-ready')" 2>&1
)
if ($LASTEXITCODE -ne 0 -or ($probe -join "`n") -notmatch
    "native-menu-special-import-ready") {
    throw "py.exe exists but cannot run the Settlement v2.5 special importer."
}

$result = @(
    & py.exe -3 $importer `
        --repo-root $root `
        --loader-primary $LoaderPrimaryCapturePath `
        --loader-confirmation $LoaderConfirmationCapturePath `
        --loading-primary $LoadingPrimaryCapturePath `
        --loading-confirmation $LoadingConfirmationCapturePath `
        --output-root $OutputRoot 2>&1
)
if ($LASTEXITCODE -ne 0) {
    throw (
        "Settlement v2.5 special-capture import failed: " +
        (($result | ForEach-Object { [string]$_ }) -join "`n")
    )
}
$result | ForEach-Object { Write-Output ([string]$_) }
