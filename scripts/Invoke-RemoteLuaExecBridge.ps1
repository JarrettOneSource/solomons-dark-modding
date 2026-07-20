[CmdletBinding()]
param(
    [Parameter(Mandatory = $false)]
    [ValidateRange(0, 65535)]
    [int]$ListenPort = 0,

    [Parameter(Mandatory = $false)]
    [string]$PipeName = 'SolomonDarkModLoader_LuaExec',

    [Parameter(Mandatory = $false)]
    [ValidateRange(100, 300000)]
    [int]$MaximumResponseTimeoutMilliseconds = 300000
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

if ($PipeName.StartsWith('\\.\pipe\', [System.StringComparison]::OrdinalIgnoreCase)) {
    $PipeName = $PipeName.Substring('\\.\pipe\'.Length)
}

$maximumFrameBytes = 16 * 1024 * 1024
$utf8 = [System.Text.UTF8Encoding]::new($false)

function Read-ExactBytes {
    param(
        [Parameter(Mandatory = $true)]
        [System.IO.Stream]$Stream,

        [Parameter(Mandatory = $true)]
        [int]$Length
    )

    $buffer = New-Object byte[] $Length
    $offset = 0
    while ($offset -lt $Length) {
        $read = $Stream.Read($buffer, $offset, $Length - $offset)
        if ($read -le 0) {
            throw [System.IO.EndOfStreamException]::new('Request stream closed early.')
        }
        $offset += $read
    }
    return $buffer
}

function Invoke-GameLua {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Code,

        [Parameter(Mandatory = $true)]
        [int]$ResponseTimeoutMilliseconds
    )

    $pipe = $null
    $memory = $null
    try {
        $pipe = [System.IO.Pipes.NamedPipeClientStream]::new(
            '.',
            $PipeName,
            [System.IO.Pipes.PipeDirection]::InOut,
            [System.IO.Pipes.PipeOptions]::Asynchronous
        )
        $pipe.Connect(5000)
        $pipe.ReadMode = [System.IO.Pipes.PipeTransmissionMode]::Message

        $request = $utf8.GetBytes($Code)
        $pipe.Write($request, 0, $request.Length)
        $pipe.Flush()

        $memory = [System.IO.MemoryStream]::new()
        $buffer = New-Object byte[] 4096
        $clock = [System.Diagnostics.Stopwatch]::StartNew()
        while ($true) {
            $remaining = $ResponseTimeoutMilliseconds - [int]$clock.ElapsedMilliseconds
            if ($remaining -le 0) {
                throw [System.TimeoutException]::new(
                    "Timed out waiting for pipe '$PipeName'.")
            }

            $readTask = $pipe.ReadAsync($buffer, 0, $buffer.Length)
            if (-not $readTask.Wait($remaining)) {
                throw [System.TimeoutException]::new(
                    "Timed out waiting for pipe '$PipeName'.")
            }
            $read = [int]$readTask.Result
            if ($read -le 0) {
                break
            }
            $memory.Write($buffer, 0, $read)
            if ($pipe.IsMessageComplete) {
                break
            }
        }
        return $utf8.GetString($memory.ToArray())
    } finally {
        if ($memory -ne $null) {
            $memory.Dispose()
        }
        if ($pipe -ne $null) {
            $pipe.Dispose()
        }
    }
}

$listener = [System.Net.Sockets.TcpListener]::new(
    [System.Net.IPAddress]::Loopback,
    $ListenPort
)
$listener.Start(1)
$boundPort = ([System.Net.IPEndPoint]$listener.LocalEndpoint).Port
[Console]::Out.WriteLine("SDMOD_BRIDGE_PORT=$boundPort")
[Console]::Out.Flush()
$shutdownRequested = $false
try {
    while (-not $shutdownRequested) {
        $client = $listener.AcceptTcpClient()
        try {
            $client.NoDelay = $true
            $stream = $client.GetStream()
            $stream.ReadTimeout = 15000
            $stream.WriteTimeout = 15000

            while (-not $shutdownRequested) {
                $header = Read-ExactBytes -Stream $stream -Length 8
                $requestLength = [System.BitConverter]::ToUInt32($header, 0)
                $requestTimeoutMilliseconds = [System.BitConverter]::ToUInt32(
                    $header,
                    4)
                if ($requestLength -eq [uint32]::MaxValue) {
                    $emptyResponse = [System.BitConverter]::GetBytes([uint32]0)
                    $stream.Write($emptyResponse, 0, $emptyResponse.Length)
                    $stream.Flush()
                    continue
                }
                if ($requestLength -eq 0) {
                    $shutdownRequested = $true
                    $emptyResponse = [System.BitConverter]::GetBytes([uint32]0)
                    $stream.Write($emptyResponse, 0, $emptyResponse.Length)
                    $stream.Flush()
                    continue
                }
                if ($requestLength -gt $maximumFrameBytes) {
                    throw "Invalid Lua request length: $requestLength"
                }
                if ($requestTimeoutMilliseconds -lt 100 -or
                    $requestTimeoutMilliseconds -gt $MaximumResponseTimeoutMilliseconds) {
                    throw "Invalid Lua request timeout: $requestTimeoutMilliseconds"
                }
                $stream.ReadTimeout = [int]$requestTimeoutMilliseconds + 5000
                $stream.WriteTimeout = [int]$requestTimeoutMilliseconds + 5000
                $requestBytes = Read-ExactBytes `
                    -Stream $stream `
                    -Length ([int]$requestLength)
                $code = $utf8.GetString($requestBytes)

                try {
                    $response = Invoke-GameLua `
                        -Code $code `
                        -ResponseTimeoutMilliseconds ([int]$requestTimeoutMilliseconds)
                } catch {
                    $message = $_.Exception.Message
                    if ([string]::IsNullOrWhiteSpace($message)) {
                        $message = 'Lua execution failed.'
                    }
                    if (-not $message.StartsWith('ERROR:', [System.StringComparison]::OrdinalIgnoreCase)) {
                        $message = "ERROR: $message"
                    }
                    $response = $message
                }

                $responseBytes = $utf8.GetBytes($response)
                if ($responseBytes.Length -gt $maximumFrameBytes) {
                    throw "Lua response exceeds $maximumFrameBytes bytes."
                }
                $responseHeader = [System.BitConverter]::GetBytes(
                    [uint32]$responseBytes.Length)
                $stream.Write($responseHeader, 0, $responseHeader.Length)
                if ($responseBytes.Length -gt 0) {
                    $stream.Write($responseBytes, 0, $responseBytes.Length)
                }
                $stream.Flush()
            }
        } catch [System.IO.EndOfStreamException] {
            # A tunnel can close between requests. Keep serving until the
            # explicit shutdown control frame arrives.
        } catch [System.IO.IOException] {
            # A timed-out caller may close while the game finishes its reply.
        } finally {
            $client.Dispose()
        }
    }
} finally {
    $listener.Stop()
}
