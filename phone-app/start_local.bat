@echo off
REM Simple launcher - start Django + Flutter
REM Django runs in background, Flutter in foreground

setlocal enabledelayedexpansion

cd /d %~dp0

echo.
echo ===================================
echo PLC Demo - Android Launcher
echo ===================================
echo.
echo Step 1: Starting Django backend...
echo.

REM Start Django in a separate window (minimized)
start "Django Server" /min cmd /c "cd %cd% && call .venv\Scripts\activate.bat && python manage.py migrate 2>nul && python manage.py runserver 0.0.0.0:8000"

REM Wait for Django to be ready
echo Waiting for Django to start...
timeout /t 3 /nobreak

echo.
echo Step 2: Checking for Android devices...
echo.

cd flutter_application_plc

REM Show available devices
flutter devices

echo.
echo IMPORTANT: If no device is shown above:
echo   1. Open Android Studio
echo   2. Start an Android emulator (or connect a real phone)
echo   3. Then press any key to continue
echo.
pause

REM Make sure we have the right endpoint
echo Configuring Flutter for local emulator (10.0.2.2:8000)...

REM Run Flutter (this stays in foreground)
echo.
echo ===================================
echo STARTING APP
echo ===================================
echo.

flutter run

echo.
echo App closed. Django is still running in background.
echo Type: tasklist ^| findstr python  (to see Django)
echo Type: taskkill /F /IM python.exe  (to stop Django)
echo.
pause
