Set-StrictMode -Version 3.0

$script:NativeMenuSettleConsecutiveSamples = 40
$script:NativeMenuSettleMinimumSpanMilliseconds = 2000
$script:NativeMenuSettleTimeoutMilliseconds = 60000
$script:NativeMenuSettlePollMilliseconds = 55

function Get-NativeMenuStringSha256 {
    param([Parameter(Mandatory = $true)][string]$Value)

    $algorithm = [Security.Cryptography.SHA256]::Create()
    try {
        $bytes = [Text.Encoding]::UTF8.GetBytes($Value)
        return ([BitConverter]::ToString(
            $algorithm.ComputeHash($bytes)
        ) -replace '-', '').ToLowerInvariant()
    } finally {
        $algorithm.Dispose()
    }
}

function Test-NativeMenuOwnedProcess {
    param(
        [Parameter(Mandatory = $true)][int]$ProcessId,
        [Parameter(Mandatory = $true)][string]$ExpectedExecutable
    )

    $process = Get-CimInstance Win32_Process `
        -Filter "ProcessId = $ProcessId" `
        -ErrorAction SilentlyContinue
    return (
        $null -ne $process -and
        $null -ne $process.ExecutablePath -and
        [string]::Equals(
            [IO.Path]::GetFullPath($process.ExecutablePath),
            $ExpectedExecutable,
            [StringComparison]::OrdinalIgnoreCase
        )
    )
}

function Invoke-NativeMenuGit {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string[]]$Arguments
    )

    $result = @(& git -C $Root @Arguments 2>&1)
    if ($LASTEXITCODE -ne 0) {
        throw (
            "BROKEN: git could not derive native-menu capture provenance: " +
            (($result | ForEach-Object { [string]$_ }) -join "`n")
        )
    }
    return (($result | ForEach-Object { [string]$_ }) -join "`n").Trim()
}

function New-NativeMenuCaptureContext {
    param(
        [Parameter(Mandatory = $true)][string]$Root,
        [Parameter(Mandatory = $true)][string]$Instance,
        [Parameter(Mandatory = $true)][int]$ProcessId
    )

    $instanceRoot = Join-Path $Root (
        "runtime\instances\" + $Instance.ToLowerInvariant()
    )
    $expectedExecutable = [IO.Path]::GetFullPath(
        (Join-Path $instanceRoot "stage\SolomonDark.exe")
    )
    $injectedLoader = [IO.Path]::GetFullPath(
        (Join-Path $Root "dist\launcher\SolomonDarkModLoader.dll")
    )
    if (-not (Test-NativeMenuOwnedProcess `
        -ProcessId $ProcessId `
        -ExpectedExecutable $expectedExecutable)) {
        throw "BROKEN: PID $ProcessId does not own the exact $Instance staged executable."
    }
    if (-not (Test-Path -LiteralPath $injectedLoader -PathType Leaf)) {
        throw "BROKEN: the repository launcher-side loader DLL is missing."
    }

    $baseCommitSha = Invoke-NativeMenuGit `
        -Root $Root `
        -Arguments @("rev-parse", "HEAD")
    if ($baseCommitSha -notmatch '^[0-9a-f]{40}$') {
        throw "BROKEN: git returned an invalid base commit for native-menu capture."
    }
    $sourceTreeSha = Invoke-NativeMenuGit `
        -Root $Root `
        -Arguments @("rev-parse", "HEAD^{tree}")
    if ($sourceTreeSha -notmatch '^[0-9a-f]{40}$') {
        throw "BROKEN: git returned an invalid source tree for native-menu capture."
    }
    $trackedChanges = Invoke-NativeMenuGit `
        -Root $Root `
        -Arguments @("status", "--porcelain", "--untracked-files=no")
    if (-not [string]::IsNullOrWhiteSpace($trackedChanges)) {
        throw (
            "BROKEN: native-menu capture requires a clean tracked tree so " +
            "base_commit_sha describes the running recorder."
        )
    }

    $pythonLauncher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($null -eq $pythonLauncher) {
        throw "BROKEN: py.exe is not available to run the Lua exec client."
    }
    $pythonProbe = @(& py.exe -3 -c "print('native-menu-python-ready')" 2>&1)
    if (
        $LASTEXITCODE -ne 0 -or
        (($pythonProbe | ForEach-Object { [string]$_ }) -join "`n").Trim() -ne
            "native-menu-python-ready"
    ) {
        throw "BROKEN: py.exe exists but cannot run the Python 3 Lua exec client."
    }

    $luaExecClient = Join-Path $Root "tools\lua-exec.py"
    if (-not (Test-Path -LiteralPath $luaExecClient -PathType Leaf)) {
        throw "BROKEN: the Lua exec client is missing from the capture tree."
    }

    $gameExecutableSha256 = (
        Get-FileHash -LiteralPath $expectedExecutable -Algorithm SHA256
    ).Hash.ToLowerInvariant()
    $loaderDllSha256 = (
        Get-FileHash -LiteralPath $injectedLoader -Algorithm SHA256
    ).Hash.ToLowerInvariant()
    $compatibilityPath = Join-Path $instanceRoot (
        "stage\.sdmod\multiplayer-compatibility.json"
    )
    if (-not (Test-Path -LiteralPath $compatibilityPath -PathType Leaf)) {
        throw "BROKEN: the staged launcher compatibility receipt is missing."
    }
    $compatibility = Get-Content -LiteralPath $compatibilityPath -Raw |
        ConvertFrom-Json
    if (
        [string]$compatibility.compatibility.gameExecutable.sha256 -ne
            $gameExecutableSha256 -or
        [string]$compatibility.compatibility.loader.sha256 -ne
            $loaderDllSha256
    ) {
        throw (
            "BROKEN: staged compatibility receipt does not identify the " +
            "exact game and launcher-side loader being hashed."
        )
    }

    $source = [ordered]@{
        base_commit_sha = $baseCommitSha
        source_tree_sha = $sourceTreeSha
        capture_tree = "exact committed tree at base_commit_sha"
        game_executable_sha256 = $gameExecutableSha256
        loader_dll_sha256 = $loaderDllSha256
    }
    return [pscustomobject]@{
        Root = $Root
        Instance = $Instance
        ProcessId = $ProcessId
        ExpectedExecutable = $expectedExecutable
        InjectedLoader = $injectedLoader
        PipeName = "SolomonDarkModLoader_LuaExec_$Instance"
        LuaExecClient = $luaExecClient
        Source = $source
    }
}

function Invoke-NativeMenuLua {
    param(
        [Parameter(Mandatory = $true)][object]$Context,
        [Parameter(Mandatory = $true)][string]$LuaCode,
        [switch]$AllowBusy
    )

    $previousPipe = $env:SDMOD_LUA_EXEC_PIPE_NAME
    try {
        $env:SDMOD_LUA_EXEC_PIPE_NAME = $Context.PipeName
        $result = @($LuaCode | & py.exe -3 $Context.LuaExecClient 2>&1)
        $exitCode = $LASTEXITCODE
    } finally {
        $env:SDMOD_LUA_EXEC_PIPE_NAME = $previousPipe
    }
    $text = (($result | ForEach-Object { [string]$_ }) -join "`n").TrimEnd()
    if ($exitCode -eq 0) {
        return [pscustomobject]@{ Status = "ready"; Text = $text }
    }

    if (-not (Test-NativeMenuOwnedProcess `
        -ProcessId $Context.ProcessId `
        -ExpectedExecutable $Context.ExpectedExecutable)) {
        throw (
            "BROKEN: the exact staged process exited while the native-menu " +
            "recorder was waiting for Lua exec."
        )
    }
    $pipeUnavailable = (
        $text -match 'Cannot connect to pipe' -or
        $text -match 'timed out waiting for pipe' -or
        $text -match 'mod loader or Lua runtime may not be initialized yet'
    )
    if ($AllowBusy -and $pipeUnavailable) {
        return [pscustomobject]@{ Status = "busy"; Text = $text }
    }
    throw "BROKEN: Lua exec failed while the owned process remained alive: $text"
}

function Get-NativeMenuLayoutProbe {
    param(
        [Parameter(Mandatory = $true)][object]$Context,
        [Parameter(Mandatory = $true)][string]$ScreenId,
        [string]$FramePath = ""
    )

    $captureFrame = ""
    if (-not [string]::IsNullOrWhiteSpace($FramePath)) {
        $captureFrame = @"
local frame_ok, frame_message = sd.debug.capture_backbuffer([=[$FramePath]=])
if not frame_ok then error(tostring(frame_message)) end
"@
    }
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
local semantic = sd.ui.get_snapshot()
local snapshot = sd.ui.capture_current_layout([=[$ScreenId]=])
if type(snapshot) ~= 'table' then
  return '__NATIVE_MENU_LAYOUT_NOT_READY__'
end
local output = {
  '{',
  '"generation":' .. tostring(snapshot.generation or 0) .. ',',
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
$captureFrame
return table.concat({
  '__SURFACE__=' .. tostring(semantic and semantic.surface_id or ''),
  '__SEMANTIC_GENERATION__=' .. tostring(semantic and semantic.generation or 0),
  '__CAPTURED_AT__=' .. tostring(snapshot.captured_at_milliseconds or 0),
  '__PAYLOAD__=' .. table.concat(output)
}, '\n')
"@
    $result = Invoke-NativeMenuLua `
        -Context $Context `
        -LuaCode $lua `
        -AllowBusy
    if ($result.Status -eq "busy") {
        return [pscustomobject]@{ Status = "busy"; Detail = $result.Text }
    }
    if ($result.Text -eq "__NATIVE_MENU_LAYOUT_NOT_READY__") {
        return [pscustomobject]@{
            Status = "not_ready"
            Detail = "capture_current_layout returned no current frame"
        }
    }
    $parts = @($result.Text -split "`r?`n", 4)
    if (
        $parts.Count -ne 4 -or
        -not $parts[0].StartsWith("__SURFACE__=") -or
        -not $parts[1].StartsWith("__SEMANTIC_GENERATION__=") -or
        -not $parts[2].StartsWith("__CAPTURED_AT__=") -or
        -not $parts[3].StartsWith("__PAYLOAD__=")
    ) {
        throw "BROKEN: malformed native-menu semantic probe: $($result.Text)"
    }
    $semanticJson = $parts[3].Substring("__PAYLOAD__=".Length)
    try {
        $semanticPayload = $semanticJson | ConvertFrom-Json
    } catch {
        throw "BROKEN: native-menu semantic probe returned invalid JSON: $semanticJson"
    }
    return [pscustomobject]@{
        Status = "ready"
        SemanticSurface = $parts[0].Substring("__SURFACE__=".Length)
        SemanticGeneration = [uint64]$parts[1].Substring(
            "__SEMANTIC_GENERATION__=".Length
        )
        CapturedAtMilliseconds = [uint64]$parts[2].Substring(
            "__CAPTURED_AT__=".Length
        )
        SemanticJson = $semanticJson
        SemanticPayload = $semanticPayload
    }
}

function Wait-NativeMenuLayoutSettlement {
    param(
        [Parameter(Mandatory = $true)][object]$Context,
        [Parameter(Mandatory = $true)][string]$ScreenId,
        [Parameter(Mandatory = $true)][Diagnostics.Stopwatch]$LatencyClock
    )

    $stableJson = ""
    $stableStartMilliseconds = 0L
    $stableCount = 0
    $sampleCount = 0
    $busyCount = 0
    $notReadyCount = 0
    $lastUnavailable = ""
    $distinctOrder = [Collections.Generic.List[string]]::new()
    $distinctByHash = @{}

    while ($LatencyClock.ElapsedMilliseconds -le
        $script:NativeMenuSettleTimeoutMilliseconds) {
        $probe = Get-NativeMenuLayoutProbe `
            -Context $Context `
            -ScreenId $ScreenId
        if ($probe.Status -ne "ready") {
            if ($probe.Status -eq "busy") {
                $busyCount += 1
            } else {
                $notReadyCount += 1
            }
            $lastUnavailable = [string]$probe.Detail
            Start-Sleep -Milliseconds $script:NativeMenuSettlePollMilliseconds
            continue
        }

        $sampleCount += 1
        $elapsed = [long]$LatencyClock.ElapsedMilliseconds
        $hash = Get-NativeMenuStringSha256 $probe.SemanticJson
        if (-not $distinctByHash.ContainsKey($hash)) {
            $entry = [ordered]@{
                semantic_sha256 = $hash
                first_seen_milliseconds = $elapsed
                last_seen_milliseconds = $elapsed
                observations = 1
                payload = $probe.SemanticPayload
            }
            $distinctByHash[$hash] = $entry
            $distinctOrder.Add($hash)
        } else {
            $entry = $distinctByHash[$hash]
            $entry["last_seen_milliseconds"] = $elapsed
            $entry["observations"] = [int]$entry["observations"] + 1
        }

        if ($probe.SemanticJson -ceq $stableJson) {
            $stableCount += 1
        } else {
            $stableJson = $probe.SemanticJson
            $stableStartMilliseconds = $elapsed
            $stableCount = 1
        }
        $stableSpan = $elapsed - $stableStartMilliseconds
        if (
            $stableCount -ge $script:NativeMenuSettleConsecutiveSamples -and
            $stableSpan -ge $script:NativeMenuSettleMinimumSpanMilliseconds
        ) {
            $distinctPayloads = [Collections.Generic.List[object]]::new()
            foreach ($distinctHash in $distinctOrder) {
                $distinctPayloads.Add($distinctByHash[$distinctHash])
            }
            return [pscustomobject]@{
                Probe = $probe
                Summary = [ordered]@{
                    criterion = (
                        "at least 40 consecutive byte-identical semantic " +
                        "payloads spanning at least 2 seconds"
                    )
                    settle_latency_milliseconds = $elapsed
                    stable_span_milliseconds = $stableSpan
                    consecutive_identical_samples = $stableCount
                    total_semantic_samples = $sampleCount
                    busy_probe_count = $busyCount
                    not_ready_probe_count = $notReadyCount
                    semantic_sha256 = $hash
                }
                DistinctPayloads = $distinctPayloads
            }
        }
        Start-Sleep -Milliseconds $script:NativeMenuSettlePollMilliseconds
    }

    throw (
        "STOP: '$ScreenId' never settled to 40 consecutive byte-identical " +
        "semantic payloads spanning at least 2 seconds within 60 seconds. " +
        "samples=$sampleCount busy=$busyCount not_ready=$notReadyCount " +
        "last_unavailable='$lastUnavailable'"
    )
}

function ConvertTo-NativeMenuLayout {
    param(
        [Parameter(Mandatory = $true)][object]$SemanticPayload,
        [Parameter(Mandatory = $true)][uint64]$CapturedAtMilliseconds
    )

    return [ordered]@{
        generation = [uint64]$SemanticPayload.generation
        captured_at_milliseconds = $CapturedAtMilliseconds
        screen_id = [string]$SemanticPayload.screen_id
        screen_title = [string]$SemanticPayload.screen_title
        capture_method = [string]$SemanticPayload.capture_method
        elements = @($SemanticPayload.elements)
    }
}

function Get-SettledNativeMenuObservation {
    param(
        [Parameter(Mandatory = $true)][object]$Context,
        [Parameter(Mandatory = $true)][string]$ScreenId,
        [Parameter(Mandatory = $true)][string]$FramePath,
        [Parameter(Mandatory = $true)][Diagnostics.Stopwatch]$LatencyClock
    )

    while ($true) {
        $settled = Wait-NativeMenuLayoutSettlement `
            -Context $Context `
            -ScreenId $ScreenId `
            -LatencyClock $LatencyClock
        if (Test-Path -LiteralPath $FramePath -PathType Leaf) {
            Remove-Item -LiteralPath $FramePath -Force
        }
        $frameProbe = Get-NativeMenuLayoutProbe `
            -Context $Context `
            -ScreenId $ScreenId `
            -FramePath $FramePath
        if (
            $frameProbe.Status -ne "ready" -or
            $frameProbe.SemanticJson -cne $settled.Probe.SemanticJson
        ) {
            if ($LatencyClock.ElapsedMilliseconds -gt
                $script:NativeMenuSettleTimeoutMilliseconds) {
                throw (
                    "STOP: '$ScreenId' changed while its settled frame was " +
                    "captured and did not re-settle within 60 seconds."
                )
            }
            continue
        }
        if (-not (Test-Path -LiteralPath $FramePath -PathType Leaf)) {
            throw "BROKEN: settled native-menu probe did not create its frame capture."
        }

        $payload = $frameProbe.SemanticPayload
        return [pscustomobject]@{
            semantic_surface = $frameProbe.SemanticSurface
            semantic_generation = $frameProbe.SemanticGeneration
            tagged_screen = [string]$payload.screen_id
            layout_generation = [uint64]$payload.generation
            element_count = @($payload.elements).Count
            capture_method = [string]$payload.capture_method
            frame_sha256 = (
                Get-FileHash -LiteralPath $FramePath -Algorithm SHA256
            ).Hash.ToLowerInvariant()
            settlement = $settled.Summary
            layout = ConvertTo-NativeMenuLayout `
                -SemanticPayload $payload `
                -CapturedAtMilliseconds $frameProbe.CapturedAtMilliseconds
            settlement_trace = @($settled.DistinctPayloads)
        }
    }
}

function Convert-NativeMenuBmpToPng {
    param(
        [Parameter(Mandatory = $true)][string]$SourcePath,
        [Parameter(Mandatory = $true)][string]$DestinationPath
    )

    Add-Type -AssemblyName System.Drawing
    $image = [Drawing.Image]::FromFile($SourcePath)
    try {
        $image.Save($DestinationPath, [Drawing.Imaging.ImageFormat]::Png)
    } finally {
        $image.Dispose()
    }
}
