[CmdletBinding()]
param(
    [Parameter(Mandatory = $false)]
    [string]$ScriptPath,

    [Parameter(Mandatory = $false)]
    [string[]]$ScriptArguments = @(),

    [Parameter(Mandatory = $false)]
    [string]$GhidraRoot = 'C:\Users\User\Documents\GitHub\ghidra_12.0.3_PUBLIC',

    [Parameter(Mandatory = $false)]
    [string]$ProjectRoot,

    [Parameter(Mandatory = $false)]
    [string]$ProjectName = 'SolomonDark',

    [Parameter(Mandatory = $false)]
    [string]$ProgramName = 'SolomonDark.exe',

    [Parameter(Mandatory = $false)]
    [string]$ReplicaRoot,

    [Parameter(Mandatory = $false)]
    [ValidateRange(1, 32)]
    [int]$ReplicaCount = 4,

    [Parameter(Mandatory = $false)]
    [ValidateRange(1, 600)]
    [int]$AcquireTimeoutSeconds = 60,

    [switch]$PreparePool,
    [switch]$RefreshReplica,
    [switch]$ClearReplicaLocks
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Resolve-WorkspacePath {
    param(
        [Parameter(Mandatory = $true)]
        [string]$BasePath,
        [Parameter(Mandatory = $true)]
        [string]$RelativePath
    )

    return [System.IO.Path]::GetFullPath((Join-Path $BasePath $RelativePath))
}

function Get-DefaultProjectRoot {
    $modLoaderRoot = Resolve-WorkspacePath -BasePath $PSScriptRoot -RelativePath '..'
    $workspaceRoot = Resolve-WorkspacePath -BasePath $modLoaderRoot -RelativePath '..'
    return Resolve-WorkspacePath -BasePath $workspaceRoot -RelativePath 'Decompiled Game\ghidra_project'
}

function Get-DefaultReplicaRoot {
    param([string]$SourceProjectRoot)
    return [System.IO.Path]::Combine([System.IO.Path]::GetDirectoryName($SourceProjectRoot), 'ghidra_project_replicas')
}

function Resolve-ScriptPath {
    param([string]$RequestedPath)

    if ([string]::IsNullOrWhiteSpace($RequestedPath)) {
        return $null
    }

    if ([System.IO.Path]::IsPathRooted($RequestedPath)) {
        return [System.IO.Path]::GetFullPath($RequestedPath)
    }

    $candidatePaths = @(
        [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot $RequestedPath)),
        [System.IO.Path]::GetFullPath((Join-Path (Join-Path $PSScriptRoot '..') $RequestedPath)),
        [System.IO.Path]::GetFullPath((Join-Path (Join-Path $PSScriptRoot '..\tools\ghidra-scripts') $RequestedPath))
    )

    foreach ($candidatePath in $candidatePaths) {
        if (Test-Path -LiteralPath $candidatePath) {
            return $candidatePath
        }
    }

    throw "Unable to resolve Ghidra script path: $RequestedPath"
}

function Get-SourceSignature {
    param(
        [Parameter(Mandatory = $true)]
        [string]$SourceProjectRoot,
        [Parameter(Mandatory = $true)]
        [string]$ProjectName
    )

    $gprPath = Join-Path $SourceProjectRoot "$ProjectName.gpr"
    $projectPropertiesPath = Join-Path $SourceProjectRoot "$ProjectName.rep\project.prp"
    if (-not (Test-Path -LiteralPath $gprPath)) {
        throw "Ghidra project file is missing: $gprPath"
    }
    if (-not (Test-Path -LiteralPath $projectPropertiesPath)) {
        throw "Ghidra project properties are missing: $projectPropertiesPath"
    }

    $gprStamp = (Get-Item -LiteralPath $gprPath).LastWriteTimeUtc.Ticks
    $prpStamp = (Get-Item -LiteralPath $projectPropertiesPath).LastWriteTimeUtc.Ticks
    return "$ProjectName|$gprStamp|$prpStamp"
}

function Get-ReplicaSlotName {
    param([int]$Index)
    return ('slot-{0:d2}' -f $Index)
}

function Get-ReplicaProjectRoot {
    param(
        [string]$ReplicaPoolRoot,
        [int]$Index
    )

    return Join-Path $ReplicaPoolRoot (Get-ReplicaSlotName -Index $Index)
}

function Get-ReplicaMarkerPath {
    param([string]$ReplicaProjectRoot)
    return Join-Path $ReplicaProjectRoot '.sdmod-ghidra-source.txt'
}

function Get-ReplicaLockPath {
    param([string]$ReplicaProjectRoot)
    return Join-Path $ReplicaProjectRoot '.sdmod-ghidra.lock'
}

function Copy-ProjectReplica {
    param(
        [Parameter(Mandatory = $true)]
        [string]$SourceProjectRoot,
        [Parameter(Mandatory = $true)]
        [string]$ReplicaProjectRoot
    )

    if (Test-Path -LiteralPath $ReplicaProjectRoot) {
        Remove-Item -LiteralPath $ReplicaProjectRoot -Recurse -Force
    }

    New-Item -ItemType Directory -Path $ReplicaProjectRoot | Out-Null

    $source = $SourceProjectRoot.TrimEnd('\')
    $destination = $ReplicaProjectRoot.TrimEnd('\')
    $robocopyArgs = @(
        $source,
        $destination,
        '/MIR',
        '/R:2',
        '/W:1',
        '/NFL',
        '/NDL',
        '/NJH',
        '/NJS',
        '/NP',
        '/XF',
        '*.lock',
        '*.lock~'
    )

    & robocopy @robocopyArgs | Out-Null
    $exitCode = $LASTEXITCODE
    if ($exitCode -ge 8) {
        throw "Robocopy failed while preparing replica '$ReplicaProjectRoot' (exit code $exitCode)."
    }
}

function Ensure-ReplicaProject {
    param(
        [Parameter(Mandatory = $true)]
        [string]$SourceProjectRoot,
        [Parameter(Mandatory = $true)]
        [string]$ReplicaProjectRoot,
        [Parameter(Mandatory = $true)]
        [string]$SourceSignature,
        [switch]$Refresh
    )

    $markerPath = Get-ReplicaMarkerPath -ReplicaProjectRoot $ReplicaProjectRoot
    $needsRefresh = $Refresh.IsPresent -or
        -not (Test-Path -LiteralPath $ReplicaProjectRoot) -or
        -not (Test-Path -LiteralPath $markerPath)

    if (-not $needsRefresh) {
        $currentSignature = Get-Content -LiteralPath $markerPath -Raw
        if ($currentSignature.Trim() -ne $SourceSignature) {
            $needsRefresh = $true
        }
    }

    if (-not $needsRefresh) {
        return
    }

    Copy-ProjectReplica -SourceProjectRoot $SourceProjectRoot -ReplicaProjectRoot $ReplicaProjectRoot
    Set-Content -LiteralPath $markerPath -Value $SourceSignature -NoNewline
}

function Clear-ReplicaLockFiles {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ReplicaPoolRoot
    )

    if (-not (Test-Path -LiteralPath $ReplicaPoolRoot)) {
        return
    }

    Get-ChildItem -LiteralPath $ReplicaPoolRoot -Filter '.sdmod-ghidra.lock' -Recurse -File -ErrorAction SilentlyContinue |
        Remove-Item -Force -ErrorAction SilentlyContinue
}

function Try-AcquireReplica {
    param(
        [Parameter(Mandatory = $true)]
        [string]$ReplicaProjectRoot
    )

    $lockPath = Get-ReplicaLockPath -ReplicaProjectRoot $ReplicaProjectRoot
    try {
        $stream = [System.IO.File]::Open($lockPath, [System.IO.FileMode]::CreateNew, [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None)
        $writer = New-Object System.IO.StreamWriter($stream, [System.Text.Encoding]::UTF8, 1024, $true)
        $writer.WriteLine("pid=$PID")
        $writer.WriteLine("started_utc={0:o}" -f [DateTime]::UtcNow)
        $writer.Flush()
        return $stream
    }
    catch [System.IO.IOException] {
        return $null
    }
}

function Acquire-ReplicaSlot {
    param(
        [Parameter(Mandatory = $true)]
        [string]$SourceProjectRoot,
        [Parameter(Mandatory = $true)]
        [string]$ReplicaPoolRoot,
        [Parameter(Mandatory = $true)]
        [string]$ProjectName,
        [Parameter(Mandatory = $true)]
        [int]$ReplicaCount,
        [Parameter(Mandatory = $true)]
        [int]$AcquireTimeoutSeconds,
        [switch]$Refresh
    )

    $sourceSignature = Get-SourceSignature -SourceProjectRoot $SourceProjectRoot -ProjectName $ProjectName
    $deadline = [DateTime]::UtcNow.AddSeconds($AcquireTimeoutSeconds)

    while ([DateTime]::UtcNow -lt $deadline) {
        for ($slotIndex = 1; $slotIndex -le $ReplicaCount; $slotIndex++) {
            $replicaProjectRoot = Get-ReplicaProjectRoot -ReplicaPoolRoot $ReplicaPoolRoot -Index $slotIndex
            $lockStream = Try-AcquireReplica -ReplicaProjectRoot $replicaProjectRoot
            if ($null -eq $lockStream) {
                continue
            }

            try {
                Ensure-ReplicaProject `
                    -SourceProjectRoot $SourceProjectRoot `
                    -ReplicaProjectRoot $replicaProjectRoot `
                    -SourceSignature $sourceSignature `
                    -Refresh:$Refresh.IsPresent

                return [pscustomobject]@{
                    Index = $slotIndex
                    ProjectRoot = $replicaProjectRoot
                    LockStream = $lockStream
                }
            }
            catch {
                $lockStream.Dispose()
                Remove-Item -LiteralPath (Get-ReplicaLockPath -ReplicaProjectRoot $replicaProjectRoot) -Force -ErrorAction SilentlyContinue
                throw
            }
        }

        Start-Sleep -Milliseconds 250
    }

    throw "Timed out waiting for a free Ghidra replica slot after $AcquireTimeoutSeconds second(s)."
}

function Release-ReplicaSlot {
    param(
        [Parameter(Mandatory = $true)]
        $ReplicaSlot
    )

    $lockPath = Get-ReplicaLockPath -ReplicaProjectRoot $ReplicaSlot.ProjectRoot
    try {
        if ($null -ne $ReplicaSlot.LockStream) {
            $ReplicaSlot.LockStream.Dispose()
        }
    }
    finally {
        Remove-Item -LiteralPath $lockPath -Force -ErrorAction SilentlyContinue
    }
}

if ([string]::IsNullOrWhiteSpace($ProjectRoot)) {
    $ProjectRoot = Get-DefaultProjectRoot
}
else {
    $ProjectRoot = [System.IO.Path]::GetFullPath($ProjectRoot)
}

if ([string]::IsNullOrWhiteSpace($ReplicaRoot)) {
    $ReplicaRoot = Get-DefaultReplicaRoot -SourceProjectRoot $ProjectRoot
}
else {
    $ReplicaRoot = [System.IO.Path]::GetFullPath($ReplicaRoot)
}

$analyzeHeadlessPath = Join-Path $GhidraRoot 'support\analyzeHeadless.bat'
if (-not (Test-Path -LiteralPath $analyzeHeadlessPath)) {
    throw "analyzeHeadless.bat was not found: $analyzeHeadlessPath"
}

if (-not (Test-Path -LiteralPath $ProjectRoot)) {
    throw "Ghidra project root was not found: $ProjectRoot"
}

New-Item -ItemType Directory -Path $ReplicaRoot -Force | Out-Null

if ($ClearReplicaLocks) {
    Clear-ReplicaLockFiles -ReplicaPoolRoot $ReplicaRoot
}

if ($PreparePool) {
    $sourceSignature = Get-SourceSignature -SourceProjectRoot $ProjectRoot -ProjectName $ProjectName
    for ($slotIndex = 1; $slotIndex -le $ReplicaCount; $slotIndex++) {
        $replicaProjectRoot = Get-ReplicaProjectRoot -ReplicaPoolRoot $ReplicaRoot -Index $slotIndex
        Ensure-ReplicaProject `
            -SourceProjectRoot $ProjectRoot `
            -ReplicaProjectRoot $replicaProjectRoot `
            -SourceSignature $sourceSignature `
            -Refresh:$RefreshReplica.IsPresent
        Write-Host ("Prepared Ghidra replica {0}: {1}" -f $slotIndex, $replicaProjectRoot)
    }

    if ([string]::IsNullOrWhiteSpace($ScriptPath)) {
        return
    }
}

$resolvedScriptPath = Resolve-ScriptPath -RequestedPath $ScriptPath
if ($null -eq $resolvedScriptPath) {
    throw "ScriptPath is required unless -PreparePool is specified by itself."
}

$scriptDirectory = [System.IO.Path]::GetDirectoryName($resolvedScriptPath)
$replicaSlot = Acquire-ReplicaSlot `
    -SourceProjectRoot $ProjectRoot `
    -ReplicaPoolRoot $ReplicaRoot `
    -ProjectName $ProjectName `
    -ReplicaCount $ReplicaCount `
    -AcquireTimeoutSeconds $AcquireTimeoutSeconds `
    -Refresh:$RefreshReplica.IsPresent

try {
    Write-Host ("Using Ghidra replica {0}: {1}" -f $replicaSlot.Index, $replicaSlot.ProjectRoot)

    $headlessArgs = @(
        $replicaSlot.ProjectRoot,
        $ProjectName,
        '-process',
        $ProgramName,
        '-readOnly',
        '-noanalysis',
        '-scriptPath',
        $scriptDirectory,
        '-postScript',
        $resolvedScriptPath
    ) + $ScriptArguments

    & $analyzeHeadlessPath @headlessArgs
    $exitCode = $LASTEXITCODE
    if ($exitCode -ne 0) {
        throw "Headless Ghidra exited with code $exitCode."
    }
}
finally {
    Release-ReplicaSlot -ReplicaSlot $replicaSlot
}
