[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[A-Za-z0-9][A-Za-z0-9._-]{0,47}$')]
    [string]$Instance,

    [Parameter(Mandatory = $true)]
    [ValidateRange(1, [int]::MaxValue)]
    [int]$ProcessId,

    [Parameter(Mandatory = $true)]
    [ValidatePattern('^[a-z0-9_]+$')]
    [string]$ScreenId,

    [Parameter(Mandatory = $true)]
    [string]$OutputPath,

    [Parameter(Mandatory = $true)]
    [string]$ReferencePngPath,

    [string]$CaptureCommit = ""
)

Set-StrictMode -Version 3.0
$ErrorActionPreference = "Stop"

$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).ProviderPath
$instanceRoot = Join-Path $root (
    "runtime\instances\" + $Instance.ToLowerInvariant()
)
$expectedExecutable = [IO.Path]::GetFullPath(
    (Join-Path $instanceRoot "stage\SolomonDark.exe")
)
$process = Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId"
if (
    $null -eq $process -or
    $null -eq $process.ExecutablePath -or
    -not [string]::Equals(
        [IO.Path]::GetFullPath($process.ExecutablePath),
        $expectedExecutable,
        [StringComparison]::OrdinalIgnoreCase
    )
) {
    throw "PID $ProcessId does not own the exact $Instance staged executable."
}

if ([string]::IsNullOrWhiteSpace($CaptureCommit)) {
    $CaptureCommit = (& git -C $root rev-parse HEAD).Trim()
    if ($LASTEXITCODE -ne 0 -or $CaptureCommit -notmatch '^[0-9a-f]{40}$') {
        throw "Could not resolve the capture commit."
    }
}
if ($CaptureCommit -notmatch '^[0-9a-f]{40}$') {
    throw "CaptureCommit must be a full lowercase Git SHA."
}

$outputItemPath = [IO.Path]::GetFullPath($OutputPath)
$referenceItemPath = [IO.Path]::GetFullPath($ReferencePngPath)
[IO.Directory]::CreateDirectory(
    (Split-Path -Parent $outputItemPath)
) | Out-Null
[IO.Directory]::CreateDirectory(
    (Split-Path -Parent $referenceItemPath)
) | Out-Null

$pipeName = "SolomonDarkModLoader_LuaExec_$Instance"
$luaExecClient = Join-Path $root "tools\lua-exec.py"
function Invoke-TargetLua {
    param(
        [Parameter(Mandatory = $true)]
        [string]$LuaCode
    )

    $previousPipe = $env:SDMOD_LUA_EXEC_PIPE_NAME
    try {
        $env:SDMOD_LUA_EXEC_PIPE_NAME = $pipeName
        $result = $LuaCode | & py.exe -3 $luaExecClient
        if ($LASTEXITCODE -ne 0) {
            throw "Lua exec failed with exit code $LASTEXITCODE."
        }
        return ($result -join "`n")
    } finally {
        $env:SDMOD_LUA_EXEC_PIPE_NAME = $previousPipe
    }
}

$screenLiteral = "[[$ScreenId]]"
$lua = @"
local function quote(value)
  value = tostring(value or '')
  value = value:gsub('\\', '\\\\')
  value = value:gsub('"', '\\"')
  value = value:gsub('\b', '\\b')
  value = value:gsub('\f', '\\f')
  value = value:gsub('\n', '\\n')
  value = value:gsub('\r', '\\r')
  value = value:gsub('\t', '\\t')
  return '"' .. value .. '"'
end
local function number(value)
  value = tonumber(value) or 0
  if value ~= value or value == math.huge or value == -math.huge then
    error('layout contains a non-finite number')
  end
  return string.format('%.6f', value)
end
local function boolean(value)
  return value and 'true' or 'false'
end
local snapshot = sd.ui.capture_current_layout($screenLiteral)
if type(snapshot) ~= 'table' then
  return '__MISSING_LAYOUT__'
end
local output = {
  '{',
  '"generation":' .. tostring(snapshot.generation or 0) .. ',',
  '"captured_at_milliseconds":' .. tostring(snapshot.captured_at_milliseconds or 0) .. ',',
  '"screen_id":' .. quote(snapshot.screen_id) .. ',',
  '"screen_title":' .. quote(snapshot.screen_title) .. ',',
  '"capture_method":' .. quote(snapshot.capture_method) .. ',',
  '"elements":['
}
for index, element in ipairs(snapshot.elements or {}) do
  if index > 1 then output[#output + 1] = ',' end
  output[#output + 1] = table.concat({
    '{"id":', quote(element.id),
    ',"kind":', quote(element.kind),
    ',"text":', quote(element.text),
    ',"action_id":', quote(element.action_id),
    ',"art_id":', quote(element.art_id),
    ',"font_id":', quote(element.font_id),
    ',"text_style":', quote(element.text_style),
    ',"visible":', boolean(element.visible),
    ',"interactive":', boolean(element.interactive),
    ',"draw_order":', tostring(element.draw_order or 0),
    ',"rect":[', number(element.left), ',', number(element.top), ',',
      number(element.right), ',', number(element.bottom), ']',
    ',"unclipped_rect":[', number(element.unclipped_left), ',',
      number(element.unclipped_top), ',', number(element.unclipped_right),
      ',', number(element.unclipped_bottom), ']}'
  })
end
output[#output + 1] = ']}'
return table.concat(output)
"@

$snapshotJson = Invoke-TargetLua -LuaCode $lua
if ($snapshotJson -eq "__MISSING_LAYOUT__") {
    throw "The live UI tree could not capture the current frame as '$ScreenId'."
}
$snapshot = $snapshotJson | ConvertFrom-Json
if ($snapshot.screen_id -ne $ScreenId) {
    throw "Requested '$ScreenId' but the live snapshot reported '$($snapshot.screen_id)'."
}
if (@($snapshot.elements).Count -eq 0) {
    throw "The live '$ScreenId' layout snapshot was empty."
}

$referenceBmpPath = [IO.Path]::ChangeExtension(
    $referenceItemPath,
    ".capture.bmp"
)
$captureLua = @"
local ok, message = sd.debug.capture_backbuffer([[$referenceBmpPath]])
if not ok then error(tostring(message)) end
return 'captured'
"@
$captureResult = Invoke-TargetLua -LuaCode $captureLua
if ($captureResult -ne "captured" -or
    -not (Test-Path -LiteralPath $referenceBmpPath -PathType Leaf)) {
    throw "The live D3D9 backbuffer capture failed: $captureResult"
}

Add-Type -AssemblyName System.Drawing
$image = [Drawing.Image]::FromFile($referenceBmpPath)
try {
    $image.Save($referenceItemPath, [Drawing.Imaging.ImageFormat]::Png)
} finally {
    $image.Dispose()
}
Remove-Item -LiteralPath $referenceBmpPath -Force

$nativeExecutableSha256 = (
    Get-FileHash -LiteralPath $expectedExecutable -Algorithm SHA256
).Hash.ToLowerInvariant()
$loaderPath = Join-Path $root "dist\launcher\SolomonDarkModLoader.dll"
if (-not (Test-Path -LiteralPath $loaderPath -PathType Leaf)) {
    throw "The exact launcher-side loader used to stage the instance is missing."
}
$loaderSha256 = (
    Get-FileHash -LiteralPath $loaderPath -Algorithm SHA256
).Hash.ToLowerInvariant()
$outputDirectoryUri = [Uri]::new(
    (Split-Path -Parent $outputItemPath).TrimEnd('\') + '\'
)
$referenceRelative = [Uri]::UnescapeDataString(
    $outputDirectoryUri.MakeRelativeUri(
        [Uri]::new($referenceItemPath)
    ).ToString()
)

$fixture = [ordered]@{
    schema = "solomon-dark-native-menu-layout-v1"
    header = [ordered]@{
        instance = $Instance
        process_id = $ProcessId
        capture_commit = $CaptureCommit
        native_exe_sha256 = $nativeExecutableSha256
        loader_dll_sha256 = $loaderSha256
        captured_at_utc = [DateTime]::UtcNow.ToString("o")
        capture_method = $snapshot.capture_method
        reference_capture = $referenceRelative
    }
    layout = $snapshot
}
$json = $fixture | ConvertTo-Json -Depth 100
[IO.File]::WriteAllText(
    $outputItemPath,
    $json + "`n",
    [Text.UTF8Encoding]::new($false)
)

[pscustomobject]@{
    success = $true
    screen = $ScreenId
    elements = @($snapshot.elements).Count
    output = $outputItemPath
    reference = $referenceItemPath
} | ConvertTo-Json -Compress
