# Starts the Training Readiness app on localhost. Run from anywhere.
$root = Split-Path -Parent $PSScriptRoot
Set-Location (Join-Path $root "backend")
& (Join-Path $root ".venv\Scripts\python.exe") -m app.main *>> (Join-Path $root "data\app.log")
