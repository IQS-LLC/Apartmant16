@echo off
REM Quick launcher for LAN (real phone on same WiFi)
REM ============================================

echo.
echo === PLC Demo - LAN Launcher ===
echo Scenario: Real phone on same WiFi
echo.

for /f "tokens=2 delims=:" %%a in ('ipconfig ^| findstr /i "IPv4"') do (
    set IP=%%a
)

set "IP=%IP: =%"

echo Your PC IP: %IP%
echo.
echo The Flutter app will connect to: http://%IP%:8000
echo.
echo Make sure your phone is on the SAME WiFi network!
echo.
pause

PowerShell -ExecutionPolicy Bypass -File "%~dp0start_demo.ps1" -Scenario "LAN" -ApiEndpoint "http://%IP%:8000"
