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
$launcherExecutable = Join-Path $extractedRoot "launcher/SolomonDarkModLauncher.exe"
$result = [ordered]@{
    ok = $false
    archive = $ArchivePath
    archiveSha256 = (Get-FileHash $ArchivePath -Algorithm SHA256).Hash.ToLowerInvariant()
    extractionRoot = $extractedRoot
    workspaceRoot = $null
    modCount = 0
    stagedExecutable = $null
    steamAppId = $null
    steamApiReady = $false
    steamApiSource = $null
    uiWindowTitle = $null
    uiCatalogStatus = $null
    uiMultiplayerActions = @()
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
    foreach ($requiredPath in @($uiExecutable, $launcherExecutable)) {
        if (-not (Test-Path $requiredPath -PathType Leaf)) {
            throw "Extracted beta is missing $requiredPath"
        }
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
    $result.steamAppId = $stageReport.steamBootstrap.appId
    $result.steamApiReady = [bool]$stageReport.steamBootstrap.readyForInitialization
    $result.steamApiSource = $stageReport.steamBootstrap.steamApiSourcePath
    if ($result.steamAppId -ne "480" -or -not $result.steamApiReady) {
        throw "Extracted host stage did not materialize the Spacewar Steam runtime."
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

        $requiredMultiplayerActions = @(
            "Host Game",
            "Join Lobby ID",
            "Play Solo",
            "How to Play"
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
