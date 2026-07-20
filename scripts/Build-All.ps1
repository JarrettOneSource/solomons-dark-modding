param(
    [ValidateSet("Debug", "Release")]
    [string]$Configuration = "Release"
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$launcher = Join-Path $root "SolomonDarkModLauncher/SolomonDarkModLauncher.csproj"
$launcherUi = Join-Path $root "SolomonDarkModLauncher.UI/SolomonDarkModLauncher.UI.csproj"
$loader = Join-Path $root "SolomonDarkModLoader/SolomonDarkModLoader.vcxproj"
$dist = Join-Path $root "dist/launcher"
$uiDist = Join-Path $root "dist/ui"
$loaderOutputDirectory = Join-Path $root "bin/$Configuration/Win32"
$loaderOutput = Join-Path $loaderOutputDirectory "SolomonDarkModLoader.dll"
$uiExecutableName = "SolomonDarkMultiplayerBeta.exe"

function Resolve-MSBuild {
    $command = Get-Command MSBuild.exe -ErrorAction SilentlyContinue
    if ($command) {
        return $command.Source
    }

    $vswhere = Join-Path ${env:ProgramFiles(x86)} "Microsoft Visual Studio\Installer\vswhere.exe"
    if (Test-Path $vswhere) {
        $candidate = & $vswhere -latest -products * -requires Microsoft.Component.MSBuild -find "MSBuild\**\Bin\MSBuild.exe" | Select-Object -First 1
        if ($candidate) {
            return $candidate
        }
    }

    throw "MSBuild.exe was not found. Visual Studio Build Tools are required to build SolomonDarkModLoader."
}

function Assert-LastExitCode {
    param([string]$Step)

    if ($LASTEXITCODE -ne 0) {
        throw "$Step failed with exit code $LASTEXITCODE."
    }
}

if (Test-Path $dist) {
    Remove-Item $dist -Recurse -Force
}

if (Test-Path $uiDist) {
    Remove-Item $uiDist -Recurse -Force
}

$msbuild = Resolve-MSBuild

& $msbuild $loader /t:Rebuild /m /nologo /p:Configuration=$Configuration /p:Platform=Win32
Assert-LastExitCode "SolomonDarkModLoader build"

dotnet publish $launcher `
    -c $Configuration `
    -r win-x86 `
    --self-contained false `
    -o $dist
Assert-LastExitCode "SolomonDarkModLauncher publish"

dotnet publish $launcherUi `
    -c $Configuration `
    --self-contained false `
    -o $uiDist
Assert-LastExitCode "SolomonDarkModLauncher.UI publish"

if (Test-Path $loaderOutput) {
    Copy-Item $loaderOutput $dist -Force
}

$launcherExecutable = Join-Path $dist "SolomonDarkModLauncher.exe"
if (-not (Test-Path $launcherExecutable)) {
    throw "SolomonDarkModLauncher publish output missing: $launcherExecutable"
}

Write-Host "Build completed."
Write-Host "Launcher: $launcherExecutable"
Write-Host "Launcher UI: $(Join-Path $uiDist $uiExecutableName)"
if (Test-Path $loaderOutput) {
    Write-Host "Loader: $loaderOutput"
}
