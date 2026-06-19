param(
    [string]$Mode = "",
    [string]$IP = "",
    [switch]$UseDocker,
    [switch]$SkipFlutter,
    [switch]$Debug
)

# PLC Project Launcher
# Interactive launcher for Django backend and Flutter frontend

$projectRoot = Split-Path $MyInvocation.MyCommand.Path
$djangoPath = $projectRoot
$flutterPath = "$projectRoot\flutter_application_plc"

function Write-Header {
    Write-Host ""
    Write-Host "=====================================" -ForegroundColor Cyan
    Write-Host "    PLC Project Launcher" -ForegroundColor Cyan
    Write-Host "=====================================" -ForegroundColor Cyan
    Write-Host ""
}

function Get-LocalIP {
    $ip = (Get-NetIPAddress | Where-Object { $_.AddressFamily -eq "IPv4" -and $_.InterfaceAlias -notlike "*Loopback*" } | Select-Object -First 1).IPAddress
    return $ip
}

function Check-Emulator {
    $emulatorRunning = $false
    try {
        $devices = & flutter devices 2>$null | Select-String "emulator"
        if ($devices) { $emulatorRunning = $true }
    } catch {}
    return $emulatorRunning
}

function Check-Docker {
    try {
        $dockerVersion = docker --version 2>$null
        return $true
    } catch {
        return $false
    }
}

function Start-Django {
    param([string]$ip = "0.0.0.0", [int]$port = 8000, [bool]$useDocker = $false)

    if ($useDocker) {
        Write-Host "Starting Django with Docker..." -ForegroundColor Green
        Push-Location $djangoPath

        # Try new docker compose syntax first, fall back to old
        try {
            & docker compose up -d django 2>$null
        } catch {
            try {
                & docker-compose up -d django 2>$null
            } catch {
                Write-Host "Docker Compose not available. Please install Docker Desktop." -ForegroundColor Red
                return $false
            }
        }

        Pop-Location
    } else {
        Write-Host "Starting Django locally..." -ForegroundColor Green
        Push-Location $djangoPath

        $pythonExe = "$djangoPath\.venv\Scripts\python.exe"
        if (!(Test-Path $pythonExe)) {
            Write-Host "Virtual environment not found. Please run: python -m venv .venv && .venv\Scripts\activate && pip install -r requirements.txt" -ForegroundColor Red
            return $false
        }

        # Run migrations
        & $pythonExe manage.py migrate 2>$null | Out-Null

        # Start server
        $serverCmd = "$pythonExe manage.py runserver ${ip}:$port"
        if ($Debug) {
            Write-Host "Debug mode: Running Django in foreground" -ForegroundColor Yellow
            & $pythonExe manage.py runserver ${ip}:$port
        } else {
            Write-Host "Starting Django server on ${ip}:$port" -ForegroundColor Green
            Start-Process -FilePath $pythonExe -ArgumentList "manage.py", "runserver", "${ip}:$port" -NoNewWindow
        }

        Pop-Location
    }
    return $true
}

function Start-Flutter {
    param([string]$apiEndpoint)

    Write-Host "Starting Flutter app..." -ForegroundColor Green
    Push-Location $flutterPath

    # Configure API endpoint
    $mainDart = "lib/main.dart"
    if (Test-Path $mainDart) {
        # This is a simple replacement - in real app, might need more sophisticated config
        $content = Get-Content $mainDart -Raw
        $newContent = $content -replace 'http://[^:]+:8000', $apiEndpoint
        Set-Content $mainDart $newContent
    }

    if ($Debug) {
        & flutter run --debug
    } else {
        & flutter run
    }

    Pop-Location
}

# Main logic
Write-Header

# Auto-detect capabilities
$hasDocker = Check-Docker
$emulatorRunning = Check-Emulator
$localIP = Get-LocalIP

Write-Host "System Detection:" -ForegroundColor Yellow
Write-Host "  Docker available: $hasDocker"
Write-Host "  Emulator running: $emulatorRunning"
Write-Host "  Local IP: $localIP"
Write-Host ""

# Interactive mode if no parameters
if ($Mode -eq "") {
    Write-Host "Select mode:" -ForegroundColor Yellow
    Write-Host "  1. Local (Android Emulator)"
    Write-Host "  2. LAN (Real device on same network)"
    Write-Host "  3. Custom IP"
    Write-Host "  4. Docker mode"
    $choice = Read-Host "Enter choice (1-4)"

    switch ($choice) {
        "1" { $Mode = "local" }
        "2" { $Mode = "lan" }
        "3" { $Mode = "custom" }
        "4" { $Mode = "docker"; $UseDocker = $true }
        default { Write-Host "Invalid choice" -ForegroundColor Red; exit }
    }
}

# Determine IP and endpoint
$apiEndpoint = ""
switch ($Mode) {
    "local" {
        if ($emulatorRunning) {
            $apiEndpoint = "http://10.0.2.2:8000"
            Write-Host "Using emulator endpoint: $apiEndpoint" -ForegroundColor Green
        } else {
            Write-Host "No emulator detected. Starting anyway..." -ForegroundColor Yellow
            $apiEndpoint = "http://127.0.0.1:8000"
        }
    }
    "lan" {
        $apiEndpoint = "http://$localIP`:8000"
        Write-Host "Using LAN endpoint: $apiEndpoint" -ForegroundColor Green
        Write-Host "Make sure your device is on the same WiFi network!" -ForegroundColor Yellow
    }
    "custom" {
        if ($IP -eq "") {
            $IP = Read-Host "Enter custom IP address"
        }
        $apiEndpoint = "http://$IP`:8000"
        Write-Host "Using custom endpoint: $apiEndpoint" -ForegroundColor Green
    }
    "docker" {
        $apiEndpoint = "http://127.0.0.1:8000"
        Write-Host "Using Docker endpoint: $apiEndpoint" -ForegroundColor Green
    }
}

# Ask about Docker if not specified
if (!$UseDocker -and $hasDocker -and $Mode -ne "docker") {
    $useDockerChoice = Read-Host "Use Docker for Django? (y/n)"
    if ($useDockerChoice -eq "y") { $UseDocker = $true }
}

# Start Django
$djangoStarted = Start-Django -ip ($apiEndpoint -replace "http://", "" -replace ":8000", "") -useDocker $UseDocker
if (!$djangoStarted) {
    Write-Host "Failed to start Django" -ForegroundColor Red
    exit 1
}

# Wait a bit for Django to start
Start-Sleep -Seconds 3

# Start Flutter if not skipped
if (!$SkipFlutter) {
    Start-Flutter -apiEndpoint $apiEndpoint
} else {
    Write-Host "Django started. Flutter skipped." -ForegroundColor Green
    Write-Host "API available at: $apiEndpoint" -ForegroundColor Cyan
    Read-Host "Press Enter to exit"
}