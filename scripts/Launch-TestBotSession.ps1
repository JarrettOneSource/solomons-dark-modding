param(
    [string]$Preset = "map_create_fire_mind"
)

Get-Process SolomonDark* -ErrorAction SilentlyContinue | Stop-Process -Force
Remove-Item "runtime/stage/.sdmod/logs/solomondarkmodloader.log" -ErrorAction SilentlyContinue

$env:SDMOD_UI_SANDBOX_PRESET = $Preset
$sandboxPresetPath = Join-Path $PSScriptRoot "..\\mods\\lua_ui_sandbox_lab\\config\\active_preset.txt"
Set-Content -Path $sandboxPresetPath -Value $Preset -Encoding ASCII

Remove-Item Env:SDMOD_TEST_AUTOSPAWN_BOT -ErrorAction SilentlyContinue
Remove-Item Env:SDMOD_TEST_AUTOSPAWN_BOT_WIZARD_ID -ErrorAction SilentlyContinue
Remove-Item Env:SDMOD_TEST_AUTOSPAWN_BOT_TRACE -ErrorAction SilentlyContinue
Remove-Item Env:SDMOD_EXPERIMENTAL_REMOTE_WIZARD_SPAWN -ErrorAction SilentlyContinue

$process = Start-Process `
    -FilePath "dist\\launcher\\SolomonDarkModLauncher.exe" `
    -ArgumentList "launch" `
    -WorkingDirectory "dist\\launcher" `
    -PassThru

Write-Output $process.Id
