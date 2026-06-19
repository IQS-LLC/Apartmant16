# PLC Demo - Just start Django, Flutter finds it
# This is a simple helper - not complex automation

$projectRoot = Split-Path $MyInvocation.MyCommand.Path
$djangoPath = $projectRoot
$flutterPath = "$projectRoot\flutter_application_plc"

Write-Host ""
Write-Host "PLC Demo Launcher" -ForegroundColor Cyan
Write-Host "==================" -ForegroundColor Cyan
Write-Host ""

Write-Host "Starting Django backend..." -ForegroundColor Green
Write-Host ""

Push-Location $djangoPath

$pythonExe = "$djangoPath\.venv\Scripts\python.exe"

# Start Django directly (doesn't auto-close)
& $pythonExe manage.py migrate 2>$null | Out-Null
& $pythonExe manage.py runserver 0.0.0.0:8000
