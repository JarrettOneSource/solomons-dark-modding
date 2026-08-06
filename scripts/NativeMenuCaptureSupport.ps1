Set-StrictMode -Version 3.0

$script:NativeMenuSettleConsecutiveSamples = 40
$script:NativeMenuSettleMinimumSpanMilliseconds = 2000
$script:NativeMenuSettleTimeoutMilliseconds = 60000
$script:NativeMenuSettlePollMilliseconds = 55
$script:NativeMenuExtendedMinimumMilliseconds = 60000
$script:NativeMenuExtendedSpanMultiplier = 10
$script:NativeMenuExtendedMinimumSamples = 200
$script:NativeMenuPopulationPhaseLimit = 4096
$script:NativeMenuActionDispatchTimeoutMilliseconds = 15000
$script:NativeMenuActionDispatchPollMilliseconds = 50

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
    $overlayReference = Join-Path $Root (
        "tests\fixtures\webgame\menu-overlay-reference.json"
    )
    if (-not (Test-Path -LiteralPath $overlayReference -PathType Leaf)) {
        throw "BROKEN: the machine-derived native-menu overlay reference is missing."
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
        OverlayReference = $overlayReference
        StartupLog = $startupLog
        Source = $source
    }
}

function Assert-NativeMenuOverlayHygiene {
    param(
        [Parameter(Mandatory = $true)][object]$Context,
        [Parameter(Mandatory = $true)][object]$Layout
    )

    $temporaryDirectory = Join-Path ([IO.Path]::GetTempPath()) (
        "sdmod-menu-overlay-hygiene-" + [Guid]::NewGuid().ToString("N")
    )
    [IO.Directory]::CreateDirectory($temporaryDirectory) | Out-Null
    $layoutPath = Join-Path $temporaryDirectory "layout.json"
    try {
        [IO.File]::WriteAllText(
            $layoutPath,
            (($Layout | ConvertTo-Json -Depth 100) + [Environment]::NewLine),
            [Text.UTF8Encoding]::new($false)
        )
        $result = @(
            & py.exe -3 $Context.SettlementClassifier check-overlay `
                --layout $layoutPath `
                --reference $Context.OverlayReference 2>&1
        )
        if ($LASTEXITCODE -ne 0) {
            $message = (
                ($result | ForEach-Object { [string]$_ }) -join "`n"
            ).Trim()
            if ([string]::IsNullOrWhiteSpace($message)) {
                $message = "STOP: native-menu overlay hygiene failed without diagnostics."
            }
            throw $message
        }
    } finally {
        if (Test-Path -LiteralPath $temporaryDirectory -PathType Container) {
            Remove-Item -LiteralPath $temporaryDirectory -Recurse -Force
        }
    }
}

function Invoke-NativeMenuLua {
    param(
        [Parameter(Mandatory = $true)][object]$Context,
        [Parameter(Mandatory = $true)][string]$LuaCode,
        [switch]$AllowBusy
    )

    $previousPipe = $env:SDMOD_LUA_EXEC_PIPE_NAME
    $previousErrorActionPreference = $ErrorActionPreference
    try {
        $env:SDMOD_LUA_EXEC_PIPE_NAME = $Context.PipeName
        # Windows PowerShell promotes a native process's stderr to an
        # ErrorRecord.  Keep it in the merged result so the exit code and exact
        # text below can distinguish a contended pipe from a broken process.
        $ErrorActionPreference = "Continue"
        $result = @($LuaCode | & py.exe -3 $Context.LuaExecClient 2>&1)
        $exitCode = $LASTEXITCODE
    } finally {
        $env:SDMOD_LUA_EXEC_PIPE_NAME = $previousPipe
        $ErrorActionPreference = $previousErrorActionPreference
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

function Wait-NativeMenuActionDispatch {
    param(
        [Parameter(Mandatory = $true)][object]$Context,
        [Parameter(Mandatory = $true)][int]$RequestId,
        [Parameter(Mandatory = $true)][string]$ActionId
    )

    $clock = [Diagnostics.Stopwatch]::StartNew()
    $lastStatus = "not_ready"
    while ($clock.ElapsedMilliseconds -le
        $script:NativeMenuActionDispatchTimeoutMilliseconds) {
        $result = Invoke-NativeMenuLua `
            -Context $Context `
            -AllowBusy `
            -LuaCode @"
local function quote(value)
  value = tostring(value or '')
  value = value:gsub('\\', '\\\\')
  value = value:gsub('"', '\\"')
  value = value:gsub('\n', '\\n')
  value = value:gsub('\r', '\\r')
  value = value:gsub('\t', '\\t')
  return '"' .. value .. '"'
end
local dispatch = sd.ui.get_action_dispatch($RequestId)
if type(dispatch) ~= 'table' then
  return '{"status":"not_ready","error_message":""}'
end
return table.concat({
  '{"status":', quote(dispatch.status),
  ',"error_message":', quote(dispatch.error_message), '}'
})
"@
        if ($result.Status -eq "busy") {
            $lastStatus = "pipe_busy"
        } else {
            try {
                $dispatch = $result.Text | ConvertFrom-Json
            } catch {
                throw (
                    "BROKEN: native-menu action dispatch '$ActionId' returned " +
                    "invalid lifecycle JSON."
                )
            }
            $lastStatus = [string]$dispatch.status
            if ($lastStatus -ceq "dispatched") {
                return $dispatch
            }
            if ($lastStatus -ceq "failed") {
                throw (
                    "BROKEN: native-menu action dispatch '$ActionId' failed: " +
                    [string]$dispatch.error_message
                )
            }
            if ($lastStatus -notin @("not_ready", "queued", "dispatching")) {
                throw (
                    "BROKEN: native-menu action dispatch '$ActionId' reported " +
                    "unknown status '$lastStatus'."
                )
            }
        }
        Start-Sleep -Milliseconds `
            $script:NativeMenuActionDispatchPollMilliseconds
    }
    throw (
        "BROKEN: native-menu action dispatch '$ActionId' never became " +
        "runnable within $script:NativeMenuActionDispatchTimeoutMilliseconds " +
        "milliseconds; last_status='$lastStatus'."
    )
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
local function core(element)
  return table.concat({
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
  end
  output[#output + 1] = core(element) .. table.concat({
    ',"rect":[', number(element.left), ',', number(element.top), ',',
      number(element.right), ',', number(element.bottom), ']',
    ',"unclipped_rect":[', number(element.unclipped_left), ',',
      number(element.unclipped_top), ',', number(element.unclipped_right),
      ',', number(element.unclipped_bottom), ']}'
  })
end
local structural_elements = {}
for index, element in ipairs(snapshot.elements or {}) do
  structural_elements[index] = element
end
table.sort(structural_elements, function(left, right)
  local left_order = tonumber(left.draw_order) or 0
  local right_order = tonumber(right.draw_order) or 0
  if left_order ~= right_order then return left_order < right_order end
  return tostring(left.id or '') < tostring(right.id or '')
end)
for index, element in ipairs(structural_elements) do
  if index > 1 then structure[#structure + 1] = ',' end
  structure[#structure + 1] = core(element) .. '}'
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

function Initialize-NativeMenuPopulationSampler {
    param([Parameter(Mandatory = $true)][object]$Context)

    $result = Invoke-NativeMenuLua -Context $Context -LuaCode @"
local sampler = rawget(_G, '__sd_native_menu_population_sampler')
if sampler == nil then
  sampler = {
    active = false,
    by_structure = {},
    phases = {},
    sample_count = 0,
    overflow = false,
    error = ''
  }
  rawset(_G, '__sd_native_menu_population_sampler', sampler)
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
  local function boolean(value)
    return value and 'true' or 'false'
  end
  local function core(element)
    return table.concat({
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
  end
  local function compact(element)
    return table.concat({
      '[', quote(element.id),
      ',', quote(element.kind),
      ',', quote(element.text),
      ',', quote(element.action_id),
      ',', quote(element.art_id),
      ',', quote(element.font_id),
      ',', quote(element.text_style),
      ',', boolean(element.visible),
      ',', boolean(element.interactive),
      ',', tostring(element.draw_order or 0),
      ',[', tostring(element.left or 0), ',', tostring(element.top or 0),
      ',', tostring(element.right or 0), ',', tostring(element.bottom or 0), ']',
      ',[', tostring(element.unclipped_left or 0),
      ',', tostring(element.unclipped_top or 0),
      ',', tostring(element.unclipped_right or 0),
      ',', tostring(element.unclipped_bottom or 0), ']]'
    })
  end
  sd.events.on('runtime.tick', function(event)
    local state = rawget(_G, '__sd_native_menu_population_sampler')
    if state == nil or not state.active then return end
    local ok, detail = pcall(function()
      local semantic = sd.ui.get_snapshot()
      if state.expected_surface ~= '' and
          tostring(semantic and semantic.surface_id or '') ~=
            state.expected_surface then
        return
      end
      local snapshot = sd.ui.capture_current_layout(state.screen_id)
      if type(snapshot) ~= 'table' then return end
      local structural_elements = {}
      for index, element in ipairs(snapshot.elements or {}) do
        structural_elements[index] = element
      end
      table.sort(structural_elements, function(left, right)
        local left_order = tonumber(left.draw_order) or 0
        local right_order = tonumber(right.draw_order) or 0
        if left_order ~= right_order then return left_order < right_order end
        return tostring(left.id or '') < tostring(right.id or '')
      end)
      local structure_elements = {}
      for index, element in ipairs(structural_elements) do
        structure_elements[index] = core(element) .. '}'
      end
      local payload_elements = {}
      for index, element in ipairs(snapshot.elements or {}) do
        payload_elements[index] = compact(element)
      end
      local prefix = table.concat({
        '{"generation":', tostring(snapshot.generation or 0),
        ',"screen_id":', quote(snapshot.screen_id),
        ',"screen_title":', quote(snapshot.screen_title),
        ',"capture_method":', quote(snapshot.capture_method),
        ',"elements":['
      })
      local structure = prefix .. table.concat(structure_elements, ',') .. ']}'
      local payload = prefix .. table.concat(payload_elements, ',') .. ']}'
      local now = tonumber(event and event.monotonic_milliseconds) or 0
      state.sample_count = state.sample_count + 1
      local phase_index = state.by_structure[structure]
      if phase_index ~= nil then
        local phase = state.phases[phase_index]
        phase.last_seen_milliseconds = now
        phase.observations = phase.observations + 1
        return
      end
      if #state.phases >= $script:NativeMenuPopulationPhaseLimit then
        state.overflow = true
        state.active = false
        return
      end
      state.phases[#state.phases + 1] = {
        first_seen_milliseconds = now,
        last_seen_milliseconds = now,
        observations = 1,
        payload_json = payload
      }
      state.by_structure[structure] = #state.phases
    end)
    if not ok then
      state.error = tostring(detail)
      state.active = false
    end
  end)
end
return 'population-sampler-ready'
"@
    if ($result.Text.Trim() -ne "population-sampler-ready") {
        throw "BROKEN: native-menu population sampler did not initialize."
    }
}

function Start-NativeMenuPopulationSampler {
    param(
        [Parameter(Mandatory = $true)][object]$Context,
        [Parameter(Mandatory = $true)][string]$ScreenId,
        [string]$ExpectedSurface = ""
    )

    $result = Invoke-NativeMenuLua -Context $Context -LuaCode @"
local sampler = rawget(_G, '__sd_native_menu_population_sampler')
if sampler == nil then error('population sampler was not initialized') end
sampler.active = false
sampler.by_structure = {}
sampler.phases = {}
sampler.sample_count = 0
sampler.overflow = false
sampler.error = ''
sampler.screen_id = [=[$ScreenId]=]
sampler.expected_surface = [=[$ExpectedSurface]=]
sampler.active = true
return 'population-sampler-armed'
"@
    if ($result.Text.Trim() -ne "population-sampler-armed") {
        throw "BROKEN: native-menu population sampler did not arm."
    }
}

function Stop-NativeMenuPopulationSampler {
    param([Parameter(Mandatory = $true)][object]$Context)

    $result = Invoke-NativeMenuLua -Context $Context -LuaCode @'
local sampler = rawget(_G, '__sd_native_menu_population_sampler')
if sampler == nil then error('population sampler was not initialized') end
sampler.active = false
local function quote(value)
  value = tostring(value or '')
  value = value:gsub('\\', '\\\\')
  value = value:gsub('"', '\\"')
  value = value:gsub('\n', '\\n')
  value = value:gsub('\r', '\\r')
  value = value:gsub('\t', '\\t')
  return '"' .. value .. '"'
end
return table.concat({
  '{"sample_count":', tostring(sampler.sample_count or 0),
  ',"overflow":', sampler.overflow and 'true' or 'false',
  ',"error":', quote(sampler.error),
  ',"phase_count":', tostring(#(sampler.phases or {})), '}'
})
'@
    try {
        $metadata = $result.Text | ConvertFrom-Json
    } catch {
        throw "BROKEN: native-menu population sampler returned invalid metadata."
    }
    if (-not [string]::IsNullOrWhiteSpace([string]$metadata.error)) {
        throw "BROKEN: native-menu population sampler failed: $($metadata.error)"
    }
    if ([bool]$metadata.overflow) {
        throw (
            "STOP: native-menu population sampler exceeded " +
            "$script:NativeMenuPopulationPhaseLimit structural phases."
        )
    }
    $phaseCount = [int]$metadata.phase_count
    if ([int]$metadata.sample_count -le 0 -or $phaseCount -le 0) {
        throw "STOP: native-menu population sampler observed no destination phase."
    }
    if ($phaseCount -gt $script:NativeMenuPopulationPhaseLimit) {
        throw "BROKEN: native-menu population phase count exceeded its declared limit."
    }

    $phases = [Collections.Generic.List[object]]::new()
    try {
        for ($phaseIndex = 1; $phaseIndex -le $phaseCount; $phaseIndex++) {
            $phaseResult = Invoke-NativeMenuLua -Context $Context -LuaCode @"
local sampler = rawget(_G, '__sd_native_menu_population_sampler')
if sampler == nil then error('population sampler was not initialized') end
local phase = (sampler.phases or {})[$phaseIndex]
if phase == nil then error('population sampler phase is absent') end
return table.concat({
  '{"first_seen_milliseconds":',
    tostring(phase.first_seen_milliseconds or 0),
  ',"last_seen_milliseconds":',
    tostring(phase.last_seen_milliseconds or 0),
  ',"observations":', tostring(phase.observations or 0),
  ',"payload_encoding":"structural-element-arrays-v1"',
  ',"payload":', phase.payload_json, '}'
})
"@
            try {
                $phases.Add(($phaseResult.Text | ConvertFrom-Json))
            } catch {
                throw (
                    "BROKEN: native-menu population sampler phase " +
                    "$phaseIndex returned invalid JSON."
                )
            }
        }
    } finally {
        Invoke-NativeMenuLua -Context $Context -LuaCode @'
local sampler = rawget(_G, '__sd_native_menu_population_sampler')
if sampler ~= nil then
  sampler.by_structure = {}
  sampler.phases = {}
end
return 'population-sampler-released'
'@ | Out-Null
    }

    return [pscustomobject]@{
        sample_count = [int]$metadata.sample_count
        overflow = $false
        error = ""
        structural_phases = @($phases)
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
            & py.exe -3 $Context.SettlementClassifier find `
                --input $inputPath `
                --output $outputPath 2>&1
        )
        if ($LASTEXITCODE -ne 0) {
            $message = (
                ($classifierOutput | ForEach-Object { [string]$_ }) -join "`n"
            ).Trim()
            if ([string]::IsNullOrWhiteSpace($message)) {
                $message = "Settlement v2.5 classifier exited without diagnostics."
            }
            throw $message
        }
        if (-not (Test-Path -LiteralPath $outputPath -PathType Leaf)) {
            throw "BROKEN: Settlement v2.5 classifier produced no result."
        }
        return Get-Content -LiteralPath $outputPath -Raw | ConvertFrom-Json
    } finally {
        if (Test-Path -LiteralPath $temporaryDirectory -PathType Container) {
            Remove-Item -LiteralPath $temporaryDirectory -Recurse -Force
        }
    }
}

function Invoke-NativeMenuExtendedObservationClassifier {
    param(
        [Parameter(Mandatory = $true)][object]$Context,
        [Parameter(Mandatory = $true)][object[]]$Samples,
        [Parameter(Mandatory = $true)][long]$RequiredSpanMilliseconds
    )

    $temporaryDirectory = Join-Path ([IO.Path]::GetTempPath()) (
        "sdmod-menu-motion-v23-" + [Guid]::NewGuid().ToString("N")
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
            & py.exe -3 $Context.SettlementClassifier classify-extended `
                --input $inputPath `
                --output $outputPath `
                --required-span-milliseconds $RequiredSpanMilliseconds 2>&1
        )
        if ($LASTEXITCODE -ne 0) {
            $message = (
                ($classifierOutput | ForEach-Object { [string]$_ }) -join "`n"
            ).Trim()
            if ([string]::IsNullOrWhiteSpace($message)) {
                $message = (
                    "Settlement v2.3 extended classifier exited without diagnostics."
                )
            }
            throw $message
        }
        if (-not (Test-Path -LiteralPath $outputPath -PathType Leaf)) {
            throw "BROKEN: Settlement v2.3 extended classifier produced no result."
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

    $sampleCount = 0
    $busyCount = 0
    $notReadyCount = 0
    $lastUnavailable = ""
    $lastRejectedCandidate = ""
    $structuralPhaseOrder = [Collections.Generic.List[string]]::new()
    $structuralPhaseByHash = @{}
    $candidateSamples = [Collections.Generic.List[object]]::new()
    $candidateProbes = [Collections.Generic.List[object]]::new()

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

        $candidateSamples.Add([ordered]@{
            elapsed_milliseconds = $elapsed
            captured_at_milliseconds = $probe.CapturedAtMilliseconds
            semantic_surface = $probe.SemanticSurface
            semantic_generation = $probe.SemanticGeneration
            payload = $probe.SemanticPayload
        })
        $candidateProbes.Add($probe)
        $candidateSpan = if ($candidateSamples.Count -gt 1) {
            $elapsed - [long]$candidateSamples[0].elapsed_milliseconds
        } else {
            0L
        }
        if (
            $candidateSamples.Count -ge $script:NativeMenuSettleConsecutiveSamples -and
            $candidateSpan -ge $script:NativeMenuSettleMinimumSpanMilliseconds
        ) {
            try {
                $classification = Invoke-NativeMenuSettlementClassifier `
                    -Context $Context `
                    -Samples @($candidateSamples)
            } catch {
                $classificationError = [string]$_.Exception.Message
                if ($classificationError -match '^BROKEN:') {
                    throw
                }
                # A rejected candidate is not settlement. Keep measuring until
                # the bounded STOP so transient population, lifecycle churn,
                # and a genuinely invalid surface remain distinguishable.
                $lastRejectedCandidate = $classificationError
                Start-Sleep -Milliseconds (
                    $script:NativeMenuSettlePollMilliseconds
                )
                continue
            }
            $stableStartIndex = [int]$classification.stable_start_index
            $stableEndIndex = [int]$classification.stable_end_index
            if (
                $stableStartIndex -lt 0 -or
                $stableEndIndex -lt $stableStartIndex -or
                $stableEndIndex -ge $candidateSamples.Count
            ) {
                throw (
                    "BROKEN: Settlement v2.5 classifier returned an invalid " +
                    "selected-window index range."
                )
            }
            $stableWindow = [Collections.Generic.List[object]]::new()
            for (
                $stableIndex = $stableStartIndex;
                $stableIndex -le $stableEndIndex;
                $stableIndex += 1
            ) {
                $stableWindow.Add($candidateSamples[$stableIndex])
            }
            if (
                $stableWindow.Count -lt $script:NativeMenuSettleConsecutiveSamples -or
                ([long]$stableWindow[$stableWindow.Count - 1].elapsed_milliseconds -
                    [long]$stableWindow[0].elapsed_milliseconds) -lt
                    $script:NativeMenuSettleMinimumSpanMilliseconds
            ) {
                throw (
                    "BROKEN: Settlement v2.5 classifier selected a window " +
                    "below the recorder's 40-sample/two-second floor."
                )
            }
            $windowAnchorProbe = $candidateProbes[$stableStartIndex]
            $structuralPhases = [Collections.Generic.List[object]]::new()
            foreach ($phaseHash in $structuralPhaseOrder) {
                $structuralPhases.Add($structuralPhaseByHash[$phaseHash])
            }
            foreach ($phase in $structuralPhases) {
                Assert-NativeMenuOverlayHygiene `
                    -Context $Context `
                    -Layout $phase.payload
            }
            $summary = [ordered]@{
                settlement_spec = [string]$classification.settlement_spec
                criterion = [string]$classification.criterion
                structural_element_order = (
                    [string]$classification.structural_element_order
                )
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
                visibility_cycling_element_ids = @(
                    $classification.visibility_cycling_element_ids
                )
                ephemeral_art_ids = @($classification.ephemeral_art_ids)
                animated_element_count = (
                    [int]$classification.animated_element_count
                )
                minimum_element_count = (
                    [int]$classification.minimum_element_count
                )
                element_count = [int]$classification.element_count
                animated_fraction = [double]$classification.animated_fraction
                stable_start_index = $stableStartIndex
                stable_end_index = $stableEndIndex
            }
            return [pscustomobject]@{
                AnchorProbe = $windowAnchorProbe
                Summary = $summary
                Layout = $classification.layout
                AnimatedElementIds = @($classification.animated_element_ids)
                VisibilityCyclingElementIds = @(
                    $classification.visibility_cycling_element_ids
                )
                EphemeralArtIds = @($classification.ephemeral_art_ids)
                StructuralPhases = $structuralPhases
                SettledWindowSamples = @($stableWindow)
            }
        }
        Start-Sleep -Milliseconds $script:NativeMenuSettlePollMilliseconds
    }

    throw (
        "STOP: '$ScreenId' never satisfied Settlement v2.5 across at least " +
        "40 samples spanning two seconds within 60 seconds. " +
        "samples=$sampleCount busy=$busyCount not_ready=$notReadyCount " +
        "last_unavailable='$lastUnavailable' " +
        "last_rejected_candidate='$lastRejectedCandidate'"
    )
}

function Test-NativeMenuFrameMatchesSettlement {
    param(
        [Parameter(Mandatory = $true)][object]$FrameProbe,
        [Parameter(Mandatory = $true)][object]$Settlement
    )

    if (
        $FrameProbe.Status -ne "ready" -or
        $FrameProbe.SemanticSurface -cne
            $Settlement.AnchorProbe.SemanticSurface -or
        $FrameProbe.SemanticGeneration -ne
            $Settlement.AnchorProbe.SemanticGeneration -or
        [string]$FrameProbe.SemanticPayload.screen_id -cne
            [string]$Settlement.Layout.screen_id -or
        [uint64]$FrameProbe.SemanticPayload.generation -ne
            [uint64]$Settlement.Layout.generation
    ) {
        return $false
    }
    # Absolute draw ordinals, ambient membership, visibility phases, and
    # animated geometry may all change after the selected window.  The frame
    # is therefore paired to the measured semantic surface and generations;
    # the campaign resolver, not a single post-window frame, contracts the
    # reproduced structural core.
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
        Assert-NativeMenuOverlayHygiene `
            -Context $Context `
            -Layout $layout
        return [pscustomobject]@{
            semantic_surface = $settled.AnchorProbe.SemanticSurface
            semantic_generation = $settled.AnchorProbe.SemanticGeneration
            tagged_screen = [string]$layout.screen_id
            layout_generation = [uint64]$layout.generation
            element_count = @($layout.elements).Count
            animated_element_ids = @($settled.AnimatedElementIds)
            visibility_cycling_element_ids = @(
                $settled.VisibilityCyclingElementIds
            )
            ephemeral_art_ids = @($settled.EphemeralArtIds)
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
