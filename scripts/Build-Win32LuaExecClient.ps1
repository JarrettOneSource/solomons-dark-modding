param(
    [string]$OutputPath = ""
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$source = Join-Path $root "tools/win32_lua_exec_client.cpp"
if ([string]::IsNullOrWhiteSpace($OutputPath)) {
    $OutputPath = Join-Path $root "runtime/tools/win32_lua_exec_client.exe"
}
$OutputPath = [System.IO.Path]::GetFullPath($OutputPath)
$outputDirectory = Split-Path $OutputPath -Parent
New-Item -ItemType Directory -Path $outputDirectory -Force | Out-Null

$vswhere = Join-Path ${env:ProgramFiles(x86)} "Microsoft Visual Studio\Installer\vswhere.exe"
if (-not (Test-Path $vswhere)) {
    throw "vswhere.exe was not found. Visual Studio Build Tools are required."
}
$installation = & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
if ([string]::IsNullOrWhiteSpace($installation)) {
    throw "Visual Studio C++ x86 build tools were not found."
}
$vcvars = Join-Path $installation "VC\Auxiliary\Build\vcvars32.bat"
if (-not (Test-Path $vcvars)) {
    throw "vcvars32.bat was not found at $vcvars"
}

$environmentLines = & $env:ComSpec /d /c "call `"$vcvars`" >nul && set"
if ($LASTEXITCODE -ne 0) {
    throw "vcvars32.bat failed with exit code $LASTEXITCODE."
}
foreach ($line in $environmentLines) {
    $separator = $line.IndexOf('=')
    if ($separator -gt 0) {
        [Environment]::SetEnvironmentVariable(
            $line.Substring(0, $separator),
            $line.Substring($separator + 1),
            'Process')
    }
}

$objectPath = [System.IO.Path]::ChangeExtension($OutputPath, ".obj")
& cl.exe /nologo /O2 /EHsc /W4 /WX /DUNICODE /D_UNICODE "/Fo:$objectPath" "/Fe:$OutputPath" $source
if ($LASTEXITCODE -ne 0) {
    throw "Win32 Lua exec client build failed with exit code $LASTEXITCODE."
}
Write-Output $OutputPath
