[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9._-]{0,47}$')]
    [string]$Instance,

    [Parameter(Mandatory = $true)]
    [ValidateRange(1, [int]::MaxValue)]
    [int]$ProcessId,

    [Parameter(Mandatory = $true)]
    [string]$OutputPath,

    [Parameter(Mandatory = $true)]
    [string]$EvidenceReceiptPath
)

Set-StrictMode -Version 3.0
$ErrorActionPreference = "Stop"

$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).ProviderPath
. (Join-Path $PSScriptRoot "NativeMenuCaptureSupport.ps1")

$instanceRoot = Join-Path $root (
    "runtime\instances\" + $Instance.ToLowerInvariant()
)
$expectedExecutable = [IO.Path]::GetFullPath(
    (Join-Path $instanceRoot "stage\SolomonDark.exe")
)
if (-not (Test-NativeMenuOwnedProcess `
    -ProcessId $ProcessId `
    -ExpectedExecutable $expectedExecutable)) {
    throw (
        "BROKEN: profile-state baseline PID $ProcessId does not own the " +
        "exact '$Instance' staged executable."
    )
}
$trackedChanges = Invoke-NativeMenuGit `
    -Root $root `
    -Arguments @("status", "--porcelain", "--untracked-files=no")
if (-not [string]::IsNullOrWhiteSpace($trackedChanges)) {
    throw (
        "BROKEN: profile-state baseline generation requires a clean tracked " +
        "tree so its machine-derived commit identifies the launcher."
    )
}
$baseCommitSha = Invoke-NativeMenuGit `
    -Root $root `
    -Arguments @("rev-parse", "HEAD")
$sourceTreeSha = Invoke-NativeMenuGit `
    -Root $root `
    -Arguments @("rev-parse", "HEAD^{tree}")
if ($baseCommitSha -notmatch '^[0-9a-f]{40}$' -or
    $sourceTreeSha -notmatch '^[0-9a-f]{40}$') {
    throw "BROKEN: profile-state baseline could not derive commit/tree provenance."
}

$receiptPath = Join-Path $instanceRoot (
    "stage\.sdmod\native-menu-profile-state.json"
)
if (-not (Test-Path -LiteralPath $receiptPath -PathType Leaf)) {
    throw "BROKEN: fresh launch has no native-menu profile-state receipt."
}
try {
    $receipt = Get-Content -LiteralPath $receiptPath -Raw | ConvertFrom-Json
} catch {
    throw "BROKEN: fresh launch profile-state receipt is not valid JSON."
}
if (
    [string]$receipt.schema -cne
        "solomon-dark-native-menu-profile-state-v1" -or
    [string]$receipt.profile_state_identity_sha256 -notmatch
        '^[0-9a-f]{64}$' -or
    [string]$receipt.baseline_mode -cne "fresh_install" -or
    [bool]$receipt.source_sandbox_excluded -ne $true -or
    [bool]$receipt.retail_appdata_seeded -ne $false -or
    @($receipt.files).Count -ne 0
) {
    throw (
        "STOP: profile-state baseline candidate is not a pristine " +
        "fresh-install state with no durable files."
    )
}

$loaderPath = Join-Path $root "dist\launcher\SolomonDarkModLoader.dll"
if (-not (Test-Path -LiteralPath $loaderPath -PathType Leaf)) {
    throw "BROKEN: profile-state baseline cannot hash the injected loader."
}
$gameSha256 = (
    Get-FileHash -LiteralPath $expectedExecutable -Algorithm SHA256
).Hash.ToLowerInvariant()
$loaderSha256 = (
    Get-FileHash -LiteralPath $loaderPath -Algorithm SHA256
).Hash.ToLowerInvariant()
$compatibilityPath = Join-Path $instanceRoot (
    "stage\.sdmod\multiplayer-compatibility.json"
)
$compatibility = Get-Content -LiteralPath $compatibilityPath -Raw |
    ConvertFrom-Json
if (
    [string]$compatibility.compatibility.gameExecutable.sha256 -cne
        $gameSha256 -or
    [string]$compatibility.compatibility.loader.sha256 -cne $loaderSha256
) {
    throw (
        "BROKEN: profile-state baseline stage receipt does not identify " +
        "the exact hashed game and injected loader."
    )
}

$evidenceItemPath = [IO.Path]::GetFullPath($EvidenceReceiptPath)
if (Test-Path -LiteralPath $evidenceItemPath) {
    throw "EvidenceReceiptPath already exists; refusing ambiguous baseline evidence."
}
[IO.Directory]::CreateDirectory(
    (Split-Path -Parent $evidenceItemPath)
) | Out-Null
Copy-Item -LiteralPath $receiptPath -Destination $evidenceItemPath
$evidenceItem = Get-Item -LiteralPath $evidenceItemPath
$evidenceSha256 = (
    Get-FileHash -LiteralPath $evidenceItem.FullName -Algorithm SHA256
).Hash.ToLowerInvariant()

$value = [ordered]@{
    schema = "solomon-dark-native-menu-profile-state-baseline-v1"
    header = [ordered]@{
        label = "menufix pristine durable-state baseline"
        instance = $Instance
        process_id = $ProcessId
        source = [ordered]@{
            base_commit_sha = $baseCommitSha
            source_tree_sha = $sourceTreeSha
            capture_tree = "exact committed tree at base_commit_sha"
            game_executable_sha256 = $gameSha256
            loader_dll_sha256 = $loaderSha256
            profile_state_identity_sha256 = (
                [string]$receipt.profile_state_identity_sha256
            )
        }
        recorded_live = $true
        captured_at_utc = [DateTime]::UtcNow.ToString("o")
        launch_receipt = [ordered]@{
            evidence_filename = $evidenceItem.Name
            sha256 = $evidenceSha256
            bytes = $evidenceItem.Length
        }
        corrective = (
            "Case A durable-state pin: source sandbox excluded, retail " +
            "APPDATA unseeded, no profile files"
        )
    }
    profile_state = [ordered]@{
        identity_schema = (
            "solomon-dark-native-menu-profile-state-input-v1"
        )
        profile_state_identity_sha256 = (
            [string]$receipt.profile_state_identity_sha256
        )
        baseline_mode = [string]$receipt.baseline_mode
        source_sandbox_excluded = [bool]$receipt.source_sandbox_excluded
        retail_appdata_seeded = [bool]$receipt.retail_appdata_seeded
        files = @($receipt.files)
    }
}

$outputItemPath = [IO.Path]::GetFullPath($OutputPath)
if (Test-Path -LiteralPath $outputItemPath) {
    throw "OutputPath already exists; refusing ambiguous profile-state baseline."
}
[IO.Directory]::CreateDirectory(
    (Split-Path -Parent $outputItemPath)
) | Out-Null
$temporaryPath = $outputItemPath + ".menufix.tmp"
try {
    [IO.File]::WriteAllText(
        $temporaryPath,
        ($value | ConvertTo-Json -Depth 20) + "`n",
        [Text.UTF8Encoding]::new($false)
    )
    [IO.File]::Move($temporaryPath, $outputItemPath)
} finally {
    if (Test-Path -LiteralPath $temporaryPath -PathType Leaf) {
        Remove-Item -LiteralPath $temporaryPath -Force
    }
}

$outputItem = Get-Item -LiteralPath $outputItemPath
[pscustomobject]@{
    success = $true
    profile_state_identity_sha256 = (
        [string]$receipt.profile_state_identity_sha256
    )
    baseline = $outputItem.FullName
    baseline_sha256 = (
        Get-FileHash -LiteralPath $outputItem.FullName -Algorithm SHA256
    ).Hash.ToLowerInvariant()
    evidence_receipt = $evidenceItem.FullName
    evidence_sha256 = $evidenceSha256
} | ConvertTo-Json -Compress
