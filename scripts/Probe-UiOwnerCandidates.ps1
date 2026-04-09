[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [int]$ProcessId,

    [Parameter(Mandatory = $true)]
    [string]$BaseAddress,

    [string]$StartOffset = "-0x100",
    [string]$EndOffset = "0x200",
    [int]$Step = 4,
    [string]$OwnerRequiredPointerOffset = "0x0",
    [string]$OwnerStatePointerOffset = "0x0",
    [string]$ControlOffset = "0x0",
    [string]$ControlValidationPointerOffset = "0x0",
    [switch]$OnlyPassing
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Convert-ToInt64 {
    param([Parameter(Mandatory = $true)][string]$Value)

    $trimmed = $Value.Trim()
    if ($trimmed.StartsWith("-0x", [System.StringComparison]::OrdinalIgnoreCase)) {
        return -[Convert]::ToInt64($trimmed.Substring(3), 16)
    }
    if ($trimmed.StartsWith("0x", [System.StringComparison]::OrdinalIgnoreCase)) {
        return [Convert]::ToInt64($trimmed.Substring(2), 16)
    }
    return [Convert]::ToInt64($trimmed, 10)
}

Add-Type @"
using System;
using System.Runtime.InteropServices;

public static class UiOwnerProbeNative {
    [DllImport("kernel32.dll", SetLastError = true)]
    public static extern IntPtr OpenProcess(uint desiredAccess, bool inheritHandle, int processId);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool ReadProcessMemory(
        IntPtr processHandle,
        IntPtr baseAddress,
        byte[] buffer,
        int size,
        out IntPtr bytesRead);

    [DllImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static extern bool CloseHandle(IntPtr handle);
}
"@

$PROCESS_VM_READ = 0x0010
$PROCESS_QUERY_INFORMATION = 0x0400

function Format-Hex32 {
    param([Parameter(Mandatory = $true)][UInt64]$Value)
    return ("0x{0:X8}" -f ($Value -band 0xFFFFFFFF))
}

function Try-ReadBytes {
    param(
        [Parameter(Mandatory = $true)][IntPtr]$Handle,
        [Parameter(Mandatory = $true)][UInt64]$Address,
        [Parameter(Mandatory = $true)][int]$Length
    )

    $buffer = New-Object byte[] $Length
    $bytesRead = [IntPtr]::Zero
    $ok = [UiOwnerProbeNative]::ReadProcessMemory(
        $Handle,
        [IntPtr]([Int64]$Address),
        $buffer,
        $Length,
        [ref]$bytesRead)

    if (-not $ok -or $bytesRead.ToInt64() -ne $Length) {
        return $null
    }

    return $buffer
}

function Try-ReadUInt32 {
    param(
        [Parameter(Mandatory = $true)][IntPtr]$Handle,
        [Parameter(Mandatory = $true)][UInt64]$Address
    )

    $buffer = Try-ReadBytes -Handle $Handle -Address $Address -Length 4
    if ($null -eq $buffer) {
        return $null
    }

    return [BitConverter]::ToUInt32($buffer, 0)
}

function Test-ReadableByte {
    param(
        [Parameter(Mandatory = $true)][IntPtr]$Handle,
        [Parameter(Mandatory = $true)][UInt64]$Address
    )

    $buffer = Try-ReadBytes -Handle $Handle -Address $Address -Length 1
    return $null -ne $buffer
}

$baseAddressValue = [UInt64](Convert-ToInt64 -Value $BaseAddress)
$startOffsetValue = Convert-ToInt64 -Value $StartOffset
$endOffsetValue = Convert-ToInt64 -Value $EndOffset
$ownerRequiredPointerOffsetValue = [UInt64](Convert-ToInt64 -Value $OwnerRequiredPointerOffset)
$ownerStatePointerOffsetValue = [UInt64](Convert-ToInt64 -Value $OwnerStatePointerOffset)
$controlOffsetValue = [UInt64](Convert-ToInt64 -Value $ControlOffset)
$controlValidationPointerOffsetValue = [UInt64](Convert-ToInt64 -Value $ControlValidationPointerOffset)

$processHandle = [UiOwnerProbeNative]::OpenProcess(
    $PROCESS_VM_READ -bor $PROCESS_QUERY_INFORMATION,
    $false,
    $ProcessId)

if ($processHandle -eq [IntPtr]::Zero) {
    throw "OpenProcess failed for PID $ProcessId."
}

try {
    for ($offset = $startOffsetValue; $offset -le $endOffsetValue; $offset += $Step) {
        $candidateAddress = [UInt64]([Int64]$baseAddressValue + $offset)
        $vtable = Try-ReadUInt32 -Handle $processHandle -Address $candidateAddress
        $ownerRequired = $null
        $ownerState = $null
        $validationPointer = $null
        $validationReadable = $false

        if ($ownerRequiredPointerOffsetValue -ne 0) {
            $ownerRequired = Try-ReadUInt32 -Handle $processHandle -Address ($candidateAddress + $ownerRequiredPointerOffsetValue)
        }

        if ($ownerStatePointerOffsetValue -ne 0) {
            $ownerState = Try-ReadUInt32 -Handle $processHandle -Address ($candidateAddress + $ownerStatePointerOffsetValue)
        }

        if ($controlOffsetValue -ne 0 -and $controlValidationPointerOffsetValue -ne 0) {
            $validationAddress = $candidateAddress + $controlOffsetValue + $controlValidationPointerOffsetValue
            $validationPointer = Try-ReadUInt32 -Handle $processHandle -Address $validationAddress
            if ($null -eq $validationPointer) {
                $validationReadable = $false
            } elseif ($validationPointer -eq 0) {
                $validationReadable = $true
            } else {
                $validationReadable = Test-ReadableByte -Handle $processHandle -Address ([UInt64]$validationPointer)
            }
        }

        $passesOwnerRequired =
            ($ownerRequiredPointerOffsetValue -eq 0) -or
            ($null -ne $ownerRequired -and $ownerRequired -ne 0)
        $passesValidation =
            ($controlOffsetValue -eq 0 -or $controlValidationPointerOffsetValue -eq 0) -or
            (($null -ne $validationPointer) -and $validationReadable)

        if ($OnlyPassing -and -not ($passesOwnerRequired -and $passesValidation)) {
            continue
        }

        $parts = @(
            "offset=$offset",
            "candidate=$(Format-Hex32 -Value $candidateAddress)",
            "vtable=$(if ($null -ne $vtable) { Format-Hex32 -Value $vtable } else { 'unreadable' })",
            "owner_required=$(if ($null -ne $ownerRequired) { Format-Hex32 -Value $ownerRequired } else { 'unreadable' })",
            "owner_state=$(if ($null -ne $ownerState) { Format-Hex32 -Value $ownerState } else { 'unreadable' })",
            "validation_pointer=$(if ($null -ne $validationPointer) { Format-Hex32 -Value $validationPointer } else { 'unreadable' })",
            "validation_readable=$validationReadable",
            "passes_owner_required=$passesOwnerRequired",
            "passes_validation=$passesValidation"
        )

        Write-Output ($parts -join " ")
    }
}
finally {
    if ($processHandle -ne [IntPtr]::Zero) {
        [void][UiOwnerProbeNative]::CloseHandle($processHandle)
    }
}
