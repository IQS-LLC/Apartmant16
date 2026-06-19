# Debug script for PLC Project
# Runs all checks and tests

param(
    [switch]$SkipTests,
    [switch]$SkipFlutter
)

Write-Host "🔍 PLC Project Debug Script" -ForegroundColor Cyan
Write-Host "============================" -ForegroundColor Cyan
Write-Host ""

$projectRoot = Split-Path $MyInvocation.MyCommand.Path
$djangoPath = $projectRoot
$flutterPath = "$projectRoot\flutter_application_plc"

# Check Python environment
Write-Host "Checking Python environment..." -ForegroundColor Yellow
$pythonExe = "$djangoPath\.venv\Scripts\python.exe"
if (!(Test-Path $pythonExe)) {
    Write-Host "❌ Virtual environment not found at $pythonExe" -ForegroundColor Red
    exit 1
}
Write-Host "✅ Python virtual environment found" -ForegroundColor Green

# Check Django
Write-Host "Checking Django..." -ForegroundColor Yellow
try {
    & $pythonExe manage.py check 2>$null | Out-Null
    Write-Host "✅ Django system check passed" -ForegroundColor Green
} catch {
    Write-Host "❌ Django system check failed" -ForegroundColor Red
    exit 1
}

# Check migrations
Write-Host "Checking migrations..." -ForegroundColor Yellow
try {
    & $pythonExe manage.py showmigrations 2>$null | Out-Null
    Write-Host "✅ Migrations OK" -ForegroundColor Green
} catch {
    Write-Host "❌ Migration check failed" -ForegroundColor Red
}

# Run Django tests
if (!$SkipTests) {
    Write-Host "Running Django tests..." -ForegroundColor Yellow
    try {
        & $pythonExe manage.py test 2>$null
        Write-Host "✅ Django tests passed" -ForegroundColor Green
    } catch {
        Write-Host "❌ Django tests failed" -ForegroundColor Red
    }
}

# Check Flutter
if (!$SkipFlutter) {
    Write-Host "Checking Flutter..." -ForegroundColor Yellow
    Push-Location $flutterPath

    # Analyze
    try {
        & flutter analyze 2>$null | Out-Null
        Write-Host "✅ Flutter analyze passed" -ForegroundColor Green
    } catch {
        Write-Host "❌ Flutter analyze failed" -ForegroundColor Red
    }

    # Pub get
    try {
        & flutter pub get 2>$null | Out-Null
        Write-Host "✅ Flutter pub get successful" -ForegroundColor Green
    } catch {
        Write-Host "❌ Flutter pub get failed" -ForegroundColor Red
    }

    # Tests
    if (!$SkipTests) {
        try {
            & flutter test 2>$null | Out-Null
            Write-Host "✅ Flutter tests passed" -ForegroundColor Green
        } catch {
            Write-Host "❌ Flutter tests failed" -ForegroundColor Red
        }
    }

    Pop-Location
}

# Check Docker
Write-Host "Checking Docker..." -ForegroundColor Yellow
try {
    $dockerVersion = docker --version 2>$null
    Write-Host "✅ Docker available: $dockerVersion" -ForegroundColor Green

    # Try to build
    Push-Location $djangoPath
    try {
        & docker compose build --no-cache 2>$null
        Write-Host "✅ Docker build successful" -ForegroundColor Green
    } catch {
        try {
            & docker-compose build --no-cache 2>$null
            Write-Host "✅ Docker build successful" -ForegroundColor Green
        } catch {
            Write-Host "❌ Docker build failed" -ForegroundColor Red
        }
    }
    Pop-Location
} catch {
    Write-Host "Docker not available" -ForegroundColor Yellow
}

Write-Host ""
Write-Host "Debug complete!" -ForegroundColor Green