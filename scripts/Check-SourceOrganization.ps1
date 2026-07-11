param(
    [int]$MaxCppLines = 700,
    [int]$MaxHeaderLines = 500,
    [int]$MaxInlLines = 700
)

$ErrorActionPreference = "Stop"

$root = Split-Path -Parent $PSScriptRoot
$loaderRoot = Join-Path $root "SolomonDarkModLoader"
$projectPath = Join-Path $loaderRoot "SolomonDarkModLoader.vcxproj"
$filtersPath = Join-Path $loaderRoot "SolomonDarkModLoader.vcxproj.filters"

function Convert-ToProjectRelativePath {
    param([Parameter(Mandatory = $true)][string]$Path)

    return $Path.Replace("\", "/")
}

function Get-MSBuildItems {
    param(
        [Parameter(Mandatory = $true)][xml]$Project,
        [Parameter(Mandatory = $true)][string]$ElementName
    )

    $namespaceManager = New-Object System.Xml.XmlNamespaceManager($Project.NameTable)
    $namespaceManager.AddNamespace("msb", "http://schemas.microsoft.com/developer/msbuild/2003")

    $items = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
    foreach ($node in $Project.SelectNodes("//msb:$ElementName", $namespaceManager)) {
        $include = $node.Include
        if ([string]::IsNullOrWhiteSpace($include) -or $include.Contains("*")) {
            continue
        }

        $relativePath = Convert-ToProjectRelativePath $include
        if ($relativePath.StartsWith("src/") -or $relativePath.StartsWith("include/")) {
            [void]$items.Add($relativePath)
        }
    }

    return $items
}

function Get-TrackedSourceFiles {
    $extensions = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
    foreach ($extension in @(".c", ".cpp", ".h", ".hpp", ".inl")) {
        [void]$extensions.Add($extension)
    }

    $files = @()
    foreach ($directory in @("src", "include")) {
        $absoluteDirectory = Join-Path $loaderRoot $directory
        if (-not (Test-Path $absoluteDirectory)) {
            continue
        }

        $files += Get-ChildItem $absoluteDirectory -Recurse -File |
            Where-Object { $extensions.Contains($_.Extension) } |
            ForEach-Object {
                $relativePath = $_.FullName.Substring($loaderRoot.Length).TrimStart("\", "/")
                Convert-ToProjectRelativePath $relativePath
            }
    }

    return @($files | Sort-Object -Unique)
}

function Get-LineCount {
    param([Parameter(Mandatory = $true)][string]$Path)

    $count = 0
    foreach ($null in [System.IO.File]::ReadLines($Path)) {
        $count += 1
    }
    return $count
}

if (-not (Test-Path $projectPath)) {
    throw "Missing project file: $projectPath"
}

if (-not (Test-Path $filtersPath)) {
    throw "Missing filters file: $filtersPath"
}

[xml]$project = Get-Content $projectPath
[xml]$filters = Get-Content $filtersPath

$compileItems = Get-MSBuildItems -Project $project -ElementName "ClCompile"
$includeItems = Get-MSBuildItems -Project $project -ElementName "ClInclude"
$projectItems = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
foreach ($item in $compileItems) { [void]$projectItems.Add($item) }
foreach ($item in $includeItems) { [void]$projectItems.Add($item) }

$filterCompileItems = Get-MSBuildItems -Project $filters -ElementName "ClCompile"
$filterIncludeItems = Get-MSBuildItems -Project $filters -ElementName "ClInclude"
$filterItems = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
foreach ($item in $filterCompileItems) { [void]$filterItems.Add($item) }
foreach ($item in $filterIncludeItems) { [void]$filterItems.Add($item) }

$sourceFiles = Get-TrackedSourceFiles
$errors = [System.Collections.Generic.List[string]]::new()

foreach ($sourceFile in $sourceFiles) {
    if (-not $projectItems.Contains($sourceFile)) {
        $errors.Add("Source file is missing from SolomonDarkModLoader.vcxproj: $sourceFile")
    }
}

foreach ($projectItem in $projectItems) {
    $absolutePath = Join-Path $loaderRoot $projectItem
    if (-not (Test-Path $absolutePath)) {
        $errors.Add("Project item points at a missing source file: $projectItem")
    }

    if (-not $filterItems.Contains($projectItem)) {
        $errors.Add("Project item is missing from SolomonDarkModLoader.vcxproj.filters: $projectItem")
    }
}

$acceptedLargeFiles = @{
    "include/multiplayer_runtime_protocol.h" = "Fixed local-UDP packet schema; split with the transport protocol redesign."
    "src/lua_engine_bindings_gameplay.cpp" = "Single Lua gameplay registration unit; split after the multiplayer API stabilizes."
    "src/mod_loader_gameplay/bot_casting/pending_cast_preparation.inl" = "Existing native cast preparation sequence with tightly coupled state guards."
    "src/mod_loader_gameplay/bot_casting/pending_cast_processing.inl" = "Existing native cast lifecycle sequence with tightly coupled cleanup paths."
    "src/mod_loader_gameplay/gameplay_hooks/actor_tick/player_actor_tick_hook.inl" = "Native actor-tick hook kept contiguous while multiplayer playback is validated."
    "src/mod_loader_gameplay/gameplay_hooks/player_control_hooks.inl" = "Native input/control detours kept together while multiplayer authority settles."
    "src/mod_loader_gameplay/public_api_keyboard_injection.inl" = "Existing input-injection API and native key routing."
    "src/mod_loader_gameplay/public_api_state_getters.inl" = "Existing gameplay snapshot API with shared native decoding helpers."
    "src/mod_loader_gameplay/replicated_loot_reconciliation.inl" = "Host-owned loot materialization lifecycle kept together through live verification."
    "src/mod_loader_gameplay/world_snapshot_reconciliation.inl" = "Host-authoritative world reconciliation pipeline pending a behavior-neutral module split."
    "src/multiplayer_local_transport.cpp" = "Local-UDP protocol prototype pending extraction behind the final transport interface."
    "src/run_lifecycle/run_and_enemy_hooks.inl" = "Run lifecycle and enemy authority hooks kept contiguous through multiplayer stress validation."
}

$largeAccepted = [System.Collections.Generic.List[string]]::new()
foreach ($sourceFile in $sourceFiles) {
    $absolutePath = Join-Path $loaderRoot $sourceFile
    $extension = [System.IO.Path]::GetExtension($sourceFile)
    $limit = switch ($extension.ToLowerInvariant()) {
        ".cpp" { $MaxCppLines }
        ".c" { $MaxCppLines }
        ".h" { $MaxHeaderLines }
        ".hpp" { $MaxHeaderLines }
        ".inl" { $MaxInlLines }
        default { 0 }
    }

    if ($limit -le 0) {
        continue
    }

    $lineCount = Get-LineCount -Path $absolutePath
    if ($lineCount -le $limit) {
        continue
    }

    if ($acceptedLargeFiles.ContainsKey($sourceFile)) {
        $largeAccepted.Add(("{0} ({1} lines): {2}" -f $sourceFile, $lineCount, $acceptedLargeFiles[$sourceFile]))
    } else {
        $errors.Add("$sourceFile has $lineCount lines, above threshold $limit.")
    }
}

if ($errors.Count -gt 0) {
    Write-Host "Source organization check failed:"
    foreach ($errorItem in $errors) {
        Write-Host "  - $errorItem"
    }
    exit 1
}

Write-Host "Source organization check passed."
Write-Host "Checked $($sourceFiles.Count) source/header fragments."

if ($largeAccepted.Count -gt 0) {
    Write-Host "Accepted large-file exceptions:"
    foreach ($largeFile in $largeAccepted) {
        Write-Host "  - $largeFile"
    }
}
