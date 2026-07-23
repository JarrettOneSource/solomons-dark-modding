param(
    [string]$ArchivePath = "",
    [string]$GameDirectory = "",
    [string]$OutputPath = "",
    [switch]$KeepExtracted
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
[xml]$versionProps = Get-Content (Join-Path $root "Directory.Build.props")
$version = ([string]$versionProps.Project.PropertyGroup.Version).Trim()
$releaseName = "SolomonDarkMultiplayerBeta-v$version"
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)

if ([string]::IsNullOrWhiteSpace($ArchivePath)) {
    $ArchivePath = Join-Path $root "artifacts/$releaseName.zip"
}
$ArchivePath = [System.IO.Path]::GetFullPath($ArchivePath)
if (-not (Test-Path $ArchivePath -PathType Leaf)) {
    throw "Beta archive was not found: $ArchivePath"
}

if ([string]::IsNullOrWhiteSpace($GameDirectory)) {
    $GameDirectory = Join-Path $root "../SolomonDarkAbandonware"
}
$GameDirectory = [System.IO.Path]::GetFullPath($GameDirectory)

if ([string]::IsNullOrWhiteSpace($OutputPath)) {
    $OutputPath = Join-Path $root "runtime/beta_release_package_smoke.json"
}
$OutputPath = [System.IO.Path]::GetFullPath($OutputPath)

$smokeRoot = Join-Path $env:TEMP "SolomonDarkMultiplayerBeta-Smoke-$version"
$extractedRoot = Join-Path $smokeRoot $releaseName
$runtimeRoot = Join-Path $smokeRoot "runtime"
$uiExecutable = Join-Path $extractedRoot "SolomonDarkMultiplayerBeta.exe"
$updaterExecutable = Join-Path $extractedRoot "SolomonDarkLauncherUpdater.exe"
$distributionFilesManifest = Join-Path $extractedRoot ".distribution-files.json"
$launcherExecutable = Join-Path $extractedRoot "launcher/SolomonDarkModLauncher.exe"
$launcherCoreClr = Join-Path $extractedRoot "launcher/coreclr.dll"
$launcherPrivateCoreLib = Join-Path $extractedRoot "launcher/System.Private.CoreLib.dll"
$launcherRuntimeConfig = Join-Path $extractedRoot "launcher/SolomonDarkModLauncher.runtimeconfig.json"
$result = [ordered]@{
    ok = $false
    archive = $ArchivePath
    extractionRoot = $extractedRoot
    workspaceRoot = $null
    modCount = 0
    enabledModCount = 0
    declaredDefaultEnabledModCount = 0
    stagedExecutable = $null
    steamAppId = $null
    steamApiReady = $false
    steamApiSource = $null
    uiWindowTitle = $null
    uiCatalogStatus = $null
    uiDisplayedModVersion = $null
    uiMultiplayerActions = @()
    uiProtocolHandler = $null
    uiSingleInstanceForwarding = $false
    uiLobbyLinkForwarding = $false
    uiMissingGameError = $null
    uiMissingGameRecoveryAvailable = $false
}

$uiSettingsDirectory = Join-Path $env:LOCALAPPDATA "SolomonDarkMultiplayerBeta"
$uiSettingsPath = Join-Path $uiSettingsDirectory "settings.json"
$hadUiSettings = Test-Path $uiSettingsPath -PathType Leaf
$originalUiSettings = if ($hadUiSettings) {
    [System.IO.File]::ReadAllBytes($uiSettingsPath)
}
else {
    $null
}
$protocolRegistrySubkey = "Software\Classes\solomondarkrevived"
$protocolRegistryPath = "HKCU:\$protocolRegistrySubkey"
$protocolRegistryBackupPath = Join-Path $env:TEMP "SolomonDarkMultiplayerBeta-scheme-$version.reg"
$hadProtocolRegistration = Test-Path $protocolRegistryPath
if ($hadProtocolRegistration) {
    & reg.exe export "HKCU\$protocolRegistrySubkey" $protocolRegistryBackupPath /y | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "Could not preserve the existing Solomon Dark lobby protocol registration."
    }
}

function Invoke-JsonLauncher {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)

    $payload = & $launcherExecutable @Arguments
    if ($LASTEXITCODE -ne 0) {
        throw "Packaged launcher failed ($LASTEXITCODE): $($Arguments -join ' ')`n$payload"
    }
    $response = $payload | ConvertFrom-Json
    if (-not $response.success) {
        throw "Packaged launcher rejected '$($Arguments -join ' ')': $($response.error)"
    }
    return $response
}

function Remove-DirectoryWithRetry {
    param([Parameter(Mandatory = $true)][string]$Path)

    $deadline = (Get-Date).AddSeconds(10)
    while (Test-Path $Path) {
        try {
            Remove-Item $Path -Recurse -Force -ErrorAction Stop
            return
        }
        catch {
            if ((Get-Date) -ge $deadline) {
                throw
            }
            Start-Sleep -Milliseconds 100
        }
    }
}

if (Test-Path $smokeRoot) {
    Remove-DirectoryWithRetry -Path $smokeRoot
}
New-Item -ItemType Directory -Path $smokeRoot -Force | Out-Null

try {
    Expand-Archive -Path $ArchivePath -DestinationPath $smokeRoot -Force
    foreach ($requiredPath in @(
            $uiExecutable,
            $updaterExecutable,
            $distributionFilesManifest,
            $launcherExecutable,
            $launcherCoreClr,
            $launcherPrivateCoreLib,
            $launcherRuntimeConfig
        )) {
        if (-not (Test-Path $requiredPath -PathType Leaf)) {
            throw "Extracted beta is missing $requiredPath"
        }
    }

    $portableMarkerPath = Join-Path $extractedRoot "solomon-dark-multiplayer.json"
    if (-not (Test-Path $portableMarkerPath -PathType Leaf)) {
        throw "Extracted beta is missing its portable release marker."
    }
    $portableMarker = Get-Content $portableMarkerPath -Raw | ConvertFrom-Json
    if ($portableMarker.PSObject.Properties.Name -notcontains "defaultEnabledMods") {
        throw "The beta release marker does not declare its default enabled-mod set."
    }
    $result.declaredDefaultEnabledModCount = @($portableMarker.defaultEnabledMods).Count
    if ($result.declaredDefaultEnabledModCount -ne 0) {
        throw "The beta release marker declares enabled mods by default."
    }

    $commonArguments = @(
        "--json",
        "--game-dir", $GameDirectory,
        "--runtime-root", $runtimeRoot
    )
    $catalog = Invoke-JsonLauncher -Arguments (@("list-mods") + $commonArguments)
    $result.workspaceRoot = $catalog.configuration.workspaceRoot
    $result.modCount = @($catalog.mods).Count
    if ($result.modCount -lt 1) {
        throw "Extracted beta discovered no mods."
    }
    $expectedDisplayedModVersion = "v$($catalog.mods[0].version)"
    $result.enabledModCount = @($catalog.mods | Where-Object { $_.enabled }).Count
    if ($result.enabledModCount -ne 0) {
        throw "A clean extracted beta enabled $($result.enabledModCount) mods; releases must start with zero enabled mods."
    }
    if (-not [string]::Equals(
            [System.IO.Path]::GetFullPath($result.workspaceRoot),
            [System.IO.Path]::GetFullPath($extractedRoot),
            [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Portable workspace discovery escaped the extracted root: $($result.workspaceRoot)"
    }

    $stage = Invoke-JsonLauncher -Arguments (@(
            "stage",
            "--multiplayer", "host",
            "--lobby-privacy", "public",
            "--directory-url", "https://solomon.genericproject.xyz"
        ) + $commonArguments)
    $result.stagedExecutable = $stage.stage.stageExecutablePath
    if (-not (Test-Path $result.stagedExecutable -PathType Leaf)) {
        throw "Packaged launcher did not stage SolomonDark.exe."
    }
    $stageReport = Get-Content $stage.stage.stageReportPath -Raw | ConvertFrom-Json
    if ([int]$stage.stage.enabledModCount -ne 0 -or [int]$stageReport.enabledModCount -ne 0) {
        throw "A clean extracted beta staged enabled mods."
    }
    $result.steamAppId = $stageReport.steamBootstrap.appId
    $result.steamApiReady = [bool]$stageReport.steamBootstrap.readyForInitialization
    $result.steamApiSource = $stageReport.steamBootstrap.steamApiSourcePath
    if ($result.steamAppId -ne "3362180" -or -not $result.steamApiReady) {
        throw "Extracted host stage did not materialize the Solomon Dark Steam runtime."
    }
    $expectedSteamRoot = [System.IO.Path]::GetFullPath(
        (Join-Path $extractedRoot "launcher/assets/steam/win32"))
    if (-not $result.steamApiSource.StartsWith(
            $expectedSteamRoot,
            [System.StringComparison]::OrdinalIgnoreCase)) {
        throw "Extracted stage did not use the packaged Steam runtime: $($result.steamApiSource)"
    }

    New-Item -ItemType Directory -Path $uiSettingsDirectory -Force | Out-Null
    $uiSettings = [ordered]@{ gameDirectory = $GameDirectory } | ConvertTo-Json
    [System.IO.File]::WriteAllText($uiSettingsPath, $uiSettings, $utf8NoBom)

    $uiProcess = Start-Process -FilePath $uiExecutable -PassThru
    try {
        $deadline = (Get-Date).AddSeconds(20)
        while ((Get-Date) -lt $deadline -and -not $uiProcess.HasExited) {
            $uiProcess.Refresh()
            if ($uiProcess.MainWindowHandle -ne 0) {
                break
            }
            Start-Sleep -Milliseconds 100
        }
        $uiProcess.Refresh()
        if ($uiProcess.HasExited -or $uiProcess.MainWindowHandle -eq 0) {
            throw "Extracted desktop launcher did not open a window."
        }
        $result.uiWindowTitle = $uiProcess.MainWindowTitle
        if ($result.uiWindowTitle -notlike "Solomon Dark Revived*") {
            throw "Unexpected desktop launcher title: $($result.uiWindowTitle)"
        }

        if (-not (Test-Path $protocolRegistryPath)) {
            throw "Desktop launcher did not register website lobby links."
        }
        $protocolKey = Get-Item $protocolRegistryPath
        if ($protocolKey.GetValueNames() -notcontains "URL Protocol") {
            throw "Desktop launcher protocol registration is not a URL handler."
        }
        $protocolCommandPath = Join-Path $protocolRegistryPath "shell/open/command"
        $protocolCommand = [string](Get-Item $protocolCommandPath).GetValue("")
        $expectedProtocolCommand = "`"$uiExecutable`" `"%1`""
        if (-not [string]::Equals(
                $protocolCommand,
                $expectedProtocolCommand,
                [System.StringComparison]::OrdinalIgnoreCase)) {
            throw "Desktop launcher registered the wrong lobby-link command: $protocolCommand"
        }
        $result.uiProtocolHandler = $protocolCommand

        $secondUiProcess = Start-Process -FilePath $uiExecutable -PassThru
        if (-not $secondUiProcess.WaitForExit(10000)) {
            Stop-Process -Id $secondUiProcess.Id -Force -ErrorAction SilentlyContinue
            throw "A second desktop launcher did not forward activation to the open launcher."
        }
        $uiProcess.Refresh()
        if ($uiProcess.HasExited) {
            throw "The primary desktop launcher exited during single-instance activation."
        }
        $result.uiSingleInstanceForwarding = $true

        Add-Type -AssemblyName UIAutomationClient
        $automationRoot = [System.Windows.Automation.AutomationElement]::FromHandle(
            $uiProcess.MainWindowHandle)
        $catalogDeadline = (Get-Date).AddSeconds(20)
        $modSummaryPattern =
            '^Enabled mods: \d+ of ' + [regex]::Escape([string]$result.modCount) + '$'
        $visibleText = @()
        while ((Get-Date) -lt $catalogDeadline -and -not $uiProcess.HasExited) {
            $elements = $automationRoot.FindAll(
                [System.Windows.Automation.TreeScope]::Descendants,
                [System.Windows.Automation.Condition]::TrueCondition)
            $visibleText = @(
                for ($index = 0; $index -lt $elements.Count; $index++) {
                    $name = $elements.Item($index).Current.Name
                    if (-not [string]::IsNullOrWhiteSpace($name)) {
                        $name
                    }
                })
            $catalogReady = $visibleText -contains "Ready"
            $catalogSummary = $visibleText |
                Where-Object { $_ -match $modSummaryPattern } |
                Select-Object -First 1
            if ($catalogReady -and $catalogSummary) {
                $result.uiCatalogStatus = "Ready"
                break
            }
            $launcherResolutionError = $visibleText |
                Where-Object { $_ -like "Could not locate SolomonDarkModLauncher.exe*" } |
                Select-Object -First 1
            if ($launcherResolutionError) {
                throw "Packaged desktop launcher could not invoke its packaged CLI: $launcherResolutionError"
            }
            Start-Sleep -Milliseconds 100
            $uiProcess.Refresh()
        }
        if ($result.uiCatalogStatus -ne "Ready") {
            $diagnostics = ($visibleText |
                Where-Object { $_ -match "failed|error|launcher|catalog" } |
                Select-Object -Unique) -join "; "
            throw "Packaged desktop launcher did not refresh its mod catalog. $diagnostics"
        }
        if ($visibleText -notcontains $expectedDisplayedModVersion) {
            throw "Packaged desktop launcher did not show mod version $expectedDisplayedModVersion."
        }
        $result.uiDisplayedModVersion = $expectedDisplayedModVersion

        $requiredMultiplayerActions = @(
            "Host Game",
            "Join Lobby ID",
            "Play Solo",
            "How to Play",
            "Choose Save"
        )
        foreach ($action in $requiredMultiplayerActions) {
            if ($visibleText -notcontains $action) {
                throw "Packaged desktop launcher is missing the '$action' action."
            }
        }
        $result.uiMultiplayerActions = $requiredMultiplayerActions
    }
    finally {
        if ($null -ne $uiProcess -and -not $uiProcess.HasExited) {
            Stop-Process -Id $uiProcess.Id -Force -ErrorAction SilentlyContinue
            $uiProcess.WaitForExit(5000) | Out-Null
        }
    }

    $missingGameDirectory = Join-Path $smokeRoot "missing-game-executable"
    New-Item -ItemType Directory -Path $missingGameDirectory -Force | Out-Null
    $missingGameSettings = [ordered]@{ gameDirectory = $missingGameDirectory } | ConvertTo-Json
    [System.IO.File]::WriteAllText($uiSettingsPath, $missingGameSettings, $utf8NoBom)

    $uiProcess = Start-Process -FilePath $uiExecutable -PassThru
    try {
        $deadline = (Get-Date).AddSeconds(20)
        while ((Get-Date) -lt $deadline -and -not $uiProcess.HasExited) {
            $uiProcess.Refresh()
            if ($uiProcess.MainWindowHandle -ne 0) {
                break
            }
            Start-Sleep -Milliseconds 100
        }
        $uiProcess.Refresh()
        if ($uiProcess.HasExited -or $uiProcess.MainWindowHandle -eq 0) {
            throw "Desktop launcher did not open for the missing-game recovery check."
        }

        $automationRoot = [System.Windows.Automation.AutomationElement]::FromHandle(
            $uiProcess.MainWindowHandle)
        $recoveryButtonText = "Select Game Folder"
        $recoveryDeadline = (Get-Date).AddSeconds(20)
        $visibleText = @()
        while ((Get-Date) -lt $recoveryDeadline -and -not $uiProcess.HasExited) {
            $elements = $automationRoot.FindAll(
                [System.Windows.Automation.TreeScope]::Descendants,
                [System.Windows.Automation.Condition]::TrueCondition)
            $visibleText = @(
                for ($index = 0; $index -lt $elements.Count; $index++) {
                    $name = $elements.Item($index).Current.Name
                    if (-not [string]::IsNullOrWhiteSpace($name)) {
                        $name
                    }
                })
            $result.uiMissingGameError = $visibleText |
                Where-Object { $_ -like "*executable not found*" } |
                Select-Object -First 1
            $result.uiMissingGameRecoveryAvailable = $visibleText -contains $recoveryButtonText
            if ($result.uiMissingGameError -and $result.uiMissingGameRecoveryAvailable) {
                break
            }
            Start-Sleep -Milliseconds 100
            $uiProcess.Refresh()
        }
        if (-not $result.uiMissingGameError) {
            throw "Desktop launcher did not report the missing game executable."
        }
        if (-not $result.uiMissingGameRecoveryAvailable) {
            throw "Desktop launcher exposed no Select Game Folder action after the saved game path failed."
        }

        $testLobbyId = "109775243840973240"
        $testDirectory = [Uri]::EscapeDataString("http://127.0.0.1:5080")
        $lobbyLinkProcess = Start-Process `
            -FilePath $uiExecutable `
            -ArgumentList "solomondarkrevived://join/${testLobbyId}?directory=${testDirectory}" `
            -PassThru
        if (-not $lobbyLinkProcess.WaitForExit(10000)) {
            Stop-Process -Id $lobbyLinkProcess.Id -Force -ErrorAction SilentlyContinue
            throw "The website lobby link did not reach the open desktop launcher."
        }

        $forwardDeadline = (Get-Date).AddSeconds(10)
        while ((Get-Date) -lt $forwardDeadline -and -not $uiProcess.HasExited) {
            $elements = $automationRoot.FindAll(
                [System.Windows.Automation.TreeScope]::Descendants,
                [System.Windows.Automation.Condition]::TrueCondition)
            for ($index = 0; $index -lt $elements.Count; $index++) {
                $element = $elements.Item($index)
                $valuePattern = $null
                if ($element.TryGetCurrentPattern(
                        [System.Windows.Automation.ValuePattern]::Pattern,
                        [ref]$valuePattern) -and
                    $valuePattern.Current.Value -eq $testLobbyId) {
                    $result.uiLobbyLinkForwarding = $true
                    break
                }
            }
            if ($result.uiLobbyLinkForwarding) {
                break
            }
            Start-Sleep -Milliseconds 100
        }
        if (-not $result.uiLobbyLinkForwarding) {
            throw "The open desktop launcher did not receive the website Lobby ID."
        }
    }
    finally {
        if ($null -ne $uiProcess -and -not $uiProcess.HasExited) {
            Stop-Process -Id $uiProcess.Id -Force -ErrorAction SilentlyContinue
            $uiProcess.WaitForExit(5000) | Out-Null
        }
    }

    $result.ok = $true
}
finally {
    if ($hadUiSettings) {
        New-Item -ItemType Directory -Path $uiSettingsDirectory -Force | Out-Null
        [System.IO.File]::WriteAllBytes($uiSettingsPath, $originalUiSettings)
    }
    elseif (Test-Path $uiSettingsPath) {
        Remove-Item $uiSettingsPath -Force
    }
    if (Test-Path $protocolRegistryPath) {
        Remove-Item $protocolRegistryPath -Recurse -Force
    }
    if ($hadProtocolRegistration) {
        & reg.exe import $protocolRegistryBackupPath | Out-Null
        if ($LASTEXITCODE -ne 0) {
            throw "Could not restore the previous lobby protocol registration."
        }
    }
    if (Test-Path $protocolRegistryBackupPath) {
        Remove-Item $protocolRegistryBackupPath -Force
    }
    $outputDirectory = Split-Path -Parent $OutputPath
    New-Item -ItemType Directory -Path $outputDirectory -Force | Out-Null
    [System.IO.File]::WriteAllText(
        $OutputPath,
        (($result | ConvertTo-Json -Depth 8) + [Environment]::NewLine),
        $utf8NoBom)
    if (-not $KeepExtracted -and (Test-Path $smokeRoot)) {
        Remove-DirectoryWithRetry -Path $smokeRoot
    }
}

Write-Host "Beta release package smoke test passed."
Write-Host "Archive: $ArchivePath"
Write-Host "Portable root: $($result.workspaceRoot)"
Write-Host "Steam API source: $($result.steamApiSource)"
Write-Host "Desktop title: $($result.uiWindowTitle)"
Write-Host "Desktop catalog: $($result.uiCatalogStatus)"
