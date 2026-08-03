param(
    [string]$Preset = "map_create_fire_mind",
    [switch]$EnableAudio
)

$audioEnabled = $EnableAudio -or $env:SDMOD_ENABLE_AUDIO -eq "1"
$root = Split-Path -Parent $PSScriptRoot
$launcher = Join-Path $root "dist\launcher\SolomonDarkModLauncher.exe"
$stagedReleaseLoaderAssertion =
    Join-Path $PSScriptRoot "Assert-StagedReleaseLoader.ps1"
. $stagedReleaseLoaderAssertion
Assert-StagedReleaseLoader `
    -Path (Join-Path (Split-Path -Parent $launcher) "SolomonDarkModLoader.dll") |
    Out-Null

Get-Process SolomonDark* -ErrorAction SilentlyContinue | Stop-Process -Force
Remove-Item "runtime/stage/.sdmod/logs/solomondarkmodloader.log" -ErrorAction SilentlyContinue

$env:SDMOD_UI_SANDBOX_PRESET = $Preset
$sandboxPresetPath = Join-Path $PSScriptRoot "..\\mods\\lua_ui_sandbox_lab\\config\\active_preset.txt"
Set-Content -Path $sandboxPresetPath -Value $Preset -Encoding ASCII

Remove-Item Env:SDMOD_TEST_AUTOSPAWN_BOT -ErrorAction SilentlyContinue
Remove-Item Env:SDMOD_TEST_AUTOSPAWN_BOT_WIZARD_ID -ErrorAction SilentlyContinue
Remove-Item Env:SDMOD_TEST_AUTOSPAWN_BOT_TRACE -ErrorAction SilentlyContinue
Remove-Item Env:SDMOD_EXPERIMENTAL_REMOTE_WIZARD_SPAWN -ErrorAction SilentlyContinue

$launchArguments = @("launch")
if (-not $audioEnabled) {
    $launchArguments += "--disable-audio"
}

$process = Start-Process `
    -FilePath $launcher `
    -ArgumentList $launchArguments `
    -WorkingDirectory (Split-Path -Parent $launcher) `
    -PassThru

Write-Output $process.Id
