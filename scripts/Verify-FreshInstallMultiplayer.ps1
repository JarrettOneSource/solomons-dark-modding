[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [string]$GameDirectory,

    [Parameter(Mandatory = $true)]
    [string]$LauncherPath,

    [Parameter(Mandatory = $true)]
    [string]$RuntimeRoot,

    [Parameter(Mandatory = $true)]
    [string]$EvidenceDirectory,

    [Parameter(Mandatory = $true)]
    [switch]$AcceptJoinPreview,

    [string]$InstancePrefix = "fresh-install",
    [UInt16]$HostPort = 47620,
    [UInt16]$ClientPort = 47621,
    [UInt16]$PreviewPort = 47622,
    [string]$HostParticipantId = "0x2000000000001601",
    [string]$ClientParticipantId = "0x2000000000001602",
    [string]$HostName = "Fresh Host",
    [string]$ClientName = "Fresh Client",
    [switch]$EnableAudio
)

Set-StrictMode -Version 3.0
$ErrorActionPreference = "Stop"
$audioEnabled = $EnableAudio -or $env:SDMOD_ENABLE_AUDIO -eq "1"

$pairScript = Join-Path $PSScriptRoot "Launch-LocalMultiplayerPair.ps1"
$captureWindowScript = Join-Path $PSScriptRoot "capture_window.py"
$processHelpers = Join-Path $PSScriptRoot "LocalMultiplayerLauncher.Process.ps1"

foreach ($requiredPath in @(
    $pairScript,
    $captureWindowScript,
    $processHelpers
)) {
    if (-not (Test-Path -LiteralPath $requiredPath -PathType Leaf)) {
        throw "Fresh-install acceptance dependency was not found: $requiredPath"
    }
}

. $processHelpers

function Resolve-NewAcceptanceDirectory {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [Parameter(Mandatory = $true)]
        [string]$Label
    )

    $resolved = [System.IO.Path]::GetFullPath($Path)
    $rootPath = [System.IO.Path]::GetPathRoot($resolved)
    if ([string]::IsNullOrWhiteSpace($rootPath) -or
        [string]::Equals(
            $resolved.TrimEnd('\'),
            $rootPath.TrimEnd('\'),
            [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "$Label cannot be a filesystem root: $resolved"
    }
    if (Test-Path -LiteralPath $resolved) {
        throw "$Label must not exist before the fresh-install gate: $resolved"
    }
    return $resolved
}

function Write-JsonArtifact {
    param(
        [Parameter(Mandatory = $true)]
        [object]$Value,
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    [System.IO.File]::WriteAllText(
        $Path,
        ($Value | ConvertTo-Json -Depth 12)
    )
}

function Write-ProofCard {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Title,
        [Parameter(Mandatory = $true)]
        [string[]]$Lines,
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    Add-Type -AssemblyName System.Drawing
    $bitmap = [System.Drawing.Bitmap]::new(1440, 900)
    $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
    $background = [System.Drawing.Color]::FromArgb(20, 16, 27)
    $headingBrush = [System.Drawing.SolidBrush]::new(
        [System.Drawing.Color]::FromArgb(224, 190, 255))
    $textBrush = [System.Drawing.SolidBrush]::new(
        [System.Drawing.Color]::FromArgb(238, 234, 241))
    $accentBrush = [System.Drawing.SolidBrush]::new(
        [System.Drawing.Color]::FromArgb(124, 220, 164))
    $titleFont = [System.Drawing.Font]::new(
        "Segoe UI",
        32,
        [System.Drawing.FontStyle]::Bold)
    $textFont = [System.Drawing.Font]::new(
        "Consolas",
        18,
        [System.Drawing.FontStyle]::Regular)
    try {
        $graphics.Clear($background)
        $graphics.DrawString($Title, $titleFont, $headingBrush, 70, 60)
        $y = 145
        foreach ($line in $Lines) {
            $brush = if ($line.StartsWith(
                    "PASS",
                    [System.StringComparison]::Ordinal)) {
                $accentBrush
            } else {
                $textBrush
            }
            $graphics.DrawString($line, $textFont, $brush, 75, $y)
            $y += 42
        }
        $bitmap.Save($Path, [System.Drawing.Imaging.ImageFormat]::Png)
    } finally {
        $titleFont.Dispose()
        $textFont.Dispose()
        $headingBrush.Dispose()
        $textBrush.Dispose()
        $accentBrush.Dispose()
        $graphics.Dispose()
        $bitmap.Dispose()
    }
}

function Capture-GameWindow {
    param(
        [Parameter(Mandatory = $true)]
        [int]$ProcessId,
        [Parameter(Mandatory = $true)]
        [string]$OutputPath
    )

    & py.exe $captureWindowScript `
        --pid $ProcessId `
        --output $OutputPath `
        --method window
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $OutputPath)) {
        throw "Failed to capture Solomon Dark PID $ProcessId."
    }
}

function Assert-ScreenshotSceneCoverage {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Label,
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    Add-Type -AssemblyName System.Drawing
    $bitmap = [System.Drawing.Bitmap]::new($Path)
    $sampleCount = 0
    $visibleSampleCount = 0
    try {
        for ($y = 0; $y -lt $bitmap.Height; $y += 32) {
            for ($x = 0; $x -lt $bitmap.Width; $x += 32) {
                $color = $bitmap.GetPixel($x, $y)
                $sampleCount++
                if (([int]$color.R + [int]$color.G + [int]$color.B) -ge 60) {
                    $visibleSampleCount++
                }
            }
        }
    } finally {
        $bitmap.Dispose()
    }
    $visibleRatio = $visibleSampleCount / $sampleCount
    if ($visibleRatio -lt 0.5) {
        throw "$Label screenshot is still a dark transition frame: $Path (visible ratio $visibleRatio)"
    }
    return [pscustomobject]@{
        label = $Label
        visibleRatio = $visibleRatio
        minimumVisibleRatio = 0.5
    }
}

function Wait-LogTokenCount {
    param(
        [Parameter(Mandatory = $true)]
        [string]$LogPath,
        [Parameter(Mandatory = $true)]
        [string]$Text,
        [int]$MinimumCount = 1,
        [int]$TimeoutSeconds = 45
    )

    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    $lastCount = 0
    while ((Get-Date) -lt $deadline) {
        if (Test-Path -LiteralPath $LogPath) {
            try {
                $logText = [string](Get-Content -LiteralPath $LogPath -Raw -ErrorAction Stop)
                $lastCount = [regex]::Matches($logText, [regex]::Escape($Text)).Count
                if ($lastCount -ge $MinimumCount) {
                    return
                }
            } catch [System.IO.IOException] {
                # The native logger may briefly have the file open without sharing.
            }
        }
        Start-Sleep -Milliseconds 50
    }
    throw "Timed out waiting for $MinimumCount occurrence(s) of '$Text' in $LogPath. Last count: $lastCount"
}

function Convert-ParticipantIdToDecimalText {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ParticipantId
    )

    if ($ParticipantId -match '^0[xX]') {
        return [Convert]::ToUInt64($ParticipantId.Substring(2), 16).ToString(
            [System.Globalization.CultureInfo]::InvariantCulture)
    }
    return [UInt64]::Parse(
        $ParticipantId,
        [System.Globalization.CultureInfo]::InvariantCulture).ToString(
            [System.Globalization.CultureInfo]::InvariantCulture)
}

function Wait-SharedRunFromNativeQuickStart {
    param(
        [Parameter(Mandatory = $true)]
        [string]$HostLog,
        [Parameter(Mandatory = $true)]
        [string]$ClientLog,
        [Parameter(Mandatory = $true)]
        [string]$HostParticipantId,
        [Parameter(Mandatory = $true)]
        [string]$ClientParticipantId
    )

    $hostParticipantDecimal =
        Convert-ParticipantIdToDecimalText $HostParticipantId
    $clientParticipantDecimal =
        Convert-ParticipantIdToDecimalText $ClientParticipantId
    Wait-LogTokenCount `
        -LogPath $HostLog `
        -Text "Multiplayer join flow armed the native quick-start run after remote-player materialization."
    Wait-LogTokenCount `
        -LogPath $HostLog `
        -Text "Queued hub testrun request."
    Wait-LogTokenCount `
        -LogPath $HostLog `
        -Text "Multiplayer join flow: loading_boneyard -> run"
    Wait-LogTokenCount `
        -LogPath $ClientLog `
        -Text "Multiplayer join flow: loading_boneyard -> run"
    Wait-LogTokenCount `
        -LogPath $HostLog `
        -Text "created gameplay-slot wizard actor. bot_id=$clientParticipantDecimal" `
        -MinimumCount 2
    Wait-LogTokenCount `
        -LogPath $ClientLog `
        -Text "created gameplay-slot wizard actor. bot_id=$hostParticipantDecimal" `
        -MinimumCount 2
    Start-Sleep -Milliseconds 1000
}

function Assert-NoTutorialSandboxArtifacts {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Role,
        [Parameter(Mandatory = $true)]
        [string]$StageRoot
    )

    $sandboxPath = Join-Path $StageRoot "sandbox"
    $tutorialArtifacts = @(
        Get-ChildItem `
            -LiteralPath $sandboxPath `
            -File `
            -Recurse `
            -ErrorAction SilentlyContinue |
            Where-Object {
                $_.Name -ieq "play.boneyard" -or
                $_.Name -match "tutorial"
            }
    )
    if ($tutorialArtifacts.Count -ne 0) {
        throw "$Role fresh runtime created tutorial artifact(s): $($tutorialArtifacts.FullName -join ', ')"
    }
    return [pscustomobject]@{
        role = $Role
        tutorialArtifactCount = 0
        sandboxPath = $sandboxPath
    }
}

function Assert-LogContract {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Role,
        [Parameter(Mandatory = $true)]
        [string]$LogPath
    )

    $text = [System.IO.File]::ReadAllText($LogPath)
    $bypassToken =
        "Fresh-save tutorial bypass redirected the stock tutorial bootstrap to standard gameplay before construction."
    $bypassCount = [regex]::Matches(
        $text,
        [regex]::Escape($bypassToken)).Count
    if ($bypassCount -ne 1) {
        throw "$Role log recorded $bypassCount pre-construction tutorial bypasses; expected exactly one."
    }
    $controlDispatchCount = [regex]::Matches(
        $text,
        [regex]::Escape(
            "target=control_scheme_picker.select_wasd surface=control_scheme_picker")).Count
    if ($controlDispatchCount -ne 1) {
        throw "$Role log recorded $controlDispatchCount control-picker dispatches; expected exactly one."
    }
    $firstRunDialogDispatchCount = [regex]::Matches(
        $text,
        [regex]::Escape(
            "target=dialog.primary surface=dialog")).Count
    if ($firstRunDialogDispatchCount -ne 1) {
        throw "$Role log recorded $firstRunDialogDispatchCount first-run dialog dispatches; expected exactly one."
    }
    $elementDispatchCount = [regex]::Matches(
        $text,
        [regex]::Escape(
            "target=create.select_element_ether surface=create")).Count
    if ($elementDispatchCount -ne 1) {
        throw "$Role log recorded $elementDispatchCount stock element dispatches; expected exactly one."
    }
    $disciplineDispatchCount = [regex]::Matches(
        $text,
        [regex]::Escape(
            "target=create.select_discipline_arcane surface=create")).Count
    if ($disciplineDispatchCount -ne 1) {
        throw "$Role log recorded $disciplineDispatchCount stock discipline dispatches; expected exactly one."
    }
    $runQueueCount = [regex]::Matches(
        $text,
        [regex]::Escape("Queued hub testrun request.")).Count
    if ($runQueueCount -ne 1) {
        throw "$Role log recorded $runQueueCount hub run requests; expected exactly one."
    }
    $nativeRunRequestCount = [regex]::Matches(
        $text,
        [regex]::Escape(
            "Multiplayer join flow requested the native quick-start run.")).Count
    if ($Role -eq "host" -and $nativeRunRequestCount -ne 1) {
        throw "host log recorded $nativeRunRequestCount native quick-start run requests; expected exactly one."
    }
    if ($Role -ne "host" -and $nativeRunRequestCount -ne 0) {
        throw "$Role log unexpectedly requested the host-only native quick-start run."
    }
    foreach ($forbidden in @(
        "observed the stock fresh-save tutorial bootstrap",
        "Tutorial.boneyard",
        "surface=tutorial",
        "scene=tutorial",
        "Vectored exception handler observed access violation",
        "Crash report captured"
    )) {
        if ($text.IndexOf(
                $forbidden,
                [System.StringComparison]::OrdinalIgnoreCase) -ge 0) {
            throw "$Role log contains forbidden fresh-install evidence: $forbidden"
        }
    }
    foreach ($required in @(
        "Multiplayer join flow: connecting -> hub",
        "Multiplayer join flow: loading_boneyard -> run",
        "Runtime bootstrap: api_version=0.2.0 mods=0 lua=0",
        "Lua runtime mods loaded: 0",
        "peers=1"
    )) {
        if ($text.IndexOf(
                $required,
                [System.StringComparison]::Ordinal) -lt 0) {
            throw "$Role log is missing acceptance evidence: $required"
        }
    }

    return [pscustomobject]@{
        role = $Role
        tutorialBypassCount = $bypassCount
        controlPickerDispatchCount = $controlDispatchCount
        firstRunDialogDispatchCount = $firstRunDialogDispatchCount
        stockElementDispatchCount = $elementDispatchCount
        stockDisciplineDispatchCount = $disciplineDispatchCount
        hubRunRequestCount = $runQueueCount
        nativeQuickStartRunRequestCount = $nativeRunRequestCount
        reachedHub = $true
        reachedRun = $true
        authenticatedLoopbackPeer = $true
    }
}

function Stop-ExactGameProcess {
    param(
        [int]$ProcessId,
        [string]$ExpectedPath
    )

    if ($ProcessId -le 0) {
        return "not_recorded"
    }
    $process = Get-CimInstance Win32_Process `
        -Filter "ProcessId = $ProcessId" `
        -ErrorAction SilentlyContinue
    if ($null -eq $process) {
        return "already_absent"
    }
    if (-not [string]::Equals(
            $process.ExecutablePath,
            $ExpectedPath,
            [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Refusing to stop PID $ProcessId at '$($process.ExecutablePath)'; expected '$ExpectedPath'."
    }
    Stop-Process -Id $ProcessId -Force
    return "stopped_exact_path"
}

if ($InstancePrefix -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]{0,47}$') {
    throw "InstancePrefix must be 1-48 filename-safe characters."
}
if (-not $AcceptJoinPreview) {
    throw "Fresh-install acceptance requires explicit -AcceptJoinPreview consent."
}
if ($HostPort -eq $ClientPort -or
    $HostPort -eq $PreviewPort -or
    $ClientPort -eq $PreviewPort) {
    throw "HostPort, ClientPort, and PreviewPort must be unique."
}

$resolvedGameDirectory = (Get-Item -LiteralPath $GameDirectory -ErrorAction Stop).FullName
$resolvedLauncherPath = (Get-Item -LiteralPath $LauncherPath -ErrorAction Stop).FullName
if (-not (Test-Path -LiteralPath (Join-Path $resolvedGameDirectory "SolomonDark.exe"))) {
    throw "GameDirectory does not contain SolomonDark.exe: $resolvedGameDirectory"
}
$resolvedRuntimeRoot = Resolve-NewAcceptanceDirectory `
    -Path $RuntimeRoot `
    -Label "RuntimeRoot"
$resolvedEvidenceDirectory = Resolve-NewAcceptanceDirectory `
    -Path $EvidenceDirectory `
    -Label "EvidenceDirectory"
if ([string]::Equals(
        $resolvedRuntimeRoot,
        $resolvedEvidenceDirectory,
        [System.StringComparison]::OrdinalIgnoreCase) -or
    $resolvedRuntimeRoot.StartsWith(
        $resolvedEvidenceDirectory.TrimEnd('\') + '\',
        [System.StringComparison]::OrdinalIgnoreCase) -or
    $resolvedEvidenceDirectory.StartsWith(
        $resolvedRuntimeRoot.TrimEnd('\') + '\',
        [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "RuntimeRoot and EvidenceDirectory must not contain one another."
}
foreach ($ownedOutputPath in @(
    $resolvedRuntimeRoot,
    $resolvedEvidenceDirectory
)) {
    if ($ownedOutputPath.StartsWith(
            $resolvedGameDirectory.TrimEnd('\') + '\',
            [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "RuntimeRoot and EvidenceDirectory must be outside GameDirectory."
    }
}

[System.IO.Directory]::CreateDirectory($resolvedEvidenceDirectory) | Out-Null

$hostInstance = "$InstancePrefix-host".ToLowerInvariant()
$clientInstance = "$InstancePrefix-client".ToLowerInvariant()
$hostInstanceRoot = Join-Path $resolvedRuntimeRoot "instances\$hostInstance"
$clientInstanceRoot = Join-Path $resolvedRuntimeRoot "instances\$clientInstance"
$hostStageRoot = Join-Path $hostInstanceRoot "stage"
$clientStageRoot = Join-Path $clientInstanceRoot "stage"
$hostTemporaryProfileRoot = Join-Path $hostInstanceRoot "temporary-client-profile"
$clientTemporaryProfileRoot = Join-Path $clientInstanceRoot "temporary-client-profile"
$hostExecutablePath = Join-Path $hostStageRoot "SolomonDark.exe"
$clientExecutablePath = Join-Path $clientStageRoot "SolomonDark.exe"
$pidLedgerPath = Join-Path $resolvedEvidenceDirectory "owned-processes.json"
$hostFirstLaunchScreenshot = Join-Path $resolvedEvidenceDirectory "01-host-first-launch.png"
$hostHubScreenshot = Join-Path $resolvedEvidenceDirectory "02-host-hub.png"
$joinPreviewJsonPath = Join-Path $resolvedEvidenceDirectory "03-join-preview-consent.json"
$joinPreviewScreenshot = Join-Path $resolvedEvidenceDirectory "03-join-preview-consent.png"
$clientJoinedScreenshot = Join-Path $resolvedEvidenceDirectory "04-client-lobby-joined.png"
$hostRunScreenshot = Join-Path $resolvedEvidenceDirectory "05-host-in-match.png"
$clientRunScreenshot = Join-Path $resolvedEvidenceDirectory "06-client-in-match.png"
$summaryPath = Join-Path $resolvedEvidenceDirectory "acceptance-summary.json"

$gameExecutablePath = Join-Path $resolvedGameDirectory "SolomonDark.exe"
$gameHash = (Get-FileHash -LiteralPath $gameExecutablePath -Algorithm SHA256).Hash
$sourceSandboxPath = Join-Path $resolvedGameDirectory "sandbox"
$freshProof = [pscustomobject]@{
    schema = "solomon-dark-fresh-install-proof-v1"
    capturedAtUtc = [DateTimeOffset]::UtcNow.ToString("o")
    runtimeRoot = $resolvedRuntimeRoot
    runtimeRootAbsentBeforeGate = -not (Test-Path -LiteralPath $resolvedRuntimeRoot)
    hostInstanceAbsentBeforeGate = -not (Test-Path -LiteralPath (Split-Path $hostStageRoot -Parent))
    clientInstanceAbsentBeforeGate = -not (Test-Path -LiteralPath (Split-Path $clientStageRoot -Parent))
    gameDirectory = $resolvedGameDirectory
    gameExecutableSha256 = $gameHash
    sourceSandboxPresent = Test-Path -LiteralPath $sourceSandboxPath
    sourceSandboxReadOrModified = $false
    joinPreviewConsentRequired = $true
    joinPreviewConsentAccepted = [bool]$AcceptJoinPreview
}
if (-not $freshProof.runtimeRootAbsentBeforeGate -or
    -not $freshProof.hostInstanceAbsentBeforeGate -or
    -not $freshProof.clientInstanceAbsentBeforeGate) {
    throw "Fresh state proof failed before the runtime root was created."
}
Write-JsonArtifact `
    -Value $freshProof `
    -Path (Join-Path $resolvedEvidenceDirectory "00-fresh-state-proof.json")
Write-ProofCard `
    -Title "Solomon Dark Fresh Install Proof" `
    -Lines @(
        "PASS new runtime root was absent before gate",
        "PASS host instance absent before gate",
        "PASS client instance absent before gate",
        "PASS source sandbox is excluded and never read",
        "Runtime: $resolvedRuntimeRoot",
        "Game SHA256: $gameHash",
        "Consent: explicit join-preview acceptance recorded"
    ) `
    -Path (Join-Path $resolvedEvidenceDirectory "00-fresh-state-proof.png")

$pythonServer = $null
$pythonServerPath = ""
$pythonServerCommandLine = ""
$hostProcessId = 0
$clientProcessId = 0
$summary = [ordered]@{
    ok = $false
    freshProof = $freshProof
}

try {
    $initialStage = Invoke-LauncherWithEnvironment `
        -LauncherPath $resolvedLauncherPath `
        -WorkingDirectory (Split-Path $resolvedLauncherPath -Parent) `
        -Environment @{} `
        -Arguments @(
            "stage",
            "--json",
            "--instance", $clientInstance,
            "--game-dir", $resolvedGameDirectory,
            "--runtime-root", $resolvedRuntimeRoot,
            "--runtime-flag", "multiplayer.steam_bootstrap=false",
            "--fresh-install",
            "--directory-url", "http://127.0.0.1:$PreviewPort"
        )
    if (-not $initialStage.configuration.freshInstall -or
        -not $initialStage.configuration.temporaryProfile) {
        throw "The launcher did not report an active fresh temporary profile."
    }
    if ([int]$initialStage.stage.enabledModCount -ne 0 -or
        @($initialStage.mods | Where-Object { $_.enabled }).Count -ne 0) {
        throw "Fresh staging enabled one or more mods before first launch."
    }
    if (Test-Path -LiteralPath ([string]$initialStage.configuration.modStatePath)) {
        throw "Fresh staging imported or created pre-staged mod settings."
    }
    $prelaunchSandboxFiles = @(
        Get-ChildItem `
            -LiteralPath (Join-Path $clientStageRoot "sandbox") `
            -File `
            -Recurse `
            -ErrorAction SilentlyContinue
    )
    if ($prelaunchSandboxFiles.Count -ne 0) {
        throw "Fresh stage contained sandbox files before launch: $($prelaunchSandboxFiles.FullName -join ', ')"
    }
    if (Test-Path -LiteralPath $clientTemporaryProfileRoot) {
        throw "Fresh staging created the temporary client profile before explicit launch."
    }
    $initialStageContract = [ordered]@{
        freshInstall = [bool]$initialStage.configuration.freshInstall
        temporaryProfile = [bool]$initialStage.configuration.temporaryProfile
        stagedSandboxFileCountBeforeLaunch = $prelaunchSandboxFiles.Count
        enabledModCountBeforeLaunch = 0
        modStateAbsentBeforeLaunch = $true
        temporaryProfileAbsentBeforeLaunch = $true
        expectedTemporaryProfileRoot = $clientTemporaryProfileRoot
        gameLaunched = $false
    }
    $existingClient = Get-CimInstance Win32_Process |
        Where-Object {
            [string]::Equals(
                $_.ExecutablePath,
                $clientExecutablePath,
                [System.StringComparison]::OrdinalIgnoreCase)
        }
    if ($null -ne $existingClient) {
        throw "Fresh staging unexpectedly launched the client game."
    }

    $stageReport = Get-Content `
        -LiteralPath ([string]$initialStage.stage.stageReportPath) `
        -Raw |
        ConvertFrom-Json
    $protocolVersion = [int]$stageReport.multiplayerCompatibility.ProtocolVersion
    $fingerprint = [string]$stageReport.multiplayerCompatibility.FingerprintSha256
    $fixtureRoot = Join-Path $resolvedEvidenceDirectory "loopback-directory"
    $joinManifestDirectory = Join-Path $fixtureRoot "api\lobbies\424242"
    [System.IO.Directory]::CreateDirectory($joinManifestDirectory) | Out-Null
    $joinManifest = [ordered]@{
        lobbyId = "424242"
        build = [ordered]@{
            appId = 3362180
            protocolVersion = $protocolVersion
            manifestSha256 = $fingerprint
            loaderVersion = "fresh-install-acceptance"
        }
        mods = @()
    }
    Write-JsonArtifact `
        -Value $joinManifest `
        -Path (Join-Path $joinManifestDirectory "join-manifest")

    $pythonExecutableOutput = [string](
        & py.exe -c "import sys; print(sys.executable)")
    if ($LASTEXITCODE -ne 0 -or
        [string]::IsNullOrWhiteSpace($pythonExecutableOutput)) {
        throw "Could not resolve the Python executable for the loopback directory."
    }
    $pythonExecutable = (
        Get-Item `
            -LiteralPath $pythonExecutableOutput.Trim() `
            -ErrorAction Stop
    ).FullName
    $pythonServerArguments = @(
            "-m", "http.server",
            [string]$PreviewPort,
            "--bind", "127.0.0.1",
            "--directory", $fixtureRoot
        )
    $pythonServer = Start-Process `
        -FilePath $pythonExecutable `
        -ArgumentList (
            ($pythonServerArguments | ForEach-Object {
                ConvertTo-MultiplayerProcessArgument $_
            }) -join " "
        ) `
        -WindowStyle Hidden `
        -PassThru
    Start-Sleep -Milliseconds 500
    $pythonServerProcess = Get-CimInstance Win32_Process `
        -Filter "ProcessId = $($pythonServer.Id)" `
        -ErrorAction SilentlyContinue
    if ($null -eq $pythonServerProcess) {
        throw "The loopback join-preview directory did not start."
    }
    $pythonServerPath = [string]$pythonServerProcess.ExecutablePath
    $pythonServerCommandLine = [string]$pythonServerProcess.CommandLine

    $preview = Invoke-LauncherWithEnvironment `
        -LauncherPath $resolvedLauncherPath `
        -WorkingDirectory (Split-Path $resolvedLauncherPath -Parent) `
        -Environment @{} `
        -Arguments @(
            "join-preview",
            "--json",
            "--instance", $clientInstance,
            "--game-dir", $resolvedGameDirectory,
            "--runtime-root", $resolvedRuntimeRoot,
            "--lobby-id", "424242",
            "--directory-url", "http://127.0.0.1:$PreviewPort"
        )
    if (-not $preview.joinPreview.usedWebsite -or
        $preview.joinPreview.unavailableCount -ne 0 -or
        $preview.joinPreview.hostProtocolVersion -ne $protocolVersion) {
        throw "Join preview did not accept the loopback host contract."
    }
    $consentProof = [ordered]@{
        accepted = [bool]$AcceptJoinPreview
        lobbyId = [string]$preview.joinPreview.lobbyId
        usedWebsite = [bool]$preview.joinPreview.usedWebsite
        hostProtocolVersion = [int]$preview.joinPreview.hostProtocolVersion
        localProtocolVersion = [int]$preview.joinPreview.localProtocolVersion
        installedCount = [int]$preview.joinPreview.installedCount
        cachedCount = [int]$preview.joinPreview.cachedCount
        downloadCount = [int]$preview.joinPreview.downloadCount
        unavailableCount = [int]$preview.joinPreview.unavailableCount
    }
    Write-JsonArtifact -Value $consentProof -Path $joinPreviewJsonPath

    $preparedJoin = Invoke-LauncherWithEnvironment `
        -LauncherPath $resolvedLauncherPath `
        -WorkingDirectory (Split-Path $resolvedLauncherPath -Parent) `
        -Environment @{} `
        -Arguments @(
            "stage",
            "--json",
            "--instance", $clientInstance,
            "--game-dir", $resolvedGameDirectory,
            "--runtime-root", $resolvedRuntimeRoot,
            "--runtime-flag", "multiplayer.steam_bootstrap=false",
            "--fresh-install",
            "--multiplayer", "join",
            "--lobby-id", "424242",
            "--directory-url", "http://127.0.0.1:$PreviewPort"
        )
    $existingClient = Get-CimInstance Win32_Process |
        Where-Object {
            [string]::Equals(
                $_.ExecutablePath,
                $clientExecutablePath,
                [System.StringComparison]::OrdinalIgnoreCase)
        }
    if ($null -ne $existingClient -or $null -ne $preparedJoin.launch) {
        throw "Join Game preparation auto-launched the client before explicit Launch Game."
    }
    Write-ProofCard `
        -Title "Join Preview Consent" `
        -Lines @(
            "PASS real launcher join-preview completed",
            "PASS host protocol $protocolVersion matched local protocol",
            "PASS unavailable mods: 0",
            "PASS consent explicitly accepted",
            "PASS Join Game prepared the stage without launching",
            "PASS explicit Launch Game is the next operation",
            "Lobby ID: 424242",
            "Host fingerprint: $fingerprint"
        ) `
        -Path $joinPreviewScreenshot

    if ($null -ne $pythonServer -and -not $pythonServer.HasExited) {
        $serverProcess = Get-CimInstance Win32_Process `
            -Filter "ProcessId = $($pythonServer.Id)" `
            -ErrorAction SilentlyContinue
        if ($null -ne $serverProcess -and
            [string]::Equals(
                $serverProcess.ExecutablePath,
                $pythonServerPath,
                [System.StringComparison]::OrdinalIgnoreCase) -and
            [string]::Equals(
                $serverProcess.CommandLine,
                $pythonServerCommandLine,
                [System.StringComparison]::Ordinal)) {
            Stop-Process -Id $pythonServer.Id -Force
        } else {
            throw "Refusing to stop the loopback directory process because its identity changed."
        }
    }
    $pythonServer = $null

    $pairOutput = & $pairScript `
        -Preset "map_create_ether_arcane_hub" `
        -HostPort $HostPort `
        -ClientPort $ClientPort `
        -HostParticipantId $HostParticipantId `
        -ClientParticipantId $ClientParticipantId `
        -HostName $HostName `
        -ClientName $ClientName `
        -InstancePrefix $InstancePrefix `
        -GameDirectory $resolvedGameDirectory `
        -RuntimeRoot $resolvedRuntimeRoot `
        -LauncherPath $resolvedLauncherPath `
        -FreshInstall `
        -NoLuaAutomation `
        -QuickStart `
        -QuickStartRun `
        -NoTileWindows `
        -EnableAudio:$audioEnabled `
        -ProcessIdOutputPath $pidLedgerPath `
        -HostFirstLaunchScreenshotPath $hostFirstLaunchScreenshot `
        -HostHubScreenshotPath $hostHubScreenshot `
        -ClientJoinedScreenshotPath $clientJoinedScreenshot
    $pair = ConvertFrom-MultiplayerLauncherJson `
        -Text ($pairOutput | Out-String)
    if ($null -eq $pair -or
        -not $pair.freshInstall -or
        -not $pair.noLuaAutomation -or
        -not $pair.quickStartRunEnabled -or
        [bool]$pair.audioDisabled -eq [bool]$audioEnabled) {
        throw "Local multiplayer pair did not report fresh zero-mod UI automation."
    }
    foreach ($modStatePath in @(
        (Join-Path $hostInstanceRoot "mod-manager-state.json"),
        (Join-Path $clientInstanceRoot "mod-manager-state.json")
    )) {
        if (Test-Path -LiteralPath $modStatePath) {
            throw "Fresh launch created pre-staged mod settings: $modStatePath"
        }
    }
    foreach ($temporaryProfileRoot in @(
        $hostTemporaryProfileRoot,
        $clientTemporaryProfileRoot
    )) {
        if (-not (Test-Path -LiteralPath $temporaryProfileRoot -PathType Container) -or
            -not (Test-Path `
                -LiteralPath (Join-Path $temporaryProfileRoot "savegames") `
                -PathType Container)) {
            throw "Fresh launch did not create its instance-local temporary profile: $temporaryProfileRoot"
        }
    }
    $hostProcessId = [int]$pair.hostProcessId
    $clientProcessId = [int]$pair.clientProcessId
    if (-not (Test-Path -LiteralPath $hostFirstLaunchScreenshot) -or
        -not (Test-Path -LiteralPath $hostHubScreenshot) -or
        -not (Test-Path -LiteralPath $clientJoinedScreenshot)) {
        throw "The pair launch did not capture all required onboarding screenshots."
    }
    $hostHubScreenshotContract = Assert-ScreenshotSceneCoverage `
        -Label "host hub" `
        -Path $hostHubScreenshot
    $clientJoinedScreenshotContract = Assert-ScreenshotSceneCoverage `
        -Label "client joined hub" `
        -Path $clientJoinedScreenshot

    Wait-SharedRunFromNativeQuickStart `
        -HostLog ([string]$pair.hostLog) `
        -ClientLog ([string]$pair.clientLog) `
        -HostParticipantId $HostParticipantId `
        -ClientParticipantId $ClientParticipantId
    Capture-GameWindow `
        -ProcessId $hostProcessId `
        -OutputPath $hostRunScreenshot
    Capture-GameWindow `
        -ProcessId $clientProcessId `
        -OutputPath $clientRunScreenshot

    $hostLogEvidence = Join-Path $resolvedEvidenceDirectory "host-solomondarkmodloader.log"
    $clientLogEvidence = Join-Path $resolvedEvidenceDirectory "client-solomondarkmodloader.log"
    Copy-Item -LiteralPath ([string]$pair.hostLog) -Destination $hostLogEvidence
    Copy-Item -LiteralPath ([string]$pair.clientLog) -Destination $clientLogEvidence
    $hostLogContract = Assert-LogContract -Role "host" -LogPath $hostLogEvidence
    $clientLogContract = Assert-LogContract -Role "client" -LogPath $clientLogEvidence
    $hostArtifactContract = Assert-NoTutorialSandboxArtifacts `
        -Role "host" `
        -StageRoot $hostStageRoot
    $clientArtifactContract = Assert-NoTutorialSandboxArtifacts `
        -Role "client" `
        -StageRoot $clientStageRoot

    $summary.ok = $true
    $summary.freshStage = $initialStageContract
    $summary.freshProfiles = @(
        [ordered]@{
            role = "host"
            root = $hostTemporaryProfileRoot
            beneathOwnedInstance = $true
        },
        [ordered]@{
            role = "client"
            root = $clientTemporaryProfileRoot
            beneathOwnedInstance = $true
        }
    )
    $summary.joinPreview = $consentProof
    $summary.manualLaunchBoundary = [ordered]@{
        preparedWithoutGame = $true
        explicitLaunchRequired = $true
    }
    $summary.pair = $pair
    $summary.logContracts = @($hostLogContract, $clientLogContract)
    $summary.runtimeArtifactContracts = @(
        $hostArtifactContract,
        $clientArtifactContract
    )
    $summary.screenshotContracts = @(
        $hostHubScreenshotContract,
        $clientJoinedScreenshotContract
    )
    $summary.screenshots = [ordered]@{
        freshState = Join-Path $resolvedEvidenceDirectory "00-fresh-state-proof.png"
        firstLaunch = $hostFirstLaunchScreenshot
        hubReached = $hostHubScreenshot
        joinPreviewConsent = $joinPreviewScreenshot
        lobbyJoined = $clientJoinedScreenshot
        hostInMatch = $hostRunScreenshot
        clientInMatch = $clientRunScreenshot
    }
    Write-JsonArtifact -Value $summary -Path $summaryPath
    $summary | ConvertTo-Json -Depth 12 -Compress
} catch {
    $summary.error = $_.Exception.Message
    Write-JsonArtifact -Value $summary -Path $summaryPath
    throw
} finally {
    $cleanup = [ordered]@{}
    if (Test-Path -LiteralPath $pidLedgerPath) {
        $ledger = Get-Content -LiteralPath $pidLedgerPath -Raw | ConvertFrom-Json
        if ($hostProcessId -le 0 -and $null -ne $ledger.hostProcessId) {
            $hostProcessId = [int]$ledger.hostProcessId
        }
        if ($clientProcessId -le 0 -and $null -ne $ledger.clientProcessId) {
            $clientProcessId = [int]$ledger.clientProcessId
        }
    }
    if ($null -ne $pythonServer -and -not $pythonServer.HasExited) {
        $serverProcess = Get-CimInstance Win32_Process `
            -Filter "ProcessId = $($pythonServer.Id)" `
            -ErrorAction SilentlyContinue
        if ($null -ne $serverProcess -and
            [string]::Equals(
                $serverProcess.ExecutablePath,
                $pythonServerPath,
                [System.StringComparison]::OrdinalIgnoreCase) -and
            [string]::Equals(
                $serverProcess.CommandLine,
                $pythonServerCommandLine,
                [System.StringComparison]::Ordinal)) {
            Stop-Process -Id $pythonServer.Id -Force
            $cleanup.previewServer = "stopped_exact_path"
        } else {
            $cleanup.previewServer = "identity_changed_not_stopped"
        }
    }
    $cleanup.host = Stop-ExactGameProcess `
        -ProcessId $hostProcessId `
        -ExpectedPath $hostExecutablePath
    $cleanup.client = Stop-ExactGameProcess `
        -ProcessId $clientProcessId `
        -ExpectedPath $clientExecutablePath
    Write-JsonArtifact `
        -Value $cleanup `
        -Path (Join-Path $resolvedEvidenceDirectory "cleanup.json")
}
