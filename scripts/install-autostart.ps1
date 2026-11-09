# Registers a scheduled task that starts the app when you log in to Windows (T5).
# Run once from PowerShell:  .\scripts\install-autostart.ps1
# Remove again with:         Unregister-ScheduledTask -TaskName "TrainingReadiness"
$root = Split-Path -Parent $PSScriptRoot
New-Item -ItemType Directory -Force -Path (Join-Path $root "data") | Out-Null
$script = Join-Path $PSScriptRoot "start.ps1"
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$script`""
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero)
Register-ScheduledTask -TaskName "TrainingReadiness" -Action $action -Trigger $trigger -Settings $settings -Force
Start-ScheduledTask -TaskName "TrainingReadiness"
Write-Host "Installed. The app starts at login and is running now on http://127.0.0.1:8000"
