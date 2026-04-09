param(
    [Parameter(Mandatory = $true)]
    [string]$ImagePath,
    [switch]$Detailed
)

$ErrorActionPreference = "Stop"

Add-Type -AssemblyName System.Runtime.WindowsRuntime

$null = [Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics.Imaging, ContentType = WindowsRuntime]
$null = [Windows.Media.Ocr.OcrEngine, Windows.Media.Ocr, ContentType = WindowsRuntime]

function Await-WinRtTask {
    param(
        [Parameter(Mandatory = $true)] $Operation,
        [Parameter(Mandatory = $true)] [Type] $ResultType
    )

    $asTask = ([System.WindowsRuntimeSystemExtensions].GetMethods() |
        Where-Object {
            $_.Name -eq "AsTask" -and
            $_.IsGenericMethod -and
            $_.GetParameters().Count -eq 1
        } |
        Select-Object -First 1).MakeGenericMethod($ResultType)

    $task = $asTask.Invoke($null, @($Operation))
    $task.Wait()
    $task.Result
}

$resolvedPath = (Resolve-Path $ImagePath).Path
$file = Await-WinRtTask ([Windows.Storage.StorageFile]::GetFileFromPathAsync($resolvedPath)) ([Windows.Storage.StorageFile])
$stream = Await-WinRtTask ($file.OpenAsync([Windows.Storage.FileAccessMode]::Read)) ([Windows.Storage.Streams.IRandomAccessStream])
$decoder = Await-WinRtTask ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
$bitmap = Await-WinRtTask ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()

if ($null -eq $engine) {
    throw "Windows OCR engine was not available for the current user profile languages."
}

$result = Await-WinRtTask ($engine.RecognizeAsync($bitmap)) ([Windows.Media.Ocr.OcrResult])

if (-not $Detailed) {
    $result.Text
    return
}

foreach ($line in $result.Lines) {
    $rect = $line.BoundingRect
    Write-Output ("LINE [{0},{1},{2},{3}] {4}" -f $rect.X, $rect.Y, $rect.Width, $rect.Height, $line.Text)

    foreach ($word in $line.Words) {
        $wordRect = $word.BoundingRect
        Write-Output ("WORD [{0},{1},{2},{3}] {4}" -f $wordRect.X, $wordRect.Y, $wordRect.Width, $wordRect.Height, $word.Text)
    }
}
