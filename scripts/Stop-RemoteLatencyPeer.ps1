param(
    [Parameter(Mandatory = $true)]
    [string]$ProcessLedgerPath
)

Set-StrictMode -Version 3.0
$ErrorActionPreference = "Stop"

$ledgerPath = (
    Get-Item -LiteralPath $ProcessLedgerPath -ErrorAction Stop
).FullName
$ledger = Get-Content -LiteralPath $ledgerPath -Raw |
    ConvertFrom-Json
$processId = [int]$ledger.processId
$expectedPath = [System.IO.Path]::GetFullPath(
    [string]$ledger.executablePath
)
$process = Get-CimInstance Win32_Process `
    -Filter "ProcessId = $processId" `
    -ErrorAction SilentlyContinue

if ($null -eq $process) {
    [pscustomobject]@{
        processId = $processId
        expectedPath = $expectedPath
        stopped = $false
        alreadyExited = $true
    } | ConvertTo-Json -Compress
    exit 0
}
if (
    $null -eq $process.ExecutablePath -or
    -not [string]::Equals(
        [System.IO.Path]::GetFullPath($process.ExecutablePath),
        $expectedPath,
        [System.StringComparison]::OrdinalIgnoreCase)
) {
    throw "PID $processId no longer owns the exact staged executable; nothing was stopped."
}

Stop-Process -Id $processId
$deadline = (Get-Date).AddSeconds(10)
while (
    (Get-Date) -lt $deadline -and
    $null -ne (
        Get-Process -Id $processId -ErrorAction SilentlyContinue
    )
) {
    Start-Sleep -Milliseconds 100
}
if (
    $null -ne (
        Get-Process -Id $processId -ErrorAction SilentlyContinue
    )
) {
    $current = Get-CimInstance Win32_Process `
        -Filter "ProcessId = $processId" `
        -ErrorAction SilentlyContinue
    if (
        $null -eq $current -or
        $null -eq $current.ExecutablePath -or
        -not [string]::Equals(
            [System.IO.Path]::GetFullPath($current.ExecutablePath),
            $expectedPath,
            [System.StringComparison]::OrdinalIgnoreCase)
    ) {
        throw "PID $processId changed identity while stopping; force-stop was not attempted."
    }
    Stop-Process -Id $processId -Force
}

[pscustomobject]@{
    processId = $processId
    expectedPath = $expectedPath
    stopped = $true
    alreadyExited = $false
} | ConvertTo-Json -Compress
