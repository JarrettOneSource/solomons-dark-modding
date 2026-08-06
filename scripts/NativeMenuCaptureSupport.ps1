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
    $settlementClassifier = Join-Path $Root (
        "tools\native_menu_settlement_v2.py"
    )
    if (-not (Test-Path -LiteralPath $settlementClassifier -PathType Leaf)) {
        throw "BROKEN: the Settlement v2 classifier is missing from the capture tree."
    }
    $startupLog = Join-Path $instanceRoot (
        "stage\.sdmod\logs\solomondarkmodloader.log"
    )
    if (-not (Test-Path -LiteralPath $startupLog -PathType Leaf)) {
        throw "BROKEN: the exact staged process has no loader startup log."
    }
    $captureHookReady = Select-String `
        -LiteralPath $startupLog `
        -SimpleMatch `
        -Quiet `
        -Pattern "Debug UI native menu-layout capture hooks installed."
    if (-not $captureHookReady) {
        throw (
            "BROKEN: the exact staged process did not install native menu-layout " +
            "capture hooks; launch it with SDMOD_NATIVE_MENU_LAYOUT_CAPTURE=1."
        )
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
        SettlementClassifier = $settlementClassifier
        StartupLog = $startupLog
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
local structure = {
  '{',
  '"generation":' .. tostring(snapshot.generation or 0) .. ',',
  '"screen_id":' .. quote(snapshot.screen_id) .. ',',
  '"screen_title":' .. quote(snapshot.screen_title) .. ',',
  '"capture_method":' .. quote(snapshot.capture_method) .. ',',
  '"elements":['
}
for index, element in ipairs(snapshot.elements or {}) do
  if index > 1 then
    output[#output + 1] = ','
    structure[#structure + 1] = ','
  end
  local core = table.concat({
    '{"id":', quote(element.id),
    ',"kind":', quote(element.kind),
    ',"text":', quote(element.text),
    ',"action_id":', quote(element.action_id),
    ',"art_id":', quote(element.art_id),
    ',"font_id":', quote(element.font_id),
    ',"text_style":', quote(element.text_style),
    ',"visible":', boolean(element.visible),
    ',"interactive":', boolean(element.interactive),
    ',"draw_order":', tostring(element.draw_order or 0)
  })
  structure[#structure + 1] = core .. '}'
  output[#output + 1] = core .. table.concat({
    ',"rect":[', number(element.left), ',', number(element.top), ',',
      number(element.right), ',', number(element.bottom), ']',
    ',"unclipped_rect":[', number(element.unclipped_left), ',',
      number(element.unclipped_top), ',', number(element.unclipped_right),
      ',', number(element.unclipped_bottom), ']}'
  })
end
output[#output + 1] = ']}'
structure[#structure + 1] = ']}'
$captureFrame
return table.concat({
  '__SURFACE__=' .. tostring(semantic and semantic.surface_id or ''),
  '__SEMANTIC_GENERATION__=' .. tostring(semantic and semantic.generation or 0),
  '__CAPTURED_AT__=' .. tostring(snapshot.captured_at_milliseconds or 0),
  '__STRUCTURE__=' .. table.concat(structure),
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
    $parts = @($result.Text -split "`r?`n", 5)
    if (
        $parts.Count -ne 5 -or
        -not $parts[0].StartsWith("__SURFACE__=") -or
        -not $parts[1].StartsWith("__SEMANTIC_GENERATION__=") -or
        -not $parts[2].StartsWith("__CAPTURED_AT__=") -or
        -not $parts[3].StartsWith("__STRUCTURE__=") -or
        -not $parts[4].StartsWith("__PAYLOAD__=")
    ) {
        throw "BROKEN: malformed native-menu semantic probe: $($result.Text)"
    }
    $nonGeometryJson = $parts[3].Substring("__STRUCTURE__=".Length)
    $semanticJson = $parts[4].Substring("__PAYLOAD__=".Length)
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
        NonGeometryJson = $nonGeometryJson
        SemanticJson = $semanticJson
        SemanticPayload = $semanticPayload
    }
}

function Invoke-NativeMenuSettlementClassifier {
    param(
        [Parameter(Mandatory = $true)][object]$Context,
        [Parameter(Mandatory = $true)][object[]]$Samples
    )

    $temporaryDirectory = Join-Path ([IO.Path]::GetTempPath()) (
        "sdmod-menu-settlement-v2-" + [Guid]::NewGuid().ToString("N")
    )
    [IO.Directory]::CreateDirectory($temporaryDirectory) | Out-Null
    $inputPath = Join-Path $temporaryDirectory "samples.json"
    $outputPath = Join-Path $temporaryDirectory "classification.json"
    try {
        [IO.File]::WriteAllText(
            $inputPath,
            (($Samples | ConvertTo-Json -Depth 100) + [Environment]::NewLine),
            [Text.UTF8Encoding]::new($false)
        )
        $classifierOutput = @(
            & py.exe -3 $Context.SettlementClassifier classify `
                --input $inputPath `
                --output $outputPath 2>&1
        )
        if ($LASTEXITCODE -ne 0) {
            $message = (
                ($classifierOutput | ForEach-Object { [string]$_ }) -join "`n"
            ).Trim()
            if ([string]::IsNullOrWhiteSpace($message)) {
                $message = "Settlement v2 classifier exited without diagnostics."
            }
            throw $message
        }
        if (-not (Test-Path -LiteralPath $outputPath -PathType Leaf)) {
            throw "BROKEN: Settlement v2 classifier produced no result."
        }
        return Get-Content -LiteralPath $outputPath -Raw | ConvertFrom-Json
    } finally {
        if (Test-Path -LiteralPath $temporaryDirectory -PathType Container) {
            Remove-Item -LiteralPath $temporaryDirectory -Recurse -Force
        }
    }
}

function Wait-NativeMenuLayoutSettlement {
    param(
        [Parameter(Mandatory = $true)][object]$Context,
        [Parameter(Mandatory = $true)][string]$ScreenId,
        [Parameter(Mandatory = $true)][Diagnostics.Stopwatch]$LatencyClock
    )

    $stableStructureJson = ""
    $stableStartMilliseconds = 0L
    $sampleCount = 0
    $busyCount = 0
    $notReadyCount = 0
    $lastUnavailable = ""
    $structuralPhaseOrder = [Collections.Generic.List[string]]::new()
    $structuralPhaseByHash = @{}
    $stableWindow = [Collections.Generic.List[object]]::new()
    $windowAnchorProbe = $null

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
        $structureHash = Get-NativeMenuStringSha256 $probe.NonGeometryJson
        if (-not $structuralPhaseByHash.ContainsKey($structureHash)) {
            $entry = [ordered]@{
                non_geometry_sha256 = $structureHash
                first_seen_milliseconds = $elapsed
                last_seen_milliseconds = $elapsed
                observations = 1
                payload = $probe.SemanticPayload
            }
            $structuralPhaseByHash[$structureHash] = $entry
            $structuralPhaseOrder.Add($structureHash)
        } else {
            $entry = $structuralPhaseByHash[$structureHash]
            $entry["last_seen_milliseconds"] = $elapsed
            $entry["observations"] = [int]$entry["observations"] + 1
        }

        if ($probe.NonGeometryJson -cne $stableStructureJson) {
            $stableStructureJson = $probe.NonGeometryJson
            $stableStartMilliseconds = $elapsed
            $stableWindow.Clear()
            $windowAnchorProbe = $probe
        }
        $stableWindow.Add([ordered]@{
            elapsed_milliseconds = $elapsed
            captured_at_milliseconds = $probe.CapturedAtMilliseconds
            payload = $probe.SemanticPayload
        })
        $stableSpan = $elapsed - $stableStartMilliseconds
        if (
            $stableWindow.Count -ge $script:NativeMenuSettleConsecutiveSamples -and
            $stableSpan -ge $script:NativeMenuSettleMinimumSpanMilliseconds
        ) {
            $classification = Invoke-NativeMenuSettlementClassifier `
                -Context $Context `
                -Samples @($stableWindow)
            $structuralPhases = [Collections.Generic.List[object]]::new()
            foreach ($phaseHash in $structuralPhaseOrder) {
                $structuralPhases.Add($structuralPhaseByHash[$phaseHash])
            }
            $summary = [ordered]@{
                criterion = [string]$classification.criterion
                settle_latency_milliseconds = (
                    [long]$classification.settle_latency_milliseconds
                )
                stable_span_milliseconds = (
                    [long]$classification.stable_span_milliseconds
                )
                consecutive_structural_samples = (
                    [int]$classification.consecutive_structural_samples
                )
                animated_id_set_sample_count = (
                    [int]$classification.animated_id_set_sample_count
                )
                total_semantic_samples = $sampleCount
                busy_probe_count = $busyCount
                not_ready_probe_count = $notReadyCount
                structural_phase_count = $structuralPhases.Count
                structural_sha256 = [string]$classification.structural_sha256
                animated_element_ids = @(
                    $classification.animated_element_ids
                )
                animated_element_count = (
                    [int]$classification.animated_element_count
                )
                element_count = [int]$classification.element_count
                animated_fraction = [double]$classification.animated_fraction
            }
            return [pscustomobject]@{
                AnchorProbe = $windowAnchorProbe
                Summary = $summary
                Layout = $classification.layout
                AnimatedElementIds = @($classification.animated_element_ids)
                NonGeometryJson = $stableStructureJson
                StructuralPhases = $structuralPhases
                SettledWindowSamples = @($stableWindow)
            }
        }
        Start-Sleep -Milliseconds $script:NativeMenuSettlePollMilliseconds
    }

    throw (
        "STOP: '$ScreenId' never settled to 40 consecutive structurally " +
        "byte-identical payloads with one measured animated ID set spanning " +
        "at least 2 seconds within 60 seconds. " +
        "samples=$sampleCount busy=$busyCount not_ready=$notReadyCount " +
        "last_unavailable='$lastUnavailable'"
    )
}

function Test-NativeMenuFrameMatchesSettlement {
    param(
        [Parameter(Mandatory = $true)][object]$FrameProbe,
        [Parameter(Mandatory = $true)][object]$Settlement
    )

    if (
        $FrameProbe.Status -ne "ready" -or
        $FrameProbe.NonGeometryJson -cne $Settlement.NonGeometryJson
    ) {
        return $false
    }
    $animated = @{}
    foreach ($elementId in @($Settlement.AnimatedElementIds)) {
        $animated[[string]$elementId] = $true
    }
    $frameById = @{}
    foreach ($element in @($FrameProbe.SemanticPayload.elements)) {
        $elementId = [string]$element.id
        if ($frameById.ContainsKey($elementId)) {
            throw "BROKEN: settled frame contains ambiguous duplicate element '$elementId'."
        }
        $frameById[$elementId] = $element
    }
    foreach ($element in @($Settlement.Layout.elements)) {
        $elementId = [string]$element.id
        if (-not $frameById.ContainsKey($elementId)) {
            return $false
        }
        if ($animated.ContainsKey($elementId)) {
            continue
        }
        $frameElement = $frameById[$elementId]
        $expectedGeometry = [ordered]@{
            rect = @($element.rect)
            unclipped_rect = @($element.unclipped_rect)
        } | ConvertTo-Json -Compress
        $frameGeometry = [ordered]@{
            rect = @($frameElement.rect)
            unclipped_rect = @($frameElement.unclipped_rect)
        } | ConvertTo-Json -Compress
        if ($frameGeometry -cne $expectedGeometry) {
            return $false
        }
    }
    return $true
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
        if (-not (Test-NativeMenuFrameMatchesSettlement `
            -FrameProbe $frameProbe `
            -Settlement $settled)) {
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

        $layout = $settled.Layout
        return [pscustomobject]@{
            semantic_surface = $settled.AnchorProbe.SemanticSurface
            semantic_generation = $settled.AnchorProbe.SemanticGeneration
            tagged_screen = [string]$layout.screen_id
            layout_generation = [uint64]$layout.generation
            element_count = @($layout.elements).Count
            animated_element_ids = @($settled.AnimatedElementIds)
            capture_method = [string]$layout.capture_method
            frame_sha256 = (
                Get-FileHash -LiteralPath $FramePath -Algorithm SHA256
            ).Hash.ToLowerInvariant()
            settlement = $settled.Summary
            layout = $layout
            settlement_trace = [ordered]@{
                structural_phases = @($settled.StructuralPhases)
                settled_window_samples = @($settled.SettledWindowSamples)
            }
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
