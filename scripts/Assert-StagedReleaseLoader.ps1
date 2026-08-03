param(
    [string]$LoaderPath = ""
)

function Get-StagedLoaderBuildFlavor {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    $loader = Get-Item -LiteralPath $Path -ErrorAction Stop
    if ($loader.PSIsContainer) {
        throw "Staged loader path is not a file: $($loader.FullName)"
    }

    $bytes = [System.IO.File]::ReadAllBytes($loader.FullName)
    if ($bytes.Length -lt 2 -or $bytes[0] -ne 0x4D -or $bytes[1] -ne 0x5A) {
        throw "Staged loader is not a PE DLL: $($loader.FullName)"
    }

    $binaryText = [System.Text.Encoding]::ASCII.GetString($bytes)
    $stampMatches = [System.Text.RegularExpressions.Regex]::Matches(
        $binaryText,
        "SDMOD_BUILD_FLAVOR=([A-Za-z]+)\x00"
    )
    $flavors = @(
        $stampMatches |
            ForEach-Object { $_.Groups[1].Value } |
            Sort-Object -Unique
    )
    if ($flavors.Count -ne 1 -or $flavors[0] -notin @("Debug", "Release")) {
        throw (
            "Staged loader has no single recognized build-flavor stamp: " +
            $loader.FullName
        )
    }

    return $flavors[0]
}

function Assert-StagedReleaseLoader {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Path
    )

    $loader = Get-Item -LiteralPath $Path -ErrorAction Stop
    $flavor = Get-StagedLoaderBuildFlavor -Path $loader.FullName
    if ($flavor -ne "Release") {
        throw (
            "Live acceptance requires a Release SolomonDarkModLoader.dll, " +
            "but '$($loader.FullName)' is stamped '$flavor'. Rebuild and " +
            "stage Release with .\scripts\Build-All.ps1 -Configuration Release."
        )
    }

    return $flavor
}

if ($MyInvocation.InvocationName -ne ".") {
    if ([string]::IsNullOrWhiteSpace($LoaderPath)) {
        throw "LoaderPath is required when this assertion is invoked directly."
    }
    Assert-StagedReleaseLoader -Path $LoaderPath
}
