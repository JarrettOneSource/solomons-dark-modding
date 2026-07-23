param(
    [string]$Version = "",
    [string]$OutputDirectory = "",
    [string]$SteamApiDll = "",
    [switch]$SkipBuild
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$versionPropsPath = Join-Path $root "Directory.Build.props"
$protocolHeaderPath = Join-Path $root "SolomonDarkModLoader/include/multiplayer_runtime_protocol.h"
$gameInstallationPath = Join-Path $root "SolomonDarkModLauncher/src/Target/GameInstallation.cs"
$launcherProject = Join-Path $root "SolomonDarkModLauncher/SolomonDarkModLauncher.csproj"
$launcherUiProject = Join-Path $root "SolomonDarkModLauncher.UI/SolomonDarkModLauncher.UI.csproj"
$nativeLoaderOutput = Join-Path $root "bin/Release/Win32/SolomonDarkModLoader.dll"
$releaseReadmePath = Join-Path $root "release/README.txt"
$thirdPartyNoticesPath = Join-Path $root "release/THIRD-PARTY-NOTICES.txt"
$configuration = "Release"
$packagePrefix = "SolomonDarkMultiplayerBeta-v"
$uiExecutableName = "SolomonDarkMultiplayerBeta.exe"
$launcherExecutableName = "SolomonDarkModLauncher.exe"
$loaderFileName = "SolomonDarkModLoader.dll"
$steamApiFileName = "steam_api.dll"
$portableMarkerFileName = "solomon-dark-multiplayer.json"
$utf8NoBom = New-Object System.Text.UTF8Encoding($false)

function Assert-LastExitCode {
    param([string]$Step)

    if ($LASTEXITCODE -ne 0) {
        throw "$Step failed with exit code $LASTEXITCODE."
    }
}

function Get-DeclaredVersion {
    [xml]$props = Get-Content $versionPropsPath
    $declaredVersion = [string]$props.Project.PropertyGroup.Version
    if ([string]::IsNullOrWhiteSpace($declaredVersion)) {
        throw "Directory.Build.props does not declare Version."
    }
    return $declaredVersion.Trim()
}

function Get-FirstRegexGroup {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path,
        [Parameter(Mandatory = $true)]
        [string]$Pattern,
        [Parameter(Mandatory = $true)]
        [string]$Description
    )

    $text = [System.IO.File]::ReadAllText($Path)
    $match = [regex]::Match($text, $Pattern)
    if (-not $match.Success) {
        throw "Could not read $Description from $Path."
    }
    return $match.Groups[1].Value
}

function Test-X86Dll {
    param([Parameter(Mandatory = $true)][string]$Path)

    if (-not (Test-Path $Path -PathType Leaf)) {
        return $false
    }

    $stream = [System.IO.File]::OpenRead($Path)
    try {
        $reader = New-Object System.IO.BinaryReader($stream)
        if ($reader.ReadUInt16() -ne 0x5A4D) {
            return $false
        }
        $stream.Position = 0x3C
        $peOffset = $reader.ReadUInt32()
        if ($peOffset -gt ($stream.Length - 6)) {
            return $false
        }
        $stream.Position = $peOffset
        if ($reader.ReadUInt32() -ne 0x00004550) {
            return $false
        }
        return $reader.ReadUInt16() -eq 0x014C
    }
    finally {
        $stream.Dispose()
    }
}

function Resolve-SteamApiDll {
    $candidates = New-Object System.Collections.Generic.List[string]
    if (-not [string]::IsNullOrWhiteSpace($SteamApiDll)) {
        $candidates.Add($SteamApiDll)
    }

    $candidates.Add((Join-Path $root "SolomonDarkModLauncher/assets/steam/win32/$steamApiFileName"))

    $sdkRoot = [Environment]::GetEnvironmentVariable("STEAMWORKS_SDK_PATH")
    if (-not [string]::IsNullOrWhiteSpace($sdkRoot)) {
        $candidates.Add((Join-Path $sdkRoot "redistributable_bin/$steamApiFileName"))
    }

    $programFilesX86 = [Environment]::GetEnvironmentVariable("ProgramFiles(x86)")
    if (-not [string]::IsNullOrWhiteSpace($programFilesX86)) {
        $candidates.Add((Join-Path $programFilesX86 "Steam/steamapps/common/SteamVR/bin/win32/$steamApiFileName"))
    }

    foreach ($candidate in $candidates) {
        if ([string]::IsNullOrWhiteSpace($candidate)) {
            continue
        }
        $normalized = [System.IO.Path]::GetFullPath($candidate)
        if (Test-X86Dll $normalized) {
            return $normalized
        }
    }

    throw "A valid x86 steam_api.dll is required for the friend-playtest package. Pass -SteamApiDll or install the Steamworks SDK/SteamVR runtime."
}

function Copy-PublishTree {
    param(
        [Parameter(Mandatory = $true)][string]$Source,
        [Parameter(Mandatory = $true)][string]$Destination
    )

    New-Item -ItemType Directory -Path $Destination -Force | Out-Null
    Get-ChildItem $Source -Force | ForEach-Object {
        if ($_.Extension -ieq ".pdb") {
            return
        }
        Copy-Item $_.FullName $Destination -Recurse -Force
    }
}

function Write-Utf8NoBom {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Content
    )

    [System.IO.File]::WriteAllText($Path, $Content, $utf8NoBom)
}

$declaredVersion = Get-DeclaredVersion
if ([string]::IsNullOrWhiteSpace($Version)) {
    $Version = $declaredVersion
}
elseif (-not [string]::Equals($Version, $declaredVersion, [System.StringComparison]::Ordinal)) {
    throw "Requested version $Version does not match Directory.Build.props version $declaredVersion."
}

$protocolVersion = [int](Get-FirstRegexGroup `
    -Path $protocolHeaderPath `
    -Pattern 'kProtocolVersion\s*=\s*(\d+)' `
    -Description "multiplayer protocol version")
$supportedGameHash = Get-FirstRegexGroup `
    -Path $gameInstallationPath `
    -Pattern 'SupportedExecutableSha256\s*=\s*\r?\n?\s*"([0-9a-fA-F]{64})"' `
    -Description "supported game executable hash"

if ([string]::IsNullOrWhiteSpace($OutputDirectory)) {
    $OutputDirectory = Join-Path $root "artifacts"
}
$OutputDirectory = [System.IO.Path]::GetFullPath($OutputDirectory)
New-Item -ItemType Directory -Path $OutputDirectory -Force | Out-Null

$releaseName = "$packagePrefix$Version"
$packageRoot = Join-Path $OutputDirectory $releaseName
$archivePath = Join-Path $OutputDirectory "$releaseName.zip"
$releaseChecksumsPath = Join-Path $OutputDirectory "SHA256SUMS.txt"
$publishRoot = Join-Path $OutputDirectory ".publish-$Version"
$launcherPublish = Join-Path $publishRoot "launcher"
$uiPublish = Join-Path $publishRoot "ui"

foreach ($generatedPath in @($packageRoot, $publishRoot, $archivePath, $releaseChecksumsPath)) {
    if (Test-Path $generatedPath) {
        Remove-Item $generatedPath -Recurse -Force
    }
}

if (-not $SkipBuild) {
    & (Join-Path $PSScriptRoot "Build-All.ps1") -Configuration $configuration
    Assert-LastExitCode "Release build"
}

dotnet publish $launcherProject `
    -c $configuration `
    -r win-x86 `
    --self-contained true `
    -p:PublishSingleFile=true `
    -p:IncludeNativeLibrariesForSelfExtract=true `
    -p:DebugType=None `
    -p:DebugSymbols=false `
    -o $launcherPublish
Assert-LastExitCode "Self-contained CLI publish"

dotnet publish $launcherUiProject `
    -c $configuration `
    -r win-x64 `
    --self-contained true `
    -p:PublishSingleFile=true `
    -p:IncludeNativeLibrariesForSelfExtract=true `
    -p:DebugType=None `
    -p:DebugSymbols=false `
    -o $uiPublish
Assert-LastExitCode "Self-contained desktop launcher publish"

New-Item -ItemType Directory -Path $packageRoot -Force | Out-Null
Copy-PublishTree -Source $uiPublish -Destination $packageRoot
Copy-PublishTree -Source $launcherPublish -Destination (Join-Path $packageRoot "launcher")
if (-not (Test-Path $nativeLoaderOutput -PathType Leaf)) {
    throw "Release loader is missing: $nativeLoaderOutput. Run without -SkipBuild."
}
Copy-Item $nativeLoaderOutput (Join-Path $packageRoot "launcher/$loaderFileName") -Force

$packagedUi = Join-Path $packageRoot $uiExecutableName
$packagedLauncher = Join-Path $packageRoot "launcher/$launcherExecutableName"
$packagedLoader = Join-Path $packageRoot "launcher/$loaderFileName"
foreach ($requiredBinary in @($packagedUi, $packagedLauncher, $packagedLoader)) {
    if (-not (Test-Path $requiredBinary -PathType Leaf)) {
        throw "Published package is missing $requiredBinary."
    }
}

Copy-Item (Join-Path $root "config") $packageRoot -Recurse -Force
Copy-Item (Join-Path $root "mods") $packageRoot -Recurse -Force

$steamApiSource = Resolve-SteamApiDll
$packagedSteamDirectory = Join-Path $packageRoot "launcher/assets/steam/win32"
New-Item -ItemType Directory -Path $packagedSteamDirectory -Force | Out-Null
$packagedSteamApi = Join-Path $packagedSteamDirectory $steamApiFileName
Copy-Item $steamApiSource $packagedSteamApi -Force
if (-not (Test-X86Dll $packagedSteamApi)) {
    throw "Packaged Steam API is not a valid x86 DLL: $packagedSteamApi"
}

$readmeText = [System.IO.File]::ReadAllText($releaseReadmePath).
    Replace("{{VERSION}}", $Version).
    Replace("{{PROTOCOL_VERSION}}", [string]$protocolVersion).
    Replace("{{SUPPORTED_EXECUTABLE_SHA256}}", $supportedGameHash.ToLowerInvariant())
Write-Utf8NoBom -Path (Join-Path $packageRoot "README.txt") -Content $readmeText
Copy-Item $thirdPartyNoticesPath (Join-Path $packageRoot "THIRD-PARTY-NOTICES.txt") -Force

$marker = [ordered]@{
    schemaVersion = 1
    product = "Solomon Dark Multiplayer Beta"
    version = $Version
    protocolVersion = $protocolVersion
    supportedGameVersion = "0.72.5"
    supportedExecutableSha256 = $supportedGameHash.ToLowerInvariant()
    steamAppId = 3362180
    defaultEnabledMods = @()
    steamApiSha256 = (Get-FileHash $packagedSteamApi -Algorithm SHA256).Hash.ToLowerInvariant()
}
$markerJson = $marker | ConvertTo-Json
Write-Utf8NoBom -Path (Join-Path $packageRoot $portableMarkerFileName) -Content ($markerJson + [Environment]::NewLine)

$contentChecksumsPath = Join-Path $packageRoot "checksums.txt"
$contentChecksumLines = Get-ChildItem $packageRoot -Recurse -File |
    Where-Object { $_.FullName -ne $contentChecksumsPath } |
    Sort-Object FullName |
    ForEach-Object {
        $relativePath = $_.FullName.Substring($packageRoot.Length + 1).Replace('\', '/')
        $hash = (Get-FileHash $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        "$hash  $relativePath"
    }
Write-Utf8NoBom -Path $contentChecksumsPath -Content (($contentChecksumLines -join "`n") + "`n")

Compress-Archive -Path $packageRoot -DestinationPath $archivePath -CompressionLevel Optimal
$archiveHash = (Get-FileHash $archivePath -Algorithm SHA256).Hash.ToLowerInvariant()
Write-Utf8NoBom -Path $releaseChecksumsPath -Content "$archiveHash  $releaseName.zip`n"

Remove-Item $publishRoot -Recurse -Force

Write-Host "Beta package completed."
Write-Host "Package directory: $packageRoot"
Write-Host "Archive: $archivePath"
Write-Host "Archive SHA-256: $archiveHash"
Write-Host "Steam API source: $steamApiSource"
